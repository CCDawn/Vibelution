import contextlib
import importlib.util
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import types
import uuid
from argparse import Namespace
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).parent.parent
LAUNCHER_SCRIPT = PROJECT_ROOT / "scripts" / "vibelution_launcher.ps1"
DESKTOP_ENTRY_SCRIPT = PROJECT_ROOT / "scripts" / "vibelution_desktop_entry.ps1"
DESKTOP_ENTRY_VBS = PROJECT_ROOT / "scripts" / "vibelution_desktop_entry.vbs"
DESKTOP_ENTRY_PY = PROJECT_ROOT / "scripts" / "vibelution_desktop_entry.py"
NATIVE_ENTRY_SOURCE = PROJECT_ROOT / "scripts" / "windows_launcher_entry" / "VibelutionLauncher.cs"
NATIVE_ENTRY_BUILD_SCRIPT = PROJECT_ROOT / "scripts" / "windows_launcher_entry" / "build_vibelution_launcher_entry.ps1"
PYTHON_LAUNCHER_SCRIPT = PROJECT_ROOT / "scripts" / "vibelution_launcher.py"
WORKBENCH_CLOSE_CANARY_SCRIPT = PROJECT_ROOT / "scripts" / "verify_desktop_workbench_close.ps1"

pytestmark = pytest.mark.slow


