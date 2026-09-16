"""Unified conversation index routes."""

from __future__ import annotations

from fastapi import APIRouter, Query

from core.web.routes.conversation_models import ConversationQueryResponse
from core.web.services.conversation_service import query_conversations


router = APIRouter(tags=["conversations"])


@router.get(
    "/conversations",
    response_model=ConversationQueryResponse,
    response_model_exclude_unset=True,
)
def conversation_list(
    limit: int = Query(default=100, ge=1, le=200),
    cursor: str = "",
    q: str = "",
    agentId: str = "",
    teamId: str = "",
    type: str = "",
) -> dict:
    """Return one cursor-paginated page of the unified conversation index.

    ``q`` matches title, summary, ids and agent identity fields (no message
    content scan). ``type`` narrows to ``direct_agent`` or ``group_room``.
    """

    return query_conversations(
        limit=limit,
        cursor=cursor,
        q=q,
        agent_id=agentId,
        team_id=teamId,
        conversation_type=type,
    )
