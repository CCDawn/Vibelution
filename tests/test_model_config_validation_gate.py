# -*- coding: utf-8 -*-
"""模型配置校验门前移的聚焦测试。

覆盖两件事：
1. 换模型运行时路径（config_for_agent_llm_model）的配置校验闸：非法字段组合
   拒绝切换、会话保持当前模型、错误消息含修复指引。
2. 启动 doctor 全量化（doctor_model_library）：全部 enabled pinned model 条目
   聚合体检，不阻塞启动；primary 由 doctor_llm_profile 单独覆盖并跳过去重。
"""

import pytest

from config.public_config import build_effective_config
from core.llm.agent_runtime import AgentLlmResolutionError, config_for_agent_llm_model
from core.llm.discovery import (
    assert_llm_compatibility,
    doctor_model_library,
    llm_model_entry_issues,
    llm_profile_entry_issues,
)


def _base_config():
    return build_effective_config(
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
                        "compat_mode": "native",
                        "context_window": 65536,
                        "protocols": {
                            "default": "chat_completions",
                            "allowed": ["chat_completions", "responses"],
                        },
                        "models": {
                            "good-model": {
                                "upstream_id": "good-model",
                                "label": "Good Model",
                                "enabled": True,
                            },
                            "bad-reasoning": {
                                "upstream_id": "bad-reasoning",
                                "label": "Bad Reasoning",
                                "enabled": True,
                                "interaction_contract": "reasoning_chat",
                            },
                            "disabled-model": {
                                "upstream_id": "disabled-model",
                                "label": "Disabled Model",
                                "enabled": False,
                                "interaction_contract": "reasoning_chat",
                            },
                        },
                    }
                },
                "profiles": {"primary": {"model_ref": "default/good-model"}},
            }
        }
    )


def _bind(config, model_id):
    return {"agentId": "agent-a", "llmBindings": {"dialogue": {"modelId": model_id}}}


# ---------------------------------------------------------------------------
# 单条目校验函数（llm_model_entry_issues / llm_profile_entry_issues）
# ---------------------------------------------------------------------------


def _entry_issues_for(config, model_id):
    entry = config.llm.model_library[model_id]
    profile = config.llm.get_profile(role="primary").model_dump()
    from core.llm.discovery import build_llm_profile_from_model_entry

    built = build_llm_profile_from_model_entry(
        profile,
        entry,
        profile_id="scratch",
        provider_id=str(entry.get("provider_id") or "default"),
        model_ref=model_id,
        model_name=str(entry.get("model") or ""),
    )
    provider = config.llm.get_provider("default")
    return llm_model_entry_issues(built, provider, model_entry=entry)


def test_entry_issues_flags_reasoning_chat_without_state_field():
    config = _base_config()
    errors, _warnings = _entry_issues_for(config, "default/bad-reasoning")
    assert any("reasoning_state_field" in item for item in errors)


def test_entry_issues_clean_for_valid_entry():
    config = _base_config()
    errors, _warnings = _entry_issues_for(config, "default/good-model")
    assert errors == []


def test_entry_issues_flags_interaction_contract_stored_as_model_protocol():
    config = _base_config()
    config.llm.model_library["default/good-model"]["protocol"] = "reasoning_chat"
    errors, _warnings = _entry_issues_for(config, "default/good-model")
    assert any("model_protocol" in item and "interaction" in item for item in errors)


def test_entry_issues_flags_deepseek_reasoning_on_responses_wire():
    config = _base_config()
    entry = config.llm.model_library["default/good-model"]
    entry["protocol"] = "deepseek_reasoning"
    entry["transport"] = "responses"
    errors, _warnings = _entry_issues_for(config, "default/good-model")
    assert any("deepseek_reasoning" in item and "chat_completions" in item for item in errors)


def test_entry_issues_flags_reasoning_adapter_without_values():
    config = _base_config()
    config.llm.model_library["default/good-model"]["reasoning_effort_adapter"] = "reasoning_object"
    errors, _warnings = _entry_issues_for(config, "default/good-model")
    assert any("reasoning_effort_values" in item for item in errors)


def test_profile_entry_issues_keeps_assert_semantics_without_entry_rules():
    """不带 model_entry 时，函数语义与 assert_llm_compatibility 使用的契约校验一致。"""
    config = _base_config()
    profile = config.llm.get_profile(role="primary")
    provider = config.llm.get_provider("default")
    errors, warnings = llm_profile_entry_issues(profile, provider)
    assert errors == []
    assert isinstance(warnings, list)


def test_assert_llm_compatibility_unchanged_for_valid_profiles():
    config = _base_config()
    assert assert_llm_compatibility(config) is config


# ---------------------------------------------------------------------------
# 换模型运行时闸门（config_for_agent_llm_model）
# ---------------------------------------------------------------------------


