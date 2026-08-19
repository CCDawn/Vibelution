"""Experiment plan / catalog / freeze / baseline operations (Clarity B6 split from experiment.py).

Late-bound facade keeps route imports and monkeypatches on
``team_workflow_orchestration_service`` stable during mechanical splits.
"""

from __future__ import annotations

from typing import Any


def _service():
    from core.web.services import team_workflow_orchestration_service

    return team_workflow_orchestration_service


def get_experiment_planning_status(team_id: str) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    s.team_service.assert_team_exists(normalized_team_id)
    with s._WORKFLOW_LOCK:
        store = s._load_stage_round_store(normalized_team_id)
        rounds = s._stage_rounds(store)
        candidate_store = s._load_candidate_store(normalized_team_id)
        plan_store = s._load_experiment_plan_store(normalized_team_id)
    return s._experiment_planning_status(normalized_team_id, rounds, candidate_store, plan_store)

def get_experiment_method_catalog(team_id: str) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    s.team_service.get_team(normalized_team_id)
    methods = s.experiment_contract.list_experiment_methods()
    for method in methods:
        method_id = str(method.get("methodId") or "")
        method["adapterAvailability"] = {
            mode: s.experiment_contract.resolve_adapter_selection(method_id, mode)
            for mode in s.experiment_contract.RESEARCH_MODES
        }
    return {
        "schemaVersion": s.experiment_contract.SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "researchModes": s.experiment_contract.list_research_modes(),
        "experimentPurposes": s.experiment_contract.list_experiment_purposes(),
        "methods": methods,
        "adapters": s.experiment_contract.list_experiment_adapters(),
        "boundaries": {
            "methodCatalogSource": "backend_registry",
            "environmentProbeRole": "adapter_preflight",
            "evidenceReviewRole": "upstream_research_stage",
            "llmSelectsAdapterId": False,
        },
    }

def create_experiment_plan(team_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    team = s.team_service.get_team(normalized_team_id)
    request_payload = payload if isinstance(payload, dict) else {}
    created_by_agent = s._trim_text(request_payload.get("createdByAgent"), max_length=160) or s.DEFAULT_OWNER_AGENT_ID
    with s._WORKFLOW_LOCK:
        workflow = s._load_or_create_workflow(normalized_team_id)
        store = s._load_stage_round_store(normalized_team_id)
        rounds = s._stage_rounds(store)
        stage_round = s._select_experiment_stage_round(request_payload, rounds)
        research_project = s.resolve_research_project_identity(
            normalized_team_id,
            s._trim_text(
                stage_round.get("researchProjectId")
                or request_payload.get("researchProjectId"),
                max_length=160,
            ),
        )
        candidate_store = s._load_candidate_store(normalized_team_id)
        selected_hypotheses = s._select_experiment_hypothesis_candidates(candidate_store, request_payload)
        plan_store = s._load_experiment_plan_store(normalized_team_id)
        plan = s._build_experiment_plan_record(
            normalized_team_id,
            workflow,
            stage_round,
            selected_hypotheses,
            request_payload,
            created_by_agent=created_by_agent,
        )
        plan["researchProjectId"] = research_project["projectId"]
        plan["experimentName"] = research_project["name"]
        stage_round["researchProjectId"] = research_project["projectId"]
        stage_round["experimentName"] = research_project["name"]
        memory_context = s._research_stage_memory_context(
            normalized_team_id,
            stage_type="experiment",
            research_question=str((plan.get("experimentContract") or {}).get("researchQuestion") or plan.get("goal") or plan.get("topic") or ""),
            actor_agent_id=created_by_agent,
            control_plan=plan,
        )
        plan["memoryContext"] = s.deepcopy(memory_context)
        stage_round["memoryContext"] = s.deepcopy(memory_context)
        now = plan["updatedAt"]
        plan_store.setdefault("plans", []).append(plan)
        plan_store["activePlanId"] = plan["planId"]
        plan_store["updatedAt"] = now
        s._write_json(s._experiment_plan_store_path(normalized_team_id), plan_store)
        stage_round["experimentPlanRef"] = {
            "planId": plan["planId"],
            "status": plan["status"],
            "storagePath": s._relative_path(s._experiment_plan_store_path(normalized_team_id)),
            "updatedAt": now,
        }
        planning_contract = stage_round.get("planningContract") if isinstance(stage_round.get("planningContract"), dict) else {}
        planning_contract["currentPlanId"] = plan["planId"]
        planning_contract["planStoragePath"] = s._relative_path(s._experiment_plan_store_path(normalized_team_id))
        planning_contract["memoryContextId"] = memory_context["contextId"]
        planning_contract["autoExecution"] = False
        planning_contract["requiresUserDecision"] = True
        stage_round["planningContract"] = planning_contract
        stage_round["status"] = "planning"
        stage_round["updatedAt"] = now
        store["rounds"] = rounds
        store["updatedAt"] = now
        s._write_json(s._stage_round_store_path(normalized_team_id), store)
        workflow["updatedAt"] = now
        workflow["activeWorkflowItems"] = s._upsert_active_item(
            workflow.get("activeWorkflowItems"),
            candidate_id=stage_round["stageRoundId"],
            current_node=s.RESEARCH_STAGE_DEFAULTS["experiment"]["currentNode"],
            status="experiment_plan_drafted",
            transfer_id="",
        )
        s._write_json(s._workflow_path(normalized_team_id), workflow)
        status_payload = s._experiment_planning_status(normalized_team_id, rounds, candidate_store, plan_store)
        stage_round_status = s.get_research_stage_round_status(normalized_team_id)
    s.lock_research_project_name(
        normalized_team_id,
        research_project["projectId"],
        reason="first_experiment_task",
    )
    s._record_workflow_event(
        "experiment_plan.drafted",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "stageRoundId": stage_round["stageRoundId"],
            "planId": plan["planId"],
            "selectedHypothesisCount": len(plan.get("selectedHypotheses") or []),
            "experimentContractSchemaVersion": int((plan.get("experimentContract") or {}).get("schemaVersion") or 0),
            "researchMode": str((plan.get("experimentContract") or {}).get("researchMode") or ""),
            "experimentMethod": str((plan.get("experimentContract") or {}).get("experimentMethod") or ""),
            "adapterAvailable": bool((plan.get("contractValidation") or {}).get("adapterAvailable")),
            "contractValid": bool((plan.get("contractValidation") or {}).get("valid")),
            "readyForPlanReview": bool((plan.get("readiness") or {}).get("readyForPlanReview")),
            "readyForFullRun": False,
            "createdByAgent": created_by_agent,
            "memoryContextId": str((plan.get("memoryContext") or {}).get("contextId") or ""),
            "memoryKnowledgeItemCount": int(((plan.get("memoryContext") or {}).get("retrieval") or {}).get("knowledgeItemCount") or 0),
            "memoryNegativeExperimentCount": int(((plan.get("memoryContext") or {}).get("retrieval") or {}).get("negativeExperimentCount") or 0),
        },
    )
    return {
        "plan": plan,
        "status": status_payload,
        "stageRound": stage_round,
        "stageRoundStatus": stage_round_status,
        "workflow": s._workflow_to_api(normalized_team_id, workflow, candidate_store),
        "team": {"teamId": team.get("teamId", normalized_team_id), "name": team.get("name", "")},
        "boundaries": s._experiment_planning_boundaries(),
    }

