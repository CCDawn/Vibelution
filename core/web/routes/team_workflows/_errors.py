from __future__ import annotations
from typing import Any, NoReturn
from fastapi import HTTPException
from core.web.services.runtime_scene_service import record_runtime_scene_event

def _truncate_route_field(value: Any, *, limit: int = 240) -> str:
    return str(value or "").strip()[:limit]


def _raise_team_workflow_route_error(
    action: str,
    team_id: str,
    exc: Exception,
    *,
    status_code: int,
    fields: dict[str, Any] | None = None,
    detail: Any | None = None,
) -> NoReturn:
    event_fields = {
        "action": _truncate_route_field(action, limit=120),
        "teamId": _truncate_route_field(team_id, limit=160),
        "statusCode": status_code,
        "errorType": type(exc).__name__,
        "errorDetail": _truncate_route_field(exc, limit=320),
    }
    if fields:
        event_fields.update({key: _truncate_route_field(value) for key, value in fields.items()})
    try:
        record_runtime_scene_event(
            "team_workflow_orchestration",
            "route_error",
            "team_workflow.route_error",
            message=f"{action} blocked at the Team Workflow API route.",
            level="warning" if status_code < 500 else "error",
            outcome="blocked" if status_code in {400, 403, 404, 409, 422} else "failed",
            fields=event_fields,
            lifecycle=True,
        )
    except Exception:
        pass
    raise HTTPException(status_code=status_code, detail=detail if detail is not None else str(exc)) from exc
