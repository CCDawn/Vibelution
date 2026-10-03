# -*- coding: utf-8 -*-
"""协议族规则表（config/protocol_families.py）的聚焦测试。

覆盖三件事：
1. 族表完整性：每族每个 model_protocol 词表成员，经族默认合成后的条目都能
   构造 LLMProfile 并通过 Wave1 校验闸（llm_model_entry_issues）零 error。
2. 合成语义：显式覆盖 > 族默认；空/缺失才落默认；未知协议族不改写。
3. 运行时集成：换模型路径（config_for_agent_llm_model）与启动 doctor
   （doctor_model_library）在族表供给下放行稀疏条目，且族表关闭时被闸拦截
   （因果对照）。
"""

import pytest

from config.public_config import build_effective_config
from config.protocol_families import (
    FAMILY_DEFAULTS,
    PROTOCOL_FAMILY_VOCABULARY,
    apply_model_entry_family_defaults,
    protocol_family_for_entry,
    resolve_model_entry_family_defaults,
)
from config.models import LLMProfile, ProviderConfig
from core.llm.agent_runtime import AgentLlmResolutionError, config_for_agent_llm_model
from core.llm.discovery import build_llm_profile_from_model_entry, doctor_model_library, llm_model_entry_issues


# ---------------------------------------------------------------------------
# 测试夹具
# ---------------------------------------------------------------------------


def _family_test_provider():
    return ProviderConfig(provider_id="family-probe", kind="openai", compat_mode="openai")


def _profile_built_from(entry):
    effective = apply_model_entry_family_defaults(entry)
    return build_llm_profile_from_model_entry(
        LLMProfile().model_dump(),
        effective,
        profile_id="family-probe",
        provider_id="family-probe",
        model_ref="family-probe/probe-model",
        model_name="probe-model",
    )


def _family_config():
    return build_effective_config(
        {
            "llm": {
                "schema_version": 2,
                "providers": {
                    "default": {
                        "label": "Family Test Provider",
                        "service_class": "aggregator",
                        "vendor": "custom",
                        "driver": "openai",
                        "base_url": "http://localhost:8000/v1",
                        "auth_kind": "none",
                        "credential_ref": "none",
                        "requires_credential": False,
                        "compat_mode": "openai",
                        "context_window": 65536,
                        "protocols": {
                            "default": "chat_completions",
                            "allowed": ["chat_completions", "responses"],
                        },
                        "models": {
                            # primary：responses 线思考模型，带显式 reasoning 合同。
                            "gpt-luna": {
                                "upstream_id": "gpt-5.6-luna",
                                "label": "GPT Luna",
                                "enabled": True,
                                "wire_protocol": "responses",
                                "interaction_contract": "tool_chat",
                                "defaults": {
                                    "reasoning_effort_values": ["low", "medium", "high"],
                                    "default_reasoning_effort": "medium",
                                    "reasoning_effort_adapter": "reasoning_object",
                                },
                            },
                            # sparse：deepseek 协议只写身份 + 协议，其余靠族默认。
                            "deepseek-sparse": {
                                "upstream_id": "deepseek-v4-pro",
                                "label": "DeepSeek Sparse",
                                "enabled": True,
                                "wire_protocol": "chat_completions",
                                "interaction_contract": "reasoning_chat",
                                "model_protocol": "deepseek_reasoning",
                            },
                        },
                    }
                },
                "profiles": {"primary": {"model_ref": "default/gpt-luna"}},
            }
        }
    )


def _identity_apply(entry):
    return dict(entry) if isinstance(entry, dict) else {}


# ---------------------------------------------------------------------------
# 1. 族表完整性：每族合成结果通过 Wave1 校验闸
# ---------------------------------------------------------------------------


def _all_family_protocol_pairs():
    return [
        (family, protocol)
        for family, protocols in PROTOCOL_FAMILY_VOCABULARY.items()
        for protocol in protocols
    ]


@pytest.mark.parametrize(("family", "protocol"), _all_family_protocol_pairs())
def test_every_family_protocol_composes_through_validation_gate(family, protocol):
    assert family in FAMILY_DEFAULTS
    entry = {"protocol": protocol}
    profile = _profile_built_from(entry)
    # 合成后的条目可构造 LLMProfile（_profile_built_from 内部完成），且过闸。
    errors, _warnings = llm_model_entry_issues(
        profile,
        _family_test_provider(),
        model_entry=apply_model_entry_family_defaults(entry),
    )
    assert errors == []


