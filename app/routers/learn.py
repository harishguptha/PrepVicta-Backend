from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from app.db.database import get_pool
from app.services.learn_service import get_chapters, search_topics, get_topic_by_chapter_section
from app.services.generate_service import generate_mechanic, MECHANIC_LABELS

router = APIRouter(prefix="/learn", tags=["Learn Center"])


class GenerateRequest(BaseModel):
    chapter: str
    section: str
    content: str
    mechanic: str


@router.get("/chapters")
async def chapters(subject: str = Query(default="Biology")):
    try:
        pool = await get_pool()
        return await get_chapters(subject, pool)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.get("/search")
async def search(q: str = Query(..., min_length=2), subject: str = Query(default="Biology"), limit: int = Query(default=5, le=10)):
    try:
        return await search_topics(q, subject, limit)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.get("/topic")
async def topic(chapter: str = Query(...), section: str = Query(...)):
    try:
        pool = await get_pool()
        result = await get_topic_by_chapter_section(chapter, section, pool)
        if not result:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Topic not found")
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.get("/mechanics")
async def mechanics():
    return [{"key": k, "label": v} for k, v in MECHANIC_LABELS.items()]


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
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
