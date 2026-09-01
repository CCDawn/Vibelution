"""Persistent JSON store for chat rooms."""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CHAT_ROOM_STATE_VERSION = 1
WRITE_RETRY_TIMEOUT_SECONDS = 5.0
# Readers must never spin long: the read path serves request threads, so the
# retry budget stays an order of magnitude below the writer's 5s budget.  A
# concurrent ``os.replace`` blocks the open() for milliseconds, so this budget
# is only a guard against pathological contention.
READ_RETRY_TIMEOUT_SECONDS = 1.0
_READ_RETRY_MAX_SLEEP_SECONDS = 0.2


class ChatRoomStoreReadError(RuntimeError):
    """The chat room state file exists but could not be read or decoded.

    Callers must never treat this as an empty store: the durable state is
    unknown, so any terminal-state decision or overwrite based on a default
    state would be unsafe.  This is deliberately distinct from "file does not
    exist", which keeps returning a default state.
    """

    def __init__(self, path: Path, cause: BaseException) -> None:
        super().__init__(
            f"Unable to read chat room state file {path}: "
            f"{type(cause).__name__}: {cause}"
        )
        self.path = path


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_state() -> dict[str, Any]:
    return {
        "version": CHAT_ROOM_STATE_VERSION,
        "updatedAt": utc_now_iso(),
        "rooms": [],
    }


@dataclass(frozen=True)
class ChatRoomStore:
    root: Path

    @property
    def state_path(self) -> Path:
        return self.root / "workspace" / "chat_rooms" / "chat_rooms.json"

    def load(self) -> dict[str, Any]:
        path = self.state_path
        try:
            exists = path.exists()
        except OSError:
            exists = False
        if not exists:
            return default_state()
        try:
            payload = _read_state_object(path)
        except FileNotFoundError:
            # The state file vanished between exists() and the read; treat it
            # like a missing store instead of a corrupted one.
            return default_state()
        state = default_state()
        state.update(payload)
        rooms = state.get("rooms")
        state["rooms"] = list(rooms or []) if isinstance(rooms, list) else []
        return state

    def save(self, state: dict[str, Any]) -> dict[str, Any]:
        payload = default_state()
        payload.update(state if isinstance(state, dict) else {})
        payload["version"] = CHAT_ROOM_STATE_VERSION
        payload["updatedAt"] = utc_now_iso()
        rooms = payload.get("rooms")
        payload["rooms"] = list(rooms or []) if isinstance(rooms, list) else []
        _atomic_write_json(self.state_path, payload)
        return payload


def _read_state_object(path: Path) -> dict[str, Any]:
    """Read and decode the state file with a short retry budget.

    A concurrent ``os.replace`` can make the open() fail with PermissionError
    on Windows, and a decode can fail on a torn/corrupt payload.  Both are
    retried briefly; after the budget is exhausted the failure is surfaced as
    ``ChatRoomStoreReadError`` so callers can distinguish "no state file" from
    "state file unreadable" instead of silently operating on an empty state.
    """

    deadline = time.monotonic() + READ_RETRY_TIMEOUT_SECONDS
    attempt = 0
    while True:
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise
        except OSError as exc:
            attempt += 1
            if time.monotonic() >= deadline:
                raise ChatRoomStoreReadError(path, exc) from exc
            time.sleep(min(0.05 * attempt, _READ_RETRY_MAX_SLEEP_SECONDS))
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            attempt += 1
            if time.monotonic() >= deadline:
                raise ChatRoomStoreReadError(path, exc) from exc
            time.sleep(min(0.05 * attempt, _READ_RETRY_MAX_SLEEP_SECONDS))
            continue
        if not isinstance(payload, dict):
            raise ChatRoomStoreReadError(
                path,
                ValueError(
                    f"chat room state root is {type(payload).__name__}, expected object"
                ),
            )
        return payload


def _record_store_event(event_code: str, *, fields: dict[str, Any], level: str) -> None:
    try:
        from core.web.services.runtime_scene_service import record_runtime_scene_event

        record_runtime_scene_event(
            "chat_room",
            "store",
            event_code,
            message=event_code,
            level=level,
            fields=dict(fields),
        )
    except Exception:
        return


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        deadline = time.monotonic() + WRITE_RETRY_TIMEOUT_SECONDS
        attempt = 0
        while True:
            try:
                os.replace(temp_path, path)
                break
            except PermissionError:
                attempt += 1
                if time.monotonic() >= deadline:
                    # Never drop a terminal state silently: surface the
                    # failure so callers (e.g. round finalizers) keep their
                    # in-memory control records and can retry.
                    _record_store_event(
                        "chat_room.store.write_failed",
                        fields={
                            "path": str(path),
                            "attempts": attempt,
                            "retryTimeoutSeconds": WRITE_RETRY_TIMEOUT_SECONDS,
                        },
                        level="warning",
                    )
                    raise
                time.sleep(min(0.05 * attempt, 0.25))
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
