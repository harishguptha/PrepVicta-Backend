import asyncio
import asyncpg
from datetime import date, timedelta
from openai import AsyncOpenAI

from app.config import get_settings


async def _get_prediction_engine(user_id: str, pool: asyncpg.Pool) -> dict:
    row = await pool.fetchrow(
        """
        SELECT
            COUNT(*) FILTER (WHERE is_done = false) AS remaining,
            COUNT(*) FILTER (WHERE is_done = true AND completed_at >= NOW() - INTERVAL '7 days') AS done_last_7,
            MAX(plan_date) AS exam_date
        FROM prepvicta_data.student_planner_tasks
        WHERE user_id = $1
        """,
        user_id,
    )
    if not row or not row["exam_date"]:
        return {"estimated_completion": None, "exam_date": None, "buffer_days": None, "remaining_tasks": 0}

    today = date.today()
    remaining = int(row["remaining"] or 0)
    done_last_7 = int(row["done_last_7"] or 0)
    exam_date: date = row["exam_date"]

    avg_daily = done_last_7 / 7
    if avg_daily > 0:
        days_needed = remaining / avg_daily
        est_completion = today + timedelta(days=int(days_needed))
    else:
        est_completion = exam_date

    buffer_days = (exam_date - est_completion).days

    return {
        "estimated_completion": est_completion.isoformat(),
        "exam_date": exam_date.isoformat(),
        "buffer_days": buffer_days,
        "remaining_tasks": remaining,
    }


async def _get_at_risk_subjects(user_id: str, pool: asyncpg.Pool) -> list[dict]:
    rows = await pool.fetch(
        """
        SELECT
            CASE WHEN tt.subject IN ('Botany','Zoology') THEN 'Biology' ELSE tt.subject END AS subject,
            ROUND(AVG(ra.score::float / NULLIF(ra.total, 0)) * 100)::int AS avg_pct,
            COUNT(*) AS attempt_count
        FROM prepvicta_data.revision_attempt ra
        JOIN prepvicta_data.task_topic tt ON tt.chapter = ra.chapter
        WHERE ra.user_id = $1::uuid AND ra.total > 0
        GROUP BY CASE WHEN tt.subject IN ('Botany','Zoology') THEN 'Biology' ELSE tt.subject END
        ORDER BY avg_pct
        """,
        user_id,
    )
    at_risk = []
    for r in rows:
        pct = int(r["avg_pct"] or 0)
        if pct < 70:
            level = "CRITICAL" if pct < 50 else "WARNING"
            issue = "Needs immediate revision" if pct < 50 else "Retention below 70% target"
            at_risk.append({
                "subject": r["subject"],
                "score": pct,
                "level": level,
                "issue": issue,
            })
    return at_risk


async def _get_ai_insight(
    user_id: str,
    subject_progress: list[dict],
    at_risk: list[dict],
    streak: int,
    pool: asyncpg.Pool,
) -> str:
    row = await pool.fetchrow(
        """
        SELECT insight FROM prepvicta_data.dashboard_ai_insight
        WHERE user_id = $1::uuid
          AND created_at >= NOW() - INTERVAL '6 hours'
        """,
        user_id,
    )
    if row:
        return row["insight"]

    try:
        settings = get_settings()
        client = AsyncOpenAI(api_key=settings.openai_api_key, timeout=settings.openai_timeout_seconds)

        lines = []
        if subject_progress:
            for s in subject_progress:
                lines.append(f"{s['subject']}: {s['completed']}/{s['total']} topics done ({s['percentage']}%)")
        if at_risk:
            risk_names = ", ".join(r["subject"] for r in at_risk)
            lines.append(f"At-risk subjects: {risk_names}")
        if streak > 0:
            lines.append(f"Study streak: {streak} day(s)")
        context = "; ".join(lines) if lines else "Student just started — no progress recorded yet"

        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a NEET exam coach. Write ONE specific, punchy sentence under 15 words. "
                        "Reference the actual subject or number from the data. No generic advice."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Data: {context}. Write one actionable tip.",
                },
            ],
            temperature=0.8,
            max_tokens=40,
        )
        raw = (response.choices[0].message.content or "").strip().strip('"').strip("'")
        insight = raw.split('.')[0].strip() + '.' if '.' in raw else raw

        await pool.execute(
            """
            INSERT INTO prepvicta_data.dashboard_ai_insight (user_id, insight)
            VALUES ($1::uuid, $2)
            ON CONFLICT (user_id) DO UPDATE SET insight = EXCLUDED.insight, created_at = NOW()
            """,
            user_id, insight,
        )
        return insight
    except Exception:
        return "Keep going — every topic studied brings you closer to your NEET goal."


