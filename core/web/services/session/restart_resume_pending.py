"""Marker for turns that a graceful restart interrupted.

A restart and an operator pressing stop both converge on the same terminal
``stopped`` work-run state, so startup recovery cannot tell them apart by
looking at the snapshot alone. ``shutdown_session_service`` records the turns
still running at shutdown time here, and the startup sweep consumes and clears
the marker, so it never outlives the restart that produced it.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Iterable

MARKER_FILENAME = "restart-resume-pending.json"
MARKER_SCHEMA_VERSION = 1

_logger = logging.getLogger(__name__)


def marker_path_for_store(store: Any) -> Path | None:
    """Marker file living beside ``work_runs`` so both share one authority."""

    root = getattr(store, "root", None)
    if root is None:
        return None
    return Path(root).parent / MARKER_FILENAME


def record_pending_restart_resume(store: Any, entries: Iterable[dict[str, Any]]) -> None:
    """Overwrite the marker with the turns this shutdown is interrupting."""

    path = marker_path_for_store(store)
    if path is None:
        return
    by_session: dict[str, list[str]] = {}
    for entry in entries or ():
        if not isinstance(entry, dict):
            continue
        session_id = str(entry.get("sessionId") or "").strip()
        turn_id = str(entry.get("turnId") or "").strip()
        if not session_id or not turn_id:
            continue
        by_session.setdefault(session_id, []).append(turn_id)
    if not by_session:
        clear_pending_restart_resume(store)
        return
    payload = {
        "schemaVersion": MARKER_SCHEMA_VERSION,
        "sessions": {
            session_id: sorted(set(turn_ids))
            for session_id, turn_ids in by_session.items()
        },
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f"{path.suffix}.tmp-{os.getpid()}")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(temporary, path)
    except OSError as exc:  # noqa: BLE001 - losing the marker only restores manual resume
        _logger.warning(
            "Failed to record restart-resume marker (%s).", type(exc).__name__
        )


def load_pending_restart_resume(store: Any) -> dict[str, set[str]]:
    """Session id -> interrupted turn ids; a missing or invalid marker is empty."""

    path = marker_path_for_store(store)
    if path is None or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _logger.warning(
            "Restart-resume marker unreadable (%s); ignoring.", type(exc).__name__
        )
        return {}
    if not isinstance(payload, dict) or payload.get("schemaVersion") != MARKER_SCHEMA_VERSION:
        return {}
    sessions = payload.get("sessions")
    if not isinstance(sessions, dict):
        return {}
    result: dict[str, set[str]] = {}
    for session_id, turn_ids in sessions.items():
        normalized_session = str(session_id or "").strip()
        if not normalized_session or not isinstance(turn_ids, list):
            continue
        normalized_turns = {
            str(turn_id).strip() for turn_id in turn_ids if str(turn_id or "").strip()
        }
        if normalized_turns:
            result[normalized_session] = normalized_turns
    return result


def clear_pending_restart_resume(store: Any) -> None:
    """Drop the marker once the sweep has consumed it."""

    path = marker_path_for_store(store)
    if path is None:
        return
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError as exc:  # noqa: BLE001 - a stale marker is retried next startup
        _logger.warning(
            "Failed to clear restart-resume marker (%s).", type(exc).__name__
        )
