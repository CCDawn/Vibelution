#!/usr/bin/env python3
"""Close leftover isolated-test Electron instances running from the user TEMP directory.

Isolated test harnesses (local scripts, acceptance tools, or external harnesses)
launch Electron/Vibelution copies whose executable or --user-data-dir lives under
the current user's TEMP directory. When a test run ends without teardown, those
instances stay alive and show up as stray Launcher/taskbar entries.

This tool enumerates candidate processes, keeps only the isolated-test leftovers
(nothing outside TEMP is ever touched), and either lists them (default ``--dry-run``)
or closes them (``--apply``): graceful ``CloseMainWindow`` first, then
``Stop-Process -Force`` for survivors. ``taskkill.exe`` is never used.

Usage:
    python scripts/cleanup_isolated_test_instances.py            # dry run
    python scripts/cleanup_isolated_test_instances.py --apply    # close them
    python scripts/cleanup_isolated_test_instances.py --apply --timeout 20
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.windowless_subprocess import no_window_subprocess_kwargs

ISOLATED_PROCESS_NAMES = {"electron.exe", "vibelution.exe"}

POWERSHELL_EXECUTABLE = "powershell.exe"

# Pure enumeration script: candidate Electron/Vibelution processes with metadata
# and main-window titles. JSON only, no console output beyond the payload.
ENUMERATE_SCRIPT = r"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$targets = @('electron.exe', 'vibelution.exe')
$procs = @(
    Get-CimInstance Win32_Process |
        Where-Object { $targets -contains $_.Name.ToLowerInvariant() } |
        Select-Object Name, ProcessId, ParentProcessId, ExecutablePath, CommandLine,
            @{ Name = 'CreatedText'; Expression = { if ($_.CreationDate) { $_.CreationDate.ToString('yyyy-MM-dd HH:mm:ss') } else { $null } } }
)
$out = foreach ($p in $procs) {
    $title = ''
    try {
        $gp = Get-Process -Id ([int]$p.ProcessId) -ErrorAction Stop
        $title = [string]$gp.MainWindowTitle
    } catch {
        $title = ''
    }
    [pscustomobject]@{
        name = $p.Name
        pid = [int]$p.ProcessId
        ppid = [int]$p.ParentProcessId
        exe = $p.ExecutablePath
        cmdline = $p.CommandLine
        created = $p.CreatedText
        title = $title
    }
}
ConvertTo-Json -InputObject @($out) -Compress -Depth 3
"""

LIVENESS_SCRIPT_TEMPLATE = """
if (Get-Process -Id {pid} -ErrorAction SilentlyContinue) {{ 'alive' }} else {{ 'gone' }}
"""

GRACEFUL_CLOSE_SCRIPT_TEMPLATE = """
$result = 'no-window'
try {{
    $gp = Get-Process -Id {pid} -ErrorAction Stop
    if ($gp.CloseMainWindow()) {{ $result = 'closed' }} else {{ $result = 'no-window' }}
}} catch {{
    $result = 'gone'
}}
$result
"""

FORCE_KILL_SCRIPT_TEMPLATE = """
Stop-Process -Id {pid} -Force -ErrorAction SilentlyContinue
if (Get-Process -Id {pid} -ErrorAction SilentlyContinue) {{ 'alive' }} else {{ 'gone' }}
"""


@dataclass(frozen=True)
class ProcessInfo:
    """One candidate process as reported by Windows."""

    pid: int
    name: str
    executable_path: str | None
    command_line: str | None
    parent_process_id: int | None
    creation_date: str | None
    window_title: str | None


@dataclass(frozen=True)
class CloseResult:
    """Outcome of closing one isolated-test instance."""

    pid: int
    outcome: str  # "graceful" | "forced" | "failed"
    detail: str


def normalize_path(value: str | None) -> str | None:
    """Return a lowercase, absolute, slash-normalized path, or None.

    Tolerates short (8.3) path components for existing files because
    ``Path.resolve`` expands them via the filesystem; missing paths are still
    normalized best-effort.
    """
    if not value:
        return None
    text = value.strip().strip('"').strip()
    if not text:
        return None
    try:
        resolved = Path(text).resolve()
    except (OSError, ValueError):
        return None
    return os.path.normcase(str(resolved))


def is_under_temp(candidate: str | None, temp_root: str) -> bool:
    """True when ``candidate`` is inside ``temp_root`` (boundary-aware, case-insensitive)."""
    normalized = normalize_path(candidate)
    if not normalized:
        return False
    normalized_root = normalize_path(temp_root)
    if not normalized_root:
        return False
    if normalized == normalized_root:
        return True
    return normalized.startswith(normalized_root.rstrip(os.sep) + os.sep)


