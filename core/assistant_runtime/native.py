"""A Launcher-owned adapter over the native Agent and Session owners.

The entry point sets process role, root, data home, and config before importing
this module. No Workbench lifecycle or project assistant proxy is started here.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from core.infrastructure.native_runtime import assistant_native_root

_LOGGER = logging.getLogger(__name__)
_LOCK = threading.RLock()
# Serialize native commands and lifecycle transitions. Read projections sample
# the binding under this lock and do their I/O outside it.
# Detail hydration can repair a Session row or journal. Its separate lease
# lets sends proceed while still fencing repairs at shutdown and migration.
_DETAIL_LIFECYCLE_LOCK = threading.Lock()
LOCK_HOLD_WARN_SECONDS = 1.0
_STOP_REQUESTED = threading.Event()
_STARTED = False
_SESSION_ID = ""
_AGENT_ID = ""
_LIFECYCLE_GENERATION = 0
_RECENT_ACCEPTED_TURN_LIMIT = 128
_RECENT_ACCEPTED_TURNS: OrderedDict[tuple[str, str, int, str], str] = OrderedDict()
_OFFLINE_MIGRATION = False
_OFFLINE_DIRECTORY_CLOSE_UNCONFIRMED = False
_QUIESCING = False
_QUIESCENCE_STATE_LOCK = threading.Lock()


@contextmanager
def _measured_lock(operation: str):
    """Measure lock holds and slow send admission waits without logging payloads."""
    requested = time.monotonic()
    wait_seconds = 0.0
    held_seconds = 0.0
    try:
        with _LOCK:
            entered = time.monotonic()
            wait_seconds = entered - requested
            try:
                yield
            finally:
                held_seconds = time.monotonic() - entered
    finally:
        if held_seconds >= LOCK_HOLD_WARN_SECONDS:
            _LOGGER.warning("assistant_native_lock_hold operation=%s held_ms=%d",
                            operation, round(held_seconds * 1000))
        if operation == "submit" and wait_seconds >= LOCK_HOLD_WARN_SECONDS:
            _LOGGER.warning("assistant_native_lock_wait operation=submit wait_ms=%d", round(wait_seconds * 1000))


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

# These optional rescue tools shipped in the default policy before they had
# runtime registrations. Keep the saved policy for a future registration.
_OPTIONAL_RESCUE_TOOLS = frozenset({
    "personal_assistant_git_tool",
    "personal_assistant_startup_diagnosis_tool",
})


def project_tool_policy(agent_id: str, policy: Mapping[str, Any], registered_names: Sequence[str]) -> Mapping[str, Any]:
    """Use the registered subset of optional tools for the native assistant."""
    if not _STARTED or agent_id != _AGENT_ID:
        return policy
    unavailable = _OPTIONAL_RESCUE_TOOLS.difference(registered_names)
    if not unavailable:
        return policy
    projected = dict(policy)
    for field in ("allowedTools", "preferredTools"):
        values = projected.get(field)
        if isinstance(values, (list, tuple, set, frozenset)):
            projected[field] = [name for name in values if str(name or "").strip() not in unavailable]
    overrides = projected.get("approvalOverrides")
    if isinstance(overrides, Mapping):
        projected["approvalOverrides"] = {
            name: mode for name, mode in overrides.items() if str(name).strip() not in unavailable
        }
    return projected


# Launcher detail reads a bounded recent window, aligned with the native session
# detail window ceiling (_SESSION_DETAIL_MESSAGE_WINDOW_MAX_LIMIT) and the
# ordinary chat page's windowed reads. An unbounded read re-serialized the whole
# history into every polled host response until the 8 MiB IPC cap rejected it
# permanently (ASSISTANT_RESPONSE_TOO_LARGE) on long sessions. The window scope
# additionally slims per-turn diagnostics exactly like the chat page payload;
# committed final answers and acceptance metadata stay intact.
LAUNCHER_ASSISTANT_DETAIL_MESSAGE_LIMIT = 200


class AssistantSessionError(RuntimeError):
    """Bounded command failure; native exceptions and paths remain private."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _settings_identity_error(exc: AssistantSessionError) -> AssistantSessionError:
    """Converge settings-command identity breaks onto one rebuild code.

    Settings reads/writes bind to the fixed singleton identity. When that
    binding can no longer be resolved (projection mismatch, or the singleton
    lost its direct Session), the only remedy is refreshing status or
    rebuilding the native assistant — never replaying the command. The bare
    unprefixed SESSION_NOT_FOUND would fall through the desktop's structured
    passthrough into its status-only fallback, which folds it back into a
    retryable "unavailable" code; ASSISTANT_IDENTITY_INVALID survives the
    whole transport and the desktop routes it to refresh/rebuild.
    """
    if exc.code == "SESSION_NOT_FOUND":
        return AssistantSessionError("ASSISTANT_IDENTITY_INVALID")
    return exc


def _services():
    from core.web.services import (
        agent_directory_service,
        personal_assistant_service,
        session_service,
    )
    from core.web.services.session import directory_runtime

    return agent_directory_service, personal_assistant_service, session_service, directory_runtime


