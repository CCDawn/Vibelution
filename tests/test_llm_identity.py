from __future__ import annotations

import hashlib

import pytest

from config.llm_credentials import canonicalize_credential_ref, resolve_credential_ref
from config.llm_identity import (
    make_model_key,
    make_model_ref,
    normalize_provider_endpoint,
    provider_identity_fingerprint,
    split_model_ref,
)


def test_provider_endpoint_normalization_preserves_semantic_path() -> None:
    assert normalize_provider_endpoint("HTTPS://Relay.Example:443/v1/") == "https://relay.example/v1"
    assert normalize_provider_endpoint("http://LOCALHOST:80/api") == "http://localhost/api"


@pytest.mark.parametrize(
    "value",
    [
        "https://user:pass@relay.example/v1",
        "https://relay.example/v1?token=secret",
        "https://relay.example/v1#fragment",
    ],
)
def test_provider_endpoint_rejects_embedded_sensitive_or_ambiguous_parts(value: str) -> None:
    with pytest.raises(ValueError, match="provider base_url"):
        normalize_provider_endpoint(value)


def test_provider_endpoint_rejects_invalid_port_without_echoing_input() -> None:
    sensitive_port = "super-secret"

    with pytest.raises(ValueError) as exc_info:
        normalize_provider_endpoint(f"https://relay.example:{sensitive_port}/v1")

    assert str(exc_info.value) == "provider base_url contains an invalid port"
    assert sensitive_port not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


def test_env_credential_reference_is_windows_case_insensitive() -> None:
    assert canonicalize_credential_ref("env:Relay_Key", windows_env=True) == "env:RELAY_KEY"
    assert canonicalize_credential_ref("none", windows_env=True) == "none"


def test_credential_resolution_does_not_expose_secret_in_repr() -> None:
    result = resolve_credential_ref(
        "env:RELAY_KEY",
        env_reader=lambda name: "super-secret" if name == "RELAY_KEY" else None,
    )
    assert result.state == "configured"
    assert result.secret == "super-secret"
    assert "super-secret" not in repr(result)


def test_provider_fingerprint_uses_endpoint_and_reference_not_secret() -> None:
    expected = hashlib.sha256(b"https://relay.example/v1\0env:RELAY_KEY").hexdigest()
    assert (
        provider_identity_fingerprint(
            "https://Relay.Example:443/v1/",
            "env:relay_key",
            auth_kind="api_key",
            windows_env=True,
        )
        == expected
    )


def test_model_key_is_stable_and_order_independent() -> None:
    assert make_model_key("gpt-5.6-luna") == "gpt-5.6-luna"
    assert make_model_key("anthropic/claude-sonnet-4.6") == "anthropic_claude-sonnet-4.6~3e041007"
    assert make_model_key(r"C:\models\Qwen.gguf") == "c_models_qwen.gguf~88f2e351"
    assert make_model_key("Model") != make_model_key("model")


def test_model_key_preserves_upstream_whitespace_identity() -> None:
    upstream_id = " model "
    expected = f"model~{hashlib.sha256(upstream_id.encode('utf-8')).hexdigest()[:8]}"

    assert make_model_key(upstream_id) == expected
    assert make_model_key(upstream_id) != make_model_key("model")


@pytest.mark.parametrize(
    ("ascii_id", "compatibility_id"),
    [
        (" model ", "\N{NO-BREAK SPACE}model\N{NO-BREAK SPACE}"),
        ("Model", "\N{FULLWIDTH LATIN CAPITAL LETTER M}odel"),
        ("model", "\N{FULLWIDTH LATIN SMALL LETTER M}odel"),
    ],
)
def test_model_key_preserves_raw_compatibility_distinctions(
    ascii_id: str,
    compatibility_id: str,
) -> None:
    compatibility_key = make_model_key(compatibility_id)

    assert compatibility_key.startswith("model~")
    assert make_model_key(ascii_id) != compatibility_key


def test_model_key_rejects_length_without_room_for_slug_and_digest() -> None:
    with pytest.raises(ValueError, match="max_length"):
        make_model_key("safe-model", max_length=9)


def test_model_ref_round_trip() -> None:
    ref = make_model_ref("pixel_relay", "gpt-5.6-luna")
    assert ref == "pixel_relay/gpt-5.6-luna"
    assert split_model_ref(ref) == ("pixel_relay", "gpt-5.6-luna")
