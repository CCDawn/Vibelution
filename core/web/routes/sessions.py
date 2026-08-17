"""Session routes for the chat/coding shell."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import StreamingResponse

from core.web.routes.session_catalog_models import (
    ChatWorkbenchBootstrapResponse,
    SessionActiveResponse,
    SessionBulkDeletePayload,
    SessionBulkDeleteResponse,
    SessionCatalogItem,
    SessionDeleteResponse,
    SessionQueryResponse,
)
from core.web.routes.session_detail_models import SessionDetailResponse
from core.web.routes.session_side_models import (
    SessionChatReviewCandidateResponse,
    SessionChildCreateResponse,
    SessionToolApprovalItem,
)
from core.web.routes.session_turn_models import (
    SessionAttachmentResponse,
    SessionLlmOptionsResponse,
    SessionTurnCommandResponse,
)
from core.web.services.runtime_scene_service import record_runtime_scene_event
from core.web.services.session.tool_approvals import (
    ToolApprovalConflictError,
    ToolApprovalError,
    ToolApprovalNotFoundError,
    list_tool_approval_requests,
    resolve_tool_approval_request,
)
from core.web.services.session_service import (
    SESSION_USER_IMAGE_MAX_BYTES,
    SessionBusyError,
    SessionChatReviewCandidateExistsError,
    SessionNotFoundError,
    SessionValidationError,
    create_chat_review_candidate_from_session,
    create_chat_session,
    create_child_session,
    bulk_delete_chat_sessions,
    delete_chat_session,
    MAX_BULK_SESSION_IDS,
    edit_and_resubmit_session_message,
    get_active_session_summary,
    get_session_detail,
    get_session_llm_options,
    list_child_sessions,
    list_sessions,
    query_sessions,
    request_stop_session_turn,
    resolve_session_image_artifact,
    resolve_session_stream_initial_payload,
    select_chat_session,
    store_session_user_image_attachment,
    stream_session_events_async,
    submit_session_guidance,
    submit_session_message,
    submit_session_message_lightweight,
    update_chat_session,
    update_chat_session_title,
    update_session_reasoning_effort,
)

router = APIRouter(tags=["sessions"])
# Initial session projection can perform filesystem work, so keep it off the
# event loop. Long-lived queue waits use the async subscriber and never occupy
# these workers.
_SESSION_STREAM_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="session-stream")


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


def _new_client_submission_id() -> str:
    return f"submission-{uuid4().hex}"


class SessionMessagePayload(BaseModel):
    clientSubmissionId: str = Field(default_factory=_new_client_submission_id, max_length=128)
    content: str = ""
    contentUtf8Base64: str = ""
    attachmentIds: list[str] = []
    references: list[dict] = []
    mentalModelEnabled: bool | None = None
    runtimeStatusEnabled: bool | None = None
    turnStatusTail: dict | None = None
    turnMode: str = ""
    writeIntent: bool | None = None


class SessionMessageEditPayload(SessionMessagePayload):
    messageId: str = ""


class SessionStopPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turnId: str = Field(min_length=1, max_length=160)


class SessionGuidancePayload(BaseModel):
    content: str = ""
    mode: str = "safe"


class SessionUpdatePayload(BaseModel):
    title: str | None = None
    agentId: str | None = None


class SessionCreatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agentId: str = ""
    title: str = ""


class SessionReasoningEffortPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reasoningEffort: str


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
    switchToChild: bool = False
    source: str = "agent_auto_split"


class SessionToolApprovalDecisionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["accept", "acceptForSession", "acceptAlways", "decline", "cancel"]


@router.get(
    "/sessions",
    response_model=list[SessionCatalogItem],
    response_model_exclude_unset=True,
)
def sessions() -> list[dict]:
    return list_sessions()


@router.get(
    "/sessions/active",
    response_model=SessionActiveResponse,
    response_model_exclude_unset=True,
)
def active_session() -> dict[str, str]:
    summary = get_active_session_summary() or {}
    return {"activeSessionId": str(summary.get("id") or "").strip()}


@router.get(
    "/sessions/query",
    response_model=SessionQueryResponse,
    response_model_exclude_unset=True,
)
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


@router.get(
    "/sessions/bootstrap",
    response_model=ChatWorkbenchBootstrapResponse,
    response_model_exclude_unset=True,
)
def session_bootstrap(
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str = "",
    q: str = "",
) -> dict:
    """Return the first-paint chat catalog from one shared projection pass."""

    from core.web.services import conversation_service

    return conversation_service.build_chat_workbench_bootstrap(
        limit=limit,
        cursor=cursor,
        q=q,
    )


@router.post(
    "/sessions",
    status_code=status.HTTP_201_CREATED,
    response_model=SessionCatalogItem,
    response_model_exclude_unset=True,
)
def session_create(
    request: Request,
    payload: SessionCreatePayload | None = None,
) -> dict:
    prefer = str(request.headers.get("prefer") or "").lower()
    lightweight = "respond-async" in prefer
    return create_chat_session(
        agent_id=str(payload.agentId or "").strip() if payload is not None else "",
        title=str(payload.title or "").strip() if payload is not None else "",
        lightweight=lightweight,
    )


@router.get(
    "/sessions/{session_id}",
    response_model=SessionDetailResponse,
    response_model_exclude_unset=True,
)
def session_detail(
    session_id: str,
    messageLimit: int = Query(default=0, ge=0, le=200),
    beforeMessageIndex: int = Query(default=0, ge=0),
    transcriptScope: str = Query(default="all"),
    includeSecondary: bool = Query(default=True),
) -> dict:
    detail = get_session_detail(
        session_id,
        message_limit=messageLimit,
        before_message_index=beforeMessageIndex,
        transcript_scope=transcriptScope,
        include_secondary=includeSecondary,
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return detail


@router.get(
    "/sessions/{session_id}/llm-options",
    response_model=SessionLlmOptionsResponse,
    response_model_exclude_unset=True,
)
def session_llm_options(session_id: str) -> dict:
    try:
        return get_session_llm_options(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch(
    "/sessions/{session_id}/reasoning-effort",
    response_model=SessionLlmOptionsResponse,
    response_model_exclude_unset=True,
)
def session_reasoning_effort_update(session_id: str, payload: SessionReasoningEffortPayload) -> dict:
    try:
        return update_session_reasoning_effort(
            session_id,
            reasoning_effort=payload.reasoningEffort,
        )
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SessionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/sessions/{session_id}/select",
    response_model=SessionCatalogItem,
    response_model_exclude_unset=True,
)
def session_select(session_id: str, request: Request) -> dict:
    try:
        prefer = str(request.headers.get("prefer") or "").lower()
        lightweight = "respond-async" in prefer
        return select_chat_session(session_id, lightweight=lightweight)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/sessions/{session_id}/child-sessions",
    response_model=list[SessionCatalogItem],
    response_model_exclude_unset=True,
)
def session_child_sessions(session_id: str) -> list[dict]:
    return list_child_sessions(session_id)


@router.post(
    "/sessions/{session_id}/child-sessions",
    status_code=status.HTTP_201_CREATED,
    response_model=SessionChildCreateResponse,
    response_model_exclude_unset=True,
)
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


@router.patch(
    "/sessions/{session_id}",
    response_model=SessionCatalogItem,
    response_model_exclude_unset=True,
)
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


@router.delete(
    "/sessions/{session_id}",
    response_model=SessionDeleteResponse,
    response_model_exclude_unset=True,
)
def session_delete(session_id: str) -> dict:
    try:
        return delete_chat_session(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SessionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/sessions/bulk-delete",
    response_model=SessionBulkDeleteResponse,
    response_model_exclude_unset=True,
)
def sessions_bulk_delete(payload: SessionBulkDeletePayload) -> dict:
    if len(payload.sessionIds) > MAX_BULK_SESSION_IDS:
        raise HTTPException(
            status_code=400,
            detail=f"Bulk session remove accepts at most {MAX_BULK_SESSION_IDS} session ids.",
        )
    try:
        return bulk_delete_chat_sessions(payload.sessionIds)
    except SessionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/sessions/{session_id}/events", response_class=StreamingResponse)
async def session_events(session_id: str, initial: str = Query("light")) -> StreamingResponse:
    try:
        initial_mode, detail, initial_state = await asyncio.get_running_loop().run_in_executor(
            _SESSION_STREAM_EXECUTOR,
            resolve_session_stream_initial_payload,
            session_id,
            initial,
        )
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc
    return StreamingResponse(
        stream_session_events_async(
            session_id,
            initial_detail=detail,
            initial=initial_mode,
            initial_state=initial_state,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get("/sessions/{session_id}/artifacts/{artifact_id}", response_class=FileResponse)
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


@router.post(
    "/sessions/{session_id}/attachments",
    status_code=status.HTTP_201_CREATED,
    response_model=SessionAttachmentResponse,
    response_model_exclude_unset=True,
)
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


@router.post(
    "/sessions/{session_id}/messages",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SessionTurnCommandResponse,
    response_model_exclude_unset=True,
)
def session_submit_message(session_id: str, payload: SessionMessagePayload, request: Request) -> dict:
    client_submission_id = str(payload.clientSubmissionId or "").strip() or _new_client_submission_id()
    try:
        if "respond-async" in str(request.headers.get("prefer") or "").lower():
            return submit_session_message_lightweight(
                session_id,
                payload.content,
                client_submission_id=client_submission_id,
                content_utf8_base64=payload.contentUtf8Base64,
                attachment_ids=payload.attachmentIds,
                references=payload.references,
                mental_model_enabled=payload.mentalModelEnabled,
                runtime_status_enabled=payload.runtimeStatusEnabled,
                turn_status_tail=payload.turnStatusTail if isinstance(payload.turnStatusTail, dict) else None,
                turn_mode=payload.turnMode,
                write_intent=payload.writeIntent,
            )
        return submit_session_message(
            session_id,
            payload.content,
            client_submission_id=client_submission_id,
            content_utf8_base64=payload.contentUtf8Base64,
            attachment_ids=payload.attachmentIds,
            references=payload.references,
            mental_model_enabled=payload.mentalModelEnabled,
            runtime_status_enabled=payload.runtimeStatusEnabled,
            turn_status_tail=payload.turnStatusTail if isinstance(payload.turnStatusTail, dict) else None,
            turn_mode=payload.turnMode,
            write_intent=payload.writeIntent,
        )
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SessionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/sessions/{session_id}/messages/edit-resubmit",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SessionCatalogItem,
    response_model_exclude_unset=True,
)
def session_edit_resubmit_message(session_id: str, payload: SessionMessageEditPayload) -> dict:
    client_submission_id = str(payload.clientSubmissionId or "").strip() or _new_client_submission_id()
    try:
        return edit_and_resubmit_session_message(
            session_id,
            payload.messageId,
            payload.content,
            client_submission_id=client_submission_id,
            content_utf8_base64=payload.contentUtf8Base64,
            mental_model_enabled=payload.mentalModelEnabled,
            runtime_status_enabled=payload.runtimeStatusEnabled,
            turn_status_tail=payload.turnStatusTail if isinstance(payload.turnStatusTail, dict) else None,
            turn_mode=payload.turnMode,
            write_intent=payload.writeIntent,
        )
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SessionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/sessions/{session_id}/stop",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SessionCatalogItem,
    response_model_exclude_unset=True,
)
def session_stop_turn(session_id: str, payload: SessionStopPayload) -> dict:
    try:
        return request_stop_session_turn(session_id, expected_turn_id=payload.turnId)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get(
    "/sessions/{session_id}/tool-approvals",
    response_model=list[SessionToolApprovalItem],
    response_model_exclude_unset=True,
)
def session_tool_approvals(
    session_id: str,
    approval_status: str = Query("", alias="status"),
) -> list[dict]:
    try:
        return list_tool_approval_requests(session_id, status=approval_status)
    except ToolApprovalError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/sessions/{session_id}/tool-approvals/{request_id}/decision",
    response_model=SessionToolApprovalItem,
    response_model_exclude_unset=True,
)
def session_resolve_tool_approval(
    session_id: str,
    request_id: str,
    payload: SessionToolApprovalDecisionPayload,
) -> dict:
    try:
        return resolve_tool_approval_request(
            session_id,
            request_id,
            decision=payload.decision,
        )
    except ToolApprovalNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ToolApprovalConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ToolApprovalError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/sessions/{session_id}/guidance",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SessionCatalogItem,
    response_model_exclude_unset=True,
)
def session_submit_guidance(session_id: str, payload: SessionGuidancePayload) -> dict:
    try:
        return submit_session_guidance(session_id, payload.content, mode=payload.mode)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/sessions/{session_id}/chat-review-candidate",
    status_code=status.HTTP_201_CREATED,
    response_model=SessionChatReviewCandidateResponse,
    response_model_exclude_unset=True,
)
def session_create_chat_review_candidate(session_id: str) -> dict:
    try:
        return create_chat_review_candidate_from_session(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (SessionBusyError, SessionChatReviewCandidateExistsError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SessionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
