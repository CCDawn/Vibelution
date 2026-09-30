"""Runtime task query routes: read-only REST over the unified task registry.

Thin layer only — DTO validation and error mapping, one service call per
handler. Projection, filtering, pagination and the stop verb live in
``core.web.services.runtime_task_query_service``.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from core.web.routes.runtime_task_models import (
    RuntimeTaskDetailResponse,
    RuntimeTaskListResponse,
    RuntimeTaskStopRequest,
    RuntimeTaskStopResponse,
)
from core.web.services.runtime_task_query_service import (
    DEFAULT_ENDED_LIMIT,
    RuntimeTaskQueryError,
    default_query_service,
)

router = APIRouter(tags=["runtime-tasks"])


@router.get(
    "/runtime-tasks",
    response_model=RuntimeTaskListResponse,
    response_model_exclude_unset=True,
)
def list_runtime_tasks(
    status: str = Query(default="all"),
    kind: str = Query(default=""),
    parent_session_id: str = Query(default=""),
    cursor: str = Query(default=""),
    limit: int = Query(default=DEFAULT_ENDED_LIMIT, ge=1, le=200),
) -> dict:
    try:
        return default_query_service().list_tasks(
            status=status,
            kind=kind,
            parent_session_id=parent_session_id,
            cursor=cursor,
            limit=limit,
        )
    except RuntimeTaskQueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/runtime-tasks/{task_id}",
    response_model=RuntimeTaskDetailResponse,
    response_model_exclude_unset=True,
)
def get_runtime_task(task_id: str) -> dict:
    task = default_query_service().get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Unknown runtime task: {task_id}")
    return task


@router.post(
    "/runtime-tasks/{task_id}/stop",
    response_model=RuntimeTaskStopResponse,
    response_model_exclude_unset=True,
)
def stop_runtime_task(
    task_id: str,
    payload: RuntimeTaskStopRequest | None = None,
) -> dict:
    initiator = payload.initiator if payload is not None else "user"
    try:
        result = default_query_service().stop_task(task_id, initiator)
    except RuntimeTaskQueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail=f"Unknown runtime task: {task_id}")
    return result