def test_switch_rejects_reasoning_chat_missing_state_field_and_keeps_session_model():
    config = _base_config()
    agent = _bind(config, "default/bad-reasoning")

    with pytest.raises(AgentLlmResolutionError) as exc_info:
        config_for_agent_llm_model(config, model_id="default/bad-reasoning")

    message = str(exc_info.value)
    assert "reasoning_state_field" in message
    assert "保持当前模型" in message
    assert "修正" in message
    # 会话当前模型不受影响：原配置的 primary profile 未被改写。
    assert config.llm.get_profile(role="primary").model == "good-model"
    assert config.llm.get_profile(role="primary").model_ref == "default/good-model"
    # agent 绑定也未被改动。
    assert agent["llmBindings"]["dialogue"]["modelId"] == "default/bad-reasoning"


def test_switch_rejects_interaction_contract_stored_as_model_protocol():
    config = _base_config()
    config.llm.model_library["default/good-model"]["protocol"] = "reasoning_chat"

    with pytest.raises(AgentLlmResolutionError) as exc_info:
        config_for_agent_llm_model(config, model_id="default/good-model")

    message = str(exc_info.value)
    assert "model_protocol" in message
    assert config.llm.get_profile(role="primary").model_ref == "default/good-model"


def test_switch_rejects_reasoning_adapter_without_values():
    config = _base_config()
    config.llm.model_library["default/good-model"]["reasoning_effort_adapter"] = "reasoning_object"

    with pytest.raises(AgentLlmResolutionError) as exc_info:
        config_for_agent_llm_model(config, model_id="default/good-model")

    assert "reasoning_effort_values" in str(exc_info.value)


def test_switch_proceeds_for_valid_entry():
    config = _base_config()
    config.llm.model_library["default/bad-reasoning"]["contract"] = "tool_chat"

    runtime = config_for_agent_llm_model(config, model_id="default/bad-reasoning")

    assert runtime.llm.get_profile(role="primary").model == "bad-reasoning"
    # 原配置不被就地改写。
    assert config.llm.get_profile(role="primary").model == "good-model"


def test_switch_tolerates_errors_when_strict_compatibility_disabled():
    config = _base_config()
    entry = config.llm.model_library["default/bad-reasoning"]
    entry["strict_compatibility"] = False

    runtime = config_for_agent_llm_model(config, model_id="default/bad-reasoning")

    assert runtime.llm.get_profile(role="primary").model == "bad-reasoning"


# ---------------------------------------------------------------------------
# 启动 doctor 全量化（doctor_model_library）
# ---------------------------------------------------------------------------


def test_doctor_model_library_aggregates_bad_entries_without_raising():
    config = _base_config()
    primary_ref = config.llm.get_profile(role="primary").model_ref

    findings = doctor_model_library(config, skip_model_refs={primary_ref})

    flagged = {finding["modelId"]: finding for finding in findings}
    # 坏的非 primary 条目被点名，错误信息含字段问题。
    assert "default/bad-reasoning" in flagged
    assert any("reasoning_state_field" in item for item in flagged["default/bad-reasoning"]["errors"])
    # 合法条目与 disabled 条目不产生 finding。
    assert "default/good-model" not in flagged
    assert "default/disabled-model" not in flagged


def test_doctor_model_library_skips_primary_entry_for_dedup():
    """primary 条目由 doctor_llm_profile 覆盖；sweep 跳过它避免重复告警。"""
    config = _base_config()
    # 把 primary 绑定到坏条目上：primary 的 doctor 单独报错，sweep 跳过该条目。
    config.llm.profiles["primary"].model_ref = "default/bad-reasoning"
    config.llm.profiles["primary"].contract = "reasoning_chat"

    findings = doctor_model_library(
        config,
        skip_model_refs={"default/bad-reasoning"},
    )

    assert all(finding["modelId"] != "default/bad-reasoning" for finding in findings)


def test_doctor_model_library_flags_missing_provider_and_window_warning():
    config = _base_config()
    config.llm.model_library["default/good-model"]["provider_id"] = "ghost-provider"
    config.llm.providers["default"].context_window = None

    findings = doctor_model_library(config)

    flagged = {finding["modelId"]: finding for finding in findings}
    assert "default/good-model" in flagged
    assert any("ghost-provider" in item for item in flagged["default/good-model"]["errors"])


def test_doctor_model_library_loads_catalog_once_per_sweep(monkeypatch):
    """启动体检不许每条目读一次磁盘：catalog state 整个 sweep 只加载一次。"""
    config = _base_config()
    calls = {"count": 0}

    def _counting_load(*args, **kwargs):
        calls["count"] += 1
        return {"schemaVersion": 2, "metadata": {}, "providers": {}}

    monkeypatch.setattr("core.llm.discovery.load_model_catalog_state", _counting_load)

    doctor_model_library(config)

    assert calls["count"] == 1
