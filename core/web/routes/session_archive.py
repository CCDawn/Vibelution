"""Session archive routes.

Thin layer only: DTO validation, 404/409/422 mapping, and one service call.
All archive semantics (metadata flag, directory index seal, busy guard) live
in ``core.web.services.session_archive_service``. The archived listing is a
separate single-segment path (``/session-archive``) so it can never be
shadowed by ``GET /sessions/{session_id}``.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from core.web.routes.session_archive_models import (
    SessionArchiveListResponse,
    SessionArchiveResponse,
)
from core.web.services.session_archive_service import (
    archive_session,
    list_archived_sessions,
    unarchive_session,
)
from core.web.services.session_service import (
    SessionBusyError,
    SessionNotFoundError,
    SessionValidationError,
)

router = APIRouter(tags=["sessions"])


@router.post(
    "/sessions/{session_id}/archive",
    response_model=SessionArchiveResponse,
    response_model_exclude_unset=True,
)
def session_archive(session_id: str) -> dict:
    """Archive one session (metadata flag only; reversible; idempotent)."""

    try:
        return archive_session(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc
    except SessionBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SessionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/sessions/{session_id}/unarchive",
    response_model=SessionArchiveResponse,
    response_model_exclude_unset=True,
)
def session_unarchive(session_id: str) -> dict:
    """Unarchive one previously archived session (idempotent)."""

    try:
        return unarchive_session(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc
    except SessionBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SessionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/session-archive",
    response_model=SessionArchiveListResponse,
    response_model_exclude_unset=True,
)
def archived_sessions(
    limit: int = Query(default=200, ge=1, le=200),
    cursor: str = "",
) -> dict:
    """Return one cursor-paginated page of archived session summaries."""

    return list_archived_sessions(limit=limit, cursor=cursor)
