"""Canonical research-workflow data-root and Ledger path (T8)."""

from __future__ import annotations

import os
from pathlib import Path

from vibelution_storage import resolve_project_data_home

LEDGER_FILENAME = "workflow-ledger.sqlite"
PROJECT_ROOT = Path(__file__).resolve().parents[5]


def research_workflow_data_root() -> Path:
    override = os.environ.get("VIBELUTION_RESEARCH_WORKFLOW_DATA_ROOT", "").strip()
    if override:
        return Path(override)
    return resolve_project_data_home(PROJECT_ROOT) / "research_workflows"


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
