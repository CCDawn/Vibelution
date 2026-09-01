from __future__ import annotations

from pathlib import Path

from core.agent_plugins.virtual_human_life.dialogue_decision_v2 import (
    DIALOGUE_DECISION_CONTRACT_VERSION_V2,
    resolve_companion_dialogue_decision_calls_v2,
)
from core.agent_plugins.virtual_human_life.interaction_expression import (
    EXPRESSION_DECISION_VERSION,
    build_companion_expression_decision,
)
from core.agent_plugins.virtual_human_life.manifest import VIRTUAL_HUMAN_TOOL_NAMES
from core.agent_plugins.virtual_human_life.prompt_pack import PROMPT_PACK_FILES

SYSTEM_CONTEXT = {
    "agentId": "agent-companion",
    "sessionId": "session-companion",
    "turnId": "turn-root",
    "generation": 7,
    "bindingRevision": 3,
}


def _call(tool_call_id: str, **overrides: object) -> dict[str, object]:
    arguments: dict[str, object] = {
        "act": "continue_dialogue",
        "reasonCode": "relevant_detail",
        "topicKey": "today-song",
        "expectsUserReply": False,
        "referencedSourceKeys": ["life:event-song"],
    }
    arguments.update(overrides)
    return {"toolCallId": tool_call_id, "arguments": arguments}


def _resolve(
    *calls: dict[str, object],
    allowed_source_keys: tuple[str, ...] = ("life:event-song",),
    tool_calling_supported: bool = True,
) -> dict[str, object]:
    return resolve_companion_dialogue_decision_calls_v2(
        calls=calls,
        system_context=SYSTEM_CONTEXT,
        allowed_source_keys=allowed_source_keys,
        tool_calling_supported=tool_calling_supported,
    )


def test_valid_decision_draft_binds_only_system_owned_identity() -> None:
    result = _resolve(_call("call-1"))

    assert result["status"] == "draft_valid"
    assert result["stopReason"] == ""
    draft = result["draft"]
    assert isinstance(draft, dict)
    assert draft == {
        "contractVersion": DIALOGUE_DECISION_CONTRACT_VERSION_V2,
        **SYSTEM_CONTEXT,
        "toolCallId": "call-1",
        "act": "continue_dialogue",
        "reasonCode": "relevant_detail",
        "topicKey": "today-song",
        "expectsUserReply": False,
        "referencedSourceKeys": ["life:event-song"],
    }


def test_model_cannot_supply_system_identity_fields() -> None:
    result = _resolve(_call("call-1", agentId="other-agent"))

    assert result["status"] == "invalid"
    assert result["effectiveAct"] == "stop"
    assert result["stopReason"] == "model_supplied_system_identity"
    assert result["draft"] is None


def test_unknown_source_key_invalidates_the_draft() -> None:
    result = _resolve(
        _call(
            "call-1",
            referencedSourceKeys=["life:event-song", "memory:invented"],
        )
    )

    assert result["status"] == "invalid"
    assert result["effectiveAct"] == "stop"
    assert result["stopReason"] == "unknown_source_key"
    assert result["unknownSourceKeys"] == ["memory:invented"]


def test_same_tool_call_id_replay_is_idempotent() -> None:
    result = _resolve(_call("call-1"), _call("call-1"))

    assert result["status"] == "draft_valid"
    assert result["acceptedToolCallIds"] == ["call-1"]
    assert result["duplicateCallCount"] == 1


def test_identical_content_with_different_call_ids_collapses() -> None:
    result = _resolve(_call("call-1"), _call("call-2"))

    assert result["status"] == "draft_valid"
    assert result["acceptedToolCallIds"] == ["call-1", "call-2"]
    assert result["draft"]["toolCallId"] == "call-1"
    assert result["duplicateCallCount"] == 1


