import json
import os
import uuid
from collections import deque
from datetime import date, timedelta
from typing import Any

import asyncpg
from dotenv import load_dotenv
from openai import AsyncOpenAI

from app.data.neet_syllabus import SYLLABUS_SYSTEM_PROMPT
from app.schemas.planning import DailyGeneratedTasks, PlanningAgentRequest, PlanningAgentResponse, PlanMetadata, StudyTask

load_dotenv()

DEFAULT_MODEL = os.getenv("OPENAI_PLANNING_MODEL", "gpt-4o-mini")

_HOURS_TO_NUMERIC = {"1-2 hrs": 1.5, "2-4 hrs": 3.0, "4-6 hrs": 5.0, "6+ hrs": 7.0}
_CONFIDENCE_TO_INT = {"Low": 1, "Medium": 2, "High": 3}


def first_sunday_of_may(year: int) -> date:
    current = date(year, 5, 1)
    days_until_sunday = (6 - current.weekday()) % 7
    return current + timedelta(days=days_until_sunday)


def _daily_minutes(hours_label: str) -> int:
    return {"1-2 hrs": 90, "2-4 hrs": 180, "4-6 hrs": 300, "6+ hrs": 420}[hours_label]


def _tasks_per_day(hours_label: str) -> int:
    return {"1-2 hrs": 2, "2-4 hrs": 3, "4-6 hrs": 4, "6+ hrs": 5}[hours_label]


def _priority_rank(priority: str) -> int:
    if "MUST DO" in priority:
        return 3
    if "HIGH" in priority:
        return 2
    return 1


def _class_stage_bonus(class_stage: str, class_level: int) -> int:
    if class_stage == "Repeater":
        return 3 if class_level == 12 else 2
    if class_stage == "Class 12":
        return 4 if class_level == 12 else 1
    return 4 if class_level == 11 else 1


def _subject_cycle(payload: PlanningAgentRequest) -> deque[str]:
    weights = {"Biology": 4, "Chemistry": 2, "Physics": 2}
    weights[payload.weakest_subject] += 2
    weights[payload.strongest_subject] = max(1, weights[payload.strongest_subject] - 1)
    cycle: list[str] = []
    for subject, weight in weights.items():
        cycle.extend([subject] * weight)
    return deque(cycle)


async def _fetch_topics_from_db(pool: asyncpg.Pool) -> list[dict[str, Any]]:
    rows = await pool.fetch("""
        SELECT
            CASE WHEN subject IN ('Botany', 'Zoology') THEN 'Biology' ELSE subject END AS subject,
            chapter,
            topic,
            priority,
            CAST(REPLACE(class, 'Class ', '') AS INTEGER) AS class_level,
            COALESCE(pyq_qs, 2) AS pyq_qs,
            COALESCE(weight_pct, 4) AS weight_pct
        FROM task_topic
        ORDER BY subject, chapter, topic
    """)
    return [dict(r) for r in rows]


def _build_topic_queues(
    payload: PlanningAgentRequest,
    topic_rows: list[dict[str, Any]],
) -> dict[str, deque[dict[str, Any]]]:
    queues: dict[str, list[dict[str, Any]]] = {"Biology": [], "Chemistry": [], "Physics": []}
    chapter_index: dict[tuple[str, str], int] = {}

    for row in topic_rows:
        subject = row["subject"]
        chapter = row["chapter"]
        key = (subject, chapter)
        topic_index = chapter_index.get(key, 0)
        chapter_index[key] = topic_index + 1

        chapter_score = (
            _priority_rank(row["priority"]) * 100
            + row["pyq_qs"] * 10
            + row["weight_pct"]
            + _class_stage_bonus(payload.current_class_stage, row["class_level"])
        )
        if subject == payload.weakest_subject:
            chapter_score += 30
        if subject == payload.strongest_subject:
            chapter_score -= 10

        queues[subject].append({
            "subject": subject,
            "chapter": chapter,
            "topic": row["topic"],
            "priority": row["priority"],
            "score": chapter_score - topic_index,
            "round": 1,
        })

    return {
        s: deque(sorted(tasks, key=lambda t: t["score"], reverse=True))
        for s, tasks in queues.items()
    }


