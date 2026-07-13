from __future__ import annotations

import pytest

from config.models import AppConfig
from config.public_config import build_effective_config, load_public_config, public_config_hash
from config.settings import ConfigLoader, normalize_public_config_dict


def _v2_config() -> dict:
    return {
        "llm": {
            "schema_version": 2,
            "providers": {
                "pixel_relay": {
                    "label": "Pixel Relay",
                    "service_class": "relay",
                    "vendor": "multi_model",
                    "driver": "openai",
                    "base_url": "https://relay.example/v1",
                    "auth_kind": "api_key",
                    "credential_ref": "env:VIBELUTION_LLM_PROVIDER_PIXEL_RELAY_API_KEY",
                    "requires_credential": True,
                    "protocols": {"default": "responses", "allowed": ["responses", "chat_completions"]},
                    "discovery": {"mode": "auto", "adapter": "openai_compatible", "cache_ttl_seconds": 3600},
                    "models": {
                        "gpt-5.6-luna": {
                            "upstream_id": "gpt-5.6-luna",
                            "label": "GPT-5.6 Luna",
                            "enabled": True,
                            "defaults": {"max_output_tokens": 32000, "timeout": 120},
                        }
                    },
                }
            },
            "profiles": {
                "primary": {
                    "model_ref": "pixel_relay/gpt-5.6-luna",
                    "overrides": {"temperature": 0.4},
                }
            },
        }
    }


def _v2_toml() -> str:
    return """
[llm]
schema_version = 2

[llm.providers.pixel_relay]
label = "Pixel Relay"
service_class = "relay"
vendor = "multi_model"
driver = "openai"
base_url = "https://relay.example/v1"
auth_kind = "api_key"
credential_ref = "env:VIBELUTION_LLM_PROVIDER_PIXEL_RELAY_API_KEY"
requires_credential = true

[llm.providers.pixel_relay.protocols]
default = "responses"
allowed = ["responses", "chat_completions"]

[llm.providers.pixel_relay.models."gpt-5.6-luna"]
upstream_id = "gpt-5.6-luna"
label = "GPT-5.6 Luna"

[llm.providers.pixel_relay.models."gpt-5.6-luna".defaults]
max_output_tokens = 32000
timeout = 120

[llm.profiles.primary]
model_ref = "pixel_relay/gpt-5.6-luna"

[llm.profiles.primary.overrides]
temperature = 0.4
""".strip()


def test_v2_projection_keeps_one_provider_and_flattens_only_runtime_models() -> None:
    normalized = normalize_public_config_dict(_v2_config())
    assert set(normalized["llm"]["providers"]) == {"pixel_relay"}
    assert set(normalized["llm"]["model_library"]) == {"pixel_relay/gpt-5.6-luna"}
    assert normalized["llm"]["model_library"]["pixel_relay/gpt-5.6-luna"]["model"] == "gpt-5.6-luna"
    assert normalized["llm"]["profiles"]["primary"]["provider_id"] == "pixel_relay"
    assert normalized["llm"]["profiles"]["primary"]["temperature"] == 0.4
    assert normalized["llm"]["profiles"]["primary"]["max_output_tokens"] == 32000


def test_v2_effective_config_resolves_provider_credential_without_inline_copies(monkeypatch) -> None:
    monkeypatch.setenv("VIBELUTION_LLM_PROVIDER_PIXEL_RELAY_API_KEY", "secret")
    effective = build_effective_config(_v2_config())
    profile = effective.llm.get_profile("primary")
    provider = effective.llm.get_provider(profile.provider_id)
    assert effective.llm.schema_version == 2
    assert profile.model_ref == "pixel_relay/gpt-5.6-luna"
    assert profile.model == "gpt-5.6-luna"
    assert provider.provider_id == "pixel_relay"
    assert provider.resolve_api_key() == "secret"
    assert not any(provider_id.startswith("inline_") for provider_id in effective.llm.providers)


def test_v1_normalization_remains_read_only_and_compatible() -> None:
    legacy = {
        "llm": {
            "model_library": {
                "relay_model": {
                    "provider": {
                        "kind": "relay",
                        "base_url": "https://relay.example/v1",
                        "api_key_env": "RELAY_KEY",
                    },
                    "model": "gpt-5.6-luna",
                }
            },
            "profiles": {"primary": {"model_ref": "relay_model"}},
        }
    }
    normalized = normalize_public_config_dict(legacy)
    assert legacy["llm"]["model_library"]["relay_model"]["provider"]["kind"] == "relay"
    assert normalized["llm"]["profiles"]["primary"]["model"] == "gpt-5.6-luna"


