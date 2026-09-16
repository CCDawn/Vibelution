# -*- coding: utf-8 -*-
"""Answer-channel internal-format leak guard.

Incident class (2026-09-16, deepseek-v4.1-flash via opencode/CommandCode
relay): the model's *internal* formatting reached the user-visible answer
channel as final-answer text:

- Case A: a legacy tool call leaked as text — ``<tool calls>`` (space, plural)
  plus ``<parameter name=...>`` and DSML-mangled closers (``</｜DSML｜ invoke>``,
  full-width bars). Neither matches ``legacy_xml_tool_decoder`` (no opening
  ``<invoke``/``<tool_call``) nor the angle-bracket patterns in the output
  boundary (full-width bars).
- Case B: the model's entire复盘 leaked as the answer — a complete
  ``<analysis>`` envelope plus an output-budget-truncated ``<summary>``
  (~8k chars), zero words answering the user, turn still ``completed``.

This module composes with ``canonicalize_legacy_xml_outcome`` at the adapter's
canonicalize seam (both the streamed and non-streamed outcome assembly points
run inside the adapter's try block), so a classified exception raised here
flows into the existing ``plan_recovery`` degraded-retry path for free.

Three stages, in order:

1. Lossless parse recovery (before any retry): ``<analysis>``/``<summary>``
   envelopes are stripped into the reasoning/thought channel (see
   ``reasoning_extractor.extract_analysis_envelope_reasoning``) and text
   tool-call fragments are re-parsed into structured tool calls
   (conservatively — only when a recognizable structure start exists; the
   Ollama-style guidance is to prefer false negatives). If residual visible
   text is non-empty the recovered outcome is released with leak telemetry.
2. Same-turn degraded retry: when recovery fails or the residual visible text
   is empty, the guard raises ``LLMError(answer_channel_leak)``. The recovery
   vocabulary maps it to ``retry_answer_without_tools`` (streaming off, tools
   off), budgeted once per invocation by the adapter's
   ``degraded_actions_used``.
3. Release with markers (circuit-breaker count): if the retry attempt leaks
   again, the original outcome is released unchanged but annotated with
   ``leakMarkers`` outcome metadata, a per-(gateway, model) in-process counter
   is bumped (interface reserved for future protocol-degradation rating), and
   the ``answer_channel_leak_detected`` scene event is emitted. The persist
   layer shows a user-visible notice for the retried case.

Detection is deliberately conservative (fence-aware, position/count
thresholds) so normal markdown, code-fenced XML teaching content, and inline
code-span discussions of these tags never trigger.
"""

from __future__ import annotations

import re
import threading
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Callable

from core.infrastructure.llm_utils import parse_xml_tool_calls
from core.llm.reasoning_extractor import (
    UNCLOSED_ENVELOPE_MAX_OPEN_RATIO,
    UNCLOSED_ENVELOPE_MIN_BODY_CHARS,
    extract_analysis_envelope_reasoning,
    strip_analysis_envelopes,
)
from core.orchestration.output_boundary import strip_llm_protocol_artifacts
from core.llm.types import (
    CanonicalItemIdentity,
    CanonicalToolCall,
    LLMError,
    LLMProtocolEvent,
    TurnOutcome,
)

ANSWER_CHANNEL_LEAK_CATEGORY = "answer_channel_leak"
ANSWER_CHANNEL_LEAK_EVENT = "answer_channel_leak_detected"

__all__ = [
    "ANSWER_CHANNEL_LEAK_CATEGORY",
    "ANSWER_CHANNEL_LEAK_EVENT",
    "LeakFinding",
    "build_answer_channel_guard",
    "detect_answer_channel_leak",
    "recover_answer_channel_leak",
    "answer_channel_leak_route_counts",
    "reset_answer_channel_leak_state",
]


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LeakFinding:
    """A conservative leak verdict: which markers fired and why."""

    markers: tuple[str, ...]
    first_positions: dict[str, int] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    probe_chars: int = 0
    triggered_by: tuple[str, ...] = ()

    @property
    def marker_names(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.markers)))


# Structural leak markers. Matched against fence-stripped probe text only.
_LEAK_MARKER_RES = (
    ("analysis_tag", re.compile(r"<analysis\b|</analysis\b", re.IGNORECASE)),
    ("summary_tag", re.compile(r"<summary\b|</summary\b", re.IGNORECASE)),
    ("tool_calls_tag", re.compile(r"<tool\s*calls?\s*>|</tool\s*calls?\s*>", re.IGNORECASE)),
    ("dsml_marker", re.compile(r"｜DSML｜")),
    ("invoke_tag", re.compile(r"<\s*invoke\b", re.IGNORECASE)),
    ("parameter_tag", re.compile(r"<\s*parameter\s+name\s*=", re.IGNORECASE)),
)