def create_experiment_plan_revision_from_iteration(
    team_id: str,
    *,
    source_plan_id: str,
    loop_id: str,
    decision_id: str,
    proposal_id: str,
    idempotency_key: str,
    decision: str,
    rationale: str,
    next_template_id: str,
    next_actions: list[str],
    allowed_variable_changes: list[str],
    frozen_controls: list[str],
    created_by_agent: str,
) -> dict[str, Any]:
    """Clone a governed plan into one idempotent, explicitly gated next-design draft."""

    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_source_plan_id = s._normalize_required_id(source_plan_id, "Source experiment plan id is required.")
    normalized_proposal_id = s._normalize_required_id(proposal_id, "Iteration proposal id is required.")
    normalized_allowed_changes = [
        text
        for item in allowed_variable_changes
        if (text := s._trim_text(item, max_length=240))
    ][:24]
    normalized_frozen_controls = [
        text
        for item in frozen_controls
        if (text := s._trim_text(item, max_length=360))
    ][:24]
    if not normalized_allowed_changes or not normalized_frozen_controls:
        raise s.TeamWorkflowOrchestrationError(
            "Iteration design requires explicit allowed variable changes and frozen controls."
        )
    with s._WORKFLOW_LOCK:
        plan_store = s._load_experiment_plan_store(normalized_team_id)
        plans = s._experiment_plans(plan_store)
        for existing in plans:
            gate = existing.get("designGate") if isinstance(existing.get("designGate"), dict) else {}
            same_proposal = str(gate.get("sourceProposalId") or "") == normalized_proposal_id
            same_idempotent_request = bool(idempotency_key) and (
                str(gate.get("sourceLoopId") or "") == loop_id
                and str(gate.get("sourceIdempotencyKey") or "") == idempotency_key
            )
            if same_proposal or same_idempotent_request:
                contract = existing.get("experimentContract") if isinstance(existing.get("experimentContract"), dict) else {}
                iteration = contract.get("iterationContract") if isinstance(contract.get("iterationContract"), dict) else {}
                if next_template_id and str(iteration.get("nextTemplateId") or "") != next_template_id:
                    iteration["nextTemplateId"] = next_template_id
                    contract["iterationContract"] = iteration
                    existing["experimentContract"] = contract
                    now = s.utc_now_iso()
                    existing["updatedAt"] = now
                    plan_store["updatedAt"] = now
                    s._write_json(s._experiment_plan_store_path(normalized_team_id), plan_store)
                return {"status": "reused", "plan": existing}
        source_plan = s._find_experiment_plan(plan_store, normalized_source_plan_id)
        if source_plan is None:
            raise s.TeamWorkflowOrchestrationError("Source experiment plan not found for iteration draft.")
        source_contract = (
            source_plan.get("experimentContract")
            if isinstance(source_plan.get("experimentContract"), dict)
            else {}
        )
        source_legacy = (
            source_plan.get("experimentPlan")
            if isinstance(source_plan.get("experimentPlan"), dict)
            else {}
        )
        source_iteration = (
            source_contract.get("iterationContract")
            if isinstance(source_contract.get("iterationContract"), dict)
            else {}
        )
        next_revision = max([s._experiment_plan_revision(plan) for plan in plans] or [0]) + 1
        iteration_contract = {
            **s.deepcopy(source_iteration),
            "sourceLoopId": loop_id,
            "sourceDecisionId": decision_id,
            "sourceProposalId": normalized_proposal_id,
            "sourceIdempotencyKey": idempotency_key,
            "sourceDecision": decision,
            "sourceRationale": rationale,
            "nextTemplateId": next_template_id,
            "nextActions": list(next_actions),
            "allowedChanges": normalized_allowed_changes,
            "frozenControls": normalized_frozen_controls,
        }
        adapter_selection = (
            source_contract.get("adapterSelection")
            if isinstance(source_contract.get("adapterSelection"), dict)
            else {}
        )
        request_payload = {
            "stageRoundId": str(source_plan.get("stageRoundId") or ""),
            "title": f"{str(source_plan.get('title') or 'Experiment design')} · v{next_revision} draft",
            "createdByAgent": created_by_agent,
            "hypothesisCandidateIds": list(source_plan.get("hypothesisCandidateIds") or []),
            "dataset": source_legacy.get("dataset"),
            "metric": source_legacy.get("metric"),
            "baseline": source_legacy.get("baseline"),
            "smokePlan": source_legacy.get("smokePlan"),
            "researchProfileId": source_contract.get("researchProfileId"),
            "researchQuestion": source_contract.get("researchQuestion"),
            "researchMode": source_contract.get("researchMode"),
            "experimentPurpose": source_contract.get("purpose"),
            "experimentMethod": source_contract.get("experimentMethod"),
            "requestedAdapterId": adapter_selection.get("requestedAdapterId")
            or adapter_selection.get("resolvedAdapterId"),
            "objective": source_contract.get("objective"),
            "constraints": list(source_contract.get("constraints") or []),
            "methodConfig": s.deepcopy(source_contract.get("methodConfig") or {}),
            "metricContract": s.deepcopy(source_contract.get("metricContract") or {}),
            "decisionContract": s.deepcopy(source_contract.get("decisionContract") or {}),
            "artifactContract": s.deepcopy(source_contract.get("artifactContract") or {}),
            "reproducibilityContract": s.deepcopy(source_contract.get("reproducibilityContract") or {}),
            "iterationContract": iteration_contract,
            "recommendation": s.deepcopy(source_contract.get("recommendation") or {}),
            "revision": next_revision,
            "supersedesPlanId": normalized_source_plan_id,
            "notes": f"Generated from {decision}: {rationale}",
        }
        created = create_experiment_plan(normalized_team_id, request_payload)
    s._record_workflow_event(
        "experiment_plan.iteration_draft_created",
        normalized_team_id,
        fields={
            "sourcePlanId": normalized_source_plan_id,
            "planId": str((created.get("plan") or {}).get("planId") or ""),
            "revision": next_revision,
            "loopId": loop_id,
            "decisionId": decision_id,
            "proposalId": normalized_proposal_id,
            "requiresExplicitFreeze": True,
        },
    )
    return {"status": "created", "plan": created["plan"]}

