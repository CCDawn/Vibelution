"""Experiment plan/status/methods/smoke/full-run and knowledge-ingestion hooks.

Late-bound facade keeps route imports and monkeypatches on
``team_workflow_orchestration_service`` stable during P0 mechanical splits.
"""

from __future__ import annotations

from typing import Any


def _service():
    from core.web.services import team_workflow_orchestration_service

    return team_workflow_orchestration_service


def get_experiment_planning_status(team_id: str) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    s.team_service.get_team(normalized_team_id)
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
        memory_context = s._research_stage_memory_context(
            normalized_team_id,
            stage_type="experiment",
            research_question=str((plan.get("experimentContract") or {}).get("researchQuestion") or plan.get("goal") or plan.get("topic") or ""),
            actor_agent_id=created_by_agent,
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
    created_by_agent: str,
) -> dict[str, Any]:
    """Clone a governed plan into one idempotent, explicitly gated next-design draft."""

    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_source_plan_id = s._normalize_required_id(source_plan_id, "Source experiment plan id is required.")
    normalized_proposal_id = s._normalize_required_id(proposal_id, "Iteration proposal id is required.")
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
        if str(gate.get("status") or "") == "frozen":
            return {"status": "already_frozen", "plan": plan}
        now = s.utc_now_iso()
        gate["status"] = "frozen"
        gate["frozenAt"] = now
        gate["frozenByAgent"] = frozen_by_agent
        plan["designGate"] = gate
        contract = plan.get("experimentContract") if isinstance(plan.get("experimentContract"), dict) else {}
        contract["status"] = "frozen"
        plan["experimentContract"] = contract
        plan["status"] = "design_frozen"
        plan["updatedAt"] = now
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

def run_experiment_smoke_run(team_id: str, plan_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """N-11：对 experiment plan 执行 V1 CPU 确定性 smoke runner，并记录结果。

    门禁：plan 缺 dataset/metric/baseline/smokePlan 之一 → 禁止运行。runner 仅跑白名单 adapter、
    固定 seed、无网络、不执行任意代码（见 core.research.smoke_runner）。decisionHint 映射到
    smoke 状态后复用 register_experiment_smoke_result 落账。
    """
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_plan_id = s._normalize_required_id(plan_id, "Experiment plan id is required.")
    s.team_service.get_team(normalized_team_id)
    payload = payload if isinstance(payload, dict) else {}
    with s._WORKFLOW_LOCK:
        plan_store = s._load_experiment_plan_store(normalized_team_id)
        plan = s._find_experiment_plan(plan_store, normalized_plan_id)
        if plan is None:
            raise s.TeamWorkflowOrchestrationError("Experiment plan not found.")
        plan_snapshot = dict(plan)
    experiment_plan = plan_snapshot.get("experimentPlan") if isinstance(plan_snapshot.get("experimentPlan"), dict) else {}
    s._require_explicit_experiment_design_frozen(plan_snapshot)
    missing = [
        field
        for field in s.EXPERIMENT_PLAN_REQUIRED_FIELDS
        if not s._has_value(plan_snapshot.get(field) or experiment_plan.get(field))
    ]
    if missing:
        raise s.TeamWorkflowOrchestrationError(f"Experiment plan missing required fields for smoke run: {missing}.")
    smoke_plan_value = plan_snapshot.get("smokePlan") or experiment_plan.get("smokePlan")
    smoke_plan = smoke_plan_value if isinstance(smoke_plan_value, dict) else {}
    adapter = (
        s._trim_text(payload.get("adapter") or smoke_plan.get("adapter"), max_length=120)
        or "synthetic_classification_baseline_vs_variant"
    )
    seed_raw = payload.get("seed") if payload.get("seed") is not None else smoke_plan.get("seed", 42)
    try:
        seed = int(seed_raw)
    except (TypeError, ValueError):
        seed = 42
    threshold_raw = payload.get("threshold") if payload.get("threshold") is not None else smoke_plan.get("successThreshold")
    if isinstance(threshold_raw, dict):
        threshold_raw = threshold_raw.get("macro_f1_delta") or threshold_raw.get("macro_f1")
    try:
        threshold = float(threshold_raw) if threshold_raw is not None else None
    except (TypeError, ValueError):
        threshold = None
    try:
        runner_result = s.smoke_runner.run_smoke_adapter(adapter, seed=seed, threshold=threshold)
    except s.smoke_runner.SmokeRunnerError as exc:
        raise s.TeamWorkflowOrchestrationError(str(exc)) from exc
    decision = str(runner_result.get("decisionHint") or "needs_full_run")
    proxy_only = runner_result.get("proxyOnly") is True
    status = (
        "needs_review"
        if runner_result.get("status") == "non_executable" or proxy_only
        else s._SMOKE_DECISION_TO_STATUS.get(decision, "needs_review")
    )
    now = s.utc_now_iso()
    smoke_run_id = s._new_record_id("smokerun")
    smoke_record = {
        "smokeRunId": smoke_run_id,
        "adapter": adapter,
        "seed": runner_result.get("seed"),
        "runnerMode": runner_result.get("runnerMode"),
        "status": status,
        "decisionHint": decision,
        "metrics": runner_result.get("metrics"),
        "artifactHash": runner_result.get("artifactHash"),
        "logs": runner_result.get("logs"),
        "proxyOnly": proxy_only,
        "boundaries": list(runner_result.get("boundaries") or []),
        "recordedByAgent": s._trim_text(payload.get("recordedByAgent"), max_length=160) or "Smoke Runner Service",
        "recordedAt": now,
    }
    # 自包含执行器直接落账（runner 同时算 baseline+variant，无需手动 baseline artifact 前置）。
    with s._WORKFLOW_LOCK:
        plan_store = s._load_experiment_plan_store(normalized_team_id)
        plan = s._find_experiment_plan(plan_store, normalized_plan_id)
        if plan is None:
            raise s.TeamWorkflowOrchestrationError("Experiment plan not found.")
        runs = [item for item in list(plan.get("smokeRunResults") or []) if isinstance(item, dict)]
        runs.append(smoke_record)
        plan["smokeRunResults"] = runs[-12:]
        plan["activeSmokeRunId"] = smoke_run_id
        plan["activeSmokeRun"] = smoke_record
        plan["status"] = "smoke_passed" if status == "passed" else f"smoke_{status}"
        plan["updatedAt"] = now
        s._refresh_experiment_plan_readiness(plan)
        plan_status = plan["status"]
        plan_store["activePlanId"] = plan["planId"]
        plan_store["updatedAt"] = now
        s._write_json(s._experiment_plan_store_path(normalized_team_id), plan_store)
        workflow = s._load_or_create_workflow(normalized_team_id)
    s._record_workflow_event(
        "experiment.smoke_run_completed",
        normalized_team_id,
        fields={
            "planId": normalized_plan_id,
            "smokeRunId": smoke_run_id,
            "adapter": adapter,
            "status": status,
            "decisionHint": decision,
        },
    )
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "planId": normalized_plan_id,
        "adapter": adapter,
        "seed": seed,
        "status": status,
        "decisionHint": decision,
        "runnerResult": runner_result,
        "smokeRun": smoke_record,
        "experimentStatus": plan_status,
        "workflowId": workflow["workflowId"],
    }