# Fenced markdown code blocks: ``` or ~~~ fences. An unclosed fence protects
# everything from the fence line to the end of the text.
_FENCE_LINE_RE = re.compile(r"^[ \t]*(?:```+|~~~+)", re.MULTILINE)
# Inline code spans (`...`): discussing a tag inside backticks is prose, not a
# structural leak. Spans of 1+ backticks matched conservatively.
_INLINE_CODE_SPAN_RE = re.compile(r"`+[^`]*`+")

# Thresholds.
FRONT_POSITION_RATIO = 0.2
MARKER_COUNT_TRIGGER = 2
SHORT_TEXT_CHARS = 200
SHORT_PURE_LEAK_RESIDUAL_CHARS = 20


def strip_code_fences(text: str) -> str:
    """Return probe text with fenced code blocks (and inline code) removed.

    An unclosed fence protects everything after the fence line — teaching
    content inside an unterminated block is still code, not an answer leak.
    """
    if not text:
        return ""
    lines = text.splitlines(keepends=True)
    probe_lines: list[str] = []
    inside_fence = False
    fence_marker = ""
    for line in lines:
        if inside_fence:
            if line.lstrip().startswith(fence_marker):
                inside_fence = False
            continue
        match = _FENCE_LINE_RE.match(line)
        if match:
            inside_fence = True
            fence_marker = line.lstrip()[:3]
            continue
        probe_lines.append(line)
    probe = "".join(probe_lines)
    return _INLINE_CODE_SPAN_RE.sub(" ", probe)


def detect_answer_channel_leak(
    text: str,
    *,
    structured_reasoning_present: bool = False,
    terminal_incomplete: bool = False,
) -> LeakFinding | None:
    """Detect internal-format leakage in a final-answer text.

    Signal rules (any one triggers): a marker occurs in the front
    :data:`FRONT_POSITION_RATIO` of the probe text; total marker occurrences
    >= :data:`MARKER_COUNT_TRIGGER`; the answer is short
    (:data:`SHORT_TEXT_CHARS`) and essentially pure leak (near-zero residual
    visible text) with a single marker; or the provider signalled an
    incomplete terminal (truncation), which tightens the threshold to any
    marker anywhere. ``structured_reasoning_present`` does not suppress
    detection (a leaked envelope is still a leak); it only steers recovery.
    """
    probe = strip_code_fences(str(text or ""))
    if not probe.strip():
        return None

    first_positions: dict[str, int] = {}
    counts: dict[str, int] = {}
    total_count = 0
    for name, pattern in _LEAK_MARKER_RES:
        matches = list(pattern.finditer(probe))
        if not matches:
            continue
        first_positions[name] = matches[0].start()
        counts[name] = len(matches)
        total_count += len(matches)

    if not counts:
        return None

    triggered_by: list[str] = []
    front_limit = len(probe) * FRONT_POSITION_RATIO
    if any(position <= front_limit for position in first_positions.values()):
        triggered_by.append("front_position")
    if total_count >= MARKER_COUNT_TRIGGER:
        triggered_by.append("marker_count")
    if terminal_incomplete:
        triggered_by.append("terminal_incomplete")
    if (
        len(probe) < SHORT_TEXT_CHARS
        and residual_visible_chars(str(text or "")) < SHORT_PURE_LEAK_RESIDUAL_CHARS
    ):
        triggered_by.append("short_pure_leak")

    if not triggered_by:
        return None

    markers = tuple(
        name
        for name, _pattern in _LEAK_MARKER_RES
        if name in first_positions
    )
    return LeakFinding(
        markers=markers,
        first_positions=first_positions,
        counts=counts,
        probe_chars=len(probe),
        triggered_by=tuple(triggered_by),
    )


# ---------------------------------------------------------------------------
# Stage 1: lossless parse recovery
# ---------------------------------------------------------------------------

# DSML-mangled structural fragments: </｜DSML｜ invoke>, <｜DSML｜ parameter>,
# or bare ｜DSML｜残片 mixed into the leaked block.
_DSML_FRAGMENT_RE = re.compile(r"</?\s*｜\s*DSML\s*｜\s*[^>\n]{0,60}>?|｜\s*DSML\s*｜")
_TOOL_CALLS_WRAPPER_RE = re.compile(r"</?\s*tool\s*calls?\s*>", re.IGNORECASE)
_INVOKE_OPEN_RE = re.compile(r"<\s*invoke\s+name\s*=", re.IGNORECASE)


