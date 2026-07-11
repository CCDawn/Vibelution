from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
import pytest

from core.llm.semantic_messages import (
    CacheHint,
    ImagePart,
    InvocationScope,
    ReasoningReplayPart,
    SemanticGenerationSettings,
    TextPart,
    ToolCallPart,
    ToolResultPart,
)
from core.llm.semantic_projector import (
    SemanticProjectionError,
    SemanticProjectionInput,
    project_semantic_request,
)


def _scope() -> InvocationScope:
    return InvocationScope(
        session_id="session-1",
        turn_id="turn-1",
        invocation_id="invocation-1",
        iteration=0,
    )


def _project(messages, tools=()):
    return project_semantic_request(
        SemanticProjectionInput(
            messages=tuple(messages),
            tools=tuple(tools),
            scope=_scope(),
            settings=SemanticGenerationSettings(max_output_tokens=256),
            tool_to_schema=lambda tool: tool,
        )
    )


def test_projector_preserves_text_tool_call_and_result_identity_in_order():
    request = _project(
        [
            HumanMessage(content="查资料"),
            AIMessage(
                content="我先查询。",
                tool_calls=[{"id": "call-search", "name": "search", "args": {"q": "moon"}}],
            ),
            ToolMessage(content="result", tool_call_id="call-search", name="search"),
            HumanMessage(content="继续"),
        ]
    )

    assert [message.role for message in request.messages] == ["user", "assistant", "tool", "user"]
    assert isinstance(request.messages[1].parts[0], TextPart)
    assert isinstance(request.messages[1].parts[1], ToolCallPart)
    assert isinstance(request.messages[2].parts[0], ToolResultPart)
    call = request.messages[1].parts[1].call
    result = request.messages[2].parts[0].result
    assert call.call_id == result.call_id == "call-search"
    assert call.identity.item_id == "tool-call:call-search"
    assert result.identity.item_id == "tool-result:call-search"
    assert call.identity.session_id == result.identity.session_id == "session-1"


def test_projector_preserves_images_cache_hints_replay_references_and_tool_schema():
    request = _project(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "look", "cache_control": {"type": "ephemeral"}},
                    {"type": "image_url", "image_url": {"url": "memory://image-1", "detail": "high"}},
                ],
            },
            {
                "role": "assistant",
                "content": "",
                "reasoning_replay_item_id": "reasoning-1",
            },
        ],
        tools=(
            {
                "type": "function",
                "function": {
                    "name": "search",
                    "description": "Search safely",
                    "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
                },
            },
        ),
    )

    assert request.messages[0].parts == (
        TextPart("look", cache_hint=CacheHint("ephemeral")),
        ImagePart("memory://image-1", "application/octet-stream", detail="high"),
    )
    assert request.messages[1].parts == (ReasoningReplayPart("reasoning-1"),)
    assert request.tools[0].name == "search"
    assert request.tools[0].description == "Search safely"
    assert request.tools[0].input_schema["properties"]["q"]["type"] == "string"


def test_projector_rejects_orphan_tool_result_before_adapter_dispatch():
    with pytest.raises(SemanticProjectionError) as exc_info:
        _project([ToolMessage(content="orphan", tool_call_id="missing", name="search")])

    assert exc_info.value.code == "orphan_tool_result"
    assert exc_info.value.message_index == 0


def test_projector_rejects_ui_tool_calls_field():
    with pytest.raises(SemanticProjectionError) as exc_info:
        _project([{"role": "assistant", "content": "", "toolCalls": [{"id": "ui-only"}]}])

    assert exc_info.value.code == "ui_projection_not_model_input"


def test_projector_rejects_duplicate_tool_call_ids():
    with pytest.raises(SemanticProjectionError) as exc_info:
        _project(
            [
                AIMessage(content="", tool_calls=[{"id": "call-1", "name": "a", "args": {}}]),
                AIMessage(content="", tool_calls=[{"id": "call-1", "name": "b", "args": {}}]),
            ]
        )

    assert exc_info.value.code == "duplicate_tool_call_id"


def test_cache_hint_rejects_unbounded_provider_metadata():
    with pytest.raises(ValueError, match="cache hint"):
        CacheHint("provider-specific")
