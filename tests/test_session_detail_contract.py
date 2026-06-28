import json

import pytest
from fastapi.testclient import TestClient

from core.chat.conversation_ledger import (
    EVENT_ASSISTANT_MESSAGE,
    EVENT_USER_MESSAGE,
    append_conversation_event,
    load_conversation_events,
)
from core.ui.chat_state import load_chat_state, save_chat_state
from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import (
    agent_directory_service,
    self_evolution_control_service,
    session_service,
    supervised_control_service,
)
from tests.helpers.web_chat_state import _seed_chat_state


client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


@pytest.fixture(autouse=True)
def disable_runtime_manager_live_control(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(supervised_control_service, "_runtime_manager_live_control_enabled", lambda: False)
    monkeypatch.setattr(self_evolution_control_service, "_runtime_manager_live_control_enabled", lambda: False)


def test_session_detail_surfaces_missing_agent_placeholder(tmp_path, monkeypatch):
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": "session-live",
            "conversations": [
                {
                    "conversation_id": "session-live",
                    "title": "断链会话",
                    "agent_id": "agent-missing",
                    "agentId": "agent-missing",
                    "updated_at": "2026-05-18T12:00:00",
                    "last_turn_status": "ready",
                    "messages": [
                        {
                            "role": "user",
                            "content": "继续",
                            "timestamp": "2026-05-18T11:55:00",
                        }
                    ],
                }
            ],
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    sessions_response = client.get("/api/sessions")
    detail_response = client.get("/api/sessions/session-live")

    assert sessions_response.status_code == 200
    assert sessions_response.json() == []
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["agentMissing"] is True
    assert detail["agentStatusCode"] == "missing_agent"
    assert detail["agentDisplayName"] == "缺少有效 Agent"
    assert "缺少有效 Agent" in detail["agentStatusMessage"]
    assert detail["groupContextEvents"] == []
    assert detail["agentInboxMessages"] == []
    assert detail["toolPolicy"] is None
    assert detail["memoryPolicy"] is None


def test_session_detail_context_usage_comes_from_ledger_after_restart(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    append_conversation_event(
        tmp_path,
        "session-live",
        "turn-ledger-2",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "重启后仍然应该统计这一条历史用户消息。"},
    )
    append_conversation_event(
        tmp_path,
        "session-live",
        "turn-ledger-2",
        EVENT_ASSISTANT_MESSAGE,
        status="completed",
        payload={"content": "收到，当前对话上下文应来自持久 ledger，而不是运行时临时计数。"},
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["messages"]) == 4
    assert payload["contextUsage"]["messageCount"] == 4
    assert payload["contextUsage"]["userMessageCount"] == 2
    assert payload["contextUsage"]["assistantMessageCount"] == 2
    assert payload["contextUsage"]["source"] == "conversation_ledger"
    assert payload["contextUsage"]["used"] == payload["contextUsage"]["estimatedTokens"]
    assert payload["contextUsage"]["used"] > 0


def test_session_detail_context_limit_uses_agent_dialogue_model_window(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    cfg = session_service.get_config().model_copy(deep=True)
    provider_id = cfg.llm.get_profile(role="primary").provider_id
    cfg.llm.get_provider(provider_id).context_window = 200_000
    cfg.llm.model_library["agent-dialogue-window-test"] = {
        "provider_id": provider_id,
        "model": "claude-opus-window-test",
        "label": "Agent dialogue window test",
    }
    cfg.context_compression.max_token_limit = 32_768
    monkeypatch.setattr(session_service, "get_config", lambda: cfg)
    agent = agent_directory_service.ensure_agent_for_session(
        "session-live",
        display_name="真实会话",
        llm_bindings={"dialogue": {"modelId": "agent-dialogue-window-test"}},
        prompt_template_id="prompt-chat-default",
    )

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200
    payload = response.json()
    assert payload["agentId"] == agent["agentId"]
    assert payload["contextUsage"]["limit"] == 200_000
    assert payload["contextUsage"]["limitSource"] == "agent_dialogue_model"
    assert payload["contextUsage"]["limitModelId"] == "agent-dialogue-window-test"
    assert payload["contextUsage"]["limitAgentId"] == agent["agentId"]


def test_session_detail_context_limit_ignores_stale_runtime_window(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    runtime_state_path = tmp_path / "workspace" / "ui_runtime_state.json"
    runtime_state_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_state_path.write_text(
        json.dumps(
            {
                "context_token_limit": 900_000,
                "context_compression": {
                    "effectiveTokenLimit": 450_000,
                    "contextWindowLimit": 900_000,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    cfg = session_service.get_config().model_copy(deep=True)
    provider_id = cfg.llm.get_profile(role="primary").provider_id
    cfg.llm.get_provider(provider_id).context_window = 200_000
    cfg.llm.model_library["agent-dialogue-runtime-stale-test"] = {
        "provider_id": provider_id,
        "model": "claude-opus-window-test",
        "label": "Agent dialogue runtime stale test",
    }
    cfg.context_compression.max_token_limit = 32_768
    monkeypatch.setattr(session_service, "get_config", lambda: cfg)
    agent_directory_service.ensure_agent_for_session(
        "session-live",
        display_name="真实会话",
        llm_bindings={"dialogue": {"modelId": "agent-dialogue-runtime-stale-test"}},
        prompt_template_id="prompt-chat-default",
    )

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200
    payload = response.json()
    assert payload["contextUsage"]["limit"] == 200_000
    assert payload["contextUsage"]["limitSource"] == "agent_dialogue_model"
    assert payload["contextUsage"]["limitModelId"] == "agent-dialogue-runtime-stale-test"


def test_session_detail_uses_provider_usage_for_prompt_cache_observation(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    runtime_state = {
        "turn_input_tokens": 1000,
        "turn_cached_input_tokens": 640,
        "last_input_tokens": 500,
        "last_cached_input_tokens": 320,
        "total_input_tokens": 5000,
        "total_cached_input_tokens": 2500,
        "updated_at": "2026-05-18T12:03:00",
    }
    runtime_state_path = tmp_path / "workspace" / "ui_runtime_state.json"
    runtime_state_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_state_path.write_text(json.dumps(runtime_state), encoding="utf-8")
    append_conversation_event(
        tmp_path,
        "session-live",
        "turn-cache-usage",
        EVENT_ASSISTANT_MESSAGE,
        status="completed",
        payload={
            "content": "缓存观测来自 ledger。",
            "llmUsage": {
                "source": "provider_usage",
                "input_tokens": 800,
                "output_tokens": 120,
                "cached_input_tokens": 200,
                "cache_creation_input_tokens": 160,
                "recorded_at": "2026-05-18T12:04:00",
            },
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200
    cache_usage = response.json()["cacheUsage"]
    assert cache_usage["turnInputTokens"] == 800
    assert cache_usage["turnCachedInputTokens"] == 200
    assert cache_usage["turnCacheReadInputTokens"] == 200
    assert cache_usage["turnCacheCreationInputTokens"] == 160
    assert cache_usage["turnUncachedInputTokens"] == 600
    assert cache_usage["lastInputTokens"] == 800
    assert cache_usage["lastCachedInputTokens"] == 200
    assert cache_usage["lastCacheCreationInputTokens"] == 160
    assert cache_usage["lastUncachedInputTokens"] == 600
    assert cache_usage["turnCacheHitRate"] == pytest.approx(0.25)
    assert cache_usage["totalCacheHitRate"] == pytest.approx(0.25)
    assert cache_usage["updatedAt"] == "2026-05-18T12:04:00"
    assert cache_usage["source"] == "provider_usage"


def test_session_detail_marks_prompt_cache_missing_without_provider_usage(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    runtime_state = {
        "turn_input_tokens": 1000,
        "turn_cached_input_tokens": 640,
        "updated_at": "2026-05-18T12:03:00",
    }
    runtime_state_path = tmp_path / "workspace" / "ui_runtime_state.json"
    runtime_state_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_state_path.write_text(json.dumps(runtime_state), encoding="utf-8")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200
    cache_usage = response.json()["cacheUsage"]
    assert cache_usage["turnInputTokens"] == 0
    assert cache_usage["turnCachedInputTokens"] == 0
    assert cache_usage["turnCacheHitRate"] == 0.0
    assert cache_usage["source"] == "missing"


def test_session_detail_exposes_last_provider_llm_usage(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    append_conversation_event(
        tmp_path,
        "session-live",
        "turn-provider-usage",
        EVENT_ASSISTANT_MESSAGE,
        status="completed",
        payload={
            "content": "模型用量来自 ledger。",
            "llmUsage": {
                "source": "provider_usage",
                "input_tokens": 2048,
                "output_tokens": 256,
                "cached_input_tokens": 512,
                "cache_creation_input_tokens": 384,
                "provider": "openai",
                "model": "gpt-5",
                "recorded_at": "2026-05-18T12:04:00",
            },
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200
    llm_usage = response.json()["llmUsage"]
    assert llm_usage["source"] == "provider_usage"
    assert llm_usage["inputTokens"] == 2048
    assert llm_usage["outputTokens"] == 256
    assert llm_usage["totalTokens"] == 2304
    assert llm_usage["cachedInputTokens"] == 512
    assert llm_usage["cacheReadInputTokens"] == 512
    assert llm_usage["cacheCreationInputTokens"] == 384
    assert llm_usage["uncachedInputTokens"] == 1536
    assert llm_usage["cacheHitRate"] == pytest.approx(0.25)
    assert llm_usage["provider"] == "openai"
    assert llm_usage["model"] == "gpt-5"
    assert llm_usage["recordedAt"] == "2026-05-18T12:04:00"


def test_session_detail_compacts_repeated_provider_metadata_from_stream_merge(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    append_conversation_event(
        tmp_path,
        "session-live",
        "turn-provider-usage-repeated",
        EVENT_ASSISTANT_MESSAGE,
        status="completed",
        payload={
            "content": "模型用量来自被聚合后的 stream chunk。",
            "llmUsage": {
                "source": "provider_usage",
                "input_tokens": 2048,
                "output_tokens": 256,
                "cached_input_tokens": 512,
                "provider": "xiaomixiaomixiaomi",
                "model": "mimo-v2.5-promimo-v2.5-promimo-v2.5-pro",
                "recorded_at": "2026-05-18T12:04:00",
            },
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200
    llm_usage = response.json()["llmUsage"]
    assert llm_usage["provider"] == "xiaomi"
    assert llm_usage["model"] == "mimo-v2.5-pro"


def test_session_detail_recovers_llm_usage_from_assistant_ledger_payload(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    append_conversation_event(
        tmp_path,
        "session-live",
        "turn-usage",
        EVENT_ASSISTANT_MESSAGE,
        status="completed",
        payload={
            "content": "收到，当前对话上下文来自 ledger。",
            "llmUsage": {
                "source": "provider_usage",
                "inputTokens": 111,
                "outputTokens": 22,
                "totalTokens": 133,
                "cachedInputTokens": 0,
                "recordedAt": "2026-05-18T12:05:00",
            },
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200
    assert response.json()["llmUsage"]["source"] == "provider_usage"
    assert response.json()["llmUsage"]["inputTokens"] == 111
    assert response.json()["llmUsage"]["outputTokens"] == 22


def test_persist_turn_result_records_missing_llm_usage_without_estimate(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    events: list[dict[str, object]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: events.append({"args": args, "kwargs": kwargs}) or {"accepted": True},
    )
    session_service._set_session_running("session-live", True, turn_id="turn-missing-usage")

    session_service._persist_session_turn_result(
        "session-live",
        {
            "status": "completed",
            "summary": "已完成。",
            "raw_output": "已完成。",
            "outcome": "done",
            "tool_call_count": 0,
            "tool_trace": [],
        },
        turn_id="turn-missing-usage",
    )

    conversation = load_chat_state(tmp_path)["conversations"][0]
    assert "last_llm_usage" not in conversation
    assert not conversation.get("messages")
    detail = session_service.get_session_detail("session-live")
    assistant_metadata = detail["messages"][-1].get("metadata")
    llm_usage = assistant_metadata["llmUsage"]
    assert assistant_metadata["turnId"] == "turn-missing-usage"
    assert llm_usage["source"] == "missing"
    assert llm_usage["inputTokens"] == 0
    assert detail["llmUsage"]["source"] == "missing"
    assert detail["llmUsage"]["inputTokens"] == 0
    assert any(
        event["args"][:3] == ("conversation", "llm_usage", "conversation.llm_usage.missing")
        for event in events
    )


def test_record_session_llm_usage_warns_when_runtime_scene_rejects_event(monkeypatch):
    warnings: list[tuple[str, str]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: {"accepted": False, "reason": "no_runtime_scene"},
    )
    monkeypatch.setattr(
        session_service._debug_logger,
        "warning",
        lambda message, tag="": warnings.append((message, tag)),
    )

    session_service._record_session_llm_usage_event(
        "session-live",
        "turn-provider-usage",
        {
            "source": "provider_usage",
            "input_tokens": 1000,
            "cached_input_tokens": 250,
            "provider": "xiaomi",
            "model": "mimo-v2.5-pro",
        },
    )

    assert warnings
    assert warnings[-1][1] == "CHAT"
    assert "conversation.llm_usage.recorded" in warnings[-1][0]
    assert "no_runtime_scene" in warnings[-1][0]
    assert "session-live" in warnings[-1][0]
    assert "turn-provider-usage" in warnings[-1][0]


def test_persist_turn_result_preserves_ordered_feedback_events(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: {"accepted": True},
    )
    session_service._set_session_running("session-live", True, turn_id="turn-feedback")

    session_service._persist_session_turn_result(
        "session-live",
        {
            "status": "completed",
            "summary": "已完成。",
            "raw_output": "已完成。",
            "outcome": "done",
            "thought": "再查 React 链路。",
            "tool_trace": [
                {"name": "read_log", "status": "done", "summary": "opened latest log"},
                {"name": "rg", "status": "done", "summary": "searched feedbackEvents"},
            ],
            "feedback_events": [
                {
                    "sequence": 1,
                    "kind": "thought",
                    "status": "running",
                    "summary": "先看日志。",
                    "resultPreview": "先看日志。",
                },
                {
                    "sequence": 2,
                    "kind": "tool",
                    "status": "done",
                    "name": "read_log",
                    "summary": "opened latest log",
                    "relatedThoughtSequence": 1,
                },
                {
                    "sequence": 3,
                    "kind": "thought",
                    "status": "running",
                    "summary": "再查 React 链路。",
                    "resultPreview": "再查 React 链路。",
                },
                {
                    "sequence": 4,
                    "kind": "tool",
                    "status": "done",
                    "name": "rg",
                    "summary": "searched feedbackEvents",
                    "relatedThoughtSequence": 3,
                },
            ],
        },
        turn_id="turn-feedback",
    )

    detail = session_service.get_session_detail("session-live")
    feedback_events = detail["messages"][-1]["feedbackEvents"]
    assert [item["kind"] for item in feedback_events] == ["thought", "tool", "thought", "tool"]
    assert feedback_events[1]["relatedThoughtSequence"] == 1
    assert feedback_events[3]["relatedThoughtSequence"] == 3
    timeline_items = detail["messages"][-1]["timelineItems"]
    assert [item["kind"] for item in timeline_items] == ["thought", "operation", "thought", "operation", "assistant_text"]
    assert timeline_items[0]["text"] == "先看日志。"
    assert timeline_items[1]["operationIds"] == [f"{detail['messages'][-1]['id']}-feedback-2"]
    assert timeline_items[-1]["text"] == "已完成。"


def test_persist_turn_result_normalizes_completed_feedback_statuses(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: {"accepted": True},
    )
    session_service._set_session_running("session-live", True, turn_id="turn-feedback-status")

    session_service._persist_session_turn_result(
        "session-live",
        {
            "status": "completed",
            "summary": "已完成。",
            "raw_output": "已完成。",
            "outcome": "done",
            "feedback_events": [
                {"sequence": 1, "kind": "thought", "status": "completed", "summary": "思考完成。"},
                {"sequence": 2, "kind": "tool", "status": "succeeded", "name": "cli_tool", "summary": "命令完成。"},
                {"sequence": 3, "kind": "status", "status": "finished", "name": "model_request", "summary": "模型完成。"},
            ],
        },
        turn_id="turn-feedback-status",
    )

    detail = session_service.get_session_detail("session-live")
    feedback_events = detail["messages"][-1]["feedbackEvents"]
    assert [item["status"] for item in feedback_events] == ["done", "done", "done"]


def test_persist_turn_result_marks_only_latest_unfinished_feedback_failed(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: {"accepted": True},
    )
    session_service._set_session_running("session-live", True, turn_id="turn-feedback-failed")

    session_service._persist_session_turn_result(
        "session-live",
        {
            "status": "failed",
            "summary": "模型请求失败。",
            "raw_output": "模型请求失败。",
            "outcome": "failed",
            "feedback_events": [
                {"sequence": 1, "kind": "status", "status": "running", "name": "context_prepare", "summary": "准备上下文。"},
                {"sequence": 2, "kind": "status", "status": "running", "name": "agent_prepare", "summary": "绑定 Agent。"},
                {"sequence": 3, "kind": "tool", "status": "done", "name": "cli_tool", "summary": "命令完成。"},
                {"sequence": 4, "kind": "status", "status": "running", "name": "model_request", "summary": "请求模型。"},
            ],
        },
        turn_id="turn-feedback-failed",
    )

    detail = session_service.get_session_detail("session-live")
    feedback_events = detail["messages"][-1]["feedbackEvents"]
    assert [item["status"] for item in feedback_events] == ["done", "done", "done", "failed"]


def test_persist_completed_visible_reply_with_tool_trace_stays_completed(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: {"accepted": True},
    )
    session_service._set_session_running("session-live", True, turn_id="turn-tool-visible")

    session_service._persist_session_turn_result(
        "session-live",
        {
            "status": "completed",
            "summary": "你好！我是 Vibelution agent，目前工作区状态正常。有什么可以帮你的吗？",
            "raw_output": "你好！我是 Vibelution agent，目前工作区状态正常。有什么可以帮你的吗？",
            "tool_call_count": 1,
            "tool_trace": [
                {
                    "name": "get_git_status_summary_tool",
                    "status": "done",
                    "summary": "工作区干净。",
                }
            ],
            "feedback_events": [
                {"sequence": 1, "kind": "status", "status": "running", "name": "context_prepare", "summary": "准备上下文。"},
                {"sequence": 2, "kind": "tool", "status": "done", "name": "get_git_status_summary_tool", "summary": "工作区干净。"},
                {"sequence": 3, "kind": "thought", "status": "running", "summary": "现在可以回应用户。"},
            ],
        },
        turn_id="turn-tool-visible",
    )

    conversation = load_chat_state(tmp_path)["conversations"][0]
    assert conversation["last_turn_status"] == "ready"

    journal_events = load_conversation_events(tmp_path, "session-live")
    completed_event = next(item for item in reversed(journal_events) if item.event_type == "turn_completed")
    assert completed_event.status == "completed"
    assert completed_event.payload["resultStatus"] == "completed"
    assert completed_event.payload["finalStatus"] == "completed"

    detail = session_service.get_session_detail("session-live")
    assistant = detail["messages"][-1]
    assert assistant["content"] == "你好！我是 Vibelution agent，目前工作区状态正常。有什么可以帮你的吗？"
    assert [item["status"] for item in assistant["feedbackEvents"]] == ["done", "done", "done"]


def test_persist_turn_result_records_provider_llm_usage(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    events: list[dict[str, object]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: events.append({"args": args, "kwargs": kwargs}) or {"accepted": True},
    )
    session_service._set_session_running("session-live", True, turn_id="turn-provider-usage")

    session_service._persist_session_turn_result(
        "session-live",
        {
            "status": "completed",
            "summary": "已完成。",
            "raw_output": "已完成。",
            "outcome": "done",
            "tool_call_count": 0,
            "tool_trace": [],
            "llm_usage": {
                "source": "provider_usage",
                "input_tokens": 1500,
                "output_tokens": 120,
                "cached_input_tokens": 300,
                "cache_creation_input_tokens": 450,
            },
        },
        turn_id="turn-provider-usage",
    )

    conversation = load_chat_state(tmp_path)["conversations"][0]
    assert "last_llm_usage" not in conversation
    assert not conversation.get("messages")
    detail = session_service.get_session_detail("session-live")
    assistant_metadata = detail["messages"][-1]["metadata"]
    assert assistant_metadata["llmUsage"]["inputTokens"] == 1500
    assert assistant_metadata["llmUsage"]["cacheCreationInputTokens"] == 450
    assert assistant_metadata["llmUsage"]["cacheHitRate"] == pytest.approx(0.2)
    assert detail["llmUsage"]["source"] == "provider_usage"
    assert detail["llmUsage"]["inputTokens"] == 1500
    assert any(
        event["args"][:3] == ("conversation", "llm_usage", "conversation.llm_usage.recorded")
        and event["kwargs"]["fields"]["inputTokens"] == 1500
        and event["kwargs"]["fields"]["cacheCreationInputTokens"] == 450
        and event["kwargs"]["fields"]["uncachedInputTokens"] == 1200
        for event in events
    )


def test_persist_turn_result_exposes_previous_context_and_cache_composition(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    append_conversation_event(
        tmp_path,
        "session-live",
        "turn-cache-history",
        EVENT_ASSISTANT_MESSAGE,
        status="completed",
        payload={
            "content": "上一轮回答",
            "llmUsage": {
                "source": "provider_usage",
                "inputTokens": 500,
                "outputTokens": 40,
                "cachedInputTokens": 100,
                "cacheCreationInputTokens": 0,
                "recordedAt": "2026-05-18T12:05:00",
            },
        },
    )
    session_service._set_session_running("session-live", True, turn_id="turn-context-composition")

    session_service._persist_session_turn_result(
        "session-live",
        {
            "status": "completed",
            "summary": "已完成。",
            "raw_output": "已完成。",
            "outcome": "done",
            "tool_call_count": 0,
            "tool_trace": [],
            "context_composition": {
                "turnId": "turn-context-composition",
                "recordedAt": "2026-05-18T12:06:00",
                "source": "runtime_assembly",
                "modelInputOrdering": ["history", "current_user"],
                "segments": [
                    {
                        "key": "current_user",
                        "label": "current user",
                        "chars": 8,
                        "tokens": 4,
                        "itemCount": 1,
                        "source": "raw_user_message",
                        "description": "safe summary",
                        "contentPreview": "本轮输入：请审查缓存圆环的外圈分段",
                        "cachePolicy": "never_cache",
                        "includedInModelInput": True,
                    },
                    {
                        "key": "history",
                        "label": "history",
                        "chars": 120,
                        "tokens": 50,
                        "itemCount": 2,
                        "source": "seed_chat_history",
                        "description": "safe summary",
                        "contentPreview": "历史摘要：上一轮确认要显示真实/计算/总均命中",
                        "cachePolicy": "prefix_candidate",
                        "includedInModelInput": True,
                    },
                ],
            },
            "llm_usage": {
                "source": "provider_usage",
                "input_tokens": 1000,
                "output_tokens": 80,
                "cached_input_tokens": 250,
                "cache_creation_input_tokens": 125,
                "provider": "xiaomi",
                "model": "mimo-v2.5-pro",
            },
        },
        turn_id="turn-context-composition",
    )

    detail = session_service.get_session_detail("session-live")

    assert detail["lastContextComposition"]["turnId"] == "turn-context-composition"
    assert [item["key"] for item in detail["lastContextComposition"]["segments"]] == ["current_user", "history"]
    assert "已完成" not in json.dumps(detail["lastContextComposition"], ensure_ascii=False)
    assert detail["lastCacheComposition"]["source"] == "provider_usage"
    assert detail["lastCacheComposition"]["inputTokens"] == 1000
    assert detail["lastCacheComposition"]["cachedInputTokens"] == 250
    assert detail["lastCacheComposition"]["cacheCreationInputTokens"] == 125
    assert detail["lastCacheComposition"]["uncachedInputTokens"] == 750
    assert [item["key"] for item in detail["lastCacheComposition"]["segments"]] == ["cached", "cache_write", "uncached"]
    assert detail["cacheUsage"]["totalInputTokens"] == 1500
    assert detail["cacheUsage"]["totalCachedInputTokens"] == 350
    assert detail["cacheUsage"]["totalObservedTurnCount"] == 2
    assert detail["cacheUsage"]["totalCacheHitRate"] == pytest.approx(350 / 1500)
    assert detail["lastCacheComposition"]["computedInputTokens"] == 1000
    assert detail["lastCacheComposition"]["computedCachedInputTokens"] == 996
    assert detail["lastCacheComposition"]["computedUncachedInputTokens"] == 4
    assert detail["lastCacheComposition"]["computedCacheHitRate"] == pytest.approx(0.996)
    assert detail["lastCacheComposition"]["upperBoundInputTokens"] == 1000
    assert detail["lastCacheComposition"]["upperBoundCachedInputTokens"] == 996
    assert detail["lastCacheComposition"]["upperBoundUncachedInputTokens"] == 4
    assert detail["lastCacheComposition"]["upperBoundCacheHitRate"] == pytest.approx(0.996)
    assert detail["lastCacheComposition"]["calibratedCachedInputTokens"] == 250
    assert detail["lastCacheComposition"]["calibratedCacheHitRate"] == pytest.approx(0.25)
    assert detail["lastCacheComposition"]["predictedInputTokens"] == 1000
    assert detail["lastCacheComposition"]["predictedCachedInputTokens"] == 250
    assert detail["lastCacheComposition"]["predictedUncachedInputTokens"] == 750
    assert detail["lastCacheComposition"]["predictedCacheHitRate"] == pytest.approx(0.25)
    assert detail["lastCacheComposition"]["computedOverestimatedInputTokens"] == 746
    assert detail["lastCacheComposition"]["providerExtraCachedInputTokens"] == 0
    assert detail["lastCacheComposition"]["calibrationStatus"] == "provider_lower_than_computed"
    assert detail["lastCacheComposition"]["predictionStatus"] == "provider_lower_than_computed"
    assert "Xiaomi/MiMo" in detail["lastCacheComposition"]["calibrationReason"]
    assert "Xiaomi/MiMo" in detail["lastCacheComposition"]["predictionReason"]
    assert detail["lastCacheComposition"]["averageInputTokens"] == 1500
    assert detail["lastCacheComposition"]["averageCachedInputTokens"] == 350
    assert detail["lastCacheComposition"]["averageObservedTurnCount"] == 2
    assert detail["lastCacheComposition"]["averageCacheHitRate"] == pytest.approx(350 / 1500)
    computed_segments = detail["lastCacheComposition"]["computedSegments"]
    assert [item["key"] for item in computed_segments] == [
        "system_prompt",
        "agent_protocol",
        "tool_descriptions",
        "tool_schema",
        "provider_unmapped",
        "history",
        "current_user",
    ]
    assert sum(item["tokens"] for item in computed_segments[:5]) == 946
    assert computed_segments[0]["tokens"] == 132
    assert computed_segments[0]["status"] == "computed_hit"
    assert computed_segments[0]["source"] == "provider_input_remainder"
    assert computed_segments[0]["promptCategory"] == "system_prompt"
    assert computed_segments[0]["estimated"] is True
    assert "系统提示词估算段" in computed_segments[0]["contentPreview"]
    assert computed_segments[2]["promptCategory"] == "tool_descriptions"
    assert computed_segments[3]["promptCategory"] == "tool_schema"
    assert computed_segments[5]["status"] == "computed_hit"
    assert computed_segments[5]["contentPreview"] == "历史摘要：上一轮确认要显示真实/计算/总均命中"
    assert computed_segments[6]["status"] == "computed_miss"
    assert computed_segments[6]["contentPreview"] == "本轮输入：请审查缓存圆环的外圈分段"
    calibrated_segments = detail["lastCacheComposition"]["calibratedSegments"]
    assert [item["key"] for item in calibrated_segments] == [
        "system_prompt",
        "agent_protocol",
        "tool_descriptions",
        "tool_schema",
        "provider_unmapped",
        "history",
        "current_user",
    ]
    assert calibrated_segments[0]["observedStatus"] == "observed_miss"
    assert calibrated_segments[0]["observedMissedInputTokens"] == 132
    assert calibrated_segments[1]["observedStatus"] == "observed_miss"
    assert calibrated_segments[1]["observedMissedInputTokens"] == 132
    assert calibrated_segments[2]["observedStatus"] == "observed_miss"
    assert calibrated_segments[2]["observedMissedInputTokens"] == 189
    assert calibrated_segments[3]["observedStatus"] == "observed_partial"
    assert calibrated_segments[3]["observedCachedInputTokens"] == 104
    assert calibrated_segments[3]["observedMissedInputTokens"] == 293
    assert sum(item["computedOverestimatedInputTokens"] for item in calibrated_segments) == 746
    assert calibrated_segments[4]["observedStatus"] == "observed_hit"
    assert calibrated_segments[4]["observedCachedInputTokens"] == 96
    assert calibrated_segments[5]["observedStatus"] == "observed_hit"
    assert calibrated_segments[5]["observedCachedInputTokens"] == 50
    assert calibrated_segments[6]["observedStatus"] == "computed_miss"
    assert calibrated_segments[6]["observedMissedInputTokens"] == 4


def test_cache_composition_context_manifest_adds_bounded_content_previews(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    conversation = load_chat_state(tmp_path)["conversations"][0]

    manifest = session_service._build_last_context_composition(
        conversation=conversation,
        turn_id="turn-preview",
        user_message="请把外圈每段都显示提示词内容，并且不要让小段无法 hover。",
        history_messages=[
            {"role": "user", "content": "上一轮我要求用圆圈显示计算命中。"},
            {"role": "assistant", "content": "已经实现双层圆环，但外圈同色段不容易审查。"},
        ],
        active_task={
            "kind": "chat_turn",
            "status": "running",
            "title": "缓存圆环细节",
            "goal": "显示外圈分段内容摘要",
        },
        runtime_context_block="Agent 上下文：稳定系统前缀。",
        guidance_context_block="最近操作指导：按顺序修复。",
        guidance_context_included=True,
    )

    by_key = {item["key"]: item for item in manifest["segments"]}
    assert by_key["current_user"]["contentPreview"] == "请把外圈每段都显示提示词内容，并且不要让小段无法 hover。"
    assert "上一轮我要求用圆圈显示计算命中" in by_key["history"]["contentPreview"]
    assert by_key["agent_context"]["contentPreview"] == "Agent 上下文：稳定系统前缀。"
    assert by_key["guidance"]["contentPreview"] == "最近操作指导：按顺序修复。"


def test_context_manifest_expands_agent_context_segments_for_cache_audit(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    conversation = load_chat_state(tmp_path)["conversations"][0]

    manifest = session_service._build_last_context_composition(
        conversation=conversation,
        turn_id="turn-agent-context-segments",
        user_message="审查外环提示词分段",
        history_messages=[],
        active_task=None,
        runtime_context_block="agent static + project rules",
        dynamic_runtime_context_block="registry dynamic state",
        dynamic_runtime_context_included=True,
        runtime_context_segments=[
            {
                "key": "agent_runtime",
                "block": "Agent Runtime Context\nAgentCode: A014",
                "placement": "cache_prefix",
                "stability": "agent_static",
                "chars": 38,
                "hash": "agent-hash",
            },
            {
                "key": "prompt_template",
                "block": "Agent prompt template\nFollow project rules.",
                "placement": "cache_prefix",
                "stability": "agent_static",
                "chars": 43,
                "hash": "prompt-hash",
            },
            {
                "key": "project_agent_registry",
                "block": "Registry active work snapshot",
                "placement": "volatile_turn",
                "stability": "turn_dynamic",
                "chars": 29,
                "hash": "registry-hash",
            },
        ],
    )

    by_key = {item["key"]: item for item in manifest["segments"]}
    assert "agent_context" not in by_key
    assert by_key["agent_runtime"]["kind"] == "agent_spec"
    assert by_key["agent_runtime"]["cachePolicy"] == "cacheable"
    assert by_key["agent_runtime"]["contentPreview"].startswith("Agent Runtime Context")
    assert by_key["prompt_template"]["kind"] == "agent_spec"
    assert by_key["project_agent_registry"]["includedInModelInput"] is True
    assert by_key["project_agent_registry"]["cachePolicy"] == "volatile"
    assert by_key["project_agent_registry"]["contentPreview"] == "Registry active work snapshot"


def test_session_detail_live_context_uses_current_missing_cache_composition(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    state = load_chat_state(tmp_path)
    state["conversations"][0]["last_cache_composition"] = {
        "turnId": "previous-turn",
        "recordedAt": "2026-05-18T12:05:00",
        "source": "provider_usage",
        "inputTokens": 1000,
        "cachedInputTokens": 250,
        "uncachedInputTokens": 750,
    }
    save_chat_state(tmp_path, state)
    session_service._set_session_running("session-live", True, turn_id="live-turn")
    session_service._set_session_live_context_composition(
        "session-live",
        {
            "turnId": "live-turn",
            "recordedAt": "2026-05-18T12:07:00",
            "source": "runtime_assembly",
            "segments": [
                {
                    "key": "current_user",
                    "label": "current user",
                    "chars": 10,
                    "tokens": 5,
                    "itemCount": 1,
                }
            ],
        },
        turn_id="live-turn",
    )

    try:
        detail = session_service.get_session_detail("session-live")
    finally:
        session_service._set_session_running("session-live", False, turn_id="live-turn")
        session_service._clear_session_live_output("session-live", turn_id="live-turn")

    assert detail["lastContextComposition"]["turnId"] == "live-turn"
    assert detail["lastCacheComposition"]["turnId"] == "live-turn"
    assert detail["lastCacheComposition"]["source"] == "missing"
    assert detail["lastCacheComposition"]["inputTokens"] == 0
    assert detail["lastCacheComposition"]["segments"][0]["key"] == "missing"


def test_provider_failure_persists_previous_context_composition_with_missing_cache(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    session_service._set_session_running("session-live", True, turn_id="turn-context-failure")

    session_service._persist_session_turn_result(
        "session-live",
        {
            "status": "failed_provider",
            "error": "provider timeout",
            "summary": "provider timeout",
            "context_composition": {
                "turnId": "turn-context-failure",
                "segments": [
                    {
                        "key": "current_user",
                        "label": "current user",
                        "chars": 10,
                        "tokens": 5,
                        "itemCount": 1,
                    }
                ],
            },
        },
        turn_id="turn-context-failure",
    )

    detail = session_service.get_session_detail("session-live")

    assert detail["lastContextComposition"]["turnId"] == "turn-context-failure"
    assert detail["lastContextComposition"]["segments"][0]["key"] == "current_user"
    assert detail["lastCacheComposition"]["source"] == "missing"
    assert detail["lastCacheComposition"]["segments"][0]["key"] == "missing"


def test_session_detail_keeps_persisted_tool_only_assistant_message(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    append_conversation_event(
        tmp_path,
        "session-live",
        "turn-tool-only",
        EVENT_ASSISTANT_MESSAGE,
        status="completed",
        payload={
            "content": "<state",
            "toolCalls": [
                {"name": "read_file_tool", "status": "done", "summary": "session_service.py"},
            ],
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200
    payload = response.json()
    assistant = payload["messages"][-1]
    assert assistant["role"] == "assistant"
    assert assistant["content"] == ""
    assert assistant["toolCalls"] == [
        {"name": "read_file_tool", "status": "done", "summary": "session_service.py"},
    ]