@pytest.mark.serial
def test_launcher_precommit_hook_supports_posix_venv_and_verifies_web_lock():
    source = (PROJECT_ROOT / ".githooks" / "pre-commit").read_text(encoding="utf-8")
    attributes = (PROJECT_ROOT / ".gitattributes").read_text(encoding="utf-8")
    mode = subprocess.run(
        ["git", "ls-files", "--stage", "--", ".githooks/pre-commit"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split(maxsplit=1)[0]

    assert '"$repo_root/.venv/Scripts/python.exe"' in source
    assert '"$repo_root/.venv/bin/python"' in source
    assert 'npm --silent --prefix "$repo_root/web" ci --ignore-scripts --dry-run --no-audit --no-fund' in source
    assert ".githooks/* text eol=lf" in attributes
    assert mode == "100755"


@pytest.mark.serial
def test_launcher_posix_git_hooks_are_executable() -> None:
    for hook_name in ("pre-commit", "post-merge", "reference-transaction"):
        mode = subprocess.run(
            ["git", "ls-files", "--stage", "--", f".githooks/{hook_name}"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split(maxsplit=1)[0]

        assert mode == "100755"


def test_python_launcher_visible_start_refuses_edge_fallback(monkeypatch, tmp_path):
    launcher = _load_python_launcher()

    monkeypatch.setattr(
        launcher.subprocess,
        "Popen",
        lambda *_args, **_kwargs: pytest.fail("visible start must not spawn Edge or a backend first"),
    )

    with pytest.raises(RuntimeError, match="Refusing Edge fallback"):
        launcher._start_managed_browser("http://127.0.0.1:8002")
    with pytest.raises(RuntimeError, match="Refusing Edge fallback"):
        launcher._start_backend(8000, "127.0.0.1", no_browser=False)


def test_python_launcher_pid_probe_without_psutil_uses_shared_liveness(monkeypatch):
    launcher = _load_python_launcher()

    # The shared stdlib-only probe must load from core/infrastructure without
    # importing the heavy core.infrastructure package.
    assert launcher._PROCESS_LIVENESS is not None

    monkeypatch.setitem(sys.modules, "psutil", None)  # import psutil -> ImportError
    assert launcher._pid_probe(0) == "dead"
    assert launcher._pid_probe(os.getpid()) == "alive"

    # The kernel32-backed shared probe decides; a stale os.kill heuristic must
    # never map a live pid to "dead" (WinError 87 is not a liveness answer).
    fake_probe = types.SimpleNamespace(is_pid_alive=lambda pid: pid == os.getpid())
    monkeypatch.setattr(launcher, "_PROCESS_LIVENESS", fake_probe)
    assert launcher._pid_probe(os.getpid()) == "alive"
    assert launcher._pid_probe(os.getpid() + 424242) == "dead"
    assert launcher._pid_alive(os.getpid()) is True


def test_python_launcher_workbench_identity_finds_the_profile_owned_window(monkeypatch, tmp_path):
    launcher = _load_python_launcher()

    monkeypatch.setattr(launcher, "os", type("FakeOs", (), {"name": "nt"})())
    monkeypatch.setattr(launcher, "WORKBENCH_BROWSER_PROFILE_DIR", tmp_path / "workbench-profile")
    monkeypatch.setattr(launcher, "_visible_windows_for_process", lambda pid: [90210] if pid == 4736 else [])
    monkeypatch.setattr(launcher, "_managed_browser_pids_for_profile", lambda profile_dir: [4736])
    monkeypatch.setattr(launcher, "_window_process_id", lambda hwnd: 4736)

    assert launcher._MANAGED_BROWSER_IDENTITY_TIMEOUT_SECONDS <= 1.0
    assert launcher._managed_browser_window_candidates(47264, "workbench") == [
        {"hwnd": 90210, "processId": 4736, "resolvedBy": "workbench_profile"},
    ]


def test_python_launcher_workbench_identity_skips_profile_scan_after_exact_pid_match(monkeypatch):
    launcher = _load_python_launcher()

    monkeypatch.setattr(launcher, "_visible_windows_for_process", lambda pid: [90210] if pid == 47264 else [])
    monkeypatch.setattr(launcher, "_window_process_id", lambda hwnd: 47264)
    monkeypatch.setattr(
        launcher,
        "_managed_browser_pids_for_profile",
        lambda profile_dir: pytest.fail("exact launch-PID match must not scan all Edge processes"),
    )

    assert launcher._managed_browser_window_candidates(47264, "workbench") == [
        {"hwnd": 90210, "processId": 47264, "resolvedBy": "launch_pid"},
    ]


def test_python_launcher_imports_safely_on_non_windows(monkeypatch):
    fake_os = types.ModuleType("os")
    fake_os.name = "posix"
    fake_os.environ = os.environ
    monkeypatch.setitem(sys.modules, "os", fake_os)
    launcher = _load_python_launcher()

    # Windows-only shell identity structures must not be constructed off-Windows;
    # importing on POSIX previously raised ValueError from _GUID.from_buffer_copy.
    assert launcher.PKEY_APPUSERMODEL_ID is None
    assert launcher.PKEY_APPUSERMODEL_RELAUNCH_DISPLAY_NAME is None
    assert launcher.PKEY_APPUSERMODEL_RELAUNCH_ICON_RESOURCE is None
    assert launcher.IID_IPROPERTY_STORE is None
    result = launcher._apply_managed_browser_app_identity(0, "workbench")
    assert result["applied"] is False
    assert result["reason"] == "non_windows"
    assert result["appUserModelId"] == "Vibelution.Workbench"


@pytest.mark.skipif(os.name != "nt", reason="Windows shell identity contract is Windows-only")
def test_python_launcher_windows_identity_runtime_contract():
    launcher = _load_python_launcher()

    assert isinstance(launcher.PKEY_APPUSERMODEL_ID, launcher._PROPERTYKEY)
    assert isinstance(launcher.PKEY_APPUSERMODEL_RELAUNCH_DISPLAY_NAME, launcher._PROPERTYKEY)
    assert isinstance(launcher.PKEY_APPUSERMODEL_RELAUNCH_ICON_RESOURCE, launcher._PROPERTYKEY)
    assert launcher.PKEY_APPUSERMODEL_ID.fmtid.Data1 == 0x9F4C2855
    assert launcher.PKEY_APPUSERMODEL_ID.pid == 5
    assert launcher.PKEY_APPUSERMODEL_RELAUNCH_DISPLAY_NAME.pid == 4
    assert launcher.PKEY_APPUSERMODEL_RELAUNCH_ICON_RESOURCE.pid == 3
    assert isinstance(launcher.IID_IPROPERTY_STORE, launcher._GUID)
    assert bytes(launcher.IID_IPROPERTY_STORE) == uuid.UUID("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99").bytes_le


def test_desktop_entry_launcher_identity_falls_back_to_profile_window(monkeypatch, tmp_path):
    bridge = _load_desktop_entry_py()
    events: list[tuple[str, dict[str, object]]] = []
    identities: list[tuple[int, str, str, str]] = []
    icon_handles: list[int] = []

    monkeypatch.setattr(bridge, "os", type("FakeOs", (), {"name": "nt"})())
    monkeypatch.setattr(bridge, "LAUNCHER_ICON_PATH", tmp_path / "vibelution.ico")
    bridge.LAUNCHER_ICON_PATH.write_text("icon", encoding="utf-8")
    monkeypatch.setattr(bridge, "_visible_windows_for_process", lambda pid: [])
    monkeypatch.setattr(
        bridge,
        "_managed_browser_window_candidates",
        lambda browser_pid, role: [{"hwnd": 90210, "resolvedBy": "launcher_control_profile", "processId": 4736}],
    )
    monkeypatch.setattr(
        bridge,
        "_set_window_app_identity",
        lambda hwnd, app_id, display_name, icon_resource: identities.append((hwnd, app_id, display_name, icon_resource)),
    )
    monkeypatch.setattr(bridge, "_apply_window_icon", lambda hwnd, icon_path: icon_handles.append(hwnd) or True)
    monkeypatch.setattr(bridge, "_window_process_id", lambda hwnd: 4736)
    monkeypatch.setattr(bridge, "_append_log", lambda event, **fields: events.append((event, fields)))

    result = bridge._apply_managed_browser_app_identity(47264, "launcher")

    assert result["applied"] is True
    assert result["windowIconApplied"] is True
    assert result["windowPid"] == 4736
    assert result["appUserModelId"] == "Vibelution.Launcher"
    assert result["resolvedBy"] == "launcher_control_profile"
    assert identities == [(90210, "Vibelution.Launcher", "Vibelution Launcher", f"{bridge.LAUNCHER_ICON_PATH},0")]
    assert icon_handles == [90210]
    assert events[-1][0] == "launcher.browser.window_app_identity.succeeded"
    assert events[-1][1]["resolvedBy"] == "launcher_control_profile"


def _load_desktop_entry_py():
    module_name = f"vibelution_desktop_entry_under_test_{time.time_ns()}"
    spec = importlib.util.spec_from_file_location(module_name, DESKTOP_ENTRY_PY)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_python_launcher():
    module_name = f"vibelution_launcher_under_test_{time.time_ns()}"
    spec = importlib.util.spec_from_file_location(module_name, PYTHON_LAUNCHER_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_python_launcher_frontend_command_is_bounded_and_reports_timeout(monkeypatch, tmp_path):
    launcher = _load_python_launcher()
    calls: list[dict[str, object]] = []
    events: list[dict[str, object]] = []

    def timed_out_run(args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    monkeypatch.setattr(launcher.subprocess, "run", timed_out_run)
    monkeypatch.setattr(launcher, "_append_frontend_build_log", lambda payload: events.append(payload))

    with pytest.raises(RuntimeError, match=r"node tsc -b timed out after 120 seconds"):
        launcher._run_checked(
            ["node", "node_modules/typescript/bin/tsc", "-b"],
            cwd=tmp_path,
            label="node tsc -b",
        )

    assert calls[0]["kwargs"]["timeout"] == launcher.FRONTEND_BUILD_TIMEOUT_SECONDS
    assert events == [
        {
            "event": "frontend_build.command_timeout",
            "command": "node tsc -b",
            "errorType": "TimeoutExpired",
            "timeoutSeconds": 120.0,
        }
    ]


def test_npm_cli_follows_unix_symlink_and_lib_prefix_layout(tmp_path, monkeypatch):
    launcher = _load_python_launcher()
    prefix = tmp_path / "node-prefix"
    cli = prefix / "lib" / "node_modules" / "npm" / "bin" / "npm-cli.js"
    cli.parent.mkdir(parents=True)
    cli.write_text("#!/usr/bin/env node\n", encoding="utf-8")
    bin_dir = prefix / "bin"
    bin_dir.mkdir()
    npm_link = bin_dir / "npm"
    npm_link.symlink_to(cli)

    def fake_which(name: str):
        if name == "npm":
            return str(npm_link)
        return None

    monkeypatch.setattr(launcher.shutil, "which", fake_which)
    resolved = Path(launcher._npm_cli_script_for_node(str(bin_dir / "node")))
    assert resolved == cli.resolve()


def test_npm_cli_finds_lib_node_modules_next_to_node(tmp_path, monkeypatch):
    launcher = _load_python_launcher()
    prefix = tmp_path / "exec-daemon"
    cli = prefix / "lib" / "node_modules" / "npm" / "bin" / "npm-cli.js"
    cli.parent.mkdir(parents=True)
    cli.write_text("#!/usr/bin/env node\n", encoding="utf-8")
    node_bin = prefix / "node"
    node_bin.write_text("", encoding="utf-8")
    monkeypatch.setattr(launcher.shutil, "which", lambda name: None)
    resolved = Path(launcher._npm_cli_script_for_node(str(node_bin)))
    assert resolved == cli


def test_python_launcher_bootstraps_project_venv_with_current_interpreter(monkeypatch, tmp_path):
    launcher = _load_python_launcher()
    monkeypatch.setattr(launcher.os, "name", "posix")
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    venv_python = project_dir / ".venv" / "bin" / "python"
    requirements = project_dir / "requirements.txt"
    requirements.write_text("fastapi>=0.111.0\nlangchain-core>=0.1.0\n", encoding="utf-8")
    monkeypatch.setattr(launcher, "PROJECT_ROOT", project_dir)
    monkeypatch.setattr(launcher, "VENV_DIR", project_dir / ".venv")
    monkeypatch.setattr(launcher, "REQUIREMENTS_PATH", requirements)
    monkeypatch.setattr(launcher, "RUNTIME_DIR", tmp_path / ".runtime" / "launcher")
    venv_creation: list[list[str]] = []
    installed: list[str] = []

    def fake_run(args, **kwargs):
        if args[:3] == [launcher._bootstrap_python_executable(), "-m", "venv"]:
            venv_creation.append(list(args))
            venv_python.parent.mkdir(parents=True)
            venv_python.write_text("#!/usr/bin/env python3", encoding="utf-8")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(launcher.subprocess, "run", fake_run)
    monkeypatch.setattr(launcher, "_runtime_imports_available", lambda exe: False)
    monkeypatch.setattr(launcher, "_install_project_dependencies", lambda exe: installed.append(exe))
    monkeypatch.setattr(launcher, "_missing_runtime_modules", lambda exe, modules: [])

    resolved = launcher._ensure_project_python_runtime()

    assert resolved == str(venv_python)
    assert venv_creation == [[launcher._bootstrap_python_executable(), "-m", "venv", str(project_dir / ".venv")]]
    assert installed == [str(venv_python)]
    assert (tmp_path / ".runtime" / "launcher" / "python-deps.stamp").exists()


def test_python_launcher_skips_reinstall_when_venv_ready_and_requirements_unchanged(monkeypatch, tmp_path):
    launcher = _load_python_launcher()
    monkeypatch.setattr(launcher.os, "name", "posix")
    project_dir = tmp_path / "project"
    venv_python = project_dir / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("#!/usr/bin/env python3", encoding="utf-8")
    requirements = project_dir / "requirements.txt"
    requirements.write_text("fastapi>=0.111.0\n", encoding="utf-8")
    monkeypatch.setattr(launcher, "PROJECT_ROOT", project_dir)
    monkeypatch.setattr(launcher, "VENV_DIR", project_dir / ".venv")
    monkeypatch.setattr(launcher, "REQUIREMENTS_PATH", requirements)
    monkeypatch.setattr(launcher, "RUNTIME_DIR", tmp_path / ".runtime" / "launcher")
    full_probes: list[str] = []
    monkeypatch.setattr(launcher, "_runtime_core_imports_available", lambda exe: True)
    monkeypatch.setattr(
        launcher,
        "_runtime_imports_available",
        lambda exe: full_probes.append(exe) or True,
    )
    installed: list[str] = []
    monkeypatch.setattr(launcher, "_install_project_dependencies", lambda exe: installed.append(exe))
    monkeypatch.setattr(launcher, "_missing_runtime_modules", lambda exe, modules: [])
    stamp_path = launcher._dependency_stamp_path()
    stamp_path.parent.mkdir(parents=True)
    stamp_path.write_text(launcher._requirements_fingerprint(), encoding="utf-8")

    resolved = launcher._ensure_project_python_runtime()

    assert resolved == str(venv_python)
    assert installed == []
    assert full_probes == []  # stamp match uses cheap core probe only
    assert stamp_path.read_text(encoding="utf-8") == launcher._requirements_fingerprint()


def test_python_launcher_stamp_match_uses_core_probe_not_full_import(monkeypatch, tmp_path):
    launcher = _load_python_launcher()
    monkeypatch.setattr(launcher.os, "name", "posix")
    project_dir = tmp_path / "project"
    venv_python = project_dir / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("#!/usr/bin/env python3", encoding="utf-8")
    requirements = project_dir / "requirements.txt"
    requirements.write_text("fastapi>=0.111.0\nlangchain>=0.1.0\n", encoding="utf-8")
    monkeypatch.setattr(launcher, "PROJECT_ROOT", project_dir)
    monkeypatch.setattr(launcher, "VENV_DIR", project_dir / ".venv")
    monkeypatch.setattr(launcher, "REQUIREMENTS_PATH", requirements)
    monkeypatch.setattr(launcher, "RUNTIME_DIR", tmp_path / ".runtime" / "launcher")
    core_probes: list[str] = []
    full_probes: list[str] = []
    monkeypatch.setattr(
        launcher,
        "_runtime_core_imports_available",
        lambda exe: core_probes.append(exe) or True,
    )
    monkeypatch.setattr(
        launcher,
        "_runtime_imports_available",
        lambda exe: full_probes.append(exe) or True,
    )
    monkeypatch.setattr(launcher, "_install_project_dependencies", lambda exe: (_ for _ in ()).throw(AssertionError("should not install")))
    stamp_path = launcher._dependency_stamp_path()
    stamp_path.parent.mkdir(parents=True)
    stamp_path.write_text(launcher._requirements_fingerprint(), encoding="utf-8")

    assert launcher._ensure_project_python_runtime() == str(venv_python)
    assert core_probes == [str(venv_python)]
    assert full_probes == []


def test_python_launcher_reinstalls_when_requirements_changed(monkeypatch, tmp_path):
    launcher = _load_python_launcher()
    monkeypatch.setattr(launcher.os, "name", "posix")
    project_dir = tmp_path / "project"
    venv_python = project_dir / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("#!/usr/bin/env python3", encoding="utf-8")
    requirements = project_dir / "requirements.txt"
    requirements.write_text("fastapi>=0.111.0\n", encoding="utf-8")
    monkeypatch.setattr(launcher, "PROJECT_ROOT", project_dir)
    monkeypatch.setattr(launcher, "VENV_DIR", project_dir / ".venv")
    monkeypatch.setattr(launcher, "REQUIREMENTS_PATH", requirements)
    monkeypatch.setattr(launcher, "RUNTIME_DIR", tmp_path / ".runtime" / "launcher")
    monkeypatch.setattr(launcher, "_runtime_imports_available", lambda exe: True)
    installed: list[str] = []
    monkeypatch.setattr(launcher, "_install_project_dependencies", lambda exe: installed.append(exe))
    monkeypatch.setattr(launcher, "_missing_runtime_modules", lambda exe, modules: [])
    stamp_path = launcher._dependency_stamp_path()
    stamp_path.parent.mkdir(parents=True)
    stamp_path.write_text("stale-fingerprint", encoding="utf-8")

    resolved = launcher._ensure_project_python_runtime()

    assert resolved == str(venv_python)
    assert installed == [str(venv_python)]
    assert stamp_path.read_text(encoding="utf-8") == launcher._requirements_fingerprint()


def test_python_launcher_reports_missing_runtime_dependencies_after_install(monkeypatch, tmp_path):
    launcher = _load_python_launcher()
    monkeypatch.setattr(launcher.os, "name", "posix")
    project_dir = tmp_path / "project"
    venv_python = project_dir / ".venv" / "bin" / "python"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("#!/usr/bin/env python3", encoding="utf-8")
    requirements = project_dir / "requirements.txt"
    requirements.write_text("langchain-core>=0.1.0\n", encoding="utf-8")
    monkeypatch.setattr(launcher, "PROJECT_ROOT", project_dir)
    monkeypatch.setattr(launcher, "VENV_DIR", project_dir / ".venv")
    monkeypatch.setattr(launcher, "REQUIREMENTS_PATH", requirements)
    monkeypatch.setattr(launcher, "RUNTIME_DIR", tmp_path / ".runtime" / "launcher")
    monkeypatch.setattr(launcher, "_runtime_imports_available", lambda exe: False)
    installed: list[str] = []
    monkeypatch.setattr(launcher, "_install_project_dependencies", lambda exe: installed.append(exe))
    monkeypatch.setattr(launcher, "_missing_runtime_modules", lambda exe, modules: ["langchain_core"])

    with pytest.raises(RuntimeError, match="langchain_core"):
        launcher._ensure_project_python_runtime()

    assert installed == [str(venv_python)]


def _write_posix_venv_python(root: Path) -> Path:
    python = root / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_text("#!/usr/bin/env python3", encoding="utf-8")
    return python


def test_isolated_start_reuses_supervisor_venv_when_requirements_match(monkeypatch, tmp_path):
    launcher = _load_python_launcher()
    monkeypatch.setattr(launcher.os, "name", "posix")
    supervisor = tmp_path / "supervisor"
    worktree = tmp_path / "worktree"
    supervisor.mkdir()
    worktree.mkdir()
    requirements = "fastapi>=0.111.0\nuvicorn>=0.30.0\n"
    (supervisor / "requirements.txt").write_text(requirements, encoding="utf-8")
    (worktree / "requirements.txt").write_text(requirements, encoding="utf-8")
    supervisor_python = _write_posix_venv_python(supervisor)
    monkeypatch.setattr(launcher, "SUPERVISOR_ROOT", supervisor)
    monkeypatch.setattr(launcher, "PROJECT_ROOT", worktree)
    monkeypatch.setattr(launcher, "VENV_DIR", worktree / ".venv")
    monkeypatch.setattr(launcher, "REQUIREMENTS_PATH", worktree / "requirements.txt")
    monkeypatch.setattr(launcher, "RUNTIME_DIR", tmp_path / "slot-runtime" / "launcher")
    events: list[dict] = []
    created: list[str] = []
    installed: list[str] = []
    monkeypatch.setattr(launcher, "_append_frontend_build_log", lambda payload: events.append(dict(payload)))
    monkeypatch.setattr(launcher, "_create_project_virtualenv", lambda: created.append("created"))
    monkeypatch.setattr(launcher, "_install_project_dependencies", lambda exe: installed.append(exe))
    monkeypatch.setattr(
        launcher,
        "_runtime_core_imports_available",
        lambda exe: exe == str(supervisor_python),
    )
    monkeypatch.setattr(launcher, "_runtime_imports_available", lambda exe: False)

    resolved = launcher._ensure_project_python_runtime()

    assert resolved == str(supervisor_python)
    assert created == []
    assert installed == []
    assert not (worktree / ".venv").exists()
    assert events == [
        {
            "event": "python_runtime.reused_supervisor",
            "pythonExecutable": str(supervisor_python),
            "reason": "requirements_fingerprint_match",
        }
    ]


def test_isolated_start_skips_incomplete_local_venv_when_supervisor_matches(monkeypatch, tmp_path):
    launcher = _load_python_launcher()
    monkeypatch.setattr(launcher.os, "name", "posix")
    supervisor = tmp_path / "supervisor"
    worktree = tmp_path / "worktree"
    supervisor.mkdir()
    worktree.mkdir()
    requirements = "fastapi>=0.111.0\n"
    (supervisor / "requirements.txt").write_text(requirements, encoding="utf-8")
    (worktree / "requirements.txt").write_text(requirements, encoding="utf-8")
    supervisor_python = _write_posix_venv_python(supervisor)
    leftover = _write_posix_venv_python(worktree)
    monkeypatch.setattr(launcher, "SUPERVISOR_ROOT", supervisor)
    monkeypatch.setattr(launcher, "PROJECT_ROOT", worktree)
    monkeypatch.setattr(launcher, "VENV_DIR", worktree / ".venv")
    monkeypatch.setattr(launcher, "REQUIREMENTS_PATH", worktree / "requirements.txt")
    monkeypatch.setattr(launcher, "RUNTIME_DIR", tmp_path / "slot-runtime" / "launcher")
    installed: list[str] = []
    monkeypatch.setattr(launcher, "_append_frontend_build_log", lambda payload: None)
    monkeypatch.setattr(launcher, "_install_project_dependencies", lambda exe: installed.append(exe))
    monkeypatch.setattr(launcher, "_create_project_virtualenv", lambda: (_ for _ in ()).throw(AssertionError("should not create")))
    monkeypatch.setattr(launcher, "_ensure_langgraph_checkpoint_sqlite_shim", lambda exe: None)
    monkeypatch.setattr(
        launcher,
        "_runtime_core_imports_available",
        lambda exe: exe == str(supervisor_python),
    )
    monkeypatch.setattr(launcher, "_runtime_imports_available", lambda exe: False)

    resolved = launcher._ensure_project_python_runtime()

    assert resolved == str(supervisor_python)
    assert leftover.exists()
    assert installed == []


def test_isolated_start_installs_private_venv_when_requirements_differ(monkeypatch, tmp_path):
    launcher = _load_python_launcher()
    monkeypatch.setattr(launcher.os, "name", "posix")
    supervisor = tmp_path / "supervisor"
    worktree = tmp_path / "worktree"
    supervisor.mkdir()
    worktree.mkdir()
    (supervisor / "requirements.txt").write_text("fastapi>=0.111.0\n", encoding="utf-8")
    (worktree / "requirements.txt").write_text("fastapi>=0.111.0\nlitellm>=1.0.0\n", encoding="utf-8")
    supervisor_python = _write_posix_venv_python(supervisor)
    worktree_python = worktree / ".venv" / "bin" / "python"
    monkeypatch.setattr(launcher, "SUPERVISOR_ROOT", supervisor)
    monkeypatch.setattr(launcher, "PROJECT_ROOT", worktree)
    monkeypatch.setattr(launcher, "VENV_DIR", worktree / ".venv")
    monkeypatch.setattr(launcher, "REQUIREMENTS_PATH", worktree / "requirements.txt")
    monkeypatch.setattr(launcher, "RUNTIME_DIR", tmp_path / "slot-runtime" / "launcher")
    installed: list[str] = []
    venv_creation: list[list[str]] = []

    def fake_run(args, **kwargs):
        if args[:3] == [launcher._bootstrap_python_executable(), "-m", "venv"]:
            venv_creation.append(list(args))
            worktree_python.parent.mkdir(parents=True, exist_ok=True)
            worktree_python.write_text("#!/usr/bin/env python3", encoding="utf-8")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(launcher.subprocess, "run", fake_run)
    monkeypatch.setattr(launcher, "_runtime_core_imports_available", lambda exe: exe == str(supervisor_python))
    monkeypatch.setattr(launcher, "_runtime_imports_available", lambda exe: False)
    monkeypatch.setattr(launcher, "_install_project_dependencies", lambda exe: installed.append(exe))
    monkeypatch.setattr(launcher, "_missing_runtime_modules", lambda exe, modules: [])
    monkeypatch.setattr(launcher, "_ensure_langgraph_checkpoint_sqlite_shim", lambda exe: None)

    resolved = launcher._ensure_project_python_runtime()

    assert resolved == str(worktree_python)
    assert installed == [str(worktree_python)]
    assert str(supervisor_python) not in installed
    assert venv_creation == [[launcher._bootstrap_python_executable(), "-m", "venv", str(worktree / ".venv")]]


def test_isolated_install_refuses_supervisor_venv(monkeypatch, tmp_path):
    launcher = _load_python_launcher()
    supervisor = tmp_path / "supervisor"
    worktree = tmp_path / "worktree"
    supervisor.mkdir()
    worktree.mkdir()
    supervisor_python = _write_posix_venv_python(supervisor)
    monkeypatch.setattr(launcher, "SUPERVISOR_ROOT", supervisor)
    monkeypatch.setattr(launcher, "PROJECT_ROOT", worktree)
    with pytest.raises(RuntimeError, match="supervisor venv"):
        launcher._install_project_dependencies(str(supervisor_python))


def test_python_launcher_dependency_install_failure_is_diagnosable(monkeypatch, tmp_path):
    launcher = _load_python_launcher()
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    requirements = project_dir / "requirements.txt"
    requirements.write_text("langchain-core>=0.1.0\n", encoding="utf-8")
    monkeypatch.setattr(launcher, "PROJECT_ROOT", project_dir)
    monkeypatch.setattr(launcher, "REQUIREMENTS_PATH", requirements)
    monkeypatch.setattr(
        launcher.subprocess,
        "run",
        lambda *args, **kwargs: types.SimpleNamespace(
            returncode=2, stdout="", stderr="ERROR: No matching distribution found for langchain-core"
        ),
    )

    with pytest.raises(RuntimeError, match="exit code 2") as exc_info:
        launcher._install_project_dependencies(str(project_dir / ".venv" / "bin" / "python"))

    assert "No matching distribution" in str(exc_info.value)


def test_python_launcher_requirements_declarations_map_to_import_modules(monkeypatch, tmp_path):
    launcher = _load_python_launcher()
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    requirements = project_dir / "requirements.txt"
    requirements.write_text(
        "\n".join(
            [
                "# comment",
                "requests>=2.28.0",
                "langchain-core>=0.1.0",
                "openai[realtime]>=2.38.0",
                'pywinpty>=3.0.5; platform_system == "Windows"',
                "pytest-xdist>=3.6.1",
                "pkg-extra @ https://example.com/pkg_extra-1.0-py3-none-any.whl",
                "",
                "fastapi >= 0.111.0",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(launcher, "PROJECT_ROOT", project_dir)
    monkeypatch.setattr(launcher, "REQUIREMENTS_PATH", requirements)
    monkeypatch.setattr(launcher.os, "name", "nt")

    expected_windows = ["requests", "langchain_core", "openai", "winpty", "xdist", "pkg_extra", "fastapi"]
    assert launcher._requirements_runtime_modules() == expected_windows

    monkeypatch.setattr(launcher.os, "name", "posix")
    assert launcher._requirements_runtime_modules() == [name for name in expected_windows if name != "winpty"]


def test_python_launcher_maps_langgraph_checkpoint_sqlite_import(monkeypatch, tmp_path):
    """langgraph-checkpoint-sqlite has no top-level module; probe must use nested import."""
    launcher = _load_python_launcher()
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    requirements = project_dir / "requirements.txt"
    requirements.write_text(
        "\n".join(
            [
                "langgraph>=0.2.0",
                "langgraph-checkpoint-sqlite>=2.0.0",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(launcher, "PROJECT_ROOT", project_dir)
    monkeypatch.setattr(launcher, "REQUIREMENTS_PATH", requirements)
    modules = launcher._requirements_runtime_modules()
    assert modules == ["langgraph", "langgraph.checkpoint.sqlite"]
    assert "langgraph_checkpoint_sqlite" not in modules


def test_python_launcher_start_launches_backend_with_project_venv_python(monkeypatch, tmp_path):
    launcher = _load_python_launcher()
    project_dir = tmp_path / "project"
    venv_python = project_dir / ".venv" / "bin" / "python"
    monkeypatch.setattr(launcher, "PROJECT_ROOT", project_dir)
    runtime_dir = tmp_path / ".runtime" / "launcher"
    monkeypatch.setattr(launcher, "RUNTIME_DIR", runtime_dir)
    monkeypatch.setattr(launcher, "PORTS_PATH", runtime_dir / "ports.json")
    monkeypatch.setattr(launcher, "BACKEND_STDOUT_PATH", runtime_dir / "backend.stdout.log")
    monkeypatch.setattr(launcher, "BACKEND_STDERR_PATH", runtime_dir / "backend.stderr.log")
    source_identity = {
        "projectRoot": str(project_dir.resolve()),
        "branch": "main",
        "commit": "a" * 40,
        "frontendTree": "tree",
        "trackedClean": True,
    }
    monkeypatch.setattr(launcher, "_read_state", lambda: {})
    monkeypatch.setattr(launcher, "_preserved_launcher_control_state", lambda state: {})
    monkeypatch.setattr(launcher, "_retire_project_workbench_instance", lambda state, port=None: [])
    monkeypatch.setattr(launcher, "_resolve_start_backend_port", lambda port, host: (8000, ""))
    monkeypatch.setattr(launcher, "_ensure_frontend_build", lambda identity, **kwargs: {})
    monkeypatch.setattr(launcher, "_runtime_source_identity", lambda: source_identity)
    monkeypatch.setattr(launcher, "_assert_runtime_source_identity", lambda identity, light=False: identity)
    monkeypatch.setattr(
        launcher,
        "_start_runtime_scene",
        lambda trigger: {
            "runtimeSceneId": "scene-1",
            "runtimeSceneDir": str(tmp_path / "scene-1"),
            "startedAt": "2026-01-01T00:00:00+00:00",
        },
    )
    monkeypatch.setattr(launcher, "_ensure_project_python_runtime", lambda: str(venv_python))
    monkeypatch.setattr(
        launcher,
        "_select_background_python",
        lambda executable: {
            "pythonExecutable": str(venv_python),
            "sourcePythonExecutable": str(venv_python),
            "noConsolePythonExecutable": str(venv_python),
            "consoleWindowSuppressed": True,
            "consoleSuppressionMode": "creation_flags",
            "consoleFallbackReason": "",
            "pythonLaunchPolicy": "pythonw",
            "creationFlagNames": ["CREATE_NO_WINDOW"],
        },
    )
    monkeypatch.setattr(launcher, "_wait_for_started_backend", lambda process, port, host: 4242)
    monkeypatch.setattr(launcher, "_remember_project_backend_port", lambda port, *, reason="": None)
    monkeypatch.setattr(launcher, "_append_frontend_build_log", lambda payload: None)
    monkeypatch.setattr(launcher, "_backend_environment", lambda host: {})
    creation_flag_requests: list[bool] = []

    def fake_windows_creation_flags(*, detach: bool = False) -> int:
        creation_flag_requests.append(detach)
        return 0

    monkeypatch.setattr(launcher, "_windows_creation_flags", fake_windows_creation_flags)
    monkeypatch.setattr(launcher, "_hidden_startup_info", lambda: None)
    written: list[dict] = []
    monkeypatch.setattr(launcher, "_write_state", lambda state: written.append(state))
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "backend.stdout.log").write_bytes(b"")
    (runtime_dir / "backend.stderr.log").write_bytes(b"")

    popen_args: list[list[str]] = []

    class FakeProcess:
        pid = 12345

        @staticmethod
        def poll():
            return None

    def fake_popen(args, **kwargs):
        popen_args.append(list(args))
        return FakeProcess()

    monkeypatch.setattr(launcher.subprocess, "Popen", fake_popen)

    state = launcher._start_backend(8000, "127.0.0.1", no_browser=True)

    assert popen_args and popen_args[0][0] == str(venv_python)
    assert popen_args[0][0] != sys.executable
    assert state["backendPid"] == 4242
    assert state["pythonExecutable"] == str(venv_python)
    assert state["lastReason"] == "python_launcher_fresh_start"
    assert written[-1]["pythonExecutable"] == str(venv_python)
    assert creation_flag_requests == [True]


def test_python_launcher_selects_venv_pythonw_on_windows(monkeypatch, tmp_path):
    launcher = _load_python_launcher()
    venv_scripts = tmp_path / ".venv" / "Scripts"
    venv_scripts.mkdir(parents=True)
    python_exe = venv_scripts / "python.exe"
    pythonw_exe = venv_scripts / "pythonw.exe"
    python_exe.write_bytes(b"")
    pythonw_exe.write_bytes(b"")
    monkeypatch.setattr(launcher.os, "name", "nt")

    result = launcher._select_background_python(str(python_exe))

    assert result["pythonExecutable"] == str(pythonw_exe)
    assert result["noConsolePythonExecutable"] == str(pythonw_exe)
    assert result["consoleFallbackReason"] == ""
    assert result["consoleWindowSuppressed"] is True
    assert result["creationFlagNames"] == ["DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP"]


def test_python_launcher_stop_reconciles_stale_state_with_real_project_port_owner(monkeypatch):
    launcher = _load_python_launcher()
    terminated: list[int] = []
    written: list[dict] = []
    monkeypatch.setattr(launcher, "_read_state", lambda: {"backendPid": 111, "backendPort": 8000, "browserWindowPid": 0})
    monkeypatch.setattr(launcher, "_listening_pid_for_port", lambda port: 222 if not terminated else 0)
    monkeypatch.setattr(launcher, "_is_project_workbench_pid", lambda pid: pid == 222)
    monkeypatch.setattr(launcher, "_terminate_pid", lambda pid: terminated.append(pid))
    monkeypatch.setattr(launcher, "_wait_for_port_release", lambda port: True)
    monkeypatch.setattr(launcher, "_write_state", lambda state: written.append(state))

    launcher._stop_backend()

    assert {111, 222} <= set(terminated)
    assert written[-1]["backendPid"] == 0


def test_python_launcher_start_auto_relocates_when_foreign_port_owner_exists(monkeypatch, tmp_path):
    launcher = _load_python_launcher()
    remembered: list[tuple[int, str]] = []

    def listening(port: int) -> int:
        return 222 if int(port) == 8000 else 0

    monkeypatch.setattr(launcher, "RUNTIME_DIR", tmp_path)
    monkeypatch.setattr(launcher, "PORTS_PATH", tmp_path / "ports.json")
    monkeypatch.setattr(launcher, "_listening_pid_for_port", listening)
    monkeypatch.setattr(launcher, "_is_project_workbench_pid", lambda pid: False)
    monkeypatch.setattr(
        launcher,
        "_remember_project_backend_port",
        lambda port, *, reason="": remembered.append((int(port), str(reason))),
    )

    # Foreign owner on preferred → free neighboring port (multi-checkout safe).
    port, note = launcher._resolve_start_backend_port(8000, "127.0.0.1")
    assert port == 8001
    assert "auto-bound" in note
    assert "222" in note
    assert remembered and remembered[-1][0] == 8001

    # Same project's owner must not be reused — start retires handles first; if still
    # listening, resolve hard-fails so we never attach to old PIDs.
    monkeypatch.setattr(launcher, "_is_project_workbench_pid", lambda pid: pid == 222)
    monkeypatch.setattr(launcher, "_backend_healthy", lambda port, host: True)
    with pytest.raises(RuntimeError, match="after instance retire"):
        launcher._resolve_start_backend_port(8000, "127.0.0.1")


def test_python_launcher_project_workbench_pid_requires_this_checkout_path(monkeypatch):
    launcher = _load_python_launcher()

    class Proc:
        def __init__(self, cmdline: list[str]):
            self._cmdline = cmdline

        def cmdline(self):
            return list(self._cmdline)

    import types

    fake_psutil = types.SimpleNamespace(
        Process=lambda pid: Proc(
            [
                "python.exe",
                r"C:\Users\Administrator\Desktop\Vibelution-live-acceptance\scripts\web_workbench.py",
                "--port",
                "8000",
            ]
        )
        if pid == 1
        else Proc(
            [
                "python.exe",
                str(launcher.PROJECT_ROOT / "scripts" / "web_workbench.py"),
                "--port",
                "8000",
            ]
        ),
    )
    monkeypatch.setitem(__import__("sys").modules, "psutil", fake_psutil)
    # pid 1 is live-acceptance → foreign; pid 2 is this PROJECT_ROOT → owned
    assert launcher._is_project_workbench_pid(1) is False
    assert launcher._is_project_workbench_pid(2) is True


def test_python_launcher_posix_listener_fallback_works_without_psutil(monkeypatch):
    launcher = _load_python_launcher()
    fake_psutil = types.SimpleNamespace(net_connections=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError()))
    monkeypatch.setitem(sys.modules, "psutil", fake_psutil)
    monkeypatch.setattr(launcher.os, "name", "posix", raising=False)
    calls: list[list[str]] = []
    monkeypatch.setattr(
        launcher.subprocess,
        "run",
        lambda args, **_kwargs: calls.append(list(args))
        or types.SimpleNamespace(stdout='LISTEN 0 2048 127.0.0.1:8000 0.0.0.0:* users:(("python",pid=4242,fd=8))'),
    )

    assert launcher._listening_pid_for_port(8000) == 4242
    assert calls == [["ss", "-ltnp", "sport = :8000"]]


def test_python_launcher_posix_parent_fallback_proves_listener_ownership_without_psutil(monkeypatch):
    launcher = _load_python_launcher()
    fake_psutil = types.SimpleNamespace(Process=lambda _pid: (_ for _ in ()).throw(RuntimeError()))
    monkeypatch.setitem(sys.modules, "psutil", fake_psutil)
    monkeypatch.setattr(launcher.os, "name", "posix", raising=False)
    parents = {4242: 3131, 3131: 2121, 2121: 1, 1: 0}
    monkeypatch.setattr(launcher, "_posix_parent_pid", lambda pid: parents.get(pid, 0))

    assert launcher._pid_belongs_to_process_tree(4242, 2121) is True
    assert launcher._pid_belongs_to_process_tree(4242, 5151) is False


def test_python_launcher_posix_command_line_fallback_recognizes_this_checkout_without_psutil(monkeypatch):
    launcher = _load_python_launcher()
    fake_psutil = types.SimpleNamespace(Process=lambda _pid: (_ for _ in ()).throw(RuntimeError()))
    monkeypatch.setitem(sys.modules, "psutil", fake_psutil)
    monkeypatch.setattr(launcher.os, "name", "posix", raising=False)
    monkeypatch.setattr(
        launcher,
        "_posix_process_command_line",
        lambda _pid: f"/opt/python {launcher.PROJECT_ROOT / 'scripts' / 'web_workbench.py'} --port 8000",
    )

    assert launcher._is_project_workbench_pid(4242) is True


def test_python_launcher_restart_builds_before_stopping_backend(monkeypatch):
    launcher = _load_python_launcher()
    calls: list[tuple[str, object]] = []
    source_identity = {
        "projectRoot": str(launcher.PROJECT_ROOT),
        "branch": "main",
        "commit": "a" * 40,
        "frontendTree": "tree-current",
        "trackedClean": True,
    }

    monkeypatch.setattr(launcher, "_assert_internal_action_authorized", lambda action: None)
    monkeypatch.setattr(launcher, "_runtime_source_identity", lambda: source_identity)
    monkeypatch.setattr(
        launcher,
        "_ensure_frontend_build",
        lambda identity: calls.append(("build", identity)) or {"rebuilt": True},
    )
    monkeypatch.setattr(
        launcher,
        "_assert_runtime_source_identity",
        lambda identity: calls.append(("assert", identity)),
    )
    monkeypatch.setattr(launcher, "_stop_backend", lambda: calls.append(("stop", None)) or {})
    monkeypatch.setattr(
        launcher,
        "_start_backend",
        lambda port, host, *, no_browser: calls.append(
            ("start", {"port": port, "host": host, "noBrowser": no_browser})
        )
        or {"instanceGeneration": 2, "previousInstanceHandles": [111]},
    )

    result = launcher.main(["--action", "restart", "--host", "127.0.0.1", "--port", "8123", "--no-browser"])

    assert result == 0
    assert calls == [
        ("build", source_identity),
        ("assert", source_identity),
        ("stop", None),
        ("start", {"port": 8123, "host": "127.0.0.1", "noBrowser": True}),
    ]


def test_python_launcher_start_always_fresh_never_short_circuits_running(monkeypatch, capsys):
    launcher = _load_python_launcher()
    calls: list[str] = []
    monkeypatch.setattr(launcher, "_assert_internal_action_authorized", lambda action: None)
    monkeypatch.setattr(
        launcher,
        "_read_state",
        lambda: {"backendPid": 999, "backendPort": 8002},
    )
    monkeypatch.setattr(launcher, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(launcher, "_backend_healthy", lambda port, host: True)
    monkeypatch.setattr(
        launcher,
        "_start_backend",
        lambda port, host, *, no_browser: calls.append("start")
        or {
            "backendPid": 1001,
            "backendLaunchPid": 1000,
            "previousInstanceHandles": [999],
            "instanceGeneration": 1,
        },
    )

    result = launcher.main(["--action", "start", "--host", "127.0.0.1", "--port", "8002", "--no-browser"])

    assert result == 0
    assert calls == ["start"]
    out = capsys.readouterr().out
    assert "fresh instance" in out
    assert "already running" not in out


def test_python_launcher_start_retires_previous_handles_before_spawn(monkeypatch, tmp_path):
    launcher = _load_python_launcher()
    terminated: list[int] = []
    previous = {
        "backendPid": 111,
        "backendLaunchPid": 110,
        "browserWindowPid": 222,
        "browserLaunchPid": 221,
        "backendPort": 8000,
        "instanceGeneration": 3,
    }

    monkeypatch.setattr(launcher, "RUNTIME_DIR", tmp_path)
    monkeypatch.setattr(launcher, "PORTS_PATH", tmp_path / "ports.json")
    monkeypatch.setattr(launcher, "BACKEND_STDOUT_PATH", tmp_path / "backend.stdout.log")
    monkeypatch.setattr(launcher, "BACKEND_STDERR_PATH", tmp_path / "backend.stderr.log")
    monkeypatch.setattr(launcher, "ACTIVE_RUNTIME_SCENE_PATH", tmp_path / "active-runtime-scene.json")
    monkeypatch.setattr(launcher, "RUNTIME_SCENE_ROOT", tmp_path / "scenes")
    monkeypatch.setattr(launcher, "_read_state", lambda: dict(previous))
    monkeypatch.setattr(launcher, "_listening_pid_for_port", lambda port: 111 if port == 8000 and 111 not in terminated else 0)
    monkeypatch.setattr(launcher, "_is_project_workbench_pid", lambda pid: pid in {111, 110})
    monkeypatch.setattr(launcher, "_terminate_pid", lambda pid: terminated.append(int(pid)))
    monkeypatch.setattr(launcher, "_wait_for_port_release", lambda port: True)
    monkeypatch.setattr(launcher, "_runtime_source_identity", lambda: {
        "projectRoot": str(tmp_path.resolve()),
        "branch": "main",
        "commit": "a" * 40,
        "frontendTree": "tree",
        "trackedClean": True,
        "allowDirty": False,
        "ignoredUserSceneEntries": [],
    })
    monkeypatch.setattr(
        launcher,
        "_ensure_frontend_build",
        lambda identity, **kwargs: {
            "rebuilt": False,
            "sourceCommit": "a" * 40,
            "frontendTree": "tree",
            "builtFromCommit": "a" * 40,
        },
    )
    monkeypatch.setattr(launcher, "_assert_runtime_source_identity", lambda identity, light=False: identity)
    monkeypatch.setattr(launcher, "_start_runtime_scene", lambda trigger: {
        "runtimeSceneId": "scene",
        "runtimeSceneDir": str(tmp_path / "scene"),
        "startedAt": "t0",
    })
    monkeypatch.setattr(launcher, "_select_background_python", lambda runtime: {
        "pythonExecutable": str(tmp_path / "pythonw.exe"),
        "sourcePythonExecutable": str(tmp_path / "python.exe"),
        "noConsolePythonExecutable": str(tmp_path / "pythonw.exe"),
        "consoleWindowSuppressed": True,
        "consoleSuppressionMode": "creation_flags",
        "consoleFallbackReason": "",
        "pythonLaunchPolicy": "pythonw",
        "creationFlagNames": ["CREATE_NO_WINDOW"],
    })
    monkeypatch.setattr(launcher, "_ensure_project_python_runtime", lambda: {})
    monkeypatch.setattr(launcher, "_backend_environment", lambda host: {})
    monkeypatch.setattr(launcher, "_windows_creation_flags", lambda *, detach=False: 0)
    monkeypatch.setattr(launcher, "_hidden_startup_info", lambda: None)
    monkeypatch.setattr(launcher, "_append_frontend_build_log", lambda payload: None)
    monkeypatch.setattr(launcher, "_remember_project_backend_port", lambda port, *, reason="": None)
    written: list[dict] = []
    monkeypatch.setattr(launcher, "_write_state", lambda state: written.append(dict(state)))
    monkeypatch.setattr(launcher, "_preserved_launcher_control_state", lambda state: {})

    class FakeProc:
        pid = 5000

    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *a, **k: FakeProc())
    monkeypatch.setattr(launcher, "_wait_for_started_backend", lambda process, port, host: 5001)

    (tmp_path / "backend.stdout.log").write_bytes(b"")
    (tmp_path / "backend.stderr.log").write_bytes(b"")

    state = launcher._start_backend(8000, "127.0.0.1", no_browser=True)

    assert 111 in terminated
    assert 110 in terminated
    assert 222 in terminated
    assert 221 in terminated
    assert state["backendPid"] == 5001
    assert state["backendLaunchPid"] == 5000
    assert state["instanceGeneration"] == 4
    assert set(state["previousInstanceHandles"]) >= {111, 110, 222, 221}
    assert state["lastReason"] == "python_launcher_fresh_start"
    assert state["sessionId"]


def test_python_launcher_stop_preserves_state_when_a_foreign_port_owner_remains(monkeypatch):
    launcher = _load_python_launcher()
    written: list[dict] = []
    monkeypatch.setattr(launcher, "_read_state", lambda: {"backendPid": 111, "backendPort": 8000})
    monkeypatch.setattr(launcher, "_listening_pid_for_port", lambda port: 333)
    monkeypatch.setattr(launcher, "_is_project_workbench_pid", lambda pid: False)
    monkeypatch.setattr(launcher, "_terminate_pid", lambda pid: None)
    monkeypatch.setattr(launcher, "_wait_for_port_release", lambda port: False)
    monkeypatch.setattr(launcher, "_write_state", lambda state: written.append(state))

    state = launcher._stop_backend()

    assert state["desiredState"] == "closed"
    assert state["backendPid"] == 0
    assert written
    assert written[-1]["desiredState"] == "closed"


def test_python_launcher_does_not_accept_a_healthy_listener_owned_by_another_process(monkeypatch):
    launcher = _load_python_launcher()

    class Process:
        pid = 111

        @staticmethod
        def poll():
            return None

    clock = iter((0.0, 0.0, 1.0))
    monkeypatch.setattr(launcher.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(launcher.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(launcher, "_listening_pid_for_port", lambda port: 222)
    monkeypatch.setattr(launcher, "_pid_belongs_to_process_tree", lambda owner_pid, root_pid: False)
    monkeypatch.setattr(launcher, "_backend_healthy", lambda port, host: True)

    assert launcher._wait_for_started_backend(Process(), 8000, "127.0.0.1", timeout_seconds=0.1) == 0


def test_python_launcher_accepts_healthy_spawn_when_listener_pid_is_unresolvable(monkeypatch):
    launcher = _load_python_launcher()

    class Process:
        pid = 7188

        @staticmethod
        def poll():
            return None

    monkeypatch.setattr(launcher, "_listening_pid_for_port", lambda port: 0)
    monkeypatch.setattr(launcher, "_backend_healthy", lambda port, host: True)
    monkeypatch.setattr(launcher.time, "sleep", lambda _seconds: None)

    assert launcher._wait_for_started_backend(Process(), 8000, "127.0.0.1", timeout_seconds=5.0) == 7188


def test_python_launcher_start_backend_requires_current_frontend(monkeypatch, tmp_path):
    launcher = _load_python_launcher()
    project_dir = tmp_path / "project"
    venv_python = project_dir / ".venv" / "bin" / "python"
    monkeypatch.setattr(launcher, "PROJECT_ROOT", project_dir)
    runtime_dir = tmp_path / ".runtime" / "launcher"
    monkeypatch.setattr(launcher, "RUNTIME_DIR", runtime_dir)
    monkeypatch.setattr(launcher, "PORTS_PATH", runtime_dir / "ports.json")
    monkeypatch.setattr(launcher, "BACKEND_STDOUT_PATH", runtime_dir / "backend.stdout.log")
    monkeypatch.setattr(launcher, "BACKEND_STDERR_PATH", runtime_dir / "backend.stderr.log")
    source_identity = {
        "projectRoot": str(project_dir.resolve()),
        "branch": "main",
        "commit": "a" * 40,
        "frontendTree": "tree",
        "trackedClean": True,
    }
    ensure_calls: list[dict[str, object]] = []

    def fake_ensure(identity, *, require_current=True):
        ensure_calls.append({"identity": identity, "require_current": require_current})
        return {"rebuilt": False, "skipped": False, "skipReason": ""}

    monkeypatch.setattr(launcher, "_read_state", lambda: {})
    monkeypatch.setattr(launcher, "_preserved_launcher_control_state", lambda state: {})
    monkeypatch.setattr(launcher, "_retire_project_workbench_instance", lambda state, port=None: [])
    monkeypatch.setattr(launcher, "_resolve_start_backend_port", lambda port, host: (8000, ""))
    monkeypatch.setattr(launcher, "_ensure_frontend_build", fake_ensure)
    monkeypatch.setattr(launcher, "_runtime_source_identity", lambda: source_identity)
    monkeypatch.setattr(launcher, "_assert_runtime_source_identity", lambda identity, light=False: identity)
    monkeypatch.setattr(
        launcher,
        "_start_runtime_scene",
        lambda trigger: {
            "runtimeSceneId": "scene-1",
            "runtimeSceneDir": str(tmp_path / "scene-1"),
            "startedAt": "2026-01-01T00:00:00+00:00",
        },
    )
    monkeypatch.setattr(launcher, "_ensure_project_python_runtime", lambda: str(venv_python))
    monkeypatch.setattr(
        launcher,
        "_select_background_python",
        lambda executable: {
            "pythonExecutable": str(venv_python),
            "sourcePythonExecutable": str(venv_python),
            "noConsolePythonExecutable": str(venv_python),
            "consoleWindowSuppressed": True,
            "consoleSuppressionMode": "creation_flags",
            "consoleFallbackReason": "",
            "pythonLaunchPolicy": "pythonw",
            "creationFlagNames": ["CREATE_NO_WINDOW"],
        },
    )
    monkeypatch.setattr(launcher, "_wait_for_started_backend", lambda process, port, host: 4242)
    monkeypatch.setattr(launcher, "_remember_project_backend_port", lambda port, *, reason="": None)
    monkeypatch.setattr(launcher, "_append_frontend_build_log", lambda payload: None)
    monkeypatch.setattr(launcher, "_backend_environment", lambda host: {})
    monkeypatch.setattr(launcher, "_windows_creation_flags", lambda *, detach=False: 0)
    monkeypatch.setattr(launcher, "_hidden_startup_info", lambda: None)
    monkeypatch.setattr(launcher, "_write_state", lambda state: None)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "backend.stdout.log").write_bytes(b"")
    (runtime_dir / "backend.stderr.log").write_bytes(b"")

    class FakeProcess:
        pid = 12345

        @staticmethod
        def poll():
            return None

    monkeypatch.setattr(launcher.subprocess, "Popen", lambda args, **kwargs: FakeProcess())

    launcher._start_backend(8000, "127.0.0.1", no_browser=True)

    assert ensure_calls == [{"identity": source_identity, "require_current": True}]


def test_python_launcher_runtime_identity_requires_clean_main(monkeypatch, tmp_path):
    launcher = _load_python_launcher()
    monkeypatch.setattr(launcher, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("VIBELUTION_ALLOW_NON_MAIN_LAUNCH", raising=False)
    monkeypatch.setattr(launcher, "_path_looks_like_task_worktree", lambda _root: False)
    monkeypatch.setattr(launcher, "_is_linked_git_worktree", lambda _cwd, _git: False)

    def fake_capture(args, *, cwd, label, timeout=15.0):
        values = {
            "git root identity": str(tmp_path),
            "git branch identity": "codex/task",
        }
        return values[label]

    monkeypatch.setattr(launcher, "_run_capture", fake_capture)

    with pytest.raises(RuntimeError, match="requires the integration checkout on local main"):
        launcher._runtime_source_identity()


def test_python_launcher_runtime_identity_allows_task_worktree_branch(monkeypatch, tmp_path):
    launcher = _load_python_launcher()
    worktree = tmp_path / "Vibelution-worktrees" / "feat-task"
    worktree.mkdir(parents=True)
    monkeypatch.setattr(launcher, "PROJECT_ROOT", worktree)
    monkeypatch.delenv("VIBELUTION_ALLOW_NON_MAIN_LAUNCH", raising=False)
    monkeypatch.delenv("VIBELUTION_ALLOW_DIRTY_LAUNCH", raising=False)

    def fake_capture(args, *, cwd, label, timeout=15.0):
        values = {
            "git root identity": str(worktree),
            "git branch identity": "codex/feat-task",
            "git commit identity": "b" * 40,
            "git worktree identity": "",
            "frontend tree identity": "tree-b",
            "git dir identity": str(worktree / ".git"),
            "git common-dir identity": str(tmp_path / ".git"),
        }
        return values[label]

    monkeypatch.setattr(launcher, "_run_capture", fake_capture)
    monkeypatch.setattr(launcher, "_resolve_git_executable", lambda: "git")

    identity = launcher._runtime_source_identity()

    assert identity["branch"] == "codex/feat-task"
    assert identity["commit"] == "b" * 40


def test_python_launcher_treats_in_repo_worktrees_as_task_checkouts(tmp_path):
    launcher = _load_python_launcher()
    in_repo = tmp_path / "project" / ".worktrees" / "feat-task"
    retired = tmp_path / "project" / ".worktrees" / "_retired" / "old"
    legacy = tmp_path / "Vibelution-worktrees" / "legacy-task"
    in_repo.mkdir(parents=True)
    retired.mkdir(parents=True)
    legacy.mkdir(parents=True)

    assert launcher._path_looks_like_task_worktree(in_repo) is True
    assert launcher._path_looks_like_task_worktree(retired) is False
    assert launcher._path_looks_like_task_worktree(legacy) is True
    assert launcher._path_looks_like_task_worktree(tmp_path / "project") is False


def test_python_launcher_subprocess_text_kwargs_replace_invalid_utf8():
    launcher = _load_python_launcher()
    kwargs = launcher._subprocess_text_kwargs()
    assert kwargs["text"] is True
    assert kwargs["encoding"] == "utf-8"
    assert kwargs["errors"] == "replace"
    # Reader-thread must not raise on Windows locale bytes (e.g. 0xbb in GBK).
    assert b"\xbb".decode(kwargs["encoding"], errors=kwargs["errors"]) == "\ufffd"


def test_python_launcher_runtime_identity_rejects_dirty_main(monkeypatch, tmp_path):
    launcher = _load_python_launcher()
    monkeypatch.setattr(launcher, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("VIBELUTION_ALLOW_DIRTY_LAUNCH", raising=False)

    def fake_capture(args, *, cwd, label, timeout=15.0):
        values = {
            "git root identity": str(tmp_path),
            "git branch identity": "main",
            "git commit identity": "a" * 40,
            "git worktree identity": " M core/app.py",
            "frontend tree identity": "tree-a",
        }
        return values[label]

    monkeypatch.setattr(launcher, "_run_capture", fake_capture)

    with pytest.raises(RuntimeError, match="requires a clean local main"):
        launcher._runtime_source_identity()


def test_python_launcher_runtime_identity_allows_known_user_scene_manifest(monkeypatch, tmp_path):
    launcher = _load_python_launcher()
    monkeypatch.setattr(launcher, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("VIBELUTION_ALLOW_DIRTY_LAUNCH", raising=False)

    def fake_capture(args, *, cwd, label, timeout=15.0):
        values = {
            "git root identity": str(tmp_path),
            "git branch identity": "main",
            "git commit identity": "a" * 40,
            "git worktree identity": "?? scripts/_tmp_stash_p3_manifest/LATEST.json\n?? scripts/_tmp_stash_p3_manifest/manifest.json",
            "frontend tree identity": "tree-a",
        }
        return values[label]

    monkeypatch.setattr(launcher, "_run_capture", fake_capture)

    identity = launcher._runtime_source_identity()

    assert identity["trackedClean"] is True
    assert identity["ignoredUserSceneEntries"] == 2


def test_python_launcher_runtime_identity_rejects_other_untracked_files(monkeypatch, tmp_path):
    launcher = _load_python_launcher()
    monkeypatch.setattr(launcher, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("VIBELUTION_ALLOW_DIRTY_LAUNCH", raising=False)

    def fake_capture(args, *, cwd, label, timeout=15.0):
        values = {
            "git root identity": str(tmp_path),
            "git branch identity": "main",
            "git commit identity": "a" * 40,
            "git worktree identity": "?? scripts/_tmp_stash_p3_manifest/LATEST.json\n?? core/unsafe_runtime_override.py",
            "frontend tree identity": "tree-a",
        }
        return values[label]

    monkeypatch.setattr(launcher, "_run_capture", fake_capture)

    with pytest.raises(RuntimeError, match="core/unsafe_runtime_override.py"):
        launcher._runtime_source_identity()


def test_python_launcher_runtime_identity_allows_dirty_when_opted_in(monkeypatch, tmp_path):
    launcher = _load_python_launcher()
    monkeypatch.setattr(launcher, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("VIBELUTION_ALLOW_DIRTY_LAUNCH", "1")

    def fake_capture(args, *, cwd, label, timeout=15.0):
        values = {
            "git root identity": str(tmp_path),
            "git branch identity": "main",
            "git commit identity": "a" * 40,
            "git worktree identity": " M core/app.py",
            "frontend tree identity": "tree-a",
        }
        return values[label]

    monkeypatch.setattr(launcher, "_run_capture", fake_capture)

    identity = launcher._runtime_source_identity()
    assert identity["trackedClean"] is False
    assert identity["allowDirty"] is True


def test_python_launcher_rejects_main_change_during_refresh(monkeypatch):
    launcher = _load_python_launcher()
    expected = {
        "projectRoot": "C:/repo",
        "branch": "main",
        "commit": "a" * 40,
        "frontendTree": "tree-a",
    }
    monkeypatch.setattr(
        launcher,
        "_runtime_source_identity",
        lambda: {**expected, "commit": "b" * 40},
    )

    with pytest.raises(RuntimeError, match="changed while Launcher was refreshing"):
        launcher._assert_runtime_source_identity(expected)


def test_python_launcher_light_identity_assert_skips_full_worktree_scan(monkeypatch):
    launcher = _load_python_launcher()
    expected = {
        "projectRoot": "C:/repo",
        "branch": "main",
        "commit": "a" * 40,
        "frontendTree": "tree-a",
        "allowDirty": True,
    }
    full_calls: list[object] = []
    light_calls: list[object] = []
    monkeypatch.setattr(
        launcher,
        "_runtime_source_identity",
        lambda **kwargs: full_calls.append(kwargs) or dict(expected),
    )
    monkeypatch.setattr(
        launcher,
        "_runtime_source_identity_light",
        lambda **kwargs: light_calls.append(kwargs) or dict(expected),
    )

    assert launcher._assert_runtime_source_identity(expected, light=True)["commit"] == "a" * 40
    assert light_calls == [{"allow_dirty": True}]
    assert full_calls == []


def test_web_workbench_access_log_filter_suppresses_polling_noise_only():
    from scripts.web_workbench import WorkbenchAccessLogFilter

    log_filter = WorkbenchAccessLogFilter()

    def access_record(message: str) -> logging.LogRecord:
        return logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, message, (), None)

    suppressed_messages = [
        '127.0.0.1:51112 - "GET /api/health HTTP/1.1" 200 OK',
        '127.0.0.1:51113 - "GET /api/runtime/summary HTTP/1.1" 200 OK',
        '127.0.0.1:51114 - "GET /api/git/status HTTP/1.1" 200 OK',
        '127.0.0.1:51115 - "GET /api/evolution/active-run HTTP/1.1" 200 OK',
        '127.0.0.1:51116 - "GET /api/evolution/runs HTTP/1.1" 200 OK',
        '127.0.0.1:51117 - "POST /api/runtime/browser-telemetry HTTP/1.1" 202 Accepted',
    ]
    kept_messages = [
        '127.0.0.1:51118 - "POST /api/evolution/runs HTTP/1.1" 202 Accepted',
        '127.0.0.1:51119 - "POST /api/evolution/proposals/delete HTTP/1.1" 200 OK',
        '127.0.0.1:51120 - "GET /supervised-evolution HTTP/1.1" 200 OK',
        '127.0.0.1:51121 - "GET /assets/index.js HTTP/1.1" 200 OK',
        'application startup complete',
    ]

    assert all(log_filter.filter(access_record(message)) is False for message in suppressed_messages)
    assert all(log_filter.filter(access_record(message)) is True for message in kept_messages)


def test_web_workbench_access_log_filter_installs_once(monkeypatch):
    from scripts.web_workbench import WorkbenchAccessLogFilter, install_access_log_filters

    logger = logging.getLogger("uvicorn.access")
    original_filters = list(logger.filters)
    logger.filters = []
    try:
        install_access_log_filters()
        install_access_log_filters()

        assert sum(isinstance(item, WorkbenchAccessLogFilter) for item in logger.filters) == 1
    finally:
        logger.filters = original_filters


def test_web_workbench_enables_windows_user_env_fallback(monkeypatch):
    from scripts import web_workbench

    monkeypatch.setattr(web_workbench.os, "name", "nt", raising=False)
    monkeypatch.delenv(web_workbench.USER_ENV_FALLBACK_ENV, raising=False)

    web_workbench.enable_user_env_fallback_for_workbench()

    assert os.environ[web_workbench.USER_ENV_FALLBACK_ENV] == "1"


def test_web_workbench_preserves_explicit_user_env_fallback(monkeypatch):
    from scripts import web_workbench

    monkeypatch.setattr(web_workbench.os, "name", "nt", raising=False)
    monkeypatch.setenv(web_workbench.USER_ENV_FALLBACK_ENV, "0")

    web_workbench.enable_user_env_fallback_for_workbench()

    assert os.environ[web_workbench.USER_ENV_FALLBACK_ENV] == "0"


def test_web_workbench_accepts_managed_launcher_marker():
    from scripts import web_workbench

    args = web_workbench.parse_args(
        [
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
            "--no-browser",
            "--managed-by-launcher",
        ]
    )

    assert args.managed_by_launcher is True


def test_web_workbench_is_headless_by_default():
    from scripts import web_workbench

    args = web_workbench.parse_args([])

    assert args.open_browser is False
    assert args.no_browser is False


def test_web_workbench_open_browser_is_explicit_and_no_browser_wins():
    from scripts import web_workbench

    assert web_workbench.parse_args(["--open-browser"]).open_browser is True
    assert web_workbench.parse_args(["--open-browser", "--no-browser"]).open_browser is False


def test_web_workbench_main_does_not_open_browser_by_default(monkeypatch):
    from scripts import web_workbench

    opened: list[str] = []
    uvicorn_calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        web_workbench,
        "parse_args",
        lambda: Namespace(host="127.0.0.1", port=8000, reload=False, open_browser=False),
    )
    monkeypatch.setattr(web_workbench.webbrowser, "open", lambda url: opened.append(url))
    monkeypatch.setattr(
        web_workbench.uvicorn,
        "run",
        lambda app, **kwargs: uvicorn_calls.append({"app": app, **kwargs}),
    )

    web_workbench.main()

    assert opened == []
    assert uvicorn_calls == [
        {"app": "core.web.app:app", "host": "127.0.0.1", "port": 8000, "reload": False}
    ]


def _powershell_exe() -> str:
    exe = shutil.which("powershell") or shutil.which("pwsh")
    if not exe:
        pytest.skip("PowerShell is required for launcher script tests")
    return exe


def _cscript_exe() -> str:
    exe = shutil.which("cscript")
    if not exe:
        pytest.skip("cscript is required for VBS desktop entry tests")
    return exe


def _loads_json_line_allowing_control_chars(line: str) -> dict[str, object]:
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        sanitized = "".join(char for char in line if char >= " " or char in "\t\r\n")
        return json.loads(sanitized)


def _resolve_launcher_backend_port(
    tmp_path: Path,
    *,
    config_text: str,
    env_overrides: dict[str, str] | None = None,
) -> int:
    config_path = tmp_path / "config.toml"
    config_path.write_text(config_text, encoding="utf-8")

    harness_path = tmp_path / "resolve-launcher-port.ps1"
    harness_path.write_text(
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath,
    [Parameter(Mandatory = $true)]
    [string]$ConfigPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -Encoding UTF8 -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

$functionAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Resolve-ConfiguredWorkbenchPort"
}, $true)
if ($null -eq $functionAst) {
    throw "Resolve-ConfiguredWorkbenchPort was not found."
}

. ([scriptblock]::Create($functionAst.Extent.Text))
Set-Variable -Name configPath -Value $ConfigPath -Scope Script
Write-Output ([string](Resolve-ConfiguredWorkbenchPort))
""".strip(),
        encoding="utf-8-sig",
    )

    command = [_powershell_exe(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness_path)]
    command += ["-LauncherPath", str(LAUNCHER_SCRIPT), "-ConfigPath", str(config_path)]
    env = os.environ.copy()
    env.pop("VIBELUTION_PORT", None)
    env.pop("AGENT_WORKBENCH_BACKEND_PORT", None)
    if env_overrides:
        env.update(env_overrides)

    result = subprocess.run(command, capture_output=True, text=True, env=env, check=False, timeout=20)
    assert result.returncode == 0, result.stderr or result.stdout
    return int(result.stdout.strip().splitlines()[-1])


def _resolve_launcher_control_port(
    tmp_path: Path,
    *,
    config_text: str,
    env_overrides: dict[str, str] | None = None,
    workbench_port: int = 8000,
) -> int:
    config_path = tmp_path / "config.toml"
    config_path.write_text(config_text, encoding="utf-8")

    harness_path = tmp_path / "resolve-launcher-control-port.ps1"
    harness_path.write_text(
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath,
    [Parameter(Mandatory = $true)]
    [string]$ConfigPath,
    [Parameter(Mandatory = $true)]
    [int]$WorkbenchPort
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -Encoding UTF8 -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

$functionAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Resolve-ConfiguredLauncherControlPort"
}, $true)
if ($null -eq $functionAst) {
    throw "Resolve-ConfiguredLauncherControlPort was not found."
}

. ([scriptblock]::Create($functionAst.Extent.Text))
Set-Variable -Name configPath -Value $ConfigPath -Scope Script
Write-Output ([string](Resolve-ConfiguredLauncherControlPort -WorkbenchPort $WorkbenchPort))
""".strip(),
        encoding="utf-8-sig",
    )

    command = [_powershell_exe(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness_path)]
    command += ["-LauncherPath", str(LAUNCHER_SCRIPT), "-ConfigPath", str(config_path), "-WorkbenchPort", str(workbench_port)]
    env = os.environ.copy()
    env.pop("VIBELUTION_LAUNCHER_PORT", None)
    env.pop("AGENT_LAUNCHER_CONTROL_PORT", None)
    if env_overrides:
        env.update(env_overrides)

    result = subprocess.run(command, capture_output=True, text=True, env=env, check=False, timeout=20)
    assert result.returncode == 0, result.stderr or result.stdout
    return int(result.stdout.strip().splitlines()[-1])


def _resolve_launcher_window_mode(
    tmp_path: Path,
    *,
    config_text: str,
    env_overrides: dict[str, str] | None = None,
) -> str:
    config_path = tmp_path / "config.toml"
    config_path.write_text(config_text, encoding="utf-8")

    harness_path = tmp_path / "resolve-launcher-window-mode.ps1"
    harness_path.write_text(
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath,
    [Parameter(Mandatory = $true)]
    [string]$ConfigPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -Encoding UTF8 -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

$functionAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Resolve-ConfiguredWorkbenchWindowMode"
}, $true)
if ($null -eq $functionAst) {
    throw "Resolve-ConfiguredWorkbenchWindowMode was not found."
}

. ([scriptblock]::Create($functionAst.Extent.Text))
Set-Variable -Name configPath -Value $ConfigPath -Scope Script
Write-Output ([string](Resolve-ConfiguredWorkbenchWindowMode))
""".strip(),
        encoding="utf-8-sig",
    )

    command = [_powershell_exe(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness_path)]
    command += ["-LauncherPath", str(LAUNCHER_SCRIPT), "-ConfigPath", str(config_path)]
    env = os.environ.copy()
    env.pop("VIBELUTION_WORKBENCH_WINDOW_MODE", None)
    env.pop("AGENT_WORKBENCH_WINDOW_MODE", None)
    if env_overrides:
        env.update(env_overrides)

    result = subprocess.run(command, capture_output=True, text=True, env=env, check=False, timeout=20)
    assert result.returncode == 0, result.stderr or result.stdout
    return result.stdout.strip().splitlines()[-1]


def _resolve_launcher_window_size(
    tmp_path: Path,
    *,
    config_text: str,
    env_overrides: dict[str, str] | None = None,
) -> str:
    config_path = tmp_path / "config.toml"
    config_path.write_text(config_text, encoding="utf-8")

    harness_path = tmp_path / "resolve-launcher-window-size.ps1"
    harness_path.write_text(
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath,
    [Parameter(Mandatory = $true)]
    [string]$ConfigPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -Encoding UTF8 -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

foreach ($functionName in @("Test-WorkbenchWindowSizeValue", "ConvertTo-EdgeWindowSizeArgument", "Resolve-ConfiguredWorkbenchWindowSize")) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $functionName
    }, $true)
    if ($null -eq $functionAst) {
        throw "$functionName was not found."
    }
    . ([scriptblock]::Create($functionAst.Extent.Text))
}

Set-Variable -Name configPath -Value $ConfigPath -Scope Script
$size = [string](Resolve-ConfiguredWorkbenchWindowSize)
$argument = [string](ConvertTo-EdgeWindowSizeArgument -Value $size)
Write-Output "$size|$argument"
""".strip(),
        encoding="utf-8-sig",
    )

    command = [_powershell_exe(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness_path)]
    command += ["-LauncherPath", str(LAUNCHER_SCRIPT), "-ConfigPath", str(config_path)]
    env = os.environ.copy()
    env.pop("VIBELUTION_WORKBENCH_WINDOW_SIZE", None)
    env.pop("AGENT_WORKBENCH_WINDOW_SIZE", None)
    if env_overrides:
        env.update(env_overrides)

    result = subprocess.run(command, capture_output=True, text=True, env=env, check=False, timeout=20)
    assert result.returncode == 0, result.stderr or result.stdout
    return result.stdout.strip().splitlines()[-1]


def _run_desktop_entry_with_fake_launcher(
    tmp_path: Path,
    *,
    action: str,
    no_browser: bool = False,
    launcher_source: str | None = None,
    env_overrides: dict[str, str] | None = None,
) -> list[dict[str, object]]:
    project_dir = tmp_path / "project"
    scripts_dir = project_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    venv_scripts_dir = project_dir / ".venv" / "Scripts"
    venv_scripts_dir.mkdir(parents=True)
    (venv_scripts_dir / "python.exe").write_text("console python", encoding="utf-8")
    (venv_scripts_dir / "python.exe").write_text("console python", encoding="utf-8")
    shutil.copyfile(DESKTOP_ENTRY_SCRIPT, scripts_dir / "vibelution_desktop_entry.ps1")
    (scripts_dir / "vibelution_launcher.ps1").write_text(
        launcher_source
        or """
param(
    [string]$Action = "",
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$projectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$logDir = Join-Path $projectDir ".runtime\\launcher"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}
$payload = @{
    action = $Action
    noBrowser = [bool]$NoBrowser
    argv = @($args)
    pythonExe = $env:VIBELUTION_PYTHON_EXE
} | ConvertTo-Json -Depth 8 -Compress
Add-Content -LiteralPath (Join-Path $logDir "fake-launcher-calls.jsonl") -Value $payload -Encoding utf8
""".strip(),
        encoding="utf-8",
    )

    command = [
        _powershell_exe(),
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(scripts_dir / "vibelution_desktop_entry.ps1"),
        "-Action",
        action,
    ]
    if no_browser:
        command.append("-NoBrowser")

    env = os.environ.copy()
    env["VIBELUTION_DESKTOP_ENTRY_SUPPRESS_FEEDBACK"] = "1"
    env["VIBELUTION_DESKTOP_ENTRY_START_MUTEX_NAME"] = f"Local\\Vibelution.Tests.{tmp_path.name}.{action}"
    if env_overrides:
        env.update(env_overrides)
    result = subprocess.run(command, capture_output=True, text=True, cwd=project_dir, env=env, check=False, timeout=30)
    assert result.returncode == 0, result.stderr or result.stdout

    calls_path = project_dir / ".runtime" / "launcher" / "fake-launcher-calls.jsonl"
    assert calls_path.exists()
    return [json.loads(line) for line in calls_path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def _run_vbs_desktop_entry_with_fake_powershell_entry(
    tmp_path: Path,
    args: list[str],
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    project_dir = tmp_path / "project"
    scripts_dir = project_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    venv_scripts_dir = project_dir / ".venv" / "Scripts"
    venv_scripts_dir.mkdir(parents=True)
    (venv_scripts_dir / "python.exe").write_text("console python", encoding="utf-8")
    (venv_scripts_dir / "python.exe").write_text("console python", encoding="utf-8")
    shutil.copyfile(DESKTOP_ENTRY_VBS, scripts_dir / "vibelution_desktop_entry.vbs")
    # This helper verifies VBS routing only; the native Python bridge is tested
    # separately, so it must not start the real Launcher backend or Edge window.
    (scripts_dir / "vibelution_desktop_entry.py").write_text(
        """
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

project_dir = Path(__file__).resolve().parent.parent
log_dir = project_dir / ".runtime" / "launcher"
log_dir.mkdir(parents=True, exist_ok=True)
payload = {
    "argv": sys.argv[1:],
    "cwd": os.getcwd(),
    "pythonExe": sys.executable,
    "runId": os.environ.get("VIBELUTION_DESKTOP_ENTRY_VBS_RUN_ID", ""),
}
with (log_dir / "fake-python-bridge-calls.jsonl").open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\\n")
""".lstrip(),
        encoding="utf-8",
    )
    (scripts_dir / "vibelution_desktop_entry.ps1").write_text(
        """
param(
    [string]$Action = "",
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$projectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$logDir = Join-Path $projectDir ".runtime\\launcher"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}
$payload = @{
    action = $Action
    noBrowser = [bool]$NoBrowser
    argv = @($args)
    pythonExe = $env:VIBELUTION_PYTHON_EXE
} | ConvertTo-Json -Depth 8 -Compress
Add-Content -LiteralPath (Join-Path $logDir "fake-vbs-entry-calls.jsonl") -Value $payload -Encoding utf8
""".strip(),
        encoding="utf-8",
    )
    (scripts_dir / "vibelution_launcher.ps1").write_text(
        """
param(
    [string]$Action = "",
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$projectDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$logDir = Join-Path $projectDir ".runtime\\launcher"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}
$payload = @{
    action = $Action
    noBrowser = [bool]$NoBrowser
    argv = @($args)
    pythonExe = $env:VIBELUTION_PYTHON_EXE
} | ConvertTo-Json -Depth 8 -Compress
Add-Content -LiteralPath (Join-Path $logDir "fake-vbs-entry-calls.jsonl") -Value $payload -Encoding utf8
""".strip(),
        encoding="utf-8",
    )

    command = [_cscript_exe(), "//NoLogo", str(scripts_dir / "vibelution_desktop_entry.vbs"), *args]
    env = os.environ.copy()
    env["VIBELUTION_DESKTOP_ENTRY_SUPPRESS_FEEDBACK"] = "1"
    env["VIBELUTION_DESKTOP_ENTRY_START_MUTEX_NAME"] = f"Local\\Vibelution.Tests.{tmp_path.name}.failure.{time.time_ns()}"
    env["VIBELUTION_DESKTOP_ENTRY_PYTHON_BRIDGE_EXE"] = sys.executable
    result = subprocess.run(command, capture_output=True, text=True, cwd=project_dir, env=env, check=False, timeout=30)
    assert result.returncode == 0, result.stderr or result.stdout

    calls_path = project_dir / ".runtime" / "launcher" / "fake-vbs-entry-calls.jsonl"
    python_bridge_calls_path = project_dir / ".runtime" / "launcher" / "fake-python-bridge-calls.jsonl"
    expect_powershell_entry_call = not _vbs_args_target_launcher(args)
    expect_python_bridge_call = _vbs_args_target_launcher(args)
    if expect_powershell_entry_call:
        deadline = time.time() + 5
        while time.time() < deadline and not calls_path.exists():
            time.sleep(0.05)
        assert calls_path.exists()
    if expect_python_bridge_call:
        deadline = time.time() + 5
        while time.time() < deadline and not python_bridge_calls_path.exists():
            time.sleep(0.05)
        assert python_bridge_calls_path.exists()
    calls_text = ""
    if calls_path.exists():
        last_permission_error: PermissionError | None = None
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                calls_text = calls_path.read_text(encoding="utf-8-sig")
                last_permission_error = None
                break
            except PermissionError as exc:
                last_permission_error = exc
                time.sleep(0.05)
        if last_permission_error is not None:
            raise last_permission_error
    calls = [json.loads(line) for line in calls_text.splitlines() if line.strip()]
    python_bridge_calls_text = ""
    if python_bridge_calls_path.exists():
        python_bridge_calls_text = python_bridge_calls_path.read_text(encoding="utf-8-sig")
    python_bridge_calls = [
        json.loads(line)
        for line in python_bridge_calls_text.splitlines()
        if line.strip()
    ]
    log_path = project_dir / ".runtime" / "launcher" / "desktop-entry-vbs.log"
    events = [
        _loads_json_line_allowing_control_chars(line)
        for line in log_path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]
    return calls, events, python_bridge_calls


def _vbs_args_target_launcher(args: list[str]) -> bool:
    candidate = "launcher"
    index = 0
    while index < len(args):
        value = str(args[index]).strip()
        lowered = value.lower()
        if lowered in {"-action", "--action"} and index + 1 < len(args):
            candidate = str(args[index + 1]).strip().lower()
            break
        if lowered.startswith("-action:") or lowered.startswith("-action="):
            candidate = value[8:].strip().lower()
            break
        if lowered.startswith("--action:") or lowered.startswith("--action="):
            candidate = value[9:].strip().lower()
            break
        if not value.startswith("-") and candidate == "launcher":
            candidate = value.lower()
        index += 1
    return candidate == "launcher"


def test_desktop_entry_source_signature_changes_when_developer_mode_changes(monkeypatch, tmp_path):
    bridge = _load_desktop_entry_py()
    monkeypatch.setattr(bridge, "PROJECT_ROOT", tmp_path)

    for relative_path in bridge.SOURCE_SIGNATURE_PATHS:
        source_path = tmp_path / relative_path
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(f"initial {relative_path}\n", encoding="utf-8")

    before = bridge._source_signature()
    developer_mode_source = tmp_path / "core" / "launcher" / "developer_mode.py"
    developer_mode_source.write_text("changed developer mode source\n", encoding="utf-8")
    after = bridge._source_signature()

    assert before != after


def test_desktop_entry_source_signature_tracks_launcher_style_maps(monkeypatch, tmp_path):
    bridge = _load_desktop_entry_py()
    monkeypatch.setattr(bridge, "PROJECT_ROOT", tmp_path)

    assert "web/src/app/LauncherShell.styles.ts" in bridge.SOURCE_SIGNATURE_PATHS
    assert "web/src/routes/LauncherRoute.styles.ts" in bridge.SOURCE_SIGNATURE_PATHS
    assert not any(path.endswith(".module.css") for path in bridge.SOURCE_SIGNATURE_PATHS)

    for relative_path in bridge.SOURCE_SIGNATURE_PATHS:
        source_path = tmp_path / relative_path
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(f"initial {relative_path}\n", encoding="utf-8")

    before = bridge._source_signature()
    launcher_route_styles = tmp_path / "web" / "src" / "routes" / "LauncherRoute.styles.ts"
    launcher_route_styles.write_text("changed launcher route styles\n", encoding="utf-8")
    after = bridge._source_signature()

    assert before != after


def test_desktop_entry_python_bridge_starts_launcher_natively(monkeypatch, tmp_path):
    bridge = _load_desktop_entry_py()
    calls: list[tuple[str, object]] = []
    saved_states: list[dict[str, object]] = []

    @contextlib.contextmanager
    def fake_lock():
        yield True

    monkeypatch.setattr(bridge, "_append_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(bridge, "_single_launcher_open_lock", fake_lock)
    monkeypatch.setattr(bridge, "_read_state", lambda: {})
    monkeypatch.setattr(bridge, "_write_state", lambda state: saved_states.append(dict(state)))
    monkeypatch.setattr(bridge, "_source_signature", lambda: "source-sig")
    monkeypatch.setattr(bridge, "_launcher_control_port", lambda: 8765)
    monkeypatch.setattr(bridge, "_launcher_control_healthy", lambda port: False)
    monkeypatch.setattr(bridge, "_start_launcher_backend", lambda python_exe, port: calls.append(("backend", (python_exe, port))) or 111)
    monkeypatch.setattr(bridge, "_open_launcher_window", lambda url: calls.append(("browser", url)) or 222)
    monkeypatch.setattr(bridge, "_repair_existing_launcher_browser_window", lambda browser_pid: 0)
    monkeypatch.setattr(bridge, "_pid_alive", lambda pid: False)

    result = bridge.main(["--action", "launcher", "--python-exe", str(tmp_path / "python.exe")])

    assert result == 0
    assert calls == [
        ("backend", (str(tmp_path / "python.exe"), 8765)),
        ("browser", "http://127.0.0.1:8765/launcher"),
    ]
    assert saved_states[-1]["launcherBackendPid"] == 111
    assert saved_states[-1]["launcherBrowserWindowPid"] == 222
    assert saved_states[-1]["launcherControlSourceSignature"] == "source-sig"


def test_desktop_entry_python_bridge_reuses_current_launcher(monkeypatch):
    bridge = _load_desktop_entry_py()
    state = {
        "sessionRole": "launcher_control_surface",
        "launcherBackendPid": 111,
        "launcherBackendLaunchPid": 111,
        "launcherBrowserWindowPid": 222,
        "launcherControlSourceSignature": "source-sig",
    }
    calls: list[str] = []
    saved_states: list[dict[str, object]] = []

    @contextlib.contextmanager
    def fake_lock():
        yield True

    monkeypatch.setattr(bridge, "_append_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(bridge, "_single_launcher_open_lock", fake_lock)
    monkeypatch.setattr(bridge, "_read_state", lambda: dict(state))
    monkeypatch.setattr(bridge, "_write_state", lambda next_state: saved_states.append(dict(next_state)))
    monkeypatch.setattr(bridge, "_source_signature", lambda: "source-sig")
    monkeypatch.setattr(bridge, "_launcher_control_port", lambda: 8765)
    monkeypatch.setattr(bridge, "_launcher_control_healthy", lambda port: True)
    monkeypatch.setattr(bridge, "_start_launcher_backend", lambda python_exe, port: calls.append("backend") or 333)
    monkeypatch.setattr(bridge, "_open_launcher_window", lambda url: calls.append("browser") or 444)
    monkeypatch.setattr(bridge, "_pid_alive", lambda pid: pid in {111, 222})

    result = bridge.main(["--action", "launcher"])

    assert result == 0
    assert calls == []
    assert saved_states[-1]["launcherBackendPid"] == 111
    assert saved_states[-1]["launcherBrowserWindowPid"] == 222


def test_desktop_entry_python_bridge_repairs_stale_launcher_browser_pid(monkeypatch):
    bridge = _load_desktop_entry_py()
    state = {
        "sessionRole": "launcher_control_surface",
        "launcherBackendPid": 111,
        "launcherBackendLaunchPid": 111,
        "launcherBrowserWindowPid": 47264,
        "launcherControlSourceSignature": "source-sig",
    }
    calls: list[tuple[str, object]] = []
    saved_states: list[dict[str, object]] = []

    @contextlib.contextmanager
    def fake_lock():
        yield True

    monkeypatch.setattr(bridge, "_append_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(bridge, "_single_launcher_open_lock", fake_lock)
    monkeypatch.setattr(bridge, "_read_state", lambda: dict(state))
    monkeypatch.setattr(bridge, "_write_state", lambda next_state: saved_states.append(dict(next_state)))
    monkeypatch.setattr(bridge, "_source_signature", lambda: "source-sig")
    monkeypatch.setattr(bridge, "_launcher_control_port", lambda: 8765)
    monkeypatch.setattr(bridge, "_launcher_control_healthy", lambda port: True)
    monkeypatch.setattr(bridge, "_start_launcher_backend", lambda python_exe, port: calls.append(("backend", port)) or 333)
    monkeypatch.setattr(bridge, "_open_launcher_window", lambda url: (_ for _ in ()).throw(AssertionError("profile window should be reused")))
    monkeypatch.setattr(bridge, "_pid_alive", lambda pid: pid == 111)
    monkeypatch.setattr(
        bridge,
        "_managed_browser_window_candidates",
        lambda browser_pid, role: [{"hwnd": 90210, "resolvedBy": "launcher_control_profile", "processId": 4736}],
    )
    monkeypatch.setattr(
        bridge,
        "_apply_managed_browser_app_identity",
        lambda browser_pid, role: calls.append(("identity", (browser_pid, role))) or {"windowPid": 4736, "applied": True},
    )

    result = bridge.main(["--action", "launcher"])

    assert result == 0
    assert calls == [("identity", (4736, "launcher"))]
    assert saved_states[-1]["launcherBackendPid"] == 111
    assert saved_states[-1]["launcherBrowserWindowPid"] == 4736


def test_desktop_entry_bootstrap_json_reports_attached_or_started(monkeypatch, tmp_path, capsys):
    bridge = _load_desktop_entry_py()

    @contextlib.contextmanager
    def fake_lock():
        yield True

    saved_states: list[dict[str, object]] = []
    monkeypatch.setattr(bridge, "RUNTIME_DIR", tmp_path / ".runtime" / "launcher")
    monkeypatch.setattr(bridge, "_append_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(bridge, "_single_launcher_open_lock", fake_lock)
    monkeypatch.setattr(bridge, "_launcher_control_port", lambda: 8765)
    monkeypatch.setattr(bridge, "_source_signature", lambda: "sig-1")
    monkeypatch.setattr(bridge, "_launcher_control_healthy", lambda port: True)
    monkeypatch.setattr(bridge, "_launcher_backend_source_current", lambda state, pid, signature: True)
    monkeypatch.setattr(
        bridge,
        "_read_state",
        lambda: {
            "launcherBackendPid": 1234,
            "launcherControlSourceSignature": "sig-1",
            "launcherControlPort": 8765,
            "sessionId": "launcher-session-1",
            "workspaceId": "workspace-1",
            "url": "http://127.0.0.1:8000",
        },
    )
    monkeypatch.setattr(bridge, "_write_state", lambda state: saved_states.append(dict(state)))
    monkeypatch.setattr(bridge, "_start_launcher_backend", lambda python_exe, port: (_ for _ in ()).throw(AssertionError("current launcher should attach")))
    monkeypatch.setattr(bridge, "_open_launcher_window", lambda url: (_ for _ in ()).throw(AssertionError("bootstrap no-browser should not open a window")))

    result = bridge.main(
        [
            "--action",
            "bootstrap",
            "--output",
            "json",
            "--workspace",
            str(tmp_path),
            "--config",
            "C:/operator/config.toml",
            "--no-browser",
        ]
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schemaVersion"] == 1
    assert payload["mode"] == "attached"
    assert payload["workspaceRoot"] == str(tmp_path)
    assert payload["operatorConfigPath"] == "C:/operator/config.toml"
    assert payload["launcherBackendPid"] == 1234
    assert payload["launcherUrl"].startswith("http://127.0.0.1:")
    assert payload["ready"] is True
    assert payload["protocolVersion"] >= 1
    assert "desktop_actions.claim" in payload["capabilities"]
    assert "workbench_close.transaction.v1" in payload["capabilities"]


def test_desktop_entry_bootstrap_repairs_managed_listener_pid_lost_from_shared_state(monkeypatch, tmp_path, capsys):
    bridge = _load_desktop_entry_py()
    state = {
        "launcherBackendPid": 0,
        "launcherBackendLaunchPid": 0,
        "launcherAdapter": "python_headless",
        "runtimeProjectRoot": str(tmp_path),
        "sessionId": "launcher-session-1",
        "workspaceId": "workspace-1",
        "url": "http://127.0.0.1:8002",
    }
    saved_states: list[dict[str, object]] = []

    monkeypatch.setattr(bridge, "_append_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(bridge, "_read_state", lambda: dict(state))
    monkeypatch.setattr(bridge, "_write_state", lambda next_state: saved_states.append(dict(next_state)))
    monkeypatch.setattr(bridge, "_launcher_control_port", lambda: 8765)
    monkeypatch.setattr(bridge, "_launcher_control_healthy", lambda port: True)
    monkeypatch.setattr(bridge, "_pid_alive", lambda pid: False)
    monkeypatch.setattr(bridge, "_managed_launcher_listener_pid", lambda port, workspace_root: 35496)

    result = bridge.main(
        [
            "--action",
            "bootstrap",
            "--output",
            "json",
            "--workspace",
            str(tmp_path),
            "--config",
            "C:/operator/config.toml",
            "--no-browser",
            "--attach-healthy-launcher",
        ]
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "attached"
    assert payload["launcherBackendPid"] == 35496
    assert saved_states[-1]["launcherBackendPid"] == 35496
    assert saved_states[-1]["launcherBackendLaunchPid"] == 35496
    assert saved_states[-1]["launcherControlPort"] == 8765
    assert saved_states[-1]["launcherControlUrl"] == "http://127.0.0.1:8765/launcher"


def test_managed_launcher_process_snapshot_fails_closed_for_unrelated_listener(tmp_path):
    bridge = _load_desktop_entry_py()

    assert bridge._managed_launcher_process_snapshot_matches(
        {
            "name": "pythonw.exe",
            "cwd": str(tmp_path),
            "cmdline": [
                str(tmp_path / ".venv" / "Scripts" / "pythonw.exe"),
                "-c",
                "import uvicorn; uvicorn.run('core.launcher.app:app', host='127.0.0.1', port=8765)",
                "--managed-launcher-control",
                "--port",
                "8765",
            ],
        },
        port=8765,
        workspace_root=tmp_path,
    )
    assert not bridge._managed_launcher_process_snapshot_matches(
        {
            "name": "pythonw.exe",
            "cwd": str(tmp_path),
            "cmdline": ["pythonw.exe", "-m", "http.server", "8765"],
        },
        port=8765,
        workspace_root=tmp_path,
    )


def test_desktop_entry_stop_owned_launcher_terminates_matching_state_pids(monkeypatch, capsys):
    bridge = _load_desktop_entry_py()
    state = {
        "sessionRole": "launcher_control_surface",
        "launcherBackendPid": 111,
        "launcherBackendLaunchPid": 111,
        "launcherBrowserWindowPid": 222,
        "launcherBrowserLaunchPid": 222,
        "launcherControlPort": 8765,
        "launcherControlSourceSignature": "source-sig",
        "browserManaged": True,
    }
    terminated: list[int] = []
    saved_states: list[dict[str, object]] = []

    monkeypatch.setattr(bridge, "_append_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(bridge, "_read_state", lambda: dict(state))
    monkeypatch.setattr(bridge, "_write_state", lambda next_state: saved_states.append(dict(next_state)))
    monkeypatch.setattr(bridge, "_terminate_pid", lambda pid: terminated.append(pid))
    monkeypatch.setattr(bridge, "_wait_for_launcher_control_stopped", lambda port: True)

    result = bridge.main(["--action", "stop-launcher", "--output", "json", "--owned-backend-pid", "111"])

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "stopped"
    assert payload["terminatedPids"] == [111, 222]
    assert terminated == [111, 222]
    assert saved_states[-1]["launcherBackendPid"] == 0
    assert saved_states[-1]["launcherBackendLaunchPid"] == 0
    assert saved_states[-1]["launcherBrowserWindowPid"] == 0
    assert saved_states[-1]["launcherBrowserLaunchPid"] == 0
    assert saved_states[-1]["browserManaged"] is False


def test_desktop_entry_stop_owned_launcher_refuses_mismatched_backend_pid(monkeypatch, capsys):
    bridge = _load_desktop_entry_py()
    state = {
        "sessionRole": "launcher_control_surface",
        "launcherBackendPid": 111,
        "launcherBackendLaunchPid": 111,
        "launcherBrowserWindowPid": 222,
        "launcherBrowserLaunchPid": 222,
        "launcherControlPort": 8765,
    }
    terminated: list[int] = []
    saved_states: list[dict[str, object]] = []

    monkeypatch.setattr(bridge, "_append_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(bridge, "_read_state", lambda: dict(state))
    monkeypatch.setattr(bridge, "_write_state", lambda next_state: saved_states.append(dict(next_state)))
    monkeypatch.setattr(bridge, "_terminate_pid", lambda pid: terminated.append(pid))

    result = bridge.main(["--action", "stop-launcher", "--output", "json", "--owned-backend-pid", "999"])

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "skipped"
    assert payload["reason"] == "owned_backend_pid_mismatch"
    assert terminated == []
    assert saved_states == []


def test_desktop_entry_stop_owned_launcher_requires_owned_backend_pid(monkeypatch, capsys):
    bridge = _load_desktop_entry_py()
    state = {
        "sessionRole": "launcher_control_surface",
        "launcherBackendPid": 111,
        "launcherBackendLaunchPid": 111,
        "launcherBrowserWindowPid": 222,
        "launcherBrowserLaunchPid": 222,
        "launcherControlPort": 8765,
    }
    terminated: list[int] = []
    saved_states: list[dict[str, object]] = []

    monkeypatch.setattr(bridge, "_append_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(bridge, "_read_state", lambda: dict(state))
    monkeypatch.setattr(bridge, "_write_state", lambda next_state: saved_states.append(dict(next_state)))
    monkeypatch.setattr(bridge, "_terminate_pid", lambda pid: terminated.append(pid))

    result = bridge.main(["--action", "stop-launcher", "--output", "json"])

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "skipped"
    assert payload["reason"] == "owned_backend_pid_required"
    assert terminated == []
    assert saved_states == []


def test_desktop_entry_python_bridge_replaces_orphaned_launcher_window(monkeypatch):
    bridge = _load_desktop_entry_py()
    state = {
        "sessionRole": "launcher_control_surface",
        "launcherBackendPid": 111,
        "launcherBackendLaunchPid": 111,
        "launcherBrowserWindowPid": 222,
        "launcherControlSourceSignature": "source-sig",
    }
    calls: list[tuple[str, object]] = []
    terminated: list[int] = []
    saved_states: list[dict[str, object]] = []

    @contextlib.contextmanager
    def fake_lock():
        yield True

    monkeypatch.setattr(bridge, "_append_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(bridge, "_single_launcher_open_lock", fake_lock)
    monkeypatch.setattr(bridge, "_read_state", lambda: dict(state))
    monkeypatch.setattr(bridge, "_write_state", lambda next_state: saved_states.append(dict(next_state)))
    monkeypatch.setattr(bridge, "_source_signature", lambda: "source-sig")
    monkeypatch.setattr(bridge, "_launcher_control_port", lambda: 8765)
    monkeypatch.setattr(bridge, "_launcher_control_healthy", lambda port: False)
    monkeypatch.setattr(bridge, "_terminate_pid", lambda pid: terminated.append(pid))
    monkeypatch.setattr(bridge, "_start_launcher_backend", lambda python_exe, port: calls.append(("backend", port)) or 333)
    monkeypatch.setattr(bridge, "_open_launcher_window", lambda url: calls.append(("browser", url)) or 444)
    monkeypatch.setattr(bridge, "_repair_existing_launcher_browser_window", lambda browser_pid: 0)
    monkeypatch.setattr(bridge, "_pid_alive", lambda pid: pid == 222)

    result = bridge.main(["--action", "launcher"])

    assert result == 0
    assert terminated == [222]
    assert calls == [
        ("backend", 8765),
        ("browser", "http://127.0.0.1:8765/launcher"),
    ]
    assert saved_states[-1]["launcherBackendPid"] == 333
    assert saved_states[-1]["launcherBrowserWindowPid"] == 444


def test_desktop_entry_python_bridge_does_not_start_when_port_is_already_healthy_without_state(monkeypatch):
    bridge = _load_desktop_entry_py()
    calls: list[str] = []
    saved_states: list[dict[str, object]] = []

    @contextlib.contextmanager
    def fake_lock():
        yield True

    monkeypatch.setattr(bridge, "_append_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(bridge, "_single_launcher_open_lock", fake_lock)
    monkeypatch.setattr(bridge, "_read_state", lambda: {})
    monkeypatch.setattr(bridge, "_write_state", lambda next_state: saved_states.append(dict(next_state)))
    monkeypatch.setattr(bridge, "_source_signature", lambda: "source-sig")
    monkeypatch.setattr(bridge, "_launcher_control_port", lambda: 8765)
    monkeypatch.setattr(bridge, "_launcher_control_healthy", lambda port: True)
    monkeypatch.setattr(bridge, "_start_launcher_backend", lambda python_exe, port: calls.append("backend") or 333)
    monkeypatch.setattr(bridge, "_open_launcher_window", lambda url: calls.append("browser") or 444)
    monkeypatch.setattr(bridge, "_repair_existing_launcher_browser_window", lambda browser_pid: 0)
    monkeypatch.setattr(bridge, "_pid_alive", lambda pid: False)

    result = bridge.main(["--action", "launcher"])

    assert result == 0
    assert calls == ["browser"]
    assert saved_states[-1]["launcherBackendPid"] == 0
    assert saved_states[-1]["launcherBrowserWindowPid"] == 444


def test_desktop_entry_python_bridge_replaces_stale_launcher(monkeypatch):
    bridge = _load_desktop_entry_py()
    state = {
        "sessionRole": "launcher_control_surface",
        "launcherBackendPid": 111,
        "launcherBackendLaunchPid": 112,
        "launcherBrowserWindowPid": 222,
        "launcherControlSourceSignature": "old-source-sig",
    }
    terminated: list[int] = []

    @contextlib.contextmanager
    def fake_lock():
        yield True

    monkeypatch.setattr(bridge, "_append_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(bridge, "_single_launcher_open_lock", fake_lock)
    monkeypatch.setattr(bridge, "_read_state", lambda: dict(state))
    monkeypatch.setattr(bridge, "_write_state", lambda next_state: None)
    monkeypatch.setattr(bridge, "_source_signature", lambda: "new-source-sig")
    monkeypatch.setattr(bridge, "_launcher_control_port", lambda: 8765)
    health_results = iter([True, False, False])
    monkeypatch.setattr(bridge, "_launcher_control_healthy", lambda port: next(health_results))
    monkeypatch.setattr(bridge, "_wait_for_launcher_control_stopped", lambda port: True)
    monkeypatch.setattr(bridge, "_terminate_pid", lambda pid: terminated.append(pid))
    monkeypatch.setattr(bridge, "_start_launcher_backend", lambda python_exe, port: 333)
    monkeypatch.setattr(bridge, "_open_launcher_window", lambda url: 444)
    monkeypatch.setattr(bridge, "_pid_alive", lambda pid: False)

    result = bridge.main(["--action", "launcher"])

    assert result == 0
    assert terminated == [111, 112, 222]


def test_desktop_entry_python_bridge_terminates_windows_pid_without_taskkill(monkeypatch):
    bridge = _load_desktop_entry_py()
    subprocess_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    class FakeKernel32:
        def __init__(self) -> None:
            self.calls: list[tuple[str, int]] = []

        def OpenProcess(self, access: int, inherit: bool, pid: int) -> int:
            self.calls.append(("OpenProcess", access, pid))
            return 99

        def TerminateProcess(self, handle: int, exit_code: int) -> int:
            self.calls.append(("TerminateProcess", handle, exit_code))
            return 1

        def CloseHandle(self, handle: int) -> int:
            self.calls.append(("CloseHandle", handle))
            return 1

    kernel32 = FakeKernel32()

    monkeypatch.setattr(bridge.os, "name", "nt", raising=False)
    monkeypatch.setattr(bridge, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(bridge, "_terminate_pid_tree_with_psutil", lambda pid: False, raising=False)
    monkeypatch.setattr(bridge.shutil, "which", lambda name: r"C:\Windows\System32\taskkill.exe" if name == "taskkill" else "")
    monkeypatch.setattr(bridge.subprocess, "run", lambda *args, **kwargs: subprocess_calls.append((args, kwargs)))
    monkeypatch.setattr(bridge.ctypes, "windll", type("FakeWindll", (), {"kernel32": kernel32})(), raising=False)

    bridge._terminate_pid(4321)

    assert subprocess_calls == []
    assert ("OpenProcess", 0x0001, 4321) in kernel32.calls
    assert ("TerminateProcess", 99, 1) in kernel32.calls
    assert ("CloseHandle", 99) in kernel32.calls


def _run_launcher_ast_harness(tmp_path: Path, harness_source: str) -> subprocess.CompletedProcess[str]:
    harness_path = tmp_path / "launcher-ast-harness.ps1"
    harness_path.write_text(_normalize_ast_harness_source(harness_source), encoding="utf-8-sig")
    command = [
        _powershell_exe(),
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(harness_path),
        "-LauncherPath",
        str(LAUNCHER_SCRIPT),
    ]
    return subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)


def _run_desktop_entry_ast_harness(tmp_path: Path, harness_source: str) -> subprocess.CompletedProcess[str]:
    harness_path = tmp_path / "desktop-entry-ast-harness.ps1"
    harness_path.write_text(_normalize_ast_harness_source(harness_source), encoding="utf-8-sig")
    command = [
        _powershell_exe(),
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(harness_path),
        "-DesktopEntryPath",
        str(DESKTOP_ENTRY_SCRIPT),
    ]
    return subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)


def _normalize_ast_harness_source(harness_source: str) -> str:
    source = harness_source.strip()
    # Windows PowerShell 5.1 defaults Get-Content to the local ANSI code page.
    # The launcher scripts contain UTF-8 display labels, so AST harnesses must
    # read them explicitly as UTF-8 before feeding them to Parser.ParseInput.
    normalized = (
        source.replace(
            "Get-Content -Raw -LiteralPath $LauncherPath",
            "Get-Content -Raw -Encoding UTF8 -LiteralPath $LauncherPath",
        )
        .replace(
            "Get-Content -Raw -LiteralPath $DesktopEntryPath",
            "Get-Content -Raw -Encoding UTF8 -LiteralPath $DesktopEntryPath",
        )
    )
    if "$LauncherPath" in normalized and "function Get-ObjectPropertyValue" not in normalized:
        helper = """
function Get-ObjectPropertyValue {
    param([object]$Object, [string]$Name, $Default = $null)
    if ($null -eq $Object) { return $Default }
    $prop = $Object.PSObject.Properties[$Name]
    if ($null -eq $prop) { return $Default }
    if ($null -eq $prop.Value) { return $Default }
    return $prop.Value
}
"""
        normalized = normalized.replace("Set-StrictMode -Version Latest", f"Set-StrictMode -Version Latest\n{helper}", 1)
    return normalized


def test_launcher_internal_action_rejection_logs_env_diagnostics(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -Encoding UTF8 -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

$testFunctionAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Test-RuntimeManagerInternalLauncherCall"
}, $true)
if ($null -eq $testFunctionAst) {
    throw "Test-RuntimeManagerInternalLauncherCall was not found."
}
$assertFunctionAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Assert-RuntimeManagerInternalLauncherCall"
}, $true)
if ($null -eq $assertFunctionAst) {
    throw "Assert-RuntimeManagerInternalLauncherCall was not found."
}
. ([scriptblock]::Create($testFunctionAst.Extent.Text))
. ([scriptblock]::Create($assertFunctionAst.Extent.Text))

$script:events = @()
$script:runtimeManagerInternalLauncherEnv = "VIBELUTION_RUNTIME_MANAGER_INTERNAL_LAUNCHER"
$script:protectedProcessIds = @()
function Test-LauncherProtectedProcessLooksLikeRuntimeManager {
    param([int]$ProcessId)
    return $false
}
function Write-LauncherControlLog {
    param([string]$Event, [string]$Message, [string]$Level = "info", [hashtable]$Fields = @{})
    $script:events += ,@{ event = $Event; level = $Level; message = $Message; fields = $Fields }
}

[Environment]::SetEnvironmentVariable($script:runtimeManagerInternalLauncherEnv, $null, "Process")
$message = ""
try {
    Assert-RuntimeManagerInternalLauncherCall -RequestedAction "internal-stop"
} catch {
    $message = $_.Exception.Message
}

if ($message -notmatch "internal-stop") {
    throw "Internal action rejection did not name the requested action: $message"
}
if (@($script:events).Count -ne 1) {
    throw "Internal action rejection did not write exactly one control log event."
}
$event = $script:events[0]
if ($event.event -ne "launcher.internal_action.rejected") {
    throw "Unexpected rejection event: $($event.event)"
}
if ($event.fields.required_env -ne $script:runtimeManagerInternalLauncherEnv) {
    throw "Required env name was not logged."
}
if ($event.fields.actual_env_present) {
    throw "Missing internal env was logged as present."
}
if ($event.fields.actual_env_length -ne 0) {
    throw "Missing internal env length was not logged as zero."
}
if ($event.fields.actual_env_value_is_one) {
    throw "Missing internal env was logged as authorized."
}

[Environment]::SetEnvironmentVariable($script:runtimeManagerInternalLauncherEnv, "1", "Process")
Assert-RuntimeManagerInternalLauncherCall -RequestedAction "internal-stop"
[Environment]::SetEnvironmentVariable($script:runtimeManagerInternalLauncherEnv, $null, "Process")
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_internal_action_allows_legacy_runtime_manager_protected_process(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

$testFunctionAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Test-RuntimeManagerInternalLauncherCall"
}, $true)
$assertFunctionAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Assert-RuntimeManagerInternalLauncherCall"
}, $true)
if ($null -eq $testFunctionAst -or $null -eq $assertFunctionAst) {
    throw "Internal launcher authorization functions were not found."
}
. ([scriptblock]::Create($testFunctionAst.Extent.Text))
. ([scriptblock]::Create($assertFunctionAst.Extent.Text))

$script:runtimeManagerInternalLauncherEnv = "VIBELUTION_RUNTIME_MANAGER_INTERNAL_LAUNCHER"
$script:protectedProcessIds = @(24680)
$script:events = @()
function Test-LauncherProtectedProcessLooksLikeRuntimeManager {
    param([int]$ProcessId)
    return $ProcessId -eq 24680
}
function Write-LauncherControlLog {
    param([string]$Event, [string]$Message, [string]$Level = "info", [hashtable]$Fields = @{})
    $script:events += ,@{ event = $Event; level = $Level; message = $Message; fields = $Fields }
}

[Environment]::SetEnvironmentVariable($script:runtimeManagerInternalLauncherEnv, $null, "Process")
if (-not (Test-RuntimeManagerInternalLauncherCall)) {
    throw "Legacy runtime manager protected process evidence was not accepted."
}
Assert-RuntimeManagerInternalLauncherCall -RequestedAction "internal-restart"
if (@($script:events).Count -ne 0) {
    throw "Authorized legacy runtime manager internal action wrote a rejection event."
}
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_backend_port_accepts_agent_env_alias(tmp_path):
    resolved = _resolve_launcher_backend_port(
        tmp_path,
        config_text="[workbench]\nbackend_port = 9101\n",
        env_overrides={"AGENT_WORKBENCH_BACKEND_PORT": "9401"},
    )

    assert resolved == 9401


def test_launcher_backend_port_prefers_vibelution_env_over_agent_alias(tmp_path):
    resolved = _resolve_launcher_backend_port(
        tmp_path,
        config_text="[workbench]\nbackend_port = 9101\n",
        env_overrides={
            "VIBELUTION_PORT": "9301",
            "AGENT_WORKBENCH_BACKEND_PORT": "9401",
        },
    )

    assert resolved == 9301


def test_launcher_backend_port_ignores_invalid_config_token(tmp_path):
    resolved = _resolve_launcher_backend_port(
        tmp_path,
        config_text="[workbench]\nbackend_port = 9101oops\n",
    )

    assert resolved == 8000


def test_launcher_control_port_is_independent_from_workbench_port(tmp_path):
    resolved = _resolve_launcher_control_port(
        tmp_path,
        config_text="[workbench]\nbackend_port = 8000\n[launcher]\ncontrol_port = 8765\n",
        workbench_port=8000,
    )

    assert resolved == 8765


def test_launcher_control_port_avoids_workbench_port_collision(tmp_path):
    resolved = _resolve_launcher_control_port(
        tmp_path,
        config_text="[workbench]\nbackend_port = 8765\n[launcher]\ncontrol_port = 8765\n",
        workbench_port=8765,
    )

    assert resolved != 8765


def test_launcher_control_port_prefers_env_override(tmp_path):
    resolved = _resolve_launcher_control_port(
        tmp_path,
        config_text="[launcher]\ncontrol_port = 8765\n",
        env_overrides={"VIBELUTION_LAUNCHER_PORT": "8899"},
        workbench_port=8000,
    )

    assert resolved == 8899


def test_launcher_window_mode_defaults_to_fullscreen(tmp_path):
    resolved = _resolve_launcher_window_mode(tmp_path, config_text="[workbench]\n")

    assert resolved == "fullscreen"


def test_launcher_window_mode_reads_config_and_env_override(tmp_path):
    resolved = _resolve_launcher_window_mode(
        tmp_path,
        config_text="[workbench]\nwindow_mode = \"fullscreen\"\n",
    )
    overridden = _resolve_launcher_window_mode(
        tmp_path,
        config_text="[workbench]\nwindow_mode = \"fullscreen\"\n",
        env_overrides={"VIBELUTION_WORKBENCH_WINDOW_MODE": "windowed"},
    )
    agent_alias = _resolve_launcher_window_mode(
        tmp_path,
        config_text="[workbench]\nwindow_mode = \"windowed\"\n",
        env_overrides={"AGENT_WORKBENCH_WINDOW_MODE": "fullscreen"},
    )

    assert resolved == "fullscreen"
    assert overridden == "windowed"
    assert agent_alias == "fullscreen"


def test_launcher_window_mode_ignores_invalid_values(tmp_path):
    resolved = _resolve_launcher_window_mode(
        tmp_path,
        config_text="[workbench]\nwindow_mode = \"borderless\"\n",
        env_overrides={"VIBELUTION_WORKBENCH_WINDOW_MODE": "floating"},
    )

    assert resolved == "fullscreen"


def test_launcher_window_size_defaults_to_auto(tmp_path):
    resolved = _resolve_launcher_window_size(tmp_path, config_text="[workbench]\n")

    assert resolved == "auto|"


def test_launcher_window_size_reads_config_and_env_override(tmp_path):
    resolved = _resolve_launcher_window_size(
        tmp_path,
        config_text="[workbench]\nwindow_size = \"1600x900\"\n",
    )
    overridden = _resolve_launcher_window_size(
        tmp_path,
        config_text="[workbench]\nwindow_size = \"1600x900\"\n",
        env_overrides={"VIBELUTION_WORKBENCH_WINDOW_SIZE": "1280x800"},
    )
    agent_alias = _resolve_launcher_window_size(
        tmp_path,
        config_text="[workbench]\nwindow_size = \"auto\"\n",
        env_overrides={"AGENT_WORKBENCH_WINDOW_SIZE": "1920x1080"},
    )

    assert resolved == "1600x900|1600,900"
    assert overridden == "1280x800|1280,800"
    assert agent_alias == "1920x1080|1920,1080"


def test_launcher_window_size_ignores_invalid_values(tmp_path):
    resolved = _resolve_launcher_window_size(
        tmp_path,
        config_text="[workbench]\nwindow_size = \"100x100\"\n",
        env_overrides={"VIBELUTION_WORKBENCH_WINDOW_SIZE": "giant"},
    )

    assert resolved == "auto|"


def test_launcher_state_save_uses_retrying_atomic_writer(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

$saveStateAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Save-State"
}, $true)
if ($null -eq $saveStateAst) {
    throw "Save-State was not found."
}

$writeStateAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Write-LauncherStateFile"
}, $true)
if ($null -eq $writeStateAst) {
    throw "Write-LauncherStateFile was not found."
}

$saveStateText = $saveStateAst.Extent.Text
$writeStateText = $writeStateAst.Extent.Text
if ($saveStateText -notmatch "Write-LauncherStateFile") {
    throw "Save-State does not use Write-LauncherStateFile."
}
if ($saveStateText -match "Set-Content") {
    throw "Save-State still writes state with Set-Content."
}
if ($writeStateText -notmatch "Move-Item") {
    throw "Write-LauncherStateFile does not atomically move a temp file into place."
}
if ($writeStateText -notmatch "Start-Sleep") {
    throw "Write-LauncherStateFile does not retry after a failed write."
}
if ($writeStateText -notmatch "launcher.state.write.failed") {
    throw "Write-LauncherStateFile does not log final write failure."
}
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_state_writer_outputs_utf8_json_without_bom(tmp_path):
    state_path = tmp_path / "state.json"
    result = _run_launcher_ast_harness(
        tmp_path,
        f"""
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {{
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}}

$functionAst = $ast.Find({{
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Write-LauncherStateFile"
}}, $true)
if ($null -eq $functionAst) {{
    throw "Write-LauncherStateFile was not found."
}}

. ([scriptblock]::Create($functionAst.Extent.Text))
$script:launcherStateWriteMaxAttempts = 2
$script:launcherStateWriteRetryDelayMilliseconds = 1
function Write-LauncherControlLog {{
    param([string]$Event, [string]$Message, [string]$Level = "info", [hashtable]$Fields = @{{}})
}}

Write-LauncherStateFile -Path {json.dumps(str(state_path))} -Value '{{"status":"ok","text":"中文"}}'
$bytes = [System.IO.File]::ReadAllBytes({json.dumps(str(state_path))})
if ($bytes.Length -ge 3 -and $bytes[0] -eq 239 -and $bytes[1] -eq 187 -and $bytes[2] -eq 191) {{
    throw "state file has UTF-8 BOM."
}}
$payload = Get-Content -LiteralPath {json.dumps(str(state_path))} -Raw -Encoding UTF8 | ConvertFrom-Json
if ($payload.status -ne "ok" -or $payload.text -ne "中文") {{
    throw "state JSON did not round-trip."
}}
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_get_listening_pid_prefers_fast_netstat_exact_port(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

$functionAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Get-ListeningPid"
}, $true)
if ($null -eq $functionAst) {
    throw "Get-ListeningPid was not found."
}
. ([scriptblock]::Create($functionAst.Extent.Text))

$script:fallbackCalled = $false
function netstat {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    return @(
        "  TCP    127.0.0.1:18000      0.0.0.0:0              LISTENING       9999",
        "  TCP    127.0.0.1:8000       0.0.0.0:0              LISTENING       4321",
        "  TCP    [::]:8000            [::]:0                 LISTENING       5432"
    )
}
function Get-NetTCPConnection {
    $script:fallbackCalled = $true
    throw "Get-NetTCPConnection should not be used when netstat has an exact match."
}

$listenerPid = Get-ListeningPid -Port 8000
if ($listenerPid -ne 4321) {
    throw "Expected PID 4321 from the first exact netstat match, got $listenerPid."
}
if ($script:fallbackCalled) {
    throw "Expected netstat fast path to avoid Get-NetTCPConnection."
}

Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_get_listening_pid_falls_back_to_get_nettcpconnection(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

$functionAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Get-ListeningPid"
}, $true)
if ($null -eq $functionAst) {
    throw "Get-ListeningPid was not found."
}
. ([scriptblock]::Create($functionAst.Extent.Text))

function netstat {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    throw "netstat unavailable"
}
function Get-NetTCPConnection {
    param([int]$LocalPort, [string]$State, [string]$ErrorAction)
    if ($LocalPort -ne 8000 -or $State -ne "Listen") {
        throw "Unexpected fallback query: LocalPort=$LocalPort State=$State"
    }
    return [pscustomobject]@{ OwningProcess = 9876 }
}

$listenerPid = Get-ListeningPid -Port 8000
if ($listenerPid -ne 9876) {
    throw "Expected fallback PID 9876, got $listenerPid."
}

Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_get_listening_pid_returns_null_from_netstat_without_slow_fallback(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

$functionAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Get-ListeningPid"
}, $true)
if ($null -eq $functionAst) {
    throw "Get-ListeningPid was not found."
}
. ([scriptblock]::Create($functionAst.Extent.Text))

$script:fallbackCalled = $false
function netstat {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    return @(
        "  TCP    127.0.0.1:18000      0.0.0.0:0              LISTENING       9999",
        "  TCP    127.0.0.1:8000       127.0.0.1:54000        ESTABLISHED     2222"
    )
}
function Get-NetTCPConnection {
    $script:fallbackCalled = $true
    throw "Get-NetTCPConnection should not be used when netstat succeeds without a listener."
}

$listenerPid = Get-ListeningPid -Port 8000
if ($null -ne $listenerPid) {
    throw "Expected no listener PID, got $listenerPid."
}
if ($script:fallbackCalled) {
    throw "Expected successful netstat no-match to avoid Get-NetTCPConnection."
}

Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_native_commands_are_hidden_and_python_checks_use_helper(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

$nativeCommandAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Invoke-NativeCommand"
}, $true)
if ($null -eq $nativeCommandAst) {
    throw "Invoke-NativeCommand was not found."
}
$hiddenProcessAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Invoke-HiddenProcessCapture"
}, $true)
if ($null -eq $hiddenProcessAst) {
    throw "Invoke-HiddenProcessCapture was not found."
}
$hiddenProcessText = $hiddenProcessAst.Extent.Text
if ($hiddenProcessText -notmatch "RunHiddenRedirected") {
    throw "Invoke-HiddenProcessCapture does not use the Win32 no-window waitable helper."
}
if ($hiddenProcessText -match "System.Diagnostics.Process" -or $hiddenProcessText -match "ProcessStartInfo") {
    throw "Invoke-HiddenProcessCapture still uses the .NET process starter."
}
if ($hiddenProcessText -notmatch "ReadAllText") {
    throw "Invoke-HiddenProcessCapture does not read redirected native output."
}
foreach ($required in @("CREATE_NO_WINDOW", "STARTF_USESTDHANDLES", "WaitForSingleObject", "GetExitCodeProcess")) {
    if ($source -notmatch $required) {
        throw "Launcher hidden process API is missing $required."
    }
}
# MSDN: CREATE_NO_WINDOW is ignored when combined with DETACHED_PROCESS.
if ($source -match "DETACHED_PROCESS\\s*\\|\\s*CREATE_NEW_PROCESS_GROUP\\s*\\|\\s*CREATE_NO_WINDOW") {
    throw "Hidden process CreateProcess still combines DETACHED_PROCESS with CREATE_NO_WINDOW."
}
if ($source -notmatch "CREATE_NEW_PROCESS_GROUP\\s*\\|\\s*CREATE_NO_WINDOW") {
    throw "Hidden process CreateProcess does not use CREATE_NO_WINDOW without DETACHED_PROCESS."
}
$nativeCommandText = $nativeCommandAst.Extent.Text
if ($nativeCommandText -notmatch "Invoke-HiddenProcessCapture") {
    throw "Invoke-NativeCommand does not use the no-window process helper."
}

$testPythonAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Test-PythonRuntime"
}, $true)
if ($null -eq $testPythonAst) {
    throw "Test-PythonRuntime was not found."
}
$testPythonText = $testPythonAst.Extent.Text
if ($testPythonText -match '&\\s+\\$CommandPath') {
    throw "Test-PythonRuntime still invokes python directly."
}
if ($testPythonText -notmatch "Invoke-NativeCommand" -or $testPythonText -notmatch "SuppressOutput") {
    throw "Test-PythonRuntime does not use the hidden native helper."
}

$depsAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Ensure-ProjectPythonDependencies"
}, $true)
if ($null -eq $depsAst) {
    throw "Ensure-ProjectPythonDependencies was not found."
}
$depsText = $depsAst.Extent.Text
if ($depsText -match '&\\s+\\$installTarget\\.FilePath') {
    throw "Python dependency install still invokes pip directly."
}
if ($depsText -notmatch "Invoke-NativeCommand") {
    throw "Python dependency install does not use the hidden native helper."
}
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_frontend_commands_avoid_cmd_wrappers(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

function Get-FunctionText {
    param([string]$Name)
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $Name
    }, $true)
    if ($null -eq $functionAst) {
        throw "$Name was not found."
    }
    return $functionAst.Extent.Text
}

$nodeText = Get-FunctionText -Name "Resolve-NodeCommand"
$npmCliText = Get-FunctionText -Name "Resolve-NpmCliScript"
$npmInvocationText = Get-FunctionText -Name "Resolve-NpmCliInvocation"
$frontendScriptText = Get-FunctionText -Name "Resolve-FrontendPackageScript"
$toolchainText = Get-FunctionText -Name "Get-FrontendToolchainMissingPaths"
$dependenciesText = Get-FunctionText -Name "Ensure-FrontendDependencies"
$buildText = Get-FunctionText -Name "Ensure-WebBuild"

if ($nodeText -notmatch "node.exe") {
    throw "Resolve-NodeCommand does not prefer node.exe."
}
if ($npmCliText -notmatch "npm-cli.js") {
    throw "Resolve-NpmCliScript does not locate npm-cli.js."
}
if ($npmInvocationText -notmatch "Resolve-NodeCommand" -or $npmInvocationText -notmatch "Resolve-NpmCliScript") {
    throw "Resolve-NpmCliInvocation does not pair node.exe with npm-cli.js."
}
if ($frontendScriptText -notmatch "ConvertTo-WebRelativePath") {
    throw "Resolve-FrontendPackageScript does not produce actionable missing-script errors."
}
if ($toolchainText -match "\\.cmd") {
    throw "Frontend toolchain detection still requires cmd shims."
}
if ($dependenciesText -notmatch "Resolve-NpmCliInvocation") {
    throw "Frontend dependency install does not use the node/npm-cli invocation."
}
if ($dependenciesText -match "Resolve-NpmCommand" -or $dependenciesText -match '\\$npmCommand') {
    throw "Frontend dependency install still targets npm.cmd directly."
}
if ($buildText -notmatch "Resolve-NodeCommand" -or $buildText -notmatch "Resolve-FrontendPackageScript") {
    throw "Frontend build does not resolve direct node package scripts."
}
if ($buildText -match "Resolve-NpmCommand" -or $buildText -match '\\$npmCommand' -or $buildText -match '"run",\\s*"build"') {
    throw "Frontend build still uses npm run build."
}
if ($buildText -notmatch "node_modules\\\\typescript\\\\bin\\\\tsc" -or $buildText -notmatch "node_modules\\\\vite\\\\bin\\\\vite.js") {
    throw "Frontend build does not call the real TypeScript and Vite package entries."
}
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_background_processes_are_started_without_windows(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

$hiddenBackgroundAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Start-HiddenBackgroundProcess"
}, $true)
if ($null -eq $hiddenBackgroundAst) {
    throw "Start-HiddenBackgroundProcess was not found."
}
$hiddenBackgroundText = $hiddenBackgroundAst.Extent.Text
if ($hiddenBackgroundText -notmatch 'CreateNoWindow\\s*=\\s*\\$true') {
    throw "Start-HiddenBackgroundProcess does not force CreateNoWindow."
}
if ($hiddenBackgroundText -notmatch 'UseShellExecute\\s*=\\s*\\$false') {
    throw "Start-HiddenBackgroundProcess does not avoid shell execution."
}
if ($hiddenBackgroundText -notmatch 'ProcessWindowStyle\\]::Hidden') {
    throw "Start-HiddenBackgroundProcess does not set hidden window style."
}

$guiProcessAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Start-GuiProcessWithoutConsole"
}, $true)
if ($null -eq $guiProcessAst) {
    throw "Start-GuiProcessWithoutConsole was not found."
}
$guiProcessText = $guiProcessAst.Extent.Text
if ($guiProcessText -match "Start-Process") {
    throw "GUI process helper still uses Start-Process."
}
if ($guiProcessText -notmatch 'CreateNoWindow\\s*=\\s*\\$true') {
    throw "GUI process helper does not force CreateNoWindow."
}
if ($guiProcessText -notmatch 'UseShellExecute\\s*=\\s*\\$false') {
    throw "GUI process helper does not avoid shell execution."
}
if ($guiProcessText -notmatch 'ProcessWindowStyle\\]::Normal') {
    throw "GUI process helper should keep GUI windows visible while suppressing console windows."
}

$redirectedAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Start-RedirectedBackgroundProcess"
}, $true)
if ($null -eq $redirectedAst) {
    throw "Start-RedirectedBackgroundProcess was not found."
}
$redirectedText = $redirectedAst.Extent.Text
if ($redirectedText -match "cmd.exe" -or $redirectedText -match "ComSpec" -or $redirectedText -match "/c") {
    throw "Redirected background process still shells out through cmd."
}
if ($redirectedText -match "Start-Process") {
    throw "Redirected background process still uses Start-Process."
}
if ($redirectedText -notmatch 'StartHiddenRedirected') {
    throw "Redirected background process does not use the Win32 no-window redirected starter."
}
if ($redirectedText -notmatch 'ConvertTo-ProcessArgumentString') {
    throw "Redirected background process does not construct an explicit command line."
}
if ($source -notmatch 'CREATE_NO_WINDOW' -or $source -notmatch 'STARTF_USESTDHANDLES') {
    throw "Redirected background process does not force no-window inherited file handles."
}
if ($redirectedText -notmatch 'distinct stdout and stderr log paths') {
    throw "Redirected background process does not guard against same-file stdout/stderr redirection."
}

foreach ($functionName in @("Start-ManagedBackend")) {
$functionAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq $functionName
}, $true)
    if ($null -eq $functionAst) {
        throw "$functionName was not found."
    }
    $functionText = $functionAst.Extent.Text
    if ($functionText -match "Start-Process") {
        throw "$functionName still uses Start-Process."
    }
    if ($functionText -notmatch "Start-RedirectedBackgroundProcess") {
        throw "$functionName does not use the redirected no-window helper."
    }
}

$supervisorAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Start-Supervisor"
}, $true)
if ($null -eq $supervisorAst) {
    throw "Start-Supervisor was not found."
}
$supervisorText = $supervisorAst.Extent.Text
if ($supervisorText -match "Start-Process") {
    throw "Start-Supervisor still uses Start-Process."
}
if ($supervisorText -notmatch "Start-RedirectedBackgroundProcess") {
    throw "Start-Supervisor should use the Win32 no-window redirected starter."
}
if ($supervisorText -notmatch "-EncodedCommand") {
    throw "Start-Supervisor should use an encoded command for stable supervisor logging."
}
if ($supervisorText -notmatch "ConvertTo-PowerShellSingleQuotedLiteral") {
    throw "Start-Supervisor should quote paths and session ids inside the encoded command."
}
if ($supervisorText -notmatch "hidden_redirected_powershell" -or $supervisorText -notmatch "console_window_suppressed") {
    throw "Start-Supervisor should log the no-console supervisor launch strategy."
}

$managedBackendAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Start-ManagedBackend"
}, $true)
$managedBackendText = $managedBackendAst.Extent.Text
if ($managedBackendText -notmatch '--managed-by-launcher') {
    if ($managedBackendText -notmatch 'managedBackendMarkerArg' -or $managedBackendText -notmatch 'managed_marker') {
        throw "Start-ManagedBackend does not tag backend processes as launcher-managed."
    }
}
if ($managedBackendText -notmatch 'managed_marker') {
    throw "Start-ManagedBackend does not log the managed backend marker."
}
if ($managedBackendText -notmatch 'Resolve-PythonBackgroundLaunchCommand' -or $managedBackendText -notmatch 'python_no_console_command') {
    throw "Start-ManagedBackend does not resolve and log the hidden Python launch command."
}
if ($managedBackendText -notmatch 'python_launch_command' -or $managedBackendText -notmatch 'python_launch_policy') {
    throw "Start-ManagedBackend does not log the actual Python launch policy."
}
if ($managedBackendText -notmatch 'console_window_suppressed') {
    throw "Start-ManagedBackend does not log whether console windows are suppressed."
}
if ($managedBackendText -notmatch 'console_suppression_mode') {
    throw "Start-ManagedBackend does not log the console suppression mode."
}

$browserAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Start-ManagedBrowser"
}, $true)
if ($null -eq $browserAst) {
    throw "Start-ManagedBrowser was not found."
}
$browserText = $browserAst.Extent.Text
if ($browserText -match "Start-Process") {
    throw "Start-ManagedBrowser still uses Start-Process."
}
if ($browserText -notmatch "Start-GuiProcessWithoutConsole") {
    throw "Start-ManagedBrowser does not use the no-console GUI helper."
}
if ($browserText -notmatch "gui_process_without_console" -or $browserText -notmatch "console_window_suppressed") {
    throw "Start-ManagedBrowser does not log the no-console launch strategy."
}
if ($browserText -notmatch '--app=\\$resolvedAppUrl') {
    throw "Start-ManagedBrowser should keep using a resolved app window URL so the web manifest can theme the chrome."
}
if ($browserText -match '--force-dark-mode') {
    throw "Start-ManagedBrowser must not force Chromium dark mode; it fights workbench theme and causes whole-window flicker."
}
if ($browserText -match '--kiosk') {
    throw "Start-ManagedBrowser should not use kiosk mode for the workbench window."
}
if ($browserText -notmatch '--start-fullscreen' -or $browserText -notmatch 'fullscreenForced') {
    throw "Start-ManagedBrowser should request fullscreen through the managed window policy."
}
if ($browserText -notmatch '--window-size=\\$windowSizeArgument' -or $browserText -notmatch 'ConvertTo-EdgeWindowSizeArgument') {
    throw "Start-ManagedBrowser should apply a persisted window_size when the workbench is windowed."
}
if ($browserText -notmatch 'configured_workbench_window_mode' -or $browserText -notmatch 'launcher_taskbar_windowed') {
    throw "Start-ManagedBrowser should enforce configurable Workbench mode and separate Launcher taskbar window policies."
}
if ($browserText -notmatch '\\$WindowPurpose -eq "launcher_control_surface"\\) \\{ "windowed" \\} else \\{ \\$configuredWindowMode \\}') {
    throw "Start-ManagedBrowser should apply workbench.window_mode to the Workbench window while keeping Launcher windowed."
}
if ($browserText -notmatch 'configured_window_mode' -or $browserText -notmatch 'window_policy') {
    throw "Start-ManagedBrowser should log both configured and effective window policy values."
}
if ($browserText -notmatch 'window_size' -or $browserText -notmatch 'configured_window_size' -or $browserText -notmatch 'window_size_argument') {
    throw "Start-ManagedBrowser should log both configured and effective window size values."
}
if ($browserText -notmatch 'app_chrome_theme' -or $browserText -notmatch 'app_url' -or $browserText -notmatch 'window_purpose' -or $browserText -notmatch 'window_mode' -or $browserText -notmatch 'fullscreen_forced') {
    throw "Start-ManagedBrowser should log the managed app chrome strategy."
}

$saveStateAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Save-SessionState"
}, $true)
if ($null -eq $saveStateAst) {
    throw "Save-SessionState was not found."
}
$saveStateText = $saveStateAst.Extent.Text
if ($saveStateText -notmatch 'backendLaunchPid\\s*=\\s*if \\(\\$SessionRole -eq "launcher_control_surface"\\) \\{ 0 \\} else \\{ \\$BackendLaunchPid \\}') {
    throw "Save-SessionState does not persist workbench backendLaunchPid while separating launcher control state."
}
if ($saveStateText -notmatch 'launcherBackendLaunchPid\\s*=\\s*if \\(\\$SessionRole -eq "launcher_control_surface"\\) \\{ \\$BackendLaunchPid \\}') {
    throw "Save-SessionState does not persist launcherBackendLaunchPid for the control plane."
}
if ($saveStateText -notmatch 'supervisorStderr\\s*=\\s*if \\(\\$script:currentRuntimeSceneDir\\)') {
    throw "Save-SessionState does not persist supervisorStderr."
}
$managedSessionText = ($ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Start-ManagedSession"
}, $true)).Extent.Text
if ($managedSessionText -notmatch 'BackendLaunchPid\\s+\\$backendProc\\.LauncherPid') {
    throw "Start-ManagedSession does not save the backend launcher PID."
}
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_upgrades_headless_backend_before_cleanup(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

$completeAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Complete-HeadlessSessionWithBrowser"
}, $true)
if ($null -eq $completeAst) {
    throw "Complete-HeadlessSessionWithBrowser was not found."
}
$completeText = $completeAst.Extent.Text
foreach ($required in @(
    "runtime.scene.headless_upgrade.started",
    "Start-ManagedBrowser",
    "Start-Supervisor",
    "Save-SessionState",
    "runtime.scene.headless_upgrade.succeeded"
)) {
    if ($completeText -notmatch [regex]::Escape($required)) {
        throw "Headless upgrade is missing '$required'."
    }
}

$managedAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Start-ManagedSession"
}, $true)
if ($null -eq $managedAst) {
    throw "Start-ManagedSession was not found."
}
$managedText = $managedAst.Extent.Text
$upgradeIndex = $managedText.IndexOf("Complete-HeadlessSessionWithBrowser")
$cleanupIndex = $managedText.IndexOf("Found an incomplete managed session")
if ($upgradeIndex -lt 0) {
    throw "Start-ManagedSession does not attempt a headless backend upgrade."
}
if ($cleanupIndex -lt 0) {
    throw "Start-ManagedSession cleanup branch was not found."
}
    if ($upgradeIndex -gt $cleanupIndex) {
        throw "Headless backend upgrade must run before stale cleanup."
    }
    foreach ($required in @(
        "launcher.session.snapshot",
        "backend_healthy",
        "browser_window_count",
        "state_present",
        "restart_reason"
    )) {
        if ($managedText -notmatch [regex]::Escape($required)) {
            throw "Start-ManagedSession snapshot log is missing '$required'."
        }
    }
    Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_runtime_scene_initialization_persists_active_sidecar(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

foreach ($functionName in @("Save-ActiveRuntimeSceneReference", "Initialize-RuntimeScene")) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $functionName
    }, $true)
    if ($null -eq $functionAst) {
        throw "$functionName was not found."
    }
    if ($functionName -eq "Initialize-RuntimeScene" -and $functionAst.Extent.Text -notmatch "Save-ActiveRuntimeSceneReference") {
        throw "Initialize-RuntimeScene does not persist the active runtime scene sidecar."
    }
}

Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_frontend_build_failure_summary_includes_typescript_error(tmp_path):
    scene_dir = tmp_path / "scene"
    result = _run_launcher_ast_harness(
        tmp_path,
        f"""
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {{
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}}

foreach ($functionName in @("Get-RuntimeSceneRelativePaths", "Get-LogTail", "Get-FrontendBuildFailureSummary")) {{
    $functionAst = $ast.Find({{
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $functionName
    }}, $true)
    if ($null -eq $functionAst) {{
        throw "$functionName was not found."
    }}
    . ([scriptblock]::Create($functionAst.Extent.Text))
}}

$script:currentRuntimeSceneDir = {json.dumps(str(scene_dir))}
function Get-CurrentRuntimeSceneFilePath {{
    param([string]$RelativePath)
    return Join-Path $script:currentRuntimeSceneDir $RelativePath
}}
New-Item -ItemType Directory -Path (Join-Path $script:currentRuntimeSceneDir "raw") -Force | Out-Null
Set-Content -LiteralPath (Join-Path $script:currentRuntimeSceneDir "raw\\frontend.build.log") -Encoding utf8 -Value @(
    "vite v6.0.0 building",
    "web/src/routes/ToolsRoute.tsx(476,49): error TS2322: Type mismatch.",
    "At scripts/vibelution_launcher.ps1:2616 char:13"
)

$summary = Get-FrontendBuildFailureSummary -ExitCode 2
if ($summary -notmatch "npm run build failed with exit code 2") {{
    throw "Build failure summary does not include the npm exit code."
}}
if ($summary -notmatch "frontend\\.build\\.failed") {{
    throw "Build failure summary does not include the build failure event code."
}}
if ($summary -notmatch "ToolsRoute\\.tsx\\(476,49\\): error TS2322") {{
    throw "Build failure summary does not include the first TypeScript error."
}}
if ($summary -match "At scripts") {{
    throw "Build failure summary should prefer TypeScript errors over PowerShell stack noise."
}}

Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_python_candidates_prefer_python_runtime_with_no_console_sibling(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

$functionAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Get-ProjectPythonCandidates"
}, $true)
if ($null -eq $functionAst) {
    throw "Get-ProjectPythonCandidates was not found."
}
. ([scriptblock]::Create($functionAst.Extent.Text))

$projectDir = Join-Path $env:TEMP ("vibelution-python-candidates-" + [guid]::NewGuid().ToString("N"))
$scriptsDir = Join-Path $projectDir ".venv\\Scripts"
New-Item -ItemType Directory -Path $scriptsDir -Force | Out-Null
$pythonPath = Join-Path $scriptsDir "python.exe"
$pythonwPath = Join-Path $scriptsDir "pythonw.exe"
Set-Content -LiteralPath $pythonPath -Value "" -Encoding ascii
Set-Content -LiteralPath $pythonwPath -Value "" -Encoding ascii
Set-Variable -Name preferredPythonExe -Value $pythonPath -Scope Script
Set-Variable -Name preferredPythonNoConsoleExe -Value $pythonwPath -Scope Script
Set-Variable -Name launcherPythonOverride -Value $pythonPath -Scope Script

$candidates = @(Get-ProjectPythonCandidates)
if ($candidates.Count -ne 1) {
    throw "Expected one deduplicated Python candidate, got $($candidates.Count)."
}
if ($candidates[0].FilePath -ne (Resolve-Path -LiteralPath $pythonPath).Path) {
    throw "Launcher did not prefer python.exe."
}
if ($candidates[0].NoConsoleFilePath -ne (Resolve-Path -LiteralPath $pythonwPath).Path) {
    throw "Launcher did not attach pythonw.exe as the no-console runtime."
}
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_bootstrap_creates_project_venv_before_python_dependency_repair(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

$bootstrapAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Ensure-ProjectVirtualEnvironment"
}, $true)
if ($null -eq $bootstrapAst) {
    throw "Ensure-ProjectVirtualEnvironment was not found."
}

$depsAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Ensure-ProjectPythonDependencies"
}, $true)
if ($null -eq $depsAst) {
    throw "Ensure-ProjectPythonDependencies was not found."
}

$bootstrapText = $bootstrapAst.Extent.Text
$depsText = $depsAst.Extent.Text
if ($bootstrapText -notmatch 'Get-Command\\s+python') {
    throw "Virtual environment bootstrap does not discover Python from PATH."
}
if ($bootstrapText -notmatch '"-m",\\s*"venv"') {
    throw "Virtual environment bootstrap does not create the project venv with python -m venv."
}
if ($bootstrapText -notmatch 'bootstrap.virtualenv.create.started') {
    throw "Virtual environment bootstrap start event is not logged."
}
if ($bootstrapText -notmatch 'bootstrap.virtualenv.create.succeeded') {
    throw "Virtual environment bootstrap success event is not logged."
}
if ($bootstrapText -notmatch 'bootstrap.virtualenv.create.failed') {
    throw "Virtual environment bootstrap failure event is not logged."
}
if ($depsText -notmatch 'Ensure-ProjectVirtualEnvironment') {
    throw "Python dependency repair does not bootstrap the project venv first."
}
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_first_run_prerequisites_are_logged_before_bootstrap(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

function Get-FunctionText {
    param([string]$Name)
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $Name
    }, $true)
    if ($null -eq $functionAst) {
        throw "$Name was not found."
    }
    return $functionAst.Extent.Text
}

$prereqText = Get-FunctionText -Name "Assert-LauncherSystemPrerequisites"
$prereqEventText = Get-FunctionText -Name "Write-BootstrapPrerequisiteEvent"
$startText = Get-FunctionText -Name "Start-ManagedSession"

foreach ($required in @(
    "Get-Command\\s+python",
    "Resolve-NpmCliInvocation",
    "Resolve-EdgeExecutable",
    "bootstrap.prerequisite",
    "system_prerequisites",
    "Missing system prerequisites for first startup"
)) {
    if ($prereqText -notmatch $required -and $prereqEventText -notmatch $required) {
        throw "First-run prerequisite flow is missing '$required'."
    }
}

$prereqIndex = $startText.IndexOf("Assert-LauncherSystemPrerequisites")
$pythonIndex = $startText.IndexOf("Ensure-ProjectPythonDependencies")
$frontendIndex = $startText.IndexOf("Ensure-WebBuild")
$runtimeIndex = $startText.IndexOf("Resolve-PythonRuntime")
if ($prereqIndex -lt 0 -or $pythonIndex -lt 0 -or $frontendIndex -lt 0 -or $runtimeIndex -lt 0) {
    throw "Start-ManagedSession is missing one of the bootstrap phases."
}
if (-not ($prereqIndex -lt $pythonIndex -and $pythonIndex -lt $frontendIndex -and $frontendIndex -lt $runtimeIndex)) {
    throw "Start-ManagedSession should run prerequisites, Python bootstrap, frontend build, then backend runtime selection."
}
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_first_run_prerequisite_failures_are_actionable(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

foreach ($name in @("Resolve-NpmCommand", "Write-BootstrapPrerequisiteEvent", "Assert-LauncherSystemPrerequisites")) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $name
    }, $true)
    if ($null -eq $functionAst) {
        throw "$name was not found."
    }
    . ([scriptblock]::Create($functionAst.Extent.Text))
}

$script:controlEvents = @()
$script:runtimeEvents = @()
$script:currentRuntimeSceneId = "test-scene"
$projectDir = Join-Path $env:TEMP ("vibelution-prereq-" + [guid]::NewGuid().ToString("N"))
$projectVenvDir = Join-Path $projectDir ".venv"
$preferredPythonExe = Join-Path $projectVenvDir "Scripts\\python.exe"
New-Item -ItemType Directory -Path $projectDir -Force | Out-Null

function Get-Command {
    param([string]$Name)
    return $null
}
function Write-LauncherControlLog {
    param([string]$Event, [string]$Message, [string]$Level = "info", [hashtable]$Fields = @{})
    $script:controlEvents += ,@{ event = $Event; level = $Level; message = $Message; fields = $Fields }
}
function Write-RuntimeSceneEvent {
    param(
        [string]$Component,
        [string]$Phase,
        [string]$EventCode,
        [string]$Message,
        [string]$Level = "info",
        [string]$Outcome = "observed",
        [hashtable]$Fields = @{}
    )
    $script:runtimeEvents += ,@{ component = $Component; phase = $Phase; eventCode = $EventCode; outcome = $Outcome; level = $Level; fields = $Fields }
}

$message = ""
try {
    Assert-LauncherSystemPrerequisites -BrowserRequired $false
} catch {
    $message = $_.Exception.Message
}

if ($message -notmatch "Missing system prerequisites for first startup") {
    throw "Missing prerequisite failure was not actionable: $message"
}
if ($message -notmatch "Python" -or $message -notmatch "Node.js/npm") {
    throw "Missing prerequisite failure did not name Python and Node/npm: $message"
}
if (@($script:controlEvents | Where-Object { $_.event -eq "bootstrap.prerequisite.missing" }).Count -lt 2) {
    throw "Missing prerequisites were not written to launcher control log."
}
if (@($script:runtimeEvents | Where-Object { $_.eventCode -eq "bootstrap.prerequisite.missing" -and $_.phase -eq "system_prerequisites" }).Count -lt 2) {
    throw "Missing prerequisites were not written to runtime scene lifecycle."
}
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_virtualenv_bootstrap_is_idempotent(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

$names = @("Ensure-ProjectVirtualEnvironment", "Get-ProjectPythonCandidates")
foreach ($name in $names) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $name
    }, $true)
    if ($null -eq $functionAst) {
        throw "$name was not found."
    }
    . ([scriptblock]::Create($functionAst.Extent.Text))
}

$script:commands = @()
$script:controlEvents = @()
$script:runtimeEvents = @()
$script:currentRuntimeSceneId = "test-scene"
$projectDir = Join-Path $env:TEMP ("vibelution-bootstrap-" + [guid]::NewGuid().ToString("N"))
$projectVenvDir = Join-Path $projectDir ".venv"
$preferredPythonExe = Join-Path $projectVenvDir "Scripts\\python.exe"
$preferredPythonNoConsoleExe = Join-Path $projectVenvDir "Scripts\\pythonw.exe"
$launcherPythonOverride = ""
New-Item -ItemType Directory -Path $projectDir -Force | Out-Null

function Write-Note {
    param([string]$Message)
}
function Write-LauncherControlLog {
    param([string]$Event, [string]$Message, [string]$Level = "info", [hashtable]$Fields = @{})
    $script:controlEvents += ,@{ event = $Event; level = $Level; fields = $Fields }
}
function Write-RuntimeSceneEvent {
    param(
        [string]$Component,
        [string]$Phase,
        [string]$EventCode,
        [string]$Message,
        [string]$Level = "info",
        [string]$Outcome = "observed",
        [hashtable]$Fields = @{}
    )
    $script:runtimeEvents += ,@{ component = $Component; phase = $Phase; eventCode = $EventCode; outcome = $Outcome; level = $Level }
}
function Invoke-NativeCommand {
    param([string]$CommandPath, [string[]]$ArgumentList = @())
    $script:commands += ,@{ commandPath = $CommandPath; argumentList = @($ArgumentList) }
    if ($ArgumentList.Count -ge 3 -and $ArgumentList[0] -eq "-m" -and $ArgumentList[1] -eq "venv") {
        $scriptsDir = Join-Path $ArgumentList[2] "Scripts"
        New-Item -ItemType Directory -Path $scriptsDir -Force | Out-Null
        Set-Content -LiteralPath (Join-Path $scriptsDir "python.exe") -Value "" -Encoding ascii
    }
    return 0
}

Ensure-ProjectVirtualEnvironment
Ensure-ProjectVirtualEnvironment

if ($script:commands.Count -ne 1) {
    throw "Expected virtualenv bootstrap to run once, got $($script:commands.Count)."
}
$args = @($script:commands[0].argumentList)
if ($args[0] -ne "-m" -or $args[1] -ne "venv" -or $args[2] -ne $projectVenvDir) {
    throw "Virtualenv bootstrap did not invoke python -m venv for the project venv."
}
if (-not (Test-Path -LiteralPath $preferredPythonExe)) {
    throw "Virtualenv bootstrap did not create the project python path."
}
$candidate = @(Get-ProjectPythonCandidates)[0]
if ($candidate.FilePath -ne (Resolve-Path -LiteralPath $preferredPythonExe).Path) {
    throw "Project venv was not returned as the preferred Python candidate."
}
if (@($script:controlEvents | Where-Object { $_.event -eq "bootstrap.virtualenv.create.succeeded" }).Count -ne 1) {
    throw "Virtualenv bootstrap success was not logged once."
}
if (@($script:runtimeEvents | Where-Object { $_.eventCode -eq "bootstrap.virtualenv.create.succeeded" }).Count -ne 1) {
    throw "Virtualenv bootstrap success was not written to runtime scene once."
}
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_runtime_scene_lifecycle_event_classifier_indexes_operational_phases(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

$functionAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Test-RuntimeSceneLifecycleEvent"
}, $true)
if ($null -eq $functionAst) {
    throw "Test-RuntimeSceneLifecycleEvent was not found."
}
. ([scriptblock]::Create($functionAst.Extent.Text))

foreach ($phase in @(
    "session",
    "startup",
    "shutdown",
    "build",
    "health",
    "supervision",
    "dependencies",
    "python_dependencies",
    "window",
    "api",
    "desktop_monitor",
    "lifecycle",
    "navigation"
)) {
    $payload = @{
        component = "probe"
        phase = $phase
        event_code = "probe.$phase"
    }
    if (-not (Test-RuntimeSceneLifecycleEvent -Payload $payload)) {
        throw "Lifecycle classifier did not index phase '$phase'."
    }
}

if (-not (Test-RuntimeSceneLifecycleEvent -Payload @{ component = "runtime"; phase = "misc"; event_code = "runtime.scene.ready" })) {
    throw "Lifecycle classifier did not index runtime.scene events."
}
if (Test-RuntimeSceneLifecycleEvent -Payload @{ component = "browser_page"; phase = "focus"; event_code = "browser.focus.changed" }) {
    throw "Lifecycle classifier indexes browser focus noise."
}
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_focus_lifecycle_events_are_traceable(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

function Get-LauncherFunctionText {
    param([string]$Name)

    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $Name
    }, $true)
    if ($null -eq $functionAst) {
        throw "$Name was not found."
    }
    return $functionAst.Extent.Text
}

$focusText = Get-LauncherFunctionText -Name "Focus-ManagedBrowserWindow"
foreach ($required in @(
    "launcher.browser.focus.succeeded",
    "launcher.browser.focus.failed",
    "window_not_found",
    "browser_pids",
    "show_window",
    "set_foreground",
    "app_activate",
    "Converge-ManagedBrowserWindows",
    "kept_hwnd"
)) {
    if ($focusText -notmatch [regex]::Escape($required)) {
        throw "Focus-ManagedBrowserWindow is missing trace field '$required'."
    }
}

$convergeText = Get-LauncherFunctionText -Name "Converge-ManagedBrowserWindows"
foreach ($required in @(
    "Get-ManagedBrowserTopLevelWindows",
    "Get-ManagedBrowserWindowScore",
    "WM_CLOSE",
    "Vibelution",
    "launcher.browser.window_converge.succeeded"
)) {
    if ($convergeText -notmatch [regex]::Escape($required)) {
        throw "Converge-ManagedBrowserWindows is missing required fragment '$required'."
    }
}

$windowStateText = Get-LauncherFunctionText -Name "Set-ManagedBrowserWindowState"
foreach ($required in @(
    "launcher.browser.window_state.succeeded",
    "launcher.browser.window_state.failed",
    "target_state",
    "show_window_code",
    "minimized",
    "window_not_found"
)) {
    if ($windowStateText -notmatch [regex]::Escape($required)) {
        throw "Set-ManagedBrowserWindowState is missing trace field '$required'."
    }
}

$adoptText = Get-LauncherFunctionText -Name "Adopt-Or-FocusSession"
foreach ($required in @(
    "runtime.scene.focused",
    "runtime.scene.focus.failed",
    "Focus-ManagedBrowserWindow",
    "backendLaunchPid",
    "BackendLaunchPid `$backendLaunchPid"
)) {
    if ($adoptText -notmatch [regex]::Escape($required)) {
        throw "Adopt-Or-FocusSession is missing trace field '$required'."
    }
}

$startText = Get-LauncherFunctionText -Name "Start-ManagedSession"
foreach ($required in @(
    "runtime.scene.ready",
    "focus_requested",
    "Focus-ManagedBrowserWindow",
    "Test-ActionAllowsSessionRefresh",
    "Write-SessionRefreshSkippedForOpen",
    "allows_session_refresh"
)) {
    if ($startText -notmatch [regex]::Escape($required)) {
        throw "Start-ManagedSession is missing trace field '$required'."
    }
}

$refreshSkipText = Get-LauncherFunctionText -Name "Write-SessionRefreshSkippedForOpen"
foreach ($required in @(
    "launcher.session.refresh_skipped_for_open",
    "restart_reason",
    "use restart for code refresh"
)) {
    if ($refreshSkipText -notmatch [regex]::Escape($required)) {
        throw "Write-SessionRefreshSkippedForOpen is missing trace field '$required'."
    }
}

Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_redirected_background_process_runs_without_visible_shell_wrapper(tmp_path):
    stdout_path = tmp_path / "redirected.out.log"
    stderr_path = tmp_path / "redirected.err.log"
    powershell_exe = _powershell_exe()
    result = _run_launcher_ast_harness(
        tmp_path,
        f"""
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {{
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}}

foreach ($name in @(
    "ConvertTo-ProcessArgument",
    "ConvertTo-ProcessArgumentString",
    "Ensure-HiddenRedirectedProcessApi",
    "Start-RedirectedBackgroundProcess"
)) {{
    $functionAst = $ast.Find({{
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $name
    }}, $true)
    if ($null -eq $functionAst) {{
        throw "$name was not found."
    }}
    . ([scriptblock]::Create($functionAst.Extent.Text))
}}

Set-Variable -Name projectDir -Value {json.dumps(str(tmp_path))} -Scope Script
$proc = Start-RedirectedBackgroundProcess `
    -CommandPath {json.dumps(powershell_exe)} `
    -ArgumentList @(
        "-NoProfile",
        "-Command",
        "[Console]::Out.WriteLine('stdout-ok'); [Console]::Error.WriteLine('stderr-ok'); Start-Sleep -Milliseconds 300"
    ) `
    -WorkingDirectory {json.dumps(str(tmp_path))} `
    -StdoutPath {json.dumps(str(stdout_path))} `
    -StderrPath {json.dumps(str(stderr_path))}
$proc.WaitForExit(10000) | Out-Null
if (-not $proc.HasExited) {{
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    throw "Redirected process did not exit."
}}
if ($proc.ProcessName -match "cmd") {{
    throw "Redirected process returned a cmd wrapper PID."
}}
$stdout = Get-Content -Raw -LiteralPath {json.dumps(str(stdout_path))}
$stderr = Get-Content -Raw -LiteralPath {json.dumps(str(stderr_path))}
if ($stdout -notmatch "stdout-ok") {{
    throw "Redirected stdout log was not written."
}}
if ($stderr -notmatch "stderr-ok") {{
    throw "Redirected stderr log was not written."
}}
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_redirected_background_process_preserves_python_arguments(tmp_path):
    stdout_path = tmp_path / "python-redirected.out.log"
    stderr_path = tmp_path / "python-redirected.err.log"
    python_exe = str(Path(sys.executable))
    result = _run_launcher_ast_harness(
        tmp_path,
        f"""
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {{
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}}

foreach ($name in @(
    "ConvertTo-ProcessArgument",
    "ConvertTo-ProcessArgumentString",
    "Ensure-HiddenRedirectedProcessApi",
    "Start-RedirectedBackgroundProcess"
)) {{
    $functionAst = $ast.Find({{
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $name
    }}, $true)
    if ($null -eq $functionAst) {{
        throw "$name was not found."
    }}
    . ([scriptblock]::Create($functionAst.Extent.Text))
}}

Set-Variable -Name projectDir -Value {json.dumps(str(tmp_path))} -Scope Script
$proc = Start-RedirectedBackgroundProcess `
    -CommandPath {json.dumps(python_exe)} `
    -ArgumentList @(
        "-c",
        "import sys; print('args-ok:' + '|'.join(sys.argv[1:]))",
        "alpha",
        "beta value"
    ) `
    -WorkingDirectory {json.dumps(str(tmp_path))} `
    -StdoutPath {json.dumps(str(stdout_path))} `
    -StderrPath {json.dumps(str(stderr_path))}
$proc.WaitForExit(10000) | Out-Null
if (-not $proc.HasExited) {{
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    throw "Redirected Python process did not exit."
}}
$stdout = Get-Content -Raw -LiteralPath {json.dumps(str(stdout_path))}
if ($stdout -notmatch "args-ok:alpha\\|beta value") {{
    throw "Redirected Python arguments were not preserved: $stdout"
}}
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_hidden_process_capture_waits_and_preserves_exit_code(tmp_path):
    python_exe = str(Path(sys.executable))
    result = _run_launcher_ast_harness(
        tmp_path,
        f"""
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {{
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}}

foreach ($name in @(
    "ConvertTo-ProcessArgument",
    "ConvertTo-ProcessArgumentString",
    "Ensure-HiddenRedirectedProcessApi",
    "Invoke-HiddenProcessCapture"
)) {{
    $functionAst = $ast.Find({{
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $name
    }}, $true)
    if ($null -eq $functionAst) {{
        throw "$name was not found."
    }}
    . ([scriptblock]::Create($functionAst.Extent.Text))
}}

Set-Variable -Name projectDir -Value {json.dumps(str(tmp_path))} -Scope Script
Set-Variable -Name launcherDir -Value {json.dumps(str(tmp_path))} -Scope Script
$result = Invoke-HiddenProcessCapture `
    -FilePath {json.dumps(python_exe)} `
    -ArgumentList @(
        "-c",
        "import sys; print('capture-stdout'); print('capture-stderr', file=sys.stderr); sys.exit(7)"
    ) `
    -WorkingDirectory {json.dumps(str(tmp_path))}
if ($result.ProcessId -le 0) {{
    throw "Hidden process capture did not report a process id."
}}
if ($result.ExitCode -ne 7) {{
    throw "Hidden process capture did not preserve the exit code: $($result.ExitCode)"
}}
if ($result.Stdout -notmatch "capture-stdout") {{
    throw "Hidden process capture did not preserve stdout: $($result.Stdout)"
}}
if ($result.Stderr -notmatch "capture-stderr") {{
    throw "Hidden process capture did not preserve stderr: $($result.Stderr)"
}}
$leftovers = @(Get-ChildItem -LiteralPath {json.dumps(str(tmp_path))} -Filter "hidden-capture-*.log" -ErrorAction SilentlyContinue)
if ($leftovers.Count -ne 0) {{
    throw "Hidden process capture left temporary logs behind."
}}
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_desktop_entry_launcher_actions_are_no_window_and_monitor_is_skipped(tmp_path):
    result = _run_desktop_entry_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$DesktopEntryPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $DesktopEntryPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Desktop entry script parse failed: $($parseErrors[0].Message)"
}

$launcherActionAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Invoke-HiddenLauncherAction"
}, $true)
if ($null -eq $launcherActionAst) {
    throw "Invoke-HiddenLauncherAction was not found."
}
$launcherActionText = $launcherActionAst.Extent.Text
if ($launcherActionText -match "Start-Process") {
    throw "Desktop entry still uses Start-Process for launcher actions."
}
if ($launcherActionText -notmatch 'CreateNoWindow\\s*=\\s*\\$true') {
    throw "Desktop entry launcher action does not force CreateNoWindow."
}
if ($launcherActionText -notmatch 'UseShellExecute\\s*=\\s*\\$false') {
    throw "Desktop entry launcher action does not avoid shell execution."
}
if ($launcherActionText -notmatch '"-WindowStyle"\\s*,\\s*"Hidden"') {
    throw "Desktop entry launcher action does not force hidden PowerShell windows."
}
if ($launcherActionText -notmatch "RedirectStandardOutput" -or $launcherActionText -notmatch "RedirectStandardError") {
    throw "Desktop entry launcher action does not capture output."
}
if ($source -match 'Invoke-HiddenLauncherAction\\s+-LauncherAction\\s+"monitor"') {
    throw "Desktop entry still attaches the launcher monitor automatically."
}
if ($source -notmatch "desktop_entry.monitor.skipped") {
    throw "Desktop entry does not log skipped monitor behavior."
}
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_runtime_manager_client_forwards_expected_command_flags(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

$functionAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Invoke-RuntimeManagerClient"
}, $true)
if ($null -eq $functionAst) {
    throw "Invoke-RuntimeManagerClient was not found."
}
$launchCommandAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Resolve-PythonBackgroundLaunchCommand"
}, $true)
if ($null -eq $launchCommandAst) {
    throw "Resolve-PythonBackgroundLaunchCommand was not found."
}

