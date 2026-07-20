"""Session UI stream capture (batching + journal tool/delta hooks).

Claim scope: live UI capture of thought/response/tools into SessionTurnCapture,
batching to live_output, and journal assistant_delta_committed / tool events.
Do not put SSE transport, session_detail publish, or submit/worker orchestration here.

Bodies late-bind ``session_service`` for sanitizers, live_output, and journal helpers
so facade monkeypatches remain effective.
"""

from __future__ import annotations

import re
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from core.chat.chat_task_types import trim_lines


def _service():
    """Late-bound facade module (avoids import cycles at package import time)."""

    from core.web.services import session_service

    return session_service


_SESSION_UI_CAPTURE_LOCK = threading.Lock()
_SESSION_UI_CAPTURE_CONTEXT: ContextVar[dict[str, Any]] = ContextVar(
    "vibelution_session_ui_capture_context",
    default={},
)

_SESSION_UI_CAPTURE_RESPONSE_BATCH_MIN_CHARS = 24

_SESSION_UI_CAPTURE_RESPONSE_BATCH_MAX_LATENCY_SECONDS = 0.12

_SESSION_UI_CAPTURE_RESPONSE_BATCH_LATENCY_MIN_CHARS = 8

_SESSION_UI_CAPTURE_THOUGHT_BATCH_MIN_CHARS = 24

_SESSION_UI_CAPTURE_THOUGHT_BATCH_MAX_LATENCY_SECONDS = 0.12

_SESSION_UI_CAPTURE_THOUGHT_BATCH_LATENCY_MIN_CHARS = 8

