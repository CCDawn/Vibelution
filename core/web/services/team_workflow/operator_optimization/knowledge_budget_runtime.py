"""Bind native knowledge child reservations and receipts to their real lineage."""
from __future__ import annotations

import json
from decimal import Decimal

from core.research.operator_optimization.knowledge import OperatorKnowledgeRequest
from core.research.workflow.contracts._canonical import sha256_hex

from .model_budget import admit_model_invocation, reserve_model_budget
from .store import CampaignConflict, read_campaign

SOURCE_NODES = {"source_finding", "source_extraction", "evidence_relations", "knowledge_ingestion"}


def is_operator_knowledge_run(store, run_id):
    run = store.get_run(run_id)
    if run is None or run.workflow_id != "challenge-cup-knowledge-sideflow":
        return False
    parent = store.get_run(run.parent_run_id) if run.parent_run_id else None
    return parent is not None and parent.workflow_id == "operator-optimization"


def knowledge_lineage(repo, run_id, node_run_id):
    run = repo.get_run(run_id)
    if run is None or run.workflow_id != "challenge-cup-knowledge-sideflow":
        raise CampaignConflict("Operator knowledge child is unavailable")
    parent = repo.get_run(run.parent_run_id)
    attempt = repo.get_attempt(node_run_id)
    if (parent is None or parent.workflow_id != "operator-optimization"
            or (run.team_id, run.project_id, run.question_id) != (parent.team_id, parent.project_id, parent.question_id)
            or run.question_id != "OPERATOR-SOFTMAX"
            or attempt is None or attempt.run_id != run_id or attempt.node_id not in SOURCE_NODES):
        raise CampaignConflict("Operator knowledge child lineage differs")
    snapshot = json.loads(run.input_snapshot_json)
    invocation = repo.get_knowledge_invocation(snapshot["invocationId"])
    if (invocation is None or invocation.knowledge_child_run_id != run_id
            or invocation.parent_run_id != parent.run_id or invocation.parent_node_id != "optimization_knowledge"
            or snapshot["parentNodeRunId"] != invocation.parent_node_run_id
            or snapshot["parentAttempt"] != invocation.parent_attempt
            or snapshot["parentRunId"] != parent.run_id):
        raise CampaignConflict("Operator knowledge invocation lineage differs")
    from ..research_runtime.knowledge_request_snapshot import validate_child_request

    frozen = validate_child_request(invocation, snapshot["knowledgeRequest"])
    request = OperatorKnowledgeRequest.model_validate(frozen["consumerContext"])
    parent_context = json.loads(parent.input_snapshot_json)["researchObjectiveContract"]
    if ((request.runId, request.teamId, request.researchProjectId) != (parent.run_id, parent.team_id, parent.project_id)
            or request.optimizationCampaignId != parent_context["optimizationCampaignId"]
            or request.roundId != parent_context["roundId"]):
        raise CampaignConflict("Operator knowledge request belongs to another round")
    return run, parent, attempt, invocation, request


def reserve_knowledge_budget(store, *, run_id, node_run_id):
    run, parent, attempt, invocation, request = store.read(lambda repo: knowledge_lineage(repo, run_id, node_run_id))
    parent_attempt = store.read(lambda repo: repo.get_attempt(invocation.parent_node_run_id))
    if (attempt.finished_at_ms is not None or parent_attempt is None
            or parent_attempt.run_id != parent.run_id or parent_attempt.node_id != "optimization_knowledge"
            or parent_attempt.attempt != invocation.parent_attempt or parent_attempt.finished_at_ms is not None
            or run.status in {"failed", "cancelled", "archived", "succeeded"}
            or parent.status in {"failed", "cancelled", "archived", "succeeded"}):
        raise CampaignConflict("Knowledge budget requires active parent and source attempts")
    campaign = read_campaign(run.team_id, run.project_id, request.optimizationCampaignId)
    record = next((r for r in campaign.rounds if r.runId == parent.run_id and r.roundId == request.roundId), None)
    if (record is None or record.hypothesisRef != request.hypothesisRef
            or not campaign.authorizedBy or not campaign.budget.authorized or campaign.budget.knowledge is None):
        raise CampaignConflict("Knowledge collection requires its explicit authorized budget")
    result = reserve_model_budget(store, run_id=run_id, node_run_id=node_run_id,
        optimization_campaign_id=request.optimizationCampaignId, round_id=request.roundId,
        campaign_budget=campaign.budget, budget_kind="knowledge",
        policy_hash=sha256_hex(campaign.budget.knowledge.model_dump(mode="json")))
    return {key: str(value) if isinstance(value, Decimal) else value for key, value in result.items()}