. ([scriptblock]::Create($launchCommandAst.Extent.Text))
. ([scriptblock]::Create($functionAst.Extent.Text))

$script:calls = @()
$script:dependencyCalls = 0
function Ensure-ProjectPythonDependencies {
    $script:dependencyCalls += 1
}
function Resolve-PythonRuntime {
    if ($script:dependencyCalls -le 0) {
        throw "Resolve-PythonRuntime was called before dependency repair."
    }
    return [pscustomobject]@{ FilePath = "python-test"; NoConsoleFilePath = "pythonw-test"; PrefixArgs = @() }
}
function Resolve-PythonRuntimeReadOnly {
    return [pscustomobject]@{ FilePath = "python-status"; NoConsoleFilePath = "pythonw-status"; PrefixArgs = @() }
}
function Get-ObjectPropertyValue {
    param($Object, [string]$Name, $Default = $null)
    if ($null -eq $Object) { return $Default }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $Default }
    return $property.Value
}
function Invoke-HiddenNativeCommand {
    param([string]$CommandPath, [string[]]$ArgumentList = @())
    $script:calls += ,@{
        commandPath = $CommandPath
        argumentList = @($ArgumentList)
    }
    return 0
}
function Set-LauncherWindowTitle {}

$noConsoleLaunch = Resolve-PythonBackgroundLaunchCommand -PythonRuntime ([pscustomobject]@{ FilePath = "python-test"; NoConsoleFilePath = "pythonw-test"; PrefixArgs = @() })
if ($noConsoleLaunch.CommandPath -ne "pythonw-test") { throw "Background launch command did not prefer pythonw." }
if ($noConsoleLaunch.LaunchPolicy -ne "pythonw_no_console_background_service") { throw "Background launch policy did not record pythonw no-console usage." }
if ($noConsoleLaunch.FallbackReason -ne "") { throw "Background launch reported a fallback despite pythonw availability." }
$fallbackLaunch = Resolve-PythonBackgroundLaunchCommand -PythonRuntime ([pscustomobject]@{ FilePath = "python-test"; NoConsoleFilePath = ""; PrefixArgs = @() })
if ($fallbackLaunch.CommandPath -ne "python-test") { throw "Background launch fallback did not use source python." }
if ($fallbackLaunch.LaunchPolicy -ne "source_python_hidden_process_fallback") { throw "Background launch fallback policy was not recorded." }
if ($fallbackLaunch.FallbackReason -ne "pythonw_missing") { throw "Background launch fallback reason did not identify missing pythonw." }

