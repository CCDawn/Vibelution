"""Health diagnostics routes."""

from __future__ import annotations

from fastapi import APIRouter

from core.web.services.diagnostics_service import get_health_diagnostics


router = APIRouter(tags=["diagnostics"])


@router.get("/diagnostics/health")
def health_diagnostics() -> dict:
    return get_health_diagnostics()
