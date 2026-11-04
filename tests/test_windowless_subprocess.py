from __future__ import annotations

import ast
import importlib
import os
import subprocess
from pathlib import Path

import pytest

from scripts.windowless_subprocess import (
    detached_no_console_popen_kwargs,
    no_window_subprocess_kwargs,
)

# Snapshot-copied hook scripts run from the hook cache without the ``core``
# package or the shared helper module, so they carry an in-place
# ``_no_window_kwargs`` policy instead of importing ``no_window_subprocess_kwargs``.
HOOK_GUARD_OWNERS = ("scripts/git_claim_guard.py", "scripts/git_hook_dispatch.py")
SUBPROCESS_ENTRYPOINTS = {"run", "check_output", "check_call", "call", "Popen"}


def test_windows_subprocess_policy_suppresses_console_windows() -> None:
    kwargs = no_window_subprocess_kwargs(creationflags=0x00000200)

    if os.name != "nt":
        assert kwargs == {}
        return

    assert kwargs["creationflags"] & int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert kwargs["creationflags"] & 0x00000200
    assert kwargs["startupinfo"].wShowWindow == int(getattr(subprocess, "SW_HIDE", 0))


def test_detached_popen_kwargs_break_away_without_visible_console() -> None:
    kwargs = detached_no_console_popen_kwargs()
    assert kwargs["stdin"] is subprocess.DEVNULL
    if os.name != "nt":
        assert kwargs["start_new_session"] is True
        return
    flags = int(kwargs["creationflags"])
    assert flags & int(getattr(subprocess, "DETACHED_PROCESS", 0x00000008))
    assert flags & 0x01000000
    assert not (flags & int(getattr(subprocess, "CREATE_NO_WINDOW", 0)))
    assert kwargs["startupinfo"].wShowWindow == int(getattr(subprocess, "SW_HIDE", 0))


def test_windowless_policy_is_used_by_high_risk_process_owners() -> None:
    project_root = Path(__file__).resolve().parents[1]
    owners = (
        "scripts/local_quality_gate.py",
        "scripts/integration_audit.py",
        "scripts/remote_test_runner.py",
        "core/infrastructure/background_tasks.py",
        "core/infrastructure/boot_pipeline.py",
        "core/infrastructure/test_gate.py",
        "core/restarter_manager/restarter.py",
        "core/web/services/config_service.py",
        "tools/python_intelligence_tools.py",
        "core/launcher/branch_instance_lifecycle.py",
        *HOOK_GUARD_OWNERS,
    )

    for relative_path in owners:
        source = (project_root / relative_path).read_text(encoding="utf-8")
        if relative_path == "core/infrastructure/background_tasks.py":
            assert "OwnedProcess.spawn" in source
            owner = (project_root / "core/infrastructure/owned_process.py").read_text(encoding="utf-8")
            assert "no_window_subprocess_kwargs" in owner
        elif relative_path in HOOK_GUARD_OWNERS:
            # Deep per-call-site coverage is enforced by the AST guard below;
            # here the helper must at least exist and be exercised.
            assert "_no_window_kwargs" in source, relative_path
            assert "_resolve_git_executable" in source, relative_path
        else:
            assert "no_window_subprocess_kwargs" in source, relative_path


def _hook_subprocess_calls(project_root: Path) -> list[tuple[str, ast.Call]]:
    calls: list[tuple[str, ast.Call]] = []
    for relative_path in HOOK_GUARD_OWNERS:
        tree = ast.parse((project_root / relative_path).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "subprocess"
                and node.func.attr in SUBPROCESS_ENTRYPOINTS
            ):
                calls.append((relative_path, node))
    return calls


def _is_no_window_suppressed(call: ast.Call) -> bool:
    return any(
        keyword.arg is None
        and isinstance(keyword.value, ast.Call)
        and getattr(keyword.value.func, "id", None) == "_no_window_kwargs"
        for keyword in call.keywords
    )


def test_hook_scripts_spawn_only_with_no_window_suppression() -> None:
    project_root = Path(__file__).resolve().parents[1]
    calls = _hook_subprocess_calls(project_root)
    assert len(calls) >= 7  # guard: 4 spawn sites + dispatch: 3 spawn sites

    for relative_path, call in calls:
        assert _is_no_window_suppressed(call), (
            f"{relative_path}:{call.lineno} spawns subprocess without _no_window_kwargs"
        )
        first = call.args[0] if call.args else None
        bare_git = isinstance(first, ast.Constant) and first.value == "git"
        assert not bare_git, (
            f"{relative_path}:{call.lineno} spawns bare PATH git instead of _resolve_git_executable()"
        )


def test_hook_script_in_place_policy_matches_shared_policy() -> None:
    guard = importlib.import_module("scripts.git_claim_guard")
    dispatch = importlib.import_module("scripts.git_hook_dispatch")

    for actual in (guard._no_window_kwargs(), dispatch._no_window_kwargs()):
        if os.name != "nt":
            assert actual == {}
            continue
        assert actual["creationflags"] & int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
        assert actual["startupinfo"].wShowWindow == int(getattr(subprocess, "SW_HIDE", 0))


@pytest.mark.parametrize("module_name", ["git_claim_guard", "git_hook_dispatch"])
def test_hook_scripts_resolve_real_git_over_cmd_trampoline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, module_name: str
) -> None:
    module = importlib.import_module(f"scripts.{module_name}")
    fake_cmd = tmp_path / "Git" / "cmd"
    fake_mingw = tmp_path / "Git" / "mingw64" / "bin"
    fake_cmd.mkdir(parents=True)
    fake_mingw.mkdir(parents=True)
    (fake_cmd / "git.exe").write_bytes(b"trampoline")
    (fake_mingw / "git.exe").write_bytes(b"real git")
    monkeypatch.setenv("PATH", str(fake_cmd))
    module._resolve_git_executable.cache_clear()
    try:
        resolved = module._resolve_git_executable()
    finally:
        module._resolve_git_executable.cache_clear()

    if os.name != "nt":
        assert resolved == "git"
        return
    assert Path(resolved) == fake_mingw / "git.exe"