def prepare_experiment_full_run(team_id: str, plan_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Validate a user-selected formal runner without starting model training.

    The preparation record is auditable but deliberately does not advance the
    research result state.  A separate explicit full-run request is required.
    """

    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_plan_id = s._normalize_required_id(plan_id, "Experiment plan id is required.")
    team = s.team_service.get_team(normalized_team_id)
    request_payload = payload if isinstance(payload, dict) else {}
    recorded_by_agent = s._trim_text(request_payload.get("recordedByAgent"), max_length=160) or s.DEFAULT_OWNER_AGENT_ID
    with s._WORKFLOW_LOCK:
        plan_store = s._load_experiment_plan_store(normalized_team_id)
        plan = s._find_experiment_plan(plan_store, normalized_plan_id)
        if plan is None:
            raise s.TeamWorkflowOrchestrationError("Experiment plan not found.")
        plan_snapshot = s.deepcopy(plan)

    adapter_id, method_config = s._require_formal_full_run_ready(plan_snapshot)
    try:
        preparation = s.formal_runner.prepare_full_run(
            adapter_id,
            method_config=method_config,
            execution_config=request_payload.get("executionConfig"),
            project_root=s.PROJECT_ROOT,
        )
    except s.formal_runner.FormalRunnerError as exc:
        raise s.TeamWorkflowOrchestrationError(str(exc)) from exc
    now = s.utc_now_iso()
    preparation_record = {
        **preparation,
        "preparationId": s._new_record_id("full-run-preparation"),
        "recordedByAgent": recorded_by_agent,
        "preparedAt": now,
    }
    with s._WORKFLOW_LOCK:
        plan_store = s._load_experiment_plan_store(normalized_team_id)
        plan = s._find_experiment_plan(plan_store, normalized_plan_id)
        if plan is None:
            raise s.TeamWorkflowOrchestrationError("Experiment plan not found.")
        preparations = [item for item in list(plan.get("fullRunPreparations") or []) if isinstance(item, dict)]
        preparations.append(preparation_record)
        plan["fullRunPreparations"] = preparations[-12:]
        plan["activeFullRunPreparationId"] = preparation_record["preparationId"]
        plan["activeFullRunPreparation"] = preparation_record
        plan["updatedAt"] = now
        plan_store["activePlanId"] = plan["planId"]
        plan_store["updatedAt"] = now
        s._write_json(s._experiment_plan_store_path(normalized_team_id), plan_store)
        workflow = s._load_or_create_workflow(normalized_team_id)
    s._record_workflow_event(
        "experiment.full_run_prepared",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "planId": normalized_plan_id,
            "preparationId": preparation_record["preparationId"],
            "adapter": adapter_id,
            "seedCount": preparation.get("seedCount"),
            "recordedByAgent": recorded_by_agent,
        },
    )
    return {
        "preparation": preparation_record,
        "plan": plan,
        "team": {"teamId": team.get("teamId", normalized_team_id), "name": team.get("name", "")},
        "boundaries": {
            "startsFullRun": False,
            "autoExecution": False,
            "requiresExplicitExecute": True,
            "requiresResultReview": True,
        },
    }

def execute_experiment_full_run(team_id: str, plan_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run an explicitly selected formal adapter and store review-only artifacts.

    The runner is synchronous by design for this bounded CPU lane.  It uses no
    shell and cannot execute a user-supplied script.  Completion keeps the
    plan at the full-run review gate; only ``register_experiment_full_run_result``
    can promote a conclusion downstream.
    """

    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_plan_id = s._normalize_required_id(plan_id, "Experiment plan id is required.")
    team = s.team_service.get_team(normalized_team_id)
    request_payload = payload if isinstance(payload, dict) else {}
    recorded_by_agent = s._trim_text(request_payload.get("recordedByAgent"), max_length=160) or s.DEFAULT_OWNER_AGENT_ID
    with s._WORKFLOW_LOCK:
        plan_store = s._load_experiment_plan_store(normalized_team_id)
        plan = s._find_experiment_plan(plan_store, normalized_plan_id)
        if plan is None:
            raise s.TeamWorkflowOrchestrationError("Experiment plan not found.")
        plan_snapshot = s.deepcopy(plan)

    adapter_id, method_config = s._require_formal_full_run_ready(plan_snapshot)
    started_at = s.utc_now_iso()
    execution_id = s._new_record_id("full-run-execution")
    with s._WORKFLOW_LOCK:
        plan_store = s._load_experiment_plan_store(normalized_team_id)
        plan = s._find_experiment_plan(plan_store, normalized_plan_id)
        if plan is None:
            raise s.TeamWorkflowOrchestrationError("Experiment plan not found.")
        plan["status"] = "full_run_running"
        plan["activeFullRunExecution"] = {
            "executionId": execution_id,
            "status": "running",
            "adapterId": adapter_id,
            "recordedByAgent": recorded_by_agent,
            "startedAt": started_at,
        }
        plan["updatedAt"] = started_at
        plan_store["activePlanId"] = plan["planId"]
        plan_store["updatedAt"] = started_at
        s._write_json(s._experiment_plan_store_path(normalized_team_id), plan_store)
        workflow = s._load_or_create_workflow(normalized_team_id)
    s._record_workflow_event(
        "experiment.full_run_started",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "planId": normalized_plan_id,
            "executionId": execution_id,
            "adapter": adapter_id,
            "recordedByAgent": recorded_by_agent,
        },
    )

    try:
        runner_result = s.formal_runner.run_full_run(
            adapter_id,
            method_config=method_config,
            execution_config=request_payload.get("executionConfig"),
            project_root=s.PROJECT_ROOT,
        )
    except s.formal_runner.FormalRunnerError as exc:
        s._record_formal_full_run_execution(
            normalized_team_id,
            normalized_plan_id,
            execution_id=execution_id,
            adapter_id=adapter_id,
            recorded_by_agent=recorded_by_agent,
            started_at=started_at,
            status="failed",
            result={"error": str(exc)},
        )
        raise s.TeamWorkflowOrchestrationError(str(exc)) from exc

    execution_record = s._record_formal_full_run_execution(
        normalized_team_id,
        normalized_plan_id,
        execution_id=execution_id,
        adapter_id=adapter_id,
        recorded_by_agent=recorded_by_agent,
        started_at=started_at,
        status="completed",
        result=runner_result,
    )
    with s._WORKFLOW_LOCK:
        plan_store = s._load_experiment_plan_store(normalized_team_id)
        plan = s._find_experiment_plan(plan_store, normalized_plan_id)
        if plan is None:
            raise s.TeamWorkflowOrchestrationError("Experiment plan not found.")
        workflow = s._load_or_create_workflow(normalized_team_id)
    return {
        "execution": execution_record,
        "plan": plan,
        "team": {"teamId": team.get("teamId", normalized_team_id), "name": team.get("name", "")},
        "workflowId": workflow["workflowId"],
        "boundaries": {
            "autoResultRegistration": False,
            "autoKnowledgeIngestion": False,
            "requiresResultReview": True,
            "requiresExplicitFullRunResultRegistration": True,
        },
    }

