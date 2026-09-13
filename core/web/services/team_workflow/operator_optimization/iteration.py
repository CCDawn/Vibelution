"""Durable post-feedback iteration over native outbox and command services."""

from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace

from core.research.workflow.contracts import (
    ActorRef,
    CommandRequest,
    WorkflowCommandKind,
)
from core.research.workflow.ledger import OutboxRecord
from core.research.workflow.contracts._canonical import sha256_hex

from ..research_runtime.formal_write_runtime import get_command_service
from ..storage_durability import inter_process_lock
from .budget import budget_summary
from .model_budget import _campaign_committed_amounts, calculate_max_reserved_cost
from .knowledge import read_ref
from .rounds import prepare_round
from .store import CampaignConflict, campaign_root, read_campaign

EVENT = "operator_round_completed"


def enqueue_iteration(uow, *, run, now_ms):
    key = "operator-next-round:" + run.run_id
    if uow.repository.execute(
        "SELECT action_id FROM outbox_actions WHERE idempotency_key=?", (key,)
    ).fetchone():
        return
    attempt = uow.repository.latest_attempt(run.run_id, "optimization_feedback")
    if attempt is None or not attempt.command_id:
        raise CampaignConflict("Iteration requires the native feedback command")
    uow.repository.insert_outbox(
        OutboxRecord(
            action_id="act-" + sha256_hex(key)[:24],
            run_id=run.run_id,
            command_id=attempt.command_id,
            node_run_id=attempt.node_run_id,
            action_kind="event_publish",
            idempotency_key=key,
            payload_json=json.dumps(
                {"eventType": EVENT, "runId": run.run_id, "teamId": run.team_id}
            ),
            status="pending",
            attempt_count=0,
            available_at_ms=now_ms,
            lease_owner=None,
            lease_expires_at_ms=None,
            last_problem_json=None,
            created_at_ms=now_ms,
            updated_at_ms=now_ms,
        )
    )


def _save(store, run_id, state):
    def mutate(uow):
        run = uow.repository.get_run(run_id)
        snapshot = json.loads(run.input_snapshot_json)
        snapshot["operatorIteration"] = state
        uow.repository.execute(
            "UPDATE workflow_runs SET input_snapshot_json=? WHERE run_id=?",
            (json.dumps(snapshot, ensure_ascii=False), run_id),
        )

    store.submit(mutate, force_flush=True).result(timeout=30)
    return state


def _budget_stop(store, campaign):
    if budget_summary(campaign)["gpuTuningAvailableSeconds"] < 1:
        return "gpu_budget_exhausted"
    budget = campaign.budget
    if budget.discussion is None or budget.planning is None:
        return "model_budget_missing"
    limit = Decimal(str(budget.modelCostLimit))
    if limit <= 0:
        return "model_budget_exhausted"
    currency = budget.discussion.prices[0].currency
    committed = store.read(
        lambda repo: _campaign_committed_amounts(
            SimpleNamespace(repository=repo),
            campaign_id=campaign.optimizationCampaignId,
            currency=currency,
            model_cost_limit=limit,
        )
    )
    required = calculate_max_reserved_cost(
        budget.discussion
    ) + calculate_max_reserved_cost(budget.planning)
    if committed + required > limit:
        return "model_budget_exhausted"
    return ""


def advance_iteration(store, payload, *, now_ms):
    run = store.get_run(payload.get("runId", ""))
    if (
        run is None
        or run.workflow_id != "operator-optimization"
        or run.team_id != payload.get("teamId")
        or payload.get("eventType") != EVENT
    ):
        raise CampaignConflict("Iteration event does not identify an operator run")
    root = campaign_root(run.team_id, run.project_id)
    with inter_process_lock(root / ("iteration-" + sha256_hex(run.run_id))):
        run = store.get_run(run.run_id)
        snapshot = json.loads(run.input_snapshot_json)
        state = snapshot.get("operatorIteration", {})
        if state.get("status") in {"started", "stopped", "blocked"}:
            return state

        def stop(reason):
            return _save(
                store, run.run_id, {**state, "status": "stopped", "reason": reason}
            )

        if (
            run.status != "succeeded"
            or run.completion_kind != "operator_round_completed"
        ):
            return stop("round_not_completed")
        cid = snapshot["researchObjectiveContract"]["optimizationCampaignId"]
        campaign = read_campaign(run.team_id, run.project_id, cid)
        if (
            campaign.status != "running"
            or not campaign.budget.authorized
            or not campaign.authorizedBy
        ):
            return stop("campaign_not_authorized_or_running")
        record = next(r for r in campaign.rounds if r.runId == run.run_id)
        if record.feedbackRef is None or record.evaluationRef is None:
            raise CampaignConflict("Completed round has no canonical feedback")
        feedback = read_ref(run.team_id, run.run_id, record.feedbackRef)
        if (
            feedback.get("runId") != run.run_id
            or feedback.get("roundId") != record.roundId
            or feedback.get("evaluationRef")
            != record.evaluationRef.model_dump(mode="json")
        ):
            raise CampaignConflict("Iteration feedback differs from its round")
        if not state:
            if campaign.activeRunId != run.run_id:
                return stop("superseded")
            if len(campaign.rounds) >= campaign.budget.maxRounds:
                return stop("max_rounds_reached")
            reason = _budget_stop(store, campaign)
            if reason:
                return stop(reason)
            state = _save(
                store,
                run.run_id,
                {
                    "status": "preparing",
                    "campaignVersion": campaign.revision,
                    "commandKey": "auto-round:" + run.run_id,
                },
            )
        if not state.get("nextRunId"):
            created = prepare_round(
                run.team_id,
                run.project_id,
                cid,
                expected_version=state["campaignVersion"],
                command_key=state["commandKey"],
            )
            next_run = store.get_run(created.activeRunId)
            state = _save(
                store,
                run.run_id,
                {
                    **state,
                    "nextRunId": next_run.run_id,
                    "startRunVersion": next_run.run_version,
                    "requestedAtMs": now_ms,
                },
            )
        campaign = read_campaign(run.team_id, run.project_id, cid)
        if (
            campaign.activeRunId != state["nextRunId"]
            or campaign.status != "running"
            or not campaign.budget.authorized
        ):
            return stop("next_round_no_longer_active")
        reason = _budget_stop(store, campaign)
        # An already accepted start must be recovered even if its reservation
        # now consumes the remaining budget; it must never be submitted twice.
        start_key = "auto-start:" + run.run_id
        existing = store.get_command_by_idempotency(state["nextRunId"], start_key)
        if reason and existing is None:
            return stop(reason)
        from ..research_runtime.command_service import NodeNotReadyError

        try:
            receipt = get_command_service().submit(
                CommandRequest(
                    command_id="cmd-" + sha256_hex(start_key)[:24],
                    run_id=state["nextRunId"],
                    team_id=run.team_id,
                    command=WorkflowCommandKind.START_NODE,
                    node_id="optimization_discussion",
                    expected_run_version=state["startRunVersion"],
                    idempotency_key=start_key,
                    payload={},
                    requested_by=ActorRef("system", "operator-iteration"),
                    requested_at_ms=state["requestedAtMs"],
                )
            )
        except NodeNotReadyError as exc:
            return _save(
                store,
                run.run_id,
                {**state, "status": "blocked", "reason": str(exc)[:500]},
            )
        return _save(
            store,
            run.run_id,
            {**state, "status": "started", "commandId": receipt.command_id},
        )
