"""Session routes for the chat/coding shell."""

from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
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
    SessionPinResponse,
    SessionQueryResponse,
)
from core.web.routes.session_detail_models import SessionDetailResponse
from core.web.routes.session_rewind_models import (
    SessionRewindApplyPayload,
    SessionRewindApplyResponse,
    SessionRewindPreviewResponse,
)
from core.web.routes.session_side_models import (
    SessionChatReviewCandidateResponse,
    SessionChildCreateResponse,
    SessionMessageCurationPayload,
    SessionMessageCurationResponse,
    SessionMessageCurationStateResponse,
    SessionToolApprovalItem,
)
from core.web.routes.session_turn_models import (
    SessionAttachmentResponse,
    SessionLlmOptionsResponse,
    SessionTurnCommandResponse,
)
from core.web.services.runtime_scene_service import record_runtime_scene_event
from core.web.services import session_service
from core.web.services.session.session_pin_ops import set_chat_session_pinned
from core.web.services.session import document_attachments as session_document_attachments
from core.web.services.session.image_attachments import (
    LocalAttachmentReadError,
    read_local_attachment_bytes,
)
from core.web.services.session.composer_example_commands import (
    get_composer_starter_commands,
)
from core.web.services.session.prompt_suggestion import (
    PromptSuggestionError,
    generate_prompt_suggestion,
)
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
    SessionIdempotencyConflictError,
    SessionIdempotencyReplayGoneError,
    SessionMessageCurationStateError,
    SessionModelSelectionError,
    SessionNotFoundError,
    SessionRewindConflictError,
    SessionValidationError,
    create_chat_review_candidate_from_session,
    create_chat_session,
    create_child_session,
    bulk_delete_chat_sessions,
    delete_chat_session,
    MAX_BULK_SESSION_IDS,
    edit_and_resubmit_session_message,
    fork_session_from_node,
    get_active_session_summary,
    get_session_detail,
    get_session_llm_options,
    get_session_message_curation,
    list_child_sessions,
    list_sessions,
    list_session_queued_turns,
    query_sessions,
    remove_session_queued_turn,
    send_now_session_queued_turn,
    update_session_queued_turn,
    regenerate_session_message,
    request_stop_session_turn,
    resolve_session_image_artifact,
    resolve_session_stream_initial_payload,
    select_chat_session,
    set_session_message_curation,
    store_session_user_image_attachment,
    stream_session_events_async,
    submit_session_guidance,
    submit_session_message,
    submit_session_message_lightweight,
    switch_session_head,
    update_chat_session,
    update_chat_session_title,
    update_session_reasoning_effort,
    preview_session_rewind,
    apply_session_rewind,
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


async def _read_session_attachment_registration(request: Request) -> dict:
    try:
        payload = await request.json()
    except Exception:
        payload = None
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=422,
            detail="Invalid JSON attachment registration payload.",
        )
    return payload


def _store_session_attachment_from_local_path(session_id: str, registration: dict) -> dict:
    """Zero-copy registration: read the referenced local file in place.

    The desktop shell resolves the real path of a drag/picker file so the
    bytes never travel through the renderer. Every read failure maps to 4xx
    so the client falls back to the binary upload transparently. The read
    bytes go through the same sniffing/size/whitelist gates as the binary
    upload, so storage behavior is identical.
    """
    local_path = str(registration.get("localPath") or "").strip()
    filename = str(registration.get("filename") or "").strip()
    content_type = str(registration.get("contentType") or "").strip()
    try:
        payload = read_local_attachment_bytes(local_path, max_bytes=SESSION_USER_IMAGE_MAX_BYTES)
    except LocalAttachmentReadError as exc:
        status_code = {
            "not_found": status.HTTP_404_NOT_FOUND,
            "too_large": status.HTTP_413_CONTENT_TOO_LARGE,
        }.get(exc.reason, 422)
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    # Same routing as the binary upload: images are identified by content
    # sniffing; anything else goes to the document store with its own
    # extension/size/payload gates.
    if session_service._sniff_image_extension(payload) or content_type.lower().startswith("image/"):
        return store_session_user_image_attachment(
            session_id,
            payload,
            filename=filename,
            content_type=content_type,
        )
    return session_document_attachments.store_session_user_document_attachment(
        session_id,
        payload,
        filename=filename,
        content_type=content_type,
    )