def test_family_table_covers_required_five_families():
    assert set(FAMILY_DEFAULTS) == {
        "deepseek_reasoning",
        "openai_reasoning",
        "anthropic_thinking",
        "qwen_thinking",
        "plain_chat",
    }


def test_deepseek_family_defaults_match_live_contract():
    defaults = FAMILY_DEFAULTS["deepseek_reasoning"]
    assert defaults["transport"] == "chat_completions"
    assert defaults["contract"] == "reasoning_chat"
    assert defaults["reasoning_state_field"] == "reasoning_content"
    assert defaults["reasoning_effort_adapter"] == "reasoning_effort"
    # adapter 与 values 成对（Wave1：adapter 声明了 values 为空即 error）。
    assert defaults["reasoning_effort_values"]
    assert defaults["default_reasoning_effort"] in defaults["reasoning_effort_values"]


# ---------------------------------------------------------------------------
# 2. 合成语义
# ---------------------------------------------------------------------------


def test_resolve_fills_missing_fields_for_sparse_deepseek_entry():
    resolved = resolve_model_entry_family_defaults({"protocol": "deepseek_reasoning"})
    assert resolved["transport"] == "chat_completions"
    assert resolved["contract"] == "reasoning_chat"
    assert resolved["reasoning_state_field"] == "reasoning_content"
    assert resolved["reasoning_effort_adapter"] == "reasoning_effort"
    assert resolved["reasoning_effort_values"] == ["low", "medium", "high"]
    assert resolved["default_reasoning_effort"] == "high"
    assert resolved["tool_calling_mode"] == "auto"


def test_resolve_treats_blank_string_and_empty_list_as_missing():
    resolved = resolve_model_entry_family_defaults(
        {
            "protocol": "deepseek_reasoning",
            "reasoning_state_field": "",
            "reasoning_effort_values": [],
            "default_reasoning_effort": None,
        }
    )
    assert resolved["reasoning_state_field"] == "reasoning_content"
    assert resolved["reasoning_effort_values"] == ["low", "medium", "high"]
    assert resolved["default_reasoning_effort"] == "high"


def test_explicit_nonblank_entry_values_win_over_family():
    entry = {
        "protocol": "deepseek_reasoning",
        "transport": "chat_completions",
        "contract": "reasoning_chat",
        "reasoning_state_field": "reasoning_content",
        "reasoning_effort_values": ["low", "xhigh"],
        "default_reasoning_effort": "xhigh",
        "reasoning_effort_adapter": "reasoning_effort",
        "tool_calling_mode": "parallel",
    }
    resolved = resolve_model_entry_family_defaults(entry)
    assert resolved == {}
    merged = apply_model_entry_family_defaults(entry)
    assert merged["reasoning_effort_values"] == ["low", "xhigh"]
    assert merged["default_reasoning_effort"] == "xhigh"
    assert merged["tool_calling_mode"] == "parallel"


def test_unknown_protocol_family_is_not_rewritten():
    for entry in (
        {"protocol": "brand_new_future_protocol"},
        {"model": "some-model", "provider_id": "p"},
        {"protocol": "tool_chat"},  # interaction contract 误存为 model_protocol，交闸处理
    ):
        assert protocol_family_for_entry(entry) == ""
        assert resolve_model_entry_family_defaults(entry) == {}
        assert apply_model_entry_family_defaults(entry) == entry


def test_raw_model_protocol_key_is_recognized():
    assert protocol_family_for_entry({"model_protocol": "deepseek_reasoning"}) == "deepseek_reasoning"
    resolved = resolve_model_entry_family_defaults({"model_protocol": "openai_responses"})
    assert resolved["transport"] == "responses"
    assert resolved["reasoning_effort_adapter"] == "reasoning_object"


def test_non_mapping_input_returns_empty_without_raising():
    for bad in (None, "deepseek_reasoning", 42, ["protocol"]):
        assert protocol_family_for_entry(bad) == ""
        assert resolve_model_entry_family_defaults(bad) == {}
        assert apply_model_entry_family_defaults(bad) == {}