Invoke-RuntimeManagerClient -Mode "command" -CommandType "open_workbench" -Reason "launcher_start" -ForwardNoBrowser
Invoke-RuntimeManagerClient -Mode "command" -CommandType "close_workbench" -Reason "launcher_stop"
Invoke-RuntimeManagerClient -Mode "command" -CommandType "restart_workbench" -Reason "launcher_restart"
Invoke-RuntimeManagerClient -Mode "status"

$openArgs = @($script:calls[0].argumentList)
$closeArgs = @($script:calls[1].argumentList)
$restartArgs = @($script:calls[2].argumentList)
$statusArgs = @($script:calls[3].argumentList)

if ($script:calls[0].commandPath -ne "pythonw-test") { throw "open_workbench did not use the no-console Python runtime." }
if ($script:calls[1].commandPath -ne "pythonw-test") { throw "close_workbench did not use the no-console Python runtime." }
if ($script:calls[2].commandPath -ne "pythonw-test") { throw "restart_workbench did not use the no-console Python runtime." }
if ($script:calls[3].commandPath -ne "pythonw-status") { throw "status did not use the read-only no-console Python runtime." }
if ($openArgs -notcontains "--no-browser") { throw "open_workbench did not forward --no-browser." }
if ($openArgs -contains "--stop-manager") { throw "open_workbench forwarded --stop-manager unexpectedly." }
if ($closeArgs -contains "--stop-manager") { throw "close_workbench should stop the workbench without stopping the Launcher control manager." }
if ($closeArgs -contains "--no-browser") { throw "close_workbench forwarded --no-browser unexpectedly." }
if ($restartArgs -contains "--no-browser") { throw "restart_workbench forwarded --no-browser unexpectedly." }
if ($restartArgs -contains "--stop-manager") { throw "restart_workbench forwarded --stop-manager unexpectedly." }
if ($restartArgs -notcontains "--timeout") { throw "restart_workbench did not pass an explicit wait timeout." }
$restartTimeoutIndex = [array]::IndexOf($restartArgs, "--timeout")
if ($restartTimeoutIndex -lt 0 -or $restartArgs[$restartTimeoutIndex + 1] -ne "180") { throw "restart_workbench should wait 180 seconds for guarded restart completion." }
if ($statusArgs -contains "command") { throw "status used command mode unexpectedly." }
if ($statusArgs -notcontains "status") { throw "status did not invoke runtime manager status." }
if ($script:dependencyCalls -ne 3) { throw "runtime manager client should repair dependencies only for mutating commands." }
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_status_reports_missing_dependencies_without_bootstrap(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

foreach ($name in @(
    "Get-ProjectPythonCandidates",
    "Get-PythonDependencyStatusReadOnly",
    "Write-StatusDependencyObservation",
    "Show-Status"
)) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $name
    }, $true)
    if ($null -eq $functionAst) {
        throw "$name was not found."
    }
    . ([scriptblock]::Create($functionAst.Extent.Text))
}

