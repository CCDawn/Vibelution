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


def test_latest_checkpoint_id_resolves_initial_and_missing_threads(tmp_path: Path) -> None:
    from core.web.services.team_workflow.research_runtime.checkpoint_lifecycle import (
        latest_checkpoint_id,
        prepare_initial_checkpoint,
    )

    checkpoint_path = str(tmp_path / "checkpoints.sqlite3")
    thread_id = "thread-latest-1"
    initial = prepare_initial_checkpoint(checkpoint_path, thread_id)
    assert initial
    assert latest_checkpoint_id(checkpoint_path, thread_id) == initial
    # Unknown thread and unreadable store both fail soft to "".
    assert latest_checkpoint_id(checkpoint_path, "thread-never-created") == ""
    assert latest_checkpoint_id(str(tmp_path / "missing.sqlite3"), thread_id) == ""


def test_concurrent_create_run_same_key_replays_idempotently(
    tmp_path: Path, monkeypatch
) -> None:
    """Two racing creates with one idempotency key must both succeed with the
    same run (P1-7: the loser used to hit the run_id primary key → HTTP 500)."""
    from concurrent.futures import ThreadPoolExecutor

    from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID
    from core.web.services.team_workflow.research_runtime.run_creation import create_run
    from tests._support.workflow_ledger_http import ledger_http_client

    with ledger_http_client(tmp_path, monkeypatch):
        run_input = _baseline_run_input()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(
                    create_run,
                    CHALLENGE_CUP_WORKFLOW_ID,
                    run_input=run_input,
                    idempotency_key="idem-race-1",
                )
                for _ in range(2)
            ]
            results = [future.result(timeout=30) for future in futures]
        assert results[0]["runId"] == results[1]["runId"]

        # Same key with different input must still conflict, including on the
        # replay path taken by the concurrent loser.
        divergent = {**run_input, "questionId": "question-divergent"}
        import pytest as _pytest

        with _pytest.raises(Exception) as exc_info:
            create_run(
                CHALLENGE_CUP_WORKFLOW_ID,
                run_input=divergent,
                idempotency_key="idem-race-1",
            )
        assert "idempotency_conflict" in str(exc_info.value.code)


def test_ledger_create_run_idempotency_ignores_client_authored_scope_mode(
    tmp_path: Path, monkeypatch
) -> None:
    from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID
    from core.web.services.team_workflow.research_runtime.run_creation import create_run
    from tests._support.workflow_ledger_http import ledger_http_client

    with ledger_http_client(tmp_path, monkeypatch):
        first_input = _baseline_run_input()
        first_input["workflowSessionScopeV3"] = {"hypothesis_design": "off"}
        replay_input = _baseline_run_input()
        replay_input["workflowSessionScopeV3"] = {"hypothesis_design": "on"}

        first = create_run(
            CHALLENGE_CUP_WORKFLOW_ID,
            run_input=first_input,
            idempotency_key="idem-scope-mode-1",
        )
        replay = create_run(
            CHALLENGE_CUP_WORKFLOW_ID,
            run_input=replay_input,
            idempotency_key="idem-scope-mode-1",
        )

        assert replay["runId"] == first["runId"]
        assert replay["inputSnapshotHash"] == first["inputSnapshotHash"]


def _baseline_run_input() -> dict:
    import json as _json

    fixture_path = (
        Path(__file__).parent / "fixtures" / "research_workflow_v21_baseline_case.json"
    )
    return _json.loads(fixture_path.read_text(encoding="utf-8"))["runInput"]
