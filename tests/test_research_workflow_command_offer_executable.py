"""T6.6B/C/D: available CommandOffers must be executable as signed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.research.workflow.contracts import WorkflowCommandKind
from core.research.workflow.definition import build_challenge_cup_workflow_definition
from core.research.workflow.definition_registry import register_or_resolve
from core.research.workflow.transitions import RunStatus
from core.web.services.team_workflow.research_runtime.command_offers import (
    build_command_offers,
)
from core.web.services.team_workflow.research_runtime.command_offers.cancel_run import (
    build_cancel_run_offer,
)
from core.web.services.team_workflow.research_runtime.query_service import (
    WorkflowQueryService,
)
from core.web.services.team_workflow.research_runtime.command_service import (
    WorkflowCommandError,
)
from tests._support.command_helpers import CommandHarness
from tests._support.readiness_fakes import FakeDomainContext
from tests._support.workflow_ledger_helpers import (
    FIXED_NOW_MS,
    build_attempt_record,
    build_command_record,
)


FIXED_GENERATED_AT = "2026-08-12T14:00:00.000Z"


def _query(harness: CommandHarness) -> WorkflowQueryService:
    return WorkflowQueryService(
        store=harness.store,
        readiness_service=harness.readiness,
        readiness_context=lambda: harness.context,
        clock_iso=lambda: FIXED_GENERATED_AT,
        evaluated_at_ms=lambda: FIXED_NOW_MS,
    )


@pytest.mark.parametrize("status", [item.value for item in RunStatus])
def test_cancel_offer_matches_transition_authority(status: str) -> None:
    from tests._support.workflow_ledger_helpers import build_run_record

    run = build_run_record(run_id="run-cancel", status=status, run_version=3)
    offer = build_cancel_run_offer(run=run)
    if status in {
        RunStatus.SUCCEEDED.value,
        RunStatus.FAILED.value,
        RunStatus.CANCELLED.value,
        RunStatus.ARCHIVED.value,
    }:
        assert offer.available is False
    else:
        assert offer.available is True


def _seed_waiting_human_run(harness: CommandHarness, run_id: str = "run-revise") -> None:
    harness.seed_run(run_id=run_id, status="waiting_human", run_version=1)

    def seed_human(uow):
        uow.repository.insert_command(
            build_command_record(
                command_id=f"cmd-{run_id}",
                run_id=run_id,
                node_id="knowledge_handoff",
                command_kind="start_node",
                idempotency_key=f"seed-{run_id}",
            )
        )
        uow.repository.insert_attempt(
            build_attempt_record(
                node_run_id=f"nr-{run_id}-1",
                run_id=run_id,
                node_id="knowledge_handoff",
                actor_kind="human",
                status="waiting_human",
                command_id=f"cmd-{run_id}",
            )
        )
        uow.repository.insert_human_task(
            task_id=f"ht-{run_id}",
            run_id=run_id,
            node_run_id=f"nr-{run_id}-1",
            handoff_id=None,
            task_kind="knowledge_gate",
            prompt_json="{}",
            created_at_ms=FIXED_NOW_MS,
        )

    harness.store.submit(seed_human, force_flush=True).result(timeout=10)


def test_root_run_revise_offer_uses_latest_thread_checkpoint(tmp_path: Path) -> None:
    """Root runs gain a usable revise decision when the caller resolves the
    thread's latest checkpoint (P1-4: revise was structurally unavailable)."""
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_waiting_human_run(harness)
        query = WorkflowQueryService(
            store=harness.store,
            readiness_service=harness.readiness,
            readiness_context=lambda: harness.context,
            clock_iso=lambda: FIXED_GENERATED_AT,
            evaluated_at_ms=lambda: FIXED_NOW_MS,
            revise_checkpoint_resolver=lambda thread_id: "ckpt-latest-1",
        )
        snap = query.get_snapshot(team_id="research-team", run_id="run-revise")
        revise = [
            offer
            for offer in snap.command_offers
            if offer.command == WorkflowCommandKind.RESOLVE_HUMAN_TASK
            and offer.payload.get("decision") == "revise"
        ]
        assert revise and revise[0].available is True
        assert revise[0].payload.get("checkpointId") == "ckpt-latest-1"
        fork = [
            offer
            for offer in snap.command_offers
            if offer.command == WorkflowCommandKind.FORK_REVISION
        ]
        assert fork and fork[0].available is True
        assert fork[0].payload.get("checkpointId") == "ckpt-latest-1"
    finally:
        harness.close()