$script:bootstrapCalls = 0
$script:observations = @()
$projectDir = Join-Path $env:TEMP ("vibelution-status-readonly-" + [guid]::NewGuid().ToString("N"))
$projectVenvDir = Join-Path $projectDir ".venv"
$preferredPythonExe = Join-Path $projectVenvDir "Scripts\\python.exe"
$preferredPythonNoConsoleExe = Join-Path $projectVenvDir "Scripts\\pythonw.exe"
$launcherPythonOverride = ""
$requirementsPath = Join-Path $projectDir "requirements.txt"
$mode = "test"
$url = "http://127.0.0.1:8000"
$statePath = Join-Path $projectDir ".runtime\\launcher\\state.json"
$script:currentRuntimeSceneId = $null
$script:currentRuntimeSceneDir = $null
New-Item -ItemType Directory -Path $projectDir -Force | Out-Null

function Ensure-ProjectVirtualEnvironment { $script:bootstrapCalls += 1 }
function Ensure-ProjectPythonDependencies { $script:bootstrapCalls += 1 }
function Test-PythonRuntime { return $false }
function Get-SessionSnapshot {
    return [pscustomobject]@{
        BackendPid = 0
        BackendHealthy = $false
        BrowserWindowCount = 0
        BrowserWindowPid = 0
        BrowserPids = @()
        SupervisorPid = 0
        SessionRunning = $false
        BackendPids = @()
        State = $null
    }
}
function Get-WebBuildReason { return "" }
function Get-SessionRestartReason { param($Snapshot) return "" }
function Write-LauncherControlLog {
    param([string]$Event, [string]$Message, [string]$Level = "info", [hashtable]$Fields = @{})
    $script:observations += ,@{ event = $Event; fields = $Fields }
}
function Write-RuntimeSceneEvent {}

Show-Status

if ($script:bootstrapCalls -ne 0) {
    throw "status triggered dependency bootstrap unexpectedly."
}
if (-not @($script:observations | Where-Object { $_.event -eq "backend.dependencies.bootstrap.required" }).Count) {
    throw "status did not log dependency bootstrap requirement."
}
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_status_tolerates_state_missing_runtime_scene_fields(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

$functionAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Show-Status"
}, $true)
if ($null -eq $functionAst) {
    throw "Show-Status was not found."
}
. ([scriptblock]::Create($functionAst.Extent.Text))

$mode = "single_service_bundled_edge_app"
$projectDir = "C:\\Users\\17533\\Desktop\\Vibelution"
$url = "http://127.0.0.1:8000"
$statePath = "C:\\Users\\17533\\Desktop\\Vibelution\\.runtime\\launcher\\state.json"

function Get-PythonDependencyStatusReadOnly {
    return [pscustomobject]@{ Status = "ready"; Reason = "backend runtime imports are available" }
}
function Write-StatusDependencyObservation { param($DependencyStatus) }
function Get-WebBuildReason { return "" }
function Get-SessionRestartReason { param($Snapshot) return "" }
function Get-SessionSnapshot {
    return [pscustomobject]@{
        BackendPid = 34700
        BackendHealthy = $true
        BrowserWindowCount = 0
        BrowserWindowPid = 0
        BrowserPids = @()
        SupervisorPid = 0
        SessionRunning = $false
        BackendPids = @(34700)
        State = [pscustomobject]@{
            sessionId = "old-state"
        }
    }
}

Show-Status

Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"
    assert "Backend   : running" in result.stdout
    assert "State     :" in result.stdout


def test_launcher_python_dependency_install_honors_pip_overrides(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

foreach ($name in @("Get-PipExtraArgumentList", "Get-PipConfigSummary", "Get-PipInstallArgumentList")) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $name
    }, $true)
    if ($null -eq $functionAst) {
        throw "$name was not found."
    }
    . ([scriptblock]::Create($functionAst.Extent.Text))
}

$launcherPipIndexUrl = "https://mirror.example.invalid/simple"
$launcherPipExtraArgs = "--trusted-host mirror.example.invalid --timeout 30"
$requirementsPath = "C:\\project\\requirements.txt"

$args = @(Get-PipInstallArgumentList)
$summary = Get-PipConfigSummary

foreach ($required in @(
    "-m",
    "pip",
    "install",
    "--disable-pip-version-check",
    "--index-url",
    "https://mirror.example.invalid/simple",
    "--trusted-host",
    "mirror.example.invalid",
    "--timeout",
    "30",
    "-r",
    "C:\\project\\requirements.txt"
)) {
    if ($args -notcontains $required) {
        throw "pip install args are missing $required"
    }
}
if (-not $summary.pip_index_configured -or $summary.pip_index_host -ne "mirror.example.invalid") {
    throw "pip index summary was not captured."
}
if (-not $summary.pip_extra_args_configured) {
    throw "pip extra arg summary was not captured."
}
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_entry_opens_control_surface_without_starting_workbench(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

$controlAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Open-LauncherControlSurface"
}, $true)
if ($null -eq $controlAst) {
    throw "Open-LauncherControlSurface was not found."
}
$controlText = $controlAst.Extent.Text
foreach ($required in @(
    '$controlSurfaceUrl = "$launcherControlUrl/launcher"',
    '$startedControlBackend = $false',
    '$launcherBackendNeedsReplacement',
    '$replacedExistingLauncherControl = $false',
    '$preserveExistingStateOnFailure = [bool]$snapshot.State',
    "Test-LauncherControlSourceCurrent",
    "launcher.control_backend.source_change_detected",
    "launcher.control_surface.stale_browser_preserved_until_preflight",
    "launcher.control_backend.source_change_preflight_succeeded",
    "Start-LauncherControlBackend",
    "Start-ManagedBrowser",
    "Set-ManagedBrowserWindowState",
    '-ProfileDir $launcherBrowserProfileDir',
    "launcher_control_surface",
    "launcher.control_surface.keep_in_taskbar",
    "launcher.control_surface.ready",
    "taskbar_minimized",
    'supervisor_started = $false'
)) {
    if ($controlText -notmatch [regex]::Escape($required)) {
        throw "Launcher control surface is missing '$required'."
    }
}

$signatureAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Get-LauncherControlSourceSignature"
}, $true)
if ($null -eq $signatureAst) {
    throw "Get-LauncherControlSourceSignature was not found."
}
$signatureText = $signatureAst.Extent.Text
foreach ($requiredControlInput in @(
    "core\\launcher\\developer_mode.py",
    "core\\runtime_manager\\__init__.py",
    "core\\runtime_manager\\constants.py",
    "core\\runtime_manager\\evolution_store.py",
    "core\\runtime_manager\\scene_logging.py",
    "core\\runtime_manager\\state_store.py",
    "core\\runtime_manager\\work_run_store.py",
    "core\\runtime_manager\\workbench_controller.py",
    "web\\src\\routes\\LauncherRoute.tsx",
    "web\\src\\routes\\LauncherRoute.styles.ts",
    "web\\src\\app\\LauncherShell.tsx",
    "web\\src\\app\\LauncherShell.styles.ts",
    "web\\src\\app\\pollingPolicy.ts",
    "web\\src\\api\\launcher.ts",
    "web\\src\\api\\client.ts"
)) {
    if ($signatureText -notmatch [regex]::Escape($requiredControlInput)) {
        throw "Launcher control source signature is missing '$requiredControlInput'."
    }
}
foreach ($retiredControlInput in @(
    "web\\src\\routes\\LauncherRoute.module.css",
    "web\\src\\app\\LauncherShell.module.css"
)) {
    if ($signatureText -match [regex]::Escape($retiredControlInput)) {
        throw "Launcher control source signature still includes retired '$retiredControlInput'."
    }
}

if ($controlText -match "Start-Supervisor") {
    throw "Launcher control surface should not start the workbench supervisor."
}
if ($controlText -match "Invoke-RuntimeManagerClient" -or $controlText -match "open_workbench") {
    throw "Launcher control surface should not queue runtime manager open_workbench."
}
if ($source -notmatch 'internal-focus') {
    throw "Launcher script should expose an internal-focus action for non-destructive workbench focus."
}
if ($source -notmatch 'Assert-RuntimeManagerInternalLauncherCall -RequestedAction \\$Action\\s+Start-ManagedSession') {
    throw "internal-start should remain guarded before starting the managed session."
}
if ($source -notmatch 'Assert-RuntimeManagerInternalLauncherCall -RequestedAction \\$Action\\s+\\$snapshot = Get-SessionSnapshot') {
    throw "internal-focus should remain guarded before reading the managed session snapshot."
}
if ($source -notmatch 'Adopt-Or-FocusSession -Snapshot \\$snapshot') {
    throw "internal-focus should focus or adopt the existing workbench session."
}
if ($source -notmatch 'focus_unavailable') {
    throw "internal-focus should log when no existing workbench window can be focused."
}
$ensureWebBuildIndex = $controlText.IndexOf("Ensure-WebBuild")
$replaceBackendIndex = $controlText.IndexOf("launcher.control_backend.source_change_preflight_succeeded")
$stopBackendIndex = $controlText.IndexOf('Stop-ProcessesById -ProcessIds $launcherBackendPids')
if ($ensureWebBuildIndex -lt 0 -or $replaceBackendIndex -lt 0 -or $stopBackendIndex -lt 0) {
    throw "Launcher control source replacement preflight markers were not found."
}
if ($replaceBackendIndex -lt $ensureWebBuildIndex -or $stopBackendIndex -lt $ensureWebBuildIndex) {
    throw "Launcher control backend replacement must happen after Ensure-WebBuild succeeds."
}
if ($controlText -notmatch 'if\\s*\\(\\s*\\$startedControlBackend\\s*\\)\\s*\\{\\s*Stop-ProcessesById\\s+@\\(\\$backendPid\\)\\s*\\}') {
    throw "Launcher control surface failure cleanup must only stop the launcher control backend it started."
}
if ($controlText -notmatch 'if\\s*\\(\\s*\\$startedControlBackend\\s+-or\\s+\\$replacedExistingLauncherControl\\s*\\)\\s*\\{\\s*Stop-ManagedBrowserProcesses\\s+-ProfileDir\\s+\\$launcherBrowserProfileDir\\s+-Role\\s+"launcher_control_surface"\\s*\\}') {
    throw "Launcher control surface failure cleanup must not close a preserved stale browser before replacement."
}
if ($controlText -match 'if\\s*\\(\\s*\\$startedControlBackend\\s*\\)\\s*\\{\\s*Stop-ManagedBackendProcesses\\s*\\}') {
    throw "Launcher control surface failure cleanup must not stop the workbench backend helper."
}
if ($controlText -notmatch 'if\\s*\\(\\s*-not\\s+\\$preserveExistingStateOnFailure\\s*\\)\\s*\\{\\s*Remove-State\\s*\\}') {
    throw "Launcher control surface failure cleanup must preserve existing workbench state."
}
foreach ($requiredProfile in @("launcher-control-profile", "workbench-app-profile")) {
    if ($source -notmatch [regex]::Escape($requiredProfile)) {
        throw "Launcher script is missing browser profile '$requiredProfile'."
    }
}

$scriptText = $ast.EndBlock.Extent.Text
if ($scriptText -notmatch '\\$runtimeManagerClientActions\\s*=\\s*@\\("toggle", "start", "stop", "restart"\\)') {
    throw "Runtime-manager client actions changed unexpectedly."
}
foreach ($forbiddenClientAction in @("launcher", "status", "repair-deps", "repair-shortcut")) {
    if ($scriptText -match ('\\$runtimeManagerClientActions\\s*=\\s*@\\([^\\)]*"' + [regex]::Escape($forbiddenClientAction) + '"')) {
        throw "$forbiddenClientAction action must stay out of runtime-manager client actions."
    }
}
if ($source -notmatch '"repair-deps"') {
    throw "Launcher script is missing the explicit dependency repair action."
}
if ($scriptText -notmatch '"status"\\s*\\{\\s*Show-Status\\s*\\}') {
    throw "status action must stay on the read-only Show-Status path."
}
if ($scriptText -notmatch '"repair-deps"\\s*\\{\\s*Repair-ProjectPythonDependencies\\s*\\}') {
    throw "repair-deps action must invoke explicit Python dependency repair."
}
if ($scriptText -notmatch '"repair-shortcut"\\s*\\{[\\s\\S]*?Repair-LauncherShortcut[\\s\\S]*?\\}') {
    throw "repair-shortcut action must invoke explicit Launcher shortcut repair."
}
if ($scriptText -notmatch '"launcher"\\s*\\{[\\s\\S]*?Open-LauncherControlSurface[\\s\\S]*?\\}\\s*"toggle"') {
    throw "launcher action does not open only the Launcher control surface."
}

$entryAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Open-LauncherAndEnsureWorkbench"
}, $true)
if ($null -eq $entryAst) {
    throw "Open-LauncherAndEnsureWorkbench was not found."
}
$entryText = $entryAst.Extent.Text
foreach ($required in @(
    "Open-LauncherControlSurface",
    "Get-SessionSnapshot",
    "Adopt-Or-FocusSession",
    "Start-ManagedSession",
    "launcher.control_surface.workbench_start_requested"
)) {
    if ($entryText -notmatch [regex]::Escape($required)) {
        throw "Launcher entry is missing '$required'."
    }
}
if ($entryText -match "restart_workbench") {
    throw "Launcher entry should not submit a direct restart_workbench command."
}
if ($scriptText -match '"launcher"\\s*\\{\\s*Open-LauncherAndEnsureWorkbench\\s*\\}') {
    throw "launcher action must not auto-start or focus the workbench."
}

Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_runtime_command_skips_full_control_surface_when_existing_control_is_healthy(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

foreach ($name in @(
    "Test-ExistingLauncherControlSurfaceReadyForRuntimeCommand",
    "Ensure-LauncherControlSurfaceForRuntimeCommand"
)) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $name
    }, $true)
    if ($null -eq $functionAst) {
        throw "$name was not found."
    }
    . ([scriptblock]::Create($functionAst.Extent.Text))
}

$script:NoBrowser = $false
$script:launcherControlUrl = "http://127.0.0.1:8765"
$script:openCalls = 0
$script:headlessOpenCalls = 0
$script:releaseCalls = 0
$script:sourceCurrent = $true
$script:events = @()

function Acquire-LauncherMutex {}
function Release-LauncherMutex { $script:releaseCalls += 1 }
function Repair-StaleLauncherControlState {}
function Sync-LauncherEndpointFromState {}
function Open-LauncherControlSurface {
    param([switch]$Headless)
    $script:openCalls += 1
    if ($Headless) {
        $script:headlessOpenCalls += 1
    }
}
function Get-State {
    return [pscustomobject]@{
        launcherBackendPid = 111
        launcherBrowserWindowPid = 222
        launcherControlSourceSignature = "current"
    }
}
function Get-ObjectPropertyValue {
    param($Object, [string]$Name, $Default)
    if ($Object -and $Object.PSObject.Properties[$Name]) {
        return $Object.PSObject.Properties[$Name].Value
    }
    return $Default
}
function Test-ProcessAlive {
    param([int]$ProcessId)
    return $ProcessId -in @(111, 222)
}
function Test-LauncherControlHealthy { return $true }
function Test-LauncherControlSourceCurrent {
    param([int]$BackendPid)
    return $script:sourceCurrent -and $BackendPid -eq 111
}
function Write-LauncherControlLog {
    param([string]$Event, [string]$Message, [string]$Level = "info", [hashtable]$Fields = @{})
    $script:events += [pscustomobject]@{ event = $Event; fields = $Fields }
}

Ensure-LauncherControlSurfaceForRuntimeCommand -RequestedAction "start"
if ($script:openCalls -ne 0) {
    throw "Healthy existing control surface should skip full Open-LauncherControlSurface."
}
if ($script:releaseCalls -ne 1) {
    throw "Launcher mutex was not released after fast path."
}
$fastForwardEvents = @($script:events | Where-Object { $_.event -eq "launcher.lifecycle.runtime_command.control_surface.fast_forwarded" })
if ($fastForwardEvents.Count -ne 1) {
    throw "Fast-forward event was not logged."
}
if ($fastForwardEvents[0].fields.backend_pid -ne 111 -or $fastForwardEvents[0].fields.browser_window_pid -ne 222) {
    throw "Fast-forward event did not include tracked control surface pids."
}

$script:sourceCurrent = $false
Ensure-LauncherControlSurfaceForRuntimeCommand -RequestedAction "stop"
if ($script:openCalls -ne 1) {
    throw "Stale control source should fall back to full Open-LauncherControlSurface."
}
if ($script:headlessOpenCalls -ne 1) {
    throw "Runtime commands should restore a stale control backend without opening its browser window."
}
if ($script:releaseCalls -ne 2) {
    throw "Launcher mutex was not released after fallback path."
}

Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_start_uses_fast_closed_snapshot_from_launcher_control_state(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

foreach ($name in @(
    "Get-ClosedWorkbenchSessionSnapshotFromState",
    "Get-StartManagedSessionSnapshot"
)) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $name
    }, $true)
    if ($null -eq $functionAst) {
        throw "$name was not found."
    }
    . ([scriptblock]::Create($functionAst.Extent.Text))
}

$script:workbenchBrowserProfileDir = "C:\\project\\.runtime\\launcher\\workbench-app-profile"
$script:fullSnapshotCalls = 0
$script:alivePids = @{}
$script:state = [pscustomobject]@{
    sessionRole = "launcher_control_surface"
    backendPid = 0
    backendLaunchPid = 0
    workbenchBrowserWindowPid = 0
    workbenchBrowserLaunchPid = 0
    supervisorPid = 0
    launcherBackendPid = 111
    launcherBrowserWindowPid = 222
}
$script:events = @()

function Get-State { return $script:state }
function Get-ObjectPropertyValue {
    param($Object, [string]$Name, $Default)
    if ($Object -and $Object.PSObject.Properties[$Name]) {
        return $Object.PSObject.Properties[$Name].Value
    }
    return $Default
}
function Test-ProcessAlive {
    param([int]$ProcessId)
    return [bool]$script:alivePids[[string]$ProcessId]
}
function Get-SessionSnapshot {
    $script:fullSnapshotCalls += 1
    return [pscustomobject]@{ SnapshotMode = "full"; SessionRunning = $true }
}
function Write-LauncherControlLog {
    param([string]$Event, [string]$Message, [string]$Level = "info", [hashtable]$Fields = @{})
    $script:events += [pscustomobject]@{ event = $Event; fields = $Fields }
}

$snapshot = Get-StartManagedSessionSnapshot
if ($script:fullSnapshotCalls -ne 0) {
    throw "Closed launcher-control state should not call full Get-SessionSnapshot."
}
if ($snapshot.SnapshotMode -ne "closed_state_fast_path") {
    throw "Closed launcher-control state did not return the fast snapshot."
}
if ($snapshot.SessionRunning -or $snapshot.BrowserWindowCount -ne 0 -or $snapshot.BackendPids.Count -ne 0) {
    throw "Fast closed snapshot should report a closed workbench."
}
if (@($script:events | Where-Object { $_.event -eq "launcher.session.snapshot.fast_closed" }).Count -ne 1) {
    throw "Fast closed snapshot event was not logged."
}

$script:state = [pscustomobject]@{
    sessionRole = "launcher_control_surface"
    backendPid = 0
    backendLaunchPid = 0
    workbenchBrowserWindowPid = 333
    workbenchBrowserLaunchPid = 0
    supervisorPid = 0
}
$script:alivePids = @{ "333" = $true }
$fallbackSnapshot = Get-StartManagedSessionSnapshot
if ($script:fullSnapshotCalls -ne 1 -or $fallbackSnapshot.SnapshotMode -ne "full") {
    throw "Alive tracked workbench pid should fall back to full snapshot."
}

$script:state = [pscustomobject]@{
    sessionRole = "workbench"
    backendPid = 444
    backendLaunchPid = 0
    workbenchBrowserWindowPid = 0
    workbenchBrowserLaunchPid = 0
    supervisorPid = 0
}
$script:alivePids = @{}
$fallbackSnapshot = Get-StartManagedSessionSnapshot
if ($script:fullSnapshotCalls -ne 2 -or $fallbackSnapshot.SnapshotMode -ne "full") {
    throw "Non launcher-control state should fall back to full snapshot."
}

Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_control_source_signature_rejects_stale_backend(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

foreach ($functionName in @(
    "Get-ObjectPropertyValue",
    "Get-LauncherControlBackendSourceSignature",
    "Test-LauncherControlSourceCurrent"
)) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $functionName
    }, $true)
    if ($null -eq $functionAst) {
        throw "$functionName was not found."
    }
    . ([scriptblock]::Create($functionAst.Extent.Text))
}

$script:state = [pscustomobject]@{
    launcherBackendPid = 1234
    launcherBackendLaunchPid = 1234
    launcherControlSourceSignature = "old-signature"
}
function Get-State { return $script:state }
function Get-LauncherControlSourceSignature { return "new-signature" }

if (Test-LauncherControlSourceCurrent -BackendPid 1234) {
    throw "stale launcher control backend source was accepted."
}

$script:state.launcherControlSourceSignature = "new-signature"
if (-not (Test-LauncherControlSourceCurrent -BackendPid 1234)) {
    throw "current launcher control backend source was rejected."
}

if (Test-LauncherControlSourceCurrent -BackendPid 9999) {
    throw "untracked launcher control backend source was accepted."
}

