"""Regression tests for challenge-flow UX bugfix batch.

1. revision_forked events must replay through WorkflowEventReplayService —
   before the fix the unknown enum value crashed the whole /events + SSE
   surface for the run (the except branch re-raised the same expression).
2. Duplicate resolve_human_task decisions must fail closed with
   InvalidHumanTaskStateError instead of silently succeeding (or hitting an
   outbox UNIQUE constraint → HTTP 500) when the idempotency key changed.
3. A missing human task reports task_not_found, not run_not_found.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.research.workflow.contracts import (
    WorkflowCommandKind,
)
from core.web.services.team_workflow.research_runtime.command_service import (
    HumanTaskNotFoundError,
    InvalidHumanTaskStateError,
)
from core.web.services.team_workflow.research_runtime.event_replay_service import (
    WorkflowEventReplayService,
)
from tests._support.command_helpers import CommandHarness


def test_revision_forked_event_replays_without_error(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        harness.service.submit(harness.request(idempotency_key="ui:key-1"))
        harness.service.submit(
            harness.request(
                command=WorkflowCommandKind.FORK_REVISION,
                node_id="hypothesis_design",
                expected_run_version=2,
                idempotency_key="ui:fork-1",
                payload={
                    "fromNodeId": "hypothesis_design",
                    "reason": "revise protocol after failed evaluation",
                    "checkpointId": "ckpt-parent-1",
                },
            )
        )

        replay = WorkflowEventReplayService(store=harness.store)
        page = replay.list_events(team_id="research-team", run_id="run-test")
        types = [event.event_type for event in page.events]
        assert "revision_forked" in [
            value.value if hasattr(value, "value") else value for value in types
        ]
    finally:
        harness.close()


def test_resolve_human_task_duplicate_decision_rejected(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        harness.service.submit(harness.request(idempotency_key="ui:key-1"))

        def create_task(uow):
            attempts = uow.repository.list_attempts("run-test")
            uow.repository.insert_human_task(
                task_id="ht-1",
                run_id="run-test",
                node_run_id=attempts[0].node_run_id,
                handoff_id=None,
                task_kind="knowledge_gate",
                prompt_json="{}",
                created_at_ms=1,
            )

        harness.store.submit(create_task, force_flush=True).result(timeout=10)

        receipt = harness.service.submit(
            harness.request(
                command=WorkflowCommandKind.RESOLVE_HUMAN_TASK,
                node_id=None,
                expected_run_version=2,
                idempotency_key="ui:ht-1",
                payload={"taskId": "ht-1", "decision": "accept", "reason": "ok"},
            )
        )
        assert receipt.accepted_run_version == 3

        # 不同 idempotencyKey（前端 key 含版本号，runVersion 已 bump）的重复决策。
        with pytest.raises(InvalidHumanTaskStateError):
            harness.service.submit(
                harness.request(
                    command=WorkflowCommandKind.RESOLVE_HUMAN_TASK,
                    node_id=None,
                    expected_run_version=3,
                    idempotency_key="ui:ht-1:v3",
                    payload={"taskId": "ht-1", "decision": "reject", "reason": "reconsider"},
                )
            )

        def read(uow):
            return uow.repository.get_human_task("ht-1")

        row = harness.store.submit(read, force_flush=True).result(timeout=10)
        assert row is not None and row[6] == "accepted"
    finally:
        harness.close()


def test_resolve_human_task_missing_task_reports_task_not_found(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        harness.service.submit(harness.request(idempotency_key="ui:key-1"))
        with pytest.raises(HumanTaskNotFoundError):
            harness.service.submit(
                harness.request(
                    command=WorkflowCommandKind.RESOLVE_HUMAN_TASK,
                    node_id=None,
                    expected_run_version=2,
                    idempotency_key="ui:ht-missing",
                    payload={"taskId": "ht-nope", "decision": "accept"},
                )
            )
    finally:
        harness.close()
