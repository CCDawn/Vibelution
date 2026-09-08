"""reconcile_run must re-project run authority FROM the ledger.

run-d02722658d8b closed loop: after the reconcile offer projection (9d3dae27e)
and identity-addressed resume (527819208), reconciling still bounced the run
between ``reconciliation_required`` and a dying dispatch because
``active_node_id`` stayed pinned to an operator-misassigned dirty attempt
(``source_finding`` a6, ``checkpoint_node_mismatch``) instead of the chain
frontier. These tests pin:

- the pure supersession rule (dirty incident blocks vs. surviving readiness
  blockers);
- the acceptance shape: dirty blocked attempt + real readiness blocker +
  terminal-failed dispatch → reconcile lands the run on ``blocked`` with the
  evaluator-authored ``auto_advance_not_ready`` verdict and the V2
  ``retry-formal-node:…:<frontier>`` retry action;
- no more reconcile death loop: no revived dispatch remains for the worker to
  re-fail;
- the plain-drift repair contract from 97e227263 still revives unrelated
  failed rows.

The knowledge chain (source_finding/source_extraction/evidence_relations/
knowledge_ingestion/knowledge_handoff) has moved out of the main workflow
definition into the challenge-cup-knowledge-sideflow, so fixtures are shaped
on current main-chain nodes (problem_understanding → hypothesis_design →
protocol_design → protocol_review → protocol_freeze → …) while keeping the
original behavioral semantics.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from core.research.workflow.contracts import WorkflowCommandKind
from core.research.workflow.definition import build_challenge_cup_workflow_definition
from core.research.workflow.definition_registry import register_or_resolve
from core.research.workflow.ledger.records import KnowledgeInvocationRecord

_PINNED_WORKFLOW_VERSION_ID = register_or_resolve(
    build_challenge_cup_workflow_definition()
).workflowVersionId
from core.web.services.team_workflow.research_runtime.command_offers.reconcile_run import (
    build_reconcile_run_offer,
)
from core.web.services.team_workflow.research_runtime.command_offers.retry_node import (
    build_retry_node_offers,
)
from core.web.services.team_workflow.research_runtime.completion_dependency import (
    COMPLETION_PENDING,
)
from core.web.services.team_workflow.research_runtime.reconcile_authority import (
    EVALUATOR_BLOCK_CODE,
    plan_ledger_authority,
)
from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import (
    FIXED_NOW_MS,
    build_attempt_record,
    build_command_record,
    build_outbox_record,
    build_run_record,
)

NODE_ORDER = tuple(
    node.nodeId for node in build_challenge_cup_workflow_definition().nodes
)

# Readiness-pipeline verdict that blocks the auto-advanced successor of
# protocol_review (the freeze gate): the evaluator's own detail names the
# missing domain fact.
_READINESS_PROBLEM = {
    "code": EVALUATOR_BLOCK_CODE,
    "detail": "protocol_review_report_missing",
}
_MISMATCH_PROBLEM = {
    "code": "checkpoint_node_mismatch",
    "detail": "thread 中断于 protocol_freeze，但 dispatch 目标是 hypothesis_design",
}


def _attempt(
    node_id: str,
    *,
    attempt: int = 1,
    status: str,
    problem: dict[str, Any] | None = None,
    started_at_ms: int = FIXED_NOW_MS,
    run_id: str = "run-test",
    command_id: str = "cmd-chain",
) -> Any:
    finished = (
        started_at_ms + 500 if status in {"succeeded", "blocked"} else None
    )
    record = build_attempt_record(
        node_run_id=f"nr-{run_id}-{node_id}-a{attempt}",
        run_id=run_id,
        node_id=node_id,
        attempt=attempt,
        status=status,
        command_id=command_id,
        started_at_ms=started_at_ms,
        problem_json=(
            json.dumps(problem, ensure_ascii=False)
            if isinstance(problem, dict)
            else problem
        ),
    )
    return replace(record, finished_at_ms=finished)


def production_shape_attempts(run_id: str = "run-test") -> list[Any]:
    """run-d02722658d8b ledger facts, in start-time order.

    Migrated onto the current main chain (the knowledge nodes of the original
    incident now live in the sideflow): mid-chain successes, a readiness-gated
    successor block, and a late misassigned retry behind the covered frontier.
    """
    base = FIXED_NOW_MS - 10_000
    step = 1_000
    return [
        _attempt("problem_understanding", status="succeeded", started_at_ms=base + 0 * step, run_id=run_id),
        _attempt("hypothesis_design", attempt=5, status="succeeded", started_at_ms=base + 1 * step, run_id=run_id),
        _attempt("protocol_design", status="succeeded", started_at_ms=base + 2 * step, run_id=run_id),
        _attempt("protocol_review", attempt=2, status="succeeded", started_at_ms=base + 3 * step, run_id=run_id),
        # Auto-advance readied this successor; readiness blocked it. Real gate.
        _attempt(
            "protocol_freeze",
            status="blocked",
            problem=_READINESS_PROBLEM,
            started_at_ms=base + 4 * step,
            run_id=run_id,
        ),
        # Late operator-misassigned retry behind the covered frontier.
        _attempt(
            "hypothesis_design",
            attempt=6,
            status="blocked",
            problem=_MISMATCH_PROBLEM,
            started_at_ms=base + 6 * step,
            run_id=run_id,
        ),
    ]


def test_plan_supersedes_covered_incident_block_only() -> None:
    plan = plan_ledger_authority(production_shape_attempts(), node_order=NODE_ORDER)

    assert plan.superseded_node_run_ids == ("nr-run-test-hypothesis_design-a6",)
    assert plan.lands_blocked is True
    assert plan.active_node_id == "protocol_freeze"
    assert dict(plan.landing_problem or {}) == _READINESS_PROBLEM


def test_plan_lands_failed_frontier_blocked_for_retry() -> None:
    """A terminal-failed attempt beyond every success authors the landing.

    The evaluator blocker stays first-class; without one, the deepest failed
    attempt lands the run blocked on its own problem so the retry offer
    survives (reconciliation_required is reserved for inconsistent dispatch
    tables)."""
    plan = plan_ledger_authority(
        [
            _attempt("problem_understanding", status="succeeded"),
            _attempt(
                "hypothesis_design",
                status="failed",
                problem={"code": "agent_turn_terminal_failed"},
            ),
        ],
        node_order=NODE_ORDER,
    )
    assert plan.lands_blocked is True
    assert plan.active_node_id == "hypothesis_design"
    assert plan.landing_problem == {"code": "agent_turn_terminal_failed"}


def test_plan_never_lands_on_uncovered_incident_block() -> None:
    """Artifact-gap style blockers stay owned by backfill/heal contracts.

    The protocol-freeze reconcile contract repairs ``frozen_protocol_missing``
    and resumes the run; an incident verdict must therefore never author the
    blocked landing, only the readiness pipeline's own code may.
    """
    base = FIXED_NOW_MS - 5_000
    attempts = [
        _attempt("problem_understanding", status="succeeded", started_at_ms=base),
        _attempt(
            "knowledge_handoff",
            status="blocked",
            problem=_MISMATCH_PROBLEM,
            started_at_ms=base + 1_000,
        ),
    ]

    plan = plan_ledger_authority(attempts, node_order=NODE_ORDER)

    assert plan.superseded_node_run_ids == ()
    assert plan.lands_blocked is False
    assert plan.active_node_id is None


def test_plan_prefers_deepest_evaluator_block_over_incidents() -> None:
    """多个 blocker 并存时，落态取最深的评估管线裁决。"""
    base = FIXED_NOW_MS - 8_000
    attempts = [
        _attempt("protocol_review", status="succeeded", started_at_ms=base),
        _attempt(
            "protocol_freeze",
            attempt=1,
            status="blocked",
            problem=_READINESS_PROBLEM,
            started_at_ms=base + 1_000,
        ),
        _attempt(
            "hypothesis_design",
            attempt=6,
            status="blocked",
            problem=_MISMATCH_PROBLEM,
            started_at_ms=base + 2_000,
        ),
    ]

    plan = plan_ledger_authority(attempts, node_order=NODE_ORDER)

    assert plan.superseded_node_run_ids == ("nr-run-test-hypothesis_design-a6",)
    assert plan.lands_blocked is True
    assert plan.active_node_id == "protocol_freeze"
    assert dict(plan.landing_problem or {}) == _READINESS_PROBLEM


def test_plan_is_noop_without_unknown_nodes_or_blockers() -> None:
    base = FIXED_NOW_MS - 3_000
    live_shape = [
        _attempt("problem_understanding", status="succeeded", started_at_ms=base),
        _attempt("source_finding", status="running", started_at_ms=base + 1_000),
    ]
    noop = plan_ledger_authority(live_shape, node_order=NODE_ORDER)
    assert noop.superseded_node_run_ids == ()
    assert noop.lands_blocked is False

    foreign = [
        replace(live_shape[0], node_id="hf_generation"),
    ]
    unknown = plan_ledger_authority(foreign, node_order=NODE_ORDER)
    assert unknown.superseded_node_run_ids == ()
    assert unknown.lands_blocked is False


def _seed_production_ledger(commands: CommandHarness, *, run_id: str = "run-test") -> None:
    record = build_run_record(
        workflow_version_id=_PINNED_WORKFLOW_VERSION_ID,
        run_id=run_id,
        status="reconciliation_required",
        run_version=7,
        last_event_sequence=20,
    )
    store = commands.store

    def mutate(uow):
        uow.repository.insert_run(record)
        uow.repository.insert_command(
            build_command_record(
                command_id="cmd-chain",
                run_id=run_id,
                idempotency_key="key:chain",
                node_id="protocol_review",
            )
        )
        uow.repository.insert_command(
            build_command_record(
                command_id="cmd-a6",
                run_id=run_id,
                idempotency_key="key:a6",
                node_id="hypothesis_design",
            )
        )
        for attempt in production_shape_attempts(run_id):
            uow.repository.insert_attempt(attempt)
        uow.repository.execute(
            """
            UPDATE workflow_runs
            SET active_node_id = 'hypothesis_design',
                blocked_problem_json = ?
            WHERE run_id = ?
            """,
            (
                json.dumps(_MISMATCH_PROBLEM, ensure_ascii=False),
                run_id,
            ),
        )
        uow.repository.insert_outbox(
            replace(
                build_outbox_record(
                    "act-hypothesis-design-a6-dead",
                    run_id=run_id,
                    command_id="cmd-a6",
                    idempotency_key="graph:resume:act-hypothesis-design-a6",
                    status="failed",
                ),
                node_run_id=f"nr-{run_id}-hypothesis_design-a6",
                last_problem_json=json.dumps(
                    {"code": "graph_dispatch_failed", "detail": "transient_exhausted"}
                ),
            )
        )

    store.submit(mutate, force_flush=True).result(timeout=10)


def _offer_as_dict(offer: Any) -> dict[str, Any]:
    if isinstance(offer, dict):
        return dict(offer)
    if hasattr(offer, "to_dict"):
        return dict(offer.to_dict())
    import dataclasses

    if dataclasses.is_dataclass(offer):
        return dataclasses.asdict(offer)
    return dict(vars(offer))


def _formal_actions_from_offers(
    *,
    run_id: str,
    run_version: int,
    offers: list[Any],
) -> list[Any]:
    from core.web.routes.team_workflows.hypothesis_first_state_models import (
        HypothesisFirstStateV2,
    )
    from core.web.services.team_workflow.research_runtime import (
        hypothesis_first_state_v2,
    )
    from core.web.services.team_workflow.research_runtime.hypothesis_first_state_v2 import (
        project_state_from_records,
    )

    # Offers→actions mapping is the focus here; stub the v2 convergence gate
    # seam with an allowed verdict (the synthetic chain carries no real claim
    # data).  The gate itself is covered by the claim-gate suites.
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            hypothesis_first_state_v2,
            "_claim_belief_gate_verdict",
            lambda _team_id, _question_id, candidate_id: {
                "candidateId": candidate_id,
                "status": "allowed",
                "reason": "",
                "claims": [],
                "blockedClaims": [],
            },
        )
        state = HypothesisFirstStateV2.model_validate(
            project_state_from_records(
                team_id="research-team",
                question_id="SCI-096",
                reset_boundary=None,
                chain_records=[],
                selection_records=[],
                meeting_records=[],
                digest_records=[],
                decision_records=[],
                hypothesis_round_records=[
                    {
                        "roundId": "round-accepted",
                        "question": "SCI-096",
                        "roundIndex": 1,
                        "status": "closed",
                        "metaReview": {"accepted": True},
                    }
                ],
                formal_runs=[
                    {
                        "runId": run_id,
                        "teamId": "research-team",
                        "questionId": "SCI-096",
                        "status": "blocked",
                        "runVersion": int(run_version),
                    }
                ],
                formal_snapshots={
                    run_id: {
                        "commandOffers": [_offer_as_dict(offer) for offer in offers]
                    }
                },
            )
        )
    return [action for action in state.allowedActions if action.kind == "command"]


def test_reconcile_lands_run_on_real_readiness_blocker(tmp_path: Path) -> None:
    commands = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_production_ledger(commands)
        receipt = commands.service.submit(
            commands.request(
                command=WorkflowCommandKind.RECONCILE_RUN,
                node_id=None,
                expected_run_version=7,
                idempotency_key="ui:reconcile-1",
            )
        )
        assert receipt is not None

        run = commands.store.get_run("run-test")
        # 验收核心：落到 blocked + 真实 readiness 阻塞，active 归位链条权威。
        assert run.status == "blocked"
        assert run.active_node_id == "protocol_freeze"
        assert json.loads(str(run.blocked_problem_json)) == _READINESS_PROBLEM

        # 脏 attempt 被判 stale；其失败 dispatch 不再复活（断开死循环）。
        stale = commands.store.submit(
            lambda uow: [
                row.status
                for row in uow.repository.list_attempts("run-test")
                if row.node_run_id == "nr-run-test-hypothesis_design-a6"
            ][0],
            force_flush=True,
        ).result(timeout=10)
        assert stale == "stale"

        outbox_rows = commands.store.submit(
            lambda uow: [
                (row.action_id, row.status)
                for row in uow.repository.list_pending_outbox("run-test")
            ],
            force_flush=True,
        ).result(timeout=10)
        dead_row = [
            row for row in outbox_rows if row[0] == "act-hypothesis-design-a6-dead"
        ]
        assert not dead_row or dead_row[0][1] != "pending"
        # 没有任何复活：worker 无需被唤醒。
        assert commands.wake_count == 0

        # V2 allowedActions 出现可用的重试入口：被 readiness 阻塞的前沿节点
        # （最新 attempt 仍为 blocked）保持可重试，对账不得把它一并打死。
        refreshed = commands.store.get_run("run-test")
        definition = build_challenge_cup_workflow_definition()
        attempts = commands.store.list_attempts("run-test")
        offers = build_retry_node_offers(
            run=refreshed, definition=definition, attempts=attempts
        )
        frontier_offer = next(o for o in offers if o.node_id == "protocol_freeze")
        assert frontier_offer.available is True
        actions = _formal_actions_from_offers(
            run_id="run-test",
            run_version=refreshed.run_version,
            offers=[*offers, build_reconcile_run_offer(run=refreshed)],
        )
        retry = next(
            a
            for a in actions
            if a.command == "retry_formal_node"
            and getattr(a.payload, "nodeId", None) == "protocol_freeze"
        )
        assert retry.enabled is True
        assert retry.idempotencyKey  # durable offer key rides along
        assert any(a.command == "reconcile_formal_run" for a in actions)
    finally:
        commands.close()


def test_reconciled_shape_does_not_reenter_reconciliation_loop(tmp_path: Path) -> None:
    """Worker tick 之后不得再次翻回 reconciliation_required。"""
    from core.web.services.team_workflow.research_runtime.graph_dispatch_worker import (
        GraphDispatchWorker,
    )

    commands = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_production_ledger(commands)
        commands.service.submit(
            commands.request(
                command=WorkflowCommandKind.RECONCILE_RUN,
                node_id=None,
                expected_run_version=7,
                idempotency_key="ui:reconcile-loop",
            )
        )

        worker = GraphDispatchWorker(
            store=commands.store,
            coordinator=object(),
            owner_id="graph-worker-test",
            now_provider=lambda: FIXED_NOW_MS + 90_000,
        )
        worker.run_once()

        run = commands.store.get_run("run-test")
        assert run.status == "blocked"
        assert run.active_node_id == "protocol_freeze"
    finally:
        commands.close()


def test_plain_drift_reconcile_still_revives_live_rows(tmp_path: Path) -> None:
    """97e227263 的常规漂移形态保持原契约：复活 running 所需的 dispatch。"""
    commands = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        record = build_run_record(
            workflow_version_id=_PINNED_WORKFLOW_VERSION_ID,
            run_id="run-drift",
            status="reconciliation_required",
            run_version=3,
            last_event_sequence=8,
        )
        store = commands.store

        def mutate(uow):
            uow.repository.insert_run(record)
            uow.repository.insert_command(
                build_command_record(
                    command_id="cmd-rel",
                    run_id="run-drift",
                    idempotency_key="key:rel",
                    node_id="evidence_relations",
                )
            )
            uow.repository.insert_attempt(
                build_attempt_record(
                    node_run_id="nr-run-drift-evidence_relations-a2",
                    run_id="run-drift",
                    node_id="evidence_relations",
                    attempt=2,
                    status="succeeded",
                    command_id="cmd-rel",
                )
            )
            uow.repository.execute(
                "UPDATE workflow_runs SET active_node_id = 'evidence_relations'"
                " WHERE run_id = 'run-drift'"
            )
            uow.repository.insert_outbox(
                replace(
                    build_outbox_record(
                        "act-run-drift-resume",
                        run_id="run-drift",
                        command_id="cmd-rel",
                        idempotency_key="graph:resume:act-run-drift",
                        status="failed",
                    ),
                    node_run_id="nr-run-drift-evidence_relations-a2",
                    last_problem_json=json.dumps(
                        {"code": "transient", "detail": "expired lease"}
                    ),
                )
            )

        store.submit(mutate, force_flush=True).result(timeout=10)

        commands.service.submit(
            commands.request(
                command=WorkflowCommandKind.RECONCILE_RUN,
                run_id="run-drift",
                node_id=None,
                expected_run_version=3,
                idempotency_key="ui:reconcile-drift",
            )
        )

        run = store.get_run("run-drift")
        assert run.status == "running"
        pending = store.submit(
            lambda uow: [
                row.status
                for row in uow.repository.list_pending_outbox("run-drift")
                if row.action_id == "act-run-drift-resume"
            ],
            force_flush=True,
        ).result(timeout=10)
        assert pending == ["pending"]
        assert commands.wake_count == 1
    finally:
        commands.close()


def test_reconcile_with_zero_revivable_or_active_work_lands_blocked_for_retry(
    tmp_path: Path,
) -> None:
    """A failed adapter-only frontier must not be projected back to running.

    It lands ``blocked`` on the deepest failed attempt's own problem so the
    ordinary retry offer stays usable; ``reconciliation_required`` remains
    reserved for genuinely inconsistent dispatch tables (a reconcile loop
    that keeps re-deriving "no active work" while retry is refused would
    wedge the run forever — SCI-003 hypothesis_design incident)."""

    commands = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        run_id = "run-zero-work"
        store = commands.store

        def seed(uow):
            uow.repository.insert_run(
                build_run_record(
                    workflow_version_id=_PINNED_WORKFLOW_VERSION_ID,
                    run_id=run_id,
                    status="reconciliation_required",
                    run_version=3,
                    last_event_sequence=8,
                )
            )
            uow.repository.insert_command(
                build_command_record(
                    command_id="cmd-zero-work",
                    run_id=run_id,
                    idempotency_key="key:zero-work",
                    node_id="protocol_freeze",
                )
            )
            uow.repository.insert_attempt(
                _attempt(
                    "protocol_review",
                    status="succeeded",
                    run_id=run_id,
                    command_id="cmd-zero-work",
                )
            )
            uow.repository.insert_attempt(
                _attempt(
                    "protocol_freeze",
                    status="failed",
                    problem={
                        "code": "adapter_execution_exception",
                        "detail": "protocol_freeze adapter raised on review handoff",
                    },
                    started_at_ms=FIXED_NOW_MS + 1_000,
                    run_id=run_id,
                    command_id="cmd-zero-work",
                )
            )
            uow.repository.execute(
                "UPDATE workflow_runs SET active_node_id = 'protocol_freeze'"
                " WHERE run_id = ?",
                (run_id,),
            )
            uow.repository.insert_outbox(
                replace(
                    build_outbox_record(
                        "act-zero-work-adapter",
                        run_id=run_id,
                        command_id="cmd-zero-work",
                        action_kind="adapter_dispatch",
                        status="failed",
                    ),
                    node_run_id=f"nr-{run_id}-protocol_freeze-a1",
                    last_problem_json=json.dumps(
                        {"code": "adapter_execution_exception"}
                    ),
                )
            )
            # Receipt/cancel reconciliation work is durable bookkeeping, not a
            # workflow action capable of advancing this failed node frontier.
            uow.repository.insert_outbox(
                build_outbox_record(
                    "act-zero-work-receipt",
                    run_id=run_id,
                    command_id="cmd-zero-work",
                    action_kind="reconcile",
                    status="pending",
                )
            )

        store.submit(seed, force_flush=True).result(timeout=10)
        commands.service.submit(
            commands.request(
                command=WorkflowCommandKind.RECONCILE_RUN,
                run_id=run_id,
                node_id=None,
                expected_run_version=3,
                idempotency_key="ui:reconcile-zero-work",
            )
        )

        run = store.get_run(run_id)
        assert run.status == "blocked"
        assert run.active_node_id == "protocol_freeze"
        assert json.loads(str(run.blocked_problem_json))["code"] == (
            "adapter_execution_exception"
        )
        assert [row.action_kind for row in store.list_pending_outbox(run_id)] == [
            "reconcile"
        ]
        assert commands.wake_count == 0
    finally:
        commands.close()


def test_reconcile_compensates_completion_pending_reservation(tmp_path: Path) -> None:
    """Reconcile closes reservations stranded by completion-dependency failures.

    A terminal completion-dependency failure (defer_completion's unavailable
    branch) historically left the attempt's budget receipt 'reserved', so its
    full estimate kept occupying the stage admission window and every later
    start_node/retry_node was rejected with budget_safety_limit_reached. The
    operator reconcile path must settle such zombie reservations (observed
    usage) and leave receipts of other failure shapes untouched."""

    commands = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        run_id = "run-zombie-lock"
        zombie_node_run_id = f"nr-{run_id}-source_finding-a2"
        other_node_run_id = f"nr-{run_id}-source_extraction-a1"
        store = commands.store

        def seed(uow):
            uow.repository.insert_run(
                build_run_record(
                    workflow_version_id=_PINNED_WORKFLOW_VERSION_ID,
                    run_id=run_id,
                    status="reconciliation_required",
                    run_version=3,
                    last_event_sequence=8,
                )
            )
            uow.repository.insert_command(
                build_command_record(
                    command_id="cmd-zombie",
                    run_id=run_id,
                    idempotency_key="key:zombie",
                    node_id="source_finding",
                )
            )
            uow.repository.insert_attempt(
                _attempt(
                    "source_finding",
                    attempt=2,
                    status="running",
                    run_id=run_id,
                    command_id="cmd-zombie",
                )
            )
            uow.repository.insert_outbox(
                replace(
                    build_outbox_record(
                        "act-zombie-adapter",
                        run_id=run_id,
                        command_id="cmd-zombie",
                        action_kind="adapter_dispatch",
                        status="failed",
                    ),
                    node_run_id=zombie_node_run_id,
                    last_problem_json=json.dumps(
                        {
                            "code": COMPLETION_PENDING,
                            "dependencyStatus": "unavailable",
                        }
                    ),
                )
            )
            uow.repository.insert_budget_receipt(
                receipt_id="budget-receipt-zombie",
                run_id=run_id,
                node_run_id=zombie_node_run_id,
                reservation_id=f"reservation-{zombie_node_run_id}",
                stage_id="knowledge_collection",
                policy_hash="p-1",
                reserved_json=json.dumps(
                    {
                        "reserved": {
                            "estimatedTokens": 1_480_468,
                            "tokens": 1_480_468,
                        },
                        "limits": {"tokens": 2_000_000},
                    }
                ),
                created_at_ms=FIXED_NOW_MS,
            )
            uow.repository.update_budget_receipt(
                "budget-receipt-zombie",
                status="reserved",
                now_ms=FIXED_NOW_MS,
                settled_json=json.dumps(
                    {
                        "usage": {"tokens": 1_066_138},
                        "invocations": {"i1": {"tokens": 1_066_138}},
                    }
                ),
            )
            # 反例：非 completion-pending 的 failed act + running attempt
            # 的预留不得被 reconcile 触碰。
            uow.repository.insert_attempt(
                _attempt(
                    "source_extraction",
                    status="running",
                    run_id=run_id,
                    command_id="cmd-zombie",
                )
            )
            uow.repository.insert_outbox(
                replace(
                    build_outbox_record(
                        "act-other-adapter",
                        run_id=run_id,
                        command_id="cmd-zombie",
                        action_kind="adapter_dispatch",
                        status="failed",
                    ),
                    node_run_id=other_node_run_id,
                    last_problem_json=json.dumps(
                        {"code": "adapter_execution_exception"}
                    ),
                )
            )
            uow.repository.insert_budget_receipt(
                receipt_id="budget-receipt-other",
                run_id=run_id,
                node_run_id=other_node_run_id,
                reservation_id=f"reservation-{other_node_run_id}",
                stage_id="knowledge_collection",
                policy_hash="p-1",
                reserved_json=json.dumps(
                    {"reserved": {"estimatedTokens": 300_000, "tokens": 300_000}}
                ),
                created_at_ms=FIXED_NOW_MS,
            )

        store.submit(seed, force_flush=True).result(timeout=10)
        commands.service.submit(
            commands.request(
                command=WorkflowCommandKind.RECONCILE_RUN,
                run_id=run_id,
                node_id=None,
                expected_run_version=3,
                idempotency_key="ui:reconcile-zombie",
            )
        )

        def receipt_status(reservation_id: str) -> str:
            return store.submit(
                lambda uow: uow.repository.execute(
                    "SELECT status FROM budget_receipts WHERE reservation_id = ?",
                    (reservation_id,),
                ).fetchone(),
                force_flush=True,
            ).result(timeout=10)[0]

        assert receipt_status(f"reservation-{zombie_node_run_id}") == "settled"
        assert receipt_status(f"reservation-{other_node_run_id}") == "reserved"

        blocked_events = [
            event
            for event in store.list_events(run_id)
            if event.event_type == "run_blocked"
        ]
        payload = json.loads(blocked_events[-1].payload_json)
        assert {
            "runId": run_id,
            "nodeRunId": zombie_node_run_id,
            "result": "settled",
        } in payload["compensatedReservations"]
    finally:
        commands.close()


def test_reconcile_compensates_zombie_reservation_in_knowledge_child_run(
    tmp_path: Path,
) -> None:
    """Reconciling the main run must also close child-run zombie reservations.

    Real acceptance (run-332a539909a6 / run-1ca97605acf3) found the zombie in
    a knowledge sideflow child run, whose reconcile_run offer has no frontend
    entry at all: the knowledge-node offer whitelist only exposes
    ensure/inspect, and only the main formal run panel carries the
    reconcile button. Unless the parent-run reconcile compensates the child
    run's stranded reservation in the same transaction, the stage admission
    window stays locked with no operable path out."""

    commands = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        run_id = "run-parent-reconcile"
        child_run_id = "run-knowledge-child"
        child_node_run_id = f"nr-{child_run_id}-source_finding-a1"
        parent_node_run_id = f"nr-{run_id}-hypothesis_design-a1"
        store = commands.store

        def seed(uow):
            uow.repository.insert_run(
                build_run_record(
                    workflow_version_id=_PINNED_WORKFLOW_VERSION_ID,
                    run_id=run_id,
                    status="reconciliation_required",
                    run_version=3,
                    last_event_sequence=8,
                )
            )
            # 知识 sideflow 子 run（challenge-cup-knowledge-sideflow 定义）。
            uow.repository.insert_run(
                build_run_record(
                    workflow_version_id=_PINNED_WORKFLOW_VERSION_ID,
                    run_id=child_run_id,
                    status="running",
                    run_version=2,
                    last_event_sequence=4,
                    parent_run_id=run_id,
                )
            )
            uow.repository.insert_command(
                build_command_record(
                    command_id="cmd-parent",
                    run_id=run_id,
                    idempotency_key="key:parent",
                    node_id="hypothesis_design",
                )
            )
            uow.repository.insert_command(
                build_command_record(
                    command_id="cmd-child",
                    run_id=child_run_id,
                    idempotency_key="key:child",
                    node_id="source_finding",
                )
            )
            uow.repository.insert_knowledge_invocation(
                KnowledgeInvocationRecord(
                    invocation_id="ki-child-zombie",
                    parent_run_id=run_id,
                    parent_node_id="hypothesis_design",
                    parent_node_run_id=parent_node_run_id,
                    parent_attempt=1,
                    question_id="SCI-096",
                    scope_hash="scope",
                    request_hash="req-child-zombie",
                    search_envelope_hash="env",
                    requirements_hash="req-hash",
                    source_policy_version="v1",
                    knowledge_child_run_id=child_run_id,
                    status="running",
                    knowledge_package_ref=None,
                    package_content_hash=None,
                    handoff_state="pending",
                    error_json=None,
                    created_at_ms=FIXED_NOW_MS - 1_000,
                    updated_at_ms=FIXED_NOW_MS,
                )
            )
            # 反例：父 run 自身只有一个非 completion-pending 的 failed
            # adapter_dispatch + running attempt，扫描不得为它产生条目。
            uow.repository.insert_attempt(
                _attempt(
                    "hypothesis_design",
                    status="running",
                    run_id=run_id,
                    command_id="cmd-parent",
                )
            )
            uow.repository.insert_outbox(
                replace(
                    build_outbox_record(
                        "act-parent-adapter",
                        run_id=run_id,
                        command_id="cmd-parent",
                        action_kind="adapter_dispatch",
                        status="failed",
                    ),
                    node_run_id=parent_node_run_id,
                    last_problem_json=json.dumps(
                        {"code": "adapter_execution_exception"}
                    ),
                )
            )
            # 子 run 的僵尸：running attempt + COMPLETION_PENDING failed act
            # + 满额 reserved budget receipt。
            uow.repository.insert_attempt(
                _attempt(
                    "source_finding",
                    status="running",
                    run_id=child_run_id,
                    command_id="cmd-child",
                )
            )
            uow.repository.insert_outbox(
                replace(
                    build_outbox_record(
                        "act-child-adapter",
                        run_id=child_run_id,
                        command_id="cmd-child",
                        action_kind="adapter_dispatch",
                        status="failed",
                    ),
                    node_run_id=child_node_run_id,
                    last_problem_json=json.dumps(
                        {
                            "code": COMPLETION_PENDING,
                            "dependencyStatus": "unavailable",
                        }
                    ),
                )
            )
            uow.repository.insert_budget_receipt(
                receipt_id="budget-receipt-child-zombie",
                run_id=child_run_id,
                node_run_id=child_node_run_id,
                reservation_id=f"reservation-{child_node_run_id}",
                stage_id="knowledge_collection",
                policy_hash="p-1",
                reserved_json=json.dumps(
                    {
                        "reserved": {
                            "estimatedTokens": 1_480_468,
                            "tokens": 1_480_468,
                        },
                        "limits": {"tokens": 2_000_000},
                    }
                ),
                created_at_ms=FIXED_NOW_MS,
            )
            uow.repository.update_budget_receipt(
                "budget-receipt-child-zombie",
                status="reserved",
                now_ms=FIXED_NOW_MS,
                settled_json=json.dumps(
                    {
                        "usage": {"tokens": 1_066_138},
                        "invocations": {"i1": {"tokens": 1_066_138}},
                    }
                ),
            )

        store.submit(seed, force_flush=True).result(timeout=10)
        commands.service.submit(
            commands.request(
                command=WorkflowCommandKind.RECONCILE_RUN,
                run_id=run_id,
                node_id=None,
                expected_run_version=3,
                idempotency_key="ui:reconcile-parent",
            )
        )

        child_status = store.submit(
            lambda uow: uow.repository.execute(
                "SELECT status FROM budget_receipts WHERE reservation_id = ?",
                (f"reservation-{child_node_run_id}",),
            ).fetchone(),
            force_flush=True,
        ).result(timeout=10)[0]
        assert child_status == "settled"

        blocked_events = [
            event
            for event in store.list_events(run_id)
            if event.event_type == "run_blocked"
        ]
        payload = json.loads(blocked_events[-1].payload_json)
        assert {
            "runId": child_run_id,
            "nodeRunId": child_node_run_id,
            "result": "settled",
        } in payload["compensatedReservations"]
        # 父 run 自身无 completion-pending 僵尸：不产生额外条目。
        assert all(
            entry.get("runId") == child_run_id
            for entry in payload["compensatedReservations"]
        )
    finally:
        commands.close()
