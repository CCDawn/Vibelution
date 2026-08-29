"""Tests for the research node thinking-budget system prompt instruction."""

from __future__ import annotations

import pytest

from core.web.services import session_service
from core.web.services.session import worker
from core.web.services.session.research_thinking_budget import (
    DEFAULT_RESEARCH_THINKING_BUDGET_CHARS,
    RESEARCH_THINKING_BUDGET_ENV,
    build_research_node_thinking_budget_block,
    build_research_thinking_budget_segment,
    is_workflow_scoped_experiment_binding,
    resolve_research_thinking_budget_chars,
)


def _load_chat_state(_project_root: object, _session_id: str):
    return None


def test_budget_defaults_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(RESEARCH_THINKING_BUDGET_ENV, raising=False)
    assert resolve_research_thinking_budget_chars() == 500


def test_budget_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(RESEARCH_THINKING_BUDGET_ENV, "800")
    assert resolve_research_thinking_budget_chars() == 800


def test_budget_env_invalid_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    for raw in ("", "abc", "0", "-50"):
        monkeypatch.setenv(RESEARCH_THINKING_BUDGET_ENV, raw)
        assert resolve_research_thinking_budget_chars() == DEFAULT_RESEARCH_THINKING_BUDGET_CHARS


def test_budget_env_extreme_value_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(RESEARCH_THINKING_BUDGET_ENV, "1000000")
    budget = resolve_research_thinking_budget_chars()
    assert 0 < budget <= 4000


def test_block_uses_hard_wording_with_budget() -> None:
    block = build_research_node_thinking_budget_block(500)
    assert "必须控制在 500 字以内" in block
    assert "快速决策，直接行动" in block
    # Quality fallback without reverse incentives.
    assert "不展开长篇推演" in block
    assert "充分思考" not in block and "深入分析" not in block


def test_workflow_scoped_binding_detection() -> None:
    assert (
        is_workflow_scoped_experiment_binding(
            {"workflowRunId": "run-1", "workflowNodeId": "node-2"}
        )
        is True
    )
    # Ordinary team-agent / user chat bindings lack the workflow scope.
    assert is_workflow_scoped_experiment_binding({}) is False
    assert is_workflow_scoped_experiment_binding({"workflowRunId": "run-1"}) is False
    assert is_workflow_scoped_experiment_binding({"workflowNodeId": "node-2"}) is False
    assert is_workflow_scoped_experiment_binding(None) is False


def test_segment_injected_for_research_node_session() -> None:
    conversation = {
        "experimentBinding": {
            "workflowRunId": "run-1",
            "workflowNodeId": "node-2",
        }
    }

    def loader(_project_root: object, _session_id: str):
        return conversation

    segment = build_research_thinking_budget_segment(
        "session-node",
        project_root=object(),
        load_chat_state=loader,
    )
    assert segment is not None
    assert segment["key"] == "research_thinking_budget"
    # cache_prefix keeps the instruction inside the static system context and
    # the worker appends it last for recency.
    assert segment["placement"] == "cache_prefix"
    assert "必须控制在 500 字以内" in segment["block"]


def test_segment_absent_for_ordinary_chat_session() -> None:
    segment = build_research_thinking_budget_segment(
        "session-chat",
        project_root=object(),
        load_chat_state=_load_chat_state,
    )
    assert segment is None


def test_segment_absent_for_team_agent_session_without_workflow_scope() -> None:
    conversation = {"experimentBinding": {"teamId": "team-1", "attempt": 1}}

    def loader(_project_root: object, _session_id: str):
        return conversation

    segment = build_research_thinking_budget_segment(
        "session-team",
        project_root=object(),
        load_chat_state=loader,
    )
    assert segment is None


def test_segment_survives_chat_state_load_failure() -> None:
    def loader(_project_root: object, _session_id: str):
        raise RuntimeError("chat state unavailable")

    segment = build_research_thinking_budget_segment(
        "session-broken",
        project_root=object(),
        load_chat_state=loader,
    )
    assert segment is None


def test_budget_segment_joins_into_static_cache_prefix_block() -> None:
    """cache_prefix placement keeps the instruction inside the static system block."""

    segments = [
        {"key": "agent_runtime", "block": "agent-runtime-block", "placement": "cache_prefix"},
        {"key": "agent_messages", "block": "volatile-block", "placement": "volatile_turn"},
    ]
    static_block = session_service._session_context_segments_block(segments, "cache_prefix")
    assert "agent-runtime-block" in static_block
    assert "volatile-block" not in static_block


def test_budget_segment_orders_after_prompt_snapshot_for_recency() -> None:
    """Worker wiring: snapshot inserted at head, budget appended at tail."""

    segments: list[dict[str, str]] = [
        {"key": "agent_runtime", "block": "runtime", "placement": "cache_prefix"},
        {"key": "research_organization", "block": "org", "placement": "cache_prefix"},
    ]
    prompt_snapshot_segment = {"key": "prompt_snapshot", "block": "snapshot", "placement": "cache_prefix"}
    research_thinking_budget_segment = {
        "key": "research_thinking_budget",
        "block": "budget-line",
        "placement": "cache_prefix",
    }
    # Mirrors the exact wiring in worker._run_session_turn_impl.
    segments.insert(0, prompt_snapshot_segment)
    segments.append(research_thinking_budget_segment)
    static_block = session_service._session_context_segments_block(segments, "cache_prefix")
    assert static_block.index("snapshot") < static_block.index("budget-line")
    assert static_block.rstrip().endswith("budget-line")


def test_worker_source_wires_budget_segment() -> None:
    """Guard the worker wiring: resolve per session, append last, before static join."""

    import inspect

    source = inspect.getsource(worker._run_session_turn_impl)
    assert "research_thinking_budget_segment = build_research_thinking_budget_segment(" in source
    assert (
        "runtime_context_segments.append(research_thinking_budget_segment)" in source
    )
    assert source.index("runtime_context_segments.append(research_thinking_budget_segment)") < source.index(
        'static_runtime_context_block = s._session_context_segments_block(runtime_context_segments, "cache_prefix")'
    )
