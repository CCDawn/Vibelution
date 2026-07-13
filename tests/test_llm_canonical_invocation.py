import inspect

from config.settings import AppConfig
from core.llm.client import LLMClient
from core.llm.invocation import run_streaming_llm_outcome
from core.llm.types import CanonicalItemIdentity, LLMProtocolEvent, StreamChunk, TurnOutcome
from core.orchestration.turn_outcome import TurnOutcomeController


def _config():
    from tests.test_llm_responses_replay_continuation import _config as replay_config

    return replay_config()

def _metadata():
    return {
        "sessionId": "session-canonical",
        "turnId": "turn-canonical",
        "invocationId": "invocation-canonical",
        "iteration": 0,
    }


def test_invoke_outcome_is_canonical_and_projection_is_one_way():
    client = LLMClient(
        config=_config(),
        backend=lambda _payload: {
            "id": "response-private",
            "status": "completed",
            "output": [
                {
                    "id": "message-1",
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "hello"}],
                }
            ],
        },
    )

    outcome = client.invoke_outcome([{"role": "user", "content": "hi"}], metadata=_metadata())
    projected = client.project_outcome_message(outcome)
    compatibility = client.invoke([{"role": "user", "content": "hi"}], metadata=_metadata())

    assert isinstance(outcome, TurnOutcome)
    assert outcome.kind == "final_answer"
    assert projected.content == "hello"
    assert "turn_outcome" not in projected.additional_kwargs
    assert isinstance(compatibility.additional_kwargs["turn_outcome"], TurnOutcome)


def test_control_and_replay_sources_do_not_read_compatibility_metadata():
    assert "additional_kwargs" not in inspect.getsource(LLMClient._build_payload)
    assert "additional_kwargs" not in inspect.getsource(TurnOutcomeController.decide_llm_iteration)
    assert "provider_payload" not in inspect.getsource(run_streaming_llm_outcome)
    assert "invoke_outcome" in inspect.getsource(LLMClient.invoke)


def test_streaming_bridge_uses_event_sink_and_generator_return(monkeypatch):
    identity = CanonicalItemIdentity(
        session_id="session-stream",
        turn_id="turn-stream",
        invocation_id="invocation-stream",
        iteration=0,
        item_id="answer-stream",
    )
    outcome = TurnOutcome.final_answer(identity=identity, text="streamed")
    event = LLMProtocolEvent(
        kind="answer_delta",
        sequence=1,
        session_id="session-stream",
        turn_id="turn-stream",
        invocation_id="invocation-stream",
        iteration=0,
        item_id="answer-stream",
        text="streamed",
    )

    class FakeContext:
        cache_partition = ""
        prompt_purpose = "test"
        surface = "test"

        def with_cache_partition(self, _partition):
            return self

        def to_metadata(self, client=None):
            return _metadata()

    class FakeClient:
        def stream_events(self, _messages, **kwargs):
            kwargs["protocol_event_sink"](event)
            yield StreamChunk(type="text_delta", text="compatibility-only")
            return outcome

    monkeypatch.setattr(
        "core.llm.invocation._developer_sandbox_module",
        lambda: type("Sandbox", (), {
            "sandbox_prompt_cache_partition": staticmethod(lambda value, surface="": value),
            "enrich_debug_fields": staticmethod(lambda value: value),
        }),
    )
    seen = []
    result = run_streaming_llm_outcome(
        FakeClient(),
        [],
        context=FakeContext(),
        on_event=seen.append,
    )

    assert result is outcome
    assert seen == [event]