@dataclass
class SessionTurnCapture:
    """Collect live UI breadcrumbs so the web session can replay them."""

    session_id: str
    turn_id: str = ""
    thought: str = ""
    content: str = ""
    mental_state: dict[str, str] = field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    feedback_events: list[dict[str, Any]] = field(default_factory=list)
    _next_feedback_sequence: int = 1
    _latest_thought_sequence: int = 0
    _latest_thought_text: str = ""
    _last_recorded_thought_sequence: int = 0
    _last_recorded_thought_text: str = ""
    _pending_related_thought_sequence: int = 0
    _tool_loop_call_count: int = 0
    _tool_loop_failure_count: int = 0
    _tool_loop_last_failure: str = ""
    _committed_content_length: int = 0
    _latest_tool_feedback_sequence: int = 0
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False, compare=False)

    def note_thought(self, text: str) -> None:
        s = _service()
        cleaned = s._sanitize_thought_delta_text(text)
        if cleaned:
            previous_total = self.thought
            previous_segment = self._latest_thought_text if self._latest_thought_sequence else ""
            if previous_total and not previous_segment and cleaned == previous_total:
                self._mark_repeated_thought_after_boundary()
                return
            next_total, next_text = self._resolve_thought_text_update(cleaned, previous_total, previous_segment)
            if not next_text:
                return
            if not previous_segment and self._is_repeated_recorded_thought(next_text):
                self._mark_repeated_thought_after_boundary()
                return
            if previous_segment and next_text == previous_segment:
                self.thought = next_total
                return
            self.thought = next_total
            self._latest_thought_text = next_text
            self._pending_related_thought_sequence = 0
            if self._latest_thought_sequence:
                self._update_latest_thought_event(next_text)
                self._remember_recorded_thought(self._latest_thought_sequence, next_text)
            else:
                self._latest_thought_sequence = self._append_feedback_event(
                    {
                        "kind": "thought",
                        "status": "running",
                        "summary": trim_lines(next_text, max_lines=2),
                        "resultPreview": next_text,
                    }
                )
                self._remember_recorded_thought(self._latest_thought_sequence, next_text)

    def _mark_repeated_thought_after_boundary(self) -> None:
        s = _service()
        if self._last_recorded_thought_sequence:
            self._pending_related_thought_sequence = self._last_recorded_thought_sequence

    def _remember_recorded_thought(self, sequence: int, text: str) -> None:
        s = _service()
        if sequence > 0 and text:
            self._last_recorded_thought_sequence = sequence
            self._last_recorded_thought_text = text

    def _is_repeated_recorded_thought(self, text: str) -> bool:
        s = _service()
        previous = self._normalize_thought_for_dedupe(self._last_recorded_thought_text)
        current = self._normalize_thought_for_dedupe(text)
        if not previous or not current:
            return False
        if current == previous:
            return True
        if len(current) < 48 or len(previous) < 48:
            return False
        if current in previous or previous in current:
            shorter = min(len(current), len(previous))
            longer = max(len(current), len(previous))
            return shorter >= int(longer * 0.85)
        return False

    @staticmethod
    def _normalize_thought_for_dedupe(text: str) -> str:
        s = _service()
        return re.sub(r"\s+", " ", str(text or "")).strip()

    def _resolve_thought_text_update(self, cleaned: str, previous_total: str, previous_segment: str) -> tuple[str, str]:
        s = _service()
        if not previous_total:
            return cleaned, cleaned
        if cleaned.startswith(previous_total):
            suffix = cleaned[len(previous_total):]
            if previous_segment:
                return cleaned, f"{previous_segment}{suffix}" if suffix else previous_segment
            return cleaned, suffix
        if previous_segment and cleaned.startswith(previous_segment):
            if previous_total.endswith(previous_segment):
                next_total = f"{previous_total[:-len(previous_segment)]}{cleaned}"
            else:
                next_total = f"{previous_total}{cleaned}"
            return next_total, cleaned
        next_total = f"{previous_total}{cleaned}"
        next_segment = f"{previous_segment}{cleaned}" if previous_segment else cleaned
        return next_total, next_segment

    def _update_latest_thought_event(self, text: str) -> None:
        s = _service()
        for index in range(len(self.feedback_events) - 1, -1, -1):
            latest = self.feedback_events[index]
            if (
                latest.get("kind") == "thought"
                and s._coerce_nonnegative_int(latest.get("sequence")) == self._latest_thought_sequence
            ):
                updated = dict(latest)
                updated["status"] = "running"
                updated["summary"] = trim_lines(text, max_lines=2)
                updated["resultPreview"] = text
                updated["timestamp"] = s._now_timestamp()
                self.feedback_events[index] = updated
                return

    def clear_thought(self) -> None:
        s = _service()
        self.thought = ""

    def note_content(self, text: str) -> None:
        s = _service()
        cleaned = s._sanitize_message_content("assistant", text)
        if cleaned:
            self.content = cleaned

    def uncommitted_content_segment(self) -> str:
        s = _service()
        content = s._sanitize_message_content("assistant", self.content)
        if not content:
            return ""
        committed_length = max(0, min(int(self._committed_content_length or 0), len(content)))
        return content[committed_length:].strip()

    def mark_content_committed(self) -> None:
        s = _service()
        self._committed_content_length = len(s._sanitize_message_content("assistant", self.content))

    def reserve_feedback_sequence(self) -> int:
        s = _service()
        with self._lock:
            sequence = self._next_feedback_sequence
            self._next_feedback_sequence += 1
            return sequence

    def clear_content(self) -> None:
        s = _service()
        self.content = ""
        self._committed_content_length = 0

    def note_mental_state(self, *, mood: str = "", feeling: str = "", whisper: str = "") -> None:
        s = _service()
        self.mental_state = {
            "mood": str(mood or "").strip(),
            "feeling": str(feeling or "").strip(),
            "whisper": str(whisper or "").strip(),
        }
        summary = trim_lines(
            self.mental_state.get("feeling") or self.mental_state.get("whisper") or self.mental_state.get("mood") or "",
            max_lines=2,
        )
        if summary:
            self._append_feedback_event(
                {
                    "kind": "mental",
                    "status": "running",
                    "summary": summary,
                }
            )

    def note_status_event(self, stage: str, summary: str, *, status: str = "running", name: str = "") -> None:
        s = _service()
        stage_key = str(stage or "").strip().lower()
        cleaned_summary = trim_lines(summary or "", max_lines=3)
        if not stage_key and not cleaned_summary:
            return
        status_name = str(name or stage_key or "status").strip()
        self.feedback_events = s._close_previous_running_status_events(self.feedback_events, status_name)
        for existing in self.feedback_events:
            if existing.get("kind") == "status" and existing.get("name") == status_name:
                existing["status"] = s._normalize_tool_call_status(status, default="running")
                if cleaned_summary:
                    existing["summary"] = cleaned_summary
                    existing["resultPreview"] = cleaned_summary
                existing["timestamp"] = s._now_timestamp()
                return
        self._append_feedback_event(
            {
                "kind": "status",
                "status": s._normalize_tool_call_status(status, default="running"),
                "name": status_name,
                "summary": cleaned_summary or stage_key,
                "resultPreview": cleaned_summary or stage_key,
            }
        )

    def note_tool_event(
        self,
        name: str,
        status: str,
        summary: str = "",
        *,
        call_id: str = "",
        arguments: dict[str, Any] | None = None,
        result: Any = "",
        error: Any = "",
        duration_ms: Any = None,
        timeout_seconds: Any = None,
        transport_status: Any = None,
        semantic_status: Any = None,
        failure_class: Any = None,
        exit_code: Any = None,
        timed_out: Any = None,
        result_kind: Any = None,
        truncated: Any = None,
        original_length: Any = None,
    ) -> None:
        s = _service()
        tool_name = str(name or "").strip()
        if not tool_name:
            return
        normalized_call_id = str(call_id or "").strip()
        entry = {
            "name": tool_name,
            "status": s._normalize_tool_call_status(semantic_status or status, default="running"),
        }
        if normalized_call_id:
            entry["callId"] = normalized_call_id
        cleaned_summary = trim_lines(summary or "", max_lines=2)
        if cleaned_summary:
            entry["summary"] = cleaned_summary
        safe_arguments = s._safe_tool_argument_details(arguments or {})
        if safe_arguments:
            entry["arguments"] = safe_arguments
        result_preview = s._trim_tool_detail_text(result, max_chars=1200, max_lines=10)
        if result_preview:
            entry["resultPreview"] = result_preview
            entry["resultType"] = type(result).__name__
            entry["resultLength"] = len(str(result or ""))
        error_preview = s._trim_tool_detail_text(error, max_chars=1200, max_lines=10)
        if error_preview:
            entry["error"] = error_preview
        numeric_duration = s._coerce_tool_number(duration_ms)
        if numeric_duration is not None:
            entry["durationMs"] = numeric_duration
        numeric_timeout = s._coerce_tool_number(timeout_seconds)
        if numeric_timeout is not None:
            entry["timeoutSeconds"] = numeric_timeout
        s._copy_tool_result_fact_fields(
            {
                "transportStatus": transport_status,
                "semanticStatus": semantic_status,
                "failureClass": failure_class,
                "exitCode": exit_code,
                "timedOut": timed_out,
                "resultKind": result_kind,
                "truncated": truncated,
                "originalLength": original_length,
            },
            entry,
        )
        with self._lock:
            related_thought_sequence = self._latest_thought_sequence or self._pending_related_thought_sequence or 0
            for index in range(len(self.tool_calls) - 1, -1, -1):
                existing = self.tool_calls[index]
                if existing.get("status") != "running":
                    continue
                existing_call_id = str(existing.get("callId") or "").strip()
                if normalized_call_id:
                    if existing_call_id != normalized_call_id:
                        continue
                elif existing_call_id or existing.get("name") != tool_name:
                    continue
                if existing.get("name") == tool_name:
                    self.tool_calls[index] = entry
                    self._update_running_tool_feedback_event(entry, related_thought_sequence=related_thought_sequence)
                    self._latest_tool_feedback_sequence = self._feedback_sequence_for_tool(tool_name, normalized_call_id)
                    self._remember_tool_loop_outcome(entry)
                    self._update_long_loop_progress_event(tool_name)
                    self._latest_thought_sequence = 0
                    self._latest_thought_text = ""
                    self._pending_related_thought_sequence = 0
                    return
            self.tool_calls.append(entry)
            self._tool_loop_call_count += 1
            if len(self.tool_calls) > 30:
                self.tool_calls = self.tool_calls[-30:]
            self._append_tool_feedback_event(entry, related_thought_sequence=related_thought_sequence)
            self._latest_tool_feedback_sequence = self._feedback_sequence_for_tool(tool_name, normalized_call_id)
            self._remember_tool_loop_outcome(entry)
            self._update_long_loop_progress_event(tool_name)
            self._latest_thought_sequence = 0
            self._latest_thought_text = ""
            self._pending_related_thought_sequence = 0

    def _feedback_sequence_for_tool(self, tool_name: str, call_id: str = "") -> int:
        s = _service()
        normalized = str(tool_name or "").strip()
        if not normalized:
            return 0
        normalized_call_id = str(call_id or "").strip()
        for existing in reversed(self.feedback_events):
            if existing.get("kind") != "tool":
                continue
            existing_call_id = str(existing.get("callId") or "").strip()
            if normalized_call_id:
                if existing_call_id != normalized_call_id:
                    continue
            elif existing_call_id or existing.get("name") != normalized:
                continue
            return s._coerce_nonnegative_int(existing.get("sequence"))
        return 0

    def _remember_tool_loop_outcome(self, tool_call: dict[str, Any]) -> None:
        s = _service()
        status = s._normalize_tool_call_status(tool_call.get("status"), default="running")
        if status == "running":
            return
        details = " ".join(
            str(tool_call.get(key) or "")
            for key in ("summary", "error", "resultPreview", "failureClass")
            if tool_call.get(key)
        )
        failure_hint = s._compact_tool_loop_failure_hint(details)
        if status in {"failed", "timeout"} or failure_hint:
            self._tool_loop_failure_count += 1
            self._tool_loop_last_failure = failure_hint or trim_lines(details, max_lines=1)

    def _update_long_loop_progress_event(self, tool_name: str) -> None:
        s = _service()
        if self._tool_loop_call_count < 3:
            return
        failure_suffix = ""
        if self._tool_loop_failure_count > 0:
            latest = self._tool_loop_last_failure or "工具返回失败"
            failure_suffix = f"；失败 {self._tool_loop_failure_count} 次，最近失败：{latest}"
        summary = f"尚未形成最终回答 · {tool_name} 第 {self._tool_loop_call_count} 次工具调用{failure_suffix}"
        preview = (
            f"{summary}\n"
            "当前仍在工具循环中，过程会继续更新；如果中断，可发送“继续”恢复这轮现场。"
        )
        for existing in self.feedback_events:
            if existing.get("kind") == "status" and existing.get("name") == "long_loop_progress":
                existing["status"] = "running"
                existing["summary"] = summary
                existing["resultPreview"] = preview
                existing["timestamp"] = s._now_timestamp()
                return
        self._append_feedback_event(
            {
                "kind": "status",
                "status": "running",
                "name": "long_loop_progress",
                "summary": summary,
                "resultPreview": preview,
            }
        )

    def _append_feedback_event(self, event: dict[str, Any]) -> int:
        s = _service()
        with self._lock:
            sequence = self._next_feedback_sequence
            self._next_feedback_sequence += 1
            entry = {
                "sequence": sequence,
                "timestamp": s._now_timestamp(),
                **event,
            }
            self.feedback_events.append(entry)
            if len(self.feedback_events) > 120:
                self.feedback_events = self.feedback_events[-120:]
            return sequence

    def _append_tool_feedback_event(self, tool_call: dict[str, Any], *, related_thought_sequence: int = 0) -> None:
        s = _service()
        entry = {
            "kind": "tool",
            "status": s._normalize_tool_call_status(tool_call.get("status"), default="running"),
            "name": str(tool_call.get("name") or "").strip(),
            "summary": trim_lines(tool_call.get("summary") or "", max_lines=2),
        }
        for key in (
            "callId",
            "arguments",
            "resultPreview",
            "resultType",
            "resultLength",
            "error",
            "durationMs",
            "durationSeconds",
            "timeoutSeconds",
            "transportStatus",
            "semanticStatus",
            "failureClass",
            "exitCode",
            "timedOut",
            "resultKind",
            "truncated",
            "originalLength",
            "tracePath",
        ):
            if key in tool_call:
                entry[key] = tool_call[key]
        if related_thought_sequence > 0:
            entry["relatedThoughtSequence"] = related_thought_sequence
        self._append_feedback_event(entry)

    def _update_running_tool_feedback_event(self, tool_call: dict[str, Any], *, related_thought_sequence: int = 0) -> None:
        s = _service()
        tool_name = str(tool_call.get("name") or "").strip()
        if not tool_name:
            return
        call_id = str(tool_call.get("callId") or "").strip()
        for index in range(len(self.feedback_events) - 1, -1, -1):
            existing = self.feedback_events[index]
            existing_call_id = str(existing.get("callId") or "").strip()
            if (
                existing.get("kind") == "tool"
                and existing.get("status") == "running"
                and (
                    (call_id and existing_call_id == call_id)
                    or (not call_id and not existing_call_id and existing.get("name") == tool_name)
                )
            ):
                sequence = existing.get("sequence")
                timestamp = existing.get("timestamp")
                updated = {
                    "sequence": sequence,
                    "timestamp": timestamp,
                    "kind": "tool",
                    "status": s._normalize_tool_call_status(tool_call.get("status"), default="done"),
                    "name": tool_name,
                    "summary": trim_lines(tool_call.get("summary") or "", max_lines=2),
                }
                for key in (
                    "callId",
                    "arguments",
                    "resultPreview",
                    "resultType",
                    "resultLength",
                    "error",
                    "durationMs",
                    "durationSeconds",
                    "timeoutSeconds",
                    "transportStatus",
                    "semanticStatus",
                    "failureClass",
                    "exitCode",
                    "timedOut",
                    "resultKind",
                    "truncated",
                    "originalLength",
                    "tracePath",
                ):
                    if key in tool_call:
                        updated[key] = tool_call[key]
                related = s._coerce_nonnegative_int(existing.get("relatedThoughtSequence") or related_thought_sequence)
                if related > 0:
                    updated["relatedThoughtSequence"] = related
                self.feedback_events[index] = updated
                return
        self._append_tool_feedback_event(tool_call, related_thought_sequence=related_thought_sequence)

