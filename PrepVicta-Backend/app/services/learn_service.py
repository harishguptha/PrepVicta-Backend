import os
from dotenv import load_dotenv
import asyncpg
from pinecone import Pinecone

load_dotenv()

PINECONE_API_KEY = os.getenv("pinecone_api_key", "")
INDEX_NAME       = os.getenv("PINECONE_INDEX", "")
NAMESPACE        = os.getenv("PINECONE_NAMESPACE", "")

_pinecone_index = None

def _get_index():
    global _pinecone_index
    if _pinecone_index is None:
        pc = Pinecone(api_key=PINECONE_API_KEY)
        _pinecone_index = pc.Index(INDEX_NAME)
    return _pinecone_index


def _extract_images(fields: dict) -> list[str]:
    images = []
    for i in range(6):
        url = fields.get(f"img_{i}")
        if url:
            images.append(url)
    return images


async def get_chapters(subject: str, pool: asyncpg.Pool, user_id: str | None = None) -> list[dict]:
    """Return chapters assigned to user (from student_planner_tasks) or all chapters (from task_topic)."""
    if user_id:
        rows = await pool.fetch(
            """
            SELECT
                CASE WHEN subject IN ('Botany','Zoology') THEN 'Biology' ELSE subject END AS subject,
                chapter,
                COUNT(DISTINCT topic) AS topic_count,
                COUNT(DISTINCT topic) FILTER (WHERE is_done = true) AS completed_count,
                MAX(CASE WHEN priority LIKE '%MUST%' THEN 3 WHEN priority LIKE '%HIGH%' THEN 2 ELSE 1 END) AS priority_rank
            FROM prepvicta_data.student_planner_tasks
            WHERE user_id = $1
              AND CASE WHEN subject IN ('Botany','Zoology') THEN 'Biology' ELSE subject END = $2
            GROUP BY subject, chapter
            ORDER BY priority_rank DESC, chapter
            """,
            user_id, subject,
        )
    else:
        rows = await pool.fetch(
            """
            SELECT
                CASE WHEN subject IN ('Botany','Zoology') THEN 'Biology' ELSE subject END AS subject,
                chapter,
                COUNT(DISTINCT topic) AS topic_count,
                0 AS completed_count,
                MAX(CASE WHEN priority LIKE '%MUST%' THEN 3 WHEN priority LIKE '%HIGH%' THEN 2 ELSE 1 END) AS priority_rank
            FROM prepvicta_data.task_topic
            WHERE CASE WHEN subject IN ('Botany','Zoology') THEN 'Biology' ELSE subject END = $1
            GROUP BY subject, chapter
            ORDER BY priority_rank DESC, chapter
            """,
            subject,
        )
    return [
        {
            "chapter": r["chapter"],
            "subject": r["subject"],
            "topic_count": r["topic_count"],
            "completed_count": r["completed_count"],
        }
        for r in rows
    ]


async def get_user_sections(chapter: str, subject: str, pool: asyncpg.Pool, user_id: str) -> list[dict]:
    """Return topics assigned to user for a given chapter."""
    rows = await pool.fetch(
        """
        SELECT DISTINCT ON (topic)
            topic, chapter, priority, duration_min, activity, is_done
        FROM prepvicta_data.student_planner_tasks
        WHERE user_id = $1 AND chapter = $2
        ORDER BY topic,
                 CASE WHEN priority LIKE '%MUST%' THEN 1 WHEN priority LIKE '%HIGH%' THEN 2 ELSE 3 END
        """,
        user_id, chapter,
    )
    return [
        {
            "section": r["topic"],
            "chapter": chapter,
            "priority": r["priority"],
            "estimated_minutes": r["duration_min"],
            "activity": r["activity"],
            "completed": r["is_done"],
        }
        for r in rows
    ]


async def search_topics(query: str, subject: str, limit: int) -> list[dict]:
    """Semantic search via Pinecone."""
    index = _get_index()
    results = index.search_records(
        namespace=NAMESPACE,
        top_k=limit,
        inputs={"text": query},
        fields=["text", "chapter", "section", "class", "image_count", "img_0", "img_1", "img_2", "img_3", "img_4"],
        filter={"subject": {"$eq": subject}},
    )
    hits = []
    for hit in results.result.hits:
        f = hit.fields
        hits.append({
            "id":      hit.id,
            "score":   round(hit.score, 3),
            "chapter": f.get("chapter", ""),
            "section": f.get("section", ""),
            "class":   f.get("class", ""),
            "content": f.get("text", ""),
            "images":  _extract_images(f),
        })
    return hits


_JUNK_SECTIONS = {"summary", "exercises", "introduction", "exercise"}


def _chapter_variants(ch: str) -> list[str]:
    """Return chapter name variants to handle '&' vs 'and' mismatches."""
    return list({ch, ch.replace("&", "and"), ch.replace(" and ", " & ")})


async def get_topic_by_chapter_section(chapter: str, section: str, subject: str = "Biology") -> dict | None:
    """Fetch best-matching topic using semantic search.

    Filters by subject + chapter variants to stay within the right chapter,
    then scores candidates by how well their section name matches the query.
    Falls back to subject-only filter if chapter filter returns nothing.
    """
    index = _get_index()
    ch_vars = _chapter_variants(chapter)

    results = index.search_records(
        namespace=NAMESPACE,
        top_k=10,
        inputs={"text": f"{section} {chapter}"},
        fields=["text", "chapter", "section", "class", "image_count", "img_0", "img_1", "img_2", "img_3", "img_4"],
        filter={"$and": [{"subject": {"$eq": subject}}, {"chapter": {"$in": ch_vars}}]},
    )
    hits = results.result.hits

    if not hits:
        results = index.search_records(
            namespace=NAMESPACE,
            top_k=10,
            inputs={"text": f"{section} {chapter}"},
            fields=["text", "chapter", "section", "class", "image_count", "img_0", "img_1", "img_2", "img_3", "img_4"],
            filter={"subject": {"$eq": subject}},
        )
        hits = results.result.hits

    if not hits:
        return None

    content_hits = [h for h in hits if h.fields.get("section", "").strip().lower() not in _JUNK_SECTIONS]
    hits = content_hits or hits

    sec_lower = section.lower()
    ch_lower  = chapter.lower().replace("&", "and")

    def score_hit(h):
        h_sec = h.fields.get("section", "").lower()
        h_ch  = h.fields.get("chapter", "").lower().replace("&", "and")
        s = 0
        if h_sec == sec_lower:                                              s += 4
        elif sec_lower in h_sec:                                            s += 2
        elif any(w in h_sec for w in sec_lower.split() if len(w) > 3):     s += 1
        if h_ch == ch_lower:                                                s += 3
        elif ch_lower in h_ch or h_ch in ch_lower:                         s += 1
        return s

    best = max(hits, key=score_hit)
    f = best.fields
    return {
        "id":      best.id,
        "chapter": f.get("chapter", ""),
        "section": f.get("section", ""),
        "class":   f.get("class", ""),
        "content": f.get("text", ""),
        "images":  _extract_images(f),
    }
