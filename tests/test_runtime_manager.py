import json
import http.client
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.runtime_manager import cli as runtime_cli
from core.runtime_manager import command_queue
from core.runtime_manager import daemon
from core.runtime_manager import constants
from core.runtime_manager import evolution_store
from core.runtime_manager import process_inventory
from core.runtime_manager import scene_logging
from core.runtime_manager import state_store
from core.runtime_manager import work_run_store
from core.runtime_manager import workbench_controller
from core.runtime_manager.work_run_store import WorkRunStore


def _repeat_last(items):
    values = list(items)
    iterator = iter(values)
    last = values[-1]

    def next_value():
        nonlocal last
        try:
            last = next(iterator)
        except StopIteration:
            pass
        return dict(last)

    return next_value


def _event_payload(events, event_type):
    return next(payload for current_type, payload in events if current_type == event_type)


def _patch_command_queue_events(monkeypatch, events_path):
    def append_event(event_type, payload, *, events_path=None, ensure_dirs=None, suppress_io_errors=True):
        target_path = events_path or events_path
        if target_path is None:
            target_path = events_path
        target_path.open("a", encoding="utf-8").write(
            json.dumps({"type": event_type, "payload": payload}, ensure_ascii=False) + "\n"
        )
        return ""

    monkeypatch.setattr(command_queue, "append_runtime_manager_file_event", append_event)
    monkeypatch.setattr(command_queue, "record_runtime_manager_scene_event", lambda *args, **kwargs: None)


@pytest.fixture(autouse=True)
def _block_real_process_termination(monkeypatch, tmp_path):
    events_path = tmp_path / "runtime-manager-events.jsonl"
    monkeypatch.setattr(daemon, "EVENTS_PATH", events_path)
    monkeypatch.setattr(command_queue, "EVENTS_PATH", events_path)
    monkeypatch.setattr(daemon, "record_runtime_manager_scene_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(command_queue, "record_runtime_manager_scene_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(daemon, "terminate_process_descendants", lambda *args, **kwargs: {"terminated": [], "remaining": []})
    monkeypatch.setattr(
        daemon,
        "terminate_unmanaged_workbench_processes",
        lambda *args, **kwargs: {"supported": True, "requested": [], "terminated": [], "remaining": []},
    )
    monkeypatch.setattr(
        daemon,
        "terminate_workbench_processes",
        lambda *args, **kwargs: {"supported": True, "requested": [], "terminated": [], "remaining": []},
    )


def test_print_status_reports_stale_runtime_manager_source(capsys):
    runtime_cli._print_status(
        {
            "daemonRunning": True,
            "managerPid": 100,
            "projectRoot": "C:/project",
            "statePath": "C:/project/.runtime/runtime-manager/state.json",
            "workbench": {
                "desiredState": "open",
                "observedState": "open",
                "phase": "steady",
                "backendPid": 200,
                "browserWindowPid": 300,
                "url": "http://127.0.0.1:8766",
            },
            "runtimeManager": {"sourceMatches": False},
        }
    )

    output = capsys.readouterr().out
    assert "source changed" in output


def test_cli_command_forwards_stop_manager(monkeypatch):
    calls = []

    monkeypatch.setattr(runtime_cli, "ensure_daemon_running", lambda: calls.append("ensure"))
    monkeypatch.setattr(
        runtime_cli,
        "submit_command",
        lambda command_type, args=None, requested_by="unknown": calls.append((command_type, args, requested_by))
        or {"commandId": "cmd-stop-manager"},
    )

    exit_code = runtime_cli.main(["command", "close_workbench", "--reason", "launcher_stop", "--stop-manager"])

    assert exit_code == 0
    assert calls == [
        "ensure",
        ("close_workbench", {"reason": "launcher_stop", "stopManager": True}, "cli"),
    ]


def test_cli_command_forwards_no_browser_without_stop_manager(monkeypatch):
    calls = []

    monkeypatch.setattr(runtime_cli, "ensure_daemon_running", lambda: calls.append("ensure"))
    monkeypatch.setattr(
        runtime_cli,
        "submit_command",
        lambda command_type, args=None, requested_by="unknown": calls.append((command_type, args, requested_by))
        or {"commandId": "cmd-no-browser"},
    )

    exit_code = runtime_cli.main(["command", "open_workbench", "--reason", "launcher_start", "--no-browser"])

    assert exit_code == 0
    assert calls == [
        "ensure",
        ("open_workbench", {"reason": "launcher_start", "noBrowser": True}, "cli"),
    ]


def test_cli_command_forwards_run_id(monkeypatch):
    calls = []

    monkeypatch.setattr(runtime_cli, "ensure_daemon_running", lambda: calls.append("ensure"))
    monkeypatch.setattr(
        runtime_cli,
        "submit_command",
        lambda command_type, args=None, requested_by="unknown": calls.append((command_type, args, requested_by))
        or {"commandId": "cmd-run-id"},
    )

    exit_code = runtime_cli.main(
        ["command", "restart_self_evolution_run", "--run-id", "web-self-123", "--reason", "code_update"]
    )

    assert exit_code == 0
    assert calls == [
        "ensure",
        ("restart_self_evolution_run", {"reason": "code_update", "runId": "web-self-123"}, "cli"),
    ]


def test_supervised_llm_key_env_sync_patches_stale_runtime_manager_env(monkeypatch):
    model_env = "VIBELUTION_LLM_MODEL_UNIT_SYNC_API_KEY"
    provider_env = "VIBELUTION_LLM_PROVIDER_UNIT_SYNC_API_KEY"
    canonical_env = "MIMO_API_KEY"
    alias_env = "XIAOMI_MIMO_API_KEY"
    secret = "unit-model-secret"
    canonical_secret = "unit-provider-secret"

    monkeypatch.delenv(model_env, raising=False)
    monkeypatch.setenv(provider_env, "already-present")
    monkeypatch.delenv(canonical_env, raising=False)
    monkeypatch.delenv(alias_env, raising=False)
    monkeypatch.setattr(
        daemon,
        "load_public_config",
        lambda: {
            "llm": {
                "model_library": {
                    "unit_model": {
                        "api_key_env": model_env,
                    }
                },
                "providers": {
                    "unit_xiaomi": {
                        "kind": "xiaomi",
                        "api_key_env": provider_env,
                    }
                },
            }
        },
    )
    monkeypatch.setattr(
        daemon,
        "read_persisted_user_env_var",
        lambda name: {
            model_env: secret,
            canonical_env: canonical_secret,
        }.get(name, ""),
    )

    payload = daemon._sync_llm_key_env_from_persisted_user_env(command_type="start_supervised_run")

    assert payload["ok"] is True
    assert payload["envCount"] == 4
    assert payload["alreadyPresentCount"] == 1
    assert payload["syncedCount"] == 2
    assert payload["missingCount"] == 1
    assert model_env in payload["syncedEnvNames"]
    assert canonical_env in payload["syncedEnvNames"]
    assert alias_env in payload["missingEnvNames"]
    assert daemon.os.environ[model_env] == secret
    assert daemon.os.environ[canonical_env] == canonical_secret
    assert secret not in json.dumps(payload)
    assert canonical_secret not in json.dumps(payload)


def test_start_supervised_run_syncs_llm_key_env_before_launch(monkeypatch):
    calls: list[object] = []
    monkeypatch.setattr(
        daemon,
        "_require_fresh_source_for_supervised_run",
        lambda: calls.append("fresh") or {"sourceFresh": True},
    )
    monkeypatch.setattr(
        daemon,
        "_sync_llm_key_env_from_persisted_user_env",
        lambda *, command_type: calls.append(("sync", command_type)) or {"ok": True, "syncedCount": 1},
    )
    monkeypatch.setattr(
        daemon.supervised_control_service,
        "_LOCAL_START_SUPERVISED_RUN",
        lambda payload: calls.append(("start", payload)) or {"runId": "web-supervised-unit"},
    )
    monkeypatch.setattr(
        daemon.RuntimeManagerDaemon,
        "_finish_command",
        lambda self, command_id, ok, message, result_data=None, **kwargs: {
            "commandId": command_id,
            "ok": ok,
            "message": message,
            **(result_data or {}),
        },
    )

    result = daemon.RuntimeManagerDaemon()._handle_start_supervised_run(
        command_id="cmd-unit",
        args={"payload": {"sourceKind": "bundle", "bundleName": "unit_bundle"}},
    )

    assert calls == [
        "fresh",
        ("sync", "start_supervised_run"),
        ("start", {"sourceKind": "bundle", "bundleName": "unit_bundle"}),
    ]
    assert result["ok"] is True
    assert result["llmKeyEnvSync"] == {"ok": True, "syncedCount": 1}


def test_backend_health_probe_treats_connection_reset_as_unhealthy(monkeypatch):
    def fake_open_backend_health_url(*args, **kwargs):
        raise ConnectionResetError(10054, "An existing connection was forcibly closed")

    monkeypatch.setattr(workbench_controller, "_open_backend_health_url", fake_open_backend_health_url)

    assert workbench_controller._is_backend_healthy("http://127.0.0.1:8000") is False


def test_backend_health_probe_treats_http_protocol_error_as_unhealthy(monkeypatch):
    def fake_open_backend_health_url(*args, **kwargs):
        raise workbench_controller.http.client.HTTPException("bad status line")

    monkeypatch.setattr(workbench_controller, "_open_backend_health_url", fake_open_backend_health_url)

    assert workbench_controller._is_backend_healthy("http://127.0.0.1:8000") is False


def test_backend_health_probe_bypasses_environment_proxies(monkeypatch):
    calls = []

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class FakeOpener:
        def open(self, url, *, timeout):
            calls.append(("open", url, timeout))
            return FakeResponse()

    def fake_build_opener(*handlers):
        calls.append(("build_opener", handlers))
        return FakeOpener()

    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setenv("ALL_PROXY", "socks5://127.0.0.1:7890")
    monkeypatch.setattr(workbench_controller.urllib.request, "build_opener", fake_build_opener)

    assert workbench_controller._is_backend_healthy("http://127.0.0.1:8000") is True

    assert calls[0][0] == "build_opener"
    handlers = calls[0][1]
    assert len(handlers) == 1
    assert isinstance(handlers[0], workbench_controller.urllib.request.ProxyHandler)
    assert handlers[0].proxies == {}
    assert calls[1] == ("open", "http://127.0.0.1:8000/api/health", 2.0)


def test_launcher_action_passes_runtime_manager_process_protection(monkeypatch, tmp_path):
    calls = []
    events: list[tuple[str, dict]] = []

    monkeypatch.setattr(workbench_controller, "LAUNCHER_SCRIPT_PATH", tmp_path / "launcher.ps1")
    monkeypatch.setattr(workbench_controller, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(workbench_controller, "configured_backend_port", lambda: 8000)
    monkeypatch.setattr(workbench_controller.os, "getpid", lambda: 29960)
    monkeypatch.setattr(workbench_controller.os, "getppid", lambda: 31096)
    monkeypatch.setattr(
        workbench_controller,
        "append_runtime_manager_file_event",
        lambda event_type, payload, **kwargs: events.append((event_type, payload)) or "2026-05-19T09:00:00+00:00",
    )

    class FakeProcess:
        def __init__(self, *args, **kwargs):
            calls.append({"args": args, "kwargs": kwargs})
            stdout_handle = kwargs["stdout"]
            stderr_handle = kwargs["stderr"]
            stdout_handle.write(b"[Vibelution] ok\n")
            stderr_handle.write(b"")

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(workbench_controller.subprocess, "Popen", FakeProcess)

    result = workbench_controller.run_launcher_action("internal-stop")

    assert result.returncode == 0
    assert calls
    env = calls[0]["kwargs"]["env"]
    assert env["VIBELUTION_PROTECTED_PROCESS_IDS"] == "29960;31096"
    assert env["VIBELUTION_RUNTIME_MANAGER_INTERNAL_LAUNCHER"] == "1"
    assert [event_type for event_type, _payload in events] == [
        "launcher.action.requested",
        "launcher.action.completed",
    ]
    assert events[0][1]["internalAction"] is True
    assert events[0][1]["internalLauncherEnvSet"] is True
    assert events[0][1]["protectedProcessIdsSet"] is True
    assert events[1][1]["returnCode"] == 0


def test_launcher_command_uses_python_adapter_on_posix(monkeypatch, tmp_path):
    launcher_path = tmp_path / "vibelution_launcher.py"
    monkeypatch.setattr(workbench_controller.os, "name", "posix", raising=False)
    monkeypatch.setattr(workbench_controller, "PYTHON_LAUNCHER_SCRIPT_PATH", launcher_path)
    monkeypatch.setattr(workbench_controller.sys, "executable", "/usr/bin/python3")

    args = workbench_controller._launcher_command_args("internal-start", no_browser=True)

    assert args == [
        "/usr/bin/python3",
        str(launcher_path),
        "--action",
        "internal-start",
        "--no-browser",
    ]


def test_launcher_command_keeps_powershell_adapter_on_windows(monkeypatch, tmp_path):
    launcher_path = tmp_path / "vibelution_launcher.ps1"
    monkeypatch.setattr(workbench_controller.os, "name", "nt", raising=False)
    monkeypatch.setattr(workbench_controller, "LAUNCHER_SCRIPT_PATH", launcher_path)

    args = workbench_controller._launcher_command_args("internal-stop", no_browser=True)

    assert args == [
        "powershell.exe",
        "-NoProfile",
        "-WindowStyle",
        "Hidden",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(launcher_path),
        "-Action",
        "internal-stop",
        "-NoBrowser",
    ]


def test_focus_workbench_uses_non_destructive_internal_focus(monkeypatch):
    calls: list[dict[str, object]] = []

    def fake_run_launcher_action(action: str, *, no_browser: bool):
        calls.append({"action": action, "no_browser": no_browser})
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="focused", stderr="")

    monkeypatch.setattr(workbench_controller, "run_launcher_action", fake_run_launcher_action)

    result = workbench_controller.focus_workbench()

    assert result.returncode == 0
    assert calls == [{"action": "internal-focus", "no_browser": False}]


def test_python_launcher_allows_lan_hosts_when_binding_wildcard(monkeypatch):
    import importlib.util

    launcher_path = constants.PROJECT_ROOT / "scripts" / "vibelution_launcher.py"
    spec = importlib.util.spec_from_file_location("vibelution_launcher_for_test", launcher_path)
    assert spec and spec.loader
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)

    monkeypatch.delenv("VIBELUTION_TRUSTED_WEB_HOSTS", raising=False)
    monkeypatch.setattr(launcher, "_local_lan_addresses", lambda: ["192.168.20.30"])

    env = launcher._backend_environment("0.0.0.0")

    assert env["VIBELUTION_TRUSTED_WEB_HOSTS"] == "192.168.20.30"


def test_python_launcher_discovers_lan_address_from_udp_route(monkeypatch):
    import importlib.util

    launcher_path = constants.PROJECT_ROOT / "scripts" / "vibelution_launcher.py"
    spec = importlib.util.spec_from_file_location("vibelution_launcher_for_udp_test", launcher_path)
    assert spec and spec.loader
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def connect(self, _target):
            return None

        def getsockname(self):
            return ("192.168.20.30", 53124)

    monkeypatch.setattr(launcher.socket, "getaddrinfo", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(launcher.socket, "socket", lambda *_args, **_kwargs: FakeSocket())

    assert launcher._local_lan_addresses() == ["192.168.20.30"]


def test_python_launcher_rejects_unauthorized_internal_action(monkeypatch):
    import importlib.util

    launcher_path = constants.PROJECT_ROOT / "scripts" / "vibelution_launcher.py"
    spec = importlib.util.spec_from_file_location("vibelution_launcher_for_internal_auth_test", launcher_path)
    assert spec and spec.loader
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)

    monkeypatch.delenv("VIBELUTION_RUNTIME_MANAGER_INTERNAL_LAUNCHER", raising=False)

    with pytest.raises(RuntimeError, match="Runtime Manager"):
        launcher._assert_internal_action_authorized("internal-stop")

    launcher._assert_internal_action_authorized("stop")


def test_python_launcher_allows_authorized_internal_action(monkeypatch):
    import importlib.util

    launcher_path = constants.PROJECT_ROOT / "scripts" / "vibelution_launcher.py"
    spec = importlib.util.spec_from_file_location("vibelution_launcher_for_internal_allowed_test", launcher_path)
    assert spec and spec.loader
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)

    monkeypatch.setenv("VIBELUTION_RUNTIME_MANAGER_INTERNAL_LAUNCHER", "1")

    launcher._assert_internal_action_authorized("internal-restart")
    launcher._assert_internal_action_authorized("internal-focus")


def test_python_launcher_internal_focus_is_non_destructive(monkeypatch, capsys):
    import importlib.util

    launcher_path = constants.PROJECT_ROOT / "scripts" / "vibelution_launcher.py"
    spec = importlib.util.spec_from_file_location("vibelution_launcher_for_focus_test", launcher_path)
    assert spec and spec.loader
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)

    calls: list[str] = []
    monkeypatch.setenv("VIBELUTION_RUNTIME_MANAGER_INTERNAL_LAUNCHER", "1")
    monkeypatch.setattr(launcher, "_read_state", lambda: {"backendPid": 24680})
    monkeypatch.setattr(launcher, "_pid_alive", lambda pid: int(pid) == 24680)
    monkeypatch.setattr(launcher, "_backend_healthy", lambda port, host: port == 8000 and host == "127.0.0.1")
    monkeypatch.setattr(launcher, "_start_backend", lambda *_args, **_kwargs: calls.append("start") or {})
    monkeypatch.setattr(launcher, "_stop_backend", lambda: calls.append("stop") or {})

    exit_code = launcher.main(["--action", "internal-focus"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "already running" in captured.out
    assert calls == []


def test_python_launcher_main_rejects_unauthorized_internal_stop_before_action(monkeypatch, tmp_path, capsys):
    import importlib.util

    launcher_path = constants.PROJECT_ROOT / "scripts" / "vibelution_launcher.py"
    spec = importlib.util.spec_from_file_location("vibelution_launcher_for_internal_main_test", launcher_path)
    assert spec and spec.loader
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)

    writes: list[dict] = []
    stop_calls: list[str] = []
    monkeypatch.delenv("VIBELUTION_RUNTIME_MANAGER_INTERNAL_LAUNCHER", raising=False)
    monkeypatch.setattr(launcher, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(launcher, "RUNTIME_DIR", tmp_path)
    monkeypatch.setattr(launcher, "_read_state", lambda: {})
    monkeypatch.setattr(launcher, "_write_state", lambda state: writes.append(state))
    monkeypatch.setattr(launcher, "_stop_backend", lambda: stop_calls.append("stop") or {})

    exit_code = launcher.main(["--action", "internal-stop"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Runtime Manager" in captured.err
    assert stop_calls == []
    assert writes[-1]["phase"] == "failed"
    assert "Runtime Manager" in writes[-1]["failureMessage"]


def test_python_launcher_frontend_build_defaults_to_direct_node_build(monkeypatch, tmp_path):
    import importlib.util

    launcher_path = constants.PROJECT_ROOT / "scripts" / "vibelution_launcher.py"
    spec = importlib.util.spec_from_file_location("vibelution_launcher_for_frontend_pm_test", launcher_path)
    assert spec and spec.loader
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)

    project_root = tmp_path / "repo"
    web_dir = project_root / "web"
    web_dir.mkdir(parents=True)
    log_path = tmp_path / "frontend-build.log"
    calls: list[tuple[list[str], str]] = []

    monkeypatch.setattr(launcher, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(launcher, "FRONTEND_BUILD_LOG_PATH", log_path)
    monkeypatch.delenv("VIBELUTION_FRONTEND_PM", raising=False)
    monkeypatch.setattr(launcher, "_node_command", lambda: r"C:\node\node.exe")
    monkeypatch.setattr(
        launcher,
        "_npm_cli_script_for_node",
        lambda node_command: r"C:\node\node_modules\npm\bin\npm-cli.js",
    )
    monkeypatch.setattr(
        launcher,
        "_run_checked",
        lambda args, *, cwd, label: calls.append((list(args), label)),
    )

    launcher._ensure_frontend_build()

    assert calls == [
        ([r"C:\node\node.exe", r"C:\node\node_modules\npm\bin\npm-cli.js", "install"], "node npm-cli.js install"),
        ([r"C:\node\node.exe", str(web_dir / "node_modules" / "typescript" / "bin" / "tsc"), "-b"], "node tsc -b"),
        ([r"C:\node\node.exe", str(web_dir / "node_modules" / "vite" / "bin" / "vite.js"), "build"], "node vite build"),
    ]
    event = json.loads(log_path.read_text(encoding="utf-8").splitlines()[-1])
    assert event["event"] == "frontend_build.ensure"
    assert event["packageManager"] == "npm"
    assert event["needsInstall"] is True
    assert event["needsBuild"] is True


def test_python_launcher_frontend_build_can_opt_into_bun(monkeypatch, tmp_path):
    import importlib.util

    launcher_path = constants.PROJECT_ROOT / "scripts" / "vibelution_launcher.py"
    spec = importlib.util.spec_from_file_location("vibelution_launcher_for_bun_pm_test", launcher_path)
    assert spec and spec.loader
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)

    project_root = tmp_path / "repo"
    web_dir = project_root / "web"
    web_dir.mkdir(parents=True)
    log_path = tmp_path / "frontend-build.log"
    calls: list[tuple[list[str], str]] = []

    monkeypatch.setattr(launcher, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(launcher, "FRONTEND_BUILD_LOG_PATH", log_path)
    monkeypatch.setenv("VIBELUTION_FRONTEND_PM", "bun")
    monkeypatch.setattr(
        launcher,
        "_run_checked",
        lambda args, *, cwd, label: calls.append((list(args), label)),
    )

    launcher._ensure_frontend_build()

    assert calls == [
        (["bun", "install"], "bun install"),
        (["bun", "run", "bun:build"], "bun run bun:build"),
    ]
    event = json.loads(log_path.read_text(encoding="utf-8").splitlines()[-1])
    assert event["event"] == "frontend_build.ensure"
    assert event["packageManager"] == "bun"
    assert event["needsInstall"] is True
    assert event["needsBuild"] is True


def test_launcher_error_detail_prioritizes_stderr_over_progress_stdout():
    detail = daemon._launcher_error_detail(
        subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="[Vibelution] Stopping Vibelution session (runtime manager stop)...\n",
            stderr="actual failure",
        ),
        "fallback",
    )

    assert "actual failure" in detail
    assert "Launcher progress before exit" in detail
    assert "Launcher exit code: 1" in detail


def test_workbench_controller_trusts_only_launcher_marked_backend(monkeypatch):
    monkeypatch.setattr(
        workbench_controller,
        "list_repo_runtime_processes",
        lambda project_root: [
            process_inventory.RuntimeProcess(
                pid=22416,
                parent_pid=1,
                kind="managed_workbench_backend",
                name="pythonw.exe",
                command_line="pythonw scripts/web_workbench.py --port 8000 --no-browser --managed-by-launcher",
                cwd=str(project_root),
                port=8000,
            ),
            process_inventory.RuntimeProcess(
                pid=49780,
                parent_pid=1,
                kind="unmanaged_workbench",
                name="python.exe",
                command_line="python scripts/web_workbench.py --port 8000 --no-browser",
                cwd=str(project_root),
                port=8000,
            ),
        ],
    )

    assert workbench_controller._pid_is_repo_workbench_backend(22416) is True
    assert workbench_controller._pid_is_repo_workbench_backend(49780) is False


def test_observe_workbench_keeps_launcher_control_surface_out_of_project_lifecycle(tmp_path, monkeypatch):
    launcher_state_path = tmp_path / ".runtime" / "launcher" / "state.json"
    launcher_state_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_state_path.write_text(
        json.dumps(
            {
                "sessionRole": "launcher_control_surface",
                "sessionId": "launcher-session",
                "url": "http://127.0.0.1:8000",
                "backendPid": 3200,
                "browserWindowPid": 4500,
                "launcherBrowserWindowPid": 4500,
                "browserManaged": True,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(workbench_controller, "LAUNCHER_STATE_PATH", launcher_state_path)
    monkeypatch.setattr(workbench_controller, "_is_process_alive", lambda pid: int(pid) in {3200, 4500})
    monkeypatch.setattr(workbench_controller, "_is_backend_healthy", lambda url: True)
    monkeypatch.setattr(workbench_controller, "_listening_pid_for_port", lambda port: 3200)
    monkeypatch.setattr(workbench_controller, "_port_is_listening_socket", lambda port: True)
    monkeypatch.setattr(workbench_controller, "_repo_workbench_backend_kind", lambda pid: "managed_workbench_backend")

    snapshot = workbench_controller.observe_workbench()

    assert snapshot["sessionRole"] == "launcher_control_surface"
    assert snapshot["observedState"] == "closed"
    assert snapshot["backendHealthy"] is True
    assert snapshot["browserWindowAlive"] is False
    assert snapshot["launcherBrowserWindowAlive"] is True
    assert snapshot["frontendOrphaned"] is False


def test_load_runtime_snapshot_aligns_legacy_open_session(monkeypatch):
    saved_states: list[dict] = []

    monkeypatch.setattr(
        daemon,
        "load_state",
        lambda: {
            "stateVersion": 3,
            "workbench": {
                "desiredState": "closed",
                "observedState": "closed",
                "phase": "steady",
            },
            "command": {"activeCommandId": ""},
        },
    )
    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        lambda: {
            "observedState": "open",
            "backendPid": 3200,
            "browserLaunchPid": 0,
            "browserWindowPid": 4500,
            "browserManaged": True,
            "sessionId": "legacy-session",
            "url": "http://127.0.0.1:8000",
        },
    )
    monkeypatch.setattr(daemon, "is_daemon_running", lambda: False)
    monkeypatch.setattr(daemon, "load_pid", lambda: 0)
    monkeypatch.setattr(daemon, "save_state", lambda state: saved_states.append(json.loads(json.dumps(state))) or state)

    snapshot = daemon.load_runtime_snapshot()

    assert snapshot["runtimeState"] == "idle"
    assert snapshot["workbench"]["desiredState"] == "open"
    assert snapshot["workbench"]["observedState"] == "open"
    assert snapshot["workbench"]["phase"] == "steady"


def test_load_runtime_snapshot_persists_stale_running_state_as_closed(monkeypatch):
    saved_states: list[dict] = []

    monkeypatch.setattr(
        daemon,
        "load_state",
        lambda: {
            "runtimeState": "running",
            "managerPid": 9912,
            "daemonRunning": True,
            "workbench": {
                "desiredState": "open",
                "observedState": "open",
                "phase": "steady",
                "backendPid": 3200,
                "browserWindowPid": 4500,
                "backendAlive": True,
                "backendHealthy": True,
                "backendObserved": True,
                "backendPortListening": True,
                "statusLine": "Workbench is open (backend PID=3200, window PID=4500)",
            },
            "command": {"activeCommandId": ""},
        },
    )
    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        lambda: {
            "observedState": "closed",
            "backendPid": 0,
            "browserLaunchPid": 0,
            "browserWindowPid": 0,
            "browserManaged": True,
            "backendAlive": False,
            "backendHealthy": False,
            "backendObserved": False,
            "backendPort": 8000,
            "backendPortListening": False,
            "backendPortOwnerPid": 0,
            "backendPortOwnerTrusted": False,
            "backendPortConflict": False,
            "browserWindowAlive": False,
            "sessionId": "",
            "url": "http://127.0.0.1:8000",
            "lifecycleConsistency": "consistent",
        },
    )
    monkeypatch.setattr(daemon, "is_daemon_running", lambda: False)
    monkeypatch.setattr(daemon, "load_pid", lambda: 0)
    monkeypatch.setattr(daemon, "save_state", lambda state: saved_states.append(json.loads(json.dumps(state))) or state)

    snapshot = daemon.load_runtime_snapshot()

    assert snapshot["runtimeState"] == "idle"
    assert snapshot["managerPid"] == 0
    assert snapshot["daemonRunning"] is False
    assert snapshot["workbench"]["desiredState"] == "closed"
    assert snapshot["workbench"]["observedState"] == "closed"
    assert snapshot["workbench"]["backendPid"] == 0
    assert snapshot["workbench"]["browserWindowPid"] == 0
    assert snapshot["workbench"]["statusLine"] == "Workbench is closed."
    assert snapshot["lastError"] == {"scope": "", "message": "", "at": ""}
    assert saved_states
    assert saved_states[-1]["runtimeState"] == "idle"
    assert saved_states[-1]["workbench"]["observedState"] == "closed"


def test_load_runtime_snapshot_marks_missing_managed_window_as_partial(monkeypatch):
    saved_states: list[dict] = []

    monkeypatch.setattr(
        daemon,
        "load_state",
        lambda: {
            "runtimeState": "running",
            "managerPid": 9912,
            "daemonRunning": True,
            "workbench": {
                "desiredState": "open",
                "observedState": "open",
                "phase": "steady",
                "backendPid": 3200,
                "browserWindowPid": 4500,
                "backendAlive": True,
                "backendHealthy": True,
                "backendObserved": True,
                "backendPortListening": True,
                "statusLine": "Workbench is open (backend PID=3200, window PID=4500)",
            },
            "command": {"activeCommandId": ""},
        },
    )
    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        lambda: {
            "observedState": "partial",
            "backendPid": 3200,
            "browserLaunchPid": 0,
            "browserWindowPid": 4500,
            "browserManaged": True,
            "backendAlive": True,
            "backendHealthy": True,
            "backendObserved": True,
            "backendPort": 8000,
            "backendPortListening": True,
            "backendPortOwnerPid": 3200,
            "backendPortOwnerTrusted": True,
            "backendPortConflict": False,
            "browserWindowAlive": False,
            "sessionId": "managed-session",
            "url": "http://127.0.0.1:8000",
            "lifecycleConsistency": "browser_missing",
        },
    )
    monkeypatch.setattr(daemon, "is_daemon_running", lambda: True)
    monkeypatch.setattr(daemon, "load_pid", lambda: 9912)
    monkeypatch.setattr(daemon, "residual_process_payload", lambda **kwargs: {"count": 0, "items": []})
    monkeypatch.setattr(daemon, "save_state", lambda state: saved_states.append(json.loads(json.dumps(state))) or state)

    snapshot = daemon.load_runtime_snapshot()

    workbench = snapshot["workbench"]
    assert snapshot["runtimeState"] == "running"
    assert workbench["desiredState"] == "open"
    assert workbench["observedState"] == "partial"
    assert workbench["phase"] == "steady"
    assert workbench["backendAlive"] is True
    assert workbench["browserWindowAlive"] is False
    assert workbench["lifecycleConsistency"] == "browser_missing"
    assert "window is closed" in workbench["statusLine"]
    assert saved_states
    assert saved_states[-1]["workbench"]["observedState"] == "partial"


def test_load_runtime_snapshot_preserves_failed_close_state(monkeypatch):
    monkeypatch.setattr(
        daemon,
        "load_state",
        lambda: {
            "stateVersion": 8,
            "workbench": {
                "desiredState": "closed",
                "observedState": "open",
                "phase": "failed",
                "failureMessage": "stop failed",
            },
            "command": {"activeCommandId": ""},
        },
    )
    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        lambda: {
            "observedState": "open",
            "backendPid": 3200,
            "browserLaunchPid": 0,
            "browserWindowPid": 4500,
            "browserManaged": True,
            "sessionId": "legacy-session",
            "url": "http://127.0.0.1:8000",
        },
    )
    monkeypatch.setattr(daemon, "is_daemon_running", lambda: True)
    monkeypatch.setattr(daemon, "load_pid", lambda: 9912)

    snapshot = daemon.load_runtime_snapshot()

    assert snapshot["runtimeState"] == "running"
    assert snapshot["workbench"]["desiredState"] == "closed"
    assert snapshot["workbench"]["phase"] == "failed"
    assert snapshot["workbench"]["failureMessage"] == "stop failed"


def test_load_runtime_snapshot_clears_stale_failed_close_after_successful_reopen(monkeypatch):
    monkeypatch.setattr(
        daemon,
        "load_state",
        lambda: {
            "stateVersion": 8,
            "workbench": {
                "desiredState": "closed",
                "observedState": "open",
                "phase": "failed",
                "failureMessage": "stop failed",
            },
            "command": {"activeCommandId": ""},
            "lastError": {"scope": "", "message": "", "at": ""},
        },
    )
    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        lambda: {
            "observedState": "open",
            "backendPid": 3200,
            "browserLaunchPid": 0,
            "browserWindowPid": 4500,
            "browserManaged": True,
            "backendAlive": True,
            "backendHealthy": True,
            "backendObserved": True,
            "backendPort": 8000,
            "backendPortListening": True,
            "backendPortOwnerPid": 3200,
            "backendPortOwnerTrusted": True,
            "backendPortConflict": False,
            "browserWindowAlive": True,
            "sessionId": "managed-session",
            "url": "http://127.0.0.1:8000",
        },
    )
    monkeypatch.setattr(daemon, "is_daemon_running", lambda: True)
    monkeypatch.setattr(daemon, "load_pid", lambda: 9912)
    monkeypatch.setattr(daemon, "_process_source_signature", lambda: "sig-current")

    snapshot = daemon.load_runtime_snapshot()

    assert snapshot["workbench"]["desiredState"] == "open"
    assert snapshot["workbench"]["observedState"] == "open"
    assert snapshot["workbench"]["phase"] == "steady"
    assert snapshot["workbench"]["failureMessage"] == ""
    assert "Workbench is open" in snapshot["workbench"]["statusLine"]


def test_load_runtime_snapshot_recovers_failed_non_lifecycle_error_when_observation_matches(monkeypatch):
    monkeypatch.setattr(
        daemon,
        "load_state",
        lambda: {
            "stateVersion": 9,
            "workbench": {
                "desiredState": "open",
                "observedState": "open",
                "phase": "failed",
                "failureMessage": "missing supervised run",
            },
            "command": {"activeCommandId": ""},
            "lastError": {
                "scope": "stop_supervised_run",
                "message": "missing supervised run",
                "at": "2026-05-19T08:00:00+00:00",
            },
        },
    )
    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        lambda: {
            "observedState": "open",
            "backendPid": 3200,
            "browserLaunchPid": 0,
            "browserWindowPid": 4500,
            "browserManaged": True,
            "sessionId": "managed-session",
            "url": "http://127.0.0.1:8000",
        },
    )
    monkeypatch.setattr(daemon, "is_daemon_running", lambda: True)
    monkeypatch.setattr(daemon, "load_pid", lambda: 9912)
    monkeypatch.setattr(daemon, "_process_source_signature", lambda: "sig-current")

    snapshot = daemon.load_runtime_snapshot()

    assert snapshot["workbench"]["phase"] == "steady"
    assert snapshot["workbench"]["failureMessage"] == ""
    assert "Workbench is open" in snapshot["workbench"]["statusLine"]