def register_experiment_smoke_result(team_id: str, plan_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_plan_id = s._normalize_required_id(plan_id, "Experiment plan id is required.")
    team = s.team_service.get_team(normalized_team_id)
    request_payload = payload if isinstance(payload, dict) else {}
    recorded_by_agent = s._trim_text(request_payload.get("recordedByAgent"), max_length=160) or s.DEFAULT_OWNER_AGENT_ID
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
        smoke_result = s._experiment_smoke_result_record(plan, request_payload, recorded_by_agent=recorded_by_agent)
        smoke_results = [item for item in list(plan.get("smokeResults") or []) if isinstance(item, dict)]
        smoke_results.append(smoke_result)
        plan["smokeResults"] = smoke_results[-12:]
        plan["activeSmokeResultId"] = smoke_result["smokeResultId"]
        plan["activeSmokeResult"] = smoke_result
        plan["status"] = "smoke_passed" if smoke_result["status"] == "passed" else f"smoke_{smoke_result['status']}"
        plan["updatedAt"] = smoke_result["recordedAt"]
        s._refresh_experiment_plan_readiness(plan)
        plan_store["activePlanId"] = plan["planId"]
        plan_store["updatedAt"] = smoke_result["recordedAt"]
        s._write_json(s._experiment_plan_store_path(normalized_team_id), plan_store)
        stage_round = s._find_stage_round(rounds, str(plan.get("stageRoundId") or ""))
        if stage_round is not None:
            stage_round["experimentPlanRef"] = {
                "planId": plan["planId"],
                "status": plan["status"],
                "storagePath": s._relative_path(s._experiment_plan_store_path(normalized_team_id)),
                "smokeResultRef": {
                    "smokeResultId": smoke_result["smokeResultId"],
                    "status": smoke_result["status"],
                    "resultPath": smoke_result["resultPath"],
                    "logRef": smoke_result["logRef"],
                },
                "updatedAt": smoke_result["recordedAt"],
            }
            baseline_selection = plan.get("baselineSelection") if isinstance(plan.get("baselineSelection"), dict) else {}
            active_artifact = (
                baseline_selection.get("activeBaselineArtifact")
                if isinstance(baseline_selection.get("activeBaselineArtifact"), dict)
                else None
            )
            if active_artifact:
                stage_round["experimentPlanRef"]["baselineArtifactRef"] = {
                    "artifactId": active_artifact.get("artifactId", ""),
                    "artifactPath": active_artifact.get("artifactPath", ""),
                }
            planning_contract = stage_round.get("planningContract") if isinstance(stage_round.get("planningContract"), dict) else {}
            planning_contract["currentPlanId"] = plan["planId"]
            planning_contract["activeSmokeResultId"] = smoke_result["smokeResultId"]
            planning_contract["readyForSmoke"] = bool((plan.get("readiness") or {}).get("readyForSmoke"))
            planning_contract["readyForFullRun"] = bool((plan.get("readiness") or {}).get("readyForFullRun"))
            planning_contract["autoExecution"] = False
            planning_contract["requiresUserDecision"] = True
            stage_round["planningContract"] = planning_contract
            stage_round["status"] = "planning"
            stage_round["updatedAt"] = smoke_result["recordedAt"]
            stage_store["rounds"] = rounds
            stage_store["updatedAt"] = smoke_result["recordedAt"]
            s._write_json(s._stage_round_store_path(normalized_team_id), stage_store)
        workflow["updatedAt"] = smoke_result["recordedAt"]
        workflow["activeWorkflowItems"] = s._upsert_active_item(
            workflow.get("activeWorkflowItems"),
            candidate_id=str(plan.get("stageRoundId") or plan["planId"]),
            current_node=s.RESEARCH_STAGE_DEFAULTS["experiment"]["currentNode"],
            status="smoke_result_registered",
            transfer_id="",
        )
        s._write_json(s._workflow_path(normalized_team_id), workflow)
        status_payload = s._experiment_planning_status(normalized_team_id, rounds, candidate_store, plan_store)
        stage_round_status = s.get_research_stage_round_status(normalized_team_id)
    s._record_workflow_event(
        "experiment_plan.smoke_result_registered",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "stageRoundId": str(plan.get("stageRoundId") or ""),
            "planId": plan["planId"],
            "smokeResultId": smoke_result["smokeResultId"],
            "status": smoke_result["status"],
            "gateDecision": smoke_result["gateDecision"],
            "readyForSmoke": bool((plan.get("readiness") or {}).get("readyForSmoke")),
            "readyForFullRun": bool((plan.get("readiness") or {}).get("readyForFullRun")),
            "recordedByAgent": recorded_by_agent,
        },
    )
    return {
        "smokeResult": smoke_result,
        "plan": plan,
        "status": status_payload,
        "stageRoundStatus": stage_round_status,
        "workflow": s._workflow_to_api(normalized_team_id, workflow, candidate_store),
        "team": {"teamId": team.get("teamId", normalized_team_id), "name": team.get("name", "")},
        "boundaries": s._experiment_planning_boundaries(),
    }

