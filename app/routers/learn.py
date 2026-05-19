import logging

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.db.database import get_pool
from app.services.generate_service import MECHANIC_LABELS, generate_mechanic
from app.services.learn_service import (
    get_chapter_sections,
    get_chapters,
    get_topic_by_chapter_section,
    get_user_progress,
    mark_topic_viewed,
    search_topics,
)

router = APIRouter(prefix="/learn", tags=["Learn Center"])
logger = logging.getLogger(__name__)
INTERNAL_ERROR = "Internal server error"


class GenerateRequest(BaseModel):
    chapter: str = Field(..., min_length=1, max_length=200)
    section: str = Field(..., min_length=1, max_length=300)
    content: str = Field(..., min_length=1, max_length=20000)
    mechanic: str = Field(..., min_length=1, max_length=50)


@router.get("/chapters")
async def chapters(subject: str = Query(default="Biology", max_length=50)):
    try:
        pool = await get_pool()
        return await get_chapters(subject, pool)
    except Exception as exc:
        logger.exception("failed_to_fetch_chapters")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=INTERNAL_ERROR) from exc


@router.get("/search")
async def search(
    q: str = Query(..., min_length=2, max_length=200),
    subject: str = Query(default="Biology", max_length=50),
    limit: int = Query(default=5, ge=1, le=10),
):
    try:
        return await search_topics(q, subject, limit)
    except Exception as exc:
        logger.exception("failed_to_search_topics")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=INTERNAL_ERROR) from exc


@router.get("/topic")
async def topic(
    chapter: str = Query(..., max_length=200),
    section: str = Query(..., max_length=300),
):
    try:
        pool = await get_pool()
        result = await get_topic_by_chapter_section(chapter, section, pool)
        if not result:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topic not found")
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("failed_to_fetch_topic")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=INTERNAL_ERROR) from exc


@router.get("/sections")
async def sections(
    chapter: str = Query(..., max_length=200),
    subject: str = Query(default="Biology", max_length=50),
):
    try:
        return await get_chapter_sections(chapter, subject)
    except Exception as exc:
        logger.exception("failed_to_fetch_sections")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=INTERNAL_ERROR) from exc


@router.get("/progress")
async def get_progress(
    user_id: str = Query(..., max_length=80),
    subject: str = Query(default="Biology", max_length=50),
):
    try:
        pool = await get_pool()
        return await get_user_progress(user_id, subject, pool)
    except Exception as exc:
        logger.exception("failed_to_fetch_progress")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=INTERNAL_ERROR) from exc


@router.post("/progress")
async def mark_progress(
    user_id: str = Query(..., max_length=80),
    chapter: str = Query(..., max_length=200),
    section: str = Query(..., max_length=300),
    subject: str = Query(default="Biology", max_length=50),
):
    try:
        pool = await get_pool()
        await mark_topic_viewed(user_id, chapter, section, subject, pool)
        return {"ok": True}
    except Exception as exc:
        logger.exception("failed_to_mark_progress")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=INTERNAL_ERROR) from exc


@router.get("/mechanics")
async def mechanics():
    return [{"key": key, "label": label} for key, label in MECHANIC_LABELS.items()]


@router.post("/generate")
async def generate(payload: GenerateRequest):
    try:
        return await generate_mechanic(
            chapter=payload.chapter,
            section=payload.section,
            content=payload.content,
            mechanic=payload.mechanic,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("failed_to_generate_mechanic")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=INTERNAL_ERROR) from exc
