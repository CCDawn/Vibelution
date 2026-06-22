from __future__ import annotations

import json
from pathlib import Path

from core.infrastructure.mental_model import (
    active_mental_workspace,
    get_mental_model,
    reset_mental_model,
    update_self_model_tool,
)
from core.orchestration.task_planner import task_storage_override
from core.ui.chat_state import CHAT_STATE_VERSION, load_chat_state, save_chat_state
from core.web.services import agent_directory_service, prompt_template_service, session_service
from tools.memory_tools import memory_storage_override
from tools.shell_tools import create_file, workspace_root_override
from tools.memory_tools import task_create_tool


def _seed_session(project_root: Path, session_id: str = "session-live") -> None:
    save_chat_state(
        project_root,
        {
            "version": CHAT_STATE_VERSION,
            "active_conversation_id": session_id,
            "updated_at": "2026-05-21T12:00:00",
            "conversations": [
                {
                    "conversation_id": session_id,
                    "title": "Agent 会话",
                    "updated_at": "2026-05-21T12:00:00",
                    "last_turn_status": "ready",
                    "messages": [],
                    "active_task": None,
                }
            ],
        },
    )


def test_session_workspace_path_is_safe_and_created(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    workspace = session_service._ensure_session_workspace("abc/../../x")

    assert workspace.parent == tmp_path / "workspace" / "sessions"
    assert workspace.name.startswith("abc-..-..-x-")
    assert (workspace / "artifacts").is_dir()
    assert (workspace / "tmp").is_dir()
    assert (workspace / "mental_model").is_dir()
    assert (workspace / "notes").is_dir()
    assert (workspace / "logs").is_dir()
    assert (workspace / "memory").is_dir()


def test_existing_session_detail_backfills_workspace_metadata(tmp_path, monkeypatch):
    _seed_session(tmp_path, "session-live")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    detail = session_service.get_session_detail("session-live")

    assert detail is not None
    assert detail["workspacePath"] == "workspace/sessions/session-live"
    assert (tmp_path / "workspace" / "sessions" / "session-live").is_dir()
    state = load_chat_state(tmp_path)
    assert state["conversations"][0]["workspace_path"] == "workspace/sessions/session-live"


def test_run_session_turn_injects_session_workspace(tmp_path, monkeypatch):
    _seed_session(tmp_path, "session-live")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    agent = agent_directory_service.create_agent_instance(
        display_name="Workspace Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        direct_session_id="session-live",
    )
    state = load_chat_state(tmp_path)
    state["conversations"][0]["agent_id"] = agent["agentId"]
    state["conversations"][0]["agentId"] = agent["agentId"]
    save_chat_state(tmp_path, state)
    captured = {}

    class WorkspaceAwareAgent:
        def __init__(self, workspace_path=None):
            captured["workspace_path"] = str(workspace_path or "")

        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            create_file("artifacts/result.txt", "session artifact")
            task_create_tool([{"description": "session task"}], goal="session goal")
            update_self_model_tool('{"strengths": ["session scoped"]}')
            return {
                "status": "completed",
                "summary": "done",
                "raw_output": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", WorkspaceAwareAgent)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: session_service._run_session_turn(context))

    payload = session_service.submit_session_message("session-live", "do it", mental_model_enabled=False)

    agent_id = payload["agentId"]
    session_workspace = tmp_path / "workspace" / "sessions" / "session-live"
    agent_workspace = tmp_path / "workspace" / "agents" / agent_id
    assert Path(captured["workspace_path"]) == agent_workspace.resolve()
    assert payload["workspacePath"] == "workspace/sessions/session-live"
    assert (agent_workspace / "artifacts" / "result.txt").read_text(encoding="utf-8") == "session artifact"
    assert not (tmp_path / "workspace" / "artifacts" / "result.txt").exists()
    task_payload = json.loads((agent_workspace / "memory" / "tasks.json").read_text(encoding="utf-8"))
    assert task_payload["goal"] == "session goal"
    self_model = json.loads((agent_workspace / "mental_model" / "self_model.json").read_text(encoding="utf-8"))
    assert self_model["strengths"] == ["session scoped"]
    conversation_log = session_workspace / "logs" / "conversation.jsonl"
    assert conversation_log.exists()
    log_records = [
        json.loads(line)
        for line in conversation_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [record["role"] for record in log_records] == ["user", "assistant"]
    assert log_records[0]["content"] == "do it"
    assert log_records[1]["content"] == "done"
    readable_log = session_workspace / "logs" / "conversation.md"
    assert "## " in readable_log.read_text(encoding="utf-8")


def test_run_session_turn_ignores_legacy_profile_and_uses_agent_binding(tmp_path, monkeypatch):
    _seed_session(tmp_path, "session-live")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    agent = agent_directory_service.create_agent_instance(
        display_name="统一会话 Agent",
        llm_bindings={"dialogue": {"modelId": "agent-dialogue-model"}},
        direct_session_id="session-live",
        primary_mode="chat",
        prompt_template_id="prompt-chat-default",
    )
    state = load_chat_state(tmp_path)
    state["conversations"][0]["agent_profile_id"] = "subagent_explorer"
    state["conversations"][0]["agent_id"] = agent["agentId"]
    state["conversations"][0]["agentId"] = agent["agentId"]
    save_chat_state(tmp_path, state)
    captured = {}

    class ProfileAwareAgent:
        def __init__(self, workspace_path=None, config=None):
            captured["workspace_path"] = str(workspace_path or "")
            captured["primary_profile_id"] = config.llm.get_profile(role="primary").profile_id
            captured["primary_model"] = config.llm.get_profile(role="primary").model

        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "done",
                "raw_output": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    base_config = session_service.get_config()
    base_config = base_config.model_copy(deep=True)
    base_config.llm.model_library["agent-dialogue-model"] = {
        "provider_id": base_config.llm.profiles["primary"].provider_id,
        "model": "agent-dialogue-runtime",
        "streaming": False,
        "tool_calling_mode": "disabled",
    }
    base_config.llm.profiles["subagent_explorer"] = base_config.llm.profiles["primary"].model_copy(deep=True)
    base_config.llm.profiles["subagent_explorer"].profile_id = "subagent_explorer"
    base_config.llm.profiles["subagent_explorer"].model = "explorer-model"
    monkeypatch.setattr(session_service, "get_config", lambda: base_config)
    monkeypatch.setattr(session_service, "create_chat_agent", ProfileAwareAgent)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: session_service._run_session_turn(context))

    session_service.submit_session_message("session-live", "do it", mental_model_enabled=False)

    repaired_state = load_chat_state(tmp_path)
    agent_id = repaired_state["conversations"][0]["agent_id"]
    assert Path(captured["workspace_path"]) == (tmp_path / "workspace" / "agents" / agent_id).resolve()
    assert captured["primary_profile_id"] == "primary"
    assert captured["primary_model"] == "agent-dialogue-runtime"
    assert "agent_profile_id" not in repaired_state["conversations"][0]


def test_run_session_turn_prefers_agent_instance_profile_over_legacy_profile(tmp_path, monkeypatch):
    _seed_session(tmp_path, "session-live")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    agent = agent_directory_service.create_agent_instance(
        display_name="统一会话 Agent",
        llm_bindings={"dialogue": {"modelId": "model-subagent-explorer"}},
        direct_session_id="session-live",
        primary_mode="chat",
        prompt_template_id="prompt-chat-default",
    )
    state = load_chat_state(tmp_path)
    state["conversations"][0]["agent_id"] = agent["agentId"]
    state["conversations"][0]["agentId"] = agent["agentId"]
    state["conversations"][0]["agent_profile_id"] = "primary"
    save_chat_state(tmp_path, state)
    captured = {}

    class ProfileAwareAgent:
        def __init__(self, workspace_path=None, config=None):
            captured["primary_model"] = config.llm.get_profile(role="primary").model

        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "done",
                "raw_output": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    base_config = session_service.get_config().model_copy(deep=True)
    base_config.llm.profiles["primary"].model = "legacy-primary-model"
    base_config.llm.model_library["model-subagent-explorer"] = {
        "provider_id": base_config.llm.profiles["primary"].provider_id,
        "model": "agent-instance-model",
        "streaming": False,
        "tool_calling_mode": "disabled",
    }
    monkeypatch.setattr(session_service, "get_config", lambda: base_config)
    monkeypatch.setattr(session_service, "create_chat_agent", ProfileAwareAgent)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: session_service._run_session_turn(context))

    session_service.submit_session_message("session-live", "do it", mental_model_enabled=False)

    assert captured["primary_model"] == "agent-instance-model"
    repaired_state = load_chat_state(tmp_path)
    assert "agent_profile_id" not in repaired_state["conversations"][0]


def test_session_detail_repairs_stale_legacy_profile_from_agent_instance(tmp_path, monkeypatch):
    _seed_session(tmp_path, "session-live")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    agent = agent_directory_service.create_agent_instance(
        display_name="统一会话 Agent",
        llm_bindings={"dialogue": {"modelId": "model-subagent-explorer"}},
        direct_session_id="session-live",
        primary_mode="chat",
        prompt_template_id="prompt-chat-default",
    )
    state = load_chat_state(tmp_path)
    state["conversations"][0]["agent_id"] = agent["agentId"]
    state["conversations"][0]["agentId"] = agent["agentId"]
    state["conversations"][0]["agent_profile_id"] = "primary"
    state["conversations"][0]["agentProfileId"] = "primary"
    save_chat_state(tmp_path, state)
    events = []

    def capture_runtime_scene_event(*args, **kwargs):
        events.append({"event_code": args[2], "fields": kwargs.get("fields") or {}})

    monkeypatch.setattr(session_service, "record_runtime_scene_event", capture_runtime_scene_event)

    detail = session_service.get_session_detail("session-live")
    sessions = session_service.list_sessions()

    assert detail is not None
    assert detail["agentId"] == agent["agentId"]
    assert "agentProfileId" not in detail
    assert "agentProfileId" not in sessions[0]
    repaired_state = load_chat_state(tmp_path)
    repaired = repaired_state["conversations"][0]
    assert "agent_profile_id" not in repaired
    assert "agentProfileId" not in repaired
    repair_events = [event for event in events if event["event_code"] == "session.agent_legacy_model_fields_repaired"]
    assert repair_events
    assert repair_events[0]["fields"]["source"] == "AgentInstance"
    assert repair_events[0]["fields"]["removedFieldNames"] == ["agentProfileId", "agent_profile_id"]


def test_run_session_turn_seeds_agent_prompt_template_context(tmp_path, monkeypatch):
    _seed_session(tmp_path, "session-live")
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(prompt_template_service, "PROJECT_ROOT", tmp_path)
    prompt_template_service.update_prompt_template(
        "prompt-chat-custom",
        name="自定义会话提示词",
        category="chat",
        source_path="workspace/prompts/chat/custom.md",
        content="你是一个只回答统一 Agent 配置迁移问题的会话 Agent。",
    )
    agent = agent_directory_service.create_agent_instance(
        display_name="提示词会话 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        direct_session_id="session-live",
        primary_mode="chat",
        prompt_template_id="prompt-chat-custom",
    )
    state = load_chat_state(tmp_path)
    state["conversations"][0]["agent_id"] = agent["agentId"]
    state["conversations"][0]["agentId"] = agent["agentId"]
    save_chat_state(tmp_path, state)
    captured = {}

    class PromptAwareAgent:
        def __init__(self, workspace_path=None, config=None):
            self.runtime_context = ""

        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def seed_runtime_context(self, content):
            captured["runtime_context"] = content

        def run_single_turn(self, initial_prompt=None):
            return {
                "status": "completed",
                "summary": "done",
                "raw_output": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    base_config = session_service.get_config().model_copy(deep=True)
    base_config.llm.model_library["model-primary"] = {
        "provider_id": base_config.llm.profiles["primary"].provider_id,
        "model": base_config.llm.profiles["primary"].model,
        "streaming": False,
        "tool_calling_mode": "disabled",
    }
    monkeypatch.setattr(session_service, "get_config", lambda: base_config)
    monkeypatch.setattr(session_service, "create_chat_agent", PromptAwareAgent)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: session_service._run_session_turn(context))

    session_service.submit_session_message("session-live", "do it", mental_model_enabled=False)

    assert "Agent Prompt Template" in captured["runtime_context"]
    assert "prompt-chat-custom" in captured["runtime_context"]
    assert "统一 Agent 配置迁移" in captured["runtime_context"]


def test_tool_storage_overrides_are_context_local(tmp_path):
    session_workspace = tmp_path / "workspace" / "sessions" / "session-live"
    session_workspace.mkdir(parents=True)
    reset_mental_model()
    try:
        with (
            workspace_root_override(session_workspace),
            memory_storage_override(session_workspace),
            task_storage_override(session_workspace),
            active_mental_workspace(session_workspace),
        ):
            create_file("notes/local.txt", "hello")
            task_create_tool([{"description": "local task"}], goal="local goal")
            update_self_model_tool('{"weaknesses": ["local only"]}')
            scoped = get_mental_model()

        global_model = get_mental_model(workspace_root=str(tmp_path / "workspace"))

        assert scoped is not global_model
        assert (session_workspace / "notes" / "local.txt").exists()
        assert (session_workspace / "memory" / "tasks.json").exists()
        assert (session_workspace / "mental_model" / "self_model.json").exists()
    finally:
        reset_mental_model()
