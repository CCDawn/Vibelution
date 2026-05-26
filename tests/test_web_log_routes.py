import json

from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import log_service


client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


def _seed_runtime_scene_root(project_root):
    (project_root / "logs" / "runtime_scenes" / "scene-tree").mkdir(parents=True, exist_ok=True)


def test_logs_roots_and_tree_are_read_only(tmp_path, monkeypatch):
    runtime_log = tmp_path / "logs" / "agent_realtime.log"
    runtime_log.parent.mkdir(parents=True, exist_ok=True)
    runtime_log.write_text("runtime line\n", encoding="utf-8")
    _seed_runtime_scene_root(tmp_path)

    workspace_log = tmp_path / "workspace" / "logs" / "turns" / "latest.md"
    workspace_log.parent.mkdir(parents=True, exist_ok=True)
    workspace_log.write_text("# latest transcript\n", encoding="utf-8")

    conversation_log = tmp_path / "log_info" / "chat.jsonl"
    conversation_log.parent.mkdir(parents=True, exist_ok=True)
    conversation_log.write_text('{"message":"ok"}\n', encoding="utf-8")

    monkeypatch.setattr(log_service, "PROJECT_ROOT", tmp_path)

    roots_response = client.get("/api/logs/roots")
    tree_response = client.get("/api/logs/tree", params={"root": "workspace_logs"})
    content_response = client.get(
        "/api/logs/content",
        params={"root": "workspace_logs", "path": "turns/latest.md"},
    )

    assert roots_response.status_code == 200
    roots_payload = roots_response.json()
    assert [
        {"id": item["id"], "path": item["path"], "exists": item["exists"]}
        for item in roots_payload
    ] == [
        {"id": "runtime_scenes", "path": "logs/runtime_scenes", "exists": True},
        {"id": "runtime_logs", "path": "logs", "exists": True},
        {"id": "workspace_logs", "path": "workspace/logs", "exists": True},
        {"id": "conversation_logs", "path": "log_info", "exists": True},
    ]
    runtime_root = next(item for item in roots_payload if item["id"] == "runtime_logs")
    assert runtime_root["summary"]["fileCount"] == 1
    assert runtime_root["summary"]["latestPath"] == "agent_realtime.log"
    assert "后端" in runtime_root["summary"]["userGuide"]
    conversation_root = next(item for item in roots_payload if item["id"] == "conversation_logs")
    assert conversation_root["summary"]["fileCount"] == 1
    assert "conversation_" in conversation_root["summary"]["agentGuide"] or "debug_" in conversation_root["summary"]["agentGuide"]

    assert tree_response.status_code == 200
    tree_payload = tree_response.json()
    assert tree_payload["root"]["id"] == "workspace_logs"
    assert tree_payload["root"]["path"] == "workspace/logs"
    assert tree_payload["nodes"][0]["name"] == "turns"
    assert tree_payload["nodes"][0]["children"][0]["path"] == "turns/latest.md"

    assert content_response.status_code == 200
    content_payload = content_response.json()
    assert content_payload["path"] == "workspace/logs/turns/latest.md"
    assert content_payload["relativePath"] == "turns/latest.md"
    assert "# latest transcript" in content_payload["content"]
    assert content_payload["diagnostics"]["severity"] == "info"
    assert content_payload["diagnostics"]["lineCount"] == 1
    assert "正常路径" in content_payload["diagnostics"]["userSummary"]

    runtime_tree_response = client.get("/api/logs/tree", params={"root": "runtime_logs"})
    assert runtime_tree_response.status_code == 200
    runtime_tree_payload = runtime_tree_response.json()
    assert all(node["name"] != "runtime_scenes" for node in runtime_tree_payload["nodes"])


