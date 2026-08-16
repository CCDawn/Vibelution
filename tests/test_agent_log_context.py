import json
from pathlib import Path

import pytest

from core.diagnostics.agent_log_context import build_agent_log_context


def test_build_agent_log_context_reads_active_scene_and_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "core.diagnostics.agent_log_context.resolve_active_project_storage_paths",
        lambda _root: _storage_paths(tmp_path),
    )
    scene_dir = tmp_path / "logs" / "runtime_scenes" / "20260816T120000Z__demo"
    launcher_dir = tmp_path / ".runtime" / "launcher"
    scene_dir.mkdir(parents=True)
    launcher_dir.mkdir(parents=True)
    summary = {
        "package_id": "demo",
        "display_name": "demo scene",
        "status": "running",
        "agent_brief": {
            "diagnosis_status": "active_issue",
            "needs_action": True,
            "primary_issue": "launcher.startup.failed",
            "evidence_refs": ["raw/launcher-control.log"],
        },
        "diagnostic_entrypoint": {
            "recommended_order": ["summary.json", "raw/launcher-control.log"],
        },
    }
    (scene_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    (launcher_dir / "active-runtime-scene.json").write_text(
        json.dumps(
            {
                "runtimeSceneId": "demo",
                "runtimeSceneDir": str(scene_dir),
            }
        ),
        encoding="utf-8",
    )

    payload = build_agent_log_context(tmp_path)

    assert payload["tool"] == "agent_log_context"
    assert payload["mode"] == "context"
    assert payload["selectionStatus"] == "active_scene"
    assert payload["currentScene"]["present"] is True
    assert payload["agentBrief"]["primary_issue"] == "launcher.startup.failed"
    assert payload["diagnosticEntrypoint"]["recommended_order"][1] == "raw/launcher-control.log"


def test_build_agent_log_context_includes_session_slice(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "core.diagnostics.agent_log_context.resolve_active_project_storage_paths",
        lambda _root: _storage_paths(tmp_path),
    )
    (tmp_path / "logs" / "runtime_scenes").mkdir(parents=True)
    (tmp_path / ".runtime" / "launcher").mkdir(parents=True)

    payload = build_agent_log_context(
        tmp_path,
        session_id="session-demo",
        turn_id="turn-demo",
        max_runtime_matches=0,
    )

    assert payload["session"]["sessionId"] == "session-demo"
    assert payload["session"]["turnId"] == "turn-demo"
    assert "journal" in payload["session"]


def test_build_agent_log_context_marks_missing_active_scene(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "core.diagnostics.agent_log_context.resolve_active_project_storage_paths",
        lambda _root: _storage_paths(tmp_path),
    )
    (tmp_path / "logs" / "runtime_scenes").mkdir(parents=True)
    (tmp_path / ".runtime" / "launcher").mkdir(parents=True)

    payload = build_agent_log_context(tmp_path)

    assert payload["selectionStatus"] == "no_active_scene"
    assert payload["currentScene"]["present"] is False


def _storage_paths(tmp_path: Path):
    class _Storage:
        project_root = tmp_path
        runtime = tmp_path / ".runtime"
        logs = tmp_path / "logs"
        migrated = False

        def as_dict(self):
            return {
                "runtime": str(self.runtime),
                "logs": str(self.logs),
                "migrated": "false",
            }

    return _Storage()