def _initial_tools() -> tuple[str, ...]:
    """Resolve the current provisioning tool surface without a module import cycle."""
    _, personal, _, _ = _services()
    return (
        *_LEGACY_LAUNCHER_TOOLS,
        "personal_assistant_computer_observe_tool",
        "personal_assistant_computer_action_tool",
        *personal.DEV_TOOLS,
    )


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


def _configure_tool_budgets() -> None:
    """The isolated Launcher process must outlive its 120s native chooser.

    Register the canonical wrapper with the existing executor API. Ordinary
    project processes retain their own default budgets and tool functions.
    """
    from core.infrastructure.tool_executor import get_tool_executor
    from tools.Key_Tools import create_key_tools
    from .actions import configure_action_result_budget

    tool = next(tool for tool in create_key_tools() if tool.name == "personal_assistant_manage_tool")
    get_tool_executor().register_tool(tool.name, tool.func, timeout=130)
    configure_action_result_budget()


def _bootstrap(root: Path | str, *, offline_migration: bool) -> dict[str, Any]:
    global _STARTED, _SESSION_ID, _AGENT_ID, _OFFLINE_MIGRATION, _LIFECYCLE_GENERATION
    expected = assistant_native_root()
    requested = Path(root)
    if not requested.is_absolute() or requested.resolve() != expected:
        raise ValueError("native assistant root differs from the process identity")
    with _measured_lock("bootstrap"):
        if _STARTED:
            if _OFFLINE_MIGRATION != offline_migration:
                raise RuntimeError("native lifecycle mode differs from the active owner")
            return _projection()
        if not offline_migration:
            _configure_tool_budgets()
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
                    "allowedTools": list(_initial_tools()),
                    "preferredTools": list(_initial_tools()),
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
                        "网页任务先用 browser_state 获取当前页签；已有目标用 browser_select 或 browser_ensure 复用，"
                        "用 browser_show 显示现有工作区，并用 browser_read 重新观察后判断结果。"
                        "内置网页与用户授权的桌面窗口是不同控制面；不得把网页已打开当成桌面窗口已授权。"
                        "授权或交回控制后先重新观察，不重放未知结果的点击、输入或提交；"
                        "不得根据旧对话宣称当前页面仍打开、已经授权或任务已完成。"
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
                        tool_policy={**policy, "allowedTools": list(_initial_tools()), "preferredTools": list(_initial_tools())},
                        expected_tool_policy_fingerprint=directory.tool_policy_fingerprint(policy))
            # Reuse native direct-Session provisioning/repair and its existing
            # preservation rules for user-authored profiles and tool policies.
            result = personal.create_personal_assistant()
            _SESSION_ID = result["assistant"]["directSessionId"]
            _AGENT_ID = result["assistant"]["agentId"]
            _LIFECYCLE_GENERATION += 1
            _RECENT_ACCEPTED_TURNS.clear()
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


def _session_read_binding(*, repairing: bool = False) -> tuple[str, str, int]:
    with _measured_lock("session_read_binding"):
        if _STOP_REQUESTED.is_set():
            raise AssistantSessionError("ASSISTANT_STOPPING")
        if not _STARTED:
            raise AssistantSessionError("ASSISTANT_NOT_READY")
        if repairing and _QUIESCING:
            raise AssistantSessionError("ASSISTANT_QUIESCING")
        if not _SESSION_ID or not _AGENT_ID:
            raise AssistantSessionError("ASSISTANT_IDENTITY_INVALID")
        return _SESSION_ID, _AGENT_ID, _LIFECYCLE_GENERATION


def _verify_session_read_binding(sessions, binding: tuple[str, str, int]) -> None:
    session_id, agent_id, _ = binding
    try:
        assistant = _projection()["assistant"]
    except sessions.SessionNotFoundError:
        raise AssistantSessionError("SESSION_NOT_FOUND") from None
    finally:
        if _session_read_binding() != binding:
            raise AssistantSessionError("ASSISTANT_IDENTITY_INVALID")
    if assistant.get("directSessionId") != session_id or assistant.get("agentId") != agent_id:
        raise AssistantSessionError("ASSISTANT_IDENTITY_INVALID")


def get_detail(session_id: str, *, before_message_index: int | None = None) -> dict[str, Any]:
    """Only the current singleton's direct Session is visible to this adapter."""
    with _DETAIL_LIFECYCLE_LOCK:
        binding = _session_read_binding(repairing=True)
        _, _, sessions, _ = _services()
        if session_id != binding[0]:
            raise sessions.SessionNotFoundError("Launcher assistant session not found")
        _verify_session_read_binding(sessions, binding)
        # Ledger replay must not delay native admission. Publish only after
        # verifying that the same binding still owns the projected detail.
        projection_started = time.monotonic()
        try:
            detail = sessions.get_session_detail(
                session_id,
                include_secondary=False,
                message_limit=LAUNCHER_ASSISTANT_DETAIL_MESSAGE_LIMIT,
                transcript_scope="window",
                read_only=True,
                **({"before_message_index": before_message_index} if before_message_index is not None else {}),
            )
        finally:
            elapsed = time.monotonic() - projection_started
            if elapsed >= LOCK_HOLD_WARN_SECONDS:
                _LOGGER.warning("assistant_native_read operation=get_detail phase=projection elapsed_ms=%d",
                                round(elapsed * 1000))
        _verify_session_read_binding(sessions, binding)
        if detail is None or detail.get("id") != session_id or detail.get("agentId") != binding[1]:
            raise sessions.SessionNotFoundError("Launcher assistant session not found")
        return detail