def test_v2_projection_uses_cycle_safe_runtime_alias_resolver() -> None:
    chained = _v2_config()
    chained["llm"]["model_aliases"] = {
        "primary-model": "latest-model",
        "latest-model": "pixel_relay/gpt-5.6-luna",
    }
    chained["llm"]["profiles"]["primary"]["model_ref"] = "primary-model"

    normalized = normalize_public_config_dict(chained)

    assert normalized["llm"]["profiles"]["primary"]["model_ref"] == "pixel_relay/gpt-5.6-luna"

    cyclic = _v2_config()
    cyclic["llm"]["model_aliases"] = {"first": "second", "second": "first"}
    cyclic["llm"]["profiles"]["primary"]["model_ref"] = "first"

    try:
        normalize_public_config_dict(cyclic)
    except ValueError as exc:
        assert str(exc) == "cyclic model alias: first"
    else:  # pragma: no cover - assertion guard
        raise AssertionError("cyclic aliases must be rejected")


@pytest.mark.parametrize(
    ("scope", "field"),
    [
        ("provider", "api_key"),
        ("provider", "api_key_env"),
        ("model", "api_key"),
        ("model", "api_key_env"),
        ("model", "credential_ref"),
        ("defaults", "api_key"),
        ("defaults", "api_key_env"),
        ("defaults", "credential_ref"),
        ("profile", "api_key"),
        ("profile", "api_key_env"),
        ("profile", "credential_ref"),
        ("overrides", "api_key"),
        ("overrides", "api_key_env"),
        ("overrides", "credential_ref"),
    ],
)
def test_v2_rejects_credential_ownership_outside_provider_credential_ref(scope: str, field: str) -> None:
    public_config = _v2_config()
    provider = public_config["llm"]["providers"]["pixel_relay"]
    model = provider["models"]["gpt-5.6-luna"]
    profile = public_config["llm"]["profiles"]["primary"]
    owner = {
        "provider": provider,
        "model": model,
        "defaults": model["defaults"],
        "profile": profile,
        "overrides": profile["overrides"],
    }[scope]
    owner[field] = "secret-must-not-appear"

    with pytest.raises(ValueError) as exc_info:
        build_effective_config(public_config)

    message = str(exc_info.value)
    assert message == f"schema v2 credential ownership violation: {scope}.{field}"
    assert "secret-must-not-appear" not in message


def test_v2_public_config_boundary_rejects_inline_secret_without_echo() -> None:
    public_config = _v2_config()
    public_config["llm"]["providers"]["pixel_relay"]["api_key"] = "public-secret-must-not-appear"

    with pytest.raises(ValueError) as exc_info:
        public_config_hash(public_config)

    message = str(exc_info.value)
    assert message == "schema v2 credential ownership violation: provider.api_key"
    assert "public-secret-must-not-appear" not in message


def test_v2_public_config_hash_rejects_input_model_library_without_echo() -> None:
    public_config = _v2_config()
    public_config["llm"]["model_library"] = {
        "secret-model-key": {"model": "legacy", "api_key": "hash-secret-must-not-appear"}
    }

    with pytest.raises(ValueError) as exc_info:
        public_config_hash(public_config)

    message = str(exc_info.value)
    assert message == "llm.model_library is not allowed in schema v2 input"
    assert "secret-model-key" not in message
    assert "hash-secret-must-not-appear" not in message


