#!/usr/bin/env python3
"""No-console bridge for the Windows desktop Launcher entry."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LAUNCHER_SCRIPT = PROJECT_ROOT / "scripts" / "vibelution_launcher.ps1"


def _hidden_creation_flags() -> int:
    if os.name != "nt":
        return 0
    flags = 0
    for name in ("CREATE_NEW_PROCESS_GROUP", "CREATE_NO_WINDOW"):
        flags |= int(getattr(subprocess, name, 0))
    return flags


def _hidden_startup_info() -> subprocess.STARTUPINFO | None:
    if os.name != "nt" or not hasattr(subprocess, "STARTUPINFO"):
        return None
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= int(getattr(subprocess, "STARTF_USESHOWWINDOW", 0))
    startupinfo.wShowWindow = int(getattr(subprocess, "SW_HIDE", 0))
    return startupinfo


def _powershell_executable() -> str:
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    candidate = Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return str(candidate) if candidate.exists() else "powershell.exe"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Open the Vibelution Launcher without a console window.")
    parser.add_argument("--action", default="launcher")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--python-exe", default="")
    parser.add_argument("--run-id", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    action = str(args.action or "launcher").strip().lower()
    if action != "launcher":
        raise SystemExit(f"Unsupported desktop-entry Python bridge action: {action}")
    command = [
        _powershell_executable(),
        "-NoLogo",
        "-NoProfile",
        "-WindowStyle",
        "Hidden",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(LAUNCHER_SCRIPT),
        "-Action",
        action,
    ]
    if args.no_browser:
        command.append("-NoBrowser")
    env = os.environ.copy()
    python_exe = str(args.python_exe or "").strip()
    if python_exe:
        env["VIBELUTION_PYTHON_EXE"] = python_exe
    run_id = str(args.run_id or "").strip()
    if run_id:
        env["VIBELUTION_DESKTOP_ENTRY_VBS_RUN_ID"] = run_id
    subprocess.Popen(
        command,
        cwd=str(PROJECT_ROOT),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=_hidden_creation_flags(),
        startupinfo=_hidden_startup_info(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
