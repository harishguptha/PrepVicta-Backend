import asyncio
import re
import json

import asyncpg
from openai import AsyncOpenAI
from pinecone import Pinecone
from pinecone.data.dataclasses.search_query import SearchQuery

from app.cache import TTLCache
from app.config import get_settings

settings = get_settings()
PINECONE_API_KEY = settings.pinecone_api_key
INDEX_NAME = settings.pinecone_index
NAMESPACE = settings.pinecone_namespace
LLM_MODEL = settings.openai_model

_pinecone_index = None
_llm_client: AsyncOpenAI | None = None
_llm_semaphore: asyncio.Semaphore | None = None
_chapters_cache: TTLCache[list[dict]] = TTLCache(settings.cache_max_items, settings.cache_ttl_seconds)
_search_cache: TTLCache[list[dict]] = TTLCache(settings.cache_max_items, settings.cache_ttl_seconds)
_chapter_images_cache: TTLCache[list[dict]] = TTLCache(settings.cache_max_items, settings.cache_ttl_seconds)
_chapter_sections_cache: TTLCache[list[dict]] = TTLCache(settings.cache_max_items, settings.cache_ttl_seconds)
_topic_cache: TTLCache[dict] = TTLCache(settings.cache_max_items, settings.cache_ttl_seconds)
_raw_topic_cache: TTLCache[dict] = TTLCache(settings.cache_max_items, settings.cache_ttl_seconds)


def _get_index():
    global _pinecone_index
    if _pinecone_index is None:
        pc = Pinecone(api_key=PINECONE_API_KEY)
        _pinecone_index = pc.Index(INDEX_NAME)
    return _pinecone_index

def _get_llm_client() -> AsyncOpenAI:
    global _llm_client
    if _llm_client is None:
        settings = get_settings()
        _llm_client = AsyncOpenAI(api_key=settings.openai_api_key, timeout=settings.openai_timeout_seconds)
    return _llm_client


def _get_llm_semaphore() -> asyncio.Semaphore:
    global _llm_semaphore
    if _llm_semaphore is None:
        _llm_semaphore = asyncio.Semaphore(get_settings().openai_max_concurrency)
    return _llm_semaphore

_LLM_SYSTEM = (
    "You are an expert NEET biology teacher. Given raw topic content, produce a clear, "
    "structured, exam-focused explanation for Class 11/12 NEET students. "
    "Use markdown formatting."
)

_LLM_USER = (
    "Chapter: {chapter}\nSection: {section}\n\n"
    "Raw Content:\n{content}\n\n"
    "Write a comprehensive NEET-focused explanation with these sections:\n"
    "1. **Overview** — What this topic is about\n"
    "2. **Key Concepts** — Important definitions and facts\n"
    "3. **Detailed Explanation** — Core concepts explained clearly\n"
    "4. **NEET Focus Points** — What NEET specifically tests from this topic\n"
    "5. **Quick Revision** — 3-5 bullet points to remember\n"
)


async def _get_cached_llm_context(chapter: str, section: str, pool: asyncpg.Pool) -> str | None:
    row = await pool.fetchrow(
        "SELECT llm_context FROM topic_llm_cache WHERE chapter=$1 AND section=$2",
        chapter, section,
    )
    return row["llm_context"] if row else None


async def _store_llm_context(chapter: str, section: str, llm_context: str, pool: asyncpg.Pool) -> None:
    await pool.execute(
        """
        INSERT INTO topic_llm_cache (chapter, section, llm_context)
        VALUES ($1, $2, $3)
        ON CONFLICT (chapter, section) DO UPDATE SET llm_context = EXCLUDED.llm_context
        """,
        chapter, section, llm_context,
    )


def _strip_images(text: str) -> str:
    return re.sub(r'!\[.*?\]\(.*?\)', '', text).strip()


async def _generate_llm_context(chapter: str, section: str, content: str, images: list[str]) -> str:
    clean_content = _strip_images(content)
    client = _get_llm_client()

    text_block = {
        "type": "text",
        "text": _LLM_USER.format(chapter=chapter, section=section, content=clean_content[:6000]),
    }

    if images:
        # Vision model — send text + all available images
        user_content = [text_block] + [
            {"type": "image_url", "image_url": {"url": url}}
            for url in images
        ]
        model = "gpt-4o"
    else:
        user_content = text_block["text"]
        model = LLM_MODEL

    async with _get_llm_semaphore():
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _LLM_SYSTEM},
                {"role": "user", "content": user_content},
            ],
            temperature=0.4,
            max_tokens=1500,
        )
    return (response.choices[0].message.content or "").strip()