def test_log_content_returns_user_and_agent_diagnostics(tmp_path, monkeypatch):
    conversation_log = tmp_path / "log_info" / "conversation_debug.jsonl"
    conversation_log.parent.mkdir(parents=True, exist_ok=True)
    conversation_log.write_text(
        "\n".join(
            [
                json.dumps({"type": "external_request", "content": "复现问题"}, ensure_ascii=False),
                json.dumps({"type": "tool_call", "tool": "read_file_tool", "status": "success"}, ensure_ascii=False),
                "Traceback (most recent call last): RuntimeError: failed to stop subagent",
                "WARNING retrying stop request",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(log_service, "PROJECT_ROOT", tmp_path)

    response = client.get(
        "/api/logs/content",
        params={"root": "conversation_logs", "path": "conversation_debug.jsonl"},
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    diagnostics = payload["diagnostics"]
    assert diagnostics["severity"] == "error"
    assert diagnostics["lineCount"] == 4
    assert diagnostics["errorCount"] == 1
    assert diagnostics["warningCount"] == 1
    assert diagnostics["firstSignalLine"] == 3
    assert "failed to stop subagent" in diagnostics["firstSignalPreview"]
    assert diagnostics["topEventTypes"][0] == {"type": "external_request", "count": 1}
    assert "conversation_logs/conversation_debug.jsonl:3" in diagnostics["agentHint"]
    assert "错误筛选" in diagnostics["suggestedNextStep"]


def test_log_content_rejects_path_escape(tmp_path, monkeypatch):
    (tmp_path / "logs").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(log_service, "PROJECT_ROOT", tmp_path)

    response = client.get(
        "/api/logs/content",
        params={"root": "runtime_logs", "path": "../log_info/chat.jsonl"},
    )

    assert response.status_code == 400
    assert "selected log root" in response.json()["detail"]


def test_clear_log_file_empties_content_but_keeps_file(tmp_path, monkeypatch):
    runtime_log = tmp_path / "logs" / "agent_realtime.log"
    runtime_log.parent.mkdir(parents=True, exist_ok=True)
    runtime_log.write_text("runtime line\nsecond line\n", encoding="utf-8")
    monkeypatch.setattr(log_service, "PROJECT_ROOT", tmp_path)

    response = client.post(
        "/api/logs/clear",
        json={"root": "runtime_logs", "path": "agent_realtime.log"},
    )

    assert response.status_code == 200, response.json()
    payload = response.json()
    assert payload["relativePath"] == "agent_realtime.log"
    assert payload["content"] == ""
    assert payload["truncated"] is False
    assert runtime_log.exists()
    assert runtime_log.read_text(encoding="utf-8") == ""


def test_delete_logs_removes_selected_files_only(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "logs"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    keep_log = runtime_dir / "keep.log"
    delete_a = runtime_dir / "delete_a.log"
    delete_b = runtime_dir / "delete_b.log"
    keep_log.write_text("keep\n", encoding="utf-8")
    delete_a.write_text("a\n", encoding="utf-8")
    delete_b.write_text("b\n", encoding="utf-8")
    monkeypatch.setattr(log_service, "PROJECT_ROOT", tmp_path)

    response = client.post(
        "/api/logs/delete",
        json={
            "root": "runtime_logs",
            "paths": ["delete_a.log", "delete_b.log", "delete_a.log"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["deletedCount"] == 2
    assert payload["deletedPaths"] == ["delete_a.log", "delete_b.log"]
    assert payload["missingPaths"] == []
    assert keep_log.exists()
    assert not delete_a.exists()
    assert not delete_b.exists()


def test_delete_logs_rejects_directory_targets(tmp_path, monkeypatch):
    turns_dir = tmp_path / "workspace" / "logs" / "turns"
    turns_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(log_service, "PROJECT_ROOT", tmp_path)

    response = client.post(
        "/api/logs/delete",
        json={"root": "workspace_logs", "paths": ["turns"]},
    )

    assert response.status_code == 400
    assert "Only log files can be deleted" in response.json()["detail"]
