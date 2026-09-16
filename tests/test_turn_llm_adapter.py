from types import SimpleNamespace

import json

import pytest
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from agent import AgentRuntime, TurnStopRequested
from core.infrastructure.llm_utils import MAX_CONSECUTIVE_FAILURES
from core.infrastructure.runtime_input import build_chat_user_message
from core.llm import LLMError
from core.llm.recovery import plan_recovery
from core.llm.semantic_messages import SemanticOutputSchema
from core.llm.types import CanonicalItemIdentity, TurnOutcome
from core.orchestration.turn_llm_adapter import (
    AgentLlmTurnHooks,
    invoke_agent_llm_turn,
    sanitize_llm_turn_messages,
)


def _identity() -> CanonicalItemIdentity:
    return CanonicalItemIdentity(
        session_id="session-test",
        turn_id="turn-test",
        invocation_id="invocation-test",
        iteration=0,
        item_id="answer-test",
    )


class _DummyContext:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _DummyUI:
    def thinking(self, _label):
        return _DummyContext()

    def add_log(self, *_args, **_kwargs):
        return None


def test_sanitize_llm_turn_messages_preserves_tool_and_cache_blocks():
    assistant = AIMessage(content="calling tool", tool_calls=[{"id": "call_1", "name": "read_file_tool", "args": {}}])
    tool = ToolMessage(content="file content", tool_call_id="call_1")
    system = {
        "role": "system",
        "content": [
            {"type": "text", "text": "stable", "cache_control": {"type": "ephemeral"}},
        ],
    }
    cleaned = sanitize_llm_turn_messages(
        [assistant, tool, SystemMessage(content="plain"), system, build_chat_user_message("hi")]
    )
    assert cleaned[0] is assistant
    assert cleaned[1] is tool
    assert isinstance(cleaned[2], SystemMessage)
    assert cleaned[2].content == "plain"
    assert cleaned[3] == system
    assert cleaned[3]["content"][0]["cache_control"] == {"type": "ephemeral"}


def test_adapter_routes_network_calls_through_injected_invocation():
    calls = []

    class DummyLLM:
        profile_id = "primary"

        def effective_route_identity(self):
            return ("primary",)

        def effective_route_id(self):
            return "primary-route"

        def project_outcome_message(self, outcome, **_kwargs):
            return AIMessage(content=outcome.final_text)

        def invoke_outcome(self, *_args, **_kwargs):
            raise AssertionError("adapter must not call client.invoke_outcome directly")

    def invoke_outcome(client, messages, **_kwargs):
        calls.append((client, messages))
        return TurnOutcome.final_answer(identity=_identity(), text="ok")

    hooks = AgentLlmTurnHooks(
        get_ui=lambda: _DummyUI(),
        llm_cancel_context=lambda _checker: _DummyContext(),
        raise_if_stop=lambda: None,
        current_stop_reason=lambda: "",
        get_llm_for_mode=lambda **_kwargs: DummyLLM(),
        should_stream=lambda *_args, **_kwargs: False,
        build_invocation_context=lambda **_kwargs: SimpleNamespace(
            to_metadata=lambda client=None: {"invocationId": "inv-1"}
        ),
        invoke_outcome=invoke_outcome,
        run_streaming_outcome=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("non-stream path must not stream")
        ),
        canonicalize=lambda outcome: outcome,
        plan_recovery=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("success path must not recover")
        ),
        record_scene_event=lambda *_args, **_kwargs: None,
        record_route_success=lambda **_kwargs: None,
        request_compression=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("success path must not compress")
        ),
        debug_logger=SimpleNamespace(error=lambda *_args, **_kwargs: None),
        error_logger=SimpleNamespace(log_error=lambda *_args, **_kwargs: None),
        config=None,
        force_disable_tools=False,
        stop_error_cls=TurnStopRequested,
    )
    result = invoke_agent_llm_turn(messages=[AIMessage(content="hello")], hooks=hooks)
    assert result.payload[1].content == "ok"
    assert calls and calls[0][0].profile_id == "primary"

