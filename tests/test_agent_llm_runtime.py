import json

import pytest

from config.public_config import build_effective_config
from core.llm.agent_runtime import AgentLlmResolutionError, config_for_agent_llm_model, resolve_agent_llm
from core.llm.client import LLMClient
from core.llm.types import LLMError

def _config_with_agent_models():
    config = build_effective_config(
        {
            "llm": {
                "schema_version": 2,
                "providers": {
                    "default": {
                        "label": "Test Provider",
                        "service_class": "local_runtime",
                        "vendor": "custom",
                        "driver": "openai",
                        "base_url": "http://localhost:8000/v1",
                        "auth_kind": "none",
                        "credential_ref": "none",
                        "requires_credential": False,
                        "protocols": {
                            "default": "chat_completions",
                            "allowed": ["chat_completions", "responses"],
                        },
                        "models": {
                            "dialogue-base": {
                                "upstream_id": "dialogue-base",
                                "label": "Dialogue Base",
                                "enabled": True,
                            }
                        },
                    }
                },
                "profiles": {"primary": {"model_ref": "default/dialogue-base"}},
            }
        }
    )
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
            "prompt_cache": {"mode": "automatic", "key": "summary-agent-cache", "retention": "24h"},
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


def test_resolve_agent_llm_rejects_unregistered_model_before_runtime_call():
    config = _config_with_agent_models()
    agent = {"agentId": "agent-a", "llmBindings": {"dialogue": {"modelId": "missing-model-id"}}}

    with pytest.raises(AgentLlmResolutionError, match="Agent dialogue model not found in model library: missing-model-id"):
        resolve_agent_llm(agent, "dialogue", config=config)


def test_resolve_agent_llm_alias_logs_requested_and_canonical_refs() -> None:
    config = _config_with_agent_models()
    config.llm.model_aliases = {"legacy-dialogue": "dialogue-model"}
    agent = {"agentId": "agent-a", "llmBindings": {"dialogue": {"modelId": "legacy-dialogue"}}}

    resolved = resolve_agent_llm(agent, "dialogue", config=config)

    assert resolved.model_id == "dialogue-model"
    assert resolved.config.llm.profiles["primary"].model_ref == "dialogue-model"
    assert resolved.log_fields()["requestedModelRef"] == "legacy-dialogue"
    assert resolved.log_fields()["modelRef"] == "dialogue-model"


def test_runtime_model_uses_upstream_id_not_deployment_artifact_path() -> None:
    config = _config_with_agent_models()
    config.llm.providers["default"].deployment.artifact_path = "D:/models/private/model.gguf"
    config.llm.model_library["default/gpt-a"] = {
        "model_ref": "default/gpt-a",
        "provider_id": "default",
        "upstream_id": "gpt-a",
        "model": "gpt-a",
    }

    runtime = config_for_agent_llm_model(config, model_id="default/gpt-a")

    assert runtime.llm.profiles["primary"].model == "gpt-a"
    assert runtime.llm.profiles["primary"].model != "D:/models/private/model.gguf"


def test_discover_model_layers_operator_over_runtime_probe_and_exposes_canonical_details(monkeypatch) -> None:
    config = _config_with_agent_models()
    config.llm.model_library["default/gpt-a"] = {
        "model_ref": "default/gpt-a",
        "provider_id": "default",
        "upstream_id": "gpt-a",
        "model": "gpt-a",
        "capabilities": {"imageInput": False},
    }
    monkeypatch.setattr(
        "core.llm.discovery.load_model_catalog_state",
        lambda: {
            "schemaVersion": 2,
            "metadata": {},
            "providers": {
                "default": {
                    "status": "reachable",
                    "catalogStale": False,
                    "models": {
                        "gpt-a": {
                            "upstreamId": "gpt-a",
                            "availability": "observed",
                            "capabilities": {
                                "image_input": {
                                    "value": "supported",
                                    "source": "runtime_probe",
                                }
                            },
                        }
                    },
                }
            },
        },
    )
    agent = {"agentId": "agent-a", "llmBindings": {"vision": {"modelId": "default/gpt-a"}}}

    resolved = resolve_agent_llm(agent, "vision", config=config, fallback_to_dialogue=False)
    details = resolved.resolved_spec.provider_details

    assert resolved.capabilities.supports_image_input is False
    assert details["model_ref"] == "default/gpt-a"
    assert details["provider_id"] == "default"
    assert details["upstream_id"] == "gpt-a"
    assert details["catalog_availability"] == "observed"
    assert details["capabilities"]["image_input"]["source"] == "operator_override"


