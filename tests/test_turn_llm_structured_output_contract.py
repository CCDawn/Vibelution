from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, SystemMessage

from agent import TurnStopRequested
from core.chat import check_conversation_payload_invariant
from core.llm.semantic_messages import SemanticOutputSchema
from core.llm.types import CanonicalItemIdentity, CanonicalToolCall, TurnOutcome
from core.orchestration.turn_llm_adapter import (
    _structured_output_disclosure_message,
    _validate_structured_output_outcome,
    AgentLlmTurnHooks,
    invoke_agent_llm_turn,
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


def _accepting_validator(payload):
    if payload.get("taskKind") != "hypothesis_design":
        raise ValueError("wrong task kind")


def _contract(**overrides) -> SemanticOutputSchema:
    kwargs = dict(
        name="research_hypothesis_design_v1",
        schema={
            "type": "object",
            "properties": {
                "taskKind": {"type": "string"},
            },
            "required": ["taskKind"],
            "additionalProperties": False,
        },
        validator=_accepting_validator,
    )
    kwargs.update(overrides)
    return SemanticOutputSchema(**kwargs)


def _route_llm(*, with_stream: bool = False):
    class RouteLLM:
        profile_id = "primary"

        def effective_route_identity(self):
            return ("primary",)

        def effective_route_id(self):
            return "primary-route"

        def project_outcome_message(self, outcome):
            return AIMessage(content=outcome.final_text)

    client = RouteLLM()
    if with_stream:
        client.stream = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("adapter must not call client.stream directly")
        )
    return client


def _hooks(**overrides) -> AgentLlmTurnHooks:
    defaults = dict(
        get_ui=lambda: _DummyUI(),
        llm_cancel_context=lambda _checker: _DummyContext(),
        raise_if_stop=lambda: None,
        current_stop_reason=lambda: "",
        get_llm_for_mode=lambda **_kwargs: _route_llm(),
        should_stream=lambda *_args, **_kwargs: False,
        build_invocation_context=lambda **_kwargs: SimpleNamespace(
            to_metadata=lambda client=None: {"invocationId": "inv-1"}
        ),
        invoke_outcome=lambda *_args, **_kwargs: TurnOutcome.final_answer(
            identity=_identity(),
            text='{"taskKind":"hypothesis_design"}',
        ),
        run_streaming_outcome=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("non-stream path must not stream")
        ),
        canonicalize=lambda outcome: outcome,
        plan_recovery=lambda *_args, **_kwargs: SimpleNamespace(
            category="structured_output_validation_error",
            retryable=False,
            action="stop",
            user_message="invalid structured output",
            wait_seconds=0,
            stop_current_turn=True,
            disable_streaming=False,
            disable_tools=False,
            request_context_compression=False,
            fallback_profile_id=None,
        ),
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


def test_disclosure_message_contains_schema_name_and_compact_schema():
    contract = _contract()
    message = _structured_output_disclosure_message(contract)
    assert isinstance(message, SystemMessage)
    assert "research_hypothesis_design_v1" in message.content
    assert '"taskKind":{"type":"string"}' in message.content
    assert '"additionalProperties":false' in message.content
    assert "final answer" in message.content
    assert "object" in message.content


def test_non_stream_path_receives_appended_disclosure_message():
    captured = []

    def invoke_outcome(_client, messages, **_kwargs):
        captured.append(list(messages))
        return TurnOutcome.final_answer(
            identity=_identity(),
            text='{"taskKind":"hypothesis_design"}',
        )

    original = [AIMessage(content="hello")]
    result = invoke_agent_llm_turn(
        messages=list(original),
        hooks=_hooks(invoke_outcome=invoke_outcome, structured_output_contract=_contract()),
    )
    assert result.payload[0].kind == "final_answer"
    assert len(captured) == 1
    sent = captured[0]
    assert len(sent) == len(original) + 1
    assert sent[:-1] == original
    assert isinstance(sent[-1], SystemMessage)
    assert "research_hypothesis_design_v1" in sent[-1].content
    assert '"taskKind":{"type":"string"}' in sent[-1].content


