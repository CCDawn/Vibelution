"""Declarative per-profile LLM fallback contract.

An operator may declare ``fallback`` on a profile. The declaration must survive
the v2 projection, win over the ranking heuristic at recovery time, and fail
closed during config validation when it cannot be honoured.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from config.effective_llm_graph import EffectiveLLMGraphBuilder, LLMGraphError
from config.llm_canonical_schema import CanonicalLLMConfigError, validate_canonical_llm_payload
from config.llm_projection import project_v2_llm_for_runtime
from core.llm.routing import select_recovery_profile
from tests.helpers.isolated_config import isolated_settings_config


def make_config(**kwargs):
    kwargs.setdefault("llm.providers.default.kind", "minimax")
    kwargs.setdefault("llm.providers.default.api_key", "test-key")
    kwargs.setdefault("llm.providers.default.base_url", "https://api.minimaxi.com/v1")
    kwargs.setdefault("llm.profiles.primary.provider_id", "default")
    kwargs.setdefault("llm.profiles.primary.model", "MiniMax-M2.7")
    return isolated_settings_config(**kwargs)


# A second provider whose profile is deliberately NOT named `fallback*`, so the
# ranking heuristic rejects it for provider-retry actions.
SPARE_ROUTE_KWARGS = {
    "llm.providers.spare.kind": "local",
    "llm.providers.spare.requires_api_key": False,
    "llm.providers.spare.base_url": "http://localhost:8000/v1",
    "llm.profiles.spare_route.provider_id": "spare",
    "llm.profiles.spare_route.model": "qwen-32b-awq",
}


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


def test_declared_mapping_reports_only_declared_profiles() -> None:
    config = validate_canonical_llm_payload(_llm_section())
    assert config.declared_fallback_profile_ids() == {"primary": "spare_route"}


# --- selection --------------------------------------------------------------


def test_undeclared_route_keeps_the_ranking_heuristic() -> None:
    """Regression guard: a route the operator never declared stays ineligible."""

    config = make_config(**SPARE_ROUTE_KWARGS)
    assert config.llm.profiles["primary"].fallback == ""
    heuristic = select_recovery_profile(
        config, current_profile_id="primary", action="retry_with_backoff"
    )
    assert heuristic != "spare_route"


def test_declared_fallback_wins_over_the_ranking_heuristic() -> None:
    config = make_config(**SPARE_ROUTE_KWARGS, **{"llm.profiles.primary.fallback": "spare_route"})
    assert config.llm.profiles["primary"].fallback == "spare_route"
    assert (
        select_recovery_profile(config, current_profile_id="primary", action="retry_with_backoff")
        == "spare_route"
    )


def test_dangling_declaration_falls_through_instead_of_crashing() -> None:
    config = make_config(**SPARE_ROUTE_KWARGS, **{"llm.profiles.primary.fallback": "no_such_profile"})
    # Runtime stays available; the config write path is where this fails closed.
    assert select_recovery_profile(
        config, current_profile_id="primary", action="retry_with_backoff"
    ) != "spare_route"


def test_self_referencing_declaration_is_ignored() -> None:
    config = make_config(**SPARE_ROUTE_KWARGS, **{"llm.profiles.primary.fallback": "primary"})
    assert select_recovery_profile(
        config, current_profile_id="primary", action="retry_with_backoff"
    ) != "primary"


# --- fail-closed config validation ------------------------------------------


def test_dangling_declaration_fails_closed_during_graph_validation() -> None:
    payload = _llm_section()
    payload["profiles"]["primary"]["fallback"] = "missing_route"
    config = validate_canonical_llm_payload(payload)
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