def parse_user_data_dir(command_line: str | None) -> str | None:
    """Extract the --user-data-dir value from an Electron command line."""
    if not command_line:
        return None
    # Tokenize respecting double quotes so spaced Windows paths survive.
    tokens: list[str] = []
    current: list[str] = []
    in_quotes = False
    for char in command_line:
        if char == '"':
            in_quotes = not in_quotes
            continue
        if char.isspace() and not in_quotes:
            if current:
                tokens.append("".join(current))
                current = []
            continue
        current.append(char)
    if current:
        tokens.append("".join(current))

    for index, token in enumerate(tokens):
        if token == "--user-data-dir":
            if index + 1 < len(tokens) and not tokens[index + 1].startswith("-"):
                return tokens[index + 1]
        elif token.startswith("--user-data-dir="):
            value = token[len("--user-data-dir="):]
            if value:
                return value
    return None


def is_isolated_test_instance(process: ProcessInfo, temp_root: str) -> bool:
    """True only for Electron/Vibelution processes rooted in the user TEMP directory.

    A process qualifies when its name is electron.exe / Vibelution.exe AND either
    its executable path or its --user-data-dir lives under ``temp_root``.
    Product instances (repo checkout, LOCALAPPDATA install) never match.
    """
    if not process.name or process.name.lower() not in ISOLATED_PROCESS_NAMES:
        return False
    if is_under_temp(process.executable_path, temp_root):
        return True
    return is_under_temp(parse_user_data_dir(process.command_line), temp_root)


def run_powershell(script: str, runner=subprocess.run, timeout: float = 30.0) -> subprocess.CompletedProcess[str]:
    """Run one PowerShell snippet console-free (CREATE_NO_WINDOW, never taskkill.exe)."""
    command = [POWERSHELL_EXECUTABLE, "-NoProfile", "-NonInteractive", "-Command", script]
    return runner(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        **no_window_subprocess_kwargs(),
    )


def enumerate_candidate_processes(
    runner=subprocess.run,
) -> list[ProcessInfo]:
    """Enumerate running Electron/Vibelution processes (unfiltered candidates)."""
    completed = run_powershell(ENUMERATE_SCRIPT, runner=runner)
    if completed.returncode != 0 or not completed.stdout.strip():
        return []
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return []
    if isinstance(payload, dict):
        payload = [payload]
    processes: list[ProcessInfo] = []
    for entry in payload or []:
        if not isinstance(entry, dict):
            continue
        try:
            pid = int(entry.get("pid"))
        except (TypeError, ValueError):
            continue
        parent = entry.get("ppid")
        processes.append(
            ProcessInfo(
                pid=pid,
                name=str(entry.get("name") or ""),
                executable_path=entry.get("exe") or None,
                command_line=entry.get("cmdline") or None,
                parent_process_id=int(parent) if parent is not None else None,
                creation_date=entry.get("created") or None,
                window_title=entry.get("title") or None,
            )
        )
    return processes


def process_alive(pid: int, runner=subprocess.run) -> bool:
    """Check process liveness through PowerShell (never via taskkill)."""
    completed = run_powershell(LIVENESS_SCRIPT_TEMPLATE.format(pid=pid), runner=runner, timeout=15.0)
    return "alive" in (completed.stdout or "").lower()


def request_graceful_close(pid: int, runner=subprocess.run) -> bool:
    """Ask a windowed process to close via CloseMainWindow; True when the request was sent."""
    completed = run_powershell(GRACEFUL_CLOSE_SCRIPT_TEMPLATE.format(pid=pid), runner=runner, timeout=15.0)
    return "closed" in (completed.stdout or "").lower()


def force_kill(pid: int, runner=subprocess.run) -> bool:
    """Stop-Process -Force one pid; True when the process is gone afterwards."""
    completed = run_powershell(FORCE_KILL_SCRIPT_TEMPLATE.format(pid=pid), runner=runner, timeout=15.0)
    stdout = (completed.stdout or "").lower()
    if "gone" in stdout:
        return True
    if "alive" in stdout:
        return False
    # Missing output: fall back to a liveness probe.
    return not process_alive(pid, runner=runner)


