"""Durable post-feedback iteration over native outbox and command services."""

from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace

from core.research.operator_optimization.decision import (
    OPTIMIZATION_DECISION_ARTIFACT_KIND,
    OperatorIterationDecision,
    OperatorIterationDecisionArtifact,
    decision_id_for,
    is_stage3_operator_run,
    iteration_route_for_action,
)
from core.research.workflow.contracts import (
    ActorRef,
    CommandRequest,
    WorkflowCommandKind,
)
from core.research.workflow.contracts._canonical import sha256_hex
from core.research.workflow.ledger import OutboxRecord

from ..research_runtime.formal_write_runtime import get_command_service
from ..research_runtime.operator_terminal_policy import (
    operator_round_terminal_policy,
)
from ..storage_durability import inter_process_lock
from .budget import budget_summary
from .decision_output import decision_task_input
from .knowledge import read_ref
from .model_budget import _campaign_committed_amounts, calculate_max_reserved_cost
from .rounds import prepare_round
from .store import CampaignConflict, campaign_root, read_campaign

EVENT = "operator_round_completed"


def _iteration_action_blocker(campaign, action: str) -> str:
    """Reject actions whose cross-round handoff has not been connected yet."""

    prior = campaign.rounds[-1] if campaign.rounds else None
    target_parent = campaign.bestCandidateRef or campaign.baselineCandidateRef
    if action == "discuss":
        return ""
    if action == "collect_knowledge":
        if prior is None or prior.hypothesisRef is None:
            return "collect_knowledge_requires_hypothesis"
        if prior.parentCandidateRef != target_parent:
            return "iteration_parent_candidate_changed"
        return ""
    if action == "plan_candidate":
        if prior is None or prior.hypothesisRef is None or prior.knowledgeRef is None:
            return "plan_candidate_requires_hypothesis_and_knowledge"
        if prior.parentCandidateRef != target_parent:
            return "iteration_parent_candidate_changed"
        return ""
    if action == "retest":
        if prior is None or prior.planRef is None:
            return "retest_requires_plan"
        if prior.parentCandidateRef != target_parent:
            return "iteration_parent_candidate_changed"
        return ""
    if action == "repair_baseline":
        return "baseline_repair_flow_not_connected"
    return "unknown_iteration_action"


def enqueue_iteration(uow, *, run, now_ms):
    key = "operator-next-round:" + run.run_id
    if uow.repository.execute(
        "SELECT action_id FROM outbox_actions WHERE idempotency_key=?", (key,)
    ).fetchone():
        return
    policy = operator_round_terminal_policy(run)
    if policy is None:
        raise CampaignConflict("Iteration requires an operator workflow run")
    attempt = uow.repository.latest_attempt(run.run_id, policy.node_id)
    if attempt is None or not attempt.command_id:
        raise CampaignConflict(
            f"Iteration requires the native {policy.node_id} command"
        )
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
        snapshot["operatorDecision"] = state
        uow.repository.execute(
            "UPDATE workflow_runs SET input_snapshot_json=? WHERE run_id=?",
            (json.dumps(snapshot, ensure_ascii=False), run_id),
        )

    store.submit(mutate, force_flush=True).result(timeout=30)
    return state


def _budget_stop(store, campaign, *, required_phases=("decision",)):
    if budget_summary(campaign)["gpuTuningAvailableSeconds"] < 1:
        return "gpu_budget_exhausted"
    budget = campaign.budget
    phase_budgets = [getattr(budget, phase, None) for phase in required_phases]
    if any(phase is None for phase in phase_budgets):
        return "model_budget_missing"
    if not phase_budgets:
        return ""
    limit = Decimal(str(budget.modelCostLimit))
    if limit <= 0:
        return "model_budget_exhausted"
    currency = phase_budgets[0].prices[0].currency
    committed = store.read(
        lambda repo: _campaign_committed_amounts(
            SimpleNamespace(repository=repo),
            campaign_id=campaign.optimizationCampaignId,
            currency=currency,
            model_cost_limit=limit,
        )
    )
    required = sum(
        (calculate_max_reserved_cost(phase) for phase in phase_budgets),
        Decimal("0"),
    )
    if committed + required > limit:
        return "model_budget_exhausted"
    return ""


