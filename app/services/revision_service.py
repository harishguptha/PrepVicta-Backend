import os, json, random
from openai import AsyncOpenAI
from dotenv import load_dotenv
import asyncpg
from app.services.learn_service import get_chapter_images

load_dotenv()

_client = None

def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))
    return _client

MODEL = os.getenv("OPENAI_PLANNING_MODEL", "gpt-4o-mini")


# ── Revision summary ───────────────────────────────────────────────────────────

SUMMARY_SYSTEM = (
    "You are a NEET exam expert. Create structured, concise revision cards from textbook content. "
    "Focus only on what NEET actually tests. Return ONLY valid JSON."
)

SUMMARY_USER = """Create a revision card for NEET topic '{section}' from chapter '{chapter}'.

Textbook content:
{content}

Return a JSON object with exactly this structure:
{{
  "key_points": ["5-8 most important conceptual points a student must know"],
  "important_facts": ["specific numbers, names, or values that appear in NEET MCQs"],
  "classifications": [{{"category": "name", "items": ["item1", "item2"]}}],
  "neet_traps": ["2-4 common misconceptions or tricky distinctions students get wrong"],
  "remember": "one memorable mnemonic or hook sentence for this topic"
}}

Rules:
- key_points: 5-8 clear conceptual statements
- important_facts: only hard data (numbers, species names, chemical names, years)
- classifications: empty list [] if this topic has no classification aspect
- neet_traps: what students commonly confuse — make these specific
- remember: single sentence, catchy enough to recall in exam
- Return ONLY the JSON object, no extra text
"""


# ── Quiz ───────────────────────────────────────────────────────────────────────

QUIZ_SYSTEM = (
    "You are a NEET exam expert. Generate high-quality MCQ questions exactly matching NEET exam pattern. "
    "Each question must have exactly 4 options (A-D), one correct answer, and a clear explanation. "
    "Draw from your full NEET knowledge — the provided content is a reference, not a strict limit. "
    "Focus on facts, processes, definitions, numerical values, and common NEET traps. "
    "Return ONLY a valid JSON array."
)

QUIZ_USER = """Generate {min_q} to {max_q} NEET-style MCQ questions for topic '{section}' from chapter '{chapter}'.

Reference content:
{content}

Return a JSON array where every item has this structure:
[
  {{
    "question": "Question text here?",
    "options": ["Option A text", "Option B text", "Option C text", "Option D text"],
    "correct": 0,
    "explanation": "Why this answer is correct and others are wrong."
  }}
]

Rules:
- correct is the 0-based index of the correct option (0=A, 1=B, 2=C, 3=D)
- Generate as many questions as the topic warrants — at minimum {min_q}
- Mix difficulty: ~30% easy, ~40% medium, ~30% hard
- Include numerical values, classifications, process-based questions
- Add NEET trap questions (questions based on common misconceptions)
- Return ONLY the JSON array, nothing else
"""


def _quiz_count(priority: str) -> tuple[int, int]:
    p = priority.upper()
    if "MUST" in p:
        return 15, 20
    if "HIGH" in p:
        return 10, 14
    return 6, 10


# ── DB helpers ─────────────────────────────────────────────────────────────────

async def get_revision_summary(chapter: str, section: str, pool: asyncpg.Pool) -> dict | None:
    row = await pool.fetchrow(
        "SELECT summary FROM prepvicta_data.revision_summary WHERE chapter = $1 AND section = $2",
        chapter, section,
    )
    if row:
        data = row["summary"] if isinstance(row["summary"], dict) else json.loads(row["summary"])
        return {"chapter": chapter, "section": section, **data}
    return None


async def generate_and_store_summary(
    chapter: str, section: str, subject: str, content: str, pool: asyncpg.Pool
) -> dict:
    client = _get_client()
    response = await client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SUMMARY_SYSTEM},
            {"role": "user", "content": SUMMARY_USER.format(
                section=section, chapter=chapter, content=content[:5000]
            )},
        ],
        temperature=0.4,
        max_tokens=1500,
        response_format={"type": "json_object"},
    )
    raw = (response.choices[0].message.content or "").strip()
    try:
        summary = json.loads(raw)
    except Exception:
        raise ValueError("Failed to parse summary JSON from AI response")

    await pool.execute(
        """
        INSERT INTO prepvicta_data.revision_summary (chapter, section, subject, summary)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (chapter, section) DO UPDATE SET summary = EXCLUDED.summary
        """,
        chapter, section, subject, json.dumps(summary),
    )
    return {"chapter": chapter, "section": section, **summary}


async def get_quiz(chapter: str, section: str, pool: asyncpg.Pool) -> dict | None:
    row = await pool.fetchrow(
        "SELECT questions FROM prepvicta_data.revision_quiz WHERE chapter = $1 AND section = $2",
        chapter, section,
    )
    if row:
        qs = row["questions"] if isinstance(row["questions"], list) else json.loads(row["questions"])
        random.shuffle(qs)
        return {"chapter": chapter, "section": section, "questions": qs}
    return None


