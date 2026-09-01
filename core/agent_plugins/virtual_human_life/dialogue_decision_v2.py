"""Pure Companion Dialogue V2 draft validation; intentionally not runtime-wired.

The model owns only a bounded next-act declaration.  Native Session identity is
injected by the caller, source references are allow-listed for the current
turn, and this module persists neither transcript text nor delivery state.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import Any

DIALOGUE_DECISION_CONTRACT_VERSION_V2 = "companion_dialogue_decision.v2"

_MODEL_FIELDS = frozenset(
    {
        "act",
        "reasonCode",
        "topicKey",
        "expectsUserReply",
        "referencedSourceKeys",
    }
)
_SYSTEM_IDENTITY_FIELDS = frozenset(
    {
        "agentId",
        "sessionId",
        "turnId",
        "generation",
        "bindingRevision",
        "toolCallId",
    }
)
_ACTS = frozenset({"continue_dialogue", "ask_user", "stop"})
_REASON_CODES = frozenset(
    {
        "unfinished_thought",
        "emotional_afterthought",
        "relevant_detail",
        "self_disclosure",
        "open_loop",
        "natural_question",
        "repaired_misunderstanding",
        "complete",
    }
)
_CONTINUE_REASONS = frozenset(
    {
        "unfinished_thought",
        "emotional_afterthought",
        "relevant_detail",
        "self_disclosure",
        "open_loop",
    }
)
_STOP_REASONS = frozenset({"complete", "repaired_misunderstanding"})
_SOURCE_REQUIRED_REASONS = frozenset({"self_disclosure", "open_loop"})
_STABLE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}$")


@dataclass(frozen=True)
class CompanionDialogueDecisionDraftV2:
    contractVersion: str
    agentId: str
    sessionId: str
    turnId: str
    generation: int
    bindingRevision: int
    toolCallId: str
    act: str
    reasonCode: str
    topicKey: str
    expectsUserReply: bool
    referencedSourceKeys: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["referencedSourceKeys"] = list(self.referencedSourceKeys)
        return payload


@dataclass(frozen=True)
class _ValidatedModelDecision:
    act: str
    reason_code: str
    topic_key: str
    expects_user_reply: bool
    referenced_source_keys: tuple[str, ...]

    @property
    def semantic_key(self) -> tuple[object, ...]:
        return (
            self.act,
            self.reason_code,
            self.topic_key,
            self.expects_user_reply,
            self.referenced_source_keys,
        )


def _base_result(
    *,
    status: str,
    stop_reason: str,
    draft: dict[str, Any] | None = None,
    accepted_tool_call_ids: Iterable[str] = (),
    duplicate_call_count: int = 0,
    unknown_source_keys: Iterable[str] = (),
) -> dict[str, Any]:
    return {
        "contractVersion": DIALOGUE_DECISION_CONTRACT_VERSION_V2,
        "status": status,
        "effectiveAct": draft.get("act") if draft is not None else "stop",
        "stopReason": stop_reason,
        "draft": draft,
        "acceptedToolCallIds": list(accepted_tool_call_ids),
        "duplicateCallCount": duplicate_call_count,
        "unknownSourceKeys": list(unknown_source_keys),
    }


def _normalized_system_context(
    value: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, str]:
    identity: dict[str, Any] = {}
    for field in ("agentId", "sessionId", "turnId"):
        normalized = str(value.get(field) or "").strip()
        if not normalized:
            return None, f"missing_system_{field}"
        identity[field] = normalized
    for field in ("generation", "bindingRevision"):
        raw = value.get(field)
        if isinstance(raw, bool):
            return None, f"invalid_system_{field}"
        try:
            normalized = int(raw)
        except (TypeError, ValueError):
            return None, f"invalid_system_{field}"
        if normalized < 0:
            return None, f"invalid_system_{field}"
        identity[field] = normalized
    return identity, ""


def _validate_model_decision(
    value: Mapping[str, Any],
    *,
    allowed_source_keys: frozenset[str],
) -> tuple[_ValidatedModelDecision | None, str, tuple[str, ...]]:
    supplied_fields = {str(key) for key in value}
    if supplied_fields & _SYSTEM_IDENTITY_FIELDS:
        return None, "model_supplied_system_identity", ()
    if supplied_fields - _MODEL_FIELDS:
        return None, "unexpected_model_field", ()
    if not _MODEL_FIELDS.issubset(supplied_fields):
        return None, "missing_model_field", ()

    act = str(value.get("act") or "").strip()
    if act not in _ACTS:
        return None, "invalid_act", ()
    reason_code = str(value.get("reasonCode") or "").strip()
    if reason_code not in _REASON_CODES:
        return None, "invalid_reason_code", ()
    topic_key = str(value.get("topicKey") or "").strip()
    if topic_key and not _STABLE_KEY.fullmatch(topic_key):
        return None, "invalid_topic_key", ()
    if act != "stop" and not topic_key:
        return None, "topic_key_required", ()

    expects_user_reply = value.get("expectsUserReply")
    if not isinstance(expects_user_reply, bool):
        return None, "invalid_expects_user_reply", ()
    if act == "ask_user" and not expects_user_reply:
        return None, "ask_user_requires_reply", ()
    if act == "continue_dialogue" and expects_user_reply:
        return None, "continue_dialogue_cannot_await_user", ()
    if act == "stop" and expects_user_reply:
        return None, "stop_cannot_await_user", ()

    if act == "continue_dialogue" and reason_code not in _CONTINUE_REASONS:
        return None, "reason_act_mismatch", ()
    if act == "ask_user" and reason_code != "natural_question":
        return None, "reason_act_mismatch", ()
    if act == "stop" and reason_code not in _STOP_REASONS:
        return None, "reason_act_mismatch", ()

    source_keys = value.get("referencedSourceKeys")
    if not isinstance(source_keys, (list, tuple)) or any(
        not isinstance(item, str) for item in source_keys
    ):
        return None, "invalid_source_keys", ()
    normalized_source_keys = tuple(
        sorted({item.strip() for item in source_keys if item.strip()})
    )
    unknown_source_keys = tuple(
        key for key in normalized_source_keys if key not in allowed_source_keys
    )
    if unknown_source_keys:
        return None, "unknown_source_key", unknown_source_keys
    if reason_code in _SOURCE_REQUIRED_REASONS and not normalized_source_keys:
        return None, "source_reference_required", ()

    return (
        _ValidatedModelDecision(
            act=act,
            reason_code=reason_code,
            topic_key=topic_key,
            expects_user_reply=expects_user_reply,
            referenced_source_keys=normalized_source_keys,
        ),
        "",
        (),
    )


def resolve_companion_dialogue_decision_calls_v2(
    *,
    calls: Iterable[Mapping[str, Any]],
    system_context: Mapping[str, Any],
    allowed_source_keys: Iterable[str],
    tool_calling_supported: bool = True,
) -> dict[str, Any]:
    """Validate and fold one Turn's V2 decision calls without persistence.

    Exact replays are idempotent, semantically identical calls collapse, and
    any conflict fails closed to ``stop``.  The returned draft is not a delivery
    plan and is not terminal-ready until a later runtime task binds a receipt.
    """

    if not tool_calling_supported:
        return _base_result(
            status="unavailable",
            stop_reason="decision_tool_unavailable",
        )

    identity, identity_error = _normalized_system_context(system_context)
    if identity is None:
        return _base_result(status="invalid", stop_reason=identity_error)

    normalized_calls = list(calls)
    if not normalized_calls:
        return _base_result(
            status="missing",
            stop_reason="decision_tool_not_called",
        )

    allowed = frozenset(
        str(item).strip() for item in allowed_source_keys if str(item).strip()
    )
    by_call_id: dict[str, tuple[object, ...]] = {}
    semantic_decisions: dict[
        tuple[object, ...], tuple[str, _ValidatedModelDecision]
    ] = {}
    accepted_call_ids: list[str] = []
    duplicate_count = 0

    for call in normalized_calls:
        tool_call_id = str(call.get("toolCallId") or "").strip()
        if not tool_call_id:
            return _base_result(status="invalid", stop_reason="missing_tool_call_id")
        arguments = call.get("arguments")
        if not isinstance(arguments, Mapping):
            return _base_result(status="invalid", stop_reason="invalid_arguments")
        decision, error, unknown = _validate_model_decision(
            arguments,
            allowed_source_keys=allowed,
        )
        if decision is None:
            return _base_result(
                status="invalid",
                stop_reason=error,
                unknown_source_keys=unknown,
            )

        previous_key = by_call_id.get(tool_call_id)
        if previous_key is not None:
            if previous_key != decision.semantic_key:
                return _base_result(
                    status="conflict",
                    stop_reason="conflicting_tool_call_replay",
                )
            duplicate_count += 1
            continue

        by_call_id[tool_call_id] = decision.semantic_key
        accepted_call_ids.append(tool_call_id)
        if decision.semantic_key in semantic_decisions:
            duplicate_count += 1
            continue
        semantic_decisions[decision.semantic_key] = (tool_call_id, decision)

    if len(semantic_decisions) != 1:
        return _base_result(
            status="conflict",
            stop_reason="conflicting_decisions",
            accepted_tool_call_ids=accepted_call_ids,
            duplicate_call_count=duplicate_count,
        )

    tool_call_id, decision = next(iter(semantic_decisions.values()))
    draft = CompanionDialogueDecisionDraftV2(
        contractVersion=DIALOGUE_DECISION_CONTRACT_VERSION_V2,
        **identity,
        toolCallId=tool_call_id,
        act=decision.act,
        reasonCode=decision.reason_code,
        topicKey=decision.topic_key,
        expectsUserReply=decision.expects_user_reply,
        referencedSourceKeys=decision.referenced_source_keys,
    ).to_dict()
    return _base_result(
        status="draft_valid",
        stop_reason="",
        draft=draft,
        accepted_tool_call_ids=accepted_call_ids,
        duplicate_call_count=duplicate_count,
    )


__all__ = [
    "DIALOGUE_DECISION_CONTRACT_VERSION_V2",
    "CompanionDialogueDecisionDraftV2",
    "resolve_companion_dialogue_decision_calls_v2",
]