def test_handle_start_supervised_run_returns_snapshot(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    scene_events: list[tuple[str, dict]] = []
    monkeypatch.setattr(daemon, "load_state", lambda: {"command": {}, "workbench": {}})
    monkeypatch.setattr(daemon, "save_state", lambda state: state)
    monkeypatch.setattr(daemon, "now_iso", lambda: "2026-05-19T08:00:00+00:00")
    monkeypatch.setattr(daemon, "observe_workbench", lambda: {"observedState": "closed"})
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(daemon, "_process_source_signature", lambda: "sig-current")
    monkeypatch.setattr(daemon, "_disk_source_signature", lambda: "sig-current")
    monkeypatch.setattr(
        daemon,
        "record_runtime_manager_scene_event",
        lambda event_type, payload, **kwargs: scene_events.append((event_type, payload)),
    )
    monkeypatch.setattr(
        daemon,
        "_sync_llm_key_env_from_persisted_user_env",
        lambda *, command_type: {"ok": True, "commandType": command_type, "syncedCount": 0},
    )
    monkeypatch.setattr(
        daemon.supervised_control_service,
        "_LOCAL_START_SUPERVISED_RUN",
        lambda payload: {"runId": "web-supervised-managed", "status": "queued", "payload": payload},
    )

    result = runtime_daemon._handle_start_supervised_run(
        command_id="cmd-1",
        args={"payload": {"sourceKind": "bundle", "bundleName": "managed_bundle"}},
    )

    assert result["ok"] is True
    assert result["runId"] == "web-supervised-managed"
    assert result["snapshot"]["status"] == "queued"
    assert result["sourceFreshness"]["sourceFresh"] is True
    assert result["llmKeyEnvSync"] == {"ok": True, "commandType": "start_supervised_run", "syncedCount": 0}
    assert scene_events == [
        (
            "supervised_run.preflight.source_fresh",
            {
                "processSourceSignature": "sig-current",
                "diskSourceSignature": "sig-current",
                "sourceFresh": True,
                "signaturePathsCount": len(daemon._SOURCE_SIGNATURE_PATHS),
            },
        )
    ]


def test_runtime_manager_source_signature_includes_supervised_harness_files():
    paths = set(daemon._SOURCE_SIGNATURE_PATHS)

    assert Path("scripts/evolution_harness.py") in paths
    assert Path("core/evaluation/dataset_adapters.py") in paths
    assert Path("core/evaluation/dataset_environment.py") in paths
    assert Path("core/evaluation/supervised_evolution.py") in paths
    assert Path("core/evaluation/supervised_workbench.py") in paths
    assert Path("core/evaluation/dataset_registry.py") in paths
    assert Path("core/orchestration/turn_runtime.py") in paths


def test_handle_start_supervised_run_blocks_stale_supervised_source(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    scene_events: list[tuple[str, dict]] = []
    monkeypatch.setattr(daemon, "_process_source_signature", lambda: "sig-old")
    monkeypatch.setattr(daemon, "_disk_source_signature", lambda: "sig-new")
    monkeypatch.setattr(
        daemon,
        "record_runtime_manager_scene_event",
        lambda event_type, payload, **kwargs: scene_events.append((event_type, payload)),
    )

    def fail_if_called(payload):
        raise AssertionError("_LOCAL_START_SUPERVISED_RUN should not run with stale runtime manager source")

    monkeypatch.setattr(daemon.supervised_control_service, "_LOCAL_START_SUPERVISED_RUN", fail_if_called)

    with pytest.raises(daemon.RuntimeManagerStaleSourceError, match="源码已过期"):
        runtime_daemon._handle_start_supervised_run(
            command_id="cmd-stale",
            args={"payload": {"sourceKind": "bundle", "bundleName": "managed_bundle"}},
        )

    assert scene_events == [
        (
            "supervised_run.preflight.stale_runtime_manager_source",
            {
                "processSourceSignature": "sig-old",
                "diskSourceSignature": "sig-new",
                "sourceFresh": False,
                "signaturePathsCount": len(daemon._SOURCE_SIGNATURE_PATHS),
            },
        )
    ]


def test_runtime_manager_active_work_runs_collects_destructive_guard_sources(monkeypatch):
    from core.web.services import chat_room_service, session_service, supervised_worktree_evolution_service

    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        daemon,
        "build_evolution_summary",
        lambda: {
            "self": {"activeRunId": "self-live", "activeStatus": "running"},
            "supervised": {"activeRunId": "supervised-done", "activeStatus": "completed"},
        },
    )
    monkeypatch.setattr(
        session_service,
        "list_active_session_work_runs",
        lambda: [
            {"runId": "chat-live", "runKind": "chat_turn", "sessionId": "session-a", "status": "running"},
            {"runId": "chat-done", "runKind": "chat_turn", "sessionId": "session-b", "status": "completed"},
        ],
    )
    monkeypatch.setattr(
        chat_room_service,
        "list_active_chat_room_work_runs",
        lambda: [{"roundId": "round-live", "runKind": "chat_room_round", "status": "running"}],
    )
    monkeypatch.setattr(
        supervised_worktree_evolution_service,
        "get_active_supervised_worktree_run",
        lambda: {"runId": "worktree-live", "runKind": "supervised_worktree_evolution_run", "status": "queued"},
    )
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))

    active = daemon._runtime_manager_active_work_runs()

    assert active == [
        {"kind": "self_evolution_run", "runId": "self-live", "status": "running", "sessionId": ""},
        {"kind": "chat_turn", "runId": "chat-live", "status": "running", "sessionId": "session-a"},
        {"kind": "chat_room_round", "runId": "round-live", "status": "running", "sessionId": ""},
        {
            "kind": "supervised_worktree_evolution_run",
            "runId": "worktree-live",
            "status": "queued",
            "sessionId": "",
        },
    ]
    assert events == []


def test_runtime_manager_active_work_runs_ignores_needs_continue_chat_turn(monkeypatch):
    from core.web.services import chat_room_service, session_service, supervised_worktree_evolution_service

    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(
        session_service,
        "list_active_session_work_runs",
        lambda: [
            {
                "runId": "chat-waiting",
                "runKind": "chat_turn",
                "sessionId": "session-a",
                "status": "needs_continue",
                "finishedAt": "2026-06-05T11:30:33Z",
            },
            {
                "runId": "chat-finished-running",
                "runKind": "chat_turn",
                "sessionId": "session-c",
                "status": "running",
                "finishedAt": "2026-06-05T11:30:34Z",
            },
            {
                "runId": "chat-live",
                "runKind": "chat_turn",
                "sessionId": "session-b",
                "status": "running",
            },
        ],
    )
    monkeypatch.setattr(chat_room_service, "list_active_chat_room_work_runs", lambda: [])
    monkeypatch.setattr(supervised_worktree_evolution_service, "get_active_supervised_worktree_run", lambda: None)

    active = daemon._runtime_manager_active_work_runs()

    assert active == [
        {"kind": "chat_turn", "runId": "chat-live", "status": "running", "sessionId": "session-b"}
    ]


def test_handle_retry_supervised_run_returns_new_snapshot(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    scene_events: list[tuple[str, dict]] = []
    monkeypatch.setattr(daemon, "load_state", lambda: {"command": {}, "workbench": {}})
    monkeypatch.setattr(daemon, "save_state", lambda state: state)
    monkeypatch.setattr(daemon, "now_iso", lambda: "2026-05-19T08:00:00+00:00")
    monkeypatch.setattr(daemon, "observe_workbench", lambda: {"observedState": "closed"})
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(daemon, "_process_source_signature", lambda: "sig-current")
    monkeypatch.setattr(daemon, "_disk_source_signature", lambda: "sig-current")
    monkeypatch.setattr(
        daemon,
        "record_runtime_manager_scene_event",
        lambda event_type, payload, **kwargs: scene_events.append((event_type, payload)),
    )
    monkeypatch.setattr(
        daemon,
        "_sync_llm_key_env_from_persisted_user_env",
        lambda *, command_type: {"ok": True, "commandType": command_type, "syncedCount": 0},
    )
    monkeypatch.setattr(
        daemon.supervised_control_service,
        "_LOCAL_RETRY_SUPERVISED_RUN",
        lambda run_id: {"runId": "web-supervised-retry", "status": "queued", "retryOfRunId": run_id},
    )

    result = runtime_daemon._handle_retry_supervised_run(
        command_id="cmd-retry",
        args={"runId": "web-supervised-old"},
    )

    assert result["ok"] is True
    assert result["runId"] == "web-supervised-retry"
    assert result["snapshot"]["retryOfRunId"] == "web-supervised-old"
    assert result["sourceFreshness"]["sourceFresh"] is True
    assert result["llmKeyEnvSync"] == {"ok": True, "commandType": "retry_supervised_run", "syncedCount": 0}
    assert [event_type for event_type, _payload in scene_events] == ["supervised_run.preflight.source_fresh"]


def test_handle_retry_supervised_run_blocks_stale_supervised_source(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    scene_events: list[tuple[str, dict]] = []
    monkeypatch.setattr(daemon, "_process_source_signature", lambda: "sig-old")
    monkeypatch.setattr(daemon, "_disk_source_signature", lambda: "sig-new")
    monkeypatch.setattr(
        daemon,
        "record_runtime_manager_scene_event",
        lambda event_type, payload, **kwargs: scene_events.append((event_type, payload)),
    )

    def fail_if_called(run_id):
        raise AssertionError("_LOCAL_RETRY_SUPERVISED_RUN should not run with stale runtime manager source")

    monkeypatch.setattr(daemon.supervised_control_service, "_LOCAL_RETRY_SUPERVISED_RUN", fail_if_called)

    with pytest.raises(daemon.RuntimeManagerStaleSourceError, match="源码已过期"):
        runtime_daemon._handle_retry_supervised_run(
            command_id="cmd-retry-stale",
            args={"runId": "web-supervised-old"},
        )

    assert scene_events == [
        (
            "supervised_run.preflight.stale_runtime_manager_source",
            {
                "processSourceSignature": "sig-old",
                "diskSourceSignature": "sig-new",
                "sourceFresh": False,
                "signaturePathsCount": len(daemon._SOURCE_SIGNATURE_PATHS),
            },
        )
    ]


def test_run_forever_refreshes_manager_started_at(monkeypatch):
    class StopLoop(Exception):
        pass

    runtime_daemon = daemon.RuntimeManagerDaemon()
    saved_states: list[dict] = []
    timestamps = iter(["2026-05-19T08:00:00+00:00", "2026-05-19T08:00:01+00:00"])

    monkeypatch.setattr(daemon, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(daemon, "recover_processing_queue", lambda: None)
    monkeypatch.setattr(daemon, "save_pid", lambda pid: None)
    monkeypatch.setattr(
        daemon,
        "load_state",
        lambda: {
            "startedAt": "2026-05-18T01:00:00+00:00",
            "command": {},
            "workbench": {},
        },
    )
    monkeypatch.setattr(daemon, "now_iso", lambda: next(timestamps))
    monkeypatch.setattr(daemon, "observe_workbench", lambda: {"observedState": "closed"})
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(daemon, "_process_source_signature", lambda: "sig-current")
    monkeypatch.setattr(daemon, "save_state", lambda state: saved_states.append(json.loads(json.dumps(state))) or state)

    def stop_after_startup():
        raise StopLoop()

    monkeypatch.setattr(daemon, "claim_next_command", stop_after_startup)

    with pytest.raises(StopLoop):
        runtime_daemon.run_forever()

    assert saved_states[0]["startedAt"] == "2026-05-19T08:00:00+00:00"
    assert saved_states[0]["runtimeManager"]["sourceSignature"] == "sig-current"


def test_run_forever_recovers_processing_queue_after_startup_reconcile(monkeypatch):
    class StopLoop(Exception):
        pass

    runtime_daemon = daemon.RuntimeManagerDaemon()
    state_store = {
        "runtimeState": "stopping",
        "managerPid": 7711,
        "daemonRunning": True,
        "startedAt": "2026-06-04T09:03:15+00:00",
        "command": {
            "activeCommandId": "cmd-old-close",
            "activeType": "close_workbench",
            "requestedBy": "web_ui",
            "stopManager": True,
        },
        "workbench": {
            "desiredState": "closed",
            "observedState": "open",
            "phase": "closing",
        },
    }
    recovered_states: list[dict] = []

    monkeypatch.setattr(daemon, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(daemon, "save_pid", lambda pid: None)
    monkeypatch.setattr(daemon, "load_state", lambda: json.loads(json.dumps(state_store)))
    monkeypatch.setattr(daemon, "now_iso", lambda: "2026-06-04T09:20:24+00:00")
    monkeypatch.setattr(daemon, "observe_workbench", lambda: {"observedState": "closed"})
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(daemon, "_process_source_signature", lambda: "sig-current")

    def fake_save_state(state):
        state_store.clear()
        state_store.update(json.loads(json.dumps(state)))
        return state

    def fake_recover_processing_queue():
        recovered_states.append(json.loads(json.dumps(state_store)))

    monkeypatch.setattr(daemon, "save_state", fake_save_state)
    monkeypatch.setattr(daemon, "recover_processing_queue", fake_recover_processing_queue)
    monkeypatch.setattr(daemon, "claim_next_command", lambda: (_ for _ in ()).throw(StopLoop()))
    monkeypatch.setattr(daemon, "clear_pid", lambda pid: None)

    with pytest.raises(StopLoop):
        runtime_daemon.run_forever()

    assert recovered_states
    recovered = recovered_states[0]
    assert recovered["runtimeState"] == "running"
    assert recovered["managerPid"] == runtime_daemon._pid
    assert recovered["daemonRunning"] is True
    assert recovered["workbench"]["desiredState"] == "closed"
    assert recovered["workbench"]["observedState"] == "closed"
    assert recovered["workbench"]["phase"] == "closing"


def test_daemon_unexpected_exit_marks_manager_not_running(monkeypatch):
    saved_states: list[dict] = []

    monkeypatch.setattr(
        daemon,
        "load_state",
        lambda: {
            "runtimeState": "running",
            "managerPid": 9912,
            "daemonRunning": True,
            "command": {"activeCommandId": ""},
            "workbench": {"desiredState": "open", "observedState": "open", "phase": "steady"},
        },
    )
    monkeypatch.setattr(daemon, "now_iso", lambda: "2026-05-24T08:00:00+00:00")
    monkeypatch.setattr(daemon, "save_state", lambda state: saved_states.append(json.loads(json.dumps(state))) or state)

    daemon._mark_daemon_not_running_after_exit(manager_pid=9912)

    assert saved_states[-1]["runtimeState"] == "idle"
    assert saved_states[-1]["managerPid"] == 0
    assert saved_states[-1]["daemonRunning"] is False
    assert saved_states[-1]["lastStoppedAt"] == "2026-05-24T08:00:00+00:00"
    assert saved_states[-1]["lastStoppedManagerPid"] == 9912


def test_daemon_unexpected_exit_does_not_overwrite_newer_manager(monkeypatch):
    saved_states: list[dict] = []

    monkeypatch.setattr(
        daemon,
        "load_state",
        lambda: {
            "runtimeState": "running",
            "managerPid": 2000,
            "daemonRunning": True,
            "command": {},
            "workbench": {},
        },
    )
    monkeypatch.setattr(daemon, "save_state", lambda state: saved_states.append(state) or state)

    daemon._mark_daemon_not_running_after_exit(manager_pid=9912)

    assert saved_states == []


def test_run_forever_cleans_descendants_before_completing_stop_daemon(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    order: list[str] = []

    monkeypatch.setattr(daemon, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(daemon, "recover_processing_queue", lambda: None)
    monkeypatch.setattr(daemon, "save_pid", lambda pid: None)
    monkeypatch.setattr(
        daemon,
        "load_state",
        lambda: {
            "startedAt": "2026-05-18T01:00:00+00:00",
            "command": {},
            "workbench": {},
        },
    )
    monkeypatch.setattr(daemon, "now_iso", lambda: "2026-05-19T08:00:00+00:00")
    monkeypatch.setattr(daemon, "observe_workbench", lambda: {"observedState": "closed"})
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(daemon, "_process_source_signature", lambda: "sig-current")
    monkeypatch.setattr(daemon, "save_state", lambda state: state)

    commands = iter(
        [
            (
                "cmd-path",
                {
                    "commandId": "cmd-stop",
                    "type": "close_workbench",
                    "requestedBy": "test",
                    "args": {"stopManager": True},
                },
            )
        ]
    )
    monkeypatch.setattr(daemon, "claim_next_command", lambda: next(commands))
    monkeypatch.setattr(
        runtime_daemon,
        "_handle_command",
        lambda payload: {
            "commandId": payload["commandId"],
            "accepted": True,
            "completed": True,
            "ok": True,
            "message": "closed",
            "stopDaemon": True,
        },
    )
    monkeypatch.setattr(
        daemon,
        "_prepare_daemon_shutdown",
        lambda: order.append("cleanup") or {"closedEvolutionRuns": [], "descendantCleanup": {"terminated": [991]}},
    )
    monkeypatch.setattr(
        daemon,
        "complete_command",
        lambda path, result: order.append(f"complete:{result['descendantCleanup']['terminated'][0]}"),
    )
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: order.append(event_type))
    monkeypatch.setattr(daemon, "clear_pid", lambda pid: order.append("clear_pid"))
    def fake_exit(code: int = 0):
        order.append(f"exit:{code}")
        raise SystemExit(code)

    monkeypatch.setattr(daemon, "_exit_current_process", fake_exit)

    with pytest.raises(SystemExit) as exit_info:
        runtime_daemon.run_forever()

    assert "cleanup" in order
    assert "daemon.stopped" in order
    assert "complete:991" in order
    assert order.index("cleanup") < order.index("complete:991")
    assert order.index("daemon.stopped") < order.index("complete:991")
    assert order[-3:] == ["clear_pid", "exit:0", "clear_pid"]
    assert exit_info.value.code == 0


def test_run_forever_marks_runtime_stopping_then_finalizes_idle_before_exit(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    saved_states: list[dict] = []
    loaded_state = {
        "runtimeState": "running",
        "startedAt": "2026-05-18T01:00:00+00:00",
        "command": {},
        "workbench": {},
    }

    monkeypatch.setattr(daemon, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(daemon, "recover_processing_queue", lambda: None)
    monkeypatch.setattr(daemon, "save_pid", lambda pid: None)
    monkeypatch.setattr(daemon, "load_state", lambda: json.loads(json.dumps(loaded_state)))
    monkeypatch.setattr(daemon, "now_iso", lambda: "2026-05-19T08:00:00+00:00")
    monkeypatch.setattr(daemon, "observe_workbench", lambda: {"observedState": "closed"})
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(daemon, "_process_source_signature", lambda: "sig-current")

    def fake_save_state(state):
        loaded_state.clear()
        loaded_state.update(json.loads(json.dumps(state)))
        saved_states.append(json.loads(json.dumps(state)))
        return state

    monkeypatch.setattr(daemon, "save_state", fake_save_state)
    monkeypatch.setattr(
        daemon,
        "claim_next_command",
        lambda: (
            "cmd-path",
            {
                "commandId": "cmd-stop",
                "type": "close_workbench",
                "requestedBy": "test",
                "args": {"stopManager": True},
            },
        ),
    )
    monkeypatch.setattr(
        runtime_daemon,
        "_handle_command",
        lambda payload: {
            "commandId": payload["commandId"],
            "accepted": True,
            "completed": True,
            "ok": True,
            "message": "closed",
            "stopDaemon": True,
        },
    )
    monkeypatch.setattr(daemon, "_prepare_daemon_shutdown", lambda: {"closedEvolutionRuns": [], "descendantCleanup": {}})
    monkeypatch.setattr(daemon, "complete_command", lambda path, result: None)
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: None)
    monkeypatch.setattr(daemon, "clear_pid", lambda pid: None)

    def fake_exit(code: int = 0):
        raise SystemExit(code)

    monkeypatch.setattr(daemon, "_exit_current_process", fake_exit)

    with pytest.raises(SystemExit):
        runtime_daemon.run_forever()

    assert any(state.get("runtimeState") == "stopping" for state in saved_states)
    assert saved_states[-1]["runtimeState"] == "idle"
    assert saved_states[-1]["managerPid"] == 0
    assert saved_states[-1]["daemonRunning"] is False
    assert saved_states[-1]["lastStoppedManagerPid"] == runtime_daemon._pid
    assert saved_states[-1]["workbench"]["desiredState"] == "closed"
    assert saved_states[-1]["workbench"]["observedState"] == "closed"
    assert saved_states[-1]["workbench"]["phase"] == "steady"


def test_reconcile_observation_keeps_daemon_running_true_and_preserves_stopping(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()

    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        lambda: {
            "observedState": "closed",
            "backendPid": 0,
            "browserLaunchPid": 0,
            "browserWindowPid": 0,
            "backendAlive": False,
            "backendHealthy": False,
            "backendObserved": False,
            "backendPort": 8000,
            "backendPortListening": False,
            "backendPortOwnerPid": 0,
            "backendPortOwnerTrusted": False,
            "backendPortConflict": False,
            "browserWindowAlive": False,
            "browserManaged": True,
            "sessionId": "",
            "url": "http://127.0.0.1:8000",
        },
    )
    monkeypatch.setattr(daemon, "residual_process_payload", lambda **kwargs: {"count": 0, "items": []})
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(daemon, "_process_source_signature", lambda: "sig-current")

    state = runtime_daemon._reconcile_observation(
        {
            "runtimeState": "stopping",
            "daemonRunning": False,
            "command": {},
            "workbench": {"desiredState": "closed", "observedState": "closed", "phase": "steady"},
        }
    )

    assert state["runtimeState"] == "stopping"
    assert state["daemonRunning"] is True
    assert state["managerPid"] == runtime_daemon._pid


def test_reconcile_observation_clears_stale_failed_close_after_successful_reopen(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()

    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        lambda: {
            "observedState": "open",
            "backendPid": 3200,
            "browserLaunchPid": 4500,
            "browserWindowPid": 4500,
            "backendAlive": True,
            "backendHealthy": True,
            "backendObserved": True,
            "backendPort": 8000,
            "backendPortListening": True,
            "backendPortOwnerPid": 3200,
            "backendPortOwnerTrusted": True,
            "backendPortConflict": False,
            "browserWindowAlive": True,
            "browserManaged": True,
            "sessionId": "managed-session",
            "url": "http://127.0.0.1:8000",
            "lifecycleConsistency": "consistent",
        },
    )
    monkeypatch.setattr(daemon, "residual_process_payload", lambda **kwargs: {"count": 0, "items": []})
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(daemon, "_process_source_signature", lambda: "sig-current")

    state = runtime_daemon._reconcile_observation(
        {
            "runtimeState": "running",
            "daemonRunning": True,
            "command": {"activeCommandId": ""},
            "lastError": {"scope": "", "message": "", "at": ""},
            "workbench": {
                "desiredState": "closed",
                "observedState": "open",
                "phase": "failed",
                "failureMessage": "stop failed",
            },
        }
    )

    workbench = state["workbench"]
    assert workbench["desiredState"] == "open"
    assert workbench["observedState"] == "open"
    assert workbench["phase"] == "steady"
    assert workbench["failureMessage"] == ""
    assert "Workbench is open" in workbench["statusLine"]


def test_reconcile_observation_cleans_up_orphaned_browser(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    events: list[tuple[str, dict]] = []
    observations = _repeat_last(
        [
            {
                "observedState": "open",
                "backendPid": 0,
                "browserLaunchPid": 12132,
                "browserWindowPid": 12132,
                "backendAlive": False,
                "backendHealthy": False,
                "backendObserved": False,
                "backendPort": 8000,
                "backendPortListening": False,
                "backendPortOwnerPid": 0,
                "backendPortOwnerTrusted": False,
                "backendPortConflict": False,
                "browserWindowAlive": True,
                "browserManaged": True,
                "backendMissing": True,
                "frontendOrphaned": True,
                "lifecycleConsistency": "orphaned_browser",
                "sessionId": "stale-session",
                "url": "http://127.0.0.1:8000",
            },
            {
                "observedState": "closed",
                "backendPid": 0,
                "browserLaunchPid": 0,
                "browserWindowPid": 0,
                "backendAlive": False,
                "backendHealthy": False,
                "backendObserved": False,
                "backendPort": 8000,
                "backendPortListening": False,
                "backendPortOwnerPid": 0,
                "backendPortOwnerTrusted": False,
                "backendPortConflict": False,
                "browserWindowAlive": False,
                "browserManaged": True,
                "backendMissing": False,
                "frontendOrphaned": False,
                "lifecycleConsistency": "consistent",
                "sessionId": "",
                "url": "http://127.0.0.1:8000",
            },
        ]
    )

    monkeypatch.setattr(daemon, "observe_workbench", observations)
    monkeypatch.setattr(daemon, "residual_process_payload", lambda **kwargs: {"count": 0, "items": []})
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(daemon, "_process_source_signature", lambda: "sig-current")
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))
    monkeypatch.setattr(daemon, "close_workbench", lambda: subprocess.CompletedProcess(args=[], returncode=0, stdout="closed", stderr=""))

    state = runtime_daemon._reconcile_observation(
        {
            "runtimeState": "running",
            "command": {"activeCommandId": ""},
            "workbench": {"desiredState": "open", "observedState": "open", "phase": "steady"},
        }
    )

    workbench = state["workbench"]
    assert workbench["desiredState"] == "closed"
    assert workbench["observedState"] == "closed"
    assert workbench["phase"] == "steady"
    assert workbench["frontendOrphaned"] is False
    assert workbench["lifecycleConsistency"] == "consistent"
    assert workbench["failureMessage"] == ""
    assert [event_type for event_type, _ in events] == [
        "workbench.consistency.orphaned_browser_detected",
        "workbench.consistency.orphaned_browser_cleanup_requested",
        "workbench.consistency.orphaned_browser_cleanup_succeeded",
    ]
    assert events[0][1]["browserWindowPid"] == 12132


def test_reconcile_observation_does_not_fail_opening_orphaned_browser(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    events: list[tuple[str, dict]] = []

    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        lambda: {
            "observedState": "open",
            "backendPid": 0,
            "browserLaunchPid": 12132,
            "browserWindowPid": 12132,
            "backendAlive": False,
            "backendHealthy": False,
            "backendObserved": False,
            "backendPort": 8000,
            "backendPortListening": False,
            "backendPortOwnerPid": 0,
            "backendPortOwnerTrusted": False,
            "backendPortConflict": False,
            "browserWindowAlive": True,
            "browserManaged": True,
            "backendMissing": True,
            "frontendOrphaned": True,
            "lifecycleConsistency": "orphaned_browser",
            "sessionId": "starting-session",
            "url": "http://127.0.0.1:8000",
        },
    )
    monkeypatch.setattr(daemon, "residual_process_payload", lambda **kwargs: {"count": 0, "items": []})
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(daemon, "_process_source_signature", lambda: "sig-current")
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))

    state = runtime_daemon._reconcile_observation(
        {
            "runtimeState": "running",
            "command": {"activeCommandId": "cmd-open", "activeType": "open_workbench"},
            "workbench": {
                "desiredState": "open",
                "observedState": "closed",
                "phase": "opening",
                "failureMessage": "",
            },
        }
    )

    workbench = state["workbench"]
    assert workbench["desiredState"] == "open"
    assert workbench["observedState"] == "open"
    assert workbench["phase"] == "opening"
    assert workbench["frontendOrphaned"] is True
    assert workbench["lifecycleConsistency"] == "orphaned_browser"
    assert workbench["failureMessage"] == ""
    assert events == []


def test_reconcile_observation_cleans_closed_residual_processes(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    events: list[tuple[str, dict]] = []
    observations = _repeat_last(
        [
            {
                "observedState": "closed",
                "backendPid": 0,
                "browserLaunchPid": 0,
                "browserWindowPid": 0,
                "backendAlive": False,
                "backendHealthy": False,
                "backendObserved": False,
                "backendPort": 8000,
                "backendPortListening": True,
                "backendPortOwnerPid": 53180,
                "backendPortOwnerKind": "unmanaged_workbench",
                "backendPortOwnerTrusted": False,
                "backendPortOwnerResidual": True,
                "backendPortConflict": False,
                "browserWindowAlive": False,
                "browserManaged": True,
                "backendMissing": False,
                "frontendOrphaned": False,
                "lifecycleConsistency": "residual_backend",
                "sessionId": "",
                "url": "http://127.0.0.1:8000",
            },
            {
                "observedState": "closed",
                "backendPid": 0,
                "browserLaunchPid": 0,
                "browserWindowPid": 0,
                "backendAlive": False,
                "backendHealthy": False,
                "backendObserved": False,
                "backendPort": 8000,
                "backendPortListening": False,
                "backendPortOwnerPid": 0,
                "backendPortOwnerKind": "",
                "backendPortOwnerTrusted": False,
                "backendPortOwnerResidual": False,
                "backendPortConflict": False,
                "browserWindowAlive": False,
                "browserManaged": True,
                "backendMissing": False,
                "frontendOrphaned": False,
                "lifecycleConsistency": "consistent",
                "sessionId": "",
                "url": "http://127.0.0.1:8000",
            },
        ]
    )
    residual_payloads = iter(
        [
            {
                "count": 2,
                "items": [
                    {"pid": 11956, "kind": "unmanaged_frontend_dev_server", "port": 5173},
                    {"pid": 53180, "kind": "unmanaged_workbench", "port": 8000},
                ],
            },
            {"count": 0, "items": []},
        ]
    )

    monkeypatch.setattr(daemon, "observe_workbench", observations)
    monkeypatch.setattr(daemon, "residual_process_payload", lambda **kwargs: next(residual_payloads))
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(daemon, "_process_source_signature", lambda: "sig-current")
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))
    monkeypatch.setattr(
        runtime_daemon,
        "_cleanup_residual_workbench_processes",
        lambda: {
            "supported": True,
            "requested": [11956, 53180],
            "terminated": [11956, 53180],
            "remaining": [],
        },
    )

    state = runtime_daemon._reconcile_observation(
        {
            "runtimeState": "running",
            "command": {"activeCommandId": ""},
            "workbench": {"desiredState": "closed", "observedState": "closed", "phase": "steady"},
        }
    )

    assert state["workbench"]["desiredState"] == "closed"
    assert state["residualProcesses"] == {"count": 0, "items": []}
    assert [event_type for event_type, _payload in events] == [
        "workbench.consistency.closed_residual_cleanup_requested",
        "workbench.consistency.closed_residual_cleanup_succeeded",
    ]
    assert events[0][1]["residualProcesses"]["count"] == 2
    assert events[1][1]["cleanup"]["terminated"] == [11956, 53180]


def test_reconcile_observation_clears_completed_active_command(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    events: list[tuple[str, dict]] = []

    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        lambda: {
            "observedState": "open",
            "backendPid": 6288,
            "browserLaunchPid": 49564,
            "browserWindowPid": 49564,
            "backendAlive": True,
            "backendHealthy": True,
            "backendObserved": True,
            "backendPort": 8000,
            "backendPortListening": True,
            "backendPortOwnerPid": 6288,
            "backendPortOwnerKind": "managed_workbench_backend",
            "backendPortOwnerTrusted": True,
            "backendPortOwnerResidual": False,
            "backendPortConflict": False,
            "browserWindowAlive": True,
            "browserManaged": True,
            "backendMissing": False,
            "frontendOrphaned": False,
            "lifecycleConsistency": "consistent",
            "sessionId": "managed-session",
            "url": "http://127.0.0.1:8000",
        },
    )
    monkeypatch.setattr(daemon, "residual_process_payload", lambda **kwargs: {"count": 0, "items": []})
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(daemon, "_process_source_signature", lambda: "sig-current")
    monkeypatch.setattr(daemon, "_command_result_is_completed", lambda command_id: command_id == "cmd-open")
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))

    state = runtime_daemon._reconcile_observation(
        {
            "runtimeState": "running",
            "command": {
                "activeCommandId": "cmd-open",
                "activeType": "open_workbench",
                "requestedBy": "codex",
                "startedAt": "2026-05-26T07:13:22+00:00",
            },
            "workbench": {"desiredState": "open", "observedState": "open", "phase": "steady"},
        }
    )

    assert state["command"]["activeCommandId"] == ""
    assert state["command"]["activeType"] == ""
    assert events == [
        (
            "command.active_completed_cleared",
            {"commandId": "cmd-open", "activeType": "open_workbench", "requestedBy": "codex"},
        )
    ]


