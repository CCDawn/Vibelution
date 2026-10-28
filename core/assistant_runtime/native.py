"""A Launcher-owned adapter over the native Agent and Session owners.

The entry point sets process role, root, data home, and config before importing
this module. No Workbench lifecycle or project assistant proxy is started here.
"""

from __future__ import annotations

import re
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from core.infrastructure.native_runtime import assistant_native_root

_LOCK = threading.RLock()
_STOP_REQUESTED = threading.Event()
_STARTED = False
_SESSION_ID = ""
_AGENT_ID = ""
_OFFLINE_MIGRATION = False
_OFFLINE_DIRECTORY_CLOSE_UNCONFIRMED = False
_QUIESCING = False
_QUIESCENCE_STATE_LOCK = threading.Lock()


def _close_offline_directory(runtime, *, timeout: float) -> None:
    """A failed directory close cannot be retried after its owner is detached."""
    global _OFFLINE_DIRECTORY_CLOSE_UNCONFIRMED
    if _OFFLINE_DIRECTORY_CLOSE_UNCONFIRMED:
        raise RuntimeError("offline_directory_close_unconfirmed")
    try:
        runtime.shutdown_session_directory_runtime(timeout=timeout)
    except Exception:
        _OFFLINE_DIRECTORY_CLOSE_UNCONFIRMED = True
        raise


_LEGACY_LAUNCHER_TOOLS = (
    "personal_assistant_action_tool", "personal_assistant_manage_tool",
    "personal_affairs_tool", "append_personal_memory_tool", "supersede_personal_memory_tool",
    "search_agent_private_memory_tool", "compress_context_tool",
)
_INITIAL_TOOLS = (*_LEGACY_LAUNCHER_TOOLS,
                  "personal_assistant_computer_observe_tool", "personal_assistant_computer_action_tool")


