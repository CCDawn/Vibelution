from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_launcher_module():
    script_path = Path(__file__).parents[1] / "scripts" / "vibelution_launcher.py"
    spec = importlib.util.spec_from_file_location("vibelution_launcher_runtime_scene_test", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_python_launcher_rotates_active_runtime_scene_for_each_start(tmp_path, monkeypatch) -> None:
    launcher = _load_launcher_module()
    runtime_dir = tmp_path / ".runtime" / "launcher"
    scene_root = tmp_path / "logs" / "runtime_scenes"
    active_path = runtime_dir / "active-runtime-scene.json"
    monkeypatch.setattr(launcher, "RUNTIME_DIR", runtime_dir)
    monkeypatch.setattr(launcher, "RUNTIME_SCENE_ROOT", scene_root)
    monkeypatch.setattr(launcher, "ACTIVE_RUNTIME_SCENE_PATH", active_path)

    first = launcher._start_runtime_scene("python_launcher_start")
    first_dir = Path(first["runtimeSceneDir"])
    (first_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "runtime_scene_id": first["runtimeSceneId"],
                "started_at": first["startedAt"],
                "status": "running",
            }
        ),
        encoding="utf-8",
    )
    (runtime_dir / "backend.stdout.log").write_text("startup tail\n", encoding="utf-8")
    second = launcher._start_runtime_scene("python_launcher_start")

    assert first["runtimeSceneId"] != second["runtimeSceneId"]
    assert first["runtimeSceneDir"] != second["runtimeSceneDir"]
    assert Path(first["runtimeSceneDir"]).is_dir()
    assert Path(second["runtimeSceneDir"]).is_dir()
    assert json.loads(active_path.read_text(encoding="utf-8")) == second
    for relative_dir in ("events", "raw", "conversations", "agent", "artifacts"):
        assert (Path(second["runtimeSceneDir"]) / relative_dir).is_dir()
    first_manifest = json.loads((first_dir / "manifest.json").read_text(encoding="utf-8"))
    assert first_manifest["status"] == "stopped"
    assert first_manifest["result"] == "orphan_reconciled"
    assert first_manifest["ended_at"]
    assert (first_dir / "raw" / "backend.stdout.log").read_text(encoding="utf-8") == "startup tail\n"


def test_runtime_scene_seal_is_idempotent_and_stop_uses_same_helper(tmp_path, monkeypatch) -> None:
    launcher = _load_launcher_module()
    runtime_dir = tmp_path / ".runtime" / "launcher"
    scene_root = tmp_path / "logs" / "runtime_scenes"
    active_path = runtime_dir / "active-runtime-scene.json"
    state_path = runtime_dir / "state.json"
    monkeypatch.setattr(launcher, "RUNTIME_DIR", runtime_dir)
    monkeypatch.setattr(launcher, "RUNTIME_SCENE_ROOT", scene_root)
    monkeypatch.setattr(launcher, "ACTIVE_RUNTIME_SCENE_PATH", active_path)
    monkeypatch.setattr(launcher, "STATE_PATH", state_path)
    scene = launcher._start_runtime_scene("python_launcher_start")
    scene_dir = Path(scene["runtimeSceneDir"])
    (scene_dir / "manifest.json").write_text(
        json.dumps({"runtime_scene_id": scene["runtimeSceneId"], "status": "running"}),
        encoding="utf-8",
    )
    launcher._write_state({"backendPort": 8123, "backendPid": 10})
    monkeypatch.setattr(launcher, "_retire_project_workbench_instance", lambda _state, _port: [10])
    monkeypatch.setattr(launcher, "_listening_pid_for_port", lambda _port: 0)

    launcher._stop_backend()
    first_bytes = (scene_dir / "manifest.json").read_bytes()
    launcher._seal_active_runtime_scene("explicit_stop", "Workbench processes confirmed closed.")

    manifest = json.loads(first_bytes)
    assert manifest["status"] == "stopped"
    assert manifest["result"] == "explicit_stop"
    assert manifest["stop_reason"] == "Workbench processes confirmed closed."
    assert (scene_dir / "manifest.json").read_bytes() == first_bytes
