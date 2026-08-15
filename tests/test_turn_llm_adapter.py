from types import SimpleNamespace

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from agent import SelfEvolvingAgent, TurnStopRequested
from core.infrastructure.llm_utils import MAX_CONSECUTIVE_FAILURES
from core.infrastructure.runtime_input import build_chat_user_message
from core.llm import LLMError
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

        def project_outcome_message(self, outcome):
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


def test_adapter_uses_injected_recovery_for_fallback_profile():
    calls = []

    class PrimaryLLM:
        profile_id = "primary"

        def effective_route_identity(self):
            return ("relay", "primary")

        def effective_route_id(self):
            return "primary-route"

        def project_outcome_message(self, outcome):
            return AIMessage(content=outcome.final_text)

    class FallbackLLM:
        profile_id = "fallback_backup"

        def effective_route_identity(self):
            return ("local", "fallback")

        def effective_route_id(self):
            return "fallback-route"

        def project_outcome_message(self, outcome):
            return AIMessage(content=outcome.final_text)

    def invoke_outcome(client, _messages, **_kwargs):
        calls.append(client.profile_id)
        if client.profile_id == "primary":
            raise LLMError(
                "server_error",
                "provider 服务异常",
                retryable=True,
                details={"attempt": 5, "max_attempts": 5, "retry_budget_exhausted": True},
            )
        return TurnOutcome.final_answer(identity=_identity(), text="fallback ok")

    def plan_recovery(_error, *, current_profile_id=None, **_kwargs):
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
            fallback_profile_id="fallback_backup" if current_profile_id == "primary" else None,
        )

    hooks = AgentLlmTurnHooks(
        get_ui=lambda: _DummyUI(),
        llm_cancel_context=lambda _checker: _DummyContext(),
        raise_if_stop=lambda: None,
        current_stop_reason=lambda: "",
        get_llm_for_mode=lambda **kwargs: (
            FallbackLLM() if kwargs.get("profile_id") == "fallback_backup" else PrimaryLLM()
        ),
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
            AssertionError("fallback success must not compress")
        ),
        debug_logger=SimpleNamespace(error=lambda *_args, **_kwargs: None),
        error_logger=SimpleNamespace(log_error=lambda *_args, **_kwargs: None),
        config=SimpleNamespace(llm=SimpleNamespace(model_name="m", provider="relay", api_base="", api_timeout=30)),
        force_disable_tools=False,
        stop_error_cls=TurnStopRequested,
        base_llm=PrimaryLLM(),
    )
    result = invoke_agent_llm_turn(messages=[AIMessage(content="hello")], hooks=hooks)
    assert calls == ["primary", "fallback_backup"]
    assert result.payload[1].content == "fallback ok"
    assert result.last_error_category == "server_error"


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
            fallback_profile_id=None,
        ),
    )
    monkeypatch.setattr(agent_module.logger, "log_error", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(agent_module, "_record_agent_scene_event", lambda *_args, **_kwargs: None)

    agent = SelfEvolvingAgent.__new__(SelfEvolvingAgent)
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
