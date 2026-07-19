from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from core.chat.model_messages import normalize_model_history_messages
from core.llm.provider_replay_state import ProviderReplayState, endpoint_fingerprint
from core.llm.protocols import WireProtocol
from core.llm.semantic_messages import (
    InvocationScope,
    SemanticGenerationSettings,
    ToolCallPart,
    ToolResultPart,
)
from core.llm.semantic_projector import SemanticProjectionInput, project_semantic_request
from core.llm.wire.chat_completions import ChatCompletionsWireAdapter
from core.llm.wire.responses import ResponsesWireAdapter


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "conversation_chain" / "canonical_tool_followup_v2.json"


def _fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _semantic_request(fixture: dict):
    turn = fixture["turns"][1]
    return project_semantic_request(
        SemanticProjectionInput(
            messages=fixture["provider_messages"],
            tools=(),
            scope=InvocationScope(
                session_id=turn["session_id"],
                turn_id=turn["turn_id"],
                invocation_id=turn["invocation_id"],
                iteration=1,
            ),
            settings=SemanticGenerationSettings(max_output_tokens=256, stream=True),
            tool_to_schema=lambda tool: tool,
        )
    )


def _route(protocol: WireProtocol):
    return SimpleNamespace(
        adapter_id=protocol.value,
        wire_protocol=protocol,
        provider_id="golden-provider",
        model_id="golden-model",
        effective_model="golden-model-runtime",
        runtime_endpoint="https://golden.example.test/v1",
        compat=SimpleNamespace(
            responses_continuation=protocol == WireProtocol.RESPONSES,
            responses_websocket=False,
        ),
    )


def test_canonical_history_keeps_two_equal_user_submissions_and_complete_semantic_tool_results() -> None:
    fixture = _fixture()
    turns = fixture["turns"]

    assert fixture["identity_fields"] == ["session_id", "turn_id", "invocation_id", "submission_id"]
    assert len(turns) == 2
    assert turns[1]["user_text"] == "继续"
    assert turns[0]["user_text"] == turns[1]["user_text"]
    assert turns[0]["turn_id"] != turns[1]["turn_id"]
    assert turns[0]["submission_id"] != turns[1]["submission_id"]

    history = normalize_model_history_messages(fixture["provider_messages"])
    users = [message for message in history if message["role"] == "user"]
    semantic_tool_results = [
        message
        for message in history
        if message["role"] == "assistant" and "历史工具结果:" in str(message.get("content") or "")
    ]
    assistant_messages = [message for message in history if message["role"] == "assistant"]
    expected_call_ids = ["call-weather-002", "call-notes-002"]

    assert [message["content"] for message in users] == ["继续", "继续"]
    assert [message["metadata"]["turn_id"] for message in users] == [
        "turn-golden-001",
        "turn-golden-002",
    ]
    assert [message["metadata"]["submission_id"] for message in users] == [
        "submission-golden-001",
        "submission-golden-002",
    ]
    assert not any(message.get("tool_calls") for message in history)
    assert not any(message["role"] == "tool" for message in history)
    assert [message["metadata"]["toolCallId"] for message in semantic_tool_results] == expected_call_ids
    assert [message["metadata"]["toolName"] for message in semantic_tool_results] == [
        "weather_lookup",
        "notes_lookup",
    ]
    assert "Shanghai" in semantic_tool_results[0]["content"]
    assert "semantic history" in semantic_tool_results[1]["content"]
    assert assistant_messages[-1]["content"] == "第二轮完成：天气晴朗，且语义历史与 wire parity 均已确认。"


def test_semantic_projection_and_both_wires_keep_parallel_call_result_pairs_and_final() -> None:
    fixture = _fixture()
    request = _semantic_request(fixture)
    parts = [part for message in request.messages for part in message.parts]
    calls = [part.call for part in parts if isinstance(part, ToolCallPart)]
    results = [part.result for part in parts if isinstance(part, ToolResultPart)]
    expected_call_ids = ["call-weather-002", "call-notes-002"]

    assert [call.call_id for call in calls] == expected_call_ids
    assert [result.call_id for result in results] == expected_call_ids
    assert all(call.identity.session_id == fixture["session_id"] for call in calls)
    assert all(call.identity.turn_id == fixture["turns"][1]["turn_id"] for call in calls)
    assert all(call.identity.invocation_id == fixture["turns"][1]["invocation_id"] for call in calls)

    responses = ResponsesWireAdapter().encode_request(
        request,
        route=_route(WireProtocol.RESPONSES),
    ).body
    response_calls = [item for item in responses["input"] if item.get("type") == "function_call"]
    response_results = [item for item in responses["input"] if item.get("type") == "function_call_output"]
    response_final = responses["input"][-1]

    assert [item["call_id"] for item in response_calls] == expected_call_ids
    assert [item["call_id"] for item in response_results] == expected_call_ids
    assert response_final == {
        "role": "assistant",
        "content": [
            {
                "type": "output_text",
                "text": "第二轮完成：天气晴朗，且语义历史与 wire parity 均已确认。",
            }
        ],
    }

    chat = ChatCompletionsWireAdapter().encode_request(
        request,
        route=_route(WireProtocol.CHAT_COMPLETIONS),
    ).body
    chat_call_message = next(message for message in chat["messages"] if message.get("tool_calls"))
    chat_results = [message for message in chat["messages"] if message.get("role") == "tool"]

    assert [item["id"] for item in chat_call_message["tool_calls"]] == expected_call_ids
    assert [message["tool_call_id"] for message in chat_results] == expected_call_ids
    assert chat["messages"][-1] == {
        "role": "assistant",
        "content": "第二轮完成：天气晴朗，且语义历史与 wire parity 均已确认。",
    }


