from fastapi import APIRouter, HTTPException, status

from app.db.database import get_pool
from app.schemas.planning import PlanningAgentRequest, PlanningAgentResponse
from app.services.planner_service import build_planning_agent_response

router = APIRouter(tags=["Planning Agent"])


@router.post("/Planningagent", response_model=PlanningAgentResponse, status_code=status.HTTP_201_CREATED)
async def create_planning_agent_plan(payload: PlanningAgentRequest) -> PlanningAgentResponse:
    try:
        pool = await get_pool()
        return await build_planning_agent_response(payload, pool)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
