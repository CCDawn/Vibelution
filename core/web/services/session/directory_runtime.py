"""Process-local ConversationStore lifecycle for the live session directory.

The store is the session-index control plane. Turn transcripts stay in
``turn_journal.jsonl``. This module never imports historical conversations.
"""

from __future__ import annotations

import logging
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.chat.conversation_store import ConversationStore, LegacyAgentConfigImporter
from core.chat.turn_journal import turn_journal_path
from core.infrastructure import developer_sandbox
from core.ui.chat_state import load_chat_state, save_chat_state

from ..runtime_scene_service import record_runtime_scene_event


logger = logging.getLogger(__name__)

_RUNTIME_LOCK = threading.RLock()
_READY = threading.Event()
_READY.set()
_LEGACY_DISCARD_IN_PROGRESS = threading.Event()
_STORE: ConversationStore | None = None
_PROJECT_ROOT: Path | None = None
_STATUS: "SessionDirectoryRuntimeStatus | None" = None
STARTING_WAIT_SECONDS = 30.0


@dataclass(frozen=True)
class SessionDirectoryRuntimeStatus:
    """Bounded startup result; it never includes session content or local paths."""

    status: str
    schema_version: int = 0
    discarded_legacy: bool = False
    discarded_session_count: int = 0
    imported_agent_count: int = 0
    error_type: str = ""


def conversation_store_path(project_root: Path) -> Path:
    return developer_sandbox.sandboxed_workspace_path(
        Path(project_root),
        "chat",
        "conversations.sqlite3",
    )


def is_directory_store_open() -> bool:
    with _RUNTIME_LOCK:
        return bool(_STORE is not None and getattr(_STORE, "_open", False))


def is_legacy_discard_in_progress() -> bool:
    return _LEGACY_DISCARD_IN_PROGRESS.is_set()


def directory_store_project_root() -> Path | None:
    with _RUNTIME_LOCK:
        return _PROJECT_ROOT


def get_open_directory_store() -> ConversationStore | None:
    with _RUNTIME_LOCK:
        if _STORE is None or not getattr(_STORE, "_open", False):
            return None
        return _STORE


def current_directory_runtime_status() -> SessionDirectoryRuntimeStatus | None:
    with _RUNTIME_LOCK:
        return _STATUS


def should_skip_directory_runtime_for_pytest() -> bool:
    import os
    import sys

    return bool(os.environ.get("PYTEST_CURRENT_TEST") or "pytest" in sys.modules)


def begin_directory_startup() -> None:
    """Mark the directory as starting so list/query wait instead of reading JSON."""

    global _STATUS
    with _RUNTIME_LOCK:
        if _STATUS is not None and _STATUS.status == "starting":
            return
        _STATUS = SessionDirectoryRuntimeStatus(status="starting")
        _READY.clear()


def wait_for_directory_startup(*, timeout: float | None = None) -> str:
    """Return the runtime phase after waiting out an in-flight startup.

    ``starting`` means the wait timed out and callers must not fall back to
    ``chat_state`` (that would flash discarded sessions).
    """

    with _RUNTIME_LOCK:
        status = _STATUS
    if status is None or status.status != "starting":
        return status.status if status is not None else "idle"
    _READY.wait(STARTING_WAIT_SECONDS if timeout is None else timeout)
    with _RUNTIME_LOCK:
        status = _STATUS
    if status is None:
        return "idle"
    return status.status


def initialize_session_directory_runtime(
    *,
    project_root: Path,
    discard_legacy_sessions: bool = True,
) -> SessionDirectoryRuntimeStatus:
    """Open the production directory store for one project root.

    Tests must pass an isolated ``project_root``. This function does not fall
    back to the operator Documents tree when the caller omits a root.
    """

    global _STORE, _PROJECT_ROOT, _STATUS
    root = Path(project_root).resolve()
    begin_directory_startup()
    shutdown_session_directory_runtime(mark_stopped=False)
    store = ConversationStore(conversation_store_path(root))
    discarded_legacy = False
    discarded_session_count = 0
    imported_agent_count = 0
    try:
        metadata = store.open()
        imported_agent_count = _import_agent_snapshots(store, root)
        if discard_legacy_sessions:
            discarded_legacy, discarded_session_count = _discard_legacy_sessions_once(
                store,
                root,
            )
        status = SessionDirectoryRuntimeStatus(
            status="ready",
            schema_version=int(metadata.get("schemaVersion") or 0),
            discarded_legacy=discarded_legacy,
            discarded_session_count=discarded_session_count,
            imported_agent_count=imported_agent_count,
        )
        _record(
            "session_directory.runtime.ready",
            outcome="started",
            fields={
                "schemaVersion": status.schema_version,
                "discardedLegacy": discarded_legacy,
                "discardedSessionCount": discarded_session_count,
                "importedAgentCount": imported_agent_count,
            },
        )
    except Exception as exc:
        store.close()
        status = SessionDirectoryRuntimeStatus(
            status="failed",
            discarded_legacy=discarded_legacy,
            discarded_session_count=discarded_session_count,
            imported_agent_count=imported_agent_count,
            error_type=type(exc).__name__,
        )
        logger.warning(
            "Session directory store failed to start (%s).",
            type(exc).__name__,
        )
        _record(
            "session_directory.runtime.failed",
            outcome="failed",
            level="warning",
            fields={"errorType": type(exc).__name__},
        )
        with _RUNTIME_LOCK:
            _STORE = None
            _PROJECT_ROOT = None
            _STATUS = status
            _READY.set()
        return status

    with _RUNTIME_LOCK:
        _STORE = store
        _PROJECT_ROOT = root
        _STATUS = status
        _READY.set()
    return status