def _activity_for(subject: str, round_number: int) -> str:
    if round_number > 1:
        if subject == "Biology":
            return "Revision: NCERT reread, diagrams, and 30 PYQ/MCQ questions."
        if subject == "Chemistry":
            return "Revision: formulas/reactions/facts plus 25 timed questions."
        return "Revision: formula sheet plus 25 numerical/PYQ questions."
    if subject == "Biology":
        return "NCERT line-by-line study, diagram recall, and 25 chapter MCQs."
    if subject == "Chemistry":
        return "Concept notes, NCERT examples, reaction/formula drill, and 20 MCQs."
    return "Concept study, formula derivation, solved examples, and 15 numericals."


def _next_task(
    queues: dict[str, deque[dict[str, Any]]],
    base_queues: dict[str, list[dict[str, Any]]],
    subject_cycle: deque[str],
    estimated_minutes: int,
) -> StudyTask:
    for _ in range(len(subject_cycle)):
        subject = subject_cycle[0]
        subject_cycle.rotate(-1)
        if queues[subject]:
            raw = queues[subject].popleft()
            return StudyTask(
                subject=raw["subject"],
                chapter=raw["chapter"],
                topic=raw["topic"],
                priority=raw["priority"],
                estimated_minutes=estimated_minutes,
                activity=_activity_for(raw["subject"], raw["round"]),
            )

    for subject in queues:
        queues[subject] = deque(
            {**t, "round": t["round"] + 1, "score": t["score"] - 20}
            for t in sorted(base_queues[subject], key=lambda t: t["score"], reverse=True)
        )
    return _next_task(queues, base_queues, subject_cycle, estimated_minutes)


def _generate_schedule(
    payload: PlanningAgentRequest,
    topic_rows: list[dict[str, Any]],
    start_date: date,
    plan_end_date: date,
) -> list[DailyGeneratedTasks]:
    plan_days = (plan_end_date - start_date).days + 1
    if plan_days <= 0:
        raise ValueError(
            f"Cannot generate a plan ending on {plan_end_date.isoformat()} because it is before {start_date.isoformat()}."
        )

    tasks_count = _tasks_per_day(payload.daily_study_hours)
    estimated_minutes = max(30, _daily_minutes(payload.daily_study_hours) // tasks_count)
    queues = _build_topic_queues(payload, topic_rows)
    base_queues = {s: list(tasks) for s, tasks in queues.items()}
    subject_cycle = _subject_cycle(payload)

    return [
        DailyGeneratedTasks(
            date=start_date + timedelta(days=i),
            tasks=[_next_task(queues, base_queues, subject_cycle, estimated_minutes) for _ in range(tasks_count)],
        )
        for i in range(plan_days)
    ]


async def _build_ai_guidance(
    payload: PlanningAgentRequest,
    metadata: PlanMetadata,
    first_day: DailyGeneratedTasks,
) -> tuple[str, list[str]]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return (
            "OpenAI guidance was skipped because OPENAI_API_KEY is not configured.",
            ["OPENAI_API_KEY is missing; returned deterministic planner guidance only."],
        )

    client = AsyncOpenAI(api_key=api_key)
    user_prompt = {
        "student": payload.model_dump(),
        "metadata": metadata.model_dump(mode="json"),
        "first_day_plan": first_day.model_dump(mode="json"),
        "instruction": "Write short actionable planning guidance for the student.",
    }

    try:
        response = await client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=[
                {"role": "system", "content": SYLLABUS_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(user_prompt)},
            ],
            temperature=0.2,
            max_tokens=260,
        )
        return (response.choices[0].message.content or "").strip(), []
    except Exception as exc:
        return (
            "OpenAI guidance could not be generated. Check the API key and network.",
            [f"OpenAI guidance failed: {exc.__class__.__name__}: {exc}"],
        )