def _extract_images(fields: dict) -> list[str]:
    images = []
    for i in range(6):
        url = fields.get(f"img_{i}")
        if url:
            images.append(url)
    return images


async def mark_topic_viewed(
    user_id: str, chapter: str, section: str, subject: str, pool: asyncpg.Pool
) -> None:
    if not user_id:
        return
    await pool.execute(
        """
        INSERT INTO prepvicta_data.topic_progress (user_id, chapter, section, subject)
        VALUES ($1::uuid, $2, $3, $4)
        ON CONFLICT (user_id, chapter, section) DO UPDATE SET
            subject = EXCLUDED.subject,
            viewed_at = NOW()
        """,
        user_id, chapter, section, subject,
    )


async def get_user_progress(user_id: str, subject: str, pool: asyncpg.Pool) -> dict:
    if not user_id:
        return {"viewed_sections": [], "chapter_scores": {}}

    viewed_rows = await pool.fetch(
        """
        SELECT chapter, section
        FROM prepvicta_data.topic_progress
        WHERE user_id = $1::uuid
          AND (subject = $2 OR ($2 = 'Biology' AND subject IN ('Biology', 'Botany', 'Zoology')))
        """,
        user_id, subject,
    )
    viewed = [f"{r['chapter']}::{r['section']}" for r in viewed_rows]

    score_rows = await pool.fetch(
        """
        SELECT DISTINCT ON (chapter)
            chapter, score, total, attempted_at
        FROM prepvicta_data.revision_attempt
        WHERE user_id = $1::uuid AND section = '__CHAPTER_TEST__'
        ORDER BY chapter, attempted_at DESC
        """,
        user_id,
    )
    chapter_scores: dict = {}
    for r in score_rows:
        correct = r["score"]
        total = r["total"]
        wrong = total - correct
        neet_score = correct * 4 - wrong
        max_score = total * 4
        pct = round((neet_score / max_score) * 100) if max_score > 0 else 0
        chapter_scores[r["chapter"]] = {
            "correct": correct,
            "total": total,
            "neet_score": neet_score,
            "max_score": max_score,
            "pct": pct,
            "attempted_at": r["attempted_at"].isoformat(),
        }

    return {"viewed_sections": viewed, "chapter_scores": chapter_scores}


async def get_chapters(subject: str, pool: asyncpg.Pool) -> list[dict]:
    """Return unique chapters with section counts from task_topic table."""
    cache_key = subject.strip()
    cached = _chapters_cache.get(cache_key)
    if cached is not None:
        return cached

    rows = await pool.fetch(
        """
        SELECT
            CASE WHEN subject IN ('Botany','Zoology') THEN 'Biology' ELSE subject END AS subject,
            chapter,
            COUNT(*) AS topic_count,
            MAX(CASE WHEN priority LIKE '%MUST%' THEN 3 WHEN priority LIKE '%HIGH%' THEN 2 ELSE 1 END) AS priority_rank
        FROM prepvicta_data.task_topic
        WHERE CASE WHEN subject IN ('Botany','Zoology') THEN 'Biology' ELSE subject END = $1
        GROUP BY subject, chapter
        ORDER BY priority_rank DESC, chapter
        """,
        subject,
    )
    result = [
        {
            "chapter": r["chapter"],
            "subject": r["subject"],
            "topic_count": r["topic_count"],
        }
        for r in rows
    ]
    _chapters_cache.set(cache_key, result)
    return result


async def search_topics(query: str, subject: str, limit: int) -> list[dict]:
    """Semantic search via Pinecone integrated inference."""
    cache_key = (query.strip().lower(), subject.strip(), limit)
    cached = _search_cache.get(cache_key)
    if cached is not None:
        return cached

    index = _get_index()
    results = await asyncio.to_thread(
        index.search_records,
        namespace=NAMESPACE,
        query=SearchQuery(inputs={"text": query}, top_k=limit, filter={"subject": {"$eq": subject}}),
        fields=["text", "chapter", "section", "class", "image_count", "img_0", "img_1", "img_2", "img_3", "img_4"],
    )
    hits = []
    for hit in results.result.hits:
        f = hit.fields
        hits.append({
            "id":      hit["_id"],
            "score":   round(hit["_score"], 3),
            "chapter": f.get("chapter", ""),
            "section": f.get("section", ""),
            "class":   f.get("class", ""),
            "content": f.get("text", ""),
            "images":  _extract_images(f),
        })
    _search_cache.set(cache_key, hits)
    return hits


