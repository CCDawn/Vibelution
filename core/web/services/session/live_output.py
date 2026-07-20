"""Session live-output state, in-memory store, and checkpoint I/O.

Claim scope: live assistant overlay state + disk checkpoint only.
Do not put submit/worker/stream publish, chat-state recovery, or UI capture here.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

SESSION_LIVE_OUTPUT_CHECKPOINT_INTERVAL_SECONDS = 0.75
_SESSION_LIVE_OUTPUT_CHECKPOINT_INTERVAL_SECONDS = SESSION_LIVE_OUTPUT_CHECKPOINT_INTERVAL_SECONDS

_SESSION_LIVE_OUTPUTS_LOCK = threading.Lock()
_SESSION_LIVE_OUTPUTS: dict[str, "SessionLiveOutputState"] = {}
_SESSION_LIVE_OUTPUT_CHECKPOINT_LOCK = threading.Lock()
_SESSION_LIVE_OUTPUT_CHECKPOINT_LAST_AT: dict[str, float] = {}


def _perf_counter() -> float:
    return time.perf_counter()


@dataclass
class SessionLiveOutputState:
    """Ephemeral live assistant output for one active web chat turn."""

    session_id: str
    turn_id: str = ""
    stage: str = ""
    thought: str = ""
    content: str = ""
    thought_delta: str = ""
    content_delta: str = ""
    replace_thought: bool = False
    replace_content: bool = False
    mental_snapshot: dict[str, Any] | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    feedback_events: list[dict[str, Any]] = field(default_factory=list)
    context_composition: dict[str, Any] | None = None
    llm_payload_trace: dict[str, Any] | None = None
    updated_at: str = ""


def live_output_delta(previous: str, current: str) -> tuple[str, bool]:
    previous_text = str(previous or "")
    current_text = str(current or "")
    if current_text.startswith(previous_text):
        return current_text[len(previous_text) :], False
    return current_text, True


def snapshot_session_live_output(session_id: str) -> SessionLiveOutputState | None:
    with _SESSION_LIVE_OUTPUTS_LOCK:
        state = _SESSION_LIVE_OUTPUTS.get(session_id)
        if state is None:
            return None
        return SessionLiveOutputState(
            session_id=session_id,
            turn_id=state.turn_id,
            stage=state.stage,
            thought=state.thought,
            content=state.content,
            mental_snapshot=dict(state.mental_snapshot or {}) if isinstance(state.mental_snapshot, dict) else None,
            tool_calls=list(state.tool_calls or []),
            feedback_events=list(state.feedback_events or []),
            context_composition=(
                dict(state.context_composition or {}) if isinstance(state.context_composition, dict) else None
            ),
            llm_payload_trace=(
                dict(state.llm_payload_trace or {}) if isinstance(state.llm_payload_trace, dict) else None
            ),
            updated_at=state.updated_at,
        )


def clear_session_live_output(session_id: str, *, turn_id: str = "") -> bool:
    """Clear in-memory live state for a session.

    Returns True when a checkpoint should be deleted (caller owns path resolution).
    """

    requested_turn_id = str(turn_id or "").strip()
    with _SESSION_LIVE_OUTPUTS_LOCK:
        if requested_turn_id:
            current = _SESSION_LIVE_OUTPUTS.get(session_id)
            if current is not None and current.turn_id and current.turn_id != requested_turn_id:
                return False
        _SESSION_LIVE_OUTPUTS.pop(session_id, None)
        return True


def discard_session_live_output_state(
    session_id: str,
    *,
    turn_id: str = "",
    checkpoint_path: Path | None = None,
) -> None:
    """Drop in-memory state and optional on-disk checkpoint for a session."""

    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return
    normalized_turn_id = str(turn_id or "").strip()
    with _SESSION_LIVE_OUTPUTS_LOCK:
        if normalized_turn_id:
            current = _SESSION_LIVE_OUTPUTS.get(normalized_session_id)
            current_turn_id = str(getattr(current, "turn_id", "") or "").strip()
            if current is not None and current_turn_id and current_turn_id != normalized_turn_id:
                return
        _SESSION_LIVE_OUTPUTS.pop(normalized_session_id, None)
    if checkpoint_path is not None:
        delete_session_live_output_checkpoint(normalized_session_id, checkpoint_path=checkpoint_path)
    else:
        # Still clear throttle bookkeeping when path is resolved by caller later.
        with _SESSION_LIVE_OUTPUT_CHECKPOINT_LOCK:
            _SESSION_LIVE_OUTPUT_CHECKPOINT_LAST_AT.pop(normalized_session_id, None)


def live_output_checkpoint_has_visible_payload(payload: dict[str, Any]) -> bool:
    return bool(
        str(payload.get("content") or "").strip()
        or str(payload.get("thought") or "").strip()
        or list(payload.get("toolCalls") or [])
        or list(payload.get("feedbackEvents") or [])
        or isinstance(payload.get("mentalSnapshot"), dict)
        or isinstance(payload.get("llmPayloadTrace"), dict)
    )


def live_output_checkpoint_has_assistant_payload(payload: dict[str, Any]) -> bool:
    return bool(
        str(payload.get("content") or "").strip()
        or str(payload.get("thought") or "").strip()
        or list(payload.get("toolCalls") or [])
        or list(payload.get("feedbackEvents") or [])
        or isinstance(payload.get("mentalSnapshot"), dict)
    )


def build_live_output_checkpoint_core_payload(
    state: SessionLiveOutputState,
    *,
    updated_at: str,
) -> dict[str, Any]:
    """Serialize store fields only (no timeline/codex projection)."""

    session_id = str(getattr(state, "session_id", "") or "").strip()
    turn_id = str(getattr(state, "turn_id", "") or "").strip()
    content = str(getattr(state, "content", "") or "")
    feedback_events = list(getattr(state, "feedback_events", []) or [])
    return {
        "schemaVersion": 1,
        "sessionId": session_id,
        "turnId": turn_id,
        "stage": str(getattr(state, "stage", "") or "").strip(),
        "content": content,
        "thought": str(getattr(state, "thought", "") or ""),
        "mentalSnapshot": getattr(state, "mental_snapshot", None),
        "toolCalls": list(getattr(state, "tool_calls", []) or []),
        "feedbackEvents": feedback_events,
        "contextComposition": getattr(state, "context_composition", None),
        "llmPayloadTrace": getattr(state, "llm_payload_trace", None),
        "updatedAt": str(updated_at or "").strip(),
    }


def write_session_live_output_checkpoint(
    session_id: str,
    *,
    checkpoint_path: Path,
    payload: dict[str, Any] | None = None,
    build_payload: Callable[[], dict[str, Any]] | None = None,
    force: bool = False,
    interval_seconds: float = SESSION_LIVE_OUTPUT_CHECKPOINT_INTERVAL_SECONDS,
) -> None:
    """Write a checkpoint payload with throttle + visibility gates.

    Prefer ``build_payload`` so expensive projection work is skipped when throttled.
    """

    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return
    now = _perf_counter()
    if not force:
        with _SESSION_LIVE_OUTPUT_CHECKPOINT_LOCK:
            last_at = _SESSION_LIVE_OUTPUT_CHECKPOINT_LAST_AT.get(normalized_session_id, 0.0)
        if last_at > 0 and now - last_at < float(interval_seconds):
            return
    if payload is None:
        if build_payload is None:
            return
        payload = build_payload()
    if not isinstance(payload, dict):
        return
    if not live_output_checkpoint_has_visible_payload(payload):
        if force:
            delete_session_live_output_checkpoint(
                normalized_session_id,
                checkpoint_path=checkpoint_path,
            )
        return
    tmp_path = checkpoint_path.with_name(f"{checkpoint_path.name}.tmp")
    try:
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        tmp_path.replace(checkpoint_path)
        with _SESSION_LIVE_OUTPUT_CHECKPOINT_LOCK:
            _SESSION_LIVE_OUTPUT_CHECKPOINT_LAST_AT[normalized_session_id] = now
    except OSError:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


def delete_session_live_output_checkpoint(
    session_id: str,
    *,
    checkpoint_path: Path,
) -> None:
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return
    with _SESSION_LIVE_OUTPUT_CHECKPOINT_LOCK:
        _SESSION_LIVE_OUTPUT_CHECKPOINT_LAST_AT.pop(normalized_session_id, None)
    try:
        checkpoint_path.unlink(missing_ok=True)
    except OSError:
        return


def load_session_live_output_checkpoint_payload(checkpoint_path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or not live_output_checkpoint_has_visible_payload(payload):
        return None
    return payload


def state_from_checkpoint_payload(
    session_id: str,
    payload: dict[str, Any],
    *,
    sanitize_thought: Callable[[Any], str],
    sanitize_content: Callable[[Any], str],
    normalize_mental_snapshot: Callable[[Any], dict[str, Any] | None],
    normalize_tool_calls: Callable[[Any], list[dict[str, Any]]],
    normalize_feedback_events: Callable[[Any], list[dict[str, Any]]],
    normalize_context_composition: Callable[[Any], dict[str, Any] | None],
    normalize_llm_payload_trace: Callable[[Any], dict[str, Any] | None],
) -> SessionLiveOutputState:
    """Build store state from a checkpoint payload using caller normalizers."""

    return SessionLiveOutputState(
        session_id=str(session_id or "").strip(),
        turn_id=str(payload.get("turnId") or "").strip(),
        stage=str(payload.get("stage") or "").strip(),
        thought=sanitize_thought(payload.get("thought") or ""),
        content=sanitize_content(payload.get("content") or ""),
        mental_snapshot=normalize_mental_snapshot(payload.get("mentalSnapshot")),
        tool_calls=normalize_tool_calls(payload.get("toolCalls") or []),
        feedback_events=normalize_feedback_events(payload.get("feedbackEvents") or []),
        context_composition=normalize_context_composition(payload.get("contextComposition")),
        llm_payload_trace=normalize_llm_payload_trace(payload.get("llmPayloadTrace")),
        updated_at=str(payload.get("updatedAt") or "").strip(),
    )


# Private aliases matching historical session_service names (facade wiring).
_live_output_delta = live_output_delta
_snapshot_session_live_output = snapshot_session_live_output
_live_output_checkpoint_has_visible_payload = live_output_checkpoint_has_visible_payload
_live_output_checkpoint_has_assistant_payload = live_output_checkpoint_has_assistant_payload
_build_live_output_checkpoint_core_payload = build_live_output_checkpoint_core_payload
_write_session_live_output_checkpoint_core = write_session_live_output_checkpoint
_delete_session_live_output_checkpoint_core = delete_session_live_output_checkpoint
_load_session_live_output_checkpoint_payload = load_session_live_output_checkpoint_payload
_state_from_checkpoint_payload = state_from_checkpoint_payload
_clear_session_live_output_memory = clear_session_live_output
_discard_session_live_output_state_core = discard_session_live_output_state
