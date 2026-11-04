"""Unit tests for scripts/cleanup_isolated_test_instances.py.

Covers the pure isolation-judgment functions and the close-flow branches with
fake process objects; no real process integration is required.
"""
from __future__ import annotations

import os
import subprocess
from types import SimpleNamespace

from scripts.cleanup_isolated_test_instances import (
    ProcessInfo,
    close_isolated_instances,
    describe_instance,
    is_isolated_test_instance,
    normalize_path,
    parse_user_data_dir,
)


def _join(*parts: str) -> str:
    return os.sep.join(parts)


TEMP_ROOT = _join("C:", "Users", "tester", "AppData", "Local", "Temp")
REPO_CHECKOUT = _join("D:", "dev-projects", "Vibelution")
LOCALAPPDATA_INSTALL = _join("C:", "Users", "tester", "AppData", "Local", "Vibelution")


def _process(
    *,
    pid: int = 100,
    name: str = "electron.exe",
    exe: str | None = None,
    cmdline: str | None = None,
    title: str | None = "Isolated test window",
) -> ProcessInfo:
    return ProcessInfo(
        pid=pid,
        name=name,
        executable_path=exe,
        command_line=cmdline,
        parent_process_id=1,
        creation_date="2026-11-04 12:15:00",
        window_title=title,
    )


class FakePowerShellRunner:
    """Record subprocess calls and script responses per PowerShell snippet kind."""

    def __init__(
        self,
        *,
        graceful: str = "closed",
        liveness: str = "gone",
        force: str = "gone",
        enumerate_stdout: str = "[]",
    ) -> None:
        self.calls: list[tuple[list[str], dict]] = []
        self._graceful = graceful
        self._liveness = liveness
        self._force = force
        self._enumerate_stdout = enumerate_stdout

    def __call__(self, command: list[str], **kwargs: object) -> SimpleNamespace:
        self.calls.append((list(command), dict(kwargs)))
        script = command[-1]
        if "Win32_Process" in script:
            stdout = self._enumerate_stdout
        elif "CloseMainWindow" in script:
            stdout = self._graceful
        elif "Stop-Process" in script:
            stdout = self._force
        else:
            stdout = self._liveness
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    @property
    def scripts(self) -> list[str]:
        return [command[-1] for command, _ in self.calls]

    def issued_force_kill(self) -> bool:
        return any("Stop-Process" in script for script in self.scripts)


# --- Isolation judgment -------------------------------------------------------


def test_matches_when_executable_lives_under_temp() -> None:
    exe = _join(TEMP_ROOT, "iso-checkout", "node_modules", "electron", "dist", "electron.exe")
    process = _process(exe=exe, cmdline=f'"{exe}" --user-data-dir={_join(TEMP_ROOT, "iso-profile")}')
    assert is_isolated_test_instance(process, TEMP_ROOT) is True


def test_matches_when_user_data_dir_lives_under_temp() -> None:
    exe = _join(LOCALAPPDATA_INSTALL, "Vibelution.exe")
    cmdline = f'"{exe}" --user-data-dir={_join(TEMP_ROOT, "vibelution-assistant-buttons")}'
    process = _process(exe=exe, cmdline=cmdline)
    assert is_isolated_test_instance(process, TEMP_ROOT) is True


def test_skips_repo_checkout_instance() -> None:
    exe = _join(REPO_CHECKOUT, "node_modules", "electron", "dist", "electron.exe")
    process = _process(exe=exe, cmdline=f'"{exe}" --user-data-dir={_join(REPO_CHECKOUT, ".vibelution")}')
    assert is_isolated_test_instance(process, TEMP_ROOT) is False


def test_skips_localappdata_product_instance() -> None:
    exe = _join(LOCALAPPDATA_INSTALL, "Vibelution.exe")
    process = _process(exe=exe, cmdline=f'"{exe}" --user-data-dir={_join(LOCALAPPDATA_INSTALL, "userdata")}')
    assert is_isolated_test_instance(process, TEMP_ROOT) is False


def test_skips_instance_without_user_data_dir_outside_temp() -> None:
    exe = _join(REPO_CHECKOUT, "node_modules", "electron", "dist", "electron.exe")
    process = _process(exe=exe, cmdline=f'"{exe}" --no-sandbox --enable-logging')
    assert is_isolated_test_instance(process, TEMP_ROOT) is False


def test_matches_across_drive_and_case_differences() -> None:
    if os.name != "nt":
        # Case-insensitive comparison is a Windows-path semantic.
        return
    temp_root = r"C:\USERS\TESTER\APPDATA\LOCAL\TEMP"
    exe = r"c:\users\tester\AppData\LOCAL\Temp\iso\electron.exe"
    process = _process(exe=exe, cmdline=None)
    assert is_isolated_test_instance(process, temp_root) is True