def residual_visible_chars(text: str) -> int:
    """Length of the visible text left after removing leak structures.

    Used by the short-pure-leak rule and by recovery to decide whether any
    user-facing answer survived.
    """
    cleaned = strip_analysis_envelopes(text)
    cleaned = _DSML_FRAGMENT_RE.sub("", cleaned)
    cleaned = _TOOL_CALLS_WRAPPER_RE.sub("", cleaned)
    cleaned = strip_llm_protocol_artifacts(cleaned)
    return len(cleaned.strip())


def _identity_for(outcome: TurnOutcome, item_id: str) -> CanonicalItemIdentity:
    return CanonicalItemIdentity(
        session_id=outcome.identity.session_id,
        turn_id=outcome.identity.turn_id,
        invocation_id=outcome.identity.invocation_id,
        iteration=outcome.identity.iteration,
        item_id=item_id,
    )


def _normalize_leak_structures(text: str) -> str:
    """Strip DSML-mangled fragments and ``<tool calls>`` wrappers from text."""
    cleaned = _DSML_FRAGMENT_RE.sub("", text)
    cleaned = _TOOL_CALLS_WRAPPER_RE.sub("", cleaned)
    return cleaned


def _recover_tool_call_fragment(
    text: str,
    outcome: TurnOutcome,
) -> tuple[CanonicalToolCall, ...]:
    """Conservatively re-parse a text tool-call fragment into structured calls.

    Only converts when a recognizable ``<invoke name=`` structure start exists
    after normalizing DSML-mangled closers and ``<tool calls>`` wrappers —
    the Ollama-style guidance is to prefer false negatives over hallucinating
    tool calls from prose. Returns ``()`` when nothing well-formed is found.
    """
    normalized = _normalize_leak_structures(text)
    if not _INVOKE_OPEN_RE.search(normalized):
        return ()
    try:
        parsed = parse_xml_tool_calls(normalized)
    except Exception:
        return ()
    calls = []
    for index, item in enumerate(parsed or ()):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        call_id = str(item.get("id") or f"leak_xml_{index}")
        calls.append(
            CanonicalToolCall(
                identity=_identity_for(outcome, call_id),
                call_id=call_id,
                name=name,
                arguments=dict(item.get("args") or {}),
            )
        )
    return tuple(calls)


def recover_answer_channel_leak(
    outcome: TurnOutcome,
    finding: LeakFinding,
) -> TurnOutcome | None:
    """Stage 1 recovery: route leaked structures to their proper channels.

    Returns a recovered :class:`TurnOutcome`, or ``None`` when recovery fails
    (no recognizable structure or zero residual visible text) and the caller
    should escalate to the degraded retry.
    """
    text = str(outcome.final_text or "")
    if not text.strip():
        return None

    structured_reasoning_present = any(
        event.kind == "reasoning_delta" and event.text for event in outcome.events
    )

    # Analysis/summary envelopes → reasoning/thought channel. When the
    # provider already delivered reasoning via structured fields, trust the
    # field and do not carve reasoning out of the body.
    reasoning_extraction = extract_analysis_envelope_reasoning(text)
    residual = strip_analysis_envelopes(text)

    # Tool-call fragment re-parse (conservative; usually unconvertible
    # fragments like the Case A dialect fall through to the retry stage).
    tool_calls = _recover_tool_call_fragment(residual, outcome)
    if tool_calls:
        commentary = strip_llm_protocol_artifacts(_normalize_leak_structures(residual))
        return TurnOutcome(
            kind="tool_calls",
            identity=outcome.identity,
            events=outcome.events,
            tool_calls=tool_calls,
            final_text=commentary,
            pending_tool_call_ids=tuple(call.call_id for call in tool_calls),
            terminal_event_seen=True,
            replay_state=outcome.replay_state,
            metadata=_leak_metadata(finding, recovered=True, retried=False),
        )

    residual = strip_llm_protocol_artifacts(_normalize_leak_structures(residual))
    if not residual.strip():
        return None

    events = outcome.events
    reasoning_body = reasoning_extraction.text
    if reasoning_body and not structured_reasoning_present:
        next_sequence = max((event.sequence for event in outcome.events), default=-1) + 1
        events = tuple(outcome.events) + (
            LLMProtocolEvent(
                kind="reasoning_delta",
                sequence=next_sequence,
                session_id=outcome.identity.session_id,
                invocation_id=outcome.identity.invocation_id,
                iteration=outcome.identity.iteration,
                turn_id=outcome.identity.turn_id,
                item_id="answer_leak_recovered_reasoning",
                text=reasoning_body,
            ),
        )
    return TurnOutcome(
        kind="final_answer",
        identity=outcome.identity,
        events=events,
        final_text=residual.strip(),
        terminal_event_seen=True,
        replay_state=outcome.replay_state,
        metadata=_leak_metadata(finding, recovered=True, retried=False),
    )