def test_submit_command_defers_open_while_runtime_manager_is_stopping(tmp_path, monkeypatch):
    inbox_dir = tmp_path / "inbox"
    processing_dir = tmp_path / "processing"
    results_dir = tmp_path / "results"
    events_path = tmp_path / "events.jsonl"
    for path in (inbox_dir, processing_dir, results_dir):
        path.mkdir(parents=True)

    monkeypatch.setattr(command_queue, "INBOX_DIR", inbox_dir)
    monkeypatch.setattr(command_queue, "PROCESSING_DIR", processing_dir)
    monkeypatch.setattr(command_queue, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(command_queue, "EVENTS_PATH", events_path)
    monkeypatch.setattr(command_queue, "record_runtime_manager_scene_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(command_queue, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(
        command_queue,
        "create_restart_intent",
        lambda *args, **kwargs: {
            "intentId": "intent-reopen",
            "target": args[0],
            "reason": kwargs.get("reason", ""),
            "payload": kwargs.get("payload", {}),
        },
    )
    monkeypatch.setattr(command_queue, "load_pid", lambda: 9912)
    monkeypatch.setattr(command_queue, "_process_is_alive", lambda pid: True)
    monkeypatch.setattr(
        command_queue,
        "load_state",
        lambda: {
            "stateVersion": 42,
            "runtimeState": "stopping",
            "managerPid": 9912,
            "command": {
                "activeCommandId": "",
                "activeType": "",
                "stopManager": False,
            },
        },
    )

    command = command_queue.submit_command("open_workbench", args={"reason": "launcher_start"}, requested_by="launcher_ps")
    result_path = results_dir / f"{command['commandId']}.json"

    assert list(inbox_dir.glob("*.json")) == []
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["ok"] is True
    assert result["deferredUntilShutdownComplete"] is True
    assert result["restartIntentId"] == "intent-reopen"
    assert result["runtimeManagerStopping"] is True
    assert result["stateVersion"] == 42
    event = json.loads(events_path.read_text(encoding="utf-8").splitlines()[-1])
    assert event["type"] == "command_queue.open_deferred_until_shutdown_complete"
    assert event["payload"]["managerPid"] == 9912


def test_submit_command_ignores_stale_shutdown_state_from_previous_runtime_manager(tmp_path, monkeypatch):
    inbox_dir = tmp_path / "inbox"
    processing_dir = tmp_path / "processing"
    results_dir = tmp_path / "results"
    events_path = tmp_path / "events.jsonl"
    for path in (inbox_dir, processing_dir, results_dir):
        path.mkdir(parents=True)

    monkeypatch.setattr(command_queue, "INBOX_DIR", inbox_dir)
    monkeypatch.setattr(command_queue, "PROCESSING_DIR", processing_dir)
    monkeypatch.setattr(command_queue, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(command_queue, "EVENTS_PATH", events_path)
    monkeypatch.setattr(command_queue, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(command_queue, "load_pid", lambda: 9912)
    monkeypatch.setattr(command_queue, "_process_is_alive", lambda pid: True)
    monkeypatch.setattr(
        command_queue,
        "load_state",
        lambda: {
            "stateVersion": 99,
            "runtimeState": "stopping",
            "managerPid": 7711,
            "command": {
                "activeCommandId": "cmd-old-close",
                "activeType": "close_workbench",
                "stopManager": True,
            },
        },
    )

    command = command_queue.submit_command("open_workbench", args={"reason": "launcher_start"}, requested_by="launcher_ps")

    queued = list(inbox_dir.glob("*.json"))
    assert len(queued) == 1
    assert queued[0].name == f"{command['commandId']}.json"
    assert list(results_dir.glob("*.json")) == []
    queued_payload = json.loads(queued[0].read_text(encoding="utf-8"))
    assert queued_payload["type"] == "open_workbench"
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    event = next(item for item in events if item["type"] == "command_queue.stale_shutdown_state_ignored")
    assert event["type"] == "command_queue.stale_shutdown_state_ignored"
    assert event["payload"]["stateManagerPid"] == 7711
    assert event["payload"]["currentManagerPid"] == 9912


def test_command_queue_records_queued_claimed_and_result_written_events(tmp_path, monkeypatch):
    inbox_dir = tmp_path / "inbox"
    processing_dir = tmp_path / "processing"
    results_dir = tmp_path / "results"
    events_path = tmp_path / "events.jsonl"
    for path in (inbox_dir, processing_dir, results_dir):
        path.mkdir(parents=True)
    scene_events: list[tuple[str, dict, dict]] = []

    monkeypatch.setattr(command_queue, "INBOX_DIR", inbox_dir)
    monkeypatch.setattr(command_queue, "PROCESSING_DIR", processing_dir)
    monkeypatch.setattr(command_queue, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(command_queue, "EVENTS_PATH", events_path)
    monkeypatch.setattr(command_queue, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(command_queue, "load_pid", lambda: 0)
    monkeypatch.setattr(command_queue, "_process_is_alive", lambda pid: False)
    monkeypatch.setattr(
        command_queue,
        "record_runtime_manager_scene_event",
        lambda event_type, payload, **kwargs: scene_events.append((event_type, payload, kwargs)) or True,
    )

    command = command_queue.submit_command(
        "open_workbench",
        args={"reason": "launcher_start", "token": "secret-value", "noBrowser": True},
        requested_by="launcher_ps",
    )
    claimed = command_queue.claim_next_command()
    assert claimed is not None
    processing_path, claimed_payload = claimed
    command_queue.complete_command(
        processing_path,
        {
            "commandId": claimed_payload["commandId"],
            "ok": True,
            "completed": True,
            "message": "Workbench opened.",
        },
    )

    file_events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    assert [event["type"] for event in file_events] == [
        "command_queue.command_queued",
        "command_queue.command_claimed",
        "command_queue.command_result_written",
    ]
    queued_payload = file_events[0]["payload"]
    assert queued_payload["commandId"] == command["commandId"]
    assert queued_payload["args"] == {"argKeys": ["token"], "noBrowser": True, "reason": "launcher_start"}
    assert file_events[1]["payload"]["queuePath"] == f"{command['commandId']}.json"
    assert file_events[2]["payload"]["ok"] is True
    assert [event_type for event_type, _, _ in scene_events] == [event["type"] for event in file_events]
    assert {kwargs["phase"] for _, _, kwargs in scene_events} == {"queue"}
    assert all(kwargs["occurred_at"] for _, _, kwargs in scene_events)


def test_submit_close_interrupts_active_open_command(tmp_path, monkeypatch):
    inbox_dir = tmp_path / "inbox"
    processing_dir = tmp_path / "processing"
    results_dir = tmp_path / "results"
    interrupts_dir = tmp_path / "interrupts"
    events_path = tmp_path / "events.jsonl"
    for path in (inbox_dir, processing_dir, results_dir, interrupts_dir):
        path.mkdir(parents=True)

    monkeypatch.setattr(command_queue, "INBOX_DIR", inbox_dir)
    monkeypatch.setattr(command_queue, "PROCESSING_DIR", processing_dir)
    monkeypatch.setattr(command_queue, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(command_queue, "INTERRUPTS_DIR", interrupts_dir)
    monkeypatch.setattr(command_queue, "EVENTS_PATH", events_path)
    monkeypatch.setattr(command_queue, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(command_queue, "load_pid", lambda: 4242)
    monkeypatch.setattr(command_queue, "_process_is_alive", lambda pid: int(pid or 0) == 4242)
    monkeypatch.setattr(
        command_queue,
        "load_state",
        lambda: {
            "stateVersion": 17,
            "managerPid": 4242,
            "command": {
                "activeCommandId": "cmd-active-open",
                "activeType": "open_workbench",
            },
        },
    )
    monkeypatch.setattr(command_queue, "record_runtime_manager_scene_event", lambda *args, **kwargs: None)

    close_command = command_queue.submit_command(
        "force_close_workbench",
        args={"reason": "launcher_force_stop_button"},
        requested_by="launcher_api",
    )

    interrupt = json.loads((interrupts_dir / "cmd-active-open.json").read_text(encoding="utf-8"))
    assert interrupt["interruptedCommandId"] == "cmd-active-open"
    assert interrupt["interruptedType"] == "open_workbench"
    assert interrupt["closeCommandId"] == close_command["commandId"]
    assert interrupt["closeCommandType"] == "force_close_workbench"
    assert interrupt["operation"] == "force_close"
    queued = json.loads((inbox_dir / f"{close_command['commandId']}.json").read_text(encoding="utf-8"))
    assert queued["type"] == "force_close_workbench"
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    assert "command_queue.active_lifecycle_interrupt_requested" in [event["type"] for event in events]
    queued_event = next(event for event in events if event["type"] == "command_queue.command_queued")
    assert queued_event["payload"]["activeCommandInterrupt"]["interruptedCommandId"] == "cmd-active-open"


def test_claim_next_command_skips_restart_deferred_until_future(tmp_path, monkeypatch):
    inbox_dir = tmp_path / "inbox"
    processing_dir = tmp_path / "processing"
    results_dir = tmp_path / "results"
    events_path = tmp_path / "events.jsonl"
    for path in (inbox_dir, processing_dir, results_dir):
        path.mkdir(parents=True)
    (inbox_dir / "cmd-deferred.json").write_text(
        json.dumps(
            {
                "commandId": "cmd-deferred",
                "type": "restart_workbench",
                "requestedBy": "web_ui",
                "args": {
                    "reason": "web_restart_button",
                    "deferredUntilActiveWorkClear": True,
                    "deferUntil": "2999-01-01T00:00:00+00:00",
                },
            }
        ),
        encoding="utf-8",
    )
    ready_command = {
        "commandId": "cmd-ready",
        "type": "open_workbench",
        "requestedBy": "launcher_ps",
        "args": {"reason": "launcher_start"},
    }
    (inbox_dir / "cmd-ready.json").write_text(json.dumps(ready_command), encoding="utf-8")

    monkeypatch.setattr(command_queue, "INBOX_DIR", inbox_dir)
    monkeypatch.setattr(command_queue, "PROCESSING_DIR", processing_dir)
    monkeypatch.setattr(command_queue, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(command_queue, "EVENTS_PATH", events_path)
    monkeypatch.setattr(command_queue, "ensure_runtime_manager_dirs", lambda: None)

    claimed = command_queue.claim_next_command()

    assert claimed is not None
    processing_path, payload = claimed
    assert payload["commandId"] == "cmd-ready"
    assert processing_path.name == "cmd-ready.json"
    assert (inbox_dir / "cmd-deferred.json").exists()


def test_defer_processing_command_for_active_work_requeues_and_logs(tmp_path, monkeypatch):
    inbox_dir = tmp_path / "inbox"
    processing_dir = tmp_path / "processing"
    results_dir = tmp_path / "results"
    events_path = tmp_path / "events.jsonl"
    for path in (inbox_dir, processing_dir, results_dir):
        path.mkdir(parents=True)
    processing_path = processing_dir / "cmd-restart.json"
    command = {
        "commandId": "cmd-restart",
        "type": "restart_workbench",
        "requestedBy": "web_ui",
        "args": {"reason": "web_restart_button", "activeWorkDeferCount": 1},
    }
    processing_path.write_text(json.dumps(command), encoding="utf-8")

    monkeypatch.setattr(command_queue, "INBOX_DIR", inbox_dir)
    monkeypatch.setattr(command_queue, "PROCESSING_DIR", processing_dir)
    monkeypatch.setattr(command_queue, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(command_queue, "EVENTS_PATH", events_path)
    monkeypatch.setattr(command_queue, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(command_queue, "record_runtime_manager_scene_event", lambda *args, **kwargs: None)

    command_queue.defer_processing_command_for_active_work(
        processing_path,
        command,
        active_work_runs=[{"kind": "chat_turn", "runId": "turn-live"}],
        delay_seconds=1,
    )

    queued = json.loads((inbox_dir / "cmd-restart.json").read_text(encoding="utf-8"))
    assert not processing_path.exists()
    assert queued["args"]["activeWorkDeferCount"] == 2
    assert queued["args"]["lastActiveWorkCount"] == 1
    assert queued["args"]["lastActiveWorkRuns"][0]["runId"] == "turn-live"
    assert queued["args"]["deferUntil"]
    event = json.loads(events_path.read_text(encoding="utf-8").splitlines()[-1])
    assert event["type"] == "command_queue.command_deferred_active_work"
    assert event["payload"]["attemptCount"] == 2
    assert event["payload"]["activeWorkCount"] == 1


def test_recover_processing_queue_completes_stale_satisfied_stop_manager_close(tmp_path, monkeypatch):
    inbox_dir = tmp_path / "inbox"
    processing_dir = tmp_path / "processing"
    results_dir = tmp_path / "results"
    events_path = tmp_path / "events.jsonl"
    for path in (inbox_dir, processing_dir, results_dir):
        path.mkdir(parents=True)

    old_close = {
        "commandId": "cmd_20260525T125402Z_4e072b74",
        "type": "close_workbench",
        "requestedBy": "web_ui",
        "requestedAt": "2026-05-25T12:54:02.877170+00:00",
        "args": {"reason": "web_close_button", "stopManager": True},
    }
    new_open = {
        "commandId": "cmd_20260525T141736Z_38094da2",
        "type": "open_workbench",
        "requestedBy": "launcher_ps",
        "requestedAt": "2026-05-25T14:17:36.134373+00:00",
        "args": {"reason": "launcher_start"},
    }
    (processing_dir / f"{old_close['commandId']}.json").write_text(json.dumps(old_close), encoding="utf-8")
    (inbox_dir / f"{new_open['commandId']}.json").write_text(json.dumps(new_open), encoding="utf-8")

    monkeypatch.setattr(command_queue, "INBOX_DIR", inbox_dir)
    monkeypatch.setattr(command_queue, "PROCESSING_DIR", processing_dir)
    monkeypatch.setattr(command_queue, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(command_queue, "EVENTS_PATH", events_path)
    monkeypatch.setattr(command_queue, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(
        command_queue,
        "load_state",
        lambda: {
            "stateVersion": 5857,
            "runtimeState": "idle",
            "managerPid": 0,
            "daemonRunning": False,
            "workbench": {"desiredState": "closed", "observedState": "closed", "phase": "steady"},
        },
    )

    command_queue.recover_processing_queue()
    claimed = command_queue.claim_next_command()

    assert claimed is not None
    _, claimed_payload = claimed
    assert claimed_payload["commandId"] == new_open["commandId"]
    skipped_result = json.loads((results_dir / f"{old_close['commandId']}.json").read_text(encoding="utf-8"))
    assert skipped_result["ok"] is True
    assert skipped_result["completed"] is True
    assert skipped_result["staleRecoveredCommand"] is True
    assert skipped_result["stopDaemon"] is False
    assert not (processing_dir / f"{old_close['commandId']}.json").exists()
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    assert "command_queue.recovered_stale_close_completed" in [event["type"] for event in events]


def test_recover_processing_queue_preserves_completed_result_without_requeue(tmp_path, monkeypatch):
    inbox_dir = tmp_path / "inbox"
    processing_dir = tmp_path / "processing"
    results_dir = tmp_path / "results"
    events_path = tmp_path / "events.jsonl"
    for path in (inbox_dir, processing_dir, results_dir):
        path.mkdir(parents=True)

    command = {
        "commandId": "cmd-completed-restart",
        "type": "restart_workbench",
        "requestedBy": "web_ui",
        "requestedAt": "2026-06-11T05:20:00+00:00",
        "args": {"reason": "web_restart_button"},
    }
    (processing_dir / "cmd-completed-restart.json").write_text(json.dumps(command), encoding="utf-8")
    (results_dir / "cmd-completed-restart.json").write_text(
        json.dumps(
            {
                "commandId": "cmd-completed-restart",
                "accepted": True,
                "completed": True,
                "ok": True,
                "message": "Workbench restarted.",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(command_queue, "INBOX_DIR", inbox_dir)
    monkeypatch.setattr(command_queue, "PROCESSING_DIR", processing_dir)
    monkeypatch.setattr(command_queue, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(command_queue, "EVENTS_PATH", events_path)
    monkeypatch.setattr(command_queue, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(command_queue, "record_runtime_manager_scene_event", lambda *args, **kwargs: None)

    command_queue.recover_processing_queue()

    assert list(inbox_dir.glob("*.json")) == []
    assert not (processing_dir / "cmd-completed-restart.json").exists()
    assert (results_dir / "cmd-completed-restart.json").exists()
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    assert events[-1]["type"] == "command_queue.recovered_processing_result_preserved"
    assert events[-1]["payload"]["resultCompleted"] is True


def test_recover_processing_queue_does_not_discard_unfinished_result(tmp_path, monkeypatch):
    inbox_dir = tmp_path / "inbox"
    processing_dir = tmp_path / "processing"
    results_dir = tmp_path / "results"
    events_path = tmp_path / "events.jsonl"
    for path in (inbox_dir, processing_dir, results_dir):
        path.mkdir(parents=True)

    command = {
        "commandId": "cmd-unfinished-restart",
        "type": "restart_workbench",
        "requestedBy": "web_ui",
        "requestedAt": "2026-06-11T05:21:00+00:00",
        "args": {"reason": "web_restart_button"},
    }
    (processing_dir / "cmd-unfinished-restart.json").write_text(json.dumps(command), encoding="utf-8")
    (results_dir / "cmd-unfinished-restart.json").write_text(
        json.dumps(
            {
                "commandId": "cmd-unfinished-restart",
                "accepted": True,
                "completed": False,
                "ok": False,
                "message": "Deferred until active work clears.",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(command_queue, "INBOX_DIR", inbox_dir)
    monkeypatch.setattr(command_queue, "PROCESSING_DIR", processing_dir)
    monkeypatch.setattr(command_queue, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(command_queue, "EVENTS_PATH", events_path)
    monkeypatch.setattr(command_queue, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(command_queue, "record_runtime_manager_scene_event", lambda *args, **kwargs: None)

    command_queue.recover_processing_queue()

    queued = json.loads((inbox_dir / "cmd-unfinished-restart.json").read_text(encoding="utf-8"))
    assert queued["commandId"] == "cmd-unfinished-restart"
    assert not (processing_dir / "cmd-unfinished-restart.json").exists()
    assert (results_dir / "cmd-unfinished-restart.json").exists()
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    assert events[-1]["type"] == "command_queue.processing_recovered"


def test_submit_command_treats_duplicate_stop_manager_close_as_idempotent(tmp_path, monkeypatch):
    inbox_dir = tmp_path / "inbox"
    processing_dir = tmp_path / "processing"
    results_dir = tmp_path / "results"
    events_path = tmp_path / "events.jsonl"
    for path in (inbox_dir, processing_dir, results_dir):
        path.mkdir(parents=True)

    monkeypatch.setattr(command_queue, "INBOX_DIR", inbox_dir)
    monkeypatch.setattr(command_queue, "PROCESSING_DIR", processing_dir)
    monkeypatch.setattr(command_queue, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(command_queue, "EVENTS_PATH", events_path)
    monkeypatch.setattr(command_queue, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(command_queue, "load_pid", lambda: 9912)
    monkeypatch.setattr(command_queue, "_process_is_alive", lambda pid: True)
    monkeypatch.setattr(
        command_queue,
        "load_state",
        lambda: {
            "stateVersion": 43,
            "runtimeState": "running",
            "managerPid": 9912,
            "command": {
                "activeCommandId": "cmd-active-close",
                "activeType": "close_workbench",
                "stopManager": True,
            },
        },
    )

    command = command_queue.submit_command(
        "close_workbench",
        args={"reason": "launcher_stop", "stopManager": True},
        requested_by="launcher_ps",
    )
    result = json.loads((results_dir / f"{command['commandId']}.json").read_text(encoding="utf-8"))

    assert list(inbox_dir.glob("*.json")) == []
    assert result["ok"] is True
    assert result["runtimeManagerStopping"] is True
    assert result["message"] == "Runtime manager shutdown is already in progress."


def test_submit_command_joins_active_close_workbench_without_stop_manager(tmp_path, monkeypatch):
    inbox_dir = tmp_path / "inbox"
    processing_dir = tmp_path / "processing"
    results_dir = tmp_path / "results"
    events_path = tmp_path / "events.jsonl"
    for path in (inbox_dir, processing_dir, results_dir):
        path.mkdir(parents=True)

    monkeypatch.setattr(command_queue, "INBOX_DIR", inbox_dir)
    monkeypatch.setattr(command_queue, "PROCESSING_DIR", processing_dir)
    monkeypatch.setattr(command_queue, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(command_queue, "EVENTS_PATH", events_path)
    monkeypatch.setattr(command_queue, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(command_queue, "load_pid", lambda: 9912)
    monkeypatch.setattr(command_queue, "_process_is_alive", lambda pid: True)
    monkeypatch.setattr(
        command_queue,
        "load_state",
        lambda: {
            "stateVersion": 44,
            "runtimeState": "running",
            "managerPid": 9912,
            "command": {
                "activeCommandId": "cmd-active-close",
                "activeType": "close_workbench",
                "stopManager": False,
            },
        },
    )

    command = command_queue.submit_command(
        "close_workbench",
        args={"reason": "launcher_stop_button", "stopManager": False},
        requested_by="launcher_api",
    )

    assert command["commandId"] == "cmd-active-close"
    assert list(inbox_dir.glob("*.json")) == []
    assert list(results_dir.glob("*.json")) == []
    event = json.loads(events_path.read_text(encoding="utf-8").splitlines()[-1])
    assert event["type"] == "command_queue.close_joined"
    assert event["payload"]["commandId"] == "cmd-active-close"


def test_submit_command_joins_pending_close_workbench_without_stop_manager(tmp_path, monkeypatch):
    inbox_dir = tmp_path / "inbox"
    processing_dir = tmp_path / "processing"
    results_dir = tmp_path / "results"
    events_path = tmp_path / "events.jsonl"
    for path in (inbox_dir, processing_dir, results_dir):
        path.mkdir(parents=True)
    (inbox_dir / "cmd-pending-close.json").write_text(
        json.dumps(
            {
                "commandId": "cmd-pending-close",
                "type": "close_workbench",
                "requestedBy": "launcher_api",
                "args": {"reason": "launcher_stop_button", "stopManager": False},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(command_queue, "INBOX_DIR", inbox_dir)
    monkeypatch.setattr(command_queue, "PROCESSING_DIR", processing_dir)
    monkeypatch.setattr(command_queue, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(command_queue, "EVENTS_PATH", events_path)
    monkeypatch.setattr(command_queue, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(command_queue, "load_pid", lambda: 9912)
    monkeypatch.setattr(command_queue, "_process_is_alive", lambda pid: True)
    monkeypatch.setattr(
        command_queue,
        "load_state",
        lambda: {
            "stateVersion": 45,
            "runtimeState": "running",
            "managerPid": 9912,
            "command": {},
        },
    )

    command = command_queue.submit_command(
        "close_workbench",
        args={"reason": "launcher_stop_button", "stopManager": False},
        requested_by="launcher_api",
    )

    assert command["commandId"] == "cmd-pending-close"
    assert len(list(inbox_dir.glob("*.json"))) == 1
    assert list(results_dir.glob("*.json")) == []
    event = json.loads(events_path.read_text(encoding="utf-8").splitlines()[-1])
    assert event["type"] == "command_queue.close_joined"
    assert event["payload"]["commandId"] == "cmd-pending-close"


def test_submit_force_close_joins_active_close_workbench(tmp_path, monkeypatch):
    inbox_dir = tmp_path / "inbox"
    processing_dir = tmp_path / "processing"
    results_dir = tmp_path / "results"
    events_path = tmp_path / "events.jsonl"
    for path in (inbox_dir, processing_dir, results_dir):
        path.mkdir(parents=True)

    monkeypatch.setattr(command_queue, "INBOX_DIR", inbox_dir)
    monkeypatch.setattr(command_queue, "PROCESSING_DIR", processing_dir)
    monkeypatch.setattr(command_queue, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(command_queue, "EVENTS_PATH", events_path)
    monkeypatch.setattr(command_queue, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(command_queue, "load_pid", lambda: 9912)
    monkeypatch.setattr(command_queue, "_process_is_alive", lambda pid: True)
    monkeypatch.setattr(
        command_queue,
        "load_state",
        lambda: {
            "stateVersion": 46,
            "runtimeState": "running",
            "managerPid": 9912,
            "command": {
                "activeCommandId": "cmd-active-close",
                "activeType": "close_workbench",
                "stopManager": False,
            },
        },
    )

    command = command_queue.submit_command(
        "force_close_workbench",
        args={"reason": "launcher_force_stop_button", "stopManager": False},
        requested_by="launcher_api",
    )

    assert command["commandId"] == "cmd-active-close"
    assert list(inbox_dir.glob("*.json")) == []
    assert list(results_dir.glob("*.json")) == []
    event = json.loads(events_path.read_text(encoding="utf-8").splitlines()[-1])
    assert event["type"] == "command_queue.force_close_joined"
    assert event["payload"]["commandId"] == "cmd-active-close"


def test_submit_force_close_joins_pending_force_close_workbench(tmp_path, monkeypatch):
    inbox_dir = tmp_path / "inbox"
    processing_dir = tmp_path / "processing"
    results_dir = tmp_path / "results"
    events_path = tmp_path / "events.jsonl"
    for path in (inbox_dir, processing_dir, results_dir):
        path.mkdir(parents=True)
    (inbox_dir / "cmd-pending-force-close.json").write_text(
        json.dumps(
            {
                "commandId": "cmd-pending-force-close",
                "type": "force_close_workbench",
                "requestedBy": "launcher_api",
                "args": {"reason": "launcher_force_stop_button", "stopManager": False},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(command_queue, "INBOX_DIR", inbox_dir)
    monkeypatch.setattr(command_queue, "PROCESSING_DIR", processing_dir)
    monkeypatch.setattr(command_queue, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(command_queue, "EVENTS_PATH", events_path)
    monkeypatch.setattr(command_queue, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(command_queue, "load_pid", lambda: 9912)
    monkeypatch.setattr(command_queue, "_process_is_alive", lambda pid: True)
    monkeypatch.setattr(
        command_queue,
        "load_state",
        lambda: {
            "stateVersion": 47,
            "runtimeState": "running",
            "managerPid": 9912,
            "command": {},
        },
    )

    command = command_queue.submit_command(
        "force_close_workbench",
        args={"reason": "launcher_force_stop_button", "stopManager": False},
        requested_by="launcher_api",
    )

    assert command["commandId"] == "cmd-pending-force-close"
    assert [path.name for path in inbox_dir.glob("*.json")] == ["cmd-pending-force-close.json"]
    assert list(results_dir.glob("*.json")) == []
    event = json.loads(events_path.read_text(encoding="utf-8").splitlines()[-1])
    assert event["type"] == "command_queue.force_close_joined"
    assert event["payload"]["commandId"] == "cmd-pending-force-close"


def test_submit_command_joins_active_open_workbench(tmp_path, monkeypatch):
    inbox_dir = tmp_path / "inbox"
    processing_dir = tmp_path / "processing"
    results_dir = tmp_path / "results"
    events_path = tmp_path / "events.jsonl"
    for path in (inbox_dir, processing_dir, results_dir):
        path.mkdir(parents=True)

    monkeypatch.setattr(command_queue, "INBOX_DIR", inbox_dir)
    monkeypatch.setattr(command_queue, "PROCESSING_DIR", processing_dir)
    monkeypatch.setattr(command_queue, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(command_queue, "EVENTS_PATH", events_path)
    monkeypatch.setattr(command_queue, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(command_queue, "load_pid", lambda: 9912)
    monkeypatch.setattr(command_queue, "_process_is_alive", lambda pid: True)
    monkeypatch.setattr(
        command_queue,
        "load_state",
        lambda: {
            "stateVersion": 51,
            "runtimeState": "running",
            "managerPid": 9912,
            "command": {
                "activeCommandId": "cmd-active-open",
                "activeType": "open_workbench",
                "noBrowser": False,
            },
        },
    )

    command = command_queue.submit_command("open_workbench", args={"reason": "launcher_start"}, requested_by="launcher_ps")

    assert command["commandId"] == "cmd-active-open"
    assert list(inbox_dir.glob("*.json")) == []
    assert list(results_dir.glob("*.json")) == []
    event = json.loads(events_path.read_text(encoding="utf-8").splitlines()[-1])
    assert event["type"] == "command_queue.open_joined"
    assert event["payload"]["commandId"] == "cmd-active-open"


def test_submit_command_joins_pending_open_workbench(tmp_path, monkeypatch):
    inbox_dir = tmp_path / "inbox"
    processing_dir = tmp_path / "processing"
    results_dir = tmp_path / "results"
    events_path = tmp_path / "events.jsonl"
    for path in (inbox_dir, processing_dir, results_dir):
        path.mkdir(parents=True)
    (inbox_dir / "cmd-pending-open.json").write_text(
        json.dumps(
            {
                "commandId": "cmd-pending-open",
                "type": "open_workbench",
                "requestedBy": "launcher_ps",
                "args": {"reason": "launcher_start"},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(command_queue, "INBOX_DIR", inbox_dir)
    monkeypatch.setattr(command_queue, "PROCESSING_DIR", processing_dir)
    monkeypatch.setattr(command_queue, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(command_queue, "EVENTS_PATH", events_path)
    monkeypatch.setattr(command_queue, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(command_queue, "load_pid", lambda: 9912)
    monkeypatch.setattr(command_queue, "_process_is_alive", lambda pid: True)
    monkeypatch.setattr(
        command_queue,
        "load_state",
        lambda: {
            "stateVersion": 52,
            "runtimeState": "running",
            "managerPid": 9912,
            "command": {"activeCommandId": "", "activeType": ""},
        },
    )

    command = command_queue.submit_command("open_workbench", args={"reason": "launcher_start"}, requested_by="launcher_ps")

    assert command["commandId"] == "cmd-pending-open"
    assert [path.name for path in inbox_dir.glob("*.json")] == ["cmd-pending-open.json"]
    assert list(results_dir.glob("*.json")) == []


def test_submit_command_does_not_join_headless_open_when_browser_is_requested(tmp_path, monkeypatch):
    inbox_dir = tmp_path / "inbox"
    processing_dir = tmp_path / "processing"
    results_dir = tmp_path / "results"
    events_path = tmp_path / "events.jsonl"
    for path in (inbox_dir, processing_dir, results_dir):
        path.mkdir(parents=True)
    (inbox_dir / "cmd-headless-open.json").write_text(
        json.dumps(
            {
                "commandId": "cmd-headless-open",
                "type": "open_workbench",
                "requestedBy": "launcher_ps",
                "args": {"reason": "launcher_start", "noBrowser": True},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(command_queue, "INBOX_DIR", inbox_dir)
    monkeypatch.setattr(command_queue, "PROCESSING_DIR", processing_dir)
    monkeypatch.setattr(command_queue, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(command_queue, "EVENTS_PATH", events_path)
    monkeypatch.setattr(command_queue, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(command_queue, "load_pid", lambda: 9912)
    monkeypatch.setattr(command_queue, "_process_is_alive", lambda pid: True)
    monkeypatch.setattr(
        command_queue,
        "load_state",
        lambda: {
            "stateVersion": 53,
            "runtimeState": "running",
            "managerPid": 9912,
            "command": {"activeCommandId": "", "activeType": ""},
        },
    )

    command = command_queue.submit_command("open_workbench", args={"reason": "launcher_start"}, requested_by="launcher_ps")

    queued = sorted(path.name for path in inbox_dir.glob("*.json"))
    assert command["commandId"] != "cmd-headless-open"
    assert queued == ["cmd-headless-open.json", f"{command['commandId']}.json"]


def test_submit_command_joins_active_restart_workbench(tmp_path, monkeypatch):
    inbox_dir = tmp_path / "inbox"
    processing_dir = tmp_path / "processing"
    results_dir = tmp_path / "results"
    events_path = tmp_path / "events.jsonl"
    for path in (inbox_dir, processing_dir, results_dir):
        path.mkdir(parents=True)

    monkeypatch.setattr(command_queue, "INBOX_DIR", inbox_dir)
    monkeypatch.setattr(command_queue, "PROCESSING_DIR", processing_dir)
    monkeypatch.setattr(command_queue, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(command_queue, "EVENTS_PATH", events_path)
    monkeypatch.setattr(command_queue, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(command_queue, "load_pid", lambda: 9912)
    monkeypatch.setattr(command_queue, "_process_is_alive", lambda pid: True)
    monkeypatch.setattr(
        command_queue,
        "load_state",
        lambda: {
            "stateVersion": 54,
            "runtimeState": "running",
            "managerPid": 9912,
            "command": {
                "activeCommandId": "cmd-active-restart",
                "activeType": "restart_workbench",
                "noBrowser": False,
            },
        },
    )

    command = command_queue.submit_command("restart_workbench", args={"reason": "launcher_restart"}, requested_by="launcher_ps")

    assert command["commandId"] == "cmd-active-restart"
    assert list(inbox_dir.glob("*.json")) == []
    assert list(results_dir.glob("*.json")) == []
    event = json.loads(events_path.read_text(encoding="utf-8").splitlines()[-1])
    assert event["type"] == "command_queue.restart_joined"
    assert event["payload"]["commandId"] == "cmd-active-restart"


def test_submit_command_joins_pending_restart_workbench(tmp_path, monkeypatch):
    inbox_dir = tmp_path / "inbox"
    processing_dir = tmp_path / "processing"
    results_dir = tmp_path / "results"
    events_path = tmp_path / "events.jsonl"
    for path in (inbox_dir, processing_dir, results_dir):
        path.mkdir(parents=True)
    (inbox_dir / "cmd-pending-restart.json").write_text(
        json.dumps(
            {
                "commandId": "cmd-pending-restart",
                "type": "restart_workbench",
                "requestedBy": "launcher_ps",
                "args": {"reason": "launcher_restart"},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(command_queue, "INBOX_DIR", inbox_dir)
    monkeypatch.setattr(command_queue, "PROCESSING_DIR", processing_dir)
    monkeypatch.setattr(command_queue, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(command_queue, "EVENTS_PATH", events_path)
    monkeypatch.setattr(command_queue, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(command_queue, "load_pid", lambda: 9912)
    monkeypatch.setattr(command_queue, "_process_is_alive", lambda pid: True)
    monkeypatch.setattr(
        command_queue,
        "load_state",
        lambda: {
            "stateVersion": 55,
            "runtimeState": "running",
            "managerPid": 9912,
            "command": {"activeCommandId": "", "activeType": ""},
        },
    )

    command = command_queue.submit_command("restart_workbench", args={"reason": "launcher_restart"}, requested_by="launcher_ps")

    assert command["commandId"] == "cmd-pending-restart"
    assert [path.name for path in inbox_dir.glob("*.json")] == ["cmd-pending-restart.json"]
    assert list(results_dir.glob("*.json")) == []
    event = json.loads(events_path.read_text(encoding="utf-8").splitlines()[-1])
    assert event["type"] == "command_queue.restart_joined"


def test_close_workbench_supersedes_pending_open_workbench(tmp_path, monkeypatch):
    inbox_dir = tmp_path / "inbox"
    processing_dir = tmp_path / "processing"
    results_dir = tmp_path / "results"
    events_path = tmp_path / "events.jsonl"
    for path in (inbox_dir, processing_dir, results_dir):
        path.mkdir(parents=True)
    (inbox_dir / "cmd-pending-open.json").write_text(
        json.dumps(
            {
                "commandId": "cmd-pending-open",
                "type": "open_workbench",
                "requestedBy": "launcher_ps",
                "args": {"reason": "launcher_start"},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(command_queue, "INBOX_DIR", inbox_dir)
    monkeypatch.setattr(command_queue, "PROCESSING_DIR", processing_dir)
    monkeypatch.setattr(command_queue, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(command_queue, "EVENTS_PATH", events_path)
    monkeypatch.setattr(command_queue, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(command_queue, "load_pid", lambda: 0)
    monkeypatch.setattr(command_queue, "_process_is_alive", lambda pid: False)
    monkeypatch.setattr(command_queue, "load_state", lambda: {"stateVersion": 61})

    close_command = command_queue.submit_command(
        "close_workbench",
        args={"reason": "web_close_button", "stopManager": True},
        requested_by="web_ui",
    )

    assert sorted(path.name for path in inbox_dir.glob("*.json")) == [f"{close_command['commandId']}.json"]
    superseded_result = json.loads((results_dir / "cmd-pending-open.json").read_text(encoding="utf-8"))
    assert superseded_result["ok"] is False
    assert superseded_result["completed"] is True
    assert superseded_result["errorType"] == "SupersededByCloseWorkbench"
    assert superseded_result["supersededByCommandId"] == close_command["commandId"]
    assert superseded_result["stateVersion"] == 61
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    supersede_event = next(event for event in events if event["type"] == "command_queue.pending_open_superseded_by_close")
    queued_event = next(event for event in events if event["type"] == "command_queue.command_queued")
    assert supersede_event["payload"]["commandId"] == close_command["commandId"]
    assert supersede_event["payload"]["commands"] == [
        {"commandId": "cmd-pending-open", "type": "open_workbench", "status": "superseded"}
    ]
    assert queued_event["payload"]["supersededPendingCommands"] == supersede_event["payload"]["commands"]


def test_close_workbench_supersedes_pending_restart_workbench(tmp_path, monkeypatch):
    inbox_dir = tmp_path / "inbox"
    processing_dir = tmp_path / "processing"
    results_dir = tmp_path / "results"
    events_path = tmp_path / "events.jsonl"
    for path in (inbox_dir, processing_dir, results_dir):
        path.mkdir(parents=True)
    (inbox_dir / "cmd-pending-restart.json").write_text(
        json.dumps(
            {
                "commandId": "cmd-pending-restart",
                "type": "restart_workbench",
                "requestedBy": "web_ui",
                "args": {"reason": "launcher_restart"},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(command_queue, "INBOX_DIR", inbox_dir)
    monkeypatch.setattr(command_queue, "PROCESSING_DIR", processing_dir)
    monkeypatch.setattr(command_queue, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(command_queue, "EVENTS_PATH", events_path)
    monkeypatch.setattr(command_queue, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(command_queue, "load_pid", lambda: 0)
    monkeypatch.setattr(command_queue, "_process_is_alive", lambda pid: False)
    monkeypatch.setattr(command_queue, "load_state", lambda: {"stateVersion": 62})

    close_command = command_queue.submit_command(
        "close_workbench",
        args={"reason": "web_close_button", "stopManager": True},
        requested_by="web_ui",
    )

    assert sorted(path.name for path in inbox_dir.glob("*.json")) == [f"{close_command['commandId']}.json"]
    superseded_result = json.loads((results_dir / "cmd-pending-restart.json").read_text(encoding="utf-8"))
    assert superseded_result["ok"] is False
    assert superseded_result["completed"] is True
    assert superseded_result["errorType"] == "SupersededByCloseWorkbench"
    assert superseded_result["supersededByCommandId"] == close_command["commandId"]
    assert superseded_result["stateVersion"] == 62
    event_types = [json.loads(line)["type"] for line in events_path.read_text(encoding="utf-8").splitlines()]
    assert "command_queue.pending_open_superseded_by_close" in event_types


def test_force_close_workbench_supersedes_pending_lifecycle_commands(tmp_path, monkeypatch):
    inbox_dir = tmp_path / "inbox"
    processing_dir = tmp_path / "processing"
    results_dir = tmp_path / "results"
    events_path = tmp_path / "events.jsonl"
    for path in (inbox_dir, processing_dir, results_dir):
        path.mkdir(parents=True)
    for command_id, command_type in (
        ("cmd-pending-open", "open_workbench"),
        ("cmd-pending-restart", "restart_workbench"),
        ("cmd-pending-close", "close_workbench"),
    ):
        (inbox_dir / f"{command_id}.json").write_text(
            json.dumps(
                {
                    "commandId": command_id,
                    "type": command_type,
                    "requestedBy": "web_ui",
                    "args": {"reason": command_type},
                }
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr(command_queue, "INBOX_DIR", inbox_dir)
    monkeypatch.setattr(command_queue, "PROCESSING_DIR", processing_dir)
    monkeypatch.setattr(command_queue, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(command_queue, "EVENTS_PATH", events_path)
    monkeypatch.setattr(command_queue, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(command_queue, "load_pid", lambda: 0)
    monkeypatch.setattr(command_queue, "_process_is_alive", lambda pid: False)
    monkeypatch.setattr(command_queue, "load_state", lambda: {"stateVersion": 63})

    force_command = command_queue.submit_command(
        "force_close_workbench",
        args={"reason": "launcher_force_stop_button", "stopManager": False},
        requested_by="launcher_api",
    )

    assert sorted(path.name for path in inbox_dir.glob("*.json")) == [f"{force_command['commandId']}.json"]
    for command_id in ("cmd-pending-open", "cmd-pending-restart", "cmd-pending-close"):
        superseded_result = json.loads((results_dir / f"{command_id}.json").read_text(encoding="utf-8"))
        assert superseded_result["ok"] is False
        assert superseded_result["completed"] is True
        assert superseded_result["errorType"] == "SupersededByForceCloseWorkbench"
        assert superseded_result["supersededByCommandId"] == force_command["commandId"]
        assert superseded_result["stateVersion"] == 63
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    supersede_event = next(event for event in events if event["type"] == "command_queue.pending_lifecycle_superseded_by_force_close")
    queued_event = next(event for event in events if event["type"] == "command_queue.command_queued")
    assert supersede_event["payload"]["commandId"] == force_command["commandId"]
    assert {item["type"] for item in supersede_event["payload"]["commands"]} == {
        "open_workbench",
        "restart_workbench",
        "close_workbench",
    }
    assert queued_event["payload"]["supersededPendingCommands"] == supersede_event["payload"]["commands"]


def test_reject_pending_commands_for_shutdown_removes_stale_open_from_inbox(tmp_path, monkeypatch):
    inbox_dir = tmp_path / "inbox"
    processing_dir = tmp_path / "processing"
    results_dir = tmp_path / "results"
    for path in (inbox_dir, processing_dir, results_dir):
        path.mkdir(parents=True)
    command_path = inbox_dir / "cmd-open.json"
    command_path.write_text(
        json.dumps(
            {
                "commandId": "cmd-open",
                "type": "open_workbench",
                "requestedBy": "launcher_ps",
                "args": {"reason": "launcher_start"},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(command_queue, "INBOX_DIR", inbox_dir)
    monkeypatch.setattr(command_queue, "RESULTS_DIR", results_dir)
    monkeypatch.setattr(command_queue, "ensure_runtime_manager_dirs", lambda: None)

    cleanup = command_queue.reject_pending_commands_for_shutdown(shutdown_state={"stateVersion": 44})

    assert cleanup["count"] == 1
    assert cleanup["items"] == [{"commandId": "cmd-open", "type": "open_workbench", "status": "completed"}]
    assert list(inbox_dir.glob("*.json")) == []
    result = json.loads((results_dir / "cmd-open.json").read_text(encoding="utf-8"))
    assert result["ok"] is False
    assert result["errorType"] == "RuntimeManagerStoppingError"
    assert result["stateVersion"] == 44


def test_prepare_daemon_shutdown_records_rejected_pending_commands(monkeypatch):
    events: list[tuple[str, dict]] = []

    monkeypatch.setattr(daemon, "_close_active_evolution_runs_for_shutdown", lambda: [])
    monkeypatch.setattr(daemon, "terminate_process_descendants", lambda *args, **kwargs: {"terminated": []})
    monkeypatch.setattr(daemon, "load_state", lambda: {"stateVersion": 45})
    monkeypatch.setattr(
        daemon,
        "reject_pending_commands_for_shutdown",
        lambda shutdown_state=None: {
            "count": 2,
            "items": [
                {"commandId": "cmd-open", "type": "open_workbench", "status": "completed"},
                {"commandId": "cmd-bad", "type": "restart_workbench", "status": "failed", "error": "locked"},
            ],
        },
    )
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))

    cleanup = daemon._prepare_daemon_shutdown()

    assert cleanup["rejectedPendingCommands"]["count"] == 2
    assert events == [
        (
            "daemon.shutdown.rejected_pending_commands",
            {
                "count": 2,
                "commands": [
                    {"commandId": "cmd-open", "type": "open_workbench", "status": "completed"},
                    {"commandId": "cmd-bad", "type": "restart_workbench", "status": "failed"},
                ],
            },
        )
    ]


def test_handle_command_reports_exception_type(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    monkeypatch.setattr(daemon, "load_state", lambda: {"command": {}, "workbench": {}})
    monkeypatch.setattr(daemon, "save_state", lambda state: state)
    monkeypatch.setattr(daemon, "observe_workbench", lambda: {"observedState": "closed"})
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})

    def boom(*, command_id: str, args: dict):
        raise ValueError("bad payload")

    monkeypatch.setattr(runtime_daemon, "_handle_start_supervised_run", boom)

    result = runtime_daemon._handle_command(
        {
            "commandId": "cmd-err",
            "type": "start_supervised_run",
            "requestedBy": "test",
            "args": {},
        }
    )

    assert result["ok"] is False
    assert result["errorType"] == "ValueError"


def test_non_lifecycle_command_failure_does_not_mark_workbench_failed(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    saved_states: list[dict] = []
    state = {
        "command": {"activeCommandId": "cmd-err", "activeType": "stop_supervised_run"},
        "workbench": {
            "desiredState": "open",
            "observedState": "open",
            "phase": "steady",
            "failureMessage": "",
        },
    }
    monkeypatch.setattr(daemon, "load_state", lambda: json.loads(json.dumps(state)))
    monkeypatch.setattr(daemon, "save_state", lambda payload: saved_states.append(payload) or payload)
    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        lambda: {
            "observedState": "open",
            "backendPid": 3200,
            "browserLaunchPid": 0,
            "browserWindowPid": 4500,
            "browserManaged": True,
        },
    )
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})

    def boom(*, command_id: str, args: dict):
        raise daemon.supervised_control_service.SupervisedRunNotFoundError("missing supervised run")

    monkeypatch.setattr(runtime_daemon, "_handle_stop_supervised_run", boom)

    result = runtime_daemon._handle_command(
        {
            "commandId": "cmd-err",
            "type": "stop_supervised_run",
            "requestedBy": "test",
            "args": {"runId": "missing"},
        }
    )

    assert result["ok"] is False
    assert result["errorType"] == "SupervisedRunNotFoundError"
    assert saved_states[-1]["lastError"]["scope"] == "stop_supervised_run"
    assert saved_states[-1]["workbench"]["phase"] == "steady"
    assert saved_states[-1]["workbench"]["failureMessage"] == ""


@pytest.mark.slow
def test_is_process_alive_windows_with_real_process():
    import os
    import sys
    import time

    if os.name != "nt":
        return

    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(2)"])
    try:
        deadline = time.time() + 2.0
        while time.time() < deadline and not daemon._is_process_alive(proc.pid):
            time.sleep(0.05)
        assert daemon._is_process_alive(proc.pid) is True
    finally:
        proc.terminate()
        proc.wait(timeout=5)

    assert daemon._is_process_alive(proc.pid) is False


def test_daemon_append_event_mirrors_runtime_scene_event(tmp_path, monkeypatch):
    events_path = tmp_path / "events.jsonl"
    scene_events: list[tuple[str, dict, dict]] = []

    monkeypatch.setattr(daemon, "EVENTS_PATH", events_path)
    monkeypatch.setattr(daemon, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(
        daemon,
        "record_runtime_manager_scene_event",
        lambda event_type, payload, **kwargs: scene_events.append((event_type, payload, kwargs)) or True,
    )

    daemon._append_event(
        "workbench.open.verification_succeeded",
        {"commandId": "cmd-open", "ok": True, "backendPid": 1234},
    )

    file_event = json.loads(events_path.read_text(encoding="utf-8").splitlines()[-1])
    assert file_event["type"] == "workbench.open.verification_succeeded"
    assert file_event["payload"]["commandId"] == "cmd-open"
    assert scene_events == [
        (
            "workbench.open.verification_succeeded",
            {"commandId": "cmd-open", "ok": True, "backendPid": 1234},
            {"phase": "open", "occurred_at": file_event["at"]},
        )
    ]


def test_runtime_manager_scene_event_backfills_recent_queue_events(tmp_path, monkeypatch):
    events_path = tmp_path / "events.jsonl"
    scene_dir = tmp_path / "logs" / "runtime_scenes" / "20260524T104120Z__scene-runtime"
    (scene_dir / "events").mkdir(parents=True)
    scene_dir.joinpath("manifest.json").write_text(
        json.dumps({"runtime_scene_id": "scene-runtime"}),
        encoding="utf-8",
    )
    events_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "command_queue.command_queued",
                        "at": "2026-05-24T10:40:40+00:00",
                        "payload": {"commandId": "cmd-other", "type": "open_workbench"},
                    }
                ),
                json.dumps(
                    {
                        "type": "command_queue.command_queued",
                        "at": "2026-05-24T10:40:43+00:00",
                        "payload": {"commandId": "cmd-open", "type": "open_workbench"},
                    }
                ),
                json.dumps(
                    {
                        "type": "command_queue.command_claimed",
                        "at": "2026-05-24T10:40:52+00:00",
                        "payload": {"commandId": "cmd-open", "type": "open_workbench"},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    recorded: list[dict] = []

    class FakeRuntimeSceneService:
        @staticmethod
        def _resolve_current_runtime_scene_dir():
            return scene_dir

        @staticmethod
        def _resolve_recent_completed_runtime_scene_dir():
            raise AssertionError("queued events should not use recent completed package fallback")

        @staticmethod
        def record_runtime_scene_event(component, phase, event_code, **kwargs):
            recorded.append(
                {
                    "component": component,
                    "phase": phase,
                    "eventCode": event_code,
                    "kwargs": kwargs,
                }
            )
            return {"accepted": True, "runtimeSceneId": "scene-runtime"}

    monkeypatch.setattr(scene_logging, "EVENTS_PATH", events_path)
    monkeypatch.setattr(scene_logging, "_BACKFILLED_SCENE_KEYS", set())
    monkeypatch.setattr(scene_logging, "_runtime_scene_service", lambda: FakeRuntimeSceneService)

    accepted = scene_logging.record_runtime_manager_scene_event(
        "command.completed",
        {"commandId": "cmd-open", "type": "open_workbench", "ok": True},
        phase="command",
        occurred_at="2026-05-24T10:41:27+00:00",
    )

    assert accepted is True
    assert [event["eventCode"] for event in recorded] == [
        "command_queue.command_queued",
        "command_queue.command_claimed",
        "command.completed",
    ]
    assert [event["phase"] for event in recorded] == ["queue", "queue", "command"]
    assert recorded[0]["kwargs"]["occurred_at"] == "2026-05-24T10:40:43+00:00"
    assert recorded[0]["kwargs"]["fields"]["runtimeManagerBackfill"] is True
    assert recorded[-1]["kwargs"]["fields"]["runtimeManagerEventAt"] == "2026-05-24T10:41:27+00:00"


def test_runtime_manager_queue_event_does_not_target_recent_completed_package(tmp_path, monkeypatch):
    events_path = tmp_path / "events.jsonl"
    scene_dir = tmp_path / "logs" / "runtime_scenes" / "20260524T111509Z__scene-failed"
    (scene_dir / "events").mkdir(parents=True)
    events_path.write_text("", encoding="utf-8")
    recorded: list[dict] = []

    class FakeRuntimeSceneService:
        @staticmethod
        def _resolve_current_runtime_scene_dir():
            return None

        @staticmethod
        def _resolve_recent_completed_runtime_scene_dir():
            return scene_dir

        @staticmethod
        def record_runtime_scene_event(component, phase, event_code, **kwargs):
            recorded.append({"phase": phase, "eventCode": event_code, "kwargs": kwargs})
            return {"accepted": False, "reason": "no_runtime_scene"}

    monkeypatch.setattr(scene_logging, "EVENTS_PATH", events_path)
    monkeypatch.setattr(scene_logging, "_BACKFILLED_SCENE_KEYS", set())
    monkeypatch.setattr(scene_logging, "_runtime_scene_service", lambda: FakeRuntimeSceneService)

    accepted = scene_logging.record_runtime_manager_scene_event(
        "command_queue.command_queued",
        {"commandId": "cmd-new", "type": "open_workbench"},
        phase="queue",
        occurred_at="2026-05-24T11:19:55+00:00",
    )

    assert accepted is False
    assert recorded == [
        {
            "phase": "queue",
            "eventCode": "command_queue.command_queued",
            "kwargs": {
                "message": "Runtime manager queue event: command_queue.command_queued",
                "level": "info",
                "outcome": "queued",
                "fields": {
                    "commandId": "cmd-new",
                    "type": "open_workbench",
                    "runtimeManagerEventAt": "2026-05-24T11:19:55+00:00",
                },
                "lifecycle": True,
                "occurred_at": "2026-05-24T11:19:55+00:00",
                "allow_recent_completed": False,
            },
        }
    ]


def test_runtime_manager_scene_event_backfills_to_recent_completed_package(tmp_path, monkeypatch):
    events_path = tmp_path / "events.jsonl"
    scene_dir = tmp_path / "logs" / "runtime_scenes" / "20260524T111509Z__scene-failed"
    (scene_dir / "events").mkdir(parents=True)
    scene_dir.joinpath("manifest.json").write_text(
        json.dumps({"runtime_scene_id": "scene-failed", "status": "failed"}),
        encoding="utf-8",
    )
    events_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "command_queue.command_queued",
                        "at": "2026-05-24T11:14:37+00:00",
                        "payload": {"commandId": "cmd-failed", "type": "open_workbench"},
                    }
                ),
                json.dumps(
                    {
                        "type": "command_queue.command_queued",
                        "at": "2026-05-24T11:14:38+00:00",
                        "payload": {"commandId": "cmd-other", "type": "open_workbench"},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    recorded: list[dict] = []

    class FakeRuntimeSceneService:
        @staticmethod
        def _resolve_current_runtime_scene_dir():
            return None

        @staticmethod
        def _resolve_recent_completed_runtime_scene_dir():
            return scene_dir

        @staticmethod
        def record_runtime_scene_event(component, phase, event_code, **kwargs):
            recorded.append({"phase": phase, "eventCode": event_code, "kwargs": kwargs})
            return {"accepted": True, "runtimeSceneId": "scene-failed"}

    monkeypatch.setattr(scene_logging, "EVENTS_PATH", events_path)
    monkeypatch.setattr(scene_logging, "_BACKFILLED_SCENE_KEYS", set())
    monkeypatch.setattr(scene_logging, "_runtime_scene_service", lambda: FakeRuntimeSceneService)

    accepted = scene_logging.record_runtime_manager_scene_event(
        "command.failed",
        {"commandId": "cmd-failed", "type": "open_workbench", "ok": False},
        phase="command",
        occurred_at="2026-05-24T11:15:17+00:00",
    )

    assert accepted is True
    assert [event["eventCode"] for event in recorded] == ["command_queue.command_queued", "command.failed"]
    assert recorded[0]["kwargs"]["fields"]["runtimeManagerBackfill"] is True
    assert all(event["kwargs"]["fields"]["commandId"] == "cmd-failed" for event in recorded)


def test_ensure_daemon_running_restarts_stale_source_signature(monkeypatch, tmp_path):
    events: list[tuple[str, dict]] = []
    terminated: list[int] = []
    popen_calls: list[list[str]] = []
    running_checks = iter([False, True])

    monkeypatch.setattr(daemon, "load_pid", lambda: 12345)
    monkeypatch.setattr(daemon, "_is_process_alive", lambda pid: pid == 12345)
    monkeypatch.setattr(
        daemon,
        "load_state",
        lambda: {
            "runtimeManager": {"sourceSignature": "old-signature"},
            "command": {"activeCommandId": "", "startedAt": ""},
        },
    )
    monkeypatch.setattr(daemon, "_process_source_signature", lambda: "new-signature")
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))
    monkeypatch.setattr(daemon, "_terminate_daemon_process", lambda pid: terminated.append(pid))
    monkeypatch.setattr(daemon, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(daemon, "is_daemon_running", lambda: next(running_checks))
    monkeypatch.setattr(daemon, "DAEMON_STDOUT_PATH", tmp_path / "daemon.out.log")
    monkeypatch.setattr(daemon, "DAEMON_STDERR_PATH", tmp_path / "daemon.err.log")
    monkeypatch.setattr(
        daemon.subprocess,
        "Popen",
        lambda args, **kwargs: popen_calls.append(args) or type("Proc", (), {"pid": 24680})(),
    )
    expected_runtime = daemon._select_daemon_python_runtime("python-test")

    assert daemon.ensure_daemon_running(python_executable="python-test") is True
    assert terminated == [12345]
    assert events == [
        ("daemon.restart_requested", {"pid": 12345, "reason": "runtime_manager_source_changed"}),
        (
            "daemon.start_requested",
            {
                "launchPid": 24680,
                "pythonExecutable": expected_runtime["pythonExecutable"],
                "sourcePythonExecutable": expected_runtime["sourcePythonExecutable"],
                "noConsolePythonExecutable": expected_runtime["noConsolePythonExecutable"],
                "consoleWindowSuppressed": expected_runtime["consoleWindowSuppressed"],
                "consoleSuppressionMode": expected_runtime["consoleSuppressionMode"],
                "consoleFallbackReason": expected_runtime["consoleFallbackReason"],
                "pythonLaunchPolicy": expected_runtime["pythonLaunchPolicy"],
                "creationFlagNames": expected_runtime["creationFlagNames"],
            },
        ),
    ]
    assert popen_calls == [["python-test", "-m", "core.runtime_manager.cli", "daemon"]]


def test_rotate_daemon_log_file_rotates_when_exceeding_max_bytes(monkeypatch, tmp_path):
    log_path = tmp_path / "daemon.out.log"
    log_path.write_text("seed", encoding="utf-8")

    result = daemon._rotate_daemon_log_file(log_path, max_bytes=3, backup_count=2)
    assert result["rotated"] is True
    assert result["action"] == "rotated"
    assert result["sizeBytes"] == 4
    assert result["backupPath"] == str(log_path.with_name("daemon.out.log.1"))
    assert log_path.exists()
    assert log_path.stat().st_size == 0
    assert log_path.with_name("daemon.out.log.1").read_text(encoding="utf-8") == "seed"
    assert not log_path.with_name("daemon.out.log.2").exists()


def test_rotate_daemon_log_file_truncates_when_backup_disabled(monkeypatch, tmp_path):
    log_path = tmp_path / "daemon.err.log"
    log_path.write_text("very-long-content", encoding="utf-8")

    result = daemon._rotate_daemon_log_file(log_path, max_bytes=3, backup_count=0)
    assert result["rotated"] is True
    assert result["action"] == "truncated"
    assert log_path.exists()
    assert log_path.stat().st_size == 0


def test_rotate_daemon_logs_before_launch_emits_events(monkeypatch, tmp_path):
    stdout = tmp_path / "daemon.out.log"
    stderr = tmp_path / "daemon.err.log"
    stdout.write_text("seed", encoding="utf-8")
    stderr.write_text("seed", encoding="utf-8")
    monkeypatch.setattr(daemon, "DAEMON_STDOUT_PATH", stdout)
    monkeypatch.setattr(daemon, "DAEMON_STDERR_PATH", stderr)
    monkeypatch.setattr(daemon, "DAEMON_LOG_MAX_BYTES", 3)

    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))

    daemon._rotate_daemon_logs_before_launch()

    assert events
    assert all(event_type == "daemon.log_rotation.completed" for event_type, _ in events)
    assert {payload["path"] for _, payload in events} == {str(stdout), str(stderr)}


def test_ensure_daemon_running_rotates_large_daemon_logs_before_launch(monkeypatch, tmp_path):
    events: list[tuple[str, dict]] = []
    popen_calls: list[list[str]] = []
    running_checks = iter([False, True])
    stdout_path = tmp_path / "daemon.out.log"
    stderr_path = tmp_path / "daemon.err.log"
    stdout_path.write_text("x" * 32, encoding="utf-8")
    stderr_path.write_text("y" * 28, encoding="utf-8")
    (tmp_path / "daemon.out.log.1").write_text("older stdout", encoding="utf-8")

    monkeypatch.setattr(daemon, "load_pid", lambda: 0)
    monkeypatch.setattr(daemon, "_is_process_alive", lambda pid: False)
    monkeypatch.setattr(daemon, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(daemon, "is_daemon_running", lambda: next(running_checks))
    monkeypatch.setattr(daemon, "DAEMON_STDOUT_PATH", stdout_path)
    monkeypatch.setattr(daemon, "DAEMON_STDERR_PATH", stderr_path)
    monkeypatch.setattr(daemon, "DAEMON_LOG_MAX_BYTES", 10)
    monkeypatch.setattr(daemon, "DAEMON_LOG_BACKUP_COUNT", 2)
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))
    monkeypatch.setattr(
        daemon.subprocess,
        "Popen",
        lambda args, **kwargs: popen_calls.append(args) or type("Proc", (), {"pid": 24680})(),
    )

    assert daemon.ensure_daemon_running(python_executable="python-test") is True

    assert stdout_path.read_text(encoding="utf-8") == ""
    assert stderr_path.read_text(encoding="utf-8") == ""
    assert (tmp_path / "daemon.out.log.1").read_text(encoding="utf-8") == "x" * 32
    assert (tmp_path / "daemon.out.log.2").read_text(encoding="utf-8") == "older stdout"
    assert (tmp_path / "daemon.err.log.1").read_text(encoding="utf-8") == "y" * 28
    assert [event_type for event_type, _ in events] == [
        "daemon.log_rotation.completed",
        "daemon.log_rotation.completed",
        "daemon.start_requested",
    ]
    assert events[0][1]["path"] == str(stdout_path)
    assert events[0][1]["sizeBytes"] == 32
    assert events[0][1]["backupPath"] == str(tmp_path / "daemon.out.log.1")
    assert popen_calls == [["python-test", "-m", "core.runtime_manager.cli", "daemon"]]


def test_ensure_daemon_running_keeps_current_source_signature(monkeypatch):
    monkeypatch.setattr(daemon, "load_pid", lambda: 12345)
    monkeypatch.setattr(daemon, "_is_process_alive", lambda pid: True)
    monkeypatch.setattr(
        daemon,
        "load_state",
        lambda: {
            "runtimeManager": {"sourceSignature": "same-signature"},
            "command": {"activeCommandId": "", "startedAt": ""},
        },
    )
    monkeypatch.setattr(daemon, "_process_source_signature", lambda: "same-signature")

    assert daemon.ensure_daemon_running() is False


def test_ensure_daemon_running_prefers_python_exe_with_hidden_creation_flags(tmp_path, monkeypatch):
    python_exe = tmp_path / "Scripts" / "python.exe"
    pythonw_exe = tmp_path / "Scripts" / "pythonw.exe"
    python_exe.parent.mkdir()
    python_exe.write_text("", encoding="utf-8")
    pythonw_exe.write_text("", encoding="utf-8")
    running_checks = iter([False, True])
    popen_calls = []
    events: list[tuple[str, dict]] = []

    monkeypatch.setattr(daemon, "load_pid", lambda: 0)
    monkeypatch.setattr(daemon, "_is_process_alive", lambda pid: False)
    monkeypatch.setattr(daemon, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(daemon, "is_daemon_running", lambda: next(running_checks))
    monkeypatch.setattr(daemon, "DAEMON_STDOUT_PATH", tmp_path / "daemon.out.log")
    monkeypatch.setattr(daemon, "DAEMON_STDERR_PATH", tmp_path / "daemon.err.log")
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))
    monkeypatch.setattr(
        daemon.subprocess,
        "Popen",
        lambda args, **kwargs: popen_calls.append(args) or type("Proc", (), {"pid": 13579})(),
    )
    expected_runtime = daemon._select_daemon_python_runtime(str(python_exe))

    assert daemon.ensure_daemon_running(python_executable=str(python_exe)) is True

    assert popen_calls == [[expected_runtime["pythonExecutable"], "-m", "core.runtime_manager.cli", "daemon"]]
    if daemon.os.name == "nt":
        assert expected_runtime["pythonExecutable"] == str(python_exe.resolve())
        assert expected_runtime["noConsolePythonExecutable"] == str(pythonw_exe.resolve())
        assert expected_runtime["pythonLaunchPolicy"] == "source_python_with_hidden_creation_flags"
    assert events == [
        (
            "daemon.start_requested",
            {
                "launchPid": 13579,
                "pythonExecutable": expected_runtime["pythonExecutable"],
                "sourcePythonExecutable": expected_runtime["sourcePythonExecutable"],
                "noConsolePythonExecutable": expected_runtime["noConsolePythonExecutable"],
                "consoleWindowSuppressed": expected_runtime["consoleWindowSuppressed"],
                "consoleSuppressionMode": expected_runtime["consoleSuppressionMode"],
                "consoleFallbackReason": expected_runtime["consoleFallbackReason"],
                "pythonLaunchPolicy": expected_runtime["pythonLaunchPolicy"],
                "creationFlagNames": expected_runtime["creationFlagNames"],
            },
        )
    ]


def test_ensure_daemon_running_uses_python_exe_even_when_pythonw_missing(tmp_path, monkeypatch):
    python_exe = tmp_path / "Scripts" / "python.exe"
    python_exe.parent.mkdir()
    python_exe.write_text("", encoding="utf-8")
    running_checks = iter([False, True])
    popen_calls = []
    events: list[tuple[str, dict]] = []

    monkeypatch.setattr(daemon, "load_pid", lambda: 0)
    monkeypatch.setattr(daemon, "_is_process_alive", lambda pid: False)
    monkeypatch.setattr(daemon, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(daemon, "is_daemon_running", lambda: next(running_checks))
    monkeypatch.setattr(daemon, "DAEMON_STDOUT_PATH", tmp_path / "daemon.out.log")
    monkeypatch.setattr(daemon, "DAEMON_STDERR_PATH", tmp_path / "daemon.err.log")
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))
    monkeypatch.setattr(
        daemon.subprocess,
        "Popen",
        lambda args, **kwargs: popen_calls.append(args) or type("Proc", (), {"pid": 13579})(),
    )
    expected_runtime = daemon._select_daemon_python_runtime(str(python_exe))

    assert daemon.ensure_daemon_running(python_executable=str(python_exe)) is True

    assert popen_calls == [[expected_runtime["pythonExecutable"], "-m", "core.runtime_manager.cli", "daemon"]]
    if daemon.os.name == "nt":
        assert expected_runtime["pythonExecutable"] == str(python_exe.resolve())
        assert expected_runtime["noConsolePythonExecutable"] == ""
        assert expected_runtime["consoleFallbackReason"] == ""
    assert events == [
        (
            "daemon.start_requested",
            {
                "launchPid": 13579,
                "pythonExecutable": expected_runtime["pythonExecutable"],
                "sourcePythonExecutable": expected_runtime["sourcePythonExecutable"],
                "noConsolePythonExecutable": expected_runtime["noConsolePythonExecutable"],
                "consoleWindowSuppressed": expected_runtime["consoleWindowSuppressed"],
                "consoleSuppressionMode": expected_runtime["consoleSuppressionMode"],
                "consoleFallbackReason": expected_runtime["consoleFallbackReason"],
                "pythonLaunchPolicy": expected_runtime["pythonLaunchPolicy"],
                "creationFlagNames": expected_runtime["creationFlagNames"],
            },
        )
    ]


def test_load_launcher_state_supports_utf8_bom(tmp_path, monkeypatch):
    launcher_state_path = tmp_path / "state.json"
    launcher_state_path.write_text(
        json.dumps({"backendPid": 28888, "browserManaged": False}),
        encoding="utf-8-sig",
    )
    monkeypatch.setattr(workbench_controller, "LAUNCHER_STATE_PATH", launcher_state_path)

    state = workbench_controller._load_launcher_state()

    assert state["backendPid"] == 28888
    assert state["browserManaged"] is False


def test_observe_workbench_drops_stale_backend_pid(monkeypatch):
    monkeypatch.setattr(
        workbench_controller,
        "_load_launcher_state",
        lambda: {
            "url": "http://127.0.0.1:8000",
            "backendPid": 40904,
            "browserLaunchPid": 0,
            "browserWindowPid": 0,
            "browserManaged": False,
            "sessionId": "stale-no-browser",
        },
    )
    monkeypatch.setattr(workbench_controller, "_is_process_alive", lambda pid: False)
    monkeypatch.setattr(workbench_controller, "_is_backend_healthy", lambda url: False)
    monkeypatch.setattr(workbench_controller, "_listening_pid_for_port", lambda port: 0)
    monkeypatch.setattr(workbench_controller, "_port_is_listening_socket", lambda port: False)

    observation = workbench_controller.observe_workbench()

    assert observation["observedState"] == "closed"
    assert observation["backendPid"] == 0
    assert observation["backendAlive"] is False
    assert observation["backendObserved"] is False


def test_observe_workbench_reports_orphaned_browser(monkeypatch):
    monkeypatch.setattr(
        workbench_controller,
        "_load_launcher_state",
        lambda: {
            "url": "http://127.0.0.1:8000",
            "backendPid": 42608,
            "backendLaunchPid": 42608,
            "browserLaunchPid": 12132,
            "browserWindowPid": 12132,
            "browserManaged": True,
            "sessionId": "orphaned-browser",
        },
    )
    monkeypatch.setattr(workbench_controller, "_is_process_alive", lambda pid: pid == 12132)
    monkeypatch.setattr(workbench_controller, "_is_backend_healthy", lambda url: False)
    monkeypatch.setattr(workbench_controller, "_listening_pid_for_port", lambda port: 0)
    monkeypatch.setattr(workbench_controller, "_port_is_listening_socket", lambda port: False)

    observation = workbench_controller.observe_workbench()

    assert observation["observedState"] == "open"
    assert observation["backendObserved"] is False
    assert observation["browserWindowAlive"] is True
    assert observation["backendMissing"] is True
    assert observation["frontendOrphaned"] is True
    assert observation["lifecycleConsistency"] == "orphaned_browser"


def test_observe_workbench_reports_managed_browser_missing_as_partial(monkeypatch):
    monkeypatch.setattr(
        workbench_controller,
        "_load_launcher_state",
        lambda: {
            "url": "http://127.0.0.1:8000",
            "backendPid": 25744,
            "backendLaunchPid": 25744,
            "browserLaunchPid": 39880,
            "browserWindowPid": 39880,
            "browserManaged": True,
            "sessionId": "managed-browser-missing",
        },
    )
    monkeypatch.setattr(workbench_controller, "_is_process_alive", lambda pid: int(pid) == 25744)
    monkeypatch.setattr(workbench_controller, "_is_backend_healthy", lambda url: True)
    monkeypatch.setattr(workbench_controller, "_listening_pid_for_port", lambda port: 25744)
    monkeypatch.setattr(workbench_controller, "_port_is_listening_socket", lambda port: True)
    monkeypatch.setattr(workbench_controller, "_repo_workbench_backend_kind", lambda pid: "managed_workbench_backend")
    monkeypatch.setattr(workbench_controller, "_recover_managed_browser_window_pid", lambda profile_dir: 0)

    observation = workbench_controller.observe_workbench()

    assert observation["observedState"] == "partial"
    assert observation["backendObserved"] is True
    assert observation["backendMissing"] is False
    assert observation["frontendOrphaned"] is False
    assert observation["browserManaged"] is True
    assert observation["browserWindowAlive"] is False
    assert observation["lifecycleConsistency"] == "browser_missing"


def test_observe_workbench_reports_backend_launch_pid(monkeypatch):
    monkeypatch.setattr(
        workbench_controller,
        "_load_launcher_state",
        lambda: {
            "url": "http://127.0.0.1:8000",
            "backendPid": 25744,
            "backendLaunchPid": 43460,
            "browserLaunchPid": 39880,
            "browserWindowPid": 39880,
            "browserManaged": True,
            "sessionId": "managed-browser",
        },
    )
    monkeypatch.setattr(workbench_controller, "_is_process_alive", lambda pid: pid in {25744, 39880})
    monkeypatch.setattr(workbench_controller, "_is_backend_healthy", lambda url: True)
    monkeypatch.setattr(workbench_controller, "_listening_pid_for_port", lambda port: 25744)
    monkeypatch.setattr(workbench_controller, "_port_is_listening_socket", lambda port: True)

    observation = workbench_controller.observe_workbench()

    assert observation["observedState"] == "open"
    assert observation["backendPid"] == 25744
    assert observation["backendLaunchPid"] == 43460


def test_observe_workbench_recovers_managed_browser_window_from_profile(monkeypatch, tmp_path):
    profile_dir = tmp_path / "workbench-app-profile"
    profile_dir.mkdir()
    monkeypatch.setattr(
        workbench_controller,
        "_load_launcher_state",
        lambda: {
            "url": "http://127.0.0.1:8000",
            "backendPid": 25744,
            "backendLaunchPid": 43460,
            "browserLaunchPid": 4500,
            "browserWindowPid": 4500,
            "workbenchBrowserProfileDir": str(profile_dir),
            "browserManaged": True,
            "sessionId": "managed-browser-remap",
        },
    )
    monkeypatch.setattr(workbench_controller, "_is_process_alive", lambda pid: pid in {25744, 4600})
    monkeypatch.setattr(workbench_controller, "_is_backend_healthy", lambda url: True)
    monkeypatch.setattr(workbench_controller, "_listening_pid_for_port", lambda port: 25744)
    monkeypatch.setattr(workbench_controller, "_port_is_listening_socket", lambda port: True)
    monkeypatch.setattr(
        workbench_controller,
        "managed_browser_process_payload",
        lambda **kwargs: {
            "supported": True,
            "profileDir": str(profile_dir),
            "count": 2,
            "items": [
                {
                    "pid": 4600,
                    "parentPid": 1,
                    "name": "msedge.exe",
                    "type": "browser",
                    "subtype": "",
                    "workingSetMB": 100,
                    "privateMB": 90,
                    "commandLinePreview": f"msedge.exe --user-data-dir={profile_dir} --app=http://127.0.0.1:8000",
                },
                {
                    "pid": 4601,
                    "parentPid": 4600,
                    "name": "msedge.exe",
                    "type": "renderer",
                    "subtype": "",
                    "workingSetMB": 60,
                    "privateMB": 50,
                    "commandLinePreview": "msedge.exe --type=renderer",
                },
            ],
        },
    )

    observation = workbench_controller.observe_workbench()

    assert observation["observedState"] == "open"
    assert observation["browserWindowPid"] == 4600
    assert observation["browserWindowAlive"] is True
    assert observation["browserWindowRecoveredPid"] == 4600
    assert observation["browserWindowRecoverySource"] == "managed_profile"
    assert observation["lifecycleConsistency"] == "consistent"


def test_observe_workbench_can_skip_backend_observed_browser_recovery(monkeypatch, tmp_path):
    profile_dir = tmp_path / "workbench-app-profile"
    profile_dir.mkdir()
    recovery_calls: list[str] = []
    monkeypatch.setattr(
        workbench_controller,
        "_load_launcher_state",
        lambda: {
            "url": "http://127.0.0.1:8000",
            "backendPid": 25744,
            "backendLaunchPid": 25744,
            "browserLaunchPid": 39880,
            "browserWindowPid": 39880,
            "workbenchBrowserProfileDir": str(profile_dir),
            "browserManaged": True,
            "sessionId": "managed-browser-missing",
        },
    )
    monkeypatch.setattr(workbench_controller, "_is_process_alive", lambda pid: int(pid) == 25744)
    monkeypatch.setattr(workbench_controller, "_is_backend_healthy", lambda url: True)
    monkeypatch.setattr(workbench_controller, "_listening_pid_for_port", lambda port: 25744)
    monkeypatch.setattr(workbench_controller, "_port_is_listening_socket", lambda port: True)
    monkeypatch.setattr(workbench_controller, "_repo_workbench_backend_kind", lambda pid: "managed_workbench_backend")

    def recover_browser_window(profile_dir: str) -> int:
        recovery_calls.append(profile_dir)
        return 4600

    monkeypatch.setattr(workbench_controller, "_recover_managed_browser_window_pid", recover_browser_window)

    observation = workbench_controller.observe_workbench(recover_browser_window_for_backend_observed=False)

    assert observation["observedState"] == "partial"
    assert observation["backendObserved"] is True
    assert observation["browserWindowAlive"] is False
    assert observation["browserWindowRecoveredPid"] == 0
    assert observation["browserWindowRecoverySource"] == ""
    assert recovery_calls == []


def test_observe_workbench_still_recovers_orphaned_browser_in_close_mode(monkeypatch, tmp_path):
    profile_dir = tmp_path / "workbench-app-profile"
    profile_dir.mkdir()
    monkeypatch.setattr(
        workbench_controller,
        "_load_launcher_state",
        lambda: {
            "url": "http://127.0.0.1:8000",
            "backendPid": 25744,
            "backendLaunchPid": 25744,
            "browserLaunchPid": 4500,
            "browserWindowPid": 4500,
            "workbenchBrowserProfileDir": str(profile_dir),
            "browserManaged": True,
            "sessionId": "managed-browser-orphaned",
        },
    )
    monkeypatch.setattr(workbench_controller, "_is_process_alive", lambda pid: int(pid) == 4600)
    monkeypatch.setattr(workbench_controller, "_is_backend_healthy", lambda url: False)
    monkeypatch.setattr(workbench_controller, "_listening_pid_for_port", lambda port: 0)
    monkeypatch.setattr(workbench_controller, "_port_is_listening_socket", lambda port: False)
    monkeypatch.setattr(workbench_controller, "_repo_workbench_backend_kind", lambda pid: "")
    monkeypatch.setattr(workbench_controller, "_recover_managed_browser_window_pid", lambda profile_dir: 4600)

    observation = workbench_controller.observe_workbench(recover_browser_window_for_backend_observed=False)

    assert observation["observedState"] == "open"
    assert observation["backendObserved"] is False
    assert observation["browserWindowAlive"] is True
    assert observation["browserWindowRecoveredPid"] == 4600
    assert observation["browserWindowRecoverySource"] == "managed_profile"
    assert observation["lifecycleConsistency"] == "orphaned_browser"


def test_snapshot_residual_excluded_pids_includes_backend_launch_tree_root():
    excluded = daemon._snapshot_residual_excluded_pids(
        {
            "backendPid": 25744,
            "backendLaunchPid": 43460,
            "backendPortOwnerPid": 25744,
            "browserLaunchPid": 39880,
            "browserWindowPid": 39880,
        },
        manager_pid=45904,
    )

    assert {25744, 43460, 39880, 45904}.issubset(excluded)


def test_snapshot_residual_excluded_pids_includes_active_backend_parent(monkeypatch):
    monkeypatch.setattr(
        daemon,
        "list_repo_runtime_processes",
        lambda project_root=None: [
            process_inventory.RuntimeProcess(
                pid=44052,
                parent_pid=48240,
                kind="unmanaged_workbench",
                name="python.exe",
                command_line="python scripts/web_workbench.py --port 8000 --no-browser",
                cwd="C:/repo",
                port=8000,
            ),
            process_inventory.RuntimeProcess(
                pid=32344,
                parent_pid=44052,
                kind="unmanaged_workbench",
                name="python.exe",
                command_line="python scripts/web_workbench.py --port 8000 --no-browser",
                cwd="C:/repo",
                port=8000,
            ),
        ],
    )

    excluded = daemon._snapshot_residual_excluded_pids(
        {
            "backendPid": 32344,
            "backendLaunchPid": 32344,
            "backendPortOwnerPid": 32344,
            "browserWindowPid": 37160,
        },
        manager_pid=26360,
    )

    assert {32344, 44052, 37160, 26360}.issubset(excluded)


def test_run_launcher_action_passes_configured_port_to_launcher_env(monkeypatch):
    captured = {}
    events: list[tuple[str, dict]] = []

    class FakeProcess:
        def __init__(self, *args, **kwargs):
            captured["kwargs"] = kwargs
            kwargs["stdout"].write(b"ok\n")
            kwargs["stdout"].flush()

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(workbench_controller, "configured_backend_port", lambda: 9101)
    monkeypatch.setattr(workbench_controller.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(
        workbench_controller,
        "append_runtime_manager_file_event",
        lambda event_type, payload, **_kwargs: events.append((event_type, payload)),
    )

    result = workbench_controller.run_launcher_action("internal-start")

    assert result.returncode == 0
    assert captured["kwargs"]["env"]["VIBELUTION_PORT"] == "9101"
    completed = _event_payload(events, "launcher.action.completed")
    assert completed["durationMs"] >= 0


def test_run_launcher_action_hides_powershell_adapter_with_detached_waitable_process(monkeypatch):
    captured = {}

    class DummyStartupInfo:
        def __init__(self):
            self.dwFlags = 0
            self.wShowWindow = -1

    class FakeProcess:
        def __init__(self, *args, **kwargs):
            captured["kwargs"] = kwargs
            kwargs["stdout"].write(b"ok\n")
            kwargs["stdout"].flush()

        def wait(self, timeout=None):
            captured["wait_called"] = True
            return 0

    monkeypatch.setattr(workbench_controller.os, "name", "nt", raising=False)
    monkeypatch.setattr(workbench_controller.subprocess, "DETACHED_PROCESS", 0x00000008, raising=False)
    monkeypatch.setattr(workbench_controller.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200, raising=False)
    monkeypatch.setattr(workbench_controller.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(workbench_controller.subprocess, "STARTF_USESHOWWINDOW", 0x00000001, raising=False)
    monkeypatch.setattr(workbench_controller.subprocess, "SW_HIDE", 0, raising=False)
    monkeypatch.setattr(workbench_controller.subprocess, "STARTUPINFO", DummyStartupInfo, raising=False)
    monkeypatch.setattr(workbench_controller.subprocess, "Popen", FakeProcess)

    result = workbench_controller.run_launcher_action("internal-start")

    assert result.returncode == 0
    assert captured["wait_called"] is True
    assert captured["kwargs"]["creationflags"] & 0x00000008
    assert captured["kwargs"]["creationflags"] & 0x00000200
    assert captured["kwargs"]["creationflags"] & 0x08000000
    startupinfo = captured["kwargs"]["startupinfo"]
    assert isinstance(startupinfo, DummyStartupInfo)
    assert startupinfo.dwFlags & 0x00000001
    assert startupinfo.wShowWindow == 0


def test_run_launcher_action_events_report_detached_waitable_launch(monkeypatch):
    events: list[tuple[str, dict]] = []

    class FakeProcess:
        def __init__(self, *args, **kwargs):
            kwargs["stdout"].write(b"ok\n")
            kwargs["stdout"].flush()

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(workbench_controller.os, "name", "nt", raising=False)
    monkeypatch.setattr(workbench_controller.subprocess, "DETACHED_PROCESS", 0x00000008, raising=False)
    monkeypatch.setattr(workbench_controller.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200, raising=False)
    monkeypatch.setattr(workbench_controller.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(workbench_controller.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(
        workbench_controller,
        "append_runtime_manager_file_event",
        lambda event_type, payload, **_kwargs: events.append((event_type, payload)),
    )

    result = workbench_controller.run_launcher_action("internal-start")

    assert result.returncode == 0
    requested = _event_payload(events, "launcher.action.requested")
    completed = _event_payload(events, "launcher.action.completed")
    assert requested["launcherLaunchApi"] == "detached_waitable_popen"
    assert "DETACHED_PROCESS" in requested["creationFlagNames"]
    assert completed["launcherLaunchApi"] == "detached_waitable_popen"
    assert "DETACHED_PROCESS" in completed["creationFlagNames"]


def test_run_launcher_action_cancelable_path_remains_waitable_on_windows(monkeypatch):
    captured = {}

    class DummyStartupInfo:
        def __init__(self):
            self.dwFlags = 0
            self.wShowWindow = -1

    class FakeProcess:
        def __init__(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            self._poll_count = 0
            kwargs["stdout"].write(b"ready\n")
            kwargs["stdout"].flush()

        def poll(self):
            self._poll_count += 1
            return None if self._poll_count == 1 else 0

        def terminate(self):
            raise AssertionError("process should not be terminated")

        def kill(self):
            raise AssertionError("process should not be killed")

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(workbench_controller.os, "name", "nt", raising=False)
    monkeypatch.setattr(workbench_controller.subprocess, "DETACHED_PROCESS", 0x00000008, raising=False)
    monkeypatch.setattr(workbench_controller.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200, raising=False)
    monkeypatch.setattr(workbench_controller.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(workbench_controller.subprocess, "STARTF_USESHOWWINDOW", 0x00000001, raising=False)
    monkeypatch.setattr(workbench_controller.subprocess, "SW_HIDE", 0, raising=False)
    monkeypatch.setattr(workbench_controller.subprocess, "STARTUPINFO", DummyStartupInfo, raising=False)
    monkeypatch.setattr(workbench_controller.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(workbench_controller.time, "sleep", lambda _seconds: None)

    result = workbench_controller.run_launcher_action("internal-start", cancel_check=lambda: False)

    assert result.returncode == 0
    assert result.stdout == "ready\n"
    assert captured["kwargs"]["creationflags"] & 0x00000008
    assert captured["kwargs"]["creationflags"] & 0x00000200
    assert captured["kwargs"]["creationflags"] & 0x08000000
    startupinfo = captured["kwargs"]["startupinfo"]
    assert isinstance(startupinfo, DummyStartupInfo)
    assert startupinfo.dwFlags & 0x00000001
    assert startupinfo.wShowWindow == 0


def test_listening_pid_probe_hides_powershell_adapter_with_detached_process(monkeypatch):
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="12345\n", stderr="")

    monkeypatch.setattr(workbench_controller.os, "name", "nt", raising=False)
    monkeypatch.setattr(workbench_controller.subprocess, "DETACHED_PROCESS", 0x00000008, raising=False)
    monkeypatch.setattr(workbench_controller.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200, raising=False)
    monkeypatch.setattr(workbench_controller.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(workbench_controller.subprocess, "run", fake_run)

    pid = workbench_controller._listening_pid_for_port_windows(8000)

    assert pid == 12345
    assert captured["args"][:5] == ["powershell.exe", "-NoProfile", "-WindowStyle", "Hidden", "-Command"]
    assert captured["kwargs"]["creationflags"] & 0x00000008
    assert captured["kwargs"]["creationflags"] & 0x00000200
    assert captured["kwargs"]["creationflags"] & 0x08000000
    assert captured["kwargs"]["stdin"] is subprocess.DEVNULL


def test_handle_open_workbench_restarts_headless_session(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {},
        "workbench": {
            "desiredState": "open",
            "observedState": "open",
            "phase": "steady",
        },
    }

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(daemon, "now_iso", lambda: "2026-05-19T09:00:00+00:00")
    observations = _repeat_last(
        [
            {
                "observedState": "open",
                "launcherStatePresent": True,
                "browserManaged": False,
                "browserWindowAlive": False,
                "backendPid": 28888,
                "browserLaunchPid": 0,
                "browserWindowPid": 0,
                "backendHealthy": True,
                "backendObserved": True,
                "backendPortListening": True,
                "backendPortOwnerPid": 28888,
                "backendPortOwnerTrusted": True,
                "backendPortConflict": False,
                "sessionId": "headless-session",
                "url": "http://127.0.0.1:8000",
            },
            {
                "observedState": "open",
                "launcherStatePresent": True,
                "browserManaged": True,
                "browserWindowAlive": True,
                "backendPid": 28888,
                "browserLaunchPid": 4500,
                "browserWindowPid": 4500,
                "backendHealthy": True,
                "backendObserved": True,
                "backendPortListening": True,
                "backendPortOwnerPid": 28888,
                "backendPortOwnerTrusted": True,
                "backendPortConflict": False,
                "sessionId": "browser-session",
                "url": "http://127.0.0.1:8000",
            },
            {
                "observedState": "open",
                "launcherStatePresent": True,
                "browserManaged": True,
                "browserWindowAlive": True,
                "backendPid": 28888,
                "browserLaunchPid": 4500,
                "browserWindowPid": 4500,
                "backendHealthy": True,
                "backendObserved": True,
                "backendPortListening": True,
                "backendPortOwnerPid": 28888,
                "backendPortOwnerTrusted": True,
                "backendPortConflict": False,
                "sessionId": "browser-session",
                "url": "http://127.0.0.1:8000",
            },
        ]
    )
    monkeypatch.setattr(daemon, "observe_workbench", observations)
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})

    opened = {}
    events = []

    def fake_open_workbench(*, no_browser: bool, cancel_check=None):
        opened["no_browser"] = no_browser
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(daemon, "open_workbench", fake_open_workbench)
    monkeypatch.setattr(daemon, "_start_background_thread", lambda **kwargs: None)
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))

    result = runtime_daemon._handle_open_workbench(command_id="cmd-open", args={})

    assert result["ok"] is True
    assert result["message"] == "Workbench opened."
    assert opened == {"no_browser": False}
    success_payload = _event_payload(events, "workbench.open.verification_succeeded")
    assert success_payload | {
        "attempts": 1,
        "commandId": "cmd-open",
        "noBrowser": False,
        "observedState": "open",
        "launcherStatePresent": True,
        "backendPid": 28888,
        "backendHealthy": True,
        "backendObserved": True,
        "backendPort": 0,
        "backendPortListening": True,
        "backendPortOwnerPid": 28888,
        "backendPortOwnerTrusted": True,
        "backendPortConflict": False,
        "browserManaged": True,
        "browserWindowPid": 4500,
        "browserWindowAlive": True,
        "url": "http://127.0.0.1:8000",
        "healthUrl": "",
        "backendReady": True,
        "backendReadySource": "health_probe",
    } == success_payload
    backup_event = _event_payload(events, "workbench.stable_backup.queued")
    assert backup_event["commandId"] == "cmd-open"
    assert backup_event["reason"] == "launcher_open_success"
    assert result["stableBackup"]["status"] == "queued"
    assert result["stableBackup"]["mode"] == "background"


def test_handle_open_workbench_fails_when_launcher_exits_before_workbench_is_ready(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {},
        "workbench": {
            "desiredState": "closed",
            "observedState": "closed",
            "phase": "steady",
        },
    }
    saved_states = []
    events = []
    closed_observation = {
        "observedState": "closed",
        "launcherStatePresent": False,
        "browserManaged": True,
        "browserWindowAlive": False,
        "backendPid": 0,
        "browserLaunchPid": 0,
        "browserWindowPid": 0,
        "backendHealthy": False,
        "backendObserved": False,
        "backendPort": 8000,
        "backendPortListening": False,
        "backendPortOwnerPid": 0,
        "backendPortOwnerTrusted": False,
        "backendPortConflict": False,
        "sessionId": "",
        "url": "http://127.0.0.1:8000",
    }
    observations = _repeat_last([closed_observation, closed_observation])

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: saved_states.append(next_state) or next_state)
    monkeypatch.setattr(daemon, "observe_workbench", observations)
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(daemon, "residual_process_payload", lambda **kwargs: {"count": 0, "items": []})
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))
    monkeypatch.setattr(daemon, "_OPEN_VERIFICATION_TIMEOUT_SECONDS", 0)
    monkeypatch.setattr(
        daemon,
        "open_workbench",
        lambda *, no_browser, cancel_check=None: subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )

    result = runtime_daemon._handle_command(
        {
            "commandId": "cmd-open",
            "type": "open_workbench",
            "requestedBy": "test",
            "args": {"reason": "launcher_start"},
        }
    )

    assert result["ok"] is False
    assert result["errorType"] == "RuntimeError"
    assert "not ready" in result["message"]
    assert saved_states[-1]["workbench"]["phase"] == "failed"
    assert saved_states[-1]["workbench"]["desiredState"] == "open"
    assert saved_states[-1]["workbench"]["observedState"] == "closed"
    assert any(event_type == "workbench.open.verification_failed" for event_type, _payload in events)
    failed_payload = next(payload for event_type, payload in events if event_type == "workbench.open.verification_failed")
    assert failed_payload["commandId"] == "cmd-open"
    assert failed_payload["attempts"] == 1
    assert failed_payload["launcher"]["returnCode"] == 0


def test_handle_open_command_skips_prelaunch_reconcile(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {},
        "workbench": {
            "desiredState": "closed",
            "observedState": "closed",
            "phase": "steady",
        },
    }
    saved_states: list[dict] = []
    events: list[tuple[str, dict]] = []

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: saved_states.append(json.loads(json.dumps(next_state))) or next_state)
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))
    monkeypatch.setattr(
        type(runtime_daemon),
        "_reconcile_observation",
        lambda self, next_state: pytest.fail("open_workbench must not reconcile before launching"),
    )
    monkeypatch.setattr(
        runtime_daemon,
        "_handle_open_workbench",
        lambda *, command_id, args: {
            "commandId": command_id,
            "accepted": True,
            "completed": True,
            "ok": True,
            "message": "Workbench opened.",
        },
    )

    result = runtime_daemon._handle_command(
        {
            "commandId": "cmd-open",
            "type": "open_workbench",
            "requestedBy": "test",
            "args": {"reason": "launcher_start"},
        }
    )

    assert result["ok"] is True
    assert saved_states[0]["command"]["activeCommandId"] == "cmd-open"
    assert saved_states[0]["runtimeState"] == "running"
    assert _event_payload(events, "command.active_marked_fast_path")["commandId"] == "cmd-open"


def test_handle_open_workbench_skips_initial_observation_when_cached_closed(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {},
        "workbench": {
            "desiredState": "closed",
            "observedState": "closed",
            "phase": "steady",
        },
    }
    events: list[tuple[str, dict]] = []
    observe_calls = 0

    ready_observation = {
        "observedState": "open",
        "launcherStatePresent": True,
        "browserManaged": True,
        "browserWindowAlive": True,
        "backendPid": 28888,
        "browserLaunchPid": 4500,
        "browserWindowPid": 4500,
        "backendHealthy": True,
        "backendObserved": True,
        "backendPortListening": True,
        "backendPortOwnerPid": 28888,
        "backendPortOwnerTrusted": True,
        "backendPortConflict": False,
        "sessionId": "browser-session",
        "url": "http://127.0.0.1:8000",
    }

    def fake_observe_workbench():
        nonlocal observe_calls
        observe_calls += 1
        return dict(ready_observation)

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(daemon, "observe_workbench", fake_observe_workbench)
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(daemon, "_start_background_thread", lambda **kwargs: None)
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))
    monkeypatch.setattr(
        daemon,
        "open_workbench",
        lambda *, no_browser, cancel_check=None: subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )

    result = runtime_daemon._handle_open_workbench(command_id="cmd-open", args={})

    assert result["ok"] is True
    assert observe_calls == 1
    assert _event_payload(events, "workbench.open.fast_path_started")["prelaunchProbeSkipped"] is True


def test_successful_open_stable_backup_runs_in_background(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    events: list[tuple[str, dict]] = []
    started: dict[str, object] = {}

    def fake_start_background_thread(*, name, target):
        started["name"] = name
        started["target"] = target
        return None

    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))
    monkeypatch.setattr(daemon, "_start_background_thread", fake_start_background_thread)

    result = runtime_daemon._queue_stable_backup_after_successful_open(
        command_id="cmd-open",
        reason="launcher_open_success",
    )

    assert result == {"status": "queued", "mode": "background", "reason": "launcher_open_success"}
    queued_payload = _event_payload(events, "workbench.stable_backup.queued")
    assert queued_payload["commandId"] == "cmd-open"
    assert queued_payload["mode"] == "background"
    assert started["name"] == "vibelution-stable-backup-cmd-open"
    assert callable(started["target"])


def test_handle_open_workbench_retries_stale_browser_only_session(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {},
        "workbench": {
            "desiredState": "closed",
            "observedState": "closed",
            "phase": "steady",
        },
    }
    events: list[tuple[str, dict]] = []
    open_calls: list[bool] = []
    observations = _repeat_last(
        [
            {
                "observedState": "open",
                "launcherStatePresent": True,
                "browserManaged": True,
                "browserWindowAlive": True,
                "backendPid": 0,
                "browserLaunchPid": 38028,
                "browserWindowPid": 38028,
                "backendHealthy": False,
                "backendObserved": False,
                "backendPort": 8000,
                "backendPortListening": False,
                "backendPortOwnerPid": 0,
                "backendPortOwnerTrusted": False,
                "backendPortConflict": False,
                "sessionId": "stale-browser-session",
                "url": "http://127.0.0.1:8000",
                "healthUrl": "http://127.0.0.1:8000/api/health",
            },
            {
                "observedState": "open",
                "launcherStatePresent": True,
                "browserManaged": True,
                "browserWindowAlive": True,
                "backendPid": 49972,
                "browserLaunchPid": 33676,
                "browserWindowPid": 33676,
                "backendHealthy": True,
                "backendObserved": True,
                "backendPort": 8000,
                "backendPortListening": True,
                "backendPortOwnerPid": 51780,
                "backendPortOwnerTrusted": True,
                "backendPortConflict": False,
                "sessionId": "fresh-browser-session",
                "url": "http://127.0.0.1:8000",
                "healthUrl": "http://127.0.0.1:8000/api/health",
            },
        ]
    )

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(daemon, "observe_workbench", observations)
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))
    monkeypatch.setattr(daemon, "_OPEN_VERIFICATION_TIMEOUT_SECONDS", 0)
    monkeypatch.setattr(daemon, "_start_background_thread", lambda **kwargs: None)

    def fake_open_workbench(*, no_browser: bool, cancel_check=None):
        open_calls.append(no_browser)
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(daemon, "open_workbench", fake_open_workbench)

    result = runtime_daemon._handle_open_workbench(command_id="cmd-open", args={})

    assert result["ok"] is True
    assert result["message"] == "Workbench opened."
    assert open_calls == [False, False]
    assert [event_type for event_type, _payload in events if event_type != "workbench.open.fast_path_started"][:2] == [
        "workbench.open.stale_session_retry",
        "workbench.open.verification_succeeded",
    ]
    retry_payload = _event_payload(events, "workbench.open.stale_session_retry")
    assert retry_payload["commandId"] == "cmd-open"
    assert retry_payload["backendHealthy"] is False
    assert retry_payload["browserWindowAlive"] is True
    assert retry_payload["attempts"] == 1
    success_payload = _event_payload(events, "workbench.open.verification_succeeded")
    assert success_payload["backendHealthy"] is True
    assert success_payload["browserWindowPid"] == 33676
    assert success_payload["retry"] == "stale_session_cleanup"
    backup_event = _event_payload(events, "workbench.stable_backup.queued")
    assert backup_event["commandId"] == "cmd-open"
    assert backup_event["reason"] == "launcher_open_retry_success"
    assert result["stableBackup"]["status"] == "queued"


def test_handle_open_workbench_restarts_browser_missing_session(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {},
        "workbench": {
            "desiredState": "closed",
            "observedState": "closed",
            "phase": "steady",
        },
    }
    events: list[tuple[str, dict]] = []
    open_calls: list[bool] = []
    restart_calls: list[bool] = []
    observations = _repeat_last(
        [
            {
                "observedState": "partial",
                "launcherStatePresent": True,
                "browserManaged": True,
                "browserWindowAlive": False,
                "backendPid": 28888,
                "browserLaunchPid": 5168,
                "browserWindowPid": 5168,
                "backendHealthy": True,
                "backendObserved": True,
                "backendPort": 8000,
                "backendPortListening": True,
                "backendPortOwnerPid": 28888,
                "backendPortOwnerTrusted": True,
                "backendPortConflict": False,
                "lifecycleConsistency": "browser_missing",
                "sessionId": "browser-missing-session",
                "url": "http://127.0.0.1:8000",
                "healthUrl": "http://127.0.0.1:8000/api/health",
            },
            {
                "observedState": "open",
                "launcherStatePresent": True,
                "browserManaged": True,
                "browserWindowAlive": True,
                "backendPid": 28888,
                "browserLaunchPid": 4500,
                "browserWindowPid": 4500,
                "backendHealthy": True,
                "backendObserved": True,
                "backendPort": 8000,
                "backendPortListening": True,
                "backendPortOwnerPid": 28888,
                "backendPortOwnerTrusted": True,
                "backendPortConflict": False,
                "lifecycleConsistency": "consistent",
                "sessionId": "fresh-browser-session",
                "url": "http://127.0.0.1:8000",
                "healthUrl": "http://127.0.0.1:8000/api/health",
            },
        ]
    )

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(daemon, "observe_workbench", observations)
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))
    monkeypatch.setattr(daemon, "_OPEN_VERIFICATION_TIMEOUT_SECONDS", 0)
    monkeypatch.setattr(daemon, "_start_background_thread", lambda **kwargs: None)

    def fake_open_workbench(*, no_browser: bool, cancel_check=None):
        open_calls.append(no_browser)
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    def fake_restart_workbench(*, no_browser: bool, cancel_check=None):
        restart_calls.append(no_browser)
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(daemon, "open_workbench", fake_open_workbench)
    monkeypatch.setattr(daemon, "restart_workbench", fake_restart_workbench)

    result = runtime_daemon._handle_open_workbench(command_id="cmd-open", args={})

    assert result["ok"] is True
    assert result["message"] == "Workbench opened."
    assert open_calls == [False]
    assert restart_calls == [False]
    restart_payload = _event_payload(events, "workbench.open.browser_missing_restart")
    assert restart_payload["commandId"] == "cmd-open"
    assert restart_payload["backendHealthy"] is True
    assert restart_payload["browserWindowAlive"] is False
    assert restart_payload["lifecycleConsistency"] == "browser_missing"
    success_payload = _event_payload(events, "workbench.open.verification_succeeded")
    assert success_payload["browserWindowPid"] == 4500
    assert success_payload["retry"] == "browser_missing_restart"


def test_handle_open_workbench_accepts_trusted_backend_when_health_probe_lags(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {},
        "workbench": {
            "desiredState": "closed",
            "observedState": "closed",
            "phase": "steady",
        },
    }
    events: list[tuple[str, dict]] = []
    observations = _repeat_last(
        [
            {
                "observedState": "closed",
                "launcherStatePresent": False,
                "browserManaged": True,
                "browserWindowAlive": False,
                "backendPid": 0,
                "browserLaunchPid": 0,
                "browserWindowPid": 0,
                "backendHealthy": False,
                "backendObserved": False,
                "backendPort": 8000,
                "backendPortListening": False,
                "backendPortOwnerPid": 0,
                "backendPortOwnerTrusted": False,
                "backendPortConflict": False,
                "sessionId": "",
                "url": "http://127.0.0.1:8000",
            },
            {
                "observedState": "closed",
                "launcherStatePresent": False,
                "browserManaged": True,
                "browserWindowAlive": False,
                "backendPid": 0,
                "browserLaunchPid": 0,
                "browserWindowPid": 0,
                "backendHealthy": False,
                "backendObserved": False,
                "backendPort": 8000,
                "backendPortListening": False,
                "backendPortOwnerPid": 0,
                "backendPortOwnerTrusted": False,
                "backendPortConflict": False,
                "sessionId": "",
                "url": "http://127.0.0.1:8000",
            },
            {
                "observedState": "open",
                "launcherStatePresent": True,
                "browserManaged": True,
                "browserWindowAlive": True,
                "backendPid": 31216,
                "browserLaunchPid": 36760,
                "browserWindowPid": 36760,
                "backendHealthy": False,
                "backendObserved": True,
                "backendPort": 8000,
                "backendPortListening": True,
                "backendPortOwnerPid": 31216,
                "backendPortOwnerTrusted": True,
                "backendPortConflict": False,
                "backendPortOwnerKind": "managed_workbench_backend",
                "sessionId": "fresh-session",
                "url": "http://127.0.0.1:8000",
                "healthUrl": "http://127.0.0.1:8000/api/health",
            },
        ]
    )

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(daemon, "observe_workbench", observations)
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))
    monkeypatch.setattr(
        daemon,
        "open_workbench",
        lambda *, no_browser, cancel_check=None: subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )

    result = runtime_daemon._handle_open_workbench(command_id="cmd-open", args={})

    assert result["ok"] is True
    assert result["message"] == "Workbench opened."
    success_payload = _event_payload(events, "workbench.open.verification_succeeded")
    assert success_payload["backendHealthy"] is False
    assert success_payload["backendReady"] is True
    assert success_payload["backendReadySource"] == "launcher_confirmed_port"


def test_handle_open_workbench_no_browser_succeeds_when_backend_is_ready(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {},
        "workbench": {
            "desiredState": "closed",
            "observedState": "closed",
            "phase": "steady",
        },
    }
    observations = _repeat_last(
        [
            {
                "observedState": "open",
                "launcherStatePresent": True,
                "browserManaged": False,
                "browserWindowAlive": False,
                "backendPid": 28888,
                "browserLaunchPid": 0,
                "browserWindowPid": 0,
                "backendHealthy": True,
                "backendObserved": True,
                "backendPort": 8000,
                "backendPortListening": True,
                "backendPortOwnerPid": 28888,
                "backendPortOwnerTrusted": True,
                "backendPortConflict": False,
                "sessionId": "headless-session",
                "url": "http://127.0.0.1:8000",
            },
            {
                "observedState": "open",
                "launcherStatePresent": True,
                "browserManaged": False,
                "browserWindowAlive": False,
                "backendPid": 28888,
                "browserLaunchPid": 0,
                "browserWindowPid": 0,
                "backendHealthy": True,
                "backendObserved": True,
                "backendPort": 8000,
                "backendPortListening": True,
                "backendPortOwnerPid": 28888,
                "backendPortOwnerTrusted": True,
                "backendPortConflict": False,
                "sessionId": "headless-session",
                "url": "http://127.0.0.1:8000",
            },
        ]
    )

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(daemon, "observe_workbench", observations)
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    events = []
    monkeypatch.setattr(
        daemon,
        "open_workbench",
        lambda *, no_browser, cancel_check=None: subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))

    result = runtime_daemon._handle_open_workbench(command_id="cmd-open", args={"noBrowser": True})

    assert result["ok"] is True
    assert result["message"] == "Workbench opened."
    success_payload = _event_payload(events, "workbench.open.verification_succeeded")
    assert success_payload["commandId"] == "cmd-open"
    assert success_payload["noBrowser"] is True
    assert success_payload["attempts"] == 1


def test_open_verification_timeout_is_extended_for_slow_startups():
    assert daemon._OPEN_VERIFICATION_TIMEOUT_SECONDS >= 45


def test_handle_open_workbench_waits_for_delayed_backend_observation(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {},
        "workbench": {
            "desiredState": "closed",
            "observedState": "closed",
            "phase": "steady",
        },
    }
    observations = _repeat_last(
        [
            {
                "observedState": "closed",
                "launcherStatePresent": False,
                "browserManaged": True,
                "browserWindowAlive": False,
                "backendPid": 0,
                "browserLaunchPid": 0,
                "browserWindowPid": 0,
                "backendHealthy": False,
                "backendObserved": False,
                "backendPort": 8000,
                "backendPortListening": False,
                "backendPortOwnerPid": 0,
                "backendPortOwnerTrusted": False,
                "backendPortConflict": False,
                "sessionId": "",
                "url": "http://127.0.0.1:8000",
            },
            {
                "observedState": "closed",
                "launcherStatePresent": False,
                "browserManaged": True,
                "browserWindowAlive": False,
                "backendPid": 0,
                "browserLaunchPid": 0,
                "browserWindowPid": 0,
                "backendHealthy": False,
                "backendObserved": False,
                "backendPort": 8000,
                "backendPortListening": False,
                "backendPortOwnerPid": 0,
                "backendPortOwnerTrusted": False,
                "backendPortConflict": False,
                "sessionId": "",
                "url": "http://127.0.0.1:8000",
            },
            {
                "observedState": "closed",
                "launcherStatePresent": False,
                "browserManaged": True,
                "browserWindowAlive": False,
                "backendPid": 0,
                "browserLaunchPid": 0,
                "browserWindowPid": 0,
                "backendHealthy": False,
                "backendObserved": False,
                "backendPort": 8000,
                "backendPortListening": False,
                "backendPortOwnerPid": 0,
                "backendPortOwnerTrusted": False,
                "backendPortConflict": False,
                "sessionId": "",
                "url": "http://127.0.0.1:8000",
            },
            {
                "observedState": "open",
                "launcherStatePresent": True,
                "browserManaged": False,
                "browserWindowAlive": False,
                "backendPid": 28888,
                "browserLaunchPid": 0,
                "browserWindowPid": 0,
                "backendHealthy": True,
                "backendObserved": True,
                "backendPort": 8000,
                "backendPortListening": True,
                "backendPortOwnerPid": 28888,
                "backendPortOwnerTrusted": True,
                "backendPortConflict": False,
                "sessionId": "headless-session",
                "url": "http://127.0.0.1:8000",
            },
        ]
    )
    sleeps = []

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(daemon, "observe_workbench", observations)
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    fake_time = type(
        "FakeTime",
        (),
        {"monotonic": staticmethod(lambda: 0.0), "sleep": staticmethod(lambda seconds: sleeps.append(seconds))},
    )
    monkeypatch.setattr(daemon, "time", fake_time)
    monkeypatch.setattr(
        daemon,
        "open_workbench",
        lambda *, no_browser, cancel_check=None: subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )
    events = []
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))

    result = runtime_daemon._handle_open_workbench(command_id="cmd-open", args={"noBrowser": True})

    assert result["ok"] is True
    assert result["message"] == "Workbench opened."
    assert sleeps
    assert all(value == daemon._OPEN_VERIFICATION_POLL_INTERVAL_SECONDS for value in sleeps)
    assert _event_payload(events, "workbench.open.verification_succeeded")["attempts"] == len(sleeps) + 1


def test_handle_open_workbench_restarts_healthy_headless_session_when_browser_requested(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {},
        "workbench": {
            "desiredState": "open",
            "observedState": "open",
            "phase": "steady",
        },
    }

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(daemon, "now_iso", lambda: "2026-05-19T09:00:00+00:00")
    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        _repeat_last(
            [
                {
                    "observedState": "open",
                    "launcherStatePresent": True,
                    "browserManaged": False,
                    "browserWindowAlive": False,
                    "backendPid": 28888,
                    "browserLaunchPid": 0,
                    "browserWindowPid": 0,
                    "backendHealthy": True,
                    "backendObserved": True,
                    "backendPortListening": True,
                    "backendPortOwnerPid": 28888,
                    "backendPortOwnerTrusted": True,
                    "backendPortConflict": False,
                    "sessionId": "headless-session",
                    "url": "http://127.0.0.1:8000",
                },
                {
                    "observedState": "open",
                    "launcherStatePresent": True,
                    "browserManaged": True,
                    "browserWindowAlive": True,
                    "backendPid": 28888,
                    "browserLaunchPid": 4500,
                    "browserWindowPid": 4500,
                    "backendHealthy": True,
                    "backendObserved": True,
                    "backendPortListening": True,
                    "backendPortOwnerPid": 28888,
                    "backendPortOwnerTrusted": True,
                    "backendPortConflict": False,
                    "sessionId": "browser-session",
                    "url": "http://127.0.0.1:8000",
                },
            ]
        ),
    )
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})

    opened = {}
    events = []

    def fake_open_workbench(*, no_browser: bool, cancel_check=None):
        opened["no_browser"] = no_browser
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(daemon, "open_workbench", fake_open_workbench)
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))

    result = runtime_daemon._handle_open_workbench(command_id="cmd-open", args={})

    assert result["ok"] is True
    assert result["message"] == "Workbench opened."
    assert opened == {"no_browser": False}
    assert _event_payload(events, "workbench.open.verification_succeeded")["commandId"] == "cmd-open"


def test_handle_open_workbench_interrupts_launcher_when_close_is_requested(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    events: list[tuple[str, dict]] = []
    state_holder = {
        "value": {
            "command": {"activeCommandId": "cmd-open", "activeType": "open_workbench"},
            "workbench": {"desiredState": "closed", "observedState": "closed", "phase": "steady"},
        }
    }
    interrupt_holder: dict[str, dict] = {"value": {}}
    interrupt = {
        "interruptedCommandId": "cmd-open",
        "interruptedType": "open_workbench",
        "closeCommandId": "cmd-force",
        "closeCommandType": "force_close_workbench",
        "operation": "force_close",
    }

    monkeypatch.setattr(daemon, "load_state", lambda: json.loads(json.dumps(state_holder["value"])))
    monkeypatch.setattr(
        daemon,
        "save_state",
        lambda next_state: state_holder.update({"value": json.loads(json.dumps(next_state))}) or next_state,
    )
    monkeypatch.setattr(daemon, "now_iso", lambda: "2026-06-12T09:40:00+00:00")
    monkeypatch.setattr(daemon, "observe_workbench", lambda: {"observedState": "closed"})
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))
    monkeypatch.setattr(
        daemon,
        "lifecycle_interrupt_requested",
        lambda command_id: interrupt_holder["value"] if command_id == "cmd-open" else None,
    )
    cleared: list[str] = []
    monkeypatch.setattr(daemon, "clear_lifecycle_interrupt", lambda command_id: cleared.append(command_id))

    def fake_open_workbench(*, no_browser: bool, cancel_check=None):
        assert no_browser is False
        interrupt_holder["value"] = interrupt
        assert cancel_check is not None and cancel_check()
        return subprocess.CompletedProcess(
            args=[],
            returncode=daemon.LAUNCHER_ACTION_CANCELLED_RETURN_CODE,
            stdout="",
            stderr="cancelled",
        )

    monkeypatch.setattr(daemon, "open_workbench", fake_open_workbench)
    monkeypatch.setattr(
        daemon,
        "_wait_for_open_verification",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("interrupted open must not verify")),
    )

    result = runtime_daemon._handle_open_workbench(command_id="cmd-open", args={})

    assert result["ok"] is False
    assert result["errorType"] == "SupersededByForceCloseWorkbench"
    assert result["interruptedByClose"] is True
    assert result["supersededByCommandId"] == "cmd-force"
    assert result["launcher"]["returnCode"] == daemon.LAUNCHER_ACTION_CANCELLED_RETURN_CODE
    assert cleared == ["cmd-open"]
    assert "workbench.open.interrupted_by_close" in [event_type for event_type, _ in events]
    assert state_holder["value"]["workbench"]["phase"] != "failed"


def test_handle_open_workbench_refocuses_existing_browser_session(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {},
        "workbench": {
            "desiredState": "open",
            "observedState": "open",
            "phase": "steady",
        },
    }

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        lambda: {
            "observedState": "open",
            "launcherStatePresent": True,
            "browserManaged": True,
            "browserWindowAlive": True,
            "backendPid": 28888,
            "browserLaunchPid": 4500,
            "browserWindowPid": 4500,
            "backendHealthy": True,
            "backendObserved": True,
            "backendPortListening": True,
            "backendPortOwnerPid": 28888,
            "backendPortOwnerTrusted": True,
            "backendPortConflict": False,
            "sessionId": "browser-session",
            "url": "http://127.0.0.1:8000",
        },
    )

    focused = {}
    events: list[tuple[str, dict]] = []

    def fake_focus_workbench():
        focused["called"] = True
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="Focused existing workbench.\n", stderr="")

    monkeypatch.setattr(daemon, "focus_workbench", fake_focus_workbench)
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))

    result = runtime_daemon._handle_open_workbench(command_id="cmd-open", args={})

    assert result["ok"] is True
    assert result["message"] == "Workbench is already open."
    assert focused == {"called": True}
    assert events == [
        (
            "workbench.open.already_satisfied",
            {
                "commandId": "cmd-open",
                "noBrowser": False,
                "focusRequested": True,
                "observedState": "open",
                "backendPid": 28888,
                "backendHealthy": True,
                "backendObserved": True,
                "browserManaged": True,
                "browserWindowPid": 4500,
                "browserWindowAlive": True,
                "sessionId": "browser-session",
                "url": "http://127.0.0.1:8000",
            },
        ),
        (
            "workbench.open.focus_requested",
            {
                "commandId": "cmd-open",
                "returnCode": 0,
                "stdout": "Focused existing workbench.",
                "stderr": "",
            },
        ),
    ]


def test_handle_open_workbench_logs_focus_failure_for_existing_browser_session(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {},
        "workbench": {
            "desiredState": "open",
            "observedState": "open",
            "phase": "steady",
        },
    }
    observation = {
        "observedState": "open",
        "launcherStatePresent": True,
        "browserManaged": True,
        "browserWindowAlive": True,
        "backendPid": 28888,
        "browserLaunchPid": 4500,
        "browserWindowPid": 4500,
        "backendHealthy": True,
        "backendObserved": True,
        "backendPortListening": True,
        "backendPortOwnerPid": 28888,
        "backendPortOwnerTrusted": True,
        "backendPortConflict": False,
        "sessionId": "browser-session",
        "url": "http://127.0.0.1:8000",
    }
    events: list[tuple[str, dict]] = []

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(daemon, "observe_workbench", lambda: observation)
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))
    monkeypatch.setattr(
        daemon,
        "focus_workbench",
        lambda: subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="No managed browser window was available to focus.",
        ),
    )

    with pytest.raises(RuntimeError, match="No managed browser window"):
        runtime_daemon._handle_open_workbench(command_id="cmd-open", args={})

    assert [event_type for event_type, _ in events] == [
        "workbench.open.already_satisfied",
        "workbench.open.focus_failed",
    ]
    assert events[1][1] == {
        "commandId": "cmd-open",
        "returnCode": 1,
        "detail": "No managed browser window was available to focus.\nLauncher exit code: 1",
    }


def test_run_launcher_action_uses_devnull_stdio(monkeypatch):
    captured = {}
    events: list[tuple[str, dict]] = []

    class FakeProcess:
        def __init__(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            kwargs["stdout"].write(b"launcher stdout\n")
            kwargs["stdout"].flush()
            kwargs["stderr"].write(b"launcher stderr\n")
            kwargs["stderr"].flush()

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(workbench_controller.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(
        workbench_controller,
        "append_runtime_manager_file_event",
        lambda event_type, payload, **kwargs: events.append((event_type, payload)) or "2026-05-19T09:00:00+00:00",
    )

    result = workbench_controller.run_launcher_action("internal-start", no_browser=True)

    assert result.returncode == 0
    assert result.stdout == "launcher stdout\n"
    assert result.stderr == "launcher stderr\n"
    assert captured["args"][0][-2:] == ["internal-start", "-NoBrowser"]
    assert captured["kwargs"]["stdin"] is subprocess.DEVNULL
    assert "capture_output" not in captured["kwargs"]
    assert "text" not in captured["kwargs"]
    assert captured["kwargs"]["stdout"] is not None
    assert captured["kwargs"]["stderr"] is not None
    assert events[-1][0] == "launcher.action.completed"
    assert events[-1][1]["stdoutTail"] == "launcher stdout\n"
    assert events[-1][1]["stderrTail"] == "launcher stderr\n"


def test_handle_restart_workbench_surfaces_launcher_error(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {},
        "workbench": {
            "desiredState": "open",
            "observedState": "open",
            "phase": "steady",
        },
    }

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(daemon, "now_iso", lambda: "2026-05-19T09:00:00+00:00")
    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        _repeat_last(
            [
                {
                    "observedState": "open",
                    "launcherStatePresent": True,
                    "browserManaged": True,
                    "browserWindowAlive": True,
                    "backendPid": 28888,
                    "browserLaunchPid": 29999,
                    "browserWindowPid": 29999,
                    "backendAlive": True,
                    "backendHealthy": True,
                    "backendObserved": True,
                    "backendPortListening": True,
                    "backendPortOwnerPid": 28888,
                    "sessionId": "managed-session",
                    "url": "http://127.0.0.1:8000",
                },
                {
                    "observedState": "closed",
                    "launcherStatePresent": False,
                    "browserManaged": True,
                    "browserWindowAlive": False,
                    "backendPid": 0,
                    "browserLaunchPid": 0,
                    "browserWindowPid": 0,
                    "backendAlive": False,
                    "backendHealthy": False,
                    "backendObserved": False,
                    "backendPortListening": False,
                    "backendPortOwnerPid": 0,
                    "sessionId": "",
                    "url": "http://127.0.0.1:8000",
                },
            ]
        ),
    )
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(
        daemon.RuntimeManagerDaemon,
        "_force_cleanup_workbench_processes",
        lambda self, observation=None: {"supported": False, "requested": [], "terminated": [], "remaining": []},
    )
    monkeypatch.setattr(
        daemon,
        "close_workbench",
        lambda: subprocess.CompletedProcess(args=[], returncode=1, stdout=None, stderr="launcher failed"),
    )

    with pytest.raises(RuntimeError, match="launcher failed"):
        runtime_daemon._handle_restart_workbench(
            command_id="cmd-restart",
            args={"skipFrontendBuildPreflight": True},
        )


def test_handle_restart_workbench_blocks_active_chat_turn_before_close(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {"activeCommandId": "cmd-restart"},
        "workbench": {
            "desiredState": "open",
            "observedState": "open",
            "phase": "steady",
        },
    }
    events: list[tuple[str, dict]] = []
    close_calls: list[str] = []

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(daemon, "observe_workbench", lambda: {"observedState": "open"})
    monkeypatch.setattr(
        daemon,
        "_runtime_manager_active_work_runs",
        lambda: [{"kind": "chat_turn", "runId": "chat-live", "status": "running", "sessionId": "session-a"}],
    )
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))
    monkeypatch.setattr(
        daemon,
        "close_workbench",
        lambda: close_calls.append("close") or subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )

    result = runtime_daemon._handle_restart_workbench(
        command_id="cmd-restart",
        args={"reason": "launcher_restart", "source": "launcher_ps"},
    )

    assert result["ok"] is False
    assert result["errorType"] == "ActiveWorkBlocked"
    assert result["message"] == "有进行中的任务，无法重启 Vibelution。请等待任务完成或先停止任务。"
    assert result["activeWorkRuns"]["count"] == 1
    assert close_calls == []
    assert events[0] == (
        "workbench.restart.blocked_active_work",
        {
            "commandId": "cmd-restart",
            "commandType": "restart_workbench",
            "reason": "launcher_restart",
            "source": "launcher_ps",
            "activeWorkCount": 1,
            "activeWorkRuns": [
                {"kind": "chat_turn", "runId": "chat-live", "status": "running", "sessionId": "session-a"}
            ],
        },
    )
    assert state["lastError"]["scope"] == "active_work"
    assert state["workbench"]["phase"] != "failed"


def test_handle_restart_workbench_blocks_when_active_work_probe_fails(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {"activeCommandId": "cmd-restart"},
        "workbench": {
            "desiredState": "open",
            "observedState": "open",
            "phase": "steady",
        },
    }
    events: list[tuple[str, dict]] = []
    close_calls: list[str] = []

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(daemon, "observe_workbench", lambda: {"observedState": "open"})
    monkeypatch.setattr(
        daemon,
        "_runtime_manager_active_work_runs",
        lambda: (_ for _ in ()).throw(
            daemon.ActiveWorkProbeFailed(
                source="list_active_session_work_runs",
                error_type="RuntimeError",
                message="session store unavailable",
            )
        ),
    )
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))
    monkeypatch.setattr(
        daemon,
        "close_workbench",
        lambda: close_calls.append("close") or subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )

    result = runtime_daemon._handle_restart_workbench(
        command_id="cmd-restart",
        args={"reason": "launcher_restart", "source": "launcher_ps"},
    )

    assert result["ok"] is False
    assert result["errorType"] == "ActiveWorkProbeFailed"
    assert result["message"] == "有进行中的任务，无法重启 Vibelution。请等待任务完成或先停止任务。"
    assert result["activeWorkRuns"] == {
        "count": 0,
        "items": [],
        "allowedItems": [],
        "probeFailed": True,
        "probeSource": "list_active_session_work_runs",
        "probeErrorType": "RuntimeError",
    }
    assert close_calls == []
    assert events[0] == (
        "workbench.restart.blocked_active_work_probe_failed",
        {
            "commandId": "cmd-restart",
            "commandType": "restart_workbench",
            "reason": "launcher_restart",
            "source": "launcher_ps",
            "probeSource": "list_active_session_work_runs",
            "errorType": "RuntimeError",
            "message": "session store unavailable",
        },
    )
    assert state["lastError"]["scope"] == "active_work"
    assert state["workbench"]["phase"] != "failed"


def test_handle_restart_workbench_defers_active_chat_turn_before_close(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {"activeCommandId": "cmd-restart"},
        "workbench": {
            "desiredState": "open",
            "observedState": "open",
            "phase": "steady",
        },
    }
    events: list[tuple[str, dict]] = []
    close_calls: list[str] = []

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(daemon, "observe_workbench", lambda: {"observedState": "open"})
    monkeypatch.setattr(
        daemon,
        "_runtime_manager_active_work_runs",
        lambda: [{"kind": "chat_turn", "runId": "chat-live", "status": "running", "sessionId": "session-a"}],
    )
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))
    monkeypatch.setattr(
        daemon,
        "close_workbench",
        lambda: close_calls.append("close") or subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )

    result = runtime_daemon._handle_restart_workbench(
        command_id="cmd-restart",
        args={
            "reason": "web_restart_button",
            "source": "web_ui",
            "deferredUntilActiveWorkClear": True,
        },
    )

    assert result["completed"] is False
    assert result["deferCommandUntilActiveWorkClear"] is True
    assert result["activeWorkRuns"][0]["runId"] == "chat-live"
    assert close_calls == []
    assert events[0] == (
        "workbench.restart.deferred_active_work_wait",
        {
            "commandId": "cmd-restart",
            "commandType": "restart_workbench",
            "reason": "web_restart_button",
            "source": "web_ui",
            "activeWorkCount": 1,
            "activeWorkRuns": [
                {"kind": "chat_turn", "runId": "chat-live", "status": "running", "sessionId": "session-a"}
            ],
        },
    )
    assert "lastError" not in state
    assert state["workbench"]["phase"] != "failed"


def test_handle_restart_workbench_build_preflight_fails_before_close(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {"activeCommandId": "cmd-restart"},
        "workbench": {
            "desiredState": "open",
            "observedState": "open",
            "phase": "steady",
            "backendAlive": True,
            "browserWindowAlive": True,
            "browserManaged": True,
            "browserWindowPid": 4567,
        },
    }
    events: list[tuple[str, dict]] = []
    close_calls: list[str] = []

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(daemon, "observe_workbench", lambda: dict(state["workbench"]))
    monkeypatch.setattr(daemon, "_runtime_manager_active_work_runs", lambda: [])
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))
    monkeypatch.setattr(
        daemon,
        "_preflight_frontend_build_for_restart",
        lambda command_id: (_ for _ in ()).throw(RuntimeError("Restart preflight failed before closing the workbench.")),
    )
    monkeypatch.setattr(
        daemon,
        "close_workbench",
        lambda: close_calls.append("close") or subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )

    with pytest.raises(RuntimeError, match="Restart preflight failed before closing"):
        runtime_daemon._handle_restart_workbench(
            command_id="cmd-restart",
            args={"reason": "launcher_restart", "source": "launcher_ps"},
        )

    assert close_calls == []
    assert state["workbench"]["observedState"] == "open"


def test_restart_build_preflight_skips_when_frontend_build_is_current(monkeypatch):
    events: list[tuple[str, dict]] = []

    def fail_run(*args, **kwargs):
        raise AssertionError("frontend preflight should not run node commands when dist is current")

    monkeypatch.setattr(
        daemon,
        "_frontend_build_current",
        lambda: (True, "frontend build is current", {"distIndex": "web/dist/index.html", "distMtime": 20.0, "inputMtime": 10.0}),
    )
    monkeypatch.setattr(daemon.subprocess, "run", fail_run)
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))

    result = daemon._preflight_frontend_build_for_restart("cmd-restart")

    assert result["ok"] is True
    assert result["skipped"] is True
    assert result["completedSteps"] == []
    assert events == [
        (
            "workbench.restart.build_preflight_skipped_current",
            {
                "commandId": "cmd-restart",
                "ok": True,
                "skipped": True,
                "reason": "frontend build is current",
                "startedAt": result["startedAt"],
                "completedSteps": [],
                "freshness": {"distIndex": "web/dist/index.html", "distMtime": 20.0, "inputMtime": 10.0},
            },
        )
    ]


def test_restart_build_preflight_uses_hidden_node_entrypoints_on_windows(monkeypatch):
    calls: list[dict[str, object]] = []
    events: list[tuple[str, dict]] = []

    class DummyStartupInfo:
        def __init__(self):
            self.dwFlags = 0
            self.wShowWindow = -1

    def fake_run(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="built", stderr="")

    monkeypatch.setattr(daemon.os, "name", "nt")
    monkeypatch.setattr(daemon.shutil, "which", lambda command: "C:\\Program Files\\nodejs\\node.exe")
    monkeypatch.setattr(daemon.subprocess, "DETACHED_PROCESS", 0x00000008, raising=False)
    monkeypatch.setattr(daemon.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200, raising=False)
    monkeypatch.setattr(daemon.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(daemon.subprocess, "STARTF_USESHOWWINDOW", 0x00000001, raising=False)
    monkeypatch.setattr(daemon.subprocess, "SW_HIDE", 0, raising=False)
    monkeypatch.setattr(daemon.subprocess, "STARTUPINFO", DummyStartupInfo, raising=False)
    monkeypatch.setattr(daemon.subprocess, "run", fake_run)
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))
    monkeypatch.setattr(
        daemon,
        "_frontend_build_current",
        lambda: (False, "frontend sources changed", {"distIndex": "web/dist/index.html", "distMtime": 10.0, "inputMtime": 20.0}),
    )

    result = daemon._preflight_frontend_build_for_restart("cmd-restart")

    assert len(calls) == 2
    assert calls[0]["args"][0][0].endswith("node.exe")
    assert "typescript" in calls[0]["args"][0][1]
    assert calls[0]["args"][0][2:] == ["-b"]
    assert calls[1]["args"][0][0].endswith("node.exe")
    assert "vite" in calls[1]["args"][0][1]
    assert calls[1]["args"][0][2:] == ["build"]
    assert all("npm" not in str(call["args"][0]).lower() for call in calls)
    for call in calls:
        kwargs = call["kwargs"]
        startupinfo = kwargs["startupinfo"]
        assert kwargs["creationflags"] & 0x00000008
        assert kwargs["creationflags"] & 0x00000200
        assert kwargs["creationflags"] & 0x08000000
        assert isinstance(startupinfo, DummyStartupInfo)
        assert startupinfo.dwFlags & 0x00000001
        assert startupinfo.wShowWindow == 0
    assert result["ok"] is True
    assert result["completedSteps"] == ["tsc -b", "vite build"]
    assert events[-1][0] == "workbench.restart.build_preflight_succeeded"


def test_runtime_manager_run_forever_requeues_deferred_restart(monkeypatch, tmp_path):
    class StopLoop(Exception):
        pass

    runtime_daemon = daemon.RuntimeManagerDaemon()
    command_path = tmp_path / "cmd-restart.json"
    command_payload = {
        "commandId": "cmd-restart",
        "type": "restart_workbench",
        "requestedBy": "web_ui",
        "args": {"deferredUntilActiveWorkClear": True},
    }
    defer_calls: list[dict[str, object]] = []
    completed: list[dict[str, object]] = []
    saved_states: list[dict[str, object]] = []

    monkeypatch.setattr(daemon, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(daemon, "save_pid", lambda pid: None)
    monkeypatch.setattr(daemon, "clear_pid", lambda pid: None)
    monkeypatch.setattr(daemon, "_mark_daemon_not_running_after_exit", lambda manager_pid: None)
    monkeypatch.setattr(daemon, "load_state", lambda: {"stateVersion": 1, "command": {}})
    monkeypatch.setattr(daemon, "save_state", lambda state: saved_states.append(dict(state)) or state)
    monkeypatch.setattr(daemon, "recover_processing_queue", lambda: None)
    monkeypatch.setattr(type(runtime_daemon), "_reconcile_observation", lambda self, state: state)
    monkeypatch.setattr(daemon, "claim_next_command", lambda: (command_path, command_payload))
    monkeypatch.setattr(
        type(runtime_daemon),
        "_handle_command",
        lambda self, payload: {
            "commandId": "cmd-restart",
            "deferCommandUntilActiveWorkClear": True,
            "activeWorkRuns": [{"kind": "chat_turn", "runId": "turn-live"}],
        },
    )
    monkeypatch.setattr(
        daemon,
        "defer_processing_command_for_active_work",
        lambda path, command, *, active_work_runs, delay_seconds: defer_calls.append(
            {
                "path": path,
                "commandId": command["commandId"],
                "activeWorkRuns": active_work_runs,
                "delaySeconds": delay_seconds,
            }
        ),
    )
    monkeypatch.setattr(type(runtime_daemon), "_clear_active_command", lambda self: (_ for _ in ()).throw(StopLoop()))
    monkeypatch.setattr(daemon, "complete_command", lambda path, result: completed.append(result))

    with pytest.raises(StopLoop):
        runtime_daemon.run_forever()

    assert defer_calls == [
        {
            "path": command_path,
            "commandId": "cmd-restart",
            "activeWorkRuns": [{"kind": "chat_turn", "runId": "turn-live"}],
            "delaySeconds": daemon._DEFERRED_RESTART_ACTIVE_WORK_POLL_SECONDS,
        }
    ]
    assert completed == []
    assert saved_states[0]["runtimeState"] == "running"


def test_hot_restart_allows_only_requester_active_chat_turn(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {"activeCommandId": "cmd-hot", "activeType": "hot_restart_workbench"},
        "workbench": {
            "desiredState": "open",
            "observedState": "open",
            "phase": "steady",
        },
    }
    events: list[tuple[str, dict]] = []

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(daemon, "observe_workbench", lambda: {"observedState": "open"})
    monkeypatch.setattr(
        daemon,
        "_runtime_manager_active_work_runs",
        lambda: [{"kind": "chat_turn", "runId": "turn-live", "status": "running", "sessionId": "session-a"}],
    )
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))
    monkeypatch.setattr(daemon, "latest_stable_backup", lambda: {"backupId": "stable-1", "archivePath": "snapshot.zip"})
    monkeypatch.setattr(
        runtime_daemon,
        "_perform_restart_workbench",
        lambda command_id, args: {"residualCleanup": {}, "requestedNoBrowser": False, "effectiveNoBrowser": False},
    )
    monkeypatch.setattr(daemon, "create_stable_backup", lambda **_kwargs: {"backupId": "stable-2"})
    monkeypatch.setattr(
        runtime_daemon,
        "_wake_hot_restart_session",
        lambda **_kwargs: {"wakeStatus": "delivered", "turnId": "turn-resume"},
    )

    result = runtime_daemon._handle_hot_restart_workbench(
        command_id="cmd-hot",
        args={
            "reason": "code_update",
            "allowActiveSessionId": "session-a",
            "allowActiveRunId": "turn-live",
            "hotRestart": {"sessionId": "session-a", "runId": "turn-live"},
        },
    )

    assert result["ok"] is True
    assert result["hotRestart"]["status"] == "completed"
    assert events[0][0] == "workbench.hot_restart.allowed_requester_active_work"


def test_hot_restart_blocks_other_active_work(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {"activeCommandId": "cmd-hot", "activeType": "hot_restart_workbench"},
        "workbench": {
            "desiredState": "open",
            "observedState": "open",
            "phase": "steady",
        },
    }
    events: list[tuple[str, dict]] = []

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(daemon, "observe_workbench", lambda: {"observedState": "open"})
    monkeypatch.setattr(
        daemon,
        "_runtime_manager_active_work_runs",
        lambda: [
            {"kind": "chat_turn", "runId": "turn-live", "status": "running", "sessionId": "session-a"},
            {"kind": "chat_turn", "runId": "turn-other", "status": "running", "sessionId": "session-b"},
        ],
    )
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))

    result = runtime_daemon._handle_hot_restart_workbench(
        command_id="cmd-hot",
        args={
            "reason": "code_update",
            "allowActiveSessionId": "session-a",
            "allowActiveRunId": "turn-live",
            "hotRestart": {"sessionId": "session-a", "runId": "turn-live"},
        },
    )

    assert result["ok"] is False
    assert result["errorType"] == "ActiveWorkBlocked"
    assert result["activeWorkRuns"]["count"] == 1
    assert result["activeWorkRuns"]["items"][0]["sessionId"] == "session-b"
    assert result["activeWorkRuns"]["allowedItems"][0]["sessionId"] == "session-a"
    assert events[0][0] == "workbench.hot_restart.blocked_active_work"


def test_handle_restart_workbench_stops_after_close_when_close_interrupt_is_pending(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {"activeCommandId": "cmd-restart", "activeType": "restart_workbench"},
        "workbench": {
            "desiredState": "open",
            "observedState": "open",
            "phase": "steady",
        },
    }
    interrupt = {
        "interruptedCommandId": "cmd-restart",
        "interruptedType": "restart_workbench",
        "closeCommandId": "cmd-close",
        "closeCommandType": "close_workbench",
        "operation": "close",
    }
    events: list[tuple[str, dict]] = []
    close_calls: list[str] = []
    cleared: list[str] = []

    monkeypatch.setattr(daemon, "load_state", lambda: json.loads(json.dumps(state)))
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(daemon, "now_iso", lambda: "2026-06-12T09:45:00+00:00")
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(daemon, "_restart_should_preflight_frontend_build", lambda workbench, args: False)
    monkeypatch.setattr(daemon, "observe_workbench", lambda: {"observedState": "closed"})
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))
    monkeypatch.setattr(daemon, "lifecycle_interrupt_requested", lambda command_id: interrupt if command_id == "cmd-restart" else None)
    monkeypatch.setattr(daemon, "clear_lifecycle_interrupt", lambda command_id: cleared.append(command_id))
    monkeypatch.setattr(
        daemon,
        "close_workbench",
        lambda: close_calls.append("close") or subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )
    monkeypatch.setattr(daemon, "_wait_for_close_verification", lambda: (True, {"observedState": "closed"}, 1))
    monkeypatch.setattr(daemon.RuntimeManagerDaemon, "_cleanup_residual_workbench_processes", lambda self: {"count": 0, "items": []})
    monkeypatch.setattr(
        daemon,
        "open_workbench",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("interrupted restart must not reopen")),
    )

    result = runtime_daemon._handle_restart_workbench(
        command_id="cmd-restart",
        args={"reason": "launcher_restart", "skipActiveWorkGuard": True},
    )

    assert result["ok"] is False
    assert result["errorType"] == "SupersededByCloseWorkbench"
    assert result["interruptedByClose"] is True
    assert result["interruptStage"] == "after_close_before_open"
    assert result["supersededByCommandId"] == "cmd-close"
    assert result["closeStrategy"] == "runtime_manager_fast_path"
    assert close_calls == []
    assert cleared == ["cmd-restart"]
    assert "workbench.restart.interrupted_by_close" in [event_type for event_type, _ in events]


def test_handle_restart_workbench_preserves_visible_browser_when_no_browser_was_forwarded(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {"activeCommandId": "cmd-restart"},
        "workbench": {
            "desiredState": "open",
            "observedState": "open",
            "phase": "steady",
        },
    }
    events: list[tuple[str, dict]] = []
    close_calls: list[str] = []
    open_calls: list[bool] = []

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(daemon, "now_iso", lambda: "2026-05-19T09:00:00+00:00")
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        lambda: {
            "observedState": "open",
            "launcherStatePresent": True,
            "browserManaged": True,
            "browserWindowAlive": True,
            "backendPid": 28888,
            "browserLaunchPid": 29999,
            "browserWindowPid": 29999,
            "backendAlive": True,
            "backendHealthy": True,
            "backendObserved": True,
            "backendPortListening": True,
            "backendPortOwnerPid": 28888,
            "sessionId": "managed-session",
            "url": "http://127.0.0.1:8000",
        },
    )
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))
    monkeypatch.setattr(
        daemon,
        "_preflight_frontend_build_for_restart",
        lambda command_id: {"ok": True, "commandId": command_id, "completedSteps": ["mock"]},
    )
    monkeypatch.setattr(
        daemon,
        "close_workbench",
        lambda: close_calls.append("close") or subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )
    monkeypatch.setattr(daemon, "_wait_for_close_verification", lambda: (True, daemon.observe_workbench(), 1))
    monkeypatch.setattr(daemon, "_wait_for_open_verification", lambda *, no_browser, cancel_check=None: (True, daemon.observe_workbench(), 1))
    monkeypatch.setattr(daemon.RuntimeManagerDaemon, "_cleanup_residual_workbench_processes", lambda self: {"count": 0, "items": []})
    monkeypatch.setattr(
        daemon,
        "open_workbench",
        lambda *, no_browser, cancel_check=None: open_calls.append(no_browser)
        or subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )

    result = runtime_daemon._handle_restart_workbench(
        command_id="cmd-restart",
        args={"reason": "launcher_restart", "noBrowser": True},
    )

    assert result["ok"] is True
    assert result["closeStrategy"] == "runtime_manager_fast_path"
    assert close_calls == []
    assert open_calls == [False]
    override_payload = next(payload for event_type, payload in events if event_type == "workbench.restart.no_browser_overridden")
    assert override_payload["browserWindowPid"] == 29999
    assert override_payload["effectiveNoBrowser"] is False
    assert "workbench.restart.close_verification_succeeded" in [event[0] for event in events]
    assert "workbench.restart.open_verification_succeeded" in [event[0] for event in events]


def test_handle_restart_workbench_keeps_headless_restart_headless(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {"activeCommandId": "cmd-restart"},
        "workbench": {
            "desiredState": "open",
            "observedState": "open",
            "phase": "steady",
        },
    }
    close_calls: list[str] = []
    open_calls: list[bool] = []

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(daemon, "now_iso", lambda: "2026-05-19T09:00:00+00:00")
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        lambda: {
            "observedState": "open",
            "launcherStatePresent": True,
            "browserManaged": False,
            "browserWindowAlive": False,
            "backendPid": 28888,
            "browserLaunchPid": 0,
            "browserWindowPid": 0,
            "backendAlive": True,
            "backendHealthy": True,
            "backendObserved": True,
            "backendPortListening": True,
            "backendPortOwnerPid": 28888,
            "sessionId": "headless-session",
            "url": "http://127.0.0.1:8000",
        },
    )
    monkeypatch.setattr(daemon, "_append_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        daemon,
        "close_workbench",
        lambda: close_calls.append("close") or subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )
    monkeypatch.setattr(daemon, "_wait_for_close_verification", lambda: (True, daemon.observe_workbench(), 1))
    monkeypatch.setattr(daemon, "_wait_for_open_verification", lambda *, no_browser, cancel_check=None: (True, daemon.observe_workbench(), 1))
    monkeypatch.setattr(daemon.RuntimeManagerDaemon, "_cleanup_residual_workbench_processes", lambda self: {"count": 0, "items": []})
    monkeypatch.setattr(
        daemon,
        "open_workbench",
        lambda *, no_browser, cancel_check=None: open_calls.append(no_browser)
        or subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )

    result = runtime_daemon._handle_restart_workbench(
        command_id="cmd-restart",
        args={"reason": "launcher_restart", "noBrowser": True},
    )

    assert result["ok"] is True
    assert result["closeStrategy"] == "runtime_manager_fast_path"
    assert close_calls == []
    assert open_calls == [True]


def test_handle_restart_workbench_accepts_trusted_backend_when_health_probe_lags(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {"activeCommandId": "cmd-restart"},
        "workbench": {
            "desiredState": "open",
            "observedState": "open",
            "phase": "steady",
        },
    }
    events: list[tuple[str, dict]] = []
    open_observation = {
        "observedState": "open",
        "launcherStatePresent": True,
        "browserManaged": True,
        "browserWindowAlive": True,
        "backendPid": 31216,
        "browserLaunchPid": 36760,
        "browserWindowPid": 36760,
        "backendAlive": True,
        "backendHealthy": False,
        "backendObserved": True,
        "backendPort": 8000,
        "backendPortListening": True,
        "backendPortOwnerPid": 31216,
        "backendPortOwnerTrusted": True,
        "backendPortConflict": False,
        "backendPortOwnerKind": "managed_workbench_backend",
        "sessionId": "fresh-session",
        "url": "http://127.0.0.1:8000",
        "healthUrl": "http://127.0.0.1:8000/api/health",
    }
    closed_observation = {
        "observedState": "closed",
        "launcherStatePresent": False,
        "browserManaged": True,
        "browserWindowAlive": False,
        "backendPid": 0,
        "browserLaunchPid": 0,
        "browserWindowPid": 0,
        "backendAlive": False,
        "backendHealthy": False,
        "backendObserved": False,
        "backendPort": 8000,
        "backendPortListening": False,
        "backendPortOwnerPid": 0,
        "backendPortOwnerTrusted": False,
        "backendPortConflict": False,
        "sessionId": "",
        "url": "http://127.0.0.1:8000",
    }
    observations = _repeat_last([open_observation, closed_observation, open_observation])

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(daemon, "now_iso", lambda: "2026-06-04T15:29:00+00:00")
    monkeypatch.setattr(daemon, "observe_workbench", observations)
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))
    monkeypatch.setattr(
        daemon,
        "_preflight_frontend_build_for_restart",
        lambda command_id: {"ok": True, "commandId": command_id, "completedSteps": ["mock"]},
    )
    monkeypatch.setattr(daemon.RuntimeManagerDaemon, "_cleanup_residual_workbench_processes", lambda self: {"count": 0, "items": []})
    monkeypatch.setattr(
        daemon,
        "close_workbench",
        lambda: subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )
    monkeypatch.setattr(daemon, "_wait_for_close_verification", lambda: (True, closed_observation, 1))
    monkeypatch.setattr(
        daemon,
        "open_workbench",
        lambda *, no_browser, cancel_check=None: subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )

    result = runtime_daemon._handle_restart_workbench(command_id="cmd-restart", args={"reason": "launcher_restart"})

    assert result["ok"] is True
    success_payload = next(payload for event_type, payload in events if event_type == "workbench.restart.open_verification_succeeded")
    assert success_payload["backendHealthy"] is False
    assert success_payload["backendReady"] is True
    assert success_payload["backendReadySource"] == "launcher_confirmed_port"


def test_handle_close_workbench_records_shutdown_source(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    saved_states: list[dict] = []
    state = {
        "command": {"activeCommandId": "cmd-close"},
        "workbench": {
            "desiredState": "open",
            "observedState": "open",
            "phase": "steady",
        },
    }

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: saved_states.append(json.loads(json.dumps(next_state))) or next_state)
    monkeypatch.setattr(daemon, "now_iso", lambda: "2026-05-19T09:00:00+00:00")
    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        _repeat_last(
            [
                {
                    "observedState": "open",
                    "launcherStatePresent": True,
                    "browserManaged": True,
                    "browserWindowAlive": True,
                    "backendPid": 28888,
                    "browserLaunchPid": 29999,
                    "browserWindowPid": 29999,
                    "backendAlive": True,
                    "backendHealthy": True,
                    "backendObserved": True,
                    "backendPortListening": True,
                    "backendPortOwnerPid": 28888,
                    "sessionId": "managed-session",
                    "url": "http://127.0.0.1:8000",
                },
                {
                    "observedState": "closed",
                    "launcherStatePresent": False,
                    "browserManaged": True,
                    "browserWindowAlive": False,
                    "backendPid": 0,
                    "browserLaunchPid": 0,
                    "browserWindowPid": 0,
                    "backendAlive": False,
                    "backendHealthy": False,
                    "backendObserved": False,
                    "backendPortListening": False,
                    "backendPortOwnerPid": 0,
                    "sessionId": "",
                    "url": "http://127.0.0.1:8000",
                },
            ]
        ),
    )
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(
        daemon,
        "close_workbench",
        lambda: subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )
    closed_calls = []
    monkeypatch.setattr(
        daemon,
        "_close_active_evolution_runs_for_shutdown",
        lambda: closed_calls.append("closed") or [],
    )

    result = runtime_daemon._handle_close_workbench(
        command_id="cmd-close",
        args={"reason": "web_close_button", "source": "web_ui"},
    )

    assert result["ok"] is True
    assert closed_calls == ["closed"]
    assert saved_states[0]["workbench"]["lastReason"] == "web_close_button"
    assert saved_states[0]["workbench"]["lastSource"] == "web_ui"


def test_handle_close_workbench_uses_runtime_manager_fast_path(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {"activeCommandId": "cmd-close"},
        "workbench": {
            "desiredState": "open",
            "observedState": "open",
            "phase": "steady",
        },
    }
    events: list[tuple[str, dict]] = []
    cleanup_calls: list[dict] = []
    state_cleanup_calls: list[str] = []
    open_observation = {
        "observedState": "open",
        "launcherStatePresent": True,
        "browserManaged": True,
        "browserWindowAlive": True,
        "backendPid": 28888,
        "backendLaunchPid": 28888,
        "backendAlive": True,
        "backendHealthy": True,
        "backendObserved": True,
        "backendPort": 8000,
        "backendPortListening": True,
        "backendPortOwnerPid": 28888,
        "backendPortOwnerTrusted": True,
        "backendPortConflict": False,
        "browserProfileDir": "C:/tmp/vibelution-workbench-profile",
        "browserLaunchPid": 29999,
        "browserWindowPid": 29999,
        "sessionId": "managed-session",
        "url": "http://127.0.0.1:8000",
    }
    closed_observation = {
        "observedState": "closed",
        "launcherStatePresent": False,
        "browserManaged": True,
        "browserWindowAlive": False,
        "backendPid": 0,
        "backendLaunchPid": 0,
        "backendAlive": False,
        "backendHealthy": False,
        "backendObserved": False,
        "backendPort": 8000,
        "backendPortListening": False,
        "backendPortOwnerPid": 0,
        "backendPortOwnerTrusted": False,
        "backendPortConflict": False,
        "browserLaunchPid": 0,
        "browserWindowPid": 0,
        "sessionId": "",
        "url": "http://127.0.0.1:8000",
    }

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(daemon, "now_iso", lambda: "2026-06-12T10:40:00+00:00")
    monkeypatch.setattr(daemon, "observe_workbench", lambda: dict(open_observation))
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(daemon, "_runtime_manager_active_work_runs", lambda: [])
    monkeypatch.setattr(daemon, "_close_active_evolution_runs_for_shutdown", lambda: [])
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))
    monkeypatch.setattr(daemon, "_wait_for_close_verification", lambda: (True, dict(closed_observation), 1))
    monkeypatch.setattr(
        daemon,
        "close_workbench",
        lambda: (_ for _ in ()).throw(AssertionError("fast path should not invoke PowerShell launcher close")),
    )
    monkeypatch.setattr(
        daemon,
        "clear_workbench_launcher_state_after_close",
        lambda: state_cleanup_calls.append("state") or {"preservedLauncherControlState": True, "removedState": False},
    )

    def fake_cleanup(self, observation=None):
        cleanup_calls.append(dict(observation or {}))
        return {"supported": True, "requested": [28888, 29999], "terminated": [28888, 29999], "remaining": []}

    monkeypatch.setattr(daemon.RuntimeManagerDaemon, "_force_cleanup_workbench_processes", fake_cleanup)

    result = runtime_daemon._handle_close_workbench(command_id="cmd-close", args={"reason": "web_close_button"})

    assert result["ok"] is True
    assert result["closeStrategy"] == "runtime_manager_fast_path"
    assert result["residualCleanup"]["terminated"] == [28888, 29999]
    assert "launcher_action_ms" not in result["lifecycleTimingsMs"]
    assert result["lifecycleTimingsMs"]["fast_cleanup_ms"] >= 0
    assert cleanup_calls[0]["backendPid"] == 28888
    assert state_cleanup_calls == ["state"]
    assert any(event_type == "workbench.close.fast_path_succeeded" for event_type, _payload in events)
    succeeded = next(payload for event_type, payload in events if event_type == "workbench.close.verification_succeeded")
    assert succeeded["closeStrategy"] == "runtime_manager_fast_path"


def test_handle_close_workbench_uses_light_observation_and_reuses_it(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {"activeCommandId": "cmd-close"},
        "workbench": {
            "desiredState": "open",
            "observedState": "partial",
            "phase": "steady",
        },
    }
    open_observation = {
        "observedState": "partial",
        "launcherStatePresent": True,
        "browserManaged": True,
        "browserWindowAlive": False,
        "backendPid": 28888,
        "backendLaunchPid": 28888,
        "backendAlive": True,
        "backendHealthy": True,
        "backendObserved": True,
        "backendPort": 8000,
        "backendPortListening": True,
        "backendPortOwnerPid": 28888,
        "backendPortOwnerTrusted": True,
        "backendPortConflict": False,
        "browserProfileDir": "C:/tmp/vibelution-workbench-profile",
        "browserLaunchPid": 29999,
        "browserWindowPid": 29999,
        "sessionId": "managed-session",
        "url": "http://127.0.0.1:8000",
        "lifecycleConsistency": "browser_missing",
    }
    observation_calls: list[dict] = []

    def fake_observe_workbench(**kwargs):
        observation_calls.append(dict(kwargs))
        return dict(open_observation)

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(daemon, "now_iso", lambda: "2026-06-12T10:40:00+00:00")
    monkeypatch.setattr(daemon, "observe_workbench", fake_observe_workbench)
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(daemon, "_runtime_manager_active_work_runs", lambda: [])
    monkeypatch.setattr(daemon, "_close_active_evolution_runs_for_shutdown", lambda: [])
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: None)
    monkeypatch.setattr(daemon, "residual_process_payload", lambda **kwargs: {"count": 0, "items": []})
    monkeypatch.setattr(daemon, "_backend_port_is_closed_for_fast_close", lambda port: True)
    monkeypatch.setattr(
        daemon,
        "clear_workbench_launcher_state_after_close",
        lambda: {"preservedLauncherControlState": True, "removedState": False},
    )
    monkeypatch.setattr(
        daemon.RuntimeManagerDaemon,
        "_force_cleanup_workbench_processes",
        lambda self, observation=None: {
            "supported": True,
            "requested": [28888],
            "terminated": [28888],
            "remaining": [],
        },
    )

    result = runtime_daemon._handle_close_workbench(command_id="cmd-close", args={"reason": "web_close_button"})

    assert result["ok"] is True
    assert result["closeStrategy"] == "runtime_manager_fast_path"
    assert observation_calls == [{"recover_browser_window_for_backend_observed": False}]


def test_handle_close_workbench_falls_back_to_launcher_when_fast_path_is_unavailable(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {"activeCommandId": "cmd-close"},
        "workbench": {
            "desiredState": "open",
            "observedState": "open",
            "phase": "steady",
        },
    }
    close_calls: list[str] = []
    open_observation = {
        "observedState": "open",
        "launcherStatePresent": True,
        "browserManaged": True,
        "browserWindowAlive": True,
        "backendPid": 28888,
        "backendAlive": True,
        "backendHealthy": True,
        "backendObserved": True,
        "backendPort": 8000,
        "backendPortListening": True,
        "backendPortOwnerPid": 28888,
        "browserWindowPid": 29999,
        "sessionId": "managed-session",
        "url": "http://127.0.0.1:8000",
    }
    closed_observation = {
        "observedState": "closed",
        "launcherStatePresent": False,
        "browserManaged": True,
        "browserWindowAlive": False,
        "backendPid": 0,
        "backendAlive": False,
        "backendHealthy": False,
        "backendObserved": False,
        "backendPort": 8000,
        "backendPortListening": False,
        "backendPortOwnerPid": 0,
        "browserWindowPid": 0,
        "sessionId": "",
        "url": "http://127.0.0.1:8000",
    }

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(daemon, "observe_workbench", lambda: dict(open_observation))
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(daemon, "_runtime_manager_active_work_runs", lambda: [])
    monkeypatch.setattr(daemon, "_close_active_evolution_runs_for_shutdown", lambda: [])
    monkeypatch.setattr(daemon, "_wait_for_close_verification", lambda: (True, dict(closed_observation), 1))
    monkeypatch.setattr(
        daemon.RuntimeManagerDaemon,
        "_force_cleanup_workbench_processes",
        lambda self, observation=None: {"supported": False, "requested": [], "terminated": [], "remaining": []},
    )
    monkeypatch.setattr(
        daemon,
        "close_workbench",
        lambda: close_calls.append("launcher") or subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )

    result = runtime_daemon._handle_close_workbench(command_id="cmd-close", args={})

    assert result["ok"] is True
    assert result["closeStrategy"] == "launcher_internal_stop"
    assert result["lifecycleTimingsMs"]["launcher_action_ms"] >= 0
    assert result["lifecycleTimingsMs"]["fast_close_path_ms"] >= 0
    assert result["lifecycleTimingsMs"]["close_verification_attempts"] == 1
    assert close_calls == ["launcher"]


def test_clear_workbench_launcher_state_after_fast_close_preserves_launcher_control(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "sessionRole": "workbench",
                "sessionId": "session-workbench",
                "backendPid": 5000,
                "backendLaunchPid": 5001,
                "launcherBackendPid": 4100,
                "launcherBackendLaunchPid": 4101,
                "launcherControlPort": 8765,
                "launcherControlUrl": "http://127.0.0.1:8765/launcher",
                "browserManaged": True,
                "browserProfileDir": "workbench-profile",
                "workbenchBrowserProfileDir": "workbench-profile",
                "launcherBrowserProfileDir": "launcher-profile",
                "browserLaunchPid": 5200,
                "browserWindowPid": 5200,
                "workbenchBrowserLaunchPid": 5200,
                "workbenchBrowserWindowPid": 5200,
                "launcherBrowserLaunchPid": 4200,
                "launcherBrowserWindowPid": 4200,
                "supervisorPid": 5300,
                "runtimeSceneId": "scene-workbench",
                "runtimeSceneDir": "logs/runtime_scenes/scene-workbench",
                "launcherControlStartedAt": "2026-06-12T10:30:00+00:00",
                "startedAt": "2026-06-12T10:31:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(workbench_controller, "LAUNCHER_STATE_PATH", state_path)
    monkeypatch.setattr(workbench_controller, "_is_process_alive", lambda pid: int(pid) in {4100, 4200})

    result = workbench_controller.clear_workbench_launcher_state_after_close()
    saved = json.loads(state_path.read_text(encoding="utf-8"))

    assert result["preservedLauncherControlState"] is True
    assert result["removedState"] is False
    assert saved["sessionRole"] == "launcher_control_surface"
    assert saved["backendPid"] == 0
    assert saved["backendLaunchPid"] == 0
    assert saved["browserProfileDir"] == "launcher-profile"
    assert saved["browserLaunchPid"] == 4200
    assert saved["browserWindowPid"] == 4200
    assert saved["workbenchBrowserLaunchPid"] == 0
    assert saved["workbenchBrowserWindowPid"] == 0
    assert saved["supervisorPid"] == 0
    assert saved["runtimeSceneId"] is None
    assert saved["runtimeSceneDir"] is None
    assert saved["startedAt"] == "2026-06-12T10:30:00+00:00"


def test_handle_force_close_workbench_marks_work_runs_and_verifies_close(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    saved_states: list[dict] = []
    events: list[tuple[str, dict]] = []
    cleanup_calls: list[dict] = []
    state_holder = {
        "value": {
            "command": {"activeCommandId": "cmd-force"},
            "workbench": {
                "desiredState": "open",
                "observedState": "open",
                "phase": "steady",
            },
        },
    }
    open_observation = {
        "observedState": "open",
        "launcherStatePresent": True,
        "browserManaged": True,
        "browserWindowAlive": True,
        "backendPid": 28888,
        "browserLaunchPid": 29999,
        "browserWindowPid": 29999,
        "backendAlive": True,
        "backendHealthy": True,
        "backendObserved": True,
        "backendPortListening": True,
        "backendPortOwnerPid": 28888,
        "sessionId": "managed-session",
        "url": "http://127.0.0.1:8000",
        "browserProfileDir": "C:/tmp/vibelution-workbench-profile",
    }
    closed_observation = {
        "observedState": "closed",
        "launcherStatePresent": False,
        "browserManaged": True,
        "browserWindowAlive": False,
        "backendPid": 0,
        "browserLaunchPid": 0,
        "browserWindowPid": 0,
        "backendAlive": False,
        "backendHealthy": False,
        "backendObserved": False,
        "backendPortListening": False,
        "backendPortOwnerPid": 0,
        "sessionId": "",
        "url": "http://127.0.0.1:8000",
        "browserProfileDir": "C:/tmp/vibelution-workbench-profile",
    }

    monkeypatch.setattr(daemon, "load_state", lambda: json.loads(json.dumps(state_holder["value"])))

    def fake_save_state(next_state):
        persisted = json.loads(json.dumps(next_state))
        state_holder["value"] = persisted
        saved_states.append(persisted)
        return persisted

    monkeypatch.setattr(daemon, "save_state", fake_save_state)
    monkeypatch.setattr(daemon, "now_iso", lambda: "2026-06-09T08:00:00+00:00")
    monkeypatch.setattr(daemon, "observe_workbench", _repeat_last([open_observation, closed_observation, closed_observation]))
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(
        daemon,
        "_runtime_manager_active_work_runs",
        lambda: (_ for _ in ()).throw(AssertionError("force close must not use regular active-work block")),
    )
    monkeypatch.setattr(
        daemon,
        "_persistent_active_work_run_snapshots",
        lambda: [{"runKind": "chat_turn", "runId": "chat-live", "status": "running", "sessionId": "session-live"}],
    )
    monkeypatch.setattr(
        daemon,
        "_mark_persistent_active_work_runs_force_stopped",
        lambda reason: [{"kind": "chat_turn", "runId": "chat-live", "status": "stopped_by_user", "reason": reason}],
    )
    monkeypatch.setattr(
        daemon,
        "_close_active_evolution_runs_for_shutdown",
        lambda: [{"kind": "self_evolution_run", "runId": "self-live", "status": "cancelled"}],
    )
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))
    monkeypatch.setattr(
        daemon,
        "_wait_for_close_verification",
        lambda: (True, dict(closed_observation), 1),
    )

    def fake_cleanup(self, observation=None):
        cleanup_calls.append(dict(observation or {}))
        return {"supported": True, "requested": [28888, 29999], "terminated": [28888, 29999], "remaining": []}

    monkeypatch.setattr(daemon.RuntimeManagerDaemon, "_force_cleanup_workbench_processes", fake_cleanup)

    result = runtime_daemon._handle_force_close_workbench(
        command_id="cmd-force",
        args={"reason": "launcher_force_stop_button", "source": "launcher_api"},
    )

    assert result["ok"] is True
    assert result["message"] == "Workbench force closed."
    assert result["residualCleanup"]["terminated"] == [28888, 29999]
    assert result["closedEvolutionRuns"] == [{"kind": "self_evolution_run", "runId": "self-live", "status": "cancelled"}]
    assert result["forceStoppedWorkRuns"] == [
        {"kind": "chat_turn", "runId": "chat-live", "status": "stopped_by_user", "reason": "launcher_force_stop_button"}
    ]
    assert cleanup_calls[0]["browserWindowPid"] == 29999
    assert saved_states[0]["workbench"]["desiredState"] == "closed"
    assert saved_states[0]["workbench"]["phase"] == "force_stopping"
    assert saved_states[0]["workbench"]["lastReason"] == "launcher_force_stop_button"
    assert saved_states[0]["workbench"]["lastSource"] == "launcher_api"
    assert saved_states[-1]["workbench"]["desiredState"] == "closed"
    assert saved_states[-1]["workbench"]["phase"] == "steady"
    requested_event = next(payload for event_type, payload in events if event_type == "workbench.force_close.requested")
    succeeded_event = next(payload for event_type, payload in events if event_type == "workbench.force_close.verification_succeeded")
    assert requested_event["activeWorkCount"] == 1
    assert succeeded_event["attempts"] == 1


def test_force_close_marks_parallel_persistent_work_runs(tmp_path, monkeypatch):
    work_runs_dir = tmp_path / ".runtime" / "runtime-manager" / "work_runs"
    stale_at = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    store = WorkRunStore(root=work_runs_dir)
    store.persist_snapshot(
        "chat_turn",
        {
            "runId": "chat-alpha",
            "runKind": "chat_turn",
            "sessionId": "session-alpha",
            "status": "running",
            "updatedAt": stale_at,
        },
        active_run_id="chat-alpha",
    )
    store.persist_snapshot(
        "chat_turn",
        {
            "runId": "chat-beta",
            "runKind": "chat_turn",
            "sessionId": "session-beta",
            "status": "queued",
        },
        active_run_id="chat-alpha",
    )
    store.persist_snapshot(
        "chat_turn",
        {
            "runId": "chat-stale",
            "runKind": "chat_turn",
            "sessionId": "session-stale",
            "status": "running",
            "updatedAt": stale_at,
        },
        active_run_id="chat-alpha",
    )
    store.persist_snapshot(
        "chat_turn",
        {
            "runId": "chat-routed",
            "runKind": "chat_turn",
            "sessionId": "session-routed",
            "status": "routed",
        },
        active_run_id="chat-alpha",
    )
    store.persist_snapshot(
        "chat_turn",
        {
            "runId": "chat-partial",
            "runKind": "chat_turn",
            "sessionId": "session-partial",
            "status": "partial",
        },
        active_run_id="chat-alpha",
    )
    store.persist_snapshot(
        "chat_turn",
        {
            "runId": "chat-done",
            "runKind": "chat_turn",
            "sessionId": "session-done",
            "status": "completed",
            "finishedAt": "2026-06-09T08:00:00+00:00",
        },
        active_run_id="chat-alpha",
    )
    monkeypatch.setattr(work_run_store, "WORK_RUNS_DIR", work_runs_dir)

    stopped = daemon._mark_persistent_active_work_runs_force_stopped("launcher_force_stop_button")

    assert {item["runId"] for item in stopped} == {"chat-alpha", "chat-beta"}
    alpha = store.load_snapshot("chat_turn", "chat-alpha")
    beta = store.load_snapshot("chat_turn", "chat-beta")
    stale = store.load_snapshot("chat_turn", "chat-stale")
    routed = store.load_snapshot("chat_turn", "chat-routed")
    partial = store.load_snapshot("chat_turn", "chat-partial")
    done = store.load_snapshot("chat_turn", "chat-done")
    assert alpha and alpha["status"] == "stopped_by_user"
    assert beta and beta["status"] == "stopped_by_user"
    assert alpha["runtimeStatus"] == "force_stopped"
    assert beta["forceStopReason"] == "launcher_force_stop_button"
    assert stale and stale["status"] == "running"
    assert routed and routed["status"] == "routed"
    assert partial and partial["status"] == "partial"
    assert done and done["status"] == "completed"
    assert store.load_run_index("chat_turn")["activeRunId"] == ""


def test_handle_close_workbench_blocks_active_chat_turn_before_close(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {"activeCommandId": "cmd-close"},
        "workbench": {
            "desiredState": "open",
            "observedState": "open",
            "phase": "steady",
        },
    }
    events: list[tuple[str, dict]] = []
    close_calls: list[str] = []

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(daemon, "observe_workbench", lambda: {"observedState": "open"})
    monkeypatch.setattr(
        daemon,
        "_runtime_manager_active_work_runs",
        lambda: [{"kind": "chat_turn", "runId": "chat-live", "status": "running", "sessionId": "session-a"}],
    )
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))
    monkeypatch.setattr(
        daemon,
        "close_workbench",
        lambda: close_calls.append("close") or subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )

    result = runtime_daemon._handle_close_workbench(
        command_id="cmd-close",
        args={"reason": "launcher_stop", "source": "launcher_ps", "stopManager": True},
    )

    assert result["ok"] is False
    assert result["errorType"] == "ActiveWorkBlocked"
    assert result["message"] == "有进行中的任务，无法重启 Vibelution。请等待任务完成或先停止任务。"
    assert result["activeWorkRuns"]["items"][0]["runId"] == "chat-live"
    assert close_calls == []
    assert events[0][0] == "workbench.close.blocked_active_work"
    assert events[0][1]["activeWorkCount"] == 1
    assert state["lastError"]["scope"] == "active_work"
    assert state["workbench"]["phase"] != "failed"


def test_handle_toggle_workbench_blocks_active_chat_turn_when_open(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {"activeCommandId": "cmd-toggle"},
        "workbench": {
            "desiredState": "open",
            "observedState": "open",
            "phase": "steady",
        },
    }
    events: list[tuple[str, dict]] = []
    close_calls: list[str] = []

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(daemon, "observe_workbench", lambda: {"observedState": "open"})
    monkeypatch.setattr(
        daemon,
        "_runtime_manager_active_work_runs",
        lambda: [{"kind": "chat_turn", "runId": "chat-live", "status": "running", "sessionId": "session-a"}],
    )
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))
    monkeypatch.setattr(
        daemon,
        "close_workbench",
        lambda: close_calls.append("close") or subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )

    result = runtime_daemon._handle_toggle_workbench(command_id="cmd-toggle", args={"reason": "launcher_toggle"})

    assert result["ok"] is False
    assert result["errorType"] == "ActiveWorkBlocked"
    assert close_calls == []
    assert events[0][0] == "workbench.toggle.blocked_active_work"


def test_handle_close_workbench_closes_active_evolution_runs(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {"activeCommandId": "cmd-close"},
        "workbench": {
            "desiredState": "open",
            "observedState": "open",
            "phase": "steady",
        },
    }

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(daemon, "now_iso", lambda: "2026-05-19T09:00:00+00:00")
    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        _repeat_last(
            [
                {
                    "observedState": "open",
                    "launcherStatePresent": True,
                    "browserManaged": True,
                    "browserWindowAlive": True,
                    "backendPid": 28888,
                    "browserLaunchPid": 29999,
                    "browserWindowPid": 29999,
                    "backendAlive": True,
                    "backendHealthy": True,
                    "backendObserved": True,
                    "backendPortListening": True,
                    "backendPortOwnerPid": 28888,
                    "sessionId": "managed-session",
                    "url": "http://127.0.0.1:8000",
                },
                {
                    "observedState": "closed",
                    "launcherStatePresent": False,
                    "browserManaged": True,
                    "browserWindowAlive": False,
                    "backendPid": 0,
                    "browserLaunchPid": 0,
                    "browserWindowPid": 0,
                    "backendAlive": False,
                    "backendHealthy": False,
                    "backendObserved": False,
                    "backendPortListening": False,
                    "backendPortOwnerPid": 0,
                    "sessionId": "",
                    "url": "http://127.0.0.1:8000",
                },
            ]
        ),
    )
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(
        daemon,
        "close_workbench",
        lambda: subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )
    monkeypatch.setattr(
        daemon,
        "_close_active_evolution_runs_for_shutdown",
        lambda: [
            {"kind": "self_evolution_run", "runId": "web-self-active", "status": "cancelled"},
            {"kind": "supervised_evolution_run", "runId": "web-supervised-active", "status": "cancelled"},
        ],
    )

    result = runtime_daemon._handle_close_workbench(command_id="cmd-close", args={"stopManager": True})

    assert result["ok"] is True
    assert result["closedEvolutionRuns"] == [
        {"kind": "self_evolution_run", "runId": "web-self-active", "status": "cancelled"},
        {"kind": "supervised_evolution_run", "runId": "web-supervised-active", "status": "cancelled"},
    ]
    assert result["stopDaemon"] is True


def test_handle_close_workbench_claims_deferred_reopen_intent(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {"activeCommandId": "cmd-close"},
        "workbench": {
            "desiredState": "open",
            "observedState": "open",
            "phase": "steady",
        },
    }
    events: list[tuple[str, dict]] = []
    intent = {
        "intentId": "intent-reopen",
        "target": "workbench",
        "reason": "launcher_start",
        "requestedBy": "launcher_ps",
        "sourceCommandId": "cmd-open",
        "payload": {"action": "reopen_after_close", "noBrowser": True},
    }

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(daemon, "now_iso", lambda: "2026-05-19T09:00:00+00:00")
    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        _repeat_last(
            [
                {
                    "observedState": "open",
                    "launcherStatePresent": True,
                    "browserManaged": True,
                    "browserWindowAlive": True,
                    "backendPid": 28888,
                    "browserLaunchPid": 29999,
                    "browserWindowPid": 29999,
                    "backendAlive": True,
                    "backendHealthy": True,
                    "backendObserved": True,
                    "backendPortListening": True,
                    "backendPortOwnerPid": 28888,
                    "sessionId": "managed-session",
                    "url": "http://127.0.0.1:8000",
                },
                {
                    "observedState": "closed",
                    "launcherStatePresent": False,
                    "browserManaged": True,
                    "browserWindowAlive": False,
                    "backendPid": 0,
                    "browserLaunchPid": 0,
                    "browserWindowPid": 0,
                    "backendAlive": False,
                    "backendHealthy": False,
                    "backendObserved": False,
                    "backendPortListening": False,
                    "backendPortOwnerPid": 0,
                    "sessionId": "",
                    "url": "http://127.0.0.1:8000",
                },
            ]
        ),
    )
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(
        daemon,
        "close_workbench",
        lambda: subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )
    monkeypatch.setattr(daemon, "_close_active_evolution_runs_for_shutdown", lambda: [])
    monkeypatch.setattr(daemon, "_claim_workbench_reopen_intent", lambda: intent)
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))

    result = runtime_daemon._handle_close_workbench(command_id="cmd-close", args={"stopManager": True})

    assert result["ok"] is True
    assert result["stopDaemon"] is False
    assert result["runDeferredWorkbenchOpen"] is True
    assert result["restartIntent"]["intentId"] == "intent-reopen"
    assert ("workbench.reopen_after_close.claimed", daemon._workbench_reopen_intent_event_payload(intent, command_id="cmd-close")) in events


def test_handle_restart_self_evolution_run_creates_restart_intent(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {"activeCommandId": "cmd-restart"},
        "workbench": {
            "desiredState": "open",
            "observedState": "open",
            "phase": "steady",
        },
    }

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        lambda: {
            "observedState": "open",
            "backendPid": 28888,
            "backendAlive": True,
            "backendHealthy": True,
            "backendObserved": True,
            "backendPortListening": True,
            "backendPortOwnerPid": 28888,
            "browserManaged": True,
            "browserWindowAlive": True,
            "browserWindowPid": 29999,
        },
    )
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(
        daemon.self_evolution_control_service,
        "_LOCAL_REQUEST_SELF_EVOLUTION_RESTART",
        lambda run_id="", reason="": {
            "intentId": "intent-self",
            "target": "self_evolution_run",
            "reason": reason,
            "snapshot": {"runId": run_id, "status": "running"},
        },
    )

    result = runtime_daemon._handle_restart_self_evolution_run(
        command_id="cmd-restart",
        args={"runId": "web-self-123", "payload": {"reason": "code_update"}},
    )

    assert result["ok"] is True
    assert result["runId"] == "web-self-123"
    assert result["restartIntent"]["intentId"] == "intent-self"
    assert result["restartIntent"]["reason"] == "code_update"