def test_adapter_fails_route_without_switching_profiles_on_retryable_error():
    calls = []

    class PrimaryLLM:
        profile_id = "primary"

        def effective_route_identity(self):
            return ("relay", "primary")

        def effective_route_id(self):
            return "primary-route"

        def project_outcome_message(self, outcome, **_kwargs):
            return AIMessage(content=outcome.final_text)

    def invoke_outcome(client, _messages, **_kwargs):
        calls.append(client.profile_id)
        raise LLMError(
            "server_error",
            "provider 服务异常",
            retryable=True,
            details={"attempt": 5, "max_attempts": 5, "retry_budget_exhausted": True},
        )

    seen_recovery_kwargs = []

    def plan_recovery(_error, **kwargs):
        seen_recovery_kwargs.append(set(kwargs))
        return SimpleNamespace(
            category="server_error",
            retryable=True,
            action="retry_with_backoff",
            user_message="provider 服务异常",
            wait_seconds=0,
            stop_current_turn=True,
            disable_streaming=False,
            disable_tools=False,
            request_context_compression=False,
        )

    hooks = AgentLlmTurnHooks(
        get_ui=lambda: _DummyUI(),
        llm_cancel_context=lambda _checker: _DummyContext(),
        raise_if_stop=lambda: None,
        current_stop_reason=lambda: "",
        get_llm_for_mode=lambda **_kwargs: PrimaryLLM(),
        should_stream=lambda *_args, **_kwargs: False,
        build_invocation_context=lambda **_kwargs: SimpleNamespace(
            to_metadata=lambda client=None: {
                "invocationId": f"inv-{getattr(client, 'profile_id', '')}",
                "sessionId": "session-a",
                "turnId": "turn-a",
                "llmRunId": "run-a",
                "agentId": "agent-a",
            }
        ),
        invoke_outcome=invoke_outcome,
        run_streaming_outcome=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("non-stream path must not stream")
        ),
        canonicalize=lambda outcome: outcome,
        plan_recovery=plan_recovery,
        record_scene_event=lambda *_args, **_kwargs: None,
        record_route_success=lambda **_kwargs: None,
        request_compression=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("route failure must not compress")
        ),
        debug_logger=SimpleNamespace(error=lambda *_args, **_kwargs: None),
        error_logger=SimpleNamespace(log_error=lambda *_args, **_kwargs: None),
        config=SimpleNamespace(llm=SimpleNamespace(model_name="m", provider="relay", api_base="", api_timeout=30)),
        force_disable_tools=False,
        stop_error_cls=TurnStopRequested,
        base_llm=PrimaryLLM(),
    )
    result = invoke_agent_llm_turn(messages=[AIMessage(content="hello")], hooks=hooks)
    assert calls == ["primary"]
    assert seen_recovery_kwargs == [{"attempt", "max_attempts"}]
    assert result.payload is None
    assert result.last_error_category == "server_error"
    assert result.last_failure_attempts == 5




def test_agent_wrapper_writes_failure_diagnostics(monkeypatch):
    import agent as agent_module

    class DummyLLM:
        profile_id = "primary"

        def effective_route_identity(self):
            return ("primary",)

        def effective_route_id(self):
            return "primary-route"

        def invoke_outcome(self, *_args, **_kwargs):
            raise LLMError("server_error", "boom", retryable=False, details={"attempt": 1, "max_attempts": 1})

    monkeypatch.setattr(agent_module, "get_ui", lambda: _DummyUI())
    monkeypatch.setattr(
        agent_module,
        "plan_llm_recovery",
        lambda *_args, **_kwargs: SimpleNamespace(
            category="server_error",
            retryable=False,
            action="stop",
            user_message="boom",
            wait_seconds=0,
            stop_current_turn=True,
            disable_streaming=False,
            disable_tools=False,
            request_context_compression=False,
        ),
    )
    monkeypatch.setattr(agent_module.logger, "log_error", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(agent_module, "_record_agent_scene_event", lambda *_args, **_kwargs: None)

    agent = AgentRuntime.__new__(AgentRuntime)
    agent.llm_with_tools = DummyLLM()
    agent._base_llm = DummyLLM()
    agent.config = SimpleNamespace(llm=SimpleNamespace(model_name="m", provider="relay", api_base="", api_timeout=30))
    agent._should_stream_llm_for_turn = lambda *_args, **_kwargs: False
    agent._get_llm_for_current_mode = lambda **_kwargs: DummyLLM()
    agent._build_llm_invocation_context = lambda **_kwargs: SimpleNamespace(
        to_metadata=lambda client=None: {"invocationId": "inv-1"}
    )

    assert agent._invoke_llm([AIMessage(content="hello")]) is None
    assert agent._last_llm_error_category == "server_error"
    assert agent._last_llm_error_retryable is False
    assert agent._last_llm_failure_max_attempts >= 1
    assert agent._last_llm_failure_attempts == 1
    assert MAX_CONSECUTIVE_FAILURES >= 1


def test_agent_wrapper_clears_stale_diagnostics_before_stop(monkeypatch):
    import agent as agent_module

    def stop_before_result(**_kwargs):
        raise TurnStopRequested("operator stopped the turn")

    monkeypatch.setattr(agent_module, "invoke_agent_llm_turn", stop_before_result)

    agent = AgentRuntime.__new__(AgentRuntime)
    agent._last_llm_error_category = "server_error"
    agent._last_llm_error_retryable = True
    agent._last_llm_recovery_action = "retry_with_backoff"
    agent._last_llm_error_message = "stale failure"
    agent._last_llm_error_details = {"exception_type": "StaleError"}
    agent._last_llm_failure_attempts = 5
    agent._last_llm_failure_max_attempts = 5

    with pytest.raises(TurnStopRequested, match="operator stopped the turn"):
        agent._invoke_llm([AIMessage(content="hello")])

    assert agent._last_llm_error_category is None
    assert agent._last_llm_error_retryable is False
    assert agent._last_llm_recovery_action is None
    assert agent._last_llm_error_message == ""
    assert agent._last_llm_error_details == {}
    assert agent._last_llm_failure_attempts == 0
    assert agent._last_llm_failure_max_attempts == MAX_CONSECUTIVE_FAILURES


def _recovery(**overrides):
    payload = dict(
        category="server_error",
        retryable=False,
        action="stop",
        user_message="boom",
        wait_seconds=0,
        stop_current_turn=True,
        disable_streaming=False,
        disable_tools=False,
        request_context_compression=False,
    )
    payload.update(overrides)
    return SimpleNamespace(**payload)


def _route_llm(profile_id: str, *, identity=None, route_id=None, fallback: str = ""):
    class RouteLLM:
        def __init__(self):
            self.profile_id = profile_id
            self.profile = SimpleNamespace(fallback=fallback)

        def effective_route_identity(self):
            return identity if identity is not None else (profile_id,)

        def effective_route_id(self):
            return route_id or f"{profile_id}-route"

        def project_outcome_message(self, outcome, **_kwargs):
            return AIMessage(content=outcome.final_text)

    return RouteLLM()


def _adapter_hooks(**overrides):
    defaults = dict(
        get_ui=lambda: _DummyUI(),
        llm_cancel_context=lambda _checker: _DummyContext(),
        raise_if_stop=lambda: None,
        current_stop_reason=lambda: "",
        get_llm_for_mode=lambda **_kwargs: _route_llm("primary"),
        should_stream=lambda *_args, **_kwargs: False,
        build_invocation_context=lambda **_kwargs: SimpleNamespace(
            to_metadata=lambda client=None: {"invocationId": "inv-1"}
        ),
        invoke_outcome=lambda *_args, **_kwargs: TurnOutcome.final_answer(identity=_identity(), text="ok"),
        run_streaming_outcome=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("non-stream path must not stream")
        ),
        canonicalize=lambda outcome: outcome,
        plan_recovery=lambda *_args, **_kwargs: _recovery(),
        record_scene_event=lambda *_args, **_kwargs: None,
        record_route_success=lambda **_kwargs: None,
        request_compression=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("must not compress")
        ),
        debug_logger=SimpleNamespace(error=lambda *_args, **_kwargs: None),
        error_logger=SimpleNamespace(log_error=lambda *_args, **_kwargs: None),
        config=None,
        force_disable_tools=False,
        stop_error_cls=TurnStopRequested,
    )
    defaults.update(overrides)
    return AgentLlmTurnHooks(**defaults)