async def _get_accomplishments(user_id: str, streak: int, pool: asyncpg.Pool) -> list[dict]:
    achievements = []

    # 1. Streak badge
    if streak >= 7:
        achievements.append({
            "icon": "🏆", "title": "Consistency King",
            "desc": f"{streak}-day study streak — incredible discipline!",
        })
    elif streak >= 3:
        achievements.append({
            "icon": "🔥", "title": f"{streak}-Day Streak",
            "desc": f"Studied {streak} days in a row — keep it going!",
        })

    # 2. Topics studied this week
    week_row = await pool.fetchrow(
        """
        SELECT COUNT(*) AS cnt
        FROM prepvicta_data.topic_progress
        WHERE user_id = $1::uuid AND viewed_at >= NOW() - INTERVAL '7 days'
        """,
        user_id,
    )
    topics_week = int(week_row["cnt"] or 0)
    if topics_week >= 15:
        achievements.append({
            "icon": "📚", "title": "Topic Crusher",
            "desc": f"{topics_week} topics covered this week — phenomenal pace!",
        })
    elif topics_week >= 5:
        achievements.append({
            "icon": "📖", "title": "Active Learner",
            "desc": f"{topics_week} new topics studied this week.",
        })
    elif topics_week >= 1:
        achievements.append({
            "icon": "🌱", "title": "Learning Started",
            "desc": f"{topics_week} topic{'s' if topics_week > 1 else ''} covered this week.",
        })

    # 3. Best quiz score this week
    quiz_row = await pool.fetchrow(
        """
        SELECT chapter, score, total,
               ROUND((score::float / NULLIF(total, 0)) * 100) AS pct
        FROM prepvicta_data.revision_attempt
        WHERE user_id = $1::uuid AND total > 0
          AND attempted_at >= NOW() - INTERVAL '7 days'
        ORDER BY pct DESC LIMIT 1
        """,
        user_id,
    )
    if quiz_row and int(quiz_row["pct"] or 0) >= 80:
        achievements.append({
            "icon": "🎯", "title": "Quiz Champion",
            "desc": f"Scored {int(quiz_row['pct'])}% in {quiz_row['chapter']}!",
        })
    elif quiz_row and int(quiz_row["pct"] or 0) >= 60:
        achievements.append({
            "icon": "✅", "title": "Quiz Cleared",
            "desc": f"{int(quiz_row['pct'])}% in {quiz_row['chapter']} — aim for 80%+!",
        })

    # 4. Fallback for brand-new users
    if not achievements:
        total_row = await pool.fetchrow(
            "SELECT COUNT(*) AS cnt FROM prepvicta_data.topic_progress WHERE user_id = $1::uuid",
            user_id,
        )
        total = int(total_row["cnt"] or 0)
        if total > 0:
            achievements.append({
                "icon": "🚀", "title": "First Steps",
                "desc": f"{total} topic{'s' if total > 1 else ''} studied so far — great start!",
            })
        else:
            achievements.append({
                "icon": "🎓", "title": "Ready to Begin",
                "desc": "Open Learning Center and study your first topic to earn badges.",
            })

    return achievements[:3]


async def _get_readiness_score(user_id: str, pool: asyncpg.Pool) -> dict:
    row = await pool.fetchrow(
        """
        SELECT
            SUM(score)           AS total_correct,
            SUM(total)           AS total_questions,
            SUM(total - score)   AS total_wrong
        FROM prepvicta_data.revision_attempt
        WHERE user_id = $1::uuid AND total > 0
        """,
        user_id,
    )
    if not row or not row["total_questions"]:
        return {"score": None, "label": None, "top_pct": None, "best_subject": None}

    correct  = int(row["total_correct"]   or 0)
    wrong    = int(row["total_wrong"]     or 0)
    total_q  = int(row["total_questions"] or 0)
    neet_score = correct * 4 - wrong
    max_score  = total_q * 4
    pct = max(0, min(100, round((neet_score / max_score) * 100) if max_score else 0))

    if pct >= 85:   label = "Excellent"
    elif pct >= 70: label = "Strong"
    elif pct >= 55: label = "Good"
    elif pct >= 40: label = "Average"
    else:           label = "Needs Work"

    # What percentile is this user among all test-takers?
    pct_row = await pool.fetchrow(
        """
        WITH user_scores AS (
            SELECT
                user_id,
                GREATEST(0, ROUND(
                    (SUM(score) * 4 - SUM(total - score))::float
                    / NULLIF(SUM(total) * 4, 0) * 100
                )) AS score_pct
            FROM prepvicta_data.revision_attempt
            WHERE total > 0
            GROUP BY user_id
        )
        SELECT
            COUNT(*)                             AS total_users,
            COUNT(*) FILTER (WHERE score_pct < $1) AS users_below
        FROM user_scores
        """,
        pct,
    )
    total_users = int(pct_row["total_users"] or 1)
    users_below = int(pct_row["users_below"] or 0)
    top_pct = max(1, round((1 - users_below / total_users) * 100))

    # Best subject by NEET score
    best_rows = await pool.fetch(
        """
        SELECT
            CASE WHEN tt.subject IN ('Botany','Zoology') THEN 'Biology' ELSE tt.subject END AS subject,
            GREATEST(0, ROUND(
                (SUM(ra.score) * 4 - SUM(ra.total - ra.score))::float
                / NULLIF(SUM(ra.total) * 4, 0) * 100
            )) AS subject_pct
        FROM prepvicta_data.revision_attempt ra
        JOIN prepvicta_data.task_topic tt ON tt.chapter = ra.chapter
        WHERE ra.user_id = $1::uuid AND ra.total > 0
        GROUP BY CASE WHEN tt.subject IN ('Botany','Zoology') THEN 'Biology' ELSE tt.subject END
        ORDER BY subject_pct DESC
        LIMIT 1
        """,
        user_id,
    )
    best_subject = best_rows[0]["subject"] if best_rows else None

    return {"score": pct, "label": label, "top_pct": top_pct, "best_subject": best_subject}


