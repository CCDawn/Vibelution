"""Import-time native storage identity for the dedicated Launcher process.

The ordinary Workbench keeps its existing source root. Environment changes
after import cannot turn a request into a different storage principal.
"""

from __future__ import annotations

import os
from pathlib import Path


PROCESS_ROLE = str(os.environ.get("VIBELUTION_PROCESS_ROLE") or "").strip()


def _read_assistant_root() -> Path | None:
    if PROCESS_ROLE != "launcher_assistant":
        return None
    raw = str(os.environ.get("VIBELUTION_ASSISTANT_NATIVE_ROOT") or "").strip()
    if not raw or not Path(raw).is_absolute():
        raise ValueError("launcher_assistant requires an absolute VIBELUTION_ASSISTANT_NATIVE_ROOT")
    return Path(raw).resolve()


_ASSISTANT_NATIVE_ROOT = _read_assistant_root()


def is_launcher_assistant_process() -> bool:
    """Report the frozen role rather than a request-time environment value."""
    return _ASSISTANT_NATIVE_ROOT is not None


def resolve_native_project_root(default: Path) -> Path:
    """Bind a facade root once without changing ordinary Workbench behavior."""
    return _ASSISTANT_NATIVE_ROOT if _ASSISTANT_NATIVE_ROOT is not None else default


def assistant_native_root() -> Path:
    """Require the dedicated process identity; never infer it from a root alone."""
    if _ASSISTANT_NATIVE_ROOT is None:
        raise RuntimeError("native assistant requires a launcher_assistant process")
    return _ASSISTANT_NATIVE_ROOT
