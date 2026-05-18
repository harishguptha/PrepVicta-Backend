import os
import re
from dotenv import load_dotenv
import asyncpg
from openai import AsyncOpenAI
from pinecone import Pinecone

load_dotenv()

PINECONE_API_KEY = os.getenv("pinecone_api_key", "")
INDEX_NAME       = os.getenv("PINECONE_INDEX", "")
NAMESPACE        = os.getenv("PINECONE_NAMESPACE", "")
LLM_MODEL        = os.getenv("OPENAI_PLANNING_MODEL", "gpt-4o-mini")

_pinecone_index = None
_llm_client: AsyncOpenAI | None = None

def _get_index():
    global _pinecone_index
    if _pinecone_index is None:
        pc = Pinecone(api_key=PINECONE_API_KEY)
        _pinecone_index = pc.Index(INDEX_NAME)
    return _pinecone_index

def _get_llm_client() -> AsyncOpenAI:
    global _llm_client
    if _llm_client is None:
        _llm_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))
    return _llm_client

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


async def get_chapters(subject: str, pool: asyncpg.Pool) -> list[dict]:
    """Return unique chapters with section counts from task_topic table."""
    rows = await pool.fetch(
        """
        SELECT
            CASE WHEN subject IN ('Botany','Zoology') THEN 'Biology' ELSE subject END AS subject,
            chapter,
            COUNT(*) AS topic_count,
            MAX(CASE WHEN priority LIKE '%MUST%' THEN 3 WHEN priority LIKE '%HIGH%' THEN 2 ELSE 1 END) AS priority_rank
        FROM task_topic
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
        }
        for r in rows
    ]


async def search_topics(query: str, subject: str, limit: int) -> list[dict]:
    """Semantic search via Pinecone integrated inference."""
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


async def get_topic_by_chapter_section(chapter: str, section: str, pool: asyncpg.Pool) -> dict | None:
    """Fetch a specific section by filtering Pinecone metadata, with LLM-enriched context cached in DB."""
    index = _get_index()
    results = index.search_records(
        namespace=NAMESPACE,
        top_k=1,
        inputs={"text": f"{chapter} {section}"},
        fields=["text", "chapter", "section", "class", "image_count", "img_0", "img_1", "img_2", "img_3", "img_4"],
        filter={"chapter": {"$eq": chapter}, "section": {"$eq": section}},
    )
    hits = results.result.hits
    if not hits:
        return None
    f = hits[0].fields
    content = f.get("text", "")

    images = _extract_images(f)
    llm_context = await _get_cached_llm_context(chapter, section, pool)
    if not llm_context:
        llm_context = await _generate_llm_context(chapter, section, content, images)
        await _store_llm_context(chapter, section, llm_context, pool)

    return {
        "id":          hits[0].id,
        "chapter":     f.get("chapter", ""),
        "section":     f.get("section", ""),
        "class":       f.get("class", ""),
        "content":     content,
        "images":      images,
        "llm_context": llm_context,
    }