def test_adapter_coerces_invalid_error_attempt_counters_and_non_mapping_details():
    def invoke_outcome(*_args, **_kwargs):
        raise LLMError(
            "server_error",
            "boom",
            retryable=False,
            details={"attempt": "bad", "max_attempts": "nope"},
        )

    result = invoke_agent_llm_turn(
        messages=[AIMessage(content="hello")],
        hooks=_adapter_hooks(invoke_outcome=invoke_outcome),
    )
    assert result.payload is None
    assert result.last_failure_attempts == 1
    assert result.last_failure_max_attempts == 1

    def invoke_non_mapping_details(*_args, **_kwargs):
        raise LLMError("server_error", "boom", retryable=False, details="not-a-mapping")

    result = invoke_agent_llm_turn(
        messages=[AIMessage(content="hello")],
        hooks=_adapter_hooks(invoke_outcome=invoke_non_mapping_details),
    )
    assert result.payload is None
    assert result.last_failure_attempts == 1
    assert result.last_error_details["exception_type"] == "LLMError"


def test_adapter_stops_for_context_compression_without_fallback():
    llm_calls = []
    compress_calls = []

    primary = _route_llm("primary", identity=("relay", "primary"))

    def invoke_outcome(client, *_args, **_kwargs):
        llm_calls.append(client.profile_id)
        raise LLMError(
            "context_length_error",
            "too long",
            retryable=True,
            details={"attempt": 1, "max_attempts": 1},
        )

    def get_llm_for_mode(**_kwargs):
        return primary

    result = invoke_agent_llm_turn(
        messages=[AIMessage(content="hello")],
        hooks=_adapter_hooks(
            get_llm_for_mode=get_llm_for_mode,
            invoke_outcome=invoke_outcome,
            plan_recovery=lambda *_args, **_kwargs: _recovery(
                category="context_length_error",
                retryable=True,
                action="compress_context",
                user_message="too long",
                request_context_compression=True,
            ),
            request_compression=lambda reason, *, source="manual": compress_calls.append(
                (reason, source)
            ),
        ),
    )
    assert result.payload is None
    assert llm_calls == ["primary"]
    assert compress_calls
    assert compress_calls[0][1] == "provider_limit"
    assert result.last_error_category == "context_length_error"
    assert result.last_recovery_action == "compress_context"


def test_adapter_invokes_when_streaming_requested_but_client_has_no_stream():
    calls = []

    def invoke_outcome(client, messages, **_kwargs):
        calls.append((client.profile_id, messages))
        return TurnOutcome.final_answer(identity=_identity(), text="ok")

    result = invoke_agent_llm_turn(
        messages=[AIMessage(content="hello")],
        hooks=_adapter_hooks(
            should_stream=lambda *_args, **_kwargs: True,
            invoke_outcome=invoke_outcome,
        ),
    )
    assert result.payload[1].content == "ok"
    assert calls and calls[0][0] == "primary"


