"""Persistent SQLite checkpointer for research workflow runs."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver

from vibelution_storage import resolve_project_data_home

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def default_checkpoint_path() -> Path:
    override = os.environ.get("VIBELUTION_RESEARCH_WORKFLOW_CHECKPOINT_PATH", "").strip()
    if override:
        return Path(override)
    data_root = os.environ.get("VIBELUTION_RESEARCH_WORKFLOW_DATA_ROOT", "").strip()
    if data_root:
        return Path(data_root) / "checkpoints.sqlite"
    return resolve_project_data_home(PROJECT_ROOT) / "research_workflows" / "checkpoints.sqlite"


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
