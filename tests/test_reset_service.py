import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.ui.chat_state import load_chat_state, save_chat_state
from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import reset_service


@pytest.fixture
def reset_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(reset_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(reset_service, "get_web_language", lambda: "zh")
    return tmp_path


def _write(path: Path, content: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _seed_scene(project_root: Path, directory_name: str, scene_id: str, status: str) -> Path:
    scene_dir = project_root / "logs" / "runtime_scenes" / directory_name
    scene_dir.mkdir(parents=True, exist_ok=True)
    _write(
        scene_dir / "manifest.json",
        json.dumps({"runtime_scene_id": scene_id, "status": status}, ensure_ascii=False),
    )
    _write(scene_dir / "raw" / "backend.log", "scene")
    return scene_dir


def test_reset_summary_includes_memory_as_optional_item(reset_project: Path):
    _write(reset_project / "workspace" / "agent_brain.db", "db")
    _write(reset_project / "workspace" / "memory" / "long-term.md", "keep")
    _write(reset_project / "workspace" / "prompts" / "STATE_MEMORY.md", "state")
    _write(reset_project / "workspace" / "prompts" / "DYNAMIC.md", "dynamic")
    _write(reset_project / "workspace" / "chat" / "chat_state.json", "{}")
    _write(reset_project / "web" / "dist" / "index.html", "<html></html>")

    summary = reset_service.get_reset_summary()

    item_ids = {item["id"] for item in summary["items"]}
    assert "memory" in item_ids
    assert "chat_history" in item_ids
    assert "workspace_sessions" in item_ids
    assert "chat_rooms" in item_ids
    assert "teams" in item_ids
    assert "agents" in item_ids
    assert "generated_tools" in item_ids
    assert "web_dist" in item_ids
    assert "workspace" not in item_ids
    memory_item = next(item for item in summary["items"] if item["id"] == "memory")
    agents_item = next(item for item in summary["items"] if item["id"] == "agents")
    assert memory_item["category"] == "agent_state"
    assert agents_item["risk"] == "high"
    assert agents_item["defaultSelected"] is False
    assert summary["presets"] == []
    web_dist_item = next(item for item in summary["items"] if item["id"] == "web_dist")
    assert "bun run bun:build" in web_dist_item["rebuildHint"]
    protected_paths = {path for group in summary["protected"] for path in group["paths"]}
    assert "core/" in protected_paths
    assert "tools/*.py" in protected_paths
    assert "workspace/agent_brain.db" not in protected_paths
    assert "workspace/memory/" not in protected_paths
    assert "workspace/prompts/" not in protected_paths
    assert "workspace/prompts/STATE_MEMORY.md" not in protected_paths
    assert "workspace/prompts/DYNAMIC.md" in protected_paths
    assert ".docs/project-memory/" in protected_paths
    protected_labels = {group["label"] for group in summary["protected"]}
    assert "配置与模型库" in protected_labels
    assert "配置与模型绑定" not in protected_labels


def test_preview_and_execute_memory_cleanup(reset_project: Path):
    db_file = reset_project / "workspace" / "agent_brain.db"
    db_file.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_file)) as conn:
        conn.execute(
            "CREATE TABLE LongTermMemory (id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT)"
        )
        conn.execute(
            "CREATE TABLE GitCommit (commit_sha TEXT PRIMARY KEY, subject TEXT)"
        )
        conn.execute("INSERT INTO LongTermMemory (content) VALUES ('remember')")
        conn.execute("INSERT INTO GitCommit (commit_sha, subject) VALUES ('abc123', 'keep')")
    memory_file = _write(reset_project / "workspace" / "memory" / "long-term.md", "keep")
    state_memory_file = _write(reset_project / "workspace" / "prompts" / "STATE_MEMORY.md", "state")
    dynamic_prompt_file = _write(reset_project / "workspace" / "prompts" / "DYNAMIC.md", "keep")
    _write(reset_project / "workspace" / "chat" / "chat_state.json", "{}")

    preview = reset_service.preview_reset(["memory"])

    assert preview["totals"]["deleteCount"] == 3
    preview_paths = {item["path"] for item in preview["items"][0]["deleteCandidates"]}
    assert preview_paths == {
        "workspace/agent_brain.db",
        "workspace/memory",
        "workspace/prompts/STATE_MEMORY.md",
    }

    result = reset_service.execute_reset(["memory"], confirmed=True)

    assert result["totals"]["deletedCount"] == 3
    assert db_file.exists()
    with sqlite3.connect(str(db_file)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM LongTermMemory").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM GitCommit").fetchone()[0] == 1
    assert not memory_file.exists()
    assert state_memory_file.exists()
    assert state_memory_file.read_text(encoding="utf-8") == ""
    assert dynamic_prompt_file.exists()
    assert (reset_project / "workspace" / "chat" / "chat_state.json").exists()


