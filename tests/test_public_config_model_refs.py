#!/usr/bin/env python3
"""
LLM 模型模板引用结构测试
"""

from pathlib import Path

from config import ConfigLoader
from config.public_config import UNCONFIGURED_MODEL_REF, build_effective_config, delete_llm_model, list_llm_model_options, load_public_config
from core.web.services.config_service import _decorate_model_options


PROJECT_ROOT = Path(__file__).parent.parent


def _openai_gpt_5_5_library_entry() -> dict:
    return {
        "model": "gpt-5.5",
        "label": "OpenAI GPT-5.5",
        "api_key_env": "VIBELUTION_LLM_OPENAI_GPT_5_5_API_KEY",
        "transport": "chat_completions",
        "contract": "tool_chat",
        "temperature": 0.7,
        "max_output_tokens": 128000,
        "timeout": 120,
        "connect_timeout": 20,
        "streaming": True,
        "tool_calling_mode": "auto",
        "discovery_enabled": True,
        "provider": {
            "kind": "openai",
            "api_key_env": "OPENAI_API_KEY",
            "base_url": "https://api.openai.com/v1",
            "compat_mode": "openai",
            "requires_api_key": True,
            "context_window": 1050000,
        },
    }


def _anthropic_claude_opus_4_7_library_entry() -> dict:
    return {
        "model": "claude-opus-4-7",
        "label": "Anthropic Claude Opus 4.7",
        "api_key_env": "VIBELUTION_LLM_ANTHROPIC_CLAUDE_OPUS_4_7_API_KEY",
        "transport": "chat_completions",
        "contract": "tool_chat",
        "max_output_tokens": 8192,
        "timeout": 120,
        "connect_timeout": 20,
        "streaming": True,
        "tool_calling_mode": "auto",
        "discovery_enabled": True,
        "prompt_cache": {"mode": "explicit_cache_control"},
        "thinking_type": "adaptive",
        "thinking_display": "summarized",
        "provider": {
            "kind": "anthropic",
            "api_key_env": "ANTHROPIC_API_KEY",
            "base_url": "https://api.anthropic.com",
            "compat_mode": "native",
            "requires_api_key": True,
            "context_window": 200000,
        },
    }


def test_build_effective_config_resolves_model_ref_and_overrides():
    public_config = load_public_config()
    public_config["llm"].setdefault("model_library", {})["openai_gpt_5_5"] = _openai_gpt_5_5_library_entry()
    public_config["llm"]["profiles"]["primary"] = {
        "model_ref": "openai_gpt_5_5",
        "overrides": {
            "temperature": 0.25,
            "max_output_tokens": 64000,
        },
    }

    effective = build_effective_config(public_config)
    profile = effective.llm.get_profile("primary")
    provider = effective.llm.get_provider(profile.provider_id)

    assert provider.kind == "openai"
    assert provider.base_url == "https://api.openai.com/v1"
    assert profile.model == "gpt-5.5"
    assert profile.temperature == 0.25
    assert profile.max_output_tokens == 64000
    assert profile.timeout == 120


def test_claude_opus_4_7_model_ref_template_omits_temperature():
    public_config = load_public_config()
    public_config["llm"].setdefault("model_library", {})[
        "anthropic_claude_opus_4_7"
    ] = _anthropic_claude_opus_4_7_library_entry()
    public_config["llm"]["profiles"]["primary"] = {
        "model_ref": "anthropic_claude_opus_4_7",
        "overrides": {},
    }
    claude = public_config["llm"]["model_library"]["anthropic_claude_opus_4_7"]
    effective = build_effective_config(public_config)
    profile = effective.llm.get_profile("primary")

    assert claude["provider"]["kind"] == "anthropic"
    assert claude["model"] == "claude-opus-4-7"
    assert "temperature" not in claude
    assert claude["prompt_cache"] == {"mode": "explicit_cache_control"}
    assert profile.model == "claude-opus-4-7"
    assert profile.prompt_cache.mode == "explicit_cache_control"


def test_current_prompt_cache_modes_follow_model_library_config():
    public_config = load_public_config()
    public_config["llm"]["profiles"]["primary"] = {
        "model_ref": "relay_openai_gpt_5_5",
        "overrides": {},
    }

    effective = build_effective_config(public_config)
    profile = effective.llm.get_profile("primary")

    assert profile.model == "gpt-5.5"
    assert profile.prompt_cache.mode == "automatic"