class AssistantSessionError(RuntimeError):
    """Bounded command failure; native exceptions and paths remain private."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _services():
    from core.web.services import (
        agent_directory_service,
        personal_assistant_service,
        session_service,
    )
    from core.web.services.session import directory_runtime

    return agent_directory_service, personal_assistant_service, session_service, directory_runtime


def _projection() -> dict[str, Any]:
    if not _STARTED:
        raise RuntimeError("native assistant is not initialized")
    _, personal, sessions, _ = _services()
    result = personal.get_personal_assistant()
    assistant = result.get("assistant") or {}
    if not assistant.get("directSessionId"):
        raise sessions.SessionNotFoundError("Launcher assistant session is unavailable")
    return result


def bootstrap(root: Path | str) -> dict[str, Any]:
    """Open one fixed native directory and explicitly provision its singleton."""
    return _bootstrap(root, offline_migration=False)


def bootstrap_for_offline_migration(root: Path | str) -> dict[str, Any]:
    """Open the native owner without resuming or admitting Session work."""
    return _bootstrap(root, offline_migration=True)


def _bootstrap(root: Path | str, *, offline_migration: bool) -> dict[str, Any]:
    global _STARTED, _SESSION_ID, _AGENT_ID, _OFFLINE_MIGRATION
    expected = assistant_native_root()
    requested = Path(root)
    if not requested.is_absolute() or requested.resolve() != expected:
        raise ValueError("native assistant root differs from the process identity")
    with _LOCK:
        if _STARTED:
            if _OFFLINE_MIGRATION != offline_migration:
                raise RuntimeError("native lifecycle mode differs from the active owner")
            return _projection()
        _STOP_REQUESTED.clear()
        directory, personal, sessions, runtime = _services()
        if sessions.PROJECT_ROOT != expected or directory.PROJECT_ROOT != expected:
            raise RuntimeError("native service roots differ from the process identity")
        opened_root = runtime.directory_store_project_root()
        if opened_root is not None and opened_root != expected:
            raise RuntimeError("a different native directory is already open")
        lifecycle = sessions.begin_session_service_lifecycle()
        if not lifecycle.get("opened"):
            raise RuntimeError("native session executors could not start")
        try:
            status = runtime.initialize_session_directory_runtime(
                project_root=expected, migrate_legacy_chat_state=False,
            )
            if status.status != "ready":
                raise RuntimeError(f"native session directory could not start: {status.status}")
            existing = personal.get_personal_assistant().get("assistant")
            if existing is None:
                policy = {
                    **personal.current_policy(),
                    "allowedTools": list(_INITIAL_TOOLS),
                    "preferredTools": list(_INITIAL_TOOLS),
                    "approvalOverrides": {},
                }
                task = {
                    **personal.TASK,
                    "responsibilities": (
                        "通过 personal_assistant_action_tool 管理 Launcher 与已登记项目；"
                        "Launcher 实时 index/describe 提供项目 Agent 管理、派遣与回执，以及助理与应用的设置/模型动作；"
                        "先发现准确对象与参数，再执行用户授权的操作。"
                        "governed=true 的动作使用 personal_assistant_manage_tool 等待原生审批，"
                        "不允许在参数中自行声明已获批准。"
                        "自己的待办、日程和目标用 personal_affairs_tool；"
                        "私人偏好和事实用 append_personal_memory_tool 记录、supersede_personal_memory_tool 更新；"
                        "自己的私有正式知识用 search_agent_private_memory_tool 查询；"
                        "上下文需要整理时用 compress_context_tool，不删除或改写原生历史。"
                        "电脑窗口操作使用原生电脑工具，只能操作用户已选择并授权的窗口。"
                        "只执行实时目录已登记的动作；目录之外的旧平台动作尚不可用。"
                    ),
                    "constraints": (
                        "这是 Launcher 本地个人助理。项目操作显式使用目录中的 project_id，"
                        "不得把本地 native root 当成目标项目，不得创建或代理目标项目的个人助理。\n"
                        + personal.TASK["constraints"].replace("\n", " ")
                    ),
                }
                # Persist the restricted policy at creation. A crash between
                # identity creation and direct-Session provisioning must never
                # leave the broader project assistant toolset behind.
                directory.create_agent_instance(
                    display_name="个人助理", primary_mode="general",
                    role_key=personal.ROLE, prompt_template_id="prompt-chat-default",
                    created_by="user_personal_assistant",
                    initial_tool_policy=policy,
                    llm_bindings=sessions.default_session_llm_bindings(),
                    metadata={
                        "personalAssistantProfile": personal.PROFILE,
                        "personalAssistantSetup": "pending",
                        "personaProfile": personal.PERSONA,
                        "taskProfile": task,
                        "delegationPolicy": {"allowSubagents": False, "allowWakeMessages": False},
                    },
                )
            # Upgrade only the exact previous Launcher default; user-edited or
            # zero-tool policies remain untouched, and migration stays read-only.
            if existing is not None and not offline_migration:
                agent_id = existing.get("agentId")
                existing = directory.get_agent(agent_id) if agent_id else None
                policy = existing.get("toolPolicy") if existing else None
                policy_id = f"tool-{agent_id}"
                old_default = {**personal.current_policy(), "allowedTools": list(_LEGACY_LAUNCHER_TOOLS),
                               "preferredTools": list(_LEGACY_LAUNCHER_TOOLS), "approvalOverrides": {}}
                if (existing is not None and existing.get("createdBy") == "user_personal_assistant"
                        and existing.get("toolPolicyId") == policy_id and isinstance(policy, dict)
                        and personal._matches_provisioning_snapshot(policy, old_default, policy_id)):
                    directory.update_agent_instance(agent_id,
                        tool_policy={**policy, "allowedTools": list(_INITIAL_TOOLS), "preferredTools": list(_INITIAL_TOOLS)},
                        expected_tool_policy_fingerprint=directory.tool_policy_fingerprint(policy))
            # Reuse native direct-Session provisioning/repair and its existing
            # preservation rules for user-authored profiles and tool policies.
            result = personal.create_personal_assistant()
            _SESSION_ID = result["assistant"]["directSessionId"]
            _AGENT_ID = result["assistant"]["agentId"]
            _OFFLINE_MIGRATION = offline_migration
            _STARTED = True
            if not offline_migration:
                from core.web.services.session.startup_recovery import (
                    recover_interrupted_session_turns_on_startup,
                )
                # Ordinary startup retains its native recovery and queue drain.
                recover_interrupted_session_turns_on_startup(should_stop=_STOP_REQUESTED.is_set)
            return _projection()
        except BaseException:
            _SESSION_ID = ""
            _AGENT_ID = ""
            if offline_migration:
                # A failed bootstrap may still own executors or a directory
                # store. Keep that ownership visible to the offline lock guard
                # until cleanup has actually succeeded.
                _STARTED = True
                _OFFLINE_MIGRATION = True
                try:
                    closed = sessions.shutdown_session_service(deadline=time.monotonic() + 5).get("closed") is True
                    if closed:
                        _close_offline_directory(runtime, timeout=5)
                        _STARTED = False
                        _OFFLINE_MIGRATION = False
                except Exception:
                    pass
            else:
                _STARTED = False
                _OFFLINE_MIGRATION = False
                sessions.shutdown_session_service(deadline=time.monotonic() + 5)
                runtime.shutdown_session_directory_runtime(timeout=5)
            raise


def get_detail(session_id: str) -> dict[str, Any]:
    """Only the current singleton's direct Session is visible to this adapter."""
    with _LOCK:
        assistant = _projection()["assistant"]
        _, _, sessions, _ = _services()
        if session_id != assistant["directSessionId"]:
            raise sessions.SessionNotFoundError("Launcher assistant session not found")
        # This endpoint is polled by the resident renderer. The native light
        # projection retains messages and execution state without computing
        # project inbox/governance/next-state side lists on every read.
        detail = sessions.get_session_detail(session_id, include_secondary=False)
        if detail is None or str(detail.get("agentId") or "") != assistant["agentId"]:
            raise sessions.SessionNotFoundError("Launcher assistant session not found")
        return detail


