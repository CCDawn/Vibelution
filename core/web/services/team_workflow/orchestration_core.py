"""Team workflow orchestration document ensure/get.

Late-bound facade helpers keep route imports and monkeypatches on
``team_workflow_orchestration_service`` stable during P0 mechanical splits.
"""

from __future__ import annotations

from typing import Any


def _service():
    from core.web.services import team_workflow_orchestration_service

    return team_workflow_orchestration_service


def get_team_workflow_orchestration(team_id: str) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    s.team_service.assert_team_exists(normalized_team_id)
    with s._WORKFLOW_LOCK:
        workflow = s._load_or_create_workflow(normalized_team_id, persist_repair=False)
        candidate_store = s._load_candidate_store(normalized_team_id)
    return s._workflow_to_api(normalized_team_id, workflow, candidate_store)

def ensure_team_workflow_orchestration(
    team_id: str,
    *,
    workflow_kind: str = "challenge_cup_research",
    owner_agent_id: str = "Research Coordination Agent",
) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_kind = s._normalize_workflow_kind(workflow_kind)
    normalized_owner_agent_id = s._trim_text(owner_agent_id, max_length=160) or s.DEFAULT_OWNER_AGENT_ID
    s.team_service.get_team(normalized_team_id)
    with s._WORKFLOW_LOCK:
        path = s._workflow_path(normalized_team_id)
        existing = s._read_json(path) if path.exists() else {}
        workflow = s._default_workflow(
            normalized_team_id,
            workflow_kind=normalized_kind,
            owner_agent_id=normalized_owner_agent_id,
        )
        if existing:
            workflow.update(s._repair_workflow(existing, normalized_team_id))
            workflow["workflowKind"] = normalized_kind
            workflow["ownerAgentId"] = normalized_owner_agent_id
            workflow["routingPolicy"] = s._sync_owner_policy(workflow.get("routingPolicy"), normalized_owner_agent_id)
            workflow["transferPolicy"] = s._sync_transfer_policy(workflow.get("transferPolicy"), normalized_owner_agent_id)
            workflow["updatedAt"] = s.utc_now_iso()
        s._write_json(path, workflow)
        candidate_store = s._load_candidate_store(normalized_team_id)
    s._record_workflow_event(
        "workflow.ensure",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "workflowKind": workflow["workflowKind"],
            "ownerAgentId": workflow["ownerAgentId"],
        },
    )
    return s._workflow_to_api(normalized_team_id, workflow, candidate_store)
