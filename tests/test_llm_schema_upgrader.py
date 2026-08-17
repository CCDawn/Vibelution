from __future__ import annotations

from pathlib import Path

import pytest

from config.llm_schema_upgrader import LLMSchemaUpgradeError, upgrade_persisted_llm_schema_if_needed
from config.public_config import build_effective_config, load_public_config
from config.settings import ConfigLoader, normalize_public_config_dict
from config.toml_writer import dumps_public_config

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "config" / "llm_schema_v1_inline.toml"


def _v1_role_bindings_toml() -> str:
    return """
[llm]
schema_version = 1

[llm.model_library.relay_text]
model = "gpt-5.6-luna"
label = "GPT-5.6 Luna"
transport = "responses"
contract = "tool_chat"
timeout = 120

[llm.model_library.relay_text.provider]
kind = "relay"
base_url = "https://relay.example/v1"
api_key_env = "VIBELUTION_LLM_MODEL_RELAY_TEXT_API_KEY"
compat_mode = "openai"
requires_api_key = true

[llm.profiles.primary]
model_ref = "relay_text"

[llm.role_bindings]
coding = "primary"
""".strip()


def test_upgrade_v1_fixture_is_atomic_and_idempotent(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    original = FIXTURE.read_text(encoding="utf-8")
    config_path.write_text(original, encoding="utf-8")

    first = upgrade_persisted_llm_schema_if_needed(config_path)
    assert first["status"] == "upgraded"
    persisted = load_public_config(config_path)
    assert persisted["llm"]["schema_version"] == 2
    assert "role_bindings" not in persisted["llm"]
    assert persisted["llm"]["profiles"]["primary"]["model_ref"].endswith("/gpt-5.6-luna")
    effective = build_effective_config(persisted)
    assert effective.llm.schema_version == 2
    assert effective.llm.get_profile("primary").model == "gpt-5.6-luna"
    after_first = config_path.read_bytes()

    second = upgrade_persisted_llm_schema_if_needed(config_path)
    assert second["status"] == "already_canonical"
    assert config_path.read_bytes() == after_first


def test_upgrade_folds_role_bindings_and_removes_runtime_shim(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(_v1_role_bindings_toml() + "\n", encoding="utf-8")

    result = upgrade_persisted_llm_schema_if_needed(config_path)
    assert result["status"] == "upgraded"
    persisted = load_public_config(config_path)
    assert "role_bindings" not in persisted["llm"]
    assert "coding" in persisted["llm"]["profiles"]
    assert persisted["llm"]["profiles"]["coding"]["model_ref"] == persisted["llm"]["profiles"]["primary"]["model_ref"]


def test_corrupt_toml_fails_closed_without_overwrite(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    original = b"this is not [valid toml"
    config_path.write_bytes(original)

    with pytest.raises(LLMSchemaUpgradeError, match="corrupt_toml"):
        upgrade_persisted_llm_schema_if_needed(config_path)

    assert config_path.read_bytes() == original


def test_unupgradeable_v1_fails_closed_without_overwrite(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    original = b"[llm]\nschema_version = 1\n"
    config_path.write_bytes(original)

    with pytest.raises(LLMSchemaUpgradeError):
        upgrade_persisted_llm_schema_if_needed(config_path)

    assert config_path.read_bytes() == original


def test_validation_failure_restores_original_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.toml"
    original = FIXTURE.read_bytes()
    config_path.write_bytes(original)

    from config import llm_schema_upgrader as upgrader

    calls = {"count": 0}
    real_effective = upgrader.build_effective_config

    def _fail_after_write(public_config):
        calls["count"] += 1
        if calls["count"] == 1:
            return real_effective(public_config)
        raise RuntimeError("post-write-validation-failed")

    monkeypatch.setattr(upgrader, "build_effective_config", _fail_after_write)

    with pytest.raises(LLMSchemaUpgradeError, match="write_failed_restored"):
        upgrade_persisted_llm_schema_if_needed(config_path)

    assert config_path.read_bytes() == original


def test_runtime_normalize_rejects_v1_and_role_bindings() -> None:
    v1 = {
        "llm": {
            "schema_version": 1,
            "model_library": {"relay_text": {"model": "gpt-5.6-luna"}},
            "profiles": {"primary": {"model_ref": "relay_text"}},
        }
    }
    with pytest.raises(ValueError, match="schema v2"):
        normalize_public_config_dict(v1)

    v2_bindings = {
        "llm": {
            "schema_version": 2,
            "role_bindings": {"coding": "primary"},
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
                    "protocols": {"default": "responses", "allowed": ["responses"]},
                    "models": {"gpt-5.6-luna": {"upstream_id": "gpt-5.6-luna", "enabled": True}},
                }
            },
            "profiles": {"primary": {"model_ref": "pixel_relay/gpt-5.6-luna"}},
        }
    }
    with pytest.raises(ValueError, match="role_bindings"):
        normalize_public_config_dict(v2_bindings)


def test_config_loader_upgrades_v1_file_before_runtime_load(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

    effective = ConfigLoader(str(config_path)).load()
    persisted = load_public_config(config_path)

    assert persisted["llm"]["schema_version"] == 2
    assert effective.llm.schema_version == 2
    assert effective.llm.get_profile("primary").model == "gpt-5.6-luna"
    assert "role_bindings" not in dumps_public_config(persisted)
    assert "api_key =" not in config_path.read_text(encoding="utf-8")
    assert "schema_version = 1" in FIXTURE.read_text(encoding="utf-8")
