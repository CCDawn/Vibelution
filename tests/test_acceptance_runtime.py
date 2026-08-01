from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


def _load_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "acceptance_runtime.py"
    spec = importlib.util.spec_from_file_location("acceptance_runtime_under_test", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def runtime():
    return _load_module()


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    (project / ".git").mkdir(parents=True)
    (project / "scripts").mkdir()
    (project / "scripts" / "web_workbench.py").write_text("# fixture\n", encoding="utf-8")
    (project / "web").mkdir()
    (project / "web" / "package.json").write_text("{}\n", encoding="utf-8")
    vite_entry = project / "web" / "node_modules" / "vite" / "bin" / "vite.js"
    vite_entry.parent.mkdir(parents=True, exist_ok=True)
    vite_entry.write_text("// fixture\n", encoding="utf-8")
    return project


def test_frontend_command_tracks_vite_node_process_directly(runtime, tmp_path, monkeypatch):
    project = _project(tmp_path)
    vite_entry = project / "web" / "node_modules" / "vite" / "bin" / "vite.js"
    monkeypatch.setattr(
        runtime.shutil,
        "which",
        lambda name: "C:/node/node.exe" if name in {"node.exe", "node"} else None,
    )

    command = runtime._frontend_command(project=project, frontend_port=5200)

    assert command[:2] == ["C:/node/node.exe", str(vite_entry.resolve())]
    assert command[2:] == ["--host", "127.0.0.1", "--port", "5200", "--strictPort"]
    assert all("npm" not in part.lower() for part in command)


def test_two_instances_receive_distinct_atomic_port_leases(runtime, tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "_port_available", lambda port, host="127.0.0.1": True)
    monkeypatch.setattr(runtime, "_process_create_time", lambda pid: 1.0)
    monkeypatch.setattr(runtime, "_process_matches", lambda pid, create_time: True)
    lease_root = tmp_path / ".leases"

    first_backend = runtime._allocate_port(
        lease_root=lease_root,
        kind="backend",
        instance_id="task-a",
        candidates=range(8100, 8102),
    )
    second_backend = runtime._allocate_port(
        lease_root=lease_root,
        kind="backend",
        instance_id="task-b",
        candidates=range(8100, 8102),
    )
    first_frontend = runtime._allocate_port(
        lease_root=lease_root,
        kind="frontend",
        instance_id="task-a",
        candidates=range(5200, 5202),
    )
    second_frontend = runtime._allocate_port(
        lease_root=lease_root,
        kind="frontend",
        instance_id="task-b",
        candidates=range(5200, 5202),
    )

    assert (first_backend, second_backend) == (8100, 8101)
    assert (first_frontend, second_frontend) == (5200, 5201)


def test_instance_environment_and_state_are_private(runtime, tmp_path, monkeypatch):
    project = _project(tmp_path)
    runtime_home = tmp_path / "acceptance"
    processes = []

    class FakeProcess:
        next_pid = 4100

        def __init__(self):
            self.pid = FakeProcess.next_pid
            FakeProcess.next_pid += 1
            self.terminated = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return 0

        def kill(self):
            self.terminated = True

    captured_envs = []
    captured_cwds = []

    def fake_spawn(command, *, cwd, env, stdout_path, stderr_path):
        process = FakeProcess()
        processes.append(process)
        captured_cwds.append(Path(cwd))
        captured_envs.append(dict(env))
        return process

    monkeypatch.setattr(runtime, "_spawn", fake_spawn)
    monkeypatch.setattr(runtime, "_wait_ready", lambda **kwargs: None)
    monkeypatch.setattr(runtime, "_process_create_time", lambda pid: float(pid))
    monkeypatch.setattr(runtime, "_process_matches", lambda pid, create_time: True)
    monkeypatch.setattr(runtime, "_port_available", lambda port, host="127.0.0.1": True)
    monkeypatch.setattr(runtime, "_source_commit", lambda project_root: "abc123")
    monkeypatch.setattr(runtime.shutil, "which", lambda name: "node.exe")

    state = runtime.start_instance(
        instance_id="task-a",
        project_root=project,
        runtime_home=runtime_home,
    )

    instance_root = (runtime_home / "task-a").resolve()
    assert Path(state["dataRoot"]).is_relative_to(instance_root)
    assert Path(state["configRoot"]).is_relative_to(instance_root)
    assert Path(state["logsRoot"]).is_relative_to(instance_root)
    assert state["sourceCommit"] == "abc123"
    assert state["status"] == "running"
    assert state["frontendUrl"] == f"http://127.0.0.1:{state['ports']['frontend']}"
    assert len(captured_envs) == 2
    assert captured_cwds == [project, project / "web"]
    for env in captured_envs:
        assert env["VIBELUTION_PORT"] == str(state["ports"]["backend"])
        assert env["VIBELUTION_FRONTEND_PORT"] == str(state["ports"]["frontend"])
        assert Path(env["VIBELUTION_DATA_HOME"]).is_relative_to(instance_root)
        assert Path(env["VIBELUTION_CONFIG_HOME"]).is_relative_to(instance_root)
        assert env["VIBELUTION_ACCEPTANCE_INSTANCE_ID"] == "task-a"
        assert env["VIBELUTION_ACCEPTANCE_MODE"] == "isolated-fixture"
    persisted = json.loads((instance_root / "state.json").read_text(encoding="utf-8"))
    assert persisted["processes"]["backend"]["pid"] == processes[0].pid
    assert "API_KEY" not in json.dumps(persisted)


def test_unsafe_instance_and_formal_runtime_roots_are_rejected(runtime, tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="instance-id"):
        runtime._instance_paths(instance_id="../escape", runtime_home=tmp_path)

    formal_root = tmp_path / "Documents" / "Vibelution"
    monkeypatch.setattr(runtime, "_formal_data_root", lambda: formal_root.resolve())
    with pytest.raises(ValueError, match="formal Vibelution data"):
        runtime._instance_paths(instance_id="task-a", runtime_home=formal_root)

    runtime_home = tmp_path / "safe"
    runtime_home.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    instance_link = runtime_home / "task-a"
    try:
        instance_link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks are not available in this environment")
    with pytest.raises(ValueError, match="escapes runtime home"):
        runtime._instance_paths(instance_id="task-a", runtime_home=runtime_home)


def test_startup_failure_rolls_back_processes_and_leases(runtime, tmp_path, monkeypatch):
    project = _project(tmp_path)
    runtime_home = tmp_path / "acceptance"

    class FakeProcess:
        next_pid = 5100

        def __init__(self):
            self.pid = FakeProcess.next_pid
            FakeProcess.next_pid += 1
            self.terminated = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return 0

        def kill(self):
            self.terminated = True

    processes = []

    def fake_spawn(*args, **kwargs):
        process = FakeProcess()
        processes.append(process)
        return process

    monkeypatch.setattr(runtime, "_spawn", fake_spawn)
    monkeypatch.setattr(runtime, "_wait_ready", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(runtime, "_process_create_time", lambda pid: float(pid))
    monkeypatch.setattr(runtime, "_process_matches", lambda pid, create_time: True)
    monkeypatch.setattr(runtime, "_port_available", lambda port, host="127.0.0.1": True)
    monkeypatch.setattr(runtime.shutil, "which", lambda name: "node.exe")

    with pytest.raises(RuntimeError, match="boom"):
        runtime.start_instance(
            instance_id="task-a",
            project_root=project,
            runtime_home=runtime_home,
        )

    assert processes and all(process.terminated for process in processes)
    assert list((runtime_home / ".leases").glob("*.json")) == []
    failed = json.loads((runtime_home / "task-a" / "state.json").read_text(encoding="utf-8"))
    assert failed["status"] == "failed"
    assert failed["ports"] == {}


def test_stale_lease_is_reclaimed(runtime, tmp_path, monkeypatch):
    lease_root = tmp_path / ".leases"
    lease_root.mkdir()
    stale_path = lease_root / "backend-8100.json"
    stale_path.write_text(
        json.dumps(
            {
                "kind": "backend",
                "port": 8100,
                "instanceId": "old-task",
                "ownerPid": 999,
                "ownerCreateTime": 1.0,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime, "_process_matches", lambda pid, create_time: False)
    monkeypatch.setattr(runtime, "_process_create_time", lambda pid: 2.0)
    monkeypatch.setattr(runtime, "_port_available", lambda port, host="127.0.0.1": True)

    port = runtime._allocate_port(
        lease_root=lease_root,
        kind="backend",
        instance_id="new-task",
        candidates=[8100],
    )

    assert port == 8100
    payload = json.loads(stale_path.read_text(encoding="utf-8"))
    assert payload["instanceId"] == "new-task"


def test_stop_is_identity_safe_and_idempotent(runtime, tmp_path, monkeypatch):
    runtime_home = tmp_path / "acceptance"
    paths = runtime._instance_paths(instance_id="task-a", runtime_home=runtime_home)
    for key in ("instanceRoot", "leaseRoot"):
        paths[key].mkdir(parents=True, exist_ok=True)
    state = {
        "instanceId": "task-a",
        "status": "running",
        "ports": {"backend": 8100, "frontend": 5200},
        "processes": {
            "backend": {"pid": 101, "createTime": 1.0},
            "frontend": {"pid": 102, "createTime": 2.0},
        },
    }
    runtime._write_json_atomic(paths["statePath"], state)
    for kind, port in state["ports"].items():
        runtime._write_json_atomic(
            runtime._lease_path(paths["leaseRoot"], kind, port),
            {"instanceId": "task-a", "kind": kind, "port": port},
        )
    attempts = []

    def fake_terminate(pid, create_time):
        attempts.append((pid, create_time))
        return False

    monkeypatch.setattr(runtime, "_terminate_recorded", fake_terminate)

    first = runtime.stop_instance(instance_id="task-a", runtime_home=runtime_home)
    second = runtime.stop_instance(instance_id="task-a", runtime_home=runtime_home)

    assert first["status"] == "stopped"
    assert first["terminated"] == {"frontend": False, "backend": False}
    assert second["status"] == "stopped"
    assert not list(paths["leaseRoot"].glob("*.json"))
    assert attempts[:2] == [(102, 2.0), (101, 1.0)]
