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
    (scene_dir / "raw").mkdir(parents=True)
    (scene_dir / "raw" / "launcher-control.log").write_text("startup ok\n", encoding="utf-8")
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
    assert payload["schemaVersion"] == 2
    assert payload["selectionStatus"] == "active_scene"
    assert payload["currentScene"]["present"] is True
    assert payload["agentBrief"]["primary_issue"] == "launcher.startup.failed"
    assert payload["diagnosticEntrypoint"]["recommended_order"][1] == "raw/launcher-control.log"
    launcher_ref = next(
        item for item in payload["resolvedEvidenceRefs"] if item["ref"] == "raw/launcher-control.log"
    )
    assert launcher_ref["exists"] is True
    assert launcher_ref["absolutePath"].endswith("raw\\launcher-control.log") or launcher_ref[
        "absolutePath"
    ].endswith("raw/launcher-control.log")
    assert "launcher-control.log" in launcher_ref["displayPath"]


def test_build_agent_log_context_resolved_evidence_warns_on_large_logs(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "core.diagnostics.agent_log_context.resolve_active_project_storage_paths",
        lambda _root: _storage_paths(tmp_path),
    )
    scene_dir = tmp_path / "logs" / "runtime_scenes" / "20260816T120000Z__demo"
    launcher_dir = tmp_path / ".runtime" / "launcher"
    scene_dir.mkdir(parents=True)
    launcher_dir.mkdir(parents=True)
    (scene_dir / "raw").mkdir(parents=True)
    large_path = scene_dir / "raw" / "backend.api.log"
    large_path.write_bytes(b"x" * (8 * 1024 * 1024 + 1))
    summary = {
        "agent_brief": {"evidence_refs": ["raw/backend.api.log"]},
        "diagnostic_entrypoint": {},
    }
    (scene_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    (launcher_dir / "active-runtime-scene.json").write_text(
        json.dumps({"runtimeSceneId": "demo", "runtimeSceneDir": str(scene_dir)}),
        encoding="utf-8",
    )

    payload = build_agent_log_context(tmp_path)
    large_ref = payload["resolvedEvidenceRefs"][0]

    assert large_ref["exists"] is True
    assert large_ref["warning"] == "do_not_read_full_file_use_scene_raw_or_tail"


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