def test_adapter_forwards_and_validates_strict_structured_output():
    received = []

    def validator(payload):
        if payload.get("taskKind") != "hypothesis_design":
            raise ValueError("wrong task kind")

    contract = SemanticOutputSchema(
        name="research_hypothesis_design_v1",
        schema={"type": "object"},
        validator=validator,
    )

    def invoke_outcome(_client, _messages, **kwargs):
        received.append(kwargs.get("output_schema"))
        return TurnOutcome.final_answer(
            identity=_identity(),
            text='{"taskKind":"hypothesis_design","reasoning":"bounded"}',
        )

    result = invoke_agent_llm_turn(
        messages=[AIMessage(content="hello")],
        hooks=_adapter_hooks(
            invoke_outcome=invoke_outcome,
            structured_output_contract=contract,
        ),
    )

    assert received == [contract]
    assert result.payload[0].kind == "final_answer"

def test_adapter_coerces_false_flags_and_json_error_details():
    llm_calls = []
    seen_disable = []

    primary = _route_llm("primary", identity=("relay", "primary"))

    def invoke_outcome(client, *_args, **_kwargs):
        llm_calls.append(client.profile_id)
        raise LLMError(
            "server_error",
            "boom",
            retryable=True,
            details='{"attempt":"1","max_attempts":"5","retry_budget_exhausted":"false"}',
        )

    def get_llm_for_mode(**kwargs):
        seen_disable.append(kwargs.get("disable_tools"))
        return primary

    result = invoke_agent_llm_turn(
        messages=[AIMessage(content="hello")],
        hooks=_adapter_hooks(
            get_llm_for_mode=get_llm_for_mode,
            invoke_outcome=invoke_outcome,
            force_disable_tools="false",
            plan_recovery=lambda *_args, **_kwargs: _recovery(
                category="server_error",
                retryable="true",
                action="retry_with_backoff",
                user_message="boom",
                stop_current_turn="false",
                request_context_compression="false",
            ),
        ),
    )
    assert llm_calls == ["primary"]
    assert result.payload is None
    assert result.last_failure_attempts == 1
    assert result.last_failure_max_attempts == 5
    assert result.last_error_details["provider_stream_retry_exhausted"] is False
    assert seen_disable == [False]



def test_adapter_fails_closed_when_structured_output_is_invalid():
    contract = SemanticOutputSchema(
        name="research_result_evaluation_v1",
        schema={"type": "object"},
        validator=lambda payload: (_ for _ in ()).throw(ValueError("invalid result")),
    )

    result = invoke_agent_llm_turn(
        messages=[AIMessage(content="hello")],
        hooks=_adapter_hooks(
            invoke_outcome=lambda *_args, **_kwargs: TurnOutcome.final_answer(
                identity=_identity(),
                text='{"taskKind":"result_evaluation"}',
            ),
            structured_output_contract=contract,
            plan_recovery=lambda *_args, **_kwargs: _recovery(
                category="structured_output_validation_error",
                retryable=False,
                action="stop",
                user_message="invalid structured output",
            ),
        ),
    )

    assert result.payload is None
    assert result.last_error_category == "structured_output_validation_error"


def test_sanitize_llm_turn_messages_rejects_character_split_and_decodes_system_role():
    assert sanitize_llm_turn_messages("abc") == []
    cleaned = sanitize_llm_turn_messages(
        '[{"role":"system","content":[{"type":"text","text":"stable"}]}]'
    )
    assert cleaned[0]["role"] == "system"
    bytes_role = sanitize_llm_turn_messages([{"role": b"system", "content": "plain"}])
    assert bytes_role[0]["role"] == b"system"
    assert bytes_role[0]["content"] == "plain"



def test_adapter_keeps_fail_fast_when_no_fallback_is_declared():
    """Explicit-switch contract: no declaration means today's fail-fast path."""

    llm_calls = []
    events = []
    primary = _route_llm("primary", identity=("relay", "primary"))

    def invoke_outcome(client, *_args, **_kwargs):
        llm_calls.append(client.profile_id)
        raise LLMError(
            "server_error", "boom", retryable=True, details={"attempt": 5, "max_attempts": 5}
        )

    result = invoke_agent_llm_turn(
        messages=[AIMessage(content="hello")],
        hooks=_adapter_hooks(
            get_llm_for_mode=lambda **_kwargs: primary,
            invoke_outcome=invoke_outcome,
            plan_recovery=lambda *_args, **_kwargs: _recovery(
                category="server_error",
                retryable=True,
                action="retry_with_backoff",
                stop_current_turn=True,
                user_message="boom",
            ),
            record_scene_event=lambda _module, event, **kwargs: events.append(
                (event, kwargs.get("fields") or {})
            ),
        ),
    )
    assert llm_calls == ["primary"]
    assert result.payload is None
    assert result.route_fallback == {}
    assert result.last_error_retryable is True
    assert not any(event == "llm_route_fallback_switched" for event, _fields in events)
    assert any(event == "llm_turn_terminal" for event, _fields in events)