def shutdown_session_directory_runtime(*, timeout: float = 5, mark_stopped: bool = True) -> None:
    global _STORE, _PROJECT_ROOT, _STATUS
    with _RUNTIME_LOCK:
        store = _STORE
        _STORE = None
        _PROJECT_ROOT = None
        if mark_stopped:
            if _STATUS is not None:
                _STATUS = SessionDirectoryRuntimeStatus(status="stopped")
            _READY.set()
    if store is not None:
        store.close(timeout=timeout)


def _import_agent_snapshots(store: ConversationStore, project_root: Path) -> int:
    from core.web.services import agent_directory_service

    if agent_directory_service.PROJECT_ROOT != project_root:
        agent_directory_service.PROJECT_ROOT = project_root
    registry_path = agent_directory_service.registry_path()
    if not registry_path.exists():
        return 0
    result = LegacyAgentConfigImporter(store.repository).import_file(registry_path)
    return int(result.get("created") or 0) + int(result.get("revised") or 0) + int(
        result.get("reused") or 0
    )


def _discard_legacy_sessions_once(
    store: ConversationStore,
    project_root: Path,
) -> tuple[bool, int]:
    if store.repository.legacy_sessions_discarded_at_ms() is not None:
        return False, 0

    from core.web.services import session_service as session_svc

    session_ids: list[str] = []
    _LEGACY_DISCARD_IN_PROGRESS.set()
    try:
        with session_svc._CHAT_STATE_LOCK:
            payload = load_chat_state(project_root)
            conversations = payload.get("conversations")
            if not isinstance(conversations, list):
                conversations = []
            session_ids = [
                str(item.get("conversation_id") or item.get("id") or "").strip()
                for item in conversations
                if isinstance(item, dict)
                and str(item.get("conversation_id") or item.get("id") or "").strip()
            ]
            payload["conversations"] = []
            payload["active_conversation_id"] = ""
            payload["version"] = int(payload.get("version") or session_svc.CHAT_STATE_VERSION)
            payload["updated_at"] = session_svc._now_timestamp()
            save_chat_state(project_root, payload)

        _clear_agent_direct_session_bindings(project_root)

        for session_id in session_ids:
            try:
                session_svc._set_session_running(session_id, False)
                session_svc._clear_session_turn_control(session_id)
                session_svc._clear_session_live_output(session_id)
                session_svc._invalidate_session_conversation_events_cache(session_id)
                session_svc._invalidate_session_agent_runtime_cache(session_id)
            except Exception as exc:
                logger.debug(
                    "Session directory discard skipped runtime cleanup for one session (%s).",
                    type(exc).__name__,
                )
            journal_path = turn_journal_path(project_root, session_id)
            session_dir = journal_path.parent
            try:
                if session_dir.exists() and session_dir.is_dir():
                    shutil.rmtree(session_dir, ignore_errors=True)
            except OSError as exc:
                logger.warning(
                    "Session directory discard could not remove a journal workspace (%s).",
                    type(exc).__name__,
                )

        store.repository.mark_legacy_sessions_discarded().result(timeout=5)
        session_svc._invalidate_session_list_cache()
        _record(
            "session_directory.legacy.discarded",
            outcome="completed",
            fields={"discardedSessionCount": len(session_ids)},
        )
        return True, len(session_ids)
    finally:
        _LEGACY_DISCARD_IN_PROGRESS.clear()


def _clear_agent_direct_session_bindings(project_root: Path) -> None:
    from core.web.services import agent_directory_service

    if agent_directory_service.PROJECT_ROOT != project_root:
        agent_directory_service.PROJECT_ROOT = project_root
    try:
        with agent_directory_service._STATE_LOCK:
            state = agent_directory_service.load_state()
            agents = state.get("agents")
            if not isinstance(agents, list):
                return
            changed = False
            for agent in agents:
                if not isinstance(agent, dict):
                    continue
                if str(agent.get("directSessionId") or "").strip():
                    agent["directSessionId"] = ""
                    changed = True
            if changed:
                agent_directory_service.save_state(state)
    except Exception as exc:
        logger.warning(
            "Session directory discard could not clear directSessionId bindings (%s).",
            type(exc).__name__,
        )


def _record(
    event_code: str,
    *,
    outcome: str,
    level: str = "info",
    fields: dict[str, Any] | None = None,
) -> None:
    try:
        record_runtime_scene_event(
            "conversation",
            "session_directory",
            event_code,
            level=level,
            outcome=outcome,
            message="Session directory store lifecycle event.",
            fields=fields or {},
            lifecycle=True,
        )
    except Exception:
        pass