def test_llm_client_emits_bounded_protocol_resolution_event_without_sensitive_payload(monkeypatch) -> None:
    config = _config_with_agent_models()
    provider = config.llm.providers["default"]
    provider.legacy_inference_allowed = False
    provider.protocols.default = "responses"
    provider.protocols.allowed = ["responses"]
    provider.extra_headers = {"Authorization": "Bearer do-not-log"}
    provider.deployment.artifact_path = "D:/private/catalog/model.gguf"
    config.llm.model_library["default/gpt-a"] = {
        "model_ref": "default/gpt-a",
        "provider_id": "default",
        "upstream_id": "gpt-a",
        "model": "gpt-a",
    }
    runtime = config_for_agent_llm_model(config, model_id="default/gpt-a")
    recorded = []
    monkeypatch.setattr("core.llm.client._record_llm_scene_event", lambda *args, **kwargs: recorded.append((args, kwargs)))

    LLMClient(config=runtime, backend=lambda payload: payload)

    event = next(item for item in recorded if item[0][1] == "llm.protocol.resolved")
    serialized = json.dumps(event[1]["fields"], ensure_ascii=False)
    assert event[1]["outcome"] == "succeeded"
    assert "do-not-log" not in serialized
    assert "Authorization" not in serialized
    assert "D:/private/catalog/model.gguf" not in serialized
    assert "messages" not in event[1]["fields"]


def test_llm_client_blocks_unknown_v2_protocol_before_request_and_emits_safe_event(monkeypatch) -> None:
    config = _config_with_agent_models()
    provider = config.llm.providers["default"]
    provider.legacy_inference_allowed = False
    provider.protocols.default = ""
    provider.protocols.allowed = []
    provider.__dict__["driver"] = "custom"
    config.llm.model_library["default/gpt-a"] = {
        "model_ref": "default/gpt-a",
        "provider_id": "default",
        "upstream_id": "gpt-a",
        "model": "gpt-a",
    }
    runtime = config_for_agent_llm_model(config, model_id="default/gpt-a")
    recorded = []
    monkeypatch.setattr("core.llm.client._record_llm_scene_event", lambda *args, **kwargs: recorded.append((args, kwargs)))

    with pytest.raises(LLMError) as error:
        LLMClient(config=runtime, backend=lambda payload: pytest.fail("request must not be sent"))

    assert error.value.category == "provider_protocol_error"
    event = next(item for item in recorded if item[0][1] == "llm.protocol.blocked")
    assert event[1]["fields"] == {
        "providerId": "default",
        "modelRef": "default/gpt-a",
        "errorType": "protocol_unknown",
    }


def test_resolve_agent_llm_inherits_prompt_cache_config_from_model_library():
    config = _config_with_agent_models()
    agent = {"agentId": "agent-a", "llmBindings": {"summary": {"modelId": "summary-model"}}}

    resolved = resolve_agent_llm(agent, "summary", config=config, fallback_to_dialogue=False)

    prompt_cache = resolved.config.llm.profiles["primary"].prompt_cache
    assert prompt_cache.mode == "automatic"
    assert prompt_cache.key == "summary-agent-cache"
    assert prompt_cache.retention == "24h"


def test_resolve_agent_llm_resets_prompt_cache_when_model_has_no_cache_config():
    config = _config_with_agent_models()
    config.llm.profiles["primary"].prompt_cache.mode = "automatic"
    config.llm.profiles["primary"].prompt_cache.key = "stale-primary-cache"
    config.llm.profiles["primary"].prompt_cache.retention = "in_memory"
    agent = {"agentId": "agent-a", "llmBindings": {"vision": {"modelId": "vision-model"}}}

    resolved = resolve_agent_llm(agent, "vision", config=config, fallback_to_dialogue=False)

    prompt_cache = resolved.config.llm.profiles["primary"].prompt_cache
    assert prompt_cache.mode == "disabled"
    assert prompt_cache.key == ""
    assert prompt_cache.retention == ""


def test_resolve_agent_llm_applies_reasoning_effort_for_supported_gpt_slot():
    config = _config_with_agent_models()
    config.llm.providers["default"].kind = "relay"
    config.llm.providers["default"].compat_mode = "openai"
    config.llm.model_library["dialogue-model"].update({
        "model": "gpt-5.5",
        "transport": "responses",
        "contract": "tool_chat",
    })
    agent = {
        "agentId": "agent-a",
        "llmBindings": {"dialogue": {"modelId": "dialogue-model"}},
        "metadata": {"llmReasoningEffort": {"dialogue": "high"}},
    }

    resolved = resolve_agent_llm(agent, "dialogue", config=config)

    assert resolved.config.llm.profiles["primary"].reasoning_effort == "high"
    assert resolved.capabilities.supports_thinking is True


def test_resolve_agent_llm_ignores_reasoning_effort_for_unsupported_slot_model():
    config = _config_with_agent_models()
    agent = {
        "agentId": "agent-a",
        "llmBindings": {"dialogue": {"modelId": "dialogue-model"}},
        "metadata": {"llmReasoningEffort": {"dialogue": "high"}},
    }

    resolved = resolve_agent_llm(agent, "dialogue", config=config)

    assert resolved.config.llm.profiles["primary"].reasoning_effort == ""