def test_conflicting_decisions_fail_closed_instead_of_last_write_winning() -> None:
    result = _resolve(
        _call("call-1"),
        _call(
            "call-2",
            act="ask_user",
            reasonCode="natural_question",
            topicKey="favorite-song",
            expectsUserReply=True,
            referencedSourceKeys=[],
        ),
    )

    assert result["status"] == "conflict"
    assert result["effectiveAct"] == "stop"
    assert result["stopReason"] == "conflicting_decisions"
    assert result["draft"] is None


def test_conflicting_replay_of_one_tool_call_id_also_fails_closed() -> None:
    result = _resolve(
        _call("call-1"),
        _call("call-1", act="stop", reasonCode="complete", topicKey=""),
    )

    assert result["status"] == "conflict"
    assert result["effectiveAct"] == "stop"
    assert result["stopReason"] == "conflicting_tool_call_replay"


def test_invalid_act_reason_and_question_semantics_stop() -> None:
    cases = (
        (_call("call-1", act="speak_forever"), "invalid_act"),
        (_call("call-1", reasonCode="because_i_want_to"), "invalid_reason_code"),
        (
            _call(
                "call-1",
                act="ask_user",
                reasonCode="natural_question",
                expectsUserReply=False,
            ),
            "ask_user_requires_reply",
        ),
        (
            _call("call-1", act="continue_dialogue", expectsUserReply=True),
            "continue_dialogue_cannot_await_user",
        ),
    )

    for call, expected_reason in cases:
        result = _resolve(call)
        assert result["status"] == "invalid"
        assert result["effectiveAct"] == "stop"
        assert result["stopReason"] == expected_reason


def test_no_tool_calling_support_degrades_to_normal_single_reply_stop() -> None:
    result = _resolve(tool_calling_supported=False)

    assert result == {
        "contractVersion": DIALOGUE_DECISION_CONTRACT_VERSION_V2,
        "status": "unavailable",
        "effectiveAct": "stop",
        "stopReason": "decision_tool_unavailable",
        "draft": None,
        "acceptedToolCallIds": [],
        "duplicateCallCount": 0,
        "unknownSourceKeys": [],
    }


def test_missing_decision_and_empty_novelty_fail_closed_without_a_fixed_count() -> None:
    missing = _resolve()
    no_new_information = _resolve(
        _call("call-1"),
        allowed_source_keys=(),
    )

    assert missing["stopReason"] == "decision_tool_not_called"
    assert no_new_information["stopReason"] == "unknown_source_key"
    assert "bubbleBudget" not in repr(no_new_information)
    assert "turnOrdinal" not in repr(no_new_information)


def test_v1_expression_remains_available_while_v2_runtime_is_registered() -> None:
    assert EXPRESSION_DECISION_VERSION == "companion_expression.v1"
    assert build_companion_expression_decision(turn_ordinal=3)["followup"] is True
    assert "virtual_human_dialogue_decision_v2_tool" in VIRTUAL_HUMAN_TOOL_NAMES
    assert "13_companion_dialogue_v2_draft.md" in PROMPT_PACK_FILES
    assert "12_companion_followup_delivery.md" not in PROMPT_PACK_FILES


def test_v2_prompt_contract_is_runtime_loaded_without_model_owned_identity() -> None:
    prompt_name = "13_companion_dialogue_v2_draft.md"
    prompt_path = (
        Path(__file__).parents[1]
        / "core"
        / "agent_plugins"
        / "virtual_human_life"
        / "prompts"
        / prompt_name
    )
    prompt = prompt_path.read_text(encoding="utf-8")
    compact_prompt = " ".join(prompt.split())

    assert prompt_name in PROMPT_PACK_FILES
    assert "Do not aim for a target number of messages" in compact_prompt
    assert "personality" in compact_prompt
    assert "relationship" in compact_prompt
    assert "mood and energy" in compact_prompt
    assert "genuinely new information" in compact_prompt
    for forbidden_identity in (
        "agentId",
        "sessionId",
        "turnId",
        "generation",
        "bindingRevision",
        "toolCallId",
    ):
        assert forbidden_identity in prompt