def advance_iteration(store, payload, *, now_ms):
    """Materialize the one durable decision request for a completed round.

    This event consumer deliberately has no authority to choose the next
    research action.  Replays return the persisted request, while a separate
    decision-agent completion applies one structured decision through
    :func:`apply_iteration_decision`.
    """
    run = store.get_run(payload.get("runId", ""))
    if (
        run is None
        or run.workflow_id != "operator-optimization"
        or run.team_id != payload.get("teamId")
        or payload.get("eventType") != EVENT
    ):
        raise CampaignConflict("Iteration event does not identify an operator run")
    if not is_stage3_operator_run(run):
        raise CampaignConflict("Historical operator workflow is read-only")
    root = campaign_root(run.team_id, run.project_id)
    with inter_process_lock(root / ("iteration-" + sha256_hex(run.run_id))):
        run = store.get_run(run.run_id)
        snapshot = json.loads(run.input_snapshot_json)
        state = snapshot.get("operatorDecision", {})
        if state:
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
        return _save(
            store,
            run.run_id,
            {
                "status": "requested",
                "decisionId": decision_id_for(run.run_id, record.feedbackRef),
                "campaignVersion": campaign.revision,
                "feedbackRef": record.feedbackRef.model_dump(mode="json"),
                "evaluationRef": record.evaluationRef.model_dump(mode="json"),
                "requestedAtMs": now_ms,
            },
        )


