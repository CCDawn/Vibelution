# -*- coding: utf-8 -*-
"""Typed next-state signals derived from dialogue turns.

These records are evidence for review and diagnosis. They are not training
samples and do not decide supervised promotion outcomes.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SIGNAL_SCHEMA_VERSION = 1
DEFAULT_SIGNAL_PATH = Path("workspace/evaluation/chat_next_state_signals.jsonl")
ALLOWED_SOURCES = {"user", "tool", "runtime", "verification", "review"}
ALLOWED_KINDS = {
    "user_guidance",
    "user_interrupt_guidance",
    "user_accepts",
    "user_corrects",
    "user_reasks",
    "user_stops",
    "user_continues",
    "assistant_output_edited",
    "tool_error",
    "verification_passed",
    "verification_failed",
    "provider_failure",
}
ALLOWED_POLARITIES = {"positive", "negative", "neutral"}
ALLOWED_MODES = {"evaluative", "directive"}
MAX_SUMMARY_CHARS = 240
MAX_METADATA_STRING_CHARS = 240


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def resolve_chat_next_state_signal_path(project_root: Path, path: str | Path | None = None) -> Path:
    raw = Path(path) if path else DEFAULT_SIGNAL_PATH
    if raw.is_absolute():
        return raw.resolve()
    return (project_root / raw).resolve()


def _trim_text(value: Any, *, max_chars: int = MAX_SUMMARY_CHARS) -> str:
    text = " ".join(str(value or "").strip().split())
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 3)].rstrip() + "..."


def _normalize_choice(value: Any, *, allowed: set[str], default: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    return normalized if normalized in allowed else default


def _safe_metadata(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _trim_text(value, max_chars=MAX_METADATA_STRING_CHARS)
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = _trim_text(raw_key, max_chars=80)
            if not key:
                continue
            safe[key] = _safe_metadata(raw_value)
        return safe
    if isinstance(value, (list, tuple, set)):
        return [_safe_metadata(item) for item in list(value)[:20]]
    return _trim_text(value, max_chars=MAX_METADATA_STRING_CHARS)


def _signal_id(payload: dict[str, Any]) -> str:
    basis = json.dumps(
        {
            "sessionId": payload.get("sessionId") or "",
            "turnId": payload.get("turnId") or "",
            "source": payload.get("source") or "",
            "kind": payload.get("kind") or "",
            "relatedEventCode": payload.get("relatedEventCode") or "",
            "createdAt": payload.get("createdAt") or "",
            "summary": payload.get("summary") or "",
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(basis.encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"chat-signal-{digest}"


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            if path.exists():
                handle.write(path.read_text(encoding="utf-8"))
            handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def _record_signal_runtime_scene(payload: dict[str, Any]) -> None:
    try:
        from core.web.services.runtime_scene_service import record_runtime_scene_event

        record_runtime_scene_event(
            "conversation",
            "next_state_signal",
            "conversation.next_state_signal.recorded",
            level="warning" if payload.get("polarity") == "negative" else "info",
            outcome=str(payload.get("kind") or "observed"),
            message=str(payload.get("summary") or "Chat next-state signal recorded."),
            fields={
                "signalId": str(payload.get("signalId") or ""),
                "sessionId": str(payload.get("sessionId") or ""),
                "turnId": str(payload.get("turnId") or ""),
                "source": str(payload.get("source") or ""),
                "kind": str(payload.get("kind") or ""),
                "polarity": str(payload.get("polarity") or ""),
                "mode": str(payload.get("mode") or ""),
                "relatedEventCode": str(payload.get("relatedEventCode") or ""),
            },
            child_log_path="conversations/chat-next-state-signals.jsonl",
            child_log_payload=payload,
            lifecycle=True,
        )
    except Exception:
        return


@dataclass(frozen=True)
class ChatNextStateSignal:
    signalId: str
    sessionId: str
    turnId: str
    source: str
    kind: str
    polarity: str
    mode: str
    relatedEventCode: str
    createdAt: str
    summary: str
    metadata: dict[str, Any] = field(default_factory=dict)
    schemaVersion: int = SIGNAL_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def append_chat_next_state_signal(
    *,
    project_root: Path,
    session_id: str,
    turn_id: str = "",
    source: str,
    kind: str,
    polarity: str = "neutral",
    mode: str = "evaluative",
    related_event_code: str = "",
    summary: str = "",
    metadata: dict[str, Any] | None = None,
    created_at: str = "",
    signal_path: str | Path | None = None,
    record_scene: bool = True,
) -> dict[str, Any]:
    created = str(created_at or _now_iso()).strip()
    payload = {
        "schemaVersion": SIGNAL_SCHEMA_VERSION,
        "sessionId": str(session_id or "").strip(),
        "turnId": str(turn_id or "").strip(),
        "source": _normalize_choice(source, allowed=ALLOWED_SOURCES, default="runtime"),
        "kind": _normalize_choice(kind, allowed=ALLOWED_KINDS, default="provider_failure"),
        "polarity": _normalize_choice(polarity, allowed=ALLOWED_POLARITIES, default="neutral"),
        "mode": _normalize_choice(mode, allowed=ALLOWED_MODES, default="evaluative"),
        "relatedEventCode": str(related_event_code or "").strip(),
        "createdAt": created,
        "summary": _trim_text(summary or kind),
        "metadata": _safe_metadata(metadata or {}),
    }
    payload["signalId"] = _signal_id(payload)
    signal = ChatNextStateSignal(**payload).to_dict()
    path = resolve_chat_next_state_signal_path(project_root, signal_path)
    _append_jsonl(path, signal)
    if record_scene:
        _record_signal_runtime_scene(signal)
    return signal


def list_chat_next_state_signals(
    *,
    project_root: Path,
    session_id: str = "",
    turn_id: str = "",
    signal_path: str | Path | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    path = resolve_chat_next_state_signal_path(project_root, signal_path)
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    expected_session = str(session_id or "").strip()
    expected_turn = str(turn_id or "").strip()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict):
            continue
        if expected_session and str(item.get("sessionId") or "").strip() != expected_session:
            continue
        if expected_turn and str(item.get("turnId") or "").strip() != expected_turn:
            continue
        records.append(item)
    if limit is not None and limit >= 0:
        return records[-int(limit):]
    return records


def summarize_chat_next_state_signals(signals: Iterable[dict[str, Any]], *, limit: int = 8) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for item in list(signals or [])[-max(0, int(limit or 0)):]:
        if not isinstance(item, dict):
            continue
        summaries.append(
            {
                "signalId": str(item.get("signalId") or "").strip(),
                "sessionId": str(item.get("sessionId") or "").strip(),
                "turnId": str(item.get("turnId") or "").strip(),
                "source": str(item.get("source") or "").strip(),
                "kind": str(item.get("kind") or "").strip(),
                "polarity": str(item.get("polarity") or "").strip(),
                "mode": str(item.get("mode") or "").strip(),
                "relatedEventCode": str(item.get("relatedEventCode") or "").strip(),
                "createdAt": str(item.get("createdAt") or "").strip(),
                "summary": _trim_text(item.get("summary") or ""),
            }
        )
    return summaries


__all__ = [
    "ChatNextStateSignal",
    "append_chat_next_state_signal",
    "list_chat_next_state_signals",
    "resolve_chat_next_state_signal_path",
    "summarize_chat_next_state_signals",
]