def test_adapter_does_not_switch_on_permanent_failure_even_when_declared():
    llm_calls = []
    events = []
    primary = _route_llm("primary", identity=("relay", "primary"), fallback="backup_qwen")

    def invoke_outcome(client, *_args, **_kwargs):
        llm_calls.append(client.profile_id)
        raise LLMError(
            "auth_error", "bad key", retryable=False, details={"attempt": 1, "max_attempts": 1}
        )

    result = invoke_agent_llm_turn(
        messages=[AIMessage(content="hello")],
        hooks=_adapter_hooks(
            get_llm_for_mode=lambda **_kwargs: primary,
            invoke_outcome=invoke_outcome,
            plan_recovery=lambda *_args, **_kwargs: _recovery(
                category="auth_error",
                retryable="false",
                action="fail_fast",
                stop_current_turn=True,
                user_message="bad key",
            ),
            record_scene_event=lambda _module, event, **kwargs: events.append(
                (event, kwargs.get("fields") or {})
            ),
        ),
    )
    assert llm_calls == ["primary"]
    assert result.payload is None
    assert result.last_error_category == "auth_error"
    assert result.last_error_retryable is False
    assert result.route_fallback == {}
    assert not any(event == "llm_route_fallback_switched" for event, _fields in events)


def test_adapter_does_not_switch_before_retry_budget_is_exhausted():
    llm_calls = []
    events = []
    primary = _route_llm("primary", identity=("relay", "primary"), fallback="backup_qwen")

    def invoke_outcome(client, *_args, **_kwargs):
        llm_calls.append(client.profile_id)
        raise LLMError(
            "server_error", "boom", retryable=True, details={"attempt": 2, "max_attempts": 5}
        )

    result = invoke_agent_llm_turn(
        messages=[AIMessage(content="hello")],
        hooks=_adapter_hooks(
            get_llm_for_mode=lambda **_kwargs: primary,
            invoke_outcome=invoke_outcome,
            plan_recovery=lambda *_args, **_kwargs: _recovery(
                category="server_error",
                retryable=True,
                action="retry_with_backoff",
                stop_current_turn=False,
                user_message="boom",
            ),
            record_scene_event=lambda _module, event, **kwargs: events.append(
                (event, kwargs.get("fields") or {})
            ),
        ),
    )
    assert llm_calls == ["primary"]
    assert result.payload is None
    assert result.last_error_details["provider_stream_retry_exhausted"] is False
    assert not any(event == "llm_route_fallback_switched" for event, _fields in events)


def test_adapter_switches_once_to_declared_fallback_and_emits_event():
    llm_calls = []
    profile_requests = []
    route_attempts = []
    success_traces = []
    events = []
    primary = _route_llm("primary", identity=("relay", "primary"), fallback="backup_qwen")
    backup = _route_llm("backup_qwen", identity=("dashscope", "backup_qwen"))

    def get_llm_for_mode(**kwargs):
        profile_requests.append(kwargs.get("profile_id"))
        return primary if len(profile_requests) == 1 else backup

    def invoke_outcome(client, *_args, **_kwargs):
        llm_calls.append(client.profile_id)
        if client.profile_id == "primary":
            raise LLMError(
                "server_error",
                "gateway down",
                retryable=True,
                details={"attempt": 5, "max_attempts": 5},
            )
        return TurnOutcome.final_answer(identity=_identity(), text="rescued")

    def build_invocation_context(**kwargs):
        route_attempts.append(kwargs.get("route_attempt"))
        metadata = {
            "sessionId": "sess-1",
            "turnId": "turn-9",
            "invocationId": f"inv-{kwargs.get('route_attempt')}",
        }
        return SimpleNamespace(
            metadata=metadata,
            to_metadata=lambda client=None: dict(metadata),
        )

    result = invoke_agent_llm_turn(
        messages=[AIMessage(content="hello")],
        hooks=_adapter_hooks(
            get_llm_for_mode=get_llm_for_mode,
            invoke_outcome=invoke_outcome,
            build_invocation_context=build_invocation_context,
            plan_recovery=lambda *_args, **_kwargs: _recovery(
                category="server_error",
                retryable=True,
                action="retry_with_backoff",
                stop_current_turn=True,
                user_message="gateway down",
            ),
            record_scene_event=lambda _module, event, **kwargs: events.append(
                (event, kwargs.get("fields") or {})
            ),
            record_route_success=lambda **kwargs: success_traces.append(kwargs),
        ),
    )
    assert llm_calls == ["primary", "backup_qwen"]
    assert profile_requests == [None, "backup_qwen"]
    assert route_attempts == [1, 2]
    assert result.payload is not None
    assert result.payload[1].content == "rescued"
    assert result.route_fallback == {"from": "primary", "to": "backup_qwen"}
    switched = [fields for event, fields in events if event == "llm_route_fallback_switched"]
    assert len(switched) == 1
    assert switched[0]["from"] == "primary"
    assert switched[0]["to"] == "backup_qwen"
    assert switched[0]["reason"] == "server_error"
    assert switched[0]["attempt"] == 1
    assert success_traces and success_traces[0]["trace_fields"]["routeAttempt"] == 2
    # Persistence is no longer an adapter concern: the durable llm_resilience
    # journal write happens in the scene-event binding layer and is covered by
    # tests/test_llm_resilience_journal.py. The in-memory route fallback
    # registry was removed; only the scene event contract remains here.
    switched_fields = switched[0]
    assert switched_fields["sessionId"] == "sess-1"
    assert switched_fields["turnId"] == "turn-9"