def test_daemon_processes_pending_self_evolution_restart_intent(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    events: list[tuple[str, dict]] = []
    completions: list[tuple[str, str, str]] = []
    intent = {
        "intentId": "intent-self",
        "target": "self_evolution_run",
        "reason": "code_update",
        "payload": {"runId": "web-self-123"},
    }

    monkeypatch.setattr(daemon, "claim_next_restart_intent", lambda target="": intent if target == "self_evolution_run" else None)
    monkeypatch.setattr(
        daemon.self_evolution_control_service,
        "_LOCAL_FULFILL_SELF_EVOLUTION_RESTART",
        lambda claimed: {
            "runId": "web-self-123",
            "message": "queued",
            "snapshot": {"runId": "web-self-123", "status": "queued"},
        },
    )
    monkeypatch.setattr(
        daemon,
        "complete_restart_intent",
        lambda intent_id, status="completed", message="": completions.append((intent_id, status, message)) or {},
    )
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))

    runtime_daemon._process_self_evolution_restart_intent()

    assert completions == [("intent-self", "completed", "queued")]
    assert events == [
        (
            "self_evolution.restarted_from_intent",
            {
                "intentId": "intent-self",
                "runId": "web-self-123",
                "status": "queued",
                "reason": "code_update",
            },
        )
    ]