async def generate_and_store_quiz(
    subject: str, chapter: str, section: str,
    content: str, priority: str, pool: asyncpg.Pool,
) -> dict:
    client = _get_client()
    min_q, max_q = _quiz_count(priority)

    response = await client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": QUIZ_SYSTEM},
            {"role": "user", "content": QUIZ_USER.format(
                section=section, chapter=chapter,
                content=content[:5000], min_q=min_q, max_q=max_q,
            )},
        ],
        temperature=0.6,
        max_tokens=4000,
        response_format={"type": "json_object"},
    )
    raw = (response.choices[0].message.content or "").strip()
    try:
        parsed = json.loads(raw)
        questions = parsed if isinstance(parsed, list) else parsed.get("questions", parsed.get("mcqs", []))
    except Exception:
        raise ValueError("Failed to parse quiz JSON from AI response")

    await pool.execute(
        """
        INSERT INTO prepvicta_data.revision_quiz (subject, chapter, section, questions)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (chapter, section) DO UPDATE SET questions = EXCLUDED.questions
        """,
        subject, chapter, section, json.dumps(questions),
    )
    random.shuffle(questions)
    return {"chapter": chapter, "section": section, "questions": questions}


async def save_attempt(
    user_id: str, chapter: str, section: str,
    score: int, total: int, answers: list, pool: asyncpg.Pool,
) -> dict:
    await pool.execute(
        """
        INSERT INTO prepvicta_data.revision_attempt (user_id, chapter, section, score, total, answers)
        VALUES ($1, $2, $3, $4, $5, $6)
        """,
        user_id, chapter, section, score, total, json.dumps(answers),
    )

    passed = score / total >= 0.6
    if passed:
        await pool.execute(
            """
            UPDATE prepvicta_data.student_planner_tasks
            SET is_done = true, completed_at = now()
            WHERE user_id = $1 AND chapter = $2 AND topic = $3 AND is_done = false
            """,
            user_id, chapter, section,
        )

    pct = round(score / total * 100)
    if pct >= 90:
        grade, feedback = "Excellent", "Outstanding! You have mastered this topic."
        improve = []
    elif pct >= 70:
        grade, feedback = "Good", "Good understanding! A quick review will make it perfect."
        improve = ["Review the explanations for questions you got wrong."]
    elif pct >= 50:
        grade, feedback = "Average", "You have the basics. Focused revision needed."
        improve = ["Re-read the revision card.", "Focus on process-based and classification questions."]
    else:
        grade, feedback = "Needs Work", "Go back to the revision card and study it thoroughly."
        improve = ["Read the revision card again carefully.", "Pay attention to NEET traps.", "Retry the quiz after revision."]

    return {
        "score": score, "total": total, "percentage": pct,
        "grade": grade, "feedback": feedback,
        "improve": improve, "passed": passed, "topic_marked_complete": passed,
    }


_CHAPTER_QUIZ_SYSTEM = (
    "You are a NEET exam expert. Generate high-quality MCQ questions that comprehensively cover an entire textbook chapter. "
    "Questions must test all key topics at NEET difficulty. Return ONLY valid JSON."
)

_CHAPTER_QUIZ_USER = """Generate exactly 30 NEET-style MCQ questions for the chapter '{chapter}' ({subject}).

Key topics in this chapter: {topics}

Return a JSON object with this structure:
{{
  "questions": [
    {{
      "question": "Question text here?",
      "options": ["Option A text", "Option B text", "Option C text", "Option D text"],
      "correct": 0,
      "explanation": "Why this answer is correct and others are wrong.",
      "topic": "Which topic this tests",
      "image": null
    }}
  ]
}}

Rules:
- Generate EXACTLY 30 questions spread across ALL topics listed
- correct is 0-based index (0=A, 1=B, 2=C, 3=D)
- Mix difficulty: ~30% easy, ~40% medium, ~30% hard
- Cover definitions, classifications, processes, numerical values
- Set "image" to null for all questions
- Return ONLY the JSON object
"""

_CHAPTER_QUIZ_USER_WITH_IMAGES = """Generate exactly 30 NEET-style MCQ questions for the chapter '{chapter}' ({subject}).

Key topics in this chapter: {topics}

The chapter contains the following diagrams/figures (shown below). For 4-6 questions, ask about what students can observe in these diagrams.

Image reference list (use exact URLs when referencing):
{image_refs}

Return a JSON object with this structure:
{{
  "questions": [
    {{
      "question": "Question text here?",
      "options": ["Option A text", "Option B text", "Option C text", "Option D text"],
      "correct": 0,
      "explanation": "Why this answer is correct and others are wrong.",
      "topic": "Which topic this tests",
      "image": null
    }}
  ]
}}

Rules:
- Generate EXACTLY 30 questions spread across ALL topics
- correct is 0-based index (0=A, 1=B, 2=C, 3=D)
- Mix difficulty: ~30% easy, ~40% medium, ~30% hard
- For diagram-based questions: set "image" to the EXACT URL from the reference list above
- For all other questions: set "image" to null
- Include 4-6 diagram/figure-based questions using the images provided
- Return ONLY the JSON object
"""

