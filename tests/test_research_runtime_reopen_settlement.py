"""Return-to-running settlement: terminal residue is replaced, not patched.

Three regression faces of the same invariant — anything that moves a run or
NodeRun back to a live status must clear the whole terminal field set in the
same settlement, never carry stale ``finishedAt``/``failureCode``/
``failureSummary``/``completedAt`` residue from the state it recovers from:

1. the shared NodeRun reopen helper clears every terminal-only field;
2. the external-agent reconciliation reopen replaces the whole residue;
3. the ledger ``update_run_status`` is a full-replacement settlement —
   non-terminal landings NULL ``completed_at_ms`` and write ``active_node_id``
   from the call, with no COALESCE carry-over.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from core.web.services.team_workflow.research_runtime.external_agent_task_failure import (
    reopen_external_agent_reconciliation_failure,
)
from core.web.services.team_workflow.research_runtime.node_execution_support import (
    NODE_RUN_TERMINAL_FIELD_KEYS,
    reopen_node_run_for_running,
)
from core.web.services.team_workflow.research_runtime.store import WorkflowRunStore

from tests._support.workflow_ledger_helpers import (
    FIXED_NOW_MS,
    build_run_record,
    open_ledger_store,
)


def test_reopen_node_run_for_running_clears_whole_terminal_field_set() -> None:
    node_run = {
        "status": "failed",
        "attempt": 2,
        "finishedAt": "2026-01-01T00:00:00Z",
        "failureCode": "adapter_execution_exception",
        "failureSummary": "boom",
    }

    reopened = reopen_node_run_for_running(node_run)

    assert reopened["status"] == "running"
    for key in NODE_RUN_TERMINAL_FIELD_KEYS:
        assert reopened[key] == "", f"{key} must not survive a return to running"
    assert reopened["attempt"] == 2


def test_external_agent_reopen_clears_all_terminal_fields(tmp_path: Path) -> None:
    store = WorkflowRunStore(tmp_path)
    record = {
        "runId": "run-1",
        "workflowId": "challenge-cup-research",
        "workflowVersionId": "wv-1",
        "threadId": "thread-1",
        "status": "blocked",
        "blockedReason": "agent_usage_missing",
        "runtimeCurrentNodeIds": [],
        "taskBundles": [],
        "modelRoutingDecisions": [],
        "commandReceipts": [],
        "events": [],
        "taskLeases": [{"nodeRunId": "node-run-1", "status": "failed"}],
        "nodeRuns": [
            {
                "nodeRunId": "node-run-1",
                "nodeId": "hypothesis_design",
                "attempt": 1,
                "status": "blocked",
                "taskId": "task-1",
                "failureCode": "agent_usage_missing",
                "failureSummary": "usage missing",
                "finishedAt": "2026-01-01T00:00:00Z",
                "artifactRefs": [],
            }
        ],
    }
    store.create_run(record)
    node_run = store.get_run("run-1")["nodeRuns"][0]

    updated = reopen_external_agent_reconciliation_failure(
        store, record=store.get_run("run-1"), node_run=node_run
    )

    reopened = next(
        item for item in updated["nodeRuns"] if item["nodeRunId"] == "node-run-1"
    )
    assert reopened["status"] == "running"
    for key in NODE_RUN_TERMINAL_FIELD_KEYS:
        assert reopened[key] == "", f"{key} must not survive the reopen"
    assert updated["status"] == "running"
    assert updated["blockedReason"] == ""
    lease = next(
        item for item in updated["taskLeases"] if item["nodeRunId"] == "node-run-1"
    )
    assert lease["status"] == "running"


def test_update_run_status_is_full_replacement_not_patch(tmp_path: Path) -> None:
    """A non-terminal settlement clears stale terminal fields wholesale.

    The seeded row carries legacy residue (``completed_at_ms`` plus
    settlement fields) that no legal transition would produce today; the
    blocked -> running settlement must NULL every one of them and write
    ``active_node_id`` only from the call.
    """
    store = open_ledger_store(tmp_path / "ledger")
    try:
        stale = dataclasses.replace(
            build_run_record(status="blocked"),
            active_node_id="stale_node",
            completion_kind="cancelled",
            terminal_reason="legacy residue",
            blocked_problem_json='{"code": "legacy"}',
            completed_at_ms=FIXED_NOW_MS,
        )

        def seed(uow) -> None:
            uow.repository.insert_run(stale)

        store.submit(seed, force_flush=True).result(timeout=10)

        def settle(uow) -> bool:
            return uow.repository.update_run_status(
                "run-test",
                "research-team",
                "running",
                FIXED_NOW_MS + 1,
                active_node_id="source_finding",
                blocked_problem_json=None,
            )

        store.submit(settle, force_flush=True).result(timeout=10)
        run = store.get_run("run-test")
        assert run is not None
        assert run.status == "running"
        assert run.active_node_id == "source_finding"
        assert run.completed_at_ms is None
        assert run.completion_kind is None
        assert run.terminal_reason is None
        assert run.blocked_problem_json is None

        # Terminal settlement: completion time lands, operational pointer clears.
        def settle_terminal(uow) -> bool:
            return uow.repository.update_run_status(
                "run-test",
                "research-team",
                "succeeded",
                FIXED_NOW_MS + 2,
                completion_kind="completed",
                terminal_reason="all nodes settled",
            )

        store.submit(settle_terminal, force_flush=True).result(timeout=10)
        run = store.get_run("run-test")
        assert run is not None
        assert run.status == "succeeded"
        assert run.completed_at_ms == FIXED_NOW_MS + 2
        assert run.active_node_id is None
        assert run.completion_kind == "completed"
        assert run.terminal_reason == "all nodes settled"
    finally:
        store.close()