def test_handle_close_workbench_does_not_short_circuit_when_backend_port_is_still_owned(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {"activeCommandId": "cmd-close"},
        "workbench": {
            "desiredState": "closed",
            "observedState": "closed",
            "phase": "steady",
        },
    }
    close_calls = []
    cleanup_calls: list[dict] = []

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(daemon, "now_iso", lambda: "2026-05-19T09:00:00+00:00")
    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        _repeat_last(
            [
                {
                    "observedState": "closed",
                    "launcherStatePresent": True,
                    "browserManaged": True,
                    "browserWindowAlive": False,
                    "backendPid": 19964,
                    "backendAlive": False,
                    "backendHealthy": False,
                    "backendObserved": True,
                    "backendPort": 8766,
                    "backendPortListening": True,
                    "backendPortOwnerPid": 52396,
                    "browserLaunchPid": 5168,
                    "browserWindowPid": 5168,
                    "sessionId": "managed-session",
                    "url": "http://127.0.0.1:8766",
                },
                {
                    "observedState": "closed",
                    "launcherStatePresent": False,
                    "browserManaged": True,
                    "browserWindowAlive": False,
                    "backendPid": 0,
                    "backendAlive": False,
                    "backendHealthy": False,
                    "backendObserved": False,
                    "backendPort": 8766,
                    "backendPortListening": False,
                    "backendPortOwnerPid": 0,
                    "browserLaunchPid": 0,
                    "browserWindowPid": 0,
                    "sessionId": "",
                    "url": "http://127.0.0.1:8766",
                },
            ]
        ),
    )
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})

    def fake_close_workbench():
        close_calls.append("close")
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(daemon, "close_workbench", fake_close_workbench)
    monkeypatch.setattr(
        daemon.RuntimeManagerDaemon,
        "_force_cleanup_workbench_processes",
        lambda self, observation=None: cleanup_calls.append(dict(observation or {}))
        or {"supported": True, "requested": [52396], "terminated": [52396], "remaining": []},
    )

    result = runtime_daemon._handle_close_workbench(command_id="cmd-close", args={})

    assert result["ok"] is True
    assert result["message"] == "Workbench closed."
    assert result["closeStrategy"] == "runtime_manager_fast_path"
    assert cleanup_calls[0]["backendPortOwnerPid"] == 52396
    assert close_calls == []