_CHAPTER_TEST_SECTION = "__CHAPTER_TEST_v2__"


async def get_chapter_quiz(chapter: str, subject: str, pool: asyncpg.Pool) -> dict:
    row = await pool.fetchrow(
        "SELECT questions FROM prepvicta_data.revision_quiz WHERE chapter = $1 AND section = $2",
        chapter, _CHAPTER_TEST_SECTION,
    )
    if row:
        qs = row["questions"] if isinstance(row["questions"], list) else json.loads(row["questions"])
        random.shuffle(qs)
        return {"chapter": chapter, "questions": qs, "total": len(qs)}

    topics_rows = await pool.fetch(
        """
        SELECT topic FROM task_topic
        WHERE chapter = $1
          AND CASE WHEN subject IN ('Botany','Zoology') THEN 'Biology' ELSE subject END = $2
        ORDER BY weight_pct DESC NULLS LAST, pyq_qs DESC NULLS LAST
        """,
        chapter, subject,
    )
    topic_list = ", ".join(r["topic"] for r in topics_rows) if topics_rows else chapter

    # Fetch chapter images from Pinecone
    chapter_images = await get_chapter_images(chapter, subject)
    images_to_use = chapter_images[:6]  # cap to avoid token overload

    client = _get_client()

    if images_to_use:
        image_refs = "\n".join(
            f"- Section '{img['section']}': {img['url']}" for img in images_to_use
        )
        text_prompt = _CHAPTER_QUIZ_USER_WITH_IMAGES.format(
            chapter=chapter, subject=subject, topics=topic_list, image_refs=image_refs,
        )
        user_content: list | str = [{"type": "text", "text": text_prompt}]
        for img in images_to_use:
            user_content.append({"type": "text", "text": f"[Diagram — section: {img['section']}]"})
            user_content.append({"type": "image_url", "image_url": {"url": img["url"], "detail": "low"}})
        model_to_use = "gpt-4o"
    else:
        user_content = _CHAPTER_QUIZ_USER.format(
            chapter=chapter, subject=subject, topics=topic_list,
        )
        model_to_use = MODEL

    response = await client.chat.completions.create(
        model=model_to_use,
        messages=[
            {"role": "system", "content": _CHAPTER_QUIZ_SYSTEM},
            {"role": "user", "content": user_content},
        ],
        temperature=0.6,
        max_tokens=7000,
        response_format={"type": "json_object"},
    )
    raw = (response.choices[0].message.content or "").strip()
    try:
        parsed = json.loads(raw)
        questions = parsed if isinstance(parsed, list) else parsed.get("questions", [])
    except Exception:
        raise ValueError("Failed to parse chapter quiz JSON")

    await pool.execute(
        """
        INSERT INTO prepvicta_data.revision_quiz (subject, chapter, section, questions)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (chapter, section) DO UPDATE SET questions = EXCLUDED.questions
        """,
        subject, chapter, _CHAPTER_TEST_SECTION, json.dumps(questions),
    )
    random.shuffle(questions)
    return {"chapter": chapter, "questions": questions, "total": len(questions)}


async def get_revision_topics(user_id: str, subject: str, pool: asyncpg.Pool) -> list[dict]:
    rows = await pool.fetch(
        """
        SELECT DISTINCT ON (tt.chapter, tt.topic)
            tt.chapter, tt.topic AS section, tt.subject, tt.priority,
            tt.is_done AS completed, tt.completed_at,
            EXISTS(
                SELECT 1 FROM prepvicta_data.revision_quiz rq
                WHERE rq.chapter = tt.chapter AND rq.section = tt.topic
            ) AS quiz_ready,
            EXISTS(
                SELECT 1 FROM prepvicta_data.revision_summary rs
                WHERE rs.chapter = tt.chapter AND rs.section = tt.topic
            ) AS summary_ready,
            (
                SELECT ra.score::float / ra.total * 100
                FROM prepvicta_data.revision_attempt ra
                WHERE ra.user_id = tt.user_id AND ra.chapter = tt.chapter AND ra.section = tt.topic
                ORDER BY ra.attempted_at DESC LIMIT 1
            ) AS last_score
        FROM prepvicta_data.student_planner_tasks tt
        WHERE tt.user_id = $1
          AND CASE WHEN tt.subject IN ('Botany','Zoology') THEN 'Biology' ELSE tt.subject END = $2
        ORDER BY tt.chapter, tt.topic, tt.is_done ASC,
                 CASE WHEN tt.priority LIKE '%MUST%' THEN 1 WHEN tt.priority LIKE '%HIGH%' THEN 2 ELSE 3 END
        """,
        user_id, subject,
    )
    return [
        {
            "chapter": r["chapter"],
            "section": r["section"],
            "subject": r["subject"],
            "priority": r["priority"],
            "completed": r["completed"],
            "completed_at": r["completed_at"].isoformat() if r["completed_at"] else None,
            "quiz_ready": r["quiz_ready"],
            "summary_ready": r["summary_ready"],
            "last_score": round(r["last_score"]) if r["last_score"] is not None else None,
        }
        for r in rows
    ]