# ---------------------------------------------------------------------------
# Stage 2/3 state: per-turn retry tracking and per-route counters
# ---------------------------------------------------------------------------

# (session_id, turn_id) -> invocation_id of the attempt whose leak raised.
# A pending entry is consumed by the very next canonicalize call for the same
# key: the degraded retry runs synchronously inside the same adapter loop, so
# the next outcome for the key is the retry attempt (or a later, clean
# iteration, which then reports the retry in telemetry instead).
_TURN_LEAK_PENDING: "OrderedDict[tuple[str, str], str]" = OrderedDict()
_TURN_LEAK_PENDING_CAP = 512
_TURN_LEAK_LOCK = threading.Lock()

# (gateway, model) -> observed leak count, process-local. Reserved interface
# for future protocol-degradation rating; not a circuit breaker yet.
_ROUTE_LEAK_COUNTS: dict[tuple[str, str], int] = {}


def _mark_retry_pending(key: tuple[str, str], invocation_id: str) -> None:
    with _TURN_LEAK_LOCK:
        _TURN_LEAK_PENDING[key] = invocation_id
        _TURN_LEAK_PENDING.move_to_end(key)
        while len(_TURN_LEAK_PENDING) > _TURN_LEAK_PENDING_CAP:
            _TURN_LEAK_PENDING.popitem(last=False)


def _peek_retry_pending(key: tuple[str, str]) -> bool:
    with _TURN_LEAK_LOCK:
        return key in _TURN_LEAK_PENDING


def _consume_retry_pending(key: tuple[str, str]) -> None:
    with _TURN_LEAK_LOCK:
        _TURN_LEAK_PENDING.pop(key, None)


def _bump_route_leak_counter(route: tuple[str, str] | None) -> None:
    if not route:
        return
    with _TURN_LEAK_LOCK:
        _ROUTE_LEAK_COUNTS[route] = _ROUTE_LEAK_COUNTS.get(route, 0) + 1


def answer_channel_leak_route_counts() -> dict[tuple[str, str], int]:
    with _TURN_LEAK_LOCK:
        return dict(_ROUTE_LEAK_COUNTS)


def reset_answer_channel_leak_state() -> None:
    """Test/helper hook: clear per-turn pending marks and route counters."""
    with _TURN_LEAK_LOCK:
        _TURN_LEAK_PENDING.clear()
        _ROUTE_LEAK_COUNTS.clear()


def _leak_metadata(finding: LeakFinding, *, recovered: bool, retried: bool) -> dict[str, Any]:
    return {
        "leakMarkers": list(finding.marker_names),
        "leakTriggeredBy": list(finding.triggered_by),
        "leakRecovered": bool(recovered),
        "leakRetried": bool(retried),
    }


# ---------------------------------------------------------------------------
# Composed canonicalize wrapper
# ---------------------------------------------------------------------------

RecordEventFn = Callable[..., None]
ResolveRouteFn = Callable[[], tuple[str, str]]