def register_experiment_full_run_result(team_id: str, plan_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_plan_id = s._normalize_required_id(plan_id, "Experiment plan id is required.")
    team = s.team_service.get_team(normalized_team_id)
    request_payload = payload if isinstance(payload, dict) else {}
    recorded_by_agent = s._trim_text(request_payload.get("recordedByAgent"), max_length=160) or s.DEFAULT_OWNER_AGENT_ID
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
        full_run_result = s._experiment_full_run_result_record(plan, request_payload, recorded_by_agent=recorded_by_agent)
        full_run_results = [item for item in list(plan.get("fullRunResults") or []) if isinstance(item, dict)]
        full_run_results.append(full_run_result)
        plan["fullRunResults"] = full_run_results[-12:]
        plan["activeFullRunResultId"] = full_run_result["fullRunResultId"]
        plan["activeFullRunResult"] = full_run_result
        plan["status"] = "full_run_passed" if full_run_result["status"] == "passed" else f"full_run_{full_run_result['status']}"
        plan["updatedAt"] = full_run_result["recordedAt"]
        s._refresh_experiment_plan_readiness(plan)
        plan_store["activePlanId"] = plan["planId"]
        plan_store["updatedAt"] = full_run_result["recordedAt"]
        s._write_json(s._experiment_plan_store_path(normalized_team_id), plan_store)
        stage_round = s._find_stage_round(rounds, str(plan.get("stageRoundId") or ""))
        if stage_round is not None:
            stage_round["experimentPlanRef"] = {
                "planId": plan["planId"],
                "status": plan["status"],
                "storagePath": s._relative_path(s._experiment_plan_store_path(normalized_team_id)),
                "fullRunResultRef": {
                    "fullRunResultId": full_run_result["fullRunResultId"],
                    "status": full_run_result["status"],
                    "resultPath": full_run_result["resultPath"],
                    "logRef": full_run_result["logRef"],
                },
                "updatedAt": full_run_result["recordedAt"],
            }
            active_smoke_result = plan.get("activeSmokeResult") if isinstance(plan.get("activeSmokeResult"), dict) else None
            if active_smoke_result:
                stage_round["experimentPlanRef"]["smokeResultRef"] = {
                    "smokeResultId": active_smoke_result.get("smokeResultId", ""),
                    "status": active_smoke_result.get("status", ""),
                    "resultPath": active_smoke_result.get("resultPath", ""),
                    "logRef": active_smoke_result.get("logRef", ""),
                }
            baseline_selection = plan.get("baselineSelection") if isinstance(plan.get("baselineSelection"), dict) else {}
            active_artifact = (
                baseline_selection.get("activeBaselineArtifact")
                if isinstance(baseline_selection.get("activeBaselineArtifact"), dict)
                else None
            )
            if active_artifact:
                stage_round["experimentPlanRef"]["baselineArtifactRef"] = {
                    "artifactId": active_artifact.get("artifactId", ""),
                    "artifactPath": active_artifact.get("artifactPath", ""),
                }
            planning_contract = stage_round.get("planningContract") if isinstance(stage_round.get("planningContract"), dict) else {}
            planning_contract["currentPlanId"] = plan["planId"]
            planning_contract["activeFullRunResultId"] = full_run_result["fullRunResultId"]
            planning_contract["readyForSmoke"] = bool((plan.get("readiness") or {}).get("readyForSmoke"))
            planning_contract["readyForFullRun"] = bool((plan.get("readiness") or {}).get("readyForFullRun"))
            planning_contract["readyForKnowledgeIngestion"] = bool((plan.get("readiness") or {}).get("readyForKnowledgeIngestion"))
            planning_contract["autoExecution"] = False
            planning_contract["requiresUserDecision"] = True
            stage_round["planningContract"] = planning_contract
            stage_round["status"] = "planning"
            stage_round["updatedAt"] = full_run_result["recordedAt"]
            stage_store["rounds"] = rounds
            stage_store["updatedAt"] = full_run_result["recordedAt"]
            s._write_json(s._stage_round_store_path(normalized_team_id), stage_store)
        workflow["updatedAt"] = full_run_result["recordedAt"]
        workflow["activeWorkflowItems"] = s._upsert_active_item(
            workflow.get("activeWorkflowItems"),
            candidate_id=str(plan.get("stageRoundId") or plan["planId"]),
            current_node=s.RESEARCH_STAGE_DEFAULTS["experiment"]["currentNode"],
            status="full_run_result_registered",
            transfer_id="",
        )
        s._write_json(s._workflow_path(normalized_team_id), workflow)
        status_payload = s._experiment_planning_status(normalized_team_id, rounds, candidate_store, plan_store)
        stage_round_status = s.get_research_stage_round_status(normalized_team_id)
    s._record_workflow_event(
        "experiment_plan.full_run_result_registered",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "stageRoundId": str(plan.get("stageRoundId") or ""),
            "planId": plan["planId"],
            "fullRunResultId": full_run_result["fullRunResultId"],
            "status": full_run_result["status"],
            "gateDecision": full_run_result["gateDecision"],
            "readyForKnowledgeIngestion": bool((plan.get("readiness") or {}).get("readyForKnowledgeIngestion")),
            "recordedByAgent": recorded_by_agent,
        },
    )
    return {
        "fullRunResult": full_run_result,
        "plan": plan,
        "status": status_payload,
        "stageRoundStatus": stage_round_status,
        "workflow": s._workflow_to_api(normalized_team_id, workflow, candidate_store),
        "team": {"teamId": team.get("teamId", normalized_team_id), "name": team.get("name", "")},
        "boundaries": s._experiment_planning_boundaries(),
    }

