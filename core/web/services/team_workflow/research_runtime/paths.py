"""Canonical research-workflow data-root and Ledger path (T8)."""

from __future__ import annotations

import os
from pathlib import Path

LEDGER_FILENAME = "workflow-ledger.sqlite"


def research_workflow_data_root() -> Path:
    override = os.environ.get("VIBELUTION_RESEARCH_WORKFLOW_DATA_ROOT", "").strip()
    if override:
        return Path(override)
    home = Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or ".")
    return home / "Documents" / "Vibelution" / "data" / "research_workflows"


def workflow_ledger_path(data_root: Path | None = None) -> Path:
    override = os.environ.get("VIBELUTION_RESEARCH_WORKFLOW_LEDGER_PATH", "").strip()
    if override:
        return Path(override)
    return (data_root or research_workflow_data_root()) / LEDGER_FILENAME


def legacy_json_runs_exist(data_root: Path | None = None) -> bool:
    root = data_root or research_workflow_data_root()
    runs = root / "runs"
    if not runs.is_dir():
        return False
    return any(runs.glob("run-*.json"))
