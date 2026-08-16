"""Focused tests for Agent runtime binding helpers.

These functions parse env, classify compression triggers, and redact turn
metadata. They were only covered indirectly through agent.py.
"""

import json

import pytest
from langchain_core.messages import AIMessage

from core.llm.agent_runtime import AgentLlmResolutionError
from core.orchestration.agent_runtime_bindings import (
    _can_reuse_initial_prompt,
    _can_reuse_system_prompt,
    _context_compression_trigger_source,
    _format_tool_result_replacement_summary,
    _looks_like_numbered_confirmation,
    _normalize_goal_from_chat_history,
    _record_agent_tool_surface_event,
    _reset_stall_signal_reported,
    _runtime_agent_binding_from_env,
    _runtime_agent_llm_bindings_from_env,
    _runtime_mental_model_override_from_env,
    _safe_llm_error_diagnostic_details,
    _safe_turn_runtime_metadata,
    _stall_signal_threshold_events,
)


def test_context_compression_trigger_source_classifies_auto_provider_and_manual():
    assert _context_compression_trigger_source("") == "auto"
    assert _context_compression_trigger_source("Level: DEEP") == "auto"
    assert _context_compression_trigger_source("context limit exceeded") == "provider_limit"
    assert _context_compression_trigger_source("超出最大上下文") == "provider_limit"
    assert _context_compression_trigger_source("operator asked to compress") == "manual"


def test_format_tool_result_replacement_summary_skips_bad_items_and_caps_list():
    assert _format_tool_result_replacement_summary({}) == ""
    summary = _format_tool_result_replacement_summary(
        {
            "replacements": [
                "skip-me",
                {
                    "toolName": "read_file_tool",
                    "toolCallId": "c1",
                    "reference": "ref-1",
                    "originalChars": "12",
                    "sha256": "abcdef0123456789ffff",
                },
                {"toolName": "cli_tool", "originalChars": "not-a-number"},
            ]
            + [{"toolName": f"t{i}", "originalChars": 10} for i in range(8)]
        }
    )
    assert "read_file_tool" in summary
    assert "ref-1" in summary
    assert "abcdef0123456789" in summary
    assert "其余 2 个工具结果" in summary
    assert "skip-me" not in summary


def test_safe_turn_runtime_metadata_hashes_partition_and_omits_raw_value():
    metadata = _safe_turn_runtime_metadata(
        {
            "sessionId": "s1",
            "runId": "t1",
            "promptCachePartition": "secret-partition-value",
            "unknown": "drop-me",
        }
    )
    assert metadata["sessionId"] == "s1"
    assert metadata["runId"] == "t1"
    assert "promptCachePartition" not in metadata
    assert "secret-partition-value" not in json.dumps(metadata)
    assert metadata["promptCachePartitionChars"] == len("secret-partition-value")
    assert len(metadata["promptCachePartitionHash"]) == 12


def test_safe_llm_error_diagnostic_details_drops_prompt_like_keys():
    safe = _safe_llm_error_diagnostic_details(
        {
            "messageIndex": 3,
            "payloadValidationErrorType": "shape",
            "prompt": "do not leak this",
            "raw": {"nested": True},
        }
    )
    assert safe == {"messageIndex": 3, "payloadValidationErrorType": "shape"}
    assert _safe_llm_error_diagnostic_details("not-a-dict") == {}


def test_explicit_empty_binding_does_not_fall_back_to_process_env(monkeypatch):
    monkeypatch.setenv("VIBELUTION_AGENT_ID", "agent-from-env")
    assert _runtime_agent_binding_from_env({}) == {}


def test_runtime_llm_bindings_env_rejects_invalid_json_and_conflicts(monkeypatch):
    monkeypatch.delenv("VIBELUTION_AGENT_LLM_BINDINGS_JSON", raising=False)
    monkeypatch.delenv("VIBELUTION_AGENT_LLM_MODEL_ID", raising=False)

    monkeypatch.setenv("VIBELUTION_AGENT_LLM_BINDINGS_JSON", "{not-json")
    with pytest.raises(AgentLlmResolutionError, match="not valid JSON"):
        _runtime_agent_llm_bindings_from_env("dialogue")

    monkeypatch.setenv(
        "VIBELUTION_AGENT_LLM_BINDINGS_JSON",
        json.dumps({"dialogue": {"modelId": "model-a"}}),
    )
    monkeypatch.setenv("VIBELUTION_AGENT_LLM_MODEL_ID", "model-b")
    with pytest.raises(AgentLlmResolutionError, match="conflicts"):
        _runtime_agent_llm_bindings_from_env("dialogue")

    monkeypatch.setenv("VIBELUTION_AGENT_LLM_MODEL_ID", "model-a")
    assert _runtime_agent_llm_bindings_from_env("dialogue") == {"dialogue": {"modelId": "model-a"}}


def test_runtime_mental_model_override_from_env(monkeypatch):
    monkeypatch.delenv("VIBELUTION_SUPERVISED_MENTAL_MODEL_ENABLED", raising=False)
    monkeypatch.delenv("VIBELUTION_SUPERVISED_MENTAL_MODEL_MODE", raising=False)
    assert _runtime_mental_model_override_from_env() is None

    monkeypatch.setenv("VIBELUTION_SUPERVISED_MENTAL_MODEL_ENABLED", "YES")
    assert _runtime_mental_model_override_from_env() is True
    monkeypatch.setenv("VIBELUTION_SUPERVISED_MENTAL_MODEL_ENABLED", "off")
    assert _runtime_mental_model_override_from_env() is False

    monkeypatch.delenv("VIBELUTION_SUPERVISED_MENTAL_MODEL_ENABLED", raising=False)
    monkeypatch.setenv("VIBELUTION_SUPERVISED_MENTAL_MODEL_MODE", "enabled")
    assert _runtime_mental_model_override_from_env() is True


def test_numbered_confirmation_requires_short_answers_and_keywords():
    assert _looks_like_numbered_confirmation("1,确认,2,可以") is True
    assert _looks_like_numbered_confirmation("hello") is False
    assert _looks_like_numbered_confirmation("1,确认") is False
    long_prompt = "1,确认,2,可以," + ("x" * 280)
    assert _looks_like_numbered_confirmation(long_prompt) is False

    goal = _normalize_goal_from_chat_history(
        "1,确认,2,可以",
        None,
        [AIMessage(content="需求：实现入口")],
    )
    assert goal.startswith("需求：实现入口")
    assert "用户确认" in goal
    assert _normalize_goal_from_chat_history("直接提问", "override-goal", []) == "override-goal"


def test_runtime_bindings_coerce_bytes_json_and_invalid_ints():
    metadata = _safe_turn_runtime_metadata(
        {
            "session_id": b"s1",
            "run_id": b"t1",
            "prompt_cache_partition": b"secret-partition-value",
        }
    )
    assert metadata["sessionId"] == "s1"
    assert metadata["runId"] == "t1"
    assert metadata["promptCachePartitionChars"] == len("secret-partition-value")
    assert "b's1'" not in json.dumps(metadata)
    assert _safe_turn_runtime_metadata(["not-a-map"]) == {}
    assert _safe_turn_runtime_metadata('{"sessionId": "s2", "runId": "t2"}')["sessionId"] == "s2"

    binding = _runtime_agent_binding_from_env({"agent_id": b"agent-bytes", "llm_slot": "dialogue"})
    assert binding["agentId"] == "agent-bytes"
    assert binding["llmSlot"] == "dialogue"
    assert _runtime_agent_binding_from_env(["not-a-map"]) == {}
    json_binding = _runtime_agent_binding_from_env('{"agentId": "agent-json"}')
    assert json_binding["agentId"] == "agent-json"

    assert _stall_signal_threshold_events(["bad"], None) == []
    assert _stall_signal_threshold_events({"no_new_evidence_steps": "bad"}, {}) == []
    assert "no_new_evidence_steps" in _stall_signal_threshold_events(
        {"no_new_evidence_steps": "3"},
        {"no_new_evidence_steps": "false"},
    )
    assert _reset_stall_signal_reported(["bad"], {"no_new_evidence_steps": True}) == {}
    assert _reset_stall_signal_reported({"no_new_evidence_steps": "3"}, {"no_new_evidence_steps": True}) == {
        "no_new_evidence_steps": True
    }

    summary = _format_tool_result_replacement_summary(
        {
            "replacements": [
                {"toolName": b"read_file_tool", "originalChars": b"12", "reference": b"ref-1"},
            ]
        }
    )
    assert "read_file_tool" in summary
    assert "chars=12" in summary
    assert _format_tool_result_replacement_summary(["not-a-map"]) == ""
    assert _context_compression_trigger_source(b"context limit exceeded") == "provider_limit"
    assert _looks_like_numbered_confirmation("1,确认,2,可以".encode("utf-8")) is True
    assert _normalize_goal_from_chat_history("直接提问".encode("utf-8"), b"override-goal", "not-messages") == "override-goal"
    json_goal = _normalize_goal_from_chat_history(
        "1,确认,2,可以",
        None,
        '[{"role":"assistant","content":"需求：实现入口"}]',
    )
    assert json_goal.startswith("需求：实现入口")
    bytes_goal = _normalize_goal_from_chat_history(
        "1,确认,2,可以",
        None,
        [{"role": "assistant", "content": "需求：实现入口".encode("utf-8")}],
    )
    assert bytes_goal.startswith("需求：实现入口")
    assert _can_reuse_system_prompt(
        has_cached_prompt="false",
        prompt_built_with_runtime_key="k1",
        current_runtime_state_memory_key="k1",
    ) is False
    assert _can_reuse_initial_prompt(
        pending=True,
        has_cached_prompt="false",
        initial_runtime_state_memory_key="k1",
        current_runtime_state_memory_key="k1",
    ) is False
    assert _safe_llm_error_diagnostic_details(
        '{"messageIndex": 3, "payloadValidationErrorType": "shape", "prompt": "do not leak this"}'
    ) == {"messageIndex": 3, "payloadValidationErrorType": "shape"}
    captured = {}
    _record_agent_tool_surface_event(
        "read_file_tool",
        recorder=lambda *args, **kwargs: captured.setdefault("fields", kwargs.get("fields")),
    )
    assert captured["fields"]["toolCount"] == 1
    assert captured["fields"]["coreChatToolsPresent"] == ["read_file_tool"]