if (Test-LauncherControlSourceCurrent -BackendPid 0) {
    throw "missing launcher control backend source was accepted."
}

Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_frontend_toolchain_detection_requires_real_package_entries(tmp_path):
    web_dir = tmp_path / "web"
    (web_dir / "node_modules" / "vite" / "bin").mkdir(parents=True)
    (web_dir / "node_modules" / "vite" / "bin" / "vite.js").write_text("", encoding="utf-8")
    result = _run_launcher_ast_harness(
        tmp_path,
        f"""
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {{
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}}

foreach ($functionName in @(
    "ConvertTo-WebRelativePath",
    "Get-FrontendToolchainMissingPaths"
)) {{
    $functionAst = $ast.Find({{
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $functionName
    }}, $true)
    if ($null -eq $functionAst) {{
        throw "$functionName was not found."
    }}
    . ([scriptblock]::Create($functionAst.Extent.Text))
}}

Set-Variable -Name webDir -Value {json.dumps(str(web_dir))} -Scope Script
$missing = @(Get-FrontendToolchainMissingPaths)
if ($missing.Count -ne 1) {{
    throw "Expected exactly one missing frontend toolchain path, got $($missing.Count): $($missing -join ', ')"
}}
if ($missing[0] -ne "node_modules\\typescript\\bin\\tsc") {{
    throw "Unexpected missing frontend toolchain path: $($missing[0])"
}}

New-Item -ItemType Directory -Force -Path (Join-Path $webDir "node_modules\\typescript\\bin") | Out-Null
New-Item -ItemType File -Force -Path (Join-Path $webDir "node_modules\\typescript\\bin\\tsc") | Out-Null
$missing = @(Get-FrontendToolchainMissingPaths)
if ($missing.Count -ne 0) {{
    throw "Expected complete frontend toolchain after restoring tsc, got: $($missing -join ', ')"
}}

Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_stop_preserves_control_surface_state(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

foreach ($functionName in @("Get-ObjectPropertyValue", "Restore-LauncherControlStateAfterWorkbenchStop")) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $functionName
    }, $true)
    if ($null -eq $functionAst) {
        throw "$functionName was not found."
    }
    . ([scriptblock]::Create($functionAst.Extent.Text))
}

$script:bindHost = "127.0.0.1"
$script:port = 8000
$script:url = "http://127.0.0.1:8000"
$script:launcherControlPort = 8765
$script:launcherControlUrl = "http://127.0.0.1:8765"
$script:launcherBrowserProfileDir = "launcher-profile"
$script:workbenchBrowserProfileDir = "workbench-profile"
$script:savedState = $null
$script:events = @()
function Test-LauncherControlHealthy { return $true }
function Get-ManagedBrowserPids {
    param([string]$ProfileDir = "", [string]$Role = "workbench")
    if ($Role -eq "launcher_control_surface") { return @(4500) }
    return @()
}
function Save-State { param($Payload) $script:savedState = $Payload }
function Write-LauncherControlLog {
    param([string]$Event, [string]$Message, [string]$Level = "info", [hashtable]$Fields = @{})
    $script:events += ,@{ event = $Event; message = $Message; fields = $Fields }
}

$previousState = [pscustomobject]@{
    sessionRole = "workbench"
    sessionId = "session-1"
    backendPid = 3001
    backendLaunchPid = 3001
    launcherBackendPid = 87650
    launcherBackendLaunchPid = 87650
    launcherBrowserLaunchPid = 4500
    launcherBrowserWindowPid = 4500
    workbenchBrowserLaunchPid = 3200
    workbenchBrowserWindowPid = 3200
    launcherControlStartedAt = "2026-06-06T00:00:00Z"
}

$restored = Restore-LauncherControlStateAfterWorkbenchStop -PreviousState $previousState
if (-not $restored) { throw "control surface state was not restored." }
if ($script:savedState.sessionRole -ne "launcher_control_surface") { throw "session role was not preserved as launcher control surface." }
if ($script:savedState.backendPid -ne 0) { throw "workbench backend pid should be cleared after stop." }
if ($script:savedState.launcherBackendPid -ne 87650) { throw "launcher backend pid was not preserved." }
if ($script:savedState.browserProfileDir -ne "launcher-profile") { throw "browser profile did not switch back to launcher profile." }
if ($script:savedState.workbenchBrowserWindowPid -ne 0) { throw "workbench browser pid should be cleared after stop." }
if ($script:savedState.launcherControlUrl -ne "http://127.0.0.1:8765/launcher") { throw "launcher control url was not restored." }
if ($script:events[0].event -ne "launcher.control_surface.state_preserved_after_workbench_stop") { throw "state preservation was not logged." }

Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_runtime_manager_client_failure_exits_launcher(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

$scriptText = $ast.EndBlock.Extent.Text
    if ($scriptText -notmatch '\\$clientExitCode\\s*=\\s*Invoke-RuntimeManagerClient') {
        throw "Runtime-manager client action return code is not captured."
    }
    if ($scriptText -notmatch 'if\\s*\\(\\s*\\$clientExitCode\\s+-ne\\s+0\\s*\\)') {
        throw "Runtime-manager client non-zero return code is not checked."
    }
    if ($scriptText -notmatch 'exit\\s+\\$clientExitCode') {
        throw "Runtime-manager client non-zero return code is not propagated."
    }
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_runtime_scene_package_search_text_expands_tags(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

foreach ($name in @(
    "ConvertTo-RuntimeSceneIndexToken",
    "Get-RuntimeSceneTriggerIndexToken",
    "Get-RuntimeSceneStatusIndexToken",
    "Get-RuntimeSceneStatusDisplayLabel",
    "Get-RuntimeSceneEffectiveStatus",
    "Get-RuntimeSceneTriggerDisplayLabel",
    "Get-RuntimeScenePackageIndex"
)) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $name
    }, $true)
    if ($null -eq $functionAst) {
        throw "$name was not found."
    }
    . ([scriptblock]::Create($functionAst.Extent.Text))
}

$index = Get-RuntimeScenePackageIndex `
    -SceneId "scene-a" `
    -StartedAt ([datetime]"2026-05-18T12:00:00Z") `
    -Trigger "internal-start" `
    -Status "stopped" `
    -Result "explicit_stop" `
    -StopReason "manual stop" `
    -EndedAt "2026-05-18T12:03:00Z"

if ($index.search_text -match "System\\.Object\\[\\]") {
    throw "search_text contains a stringified tag array."
}
if ($index.display_name -notmatch "工作台启动" -or $index.display_name -notmatch "手动停止") {
    throw "display_name is not user-readable Chinese."
}
foreach ($tag in @("runtime-scene", "workbench-lifecycle", "workbench-start", "manual-stop", "managed")) {
    if ($index.search_text -notmatch [regex]::Escape($tag)) {
        throw "search_text is missing tag $tag."
    }
}
if (@($index.tags) -contains "System.Object[]") {
    throw "tags contains a stringified array."
}
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_runtime_scene_manifest_writes_package_index_file(tmp_path):
    scene_dir = tmp_path / "scene"
    result = _run_launcher_ast_harness(
        tmp_path,
        f"""
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {{
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}}

foreach ($name in @(
    "ConvertTo-RuntimeSceneIndexToken",
    "Get-RuntimeSceneTriggerIndexToken",
    "Get-RuntimeSceneStatusIndexToken",
    "Get-RuntimeSceneStatusDisplayLabel",
    "Get-RuntimeSceneEffectiveStatus",
    "Get-RuntimeSceneTriggerDisplayLabel",
    "Get-RuntimeScenePackageIndex",
    "Get-RuntimeScenePackageSummary",
    "Get-RuntimeSceneJsonlEventCount",
    "Get-RuntimeSceneSeverityCounts",
    "Get-RuntimeSceneEventSeverity",
    "Get-RuntimeSceneChildFileCount",
    "Get-HashtableStringValue",
    "ConvertTo-PlainHashtable",
    "Write-RuntimeSceneJsonFile",
    "Save-RuntimeSceneManifest"
)) {{
    $functionAst = $ast.Find({{
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $name
    }}, $true)
    if ($null -eq $functionAst) {{
        throw "$name was not found."
    }}
    . ([scriptblock]::Create($functionAst.Extent.Text))
}}

$script:currentRuntimeSceneDir = {json.dumps(str(scene_dir))}
$script:runtimeSceneWriteMaxAttempts = 2
$script:runtimeSceneWriteRetryDelayMilliseconds = 1
function Ensure-CurrentRuntimeSceneSubdirs {{
    New-Item -ItemType Directory -Path $script:currentRuntimeSceneDir -Force | Out-Null
}}
function Get-CurrentRuntimeSceneFilePath {{
    param([string]$RelativePath)
    return Join-Path $script:currentRuntimeSceneDir $RelativePath
}}
New-Item -ItemType Directory -Path (Join-Path $script:currentRuntimeSceneDir "agent/supervised_runs") -Force | Out-Null
Set-Content -Path (Join-Path $script:currentRuntimeSceneDir "agent/supervised_runs/run-a.jsonl") -Value '{{}}' -Encoding UTF8
New-Item -ItemType Directory -Path (Join-Path $script:currentRuntimeSceneDir "agent/self_evolution_runs") -Force | Out-Null
Set-Content -Path (Join-Path $script:currentRuntimeSceneDir "agent/self_evolution_runs/run-b.jsonl") -Value '{{}}' -Encoding UTF8
Set-Content -Path (Join-Path $script:currentRuntimeSceneDir "timeline.jsonl") -Value @(
    '{{"level":"info","outcome":"observed","fields":{{}}}}',
    '{{"level":"warning","outcome":"degraded","fields":{{}}}}',
    '{{"level":"warning","outcome":"retrying","fields":{{"errorType":"network_error","error":"temporary transport failure"}}}}',
    '{{"level":"error","outcome":"failed","fields":{{"errorType":"RuntimeError"}}}}'
) -Encoding UTF8
Set-Content -Path (Join-Path $script:currentRuntimeSceneDir "lifecycle.jsonl") -Value @(
    '{{"phase":"startup","level":"info","outcome":"observed","fields":{{}}}}',
    '{{"phase":"shutdown","level":"info","outcome":"succeeded","fields":{{}}}}'
) -Encoding UTF8

Save-RuntimeSceneManifest -Manifest @{{
    schema_version = 2
    runtime_scene_id = "scene-a"
    started_at = "2026-05-18T12:00:00Z"
    ended_at = "2026-05-18T12:03:00Z"
    status = "stopped"
    result = "explicit_stop"
    stop_reason = "manual stop"
    trigger = "internal-start"
}}

$manifest = Get-Content -LiteralPath (Join-Path $script:currentRuntimeSceneDir "manifest.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$packageIndex = Get-Content -LiteralPath (Join-Path $script:currentRuntimeSceneDir "package_index.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$summary = Get-Content -LiteralPath (Join-Path $script:currentRuntimeSceneDir "summary.json") -Raw -Encoding UTF8 | ConvertFrom-Json
if ($manifest.package.package_index_path -ne "package_index.json") {{
    throw "manifest package does not point to package_index.json."
}}
if ($manifest.package.summary_path -ne "summary.json") {{
    throw "manifest package does not point to summary.json."
}}
if ($packageIndex.package_id -ne "scene-a") {{
    throw "package_index package_id did not round-trip."
}}
if ($packageIndex.index_key -ne $manifest.package.index_key) {{
    throw "package_index and manifest package index_key diverged."
}}
if ($packageIndex.search_text -match "System\\.Object\\[\\]") {{
    throw "package_index search_text contains a stringified tag array."
}}
if ($summary.package_id -ne "scene-a") {{
    throw "summary package_id did not round-trip."
}}
if ($summary.primary_files.package_index -ne "package_index.json") {{
    throw "summary does not point to package_index.json."
}}
if ($summary.primary_files.timeline -ne "timeline.jsonl" -or $summary.primary_files.lifecycle -ne "lifecycle.jsonl") {{
    throw "summary does not point to lifecycle entry files."
}}
if ($summary.primary_files.startup -ne "raw/desktop-entry.log") {{
    throw "summary does not point to startup entry file."
}}
if ($summary.sections.startup.path -ne "raw/desktop-entry.log") {{
    throw "summary missing startup section."
}}
if ($summary.sections.startup.launcher_path -ne "raw/launcher-control.log") {{
    throw "summary startup section does not include launcher control log."
}}
if ($summary.sections.supervised_evolution.path -ne "agent/supervised_runs") {{
    throw "summary missing supervised evolution section."
}}
if ($summary.sections.supervised_evolution.worktree_path -ne "agent/supervised_worktree_runs") {{
    throw "summary missing supervised worktree evolution section."
}}
if ($summary.sections.self_evolution.path -ne "agent/self_evolution_runs") {{
    throw "summary missing self evolution section."
}}
if ($summary.event_counts.supervised_evolution_logs -ne 1) {{
    throw "summary supervised evolution log count is wrong."
}}
if ($summary.event_counts.self_evolution_logs -ne 1) {{
    throw "summary self evolution log count is wrong."
}}
if ($summary.event_counts.timeline_events -ne 4) {{
    throw "summary timeline event count should count jsonl rows."
}}
if ($summary.event_counts.lifecycle_events -ne 2) {{
    throw "summary lifecycle event count should count jsonl rows."
}}
if ($summary.event_counts.errors -ne 1) {{
    throw "summary error count should reflect timeline event severity."
}}
if ($summary.event_counts.warnings -ne 2) {{
    throw "summary warning count should preserve explicit warning level before error markers."
}}
if ($summary.diagnostic_entrypoint.recommended_order[0] -ne "summary.json") {{
    throw "summary diagnostic order does not start from summary.json."
}}
if ($summary.diagnostic_entrypoint.recommended_order[2] -ne "raw/desktop-entry-vbs.log") {{
    throw "summary diagnostic order should inspect startup logs before timeline."
}}
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_runtime_scene_manifest_treats_active_unknown_package_as_running(tmp_path):
    scene_dir = tmp_path / "scene"
    result = _run_launcher_ast_harness(
        tmp_path,
        f"""
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {{
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}}

foreach ($name in @(
    "ConvertTo-RuntimeSceneIndexToken",
    "Get-RuntimeSceneTriggerIndexToken",
    "Get-RuntimeSceneStatusIndexToken",
    "Get-RuntimeSceneStatusDisplayLabel",
    "Get-RuntimeSceneEffectiveStatus",
    "Get-RuntimeSceneTriggerDisplayLabel",
    "Get-RuntimeScenePackageIndex",
    "Get-RuntimeScenePackageSummary",
    "Get-RuntimeSceneJsonlEventCount",
    "Get-RuntimeSceneSeverityCounts",
    "Get-RuntimeSceneEventSeverity",
    "Get-RuntimeSceneChildFileCount",
    "Get-HashtableStringValue",
    "ConvertTo-PlainHashtable",
    "Write-RuntimeSceneJsonFile",
    "Save-RuntimeSceneManifest"
)) {{
    $functionAst = $ast.Find({{
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $name
    }}, $true)
    if ($null -eq $functionAst) {{
        throw "$name was not found."
    }}
    . ([scriptblock]::Create($functionAst.Extent.Text))
}}

$script:currentRuntimeSceneDir = {json.dumps(str(scene_dir))}
$script:runtimeSceneWriteMaxAttempts = 2
$script:runtimeSceneWriteRetryDelayMilliseconds = 1
function Ensure-CurrentRuntimeSceneSubdirs {{
    New-Item -ItemType Directory -Path $script:currentRuntimeSceneDir -Force | Out-Null
}}
function Get-CurrentRuntimeSceneFilePath {{
    param([string]$RelativePath)
    return Join-Path $script:currentRuntimeSceneDir $RelativePath
}}

Save-RuntimeSceneManifest -Manifest @{{
    schema_version = 2
    runtime_scene_id = "scene-active"
    started_at = "2026-05-24T12:00:01Z"
    ended_at = ""
    status = "unknown"
    trigger = "internal-start"
}}

$manifest = Get-Content -LiteralPath (Join-Path $script:currentRuntimeSceneDir "manifest.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$packageIndex = Get-Content -LiteralPath (Join-Path $script:currentRuntimeSceneDir "package_index.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$summary = Get-Content -LiteralPath (Join-Path $script:currentRuntimeSceneDir "summary.json") -Raw -Encoding UTF8 | ConvertFrom-Json
if ($packageIndex.index_key -notmatch "_running$") {{
    throw "active unknown package index should end with running."
}}
if ($packageIndex.display_name -notmatch "运行中") {{
    throw "active unknown package display name should be user-readable running."
}}
if ($summary.status -ne "running") {{
    throw "active unknown package summary should report running."
}}
if ($manifest.package.index_key -ne $packageIndex.index_key) {{
    throw "manifest package index should match package_index."
}}
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_runtime_scene_json_write_is_nonfatal_when_manifest_locked(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

$functionAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Write-RuntimeSceneJsonFile"
}, $true)
if ($null -eq $functionAst) {
    throw "Write-RuntimeSceneJsonFile was not found."
}

. ([scriptblock]::Create($functionAst.Extent.Text))

$script:runtimeSceneWriteMaxAttempts = 1
$script:runtimeSceneWriteRetryDelayMilliseconds = 1
$script:logEvents = @()
function Write-LauncherControlLog {
    param(
        [string]$Event,
        [string]$Message,
        [string]$Level = "info",
        [hashtable]$Fields = @{}
    )
    $script:logEvents += ,@{
        event = $Event
        message = $Message
        level = $Level
        fields = $Fields
    }
}

$targetDir = Join-Path ([System.IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
$manifestPath = Join-Path $targetDir "manifest.json"
[System.IO.File]::WriteAllText($manifestPath, "{}")
$lock = [System.IO.File]::Open($manifestPath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
try {
    $ok = Write-RuntimeSceneJsonFile -Path $manifestPath -Value @{ status = "running" } -Depth 4
} finally {
    $lock.Dispose()
}

if ($ok) {
    throw "Runtime scene JSON write unexpectedly succeeded while the target file was locked."
}
if ($script:logEvents.Count -ne 1) {
    throw "Runtime scene JSON write failure was not logged exactly once."
}
if ($script:logEvents[0].event -ne "launcher.runtime_scene.write.failed") {
    throw "Unexpected log event: $($script:logEvents[0].event)"
}
if ($script:logEvents[0].level -ne "warning") {
    throw "Runtime scene JSON write failure should be a warning, not a fatal error."
}
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_runtime_scene_event_append_is_nonfatal_when_lifecycle_locked(tmp_path):
    scene_dir = tmp_path / "scene"
    result = _run_launcher_ast_harness(
        tmp_path,
        f"""
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {{
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}}

foreach ($name in @(
    "Write-RuntimeSceneTextLine",
    "Test-RuntimeSceneLifecycleEvent",
    "Write-RuntimeSceneEvent"
)) {{
    $functionAst = $ast.Find({{
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $name
    }}, $true)
    if ($null -eq $functionAst) {{
        throw "$name was not found."
    }}
    . ([scriptblock]::Create($functionAst.Extent.Text))
}}

$script:currentRuntimeSceneId = "scene-locked"
$script:currentRuntimeSceneDir = {json.dumps(str(scene_dir))}
$script:sceneEventSequence = @{{}}
$script:runtimeSceneWriteMaxAttempts = 1
$script:runtimeSceneWriteRetryDelayMilliseconds = 1
$sceneSchemaVersion = 2
$script:logEvents = @()
function Ensure-CurrentRuntimeSceneSubdirs {{
    New-Item -ItemType Directory -Path $script:currentRuntimeSceneDir -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $script:currentRuntimeSceneDir "events") -Force | Out-Null
}}
function Get-CurrentRuntimeSceneFilePath {{
    param([string]$RelativePath)
    return Join-Path $script:currentRuntimeSceneDir $RelativePath
}}
function Write-LauncherControlLog {{
    param(
        [string]$Event,
        [string]$Message,
        [string]$Level = "info",
        [hashtable]$Fields = @{{}}
    )
    $script:logEvents += ,@{{
        event = $Event
        message = $Message
        level = $Level
        fields = $Fields
    }}
}}

Ensure-CurrentRuntimeSceneSubdirs
$lifecyclePath = Join-Path $script:currentRuntimeSceneDir "lifecycle.jsonl"
[System.IO.File]::WriteAllText($lifecyclePath, "")
$lock = [System.IO.File]::Open($lifecyclePath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
try {{
    Write-RuntimeSceneEvent `
        -Component "launcher" `
        -Phase "session" `
        -EventCode "runtime.scene.ready" `
        -Message "ready" `
        -Outcome "succeeded"
}} finally {{
    $lock.Dispose()
}}

$eventPath = Join-Path $script:currentRuntimeSceneDir "events/launcher.jsonl"
$timelinePath = Join-Path $script:currentRuntimeSceneDir "timeline.jsonl"
if (-not (Test-Path -LiteralPath $eventPath)) {{
    throw "Component event file was not written."
}}
if (-not (Test-Path -LiteralPath $timelinePath)) {{
    throw "Timeline file was not written."
}}
if ($script:logEvents.Count -ne 1) {{
    throw "Expected exactly one append failure log, got $($script:logEvents.Count)."
}}
if ($script:logEvents[0].event -ne "launcher.runtime_scene.append.failed") {{
    throw "Unexpected log event: $($script:logEvents[0].event)"
}}
if ($script:logEvents[0].level -ne "warning") {{
    throw "Runtime scene append failure should be a warning."
}}
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_closure_record_normalizes_successful_manifest_runtime_manager(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

$functionAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Write-ManagedSessionClosureRecord"
}, $true)
if ($null -eq $functionAst) {
    throw "Write-ManagedSessionClosureRecord was not found."
}
. ([scriptblock]::Create($functionAst.Extent.Text))

$script:currentRuntimeSceneId = "scene-1"
$launcherControlLogPath = "control.log"
$script:manifestUpdates = @()
$script:manifestState = @{}
$script:controlFields = @()
function Get-RuntimeSceneFinalState {
    param([string]$Reason)
    if ($Reason -match "startup failure") {
        return @{ status = "failed"; result = "startup_failed" }
    }
    return @{ status = "stopped"; result = "runtime_manager_stop" }
}
function Get-RuntimeSceneRelativePaths {
    return [pscustomobject]@{ LauncherControl = "raw/launcher-control.log" }
}
function Get-RuntimeSceneManifest {
    return $script:manifestState
}
function Update-RuntimeSceneManifest {
    param([hashtable]$Changes)
    $script:manifestUpdates += ,$Changes
    foreach ($key in $Changes.Keys) {
        $script:manifestState[$key] = $Changes[$key]
    }
}
function Write-LauncherControlLog {
    param([string]$Event, [string]$Message, [string]$Level = "info", [hashtable]$Fields = @{})
    $script:controlFields += ,$Fields
}

$closingSnapshot = [pscustomobject]@{
    BackendStopped = $true
    BackendHealthy = $false
    BrowserStopped = $true
    ManagerClosed = $false
    BackendPids = @()
    BrowserPids = @()
    BrowserWindowCount = 0
    PortOwnerPid = $null
    DesiredState = "closed"
    ObservedState = "open"
    Phase = "closing"
    FailureMessage = ""
}

Write-ManagedSessionClosureRecord -Closure $closingSnapshot -Reason "runtime manager stop" -Source "launcher_stop" -Success $true -Timings @{ total_ms = 123; browser_wait_ms = 45 }
Write-ManagedSessionClosureRecord -Closure $closingSnapshot -Reason "launcher_start" -Source "desktop_monitor" -Success $true
Write-ManagedSessionClosureRecord -Closure $closingSnapshot -Reason "desktop monitor shutdown timeout" -Source "desktop_monitor" -Success $false
Write-ManagedSessionClosureRecord -Closure $closingSnapshot -Reason "startup failure" -Source "launcher_stop" -Success $true

$successRuntimeManager = $script:manifestUpdates[0].runtime_manager
$monitorRuntimeManager = $script:manifestUpdates[1].runtime_manager
$failedRuntimeManager = $script:manifestUpdates[2].runtime_manager
$startupFailureRuntimeManager = $script:manifestUpdates[3].runtime_manager
$payload = @{
    success = $successRuntimeManager
    successSupervisor = $script:manifestUpdates[0].supervisor
    monitor = @{
        result = $script:manifestUpdates[1].result
        stopReason = $script:manifestUpdates[1].stop_reason
        runtimeManager = $monitorRuntimeManager
        supervisor = $script:manifestUpdates[1].supervisor
    }
    failed = $failedRuntimeManager
    failedHasSupervisor = $script:manifestUpdates[2].ContainsKey("supervisor")
    startupFailure = $startupFailureRuntimeManager
    startupFailureHasSupervisor = $script:manifestUpdates[3].ContainsKey("supervisor")
    controlLogBackendHealthy = $script:controlFields[0].backend_healthy
    controlLogPhase = $script:controlFields[0].phase
    controlLogObservedState = $script:controlFields[0].observed_state
    manifestTimingTotal = $script:manifestUpdates[0].launcher.shutdown_timings_ms.total_ms
    controlTimingBrowserWait = $script:controlFields[0].timings_ms.browser_wait_ms
} | ConvertTo-Json -Depth 8 -Compress
Write-Output $payload
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["success"] == {
        "desired_state": "closed",
        "failure_message": "",
        "observed_state": "closed",
        "phase": "steady",
    }
    assert payload["successSupervisor"] == {"pid": 0, "status": "stopped"}
    assert payload["monitor"]["result"] == "runtime_manager_stop"
    assert payload["monitor"]["stopReason"] == "runtime manager stop"
    assert payload["monitor"]["runtimeManager"]["observed_state"] == "closed"
    assert payload["monitor"]["runtimeManager"]["phase"] == "steady"
    assert payload["monitor"]["supervisor"] == {"pid": 0, "status": "stopped"}
    assert payload["failed"]["observed_state"] == "open"
    assert payload["failed"]["phase"] == "closing"
    assert payload["failedHasSupervisor"] is False
    assert payload["startupFailure"]["observed_state"] == "open"
    assert payload["startupFailure"]["phase"] == "closing"
    assert payload["startupFailureHasSupervisor"] is False
    assert payload["controlLogBackendHealthy"] is False
    assert payload["controlLogObservedState"] == "open"
    assert payload["controlLogPhase"] == "closing"
    assert payload["manifestTimingTotal"] == 123
    assert payload["controlTimingBrowserWait"] == 45


def test_launcher_backend_liveness_accepts_reconciled_backend(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

foreach ($functionName in @("Get-ManagedBackendLiveness", "Test-ManagedBackendAlive")) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $functionName
    }, $true)
    if ($null -eq $functionAst) {
        throw "$functionName was not found."
    }
    . ([scriptblock]::Create($functionAst.Extent.Text))
}

$script:candidatePids = @(2222)
$script:webHealthy = $false
function Get-ManagedBackendCandidatePids { return @($script:candidatePids) }
function Test-ProcessAlive { param([int]$ProcessId) return $false }
function Test-WebHealthy { return [bool]$script:webHealthy }

$candidateOnly = Get-ManagedBackendLiveness -TrackedPid 1111
if (-not $candidateOnly.Alive -or $candidateOnly.TrackedPidAlive -or $candidateOnly.CandidatePids[0] -ne 2222) {
    throw "candidate backend was not accepted as alive."
}
if (-not (Test-ManagedBackendAlive -TrackedPid 1111)) {
    throw "Test-ManagedBackendAlive rejected a candidate backend."
}

$script:candidatePids = @()
$script:webHealthy = $true
$healthyOnly = Get-ManagedBackendLiveness -TrackedPid 1111
if (-not $healthyOnly.Alive -or -not $healthyOnly.Healthy) {
    throw "healthy backend was not accepted as alive."
}

$script:webHealthy = $false
$dead = Get-ManagedBackendLiveness -TrackedPid 1111
if ($dead.Alive) {
    throw "dead backend was accepted as alive."
}

Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_restart_guard_blocks_active_work_from_status(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

foreach ($functionName in @(
    "Get-ObjectPropertyValue",
    "Test-LauncherRestartActiveWorkBlocked"
)) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $functionName
    }, $true)
    if ($null -eq $functionAst) {
        throw "$functionName was not found."
    }
    . ([scriptblock]::Create($functionAst.Extent.Text))
}

$script:url = "http://127.0.0.1:8000"
$script:launcherControlUrl = "http://127.0.0.1:8765"
$script:notes = @()
$script:events = @()
function Test-WebHealthy { return $true }
function Test-LauncherControlHealthy { return $true }
function Get-LauncherLocalActiveWorkRunCount { return 1 }
function Write-Note { param([string]$Message) $script:notes += $Message }
function Write-LauncherControlLog {
    param([string]$Event, [string]$Message, [string]$Level = "info", [hashtable]$Fields = @{})
    $script:events += ,@{ event = $Event; message = $Message; level = $Level; fields = $Fields }
}
function Invoke-WebRequest {
    throw "restart guard should not query HTTP status."
}

$blocked = Test-LauncherRestartActiveWorkBlocked
if (-not $blocked) { throw "active work did not block restart." }
if ($script:notes[0] -notmatch "有进行中的任务，无法重启 Vibelution") { throw "blocked message was not user-readable." }
if ($script:events[0].event -ne "launcher.restart.blocked_active_work") { throw "blocked event was not logged." }
if ($script:events[0].fields.active_work_count -ne 1) { throw "active work count was not logged." }
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_restart_guard_allows_recovery_when_backend_unhealthy(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

$functionAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Test-LauncherRestartActiveWorkBlocked"
}, $true)
if ($null -eq $functionAst) {
    throw "Test-LauncherRestartActiveWorkBlocked was not found."
}
. ([scriptblock]::Create($functionAst.Extent.Text))

$script:url = "http://127.0.0.1:8000"
function Test-LauncherControlHealthy { return $false }
function Test-WebHealthy { return $false }
function Get-LauncherLocalActiveWorkRunCount { return 0 }
function Write-LauncherControlLog {
    param([string]$Event, [string]$Message, [string]$Level = "info", [hashtable]$Fields = @{})
}
function Invoke-WebRequest { throw "status endpoint should not be queried when backend is unhealthy." }

if (Test-LauncherRestartActiveWorkBlocked) {
    throw "unhealthy backend should not block recovery restart."
}
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_restart_guard_blocks_when_probe_fails_but_local_active_work_exists(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

$functionAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Test-LauncherRestartActiveWorkBlocked"
}, $true)
foreach ($functionName in @(
    "Get-ObjectPropertyValue",
    "Test-LauncherWorkRunStatusBlocksLifecycle",
    "Get-LauncherLocalActiveWorkRunCount",
    "Test-LauncherRestartActiveWorkBlocked"
)) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $functionName
    }, $true)
    if ($null -eq $functionAst) {
        throw "$functionName was not found."
    }
    . ([scriptblock]::Create($functionAst.Extent.Text))
}

$script:url = "http://127.0.0.1:8000"
$script:launcherControlUrl = "http://127.0.0.1:8765"
$script:projectDir = Join-Path ([System.IO.Path]::GetTempPath()) ("vibelution-launcher-active-work-" + [guid]::NewGuid().ToString("N"))
$kindDir = Join-Path $script:projectDir ".runtime\\runtime-manager\\work_runs\\chat_turn"
$runDir = Join-Path $kindDir "runs"
New-Item -ItemType Directory -Path $runDir -Force | Out-Null
'{"version":1,"activeRunId":"chat-live","latestRunId":"chat-live"}' |
    Set-Content -LiteralPath (Join-Path $kindDir "index.json") -Encoding utf8
'{"runId":"chat-live","sessionId":"session-live","status":"running","currentPhase":"running"}' |
    Set-Content -LiteralPath (Join-Path $runDir "chat-live.json") -Encoding utf8
$script:notes = @()
$script:events = @()
function Test-WebHealthy { return $true }
function Test-LauncherControlHealthy { return $true }
function Write-Note { param([string]$Message) $script:notes += $Message }
function Write-LauncherControlLog {
    param([string]$Event, [string]$Message, [string]$Level = "info", [hashtable]$Fields = @{})
    $script:events += ,@{ event = $Event; message = $Message; level = $Level; fields = $Fields }
}
function Invoke-WebRequest {
    param([string]$Uri, [int]$TimeoutSec, [switch]$UseBasicParsing)
    throw "status timeout"
}

$blocked = Test-LauncherRestartActiveWorkBlocked
if (-not $blocked) { throw "healthy backend with failed probe and local active work should block restart." }
if ($script:notes[0] -notmatch "有进行中的任务，无法重启 Vibelution") { throw "probe failure block message was not user-readable." }
if ($script:events[0].event -ne "launcher.restart.blocked_active_work") { throw "local active-work block event was not logged." }
if ($script:events[0].fields.active_work_count -ne 1) { throw "local active work count was not logged." }
if ($script:events[0].fields.source -ne "local_work_runs") { throw "local active-work source was not logged." }
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_restart_guard_allows_when_probe_fails_and_local_work_is_clear(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

foreach ($functionName in @(
    "Get-ObjectPropertyValue",
    "Test-LauncherWorkRunStatusBlocksLifecycle",
    "Get-LauncherLocalActiveWorkRunCount",
    "Test-LauncherRestartActiveWorkBlocked"
)) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $functionName
    }, $true)
    if ($null -eq $functionAst) {
        throw "$functionName was not found."
    }
    . ([scriptblock]::Create($functionAst.Extent.Text))
}

$script:url = "http://127.0.0.1:8000"
$script:launcherControlUrl = "http://127.0.0.1:8765"
$script:projectDir = Join-Path ([System.IO.Path]::GetTempPath()) ("vibelution-launcher-clear-work-" + [guid]::NewGuid().ToString("N"))
$runDir = Join-Path $script:projectDir ".runtime\\runtime-manager\\work_runs\\chat_turn\\runs"
New-Item -ItemType Directory -Path $runDir -Force | Out-Null
'{"runId":"chat-done","sessionId":"session-done","status":"completed","currentPhase":"completed","finishedAt":"2026-06-05T04:00:00Z"}' |
    Set-Content -LiteralPath (Join-Path $runDir "chat-done.json") -Encoding utf8
'{"runId":"chat-waiting","sessionId":"session-waiting","status":"needs_continue","currentPhase":"needs_continue","finishedAt":"2026-06-05T04:01:00Z"}' |
    Set-Content -LiteralPath (Join-Path $runDir "chat-waiting.json") -Encoding utf8
$script:notes = @()
$script:events = @()
function Test-WebHealthy { return $true }
function Test-LauncherControlHealthy { return $true }
function Write-Note { param([string]$Message) $script:notes += $Message }
function Write-LauncherControlLog {
    param([string]$Event, [string]$Message, [string]$Level = "info", [hashtable]$Fields = @{})
    $script:events += ,@{ event = $Event; message = $Message; level = $Level; fields = $Fields }
}
function Invoke-WebRequest {
    param([string]$Uri, [int]$TimeoutSec, [switch]$UseBasicParsing)
    throw "status timeout"
}

$blocked = Test-LauncherRestartActiveWorkBlocked
if ($blocked) { throw "healthy backend with failed probe but clear local work should not block restart." }
if ($script:notes.Count -ne 0) { throw "clear local work should not show active-work block note." }
if ($script:events[0].event -ne "launcher.restart.active_work_local_clear") { throw "local clear event was not logged." }
if ($script:events[0].fields.source -ne "local_work_runs") { throw "local clear source was not logged." }
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_restart_guard_ignores_stale_source_collection_local_snapshot(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

foreach ($functionName in @(
    "Get-ObjectPropertyValue",
    "Test-LauncherWorkRunStatusBlocksLifecycle",
    "Get-LauncherLocalActiveWorkRunCount",
    "Test-LauncherRestartActiveWorkBlocked"
)) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $functionName
    }, $true)
    if ($null -eq $functionAst) {
        throw "$functionName was not found."
    }
    . ([scriptblock]::Create($functionAst.Extent.Text))
}

$script:url = "http://127.0.0.1:8000"
$script:launcherControlUrl = "http://127.0.0.1:8765"
$script:projectDir = Join-Path ([System.IO.Path]::GetTempPath()) ("vibelution-launcher-stale-source-work-" + [guid]::NewGuid().ToString("N"))
$kindDir = Join-Path $script:projectDir ".runtime\\runtime-manager\\work_runs\\source_collection_run"
$runDir = Join-Path $kindDir "runs"
New-Item -ItemType Directory -Path $runDir -Force | Out-Null
'{"version":1,"activeRunId":"dprun-stale-source","latestRunId":"dprun-stale-source","updatedAt":"2026-07-02T13:08:46Z"}' |
    Set-Content -LiteralPath (Join-Path $kindDir "index.json") -Encoding utf8
'{"runId":"dprun-stale-source","runKind":"source_collection_run","status":"running","currentPhase":"searching","startedAt":"2026-07-02T13:08:46Z","updatedAt":"2026-07-02T21:08:46Z"}' |
    Set-Content -LiteralPath (Join-Path $runDir "dprun-stale-source.json") -Encoding utf8
$script:notes = @()
$script:events = @()
function Test-WebHealthy { return $true }
function Test-LauncherControlHealthy { return $true }
function Write-Note { param([string]$Message) $script:notes += $Message }
function Write-LauncherControlLog {
    param([string]$Event, [string]$Message, [string]$Level = "info", [hashtable]$Fields = @{})
    $script:events += ,@{ event = $Event; message = $Message; level = $Level; fields = $Fields }
}
function Invoke-WebRequest {
    param([string]$Uri, [int]$TimeoutSec, [switch]$UseBasicParsing)
    throw "status timeout"
}

$blocked = Test-LauncherRestartActiveWorkBlocked
if ($blocked) { throw "stale source_collection_run local snapshot should not block restart when launcher status probes fail." }
if ($script:notes.Count -ne 0) { throw "stale source_collection_run should not show active-work block note." }
if ($script:events[0].event -ne "launcher.restart.active_work_local_clear") { throw "local clear event was not logged." }
if ($script:events[0].fields.source -ne "local_work_runs") { throw "local clear source was not logged." }
Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_backend_candidates_include_tracked_launch_and_listener_pids(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

foreach ($name in @(
    "ConvertTo-LauncherComparableText",
    "Test-CommandLineMentionsWorkbenchScript",
    "Test-CommandLineLooksLikeManagedBackend",
    "Test-ProcessLooksLikeManagedBackend",
    "Get-ObjectPropertyValue",
    "Get-ManagedBackendCandidatePids"
)) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $name
    }, $true)
    if ($null -eq $functionAst) {
        throw "$name was not found."
    }
    . ([scriptblock]::Create($functionAst.Extent.Text))
}

$script:port = 8000
$script:healthy = $true
$script:fullScanCalls = 0
function Get-State {
    return [pscustomobject]@{
        backendPid = 6544
        backendLaunchPid = 6544
        port = 8000
    }
}
function Test-ProcessAlive {
    param([int]$ProcessId)
    return $ProcessId -eq 6544
}
function Get-ListeningPid {
    param([int]$Port)
    if ($Port -eq 8000) {
        return 14916
    }
    return $null
}
function Get-CimInstance {
    param([string]$ClassName, [string]$Filter, [string]$ErrorAction)
    if (-not $Filter) {
        $script:fullScanCalls += 1
        throw "Get-ManagedBackendCandidatePids should not run a full process scan when tracked/listener PIDs are enough."
    }
    if ($Filter -match "ProcessId = 14916") {
        return [pscustomobject]@{
            ProcessId = 14916
            CommandLine = "`"C:\\Python312\\python.exe`" scripts/web_workbench.py --host 127.0.0.1 --port 8000 --no-browser --managed-by-launcher"
        }
    }
    if ($Filter -match "ProcessId = 6544") {
        return [pscustomobject]@{
            ProcessId = 6544
            CommandLine = "`"C:\\Python312\\python.exe`" scripts/web_workbench.py --host 127.0.0.1 --port 8000 --no-browser --managed-by-launcher"
        }
    }
    return @()
}
function Test-WebHealthy { return [bool]$script:healthy }

$pids = @(Get-ManagedBackendCandidatePids)
if (($pids -join ",") -ne "6544,14916") {
    throw "Expected tracked launch and listener PIDs, got $($pids -join ',')."
}
if ($script:fullScanCalls -ne 0) {
    throw "Expected no full process scan, got $script:fullScanCalls."
}

Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_backend_candidates_fallback_scan_when_no_tracked_or_listener_pid(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

foreach ($name in @(
    "ConvertTo-LauncherComparableText",
    "Test-CommandLineMentionsWorkbenchScript",
    "Test-CommandLineLooksLikeManagedBackend",
    "Test-ProcessLooksLikeManagedBackend",
    "Get-ObjectPropertyValue",
    "Get-ManagedBackendCandidatePids"
)) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $name
    }, $true)
    if ($null -eq $functionAst) {
        throw "$name was not found."
    }
    . ([scriptblock]::Create($functionAst.Extent.Text))
}

$script:port = 8000
$script:fullScanCalls = 0
function Get-State {
    return [pscustomobject]@{
        backendPid = 0
        backendLaunchPid = 0
        port = 8000
    }
}
function Test-ProcessAlive { param([int]$ProcessId) return $false }
function Get-ListeningPid { param([int]$Port) return $null }
function Get-CimInstance {
    param([string]$ClassName, [string]$Filter, [string]$ErrorAction)
    if (-not $Filter) {
        $script:fullScanCalls += 1
        return @(
            [pscustomobject]@{
                ProcessId = 2112
                CommandLine = "`"C:\\Python312\\python.exe`" scripts/web_workbench.py --host 127.0.0.1 --port 8000 --no-browser --managed-by-launcher"
            },
            [pscustomobject]@{
                ProcessId = 9000
                CommandLine = "`"C:\\Python312\\python.exe`" scripts/web_workbench.py --host 127.0.0.1 --port 9000 --no-browser --managed-by-launcher"
            }
        )
    }
    return @()
}

$pids = @(Get-ManagedBackendCandidatePids)
if (($pids -join ",") -ne "2112") {
    throw "Expected fallback scan to find only the matching managed backend, got $($pids -join ',')."
}
if ($script:fullScanCalls -ne 1) {
    throw "Expected one fallback full scan, got $script:fullScanCalls."
}

Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_backend_candidates_ignore_reused_tracked_pid(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

foreach ($name in @(
    "ConvertTo-LauncherComparableText",
    "Test-CommandLineMentionsWorkbenchScript",
    "Test-CommandLineLooksLikeManagedBackend",
    "Test-ProcessLooksLikeManagedBackend",
    "Get-ObjectPropertyValue",
    "Get-ManagedBackendCandidatePids"
)) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $name
    }, $true)
    if ($null -eq $functionAst) {
        throw "$name was not found."
    }
    . ([scriptblock]::Create($functionAst.Extent.Text))
}

$script:port = 8000
function Get-State {
    return [pscustomobject]@{
        backendPid = 384
        backendLaunchPid = 34848
        port = 8000
    }
}
function Test-ProcessAlive {
    param([int]$ProcessId)
    return $ProcessId -in @(384, 34848)
}
function Get-ListeningPid { param([int]$Port) return $null }
function Get-CimInstance {
    param([string]$ClassName, [string]$Filter, [string]$ErrorAction)
    if ($Filter -match "ProcessId = 384") {
        return [pscustomobject]@{
            ProcessId = 384
            Name = "svchost.exe"
            CommandLine = ""
        }
    }
    if ($Filter -match "ProcessId = 34848") {
        return [pscustomobject]@{
            ProcessId = 34848
            Name = "pythonw.exe"
            CommandLine = "`"C:\\Python312\\pythonw.exe`" scripts/web_workbench.py --host 127.0.0.1 --port 8000 --no-browser --managed-by-launcher"
        }
    }
    return @()
}

$pids = @(Get-ManagedBackendCandidatePids)
if (($pids -join ",") -ne "34848") {
    throw "Expected reused tracked PID to be ignored, got $($pids -join ',')."
}

Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_backend_candidates_ignore_missing_listener_process_under_strict_mode(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

foreach ($name in @(
    "ConvertTo-LauncherComparableText",
    "Test-CommandLineMentionsWorkbenchScript",
    "Test-CommandLineLooksLikeManagedBackend",
    "Test-ProcessLooksLikeManagedBackend",
    "Get-ObjectPropertyValue",
    "Get-ManagedBackendCandidatePids"
)) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $name
    }, $true)
    if ($null -eq $functionAst) {
        throw "$name was not found."
    }
    . ([scriptblock]::Create($functionAst.Extent.Text))
}

