from __future__ import annotations

from core.runtime_manager import process_inventory, workbench_controller


def test_repo_runtime_process_for_pid_classifies_only_the_requested_process(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    requested_attrs: list[list[str]] = []

    class FakeProcess:
        def as_dict(self, attrs):
            requested_attrs.append(list(attrs))
            return {
                "pid": 4312,
                "ppid": 1,
                "name": "pythonw.exe",
                "cmdline": [
                    str(repo / ".venv" / "Scripts" / "pythonw.exe"),
                    "scripts/web_workbench.py",
                    "--port",
                    "8002",
                    "--managed-by-launcher",
                ],
                "cwd": str(repo),
            }

    class FakePsutil:
        NoSuchProcess = ProcessLookupError
        AccessDenied = PermissionError

        @staticmethod
        def Process(pid):
            assert pid == 4312
            return FakeProcess()

        @staticmethod
        def process_iter(_attrs):
            raise AssertionError("single-PID lookup must not enumerate every system process")

    monkeypatch.setattr(process_inventory, "psutil", FakePsutil)

    process = process_inventory.repo_runtime_process_for_pid(4312, project_root=repo)

    assert process is not None
    assert process.pid == 4312
    assert process.kind == "managed_workbench_backend"
    assert process.port == 8002
    assert requested_attrs == [["pid", "ppid", "name", "cmdline", "cwd"]]


def test_repo_runtime_process_for_pid_rejects_external_process(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    other = tmp_path / "other"
    repo.mkdir()
    other.mkdir()

    class FakeProcess:
        @staticmethod
        def as_dict(_attrs):
            return {
                "pid": 4312,
                "ppid": 1,
                "name": "pythonw.exe",
                "cmdline": ["pythonw.exe", "scripts/web_workbench.py", "--managed-by-launcher"],
                "cwd": str(other),
            }

    class FakePsutil:
        NoSuchProcess = ProcessLookupError
        AccessDenied = PermissionError

        @staticmethod
        def Process(pid):
            assert pid == 4312
            return FakeProcess()

    monkeypatch.setattr(process_inventory, "psutil", FakePsutil)

    assert process_inventory.repo_runtime_process_for_pid(4312, project_root=repo) is None


def test_repo_workbench_backend_kind_uses_targeted_process_lookup(monkeypatch):
    expected = process_inventory.RuntimeProcess(
        pid=4312,
        parent_pid=1,
        kind="managed_workbench_backend",
        name="pythonw.exe",
        command_line="pythonw scripts/web_workbench.py --managed-by-launcher",
        cwd="C:/workspace",
        port=8002,
    )
    requested: list[tuple[int, object]] = []

    def lookup(pid, *, project_root):
        requested.append((pid, project_root))
        return expected

    monkeypatch.setattr(workbench_controller, "repo_runtime_process_for_pid", lookup)

    assert workbench_controller._repo_workbench_backend_kind(4312) == "managed_workbench_backend"
    assert requested and requested[0][0] == 4312
