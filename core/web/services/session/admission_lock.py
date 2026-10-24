"""Per-project/session admission, distinct from the journal append lock."""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil

from core.chat.conversation_ledger import conversation_ledger_path
from core.infrastructure.file_lock import cross_process_file_lock
from core.infrastructure.process_liveness import is_pid_alive
from core.runtime_manager.work_run_store import ACTIVE_RUN_IDS_LIMIT, active_work_payload_blocks_lifecycle

from . import journal_bridge

# A live worker refreshes the chat_turn snapshot (heartbeat) at most every
# ~30s; align the foreign-owner freshness window with the stale sweep's
# ``_CHAT_TURN_WORKER_GONE_GRACE_SECONDS`` so both layers call the same
# snapshot abandoned.
_FOREIGN_OWNER_FRESH_SECONDS = 120.0


class SessionAdmissionLock:
    """Keep the historical acquire/release API; share fencing across backends."""

    def __init__(self, project_root: Path, session_id: str) -> None:
        self.path = conversation_ledger_path(project_root, session_id).with_name("session_admission")
        self._local = threading.local()

    def acquire(self, *, timeout: float = 30.0) -> bool:
        manager = cross_process_file_lock(self.path, timeout=timeout)
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


def _latest_user_message_turn_id(s, session_id: str) -> str:
    events = journal_bridge.load_session_conversation_events_snapshot(
        session_id, project_root=s.PROJECT_ROOT
    )
    return next(
        (event.turn_id for event in reversed(events) if event.event_type == "user_message"),
        "",
    )


def _session_blocking_work_run_snapshots(
    s, session_id: str, turn_id: str = ""
) -> tuple[list[dict[str, Any]], bool]:
    """Active chat_turn snapshots that still block a new turn for the session.

    Returns ``(snapshots, suspicious_index)``.  A suspicious index (wrong
    shape or over the active-id bound) conservatively reports blocking
    without snapshot evidence, so callers must honor it instead of the
    snapshot list.
    """

    if not turn_id:
        turn_id = _latest_user_message_turn_id(s, session_id)
    index = s._WORK_RUN_STORE.load_run_index("chat_turn")
    ids = index.get("activeRunIds") or [index.get("activeRunId")]
    if not isinstance(ids, list) or len(ids) > ACTIVE_RUN_IDS_LIMIT:
        return [], True
    blocking: list[dict[str, Any]] = []
    for run_id in dict.fromkeys(key for key in [turn_id, *ids] if isinstance(key, str) and key):
        row = s._WORK_RUN_STORE.load_snapshot("chat_turn", run_id)
        if (row and row.get("sessionId") == session_id
                and active_work_payload_blocks_lifecycle(row)):
            blocking.append(row)
    return blocking, False


def session_has_active_work_run(s, session_id: str, turn_id: str = "") -> bool:
    blocking, suspicious = _session_blocking_work_run_snapshots(s, session_id, turn_id)
    return suspicious or bool(blocking)


def session_active_work_run_owner_alive(s, session_id: str, turn_id: str = "") -> bool:
    """True when a blocking work-run snapshot proves a live foreign writer.

    On-disk work-run snapshots are the only cross-process turn visibility:
    the in-process running registry cannot see turns owned by other
    processes.  Ownership follows the ``formal_review_work`` convention —
    the writer stamps ``ownerPid`` + ``ownerCreateTime``, and create-time
    equality pins identity against pid reuse.  Snapshots without the stamp,
    whose writer is dead, or that are stale are abandoned residue of a dead
    process — exactly what the ``hot_restart_resume`` admission exemption
    exists to bypass.
    """

    blocking, suspicious = _session_blocking_work_run_snapshots(s, session_id, turn_id)
    if suspicious:
        # Cannot see who owns the index: assume the worst so the normal busy
        # semantics, not the exemption, apply.
        return True
    now = time.time()
    return any(_snapshot_owner_process_alive(row, now=now) for row in blocking)


def _snapshot_owner_process_alive(snapshot: dict[str, Any], *, now: float) -> bool:
    try:
        owner_pid = int(snapshot.get("ownerPid") or 0)
    except (TypeError, ValueError):
        # Malformed ownership stamp: admission must not crash the recovery
        # path over it, and without a readable stamp liveness is not
        # provable, so it never overrides the hot-restart exemption.
        return False
    if owner_pid == os.getpid():
        # Own residue: this process's running registry is the authority and
        # the caller already consulted it.
        return False
    if owner_pid <= 0:
        # Legacy snapshot without the ownership stamp: liveness is not
        # provable, so it never overrides the hot-restart exemption.
        return False
    if not is_pid_alive(owner_pid):
        return False
    owner_create_time = snapshot.get("ownerCreateTime")
    if owner_create_time:
        try:
            return abs(psutil.Process(owner_pid).create_time() - float(owner_create_time)) < 0.01
        except psutil.AccessDenied:
            # Inconclusive identity probe: keep the busy semantics.
            return True
        except Exception:
            # e.g. the writer died between the pid probe and the create-time
            # read, or the stamp is malformed: residue.
            return False
    # An alive pid without an identity pin could be a recycled pid: trust it
    # only while the snapshot is fresh.
    return not _snapshot_stale(snapshot, now=now)


def _snapshot_stale(snapshot: dict[str, Any], *, now: float) -> bool:
    raw = str(snapshot.get("updatedAt") or snapshot.get("startedAt") or "").strip()
    if not raw:
        return False
    try:
        updated = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    return (now - updated.timestamp()) > _FOREIGN_OWNER_FRESH_SECONDS
