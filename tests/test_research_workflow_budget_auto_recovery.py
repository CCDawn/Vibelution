"""Automated budget-precheck recovery (P0-B): sweep-driven extend → retry.

The 2026-09-08→09-09 SCI-009 overnight stall left a knowledge sideflow child
run blocked ``budget_precheck_insufficient`` for 8.3h although the block
carries a machine-readable recovery contract (extend_budget by the stored
``suggestedExtensionTokens``, then retry_node).  The maintenance sweep now
drives that same contract through the same command service, bounded and
idempotent:

- a blocked node with a valid suggestion is extended and retried exactly
  once; re-running the sweep is a no-op (the extension is visible in
  ``safety_limits_json`` and the retried attempt is no longer blocked);
- the per-node automated extension cap (default 2) declines further
  extensions and records WHY in ``recovery_records`` while leaving the
  human-visible stop intact;
- a manual extension is detected and the step then only retries;
- non-budget ``auto_advance_not_ready`` blocks stay excluded (step three's
  contract is unchanged);
- ``VIBELUTION_AUTO_BUDGET_RECOVERY=0`` disables the step entirely.

No real model, network, or research activity is involved.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from core.research.workflow.contracts import WorkflowCommandKind
from core.research.workflow.challenge_cup_runtime import ChallengeCupGraphCoordinator
from core.web.services.team_workflow.research_runtime import (
    hypothesis_first_chain as chain,
)
from core.web.services.team_workflow.research_runtime import (
    runtime_factory,
)
from core.web.services.team_workflow.research_runtime.budget_stage_admission import (
    AUTO_BUDGET_RECOVERY_ACTOR_ID,
    AUTO_BUDGET_RECOVERY_ENV,
    AUTO_BUDGET_RECOVERY_MAX_EXTENSIONS_ENV,
    BUDGET_PRECHECK_INSUFFICIENT_CODE,
)
from core.web.services.team_workflow.research_runtime.graph_dispatch_worker import (
    GraphDispatchWorker,
)
from tests._support.graph_helpers import GraphHarness
from tests._support.team_workflow.helpers import _use_tmp_project_root
from tests._support.workflow_ledger_helpers import (
    FIXED_NOW_MS,
    build_attempt_record,
)

_TEAM_ID = "research-team"
_QUESTION_ID = "SCI-096"
STAGE = "experiment_design"


# ---------------------------------------------------------------------------
# fixtures: a run actually blocked by the stage-boundary budget precheck


def _worker(harness: GraphHarness) -> GraphDispatchWorker:
    return GraphDispatchWorker(
        store=harness.commands.store,
        coordinator=ChallengeCupGraphCoordinator(harness.tmp_path / "checkpoints.sqlite"),
        owner_id="graph-worker-budget-auto-recovery",
        now_provider=lambda: FIXED_NOW_MS + 1000,
    )


def _update_input_snapshot(harness: GraphHarness, run_id: str, snapshot: dict) -> None:
    def mutate(uow):
        uow.repository.execute(
            "UPDATE workflow_runs SET input_snapshot_json = ? WHERE run_id = ?",
            (json.dumps(snapshot), run_id),
        )

    harness.commands.store.submit(mutate, force_flush=True).result(timeout=10)


def _seed_history(harness: GraphHarness, *, tokens: int) -> None:
    """A settled, usage-observed budget receipt in a sibling run (same question)."""

    harness.commands.seed_run(run_id="run-history")
    node_run_id = "nr-run-history-protocol_design-a1"
    command_id = "cmd-run-history-protocol_design"

    def mutate(uow):
        from tests._support.workflow_ledger_helpers import build_command_record

        uow.repository.insert_command(
            build_command_record(
                command_id=command_id,
                run_id="run-history",
                node_id="protocol_design",
                idempotency_key=f"key:{command_id}",
            )
        )
        uow.repository.insert_attempt(
            build_attempt_record(
                node_run_id=node_run_id,
                run_id="run-history",
                node_id="protocol_design",
                attempt=1,
                status="succeeded",
                command_id=command_id,
            )
        )
        uow.repository.insert_budget_receipt(
            receipt_id="br-run-history-protocol_design",
            run_id="run-history",
            node_run_id=node_run_id,
            reservation_id=f"reservation-{node_run_id}",
            stage_id=STAGE,
            policy_hash="",
            reserved_json=json.dumps({"reserved": {"estimatedTokens": tokens}}),
            created_at_ms=FIXED_NOW_MS,
        )
        uow.repository.execute(
            "UPDATE budget_receipts SET status = 'settled', settled_json = ? "
            "WHERE receipt_id = ?",
            (json.dumps({"usage": {"tokens": tokens}}), "br-run-history-protocol_design"),
        )

    harness.commands.store.submit(mutate, force_flush=True).result(timeout=10)


def _consume_run_budget(harness: GraphHarness, *, tokens: int) -> None:
    def mutate(uow):
        uow.repository.insert_budget_receipt(
            receipt_id="br-run-test-hypothesis_design-used",
            run_id="run-test",
            node_run_id="nr-run-test-hypothesis_design-a1",
            reservation_id="reservation-nr-run-test-hypothesis_design-a1",
            stage_id=STAGE,
            policy_hash="",
            reserved_json=json.dumps({"reserved": {"estimatedTokens": tokens}}),
            created_at_ms=FIXED_NOW_MS,
        )
        uow.repository.execute(
            "UPDATE budget_receipts SET status = 'settled', settled_json = ? "
            "WHERE receipt_id = ?",
            (json.dumps({"usage": {"tokens": tokens}}), "br-run-test-hypothesis_design-used"),
        )

    harness.commands.store.submit(mutate, force_flush=True).result(timeout=10)


def _seed_blocked_on_budget_precheck(harness: GraphHarness) -> dict[str, Any]:
    """400K stage, 300K consumed, 300K typical node → blocked with suggestion."""

    harness.seed()
    harness.start_thread_to("hypothesis_design")
    _update_input_snapshot(
        harness,
        "run-test",
        {"budgetPolicy": {"stageBudgets": {STAGE: {"tokens": 400_000}}}},
    )
    _seed_history(harness, tokens=300_000)
    _consume_run_budget(harness, tokens=300_000)
    harness.worker = _worker(harness)
    pending = harness.latest_adapter_pending()
    assert pending is not None
    harness.consume_adapter(pending.action_id)
    harness.resume(
        run_id="run-test",
        node_id="hypothesis_design",
        attempt=1,
        action_id=json.loads(pending.payload_json)["actionId"],
    )
    handled = harness.worker.run_once()
    assert handled == 1
    attempts = harness.commands.store.list_attempts("run-test")
    blocked = next(a for a in attempts if a.node_id == "protocol_design")
    assert blocked.status == "blocked"
    problem = json.loads(blocked.problem_json or "{}")
    assert problem["code"] == BUDGET_PRECHECK_INSUFFICIENT_CODE
    run = harness.commands.store.get_run("run-test")
    assert run is not None and run.status == "blocked"
    return problem


class _HarnessRuntime:
    """Duck-typed runtime exposing store + command_service to the sweep."""

    def __init__(self, harness: GraphHarness) -> None:
        self.store = harness.commands.store
        self.command_service = harness.commands.service


class _FakeQueryService:
    def __init__(self, runs: list[dict[str, Any]]) -> None:
        self._runs = runs

    def list_runs(self, *, team_id: str, workflow_id: str) -> dict[str, Any]:
        return {"workflowId": workflow_id, "runs": list(self._runs)}


def _runtime_env(
    monkeypatch: pytest.MonkeyPatch,
    harness: GraphHarness,
    *,
    run_status: str = "blocked",
) -> _HarnessRuntime:
    from core.web.services.team_workflow.research_runtime import (
        formal_read_runtime,
    )

    monkeypatch.setattr(
        formal_read_runtime,
        "get_query_service",
        lambda: _FakeQueryService(
            [
                {
                    "runId": "run-test",
                    "questionId": _QUESTION_ID,
                    "status": run_status,
                }
            ]
        ),
    )
    runtime = _HarnessRuntime(harness)
    monkeypatch.setattr(
        runtime_factory,
        "production_workflow_runtime",
        lambda: runtime,
    )
    return runtime


def _run_version(harness: GraphHarness) -> int:
    record = harness.commands.store.get_run("run-test")
    assert record is not None
    return record.run_version


def _recovery_rows(harness: GraphHarness) -> list[dict[str, Any]]:
    rows = harness.commands.store.submit(
        lambda uow: uow.repository.execute(
            "SELECT recovery_id, problem_code, evidence_json, status, resolution_json "
            "FROM recovery_records WHERE run_id = 'run-test' "
            "ORDER BY created_at_ms"
        ).fetchall(),
        force_flush=True,
    ).result(timeout=10)
    return [
        {
            "recoveryId": row[0],
            "problemCode": row[1],
            "evidence": json.loads(row[2]),
            "status": row[3],
            "resolution": json.loads(row[4]) if row[4] else None,
        }
        for row in rows or []
    ]


# ---------------------------------------------------------------------------
# (a) blocked + valid suggestion → extend + retry exactly once, idempotent


def test_sweep_extends_and_retries_blocked_node_exactly_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = GraphHarness(tmp_path)
    try:
        problem = _seed_blocked_on_budget_precheck(harness)
        runtime = _runtime_env(monkeypatch, harness)
        suggested = int(problem["suggestedExtensionTokens"])
        new_total = int(problem["stageLimitTokens"]) + suggested

        first = chain.auto_extend_budget_blocked_nodes(
            _TEAM_ID, question_id=_QUESTION_ID
        )

        assert first == {
            "blockedRuns": 1,
            "extended": 1,
            "retried": 1,
            "declined": 0,
            "skipped": 0,
            "ineligible": 0,
            "failed": 0,
        }
        # extend landed through the command SSOT: safety limits carry the new
        # overrun-aware total and a budget_settled event audits it.
        run = harness.commands.store.get_run("run-test")
        assert run is not None
        limits = json.loads(run.safety_limits_json or "{}")
        assert limits["stageTokens"][STAGE] == new_total
        events = harness.commands.store.list_events("run-test")
        assert any(e.event_type == "budget_settled" for e in events)
        # retry landed through the same command SSOT: old attempt stale,
        # successor attempt owns the node again.
        attempts = sorted(
            (a for a in harness.commands.store.list_attempts("run-test")
             if a.node_id == "protocol_design"),
            key=lambda a: a.attempt,
        )
        assert [a.attempt for a in attempts] == [1, 2]
        assert attempts[0].status == "stale"
        assert attempts[1].status in {"starting", "dispatching"}
        # audit trail: exactly one automated extension, actor distinguishable.
        records = _recovery_rows(harness)
        assert len(records) == 1
        assert records[0]["evidence"]["action"] == "auto_extend"
        assert records[0]["evidence"]["actor"] == AUTO_BUDGET_RECOVERY_ACTOR_ID
        assert records[0]["evidence"]["nodeId"] == "protocol_design"
        assert records[0]["resolution"]["newStageTokens"] == new_total
        assert records[0]["status"] == "resolved"
        assert chain._count_auto_budget_extensions(
            harness.commands.store, run_id="run-test", node_id="protocol_design"
        ) == 1

        # Idempotency: the retried node is no longer blocked on budget, the
        # extension is already visible, so a second pass must be a no-op.
        monkeypatch.setattr(
            runtime_factory,
            "production_workflow_runtime",
            lambda: runtime,
        )
        second = chain.auto_extend_budget_blocked_nodes(
            _TEAM_ID, question_id=_QUESTION_ID
        )
        assert second["extended"] == 0
        assert second["retried"] == 0
        assert second["declined"] == 0
        assert _recovery_rows(harness) == records
        final_run = harness.commands.store.get_run("run-test")
        assert final_run is not None
        assert json.loads(final_run.safety_limits_json or "{}")["stageTokens"][
            STAGE
        ] == new_total
    finally:
        harness.close()


# ---------------------------------------------------------------------------
# (b) cap exceeded → no extension, human stop preserved, decline recorded


def test_sweep_declines_when_extension_cap_exhausted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = GraphHarness(tmp_path)
    try:
        problem = _seed_blocked_on_budget_precheck(harness)
        _runtime_env(monkeypatch, harness)
        monkeypatch.setenv(AUTO_BUDGET_RECOVERY_MAX_EXTENSIONS_ENV, "1")
        seeded_run = harness.commands.store.get_run("run-test")
        assert seeded_run is not None
        seeded_limits_json = str(seeded_run.safety_limits_json or "")
        # one automated extension already spent on this node (restart-proof:
        # the cap is counted from the recovery_records audit trail).
        assert chain._record_auto_budget_recovery(
            harness.commands.store,
            run_id="run-test",
            node_id="protocol_design",
            attempt_no=1,
            action="auto_extend",
            resolution={"stageId": STAGE, "newStageTokens": 999},
            now_ms=FIXED_NOW_MS,
        )

        summary = chain.auto_extend_budget_blocked_nodes(
            _TEAM_ID, question_id=_QUESTION_ID
        )

        assert summary["declined"] == 1
        assert summary["extended"] == 0
        assert summary["retried"] == 0
        assert summary["failed"] == 0
        # the human-visible stop is intact: run still blocked on the same
        # budget problem, limits untouched, no budget_settled event.
        run = harness.commands.store.get_run("run-test")
        assert run is not None and run.status == "blocked"
        landed = json.loads(run.blocked_problem_json or "{}")
        assert landed["code"] == BUDGET_PRECHECK_INSUFFICIENT_CODE
        assert json.loads(run.safety_limits_json or "{}") == json.loads(
            seeded_limits_json
        )
        events = harness.commands.store.list_events("run-test")
        assert not any(e.event_type == "budget_settled" for e in events)
        assert not any(e.event_type == "node_starting" for e in events)
        # decline is audited with the reason, once per blocked attempt.
        records = _recovery_rows(harness)
        declines = [r for r in records if r["evidence"].get("action") == "declined"]
        assert len(declines) == 1
        assert declines[0]["resolution"]["reason"] == "auto_extension_cap_exhausted"
        assert declines[0]["resolution"]["autoExtensionsApplied"] == 1
        # re-running never duplicates the decline entry.
        again = chain.auto_extend_budget_blocked_nodes(
            _TEAM_ID, question_id=_QUESTION_ID
        )
        assert again["declined"] == 1
        assert [
            r for r in _recovery_rows(harness)
            if r["evidence"].get("action") == "declined"
        ] == declines
    finally:
        harness.close()


# ---------------------------------------------------------------------------
# (c) manual extension already present → the step only retries


def test_sweep_only_retries_when_manual_extension_already_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = GraphHarness(tmp_path)
    try:
        _seed_blocked_on_budget_precheck(harness)
        _runtime_env(monkeypatch, harness)
        # the operator's manual one-click extend: same command path as the
        # anomaly-inbox CTA (budget_settled, stage limit raised).
        receipt = harness.commands.service.submit(
            harness.commands.request(
                command=WorkflowCommandKind.EXTEND_BUDGET,
                node_id=None,
                payload={"limits": {"stageTokens": {STAGE: 2_000_000}}},
                expected_run_version=_run_version(harness),
                idempotency_key="ui:manual-extend-1",
            )
        )
        assert receipt.status == "accepted"

        summary = chain.auto_extend_budget_blocked_nodes(
            _TEAM_ID, question_id=_QUESTION_ID
        )

        assert summary["extended"] == 0
        assert summary["retried"] == 1
        assert summary["declined"] == 0
        # no automated extension audit row: the extend was not ours.
        records = [
            r for r in _recovery_rows(harness)
            if r["evidence"].get("action") == "auto_extend"
        ]
        assert records == []
        attempts = sorted(
            (a for a in harness.commands.store.list_attempts("run-test")
             if a.node_id == "protocol_design"),
            key=lambda a: a.attempt,
        )
        assert [a.attempt for a in attempts] == [1, 2]
        assert attempts[1].status in {"starting", "dispatching"}
    finally:
        harness.close()


# ---------------------------------------------------------------------------
# (d) non-budget auto_advance_not_ready blocks stay excluded


def _attempt_record_for(
    run_id: str,
    node_id: str,
    attempt: int,
    status: str,
    problem: dict[str, Any] | None,
    updated_at_ms: int = 1_000,
) -> Any:
    from core.research.workflow.ledger.records import NodeAttemptRecord

    return NodeAttemptRecord(
        node_run_id=f"nrun-{run_id}-{node_id}-{attempt}",
        run_id=run_id,
        node_id=node_id,
        attempt=attempt,
        actor_kind="agent",
        status=status,
        command_id="cmd-seed",
        binding_snapshot_id=None,
        input_snapshot_hash="hash-seed",
        pending_action_id=None,
        execution_anchor_id=None,
        retry_of_node_run_id=None,
        problem_json=(
            json.dumps(problem, ensure_ascii=False) if problem is not None else None
        ),
        started_at_ms=updated_at_ms - 10,
        updated_at_ms=updated_at_ms,
        finished_at_ms=None,
    )


def test_sweep_ignores_non_budget_auto_advance_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """blocked on the transient readiness verdict → untouched, no audit row."""

    from core.web.services.team_workflow.research_runtime import (
        formal_read_runtime,
    )

    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(
        formal_read_runtime,
        "get_query_service",
        lambda: _FakeQueryService(
            [
                {
                    "runId": "run-readiness",
                    "questionId": _QUESTION_ID,
                    "status": "blocked",
                }
            ]
        ),
    )

    class _Store:
        def __init__(self) -> None:
            self.submits: list[Any] = []

        def list_attempts(self, run_id: str) -> list[Any]:
            return [
                _attempt_record_for(
                    "run-readiness",
                    "source_finding",
                    3,
                    "blocked",
                    {"code": "auto_advance_not_ready", "detail": "meeting_open"},
                    updated_at_ms=2_000,
                ),
                # an older budget block moved on: the latest verdict is the
                # readiness one, so the node is NOT budget-recoverable.
                _attempt_record_for(
                    "run-readiness",
                    "source_finding",
                    2,
                    "blocked",
                    {
                        "code": BUDGET_PRECHECK_INSUFFICIENT_CODE,
                        "stageId": STAGE,
                        "stageLimitTokens": 400_000,
                        "suggestedExtensionTokens": 200_000,
                    },
                    updated_at_ms=1_000,
                ),
            ]

        def submit(self, fn, *args, **kwargs):
            self.submits.append(fn)
            raise AssertionError("ineligible runs must not touch recovery_records")

    class _Runtime:
        store = _Store()

    monkeypatch.setattr(
        runtime_factory, "production_workflow_runtime", lambda: _Runtime()
    )

    summary = chain.auto_extend_budget_blocked_nodes(
        _TEAM_ID, question_id=_QUESTION_ID
    )

    assert summary == {
        "blockedRuns": 1,
        "extended": 0,
        "retried": 0,
        "declined": 0,
        "skipped": 0,
        "ineligible": 1,
        "failed": 0,
    }
    assert _Runtime.store.submits == []


# ---------------------------------------------------------------------------
# config gate: VIBELUTION_AUTO_BUDGET_RECOVERY=0 disables the step


def test_env_gate_disables_auto_budget_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services.team_workflow.research_runtime import (
        formal_read_runtime,
    )

    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setenv(AUTO_BUDGET_RECOVERY_ENV, "0")

    def _forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("disabled step must not enumerate runs")

    monkeypatch.setattr(formal_read_runtime, "get_query_service", _forbidden)

    summary = chain.auto_extend_budget_blocked_nodes(
        _TEAM_ID, question_id=_QUESTION_ID
    )

    assert summary == {
        "blockedRuns": 0,
        "extended": 0,
        "retried": 0,
        "declined": 0,
        "skipped": 0,
        "ineligible": 0,
        "failed": 0,
    }