def test_handle_close_workbench_cleans_residual_processes_and_can_stop_daemon(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {"activeCommandId": "cmd-close"},
        "workbench": {
            "desiredState": "open",
            "observedState": "open",
            "phase": "steady",
        },
    }
    cleanup_calls: list[dict] = []

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(daemon, "now_iso", lambda: "2026-05-19T09:00:00+00:00")
    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        lambda: {
            "observedState": "closed",
            "launcherStatePresent": False,
            "browserManaged": True,
            "browserWindowAlive": False,
            "backendPid": 0,
            "backendAlive": False,
            "backendHealthy": False,
            "backendObserved": False,
            "backendPort": 8766,
            "backendPortListening": False,
            "backendPortOwnerPid": 0,
            "browserLaunchPid": 0,
            "browserWindowPid": 0,
            "sessionId": "",
            "url": "http://127.0.0.1:8766",
        },
    )
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(
        daemon,
        "close_workbench",
        lambda: subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )

    def fake_cleanup(**kwargs):
        cleanup_calls.append(kwargs)
        return {"supported": True, "requested": [49780], "terminated": [49780], "remaining": []}

    monkeypatch.setattr(daemon, "terminate_unmanaged_workbench_processes", fake_cleanup)

    result = runtime_daemon._handle_close_workbench(
        command_id="cmd-close",
        args={"stopManager": True},
    )

    assert result["ok"] is True
    assert result["stopDaemon"] is True
    assert result["residualCleanup"]["terminated"] == [49780]
    assert cleanup_calls
    assert runtime_daemon._pid in cleanup_calls[0]["exclude_pids"]


