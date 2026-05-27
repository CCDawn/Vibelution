"""Unified conversation index routes."""

from __future__ import annotations

from fastapi import APIRouter

from core.web.services.conversation_service import list_conversations


router = APIRouter(tags=["conversations"])


@router.get("/conversations")
def conversation_list() -> list[dict]:
    return list_conversations()
