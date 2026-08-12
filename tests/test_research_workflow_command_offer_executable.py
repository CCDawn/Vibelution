"""T6.6B/C/D: available CommandOffers must be executable as signed."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.research.workflow.contracts import WorkflowCommandKind
from core.research.workflow.definition import build_challenge_cup_workflow_definition
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
