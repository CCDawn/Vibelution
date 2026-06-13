#!/usr/bin/env python3
"""
配置结构统一性测试
"""

import tomllib
from pathlib import Path

import pytest

from config import AppConfig, ConfigLoader, Settings, normalize_public_config_dict, reload_config
from config import workbench as workbench_config


SAMPLE_PUBLIC_CONFIG = """
[runtime]
profile = "safe_remote"

[workbench]
backend_port = 8000
frontend_port = 5173
window_mode = "fullscreen"
window_size = "auto"

[llm.discovery]
timeout = 12

[llm.model_library.relay_openai_gpt_5_5]
model = "gpt-5.5"
label = "Relay GPT 5.5"
transport = "chat_completions"
contract = "tool_chat"
temperature = 0.7
max_output_tokens = 128000
timeout = 120
connect_timeout = 20
streaming = true
tool_calling_mode = "auto"
discovery_enabled = true

[llm.model_library.relay_openai_gpt_5_5.provider]
kind = "openai"
api_key_env = "OPENAI_API_KEY"
base_url = "https://api.openai.com/v1"
compat_mode = "openai"
requires_api_key = true
context_window = 1050000

[llm.profiles.primary]
model_ref = "relay_openai_gpt_5_5"

[llm.profiles.primary.overrides]
temperature = 0.2

[prompt]
default_components = ["CONFIG_AWARENESS", "LANGUAGE_AWARENESS", "MEMORY", "RUNTIME_LOG_INDEX"]

[[prompt.sections]]
id = "unit"
path = "workspace/prompts/UNIT.md"
enabled = true

[[prompt.sections]]
id = "spec"
path = "workspace/prompts/SPEC.md"
enabled = true

[pet.gene]
inherit_from_model = true
""".strip()


def _load_toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _write_sample_public_config(tmp_path: Path, filename: str = "config.toml") -> Path:
    config_file = tmp_path / filename
    config_file.write_text(SAMPLE_PUBLIC_CONFIG + "\n", encoding="utf-8")
    return config_file


def _assert_same_shape(left, right, path="root"):
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return

    assert type(left) is type(right), f"{path}: {type(left).__name__} != {type(right).__name__}"

    if isinstance(left, dict):
        assert set(left.keys()) == set(right.keys()), (
            f"{path}: keys mismatch\nleft={sorted(left.keys())}\nright={sorted(right.keys())}"
        )
        for key in sorted(left.keys()):
            _assert_same_shape(left[key], right[key], f"{path}.{key}")
        return

    if isinstance(left, list):
        if not left or not right:
            return
        first_left = left[0]
        first_right = right[0]
        if isinstance(first_left, dict) and isinstance(first_right, dict):
            assert set(first_left.keys()) == set(first_right.keys()), (
                f"{path}[0]: dict item keys mismatch\n"
                f"left={sorted(first_left.keys())}\nright={sorted(first_right.keys())}"
            )


def _assert_model_shape_is_exposed(expected, actual, path="root"):
    if isinstance(expected, dict):
        assert isinstance(actual, dict), f"{path}: expected dict"
        for key, value in expected.items():
            assert key in actual, f"{path}: missing key {key}"
            _assert_model_shape_is_exposed(value, actual[key], f"{path}.{key}")
        return

    if isinstance(expected, list):
        assert isinstance(actual, list), f"{path}: expected list"
        return


def test_external_config_samples_have_same_public_shape(tmp_path):
    main_config = _write_sample_public_config(tmp_path, "config.toml")
    example_config = _write_sample_public_config(tmp_path, "config.example.toml")
    main = _load_toml(main_config)
    example = _load_toml(example_config)

    _assert_same_shape(main, example)


def test_sample_config_exposes_all_public_model_blocks(tmp_path):
    raw = _load_toml(_write_sample_public_config(tmp_path))
    assert "providers" not in raw["llm"]
    assert "profiles" in raw["llm"]
    assert "discovery" in raw["llm"]
    assert "model_library" in raw["llm"]
    assert "primary" in raw["llm"]["profiles"]
    assert "model_ref" in raw["llm"]["profiles"]["primary"]
    assert "overrides" in raw["llm"]["profiles"]["primary"]
    assert "compression" not in raw["llm"]["profiles"]
    assert "subagent_explorer" not in raw["llm"]["profiles"]
    assert "relay_openai_gpt_5_5" in raw["llm"]["model_library"]
    assert "provider" in raw["llm"]["model_library"]["relay_openai_gpt_5_5"]


