"""Experiment full run operations (Clarity B6 split from experiment.py).

Late-bound facade keeps route imports and monkeypatches on
``team_workflow_orchestration_service`` stable during mechanical splits.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from core.runtime_manager import formal_run_registry
from core.web.services.team_workflow import experiment_kernel as _experiment_kernel

_FORMAL_EXECUTION_PATH_KEYS = ("pythonExecutable", "dataRoot", "outputRoot")
_FORMAL_ENV_OPTIONAL_INTS = (
    ("VIBELUTION_FORMAL_TIMEOUT_SECONDS", "timeoutSeconds"),
    ("VIBELUTION_FORMAL_TRAIN_SAMPLES", "trainSamples"),
    ("VIBELUTION_FORMAL_TEST_SAMPLES", "testSamples"),
    ("VIBELUTION_FORMAL_EPOCHS", "epochs"),
)


def _service():
    from core.web.services import team_workflow_orchestration_service

    return team_workflow_orchestration_service


def formal_execution_config_is_provisioned(config: dict[str, Any] | None) -> bool:
    """True when the operator supplied the three explicit local runner paths."""
    if not isinstance(config, dict):
        return False
    return all(str(config.get(key) or "").strip() for key in _FORMAL_EXECUTION_PATH_KEYS)


def resolve_formal_execution_config(
    plan: dict[str, Any] | None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Prefer request payload, then a stored preparation, then process env.

    Workflow canvas retry does not send executionConfig. Cloud/operator
    provision must still reach ``run_full_run`` without silently bounded-STOP.
    """
    request = payload if isinstance(payload, dict) else {}
    request_config = (
        dict(request.get("executionConfig") or {})
        if isinstance(request.get("executionConfig"), dict)
        else {}
    )
    if formal_execution_config_is_provisioned(request_config):
        return request_config
    for fallback in (
        _execution_config_from_preparation(plan),
        _execution_config_from_env(),
    ):
        if formal_execution_config_is_provisioned(fallback):
            return {**fallback, **request_config}
    return request_config