def test_v2_load_public_config_rejects_input_model_library_without_echo(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[llm]
schema_version = 2

[llm.model_library.secret_model_key]
model = "legacy"
api_key = "load-secret-must-not-appear"
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as exc_info:
        load_public_config(config_path)

    message = str(exc_info.value)
    assert message == "llm.model_library is not allowed in schema v2 input"
    assert "secret_model_key" not in message
    assert "load-secret-must-not-appear" not in message


def test_v2_public_hash_rejects_nested_model_credential_without_echo() -> None:
    public_config = _v2_config()
    model = public_config["llm"]["providers"]["pixel_relay"]["models"]["gpt-5.6-luna"]
    model["compatibility"] = {"nested": {"api_key": "nested-hash-secret-must-not-appear"}}

    with pytest.raises(ValueError) as exc_info:
        public_config_hash(public_config)

    assert str(exc_info.value) == "schema v2 credential ownership violation: model.api_key"
    assert "nested-hash-secret-must-not-appear" not in str(exc_info.value)
    assert "nested-hash-secret-must-not-appear" not in repr(exc_info.value)


def test_v2_public_hash_rejects_nested_llm_credential_without_echo() -> None:
    public_config = _v2_config()
    public_config["llm"]["discovery"] = {
        "enabled": True,
        "metadata": {"api_key_env": "NESTED_ROOT_SECRET_MUST_NOT_APPEAR"},
    }

    with pytest.raises(ValueError) as exc_info:
        public_config_hash(public_config)

    assert str(exc_info.value) == "schema v2 credential ownership violation: llm.api_key_env"
    assert "NESTED_ROOT_SECRET_MUST_NOT_APPEAR" not in str(exc_info.value)
    assert "NESTED_ROOT_SECRET_MUST_NOT_APPEAR" not in repr(exc_info.value)


def test_v2_effective_config_rejects_nested_override_credential_without_echo() -> None:
    public_config = _v2_config()
    public_config["llm"]["profiles"]["primary"]["overrides"]["compat"] = {
        "nested": {"credential_ref": "env:NESTED_SECRET_MUST_NOT_APPEAR"}
    }

    with pytest.raises(ValueError) as exc_info:
        build_effective_config(public_config)

    assert str(exc_info.value) == "schema v2 credential ownership violation: overrides.credential_ref"
    assert "NESTED_SECRET_MUST_NOT_APPEAR" not in str(exc_info.value)
    assert "NESTED_SECRET_MUST_NOT_APPEAR" not in repr(exc_info.value)


def test_v2_load_public_config_rejects_nested_model_credential_without_echo(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        _v2_toml()
        + """

[llm.providers.pixel_relay.models."gpt-5.6-luna".compatibility.nested]
api_key = "nested-load-secret-must-not-appear"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as exc_info:
        load_public_config(config_path)

    assert str(exc_info.value) == "schema v2 credential ownership violation: model.api_key"
    assert "nested-load-secret-must-not-appear" not in str(exc_info.value)
    assert "nested-load-secret-must-not-appear" not in repr(exc_info.value)


def test_v1_public_config_hash_still_accepts_legacy_model_library() -> None:
    legacy = {
        "llm": {
            "model_library": {
                "relay_model": {
                    "provider": {"kind": "relay", "base_url": "https://relay.example/v1"},
                    "model": "gpt-5.6-luna",
                }
            },
            "profiles": {"primary": {"model_ref": "relay_model"}},
        }
    }

    assert len(public_config_hash(legacy)) == 64


def test_v2_config_loader_keeps_credential_lazy_and_secret_out_of_effective_config(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(_v2_toml(), encoding="utf-8")
    monkeypatch.setenv("VIBELUTION_LLM_PROVIDER_PIXEL_RELAY_API_KEY", "lazy-secret-must-not-materialize")

    effective = ConfigLoader(str(config_path)).load()
    provider = effective.llm.get_provider("pixel_relay")

    assert effective.llm.schema_version == 2
    assert set(effective.llm.providers) == {"pixel_relay"}
    assert provider.api_key == ""
    assert provider.credential_ref == "env:VIBELUTION_LLM_PROVIDER_PIXEL_RELAY_API_KEY"
    assert provider.resolve_api_key() == "lazy-secret-must-not-materialize"
    assert "lazy-secret-must-not-materialize" not in repr(effective)


@pytest.mark.parametrize(
    "env_name",
    [
        "OPENAI_API_KEY",
        "AGENT_LLM__PROFILES__PRIMARY__PROVIDER__API_KEY",
    ],
)
def test_v2_config_loader_ignores_legacy_provider_credential_env(env_name: str, tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(_v2_toml(), encoding="utf-8")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AGENT_LLM__PROFILES__PRIMARY__PROVIDER__API_KEY", raising=False)
    monkeypatch.setenv(env_name, "legacy-env-secret-must-not-appear")

    effective = ConfigLoader(str(config_path)).load()
    profile = effective.llm.get_profile("primary")
    provider = effective.llm.get_provider("pixel_relay")

    assert set(effective.llm.providers) == {"pixel_relay"}
    assert profile.provider_id == "pixel_relay"
    assert provider.api_key == ""
    assert "legacy-env-secret-must-not-appear" not in repr(effective)


def test_v2_config_loader_keeps_noncredential_profile_env_override(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(_v2_toml(), encoding="utf-8")
    monkeypatch.setenv("AGENT_LLM__PROFILES__PRIMARY__TEMPERATURE", "0.25")

    effective = ConfigLoader(str(config_path)).load()

    assert effective.llm.get_profile("primary").temperature == 0.25
    assert effective.llm.get_profile("primary").provider_id == "pixel_relay"


@pytest.mark.parametrize(
    ("env_name", "field", "value"),
    [
        (
            "AGENT_LLM__PROVIDERS__PIXEL_RELAY__BASE_URL",
            "base_url",
            "https://override-relay.example/v1",
        ),
        ("AGENT_LLM__PROVIDERS__PIXEL_RELAY__LABEL", "label", "Overridden Relay"),
    ],
)
def test_v2_config_loader_applies_named_provider_noncredential_env_increment(
    env_name: str,
    field: str,
    value: str,
    tmp_path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(_v2_toml(), encoding="utf-8")
    monkeypatch.setenv(env_name, value)

    effective = ConfigLoader(str(config_path)).load()
    provider = effective.llm.get_provider("pixel_relay")

    assert getattr(provider, field) == value
    assert set(effective.llm.providers) == {"pixel_relay"}
    assert effective.llm.get_profile("primary").provider_id == "pixel_relay"


def test_v2_config_loader_rejects_env_schema_downgrade_without_secret_echo(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(_v2_toml(), encoding="utf-8")
    monkeypatch.setenv("AGENT_LLM__SCHEMA_VERSION", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "downgrade-secret-must-not-appear")

    with pytest.raises(ValueError) as exc_info:
        ConfigLoader(str(config_path)).load()

    message = str(exc_info.value)
    assert message == "schema_version cannot be changed by incremental config"
    assert "downgrade-secret-must-not-appear" not in message


def test_v2_config_loader_treats_equal_env_schema_as_noop_and_keeps_credentials_lazy(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(_v2_toml(), encoding="utf-8")
    monkeypatch.setenv("AGENT_LLM__SCHEMA_VERSION", "2")
    monkeypatch.setenv("OPENAI_API_KEY", "canonical-secret-must-stay-lazy")

    effective = ConfigLoader(str(config_path)).load()

    assert effective.llm.schema_version == 2
    assert set(effective.llm.providers) == {"pixel_relay"}
    assert effective.llm.get_profile("primary").provider_id == "pixel_relay"
    assert effective.llm.get_provider("pixel_relay").api_key == ""
    assert "canonical-secret-must-stay-lazy" not in repr(effective)


def test_v2_config_loader_locks_schema_for_kwargs_and_strips_equal_declaration(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(_v2_toml(), encoding="utf-8")

    with pytest.raises(ValueError, match="^schema_version cannot be changed by incremental config$"):
        ConfigLoader(str(config_path)).load(**{"llm.schema_version": 1})

    effective = ConfigLoader(str(config_path)).load(
        **{
            "llm.schema_version": 2,
            "llm.providers.pixel_relay.label": "Schema Locked Relay",
        }
    )
    assert effective.llm.schema_version == 2
    assert effective.llm.get_provider("pixel_relay").label == "Schema Locked Relay"


@pytest.mark.parametrize(
    ("path", "field", "value"),
    [
        ("llm.providers.pixel_relay.base_url", "base_url", "https://kwargs-relay.example/v1"),
        ("llm.providers.pixel_relay.label", "label", "Kwargs Relay"),
    ],
)
def test_v2_config_loader_applies_named_provider_noncredential_kwargs(
    path: str,
    field: str,
    value: str,
    tmp_path,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(_v2_toml(), encoding="utf-8")

    effective = ConfigLoader(str(config_path)).load(**{path: value})

    assert getattr(effective.llm.get_provider("pixel_relay"), field) == value
    assert set(effective.llm.providers) == {"pixel_relay"}
    assert effective.llm.get_profile("primary").provider_id == "pixel_relay"


def test_v2_config_loader_applies_profile_scalar_kwargs(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(_v2_toml(), encoding="utf-8")

    effective = ConfigLoader(str(config_path)).load(**{"llm.profiles.primary.temperature": 0.15})

    assert effective.llm.get_profile("primary").temperature == 0.15
    assert effective.llm.get_profile("primary").provider_id == "pixel_relay"


@pytest.mark.parametrize(
    ("path", "expected_error"),
    [
        (
            "llm.providers.pixel_relay.api_key",
            "schema v2 credential fields are not allowed in incremental config",
        ),
        (
            "llm.profiles.primary.provider.base_url",
            "schema v2 inline providers are not allowed in incremental config",
        ),
        ("llm.providers.unknown.base_url", "schema v2 incremental config cannot add providers"),
        ("llm.profiles.unknown.temperature", "schema v2 incremental config cannot add profiles"),
    ],
)
def test_v2_config_loader_rejects_unsafe_kwargs_increment(path: str, expected_error: str, tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(_v2_toml(), encoding="utf-8")

    with pytest.raises(ValueError) as exc_info:
        ConfigLoader(str(config_path)).load(**{path: "kwargs-secret-must-not-appear"})

    message = str(exc_info.value)
    assert message == expected_error
    assert "kwargs-secret-must-not-appear" not in message


@pytest.mark.parametrize("credential_field", ["api_key", "api_key_env", "credential_ref"])
def test_v2_config_loader_rejects_credentials_nested_in_list_valued_kwargs(
    credential_field: str,
    tmp_path,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(_v2_toml(), encoding="utf-8")
    sentinel = "list-secret-must-not-appear"

    with pytest.raises(ValueError) as exc_info:
        effective = ConfigLoader(str(config_path)).load(
            **{
                "llm.providers.pixel_relay.models": {
                    "gpt-5.6-luna": {"compatibility": {"payload": [{credential_field: sentinel}]}}
                }
            }
        )

    assert str(exc_info.value) == "schema v2 credential fields are not allowed in incremental config"
    assert sentinel not in str(exc_info.value)
    assert sentinel not in repr(exc_info.value)
    assert "effective" not in locals()


def test_v2_config_loader_allows_noncredential_list_metadata_in_kwargs(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(_v2_toml(), encoding="utf-8")

    effective = ConfigLoader(str(config_path)).load(
        **{
            "llm.providers.pixel_relay.models": {
                "gpt-5.6-luna": {"compatibility": {"payload": [{"format": "json"}]}}
            }
        }
    )

    compatibility = effective.llm.get_provider("pixel_relay").models["gpt-5.6-luna"].compatibility
    assert compatibility["payload"] == [{"format": "json"}]


@pytest.mark.parametrize(
    "override_path",
    [
        "provider.base_url",
        "provider_id",
        "model_ref",
        "model",
        "unknown_runtime_field",
    ],
)
def test_v2_config_loader_rejects_identity_or_unknown_nested_profile_override(override_path: str, tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(_v2_toml(), encoding="utf-8")
    top_level_field = override_path.split(".", 1)[0]

    with pytest.raises(ValueError) as exc_info:
        ConfigLoader(str(config_path)).load(
            **{f"llm.profiles.primary.overrides.{override_path}": "override-must-not-apply"}
        )

    assert str(exc_info.value) == f"unsupported schema v2 runtime field: overrides.{top_level_field}"


def test_v2_config_loader_applies_allowlisted_nested_profile_override(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(_v2_toml(), encoding="utf-8")

    effective = ConfigLoader(str(config_path)).load(
        **{"llm.profiles.primary.overrides.temperature": 0.12}
    )

    assert effective.llm.get_profile("primary").temperature == 0.12
    assert effective.llm.get_profile("primary").provider_id == "pixel_relay"


def test_v1_config_loader_keeps_profile_scalar_kwargs_behavior(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[llm.providers.default]
kind = "relay"
base_url = "https://relay.example/v1"

[llm.profiles.primary]
provider_id = "default"
model = "gpt-5.6-luna"
""".strip(),
        encoding="utf-8",
    )

    effective = ConfigLoader(str(config_path)).load(**{"llm.profiles.primary.temperature": 0.2})

    assert effective.llm.schema_version == 1
    assert effective.llm.get_profile("primary").temperature == 0.2


def test_v1_config_loader_still_materializes_legacy_provider_api_key(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[llm.providers.default]
kind = "relay"
api_key_env = "LEGACY_RELAY_KEY"
base_url = "https://relay.example/v1"

[llm.profiles.primary]
provider_id = "default"
model = "gpt-5.6-luna"
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("LEGACY_RELAY_KEY", "legacy-materialized-secret")

    effective = ConfigLoader(str(config_path)).load()

    assert effective.llm.schema_version == 1
    assert effective.llm.get_provider(role="primary").api_key == "legacy-materialized-secret"


@pytest.mark.parametrize("scope", ["defaults", "overrides"])
def test_v2_rejects_runtime_fields_outside_explicit_allowlist(scope: str) -> None:
    public_config = _v2_config()
    provider = public_config["llm"]["providers"]["pixel_relay"]
    target = (
        provider["models"]["gpt-5.6-luna"]["defaults"]
        if scope == "defaults"
        else public_config["llm"]["profiles"]["primary"]["overrides"]
    )
    target["unapproved_runtime_flag"] = True

    with pytest.raises(ValueError) as exc_info:
        normalize_public_config_dict(public_config)

    assert str(exc_info.value) == f"unsupported schema v2 runtime field: {scope}.unapproved_runtime_flag"


def test_v2_projection_preserves_verified_reasoning_contract_model_defaults() -> None:
    public_config = _v2_config()
    defaults = public_config["llm"]["providers"]["pixel_relay"]["models"][
        "gpt-5.6-luna"
    ]["defaults"]
    defaults.update(
        {
            "reasoning_effort_values": ["low", "high"],
            "default_reasoning_effort": "high",
            "reasoning_effort_adapter": "reasoning_object",
            "reasoning_effort_map": {"low": "low", "high": "high"},
        }
    )

    normalized = normalize_public_config_dict(public_config)

    model = normalized["llm"]["model_library"]["pixel_relay/gpt-5.6-luna"]
    profile = normalized["llm"]["profiles"]["primary"]
    for projected in (model, profile):
        assert projected["reasoning_effort_values"] == ["low", "high"]
        assert projected["default_reasoning_effort"] == "high"
        assert projected["reasoning_effort_adapter"] == "reasoning_object"
        assert projected["reasoning_effort_map"] == {"low": "low", "high": "high"}


@pytest.mark.parametrize("missing_section", ["providers", "profiles"])
def test_v2_empty_provider_or_profile_set_fails_closed_without_legacy_defaults(missing_section: str) -> None:
    public_config = _v2_config()
    public_config["llm"][missing_section] = {}

    with pytest.raises(ValueError, match=f"^llm.{missing_section} must not be empty in schema v2$"):
        normalize_public_config_dict(public_config)

    typed_input = {"llm": {"schema_version": 2, "providers": {}, "profiles": {}}}
    with pytest.raises(ValueError) as typed_exc_info:
        AppConfig.model_validate(typed_input)
    assert "llm.providers must not be empty in schema v2" in str(typed_exc_info.value)


@pytest.mark.parametrize(
    "upstream_id",
    [
        "  model with spaces  ",
        "模型/版本 β",
        "../models/private\\checkpoint",
    ],
)
def test_v2_projection_preserves_nonempty_upstream_id_exactly(upstream_id: str) -> None:
    public_config = _v2_config()
    public_config["llm"]["providers"]["pixel_relay"]["models"]["gpt-5.6-luna"]["upstream_id"] = upstream_id

    normalized = normalize_public_config_dict(public_config)

    assert normalized["llm"]["model_library"]["pixel_relay/gpt-5.6-luna"]["model"] == upstream_id
    assert normalized["llm"]["profiles"]["primary"]["model"] == upstream_id


def test_v2_projection_rejects_whitespace_only_upstream_id() -> None:
    public_config = _v2_config()
    public_config["llm"]["providers"]["pixel_relay"]["models"]["gpt-5.6-luna"]["upstream_id"] = " \t\n "

    with pytest.raises(ValueError, match="^pinned model pixel_relay/gpt-5.6-luna requires upstream_id$"):
        normalize_public_config_dict(public_config)
