from pathlib import Path
import tarfile
import subprocess

import pytest

from scripts import remote_test_runner


def make_config(**overrides):
    values = {
        "host": "bossai-server-b",
        "remote_root": "/home/enrigin/Vibelution-test",
        "workers": 8,
        "local_workers": 8,
        "suite": "parallel",
        "backend": "venv",
        "docker_image": "vibelution-test",
        "rebuild_image": False,
        "remote_command": None,
        "no_install": False,
        "distributed": False,
        "apt_mirror": remote_test_runner.DEFAULT_APT_MIRROR,
        "pip_index_url": remote_test_runner.DEFAULT_PIP_INDEX_URL,
        "pip_trusted_host": remote_test_runner.DEFAULT_PIP_TRUSTED_HOST,
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


def test_split_targets_by_capacity_prefers_more_weight_on_remote(tmp_path):
    project = tmp_path / "project"
    tests_dir = project / "tests"
    tests_dir.mkdir(parents=True)
    sizes = {
        "test_large.py": 800,
        "test_medium.py": 400,
        "test_small.py": 120,
        "test_tiny.py": 80,
    }
    for name, size in sizes.items():
        (tests_dir / name).write_text("x" * size, encoding="utf-8")

    targets = remote_test_runner.discover_test_targets(project)
    local_targets, remote_targets = remote_test_runner.split_targets_by_capacity(
        targets,
        project_root=project,
        local_workers=8,
        remote_workers=16,
    )

    assert local_targets
    assert remote_targets
    assert set(local_targets).isdisjoint(remote_targets)
    assert set(local_targets + remote_targets) == set(targets)
    remote_weight = sum((project / target).stat().st_size for target in remote_targets)
    local_weight = sum((project / target).stat().st_size for target in local_targets)
    assert remote_weight > local_weight


def test_build_parallel_pytest_command_uses_xdist_marker_and_workers():
    command = remote_test_runner.build_parallel_pytest_command(
        [Path("tests/test_a.py"), "tests/test_b.py"],
        workers=16,
        python_executable="python",
    )

    assert command[:3] == ["python", "-m", "pytest"]
    assert "tests/test_a.py" in command
    assert "tests/test_b.py" in command
    assert command[command.index("-n") + 1] == "16"
    assert command[command.index("--dist") + 1] == "loadfile"
    assert command[command.index("-m", 3) + 1] == "not serial"


def test_build_parallel_pytest_shell_command_reads_targets_from_manifest():
    command = remote_test_runner.build_parallel_pytest_shell_command_from_manifest(
        ".remote-test/remote-targets.txt",
        workers=16,
    )

    assert "python -m pytest $(cat .remote-test/remote-targets.txt)" in command
    assert "-n 16" in command
    assert "-m 'not serial'" in command


def test_distributed_correctness_summary_names_excluded_gates():
    summary = remote_test_runner.build_distributed_correctness_summary(
        local_targets=[Path("tests/test_a.py")],
        remote_targets=[Path("tests/test_b.py"), Path("tests/test_c.py")],
        local_workers=8,
        remote_workers=16,
    )

    assert summary.startswith("correctness_scope=python_pytest:not_serial")
    assert "targets:3" in summary
    assert "local_targets:1" in summary
    assert "remote_targets:2" in summary
    assert "workers:8+16" in summary
    assert "excluded:serial_pytest,frontend_vitest,frontend_build" in summary
    assert "gate_hint:run_serial_and_frontend_for_release_or_matching_changes" in summary


def test_create_source_archive_can_embed_extra_files(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "file.txt").write_text("content", encoding="utf-8")
    archive_path = tmp_path / "source.tar.gz"

    file_count = remote_test_runner.create_source_archive(
        project,
        archive_path,
        extra_files={".remote-test/remote-targets.txt": "tests/test_a.py\n"},
    )

    assert file_count == 2
    with tarfile.open(archive_path, "r:gz") as archive:
        assert archive.extractfile(".remote-test/remote-targets.txt").read().decode("utf-8") == "tests/test_a.py\n"


def test_remote_script_prepares_venv_and_captures_log():
    script = remote_test_runner.build_remote_script(make_config(), "20260621T000000Z")

    assert "backend=venv" in script
    assert 'cat > "$REMOTE_SOURCE/.remote-test/config.toml"' in script
    assert 'profile = "safe_remote"' in script
    assert "[llm.model_library.relay_openai_gpt_5_5]" in script
    assert 'model = "gpt-5.5"' in script
    assert "[llm.model_library.relay_openai_gpt_5_5.prompt_cache]" in script
    assert 'mode = "automatic"' in script
    assert 'name = "SOUL"' in script
    assert 'path = "core/core_prompt/SOUL.md"' in script
    assert 'name = "SPEC"' in script
    assert 'path = "core/core_prompt/SPEC.md"' in script
    assert 'export VIBELUTION_CONFIG_PATH="$REMOTE_SOURCE/.remote-test/config.toml"' in script
    assert f"PIP_INDEX_URL={remote_test_runner.DEFAULT_PIP_INDEX_URL}" in script
    assert 'echo pip_index_url="${PIP_INDEX_URL:-default}"' in script
    assert 'VENV="$CACHE_ROOT/venv-py${PY_VERSION}"' in script
    assert 'python3 -m venv "$VENV"' in script
    assert 'exec > >(tee "$REMOTE_ARTIFACTS/remote-test.log") 2>&1' in script
    assert 'REQ_MARKER="$VENV/.vibelution-requirements.sha256"' in script
    assert "python -m pip install $PIP_ARGS -r requirements.txt" in script
    assert "python tests/test_runner.py --parallel --workers 8" in script


def test_no_install_skips_pip_steps():
    script = remote_test_runner.build_remote_script(make_config(no_install=True), "run-1")

    assert "pip install" not in script


def test_remote_script_can_run_inside_docker_backend():
    script = remote_test_runner.build_remote_script(make_config(backend="docker"), "20260621T000000Z")

    assert "backend=docker" in script
    assert "command -v docker" in script
    assert "DOCKER_SPEC_VERSION=git2" in script
    assert f"APT_MIRROR={remote_test_runner.DEFAULT_APT_MIRROR}" in script
    assert f"PIP_INDEX_URL={remote_test_runner.DEFAULT_PIP_INDEX_URL}" in script
    assert 'DOCKER_IMAGE="${DOCKER_IMAGE_BASE}:py${PY_VERSION}-${REQ_HASH}-${DOCKER_SPEC_VERSION}"' in script
    assert 'DOCKER_BUILD_CONTEXT="$CACHE_ROOT/docker-build/py${PY_VERSION}-${REQ_HASH}-${DOCKER_SPEC_VERSION}"' in script
    assert 'cp requirements.txt "$DOCKER_BUILD_CONTEXT/requirements.txt"' in script
    assert "ARG APT_MIRROR" in script
    assert "ARG PIP_INDEX_URL" in script
    assert "pip config set global.index-url" in script
    assert "apt-get install -y --no-install-recommends git" in script
    assert 'docker build --build-arg APT_MIRROR="$APT_MIRROR"' in script
    assert 'docker build -t "$DOCKER_IMAGE" -f "$DOCKERFILE" "$REMOTE_SOURCE"' not in script
    assert "docker run --rm" in script
    assert "-e NO_PROXY=localhost,127.0.0.1" in script
    assert "-e COLUMNS=120" in script
    assert "-e VIBELUTION_CONFIG_PATH=/workspace/.remote-test/config.toml" in script
    assert "-v \"$REMOTE_SOURCE:/workspace\"" in script
    assert "python tests/test_runner.py --parallel --workers 8" in script


def test_remote_script_can_force_docker_image_rebuild():
    script = remote_test_runner.build_remote_script(make_config(backend="docker", rebuild_image=True), "run-1")

    assert "REBUILD_IMAGE=1" in script


def test_parse_args_allows_remote_install_mirror_overrides(monkeypatch):
    monkeypatch.setattr(remote_test_runner.shutil, "which", lambda name: f"/usr/bin/{name}")

    config = remote_test_runner.parse_args(
        [
            "--apt-mirror",
            "http://mirror.example/debian",
            "--pip-index-url",
            "https://mirror.example/pypi/simple",
            "--pip-trusted-host",
            "mirror.example",
        ]
    )

    assert config.apt_mirror == "http://mirror.example/debian"
    assert config.pip_index_url == "https://mirror.example/pypi/simple"
    assert config.pip_trusted_host == "mirror.example"


def test_parse_args_distributed_defaults_to_twenty_four_total_workers(monkeypatch):
    monkeypatch.setattr(remote_test_runner.shutil, "which", lambda name: f"/usr/bin/{name}")

    config = remote_test_runner.parse_args(["--distributed"])

    assert config.distributed is True
    assert config.local_workers == 8
    assert config.workers == 16


def test_parse_args_rejects_distributed_custom_remote_command(monkeypatch):
    monkeypatch.setattr(remote_test_runner.shutil, "which", lambda name: f"/usr/bin/{name}")

    with pytest.raises(SystemExit):
        remote_test_runner.parse_args(["--distributed", "--remote-command", "python -m pytest"])


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


def test_distributed_dry_run_splits_local_and_remote_commands(tmp_path, monkeypatch, capsys):
    project = tmp_path / "project"
    tests_dir = project / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_large.py").write_text("x" * 800, encoding="utf-8")
    (tests_dir / "test_small.py").write_text("x" * 100, encoding="utf-8")

    monkeypatch.setattr(remote_test_runner, "utc_run_id", lambda: "run-1")
    calls = []
    runner = remote_test_runner.RemoteTestRunner(
        make_config(
            distributed=True,
            workers=16,
            local_workers=8,
            backend="docker",
            local_artifacts_dir=tmp_path / "artifacts",
        ),
        project_root=project,
        run=lambda command: calls.append(list(command)) or 0,
    )

    assert runner.run() == 0

    output = capsys.readouterr().out
    assert calls == []
    assert "distributed_split=local:" in output
    assert "correctness_scope=python_pytest:not_serial" in output
    assert "excluded:serial_pytest,frontend_vitest,frontend_build" in output
    assert "remote:" in output
    assert "local " in output
    assert "-n 8" in output
    assert "-n 16" in output
    assert "not serial" in output
    assert (tmp_path / "artifacts" / "run-1").exists()


def test_distributed_wait_terminates_peer_when_one_side_fails():
    runner = remote_test_runner.RemoteTestRunner(make_config())

    class FakeProcess:
        def __init__(self, returncode=None):
            self.returncode = returncode
            self.terminated = False
            self.wait_calls = 0

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            self.wait_calls += 1
            if self.returncode is None:
                if self.terminated:
                    self.returncode = -15
                else:
                    raise subprocess.TimeoutExpired(cmd="fake", timeout=timeout)
            return self.returncode

        def terminate(self):
            self.terminated = True

    remote_process = FakeProcess(returncode=None)
    local_process = FakeProcess(returncode=3)

    remote_returncode, local_returncode = runner._wait_distributed_processes(remote_process, local_process)

    assert local_returncode == 3
    assert remote_returncode == -15
    assert remote_process.terminated is True


def test_terminate_processes_stops_running_children():
    runner = remote_test_runner.RemoteTestRunner(make_config())

    class FakeProcess:
        def __init__(self):
            self.terminated = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

    local_process = FakeProcess()
    remote_process = FakeProcess()

    runner._terminate_processes(local_process, remote_process)

    assert local_process.terminated is True
    assert remote_process.terminated is True


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