def identity() -> dict[str, Any]:
    """Refresh native settings without re-provisioning or changing identity."""
    with _LOCK:
        return _projection()


def submit(message: str, request_id: str, attachment_ids: list[str] | None = None) -> dict[str, Any]:
    """Use native acceptance and journal idempotency, without a second queue."""
    if not isinstance(message, str):
        raise ValueError("message must be text")  # noqa: TRY004 - preserve the existing submit contract.
    if not isinstance(request_id, str) or not request_id.strip():
        raise ValueError("request_id is required")
    with _session_command() as (sessions, session_id):
        if attachment_ids is not None:
            from . import attachments
            attachments.validate_ids(sessions, session_id, attachment_ids)
        return sessions.submit_session_message_lightweight(
            session_id, message,
            client_submission_id=request_id.strip(), queue_if_busy=True, attachment_ids=attachment_ids,
        )


def upload_attachment(payload: bytes, *, filename: str, content_type: str) -> dict[str, Any]:
    """Store bytes only in the fixed assistant Session; return public metadata."""
    from . import attachments

    with _session_command() as (sessions, session_id):
        return attachments.store(sessions, session_id, payload, filename=filename, content_type=content_type)


def read_attachment(artifact_id: str) -> tuple[bytes, str]:
    """Read an artifact belonging to the fixed assistant Session."""
    from . import attachments

    with _session_command() as (sessions, session_id):
        try:
            from .migration_io import read_stable_file
            path, content_type = attachments.resolve(session_id, artifact_id)
            snapshot = read_stable_file(path, sessions.SESSION_USER_IMAGE_MAX_BYTES)
            return snapshot.raw, content_type
        except (FileNotFoundError, OSError, ValueError):
            raise AssistantSessionError("ATTACHMENT_NOT_FOUND") from None