def validate_knowledge_receipt_scope(repo, scope):
    run, parent, attempt, invocation, request = knowledge_lineage(repo, scope["workflowRunId"], scope["formalNodeRunId"])
    expected = {"teamId": run.team_id, "researchProjectId": run.project_id,
        "workflowVersionId": run.workflow_version_id, "formalNodeId": attempt.node_id,
        "formalNodeAttempt": str(attempt.attempt), "parentRunId": parent.run_id,
        "parentNodeRunId": invocation.parent_node_run_id, "knowledgeInvocationId": invocation.invocation_id,
        "requestHash": invocation.request_hash, "optimizationCampaignId": request.optimizationCampaignId,
        "roundId": request.roundId}
    if any(str(scope.get(key, "")) != value for key, value in expected.items()):
        raise CampaignConflict("Knowledge receipt differs from its frozen lineage")
    row = repo.execute("SELECT reserved_json FROM budget_receipts WHERE reservation_id = ? AND run_id = ? AND node_run_id = ?",
        ("reservation-" + attempt.node_run_id, run.run_id, attempt.node_run_id)).fetchone()
    budget = json.loads(row[0])["operatorModelBudget"] if row else {}
    if (budget.get("budgetKind") != "knowledge" or budget.get("optimizationCampaignId") != request.optimizationCampaignId
            or budget.get("roundId") != request.roundId):
        raise CampaignConflict("Knowledge receipt has no matching campaign reservation")
    return budget


def knowledge_receipt_context(store, binding, *, expected_model_route):
    """Build ephemeral callbacks from a server-bound source task identity."""
    scope = binding.model_dump(mode="json")
    budget = store.read(lambda repo: validate_knowledge_receipt_scope(repo, scope))
    if expected_model_route.get("modelRef") not in {p["modelRef"] for p in budget["prices"]}:
        raise CampaignConflict("Knowledge model has no frozen price")

    def preflight(*, invocation_id, estimated_input_tokens, max_output_tokens):
        def validate(repo):
            current = validate_knowledge_receipt_scope(repo, scope)
            run = repo.get_run(binding.workflowRunId)
            parent = repo.get_run(binding.parentRunId)
            attempt = repo.get_attempt(binding.formalNodeRunId)
            if (attempt.finished_at_ms is not None or run.status in {"failed", "cancelled", "archived", "succeeded"}
                    or parent.status in {"failed", "cancelled", "archived", "succeeded"}):
                raise CampaignConflict("Knowledge source attempt is no longer active")
            return current
        current = store.read(validate)
        output = min(max_output_tokens, current["maxOutputTokensPerCall"])
        result = admit_model_invocation(store,
            reservation={"reservationId": "reservation-" + binding.formalNodeRunId,
                "runId": binding.workflowRunId, "nodeRunId": binding.formalNodeRunId},
            invocation_id=invocation_id, model_ref=expected_model_route["modelRef"],
            input_tokens=estimated_input_tokens, output_tokens=output)
        return {"maxOutputTokens": output, "remainingTokens": max(0, current["tokenLimit"] - result["tokensUsed"])}

    def persist(receipt):
        from ..research_runtime.receipt_persistence import enqueue_question_model_invocation_receipt
        if any(receipt["scope"].get(k) != scope[k] for k in ("sessionId", "taskId", "turnId")):
            raise CampaignConflict("Knowledge receipt differs from its bound task")
        enqueue_question_model_invocation_receipt(store, team_id=binding.teamId,
            question_id=binding.questionId, workflow_run_id=binding.workflowRunId, receipt=receipt)

    return {"operatorInvocationBinding": scope, "invocationBudgetPreflight": preflight,
        "operatorInvocationReceiptCallback": persist, "receiptRunAuthority": "workflow_run",
        "receiptRunId": binding.workflowRunId, "teamId": binding.teamId,
        "modelPolicySha256": binding.modelPolicySha256, "expectedModelRoute": dict(expected_model_route)}
