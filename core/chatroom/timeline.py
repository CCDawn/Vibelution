# -*- coding: utf-8 -*-
"""Append-only per-room timeline log for chat rooms.

One JSONL file per room at ``workspace/chat_rooms/<roomId>/timeline.jsonl``
(lazily created on first append).  Every event carries
``{eventId, roomId, seq, type, from, to, payload, createdAt}`` where ``seq``
is monotonic within the room, allocated under the append lock by reading the
tail of the file.  The log is the room's durable observable history: message
landings, round state transitions, membership changes and (schema-only for
now) artifact registrations.

Concurrency and durability conventions deliberately mirror
``core/web/services/team_workflow/storage_durability.py`` (inter-process
``<file>.lock`` keyed file lock, O(line) locked append with fsync, tolerant
read that quarantines corrupt lines to ``<file>.corrupt`` and rewrites them
away) but are re-implemented locally: ``core/chatroom`` is a lower layer and
must not import the web service layer.

Seq allocation on a torn tail: a crash mid-append can leave a final
non-JSON line.  ``_last_seq`` scans backwards over unparsable trailing lines
and takes the last valid ``seq``, so the next append continues the sequence
and the torn line is quarantined by the next tolerant read instead of
poisoning the room history.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
import threading
import time
import uuid
from collections.abc import Iterator, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.infrastructure import developer_sandbox

PROJECT_ROOT = Path(__file__).resolve().parents[2]

EVENT_TYPE_MESSAGE = "message"
EVENT_TYPE_ROUND_STATE = "round_state"
EVENT_TYPE_MEMBER_CHANGE = "member_change"
EVENT_TYPE_ARTIFACT = "artifact"
EVENT_TYPES = frozenset(
    {
        EVENT_TYPE_MESSAGE,
        EVENT_TYPE_ROUND_STATE,
        EVENT_TYPE_MEMBER_CHANGE,
        EVENT_TYPE_ARTIFACT,
    }
)

SCHEMA_VERSION = 1
DEFAULT_READ_LIMIT = 200
MAX_READ_LIMIT = 500
APPEND_LOCK_TIMEOUT_SECONDS = 30.0
_MAX_TAIL_SCAN_BYTES = 262_144

_IS_WINDOWS = os.name == "nt"
_WINDOWS_EXTENDED_LENGTH_PREFIX = "\\\\?\\"
_WINDOWS_LONG_PATH_THRESHOLD = 248
_SAFE_COMPONENT_RE = re.compile(r"[^A-Za-z0-9._-]+")


class TimelineError(RuntimeError):
    """Raised when a timeline room id or event payload is unusable."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _project_root(project_root: Path | None) -> Path:
    return Path(project_root) if project_root is not None else PROJECT_ROOT


def _safe_room_component(room_id: str) -> str:
    normalized = str(room_id or "").strip()
    if not normalized:
        raise TimelineError("Chat room timeline requires a non-empty roomId.")
    component = _SAFE_COMPONENT_RE.sub("-", normalized).strip("._-")[:128]
    return component or "room"


def chat_rooms_root(project_root: Path | None = None) -> Path:
    """Resolve the chat-rooms directory exactly like :class:`ChatRoomStore`.

    ``ChatRoomStore.state_path`` is ``<workspace home>.parent / "workspace" /
    "chat_rooms" / "chat_rooms.json"``; mirroring that chain keeps the
    timeline directory colocated with the room store in every environment,
    including test pins of a module ``PROJECT_ROOT``.
    """

    root = _project_root(project_root)
    workspace_home = developer_sandbox.formal_workspace_path(root)
    return workspace_home.parent / "workspace" / "chat_rooms"


def timeline_path(room_id: str, *, project_root: Path | None = None) -> Path:
    return (
        chat_rooms_root(project_root)
        / _safe_room_component(room_id)
        / "timeline.jsonl"
    )


def _windows_extended_length_path(path: Path) -> Path:
    text = str(path)
    if (
        _IS_WINDOWS
        and len(text) >= _WINDOWS_LONG_PATH_THRESHOLD
        and text[1:3] == ":\\"
        and not text.startswith(_WINDOWS_EXTENDED_LENGTH_PREFIX)
    ):
        return Path(_WINDOWS_EXTENDED_LENGTH_PREFIX + text)
    return path


