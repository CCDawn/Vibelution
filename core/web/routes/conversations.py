"""Unified conversation index routes."""

from __future__ import annotations

from fastapi import APIRouter

from core.web.routes.conversation_models import ConversationIndexItem
from core.web.services.conversation_service import list_conversations


router = APIRouter(tags=["conversations"])


@router.get(
    "/conversations",
    response_model=list[ConversationIndexItem],
    response_model_exclude_unset=True,
)
def conversation_list() -> list[dict]:
    return list_conversations()
