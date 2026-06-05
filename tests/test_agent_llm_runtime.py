from config import Settings
from core.llm.agent_runtime import resolve_agent_llm


def _config_with_agent_models():
    config = Settings(
        None,
        **{
            "llm.providers.default.kind": "local",
            "llm.providers.default.requires_api_key": False,
            "llm.providers.default.base_url": "http://localhost:8000/v1",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "dialogue-base",
        },
    ).config
    config.llm.model_library = {
        "dialogue-model": {
            "provider_id": "default",
            "model": "dialogue-base",
            "streaming": False,
            "tool_calling_mode": "disabled",
            "supports_image_input": False,
        },
        "summary-model": {
            "provider_id": "default",
            "model": "summary-fast",
            "streaming": True,
            "tool_calling_mode": "disabled",
        },
        "vision-model": {
            "provider_id": "default",
            "model": "vision-capable",
            "streaming": True,
            "tool_calling_mode": "auto",
            "capabilities": {"imageInput": True},
        },
    }
    return config


def test_resolve_agent_llm_maps_slot_model_to_runtime_primary_profile():
    config = _config_with_agent_models()
    agent = {
        "agentId": "agent-a",
        "llmBindings": {
            "dialogue": {"modelId": "dialogue-model"},
            "vision": {"modelId": "vision-model"},
        },
    }

    resolved = resolve_agent_llm(agent, "vision", config=config)

    assert resolved.agent_id == "agent-a"
    assert resolved.slot == "vision"
    assert resolved.model_id == "vision-model"
    assert resolved.runtime_profile_id == "primary"
    assert resolved.config.llm.profiles["primary"].model == "vision-capable"
    assert resolved.capabilities.supports_image_input is True
    assert resolved.capabilities.supports_tool_calling is True
    assert resolved.resolved_spec.provider_details["capability_source"] == "model_library.capabilities"
    assert resolved.log_fields()["supportsImageInput"] is True


def test_resolve_agent_llm_preserves_model_library_protocol_and_compat():
    config = _config_with_agent_models()
    config.llm.model_library["vision-model"]["protocol"] = "llamacpp_qwen_thinking"
    config.llm.model_library["vision-model"]["compat"] = {
        "allowAssistantPrefill": False,
        "reasoningRoundtrip": False,
        "toolChoiceMode": "omit",
    }
    agent = {
        "agentId": "agent-a",
        "llmBindings": {"vision": {"modelId": "vision-model"}},
    }

    resolved = resolve_agent_llm(agent, "vision", config=config)
    profile = resolved.config.llm.profiles["primary"]

    assert profile.protocol == "llamacpp_qwen_thinking"
    assert profile.compat["allowAssistantPrefill"] is False
    assert profile.compat["toolChoiceMode"] == "omit"


def test_resolve_agent_llm_falls_back_to_dialogue_when_optional_slot_missing():
    config = _config_with_agent_models()
    agent = {"agentId": "agent-a", "llmBindings": {"dialogue": {"modelId": "dialogue-model"}}}

    resolved = resolve_agent_llm(agent, "summary", config=config, fallback_to_dialogue=True)

    assert resolved.slot == "dialogue"
    assert resolved.requested_slot == "summary"
    assert resolved.model_id == "dialogue-model"
    assert resolved.fallback_chain == ["summary->dialogue"]
    assert resolved.capabilities.supports_streaming is False
    assert resolved.capabilities.supports_tool_calling is False
