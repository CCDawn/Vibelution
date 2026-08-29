"""Runtime summary routes."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from core.runtime_manager.command_queue import cancel_lifecycle_command
from core.web.routes.runtime_models import (
    BrowserTelemetryPayload,
    RuntimeBrowserTelemetryResponse,
    RuntimeCodeFreshnessResponse,
    RuntimeLifecycleCancelPayload,
    RuntimeLifecycleCancelResponse,
    RuntimeLifecycleResponse,
    RuntimeShutdownPayload,
    RuntimeSummaryResponse,
)
from core.web.services.code_freshness import resolve_code_freshness
from core.web.services.runtime_scene_service import record_browser_telemetry
from core.web.services.runtime_service import (
    RuntimeRestartActiveWorkBlocked,
    get_runtime_summary_http_future,
    request_runtime_restart,
    request_runtime_shutdown,
)

router = APIRouter(tags=["runtime"])

PROJECT_ROOT = Path(__file__).resolve().parents[3]


@router.get(
    "/runtime/summary",
    response_model=RuntimeSummaryResponse,
    response_model_exclude_unset=True,
)
async def runtime_summary() -> dict:
    return await asyncio.wrap_future(get_runtime_summary_http_future())


@router.get(
    "/runtime/code-freshness",
    response_model=RuntimeCodeFreshnessResponse,
    response_model_exclude_unset=True,
)
def runtime_code_freshness() -> dict:
    return resolve_code_freshness(project_root=PROJECT_ROOT)


@router.post(
    "/runtime/shutdown",
    status_code=202,
    response_model=RuntimeLifecycleResponse,
    response_model_exclude_unset=True,
)
def runtime_shutdown(payload: RuntimeShutdownPayload | None = None) -> dict:
    try:
        return request_runtime_shutdown(
            body_present=payload is not None,
            source=str(payload.source or "") if payload else "",
            reason=str(payload.reason or "") if payload else "",
            stop_manager=bool(payload.stopManager) if payload else False,
        )
    except RuntimeRestartActiveWorkBlocked as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "active_work_stop_blocked",
                "message": exc.message,
                "activeWorkRuns": exc.active_work_runs,
            },
        ) from exc


@router.post(
    "/runtime/restart",
    status_code=202,
    response_model=RuntimeLifecycleResponse,
    response_model_exclude_unset=True,
)
def runtime_restart() -> dict:
    try:
        return request_runtime_restart()
    except RuntimeRestartActiveWorkBlocked as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "active_work_restart_blocked",
                "message": exc.message,
                "activeWorkRuns": exc.active_work_runs,
            },
        ) from exc


@router.post(
    "/runtime/lifecycle-command/cancel",
    response_model=RuntimeLifecycleCancelResponse,
    response_model_exclude_unset=True,
)
def runtime_lifecycle_command_cancel(payload: RuntimeLifecycleCancelPayload) -> dict:
    return cancel_lifecycle_command(
        command_id=payload.commandId,
        operation=payload.operation,
        requested_by=payload.source or "web_ui",
    )


@router.post(
    "/runtime/browser-telemetry",
    status_code=202,
    response_model=RuntimeBrowserTelemetryResponse,
    response_model_exclude_unset=True,
)
def runtime_browser_telemetry(payload: BrowserTelemetryPayload) -> dict:
    return record_browser_telemetry(payload.model_dump())


@router.get(
    "/runtime/events",
    response_class=StreamingResponse,
)
async def runtime_events() -> StreamingResponse:
    async def event_stream():
        while True:
            payload = {
                "type": "heartbeat",
                "at": datetime.now(timezone.utc).isoformat(),
            }
            yield f"event: heartbeat\ndata: {json.dumps(payload)}\n\n"
            await asyncio.sleep(15)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