def test_preview_is_non_destructive_and_reports_candidates(reset_project: Path):
    log_file = _write(reset_project / "log_info" / "conversation_001.jsonl", "{}\n")
    debug_file = _write(reset_project / "log_info" / "debug_001.log", "debug")

    preview = reset_service.preview_reset(["conversation_logs"])

    assert log_file.exists()
    assert debug_file.exists()
    assert preview["totals"]["deleteCount"] == 2
    paths = {item["path"] for item in preview["items"][0]["deleteCandidates"]}
    assert paths == {"log_info/conversation_001.jsonl", "log_info/debug_001.log"}


def test_execute_selected_items_deletes_only_allow_list_targets(reset_project: Path):
    _write(reset_project / "log_info" / "conversation_001.jsonl", "{}\n")
    _write(reset_project / "logs" / "agent_realtime.log", "runtime")
    _write(reset_project / "logs" / "runtime_scenes" / "keep" / "raw.log", "scene")
    _write(reset_project / "workspace" / "agent_brain.db", "db")
    _write(reset_project / "workspace" / "memory" / "long-term.md", "keep")
    _write(reset_project / "workspace" / "prompts" / "STATE_MEMORY.md", "state")
    _write(reset_project / "workspace" / "prompts" / "dynamic.md", "keep")
    _write(reset_project / "workspace" / "supervised_evolution" / "decision.json", "{}")

    result = reset_service.execute_reset(["conversation_logs", "runtime_logs"], confirmed=True)

    assert result["totals"]["deletedCount"] == 2
    assert not (reset_project / "log_info" / "conversation_001.jsonl").exists()
    assert not (reset_project / "logs" / "agent_realtime.log").exists()
    assert (reset_project / "logs" / "runtime_scenes" / "keep" / "raw.log").exists()
    assert (reset_project / "workspace" / "agent_brain.db").exists()
    assert (reset_project / "workspace" / "memory" / "long-term.md").exists()
    assert (reset_project / "workspace" / "prompts" / "STATE_MEMORY.md").exists()
    assert (reset_project / "workspace" / "prompts" / "dynamic.md").exists()
    assert (reset_project / "workspace" / "supervised_evolution" / "decision.json").exists()


def test_execute_chat_history_recreates_empty_default_session(reset_project: Path):
    save_chat_state(reset_project, {"version": 1, "conversations": [{"messages": [{"role": "user", "content": "old"}]}]})

    result = reset_service.execute_reset(["chat_history"], confirmed=True)
    state = load_chat_state(reset_project)

    assert result["items"][0]["deleted"][0]["action"] == "reset"
    assert state["conversations"][0]["messages"] == []
    assert state["active_conversation_id"] == "default"


def test_reset_can_clear_sessions_rooms_teams_agents_and_bus(reset_project: Path):
    _write(reset_project / "workspace" / "sessions" / "session-a" / "state.json", "{}")
    _write(reset_project / "workspace" / "chat_rooms" / "rooms.json", "[]")
    _write(reset_project / "workspace" / "teams" / "teams.json", "[]")
    _write(reset_project / "workspace" / "agents" / "agents.json", json.dumps({"agents": [{"id": "agent-a"}]}))
    _write(reset_project / "workspace" / "agents" / "agent-a" / "events" / "event.jsonl", "{}\n")
    _write(reset_project / "workspace" / "shared" / "keep.txt", "shared")
    _write(reset_project / "workspace" / "project_agent_bus" / "queue.jsonl", "{}\n")

    preview = reset_service.preview_reset([
        "workspace_sessions",
        "chat_rooms",
        "teams",
        "agents",
        "project_agent_bus",
    ])
    preview_paths = {
        entry["path"]
        for item in preview["items"]
        for entry in item["deleteCandidates"]
    }

    assert preview_paths == {
        "workspace/sessions",
        "workspace/chat_rooms",
        "workspace/teams",
        "workspace/agents",
        "workspace/project_agent_bus",
    }

    result = reset_service.execute_reset([
        "workspace_sessions",
        "chat_rooms",
        "teams",
        "agents",
        "project_agent_bus",
    ], confirmed=True)

    assert result["totals"]["failedCount"] == 0
    assert not (reset_project / "workspace" / "sessions").exists()
    assert not (reset_project / "workspace" / "chat_rooms").exists()
    assert not (reset_project / "workspace" / "teams").exists()
    assert not (reset_project / "workspace" / "project_agent_bus").exists()
    agents_registry = reset_project / "workspace" / "agents" / "agents.json"
    assert agents_registry.exists()
    assert json.loads(agents_registry.read_text(encoding="utf-8"))["agents"] == []
    assert (reset_project / "workspace" / "shared" / "keep.txt").exists()