@dataclass
class _SessionUiCaptureTextBatcher:
    session_id: str
    capture: SessionTurnCapture
    response_batch_min_chars: int = _SESSION_UI_CAPTURE_RESPONSE_BATCH_MIN_CHARS
    response_batch_max_latency_seconds: float = _SESSION_UI_CAPTURE_RESPONSE_BATCH_MAX_LATENCY_SECONDS
    response_batch_latency_min_chars: int = _SESSION_UI_CAPTURE_RESPONSE_BATCH_LATENCY_MIN_CHARS
    thought_batch_min_chars: int = _SESSION_UI_CAPTURE_THOUGHT_BATCH_MIN_CHARS
    thought_batch_max_latency_seconds: float = _SESSION_UI_CAPTURE_THOUGHT_BATCH_MAX_LATENCY_SECONDS
    thought_batch_latency_min_chars: int = _SESSION_UI_CAPTURE_THOUGHT_BATCH_LATENCY_MIN_CHARS
    _pending_thought_text: str = ""
    _pending_thought_started_at: float = 0.0
    _published_thought_text: str = ""
    _pending_response_content: str = ""
    _pending_response_started_at: float = 0.0
    _published_response_content: str = ""

    def note_thought(self, thought: str, *, feedback_events: list[dict[str, Any]] | None = None) -> None:
        s = _service()
        cleaned = s._sanitize_thought_text(thought)
        if not cleaned:
            return
        self._pending_thought_text = cleaned
        if self._pending_thought_started_at <= 0:
            self._pending_thought_started_at = s._perf_counter()
        if self._should_flush_thought(cleaned):
            self.flush_thought(feedback_events=feedback_events)

    def note_response(self, content: str, *, done: bool = False) -> None:
        s = _service()
        cleaned = s._sanitize_message_content("assistant", content)
        if not cleaned:
            if done:
                self.flush_all()
            return
        self.flush_thought()
        self._pending_response_content = cleaned
        if self._pending_response_started_at <= 0:
            self._pending_response_started_at = s._perf_counter()
        if done or self._should_flush_response(cleaned):
            self.flush_response()

    def flush_thought(self, *, feedback_events: list[dict[str, Any]] | None = None) -> None:
        s = _service()
        thought = s._sanitize_thought_text(self._pending_thought_text)
        if not thought:
            self._pending_thought_text = ""
            self._pending_thought_started_at = 0.0
            return
        if thought != self._published_thought_text or feedback_events is not None:
            s._set_session_live_output(
                self.session_id,
                turn_id=self.capture.turn_id,
                thought=thought,
                feedback_events=feedback_events if feedback_events is not None else self.capture.feedback_events,
            )
            self._published_thought_text = thought
        self._pending_thought_text = ""
        self._pending_thought_started_at = 0.0

    def flush_response(self) -> None:
        s = _service()
        content = s._sanitize_message_content("assistant", self._pending_response_content)
        if not content:
            self._pending_response_content = ""
            self._pending_response_started_at = 0.0
            return
        if content != self._published_response_content:
            s._set_session_live_output(
                self.session_id,
                turn_id=self.capture.turn_id,
                stage="assistant_response",
                content=content,
            )
            self._published_response_content = content
        self._pending_response_content = ""
        self._pending_response_started_at = 0.0

    def clear_thought(self) -> None:
        s = _service()
        self._pending_thought_text = ""
        self._pending_thought_started_at = 0.0
        self._published_thought_text = ""
        s._set_session_live_output(self.session_id, turn_id=self.capture.turn_id, thought="")

    def clear_response(self) -> None:
        s = _service()
        self._pending_response_content = ""
        self._pending_response_started_at = 0.0
        self._published_response_content = ""
        s._set_session_live_output(self.session_id, turn_id=self.capture.turn_id, content="")

    def flush_all(self) -> None:
        s = _service()
        self.flush_thought()
        self.flush_response()

    def _should_flush_thought(self, thought: str) -> bool:
        s = _service()
        pending_delta, replace = s._live_output_delta(self._published_thought_text, thought)
        pending_chars = len(thought if replace else pending_delta)
        if pending_chars >= max(1, int(self.thought_batch_min_chars or 1)):
            return True
        if self._pending_thought_started_at <= 0:
            return False
        elapsed = s._perf_counter() - self._pending_thought_started_at
        return (
            elapsed >= max(0.0, float(self.thought_batch_max_latency_seconds or 0.0))
            and pending_chars >= max(1, int(self.thought_batch_latency_min_chars or 1))
        )

    def _should_flush_response(self, content: str) -> bool:
        s = _service()
        pending_delta, replace = s._live_output_delta(self._published_response_content, content)
        pending_chars = len(content if replace else pending_delta)
        if pending_chars >= max(1, int(self.response_batch_min_chars or 1)):
            return True
        if self._pending_response_started_at <= 0:
            return False
        elapsed = s._perf_counter() - self._pending_response_started_at
        if elapsed < max(0.0, float(self.response_batch_max_latency_seconds or 0.0)):
            return False
        latency_min_chars = max(1, int(self.response_batch_latency_min_chars or 1))
        if pending_chars >= latency_min_chars:
            return True
        return pending_chars > 0