async def get_chapter_images(chapter: str, subject: str) -> list[dict]:
    """Return unique image URLs across all sections of a chapter from Pinecone."""
    cache_key = (chapter.strip(), subject.strip())
    cached = _chapter_images_cache.get(cache_key)
    if cached is not None:
        return cached

    index = _get_index()
    alt = chapter.replace(' & ', ' and ') if ' & ' in chapter else chapter.replace(' and ', ' & ')
    chapter_filter = {"$in": [chapter, alt]} if alt != chapter else {"$eq": chapter}
    subj_filter = {"$in": ["Biology", "Botany", "Zoology"]} if subject == "Biology" else {"$eq": subject}

    results = await asyncio.to_thread(
        index.search_records,
        namespace=NAMESPACE,
        query=SearchQuery(inputs={"text": chapter}, top_k=40, filter={"chapter": chapter_filter, "subject": subj_filter}),
        fields=["section", "img_0", "img_1", "img_2", "img_3", "img_4", "img_5"],
    )
    images: list[dict] = []
    seen: set[str] = set()
    for hit in results.result.hits:
        section = hit.fields.get("section", "")
        imgs = _extract_images(hit.fields)
        for url in imgs:
            if url not in seen:
                seen.add(url)
                images.append({"section": section, "url": url})
    _chapter_images_cache.set(cache_key, images)
    return images


def _normalize_chapter(name: str) -> str:
    # Fix mojibake en/em dash variants → plain space, and & ↔ and handled separately
    for dash in [" – ", " — ", " - ", " − "]:
        name = name.replace(dash, " ")
    # Fix double-encoded mojibake (â€" / â€" patterns)
    try:
        name = name.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    for dash in [" – ", " — ", " - "]:
        name = name.replace(dash, " ")
    return name.strip()


async def get_chapter_sections(chapter: str, subject: str) -> list[dict]:
    """Return all unique sections for a chapter from Pinecone (no row-count cap)."""
    chapter = _normalize_chapter(chapter)
    cache_key = (chapter.strip(), subject.strip())
    cached = _chapter_sections_cache.get(cache_key)
    if cached is not None:
        return cached

    index = _get_index()
    alt = chapter.replace(' & ', ' and ') if ' & ' in chapter else chapter.replace(' and ', ' & ')
    chapter_filter = {"$in": [chapter, alt]} if alt != chapter else {"$eq": chapter}
    subj_filter = {"$in": ["Biology", "Botany", "Zoology"]} if subject == "Biology" else {"$eq": subject}

    results = await asyncio.to_thread(
        index.search_records,
        namespace=NAMESPACE,
        query=SearchQuery(inputs={"text": chapter}, top_k=60, filter={"chapter": chapter_filter, "subject": subj_filter}),
        fields=["section", "chapter", "class", "subject"],
    )
    unique: list[dict] = []
    seen: set[str] = set()
    for hit in results.result.hits:
        sec = hit.fields.get("section", "")
        if sec and sec not in seen:
            seen.add(sec)
            unique.append({
                "section": sec,
                "chapter": hit.fields.get("chapter", chapter),
                "class":   hit.fields.get("class", ""),
                "subject": hit.fields.get("subject", subject),
            })
    _chapter_sections_cache.set(cache_key, unique)
    return unique


async def get_infographic_cached(chapter: str, section: str, pool: asyncpg.Pool) -> dict | None:
    row = await pool.fetchrow(
        "SELECT infographic FROM prepvicta_data.topic_infographic WHERE chapter = $1 AND section = $2",
        chapter, section,
    )
    if row:
        return row["infographic"] if isinstance(row["infographic"], dict) else json.loads(row["infographic"])
    return None


