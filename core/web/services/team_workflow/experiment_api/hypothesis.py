"""Experiment hypothesis materialization operations (Clarity B6 split from experiment.py).

Late-bound facade keeps route imports and monkeypatches on
``team_workflow_orchestration_service`` stable during mechanical splits.
"""

from __future__ import annotations

from typing import Any


def _service():
    from core.web.services import team_workflow_orchestration_service

    return team_workflow_orchestration_service


def materialize_experiment_proxy_hypothesis(
    team_id: str,
    plan_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create one append-only engineering proxy hypothesis from a saved design.

    The record proves only that a bounded experiment contract exists. It never
    upgrades the proxy to a scientific claim and always enters human review.
    """

    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_plan_id = s._normalize_required_id(
        plan_id,
        "Experiment plan id is required.",
    )
    s.team_service.get_team(normalized_team_id)
    request_payload = payload if isinstance(payload, dict) else {}
    created_by_agent = (
        s._trim_text(request_payload.get("createdByAgent"), max_length=160)
        or s.DEFAULT_OWNER_AGENT_ID
    )
    created = False
    with s._WORKFLOW_LOCK:
        plan_store = s._load_experiment_plan_store(normalized_team_id)
        plan = s._find_experiment_plan(plan_store, normalized_plan_id)
        if plan is None:
            raise s.TeamWorkflowOrchestrationError("Experiment plan not found.")
        candidate_store = s._load_candidate_store(normalized_team_id)
        fingerprint = s._experiment_proxy_hypothesis_fingerprint(
            normalized_plan_id,
            request_payload,
        )
        candidate = s._find_reusable_experiment_proxy_hypothesis(
            candidate_store,
            source_plan_id=normalized_plan_id,
            fingerprint=fingerprint,
        )
        workflow = s._load_or_create_workflow(normalized_team_id)
        if candidate is None:
            candidate = s._build_experiment_proxy_hypothesis_record(
                normalized_team_id,
                workflow,
                plan,
                request_payload,
                created_by_agent=created_by_agent,
            )
            candidate_store.setdefault("candidates", []).append(candidate)
            candidate_store["updatedAt"] = candidate["updatedAt"]
            s._write_json(
                s._candidate_store_path(normalized_team_id),
                candidate_store,
            )
            created = True
        stage_store = s._load_stage_round_store(normalized_team_id)
        rounds = s._stage_rounds(stage_store)
        experiment_status = s._experiment_planning_status(
            normalized_team_id,
            rounds,
            candidate_store,
            plan_store,
        )
        hypothesis_summary = s._experiment_hypothesis_summary(candidate)
    if created:
        s._record_workflow_event(
            "candidate.engineering_proxy_hypothesis_materialized",
            normalized_team_id,
            fields={
                "workflowId": workflow["workflowId"],
                "planId": normalized_plan_id,
                "candidateId": str(candidate.get("candidateId") or ""),
                "researchProjectId": str(plan.get("researchProjectId") or ""),
                "officialState": "candidate_only",
                "requiresReview": True,
                "noRunExecuted": True,
            },
        )
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "planId": normalized_plan_id,
        "status": "created" if created else "reused",
        "candidate": candidate,
        "hypothesisSummary": hypothesis_summary,
        "experimentStatus": experiment_status,
        "workflow": s._workflow_to_api(
            normalized_team_id,
            workflow,
            candidate_store,
        ),
        "boundaries": {
            "officialState": "candidate_only",
            "requiresHumanReview": True,
            "createsExperimentAttempt": False,
            "writesScientificClaim": False,
        },
    }

def complete_experiment_hypothesis_from_design(
    team_id: str,
    *,
    source_plan_id: str,
    hypothesis_candidate_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append a design-complete scientific hypothesis revision for review."""

    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_source_plan_id = s._normalize_required_id(
        source_plan_id,
        "Source experiment plan id is required.",
    )
    normalized_candidate_id = s._normalize_required_id(
        hypothesis_candidate_id,
        "Hypothesis candidate id is required.",
    )
    s.team_service.get_team(normalized_team_id)
    request_payload = payload if isinstance(payload, dict) else {}
    created_by_agent = (
        s._trim_text(request_payload.get("createdByAgent"), max_length=160)
        or s.DEFAULT_OWNER_AGENT_ID
    )
    created = False
    with s._WORKFLOW_LOCK:
        plan_store = s._load_experiment_plan_store(normalized_team_id)
        source_plan = s._find_experiment_plan(
            plan_store,
            normalized_source_plan_id,
        )
        if source_plan is None:
            raise s.TeamWorkflowOrchestrationError(
                "Source experiment plan not found."
            )
        candidate_store = s._load_candidate_store(normalized_team_id)
        source_candidate = s._find_candidate(
            candidate_store,
            normalized_candidate_id,
        )
        if source_candidate is None:
            raise s.TeamWorkflowOrchestrationError(
                "Source scientific hypothesis candidate not found."
            )
        normalized_request = s._scientific_hypothesis_design_request(
            request_payload
        )
        fingerprint = s._scientific_hypothesis_completion_fingerprint(
            normalized_source_plan_id,
            normalized_candidate_id,
            normalized_request,
        )
        candidate = s._find_reusable_scientific_hypothesis_completion(
            candidate_store,
            source_plan_id=normalized_source_plan_id,
            source_candidate_id=normalized_candidate_id,
            fingerprint=fingerprint,
        )
        workflow = s._load_or_create_workflow(normalized_team_id)
        if candidate is None:
            candidate = s._build_scientific_hypothesis_completion_record(
                normalized_team_id,
                workflow,
                source_plan,
                source_candidate,
                request_payload,
                created_by_agent=created_by_agent,
            )
            candidate_store.setdefault("candidates", []).append(candidate)
            candidate_store["updatedAt"] = candidate["updatedAt"]
            s._write_json(
                s._candidate_store_path(normalized_team_id),
                candidate_store,
            )
            created = True
        stage_store = s._load_stage_round_store(normalized_team_id)
        experiment_status = s._experiment_planning_status(
            normalized_team_id,
            s._stage_rounds(stage_store),
            candidate_store,
            plan_store,
        )
        hypothesis_summary = s._experiment_hypothesis_summary(candidate)
    if created:
        s._record_workflow_event(
            "candidate.scientific_hypothesis_design_completed",
            normalized_team_id,
            fields={
                "workflowId": workflow["workflowId"],
                "sourcePlanId": normalized_source_plan_id,
                "sourceCandidateId": normalized_candidate_id,
                "candidateId": str(candidate.get("candidateId") or ""),
                "researchProjectId": str(
                    source_plan.get("researchProjectId") or ""
                ),
                "requiresReview": True,
                "noRunExecuted": True,
            },
        )
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "planId": normalized_source_plan_id,
        "sourceCandidateId": normalized_candidate_id,
        "status": "created" if created else "reused",
        "candidate": candidate,
        "hypothesisSummary": hypothesis_summary,
        "experimentStatus": experiment_status,
        "workflow": s._workflow_to_api(
            normalized_team_id,
            workflow,
            candidate_store,
        ),
        "boundaries": {
            "appendOnlyRevision": True,
            "requiresHumanReview": True,
            "createsExperimentAttempt": False,
            "writesScientificClaim": False,
        },
    }