async def _save_plan_to_db(
    pool: asyncpg.Pool,
    payload: PlanningAgentRequest,
    plan_id: str,
    schedule: list[DailyGeneratedTasks],
) -> None:
    user_id = payload.user_id

    # Upsert student profile
    existing = await pool.fetchval(
        "SELECT id FROM student_profiles WHERE user_id = $1", user_id
    )
    if existing:
        await pool.execute(
            """
            UPDATE student_profiles SET
                stage = $1, attempt_year = $2, daily_study_hours = $3,
                strongest_subject = $4, weakest_subject = $5, confidence = $6,
                updated_at = NOW()
            WHERE user_id = $7
            """,
            payload.current_class_stage,
            payload.neet_attempt_year,
            _HOURS_TO_NUMERIC[payload.daily_study_hours],
            payload.strongest_subject,
            payload.weakest_subject,
            _CONFIDENCE_TO_INT[payload.self_confidence_level],
            user_id,
        )
    else:
        await pool.execute(
            """
            INSERT INTO student_profiles
                (id, user_id, stage, attempt_year, daily_study_hours,
                 strongest_subject, weakest_subject, confidence,
                 onboarding_completed_at, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW(), NOW(), NOW())
            """,
            str(uuid.uuid4()),
            user_id,
            payload.current_class_stage,
            payload.neet_attempt_year,
            _HOURS_TO_NUMERIC[payload.daily_study_hours],
            payload.strongest_subject,
            payload.weakest_subject,
            _CONFIDENCE_TO_INT[payload.self_confidence_level],
        )

    # Insert all tasks
    task_rows = [
        (
            str(uuid.uuid4()),
            plan_id,
            user_id,
            task.subject,
            task.chapter,
            task.topic,
            task.activity,
            task.estimated_minutes,
            task.priority,
            "pending",
            False,
            day.date,
        )
        for day in schedule
        for task in day.tasks
    ]

    await pool.executemany(
        """
        INSERT INTO student_planner_tasks
            (id, plan_id, user_id, subject, chapter, topic, activity,
             duration_min, priority, status, is_done, plan_date, created_at, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, NOW(), NOW())
        """,
        task_rows,
    )


async def build_planning_agent_response(
    payload: PlanningAgentRequest,
    pool: asyncpg.Pool,
) -> PlanningAgentResponse:
    topic_rows = await _fetch_topics_from_db(pool)

    today_date = date.today()
    exam_date = first_sunday_of_may(payload.neet_attempt_year)
    plan_end_date = exam_date - timedelta(days=30)

    schedule = _generate_schedule(payload, topic_rows, today_date, plan_end_date)

    metadata = PlanMetadata(
        student_name=payload.full_name.strip(),
        current_class_stage=payload.current_class_stage,
        neet_attempt_year=payload.neet_attempt_year,
        neet_exam_date=exam_date,
        plan_start_date=today_date,
        plan_end_date=plan_end_date,
        days_left=(exam_date - today_date).days,
        daily_study_hours=payload.daily_study_hours,
        preferred_study_time=payload.preferred_study_time,
        strongest_subject=payload.strongest_subject,
        weakest_subject=payload.weakest_subject,
        self_confidence_level=payload.self_confidence_level,
        generated_plan_days=len(schedule),
    )

    ai_guidance, warnings = await _build_ai_guidance(payload, metadata, schedule[0])
    plan_id = str(uuid.uuid4())

    await _save_plan_to_db(pool, payload, plan_id, schedule)

    return PlanningAgentResponse(
        plan_id=plan_id,
        metadata=metadata,
        daily_schedule=schedule,
        ai_guidance=ai_guidance,
        storage_path="db",
        warnings=warnings,
    )
