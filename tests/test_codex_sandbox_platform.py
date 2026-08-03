"""Cross-platform Codex sandbox tests.

These tests inject the project-owned platform probe (``_host_platform`` /
``host_platform``) instead of mutating the global ``os.name``, so the same file
runs on Windows and Linux CI without WindowsPath internal errors.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.infrastructure import codex_cli_sandbox
from core.infrastructure.codex_sandbox import platform as platform_module
from core.infrastructure.codex_sandbox import process as process_module
from core.infrastructure.codex_sandbox import resolver


# ---------------------------------------------------------------------------
# Resolver: explicit path, Windows local install dir, PATH, fail closed
# ---------------------------------------------------------------------------

def test_resolver_uses_explicit_vibelution_codex_path(tmp_path):
    executable = tmp_path / "codex"
    executable.write_bytes(b"codex")
    env = {"VIBELUTION_CODEX_PATH": str(executable)}

    resolved = resolver.resolve_codex_executable(
        platform="linux",
        environ=env,
        which=lambda name: None,
    )

    assert resolved == str(executable.resolve())


def test_resolver_explicit_invalid_path_fails_closed(tmp_path):
    env = {"VIBELUTION_CODEX_PATH": str(tmp_path / "missing-codex")}

    resolved = resolver.resolve_codex_executable(
        platform="linux",
        environ=env,
        which=lambda name: "/usr/bin/codex",
    )

    assert resolved == ""


def test_resolver_windows_local_install_dir(tmp_path):
    local_executable = tmp_path / "OpenAI" / "Codex" / "bin" / "0.1.0" / "codex.exe"
    local_executable.parent.mkdir(parents=True)
    local_executable.write_bytes(b"codex")

    resolved = resolver.resolve_codex_executable(
        platform="windows",
        environ={"LOCALAPPDATA": str(tmp_path)},
        which=lambda name: None,
    )

    assert resolved == str(local_executable.resolve())


def test_resolver_windows_path_lookup_finds_codex_exe(tmp_path):
    executable = tmp_path / "codex.exe"
    executable.write_bytes(b"codex")

    resolved = resolver.resolve_codex_executable(
        platform="windows",
        environ={},
        which=lambda name: str(executable) if name == "codex.exe" else None,
    )

    assert resolved == str(executable.resolve())


def test_resolver_linux_path_lookup_finds_codex(tmp_path):
    executable = tmp_path / "codex"
    executable.write_bytes(b"codex")

    resolved = resolver.resolve_codex_executable(
        platform="linux",
        environ={},
        which=lambda name: str(executable) if name == "codex" else None,
    )

    assert resolved == str(executable.resolve())


def test_resolver_missing_fails_closed():
    assert resolver.resolve_codex_executable(platform="linux", environ={}, which=lambda name: None) == ""
    assert resolver.resolve_codex_executable(platform="windows", environ={}, which=lambda name: None) == ""


# ---------------------------------------------------------------------------
# Sandbox argv: workspace_write and danger_full_access
# ---------------------------------------------------------------------------

def test_linux_workspace_write_argv_uses_unified_codex_sandbox_surface(monkeypatch):
    monkeypatch.setattr(codex_cli_sandbox, "_host_platform", lambda: "linux")
    monkeypatch.setattr(codex_cli_sandbox, "_unix_shell_executable", lambda: "/bin/bash")
    route = SimpleNamespace(route="bash", command="git status")
    executable = "/opt/codex-cli/codex"

    argv = codex_cli_sandbox._sandbox_argv(executable, route)

    assert argv == [
        executable,
        "sandbox",
        "-c",
        'sandbox_mode="workspace-write"',
        "--",
        "/bin/bash",
        "-c",
        "git status",
    ]
    assert "windows.sandbox" not in argv


def test_linux_workspace_write_argv_requires_executable(monkeypatch):
    monkeypatch.setattr(codex_cli_sandbox, "_host_platform", lambda: "linux")
    route = SimpleNamespace(route="bash", command="echo hi")

    with pytest.raises(RuntimeError, match="executable is required"):
        codex_cli_sandbox._sandbox_argv("", route)


def test_linux_full_access_argv_uses_unix_shell_without_codex_binary(monkeypatch):
    monkeypatch.setattr(codex_cli_sandbox, "_host_platform", lambda: "linux")
    monkeypatch.setattr(codex_cli_sandbox, "_unix_shell_executable", lambda: "/bin/bash")
    route = SimpleNamespace(route="bash", command="echo full")

    argv = codex_cli_sandbox._sandbox_argv(
        "",
        route,
        sandbox_mode="danger_full_access",
    )

    assert argv == ["/bin/bash", "-c", "echo full"]
    assert "sandbox" not in argv
    assert "codex" not in " ".join(argv).lower()


def test_windows_workspace_write_argv_keeps_windows_sandbox_config(monkeypatch):
    monkeypatch.setattr(codex_cli_sandbox, "_host_platform", lambda: "windows")
    monkeypatch.setattr(
        codex_cli_sandbox,
        "_windows_command_interpreter",
        lambda: r"C:\Windows\System32\cmd.exe",
    )
    route = SimpleNamespace(route="cmd", command="dir")

    argv = codex_cli_sandbox._sandbox_argv(r"C:\Codex\codex.exe", route)

    assert 'windows.sandbox="unelevated"' in argv
    assert 'sandbox_mode="workspace-write"' in argv
    assert argv[-5:] == [
        r"C:\Windows\System32\cmd.exe",
        "/d",
        "/s",
        "/c",
        "dir",
    ]


def test_windows_full_access_argv_keeps_cmd_interpreter(monkeypatch):
    monkeypatch.setattr(codex_cli_sandbox, "_host_platform", lambda: "windows")
    monkeypatch.setattr(
        codex_cli_sandbox,
        "_windows_command_interpreter",
        lambda: r"C:\Windows\System32\cmd.exe",
    )
    route = SimpleNamespace(route="cmd", command="echo full")

    argv = codex_cli_sandbox._sandbox_argv(
        r"C:\Codex\codex.exe",
        route,
        sandbox_mode="danger_full_access",
    )

    assert argv == [r"C:\Windows\System32\cmd.exe", "/d", "/s", "/c", "echo full"]
    assert "sandbox" not in argv


def test_linux_execute_full_access_does_not_resolve_codex(monkeypatch, tmp_path):
    recorded = {}

    monkeypatch.setattr(codex_cli_sandbox, "_host_platform", lambda: "linux")
    monkeypatch.setattr(codex_cli_sandbox, "_unix_shell_executable", lambda: "/bin/bash")
    monkeypatch.setattr(
        codex_cli_sandbox,
        "_current_agent_sandbox_mode",
        lambda: "danger_full_access",
    )
    monkeypatch.setattr(
        codex_cli_sandbox,
        "_resolve_codex_executable",
        lambda: (_ for _ in ()).throw(
            AssertionError("full access must not resolve codex sandbox")
        ),
    )

    class _Completed:
        pid = 1
        returncode = 0

        def poll(self):
            return self.returncode

        def communicate(self, timeout=None):
            return "full ok\n", ""

    def fake_popen(argv, **kwargs):
        recorded["argv"] = argv
        recorded["start_new_session"] = kwargs.get("start_new_session")
        return _Completed()

    monkeypatch.setattr(codex_cli_sandbox.subprocess, "Popen", fake_popen)

    result = codex_cli_sandbox.execute_codex_sandbox_command(
        command="echo full",
        cwd=str(tmp_path),
    )

    assert result == "full ok"
    assert recorded["argv"][0] == "/bin/bash"
    assert recorded["start_new_session"] is True
    assert "sandbox" not in recorded["argv"]


# ---------------------------------------------------------------------------
# Child environment: credential scrubbing, temp layout, platform differences
# ---------------------------------------------------------------------------

def test_linux_sandbox_environment_does_not_install_windows_sitecustomize(monkeypatch, tmp_path):
    monkeypatch.setattr(codex_cli_sandbox, "_host_platform", lambda: "linux")

    environment, sandbox_temp = codex_cli_sandbox._sandbox_process_environment(
        tmp_path,
        "linux-env",
    )

    assert not (sandbox_temp / "sitecustomize.py").exists()
    assert Path(environment["VIBELUTION_CONFIG_PATH"]) == (
        sandbox_temp / "vibelution-config" / "config.toml"
    )
    assert environment["VIBELUTION_CODEX_SANDBOX_TEMP"] == str(sandbox_temp)


def test_windows_sandbox_environment_keeps_sitecustomize_shim(monkeypatch, tmp_path):
    monkeypatch.setattr(codex_cli_sandbox, "_host_platform", lambda: "windows")

    _environment, sandbox_temp = codex_cli_sandbox._sandbox_process_environment(
        tmp_path,
        "windows-env",
    )

    assert (sandbox_temp / "sitecustomize.py").is_file()


def test_default_environment_scrubs_credential_like_entries(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "api-secret")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp-token")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-secret")
    monkeypatch.setenv("POSTGRES_PASSWORD", "pg-password")
    monkeypatch.setenv("SSH_AUTH_SOCK", "/run/user/1000/ssh-agent")
    monkeypatch.setenv("PATH", "/usr/local/bin:/usr/bin")
    monkeypatch.setenv("LANG", "C.UTF-8")

    environment, _sandbox_temp = codex_cli_sandbox._sandbox_process_environment(
        tmp_path,
        "scrub",
    )

    for name in (
        "OPENAI_API_KEY",
        "GITHUB_TOKEN",
        "AWS_SECRET_ACCESS_KEY",
        "POSTGRES_PASSWORD",
        "SSH_AUTH_SOCK",
    ):
        assert name not in environment
    assert environment["PATH"] == "/usr/local/bin:/usr/bin"
    assert environment["LANG"] == "C.UTF-8"
    assert environment["VIBELUTION_CONFIG_PATH"].endswith("config.toml")


@pytest.mark.skipif(sys.platform != "linux", reason="POSIX permission bits only on Linux")
def test_linux_sandbox_temp_dir_is_0700(monkeypatch, tmp_path):
    monkeypatch.setattr(codex_cli_sandbox, "_host_platform", lambda: "linux")

    _environment, sandbox_temp = codex_cli_sandbox._sandbox_process_environment(
        tmp_path,
        "mode-0700",
    )

    mode = sandbox_temp.stat().st_mode & 0o777
    assert mode == 0o700


# ---------------------------------------------------------------------------
# Process start/termination: no console on Windows, no taskkill on POSIX
# ---------------------------------------------------------------------------

def test_sandbox_popen_kwargs_windows_keeps_no_window_flags(monkeypatch):
    monkeypatch.setattr(process_module, "host_platform", lambda: "windows")
    monkeypatch.setattr(
        process_module,
        "no_window_subprocess_kwargs",
        lambda: {"creationflags": 0x08000000},
    )

    kwargs = process_module.sandbox_popen_kwargs()

    assert kwargs == {"creationflags": 0x08000000}
    assert "start_new_session" not in kwargs


def test_sandbox_popen_kwargs_posix_uses_own_process_group(monkeypatch):
    monkeypatch.setattr(process_module, "host_platform", lambda: "linux")
    monkeypatch.setattr(process_module, "no_window_subprocess_kwargs", lambda: {})

    kwargs = process_module.sandbox_popen_kwargs()

    assert kwargs == {"start_new_session": True}


def test_posix_terminate_process_tree_never_invokes_taskkill(monkeypatch):
    calls = {"run": [], "killpg": []}

    class _Process:
        pid = 9999

        def __init__(self):
            self._returncode = None

        def poll(self):
            return self._returncode

        def terminate(self):
            self._returncode = -15

        def kill(self):
            self._returncode = -9

        def wait(self, timeout=None):
            return self._returncode

    process = _Process()
    fake_os = SimpleNamespace(
        killpg=lambda pgid, sig: calls["killpg"].append((pgid, sig)),
        getpgid=lambda pid: pid,
    )
    monkeypatch.setattr(process_module, "host_platform", lambda: "linux")
    monkeypatch.setattr(
        process_module.subprocess,
        "run",
        lambda *args, **kwargs: calls["run"].append(args),
    )
    monkeypatch.setattr(process_module, "os", fake_os)

    process_module.terminate_process_tree(process, platform="linux")

    assert calls["run"] == []  # taskkill is Windows-only
    assert calls["killpg"] == [(9999, 15)]


# ---------------------------------------------------------------------------
# os.name is never mutated by the platform tests
# ---------------------------------------------------------------------------

def test_platform_tests_never_mutate_global_os_name():
    assert os.name in {"nt", "posix"}
    assert platform_module.host_platform() in {"windows", "linux", "darwin"}
