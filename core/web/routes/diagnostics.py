"""Health diagnostics routes."""

from __future__ import annotations

from fastapi import APIRouter

from core.web.routes.diagnostics_models import HealthDiagnosticsResponse
from core.web.services.diagnostics_service import get_health_diagnostics


router = APIRouter(tags=["diagnostics"])


@router.get(
    "/diagnostics/health",
    response_model=HealthDiagnosticsResponse,
    response_model_exclude_unset=True,
)
def health_diagnostics() -> dict:
    return get_health_diagnostics()