def test_prompt_cache_override_can_change_referenced_model_mode():
    public_config = load_public_config()
    public_config["llm"].setdefault("model_library", {})["cache_probe_model"] = _openai_gpt_5_5_library_entry()
    public_config["llm"]["model_library"]["cache_probe_model"]["prompt_cache"] = {"mode": "automatic"}
    public_config["llm"]["profiles"]["primary"] = {
        "model_ref": "cache_probe_model",
        "overrides": {"prompt_cache": {"mode": "unsupported"}},
    }

    effective = build_effective_config(public_config)
    profile = effective.llm.get_profile("primary")

    assert profile.model == "gpt-5.5"
    assert profile.prompt_cache.mode == "unsupported"


def test_list_llm_model_options_exposes_protocol_route_fields():
    public_config = load_public_config()
    entry = _openai_gpt_5_5_library_entry()
    entry["provider"]["api"] = "openai-responses"
    entry["protocol"] = "relay_responses"
    entry["compat"] = {"streamUsageOptions": True}
    public_config["llm"].setdefault("model_library", {})["protocol_probe_model"] = entry

    options = list_llm_model_options(public_config)
    option = next(item for item in options if item["model_id"] == "protocol_probe_model")

    assert option["provider_api"] == "openai-responses"
    assert option["protocol"] == "relay_responses"
    assert option["compat"] == {"streamUsageOptions": True}
    assert option["details"]["protocol"] == "relay_responses"
    assert option["details"]["compat"] == {"streamUsageOptions": True}


def test_decorated_model_options_expose_resolved_protocol_route():
    public_config = load_public_config()
    entry = _openai_gpt_5_5_library_entry()
    entry["provider"]["kind"] = "llamacpp"
    entry["provider"]["api"] = "local-openai-compatible"
    entry["provider"]["base_url"] = "http://127.0.0.1:8081/v1"
    entry["model"] = "qwen3-test"
    entry["thinking_type"] = "adaptive"
    public_config["llm"].setdefault("model_library", {})["local_qwen_probe"] = entry

    options = _decorate_model_options(public_config, draft_meta=None)
    option = next(item for item in options if item["model_id"] == "local_qwen_probe")

    assert option["provider_api"] == "local-openai-compatible"
    assert option["resolved_provider_api"] == "local-openai-compatible"
    assert option["resolved_protocol"] == "llamacpp_qwen_thinking"
    assert option["protocol_source"] == "inferred"
    assert option["resolved_compat"]["allowAssistantPrefill"] is False


def test_config_loader_accepts_model_ref_toml(tmp_path):
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """
[llm.model_library.openai_gpt_5_5]
model = "gpt-5.5"
label = "OpenAI GPT-5.5"
api_key_env = "VIBELUTION_LLM_OPENAI_GPT_5_5_API_KEY"
transport = "chat_completions"
contract = "tool_chat"
temperature = 0.7
max_output_tokens = 128000
timeout = 120
connect_timeout = 20
streaming = true
tool_calling_mode = "auto"
discovery_enabled = true

[llm.model_library.openai_gpt_5_5.provider]
kind = "openai"
api_key_env = "OPENAI_API_KEY"
base_url = "https://api.openai.com/v1"
compat_mode = "openai"
requires_api_key = true
context_window = 1050000

[llm.profiles.primary]
model_ref = "openai_gpt_5_5"

[llm.profiles.primary.overrides]
temperature = 0.2
max_output_tokens = 32000
""".strip(),
        encoding="utf-8",
    )

    config = ConfigLoader(str(config_file)).load()
    profile = config.llm.get_profile("primary")
    provider = config.llm.get_provider(profile.provider_id)

    assert provider.kind == "openai"
    assert profile.model == "gpt-5.5"
    assert profile.temperature == 0.2
    assert profile.max_output_tokens == 32000


def test_delete_llm_model_marks_model_ref_profiles_unconfigured():
    public_config = load_public_config()
    public_config["llm"].setdefault("model_library", {})["openai_gpt_5_5"] = _openai_gpt_5_5_library_entry()
    public_config["llm"]["profiles"]["primary"] = {
        "model_ref": "openai_gpt_5_5",
        "overrides": {"temperature": 0.3},
    }
    public_config["llm"]["profiles"]["mental_model"] = {
        "model_ref": "openai_gpt_5_5",
        "overrides": {"temperature": 0.4},
    }

    deleted = delete_llm_model(public_config, "openai_gpt_5_5")

    assert deleted["llm"]["profiles"]["primary"]["model_ref"] == UNCONFIGURED_MODEL_REF
    assert deleted["llm"]["profiles"]["primary"]["overrides"] == {}
    assert deleted["llm"]["profiles"]["mental_model"]["model_ref"] == UNCONFIGURED_MODEL_REF
    assert deleted["llm"]["profiles"]["mental_model"]["overrides"] == {}
