"""Workbench UI preference routes (layout / shell chrome memory)."""

from __future__ import annotations

from fastapi import APIRouter

from core.web.routes.workbench_ui_models import (
    WorkbenchUiPreferencesPayload,
    WorkbenchUiPreferencesResponse,
    WorkbenchUiPreferencesSaveResponse,
)
from core.web.services import workbench_ui_preferences_service as prefs


router = APIRouter(tags=["workbench-ui"])


@router.get(
    "/workbench/ui-preferences",
    response_model=WorkbenchUiPreferencesResponse,
    response_model_exclude_unset=True,
)
def get_workbench_ui_preferences() -> dict:
    return prefs.load_workbench_ui_preferences()


@router.put(
    "/workbench/ui-preferences",
    response_model=WorkbenchUiPreferencesSaveResponse,
    response_model_exclude_unset=True,
)
def put_workbench_ui_preferences(payload: WorkbenchUiPreferencesPayload) -> dict:
    body = payload.model_dump(exclude_none=True)
    saved = prefs.save_workbench_ui_preferences(body)
    return {"ok": True, "preferences": saved}