def test_stream_path_receives_appended_disclosure_message():
    captured = []

    def run_streaming_outcome(_client, messages, **_kwargs):
        captured.append(list(messages))
        return TurnOutcome.final_answer(
            identity=_identity(),
            text='{"taskKind":"hypothesis_design"}',
        )

    original = [AIMessage(content="hello")]
    result = invoke_agent_llm_turn(
        messages=list(original),
        hooks=_hooks(
            get_llm_for_mode=lambda **_kwargs: _route_llm(with_stream=True),
            should_stream=lambda *_args, **_kwargs: True,
            run_streaming_outcome=run_streaming_outcome,
            structured_output_contract=_contract(),
        ),
    )
    assert result.payload[0].kind == "final_answer"
    assert len(captured) == 1
    sent = captured[0]
    assert len(sent) == len(original) + 1
    assert sent[:-1] == original
    assert isinstance(sent[-1], SystemMessage)
    assert "research_hypothesis_design_v1" in sent[-1].content


def test_no_contract_keeps_messages_unchanged():
    captured = []

    def invoke_outcome(_client, messages, **_kwargs):
        captured.append(list(messages))
        return TurnOutcome.final_answer(
            identity=_identity(),
            text='{"taskKind":"hypothesis_design"}',
        )

    original = [AIMessage(content="hello")]
    result = invoke_agent_llm_turn(
        messages=list(original),
        hooks=_hooks(invoke_outcome=invoke_outcome),
    )
    assert result.payload[0].kind == "final_answer"
    assert captured == [original]


def test_validate_accepts_plain_json_object():
    contract = _contract()
    outcome = TurnOutcome.final_answer(
        identity=_identity(),
        text='{"taskKind":"hypothesis_design","reasoning":"bounded"}',
    )
    _validate_structured_output_outcome(outcome, contract)


def test_validate_accepts_json_fence_variants():
    contract = _contract()
    fenced = TurnOutcome.final_answer(
        identity=_identity(),
        text='```json\n{"taskKind":"hypothesis_design"}\n```',
    )
    _validate_structured_output_outcome(fenced, contract)

    bare_fenced = TurnOutcome.final_answer(
        identity=_identity(),
        text='```\n{"taskKind":"hypothesis_design"}\n```',
    )
    _validate_structured_output_outcome(bare_fenced, contract)

    padded = TurnOutcome.final_answer(
        identity=_identity(),
        text='  \n```json\n{"taskKind":"hypothesis_design"}\n```\n',
    )
    _validate_structured_output_outcome(padded, contract)


def test_validate_rejects_natural_language_final_answer():
    contract = _contract()
    outcome = TurnOutcome.final_answer(
        identity=_identity(),
        text="我认为核心假设应该是用户更偏好自动化流程。",
    )
    with pytest.raises(Exception) as excinfo:
        _validate_structured_output_outcome(outcome, contract)
    assert getattr(excinfo.value, "category", None) == "structured_output_validation_error"
    assert excinfo.value.retryable is False


def test_validate_rejects_valid_json_failed_by_validator():
    contract = _contract()
    outcome = TurnOutcome.final_answer(
        identity=_identity(),
        text='{"taskKind":"result_evaluation"}',
    )
    with pytest.raises(Exception) as excinfo:
        _validate_structured_output_outcome(outcome, contract)
    assert getattr(excinfo.value, "category", None) == "structured_output_validation_error"
    assert excinfo.value.retryable is False


def test_validate_ignores_non_final_outcomes_and_missing_contract():
    contract = _contract()
    call = CanonicalToolCall(identity=_identity(), call_id="call_1", name="read_file_tool")
    tool_outcome = TurnOutcome(
        kind="tool_calls",
        identity=_identity(),
        tool_calls=(call,),
        pending_tool_call_ids=("call_1",),
    )
    _validate_structured_output_outcome(tool_outcome, contract)

    plain = TurnOutcome.final_answer(identity=_identity(), text="not json")
    _validate_structured_output_outcome(plain, None)


def test_appended_system_message_keeps_conversation_payload_invariant_ok():
    contract = _contract()
    original = [
        AIMessage(content="calling tool", tool_calls=[{"id": "call_1", "name": "search_tool", "args": {}}]),
        SystemMessage(content="stable system"),
    ]
    appended = list(original) + [_structured_output_disclosure_message(contract)]
    result = check_conversation_payload_invariant(appended, expected_fingerprint="")
    assert result.ok is True