def test_handle_close_workbench_includes_active_backend_in_residual_cleanup(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {"activeCommandId": "cmd-close"},
        "workbench": {
            "desiredState": "open",
            "observedState": "open",
            "phase": "steady",
        },
    }
    cleanup_calls: list[dict] = []
    observations = _repeat_last(
        [
            {
                "observedState": "open",
                "launcherStatePresent": True,
                "browserManaged": False,
                "browserWindowAlive": False,
                "backendPid": 2748,
                "backendLaunchPid": 2748,
                "backendAlive": True,
                "backendHealthy": True,
                "backendObserved": True,
                "backendPort": 8000,
                "backendPortListening": True,
                "backendPortOwnerPid": 33556,
                "backendPortOwnerTrusted": True,
                "backendPortConflict": False,
                "browserLaunchPid": 0,
                "browserWindowPid": 0,
                "sessionId": "managed-session",
                "url": "http://127.0.0.1:8000",
            },
            {
                "observedState": "closed",
                "launcherStatePresent": False,
                "browserManaged": False,
                "browserWindowAlive": False,
                "backendPid": 0,
                "backendLaunchPid": 0,
                "backendAlive": False,
                "backendHealthy": False,
                "backendObserved": False,
                "backendPort": 8000,
                "backendPortListening": False,
                "backendPortOwnerPid": 0,
                "backendPortOwnerTrusted": False,
                "backendPortConflict": False,
                "browserLaunchPid": 0,
                "browserWindowPid": 0,
                "sessionId": "",
                "url": "http://127.0.0.1:8000",
            },
        ]
    )

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(daemon, "observe_workbench", observations)
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(
        daemon,
        "close_workbench",
        lambda: subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )

    def fake_cleanup(self, observation=None):
        cleanup_calls.append(dict(observation or {}))
        return {"supported": True, "requested": [2748, 33556], "terminated": [2748, 33556], "remaining": []}

    monkeypatch.setattr(daemon.RuntimeManagerDaemon, "_force_cleanup_workbench_processes", fake_cleanup)

    result = runtime_daemon._handle_close_workbench(command_id="cmd-close", args={})

    assert result["ok"] is True
    assert cleanup_calls
    assert cleanup_calls[0]["backendPid"] == 2748
    assert cleanup_calls[0]["backendPortOwnerPid"] == 33556
    assert result["closeStrategy"] == "runtime_manager_fast_path"


def test_handle_close_workbench_fails_when_post_close_verification_still_sees_browser(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {"activeCommandId": "cmd-close"},
        "workbench": {
            "desiredState": "open",
            "observedState": "open",
            "phase": "steady",
        },
    }
    observations = _repeat_last(
        [
            {
                "observedState": "open",
                "launcherStatePresent": True,
                "browserManaged": True,
                "browserWindowAlive": True,
                "backendPid": 6544,
                "backendLaunchPid": 6544,
                "backendAlive": True,
                "backendHealthy": True,
                "backendObserved": True,
                "backendPort": 8000,
                "backendPortListening": True,
                "backendPortOwnerPid": 14916,
                "backendPortOwnerTrusted": True,
                "backendPortConflict": False,
                "browserLaunchPid": 40736,
                "browserWindowPid": 40736,
                "sessionId": "managed-session",
                "url": "http://127.0.0.1:8000",
            },
            {
                "observedState": "open",
                "launcherStatePresent": True,
                "browserManaged": True,
                "browserWindowAlive": True,
                "backendPid": 0,
                "backendLaunchPid": 6544,
                "backendAlive": False,
                "backendHealthy": False,
                "backendObserved": False,
                "backendPort": 8000,
                "backendPortListening": False,
                "backendPortOwnerPid": 0,
                "backendPortOwnerTrusted": False,
                "backendPortConflict": False,
                "browserLaunchPid": 40736,
                "browserWindowPid": 40736,
                "sessionId": "managed-session",
                "url": "http://127.0.0.1:8000",
            },
        ]
    )
    events: list[tuple[str, dict]] = []

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(daemon, "now_iso", lambda: "2026-05-24T05:30:00+00:00")
    monkeypatch.setattr(daemon, "observe_workbench", observations)
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(daemon, "_append_event", lambda event_type, payload: events.append((event_type, payload)))
    monkeypatch.setattr(daemon, "_CLOSE_VERIFICATION_TIMEOUT_SECONDS", 0)
    monkeypatch.setattr(
        daemon,
        "close_workbench",
        lambda: subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )
    monkeypatch.setattr(
        runtime_daemon,
        "_cleanup_residual_workbench_processes",
        lambda: {"supported": True, "requested": [], "terminated": [], "remaining": []},
    )

    result = runtime_daemon._handle_command(
        {
            "commandId": "cmd-close",
            "type": "close_workbench",
            "requestedBy": "test",
            "args": {},
        }
    )

    assert result["ok"] is False
    assert result["errorType"] == "RuntimeError"
    assert "not fully stopped" in result["message"]
    assert any(event_type == "workbench.close.verification_failed" for event_type, _payload in events)
    failed_payload = next(payload for event_type, payload in events if event_type == "workbench.close.verification_failed")
    assert failed_payload["commandId"] == "cmd-close"
    assert failed_payload["browserWindowPid"] == 40736
    assert failed_payload["attempts"] == 1