def test_generated_tools_reset_keeps_source_tools(reset_project: Path):
    generated_tools = _write(
        reset_project / "workspace" / "tool_registry" / "generated_tools.json",
        json.dumps([{"name": "draft_tool"}]),
    )
    source_tool = _write(reset_project / "tools" / "real_tool.py", "print('keep')\n")

    result = reset_service.execute_reset(["generated_tools"], confirmed=True)

    assert result["totals"]["deletedCount"] == 1
    assert generated_tools.exists()
    assert json.loads(generated_tools.read_text(encoding="utf-8")) == []
    assert source_tool.exists()


def test_reset_clears_agent_config_state(reset_project: Path):
    mode_bindings = _write(reset_project / "workspace" / "agent_config" / "mode_bindings.json", "{}")
    prompt_templates = _write(reset_project / "workspace" / "agent_config" / "prompt_templates.json", "{}")
    dynamic_prompt = _write(reset_project / "workspace" / "prompts" / "DYNAMIC.md", "keep")

    result = reset_service.execute_reset(["agent_config_state"], confirmed=True)

    assert result["totals"]["deletedCount"] == 2
    assert not mode_bindings.exists()
    assert not prompt_templates.exists()
    assert dynamic_prompt.exists()


def test_chat_history_is_available_even_before_state_file_exists(reset_project: Path):
    preview = reset_service.preview_reset(["chat_history"])

    assert preview["totals"]["deleteCount"] == 1
    assert preview["items"][0]["deleteCandidates"][0]["action"] == "reset"

    result = reset_service.execute_reset(["chat_history"], confirmed=True)

    assert result["totals"]["deletedCount"] == 1
    assert (reset_project / "workspace" / "chat" / "chat_state.json").exists()


def test_runtime_scene_cleanup_skips_running_and_current_scene(reset_project: Path):
    stopped = _seed_scene(reset_project, "20260501T000000Z__stopped", "stopped", "stopped")
    running = _seed_scene(reset_project, "20260501T010000Z__running", "running", "running")
    current = _seed_scene(reset_project, "20260501T020000Z__current", "current", "stopped")
    _write(
        reset_project / ".runtime" / "launcher" / "state.json",
        json.dumps({"runtimeSceneDir": str(current)}, ensure_ascii=False),
    )

    preview = reset_service.preview_reset(["stopped_runtime_scenes"])
    protected_paths = {item["path"] for item in preview["items"][0]["protected"]}
    delete_paths = {item["path"] for item in preview["items"][0]["deleteCandidates"]}

    assert "logs/runtime_scenes/20260501T000000Z__stopped" in delete_paths
    assert "logs/runtime_scenes/20260501T010000Z__running" in protected_paths
    assert "logs/runtime_scenes/20260501T020000Z__current" in protected_paths

    result = reset_service.execute_reset(["stopped_runtime_scenes"], confirmed=True)

    assert result["totals"]["deletedCount"] == 1
    assert not stopped.exists()
    assert running.exists()
    assert current.exists()


def test_browser_profile_cleanup_protects_current_profile(reset_project: Path):
    current = reset_project / ".runtime" / "launcher" / "edge-app-profile"
    old = reset_project / ".runtime" / "old-test-profile"
    _write(current / "Default" / "LOCK", "locked")
    _write(old / "Default" / "Preferences", "{}")
    _write(
        reset_project / ".runtime" / "launcher" / "state.json",
        json.dumps({"browserProfileDir": str(current)}, ensure_ascii=False),
    )

    result = reset_service.execute_reset(["browser_profiles"], confirmed=True)

    assert result["totals"]["deletedCount"] == 1
    assert current.exists()
    assert not old.exists()