$script:port = 8000
function Get-State {
    return [pscustomobject]@{
        backendPid = 0
        backendLaunchPid = 0
        port = 8000
    }
}
function Test-ProcessAlive { param([int]$ProcessId) return $false }
function Get-ListeningPid {
    param([int]$Port)
    if ($Port -eq 8000) {
        return 14916
    }
    return $null
}
function Get-CimInstance {
    param([string]$ClassName, [string]$Filter, [string]$ErrorAction)
    return @()
}

$pids = @(Get-ManagedBackendCandidatePids)
if ($pids.Count -ne 0) {
    throw "Expected missing listener process to stay unadopted, got $($pids -join ',')."
}

Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_backend_candidates_do_not_adopt_unmarked_manual_listener(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

foreach ($name in @(
    "ConvertTo-LauncherComparableText",
    "Test-CommandLineMentionsWorkbenchScript",
    "Test-CommandLineLooksLikeManagedBackend",
    "Test-ProcessLooksLikeManagedBackend",
    "Get-ObjectPropertyValue",
    "Get-ManagedBackendCandidatePids"
)) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $name
    }, $true)
    if ($null -eq $functionAst) {
        throw "$name was not found."
    }
    . ([scriptblock]::Create($functionAst.Extent.Text))
}

$script:port = 8000
function Get-State {
    return [pscustomobject]@{
        backendPid = 0
        backendLaunchPid = 0
        port = 8000
    }
}
function Test-ProcessAlive { param([int]$ProcessId) return $false }
function Get-ListeningPid {
    param([int]$Port)
    if ($Port -eq 8000) {
        return 14916
    }
    return $null
}
function Get-CimInstance {
    param([string]$ClassName, [string]$Filter, [string]$ErrorAction)
    if ($Filter -match "ProcessId = 14916") {
        return [pscustomobject]@{
            ProcessId = 14916
            CommandLine = "`"C:\\Python312\\python.exe`" scripts/web_workbench.py --host 127.0.0.1 --port 8000 --no-browser"
        }
    }
    return @()
}
function Test-WebHealthy { return $true }

$pids = @(Get-ManagedBackendCandidatePids)
if ($pids.Count -ne 0) {
    throw "Expected unmarked manual backend listener to stay unadopted, got $($pids -join ',')."
}

Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_managed_browser_launch_keeps_startup_alive_in_background(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

$functionAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Start-ManagedBrowser"
}, $true)
if ($null -eq $functionAst) {
    throw "Start-ManagedBrowser was not found."
}
$startBrowserText = $functionAst.Extent.Text

foreach ($forbidden in @(
    "--disable-background-networking",
    "--disable-background-mode"
)) {
    if ($startBrowserText -match [regex]::Escape($forbidden)) {
        throw "Start-ManagedBrowser still includes startup-blocking flag '$forbidden'."
    }
}

foreach ($required in @(
    "--disable-background-timer-throttling",
    "--disable-renderer-backgrounding",
    "CalculateNativeWinOcclusion",
    "IntensiveWakeUpThrottling",
    "launch_flags"
)) {
    if ($startBrowserText -notmatch [regex]::Escape($required)) {
        throw "Start-ManagedBrowser is missing background startup flag or log field '$required'."
    }
}

Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_browser_open_skips_startup_blocking_process_memory_sample(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

function Get-FunctionText {
    param([string]$Name)
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $Name
    }, $true)
    if ($null -eq $functionAst) {
        throw "$Name was not found."
    }
    return $functionAst.Extent.Text
}

$startBrowserText = Get-FunctionText -Name "Start-ManagedBrowser"
$skipText = Get-FunctionText -Name "Write-ManagedBrowserProcessMemoryStartupSkip"

if ($startBrowserText -match [regex]::Escape('Write-ManagedBrowserProcessMemorySnapshot -Reason "browser_opened"')) {
    throw "Start-ManagedBrowser still samples browser process memory on the startup ready path."
}
if ($startBrowserText -notmatch [regex]::Escape('Write-ManagedBrowserProcessMemoryStartupSkip -Reason "browser_opened"')) {
    throw "Start-ManagedBrowser does not record the startup process-memory skip event."
}
foreach ($required in @(
    "browser.process_memory.sample_skipped_startup",
    "startup_blocking_sample_skipped",
    "startup_critical_path"
)) {
    if ($skipText -notmatch [regex]::Escape($required)) {
        throw "Browser process memory startup skip logging is missing '$required'."
    }
}

Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_focus_and_stop_paths_reuse_known_fast_results(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        r"""
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

function Get-FunctionText {
    param([string]$Name)
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $Name
    }, $true)
    if ($null -eq $functionAst) {
        throw "$Name was not found."
    }
    return $functionAst.Extent.Text
}

$focusText = Get-FunctionText -Name "Focus-ManagedBrowserWindow"
$startText = Get-FunctionText -Name "Start-ManagedSession"
$headlessText = Get-FunctionText -Name "Complete-HeadlessSessionWithBrowser"
$adoptText = Get-FunctionText -Name "Adopt-Or-FocusSession"
$stopBrowserText = Get-FunctionText -Name "Stop-ManagedBrowserProcesses"
$stopSessionText = Get-FunctionText -Name "Stop-ManagedSession"

if ($focusText -notmatch 'KnownWindowPid' -or $focusText -notmatch 'Get-Process\s+-Id\s+\$KnownWindowPid') {
    throw "Focus-ManagedBrowserWindow should try the known window PID before scanning the browser profile."
}
if ($startText -notmatch '-KnownWindowPid\s+\$browserInfo\.WindowPid') {
    throw "Start-ManagedSession should focus the newly opened browser by known window PID."
}
if ($headlessText -notmatch '-KnownWindowPid\s+\$browserInfo\.WindowPid') {
    throw "Complete-HeadlessSessionWithBrowser should focus the newly opened browser by known window PID."
}
if ($adoptText -notmatch '-KnownWindowPid\s+\$Snapshot\.BrowserWindowPid') {
    throw "Adopt-Or-FocusSession should focus an existing browser by the snapshot window PID."
}
if ($stopBrowserText -notmatch '\[switch\]\$PassThru' -or $stopSessionText -notmatch 'Stop-ManagedBrowserProcesses.+-PassThru') {
    throw "Stop-ManagedSession should reuse Stop-ManagedBrowserProcesses completion instead of always scanning again."
}
if ($stopSessionText -notmatch 'if \(\$browserStoppedByStopper\)') {
    throw "Stop-ManagedSession should skip the follow-up browser wait when the stopper already confirmed closure."
}

Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_web_health_prefers_root_ready_probe_then_health_fallback(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

$functionAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Test-WebHealthy"
}, $true)
if ($null -eq $functionAst) {
    throw "Test-WebHealthy was not found."
}
. ([scriptblock]::Create($functionAst.Extent.Text))

$script:backendReadyUrl = "http://127.0.0.1:8000"
$script:healthUrl = "http://127.0.0.1:8000/api/health"
$script:probes = @()
$script:failRootProbe = $false
function Invoke-WebRequest {
    param(
        [switch]$UseBasicParsing,
        [string]$Uri,
        [int]$TimeoutSec
    )
    $script:probes += [pscustomobject]@{
        Uri = $Uri
        TimeoutSec = $TimeoutSec
    }
    if ($Uri -eq $script:backendReadyUrl -and $script:failRootProbe) {
        throw "root probe unavailable"
    }
    return [pscustomobject]@{ StatusCode = 200 }
}

if (-not (Test-WebHealthy)) {
    throw "Expected root ready probe to be healthy."
}
if ($script:probes.Count -ne 1 -or $script:probes[0].Uri -ne $script:backendReadyUrl) {
    throw "Expected Test-WebHealthy to probe the root ready URL first."
}
if ($script:probes[0].TimeoutSec -ne 1) {
    throw "Expected root ready probe timeout to stay at one second."
}

$script:probes = @()
$script:failRootProbe = $true
if (-not (Test-WebHealthy)) {
    throw "Expected /api/health fallback to report healthy."
}
if ($script:probes.Count -ne 2) {
    throw "Expected root probe plus /api/health fallback, got $($script:probes.Count)."
}
if ($script:probes[0].Uri -ne $script:backendReadyUrl -or $script:probes[1].Uri -ne $script:healthUrl) {
    throw "Expected root ready probe before /api/health fallback."
}

Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_browser_candidates_include_tracked_launch_window_and_profile_pids(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

$functionAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Get-ManagedBrowserCandidatePids"
}, $true)
if ($null -eq $functionAst) {
    throw "Get-ManagedBrowserCandidatePids was not found."
}
. ([scriptblock]::Create($functionAst.Extent.Text))

$script:browserProfileDir = "C:\\Users\\17533\\Desktop\\Vibelution\\.runtime\\launcher\\edge-app-profile"
function Ensure-Directories { }
function Get-State {
    return [pscustomobject]@{
        browserWindowPid = 40736
        browserLaunchPid = 40736
    }
}
function Test-ProcessAlive {
    param([int]$ProcessId)
    return $ProcessId -in @(40736, 36192)
}
function Get-CimInstance {
    param([string]$ClassName, [string]$Filter, [string]$ErrorAction)
    return @(
        [pscustomobject]@{
            ProcessId = 40736
            Name = "msedge.exe"
            CommandLine = "`"C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe`" --user-data-dir=C:\\Users\\17533\\Desktop\\Vibelution\\.runtime\\launcher\\edge-app-profile --app=http://127.0.0.1:8000"
        },
        [pscustomobject]@{
            ProcessId = 36192
            Name = "msedge.exe"
            CommandLine = "`"C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe`" --type=renderer --user-data-dir=C:\\Users\\17533\\Desktop\\Vibelution\\.runtime\\launcher\\edge-app-profile"
        }
    )
}

$pids = @(Get-ManagedBrowserCandidatePids)
if (($pids -join ",") -ne "36192,40736") {
    throw "Expected tracked browser and profile PIDs, got $($pids -join ',')."
}

Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_stop_backend_kills_remaining_managed_port_owner(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

foreach ($functionName in @(
    "ConvertTo-LauncherComparableText",
    "Test-NormalizedTextContainsPathSegment",
    "Test-TextReferencesProjectPath",
    "Test-CommandLineMentionsWorkbenchScript",
    "Test-CommandLineUsesRelativeWorkbenchScript",
    "Get-LauncherProcessPropertyValue",
    "Test-CommandLineLooksLikeRepoWorkbenchBackend",
    "Test-ProcessLooksLikeRepoWorkbenchBackend",
    "Test-CommandLineLooksLikeManagedBackend",
    "Stop-ManagedBackendProcesses"
)) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $functionName
    }, $true)
    if ($null -eq $functionAst) {
        throw "$functionName was not found."
    }
    . ([scriptblock]::Create($functionAst.Extent.Text))
}

$script:port = 8000
$script:projectDir = "C:\\Users\\17533\\Desktop\\Vibelution"
$script:stopCalls = @()
$script:listenerCalls = 0
function Get-ManagedBackendCandidatePids { return @(6544) }
function Stop-ProcessesById {
    param([int[]]$ProcessIds)
    $script:stopCalls += ,@($ProcessIds)
}
function Write-LauncherControlLog {
    param([string]$Event, [string]$Message, [string]$Level = "info", [hashtable]$Fields = @{})
}
function Get-State {
    return [pscustomobject]@{
        port = 8000
        backendPid = 14916
        backendLaunchPid = 6544
    }
}
function Get-ListeningPid {
    param([int]$Port)
    $script:listenerCalls += 1
    if ($script:listenerCalls -eq 1) {
        return 14916
    }
    return $null
}
function Get-CimInstance {
    param([string]$ClassName, [string]$Filter, [string]$ErrorAction)
    if ($Filter -match "ProcessId = 14916") {
        return [pscustomobject]@{
            ProcessId = 14916
            CommandLine = "`"C:\\Python312\\python.exe`" scripts/web_workbench.py --host 127.0.0.1 --port 8000 --no-browser --managed-by-launcher"
        }
    }
    return @()
}
function Test-WebHealthy { return $true }

Stop-ManagedBackendProcesses

$payload = @{
    calls = @($script:stopCalls | ForEach-Object { @($_) })
} | ConvertTo-Json -Depth 8 -Compress
Write-Output $payload
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["calls"] == [6544, 14916]


def test_launcher_stop_processes_preserves_protected_runtime_manager_child(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

$functionAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Stop-ProcessesById"
}, $true)
if ($null -eq $functionAst) {
    throw "Stop-ProcessesById was not found."
}
. ([scriptblock]::Create($functionAst.Extent.Text))

$script:selfProcessId = 111
$script:protectedProcessIds = @(29960, 46992)
$script:stopped = @()
$script:controlEvents = @()
$script:fullChildMapCalls = 0
function Get-CimInstance {
    param([string]$ClassName, [string]$Filter, [string]$ErrorAction)
    if (-not $Filter) {
        $script:fullChildMapCalls += 1
        throw "Stop-ProcessesById should not build a full process child map for a small targeted stop."
    }
    if ($Filter -match "ParentProcessId = 8976") {
        return @(
            [pscustomobject]@{ ProcessId = 31096 },
            [pscustomobject]@{ ProcessId = 29960 }
        )
    }
    if ($Filter -match "ParentProcessId = 29960") {
        return @([pscustomobject]@{ ProcessId = 46992 })
    }
    return @()
}
function Stop-Process {
    param([int]$Id, [switch]$Force, [string]$ErrorAction)
    $script:stopped += $Id
}
function Write-LauncherControlLog {
    param([string]$Event, [string]$Message, [string]$Level = "info", [hashtable]$Fields = @{})
    $script:controlEvents += ,@{ event = $Event; fields = $Fields }
}

Stop-ProcessesById -ProcessIds @(8976)

$payload = @{
    stopped = @($script:stopped)
    skipped = @($script:controlEvents | Where-Object { $_.event -eq "launcher.process.stop.skipped_protected" } | ForEach-Object { $_.fields.pid })
    fullChildMapCalls = $script:fullChildMapCalls
} | ConvertTo-Json -Depth 8 -Compress
Write-Output $payload
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["stopped"] == [31096, 8976]
    assert payload["skipped"] == [29960]
    assert payload["fullChildMapCalls"] == 0


def test_launcher_stop_browser_processes_retry_until_profile_processes_exit(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

foreach ($functionName in @("Wait-ForManagedBrowserPidsGone", "Stop-ManagedBrowserProcesses")) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $functionName
    }, $true)
    if ($null -eq $functionAst) {
        throw "$functionName was not found."
    }
    . ([scriptblock]::Create($functionAst.Extent.Text))
}

$script:browserPids = @(40736, 36192)
$script:stopCalls = @()
$script:closeCalls = 0
$script:logEvents = @()
$script:pidProbeCalls = 0

$windowProcess = [pscustomobject]@{
    Id = 40736
    MainWindowHandle = 2821910
}
$windowProcess | Add-Member -MemberType ScriptMethod -Name CloseMainWindow -Value {
    $script:closeCalls += 1
    return $true
}

function Get-ManagedBrowserWindowProcesses {
    return @($windowProcess)
}
function Get-ManagedBrowserPids {
    $script:pidProbeCalls += 1
    return @($script:browserPids)
}
function Stop-ProcessesById {
    param([int[]]$ProcessIds)
    $script:stopCalls += ,(($ProcessIds -join ","))
    if ($script:stopCalls.Count -eq 1) {
        $script:browserPids = @($script:browserPids | Where-Object { $_ -ne 40736 })
    } else {
        $script:browserPids = @()
    }
}
function Write-LauncherControlLog {
    param([string]$Event, [string]$Message, [string]$Level = "info", [hashtable]$Fields = @{})
    $script:logEvents += $Event
}
function Start-Sleep { param([int]$Milliseconds, [int]$Seconds) }

Stop-ManagedBrowserProcesses

$payload = @{
    closeCalls = $script:closeCalls
    stopCalls = @($script:stopCalls)
    logEvents = @($script:logEvents)
    remaining = @($script:browserPids)
    pidProbeCalls = $script:pidProbeCalls
} | ConvertTo-Json -Depth 8 -Compress
Write-Output $payload
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["closeCalls"] == 1
    assert payload["stopCalls"] == ["40736,36192", "36192"]
    assert "launcher.browser.stop.retry" in payload["logEvents"]
    assert "launcher.browser.stop.incomplete" not in payload["logEvents"]
    assert payload["remaining"] == []
    assert payload["pidProbeCalls"] >= 3


def test_launcher_stop_session_closes_browser_when_backend_stop_is_unconfirmed(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

foreach ($functionName in @(
    "Set-RuntimeSceneContextFromStateObject",
    "Stop-ManagedSession"
)) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $functionName
    }, $true)
    if ($null -eq $functionAst) {
        throw "$functionName was not found."
    }
    . ([scriptblock]::Create($functionAst.Extent.Text))
}

$script:port = 8000
$script:selfProcessId = 123
$script:currentRuntimeSceneId = ""
$script:workbenchBrowserProfileDir = "C:\\Users\\17533\\Desktop\\Vibelution\\.runtime\\launcher\\workbench-app-profile"
$script:browserStopCalls = 0
$script:browserWaitCalls = 0
$script:browserStopProfiles = @()
$script:browserWaitProfiles = @()
$script:removedState = $false
$script:notes = @()
$script:controlEvents = @()

function Get-ObjectPropertyValue {
    param([object]$Object, [string]$Name, $Default = $null)
    if ($null -eq $Object) { return $Default }
    $prop = $Object.PSObject.Properties[$Name]
    if ($null -eq $prop) { return $Default }
    if ($null -eq $prop.Value) { return $Default }
    return $prop.Value
}
function Get-SessionSnapshot {
    return [pscustomobject]@{
        BackendPids = @(6544)
        BackendPid = 6544
        BrowserPids = @(40736)
        BrowserWindowCount = 1
        State = [pscustomobject]@{
            supervisorPid = 7777
            runtimeSceneId = ""
            runtimeSceneDir = ""
        }
    }
}
function Stop-ManagedBackendProcesses {
    return [pscustomobject]@{
        CandidatePids = @(6544)
        RemainingPortPid = 14916
        RemainingLooksManaged = $false
        RemainingHealthy = $false
        PortOwnerStopped = $false
    }
}
function Wait-ForPortClosed {
    param([int]$Port)
    return $false
}
function Stop-ProcessesById { param([int[]]$ProcessIds) }
function Stop-ManagedBrowserProcesses {
    param([string]$ProfileDir = "", [string]$Role = "workbench", [switch]$PassThru)
    $script:browserStopCalls += 1
    $script:browserStopProfiles += ,@{ profileDir = $ProfileDir; role = $Role }
    if ($PassThru) { return $true }
}
function Wait-ForBrowserStopped {
    param([int]$TimeoutSeconds, [string]$ProfileDir = "", [string]$Role = "workbench")
    $script:browserWaitCalls += 1
    $script:browserWaitProfiles += ,@{ profileDir = $ProfileDir; role = $Role }
    return $true
}
function Get-ManagedSessionClosureSnapshot {
    return [pscustomobject]@{
        BackendStopped = $false
        BrowserStopped = $true
        ManagerClosed = $false
        BackendPids = @(6544)
        BackendHealthy = $false
        BrowserPids = @()
        BrowserWindowCount = 0
        PortOwnerPid = 14916
        DesiredState = "closed"
        ObservedState = "open"
        Phase = "closing"
        FailureMessage = ""
    }
}
function Test-ManagedSessionClosureSucceeded {
    param([pscustomobject]$Closure, [bool]$RequireManagerClosed = $true)
    return $false
}
function Write-ManagedSessionClosureRecord {
    param([pscustomobject]$Closure, [string]$Reason, [string]$Source, [bool]$Success, [hashtable]$Timings = @{})
}
function Remove-State { $script:removedState = $true }
function Get-ListeningPid { param([int]$Port) return 14916 }
function Write-LauncherControlLog {
    param([string]$Event, [string]$Message, [string]$Level = "info", [hashtable]$Fields = @{})
    $script:controlEvents += ,@{ event = $Event; level = $Level; fields = $Fields }
}
function Write-Note {
    param([string]$Message)
    $script:notes += $Message
}

$errorMessage = ""
try {
    Stop-ManagedSession -Reason "web_close_button"
} catch {
    $errorMessage = $_.Exception.Message
}

$payload = @{
    browserStopCalls = $script:browserStopCalls
    browserWaitCalls = $script:browserWaitCalls
    browserStopProfiles = @($script:browserStopProfiles)
    browserWaitProfiles = @($script:browserWaitProfiles)
    removedState = $script:removedState
    notes = @($script:notes)
    controlEvents = @($script:controlEvents)
    errorMessage = $errorMessage
} | ConvertTo-Json -Depth 10 -Compress
Write-Output $payload
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["browserStopCalls"] == 1
    assert payload["browserWaitCalls"] == 0
    assert payload["browserStopProfiles"][0]["role"] == "workbench"
    assert payload["browserStopProfiles"][0]["profileDir"].endswith("workbench-app-profile")
    assert payload["removedState"] is False
    assert "backend did not stop" in payload["errorMessage"]
    assert "browser did not stop" not in payload["errorMessage"]
    assert "launcher.browser.stop.with_backend_unconfirmed" in [item["event"] for item in payload["controlEvents"]]
    assert any("browser was closed" in note for note in payload["notes"])


def test_launcher_stop_session_records_shutdown_timings(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

foreach ($functionName in @(
    "Set-RuntimeSceneContextFromStateObject",
    "Stop-ManagedSession"
)) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $functionName
    }, $true)
    if ($null -eq $functionAst) {
        throw "$functionName was not found."
    }
    . ([scriptblock]::Create($functionAst.Extent.Text))
}

$script:port = 8000
$script:selfProcessId = 123
$script:currentRuntimeSceneId = "scene-1"
$script:workbenchBrowserProfileDir = "C:\\Users\\17533\\Desktop\\Vibelution\\.runtime\\launcher\\workbench-app-profile"
$script:runtimeEvents = @()
$script:controlEvents = @()
$script:closureRecords = @()
$script:removedState = $false
$script:restored = $false

function Get-SessionSnapshot {
    return [pscustomobject]@{
        BackendPids = @(6544)
        BackendPid = 6544
        BrowserPids = @(40736)
        BrowserWindowCount = 1
        State = [pscustomobject]@{
            supervisorPid = 7777
            runtimeSceneId = "scene-1"
            runtimeSceneDir = "C:\\runtime\\scene-1"
        }
    }
}
function Set-CurrentRuntimeSceneContext { param([string]$SceneId, [string]$SceneDir) }
function Write-RuntimeSceneEvent {
    param(
        [string]$Component,
        [string]$Phase,
        [string]$EventCode,
        [string]$Message,
        [string]$Level = "info",
        [string]$Outcome = "",
        [hashtable]$Fields = @{}
    )
    $script:runtimeEvents += ,@{ event = $EventCode; level = $Level; outcome = $Outcome; fields = $Fields }
}
function Update-RuntimeSceneManifest { param([hashtable]$Changes) }
function Stop-ManagedBackendProcesses {
    Start-Sleep -Milliseconds 2
    return [pscustomobject]@{
        CandidatePids = @(6544)
        RemainingPortPid = $null
        RemainingLooksManaged = $false
        RemainingHealthy = $false
        PortOwnerStopped = $true
    }
}
function Wait-ForPortClosed {
    param([int]$Port)
    Start-Sleep -Milliseconds 2
    return $true
}
function Stop-ProcessesById {
    param([int[]]$ProcessIds)
    Start-Sleep -Milliseconds 2
}
function Stop-ManagedBrowserProcesses {
    param([string]$ProfileDir = "", [string]$Role = "workbench", [switch]$PassThru)
    Start-Sleep -Milliseconds 2
    if ($PassThru) { return $true }
}
function Wait-ForBrowserStopped {
    param([int]$TimeoutSeconds, [string]$ProfileDir = "", [string]$Role = "workbench")
    Start-Sleep -Milliseconds 2
    return $true
}
function Get-ManagedSessionClosureSnapshot {
    Start-Sleep -Milliseconds 2
    return [pscustomobject]@{
        BackendStopped = $true
        BrowserStopped = $true
        ManagerClosed = $false
        BackendPids = @()
        BackendHealthy = $false
        BrowserPids = @()
        BrowserWindowCount = 0
        PortOwnerPid = $null
        DesiredState = "closed"
        ObservedState = "closed"
        Phase = "steady"
        FailureMessage = ""
    }
}
function Test-ManagedSessionClosureSucceeded {
    param([pscustomobject]$Closure, [bool]$RequireManagerClosed = $true)
    return $true
}
function Write-ManagedSessionClosureRecord {
    param([pscustomobject]$Closure, [string]$Reason, [string]$Source, [bool]$Success, [hashtable]$Timings = @{})
    $script:closureRecords += ,@{ reason = $Reason; source = $Source; success = $Success; timings = $Timings }
}
function Restore-LauncherControlStateAfterWorkbenchStop {
    param($PreviousState)
    $script:restored = $true
    return $true
}
function Remove-State { $script:removedState = $true }
function Write-LauncherControlLog {
    param([string]$Event, [string]$Message, [string]$Level = "info", [hashtable]$Fields = @{})
    $script:controlEvents += ,@{ event = $Event; level = $Level; fields = $Fields }
}
function Write-Note { param([string]$Message) }

Stop-ManagedSession -Reason "web_close_button"

$stoppedEvent = $script:runtimeEvents | Where-Object { $_.event -eq "runtime.scene.stopped" } | Select-Object -First 1
$payload = @{
    stoppedTimings = $stoppedEvent.fields.timings_ms
    closureTimings = $script:closureRecords[0].timings
    restored = $script:restored
    removedState = $script:removedState
} | ConvertTo-Json -Depth 10 -Compress
Write-Output $payload
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    stopped_timings = payload["stoppedTimings"]
    closure_timings = payload["closureTimings"]
    for key in [
        "total_ms",
        "backend_stop_ms",
        "port_wait_ms",
        "supervisor_stop_ms",
        "browser_stop_ms",
        "browser_wait_ms",
        "closure_snapshot_ms",
    ]:
        assert key in stopped_timings
        assert key in closure_timings
        assert isinstance(stopped_timings[key], int)
        assert isinstance(closure_timings[key], int)
    assert stopped_timings["total_ms"] >= stopped_timings["backend_stop_ms"]
    assert closure_timings["total_ms"] == stopped_timings["total_ms"]
    assert payload["restored"] is True
    assert payload["removedState"] is False


def test_launcher_stop_backend_logs_traceable_candidates_and_port_owner(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

foreach ($functionName in @(
    "ConvertTo-LauncherComparableText",
    "Test-NormalizedTextContainsPathSegment",
    "Test-TextReferencesProjectPath",
    "Test-CommandLineMentionsWorkbenchScript",
    "Test-CommandLineUsesRelativeWorkbenchScript",
    "Get-LauncherProcessPropertyValue",
    "Test-CommandLineLooksLikeRepoWorkbenchBackend",
    "Test-ProcessLooksLikeRepoWorkbenchBackend",
    "Test-CommandLineLooksLikeManagedBackend",
    "Stop-ManagedBackendProcesses"
)) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $functionName
    }, $true)
    if ($null -eq $functionAst) {
        throw "$functionName was not found."
    }
    . ([scriptblock]::Create($functionAst.Extent.Text))
}