def _seed_capture_from_live_feedback_events(session_id: str, capture: SessionTurnCapture) -> None:
    s = _service()
    live_state = s._snapshot_session_live_output(session_id)
    if live_state is None:
        return
    live_turn_id = str(live_state.turn_id or "").strip()
    if live_turn_id and capture.turn_id and live_turn_id != capture.turn_id:
        return
    events = s._normalize_message_feedback_events(live_state.feedback_events)
    if not events:
        return
    capture.feedback_events = events
    capture._next_feedback_sequence = max(s._coerce_nonnegative_int(item.get("sequence")) for item in events) + 1
    latest_thought = 0
    for item in events:
        if item.get("kind") == "thought":
            latest_thought = s._coerce_nonnegative_int(item.get("sequence"))
    capture._latest_thought_sequence = latest_thought

def _active_session_turn_capture(session_id: str, turn_id: str = "") -> SessionTurnCapture | None:
    s = _service()
    context = _SESSION_UI_CAPTURE_CONTEXT.get({})
    if not isinstance(context, dict):
        return None
    capture = context.get("capture")
    if not isinstance(capture, SessionTurnCapture):
        return None
    expected_session_id = str(context.get("sessionId") or "").strip()
    if expected_session_id and expected_session_id != str(session_id or "").strip():
        return None
    requested_turn_id = str(turn_id or "").strip()
    if requested_turn_id and capture.turn_id and requested_turn_id != capture.turn_id:
        return None
    return capture

