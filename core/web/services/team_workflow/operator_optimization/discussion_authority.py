"""Server-owned operator meeting setup and exact speaker receipt lineage."""
from __future__ import annotations

import json
from copy import deepcopy

from core.research.operator_optimization.discussion_contracts import OperatorInvocationBinding
from core.research.workflow.contracts._canonical import sha256_hex
from core.web.services import agent_directory_service, chat_room_service, team_service

from ..research_runtime import workflow_artifact_store as artifacts
from ..research_runtime.artifact_readback_registry import load_scoped_artifact_payload
from ..research_runtime.formal_write_runtime import get_write_store
from ..storage_durability import inter_process_lock
from .discussion import discussion_input
from .store import CampaignConflict, read_campaign

AUTHORITY_KIND = "operator_discussion"


def _active_run(team_id, run_id, node_run_id):
    store = get_write_store()
    run = store.get_run(run_id)
    if run is None or run.team_id != team_id or run.workflow_id != "operator-optimization":
        raise CampaignConflict("Operator discussion run scope differs")
    attempt = store.latest_attempt(run_id, "optimization_discussion")
    if (attempt is None or attempt.node_run_id != node_run_id or attempt.finished_at_ms is not None
            or run.status in {"failed", "cancelled", "archived", "succeeded"}):
        raise CampaignConflict("Operator discussion requires its active node attempt")
    return run, attempt


def build_operator_meeting_authority(team_id: str, run_id: str, *, node_run_id: str) -> dict:
    run, attempt = _active_run(team_id, run_id, node_run_id)
    inputs = discussion_input(team_id, run_id)
    context = inputs["context"]
    campaign = read_campaign(team_id, run.project_id, context["optimizationCampaignId"])
    if (not campaign.budget.authorized or not campaign.authorizedBy
            or campaign.budget.modelCostLimit <= 0 or campaign.budget.discussion is None):
        raise CampaignConflict("Discussion requires explicit authorized model budget and prices")
    identity = "discussion-setup:" + context["roundId"]
    with inter_process_lock(artifacts._path(team_id, "optimization_discussion")):
        saved = load_scoped_artifact_payload("optimization_discussion", team_id=team_id,
            workflow_run_id=run_id, authority_run_id=run_id, record_id=identity)
        if saved:
            result = saved["payload"]
            if result["inputHash"] != sha256_hex(inputs) or result["nodeRunId"] != node_run_id:
                raise CampaignConflict("Existing discussion belongs to another frozen input or attempt")
            return result
        snapshot = json.loads(run.input_snapshot_json)
        planners = {b.get("agentId") for b in snapshot.get("agentBindingSnapshot", [])
            if b.get("nodeId") == "optimization_discussion" and b.get("agentId")}
        if len(planners) != 1:
            raise CampaignConflict("Discussion requires one bound experiment_planner")
        planner = next(iter(planners))
        members = list({m["agentId"]: m for m in (team_service.get_team(team_id).get("members") or [])
            if m.get("agentId")}.values())
        if len(members) < 2 or planner not in {m["agentId"] for m in members}:
            raise CampaignConflict("Discussion requires at least two team participants including its planner")
        if len(members) > campaign.budget.discussion.maxCalls:
            raise CampaignConflict("Discussion participants exceed the authorized call limit")
        members.sort(key=lambda m: m["agentId"] == planner)
        seats = []
        for member in members:
            agent = agent_directory_service.get_agent(member["agentId"], include_archived=False)
            resolved = chat_room_service._resolve_chat_room_agent_llm(agent)
            prices = [p for p in campaign.budget.discussion.prices if p.modelRef == resolved.model_ref
                and p.currency == campaign.budget.currency]
            if len(prices) != 1:
                raise CampaignConflict("Discussion model requires one price in the authorized currency")
            seats.append({"agentId": member["agentId"], "role": member.get("role") or "researcher",
                "modelRef": resolved.model_ref, "providerId": resolved.provider_id, "modelId": resolved.model})
        result = {"schemaVersion": 1, "authorityKind": AUTHORITY_KIND,
            "teamId": team_id, "researchProjectId": run.project_id,
            "optimizationCampaignId": context["optimizationCampaignId"], "roundId": context["roundId"],
            "workflowRunId": run_id, "workflowId": run.workflow_id, "workflowVersionId": run.workflow_version_id,
            "nodeRunId": node_run_id, "nodeAttempt": attempt.attempt,
            "questionId": snapshot["questionId"], "inputHash": sha256_hex(inputs),
            "budget": campaign.budget.model_dump(mode="json"),
            "participants": seats, "finalAgentId": planner, "modelPolicySha256": sha256_hex(seats)}
        artifacts.put_workflow_artifact(team_id, kind="optimization_discussion", workflow_run_id=run_id,
            artifact_identity=identity, payload=result)
        return result