def test_config_loader_normalizes_nested_public_blocks(tmp_path):
    config_file = _write_sample_public_config(tmp_path)
    raw = _load_toml(config_file)
    normalized = normalize_public_config_dict(raw)
    config = AppConfig.model_validate(normalized)

    primary_profile = raw["llm"]["profiles"]["primary"]
    primary_model_ref = str(primary_profile.get("model_ref") or "").strip()
    expected_primary_model = raw["llm"]["model_library"][primary_model_ref]["model"]
    assert config.llm.get_profile("primary").model == expected_primary_model
    assert config.llm.get_profile(role="compression").profile_id == "primary"
    assert config.llm.discovery.timeout == raw["llm"]["discovery"]["timeout"]
    assert config.pet_gene.inherit_from_model == raw["pet"]["gene"]["inherit_from_model"]
    assert len(config.prompt.sections) == len(raw["prompt"]["sections"])
    assert config.workbench.backend_port == raw["workbench"]["backend_port"]
    assert config.workbench.frontend_port == raw["workbench"]["frontend_port"]
    assert config.workbench.window_mode == raw["workbench"]["window_mode"]
    assert config.workbench.window_size == raw["workbench"]["window_size"]


def test_config_loader_canonicalizes_inline_profile_model_env(tmp_path, monkeypatch):
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """
[llm.profiles.primary]
model = "unit-runtime-model"
api_key_env = "LEGACY_PROFILE_ENV"
transport = "chat_completions"
contract = "tool_chat"
strict_compatibility = false
temperature = 0.7
max_output_tokens = 128000
timeout = 120
connect_timeout = 20
streaming = true
tool_calling_mode = "auto"
discovery_enabled = true
supports_image_input = true

[llm.profiles.primary.provider]
kind = "openai_compatible"
api_key_env = "UNIT_PROVIDER_KEY"
base_url = "https://unit-test.example.com/v1"
compat_mode = "openai"
requires_api_key = true
context_window = 1000000
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.delenv("LEGACY_PROFILE_ENV", raising=False)
    monkeypatch.delenv("UNIT_PROVIDER_KEY", raising=False)
    monkeypatch.delenv("VIBELUTION_ENABLE_USER_ENV_FALLBACK", raising=False)

    config = ConfigLoader(str(config_file)).load()
    profile = config.llm.get_profile("primary")
    model_id, entry = config.llm.get_model_library_entry_for_profile(profile)

    assert model_id
    assert str(model_id).startswith("generated_openai_compatible_unit_runtime_model_")
    assert isinstance(entry, dict)
    assert profile.api_key_env == entry["api_key_env"]
    assert entry["api_key_env"].startswith("VIBELUTION_LLM_MODEL_GENERATED_OPENAI_COMPATIBLE_UNIT_")
    assert config.get_api_key_for_profile(profile_id="primary") is None

    monkeypatch.setenv(entry["api_key_env"], "runtime-model-key")

    assert config.get_api_key_for_profile(profile_id="primary") == "runtime-model-key"


def test_evolution_default_allowlist_includes_safe_modify_probe_file():
    config = AppConfig()

    assert config.evolution.allowed_target_dirs == [
        "workspace/prompts/",
        "tests/harness_safe_modify_probe.py",
    ]


def test_workbench_ports_have_defaults_and_validate_range():
    config = AppConfig()

    assert config.workbench.backend_port == 8000
    assert config.workbench.frontend_port == 5173
    assert config.workbench.window_mode == "fullscreen"

    with pytest.raises(ValueError):
        AppConfig.model_validate({"workbench": {"backend_port": 0, "frontend_port": 5173}})
    with pytest.raises(ValueError):
        AppConfig.model_validate({"workbench": {"backend_port": 8000, "frontend_port": 70000}})


def test_workbench_window_mode_normalizes_and_validates():
    config = AppConfig.model_validate({"workbench": {"window_mode": "FULLSCREEN"}})

    assert config.workbench.window_mode == "fullscreen"

    with pytest.raises(ValueError):
        AppConfig.model_validate({"workbench": {"window_mode": "borderless"}})


def test_workbench_port_helpers_read_saved_config_without_settings_cache(monkeypatch, tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text("[workbench]\nbackend_port = 9101\nfrontend_port = 6200\n", encoding="utf-8")
    monkeypatch.setattr(workbench_config, "CONFIG_PATH", config_path)
    monkeypatch.delenv("VIBELUTION_PORT", raising=False)
    monkeypatch.delenv("VIBELUTION_FRONTEND_PORT", raising=False)
    monkeypatch.delenv("AGENT_WORKBENCH_BACKEND_PORT", raising=False)
    monkeypatch.delenv("AGENT_WORKBENCH_FRONTEND_PORT", raising=False)

    assert workbench_config.configured_backend_port() == 9101
    assert workbench_config.configured_frontend_port() == 6200
    assert workbench_config.backend_url() == "http://127.0.0.1:9101"

    config_path.write_text("[workbench]\nbackend_port = 9201\nfrontend_port = 6300\n", encoding="utf-8")

    assert workbench_config.configured_backend_port() == 9201
    assert workbench_config.configured_frontend_port() == 6300


def test_workbench_port_helpers_keep_environment_overrides(monkeypatch, tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text("[workbench]\nbackend_port = 9101\nfrontend_port = 6200\n", encoding="utf-8")
    monkeypatch.setattr(workbench_config, "CONFIG_PATH", config_path)
    monkeypatch.setenv("VIBELUTION_PORT", "9301")
    monkeypatch.setenv("VIBELUTION_FRONTEND_PORT", "6400")

    assert workbench_config.configured_backend_port() == 9301
    assert workbench_config.configured_frontend_port() == 6400
    assert workbench_config.configured_backend_port(include_env=False) == 9101
    assert workbench_config.configured_frontend_port(include_env=False) == 6200


def test_workbench_port_helpers_ignore_invalid_agent_alias_overrides(monkeypatch, tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text("[workbench]\nbackend_port = 9101\nfrontend_port = 6200\n", encoding="utf-8")
    monkeypatch.setattr(workbench_config, "CONFIG_PATH", config_path)
    monkeypatch.delenv("VIBELUTION_PORT", raising=False)
    monkeypatch.delenv("VIBELUTION_FRONTEND_PORT", raising=False)
    monkeypatch.setenv("AGENT_WORKBENCH_BACKEND_PORT", "9301oops")
    monkeypatch.setenv("AGENT_WORKBENCH_FRONTEND_PORT", "6400oops")

    assert workbench_config.configured_backend_port() == 9101
    assert workbench_config.configured_frontend_port() == 6200


def test_workbench_frontend_port_can_be_overridden_from_environment(monkeypatch, tmp_path):
    config_file = _write_sample_public_config(tmp_path)
    monkeypatch.setenv("VIBELUTION_FRONTEND_PORT", "6400")

    config = ConfigLoader(str(config_file)).load()

    assert config.workbench.frontend_port == 6400


def test_reload_config_refreshes_cached_settings_config(tmp_path):
    first_config = tmp_path / "first.toml"
    second_config = tmp_path / "second.toml"
    first_config.write_text(
        "[llm.profiles.primary]\nmodel = \"first-model\"\n",
        encoding="utf-8",
    )
    second_config.write_text(
        "[llm.profiles.primary]\nmodel = \"second-model\"\n",
        encoding="utf-8",
    )

    try:
        assert reload_config(str(first_config)).llm.get_profile("primary").model == "first-model"
        assert reload_config(str(second_config)).llm.get_profile("primary").model == "second-model"
    finally:
        reload_config(str(first_config))


def test_config_loader_accepts_agent_workbench_port_aliases(monkeypatch, tmp_path):
    config_file = tmp_path / "config.toml"
    config_file.write_text("[workbench]\nbackend_port = 9101\nfrontend_port = 6200\n", encoding="utf-8")
    monkeypatch.delenv("VIBELUTION_PORT", raising=False)
    monkeypatch.delenv("VIBELUTION_FRONTEND_PORT", raising=False)
    monkeypatch.delenv("VIBELUTION_WORKBENCH_WINDOW_MODE", raising=False)
    monkeypatch.setenv("AGENT_WORKBENCH_BACKEND_PORT", "9301")
    monkeypatch.setenv("AGENT_WORKBENCH_FRONTEND_PORT", "6400")
    monkeypatch.setenv("AGENT_WORKBENCH_WINDOW_MODE", "fullscreen")

    config = ConfigLoader(str(config_file)).load()

    assert config.workbench.backend_port == 9301
    assert config.workbench.frontend_port == 6400
    assert config.workbench.window_mode == "fullscreen"


def test_config_loader_prefers_vibelution_workbench_port_over_agent_alias(monkeypatch, tmp_path):
    config_file = tmp_path / "config.toml"
    config_file.write_text("[workbench]\nbackend_port = 9101\nfrontend_port = 6200\n", encoding="utf-8")
    monkeypatch.setenv("AGENT_WORKBENCH_BACKEND_PORT", "9301")
    monkeypatch.setenv("AGENT_WORKBENCH_FRONTEND_PORT", "6400")
    monkeypatch.setenv("AGENT_WORKBENCH_WINDOW_MODE", "fullscreen")
    monkeypatch.setenv("VIBELUTION_PORT", "9401")
    monkeypatch.setenv("VIBELUTION_FRONTEND_PORT", "6500")
    monkeypatch.setenv("VIBELUTION_WORKBENCH_WINDOW_MODE", "windowed")

    config = ConfigLoader(str(config_file)).load()

    assert config.workbench.backend_port == 9401
    assert config.workbench.frontend_port == 6500
    assert config.workbench.window_mode == "windowed"


def test_config_loader_ignores_invalid_agent_workbench_port_aliases(monkeypatch, tmp_path):
    config_file = tmp_path / "config.toml"
    config_file.write_text("[workbench]\nbackend_port = 9101\nfrontend_port = 6200\n", encoding="utf-8")
    monkeypatch.delenv("VIBELUTION_PORT", raising=False)
    monkeypatch.delenv("VIBELUTION_FRONTEND_PORT", raising=False)
    monkeypatch.setenv("AGENT_WORKBENCH_BACKEND_PORT", "9301oops")
    monkeypatch.setenv("AGENT_WORKBENCH_FRONTEND_PORT", "6400oops")

    config = ConfigLoader(str(config_file)).load()

    assert config.workbench.backend_port == 9101
    assert config.workbench.frontend_port == 6200


def test_pet_system_config_reads_unified_settings(monkeypatch):
    from core.pet_system.pet_system import PetSystemConfig

    app_config = AppConfig.model_validate(
        {
            "pet": {"name": "设置虾", "save_interval": 7},
            "pet_gene": {"context_window_factor": 0.123},
            "pet_heart": {"active_rate": 3.5},
            "pet_dream": {"dream_duration": 9},
            "pet_sound": {"volume": 0.25},
        }
    )
    monkeypatch.setattr("config.settings.get_config", lambda: app_config)

    config = PetSystemConfig()

    assert config.pet.name == "设置虾"
    assert config.pet.save_interval == 7
    assert config.gene.context_window_factor == 0.123
    assert config.heart.active_rate == 3.5
    assert config.dream.dream_duration == 9
    assert config.sound.volume == 0.25


def test_pet_system_applies_configured_pet_name(monkeypatch, tmp_path):
    from core.pet_system import pet_system as pet_system_module

    app_config = AppConfig.model_validate({"pet": {"name": "设置虾"}})
    monkeypatch.setattr("config.settings.get_config", lambda: app_config)
    monkeypatch.chdir(tmp_path)
    pet_system_module.reset_pet_system()

    try:
        pet = pet_system_module.get_pet_system()
        assert pet.data.attributes.name == "设置虾"
    finally:
        pet_system_module.reset_pet_system()


def test_external_sample_configs_load_through_entrypoints(tmp_path):
    main_config = _write_sample_public_config(tmp_path, "config.toml")
    example_config = _write_sample_public_config(tmp_path, "config.example.toml")
    main_loader = ConfigLoader(str(main_config)).load()
    example_loader = ConfigLoader(str(example_config)).load()
    settings_config = Settings(config_path=str(main_config)).config
    main_primary_provider_kind = main_loader.llm.get_provider(main_loader.llm.get_profile("primary").provider_id).kind
    settings_primary_provider_kind = settings_config.llm.get_provider(
        settings_config.llm.get_profile("primary").provider_id
    ).kind

    assert main_loader.prompt.default_components == settings_config.prompt.default_components
    assert "CONFIG_AWARENESS" in main_loader.prompt.default_components
    assert "LANGUAGE_AWARENESS" in main_loader.prompt.default_components
    assert "MEMORY" in main_loader.prompt.default_components
    assert "RUNTIME_LOG_INDEX" in main_loader.prompt.default_components
    assert len(main_loader.prompt.sections) == len(settings_config.prompt.sections) == 2
    assert example_loader.tools.restart_enabled is True
    assert example_loader.workbench.backend_port == 8000
    assert example_loader.workbench.frontend_port == 5173
    assert example_loader.workbench.window_mode == "fullscreen"
    assert example_loader.workbench.window_size == "auto"
    assert main_loader.pet_heart.enabled is True
    assert settings_primary_provider_kind == main_primary_provider_kind