def identity() -> dict[str, Any]:
    """Refresh native settings without re-provisioning or changing identity."""
    with _measured_lock("identity"):
        return _projection()


def assistant_settings() -> dict[str, Any]:
    """Read the singleton owner's safe settings without model execution."""
    with _measured_lock("assistant_settings"):
        _, personal, _, _ = _services()
        with personal._LOCK:
            assistant = _projection()["assistant"]
            if (not _AGENT_ID or not _SESSION_ID or assistant.get("agentId") != _AGENT_ID
                    or assistant.get("directSessionId") != _SESSION_ID):
                raise AssistantSessionError("ASSISTANT_IDENTITY_INVALID")
            settings = personal.get_personal_assistant_settings().get("settings")
            if not isinstance(settings, dict):
                raise AssistantSessionError("ASSISTANT_MODEL_UNAVAILABLE")
            model = settings.get("model") or {}
            fields = ("modelId", "label", "providerLabel", "isDefault", "providerHealthy",
                      "missingApiKey", "availability")
            return {"ok": True, "verified": True, "status": "completed",
                    "displayName": settings.get("displayName", ""),
                    "preferences": {key: value for key, value in (settings.get("preferences") or {}).items()
                                    if key in personal.PREFERENCES_FIELDS},
                    "modelId": model.get("currentModelId", ""),
                    "modelChoices": [{key: row[key] for key in fields if key in row}
                                     for row in model.get("choices", []) if isinstance(row, dict)],
                    "managementPermission": settings["managementPermission"]}


def set_management_permission(preset: str, expected_revision: int) -> dict[str, str | int]:
    """Change only future management admissions; pending approvals stay pending."""
    from core.web.services.local_assistant import management_permissions
    if (not isinstance(preset, str) or preset not in management_permissions.PERMISSION_PRESETS
            or not management_permissions._valid_revision(expected_revision)):
        raise AssistantSessionError("ASSISTANT_PERMISSION_INVALID")
    try:
        with _session_command():
            _, personal, _, _ = _services()
            with personal._LOCK:
                expected_agent_id, expected_session_id = _AGENT_ID, _SESSION_ID
                # Recheck the same fixed Agent/Session while holding its owner
                # lock. Deliberately do not require idle work or settle approvals.
                assistant_settings()
                return management_permissions.update(preset, expected_revision,
                    expected_agent_id=expected_agent_id, expected_session_id=expected_session_id)
    except management_permissions.ManagementPermissionError as exc:
        raise AssistantSessionError(exc.code) from None
    except AssistantSessionError as exc:
        # Every AssistantSessionError here already names its root cause
        # (identity break, stopping, quiescing, session conflict). Folding
        # them into ASSISTANT_PERMISSION_UNAVAILABLE made the desktop treat a
        # terminal identity break as a retryable permission outage; only an
        # unclassified infrastructure failure keeps that generic code below.
        raise _settings_identity_error(exc) from None
    except Exception:
        raise AssistantSessionError("ASSISTANT_PERMISSION_UNAVAILABLE") from None


@contextmanager
def _budget_parameters_command():
    """Keep both sides of the fixed binding stable through the owner call."""
    try:
        with _session_command() as (sessions, session_id):
            directory, personal, _, _ = _services()
            with personal._LOCK, sessions.session_agent_lifecycle_transaction(), directory._STATE_LOCK:
                assistant_settings()
                if sessions._session_agent_id_snapshot(session_id) != _AGENT_ID:
                    # The Session's bound agent moved: an identity break, not a
                    # busy budget endpoint. A retryable code here made the
                    # desktop loop a write that can never bind again.
                    raise AssistantSessionError("ASSISTANT_IDENTITY_INVALID")
                yield sessions, session_id
    except AssistantSessionError as exc:
        # Real codes pass through: ASSISTANT_BUDGET_CONFLICT (refresh and
        # re-save), ASSISTANT_BUDGET_INVALID, lifecycle states, and the
        # identity code above. Only unclassified failures keep the generic
        # budget-unavailable fold below.
        raise _settings_identity_error(exc) from None
    except Exception:
        raise AssistantSessionError("ASSISTANT_BUDGET_UNAVAILABLE") from None


