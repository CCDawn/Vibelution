"""Experiment smoke run operations (Clarity B6 split from experiment.py).

Late-bound facade keeps route imports and monkeypatches on
``team_workflow_orchestration_service`` stable during mechanical splits.
"""

from __future__ import annotations

from typing import Any


def _service():
    from core.web.services import team_workflow_orchestration_service

    return team_workflow_orchestration_service


def _resolve_declared_smoke_adapter(
    s: Any,
    *,
    sources: tuple[Any, ...],
    known_smoke_adapters: set[str],
) -> str:
    """Pick a smoke adapter, skipping formal-only FashionMNIST selection.

    Frozen-protocol bind stamps ``fashion_mnist_predictive_coding_multi_seed``
    onto ``adapterSelection`` so later full-run readiness can see an explicit
    choice. That id is not a V1 CPU smoke adapter. Treating it as one 422s
    SCI-096 ``controlled_run`` retry before bounded STOP can run.
    Unknown smoke-plan ids still fail closed.
    """
    formal_only = {s.formal_runner.FASHION_MNIST_MULTI_SEED_ADAPTER}
    for raw in sources:
        text = s._trim_text(raw, max_length=120)
        if not text or text in formal_only:
            continue
        if text not in known_smoke_adapters:
            raise s.TeamWorkflowOrchestrationError(
                f"Experiment plan declares an unavailable smoke adapter: {text}."
            )
        return text
    return ""


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
    legacy_smoke_settings: dict[str, str] = {}
    if isinstance(smoke_plan_value, str):
        segments = [
            segment.strip()
            for segment in smoke_plan_value.replace("；", ";").split(";")
            if segment.strip()
        ]
        if segments:
            first_segment = segments[0]
            if "=" not in first_segment:
                legacy_smoke_settings["adapter"] = first_segment
            for segment in segments:
                if "=" not in segment:
                    continue
                key, value = segment.split("=", 1)
                legacy_smoke_settings[key.strip()] = value.strip()
    experiment_contract = (
        plan_snapshot.get("experimentContract")
        if isinstance(plan_snapshot.get("experimentContract"), dict)
        else {}
    )
    adapter_selection = (
        experiment_contract.get("adapterSelection")
        if isinstance(experiment_contract.get("adapterSelection"), dict)
        else {}
    )
    known_smoke_adapters = {
        *s.smoke_runner.WHITELIST_ADAPTERS,
        *s.smoke_runner.NON_EXECUTABLE_ADAPTERS,
    }
    declared_adapter = _resolve_declared_smoke_adapter(
        s,
        sources=(
            adapter_selection.get("requestedAdapterId"),
            adapter_selection.get("resolvedAdapterId"),
            smoke_plan.get("adapter"),
            legacy_smoke_settings.get("adapter"),
        ),
        known_smoke_adapters=known_smoke_adapters,
    )
    requested_adapter = s._trim_text(payload.get("adapter"), max_length=120)
    if declared_adapter and requested_adapter and declared_adapter != requested_adapter:
        raise s.TeamWorkflowOrchestrationError(
            "Requested smoke adapter does not match the experiment plan."
        )
    adapter = (
        declared_adapter
        or requested_adapter
        or "synthetic_classification_baseline_vs_variant"
    )
    seed_raw = (
        payload.get("seed")
        if payload.get("seed") is not None
        else smoke_plan.get("seed", legacy_smoke_settings.get("seed", 42))
    )
    try:
        seed = int(seed_raw)
    except (TypeError, ValueError):
        seed = 42
    threshold_raw = (
        payload.get("threshold")
        if payload.get("threshold") is not None
        else smoke_plan.get(
            "successThreshold",
            legacy_smoke_settings.get("successThreshold"),
        )
    )
    if isinstance(threshold_raw, dict):
        threshold_raw = (
            threshold_raw.get("macro_f1_delta")
            or threshold_raw.get("macro_f1")
            or threshold_raw.get("mse_improvement")
        )
    try:
        threshold = float(threshold_raw) if threshold_raw is not None else None
    except (TypeError, ValueError):
        threshold = None
    if threshold is not None and threshold <= 0:
        # A non-positive threshold makes every delta "pass"; refuse it so the
        # decision hint stays meaningful.
        raise s.TeamWorkflowOrchestrationError(
            "Smoke successThreshold must be a positive number."
        )
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
        # The runner executes outside the lock; re-assert the frozen design so a
        # result is never recorded against changed terms.
        s._require_explicit_experiment_design_frozen(plan)
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

def register_experiment_smoke_result(team_id: str, plan_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    from core.web.services.team_workflow.research_runtime.challenge_cup_maintenance_fence import (
        assert_writes_allowed,
    )

    assert_writes_allowed(normalized_team_id, operation="experiment_writeback")
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
        from core.web.services.team_workflow.outcome_graph import merge_registered_result

        merge_registered_result(
            plan,
            smoke_result,
            extra=request_payload,
            peer_plans=[item for item in list(plan_store.get("plans") or []) if isinstance(item, dict)],
        )
        s._refresh_hypothesis_progress(plan)
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
