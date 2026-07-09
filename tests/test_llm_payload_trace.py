import json

from core.infrastructure.event_bus import EventNames, get_event_bus
from core.llm.client import LLMClient, llm_status_context
from core.llm.payload_trace import build_llm_payload_trace
from tests.helpers.isolated_config import isolated_settings_config


def test_llm_payload_trace_uses_safe_payload_facts_without_message_content():
    trace = build_llm_payload_trace(
        phase="stream",
        stream=True,
        role="primary",
        profile_id="primary",
        provider="relay",
        model="gpt-5.5",
        message_count=2,
        tool_count=1,
        metadata={
            "sessionId": "session-1",
            "llmRunId": "turn-1",
            "agentId": "agent-1",
            "llmSlot": "dialogue",
            "llmModelId": "agent-model",
            "promptPurpose": "main_reply",
            "dialogueChainMode": "responses_agent",
            "promptCachePartition": "secret-partition-text",
            "promptCachePartitionHash": "abc123",
        },
        summaries=[
            {"messageRoleCounts": {"system": 1, "user": 1}, "messageRoles": ["system", "user"]},
            {"transport": "responses", "selectedProtocol": "relay_responses", "protocolSource": "explicit_model"},
            {"inputItemCount": 2, "imageBlockCount": 0, "toolDefinitionCount": 1},
            {"promptCacheMode": "automatic", "promptCachePayloadEnabled": True},
            {"thinkingRequested": True, "thinkingType": "enabled", "thinkingDisplay": "hidden"},
        ],
    )

    assert trace["sessionId"] == "session-1"
    assert trace["turnId"] == "turn-1"
    assert trace["agentId"] == "agent-1"
    assert trace["provider"] == "relay"
    assert trace["selectedProtocol"] == "relay_responses"
    assert trace["dialogueChainMode"] == "responses_agent"
    assert trace["messageRoleCounts"] == {"system": 1, "user": 1}
    assert trace["messageRoles"] == ["system", "user"]
    assert trace["promptCache"]["promptCachePartitionHash"] == "abc123"
    assert trace["promptCache"]["promptCachePartitionChars"] == 0
    assert trace["thinking"]["thinkingRequested"] is True
    serialized = json.dumps(trace, ensure_ascii=False)
    assert "secret-partition-text" not in serialized
    assert "raw prompt" not in serialized


def _make_config(**kwargs):
    kwargs.setdefault("llm.profiles.primary.contract", "tool_chat")
    kwargs.setdefault("llm.profiles.primary.streaming", True)
    kwargs.setdefault("llm.profiles.primary.tool_calling_mode", "auto")
    kwargs.setdefault("llm.profiles.primary.transport", "chat_completions")
    kwargs.setdefault("llm.providers.default.kind", "openai_compatible")
    kwargs.setdefault("llm.providers.default.api_key", "test-key")
    kwargs.setdefault("llm.providers.default.base_url", "https://example.test/v1")
    kwargs.setdefault("llm.profiles.primary.provider_id", "default")
    kwargs.setdefault("llm.profiles.primary.model", "gpt-5.5")
    return isolated_settings_config(**kwargs)


def test_llm_client_invoke_emits_safe_payload_trace_event():
    events = []
    event_bus = get_event_bus()

    def capture(event):
        events.append(event.data)

    callback_id = event_bus.subscribe(
        EventNames.LLM_STATUS,
        capture,
        callback_id="test-llm-payload-trace-invoke",
    )
    try:
        client = LLMClient(
            config=_make_config(),
            backend=lambda payload: {"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
        )
        with llm_status_context(sessionId="session-1", turnId="turn-1"):
            client.invoke([{"role": "user", "content": "secret raw prompt"}])
    finally:
        event_bus.unsubscribe_by_id(callback_id)

    trace_events = [event for event in events if event.get("status") == "payload_trace"]
    assert len(trace_events) == 1
    trace = trace_events[0]["llmPayloadTrace"]
    assert trace["traceId"] == trace_events[0]["traceId"]
    assert trace["sessionId"] == "session-1"
    assert trace["turnId"] == "turn-1"
    assert trace["provider"] == "openai_compatible"
    assert trace["model"] == "gpt-5.5"
    serialized = json.dumps(trace, ensure_ascii=False)
    assert "secret raw prompt" not in serialized


def test_llm_client_stream_emits_safe_payload_trace_event():
    events = []
    event_bus = get_event_bus()

    def capture(event):
        events.append(event.data)

    callback_id = event_bus.subscribe(
        EventNames.LLM_STATUS,
        capture,
        callback_id="test-llm-payload-trace-stream",
    )
    try:
        client = LLMClient(
            config=_make_config(),
            backend=lambda payload: iter([{"choices": [{"delta": {"content": "ok"}}]}]),
        )
        with llm_status_context(sessionId="session-1", turnId="turn-stream"):
            stream_events = list(client.stream_events([{"role": "user", "content": "secret raw prompt"}]))
    finally:
        event_bus.unsubscribe_by_id(callback_id)

    assert [event.type for event in stream_events] == ["text_delta", "done"]
    trace_events = [event for event in events if event.get("status") == "payload_trace"]
    assert len(trace_events) == 1
    trace = trace_events[0]["llmPayloadTrace"]
    assert trace["phase"] == "stream"
    assert trace["stream"] is True
    assert trace["sessionId"] == "session-1"
    assert trace["turnId"] == "turn-stream"
    serialized = json.dumps(trace, ensure_ascii=False)
    assert "secret raw prompt" not in serialized


def test_llm_payload_trace_respects_explicit_empty_tools_over_bound_tools():
    events = []
    event_bus = get_event_bus()

    def capture(event):
        events.append(event.data)

    callback_id = event_bus.subscribe(
        EventNames.LLM_STATUS,
        capture,
        callback_id="test-llm-payload-trace-empty-tools",
    )
    try:
        client = LLMClient(
            config=_make_config(),
            bound_tools=[{"name": "read_file"}],
            backend=lambda payload: {"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
        )
        client.invoke([{"role": "user", "content": "ping"}], tools=[])
    finally:
        event_bus.unsubscribe_by_id(callback_id)

    trace_events = [event for event in events if event.get("status") == "payload_trace"]
    assert len(trace_events) == 1
    trace = trace_events[0]["llmPayloadTrace"]
    assert trace["toolCount"] == 0
    assert trace["payloadShape"].get("toolDefinitionCount") in (None, 0)