def _new_client_submission_id() -> str:
    return f"submission-{uuid4().hex}"


class SessionModelSelectionPayload(BaseModel):
    """One-shot per-turn model override (does not change the session default)."""

    modelId: str = ""
    reasoningEffort: str | None = None


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
    queueIfBusy: bool = False
    modelSelection: SessionModelSelectionPayload | None = None


class SessionMessageEditPayload(SessionMessagePayload):
    messageId: str = ""
    baseMessageId: str = ""


class SessionMessageRegeneratePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clientSubmissionId: str = Field(default_factory=_new_client_submission_id, max_length=128)
    messageId: str = ""
    baseMessageId: str = ""
    mentalModelEnabled: bool | None = None
    runtimeStatusEnabled: bool | None = None
    turnStatusTail: dict | None = None
    turnMode: str = ""
    writeIntent: bool | None = None


class SessionHeadPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodeId: str = Field(min_length=1, max_length=200)


class SessionForkPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodeId: str = Field(min_length=1, max_length=200)
    scope: str = Field(default="visible_path", max_length=40)


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


class SessionPromptSuggestionPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    afterTurnId: str = ""


class SessionPromptSuggestionResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sessionId: str
    turnId: str = ""
    suggestion: str | None = None
    reason: str = ""


class SessionComposerStarterItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    heading: str
    command: str


class SessionComposerExampleResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    command: str | None = None
    starters: list[SessionComposerStarterItem] = []


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
    teamId: str = "",
) -> dict:
    return query_sessions(
        limit=limit,
        cursor=cursor,
        q=q,
        agent_id=agentId,
        session_kind=sessionKind,
        state=state,
        sort=sort,
        team_id=teamId,
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
    responses={
        status.HTTP_409_CONFLICT: {
            "description": "Idempotency-Key was already used for a different session create request."
        },
        status.HTTP_410_GONE: {
            "description": "The session previously created for this Idempotency-Key no longer exists."
        },
    },
)
def session_create(
    request: Request,
    payload: SessionCreatePayload | None = None,
    idempotency_key: str = Header(
        default="",
        alias="Idempotency-Key",
        description="Optional retry key for creating one session; maximum 200 characters.",
    ),
) -> dict:
    prefer = str(request.headers.get("prefer") or "").lower()
    lightweight = "respond-async" in prefer
    idempotency_key = str(idempotency_key or "").strip()
    started_at = time.perf_counter()
    if len(idempotency_key) > 200:
        _record_session_create_request_timing(
            started_at,
            lightweight=lightweight,
            idempotency_enabled=True,
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            outcome="rejected",
            error_type="invalid_idempotency_key",
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Idempotency-Key exceeds 200 characters.",
        )
    try:
        result = create_chat_session(
            agent_id=str(payload.agentId or "").strip() if payload is not None else "",
            title=str(payload.title or "").strip() if payload is not None else "",
            lightweight=lightweight,
            idempotency_key=idempotency_key,
        )
    except SessionIdempotencyConflictError as exc:
        _record_session_create_request_timing(
            started_at,
            lightweight=lightweight,
            idempotency_enabled=bool(idempotency_key),
            status_code=status.HTTP_409_CONFLICT,
            outcome="conflict",
            error_type=type(exc).__name__,
        )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except SessionIdempotencyReplayGoneError as exc:
        _record_session_create_request_timing(
            started_at,
            lightweight=lightweight,
            idempotency_enabled=bool(idempotency_key),
            status_code=status.HTTP_410_GONE,
            outcome="gone",
            error_type=type(exc).__name__,
        )
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=str(exc)) from exc
    except Exception as exc:
        _record_session_create_request_timing(
            started_at,
            lightweight=lightweight,
            idempotency_enabled=bool(idempotency_key),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            outcome="failed",
            error_type=type(exc).__name__,
        )
        raise
    _record_session_create_request_timing(
        started_at,
        lightweight=lightweight,
        idempotency_enabled=bool(idempotency_key),
        status_code=status.HTTP_201_CREATED,
        outcome="succeeded",
        session_id=str(result.get("id") or ""),
    )
    return result


