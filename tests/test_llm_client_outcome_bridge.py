from core.llm.client import LLMClient
from core.llm.invocation import invocation_scope_from_metadata
from tests.helpers.isolated_config import isolated_settings_config


def _config(*, transport: str):
    return isolated_settings_config(
        **{
            "llm.providers.default.kind": "relay",
            "llm.providers.default.api_key": "test-key",
            "llm.providers.default.base_url": "https://relay.example.test/v1",
            "llm.providers.default.compat_mode": "openai",
            "llm.profiles.primary.provider_id": "default",
            "llm.profiles.primary.model": "gpt-5.6-luna",
            "llm.profiles.primary.transport": transport,
            "llm.profiles.primary.contract": "tool_chat",
            "llm.profiles.primary.streaming": True,
            "llm.profiles.primary.tool_calling_mode": "auto",
        }
    )


def _metadata():
    return {
        "sessionId": "session-1",
        "turnId": "turn-2",
        "invocationId": "invocation-3",
        "iteration": 4,
        "promptPurpose": "main_reply",
    }


def test_invocation_scope_uses_explicit_conversation_identity():
    scope = invocation_scope_from_metadata(_metadata())

    assert scope.session_id == "session-1"
    assert scope.turn_id == "turn-2"
    assert scope.invocation_id == "invocation-3"
    assert scope.iteration == 4
    assert scope.is_synthetic is False


def test_invocation_scope_uses_controlled_synthetic_identity_for_auxiliary_calls():
    scope = invocation_scope_from_metadata(
        {"llmRunId": "research-7", "promptPurpose": "research broad search"}
    )

    assert scope.session_id == "synthetic:research-broad-search"
    assert scope.turn_id == "synthetic:research-broad-search:research-7"
    assert scope.invocation_id == "research-7"
    assert scope.iteration == 0
    assert scope.is_synthetic is True


def test_responses_invoke_attaches_canonical_outcome_and_projects_final_text():
    response = {
        "id": "resp-1",
        "status": "completed",
        "output": [
            {
                "id": "message-1",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": "标准最终回答"}],
            }
        ],
    }
    client = LLMClient(config=_config(transport="responses"), backend=lambda _payload: response)

    message = client.invoke([{"role": "user", "content": "ping"}], metadata=_metadata())

    outcome = message.additional_kwargs["turn_outcome"]
    assert outcome.kind == "final_answer"
    assert outcome.final_text == "标准最终回答"
    assert outcome.identity.invocation_id == "invocation-3"
    assert message.content == outcome.final_text


def test_chat_invoke_attaches_tool_outcome_and_projects_tool_calls():
    response = {
        "id": "chat-1",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "先检查文件",
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {
                                "name": "read_file",
                                "arguments": '{"path":"agent.py"}',
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
    }
    client = LLMClient(config=_config(transport="chat_completions"), backend=lambda _payload: response)

    message = client.invoke([{"role": "user", "content": "ping"}], metadata=_metadata())

    outcome = message.additional_kwargs["turn_outcome"]
    assert outcome.kind == "tool_calls"
    assert outcome.final_text == ""
    assert [call.call_id for call in outcome.tool_calls] == ["call-1"]
    assert len(message.tool_calls) == 1
    assert message.tool_calls[0]["id"] == "call-1"
    assert message.tool_calls[0]["name"] == "read_file"
    assert message.tool_calls[0]["args"] == {"path": "agent.py"}


def test_chat_stream_carries_tool_outcome_on_terminal_compatibility_chunk():
    chunks = [
        {"id": "chat-1", "choices": [{"delta": {"content": "先检查文件"}}]},
        {
            "id": "chat-1",
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call-1",
                                "type": "function",
                                "function": {
                                    "name": "read_file",
                                    "arguments": '{"path":"agent.py"}',
                                },
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ],
        },
    ]
    client = LLMClient(
        config=_config(transport="chat_completions"),
        backend=lambda _payload: iter(chunks),
    )

    streamed = list(
        client.stream([{"role": "user", "content": "ping"}], metadata=_metadata())
    )

    outcome = streamed[-1].additional_kwargs["turn_outcome"]
    assert outcome.kind == "tool_calls"
    assert outcome.final_text == ""
    assert [call.call_id for call in outcome.tool_calls] == ["call-1"]
    assert any(chunk.content == "先检查文件" for chunk in streamed)
    assert any(chunk.tool_calls for chunk in streamed)


def test_responses_stream_reconstructs_terminal_text_and_carries_outcome():
    chunks = [
        {
            "type": "response.output_item.done",
            "item": {
                "id": "message-1",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": "只在终态出现"}],
            },
        },
        {"type": "response.completed", "response": {"id": "resp-1", "status": "completed"}},
    ]
    client = LLMClient(
        config=_config(transport="responses"),
        backend=lambda _payload: iter(chunks),
    )

    streamed = list(
        client.stream([{"role": "user", "content": "ping"}], metadata=_metadata())
    )

    outcome = streamed[-1].additional_kwargs["turn_outcome"]
    assert outcome.kind == "final_answer"
    assert outcome.final_text == "只在终态出现"
    assert any(chunk.content == "只在终态出现" for chunk in streamed)


def test_chat_stream_retry_reuses_one_canonical_invocation_scope(monkeypatch):
    from core.llm import invocation

    scopes = []
    original_scope_builder = invocation.invocation_scope_from_metadata

    def recording_scope_builder(metadata=None):
        scope = original_scope_builder(metadata)
        scopes.append(scope)
        return scope

    attempts = 0

    def backend(_payload):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            def failing_stream():
                raise ConnectionError("temporary stream failure")
                yield

            return failing_stream()
        return iter(
            [
                {
                    "id": "chat-retry",
                    "choices": [
                        {"delta": {"content": "重试完成"}, "finish_reason": "stop"}
                    ],
                }
            ]
        )

    monkeypatch.setattr(invocation, "invocation_scope_from_metadata", recording_scope_builder)
    monkeypatch.setattr("core.llm.client.time.sleep", lambda _seconds: None)
    client = LLMClient(config=_config(transport="chat_completions"), backend=backend)

    streamed = list(client.stream([{"role": "user", "content": "ping"}]))

    assert attempts == 2
    assert len(scopes) == 1
    assert streamed[-1].additional_kwargs["turn_outcome"].identity.invocation_id == scopes[0].invocation_id
