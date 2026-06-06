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
        if not path.exists():
            return default_state()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default_state()
        if not isinstance(payload, dict):
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
                    raise
                time.sleep(min(0.05 * attempt, 0.25))
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