def build_answer_channel_guard(
    base: Callable[[TurnOutcome], TurnOutcome],
    *,
    record_event: RecordEventFn | None = None,
    resolve_route: ResolveRouteFn | None = None,
) -> Callable[[TurnOutcome], TurnOutcome]:
    """Compose the leak guard around ``canonicalize_legacy_xml_outcome``.

    The returned callable keeps the ``canonicalize(outcome)`` hook shape, so
    it plugs into ``AgentLlmTurnHooks`` at the outcome assembly point (inside
    the adapter try block) for both the streamed and non-streamed paths.
    """

    def _emit(
        outcome: TurnOutcome,
        finding: LeakFinding | None,
        *,
        recovered: bool,
        retried: bool,
        retry_requested: bool = False,
    ) -> None:
        if record_event is None:
            return
        try:
            fields: dict[str, Any] = {
                "sessionId": outcome.identity.session_id,
                "turnId": outcome.identity.turn_id,
                "invocationId": outcome.identity.invocation_id,
                "outcomeKind": outcome.kind,
            }
            if finding is not None:
                fields["leakMarkers"] = list(finding.marker_names)
                fields["leakTriggeredBy"] = list(finding.triggered_by)
                fields["leakProbeChars"] = int(finding.probe_chars)
            fields["leakRecovered"] = bool(recovered)
            fields["leakRetried"] = bool(retried)
            if retry_requested:
                fields["leakRetryRequested"] = True
            record_event(
                "llm_route",
                ANSWER_CHANNEL_LEAK_EVENT,
                message=(
                    "检测到模型把内部格式泄漏为答复通道，已按三段式守卫处理"
                    "（解析恢复→同体降级重试→带标记放行）。"
                ),
                fields=fields,
                level="warning",
                outcome="degraded",
            )
        except Exception:
            return

    def _guarded(outcome: TurnOutcome) -> TurnOutcome:
        outcome = base(outcome)
        if outcome.kind != "final_answer" or not str(outcome.final_text or "").strip():
            return outcome

        identity = outcome.identity
        key = (identity.session_id, identity.turn_id)
        retry_pending = _peek_retry_pending(key)

        finding = detect_answer_channel_leak(
            outcome.final_text,
            structured_reasoning_present=any(
                event.kind == "reasoning_delta" and event.text for event in outcome.events
            ),
            terminal_incomplete=any(event.kind == "turn_incomplete" for event in outcome.events),
        )
        if finding is None:
            if retry_pending:
                # Clean outcome on the retry attempt: report that one degraded
                # retry was spent and stop tracking this turn.
                _consume_retry_pending(key)
                _bump_route_leak_counter(resolve_route() if resolve_route else None)
                _emit(outcome, None, recovered=True, retried=True)
                return _with_metadata(outcome, recovered=True, retried=True, markers=())
            return outcome

        recovered = recover_answer_channel_leak(outcome, finding)
        if recovered is not None:
            _consume_retry_pending(key)
            _bump_route_leak_counter(resolve_route() if resolve_route else None)
            _emit(outcome, finding, recovered=True, retried=retry_pending)
            return _with_metadata(
                recovered,
                recovered=True,
                retried=retry_pending,
                markers=finding.marker_names,
                triggered_by=finding.triggered_by,
            )

        if not retry_pending:
            # First unrecoverable leak this invocation: raise so the existing
            # adapter except-block plans the ``retry_answer_without_tools``
            # degraded retry (budgeted once per invocation).
            _mark_retry_pending(key, identity.invocation_id)
            _emit(outcome, finding, recovered=False, retried=False, retry_requested=True)
            raise LLMError(
                ANSWER_CHANNEL_LEAK_CATEGORY,
                "model leaked internal formatting (analysis/tool-call envelope) "
                "into the final answer channel",
                retryable=True,
                details={
                    "leakMarkers": list(finding.marker_names),
                    "leakTriggeredBy": list(finding.triggered_by),
                    "leakProbeChars": int(finding.probe_chars),
                },
            )

        # Second unrecoverable leak on the retry attempt: release unchanged
        # with leak markers so the turn still completes, telemetry recorded.
        _consume_retry_pending(key)
        _bump_route_leak_counter(resolve_route() if resolve_route else None)
        _emit(outcome, finding, recovered=False, retried=True)
        return _with_metadata(
            outcome,
            recovered=False,
            retried=True,
            markers=finding.marker_names,
            triggered_by=finding.triggered_by,
        )

    return _guarded


def _with_metadata(
    outcome: TurnOutcome,
    *,
    recovered: bool,
    retried: bool,
    markers: tuple[str, ...],
    triggered_by: tuple[str, ...] = (),
) -> TurnOutcome:
    patch: dict[str, Any] = {
        "leakMarkers": list(markers),
        "leakRecovered": bool(recovered),
        "leakRetried": bool(retried),
    }
    if triggered_by:
        patch["leakTriggeredBy"] = list(triggered_by)
    existing = outcome.metadata if isinstance(outcome.metadata, Mapping) else {}
    merged: dict[str, Any] = {**dict(existing), **patch}
    try:
        return TurnOutcome(
            kind=outcome.kind,
            identity=outcome.identity,
            events=outcome.events,
            tool_calls=outcome.tool_calls,
            tool_results=outcome.tool_results,
            final_text=outcome.final_text,
            pending_tool_call_ids=outcome.pending_tool_call_ids,
            terminal_event_seen=outcome.terminal_event_seen,
            error=outcome.error,
            replay_state=outcome.replay_state,
            model_invocation_receipt=outcome.model_invocation_receipt,
            metadata=merged,
        )
    except (TypeError, ValueError):
        # Metadata annotation must never break the outcome itself.
        return outcome