async def get_dashboard(user_id: str, pool: asyncpg.Pool) -> dict:
    # Total topics per subject from NEET curriculum (always populated)
    total_rows = await pool.fetch(
        """
        SELECT
            CASE WHEN subject IN ('Botany','Zoology') THEN 'Biology' ELSE subject END AS subject,
            COUNT(*) AS total
        FROM prepvicta_data.task_topic
        GROUP BY CASE WHEN subject IN ('Botany','Zoology') THEN 'Biology' ELSE subject END
        ORDER BY subject
        """,
    )

    # Topics this user has actually studied in the Learning Center
    studied_rows = await pool.fetch(
        """
        SELECT
            CASE WHEN subject IN ('Botany','Zoology') THEN 'Biology' ELSE subject END AS subject,
            COUNT(*) AS done
        FROM prepvicta_data.topic_progress
        WHERE user_id = $1::uuid
        GROUP BY CASE WHEN subject IN ('Botany','Zoology') THEN 'Biology' ELSE subject END
        """,
        user_id,
    )
    studied_map = {r["subject"]: int(r["done"]) for r in studied_rows}

    subject_progress = []
    overall_total = overall_done = 0
    for r in total_rows:
        subj  = r["subject"]
        total = int(r["total"])
        done  = studied_map.get(subj, 0)
        overall_total += total
        overall_done  += done
        subject_progress.append({
            "subject":    subj,
            "total":      total,
            "completed":  done,
            "percentage": round(done / total * 100) if total else 0,
        })

    today = date.today()
    today_rows = await pool.fetch(
        """
        SELECT DISTINCT ON (chapter, topic)
            chapter, topic AS section, subject, priority,
            duration_min AS estimated_minutes, activity, is_done AS completed
        FROM prepvicta_data.student_planner_tasks
        WHERE user_id = $1 AND plan_date = $2
        ORDER BY chapter, topic,
                 CASE WHEN priority LIKE '%MUST%' THEN 1 WHEN priority LIKE '%HIGH%' THEN 2 ELSE 3 END
        """,
        user_id, today,
    )
    today_tasks = [
        {
            "chapter": r["chapter"], "section": r["section"],
            "subject": r["subject"], "priority": r["priority"],
            "estimated_minutes": r["estimated_minutes"],
            "activity": r["activity"], "completed": r["completed"],
        }
        for r in today_rows
    ]

    streak_rows = await pool.fetch(
        """
        SELECT DISTINCT DATE(completed_at) AS day
        FROM prepvicta_data.student_planner_tasks
        WHERE user_id = $1 AND is_done = true AND completed_at IS NOT NULL
        ORDER BY day DESC LIMIT 30
        """,
        user_id,
    )
    streak = 0
    check = today
    for r in streak_rows:
        if r["day"] == check:
            streak += 1
            check = check - timedelta(days=1)
        else:
            break

    recent_rows = await pool.fetch(
        """
        SELECT DISTINCT ON (chapter, topic) chapter, topic AS section, subject, completed_at
        FROM prepvicta_data.student_planner_tasks
        WHERE user_id = $1 AND is_done = true AND completed_at IS NOT NULL
        ORDER BY chapter, topic, completed_at DESC
        LIMIT 5
        """,
        user_id,
    )
    recent = [
        {
            "chapter": r["chapter"], "section": r["section"],
            "subject": r["subject"], "completed_at": r["completed_at"].isoformat(),
        }
        for r in recent_rows
    ]

    prediction, at_risk, readiness, accomplishments = await asyncio.gather(
        _get_prediction_engine(user_id, pool),
        _get_at_risk_subjects(user_id, pool),
        _get_readiness_score(user_id, pool),
        _get_accomplishments(user_id, streak, pool),
    )
    ai_insight = await _get_ai_insight(user_id, subject_progress, at_risk, streak, pool)

    return {
        "subject_progress": subject_progress,
        "overall": {
            "total": overall_total, "completed": overall_done,
            "percentage": round(overall_done / overall_total * 100) if overall_total else 0,
        },
        "today_tasks": today_tasks,
        "streak_days": streak,
        "recent_completions": recent,
        "prediction_engine": prediction,
        "at_risk_subjects": at_risk,
        "readiness_score": readiness,
        "accomplishments": accomplishments,
        "ai_insight": ai_insight,
    }