def _attach_turn_capture_to_result(
    result: Any,
    capture: SessionTurnCapture,
    *,
    mental_model_enabled: bool | None = None,
) -> Any:
    s = _service()
    if not isinstance(result, dict):
        return result
    if s._is_provider_failed_result(result):
        if capture.thought and not result.get("thought") and not result.get("reasoning_content"):
            result["thought"] = capture.thought
        if (
            s._is_mental_model_enabled_for_turn(mental_model_enabled)
            and capture.mental_state
            and not result.get("state_info")
            and not result.get("stateInfo")
        ):
            result["state_info"] = dict(capture.mental_state)
        if capture.tool_calls and not result.get("tool_trace") and not result.get("tool_calls"):
            result["tool_trace"] = list(capture.tool_calls)
        if capture.feedback_events and not result.get("feedback_events") and not result.get("feedbackEvents"):
            result["feedback_events"] = list(capture.feedback_events)
        return result
    if capture.thought and not result.get("thought") and not result.get("reasoning_content"):
        result["thought"] = capture.thought
    live_state = s._snapshot_session_live_output(capture.session_id)
    live_turn_id = str(getattr(live_state, "turn_id", "") if live_state else "").strip()
    capture_turn_id = str(capture.turn_id or "").strip()
    live_content = (
        s._sanitize_message_content("assistant", getattr(live_state, "content", "") if live_state else "")
        if (
            live_state is not None
            and str(getattr(live_state, "stage", "") or "").strip().lower() == "assistant_response"
            and (not capture_turn_id or live_turn_id == capture_turn_id)
        )
        else ""
    )
    captured_content = capture.content or live_content
    visible_result = s._visible_reply_candidate(result)
    raw_visible_result = str(result.get("raw_output") or result.get("summary") or result.get("message") or "").strip()
    raw_visible_was_control_only = bool(raw_visible_result and not s._sanitize_message_content("assistant", raw_visible_result))
    derived_tool_activity_visible = s._visible_reply_matches_derived_tool_activity(result, visible_result)
    if captured_content and (
        not visible_result
        or s._looks_like_structured_payload(visible_result)
        or raw_visible_was_control_only
        or derived_tool_activity_visible
    ):
        result["raw_output"] = captured_content
        result["summary"] = captured_content
    if (
        s._is_mental_model_enabled_for_turn(mental_model_enabled)
        and capture.mental_state
        and not result.get("state_info")
        and not result.get("stateInfo")
    ):
        result["state_info"] = dict(capture.mental_state)
    if capture.tool_calls and not result.get("tool_trace") and not result.get("tool_calls"):
        result["tool_trace"] = list(capture.tool_calls)
    if capture.feedback_events and not result.get("feedback_events") and not result.get("feedbackEvents"):
        result["feedback_events"] = list(capture.feedback_events)
    return result

