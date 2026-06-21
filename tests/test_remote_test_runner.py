from pathlib import Path

import pytest

from scripts import remote_test_runner


def make_config(**overrides):
    values = {
        "host": "bossai-server-b",
        "remote_root": "/home/enrigin/Vibelution-test",
        "workers": 8,
        "suite": "parallel",
        "remote_command": None,
        "no_install": False,
        "dry_run": True,
        "local_artifacts_dir": Path("artifacts"),
    }
    values.update(overrides)
    return remote_test_runner.RemoteTestConfig(**values)


def test_should_exclude_heavy_local_runtime_paths():
    excluded = [
        Path(".git/config"),
        Path(".env"),
        Path(".env.local"),
        Path(".venv/pyvenv.cfg"),
        Path("config/local-secret.key"),
        Path("data/runtime.sqlite"),
        Path("crates/helper/target/debug/helper.exe"),
        Path("web/node_modules/vite/index.js"),
        Path("web/dist/index.html"),
        Path("logs/runtime_scenes/example.jsonl"),
        Path(".runtime/runtime-manager/state.json"),
        Path("core/__pycache__/module.pyc"),
    ]

    assert all(not remote_test_runner.should_include(path) for path in excluded)
    assert remote_test_runner.should_include(Path("tests/test_runner.py"))
    assert remote_test_runner.should_include(Path("scripts/remote_test_runner.py"))


def test_builds_default_parallel_command_with_eight_workers():
    command = remote_test_runner.build_test_command(make_config())

    assert command == "python tests/test_runner.py --parallel --workers 8"


def test_custom_remote_command_overrides_suite():
    command = remote_test_runner.build_test_command(
        make_config(suite="hybrid", remote_command="python -m pytest tests/test_runner.py -q")
    )

    assert command == "python -m pytest tests/test_runner.py -q"


def test_remote_script_prepares_venv_and_captures_log():
    script = remote_test_runner.build_remote_script(make_config(), "20260621T000000Z")

    assert 'VENV="$CACHE_ROOT/venv-py${PY_VERSION}"' in script
    assert 'python3 -m venv "$VENV"' in script
    assert 'exec > >(tee "$REMOTE_ARTIFACTS/remote-test.log") 2>&1' in script
    assert 'REQ_MARKER="$VENV/.vibelution-requirements.sha256"' in script
    assert "python -m pip install -r requirements.txt" in script
    assert "python tests/test_runner.py --parallel --workers 8" in script


def test_no_install_skips_pip_steps():
    script = remote_test_runner.build_remote_script(make_config(no_install=True), "run-1")

    assert "pip install" not in script


def test_dry_run_prints_commands_without_executing(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / "tests").mkdir()
    (project / "tests" / "test_example.py").write_text("def test_ok(): pass\n", encoding="utf-8")

    monkeypatch.setattr(remote_test_runner, "utc_run_id", lambda: "run-1")
    calls = []
    runner = remote_test_runner.RemoteTestRunner(
        make_config(local_artifacts_dir=tmp_path / "artifacts"),
        project_root=project,
        run=lambda command: calls.append(list(command)) or 0,
    )

    assert runner.run() == 0
    assert calls == []
    assert (tmp_path / "artifacts" / "run-1").exists()


def test_runner_raises_on_failed_command(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / "file.txt").write_text("content", encoding="utf-8")

    monkeypatch.setattr(remote_test_runner, "utc_run_id", lambda: "run-1")
    runner = remote_test_runner.RemoteTestRunner(
        make_config(dry_run=False, local_artifacts_dir=tmp_path / "artifacts"),
        project_root=project,
        run=lambda command: 23,
    )

    with pytest.raises(remote_test_runner.CommandFailed) as exc_info:
        runner.run()

    assert exc_info.value.returncode == 23


def test_runner_copies_artifacts_after_remote_test_failure(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / "file.txt").write_text("content", encoding="utf-8")

    monkeypatch.setattr(remote_test_runner, "utc_run_id", lambda: "run-1")
    calls = []

    def fake_run(command):
        calls.append(list(command))
        if command[0] == "ssh" and "bash -lc" in command[2]:
            return 17
        return 0

    runner = remote_test_runner.RemoteTestRunner(
        make_config(dry_run=False, local_artifacts_dir=tmp_path / "artifacts"),
        project_root=project,
        run=fake_run,
    )

    with pytest.raises(remote_test_runner.CommandFailed) as exc_info:
        runner.run()

    assert exc_info.value.returncode == 17
    assert len(calls) == 4
    assert calls[-1][0] == "scp"
    assert calls[-1][1] == "-r"