@contextlib.contextmanager
def _inter_process_lock(store_path: Path, *, timeout_s: float = 10.0) -> Iterator[None]:
    """Cross-process lock keyed on ``<store>.lock`` (OS lock, crash-safe)."""

    lock_path = _windows_extended_length_path(
        store_path.with_name(store_path.name + ".lock")
    )
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+b")
    try:
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                if _IS_WINDOWS:
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.02)
        try:
            yield
        finally:
            if _IS_WINDOWS:
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def _parse_event_line(line: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _last_seq(path: Path) -> int:
    """Return the last valid ``seq`` in the file by scanning the tail.

    Caller holds the append lock.  Trailing torn/non-JSON lines are skipped;
    a missing or empty file yields 0.
    """

    try:
        size = path.stat().st_size
    except OSError:
        return 0
    if size <= 0:
        return 0
    window = min(size, _MAX_TAIL_SCAN_BYTES)
    with path.open("rb") as handle:
        handle.seek(size - window)
        tail = handle.read(window).decode("utf-8", errors="replace")
    lines = [line for line in tail.split("\n") if line.strip()]
    # When the window cut into the middle of a line, the first element is a
    # partial line; drop it so only complete lines are considered.
    if window < size and lines:
        lines = lines[1:]
    for line in reversed(lines):
        payload = _parse_event_line(line.strip())
        if payload is None:
            continue
        try:
            return max(0, int(payload.get("seq") or 0))
        except (TypeError, ValueError):
            continue
    return 0


def _quarantine_and_rewrite(path: Path, corrupt_lines: list[str]) -> None:
    """Quarantine corrupt lines to ``<file>.corrupt`` and rewrite the file.

    Caller holds the append lock.  Mirrors the tolerant-read quarantine in
    the team workflow storage primitives so a repeat read never re-quarantines
    the same line and the bad payload stays recoverable on the side.
    """

    quarantine_path = path.with_name(path.name + ".corrupt")
    with quarantine_path.open("a", encoding="utf-8") as handle:
        for line in corrupt_lines:
            handle.write(line + "\n")
    kept = "\n".join(
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and line not in corrupt_lines
    )
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            if kept:
                handle.write(kept + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def read_events(
    room_id: str,
    *,
    after_seq: int = 0,
    limit: int | None = None,
    project_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Read timeline events with ``seq > after_seq`` in file (== seq) order.

    Corrupt lines are quarantined to ``<file>.corrupt`` instead of raising,
    so one torn write cannot brick a room's history.  Returns ``[]`` for a
    room with no timeline yet.
    """

    path = timeline_path(room_id, project_root=project_root)
    if not path.exists():
        return []
    try:
        resolved_limit = (
            DEFAULT_READ_LIMIT if limit is None else max(0, min(int(limit), MAX_READ_LIMIT))
        )
    except (TypeError, ValueError):
        resolved_limit = DEFAULT_READ_LIMIT
    floor = max(0, int(after_seq or 0))
    events: list[dict[str, Any]] = []
    with _inter_process_lock(path):
        corrupt: list[str] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = _parse_event_line(line.strip())
            if payload is None:
                corrupt.append(line)
                continue
            try:
                seq = int(payload.get("seq") or 0)
            except (TypeError, ValueError):
                corrupt.append(line)
                continue
            if seq <= floor:
                continue
            events.append(payload)
            if resolved_limit and len(events) >= resolved_limit:
                break
        if corrupt:
            _quarantine_and_rewrite(path, corrupt)
    events.sort(key=lambda item: int(item.get("seq") or 0))
    return events


def append_room_event(
    room_id: str,
    *,
    type: str,
    payload: Mapping[str, Any] | None = None,
    from_id: str = "",
    to_id: str = "",
    round_id: str = "",
    project_root: Path | None = None,
    created_at: str = "",
    event_id: str = "",
) -> dict[str, Any]:
    """Append one event to the room timeline and return the stored record.

    ``seq`` is allocated under the inter-process lock from the file tail, so
    concurrent writers (backend plus a second process) can never mint the
    same sequence number.
    """

    normalized_type = str(type or "").strip()
    if normalized_type not in EVENT_TYPES:
        raise TimelineError(f"Unsupported chat room timeline event type: {type!r}")
    path = timeline_path(room_id, project_root=project_root)
    event: dict[str, Any] = {
        "eventId": str(event_id or "").strip() or f"tle-{uuid.uuid4().hex}",
        "roomId": str(room_id or "").strip(),
        "seq": 0,
        "type": normalized_type,
        "roundId": str(round_id or "").strip(),
        "from": str(from_id or "").strip(),
        "to": str(to_id or "").strip(),
        "payload": dict(payload) if isinstance(payload, Mapping) else {},
        "createdAt": str(created_at or "").strip() or utc_now_iso(),
        "schemaVersion": SCHEMA_VERSION,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with _inter_process_lock(path, timeout_s=APPEND_LOCK_TIMEOUT_SECONDS):
        event["seq"] = _last_seq(path) + 1
        line = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    return event


__all__ = [
    "APPEND_LOCK_TIMEOUT_SECONDS",
    "DEFAULT_READ_LIMIT",
    "EVENT_TYPES",
    "EVENT_TYPE_ARTIFACT",
    "EVENT_TYPE_MEMBER_CHANGE",
    "EVENT_TYPE_MESSAGE",
    "EVENT_TYPE_ROUND_STATE",
    "MAX_READ_LIMIT",
    "PROJECT_ROOT",
    "SCHEMA_VERSION",
    "TimelineError",
    "append_room_event",
    "chat_rooms_root",
    "read_events",
    "timeline_path",
    "utc_now_iso",
]