def validate_operator_authority(authority: dict) -> dict:
    if authority.get("authorityKind") != AUTHORITY_KIND:
        raise CampaignConflict("Operator authority kind differs")
    run, _ = _active_run(authority["teamId"], authority["workflowRunId"], authority["nodeRunId"])
    saved = load_scoped_artifact_payload("optimization_discussion", team_id=run.team_id,
        workflow_run_id=run.run_id, authority_run_id=run.run_id,
        record_id="discussion-setup:" + authority["roundId"])
    if saved is None or saved["payload"] != authority or run.project_id != authority["researchProjectId"]:
        raise CampaignConflict("Operator authority differs from server-frozen setup")
    discussion_input(run.team_id, run.run_id)
    return authority


def operator_workflow_stop_reason(authority: dict) -> str:
    try:
        validate_operator_authority(authority)
        run = get_write_store().get_run(authority["workflowRunId"])
        if run.status == "blocked":
            from ..research_runtime.completion_dependency import COMPLETION_PENDING

            if json.loads(run.blocked_problem_json or "{}").get("code") != COMPLETION_PENDING:
                return "operator_workflow_blocked"
        elif run.status != "running":
            return "operator_workflow_inactive"
    except (CampaignConflict, ValueError, KeyError):
        return "operator_discussion_authority_inactive"
    return ""


def speaker_receipt_context(participant: dict, context: dict, *, session_id: str,
        turn_identity: str, expected_model_route: dict) -> dict:
    authority = validate_operator_authority(context["_modelInvocationReceiptAuthority"])
    if (context.get("meetingType") != "operator_optimization_discussion"
            or context.get("teamId") != authority["teamId"]
            or context.get("workflowRunId") != authority["workflowRunId"]):
        raise CampaignConflict("Operator speaker scope differs from its meeting")
    seats = [s for s in authority["participants"] if s["agentId"] == participant.get("agentId")]
    if len(seats) != 1 or any(expected_model_route.get(k) != seats[0][k]
            for k in ("modelRef", "providerId", "modelId")):
        raise CampaignConflict("Operator speaker model differs from the frozen seat")
    participant_id = participant["participantId"]
    if turn_identity != f"chat-room:{context['roundId']}:{participant_id}" or participant.get("sessionId") != session_id:
        raise CampaignConflict("Operator speaker Turn identity differs")
    binding = OperatorInvocationBinding(
        teamId=authority["teamId"], researchProjectId=authority["researchProjectId"],
        optimizationCampaignId=authority["optimizationCampaignId"], roundId=authority["roundId"],
        workflowRunId=authority["workflowRunId"], workflowVersionId=authority["workflowVersionId"],
        formalNodeRunId=authority["nodeRunId"], formalNodeAttempt=authority["nodeAttempt"],
        sessionId=session_id, taskId=f"operator-speaker:{context['roundId']}:{participant_id}",
        turnId=turn_identity, participantId=participant_id, modelPolicySha256=authority["modelPolicySha256"])
    from .discussion_budget_runtime import speaker_budget_preflight, speaker_receipt_sink

    return {"receiptRunAuthority": "workflow_run", "receiptRunId": authority["workflowRunId"],
        "invocationBudgetPreflight": speaker_budget_preflight(authority, seats[0]["modelRef"]),
        "operatorInvocationReceiptCallback": speaker_receipt_sink(authority, binding),
        "operatorInvocationBinding": binding.model_dump(mode="json"),
        "modelPolicySha256": authority["modelPolicySha256"], "expectedModelRoute": expected_model_route,
        "evidenceLocator": {"kind": "operator_model_invocation", "executionKind": "chat_room_meeting",
            "meetingRoundId": authority["roundId"], "chatRoomRoundId": context["roundId"],
            "participantId": participant_id}}


def resolve_speaker_llm(agent: dict, context: dict, resolver):
    authority = validate_operator_authority(context["_modelInvocationReceiptAuthority"])
    seat = next((s for s in authority["participants"] if s["agentId"] == agent.get("agentId")), None)
    if seat is None:
        raise CampaignConflict("Speaker is outside the frozen operator team")
    frozen = deepcopy(agent)
    frozen.setdefault("llmBindings", {})["dialogue"] = {"modelId": seat["modelRef"]}
    resolved = resolver(frozen)
    if (resolved.model_ref, resolved.provider_id, resolved.model) != (seat["modelRef"], seat["providerId"], seat["modelId"]):
        raise CampaignConflict("Resolved operator model differs from its frozen route")
    return resolved
