import logging

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.db.database import get_pool
from app.services.learn_service import get_raw_topic_by_chapter_section
from app.services.revision_service import (
    generate_and_store_quiz,
    generate_and_store_summary,
    get_chapter_quiz,
    get_quiz,
    get_revision_summary,
    get_revision_topics,
    save_attempt,
)

router = APIRouter(prefix="/revision", tags=["Revision Center"])
logger = logging.getLogger(__name__)
INTERNAL_ERROR = "Internal server error"


class AttemptRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=80)
    chapter: str = Field(..., min_length=1, max_length=200)
    section: str = Field(..., min_length=1, max_length=300)
    score: int = Field(..., ge=0)
    total: int = Field(..., ge=1)
    answers: list = Field(default_factory=list)


@router.get("/topics")
async def topics(
    user_id: str = Query(..., max_length=80),
    subject: str = Query(default="Biology", max_length=50),
):
    try:
        pool = await get_pool()
        return await get_revision_topics(user_id, subject, pool)
    except Exception as exc:
        logger.exception("failed_to_fetch_revision_topics")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=INTERNAL_ERROR) from exc


@router.get("/summary")
async def summary(
    chapter: str = Query(..., max_length=200),
    section: str = Query(..., max_length=300),
    subject: str = Query(default="Biology", max_length=50),
):
    try:
        pool = await get_pool()
        existing = await get_revision_summary(chapter, section, pool)
        if existing:
            return existing

        topic = await get_raw_topic_by_chapter_section(chapter, section)
        content = topic["content"] if topic else f"{chapter} - {section}"

        return await generate_and_store_summary(chapter, section, subject, content, pool)
    except Exception as exc:
        logger.exception("failed_to_fetch_summary")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=INTERNAL_ERROR) from exc


@router.get("/quiz")
async def quiz(
    chapter: str = Query(..., max_length=200),
    section: str = Query(..., max_length=300),
    subject: str = Query(default="Biology", max_length=50),
    priority: str = Query(default="HIGH", max_length=50),
):
    try:
        pool = await get_pool()
        existing = await get_quiz(chapter, section, pool)
        if existing:
            return existing

        topic = await get_raw_topic_by_chapter_section(chapter, section)
        content = topic["content"] if topic else f"{chapter} - {section}"

        return await generate_and_store_quiz(
            subject=subject,
            chapter=chapter,
            section=section,
            content=content,
            priority=priority,
            pool=pool,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("failed_to_fetch_quiz")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=INTERNAL_ERROR) from exc


@router.get("/chapter-quiz")
async def chapter_quiz(
    chapter: str = Query(..., max_length=200),
    subject: str = Query(default="Biology", max_length=50),
):
    try:
        pool = await get_pool()
        return await get_chapter_quiz(chapter, subject, pool)
    except Exception as exc:
        logger.exception("failed_to_fetch_chapter_quiz")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=INTERNAL_ERROR) from exc


@router.post("/attempt")
async def attempt(payload: AttemptRequest):
    try:
        if payload.score > payload.total:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="score cannot exceed total")
        pool = await get_pool()
        return await save_attempt(
            user_id=payload.user_id,
            chapter=payload.chapter,
            section=payload.section,
            score=payload.score,
            total=payload.total,
            answers=payload.answers,
            pool=pool,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("failed_to_save_attempt")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=INTERNAL_ERROR) from exc