def test_adapter_single_hop_caps_the_fallback_chain():
    llm_calls = []
    events = []
    profile_requests = []
    primary = _route_llm("primary", identity=("relay", "primary"), fallback="backup_qwen")
    backup = _route_llm("backup_qwen", identity=("dashscope", "backup_qwen"), fallback="primary")

    def get_llm_for_mode(**kwargs):
        profile_requests.append(kwargs.get("profile_id"))
        return primary if len(profile_requests) == 1 else backup

    def invoke_outcome(client, *_args, **_kwargs):
        llm_calls.append(client.profile_id)
        raise LLMError(
            "server_error", "boom", retryable=True, details={"attempt": 5, "max_attempts": 5}
        )

    result = invoke_agent_llm_turn(
        messages=[AIMessage(content="hello")],
        hooks=_adapter_hooks(
            get_llm_for_mode=get_llm_for_mode,
            invoke_outcome=invoke_outcome,
            plan_recovery=lambda *_args, **_kwargs: _recovery(
                category="server_error",
                retryable=True,
                action="retry_with_backoff",
                stop_current_turn=True,
                user_message="boom",
            ),
            record_scene_event=lambda _module, event, **kwargs: events.append(
                (event, kwargs.get("fields") or {})
            ),
        ),
    )
    assert llm_calls == ["primary", "backup_qwen"]
    assert result.payload is None
    assert len([1 for event, _f in events if event == "llm_route_fallback_switched"]) == 1
    terminal = [fields for event, fields in events if event == "llm_turn_terminal"]
    assert terminal and terminal[0]["routeAttempts"] == 2
    assert terminal[0]["routeFallback"] == {"from": "primary", "to": "backup_qwen"}


def test_sanitize_llm_turn_messages_unwraps_history_envelope():
    cleaned = sanitize_llm_turn_messages(
        b'{"messages": [{"role": "system", "content": "stable"}]}'
    )
    assert cleaned[0]["role"] == "system"
    assert cleaned[0]["content"] == "stable"
    assert sanitize_llm_turn_messages("not-a-history") == []


def test_adapter_parses_camelcase_error_details_without_treating_true_as_attempt_one():
    def invoke_camel(*_args, **_kwargs):
        raise LLMError(
            "server_error",
            "boom",
            retryable=False,
            details='{"attempt": 2, "maxAttempts": 5, "retryBudgetExhausted": "false"}',
        )

    camel = invoke_agent_llm_turn(
        messages=[AIMessage(content="hello")],
        hooks=_adapter_hooks(
            invoke_outcome=invoke_camel,
            build_invocation_context=lambda **_kwargs: SimpleNamespace(
                metadata=b'{"invocationId": "inv-json"}',
                to_metadata=lambda client=None: {"invocationId": "other"},
            ),
        ),
    )
    assert camel.last_failure_attempts == 2
    assert camel.last_failure_max_attempts == 5
    assert camel.last_error_details["provider_stream_retry_exhausted"] is False
    assert camel.last_error_details["invocation_id"] == "inv-json"

    def invoke_true_attempt(*_args, **_kwargs):
        raise LLMError(
            "server_error",
            "boom",
            retryable=False,
            details={"attempt": True, "max_attempts": 5},
        )

    truthy = invoke_agent_llm_turn(
        messages=[AIMessage(content="hello")],
        hooks=_adapter_hooks(invoke_outcome=invoke_true_attempt),
    )
    assert truthy.last_failure_attempts == 0
    assert truthy.last_error_details["provider_stream_retry_exhausted"] is False


# --- attempt-level degradation dispatch (core/llm/recovery.py actions) -------
# These tests bind the REAL plan_recovery so the adapter's dispatch stays
# locked to the single-source action mapping in core/llm/recovery.py.


def _empty_content_error() -> LLMError:
    return LLMError("empty_content_error", "chat content is empty", retryable=False)


def _tool_protocol_error() -> LLMError:
    return LLMError(
        "tool_protocol_error",
        "invalid params, duplicate tool_call id: call_1",
        retryable=False,
    )


