"""Persistent SQLite checkpointer for research workflow runs.

v1 default path lives under operator Documents data dir (not repo / not localStorage).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver

# Operator workspace (desktop v1). Overridable for tests.
DEFAULT_CHECKPOINT_REL = Path("Vibelution") / "data" / "research_workflows" / "checkpoints.sqlite"


def default_checkpoint_path() -> Path:
    override = os.environ.get("VIBELUTION_RESEARCH_WORKFLOW_CHECKPOINT_PATH", "").strip()
    if override:
        return Path(override)
    home = Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or ".")
    return home / "Documents" / DEFAULT_CHECKPOINT_REL


def ensure_checkpoint_parent(path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def open_sqlite_checkpointer(path: Path | str | None = None) -> Any:
    """Return a context-manager SqliteSaver (use as `with open_sqlite_checkpointer() as cp:`)."""
    target = ensure_checkpoint_parent(Path(path) if path else default_checkpoint_path())
    return SqliteSaver.from_conn_string(str(target))


def assert_not_memory_saver(checkpointer: Any) -> None:
    name = type(checkpointer).__name__
    if name in {"MemorySaver", "InMemorySaver"}:
        raise RuntimeError("InMemorySaver is not allowed as delivery checkpointer (ADR 0006).")