def test_revise_checkpoint_resolver_failure_fails_soft(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_waiting_human_run(harness)
        query = WorkflowQueryService(
            store=harness.store,
            readiness_service=harness.readiness,
            readiness_context=lambda: harness.context,
            clock_iso=lambda: FIXED_GENERATED_AT,
            evaluated_at_ms=lambda: FIXED_NOW_MS,
            revise_checkpoint_resolver=lambda thread_id: (_ for _ in ()).throw(
                RuntimeError("checkpoint store unavailable")
            ),
        )
        snap = query.get_snapshot(team_id="research-team", run_id="run-revise")
        revise = [
            offer
            for offer in snap.command_offers
            if offer.command == WorkflowCommandKind.RESOLVE_HUMAN_TASK
            and offer.payload.get("decision") == "revise"
        ]
        assert revise and revise[0].available is False
        assert "revise_checkpoint_unavailable" in revise[0].blocker_ids
    finally:
        harness.close()


def test_human_resolve_offers_are_decision_complete(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(run_id="run-human", status="waiting_human", run_version=1)

        def seed_human(uow):
            uow.repository.insert_command(
                build_command_record(
                    command_id="cmd-human",
                    run_id="run-human",
                    node_id="knowledge_handoff",
                    command_kind="start_node",
                    idempotency_key="seed-human",
                )
            )
            uow.repository.insert_attempt(
                build_attempt_record(
                    node_run_id="nr-human-1",
                    run_id="run-human",
                    node_id="knowledge_handoff",
                    actor_kind="human",
                    status="waiting_human",
                    command_id="cmd-human",
                )
            )
            uow.repository.insert_human_task(
                task_id="ht-kh-1",
                run_id="run-human",
                node_run_id="nr-human-1",
                handoff_id=None,
                task_kind="knowledge_gate",
                prompt_json="{}",
                created_at_ms=FIXED_NOW_MS,
            )

        harness.store.submit(seed_human, force_flush=True).result(timeout=10)

        snap = _query(harness).get_snapshot(team_id="research-team", run_id="run-human")
        resolve_offers = [
            offer
            for offer in snap.command_offers
            if offer.command == WorkflowCommandKind.RESOLVE_HUMAN_TASK
            and offer.node_id == "knowledge_handoff"
        ]
        decisions = {
            str(offer.payload.get("decision"))
            for offer in resolve_offers
            if offer.available
        }
        assert "accept" in decisions
        assert "reject" in decisions
        revise = [
            offer
            for offer in resolve_offers
            if offer.payload.get("decision") == "revise"
        ]
        assert revise and revise[0].available is False
        assert "revise_checkpoint_unavailable" in revise[0].blocker_ids

        accept = next(
            offer
            for offer in resolve_offers
            if offer.available and offer.payload.get("decision") == "accept"
        )
        receipt = harness.service.submit(
            harness.request(
                run_id="run-human",
                command=accept.command,
                node_id=accept.node_id,
                expected_run_version=accept.expected_run_version,
                idempotency_key=accept.idempotency_key,
                payload=dict(accept.payload),
            )
        )
        assert receipt.status == "accepted"
    finally:
        harness.close()


def test_blocked_human_gate_exposes_executable_retry_offer(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(run_id="run-human-blocked", status="blocked", run_version=1)

        def seed_blocked_human(uow):
            uow.repository.insert_command(
                build_command_record(
                    command_id="cmd-human-blocked",
                    run_id="run-human-blocked",
                    node_id="knowledge_handoff",
                    command_kind="start_node",
                    idempotency_key="seed-human-blocked",
                )
            )
            uow.repository.insert_attempt(
                build_attempt_record(
                    node_run_id="nr-human-blocked-a1",
                    run_id="run-human-blocked",
                    node_id="knowledge_handoff",
                    actor_kind="human",
                    status="blocked",
                    command_id="cmd-human-blocked",
                    attempt=1,
                )
            )

        harness.store.submit(seed_blocked_human, force_flush=True).result(timeout=10)

        snap = _query(harness).get_snapshot(
            team_id="research-team", run_id="run-human-blocked"
        )
        retry = next(
            offer
            for offer in snap.command_offers
            if offer.command == WorkflowCommandKind.RETRY_NODE
            and offer.node_id == "knowledge_handoff"
        )
        assert retry.available is True
        assert retry.reason_code == "retry_available"

        receipt = harness.service.submit(
            harness.request(
                run_id="run-human-blocked",
                command=retry.command,
                node_id=retry.node_id,
                expected_run_version=retry.expected_run_version,
                idempotency_key=retry.idempotency_key,
                payload=dict(retry.payload),
            )
        )
        assert receipt.status == "accepted"
        latest = harness.store.latest_attempt("run-human-blocked", "knowledge_handoff")
        assert latest is not None
        assert latest.attempt == 2
        assert latest.status == "starting"
    finally:
        harness.close()


def test_all_available_snapshot_offers_are_executable(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3", context=FakeDomainContext())
    try:
        harness.seed_run(run_id="run-all", status="created", run_version=1)
        query = _query(harness)
        # Execute every available Offer as signed (exact key/payload/version).
        # Cap iterations to avoid unbounded cancel↔extend churn.
        for _ in range(32):
            snap = query.get_snapshot(team_id="research-team", run_id="run-all")
            available = [offer for offer in snap.command_offers if offer.available]
            if not available:
                break
            offer = available[0]
            receipt = harness.service.submit(
                harness.request(
                    run_id="run-all",
                    command=offer.command,
                    node_id=offer.node_id,
                    expected_run_version=offer.expected_run_version,
                    idempotency_key=offer.idempotency_key,
                    payload=dict(offer.payload),
                )
            )
            assert receipt.status == "accepted", (offer.command, offer.payload, receipt)
        else:
            pytest.fail("available offers did not drain within iteration budget")
    finally:
        harness.close()


def test_offer_builder_covers_required_command_kinds(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(run_id="run-cov")
        run = harness.store.get_run("run-cov")
        assert run is not None
        offers = build_command_offers(
            readiness_service=harness.readiness,
            context=harness.context,
            team_id=run.team_id,
            run=run,
            definition=build_challenge_cup_workflow_definition(),
            pending_human_tasks=(),
            attempts=(),
        )
        kinds = {offer.command for offer in offers}
        for required in (
            WorkflowCommandKind.START_NODE,
            WorkflowCommandKind.RESOLVE_HUMAN_TASK,
            WorkflowCommandKind.CANCEL_RUN,
            WorkflowCommandKind.RETRY_NODE,
            WorkflowCommandKind.REBIND_NODE,
            WorkflowCommandKind.FORK_REVISION,
            WorkflowCommandKind.EXTEND_BUDGET,
            WorkflowCommandKind.RECONCILE_RUN,
        ):
            assert required in kinds
    finally:
        harness.close()


@pytest.mark.parametrize(
    "limits",
    [
        {},
        {"toolCalls": 600},
        {"toolCalls": 0},
        {"toolCalls": -1},
        {"toolCalls": True},
        {"stageTokens": {}},
        {"stageTokens": {"knowledge_collection": 2_000_000}},
        {"stageTokens": {"knowledge_collection": 0}},
        {"unknownLimit": 1},
    ],
)
def test_extend_budget_rejects_empty_invalid_or_non_increasing_limits(
    tmp_path: Path,
    limits: dict,
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        harness.store.submit(
            lambda uow: uow.repository.update_run_safety_limits(
                "run-test",
                "research-team",
                json.dumps(
                {
                    "stageTokens": {"knowledge_collection": 2_000_000},
                    "toolCalls": 600,
                    "wallClockSeconds": 14_400,
                    "maxRetries": 3,
                }
                ),
                FIXED_NOW_MS,
            ),
            force_flush=True,
        ).result(timeout=10)
        with pytest.raises(WorkflowCommandError, match="budget"):
            harness.service.submit(
                harness.request(
                    command=WorkflowCommandKind.EXTEND_BUDGET,
                    node_id=None,
                    payload={"limits": limits},
                )
            )
        run = harness.store.get_run("run-test")
        assert run is not None
        assert run.run_version == 1
    finally:
        harness.close()


def test_extend_budget_merges_one_concrete_monotonic_extension(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        harness.store.submit(
            lambda uow: uow.repository.update_run_safety_limits(
                "run-test",
                "research-team",
                json.dumps(
                {
                    "stageTokens": {
                        "knowledge_collection": 2_000_000,
                        "experiment_design": 2_000_000,
                    },
                    "toolCalls": 600,
                    "wallClockSeconds": 14_400,
                    "maxRetries": 3,
                }
                ),
                FIXED_NOW_MS,
            ),
            force_flush=True,
        ).result(timeout=10)
        receipt = harness.service.submit(
            harness.request(
                command=WorkflowCommandKind.EXTEND_BUDGET,
                node_id=None,
                payload={
                    "limits": {
                        "stageTokens": {"knowledge_collection": 2_500_000},
                        "toolCalls": 700,
                    }
                },
            )
        )
        assert receipt.status == "accepted"
        run = harness.store.get_run("run-test")
        assert run is not None
        assert json.loads(run.safety_limits_json) == {
            "stageTokens": {
                "knowledge_collection": 2_500_000,
                "experiment_design": 2_000_000,
            },
            "toolCalls": 700,
            "wallClockSeconds": 14_400,
            "maxRetries": 3,
        }
    finally:
        harness.close()


def test_start_offer_payload_carries_blocker_wording(tmp_path: Path) -> None:
    """The UI's disabled reason must come from the blocker itself, not a
    frontend guess keyed on the coarse reason code."""
    from types import SimpleNamespace

    from core.research.workflow.contracts.node_readiness import ReadinessBlocker
    from core.research.workflow.contracts.workflow_problem import (
        Remediation,
        RemediationKind,
    )
    from core.web.services.team_workflow.research_runtime.command_offers import (
        start_node as start_offers,
    )

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(run_id="run-blocker-wording")
        run = harness.store.get_run("run-blocker-wording")
        assert run is not None

        blocker = ReadinessBlocker(
            code="hypothesis_first_meeting_open",
            title="评审缺少资料缺口请求",
            detail="假说评审已全部闭环，但没有任何一轮决策携带资料缺口请求",
            remediation=Remediation(
                kind=RemediationKind.RESOLVE_HUMAN,
                label="再开一轮评审，让团队提出资料缺口（证据请求）",
            ),
        )

        class _StubReadiness:
            def evaluate(self, **_kwargs):
                return SimpleNamespace(ready=False, blockers=(blocker,))

        offers = start_offers.build_start_node_offers(
            readiness_service=_StubReadiness(),  # type: ignore[arg-type]
            context=harness.context,
            team_id=run.team_id,
            run=run,
            definition=build_challenge_cup_workflow_definition(),
        )
        blocked = next(
            offer
            for offer in offers
            if offer.command == WorkflowCommandKind.START_NODE
            and offer.node_id == "source_finding"
        )
        assert blocked.available is False
        assert blocked.payload.get("remediation_label") == (
            "再开一轮评审，让团队提出资料缺口（证据请求）"
        )
        assert blocked.payload.get("blocker_title") == "评审缺少资料缺口请求"
        assert "资料缺口请求" in str(blocked.payload.get("blocker_detail"))
    finally:
        harness.close()


def _seed_finding_rerun_run(
    harness: CommandHarness,
    *,
    run_id: str,
    run_status: str,
    blocked_problem_json: str | None,
    attempt_status: str,
) -> None:
    """Seed a run plus one source_finding attempt in one ledger transaction."""

    import json as _json
    from dataclasses import replace

    from tests._support.workflow_ledger_helpers import (
        build_attempt_record,
        build_command_record,
        build_event_record,
        build_run_record,
    )

    identity = register_or_resolve(build_challenge_cup_workflow_definition())
    run = replace(
        build_run_record(
            run_id=run_id,
            status=run_status,
            run_version=2,
            last_event_sequence=1,
            workflow_version_id=identity.workflowVersionId,
        ),
        structure_hash=identity.structureHash,
        blocked_problem_json=blocked_problem_json,
    )

    def mutate(uow):
        uow.repository.insert_run(run)
        uow.repository.insert_event(
            build_event_record(
                sequence=1,
                run_id=run_id,
                event_type="run_created",
                event_id=f"evt-created-{run_id}",
            )
        )
        uow.repository.insert_command(
            build_command_record(
                command_id=f"cmd-{run_id}-a1",
                run_id=run_id,
                node_id="source_finding",
                command_kind="start_node",
                idempotency_key=f"seed-{run_id}",
            )
        )
        uow.repository.insert_attempt(
            build_attempt_record(
                node_run_id=f"nr-{run_id}-a1",
                run_id=run_id,
                node_id="source_finding",
                status=attempt_status,
                command_id=f"cmd-{run_id}-a1",
                attempt=1,
            )
        )

    harness.store.submit(mutate, force_flush=True).result(timeout=10)


def test_succeeded_finding_rerun_offer_available_and_executable(
    tmp_path: Path,
) -> None:
    """A restart can kill the agent turn after the ledger already marked
    source_finding succeeded, leaving the candidate store empty and the run
    blocked on source_candidates_missing.  Re-running the idempotent finding
    stage is the only recovery, so its retry offer must be available and
    executable as signed."""
    import json as _json

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_finding_rerun_run(
            harness,
            run_id="run-finding-rerun",
            run_status="blocked",
            blocked_problem_json=_json.dumps(
                {"code": "auto_advance_not_ready", "detail": "source_candidates_missing"}
            ),
            attempt_status="succeeded",
        )

        snap = _query(harness).get_snapshot(
            team_id="research-team", run_id="run-finding-rerun"
        )
        retry = next(
            offer
            for offer in snap.command_offers
            if offer.command == WorkflowCommandKind.RETRY_NODE
            and offer.node_id == "source_finding"
        )
        assert retry.available is True
        assert retry.label == "重跑 资料寻找"

        receipt = harness.service.submit(
            harness.request(
                run_id="run-finding-rerun",
                command=retry.command,
                node_id=retry.node_id,
                expected_run_version=retry.expected_run_version,
                idempotency_key=retry.idempotency_key,
                payload=dict(retry.payload),
            )
        )
        assert receipt.status == "accepted"
        latest = harness.store.latest_attempt("run-finding-rerun", "source_finding")
        assert latest is not None
        assert latest.attempt == 2
        assert latest.status == "starting"
    finally:
        harness.close()


def test_succeeded_finding_rerun_offer_unavailable_on_healthy_run(
    tmp_path: Path,
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_finding_rerun_run(
            harness,
            run_id="run-finding-healthy",
            run_status="running",
            blocked_problem_json=None,
            attempt_status="succeeded",
        )

        snap = _query(harness).get_snapshot(
            team_id="research-team", run_id="run-finding-healthy"
        )
        retry = next(
            offer
            for offer in snap.command_offers
            if offer.command == WorkflowCommandKind.RETRY_NODE
            and offer.node_id == "source_finding"
        )
        assert retry.available is False
    finally:
        harness.close()


def test_succeeded_node_rerun_available_requires_blocker_gap() -> None:
    """Only the whitelisted idempotent node blocked on its own missing
    artifacts may re-run after success; every other combination stays under
    the strict non-retryable contract."""
    import json as _json
    from dataclasses import replace

    from core.web.services.team_workflow.research_runtime.command_offers.retry_node import (
        succeeded_node_rerun_available,
    )
    from tests._support.workflow_ledger_helpers import (
        build_attempt_record,
        build_run_record,
    )

    run = replace(
        build_run_record(status="blocked"),
        blocked_problem_json=_json.dumps(
            {"code": "auto_advance_not_ready", "detail": "source_candidates_missing"}
        ),
    )
    latest = build_attempt_record(node_id="source_finding", status="succeeded")
    assert succeeded_node_rerun_available(
        node_id="source_finding", latest=latest, run=run
    )

    blocked_problem_cases = (
        None,
        "",
        "not-json",
        _json.dumps({"code": "auto_advance_not_ready", "detail": "other_gap"}),
        _json.dumps({"code": "other_code", "detail": "source_candidates_missing"}),
    )
    for problem_json in blocked_problem_cases:
        assert not succeeded_node_rerun_available(
            node_id="source_finding",
            latest=latest,
            run=replace(run, blocked_problem_json=problem_json),
        ), problem_json

    assert not succeeded_node_rerun_available(
        node_id="source_extraction", latest=latest, run=run
    )
    assert not succeeded_node_rerun_available(
        node_id="source_finding",
        latest=build_attempt_record(node_id="source_finding", status="running"),
        run=run,
    )
    assert not succeeded_node_rerun_available(
        node_id="source_finding",
        latest=latest,
        run=build_run_record(status="running"),
    )
    assert not succeeded_node_rerun_available(
        node_id="source_finding", latest=None, run=run
    )


def test_succeeded_node_rerun_available_heals_evidence_graph_gap() -> None:
    """A succeeded evidence_relations node re-runs only when the run is
    blocked on evidence_graph_incomplete (dangling relation edges materialized
    into missingLinks); the mapping target is exclusive to that detail."""
    import json as _json
    from dataclasses import replace

    from core.web.services.team_workflow.research_runtime.command_offers.retry_node import (
        succeeded_node_rerun_available,
    )
    from tests._support.workflow_ledger_helpers import (
        build_attempt_record,
        build_run_record,
    )

    run = replace(
        build_run_record(status="blocked"),
        blocked_problem_json=_json.dumps(
            {"code": "auto_advance_not_ready", "detail": "evidence_graph_incomplete"}
        ),
    )
    latest = build_attempt_record(node_id="evidence_relations", status="succeeded")
    assert succeeded_node_rerun_available(
        node_id="evidence_relations", latest=latest, run=run
    )

    assert not succeeded_node_rerun_available(
        node_id="source_extraction", latest=latest, run=run
    )
    assert not succeeded_node_rerun_available(
        node_id="evidence_relations",
        latest=build_attempt_record(node_id="evidence_relations", status="failed"),
        run=run,
    )
    assert not succeeded_node_rerun_available(
        node_id="evidence_relations",
        latest=latest,
        run=replace(
            run,
            blocked_problem_json=_json.dumps(
                {"code": "auto_advance_not_ready", "detail": "source_candidates_missing"}
            ),
        ),
    )