def test_adapter_degrades_empty_content_to_single_non_streaming_retry():
    """(a) empty_content -> one same-profile non-streaming retry keeps the turn alive."""
    streaming_calls = []
    invoke_calls = []
    llm_requests = []
    events = []
    primary = _route_llm("primary", identity=("relay", "primary"))
    primary.stream = True

    def get_llm_for_mode(**kwargs):
        llm_requests.append((kwargs.get("disable_tools"), kwargs.get("profile_id")))
        return primary

    def run_streaming_outcome(*_args, **_kwargs):
        streaming_calls.append(1)
        raise _empty_content_error()

    def invoke_outcome(*_args, **_kwargs):
        invoke_calls.append(1)
        return TurnOutcome.final_answer(identity=_identity(), text="recovered")

    result = invoke_agent_llm_turn(
        messages=[AIMessage(content="hello")],
        hooks=_adapter_hooks(
            get_llm_for_mode=get_llm_for_mode,
            should_stream=lambda *_args, **_kwargs: True,
            run_streaming_outcome=run_streaming_outcome,
            invoke_outcome=invoke_outcome,
            plan_recovery=plan_recovery,
            record_scene_event=lambda _module, event, **kwargs: events.append(
                (event, kwargs.get("fields") or {})
            ),
        ),
    )
    assert streaming_calls == [1]
    assert invoke_calls == [1]
    assert llm_requests == [(False, None), (False, None)]
    assert result.payload is not None
    assert result.payload[1].content == "recovered"
    assert result.degraded_actions == ["retry_without_streaming"]
    degraded = [fields for event, fields in events if event == "llm_route_degraded_retry"]
    assert len(degraded) == 1
    assert degraded[0]["action"] == "retry_without_streaming"
    assert degraded[0]["fromCategory"] == "empty_content_error"
    assert degraded[0]["routeAttempt"] == 1
    assert degraded[0]["attempt"] == 2
    assert degraded[0]["profileId"] == "primary"


def test_adapter_degrades_tool_protocol_to_tools_off_non_streaming_retry():
    """(b) tool_protocol -> one same-profile tools-off non-streaming retry."""
    llm_requests = []
    events = []
    primary = _route_llm("primary", identity=("relay", "primary"))
    primary.stream = True

    def get_llm_for_mode(**kwargs):
        llm_requests.append(kwargs.get("disable_tools"))
        return primary

    def run_streaming_outcome(*_args, **_kwargs):
        raise _tool_protocol_error()

    def invoke_outcome(*_args, **_kwargs):
        return TurnOutcome.final_answer(identity=_identity(), text="plain text answer")

    result = invoke_agent_llm_turn(
        messages=[AIMessage(content="hello")],
        hooks=_adapter_hooks(
            get_llm_for_mode=get_llm_for_mode,
            should_stream=lambda *_args, **_kwargs: True,
            run_streaming_outcome=run_streaming_outcome,
            invoke_outcome=invoke_outcome,
            plan_recovery=plan_recovery,
            record_scene_event=lambda _module, event, **kwargs: events.append(
                (event, kwargs.get("fields") or {})
            ),
        ),
    )
    assert llm_requests == [False, True]
    assert result.payload is not None
    assert result.payload[1].content == "plain text answer"
    assert result.degraded_actions == ["disable_tools_and_retry_without_streaming"]
    degraded = [fields for event, fields in events if event == "llm_route_degraded_retry"]
    assert len(degraded) == 1
    assert degraded[0]["action"] == "disable_tools_and_retry_without_streaming"
    assert degraded[0]["fromCategory"] == "tool_protocol_error"
    assert degraded[0]["streamingDisabled"] is True
    assert degraded[0]["toolsDisabled"] is True


def test_adapter_degraded_retry_does_not_loop():
    """(c) each degradation action fires at most once per turn, then terminal."""
    streaming_calls = []
    invoke_calls = []
    events = []
    primary = _route_llm("primary", identity=("relay", "primary"))
    primary.stream = True

    def run_streaming_outcome(*_args, **_kwargs):
        streaming_calls.append(1)
        raise _empty_content_error()

    def invoke_outcome(*_args, **_kwargs):
        invoke_calls.append(1)
        raise _empty_content_error()

    result = invoke_agent_llm_turn(
        messages=[AIMessage(content="hello")],
        hooks=_adapter_hooks(
            get_llm_for_mode=lambda **_kwargs: primary,
            should_stream=lambda *_args, **_kwargs: True,
            run_streaming_outcome=run_streaming_outcome,
            invoke_outcome=invoke_outcome,
            plan_recovery=plan_recovery,
            record_scene_event=lambda _module, event, **kwargs: events.append(
                (event, kwargs.get("fields") or {})
            ),
        ),
    )
    assert streaming_calls == [1]
    assert invoke_calls == [1]
    assert result.payload is None
    assert result.degraded_actions == ["retry_without_streaming"]
    assert len([1 for event, _f in events if event == "llm_route_degraded_retry"]) == 1
    terminal = [fields for event, fields in events if event == "llm_turn_terminal"]
    assert terminal and terminal[0]["routeAttempts"] == 2


