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
_INITIAL_TOOLS = (
    "personal_assistant_action_tool", "personal_assistant_manage_tool",
    "personal_affairs_tool", "append_personal_memory_tool", "supersede_personal_memory_tool",
    "search_agent_private_memory_tool", "compress_context_tool",
)


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
    global _STARTED, _SESSION_ID, _AGENT_ID
    expected = assistant_native_root()
    requested = Path(root)
    if not requested.is_absolute() or requested.resolve() != expected:
        raise ValueError("native assistant root differs from the process identity")
    with _LOCK:
        if _STARTED:
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
            # Reuse native direct-Session provisioning/repair and its existing
            # preservation rules for user-authored profiles and tool policies.
            result = personal.create_personal_assistant()
            _SESSION_ID = result["assistant"]["directSessionId"]
            _AGENT_ID = result["assistant"]["agentId"]
            _STARTED = True
            from core.web.services.session.startup_recovery import (
                recover_interrupted_session_turns_on_startup,
            )

            # This owner reads only the already-bound native root. Its operator
            # switch, retry ledger, and queue drain remain the native authority.
            recover_interrupted_session_turns_on_startup(should_stop=_STOP_REQUESTED.is_set)
            return _projection()
        except BaseException:
            _STARTED = False
            _SESSION_ID = ""
            _AGENT_ID = ""
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


def submit(message: str, request_id: str) -> dict[str, Any]:
    """Use native acceptance and journal idempotency, without a second queue."""
    if not isinstance(message, str):
        raise ValueError("message must be text")  # noqa: TRY004 - preserve the existing submit contract.
    if not isinstance(request_id, str) or not request_id.strip():
        raise ValueError("request_id is required")
    with _session_command() as (sessions, session_id):
        return sessions.submit_session_message_lightweight(
            session_id, message,
            client_submission_id=request_id.strip(), queue_if_busy=True,
        )


@contextmanager
def _session_command(*, fixed_identity_only: bool = False):
    # Commands admitted here finish before shutdown closes native admission.
    # A command waiting for this lock observes shutdown's early stop flag.
    with _LOCK:
        if _STOP_REQUESTED.is_set():
            raise AssistantSessionError("ASSISTANT_STOPPING")
        if not _STARTED:
            raise AssistantSessionError("ASSISTANT_NOT_READY")
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
    global _STARTED, _SESSION_ID, _AGENT_ID
    deadline = time.monotonic() + max(0.0, timeout)
    _STOP_REQUESTED.set()
    remaining = max(0.0, deadline - time.monotonic())
    admitted = _LOCK.acquire(timeout=remaining) if remaining > 0 else _LOCK.acquire(blocking=False)
    if not admitted:
        return {"closed": False, "code": "NATIVE_SHUTDOWN_ADMISSION_BUSY"}
    try:
        if not _STARTED:
            return {"closed": True}
        _, _, sessions, runtime = _services()
        sessions.stop_session_service_admission()
        try:
            sessions.request_stop_session_turn(
                _SESSION_ID, fast_ack=True, stop_reason="launcher_assistant_shutdown",
            )
        except sessions.SessionNotFoundError:
            # A removed singleton must not strand this process's executors.
            pass
        result = sessions.shutdown_session_service(deadline=deadline)
        if result.get("closed"):
            runtime.shutdown_session_directory_runtime(timeout=max(0.0, deadline - time.monotonic()))
            _STARTED = False
            _SESSION_ID = ""
            _AGENT_ID = ""
        return result
    finally:
        _LOCK.release()
