"""Family-default reasoning contract for Agent model candidates.

Official DeepSeek pins declare ``model_protocol = "deepseek_reasoning"`` without
repeating the reasoning-effort triple, so the candidate projection has to merge
the protocol family defaults the same way runtime LLM profiles do. Otherwise the
Agent UI hides 思考强度 for those pins.
"""

from __future__ import annotations

from core.web.services.agent_model_candidate_service import project_reasoning_contract


def _project(pinned: dict) -> dict:
    return project_reasoning_contract(
        pinned,
        {},
        current_provider_fingerprint="fingerprint-1",
    )


def test_protocol_family_defaults_supply_reasoning_effort_for_bare_deepseek_pin():
    contract = _project(
        {
            "upstream_id": "deepseek-v4-flash",
            "model_protocol": "deepseek_reasoning",
            "reasoning_state_field": "reasoning_content",
            "defaults": {"temperature": 0.7, "max_output_tokens": 384000},
        }
    )

    assert contract["supportsReasoningEffort"] is True
    assert contract["reasoningEffortValues"] == ["low", "medium", "high"]
    assert contract["defaultReasoningEffort"] == "high"
    assert contract["reasoningAdapter"] == "reasoning_effort"
    assert contract["reasoningDefaultSource"] == "protocol_family_default"


def test_explicit_operator_values_still_win_over_family_defaults():
    contract = _project(
        {
            "upstream_id": "deepseek-v4-flash",
            "model_protocol": "deepseek_reasoning",
            "defaults": {
                "reasoning_effort_values": ["low", "xhigh"],
                "default_reasoning_effort": "xhigh",
                "reasoning_effort_adapter": "reasoning_effort",
            },
        }
    )

    assert contract["reasoningEffortValues"] == ["low", "xhigh"]
    assert contract["defaultReasoningEffort"] == "xhigh"
    assert contract["reasoningDefaultSource"] == "operator_override"


def test_plain_chat_pin_without_thinking_contract_stays_unsupported():
    contract = _project(
        {
            "upstream_id": "plain-model",
            "model_protocol": "openai_chat_tools",
            "defaults": {"temperature": 0.7},
        }
    )

    assert contract["supportsReasoningEffort"] is False
    assert contract["reasoningEffortValues"] == []
    assert contract["reasoningAdapter"] == "none"