async def generate_and_store_infographic(
    chapter: str, section: str, subject: str, content: str, pool: asyncpg.Pool
) -> dict:
    from app.services.generate_service import generate_infographic_json
    data = await generate_infographic_json(chapter, section, content)
    await pool.execute(
        """
        INSERT INTO prepvicta_data.topic_infographic (chapter, section, subject, infographic)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (chapter, section) DO UPDATE SET infographic = EXCLUDED.infographic
        """,
        chapter, section, subject, json.dumps(data),
    )
    return data


async def get_mind_map_cached(chapter: str, section: str, pool: asyncpg.Pool) -> dict | None:
    row = await pool.fetchrow(
        "SELECT mindmap FROM prepvicta_data.topic_mindmap WHERE chapter = $1 AND section = $2",
        chapter, section,
    )
    if row:
        return row["mindmap"] if isinstance(row["mindmap"], dict) else json.loads(row["mindmap"])
    return None


async def generate_and_store_mind_map(
    chapter: str, section: str, subject: str, content: str, pool: asyncpg.Pool
) -> dict:
    from app.services.generate_service import generate_mind_map_json
    data = await generate_mind_map_json(chapter, section, content)
    await pool.execute(
        """
        INSERT INTO prepvicta_data.topic_mindmap (chapter, section, subject, mindmap)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (chapter, section) DO UPDATE SET mindmap = EXCLUDED.mindmap
        """,
        chapter, section, subject, json.dumps(data),
    )
    return data


async def get_flowchart_cached(chapter: str, section: str, pool: asyncpg.Pool) -> dict | None:
    row = await pool.fetchrow(
        "SELECT flowchart FROM prepvicta_data.topic_flowchart WHERE chapter = $1 AND section = $2",
        chapter, section,
    )
    if row:
        return row["flowchart"] if isinstance(row["flowchart"], dict) else json.loads(row["flowchart"])
    return None


async def generate_and_store_flowchart(
    chapter: str, section: str, subject: str, content: str, pool: asyncpg.Pool
) -> dict:
    from app.services.generate_service import generate_flowchart_json
    data = await generate_flowchart_json(chapter, section, content)
    await pool.execute(
        """
        INSERT INTO prepvicta_data.topic_flowchart (chapter, section, subject, flowchart)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (chapter, section) DO UPDATE SET flowchart = EXCLUDED.flowchart
        """,
        chapter, section, subject, json.dumps(data),
    )
    return data


async def get_raw_topic_by_chapter_section(chapter: str, section: str) -> dict | None:
    """Fetch a specific section from Pinecone without generating LLM context."""
    cache_key = (chapter.strip(), section.strip())
    cached = _raw_topic_cache.get(cache_key)
    if cached is not None:
        return cached

    index = _get_index()
    results = await asyncio.to_thread(
        index.search_records,
        namespace=NAMESPACE,
        query=SearchQuery(inputs={"text": f"{chapter} {section}"}, top_k=1, filter={"chapter": {"$eq": chapter}, "section": {"$eq": section}}),
        fields=["text", "chapter", "section", "subject", "class", "image_count", "img_0", "img_1", "img_2", "img_3", "img_4"],
    )
    hits = results.result.hits
    if not hits:
        return None

    f = hits[0].fields
    content = f.get("text", "")
    images = _extract_images(f)

    result = {
        "id": hits[0].id,
        "chapter": f.get("chapter", ""),
        "section": f.get("section", ""),
        "subject": f.get("subject", ""),
        "class": f.get("class", ""),
        "content": content,
        "images": images,
    }
    _raw_topic_cache.set(cache_key, result)
    return result


async def get_topic_by_chapter_section(chapter: str, section: str, pool: asyncpg.Pool) -> dict | None:
    """Fetch a specific section with LLM-enriched context cached in DB."""
    chapter = _normalize_chapter(chapter)
    cache_key = (chapter.strip(), section.strip())
    cached = _topic_cache.get(cache_key)
    if cached is not None:
        return cached

    topic = await get_raw_topic_by_chapter_section(chapter, section)
    if not topic:
        return None

    content = topic["content"]
    images = topic["images"]
    llm_context = await _get_cached_llm_context(chapter, section, pool)
    if not llm_context:
        llm_context = await _generate_llm_context(chapter, section, content, images)
        await _store_llm_context(chapter, section, llm_context, pool)

    result = {
        **topic,
        "llm_context": llm_context,
    }
    _topic_cache.set(cache_key, result)
    return result
