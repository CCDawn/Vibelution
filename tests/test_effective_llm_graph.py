from __future__ import annotations

from config.llm_canonical_schema import validate_canonical_llm_payload
from config.effective_llm_graph import EffectiveLLMGraphBuilder, LLMGraphError


def _config(*, service_class: str = "relay", endpoint: str = "https://relay.example/v1"):
    auth_kind = "none" if service_class == "local_runtime" else "api_key"
    credential_ref = "none" if auth_kind == "none" else "env:OPENAI_API_KEY"
    return validate_canonical_llm_payload(
        {
            "schema_version": 2,
            "providers": {
                "p": {
                    "provider_id": "p",
                    "kind": "openai",
                    "service_class": service_class,
                    "driver": "openai",
                    "auth_kind": auth_kind,
                    "requires_credential": auth_kind != "none",
                    "credential_ref": credential_ref,
                    "base_url": endpoint,
                    "protocols": {
                        "default": "chat_completions",
                        "allowed": ["chat_completions", "responses", "anthropic_messages"],
                    },
                    "models": {
                        "m": {
                            "upstream_id": "same-name",
                            "wire_protocol": "chat_completions",
                            "interaction_contract": "tool_chat",
                            "model_protocol": "openai_chat_tools",
                        }
                    },
                }
            },
            "profiles": {
                "primary": {
                    "profile_id": "primary",
                    "provider_id": "p",
                    "model_ref": "p/m",
                    "model": "same-name",
                    "transport": "chat_completions",
                    "contract": "tool_chat",
                }
            },
            "model_aliases": {"main": "p/m"},
        }
    )


def test_graph_is_deterministic_and_contains_no_secret_value() -> None:
    config = _config()
    config.providers["p"].api_key = "must-not-appear"
    first = EffectiveLLMGraphBuilder().build(config)
    second = EffectiveLLMGraphBuilder().build(config)

    assert first.fingerprint == second.fingerprint
    assert first.routes[0].route_fingerprint == second.routes[0].route_fingerprint
    assert "must-not-appear" not in repr(first)


def test_official_relay_and_local_routes_with_same_model_have_distinct_identity() -> None:
    relay = EffectiveLLMGraphBuilder().build(_config(service_class="relay"))
    local = EffectiveLLMGraphBuilder().build(
        _config(service_class="local_runtime", endpoint="http://127.0.0.1:8000/v1")
    )
    official = EffectiveLLMGraphBuilder().build(_config(service_class="official_api"))

    assert len(
        {
            relay.routes[0].route_fingerprint,
            local.routes[0].route_fingerprint,
            official.routes[0].route_fingerprint,
        }
    ) == 3


def test_graph_reports_dangling_and_cyclic_aliases_as_typed_issues() -> None:
    config = _config()
    config.model_aliases = {"dangling": "p/missing", "a": "b", "b": "a"}

    try:
        EffectiveLLMGraphBuilder().build(config)
    except LLMGraphError as exc:
        codes = {issue.code for issue in exc.issues}
    else:
        raise AssertionError("invalid aliases must fail closed")
    assert {"dangling_model_alias", "cyclic_model_alias"}.issubset(codes)


def test_fallback_must_not_resolve_to_same_effective_route() -> None:
    config = _config()
    config.profiles["fallback"] = config.profiles["primary"].model_copy(
        update={"profile_id": "fallback"}
    )
    try:
        EffectiveLLMGraphBuilder().build(
            config, fallback_profile_ids={"primary": "fallback"}
        )
    except LLMGraphError as exc:
        assert "fallback_same_effective_identity" in {issue.code for issue in exc.issues}
    else:
        raise AssertionError("same effective fallback must fail closed")


def test_wire_adapter_backend_and_endpoint_change_route_fingerprint() -> None:
    config = _config()
    base = EffectiveLLMGraphBuilder().build(config).routes[0]
    config.providers["p"].models["m"].wire_protocol = "responses"
    changed_wire = EffectiveLLMGraphBuilder().build(config).routes[0]
    config.providers["p"].base_url = "https://other-relay.example/v1"
    changed_endpoint = EffectiveLLMGraphBuilder().build(config).routes[0]

    assert base.route_fingerprint != changed_wire.route_fingerprint
    assert changed_wire.route_fingerprint != changed_endpoint.route_fingerprint
    assert base.backend_identity == "litellm_chat_completions"
    assert changed_wire.backend_identity == "litellm_responses"
