"""Crash-safe workflow run store and idempotency index."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID
from core.web.services.team_workflow.research_runtime.atomic_fs import (
    CorruptWorkflowStoreError,
    atomic_write_text,
)
from core.web.services.team_workflow.research_runtime.store import WorkflowRunStore


def test_atomic_run_update_preserves_previous_record_on_write_failure(tmp_path: Path) -> None:
    store = WorkflowRunStore(tmp_path / "runs")
    record = store.create_run(
        {
            "runId": "run-atomic-1",
            "workflowId": CHALLENGE_CUP_WORKFLOW_ID,
            "status": "waiting_human",
            "events": [],
            "handoffs": [],
            "humanTasks": [],
        }
    )
    path = tmp_path / "runs" / "run-atomic-1.json"
    original = path.read_text(encoding="utf-8")

    def boom(*_args, **_kwargs):
        raise OSError("simulated write failure")

    with patch(
        "core.web.services.team_workflow.research_runtime.store.atomic_write_text",
        side_effect=boom,
    ):
        with pytest.raises(OSError, match="simulated write failure"):
            store.update_run("run-atomic-1", {"status": "blocked"})

    assert path.read_text(encoding="utf-8") == original
    restored = store.get_run("run-atomic-1")
    assert restored is not None
    assert restored["status"] == "waiting_human"
    assert restored["runId"] == record["runId"]


def test_corrupt_run_record_returns_diagnostic_error(tmp_path: Path) -> None:
    store = WorkflowRunStore(tmp_path / "runs")
    path = tmp_path / "runs" / "run-bad.json"
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(CorruptWorkflowStoreError) as exc_info:
        store.get_run("run-bad")
    assert "corrupt" in str(exc_info.value).lower()
    assert "run-bad.json" in str(exc_info.value)


def test_atomic_write_text_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "file.json"
    atomic_write_text(path, '{"ok": true}\n')
    assert path.read_text(encoding="utf-8") == '{"ok": true}\n'
