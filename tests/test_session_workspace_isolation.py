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
from core.web.services import session_service
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

    session_workspace = tmp_path / "workspace" / "sessions" / "session-live"
    assert Path(captured["workspace_path"]) == session_workspace.resolve()
    assert payload["workspacePath"] == "workspace/sessions/session-live"
    assert (session_workspace / "artifacts" / "result.txt").read_text(encoding="utf-8") == "session artifact"
    assert not (tmp_path / "workspace" / "artifacts" / "result.txt").exists()
    task_payload = json.loads((session_workspace / "memory" / "tasks.json").read_text(encoding="utf-8"))
    assert task_payload["goal"] == "session goal"
    self_model = json.loads((session_workspace / "mental_model" / "self_model.json").read_text(encoding="utf-8"))
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