def usage_summary() -> dict[str, Any]:
    """Read the real ledger only while the fixed native binding is stable."""
    from .cache_usage import read_usage_summary

    try:
        with _session_command() as (sessions, session_id):
            directory, personal, _, directory_runtime = _services()
            with personal._LOCK, sessions.session_agent_lifecycle_transaction(), directory._STATE_LOCK:
                root = assistant_native_root()
                if (sessions.PROJECT_ROOT != root or directory.PROJECT_ROOT != root
                        or directory_runtime.directory_store_project_root() != root):
                    raise AssistantSessionError("ASSISTANT_USAGE_UNAVAILABLE")
                agent = directory.get_agent_parameter_snapshot(_AGENT_ID, include_archived=False)
                if (not agent or agent.get("agentId") != _AGENT_ID
                        or agent.get("directSessionId") != session_id
                        or sessions._session_agent_id_snapshot(session_id) != _AGENT_ID):
                    # The fixed Agent/Session binding no longer resolves: an
                    # identity break, reported as such instead of a retryable
                    # usage outage.
                    raise AssistantSessionError("ASSISTANT_IDENTITY_INVALID")
                return read_usage_summary(project_root=root, session_id=session_id, agent_id=_AGENT_ID)
    except AssistantSessionError as exc:
        raise _settings_identity_error(exc) from None
    except Exception:
        raise AssistantSessionError("ASSISTANT_USAGE_UNAVAILABLE") from None


def budget_parameters() -> dict[str, int | None]:
    """Read only the fixed assistant's canonical Session budget override."""
    from .budget_parameters import AssistantBudgetParameters

    with _budget_parameters_command() as (sessions, session_id):
        return AssistantBudgetParameters.model_validate(
            sessions.get_session_budget_parameters_view(session_id)
        ).model_dump()


def set_budget_parameters(max_calls_per_turn: int | None, expected_revision: int) -> dict[str, int | None]:
    """Save for later turns without changing a running turn's accepted budget."""
    from .budget_parameters import AssistantBudgetParameters

    try:
        payload = AssistantBudgetParameters(revision=expected_revision, maxCallsPerTurn=max_calls_per_turn)
    except ValueError:
        raise AssistantSessionError("ASSISTANT_BUDGET_INVALID") from None
    with _budget_parameters_command() as (sessions, session_id):
        try:
            result = sessions.update_session_budget_parameters(
                session_id, expected_revision=payload.revision,
                max_calls_per_turn=payload.maxCallsPerTurn,
            )
        except sessions.SessionBudgetParametersConflictError:
            raise AssistantSessionError("ASSISTANT_BUDGET_CONFLICT") from None
        return AssistantBudgetParameters.model_validate(result).model_dump()


def set_model(model_id: str) -> dict[str, str]:
    """Rebind only this assistant through its existing settings owner."""
    from core.web.services import agent_directory_service as directory
    from core.web.services.session.admission_lock import SessionAdmissionLock

    if (not isinstance(model_id, str) or not 1 <= len(model_id) <= 200
            or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in model_id)):
        raise AssistantSessionError("ASSISTANT_MODEL_INVALID")
    # Unlike the budget endpoint — whose write is scoped to future turns by
    # update_session_budget_parameters, so running turns keep their snapshotted
    # parameters — a model rebind takes effect for the running turn's next LLM
    # call. Rebinding mid-turn could mix providers inside one turn, so this
    # endpoint deliberately fences on a fully idle Session. That asymmetry is
    # intentional; do not "align" it with the budget endpoint.
    try:
        with _session_command() as (sessions, session_id):
            _, personal, _, _ = _services()
            with personal._LOCK:
                # Recheck under the singleton owner's lock before any mutation.
                assistant_settings()
                lock = SessionAdmissionLock(sessions.PROJECT_ROOT, session_id)
                try:
                    lock.acquire(timeout=0.1)
                except sessions.SessionBusyError:
                    raise AssistantSessionError("ASSISTANT_MODEL_BUSY") from None
                try:
                    try:
                        _assert_session_idle(sessions, session_id)
                    except AssistantSessionError as exc:
                        # Busy keeps the dedicated 409; a stop already requested
                        # surfaces its real lifecycle code; only an unverifiable
                        # idle state keeps the retryable unavailable fold.
                        if exc.code == "ASSISTANT_QUIESCENCE_BUSY":
                            raise AssistantSessionError("ASSISTANT_MODEL_BUSY") from None
                        if exc.code == "ASSISTANT_QUIESCENCE_UNAVAILABLE":
                            raise AssistantSessionError("ASSISTANT_STOPPING") from None
                        raise AssistantSessionError("ASSISTANT_MODEL_UNAVAILABLE") from None
                    try:
                        personal.update_personal_assistant_model(model_id)
                    except directory.AgentStateConflictError:
                        # The agent document moved underneath the rebind:
                        # refresh and re-pick, not a retryable outage.
                        raise AssistantSessionError("ASSISTANT_MODEL_CONFLICT") from None
                    except directory.AgentDirectoryError:
                        raise AssistantSessionError("ASSISTANT_MODEL_INVALID") from None
                    observed = assistant_settings()["modelId"]
                    if observed != model_id:
                        raise AssistantSessionError("ASSISTANT_MODEL_UNAVAILABLE")
                    return {"modelId": observed}
                finally:
                    lock.release()
    except AssistantSessionError as exc:
        raise _settings_identity_error(exc) from None


