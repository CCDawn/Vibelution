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


def test_python_launcher_unsupported_action_reports_supported_actions(tmp_path, monkeypatch, capsys) -> None:
    launcher = _load_launcher_module()
    runtime_dir = tmp_path / ".runtime" / "launcher"
    state_path = runtime_dir / "state.json"
    monkeypatch.setattr(launcher, "RUNTIME_DIR", runtime_dir)
    monkeypatch.setattr(launcher, "STATE_PATH", state_path)

    exit_code = launcher.main(["--action", "status"])

    assert exit_code == 1
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["phase"] == "failed"
    message = str(state["failureMessage"])
    assert "Unsupported launcher action: status" in message
    assert "supported: start, stop, focus, restart" in message
    assert "vibelution_launcher.ps1" in message
    captured = capsys.readouterr()
    assert "supported: start, stop, focus, restart" in captured.err


def test_focus_keeps_validated_live_backend_pid(tmp_path, monkeypatch) -> None:
    launcher = _load_launcher_module()
    runtime_dir = tmp_path / ".runtime" / "launcher"
    state_path = runtime_dir / "state.json"
    monkeypatch.setattr(launcher, "RUNTIME_DIR", runtime_dir)
    monkeypatch.setattr(launcher, "STATE_PATH", state_path)
    launcher._write_state({"backendPid": 4321, "backendPort": 8123})
    monkeypatch.setattr(launcher, "_pid_alive", lambda pid: pid == 4321)
    monkeypatch.setattr(
        launcher,
        "_verify_project_backend_pid",
        lambda pid: "project" if pid == 4321 else "foreign",
    )
    monkeypatch.setattr(launcher, "_backend_healthy", lambda port, host="127.0.0.1": True)
    monkeypatch.setattr(launcher, "_listening_pid_for_port", lambda port: 4321)

    state = launcher._focus_backend(8123, "127.0.0.1")

    assert state["backendPid"] == 4321
    assert "focusAdvisoryNote" not in state
    assert json.loads(state_path.read_text(encoding="utf-8")) == state


def test_focus_replaces_foreign_recorded_pid_with_verified_port_owner(tmp_path, monkeypatch) -> None:
    launcher = _load_launcher_module()
    runtime_dir = tmp_path / ".runtime" / "launcher"
    state_path = runtime_dir / "state.json"
    monkeypatch.setattr(launcher, "RUNTIME_DIR", runtime_dir)
    monkeypatch.setattr(launcher, "STATE_PATH", state_path)
    launcher._write_state({"backendPid": 999, "backendPort": 8123})
    monkeypatch.setattr(launcher, "_pid_alive", lambda pid: pid == 999)
    monkeypatch.setattr(
        launcher,
        "_verify_project_backend_pid",
        lambda pid: "project" if pid == 4322 else "foreign",
    )
    monkeypatch.setattr(launcher, "_backend_healthy", lambda port, host="127.0.0.1": True)
    monkeypatch.setattr(launcher, "_listening_pid_for_port", lambda port: 4322)

    state = launcher._focus_backend(8123, "127.0.0.1")

    assert state["backendPid"] == 4322
    assert "unrelated process" in str(state.get("focusAdvisoryNote"))
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["backendPid"] == 4322
    assert persisted["desiredState"] == "open"


def test_focus_clears_dead_recorded_pid_without_adopting_foreign_owner(tmp_path, monkeypatch) -> None:
    launcher = _load_launcher_module()
    runtime_dir = tmp_path / ".runtime" / "launcher"
    state_path = runtime_dir / "state.json"
    monkeypatch.setattr(launcher, "RUNTIME_DIR", runtime_dir)
    monkeypatch.setattr(launcher, "STATE_PATH", state_path)
    launcher._write_state({"backendPid": 999, "backendPort": 8123})
    monkeypatch.setattr(launcher, "_pid_alive", lambda pid: False)
    monkeypatch.setattr(launcher, "_verify_project_backend_pid", lambda pid: "foreign")
    monkeypatch.setattr(launcher, "_backend_healthy", lambda port, host="127.0.0.1": True)
    monkeypatch.setattr(launcher, "_listening_pid_for_port", lambda port: 555)

    state = launcher._focus_backend(8123, "127.0.0.1")

    # Focus itself still succeeds for the user's window/refresh goal, but the
    # dead recorded pid and the unverified port owner are never registered.
    assert state["backendPid"] == 0
    assert state["desiredState"] == "open"
    assert state["observedState"] == "open"
    assert "has exited" in str(state.get("focusAdvisoryNote"))


def test_project_backend_verdict_classifies_command_line(monkeypatch) -> None:
    launcher = _load_launcher_module()
    project_root = Path("D:/dev-projects/Vibelution")
    monkeypatch.setattr(launcher, "PROJECT_ROOT", project_root)

    command_line = (
        f"{project_root / '.venv/Scripts/pythonw.exe'} "
        f"{project_root / 'scripts/web_workbench.py'} --port 8000"
    )
    assert launcher._project_backend_verdict_from_command_line(command_line) == "project"
    assert launcher._project_backend_verdict_from_command_line(
        "C:/Windows/System32/notepad.exe"
    ) == "foreign"
    assert launcher._project_backend_verdict_from_command_line("") == "unknown"