def request_experiment_result_knowledge_ingestion(team_id: str, plan_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_plan_id = s._normalize_required_id(plan_id, "Experiment plan id is required.")
    team = s.team_service.get_team(normalized_team_id)
    request_payload = payload if isinstance(payload, dict) else {}
    requested_by_agent = s._trim_text(request_payload.get("requestedByAgent"), max_length=160) or s.DEFAULT_OWNER_AGENT_ID
    steward_agent_id = s._trim_text(request_payload.get("stewardAgentId"), max_length=160) or s.agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID
    knowledge_base_id = s._trim_text(request_payload.get("knowledgeBaseId"), max_length=160) or f"{normalized_team_id}-challenge-cup-experiments"
    target_domain = s._trim_text(request_payload.get("targetDomain"), max_length=240) or "挑战杯实验结果"
    wake_steward_agent = bool(request_payload.get("wakeStewardAgent", True))
    with s._WORKFLOW_LOCK:
        workflow = s._load_or_create_workflow(normalized_team_id)
        stage_store = s._load_stage_round_store(normalized_team_id)
        rounds = s._stage_rounds(stage_store)
        candidate_store = s._load_candidate_store(normalized_team_id)
        plan_store = s._load_experiment_plan_store(normalized_team_id)
        plan = s._find_experiment_plan(plan_store, normalized_plan_id)
        if plan is None:
            raise s.TeamWorkflowOrchestrationError("Experiment plan not found.")
        experiment_result_pack = s._experiment_result_ingestion_pack_record(
            plan,
            request_payload,
            knowledge_base_id=knowledge_base_id,
            target_domain=target_domain,
            requested_by_agent=requested_by_agent,
        )
        activation = s._notify_knowledge_steward_for_experiment_result(
            normalized_team_id,
            steward_agent_id=steward_agent_id,
            requester_agent_id=requested_by_agent,
            experiment_result_pack=experiment_result_pack,
            knowledge_base_id=knowledge_base_id,
            target_domain=target_domain,
            wake_target=wake_steward_agent,
        )
        activation_status = str(activation.get("status") or "")
        if activation_status in {"message_written", "agent_wake_started"}:
            plan_status = "knowledge_steward_notified"
        elif activation_status.startswith("agent_wake_"):
            plan_status = "knowledge_steward_wake_pending"
        else:
            plan_status = "knowledge_steward_notification_failed"
        plan["knowledgeIngestion"] = {
            "status": plan_status,
            "experimentResultPack": experiment_result_pack,
            "knowledgeStewardActivation": activation,
            "knowledgeBaseId": knowledge_base_id,
            "targetDomain": target_domain,
            "updatedAt": experiment_result_pack["createdAt"],
            "officialBoundary": experiment_result_pack["officialBoundary"],
        }
        plan["status"] = plan_status
        plan["updatedAt"] = experiment_result_pack["createdAt"]
        s._refresh_experiment_plan_readiness(plan)
        plan_store["activePlanId"] = plan["planId"]
        plan_store["updatedAt"] = experiment_result_pack["createdAt"]
        s._write_json(s._experiment_plan_store_path(normalized_team_id), plan_store)
        stage_round = s._find_stage_round(rounds, str(plan.get("stageRoundId") or ""))
        if stage_round is not None:
            stage_round["experimentPlanRef"] = {
                "planId": plan["planId"],
                "status": plan["status"],
                "storagePath": s._relative_path(s._experiment_plan_store_path(normalized_team_id)),
                "experimentResultPackRef": {
                    "packId": experiment_result_pack["packId"],
                    "fullRunResultId": experiment_result_pack["fullRunResultId"],
                    "knowledgeBaseId": knowledge_base_id,
                    "messageId": str(activation.get("messageId") or ""),
                },
                "updatedAt": experiment_result_pack["createdAt"],
            }
            active_full_run = plan.get("activeFullRunResult") if isinstance(plan.get("activeFullRunResult"), dict) else None
            if active_full_run:
                stage_round["experimentPlanRef"]["fullRunResultRef"] = {
                    "fullRunResultId": active_full_run.get("fullRunResultId", ""),
                    "status": active_full_run.get("status", ""),
                    "resultPath": active_full_run.get("resultPath", ""),
                    "logRef": active_full_run.get("logRef", ""),
                }
            planning_contract = stage_round.get("planningContract") if isinstance(stage_round.get("planningContract"), dict) else {}
            planning_contract["currentPlanId"] = plan["planId"]
            planning_contract["experimentResultPackId"] = experiment_result_pack["packId"]
            planning_contract["knowledgeStewardInboxMessageId"] = str(activation.get("messageId") or "")
            planning_contract["readyForKnowledgeIngestion"] = bool((plan.get("readiness") or {}).get("readyForKnowledgeIngestion"))
            planning_contract["autoExecution"] = False
            planning_contract["requiresUserDecision"] = True
            stage_round["planningContract"] = planning_contract
            stage_round["status"] = "planning"
            stage_round["updatedAt"] = experiment_result_pack["createdAt"]
            stage_store["rounds"] = rounds
            stage_store["updatedAt"] = experiment_result_pack["createdAt"]
            s._write_json(s._stage_round_store_path(normalized_team_id), stage_store)
        workflow["updatedAt"] = experiment_result_pack["createdAt"]
        workflow["activeWorkflowItems"] = s._upsert_active_item(
            workflow.get("activeWorkflowItems"),
            candidate_id=str(plan.get("stageRoundId") or plan["planId"]),
            current_node=s.RESEARCH_STAGE_DEFAULTS["experiment"]["currentNode"],
            status=plan_status,
            transfer_id="",
        )
        s._write_json(s._workflow_path(normalized_team_id), workflow)
        status_payload = s._experiment_planning_status(normalized_team_id, rounds, candidate_store, plan_store)
        stage_round_status = s.get_research_stage_round_status(normalized_team_id)
    s._record_workflow_event(
        "experiment_plan.knowledge_ingestion_requested",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "stageRoundId": str(plan.get("stageRoundId") or ""),
            "planId": plan["planId"],
            "experimentResultPackId": experiment_result_pack["packId"],
            "fullRunResultId": experiment_result_pack["fullRunResultId"],
            "knowledgeBaseId": knowledge_base_id,
            "knowledgeStewardActivationStatus": activation_status,
            "knowledgeStewardInboxMessageId": str(activation.get("messageId") or ""),
            "requestedByAgent": requested_by_agent,
        },
    )
    notification_failed = activation_status not in {"message_written", "agent_wake_started"} and not activation_status.startswith("agent_wake_")
    s._record_workflow_event(
        "experiment_plan.steward_notification_failed" if notification_failed else "experiment_plan.steward_notification_completed",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "stageRoundId": str(plan.get("stageRoundId") or ""),
            "planId": plan["planId"],
            "experimentResultPackId": experiment_result_pack["packId"],
            "fullRunResultId": experiment_result_pack["fullRunResultId"],
            "knowledgeBaseId": knowledge_base_id,
            "targetAgentId": str(activation.get("targetAgentId") or ""),
            "status": activation_status,
            "messageId": str(activation.get("messageId") or ""),
            "threadId": str(activation.get("threadId") or ""),
            "wakeStatus": str(activation.get("wakeStatus") or ""),
            "requestedByAgent": requested_by_agent,
            "errorType": type(activation.get("error")).__name__ if activation.get("error") and not isinstance(activation.get("error"), str) else "",
        },
        level="warning" if notification_failed else "info",
        outcome="failed" if notification_failed else "completed",
        child_log_path=f"artifacts/experiment-result-{s._safe_token(experiment_result_pack['packId'], default='pack', max_length=96)}-steward-notification.jsonl",
        child_log_payload=s._experiment_result_steward_notification_child_log_payload(
            team_id=normalized_team_id,
            experiment_result_pack=experiment_result_pack,
            activation=activation,
            knowledge_base_id=knowledge_base_id,
            target_domain=target_domain,
            requested_by_agent=requested_by_agent,
        ),
        lifecycle=notification_failed,
    )
    return {
        "experimentResultPack": experiment_result_pack,
        "knowledgeStewardActivation": activation,
        "plan": plan,
        "status": status_payload,
        "stageRoundStatus": stage_round_status,
        "workflow": s._workflow_to_api(normalized_team_id, workflow, candidate_store),
        "team": {"teamId": team.get("teamId", normalized_team_id), "name": team.get("name", "")},
        "boundaries": s._experiment_planning_boundaries(),
    }

