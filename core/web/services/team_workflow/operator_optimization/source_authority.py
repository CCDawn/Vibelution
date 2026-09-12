"""Freeze source routing on the real knowledge NodeRun, then bind native tasks."""

from __future__ import annotations

import json

from core.research.operator_optimization.knowledge_invocation import (
    OperatorKnowledgeInvocationBinding,
)
from core.research.workflow.contracts._canonical import sha256_hex
from core.web.services import agent_directory_service, chat_room_service

from .knowledge_budget_runtime import (
    knowledge_lineage,
    knowledge_receipt_context,
    validate_knowledge_receipt_scope,
)
from .store import CampaignConflict


def _active(repo, run_id, node_run_id):
    lineage = knowledge_lineage(repo, run_id, node_run_id)
    run, parent, attempt, invocation, _ = lineage
    latest = repo.latest_attempt(run_id, attempt.node_id)
    parent_latest = repo.latest_attempt(parent.run_id, "optimization_knowledge")
    if (
        latest is None
        or latest.node_run_id != node_run_id
        or attempt.finished_at_ms is not None
        or parent_latest is None
        or parent_latest.node_run_id != invocation.parent_node_run_id
        or parent_latest.finished_at_ms is not None
        or run.status in {"failed", "cancelled", "archived", "succeeded"}
        or parent.status in {"failed", "cancelled", "archived", "succeeded"}
    ):
        raise CampaignConflict(
            "Operator source requires its active parent and child attempts"
        )
    return lineage


def build_operator_source_authority(store, action, *, agent_id):
    def freeze(uow):
        repo = uow.repository
        run, parent, attempt, invocation, request = _active(
            repo, action.run_id, action.node_run_id
        )
        snapshot = json.loads(run.input_snapshot_json)
        bindings = [
            b
            for b in snapshot.get("agentBindingSnapshot", [])
            if b.get("nodeId") == attempt.node_id and b.get("agentId") == agent_id
        ]
        if len(bindings) != 1:
            raise CampaignConflict(
                "Operator source Agent differs from its frozen binding"
            )
        saved = snapshot.setdefault("operatorSourceAuthorities", {})
        if attempt.node_run_id in saved:
            authority = saved[attempt.node_run_id]
            if authority["agentId"] != agent_id:
                raise CampaignConflict("Operator source replay changed Agent")
            return authority
        agent = agent_directory_service.get_agent(agent_id, include_archived=False)
        resolved = chat_room_service._resolve_chat_room_agent_llm(agent)
        route = {
            "modelRef": resolved.model_ref,
            "providerId": resolved.provider_id,
            "modelId": resolved.model,
        }
        scope = {
            "teamId": run.team_id,
            "researchProjectId": run.project_id,
            "optimizationCampaignId": request.optimizationCampaignId,
            "roundId": request.roundId,
            "parentRunId": parent.run_id,
            "parentNodeRunId": invocation.parent_node_run_id,
            "knowledgeInvocationId": invocation.invocation_id,
            "requestHash": invocation.request_hash,
            "workflowRunId": run.run_id,
            "workflowVersionId": run.workflow_version_id,
            "formalNodeId": attempt.node_id,
            "formalNodeRunId": attempt.node_run_id,
            "formalNodeAttempt": attempt.attempt,
        }
        budget = validate_knowledge_receipt_scope(repo, scope)
        if route["modelRef"] not in {p["modelRef"] for p in budget["prices"]}:
            raise CampaignConflict("Operator source model has no authorized price")
        authority = {
            "authorityKind": "operator_source",
            **scope,
            "agentId": agent_id,
            "agentRole": bindings[0]["roleKey"],
            "expectedModelRoute": route,
            "modelPolicySha256": sha256_hex({"route": route, "budget": budget}),
        }
        saved[attempt.node_run_id] = authority
        repo.execute(
            "UPDATE workflow_runs SET input_snapshot_json = ? WHERE run_id = ?",
            (json.dumps(snapshot, ensure_ascii=False), run.run_id),
        )
        return authority

    return store.submit(freeze, force_flush=True).result(timeout=30)


def validate_operator_source_authority(
    store,
    authority,
    *,
    team_id,
    project_id,
    workflow_run_id,
    node_id,
    agent_id,
    agent_role,
):
    def validate(repo):
        run, _, _, _, _ = _active(repo, workflow_run_id, authority["formalNodeRunId"])
        saved = (
            json.loads(run.input_snapshot_json)
            .get("operatorSourceAuthorities", {})
            .get(authority["formalNodeRunId"])
        )
        expected = (
            run.team_id,
            run.project_id,
            run.run_id,
            authority["formalNodeId"],
            authority["agentId"],
            authority["agentRole"],
        )
        if saved != authority or expected != (
            team_id,
            project_id,
            workflow_run_id,
            node_id,
            agent_id,
            agent_role,
        ):
            raise CampaignConflict(
                "Operator source task differs from its server-frozen authority"
            )

    store.read(validate)
    return authority


def source_task_receipt_context(store, task, *, session_id, turn_id):
    authority = task["operatorSourceAuthority"]
    validate_operator_source_authority(
        store,
        authority,
        team_id=task["teamId"],
        project_id=task["researchProjectId"],
        workflow_run_id=task["workflowRunId"],
        node_id={
            "finding": "source_finding",
            "extraction": "source_extraction",
            "relations": "evidence_relations",
            "ingestion": "knowledge_ingestion",
        }[task["stageId"]],
        agent_id=task["agentId"],
        agent_role=task["agentRole"],
    )
    binding = OperatorKnowledgeInvocationBinding.model_validate(
        {
            **{
                k: v
                for k, v in authority.items()
                if k in OperatorKnowledgeInvocationBinding.model_fields
            },
            "sessionId": session_id,
            "taskId": task["taskId"],
            "turnId": turn_id,
        }
    )
    return knowledge_receipt_context(
        store, binding, expected_model_route=authority["expectedModelRoute"]
    )