def _record_session_create_request_timing(
    started_at: float,
    *,
    lightweight: bool,
    idempotency_enabled: bool,
    status_code: int,
    outcome: str,
    session_id: str = "",
    error_type: str = "",
) -> None:
    fields: dict[str, object] = {
        "durationMs": max(0, int((time.perf_counter() - started_at) * 1000)),
        "lightweight": bool(lightweight),
        "idempotencyEnabled": bool(idempotency_enabled),
        "statusCode": int(status_code),
    }
    if session_id:
        fields["sessionId"] = session_id[:160]
    if error_type:
        fields["errorType"] = str(error_type)[:80]
    try:
        record_runtime_scene_event(
            "conversation",
            "session_lifecycle",
            "conversation.session.create.request",
            level="warning" if outcome not in {"succeeded"} else "info",
            outcome=outcome,
            message="Session create HTTP request timing.",
            fields=fields,
            lifecycle=True,
        )
    except Exception:
        pass


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
    except SessionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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
    "/sessions/{session_id}/pin",
    response_model=SessionPinResponse,
    response_model_exclude_unset=True,
)
def session_pin(session_id: str) -> dict:
    try:
        return set_chat_session_pinned(session_id, pinned=True)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/sessions/{session_id}/unpin",
    response_model=SessionPinResponse,
    response_model_exclude_unset=True,
)
def session_unpin(session_id: str) -> dict:
    try:
        return set_chat_session_pinned(session_id, pinned=False)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
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
async def session_events(
    session_id: str,
    initial: str = Query("light"),
    request: Request = None,
) -> StreamingResponse:
    raw_last_event_id = request.headers.get("last-event-id") if request is not None else None
    try:
        last_event_id = session_service.parse_session_stream_last_event_id(raw_last_event_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
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
            last_event_id=last_event_id,
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
    except FileNotFoundError:
        # Document artifacts live beside images in the session workspace;
        # fall through to the document resolver before giving up.
        try:
            path, content_type = session_document_attachments.resolve_session_document_artifact(
                session_id,
                artifact_id,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Session artifact not found") from exc
    filename = path.name if download else None
    return FileResponse(path, media_type=content_type, filename=filename)


@router.post(
    "/sessions/{session_id}/prompt-suggestion",
    response_model=SessionPromptSuggestionResponse,
    response_model_exclude_unset=True,
)
def session_prompt_suggestion(
    session_id: str,
    payload: SessionPromptSuggestionPayload,
) -> dict:
    try:
        result = generate_prompt_suggestion(session_id, after_turn_id=payload.afterTurnId)
    except PromptSuggestionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"sessionId": session_id, **result}


def _composer_starters_for_detail(detail: dict | None) -> list[dict[str, str]]:
    agent_id = ""
    if isinstance(detail, dict):
        agent_id = str(detail.get("agentId") or "").strip()
    if agent_id:
        try:
            from core.web.services.financial_assistant_service import (
                composer_starters_for_agent,
            )

            specialized = composer_starters_for_agent(agent_id)
        except Exception:
            specialized = None
        if specialized:
            return specialized
    return get_composer_starter_commands(session_service.PROJECT_ROOT)


@router.get(
    "/sessions/{session_id}/composer-example",
    response_model=SessionComposerExampleResponse,
    response_model_exclude_unset=True,
)
def session_composer_example(session_id: str) -> dict:
    try:
        detail = get_session_detail(session_id, message_limit=0, transcript_scope="none")
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if detail is None:
        raise HTTPException(status_code=404, detail="Session not found")
    starters = _composer_starters_for_detail(detail)
    return {
        "command": starters[0]["command"] if starters else None,
        "starters": starters,
    }


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
        if content_type.lower().startswith("application/json"):
            # Zero-copy registration variant: the desktop shell references a
            # real local path and the backend reads the file in place. Any
            # failure answers 4xx so the client falls back to the binary
            # upload transparently.
            registration = await _read_session_attachment_registration(request)
            return _store_session_attachment_from_local_path(session_id, registration)
        payload = await _read_session_attachment_payload(session_id, request)
        # Images are identified by content sniffing; anything that does not
        # sniff as png/jpeg/webp goes to the document store, which enforces
        # its own extension/size/payload gates.
        if session_service._sniff_image_extension(payload) or content_type.lower().startswith("image/"):
            return store_session_user_image_attachment(
                session_id,
                payload,
                filename=filename,
                content_type=content_type,
            )
        return session_document_attachments.store_session_user_document_attachment(
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
    model_selection = payload.modelSelection.model_dump() if payload.modelSelection is not None else None
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
                queue_if_busy=payload.queueIfBusy,
                model_selection=model_selection,
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
            queue_if_busy=payload.queueIfBusy,
            model_selection=model_selection,
        )
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionModelSelectionError as exc:
        # Documented 400: the caller pinned a model outside the session
        # llm-options list; distinct from the generic 422 payload shape error.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SessionBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SessionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class SessionQueuedTurnUpdatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str | None = None
    position: int | None = Field(default=None, ge=1)
    status: Literal["paused", "queued"] | None = None


class SessionQueuedTurnAttachmentResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    artifactId: str
    filename: str | None = None
    contentType: str | None = None
    imageUrl: str | None = None
    sizeBytes: int | None = None


class SessionQueuedTurnReferenceResponse(BaseModel):
    """Open reference object; reference kinds add their own fields over time."""

    model_config = ConfigDict(extra="allow")


class SessionQueuedTurnModelSelectionResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    modelId: str
    reasoningEffort: str | None = None


class SessionQueuedTurnResponse(BaseModel):
    """One public queue row, preserving extra runtime-notice fields."""

    model_config = ConfigDict(extra="allow")

    id: str
    position: int
    kind: str = "user"
    status: str = "queued"
    content: str = ""
    sendNow: bool | None = None
    attachments: list[SessionQueuedTurnAttachmentResponse] = Field(default_factory=list)
    references: list[SessionQueuedTurnReferenceResponse] = Field(default_factory=list)
    lastError: str | None = None
    clientSubmissionId: str | None = None
    mentalModelEnabled: bool | None = None
    runtimeStatusEnabled: bool | None = None
    turnMode: str | None = None
    writeIntent: bool | None = None
    modelSelection: SessionQueuedTurnModelSelectionResponse | None = None
    createdAt: str | None = None
    updatedAt: str | None = None
    branchGeneration: int | None = None


class SessionQueuedTurnsResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    queuedTurns: list[SessionQueuedTurnResponse]


class SessionQueuedTurnSendNowResponse(SessionQueuedTurnsResponse):
    stopRequested: bool


@router.get(
    "/sessions/{session_id}/queued-turns",
    response_model=SessionQueuedTurnsResponse,
    response_model_exclude_unset=True,
)
def session_list_queued_turns(session_id: str) -> dict:
    return {"queuedTurns": list_session_queued_turns(session_id)}


@router.patch(
    "/sessions/{session_id}/queued-turns/{queued_turn_id}",
    response_model=SessionQueuedTurnsResponse,
    response_model_exclude_unset=True,
)
def session_update_queued_turn(
    session_id: str,
    queued_turn_id: str,
    payload: SessionQueuedTurnUpdatePayload,
) -> dict:
    try:
        rows = update_session_queued_turn(
            session_id,
            queued_turn_id,
            content=payload.content,
            position=payload.position,
            status=payload.status,
        )
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"queuedTurns": rows}


