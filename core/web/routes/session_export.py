"""Session local HTML export route.

Thin layer only: DTO validation, 404 mapping, and one service call. All
assembly, escaping, and attachment embedding live in
``core.web.services.session.export_html`` (users' content is untrusted input;
the escape red line is enforced in the service and its tests).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from core.web.routes.session_export_models import (
    SessionExportHtmlPayload,
    SessionExportHtmlResponse,
)
from core.web.services.session.export_html import export_session_html
from core.web.services.session_service import SessionNotFoundError

router = APIRouter(tags=["sessions"])


@router.post(
    "/sessions/{session_id}/export-html",
    response_model=SessionExportHtmlResponse,
    response_model_exclude_unset=True,
)
def session_export_html(session_id: str, payload: SessionExportHtmlPayload) -> dict:
    """Build the single-file HTML export for the selected turns of one session."""

    try:
        return export_session_html(
            session_id,
            turn_ids=payload.turnIds,
            include_attachments=payload.includeAttachments,
        )
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc
