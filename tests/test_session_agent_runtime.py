from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from core.orchestration.turn_runner import create_agent_runtime
from core.web.services import session_service


def test_web_session_factory_propagates_agent_runtime_binding(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}
    runtime_agent = SimpleNamespace()

    def fake_chat_agent_factory(**kwargs):
        captured.update(kwargs)
        return runtime_agent

    monkeypatch.setattr(session_service, "create_chat_agent", fake_chat_agent_factory)
    agent_instance = {
        "agentId": "agent-luna-pressure",
        "directSessionId": "session-luna-pressure",
        "workspacePath": "workspace/agents/agent-luna-pressure",
    }

    created = session_service._create_chat_agent_for_session(
        tmp_path,
        agent_instance=agent_instance,
        llm_slot="dialogue",
        resolved_llm=SimpleNamespace(config=object()),
    )

    assert created is runtime_agent
    assert captured["runtime_agent_binding"] == {
        "agentId": "agent-luna-pressure",
        "directSessionId": "session-luna-pressure",
        "workspacePath": "workspace/agents/agent-luna-pressure",
        "llmSlot": "dialogue",
    }


def test_shared_agent_factory_propagates_explicit_runtime_binding() -> None:
    captured: dict[str, object] = {}
    runtime_agent = object()
    runtime_binding = {
        "agentId": "agent-luna-pressure",
        "llmSlot": "dialogue",
    }

    def factory(**kwargs):
        captured.update(kwargs)
        return runtime_agent

    created = create_agent_runtime(
        mode="chat",
        workspace_path="workspace/sessions/session-luna-pressure",
        config="config",
        runtime_agent_binding=runtime_binding,
        agent_factory=factory,
    )

    assert created is runtime_agent
    assert captured["runtime_agent_binding"] == runtime_binding


def test_runtime_cache_fingerprint_tracks_authoritative_agent_compression_policy(
    tmp_path: Path,
) -> None:
    base_agent = {
        "agentId": "agent-luna-pressure",
        "updatedAt": "2026-07-31T12:00:00Z",
        "configRevision": 8,
        "configHash": "config-hash-v8",
        "contextCompressionPolicy": {
            "mode": "custom",
            "enabled": True,
            "maxTokenLimit": 262_144,
        },
    }
    fingerprint = session_service._session_agent_runtime_cache_fingerprint(
        session_workspace=tmp_path,
        agent_instance=base_agent,
        llm_slot="dialogue",
        resolved_llm=SimpleNamespace(
            config={"context_compression": {"enabled": True}},
            model_id="gpt-5.6-luna",
        ),
        mode="chat",
        prompt_snapshot_hash="prompt-v1",
    )
    changed_policy = session_service._session_agent_runtime_cache_fingerprint(
        session_workspace=tmp_path,
        agent_instance={
            **base_agent,
            "contextCompressionPolicy": {
                **base_agent["contextCompressionPolicy"],
                "maxTokenLimit": 300_000,
            },
        },
        llm_slot="dialogue",
        resolved_llm=SimpleNamespace(
            config={"context_compression": {"enabled": True}},
            model_id="gpt-5.6-luna",
        ),
        mode="chat",
        prompt_snapshot_hash="prompt-v1",
    )

    assert changed_policy != fingerprint


def test_resolved_workspace_path_key_matches_path_resolve_and_memoizes(
    tmp_path: Path,
) -> None:
    """fingerprint 的 workspace resolve memo：值与 Path.resolve() 一致且稳定。

    同一输入重复调用必须返回同一字符串（memo 命中），保证 fingerprint 对
    相同输入保持稳定，AgentRuntime 缓存命中率不受影响。
    """

    from core.web.services.session.agent_runtime import (
        _resolved_workspace_path_key,
    )

    first = _resolved_workspace_path_key(tmp_path)
    assert first == str(tmp_path.resolve())
    assert _resolved_workspace_path_key(tmp_path) == first


def test_fingerprint_stable_across_repeated_calls(tmp_path: Path) -> None:
    agent = {"agentId": "agent-fp-stable", "configRevision": 3}
    kwargs = {
        "agent_instance": agent,
        "llm_slot": "dialogue",
        "resolved_llm": SimpleNamespace(
            config={"context_compression": {"enabled": True}},
            model_id="glm-fp",
        ),
        "mode": "chat",
        "prompt_snapshot_hash": "prompt-v1",
    }
    fingerprints = [
        session_service._session_agent_runtime_cache_fingerprint(
            session_workspace=tmp_path,
            **kwargs,
        )
        for _ in range(3)
    ]
    assert len(set(fingerprints)) == 1


@pytest.fixture
def compression_failure_runtime(monkeypatch):
    import agent as agent_module
    from langchain_core.messages import ToolMessage
    from tests.test_agent_protocol import TestLocalProviderBootstrap
    from tests.test_turn_compression import _FakeStrategy
    from core.orchestration import turn_compression

    invoked, events = [], []
    def unexpected_model_call(*args, **kwargs):
        invoked.append(True)
        raise AssertionError("A compression refusal must prevent the model call")
    runtime = TestLocalProviderBootstrap()._provider_context_retry_agent(
        monkeypatch, max_retries=1, invoke=unexpected_model_call, compress_calls=[], ui_logs=[])
    # Reuse the existing full-loop harness, while exercising the real compression
    # adapter, retention gate, run_single_turn finalizer and diagnostic projection.
    del runtime._compress_messages
    runtime.config.agent.awake_interval = 1
    runtime.key_tools = []
    runtime._resolve_tool_authorization = lambda _tools: SimpleNamespace(
        decision=SimpleNamespace(decision_fingerprint="current-turn"))
    runtime._announce_scene_diagnostic_package = lambda: None
    runtime._context_compression_trigger_tokens = 400
    runtime._context_input_hard_limit = 1000
    runtime._post_compression_target_tokens = 300
    runtime._last_compression_iteration = 0
    runtime._compression_count_this_turn = 0
    runtime._compression_strategy = _FakeStrategy()
    runtime.token_compressor = SimpleNamespace(compress=lambda messages, **kwargs: (
        [message for message in messages if not isinstance(message, ToolMessage)], "fixture checkpoint"))
    for name in ("start_session", "end_session"):
        monkeypatch.setattr(agent_module.logger, name, lambda *a, **k: None, raising=False)
    for name in ("start_session", "system", "info", "end_session"):
        monkeypatch.setattr(agent_module._debug_logger, name, lambda *a, **k: None)
    monkeypatch.setattr(agent_module, "get_state_manager", lambda: SimpleNamespace(set_state=lambda *a, **k: None))
    monkeypatch.setattr(agent_module, "_record_agent_scene_event",
                        lambda _phase, code, **kwargs: events.append((code, kwargs.get("fields", {}))))
    monkeypatch.setattr(turn_compression, "resolve_feature_decision",
                        lambda *a, **k: SimpleNamespace(effective_enabled=True))
    return SimpleNamespace(agent=runtime, invoked=invoked, events=events)


@pytest.mark.parametrize("previous_failed", [True, False])
def test_reused_agent_compression_refusal_keeps_current_turn_diagnostics(compression_failure_runtime, previous_failed):
    from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
    from core.web.services.session.agent_runtime import _prepare_reused_agent

    runtime = compression_failure_runtime.agent
    runtime._record_turn_failure_diagnostic(category="runtime_error", reason_code="prior_turn_failure",
        reason_summary="prior failure", reason_detail="prior diagnostic", chain_stage="prior_turn",
        event_code="agent.turn.prior_failure")
    runtime._last_turn_failed = previous_failed
    _prepare_reused_agent(runtime, SimpleNamespace(release=lambda: None))
    assert runtime._last_turn_metadata == {}
    runtime._active_turn_messages = [SystemMessage(content="fixture rules"),
        AIMessage(content="", tool_calls=[{"id": "fixture-call", "name": "fixture_tool", "args": {}}]),
        ToolMessage(content="fixture result", tool_call_id="fixture-call")]

    result = runtime.run_single_turn(initial_prompt="fixture request")

    assert compression_failure_runtime.invoked == []
    assert result["status"] == "failed"
    failure = result["llm_failure"]
    assert failure["reason_code"] == "context_budget_exhausted"
    assert failure["chain_stage"] == "llm_preflight"
    assert "guardReason=retention_missing" in failure["reason_detail"]
    assert "contextInputHardLimit=1000" in failure["reason_detail"]
    assert "postCompressionTargetTokens=300" in failure["reason_detail"]
    assert not any(code == "agent.turn.failed_without_diagnostics" for code, _ in compression_failure_runtime.events)
    projected = session_service._normalize_session_turn_error(session_service._make_session_turn_error(
        "", lang="zh", error_type="runtime_error", turn_id="fixture-turn", llm_failure=failure))
    assert projected["reasonCode"] == "context_budget_exhausted"
    assert "guardReason=retention_missing" in projected["reasonDetail"]


def test_context_failure_detail_keeps_only_bounded_budget_metadata(compression_failure_runtime):
    import json
    runtime = compression_failure_runtime.agent
    fields = {"guardReason": "budget_window_checkpoint_not_written", "estimatedTokens": 123,
              "afterTokens": 100, "contextInputHardLimit": 1000, "hardLimit": 1000,
              "postCompressionTargetTokens": 300, "summaryMaxChars": 80,
              "prompt": "secret-prompt", "summary": "secret-summary", "raw_error": "secret-error",
              "api_key": "secret-key", "toolArgs": {"secret": "secret-args"}}
    failure = runtime._record_turn_failure_diagnostic(category="context_error", reason_code="context_budget_exhausted",
        reason_summary="context refused", reason_detail="x" * 600, chain_stage="llm_preflight",
        event_code="agent.context_budget_exhausted", fields=fields)
    assert len(failure["reason_detail"]) <= 500
    for key in ("guardReason", "estimatedTokens", "afterTokens", "contextInputHardLimit", "hardLimit",
                "postCompressionTargetTokens", "summaryMaxChars"):
        assert f"{key}={fields[key]}" in failure["reason_detail"]
    assert "secret-" not in json.dumps(failure)
    context_fields = compression_failure_runtime.events[-1][1]
    assert not ({"prompt", "summary", "raw_error", "api_key", "toolArgs"} & context_fields.keys())


@pytest.mark.parametrize("guard,budget", [
    ("../secret-path", True), ("secret value", -1), ("code\nsecret-body", 2 ** 80),
    ("a" * 82, 1.5), (True, "secret-number"), (9, None), (None, False),
])
def test_context_failure_detail_rejects_non_code_guard_and_non_budget_values(compression_failure_runtime, guard, budget):
    runtime = compression_failure_runtime.agent
    failure = runtime._record_turn_failure_diagnostic(category="context_error", reason_code="context_budget_exhausted",
        reason_summary="context refused", reason_detail="safe detail", chain_stage="llm_preflight",
        event_code="agent.context_budget_exhausted", fields={"guardReason": guard, "estimatedTokens": budget,
            "unrecognized": "secret-field"})
    assert failure["reason_detail"] == "safe detail"
    context_fields = compression_failure_runtime.events[-1][1]
    assert not ({"guardReason", "estimatedTokens", "unrecognized"} & context_fields.keys())