@router.delete(
    "/sessions/{session_id}/queued-turns/{queued_turn_id}",
    response_model=SessionQueuedTurnsResponse,
    response_model_exclude_unset=True,
)
def session_remove_queued_turn(session_id: str, queued_turn_id: str) -> dict:
    try:
        rows = remove_session_queued_turn(session_id, queued_turn_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"queuedTurns": rows}


class SessionQueuedTurnSendNowPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Identity of the running turn the caller saw; a mismatch (the turn
    # settled or was replaced meanwhile) rejects the stop so the promotion
    # rolls back instead of interrupting an unrelated newer turn.
    expectedTurnId: str | None = None


@router.post(
    "/sessions/{session_id}/queued-turns/{queued_turn_id}/send-now",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SessionQueuedTurnSendNowResponse,
    response_model_exclude_unset=True,
)
def session_send_now_queued_turn(
    session_id: str,
    queued_turn_id: str,
    payload: SessionQueuedTurnSendNowPayload,
) -> dict:
    try:
        result = send_now_session_queued_turn(
            session_id,
            queued_turn_id,
            expected_turn_id=payload.expectedTurnId or "",
        )
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SessionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"queuedTurns": result["queuedTurns"], "stopRequested": bool(result["stopRequested"])}


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
            base_message_id=payload.baseMessageId,
            attachment_ids=payload.attachmentIds,
        )
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SessionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/sessions/{session_id}/messages/regenerate",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SessionCatalogItem,
    response_model_exclude_unset=True,
)
def session_regenerate_message(session_id: str, payload: SessionMessageRegeneratePayload) -> dict:
    client_submission_id = str(payload.clientSubmissionId or "").strip() or _new_client_submission_id()
    try:
        return regenerate_session_message(
            session_id,
            payload.messageId,
            client_submission_id=client_submission_id,
            mental_model_enabled=payload.mentalModelEnabled,
            runtime_status_enabled=payload.runtimeStatusEnabled,
            turn_status_tail=payload.turnStatusTail if isinstance(payload.turnStatusTail, dict) else None,
            turn_mode=payload.turnMode,
            write_intent=payload.writeIntent,
            base_message_id=payload.baseMessageId,
        )
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SessionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/sessions/{session_id}/head",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SessionCatalogItem,
    response_model_exclude_unset=True,
)
def session_switch_head(session_id: str, payload: SessionHeadPayload) -> dict:
    try:
        return switch_session_head(session_id, payload.nodeId)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SessionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/sessions/{session_id}/fork",
    status_code=status.HTTP_201_CREATED,
    response_model=SessionCatalogItem,
    response_model_exclude_unset=True,
)
def session_fork_from_node(session_id: str, payload: SessionForkPayload) -> dict:
    try:
        return fork_session_from_node(session_id, payload.nodeId, scope=payload.scope)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SessionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/sessions/{session_id}/rewind/{turn_id}",
    response_model=SessionRewindPreviewResponse,
    response_model_exclude_unset=True,
)
def session_rewind_preview(session_id: str, turn_id: str) -> dict:
    try:
        preview = preview_session_rewind(session_id, turn_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if preview is None:
        raise HTTPException(
            status_code=404,
            detail="该轮次没有可回退的文件检查点。",
        )
    return preview


@router.post(
    "/sessions/{session_id}/rewind",
    response_model=SessionRewindApplyResponse,
    response_model_exclude_unset=True,
)
def session_rewind_apply(session_id: str, payload: SessionRewindApplyPayload) -> dict:
    try:
        return apply_session_rewind(
            session_id,
            payload.turnId,
            force=payload.force,
        )
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SessionRewindConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(exc),
                "unsafeFiles": list(exc.unsafe_files),
            },
        ) from exc


@router.post(
    "/sessions/{session_id}/stop",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SessionCatalogItem,
    response_model_exclude_unset=True,
)
def session_stop_turn(session_id: str, payload: SessionStopPayload) -> dict:
    try:
        return request_stop_session_turn(
            session_id,
            expected_turn_id=payload.turnId,
            fast_ack=True,
        )
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


@router.post(
    "/sessions/{session_id}/messages/{message_id}/curation",
    status_code=status.HTTP_200_OK,
    response_model=SessionMessageCurationResponse,
    response_model_exclude_unset=True,
)
def session_set_message_curation(session_id: str, message_id: str, payload: SessionMessageCurationPayload) -> dict:
    try:
        return set_session_message_curation(session_id, message_id, action=payload.action)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionMessageCurationStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SessionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/sessions/{session_id}/curation",
    status_code=status.HTTP_200_OK,
    response_model=SessionMessageCurationStateResponse,
    response_model_exclude_unset=True,
)
def session_message_curation_state(session_id: str) -> dict:
    try:
        return get_session_message_curation(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
