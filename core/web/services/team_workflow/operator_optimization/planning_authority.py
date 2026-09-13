"""Ledger-owned planner identity and ephemeral model accounting callbacks."""

from __future__ import annotations

import json
from decimal import Decimal

from core.research.operator_optimization.planning_invocation import (
    OperatorPlanningInvocationBinding,
)
from core.research.workflow.contracts._canonical import sha256_hex
from core.web.services import agent_directory_service, chat_room_service

from .model_budget import admit_model_invocation, reserve_model_budget
from .planning_output import planning_task_input
from .knowledge import round_context
from .store import CampaignConflict


def _lineage(repo, run_id, node_run_id, *, active=True):
    run = repo.get_run(run_id)
    attempt = repo.get_attempt(node_run_id)
    if (
        run is None
        or run.workflow_id != "operator-optimization"
        or run.question_id != "OPERATOR-SOFTMAX"
        or attempt is None
        or attempt.run_id != run_id
        or attempt.node_id != "optimization_plan"
    ):
        raise CampaignConflict("Planner requires its real operator NodeRun")
    if active:
        latest = repo.latest_attempt(run_id, "optimization_plan")
        if (
            latest is None
            or latest.node_run_id != node_run_id
            or attempt.finished_at_ms is not None
            or run.status not in {"running", "blocked"}
        ):
            raise CampaignConflict("Planner attempt is no longer active")
    return run, attempt


def read_planning_task(repo, run_id, node_run_id, *, active=True):
    run, attempt = _lineage(repo, run_id, node_run_id, active=active)
    task = (
        json.loads(run.input_snapshot_json)
        .get("operatorPlanningTasks", {})
        .get(node_run_id)
    )
    if not task or (
        task["teamId"],
        task["researchProjectId"],
        task["workflowVersionId"],
        task["formalNodeAttempt"],
    ) != (run.team_id, run.project_id, run.workflow_version_id, attempt.attempt):
        raise CampaignConflict("Canonical planning task is unavailable or differs")
    return task


def prepare_planning_task(store, action, agent_id):
    run = store.get_run(action.run_id)
    inputs = planning_task_input(run.team_id, run.run_id)
    campaign, record, _ = round_context(run.team_id, run.run_id)
    if (
        not campaign.authorizedBy
        or not campaign.budget.authorized
        or campaign.budget.planning is None
    ):
        raise CampaignConflict("Planning requires its explicit authorized model budget")

    def freeze(uow):
        repo = uow.repository
        current, attempt = _lineage(repo, action.run_id, action.node_run_id)
        snapshot = json.loads(current.input_snapshot_json)
        bindings = [
            b
            for b in snapshot.get("agentBindingSnapshot", [])
            if b.get("nodeId") == "optimization_plan"
            and b.get("agentId") == agent_id
            and b.get("roleKey") == "experiment_planner"
        ]
        if len(bindings) != 1:
            raise CampaignConflict("Planner differs from the frozen Agent binding")
        tasks = snapshot.setdefault("operatorPlanningTasks", {})
        if action.node_run_id in tasks:
            task = tasks[action.node_run_id]
            if task["agentId"] != agent_id or task["inputHash"] != inputs["inputHash"]:
                raise CampaignConflict("Planner replay changed Agent or inputs")
            return task
        agent = agent_directory_service.get_agent(agent_id, include_archived=False)
        resolved = chat_room_service._resolve_chat_room_agent_llm(agent)
        route = {
            "modelRef": resolved.model_ref,
            "providerId": resolved.provider_id,
            "modelId": resolved.model,
        }
        if route["modelRef"] not in {
            p.modelRef for p in campaign.budget.planning.prices
        }:
            raise CampaignConflict("Planner model has no authorized price")
        task = {
            "teamId": current.team_id,
            "researchProjectId": current.project_id,
            "workflowRunId": current.run_id,
            "workflowVersionId": current.workflow_version_id,
            "optimizationCampaignId": campaign.optimizationCampaignId,
            "roundId": record.roundId,
            "formalNodeId": "optimization_plan",
            "formalNodeRunId": attempt.node_run_id,
            "formalNodeAttempt": attempt.attempt,
            "agentId": agent_id,
            "taskId": "operator-planner:" + attempt.node_run_id,
            "turnId": "",
            "sessionId": "",
            "inputHash": inputs["inputHash"],
            "expectedModelRoute": route,
            "budget": campaign.budget.model_dump(mode="json"),
            "modelPolicySha256": sha256_hex(
                {
                    "route": route,
                    "budget": campaign.budget.planning.model_dump(mode="json"),
                }
            ),
        }
        tasks[action.node_run_id] = task
        repo.execute(
            "UPDATE workflow_runs SET input_snapshot_json = ? WHERE run_id = ?",
            (json.dumps(snapshot, ensure_ascii=False), current.run_id),
        )
        return task

    return store.submit(freeze, force_flush=True).result(timeout=30)


