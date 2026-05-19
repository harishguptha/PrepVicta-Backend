import traceback
import logging

from fastapi import APIRouter, HTTPException, Query, status
from app.db.database import get_pool
from app.services.dashboard_service import get_dashboard

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("")
async def dashboard(user_id: str = Query(...)):
    try:
        pool = await get_pool()
        return await get_dashboard(user_id, pool)
    except Exception as exc:
        logger.error("Dashboard error for user %s:\n%s", user_id, traceback.format_exc())
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