def test_apply_does_not_mutate_input_entry():
    entry = {"protocol": "deepseek_reasoning"}
    merged = apply_model_entry_family_defaults(entry)
    assert "reasoning_state_field" not in entry
    assert merged["reasoning_state_field"] == "reasoning_content"


# ---------------------------------------------------------------------------
# 3. 运行时集成：换模型路径与启动 doctor
# ---------------------------------------------------------------------------


def test_switch_sparse_deepseek_entry_succeeds_with_family_defaults():
    config = _family_config()
    runtime = config_for_agent_llm_model(config, model_id="default/deepseek-sparse")
    profile = runtime.llm.get_profile(role="primary")
    assert profile.model == "deepseek-v4-pro"
    assert profile.protocol == "deepseek_reasoning"
    assert profile.contract == "reasoning_chat"
    assert profile.transport == "chat_completions"
    # 族表补齐了条目漏写的 reasoning_state_field（漂移修复）。
    assert profile.reasoning_state_field == "reasoning_content"
    assert profile.reasoning_effort_adapter == "reasoning_effort"
    assert list(profile.reasoning_effort_values) == ["low", "medium", "high"]
    assert profile.default_reasoning_effort == "high"


def test_family_defaults_beat_primary_profile_leftovers():
    """primary 是 responses 思考模型时，切到 sparse deepseek 不得泄漏 primary 的 reasoning 合同。"""
    config = _family_config()
    primary = config.llm.get_profile(role="primary")
    assert primary.reasoning_effort_adapter == "reasoning_object"
    runtime = config_for_agent_llm_model(config, model_id="default/deepseek-sparse")
    profile = runtime.llm.get_profile(role="primary")
    assert profile.reasoning_effort_adapter == "reasoning_effort"
    assert profile.reasoning_state_field == "reasoning_content"


def test_operator_explicit_value_beats_family_default_at_runtime():
    config = _family_config()
    config.llm.model_library["default/deepseek-sparse"]["tool_calling_mode"] = "parallel"
    runtime = config_for_agent_llm_model(config, model_id="default/deepseek-sparse")
    assert runtime.llm.get_profile(role="primary").tool_calling_mode == "parallel"


def test_switch_sparse_entry_rejected_when_family_disabled(monkeypatch):
    """因果对照：关掉族表后同一稀疏条目被 Wave1 闸拦截（缺 reasoning_state_field）。"""
    monkeypatch.setattr("core.llm.discovery.apply_model_entry_family_defaults", _identity_apply)
    config = _family_config()
    with pytest.raises(AgentLlmResolutionError) as exc_info:
        config_for_agent_llm_model(config, model_id="default/deepseek-sparse")
    assert "reasoning_state_field" in str(exc_info.value)
    # 原配置不受影响。
    assert config.llm.get_profile(role="primary").model == "gpt-5.6-luna"


def test_doctor_model_library_clean_with_family_flags_without(monkeypatch):
    config = _family_config()
    primary_ref = config.llm.get_profile(role="primary").model_ref

    findings = doctor_model_library(config, skip_model_refs={primary_ref})
    assert all(finding["modelId"] != "default/deepseek-sparse" for finding in findings)

    monkeypatch.setattr("core.llm.discovery.apply_model_entry_family_defaults", _identity_apply)
    findings = doctor_model_library(config, skip_model_refs={primary_ref})
    flagged = {finding["modelId"]: finding for finding in findings}
    assert "default/deepseek-sparse" in flagged
    assert any("reasoning_state_field" in item for item in flagged["default/deepseek-sparse"]["errors"])


def test_deepseek_reasoning_on_explicit_responses_wire_still_rejected():
    """族默认不救助显式错配：条目显式 transport=responses 时闸仍报 deepseek+responses 错。"""
    entry = {"protocol": "deepseek_reasoning", "transport": "responses"}
    profile = _profile_built_from(entry)
    assert profile.transport == "responses"
    errors, _warnings = llm_model_entry_issues(
        profile,
        _family_test_provider(),
        model_entry=apply_model_entry_family_defaults(entry),
    )
    assert any("deepseek_reasoning" in item and "chat_completions" in item for item in errors)