def test_five_round_tool_chain_keeps_wire_parity_and_stateful_responses_deltas() -> None:
    route_responses = _route(WireProtocol.RESPONSES)
    route_chat = _route(WireProtocol.CHAT_COMPLETIONS)
    messages: list[dict] = [
        {"role": "system", "content": "Use each requested inspection tool in order."},
        {"role": "user", "content": "Run five bounded inspections, then summarize."},
    ]
    call_ids: list[str] = []
    for round_number in range(1, 6):
        call_id = f"call-inspect-{round_number}"
        call_ids.append(call_id)
        messages.extend(
            [
                {
                    "role": "assistant",
                    "content": f"Inspection round {round_number}.",
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": "inspect_tool",
                                "arguments": json.dumps(
                                    {"round": round_number},
                                    ensure_ascii=False,
                                ),
                            },
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": json.dumps(
                        {"round": round_number, "status": "ok"},
                        ensure_ascii=False,
                    ),
                },
            ]
        )
    messages.append(
        {
            "role": "assistant",
            "content": "All five inspection rounds completed successfully.",
        }
    )
    scope = InvocationScope(
        session_id="session-five-round",
        turn_id="turn-five-round",
        invocation_id="invocation-five-round",
        iteration=5,
    )
    request = project_semantic_request(
        SemanticProjectionInput(
            messages=messages,
            tools=(),
            scope=scope,
            settings=SemanticGenerationSettings(max_output_tokens=256, stream=True),
            tool_to_schema=lambda tool: tool,
        )
    )

    responses = ResponsesWireAdapter().encode_request(
        request,
        route=route_responses,
    ).body
    response_calls = [
        item for item in responses["input"] if item.get("type") == "function_call"
    ]
    response_outputs = [
        item
        for item in responses["input"]
        if item.get("type") == "function_call_output"
    ]
    assert [item["call_id"] for item in response_calls] == call_ids
    assert [item["call_id"] for item in response_outputs] == call_ids
    assert "previous_response_id" not in responses

    chat = ChatCompletionsWireAdapter().encode_request(
        request,
        route=route_chat,
    ).body
    chat_calls = [
        call
        for message in chat["messages"]
        for call in message.get("tool_calls", [])
    ]
    chat_outputs = [
        message for message in chat["messages"] if message.get("role") == "tool"
    ]
    assert [call["id"] for call in chat_calls] == call_ids
    assert [message["tool_call_id"] for message in chat_outputs] == call_ids
    assert chat["messages"][-1]["content"] == (
        "All five inspection rounds completed successfully."
    )
    assert all("previous_response_id" not in message for message in chat["messages"])
    assert all(message.get("type") != "function_call_output" for message in chat["messages"])

    for round_number, call_id in enumerate(call_ids, start=1):
        replay_state = ProviderReplayState(
            issuer="responses",
            provider_id=route_responses.provider_id,
            endpoint_fingerprint=endpoint_fingerprint(
                route_responses.runtime_endpoint
            ),
            model_id=route_responses.model_id,
            wire_protocol=WireProtocol.RESPONSES,
            opaque_items=(),
            response_id=f"response-{round_number}",
            pending_call_ids=(call_id,),
        )
        continuation = project_semantic_request(
            SemanticProjectionInput(
                messages=(
                    messages[(round_number - 1) * 2 + 2],
                    messages[(round_number - 1) * 2 + 3],
                ),
                tools=(),
                scope=InvocationScope(
                    session_id=scope.session_id,
                    turn_id=scope.turn_id,
                    invocation_id=f"{scope.invocation_id}-{round_number}",
                    iteration=round_number,
                ),
                settings=SemanticGenerationSettings(
                    max_output_tokens=256,
                    stream=True,
                ),
                tool_to_schema=lambda tool: tool,
                replay_state=replay_state,
            )
        )
        stateful = ResponsesWireAdapter().encode_request(
            continuation,
            route=route_responses,
        ).body

        assert stateful["previous_response_id"] == f"response-{round_number}"
        assert stateful["input"] == [
            {
                "type": "function_call_output",
                "call_id": call_id,
                "output": json.dumps(
                    {"round": round_number, "status": "ok"},
                    ensure_ascii=False,
                ),
            }
        ]