def test_adapter_degrades_before_declared_fallback_switch():
    """(d) priority: same-profile degraded retry first, declared fallback only after."""
    streaming_calls = []
    invoke_calls = []
    llm_requests = []
    route_attempts = []
    events = []
    primary = _route_llm("primary", identity=("relay", "primary"), fallback="backup_qwen")
    primary.stream = True
    backup = _route_llm("backup_qwen", identity=("dashscope", "backup_qwen"))
    backup.stream = True

    def get_llm_for_mode(**kwargs):
        llm_requests.append((kwargs.get("disable_tools"), kwargs.get("profile_id")))
        return primary if kwargs.get("profile_id") is None else backup

    def run_streaming_outcome(llm, *_args, **_kwargs):
        streaming_calls.append(llm.profile_id)
        if llm.profile_id == "primary":
            raise _empty_content_error()
        return TurnOutcome.final_answer(identity=_identity(), text="rescued")

    def invoke_outcome(client, *_args, **_kwargs):
        invoke_calls.append(client.profile_id)
        raise LLMError(
            "server_error",
            "gateway down",
            retryable=True,
            details={"attempt": 5, "max_attempts": 5, "retry_budget_exhausted": True},
        )

    def build_invocation_context(**kwargs):
        route_attempts.append(kwargs.get("route_attempt"))
        metadata = {
            "sessionId": "sess-degrade",
            "turnId": "turn-1",
            "invocationId": f"inv-{kwargs.get('route_attempt')}",
        }
        return SimpleNamespace(
            metadata=metadata,
            to_metadata=lambda client=None: dict(metadata),
        )

    result = invoke_agent_llm_turn(
        messages=[AIMessage(content="hello")],
        hooks=_adapter_hooks(
            get_llm_for_mode=get_llm_for_mode,
            should_stream=lambda *_args, **_kwargs: True,
            run_streaming_outcome=run_streaming_outcome,
            invoke_outcome=invoke_outcome,
            build_invocation_context=build_invocation_context,
            plan_recovery=plan_recovery,
            record_scene_event=lambda _module, event, **kwargs: events.append(
                (event, kwargs.get("fields") or {})
            ),
        ),
    )
    # attempt 1: primary streamed and hit empty content -> degraded retry;
    # attempt 2: primary, non-streaming, hit a gateway failure -> fallback
    # switch; attempt 3: backup, streaming again (degrade overrides expired).
    assert streaming_calls == ["primary", "backup_qwen"]
    assert invoke_calls == ["primary"]
    assert llm_requests == [(False, None), (False, None), (False, "backup_qwen")]
    assert route_attempts == [1, 2, 3]
    assert result.payload is not None
    assert result.payload[1].content == "rescued"
    assert result.degraded_actions == ["retry_without_streaming"]
    assert result.route_fallback == {"from": "primary", "to": "backup_qwen"}
    event_names = [event for event, _fields in events]
    assert event_names.index("llm_route_degraded_retry") < event_names.index(
        "llm_route_fallback_switched"
    )
    switched = [fields for event, fields in events if event == "llm_route_fallback_switched"]
    assert switched and switched[0]["reason"] == "server_error"
    # Durable persistence is the scene-event binding layer's job (covered by
    # tests/test_llm_resilience_journal.py); the adapter only owes the scene
    # event fields that the mirror consumes.
    assert switched[0]["sessionId"] == "sess-degrade"
    assert switched[0]["turnId"] == "turn-1"


def test_adapter_skips_noop_degrade_when_attempt_was_already_non_streaming():
    """retry_without_streaming is a no-op on a non-streaming attempt: no extra request."""
    invoke_calls = []
    events = []
    primary = _route_llm("primary", identity=("relay", "primary"))

    def invoke_outcome(*_args, **_kwargs):
        invoke_calls.append(1)
        raise _empty_content_error()

    result = invoke_agent_llm_turn(
        messages=[AIMessage(content="hello")],
        hooks=_adapter_hooks(
            get_llm_for_mode=lambda **_kwargs: primary,
            should_stream=lambda *_args, **_kwargs: False,
            invoke_outcome=invoke_outcome,
            plan_recovery=plan_recovery,
            record_scene_event=lambda _module, event, **kwargs: events.append(
                (event, kwargs.get("fields") or {})
            ),
        ),
    )
    assert invoke_calls == [1]
    assert result.payload is None
    assert result.degraded_actions == []
    assert not any(event == "llm_route_degraded_retry" for event, _fields in events)
    assert any(event == "llm_turn_terminal" for event, _fields in events)


def test_adapter_degrades_tool_protocol_even_without_streaming():
    """Dropping tools still changes the request shape on a non-streaming attempt."""
    invoke_calls = []
    llm_requests = []
    primary = _route_llm("primary", identity=("relay", "primary"))

    def get_llm_for_mode(**kwargs):
        llm_requests.append(kwargs.get("disable_tools"))
        return primary

    def invoke_outcome(*_args, **_kwargs):
        invoke_calls.append(len(invoke_calls) + 1)
        if len(invoke_calls) == 1:
            raise _tool_protocol_error()
        return TurnOutcome.final_answer(identity=_identity(), text="plain answer")

    result = invoke_agent_llm_turn(
        messages=[AIMessage(content="hello")],
        hooks=_adapter_hooks(
            get_llm_for_mode=get_llm_for_mode,
            should_stream=lambda *_args, **_kwargs: False,
            invoke_outcome=invoke_outcome,
            plan_recovery=plan_recovery,
        ),
    )
    assert llm_requests == [False, True]
    assert invoke_calls == [1, 2]
    assert result.payload is not None
    assert result.payload[1].content == "plain answer"
    assert result.degraded_actions == ["disable_tools_and_retry_without_streaming"]
