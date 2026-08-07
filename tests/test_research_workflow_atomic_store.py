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
from core.web.services.team_workflow.research_runtime.durable_index import DurableWorkflowIndex
from core.web.services.team_workflow.research_runtime.service import (
    ResearchWorkflowRuntimeService,
    reset_research_workflow_runtime_service_for_tests,
)
from core.web.services.team_workflow.research_runtime.store import WorkflowRunStore


def test_corrupt_idempotency_index_does_not_create_duplicate_run(tmp_path: Path) -> None:
    store = WorkflowRunStore(tmp_path / "runs")
    index = DurableWorkflowIndex(tmp_path / "runs" / "_index")
    ckpt = str(tmp_path / "ckpt.sqlite")
    svc = reset_research_workflow_runtime_service_for_tests(
        run_store=store,
        checkpoint_path=ckpt,
        durable_index=index,
    )
    first = svc.create_run(CHALLENGE_CUP_WORKFLOW_ID, idempotency_key="idem-1")
    # Corrupt the index after a successful create.
    index_path = tmp_path / "runs" / "_index" / "idempotency.json"
    index_path.write_text("{not-json", encoding="utf-8")

    svc2 = ResearchWorkflowRuntimeService(
        run_store=WorkflowRunStore(tmp_path / "runs"),
        checkpoint_path=ckpt,
        durable_index=DurableWorkflowIndex(tmp_path / "runs" / "_index"),
    )
    with pytest.raises(CorruptWorkflowStoreError):
        svc2.create_run(CHALLENGE_CUP_WORKFLOW_ID, idempotency_key="idem-1")
    # Original run record still present; no silent second run under same key path.
    listed = store.list_runs(CHALLENGE_CUP_WORKFLOW_ID)
    assert any(r["runId"] == first["runId"] for r in listed)


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