def create_experiment_plan_revision_from_hypothesis(
    team_id: str,
    *,
    source_plan_id: str,
    hypothesis_candidate_id: str,
    created_by_agent: str,
    idempotency_key: str = "",
) -> dict[str, Any]:
    """Clone one design after an explicitly approved hypothesis selection."""

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
    normalized_created_by = (
        s._trim_text(created_by_agent, max_length=160)
        or s.DEFAULT_OWNER_AGENT_ID
    )
    normalized_idempotency_key = (
        s._trim_text(idempotency_key, max_length=240)
        or f"{normalized_source_plan_id}:{normalized_candidate_id}:hypothesis-revision"
    )
    with s._WORKFLOW_LOCK:
        plan_store = s._load_experiment_plan_store(normalized_team_id)
        plans = s._experiment_plans(plan_store)
        for existing in plans:
            selection = (
                existing.get("hypothesisSelection")
                if isinstance(existing.get("hypothesisSelection"), dict)
                else {}
            )
            if (
                str(selection.get("sourcePlanId") or "")
                == normalized_source_plan_id
                and str(selection.get("hypothesisCandidateId") or "")
                == normalized_candidate_id
                and str(selection.get("idempotencyKey") or "")
                == normalized_idempotency_key
            ):
                return {
                    "status": "reused",
                    "plan": existing,
                    "experimentStatus": s.get_experiment_planning_status(
                        normalized_team_id
                    ),
                }
        source_plan = s._find_experiment_plan(
            plan_store,
            normalized_source_plan_id,
        )
        if source_plan is None:
            raise s.TeamWorkflowOrchestrationError(
                "Source experiment plan not found for hypothesis revision."
            )
        candidate_store = s._load_candidate_store(normalized_team_id)
        candidate = s._find_candidate(candidate_store, normalized_candidate_id)
        if candidate is None:
            raise s.TeamWorkflowOrchestrationError(
                "Hypothesis candidate not found for experiment revision."
            )
        if not s._experiment_hypothesis_is_ready(candidate):
            raise s.TeamWorkflowOrchestrationError(
                "Hypothesis candidate must be valid, complete, and approved before creating a new design revision."
            )
        candidate_summary = s._experiment_hypothesis_summary(candidate)
        candidate_source_plan_id = s._trim_text(
            candidate_summary.get("sourcePlanId"),
            max_length=160,
        )
        if (
            candidate_summary.get("hypothesisKind") == "engineering_proxy"
            and candidate_source_plan_id != normalized_source_plan_id
        ):
            raise s.TeamWorkflowOrchestrationError(
                "Engineering proxy hypothesis must revise the experiment plan it was derived from."
            )
        source_project_id = s._trim_text(
            source_plan.get("researchProjectId"),
            max_length=160,
        )
        candidate_project_id = s._trim_text(
            candidate_summary.get("researchProjectId"),
            max_length=160,
        )
        if (
            source_project_id
            and candidate_project_id
            and source_project_id != candidate_project_id
        ):
            raise s.TeamWorkflowOrchestrationError(
                "Hypothesis candidate belongs to a different research project."
            )
        review = s._experiment_hypothesis_review_state(candidate)
        metadata = (
            candidate.get("metadata")
            if isinstance(candidate.get("metadata"), dict)
            else {}
        )
        design_completion = (
            metadata.get("designCompletion")
            if isinstance(metadata.get("designCompletion"), dict)
            else {}
        )
        proposed_request = (
            design_completion.get("proposedExperimentRequest")
            if isinstance(
                design_completion.get("proposedExperimentRequest"),
                dict,
            )
            else {}
        )
        source_contract = (
            source_plan.get("experimentContract")
            if isinstance(source_plan.get("experimentContract"), dict)
            else {}
        )
        source_legacy = (
            source_plan.get("experimentPlan")
            if isinstance(source_plan.get("experimentPlan"), dict)
            else {}
        )
        adapter_selection = (
            source_contract.get("adapterSelection")
            if isinstance(source_contract.get("adapterSelection"), dict)
            else {}
        )
        next_revision = max(
            [s._experiment_plan_revision(plan) for plan in plans] or [0]
        ) + 1
        request_payload = {
            "stageRoundId": str(source_plan.get("stageRoundId") or ""),
            "researchProjectId": str(source_plan.get("researchProjectId") or ""),
            "title": f"{str(source_plan.get('title') or 'Experiment design')} · v{next_revision}",
            "createdByAgent": normalized_created_by,
            "hypothesisCandidateIds": [normalized_candidate_id],
            "dataset": source_legacy.get("dataset"),
            "metric": source_legacy.get("metric"),
            "baseline": source_legacy.get("baseline"),
            "smokePlan": source_legacy.get("smokePlan"),
            "researchProfileId": source_contract.get("researchProfileId"),
            "researchQuestion": source_contract.get("researchQuestion"),
            "researchMode": source_contract.get("researchMode"),
            "experimentPurpose": source_contract.get("purpose"),
            "experimentMethod": source_contract.get("experimentMethod"),
            "requestedAdapterId": adapter_selection.get("requestedAdapterId")
            or adapter_selection.get("resolvedAdapterId"),
            "objective": source_contract.get("objective"),
            "constraints": list(source_contract.get("constraints") or []),
            "methodConfig": s.deepcopy(source_contract.get("methodConfig") or {}),
            "metricContract": s.deepcopy(
                source_contract.get("metricContract") or {}
            ),
            "decisionContract": s.deepcopy(
                source_contract.get("decisionContract") or {}
            ),
            "artifactContract": s.deepcopy(
                source_contract.get("artifactContract") or {}
            ),
            "reproducibilityContract": s.deepcopy(
                source_contract.get("reproducibilityContract") or {}
            ),
            "iterationContract": s.deepcopy(
                source_contract.get("iterationContract") or {}
            ),
            "recommendation": s.deepcopy(
                source_contract.get("recommendation") or {}
            ),
            "revision": next_revision,
            "supersedesPlanId": normalized_source_plan_id,
            "hypothesisSelection": {
                "sourcePlanId": normalized_source_plan_id,
                "hypothesisCandidateId": normalized_candidate_id,
                "reviewRecordId": review["reviewRecordId"],
                "reviewedAt": review["reviewedAt"],
                "selectedByAgent": normalized_created_by,
                "selectedAt": s.utc_now_iso(),
                "idempotencyKey": normalized_idempotency_key,
            },
            "notes": (
                "Created from an explicitly approved hypothesis selection. "
                "The new design remains draft and requires explicit freeze."
            ),
        }
        if candidate_summary.get("hypothesisKind") == "scientific_revision":
            if not proposed_request:
                raise s.TeamWorkflowOrchestrationError(
                    "Scientific hypothesis revision is missing its proposed experiment design."
                )
            request_payload.update(s.deepcopy(proposed_request))
            request_payload.update(
                {
                    "stageRoundId": str(
                        source_plan.get("stageRoundId") or ""
                    ),
                    "researchProjectId": str(
                        source_plan.get("researchProjectId") or ""
                    ),
                    "title": (
                        f"{str(source_plan.get('title') or 'Experiment design')} "
                        f"· v{next_revision}"
                    ),
                    "createdByAgent": normalized_created_by,
                    "hypothesisCandidateIds": [normalized_candidate_id],
                    "dataset": candidate_summary["experimentPlan"]["dataset"],
                    "metric": candidate_summary["experimentPlan"]["metric"],
                    "baseline": candidate_summary["experimentPlan"]["baseline"],
                    "smokePlan": candidate_summary["experimentPlan"]["smokePlan"],
                    "revision": next_revision,
                    "supersedesPlanId": normalized_source_plan_id,
                    "hypothesisSelection": {
                        "sourcePlanId": normalized_source_plan_id,
                        "hypothesisCandidateId": normalized_candidate_id,
                        "reviewRecordId": review["reviewRecordId"],
                        "reviewedAt": review["reviewedAt"],
                        "selectedByAgent": normalized_created_by,
                        "selectedAt": s.utc_now_iso(),
                        "idempotencyKey": normalized_idempotency_key,
                    },
                    "notes": (
                        "Created from an explicitly approved append-only "
                        "scientific hypothesis revision. No experiment was run."
                    ),
                }
            )
        created = create_experiment_plan(normalized_team_id, request_payload)
    s._record_workflow_event(
        "experiment_plan.hypothesis_revision_created",
        normalized_team_id,
        fields={
            "sourcePlanId": normalized_source_plan_id,
            "planId": str((created.get("plan") or {}).get("planId") or ""),
            "hypothesisCandidateId": normalized_candidate_id,
            "reviewRecordId": review["reviewRecordId"],
            "revision": next_revision,
            "requiresExplicitFreeze": True,
            "createsExperimentAttempt": False,
        },
    )
    return {
        "status": "created",
        "plan": created["plan"],
        "experimentStatus": created["status"],
        "stageRound": created["stageRound"],
        "stageRoundStatus": created["stageRoundStatus"],
        "workflow": created["workflow"],
        "boundaries": created["boundaries"],
    }