def reserve_planning_budget(store, task):
    result = reserve_model_budget(
        store,
        run_id=task["workflowRunId"],
        node_run_id=task["formalNodeRunId"],
        optimization_campaign_id=task["optimizationCampaignId"],
        round_id=task["roundId"],
        campaign_budget=task["budget"],
        budget_kind="planning",
        policy_hash=task["modelPolicySha256"],
    )
    return {
        key: str(value) if isinstance(value, Decimal) else value
        for key, value in result.items()
    }


def validate_planning_receipt_scope(repo, scope):
    task = read_planning_task(
        repo, scope["workflowRunId"], scope["formalNodeRunId"], active=False
    )
    for key in OperatorPlanningInvocationBinding.model_fields:
        if key in task and str(scope.get(key, "")) != str(task[key]):
            raise CampaignConflict("Planner receipt differs from its canonical task")
    row = repo.execute(
        "SELECT reserved_json FROM budget_receipts WHERE reservation_id = ? AND run_id = ? AND node_run_id = ?",
        (
            "reservation-" + task["formalNodeRunId"],
            task["workflowRunId"],
            task["formalNodeRunId"],
        ),
    ).fetchone()
    budget = json.loads(row[0]).get("operatorModelBudget", {}) if row else {}
    if (
        budget.get("budgetKind") != "planning"
        or budget.get("optimizationCampaignId") != task["optimizationCampaignId"]
        or budget.get("roundId") != task["roundId"]
    ):
        raise CampaignConflict("Planner receipt has no matching planning reservation")
    return task


def task_for_turn(store, metadata, session_id, turn_id):
    task = store.read(
        lambda repo: read_planning_task(
            repo, metadata["workflowRunId"], metadata["nodeRunId"]
        )
    )
    if not task["turnId"]:
        from .planning_task import recover_planning_turn

        task = recover_planning_turn(store, task)
    if (
        task["taskId"],
        task["teamId"],
        task["researchProjectId"],
        task["sessionId"],
        task["turnId"],
    ) != (
        metadata.get("taskId"),
        metadata.get("teamId"),
        metadata.get("researchProjectId"),
        session_id,
        turn_id,
    ):
        raise CampaignConflict("Planner turn locator differs from its canonical task")
    return task


def planning_receipt_context(store, task):
    binding = OperatorPlanningInvocationBinding.model_validate(
        {
            k: task[k]
            for k in OperatorPlanningInvocationBinding.model_fields
            if k in task
        }
    )
    scope = binding.model_dump(mode="json")
    store.read(lambda repo: validate_planning_receipt_scope(repo, scope))

    def preflight(*, invocation_id, estimated_input_tokens, max_output_tokens):
        current = store.read(
            lambda repo: read_planning_task(
                repo, binding.workflowRunId, binding.formalNodeRunId
            )
        )
        inputs = planning_task_input(binding.teamId, binding.workflowRunId)
        campaign, _, _ = round_context(binding.teamId, binding.workflowRunId)
        if inputs["inputHash"] != binding.inputHash or not campaign.budget.authorized:
            raise CampaignConflict("Planner input or authorization is no longer valid")
        policy = current["budget"]["planning"]
        output = min(max_output_tokens, policy["maxOutputTokensPerCall"])
        result = admit_model_invocation(
            store,
            reservation={
                "reservationId": "reservation-" + binding.formalNodeRunId,
                "runId": binding.workflowRunId,
                "nodeRunId": binding.formalNodeRunId,
            },
            invocation_id=invocation_id,
            model_ref=current["expectedModelRoute"]["modelRef"],
            input_tokens=estimated_input_tokens,
            output_tokens=output,
        )
        return {
            "maxOutputTokens": output,
            "remainingTokens": max(0, policy["tokenLimit"] - result["tokensUsed"]),
        }

    def persist(receipt):
        from ..research_runtime.receipt_persistence import (
            enqueue_question_model_invocation_receipt,
        )

        store.read(lambda repo: validate_planning_receipt_scope(repo, receipt["scope"]))
        enqueue_question_model_invocation_receipt(
            store,
            team_id=binding.teamId,
            question_id=binding.questionId,
            workflow_run_id=binding.workflowRunId,
            receipt=receipt,
        )

    return {
        "operatorInvocationBinding": scope,
        "invocationBudgetPreflight": preflight,
        "operatorInvocationReceiptCallback": persist,
        "receiptRunAuthority": "workflow_run",
        "receiptRunId": binding.workflowRunId,
        "teamId": binding.teamId,
        "modelPolicySha256": binding.modelPolicySha256,
        "expectedModelRoute": task["expectedModelRoute"],
    }
