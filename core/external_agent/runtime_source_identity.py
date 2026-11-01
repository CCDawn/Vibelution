"""Conservative source equivalence for an authenticated running backend.

Git HEAD is a checkout identity, not an API implementation identity. Only
explicitly non-runtime changes can bridge different commits; unknown paths,
missing history, dirty startup snapshots and failed probes remain blocked.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from core.infrastructure.no_console_git import run_git

_REVISION = re.compile(r"[a-fA-F0-9]{40}(?:[a-fA-F0-9]{24})?\Z")
_NON_RUNTIME_DIRS = ("docs/", "tests/", "web/", ".github/")
_INSTALLER_FILES = frozenset({
    "scripts/install_windows.ps1",
    "scripts/desktop_entry_catalog.ps1",
    "scripts/launch_vibelution_shortcut.ps1",
    "scripts/vibelution_launcher.ps1",
})
_MAX_PATH_OUTPUT = 64 * 1024


def _non_runtime_path(path: str) -> bool:
    # Git's -z output is unquoted and relative; reject malformed paths instead
    # of normalizing a traversal into one of the permitted prefixes.
    if not path or "\\" in path or path.startswith("/") or any(part in {"", ".", ".."} for part in path.split("/")):
        return False
    return path.startswith(_NON_RUNTIME_DIRS) or path in _INSTALLER_FILES


def runtime_sources_match(project_root: Path, running_revision: str, checkout_revision: str) -> bool:
    """Prove that a clean startup's runtime inputs still match this checkout.

    Callers must separately authenticate the live root, protocol and startup
    descriptor, and verify the startup fingerprint was clean. The committed
    range and the working tree are both checked so an uncommitted backend edit
    cannot be hidden behind a docs/installer-only commit.
    """
    if not _REVISION.fullmatch(running_revision) or not _REVISION.fullmatch(checkout_revision):
        return False
    commands = (
        ["diff", "--name-only", "-z", "--no-renames", "--no-ext-diff", "--no-textconv", running_revision, checkout_revision, "--"],
        ["diff", "--name-only", "-z", "--no-renames", "--no-ext-diff", "--no-textconv", checkout_revision, "--"],
        ["ls-files", "--others", "--exclude-standard", "-z"],
    )
    try:
        for args in commands:
            result = run_git(["--no-optional-locks", *args], cwd=project_root, timeout=1.0)
            if result.returncode or len(result.stdout) > _MAX_PATH_OUTPUT:
                return False
            if result.stdout and (not result.stdout.endswith("\0")
                                  or not all(_non_runtime_path(path) for path in result.stdout[:-1].split("\0"))):
                return False
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False
    return True
