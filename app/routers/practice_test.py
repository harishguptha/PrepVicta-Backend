import json
import logging
import random
import zipfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from app.db.database import get_pool

router = APIRouter(prefix="/practice-test", tags=["Practice Tests"])
logger = logging.getLogger(__name__)

_CORRECT_IDX = {"a": 0, "b": 1, "c": 2, "d": 3}
_IMG_CONTENT_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


def _row_to_question(r) -> dict:
    refs = r["image_refs"]
    if isinstance(refs, str):
        refs = json.loads(refs)
    return {
        "q_number": r["q_number"],
        "text": r["question_text"],
        "options": [r["option_a"], r["option_b"], r["option_c"], r["option_d"]],
        "correct": _CORRECT_IDX.get(r["correct_option"]),
        "subject": r["subject"].lower(),
        "has_image": r["has_image"],
        "image_refs": refs or [],
        "solution": r["solution"],
        "paper_year": r["paper_year"],
        "paper_number": r["paper_number"],
    }


@router.get("/papers")
async def list_papers():
    """Return all available practice test papers."""
    try:
        pool = await get_pool()
        rows = await pool.fetch(
            """
            SELECT paper_year, paper_number, paper_name,
                   COUNT(*) AS total_questions,
                   COUNT(*) FILTER (WHERE option_a != '' AND option_b != '' AND option_c != '' AND option_d != '') AS text_questions
            FROM prepvicta_data.practise_complete_full_test
            GROUP BY paper_year, paper_number, paper_name
            ORDER BY paper_year DESC, paper_number ASC
            """
        )
        return [
            {
                "paper_year": r["paper_year"],
                "paper_number": r["paper_number"],
                "paper_name": r["paper_name"],
                "total_questions": r["total_questions"],
                "text_questions": r["text_questions"],
            }
            for r in rows
        ]
    except Exception as exc:
        logger.exception("Failed to list practice test papers")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/questions")
async def get_questions(
    paper_year: int = Query(default=2026),
    paper_number: int = Query(default=1),
    subject: str = Query(default="all", max_length=20),
    count: int = Query(default=45, ge=1, le=180),
):
    """
    Return shuffled questions from a practice paper.
    All questions are returned — options may be text or [IMG:path] for image options.
    """
    try:
        pool = await get_pool()
        where_subject = "" if subject.lower() == "all" else "AND subject = $3"
        params = [paper_year, paper_number]
        if subject.lower() != "all":
            params.append(subject.capitalize())

        rows = await pool.fetch(
            f"""
            SELECT q_number, question_text, option_a, option_b, option_c, option_d,
                   correct_option, subject, has_image, image_refs, solution, paper_year, paper_number
            FROM prepvicta_data.practise_complete_full_test
            WHERE paper_year = $1 AND paper_number = $2
              AND option_a != '' AND option_b != '' AND option_c != '' AND option_d != ''
              {where_subject}
            ORDER BY q_number
            """,
            *params,
        )

        questions = [_row_to_question(r) for r in rows]

        if len(questions) > count:
            questions = random.sample(questions, count)
            order = {"chemistry": 0, "physics": 1, "biology": 2}
            questions.sort(key=lambda q: (order.get(q["subject"], 3), q["q_number"]))

        return questions
    except Exception as exc:
        logger.exception("Failed to fetch practice test questions")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/image")
async def serve_image(
    paper_year: int = Query(...),
    paper_number: int = Query(...),
    path: str = Query(..., max_length=300),
):
    """Serve an image from inside the paper's ZIP file."""
    try:
        pool = await get_pool()
        zip_path = await pool.fetchval(
            "SELECT zip_path FROM prepvicta_data.practise_complete_full_test "
            "WHERE paper_year=$1 AND paper_number=$2 AND zip_path != '' LIMIT 1",
            paper_year, paper_number,
        )
        if not zip_path or not Path(zip_path).exists():
            raise HTTPException(status_code=404, detail="ZIP not found")

        with zipfile.ZipFile(zip_path) as z:
            # img_path from content_list is like "images/hash.jpg"
            # actual ZIP path is like "Paper Name/auto/images/hash.jpg"
            match = next(
                (n for n in z.namelist() if n.endswith("/" + path) or n.endswith(path)),
                None,
            )
            if not match:
                raise HTTPException(status_code=404, detail="Image not found in ZIP")
            img_bytes = z.read(match)

        ext = Path(path).suffix.lower()
        content_type = _IMG_CONTENT_TYPES.get(ext, "image/jpeg")
        return Response(content=img_bytes, media_type=content_type)

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to serve practice test image")
        raise HTTPException(status_code=500, detail="Internal server error")
