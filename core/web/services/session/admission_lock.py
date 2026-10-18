"""Per-project/session admission, distinct from the journal append lock."""

from __future__ import annotations

import threading
from pathlib import Path

from core.chat.conversation_ledger import conversation_ledger_path
from core.infrastructure.file_lock import cross_process_file_lock
from core.runtime_manager.work_run_store import ACTIVE_RUN_IDS_LIMIT

from . import journal_bridge


class SessionAdmissionLock:
    """Keep the historical acquire/release API; share fencing across backends."""

    def __init__(self, project_root: Path, session_id: str) -> None:
        self.path = conversation_ledger_path(project_root, session_id).with_name("session_admission")
        self._local = threading.local()

    def acquire(self) -> bool:
        manager = cross_process_file_lock(self.path)
        try:
            manager.__enter__()
        except TimeoutError as exc:
            from core.web.services.session_service import SessionBusyError

            raise SessionBusyError("Session接纳正忙，请稍后重试。") from exc
        stack = getattr(self._local, "stack", None)
        if stack is None:
            stack = self._local.stack = []
        stack.append(manager)
        return True

    def release(self) -> None:
        stack = getattr(self._local, "stack", [])
        if not stack:
            raise RuntimeError("release unlocked session admission")
        stack.pop().__exit__(None, None, None)

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *_exc):
        self.release()


def session_has_active_work_run(s, session_id: str, turn_id: str = "") -> bool:
    if not turn_id:
        events = journal_bridge.load_session_conversation_events_snapshot(session_id, project_root=s.PROJECT_ROOT)
        turn_id = next((event.turn_id for event in reversed(events) if event.event_type == "user_message"), "")
    index = s._WORK_RUN_STORE.load_run_index("chat_turn")
    ids = index.get("activeRunIds") or [index.get("activeRunId")]
    if not isinstance(ids, list) or len(ids) > ACTIVE_RUN_IDS_LIMIT:
        return True
    for run_id in dict.fromkeys(key for key in [turn_id, *ids] if isinstance(key, str) and key):
        row = s._WORK_RUN_STORE.load_snapshot("chat_turn", run_id)
        if (row and row.get("sessionId") == session_id
                and str(row.get("status") or row.get("currentPhase") or "").lower()
                in {"queued", "running", "stopping", "paused"}
                and not (row.get("finishedAt") or row.get("endedAt"))):
            return True
    return False
