#!/usr/bin/env python3
"""
LLM 模型模板引用结构测试
"""

from pathlib import Path

from config import ConfigLoader
from config.public_config import LLM_MODEL_PRESETS, build_effective_config, delete_llm_model, list_llm_model_options, load_public_config
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


def test_openai_compatible_model_without_prompt_cache_defaults_to_automatic():
    public_config = load_public_config()
    public_config["llm"].setdefault("model_library", {})["gpt_5_5_gpt_5_5"] = {
        "model": "gpt-5.5",
        "label": "gpt-5.5-share",
        "transport": "chat_completions",
        "contract": "tool_chat",
        "strict_compatibility": False,
        "temperature": 0.7,
        "max_output_tokens": 128000,
        "timeout": 120,
        "connect_timeout": 20,
        "streaming": True,
        "tool_calling_mode": "auto",
        "discovery_enabled": True,
        "provider": {
            "kind": "openai_compatible",
            "api_key_env": "OPENAI_API_KEY",
            "base_url": "https://share-api.com/v1",
            "compat_mode": "openai",
            "requires_api_key": True,
            "context_window": 1050000,
        },
    }
    public_config["llm"]["profiles"]["primary"] = {
        "model_ref": "gpt_5_5_gpt_5_5",
        "overrides": {},
    }

    effective = build_effective_config(public_config)
    profile = effective.llm.get_profile("primary")

    assert public_config["llm"]["model_library"]["gpt_5_5_gpt_5_5"].get("prompt_cache") is None
    assert profile.model == "gpt-5.5"
    assert profile.prompt_cache.mode == "automatic"


def test_deepseek_model_without_prompt_cache_stays_disabled_by_default():
    public_config = load_public_config()
    public_config["llm"].setdefault("model_library", {})["deepseek_prompt_cache_probe"] = {
        "model": "deepseek-v4-pro",
        "label": "DeepSeek V4 Pro",
        "transport": "chat_completions",
        "contract": "reasoning_chat",
        "reasoning_state_field": "reasoning_content",
        "provider": {
            "kind": "deepseek",
            "api_key_env": "DEEPSEEK_API_KEY",
            "base_url": "https://api.deepseek.com",
            "compat_mode": "openai",
            "requires_api_key": True,
            "context_window": 1000000,
        },
    }
    public_config["llm"]["profiles"]["primary"] = {
        "model_ref": "deepseek_prompt_cache_probe",
        "overrides": {},
    }

    effective = build_effective_config(public_config)
    profile = effective.llm.get_profile("primary")

    assert profile.model == "deepseek-v4-pro"
    assert profile.prompt_cache.mode == "disabled"


def test_local_qwen_without_prompt_cache_support_stays_disabled_by_default():
    public_config = load_public_config()
    public_config["llm"].setdefault("model_library", {})["local_qwen_no_cache_probe"] = {
        "model": "Qwen3-32B-AWQ",
        "label": "Local Qwen without cache support",
        "transport": "chat_completions",
        "contract": "basic_chat",
        "protocol": "qwen_thinking_no_prefill",
        "tool_calling_mode": "disabled",
        "provider": {
            "kind": "local",
            "api": "openai-completions",
            "api_key_env": "",
            "base_url": "http://192.168.20.63:8000/v1",
            "compat_mode": "openai",
            "requires_api_key": False,
            "context_window": 128000,
        },
    }
    public_config["llm"]["profiles"]["primary"] = {
        "model_ref": "local_qwen_no_cache_probe",
        "overrides": {},
    }

    effective = build_effective_config(public_config)
    profile = effective.llm.get_profile("primary")

    assert profile.model == "Qwen3-32B-AWQ"
    assert profile.prompt_cache.mode == "disabled"


def test_local_qwen_with_prompt_cache_support_defaults_to_explicit_cache_control():
    public_config = load_public_config()
    public_config["llm"].setdefault("model_library", {})["local_qwen_cache_probe"] = {
        "model": "Qwen3-32B-AWQ",
        "label": "Local Qwen with cache support",
        "transport": "chat_completions",
        "contract": "basic_chat",
        "protocol": "qwen_thinking_no_prefill",
        "tool_calling_mode": "disabled",
        "supports_prompt_cache": True,
        "provider": {
            "kind": "local",
            "api": "openai-completions",
            "api_key_env": "",
            "base_url": "http://192.168.20.63:8000/v1",
            "compat_mode": "openai",
            "requires_api_key": False,
            "context_window": 128000,
        },
    }
    public_config["llm"]["profiles"]["primary"] = {
        "model_ref": "local_qwen_cache_probe",
        "overrides": {},
    }

    effective = build_effective_config(public_config)
    profile = effective.llm.get_profile("primary")

    assert profile.model == "Qwen3-32B-AWQ"
    assert profile.prompt_cache.mode == "explicit_cache_control"


def test_dashscope_qwen_preset_uses_explicit_cache_control():
    model = LLM_MODEL_PRESETS["dashscope_qwen3_6_plus"]["model"]

    assert model["model"] == "qwen3.6-plus"
    assert model["prompt_cache"] == {"mode": "explicit_cache_control"}
    assert model["protocol"] == "qwen_openai_compat"


def test_main_model_presets_declare_protocol_source_of_truth():
    assert LLM_MODEL_PRESETS["xiaomi_mimo_v2_5_pro_token_plan"]["model"]["protocol"] == (
        "xiaomi_mimo_token_plan_openai_compat"
    )
    assert LLM_MODEL_PRESETS["xiaomi_mimo_v2_5_multimodal"]["model"]["protocol"] == (
        "xiaomi_mimo_multimodal_openai_compat"
    )
    assert LLM_MODEL_PRESETS["deepseek_v4_flash"]["model"]["protocol"] == "deepseek_reasoning"
    assert LLM_MODEL_PRESETS["deepseek_v4_pro"]["model"]["protocol"] == "deepseek_reasoning"
    assert LLM_MODEL_PRESETS["anthropic_claude_sonnet"]["model"]["protocol"] == "anthropic_chat"


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


def test_delete_llm_model_leaves_legacy_profiles_unchanged():
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

    assert "openai_gpt_5_5" not in deleted["llm"]["model_library"]
    assert deleted["llm"]["profiles"]["primary"] == public_config["llm"]["profiles"]["primary"]
    assert deleted["llm"]["profiles"]["mental_model"] == public_config["llm"]["profiles"]["mental_model"]
