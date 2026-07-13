# -*- coding: utf-8 -*-
"""Bounded compatibility decoder for historical XML tool-call syntax."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from core.infrastructure.llm_utils import parse_xml_tool_calls
from core.orchestration.output_boundary import strip_llm_protocol_artifacts

from .semantic_messages import InvocationScope
from .types import CanonicalItemIdentity, CanonicalToolCall, TurnOutcome


_XML_CONTROL_PATTERN = re.compile(r"<\s*(?:invoke|tool_call)\b", re.IGNORECASE)


@dataclass(frozen=True)
class LegacyXmlDecodeResult:
    matched: bool
    commentary: str
    tool_calls: tuple[CanonicalToolCall, ...]
    error: str = ""


def _identity(scope: InvocationScope, item_id: str) -> CanonicalItemIdentity:
    return CanonicalItemIdentity(
        session_id=scope.session_id,
        turn_id=scope.turn_id,
        invocation_id=scope.invocation_id,
        iteration=scope.iteration,
        item_id=item_id,
    )


def decode_legacy_xml_tool_calls(text: str, *, scope: InvocationScope) -> LegacyXmlDecodeResult:
    source = str(text or "")
    matched = bool(_XML_CONTROL_PATTERN.search(source))
    if not matched:
        return LegacyXmlDecodeResult(False, source, ())
    parsed = parse_xml_tool_calls(source)
    commentary = strip_llm_protocol_artifacts(source)
    if not parsed:
        return LegacyXmlDecodeResult(True, commentary, (), "tool_call_decode_error")
    calls = tuple(
        CanonicalToolCall(
            identity=_identity(scope, str(item.get("id") or f"xml_{index}")),
            call_id=str(item.get("id") or f"xml_{index}"),
            name=str(item.get("name") or "").strip(),
            arguments=dict(item.get("args") or {}),
        )
        for index, item in enumerate(parsed)
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    )
    if not calls:
        return LegacyXmlDecodeResult(True, commentary, (), "tool_call_decode_error")
    return LegacyXmlDecodeResult(True, commentary, calls)


def canonicalize_legacy_xml_outcome(outcome: TurnOutcome) -> TurnOutcome:
    """Translate XML fallback once, before Agent control or tool execution."""
    if outcome.kind != "final_answer" or outcome.tool_calls:
        return outcome
    scope = InvocationScope(
        session_id=outcome.identity.session_id,
        turn_id=outcome.identity.turn_id,
        invocation_id=outcome.identity.invocation_id,
        iteration=outcome.identity.iteration,
    )
    decoded = decode_legacy_xml_tool_calls(outcome.final_text, scope=scope)
    if not decoded.matched:
        return outcome
    if decoded.error:
        return TurnOutcome(
            kind="failed",
            identity=outcome.identity,
            terminal_event_seen=True,
            replay_state=outcome.replay_state,
        )
    return TurnOutcome(
        kind="tool_calls",
        identity=outcome.identity,
        events=outcome.events,
        tool_calls=decoded.tool_calls,
        final_text=decoded.commentary,
        pending_tool_call_ids=tuple(call.call_id for call in decoded.tool_calls),
        terminal_event_seen=True,
        replay_state=outcome.replay_state,
    )


def canonical_outcome_from_message(message: Any, *, scope: InvocationScope) -> TurnOutcome:
    """Compatibility-only coercion for old test/plugin message producers."""
    content = str(getattr(message, "content", "") or "")
    raw_calls = list(getattr(message, "tool_calls", None) or [])
    calls: list[CanonicalToolCall] = []
    for index, item in enumerate(raw_calls):
        if not isinstance(item, dict):
            continue
        call_id = str(item.get("id") or f"compat_{index}")
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        calls.append(
            CanonicalToolCall(
                identity=_identity(scope, call_id),
                call_id=call_id,
                name=name,
                arguments=dict(item.get("args") or item.get("arguments") or {}),
            )
        )
    identity = _identity(scope, calls[0].call_id if calls else "compatibility-answer")
    if calls:
        return TurnOutcome(
            kind="tool_calls",
            identity=identity,
            tool_calls=tuple(calls),
            final_text=content,
            pending_tool_call_ids=tuple(call.call_id for call in calls),
            terminal_event_seen=True,
        )
    return canonicalize_legacy_xml_outcome(TurnOutcome.final_answer(identity=identity, text=content))


__all__ = [
    "LegacyXmlDecodeResult",
    "canonical_outcome_from_message",
    "canonicalize_legacy_xml_outcome",
    "decode_legacy_xml_tool_calls",
]