def test_handle_close_workbench_skips_residual_cleanup_for_plain_close_when_already_closed_without_residual(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {"activeCommandId": "cmd-close"},
        "workbench": {
            "desiredState": "closed",
            "observedState": "closed",
            "phase": "steady",
        },
    }
    close_calls = []

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        lambda: {
            "observedState": "closed",
            "backendAlive": False,
            "backendHealthy": False,
            "backendObserved": False,
            "backendPortListening": False,
            "backendPortOwnerPid": 0,
            "backendPortOwnerResidual": False,
            "lifecycleConsistency": "consistent",
            "browserWindowAlive": False,
        },
    )
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(
        daemon,
        "close_workbench",
        lambda: close_calls.append("close") or subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )
    monkeypatch.setattr(
        runtime_daemon,
        "_cleanup_residual_workbench_processes",
        lambda: (_ for _ in ()).throw(AssertionError("already-closed clean path should not scan residual processes")),
    )

    result = runtime_daemon._handle_close_workbench(
        command_id="cmd-close",
        args={"stopManager": False},
    )

    assert result["ok"] is True
    assert result["message"] == "Workbench is already closed."
    assert result["stopDaemon"] is False
    assert result["residualCleanup"]["skipped"] == "already_closed_no_residual"
    assert close_calls == []


def test_handle_close_workbench_cleans_residual_processes_when_already_closed_with_residual(monkeypatch):
    runtime_daemon = daemon.RuntimeManagerDaemon()
    state = {
        "command": {"activeCommandId": "cmd-close"},
        "workbench": {
            "desiredState": "closed",
            "observedState": "closed",
            "phase": "steady",
        },
    }
    cleanup_calls = []
    close_calls = []

    monkeypatch.setattr(daemon, "load_state", lambda: state)
    monkeypatch.setattr(daemon, "save_state", lambda next_state: next_state)
    monkeypatch.setattr(
        daemon,
        "observe_workbench",
        lambda: {
            "observedState": "closed",
            "backendAlive": False,
            "backendHealthy": False,
            "backendObserved": False,
            "backendPortListening": False,
            "backendPortOwnerPid": 0,
            "backendPortOwnerResidual": True,
            "lifecycleConsistency": "residual_backend",
            "browserWindowAlive": False,
        },
    )
    monkeypatch.setattr(daemon, "build_evolution_summary", lambda: {"self": {}, "supervised": {}})
    monkeypatch.setattr(
        daemon,
        "close_workbench",
        lambda: close_calls.append("close") or subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )
    monkeypatch.setattr(
        runtime_daemon,
        "_cleanup_residual_workbench_processes",
        lambda: cleanup_calls.append("cleanup") or {"supported": True, "requested": [49128], "terminated": [49128], "remaining": []},
    )

    result = runtime_daemon._handle_close_workbench(
        command_id="cmd-close",
        args={"stopManager": True},
    )

    assert result["ok"] is True
    assert result["message"] == "Workbench is already closed."
    assert result["stopDaemon"] is True
    assert result["residualCleanup"]["terminated"] == [49128]
    assert cleanup_calls == ["cleanup"]
    assert close_calls == []


def test_observe_workbench_marks_trusted_backend_partial_when_managed_window_is_missing(tmp_path, monkeypatch):
    launcher_state_path = tmp_path / "state.json"
    launcher_state_path.write_text(
        json.dumps(
            {
                "backendPid": 19964,
                "browserWindowPid": 5168,
                "browserManaged": True,
                "url": "http://127.0.0.1:8766",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(workbench_controller, "LAUNCHER_STATE_PATH", launcher_state_path)
    monkeypatch.setattr(workbench_controller, "_is_process_alive", lambda pid: False)
    monkeypatch.setattr(workbench_controller, "_is_backend_healthy", lambda url: False)
    monkeypatch.setattr(workbench_controller, "_listening_pid_for_port", lambda port: 52396)
    monkeypatch.setattr(workbench_controller, "_port_is_listening_socket", lambda port: False)
    monkeypatch.setattr(
        workbench_controller,
        "_repo_workbench_backend_kind",
        lambda pid: "managed_workbench_backend" if pid == 52396 else "",
    )

    observation = workbench_controller.observe_workbench()

    assert observation["observedState"] == "partial"
    assert observation["backendObserved"] is True
    assert observation["backendPortListening"] is True
    assert observation["backendPortOwnerPid"] == 52396
    assert observation["backendPortOwnerKind"] == "managed_workbench_backend"
    assert observation["backendPortOwnerTrusted"] is True
    assert observation["backendPortOwnerResidual"] is False
    assert observation["backendPortConflict"] is False
    assert observation["browserWindowAlive"] is False
    assert observation["lifecycleConsistency"] == "browser_missing"


def test_observe_workbench_treats_trusted_headless_backend_as_open_when_tracked_pid_is_dead(tmp_path, monkeypatch):
    launcher_state_path = tmp_path / "state.json"
    launcher_state_path.write_text(
        json.dumps(
            {
                "backendPid": 19964,
                "browserWindowPid": 0,
                "browserManaged": False,
                "url": "http://127.0.0.1:8766",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(workbench_controller, "LAUNCHER_STATE_PATH", launcher_state_path)
    monkeypatch.setattr(workbench_controller, "_is_process_alive", lambda pid: False)
    monkeypatch.setattr(workbench_controller, "_is_backend_healthy", lambda url: False)
    monkeypatch.setattr(workbench_controller, "_listening_pid_for_port", lambda port: 52396)
    monkeypatch.setattr(workbench_controller, "_port_is_listening_socket", lambda port: False)
    monkeypatch.setattr(
        workbench_controller,
        "_repo_workbench_backend_kind",
        lambda pid: "managed_workbench_backend" if pid == 52396 else "",
    )

    observation = workbench_controller.observe_workbench()

    assert observation["observedState"] == "open"
    assert observation["backendObserved"] is True
    assert observation["browserManaged"] is False
    assert observation["browserWindowAlive"] is False
    assert observation["lifecycleConsistency"] == "consistent"


def test_observe_workbench_does_not_treat_external_port_owner_as_open(tmp_path, monkeypatch):
    launcher_state_path = tmp_path / "state.json"
    launcher_state_path.write_text(
        json.dumps(
            {
                "backendPid": 19964,
                "browserWindowPid": 0,
                "browserManaged": True,
                "url": "http://127.0.0.1:8766",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(workbench_controller, "LAUNCHER_STATE_PATH", launcher_state_path)
    monkeypatch.setattr(workbench_controller, "_is_process_alive", lambda pid: False)
    monkeypatch.setattr(workbench_controller, "_is_backend_healthy", lambda url: True)
    monkeypatch.setattr(workbench_controller, "_listening_pid_for_port", lambda port: 52396)
    monkeypatch.setattr(workbench_controller, "_port_is_listening_socket", lambda port: True)
    monkeypatch.setattr(workbench_controller, "_repo_workbench_backend_kind", lambda pid: "")

    observation = workbench_controller.observe_workbench()

    assert observation["observedState"] == "closed"
    assert observation["backendObserved"] is False
    assert observation["backendPortListening"] is True
    assert observation["backendPortOwnerPid"] == 52396
    assert observation["backendPortOwnerKind"] == ""
    assert observation["backendPortOwnerTrusted"] is False
    assert observation["backendPortOwnerResidual"] is False
    assert observation["backendPortConflict"] is True


def test_observe_workbench_reports_unmanaged_repo_port_owner_as_residual(tmp_path, monkeypatch):
    launcher_state_path = tmp_path / "state.json"
    launcher_state_path.write_text(
        json.dumps(
            {
                "backendPid": 19964,
                "browserWindowPid": 0,
                "browserManaged": True,
                "url": "http://127.0.0.1:8766",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(workbench_controller, "LAUNCHER_STATE_PATH", launcher_state_path)
    monkeypatch.setattr(workbench_controller, "_is_process_alive", lambda pid: False)
    monkeypatch.setattr(workbench_controller, "_is_backend_healthy", lambda url: True)
    monkeypatch.setattr(workbench_controller, "_listening_pid_for_port", lambda port: 52396)
    monkeypatch.setattr(workbench_controller, "_port_is_listening_socket", lambda port: True)
    monkeypatch.setattr(
        workbench_controller,
        "_repo_workbench_backend_kind",
        lambda pid: "unmanaged_workbench" if pid == 52396 else "",
    )

    observation = workbench_controller.observe_workbench()

    assert observation["observedState"] == "closed"
    assert observation["backendObserved"] is False
    assert observation["backendHealthy"] is True
    assert observation["backendPortListening"] is True
    assert observation["backendPortOwnerPid"] == 52396
    assert observation["backendPortOwnerKind"] == "unmanaged_workbench"
    assert observation["backendPortOwnerTrusted"] is False
    assert observation["backendPortOwnerResidual"] is True
    assert observation["backendPortConflict"] is False
    assert observation["lifecycleConsistency"] == "residual_backend"


def test_snapshot_residual_exclusions_keep_untrusted_residual_port_owner(monkeypatch):
    monkeypatch.setattr(daemon.os, "getpid", lambda: 700)
    monkeypatch.setattr(daemon, "list_repo_runtime_processes", lambda project_root: [])

    excluded = daemon._snapshot_residual_excluded_pids(
        {
            "backendPid": 0,
            "backendLaunchPid": 0,
            "backendPortOwnerPid": 52396,
            "backendPortOwnerTrusted": False,
            "backendPortOwnerResidual": True,
            "browserLaunchPid": 0,
            "browserWindowPid": 0,
        },
        manager_pid=701,
    )

    assert 700 in excluded
    assert 701 in excluded
    assert 52396 not in excluded


def test_snapshot_residual_exclusions_keep_trusted_port_owner_out_of_residuals(monkeypatch):
    monkeypatch.setattr(daemon.os, "getpid", lambda: 700)
    monkeypatch.setattr(daemon, "list_repo_runtime_processes", lambda project_root: [])

    excluded = daemon._snapshot_residual_excluded_pids(
        {
            "backendPid": 0,
            "backendLaunchPid": 0,
            "backendPortOwnerPid": 52396,
            "backendPortOwnerTrusted": True,
            "backendPortOwnerResidual": False,
            "browserLaunchPid": 0,
            "browserWindowPid": 0,
        },
        manager_pid=701,
    )

    assert 52396 in excluded


def test_listening_pid_for_port_prefers_psutil(monkeypatch):
    class LocalAddress:
        port = 8766

    class Connection:
        laddr = LocalAddress()
        status = "LISTEN"
        pid = 52396

    class FakePsutil:
        @staticmethod
        def net_connections(kind):
            assert kind == "tcp"
            return [Connection()]

    monkeypatch.setitem(sys.modules, "psutil", FakePsutil)
    monkeypatch.setattr(workbench_controller.os, "name", "nt", raising=False)
    monkeypatch.setattr(workbench_controller, "_listening_pid_for_port_windows", lambda port: 0)

    assert workbench_controller._listening_pid_for_port(8766) == 52396


def test_residual_process_payload_reports_only_unmanaged_workbench(monkeypatch, tmp_path):
    class FakeProc:
        def __init__(self, info):
            self.info = info

    repo = tmp_path / "repo"
    repo.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.setattr(
        process_inventory.psutil,
        "process_iter",
        lambda attrs: iter(
            [
                FakeProc(
                    {
                        "pid": 49780,
                        "ppid": 1,
                        "name": "python.exe",
                        "cmdline": ["python", "scripts/web_workbench.py", "--port", "8001", "--no-browser"],
                        "cwd": str(repo),
                    }
                ),
                FakeProc(
                    {
                        "pid": 18860,
                        "ppid": 1,
                        "name": "python.exe",
                        "cmdline": ["python", "-m", "core.runtime_manager.cli", "daemon"],
                        "cwd": str(repo),
                    }
                ),
                FakeProc(
                    {
                        "pid": 3000,
                        "ppid": 1,
                        "name": "python.exe",
                        "cmdline": ["python", "scripts/web_workbench.py", "--port", "9001", "--no-browser"],
                        "cwd": str(other),
                    }
                ),
            ]
        ),
    )

    payload = process_inventory.residual_process_payload(project_root=repo, exclude_pids={18860})

    assert payload["count"] == 1
    assert payload["items"][0]["pid"] == 49780
    assert payload["items"][0]["port"] == 8001


def test_residual_process_payload_uses_configured_port_for_workbench_without_port_arg(monkeypatch, tmp_path):
    class FakeProc:
        def __init__(self, info):
            self.info = info

    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(process_inventory, "configured_backend_port", lambda: 8000)
    monkeypatch.setattr(
        process_inventory.psutil,
        "process_iter",
        lambda attrs: iter(
            [
                FakeProc(
                    {
                        "pid": 31832,
                        "ppid": 50404,
                        "name": "python.exe",
                        "cmdline": ["python", "scripts/web_workbench.py", "--no-browser"],
                        "cwd": str(repo),
                    }
                ),
            ]
        ),
    )

    payload = process_inventory.residual_process_payload(project_root=repo)

    assert payload["count"] == 1
    assert payload["items"][0]["pid"] == 31832
    assert payload["items"][0]["kind"] == "unmanaged_workbench"
    assert payload["items"][0]["port"] == 8000


def test_residual_process_payload_ignores_launcher_managed_backend(monkeypatch, tmp_path):
    class FakeProc:
        def __init__(self, info):
            self.info = info

    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(
        process_inventory.psutil,
        "process_iter",
        lambda attrs: iter(
            [
                FakeProc(
                    {
                        "pid": 22416,
                        "ppid": 1,
                        "name": "pythonw.exe",
                        "cmdline": [
                            str(repo / ".venv" / "Scripts" / "pythonw.exe"),
                            "scripts/web_workbench.py",
                            "--port",
                            "8001",
                            "--no-browser",
                            "--managed-by-launcher",
                        ],
                        "cwd": str(repo),
                    }
                ),
                FakeProc(
                    {
                        "pid": 49780,
                        "ppid": 1,
                        "name": "python.exe",
                        "cmdline": ["python", "scripts/web_workbench.py", "--port", "8001", "--no-browser"],
                        "cwd": str(repo),
                    }
                ),
            ]
        ),
    )

    payload = process_inventory.residual_process_payload(project_root=repo)
    processes = process_inventory.list_repo_runtime_processes(project_root=repo)

    assert {item.kind for item in processes} == {"managed_workbench_backend", "unmanaged_workbench"}
    assert payload["count"] == 1
    assert payload["items"][0]["pid"] == 49780


def test_managed_browser_process_payload_groups_profile_children(monkeypatch, tmp_path):
    class MemoryInfo:
        def __init__(self, rss, private):
            self.rss = rss
            self.private = private

    class FakeProc:
        def __init__(self, info):
            self.info = info

    profile_dir = tmp_path / "repo" / ".runtime" / "launcher" / "edge-app-profile"
    profile_dir.mkdir(parents=True)
    ordinary_profile = tmp_path / "Edge" / "User Data"
    ordinary_profile.mkdir(parents=True)
    mib = 1024 * 1024

    monkeypatch.setattr(
        process_inventory.psutil,
        "process_iter",
        lambda attrs: iter(
            [
                FakeProc(
                    {
                        "pid": 100,
                        "ppid": 1,
                        "name": "msedge.exe",
                        "cmdline": ["msedge.exe", f"--user-data-dir={profile_dir}", "--app=http://127.0.0.1:8000"],
                        "memory_info": MemoryInfo(200 * mib, 180 * mib),
                    }
                ),
                FakeProc(
                    {
                        "pid": 101,
                        "ppid": 100,
                        "name": "msedge.exe",
                        "cmdline": ["msedge.exe", "--type=gpu-process"],
                        "memory_info": MemoryInfo(120 * mib, 110 * mib),
                    }
                ),
                FakeProc(
                    {
                        "pid": 102,
                        "ppid": 100,
                        "name": "msedge.exe",
                        "cmdline": [
                            "msedge.exe",
                            "--type=renderer",
                            "--renderer-sub-type=extension",
                            f"--user-data-dir={profile_dir}",
                        ],
                        "memory_info": MemoryInfo(90 * mib, 80 * mib),
                    }
                ),
                FakeProc(
                    {
                        "pid": 200,
                        "ppid": 1,
                        "name": "msedge.exe",
                        "cmdline": ["msedge.exe", f"--user-data-dir={ordinary_profile}"],
                        "memory_info": MemoryInfo(500 * mib, 450 * mib),
                    }
                ),
            ]
        ),
    )

    payload = process_inventory.managed_browser_process_payload(profile_dir=profile_dir)

    assert payload["supported"] is True
    assert payload["count"] == 3
    assert payload["totalWorkingSetMB"] == 410
    assert payload["totalPrivateMB"] == 370
    assert {item["pid"] for item in payload["items"]} == {100, 101, 102}
    assert {item["type"] for item in payload["items"]} == {"browser", "gpu-process", "renderer"}
    assert any(item["subtype"] == "extension" for item in payload["items"])


def test_unmanaged_backend_cleanup_payload_leaves_frontend_dev_servers_out(monkeypatch, tmp_path):
    class FakeProc:
        def __init__(self, info):
            self.info = info

    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(
        process_inventory.psutil,
        "process_iter",
        lambda attrs: iter(
            [
                FakeProc(
                    {
                        "pid": 49780,
                        "ppid": 1,
                        "name": "python.exe",
                        "cmdline": ["python", "scripts/web_workbench.py", "--port", "8013", "--no-browser"],
                        "cwd": str(repo),
                    }
                ),
                FakeProc(
                    {
                        "pid": 51518,
                        "ppid": 1,
                        "name": "node.exe",
                        "cmdline": ["node", "node_modules/.bin/vite", "--host", "127.0.0.1"],
                        "cwd": str(repo),
                    }
                ),
            ]
        ),
    )

    payload = process_inventory.unmanaged_workbench_process_payload(project_root=repo)
    residual = process_inventory.residual_process_payload(project_root=repo)

    assert payload["count"] == 1
    assert payload["items"][0]["pid"] == 49780
    assert residual["count"] == 2


def test_residual_process_payload_ignores_descendants_of_active_backend(monkeypatch, tmp_path):
    class FakeProc:
        def __init__(self, info):
            self.info = info

    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(
        process_inventory.psutil,
        "process_iter",
        lambda attrs: iter(
            [
                FakeProc(
                    {
                        "pid": 13492,
                        "ppid": 1,
                        "name": "cmd.exe",
                        "cmdline": [
                            "cmd.exe",
                            "/d",
                            "/s",
                            "/c",
                            str(repo / ".venv" / "Scripts" / "python.exe"),
                            "scripts/web_workbench.py",
                            "--port",
                            "8000",
                            "--no-browser",
                        ],
                        "cwd": str(repo),
                    }
                ),
                FakeProc(
                    {
                        "pid": 31408,
                        "ppid": 13492,
                        "name": "python.exe",
                        "cmdline": [
                            str(repo / ".venv" / "Scripts" / "python.exe"),
                            "scripts/web_workbench.py",
                            "--port",
                            "8000",
                            "--no-browser",
                        ],
                        "cwd": str(repo),
                    }
                ),
                FakeProc(
                    {
                        "pid": 41160,
                        "ppid": 31408,
                        "name": "python.exe",
                        "cmdline": [
                            "python.exe",
                            "scripts/web_workbench.py",
                            "--port",
                            "8000",
                            "--no-browser",
                        ],
                        "cwd": str(repo),
                    }
                ),
                FakeProc(
                    {
                        "pid": 49780,
                        "ppid": 1,
                        "name": "python.exe",
                        "cmdline": ["python", "scripts/web_workbench.py", "--port", "8001", "--no-browser"],
                        "cwd": str(repo),
                    }
                ),
            ]
        ),
    )

    payload = process_inventory.residual_process_payload(project_root=repo, exclude_pids={13492, 31408})

    assert payload["count"] == 1
    assert payload["items"][0]["pid"] == 49780


def test_residual_process_payload_reports_unmanaged_frontend_dev_server(monkeypatch, tmp_path):
    class FakeProc:
        def __init__(self, info):
            self.info = info

    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(
        process_inventory.psutil,
        "process_iter",
        lambda attrs: iter(
            [
                FakeProc(
                    {
                        "pid": 51517,
                        "ppid": 1,
                        "name": "python.exe",
                        "cmdline": ["python", "-m", "http.server", "5173", "-d", "frontend"],
                        "cwd": str(repo),
                    }
                ),
                FakeProc(
                    {
                        "pid": 51518,
                        "ppid": 1,
                        "name": "node.exe",
                        "cmdline": ["node", "node_modules/.bin/vite", "--host", "127.0.0.1"],
                        "cwd": str(repo),
                    }
                ),
            ]
        ),
    )

    payload = process_inventory.residual_process_payload(project_root=repo)

    assert payload["count"] == 2
    assert {item["kind"] for item in payload["items"]} == {"unmanaged_frontend_dev_server"}
    assert {item["pid"] for item in payload["items"]} == {51517, 51518}
    assert {item["port"] for item in payload["items"]} == {5173}


def test_residual_process_payload_reports_bun_frontend_dev_server(monkeypatch, tmp_path):
    class FakeProc:
        def __init__(self, info):
            self.info = info

    repo = tmp_path / "repo"
    web = repo / "web"
    web.mkdir(parents=True)
    monkeypatch.setattr(
        process_inventory.psutil,
        "process_iter",
        lambda attrs: iter(
            [
                FakeProc(
                    {
                        "pid": 51522,
                        "ppid": 1,
                        "name": "bun.exe",
                        "cmdline": ["bun", "run", "bun:dev", "--host", "127.0.0.1"],
                        "cwd": str(web),
                    }
                ),
            ]
        ),
    )

    payload = process_inventory.residual_process_payload(project_root=repo)

    assert payload["count"] == 1
    assert payload["items"][0]["kind"] == "unmanaged_frontend_dev_server"
    assert payload["items"][0]["pid"] == 51522
    assert payload["items"][0]["port"] == 5173


def test_residual_process_payload_ignores_one_shot_frontend_build(monkeypatch, tmp_path):
    class FakeProc:
        def __init__(self, info):
            self.info = info

    repo = tmp_path / "repo"
    web = repo / "web"
    web.mkdir(parents=True)
    monkeypatch.setattr(
        process_inventory.psutil,
        "process_iter",
        lambda attrs: iter(
            [
                FakeProc(
                    {
                        "pid": 51520,
                        "ppid": 1,
                        "name": "cmd.exe",
                        "cmdline": ["cmd.exe", "/d", "/s", "/c", "tsc", "-b", "&&", "vite", "build"],
                        "cwd": str(web),
                    }
                ),
                FakeProc(
                    {
                        "pid": 51521,
                        "ppid": 51520,
                        "name": "node.exe",
                        "cmdline": ["node", "node_modules/.bin/vite", "build"],
                        "cwd": str(web),
                    }
                ),
                FakeProc(
                    {
                        "pid": 51523,
                        "ppid": 1,
                        "name": "bun.exe",
                        "cmdline": ["bun", "run", "bun:build"],
                        "cwd": str(web),
                    }
                ),
            ]
        ),
    )

    payload = process_inventory.residual_process_payload(project_root=repo)

    assert payload == {"count": 0, "items": []}


def test_residual_process_payload_ignores_inline_diagnostics_mentioning_frontend_tools(monkeypatch, tmp_path):
    class FakeProc:
        def __init__(self, info):
            self.info = info

    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(
        process_inventory.psutil,
        "process_iter",
        lambda attrs: iter(
            [
                FakeProc(
                    {
                        "pid": 51519,
                        "ppid": 1,
                        "name": "python.exe",
                        "cmdline": [
                            "python",
                            "-c",
                            "print('diagnose http.server vite 5173 frontend')",
                        ],
                        "cwd": str(repo),
                    }
                ),
            ]
        ),
    )

    payload = process_inventory.residual_process_payload(project_root=repo)

    assert payload == {"count": 0, "items": []}


def test_residual_process_payload_ignores_adjacent_repo_prefix_match(monkeypatch, tmp_path):
    class FakeProc:
        def __init__(self, info):
            self.info = info

    repo = tmp_path / "repo"
    repo.mkdir()
    adjacent_repo = tmp_path / "repo-backup"
    adjacent_repo.mkdir()
    monkeypatch.setattr(
        process_inventory.psutil,
        "process_iter",
        lambda attrs: iter(
            [
                FakeProc(
                    {
                        "pid": 49780,
                        "ppid": 1,
                        "name": "python.exe",
                        "cmdline": [
                            "python",
                            str(adjacent_repo / "scripts" / "web_workbench.py"),
                            "--port",
                            "8001",
                            "--no-browser",
                        ],
                        "cwd": "",
                    }
                ),
            ]
        ),
    )

    payload = process_inventory.residual_process_payload(project_root=repo)

    assert payload == {"count": 0, "items": []}


def test_residual_process_payload_uses_command_line_path_when_cwd_is_unavailable(monkeypatch, tmp_path):
    class FakeProc:
        def __init__(self, info):
            self.info = info

    repo = tmp_path / "repo"
    script_path = repo / "scripts" / "web_workbench.py"
    script_path.parent.mkdir(parents=True)
    script_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        process_inventory.psutil,
        "process_iter",
        lambda attrs: iter(
            [
                FakeProc(
                    {
                        "pid": 49780,
                        "ppid": 1,
                        "name": "python.exe",
                        "cmdline": ["python", str(script_path), "--port", "8001", "--no-browser"],
                        "cwd": "",
                    }
                ),
            ]
        ),
    )

    payload = process_inventory.residual_process_payload(project_root=repo)

    assert payload["count"] == 1
    assert payload["items"][0]["pid"] == 49780
    assert payload["items"][0]["port"] == 8001


def test_atomic_write_text_retries_permission_error(tmp_path, monkeypatch):
    target_path = tmp_path / "state.json"
    replace_calls = {"count": 0}
    sleep_calls = []
    real_replace = state_store.os.replace

    monkeypatch.setattr(state_store, "ensure_runtime_manager_dirs", lambda: None)

    def flaky_replace(src: str, dst: str):
        replace_calls["count"] += 1
        if replace_calls["count"] == 1:
            raise PermissionError("locked")
        return real_replace(src, dst)

    monkeypatch.setattr(state_store.os, "replace", flaky_replace)
    monkeypatch.setattr(state_store.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    state_store._atomic_write_text(target_path, "hello")

    assert target_path.read_text(encoding="utf-8") == "hello"
    assert replace_calls["count"] == 2
    assert sleep_calls == [0.05]


def test_atomic_write_text_waits_out_longer_permission_error(tmp_path, monkeypatch):
    target_path = tmp_path / "state.json"
    replace_calls = {"count": 0}
    sleep_calls = []
    real_replace = state_store.os.replace

    monkeypatch.setattr(state_store, "ensure_runtime_manager_dirs", lambda: None)

    def flaky_replace(src: str, dst: str):
        replace_calls["count"] += 1
        if replace_calls["count"] <= 8:
            raise PermissionError("locked")
        return real_replace(src, dst)

    monkeypatch.setattr(state_store.os, "replace", flaky_replace)
    monkeypatch.setattr(state_store.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    state_store._atomic_write_text(target_path, "hello")

    assert target_path.read_text(encoding="utf-8") == "hello"
    assert replace_calls["count"] == 9
    assert sleep_calls[:3] == [0.05, 0.1, 0.15000000000000002]
    assert sleep_calls[-1] == 0.25


def test_atomic_write_text_falls_back_to_in_place_write_after_replace_timeout(tmp_path, monkeypatch):
    target_path = tmp_path / "state.json"
    replace_calls = {"count": 0}
    monotonic_values = iter([0.0, state_store.WRITE_RETRY_TIMEOUT_SECONDS + 0.1])

    monkeypatch.setattr(state_store, "ensure_runtime_manager_dirs", lambda: None)
    monkeypatch.setattr(state_store.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(state_store.time, "monotonic", lambda: next(monotonic_values))

    def always_locked_replace(src: str, dst: str):
        replace_calls["count"] += 1
        raise PermissionError("locked")

    monkeypatch.setattr(state_store.os, "replace", always_locked_replace)

    state_store._atomic_write_text(target_path, "hello")

    assert target_path.read_text(encoding="utf-8") == "hello"
    assert replace_calls["count"] == 1


def test_load_state_retries_transient_json_decode_error(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    state_path.write_text('{"runtimeState": "running"}', encoding="utf-8")
    real_json_loads = state_store.json.loads
    load_calls = {"count": 0}
    sleep_calls = []

    monkeypatch.setattr(state_store, "STATE_PATH", state_path)
    monkeypatch.setattr(state_store.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    def flaky_json_loads(raw: str):
        load_calls["count"] += 1
        if load_calls["count"] == 1:
            raise json.JSONDecodeError("transient", raw, 0)
        return real_json_loads(raw)

    monkeypatch.setattr(state_store.json, "loads", flaky_json_loads)

    payload = state_store.load_state()

    assert payload["runtimeState"] == "running"
    assert load_calls["count"] == 2
    assert sleep_calls == [0.05]


def test_evolution_store_atomic_write_retries_permission_error(tmp_path, monkeypatch):
    target_path = tmp_path / "snapshot.json"
    replace_calls = {"count": 0}
    sleep_calls = []
    real_replace = evolution_store.os.replace

    monkeypatch.setattr(evolution_store, "ensure_evolution_store_dirs", lambda: None)

    def flaky_replace(src: str, dst: str):
        replace_calls["count"] += 1
        if replace_calls["count"] <= 3:
            raise PermissionError("locked")
        return real_replace(src, dst)

    monkeypatch.setattr(evolution_store.os, "replace", flaky_replace)
    monkeypatch.setattr(evolution_store.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    evolution_store._atomic_write_json(target_path, {"ok": True})

    assert json.loads(target_path.read_text(encoding="utf-8")) == {"ok": True}
    assert replace_calls["count"] == 4
    assert sleep_calls == [0.05, 0.1, 0.15000000000000002]


def test_evolution_store_is_isolated_from_real_runtime_during_pytest():
    real_runtime_root = constants.PROJECT_ROOT / ".runtime" / "runtime-manager"
    run_id = "pytest-runtime-store-isolation-sentinel"
    original_index = evolution_store.load_run_index("self")
    target_path = real_runtime_root / "evolution" / "self" / "runs" / f"{run_id}.json"
    assert not target_path.exists()

    try:
        evolution_store.persist_run_snapshot(
            "self",
            {
                "runId": run_id,
                "status": "queued",
                "startedAt": "2026-05-21T00:00:00Z",
                "updatedAt": "2026-05-21T00:00:00Z",
            },
            active_run_id=run_id,
        )

        assert not target_path.exists()
    finally:
        if target_path.exists():
            target_path.unlink()
        evolution_store.save_run_index(
            "self",
            active_run_id=str(original_index.get("activeRunId") or ""),
            latest_run_id=str(original_index.get("latestRunId") or ""),
        )


def test_evolution_store_delete_snapshot_clears_active_and_repoints_latest(tmp_path, monkeypatch):
    runs_dir = tmp_path / "supervised" / "runs"
    index_path = tmp_path / "supervised" / "index.json"

    def fake_kind_paths(kind: str):
        assert kind == "supervised"
        return runs_dir, index_path

    monkeypatch.setattr(evolution_store, "_kind_paths", fake_kind_paths)
    runs_dir.mkdir(parents=True, exist_ok=True)

    old = {
        "runId": "old-run",
        "status": "cancelled",
        "startedAt": "2026-05-18T11:00:00Z",
        "updatedAt": "2026-05-18T11:00:00Z",
    }
    active = {
        "runId": "active-run",
        "status": "queued",
        "startedAt": "2026-05-18T12:00:00Z",
        "updatedAt": "2026-05-18T12:00:00Z",
    }
    evolution_store.persist_run_snapshot("supervised", old, active_run_id="")
    evolution_store.persist_run_snapshot("supervised", active, active_run_id="active-run")

    result = evolution_store.delete_run_snapshot("supervised", "active-run")

    assert result["deleted"] is True
    assert result["clearedActive"] is True
    assert result["clearedLatest"] is True
    assert result["activeRunId"] == ""
    assert result["latestRunId"] == "old-run"
    assert evolution_store.load_run_snapshot("supervised", "active-run") is None
    assert evolution_store.load_latest_run_snapshot("supervised")["runId"] == "old-run"


def test_evolution_store_delete_corrupt_index_only_run_clears_index(tmp_path, monkeypatch):
    runs_dir = tmp_path / "supervised" / "runs"
    index_path = tmp_path / "supervised" / "index.json"

    def fake_kind_paths(kind: str):
        assert kind == "supervised"
        return runs_dir, index_path

    monkeypatch.setattr(evolution_store, "_kind_paths", fake_kind_paths)
    runs_dir.mkdir(parents=True, exist_ok=True)

    evolution_store.save_run_index("supervised", active_run_id="missing-run", latest_run_id="missing-run")

    result = evolution_store.delete_run_snapshot("supervised", "missing-run")

    assert result["deleted"] is False
    assert result["clearedActive"] is True
    assert result["clearedLatest"] is True
    assert result["activeRunId"] == ""
    assert result["latestRunId"] == ""


def test_clear_pid_keeps_newer_owner(tmp_path, monkeypatch):
    pid_path = tmp_path / "daemon.pid"
    monkeypatch.setattr(state_store, "PID_PATH", pid_path)

    state_store.save_pid(200)
    state_store.clear_pid(100)
    assert pid_path.read_text(encoding="utf-8") == "200"

    state_store.clear_pid(200)
    assert not pid_path.exists()


def test_daemon_exit_marks_matching_manager_not_running(monkeypatch):
    state = {
        "runtimeState": "running",
        "managerPid": 321,
        "daemonRunning": True,
    }
    saved_states = []

    monkeypatch.setattr(daemon, "load_state", lambda: dict(state))
    monkeypatch.setattr(daemon, "save_state", lambda next_state: saved_states.append(dict(next_state)))
    monkeypatch.setattr(daemon, "now_iso", lambda: "2026-05-24T15:00:00+00:00")

    daemon._mark_daemon_not_running_after_exit(manager_pid=321)

    assert saved_states[-1]["runtimeState"] == "idle"
    assert saved_states[-1]["managerPid"] == 0
    assert saved_states[-1]["daemonRunning"] is False
    assert saved_states[-1]["lastStoppedManagerPid"] == 321


def test_daemon_exit_keeps_newer_manager_owner(monkeypatch):
    state = {
        "runtimeState": "running",
        "managerPid": 654,
        "daemonRunning": True,
    }
    saved_states = []

    monkeypatch.setattr(daemon, "load_state", lambda: dict(state))
    monkeypatch.setattr(daemon, "save_state", lambda next_state: saved_states.append(dict(next_state)))

    daemon._mark_daemon_not_running_after_exit(manager_pid=321)

    assert saved_states == []


def test_backend_health_probe_treats_low_level_http_errors_as_unhealthy(monkeypatch):
    def raise_http_exception(*_args, **_kwargs):
        raise http.client.HTTPException("connection closed")

    monkeypatch.setattr(workbench_controller, "_open_backend_health_url", raise_http_exception)

    assert workbench_controller._is_backend_healthy("http://127.0.0.1:8766") is False