@contextmanager
def _session_command(*, fixed_identity_only: bool = False):
    # Commands admitted here finish before shutdown closes native admission.
    # A command waiting for this lock observes shutdown's early stop flag.
    with _LOCK:
        if _STOP_REQUESTED.is_set():
            raise AssistantSessionError("ASSISTANT_STOPPING")
        if not _STARTED:
            raise AssistantSessionError("ASSISTANT_NOT_READY")
        if _OFFLINE_MIGRATION:
            raise AssistantSessionError("OFFLINE_MIGRATION_READ_ONLY")
        if _QUIESCING and not fixed_identity_only:
            # No Session admission or Journal write has occurred. The caller
            # must retain the original request and retry it after the fence.
            raise AssistantSessionError("ASSISTANT_QUIESCING")
        _, _, sessions, _ = _services()
        try:
            if fixed_identity_only:
                if not _SESSION_ID or not _AGENT_ID:
                    raise AssistantSessionError("ASSISTANT_IDENTITY_INVALID")
                yield sessions, _SESSION_ID
                return
            assistant = _projection()["assistant"]
            if (not _SESSION_ID or not _AGENT_ID
                    or assistant.get("directSessionId") != _SESSION_ID
                    or assistant.get("agentId") != _AGENT_ID):
                raise AssistantSessionError("ASSISTANT_IDENTITY_INVALID")
            yield sessions, _SESSION_ID
        except sessions.SessionNotFoundError:
            raise AssistantSessionError("SESSION_NOT_FOUND") from None
        except sessions.SessionBusyError:
            raise AssistantSessionError("SESSION_CONFLICT") from None
        except sessions.SessionValidationError:
            raise AssistantSessionError("SESSION_INVALID") from None


@contextmanager
def session_quiescence():
    """Fence assistant commands while observing the fixed native Session.

    This is one component of a migration barrier, not proof that unrelated
    producers or external dispatches are drained. The caller must fence and
    drain those owners before entering, keep them fenced throughout, and avoid
    lifecycle shutdown until this context exits. The context and its native
    admission lock must be entered and exited by the same thread.
    """
    global _QUIESCING
    from core.chat.turn_journal import latest_open_turn_id
    from core.web.services.session import journal_bridge, tool_approvals
    from core.web.services.session.admission_lock import SessionAdmissionLock, session_has_active_work_run
    from core.web.services.session.queued_turns import QUEUED_TURN_STATE_KEY, session_queued_turn_rows

    with _LOCK:
        if _STOP_REQUESTED.is_set() or not _STARTED or _OFFLINE_MIGRATION or _QUIESCING:
            raise AssistantSessionError("ASSISTANT_QUIESCENCE_UNAVAILABLE")
        assistant = _projection()["assistant"]
        if (not _SESSION_ID or not _AGENT_ID or assistant.get("directSessionId") != _SESSION_ID
                or assistant.get("agentId") != _AGENT_ID):
            raise AssistantSessionError("ASSISTANT_IDENTITY_INVALID")
        _, _, sessions, _ = _services()
        session_id = _SESSION_ID
        with _QUIESCENCE_STATE_LOCK:
            if _STOP_REQUESTED.is_set():
                raise AssistantSessionError("ASSISTANT_QUIESCENCE_UNAVAILABLE")
            _QUIESCING = True
    try:
        # Holding native admission closes the race with native Session submit
        # producers. Producers waiting on it still need an owner-level fence.
        lock = SessionAdmissionLock(sessions.PROJECT_ROOT, session_id)
        try:
            lock.acquire(timeout=0.1)
        except sessions.SessionBusyError:
            raise AssistantSessionError("ASSISTANT_QUIESCENCE_BUSY") from None
        try:
            conversation = sessions.load_session_chat_state(sessions.PROJECT_ROOT, session_id)
            if not isinstance(conversation, dict):
                raise AssistantSessionError("ASSISTANT_QUIESCENCE_UNKNOWN")
            raw_queue = conversation.get(QUEUED_TURN_STATE_KEY, [])
            if not isinstance(raw_queue, list) or len(raw_queue) != len(session_queued_turn_rows(conversation)):
                raise AssistantSessionError("ASSISTANT_QUIESCENCE_UNKNOWN")
            events = journal_bridge.load_session_conversation_events_snapshot(
                session_id, project_root=sessions.PROJECT_ROOT,
            )
            approvals = tool_approvals.list_tool_approval_requests(session_id)
            settled_approvals = {"accepted", "accepted_for_session", "accepted_for_session_tool",
                                 "accepted_with_action_window", "accepted_always", "declined",
                                 "cancelled", "expired"}
            with sessions._RUNNING_SESSIONS_LOCK:
                active_turn = bool(sessions._SESSION_ACTIVE_TURN_IDS.get(session_id))
            if (sessions._is_session_running(session_id)
                    or active_turn
                    or latest_open_turn_id(events)
                    or raw_queue
                    or session_has_active_work_run(sessions, session_id)
                    or any(not isinstance(row, dict) or row.get("status") not in settled_approvals
                           for row in approvals)):
                raise AssistantSessionError("ASSISTANT_QUIESCENCE_BUSY")
            if _STOP_REQUESTED.is_set():
                raise AssistantSessionError("ASSISTANT_QUIESCENCE_UNAVAILABLE")
            yield
        finally:
            lock.release()
    finally:
        with _LOCK:
            with _QUIESCENCE_STATE_LOCK:
                _QUIESCING = False