def _assistant_avatar_agent() -> dict[str, Any]:
    from .assistant_avatar import _config_path
    _config_path()  # Missing config must not trigger any owner initialization.
    if not _STARTED or not _AGENT_ID or not _SESSION_ID:
        raise ValueError("assistant_avatar_unavailable")
    assistant = _projection().get("assistant") or {}
    if assistant.get("agentId") != _AGENT_ID or assistant.get("directSessionId") != _SESSION_ID:
        raise ValueError("assistant_avatar_unavailable")
    directory, _, _, _ = _services()
    agent = directory.get_agent_parameter_snapshot(_AGENT_ID, include_archived=False)
    if not agent or agent.get("agentId") != _AGENT_ID or agent.get("directSessionId") != _SESSION_ID:
        raise ValueError("assistant_avatar_unavailable")
    return agent


def assistant_avatar_revision() -> str | None:
    try:
        from .assistant_avatar import revision
        with _measured_lock("avatar_revision"):
            return revision(_assistant_avatar_agent())
    except Exception:  # noqa: BLE001 - asset failures must not break lightweight status.
        return None


def read_assistant_avatar() -> dict[str, Any]:
    try:
        from .assistant_avatar import read
        with _measured_lock("avatar_read"):
            agent = _assistant_avatar_agent()
            result = read(agent)
            if agent != _assistant_avatar_agent():
                raise ValueError("assistant_avatar_unavailable")
            return result
    except Exception:  # noqa: BLE001 - never disclose paths or native owner errors.
        raise ValueError("assistant_avatar_unavailable") from None


