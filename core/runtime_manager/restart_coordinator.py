"""Persisted restart intents coordinated by the runtime manager."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .constants import EVENTS_PATH, RESTART_INTENTS_DIR, ensure_runtime_manager_dirs
from .scene_logging import append_runtime_manager_file_event, record_runtime_manager_scene_event, truncate_event_text


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def create_restart_intent(
    target: str,
    *,
    reason: str = "",
    source_command_id: str = "",
    requested_by: str = "unknown",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a durable intent that a supervisor loop can fulfil later."""

    ensure_runtime_manager_dirs()
    created_at = now_iso()
    intent = {
        "intentId": f"intent_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_{uuid4().hex[:8]}",
        "target": str(target or "").strip(),
        "reason": str(reason or "").strip(),
        "requestedBy": str(requested_by or "unknown").strip() or "unknown",
        "sourceCommandId": str(source_command_id or "").strip(),
        "status": "pending",
        "createdAt": created_at,
        "updatedAt": created_at,
        "attempts": 0,
        "failureCount": 0,
        "lastError": "",
        "nextAllowedAt": "",
        "payload": payload or {},
    }
    _write_intent(intent)
    _append_restart_event(
        "restart.intent.created",
        {
            "intentId": intent["intentId"],
            "target": intent["target"],
            "reason": truncate_event_text(intent["reason"], limit=240),
            "requestedBy": intent["requestedBy"],
            "sourceCommandId": intent["sourceCommandId"],
        },
    )
    return intent


def list_pending_restart_intents(*, target: str = "") -> list[dict[str, Any]]:
    ensure_runtime_manager_dirs()
    intents: list[dict[str, Any]] = []
    for path in sorted(RESTART_INTENTS_DIR.glob("*.json")):
        intent = _read_intent(path)
        if not intent or str(intent.get("status") or "") != "pending":
            continue
        if target and str(intent.get("target") or "") != target:
            continue
        intents.append(intent)
    return intents


def claim_next_restart_intent(*, target: str = "") -> dict[str, Any] | None:
    intents = list_pending_restart_intents(target=target)
    if not intents:
        return None
    intent = intents[0]
    intent["status"] = "claimed"
    intent["updatedAt"] = now_iso()
    intent["attempts"] = max(0, int(intent.get("attempts") or 0)) + 1
    _write_intent(intent)
    _append_restart_event(
        "restart.intent.claimed",
        {
            "intentId": str(intent.get("intentId") or ""),
            "target": str(intent.get("target") or ""),
            "attempts": int(intent.get("attempts") or 0),
        },
    )
    return intent


def complete_restart_intent(intent_id: str, *, status: str = "completed", message: str = "") -> dict[str, Any]:
    intent = load_restart_intent(intent_id)
    if not intent:
        return {}
    intent["status"] = str(status or "completed").strip() or "completed"
    intent["updatedAt"] = now_iso()
    if message:
        intent["message"] = truncate_event_text(message, limit=500)
    _write_intent(intent)
    _append_restart_event(
        "restart.intent.completed" if intent["status"] == "completed" else "restart.intent.failed",
        {
            "intentId": str(intent.get("intentId") or ""),
            "target": str(intent.get("target") or ""),
            "status": str(intent.get("status") or ""),
            "message": truncate_event_text(message, limit=240),
        },
    )
    return intent


def load_restart_intent(intent_id: str) -> dict[str, Any]:
    normalized = str(intent_id or "").strip()
    if not normalized:
        return {}
    return _read_intent(RESTART_INTENTS_DIR / f"{normalized}.json")


def _write_intent(intent: dict[str, Any]) -> None:
    intent_id = str(intent.get("intentId") or "").strip()
    if not intent_id:
        raise ValueError("restart intent requires intentId")
    _atomic_write_json(RESTART_INTENTS_DIR / f"{intent_id}.json", intent)


def _read_intent(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    ensure_runtime_manager_dirs()
    fd, temp_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def _append_restart_event(event_type: str, payload: dict[str, Any]) -> None:
    event_at = append_runtime_manager_file_event(
        event_type,
        payload,
        events_path=EVENTS_PATH,
        ensure_dirs=ensure_runtime_manager_dirs,
        suppress_io_errors=True,
    )
    record_runtime_manager_scene_event(event_type, payload, phase="restart", occurred_at=event_at)