def reconcile_experiment_knowledge_ingestion(
    team_id: str,
    *,
    inbox_source_id: str,
    source_ref: dict[str, Any] | None,
    direct_ingestion: dict[str, Any] | None,
    reconciled_by_agent_id: str = "",
) -> dict[str, Any]:
    """Idempotently project a completed direct ingestion into its experiment ledger."""

    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_inbox_source_id = s._normalize_required_id(inbox_source_id, "Inbox source id is required.")
    normalized_source_ref = source_ref if isinstance(source_ref, dict) else {}
    normalized_direct_ingestion = direct_ingestion if isinstance(direct_ingestion, dict) else {}
    plan_id = s._trim_text(normalized_source_ref.get("planId"), max_length=160)
    pack_id = s._trim_text(normalized_source_ref.get("experimentResultPackId"), max_length=160)
    item = normalized_direct_ingestion.get("item") if isinstance(normalized_direct_ingestion.get("item"), dict) else {}
    batch = normalized_direct_ingestion.get("batch") if isinstance(normalized_direct_ingestion.get("batch"), dict) else {}
    source_artifact = (
        normalized_direct_ingestion.get("sourceArtifact")
        if isinstance(normalized_direct_ingestion.get("sourceArtifact"), dict)
        else {}
    )
    knowledge_item_id = s._trim_text(item.get("knowledgeItemId"), max_length=160)
    batch_id = s._trim_text(batch.get("batchId"), max_length=160)
    source_artifact_id = s._trim_text(source_artifact.get("sourceArtifactId"), max_length=160)
    if not source_artifact_id:
        source_artifact_ids = item.get("sourceArtifactIds") if isinstance(item.get("sourceArtifactIds"), list) else []
        source_artifact_id = s._trim_text(source_artifact_ids[0] if source_artifact_ids else "", max_length=160)
    central_source_id = s._trim_text(source_artifact.get("centralSourceId"), max_length=160)
    if not central_source_id:
        central_source_ids = item.get("centralSourceIds") if isinstance(item.get("centralSourceIds"), list) else []
        central_source_id = s._trim_text(central_source_ids[0] if central_source_ids else "", max_length=160)
    direct_status = s._trim_text(normalized_direct_ingestion.get("status"), max_length=80).lower()
    required_evidence = {
        "planId": plan_id,
        "experimentResultPackId": pack_id,
        "knowledgeItemId": knowledge_item_id,
        "centralSourceId": central_source_id,
        "sourceArtifactId": source_artifact_id,
        "batchId": batch_id,
    }
    if direct_status != "ingested" or any(not value for value in required_evidence.values()):
        return {
            "schemaVersion": s.SCHEMA_VERSION,
            "status": "ignored",
            "updated": False,
            "reason": "incomplete_direct_ingestion_evidence",
            "teamId": normalized_team_id,
            "inboxSourceId": normalized_inbox_source_id,
        }
    direct_owner_type = s._trim_text(normalized_direct_ingestion.get("ownerType"), max_length=40).lower()
    direct_owner_id = s._trim_text(normalized_direct_ingestion.get("ownerId"), max_length=160)
    if (direct_owner_type and direct_owner_type != "team") or (
        direct_owner_id and direct_owner_id != normalized_team_id
    ):
        return {
            "schemaVersion": s.SCHEMA_VERSION,
            "status": "ignored",
            "updated": False,
            "reason": "direct_ingestion_owner_mismatch",
            "teamId": normalized_team_id,
            "inboxSourceId": normalized_inbox_source_id,
        }

    updated = False
    reason = "reconciled"
    now = (
        s._trim_text(normalized_direct_ingestion.get("updatedAt"), max_length=80)
        or s._trim_text(batch.get("appliedAt"), max_length=80)
        or s._trim_text(item.get("appliedAt"), max_length=80)
        or s.utc_now_iso()
    )
    result_evidence = {
        "status": "ingested",
        "inboxSourceId": normalized_inbox_source_id,
        "experimentResultPackId": pack_id,
        "planId": plan_id,
        "knowledgeItemId": knowledge_item_id,
        "centralSourceId": central_source_id,
        "sourceArtifactId": source_artifact_id,
        "batchId": batch_id,
        "knowledgeBaseId": s._trim_text(
            normalized_direct_ingestion.get("scopedKnowledgeBaseId")
            or normalized_direct_ingestion.get("knowledgeBaseId"),
            max_length=200,
        ),
        "reconciledByAgentId": s._trim_text(reconciled_by_agent_id, max_length=160),
        "ingestedAt": now,
    }
    with s._WORKFLOW_LOCK:
        workflow = s._load_or_create_workflow(normalized_team_id)
        stage_store = s._load_stage_round_store(normalized_team_id)
        rounds = s._stage_rounds(stage_store)
        candidate_store = s._load_candidate_store(normalized_team_id)
        plan_store = s._load_experiment_plan_store(normalized_team_id)
        plan = s._find_experiment_plan(plan_store, plan_id)
        if plan is None:
            return {
                "schemaVersion": s.SCHEMA_VERSION,
                "status": "ignored",
                "updated": False,
                "reason": "experiment_plan_not_found",
                "teamId": normalized_team_id,
                "inboxSourceId": normalized_inbox_source_id,
                "planId": plan_id,
            }
        knowledge_ingestion = plan.get("knowledgeIngestion") if isinstance(plan.get("knowledgeIngestion"), dict) else {}
        stored_pack = (
            knowledge_ingestion.get("experimentResultPack")
            if isinstance(knowledge_ingestion.get("experimentResultPack"), dict)
            else {}
        )
        stored_activation = (
            knowledge_ingestion.get("knowledgeStewardActivation")
            if isinstance(knowledge_ingestion.get("knowledgeStewardActivation"), dict)
            else {}
        )
        if (
            s._trim_text(stored_pack.get("packId"), max_length=160) != pack_id
            or s._trim_text(stored_activation.get("inboxSourceId"), max_length=160) != normalized_inbox_source_id
        ):
            return {
                "schemaVersion": s.SCHEMA_VERSION,
                "status": "ignored",
                "updated": False,
                "reason": "experiment_ingestion_reference_mismatch",
                "teamId": normalized_team_id,
                "inboxSourceId": normalized_inbox_source_id,
                "planId": plan_id,
            }
        existing_result = knowledge_ingestion.get("result") if isinstance(knowledge_ingestion.get("result"), dict) else {}
        if s._trim_text(knowledge_ingestion.get("status"), max_length=80).lower() == "ingested":
            stable_keys = (
                "inboxSourceId",
                "experimentResultPackId",
                "planId",
                "knowledgeItemId",
                "centralSourceId",
                "sourceArtifactId",
                "batchId",
            )
            if all(str(existing_result.get(key) or "") == str(result_evidence.get(key) or "") for key in stable_keys):
                reason = "already_reconciled"
            else:
                return {
                    "schemaVersion": s.SCHEMA_VERSION,
                    "status": "ignored",
                    "updated": False,
                    "reason": "conflicting_ingestion_evidence",
                    "teamId": normalized_team_id,
                    "inboxSourceId": normalized_inbox_source_id,
                    "planId": plan_id,
                }
        else:
            allowed_statuses = {
                "knowledge_steward_notified",
                "knowledge_steward_wake_pending",
            }
            if s._trim_text(knowledge_ingestion.get("status"), max_length=80).lower() not in allowed_statuses:
                return {
                    "schemaVersion": s.SCHEMA_VERSION,
                    "status": "ignored",
                    "updated": False,
                    "reason": "experiment_ingestion_not_awaiting_steward",
                    "teamId": normalized_team_id,
                    "inboxSourceId": normalized_inbox_source_id,
                    "planId": plan_id,
                }
            knowledge_ingestion["status"] = "ingested"
            knowledge_ingestion["result"] = result_evidence
            knowledge_ingestion["updatedAt"] = now
            plan["knowledgeIngestion"] = knowledge_ingestion
            plan["status"] = "ingested"
            plan["updatedAt"] = now
            plan_store["activePlanId"] = plan["planId"]
            plan_store["updatedAt"] = now
            s._write_json(s._experiment_plan_store_path(normalized_team_id), plan_store)

            stage_round = s._find_stage_round(rounds, str(plan.get("stageRoundId") or ""))
            if stage_round is not None:
                experiment_plan_ref = (
                    stage_round.get("experimentPlanRef")
                    if isinstance(stage_round.get("experimentPlanRef"), dict)
                    else {}
                )
                experiment_plan_ref["planId"] = plan["planId"]
                experiment_plan_ref["status"] = "ingested"
                experiment_plan_ref["knowledgeIngestionResultRef"] = result_evidence
                experiment_plan_ref["updatedAt"] = now
                stage_round["experimentPlanRef"] = experiment_plan_ref
                planning_contract = (
                    stage_round.get("planningContract")
                    if isinstance(stage_round.get("planningContract"), dict)
                    else {}
                )
                planning_contract["currentPlanId"] = plan["planId"]
                planning_contract["knowledgeIngestionStatus"] = "ingested"
                planning_contract["knowledgeItemId"] = knowledge_item_id
                planning_contract["requiresUserDecision"] = False
                stage_round["planningContract"] = planning_contract
                stage_round["updatedAt"] = now
                stage_store["rounds"] = rounds
                stage_store["updatedAt"] = now
                s._write_json(s._stage_round_store_path(normalized_team_id), stage_store)
            workflow["updatedAt"] = now
            workflow["activeWorkflowItems"] = s._upsert_active_item(
                workflow.get("activeWorkflowItems"),
                candidate_id=str(plan.get("stageRoundId") or plan["planId"]),
                current_node=s.RESEARCH_STAGE_DEFAULTS["experiment"]["currentNode"],
                status="ingested",
                transfer_id="",
            )
            s._write_json(s._workflow_path(normalized_team_id), workflow)
            updated = True
        status_payload = s._experiment_planning_status(normalized_team_id, rounds, candidate_store, plan_store)

    if updated:
        s._record_workflow_event(
            "experiment_plan.knowledge_ingestion_reconciled",
            normalized_team_id,
            fields={
                "workflowId": workflow["workflowId"],
                "stageRoundId": str(plan.get("stageRoundId") or ""),
                **result_evidence,
            },
            outcome="completed",
        )
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "status": "ingested",
        "updated": updated,
        "reason": reason,
        "teamId": normalized_team_id,
        "planId": plan_id,
        "inboxSourceId": normalized_inbox_source_id,
        "result": result_evidence,
        "projectionStatus": status_payload["status"],
    }