def test_workspace_runtime_residue_cleanup(reset_project: Path):
    workspace_profile = _write(reset_project / "workspace" / "edge-headless-profile" / "Default" / "Preferences", "{}")
    workspace_log = _write(reset_project / "workspace" / "server.err.log", "err")
    workspace_logs_dir = _write(reset_project / "workspace" / "logs" / "service.log", "log")
    diagnostic_payload = _write(reset_project / "log_info" / "payloads" / "payload.json", "{}")
    root_tmp = _write(reset_project / ".tmp-vite-chat2.log", "tmp")
    root_tmp_dir = _write(reset_project / "tmp_prompt_debug" / "trace.log", "tmp")
    runtime_preview = _write(reset_project / ".runtime" / "codex-preview" / "trace.log", "tmp")
    runtime_tmp = _write(reset_project / ".runtime" / "tmp-run" / "trace.log", "tmp")

    result = reset_service.execute_reset([
        "workspace_browser_profiles",
        "workspace_service_logs",
        "diagnostic_payloads",
        "root_temp_artifacts",
        "runtime_preview_artifacts",
    ], confirmed=True)

    assert result["totals"]["failedCount"] == 0
    assert not workspace_profile.exists()
    assert not workspace_log.exists()
    assert not workspace_logs_dir.exists()
    assert not diagnostic_payload.exists()
    assert not root_tmp.exists()
    assert not root_tmp_dir.exists()
    assert not runtime_preview.exists()
    assert not runtime_tmp.exists()


def test_reset_execution_keeps_protected_runtime_targets_out_of_candidate_events(
    reset_project: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    current_scene = _seed_scene(reset_project, "20260501T020000Z__current", "current", "stopped")
    stopped_scene = _seed_scene(reset_project, "20260501T000000Z__stopped", "stopped", "stopped")
    current_profile = reset_project / ".runtime" / "launcher" / "edge-app-profile"
    old_profile = reset_project / ".runtime" / "old-test-profile"
    _write(current_profile / "Default" / "LOCK", "locked")
    _write(old_profile / "Default" / "Preferences", "{}")
    _write(
        reset_project / ".runtime" / "launcher" / "state.json",
        json.dumps(
            {
                "runtimeSceneDir": str(current_scene),
                "browserProfileDir": str(current_profile),
            },
            ensure_ascii=False,
        ),
    )
    events: list[dict] = []

    def capture_reset_event(component: str, phase: str, event_code: str, **kwargs):
        events.append(
            {
                "component": component,
                "phase": phase,
                "eventCode": event_code,
                "fields": kwargs.get("fields") or {},
            }
        )

    monkeypatch.setattr(reset_service, "record_runtime_scene_event", capture_reset_event)

    result = reset_service.execute_reset(["stopped_runtime_scenes", "browser_profiles"], confirmed=True)

    assert result["totals"]["deletedCount"] == 2
    assert result["totals"]["protectedCount"] == 2
    assert current_scene.exists()
    assert current_profile.exists()
    assert not stopped_scene.exists()
    assert not old_profile.exists()
    protected_paths = {
        item["path"]
        for result_item in result["items"]
        for item in result_item["protected"]
    }
    assert protected_paths == {
        "logs/runtime_scenes/20260501T020000Z__current",
        ".runtime/launcher/edge-app-profile",
    }

    candidate_events = [event for event in events if event["eventCode"].startswith("reset.candidate.")]
    assert {event["eventCode"] for event in candidate_events} == {"reset.candidate.deleted"}
    assert {event["fields"]["path"] for event in candidate_events} == {
        "logs/runtime_scenes/20260501T000000Z__stopped",
        ".runtime/old-test-profile",
    }


def test_unknown_reset_item_is_rejected(reset_project: Path):
    with pytest.raises(ValueError, match="Unknown reset item id"):
        reset_service.preview_reset(["../workspace"])


def test_reset_routes_expose_preview_and_execute(reset_project: Path):
    _write(reset_project / "web" / "dist" / "index.html", "<html></html>")
    client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})

    summary_response = client.get("/api/reset/summary")
    preview_response = client.post("/api/reset/preview", json={"itemIds": ["web_dist"]})
    rejected_response = client.post("/api/reset/preview", json={"itemIds": ["bad"]})
    execute_response = client.post("/api/reset/execute", json={"itemIds": ["web_dist"], "confirmed": True})

    assert summary_response.status_code == 200
    assert summary_response.json()["mode"] == "custom"
    assert preview_response.status_code == 200
    assert preview_response.json()["totals"]["deleteCount"] == 1
    assert rejected_response.status_code == 400
    assert execute_response.status_code == 200
    assert not (reset_project / "web" / "dist").exists()
