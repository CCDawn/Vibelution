import base64
import copy
import json
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
import httpx

from config import models as config_models
from core.evaluation.chat_next_state_signals import append_chat_next_state_signal, list_chat_next_state_signals
from config import public_config as public_config_module
from config.models import LLMProfile, ProviderConfig
from config.public_config import LLM_MODEL_PRESETS, UNCONFIGURED_MODEL_REF, load_public_config, public_config_hash
from config.runtime_capabilities import MODEL_CAPABILITY_CACHE_ENV
from core.chat.slash_commands import parse_skill_slash_command
from core.ui.chat_state import load_chat_state, save_chat_state
from core.runtime_manager import constants as runtime_manager_constants
from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes import cli_agents as cli_agent_routes
from core.web.services import (
    agent_directory_service,
    chat_review_service,
    config_service,
    log_service,
    runtime_service,
    runtime_scene_service,
    session_service,
    skill_service,
    self_evolution_control_service,
    self_evolution_service,
    supervised_control_service,
    supervised_worktree_evolution_service,
    workbench_contract_service,
)
import core.web.services.avatar_image_service as avatar_image_service
from tests.helpers.chat_turn_harness import wait_for_matching_event
from tests.helpers.web_runtime_scene import _seed_runtime_scene_bundle

pytestmark = pytest.mark.serial


client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


CONTEXT_PREPARE_LIVE_MESSAGE = "正在准备对话上下文...\n正在读取当前会话、绑定 Agent、工具权限和可恢复的上轮现场。"


def _ensure_preset_model(public_config: dict, preset_id: str) -> dict:
    preset = LLM_MODEL_PRESETS[preset_id]
    model_entry = copy.deepcopy(preset["model"])
    model_entry["provider"] = copy.deepcopy(preset["provider"])
    model_entry.setdefault("label", str(preset.get("label") or model_entry.get("model") or preset_id))
    model_entry.setdefault("api_key_env", f"VIBELUTION_LLM_MODEL_{preset_id.upper()}_API_KEY")
    public_config.setdefault("llm", {}).setdefault("model_library", {})[preset_id] = model_entry
    return model_entry


def _capture_session_lifecycle_events(monkeypatch):
    events = []
    condition = threading.Condition()

    def record_session_turn_lifecycle_event(session_id, phase, **kwargs):
        event = {
            "session_id": session_id,
            "phase": phase,
            "turn_id": kwargs.get("turn_id", ""),
            "outcome": kwargs.get("outcome", ""),
            "fields": dict(kwargs.get("fields") or {}),
        }
        with condition:
            events.append(event)
            condition.notify_all()

    def wait_for_phase(phase, *, timeout=2.0, fields=None):
        expected_fields = fields or {}
        return wait_for_matching_event(
            events,
            timeout_s=timeout,
            predicate=lambda event: (
                event["phase"] == phase
                and all(
                    event["fields"].get(key) == value
                    for key, value in expected_fields.items()
                )
            ),
            condition=condition,
        )

    monkeypatch.setattr(session_service, "_record_session_turn_lifecycle_event", record_session_turn_lifecycle_event)
    return wait_for_phase, events


def _install_session_turn_scheduler(monkeypatch, *, max_active_per_agent: int):
    scheduler = session_service.SessionTurnScheduler(
        agent_key_for_context=session_service._session_scheduler_agent_key,
        session_key_for_context=session_service._session_scheduler_session_key,
        max_active_per_agent=max_active_per_agent,
        now=session_service._perf_counter,
        record_event=session_service._record_scheduler_event_adapter,
        mark_queued=lambda context, position: session_service._mark_session_turn_queued(
            context,
            queue_position=position,
        ),
        mark_dequeued=lambda context: session_service._mark_session_turn_dequeued(context),
        is_session_running=lambda session_id: session_service._is_session_running(session_id),
        is_session_turn_current=lambda session_id, turn_id: session_service._is_session_turn_current(
            session_id,
            turn_id,
        ),
    )
    monkeypatch.setattr(session_service, "_SESSION_TURN_SCHEDULER", scheduler)
    return scheduler


@pytest.fixture(autouse=True)
def disable_runtime_manager_live_control(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(supervised_control_service, "_runtime_manager_live_control_enabled", lambda: False)
    monkeypatch.setattr(self_evolution_control_service, "_runtime_manager_live_control_enabled", lambda: False)


@pytest.fixture(autouse=True)
def isolate_evolution_live_state():
    self_evolution_service.invalidate_self_evolution_overview_cache()
    with supervised_control_service._RUN_STATE_LOCK:
        supervised_control_service._RUN_STATES.clear()
        supervised_control_service._RUN_CONTROLLERS.clear()
        supervised_control_service._ACTIVE_RUN_ID = None
    with supervised_control_service._RUN_SUBSCRIBERS_LOCK:
        supervised_control_service._RUN_SUBSCRIBERS.clear()
    with self_evolution_control_service._RUN_STATE_LOCK:
        self_evolution_control_service._RUN_STATES.clear()
        self_evolution_control_service._RUN_INTERNALS.clear()
        self_evolution_control_service._ACTIVE_RUN_ID = None
    with self_evolution_control_service._RUN_SUBSCRIBERS_LOCK:
        self_evolution_control_service._RUN_SUBSCRIBERS.clear()
    yield
    self_evolution_service.invalidate_self_evolution_overview_cache()
    with supervised_control_service._RUN_STATE_LOCK:
        supervised_control_service._RUN_STATES.clear()
        supervised_control_service._RUN_CONTROLLERS.clear()
        supervised_control_service._ACTIVE_RUN_ID = None
    with supervised_control_service._RUN_SUBSCRIBERS_LOCK:
        supervised_control_service._RUN_SUBSCRIBERS.clear()
    with self_evolution_control_service._RUN_STATE_LOCK:
        self_evolution_control_service._RUN_STATES.clear()
        self_evolution_control_service._RUN_INTERNALS.clear()
        self_evolution_control_service._ACTIVE_RUN_ID = None
    with self_evolution_control_service._RUN_SUBSCRIBERS_LOCK:
        self_evolution_control_service._RUN_SUBSCRIBERS.clear()


def _read_first_sse_event(response):
    event_name = ""
    data_lines = []
    for line in response.iter_lines():
        if line.startswith("event: "):
            event_name = line[len("event: ") :]
            continue
        if line.startswith("data: "):
            data_lines.append(line[len("data: ") :])
            continue
        if line == "":
            if event_name or data_lines:
                return {
                    "event": event_name,
                    "data": "\n".join(data_lines),
                }
    raise AssertionError("Expected at least one SSE event")


def _real_runtime_manager_evolution_paths(kind: str, run_id: str) -> tuple[Path, Path]:
    root = runtime_manager_constants.PROJECT_ROOT / ".runtime" / "runtime-manager" / "evolution" / kind
    return root / "runs" / f"{run_id}.json", root / "index.json"


def _read_optional_text(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.exists() else None


def _restore_real_runtime_index_if_touched(kind: str, run_id: str, original_index_text: str | None) -> None:
    run_path, index_path = _real_runtime_manager_evolution_paths(kind, run_id)
    if run_path.exists():
        run_path.unlink()
    if index_path.exists() and run_id in index_path.read_text(encoding="utf-8"):
        if original_index_text is None:
            index_path.unlink()
        else:
            index_path.write_text(original_index_text, encoding="utf-8")


def _seed_chat_state(project_root, *, task_status="reading", active_task=None, conversations=None):
    seeded_conversations = conversations
    if seeded_conversations is None:
        seeded_conversations = [
            {
                "conversation_id": "session-live",
                "title": "真实会话",
                "updated_at": "2026-05-18T12:00:00",
                "last_turn_status": "failed" if task_status == "failed" else "ready",
                "active_task": active_task,
                "messages": [
                    {
                        "role": "user",
                        "content": "继续前端开发",
                        "timestamp": "2026-05-18T11:55:00",
                    },
                    {
                        "role": "assistant",
                        "content": "<think>internal</think>\n\n已经接到真实状态了。",
                        "timestamp": "2026-05-18T11:56:00",
                        "tool_calls": [
                            {"name": "read_file_tool"},
                            {"function": {"name": "search_code_tool"}},
                        ],
                    },
                ],
            }
        ]
    save_chat_state(
        project_root,
        {
            "version": 1,
            "active_conversation_id": "session-live",
            "updated_at": "2026-05-18T12:00:00",
            "conversations": seeded_conversations,
        },
    )
    session_service._invalidate_session_list_cache()


def _bind_seeded_session_agent(project_root: Path, agent: dict, *, session_id: str = "session-live") -> None:
    state = load_chat_state(project_root)
    agent_id = str(agent.get("agentId") or "").strip()
    for conversation in state.get("conversations") or []:
        if str(conversation.get("conversation_id") or "").strip() == session_id:
            conversation["agent_id"] = agent_id
            conversation["agentId"] = agent_id
            break
    save_chat_state(project_root, state)


def _read_next_state_signals(project_root: Path, *, session_id: str = "", turn_id: str = "") -> list[dict]:
    return list_chat_next_state_signals(project_root=project_root, session_id=session_id, turn_id=turn_id)


def test_session_detail_exists(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    sessions_response = client.get("/api/sessions")
    assert sessions_response.status_code == 200
    sessions = sessions_response.json()
    assert sessions
    assert sessions[0]["id"] == "session-live"

    response = client.get("/api/sessions/session-live")
    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "session-live"
    assert payload["messages"]
    assert payload["messages"][1]["content"] == "已经接到真实状态了。"
    assert payload["messages"][1]["thought"] == "internal"
    assert payload["messages"][1]["toolCalls"] == [
        {"name": "read_file_tool", "status": "done"},
        {"name": "search_code_tool", "status": "done"},
    ]
    assert payload["lastTurnError"] is None
    assert payload["taskSummary"] == "已经接到真实状态了。"
    assert payload["previewTabs"] == []
    assert payload["currentPhase"] == "ready"
    assert payload["contextUsage"]["source"] == "session_messages"
    assert payload["contextUsage"]["messageCount"] == 2
    assert payload["contextUsage"]["userMessageCount"] == 1
    assert payload["contextUsage"]["assistantMessageCount"] == 1
    assert payload["contextUsage"]["toolCallCount"] == 2
    assert payload["contextUsage"]["used"] > 0
    assert payload["contextUsage"]["limit"] > 0


def test_session_query_paginates_searches_and_filters(tmp_path, monkeypatch):
    conversations = [
        {
            "conversation_id": "session-alpha",
            "title": "Alpha planning",
            "agent_id": "agent-a",
            "agentId": "agent-a",
            "session_kind": "main",
            "updated_at": "2026-05-18T12:00:00",
            "messages": [{"role": "assistant", "content": "Alpha summary", "timestamp": "2026-05-18T12:00:00"}],
        },
        {
            "conversation_id": "session-beta",
            "title": "Beta research",
            "agent_id": "agent-b",
            "agentId": "agent-b",
            "session_kind": "child",
            "parent_session_id": "session-alpha",
            "root_session_id": "session-alpha",
            "updated_at": "2026-05-18T13:00:00",
            "messages": [{"role": "assistant", "content": "Beta summary", "timestamp": "2026-05-18T13:00:00"}],
        },
        {
            "conversation_id": "session-gamma",
            "title": "Gamma coding",
            "agent_id": "agent-a",
            "agentId": "agent-a",
            "session_kind": "main",
            "updated_at": "2026-05-18T14:00:00",
            "messages": [{"role": "assistant", "content": "Gamma summary", "timestamp": "2026-05-18T14:00:00"}],
        },
    ]
    _seed_chat_state(tmp_path, conversations=conversations)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    agent_directory_service.save_state(
        {
            "agents": [
                {"agentId": "agent-a", "displayName": "Agent Alpha", "status": "active", "directSessionId": "session-alpha"},
                {"agentId": "agent-b", "displayName": "Agent Beta", "status": "active", "directSessionId": "session-beta"},
            ]
        }
    )

    first_page = client.get("/api/sessions/query?limit=2")
    assert first_page.status_code == 200
    first_payload = first_page.json()
    assert [item["id"] for item in first_payload["items"]] == ["session-gamma", "session-beta"]
    assert first_payload["nextCursor"] == "2"
    assert first_payload["totalEstimate"] == 3

    second_page = client.get(f"/api/sessions/query?limit=2&cursor={first_payload['nextCursor']}")
    assert second_page.status_code == 200
    assert [item["id"] for item in second_page.json()["items"]] == ["session-alpha"]
    assert second_page.json()["nextCursor"] == ""

    search_response = client.get("/api/sessions/query?q=beta")
    assert search_response.status_code == 200
    assert [item["id"] for item in search_response.json()["items"]] == ["session-beta"]

    filtered_response = client.get("/api/sessions/query?agentId=agent-a&sessionKind=main&sort=title_asc")
    assert filtered_response.status_code == 200
    assert {item["id"] for item in filtered_response.json()["items"]} == {"session-alpha", "session-gamma"}


def test_session_query_default_page_skips_per_item_filtering(tmp_path, monkeypatch):
    conversations = [
        {
            "conversation_id": "session-alpha",
            "title": "Alpha",
            "agent_id": "agent-a",
            "updated_at": "2026-05-18T12:00:00",
            "messages": [{"role": "user", "content": "alpha", "timestamp": "2026-05-18T12:00:00"}],
        },
        {
            "conversation_id": "session-beta",
            "title": "Beta",
            "agent_id": "agent-b",
            "updated_at": "2026-05-18T11:00:00",
            "messages": [{"role": "user", "content": "beta", "timestamp": "2026-05-18T11:00:00"}],
        },
    ]
    _seed_chat_state(tmp_path, conversations=conversations)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    agent_directory_service.save_state(
        {
            "agents": [
                {"agentId": "agent-a", "displayName": "Agent Alpha", "status": "active", "directSessionId": "session-alpha"},
                {"agentId": "agent-b", "displayName": "Agent Beta", "status": "active", "directSessionId": "session-beta"},
            ]
        }
    )

    def fail_match(*args, **kwargs):
        raise AssertionError("default session query should slice the existing sorted index")

    monkeypatch.setattr(session_service, "_session_query_matches", fail_match)

    response = client.get("/api/sessions/query?limit=1")

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload["items"]] == ["session-alpha"]
    assert payload["nextCursor"] == "1"
    assert payload["totalEstimate"] == 2


def test_supervised_agent_session_is_hidden_and_preserves_prompt_with_mental_override(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, conversations=[])
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    cfg = runtime_service.get_config().model_copy(deep=True)
    primary_profile = cfg.llm.get_profile(role="primary")
    cfg.llm.model_library["model-a"] = {
        "provider_id": primary_profile.provider_id,
        "model": "model-a",
        "label": "Supervised test model",
    }
    monkeypatch.setattr(session_service, "get_config", lambda: cfg)
    agent_directory_service.save_state(
        {
            "agents": [
                {
                    "agentId": "agent-supervised",
                    "displayName": "Supervised Agent",
                    "status": "active",
                    "directSessionId": "",
                    "llmBindings": {"dialogue": {"modelId": "model-a"}},
                }
            ]
        }
    )
    scheduled_contexts: list[dict] = []

    class DummyAgent:
        def __init__(self):
            self.override = None
            self.seeded_history = []

        def set_mental_model_enabled_override(self, enabled):
            self.override = enabled

        def seed_chat_history(self, messages):
            self.seeded_history = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": f"seen: {initial_prompt}",
                "raw_output": f"seen: {initial_prompt}",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", DummyAgent)
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: scheduled_contexts.append(dict(context)) or session_service._run_session_turn(context),
    )

    created = session_service.create_supervised_agent_session(
        agent_id="agent-supervised",
        title="hidden supervised case",
        metadata={"role": "baseline"},
    )
    session_id = created["id"]
    assert created["sessionKind"] == "supervised"
    assert created["hiddenFromIndex"] is True
    assert session_id not in {item["id"] for item in session_service.list_sessions()}
    assert (agent_directory_service.get_agent("agent-supervised") or {}).get("directSessionId") != session_id

    prompt = "继续。这个监督 case 必须逐字保留，不要改写成上一轮任务。"
    response = session_service.submit_session_message(
        session_id,
        prompt,
        mental_model_enabled=False,
        message_source="supervised_evolution",
    )

    assert response["messages"][-1]["content"] == f"seen: {prompt}"
    assert scheduled_contexts[-1]["user_message"] == prompt
    assert scheduled_contexts[-1]["user_message_source"] == "supervised_evolution"
    assert scheduled_contexts[-1]["mental_model_enabled"] is False
    assert scheduled_contexts[-1]["leases"] == ["readonly_chat"]
    assert session_id not in {item["id"] for item in session_service.list_sessions()}
    assert (agent_directory_service.get_agent("agent-supervised") or {}).get("directSessionId") != session_id


def test_session_query_keeps_active_session_on_default_first_page(tmp_path, monkeypatch):
    conversations = []
    for index in range(60):
        session_id = f"session-{index:02d}"
        conversations.append(
            {
                "conversation_id": session_id,
                "title": f"Session {index:02d}",
                "updated_at": f"2026-05-18T14:{index:02d}:00",
                "messages": [{"role": "assistant", "content": f"Summary {index:02d}", "timestamp": "2026-05-18T14:00:00"}],
            }
        )
    conversations.append(
        {
            "conversation_id": "session-active",
            "title": "Active old session",
            "updated_at": "2026-05-18T09:00:00",
            "messages": [{"role": "assistant", "content": "Active summary", "timestamp": "2026-05-18T09:00:00"}],
        }
    )
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": "session-active",
            "updated_at": "2026-05-18T15:00:00",
            "conversations": conversations,
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/sessions/query?limit=10")

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["id"] == "session-active"
    assert payload["nextCursor"] == "10"


def test_session_summary_exposes_dialogue_model_id(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        conversations=[
            {
                "conversation_id": "session-live",
                "title": "真实会话",
                "agent_id": "agent-live",
                "agentId": "agent-live",
                "updated_at": "2026-05-18T12:00:00",
                "messages": [{"role": "user", "content": "继续前端开发", "timestamp": "2026-05-18T11:55:00"}],
            }
        ],
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    fake_agent = {
        "agentId": "agent-live",
        "agentCode": "A001",
        "displayName": "程听澜",
        "directSessionId": "session-live",
        "primaryMode": "chat",
        "roleKey": "chat-default",
        "promptTemplateId": "prompt-chat-default",
        "workspacePath": "workspace/agents/agent-live",
        "status": "active",
        "llmBindings": {"dialogue": {"modelId": "houmo_qwen3_30b_agent"}},
    }
    agent_directory_service.save_state({"agents": [fake_agent]})
    monkeypatch.setattr(session_service, "get_agent", lambda agent_id, **_kwargs: fake_agent if agent_id == "agent-live" else None)

    sessions_response = client.get("/api/sessions")
    detail_response = client.get("/api/sessions/session-live")

    assert sessions_response.status_code == 200
    assert detail_response.status_code == 200
    assert sessions_response.json()[0]["dialogueModelId"] == "houmo_qwen3_30b_agent"
    assert detail_response.json()["dialogueModelId"] == "houmo_qwen3_30b_agent"


def test_session_detail_marks_agent_direct_session_mismatch(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        conversations=[
            {
                "conversation_id": "session-legacy",
                "title": "旧直连会话",
                "agent_id": "agent-live",
                "agentId": "agent-live",
                "updated_at": "2026-05-18T12:00:00",
                "active_task": {
                    "task_id": "old-task",
                    "kind": "coding",
                    "status": "blocked",
                    "title": "旧任务",
                    "latest_summary": "旧会话残留任务",
                },
                "messages": [{"role": "user", "content": "旧消息", "timestamp": "2026-05-18T11:55:00"}],
            },
            {
                "conversation_id": "session-current",
                "title": "当前直连会话",
                "agent_id": "agent-live",
                "agentId": "agent-live",
                "updated_at": "2026-05-18T12:05:00",
                "messages": [{"role": "user", "content": "当前消息", "timestamp": "2026-05-18T12:05:00"}],
            },
        ],
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    fake_agent = {
        "agentId": "agent-live",
        "agentCode": "A001",
        "displayName": "程听澜",
        "directSessionId": "session-current",
        "primaryMode": "chat",
        "workspacePath": "workspace/agents/agent-live",
        "status": "active",
        "llmBindings": {"dialogue": {"modelId": "houmo_qwen3_30b_agent"}},
    }
    agent_directory_service.save_state({"agents": [fake_agent]})
    monkeypatch.setattr(session_service, "get_agent", lambda agent_id, **_kwargs: fake_agent if agent_id == "agent-live" else None)

    response = client.get("/api/sessions/session-legacy")

    assert response.status_code == 200
    payload = response.json()
    assert payload["agentDirectSessionMismatch"] is True
    assert payload["agentPrimaryDirectSessionId"] == "session-current"
    assert payload["activeTask"] is None
    assert agent_directory_service.get_agent("agent-live")["directSessionId"] == "session-current"


def test_session_detail_uses_targeted_conversation_read(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        conversations=[
            {
                "conversation_id": "session-older",
                "title": "旧会话",
                "updated_at": "2026-05-18T10:00:00",
                "messages": [{"role": "user", "content": "旧消息", "timestamp": "2026-05-18T10:00:00"}],
            },
            {
                "conversation_id": "session-live",
                "title": "真实会话",
                "updated_at": "2026-05-18T12:00:00",
                "messages": [{"role": "user", "content": "目标消息", "timestamp": "2026-05-18T12:00:00"}],
            },
        ],
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    def fail_append_agent_directory_conversations(*args, **kwargs):
        raise AssertionError("session detail should not append every Agent Directory conversation")

    monkeypatch.setattr(
        session_service,
        "_append_agent_directory_conversations",
        fail_append_agent_directory_conversations,
    )

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "session-live"
    assert payload["messages"][0]["content"] == "目标消息"


def test_session_detail_does_not_scan_full_conversation_list_for_known_id(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        conversations=[
            {
                "conversation_id": "session-older",
                "title": "旧会话",
                "updated_at": "2026-05-18T10:00:00",
                "messages": [{"role": "user", "content": "旧消息", "timestamp": "2026-05-18T10:00:00"}],
            },
            {
                "conversation_id": "session-live",
                "title": "真实会话",
                "updated_at": "2026-05-18T12:00:00",
                "messages": [{"role": "user", "content": "目标消息", "timestamp": "2026-05-18T12:00:00"}],
            },
        ],
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    def fail_list_conversations(*args, **kwargs):
        raise AssertionError("session detail should not load full conversations list")

    monkeypatch.setattr(session_service, "_load_conversations", fail_list_conversations)

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "session-live"
    assert payload["messages"][0]["content"] == "目标消息"


def test_create_child_session_api_persists_root_child_relationship(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    agent = agent_directory_service.ensure_agent_for_session("session-live", display_name="真实会话")

    response = client.post(
        "/api/sessions/session-live/child-sessions",
        json={
            "userRequest": "单独修复子对话展示",
            "taskTitle": "子对话展示修复",
            "splitReason": "这是独立 UI 工作",
            "inheritedFacts": ["主会话已确认只做一层子对话"],
            "relevantFiles": ["web/src/routes/ChatCodingRoute.tsx"],
            "constraints": ["不要复制完整历史"],
            "autoStart": False,
            "switchToChild": False,
        },
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    child = payload["childSession"]
    parent = payload["parentSession"]
    child_id = payload["childSessionId"]
    assert payload["parentSessionId"] == "session-live"
    assert payload["autoStarted"] is False
    assert payload["switched"] is False
    assert child["id"] == child_id
    assert child["agentId"] == agent["agentId"]
    assert child["sessionKind"] == "child"
    assert child["parentSessionId"] == "session-live"
    assert child["rootSessionId"] == "session-live"
    assert child["taskTitle"] == "子对话展示修复"
    assert child["handoffContext"]["parentSessionId"] == "session-live"
    assert child["handoffContext"]["sourceSessionId"] == "session-live"
    assert child["handoffContext"]["inheritedFacts"] == ["主会话已确认只做一层子对话"]
    assert child["handoffContext"]["relevantFiles"] == ["web/src/routes/ChatCodingRoute.tsx"]
    assert parent["childSessionIds"] == [child_id]
    assert parent["activeChildSessionId"] == child_id
    assert parent["messages"][-1]["metadata"]["kind"] == "child_session_card"
    assert parent["messages"][-1]["metadata"]["childSessionId"] == child_id

    list_response = client.get("/api/sessions/session-live/child-sessions")
    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()] == [child_id]


def test_create_child_session_from_child_attaches_sibling_to_root(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    agent_directory_service.ensure_agent_for_session("session-live", display_name="真实会话")

    first = client.post(
        "/api/sessions/session-live/child-sessions",
        json={
            "userRequest": "第一件事",
            "taskTitle": "第一件事",
            "autoStart": False,
            "switchToChild": False,
        },
    ).json()
    first_child_id = first["childSessionId"]

    second_response = client.post(
        f"/api/sessions/{first_child_id}/child-sessions",
        json={
            "userRequest": "第二件事",
            "taskTitle": "第二件事",
            "autoStart": False,
            "switchToChild": False,
        },
    )

    assert second_response.status_code == 201, second_response.text
    second = second_response.json()
    second_child_id = second["childSessionId"]
    root_detail = client.get("/api/sessions/session-live").json()
    first_child_detail = client.get(f"/api/sessions/{first_child_id}").json()
    second_child_detail = client.get(f"/api/sessions/{second_child_id}").json()

    assert second["parentSessionId"] == "session-live"
    assert root_detail["childSessionIds"] == [first_child_id, second_child_id]
    assert root_detail["activeChildSessionId"] == second_child_id
    assert first_child_detail["childSessionIds"] == []
    assert second_child_detail["parentSessionId"] == "session-live"
    assert second_child_detail["handoffContext"]["sourceSessionId"] == first_child_id


def test_child_session_tool_uses_current_agent_runtime_session(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    agent = agent_directory_service.ensure_agent_for_session("session-live", display_name="真实会话")
    from tools import session_child_tools

    with agent_directory_service.active_agent_runtime(agent["agentId"], session_id="session-live"):
        raw = session_child_tools.create_child_session_tool(
            user_request="拆出去处理缓存命中问题",
            task_title="缓存命中分析",
            split_reason="新事项与当前 UI 实现不同",
            auto_start=False,
            switch_to_child=False,
        )

    payload = json.loads(raw)
    child_id = payload["childSessionId"]
    assert payload["status"] == "created"
    assert payload["parentSessionId"] == "session-live"
    assert payload["childSession"]["id"] == child_id
    assert payload["childSession"]["agentId"] == agent["agentId"]

    with agent_directory_service.active_agent_runtime(agent["agentId"], session_id="session-live"):
        listed = json.loads(session_child_tools.list_child_sessions_tool())

    assert listed["status"] == "ok"
    assert listed["count"] == 1
    assert listed["childSessions"][0]["id"] == child_id


def test_skills_api_lists_read_only_skill_library(tmp_path, monkeypatch):
    skill_root = tmp_path / "skills"
    skill_dir = skill_root / "brt"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: brt\ndescription: BRT gate\n---\n\n# BRT\n\nStop before implementation.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(skill_service, "default_skill_roots", lambda: [skill_root])

    response = client.get("/api/skills")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "read_only"
    assert payload["counts"]["total"] == 1
    assert payload["skills"][0]["command"] == "/brt"
    assert "content" not in payload["skills"][0]


def test_skills_api_returns_skill_detail(tmp_path, monkeypatch):
    skill_root = tmp_path / "skills"
    skill_dir = skill_root / "brt"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: brt\ndescription: BRT gate\n---\n\n# BRT\n\nAsk one question at a time.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(skill_service, "default_skill_roots", lambda: [skill_root])

    response = client.get("/api/skills/brt")

    assert response.status_code == 200
    payload = response.json()
    assert payload["name"] == "brt"
    assert payload["command"] == "/brt"
    assert "Ask one question at a time." in payload["content"]


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


def test_session_detail_context_usage_comes_from_persisted_messages_after_restart(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    state = load_chat_state(tmp_path)
    state["conversations"][0]["messages"].extend(
        [
            {
                "role": "user",
                "content": "重启后仍然应该统计这一条历史用户消息。",
                "timestamp": "2026-05-18T11:57:00",
            },
            {
                "role": "assistant",
                "content": "收到，当前对话上下文应来自持久化消息，而不是运行时临时计数。",
                "timestamp": "2026-05-18T11:58:00",
            },
        ]
    )
    save_chat_state(tmp_path, state)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["messages"]) == 4
    assert payload["contextUsage"]["messageCount"] == 4
    assert payload["contextUsage"]["userMessageCount"] == 2
    assert payload["contextUsage"]["assistantMessageCount"] == 2
    assert payload["contextUsage"]["source"] == "session_messages"
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
    state = load_chat_state(tmp_path)
    state["conversations"][0]["last_llm_usage"] = {
        "source": "provider_usage",
        "input_tokens": 800,
        "output_tokens": 120,
        "cached_input_tokens": 200,
        "cache_creation_input_tokens": 160,
        "recorded_at": "2026-05-18T12:04:00",
    }
    save_chat_state(tmp_path, state)
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
    state = load_chat_state(tmp_path)
    state["conversations"][0]["last_llm_usage"] = {
        "source": "provider_usage",
        "input_tokens": 2048,
        "output_tokens": 256,
        "cached_input_tokens": 512,
        "cache_creation_input_tokens": 384,
        "provider": "openai",
        "model": "gpt-5",
        "recorded_at": "2026-05-18T12:04:00",
    }
    save_chat_state(tmp_path, state)
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


def test_session_detail_recovers_llm_usage_from_assistant_metadata(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    state = load_chat_state(tmp_path)
    state["conversations"][0]["messages"][1]["metadata"] = {
        "llmUsage": {
            "source": "provider_usage",
            "inputTokens": 111,
            "outputTokens": 22,
            "totalTokens": 133,
            "cachedInputTokens": 0,
            "recordedAt": "2026-05-18T12:05:00",
        }
    }
    save_chat_state(tmp_path, state)
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
    llm_usage = conversation["last_llm_usage"]
    assistant_metadata = conversation["messages"][-1].get("metadata")
    assert llm_usage["source"] == "missing"
    assert llm_usage["inputTokens"] == 0
    assert assistant_metadata is None
    detail = session_service.get_session_detail("session-live")
    assert detail["llmUsage"]["source"] == "missing"
    assert detail["llmUsage"]["inputTokens"] == 0
    assert any(
        event["args"][:3] == ("conversation", "llm_usage", "conversation.llm_usage.missing")
        for event in events
    )


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

    stored_message = load_chat_state(tmp_path)["conversations"][0]["messages"][-1]
    assert [item["kind"] for item in stored_message["feedback_events"]] == ["thought", "tool", "thought", "tool"]
    detail = session_service.get_session_detail("session-live")
    feedback_events = detail["messages"][-1]["feedbackEvents"]
    assert [item["kind"] for item in feedback_events] == ["thought", "tool", "thought", "tool"]
    assert feedback_events[1]["relatedThoughtSequence"] == 1
    assert feedback_events[3]["relatedThoughtSequence"] == 3


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
    assistant_metadata = conversation["messages"][-1]["metadata"]
    assert conversation["last_llm_usage"]["source"] == "provider_usage"
    assert conversation["last_llm_usage"]["inputTokens"] == 1500
    assert conversation["last_llm_usage"]["cacheCreationInputTokens"] == 450
    assert conversation["last_llm_usage"]["uncachedInputTokens"] == 1200
    assert assistant_metadata["llmUsage"]["inputTokens"] == 1500
    assert assistant_metadata["llmUsage"]["cacheCreationInputTokens"] == 450
    assert assistant_metadata["llmUsage"]["cacheHitRate"] == pytest.approx(0.2)
    detail = session_service.get_session_detail("session-live")
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
    state = load_chat_state(tmp_path)
    state["conversations"][0]["messages"].append(
        {
            "role": "assistant",
            "content": "上一轮回答",
            "timestamp": "2026-05-18T12:05:00",
            "metadata": {
                "llmUsage": {
                    "source": "provider_usage",
                    "inputTokens": 500,
                    "outputTokens": 40,
                    "cachedInputTokens": 100,
                    "cacheCreationInputTokens": 0,
                    "recordedAt": "2026-05-18T12:05:00",
                }
            },
        }
    )
    save_chat_state(tmp_path, state)
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
    assert detail["lastCacheComposition"]["averageInputTokens"] == 1500
    assert detail["lastCacheComposition"]["averageCachedInputTokens"] == 350
    assert detail["lastCacheComposition"]["averageObservedTurnCount"] == 2
    assert detail["lastCacheComposition"]["averageCacheHitRate"] == pytest.approx(350 / 1500)
    computed_segments = detail["lastCacheComposition"]["computedSegments"]
    assert [item["key"] for item in computed_segments] == ["system_prompt_overhead", "history", "current_user"]
    assert computed_segments[0]["tokens"] == 946
    assert computed_segments[0]["status"] == "computed_hit"
    assert computed_segments[0]["source"] == "provider_input_remainder"
    assert "system prompt" in computed_segments[0]["contentPreview"]
    assert computed_segments[1]["status"] == "computed_hit"
    assert computed_segments[1]["contentPreview"] == "历史摘要：上一轮确认要显示真实/计算/总均命中"
    assert computed_segments[2]["status"] == "computed_miss"
    assert computed_segments[2]["contentPreview"] == "本轮输入：请审查缓存圆环的外圈分段"


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


def test_session_detail_live_context_uses_current_missing_cache_composition(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    state = load_chat_state(tmp_path)
    state["conversations"][0]["last_llm_usage"] = {
        "source": "missing",
        "inputTokens": 0,
        "outputTokens": 0,
        "totalTokens": 0,
        "cachedInputTokens": 0,
        "recordedAt": "2026-05-18T12:06:00",
    }
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
    state = load_chat_state(tmp_path)
    state["conversations"][0]["messages"].append(
        {
            "role": "assistant",
            "content": "<state",
            "timestamp": "2026-05-18T11:57:00",
            "tool_calls": [
                {"name": "read_file_tool", "status": "done", "summary": "session_service.py"},
            ],
        }
    )
    save_chat_state(tmp_path, state)
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


def test_history_seed_omits_state_only_assistant_messages():
    history = session_service._history_messages_for_agent_seed(
        [
            {"role": "user", "content": "审查对话日志并汇报"},
            {"role": "assistant", "content": "<state>{\"mood\":\"open\"}</state>"},
            {"role": "assistant", "content": "<state"},
            {"role": "assistant", "content": "已完成审查。"},
        ]
    )

    assert [
        {"role": item["role"], "content": item["content"]}
        for item in history
    ] == [
        {"role": "user", "content": "审查对话日志并汇报"},
        {"role": "assistant", "content": "已完成审查。"},
    ]


def test_history_seed_keeps_empty_assistant_message_with_tool_calls():
    history = session_service._history_messages_for_agent_seed(
        [
            {"role": "user", "content": "继续验证"},
            {
                "role": "assistant",
                "content": "",
                "toolCalls": [
                    {
                        "toolName": "cli_tool",
                        "toolCallId": "call_test",
                        "status": "failed",
                        "resultPreview": "Windows detected Unix shell fragment.",
                    }
                ],
            },
        ]
    )

    assert len(history) == 2
    assert history[1]["role"] == "assistant"
    assert history[1]["content"] == ""
    assert history[1]["tool_calls"][0]["name"] == "cli_tool"
    assert history[1]["tool_calls"][0]["resultPreview"] == "Windows detected Unix shell fragment."


def test_history_seed_omits_turn_error_messages():
    history = session_service._history_messages_for_agent_seed(
        [
            {"role": "user", "content": "继续检查模型调用"},
            {
                "role": "assistant",
                "content": "模型服务上游暂时失败，本轮没有完成。",
                "metadata": {
                    "kind": "turn_error",
                    "errorType": "provider_protocol_error",
                },
            },
            {"role": "user", "content": "继续检查最新模型调用状态"},
            {"role": "assistant", "content": "现在可以继续处理。"},
        ]
    )

    assert [
        {"role": item["role"], "content": item["content"]}
        for item in history
    ] == [
        {"role": "user", "content": "继续检查模型调用"},
        {"role": "user", "content": "继续检查最新模型调用状态"},
        {"role": "assistant", "content": "现在可以继续处理。"},
    ]


def test_build_followup_prompt_unwraps_nested_continue_goal():
    prompt = session_service._build_followup_prompt(
        original_prompt="审查对话日志并汇报",
        effective_prompt=(
            "继续完成同一个用户目标：继续完成同一个用户目标：审查对话日志并汇报\n"
            "上一内部回合仍未完成用户目标（第 1 轮）。"
        ),
        latest_result={
            "status": "completed",
            "outcome": "progress",
            "recommended_next_action": "基于已读证据输出结论。",
        },
        history_messages=[{"role": "user", "content": "审查对话日志并汇报"}],
        turn_index=2,
    )

    assert prompt.count("继续完成同一个用户目标：") == 1
    assert "继续完成同一个用户目标：审查对话日志并汇报" in prompt
    assert "继续完成同一个用户目标：继续完成" not in prompt


def test_build_followup_prompt_includes_running_turn_guidance():
    prompt = session_service._build_followup_prompt(
        original_prompt="审查对话日志并汇报",
        effective_prompt="审查对话日志并汇报",
        latest_result={
            "status": "completed",
            "outcome": "progress",
            "recommended_next_action": "基于已读证据输出结论。",
        },
        history_messages=[{"role": "user", "content": "审查对话日志并汇报"}],
        turn_index=2,
        guidance_summaries=["先不要继续实现，先汇报链路风险。"],
    )

    assert "用户在当前运行轮补充了以下引导" in prompt
    assert "先不要继续实现，先汇报链路风险。" in prompt


def test_normalize_persisted_tool_calls_preserves_timeout_as_failed():
    tool_calls = session_service._normalize_persisted_tool_calls(
        [
            {
                "name": "grep_search_tool",
                "status": "done",
                "summary": "[超时] grep_search_tool 执行超时 (30秒)",
            },
            {
                "name": "read_file_tool",
                "summary": "read ok",
            },
        ]
    )

    assert tool_calls[0]["status"] == "failed"
    assert tool_calls[1]["status"] == "done"


def test_normalize_persisted_tool_calls_preserves_safe_details():
    tool_calls = session_service._normalize_persisted_tool_calls(
        [
            {
                "name": "image2_generate_tool",
                "status": "failed",
                "summary": "Read timed out.",
                "args": {
                    "prompt": "生成美女图片",
                    "size": "1024x1024",
                    "_cancel_checker": "internal",
                    "api_key": "secret",
                },
                "error": "HTTPSConnectionPool read timed out",
                "durationMs": 180452,
                "timeoutSeconds": 180,
                "resultType": "str",
                "resultLength": 755,
                "tracePath": "conversations/session/tool_calls.jsonl",
            },
        ]
    )

    assert tool_calls == [
        {
            "name": "image2_generate_tool",
            "status": "failed",
            "summary": "Read timed out.",
            "arguments": {
                "prompt": "生成美女图片",
                "size": "1024x1024",
            },
            "error": "HTTPSConnectionPool read timed out",
            "durationMs": 180452,
            "timeoutSeconds": 180,
            "resultType": "str",
            "resultLength": 755,
            "tracePath": "conversations/session/tool_calls.jsonl",
        }
    ]


def test_normalize_persisted_tool_calls_preserves_error_like_statuses():
    tool_calls = session_service._normalize_persisted_tool_calls(
        [
            {"name": "grep_search_tool", "status": "no_result", "summary": "No match found."},
            {"name": "read_file_tool", "status": "cancelled", "summary": "User cancelled read."},
            {"name": "python_lint_tool", "status": "submitted", "summary": "lint submission accepted."},
            {"name": "task_update_tool", "status": "in_progress", "summary": "task update job running."},
        ]
    )

    assert tool_calls[0]["status"] == "no_result"
    assert tool_calls[1]["status"] == "cancelled"
    assert tool_calls[2]["status"] == "submitted"
    assert tool_calls[3]["status"] == "in_progress"


def test_chat_turn_records_keep_tool_names_when_persisted_calls_have_details():
    records = session_service._build_chat_turn_records_from_messages(
        [
            {"role": "user", "content": "生成图片"},
            {
                "role": "assistant",
                "content": "已调用工具。",
                "tool_calls": [
                    {
                        "name": "image2_generate_tool",
                        "status": "failed",
                        "args": {"prompt": "生成美女图片"},
                        "error": "timeout",
                    }
                ],
            },
        ]
    )

    assert records[0].tool_calls == ["image2_generate_tool"]
    assert records[0].tool_call_count == 1


def test_session_detail_exposes_recent_next_state_signal_summaries(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    append_chat_next_state_signal(
        project_root=tmp_path,
        session_id="session-live",
        turn_id="turn-signal",
        source="runtime",
        kind="provider_failure",
        polarity="negative",
        mode="evaluative",
        related_event_code="conversation.turn_circuit_breaker",
        summary="Provider failed after a partial tool pass.",
        metadata={"rawError": "full provider payload should stay out of session detail"},
        created_at="2026-05-18T11:58:00Z",
        record_scene=False,
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200
    payload = response.json()
    assert payload["nextStateSignals"] == [
        {
            "signalId": payload["nextStateSignals"][0]["signalId"],
            "sessionId": "session-live",
            "turnId": "turn-signal",
            "source": "runtime",
            "kind": "provider_failure",
            "polarity": "negative",
            "mode": "evaluative",
            "relatedEventCode": "conversation.turn_circuit_breaker",
            "createdAt": "2026-05-18T11:58:00Z",
            "summary": "Provider failed after a partial tool pass.",
        }
    ]
    assert "metadata" not in payload["nextStateSignals"][0]
    assert payload["messages"][0]["content"] == "继续前端开发"
    assert all(message["role"] in {"user", "assistant"} for message in payload["messages"])


def test_create_session_persists_new_active_empty_conversation(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.post("/api/sessions")

    assert response.status_code == 201
    payload = response.json()
    assert payload["id"].startswith("session-")
    assert payload["title"] == payload["agentDisplayName"]
    assert payload["taskTitle"] == "新会话"
    assert payload["title"] != "新会话"
    assert payload["messages"] == []
    assert payload["currentPhase"] == "ready"

    state = load_chat_state(tmp_path)
    assert state["active_conversation_id"] == payload["id"]
    assert [item["conversation_id"] for item in state["conversations"]] == [
        "session-live",
        payload["id"],
    ]
    created = state["conversations"][-1]
    assert created["title"] == "新会话"
    assert created["agent_id"] == payload["agentId"]
    assert created["agentId"] == payload["agentId"]
    assert agent_directory_service.get_agent(payload["agentId"])["directSessionId"] == payload["id"]
    assert "agent_profile_id" not in created
    assert "agentProfileId" not in created


def test_create_session_invalidates_agent_index_cache_after_project_root_switch(tmp_path, monkeypatch):
    old_root = tmp_path / "old-project"
    new_root = tmp_path / "new-project"
    _seed_chat_state(old_root)
    _seed_chat_state(new_root)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", old_root)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", old_root)
    agent = agent_directory_service.create_agent_instance(
        display_name="旧项目 Agent",
        direct_session_id="session-live",
        primary_mode="chat",
    )
    old_state = load_chat_state(old_root)
    old_state["conversations"][0]["agent_id"] = agent["agentId"]
    old_state["conversations"][0]["agentId"] = agent["agentId"]
    save_chat_state(old_root, old_state)
    old_cached_title = client.get("/api/sessions").json()[0]["title"]
    assert old_cached_title

    monkeypatch.setattr(session_service, "PROJECT_ROOT", new_root)

    response = client.post("/api/sessions")

    assert response.status_code == 201
    payload = response.json()
    assert payload["title"] != old_cached_title
    assert payload["title"] == payload["agentDisplayName"]
    assert payload["taskTitle"] == "新会话"
    assert payload["agentId"]
    assert agent_directory_service.PROJECT_ROOT == new_root


def test_update_session_title_persists_to_list_and_detail(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.patch(
        "/api/sessions/session-live",
        json={"title": "重命名后的会话"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "session-live"
    assert payload["title"] == "重命名后的会话"

    sessions_response = client.get("/api/sessions")
    assert sessions_response.status_code == 200
    assert sessions_response.json()[0]["title"] == "重命名后的会话"

    state = load_chat_state(tmp_path)
    assert state["conversations"][0]["title"] == "重命名后的会话"


def test_update_root_agent_session_title_syncs_agent_display_name(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    agent = agent_directory_service.create_agent_instance(
        display_name="旧 Agent 名",
        direct_session_id="session-live",
        primary_mode="chat",
    )
    _seed_chat_state(
        tmp_path,
        conversations=[
            {
                "conversation_id": "session-live",
                "title": "旧任务名",
                "agent_id": agent["agentId"],
                "agentId": agent["agentId"],
                "updated_at": "2026-05-18T12:00:00",
                "last_turn_status": "ready",
                "messages": [],
            }
        ],
    )

    response = client.patch("/api/sessions/session-live", json={"title": "新 Agent 名"})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["title"] == "新 Agent 名"
    assert payload["agentDisplayName"] == "新 Agent 名"
    assert agent_directory_service.get_agent(agent["agentId"])["displayName"] == "新 Agent 名"


def test_update_child_session_title_keeps_agent_display_name_separate(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    agent = agent_directory_service.create_agent_instance(
        display_name="根 Agent 名",
        direct_session_id="session-test-root",
        primary_mode="chat",
    )
    agent_display_name = agent["displayName"]
    _seed_chat_state(
        tmp_path,
        conversations=[
            {
                "conversation_id": "session-child",
                "title": "旧子任务",
                "task_title": "旧子任务",
                "taskTitle": "旧子任务",
                "session_kind": "child",
                "sessionKind": "child",
                "parent_session_id": "session-test-root",
                "parentSessionId": "session-test-root",
                "root_session_id": "session-test-root",
                "rootSessionId": "session-test-root",
                "agent_id": agent["agentId"],
                "agentId": agent["agentId"],
                "updated_at": "2026-05-18T12:00:00",
                "last_turn_status": "ready",
                "messages": [],
            }
        ],
    )

    response = client.patch("/api/sessions/session-child", json={"title": "新子任务"})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["title"] == "新子任务"
    assert payload["taskTitle"] == "新子任务"
    assert payload["agentDisplayName"] == agent_display_name
    assert agent_directory_service.get_agent(agent["agentId"])["displayName"] == agent_display_name


def test_update_session_agent_profile_payload_is_rejected(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)

    response = client.patch(
        "/api/sessions/session-live",
        json={"agentProfileId": "subagent_explorer"},
    )

    assert response.status_code == 422

    state = load_chat_state(tmp_path)
    assert "agent_profile_id" not in state["conversations"][0]
    assert "agentProfileId" not in state["conversations"][0]


def test_update_session_agent_id_persists_as_primary_binding(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    agent = agent_directory_service.create_agent_instance(
        display_name="备用会话 Agent",
        llm_bindings={"dialogue": {"modelId": "model-backup"}},
        primary_mode="chat",
        prompt_template_id="prompt-chat-default",
    )

    response = client.patch(
        "/api/sessions/session-live",
        json={"agentId": agent["agentId"]},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["id"] == "session-live"
    assert payload["agentId"] == agent["agentId"]
    assert "agentProfileId" not in payload

    state = load_chat_state(tmp_path)
    assert state["conversations"][0]["agent_id"] == agent["agentId"]
    assert state["conversations"][0]["agentId"] == agent["agentId"]
    assert "agent_profile_id" not in state["conversations"][0]
    assert "agentProfileId" not in state["conversations"][0]
    rebound_agent = agent_directory_service.get_agent(agent["agentId"])
    assert rebound_agent is not None
    assert rebound_agent["directSessionId"] == "session-live"
    assert rebound_agent["llmBindings"]["dialogue"]["modelId"] == "model-backup"
    directory_state = agent_directory_service.load_state()
    assert [
        item["agentId"]
        for item in directory_state.get("agents", [])
        if item.get("status") == "active" and item.get("directSessionId") == "session-live"
    ] == [agent["agentId"]]


def test_session_agent_templates_endpoint_removed():
    response = client.get("/api/sessions/agent-templates")

    assert response.status_code == 404


def test_update_session_title_rejects_empty_title(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.patch(
        "/api/sessions/session-live",
        json={"title": "   "},
    )

    assert response.status_code == 422
    assert "名称" in response.json()["detail"]
    state = load_chat_state(tmp_path)
    assert state["conversations"][0]["title"] == "真实会话"


def test_delete_session_switches_to_latest_remaining_session(tmp_path, monkeypatch):
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": "session-live",
            "updated_at": "2026-05-18T12:00:00",
            "conversations": [
                {
                    "conversation_id": "session-live",
                    "title": "当前会话",
                    "updated_at": "2026-05-18T12:00:00",
                    "last_turn_status": "ready",
                    "messages": [{"role": "user", "content": "删除我", "timestamp": "2026-05-18T12:00:00"}],
                },
                {
                    "conversation_id": "session-older",
                    "title": "旧会话",
                    "updated_at": "2026-05-18T10:00:00",
                    "last_turn_status": "ready",
                    "messages": [{"role": "user", "content": "旧", "timestamp": "2026-05-18T10:00:00"}],
                },
                {
                    "conversation_id": "session-newer",
                    "title": "新会话",
                    "updated_at": "2026-05-18T11:00:00",
                    "last_turn_status": "ready",
                    "messages": [{"role": "user", "content": "新", "timestamp": "2026-05-18T11:00:00"}],
                },
            ],
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    events = []

    def capture_session_delete_event(component, phase, event_code, **kwargs):
        if str(event_code).startswith("session.delete."):
            events.append(
                {
                    "component": component,
                    "phase": phase,
                    "eventCode": event_code,
                    **kwargs,
                }
            )

    monkeypatch.setattr(session_service, "record_runtime_scene_event", capture_session_delete_event)

    response = client.delete("/api/sessions/session-live")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "session-newer"

    state = load_chat_state(tmp_path)
    assert state["active_conversation_id"] == "session-newer"
    assert [item["conversation_id"] for item in state["conversations"]] == [
        "session-older",
        "session-newer",
    ]
    assert [event["eventCode"] for event in events] == [
        "session.delete.requested",
        "session.delete.agent_unbound",
        "session.delete.deleted",
    ]
    assert events[0]["fields"]["phase"] == "ready"
    assert events[1]["fields"]["previousDirectSessionId"] == "session-live"
    assert events[2]["fields"]["nextActiveSessionId"] == "session-newer"


def test_delete_session_keeps_bound_agent_active(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    agent = agent_directory_service.ensure_agent_for_session(
        "session-live",
        display_name="科研复核 Agent",
        primary_mode="research",
        role_key="research_review",
        prompt_template_id="prompt-research-review",
    )
    state = load_chat_state(tmp_path)
    state["conversations"][0]["agent_id"] = agent["agentId"]
    state["conversations"][0]["agentId"] = agent["agentId"]
    save_chat_state(tmp_path, state)

    response = client.delete("/api/sessions/session-live")

    assert response.status_code == 200
    kept_agent = agent_directory_service.get_agent(agent["agentId"], include_archived=True)
    assert kept_agent is not None
    assert kept_agent["status"] == "active"


def test_delete_bound_direct_session_rebinds_agent_without_reviving_old_session(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    events = []
    agent = agent_directory_service.ensure_agent_for_session(
        "session-live",
        display_name="科研复核 Agent",
        primary_mode="research",
        role_key="research_review",
        prompt_template_id="prompt-research-review",
    )
    state = load_chat_state(tmp_path)
    state["conversations"][0]["agent_id"] = agent["agentId"]
    state["conversations"][0]["agentId"] = agent["agentId"]
    save_chat_state(tmp_path, state)

    def capture_session_delete_event(component, phase, event_code, **kwargs):
        if str(event_code).startswith("session.delete."):
            events.append(
                {
                    "component": component,
                    "phase": phase,
                    "eventCode": event_code,
                    **kwargs,
                }
            )

    monkeypatch.setattr(session_service, "record_runtime_scene_event", capture_session_delete_event)

    response = client.delete("/api/sessions/session-live")

    assert response.status_code == 200
    rebound_agent = agent_directory_service.get_agent(agent["agentId"], include_archived=True)
    assert rebound_agent is not None
    assert rebound_agent["status"] == "active"
    assert rebound_agent["directSessionId"] == ""
    assert session_service.get_session_detail("session-live") is None
    sessions = session_service.list_sessions()
    assert "session-live" not in {item["id"] for item in sessions}
    assert agent["agentId"] not in {item["agentId"] for item in sessions}
    unbound_events = [event for event in events if event["eventCode"] == "session.delete.agent_unbound"]
    assert len(unbound_events) == 1
    assert unbound_events[0]["fields"]["agentId"] == agent["agentId"]
    assert unbound_events[0]["fields"]["previousDirectSessionId"] == "session-live"


def test_delete_last_session_creates_replacement(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.delete("/api/sessions/session-live")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"].startswith("session-")
    assert payload["id"] != "session-live"
    assert payload["title"] == "新会话"
    assert payload["agentId"] == ""
    assert payload["messages"] == []

    state = load_chat_state(tmp_path)
    assert state["active_conversation_id"] == payload["id"]
    assert [item["conversation_id"] for item in state["conversations"]] == [payload["id"]]


def test_delete_session_prefer_async_returns_lightweight_handoff(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        conversations=[
            {
                "conversation_id": "session-live",
                "title": "当前会话",
                "updated_at": "2026-05-18T09:00:00",
                "last_turn_status": "ready",
                "messages": [{"role": "user", "content": "当前", "timestamp": "2026-05-18T09:00:00"}],
            },
            {
                "conversation_id": "session-next",
                "title": "下一个会话",
                "updated_at": "2026-05-18T10:00:00",
                "last_turn_status": "ready",
                "messages": [{"role": "user", "content": "下一个", "timestamp": "2026-05-18T10:00:00"}],
            },
        ],
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.delete("/api/sessions/session-live", headers={"Prefer": "respond-async"})

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "deleted": True,
        "deletedSessionId": "session-live",
        "nextActiveSessionId": "session-next",
        "replacementDirectSessionId": "",
    }
    assert session_service.get_session_detail("session-live") is None


def test_delete_session_rejects_running_turn(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    events = []

    def capture_session_delete_event(component, phase, event_code, **kwargs):
        if str(event_code).startswith("session.delete."):
            events.append(
                {
                    "component": component,
                    "phase": phase,
                    "eventCode": event_code,
                    **kwargs,
                }
            )

    monkeypatch.setattr(session_service, "record_runtime_scene_event", capture_session_delete_event)

    session_service._set_session_running("session-live", True)
    try:
        response = client.delete("/api/sessions/session-live")
    finally:
        session_service._set_session_running("session-live", False)

    assert response.status_code == 409
    assert "运行" in response.json()["detail"]
    state = load_chat_state(tmp_path)
    assert [item["conversation_id"] for item in state["conversations"]] == ["session-live"]
    assert [event["eventCode"] for event in events] == [
        "session.delete.requested",
        "session.delete.blocked",
    ]
    assert events[0]["fields"]["phase"] == "running"
    assert events[1]["fields"]["reason"] == "busy"


def test_session_detail_uses_live_phase_while_turn_is_running(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    session_service._set_session_running("session-live", True)
    try:
        response = client.get("/api/sessions/session-live")
    finally:
        session_service._set_session_running("session-live", False)

    assert response.status_code == 200
    payload = response.json()
    assert payload["currentPhase"] == "running"


def test_session_detail_exposes_pre_model_progress_stage(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    session_service._set_session_running("session-live", True, turn_id="turn-progress")
    try:
        session_service._set_session_waiting_live_output("session-live", turn_id="turn-progress")
        response = client.get("/api/sessions/session-live")
    finally:
        session_service._clear_session_live_output("session-live")
        session_service._set_session_running("session-live", False, turn_id="turn-progress")

    assert response.status_code == 200
    payload = response.json()
    live_message = payload["messages"][-1]
    assert live_message["streaming"] is True
    assert live_message["streamStage"] == "context_prepare"
    assert live_message["content"] == CONTEXT_PREPARE_LIVE_MESSAGE


def test_session_detail_exposes_pre_model_progress_as_ordered_feedback_events(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    session_service._set_session_running("session-live", True, turn_id="turn-progress-events")
    try:
        session_service._persist_chat_turn_work_run(
            session_id="session-live",
            turn_id="turn-progress-events",
            status="running",
            user_message="继续",
            updated_at="2026-06-05T00:00:00",
        )
        session_service._set_session_turn_progress_live_output("session-live", "context_prepare", turn_id="turn-progress-events")
        session_service._set_session_turn_progress_live_output("session-live", "agent_prepare", turn_id="turn-progress-events")
        session_service._set_session_turn_progress_live_output("session-live", "model_request", turn_id="turn-progress-events")
        response = client.get("/api/sessions/session-live")
    finally:
        session_service._clear_session_live_output("session-live", turn_id="turn-progress-events")
        session_service._set_session_running("session-live", False, turn_id="turn-progress-events")
        session_service._persist_chat_turn_work_run(
            session_id="session-live",
            turn_id="turn-progress-events",
            status="completed",
            finished_at="2026-06-05T00:00:10",
            updated_at="2026-06-05T00:00:10",
        )

    assert response.status_code == 200
    payload = response.json()
    live_message = payload["messages"][-1]
    assert live_message["streamStage"] == "model_request"
    assert [item["kind"] for item in live_message["feedbackEvents"]] == ["status", "status", "status"]
    assert [item["name"] for item in live_message["feedbackEvents"]] == [
        "context_prepare",
        "agent_prepare",
        "model_request",
    ]
    work_run = session_service._WORK_RUN_STORE.load_snapshot("chat_turn", "turn-progress-events")
    assert work_run is not None
    assert work_run["updatedAt"] != "2026-06-05T00:00:00"
    assert "正在请求模型" in work_run["summary"]


def test_session_detail_prefers_running_turn_context_composition(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        conversations=[
            {
                "conversation_id": "session-live",
                "title": "真实会话",
                "updated_at": "2026-05-18T12:00:00",
                "last_turn_status": "ready",
                "last_context_composition": {
                    "turnId": "old-turn",
                    "recordedAt": "2026-06-04T00:00:00",
                    "totalTokens": 10,
                    "segments": [{"key": "history", "label": "history", "tokens": 10, "chars": 100}],
                },
                "messages": [
                    {"role": "user", "content": "上一轮", "timestamp": "2026-05-18T11:55:00"},
                    {"role": "assistant", "content": "完成", "timestamp": "2026-05-18T11:56:00"},
                ],
            }
        ],
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    session_service._set_session_running("session-live", True, turn_id="new-turn")
    try:
        session_service._set_session_live_context_composition(
            "session-live",
            {
                "turnId": "new-turn",
                "recordedAt": "2026-06-05T00:00:00",
                "source": "runtime_assembly",
                "totalTokens": 42,
                "segments": [{"key": "current_user", "label": "current user", "tokens": 42, "chars": 420}],
            },
            turn_id="new-turn",
        )
        response = client.get("/api/sessions/session-live")
    finally:
        session_service._clear_session_live_output("session-live", turn_id="new-turn")
        session_service._set_session_running("session-live", False, turn_id="new-turn")

    assert response.status_code == 200
    payload = response.json()
    assert payload["lastContextComposition"]["turnId"] == "new-turn"
    assert payload["lastContextComposition"]["totalTokens"] == 42
    assert payload["lastContextComposition"]["segments"][0]["key"] == "current_user"


def test_session_detail_overrides_active_task_status_from_running_work_run(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        active_task={
            "task_id": "previous-task",
            "kind": "coding",
            "status": "done",
            "title": "上一轮任务",
            "latest_summary": "上一轮已结束。",
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    session_service._set_session_running("session-live", True, turn_id="turn-active-task")
    try:
        session_service._persist_chat_turn_work_run(
            session_id="session-live",
            turn_id="turn-active-task",
            status="running",
            user_message="继续",
            summary="正在请求模型，等待首个响应片段...",
        )
        response = client.get("/api/sessions/session-live")
    finally:
        session_service._set_session_running("session-live", False, turn_id="turn-active-task")
        session_service._persist_chat_turn_work_run(
            session_id="session-live",
            turn_id="turn-active-task",
            status="completed",
            finished_at="2026-06-05T00:00:10",
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["currentPhase"] == "running"
    assert payload["activeTask"] is None


def test_session_detail_hydrates_file_context_from_saved_active_task(tmp_path, monkeypatch):
    (tmp_path / "web" / "src" / "routes").mkdir(parents=True, exist_ok=True)
    (tmp_path / "core" / "web" / "services").mkdir(parents=True, exist_ok=True)
    (tmp_path / "web" / "src" / "routes" / "ChatCodingRoute.tsx").write_text("export {};\n", encoding="utf-8")
    (tmp_path / "core" / "web" / "services" / "session_service.py").write_text("pass\n", encoding="utf-8")
    _seed_chat_state(
        tmp_path,
        active_task={
            "task_id": "session-live-coding-task",
            "kind": "coding",
            "status": "done",
            "title": "修复会话页面文件上下文",
            "read_files": ["web/src/routes/ChatCodingRoute.tsx"],
            "changed_files": ["core/web/services/session_service.py"],
            "verification_status": "passed",
            "verification_summary": "2 passed in 0.31s",
            "default_file_context": "core/web/services/session_service.py",
            "metadata": {"source": "task_tool"},
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200
    payload = response.json()
    assert payload["readFiles"] == ["web/src/routes/ChatCodingRoute.tsx"]
    assert payload["changedFiles"] == ["core/web/services/session_service.py"]
    assert payload["defaultFileContext"] == "core/web/services/session_service.py"
    assert payload["previewTabs"] == [
        "core/web/services/session_service.py",
        "web/src/routes/ChatCodingRoute.tsx",
    ]
    assert payload["activePreviewPath"] == "core/web/services/session_service.py"
    assert payload["activeTask"]["title"] == "修复会话页面文件上下文"
    assert payload["activeTask"]["changedFiles"] == ["core/web/services/session_service.py"]
    assert payload["activeTask"]["readFiles"] == ["web/src/routes/ChatCodingRoute.tsx"]


def test_session_events_stream_initial_detail(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    detail = session_service.get_session_detail("session-live")
    assert detail is not None

    stream = session_service.stream_session_events("session-live", initial_detail=detail)
    raw_event = next(stream)
    stream.close()

    class _SingleEventResponse:
        def iter_lines(self):
            for line in str(raw_event).splitlines():
                yield line
            yield ""

    event = _read_first_sse_event(_SingleEventResponse())

    assert event["event"] == "session_detail"
    payload = json.loads(event["data"])
    assert payload["type"] == "session_detail"
    assert payload["sessionId"] == "session-live"
    assert payload["detail"]["id"] == "session-live"
    assert payload["detail"]["messages"][1]["content"] == "已经接到真实状态了。"


def test_session_detail_snapshot_publish_records_perf_event(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    recorded_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )

    detail = session_service.get_session_detail("session-live")
    assert detail is not None
    stream = session_service.stream_session_events("session-live", initial_detail=detail)
    next(stream)
    try:
        session_service._publish_session_detail_snapshot("session-live")
    finally:
        stream.close()

    published_events = [item for item in recorded_events if item[0][2] == "session.detail_snapshot.published"]
    assert len(published_events) == 1
    fields = published_events[0][1]["fields"]
    assert fields["sessionId"] == "session-live"
    assert fields["subscriberCount"] == 1
    assert fields["deliveredCount"] == 1
    assert fields["droppedCount"] == 0
    assert fields["messageCount"] == len(detail["messages"])
    assert fields["elapsedMs"] >= 0


def test_session_detail_snapshot_publish_coalesces_stale_detail_events(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    recorded_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )

    subscriber: queue.Queue[dict[str, object]] = queue.Queue(maxsize=8)
    session_service._register_session_stream_subscriber("session-live", subscriber)
    try:
        for index in range(3):
            subscriber.put_nowait({"type": "session_detail", "detail": {"stale": index}})
        session_service._publish_session_detail_snapshot("session-live")
    finally:
        session_service._unregister_session_stream_subscriber("session-live", subscriber)

    assert subscriber.qsize() == 1
    latest = subscriber.get_nowait()
    assert latest["type"] == "session_detail"
    assert latest["detail"]["id"] == "session-live"
    published_events = [item for item in recorded_events if item[0][2] == "session.detail_snapshot.published"]
    assert published_events[-1][1]["fields"]["deliveredCount"] == 1
    assert published_events[-1][1]["fields"]["droppedCount"] == 3


def test_session_live_output_publishes_lightweight_assistant_delta_without_detail_snapshot(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    recorded_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )

    detail_calls = 0
    original_get_session_detail = session_service.get_session_detail

    def counted_get_session_detail(*args, **kwargs):
        nonlocal detail_calls
        detail_calls += 1
        return original_get_session_detail(*args, **kwargs)

    monkeypatch.setattr(session_service, "get_session_detail", counted_get_session_detail)

    subscriber: queue.Queue[dict[str, object]] = queue.Queue(maxsize=8)
    session_service._register_session_stream_subscriber("session-live", subscriber)
    session_service._set_session_running("session-live", True, turn_id="turn-running")
    try:
        session_service._set_session_live_output("session-live", turn_id="turn-running", content="hello")
        session_service._set_session_live_output(
            "session-live",
            turn_id="turn-running",
            thought="thinking",
            feedback_events=[{"kind": "status", "name": "model_response"}],
        )
    finally:
        session_service._set_session_running("session-live", False, turn_id="turn-running")
        session_service._unregister_session_stream_subscriber("session-live", subscriber)
        with session_service._SESSION_LIVE_OUTPUTS_LOCK:
            session_service._SESSION_LIVE_OUTPUTS.pop("session-live", None)

    assert detail_calls == 0
    assert subscriber.qsize() == 1
    event = subscriber.get_nowait()
    assert event["type"] == "assistant_delta"
    assert event["sessionId"] == "session-live"
    assert event["turnId"] == "turn-running"
    assert event["content"] == ""
    assert event["thought"] == ""
    assert event["contentDelta"] == "hello"
    assert event["thoughtDelta"] == "thinking"
    assert event["replaceContent"] is False
    assert event["replaceThought"] is False
    assert event["feedbackEvents"][0]["kind"] == "status"
    assert event["feedbackEvents"][0]["name"] == "model_response"
    assert event["done"] is False
    delta_events = [item for item in recorded_events if item[0][2] == "session.assistant_delta.published"]
    snapshot_events = [item for item in recorded_events if item[0][2] == "session.detail_snapshot.published"]
    assert len(delta_events) == 2
    assert not snapshot_events
    assert any(item[1]["fields"]["contentChars"] == 5 for item in delta_events)
    assert any(item[1]["fields"]["thoughtChars"] == 8 for item in delta_events)
    fields = delta_events[-1][1]["fields"]
    assert fields["subscriberCount"] == 1


def test_session_detail_snapshot_publish_throttles_busy_snapshots(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    recorded_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )
    monkeypatch.setattr(session_service, "_SESSION_STREAM_MIN_BUSY_SNAPSHOT_INTERVAL_SECONDS", 10.0)
    with session_service._SESSION_STREAM_LAST_SNAPSHOT_LOCK:
        session_service._SESSION_STREAM_LAST_SNAPSHOT_AT.pop("session-live", None)
        session_service._SESSION_STREAM_THROTTLED_COUNTS.pop("session-live", None)

    subscriber: queue.Queue[dict[str, object]] = queue.Queue(maxsize=8)
    session_service._register_session_stream_subscriber("session-live", subscriber)
    session_service._set_session_running("session-live", True, turn_id="turn-running")
    try:
        session_service._publish_session_detail_snapshot("session-live")
        session_service._publish_session_detail_snapshot("session-live")
    finally:
        session_service._set_session_running("session-live", False, turn_id="turn-running")
        session_service._unregister_session_stream_subscriber("session-live", subscriber)
        with session_service._SESSION_STREAM_LAST_SNAPSHOT_LOCK:
            session_service._SESSION_STREAM_LAST_SNAPSHOT_AT.pop("session-live", None)
            session_service._SESSION_STREAM_THROTTLED_COUNTS.pop("session-live", None)

    assert subscriber.qsize() == 1
    published_events = [item for item in recorded_events if item[0][2] == "session.detail_snapshot.published"]
    throttled_events = [item for item in recorded_events if item[0][2] == "session.detail_snapshot.throttled"]
    assert len(published_events) == 1
    assert len(throttled_events) == 1
    assert throttled_events[0][1]["fields"]["skippedCount"] == 1


def test_session_detail_snapshot_publish_does_not_throttle_terminal_snapshots(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="failed")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    recorded_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )
    monkeypatch.setattr(session_service, "_SESSION_STREAM_MIN_BUSY_SNAPSHOT_INTERVAL_SECONDS", 10.0)
    with session_service._SESSION_STREAM_LAST_SNAPSHOT_LOCK:
        session_service._SESSION_STREAM_LAST_SNAPSHOT_AT.pop("session-live", None)
        session_service._SESSION_STREAM_THROTTLED_COUNTS.pop("session-live", None)

    subscriber: queue.Queue[dict[str, object]] = queue.Queue(maxsize=8)
    session_service._register_session_stream_subscriber("session-live", subscriber)
    try:
        session_service._publish_session_detail_snapshot("session-live")
        session_service._publish_session_detail_snapshot("session-live")
    finally:
        session_service._unregister_session_stream_subscriber("session-live", subscriber)
        with session_service._SESSION_STREAM_LAST_SNAPSHOT_LOCK:
            session_service._SESSION_STREAM_LAST_SNAPSHOT_AT.pop("session-live", None)
            session_service._SESSION_STREAM_THROTTLED_COUNTS.pop("session-live", None)

    assert subscriber.qsize() == 1
    published_events = [item for item in recorded_events if item[0][2] == "session.detail_snapshot.published"]
    throttled_events = [item for item in recorded_events if item[0][2] == "session.detail_snapshot.throttled"]
    assert len(published_events) == 2
    assert not throttled_events


def test_session_events_stream_rejects_missing_session():
    response = client.get("/api/sessions/missing-session/events")
    assert response.status_code == 404
    assert response.json()["detail"] == "Session not found"


def test_cli_agent_terminal_stop_route_records_lifecycle_event(monkeypatch):
    recorded = []

    terminal_session = {
        "terminalSessionId": "term-1",
        "sourceSessionId": "session-live",
        "cliRunId": "cli-run-1",
        "adapterId": "mimo_code",
        "label": "MiMo Code",
    }

    def fake_append(session_id, *, event, terminal_session):
        recorded.append((session_id, event, dict(terminal_session)))
        return {
            "id": "session-live-message-2",
            "role": "assistant",
            "content": "MiMo Code 已关闭。",
            "timestamp": "2026-06-14T10:00:00",
            "metadata": {
                "kind": "cli_agent_lifecycle",
                "event": "closed",
                "cliRunId": "cli-run-1",
            },
        }

    monkeypatch.setattr(
        cli_agent_routes,
        "stop_cli_agent_terminal_session",
        lambda terminal_session_id: {**terminal_session, "terminalSessionId": terminal_session_id},
    )
    monkeypatch.setattr(cli_agent_routes, "append_cli_agent_lifecycle_event", fake_append)

    response = client.post("/api/cli-agents/terminal-sessions/term-1/stop")

    assert response.status_code == 200
    payload = response.json()
    assert payload["terminalSessionId"] == "term-1"
    assert payload["lifecycleEvent"]["metadata"]["kind"] == "cli_agent_lifecycle"
    assert payload["lifecycleEvent"]["metadata"]["cliRunId"] == "cli-run-1"
    assert recorded == [("session-live", "closed", {**terminal_session, "terminalSessionId": "term-1"})]


def test_submit_session_message_rejects_archived_agent_without_mutating_session(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    detail = session_service.create_chat_session(title="归档 Agent")
    agent_directory_service.archive_agent_instance(detail["agentId"])
    events = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)) or {"accepted": True},
    )
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: pytest.fail("archived Agent sessions must not schedule turns"),
    )

    with pytest.raises(session_service.SessionValidationError, match="已归档|archived"):
        session_service.submit_session_message(detail["id"], "这条消息不应该进入运行队列")

    state = load_chat_state(tmp_path)
    conversation = state["conversations"][0]
    assert conversation["messages"] == []
    blocked_events = [item for item in events if item[0][2] == "conversation.turn.blocked_archived_agent"]
    assert len(blocked_events) == 1
    assert blocked_events[0][1]["fields"]["agentId"] == detail["agentId"]


def test_edit_resubmit_session_message_rejects_archived_agent_without_mutating_session(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    detail = session_service.create_chat_session(title="归档重发 Agent")
    state = load_chat_state(tmp_path)
    conversation = state["conversations"][0]
    conversation["messages"] = [
        {"role": "user", "content": "原始消息", "timestamp": "2026-05-29T08:40:00+00:00"}
    ]
    save_chat_state(tmp_path, state)
    agent_directory_service.archive_agent_instance(detail["agentId"])
    events = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)) or {"accepted": True},
    )
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: pytest.fail("archived Agent edit-resubmit must not schedule turns"),
    )

    with pytest.raises(session_service.SessionValidationError, match="已归档|archived"):
        session_service.edit_and_resubmit_session_message(
            detail["id"],
            f"{detail['id']}-message-1",
            "编辑后的消息不应进入运行队列",
        )

    next_state = load_chat_state(tmp_path)
    next_conversation = next_state["conversations"][0]
    assert next_conversation["messages"][0]["content"] == "原始消息"
    assert next_conversation.get("last_turn_status") != "running"
    blocked_events = [item for item in events if item[0][2] == "conversation.turn.blocked_archived_agent"]
    assert len(blocked_events) == 1
    assert blocked_events[0][1]["fields"]["agentId"] == detail["agentId"]


def test_run_session_turn_blocks_if_agent_archived_after_scheduling(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    detail = session_service.create_chat_session(title="排队后归档 Agent")
    scheduled_contexts = []
    events = []
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: scheduled_contexts.append(context))
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)) or {"accepted": True},
    )
    monkeypatch.setattr(
        session_service,
        "create_chat_agent",
        lambda **_kwargs: pytest.fail("archived Agent worker must not create runtime"),
    )

    session_service.submit_session_message(detail["id"], "这条消息排队后 Agent 会被归档")
    assert len(scheduled_contexts) == 1

    agent_directory_service.archive_agent_instance(detail["agentId"])
    session_service._run_session_turn(scheduled_contexts[0])

    next_detail = session_service.get_session_detail(detail["id"])
    assert next_detail["currentPhase"] == "failed"
    assert next_detail["messages"][-1]["role"] == "assistant"
    assert "已归档" in next_detail["messages"][-1]["content"]
    blocked_events = [item for item in events if item[0][2] == "conversation.turn.blocked_archived_agent"]
    assert len(blocked_events) == 1
    assert blocked_events[0][1]["fields"]["agentId"] == detail["agentId"]


def test_submit_session_message_runs_turn_and_persists_reply(tmp_path, monkeypatch):
    (tmp_path / "web" / "src" / "routes").mkdir(parents=True, exist_ok=True)
    (tmp_path / "core" / "web" / "services").mkdir(parents=True, exist_ok=True)
    (tmp_path / "web" / "src" / "routes" / "ChatCodingRoute.tsx").write_text("export {};\n", encoding="utf-8")
    (tmp_path / "core" / "web" / "services" / "session_service.py").write_text("pass\n", encoding="utf-8")
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    base_config = session_service.get_config().model_copy(deep=True)
    primary_profile = base_config.llm.get_profile(role="primary")
    dialogue_model_id = "session-message-dialogue-test"
    base_config.llm.model_library[dialogue_model_id] = {
        "provider_id": primary_profile.provider_id,
        "model": "gpt-5.5",
        "label": "Session message dialogue test",
    }
    monkeypatch.setattr(session_service, "get_config", lambda: base_config)
    session_agent = agent_directory_service.ensure_agent_for_session(
        "session-live",
        display_name="真实会话",
        llm_bindings={"dialogue": {"modelId": dialogue_model_id}},
        prompt_template_id="prompt-chat-default",
    )
    _bind_seeded_session_agent(tmp_path, session_agent)
    session_service._invalidate_session_list_cache()
    recorded_scene_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_scene_events.append((args, kwargs)) or {"accepted": True},
    )

    class DummyAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            assert "ChatCodingRoute.tsx" in initial_prompt
            return {
                "status": "completed",
                "summary": "已完成网页对话提交接线。",
                "raw_output": "已完成网页对话提交接线。",
                "reasoning_content": "先确认消息模型，再把思考与心智快照一起落盘。",
                "mental_snapshot": {
                    "mood": "专注",
                    "feeling": "主链路已经清楚了。",
                    "whisper": "把思考和回答放在同一张卡片里。",
                    "summary": "主链路已经清楚了。",
                    "cognitiveState": "productive",
                    "confidence": 0.86,
                    "sampleSize": 4,
                    "interventionCount": 1,
                    "updatedAt": "2026-05-18T12:01:00",
                    "source": "state",
                },
                "outcome": "done",
                "read_files": ["web/src/routes/ChatCodingRoute.tsx"],
                "changed_files": ["core/web/services/session_service.py"],
                "verification_status": "passed",
                "verification_summary": "2 passed in 0.31s",
                "tool_call_count": 2,
                "tool_trace": [
                    {"name": "read_file_tool"},
                    {"function": {"name": "apply_patch_tool"}},
                ],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "请继续修复 web/src/routes/ChatCodingRoute.tsx 并验证"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["messages"][-2]["role"] == "user"
    assert payload["messages"][-2]["content"] == "请继续修复 web/src/routes/ChatCodingRoute.tsx 并验证"
    assert payload["messages"][-1]["role"] == "assistant"
    assert payload["messages"][-1]["content"] == "已完成网页对话提交接线。"
    assert payload["messages"][-1]["thought"] == "先确认消息模型，再把思考与心智快照一起落盘。"
    assert payload["messages"][-1]["mentalSnapshot"]["mood"] == "专注"
    assert payload["messages"][-1]["mentalSnapshot"]["cognitiveState"] == "productive"
    assert payload["messages"][-1]["toolCalls"] == [
        {"name": "read_file_tool", "status": "done"},
        {"name": "apply_patch_tool", "status": "done"},
    ]
    assert payload["taskSummary"] == "已完成网页对话提交接线。"
    assert payload["currentPhase"] == "ready"
    assert payload["readFiles"] == []
    assert payload["changedFiles"] == []
    assert payload["defaultFileContext"] == ""
    assert payload["previewTabs"] == []
    assert payload["activePreviewPath"] == "agent"
    assert payload["activeTask"] is None
    assert "active_task" not in load_chat_state(tmp_path)["conversations"][0]
    turn_events = [
        (args[2], kwargs)
        for args, kwargs in recorded_scene_events
        if len(args) >= 3 and str(args[2]).startswith("conversation.turn.")
    ]
    event_codes = [event_code for event_code, _kwargs in turn_events]
    for expected in [
        "conversation.turn.started",
        "conversation.turn.scheduled",
        "conversation.turn.worker_started",
        "conversation.turn.ui_capture_started",
        "conversation.turn.agent_created",
        "conversation.turn.history_seeded",
        "conversation.turn.agent_turn_started",
        "conversation.turn.agent_turn_returned",
        "conversation.turn.terminal_result",
        "conversation.turn.capture_attached",
        "conversation.turn.result_persisted",
        "conversation.turn.worker_finished",
    ]:
        assert expected in event_codes
    persisted_event = next(kwargs for event_code, kwargs in turn_events if event_code == "conversation.turn.result_persisted")
    assert persisted_event["outcome"] == "completed"
    assert persisted_event["fields"]["sessionId"] == "session-live"
    assert persisted_event["fields"]["assistantTextLength"] == len("已完成网页对话提交接线。")
    assert persisted_event["child_log_path"] == "conversations/session-live-turns.jsonl"


def test_session_submit_message_routes_slash_skill_into_scheduled_context(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    skill_root = tmp_path / "skills"
    skill_dir = skill_root / "brt"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: brt\ndescription: BRT gate\n---\n\n# BRT\n\nStop before implementation.\n",
        encoding="utf-8",
    )
    scheduled_contexts: list[dict] = []
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: scheduled_contexts.append(dict(context)))
    monkeypatch.setattr(
        session_service,
        "parse_skill_slash_command",
        lambda content: parse_skill_slash_command(content, skill_roots=[skill_root]),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "/brt 设计斜杠 skill 调用"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["messages"][-2]["role"] == "user"
    assert payload["messages"][-2]["content"] == "/brt 设计斜杠 skill 调用"
    persisted_skill = payload["messages"][-2]["metadata"]["slashSkillCommand"]
    assert persisted_skill["command"] == "brt"
    assert persisted_skill["skillName"] == "brt"
    assert persisted_skill["skillHash"]
    assert "content" not in persisted_skill
    assert payload["activeSkillContract"]["command"] == "brt"
    assert payload["activeSkillContract"]["skillName"] == "brt"
    assert payload["activeSkillContract"]["skillHash"]
    assert "content" not in payload["activeSkillContract"]
    assert "Stop before implementation." not in json.dumps(payload["activeSkillContract"], ensure_ascii=False)
    assert len(scheduled_contexts) == 1
    invocation = scheduled_contexts[0]["skill_invocation"]
    assert invocation["command"] == "brt"
    assert invocation["args"] == "设计斜杠 skill 调用"
    assert invocation["skillName"] == "brt"
    assert invocation["skillHash"]
    assert scheduled_contexts[0]["active_skill_contract"]["command"] == "brt"


def test_session_worker_seeds_slash_skill_runtime_context(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    skill_root = tmp_path / "skills"
    skill_dir = skill_root / "brt"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: brt\ndescription: BRT gate\n---\n\n# BRT\n\nAsk one question at a time.\n",
        encoding="utf-8",
    )
    seen_contexts: list[str] = []
    marker_calls: list[str] = []
    seen_prompt: dict[str, str] = {}
    scene_events: list[dict] = []
    lifecycle_events: list[dict] = []

    class DummyAgent:
        def set_mental_model_enabled_override(self, _enabled):
            pass

        def seed_chat_history(self, _messages):
            pass

        def seed_static_runtime_context(self, content):
            seen_contexts.append(f"static:{content}")

        def seed_runtime_context(self, content):
            seen_contexts.append(f"dynamic:{content}")

        def seed_volatile_runtime_context(self, content):
            seen_contexts.append(f"volatile:{content}")

        def mark_runtime_context_seeded_by_host(self):
            marker_calls.append("marked")

        def run_single_turn(self, initial_prompt=None, attachments=None):
            seen_prompt["value"] = initial_prompt
            return {"status": "completed", "summary": "ok", "raw_output": "ok", "outcome": "done"}

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "create_chat_agent", lambda **_kwargs: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_resolve_session_agent_llm",
        lambda *_args, **_kwargs: SimpleNamespace(
            model_id="test-dialogue-model",
            config=SimpleNamespace(),
            log_fields=lambda: {"llmModelId": "test-dialogue-model"},
        ),
    )
    _install_session_turn_scheduler(monkeypatch, max_active_per_agent=1)
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", SimpleNamespace(submit=lambda fn, context: fn(context)))
    monkeypatch.setattr(
        session_service,
        "build_agent_context",
        lambda *_args, **_kwargs: SimpleNamespace(
            memory_policy={},
            static_context_block="## Agent Static Context\nstable",
            dynamic_context_block="## Agent Runtime Context\nvolatile",
            context_block="## Agent Static Context\nstable\n\n## Agent Runtime Context\nvolatile",
            context_segments=[],
            timings={},
        ),
    )
    monkeypatch.setattr(
        session_service,
        "parse_skill_slash_command",
        lambda content: parse_skill_slash_command(content, skill_roots=[skill_root]),
    )
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda component, phase, event_code, **kwargs: scene_events.append(
            {"component": component, "phase": phase, "eventCode": event_code, **kwargs}
        ),
    )
    monkeypatch.setattr(
        session_service,
        "_record_session_turn_lifecycle_event",
        lambda session_id, phase, **kwargs: lifecycle_events.append(
            {"sessionId": session_id, "phase": phase, **kwargs}
        ),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "/brt 设计斜杠 skill 调用"},
    )

    assert response.status_code == 202
    assert seen_prompt["value"] == "/brt 设计斜杠 skill 调用"
    assert len(seen_contexts) == 3
    assert seen_contexts[0] == "static:## Agent Static Context\nstable"
    assert seen_contexts[1] == "volatile:## Agent Runtime Context\nvolatile"
    assert seen_contexts[2].startswith("volatile:## Slash Skill Context")
    assert "Command: /brt" in seen_contexts[2]
    assert "Ask one question at a time." in seen_contexts[2]
    assert marker_calls
    history_seeded_events = [event for event in lifecycle_events if event["phase"] == "history_seeded"]
    assert history_seeded_events
    history_fields = history_seeded_events[-1]["fields"]
    assert history_fields["staticRuntimeContextIncluded"] is True
    assert history_fields["dynamicRuntimeContextIncluded"] is True
    assert history_fields["dynamicRuntimeContextAvailable"] is True
    assert history_fields["dynamicRuntimeContextOmittedFromModelInput"] is False
    assert history_fields["skillRuntimeContextIncluded"] is True
    assert history_fields["skillRuntimeContextAvailable"] is True
    assert history_fields["skillRuntimeContextOmittedFromModelInput"] is False
    assert history_fields["skillRuntimeContextPlacement"] == "before_current_user"
    assert history_fields["runtimeContextSegmentCount"] == 0
    assert history_fields["staticRuntimeContextSeedAvailable"] is True
    assert history_fields["runtimeContextSeedAvailable"] is True
    assert history_fields["volatileRuntimeContextSeedAvailable"] is True
    assert any(event["eventCode"] == "conversation.skill_command.routed" for event in scene_events)


def test_session_worker_seeds_active_skill_contract_on_later_turn(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    skill_root = tmp_path / "skills"
    skill_dir = skill_root / "brt"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: brt\ndescription: BRT gate\n---\n\n# BRT\n\n- Ask one question at a time.\n",
        encoding="utf-8",
    )
    command = parse_skill_slash_command("/brt 设计斜杠 skill 调用", skill_roots=[skill_root])
    invocation = session_service._skill_invocation_payload(command)
    contract = session_service._active_skill_contract_from_invocation(invocation, turn_id="previous-turn")
    state = load_chat_state(tmp_path)
    state["conversations"][0]["active_skill_contract"] = contract
    save_chat_state(tmp_path, state)

    seen_contexts: list[str] = []
    seen_prompt: dict[str, str] = {}
    lifecycle_events: list[dict] = []

    class DummyAgent:
        def set_mental_model_enabled_override(self, _enabled):
            pass

        def seed_chat_history(self, _messages):
            pass

        def seed_static_runtime_context(self, content):
            seen_contexts.append(f"static:{content}")

        def seed_volatile_runtime_context(self, content):
            seen_contexts.append(f"volatile:{content}")

        def mark_runtime_context_seeded_by_host(self):
            pass

        def run_single_turn(self, initial_prompt=None, attachments=None):
            seen_prompt["value"] = initial_prompt
            return {"status": "completed", "summary": "ok", "raw_output": "ok", "outcome": "done"}

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "create_chat_agent", lambda **_kwargs: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_resolve_session_agent_llm",
        lambda *_args, **_kwargs: SimpleNamespace(
            model_id="test-dialogue-model",
            config=SimpleNamespace(),
            log_fields=lambda: {"llmModelId": "test-dialogue-model"},
        ),
    )
    _install_session_turn_scheduler(monkeypatch, max_active_per_agent=1)
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", SimpleNamespace(submit=lambda fn, context: fn(context)))
    monkeypatch.setattr(
        session_service,
        "build_agent_context",
        lambda *_args, **_kwargs: SimpleNamespace(
            memory_policy={},
            static_context_block="## Agent Static Context\nstable",
            dynamic_context_block="",
            context_block="## Agent Static Context\nstable",
            context_segments=[],
            timings={},
        ),
    )
    monkeypatch.setattr(
        session_service,
        "_record_session_turn_lifecycle_event",
        lambda session_id, phase, **kwargs: lifecycle_events.append(
            {"sessionId": session_id, "phase": phase, **kwargs}
        ),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续"},
    )

    assert response.status_code == 202
    assert seen_prompt["value"]
    volatile_contexts = [item for item in seen_contexts if item.startswith("volatile:")]
    assert len(volatile_contexts) == 1
    assert volatile_contexts[0].startswith("volatile:## Active Skill Context")
    assert "Command: /brt" in volatile_contexts[0]
    assert "Ask one question at a time." in volatile_contexts[0]
    assert "## Slash Skill Context" not in volatile_contexts[0]
    assert "SKILL.md:" not in volatile_contexts[0]
    history_seeded_events = [event for event in lifecycle_events if event["phase"] == "history_seeded"]
    assert history_seeded_events
    history_fields = history_seeded_events[-1]["fields"]
    assert history_fields["activeSkillContractAvailable"] is True
    assert history_fields["activeSkillContextIncluded"] is True
    assert history_fields["activeSkillContextPlacement"] == "before_current_user"
    detail = response.json()
    assert detail["lastContextComposition"]["cache"]["volatileSegmentCount"] >= 1
    assert any(
        item["key"] == "active_skill"
        and item["includedInModelInput"] is True
        and item["placement"] == "before_current_user"
        for item in detail["lastContextComposition"]["segments"]
    )


def test_edit_resubmit_session_message_routes_slash_skill_into_scheduled_context(tmp_path, monkeypatch):
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": "session-live",
            "updated_at": "2026-05-18T12:03:00",
            "conversations": [
                {
                    "conversation_id": "session-live",
                    "title": "真实会话",
                    "updated_at": "2026-05-18T12:03:00",
                    "last_turn_status": "ready",
                    "messages": [
                        {"role": "user", "content": "原始需求", "timestamp": "2026-05-18T12:00:00"},
                        {"role": "assistant", "content": "原始回答", "timestamp": "2026-05-18T12:01:00"},
                        {"role": "user", "content": "后续追问", "timestamp": "2026-05-18T12:02:00"},
                        {"role": "assistant", "content": "后续回答", "timestamp": "2026-05-18T12:03:00"},
                    ],
                }
            ],
        },
    )
    skill_root = tmp_path / "skills"
    skill_dir = skill_root / "brt"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: brt\ndescription: BRT gate\n---\n\n# BRT\n\nStop before implementation.\n",
        encoding="utf-8",
    )
    scheduled_contexts: list[dict] = []
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: scheduled_contexts.append(dict(context)))
    monkeypatch.setattr(
        session_service,
        "parse_skill_slash_command",
        lambda content: parse_skill_slash_command(content, skill_roots=[skill_root]),
    )

    response = client.post(
        "/api/sessions/session-live/messages/edit-resubmit",
        json={
            "messageId": "session-live-message-3",
            "content": "/brt 重新设计斜杠入口",
            "mentalModelEnabled": False,
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["messages"][-2]["role"] == "user"
    assert payload["messages"][-2]["content"] == "/brt 重新设计斜杠入口"
    persisted_skill = payload["messages"][-2]["metadata"]["slashSkillCommand"]
    assert persisted_skill["command"] == "brt"
    assert persisted_skill["skillName"] == "brt"
    assert persisted_skill["skillHash"]
    assert "content" not in persisted_skill
    assert payload["activeSkillContract"]["command"] == "brt"
    assert payload["activeSkillContract"]["skillName"] == "brt"
    assert len(scheduled_contexts) == 1
    invocation = scheduled_contexts[0]["skill_invocation"]
    assert invocation["command"] == "brt"
    assert invocation["args"] == "重新设计斜杠入口"
    assert invocation["skillName"] == "brt"
    assert scheduled_contexts[0]["active_skill_contract"]["command"] == "brt"

    session_service._set_session_running("session-live", False)
    session_service._clear_session_turn_control("session-live")
    session_service._clear_session_live_output("session-live")


def test_session_user_image_attachment_upload_and_submit_reaches_agent(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    base_config = session_service.get_config().model_copy(deep=True)
    base_config.llm.profiles["primary"].supports_image_input = True
    primary_profile = base_config.llm.get_profile(role="primary")
    primary_model_id, primary_model_entry = base_config.llm.get_model_library_entry_for_profile(primary_profile)
    provider_id = str((primary_model_entry or {}).get("provider_id") or primary_profile.provider_id)
    vision_model_id = primary_model_id or "vision-upload-test-model"
    base_config.llm.model_library[vision_model_id] = {
        **dict(primary_model_entry or {}),
        "provider_id": provider_id,
        "model": str((primary_model_entry or {}).get("model") or "vision-upload-test"),
        "label": str((primary_model_entry or {}).get("label") or "vision-upload-test"),
        "supports_image_input": True,
    }
    monkeypatch.setattr(session_service, "get_config", lambda: base_config)
    _bind_seeded_session_agent(
        tmp_path,
        agent_directory_service.ensure_agent_for_session(
            "session-live",
            display_name="真实会话",
            llm_bindings={
                "dialogue": {"modelId": vision_model_id},
                "vision": {"modelId": vision_model_id},
            },
            prompt_template_id="prompt-chat-default",
        ),
    )
    seen: dict[str, object] = {}

    class DummyAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None, attachments=None):
            seen["initial_prompt"] = initial_prompt
            seen["attachments"] = list(attachments or [])
            return {
                "status": "completed",
                "summary": "我已经看到了图片。",
                "raw_output": "我已经看到了图片。",
                "outcome": "done",
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda **_kwargs: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_SESSION_EXECUTOR",
        SimpleNamespace(submit=lambda fn, context: fn(context)),
    )

    upload_response = client.post(
        "/api/sessions/session-live/attachments",
        content=(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
            b"\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
            b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        ),
        headers={"Content-Type": "image/png", "X-Vibelution-Filename": "sketch.png"},
    )
    assert upload_response.status_code == 201
    attachment = upload_response.json()

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "分析这张图", "attachmentIds": [attachment["artifactId"]], "mentalModelEnabled": False},
    )

    assert response.status_code == 202
    payload = response.json()
    user_message = payload["messages"][-2]
    assert user_message["attachments"][0]["artifactId"] == attachment["artifactId"]
    assert user_message["attachments"][0]["filename"] == "sketch.png"
    assert seen["initial_prompt"] == "分析这张图"
    seen_attachment = seen["attachments"][0]
    assert seen_attachment["artifactId"] == attachment["artifactId"]
    assert seen_attachment["dataUrl"].startswith("data:image/png;base64,")

    state = load_chat_state(tmp_path)
    stored_user = state["conversations"][0]["messages"][-2]
    assert stored_user["attachments"][0]["artifactId"] == attachment["artifactId"]
    assert "dataUrl" not in stored_user["attachments"][0]


def test_session_user_image_attachment_vision_intent_blocks_unsupported_agent(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    base_config = session_service.get_config().model_copy(deep=True)
    base_config.llm.profiles["primary"].supports_image_input = False
    primary_profile = base_config.llm.get_profile(role="primary")
    primary_model_id, primary_model_entry = base_config.llm.get_model_library_entry_for_profile(primary_profile)
    if primary_model_id and isinstance(primary_model_entry, dict):
        base_config.llm.model_library[primary_model_id]["supports_image_input"] = False
    monkeypatch.setattr(session_service, "get_config", lambda: base_config)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: pytest.fail("LLM turn should not be scheduled"))

    upload_response = client.post(
        "/api/sessions/session-live/attachments",
        content=(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
            b"\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
            b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        ),
        headers={"Content-Type": "image/png", "X-Vibelution-Filename": "sketch.png"},
    )
    assert upload_response.status_code == 201

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "分析这张图里有什么", "attachmentIds": [upload_response.json()["artifactId"]]},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["currentPhase"] == "failed"
    assert "未确认支持图像输入" in payload["messages"][-1]["content"]
    state = load_chat_state(tmp_path)
    assert state["conversations"][0]["last_turn_status"] == "failed"


def test_session_user_image_attachment_picture_content_phrase_stays_vision_intent(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    base_config = session_service.get_config().model_copy(deep=True)
    base_config.llm.profiles["primary"].supports_image_input = False
    primary_profile = base_config.llm.get_profile(role="primary")
    primary_model_id, primary_model_entry = base_config.llm.get_model_library_entry_for_profile(primary_profile)
    if primary_model_id and isinstance(primary_model_entry, dict):
        base_config.llm.model_library[primary_model_id]["supports_image_input"] = False
    monkeypatch.setattr(session_service, "get_config", lambda: base_config)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: pytest.fail("LLM turn should not be scheduled"))

    upload_response = client.post(
        "/api/sessions/session-live/attachments",
        content=(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
            b"\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
            b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        ),
        headers={"Content-Type": "image/png", "X-Vibelution-Filename": "sketch.png"},
    )
    assert upload_response.status_code == 201

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "画面里有什么", "attachmentIds": [upload_response.json()["artifactId"]]},
    )

    assert response.status_code == 202
    assert "未确认支持图像输入" in response.json()["messages"][-1]["content"]


def test_session_user_image_attachment_vision_intent_reaches_supported_agent(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    base_config = session_service.get_config().model_copy(deep=True)
    base_config.llm.profiles["primary"].supports_image_input = True
    primary_profile = base_config.llm.get_profile(role="primary")
    primary_model_id, primary_model_entry = base_config.llm.get_model_library_entry_for_profile(primary_profile)
    provider_id = str((primary_model_entry or {}).get("provider_id") or primary_profile.provider_id)
    vision_model_id = primary_model_id or "vision-intent-test-model"
    base_config.llm.model_library[vision_model_id] = {
        **dict(primary_model_entry or {}),
        "provider_id": provider_id,
        "model": str((primary_model_entry or {}).get("model") or "vision-intent-test"),
        "label": str((primary_model_entry or {}).get("label") or "vision-intent-test"),
        "supports_image_input": True,
    }
    monkeypatch.setattr(session_service, "get_config", lambda: base_config)
    _bind_seeded_session_agent(
        tmp_path,
        agent_directory_service.ensure_agent_for_session(
            "session-live",
            display_name="真实会话",
            llm_bindings={
                "dialogue": {"modelId": vision_model_id},
                "vision": {"modelId": vision_model_id},
            },
            prompt_template_id="prompt-chat-default",
        ),
    )
    seen: dict[str, object] = {}

    class DummyAgent:
        def seed_chat_history(self, messages):
            pass

        def run_single_turn(self, initial_prompt=None, attachments=None):
            seen["initial_prompt"] = initial_prompt
            seen["attachments"] = list(attachments or [])
            return {"status": "completed", "summary": "看到了图片。", "raw_output": "看到了图片。", "outcome": "done"}

    monkeypatch.setattr(session_service, "create_chat_agent", lambda **_kwargs: DummyAgent())
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", SimpleNamespace(submit=lambda fn, context: fn(context)))

    upload_response = client.post(
        "/api/sessions/session-live/attachments",
        content=(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
            b"\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
            b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        ),
        headers={"Content-Type": "image/png", "X-Vibelution-Filename": "sketch.png"},
    )
    assert upload_response.status_code == 201

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "分析这张图", "attachmentIds": [upload_response.json()["artifactId"]]},
    )

    assert response.status_code == 202
    assert seen["initial_prompt"] == "分析这张图"
    assert seen["attachments"][0]["dataUrl"].startswith("data:image/png;base64,")


def test_session_recent_image_reference_reuses_last_user_attachment_for_vision(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    base_config = session_service.get_config().model_copy(deep=True)
    base_config.llm.profiles["primary"].supports_image_input = True
    primary_profile = base_config.llm.get_profile(role="primary")
    primary_model_id, primary_model_entry = base_config.llm.get_model_library_entry_for_profile(primary_profile)
    provider_id = str((primary_model_entry or {}).get("provider_id") or primary_profile.provider_id)
    vision_model_id = primary_model_id or "vision-recent-reference-test-model"
    base_config.llm.model_library[vision_model_id] = {
        **dict(primary_model_entry or {}),
        "provider_id": provider_id,
        "model": str((primary_model_entry or {}).get("model") or "vision-recent-reference-test"),
        "label": str((primary_model_entry or {}).get("label") or "vision-recent-reference-test"),
        "supports_image_input": True,
    }
    monkeypatch.setattr(session_service, "get_config", lambda: base_config)
    _bind_seeded_session_agent(
        tmp_path,
        agent_directory_service.ensure_agent_for_session(
            "session-live",
            display_name="真实会话",
            llm_bindings={
                "dialogue": {"modelId": vision_model_id},
                "vision": {"modelId": vision_model_id},
            },
            prompt_template_id="prompt-chat-default",
        ),
    )
    seen_turns: list[dict[str, object]] = []

    class DummyAgent:
        def seed_chat_history(self, messages):
            pass

        def run_single_turn(self, initial_prompt=None, attachments=None):
            seen_turns.append({"initial_prompt": initial_prompt, "attachments": list(attachments or [])})
            return {"status": "completed", "summary": "看到了图片。", "raw_output": "看到了图片。", "outcome": "done"}

    monkeypatch.setattr(session_service, "create_chat_agent", lambda **_kwargs: DummyAgent())
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", SimpleNamespace(submit=lambda fn, context: fn(context)))

    upload_response = client.post(
        "/api/sessions/session-live/attachments",
        content=(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
            b"\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
            b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        ),
        headers={"Content-Type": "image/png", "X-Vibelution-Filename": "sketch.png"},
    )
    assert upload_response.status_code == 201
    artifact_id = upload_response.json()["artifactId"]

    first = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "分析这张图", "attachmentIds": [artifact_id]},
    )
    assert first.status_code == 202

    second = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "再看一下刚才那张图"},
    )

    assert second.status_code == 202
    assert seen_turns[-1]["initial_prompt"] == "再看一下刚才那张图"
    assert seen_turns[-1]["attachments"][0]["artifactId"] == artifact_id
    assert seen_turns[-1]["attachments"][0]["dataUrl"].startswith("data:image/png;base64,")
    latest_user = [message for message in second.json()["messages"] if message["role"] == "user"][-1]
    assert latest_user["attachments"][0]["artifactId"] == artifact_id
    assert latest_user["metadata"]["resolvedRecentImageReference"]["status"] == "resolved"


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("基于这张图描述一下", "vision_analysis"),
        ("参考这张图分析风格", "vision_analysis"),
        ("基于这张图生成一张海报", "image2_edit"),
        ("照着这个图片改成二次元", "image2_edit"),
        ("参考这张图", "clarify"),
    ],
)
def test_session_user_image_attachment_intent_uses_explicit_rules(message, expected):
    assert session_service._classify_image_attachment_intent(message) == expected


def test_session_user_image_attachment_vision_support_inherits_model_library(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    base_config = session_service.get_config().model_copy(deep=True)
    profile = base_config.llm.profiles["primary"]
    profile.supports_image_input = None
    mimo_model_id = ""
    for item in base_config.llm.model_library.values():
        if isinstance(item, dict) and item.get("model") == "mimo-v2.5":
            item["supports_image_input"] = True
    for model_id, item in base_config.llm.model_library.items():
        if isinstance(item, dict) and item.get("model") == "mimo-v2.5":
            mimo_model_id = str(model_id)
            break
    if not mimo_model_id:
        primary_model_id, primary_model_entry = base_config.llm.get_model_library_entry_for_profile(profile)
        provider_id = str((primary_model_entry or {}).get("provider_id") or profile.provider_id)
        mimo_model_id = "xiaomi-mimo-v25-test"
        base_config.llm.model_library[mimo_model_id] = {
            "provider_id": provider_id,
            "model": "mimo-v2.5",
            "label": "mimo-v2.5",
            "supports_image_input": True,
        }
    monkeypatch.setattr(session_service, "get_config", lambda: base_config)
    _bind_seeded_session_agent(
        tmp_path,
        agent_directory_service.ensure_agent_for_session(
            "session-live",
            display_name="真实会话",
            llm_bindings={
                "dialogue": {"modelId": mimo_model_id},
                "vision": {"modelId": mimo_model_id},
            },
            prompt_template_id="prompt-chat-default",
        ),
    )
    seen: dict[str, object] = {}
    recorded_scene_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_scene_events.append((args, kwargs)) or {"accepted": True},
    )

    class DummyAgent:
        def seed_chat_history(self, messages):
            pass

        def run_single_turn(self, initial_prompt=None, attachments=None):
            seen["initial_prompt"] = initial_prompt
            seen["attachments"] = list(attachments or [])
            return {"status": "completed", "summary": "看到了图片。", "raw_output": "看到了图片。", "outcome": "done"}

    monkeypatch.setattr(session_service, "create_chat_agent", lambda **_kwargs: DummyAgent())
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", SimpleNamespace(submit=lambda fn, context: fn(context)))

    upload_response = client.post(
        "/api/sessions/session-live/attachments",
        content=(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
            b"\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
            b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        ),
        headers={"Content-Type": "image/png", "X-Vibelution-Filename": "sketch.png"},
    )
    assert upload_response.status_code == 201

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "向我描述一下这个图片", "attachmentIds": [upload_response.json()["artifactId"]]},
    )

    assert response.status_code == 202
    assert seen["initial_prompt"] == "向我描述一下这个图片"
    assert seen["attachments"][0]["dataUrl"].startswith("data:image/png;base64,")
    router_events = [
        kwargs for args, kwargs in recorded_scene_events
        if args[:3] == ("conversation", "image_attachment_router", "conversation.image_attachment_router.routed")
    ]
    assert router_events
    assert router_events[-1]["fields"]["route"] == "vision"
    assert router_events[-1]["fields"]["supportsImageInput"] is True
    assert router_events[-1]["fields"]["modelName"] == "mimo-v2.5"


def test_session_user_image_attachment_vision_slot_overrides_dialogue_model(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    base_config = session_service.get_config().model_copy(deep=True)
    primary_profile = base_config.llm.get_profile(role="primary")
    dialogue_model_id, dialogue_model_entry = base_config.llm.get_model_library_entry_for_profile(primary_profile)
    if not dialogue_model_id:
        dialogue_model_id = "dialogue-no-vision-test"
    provider_id = str((dialogue_model_entry or {}).get("provider_id") or primary_profile.provider_id)
    base_config.llm.model_library[dialogue_model_id] = {
        **dict(dialogue_model_entry or {}),
        "provider_id": provider_id,
        "model": "dialogue-no-vision",
        "label": "dialogue-no-vision",
        "supports_image_input": False,
    }
    vision_model_id = "vision-slot-model-test"
    base_config.llm.model_library[vision_model_id] = {
        "provider_id": provider_id,
        "model": "mimo-v2.5",
        "label": "vision-slot-model",
        "supports_image_input": True,
    }
    monkeypatch.setattr(session_service, "get_config", lambda: base_config)
    _bind_seeded_session_agent(
        tmp_path,
        agent_directory_service.ensure_agent_for_session(
            "session-live",
            display_name="真实会话",
            llm_bindings={
                "dialogue": {"modelId": dialogue_model_id},
                "vision": {"modelId": vision_model_id},
            },
            prompt_template_id="prompt-chat-default",
        ),
    )
    seen: dict[str, object] = {}
    recorded_scene_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_scene_events.append((args, kwargs)) or {"accepted": True},
    )

    class DummyAgent:
        def seed_chat_history(self, messages):
            pass

        def run_single_turn(self, initial_prompt=None, attachments=None):
            seen["initial_prompt"] = initial_prompt
            seen["attachments"] = list(attachments or [])
            return {"status": "completed", "summary": "看到了图片。", "raw_output": "看到了图片。", "outcome": "done"}

    def fake_create_chat_agent(**kwargs):
        seen["runtime_model"] = kwargs["config"].llm.profiles["primary"].model
        return DummyAgent()

    monkeypatch.setattr(session_service, "create_chat_agent", fake_create_chat_agent)
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", SimpleNamespace(submit=lambda fn, context: fn(context)))

    upload_response = client.post(
        "/api/sessions/session-live/attachments",
        content=(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
            b"\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
            b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        ),
        headers={"Content-Type": "image/png", "X-Vibelution-Filename": "sketch.png"},
    )
    assert upload_response.status_code == 201

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "分析这张图里有什么", "attachmentIds": [upload_response.json()["artifactId"]]},
    )

    assert response.status_code == 202
    assert seen["runtime_model"] == "mimo-v2.5"
    assert seen["attachments"][0]["dataUrl"].startswith("data:image/png;base64,")
    router_events = [
        kwargs for args, kwargs in recorded_scene_events
        if args[:3] == ("conversation", "image_attachment_router", "conversation.image_attachment_router.routed")
    ]
    assert router_events
    assert router_events[-1]["fields"]["route"] == "vision"
    assert router_events[-1]["fields"]["llmSlot"] == "vision"
    assert router_events[-1]["fields"]["llmModelId"] == vision_model_id
    assert router_events[-1]["fields"]["dialogueModelId"] == dialogue_model_id
    assert router_events[-1]["fields"]["visionModelId"] == vision_model_id


def test_session_user_image_attachment_edit_intent_reaches_supported_multimodal_agent(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", SimpleNamespace(submit=lambda fn, context: fn(context)))
    monkeypatch.setattr(
        "tools.image2_tools.image2_generate_tool",
        lambda **kwargs: pytest.fail("supported multimodal models must receive image input before image2"),
    )
    base_config = session_service.get_config().model_copy(deep=True)
    primary_profile = base_config.llm.get_profile(role="primary")
    primary_model_id, primary_model_entry = base_config.llm.get_model_library_entry_for_profile(primary_profile)
    provider_id = str((primary_model_entry or {}).get("provider_id") or primary_profile.provider_id)
    vision_model_id = primary_model_id or "mimo-edit-intent-test-model"
    base_config.llm.model_library[vision_model_id] = {
        **dict(primary_model_entry or {}),
        "provider_id": provider_id,
        "model": str((primary_model_entry or {}).get("model") or "mimo-v2.5-pro"),
        "label": str((primary_model_entry or {}).get("label") or "mimo-edit-intent-test-model"),
        "supports_image_input": True,
    }
    monkeypatch.setattr(session_service, "get_config", lambda: base_config)
    _bind_seeded_session_agent(
        tmp_path,
        agent_directory_service.ensure_agent_for_session(
            "session-live",
            display_name="真实会话",
            llm_bindings={
                "dialogue": {"modelId": vision_model_id},
                "vision": {"modelId": vision_model_id},
            },
            prompt_template_id="prompt-chat-default",
        ),
    )
    seen: dict[str, object] = {}
    recorded_scene_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_scene_events.append((args, kwargs)) or {"accepted": True},
    )

    class DummyAgent:
        def seed_chat_history(self, messages):
            pass

        def run_single_turn(self, initial_prompt=None, attachments=None):
            seen["initial_prompt"] = initial_prompt
            seen["attachments"] = list(attachments or [])
            return {
                "status": "completed",
                "summary": "我已先查看图片并准备调整方案。",
                "raw_output": "我已先查看图片并准备调整方案。",
                "outcome": "done",
            }

    def fake_create_chat_agent(**kwargs):
        seen["runtime_model"] = kwargs["config"].llm.profiles["primary"].model
        return DummyAgent()

    monkeypatch.setattr(session_service, "create_chat_agent", fake_create_chat_agent)

    upload_response = client.post(
        "/api/sessions/session-live/attachments",
        content=(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
            b"\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
            b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        ),
        headers={"Content-Type": "image/png", "X-Vibelution-Filename": "sketch.png"},
    )
    assert upload_response.status_code == 201
    artifact_id = upload_response.json()["artifactId"]

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "把这张图改成 2D 卡通头像", "attachmentIds": [artifact_id]},
    )

    assert response.status_code == 202
    assert seen["initial_prompt"] == "把这张图改成 2D 卡通头像"
    assert seen["runtime_model"] == base_config.llm.model_library[vision_model_id]["model"]
    assert seen["attachments"][0]["artifactId"] == artifact_id
    assert seen["attachments"][0]["dataUrl"].startswith("data:image/png;base64,")
    router_events = [
        kwargs for args, kwargs in recorded_scene_events
        if args[:3] == ("conversation", "image_attachment_router", "conversation.image_attachment_router.routed")
    ]
    assert router_events
    assert router_events[-1]["fields"]["route"] == "vision"
    assert router_events[-1]["fields"]["intent"] == "image2_edit"
    assert router_events[-1]["fields"]["llmSlot"] == "vision"
    assert router_events[-1]["fields"]["supportsImageInput"] is True


def test_session_user_image_attachment_edit_intent_blocks_when_agent_cannot_read_images(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", SimpleNamespace(submit=lambda fn, context: fn(context)))
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: pytest.fail("LLM turn should not be scheduled"))
    base_config = session_service.get_config().model_copy(deep=True)
    primary_profile = base_config.llm.get_profile(role="primary")
    primary_model_id, primary_model_entry = base_config.llm.get_model_library_entry_for_profile(primary_profile)
    provider_id = str((primary_model_entry or {}).get("provider_id") or primary_profile.provider_id)
    dialogue_model_id = primary_model_id or "image2-fallback-no-vision-model"
    base_config.llm.model_library[dialogue_model_id] = {
        **dict(primary_model_entry or {}),
        "provider_id": provider_id,
        "model": str((primary_model_entry or {}).get("model") or "image2-fallback-no-vision"),
        "label": str((primary_model_entry or {}).get("label") or "image2-fallback-no-vision"),
        "supports_image_input": False,
    }
    monkeypatch.setattr(session_service, "get_config", lambda: base_config)
    _bind_seeded_session_agent(
        tmp_path,
        agent_directory_service.ensure_agent_for_session(
            "session-live",
            display_name="真实会话",
            llm_bindings={
                "dialogue": {"modelId": dialogue_model_id},
                "vision": {"modelId": dialogue_model_id},
            },
            prompt_template_id="prompt-chat-default",
        ),
    )
    monkeypatch.setattr(
        "tools.image2_tools.image2_generate_tool",
        lambda **kwargs: pytest.fail("image2 must be called by the model tool protocol, not the session entry"),
    )
    recorded_scene_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_scene_events.append((args, kwargs)) or {"accepted": True},
    )

    upload_response = client.post(
        "/api/sessions/session-live/attachments",
        content=(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
            b"\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
            b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        ),
        headers={"Content-Type": "image/png", "X-Vibelution-Filename": "sketch.png"},
    )
    assert upload_response.status_code == 201
    artifact_id = upload_response.json()["artifactId"]

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "把这张图改成 2D 卡通头像", "attachmentIds": [artifact_id]},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["currentPhase"] == "failed"
    assert "未确认支持图像输入" in payload["messages"][-1]["content"]
    router_events = [
        kwargs for args, kwargs in recorded_scene_events
        if args[:3] == ("conversation", "image_attachment_router", "conversation.image_attachment_router.routed")
    ]
    assert router_events
    assert router_events[-1]["fields"]["route"] == "block_vision"
    assert router_events[-1]["fields"]["intent"] == "image2_edit"
    state = load_chat_state(tmp_path)
    assert state["conversations"][0]["last_turn_status"] == "failed"


def test_session_recent_image_reference_blocks_when_agent_cannot_read_images(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", SimpleNamespace(submit=lambda fn, context: fn(context)))
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: pytest.fail("LLM turn should not be scheduled"))
    base_config = session_service.get_config().model_copy(deep=True)
    primary_profile = base_config.llm.get_profile(role="primary")
    primary_model_id, primary_model_entry = base_config.llm.get_model_library_entry_for_profile(primary_profile)
    provider_id = str((primary_model_entry or {}).get("provider_id") or primary_profile.provider_id)
    dialogue_model_id = primary_model_id or "recent-image2-fallback-no-vision-model"
    base_config.llm.model_library[dialogue_model_id] = {
        **dict(primary_model_entry or {}),
        "provider_id": provider_id,
        "model": str((primary_model_entry or {}).get("model") or "recent-image2-fallback-no-vision"),
        "label": str((primary_model_entry or {}).get("label") or "recent-image2-fallback-no-vision"),
        "supports_image_input": False,
    }
    monkeypatch.setattr(session_service, "get_config", lambda: base_config)
    _bind_seeded_session_agent(
        tmp_path,
        agent_directory_service.ensure_agent_for_session(
            "session-live",
            display_name="真实会话",
            llm_bindings={
                "dialogue": {"modelId": dialogue_model_id},
                "vision": {"modelId": dialogue_model_id},
            },
            prompt_template_id="prompt-chat-default",
        ),
    )
    monkeypatch.setattr(
        "tools.image2_tools.image2_generate_tool",
        lambda **kwargs: pytest.fail("image2 must be called by the model tool protocol, not the session entry"),
    )
    recorded_scene_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_scene_events.append((args, kwargs)) or {"accepted": True},
    )

    upload_response = client.post(
        "/api/sessions/session-live/attachments",
        content=(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
            b"\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
            b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        ),
        headers={"Content-Type": "image/png", "X-Vibelution-Filename": "sketch.png"},
    )
    assert upload_response.status_code == 201
    artifact_id = upload_response.json()["artifactId"]

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "把刚才那张图改成 2D 卡通头像"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["currentPhase"] == "failed"
    assert "未确认支持图像输入" in payload["messages"][-1]["content"]
    router_events = [
        kwargs for args, kwargs in recorded_scene_events
        if args[:3] == ("conversation", "image_attachment_router", "conversation.image_attachment_router.routed")
    ]
    assert router_events
    assert router_events[-1]["fields"]["route"] == "block_vision"
    assert router_events[-1]["fields"]["intent"] == "image2_edit"
    latest_user = [message for message in response.json()["messages"] if message["role"] == "user"][-1]
    assert latest_user["metadata"]["resolvedRecentImageReference"]["status"] == "resolved"
    assert latest_user["metadata"]["resolvedRecentImageReference"]["artifactIds"] == [artifact_id]


def test_session_contextual_retry_restores_recent_image_attachment_for_supported_multimodal_agent(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", SimpleNamespace(submit=lambda fn, context: fn(context)))
    monkeypatch.setattr(
        "tools.image2_tools.image2_generate_tool",
        lambda **kwargs: pytest.fail("contextual retry must return to the dialogue model, not image2"),
    )
    base_config = session_service.get_config().model_copy(deep=True)
    primary_profile = base_config.llm.get_profile(role="primary")
    primary_model_id, primary_model_entry = base_config.llm.get_model_library_entry_for_profile(primary_profile)
    provider_id = str((primary_model_entry or {}).get("provider_id") or primary_profile.provider_id)
    vision_model_id = primary_model_id or "contextual-retry-vision-model"
    base_config.llm.model_library[vision_model_id] = {
        **dict(primary_model_entry or {}),
        "provider_id": provider_id,
        "model": str((primary_model_entry or {}).get("model") or "contextual-retry-vision"),
        "label": str((primary_model_entry or {}).get("label") or "contextual-retry-vision"),
        "supports_image_input": True,
    }
    monkeypatch.setattr(session_service, "get_config", lambda: base_config)
    _bind_seeded_session_agent(
        tmp_path,
        agent_directory_service.ensure_agent_for_session(
            "session-live",
            display_name="真实会话",
            llm_bindings={
                "dialogue": {"modelId": vision_model_id},
                "vision": {"modelId": vision_model_id},
            },
            prompt_template_id="prompt-chat-default",
        ),
    )
    seen_turns: list[dict[str, object]] = []

    class DummyAgent:
        def seed_chat_history(self, messages):
            pass

        def run_single_turn(self, initial_prompt=None, attachments=None):
            seen_turns.append(
                {
                    "initial_prompt": initial_prompt,
                    "attachments": list(attachments or []),
                }
            )
            return {
                "status": "completed",
                "summary": "已读取图片并继续处理。",
                "raw_output": "已读取图片并继续处理。",
                "outcome": "done",
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda **kwargs: DummyAgent())

    upload_response = client.post(
        "/api/sessions/session-live/attachments",
        content=(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
            b"\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
            b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        ),
        headers={"Content-Type": "image/png", "X-Vibelution-Filename": "generated.png"},
    )
    assert upload_response.status_code == 201
    artifact_id = upload_response.json()["artifactId"]

    first = client.post(
        "/api/sessions/session-live/messages",
        json={
            "content": "这是你生成的图片,跟原来的图片完全不一样,你需要继续调整提示词,来逼近原来的图片",
            "attachmentIds": [artifact_id],
        },
    )
    assert first.status_code == 202

    second = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "你再试试,应该可以了"},
    )

    assert second.status_code == 202
    assert len(seen_turns) == 2
    assert seen_turns[-1]["attachments"][0]["artifactId"] == artifact_id
    assert seen_turns[-1]["initial_prompt"] == "这是你生成的图片,跟原来的图片完全不一样,你需要继续调整提示词,来逼近原来的图片"
    latest_user = [message for message in second.json()["messages"] if message["role"] == "user"][-1]
    assert latest_user["metadata"]["resolvedRecentImageReference"]["status"] == "resolved"
    assert latest_user["metadata"]["resolvedRecentImageReference"]["source"] == "contextual_retry"


def test_session_contextual_retry_ignores_active_task_image_clarification(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        task_status="done",
        active_task={
            "task_id": "session-live-coding-task",
            "kind": "coding",
            "status": "editing",
            "title": "打开 mimo_cli",
            "goal": "打开 mimo_cli",
            "latest_summary": "我看到你发送了图片。你想让我分析这张图片，还是基于它生成/调整图片？请补一句你的目标。",
            "metadata": {"source": "task_tool"},
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    scheduled_contexts: list[dict] = []
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: scheduled_contexts.append(dict(context)))
    monkeypatch.setattr(
        "tools.image2_tools.image2_generate_tool",
        lambda **kwargs: pytest.fail("plain continue must not be routed to image2"),
    )

    upload_response = client.post(
        "/api/sessions/session-live/attachments",
        content=(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
            b"\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
            b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        ),
        headers={"Content-Type": "image/png", "X-Vibelution-Filename": "state.png"},
    )
    assert upload_response.status_code == 201
    artifact = upload_response.json()
    state = load_chat_state(tmp_path)
    conversation = state["conversations"][0]
    conversation["messages"].extend(
        [
            {
                "role": "user",
                "content": "我刚才点击了测试,还是显示不支持图像为什么",
                "timestamp": "2026-05-18T11:58:00",
                "attachments": [artifact],
            },
            {
                "role": "assistant",
                "content": "我看到你发送了图片。你想让我分析这张图片，还是基于它生成/调整图片？请补一句你的目标。",
                "timestamp": "2026-05-18T11:59:00",
            },
            {
                "role": "user",
                "content": "继续",
                "timestamp": "2026-05-18T12:00:00",
                "metadata": {
                    "resolvedRecentImageReference": {
                        "status": "resolved",
                        "source": "contextual_retry",
                        "prompt": "我看到你发送了图片。你想让我分析这张图片，还是基于它生成/调整图片？请补一句你的目标。",
                        "artifactIds": [artifact["artifactId"]],
                    }
                },
            },
            {
                "role": "assistant",
                "content": "图片生成失败：image2 provider returned 401",
                "timestamp": "2026-05-18T12:01:00",
                "metadata": {
                    "kind": "turn_error",
                    "reasonCode": "auth_failed",
                },
            },
        ]
    )
    save_chat_state(tmp_path, state)

    response = client.post("/api/sessions/session-live/messages", json={"content": "继续"})

    assert response.status_code == 202
    assert len(scheduled_contexts) == 1
    assert scheduled_contexts[0]["user_message"] == "继续"
    assert scheduled_contexts[0].get("attachments") in (None, [])
    latest_user = [message for message in response.json()["messages"] if message["role"] == "user"][-1]
    assert "resolvedRecentImageReference" not in (latest_user.get("metadata") or {})


def test_session_recent_image_reference_without_history_asks_for_image(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: pytest.fail("LLM turn should not be scheduled"))

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "再看一下刚才那张图"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["messages"][-2]["metadata"]["resolvedRecentImageReference"]["status"] == "missing"
    assert "没有在当前会话里找到" in payload["messages"][-1]["content"]


def test_session_user_image_attachment_empty_text_asks_for_clarification(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: pytest.fail("LLM turn should not be scheduled"))

    upload_response = client.post(
        "/api/sessions/session-live/attachments",
        content=(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
            b"\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05"
            b"\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        ),
        headers={"Content-Type": "image/png", "X-Vibelution-Filename": "sketch.png"},
    )
    assert upload_response.status_code == 201

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "", "attachmentIds": [upload_response.json()["artifactId"]]},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["currentPhase"] == "ready"
    assert "分析这张图片" in payload["messages"][-1]["content"]


def test_session_user_image_attachment_rejects_unsupported_type(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.post(
        "/api/sessions/session-live/attachments",
        content=b"not an image",
        headers={"Content-Type": "text/plain", "X-Vibelution-Filename": "note.txt"},
    )

    assert response.status_code == 422


def test_session_user_image_attachment_rejects_spoofed_image_payload(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.post(
        "/api/sessions/session-live/attachments",
        content=b"not really a png",
        headers={"Content-Type": "image/png", "X-Vibelution-Filename": "spoof.png"},
    )

    assert response.status_code == 422


def test_session_user_image_attachment_rejects_oversized_content_length_before_storage(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    recorded_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        "core.web.routes.sessions.record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )
    monkeypatch.setattr(
        "core.web.routes.sessions.store_session_user_image_attachment",
        lambda *_args, **_kwargs: pytest.fail("oversized upload should be rejected before storage"),
    )

    response = client.post(
        "/api/sessions/session-live/attachments",
        content=b"",
        headers={
            "Content-Type": "image/png",
            "X-Vibelution-Filename": "huge.png",
            "Content-Length": str(session_service.SESSION_USER_IMAGE_MAX_BYTES + 1),
        },
    )

    assert response.status_code == 413
    assert recorded_events
    args, kwargs = recorded_events[-1]
    assert args[:3] == ("conversation", "attachment_upload", "conversation.attachment_upload.rejected")
    assert kwargs["fields"]["reason"] == "content_length_exceeded"
    assert kwargs["fields"]["limitBytes"] == session_service.SESSION_USER_IMAGE_MAX_BYTES


def test_session_user_image_attachment_rejects_stream_that_exceeds_limit(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    recorded_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        "core.web.routes.sessions.record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )
    monkeypatch.setattr(
        "core.web.routes.sessions.SESSION_USER_IMAGE_MAX_BYTES",
        16,
    )
    monkeypatch.setattr(
        "core.web.routes.sessions.store_session_user_image_attachment",
        lambda *_args, **_kwargs: pytest.fail("oversized stream should be rejected before storage"),
    )

    response = client.post(
        "/api/sessions/session-live/attachments",
        content=iter([b"\x89PNG\r\n\x1a\n", b"0123456789"]),
        headers={"Content-Type": "image/png", "X-Vibelution-Filename": "stream.png"},
    )

    assert response.status_code == 413
    assert recorded_events[-1][1]["fields"]["reason"] == "stream_limit_exceeded"
    assert recorded_events[-1][1]["fields"]["receivedBytes"] > 16


def test_submit_session_message_preserves_chinese_content_round_trip(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)

    content = "修复中文编码：runtime circuit breaker validation ping"

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": content},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["messages"][-2]["role"] == "user"
    assert payload["messages"][-2]["content"] == content
    assert payload["messages"][-1]["role"] == "assistant"
    assert payload["messages"][-1]["streaming"] is True

    state = load_chat_state(tmp_path)
    persisted = state["conversations"][0]["messages"][-1]
    assert persisted["role"] == "user"
    assert persisted["content"] == content

    workspace_log = tmp_path / "workspace" / "sessions" / "session-live" / "logs" / "conversation.jsonl"
    log_records = [json.loads(line) for line in workspace_log.read_text(encoding="utf-8").splitlines()]
    assert log_records[-1]["content"] == content


def test_submit_session_message_preserves_full_multiline_prompt_for_agent(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    captured: dict[str, object] = {}
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: captured.update({"context": dict(context)}))

    content = "\n".join(
        [
            "第一行：这是完整需求的开头",
            "第二行：保留背景",
            "第三行：保留约束",
            "第四行：保留测试要求",
            "第五行：不能被本地 trim_lines 截断",
            "第六行：仍然应该交给 LLM 判断",
        ]
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": content},
    )

    assert response.status_code == 202
    assert captured["context"]["user_message"] == content
    assert captured["context"]["raw_user_message"] == content
    assert captured["context"]["user_message_source"] == "raw_meaningful"


def test_submit_session_message_shows_waiting_live_message_while_turn_runs(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)

    try:
        response = client.post(
            "/api/sessions/session-live/messages",
            json={"content": "检查为什么对话看起来卡住"},
        )

        assert response.status_code == 202
        payload = response.json()
        assert payload["currentPhase"] == "running"
        live_message = payload["messages"][-1]
        assert live_message["role"] == "assistant"
        assert live_message["streaming"] is True
        assert live_message["content"] == CONTEXT_PREPARE_LIVE_MESSAGE
    finally:
        session_service._set_session_running("session-live", False)
        session_service._clear_session_turn_control("session-live")
        session_service._clear_session_live_output("session-live")


def test_submit_session_message_recovers_content_from_utf8_base64_fallback(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)

    content = "请继续检查中文输入链路"
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "???????:runtime circuit breaker validation ping", "contentUtf8Base64": encoded},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["messages"][-2]["content"] == content
    assert payload["messages"][-1]["streaming"] is True
    assert payload["messages"][-1]["content"] == CONTEXT_PREPARE_LIVE_MESSAGE
    state = load_chat_state(tmp_path)
    assert state["conversations"][0]["messages"][-1]["content"] == content
    assert _read_next_state_signals(tmp_path, session_id="session-live") == []


def test_submit_session_message_rejects_encoding_replacement_pollution(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "???????:runtime circuit breaker validation ping"},
    )

    assert response.status_code == 422
    assert "编码损坏" in response.json()["detail"]
    state = load_chat_state(tmp_path)
    assert [item["content"] for item in state["conversations"][0]["messages"]] == [
        "继续前端开发",
        "<think>internal</think>\n\n已经接到真实状态了。",
    ]


def test_submit_session_message_preserves_short_dialogue_prompt_without_task_fallback(tmp_path, monkeypatch):
    (tmp_path / "web" / "src" / "routes").mkdir(parents=True, exist_ok=True)
    (tmp_path / "web" / "src" / "routes" / "ChatCodingRoute.tsx").write_text("export {};\n", encoding="utf-8")
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        active_task={
            "task_id": "session-live-coding-task",
            "kind": "coding",
            "status": "reading",
            "title": "继续前端开发",
            "goal": "继续前端开发",
            "read_files": ["web/src/routes/ChatCodingRoute.tsx"],
            "default_file_context": "web/src/routes/ChatCodingRoute.tsx",
            "metadata": {"source": "task_tool"},
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    recorded_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )

    captured: dict[str, object] = {}

    class DummyAgent:
        def seed_chat_history(self, messages):
            captured["seeded"] = list(messages)

        def run_single_turn(self, initial_prompt=None):
            captured["prompt"] = initial_prompt
            return {
                "status": "completed",
                "summary": "继续前端开发",
                "raw_output": "继续前端开发",
                "outcome": "done",
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "你好"},
    )

    assert response.status_code == 202
    assert captured["prompt"] == "你好"
    assert all(item["content"] != "你好" for item in captured["seeded"])
    payload = response.json()
    assert payload["activeTask"]["goal"] == "继续前端开发"
    assert payload["activeTask"]["title"] == "继续前端开发"
    event_codes = [args[2] for args, _kwargs in recorded_events]
    assert "conversation.user_message_filtered" not in event_codes


def test_lightweight_chat_does_not_classify_user_text_or_disable_tools():
    enabled, reason = session_service._lightweight_chat_payload_decision(
        {"raw_user_message": "Capital ok?", "user_message": "Capital ok?"}
    )
    assert (enabled, reason) == (False, "unified_conversation_chain")

    enabled, reason = session_service._lightweight_chat_payload_decision(
        {"raw_user_message": "API ok?", "user_message": "API ok?"}
    )
    assert (enabled, reason) == (False, "unified_conversation_chain")


def test_lightweight_chat_keeps_active_skill_contract_in_full_payload():
    enabled, reason = session_service._lightweight_chat_payload_decision(
        {
            "raw_user_message": "收到",
            "user_message": "收到",
            "active_skill_contract": {
                "command": "brt",
                "skillName": "brt",
                "skillHash": "hash-a",
                "keyRules": ["Ask one question at a time."],
            },
        }
    )

    assert (enabled, reason) == (False, "active_skill_contract")


def test_submit_session_message_continue_preserves_raw_prompt_and_dialogue_history(tmp_path, monkeypatch):
    (tmp_path / "core" / "web" / "services").mkdir(parents=True, exist_ok=True)
    (tmp_path / "core" / "web" / "services" / "session_service.py").write_text("pass\n", encoding="utf-8")
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        active_task={
            "task_id": "session-live-coding-task",
            "kind": "coding",
            "status": "reading",
            "title": "修复对话消息流程",
            "goal": "修复对话消息流程",
            "read_files": ["core/web/services/session_service.py"],
            "default_file_context": "core/web/services/session_service.py",
            "metadata": {"source": "task_tool"},
        },
    )
    state = load_chat_state(tmp_path)
    state["conversations"][0]["messages"].append(
        {"role": "user", "content": "?", "timestamp": "2026-05-18T11:57:00"}
    )
    save_chat_state(tmp_path, state)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    captured: dict[str, object] = {}

    class DummyAgent:
        def seed_chat_history(self, messages):
            captured["seeded"] = list(messages)

        def run_single_turn(self, initial_prompt=None):
            captured["prompt"] = initial_prompt
            return {
                "status": "completed",
                "summary": "修复对话消息流程",
                "raw_output": "修复对话消息流程",
                "outcome": "done",
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续"},
    )

    assert response.status_code == 202
    assert captured["prompt"] == "继续"
    assert any(item["content"] == "?" for item in captured["seeded"])


def test_submit_session_message_does_not_promote_contextual_confirmation_to_task_goal(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        active_task={
            "task_id": "session-live-coding-task",
            "kind": "coding",
            "status": "reading",
            "title": "优化日志摘要入口",
            "goal": "优化日志摘要入口",
            "latest_summary": "已经形成日志摘要优化计划。",
            "metadata": {"source": "task_tool"},
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    class DummyAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "已开始按计划修改日志摘要入口。",
                "raw_output": "已开始按计划修改日志摘要入口。",
                "outcome": "done",
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "好的开始修改"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["activeTask"]["goal"] == "优化日志摘要入口"
    assert payload["activeTask"]["title"] != "好的开始修改"
    state = load_chat_state(tmp_path)
    assert state["conversations"][0]["active_task"]["goal"] == "优化日志摘要入口"


def test_submit_session_contextual_confirmation_preserves_raw_prompt(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        active_task={
            "task_id": "agent-avatar-task",
            "kind": "coding",
            "status": "editing",
            "title": "现在agent可以设置默认头像吗",
            "goal": "现在agent可以设置默认头像吗",
            "changed_files": ["workspace/avatars/avatars.json"],
            "latest_summary": "Agent 目前不能设置默认图片头像。要我现在开始实现吗？",
            "next_action": "",
            "metadata": {"source": "task_tool", "outcome": "no_change"},
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    captured: dict[str, object] = {}

    class DummyAgent:
        def seed_chat_history(self, messages):
            captured["seeded"] = list(messages)

        def run_single_turn(self, initial_prompt=None):
            captured["prompt"] = initial_prompt
            return {
                "status": "completed",
                "summary": "已开始实现 Agent 默认头像支持。",
                "raw_output": "已开始实现 Agent 默认头像支持。",
                "outcome": "done",
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "开始实现"},
    )

    assert response.status_code == 202
    assert captured["prompt"] == "开始实现"
    payload = response.json()
    assert payload["activeTask"]["goal"] == "现在agent可以设置默认头像吗"
    assert payload["activeTask"]["title"] == "现在agent可以设置默认头像吗"


def test_submit_session_plain_confirmation_preserves_raw_prompt_without_agent_inbox_task_pollution(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        active_task={
            "task_id": "session-live-coding-task",
            "kind": "coding",
            "status": "reading",
            "title": "[Agent 私信回复]\n来源 Agent: A013 · 白予安",
            "goal": "[Agent 私信回复]\n来源 Agent: A013 · 白予安",
            "latest_summary": "白予安回复说需要 CEO 确认后继续推进记忆系统开发。",
            "read_files": ["core/web/services/session_service.py"],
            "metadata": {"source": "task_tool", "last_user_message_filtered": True},
        },
    )
    state = load_chat_state(tmp_path)
    messages = state["conversations"][0]["messages"]
    messages.append(
        {
            "role": "user",
            "content": "我现在需要对项目的记忆系统进行开发,需要你的团队,请你把这个作为目前的任务,分析一下如何进展",
            "timestamp": "2026-05-31T17:03:58",
        }
    )
    messages.append(
        {
            "role": "user",
            "content": "[Agent 私信回复]\n来源 Agent: A013 · 白予安\n\n消息内容:\n需要 CEO 确认。",
            "timestamp": "2026-05-31T17:08:50",
            "metadata": {
                "kind": "agent_inbox_message",
                "inboxKind": "agent_inbox_reply",
                "sourceAgentId": "agent-a013",
                "targetAgentId": "agent-ceo",
            },
        }
    )
    messages.append(
        {
            "role": "assistant",
            "content": "团队已完成前期组织诊断和能力评估，现在需要您的决策来推进下一阶段工作。请确认上述决策点。",
            "timestamp": "2026-05-31T17:09:00",
        }
    )
    save_chat_state(tmp_path, state)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    captured: dict[str, object] = {}

    class DummyAgent:
        def seed_chat_history(self, messages):
            captured["seeded"] = list(messages)

        def run_single_turn(self, initial_prompt=None):
            captured["prompt"] = initial_prompt
            return {
                "status": "completed",
                "summary": "已收到确认，继续推进记忆系统开发组织任务。",
                "raw_output": "已收到确认，继续推进记忆系统开发组织任务。",
                "outcome": "done",
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "确认"},
    )

    assert response.status_code == 202
    prompt = str(captured["prompt"])
    assert prompt == "确认"
    assert "[Agent 私信回复]" not in prompt
    state = load_chat_state(tmp_path)
    active_task = state["conversations"][0]["active_task"]
    assert active_task["goal"].startswith("我现在需要对项目的记忆系统进行开发")
    assert "[Agent 私信回复]" not in active_task["goal"]


def test_submit_session_agent_inbox_turn_preserves_inbox_prompt_without_history_fallback(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        active_task={
            "task_id": "session-live-coding-task",
            "kind": "coding",
            "status": "reading",
            "title": "只需要创建记忆库管理员",
            "goal": "只需要创建记忆库管理员",
            "latest_summary": "等待团队私信回复。",
            "metadata": {"source": "task_tool"},
        },
    )
    state = load_chat_state(tmp_path)
    state["conversations"][0]["messages"].append(
        {
            "role": "user",
            "content": "只需要创建记忆库管理员",
            "timestamp": "2026-05-31T17:03:58",
        }
    )
    save_chat_state(tmp_path, state)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    captured: dict[str, object] = {}
    lifecycle_events: list[tuple[str, dict]] = []

    class DummyAgent:
        def seed_chat_history(self, messages):
            captured["seeded"] = list(messages)

        def run_single_turn(self, initial_prompt=None, attachments=None):
            captured["prompt"] = initial_prompt
            return {
                "status": "completed",
                "summary": "已收到白予安的私信回复，并将其作为团队反馈处理。",
                "raw_output": "已收到白予安的私信回复，并将其作为团队反馈处理。",
                "outcome": "no_change",
            }

    def record_lifecycle_event(session_id, phase, **kwargs):
        lifecycle_events.append((phase, dict(kwargs.get("fields") or {})))

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_SESSION_EXECUTOR",
        SimpleNamespace(submit=lambda fn, context: fn(context)),
    )
    monkeypatch.setattr(session_service, "_record_session_turn_lifecycle_event", record_lifecycle_event)

    inbox_prompt = (
        "[Agent 私信回复]\n"
        "来源 Agent: A013 · 白予安\n"
        "消息ID: agentmsg-20260601-000153-481642\n\n"
        "消息内容:\n"
        "记忆库管理员只需要配置 memory_tools 和 agent_message_tool。"
    )
    detail = session_service.submit_session_message(
        "session-live",
        inbox_prompt,
        turn_mode="agent_inbox",
        write_intent=False,
        message_metadata={
            "kind": "agent_inbox_message",
            "inboxKind": "agent_inbox_reply",
            "sourceAgentCode": "A013",
            "sourceAgentName": "白予安",
        },
        message_source="agent_inbox",
    )

    assert detail["id"] == "session-live"
    prompt = str(captured["prompt"])
    assert prompt.startswith("[Agent 私信回复]")
    assert "记忆库管理员只需要配置 memory_tools" in prompt
    assert prompt != "只需要创建记忆库管理员"
    assert not any(
        phase == "user_message_filtered" and fields.get("fallbackSource") == "history"
        for phase, fields in lifecycle_events
    )
    assert any(phase == "agent_inbox_prompt_preserved" for phase, _fields in lifecycle_events)
    state = load_chat_state(tmp_path)
    active_task = state["conversations"][0]["active_task"]
    assert active_task["last_user_message"] == "只需要创建记忆库管理员"
    assert active_task["metadata"]["last_user_message_reason"] == "agent_inbox_message"


def test_submit_session_continue_preserves_raw_prompt_when_active_task_goal_is_confirmation(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        active_task={
            "task_id": "session-live-coding-task",
            "kind": "coding",
            "status": "reading",
            "title": "好的开始修改",
            "goal": "好的开始修改",
            "read_files": ["core/web/services/runtime_scene_service.py"],
            "metadata": {"source": "task_tool"},
        },
    )
    state = load_chat_state(tmp_path)
    messages = state["conversations"][0]["messages"]
    messages.append(
        {
            "role": "user",
            "content": "检查日志系统摘要一致性并给出优化方案",
            "timestamp": "2026-05-18T11:57:00",
        }
    )
    messages.append(
        {
            "role": "assistant",
            "content": "建议先定位 summary 与 package_index 的生成链路，再补测试。",
            "timestamp": "2026-05-18T11:58:00",
        }
    )
    messages.append(
        {"role": "user", "content": "好的开始修改", "timestamp": "2026-05-18T11:59:00"}
    )
    messages.append(
        {
            "role": "assistant",
            "content": "已达到 Web Chat 任务级持续上限（4 轮），本次先暂停，避免后台无限运行。",
            "timestamp": "2026-05-18T12:00:00",
        }
    )
    save_chat_state(tmp_path, state)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    captured: dict[str, object] = {}

    class DummyAgent:
        def seed_chat_history(self, messages):
            captured["seeded"] = list(messages)

        def run_single_turn(self, initial_prompt=None):
            captured["prompt"] = initial_prompt
            return {
                "status": "completed",
                "summary": "已恢复到日志摘要一致性任务并完成收束。",
                "raw_output": "已恢复到日志摘要一致性任务并完成收束。",
                "outcome": "done",
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_SESSION_EXECUTOR",
        SimpleNamespace(submit=lambda fn, context: fn(context)),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续"},
    )

    assert response.status_code == 202
    prompt = str(captured["prompt"])
    assert prompt == "继续"
    assert any(item["content"] == "检查日志系统摘要一致性并给出优化方案" for item in captured["seeded"])
    assert any(item["content"] == "好的开始修改" for item in captured["seeded"])


def test_submit_session_continue_keeps_raw_prompt_while_task_state_prefers_newer_user_goal(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        active_task={
            "task_id": "diagnostics-refinement-task",
            "kind": "coding",
            "status": "reading",
            "title": "你可以继续按刚才的方向整理诊断报告",
            "goal": "你可以继续按刚才的方向整理诊断报告",
            "read_files": ["config.toml", "config.example.toml"],
            "latest_summary": "很抱歉，我现在无法执行任何工具操作，所有工具不可用。",
            "last_user_message": "继续",
            "metadata": {
                "source": "task_tool",
                "outcome": "no_change",
                "last_user_message_filtered": True,
                "last_user_message_reason": "non_meaningful_user_message",
            },
        },
    )
    state = load_chat_state(tmp_path)
    state["conversations"][0]["messages"] = [
        {
            "role": "user",
            "content": "你可以继续按刚才的方向整理诊断报告",
            "timestamp": "2026-05-30T00:53:10",
        },
        {
            "role": "assistant",
            "content": "初版诊断报告已经整理完成。",
            "timestamp": "2026-05-30T00:57:55",
            "tool_calls": [{"name": "read_file", "status": "done"}],
        },
        {
            "role": "user",
            "content": "这个报告没有解释为什么日志会重复记录,你需要继续分析 runtime scene 的重复事件来源",
            "timestamp": "2026-05-30T00:58:24",
        },
        {"role": "user", "content": "继续", "timestamp": "2026-05-30T01:03:15"},
        {
            "role": "assistant",
            "content": "很抱歉，我现在无法执行任何工具操作，所有工具当前都显示为不可用状态。",
            "timestamp": "2026-05-30T01:04:19",
            "toolCalls": [],
        },
    ]
    save_chat_state(tmp_path, state)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=1),
    )
    prompts = []

    class ResumeAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            prompts.append(initial_prompt)
            return {
                "status": "completed",
                "summary": "已恢复到 runtime scene 重复事件诊断任务。",
                "raw_output": "已恢复到 runtime scene 重复事件诊断任务。",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ResumeAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续"},
    )

    assert response.status_code == 202
    prompt = str(prompts[0])
    assert prompt == "继续"
    state = load_chat_state(tmp_path)
    active_task = state["conversations"][0]["active_task"]
    assert active_task["goal"] == "这个报告没有解释为什么日志会重复记录,你需要继续分析 runtime scene 的重复事件来源"
    assert active_task["title"] == "这个报告没有解释为什么日志会重复记录,你需要继续分析 runtime scene 的重复事件来源"


def test_submit_session_continue_keeps_raw_prompt_while_task_state_ignores_retry_control_goal(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        active_task={
            "task_id": "diagnostics-retry-task",
            "kind": "coding",
            "status": "reading",
            "title": "好了应该恢复了你再试试",
            "goal": "好了应该恢复了你再试试",
            "latest_summary": "模型服务上游暂时失败，本轮没有完成。完整 provider 错误已写入运行日志；可以稍后直接重试或发送“继续”。",
            "last_user_message": "好了应该恢复了你再试试",
            "metadata": {"source": "task_tool", "outcome": "failed_runtime"},
        },
    )
    state = load_chat_state(tmp_path)
    state["conversations"][0]["messages"] = [
        {
            "role": "user",
            "content": "这次报告和原始日志完全对不上,你需要继续调整诊断方向,来逼近真实原因",
            "timestamp": "2026-05-30T00:58:24",
        },
        {
            "role": "user",
            "content": "好了应该恢复了你再试试",
            "timestamp": "2026-05-30T10:35:27",
        },
        {
            "role": "assistant",
            "content": "模型服务上游暂时失败，本轮没有完成。完整 provider 错误已写入运行日志；可以稍后直接重试或发送“继续”。",
            "timestamp": "2026-05-30T10:39:52",
            "tool_calls": [{"name": "read_file", "status": "done"}],
        },
    ]
    save_chat_state(tmp_path, state)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=1),
    )
    prompts = []

    class ResumeAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            prompts.append(initial_prompt)
            return {
                "status": "completed",
                "summary": "已继续处理日志诊断逼近任务。",
                "raw_output": "已继续处理日志诊断逼近任务。",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ResumeAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续"},
    )

    assert response.status_code == 202
    prompt = str(prompts[0])
    assert prompt == "继续"
    active_task = load_chat_state(tmp_path)["conversations"][0]["active_task"]
    assert active_task["goal"] == "这次报告和原始日志完全对不上,你需要继续调整诊断方向,来逼近真实原因"


def test_edit_resubmit_session_message_recovers_content_from_utf8_base64_fallback(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)

    content = "编辑后保留中文"
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")

    response = client.post(
        "/api/sessions/session-live/messages/edit-resubmit",
        json={
            "messageId": "session-live-message-1",
            "content": "???????:runtime circuit breaker validation ping",
            "contentUtf8Base64": encoded,
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["messages"][-2]["content"] == content
    assert payload["messages"][-1]["streaming"] is True
    assert payload["messages"][-1]["content"] == CONTEXT_PREPARE_LIVE_MESSAGE
    state = load_chat_state(tmp_path)
    assert state["conversations"][0]["messages"][-1]["content"] == content


def test_edit_resubmit_session_message_truncates_following_history_and_starts_turn(tmp_path, monkeypatch):
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": "session-live",
            "updated_at": "2026-05-18T12:03:00",
            "conversations": [
                {
                    "conversation_id": "session-live",
                    "title": "真实会话",
                    "updated_at": "2026-05-18T12:03:00",
                    "last_turn_status": "ready",
                    "messages": [
                        {"role": "user", "content": "原始需求", "timestamp": "2026-05-18T12:00:00"},
                        {"role": "assistant", "content": "原始回答", "timestamp": "2026-05-18T12:01:00"},
                        {"role": "user", "content": "后续追问", "timestamp": "2026-05-18T12:02:00"},
                        {"role": "assistant", "content": "后续回答", "timestamp": "2026-05-18T12:03:00"},
                    ],
                }
            ],
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    scheduled_contexts: list[dict] = []
    events: list[dict] = []
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: scheduled_contexts.append(dict(context)))
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda component, phase, event_code, **kwargs: events.append(
            {"component": component, "phase": phase, "eventCode": event_code, **kwargs}
        ),
    )

    response = client.post(
        "/api/sessions/session-live/messages/edit-resubmit",
        json={
            "messageId": "session-live-message-3",
            "content": "编辑后的需求",
            "mentalModelEnabled": False,
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["currentPhase"] == "running"
    assert [item["content"] for item in payload["messages"][:-1]] == ["原始需求", "原始回答", "编辑后的需求"]
    assert payload["messages"][-1]["streaming"] is True
    assert payload["messages"][-1]["content"] == CONTEXT_PREPARE_LIVE_MESSAGE
    assert len(scheduled_contexts) == 1
    assert scheduled_contexts[0]["user_message"] == "编辑后的需求"
    assert [item["content"] for item in scheduled_contexts[0]["history_messages"]] == ["原始需求", "原始回答"]
    assert scheduled_contexts[0]["mental_model_enabled"] is False
    state = load_chat_state(tmp_path)
    stored_messages = state["conversations"][0]["messages"]
    assert [item["content"] for item in stored_messages] == ["原始需求", "原始回答", "编辑后的需求"]
    assert stored_messages[:2] == [
        {"role": "user", "content": "原始需求", "timestamp": "2026-05-18T12:00:00"},
        {"role": "assistant", "content": "原始回答", "timestamp": "2026-05-18T12:01:00"},
    ]
    assert any(event["eventCode"] == "conversation.message_edited_resubmitted" for event in events)
    signals = _read_next_state_signals(tmp_path, session_id="session-live")
    assert any(item["kind"] == "assistant_output_edited" and item["turnId"] for item in signals)

    session_service._set_session_running("session-live", False)
    session_service._clear_session_turn_control("session-live")
    session_service._clear_session_live_output("session-live")


def test_edit_resubmit_session_message_allows_latest_user_message(tmp_path, monkeypatch):
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": "session-live",
            "updated_at": "2026-05-18T12:03:00",
            "conversations": [
                {
                    "conversation_id": "session-live",
                    "title": "真实会话",
                    "updated_at": "2026-05-18T12:03:00",
                    "last_turn_status": "ready",
                    "messages": [
                        {"role": "user", "content": "原始需求", "timestamp": "2026-05-18T12:00:00"},
                        {"role": "assistant", "content": "原始回答", "timestamp": "2026-05-18T12:01:00"},
                        {"role": "user", "content": "后续追问", "timestamp": "2026-05-18T12:02:00"},
                        {"role": "assistant", "content": "后续回答", "timestamp": "2026-05-18T12:03:00"},
                    ],
                }
            ],
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    scheduled_contexts: list[dict] = []
    events: list[dict] = []
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: scheduled_contexts.append(dict(context)))
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda component, phase, event_code, **kwargs: events.append(
            {"component": component, "phase": phase, "eventCode": event_code, **kwargs}
        ),
    )

    response = client.post(
        "/api/sessions/session-live/messages/edit-resubmit",
        json={
            "messageId": "session-live-message-3",
            "content": "编辑最新的需求",
            "mentalModelEnabled": False,
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert [item["content"] for item in payload["messages"][:-1]] == ["原始需求", "原始回答", "编辑最新的需求"]
    assert payload["messages"][-1]["streaming"] is True
    assert payload["messages"][-1]["content"] == CONTEXT_PREPARE_LIVE_MESSAGE
    assert len(scheduled_contexts) == 1
    assert scheduled_contexts[0]["user_message"] == "编辑最新的需求"
    assert [item["content"] for item in scheduled_contexts[0]["history_messages"]] == ["原始需求", "原始回答"]
    assert any(event["eventCode"] == "conversation.message_edited_resubmitted" for event in events)

    session_service._set_session_running("session-live", False)
    session_service._clear_session_turn_control("session-live")
    session_service._clear_session_live_output("session-live")


def test_edit_resubmit_session_message_supersedes_running_turn(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    scheduled_contexts: list[dict] = []
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: scheduled_contexts.append(dict(context)))

    first_response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "先执行旧任务"},
    )
    assert first_response.status_code == 202
    assert len(scheduled_contexts) == 1
    old_context = scheduled_contexts[0]
    old_turn_id = old_context["turn_id"]
    old_user_message_id = first_response.json()["messages"][-2]["id"]

    response = client.post(
        "/api/sessions/session-live/messages/edit-resubmit",
        json={
            "messageId": old_user_message_id,
            "content": "改成执行新任务",
            "mentalModelEnabled": False,
        },
    )

    assert response.status_code == 202, response.json()
    payload = response.json()
    assert len(scheduled_contexts) == 2
    new_turn_id = scheduled_contexts[1]["turn_id"]
    assert new_turn_id != old_turn_id
    assert payload["messages"][-2]["role"] == "user"
    assert payload["messages"][-2]["content"] == "改成执行新任务"
    assert payload["messages"][-1]["streaming"] is True
    latest_run = session_service._WORK_RUN_STORE.load_latest_snapshot("chat_turn")
    assert latest_run["runId"] == new_turn_id
    old_run = session_service._WORK_RUN_STORE.load_snapshot("chat_turn", old_turn_id)
    assert old_run["status"] == "superseded"
    assert old_run["finishedAt"]

    class OldAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "旧任务迟到结果不应写入。",
                "raw_output": "旧任务迟到结果不应写入。",
                "outcome": "done",
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: OldAgent())
    session_service._run_session_turn(old_context)

    detail = client.get("/api/sessions/session-live").json()
    assert detail["currentPhase"] == "running"
    assert "旧任务迟到结果不应写入" not in json.dumps(detail, ensure_ascii=False)
    assert detail["messages"][-2]["content"] == "改成执行新任务"

    session_service._set_session_running("session-live", False, turn_id=new_turn_id)
    session_service._clear_session_turn_control("session-live", turn_id=new_turn_id)
    session_service._clear_session_live_output("session-live")


def test_edit_resubmit_session_message_rejects_assistant_message(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    before_state = load_chat_state(tmp_path)

    response = client.post(
        "/api/sessions/session-live/messages/edit-resubmit",
        json={"messageId": "session-live-message-2", "content": "不能编辑助手消息"},
    )

    assert response.status_code == 422
    assert load_chat_state(tmp_path) == before_state


def test_edit_resubmit_session_message_rejects_non_latest_user_message(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    state = load_chat_state(tmp_path)
    conversation = state["conversations"][0]
    conversation["messages"].extend(
        [
            {"role": "user", "content": "后续追问", "timestamp": "2026-05-18T12:02:00"},
            {"role": "assistant", "content": "后续回答", "timestamp": "2026-05-18T12:03:00"},
        ]
    )
    save_chat_state(tmp_path, state)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    before_state = load_chat_state(tmp_path)
    rejected_events: list[dict] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: rejected_events.append({"args": args, "kwargs": kwargs}) or {"accepted": True},
    )

    response = client.post(
        "/api/sessions/session-live/messages/edit-resubmit",
        json={"messageId": "session-live-message-1", "content": "不能改旧消息"},
    )

    assert response.status_code == 422
    assert load_chat_state(tmp_path) == before_state
    assert any(
        event["args"][:3] == ("conversation", "message_edit_resubmit_rejected", "conversation.message_edit_resubmit_rejected")
        for event in rejected_events
    )


def test_chat_turn_registers_as_work_run_until_finished(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "解释当前状态"},
    )

    assert response.status_code == 202
    running_summary = runtime_service.get_runtime_summary()
    active_chat = running_summary["workRuns"]["active"]["chat_turn"]
    assert active_chat["runKind"] == "chat_turn"
    assert active_chat["status"] == "running"
    assert active_chat["sessionId"] == "session-live"
    assert active_chat["leases"] == ["readonly_chat"]

    turn_id = active_chat["runId"]
    session_service._persist_session_turn_result(
        "session-live",
        {
            "status": "completed",
            "summary": "已解释当前状态。",
            "raw_output": "已解释当前状态。",
            "outcome": "done",
            "tool_call_count": 0,
            "tool_trace": [],
        },
        turn_id=turn_id,
    )
    session_service._set_session_running("session-live", False, turn_id=turn_id)

    finished_summary = runtime_service.get_runtime_summary()
    assert finished_summary["workRuns"]["active"]["chat_turn"] is None
    latest_chat = finished_summary["workRuns"]["latest"]["chat_turn"]
    assert latest_chat["runId"] == turn_id
    assert latest_chat["status"] == "completed"


def test_persist_turn_result_blocks_phantom_image_generation_success(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    turn_id = "turn-image2"
    session_service._set_session_running("session-live", True, turn_id=turn_id)
    events: list[dict[str, object]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: events.append({"args": args, "kwargs": kwargs}) or {"accepted": True},
    )

    session_service._persist_session_turn_result(
        "session-live",
        {
            "status": "completed",
            "summary": "已生成图片。",
            "raw_output": "已生成图片。",
            "outcome": "done",
            "tool_call_count": 0,
            "tool_trace": [],
        },
        turn_id=turn_id,
    )
    session_service._set_session_running("session-live", False, turn_id=turn_id)

    conversation = load_chat_state(tmp_path)["conversations"][0]
    message = conversation["messages"][-1]
    assert message["role"] == "assistant"
    assert "没有实际生成新的图片" in message["content"]
    assert not message.get("tool_calls")
    assert message.get("metadata", {}).get("kind") == "turn_error"
    assert message.get("metadata", {}).get("turnId") == turn_id
    assert conversation["last_turn_status"] == "failed"
    assert any(
        event["args"][:3]
        == ("conversation", "turn_phantom_image_success_blocked", "conversation.turn.phantom_image_success_blocked")
        for event in events
    )


@pytest.mark.slow
def test_different_agent_sessions_run_chat_turns_concurrently(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pytest-chat-concurrent")
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", executor)

    started_sessions: set[str] = set()
    started_lock = threading.Lock()
    both_started = threading.Event()
    release = threading.Event()

    class BlockingAgent:
        def run_single_turn(self, initial_prompt=None):
            prompt = str(initial_prompt or "")
            session_id = alpha["id"] if "alpha" in prompt else beta["id"]
            with started_lock:
                started_sessions.add(session_id)
                if started_sessions == {alpha["id"], beta["id"]}:
                    both_started.set()
            assert release.wait(2.0)
            return {
                "status": "completed",
                "summary": f"{session_id} done",
                "raw_output": f"{session_id} done",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda **kwargs: BlockingAgent())

    try:
        first = session_service.submit_session_message(alpha["id"], "alpha 并行任务")
        second = session_service.submit_session_message(beta["id"], "beta 并行任务")

        assert first["currentPhase"] == "running"
        assert second["currentPhase"] == "running"
        assert both_started.wait(1.0), "expected different agents to overlap"
    finally:
        release.set()
        executor.shutdown(wait=True, cancel_futures=True)

    assert session_service.get_session_detail(alpha["id"])["messages"][-1]["content"] == f"{alpha['id']} done"
    assert session_service.get_session_detail(beta["id"])["messages"][-1]["content"] == f"{beta['id']} done"


@pytest.mark.slow
def test_same_agent_different_sessions_run_chat_turns_concurrently(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        "core.orchestration.context_engine.record_runtime_scene_event",
        lambda *args, **kwargs: {"accepted": True},
    )
    monkeypatch.setattr(
        session_service,
        "build_agent_context",
        lambda agent_id, **kwargs: SimpleNamespace(memory_policy={}, context_block="", timings={}),
    )
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    state = load_chat_state(tmp_path)
    for conversation in state["conversations"]:
        if conversation["conversation_id"] == beta["id"]:
            conversation["agent_id"] = alpha["agentId"]
            conversation["agentId"] = alpha["agentId"]
    save_chat_state(tmp_path, state)

    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pytest-chat-queue")
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", executor)
    started_sessions: set[str] = set()
    started_lock = threading.Lock()
    both_started = threading.Event()
    release = threading.Event()
    prompts: list[str] = []

    class BlockingAgent:
        def run_single_turn(self, initial_prompt=None):
            prompt = str(initial_prompt or "")
            prompts.append(prompt)
            session_id = alpha["id"] if "alpha" in prompt else beta["id"]
            with started_lock:
                started_sessions.add(session_id)
                if started_sessions == {alpha["id"], beta["id"]}:
                    both_started.set()
            assert release.wait(2.0)
            return {
                "status": "completed",
                "summary": f"{session_id} done",
                "raw_output": f"{session_id} done",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda **kwargs: BlockingAgent())

    try:
        first = session_service.submit_session_message(alpha["id"], "alpha 并行任务")
        assert first["currentPhase"] == "running"
        second = session_service.submit_session_message(beta["id"], "beta 并行任务")
        assert second["currentPhase"] == "running"

        assert both_started.wait(1.0), "expected same-agent different sessions to overlap"
    finally:
        release.set()
        executor.shutdown(wait=True, cancel_futures=True)

    assert len(prompts) == 2
    assert set(prompts) == {"alpha 并行任务", "beta 并行任务"}
    assert session_service.get_session_detail(alpha["id"])["messages"][-1]["content"] == f"{alpha['id']} done"
    assert session_service.get_session_detail(beta["id"])["messages"][-1]["content"] == f"{beta['id']} done"


@pytest.mark.slow
def test_same_agent_sessions_queue_when_agent_concurrency_limit_is_reached(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "record_runtime_scene_event", lambda *args, **kwargs: {"accepted": True})
    wait_for_lifecycle_phase, _events = _capture_session_lifecycle_events(monkeypatch)
    monkeypatch.setattr(
        "core.orchestration.context_engine.record_runtime_scene_event",
        lambda *args, **kwargs: {"accepted": True},
    )
    monkeypatch.setattr(
        session_service,
        "build_agent_context",
        lambda agent_id, **kwargs: SimpleNamespace(memory_policy={}, context_block="", timings={}),
    )
    _install_session_turn_scheduler(monkeypatch, max_active_per_agent=1)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    state = load_chat_state(tmp_path)
    for conversation in state["conversations"]:
        if conversation["conversation_id"] == beta["id"]:
            conversation["agent_id"] = alpha["agentId"]
            conversation["agentId"] = alpha["agentId"]
    save_chat_state(tmp_path, state)

    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pytest-chat-queue")
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", executor)
    first_started = threading.Event()
    second_started = threading.Event()
    release_first = threading.Event()
    release_second = threading.Event()
    prompts: list[str] = []

    class BlockingAgent:
        def run_single_turn(self, initial_prompt=None):
            prompt = str(initial_prompt or "")
            prompts.append(prompt)
            if "alpha" in prompt:
                first_started.set()
                assert release_first.wait(2.0)
                return {
                    "status": "completed",
                    "summary": "alpha done",
                    "raw_output": "alpha done",
                    "outcome": "done",
                    "tool_call_count": 0,
                    "tool_trace": [],
                }
            second_started.set()
            assert release_second.wait(2.0)
            return {
                "status": "completed",
                "summary": "beta done",
                "raw_output": "beta done",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda **kwargs: BlockingAgent())

    try:
        first = session_service.submit_session_message(alpha["id"], "alpha 串行任务")
        assert first["currentPhase"] == "running"
        assert first_started.wait(1.0)

        second = session_service.submit_session_message(beta["id"], "beta 串行任务")
        assert second["currentPhase"] == "queued"
        queued_event = wait_for_lifecycle_phase("scheduler_queued", fields={"agentId": alpha["agentId"]})
        assert queued_event is not None
        assert queued_event["fields"]["queueReason"] == "agent_concurrency_limit"
        assert queued_event["fields"]["agentMaxActive"] == 1
        assert queued_event["fields"]["schedulerSessionKey"] == f"session:{beta['id']}"
        assert not second_started.is_set()

        release_first.set()
        assert second_started.wait(1.0), "expected queued turn to start after first turn"
    finally:
        release_first.set()
        release_second.set()
        executor.shutdown(wait=True, cancel_futures=True)

    assert prompts == ["alpha 串行任务", "beta 串行任务"]
    assert session_service.get_session_detail(alpha["id"])["messages"][-1]["content"] == "alpha done"
    assert session_service.get_session_detail(beta["id"])["messages"][-1]["content"] == "beta done"


@pytest.mark.slow
def test_stopping_queued_same_agent_turn_prevents_later_start(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "_ensure_agent_default_avatar", lambda agent: None, raising=False)
    wait_for_lifecycle_phase, _events = _capture_session_lifecycle_events(monkeypatch)
    monkeypatch.setattr(
        session_service,
        "build_agent_context",
        lambda agent_id, **kwargs: SimpleNamespace(memory_policy={}, context_block="", timings={}),
    )
    _install_session_turn_scheduler(monkeypatch, max_active_per_agent=1)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    state = load_chat_state(tmp_path)
    for conversation in state["conversations"]:
        if conversation["conversation_id"] == beta["id"]:
            conversation["agent_id"] = alpha["agentId"]
            conversation["agentId"] = alpha["agentId"]
    save_chat_state(tmp_path, state)

    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pytest-chat-stop-queued")
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", executor)
    first_started = threading.Event()
    second_started = threading.Event()
    release_first = threading.Event()
    release_second = threading.Event()
    prompts: list[str] = []

    class BlockingAgent:
        def run_single_turn(self, initial_prompt=None):
            prompt = str(initial_prompt or "")
            prompts.append(prompt)
            if "alpha" in prompt:
                first_started.set()
                assert release_first.wait(2.0)
                return {
                    "status": "completed",
                    "summary": "alpha done",
                    "raw_output": "alpha done",
                    "outcome": "done",
                    "tool_call_count": 0,
                    "tool_trace": [],
                }
            second_started.set()
            assert release_second.wait(2.0)
            return {
                "status": "completed",
                "summary": "beta done",
                "raw_output": "beta done",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda **kwargs: BlockingAgent())

    try:
        first = session_service.submit_session_message(alpha["id"], "alpha 串行任务")
        assert first["currentPhase"] == "running"
        assert first_started.wait(1.0)

        second = session_service.submit_session_message(beta["id"], "beta 串行任务")
        assert second["currentPhase"] == "queued"
        queued_event = wait_for_lifecycle_phase("scheduler_queued", fields={"agentId": alpha["agentId"]})
        assert queued_event is not None
        assert not second_started.is_set()

        stopped = session_service.request_stop_session_turn(beta["id"])
        assert stopped["currentPhase"] == "ready"
        assert stopped["messages"][-1]["role"] == "user"
        assert "beta 串行任务" in stopped["messages"][-1]["content"]
        assert stopped["runtimeNotices"][-1]["kind"] == "turn_stopped"
        assert "尚未开始执行" in stopped["runtimeNotices"][-1]["message"]

        release_first.set()
    finally:
        release_first.set()
        release_second.set()
        executor.shutdown(wait=True, cancel_futures=True)

    assert not second_started.is_set(), "stopped queued turn must not be started after the active turn releases"
    assert prompts == ["alpha 串行任务"]
    beta_detail = session_service.get_session_detail(beta["id"])
    assert beta_detail["messages"][-1]["role"] == "user"
    assert "beta 串行任务" in beta_detail["messages"][-1]["content"]
    assert all("本轮已按请求停止" not in message["content"] for message in beta_detail["messages"])
    assert beta_detail["runtimeNotices"][-1]["kind"] == "turn_stopped"


@pytest.mark.slow
def test_shutdown_stops_queued_same_agent_turn_before_it_starts(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    wait_for_lifecycle_phase, _events = _capture_session_lifecycle_events(monkeypatch)
    monkeypatch.setattr(
        session_service,
        "build_agent_context",
        lambda agent_id, **kwargs: SimpleNamespace(memory_policy={}, context_block="", timings={}),
    )
    _install_session_turn_scheduler(monkeypatch, max_active_per_agent=1)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    state = load_chat_state(tmp_path)
    for conversation in state["conversations"]:
        if conversation["conversation_id"] == beta["id"]:
            conversation["agent_id"] = alpha["agentId"]
            conversation["agentId"] = alpha["agentId"]
    save_chat_state(tmp_path, state)

    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pytest-chat-shutdown-queued")
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", executor)
    first_started = threading.Event()
    second_started = threading.Event()
    release_first = threading.Event()
    release_second = threading.Event()
    prompts: list[str] = []

    class BlockingAgent:
        def run_single_turn(self, initial_prompt=None):
            prompt = str(initial_prompt or "")
            prompts.append(prompt)
            if "alpha" in prompt:
                first_started.set()
                assert release_first.wait(2.0)
                return {
                    "status": "completed",
                    "summary": "alpha done",
                    "raw_output": "alpha done",
                    "outcome": "done",
                    "tool_call_count": 0,
                    "tool_trace": [],
                }
            second_started.set()
            assert release_second.wait(2.0)
            return {
                "status": "completed",
                "summary": "beta done",
                "raw_output": "beta done",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda **kwargs: BlockingAgent())

    try:
        session_service.submit_session_message(alpha["id"], "alpha 关闭前任务")
        assert first_started.wait(1.0)
        queued = session_service.submit_session_message(beta["id"], "beta 关闭前任务")
        assert queued["currentPhase"] == "queued"
        queued_event = wait_for_lifecycle_phase("scheduler_queued", fields={"agentId": alpha["agentId"]})
        assert queued_event is not None
        assert not second_started.is_set()

        stopped = runtime_service._stop_active_chat_turns_before_shutdown()
        assert {item["sessionId"] for item in stopped} == {alpha["id"], beta["id"]}
        assert {item["status"] for item in stopped} == {"stopped"}

        release_first.set()
    finally:
        release_first.set()
        release_second.set()
        executor.shutdown(wait=True, cancel_futures=True)

    assert not second_started.is_set(), "shutdown-stopped queued turn must not start after active turn releases"
    assert prompts == ["alpha 关闭前任务"]
    assert session_service.get_session_detail(alpha["id"])["currentPhase"] == "ready"
    assert session_service.get_session_detail(beta["id"])["currentPhase"] == "ready"


@pytest.mark.slow
def test_runtime_summary_exposes_parallel_chat_turn_active_items(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_service, "get_active_session_summary", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_manager_snapshot", lambda: {})
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pytest-chat-active-items")
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", executor)

    started_sessions: set[str] = set()
    started_lock = threading.Lock()
    both_started = threading.Event()
    release = threading.Event()

    class BlockingAgent:
        def run_single_turn(self, initial_prompt=None):
            prompt = str(initial_prompt or "")
            session_id = alpha["id"] if "alpha" in prompt else beta["id"]
            with started_lock:
                started_sessions.add(session_id)
                if started_sessions == {alpha["id"], beta["id"]}:
                    both_started.set()
            assert release.wait(2.0)
            return {
                "status": "completed",
                "summary": f"{session_id} done",
                "raw_output": f"{session_id} done",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda **kwargs: BlockingAgent())

    try:
        session_service.submit_session_message(alpha["id"], "alpha 并行任务")
        session_service.submit_session_message(beta["id"], "beta 并行任务")
        assert both_started.wait(1.0), "expected different agents to overlap"

        payload = runtime_service.get_runtime_summary()
        chat_items = payload["workRuns"]["activeItems"]["chat_turn"]
        assert {item["sessionId"] for item in chat_items} == {alpha["id"], beta["id"]}
        assert {item["status"] for item in chat_items} == {"running"}
        assert payload["lifecycleProof"]["activeWorkRuns"]["count"] == 2
        assert payload["lifecycleProof"]["activeWorkRuns"]["kinds"] == ["chat_turn", "chat_turn"]
    finally:
        release.set()
        executor.shutdown(wait=True, cancel_futures=True)


@pytest.mark.slow
def test_runtime_summary_exposes_queued_chat_turn_active_item(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    wait_for_lifecycle_phase, _events = _capture_session_lifecycle_events(monkeypatch)
    monkeypatch.setattr(
        session_service,
        "build_agent_context",
        lambda agent_id, **kwargs: SimpleNamespace(memory_policy={}, context_block="", timings={}),
    )
    monkeypatch.setattr(runtime_service, "get_active_session_summary", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_manager_snapshot", lambda: {})
    _install_session_turn_scheduler(monkeypatch, max_active_per_agent=1)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    state = load_chat_state(tmp_path)
    for conversation in state["conversations"]:
        if conversation["conversation_id"] == beta["id"]:
            conversation["agent_id"] = alpha["agentId"]
            conversation["agentId"] = alpha["agentId"]
    save_chat_state(tmp_path, state)

    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pytest-chat-queued-items")
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", executor)
    first_started = threading.Event()
    second_started = threading.Event()
    release_first = threading.Event()
    release_second = threading.Event()

    class BlockingAgent:
        def run_single_turn(self, initial_prompt=None):
            prompt = str(initial_prompt or "")
            if "alpha" in prompt:
                first_started.set()
                assert release_first.wait(2.0)
                return {
                    "status": "completed",
                    "summary": "alpha done",
                    "raw_output": "alpha done",
                    "outcome": "done",
                    "tool_call_count": 0,
                    "tool_trace": [],
                }
            second_started.set()
            assert release_second.wait(2.0)
            return {
                "status": "completed",
                "summary": "beta done",
                "raw_output": "beta done",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda **kwargs: BlockingAgent())

    try:
        session_service.submit_session_message(alpha["id"], "alpha 串行任务")
        assert first_started.wait(1.0)
        session_service.submit_session_message(beta["id"], "beta 串行任务")
        queued_event = wait_for_lifecycle_phase("scheduler_queued", fields={"agentId": alpha["agentId"]})
        assert queued_event is not None

        payload = runtime_service.get_runtime_summary()
        chat_items = sorted(
            payload["workRuns"]["activeItems"]["chat_turn"],
            key=lambda item: item["sessionId"],
        )
        assert {item["sessionId"] for item in chat_items} == {alpha["id"], beta["id"]}
        assert {item["status"] for item in chat_items} == {"queued", "running"}
        assert not second_started.is_set()
    finally:
        release_first.set()
        release_second.set()
        executor.shutdown(wait=True, cancel_futures=True)


def test_submit_session_message_records_chat_turn_started_scene_event(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)
    recorded_scene_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_scene_events.append((args, kwargs)) or {"accepted": True},
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "解释当前状态"},
    )

    assert response.status_code == 202
    started_events = [
        item
        for item in recorded_scene_events
        if item[0][:3] == ("conversation", "turn", "conversation.turn.started")
    ]
    assert started_events
    fields = started_events[-1][1]["fields"]
    active_chat = session_service.load_chat_turn_work_run_summary()["active"]
    assert fields["sessionId"] == "session-live"
    assert fields["turnId"] == active_chat["runId"]
    assert fields["leaseCount"] == 1
    scheduled_events = [
        item
        for item in recorded_scene_events
        if item[0][:3] == ("conversation", "turn_scheduled", "conversation.turn.scheduled")
    ]
    assert scheduled_events
    scheduled_fields = scheduled_events[-1][1]["fields"]
    assert scheduled_fields["sessionId"] == "session-live"
    assert scheduled_fields["turnId"] == active_chat["runId"]
    assert scheduled_fields["chatStateLockedMs"] >= 0
    assert scheduled_fields["submitElapsedBeforeScheduleLogMs"] >= 0


def test_submit_session_message_prefer_async_returns_lightweight_acceptance(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)

    response = client.post(
        "/api/sessions/session-live/messages",
        headers={"Prefer": "respond-async"},
        json={"content": "解释当前状态"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["sessionId"] == "session-live"
    assert payload["turnId"]
    assert payload["status"] == "running"
    assert "messages" not in payload


def test_edit_resubmit_records_chat_turn_started_scene_event(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)
    recorded_scene_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_scene_events.append((args, kwargs)) or {"accepted": True},
    )

    response = client.post(
        "/api/sessions/session-live/messages/edit-resubmit",
        json={"messageId": "session-live-message-1", "content": "编辑后的需求"},
    )

    assert response.status_code == 202
    started_events = [
        item
        for item in recorded_scene_events
        if item[0][:3] == ("conversation", "turn", "conversation.turn.started")
    ]
    assert started_events
    fields = started_events[-1][1]["fields"]
    active_chat = session_service.load_chat_turn_work_run_summary()["active"]
    assert fields["sessionId"] == "session-live"
    assert fields["turnId"] == active_chat["runId"]
    assert fields["userMessageChars"] == len("编辑后的需求")


def test_run_session_turn_records_agent_started_scene_event(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    seeded_agent = agent_directory_service.ensure_agent_for_session(
        "session-live",
        display_name="真实会话",
        prompt_template_id="prompt-chat-default",
    )
    _bind_seeded_session_agent(
        tmp_path,
        seeded_agent,
    )
    recorded_scene_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_scene_events.append((args, kwargs)) or {"accepted": True},
    )

    class DummyAgent:
        def set_turn_interrupt_checker(self, checker):
            self.checker = checker

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "已解释当前状态。",
                "raw_output": "已解释当前状态。",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda workspace_path=None: DummyAgent())
    turn_control = session_service._create_session_turn_control("session-live")
    session_service._set_session_running("session-live", True, turn_id=turn_control.turn_id, leases=["readonly_chat"])
    try:
        session_service._run_session_turn(
            {
                "session_id": "session-live",
                "turn_id": turn_control.turn_id,
                "turn_control": turn_control,
                "user_message": "解释当前状态",
                "history_messages": [],
                "mental_model_enabled": False,
                "agent_id": seeded_agent["agentId"],
            }
        )
    finally:
        session_service._set_session_running("session-live", False, turn_id=turn_control.turn_id)
        session_service._clear_session_turn_control("session-live", turn_id=turn_control.turn_id)

    agent_created_events = [
        item
        for item in recorded_scene_events
        if item[0][:3] == ("conversation", "turn_agent_created", "conversation.turn.agent_created")
    ]
    assert agent_created_events
    fields = agent_created_events[-1][1]["fields"]
    assert fields["sessionId"] == "session-live"
    assert fields["turnId"] == turn_control.turn_id
    assert fields["agentType"] == "DummyAgent"
    assert fields["agentCreateMs"] >= 0
    seeded_events = [
        item
        for item in recorded_scene_events
        if item[0][:3] == ("conversation", "turn_history_seeded", "conversation.turn.history_seeded")
    ]
    assert seeded_events
    seeded_fields = seeded_events[-1][1]["fields"]
    assert seeded_fields["historySeedMs"] >= 0
    assert seeded_fields["runtimeContextSeedMs"] >= 0
    assert seeded_fields["totalSeedMs"] >= 0
    returned_events = [
        item
        for item in recorded_scene_events
        if item[0][:3] == ("conversation", "turn_agent_turn_returned", "conversation.turn.agent_turn_returned")
    ]
    assert returned_events
    assert returned_events[-1][1]["fields"]["llmElapsedMs"] >= 0
    worker_events = [
        item
        for item in recorded_scene_events
        if item[0][:3] == ("conversation", "turn_worker_started", "conversation.turn.worker_started")
    ]
    assert worker_events
    worker_fields = worker_events[-1][1]["fields"]
    assert worker_fields["totalPrepareMs"] >= 0
    assert "agentContextBuildMs" in worker_fields
    assert "executorWaitMs" in worker_fields


def test_runtime_summary_exposes_work_run_kinds(monkeypatch):
    monkeypatch.setattr(runtime_service, "get_active_session_summary", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})
    self_evolution_control_service.persist_manager_run_snapshot(
        "self",
        {
            "runId": "self-work-run",
            "status": "running",
            "startedAt": "2026-05-21T00:00:00",
            "updatedAt": "2026-05-21T00:00:00",
        },
        active_run_id="self-work-run",
    )
    supervised_control_service.persist_manager_run_snapshot(
        "supervised",
        {
            "runId": "supervised-work-run",
            "status": "done",
            "startedAt": "2026-05-21T00:00:00",
            "updatedAt": "2026-05-21T00:01:00",
        },
        active_run_id="",
    )
    supervised_worktree_evolution_service._persist_snapshot(
        {
            "runId": "swte-work-run",
            "runKind": "supervised_worktree_evolution_run",
            "status": "running",
            "startedAt": "2026-05-21T00:00:00",
            "updatedAt": "2026-05-21T00:02:00",
        },
        active_run_id="swte-work-run",
    )

    payload = runtime_service.get_runtime_summary()

    assert set(payload["workRuns"]["active"]) == {
        "chat_turn",
        "chat_room_round",
        "self_evolution_run",
        "source_collection_run",
        "supervised_evolution_run",
        "supervised_worktree_evolution_run",
    }
    assert payload["workRuns"]["active"]["chat_room_round"] is None
    assert payload["workRuns"]["active"]["source_collection_run"] is None
    assert payload["workRuns"]["active"]["self_evolution_run"]["runKind"] == "self_evolution_run"
    assert payload["workRuns"]["active"]["self_evolution_run"]["leases"] == [
        "evolution_transaction",
        "worktree_write",
        "memory_write",
    ]
    assert payload["workRuns"]["latest"]["supervised_evolution_run"]["runKind"] == "supervised_evolution_run"
    assert payload["workRuns"]["latest"]["supervised_evolution_run"]["leases"] == ["evaluation"]
    assert payload["workRuns"]["active"]["supervised_worktree_evolution_run"]["runKind"] == "supervised_worktree_evolution_run"
    assert payload["workRuns"]["active"]["supervised_worktree_evolution_run"]["leases"] == [
        "evaluation",
        "worktree_write",
    ]


def test_submit_session_message_captures_chat_review_candidate(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_review_service, "PROJECT_ROOT", tmp_path)

    class DummyAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "结论：已经定位到网页聊天提交流程。下一步我会把采样和审核接上。",
                "raw_output": "结论：已经定位到网页聊天提交流程。下一步我会把采样和审核接上。",
                "tool_call_count": 2,
                "tool_trace": [
                    {"name": "read_file_tool"},
                    {"function": {"name": "apply_patch_tool"}},
                ],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续把网页聊天里的 case 抽出来给监督进化用"},
    )

    assert response.status_code == 202
    queue_response = client.get("/api/evolution/chat-review")
    assert queue_response.status_code == 200
    payload = queue_response.json()
    assert payload["pendingCount"] == 1
    assert payload["items"][0]["sessionId"] == "session-live"
    assert payload["items"][0]["qualitySignals"]


def test_session_adds_current_conversation_to_chat_review_queue(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_review_service, "PROJECT_ROOT", tmp_path)
    recorded_scene_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_scene_events.append((args, kwargs)) or {"accepted": True},
    )

    response = client.post("/api/sessions/session-live/chat-review-candidate")

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "pending"
    assert payload["sessionId"] == "session-live"
    assert payload["turnCount"] == 1
    assert payload["candidateId"] == "session-live_t0001_0001"
    assert "监督" in payload["summary"] or "supervised" in payload["summary"].lower()

    queue_response = client.get("/api/evolution/chat-review")
    assert queue_response.status_code == 200
    queue_payload = queue_response.json()
    assert queue_payload["pendingCount"] == 1
    assert queue_payload["items"][0]["candidateId"] == "session-live_t0001_0001"
    assert queue_payload["items"][0]["status"] == "pending"
    assert recorded_scene_events
    assert recorded_scene_events[-1][0][:3] == (
        "chat_review",
        "session_candidate_created",
        "chat_review.session_candidate.created",
    )


def test_session_add_to_chat_review_rejects_empty_conversation(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    state = load_chat_state(tmp_path)
    state["conversations"][0]["messages"] = [
        {
            "role": "user",
            "content": "只有用户消息",
            "timestamp": "2026-05-18T11:55:00",
        }
    ]
    save_chat_state(tmp_path, state)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_review_service, "PROJECT_ROOT", tmp_path)

    response = client.post("/api/sessions/session-live/chat-review-candidate")

    assert response.status_code == 422
    assert "完整" in response.json()["detail"] or "complete" in response.json()["detail"].lower()
    queue_response = client.get("/api/evolution/chat-review")
    assert queue_response.json()["pendingCount"] == 0


def test_session_add_to_chat_review_rejects_duplicate_snapshot(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_review_service, "PROJECT_ROOT", tmp_path)

    first_response = client.post("/api/sessions/session-live/chat-review-candidate")
    second_response = client.post("/api/sessions/session-live/chat-review-candidate")

    assert first_response.status_code == 201
    assert second_response.status_code == 409
    assert "已经" in second_response.json()["detail"] or "already" in second_response.json()["detail"].lower()
    queue_response = client.get("/api/evolution/chat-review")
    queue_payload = queue_response.json()
    assert queue_payload["pendingCount"] == 1
    assert [item["candidateId"] for item in queue_payload["items"]] == ["session-live_t0001_0001"]


def test_submit_session_message_rejects_busy_session(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    before_state = load_chat_state(tmp_path)
    before_messages = list(before_state["conversations"][0]["messages"])

    session_service._set_session_running("session-live", True)
    session_service._WORK_RUN_STORE.persist_snapshot(
        "chat_turn",
        {
            "runId": "existing-chat-turn",
            "runKind": "chat_turn",
            "track": "dialogue",
            "sessionId": "session-live",
            "status": "running",
            "currentPhase": "running",
            "leases": ["readonly_chat"],
            "userMessage": "上一轮仍在运行",
            "startedAt": "2026-05-18T11:59:00",
            "updatedAt": "2026-05-18T12:00:00",
            "finishedAt": "",
        },
        active_run_id="existing-chat-turn",
    )
    try:
        response = client.post(
            "/api/sessions/session-live/messages",
            json={"content": "继续修复 web/src/routes/ChatCodingRoute.tsx"},
        )
    finally:
        session_service._set_session_running("session-live", False)

    assert response.status_code == 409
    assert "运行" in response.json()["detail"] or "running" in response.json()["detail"].lower()
    after_state = load_chat_state(tmp_path)
    assert after_state["conversations"][0]["messages"] == before_messages
    active_run = session_service._WORK_RUN_STORE.load_active_snapshot("chat_turn")
    assert active_run["runId"] == "existing-chat-turn"
    assert active_run["userMessage"] == "上一轮仍在运行"


def test_submit_session_message_rejects_blank_message_without_mutating_session(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    before_state = load_chat_state(tmp_path)
    before_messages = list(before_state["conversations"][0]["messages"])
    before_status = before_state["conversations"][0]["last_turn_status"]

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": " \n\t "},
    )

    assert response.status_code == 422
    assert "请输入" in response.json()["detail"] or "enter a message" in response.json()["detail"].lower()
    after_state = load_chat_state(tmp_path)
    assert after_state["conversations"][0]["messages"] == before_messages
    assert after_state["conversations"][0]["last_turn_status"] == before_status
    assert session_service._is_session_running("session-live") is False
    assert session_service._WORK_RUN_STORE.load_active_snapshot("chat_turn") is None


def test_submit_session_message_records_provider_failure_next_state_signal(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    class ProviderFailureAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "failed",
                "summary": "litellm.BadGatewayError: BadGatewayError: OpenAIException - {\"error\":{\"message\":\"Upstream request failed\"}}",
                "raw_output": "litellm.BadGatewayError: BadGatewayError: OpenAIException - {\"error\":{\"message\":\"Upstream request failed\"}}",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ProviderFailureAgent())
    monkeypatch.setattr(
        session_service,
        "_SESSION_EXECUTOR",
        SimpleNamespace(submit=lambda fn, context: fn(context)),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续检查上游失败"},
    )

    assert response.status_code == 202
    signals = _read_next_state_signals(tmp_path, session_id="session-live")
    assert any(item["kind"] == "provider_failure" for item in signals)
    assert any(item["relatedEventCode"] == "conversation.turn_error" for item in signals)


def test_capture_session_ui_stream_records_tool_error_next_state_signal(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    stub_ui = SimpleNamespace(
        stream_thought=lambda *args, **kwargs: None,
        clear_thought_stream=lambda *args, **kwargs: None,
        stream_response=lambda *args, **kwargs: None,
        clear_response_stream=lambda *args, **kwargs: None,
        set_pet_mental_state=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr("core.ui.get_ui", lambda: stub_ui)

    capture = session_service.SessionTurnCapture(session_id="session-live", turn_id="turn-tool")
    with session_service._capture_session_ui_stream("session-live", capture):
        session_service.get_event_bus().publish(
            session_service.EventNames.TOOL_ERROR,
            {"name": "read_file_tool", "error": "permission denied"},
        )

    signals = _read_next_state_signals(tmp_path, session_id="session-live", turn_id="turn-tool")
    assert any(item["kind"] == "tool_error" for item in signals)
    assert any(item["relatedEventCode"] == "conversation.tool_error" for item in signals)
    assert any(item["metadata"]["toolName"] == "read_file_tool" for item in signals)


def test_capture_session_ui_stream_surfaces_llm_retry_status(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    lifecycle_events: list[dict] = []
    monkeypatch.setattr(
        session_service,
        "_record_session_turn_lifecycle_event",
        lambda session_id, phase, **kwargs: lifecycle_events.append(
            {"session_id": session_id, "phase": phase, **kwargs}
        ),
    )
    published: list[str] = []
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda session_id: published.append(session_id))
    stub_ui = SimpleNamespace(
        stream_thought=lambda *args, **kwargs: None,
        clear_thought_stream=lambda *args, **kwargs: None,
        stream_response=lambda *args, **kwargs: None,
        clear_response_stream=lambda *args, **kwargs: None,
        set_pet_mental_state=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr("core.ui.get_ui", lambda: stub_ui)

    capture = session_service.SessionTurnCapture(session_id="session-live", turn_id="turn-llm")
    with session_service._capture_session_ui_stream("session-live", capture):
        session_service.get_event_bus().publish(
            session_service.EventNames.LLM_STATUS,
            {
                "status": "retrying",
                "attempt": 2,
                "max_attempts": 5,
                "category": "network_error",
            },
        )

    live_state = session_service._snapshot_session_live_output("session-live")
    assert live_state is not None
    assert live_state.stage == "model_retry"
    assert "模型连接正在重试" in live_state.content
    assert "2/5" in live_state.content
    assert published == ["session-live"]
    assert any(item["phase"] == "llm_status_retrying" for item in lifecycle_events)


def test_capture_session_ui_stream_surfaces_live_thought_as_model_thinking(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    lifecycle_events: list[dict] = []
    monkeypatch.setattr(
        session_service,
        "_record_session_turn_lifecycle_event",
        lambda session_id, phase, **kwargs: lifecycle_events.append(
            {"session_id": session_id, "phase": phase, **kwargs}
        ),
    )
    published: list[str] = []
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda session_id: published.append(session_id))
    stub_ui = SimpleNamespace(
        stream_thought=lambda *args, **kwargs: None,
        clear_thought_stream=lambda *args, **kwargs: None,
        stream_response=lambda *args, **kwargs: None,
        clear_response_stream=lambda *args, **kwargs: None,
        set_pet_mental_state=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr("core.ui.get_ui", lambda: stub_ui)

    capture = session_service.SessionTurnCapture(session_id="session-live-thought", turn_id="turn-thinking")
    with session_service._capture_session_ui_stream("session-live-thought", capture):
        stub_ui.stream_thought("先看最新日志，再判断是否真的卡住。", done=False)

    live_state = session_service._snapshot_session_live_output("session-live-thought")
    assert live_state is not None
    assert live_state.stage == "model_thinking"
    assert "正在思考" in live_state.content
    assert live_state.thought == "先看最新日志，再判断是否真的卡住。"
    assert capture.thought == "先看最新日志，再判断是否真的卡住。"
    assert published
    assert all(item == "session-live-thought" for item in published)
    assert any(item["phase"] == "ui_progress_model_thinking" for item in lifecycle_events)
    assert any(item["phase"] == "llm_status_reasoning" for item in lifecycle_events)


def test_capture_session_ui_stream_merges_incremental_thought_updates(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda _session_id: None)
    stub_ui = SimpleNamespace(
        stream_thought=lambda *args, **kwargs: None,
        clear_thought_stream=lambda *args, **kwargs: None,
        stream_response=lambda *args, **kwargs: None,
        clear_response_stream=lambda *args, **kwargs: None,
        set_pet_mental_state=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr("core.ui.get_ui", lambda: stub_ui)

    capture = session_service.SessionTurnCapture(session_id="session-live-thought", turn_id="turn-thinking")
    with session_service._capture_session_ui_stream("session-live-thought", capture):
        stub_ui.stream_thought("先看", done=False)
        stub_ui.stream_thought("日志", done=False)
        stub_ui.stream_thought("先看日志和代码", done=False)

    live_state = session_service._snapshot_session_live_output("session-live-thought")
    assert live_state is not None
    thought_events = [item for item in live_state.feedback_events if item["kind"] == "thought"]
    assert len(thought_events) == 1
    assert thought_events[0]["resultPreview"] == "先看日志和代码"
    assert capture.thought == "先看日志和代码"


def test_capture_session_ui_stream_preserves_ordered_feedback_events(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda _session_id: None)
    stub_ui = SimpleNamespace(
        stream_thought=lambda *args, **kwargs: None,
        clear_thought_stream=lambda *args, **kwargs: None,
        stream_response=lambda *args, **kwargs: None,
        clear_response_stream=lambda *args, **kwargs: None,
        set_pet_mental_state=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr("core.ui.get_ui", lambda: stub_ui)

    capture = session_service.SessionTurnCapture(session_id="session-feedback", turn_id="turn-feedback")
    with session_service._capture_session_ui_stream("session-feedback", capture):
        stub_ui.stream_thought("先读日志。", done=False)
        session_service.get_event_bus().publish(
            session_service.EventNames.TOOL_START,
            {"name": "read_log", "args": {"path": "logs/runtime_scenes/latest"}},
        )
        session_service.get_event_bus().publish(
            session_service.EventNames.TOOL_SUCCESS,
            {"name": "read_log", "result": "opened latest package", "durationMs": 12},
        )
        stub_ui.stream_thought("再检查前端链路。", done=False)
        session_service.get_event_bus().publish(
            session_service.EventNames.TOOL_START,
            {"name": "rg", "args": {"pattern": "feedbackEvents"}},
        )

    live_state = session_service._snapshot_session_live_output("session-feedback")
    assert live_state is not None
    kinds = [item["kind"] for item in live_state.feedback_events]
    assert kinds == ["thought", "status", "tool", "thought", "tool"]
    assert live_state.feedback_events[1]["name"] == "model_thinking"
    assert live_state.feedback_events[2]["name"] == "read_log"
    assert live_state.feedback_events[2]["status"] == "done"
    assert live_state.feedback_events[2]["relatedThoughtSequence"] == live_state.feedback_events[0]["sequence"]
    assert live_state.feedback_events[4]["relatedThoughtSequence"] == live_state.feedback_events[3]["sequence"]


def test_capture_session_ui_stream_filters_llm_status_by_event_context(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    published: list[str] = []
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda session_id: published.append(session_id))
    stub_ui = SimpleNamespace(
        stream_thought=lambda *args, **kwargs: None,
        clear_thought_stream=lambda *args, **kwargs: None,
        stream_response=lambda *args, **kwargs: None,
        clear_response_stream=lambda *args, **kwargs: None,
        set_pet_mental_state=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr("core.ui.get_ui", lambda: stub_ui)

    capture = session_service.SessionTurnCapture(session_id="session-live", turn_id="turn-llm")
    with session_service._capture_session_ui_stream("session-live", capture):
        session_service.get_event_bus().publish(
            session_service.EventNames.LLM_STATUS,
            {
                "status": "retrying",
                "session_id": "other-session",
                "turn_id": "turn-llm",
                "attempt": 1,
                "max_attempts": 5,
                "category": "network_error",
            },
        )
        session_service.get_event_bus().publish(
            session_service.EventNames.LLM_STATUS,
            {
                "status": "retrying",
                "session_id": "session-live",
                "turn_id": "turn-llm",
                "attempt": 2,
                "max_attempts": 5,
                "category": "network_error",
            },
        )

    live_state = session_service._snapshot_session_live_output("session-live")
    assert live_state is not None
    assert live_state.stage == "model_retry"
    assert "2/5" in live_state.content
    assert published == ["session-live"]


def test_turn_circuit_breaker_records_next_state_signal_with_turn_id(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        "core.web.services.runtime_scene_service.record_runtime_scene_event",
        lambda *args, **kwargs: {"accepted": True},
    )

    session_service._record_session_turn_circuit_breaker_event(
        "session-live",
        {
            "error": "litellm.BadGatewayError: BadGatewayError: OpenAIException - {\"error\":{\"message\":\"Upstream request failed\"}}",
            "llm_failure": {
                "category": "server_error",
                "retryable": True,
                "attempts": 5,
                "max_attempts": 5,
                "consecutive_failures": 5,
                "stop_reason": "retry budget exhausted",
            },
        },
        turn_id="turn-42",
        turn_index=2,
    )

    signals = _read_next_state_signals(tmp_path, session_id="session-live", turn_id="turn-42")
    assert any(item["kind"] == "provider_failure" for item in signals)
    assert any(item["relatedEventCode"] == "conversation.turn_circuit_breaker" for item in signals)
    assert any(item["metadata"]["continuationTurn"] == 2 for item in signals)


def test_submit_session_message_recovers_when_scheduler_fails(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    recorded_scene_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_scene_events.append((args, kwargs)) or {"accepted": True},
    )

    def fail_schedule(context):
        raise RuntimeError("scheduler unavailable")

    monkeypatch.setattr(session_service, "_schedule_session_turn", fail_schedule)

    with pytest.raises(RuntimeError, match="scheduler unavailable"):
        session_service.submit_session_message("session-live", "继续检查调度失败恢复")

    payload = session_service.get_session_detail("session-live")
    assert payload["currentPhase"] == "failed"
    assert payload["messages"][-2]["role"] == "user"
    assert payload["messages"][-2]["content"] == "继续检查调度失败恢复"
    assert payload["messages"][-1]["role"] == "assistant"
    assert "scheduler unavailable" in payload["messages"][-1]["content"]
    assert payload["lastTurnError"]["errorType"] == "RuntimeError"
    assert "scheduler unavailable" in payload["lastTurnError"]["message"]
    assert session_service._is_session_running("session-live") is False
    assert session_service._get_session_turn_control("session-live") is None
    assert session_service._WORK_RUN_STORE.load_active_snapshot("chat_turn") is None
    latest_run = session_service._WORK_RUN_STORE.load_latest_snapshot("chat_turn")
    assert latest_run["status"] == "failed"
    assert latest_run["errorType"] == "RuntimeError"
    assert latest_run["userMessage"] == "继续检查调度失败恢复"
    assert "scheduler unavailable" in latest_run["error"]
    event_codes = [args[2] for args, _kwargs in recorded_scene_events if len(args) >= 3]
    assert "conversation.turn.started" in event_codes
    assert "conversation.turn.scheduled" in event_codes
    assert "conversation.turn.failure_persisted" in event_codes


def test_submit_session_message_write_intent_rejects_self_evolution_lease(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)
    self_snapshot = {
        "runId": "web-self-active-for-chat",
        "runKind": "self_evolution_run",
        "status": "running",
        "leases": ["evolution_transaction", "worktree_write", "memory_write"],
        "startedAt": "2026-05-21T00:00:00",
        "updatedAt": "2026-05-21T00:00:00",
    }
    self_evolution_control_service.persist_manager_run_snapshot("self", self_snapshot, active_run_id=self_snapshot["runId"])

    readonly = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "解释当前状态"},
    )

    assert readonly.status_code == 202
    session_service._set_session_running("session-live", False)
    session_service._clear_session_turn_control("session-live")

    write_response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续修复这个 bug", "writeIntent": True},
    )

    assert write_response.status_code == 409
    assert "resource" in write_response.json()["detail"].lower() or "资源" in write_response.json()["detail"]


def test_request_stop_session_turn_persists_stop_snapshot_and_releases_session(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)

    try:
        submit_response = client.post(
            "/api/sessions/session-live/messages",
            json={"content": "先继续分析当前对话提交流程"},
        )

        assert submit_response.status_code == 202
        running_payload = submit_response.json()
        assert running_payload["currentPhase"] == "running"
        assert running_payload["stopRequested"] is False

        stop_response = client.post("/api/sessions/session-live/stop")

        assert stop_response.status_code == 202
        payload = stop_response.json()
        assert payload["currentPhase"] == "ready"
        assert payload["stopRequested"] is False
        assert payload["messages"][-1]["role"] == "assistant"
        assert "本轮已按请求停止" in payload["messages"][-1]["content"]
        stop_signals = _read_next_state_signals(tmp_path, session_id="session-live")
        assert any(item["kind"] == "user_stops" and item["turnId"] for item in stop_signals)

        continue_response = client.post(
            "/api/sessions/session-live/messages",
            json={"content": "继续"},
        )
        assert continue_response.status_code == 202
        assert continue_response.json()["currentPhase"] == "running"
        continue_signals = _read_next_state_signals(tmp_path, session_id="session-live")
        assert any(item["kind"] == "user_continues" for item in continue_signals)
    finally:
        session_service._set_session_running("session-live", False)
        session_service._clear_session_turn_control("session-live")


def test_submit_session_safe_guidance_records_signal_without_stopping(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)

    try:
        submit_response = client.post(
            "/api/sessions/session-live/messages",
            json={"content": "先继续分析当前对话提交流程"},
        )
        assert submit_response.status_code == 202

        guidance_response = client.post(
            "/api/sessions/session-live/guidance",
            json={"mode": "safe", "content": "这一轮先不要改代码，只汇报安全引导链路。"},
        )

        assert guidance_response.status_code == 202
        payload = guidance_response.json()
        assert payload["currentPhase"] == "running"
        assert payload["stopRequested"] is False
        signals = _read_next_state_signals(tmp_path, session_id="session-live")
        assert any(
            item["kind"] == "user_guidance"
            and item["summary"] == "这一轮先不要改代码，只汇报安全引导链路。"
            and item["turnId"]
            for item in signals
        )
    finally:
        session_service._set_session_running("session-live", False)
        session_service._clear_session_turn_control("session-live")


def test_submit_session_interrupt_guidance_records_signal_and_stops(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)

    try:
        submit_response = client.post(
            "/api/sessions/session-live/messages",
            json={"content": "先继续分析当前对话提交流程"},
        )
        assert submit_response.status_code == 202

        guidance_response = client.post(
            "/api/sessions/session-live/guidance",
            json={"mode": "interrupt", "content": "停止当前思路，改为先审计数据流。"},
        )

        assert guidance_response.status_code == 202
        payload = guidance_response.json()
        assert payload["currentPhase"] == "ready"
        assert payload["stopRequested"] is False
        assert "本轮已按请求停止" in payload["messages"][-1]["content"]
        signals = _read_next_state_signals(tmp_path, session_id="session-live")
        assert any(
            item["kind"] == "user_interrupt_guidance"
            and item["summary"] == "停止当前思路，改为先审计数据流。"
            and item["turnId"]
            for item in signals
        )
        assert any(item["kind"] == "user_stops" for item in signals)
    finally:
        session_service._set_session_running("session-live", False)
        session_service._clear_session_turn_control("session-live")


def test_request_stop_session_turn_reuses_active_work_run_when_controller_is_missing(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    scene_events = []

    def record_scene_event(component, phase, event_code, **kwargs):
        scene_events.append((component, phase, event_code, kwargs))
        return {"accepted": True}

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "record_runtime_scene_event", record_scene_event)
    monkeypatch.setattr(
        session_service,
        "_WORK_RUN_STORE",
        session_service.WorkRunStore(tmp_path / ".runtime" / "runtime-manager" / "work_runs"),
    )
    session_service._set_session_running("session-live", True)
    session_service._clear_session_turn_control("session-live")
    session_service._WORK_RUN_STORE.persist_snapshot(
        "chat_turn",
        {
            "runId": "existing-chat-turn",
            "runKind": "chat_turn",
            "track": "dialogue",
            "sessionId": "session-live",
            "status": "running",
            "currentPhase": "running",
            "leases": ["readonly_chat"],
            "userMessage": "上一轮控制器丢失但 WorkRun 仍活跃",
            "startedAt": "2026-05-18T11:59:00",
            "updatedAt": "2026-05-18T12:00:00",
            "finishedAt": "",
        },
        active_run_id="existing-chat-turn",
    )

    try:
        stop_response = client.post("/api/sessions/session-live/stop")

        assert stop_response.status_code == 202
        payload = stop_response.json()
        assert payload["currentPhase"] == "ready"
        assert payload["stopRequested"] is False
        assert "本轮已按请求停止" in payload["messages"][-1]["content"]
        assert session_service._WORK_RUN_STORE.load_active_snapshot("chat_turn") is None
        latest_run = session_service._WORK_RUN_STORE.load_latest_snapshot("chat_turn")
        assert latest_run["runId"] == "existing-chat-turn"
        assert latest_run["status"] == "stopped"
        assert latest_run["finishedAt"]
        assert any(
            event[2] == "conversation.turn_control_recovered"
            and event[3]["fields"]["turnId"] == "existing-chat-turn"
            and event[3]["fields"]["reusedActiveRun"] is True
            for event in scene_events
        )
    finally:
        session_service._set_session_running("session-live", False)
        session_service._clear_session_turn_control("session-live")
        session_service._clear_session_live_output("session-live")


@pytest.mark.slow
def test_stop_requested_turn_persists_visible_stop_message(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    started = threading.Event()
    finished = threading.Event()
    worker_threads = []

    class StoppableAgent:
        def __init__(self):
            self.stop_checker = None

        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def set_turn_interrupt_checker(self, checker):
            self.stop_checker = checker

        def run_single_turn(self, initial_prompt=None):
            started.set()
            for _ in range(200):
                reason = self.stop_checker() if callable(self.stop_checker) else ""
                if reason:
                    return {
                        "status": "stopped",
                        "summary": "",
                        "raw_output": "",
                        "stop_requested": True,
                        "stop_reason": reason,
                        "tool_call_count": 0,
                        "tool_trace": [],
                    }
                time.sleep(0.01)
            return {
                "status": "completed",
                "summary": "不该走到这里。",
                "raw_output": "不该走到这里。",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: StoppableAgent())

    def run_async(context):
        def _worker():
            try:
                session_service._run_session_turn(context)
            finally:
                finished.set()

        thread = threading.Thread(target=_worker, daemon=True)
        worker_threads.append(thread)
        thread.start()

    monkeypatch.setattr(session_service, "_schedule_session_turn", run_async)

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续推进当前网页会话的终止能力"},
    )

    assert response.status_code == 202
    assert started.wait(1.0), "expected the background turn to start"

    stop_response = client.post("/api/sessions/session-live/stop")

    assert stop_response.status_code == 202
    assert stop_response.json()["currentPhase"] == "ready"
    assert finished.wait(2.0), "expected the stopped turn to finish"

    for thread in worker_threads:
        thread.join(timeout=0.2)

    detail_response = client.get("/api/sessions/session-live")
    assert detail_response.status_code == 200
    payload = detail_response.json()
    assert payload["currentPhase"] == "ready"
    assert payload["stopRequested"] is False
    assert payload["messages"][-1]["role"] == "assistant"
    assert "本轮已按请求停止" in payload["messages"][-1]["content"]


def test_stop_session_turn_persists_partial_snapshot_and_allows_immediate_continue(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        active_task={
            "task_id": "chat-stop-resume",
            "kind": "coding",
            "status": "reading",
            "title": "修复 Web Chat 停止恢复",
            "goal": "修复 Web Chat 停止恢复",
            "read_files": ["tests/prompt_debugger.py"],
            "latest_summary": "已定位停止按钮问题。",
            "updated_at": "2026-05-20T16:24:53",
            "metadata": {"source": "task_tool"},
        },
    )
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "prompt_debugger.py").write_text("pass\n", encoding="utf-8")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)

    submit_response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续修复停止恢复"},
    )
    assert submit_response.status_code == 202
    old_control = session_service._get_session_turn_control("session-live")
    assert old_control is not None

    session_service._set_session_live_output(
        "session-live",
        thought="我已经定位到 stop checker。",
        content="已完成一部分：停止请求进入后会设置 stop flag。",
        tool_calls=[{"name": "read_file_tool", "status": "done", "summary": "session_service.py"}],
    )

    stop_response = client.post("/api/sessions/session-live/stop")
    assert stop_response.status_code == 202
    stopped_payload = stop_response.json()
    assert stopped_payload["currentPhase"] == "ready"
    assert stopped_payload["stopRequested"] is False
    assert "已完成一部分" in stopped_payload["messages"][-1]["content"]
    assert "本轮已按请求停止" in stopped_payload["messages"][-1]["content"]
    assert stopped_payload["messages"][-1]["thought"] == "我已经定位到 stop checker。"
    assert stopped_payload["messages"][-1]["toolCalls"][0]["name"] == "read_file_tool"

    continue_response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续"},
    )
    assert continue_response.status_code == 202
    new_control = session_service._get_session_turn_control("session-live")
    assert new_control is not None
    assert new_control.turn_id != old_control.turn_id

    session_service._clear_session_turn_control("session-live", turn_id=old_control.turn_id)
    assert session_service._get_session_turn_control("session-live").turn_id == new_control.turn_id

    session_service._set_session_running("session-live", False, turn_id=old_control.turn_id)
    assert session_service._is_session_running("session-live") is True

    session_service._set_session_running("session-live", False, turn_id=new_control.turn_id)
    session_service._clear_session_turn_control("session-live", turn_id=new_control.turn_id)


def test_stop_session_turn_keeps_old_control_cancel_token_until_worker_observes_it(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)

    submit_response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "第一轮会被停止"},
    )
    assert submit_response.status_code == 202
    old_control = session_service._get_session_turn_control("session-live")
    assert old_control is not None
    old_turn_id = old_control.turn_id

    stop_response = client.post("/api/sessions/session-live/stop")
    assert stop_response.status_code == 202
    assert old_control.snapshot()["stopRequested"] is True
    assert "操作者请求停止当前轮" in old_control.snapshot()["stopReason"]

    continue_response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续新一轮"},
    )
    assert continue_response.status_code == 202
    new_control = session_service._get_session_turn_control("session-live")
    assert new_control is not None
    assert new_control.turn_id != old_turn_id
    assert old_control.snapshot()["stopRequested"] is True

    session_service._clear_session_turn_control("session-live", turn_id=old_turn_id)
    assert session_service._get_session_turn_control("session-live").turn_id == new_control.turn_id

    session_service._set_session_running("session-live", False, turn_id=new_control.turn_id)
    session_service._clear_session_turn_control("session-live", turn_id=new_control.turn_id)


def test_stale_stopped_turn_does_not_run_after_immediate_continue(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    scheduled_contexts = []
    stale_agent_called = False

    class StaleAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def set_turn_interrupt_checker(self, checker):
            self.stop_checker = checker

        def run_single_turn(self, initial_prompt=None):
            nonlocal stale_agent_called
            stale_agent_called = True
            return {
                "status": "completed",
                "summary": "旧轮结果不应该写入当前会话。",
                "raw_output": "旧轮结果不应该写入当前会话。",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: scheduled_contexts.append(dict(context)))
    monkeypatch.setattr(session_service, "create_chat_agent", lambda: StaleAgent())

    try:
        first_response = client.post(
            "/api/sessions/session-live/messages",
            json={"content": "第一轮需要停止"},
        )
        assert first_response.status_code == 202
        assert len(scheduled_contexts) == 1

        stop_response = client.post("/api/sessions/session-live/stop")
        assert stop_response.status_code == 202

        continue_response = client.post(
            "/api/sessions/session-live/messages",
            json={"content": "第二轮已经开始"},
        )
        assert continue_response.status_code == 202
        assert continue_response.json()["currentPhase"] == "running"
        assert len(scheduled_contexts) == 2

        session_service._run_session_turn(scheduled_contexts[0])

        detail_response = client.get("/api/sessions/session-live")
        assert detail_response.status_code == 200
        payload = detail_response.json()
        assert stale_agent_called is False
        assert payload["currentPhase"] == "running"
        assert payload["messages"][-2]["role"] == "user"
        assert payload["messages"][-2]["content"] == "第二轮已经开始"
        assert payload["messages"][-1]["role"] == "assistant"
        assert payload["messages"][-1]["streaming"] is True
        assert payload["messages"][-1]["content"] == CONTEXT_PREPARE_LIVE_MESSAGE
    finally:
        session_service._set_session_running("session-live", False)
        session_service._clear_session_turn_control("session-live")
        session_service._clear_session_live_output("session-live")


def test_stop_during_agent_call_does_not_record_late_completed_result(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    lifecycle_events = []

    def record_lifecycle_event(session_id, phase, **kwargs):
        lifecycle_events.append(
            {
                "session_id": session_id,
                "phase": phase,
                "turn_id": kwargs.get("turn_id", ""),
                "outcome": kwargs.get("outcome", ""),
                "fields": dict(kwargs.get("fields") or {}),
            }
        )

    class LateCompletedAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def set_turn_interrupt_checker(self, checker):
            self.stop_checker = checker

        def run_single_turn(self, initial_prompt=None):
            control = session_service._get_session_turn_control("session-live")
            assert control is not None
            control.request_stop("操作者请求停止当前轮。")
            return {
                "status": "completed",
                "summary": "停止后的迟到完成结果不应该落盘。",
                "raw_output": "停止后的迟到完成结果不应该落盘。",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(
        session_service,
        "_record_session_turn_lifecycle_event",
        record_lifecycle_event,
    )
    monkeypatch.setattr(session_service, "create_chat_agent", lambda: LateCompletedAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    try:
        response = client.post(
            "/api/sessions/session-live/messages",
            json={"content": "这轮会在模型调用期间被停止"},
        )

        assert response.status_code == 202
        latest_run = session_service._WORK_RUN_STORE.load_latest_snapshot("chat_turn")
        detail_response = client.get("/api/sessions/session-live")
        assert detail_response.status_code == 200
        payload = detail_response.json()
        assert latest_run["status"] == "stopped_by_user"
        assert payload["currentPhase"] == "ready"
        assert "本轮已按请求停止" in payload["messages"][-1]["content"]
        assert "迟到完成结果" not in payload["messages"][-1]["content"]
        assert not any(
            event["phase"] in {"agent_turn_returned", "terminal_result"} and event["outcome"] == "completed"
            for event in lifecycle_events
        )
        assert any(
            event["phase"] == "stop_observed"
            and event["outcome"] == "stopped"
            and event["fields"].get("stage") == "agent_return"
            for event in lifecycle_events
        )
    finally:
        session_service._set_session_running("session-live", False)
        session_service._clear_session_turn_control("session-live")
        session_service._clear_session_live_output("session-live")


def test_stale_turn_live_output_does_not_overwrite_new_turn(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)

    try:
        first_response = client.post(
            "/api/sessions/session-live/messages",
            json={"content": "第一轮需要停止"},
        )
        assert first_response.status_code == 202
        old_control = session_service._get_session_turn_control("session-live")
        assert old_control is not None

        stop_response = client.post("/api/sessions/session-live/stop")
        assert stop_response.status_code == 202

        continue_response = client.post(
            "/api/sessions/session-live/messages",
            json={"content": "第二轮已经开始"},
        )
        assert continue_response.status_code == 202
        new_control = session_service._get_session_turn_control("session-live")
        assert new_control is not None

        session_service._set_session_live_output(
            "session-live",
            turn_id=new_control.turn_id,
            content="新轮正在输出。",
        )
        session_service._set_session_live_output(
            "session-live",
            turn_id=old_control.turn_id,
            content="旧轮迟到输出，不应该可见。",
        )

        detail_response = client.get("/api/sessions/session-live")
        assert detail_response.status_code == 200
        payload = detail_response.json()
        assert payload["messages"][-1]["streaming"] is True
        assert payload["messages"][-1]["content"] == "新轮正在输出。"
    finally:
        session_service._set_session_running("session-live", False)
        session_service._clear_session_turn_control("session-live")
        session_service._clear_session_live_output("session-live")


def test_stale_turn_live_output_clear_does_not_remove_new_turn(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    session_service._set_session_live_output(
        "session-live",
        turn_id="turn-new",
        content="新轮正在输出。",
    )

    session_service._clear_session_live_output("session-live", turn_id="turn-old")
    response = client.get("/api/sessions/session-live")
    assert response.status_code == 200
    payload = response.json()
    assert payload["messages"][-1]["streaming"] is True
    assert payload["messages"][-1]["content"] == "新轮正在输出。"

    session_service._clear_session_live_output("session-live", turn_id="turn-new")
    response_after_clear = client.get("/api/sessions/session-live")
    assert response_after_clear.status_code == 200
    assert not response_after_clear.json()["messages"][-1].get("streaming")


def test_session_detail_includes_live_thought_draft(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    session_service._set_session_running("session-live", True)
    session_service._set_session_live_output(
        "session-live",
        thought="先把这轮的思考过程挂进消息卡片。",
        feedback_events=[
            {
                "sequence": 1,
                "kind": "thought",
                "status": "running",
                "summary": "先把这轮的思考过程挂进消息卡片。",
                "resultPreview": "先把这轮的思考过程挂进消息卡片。",
            }
        ],
        mental_snapshot={
            "mood": "专注",
            "feeling": "链路已经接近打通。",
            "whisper": "再把默认折叠状态接上。",
            "cognitiveState": "productive",
        },
    )
    try:
        response = client.get("/api/sessions/session-live")
    finally:
        session_service._clear_session_live_output("session-live")
        session_service._set_session_running("session-live", False)

    assert response.status_code == 200
    payload = response.json()
    assert payload["messages"][-1]["streaming"] is True
    assert payload["messages"][-1]["thought"] == "先把这轮的思考过程挂进消息卡片。"
    assert payload["messages"][-1]["feedbackEvents"][0]["kind"] == "thought"
    assert payload["messages"][-1]["mentalSnapshot"]["mood"] == "专注"


def test_session_detail_hides_partial_state_live_answer(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    session_service._set_session_running("session-live", True)
    session_service._set_session_live_output(
        "session-live",
        content="<state",
        tool_calls=[{"name": "read_file_tool", "status": "running"}],
    )
    try:
        response = client.get("/api/sessions/session-live")
    finally:
        session_service._clear_session_live_output("session-live")
        session_service._set_session_running("session-live", False)

    assert response.status_code == 200
    payload = response.json()
    assert payload["messages"][-1]["streaming"] is True
    assert payload["messages"][-1]["content"] == ""
    assert payload["messages"][-1]["toolCalls"] == [
        {"name": "read_file_tool", "status": "running"}
    ]


def test_session_detail_hides_dsml_and_lone_angle_live_answer(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    session_service._set_session_running("session-live", True)
    session_service._set_session_live_output(
        "session-live",
        content="<state>\n{}\n</｜｜DSML｜｜parameter>\n</invoke>\n</｜｜DSML｜｜tool_calls>\n<",
        thought="</invoke>\n<",
        tool_calls=[{"name": "spawn_agent_tool", "status": "running"}],
    )
    try:
        response = client.get("/api/sessions/session-live")
    finally:
        session_service._clear_session_live_output("session-live")
        session_service._set_session_running("session-live", False)

    assert response.status_code == 200
    payload = response.json()
    assert payload["messages"][-1]["streaming"] is True
    assert payload["messages"][-1]["content"] == ""
    assert "thought" not in payload["messages"][-1]
    assert payload["messages"][-1]["toolCalls"] == [
        {"name": "spawn_agent_tool", "status": "running"}
    ]


def test_session_detail_hides_parameter_live_answer(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    session_service._set_session_running("session-live", True)
    session_service._set_session_live_output(
        "session-live",
        content="连续被拦截。让我尝试拆分写入。\n</parameter>",
        thought="</parameter>\n<parameter",
        tool_calls=[{"name": "cli_tool", "status": "running"}],
    )
    try:
        response = client.get("/api/sessions/session-live")
    finally:
        session_service._clear_session_live_output("session-live")
        session_service._set_session_running("session-live", False)

    assert response.status_code == 200
    payload = response.json()
    assert payload["messages"][-1]["streaming"] is True
    assert payload["messages"][-1]["content"] == "连续被拦截。让我尝试拆分写入。"
    assert "thought" not in payload["messages"][-1]
    assert payload["messages"][-1]["toolCalls"] == [
        {"name": "cli_tool", "status": "running"}
    ]


def test_session_detail_sanitizes_persisted_protocol_messages_and_active_task(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "prompt_debugger.py").write_text("pass\n", encoding="utf-8")
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        active_task={
            "task_id": "polluted-protocol",
            "kind": "coding",
            "status": "reading",
            "title": "<invoke name=\"read_file_tool\"><parameter name=\"file_path\">secret.py</parameter></invoke>",
            "goal": "<state",
            "read_files": ["tests/prompt_debugger.py"],
            "latest_summary": "继续检查。\n</parameter>",
            "next_action": "<parameter name=\"file_path\">secret.py</parameter>",
            "updated_at": "2026-05-20T17:54:06",
            "metadata": {"source": "task_tool"},
        },
    )
    state = load_chat_state(tmp_path)
    state["conversations"][0]["messages"].append(
        {
            "role": "assistant",
            "content": (
                "继续检查。\n"
                '<invoke name="read_file_tool">'
                '<parameter name="file_path">tests/prompt_debugger.py</parameter>'
                "</invoke>\n"
                "<state"
            ),
            "thought": "</parameter>\n<parameter",
            "timestamp": "2026-05-20T17:55:00",
            "tool_calls": [{"name": "read_file_tool"}],
        }
    )
    save_chat_state(tmp_path, state)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200, response.json()
    payload = response.json()
    normalized_task = session_service._normalize_session_active_task(
        load_chat_state(tmp_path)["conversations"][0]["active_task"]
    )
    assistant = payload["messages"][-1]
    assert assistant["content"] == "继续检查。"
    assert "thought" not in assistant
    assert payload["taskSummary"] == "继续检查。"
    assert payload["activeTask"]["latestSummary"] == "继续检查。"
    assert payload["activeTask"]["title"] == ""
    assert payload["activeTask"]["goal"] == ""
    assert payload["activeTask"]["nextAction"] == ""
    assert normalized_task["latest_summary"] == "继续检查。"
    assert normalized_task["title"] == ""
    assert normalized_task["goal"] == ""
    assert normalized_task["next_action"] == ""
    assert "<invoke" not in json.dumps(payload, ensure_ascii=False)
    assert "<parameter" not in json.dumps(payload, ensure_ascii=False)
    assert "<state" not in json.dumps(payload, ensure_ascii=False)


def test_session_detail_promotes_legacy_runtime_notice_outside_messages(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="idle")
    state = load_chat_state(tmp_path)
    state["conversations"][0]["messages"].extend(
        [
            {
                "role": "assistant",
                "content": "上一轮运行已被中断，当前会话已恢复为可继续状态。",
                "timestamp": "2026-05-29T18:16:31",
            },
            {
                "role": "assistant",
                "content": "继续分析日志。",
                "timestamp": "2026-05-29T18:16:32",
            },
        ]
    )
    save_chat_state(tmp_path, state)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert [message["content"] for message in payload["messages"]][-1:] == ["继续分析日志。"]
    assert all("已被中断" not in message["content"] for message in payload["messages"])
    assert payload["runtimeNotices"] == []


def test_session_detail_filters_legacy_queued_stop_notice_from_messages(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="idle")
    state = load_chat_state(tmp_path)
    state["conversations"][0]["messages"].extend(
        [
            {
                "role": "user",
                "content": "按照这个提示词来生成图片",
                "timestamp": "2026-05-29T21:36:11",
            },
            {
                "role": "assistant",
                "content": "当前 Agent 正在处理上一项任务，本轮已进入队列...\n会在前一轮释放会话锁后继续执行。\n\n本轮已按请求停止。可发送“继续”恢复这次未完成的任务。",
                "timestamp": "2026-05-29T21:36:20",
            },
        ]
    )
    save_chat_state(tmp_path, state)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "_ensure_agent_default_avatar", lambda agent: None, raising=False)

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["messages"][-1]["role"] == "user"
    assert all("本轮已进入队列" not in message["content"] for message in payload["messages"])
    assert len(payload["runtimeNotices"]) == 1
    assert payload["runtimeNotices"][0]["kind"] == "runtime_notice"
    assert "本轮已进入队列" in payload["runtimeNotices"][0]["message"]


def test_session_detail_shows_current_runtime_notice_until_real_message_arrives(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="idle")
    state = load_chat_state(tmp_path)
    state["conversations"][0]["runtime_notices"] = [
        {
            "kind": "turn_recovered",
            "level": "warning",
            "message": "上一轮运行已被中断，当前会话已恢复为可继续状态。",
            "timestamp": "2026-05-29T18:16:31",
            "source": "conversation.turn_recovered",
        },
        {
            "kind": "turn_recovered",
            "level": "warning",
            "message": "上一轮运行已被中断，当前会话已恢复为可继续状态。",
            "timestamp": "2026-05-29T18:16:32",
            "source": "legacy_assistant_message",
        },
    ]
    save_chat_state(tmp_path, state)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    fresh_notice = client.get("/api/sessions/session-live").json()
    assert len(fresh_notice["runtimeNotices"]) == 1
    assert fresh_notice["runtimeNotices"][0]["source"] == "conversation.turn_recovered"

    state = load_chat_state(tmp_path)
    state["conversations"][0]["messages"].append(
        {
            "role": "assistant",
            "content": "已恢复并继续完成任务。",
            "timestamp": "2026-05-29T18:16:33",
        }
    )
    save_chat_state(tmp_path, state)

    settled = client.get("/api/sessions/session-live").json()
    assert settled["runtimeNotices"] == []


def test_submit_session_message_persists_lease_conflict_notice_without_llm_call(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="idle")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    events: list[dict[str, object]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: events.append({"args": args, "kwargs": kwargs}) or {"accepted": True},
    )
    monkeypatch.setattr(
        session_service,
        "load_evolution_active_run_snapshot",
        lambda kind: {
            "runId": "web-supervised-busy",
            "runKind": "supervised_worktree_evolution_run",
            "status": "running",
            "leases": ["evaluation", "worktree_write"],
        } if kind == "supervised" else None,
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "修复这个前端显示问题"},
    )

    assert response.status_code == 409
    assert "worktree_write" in response.json()["detail"]
    detail = client.get("/api/sessions/session-live").json()
    assert detail["messages"][-1]["content"] != "修复这个前端显示问题"
    assert detail["runtimeNotices"][-1]["kind"] == "turn_rejected"
    assert "HTTP 409" in detail["runtimeNotices"][-1]["message"]
    assert "web-supervised-busy" in detail["runtimeNotices"][-1]["message"]
    assert detail["llmUsage"]["source"] == "not_called"
    assert detail["cacheUsage"]["source"] == "not_called"
    assert detail["lastCacheComposition"]["source"] == "not_called"
    assert detail["lastTurnError"]["httpStatus"] == 409
    assert any(
        event["args"][:3] == ("conversation", "turn_rejected", "conversation.turn.rejected_before_llm")
        and event["kwargs"]["fields"]["llmCalled"] is False
        and event["kwargs"]["fields"]["conflictRunId"] == "web-supervised-busy"
        for event in events
    )


def test_session_detail_recovers_stale_running_state(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    state = load_chat_state(tmp_path)
    state["conversations"][0]["last_turn_status"] = "running"
    save_chat_state(tmp_path, state)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    session_service._WORK_RUN_STORE.persist_snapshot(
        "chat_turn",
        {
            "runId": "stale-turn-1",
            "runKind": "chat_turn",
            "track": "dialogue",
            "sessionId": "session-live",
            "status": "running",
            "currentPhase": "running",
            "leases": ["readonly_chat"],
            "userMessage": "继续前端开发",
            "startedAt": "2026-05-18T11:59:00",
            "updatedAt": "2026-05-18T12:00:00",
            "finishedAt": "",
        },
        active_run_id="stale-turn-1",
    )
    session_service._set_session_running("session-live", False)

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200
    payload = response.json()
    assert payload["currentPhase"] == "ready"
    assert all("已被中断" not in message["content"] for message in payload["messages"])
    assert payload["runtimeNotices"][-1]["kind"] == "turn_recovered"
    assert payload["runtimeNotices"][-1]["source"] == "conversation.turn_recovered"
    assert "已被中断" in payload["runtimeNotices"][-1]["message"]
    persisted = load_chat_state(tmp_path)
    assert persisted["conversations"][0]["last_turn_status"] == "ready"
    assert all("已被中断" not in message["content"] for message in persisted["conversations"][0]["messages"])
    assert persisted["conversations"][0]["runtime_notices"][-1]["kind"] == "turn_recovered"
    assert session_service._WORK_RUN_STORE.load_active_snapshot("chat_turn") is None
    latest_run = session_service._WORK_RUN_STORE.load_latest_snapshot("chat_turn")
    assert latest_run["runId"] == "stale-turn-1"
    assert latest_run["status"] == "stopped"
    assert latest_run["finishedAt"]


def test_submit_session_message_allows_follow_up_when_previous_turn_finished(tmp_path, monkeypatch):
    (tmp_path / "web" / "src" / "routes").mkdir(parents=True, exist_ok=True)
    (tmp_path / "web" / "src" / "routes" / "ChatCodingRoute.tsx").write_text("export {};\n", encoding="utf-8")
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=2),
    )

    class DummyAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "继续推进并给出下一步建议。",
                "raw_output": "继续推进并给出下一步建议。",
                "outcome": "done",
                "read_files": ["web/src/routes/ChatCodingRoute.tsx"],
                "tool_call_count": 1,
                "tool_trace": [
                    {"name": "read_file_tool"},
                ],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续修复 web/src/routes/ChatCodingRoute.tsx"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["messages"][-1]["role"] == "assistant"
    assert payload["messages"][-1]["content"] == "继续推进并给出下一步建议。"
    assert payload["currentPhase"] == "ready"
    assert payload["activeTask"] is None


def test_submit_session_message_keeps_streamed_reply_when_final_result_is_control_marker(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=1),
    )

    class ControlMarkerAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            from core.ui import get_ui

            get_ui().stream_response("项目审查完成：核心问题集中在会话持久化和前端状态冗余。", done=False)
            get_ui().stream_response("[outcome=done]", done=True)
            return {
                "status": "completed",
                "summary": "[outcome=done]",
                "raw_output": "[outcome=done]",
                "outcome": "done",
                "read_files": ["README.md"],
                "tool_call_count": 1,
                "tool_trace": [{"name": "read_file_tool", "args": {"file_path": "README.md"}}],
            }

    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ControlMarkerAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "审查整个项目并汇报"},
    )

    assert response.status_code == 202, response.json()
    payload = response.json()
    assistant = payload["messages"][-1]
    assert assistant["content"] == "项目审查完成：核心问题集中在会话持久化和前端状态冗余。"
    assert "[outcome=done]" not in json.dumps(payload, ensure_ascii=False)
    assert payload["activeTask"] is None


def test_submit_session_message_keeps_fallback_streamed_reply_when_final_result_is_control_marker(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=1),
    )

    class FallbackReplyAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            from core.ui import get_ui

            get_ui().stream_response("非流式回答已返回：这是最终可见正文。", done=True)
            return {
                "status": "completed",
                "summary": "[outcome=done]",
                "raw_output": "[outcome=done]",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: FallbackReplyAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续并给出最终回答"},
    )

    assert response.status_code == 202, response.json()
    payload = response.json()
    assistant = payload["messages"][-1]
    assert assistant["content"] == "非流式回答已返回：这是最终可见正文。"
    assert payload["activeTask"] is None


def test_submit_session_message_marks_completed_file_artifact_task_done(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    output_path = tmp_path / "workspace" / "agents" / "agent-a" / "outputs" / "presentation_structure.html"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("<html>slides</html>\n", encoding="utf-8")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    recorded_scene_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_scene_events.append((args, kwargs)) or {"accepted": True},
    )
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=1),
    )

    class ArtifactDoneAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "文件已成功创建：workspace/agents/agent-a/outputs/presentation_structure.html\n任务完成：10页HTML演示文稿已生成。",
                "raw_output": "文件已成功创建：workspace/agents/agent-a/outputs/presentation_structure.html\n任务完成：10页HTML演示文稿已生成。",
                "outcome": "done",
                "tool_call_count": 2,
                "tool_trace": [
                    {
                        "name": "write_file_tool",
                        "args": {"file_path": "workspace/agents/agent-a/outputs/presentation_structure.html"},
                        "result_preview": "[创建文件] [OK] 成功",
                    },
                    {"name": "task_complete_tool", "args": {"status": "done"}},
                ],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ArtifactDoneAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "给我一个10页的ppt,html也可以"},
    )

    assert response.status_code == 202, response.json()
    payload = response.json()
    assert payload["currentPhase"] == "ready"
    assert payload["activeTask"]["status"] == "done"
    assert payload["activeTask"]["changedFiles"] == ["workspace/agents/agent-a/outputs/presentation_structure.html"]
    assert payload["activeTask"]["nextAction"] == ""
    assert payload["messages"][-1]["content"].startswith("文件已成功创建")
    persisted_events = [
        kwargs
        for args, kwargs in recorded_scene_events
        if len(args) >= 3 and args[2] == "conversation.turn.result_persisted"
    ]
    assert persisted_events
    assert persisted_events[-1]["fields"]["activeTaskStatus"] == "done"
    assert persisted_events[-1]["fields"]["activeTaskOutcome"] == "done"
    assert persisted_events[-1]["fields"]["activeTaskChangedFileCount"] == 1


def test_submit_session_message_continues_progress_until_done(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "prompt_debugger.py").write_text("pass\n", encoding="utf-8")
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=2),
    )
    calls = []

    class ContinuingAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            calls.append(initial_prompt)
            if len(calls) == 1:
                return {
                    "status": "completed",
                    "summary": "<state>",
                    "raw_output": "<state>",
                    "outcome": "progress",
                    "next_action": "继续读取测试工具结构并形成规划。",
                    "read_files": ["tests/prompt_debugger.py"],
                    "tool_call_count": 1,
                    "tool_trace": [
                        {"name": "read_file_tool", "args": {"file_path": "tests/prompt_debugger.py"}},
                    ],
                }
            return {
                "status": "completed",
                "summary": "规划完成：先复用 prompt_debugger，再包装 BDD 调试入口。",
                "raw_output": "规划完成：先复用 prompt_debugger，再包装 BDD 调试入口。",
                "outcome": "done",
                "read_files": ["tests/prompt_debugger.py"],
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ContinuingAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "做一个测试工具吧,能够更快速的进行BDD调试,先规划一下,然后向我汇报"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert len(calls) == 2
    assert "继续完成同一个用户目标" in calls[1]
    assert payload["messages"][-1]["content"] == "规划完成：先复用 prompt_debugger，再包装 BDD 调试入口。"
    assert payload["currentPhase"] == "ready"


def test_submit_session_message_continues_after_bookkeeping_progress(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=2),
    )
    calls = []

    class BookkeepingProgressAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            calls.append(initial_prompt)
            if len(calls) == 1:
                return {
                    "status": "partial",
                    "summary": "",
                    "raw_output": "",
                    "outcome": "progress",
                    "recommended_next_action": "继续读取证据或直接给出结论。",
                    "tool_call_count": 3,
                    "tool_trace": [
                        {"name": "get_git_status_summary_tool"},
                        {"name": "task_create_tool"},
                        {"name": "task_update_tool"},
                    ],
                }
            return {
                "status": "completed",
                "summary": "已找到优化点：任务管理工具不应算作有效证据推进。",
                "raw_output": "已找到优化点：任务管理工具不应算作有效证据推进。",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: BookkeepingProgressAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "寻找可以优化的地方并汇报"},
    )

    assert response.status_code == 202, response.json()
    payload = response.json()
    assert len(calls) == 2
    assert "继续完成同一个用户目标" in calls[1]
    assert "继续读取证据或直接给出结论" in calls[1]
    assert payload["messages"][-1]["content"] == "已找到优化点：任务管理工具不应算作有效证据推进。"
    assert payload["currentPhase"] == "ready"


def test_submit_session_message_keeps_tools_available_after_tool_progress(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=3),
    )
    calls = []

    class ToolProgressAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None, disable_tools=False):
            calls.append({"prompt": initial_prompt, "disable_tools": disable_tools})
            if len(calls) == 1:
                return {
                    "status": "partial",
                    "summary": "已读取 core/web/services/runtime_scene_service.py，下一步继续校准 runtime scene 摘要。",
                    "raw_output": "已读取 core/web/services/runtime_scene_service.py，下一步继续校准 runtime scene 摘要。",
                    "outcome": "progress",
                    "recommended_next_action": "基于已读证据给出可见结论。",
                    "tool_call_count": 3,
                    "tool_trace": [
                        {"name": "code_symbol_tool"},
                        {"name": "read_file_tool"},
                        {"name": "grep_search_tool"},
                    ],
                }
            assert disable_tools is False
            assert "工具循环保护" not in str(initial_prompt)
            return {
                "status": "completed",
                "summary": "已修正工具路径并收束：runtime scene 摘要需要基于返回内容继续推进。",
                "raw_output": "已修正工具路径并收束：runtime scene 摘要需要基于返回内容继续推进。",
                "outcome": "done",
                "tool_call_count": 1,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ToolProgressAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "好的开始修改"},
    )

    assert response.status_code == 202, response.json()
    payload = response.json()
    assert len(calls) == 2
    assert calls[0]["disable_tools"] is False
    assert calls[1]["disable_tools"] is False
    assert "继续完成同一个用户目标" in calls[1]["prompt"]
    assert "基于已读证据给出可见结论" in calls[1]["prompt"]
    assert "工具结果是否真正服务于用户目标" not in calls[1]["prompt"]
    assert "禁用工具" not in calls[1]["prompt"]
    assert "工具循环保护" not in calls[1]["prompt"]
    assert payload["messages"][-1]["content"] == "已修正工具路径并收束：runtime scene 摘要需要基于返回内容继续推进。"
    assert payload["currentPhase"] == "ready"


def test_submit_session_message_keeps_previous_continuation_reply_when_done_marker_follows(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=2),
    )
    calls = []

    class MarkerAfterReplyAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            calls.append(initial_prompt)
            if len(calls) == 1:
                return {
                    "status": "completed",
                    "summary": "已审查当前项目。以下是汇报结果。\n\n核心问题是回答持久化和 UI 区分度。",
                    "raw_output": "已审查当前项目。以下是汇报结果。\n\n核心问题是回答持久化和 UI 区分度。",
                    "outcome": "progress",
                    "read_files": ["README.md"],
                    "tool_call_count": 1,
                    "tool_trace": [
                        {"name": "read_file_tool", "args": {"file_path": "README.md"}},
                    ],
                }
            return {
                "status": "completed",
                "summary": "[outcome=done]",
                "raw_output": "[outcome=done]",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    monkeypatch.setattr(session_service, "create_chat_agent", lambda: MarkerAfterReplyAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "你现在审查一下整个项目,并向我汇报结果"},
    )

    assert response.status_code == 202, response.json()
    payload = response.json()
    assistant = payload["messages"][-1]
    assert len(calls) == 2
    assert assistant["content"] == "已审查当前项目。以下是汇报结果。\n\n核心问题是回答持久化和 UI 区分度。"
    assert "[outcome=done]" not in json.dumps(payload, ensure_ascii=False)
    assert payload["activeTask"] is None


def test_submit_session_message_never_persists_empty_assistant_reply(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=1),
    )

    class EmptyVisibleAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "[outcome=done]",
                "raw_output": "<state>{}</state>",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: EmptyVisibleAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "请审查项目并汇报"},
    )

    assert response.status_code == 202, response.json()
    payload = response.json()
    assistant = payload["messages"][-1]
    assert assistant["role"] == "assistant"
    assert assistant["content"].strip()
    assert assistant["content"] == "本轮没有产生可见回复。"

    state = load_chat_state(tmp_path)
    persisted_assistant = state["conversations"][0]["messages"][-1]
    assert persisted_assistant["role"] == "assistant"
    assert persisted_assistant["content"] == "本轮没有产生可见回复。"


def test_session_visible_reply_treats_litellm_empty_placeholder_as_no_visible_reply():
    placeholder = "[System: Empty message content sanitised to satisfy protocol]"
    result = {
        "status": "completed",
        "summary": placeholder,
        "raw_output": placeholder,
        "outcome": "progress",
        "tool_call_count": 1,
        "tool_trace": [
            {"name": "read_file_tool", "args": {"file_path": "README.md"}},
        ],
    }

    visible = session_service._format_visible_reply(result)
    ensured = session_service._ensure_assistant_visible_text(
        visible,
        result=result,
        lang="zh",
    )

    assert visible == "已查看：README.md"
    assert ensured == "已查看：README.md"
    assert session_service._visible_reply_summary_candidate(result) == "已查看：README.md"
    assert placeholder not in ensured


def test_submit_session_message_does_not_persist_xml_protocol_as_reply_or_task(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "prompt_debugger.py").write_text("pass\n", encoding="utf-8")
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=1),
    )

    class ProtocolOnlyAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": (
                    "继续检查文件。\n"
                    '<invoke name="read_file_tool">'
                    '<parameter name="file_path">tests/prompt_debugger.py</parameter>'
                    "</invoke>\n"
                    "</parameter>"
                ),
                "raw_output": (
                    "继续检查文件。\n"
                    '<invoke name="read_file_tool">'
                    '<parameter name="file_path">tests/prompt_debugger.py</parameter>'
                    "</invoke>\n"
                    "<state"
                ),
                "outcome": "done",
                "read_files": ["tests/prompt_debugger.py"],
                "tool_call_count": 1,
                "tool_trace": [
                    {"name": "read_file_tool", "args": {"file_path": "tests/prompt_debugger.py"}},
                ],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ProtocolOnlyAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "请继续检查 BDD 调试工具规划"},
    )

    assert response.status_code == 202, response.json()
    payload = response.json()
    assistant = payload["messages"][-1]
    assert assistant["content"] == "继续检查文件。"
    state = load_chat_state(tmp_path)
    persisted_json = json.dumps(state, ensure_ascii=False)
    assert "<invoke" not in persisted_json
    assert "<parameter" not in persisted_json
    assert "</parameter>" not in persisted_json
    assert "<state" not in persisted_json
    assert "active_task" not in state["conversations"][0]


def test_submit_session_message_ignores_configured_continuation_limit_until_done(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "prompt_debugger.py").write_text("pass\n", encoding="utf-8")
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=1),
    )
    calls = []

    class ProgressThenDoneAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            calls.append(initial_prompt)
            if len(calls) < 3:
                return {
                    "status": "completed",
                    "summary": "",
                    "raw_output": "",
                    "outcome": "progress",
                    "next_action": "继续读取测试工具结构并形成规划。",
                    "read_files": ["tests/prompt_debugger.py"],
                    "tool_call_count": 1,
                    "tool_trace": [
                        {"name": "read_file_tool", "args": {"file_path": "tests/prompt_debugger.py"}},
                    ],
                }
            return {
                "status": "completed",
                "summary": "规划完成：包装 prompt_debugger 的 BDD 场景过滤能力。",
                "raw_output": "规划完成：包装 prompt_debugger 的 BDD 场景过滤能力。",
                "outcome": "done",
                "read_files": ["tests/prompt_debugger.py"],
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ProgressThenDoneAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "做一个测试工具吧,能够更快速的进行BDD调试,先规划一下,然后向我汇报"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert len(calls) == 3
    assert "任务级持续上限" not in payload["messages"][-1]["content"]
    assert payload["messages"][-1]["content"] == "规划完成：包装 prompt_debugger 的 BDD 场景过滤能力。"
    assert payload["currentPhase"] == "ready"
    latest_run = session_service.load_chat_turn_work_run_summary()["latest"]
    assert latest_run["status"] == "completed"
    assert latest_run["finishedAt"]


def test_submit_session_message_preserves_visible_progress_without_limit_prompt(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=1),
    )
    calls = []

    class VisibleProgressAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            calls.append(initial_prompt)
            if len(calls) == 1:
                return {
                    "status": "completed",
                    "summary": "我已经完成第一项优化，并通过基础验证。下一步继续收口剩余日志路径。",
                    "raw_output": "我已经完成第一项优化，并通过基础验证。下一步继续收口剩余日志路径。",
                    "outcome": "progress",
                    "next_action": "继续收口剩余日志路径。",
                    "tool_call_count": 1,
                    "tool_trace": [{"name": "cli_tool", "args": {"command": "python -m py_compile core/logging/__init__.py"}}],
                }
            return {
                "status": "completed",
                "summary": "[outcome=done]",
                "raw_output": "[outcome=done]",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: VisibleProgressAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续优化日志系统"},
    )

    assert response.status_code == 202
    payload = response.json()
    assistant = payload["messages"][-1]
    assert len(calls) == 2
    assert assistant["content"] == "我已经完成第一项优化，并通过基础验证。下一步继续收口剩余日志路径。"
    assert "任务级持续上限" not in assistant["content"]
    assert payload["currentPhase"] == "ready"
    latest_run = session_service.load_chat_turn_work_run_summary()["latest"]
    assert latest_run["status"] == "completed"
    state = load_chat_state(tmp_path)
    assert "active_task" not in state["conversations"][0]


def test_submit_session_message_continues_repeated_visible_progress_until_done(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=4),
    )
    calls = []
    repeated_reply = "已完成日志审查：问题集中在 continuation loop 反复发送同一段可见进展。"

    class RepeatingVisibleProgressAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            calls.append(initial_prompt)
            if len(calls) < 3:
                return {
                    "status": "completed",
                    "summary": repeated_reply,
                    "raw_output": repeated_reply,
                    "outcome": "progress",
                    "next_action": "继续收束同一问题。",
                    "tool_call_count": 1,
                    "tool_trace": [{"name": "read_file_tool", "args": {"file_path": "core/web/services/session_service.py"}}],
                }
            return {
                "status": "completed",
                "summary": "[outcome=done]",
                "raw_output": "[outcome=done]",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: RepeatingVisibleProgressAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "分析对话重复输出问题"},
    )

    assert response.status_code == 202
    payload = response.json()
    assistant = payload["messages"][-1]
    assert len(calls) == 3
    assert assistant["content"] == repeated_reply
    assert assistant["content"].count(repeated_reply) == 1
    assert "任务级持续上限" not in assistant["content"]
    assert payload["currentPhase"] == "ready"
    latest_run = session_service.load_chat_turn_work_run_summary()["latest"]
    assert latest_run["status"] == "completed"


def test_submit_session_message_stops_on_inferred_progress_visible_conclusion(tmp_path, monkeypatch):
    (tmp_path / "core" / "web" / "services").mkdir(parents=True, exist_ok=True)
    (tmp_path / "core" / "web" / "services" / "session_service.py").write_text("pass\n", encoding="utf-8")
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=1),
    )
    calls = []
    conclusion = "根因已经确认：推断出来的 progress 不应该让已完成的可见结论再次进入 continuation。"

    class InferredProgressConclusionAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            calls.append(initial_prompt)
            return {
                "status": "completed",
                "summary": conclusion,
                "raw_output": conclusion,
                "outcome": "progress",
                "metadata": {"chat_contract_outcome_source": "inferred"},
                "read_files": ["core/web/services/session_service.py"],
                "tool_call_count": 1,
                "tool_trace": [
                    {
                        "name": "read_file_tool",
                        "args": {"file_path": "core/web/services/session_service.py"},
                    }
                ],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: InferredProgressConclusionAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "分析对话重复输出问题"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert len(calls) == 1
    assert payload["messages"][-1]["content"] == conclusion
    assert payload["currentPhase"] == "ready"
    latest_run = session_service.load_chat_turn_work_run_summary()["latest"]
    assert latest_run["status"] == "completed"


def test_submit_session_message_completed_turn_ignores_low_configured_limit(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="reading")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=1),
    )

    class DoneAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "已经完成优化并验证通过。",
                "raw_output": "已经完成优化并验证通过。",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DoneAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "完成这个优化"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["messages"][-1]["content"] == "已经完成优化并验证通过。"
    assert "任务级持续上限" not in payload["messages"][-1]["content"]
    assert payload["currentPhase"] == "ready"
    latest_run = session_service.load_chat_turn_work_run_summary()["latest"]
    assert latest_run["status"] == "completed"


def test_submit_session_continue_preserves_raw_prompt_and_unfinished_task_state(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "prompt_debugger.py").write_text("pass\n", encoding="utf-8")
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        active_task={
            "task_id": "bdd-tool-plan",
            "kind": "coding",
            "status": "reading",
            "title": "做一个 BDD 调试测试工具规划并汇报",
            "goal": "做一个 BDD 调试测试工具规划并汇报",
            "read_files": ["tests/prompt_debugger.py"],
            "latest_summary": "已读取测试工具结构。",
            "updated_at": "2026-05-20T16:24:53",
            "metadata": {"source": "task_tool"},
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=1),
    )
    prompts = []

    class ResumeAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            prompts.append(initial_prompt)
            return {
                "status": "completed",
                "summary": "继续完成规划：建议包装 prompt_debugger 的 BDD 场景过滤能力。",
                "raw_output": "继续完成规划：建议包装 prompt_debugger 的 BDD 场景过滤能力。",
                "outcome": "done",
                "read_files": ["tests/prompt_debugger.py"],
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ResumeAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert prompts[0] == "继续"
    state = load_chat_state(tmp_path)
    active_task = state["conversations"][0]["active_task"]
    assert active_task["goal"] == "做一个 BDD 调试测试工具规划并汇报"
    assert active_task["title"] == "做一个 BDD 调试测试工具规划并汇报"
    assert active_task["last_user_message"] == "继续"


def test_submit_session_continue_clears_stale_next_action_after_visible_reply(tmp_path, monkeypatch):
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        active_task={
            "task_id": "stale-next-action",
            "kind": "coding",
            "status": "reading",
            "title": "查看系统提示词",
            "goal": "查看系统提示词",
            "latest_summary": "已完成前半段汇报。",
            "next_action": "发送“继续”以恢复停止前的现场。",
            "updated_at": "2026-05-24T20:10:41",
            "metadata": {"source": "task_tool"},
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=1),
    )

    class ResumeAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "继续上次未完成的汇报，系统提示词已汇总完成。",
                "raw_output": "继续上次未完成的汇报，系统提示词已汇总完成。",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ResumeAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["activeTask"]["goal"] == "查看系统提示词"
    assert payload["activeTask"]["latestSummary"] == "继续上次未完成的汇报，系统提示词已汇总完成。"
    assert payload["activeTask"]["nextAction"] == ""

    state = load_chat_state(tmp_path)
    active_task = state["conversations"][0]["active_task"]
    assert active_task["next_action"] == ""


def test_submit_session_continue_keeps_raw_prompt_when_active_task_is_continue(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "prompt_debugger.py").write_text("pass\n", encoding="utf-8")
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        active_task={
            "task_id": "polluted-continue",
            "kind": "coding",
            "status": "reading",
            "title": "继续",
            "goal": "继续",
            "read_files": ["tests/prompt_debugger.py"],
            "latest_summary": "<state",
            "updated_at": "2026-05-20T17:54:06",
            "metadata": {"source": "task_tool"},
        },
    )
    state = load_chat_state(tmp_path)
    state["conversations"][0]["messages"] = [
        {
            "role": "user",
            "content": "做一个测试工具吧,能够更快速的进行BDD调试,先规划一下,然后向我汇报",
            "timestamp": "2026-05-20T17:50:00",
        },
        {
            "role": "assistant",
            "content": "已达到 Web Chat 任务级持续上限（1 轮），本次先暂停，避免后台无限运行。",
            "timestamp": "2026-05-20T17:51:00",
        },
        {
            "role": "user",
            "content": "继续",
            "timestamp": "2026-05-20T17:53:05",
        },
    ]
    save_chat_state(tmp_path, state)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=2),
    )
    prompts = []

    class ResumeAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            prompts.append(initial_prompt)
            if len(prompts) == 1:
                return {
                    "status": "completed",
                    "summary": "<state",
                    "raw_output": "<state",
                    "outcome": "progress",
                    "next_action": "继续读取测试工具结构并形成规划。",
                    "read_files": ["tests/prompt_debugger.py"],
                    "tool_call_count": 1,
                    "tool_trace": [
                        {"name": "read_file_tool", "args": {"file_path": "tests/prompt_debugger.py"}},
                    ],
                }
            return {
                "status": "completed",
                "summary": "规划已恢复：先包装 prompt_debugger 的 BDD 场景过滤能力。",
                "raw_output": "规划已恢复：先包装 prompt_debugger 的 BDD 场景过滤能力。",
                "outcome": "done",
                "read_files": ["tests/prompt_debugger.py"],
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ResumeAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续"},
    )

    assert response.status_code == 202
    assert prompts[0] == "继续"
    payload = response.json()
    assert len(prompts) == 2
    assert prompts[1] == "继续完成同一个用户目标：做一个测试工具吧,能够更快速的进行BDD调试,先规划一下,然后向我汇报\n上一内部回合仍未完成用户目标（第 1 轮）。\n不要只输出 <state>；如果目标已完成，请给出可见汇报并标记 outcome=done。\n优先执行上一轮下一步：继续读取测试工具结构并形成规划。"
    assert payload["messages"][-1]["content"] == "规划已恢复：先包装 prompt_debugger 的 BDD 场景过滤能力。"
    assert "任务级持续上限" not in payload["messages"][-1]["content"]
    assert "<state" not in payload["messages"][-1]["content"]
    state = load_chat_state(tmp_path)
    active_task = state["conversations"][0]["active_task"]
    assert active_task["goal"] == "做一个测试工具吧,能够更快速的进行BDD调试,先规划一下,然后向我汇报"
    assert active_task["title"] == "做一个测试工具吧,能够更快速的进行BDD调试,先规划一下,然后向我汇报"
    assert active_task["latest_summary"] == "规划已恢复：先包装 prompt_debugger 的 BDD 场景过滤能力。"


def test_persist_turn_result_cleans_parameter_and_requires_real_stop(tmp_path, monkeypatch):
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "prompt_debugger.py").write_text("pass\n", encoding="utf-8")
    _seed_chat_state(
        tmp_path,
        task_status="reading",
        active_task={
            "task_id": "bdd-tool-plan",
            "kind": "coding",
            "status": "reading",
            "title": "做一个 BDD 调试测试工具规划并汇报",
            "goal": "做一个 BDD 调试测试工具规划并汇报",
            "read_files": ["tests/prompt_debugger.py"],
            "latest_summary": "已读取测试工具结构。",
            "updated_at": "2026-05-20T16:24:53",
            "metadata": {"source": "task_tool"},
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    session_service._clear_session_turn_control("session-live")

    session_service._persist_session_turn_result(
        "session-live",
        {
            "status": "stopped",
            "summary": "连续被拦截。让我尝试拆分写入。\n</parameter>",
            "raw_output": "连续被拦截。让我尝试拆分写入。\n</parameter>",
            "stop_requested": True,
            "outcome": "progress",
            "read_files": ["tests/prompt_debugger.py"],
            "tool_call_count": 0,
            "tool_trace": [],
        },
    )

    state = load_chat_state(tmp_path)
    message = state["conversations"][0]["messages"][-1]
    assert message["role"] == "assistant"
    assert message["content"] == "连续被拦截。让我尝试拆分写入。"
    assert message["content"] != "本轮已按请求停止。"
    active_task = state["conversations"][0]["active_task"]
    assert active_task["latest_summary"] == "连续被拦截。让我尝试拆分写入。"
    assert "</parameter>" not in json.dumps(active_task, ensure_ascii=False)


def test_session_detail_uses_ready_phase_for_resting_sessions(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200
    payload = response.json()
    assert payload["currentPhase"] == "ready"


def test_submit_session_message_persists_visible_failure(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    class FailingAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            raise RuntimeError("LLM unavailable")

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: FailingAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "请修复 web/src/routes/ChatCodingRoute.tsx 的提交流程"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["messages"][-1]["role"] == "assistant"
    assert "失败" in payload["messages"][-1]["content"] or "failed" in payload["messages"][-1]["content"].lower()
    assert "LLM unavailable" in payload["messages"][-1]["content"]
    assert payload["currentPhase"] == "failed"


def test_submit_session_message_surfaces_failed_result_error(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    class FailingResultAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "failed",
                "summary": "",
                "raw_output": "",
                "error": "configuration_error: LiteLLM 未安装，无法执行模型调用；请安装 litellm",
                "outcome": "blocked",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: FailingResultAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "你现在是这个项目的agent，请告诉我目前的感受"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["messages"][-1]["role"] == "assistant"
    assert "LiteLLM 未安装" in payload["messages"][-1]["content"]
    assert payload["currentPhase"] == "failed"


def test_submit_session_message_surfaces_provider_error_inside_messages(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "_WORK_RUN_STORE",
        session_service.WorkRunStore(tmp_path / ".runtime" / "runtime-manager" / "work_runs"),
    )

    provider_error = (
        'provider_protocol_error: litellm.BadGatewayError: BadGatewayError: OpenAIException - '
        '{"error":{"message":"Upstream request failed","type":"upstream_error"}}'
    )

    class ProviderFailingAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "failed",
                "summary": provider_error,
                "raw_output": provider_error,
                "error": provider_error,
                "outcome": "blocked",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ProviderFailingAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续当前对话"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["messages"][-2]["role"] == "user"
    assert payload["messages"][-2]["content"] == "继续当前对话"
    assert payload["messages"][-1]["role"] == "assistant"
    assert "模型服务上游暂时失败" in payload["messages"][-1]["content"]
    assert "provider 上游服务不可用或网关失败" in payload["messages"][-1]["content"]
    assert payload["messages"][-1]["metadata"]["kind"] == "turn_error"
    assert payload["messages"][-1]["metadata"]["providerFailure"] is True
    assert payload["messages"][-1]["metadata"]["reasonCode"] == "upstream_unavailable"
    assert payload["messages"][-1]["metadata"]["reasonDetail"] == "Upstream request failed"
    assert payload["lastTurnError"]["errorType"] == "provider_upstream_error"
    assert payload["lastTurnError"]["reasonCode"] == "upstream_unavailable"
    assert "provider 上游服务不可用或网关失败" in payload["lastTurnError"]["reasonSummary"]
    assert payload["lastTurnError"]["reasonDetail"] == "Upstream request failed"
    assert "模型服务上游暂时失败" in payload["lastTurnError"]["message"]
    assert "Upstream request failed" in payload["messages"][-1]["content"]
    assert "litellm.BadGatewayError" not in payload["lastTurnError"]["message"]
    assert "litellm.BadGatewayError" not in payload["messages"][-1]["content"]
    latest_run = session_service._WORK_RUN_STORE.load_latest_snapshot("chat_turn")
    assert latest_run["errorType"] == "provider_upstream_error"
    assert "litellm.BadGatewayError" in latest_run["error"]


def test_submit_session_message_surfaces_local_runtime_exception_as_turn_error(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "_WORK_RUN_STORE",
        session_service.WorkRunStore(tmp_path / ".runtime" / "runtime-manager" / "work_runs"),
    )

    def raise_missing_key(*_args, **_kwargs):
        raise ValueError("未设置 API Key: VIBELUTION_LLM_MODEL_RELAY_OPENAI_GPT_5_5_API_KEY")

    monkeypatch.setattr(session_service, "create_chat_agent", raise_missing_key)
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续当前对话"},
    )

    assert response.status_code == 202
    payload = response.json()
    error_message = payload["messages"][-1]
    assert error_message["role"] == "assistant"
    assert error_message["metadata"]["kind"] == "turn_error"
    assert error_message["metadata"]["providerFailure"] is False
    assert error_message["metadata"]["errorType"] == "ValueError"
    assert "网页工作台这一轮执行失败" in error_message["content"]
    assert "未设置 API Key" in error_message["content"]
    assert payload["lastTurnError"]["errorType"] == "ValueError"
    assert payload["lastTurnError"]["recoverable"] is False
    latest_run = session_service._WORK_RUN_STORE.load_latest_snapshot("chat_turn")
    assert latest_run["errorType"] == "ValueError"
    assert "VIBELUTION_LLM_MODEL_RELAY_OPENAI_GPT_5_5_API_KEY" in latest_run["error"]


def test_failed_runtime_turn_result_is_persisted_as_turn_error_with_trace(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    failed_result = {
        "status": "failed_runtime",
        "summary": "图像路由失败：当前模型不支持图片输入。",
        "raw_output": "图像路由失败：当前模型不支持图片输入。",
        "error": "图像路由失败：当前模型不支持图片输入。",
        "outcome": "blocked",
        "thought": "Need a vision-capable model before continuing.",
        "tool_trace": [{"name": "image2_generate_tool", "status": "failed", "summary": "unsupported"}],
        "feedback_events": [{"kind": "status", "name": "model_request", "status": "failed", "summary": "模型请求失败"}],
    }

    session_service._set_session_running("session-live", True, turn_id="turn-runtime-failure")
    try:
        session_service._persist_session_turn_result(
            "session-live",
            failed_result,
            turn_id="turn-runtime-failure",
        )
    finally:
        session_service._set_session_running("session-live", False, turn_id="turn-runtime-failure")
    payload = session_service.get_session_detail("session-live")

    error_message = payload["messages"][-1]
    assert error_message["metadata"]["kind"] == "turn_error"
    assert error_message["metadata"]["providerFailure"] is False
    assert error_message["content"].startswith("网页工作台这一轮执行失败")
    assert "当前模型不支持图片输入" in error_message["content"]
    assert error_message["thought"] == "Need a vision-capable model before continuing."
    assert error_message["toolCalls"] == [
        {"name": "image2_generate_tool", "status": "failed", "summary": "unsupported"}
    ]
    assert error_message["feedbackEvents"][0]["status"] == "failed"
    assert payload["lastTurnError"]["errorType"] == "runtime_error"
    assert payload["currentPhase"] == "failed"


def test_submit_session_message_surfaces_provider_http_diagnostics(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    provider_error = (
        "server_error: litellm.ServiceUnavailableError: AnthropicException - "
        "b'{\"error\":{\"message\":\"No available accounts: no available accounts\","
        "\"type\":\"api_error\"},\"type\":\"error\"}'."
    )

    class ProviderFailingAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "failed",
                "summary": "server_error",
                "raw_output": "server_error",
                "error": "server_error",
                "llm_failure": {
                    "category": "server_error",
                    "message": provider_error,
                    "provider": "anthropic",
                    "model": "claude-opus-4-7",
                    "api_base": "https://www.atpify.cn",
                    "retryable": True,
                },
                "outcome": "blocked",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ProviderFailingAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续当前对话"},
    )

    assert response.status_code == 202
    payload = response.json()
    metadata = payload["messages"][-1]["metadata"]
    assert metadata["httpStatus"] == 503
    assert metadata["provider"] == "anthropic"
    assert metadata["providerHost"] == "www.atpify.cn"
    assert metadata["providerErrorType"] == "api_error"
    assert metadata["providerErrorMessage"] == "No available accounts: no available accounts"
    assert metadata["model"] == "claude-opus-4-7"
    assert payload["lastTurnError"]["httpStatus"] == 503
    assert payload["lastTurnError"]["providerErrorType"] == "api_error"
    assert payload["lastTurnError"]["providerErrorMessage"] == "No available accounts: no available accounts"
    assert "HTTP 503" in payload["messages"][-1]["content"]
    assert "No available accounts" in payload["messages"][-1]["content"]


def test_submit_session_message_surfaces_prompt_cache_unsupported_inside_messages(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    cache_error = (
        "prompt_cache_unsupported: 当前模型配置声明不支持 prompt cache；"
        "profile `primary` provider `relay` transport `responses` model `gpt-5.5`。"
    )

    class CacheUnsupportedAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "failed",
                "summary": cache_error,
                "raw_output": cache_error,
                "error": cache_error,
                "outcome": "blocked",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: CacheUnsupportedAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续当前对话"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["messages"][-1]["role"] == "assistant"
    assert "模型配置不满足本轮 prompt cache 要求" in payload["messages"][-1]["content"]
    assert "当前模型配置声明不支持 prompt cache" in payload["messages"][-1]["content"]
    assert "prompt_cache.mode 配置为 automatic 或 explicit_cache_control" in payload["messages"][-1]["content"]
    assert "模型服务上游暂时失败" not in payload["messages"][-1]["content"]
    assert payload["messages"][-1]["metadata"]["kind"] == "turn_error"
    assert payload["messages"][-1]["metadata"]["reasonCode"] == "prompt_cache_unsupported"
    assert payload["lastTurnError"]["errorType"] == "prompt_cache_unsupported"
    assert payload["lastTurnError"]["reasonCode"] == "prompt_cache_unsupported"


def test_submit_session_message_surfaces_provider_quota_reason_inside_messages(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    provider_error = (
        'provider_protocol_error: litellm.RateLimitError: AnthropicException - '
        'b\'{"error":{"message":"api key 7天限额已用完","type":"rate_limit_exceeded"},"type":"error"}\''
    )

    class ProviderFailingAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "failed",
                "summary": provider_error,
                "raw_output": provider_error,
                "error": provider_error,
                "outcome": "blocked",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ProviderFailingAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "你好"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert "API Key 额度或当日限额已用完" in payload["messages"][-1]["content"]
    assert "api key 7天限额已用完" in payload["messages"][-1]["content"]
    assert payload["messages"][-1]["metadata"]["reasonCode"] == "quota_exhausted"
    assert payload["messages"][-1]["metadata"]["reasonDetail"] == "api key 7天限额已用完"
    assert payload["lastTurnError"]["reasonCode"] == "quota_exhausted"
    assert payload["lastTurnError"]["reasonSummary"] == "API Key 额度或当日限额已用完"
    assert payload["lastTurnError"]["reasonDetail"] == "api key 7天限额已用完"


def test_submit_session_message_prefers_llm_failure_message_for_provider_detail(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    generic_error = "provider_protocol_error"
    detailed_error = (
        'provider_protocol_error: litellm.RateLimitError: AnthropicException - '
        'b\'{"error":{"message":"group requests-per-minute limit exceeded","type":"rate_limit_exceeded"},"type":"error"}\''
    )

    class CircuitBreakerFailingAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "failed",
                "summary": generic_error,
                "raw_output": generic_error,
                "error": generic_error,
                "llm_failure": {
                    "category": "provider_protocol_error",
                    "message": detailed_error,
                    "retryable": False,
                },
                "outcome": "blocked",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: CircuitBreakerFailingAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "你好"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert "provider 正在限流" in payload["messages"][-1]["content"]
    assert "group requests-per-minute limit exceeded" in payload["messages"][-1]["content"]
    assert payload["messages"][-1]["metadata"]["reasonCode"] == "rate_limited"
    assert payload["messages"][-1]["metadata"]["reasonDetail"] == "group requests-per-minute limit exceeded"
    assert payload["lastTurnError"]["reasonDetail"] == "group requests-per-minute limit exceeded"


def test_submit_session_message_surfaces_deprecated_parameter_reason_inside_messages(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    provider_error = "provider_protocol_error: invalid_request_error: `temperature` is deprecated for this model."

    class ProviderFailingAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "failed",
                "summary": provider_error,
                "raw_output": provider_error,
                "error": provider_error,
                "outcome": "blocked",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: ProviderFailingAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "你好"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert "模型不接受当前采样参数，例如 temperature" in payload["messages"][-1]["content"]
    assert "`temperature` is deprecated" in payload["messages"][-1]["content"]
    assert payload["messages"][-1]["metadata"]["reasonCode"] == "deprecated_sampling_parameter"
    assert payload["messages"][-1]["metadata"]["reasonDetail"] == "`temperature` is deprecated for this model."
    assert payload["lastTurnError"]["reasonCode"] == "deprecated_sampling_parameter"


def test_submit_session_message_omits_mental_snapshot_when_disabled(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "is_mental_model_enabled", lambda: False)

    class DummyAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "继续推进并给出下一步建议。",
                "raw_output": "继续推进并给出下一步建议。",
                "reasoning_content": "先保留思考，再让心智快照按开关退场。",
                "mental_snapshot": {
                    "mood": "专注",
                    "feeling": "这部分应该被开关挡住。",
                    "whisper": "不要落盘。",
                    "cognitiveState": "productive",
                },
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续修复 web/src/routes/ChatCodingRoute.tsx"},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["messages"][-1]["thought"] == "先保留思考，再让心智快照按开关退场。"
    assert "mentalSnapshot" not in payload["messages"][-1]


def test_submit_session_message_uses_per_turn_mental_model_override(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "is_mental_model_enabled", lambda: True)

    created_agents = []

    class DummyAgent:
        def __init__(self):
            self.override = None
            self.seeded_history = None
            created_agents.append(self)

        def set_mental_model_enabled_override(self, enabled):
            self.override = enabled

        def seed_chat_history(self, messages):
            self.seeded_history = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "已按本轮开关处理。",
                "raw_output": "已按本轮开关处理。",
                "mental_snapshot": {
                    "mood": "专注",
                    "feeling": "如果开关关闭，这里不应该落盘。",
                    "whisper": "per-turn",
                    "cognitiveState": "productive",
                },
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", DummyAgent)
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    disabled_response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "这一轮不要打开心智模型", "mentalModelEnabled": False},
    )

    assert disabled_response.status_code == 202, disabled_response.json()
    disabled_payload = disabled_response.json()
    assert created_agents[-1].override is False
    assert "mentalSnapshot" not in disabled_payload["messages"][-1]

    enabled_response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "这一轮打开心智模型", "mentalModelEnabled": True},
    )

    assert enabled_response.status_code == 202, enabled_response.json()
    enabled_payload = enabled_response.json()
    assert created_agents[-1].override is True
    assert enabled_payload["messages"][-1]["mentalSnapshot"]["mood"] == "专注"


def test_turn_mental_snapshot_prefers_current_state_info_over_runtime_summary(monkeypatch):
    monkeypatch.setattr(session_service, "is_mental_model_enabled", lambda: True)
    monkeypatch.setattr(
        runtime_service,
        "_mental_state_summary",
        lambda lang: {
            "mood": "焦虑",
            "feeling": "旧的图片生成失败状态。",
            "whisper": "先检查 API 密钥。",
            "summary": "旧状态不应覆盖本轮。",
            "source": "state",
        },
    )
    monkeypatch.setattr(
        session_service,
        "_diagnosis_mental_snapshot",
        lambda lang, *, session_workspace=None: {
            "mood": "",
            "feeling": "",
            "whisper": "",
            "summary": "当前以规则诊断为主，认知态：稳定。",
            "cognitiveState": "normal",
            "confidence": 0.5,
            "sampleSize": 2,
            "interventionCount": 0,
            "source": "diagnosis",
        },
    )
    recorded_events = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)),
    )

    snapshot = session_service._build_turn_mental_snapshot(
        {
            "state_info": {
                "mood": "专注",
                "feeling": "正在按用户最新要求配置默认头像。",
                "whisper": "使用 workspace/avatars 里的现有图片。",
            }
        },
        "zh",
        mental_model_enabled=True,
        session_id="session-live",
        turn_id="turn-current",
    )

    assert snapshot["mood"] == "专注"
    assert snapshot["feeling"] == "正在按用户最新要求配置默认头像。"
    assert snapshot["whisper"] == "使用 workspace/avatars 里的现有图片。"
    assert snapshot["source"] == "state"
    assert snapshot["cognitiveState"] == "normal"
    assert recorded_events
    assert recorded_events[-1][0] == (
        "conversation",
        "mental_snapshot",
        "conversation.mental_snapshot.selected",
    )
    assert recorded_events[-1][1]["fields"]["chosenSource"] == "state"
    assert recorded_events[-1][1]["fields"]["hasRuntimeSnapshot"] is True


def test_submit_session_message_includes_stream_friendly_tool_and_mental_payloads(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    class DummyAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "已完成三段式输出。",
                "raw_output": "最终回答内容。",
                "thought": "这是一段可见思考。",
                "reasoning_content": "这是一段可见思考。",
                "state_info": {
                    "mood": "专注",
                    "feeling": "心智模型已展开。",
                    "whisper": "工具调用继续保持单块。",
                },
                "mental_snapshot": {
                    "mood": "专注",
                    "feeling": "心智模型已展开。",
                    "whisper": "工具调用继续保持单块。",
                    "cognitiveState": "productive",
                    "confidence": 0.91,
                    "sampleSize": 3,
                    "interventionCount": 1,
                    "updatedAt": "2026-05-18T12:01:00",
                    "source": "diagnosis",
                    "intervention": "继续保持当前路径。",
                    "metrics": {"sample_size": 3, "intervention_count": 1},
                    "historyTail": [
                        {"cognitiveState": "productive", "confidence": 0.91, "timestamp": "2026-05-18T12:01:00"},
                    ],
                },
                "tool_trace": [
                    {"name": "read_file_tool", "result_preview": "read ok", "status": "success"},
                    {"name": "run_test_for_tool", "result_preview": "tests passed", "status": "success"},
                ],
                "tool_call_count": 2,
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "继续把对话展示改成四段式"},
    )

    assert response.status_code == 202
    payload = response.json()
    assistant = payload["messages"][-1]
    assert assistant["content"] == "最终回答内容。"
    assert assistant["thought"] == "这是一段可见思考。"
    assert assistant["mentalSnapshot"]["cognitiveState"] == "productive"
    assert assistant["mentalSnapshot"]["intervention"] == "继续保持当前路径。"
    assert assistant["mentalSnapshot"]["metrics"]["sample_size"] == 3
    assert assistant["toolCalls"] == [
        {"name": "read_file_tool", "status": "done", "summary": "read ok", "resultPreview": "read ok"},
        {
            "name": "run_test_for_tool",
            "status": "done",
            "summary": "tests passed",
            "resultPreview": "tests passed",
        },
    ]
    assert payload["currentPhase"] == "ready"


def test_submit_session_message_restores_prior_mental_snapshot_for_agent(tmp_path, monkeypatch):
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": "session-live",
            "updated_at": "2026-05-20T14:00:00",
            "conversations": [
                {
                    "conversation_id": "session-live",
                    "title": "真实会话",
                    "updated_at": "2026-05-20T14:00:00",
                    "last_turn_status": "ready",
                    "messages": [
                        {
                            "role": "user",
                            "content": "你能感知到你的心智模型吗",
                            "timestamp": "2026-05-20T13:58:00",
                        },
                        {
                            "role": "assistant",
                            "content": "我对自己的心智模型能感知多少？",
                            "timestamp": "2026-05-20T13:59:00",
                            "mental_snapshot": {
                                "mood": "沉思",
                                "feeling": "正在延续心智模型话题。",
                                "whisper": "接住上一段回答。",
                                "sampleSize": 4,
                            },
                        },
                    ],
                }
            ],
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    captured = {}

    class DummyAgent:
        def seed_chat_history(self, messages):
            captured["history"] = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "继续补完心智模型回答。",
                "raw_output": "继续补完心智模型回答。",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DummyAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn(context),
    )

    response = client.post(
        "/api/sessions/session-live/messages",
        json={"content": "你话还没说完"},
    )

    assert response.status_code == 202
    assert captured["history"][1]["mental_snapshot"]["mood"] == "沉思"
    assert captured["history"][0]["content"] == "你能感知到你的心智模型吗"


def test_runtime_summary_prefers_current_phase_over_stale_task_progress(monkeypatch):
    monkeypatch.setattr(
        runtime_service,
        "get_active_session_summary",
        lambda: {
            "title": "真实会话",
            "taskSummary": "继续前端开发",
            "currentPhase": "ready",
            "changedFiles": ["web/src/routes/ChatCodingRoute.tsx"],
        },
    )
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})

    payload = runtime_service.get_runtime_summary()

    assert payload["status"] == "success"
    assert payload["currentPhase"] == "ready"


def test_runtime_summary_exposes_runtime_manager_workbench_state(monkeypatch):
    monkeypatch.setattr(runtime_service, "get_active_session_summary", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})
    monkeypatch.setattr(
        runtime_service,
        "_load_runtime_manager_snapshot",
        lambda: {
            "daemonRunning": True,
            "runtimeState": "running",
            "managerPid": 9912,
            "stateVersion": 17,
            "workbench": {
                "desiredState": "closed",
                "observedState": "open",
                "phase": "closing",
                "backendPid": 3001,
                "browserWindowPid": 4002,
                "browserManaged": True,
                "url": "http://127.0.0.1:8000",
                "lastReason": "web_close_button",
                "failureMessage": "",
            },
        },
    )

    payload = runtime_service.get_runtime_summary()

    assert payload["runtimeManager"]["running"] is True
    assert payload["runtimeManager"]["managerPid"] == 9912
    assert payload["workbench"]["desiredState"] == "closed"
    assert payload["workbench"]["observedState"] == "open"
    assert payload["workbench"]["phase"] == "closing"
    assert payload["workbench"]["backendPid"] == 3001


def test_runtime_summary_uses_light_runtime_manager_snapshot(monkeypatch):
    monkeypatch.setattr(runtime_service, "get_active_session_summary", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})
    monkeypatch.setattr(
        runtime_service,
        "load_runtime_manager_state",
        lambda: {
            "runtimeState": "running",
            "managerPid": 9912,
            "stateVersion": 17,
            "workbench": {
                "desiredState": "open",
                "observedState": "open",
                "phase": "steady",
                "backendPid": 3001,
                "browserWindowPid": 4002,
                "browserManaged": True,
                "url": "http://127.0.0.1:8000",
            },
        },
    )
    monkeypatch.setattr(runtime_service, "current_runtime_manager_pid", lambda project_root: 9912)
    monkeypatch.setattr(
        runtime_service,
        "load_runtime_snapshot",
        lambda: (_ for _ in ()).throw(AssertionError("runtime summary must not perform full runtime snapshot observation")),
        raising=False,
    )

    payload = runtime_service.get_runtime_summary()

    assert payload["runtimeManager"]["running"] is True
    assert payload["runtimeManager"]["managerPid"] == 9912
    assert payload["workbench"]["observedState"] == "open"
    assert payload["lifecycleProof"]["projectRootMatches"] is True


def test_runtime_summary_labels_launcher_control_surface_separately(monkeypatch):
    monkeypatch.setattr(runtime_service, "get_active_session_summary", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})
    monkeypatch.setattr(
        runtime_service,
        "_load_runtime_manager_snapshot",
        lambda: {
            "daemonRunning": True,
            "runtimeState": "running",
            "managerPid": 9912,
            "stateVersion": 19,
            "workbench": {
                "sessionRole": "launcher_control_surface",
                "desiredState": "closed",
                "observedState": "closed",
                "phase": "steady",
                "backendPid": 3001,
                "backendAlive": True,
                "backendHealthy": True,
                "backendObserved": True,
                "browserWindowPid": 4002,
                "browserWindowAlive": True,
                "browserManaged": True,
                "url": "http://127.0.0.1:8000",
            },
        },
    )

    payload = runtime_service.get_runtime_summary()

    assert payload["workbench"]["sessionRole"] == "launcher_control_surface"
    assert payload["workbench"]["observedState"] == "closed"
    assert "Launcher 控制台正在运行" in payload["workbench"]["statusLine"]
    assert payload["lifecycleProof"]["overallState"] == "partial"


def test_runtime_summary_exposes_orphaned_browser_status(monkeypatch):
    monkeypatch.setattr(runtime_service, "get_active_session_summary", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})
    monkeypatch.setattr(
        runtime_service,
        "_load_runtime_manager_snapshot",
        lambda: {
            "daemonRunning": True,
            "runtimeState": "running",
            "managerPid": 9912,
            "stateVersion": 18,
            "workbench": {
                "desiredState": "closed",
                "observedState": "open",
                "phase": "failed",
                "backendPid": 0,
                "browserWindowPid": 12132,
                "backendObserved": False,
                "backendPortListening": False,
                "browserWindowAlive": True,
                "browserManaged": True,
                "backendMissing": True,
                "frontendOrphaned": True,
                "lifecycleConsistency": "orphaned_browser",
                "url": "http://127.0.0.1:8000",
                "lastReason": "external_close",
                "failureMessage": "",
            },
        },
    )

    payload = runtime_service.get_runtime_summary()

    assert payload["workbench"]["frontendOrphaned"] is True
    assert payload["workbench"]["backendMissing"] is True
    assert payload["workbench"]["lifecycleConsistency"] == "orphaned_browser"
    assert "后端服务已经离线" in payload["workbench"]["statusLine"]
    assert payload["lifecycleProof"]["overallState"] == "failed"


def test_runtime_summary_marks_missing_managed_window_as_partial(monkeypatch):
    monkeypatch.setattr(runtime_service, "get_active_session_summary", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})
    monkeypatch.setattr(
        runtime_service,
        "_work_run_summary",
        lambda: {
            "active": {
                "chat_turn": None,
                "self_evolution_run": None,
                "supervised_evolution_run": None,
            },
            "latest": {
                "chat_turn": None,
                "self_evolution_run": None,
                "supervised_evolution_run": None,
            },
        },
    )
    monkeypatch.setattr(
        runtime_service,
        "_load_runtime_manager_snapshot",
        lambda: {
            "daemonRunning": True,
            "runtimeState": "running",
            "managerPid": 9912,
            "stateVersion": 18,
            "projectRoot": str(runtime_service.PROJECT_ROOT),
            "runtimeManager": {"sourceMatches": True},
            "workbench": {
                "desiredState": "open",
                "observedState": "partial",
                "phase": "steady",
                "backendPid": 3001,
                "backendAlive": True,
                "backendHealthy": True,
                "backendObserved": True,
                "backendPort": 8000,
                "backendPortListening": True,
                "backendPortOwnerPid": 3001,
                "backendPortOwnerTrusted": True,
                "backendPortConflict": False,
                "browserWindowPid": 4002,
                "browserWindowAlive": False,
                "browserManaged": True,
                "lifecycleConsistency": "browser_missing",
                "url": "http://127.0.0.1:8000",
                "lastReason": "start",
                "failureMessage": "",
            },
        },
    )

    payload = runtime_service.get_runtime_summary()

    assert payload["workbench"]["observedState"] == "partial"
    assert payload["workbench"]["lifecycleConsistency"] == "browser_missing"
    assert payload["workbench"]["statusLine"] == "工作台窗口已关闭，后端仍在运行。"
    proof = payload["lifecycleProof"]
    assert proof["overallState"] == "partial"
    backend = next(component for component in proof["components"] if component["id"] == "backend")
    window = next(component for component in proof["components"] if component["id"] == "workbench_window")
    assert backend["ok"] is True
    assert window["state"] == "missing"


def test_runtime_lifecycle_proof_marks_ready_when_components_agree(monkeypatch):
    monkeypatch.setattr(runtime_service, "get_active_session_summary", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})
    monkeypatch.setattr(
        runtime_service,
        "_work_run_summary",
        lambda: {
            "active": {
                "chat_turn": None,
                "self_evolution_run": None,
                "supervised_evolution_run": None,
            },
            "latest": {
                "chat_turn": None,
                "self_evolution_run": None,
                "supervised_evolution_run": None,
            },
        },
    )
    monkeypatch.setattr(
        runtime_service,
        "_load_runtime_manager_snapshot",
        lambda: {
            "daemonRunning": True,
            "runtimeState": "running",
            "managerPid": 9912,
            "stateVersion": 17,
            "projectRoot": str(runtime_service.PROJECT_ROOT),
            "runtimeManager": {"sourceMatches": True},
            "workbench": {
                "desiredState": "open",
                "observedState": "open",
                "phase": "steady",
                "backendPid": 3001,
                "browserWindowPid": 4002,
                "browserManaged": True,
                "url": "http://127.0.0.1:8000",
                "lastReason": "start",
                "failureMessage": "",
            },
        },
    )

    payload = runtime_service.get_runtime_summary()

    proof = payload["lifecycleProof"]
    assert proof["overallState"] == "ready"
    assert proof["projectRootMatches"] is True
    assert proof["activeWorkRuns"]["count"] == 0
    assert {component["id"] for component in proof["components"]} >= {
        "runtime_manager",
        "backend",
        "workbench_window",
        "project_root",
        "active_work_runs",
    }


def test_runtime_lifecycle_proof_keeps_advisory_source_staleness_non_blocking(monkeypatch):
    monkeypatch.setattr(runtime_service, "get_active_session_summary", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})
    monkeypatch.setattr(
        runtime_service,
        "_work_run_summary",
        lambda: {
            "active": {
                "chat_turn": None,
                "self_evolution_run": None,
                "supervised_evolution_run": None,
            },
            "latest": {
                "chat_turn": None,
                "self_evolution_run": None,
                "supervised_evolution_run": None,
            },
        },
    )
    monkeypatch.setattr(
        runtime_service,
        "_load_runtime_manager_snapshot",
        lambda: {
            "daemonRunning": True,
            "runtimeState": "running",
            "managerPid": 9912,
            "stateVersion": 18,
            "projectRoot": str(runtime_service.PROJECT_ROOT),
            "runtimeManager": {"sourceMatches": False},
            "workbench": {
                "desiredState": "open",
                "observedState": "open",
                "phase": "steady",
                "backendPid": 3001,
                "backendAlive": True,
                "backendHealthy": True,
                "backendObserved": True,
                "backendPort": 8000,
                "backendPortListening": True,
                "backendPortOwnerPid": 3001,
                "backendPortOwnerTrusted": True,
                "backendPortConflict": False,
                "browserWindowPid": 0,
                "browserWindowAlive": False,
                "browserManaged": True,
                "url": "http://127.0.0.1:8000",
                "lastReason": "start",
                "failureMessage": "",
            },
        },
    )

    payload = runtime_service.get_runtime_summary()

    proof = payload["lifecycleProof"]
    source_component = next(component for component in proof["components"] if component["id"] == "source_freshness")
    assert proof["overallState"] == "ready"
    assert source_component["state"] == "failed"
    assert source_component["requiredForOpen"] is False


def test_runtime_lifecycle_proof_does_not_mark_closed_with_active_work_runs(monkeypatch):
    monkeypatch.setattr(runtime_service, "get_active_session_summary", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})
    monkeypatch.setattr(
        runtime_service,
        "_work_run_summary",
        lambda: {
            "active": {
                "chat_turn": {
                    "runId": "turn-live",
                    "runKind": "chat_turn",
                    "status": "running",
                },
                "self_evolution_run": None,
                "supervised_evolution_run": None,
            },
            "latest": {
                "chat_turn": None,
                "self_evolution_run": None,
                "supervised_evolution_run": None,
            },
        },
    )
    monkeypatch.setattr(
        runtime_service,
        "_load_runtime_manager_snapshot",
        lambda: {
            "daemonRunning": False,
            "runtimeState": "idle",
            "managerPid": 0,
            "stateVersion": 17,
            "projectRoot": str(runtime_service.PROJECT_ROOT),
            "workbench": {
                "desiredState": "closed",
                "observedState": "closed",
                "phase": "steady",
                "backendPid": 0,
                "browserWindowPid": 0,
                "browserManaged": True,
                "url": "http://127.0.0.1:8000",
                "lastReason": "web_close_button",
                "failureMessage": "",
            },
        },
    )

    payload = runtime_service.get_runtime_summary()

    proof = payload["lifecycleProof"]
    assert proof["overallState"] == "partial"
    assert proof["activeWorkRuns"]["count"] == 1
    assert proof["activeWorkRuns"]["kinds"] == ["chat_turn"]


def test_runtime_lifecycle_proof_ignores_finished_needs_continue_work_run(monkeypatch):
    monkeypatch.setattr(runtime_service, "get_active_session_summary", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})
    monkeypatch.setattr(runtime_service, "list_active_session_work_runs", lambda: [])
    finished_run = {
        "runId": "turn-needs-continue",
        "runKind": "chat_turn",
        "sessionId": "session-a",
        "status": "needs_continue",
        "currentPhase": "needs_continue",
        "updatedAt": "2026-06-05T11:30:33Z",
        "finishedAt": "2026-06-05T11:30:33Z",
    }
    monkeypatch.setattr(
        runtime_service,
        "_work_run_summary",
        lambda: {
            "active": {
                "chat_turn": finished_run,
                "self_evolution_run": None,
                "supervised_evolution_run": None,
                "supervised_worktree_evolution_run": None,
            },
            "latest": {
                "chat_turn": finished_run,
                "self_evolution_run": None,
                "supervised_evolution_run": None,
                "supervised_worktree_evolution_run": None,
            },
            "activeItems": {
                "chat_turn": [finished_run],
            },
        },
    )
    monkeypatch.setattr(
        runtime_service,
        "_load_runtime_manager_snapshot",
        lambda: {
            "daemonRunning": False,
            "runtimeState": "idle",
            "managerPid": 0,
            "stateVersion": 17,
            "projectRoot": str(runtime_service.PROJECT_ROOT),
            "workbench": {
                "desiredState": "closed",
                "observedState": "closed",
                "phase": "steady",
                "backendPid": 0,
                "browserWindowPid": 0,
                "browserManaged": True,
                "url": "http://127.0.0.1:8000",
                "lastReason": "web_close_button",
                "failureMessage": "",
            },
        },
    )

    payload = runtime_service.get_runtime_summary()

    proof = payload["lifecycleProof"]
    assert proof["overallState"] == "closed"
    assert proof["activeWorkRuns"]["count"] == 0
    assert runtime_service._restart_guard_active_work_runs() == []


def test_runtime_lifecycle_proof_does_not_mark_closed_when_backend_port_is_still_owned(monkeypatch):
    monkeypatch.setattr(runtime_service, "get_active_session_summary", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})
    monkeypatch.setattr(
        runtime_service,
        "_work_run_summary",
        lambda: {
            "active": {
                "chat_turn": None,
                "self_evolution_run": None,
                "supervised_evolution_run": None,
            },
            "latest": {
                "chat_turn": None,
                "self_evolution_run": None,
                "supervised_evolution_run": None,
            },
        },
    )
    monkeypatch.setattr(
        runtime_service,
        "_load_runtime_manager_snapshot",
        lambda: {
            "daemonRunning": True,
            "runtimeState": "running",
            "managerPid": 9912,
            "stateVersion": 18,
            "projectRoot": str(runtime_service.PROJECT_ROOT),
            "runtimeManager": {"sourceMatches": True},
            "workbench": {
                "desiredState": "closed",
                "observedState": "closed",
                "phase": "steady",
                "backendPid": 19964,
                "backendAlive": False,
                "backendHealthy": False,
                "backendObserved": True,
                "backendPort": 8766,
                "backendPortListening": True,
                "backendPortOwnerPid": 52396,
                "backendPortOwnerTrusted": False,
                "backendPortConflict": True,
                "browserWindowPid": 0,
                "browserWindowAlive": False,
                "browserManaged": True,
                "url": "http://127.0.0.1:8766",
                "lastReason": "web_close_button",
                "failureMessage": "",
            },
        },
    )

    payload = runtime_service.get_runtime_summary()

    proof = payload["lifecycleProof"]
    backend_component = next(component for component in proof["components"] if component["id"] == "backend")
    assert proof["overallState"] == "partial"
    assert backend_component["ok"] is False
    assert backend_component["state"] == "closing"
    assert backend_component["pid"] == 19964
    assert "52396" in backend_component["detail"]


def test_runtime_lifecycle_proof_does_not_mark_closed_with_residual_repo_processes(monkeypatch):
    monkeypatch.setattr(runtime_service, "get_active_session_summary", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})
    monkeypatch.setattr(
        runtime_service,
        "_work_run_summary",
        lambda: {
            "active": {
                "chat_turn": None,
                "self_evolution_run": None,
                "supervised_evolution_run": None,
            },
            "latest": {
                "chat_turn": None,
                "self_evolution_run": None,
                "supervised_evolution_run": None,
            },
        },
    )
    monkeypatch.setattr(
        runtime_service,
        "_load_runtime_manager_snapshot",
        lambda: {
            "daemonRunning": False,
            "runtimeState": "idle",
            "managerPid": 0,
            "stateVersion": 19,
            "projectRoot": str(runtime_service.PROJECT_ROOT),
            "runtimeManager": {"sourceMatches": True},
            "workbench": {
                "desiredState": "closed",
                "observedState": "closed",
                "phase": "steady",
                "backendPid": 0,
                "backendAlive": False,
                "backendHealthy": False,
                "backendObserved": False,
                "backendPort": 8766,
                "backendPortListening": False,
                "backendPortOwnerPid": 0,
                "browserWindowPid": 0,
                "browserWindowAlive": False,
                "browserManaged": True,
                "url": "http://127.0.0.1:8766",
                "lastReason": "web_close_button",
                "failureMessage": "",
            },
            "residualProcesses": {
                "count": 1,
                "items": [
                    {
                        "pid": 49780,
                        "parentPid": 0,
                        "kind": "unmanaged_workbench",
                        "name": "python.exe",
                        "commandLine": "python scripts/web_workbench.py --port 8001 --no-browser",
                        "cwd": str(runtime_service.PROJECT_ROOT),
                        "port": 8001,
                    }
                ],
            },
        },
    )

    payload = runtime_service.get_runtime_summary()

    proof = payload["lifecycleProof"]
    residual_component = next(component for component in proof["components"] if component["id"] == "residual_processes")
    assert proof["overallState"] == "partial"
    assert proof["residualProcesses"]["count"] == 1
    assert residual_component["ok"] is False
    assert residual_component["state"] == "running"
    assert residual_component["pid"] == 49780


def test_runtime_lifecycle_proof_detects_unmanaged_frontend_dev_server(monkeypatch):
    monkeypatch.setattr(runtime_service, "get_active_session_summary", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})
    monkeypatch.setattr(
        runtime_service,
        "_work_run_summary",
        lambda: {
            "active": {
                "chat_turn": None,
                "self_evolution_run": None,
                "supervised_evolution_run": None,
            },
            "latest": {
                "chat_turn": None,
                "self_evolution_run": None,
                "supervised_evolution_run": None,
            },
        },
    )
    monkeypatch.setattr(
        runtime_service,
        "_load_runtime_manager_snapshot",
        lambda: {
            "daemonRunning": False,
            "runtimeState": "idle",
            "managerPid": 0,
            "stateVersion": 19,
            "projectRoot": str(runtime_service.PROJECT_ROOT),
            "runtimeManager": {"sourceMatches": True},
            "workbench": {
                "desiredState": "closed",
                "observedState": "closed",
                "phase": "steady",
                "backendPid": 0,
                "backendAlive": False,
                "backendHealthy": False,
                "backendObserved": False,
                "backendPort": 8766,
                "backendPortListening": False,
                "backendPortOwnerPid": 0,
                "browserWindowPid": 0,
                "browserWindowAlive": False,
                "browserManaged": True,
                "url": "http://127.0.0.1:8766",
                "lastReason": "web_close_button",
                "failureMessage": "",
            },
            "residualProcesses": {
                "count": 1,
                "items": [
                    {
                        "pid": 51517,
                        "parentPid": 1,
                        "kind": "unmanaged_frontend_dev_server",
                        "name": "python.exe",
                        "commandLine": "python -m http.server 5173 -d frontend",
                        "cwd": str(runtime_service.PROJECT_ROOT),
                        "port": 5173,
                    }
                ],
            },
        },
    )

    payload = runtime_service.get_runtime_summary()

    proof = payload["lifecycleProof"]
    residual_component = next(component for component in proof["components"] if component["id"] == "residual_processes")
    assert proof["overallState"] == "partial"
    assert proof["residualProcesses"]["count"] == 1
    assert proof["residualProcesses"]["items"][0]["kind"] == "unmanaged_frontend_dev_server"
    assert residual_component["ok"] is False
    assert residual_component["pid"] == 51517
    assert "5173" in residual_component["detail"]


def test_runtime_summary_exposes_tool_call_session_state(monkeypatch):
    monkeypatch.setattr(
        runtime_service,
        "get_active_session_summary",
        lambda: {
            "title": "真实会话",
            "taskSummary": "继续前端开发",
            "currentPhase": "running",
        },
    )
    monkeypatch.setattr(
        runtime_service,
        "_load_runtime_state",
        lambda: {
            "status": "THINKING",
            "runtime_status": "ACTING",
            "last_tool_name": "read_file_tool",
        },
    )

    payload = runtime_service.get_runtime_summary()

    assert payload["sessionState"] == "tooling"
    assert payload["sessionNeedsResponse"] is False
    assert payload["sessionToolName"] == "read_file_tool"
    assert "tool" in payload["sessionStateLine"].lower() or "工具" in payload["sessionStateLine"]


def test_runtime_summary_exposes_thinking_session_state(monkeypatch):
    monkeypatch.setattr(
        runtime_service,
        "get_active_session_summary",
        lambda: {
            "title": "真实会话",
            "taskSummary": "继续前端开发",
            "currentPhase": "running",
        },
    )
    monkeypatch.setattr(
        runtime_service,
        "_load_runtime_state",
        lambda: {
            "status": "THINKING",
            "runtime_status": "WORKING",
            "last_tool_name": "grep_search_tool",
        },
    )

    payload = runtime_service.get_runtime_summary()

    assert payload["sessionState"] == "thinking"
    assert payload["sessionNeedsResponse"] is False
    assert payload["sessionToolName"] == "grep_search_tool"


def test_runtime_summary_exposes_answering_session_state(monkeypatch):
    monkeypatch.setattr(
        runtime_service,
        "get_active_session_summary",
        lambda: {
            "title": "真实会话",
            "taskSummary": "继续前端开发",
            "currentPhase": "running",
        },
    )
    monkeypatch.setattr(
        runtime_service,
        "_load_runtime_state",
        lambda: {
            "status": "WORKING",
            "runtime_status": "WORKING",
            "turn_output_tokens": 64,
            "last_tool_name": "",
        },
    )

    payload = runtime_service.get_runtime_summary()

    assert payload["sessionState"] == "answering"
    assert payload["sessionNeedsResponse"] is False


def test_runtime_summary_treats_stopping_session_as_active(monkeypatch):
    monkeypatch.setattr(
        runtime_service,
        "get_active_session_summary",
        lambda: {
            "title": "真实会话",
            "taskSummary": "正在收束当前轮。",
            "currentPhase": "stopping",
        },
    )
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})

    payload = runtime_service.get_runtime_summary()

    assert payload["status"] == "running"
    assert payload["sessionState"] == "running"
    assert payload["sessionNeedsResponse"] is False


def test_runtime_summary_marks_ready_session_as_needing_response(monkeypatch):
    monkeypatch.setattr(
        runtime_service,
        "get_active_session_summary",
        lambda: {
            "title": "真实会话",
            "taskSummary": "继续前端开发",
            "currentPhase": "ready",
        },
    )
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})

    payload = runtime_service.get_runtime_summary()

    assert payload["sessionState"] == "ready"
    assert payload["sessionNeedsResponse"] is True
    assert "继续" in payload["sessionStateLine"] or "ready" in payload["sessionStateLine"].lower()


def test_runtime_summary_marks_failed_session_as_needing_response(monkeypatch):
    monkeypatch.setattr(
        runtime_service,
        "get_active_session_summary",
        lambda: {
            "title": "真实会话",
            "taskSummary": "测试失败，需要你决定先修测试还是先回退。",
            "currentPhase": "failed",
            "updatedAt": "2026-05-18T20:00:00",
        },
    )
    monkeypatch.setattr(
        runtime_service,
        "_load_runtime_state",
        lambda: {
            "status": "ERROR",
            "runtime_status": "ERROR",
            "updated_at": "2026-05-18T20:00:01",
        },
    )

    payload = runtime_service.get_runtime_summary()

    assert payload["sessionState"] == "failed"
    assert payload["sessionNeedsResponse"] is True
    assert payload["sessionUpdatedAt"] == "2026-05-18T20:00:00"


def test_runtime_summary_ready_session_ignores_stale_runtime_error(monkeypatch):
    monkeypatch.setattr(
        runtime_service,
        "get_active_session_summary",
        lambda: {
            "title": "真实会话",
            "taskSummary": "继续前端开发",
            "currentPhase": "ready",
            "updatedAt": "2026-05-18T20:30:00",
        },
    )
    monkeypatch.setattr(
        runtime_service,
        "_load_runtime_state",
        lambda: {
            "status": "ERROR",
            "runtime_status": "IDLE",
            "updated_at": "2026-05-18T20:29:59",
        },
    )

    payload = runtime_service.get_runtime_summary()

    assert payload["status"] == "success"
    assert payload["sessionState"] == "ready"
    assert payload["sessionNeedsResponse"] is True


def test_runtime_summary_exposes_latest_mental_state(monkeypatch):
    monkeypatch.setattr(runtime_service, "get_active_session_summary", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})

    class DummyMentalModel:
        def get_last_state(self):
            return {
                "mood": "专注",
                "feeling": "规则感知: normal",
                "whisper": "继续推进",
                "timestamp": "2026-05-18T20:00:02",
            }

        def diagnose(self):
            return SimpleNamespace(
                state="normal",
                confidence=0.82,
                metrics={"sample_size": 6, "intervention_count": 1},
                timestamp="2026-05-18T20:00:02",
            )

    monkeypatch.setattr(runtime_service, "get_mental_model", lambda *args, **kwargs: DummyMentalModel())

    payload = runtime_service.get_runtime_summary()

    assert payload["mentalState"]["mood"] == "专注"
    assert payload["mentalState"]["feeling"] == "规则感知: normal"
    assert payload["mentalState"]["whisper"] == "继续推进"
    assert payload["mentalState"]["cognitiveState"] == "normal"
    assert payload["mentalState"]["source"] == "state"
    assert payload["mentalState"]["confidence"] == pytest.approx(0.82)
    assert payload["mentalState"]["sampleSize"] == 6
    assert payload["mentalState"]["updatedAt"] == "2026-05-18T20:00:02"


def test_runtime_summary_reports_disabled_mental_model(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config["mental_model"] = {"enabled": False}

    monkeypatch.setattr(runtime_service, "load_public_config", lambda: copy.deepcopy(public_config))
    monkeypatch.setattr(runtime_service, "get_active_session_summary", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_manager_snapshot", lambda: {})

    payload = runtime_service.get_runtime_summary()

    assert payload["mentalState"]["source"] == "disabled"
    assert "关闭" in payload["mentalState"]["summary"] or "disabled" in payload["mentalState"]["summary"].lower()


def test_runtime_summary_falls_back_to_mental_diagnosis_when_state_is_empty(monkeypatch):
    monkeypatch.setattr(runtime_service, "get_active_session_summary", lambda: {})
    monkeypatch.setattr(runtime_service, "_load_runtime_state", lambda: {})

    class DummyMentalModel:
        def get_last_state(self):
            return {}

        def diagnose(self):
            return SimpleNamespace(
                state="thrashing",
                confidence=0.71,
                metrics={"sample_size": 8, "intervention_count": 3},
                timestamp="2026-05-18T20:00:03",
            )

    monkeypatch.setattr(runtime_service, "get_mental_model", lambda *args, **kwargs: DummyMentalModel())

    payload = runtime_service.get_runtime_summary()

    assert payload["mentalState"]["mood"] == ""
    assert payload["mentalState"]["cognitiveState"] == "thrashing"
    assert payload["mentalState"]["source"] == "diagnosis"
    assert payload["mentalState"]["confidence"] == pytest.approx(0.71)
    assert payload["mentalState"]["sampleSize"] == 8
    assert payload["mentalState"]["updatedAt"] == "2026-05-18T20:00:03"


def test_config_summary_exposes_language():
    response = client.get("/api/config/public")
    assert response.status_code == 200
    payload = response.json()
    assert payload["language"] in {"zh", "en"}


def test_config_summary_exposes_model_labels(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config.setdefault("llm", {})["model_library"] = {
        "gpt_5_5_gpt_5_5": {
            "provider": {"kind": "relay", "api": "openai", "base_url": "https://example.test/v1"},
            "model": "gpt-5.5",
            "label": "gpt-5.5-share",
        },
        "raw_model": {
            "provider": {"kind": "relay", "api": "openai", "base_url": "https://example.test/v1"},
            "model": "raw-model",
        },
    }

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.get("/api/config/public")

    assert response.status_code == 200
    payload = response.json()
    assert payload["modelLabels"]["gpt_5_5_gpt_5_5"] == "gpt-5.5-share"
    assert payload["modelLabels"]["raw_model"] == "raw-model"


def test_config_workspace_exposes_unified_config_payload(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config.setdefault("ui", {})["language"] = "en"

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.get("/api/config/workspace")

    assert response.status_code == 200
    payload = response.json()
    assert payload["language"] == "en"
    assert payload["publicConfig"]["ui"]["language"] == "en"
    assert "rawToml" in payload
    assert "diagnosis" in payload
    preset_options = {item["preset_id"]: item for item in payload["modelPresetOptions"]}
    relay_preset = preset_options["relay_openai_gpt_5_5"]
    assert relay_preset["category"] == "relay"
    assert relay_preset["provider"]["kind"] == "relay"
    assert relay_preset["provider"]["base_url"] == "https://pixel.try-chatapi.com/v1"
    assert relay_preset["model"]["transport"] == "responses"
    assert relay_preset["model"]["contract"] == "tool_chat"
    image2_preset = preset_options["relay_image2"]
    assert image2_preset["category"] == "relay"
    assert image2_preset["provider"]["kind"] == "relay"
    assert image2_preset["provider"]["base_url"] == "https://ai-pixel.online"
    assert not image2_preset["provider"]["base_url"].endswith("/v1")
    assert image2_preset["model"]["model"] == "image2"
    assert image2_preset["model"]["streaming"] is False
    assert image2_preset["model"]["tool_calling_mode"] == "disabled"
    assert preset_options["custom_openai_compatible_relay"]["category"] == "openai_compatible"
    assert preset_options["custom_openai_compatible_relay"]["provider"]["kind"] == "openai_compatible"
    assert preset_options["custom_relay_responses"]["category"] == "relay"
    assert preset_options["custom_relay_responses"]["model"]["transport"] == "responses"
    assert preset_options["xiaomi_mimo_v2_5_pro_token_plan"]["category"] == "official"
    assert preset_options["xiaomi_mimo_v2_5_pro_token_plan"]["provider"]["kind"] == "xiaomi"
    assert preset_options["xiaomi_mimo_v2_5_pro_token_plan"]["provider"]["base_url"] == (
        "https://token-plan-cn.xiaomimimo.com/v1"
    )
    assert preset_options["xiaomi_mimo_v2_5_pro_token_plan"]["model"]["model"] == "mimo-v2.5-pro"
    assert preset_options["xiaomi_mimo_v2_5_multimodal"]["category"] == "official"
    assert preset_options["xiaomi_mimo_v2_5_multimodal"]["provider"]["kind"] == "xiaomi"
    assert preset_options["xiaomi_mimo_v2_5_multimodal"]["provider"]["base_url"] == "https://api.xiaomimimo.com/v1"
    assert preset_options["xiaomi_mimo_v2_5_multimodal"]["model"]["model"] == "mimo-v2.5"
    assert preset_options["xiaomi_mimo_v2_5_multimodal"]["model"]["supports_image_input"] is True
    assert preset_options["deepseek_v4_pro"]["model"]["supports_image_input"] is False
    assert preset_options["deepseek_v4_pro"]["model"]["capability_status"] == "unsupported"
    assert preset_options["deepseek_v4_flash"]["model"]["supports_image_input"] is False
    assert preset_options["deepseek_v4_flash"]["model"]["capability_status"] == "unsupported"
    provider_options = {item["provider_preset_id"]: item for item in payload["providerPresetOptions"]}
    assert provider_options["openai_main"]["vendor_label"] == "OpenAI"
    assert provider_options["openai_main"]["label"] == "OpenAI 官方 API"
    assert provider_options["openai_main"]["provider"]["kind"] == "openai"
    assert provider_options["xiaomi_mimo_token_plan_cn"]["vendor_label"] == "小米 MiMo"
    assert provider_options["xiaomi_mimo_token_plan_cn"]["label"] == "MiMo Token Plan CN"
    assert provider_options["xiaomi_mimo_api_cn"]["label"] == "MiMo 官方 API CN"
    assert provider_options["relay_openai"]["vendor_label"] == "中转站 / Relay"
    assert len([item for item in payload["providerPresetOptions"] if item["provider_preset_id"] == "openai_main"]) == 1
    assert "modelOptions" in payload
    assert "profileCards" not in payload
    assert "profileCount" not in payload


def test_config_workspace_exposes_editor_schema_without_launcher_owned_startup_settings(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.get("/api/config/workspace")

    assert response.status_code == 200
    payload = response.json()
    editor_sections = {section["id"]: section for section in payload["editorSections"]}
    editor_meta = payload["editorMeta"]

    assert "runtime" not in editor_sections
    assert "workbench" not in editor_sections
    assert "tools" not in editor_sections
    assert "context-compression" in editor_sections
    assert "analysis" in editor_sections
    assert "prompt" not in editor_sections
    assert "llm-profiles" not in editor_sections
    assert "agent" not in editor_sections
    assert "evolution" not in editor_sections
    assert "memory" not in editor_sections
    assert "strategy" not in editor_sections
    sections_by_id = {section["id"]: section for section in payload["sections"]}
    assert "runtime" not in sections_by_id
    assert "workbench" not in sections_by_id
    assert "profiles" not in sections_by_id
    assert sections_by_id["models"]["title"] == "模型库"
    assert "模型资产" in sections_by_id["models"]["summary"]
    assert sections_by_id["draft"]["title"] == "高级配置检查"
    assert "JSON" not in sections_by_id["draft"]["title"]
    assert "JSON" not in sections_by_id["draft"]["summary"]
    assert "草稿" not in sections_by_id["draft"]["summary"]
    assert editor_sections["context-compression"]["title"] == "上下文压缩"
    assert "git" not in editor_sections
    assert editor_sections["git-commit-model"]["path"] == "git.commit_message_model_ref"
    assert editor_sections["git-commit-model"]["title"] == "Git 提交模型"
    assert editor_sections["git-commit-model"]["fieldCount"] == 1
    assert editor_sections["git-commit-prompt"]["path"] == "git.commit_message_prompt"
    assert editor_sections["git-commit-prompt"]["title"] == "Git 提交提示词"
    assert editor_sections["git-commit-prompt"]["fieldCount"] == 1
    assert "user-profile" in editor_sections
    assert editor_sections["user-profile"]["path"] == "user_profile"
    assert editor_sections["user-profile"]["title"] == "用户信息"
    assert payload["publicConfig"]["runtime"] == public_config["runtime"]
    assert payload["publicConfig"]["workbench"] == public_config["workbench"]
    assert "runtime.profile" not in editor_meta
    assert "runtime.preflight_doctor" not in editor_meta
    assert "runtime.require_venv" not in editor_meta
    assert "workbench.backend_port" not in editor_meta
    assert "workbench.frontend_port" not in editor_meta
    assert "workbench.window_mode" not in editor_meta
    assert editor_meta["user_profile.display_name"]["kind"] == "text"
    assert editor_meta["user_profile.display_name"]["label"] == "用户显示名"
    assert editor_meta["user_profile.bio"]["kind"] == "multiline"
    assert editor_meta["user_profile.preferences"]["kind"] == "string_list"
    assert editor_meta["user_profile.avatar_preset"]["kind"] == "select"
    assert editor_meta["user_profile.avatar_preset"]["options"]
    assert editor_meta["user_profile.avatar_image_path"]["kind"] == "image"
    assert "本地图片" in editor_meta["user_profile.avatar_image_path"]["hint"]
    assert editor_meta["network.proxy_enabled"]["kind"] == "boolean"
    assert editor_meta["network.proxy_enabled"]["label"] == "启用代理"
    assert editor_meta["network.proxy_url"]["kind"] == "url"
    assert editor_meta["network.proxy_url"]["label"] == "代理地址"
    assert "科研调研" in editor_meta["network.proxy_enabled"]["hint"]
    assert "tools.file.editable_extensions" not in editor_meta
    assert "tools.image2.default_model_ref" not in editor_meta
    assert "prompt.sections" not in editor_meta
    assert "llm.profiles.primary.model_ref" not in editor_meta
    assert "llm.profiles.primary.provider.kind" not in editor_meta
    assert "llm.profiles.primary.provider.base_url" not in editor_meta
    assert "commit_message_profile" not in payload["publicConfig"]["git"]
    assert "commit_message_model_ref" in payload["publicConfig"]["git"]
    assert "{diff}" in payload["publicConfig"]["git"]["commit_message_prompt"]
    assert editor_meta["git.commit_message_model_ref"]["kind"] == "select"
    assert editor_meta["git.commit_message_model_ref"]["label"] == "Git 提交使用的模型"
    assert "profile" not in editor_meta["git.commit_message_model_ref"]["hint"].lower()
    assert editor_meta["git.commit_message_prompt"]["kind"] == "multiline"
    assert "系统提示词模板" in editor_meta["git.commit_message_prompt"]["hint"]
    assert sections_by_id["health-diagnostics"]["title"] == "健康诊断"
    assert any(section["id"] == "overview" for section in payload["sections"])
    assert any(section["id"] == "shell" for section in payload["sections"])


def test_config_avatar_image_upload_stores_safe_project_file(monkeypatch, tmp_path):
    monkeypatch.setattr(avatar_image_service, "USER_AVATAR_DIR", tmp_path / "user_avatars")
    png_payload = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16

    response = client.post(
        "/api/config/avatar-image",
        json={
            "filename": "my avatar.png",
            "contentType": "image/png",
            "dataBase64": base64.b64encode(png_payload).decode("ascii"),
        },
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["path"].startswith("workspace/user_avatars/avatar-")
    assert payload["path"].endswith(".png")
    assert payload["url"].startswith("/api/config/avatar-image/avatar-")
    saved_files = list((tmp_path / "user_avatars").glob("*.png"))
    assert len(saved_files) == 1
    assert saved_files[0].read_bytes() == png_payload

    image_response = client.get(payload["url"])
    assert image_response.status_code == 200
    assert image_response.headers["content-type"].startswith("image/png")
    assert image_response.content == png_payload


def test_config_avatar_image_upload_rejects_disguised_image(monkeypatch, tmp_path):
    monkeypatch.setattr(avatar_image_service, "USER_AVATAR_DIR", tmp_path / "user_avatars")

    response = client.post(
        "/api/config/avatar-image",
        json={
            "filename": "not-image.png",
            "contentType": "image/png",
            "dataBase64": base64.b64encode(b"not a png").decode("ascii"),
        },
    )

    assert response.status_code == 422
    assert not (tmp_path / "user_avatars").exists()


def test_config_avatar_image_upload_rejects_oversized_image(monkeypatch, tmp_path):
    monkeypatch.setattr(avatar_image_service, "USER_AVATAR_DIR", tmp_path / "user_avatars")
    monkeypatch.setattr(avatar_image_service, "MAX_USER_AVATAR_IMAGE_BYTES", 8)

    response = client.post(
        "/api/config/avatar-image",
        json={
            "filename": "avatar.png",
            "contentType": "image/png",
            "dataBase64": base64.b64encode(b"\x89PNG\r\n\x1a\nextra").decode("ascii"),
        },
    )

    assert response.status_code == 422
    assert not (tmp_path / "user_avatars").exists()


def test_health_diagnostics_endpoint_returns_log_helpers(tmp_path, monkeypatch):
    _seed_chat_state(tmp_path, task_status="done")
    runtime_log = tmp_path / "logs" / "agent_realtime.log"
    runtime_log.parent.mkdir(parents=True, exist_ok=True)
    runtime_log.write_text("runtime line\n", encoding="utf-8")
    conversation_log = tmp_path / "log_info" / "conversation_debug.jsonl"
    conversation_log.parent.mkdir(parents=True, exist_ok=True)
    conversation_log.write_text('{"type":"external_request"}\n', encoding="utf-8")

    _seed_runtime_scene_bundle(tmp_path, scene_id="scene-health", status="failed")
    monkeypatch.setattr(log_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runtime_scene_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    response = client.get("/api/diagnostics/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "blocked"
    session_helpers = {item["id"]: item for item in payload["sessionHelpers"]}
    assert session_helpers["chat_sessions"]["sessionCount"] == 1
    assert session_helpers["chat_sessions"]["activeSessionId"] == "session-live"
    assert session_helpers["chat_sessions"]["route"] == "/chat?session=session-live"
    assert session_helpers["chat_sessions"]["protected"] is True
    helpers = {item["id"]: item for item in payload["logHelpers"]}
    assert set(helpers) == {"runtime_scenes", "runtime_logs", "workspace_logs", "conversation_logs"}
    assert helpers["runtime_scenes"]["route"] == "/logs?root=runtime_scenes"
    assert helpers["runtime_scenes"]["resetItemId"] == "stopped_runtime_scenes"
    assert helpers["runtime_scenes"]["protected"] is True
    assert helpers["runtime_logs"]["route"] == "/logs?root=runtime_logs"
    assert helpers["conversation_logs"]["resetItemId"] == "conversation_logs"
    assert helpers["workspace_logs"]["status"] == "warning"
    assert payload["findings"][0]["id"] == "runtime_scene_failed"
    assert payload["findings"][0]["severity"] == "blocked"
    assert payload["findings"][0]["route"] == "/logs?root=runtime_scenes"
    assert helpers["runtime_scenes"]["primaryFindingId"] == "runtime_scene_failed"
    assert any(item["source"] == "reset" and item["protected"] is True for item in payload["findings"])
    assert payload["quickActions"][0]["findingId"] == "runtime_scene_failed"
    assert any(item["resetItemId"] == "stopped_runtime_scenes" for item in payload["quickActions"])


def test_config_workspace_surfaces_llm_security_diagnostics_without_blocking_read(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config["llm"]["profiles"]["primary"]["provider"] = {
        "kind": "openai",
        "api_key_env": "OPENAI_API_KEY",
        "base_url": "file:///C:/Windows/win.ini",
        "compat_mode": "openai",
        "requires_api_key": True,
        "context_window": 100000,
    }

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.get("/api/config/workspace")

    assert response.status_code == 200
    payload = response.json()
    assert payload["blockingCount"] >= 1
    assert any("LLM security guard" in item for item in payload["diagnosis"]["blocking_issues"])


def test_config_workspace_draft_delete_model_rejects_primary_profile_model(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config["llm"]["profiles"]["primary"] = {
        "model_ref": "relay_openai_gpt_5_5",
        "overrides": {},
    }
    scene_events = []

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))
    monkeypatch.setattr(
        config_service,
        "_record_config_scene_event",
        lambda phase, event_code, **kwargs: scene_events.append((phase, event_code, kwargs)),
    )

    response = client.post(
        "/api/config/draft/delete-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "modelId": "relay_openai_gpt_5_5",
        },
    )

    assert response.status_code == 422
    assert "primary" in response.json()["detail"]
    assert scene_events[-1][1] == "config.llm_model.delete_rejected"
    assert scene_events[-1][2]["fields"]["reason"] == "primary_profile_ref"


def test_config_workspace_draft_delete_model_rejects_git_commit_model(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config.setdefault("git", {})["commit_message_model_ref"] = "relay_openai_gpt_5_5"
    scene_events = []

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))
    monkeypatch.setattr(
        config_service,
        "_record_config_scene_event",
        lambda phase, event_code, **kwargs: scene_events.append((phase, event_code, kwargs)),
    )

    response = client.post(
        "/api/config/draft/delete-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "modelId": "relay_openai_gpt_5_5",
        },
    )

    assert response.status_code == 422
    assert "Git commit" in response.json()["detail"]
    assert scene_events[-1][1] == "config.llm_model.delete_rejected"
    assert scene_events[-1][2]["fields"]["reason"] == "git_commit_model_ref"


def test_config_workspace_apply_allows_deleted_non_primary_profile_model(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    _ensure_preset_model(public_config, "deepseek_v4_pro")
    public_config["llm"]["profiles"]["primary"] = {
        "model_ref": "deepseek_v4_pro",
        "overrides": {},
    }
    public_config["llm"]["profiles"]["mental_model"] = {
        "model_ref": "relay_openai_gpt_5_5",
        "overrides": {},
    }

    saved_configs = []
    scene_events = []
    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))
    monkeypatch.setattr(config_service, "save_public_config", lambda payload: saved_configs.append(copy.deepcopy(payload)))
    monkeypatch.setattr(config_service, "reload_config", lambda path: config_service.build_effective_config(saved_configs[-1]))
    monkeypatch.setattr(
        config_service,
        "_record_config_scene_event",
        lambda phase, event_code, **kwargs: scene_events.append((phase, event_code, kwargs)),
    )

    delete_response = client.post(
        "/api/config/draft/delete-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "modelId": "relay_openai_gpt_5_5",
        },
    )

    assert delete_response.status_code == 200, delete_response.json()
    draft_payload = delete_response.json()
    assert draft_payload["publicConfig"]["llm"]["profiles"]["mental_model"]["model_ref"] == UNCONFIGURED_MODEL_REF

    apply_response = client.put(
        "/api/config/apply",
        json={
            "publicConfig": draft_payload["publicConfig"],
            "draftMeta": draft_payload["draftMeta"],
            "baseHash": public_config_hash(public_config),
        },
    )

    assert apply_response.status_code == 200, apply_response.json()
    assert saved_configs
    assert "relay_openai_gpt_5_5" not in saved_configs[-1]["llm"]["model_library"]
    assert any(event_code == "config.llm_profiles.optional_missing_allowed" for _, event_code, _ in scene_events)


def test_config_open_environment_opens_system_ui_without_returning_keys(monkeypatch):
    launched_commands = []
    focused_windows = []

    def fake_run(command, **kwargs):
        launched_commands.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(config_service.os, "name", "nt")
    monkeypatch.setattr(config_service.subprocess, "run", fake_run)
    monkeypatch.setattr(config_service, "_focus_environment_variables_window", lambda: focused_windows.append("focused") or True)
    monkeypatch.setenv("VIBELUTION_SECRET_TEST_KEY", "should-not-leak")

    response = client.post("/api/config/open-environment", json={})

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["opened"] is True
    assert payload["method"] == "interactive-scheduled-task"
    assert payload["focused"] is True
    assert payload["cleanup_ok"] is True
    assert payload["cleanup_error"] is None
    assert launched_commands
    assert focused_windows == ["focused"]
    assert [command[0][1] for command in launched_commands] == ["/Delete", "/Create", "/Run", "/Delete"]
    create_command = launched_commands[1][0]
    assert "/IT" in create_command
    assert "rundll32.exe sysdm.cpl,EditEnvironmentVariables" in create_command
    assert "should-not-leak" not in response.text
    assert "VIBELUTION_SECRET_TEST_KEY" not in response.text


def test_config_open_environment_reports_cleanup_failure(monkeypatch):
    launched_commands = []

    def fake_run(command, **kwargs):
        launched_commands.append(command)
        if command[1] == "/Delete" and len(launched_commands) == 4:
            return SimpleNamespace(returncode=1, stdout="", stderr="delete denied")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(config_service.os, "name", "nt")
    monkeypatch.setattr(config_service.subprocess, "run", fake_run)
    monkeypatch.setattr(config_service, "_focus_environment_variables_window", lambda: True)

    response = client.post("/api/config/open-environment", json={})

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["opened"] is True
    assert payload["cleanup_ok"] is False
    assert payload["cleanup_error"] == "delete denied"


def test_config_open_environment_reports_unsupported_platform(monkeypatch):
    monkeypatch.setattr(config_service.os, "name", "posix")

    response = client.post("/api/config/open-environment", json={})

    assert response.status_code == 422
    assert "Windows" in response.json()["detail"]


def test_config_open_environment_reports_launch_failure(monkeypatch):
    def fake_run(command, **kwargs):
        if command[1] == "/Create":
            return SimpleNamespace(returncode=1, stdout="", stderr="blocked")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(config_service.os, "name", "nt")
    monkeypatch.setattr(config_service.subprocess, "run", fake_run)

    response = client.post("/api/config/open-environment", json={})

    assert response.status_code == 422
    assert "无法打开系统环境变量窗口" in response.json()["detail"]


def test_config_open_environment_focuses_detected_window(monkeypatch):
    focused_handles = []

    monkeypatch.setattr(config_service.os, "name", "nt")
    monkeypatch.setattr(config_service, "_find_environment_variables_window", lambda: 12345)
    monkeypatch.setattr(config_service, "_focus_window", lambda hwnd: focused_handles.append(hwnd) or True)

    assert config_service._focus_environment_variables_window(timeout_seconds=0.01) is True
    assert focused_handles == [12345]


def test_config_open_environment_promotes_window_when_foreground_is_blocked(monkeypatch):
    calls = []

    class FakeUser32:
        def GetForegroundWindow(self):
            return 0

        def GetWindowThreadProcessId(self, hwnd, process_id):
            return 222 if hwnd == 12345 else 0

        def AttachThreadInput(self, current_thread, target_thread, attach):
            calls.append(("AttachThreadInput", current_thread, target_thread, attach))
            return True

        def ShowWindow(self, hwnd, mode):
            calls.append(("ShowWindow", hwnd, mode))
            return True

        def BringWindowToTop(self, hwnd):
            calls.append(("BringWindowToTop", hwnd))
            return True

        def SetActiveWindow(self, hwnd):
            calls.append(("SetActiveWindow", hwnd))
            return hwnd

        def SetFocus(self, hwnd):
            calls.append(("SetFocus", hwnd))
            return hwnd

        def SetForegroundWindow(self, hwnd):
            calls.append(("SetForegroundWindow", hwnd))
            return False

        def SwitchToThisWindow(self, hwnd, alt_tab):
            calls.append(("SwitchToThisWindow", hwnd, alt_tab))
            return None

        def SetWindowPos(self, hwnd, insert_after, x, y, cx, cy, flags):
            calls.append(("SetWindowPos", hwnd, insert_after, flags))
            return True

    class FakeKernel32:
        def GetCurrentThreadId(self):
            return 111

    monkeypatch.setattr(
        config_service.ctypes,
        "windll",
        SimpleNamespace(user32=FakeUser32(), kernel32=FakeKernel32()),
        raising=False,
    )

    assert config_service._focus_window(12345) is False
    assert ("AttachThreadInput", 111, 222, True) in calls
    assert ("AttachThreadInput", 111, 222, False) in calls
    assert ("SetWindowPos", 12345, config_service._HWND_TOPMOST, config_service._SWP_NOMOVE | config_service._SWP_NOSIZE | config_service._SWP_SHOWWINDOW) in calls
    assert ("SetWindowPos", 12345, config_service._HWND_NOTOPMOST, config_service._SWP_NOMOVE | config_service._SWP_NOSIZE | config_service._SWP_SHOWWINDOW) in calls


def test_config_workspace_test_llm_uses_pending_draft_key(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    _ensure_preset_model(public_config, "deepseek_v4_pro")
    deepseek_env = public_config["llm"]["model_library"]["deepseek_v4_pro"]["api_key_env"]
    public_config["llm"]["profiles"]["subagent_explorer"] = {
        "model_ref": "deepseek_v4_pro",
        "overrides": {},
    }
    monkeypatch.delenv("VIBELUTION_LLM_DEEPSEEK_V4_PRO_API_KEY", raising=False)
    monkeypatch.delenv(deepseek_env, raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("VIBELUTION_LLM_MODEL_RELAY_OPENAI_GPT_5_5_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    def fake_runtime_probe(provider, profile, api_key=None):
        assert api_key == "draft-secret"
        return {"ok": True, "message": "ok", "runtime_route": f"{profile.transport}:{profile.model}"}

    monkeypatch.setattr("config.public_config._probe_llm_runtime", fake_runtime_probe)

    draft_response = client.post(
        "/api/config/draft/update-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "modelId": "deepseek_v4_pro",
            "provider": public_config["llm"]["model_library"]["deepseek_v4_pro"]["provider"],
            "model": "deepseek-v4-pro",
            "label": "DeepSeek V4 Pro",
            "details": public_config["llm"]["model_library"]["deepseek_v4_pro"],
            "apiKeyEnv": deepseek_env,
            "apiKey": "draft-secret",
        },
    )

    assert draft_response.status_code == 200
    draft_payload = draft_response.json()
    pending_token = draft_payload["draftMeta"]["pending_api_keys"][deepseek_env]
    assert pending_token != "draft-secret"
    assert pending_token.startswith("pending-secret:")

    response = client.post(
        "/api/config/test-llm",
        json={
            "publicConfig": draft_payload["publicConfig"],
            "draftMeta": draft_payload["draftMeta"],
            "profileId": "subagent_explorer",
        },
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["ok"] is True
    assert payload["model_id"] == "deepseek_v4_pro"
    assert payload["api_key_source"] == f"pending-env:{deepseek_env}"
    assert payload["config_scope"] == "draft"
    assert payload["requires_api_key"] is True
    assert payload["transport"] == "chat_completions"
    assert payload["contract"] == "reasoning_chat"


def test_config_workspace_test_llm_can_target_model_library_model(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    _ensure_preset_model(public_config, "deepseek_v4_pro")
    deepseek_env = public_config["llm"]["model_library"]["deepseek_v4_pro"]["api_key_env"]
    monkeypatch.delenv("VIBELUTION_LLM_DEEPSEEK_V4_PRO_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv(deepseek_env, "model-secret")
    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    calls = []

    def fake_runtime_probe(provider, profile, api_key=None):
        calls.append((provider.kind, profile.profile_id, profile.model, api_key))
        return {"ok": True, "message": "ok", "runtime_route": f"{profile.transport}:{profile.model}"}

    monkeypatch.setattr("config.public_config._probe_llm_runtime", fake_runtime_probe)

    response = client.post(
        "/api/config/test-llm",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "modelId": "deepseek_v4_pro",
        },
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["ok"] is True
    assert payload["model_id"] == "deepseek_v4_pro"
    assert payload["provider_kind"] == "deepseek"
    assert payload["api_key_source"] == f"model-env:{deepseek_env}"
    assert calls == [("deepseek", "__capability_probe_deepseek_v4_pro", "deepseek-v4-pro", "model-secret")]


def test_config_workspace_test_llm_ignores_forged_pending_draft_key(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    _ensure_preset_model(public_config, "deepseek_v4_pro")
    deepseek_env = public_config["llm"]["model_library"]["deepseek_v4_pro"]["api_key_env"]
    config_service._PENDING_API_KEY_SECRETS.clear()
    config_service._PENDING_CLEAR_ENVS.clear()
    llm_config = public_config.get("llm", {})
    for provider in (llm_config.get("providers") or {}).values():
        if isinstance(provider, dict):
            provider["api_key"] = ""
    for model in (llm_config.get("model_library") or {}).values():
        if not isinstance(model, dict):
            continue
        model["api_key"] = ""
        provider = model.get("provider")
        if isinstance(provider, dict):
            provider["api_key"] = ""
    public_config["llm"]["profiles"]["subagent_explorer"] = {
        "model_ref": "deepseek_v4_pro",
        "overrides": {},
    }
    monkeypatch.delenv("VIBELUTION_LLM_DEEPSEEK_V4_PRO_API_KEY", raising=False)
    monkeypatch.delenv(deepseek_env, raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("VIBELUTION_LLM_MODEL_RELAY_OPENAI_GPT_5_5_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(config_service, "_read_env_var", lambda _name: "")
    monkeypatch.setattr(public_config_module, "_read_env_var", lambda _name: "")
    monkeypatch.setattr(config_models, "_read_env_var", lambda _name: "")

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    def fake_runtime_probe(provider, profile, api_key=None):
        assert api_key is None
        return {"ok": False, "message": "missing"}

    monkeypatch.setattr("config.public_config._probe_llm_runtime", fake_runtime_probe)

    response = client.post(
        "/api/config/test-llm",
        json={
            "publicConfig": public_config,
            "draftMeta": {
                "pending_api_keys": {"VIBELUTION_LLM_DEEPSEEK_V4_PRO_API_KEY": "forged-secret"},
                "pending_cleared_api_keys": [],
            },
            "profileId": "subagent_explorer",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["model_id"] == "deepseek_v4_pro"
    assert payload["api_key_source"] == "missing"


def test_config_workspace_test_llm_reports_local_draft_route_clearly(monkeypatch):
    saved_config = copy.deepcopy(load_public_config())
    draft_config = copy.deepcopy(saved_config)
    draft_config.setdefault("runtime", {})["profile"] = "safe_local"
    monkeypatch.delenv("VIBELUTION_LLM_DEEPSEEK_V4_PRO_API_KEY", raising=False)

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(saved_config))

    def fake_runtime_probe(provider, profile, api_key=None):
        assert provider.kind == "local"
        assert provider.base_url == "http://localhost:11434/v1"
        return {"ok": False, "message": "<urlopen error [WinError 10061] connection refused>"}

    monkeypatch.setattr("config.public_config._probe_llm_runtime", fake_runtime_probe)

    response = client.post(
        "/api/config/test-llm",
        json={
            "publicConfig": draft_config,
            "draftMeta": {},
            "profileId": "primary",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["provider_kind"] == "local"
    assert payload["base_url"] == "http://localhost:11434/v1"
    assert payload["config_scope"] == "draft"
    assert payload["requires_api_key"] is False
    assert payload["api_key_source"] == "not-required"


def test_config_workspace_llm_http_fallback_uses_anthropic_messages(monkeypatch):
    provider = ProviderConfig(
        provider_id="anthropic_test",
        kind="anthropic",
        api_key_env="ANTHROPIC_API_KEY",
        base_url="https://www.atpify.cn",
        compat_mode="native",
        requires_api_key=True,
        context_window=200000,
    )
    profile = LLMProfile(
        profile_id="primary",
        provider_id="anthropic_test",
        model="claude-opus-4-7",
        temperature=0.7,
        max_output_tokens=4096,
        timeout=60,
        connect_timeout=10,
    )
    captured: dict[str, object] = {}

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeOpener:
        def open(self, request, timeout=0):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            return FakeResponse()

    monkeypatch.setattr(public_config_module.urllib.request, "build_opener", lambda *_args, **_kwargs: FakeOpener())

    result = public_config_module._probe_llm_http(provider, profile, "anthropic-secret")

    assert result["ok"] is True
    assert captured["url"] == "https://www.atpify.cn/v1/messages"
    assert captured["payload"]["model"] == "claude-opus-4-7"
    assert "temperature" not in captured["payload"]
    assert captured["headers"]["Anthropic-version"] == "2023-06-01"
    assert captured["headers"]["X-api-key"] == "anthropic-secret"


def test_config_workspace_llm_http_fallback_uses_primary_openai_chat_completion(monkeypatch):
    provider = ProviderConfig(
        provider_id="primary",
        kind="xiaomi",
        api_key_env="XIAOMI_API_KEY",
        base_url="https://token-plan-cn.xiaomimimo.com/v1",
        compat_mode="openai",
        requires_api_key=True,
    )
    profile = LLMProfile(
        profile_id="primary",
        provider_id="primary",
        model="mimo-v2.5",
        transport="chat_completions",
        contract="tool_chat",
        temperature=0.7,
    )
    captured: dict[str, object] = {}

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeOpener:
        def open(self, request, timeout=0):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            return FakeResponse()

    monkeypatch.setattr(public_config_module.urllib.request, "build_opener", lambda *_args, **_kwargs: FakeOpener())

    result = public_config_module._probe_llm_http(provider, profile, "token-plan-secret")

    assert result["ok"] is True
    assert captured["url"] == "https://token-plan-cn.xiaomimimo.com/v1/chat/completions"
    assert captured["payload"]["model"] == "mimo-v2.5"
    assert captured["payload"]["temperature"] == profile.temperature
    assert captured["headers"]["Authorization"] == "Bearer token-plan-secret"


def test_config_workspace_test_llm_rejects_metadata_service_base_url(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    target = public_config["llm"]["profiles"]["primary"]
    target["provider"] = {
        "kind": "openai",
        "api_key_env": "OPENAI_API_KEY",
        "base_url": "http://169.254.169.254/v1",
        "compat_mode": "openai",
        "requires_api_key": True,
        "context_window": 100000,
    }
    target["model"] = "gpt-5.5"

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(load_public_config()))

    response = client.post(
        "/api/config/test-llm",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "profileId": "primary",
        },
    )

    assert response.status_code == 422
    assert "base_url" in response.json()["detail"]


def test_config_workspace_test_llm_rejects_file_base_url(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    target = public_config["llm"]["profiles"]["primary"]
    target["provider"] = {
        "kind": "openai",
        "api_key_env": "OPENAI_API_KEY",
        "base_url": "file:///C:/Windows/win.ini",
        "compat_mode": "openai",
        "requires_api_key": True,
        "context_window": 100000,
    }
    target["model"] = "gpt-5.5"

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(load_public_config()))

    response = client.post(
        "/api/config/test-llm",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "profileId": "primary",
        },
    )

    assert response.status_code == 422
    assert "http(s)" in response.json()["detail"]


def test_config_workspace_test_llm_allows_localhost_for_local_provider(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config.setdefault("llm", {}).setdefault("model_library", {})["local_loopback_model"] = {
        "provider": {
            "kind": "local",
            "api_key_env": "",
            "base_url": "http://127.0.0.1:11434/v1",
            "compat_mode": "openai",
            "requires_api_key": False,
            "context_window": 65536,
        },
        "model": "llama3.2",
        "label": "Local Loopback Model",
    }
    public_config.setdefault("llm", {}).setdefault("profiles", {}).setdefault("primary", {})["model_ref"] = "local_loopback_model"

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(load_public_config()))

    def fake_runtime_probe(provider, profile, api_key=None):
        assert provider.kind in {"local", "llamacpp"}
        assert provider.base_url.startswith("http://")
        assert api_key is None
        return {"ok": True, "message": "local-ok"}

    monkeypatch.setattr("config.public_config._probe_llm_runtime", fake_runtime_probe)

    response = client.post(
        "/api/config/test-llm",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "profileId": "primary",
        },
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["ok"] is True
    assert payload["provider_kind"] in {"local", "llamacpp"}


def test_config_workspace_test_llm_allows_private_lan_local_model(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config.setdefault("llm", {}).setdefault("model_library", {})["lan_local_model"] = {
        "provider": {
            "kind": "local",
            "api_key_env": "",
            "base_url": "http://192.168.20.46:8081/v1",
            "compat_mode": "openai",
            "requires_api_key": False,
            "context_window": 65536,
        },
        "model": "qwen-local",
        "label": "LAN Local Model",
    }
    public_config.setdefault("llm", {}).setdefault("profiles", {}).setdefault("primary", {})["model_ref"] = "lan_local_model"

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(load_public_config()))

    def fake_runtime_probe(provider, profile, api_key=None):
        assert provider.kind == "local"
        assert provider.base_url == "http://192.168.20.46:8081/v1"
        assert api_key is None
        return {"ok": True, "message": "lan-local-ok"}

    monkeypatch.setattr("config.public_config._probe_llm_runtime", fake_runtime_probe)

    response = client.post(
        "/api/config/test-llm",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "profileId": "primary",
        },
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["ok"] is True
    assert payload["provider_kind"] == "local"
    assert payload["base_url"] == "http://192.168.20.46:8081/v1"
    assert payload["api_key_source"] == "not-required"


def test_config_workspace_test_llm_extends_private_lan_local_probe_timeout():
    provider = ProviderConfig(
        provider_id="local_model_server_b",
        kind="local",
        api_key_env="VIBELUTION_LLM_MODEL_LOCAL_MODEL_SERVER_B_API_KEY",
        base_url="http://192.168.20.63:8000/v1",
        compat_mode="openai",
        requires_api_key=True,
        context_window=128000,
    )
    profile = LLMProfile(
        profile_id="__capability_probe_local_model_server_b",
        provider_id="local_model_server_b",
        model="Qwen3-32B-AWQ",
        temperature=0.3,
        max_output_tokens=4096,
        timeout=120,
        connect_timeout=20,
    )

    assert config_service._llm_test_probe_timeout_seconds(provider, profile) == 30


def test_config_workspace_test_llm_keeps_remote_probe_timeout_short():
    provider = ProviderConfig(
        provider_id="deepseek",
        kind="deepseek",
        api_key_env="DEEPSEEK_API_KEY",
        base_url="https://api.deepseek.com",
        compat_mode="native",
        requires_api_key=True,
        context_window=65536,
    )
    profile = LLMProfile(
        profile_id="primary",
        provider_id="deepseek",
        model="deepseek-v4-pro",
        temperature=0.3,
        max_output_tokens=4096,
        timeout=120,
        connect_timeout=20,
    )

    assert config_service._llm_test_probe_timeout_seconds(provider, profile) == 10


def test_config_image_input_probe_status_avoids_generic_vision_overmatch():
    assert config_service._image_input_probe_status("vision") == (None, "unknown")
    assert config_service._image_input_probe_status("vision is not supported by this route") == (False, "unsupported")
    assert config_service._image_input_probe_status("model does not support vision") == (False, "unsupported")


def test_config_workspace_test_llm_image_input_reports_unsupported(monkeypatch, tmp_path):
    monkeypatch.setenv(MODEL_CAPABILITY_CACHE_ENV, str(tmp_path / "model-capabilities.json"))
    public_config = copy.deepcopy(load_public_config())
    public_config["llm"]["model_library"]["local_image_probe"] = {
        "provider": {
            "kind": "local",
            "api_key_env": "",
            "base_url": "http://127.0.0.1:11434/v1",
            "compat_mode": "openai",
            "requires_api_key": False,
            "context_window": 65536,
        },
        "model": "llama3.2",
        "label": "Local Image Probe",
    }
    public_config["llm"]["profiles"]["primary"] = {"model_ref": "local_image_probe"}
    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    recorded_scene_events: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(
        config_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_scene_events.append((args, kwargs)) or {"accepted": True},
    )

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def invoke(self, messages, tools=None, metadata=None):
            assert messages[0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
            raise RuntimeError("connection refused")

    monkeypatch.setattr("core.llm.LLMClient", FakeClient)

    response = client.post(
        "/api/config/test-llm",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "profileId": "primary",
            "capability": "image_input",
        },
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["ok"] is False
    assert payload["capability"] == "image_input"
    assert payload["capability_status"] == "unknown"
    assert payload["supports_image_input"] is None
    assert payload["api_key_source"] == "not-required"
    assert payload["requires_api_key"] is False
    assert recorded_scene_events
    fields = recorded_scene_events[-1][1]["fields"]
    assert fields["capability"] == "image_input"
    assert fields["supportsImageInput"] is None
    assert "base64" not in str(fields).lower()


def test_config_workspace_test_llm_image_input_maps_provider_unsupported(monkeypatch, tmp_path):
    monkeypatch.setenv(MODEL_CAPABILITY_CACHE_ENV, str(tmp_path / "model-capabilities.json"))
    public_config = copy.deepcopy(load_public_config())
    public_config["llm"]["model_library"]["local_image_probe"] = {
        "provider": {
            "kind": "local",
            "api_key_env": "",
            "base_url": "http://127.0.0.1:11434/v1",
            "compat_mode": "openai",
            "requires_api_key": False,
            "context_window": 65536,
        },
        "model": "llama3.2",
        "label": "Local Image Probe",
    }
    public_config["llm"]["profiles"]["primary"] = {"model_ref": "local_image_probe"}
    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def invoke(self, messages, tools=None, metadata=None):
            assert messages[0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
            raise RuntimeError("OpenAIException - No endpoints found that support image input")

    monkeypatch.setattr("core.llm.LLMClient", FakeClient)

    response = client.post(
        "/api/config/test-llm",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "profileId": "primary",
            "capability": "image_input",
        },
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["ok"] is False
    assert payload["capability_status"] == "unsupported"
    assert payload["supports_image_input"] is False
    assert payload["message"] == "image input is not supported by this model route"


def test_config_workspace_batch_image_capability_persists_model_only(monkeypatch, tmp_path):
    monkeypatch.setenv(MODEL_CAPABILITY_CACHE_ENV, str(tmp_path / "model-capabilities.json"))
    public_config = copy.deepcopy(load_public_config())
    public_config["llm"]["model_library"]["local_vision_probe"] = {
        "provider": {
            "kind": "local",
            "api_key_env": "",
            "base_url": "http://127.0.0.1:11434/v1",
            "compat_mode": "openai",
            "requires_api_key": False,
            "context_window": 65536,
        },
        "model": "local-vision",
        "label": "Local Vision",
        "api_key_env": "",
        "transport": "chat_completions",
        "contract": "tool_chat",
        "streaming": True,
        "tool_calling_mode": "auto",
        "discovery_enabled": True,
        "supports_image_input": False,
    }
    public_config["llm"]["profiles"]["primary"] = {"model_ref": "local_vision_probe"}
    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    class FakeClient:
        def __init__(self, *args, **kwargs):
            config = kwargs["config"]
            profile_id = kwargs["profile_id"]
            profile = config.llm.get_profile(profile_id=profile_id)
            assert config.llm.get_provider(profile.provider_id).provider_id
            assert profile.supports_image_input is True
            model_entry = config.llm.get_model_library_entry_for_profile(profile)[1]
            assert model_entry["model"] == "local-vision"
            assert model_entry["supports_image_input"] is True

        def invoke(self, messages, tools=None, metadata=None):
            assert metadata["probeCapability"] == "image_input"
            assert metadata["llmInvocationSurface"] == "config_image_input_probe"
            assert messages[0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
            return {"ok": True}

    monkeypatch.setattr("core.llm.LLMClient", FakeClient)

    response = client.post(
        "/api/config/draft/check-model-capabilities",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "modelIds": ["local_vision_probe"],
        },
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    model = payload["publicConfig"]["llm"]["model_library"]["local_vision_probe"]
    profile = payload["publicConfig"]["llm"]["profiles"]["primary"]
    assert model["supports_image_input"] is True
    assert model["capability_status"] == "supported"
    assert model["capability_source"] == "runtime_probe"
    assert "capability_checked_at" in model
    assert "capability_error" not in model
    assert "supports_image_input" not in profile
    assert "capability_status" not in profile
    assert "capability_source" not in profile
    assert "capability_checked_at" not in profile
    assert payload["capabilityResults"][0]["supportsImageInput"] is True


def test_config_workspace_batch_image_capability_records_unsupported(monkeypatch, tmp_path):
    monkeypatch.setenv(MODEL_CAPABILITY_CACHE_ENV, str(tmp_path / "model-capabilities.json"))
    public_config = copy.deepcopy(load_public_config())
    public_config["llm"]["model_library"]["local_text_probe"] = {
        "provider": {
            "kind": "local",
            "api_key_env": "",
            "base_url": "http://127.0.0.1:11434/v1",
            "compat_mode": "openai",
            "requires_api_key": False,
            "context_window": 65536,
        },
        "model": "local-text",
        "label": "Local Text",
        "api_key_env": "",
        "transport": "chat_completions",
        "contract": "tool_chat",
        "streaming": True,
        "tool_calling_mode": "auto",
        "discovery_enabled": True,
    }
    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def invoke(self, messages, tools=None, metadata=None):
            raise RuntimeError("No endpoints found that support image input")

    monkeypatch.setattr("core.llm.LLMClient", FakeClient)

    response = client.post(
        "/api/config/draft/check-model-capabilities",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "modelIds": ["local_text_probe"],
        },
    )

    assert response.status_code == 200, response.json()
    model = response.json()["publicConfig"]["llm"]["model_library"]["local_text_probe"]
    assert model["supports_image_input"] is False
    assert model["capability_status"] == "unsupported"
    assert model["capability_source"] == "runtime_probe"
    assert model["capability_error"] == "image input is not supported by this model route"


def test_config_workspace_draft_model_ignores_submitted_api_key_env(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    _ensure_preset_model(public_config, "deepseek_v4_pro")

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.post(
        "/api/config/draft/update-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "modelId": "deepseek_v4_pro",
            "provider": public_config["llm"]["model_library"]["deepseek_v4_pro"]["provider"],
            "model": "deepseek-v4-pro",
            "label": "DeepSeek V4 Pro",
            "details": public_config["llm"]["model_library"]["deepseek_v4_pro"],
            "apiKeyEnv": "PATH",
            "apiKey": "draft-secret",
        },
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    updated = payload["publicConfig"]["llm"]["model_library"]["deepseek_v4_pro"]
    assert updated["api_key_env"] == "VIBELUTION_LLM_MODEL_DEEPSEEK_V4_PRO_API_KEY"
    assert "PATH" not in payload["draftMeta"]["pending_api_keys"]
    assert "VIBELUTION_LLM_MODEL_DEEPSEEK_V4_PRO_API_KEY" in payload["draftMeta"]["pending_api_keys"]


def test_config_workspace_draft_model_persists_manual_image_input_support(monkeypatch, tmp_path):
    monkeypatch.setenv(MODEL_CAPABILITY_CACHE_ENV, str(tmp_path / "model-capabilities.json"))
    public_config = copy.deepcopy(load_public_config())
    public_config["llm"]["model_library"]["local_manual_image_probe"] = {
        "provider": {
            "kind": "local",
            "api_key_env": "",
            "base_url": "http://127.0.0.1:11434/v1",
            "compat_mode": "openai",
            "requires_api_key": False,
            "context_window": 65536,
        },
        "model": "local-vision",
        "label": "Local Vision",
        "api_key_env": "",
        "transport": "chat_completions",
        "contract": "tool_chat",
        "streaming": True,
        "tool_calling_mode": "auto",
        "supports_image_input": False,
    }
    target = public_config["llm"]["model_library"]["local_manual_image_probe"]

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.post(
        "/api/config/draft/update-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "modelId": "local_manual_image_probe",
            "provider": target["provider"],
            "model": "local-vision",
            "label": "Local Vision",
            "details": {
                **target,
                "supports_image_input": True,
                "capability_status": "supported",
                "capability_source": "manual",
            },
            "apiKeyEnv": "",
            "apiKey": "",
        },
    )

    assert response.status_code == 200, response.json()
    model = response.json()["publicConfig"]["llm"]["model_library"]["local_manual_image_probe"]
    assert model["supports_image_input"] is True
    assert model["capability_status"] == "supported"
    assert model["capability_source"] == "manual"
def test_config_workspace_draft_model_allows_custom_public_relay_host(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    target = public_config["llm"]["model_library"]["relay_openai_gpt_5_5"]
    provider = copy.deepcopy(target["provider"])
    provider["base_url"] = "https://relay.example.com/v1"

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.post(
        "/api/config/draft/update-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "modelId": "relay_openai_gpt_5_5",
            "provider": provider,
            "model": "gpt-5.5",
            "label": "GPT-5.5 via relay",
            "details": target,
            "apiKeyEnv": "VIBELUTION_LLM_MODEL_RELAY_OPENAI_GPT_5_5_API_KEY",
            "apiKey": "",
        },
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    updated = payload["publicConfig"]["llm"]["model_library"]["relay_openai_gpt_5_5"]
    assert updated["provider"]["base_url"] == "https://relay.example.com/v1"


def test_config_workspace_draft_model_allows_custom_openai_compatible_relay(monkeypatch):
    public_config = copy.deepcopy(load_public_config())

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.post(
        "/api/config/draft/add-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "presetId": "custom_openai_compatible_relay",
            "modelId": "custom_relay",
            "provider": {
                "kind": "openai_compatible",
                "api_key_env": "OPENAI_API_KEY",
                "base_url": "https://relay.example.com/v1",
                "compat_mode": "openai",
                "requires_api_key": True,
                "context_window": 65536,
            },
            "model": "custom-gpt",
            "label": "Custom Relay",
            "details": {
                "transport": "chat_completions",
                "contract": "tool_chat",
                "streaming": True,
            },
            "apiKeyEnv": "VIBELUTION_LLM_MODEL_CUSTOM_RELAY_API_KEY",
            "apiKey": "draft-secret",
        },
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    updated = payload["publicConfig"]["llm"]["model_library"]["custom_relay"]
    assert updated["provider"]["kind"] == "openai_compatible"
    assert updated["provider"]["base_url"] == "https://relay.example.com/v1"
    assert updated["prompt_cache"] == {"mode": "automatic"}
    assert updated["api_key_env"] == "VIBELUTION_LLM_MODEL_CUSTOM_RELAY_API_KEY"
    assert "VIBELUTION_LLM_MODEL_CUSTOM_RELAY_API_KEY" in payload["draftMeta"]["pending_api_keys"]


def test_config_workspace_draft_update_model_preserves_prompt_cache_when_details_omit_it(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config["llm"]["model_library"]["custom_relay"] = {
        "provider": {
            "kind": "openai_compatible",
            "api_key_env": "OPENAI_API_KEY",
            "base_url": "https://relay.example.com/v1",
            "compat_mode": "openai",
            "requires_api_key": True,
            "context_window": 65536,
        },
        "model": "custom-gpt",
        "label": "Custom Relay",
        "transport": "chat_completions",
        "contract": "tool_chat",
        "prompt_cache": {"mode": "unsupported"},
        "api_key_env": "VIBELUTION_LLM_MODEL_CUSTOM_RELAY_API_KEY",
    }

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.post(
        "/api/config/draft/update-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "modelId": "custom_relay",
            "provider": public_config["llm"]["model_library"]["custom_relay"]["provider"],
            "model": "custom-gpt",
            "label": "Custom Relay",
            "details": {
                "transport": "chat_completions",
                "contract": "tool_chat",
                "streaming": True,
            },
            "apiKeyEnv": "VIBELUTION_LLM_MODEL_CUSTOM_RELAY_API_KEY",
            "apiKey": "",
        },
    )

    assert response.status_code == 200, response.json()
    updated = response.json()["publicConfig"]["llm"]["model_library"]["custom_relay"]
    assert updated["prompt_cache"] == {"mode": "unsupported"}


def test_config_workspace_draft_model_allows_custom_relay_responses(monkeypatch):
    public_config = copy.deepcopy(load_public_config())

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.post(
        "/api/config/draft/add-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "presetId": "custom_relay_responses",
            "modelId": "custom_relay_responses_model",
            "provider": {
                "kind": "relay",
                "api_key_env": "OPENAI_API_KEY",
                "base_url": "https://ai-pixel.online",
                "compat_mode": "openai",
                "requires_api_key": True,
                "context_window": 1000000,
            },
            "model": "gpt-5.5",
            "label": "Custom Relay Responses",
            "details": {
                "transport": "responses",
                "contract": "tool_chat",
                "streaming": True,
            },
            "apiKeyEnv": "VIBELUTION_LLM_MODEL_CUSTOM_RELAY_RESPONSES_MODEL_API_KEY",
            "apiKey": "draft-secret",
        },
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    updated = payload["publicConfig"]["llm"]["model_library"]["custom_relay_responses_model"]
    assert updated["provider"]["kind"] == "relay"
    assert updated["provider"]["base_url"] == "https://ai-pixel.online"
    assert updated["transport"] == "responses"
    assert updated["api_key_env"] == "VIBELUTION_LLM_MODEL_CUSTOM_RELAY_RESPONSES_MODEL_API_KEY"


def test_config_workspace_draft_model_rejects_unknown_model_id(monkeypatch):
    public_config = copy.deepcopy(load_public_config())

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.post(
        "/api/config/draft/update-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "modelId": "generated_from_profile",
            "provider": public_config["llm"]["model_library"]["relay_openai_gpt_5_5"]["provider"],
            "model": "gpt-5.5",
            "label": "Generated from profile",
            "details": public_config["llm"]["model_library"]["relay_openai_gpt_5_5"],
            "apiKeyEnv": "VIBELUTION_LLM_MODEL_RELAY_OPENAI_GPT_5_5_API_KEY",
            "apiKey": "",
        },
    )

    assert response.status_code == 422
    assert "unknown LLM model" in response.json()["detail"]


def test_config_workspace_draft_update_model_migrates_to_unique_model_key(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config["llm"]["model_library"]["custom_relay"] = {
        "provider": {
            "kind": "openai_compatible",
            "api_key_env": "OPENAI_API_KEY",
            "base_url": "https://relay.example.com/v1",
            "compat_mode": "openai",
            "requires_api_key": True,
            "context_window": 65536,
        },
        "model": "custom-gpt",
        "label": "Custom Relay",
        "api_key_env": "VIBELUTION_LLM_CUSTOM_RELAY_API_KEY",
    }

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))
    monkeypatch.setenv("VIBELUTION_LLM_CUSTOM_RELAY_API_KEY", "legacy-secret")
    monkeypatch.delenv("VIBELUTION_LLM_MODEL_CUSTOM_RELAY_API_KEY", raising=False)

    response = client.post(
        "/api/config/draft/update-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "modelId": "custom_relay",
            "provider": public_config["llm"]["model_library"]["custom_relay"]["provider"],
            "model": "custom-gpt",
            "label": "Custom Relay",
            "details": {},
            "apiKeyEnv": "VIBELUTION_LLM_CUSTOM_RELAY_API_KEY",
            "apiKey": "",
        },
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    updated = payload["publicConfig"]["llm"]["model_library"]["custom_relay"]
    assert updated["api_key_env"] == "VIBELUTION_LLM_MODEL_CUSTOM_RELAY_API_KEY"
    assert "VIBELUTION_LLM_MODEL_CUSTOM_RELAY_API_KEY" in payload["draftMeta"]["pending_api_keys"]
    assert payload["draftMeta"]["pending_cleared_api_keys"] == ["VIBELUTION_LLM_CUSTOM_RELAY_API_KEY"]


def test_config_workspace_draft_model_auto_generates_custom_relay_model_id(monkeypatch):
    public_config = copy.deepcopy(load_public_config())

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.post(
        "/api/config/draft/add-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "presetId": "custom_openai_compatible_relay",
            "modelId": "",
            "provider": {
                "kind": "openai_compatible",
                "api_key_env": "OPENAI_API_KEY",
                "base_url": "https://example.com/v1",
                "compat_mode": "openai",
                "requires_api_key": True,
                "context_window": 65536,
            },
            "model": "gpt-5.5",
            "label": "GPT-5.5",
            "details": {
                "transport": "chat_completions",
                "contract": "tool_chat",
                "streaming": True,
            },
            "apiKeyEnv": "",
            "apiKey": "",
        },
    )

    assert response.status_code == 200, response.json()
    model_library = response.json()["publicConfig"]["llm"]["model_library"]
    assert "gpt_5_5" in model_library
    assert "custom_openai_compatible_relay" not in model_library
    assert model_library["gpt_5_5"]["api_key_env"] == "VIBELUTION_LLM_MODEL_GPT_5_5_API_KEY"


def test_config_workspace_draft_model_rejects_custom_relay_localhost(monkeypatch):
    public_config = copy.deepcopy(load_public_config())

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.post(
        "/api/config/draft/add-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "presetId": "custom_openai_compatible_relay",
            "modelId": "custom_relay",
            "provider": {
                "kind": "openai_compatible",
                "api_key_env": "OPENAI_API_KEY",
                "base_url": "http://127.0.0.1:11434/v1",
                "compat_mode": "openai",
                "requires_api_key": True,
                "context_window": 65536,
            },
            "model": "custom-gpt",
            "label": "Custom Relay",
            "details": {
                "transport": "chat_completions",
                "contract": "tool_chat",
                "streaming": True,
            },
            "apiKeyEnv": "VIBELUTION_LLM_MODEL_CUSTOM_RELAY_API_KEY",
            "apiKey": "",
        },
    )

    assert response.status_code == 422
    assert "localhost" in response.json()["detail"] or "https" in response.json()["detail"]


def test_config_workspace_draft_model_rejects_custom_responses_relay_localhost(monkeypatch):
    public_config = copy.deepcopy(load_public_config())

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.post(
        "/api/config/draft/add-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "presetId": "custom_relay_responses",
            "modelId": "custom_relay_responses_model",
            "provider": {
                "kind": "relay",
                "api_key_env": "OPENAI_API_KEY",
                "base_url": "https://127.0.0.1:11434/v1",
                "compat_mode": "openai",
                "requires_api_key": True,
                "context_window": 1000000,
            },
            "model": "gpt-5.5",
            "label": "Custom Relay Responses",
            "details": {
                "transport": "responses",
                "contract": "tool_chat",
                "streaming": True,
            },
            "apiKeyEnv": "VIBELUTION_LLM_MODEL_CUSTOM_RELAY_RESPONSES_MODEL_API_KEY",
            "apiKey": "",
        },
    )

    assert response.status_code == 422
    assert "localhost" in response.json()["detail"]


def test_config_workspace_draft_model_allows_private_lan_local_provider(monkeypatch):
    public_config = copy.deepcopy(load_public_config())

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.post(
        "/api/config/draft/add-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "presetId": "local_openai_compatible",
            "modelId": "lan_local_model",
            "provider": {
                "kind": "local",
                "api_key_env": "",
                "base_url": "http://192.168.20.46:8081/v1",
                "compat_mode": "openai",
                "requires_api_key": False,
                "context_window": 65536,
            },
            "model": "qwen-local",
            "label": "LAN Local Model",
            "details": {
                "transport": "chat_completions",
                "contract": "basic_chat",
                "streaming": True,
            },
            "apiKeyEnv": "",
            "apiKey": "",
        },
    )

    assert response.status_code == 200, response.json()
    model_library = response.json()["publicConfig"]["llm"]["model_library"]
    assert model_library["lan_local_model"]["provider"]["kind"] == "local"
    assert model_library["lan_local_model"]["provider"]["base_url"] == "http://192.168.20.46:8081/v1"
    assert model_library["lan_local_model"]["provider"]["requires_api_key"] is False


def test_config_workspace_draft_model_rejects_private_lan_remote_provider(monkeypatch):
    public_config = copy.deepcopy(load_public_config())

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.post(
        "/api/config/draft/add-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "presetId": "custom_openai_compatible_relay",
            "modelId": "lan_remote_model",
            "provider": {
                "kind": "openai_compatible",
                "api_key_env": "OPENAI_API_KEY",
                "base_url": "http://192.168.20.46:8081/v1",
                "compat_mode": "openai",
                "requires_api_key": True,
                "context_window": 65536,
            },
            "model": "qwen-local",
            "label": "LAN Remote Model",
            "details": {
                "transport": "chat_completions",
                "contract": "tool_chat",
                "streaming": True,
            },
            "apiKeyEnv": "VIBELUTION_LLM_MODEL_LAN_REMOTE_MODEL_API_KEY",
            "apiKey": "",
        },
    )

    assert response.status_code == 422
    assert "https" in response.json()["detail"] or "non-public" in response.json()["detail"]


def test_config_workspace_draft_model_rejects_link_local_metadata_for_local_provider(monkeypatch):
    public_config = copy.deepcopy(load_public_config())

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.post(
        "/api/config/draft/add-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "presetId": "local_openai_compatible",
            "modelId": "metadata_local_model",
            "provider": {
                "kind": "local",
                "api_key_env": "",
                "base_url": "http://169.254.169.254/v1",
                "compat_mode": "openai",
                "requires_api_key": False,
                "context_window": 65536,
            },
            "model": "metadata-model",
            "label": "Metadata Local Model",
            "details": {
                "transport": "chat_completions",
                "contract": "basic_chat",
                "streaming": True,
            },
            "apiKeyEnv": "",
            "apiKey": "",
        },
    )

    assert response.status_code == 422
    assert "localhost" in response.json()["detail"] or "private LAN" in response.json()["detail"]


def _mock_model_discovery_public_dns(monkeypatch):
    monkeypatch.setattr(
        "config.llm_security.socket.getaddrinfo",
        lambda host, port, type=None: [(None, None, None, None, ("8.8.8.8", port))],
    )


def test_config_workspace_discovers_custom_openai_compatible_models(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    seen = {}

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))
    _mock_model_discovery_public_dns(monkeypatch)

    def fake_discover_model_list(api_base, *, api_key="", timeout=10, api_key_source=""):
        seen["api_base"] = api_base
        seen["api_key"] = api_key
        seen["api_key_source"] = api_key_source
        seen["timeout"] = timeout
        return [
            {"id": "gpt-5.5", "label": "GPT-5.5", "context_window": 1000000},
            {"id": "gpt-5.5-mini", "label": "GPT-5.5 Mini", "context_window": 128000},
        ]

    monkeypatch.setattr(config_service, "_discover_openai_compatible_model_list", fake_discover_model_list)

    response = client.post(
        "/api/config/discover-models",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "provider": {
                "kind": "openai_compatible",
                "api_key_env": "OPENAI_API_KEY",
                "base_url": "https://example.com/v1",
                "compat_mode": "openai",
                "requires_api_key": True,
                "context_window": 65536,
            },
            "apiKey": "draft-secret",
        },
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["models"][0]["id"] == "gpt-5.5"
    assert payload["models"][0]["contextWindow"] == 1000000
    assert payload["models"][1]["id"] == "gpt-5.5-mini"
    assert seen == {
        "api_base": "https://example.com/v1",
        "api_key": "draft-secret",
        "api_key_source": "手动输入",
        "timeout": config_service._MODEL_DISCOVERY_DEFAULT_TIMEOUT_SECONDS,
    }


def test_config_workspace_discovers_custom_public_relay_models(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    seen = {}

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))
    _mock_model_discovery_public_dns(monkeypatch)

    def fake_discover_model_list(api_base, *, api_key="", timeout=10, api_key_source=""):
        seen["api_base"] = api_base
        seen["api_key"] = api_key
        seen["api_key_source"] = api_key_source
        seen["timeout"] = timeout
        return [{"id": "gpt-5.5", "label": "GPT-5.5", "context_window": 1000000}]

    monkeypatch.setattr(config_service, "_discover_openai_compatible_model_list", fake_discover_model_list)

    response = client.post(
        "/api/config/discover-models",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "provider": {
                "kind": "relay",
                "api_key_env": "OPENAI_API_KEY",
                "base_url": "https://relay.example.com/v1",
                "compat_mode": "openai",
                "requires_api_key": True,
                "context_window": 1000000,
            },
            "apiKey": "draft-secret",
        },
    )

    assert response.status_code == 200, response.json()
    assert response.json()["providerKind"] == "relay"
    assert response.json()["baseUrl"] == "https://relay.example.com/v1"
    assert response.json()["models"][0]["id"] == "gpt-5.5"
    assert seen == {
        "api_base": "https://relay.example.com/v1",
        "api_key": "draft-secret",
        "api_key_source": "手动输入",
        "timeout": config_service._MODEL_DISCOVERY_DEFAULT_TIMEOUT_SECONDS,
    }


def test_config_workspace_discovers_custom_public_relay_models(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    seen = {}

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))
    _mock_model_discovery_public_dns(monkeypatch)

    def fake_discover_model_list(api_base, *, api_key="", timeout=10, api_key_source=""):
        seen["api_base"] = api_base
        seen["api_key"] = api_key
        seen["api_key_source"] = api_key_source
        seen["timeout"] = timeout
        return [{"id": "gpt-5.5", "label": "GPT-5.5", "context_window": 1000000}]

    monkeypatch.setattr(config_service, "_discover_openai_compatible_model_list", fake_discover_model_list)

    response = client.post(
        "/api/config/discover-models",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "provider": {
                "kind": "relay",
                "api_key_env": "OPENAI_API_KEY",
                "base_url": "https://relay.example.com/v1",
                "compat_mode": "openai",
                "requires_api_key": True,
                "context_window": 1000000,
            },
            "apiKey": "draft-secret",
        },
    )

    assert response.status_code == 200, response.json()
    assert response.json()["providerKind"] == "relay"
    assert response.json()["baseUrl"] == "https://relay.example.com/v1"
    assert response.json()["models"][0]["id"] == "gpt-5.5"
    assert seen == {
        "api_base": "https://relay.example.com/v1",
        "api_key": "draft-secret",
        "api_key_source": "手动输入",
        "timeout": config_service._MODEL_DISCOVERY_DEFAULT_TIMEOUT_SECONDS,
    }


def test_config_workspace_model_discovery_uses_configured_environment_key(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    seen = {}

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))
    _mock_model_discovery_public_dns(monkeypatch)
    monkeypatch.setenv("VIBELUTION_LLM_MODEL_CUSTOM_RELAY_API_KEY", "env-secret")

    def fake_discover_model_list(api_base, *, api_key="", timeout=10, api_key_source=""):
        seen["api_base"] = api_base
        seen["api_key"] = api_key
        seen["api_key_source"] = api_key_source
        return [{"id": "relay-model", "label": "Relay Model"}]

    monkeypatch.setattr(config_service, "_discover_openai_compatible_model_list", fake_discover_model_list)

    response = client.post(
        "/api/config/discover-models",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "provider": {
                "kind": "openai_compatible",
                "api_key_env": "VIBELUTION_LLM_MODEL_CUSTOM_RELAY_API_KEY",
                "base_url": "https://example.com/v1",
                "compat_mode": "openai",
                "requires_api_key": True,
                "context_window": 65536,
            },
            "apiKey": "",
        },
    )

    assert response.status_code == 200, response.json()
    assert response.json()["apiKeySource"] == "系统环境变量 VIBELUTION_LLM_MODEL_CUSTOM_RELAY_API_KEY"
    assert seen == {
        "api_base": "https://example.com/v1",
        "api_key": "env-secret",
        "api_key_source": "系统环境变量 VIBELUTION_LLM_MODEL_CUSTOM_RELAY_API_KEY",
    }


def test_config_workspace_model_discovery_prefers_model_key_env(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    seen = {}

    public_config["llm"]["model_library"]["custom_relay"] = {
        "provider": {
            "kind": "openai_compatible",
            "api_key_env": "OPENAI_API_KEY",
            "base_url": "https://example.com/v1",
            "compat_mode": "openai",
            "requires_api_key": True,
            "context_window": 65536,
        },
        "model": "custom-gpt",
        "label": "Custom Relay",
        "api_key_env": "VIBELUTION_LLM_MODEL_CUSTOM_RELAY_API_KEY",
    }
    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))
    _mock_model_discovery_public_dns(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "provider-secret")
    monkeypatch.setenv("VIBELUTION_LLM_MODEL_CUSTOM_RELAY_API_KEY", "model-secret")

    def fake_discover_model_list(api_base, *, api_key="", timeout=10, api_key_source=""):
        seen["api_base"] = api_base
        seen["api_key"] = api_key
        seen["api_key_source"] = api_key_source
        return [{"id": "relay-model", "label": "Relay Model"}]

    monkeypatch.setattr(config_service, "_discover_openai_compatible_model_list", fake_discover_model_list)

    response = client.post(
        "/api/config/discover-models",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "provider": {
                "kind": "openai_compatible",
                "api_key_env": "OPENAI_API_KEY",
                "base_url": "https://example.com/v1",
                "compat_mode": "openai",
                "requires_api_key": True,
                "context_window": 65536,
            },
            "modelId": "custom_relay",
            "apiKey": "",
        },
    )

    assert response.status_code == 200, response.json()
    assert response.json()["apiKeySource"] == "系统环境变量 VIBELUTION_LLM_MODEL_CUSTOM_RELAY_API_KEY"
    assert seen == {
        "api_base": "https://example.com/v1",
        "api_key": "model-secret",
        "api_key_source": "系统环境变量 VIBELUTION_LLM_MODEL_CUSTOM_RELAY_API_KEY",
    }


def test_config_workspace_model_discovery_uses_submitted_model_key_env(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    seen = {}

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))
    _mock_model_discovery_public_dns(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "provider-secret")
    monkeypatch.setenv("VIBELUTION_LLM_MODEL_NEW_RELAY_API_KEY", "new-model-secret")

    def fake_discover_model_list(api_base, *, api_key="", timeout=10, api_key_source=""):
        seen["api_key"] = api_key
        seen["api_key_source"] = api_key_source
        return [{"id": "new-model", "label": "New Model"}]

    monkeypatch.setattr(config_service, "_discover_openai_compatible_model_list", fake_discover_model_list)

    response = client.post(
        "/api/config/discover-models",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "provider": {
                "kind": "openai_compatible",
                "api_key_env": "OPENAI_API_KEY",
                "base_url": "https://example.com/v1",
                "compat_mode": "openai",
                "requires_api_key": True,
                "context_window": 65536,
            },
            "modelId": "new_relay",
            "apiKeyEnv": "VIBELUTION_LLM_MODEL_NEW_RELAY_API_KEY",
            "apiKey": "",
        },
    )

    assert response.status_code == 200, response.json()
    assert seen == {
        "api_key": "new-model-secret",
        "api_key_source": "系统环境变量 VIBELUTION_LLM_MODEL_NEW_RELAY_API_KEY",
    }


def test_config_workspace_model_discovery_url_candidates_do_not_duplicate_v1():
    assert config_service._model_discovery_urls("https://ai-pixel.online") == [
        "https://ai-pixel.online/models",
        "https://ai-pixel.online/v1/models",
    ]
    assert config_service._model_discovery_urls("https://ai-pixel.online/v1") == [
        "https://ai-pixel.online/v1/models",
    ]
    assert config_service._model_discovery_urls("https://ai-pixel.online/v1/models") == [
        "https://ai-pixel.online/v1/models",
    ]


def test_config_workspace_model_discovery_uses_fast_fail_timeout(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    seen = {}

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    def fake_discover_model_list(api_base, *, api_key="", timeout=10, api_key_source=""):
        seen["timeout"] = timeout
        return [{"id": "fast-model", "label": "Fast Model"}]

    monkeypatch.setattr(config_service, "_discover_openai_compatible_model_list", fake_discover_model_list)

    response = client.post(
        "/api/config/discover-models",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "provider": {
                "kind": "openai_compatible",
                "api_key_env": "OPENAI_API_KEY",
                "base_url": "https://example.com/v1",
                "compat_mode": "openai",
                "requires_api_key": True,
                "context_window": 65536,
            },
            "apiKey": "draft-secret",
        },
    )

    assert response.status_code == 200, response.json()
    assert seen["timeout"] == config_service._MODEL_DISCOVERY_DEFAULT_TIMEOUT_SECONDS


def test_config_workspace_model_discovery_caches_recent_failures(monkeypatch):
    calls = []
    events = []

    config_service._MODEL_DISCOVERY_NEGATIVE_CACHE.clear()
    monkeypatch.setattr(config_service, "_model_discovery_urls", lambda api_base: ["https://example.com/models"])
    monkeypatch.setattr(config_service, "record_runtime_scene_event", lambda *args, **kwargs: events.append((args, kwargs)))

    def fake_discover_model_url(url, *, headers, timeout):
        calls.append((url, timeout))
        return url, 404, 12, [], httpx.HTTPStatusError(
            "not found",
            request=httpx.Request("GET", url),
            response=httpx.Response(404, request=httpx.Request("GET", url)),
        )

    monkeypatch.setattr(config_service, "_discover_model_url", fake_discover_model_url)

    with pytest.raises(ValueError) as first_error:
        config_service._discover_openai_compatible_model_list(
            "https://example.com",
            api_key="secret",
            timeout=10,
            api_key_source="手动输入",
        )
    with pytest.raises(ValueError) as second_error:
        config_service._discover_openai_compatible_model_list(
            "https://example.com",
            api_key="secret",
            timeout=10,
            api_key_source="手动输入",
        )

    assert len(calls) == 1
    assert calls[0][1] == config_service._MODEL_DISCOVERY_DEFAULT_TIMEOUT_SECONDS
    assert str(first_error.value) == str(second_error.value)
    assert any(args[2] == "config.model_discovery.cached_failure" for args, _ in events)


def test_config_workspace_model_discovery_rejects_localhost(monkeypatch):
    public_config = copy.deepcopy(load_public_config())

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.post(
        "/api/config/discover-models",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "provider": {
                "kind": "openai_compatible",
                "api_key_env": "OPENAI_API_KEY",
                "base_url": "http://127.0.0.1:11434/v1",
                "compat_mode": "openai",
                "requires_api_key": True,
                "context_window": 65536,
            },
            "apiKey": "",
        },
    )

    assert response.status_code == 422
    assert "localhost" in response.json()["detail"] or "https" in response.json()["detail"]


def test_config_workspace_apply_rejects_stale_base_hash(monkeypatch):
    original = copy.deepcopy(load_public_config())
    stale_hash = public_config_hash(original)
    external = copy.deepcopy(original)
    external.setdefault("ui", {})["language"] = "en"
    public_config = external

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))

    response = client.put(
        "/api/config/apply",
        json={
            "publicConfig": original,
            "draftMeta": {},
            "baseHash": stale_hash,
        },
    )

    assert response.status_code == 409
    assert "重新加载" in response.json()["detail"]


def test_config_workspace_apply_persists_changes_and_pending_env(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    _ensure_preset_model(public_config, "deepseek_v4_pro")
    writes = []
    deletes = []
    reloads = []
    scene_events = []

    def fake_load_public_config():
        return copy.deepcopy(public_config)

    def fake_save_public_config(updated_public_config):
        public_config.clear()
        public_config.update(copy.deepcopy(updated_public_config))

    monkeypatch.setattr(config_service, "load_public_config", fake_load_public_config)
    monkeypatch.setattr(config_service, "save_public_config", fake_save_public_config)
    monkeypatch.setattr(config_service, "_set_user_env_var", lambda name, value: writes.append((name, value)))
    monkeypatch.setattr(config_service, "_delete_user_env_var", lambda name: deletes.append(name))
    monkeypatch.setattr(
        config_service,
        "reload_config",
        lambda config_path=None: reloads.append((config_path, copy.deepcopy(public_config)))
        or config_service.build_effective_config(public_config),
    )
    monkeypatch.setattr(config_service, "_record_config_scene_event", lambda *args, **kwargs: scene_events.append((args, kwargs)))

    payload = copy.deepcopy(public_config)
    payload.setdefault("ui", {})["language"] = "en"

    draft_response = client.post(
        "/api/config/draft/update-model",
        json={
            "publicConfig": payload,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "modelId": "deepseek_v4_pro",
            "provider": payload["llm"]["model_library"]["deepseek_v4_pro"]["provider"],
            "model": "deepseek-v4-pro",
            "label": "DeepSeek V4 Pro",
            "details": payload["llm"]["model_library"]["deepseek_v4_pro"],
            "apiKeyEnv": "VIBELUTION_LLM_DEEPSEEK_V4_PRO_API_KEY",
            "apiKey": "draft-secret",
        },
    )

    assert draft_response.status_code == 200
    draft_payload = draft_response.json()

    response = client.put(
        "/api/config/apply",
        json={
            "publicConfig": draft_payload["publicConfig"],
            "draftMeta": draft_payload["draftMeta"],
            "baseHash": public_config_hash(public_config),
        },
    )

    assert response.status_code == 200
    persisted = response.json()
    assert public_config["ui"]["language"] == "en"
    assert writes == [("VIBELUTION_LLM_MODEL_DEEPSEEK_V4_PRO_API_KEY", "draft-secret")]
    assert deletes == []
    assert persisted["baseHash"] == persisted["hash"]
    assert len(reloads) == 1
    assert reloads[0][0] == str(config_service.CONFIG_PATH)
    assert reloads[0][1]["ui"]["language"] == "en"
    applied_event = scene_events[-1][1]["fields"]
    assert applied_event["runtimeConfigReloaded"] is True
    assert applied_event["primaryProviderKind"]
    assert applied_event["primaryTransport"]
    assert applied_event["primaryModel"] == config_service.build_effective_config(public_config).llm.get_profile(role="primary").model


def test_config_workspace_apply_deletes_removed_model_key(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config["llm"]["model_library"]["custom_relay"] = {
        "provider": {
            "kind": "openai_compatible",
            "api_key_env": "OPENAI_API_KEY",
            "base_url": "https://relay.example.com/v1",
            "compat_mode": "openai",
            "requires_api_key": True,
            "context_window": 65536,
        },
        "model": "custom-gpt",
        "label": "Custom Relay",
        "api_key_env": "VIBELUTION_LLM_MODEL_CUSTOM_RELAY_API_KEY",
    }
    writes = []
    deletes = []

    def fake_load_public_config():
        return copy.deepcopy(public_config)

    def fake_save_public_config(updated_public_config):
        public_config.clear()
        public_config.update(copy.deepcopy(updated_public_config))

    monkeypatch.setattr(config_service, "load_public_config", fake_load_public_config)
    monkeypatch.setattr(config_service, "save_public_config", fake_save_public_config)
    monkeypatch.setattr(config_service, "_set_user_env_var", lambda name, value: writes.append((name, value)))
    monkeypatch.setattr(config_service, "_delete_user_env_var", lambda name: deletes.append(name))
    monkeypatch.setattr(
        config_service,
        "reload_config",
        lambda config_path=None: config_service.build_effective_config(public_config),
    )
    monkeypatch.setattr(config_service, "_record_config_scene_event", lambda *args, **kwargs: None)

    draft_response = client.post(
        "/api/config/draft/delete-model",
        json={
            "publicConfig": public_config,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
            "modelId": "custom_relay",
        },
    )
    assert draft_response.status_code == 200, draft_response.json()

    response = client.put(
        "/api/config/apply",
        json={
            "publicConfig": draft_response.json()["publicConfig"],
            "draftMeta": draft_response.json()["draftMeta"],
            "baseHash": public_config_hash(public_config),
        },
    )

    assert response.status_code == 200, response.json()
    assert writes == []
    assert deletes == ["VIBELUTION_LLM_MODEL_CUSTOM_RELAY_API_KEY"]
    assert "custom_relay" not in public_config["llm"]["model_library"]


def test_config_workspace_apply_rejects_missing_git_commit_model(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    _ensure_preset_model(public_config, "deepseek_v4_pro")
    public_config["llm"]["model_library"]["git_commit_model"] = copy.deepcopy(
        public_config["llm"]["model_library"]["deepseek_v4_pro"]
    )
    public_config.setdefault("git", {})["commit_message_model_ref"] = "git_commit_model"
    payload = copy.deepcopy(public_config)
    payload["llm"]["model_library"].pop("git_commit_model", None)
    scene_events = []

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))
    monkeypatch.setattr(config_service, "save_public_config", lambda updated: pytest.fail("invalid config should not be saved"))
    monkeypatch.setattr(
        config_service,
        "_record_config_scene_event",
        lambda phase, event_code, **kwargs: scene_events.append((phase, event_code, kwargs)),
    )

    response = client.put(
        "/api/config/apply",
        json={
            "publicConfig": payload,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
        },
    )

    assert response.status_code == 422
    assert "unknown Git commit message model" in response.json()["detail"]
    assert scene_events[-1][1] == "config.git_commit_model_ref.rejected"


def test_config_workspace_apply_rejects_invalid_git_commit_prompt(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    payload = copy.deepcopy(public_config)
    payload.setdefault("git", {})["commit_message_prompt"] = "Summary only: {summary}"
    scene_events = []

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))
    monkeypatch.setattr(config_service, "save_public_config", lambda updated: pytest.fail("invalid config should not be saved"))
    monkeypatch.setattr(
        config_service,
        "_record_config_scene_event",
        lambda phase, event_code, **kwargs: scene_events.append((phase, event_code, kwargs)),
    )

    response = client.put(
        "/api/config/apply",
        json={
            "publicConfig": payload,
            "draftMeta": {},
            "baseHash": public_config_hash(public_config),
        },
    )

    assert response.status_code == 422
    assert "{files}" in response.json()["detail"]
    assert "{diff}" in response.json()["detail"]
    assert scene_events[-1][1] == "config.git_commit_prompt.rejected"


def test_config_workspace_apply_ignores_forged_pending_env(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    writes = []

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))
    monkeypatch.setattr(config_service, "save_public_config", lambda updated: None)
    monkeypatch.setattr(config_service, "_set_user_env_var", lambda name, value: writes.append((name, value)))

    response = client.put(
        "/api/config/apply",
        json={
            "publicConfig": public_config,
            "draftMeta": {
                "pending_api_keys": {"VIBELUTION_LLM_DEEPSEEK_V4_PRO_API_KEY": "forged-secret"},
                "pending_cleared_api_keys": [],
            },
            "baseHash": public_config_hash(public_config),
        },
    )

    assert response.status_code == 200
    assert writes == []


def test_config_and_evolution_share_intake_mode(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config.setdefault("evolution", {})["intake_mode"] = "auto"

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))
    monkeypatch.setattr(workbench_contract_service, "load_public_config", lambda: copy.deepcopy(public_config))

    config_response = client.get("/api/config/public")
    overview_response = client.get("/api/evolution/overview")

    assert config_response.status_code == 200
    assert overview_response.status_code == 200
    assert config_response.json()["intakeMode"] == "auto"
    assert overview_response.json()["intakeMode"] == "auto"


def test_chat_disable_redirects_home_contract_to_evolution(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    agent_cfg = public_config.setdefault("agent", {})
    modes_cfg = agent_cfg.setdefault("modes", {})
    modes_cfg["chat_enabled"] = False
    modes_cfg["self_evolution_enabled"] = True
    modes_cfg["supervised_evolution_enabled"] = True
    modes_cfg["default_shell_mode"] = "chat"
    public_config.setdefault("evolution", {})["enabled"] = True

    monkeypatch.setattr(config_service, "load_public_config", lambda: copy.deepcopy(public_config))
    monkeypatch.setattr(runtime_service, "load_public_config", lambda: copy.deepcopy(public_config))

    config_response = client.get("/api/config/public")
    runtime_response = client.get("/api/runtime/summary")

    assert config_response.status_code == 200
    assert runtime_response.status_code == 200

    config_payload = config_response.json()
    runtime_payload = runtime_response.json()

    assert config_payload["defaultRoute"] == "/self-evolution"
    assert runtime_payload["defaultRoute"] == "/self-evolution"
    assert config_payload["defaultMode"] == "self_evolution"
    assert runtime_payload["mode"] == "self_evolution"
    assert config_payload["domainAvailability"]["chat"] is False
    assert config_payload["domainAvailability"]["evolution"] is True
    assert runtime_payload["domainAvailability"]["chat"] is False
    assert runtime_payload["domainAvailability"]["evolution"] is True


def test_updating_intake_mode_refreshes_config_and_evolution(monkeypatch):
    public_config = copy.deepcopy(load_public_config())

    def fake_load_public_config():
        return copy.deepcopy(public_config)

    def fake_save_public_config(updated_public_config):
        public_config.clear()
        public_config.update(copy.deepcopy(updated_public_config))

    monkeypatch.setattr(config_service, "load_public_config", fake_load_public_config)
    monkeypatch.setattr(config_service, "save_public_config", fake_save_public_config)
    monkeypatch.setattr(workbench_contract_service, "load_public_config", fake_load_public_config)

    update_response = client.put("/api/config/intake-mode", json={"intakeMode": "auto"})
    config_response = client.get("/api/config/public")
    overview_response = client.get("/api/evolution/overview")

    assert update_response.status_code == 200
    assert config_response.status_code == 200
    assert overview_response.status_code == 200
    assert update_response.json()["intakeMode"] == "auto"
    assert config_response.json()["intakeMode"] == "auto"
    assert overview_response.json()["intakeMode"] == "auto"


def test_updating_language_refreshes_config_summary(monkeypatch):
    public_config = copy.deepcopy(load_public_config())
    public_config.setdefault("ui", {})["language"] = "zh"

    def fake_load_public_config():
        return copy.deepcopy(public_config)

    def fake_save_public_config(updated_public_config):
        public_config.clear()
        public_config.update(copy.deepcopy(updated_public_config))

    monkeypatch.setattr(config_service, "load_public_config", fake_load_public_config)
    monkeypatch.setattr(config_service, "save_public_config", fake_save_public_config)
    monkeypatch.setattr("core.web.services.i18n.load_public_config", fake_load_public_config)

    update_response = client.put("/api/config/language", json={"language": "en"})
    config_response = client.get("/api/config/public")

    assert update_response.status_code == 200
    assert config_response.status_code == 200
    assert update_response.json()["language"] == "en"
    assert config_response.json()["language"] == "en"
