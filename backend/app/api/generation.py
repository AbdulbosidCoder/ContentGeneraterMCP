from __future__ import annotations

from fastapi import APIRouter, Depends

from app.deps import current_user
from app.models import PlanRequest
from common.models import User
from rag.generation import generate_content_plan

router = APIRouter(tags=["generation"])


# Sync handler: runs in FastAPI's threadpool, keeping blocking embedding/Claude calls off the event loop.
@router.post("/plan")
def plan(body: PlanRequest, user: User = Depends(current_user)) -> dict:
    """One-off content plan (used by the MCP server). The web app plans inside conversations (/api/chat)."""
    return generate_content_plan(body.topic, body.n_examples, str(user.id), body.sources)
