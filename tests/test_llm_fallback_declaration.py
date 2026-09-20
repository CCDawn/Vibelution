"""Declarative per-profile LLM fallback contract.

An operator may declare ``fallback`` on a profile. The declaration must survive
the v2 projection and fail closed during config validation when it cannot be
honoured. Runtime switching itself is covered by tests/test_turn_llm_adapter.py:
the adapter switches once, only for recoverable gateway-level categories after
the primary route's retry budget is exhausted, and never chains.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from config.effective_llm_graph import EffectiveLLMGraphBuilder, LLMGraphError
from config.llm_canonical_schema import CanonicalLLMConfigError, validate_canonical_llm_payload
from config.llm_projection import project_v2_llm_for_runtime


def _llm_section() -> dict[str, Any]:
    """The canonical validator and the graph builder take the llm section itself."""
    return {
        "schema_version": 2,
        "providers": {
            "relay_main": {
                "label": "Relay",
                "service_class": "relay",
                "vendor": "custom",
                "driver": "openai",
                "base_url": "https://relay.example/v1",
                "credential_ref": "env:RELAY_KEY",
                "protocols": {"default": "chat_completions", "allowed": ["chat_completions"]},
                "models": {
                    "glm": {
                        "upstream_id": "glm-5.3-flash",
                        "wire_protocol": "chat_completions",
                        "interaction_contract": "tool_chat",
                    }
                },
            },
            "official_deepseek": {
                "label": "DeepSeek",
                "service_class": "official_api",
                "vendor": "deepseek",
                "driver": "openai",
                "base_url": "https://api.deepseek.com",
                "credential_ref": "env:DEEPSEEK_API_KEY",
                "protocols": {"default": "chat_completions", "allowed": ["chat_completions"]},
                "models": {
                    "v4": {
                        "upstream_id": "deepseek-v4-flash",
                        "wire_protocol": "chat_completions",
                        "interaction_contract": "reasoning_chat",
                        "model_protocol": "deepseek_reasoning",
                    }
                },
            },
        },
        "profiles": {
            "primary": {"model_ref": "relay_main/glm", "fallback": "spare_route"},
            "spare_route": {"model_ref": "official_deepseek/v4"},
        },
    }


def _v2_payload() -> dict[str, Any]:
    """The projection step consumes the whole public config."""
    return {"llm": _llm_section()}


# --- schema -----------------------------------------------------------------


def test_canonical_schema_accepts_the_fallback_field() -> None:
    config = validate_canonical_llm_payload(_llm_section())
    assert config.profiles["primary"].fallback == "spare_route"
    assert config.profiles["spare_route"].fallback == ""


def test_unknown_profile_field_still_fails_closed() -> None:
    payload = _llm_section()
    payload["profiles"]["primary"]["fallbak"] = "spare_route"
    with pytest.raises(CanonicalLLMConfigError) as exc:
        validate_canonical_llm_payload(payload)
    assert "unknown_field" in {issue.code for issue in exc.value.issues}


def test_declared_mapping_reports_only_declared_profiles() -> None:
    config = validate_canonical_llm_payload(_llm_section())
    assert config.declared_fallback_profile_ids() == {"primary": "spare_route"}


# --- projection -------------------------------------------------------------


def test_projection_carries_the_declaration_into_runtime_profiles() -> None:
    projected = project_v2_llm_for_runtime(_v2_payload())
    assert projected["llm"]["profiles"]["primary"]["fallback"] == "spare_route"
    assert projected["llm"]["profiles"]["spare_route"]["fallback"] == ""


def test_projection_carries_the_declaration_for_unconfigured_profiles() -> None:
    payload = _v2_payload()
    payload["llm"]["profiles"]["placeholder"] = {
        "model_ref": "__unconfigured__",
        "fallback": "spare_route",
    }
    projected = project_v2_llm_for_runtime(payload)
    assert projected["llm"]["profiles"]["placeholder"]["fallback"] == "spare_route"


# --- fail-closed config validation ------------------------------------------


def test_dangling_declaration_fails_closed_during_graph_validation() -> None:
    payload = _llm_section()
    payload["profiles"]["primary"]["fallback"] = "missing_route"
    # Reference integrity now fails closed at canonical validation time (typed
    # LLMConfig.ensure_defaults), before the graph builder ever runs.
    with pytest.raises(CanonicalLLMConfigError):
        validate_canonical_llm_payload(payload)

    # The graph builder keeps its own independent fallback_profile_not_found
    # defence: inject the dangling reference past validation and confirm it is
    # still rejected there.
    config = validate_canonical_llm_payload(_llm_section())
    config.profiles["primary"].fallback = "missing_route"
    with pytest.raises(LLMGraphError) as exc:
        EffectiveLLMGraphBuilder().build(
            config, fallback_profile_ids=config.declared_fallback_profile_ids()
        )
    assert "fallback_profile_not_found" in {issue.code for issue in exc.value.issues}


def test_declaration_matching_its_own_route_fails_closed() -> None:
    payload = _llm_section()
    payload["profiles"]["twin"] = copy.deepcopy(payload["profiles"]["spare_route"])
    payload["profiles"]["spare_route"]["fallback"] = "twin"
    config = validate_canonical_llm_payload(payload)
    with pytest.raises(LLMGraphError) as exc:
        EffectiveLLMGraphBuilder().build(
            config, fallback_profile_ids=config.declared_fallback_profile_ids()
        )
    assert "fallback_same_effective_identity" in {issue.code for issue in exc.value.issues}


def test_declaration_that_differs_is_accepted() -> None:
    config = validate_canonical_llm_payload(_llm_section())
    graph = EffectiveLLMGraphBuilder().build(
        config, fallback_profile_ids=config.declared_fallback_profile_ids()
    )
    assert graph.route_for_profile("primary").provider_id == "relay_main"
