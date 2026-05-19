from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from app.db.database import get_pool
from app.services.revision_service import (
    get_revision_summary, generate_and_store_summary,
    get_quiz, generate_and_store_quiz, save_attempt, get_revision_topics,
    get_chapter_quiz,
)
from app.services.learn_service import get_topic_by_chapter_section

router = APIRouter(prefix="/revision", tags=["Revision Center"])


class AttemptRequest(BaseModel):
    user_id: str
    chapter: str
    section: str
    score: int
    total: int
    answers: list


@router.get("/topics")
async def topics(
    user_id: str = Query(...),
    subject: str = Query(default="Biology"),
):
    try:
        pool = await get_pool()
        return await get_revision_topics(user_id, subject, pool)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.get("/summary")
async def summary(
    chapter: str = Query(...),
    section: str = Query(...),
    subject: str = Query(default="Biology"),
):
    try:
        pool = await get_pool()
        existing = await get_revision_summary(chapter, section, pool)
        if existing:
            return existing

        topic = await get_topic_by_chapter_section(chapter, section, pool)
        content = topic["content"] if topic else f"{chapter} — {section}"

        return await generate_and_store_summary(chapter, section, subject, content, pool)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.get("/quiz")
async def quiz(
    chapter: str = Query(...),
    section: str = Query(...),
    subject: str = Query(default="Biology"),
    priority: str = Query(default="HIGH"),
):
    try:
        pool = await get_pool()
        existing = await get_quiz(chapter, section, pool)
        if existing:
            return existing

        topic = await get_topic_by_chapter_section(chapter, section, pool)
        content = topic["content"] if topic else f"{chapter} — {section}"

        return await generate_and_store_quiz(
            subject=subject, chapter=chapter, section=section,
            content=content, priority=priority, pool=pool,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.get("/chapter-quiz")
async def chapter_quiz(
    chapter: str = Query(...),
    subject: str = Query(default="Biology"),
):
    try:
        pool = await get_pool()
        return await get_chapter_quiz(chapter, subject, pool)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.post("/attempt")
async def attempt(payload: AttemptRequest):
    try:
        pool = await get_pool()
        return await save_attempt(
            user_id=payload.user_id, chapter=payload.chapter, section=payload.section,
            score=payload.score, total=payload.total, answers=payload.answers, pool=pool,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
