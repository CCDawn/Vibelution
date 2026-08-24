from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import os
import subprocess
import sys
import time
import types
import uuid
from pathlib import Path

import pytest

import scripts.vibelution_desktop_entry as desktop_entry


DESKTOP_ENTRY_PY = Path(__file__).parents[1] / "scripts" / "vibelution_desktop_entry.py"


def _load_desktop_entry_py():
    module_name = f"vibelution_desktop_entry_under_test_{time.time_ns()}"
    spec = importlib.util.spec_from_file_location(module_name, DESKTOP_ENTRY_PY)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_desktop_entry_direct_execution_loads_local_windowless_helper(tmp_path):
    result = subprocess.run(
        [sys.executable, str(DESKTOP_ENTRY_PY), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Open the Vibelution Launcher without a console window." in result.stdout


def test_desktop_entry_imports_safely_on_non_windows(monkeypatch):
    fake_os = types.ModuleType("os")
    fake_os.name = "posix"
    fake_os.environ = os.environ
    monkeypatch.setitem(sys.modules, "os", fake_os)
    entry = _load_desktop_entry_py()

    # Windows-only shell identity structures must not be constructed off-Windows;
    # importing on POSIX previously raised ValueError from _GUID.from_buffer_copy.
    assert entry.PKEY_APPUSERMODEL_ID is None
    assert entry.PKEY_APPUSERMODEL_RELAUNCH_DISPLAY_NAME is None
    assert entry.PKEY_APPUSERMODEL_RELAUNCH_ICON_RESOURCE is None
    assert entry.IID_IPROPERTY_STORE is None
    result = entry._apply_managed_browser_app_identity(0, "launcher")
    assert result["applied"] is False
    assert result["reason"] == "non_windows"
    assert result["appUserModelId"] == "Vibelution.Launcher"


@pytest.mark.skipif(os.name != "nt", reason="Windows shell identity contract is Windows-only")
def test_desktop_entry_windows_identity_runtime_contract():
    entry = _load_desktop_entry_py()

    assert isinstance(entry.PKEY_APPUSERMODEL_ID, entry._PROPERTYKEY)
    assert isinstance(entry.PKEY_APPUSERMODEL_RELAUNCH_DISPLAY_NAME, entry._PROPERTYKEY)
    assert isinstance(entry.PKEY_APPUSERMODEL_RELAUNCH_ICON_RESOURCE, entry._PROPERTYKEY)
    assert entry.PKEY_APPUSERMODEL_ID.fmtid.Data1 == 0x9F4C2855
    assert entry.PKEY_APPUSERMODEL_ID.pid == 5
    assert entry.PKEY_APPUSERMODEL_RELAUNCH_DISPLAY_NAME.pid == 4
    assert entry.PKEY_APPUSERMODEL_RELAUNCH_ICON_RESOURCE.pid == 3
    assert isinstance(entry.IID_IPROPERTY_STORE, entry._GUID)
    assert bytes(entry.IID_IPROPERTY_STORE) == uuid.UUID("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99").bytes_le


def test_bootstrap_marks_untracked_healthy_launcher_port_as_attached(monkeypatch):
    states = iter(
        [
            {"launcherBackendPid": 0},
            {
                "launcherBackendPid": 0,
                "launcherControlPort": 8765,
                "sessionId": "launcher-session",
                "url": "http://127.0.0.1:8000",
            },
        ]
    )

    monkeypatch.setattr(desktop_entry, "_read_state", lambda: next(states))
    monkeypatch.setattr(desktop_entry, "_open_launcher", lambda args: None)
    monkeypatch.setattr(desktop_entry, "_launcher_control_port", lambda: 8765)
    monkeypatch.setattr(desktop_entry, "_launcher_control_url", lambda port: "http://127.0.0.1:8765/launcher")
    monkeypatch.setattr(desktop_entry, "_launcher_control_healthy", lambda port: True)

    result = desktop_entry._bootstrap_launcher(
        argparse.Namespace(workspace="", config="", no_browser=True, python_exe="")
    )

    assert result["mode"] == "attached"
    assert result["launcherBackendPid"] == 0


def test_electron_bootstrap_attaches_to_healthy_managed_launcher_without_replacing_it(monkeypatch):
    state = {
        "launcherAdapter": "python_headless",
        "launcherBackendPid": 4321,
        "launcherBackendLaunchPid": 4321,
        "launcherControlPort": 8765,
        "launcherControlSourceSignature": "older-source",
        "runtimeProjectRoot": str(desktop_entry.PROJECT_ROOT),
        "sessionId": "launcher-session",
        "url": "http://127.0.0.1:8002",
    }
    events: list[tuple[str, dict[str, object]]] = []

    monkeypatch.setattr(desktop_entry, "_read_state", lambda: dict(state))
    monkeypatch.setattr(desktop_entry, "_launcher_control_port", lambda: 8765)
    monkeypatch.setattr(desktop_entry, "_launcher_control_url", lambda port: "http://127.0.0.1:8765/launcher")
    monkeypatch.setattr(desktop_entry, "_launcher_control_healthy", lambda port: True)
    monkeypatch.setattr(desktop_entry, "_pid_alive", lambda pid: pid == 4321)
    monkeypatch.setattr(
        desktop_entry,
        "_open_launcher",
        lambda args: pytest.fail("healthy managed Launcher must not be replaced during Electron bootstrap"),
    )
    monkeypatch.setattr(
        desktop_entry,
        "_append_log",
        lambda event, **fields: events.append((event, fields)),
    )

    result = desktop_entry._bootstrap_launcher(
        argparse.Namespace(
            workspace=str(desktop_entry.PROJECT_ROOT),
            config="",
            no_browser=True,
            python_exe="",
            attach_healthy_launcher=True,
        )
    )

    assert result["mode"] == "attached"
    assert result["launcherBackendPid"] == 4321
    assert result["workbenchUrl"] == "http://127.0.0.1:8002"
    assert events == [
        (
            "desktop_entry_python.backend.attached_managed_healthy",
            {
                "port": 8765,
                "backend_pid": 4321,
                "reason": "electron_bootstrap",
                "source_signature_policy": "ignored_for_attach",
            },
        )
    ]


def test_electron_bootstrap_rejects_healthy_launcher_with_mismatched_workspace(monkeypatch):
    state = {
        "launcherAdapter": "python_headless",
        "launcherBackendPid": 4321,
        "launcherBackendLaunchPid": 4321,
        "launcherControlPort": 8765,
        "runtimeProjectRoot": "C:/different-project",
    }

    monkeypatch.setattr(desktop_entry, "_read_state", lambda: dict(state))
    monkeypatch.setattr(desktop_entry, "_launcher_control_port", lambda: 8765)
    monkeypatch.setattr(desktop_entry, "_launcher_control_healthy", lambda port: True)
    monkeypatch.setattr(desktop_entry, "_pid_alive", lambda pid: pid == 4321)
    monkeypatch.setattr(
        desktop_entry,
        "_open_launcher",
        lambda args: pytest.fail("identity mismatch must fail closed before ordinary bootstrap"),
    )

    with pytest.raises(RuntimeError, match="does not belong to this workspace"):
        desktop_entry._bootstrap_launcher(
            argparse.Namespace(
                workspace=str(desktop_entry.PROJECT_ROOT),
                config="",
                no_browser=True,
                python_exe="",
                attach_healthy_launcher=True,
            )
        )


def test_ordinary_bootstrap_keeps_existing_launcher_refresh_path(monkeypatch):
    states = iter(
        [
            {"launcherBackendPid": 4321},
            {
                "launcherBackendPid": 5678,
                "launcherControlPort": 8765,
                "sessionId": "replacement-launcher",
                "url": "http://127.0.0.1:8002",
            },
        ]
    )
    calls: list[argparse.Namespace] = []

    monkeypatch.setattr(desktop_entry, "_read_state", lambda: next(states))
    monkeypatch.setattr(desktop_entry, "_open_launcher", lambda args: calls.append(args))
    monkeypatch.setattr(desktop_entry, "_launcher_control_port", lambda: 8765)
    monkeypatch.setattr(desktop_entry, "_launcher_control_url", lambda port: "http://127.0.0.1:8765/launcher")
    monkeypatch.setattr(desktop_entry, "_launcher_control_healthy", lambda port: True)

    args = argparse.Namespace(workspace="", config="", no_browser=True, python_exe="")
    result = desktop_entry._bootstrap_launcher(args)

    assert calls == [args]
    assert result["mode"] == "started"
    assert result["launcherBackendPid"] == 5678


def test_ordinary_bootstrap_attaches_to_healthy_control_while_same_workspace_electron_is_active(monkeypatch):
    state = {
        "launcherAdapter": "python_headless",
        "launcherBackendPid": 4321,
        "launcherBackendLaunchPid": 4321,
        "launcherControlPort": 8765,
        "launcherControlSourceSignature": "older-source",
        "runtimeProjectRoot": str(desktop_entry.PROJECT_ROOT),
    }
    saved: list[dict[str, object]] = []
    events: list[tuple[str, dict[str, object]]] = []

    monkeypatch.setattr(desktop_entry, "_single_launcher_open_lock", lambda: contextlib.nullcontext(True))
    monkeypatch.setattr(desktop_entry, "_read_state", lambda: dict(state))
    monkeypatch.setattr(desktop_entry, "_launcher_control_port", lambda: 8765)
    monkeypatch.setattr(desktop_entry, "_launcher_control_healthy", lambda _port: True)
    monkeypatch.setattr(desktop_entry, "_pid_alive", lambda pid: pid == 4321)
    monkeypatch.setattr(desktop_entry, "_source_signature", lambda: "newer-source")
    monkeypatch.setattr(
        desktop_entry,
        "_active_electron_desktop_session_for_workspace",
        lambda _workspace: {"desktopSessionId": "electron-launcher-session-8952-msqairvx"},
    )
    monkeypatch.setattr(
        desktop_entry,
        "_replace_stale_launcher_control",
        lambda *_args, **_kwargs: pytest.fail("active Electron must keep the healthy control plane attached"),
    )
    monkeypatch.setattr(
        desktop_entry,
        "_save_launcher_state",
        lambda previous, **kwargs: saved.append({**previous, **kwargs}),
    )
    monkeypatch.setattr(desktop_entry, "_append_log", lambda event, **fields: events.append((event, fields)))

    desktop_entry._open_launcher(
        argparse.Namespace(
            workspace=str(desktop_entry.PROJECT_ROOT),
            config="",
            no_browser=True,
            python_exe="C:/Python/python.exe",
        )
    )

    assert saved[-1]["current_signature"] == "older-source"
    assert ("desktop_entry_python.backend.attached_active_electron", {
        "port": 8765,
        "backend_pid": 4321,
        "desktop_session_id": "electron-launcher-session-8952-msqairvx",
        "source_signature_policy": "preserved_until_controlled_restart",
    }) in events


def test_active_electron_session_helper_rejects_canonical_dead_process(monkeypatch):
    from core.launcher import desktop_session_store

    monkeypatch.setattr(
        desktop_session_store,
        "latest_active_desktop_session",
        lambda **_kwargs: {
            "desktopSessionId": "electron-launcher-session-8952-msqairvx",
            "revision": 33,
        },
    )
    monkeypatch.setattr(desktop_entry, "_pid_alive", lambda _pid: False)

    assert desktop_entry._active_electron_desktop_session_for_workspace(desktop_entry.PROJECT_ROOT) == {}


def test_launcher_state_records_workspace_identity_for_future_attach(tmp_path, monkeypatch):
    writes: list[dict[str, object]] = []

    monkeypatch.setattr(desktop_entry, "_write_state", lambda state: writes.append(dict(state)))
    monkeypatch.setattr(desktop_entry, "_select_no_console_python", lambda value: value)
    monkeypatch.setattr(desktop_entry, "LAUNCHER_BROWSER_PROFILE_DIR", tmp_path / "launcher-profile")

    desktop_entry._save_launcher_state(
        {},
        port=8765,
        backend_pid=4321,
        browser_pid=0,
        current_signature="signature",
        python_exe="C:/Python/python.exe",
    )

    assert writes[-1]["runtimeProjectRoot"] == str(desktop_entry.PROJECT_ROOT)


def test_workbench_port_prefers_ports_json_over_config(monkeypatch, tmp_path):
    ports_dir = tmp_path / ".runtime" / "launcher"
    ports_dir.mkdir(parents=True)
    (ports_dir / "ports.json").write_text('{"backendPort": 8002}', encoding="utf-8")

    monkeypatch.setattr(desktop_entry, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("VIBELUTION_PORT", raising=False)
    monkeypatch.delenv("AGENT_WORKBENCH_BACKEND_PORT", raising=False)
    monkeypatch.setattr(
        desktop_entry,
        "_config_section",
        lambda name: {"backend_port": 8000} if name == "workbench" else {},
    )

    assert desktop_entry._workbench_port() == 8002


def test_bootstrap_workbench_url_falls_back_to_workbench_port(monkeypatch):
    states = iter(
        [
            {"launcherBackendPid": 0},
            {
                "launcherBackendPid": 0,
                "launcherControlPort": 8765,
                "sessionId": "launcher-session",
                "url": "",
            },
        ]
    )

    monkeypatch.setattr(desktop_entry, "_read_state", lambda: next(states))
    monkeypatch.setattr(desktop_entry, "_open_launcher", lambda args: None)
    monkeypatch.setattr(desktop_entry, "_launcher_control_port", lambda: 8765)
    monkeypatch.setattr(desktop_entry, "_launcher_control_url", lambda port: "http://127.0.0.1:8765/launcher")
    monkeypatch.setattr(desktop_entry, "_launcher_control_healthy", lambda port: True)
    monkeypatch.setattr(desktop_entry, "_workbench_port", lambda: 8002)

    result = desktop_entry._bootstrap_launcher(
        argparse.Namespace(workspace="", config="", no_browser=True, python_exe="")
    )

    assert result["workbenchUrl"] == "http://127.0.0.1:8002"


def test_lifecycle_bridge_parses_operations():
    args = desktop_entry.parse_args(["--action", "lifecycle", "--lifecycle-operation", "restart"])
    assert args.lifecycle_operation == "restart"


def test_lifecycle_bridge_refuses_product_writes(monkeypatch):
    entry = _load_desktop_entry_py()
    monkeypatch.setattr(entry, "_append_log", lambda *a, **k: None)

    for operation in ("start", "stop", "force-stop", "restart", "rebuild-and-start", "shutdown"):
        payload = entry._run_lifecycle_bridge(argparse.Namespace(lifecycle_operation=operation))
        assert payload["accepted"] is False
        assert payload["code"] == "control_plane_is_electron"
        assert payload["operation"] == operation
        assert payload["schemaVersion"] == 1


def test_direct_lifecycle_actions_return_electron_takeover_error(monkeypatch, capsys):
    entry = _load_desktop_entry_py()
    monkeypatch.setattr(entry, "_append_log", lambda *a, **k: None)

    code = entry.main(["--action", "start", "--output", "json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert code == 2
    assert payload["accepted"] is False
    assert payload["code"] == "control_plane_is_electron"
    assert "Electron main" in payload["message"]


def test_lifecycle_bridge_rejects_unknown_operation():
    entry = _load_desktop_entry_py()
    with pytest.raises(ValueError):
        entry._run_lifecycle_bridge(argparse.Namespace(lifecycle_operation="taskkill"))


def test_branch_instance_bridge_parses_operations():
    args = desktop_entry.parse_args(
        ["--action", "branch-instance", "--branch-instance-operation", "start", "--instance-id", "worktree:task"]
    )
    assert args.branch_instance_operation == "start"
    assert args.instance_id == "worktree:task"


def test_branch_instance_bridge_refuses_product_writes(monkeypatch):
    entry = _load_desktop_entry_py()
    monkeypatch.setattr(entry, "_append_log", lambda *a, **k: None)

    payload = entry._run_branch_instance_bridge(
        argparse.Namespace(branch_instance_operation="start", instance_id="worktree:task", trigger="")
    )
    assert payload["accepted"] is False
    assert payload["code"] == "control_plane_is_electron"
    assert payload["schemaVersion"] == 1
    assert payload["instanceId"] == "worktree:task"


def test_branch_instance_bridge_observe_is_also_retired(monkeypatch):
    entry = _load_desktop_entry_py()
    monkeypatch.setattr(entry, "_append_log", lambda *a, **k: None)
    payload = entry._run_branch_instance_bridge(
        argparse.Namespace(
            branch_instance_operation="observe-ready",
            instance_id="worktree:task",
            trigger="",
        )
    )
    assert payload["accepted"] is False
    assert payload["code"] == "control_plane_is_electron"


def test_launcher_api_bridge_dispatches_consolidated_state_refresh(monkeypatch):
    entry = _load_desktop_entry_py()
    monkeypatch.setattr(entry, "_append_log", lambda *a, **k: None)
    launcher_module = _fake_launcher_service_module()
    state_refresh_module = types.ModuleType("core.launcher.state_refresh")
    seen = {}

    def build_launcher_state_refresh(*, electron_window_instance_ids=()):
        seen["window_ids"] = list(electron_window_instance_ids)
        return {"schemaVersion": 1, "status": {}, "branchInstances": {"items": []}, "cleanup": {}}

    state_refresh_module.build_launcher_state_refresh = build_launcher_state_refresh
    monkeypatch.setitem(sys.modules, "core.launcher", types.ModuleType("core.launcher"))
    monkeypatch.setitem(sys.modules, "core.launcher.service", launcher_module)
    monkeypatch.setitem(sys.modules, "core.launcher.state_refresh", state_refresh_module)

    payload = entry._run_launcher_api_bridge(
        argparse.Namespace(
            launcher_api_path="state-refresh",
            launcher_api_method="POST",
            launcher_api_body=json.dumps({"electronWindowInstanceIds": ["main", "worktree:task"]}),
        )
    )

    assert payload["ok"] is True
    assert payload["payload"]["schemaVersion"] == 1
    assert seen["window_ids"] == ["main", "worktree:task"]


def test_branch_instance_bridge_rejects_unknown_operation():
    entry = _load_desktop_entry_py()
    with pytest.raises(ValueError):
        entry._run_branch_instance_bridge(
            argparse.Namespace(branch_instance_operation="explode", instance_id="x", trigger="")
        )


def _fake_launcher_service_module():
    launcher_module = types.ModuleType("core.launcher.service")
    launcher_module.LauncherActiveWorkBlocked = type("LauncherActiveWorkBlocked", (Exception,), {})

    def record(marker):
        return lambda *args, **kwargs: {"marker": marker}

    for path, marker in [
        ("settings/workbench-window", "workbench_window"),
        ("settings/startup", "startup"),
        ("developer-mode", "developer_mode"),
        ("developer-mode/noise-overview", "noise"),
        ("developer-mode/cleanup/preview", "cleanup_preview"),
        ("developer-mode/cleanup/apply", "cleanup_apply"),
        ("maintenance/reset/summary", "maintenance_summary"),
        ("maintenance/reset/preview", "maintenance_preview"),
        ("maintenance/reset/apply", "maintenance_apply"),
    ]:
        setattr(launcher_module, f"_{path}", record(marker))
    launcher_module.get_workbench_window_mode_setting = record("workbench_window")
    launcher_module.update_workbench_window_mode = record("workbench_window_put")
    launcher_module.get_launcher_startup_settings = record("startup")
    launcher_module.update_launcher_startup_settings = record("startup_put")
    launcher_module.get_launcher_developer_mode_setting = record("developer_mode")
    launcher_module.update_launcher_developer_mode = record("developer_mode_put")
    launcher_module.reset_launcher_developer_sandbox = record("reset_sandbox")
    launcher_module.get_launcher_developer_noise_overview = record("noise")
    launcher_module.preview_launcher_developer_cleanup = record("cleanup_preview")
    launcher_module.apply_launcher_developer_cleanup = record("cleanup_apply")
    launcher_module.get_launcher_maintenance_summary = record("maintenance_summary")
    launcher_module.preview_launcher_maintenance_plan = record("maintenance_preview")
    launcher_module.apply_launcher_maintenance_plan = record("maintenance_apply")
    launcher_module.get_launcher_status = record("status")
    launcher_module.get_launcher_freshness = record("freshness")
    launcher_module.list_launcher_branch_instances = record("branch_instances")
    launcher_module.cleanup_launcher_branch_instances = record("branch_cleanup")
    return launcher_module


def test_launcher_api_bridge_dispatches_settings_and_maintenance(monkeypatch):
    entry = _load_desktop_entry_py()
    monkeypatch.setattr(entry, "_append_log", lambda *a, **k: None)
    monkeypatch.setitem(sys.modules, "core.launcher", types.ModuleType("core.launcher"))
    monkeypatch.setitem(sys.modules, "core.launcher.service", _fake_launcher_service_module())

    payload = entry._run_launcher_api_bridge(
        argparse.Namespace(launcher_api_path="settings/workbench-window", launcher_api_method="GET", launcher_api_body="")
    )
    assert payload["ok"] is True
    assert payload["payload"]["marker"] == "workbench_window"

    payload = entry._run_launcher_api_bridge(
        argparse.Namespace(
            launcher_api_path="maintenance/reset/apply",
            launcher_api_method="POST",
            launcher_api_body=json.dumps({"profileId": "clean_start"}),
        )
    )
    assert payload["ok"] is True
    assert payload["payload"]["marker"] == "maintenance_apply"

    payload = entry._run_launcher_api_bridge(
        argparse.Namespace(launcher_api_path="status", launcher_api_method="GET", launcher_api_body="")
    )
    assert payload["ok"] is True
    assert payload["payload"]["marker"] == "status"

    payload = entry._run_launcher_api_bridge(
        argparse.Namespace(launcher_api_path="freshness", launcher_api_method="GET", launcher_api_body="")
    )
    assert payload["ok"] is True
    assert payload["payload"]["marker"] == "freshness"

    payload = entry._run_launcher_api_bridge(
        argparse.Namespace(launcher_api_path="branch-instances", launcher_api_method="GET", launcher_api_body="")
    )
    assert payload["ok"] is True
    assert payload["payload"]["marker"] == "branch_instances"

    payload = entry._run_launcher_api_bridge(
        argparse.Namespace(
            launcher_api_path="branch-instances?cleanupMetadata=1",
            launcher_api_method="GET",
            launcher_api_body="",
        )
    )
    assert payload["ok"] is True
    assert payload["payload"]["marker"] == "branch_instances"


def test_launcher_api_bridge_branch_instances_cleanup_metadata_is_opt_in(monkeypatch):
    entry = _load_desktop_entry_py()
    monkeypatch.setattr(entry, "_append_log", lambda *a, **k: None)
    launcher_module = _fake_launcher_service_module()
    seen: list[dict[str, object]] = []

    def capture_list(*args, **kwargs):
        seen.append({"args": args, "kwargs": kwargs})
        return {"items": []}

    launcher_module.list_launcher_branch_instances = capture_list
    monkeypatch.setitem(sys.modules, "core.launcher", types.ModuleType("core.launcher"))
    monkeypatch.setitem(sys.modules, "core.launcher.service", launcher_module)

    default_payload = entry._run_launcher_api_bridge(
        argparse.Namespace(launcher_api_path="branch-instances", launcher_api_method="GET", launcher_api_body="")
    )
    annotated_payload = entry._run_launcher_api_bridge(
        argparse.Namespace(
            launcher_api_path="branch-instances?cleanupMetadata=1",
            launcher_api_method="GET",
            launcher_api_body="",
        )
    )
    assert default_payload["ok"] is True
    assert annotated_payload["ok"] is True
    assert seen[0]["kwargs"] == {}
    assert seen[1]["kwargs"] == {"include_cleanup_metadata": True}


def test_launcher_api_bridge_rejects_unknown_paths(monkeypatch):
    entry = _load_desktop_entry_py()
    monkeypatch.setattr(entry, "_append_log", lambda *a, **k: None)
    monkeypatch.setitem(sys.modules, "core.launcher", types.ModuleType("core.launcher"))
    monkeypatch.setitem(sys.modules, "core.launcher.service", _fake_launcher_service_module())

    payload = entry._run_launcher_api_bridge(
        argparse.Namespace(launcher_api_path="workbench-close-transactions", launcher_api_method="GET", launcher_api_body="")
    )
    assert payload["ok"] is False
    assert "Unsupported launcher api path" in str(payload["message"])


def test_launcher_api_bridge_surfaces_service_errors(monkeypatch):
    entry = _load_desktop_entry_py()
    monkeypatch.setattr(entry, "_append_log", lambda *a, **k: None)
    launcher_module = _fake_launcher_service_module()
    launcher_module.apply_launcher_maintenance_plan = lambda body: (_ for _ in ()).throw(ValueError("active work blocks reset"))
    monkeypatch.setitem(sys.modules, "core.launcher", types.ModuleType("core.launcher"))
    monkeypatch.setitem(sys.modules, "core.launcher.service", launcher_module)

    payload = entry._run_launcher_api_bridge(
        argparse.Namespace(launcher_api_path="maintenance/reset/apply", launcher_api_method="POST", launcher_api_body="{}")
    )
    assert payload["ok"] is False
    assert payload["code"] == "launcher_api_bridge_failed"
    assert "active work blocks reset" in str(payload["message"])


def test_desktop_shell_status_bridge_uses_workspace_root(monkeypatch, tmp_path):
    entry = _load_desktop_entry_py()
    monkeypatch.setattr(entry, "_append_log", lambda *a, **k: None)
    seen = {}

    def fake_inspect(root):
        seen["root"] = Path(root)
        return {"schemaVersion": 1, "stale": True, "reason": "provenance_mismatch"}

    import core.launcher.desktop_shell as shell

    monkeypatch.setattr(shell, "inspect_desktop_shell", fake_inspect)
    payload = entry._desktop_shell_status_bridge(argparse.Namespace(workspace=str(tmp_path)))
    assert payload["stale"] is True
    assert seen["root"] == tmp_path.resolve()


def test_parse_args_accepts_desktop_shell_refresh_flags():
    args = desktop_entry.parse_args(
        ["--action", "schedule-desktop-shell-refresh", "--wait-pid", "12", "--then-lifecycle", "start"]
    )
    assert args.action == "schedule-desktop-shell-refresh"
    assert args.wait_pid == 12
    assert args.then_lifecycle == "start"


def test_parse_args_accepts_launch_desktop_shell_flags():
    args = desktop_entry.parse_args(
        ["--action", "launch-desktop-shell", "--then-lifecycle", "start", "--open-workbench", "--workspace", r"C:\repo"]
    )
    assert args.action == "launch-desktop-shell"
    assert args.then_lifecycle == "start"
    assert args.open_workbench is True
    assert args.workspace == r"C:\repo"


def test_launch_desktop_shell_action_dispatches_to_desktop_shell(monkeypatch, capsys):
    captured: dict[str, object] = {}

    def fake_launch(*, project_root, then_lifecycle, open_workbench):
        captured["project_root"] = project_root
        captured["then_lifecycle"] = then_lifecycle
        captured["open_workbench"] = open_workbench
        return {"schemaVersion": 1, "kind": "unpackaged", "pid": 9, "thenLifecycle": then_lifecycle, "openWorkbench": open_workbench}

    monkeypatch.setattr("core.launcher.desktop_shell.launch_desktop_shell", fake_launch)
    result = desktop_entry.main(
        ["--action", "launch-desktop-shell", "--output", "json", "--then-lifecycle", "start", "--open-workbench"]
    )
    assert result == 0
    assert captured["then_lifecycle"] == "start"
    assert captured["open_workbench"] is True
    payload = json.loads(capsys.readouterr().out)
    assert payload["kind"] == "unpackaged"
    assert payload["pid"] == 9


def test_ensure_latest_launcher_action_dispatches_to_desktop_shell(monkeypatch, capsys):
    captured: dict[str, object] = {}

    def fake_ensure(root):
        captured["root"] = root
        return {
            "schemaVersion": 1,
            "ok": True,
            "electron": {"rebuilt": False, "reason": "current"},
            "frontend": {"skipped": True, "ok": True, "reason": "frontend build is current"},
        }

    monkeypatch.setattr("core.launcher.desktop_shell.ensure_latest_launcher", fake_ensure)
    result = desktop_entry.main(["--action", "ensure-latest-launcher", "--output", "json"])
    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["frontend"]["skipped"] is True
    assert captured["root"] is not None


def test_ensure_frontend_build_action_uses_shared_release_builder(monkeypatch, tmp_path, capsys):
    captured: dict[str, object] = {}

    def fake_ensure(root):
        captured["root"] = root
        return {"skipped": False, "rebuilt": True, "buildKey": "key-1", "dist": str(tmp_path / "release-key-1")}

    monkeypatch.setattr("core.launcher.frontend_build.ensure_frontend_build", fake_ensure)
    result = desktop_entry.main(
        ["--action", "ensure-frontend-build", "--workspace", str(tmp_path), "--output", "json"]
    )

    assert result == 0
    assert captured["root"] == tmp_path.resolve()
    assert json.loads(capsys.readouterr().out) == {
        "schemaVersion": 1,
        "ok": True,
        "skipped": False,
        "rebuilt": True,
        "reason": "frontend build release published",
        "buildKey": "key-1",
        "release": str(tmp_path / "release-key-1"),
    }


def test_parse_args_accepts_state_owned_backend_pid_flag():
    args = desktop_entry.parse_args(
        ["--action", "stop-launcher", "--use-state-owned-backend-pid", "--workspace", r"C:\repo"]
    )
    assert args.action == "stop-launcher"
    assert args.use_state_owned_backend_pid is True
    assert args.workspace == r"C:\repo"


def test_launcher_control_git_current_parses_false_payload(monkeypatch):
    class FakeResponse:
        status = 200

        def read(self) -> bytes:
            return b'{"schemaVersion":1,"current":false}'

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

    monkeypatch.setattr(desktop_entry.urllib.request, "urlopen", lambda *args, **kwargs: FakeResponse())
    assert desktop_entry._launcher_control_git_current(8765) is False


def test_stop_launcher_uses_state_owned_pid_when_workspace_matches(monkeypatch, capsys, tmp_path):
    bridge = _load_desktop_entry_py()
    state = {
        "sessionRole": "launcher_control_surface",
        "launcherBackendPid": 111,
        "launcherBackendLaunchPid": 111,
        "launcherBackendCreateTime": 1.0,
        "launcherBackendExecutable": r"C:\\Python\\pythonw.exe",
        "launcherBackendLaunchCreateTime": 1.0,
        "launcherBackendLaunchExecutable": r"C:\\Python\\pythonw.exe",
        "launcherBrowserWindowPid": 222,
        "launcherBrowserLaunchPid": 222,
        "launcherBrowserWindowCreateTime": 2.0,
        "launcherBrowserWindowExecutable": r"C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
        "launcherBrowserLaunchCreateTime": 2.0,
        "launcherBrowserLaunchExecutable": r"C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
        "launcherControlPort": 8765,
        "runtimeProjectRoot": str(tmp_path),
        "browserManaged": True,
    }
    terminated: list[int] = []
    saved_states: list[dict[str, object]] = []

    monkeypatch.setattr(bridge, "_append_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(bridge, "_read_state", lambda: dict(state))
    monkeypatch.setattr(bridge, "_write_state", lambda next_state: saved_states.append(dict(next_state)))
    monkeypatch.setattr(bridge, "_terminate_pid", lambda pid: terminated.append(pid))
    monkeypatch.setattr(bridge, "_wait_for_launcher_control_stopped", lambda port: True)
    monkeypatch.setattr(bridge, "inspect_process_identity", lambda expected: {"status": "match", "reason": "identity_match"})

    result = bridge.main(
        [
            "--action",
            "stop-launcher",
            "--output",
            "json",
            "--use-state-owned-backend-pid",
            "--workspace",
            str(tmp_path),
        ]
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "stopped"
    assert payload["expectedBackendPid"] == 111
    assert payload["terminatedPids"] == [111, 222]
    assert terminated == [111, 222]
    assert saved_states[-1]["launcherBackendPid"] == 0


def test_stop_launcher_state_owned_pid_rejects_reused_process_identity(monkeypatch, capsys, tmp_path):
    bridge = _load_desktop_entry_py()
    state = {
        "sessionRole": "launcher_control_surface",
        "launcherBackendPid": 111,
        "launcherBackendLaunchPid": 111,
        "launcherBackendCreateTime": 1.0,
        "launcherBackendExecutable": r"C:\\Python\\pythonw.exe",
        "launcherBackendLaunchCreateTime": 1.0,
        "launcherBackendLaunchExecutable": r"C:\\Python\\pythonw.exe",
        "launcherControlPort": 8765,
        "runtimeProjectRoot": str(tmp_path),
    }
    terminated: list[int] = []

    monkeypatch.setattr(bridge, "_append_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(bridge, "_read_state", lambda: dict(state))
    monkeypatch.setattr(bridge, "_write_state", lambda next_state: pytest.fail("mismatched identity must retain state"))
    monkeypatch.setattr(bridge, "_terminate_pid", lambda pid: terminated.append(pid))
    monkeypatch.setattr(
        bridge,
        "inspect_process_identity",
        lambda expected: {"status": "mismatch", "reason": "create_time_mismatch"},
    )

    result = bridge.main(
        [
            "--action",
            "stop-launcher",
            "--output",
            "json",
            "--use-state-owned-backend-pid",
            "--workspace",
            str(tmp_path),
        ]
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "skipped"
    assert payload["reason"] == "state_owned_process_identity_mismatch"
    assert terminated == []


def test_save_launcher_state_captures_pid_create_time_and_executable(monkeypatch):
    bridge = _load_desktop_entry_py()
    saved_states: list[dict[str, object]] = []

    monkeypatch.setattr(
        bridge,
        "capture_process_identity",
        lambda pid: {
            "pid": pid,
            "createTime": float(pid),
            "executable": rf"C:\\managed\\{pid}.exe",
        },
    )
    monkeypatch.setattr(bridge, "_write_state", lambda state: saved_states.append(dict(state)))

    bridge._save_launcher_state(
        {},
        port=8765,
        backend_pid=111,
        browser_pid=222,
        current_signature="sig",
        python_exe=r"C:\\Python\\python.exe",
    )

    persisted = saved_states[-1]
    assert persisted["launcherBackendCreateTime"] == 111.0
    assert persisted["launcherBackendExecutable"] == r"C:\\managed\\111.exe"
    assert persisted["launcherBackendLaunchCreateTime"] == 111.0
    assert persisted["launcherBrowserWindowCreateTime"] == 222.0
    assert persisted["launcherBrowserLaunchExecutable"] == r"C:\\managed\\222.exe"


def test_stop_launcher_state_owned_pid_skips_workspace_mismatch(monkeypatch, capsys, tmp_path):
    bridge = _load_desktop_entry_py()
    state = {
        "sessionRole": "launcher_control_surface",
        "launcherBackendPid": 111,
        "launcherBackendLaunchPid": 111,
        "launcherControlPort": 8765,
        "runtimeProjectRoot": str(tmp_path / "other"),
    }
    terminated: list[int] = []

    monkeypatch.setattr(bridge, "_append_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(bridge, "_read_state", lambda: dict(state))
    monkeypatch.setattr(bridge, "_write_state", lambda next_state: pytest.fail("mismatch must not write state"))
    monkeypatch.setattr(bridge, "_terminate_pid", lambda pid: terminated.append(pid))

    result = bridge.main(
        [
            "--action",
            "stop-launcher",
            "--output",
            "json",
            "--use-state-owned-backend-pid",
            "--workspace",
            str(tmp_path),
        ]
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "skipped"
    assert payload["reason"] == "workspace_mismatch"
    assert terminated == []


def test_open_launcher_replaces_git_stale_backend_when_source_signature_matches(monkeypatch):
    bridge = _load_desktop_entry_py()
    state = {
        "sessionRole": "launcher_control_surface",
        "launcherBackendPid": 111,
        "launcherBackendLaunchPid": 111,
        "launcherBrowserWindowPid": 222,
        "launcherControlSourceSignature": "same-source-sig",
    }
    terminated: list[int] = []
    replace_logs: list[dict[str, object]] = []

    @contextlib.contextmanager
    def fake_lock():
        yield True

    def capture_log(event, **fields):
        if event == "desktop_entry_python.stale_launcher_control.replacing":
            replace_logs.append(fields)

    monkeypatch.setattr(bridge, "_append_log", capture_log)
    monkeypatch.setattr(bridge, "_single_launcher_open_lock", fake_lock)
    monkeypatch.setattr(bridge, "_read_state", lambda: dict(state))
    monkeypatch.setattr(bridge, "_write_state", lambda next_state: None)
    monkeypatch.setattr(bridge, "_source_signature", lambda: "same-source-sig")
    monkeypatch.setattr(bridge, "_launcher_control_port", lambda: 8765)
    monkeypatch.setattr(bridge, "_active_electron_desktop_session_for_workspace", lambda workspace_root: {})
    monkeypatch.setattr(bridge, "_launcher_control_git_current", lambda port: False)
    health_results = iter([True, False, False])
    monkeypatch.setattr(bridge, "_launcher_control_healthy", lambda port: next(health_results))
    monkeypatch.setattr(bridge, "_wait_for_launcher_control_stopped", lambda port: True)
    monkeypatch.setattr(bridge, "_terminate_pid", lambda pid: terminated.append(pid))
    monkeypatch.setattr(bridge, "_start_launcher_backend", lambda python_exe, port: 333)
    monkeypatch.setattr(bridge, "_open_launcher_window", lambda url: 444)
    monkeypatch.setattr(bridge, "_pid_alive", lambda pid: False)

    result = bridge.main(["--action", "launcher"])

    assert result == 0
    assert terminated == [111, 222]
    assert replace_logs[0]["reason"] == "git_freshness"


def test_open_launcher_keeps_backend_when_git_freshness_unknown_and_source_current(monkeypatch):
    bridge = _load_desktop_entry_py()
    state = {
        "sessionRole": "launcher_control_surface",
        "launcherBackendPid": 111,
        "launcherBackendLaunchPid": 111,
        "launcherBrowserWindowPid": 222,
        "launcherControlSourceSignature": "same-source-sig",
    }
    terminated: list[int] = []

    @contextlib.contextmanager
    def fake_lock():
        yield True

    monkeypatch.setattr(bridge, "_append_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(bridge, "_single_launcher_open_lock", fake_lock)
    monkeypatch.setattr(bridge, "_read_state", lambda: dict(state))
    monkeypatch.setattr(bridge, "_write_state", lambda next_state: None)
    monkeypatch.setattr(bridge, "_source_signature", lambda: "same-source-sig")
    monkeypatch.setattr(bridge, "_launcher_control_port", lambda: 8765)
    monkeypatch.setattr(bridge, "_active_electron_desktop_session_for_workspace", lambda workspace_root: {})
    monkeypatch.setattr(bridge, "_launcher_control_git_current", lambda port: None)
    monkeypatch.setattr(bridge, "_launcher_control_healthy", lambda port: True)
    monkeypatch.setattr(bridge, "_terminate_pid", lambda pid: terminated.append(pid))
    monkeypatch.setattr(
        bridge,
        "_start_launcher_backend",
        lambda python_exe, port: pytest.fail("unknown freshness must not start a replacement backend"),
    )
    monkeypatch.setattr(bridge, "_open_launcher_window", lambda url: 444)
    monkeypatch.setattr(bridge, "_pid_alive", lambda pid: True)

    result = bridge.main(["--action", "launcher"])

    assert result == 0
    assert terminated == []
