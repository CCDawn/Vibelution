from __future__ import annotations

import pytest

from config.llm_canonical_schema import (
    CanonicalLLMConfigError,
    validate_canonical_llm_payload,
)


def _payload() -> dict:
    return {
        "schema_version": 2,
        "providers": {
            "relay": {
                "provider_id": "relay",
                "kind": "openai",
                "service_class": "relay",
                "driver": "openai",
                "base_url": "https://relay.example/v1",
                "credential_ref": "env:OPENAI_API_KEY",
                "protocols": {
                    "default": "responses",
                    "allowed": ["responses", "chat_completions"],
                },
                "models": {
                    "gpt": {
                        "upstream_id": "gpt-test",
                        "wire_protocol": "responses",
                        "interaction_contract": "responses_agent",
                        "model_protocol": "openai_responses",
                    }
                },
            }
        },
        "profiles": {
            "primary": {
                "profile_id": "primary",
                "provider_id": "relay",
                "model_ref": "relay/gpt",
                "model": "gpt-test",
                "transport": "responses",
                "contract": "responses_agent",
            }
        },
        "model_aliases": {"primary-model": "relay/gpt"},
    }


@pytest.mark.parametrize(
    ("mutate", "path"),
    [
        (lambda p: p["providers"]["relay"].__setitem__("protcols", {}), "providers.relay.protcols"),
        (
            lambda p: p["providers"]["relay"]["models"]["gpt"].__setitem__(
                "wire_protcol", "responses"
            ),
            "providers.relay.models.gpt.wire_protcol",
        ),
        (
            lambda p: p["profiles"]["primary"].__setitem__("unknown_runtime_field", True),
            "profiles.primary.unknown_runtime_field",
        ),
    ],
)
def test_strict_canonical_schema_rejects_unknown_fields_with_exact_path(mutate, path) -> None:
    payload = _payload()
    mutate(payload)
    with pytest.raises(CanonicalLLMConfigError) as exc:
        validate_canonical_llm_payload(payload)
    assert path in {issue.path for issue in exc.value.issues}


def test_strict_canonical_schema_rejects_inline_secret() -> None:
    payload = _payload()
    payload["providers"]["relay"]["api_key"] = "sk-live-secret"
    with pytest.raises(CanonicalLLMConfigError) as exc:
        validate_canonical_llm_payload(payload)
    assert "inline_secret_forbidden" in {issue.code for issue in exc.value.issues}


@pytest.mark.parametrize("value", ["chat_completion", "a2a", "mcp", "ag_ui"])
def test_strict_canonical_schema_rejects_cross_layer_wire_protocol(value: str) -> None:
    payload = _payload()
    payload["providers"]["relay"]["protocols"]["default"] = value
    payload["providers"]["relay"]["protocols"]["allowed"] = [value]
    with pytest.raises(CanonicalLLMConfigError) as exc:
        validate_canonical_llm_payload(payload)
    assert "unknown_wire_protocol" in {issue.code for issue in exc.value.issues}


def test_interaction_contract_cannot_be_used_as_model_protocol() -> None:
    payload = _payload()
    payload["providers"]["relay"]["models"]["gpt"]["model_protocol"] = "tool_chat"
    with pytest.raises(CanonicalLLMConfigError) as exc:
        validate_canonical_llm_payload(payload)
    assert "interaction_contract_in_model_protocol" in {
        issue.code for issue in exc.value.issues
    }


def test_valid_payload_preserves_explicit_three_layer_protocol_fields() -> None:
    config = validate_canonical_llm_payload(_payload())
    model = config.providers["relay"].models["gpt"]
    assert model.interaction_contract == "responses_agent"
    assert model.model_protocol == "openai_responses"
    assert model.wire_protocol == "responses"