def _commit_session_capture_assistant_segment(
    session_id: str,
    capture: SessionTurnCapture,
    *,
    boundary: str,
    status: str = "completed",
) -> None:
    s = _service()
    segment = capture.uncommitted_content_segment()
    if not segment:
        return
    sequence = capture._append_feedback_event(
        {
            "kind": "assistant_text",
            "status": s._normalize_tool_call_status(status, default="done"),
            "content": segment,
        }
    )
    s._append_session_conversation_event(
        session_id,
        capture.turn_id,
        s.EVENT_ASSISTANT_DELTA_COMMITTED,
        status=status,
        payload={
            "content": segment,
            "feedbackSequence": sequence,
            "metadata": {
                "boundary": str(boundary or "").strip(),
                "source": "session_ui_capture",
            },
        },
        source="session_ui_capture",
        projection_kind="assistant_timeline_segment",
    )
    capture.mark_content_committed()
    s._set_session_live_output(
        session_id,
        turn_id=capture.turn_id,
        content=capture.content,
        feedback_events=capture.feedback_events,
    )

@contextmanager
def _capture_session_ui_stream(
    session_id: str,
    capture: SessionTurnCapture,
    *,
    mental_model_enabled: bool | None = None,
):
    s = _service()
    from core.ui import get_ui

    ui = get_ui()
    _ensure_session_ui_capture_hooks(ui)
    _seed_capture_from_live_feedback_events(session_id, capture)
    event_bus = s.get_event_bus()
    callback_ids: list[str] = []

    def tool_event_proxy(event):
        s = _service()
        context = _SESSION_UI_CAPTURE_CONTEXT.get({})
        if not isinstance(context, dict) or context.get("capture") is not capture:
            return
        batcher = context.get("textBatcher")
        if isinstance(batcher, _SessionUiCaptureTextBatcher):
            batcher.flush_all()
        _commit_session_capture_assistant_segment(
            session_id,
            capture,
            boundary="tool_event",
        )
        data = event.data or {}
        name = str(data.get("name") or "").strip()
        if not name:
            return
        call_id = str(data.get("callId") or data.get("call_id") or "").strip()
        semantic_status = str(data.get("semanticStatus") or data.get("semantic_status") or "").strip()
        status = {
            s.EventNames.TOOL_START: "running",
            s.EventNames.TOOL_SUCCESS: semantic_status or "done",
            s.EventNames.TOOL_ERROR: semantic_status or "failed",
        }.get(event.name, "running")
        status = s._normalize_tool_call_status(status, default="running")
        result = data.get("result") if "result" in data else ""
        error = data.get("error") if "error" in data else ""
        summary = str(data.get("summary") or result or error or "").strip()
        fact_fields = {
            "transportStatus": s._first_present_mapping_value(data, ("transportStatus", "transport_status")),
            "semanticStatus": semantic_status,
            "failureClass": s._first_present_mapping_value(data, ("failureClass", "failure_class")),
            "exitCode": s._first_present_mapping_value(data, ("exitCode", "exit_code")),
            "timedOut": s._first_present_mapping_value(data, ("timedOut", "timed_out")),
            "resultKind": s._first_present_mapping_value(data, ("resultKind", "result_kind")),
            "truncated": data.get("truncated"),
            "originalLength": s._first_present_mapping_value(data, ("originalLength", "original_length")),
        }
        capture.note_tool_event(
            name,
            status,
            summary,
            call_id=call_id,
            arguments=data.get("args") if isinstance(data.get("args"), dict) else None,
            result=result,
            error=error,
            duration_ms=data.get("durationMs") or data.get("duration_ms"),
            timeout_seconds=data.get("timeoutSeconds") or data.get("timeout_seconds"),
            transport_status=fact_fields["transportStatus"],
            semantic_status=fact_fields["semanticStatus"],
            failure_class=fact_fields["failureClass"],
            exit_code=fact_fields["exitCode"],
            timed_out=fact_fields["timedOut"],
            result_kind=fact_fields["resultKind"],
            truncated=fact_fields["truncated"],
            original_length=fact_fields["originalLength"],
        )
        tool_call_payload = {
            "name": name,
            "status": status,
            "feedbackSequence": capture._latest_tool_feedback_sequence,
            "arguments": data.get("args") if isinstance(data.get("args"), dict) else {},
            "summary": summary,
            "result": result,
            "error": error,
            "durationMs": data.get("durationMs") or data.get("duration_ms"),
            "timeoutSeconds": data.get("timeoutSeconds") or data.get("timeout_seconds"),
        }
        if call_id:
            tool_call_payload["callId"] = call_id
        s._copy_tool_result_fact_fields(fact_fields, tool_call_payload)
        s._append_session_conversation_event(
            session_id,
            capture.turn_id,
            s.EVENT_TOOL_CALL_STARTED if event.name == s.EventNames.TOOL_START else s.EVENT_TOOL_RESULT,
            status=status,
            payload={
                "toolCall": tool_call_payload
            },
            source="session_ui_capture",
            tool_call_id=call_id,
            correlation_id=call_id,
        )
        s._set_session_live_output(
            session_id,
            turn_id=capture.turn_id,
            tool_calls=capture.tool_calls,
            feedback_events=capture.feedback_events,
        )
        if event.name == s.EventNames.TOOL_ERROR:
            error_preview = trim_lines(summary or str(error or ""), max_lines=2)
            work_run_summary = s.text_for(
                s.get_web_language(),
                zh=f"工具失败：{name}。" + (f" {error_preview}" if error_preview else ""),
                en=f"Tool failed: {name}." + (f" {error_preview}" if error_preview else ""),
            )
            s._touch_chat_turn_work_run(
                session_id=session_id,
                turn_id=capture.turn_id,
                stage="tool_error",
                summary=work_run_summary,
                last_tool_error={
                    "callId": call_id,
                    "toolName": name,
                    "summary": work_run_summary,
                    "errorPreview": error_preview,
                    "relatedEventCode": "conversation.tool_error",
                    "updatedAt": s._now_timestamp(),
                },
            )
            s._record_chat_next_state_signal(
                session_id=session_id,
                turn_id=capture.turn_id,
                source="tool",
                kind="tool_error",
                polarity="negative",
                mode="evaluative",
                related_event_code="conversation.tool_error",
                summary=f"Tool failed: {name}",
                metadata={
                    "toolName": name,
                    "errorPreview": summary,
                },
            )

    def llm_status_event_proxy(event):
        s = _service()
        context = _SESSION_UI_CAPTURE_CONTEXT.get({})
        data = event.data if isinstance(event.data, dict) else {}
        event_session_id = str(data.get("session_id") or data.get("sessionId") or "").strip()
        event_turn_id = str(data.get("turn_id") or data.get("turnId") or "").strip()
        expected_session_id = str(context.get("sessionId") or session_id or "").strip() if isinstance(context, dict) else str(session_id or "").strip()
        if event_session_id and event_session_id != expected_session_id:
            return
        if event_turn_id and capture.turn_id and event_turn_id != capture.turn_id:
            return
        if not event_session_id and (not isinstance(context, dict) or context.get("capture") is not capture):
            return
        target_session_id = event_session_id or expected_session_id
        if not target_session_id:
            return
        status = str(data.get("status") or "").strip()
        if not status:
            return
        if status == "payload_trace" and isinstance(data.get("llmPayloadTrace"), dict):
            s._set_session_llm_payload_trace_live_output(
                target_session_id,
                data.get("llmPayloadTrace"),
                turn_id=event_turn_id or capture.turn_id,
            )
            return
        batcher = context.get("textBatcher") if isinstance(context, dict) else None
        if isinstance(batcher, _SessionUiCaptureTextBatcher):
            batcher.flush_all()
        s._set_session_llm_status_live_output(
            target_session_id,
            status,
            turn_id=capture.turn_id,
            fields=data,
        )

    def llm_response_event_proxy(event):
        s = _service()
        context = _SESSION_UI_CAPTURE_CONTEXT.get({})
        if not isinstance(context, dict) or context.get("capture") is not capture:
            return
        data = event.data if isinstance(event.data, dict) else {}
        outcome = data.get("turn_outcome")
        if outcome is None:
            return
        s.append_conversation_turn_outcome(s.PROJECT_ROOT, session_id, capture.turn_id, outcome)
        s._invalidate_session_conversation_events_cache(session_id)
        capture.mark_content_committed()

    for event_name in (s.EventNames.TOOL_START, s.EventNames.TOOL_SUCCESS, s.EventNames.TOOL_ERROR):
        callback_ids.append(
            event_bus.subscribe(
                event_name,
                tool_event_proxy,
                callback_id=f"web_chat_{session_id}_{event_name}_{id(capture)}",
            )
        )
    callback_ids.append(
        event_bus.subscribe(
            s.EventNames.LLM_RESPONSE,
            llm_response_event_proxy,
            callback_id=f"web_chat_{session_id}_{s.EventNames.LLM_RESPONSE}_{id(capture)}",
        )
    )
    callback_ids.append(
        event_bus.subscribe(
            s.EventNames.LLM_STATUS,
            llm_status_event_proxy,
            callback_id=f"web_chat_{session_id}_{s.EventNames.LLM_STATUS}_{id(capture)}",
        )
    )
    with s.llm_status_context(session_id=session_id, turn_id=capture.turn_id):
        token = _SESSION_UI_CAPTURE_CONTEXT.set(
            {
                "ui": ui,
                "sessionId": session_id,
                "capture": capture,
                "mentalModelEnabled": mental_model_enabled,
                "textBatcher": _SessionUiCaptureTextBatcher(session_id=session_id, capture=capture),
            }
        )
        try:
            yield
        finally:
            context = _SESSION_UI_CAPTURE_CONTEXT.get({})
            batcher = context.get("textBatcher") if isinstance(context, dict) else None
            if isinstance(batcher, _SessionUiCaptureTextBatcher):
                batcher.flush_all()
            _commit_session_capture_assistant_segment(
                session_id,
                capture,
                boundary="capture_close",
            )
            _SESSION_UI_CAPTURE_CONTEXT.reset(token)
            for callback_id in callback_ids:
                event_bus.unsubscribe_by_id(callback_id)