def apply_iteration_decision(store, payload, decision, *, now_ms):
    """Apply one persisted research decision and execute only its chosen action."""
    run = store.get_run(payload.get("runId", ""))
    if (
        run is None
        or run.workflow_id != "operator-optimization"
        or run.team_id != payload.get("teamId")
        or payload.get("eventType") != EVENT
    ):
        raise CampaignConflict("Iteration event does not identify an operator run")
    if not is_stage3_operator_run(run):
        raise CampaignConflict("Historical operator workflow is read-only")
    root = campaign_root(run.team_id, run.project_id)
    with inter_process_lock(root / ("iteration-" + sha256_hex(run.run_id))):
        run = store.get_run(run.run_id)
        snapshot = json.loads(run.input_snapshot_json)
        state = snapshot.get("operatorDecision", {})
        if not state:
            raise CampaignConflict("Completed round has no research decision request")
        try:
            normalized = OperatorIterationDecision.model_validate(decision).model_dump(
                mode="json"
            )
        except Exception as exc:
            raise CampaignConflict(f"Research decision is invalid: {exc}") from exc
        if normalized["decisionId"] != state.get("decisionId"):
            raise CampaignConflict("Research decision does not match the pending request")
        existing = state.get("decision")
        if existing is not None:
            if existing != normalized:
                raise CampaignConflict("Research decision is immutable")
            if state.get("status") in {"started", "stopped", "blocked"}:
                return state
        elif state.get("status") != "requested":
            raise CampaignConflict("Research decision request is not pending")

        def stop(reason):
            return _save(
                store,
                run.run_id,
                {**state, "decision": normalized, "status": "stopped", "reason": reason},
            )

        cid = snapshot["researchObjectiveContract"]["optimizationCampaignId"]
        campaign = read_campaign(run.team_id, run.project_id, cid)
        if normalized["kind"] == "stop":
            return stop(normalized["reason"])
        if (
            campaign.status != "running"
            or not campaign.budget.authorized
            or not campaign.authorizedBy
        ):
            return stop("campaign_not_authorized_or_running")
        required_phases = {
            "discuss": ("discussion",),
            "collect_knowledge": ("knowledge",),
            "plan_candidate": ("planning",),
            "retest": (),
            "repair_baseline": (),
        }[normalized["kind"]]
        if existing is None:
            if campaign.activeRunId != run.run_id:
                return stop("superseded")
            if campaign.revision != state.get("campaignVersion"):
                return stop("campaign_changed_after_decision_request")
            if len(campaign.rounds) >= campaign.budget.maxRounds:
                return stop("max_rounds_reached")
            reason = _budget_stop(
                store, campaign, required_phases=required_phases
            )
            if reason:
                return stop(reason)
            action_blocker = _iteration_action_blocker(campaign, normalized["kind"])
            if action_blocker:
                return _save(
                    store,
                    run.run_id,
                    {
                        **state,
                        "decision": normalized,
                        "status": "blocked",
                        "reason": action_blocker,
                    },
                )
            state = _save(
                store,
                run.run_id,
                {
                    **state,
                    "decision": normalized,
                    "status": "preparing",
                    "commandKey": "decision-round:" + normalized["decisionId"],
                },
            )
        if not state.get("nextRunId"):
            try:
                created = prepare_round(
                    run.team_id,
                    run.project_id,
                    cid,
                    expected_version=state["campaignVersion"],
                    command_key=state["commandKey"],
                    iteration_action=normalized["kind"],
                )
            except CampaignConflict as exc:
                return _save(
                    store,
                    run.run_id,
                    {**state, "status": "blocked", "reason": str(exc)[:500]},
                )
            next_run = store.get_run(created.activeRunId)
            state = _save(
                store,
                run.run_id,
                {
                    **state,
                    "nextRunId": next_run.run_id,
                    "startRunVersion": next_run.run_version,
                    "actionRequestedAtMs": now_ms,
                },
            )
        campaign = read_campaign(run.team_id, run.project_id, cid)
        if (
            campaign.activeRunId != state["nextRunId"]
            or campaign.status != "running"
            or not campaign.budget.authorized
        ):
            return stop("next_round_no_longer_active")
        reason = _budget_stop(
            store, campaign, required_phases=required_phases
        )
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
                    node_id=iteration_route_for_action(normalized["kind"]),
                    expected_run_version=state["startRunVersion"],
                    idempotency_key=start_key,
                    payload={},
                    requested_by=ActorRef("system", "operator-iteration"),
                    requested_at_ms=state["actionRequestedAtMs"],
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


def apply_persisted_iteration_decision(store, payload, *, now_ms):
    """Apply the single decision artifact already verified by the graph node."""

    run = store.get_run(payload.get("runId", ""))
    if run is None:
        raise CampaignConflict("Decision artifact run is unavailable")
    from ..research_runtime.workflow_artifact_store import list_workflow_artifacts

    rows = list_workflow_artifacts(
        run.team_id,
        kind=OPTIMIZATION_DECISION_ARTIFACT_KIND,
        workflow_run_id=run.run_id,
    )
    if len(rows) != 1:
        raise CampaignConflict("Completed round requires exactly one decision artifact")
    artifact = OperatorIterationDecisionArtifact.model_validate(rows[0]["payload"])
    inputs = decision_task_input(run.team_id, run.run_id)
    if (
        artifact.runId != run.run_id
        or artifact.optimizationCampaignId != inputs["optimizationCampaignId"]
        or artifact.roundId != inputs["roundId"]
        or artifact.inputHash != inputs["inputHash"]
        or artifact.feedbackRef.model_dump(mode="json") != inputs["feedbackRef"]
        or artifact.evaluationRef.model_dump(mode="json") != inputs["evaluationRef"]
        or artifact.decision.decisionId
        != decision_id_for(run.run_id, inputs["feedbackRef"])
    ):
        raise CampaignConflict("Decision artifact differs from the current round evidence")
    state = advance_iteration(store, payload, now_ms=now_ms)
    if state.get("status") != "requested" and not state.get("decision"):
        return state
    return apply_iteration_decision(
        store,
        payload,
        artifact.decision.model_dump(mode="json"),
        now_ms=now_ms,
    )