@contextmanager
def _source_command():
    """A tool worker must never wait for shutdown while shutdown drains it."""
    if _STOP_REQUESTED.is_set():
        raise AssistantSessionError("ASSISTANT_STOPPING")
    if not _LOCK.acquire(blocking=False):
        raise AssistantSessionError("TASK_SOURCE_BUSY")
    try:
        if _STOP_REQUESTED.is_set():
            raise AssistantSessionError("ASSISTANT_STOPPING")
        with _session_command(fixed_identity_only=True) as command:
            yield command
    finally:
        _LOCK.release()


def read_task_source(runtime: dict, *, source_ref: dict | None = None) -> dict:
    """Private tool-only read of one admitted operator event in the fixed Journal."""
    from core.chat.turn_journal import EVENT_TURN_STARTED, EVENT_USER_MESSAGE, TERMINAL_EVENTS, load_turn_events

    try:
        root = assistant_native_root()
    except RuntimeError:
        raise AssistantSessionError("TASK_SOURCE_IDENTITY_INVALID") from None
    with _source_command() as (sessions, session_id):
        directory, _, _, directory_runtime = _services()
        trusted = directory.current_agent_runtime()
        if (not isinstance(runtime, dict) or not isinstance(trusted, dict)
            or any(not isinstance(runtime.get(key), str) or not runtime[key] or runtime[key] != trusted.get(key)
                   for key in ("agentId", "sessionId", "turnId"))
            or runtime["agentId"] != _AGENT_ID or runtime["sessionId"] != session_id
            or Path(sessions.PROJECT_ROOT).resolve() != root or Path(directory.PROJECT_ROOT).resolve() != root
            or directory_runtime.directory_store_project_root() != root
            or directory_runtime.get_open_directory_store() is None):
            raise AssistantSessionError("TASK_SOURCE_IDENTITY_INVALID")
        if source_ref is not None and (source_ref.get("agentId") != _AGENT_ID or source_ref.get("sessionId") != session_id):
            raise AssistantSessionError("TASK_SOURCE_IDENTITY_INVALID")
        events = load_turn_events(root, session_id)
        if any(event.turn_id == runtime["turnId"] and event.event_type in TERMINAL_EVENTS for event in events):
            raise AssistantSessionError("TASK_SOURCE_TURN_SETTLED")

        def operator_event(turn_id):
            rows = [event for event in events if event.session_id == session_id and event.turn_id == turn_id]
            users = [event for event in rows if event.event_type == EVENT_USER_MESSAGE]
            starts = [event for event in rows if event.event_type == EVENT_TURN_STARTED]
            if len(users) != 1 or len(starts) != 1:
                raise AssistantSessionError("TASK_SOURCE_UNAVAILABLE")
            user, start = users[0], starts[0]
            metadata = user.payload.get("metadata")
            if (not isinstance(metadata, dict) or not isinstance(metadata.get("clientSubmissionId"), str)
                or not metadata["clientSubmissionId"] or user.correlation_id != metadata["clientSubmissionId"]
                or user.source != "submit_session_message" or user.source_kind not in {"", "user", "operator"}
                or user.payload.get("source") != "raw" or metadata.get("kind") not in (None, "", "user")
                or metadata.get("turnId") not in (None, "", turn_id)
                or metadata.get("source") not in (None, "", "user", "operator", "raw")
                or any(metadata.get(key) not in (None, "", "user", "operator") for key in ("actor", "actorId", "actorType", "sourceKind"))
                or any(metadata.get(key) for key in ("agentId", "actorAgentId", "proactive", "system", "sourceAgentId"))
                or start.source != "submit_session_message" or start.payload.get("agentId") != _AGENT_ID
                or start.correlation_id != user.correlation_id
                or start.source_kind not in {"", "user", "operator"}
                or start.payload.get("source") != "raw" or user.sequence <= start.sequence
                or not user.visible_in_model):
                raise AssistantSessionError("TASK_SOURCE_NOT_OPERATOR")
            return user

        current = operator_event(runtime["turnId"])
        user = operator_event(source_ref["turnId"]) if source_ref is not None else current
        if source_ref is not None and user.event_id != source_ref.get("eventId"):
            raise AssistantSessionError("TASK_SOURCE_UNAVAILABLE")
        content = user.payload.get("content")
        if not isinstance(content, str) or not content:
            raise AssistantSessionError("TASK_SOURCE_UNAVAILABLE")
        return {"agentId": _AGENT_ID, "sessionId": session_id, "turnId": user.turn_id,
                "eventId": user.event_id, "content": content}


