"""Local operator control only; no endpoint dispatches model-selected input."""
from contextlib import contextmanager
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from core.web.control import ensure_control_source
from core.web.services import personal_assistant_computer_service as service
from core.web.services.team_workflow.research_runtime.operator_authorization import (
    server_operator_scope_from_http,
)
from core.web.services.team_workflow.research_runtime.operator_permissions import operator_has_privileged_role

router = APIRouter(prefix="/personal-assistant/computer", tags=["personal-assistant"])


class Window(BaseModel):
    selectionId: str
    title: str
    appName: str


class Pending(BaseModel):
    id: str
    action: str
    targetLabel: str
    text: str | None


class State(BaseModel):
    available: StrictBool
    status: Literal["idle", "ready", "working", "waiting_confirmation", "paused", "manual", "ended", "error"]
    message: str
    grantId: str | None
    window: Window | None
    pending: Pending | None


class Windows(BaseModel):
    windows: list[Window]


class Grant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selectionId: str = Field(min_length=1, max_length=100)
    allowVision: StrictBool


class Control(BaseModel):
    model_config = ConfigDict(extra="forbid")
    grantId: str = Field(min_length=1, max_length=100)
    action: Literal["pause", "resume", "takeover", "return", "end"]


class Confirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    grantId: str = Field(min_length=1, max_length=100)
    pendingId: str = Field(min_length=1, max_length=100)
    approved: StrictBool


@contextmanager
def _operator(request: Request):
    ensure_control_source(request)
    if request.headers.get("X-OpenCode-Session") is not None:
        raise HTTPException(403, "电脑控制仅允许本机操作者使用。")
    try:
        with server_operator_scope_from_http(request) as operator:
            if not operator_has_privileged_role(operator.roles):
                raise PermissionError("operator_required")
            yield
    except PermissionError:
        raise HTTPException(403, "电脑控制需要本机操作者授权。") from None
    except (ValueError, OSError, service.CuaDriverError):
        raise HTTPException(409, "电脑控制状态已变化或驱动不可用，请刷新后重试。") from None


@router.get("", response_model=State)
def get_state(request: Request) -> dict:
    with _operator(request):
        return service.get_state()


@router.get("/windows", response_model=Windows)
def list_windows(request: Request) -> dict:
    with _operator(request):
        return service.list_windows()


@router.post("/grant", response_model=State)
def grant(payload: Grant, request: Request) -> dict:
    with _operator(request):
        return service.grant_window(payload.selectionId, payload.allowVision)


@router.post("/control", response_model=State)
def control(payload: Control, request: Request) -> dict:
    with _operator(request):
        return service.control(payload.grantId, payload.action)


@router.post("/confirm", response_model=State)
def confirm(payload: Confirmation, request: Request) -> dict:
    with _operator(request):
        return service.confirm(payload.grantId, payload.pendingId, payload.approved)