$script:port = 8000
$script:projectDir = "C:\\Users\\17533\\Desktop\\Vibelution"
$script:controlEvents = @()
function Write-LauncherControlLog {
    param([string]$Event, [string]$Message, [string]$Level = "info", [hashtable]$Fields = @{})
    $script:controlEvents += ,@{ event = $Event; level = $Level; fields = $Fields }
}
function Get-ManagedBackendCandidatePids { return @(6544) }
function Stop-ProcessesById { param([int[]]$ProcessIds) }
function Get-State { return [pscustomobject]@{ port = 8000 } }
function Get-ListeningPid { param([int]$Port) return 14916 }
function Get-CimInstance {
    param([string]$ClassName, [string]$Filter, [string]$ErrorAction)
    return [pscustomobject]@{
        ProcessId = 14916
        CommandLine = "`"C:\\Python312\\python.exe`" scripts/web_workbench.py --host 127.0.0.1 --port 8000 --no-browser --managed-by-launcher"
    }
}
function Test-WebHealthy { return $true }

$trace = Stop-ManagedBackendProcesses
$payload = @{
    trace = $trace
    events = @($script:controlEvents)
} | ConvertTo-Json -Depth 8 -Compress
Write-Output $payload
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["trace"]["CandidatePids"] == [6544]
    assert payload["trace"]["RemainingPortPid"] == 14916
    assert payload["trace"]["RemainingLooksManaged"] is True
    assert payload["trace"]["RemainingHealthy"] is True
    assert [item["event"] for item in payload["events"]] == [
        "launcher.backend.stop.requested",
        "launcher.backend.stop.port_owner_detected",
    ]
    assert payload["events"][1]["level"] == "warning"


def test_launcher_stop_backend_cleans_repo_local_unmarked_residual_port_owner(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

foreach ($functionName in @(
    "ConvertTo-LauncherComparableText",
    "Test-NormalizedTextContainsPathSegment",
    "Test-TextReferencesProjectPath",
    "Test-CommandLineMentionsWorkbenchScript",
    "Test-CommandLineUsesRelativeWorkbenchScript",
    "Get-LauncherProcessPropertyValue",
    "Test-CommandLineLooksLikeRepoWorkbenchBackend",
    "Test-ProcessLooksLikeRepoWorkbenchBackend",
    "Test-CommandLineLooksLikeManagedBackend",
    "Stop-ManagedBackendProcesses"
)) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $functionName
    }, $true)
    if ($null -eq $functionAst) {
        throw "$functionName was not found."
    }
    . ([scriptblock]::Create($functionAst.Extent.Text))
}

$script:port = 8000
$script:projectDir = "C:\\Users\\17533\\Desktop\\Vibelution"
$script:controlEvents = @()
$script:stopCalls = @()
$script:listenerCalls = 0
function Write-LauncherControlLog {
    param([string]$Event, [string]$Message, [string]$Level = "info", [hashtable]$Fields = @{})
    $script:controlEvents += ,@{ event = $Event; level = $Level; fields = $Fields }
}
function Get-ManagedBackendCandidatePids { return @() }
function Stop-ProcessesById {
    param([int[]]$ProcessIds)
    $script:stopCalls += ,@($ProcessIds)
}
function Get-State { return [pscustomobject]@{ port = 8000 } }
function Get-ListeningPid {
    param([int]$Port)
    $script:listenerCalls += 1
    if ($script:listenerCalls -eq 1) {
        return 31832
    }
    return $null
}
function Get-CimInstance {
    param([string]$ClassName, [string]$Filter, [string]$ErrorAction)
    if ($Filter -match "ProcessId = 31832") {
        return [pscustomobject]@{
            ProcessId = 31832
            ParentProcessId = 50404
            CommandLine = "`"C:\\Users\\17533\\AppData\\Local\\Programs\\Python\\Python312\\python.exe`" scripts\\web_workbench.py --no-browser"
            ExecutablePath = "C:\\Users\\17533\\AppData\\Local\\Programs\\Python\\Python312\\python.exe"
        }
    }
    if ($Filter -match "ProcessId = 50404") {
        return [pscustomobject]@{
            ProcessId = 50404
            ParentProcessId = 1
            CommandLine = "`"C:\\Users\\17533\\Desktop\\Vibelution\\.venv\\Scripts\\python.exe`" scripts\\web_workbench.py --no-browser"
            ExecutablePath = "C:\\Users\\17533\\Desktop\\Vibelution\\.venv\\Scripts\\python.exe"
        }
    }
    return @()
}
function Test-WebHealthy { return $true }
function Invoke-RepoResidualWorkbenchCleanup {
    param([int[]]$ExcludePids = @())
    return [pscustomobject]@{
        supported = $true
        requested = @()
        terminated = @()
        remaining = @()
    }
}

$trace = Stop-ManagedBackendProcesses
$payload = @{
    trace = $trace
    stopCalls = @($script:stopCalls | ForEach-Object { @($_) })
    events = @($script:controlEvents)
} | ConvertTo-Json -Depth 10 -Compress
Write-Output $payload
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["trace"]["RemainingLooksManaged"] is False
    assert payload["trace"]["RemainingLooksRepoWorkbench"] is True
    assert payload["trace"]["PortOwnerStopped"] is True
    assert payload["trace"]["PortOwnerCleanupReason"] == "repo_workbench_ancestor"
    assert payload["stopCalls"] == [31832]
    assert payload["events"][1]["fields"]["remaining_looks_repo_workbench"] is True
    assert payload["events"][1]["fields"]["port_owner_cleanup_reason"] == "repo_workbench_ancestor"


def test_launcher_wait_for_backend_healthy_uses_fast_http_ready_probe(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

$functionAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Wait-ForBackendHealthy"
}, $true)
if ($null -eq $functionAst) {
    throw "Wait-ForBackendHealthy was not found."
}
. ([scriptblock]::Create($functionAst.Extent.Text))

$script:webHealthyCalls = 0
$script:sleepIntervals = @()
function Get-ManagedBackendLiveness {
    param([int]$TrackedPid = 0)
    throw "Wait-ForBackendHealthy should not run full backend liveness scans."
}
function Test-WebHealthy {
    $script:webHealthyCalls += 1
    return ($script:webHealthyCalls -ge 2)
}
function Start-Sleep {
    param([int]$Milliseconds, [int]$Seconds)
    $script:sleepIntervals += $Milliseconds
}

$healthy = Wait-ForBackendHealthy -ProcessId 1111 -TimeoutSeconds 5
if (-not $healthy) {
    throw "Wait-ForBackendHealthy aborted before the delayed HTTP ready probe."
}
if ($script:webHealthyCalls -ne 2) {
    throw "Expected two HTTP ready probes, got $script:webHealthyCalls."
}
if ($script:sleepIntervals.Count -ne 1 -or $script:sleepIntervals[0] -ne 250) {
    throw "Expected one 250ms wait between ready probes."
}

Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_supervisor_does_not_stop_when_backend_pid_is_reconciled(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

foreach ($functionName in @(
    "Get-ObjectPropertyValue",
    "Wait-ForSupervisorSessionState",
    "Run-SupervisorLoop"
)) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $functionName
    }, $true)
    if ($null -eq $functionAst) {
        throw "$functionName was not found."
    }
    . ([scriptblock]::Create($functionAst.Extent.Text))
}

$script:getStateCalls = 0
$script:stops = @()
$script:controlEvents = @()
function Get-State {
    $script:getStateCalls += 1
    if ($script:getStateCalls -gt 2) {
        return $null
    }
    return [pscustomobject]@{
        sessionId = "session-1"
        backendPid = 1111
        browserManaged = $true
    }
}
function Get-ManagedBackendLiveness {
    param([int]$TrackedPid = 0)
    return [pscustomobject]@{
        Alive = $true
        Healthy = $true
        TrackedPid = $TrackedPid
        TrackedPidAlive = $false
        CandidatePids = @(2222)
    }
}
function Get-ManagedBrowserWindowProcesses {
    return @([pscustomobject]@{ Id = 3333; MainWindowHandle = 1 })
}
function Write-LauncherControlLog {
    param([string]$Event, [string]$Message, [string]$Level = "info", [hashtable]$Fields = @{})
    $script:controlEvents += $Event
}
function Stop-ManagedSession {
    param([string]$Reason = "")
    $script:stops += $Reason
}
function Write-Note { param([string]$Message) }
function Start-Sleep { param([int]$Milliseconds, [int]$Seconds) }

Run-SupervisorLoop -ManagedSessionId "session-1"

$payload = @{
    stops = @($script:stops)
    controlEvents = @($script:controlEvents)
    getStateCalls = $script:getStateCalls
} | ConvertTo-Json -Depth 8 -Compress
Write-Output $payload
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["stops"] == []
    assert payload["getStateCalls"] == 3
    assert "launcher.supervisor.backend_pid.reconciled" in payload["controlEvents"]


def test_launcher_supervisor_waits_for_matching_state_before_monitoring(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

foreach ($functionName in @(
    "Get-ObjectPropertyValue",
    "Wait-ForSupervisorSessionState",
    "Run-SupervisorLoop"
)) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $functionName
    }, $true)
    if ($null -eq $functionAst) {
        throw "$functionName was not found."
    }
    . ([scriptblock]::Create($functionAst.Extent.Text))
}

$script:getStateCalls = 0
$script:stops = @()
$script:controlEvents = @()
function Get-State {
    $script:getStateCalls += 1
    if ($script:getStateCalls -eq 1) {
        return $null
    }
    if ($script:getStateCalls -gt 3) {
        return $null
    }
    return [pscustomobject]@{
        sessionId = "session-1"
        backendPid = 1111
        browserManaged = $true
    }
}
function Get-ManagedBackendLiveness {
    param([int]$TrackedPid = 0)
    return [pscustomobject]@{
        Alive = $true
        Healthy = $true
        TrackedPid = $TrackedPid
        TrackedPidAlive = $true
        CandidatePids = @(1111)
    }
}
function Get-ManagedBrowserWindowProcesses {
    return @([pscustomobject]@{ Id = 3333; MainWindowHandle = 1 })
}
function Write-LauncherControlLog {
    param([string]$Event, [string]$Message, [string]$Level = "info", [hashtable]$Fields = @{})
    $script:controlEvents += $Event
}
function Stop-ManagedSession {
    param([string]$Reason = "")
    $script:stops += $Reason
}
function Write-Note { param([string]$Message) }
function Start-Sleep { param([int]$Milliseconds, [int]$Seconds) }

Run-SupervisorLoop -ManagedSessionId "session-1"

$payload = @{
    stops = @($script:stops)
    controlEvents = @($script:controlEvents)
    getStateCalls = $script:getStateCalls
} | ConvertTo-Json -Depth 8 -Compress
Write-Output $payload
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["stops"] == []
    assert payload["getStateCalls"] == 4
    assert "launcher.supervisor.state_wait_timeout" not in payload["controlEvents"]
    assert "launcher.supervisor.exit_state_missing" in payload["controlEvents"]


def test_launcher_supervisor_start_fails_fast_when_process_exits(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

foreach ($functionName in @(
    "ConvertTo-PowerShellSingleQuotedLiteral",
    "Get-ObjectPropertyValue",
    "Start-Supervisor"
)) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $functionName
    }, $true)
    if ($null -eq $functionAst) {
        throw "$functionName was not found."
    }
    . ([scriptblock]::Create($functionAst.Extent.Text))
}

$script:currentRuntimeSceneId = $null
$script:events = @()
$script:launcherDir = Join-Path ([System.IO.Path]::GetTempPath()) ("vibelution-supervisor-start-" + [guid]::NewGuid().ToString("N"))
$script:projectDir = $script:launcherDir
$script:PSCommandPath = $LauncherPath
$script:port = 8000
New-Item -ItemType Directory -Path $script:launcherDir -Force | Out-Null
function Start-RedirectedBackgroundProcess {
    param(
        [string]$CommandPath,
        [string[]]$ArgumentList = @(),
        [string]$StdoutPath = "",
        [string]$StderrPath = "",
        [string]$WorkingDirectory = ""
    )
    return [pscustomobject]@{ Id = 999999 }
}
function Get-State {
    return [pscustomobject]@{
        sessionId = "session-1"
    }
}
function Get-ManagedBackendLiveness {
    return [pscustomobject]@{
        Alive = $true
        Healthy = $true
        CandidatePids = @(1111, 2222)
    }
}
function Get-ListeningPid {
    param([int]$Port)
    return 1111
}
function Get-ManagedBrowserWindowProcesses {
    return @([pscustomobject]@{ Id = 3333 })
}
function Write-LauncherControlLog {
    param([string]$Event, [string]$Message, [string]$Level = "info", [hashtable]$Fields = @{})
    $script:events += [pscustomobject]@{ event = $Event; message = $Message; level = $Level; fields = $Fields }
}
function Start-Sleep { param([int]$Milliseconds, [int]$Seconds) }

$errorMessage = ""
try {
    Start-Supervisor -ManagedSessionId "session-1" | Out-Null
} catch {
    $errorMessage = $_.Exception.Message
}

$payload = @{
    errorMessage = $errorMessage
    events = @($script:events)
} | ConvertTo-Json -Depth 8 -Compress
Write-Output $payload
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert "Supervisor process exited during startup" in payload["errorMessage"]
    assert payload["events"][0]["event"] == "launcher.supervisor.start_failed"
    fields = payload["events"][0]["fields"]
    assert fields["stdout_path"]
    assert fields["stderr_path"]
    assert fields["supervisor_action"] == "supervise"
    assert fields["supervisor_launch_api"] == "hidden_redirected_powershell"
    assert fields["console_window_suppressed"] is True
    assert fields["supervisor_command_logged"] is False
    assert fields["startup_wait_timeout_ms"] == 8000
    assert fields["startup_settle_milliseconds"] == 250
    assert fields["startup_wait_exit_reason"] == "process_exited"
    assert fields["argument_count"] == 6
    assert fields["state_present"] is True
    assert fields["state_session_matches"] is True
    assert fields["backend_alive"] is True
    assert fields["backend_healthy"] is True
    assert fields["backend_candidate_count"] == 2
    assert fields["backend_port"] == 8000
    assert fields["backend_port_owner_pid"] == 1111
    assert fields["browser_window_count"] == 1
    assert fields["stdout_empty"] is True
    assert fields["stderr_empty"] is True
    assert "EncodedCommand" not in json.dumps(fields, ensure_ascii=False)


def test_launcher_supervisor_start_accepts_clean_wrapper_exit_when_session_is_live(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

foreach ($functionName in @(
    "ConvertTo-PowerShellSingleQuotedLiteral",
    "Get-ObjectPropertyValue",
    "Start-Supervisor"
)) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $functionName
    }, $true)
    if ($null -eq $functionAst) {
        throw "$functionName was not found."
    }
    . ([scriptblock]::Create($functionAst.Extent.Text))
}

$script:currentRuntimeSceneId = $null
$script:events = @()
$script:launcherDir = Join-Path ([System.IO.Path]::GetTempPath()) ("vibelution-supervisor-clean-exit-" + [guid]::NewGuid().ToString("N"))
$script:projectDir = $script:launcherDir
$script:PSCommandPath = $LauncherPath
$script:port = 8000
New-Item -ItemType Directory -Path $script:launcherDir -Force | Out-Null
function Start-RedirectedBackgroundProcess {
    param(
        [string]$CommandPath,
        [string[]]$ArgumentList = @(),
        [string]$StdoutPath = "",
        [string]$StderrPath = "",
        [string]$WorkingDirectory = ""
    )
    Set-Content -LiteralPath $StdoutPath -Value "" -Encoding UTF8
    Set-Content -LiteralPath $StderrPath -Value "" -Encoding UTF8
    return [pscustomobject]@{ Id = 999999; HasExited = $true; ExitCode = 0 }
}
function Get-Process {
    param([int]$Id, [string]$ErrorAction)
    return [pscustomobject]@{ Id = $Id; HasExited = $true; ExitCode = 0 }
}
function Get-State {
    return [pscustomobject]@{
        sessionId = "session-1"
    }
}
function Get-ManagedBackendLiveness {
    return [pscustomobject]@{
        Alive = $true
        Healthy = $true
        CandidatePids = @(1111, 2222)
    }
}
function Get-ListeningPid {
    param([int]$Port)
    return 1111
}
function Get-ManagedBrowserWindowProcesses {
    return @([pscustomobject]@{ Id = 3333 })
}
function Write-LauncherControlLog {
    param([string]$Event, [string]$Message, [string]$Level = "info", [hashtable]$Fields = @{})
    $script:events += [pscustomobject]@{ event = $Event; message = $Message; level = $Level; fields = $Fields }
}
function Start-Sleep { param([int]$Milliseconds, [int]$Seconds) }

$errorMessage = ""
$supervisorPid = 0
try {
    $supervisorPid = Start-Supervisor -ManagedSessionId "session-1"
} catch {
    $errorMessage = $_.Exception.Message
}

$payload = @{
    errorMessage = $errorMessage
    supervisorPid = $supervisorPid
    events = @($script:events)
} | ConvertTo-Json -Depth 8 -Compress
Write-Output $payload
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["errorMessage"] == ""
    assert payload["supervisorPid"] == 0
    assert payload["events"][0]["event"] == "launcher.supervisor.clean_exit_adopted"
    fields = payload["events"][0]["fields"]
    assert fields["state_session_matches"] is True
    assert fields["backend_alive"] is True
    assert fields["backend_healthy"] is True
    assert fields["browser_window_count"] == 1


def test_launcher_powershell_single_quoted_literal_escapes_quotes(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

$functionAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "ConvertTo-PowerShellSingleQuotedLiteral"
}, $true)
if ($null -eq $functionAst) {
    throw "ConvertTo-PowerShellSingleQuotedLiteral was not found."
}
. ([scriptblock]::Create($functionAst.Extent.Text))

$literal = ConvertTo-PowerShellSingleQuotedLiteral -Value "C:\\tmp\\user's file.ps1"
$payload = @{ literal = $literal } | ConvertTo-Json -Compress
Write-Output $payload
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["literal"] == "'C:\\tmp\\user''s file.ps1'"


def test_launcher_supervisor_preserves_requested_shutdown_reason_on_backend_exit(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

foreach ($functionName in @(
    "ConvertTo-PlainHashtable",
    "Get-ObjectPropertyValue",
    "Get-RuntimeManagerWorkbenchReason",
    "Wait-ForSupervisorSessionState",
    "Run-SupervisorLoop"
)) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $functionName
    }, $true)
    if ($null -eq $functionAst) {
        throw "$functionName was not found."
    }
    . ([scriptblock]::Create($functionAst.Extent.Text))
}

$script:getStateCalls = 0
$script:stops = @()
$script:notes = @()
function Get-State {
    $script:getStateCalls += 1
    if ($script:getStateCalls -gt 2) {
        return $null
    }
    return [pscustomobject]@{
        sessionId = "session-1"
        backendPid = 1111
        browserManaged = $true
    }
}
function Get-ManagedBackendLiveness {
    param([int]$TrackedPid = 0)
    return [pscustomobject]@{
        Alive = $false
        Healthy = $false
        TrackedPid = $TrackedPid
        TrackedPidAlive = $false
        CandidatePids = @()
    }
}
function Get-RuntimeManagerWorkbench {
    return [pscustomobject]@{
        desiredState = "closed"
        observedState = "open"
        phase = "closing"
        lastReason = "web_close_button"
        lastSource = "web_ui"
    }
}
function Get-ManagedBrowserWindowProcesses {
    return @([pscustomobject]@{ Id = 3333; MainWindowHandle = 1 })
}
function Stop-ManagedSession {
    param([string]$Reason = "")
    $script:stops += $Reason
}
function Write-LauncherControlLog {
    param([string]$Event, [string]$Message, [string]$Level = "info", [hashtable]$Fields = @{})
}
function Write-Note {
    param([string]$Message)
    $script:notes += $Message
}
function Start-Sleep { param([int]$Milliseconds, [int]$Seconds) }

Run-SupervisorLoop -ManagedSessionId "session-1"

$payload = @{
    stops = @($script:stops)
    notes = @($script:notes)
    getStateCalls = $script:getStateCalls
} | ConvertTo-Json -Depth 8 -Compress
Write-Output $payload
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["stops"] == ["web_close_button"]
    assert "backend exited unexpectedly" not in json.dumps(payload, ensure_ascii=False)
    assert payload["getStateCalls"] == 2


def test_desktop_entry_maps_open_to_launcher_without_monitor(tmp_path):
    calls = _run_desktop_entry_with_fake_launcher(tmp_path, action="open")

    assert calls == [
        {
            "action": "launcher",
            "argv": [],
            "noBrowser": False,
            "pythonExe": str(tmp_path / "project" / ".venv" / "Scripts" / "python.exe"),
        }
    ]


def test_desktop_entry_maps_start_to_launcher_without_monitor(tmp_path):
    calls = _run_desktop_entry_with_fake_launcher(tmp_path, action="start")

    assert calls == [
        {
            "action": "launcher",
            "argv": [],
            "noBrowser": False,
            "pythonExe": str(tmp_path / "project" / ".venv" / "Scripts" / "python.exe"),
        }
    ]


@pytest.mark.serial
def test_desktop_entry_launcher_action_times_out_and_logs_failure(tmp_path):
    project_dir = tmp_path / "project"
    scripts_dir = project_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    venv_scripts_dir = project_dir / ".venv" / "Scripts"
    venv_scripts_dir.mkdir(parents=True)
    (venv_scripts_dir / "python.exe").write_text("console python", encoding="utf-8")
    shutil.copyfile(DESKTOP_ENTRY_SCRIPT, scripts_dir / "vibelution_desktop_entry.ps1")
    (scripts_dir / "vibelution_launcher.ps1").write_text(
        """
param([string]$Action = "")
Start-Sleep -Seconds 30
""".strip(),
        encoding="utf-8-sig",
    )

    env = os.environ.copy()
    env["VIBELUTION_DESKTOP_ENTRY_SUPPRESS_FEEDBACK"] = "1"
    env["VIBELUTION_DESKTOP_ENTRY_ACTION_TIMEOUT_SECONDS"] = "1"
    env["VIBELUTION_DESKTOP_ENTRY_START_MUTEX_NAME"] = f"Local\\Vibelution.Tests.{tmp_path.name}.timeout"
    command = [
        _powershell_exe(),
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(scripts_dir / "vibelution_desktop_entry.ps1"),
        "-Action",
        "open",
    ]
    result = subprocess.run(command, capture_output=True, text=True, cwd=project_dir, env=env, check=False, timeout=15)

    assert result.returncode == 1
    log_path = project_dir / ".runtime" / "launcher" / "desktop-entry.log"
    events = [json.loads(line) for line in log_path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    event_names = [item["event"] for item in events]
    assert "desktop_entry.launcher_action.timed_out" in event_names
    assert "desktop_entry.failed" in event_names


def test_desktop_entry_defines_launcher_action_timeout_and_process_tree_cleanup(tmp_path):
    result = _run_desktop_entry_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$DesktopEntryPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $DesktopEntryPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Desktop entry script parse failed: $($parseErrors[0].Message)"
}

foreach ($functionName in @("Invoke-HiddenLauncherAction", "Resolve-DesktopEntryActionTimeoutSeconds", "Stop-DesktopEntryProcessTree")) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $functionName
    }, $true)
    if ($null -eq $functionAst) {
        throw "$functionName was not found."
    }
    . ([scriptblock]::Create($functionAst.Extent.Text))
}

$invokeText = ($ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Invoke-HiddenLauncherAction"
}, $true)).Extent.Text
foreach ($required in @(
    "desktop_entry.launcher_action.timed_out",
    "Stop-DesktopEntryProcessTree",
    "stream_capture_timed_out"
)) {
    if ($invokeText -notmatch [regex]::Escape($required)) {
        throw "Invoke-HiddenLauncherAction is missing timeout behavior: $required"
    }
}

$timeoutText = ($ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Resolve-DesktopEntryActionTimeoutSeconds"
}, $true)).Extent.Text
if ($timeoutText -notmatch "VIBELUTION_DESKTOP_ENTRY_ACTION_TIMEOUT_SECONDS") {
    throw "Timeout resolver should honor VIBELUTION_DESKTOP_ENTRY_ACTION_TIMEOUT_SECONDS."
}

$env:VIBELUTION_DESKTOP_ENTRY_ACTION_TIMEOUT_SECONDS = "7"
if ((Resolve-DesktopEntryActionTimeoutSeconds -LauncherAction "launcher") -ne 7) {
    throw "Configured timeout was not honored."
}
$env:VIBELUTION_DESKTOP_ENTRY_ACTION_TIMEOUT_SECONDS = ""
if ((Resolve-DesktopEntryActionTimeoutSeconds -LauncherAction "launcher") -lt 120) {
    throw "Default launcher timeout should leave enough time for build/start."
}

Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


@pytest.mark.serial
def test_desktop_entry_failure_is_logged_without_blocking_popup(tmp_path):
    project_dir = tmp_path / "project"
    scripts_dir = project_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    venv_scripts_dir = project_dir / ".venv" / "Scripts"
    venv_scripts_dir.mkdir(parents=True)
    (venv_scripts_dir / "python.exe").write_text("console python", encoding="utf-8")
    (venv_scripts_dir / "python.exe").write_text("console python", encoding="utf-8")
    shutil.copyfile(DESKTOP_ENTRY_SCRIPT, scripts_dir / "vibelution_desktop_entry.ps1")
    (scripts_dir / "vibelution_launcher.ps1").write_text(
        """
param(
    [string]$Action = "",
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
throw "synthetic launcher failure"
""".strip(),
        encoding="utf-8",
    )

    command = [
        _powershell_exe(),
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(scripts_dir / "vibelution_desktop_entry.ps1"),
        "-Action",
        "open",
    ]
    env = os.environ.copy()
    env["VIBELUTION_DESKTOP_ENTRY_SUPPRESS_FEEDBACK"] = "1"
    env["VIBELUTION_DESKTOP_ENTRY_START_MUTEX_NAME"] = f"Local\\Vibelution.Tests.{tmp_path.name}.failure.{time.time_ns()}"
    result = subprocess.run(command, capture_output=True, text=True, cwd=project_dir, env=env, check=False, timeout=30)

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == ""
    log_path = project_dir / ".runtime" / "launcher" / "desktop-entry.log"
    events = [json.loads(line) for line in log_path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    assert [event["event"] for event in events[-3:]] == [
        "desktop_entry.failed",
        "desktop_entry.failure.notice.requested",
        "desktop_entry.feedback.suppressed",
    ]
    assert "synthetic launcher failure" in events[-2]["fields"]["error"]


def test_desktop_entry_syncs_logs_from_active_runtime_scene_sidecar(tmp_path):
    scene_dir = tmp_path / "scene"
    launcher_dir = tmp_path / "launcher"
    result = _run_desktop_entry_ast_harness(
        tmp_path,
        f"""
param(
    [Parameter(Mandatory = $true)]
    [string]$DesktopEntryPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $DesktopEntryPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {{
    throw "Desktop entry script parse failed: $($parseErrors[0].Message)"
}}

foreach ($functionName in @(
    "Sync-DesktopEntryLogsIntoRuntimeScene",
    "Get-DesktopEntryRuntimeSceneDir",
    "Get-JsonPayloadField",
    "Sync-DesktopEntryLogFile"
)) {{
    $functionAst = $ast.Find({{
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $functionName
    }}, $true)
    if ($null -eq $functionAst) {{
        throw "$functionName was not found."
    }}
    . ([scriptblock]::Create($functionAst.Extent.Text))
}}

$launcherDir = {json.dumps(str(launcher_dir))}
$entryLogPath = Join-Path $launcherDir "desktop-entry.log"
$script:desktopEntryRunId = "entry-run"
$env:VIBELUTION_DESKTOP_ENTRY_VBS_RUN_ID = "vbs-run"
New-Item -ItemType Directory -Path $launcherDir -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path {json.dumps(str(scene_dir))} "raw") -Force | Out-Null
@{{
    runtimeSceneId = "scene-a"
    runtimeSceneDir = {json.dumps(str(scene_dir))}
}} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $launcherDir "active-runtime-scene.json") -Encoding utf8

Set-Content -LiteralPath $entryLogPath -Encoding utf8 -Value @(
    '{{"event":"desktop_entry.started","fields":{{"run_id":"entry-run"}}}}',
    '{{"event":"desktop_entry.started","fields":{{"run_id":"other-run"}}}}'
)
Set-Content -LiteralPath (Join-Path $launcherDir "desktop-entry-vbs.log") -Encoding utf8 -Value @(
    '{{"event":"desktop_entry_vbs.started","details":"run_id=vbs-run action=start"}}',
    '{{"event":"desktop_entry_vbs.started","details":"run_id=other-vbs action=start"}}'
)

Sync-DesktopEntryLogsIntoRuntimeScene

$entryTarget = Get-Content -LiteralPath (Join-Path {json.dumps(str(scene_dir))} "raw\\desktop-entry.log") -Raw -Encoding utf8
$vbsTarget = Get-Content -LiteralPath (Join-Path {json.dumps(str(scene_dir))} "raw\\desktop-entry-vbs.log") -Raw -Encoding utf8
if ($entryTarget -notmatch "entry-run" -or $entryTarget -match "other-run") {{
    throw "Desktop entry log was not filtered by run id through the sidecar scene reference."
}}
if ($vbsTarget -notmatch "vbs-run" -or $vbsTarget -match "other-vbs") {{
    throw "Desktop entry VBS log was not filtered by VBS run id through the sidecar scene reference."
}}

Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_desktop_entry_success_feedback_is_quiet_by_default(tmp_path):
    result = _run_desktop_entry_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$DesktopEntryPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $DesktopEntryPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Desktop entry script parse failed: $($parseErrors[0].Message)"
}

foreach ($functionName in @("Show-DesktopEntryFeedback", "Test-DesktopEntryFeedbackSuppressed", "Test-DesktopEntryFeedbackEnabled")) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $functionName
    }, $true)
    if ($null -eq $functionAst) {
        throw "$functionName was not found."
    }
    . ([scriptblock]::Create($functionAst.Extent.Text))
}

$script:feedbackEvents = @()
function Write-DesktopEntryLog {
    param(
        [string]$Event,
        [string]$Message,
        [string]$Level = "info",
        [hashtable]$Fields = @{}
    )
    $script:feedbackEvents += ,@{ event = $Event; fields = $Fields }
}

$env:VIBELUTION_DESKTOP_ENTRY_SUPPRESS_FEEDBACK = ""
$env:VIBELUTION_DESKTOP_ENTRY_SHOW_FEEDBACK = ""
Show-DesktopEntryFeedback -Title "title" -Message "message" -Seconds 1 -Kind "info"
if ($script:feedbackEvents.Count -ne 1 -or $script:feedbackEvents[0].event -ne "desktop_entry.feedback.suppressed") {
    throw "Success feedback should be quiet by default."
}
if ($script:feedbackEvents[0].fields.reason -ne "default_quiet") {
    throw "Default quiet feedback should log reason=default_quiet."
}

Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_desktop_entry_has_nonblocking_start_gate(tmp_path):
    result = _run_desktop_entry_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$DesktopEntryPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $DesktopEntryPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Desktop entry script parse failed: $($parseErrors[0].Message)"
}

foreach ($functionName in @("Enter-DesktopEntryStartGate", "Exit-DesktopEntryStartGate", "Test-DesktopEntryStartAction", "Show-DesktopEntryFeedback", "Test-DesktopEntryFeedbackSuppressed", "Test-DesktopEntryFeedbackEnabled", "Clear-StaleDesktopEntryStartProcesses")) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $functionName
    }, $true)
    if ($null -eq $functionAst) {
        throw "$functionName was not found."
    }
    . ([scriptblock]::Create($functionAst.Extent.Text))
}

$gateAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Enter-DesktopEntryStartGate"
}, $true)
$gateText = $gateAst.Extent.Text
if ($gateText -notmatch "WaitOne\\(0\\)") {
    throw "Start gate should use nonblocking mutex acquisition."
}
if ($gateText -notmatch "desktop_entry.start.skipped_in_progress") {
    throw "Start gate should log duplicate start suppression."
}
if ($gateText -notmatch "Show-DesktopEntryFeedback") {
    throw "Start gate should request visible feedback when a duplicate start is skipped."
}
if ($gateText -notmatch 'return\\s+\\$false') {
    throw "Start gate should skip duplicate starts."
}

$cleanupAst = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Clear-StaleDesktopEntryStartProcesses"
}, $true)
$cleanupText = $cleanupAst.Extent.Text
foreach ($required in @(
    "desktop_entry.stale_start_process.cleaned",
    "Stop-DesktopEntryProcessTree",
    "Test-DesktopEntryStartAction",
    "stale_after_seconds"
)) {
    if ($cleanupText -notmatch [regex]::Escape($required)) {
        throw "Stale desktop entry cleanup is missing '$required'."
    }
}

$endBlockText = $ast.EndBlock.Extent.Text
$cleanupIndex = $endBlockText.IndexOf("Clear-StaleDesktopEntryStartProcesses")
$gateIndex = $endBlockText.IndexOf("Enter-DesktopEntryStartGate")
if ($cleanupIndex -lt 0 -or $gateIndex -lt 0 -or $cleanupIndex -gt $gateIndex) {
    throw "Stale desktop entry cleanup should run before start gate acquisition."
}

if (-not (Test-DesktopEntryStartAction -LauncherAction "start")) {
    throw "start should be gated."
}
if (-not (Test-DesktopEntryStartAction -LauncherAction "launcher")) {
    throw "launcher should be gated."
}
if (Test-DesktopEntryStartAction -LauncherAction "stop") {
    throw "stop should not be gated."
}
if (Test-DesktopEntryStartAction -LauncherAction "status") {
    throw "status should not be gated."
}

$env:VIBELUTION_DESKTOP_ENTRY_SUPPRESS_FEEDBACK = "1"
$script:feedbackEvents = @()
function Write-DesktopEntryLog {
    param(
        [string]$Event,
        [string]$Message,
        [string]$Level = "info",
        [hashtable]$Fields = @{}
    )
    $script:feedbackEvents += ,@{ event = $Event; fields = $Fields }
}
Show-DesktopEntryFeedback -Title "title" -Message "message" -Seconds 1 -Kind "info"
if ($script:feedbackEvents.Count -ne 1 -or $script:feedbackEvents[0].event -ne "desktop_entry.feedback.suppressed") {
    throw "Feedback suppression should be logged."
}

Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


@pytest.mark.serial
def test_launcher_internal_actions_skip_outer_mutex(tmp_path):
    harness_path = tmp_path / "launcher-internal-mutex.ps1"
    harness_path.write_text(
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -Encoding UTF8 -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

foreach ($functionName in @("Acquire-LauncherMutex", "Release-LauncherMutex")) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $functionName
    }, $true)
    if ($null -eq $functionAst) {
        throw "$functionName was not found."
    }
    . ([scriptblock]::Create($functionAst.Extent.Text))
}

$acquireText = ($ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Acquire-LauncherMutex"
}, $true)).Extent.Text
$releaseText = ($ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Release-LauncherMutex"
}, $true)).Extent.Text

foreach ($text in @($acquireText, $releaseText)) {
    if ($text -notmatch 'StartsWith\\("internal-"\\)') {
        throw "Internal launcher actions should skip the outer process mutex."
    }
}

$script:launcherMutex = $null
$script:mutexName = "Global\\Vibelution.Test.Launcher.InternalMutex.$PID"
$script:Action = "internal-start"
Acquire-LauncherMutex
if ($null -ne $script:launcherMutex) {
    throw "internal-start should not acquire the outer launcher mutex."
}
Release-LauncherMutex

$script:Action = "start"
Acquire-LauncherMutex
try {
    if ($null -eq $script:launcherMutex) {
        throw "start should still acquire the outer launcher mutex."
    }
} finally {
    Release-LauncherMutex
}

Write-Output "ok"
""".strip(),
        encoding="utf-8",
    )

    result = subprocess.run(
        [_powershell_exe(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness_path), "-LauncherPath", str(LAUNCHER_SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_start_marks_ready_before_nonblocking_supervisor_attach(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

function Get-LauncherFunctionText {
    param([string]$Name)

    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $Name
    }, $true)
    if ($null -eq $functionAst) {
        throw "$Name was not found."
    }
    return $functionAst.Extent.Text
}

$startText = Get-LauncherFunctionText -Name "Start-ManagedSession"
$readyIndex = $startText.IndexOf("runtime.scene.ready")
$supervisorAttachIndex = $startText.IndexOf("Start-SupervisorDetached")
if ($readyIndex -lt 0) {
    throw "Start-ManagedSession should mark the runtime scene ready."
}
if ($supervisorAttachIndex -lt 0) {
    throw "Start-ManagedSession should attach supervision through Start-SupervisorDetached."
}
if ($readyIndex -gt $supervisorAttachIndex) {
    throw "Start-ManagedSession should mark ready before nonblocking supervisor attachment."
}
foreach ($required in @(
    "supervisor_attach_mode",
    "non_blocking",
    "supervisor_pid = 0"
)) {
    if ($startText -notmatch [regex]::Escape($required)) {
        throw "Start-ManagedSession ready event is missing '$required'."
    }
}

$detachedText = Get-LauncherFunctionText -Name "Start-SupervisorDetached"
foreach ($required in @(
    "Start-RedirectedBackgroundProcess",
    "startup_wait_skipped",
    "launcher.supervisor.attach.started",
    "supervisor.attach.started",
    "hidden_redirected_powershell",
    "console_window_suppressed",
    "StdoutPath",
    "StderrPath"
)) {
    if ($detachedText -notmatch [regex]::Escape($required)) {
        throw "Start-SupervisorDetached is missing '$required'."
    }
}
if ($detachedText -match "Start-HiddenBackgroundProcess") {
    throw "Start-SupervisorDetached should use the redirected no-window starter."
}
if ($detachedText -notmatch "-EncodedCommand") {
    throw "Start-SupervisorDetached should still use an encoded supervisor command."
}
if ($detachedText -notmatch "3>&1 4>&1 5>&1 6>&1") {
    throw "Start-SupervisorDetached should merge non-error streams before parent stdout redirection."
}
if ($detachedText -match "1>>" -or $detachedText -match "2>>") {
    throw "Start-SupervisorDetached should leave stdout and stderr redirection to the parent starter."
}
if ($detachedText -match "3>> `$stdoutLiteral" -or $detachedText -match "4>> `$stdoutLiteral" -or $detachedText -match "5>> `$stdoutLiteral" -or $detachedText -match "6>> `$stdoutLiteral") {
    throw "Start-SupervisorDetached should not open competing redirected writers to supervisor stdout."
}

Write-Output "ok"
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout.strip().splitlines()[-1] == "ok"


def test_launcher_detached_supervisor_attach_failure_is_best_effort(tmp_path):
    result = _run_launcher_ast_harness(
        tmp_path,
        """
param(
    [Parameter(Mandatory = $true)]
    [string]$LauncherPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$source = Get-Content -Raw -LiteralPath $LauncherPath
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($source, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors -and $parseErrors.Count -gt 0) {
    throw "Launcher script parse failed: $($parseErrors[0].Message)"
}

foreach ($functionName in @(
    "ConvertTo-PowerShellSingleQuotedLiteral",
    "Test-SupervisorAttachFileConflictMessage",
    "Start-SupervisorDetached"
)) {
    $functionAst = $ast.Find({
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $functionName
    }, $true)
    if ($null -eq $functionAst) {
        throw "$functionName was not found."
    }
    . ([scriptblock]::Create($functionAst.Extent.Text))
}

function Get-SupervisorAttachFileDiagnostics {
    param(
        [string]$ManagedSessionId,
        [string]$StdoutLog,
        [string]$StderrLog,
        [string]$ErrorMessage
    )

    return @{
        probed_at = "2026-06-11T00:00:00Z"
        file_conflict_likely = (Test-SupervisorAttachFileConflictMessage -Message $ErrorMessage)
        stdout = @{ path = $StdoutLog }
        stderr = @{ path = $StderrLog }
        candidate_process_count = 0
        candidate_processes = @()
    }
}

$script:currentRuntimeSceneId = "scene-1"
$script:events = @()
$script:manifestUpdates = @()
$script:rawRefs = @()
$script:projectDir = [System.IO.Path]::GetTempPath()
$script:launcherDir = [System.IO.Path]::GetTempPath()
$script:PSCommandPath = $LauncherPath
$script:sceneRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("supervisor-attach-test-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path (Join-Path $script:sceneRoot "raw") | Out-Null

function Get-RuntimeSceneRelativePaths {
    return [pscustomobject]@{
        Supervisor = "raw/supervisor.log"
        SupervisorStderr = "raw/supervisor.stderr.log"
        LauncherControl = "raw/launcher-control.jsonl"
    }
}
function Get-CurrentRuntimeSceneFilePath {
    param([string]$RelativePath)
    return (Join-Path $script:sceneRoot $RelativePath)
}
function Write-LauncherControlLog {
    param([string]$Event, [string]$Message, [string]$Level = "info", [hashtable]$Fields = @{})
    $script:events += [pscustomobject]@{ event = $Event; message = $Message; level = $Level; fields = $Fields }
}
function Update-RuntimeSceneManifest {
    param([hashtable]$Patch)
    $script:manifestUpdates += $Patch
}
function Write-RuntimeSceneEvent {
    param(
        [string]$Component,
        [string]$Phase,
        [string]$EventCode,
        [string]$Message,
        [string]$Level = "info",
        [string]$Outcome = "",
        [hashtable]$Fields = @{},
        [object[]]$RawRefs = @()
    )
    $script:events += [pscustomobject]@{
        component = $Component
        phase = $Phase
        eventCode = $EventCode
        message = $Message
        level = $Level
        outcome = $Outcome
        fields = $Fields
    }
    $script:rawRefs += @($RawRefs)
}
function New-RuntimeSceneRawRef {
    param([string]$RelativePath, [int]$TailLines)
    return [pscustomobject]@{ relativePath = $RelativePath; tailLines = $TailLines }
}
function Start-RedirectedBackgroundProcess {
    param(
        [string]$CommandPath,
        [string[]]$ArgumentList,
        [string]$WorkingDirectory,
        [string]$StdoutPath,
        [string]$StderrPath
    )
    throw "simulated redirected supervisor attach failure"
}

$pidResult = Start-SupervisorDetached -ManagedSessionId "session-1"
$payload = @{
    pid = $pidResult
    events = @($script:events)
    manifestUpdates = @($script:manifestUpdates)
    rawRefCount = $script:rawRefs.Count
} | ConvertTo-Json -Depth 8 -Compress
Write-Output $payload
""",
    )

    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["pid"] == 0
    assert payload["events"][0]["event"] == "launcher.supervisor.attach.failed"
    assert payload["events"][0]["level"] == "warning"
    assert "file_probe" in payload["events"][0]["fields"]
    assert payload["events"][1]["eventCode"] == "supervisor.attach.failed"
    assert payload["events"][1]["outcome"] == "failed"
    assert payload["manifestUpdates"][0]["supervisor"]["status"] == "attach_failed"
    assert payload["rawRefCount"] == 3


def test_desktop_entry_maps_close_to_stop_without_monitor(tmp_path):
    calls = _run_desktop_entry_with_fake_launcher(tmp_path, action="close")

    assert calls == [
        {
            "action": "stop",
            "argv": [],
            "noBrowser": False,
            "pythonExe": str(tmp_path / "project" / ".venv" / "Scripts" / "python.exe"),
        }
    ]


def test_desktop_entry_runs_restart_without_monitor(tmp_path):
    calls = _run_desktop_entry_with_fake_launcher(tmp_path, action="restart")

    assert calls == [
        {
            "action": "restart",
            "argv": [],
            "noBrowser": False,
            "pythonExe": str(tmp_path / "project" / ".venv" / "Scripts" / "python.exe"),
        }
    ]


def test_desktop_entry_status_does_not_attach_monitor(tmp_path):
    calls = _run_desktop_entry_with_fake_launcher(tmp_path, action="status")

    assert calls == [
        {
            "action": "status",
            "argv": [],
            "noBrowser": False,
            "pythonExe": str(tmp_path / "project" / ".venv" / "Scripts" / "python.exe"),
        }
    ]


def test_desktop_entry_forwards_no_browser_and_skips_monitor(tmp_path):
    calls = _run_desktop_entry_with_fake_launcher(tmp_path, action="open", no_browser=True)

    assert calls == [
        {
            "action": "launcher",
            "argv": [],
            "noBrowser": True,
            "pythonExe": str(tmp_path / "project" / ".venv" / "Scripts" / "python.exe"),
        }
    ]


def test_vbs_desktop_entry_defaults_to_launcher_action(tmp_path):
    calls, events, python_bridge_calls = _run_vbs_desktop_entry_with_fake_powershell_entry(tmp_path, [])

    assert calls == []
    assert len(python_bridge_calls) == 1
    assert python_bridge_calls[0]["argv"][0:2] == ["--action", "launcher"]
    assert "--python-exe" in python_bridge_calls[0]["argv"]
    assert "--run-id" in python_bridge_calls[0]["argv"]
    python_exe_index = python_bridge_calls[0]["argv"].index("--python-exe")
    expected_python_exe = str(tmp_path / "project" / ".venv" / "Scripts" / "python.exe")
    assert python_bridge_calls[0]["argv"][python_exe_index + 1] == expected_python_exe
    assert python_bridge_calls[0]["cwd"] == str(tmp_path / "project")
    assert events[-2]["event"] == "desktop_entry_vbs.launched"
    assert "wmi_python_bridge_hidden_process" in events[-2]["details"]
    launcher_dir = tmp_path / "project" / ".runtime" / "launcher"
    assert not (launcher_dir / "launcher-control-profile").exists()
    assert not (launcher_dir / "launcher-backend.stdout.log").exists()


def test_vbs_desktop_entry_accepts_named_action_arguments(tmp_path):
    calls, _events, python_bridge_calls = _run_vbs_desktop_entry_with_fake_powershell_entry(tmp_path, ["-Action", "close"])

    assert calls == [
        {
            "action": "close",
            "argv": [],
            "noBrowser": False,
            "pythonExe": str(tmp_path / "project" / ".venv" / "Scripts" / "python.exe"),
        }
    ]
    assert python_bridge_calls == []


def test_vbs_desktop_entry_accepts_powershell_style_no_browser_switch(tmp_path):
    calls, events, python_bridge_calls = _run_vbs_desktop_entry_with_fake_powershell_entry(tmp_path, ["open", "-NoBrowser"])

    assert calls == [
        {
            "action": "open",
            "argv": [],
            "noBrowser": True,
            "pythonExe": str(tmp_path / "project" / ".venv" / "Scripts" / "python.exe"),
        }
    ]
    assert python_bridge_calls == []
    assert events[-1]["event"] == "desktop_entry_vbs.feedback.suppressed"


def test_vbs_desktop_entry_accepts_colon_action_argument(tmp_path):
    calls, _events, python_bridge_calls = _run_vbs_desktop_entry_with_fake_powershell_entry(tmp_path, ["-Action:status"])

    assert calls == [
        {
            "action": "status",
            "argv": [],
            "noBrowser": False,
            "pythonExe": str(tmp_path / "project" / ".venv" / "Scripts" / "python.exe"),
        }
    ]
    assert python_bridge_calls == []


def test_vbs_desktop_entry_accepts_equals_action_argument(tmp_path):
    calls, _events, python_bridge_calls = _run_vbs_desktop_entry_with_fake_powershell_entry(tmp_path, ["--action=restart", "--no-browser"])

    assert calls == [
        {
            "action": "restart",
            "argv": [],
            "noBrowser": True,
            "pythonExe": str(tmp_path / "project" / ".venv" / "Scripts" / "python.exe"),
        }
    ]
    assert python_bridge_calls == []
