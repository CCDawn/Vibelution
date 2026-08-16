"""Focused tests for turn diagnostics that agent.py currently stubs away."""

from types import SimpleNamespace

from langchain_core.messages import HumanMessage, SystemMessage

from core.orchestration.turn_diagnostics import (
    build_llm_invocation_context,
    publish_llm_retry_status,
    record_turn_cache_diagnostics,
)


class _Bus:
    def __init__(self) -> None:
        self.events: list[tuple] = []

    def publish(self, name, payload, source=None):
        self.events.append((name, payload, source))


class _Ui:
    def __init__(self, *, snapshot=None, snapshot_error=False, note_error=False) -> None:
        self.notes: list[dict] = []
        self._snapshot = snapshot or {}
        self._snapshot_error = snapshot_error
        self._note_error = note_error

    def cache_average_snapshot(self):
        if self._snapshot_error:
            raise RuntimeError("snapshot failed")
        return self._snapshot

    def note_cache_diagnostics(self, **kwargs):
        if self._note_error:
            raise RuntimeError("persist failed")
        self.notes.append(kwargs)


def test_publish_llm_retry_status_skips_empty_and_publishes_reconnect_payload():
    bus = _Bus()
    publish_llm_retry_status(
        attempt=2,
        max_attempts=5,
        category="",
        action="",
        event_bus_getter=lambda: bus,
    )
    assert bus.events == []

    publish_llm_retry_status(
        attempt=2,
        max_attempts=5,
        category="network_error",
        action="retry_with_backoff",
        event_bus_getter=lambda: bus,
    )
    assert len(bus.events) == 1
    name, payload, source = bus.events[0]
    assert name == "llm:status"
    assert source == "SelfEvolvingAgent"
    assert payload["status"] == "retrying"
    assert payload["attempt"] == 2
    assert payload["max_attempts"] == 5
    assert payload["category"] == "network_error"
    assert payload["recovery_action"] == "retry_with_backoff"
    assert payload["source"] == "agent_outer_reconnect"


def test_publish_llm_retry_status_swallows_bus_failures():
    publish_llm_retry_status(
        attempt=1,
        max_attempts=3,
        category="timeout",
        action="retry",
        event_bus_getter=lambda: (_ for _ in ()).throw(RuntimeError("bus down")),
    )


def test_build_llm_invocation_context_falls_back_and_clamps_route_attempt():
    context = build_llm_invocation_context(
        runtime_binding={"agentId": "agent-1", "directSessionId": "session-from-binding", "llmSlot": ""},
        mode_value="chat",
        orchestrator_kind="chat",
        route_attempt=0,
        turn_runtime_fn=lambda: {},
        status_context_fn=lambda: {"turn_id": "turn-status"},
    )
    assert context.surface == "chat_turn"
    assert context.conversation_bound is True
    assert context.session_id == "session-from-binding"
    assert context.agent_id == "agent-1"
    assert context.llm_slot == "dialogue"
    assert context.metadata["routeAttempt"] == 1
    assert context.metadata["turnId"] == "turn-status"

    agent_context = build_llm_invocation_context(
        mode_value="self_evolution",
        orchestrator_kind="evolution",
        turn_runtime_fn=lambda: {"runKind": "supervised_case", "runId": "run-9"},
        status_context_fn=lambda: {},
    )
    assert agent_context.surface == "agent_turn"
    assert agent_context.run_kind == "supervised_case"
    assert agent_context.run_id == "run-9"
    assert agent_context.conversation_bound is False


def test_record_turn_cache_diagnostics_notes_usage_and_survives_ui_errors():
    token_usage = SimpleNamespace(
        observed=True,
        input_tokens=120,
        output_tokens=8,
        total_tokens=128,
        cached_input_tokens=40,
        cache_creation_input_tokens=0,
        uncached_input_tokens=80,
    )
    response = SimpleNamespace(response_metadata={"provider": "openai", "model": "gpt-test"})
    messages = [SystemMessage(content="system prompt"), HumanMessage(content="hello")]
    ui = _Ui()

    llm_usage, metadata = record_turn_cache_diagnostics(
        token_usage=token_usage,
        response=response,
        messages=messages,
        current_turn=7,
        context_window_limit=8000,
        get_ui_fn=lambda: ui,
        turn_runtime_fn=lambda: {
            "sessionId": "s1",
            "runId": "t7",
            "promptCachePartition": "part-secret",
        },
    )

    assert llm_usage["source"] == "provider_usage"
    assert llm_usage["inputTokens"] == 120
    assert llm_usage["cachedInputTokens"] == 40
    assert llm_usage["promptCachePartition"] == "part-secret"
    assert metadata["context_composition"]["limitTokens"] == 8000
    assert metadata["cache_composition"]["source"] == "provider_usage"
    assert ui.notes and ui.notes[0]["llm_usage"]["cachedInputTokens"] == 40

    failing_ui = _Ui(snapshot_error=True, note_error=True)
    usage, metadata = record_turn_cache_diagnostics(
        token_usage=token_usage,
        response=response,
        messages=messages,
        current_turn=7,
        context_window_limit="not-a-number",
        get_ui_fn=lambda: failing_ui,
        turn_runtime_fn=lambda: {},
    )
    assert usage["source"] == "provider_usage"
    assert metadata["context_composition"]["limitTokens"] == 0
    assert failing_ui.notes == []
