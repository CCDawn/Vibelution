"""Project-owned host platform probe.

Tests inject this function instead of mutating the global ``os.name``, so
running the suite on Linux never flips pathlib into WindowsPath semantics.
"""

from __future__ import annotations

import platform as _platform_module


def host_platform() -> str:
    """Return the host platform key: ``"windows"``, ``"linux"``, ``"darwin"``, ..."""
    return _platform_module.system().lower()


def is_windows(platform: str | None = None) -> bool:
    """Whether a platform key (or the live host) is Windows."""
    return (platform or host_platform()) == "windows"


def is_posix(platform: str | None = None) -> bool:
    """Whether a platform key (or the live host) is a POSIX system."""
    return (platform or host_platform()) in {"linux", "darwin"}