def submit(message: str, request_id: str, attachment_ids: list[str] | None = None,
           references: list[dict[str, Any]] | None = None,
           control_continuation: dict[str, Any] | None = None) -> dict[str, Any]:
    """Use native acceptance and journal idempotency, without a second queue."""
    if not isinstance(message, str):
        raise ValueError("message must be text")  # noqa: TRY004 - preserve the existing submit contract.
    if not isinstance(request_id, str) or not request_id.strip():
        raise ValueError("request_id is required")
    normalized_request_id = request_id.strip()
    expected = None
    if control_continuation is not None:
        from .control_continuation import CONTROL_CONTINUATION_MESSAGE, normalize_control_continuation
        try:
            expected = normalize_control_continuation(control_continuation)
        except ValueError:
            raise AssistantSessionError("SESSION_INVALID") from None
        if (message != CONTROL_CONTINUATION_MESSAGE or attachment_ids or references
                or re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", request_id) is None):
            raise AssistantSessionError("SESSION_INVALID")
    with _session_command(operation="submit") as (sessions, session_id):
        if expected is not None:
            if expected["sessionId"] != session_id or expected["agentId"] != _AGENT_ID:
                raise AssistantSessionError("ASSISTANT_IDENTITY_INVALID")
            from .control_continuation import submit_control_continuation
            accepted = submit_control_continuation(sessions, session_id, message, request_id, expected)
        else:
            if attachment_ids is not None:
                from . import attachments
                attachments.validate_ids(sessions, session_id, attachment_ids)
            accepted = sessions.submit_session_message_lightweight(
                session_id, message,
                client_submission_id=normalized_request_id, queue_if_busy=True, attachment_ids=attachment_ids,
                references=references,
            )
        _remember_accepted_turn(session_id, normalized_request_id, accepted)
        return accepted


def _remember_accepted_turn(session_id: str, request_id: str, accepted: dict[str, Any]) -> None:
    # The submission owner has already persisted acceptance. Keep this
    # shortcut under native admission's lock, before returning the HTTP ACK.
    if (not isinstance(accepted, dict) or accepted.get("accepted") is not True
            or accepted.get("sessionId") != session_id or accepted.get("clientSubmissionId") != request_id
            or accepted.get("queuedTurnId") or re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", request_id) is None):
        return
    turn_id = accepted.get("turnId")
    if not isinstance(turn_id, str) or re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", turn_id) is None:
        return
    key = (session_id, _AGENT_ID, _LIFECYCLE_GENERATION, request_id)
    _RECENT_ACCEPTED_TURNS[key] = turn_id
    _RECENT_ACCEPTED_TURNS.move_to_end(key)
    if len(_RECENT_ACCEPTED_TURNS) > _RECENT_ACCEPTED_TURN_LIMIT:
        _RECENT_ACCEPTED_TURNS.popitem(last=False)


def _receipt_session_state(personal, runtime, pin, binding: tuple[str, str, int]) -> dict[str, Any]:
    session_id, agent_id, _ = binding
    try:
        agent = personal._profile_agent()
        conversation = pin.store.repository.get_session_runtime_state(session_id)
    finally:
        if _session_read_binding() != binding:
            raise AssistantSessionError("ASSISTANT_IDENTITY_INVALID")
        if not runtime.directory_store_pin_is_current(pin):
            raise AssistantSessionError("ASSISTANT_NOT_READY")
    if (not agent or agent.get("agentId") != agent_id or agent.get("directSessionId") != session_id
            or agent.get("status") != "active" or not personal._owns_session(agent, conversation)):
        raise AssistantSessionError("ASSISTANT_IDENTITY_INVALID")
    return conversation


def _persisted_submission_proof(project_root, session_id: str, request_id: str,
                                conversation: dict[str, Any]) -> dict[str, str] | None:
    from core.chat.turn_journal import EVENT_USER_MESSAGE
    from core.web.services.session.journal_bridge import (
        load_session_conversation_events_by_correlation,
    )
    from core.web.services.session.queued_turns import (
        KIND_USER,
        session_queued_turn_rows,
    )

    # Promotion persists the user event before removing the queued row. Read
    # the queue first so a promotion in flight can be observed on either side.
    queued = next((row for row in session_queued_turn_rows(conversation)
                   if row["kind"] == KIND_USER and row.get("clientSubmissionId") == request_id), None)
    if queued is not None:
        return {"queuedTurnId": queued["id"]}
    events = load_session_conversation_events_by_correlation(
        session_id, event_type=EVENT_USER_MESSAGE, correlation_id=request_id, project_root=project_root,
    )
    turn_ids = {event.turn_id for event in events
                if event.session_id == session_id and event.correlation_id == request_id and event.turn_id}
    return {"turnId": turn_ids.pop()} if len(turn_ids) == 1 else None


def get_submission_receipt(session_id: str, request_id: str) -> dict[str, Any]:
    """Read existing acceptance from the fixed binding's already-open store."""
    binding = _session_read_binding()
    if session_id != binding[0]:
        raise AssistantSessionError("ASSISTANT_IDENTITY_INVALID")
    _, personal, sessions, runtime = _services()
    pin = runtime.pin_open_directory_store(sessions.PROJECT_ROOT)
    if pin is None:
        raise AssistantSessionError("ASSISTANT_NOT_READY")
    conversation = _receipt_session_state(personal, runtime, pin, binding)
    with _LOCK:
        turn_id = _RECENT_ACCEPTED_TURNS.get((*binding, request_id))
    proof = {"turnId": turn_id} if turn_id is not None else _persisted_submission_proof(
        sessions.PROJECT_ROOT, session_id, request_id, conversation,
    )
    _receipt_session_state(personal, runtime, pin, binding)
    if proof is not None and "turnId" in proof:
        with sessions._RUNNING_SESSIONS_LOCK:
            turn_active = (session_id in sessions._RUNNING_SESSION_IDS
                           and sessions._SESSION_ACTIVE_TURN_IDS.get(session_id) == proof["turnId"])
        proof = {**proof, "turnActive": turn_active}
    acceptance = None if proof is None else {
        "accepted": True, "sessionId": session_id, "clientSubmissionId": request_id, **proof,
    }
    return {"sessionId": session_id, "requestId": request_id, "acceptance": acceptance}


def upload_attachment(payload: bytes, *, filename: str, content_type: str) -> dict[str, Any]:
    """Store bytes only in the fixed assistant Session; return public metadata."""
    from . import attachments

    with _session_command() as (sessions, session_id):
        return attachments.store(sessions, session_id, payload, filename=filename, content_type=content_type)


def upload_secret_attachment(value: str, *, kind: str = "secret", label: str = "") -> dict[str, Any]:
    """Stage a privacy attachment in process memory; never persist or log it.

    The plaintext stays in the secret store and only the one-shot ``sec_``
    reference id (plus channel kind and optional display label) is returned.
    """
    from . import attachments

    with _session_command():
        try:
            return attachments.store_secret(value, kind=kind, label=label)
        except ValueError:
            raise AssistantSessionError("SESSION_INVALID") from None


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
def _session_command(*, fixed_identity_only: bool = False, operation: str = "session_command"):
    # Commands admitted here finish before shutdown closes native admission.
    # A command waiting for this lock observes shutdown's early stop flag.
    with _measured_lock(operation):
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


def _assert_session_idle(sessions, session_id):
    from core.chat.turn_journal import latest_open_turn_id
    from core.web.services.session import journal_bridge, tool_approvals
    from core.web.services.session.admission_lock import session_has_active_work_run
    from core.web.services.session.queued_turns import QUEUED_TURN_STATE_KEY, session_queued_turn_rows
    conversation = sessions.load_session_chat_state(sessions.PROJECT_ROOT, session_id)
    if not isinstance(conversation, dict):
        raise AssistantSessionError("ASSISTANT_QUIESCENCE_UNKNOWN")
    raw_queue = conversation.get(QUEUED_TURN_STATE_KEY, [])
    if not isinstance(raw_queue, list) or len(raw_queue) != len(session_queued_turn_rows(conversation)):
        raise AssistantSessionError("ASSISTANT_QUIESCENCE_UNKNOWN")
    events = journal_bridge.load_session_conversation_events_snapshot(session_id, project_root=sessions.PROJECT_ROOT)
    approvals = tool_approvals.list_tool_approval_requests(session_id)
    settled = {"accepted", "accepted_for_session", "accepted_for_session_tool", "accepted_with_action_window",
               "accepted_always", "declined", "cancelled", "expired"}
    with sessions._RUNNING_SESSIONS_LOCK:
        active_turn = bool(sessions._SESSION_ACTIVE_TURN_IDS.get(session_id))
    if (sessions._is_session_running(session_id) or active_turn or latest_open_turn_id(events) or raw_queue
            or session_has_active_work_run(sessions, session_id)
            or any(not isinstance(row, dict) or row.get("status") not in settled for row in approvals)):
        raise AssistantSessionError("ASSISTANT_QUIESCENCE_BUSY")
    if _STOP_REQUESTED.is_set():
        raise AssistantSessionError("ASSISTANT_QUIESCENCE_UNAVAILABLE")


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
    from core.web.services.session.admission_lock import SessionAdmissionLock

    with _DETAIL_LIFECYCLE_LOCK, _measured_lock("quiescence_enter"):
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
            _assert_session_idle(sessions, session_id)
            yield
        finally:
            lock.release()
    finally:
        with _measured_lock("quiescence_exit"):
            with _QUIESCENCE_STATE_LOCK:
                _QUIESCING = False


def commit_quiescent_shutdown() -> None:
    """Transfer held native admission to stopping before releasing its fence."""
    with _QUIESCENCE_STATE_LOCK:
        if not _STARTED or not _QUIESCING:
            raise AssistantSessionError("ASSISTANT_QUIESCENCE_UNAVAILABLE")
        _STOP_REQUESTED.set()


def lifecycle_status() -> dict[str, Any]:
    """Bounded native-only observation; final shutdown still needs a held fence."""
    from core.web.services.session.admission_lock import SessionAdmissionLock
    try:
        # Unlike a held shutdown proof, polling must not toggle _QUIESCING and
        # reject a concurrent user's command. It waits behind normal admission.
        with _measured_lock("lifecycle_status"):
            if _STOP_REQUESTED.is_set() or not _STARTED or _OFFLINE_MIGRATION or _QUIESCING:
                return {"schemaVersion": 1, "state": "unknown"}
            assistant = _projection()["assistant"]
            if not _SESSION_ID or not _AGENT_ID or assistant.get("directSessionId") != _SESSION_ID or assistant.get("agentId") != _AGENT_ID:
                return {"schemaVersion": 1, "state": "unknown"}
            _, _, sessions, _ = _services()
            lock = SessionAdmissionLock(sessions.PROJECT_ROOT, _SESSION_ID)
            try:
                lock.acquire(timeout=0.1)
            except sessions.SessionBusyError:
                return {"schemaVersion": 1, "state": "active"}
            try:
                _assert_session_idle(sessions, _SESSION_ID)
                return {"schemaVersion": 1, "state": "idle"}
            finally:
                lock.release()
    except AssistantSessionError as error:
        return {"schemaVersion": 1, "state": "active" if error.code == "ASSISTANT_QUIESCENCE_BUSY" else "unknown"}
    except Exception:
        return {"schemaVersion": 1, "state": "unknown"}


@contextmanager
def _source_command():
    """A tool worker must never wait for shutdown while shutdown drains it."""
    if _STOP_REQUESTED.is_set():
        raise AssistantSessionError("ASSISTANT_STOPPING")
    if not _LOCK.acquire(blocking=False):
        raise AssistantSessionError("TASK_SOURCE_BUSY")
    entered = time.monotonic()
    try:
        if _STOP_REQUESTED.is_set():
            raise AssistantSessionError("ASSISTANT_STOPPING")
        with _session_command(fixed_identity_only=True) as command:
            yield command
    finally:
        held_seconds = time.monotonic() - entered
        _LOCK.release()
        if held_seconds >= LOCK_HOLD_WARN_SECONDS:
            _LOGGER.warning("assistant_native_lock_hold operation=%s held_ms=%d",
                            "source_command", round(held_seconds * 1000))


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


def _validate_queued_turn_id(queued_turn_id: str) -> None:
    if not isinstance(queued_turn_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", queued_turn_id):
        raise AssistantSessionError("SESSION_INVALID")


def update_queued_turn(queued_turn_id: str, *, content: str | None = None,
                       position: int | None = None, status: str | None = None) -> dict[str, Any]:
    """Edit the fixed Session's native queue without owning another queue."""
    _validate_queued_turn_id(queued_turn_id)
    if (content is not None and (not isinstance(content, str) or len(content) > 64000)
            or position is not None and (type(position) is not int or not 1 <= position <= 2**53 - 1)
            or status is not None and (not isinstance(status, str) or status not in {"paused", "queued"})):
        raise AssistantSessionError("SESSION_INVALID")
    with _session_command() as (_, session_id):
        from core.web.services.session.queued_turns import update_session_queued_turn

        return {"queuedTurns": update_session_queued_turn(
            session_id, queued_turn_id, content=content, position=position, status=status,
        )}


def remove_queued_turn(queued_turn_id: str) -> dict[str, Any]:
    """Withdraw one row through the native owner of the fixed Session."""
    _validate_queued_turn_id(queued_turn_id)
    with _session_command() as (_, session_id):
        from core.web.services.session.queued_turns import remove_session_queued_turn

        return {"queuedTurns": remove_session_queued_turn(session_id, queued_turn_id)}


def send_now_queued_turn(queued_turn_id: str, *, expected_turn_id: str = "") -> dict[str, Any]:
    """Keep native promotion, stop fencing, rollback and repeated-click semantics."""
    _validate_queued_turn_id(queued_turn_id)
    if not isinstance(expected_turn_id, str) or (expected_turn_id
            and not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", expected_turn_id)):
        raise AssistantSessionError("SESSION_INVALID")
    with _session_command() as (_, session_id):
        from core.web.services.session.queued_turns import send_now_session_queued_turn

        return send_now_session_queued_turn(session_id, queued_turn_id, expected_turn_id=expected_turn_id)


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


def switch_head(node_id: str) -> dict[str, Any]:
    """Point the fixed assistant Session's active branch head at a version leaf.

    The shared service layer owns the append-only branch rebase and republishes
    the full detail snapshot; this wrapper only binds it to the fixed identity
    and reuses the session-command admission and error mapping.
    """
    if not isinstance(node_id, str) or not node_id.strip() or len(node_id) > 200:
        raise AssistantSessionError("SESSION_INVALID")
    with _session_command() as (sessions, session_id):
        from core.web.services.session.branch_head import switch_session_head

        return switch_session_head(session_id, node_id.strip())


def regenerate(message_id: str, request_id: str) -> dict[str, Any]:
    """Rerun the fixed assistant Session's last user request at the target turn.

    The shared service layer owns the branch fork and journal idempotency; the
    client_submission_id keeps the native turnId/requestId acceptance contract
    the composer's send confirmation relies on.
    """
    if not isinstance(message_id, str) or not message_id.strip() or len(message_id) > 160:
        raise AssistantSessionError("SESSION_INVALID")
    if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", request_id or ""):
        raise AssistantSessionError("SESSION_INVALID")
    with _session_command() as (sessions, session_id):
        return sessions.regenerate_session_message(
            session_id, message_id.strip(), client_submission_id=request_id,
        )


def guidance(content: str, mode: str) -> dict[str, Any]:
    """Record operator guidance for the running native turn, as Chat does.

    The shared service layer owns the guidance event, the interrupt polarity,
    and the stop request when ``mode`` is interrupt; this wrapper binds it to
    the fixed identity and session-command admission.
    """
    if not isinstance(content, str) or not content.strip() or len(content) > 64000:
        raise AssistantSessionError("SESSION_INVALID")
    if not isinstance(mode, str) or mode not in {"safe", "interrupt"}:
        raise AssistantSessionError("SESSION_INVALID")
    with _session_command() as (sessions, session_id):
        return sessions.submit_session_guidance(session_id, content, mode=mode)


def shutdown(*, timeout: float = 8.0) -> dict[str, Any]:
    """Stop owned native work and drain it before closing its directory store."""
    global _STARTED, _SESSION_ID, _AGENT_ID, _OFFLINE_MIGRATION
    deadline = time.monotonic() + max(0.0, timeout)
    with _QUIESCENCE_STATE_LOCK:
        if _QUIESCING:
            return {"closed": False, "code": "NATIVE_QUIESCENCE_ACTIVE"}
        _STOP_REQUESTED.set()
    if not _DETAIL_LIFECYCLE_LOCK.acquire(timeout=max(0.0, deadline - time.monotonic())):
        return {"closed": False, "code": "NATIVE_SHUTDOWN_ADMISSION_BUSY"}
    try:
        admitted = _LOCK.acquire(timeout=max(0.0, deadline - time.monotonic()))
    finally:
        # The early stop flag and native admission lock now fence new repairs.
        _DETAIL_LIFECYCLE_LOCK.release()
    if not admitted:
        return {"closed": False, "code": "NATIVE_SHUTDOWN_ADMISSION_BUSY"}
    entered = time.monotonic()
    try:
        if _OFFLINE_MIGRATION and _OFFLINE_DIRECTORY_CLOSE_UNCONFIRMED:
            raise RuntimeError("offline_directory_close_unconfirmed")
        if not _STARTED:
            return {"closed": True}
        _, _, sessions, runtime = _services()
        # Record before the stop below settles these runs; afterwards the
        # snapshots are terminal and nothing can be recovered from them.
        sessions.record_restart_resume_pending()
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
            _RECENT_ACCEPTED_TURNS.clear()
        return result
    finally:
        held_seconds = time.monotonic() - entered
        _LOCK.release()
        # Shutdown holds admission across the whole drain: exactly the kind of
        # long critical section the hold-time observation must surface.
        if held_seconds >= LOCK_HOLD_WARN_SECONDS:
            _LOGGER.warning("assistant_native_lock_hold operation=%s held_ms=%d",
                            "shutdown", round(held_seconds * 1000))
