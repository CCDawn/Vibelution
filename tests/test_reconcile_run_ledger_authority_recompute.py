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
  evaluator-authored ``auto_advance_not_ready``/``evidence_graph_incomplete``
  verdict and the V2 ``retry-formal-node:…:evidence_relations`` rerun action;
- no more reconcile death loop: no revived dispatch remains for the worker to
  re-fail;
- the plain-drift repair contract from 97e227263 still revives unrelated
  failed rows.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from core.research.workflow.contracts import WorkflowCommandKind
from core.research.workflow.definition import build_challenge_cup_workflow_definition
from core.web.services.team_workflow.research_runtime.command_offers.reconcile_run import (
    build_reconcile_run_offer,
)
from core.web.services.team_workflow.research_runtime.command_offers.retry_node import (
    build_retry_node_offers,
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

_INGESTION_PROBLEM = {
    "code": EVALUATOR_BLOCK_CODE,
    "detail": "evidence_graph_incomplete",
}
_MISMATCH_PROBLEM = {
    "code": "checkpoint_node_mismatch",
    "detail": "thread 中断于 knowledge_handoff，但 dispatch 目标是 source_finding",
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
    """run-d02722658d8b ledger facts, in start-time order."""
    base = FIXED_NOW_MS - 10_000
    step = 1_000
    return [
        _attempt("problem_understanding", status="succeeded", started_at_ms=base + 0 * step, run_id=run_id),
        _attempt("source_finding", attempt=5, status="succeeded", started_at_ms=base + 1 * step, run_id=run_id),
        _attempt("source_extraction", status="succeeded", started_at_ms=base + 2 * step, run_id=run_id),
        _attempt("evidence_relations", attempt=2, status="succeeded", started_at_ms=base + 3 * step, run_id=run_id),
        # Auto-advance readied this successor; readiness blocked it. Real gate.
        _attempt(
            "knowledge_ingestion",
            status="blocked",
            problem=_INGESTION_PROBLEM,
            started_at_ms=base + 4 * step,
            run_id=run_id,
        ),
        # Late operator-misassigned retry behind the covered frontier.
        _attempt(
            "source_finding",
            attempt=6,
            status="blocked",
            problem=_MISMATCH_PROBLEM,
            started_at_ms=base + 6 * step,
            run_id=run_id,
        ),
    ]


def test_plan_supersedes_covered_incident_block_only() -> None:
    plan = plan_ledger_authority(production_shape_attempts(), node_order=NODE_ORDER)

    assert plan.superseded_node_run_ids == ("nr-run-test-source_finding-a6",)
    assert plan.lands_blocked is True
    assert plan.active_node_id == "knowledge_ingestion"
    assert dict(plan.landing_problem or {}) == _INGESTION_PROBLEM


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
        _attempt("evidence_relations", status="succeeded", started_at_ms=base),
        _attempt(
            "knowledge_ingestion",
            attempt=1,
            status="blocked",
            problem=_INGESTION_PROBLEM,
            started_at_ms=base + 1_000,
        ),
        _attempt(
            "source_finding",
            attempt=6,
            status="blocked",
            problem=_MISMATCH_PROBLEM,
            started_at_ms=base + 2_000,
        ),
    ]

    plan = plan_ledger_authority(attempts, node_order=NODE_ORDER)

    assert plan.superseded_node_run_ids == ("nr-run-test-source_finding-a6",)
    assert plan.lands_blocked is True
    assert plan.active_node_id == "knowledge_ingestion"
    assert dict(plan.landing_problem or {}) == _INGESTION_PROBLEM


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
                node_id="evidence_relations",
            )
        )
        uow.repository.insert_command(
            build_command_record(
                command_id="cmd-a6",
                run_id=run_id,
                idempotency_key="key:a6",
                node_id="source_finding",
            )
        )
        for attempt in production_shape_attempts(run_id):
            uow.repository.insert_attempt(attempt)
        uow.repository.execute(
            """
            UPDATE workflow_runs
            SET active_node_id = 'source_finding',
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
                    "act-source-finding-a6-dead",
                    run_id=run_id,
                    command_id="cmd-a6",
                    idempotency_key="graph:resume:act-source-finding-a6",
                    status="failed",
                ),
                node_run_id=f"nr-{run_id}-source_finding-a6",
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
    from core.web.services.team_workflow.research_runtime.hypothesis_first_state_v2 import (
        project_state_from_records,
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
        assert run.active_node_id == "knowledge_ingestion"
        assert json.loads(str(run.blocked_problem_json)) == _INGESTION_PROBLEM

        # 脏 attempt 被判 stale；其失败 dispatch 不再复活（断开死循环）。
        stale = commands.store.submit(
            lambda uow: [
                row.status
                for row in uow.repository.list_attempts("run-test")
                if row.node_run_id == "nr-run-test-source_finding-a6"
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
        dead_row = [row for row in outbox_rows if row[0] == "act-source-finding-a6-dead"]
        assert not dead_row or dead_row[0][1] != "pending"
        # 没有任何复活：worker 无需被唤醒。
        assert commands.wake_count == 0

        # V2 allowedActions 出现可用的重跑证据关系入口。
        refreshed = commands.store.get_run("run-test")
        definition = build_challenge_cup_workflow_definition()
        attempts = commands.store.list_attempts("run-test")
        offers = build_retry_node_offers(
            run=refreshed, definition=definition, attempts=attempts
        )
        rel_offer = next(o for o in offers if o.node_id == "evidence_relations")
        assert rel_offer.available is True
        actions = _formal_actions_from_offers(
            run_id="run-test",
            run_version=refreshed.run_version,
            offers=[*offers, build_reconcile_run_offer(run=refreshed)],
        )
        retry = next(
            a
            for a in actions
            if a.command == "retry_formal_node"
            and getattr(a.payload, "nodeId", None) == "evidence_relations"
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
        assert run.active_node_id == "knowledge_ingestion"
    finally:
        commands.close()


def test_plain_drift_reconcile_still_revives_live_rows(tmp_path: Path) -> None:
    """97e227263 的常规漂移形态保持原契约：复活 running 所需的 dispatch。"""
    commands = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        record = build_run_record(
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