def test_skips_non_electron_process_even_under_temp() -> None:
    exe = _join(TEMP_ROOT, "unrelated", "chrome.exe")
    process = _process(name="chrome.exe", exe=exe)
    assert is_isolated_test_instance(process, TEMP_ROOT) is False


def test_skips_temp_sibling_directory_lookalike() -> None:
    sibling = TEMP_ROOT + "2"
    exe = _join(sibling, "electron.exe")
    process = _process(exe=exe)
    assert is_isolated_test_instance(process, TEMP_ROOT) is False


def test_normalize_path_handles_missing_paths_and_quotes() -> None:
    quoted = '"' + _join(TEMP_ROOT, "iso", "electron.exe") + '"'
    normalized = normalize_path(quoted)
    assert normalized is not None
    assert normalized == normalize_path(_join(TEMP_ROOT, "iso", "electron.exe"))


def test_normalize_path_rejects_empty_values() -> None:
    assert normalize_path(None) is None
    assert normalize_path("") is None
    assert normalize_path('  "  " ') is None


# --- Command line parsing ------------------------------------------------------


def test_parse_user_data_dir_equals_form() -> None:
    cmdline = f'"exe.exe" --flag --user-data-dir={_join(TEMP_ROOT, "profile")} --next-flag'
    assert parse_user_data_dir(cmdline) == _join(TEMP_ROOT, "profile")


def test_parse_user_data_dir_spaced_value_with_quotes() -> None:
    spaced = _join(TEMP_ROOT, "my profile")
    cmdline = f'"exe.exe" --user-data-dir "{spaced}" --next'
    assert parse_user_data_dir(cmdline) == spaced


def test_parse_user_data_dir_missing_returns_none() -> None:
    assert parse_user_data_dir(None) is None
    assert parse_user_data_dir('"exe.exe" --no-sandbox') is None


# --- Close flow branches (fake process objects) ---------------------------------


def test_graceful_close_success_without_force() -> None:
    process = _process(pid=11, title="Isolated Vibelution")
    fake = FakePowerShellRunner(graceful="closed", liveness="gone")
    results = close_isolated_instances([process], timeout=0.05, runner=fake, sleep=lambda _s: None)

    assert [r.outcome for r in results] == ["graceful"]
    assert fake.issued_force_kill() is False
    assert all("taskkill" not in script for script in fake.scripts)


def test_graceful_timeout_upgrades_to_forced_stop() -> None:
    process = _process(pid=12, title="Isolated Vibelution")
    fake = FakePowerShellRunner(graceful="closed", liveness="alive", force="gone")
    results = close_isolated_instances([process], timeout=0.05, runner=fake, sleep=lambda _s: None)

    assert [r.outcome for r in results] == ["forced"]
    assert fake.issued_force_kill() is True


def test_headless_child_exits_with_parent() -> None:
    windowed = _process(pid=21, title="Isolated Vibelution")
    child = _process(pid=22, title=None)
    fake = FakePowerShellRunner(graceful="closed", liveness="gone")
    results = close_isolated_instances([windowed, child], timeout=0.05, runner=fake, sleep=lambda _s: None)

    assert [r.outcome for r in results] == ["graceful", "graceful"]
    assert results[1].detail == "exited with parent"
    assert fake.issued_force_kill() is False


def test_surviving_headless_child_is_force_stopped() -> None:
    windowed = _process(pid=31, title="Isolated Vibelution")
    child = _process(pid=32, title=None)
    # After the graceful phase the windowed parent is gone, the child lingers.
    fake = FakePowerShellRunner(graceful="closed", liveness="alive", force="gone")
    results = close_isolated_instances([windowed, child], timeout=0.05, runner=fake, sleep=lambda _s: None)

    assert results[0].outcome == "forced"
    assert results[1].outcome == "forced"
    assert fake.issued_force_kill() is True


def test_force_failure_is_reported_not_hidden() -> None:
    process = _process(pid=41, title="Isolated Vibelution")
    fake = FakePowerShellRunner(graceful="closed", liveness="alive", force="alive")
    results = close_isolated_instances([process], timeout=0.05, runner=fake, sleep=lambda _s: None)

    assert [r.outcome for r in results] == ["failed"]
    assert "survived" in results[0].detail


def test_close_flow_uses_console_free_subprocess_policy() -> None:
    process = _process(pid=51, title="Isolated Vibelution")
    fake = FakePowerShellRunner(graceful="closed", liveness="gone")
    close_isolated_instances([process], timeout=0.05, runner=fake, sleep=lambda _s: None)

    if os.name != "nt":
        return
    create_no_window = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert fake.calls, "expected PowerShell subprocess calls"
    for _command, kwargs in fake.calls:
        assert int(kwargs.get("creationflags", 0)) & create_no_window


def test_describe_instance_lists_required_fields() -> None:
    process = _process(pid=61, exe=_join(TEMP_ROOT, "iso", "electron.exe"))
    text = describe_instance(process)
    assert "PID 61" in text
    assert "electron.exe" in text
    assert process.creation_date in text