def wait_until_dead(pid: int, timeout: float, runner=subprocess.run, sleep=time.sleep) -> bool:
    """Poll liveness until the process exits or ``timeout`` seconds elapse."""
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        if not process_alive(pid, runner=runner):
            return True
        if time.monotonic() >= deadline:
            return False
        sleep(min(0.5, max(0.05, deadline - time.monotonic())))


def close_isolated_instances(
    instances: list[ProcessInfo],
    *,
    timeout: float = 10.0,
    runner=subprocess.run,
    sleep=time.sleep,
) -> list[CloseResult]:
    """Close the matched instances: graceful window close first, then forced stop.

    Inject ``runner``/``sleep`` in tests; production callers use PowerShell with
    CREATE_NO_WINDOW and never taskkill.exe. Returns exactly one result per input
    instance, in input order.
    """
    outcomes: dict[int, str] = {}
    details: dict[int, str] = {}
    windowed_pids = {p.pid for p in instances if (p.window_title or "").strip()}

    # Phase 1: graceful window closes for windowed instances.
    for process in instances:
        if process.pid not in windowed_pids:
            continue
        requested = request_graceful_close(process.pid, runner=runner)
        if not requested and not process_alive(process.pid, runner=runner):
            outcomes[process.pid] = "graceful"
            details[process.pid] = "exited before close"
            continue
        if wait_until_dead(process.pid, timeout, runner=runner, sleep=sleep):
            outcomes[process.pid] = "graceful"
            details[process.pid] = "closed via window close"
        else:
            outcomes[process.pid] = "pending-force"
            details[process.pid] = "graceful close timed out"

    # Phase 2: headless children usually die with their windowed parent.
    for process in instances:
        if process.pid in outcomes:
            continue
        if not process_alive(process.pid, runner=runner):
            outcomes[process.pid] = "graceful"
            details[process.pid] = "exited with parent"
        else:
            outcomes[process.pid] = "pending-force"
            details[process.pid] = "headless child still alive"

    # Phase 3: Stop-Process -Force for survivors, highest pid (parents) first.
    survivors = [p for p in instances if outcomes.get(p.pid) == "pending-force"]
    for process in sorted(survivors, key=lambda item: item.pid, reverse=True):
        if force_kill(process.pid, runner=runner):
            outcomes[process.pid] = "forced"
            details[process.pid] = "force-stopped"
        else:
            outcomes[process.pid] = "failed"
            details[process.pid] = "survived Stop-Process -Force"

    return [
        CloseResult(pid=process.pid, outcome=outcomes[process.pid], detail=details[process.pid])
        for process in instances
    ]


def describe_instance(process: ProcessInfo) -> str:
    """One human-readable line for a matched instance."""
    user_data = parse_user_data_dir(process.command_line) or "-"
    title = (process.window_title or "").strip() or "-"
    exe = process.executable_path or "-"
    created = process.creation_date or "-"
    return (
        f"PID {process.pid}  name={process.name}\n"
        f"  exe:        {exe}\n"
        f"  user-data:  {user_data}\n"
        f"  window:     {title}\n"
        f"  created:    {created}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="list leftover instances without closing (default)")
    mode.add_argument("--apply", action="store_true", help="close matched instances gracefully, then forcibly")
    parser.add_argument("--timeout", type=float, default=10.0, help="graceful close wait in seconds (default 10)")
    args = parser.parse_args(argv)

    apply_changes = bool(args.apply)
    temp_root = tempfile.gettempdir()
    candidates = enumerate_candidate_processes()
    matched = [p for p in candidates if is_isolated_test_instance(p, temp_root)]
    skipped = len(candidates) - len(matched)

    if not apply_changes:
        print(f"Temp root: {temp_root}")
        if not matched:
            print(f"No isolated-test instances found (skipped {skipped} product processes).")
            return 0
        print(f"Found {len(matched)} isolated-test instance(s), skipped {skipped} product process(es):")
        for process in matched:
            print(describe_instance(process))
        print("Dry run only; re-run with --apply to close them.")
        return 0

    if not matched:
        print(f"Nothing to close (skipped {skipped} product processes).")
        return 0

    results = close_isolated_instances(matched, timeout=args.timeout)
    graceful = sum(1 for r in results if r.outcome == "graceful")
    forced = sum(1 for r in results if r.outcome == "forced")
    failed = [r for r in results if r.outcome == "failed"]

    print(f"Temp root: {temp_root}")
    print(
        f"Summary: {graceful} closed gracefully, {forced} force-stopped, "
        f"{len(failed)} failed, {skipped} product process(es) skipped."
    )
    for result in failed:
        print(f"  FAILED PID {result.pid}: {result.detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
