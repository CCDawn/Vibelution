"""Computer Use API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from core.web.routes.computer_use_models import (
    ComputerUseCancelPayload,
    ComputerUseConfirmPayload,
    ComputerUseSessionResponse,
    ComputerUseTaskPayload,
)
from core.web.services.computer_use_service import (
    ComputerUseError,
    cancel_computer_use_session,
    computer_use_screenshot_path,
    confirm_computer_use_session,
    get_computer_use_session,
    start_computer_use_task,
)


router = APIRouter(tags=["computer-use"])


def _raise_computer_use_error(exc: Exception) -> None:
    if isinstance(exc, FileNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, ComputerUseError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise HTTPException(status_code=500, detail="Computer Use operation failed") from exc


@router.post(
    "/computer-use/tasks",
    response_model=ComputerUseSessionResponse,
    response_model_exclude_unset=True,
)
def create_computer_use_task(payload: ComputerUseTaskPayload) -> dict:
    try:
        return start_computer_use_task(
            task=payload.task,
            target_url=payload.targetUrl,
            allowed_domains=payload.allowedDomains,
            actions=payload.actions,
            max_steps=payload.maxSteps,
            require_confirmation=payload.requireConfirmation,
            mode=payload.mode,
            timeout_seconds=payload.timeoutSeconds,
        )
    except Exception as exc:  # pragma: no cover - routed by helper
        _raise_computer_use_error(exc)


@router.get(
    "/computer-use/sessions/{session_id}",
    response_model=ComputerUseSessionResponse,
    response_model_exclude_unset=True,
)
def read_computer_use_session(session_id: str) -> dict:
    try:
        return get_computer_use_session(session_id)
    except Exception as exc:  # pragma: no cover - routed by helper
        _raise_computer_use_error(exc)


@router.post(
    "/computer-use/sessions/{session_id}/confirm",
    response_model=ComputerUseSessionResponse,
    response_model_exclude_unset=True,
)
def confirm_computer_use(session_id: str, payload: ComputerUseConfirmPayload | None = None) -> dict:
    try:
        return confirm_computer_use_session(session_id, confirmation=(payload.confirmation if payload else "approved"))
    except Exception as exc:  # pragma: no cover - routed by helper
        _raise_computer_use_error(exc)


@router.post(
    "/computer-use/sessions/{session_id}/cancel",
    response_model=ComputerUseSessionResponse,
    response_model_exclude_unset=True,
)
def cancel_computer_use(session_id: str, payload: ComputerUseCancelPayload | None = None) -> dict:
    try:
        return cancel_computer_use_session(session_id, reason=(payload.reason if payload else "cancelled_by_user"))
    except Exception as exc:  # pragma: no cover - routed by helper
        _raise_computer_use_error(exc)


@router.get(
    "/computer-use/sessions/{session_id}/screenshots/{image_id}",
    response_class=FileResponse,
)
def read_computer_use_screenshot(session_id: str, image_id: str):
    try:
        return FileResponse(computer_use_screenshot_path(session_id, image_id), media_type="image/png")
    except Exception as exc:  # pragma: no cover - routed by helper
        _raise_computer_use_error(exc)
