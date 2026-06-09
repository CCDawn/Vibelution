"""Session routes for the chat/coding shell."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from core.web.services.session_service import (
    SESSION_USER_IMAGE_MAX_BYTES,
    SessionChatReviewCandidateExistsError,
    SessionBusyError,
    SessionNotFoundError,
    SessionValidationError,
    create_chat_review_candidate_from_session,
    create_child_session,
    create_chat_session,
    delete_chat_session,
    delete_chat_session_lightweight,
    edit_and_resubmit_session_message,
    get_session_detail,
    list_child_sessions,
    list_sessions,
    query_sessions,
    request_stop_session_turn,
    resolve_session_image_artifact,
    store_session_user_image_attachment,
    stream_session_events,
    submit_session_guidance,
    submit_session_message,
    submit_session_message_lightweight,
    update_chat_session,
    update_chat_session_title,
)
from core.web.services.runtime_scene_service import record_runtime_scene_event


router = APIRouter(tags=["sessions"])


def _record_session_attachment_upload_rejected(
    session_id: str,
    *,
    content_length: int,
    received_bytes: int,
    reason: str,
) -> None:
    try:
        record_runtime_scene_event(
            "conversation",
            "attachment_upload",
            "conversation.attachment_upload.rejected",
            message="Session image attachment upload was rejected before storage.",
            level="warning",
            outcome="too_large",
            fields={
                "sessionId": str(session_id or "").strip(),
                "contentLength": max(0, int(content_length or 0)),
                "receivedBytes": max(0, int(received_bytes or 0)),
                "limitBytes": SESSION_USER_IMAGE_MAX_BYTES,
                "reason": str(reason or "").strip(),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _content_length_from_request(request: Request) -> int | None:
    raw = str(request.headers.get("content-length") or "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value >= 0 else None


async def _read_session_attachment_payload(session_id: str, request: Request) -> bytes:
    content_length = _content_length_from_request(request)
    if content_length is not None and content_length > SESSION_USER_IMAGE_MAX_BYTES:
        _record_session_attachment_upload_rejected(
            session_id,
            content_length=content_length,
            received_bytes=0,
            reason="content_length_exceeded",
        )
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Image attachment is too large.")

    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        if not chunk:
            continue
        total += len(chunk)
        if total > SESSION_USER_IMAGE_MAX_BYTES:
            _record_session_attachment_upload_rejected(
                session_id,
                content_length=content_length or 0,
                received_bytes=total,
                reason="stream_limit_exceeded",
            )
            raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Image attachment is too large.")
        chunks.append(bytes(chunk))
    return b"".join(chunks)


class SessionMessagePayload(BaseModel):
    content: str = ""
    contentUtf8Base64: str = ""
    attachmentIds: list[str] = []
    references: list[dict] = []
    mentalModelEnabled: bool | None = None
    turnMode: str = ""
    writeIntent: bool | None = None


class SessionMessageEditPayload(SessionMessagePayload):
    messageId: str = ""


class SessionGuidancePayload(BaseModel):
    content: str = ""
    mode: str = "safe"


class SessionUpdatePayload(BaseModel):
    title: str | None = None
    agentId: str | None = None


class ChildSessionCreatePayload(BaseModel):
    userRequest: str = ""
    taskTitle: str = ""
    splitReason: str = ""
    inheritedFacts: list[str] = []
    relevantFiles: list[str] = []
    relevantLogs: list[str] = []
    constraints: list[str] = []
    excludedContextSummary: str = ""
    autoStart: bool = True
    switchToChild: bool = True
    source: str = "agent_auto_split"


@router.get("/sessions")
def sessions() -> list[dict]:
    return list_sessions()


@router.get("/sessions/query")
def session_query(
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str = "",
    q: str = "",
    agentId: str = "",
    sessionKind: str = "",
    state: str = "",
    sort: str = "updatedAt_desc",
) -> dict:
    return query_sessions(
        limit=limit,
        cursor=cursor,
        q=q,
        agent_id=agentId,
        session_kind=sessionKind,
        state=state,
        sort=sort,
    )


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
def session_create() -> dict:
    return create_chat_session()


@router.get("/sessions/{session_id}")
def session_detail(session_id: str) -> dict:
    detail = get_session_detail(session_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return detail


@router.get("/sessions/{session_id}/child-sessions")
def session_child_sessions(session_id: str) -> list[dict]:
    return list_child_sessions(session_id)


@router.post("/sessions/{session_id}/child-sessions", status_code=status.HTTP_201_CREATED)
def session_create_child_session(session_id: str, payload: ChildSessionCreatePayload) -> dict:
    try:
        return create_child_session(
            session_id,
            user_request=payload.userRequest,
            task_title=payload.taskTitle,
            split_reason=payload.splitReason,
            inherited_facts=payload.inheritedFacts,
            relevant_files=payload.relevantFiles,
            relevant_logs=payload.relevantLogs,
            constraints=payload.constraints,
            excluded_context_summary=payload.excludedContextSummary,
            auto_start=payload.autoStart,
            switch_to_child=payload.switchToChild,
            source=payload.source,
        )
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SessionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/sessions/{session_id}")
def session_update(session_id: str, payload: SessionUpdatePayload) -> dict:
    try:
        if payload.agentId is not None:
            return update_chat_session(
                session_id,
                title=payload.title,
                agent_id=payload.agentId,
            )
        return update_chat_session_title(session_id, payload.title or "")
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/sessions/{session_id}")
def session_delete(session_id: str, request: Request) -> dict:
    try:
        if "respond-async" in str(request.headers.get("prefer") or "").lower():
            return delete_chat_session_lightweight(session_id)
        return delete_chat_session(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/sessions/{session_id}/events")
def session_events(session_id: str) -> StreamingResponse:
    detail = get_session_detail(session_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return StreamingResponse(
        stream_session_events(session_id, initial_detail=detail),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get("/sessions/{session_id}/artifacts/{artifact_id}")
def session_image_artifact(
    session_id: str,
    artifact_id: str,
    download: bool = Query(default=False),
) -> FileResponse:
    try:
        path, content_type = resolve_session_image_artifact(session_id, artifact_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session artifact not found") from exc
    filename = path.name if download else None
    return FileResponse(path, media_type=content_type, filename=filename)


@router.post("/sessions/{session_id}/attachments", status_code=status.HTTP_201_CREATED)
async def session_upload_attachment(session_id: str, request: Request) -> dict:
    content_type = str(request.headers.get("content-type") or "").strip()
    filename = str(request.headers.get("x-vibelution-filename") or "").strip()
    try:
        payload = await _read_session_attachment_payload(session_id, request)
        return store_session_user_image_attachment(
            session_id,
            payload,
            filename=filename,
            content_type=content_type,
        )
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/messages", status_code=status.HTTP_202_ACCEPTED)
def session_submit_message(session_id: str, payload: SessionMessagePayload, request: Request) -> dict:
    try:
        if "respond-async" in str(request.headers.get("prefer") or "").lower():
            return submit_session_message_lightweight(
                session_id,
                payload.content,
                content_utf8_base64=payload.contentUtf8Base64,
                attachment_ids=payload.attachmentIds,
                references=payload.references,
                mental_model_enabled=payload.mentalModelEnabled,
                turn_mode=payload.turnMode,
                write_intent=payload.writeIntent,
            )
        return submit_session_message(
            session_id,
            payload.content,
            content_utf8_base64=payload.contentUtf8Base64,
            attachment_ids=payload.attachmentIds,
            references=payload.references,
            mental_model_enabled=payload.mentalModelEnabled,
            turn_mode=payload.turnMode,
            write_intent=payload.writeIntent,
        )
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SessionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/messages/edit-resubmit", status_code=status.HTTP_202_ACCEPTED)
def session_edit_resubmit_message(session_id: str, payload: SessionMessageEditPayload) -> dict:
    try:
        return edit_and_resubmit_session_message(
            session_id,
            payload.messageId,
            payload.content,
            content_utf8_base64=payload.contentUtf8Base64,
            mental_model_enabled=payload.mentalModelEnabled,
            turn_mode=payload.turnMode,
            write_intent=payload.writeIntent,
        )
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SessionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/stop", status_code=status.HTTP_202_ACCEPTED)
def session_stop_turn(session_id: str) -> dict:
    try:
        return request_stop_session_turn(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/guidance", status_code=status.HTTP_202_ACCEPTED)
def session_submit_guidance(session_id: str, payload: SessionGuidancePayload) -> dict:
    try:
        return submit_session_guidance(session_id, payload.content, mode=payload.mode)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/chat-review-candidate", status_code=status.HTTP_201_CREATED)
def session_create_chat_review_candidate(session_id: str) -> dict:
    try:
        return create_chat_review_candidate_from_session(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (SessionBusyError, SessionChatReviewCandidateExistsError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SessionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
