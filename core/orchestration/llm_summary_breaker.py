# -*- coding: utf-8 -*-
"""LLM summary consecutive-failure circuit breaker for context compression.

DEEP/EMERGENCY full compression summarizes old history with a lightweight LLM.
When that summary keeps failing, silently falling back to the rule-based
summary on every attempt both burns retries against a failing dependency and
hides the degradation. This module keeps the in-process consecutive-failure
state per session/agent scope and reports it as structured scene events.

Design anchors (ZCode CLI, apps/zcode-cli/packages/core/src/compact/policy.ts,
MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES = 3, Apache-2.0): failures have a cap,
the breaker pauses only the *automatic* path, one success resets the counter,
and cancellation-adjacent paths never count as failures. Micro-compaction and
manual/explicit compression requests are never intercepted here; while the
breaker is open, automatic full compression degrades explicitly to the
rule-based summary instead of hammering the failing LLM.

State placement follows the existing in-process compression runtime state
precedent (``tools/token_manager.py`` module-level compression-request flags):
the breaker is a runtime pause for the owning session process. Durable
per-attempt failure evidence already lives in the conversation ledger
(``failed_preserved`` markers), so nothing here needs to persist across a
process restart -- a restart also rebuilds the LLM client state that failed.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, Optional

DEFAULT_LLM_SUMMARY_FAILURE_BREAKER_THRESHOLD = 3
BREAKER_GUARD_REASON = "llm_summary_breaker_open"

_ERROR_SUMMARY_MAX_CHARS = 160

_lock = threading.Lock()
_states: Dict[str, Dict[str, Any]] = {}


def scope_key(session_id: str = "", agent_id: str = "") -> str:
    """Resolve the breaker scope key: session first, agent fallback."""

    session = str(session_id or "").strip()
    agent = str(agent_id or "").strip()
    if session:
        return f"session:{session}"
    if agent:
        return f"agent:{agent}"
    return "session:anonymous"


def _summary_text(error_text: Any) -> str:
    text = str(error_text or "").strip().replace("\r", " ").replace("\n", " ")
    return text[:_ERROR_SUMMARY_MAX_CHARS]


def _coerce_threshold(threshold: Any) -> int:
    try:
        value = int(threshold)
    except (TypeError, ValueError):
        return DEFAULT_LLM_SUMMARY_FAILURE_BREAKER_THRESHOLD
    return max(0, value)


def consecutive_failures(session_id: str = "", agent_id: str = "") -> int:
    """Current consecutive LLM summary failure count for the scope."""

    key = scope_key(session_id, agent_id)
    with _lock:
        state = _states.get(key)
        return int(state.get("consecutiveFailures", 0)) if state else 0


def is_open(session_id: str = "", agent_id: str = "") -> bool:
    """Whether the breaker is open (automatic full compression degraded)."""

    key = scope_key(session_id, agent_id)
    with _lock:
        state = _states.get(key)
        return bool(state.get("open", False)) if state else False


def snapshot(session_id: str = "", agent_id: str = "") -> Dict[str, Any]:
    """Read-only copy of the scope state for diagnostics/tests."""

    key = scope_key(session_id, agent_id)
    with _lock:
        state = _states.get(key)
        if not state:
            return {"consecutiveFailures": 0, "open": False, "lastErrorSummary": ""}
        return dict(state)


def reset_scope(session_id: str = "", agent_id: str = "") -> None:
    """Drop the scope state (used by tests and scope teardown)."""

    key = scope_key(session_id, agent_id)
    with _lock:
        _states.pop(key, None)


def reset_all() -> None:
    """Drop every scope state (test isolation only)."""

    with _lock:
        _states.clear()


def record_failure(
    session_id: str = "",
    agent_id: str = "",
    *,
    error_text: Any = "",
    threshold: Any = DEFAULT_LLM_SUMMARY_FAILURE_BREAKER_THRESHOLD,
) -> Dict[str, Any]:
    """Record one LLM summary failure and evaluate the breaker transition.

    Returns event fields: consecutiveFailures, threshold, breakerOpen,
    breakerTripped (False -> True transition), errorSummary. Cancellations and
    non-attempts must not be recorded here -- only actual LLM summary failures.
    """

    key = scope_key(session_id, agent_id)
    limit = _coerce_threshold(threshold)
    error_summary = _summary_text(error_text)
    with _lock:
        state = _states.setdefault(
            key, {"consecutiveFailures": 0, "open": False, "lastErrorSummary": ""}
        )
        state["consecutiveFailures"] = int(state.get("consecutiveFailures", 0)) + 1
        state["lastErrorSummary"] = error_summary
        was_open = bool(state.get("open", False))
        tripped = False
        if limit > 0 and state["consecutiveFailures"] >= limit and not was_open:
            state["open"] = True
            tripped = True
        return {
            "consecutiveFailures": state["consecutiveFailures"],
            "threshold": limit,
            "breakerOpen": bool(state.get("open", False)),
            "breakerTripped": tripped,
            "errorSummary": error_summary,
        }


def record_success(session_id: str = "", agent_id: str = "") -> Dict[str, Any]:
    """Reset the consecutive-failure counter after one successful LLM summary.

    Returns event fields: consecutiveFailures (always 0 after the reset),
    breakerReleased (True when an open breaker closed again).
    """

    key = scope_key(session_id, agent_id)
    with _lock:
        state = _states.get(key)
        was_open = bool(state.get("open", False)) if state else False
        if state:
            state["consecutiveFailures"] = 0
            state["open"] = False
            state["lastErrorSummary"] = ""
        return {
            "consecutiveFailures": 0,
            "threshold": DEFAULT_LLM_SUMMARY_FAILURE_BREAKER_THRESHOLD,
            "breakerOpen": False,
            "breakerReleased": was_open,
        }


class SummaryBreakerReporter:
    """Failure/success hook handed to the compressor's LLM summary path.

    The compressor owns the attempt; this reporter owns the policy: counting,
    breaker transitions, and the structured scene events that replace the old
    silent warning-only fallback. ``recorder`` is the same scene-event callable
    ``compress_turn_messages`` already uses, so events land in the runtime
    scene exactly like the other compression events.
    """

    def __init__(
        self,
        *,
        session_id: str = "",
        agent_id: str = "",
        turn_id: str = "",
        iteration: int = 0,
        threshold: Any = DEFAULT_LLM_SUMMARY_FAILURE_BREAKER_THRESHOLD,
        trigger_source: str = "",
        recorder: Optional[Callable[..., None]] = None,
    ) -> None:
        self._session_id = str(session_id or "").strip()
        self._agent_id = str(agent_id or "").strip()
        self._turn_id = str(turn_id or "").strip()
        self._iteration = max(0, int(iteration or 0))
        self._threshold = _coerce_threshold(threshold)
        self._trigger_source = str(trigger_source or "").strip()
        self._recorder = recorder

    def _base_fields(self) -> Dict[str, Any]:
        return {
            "agentId": self._agent_id,
            "sessionId": self._session_id,
            "turnId": self._turn_id,
            "iteration": self._iteration,
            "triggerSource": self._trigger_source,
        }

    def on_failure(self, error_text: Any = "") -> Dict[str, Any]:
        state = record_failure(
            self._session_id,
            self._agent_id,
            error_text=error_text,
            threshold=self._threshold,
        )
        fields = {
            **self._base_fields(),
            "fallbackType": "rule_based_summary",
            "consecutiveFailures": state["consecutiveFailures"],
            "threshold": state["threshold"],
            "breakerOpen": state["breakerOpen"],
            "errorSummary": state["errorSummary"],
        }
        if self._recorder is not None:
            self._recorder(
                "runtime",
                "agent.context_compression.llm_summary_fallback",
                message="Compression LLM summary failed; degraded to the rule-based summary.",
                level="warning",
                outcome="degraded",
                fields=fields,
            )
        if state["breakerTripped"]:
            if self._recorder is not None:
                self._recorder(
                    "runtime",
                    "agent.context_compression.llm_summary_breaker_tripped",
                    message=(
                        "Compression LLM summary failed repeatedly; automatic full "
                        "compression is degraded to rule summaries until one succeeds."
                    ),
                    level="warning",
                    outcome="paused",
                    fields={**self._base_fields(), **fields},
                )
        return state

    def on_success(self) -> Dict[str, Any]:
        state = record_success(self._session_id, self._agent_id)
        if state.get("breakerReleased") and self._recorder is not None:
            self._recorder(
                "runtime",
                "agent.context_compression.llm_summary_breaker_released",
                message="Compression LLM summary succeeded; automatic full compression resumes.",
                level="info",
                outcome="resumed",
                fields={
                    **self._base_fields(),
                    "consecutiveFailures": 0,
                    "threshold": self._threshold,
                },
            )
        return state