def stop(turn_id: str) -> dict[str, Any]:
    """Stop the selected native turn and freeze its queued rows, as Chat does."""
    if not isinstance(turn_id, str) or not turn_id.strip() or len(turn_id) > 160:
        raise AssistantSessionError("SESSION_INVALID")
    with _session_command() as (sessions, session_id):
        from core.web.services.session.queued_turns import set_session_queue_hold

        ack = sessions.request_stop_session_turn(
            session_id, expected_turn_id=turn_id.strip(), fast_ack=True,
        )
        set_session_queue_hold(session_id, turn_id=turn_id.strip())
        return ack


def continue_turn(request_id: str, continuation: dict[str, Any]) -> dict[str, Any]:
    """Admit one fixed continuation against the native settled snapshot."""
    if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", request_id):
        raise AssistantSessionError("SESSION_INVALID")
    if not isinstance(continuation, dict):
        raise AssistantSessionError("SESSION_INVALID")
    with _session_command() as (sessions, session_id):
        return sessions.submit_session_message_lightweight(
            session_id, "继续", client_submission_id=request_id,
            queue_if_busy=False, _continuation_expected=dict(continuation),
        )


def shutdown(*, timeout: float = 8.0) -> dict[str, Any]:
    """Stop owned native work and drain it before closing its directory store."""
    global _STARTED, _SESSION_ID, _AGENT_ID, _OFFLINE_MIGRATION
    deadline = time.monotonic() + max(0.0, timeout)
    with _QUIESCENCE_STATE_LOCK:
        if _QUIESCING:
            return {"closed": False, "code": "NATIVE_QUIESCENCE_ACTIVE"}
        _STOP_REQUESTED.set()
    remaining = max(0.0, deadline - time.monotonic())
    admitted = _LOCK.acquire(timeout=remaining) if remaining > 0 else _LOCK.acquire(blocking=False)
    if not admitted:
        return {"closed": False, "code": "NATIVE_SHUTDOWN_ADMISSION_BUSY"}
    try:
        if _OFFLINE_MIGRATION and _OFFLINE_DIRECTORY_CLOSE_UNCONFIRMED:
            raise RuntimeError("offline_directory_close_unconfirmed")
        if not _STARTED:
            return {"closed": True}
        _, _, sessions, runtime = _services()
        sessions.stop_session_service_admission()
        if not _OFFLINE_MIGRATION:
            try:
                sessions.request_stop_session_turn(
                    _SESSION_ID, fast_ack=True, stop_reason="launcher_assistant_shutdown",
                )
            except sessions.SessionNotFoundError:
                # A removed singleton must not strand this process's executors.
                pass
        result = sessions.shutdown_session_service(deadline=deadline)
        if result.get("closed"):
            if _OFFLINE_MIGRATION:
                _close_offline_directory(runtime, timeout=max(0.0, deadline - time.monotonic()))
            else:
                runtime.shutdown_session_directory_runtime(timeout=max(0.0, deadline - time.monotonic()))
            _STARTED = False
            _OFFLINE_MIGRATION = False
            _SESSION_ID = ""
            _AGENT_ID = ""
        return result
    finally:
        _LOCK.release()