def _ensure_session_ui_capture_hooks(ui: Any) -> None:
    s = _service()
    if bool(getattr(ui, "_vibelution_session_capture_wrapped", False)):
        return
    with _SESSION_UI_CAPTURE_LOCK:
        if bool(getattr(ui, "_vibelution_session_capture_wrapped", False)):
            return
        originals = {
            "stream_thought": getattr(ui, "stream_thought", None),
            "clear_thought_stream": getattr(ui, "clear_thought_stream", None),
            "stream_response": getattr(ui, "stream_response", None),
            "clear_response_stream": getattr(ui, "clear_response_stream", None),
            "set_pet_mental_state": getattr(ui, "set_pet_mental_state", None),
        }

        def active_context() -> dict[str, Any]:
            s = _service()
            context = _SESSION_UI_CAPTURE_CONTEXT.get({})
            if not isinstance(context, dict) or context.get("ui") is not ui:
                return {}
            return context

        def stream_thought_proxy(text: str, done: bool = False):
            s = _service()
            original = originals.get("stream_thought")
            if callable(original):
                original(text, done=done)
            context = active_context()
            capture = context.get("capture")
            session_id = str(context.get("sessionId") or "").strip()
            if not isinstance(capture, SessionTurnCapture) or not session_id:
                return
            cleaned = s._sanitize_thought_delta_text(text)
            if cleaned and not done:
                batcher = context.get("textBatcher")
                capture.note_thought(cleaned)
                s._set_session_model_thinking_live_output(
                    session_id,
                    turn_id=capture.turn_id,
                    thought_chars=len(cleaned),
                )
                if isinstance(batcher, _SessionUiCaptureTextBatcher):
                    batcher.note_thought(capture.thought, feedback_events=capture.feedback_events)
                else:
                    s._set_session_live_output(
                        session_id,
                        turn_id=capture.turn_id,
                        thought=capture.thought,
                        feedback_events=capture.feedback_events,
                    )

        def clear_thought_stream_proxy():
            s = _service()
            original = originals.get("clear_thought_stream")
            if callable(original):
                original()
            context = active_context()
            capture = context.get("capture")
            session_id = str(context.get("sessionId") or "").strip()
            if not isinstance(capture, SessionTurnCapture) or not session_id:
                return
            batcher = context.get("textBatcher")
            if isinstance(batcher, _SessionUiCaptureTextBatcher):
                batcher.clear_thought()
            else:
                s._set_session_live_output(session_id, turn_id=capture.turn_id, thought="")
            capture.clear_thought()

        def stream_response_proxy(text: str, done: bool = False):
            s = _service()
            original = originals.get("stream_response")
            if callable(original):
                original(text, done=done)
            context = active_context()
            capture = context.get("capture")
            session_id = str(context.get("sessionId") or "").strip()
            if not isinstance(capture, SessionTurnCapture) or not session_id:
                return
            cleaned = s._sanitize_message_content("assistant", text)
            if cleaned:
                previous = str(capture.content or "")
                if done:
                    next_content = cleaned
                elif previous and cleaned.startswith(previous):
                    next_content = cleaned
                else:
                    next_content = f"{previous}{cleaned}" if previous else cleaned
                capture.note_content(next_content)
                batcher = context.get("textBatcher")
                if isinstance(batcher, _SessionUiCaptureTextBatcher):
                    batcher.note_response(next_content, done=done)
                else:
                    s._set_session_live_output(
                        session_id,
                        turn_id=capture.turn_id,
                        stage="assistant_response",
                        content=next_content,
                    )
            elif done:
                batcher = context.get("textBatcher")
                if isinstance(batcher, _SessionUiCaptureTextBatcher):
                    batcher.flush_all()

        def clear_response_stream_proxy():
            s = _service()
            original = originals.get("clear_response_stream")
            if callable(original):
                original()
            context = active_context()
            capture = context.get("capture")
            session_id = str(context.get("sessionId") or "").strip()
            if not isinstance(capture, SessionTurnCapture) or not session_id:
                return
            capture.clear_content()
            batcher = context.get("textBatcher")
            if isinstance(batcher, _SessionUiCaptureTextBatcher):
                batcher.clear_response()
            else:
                s._set_session_live_output(session_id, turn_id=capture.turn_id, content="")

        def set_pet_mental_state_proxy(mood: str = "", feeling: str = "", whisper: str = ""):
            s = _service()
            original = originals.get("set_pet_mental_state")
            if callable(original):
                original(mood=mood, feeling=feeling, whisper=whisper)
            context = active_context()
            capture = context.get("capture")
            session_id = str(context.get("sessionId") or "").strip()
            if not isinstance(capture, SessionTurnCapture) or not session_id:
                return
            if not s._is_mental_model_enabled_for_turn(context.get("mentalModelEnabled")):
                return
            batcher = context.get("textBatcher")
            if isinstance(batcher, _SessionUiCaptureTextBatcher):
                batcher.flush_all()
            capture.note_mental_state(mood=mood, feeling=feeling, whisper=whisper)
            snapshot = s._live_mental_snapshot(capture.mental_state, s.get_web_language())
            if snapshot is not None:
                s._set_session_live_output(
                    session_id,
                    turn_id=capture.turn_id,
                    mental_snapshot=snapshot,
                    feedback_events=capture.feedback_events,
                )

        setattr(ui, "_vibelution_session_capture_originals", originals)
        setattr(ui, "stream_thought", stream_thought_proxy)
        setattr(ui, "clear_thought_stream", clear_thought_stream_proxy)
        setattr(ui, "stream_response", stream_response_proxy)
        setattr(ui, "clear_response_stream", clear_response_stream_proxy)
        setattr(ui, "set_pet_mental_state", set_pet_mental_state_proxy)
        setattr(ui, "_vibelution_session_capture_wrapped", True)