def resume_experiment_hypothesis(team_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resume one hypothesis: point the workbench at the plan tracking it.

    The hypothesis' checkpoint (``hypothesisProgress``) is the resume pointer;
    switching ``activePlanId`` makes the existing status payload render that
    plan's next uncompleted step. Idempotent: resuming the already-active plan
    only re-derives progress.
    """

    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    team = s.team_service.get_team(normalized_team_id)
    request_payload = payload if isinstance(payload, dict) else {}
    normalized_candidate_id = s._normalize_required_id(
        request_payload.get("hypothesisCandidateId"),
        "Hypothesis candidate id is required.",
    )
    with s._WORKFLOW_LOCK:
        candidate_store = s._load_candidate_store(normalized_team_id)
        candidate = s._find_candidate(candidate_store, normalized_candidate_id)
        if candidate is None:
            raise s.TeamWorkflowOrchestrationError("Hypothesis candidate not found.")
        plan_store = s._load_experiment_plan_store(normalized_team_id)
        plans = [
            plan
            for plan in s._experiment_plans(plan_store)
            if s._hypothesis_progress_plan_tracks(plan, normalized_candidate_id)
        ]
        if not plans:
            raise s.TeamWorkflowOrchestrationError(
                "No experiment plan tracks this hypothesis candidate yet."
            )
        active_plan_id = str(plan_store.get("activePlanId") or "")
        plans.sort(
            key=lambda plan: (
                str(plan.get("planId") or "") == active_plan_id,
                _hypothesis_progress_rank(plan, normalized_candidate_id),
                str(plan.get("updatedAt") or ""),
            ),
            reverse=True,
        )
        plan = plans[0]
        s._refresh_hypothesis_progress(plan)
        entry = s._hypothesis_progress_find(plan, normalized_candidate_id)
        summary = s._hypothesis_progress_summary(entry)
        switched = str(plan.get("planId") or "") != active_plan_id
        if switched:
            plan_store["activePlanId"] = plan["planId"]
            plan_store["updatedAt"] = s.utc_now_iso()
            s._write_json(s._experiment_plan_store_path(normalized_team_id), plan_store)
        store = s._load_stage_round_store(normalized_team_id)
        rounds = s._stage_rounds(store)
        status_payload = s._experiment_planning_status(normalized_team_id, rounds, candidate_store, plan_store)
    s._record_workflow_event(
        "experiment_plan.hypothesis_resumed",
        normalized_team_id,
        fields={
            "planId": str(plan.get("planId") or ""),
            "hypothesisCandidateId": normalized_candidate_id,
            "nextStep": str((summary or {}).get("nextStep") or ""),
            "completedCount": int((summary or {}).get("completedCount") or 0),
            "switchedActivePlan": switched,
        },
    )
    return {
        "status": "resumed",
        "plan": plan,
        "resume": {
            **(summary or {}),
            "switchedActivePlan": switched,
        },
        "experimentStatus": status_payload,
        "team": {"teamId": team.get("teamId", normalized_team_id), "name": team.get("name", "")},
        "boundaries": s._experiment_planning_boundaries(),
    }


def _hypothesis_progress_rank(plan: dict[str, Any], candidate_id: str) -> int:
    s = _service()
    entry = s._hypothesis_progress_find(plan, candidate_id)
    if not isinstance(entry, dict):
        return -1
    return int(entry.get("completedCount") or 0)


def freeze_experiment_design(team_id: str, plan_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_plan_id = s._normalize_required_id(plan_id, "Experiment plan id is required.")
    request_payload = payload if isinstance(payload, dict) else {}
    frozen_by_agent = s._trim_text(request_payload.get("frozenByAgent"), max_length=160) or s.DEFAULT_OWNER_AGENT_ID
    with s._WORKFLOW_LOCK:
        plan_store = s._load_experiment_plan_store(normalized_team_id)
        plan = s._find_experiment_plan(plan_store, normalized_plan_id)
        if plan is None:
            raise s.TeamWorkflowOrchestrationError("Experiment plan not found.")
        gate = plan.get("designGate") if isinstance(plan.get("designGate"), dict) else None
        if gate is None:
            raise s.TeamWorkflowOrchestrationError("Experiment plan uses the legacy derived design gate and cannot be explicitly frozen.")
        validation = plan.get("contractValidation") if isinstance(plan.get("contractValidation"), dict) else {}
        readiness = plan.get("readiness") if isinstance(plan.get("readiness"), dict) else {}
        if validation.get("valid") is not True or readiness.get("readyForPlanReview") is not True:
            raise s.TeamWorkflowOrchestrationError("Experiment design must be valid and review-ready before it can be frozen.")
        contract = plan.get("experimentContract") if isinstance(plan.get("experimentContract"), dict) else {}
        iteration_contract = (
            contract.get("iterationContract")
            if isinstance(contract.get("iterationContract"), dict)
            else {}
        )
        governed_iteration = bool(
            str(gate.get("sourceProposalId") or "")
            or str(iteration_contract.get("sourceDecision") or "")
            in {"promote_to_iteration", "repair_and_repeat"}
        )
        if governed_iteration:
            allowed_changes = list(
                iteration_contract.get("allowedChanges")
                or iteration_contract.get("allowedVariableChanges")
                or []
            )
            frozen_controls = list(iteration_contract.get("frozenControls") or [])
            if not allowed_changes or not frozen_controls:
                raise s.TeamWorkflowOrchestrationError(
                    "Iteration design requires explicit allowed variable changes and frozen controls before freeze."
                )
        if str(gate.get("status") or "") == "frozen":
            return {"status": "already_frozen", "plan": plan}
        now = s.utc_now_iso()
        gate["status"] = "frozen"
        gate["frozenAt"] = now
        gate["frozenByAgent"] = frozen_by_agent
        plan["designGate"] = gate
        plan["status"] = "design_frozen"
        plan["updatedAt"] = now
        s._refresh_experiment_bounded_smoke_readiness(plan)
        s._refresh_hypothesis_progress(plan)
        contract["status"] = "frozen"
        plan["experimentContract"] = contract
        plan_store["activePlanId"] = normalized_plan_id
        plan_store["updatedAt"] = now
        s._write_json(s._experiment_plan_store_path(normalized_team_id), plan_store)
        stage_store = s._load_stage_round_store(normalized_team_id)
        rounds = s._stage_rounds(stage_store)
        stage_round = s._find_stage_round(rounds, str(plan.get("stageRoundId") or ""))
        if stage_round is not None:
            ref = stage_round.get("experimentPlanRef") if isinstance(stage_round.get("experimentPlanRef"), dict) else {}
            ref.update({"planId": normalized_plan_id, "status": plan["status"], "updatedAt": now})
            stage_round["experimentPlanRef"] = ref
            stage_round["updatedAt"] = now
            stage_store["rounds"] = rounds
            stage_store["updatedAt"] = now
            s._write_json(s._stage_round_store_path(normalized_team_id), stage_store)
        candidate_store = s._load_candidate_store(normalized_team_id)
        status_payload = s._experiment_planning_status(normalized_team_id, rounds, candidate_store, plan_store)
    s._record_workflow_event(
        "experiment_plan.design_frozen",
        normalized_team_id,
        fields={
            "planId": normalized_plan_id,
            "revision": s._experiment_plan_revision(plan),
            "frozenByAgent": frozen_by_agent,
            "sourceProposalId": str(gate.get("sourceProposalId") or ""),
        },
    )
    return {"status": "frozen", "plan": plan, "experimentStatus": status_payload}

def register_experiment_baseline_artifact(team_id: str, plan_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_plan_id = s._normalize_required_id(plan_id, "Experiment plan id is required.")
    team = s.team_service.get_team(normalized_team_id)
    request_payload = payload if isinstance(payload, dict) else {}
    registered_by_agent = s._trim_text(request_payload.get("registeredByAgent"), max_length=160) or s.DEFAULT_OWNER_AGENT_ID
    with s._WORKFLOW_LOCK:
        workflow = s._load_or_create_workflow(normalized_team_id)
        stage_store = s._load_stage_round_store(normalized_team_id)
        rounds = s._stage_rounds(stage_store)
        candidate_store = s._load_candidate_store(normalized_team_id)
        plan_store = s._load_experiment_plan_store(normalized_team_id)
        plan = s._find_experiment_plan(plan_store, normalized_plan_id)
        if plan is None:
            raise s.TeamWorkflowOrchestrationError("Experiment plan not found.")
        s._require_explicit_experiment_design_frozen(plan)
        artifact = s._experiment_baseline_artifact_record(plan, request_payload, registered_by_agent=registered_by_agent)
        baseline_selection = plan.get("baselineSelection") if isinstance(plan.get("baselineSelection"), dict) else {}
        artifacts = [item for item in list(baseline_selection.get("artifacts") or []) if isinstance(item, dict)]
        artifacts.append(artifact)
        baseline_selection["baseline"] = artifact["baseline"]
        baseline_selection["status"] = "active_artifact_registered"
        baseline_selection["activeBaselineReady"] = True
        baseline_selection["activeBaselineArtifactId"] = artifact["artifactId"]
        baseline_selection["activeBaselineArtifact"] = artifact
        baseline_selection["artifacts"] = artifacts[-12:]
        baseline_selection["reason"] = "Active baseline artifact is registered; smoke execution still requires an explicit user trigger."
        plan["baselineSelection"] = baseline_selection
        plan["status"] = "baseline_ready"
        plan["updatedAt"] = artifact["registeredAt"]
        s._refresh_experiment_plan_readiness(plan)
        plan_store["activePlanId"] = plan["planId"]
        plan_store["updatedAt"] = artifact["registeredAt"]
        s._write_json(s._experiment_plan_store_path(normalized_team_id), plan_store)
        stage_round = s._find_stage_round(rounds, str(plan.get("stageRoundId") or ""))
        if stage_round is not None:
            stage_round["experimentPlanRef"] = {
                "planId": plan["planId"],
                "status": plan["status"],
                "storagePath": s._relative_path(s._experiment_plan_store_path(normalized_team_id)),
                "baselineArtifactRef": {"artifactId": artifact["artifactId"], "artifactPath": artifact["artifactPath"]},
                "updatedAt": artifact["registeredAt"],
            }
            planning_contract = stage_round.get("planningContract") if isinstance(stage_round.get("planningContract"), dict) else {}
            planning_contract["currentPlanId"] = plan["planId"]
            planning_contract["activeBaselineArtifactId"] = artifact["artifactId"]
            planning_contract["readyForSmoke"] = bool((plan.get("readiness") or {}).get("readyForSmoke"))
            planning_contract["autoExecution"] = False
            planning_contract["requiresUserDecision"] = True
            stage_round["planningContract"] = planning_contract
            stage_round["status"] = "planning"
            stage_round["updatedAt"] = artifact["registeredAt"]
            stage_store["rounds"] = rounds
            stage_store["updatedAt"] = artifact["registeredAt"]
            s._write_json(s._stage_round_store_path(normalized_team_id), stage_store)
        workflow["updatedAt"] = artifact["registeredAt"]
        workflow["activeWorkflowItems"] = s._upsert_active_item(
            workflow.get("activeWorkflowItems"),
            candidate_id=str(plan.get("stageRoundId") or plan["planId"]),
            current_node=s.RESEARCH_STAGE_DEFAULTS["experiment"]["currentNode"],
            status="baseline_artifact_registered",
            transfer_id="",
        )
        s._write_json(s._workflow_path(normalized_team_id), workflow)
        status_payload = s._experiment_planning_status(normalized_team_id, rounds, candidate_store, plan_store)
        stage_round_status = s.get_research_stage_round_status(normalized_team_id)
    s._record_workflow_event(
        "experiment_plan.baseline_artifact_registered",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "stageRoundId": str(plan.get("stageRoundId") or ""),
            "planId": plan["planId"],
            "baselineArtifactId": artifact["artifactId"],
            "readyForSmoke": bool((plan.get("readiness") or {}).get("readyForSmoke")),
            "readyForFullRun": False,
            "registeredByAgent": registered_by_agent,
        },
    )
    return {
        "baselineArtifact": artifact,
        "plan": plan,
        "status": status_payload,
        "stageRoundStatus": stage_round_status,
        "workflow": s._workflow_to_api(normalized_team_id, workflow, candidate_store),
        "team": {"teamId": team.get("teamId", normalized_team_id), "name": team.get("name", "")},
        "boundaries": s._experiment_planning_boundaries(),
    }


def bind_frozen_protocol_to_experiment_plan(
    team_id: str,
    frozen: dict[str, Any] | None,
) -> dict[str, Any]:
    """Copy a research-workflow frozen protocol into the experiment plan store.

    Protocol freeze writes ``frozen_protocol`` without updating ``designGate``.
    Smoke still reads the plan store, so historical SCI-096 retries 422 with
    ``Experiment plan not found`` or an unfrozen draft. This bind is idempotent.
    """
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    payload = frozen if isinstance(frozen, dict) else {}
    nested = payload.get("payload")
    if isinstance(nested, dict) and (
        nested.get("planId") or nested.get("protocolId") or nested.get("protocol")
    ):
        payload = nested
    protocol = payload.get("protocol") if isinstance(payload.get("protocol"), dict) else {}
    plan_id = str(
        payload.get("planId") or payload.get("protocolId") or protocol.get("planId") or ""
    ).strip()
    if not plan_id:
        raise s.TeamWorkflowOrchestrationError("Experiment plan not found.")
    smoke_plan = protocol.get("smokePlan")
    if not s._has_value(smoke_plan):
        smoke_plan = protocol.get("smoke_plan")
    now = s.utc_now_iso()
    with s._WORKFLOW_LOCK:
        plan_store = s._load_experiment_plan_store(normalized_team_id)
        plans = [item for item in list(plan_store.get("plans") or []) if isinstance(item, dict)]
        plan = next((item for item in plans if str(item.get("planId") or "") == plan_id), None)
        if plan is None:
            plan = {
                "planId": plan_id,
                "teamId": normalized_team_id,
                "status": "design_frozen",
                "createdAt": now,
                "experimentPlan": {},
                "designGate": {},
            }
            plans.append(plan)
        experiment_plan = (
            plan.get("experimentPlan") if isinstance(plan.get("experimentPlan"), dict) else {}
        )
        for field, source in (
            ("dataset", protocol.get("dataset")),
            ("metric", protocol.get("metric")),
            ("baseline", protocol.get("baseline")),
        ):
            if s._has_value(source):
                experiment_plan[field] = source
        if s._has_value(smoke_plan):
            experiment_plan["smokePlan"] = smoke_plan
        plan["experimentPlan"] = experiment_plan
        gate = plan.get("designGate") if isinstance(plan.get("designGate"), dict) else {}
        gate["status"] = "frozen"
        gate["frozenAt"] = str(gate.get("frozenAt") or now)
        gate["source"] = str(gate.get("source") or "research_workflow_frozen_protocol")
        plan["designGate"] = gate
        plan["status"] = "design_frozen"
        _stamp_frozen_protocol_formal_adapter(s, plan, protocol=protocol)
        s._refresh_experiment_plan_readiness(plan)
        plan["updatedAt"] = now
        plan_store["plans"] = plans
        plan_store["activePlanId"] = plan_id
        plan_store["updatedAt"] = now
        s._write_json(s._experiment_plan_store_path(normalized_team_id), plan_store)
    return dict(plan)


def _stamp_frozen_protocol_formal_adapter(
    s: Any,
    plan: dict[str, Any],
    *,
    protocol: dict[str, Any],
) -> None:
    """Frozen protocol bind is the explicit FashionMNIST adapter selection.

    ``fashion_mnist_predictive_coding_multi_seed`` requiresExplicitSelection and
    is never a catalog default. The governed freeze of this workflow *is* that
    selection. Without it, ``controlled_run`` fails at
    ``_require_formal_full_run_ready``.
    """
    adapter_id = s.formal_runner.FASHION_MNIST_MULTI_SEED_ADAPTER
    contract = (
        plan.get("experimentContract")
        if isinstance(plan.get("experimentContract"), dict)
        else {}
    )
    selection = (
        contract.get("adapterSelection")
        if isinstance(contract.get("adapterSelection"), dict)
        else {}
    )
    if str(selection.get("resolvedAdapterId") or "") == adapter_id:
        s.experiment_contract.sync_plan_record_contract_status(plan)
        return
    experiment_plan = (
        plan.get("experimentPlan") if isinstance(plan.get("experimentPlan"), dict) else {}
    )
    raw_seeds = protocol.get("seeds")
    if raw_seeds is None:
        raw_seeds = protocol.get("seed")
    seeds: list[int] = []
    if isinstance(raw_seeds, list):
        seeds = [int(item) for item in raw_seeds if isinstance(item, int) and not isinstance(item, bool)]
    elif isinstance(raw_seeds, int) and not isinstance(raw_seeds, bool):
        seeds = [int(raw_seeds)]
    if len(seeds) < 3:
        seeds = [17, 42, 101]
    metric = str(experiment_plan.get("metric") or protocol.get("metric") or "primary metric")
    question = str(
        protocol.get("researchQuestion")
        or plan.get("researchQuestion")
        or f"Frozen protocol comparison on {experiment_plan.get('dataset') or 'FashionMNIST'}."
    ).strip()
    rebuilt = s.experiment_contract.build_experiment_contract(
        plan_id=str(plan.get("planId") or ""),
        team_id=str(plan.get("teamId") or ""),
        research_question=question,
        payload={
            "researchProfileId": str(
                protocol.get("researchProfileId") or "challenge-cup-predictive-coding"
            ),
            "researchMode": "full_research_loop",
            "experimentMethod": "model_training_inference",
            "requestedAdapterId": adapter_id,
            "methodConfig": {
                "dataset": experiment_plan.get("dataset") or "FashionMNIST",
                "model": protocol.get("model") or "predictive-coding-inspired candidate",
                "baseline": experiment_plan.get("baseline") or "standard backpropagation",
                "seeds": seeds,
                "budget": protocol.get("budget") or "same seeds and training budget",
                "smokePlan": experiment_plan.get("smokePlan") or "bounded smoke observation",
            },
            "decisionContract": {
                "successCriteria": [f"improve {metric} under the frozen protocol"],
                "failureCriteria": ["consistently worse than baseline"],
                "inconclusiveCriteria": ["seed variance prevents a fair conclusion"],
            },
            "status": "prepared",
        },
        legacy_plan=experiment_plan,
        hypothesis_refs=protocol.get("hypothesisRefs")
        if isinstance(protocol.get("hypothesisRefs"), list)
        else [],
    )
    plan["experimentContract"] = rebuilt
    s.experiment_contract.sync_plan_record_contract_status(plan)
