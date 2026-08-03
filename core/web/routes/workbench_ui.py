"""Workbench UI preference routes (layout / shell chrome memory)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from core.web.services import workbench_ui_preferences_service as prefs


router = APIRouter(tags=["workbench-ui"])


class PaneLayoutPatch(BaseModel):
    layoutId: str = Field(min_length=1)
    widths: dict[str, float] = Field(default_factory=dict)


class WorkbenchUiPreferencesPayload(BaseModel):
    paneLayouts: dict[str, dict[str, float]] | None = None
    paneLayout: PaneLayoutPatch | None = None
    shell: dict[str, Any] | None = None


@router.get("/workbench/ui-preferences")
def get_workbench_ui_preferences() -> dict[str, Any]:
    return prefs.load_workbench_ui_preferences()


@router.put("/workbench/ui-preferences")
def put_workbench_ui_preferences(payload: WorkbenchUiPreferencesPayload) -> dict[str, Any]:
    body = payload.model_dump(exclude_none=True)
    saved = prefs.save_workbench_ui_preferences(body)
    return {"ok": True, "preferences": saved}