def _execution_config_from_preparation(plan: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(plan, dict):
        return {}
    prep = plan.get("activeFullRunPreparation")
    if not isinstance(prep, dict):
        return {}
    stored = prep.get("executionConfig")
    if formal_execution_config_is_provisioned(stored if isinstance(stored, dict) else None):
        return dict(stored)
    environment = prep.get("environment") if isinstance(prep.get("environment"), dict) else {}
    mapped = {
        "pythonExecutable": environment.get("pythonExecutable"),
        "dataRoot": environment.get("dataRoot"),
        "outputRoot": environment.get("outputRoot"),
    }
    timeout = prep.get("timeoutSecondsPerSeed")
    if timeout is not None:
        mapped["timeoutSeconds"] = timeout
    run_options = prep.get("runOptions") if isinstance(prep.get("runOptions"), dict) else {}
    for key in ("trainSamples", "testSamples", "epochs", "batchSize"):
        if key in run_options:
            mapped[key] = run_options[key]
    return mapped


def _execution_config_from_env() -> dict[str, Any]:
    mapped = {
        "pythonExecutable": os.environ.get("VIBELUTION_FORMAL_PYTHON_EXECUTABLE", ""),
        "dataRoot": os.environ.get("VIBELUTION_FORMAL_DATA_ROOT", ""),
        "outputRoot": os.environ.get("VIBELUTION_FORMAL_OUTPUT_ROOT", ""),
    }
    for env_key, field in _FORMAL_ENV_OPTIONAL_INTS:
        raw = str(os.environ.get(env_key) or "").strip()
        if not raw:
            continue
        try:
            mapped[field] = int(raw)
        except ValueError:
            continue
    return mapped


def _bind_formal_execution_config(
    config: dict[str, Any] | None,
    *,
    project_root: Path | str,
) -> dict[str, Any]:
    """Bind a product full-run config to the current instance data root.

    Request payloads, stored preparation records, and environment fallbacks
    are all untrusted input at this boundary.  Keep their other options intact
    for the runner, but resolve ``outputRoot`` through the formal runner's
    canonical-path helper immediately before any prepare/run call.
    """

    s = _service()
    bound = dict(config) if isinstance(config, dict) else {}
    try:
        bound["outputRoot"] = str(
            s.formal_runner.assert_canonical_project_data_path(
                bound.get("outputRoot"),
                project_root=project_root,
                label="outputRoot",
            )
        )
    except s.formal_runner.FormalRunnerError as exc:
        raise s.TeamWorkflowOrchestrationError(str(exc)) from exc
    return bound


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
    execution_config = resolve_formal_execution_config(plan_snapshot, request_payload)
    try:
        execution_config = _bind_formal_execution_config(
            execution_config,
            project_root=s.PROJECT_ROOT,
        )
        preparation = s.formal_runner.prepare_full_run(
            adapter_id,
            method_config=method_config,
            execution_config=execution_config,
            project_root=s.PROJECT_ROOT,
        )
    except s.formal_runner.FormalRunnerError as exc:
        raise s.TeamWorkflowOrchestrationError(str(exc)) from exc
    now = s.utc_now_iso()
    preparation_record = {
        **preparation,
        "preparationId": s._new_record_id("full-run-preparation"),
        "planId": normalized_plan_id,
        "planRevision": s._experiment_plan_revision(plan_snapshot),
        "adapterId": adapter_id,
        "methodConfigDigest": _experiment_kernel._experiment_method_config_digest(plan_snapshot),
        "executionConfigDigest": _experiment_kernel._full_run_execution_config_digest(execution_config),
        "recordedByAgent": recorded_by_agent,
        "preparedAt": now,
        "executionConfig": execution_config,
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

def _assert_exclusive_formal_output_root(execution_config: dict[str, Any] | None) -> None:
    """Refuse to start when another active formal run owns an overlapping outputRoot.

    The per-plan ``activeFullRunExecution`` guard cannot see a concurrent run of
    a different plan.  Two formal runs sharing or nesting an outputRoot would
    overwrite each other's seed directories and summary artifacts, so the check
    fails closed (including when the snapshot store itself is unreadable).
    """

    output_root = str((execution_config or {}).get("outputRoot") or "").strip()
    s = _service()
    try:
        formal_run_registry.assert_output_root_is_exclusive(output_root)
    except formal_run_registry.FormalRunOutputRootConflict as exc:
        raise s.TeamWorkflowOrchestrationError(str(exc)) from exc
    except OSError as exc:
        raise s.TeamWorkflowOrchestrationError(
            f"Unable to inspect active formal runs before start: {exc}"
        ) from exc


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
    execution_config = resolve_formal_execution_config(plan_snapshot, request_payload)
    execution_config = _bind_formal_execution_config(
        execution_config,
        project_root=s.PROJECT_ROOT,
    )
    preparation_snapshot = (
        s.deepcopy(plan_snapshot.get("activeFullRunPreparation"))
        if isinstance(plan_snapshot.get("activeFullRunPreparation"), dict)
        else None
    )
    plan_revision = s._experiment_plan_revision(plan_snapshot)
    method_config_digest = _experiment_kernel._experiment_method_config_digest(plan_snapshot)
    started_at = s.utc_now_iso()
    execution_id = s._new_record_id("full-run-execution")
    with s._WORKFLOW_LOCK:
        plan_store = s._load_experiment_plan_store(normalized_team_id)
        plan = s._find_experiment_plan(plan_store, normalized_plan_id)
        if plan is None:
            raise s.TeamWorkflowOrchestrationError("Experiment plan not found.")
        # Gate-then-act guard: the readiness check above ran unlocked; re-check
        # inside the lock and refuse duplicate concurrent executions.
        current_execution = (
            plan.get("activeFullRunExecution")
            if isinstance(plan.get("activeFullRunExecution"), dict)
            else {}
        )
        if str(current_execution.get("status") or "") == "running":
            raise s.TeamWorkflowOrchestrationError(
                "A formal full run is already executing for this plan."
            )
        s._require_formal_full_run_ready(plan)
        # C7 active-work registration: check outputRoot exclusivity and publish
        # the running snapshot before the plan flips to full_run_running, so a
        # restart/Launcher probe can never miss a synchronous training run.
        _assert_exclusive_formal_output_root(execution_config)
        formal_run_registry.register_active_formal_run(
            run_id=execution_id,
            output_root=str(execution_config.get("outputRoot") or ""),
            team_id=normalized_team_id,
            plan_id=normalized_plan_id,
            adapter_id=adapter_id,
            started_at=started_at,
        )
        plan["status"] = "full_run_running"
        plan["activeFullRunExecution"] = {
            "executionId": execution_id,
            "status": "running",
            "planId": normalized_plan_id,
            "planRevision": plan_revision,
            "adapterId": adapter_id,
            "preparationId": str((preparation_snapshot or {}).get("preparationId") or ""),
            "executionConfig": execution_config,
            "executionConfigDigest": _experiment_kernel._full_run_execution_config_digest(execution_config),
            "methodConfigDigest": method_config_digest,
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
            execution_config=execution_config,
            project_root=s.PROJECT_ROOT,
        )
    except s.formal_runner.FormalRunnerError as exc:
        formal_run_registry.complete_formal_run(run_id=execution_id, status="failed", error=str(exc))
        s._record_formal_full_run_execution(
            normalized_team_id,
            normalized_plan_id,
            execution_id=execution_id,
            adapter_id=adapter_id,
            recorded_by_agent=recorded_by_agent,
            started_at=started_at,
            status="failed",
            result={"error": str(exc)},
            preparation=preparation_snapshot,
            plan_revision=plan_revision,
            execution_config=execution_config,
            method_config=method_config,
            method_config_digest=method_config_digest,
        )
        raise s.TeamWorkflowOrchestrationError(str(exc)) from exc

    try:
        execution_record = s._record_formal_full_run_execution(
            normalized_team_id,
            normalized_plan_id,
            execution_id=execution_id,
            adapter_id=adapter_id,
            recorded_by_agent=recorded_by_agent,
            started_at=started_at,
            status="completed",
            result=runner_result,
            preparation=preparation_snapshot,
            plan_revision=plan_revision,
            execution_config=execution_config,
            method_config=method_config,
            method_config_digest=method_config_digest,
        )
    except BaseException:
        formal_run_registry.complete_formal_run(
            run_id=execution_id,
            status="failed",
            error="formal run execution record failed",
        )
        raise
    formal_run_registry.complete_formal_run(run_id=execution_id, status="completed")
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

def register_experiment_full_run_result(team_id: str, plan_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
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
    evidence_kind = s._trim_text(request_payload.get("evidenceKind"), max_length=80).lower()
    if evidence_kind not in {
        _experiment_kernel._FORMAL_RUN_CANONICAL_EVIDENCE_KIND,
        _experiment_kernel._FORMAL_RUN_EXTERNAL_EVIDENCE_KIND,
    }:
        raise s.TeamWorkflowOrchestrationError(
            "Full-run result evidenceKind must be explicit: canonical_runner or external_manual."
        )
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
        if evidence_kind == _experiment_kernel._FORMAL_RUN_CANONICAL_EVIDENCE_KIND:
            full_run_result = _experiment_kernel._canonical_formal_full_run_result_record(
                plan,
                request_payload,
                recorded_by_agent=recorded_by_agent,
            )
        else:
            full_run_result = s._experiment_full_run_result_record(
                plan,
                request_payload,
                recorded_by_agent=recorded_by_agent,
            )
        full_run_results = [item for item in list(plan.get("fullRunResults") or []) if isinstance(item, dict)]
        existing_result = (
            next(
                (
                    item
                    for item in full_run_results
                    if isinstance(item, dict)
                    and full_run_result.get("receiptId")
                    and item.get("receiptId") == full_run_result.get("receiptId")
                ),
                None,
            )
            if evidence_kind == _experiment_kernel._FORMAL_RUN_CANONICAL_EVIDENCE_KIND
            else None
        )
        is_replay = existing_result is not None
        if is_replay:
            full_run_result = existing_result
        else:
            full_run_results.append(full_run_result)
        if evidence_kind == _experiment_kernel._FORMAL_RUN_EXTERNAL_EVIDENCE_KIND:
            external_results = [
                item for item in full_run_results
                if item.get("evidenceKind") == _experiment_kernel._FORMAL_RUN_EXTERNAL_EVIDENCE_KIND
            ]
            retained_results = [
                item for item in full_run_results
                if item.get("evidenceKind") != _experiment_kernel._FORMAL_RUN_EXTERNAL_EVIDENCE_KIND
            ]
            plan["fullRunResults"] = retained_results + external_results[-12:]
        else:
            plan["fullRunResults"] = full_run_results
        plan["activeFullRunResultId"] = full_run_result["fullRunResultId"]
        plan["activeFullRunResult"] = full_run_result
        plan["status"] = "full_run_passed" if full_run_result["status"] == "passed" else f"full_run_{full_run_result['status']}"
        plan["updatedAt"] = full_run_result["recordedAt"]
        s._refresh_experiment_plan_readiness(plan)
        if not is_replay and evidence_kind == _experiment_kernel._FORMAL_RUN_CANONICAL_EVIDENCE_KIND:
            from core.web.services.team_workflow.outcome_graph import merge_registered_result

            merge_registered_result(
                plan,
                full_run_result,
                extra=request_payload,
                peer_plans=[item for item in list(plan_store.get("plans") or []) if isinstance(item, dict)],
            )
        s._refresh_hypothesis_progress(plan)
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
                    "evidenceKind": full_run_result.get("evidenceKind", ""),
                    "receiptId": full_run_result.get("receiptId", ""),
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
