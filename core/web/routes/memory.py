"""Agent memory overview routes."""

from __future__ import annotations

from fastapi import APIRouter

from core.web.services.memory_service import get_memory_overview


router = APIRouter(tags=["memory"])


@router.get("/memory/overview")
def memory_overview() -> dict:
    return get_memory_overview()
