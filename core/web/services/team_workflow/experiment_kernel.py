"""Experiment private kernel: plan records, readiness, lifecycle projection, steward notify.

Public experiment entrypoints remain in ``experiment.py``. Late-bound facade
keeps monkeypatches stable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.web.services.team_workflow.challenge_program import build_challenge_program_projection
from core.web.services.team_workflow.challenge_question_runs import challenge_question_run_summary


CHALLENGE_PROGRAM_CASE_REGISTRY_PATH = Path("挑战杯") / "data" / "representative_deep_cases.json"


def _service():
    from core.web.services import team_workflow_orchestration_service

    return team_workflow_orchestration_service


def _load_challenge_program_case_registry() -> dict[str, Any]:
    s = _service()
    path = Path(s.PROJECT_ROOT) / CHALLENGE_PROGRAM_CASE_REGISTRY_PATH
    return s._read_json(path) if path.exists() else {}


def _require_formal_full_run_ready(plan: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    s = _service()
    contract = plan.get("experimentContract") if isinstance(plan.get("experimentContract"), dict) else {}
    validation = plan.get("contractValidation") if isinstance(plan.get("contractValidation"), dict) else {}
    readiness = plan.get("readiness") if isinstance(plan.get("readiness"), dict) else {}
    selection = contract.get("adapterSelection") if isinstance(contract.get("adapterSelection"), dict) else {}
    adapter_id = s._trim_text(selection.get("resolvedAdapterId"), max_length=200)
    s._require_explicit_experiment_design_frozen(plan)
    if adapter_id != s.formal_runner.FASHION_MNIST_MULTI_SEED_ADAPTER:
        raise s.TeamWorkflowOrchestrationError("Experiment plan does not select the formal FashionMNIST multi-seed adapter.")
    if not bool(validation.get("valid")):
        raise s.TeamWorkflowOrchestrationError("Experiment plan contract must be valid before formal full-run preparation.")
    if not bool(readiness.get("readyForFullRun")):
        raise s.TeamWorkflowOrchestrationError("Record a passing smoke result before formal full-run preparation.")
    method_config = contract.get("methodConfig") if isinstance(contract.get("methodConfig"), dict) else {}
    return adapter_id, method_config


def _require_explicit_experiment_design_frozen(plan: dict[str, Any]) -> None:
    s = _service()
    design_gate = plan.get("designGate") if isinstance(plan.get("designGate"), dict) else None
    if design_gate is not None and str(design_gate.get("status") or "") != "frozen":
        raise s.TeamWorkflowOrchestrationError("Experiment design must be explicitly frozen before execution evidence can be recorded.")


def _record_formal_full_run_execution(
    team_id: str,
    plan_id: str,
    *,
    execution_id: str,
    adapter_id: str,
    recorded_by_agent: str,
    started_at: str,
    status: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    s = _service()
    finished_at = s.utc_now_iso()
    execution_record = {
        "executionId": execution_id,
        "status": status,
        "adapterId": adapter_id,
        "recordedByAgent": recorded_by_agent,
        "startedAt": started_at,
        "finishedAt": finished_at,
        "result": result,
        "requiresResultReview": True,
        "automaticPromotion": False,
    }
    with s._WORKFLOW_LOCK:
        plan_store = s._load_experiment_plan_store(team_id)
        plan = s._find_experiment_plan(plan_store, plan_id)
        if plan is None:
            raise s.TeamWorkflowOrchestrationError("Experiment plan not found.")
        executions = [item for item in list(plan.get("fullRunExecutions") or []) if isinstance(item, dict)]
        executions.append(execution_record)
        plan["fullRunExecutions"] = executions[-12:]
        plan["activeFullRunExecutionId"] = execution_id
        plan["activeFullRunExecution"] = execution_record
        plan["status"] = "smoke_passed"
        plan["updatedAt"] = finished_at
        s._refresh_experiment_plan_readiness(plan)
        plan_store["activePlanId"] = plan["planId"]
        plan_store["updatedAt"] = finished_at
        s._write_json(s._experiment_plan_store_path(team_id), plan_store)
        workflow = s._load_or_create_workflow(team_id)
        workflow["updatedAt"] = finished_at
        workflow["activeWorkflowItems"] = s._upsert_active_item(
            workflow.get("activeWorkflowItems"),
            candidate_id=str(plan.get("stageRoundId") or plan["planId"]),
            current_node=s.RESEARCH_STAGE_DEFAULTS["experiment"]["currentNode"],
            status=f"full_run_execution_{status}",
            transfer_id="",
        )
        s._write_json(s._workflow_path(team_id), workflow)
    s._record_workflow_event(
        f"experiment.full_run_{status}",
        team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "planId": plan_id,
            "executionId": execution_id,
            "adapter": adapter_id,
            "status": status,
            "resultPath": s._trim_text(result.get("resultPath"), max_length=500),
        },
    )
    return execution_record


def _experiment_result_steward_notification_child_log_payload(
    *,
    team_id: str,
    experiment_result_pack: dict[str, Any],
    activation: dict[str, Any],
    knowledge_base_id: str,
    target_domain: str,
    requested_by_agent: str,
) -> dict[str, Any]:
    s = _service()
    delivery = activation.get("delivery") if isinstance(activation.get("delivery"), dict) else {}
    kernel = activation.get("kernel") if isinstance(activation.get("kernel"), dict) else {}
    return {
        "kind": "experiment_result_steward_notification",
        "teamId": s._trim_text(team_id, max_length=160),
        "planId": s._trim_text(experiment_result_pack.get("planId"), max_length=160),
        "experimentResultPackId": s._trim_text(experiment_result_pack.get("packId"), max_length=160),
        "fullRunResultId": s._trim_text(experiment_result_pack.get("fullRunResultId"), max_length=160),
        "knowledgeBaseId": s._trim_text(knowledge_base_id, max_length=160),
        "targetDomain": s._trim_text(target_domain, max_length=240),
        "requestedByAgent": s._trim_text(requested_by_agent, max_length=160),
        "targetAgentId": s._trim_text(activation.get("targetAgentId"), max_length=160),
        "status": s._trim_text(activation.get("status"), max_length=80),
        "messageId": s._trim_text(activation.get("messageId"), max_length=160),
        "threadId": s._trim_text(activation.get("threadId"), max_length=240),
        "wakeRequested": bool(activation.get("wakeRequested")),
        "wakeStatus": s._trim_text(activation.get("wakeStatus"), max_length=80),
        "turnId": s._trim_text(delivery.get("turnId"), max_length=160),
        "kernel": {
            "taskId": s._trim_text(kernel.get("taskId"), max_length=160),
            "workRunId": s._trim_text(kernel.get("workRunId"), max_length=160),
            "outcomeStatus": s._trim_text(kernel.get("outcomeStatus"), max_length=80),
            "reused": bool(kernel.get("reused")),
        },
        "error": s._trim_text(activation.get("error"), max_length=500),
    }


def _load_experiment_plan_store(team_id: str) -> dict[str, Any]:
    s = _service()
    path = s._experiment_plan_store_path(team_id)
    if path.exists():
        payload = s._read_json(path)
        if payload.get("storeKind") == s.EXPERIMENT_PLAN_STORE_KIND and isinstance(payload.get("plans"), list):
            projected = s.experiment_contract.project_plan_store_contracts(payload)
            for plan in list(projected.get("plans") or []):
                if isinstance(plan, dict):
                    _sanitize_projected_experiment_plan(plan)
            return projected
    now = s.utc_now_iso()
    payload = {
        "schemaVersion": s.SCHEMA_VERSION,
        "teamId": team_id,
        "storeKind": s.EXPERIMENT_PLAN_STORE_KIND,
        "activePlanId": "",
        "plans": [],
        "createdAt": now,
        "updatedAt": now,
    }
    s._write_json(path, payload)
    return payload


def _experiment_plan_field_text(
    value: Any,
    *,
    preferred_keys: tuple[str, ...] = (),
    max_length: int = 1200,
) -> str:
    """Return a human-authored scalar, never a serialized structured placeholder."""
    s = _service()
    if isinstance(value, str):
        text = s._trim_text(value, max_length=max_length)
        if text.startswith("{") and text.endswith("}"):
            return ""
        return text
    if isinstance(value, dict):
        status = s._trim_text(value.get("status"), max_length=80).lower()
        if status in {
            "blocked",
            "draft_blocked",
            "missing",
            "not_ready",
            "pending_input",
            "unresolved",
        }:
            return ""
        for key in preferred_keys:
            text = _experiment_plan_field_text(
                value.get(key),
                max_length=max_length,
            )
            if text:
                return text
    return ""


def _sanitize_projected_experiment_plan(plan: dict[str, Any]) -> None:
    """Repair read projections from older native-v2 records without rewriting history."""
    legacy = plan.get("experimentPlan") if isinstance(plan.get("experimentPlan"), dict) else {}
    field_specs = {
        "dataset": ("name", "dataset", "label", "id"),
        "metric": ("primaryMetric", "name", "metric", "label"),
        "baseline": ("name", "baseline", "label", "id"),
        "smokePlan": ("protocol", "smokePlan", "summary", "label"),
    }
    contract = plan.get("experimentContract") if isinstance(plan.get("experimentContract"), dict) else {}
    method_config = contract.get("methodConfig") if isinstance(contract.get("methodConfig"), dict) else {}
    metric_contract = contract.get("metricContract") if isinstance(contract.get("metricContract"), dict) else {}
    contract_migration = (
        plan.get("contractMigration")
        if isinstance(plan.get("contractMigration"), dict)
        else {}
    )
    design_gate = plan.get("designGate") if isinstance(plan.get("designGate"), dict) else None
    contract_validation = (
        plan.get("contractValidation")
        if isinstance(plan.get("contractValidation"), dict)
        else {}
    )
    project_explicit_design_gate = (
        design_gate is None
        and str(plan.get("status") or "").strip().lower() == "draft"
        and contract.get("schemaVersion") == 2
        and str(contract.get("status") or "").strip().lower() == "draft"
        and contract_validation.get("valid") is True
        and contract_migration.get("status") != "projected_from_v1"
    )

    def needs_projection_repair(value: Any) -> bool:
        if isinstance(value, str):
            text = value.strip()
            return text.startswith("{") and text.endswith("}")
        if not isinstance(value, dict):
            return False
        return str(value.get("status") or "").strip().lower() in {
            "blocked",
            "draft_blocked",
            "missing",
            "not_ready",
            "pending_input",
            "unresolved",
        }

    repair_values = [
        *(legacy.get(field) for field in field_specs),
        *(method_config.get(field) for field in ("dataset", "baseline", "smokePlan")),
        metric_contract.get("primaryMetric"),
    ]
    structured_placeholder_found = any(
        needs_projection_repair(value) for value in repair_values
    )
    legacy_projection = {
        field: _experiment_plan_field_text(
            legacy.get(field),
            preferred_keys=preferred_keys,
            max_length=1200 if field == "smokePlan" else 500,
        )
        for field, preferred_keys in field_specs.items()
    }
    canonical_projection = {
        "dataset": _experiment_plan_field_text(
            method_config.get("dataset"),
            preferred_keys=field_specs["dataset"],
            max_length=500,
        ),
        "metric": _experiment_plan_field_text(
            metric_contract.get("primaryMetric"),
            preferred_keys=field_specs["metric"],
            max_length=500,
        ),
        "baseline": _experiment_plan_field_text(
            method_config.get("baseline"),
            preferred_keys=field_specs["baseline"],
            max_length=500,
        ),
        "smokePlan": _experiment_plan_field_text(
            method_config.get("smokePlan"),
            preferred_keys=field_specs["smokePlan"],
            max_length=1200,
        ),
    }
    sanitized = {
        field: canonical_projection[field] or legacy_projection[field]
        for field in field_specs
    }
    projection_changed = any(
        legacy_projection[field] != sanitized[field] for field in field_specs
    )
    if (
        not structured_placeholder_found
        and not projection_changed
        and not project_explicit_design_gate
    ):
        return

    s = _service()
    plan["experimentPlan"] = sanitized
    if project_explicit_design_gate:
        plan["designGate"] = {
            "status": "draft",
            "requiresExplicitFreeze": True,
            "source": "native_v2_plan",
            "sourceLoopId": "",
            "sourceDecisionId": "",
            "sourceProposalId": "",
            "sourceIdempotencyKey": "",
            "frozenAt": "",
            "frozenByAgent": "",
        }
    for field in ("dataset", "baseline", "smokePlan"):
        method_config[field] = canonical_projection[field]
    contract["methodConfig"] = method_config
    metric_contract = contract.get("metricContract") if isinstance(contract.get("metricContract"), dict) else {}
    primary_metric = canonical_projection["metric"]
    metric_contract["primaryMetric"] = primary_metric
    metric_contract["metrics"] = [
        item
        for item in list(metric_contract.get("metrics") or [])
        if isinstance(item, dict)
        and _experiment_plan_field_text(
            item.get("name"),
            preferred_keys=field_specs["metric"],
            max_length=500,
        )
    ]
    contract["metricContract"] = metric_contract
    plan["experimentContract"] = contract
    baseline_selection = (
        plan.get("baselineSelection")
        if isinstance(plan.get("baselineSelection"), dict)
        else {}
    )
    baseline_selection["baseline"] = sanitized["baseline"]
    baseline_selection["status"] = (
        "planned_not_validated" if sanitized["baseline"] else "missing"
    )
    plan["baselineSelection"] = baseline_selection
    plan["successMetrics"] = s._dedupe_text_values([sanitized["metric"]])
    _refresh_experiment_plan_readiness(plan)
    migration = contract_migration
    if structured_placeholder_found:
        migration["projectionRepair"] = "structured_placeholder_removed"
    elif projection_changed:
        migration["projectionRepair"] = "canonical_contract_projected"
    else:
        migration["projectionRepair"] = "explicit_design_gate_projected"
    if project_explicit_design_gate:
        migration["designGateProjection"] = "explicit_draft_gate_projected"
    migration["persistOnNextMutation"] = True
    migration["missingFields"] = list(
        (plan.get("contractValidation") or {}).get("missingFields") or []
    )
    plan["contractMigration"] = migration


def materialize_candidate_graph_hypotheses_for_experiment_design(
    team_id: str,
    research_project_id: str,
) -> dict[str, Any]:
    """Project graph hypotheses into candidate-only drafts at the explicit design gate."""
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_project_id = s._normalize_required_id(
        research_project_id,
        "Research project id is required.",
    )
    project_root = s.resolve_research_project_workspace_root(
        normalized_team_id,
        normalized_project_id,
    )
    store_path = project_root / "candidate_store" / "index.json"
    with s._WORKFLOW_LOCK:
        store = s._read_json(store_path)
        candidates = [
            item
            for item in list(store.get("candidates") or [])
            if isinstance(item, dict)
        ]
        graph_candidates = [
            item
            for item in candidates
            if item.get("candidateType") == "candidate_graph"
            and not s._candidate_is_archived(item)
        ]
        graph_candidates.sort(
            key=lambda item: (
                s._trim_text(item.get("updatedAt"), max_length=120),
                s._trim_text(item.get("createdAt"), max_length=120),
            )
        )
        if not graph_candidates:
            return {
                "candidateGraphId": "",
                "materializedCandidateIds": [],
                "reusedCandidateIds": [],
            }
        graph_candidate = graph_candidates[-1]
        metadata = (
            graph_candidate.get("metadata")
            if isinstance(graph_candidate.get("metadata"), dict)
            else {}
        )
        agent_writeback = (
            metadata.get("agentWriteback")
            if isinstance(metadata.get("agentWriteback"), dict)
            else {}
        )
        writeback_result = (
            agent_writeback.get("result")
            if isinstance(agent_writeback.get("result"), dict)
            else {}
        )
        output = (
            metadata.get("output")
            if isinstance(metadata.get("output"), dict)
            else {}
        )
        graph_payload = next(
            (
                value
                for value in (
                    writeback_result.get("candidateGraph"),
                    output.get("candidateGraph"),
                    metadata.get("candidateGraph"),
                    graph_candidate.get("candidateGraph"),
                )
                if isinstance(value, dict)
            ),
            {},
        )
        hypotheses = [
            item
            for item in list(graph_payload.get("falsifiableHypotheses") or [])
            if isinstance(item, dict)
            and s._trim_text(item.get("statement"), max_length=4000)
        ][:16]
        if not hypotheses:
            return {
                "candidateGraphId": s._trim_text(
                    graph_candidate.get("candidateId"),
                    max_length=160,
                ),
                "materializedCandidateIds": [],
                "reusedCandidateIds": [],
            }
        graph_id = s._trim_text(graph_candidate.get("candidateId"), max_length=160)
        existing_by_hypothesis_id = {
            s._trim_text(
                (
                    (item.get("metadata") or {}).get("projection") or {}
                ).get("graphHypothesisId"),
                max_length=160,
            ): item
            for item in candidates
            if item.get("candidateType") == "algorithm_hypothesis"
            and isinstance(item.get("metadata"), dict)
            and isinstance((item.get("metadata") or {}).get("projection"), dict)
            and s._trim_text(
                ((item.get("metadata") or {}).get("projection") or {}).get(
                    "candidateGraphId"
                ),
                max_length=160,
            )
            == graph_id
        }
        nodes = {
            s._trim_text(item.get("id") or item.get("candidateId"), max_length=160): item
            for item in list(graph_payload.get("nodes") or [])
            if isinstance(item, dict)
            and s._trim_text(
                item.get("id") or item.get("candidateId"),
                max_length=160,
            )
        }
        now = s.utc_now_iso()
        materialized: list[str] = []
        reused: list[str] = []
        for index, hypothesis in enumerate(hypotheses, start=1):
            hypothesis_id = (
                s._trim_text(hypothesis.get("id"), max_length=160)
                or f"H{index}"
            )
            existing = existing_by_hypothesis_id.get(hypothesis_id)
            if existing is not None:
                reused.append(
                    s._trim_text(existing.get("candidateId"), max_length=160)
                )
                continue
            supporting_ids = s._normalize_text_list(
                hypothesis.get("supportingCandidates"),
                max_items=24,
                max_length=160,
            )
            challenging_ids = s._normalize_text_list(
                hypothesis.get("challengingCandidates"),
                max_items=24,
                max_length=160,
            )
            linked_ids = s._dedupe_text_values(
                [*supporting_ids, *challenging_ids]
            )
            source_refs = [
                {
                    "type": "candidate",
                    "id": candidate_id,
                    "label": s._trim_text(
                        (nodes.get(candidate_id) or {}).get("title"),
                        max_length=240,
                    )
                    or candidate_id,
                }
                for candidate_id in linked_ids
            ]
            evidence_refs = [
                {
                    "type": "evidence",
                    "id": evidence_ref,
                    "label": s._trim_text(
                        (nodes.get(candidate_id) or {}).get("title"),
                        max_length=240,
                    )
                    or evidence_ref,
                }
                for candidate_id in linked_ids
                if (
                    evidence_ref := s._trim_text(
                        (nodes.get(candidate_id) or {}).get("evidenceRef"),
                        max_length=200,
                    )
                )
            ]
            statement = s._trim_text(
                hypothesis.get("statement"),
                max_length=4000,
            )
            boundary = s._trim_text(
                hypothesis.get("boundary"),
                max_length=2000,
            )
            candidate_id = s._new_record_id("algorithm-hypothesis")
            hypothesis_output = {
                "candidateType": "algorithm_hypothesis",
                "sourceRefs": source_refs,
                "evidenceRefs": evidence_refs,
                "candidateGraphIds": [graph_id],
                "hypothesis": statement,
                "baseline": "",
                "expectedBenefit": "",
                "expectedComputeCost": "",
                "experimentPlan": {},
                "uncertainty": [boundary] if boundary else [],
                "riskFlags": [
                    "candidate_graph_projection",
                    "experiment_design_required",
                ],
                "confidence": 0,
                "nextAction": "complete_experiment_design_and_review",
                "requiresReview": True,
            }
            record = {
                "schemaVersion": s.SCHEMA_VERSION,
                "candidateId": candidate_id,
                "candidateType": "algorithm_hypothesis",
                "teamId": normalized_team_id,
                "workflowId": graph_candidate.get("workflowId", ""),
                "title": f"{hypothesis_id} · {statement[:180]}",
                "sourceKind": "candidate_graph_hypothesis_projection",
                "summary": statement,
                "sourceRefs": source_refs,
                "evidenceRefs": evidence_refs,
                "metadata": {
                    "taskType": "algorithm_hypothesis_draft",
                    "output": hypothesis_output,
                    "projection": {
                        "candidateGraphId": graph_id,
                        "graphHypothesisId": hypothesis_id,
                        "supportingCandidateIds": supporting_ids,
                        "challengingCandidateIds": challenging_ids,
                        "boundary": boundary,
                        "officialState": "candidate_only",
                    },
                },
                "createdByAgent": s._trim_text(
                    graph_candidate.get("createdByAgent"),
                    max_length=160,
                ),
                "currentWorkflowNode": "algorithm_hypothesis",
                "currentState": "hypothesis_needs_revision",
                "qualityStatus": "needs_revision",
                "createdAt": now,
                "updatedAt": now,
            }
            record["metadata"]["validation"] = s.validate_candidate_record(record)
            candidates.append(record)
            materialized.append(candidate_id)
        if materialized:
            store["candidates"] = candidates
            store["updatedAt"] = now
            s._write_json(store_path, store)
    if materialized:
        s._record_workflow_event(
            "candidate_graph.hypotheses_materialized_for_experiment_design",
            normalized_team_id,
            fields={
                "researchProjectId": normalized_project_id,
                "candidateGraphId": graph_id,
                "materializedCandidateCount": len(materialized),
                "reusedCandidateCount": len(reused),
                "officialState": "candidate_only",
            },
        )
    return {
        "candidateGraphId": graph_id,
        "materializedCandidateIds": materialized,
        "reusedCandidateIds": reused,
    }


def _research_stage_memory_context(
    team_id: str,
    *,
    stage_type: str,
    research_question: str,
    actor_agent_id: str,
) -> dict[str, Any]:
    s = _service()
    candidate_store = s._load_candidate_store(team_id)
    plan_store = s._load_experiment_plan_store(team_id)
    loop_store = s._read_json(s._team_workflow_root(team_id) / "research_loops" / "index.json")
    knowledge_results, retrieval_status = s._research_memory_knowledge_results(
        team_id,
        research_question=research_question,
        actor_agent_id=actor_agent_id,
    )
    normalized_stage_type = (
        "experiment_execution_iteration"
        if stage_type == "iteration"
        else "experiment_design"
    )
    return s._build_research_memory_context(
        stage_type=normalized_stage_type,
        research_question=research_question,
        candidates=[
            item
            for item in list(candidate_store.get("candidates") or [])
            if isinstance(item, dict)
        ],
        plans=s._experiment_plans(plan_store),
        loops=[
            item
            for item in list(loop_store.get("loops") or [])
            if isinstance(item, dict)
        ],
        knowledge_results=knowledge_results,
        retrieval_status=retrieval_status,
        control_plan=s._active_experiment_plan(plan_store),
    )


def _experiment_plan_revision(plan: dict[str, Any] | None) -> int:
    contract = plan.get("experimentContract") if isinstance((plan or {}).get("experimentContract"), dict) else {}
    try:
        return max(0, int(contract.get("revision") or 0))
    except (TypeError, ValueError):
        return 0


def _experiment_design_is_frozen(plan: dict[str, Any] | None) -> bool:
    if not isinstance(plan, dict):
        return False
    validation = plan.get("contractValidation") if isinstance(plan.get("contractValidation"), dict) else {}
    readiness = plan.get("readiness") if isinstance(plan.get("readiness"), dict) else {}
    design_gate = plan.get("designGate") if isinstance(plan.get("designGate"), dict) else None
    if design_gate is not None:
        return (
            str(design_gate.get("status") or "") == "frozen"
            and validation.get("valid") is True
            and readiness.get("readyForPlanReview") is True
        )
    return validation.get("valid") is True and readiness.get("readyForPlanReview") is True


def _latest_frozen_experiment_design(plans: list[dict[str, Any]]) -> dict[str, Any] | None:
    s = _service()
    frozen = [plan for plan in plans if s._experiment_design_is_frozen(plan)]
    if not frozen:
        return None
    return max(
        frozen,
        key=lambda plan: (
            s._experiment_plan_revision(plan),
            str(plan.get("updatedAt") or plan.get("createdAt") or ""),
        ),
    )


def _best_validated_experiment_plan(
    plans: list[dict[str, Any]],
    active_loop: dict[str, Any] | None,
) -> dict[str, Any] | None:
    s = _service()
    linked_experiment = (
        active_loop.get("linkedExperiment")
        if isinstance((active_loop or {}).get("linkedExperiment"), dict)
        else {}
    )
    linked_plan_id = str(linked_experiment.get("planId") or "")
    if linked_plan_id:
        linked_plan = next((plan for plan in plans if str(plan.get("planId") or "") == linked_plan_id), None)
        if linked_plan is not None:
            return linked_plan
    validated: list[dict[str, Any]] = []
    for plan in plans:
        full_run = plan.get("activeFullRunResult") if isinstance(plan.get("activeFullRunResult"), dict) else {}
        ingestion = plan.get("knowledgeIngestion") if isinstance(plan.get("knowledgeIngestion"), dict) else {}
        if str(full_run.get("status") or "").lower() == "passed" or str(ingestion.get("status") or "").lower() == "ingested":
            validated.append(plan)
    if not validated:
        return None
    return max(
        validated,
        key=lambda plan: (
            s._experiment_plan_revision(plan),
            str(plan.get("updatedAt") or plan.get("createdAt") or ""),
        ),
    )


def _experiment_lifecycle_projection(
    *,
    team_id: str,
    latest_collection: dict[str, Any] | None,
    latest_experiment: dict[str, Any] | None,
    latest_iteration: dict[str, Any] | None,
    candidate_store: dict[str, Any],
    plans: list[dict[str, Any]],
    active_plan: dict[str, Any] | None,
) -> dict[str, Any]:
    s = _service()
    candidates = [item for item in list(candidate_store.get("candidates") or []) if isinstance(item, dict)]
    source_candidates = [item for item in candidates if str(item.get("candidateType") or "") == "source_manifest"]
    hypothesis_candidates = [item for item in candidates if str(item.get("candidateType") or "") == "algorithm_hypothesis"]
    frozen_design = s._latest_frozen_experiment_design(plans)
    active_design_gate = (
        active_plan.get("designGate")
        if isinstance((active_plan or {}).get("designGate"), dict)
        else None
    )
    design_plan = active_plan if active_design_gate is not None else (frozen_design or active_plan)
    active_loop = s._active_research_loop_projection(team_id)
    best_plan = s._best_validated_experiment_plan(plans, active_loop)
    linked_experiment = (
        active_loop.get("linkedExperiment")
        if isinstance((active_loop or {}).get("linkedExperiment"), dict)
        else {}
    )
    linked_candidate_ids = [
        str(item)
        for item in list(linked_experiment.get("candidateIds") or [])
        if str(item).strip()
    ]
    best_plan_candidate_ids = [
        str(item)
        for item in list((best_plan or {}).get("hypothesisCandidateIds") or [])
        if str(item).strip()
    ]
    best_candidate_id = (linked_candidate_ids or best_plan_candidate_ids or [""])[0]
    loop_result_id = s._best_research_loop_evidence_id(active_loop)
    best_validated_result_id = loop_result_id or str((best_plan or {}).get("activeFullRunResultId") or "")
    latest_plan = max(
        plans,
        key=lambda plan: (
            s._experiment_plan_revision(plan),
            str(plan.get("updatedAt") or plan.get("createdAt") or ""),
        ),
        default=None,
    )
    stage2_status = "not_started"
    if design_plan is not None:
        stage2_status = "frozen" if s._experiment_design_is_frozen(design_plan) else "draft"
    stage3_status = str((active_loop or {}).get("status") or "")
    if not stage3_status:
        stage3_status = "validated" if best_validated_result_id else "not_started"
    latest_diagnostic_status = {
        "planId": str((latest_plan or {}).get("planId") or ""),
        "revision": s._experiment_plan_revision(latest_plan),
        "status": str((latest_plan or {}).get("status") or ""),
        "title": str((latest_plan or {}).get("title") or ""),
    }
    knowledge_item_ids = [
        str(((plan.get("knowledgeIngestion") or {}).get("result") or {}).get("knowledgeItemId") or "")
        for plan in plans
        if isinstance(plan.get("knowledgeIngestion"), dict)
        and isinstance((plan.get("knowledgeIngestion") or {}).get("result"), dict)
    ]
    knowledge_item_ids = [item for item in knowledge_item_ids if item]
    stage2_memory_context = (
        design_plan.get("memoryContext")
        if isinstance((design_plan or {}).get("memoryContext"), dict)
        else (latest_experiment or {}).get("memoryContext")
    )
    stage3_memory_context = (
        active_loop.get("memoryContext")
        if isinstance((active_loop or {}).get("memoryContext"), dict)
        else (latest_iteration or {}).get("memoryContext")
    )
    fallback_contexts: dict[str, dict[str, Any]] = {}
    if (
        (design_plan is not None and not isinstance(stage2_memory_context, dict))
        or (
            (active_loop is not None or latest_iteration is not None or best_plan is not None)
            and not isinstance(stage3_memory_context, dict)
        )
    ):
        fallback_contexts = s._legacy_research_lifecycle_memory_contexts(
            team_id=team_id,
            candidate_store=candidate_store,
            plans=plans,
            design_plan=design_plan,
            best_plan=best_plan,
            latest_experiment=latest_experiment,
            latest_iteration=latest_iteration,
            active_loop=active_loop,
        )
    if design_plan is not None and not isinstance(stage2_memory_context, dict):
        stage2_memory_context = fallback_contexts.get("stage2")
    if (
        (active_loop is not None or latest_iteration is not None or best_plan is not None)
        and not isinstance(stage3_memory_context, dict)
    ):
        stage3_memory_context = fallback_contexts.get("stage3")
    return {
        "schemaVersion": 1,
        "migrationMode": "derived_from_append_only_history",
        "stage1": {
            "status": "ready_for_hypothesis" if latest_collection and hypothesis_candidates else "collecting",
            "latestRoundId": str((latest_collection or {}).get("stageRoundId") or ""),
            "sourceCandidateCount": len(source_candidates),
            "hypothesisCandidateCount": len(hypothesis_candidates),
            "linkedExperimentKnowledgeItemCount": len(set(knowledge_item_ids)),
        },
        "stage2": {
            "status": stage2_status,
            "activeDesignPlanId": str((design_plan or {}).get("planId") or ""),
            "frozenDesignRevision": s._experiment_plan_revision(design_plan) if stage2_status == "frozen" else 0,
            "readyForExecution": stage2_status == "frozen",
            "completionDefinition": "frozen_executable_experiment_design",
            "memoryContextSummary": s._research_memory_context_summary(stage2_memory_context),
        },
        "stage3": {
            "status": stage3_status,
            "activeIterationId": str((active_loop or {}).get("loopId") or ""),
            "bestCandidateId": best_candidate_id,
            "bestValidatedResultId": best_validated_result_id,
            "bestValidatedPlanId": str((best_plan or {}).get("planId") or ""),
            "latestDiagnosticStatus": latest_diagnostic_status,
            "completionDefinition": "executed_evaluated_and_governed_result",
            "memoryContextSummary": s._research_memory_context_summary(stage3_memory_context),
        },
        "compatibility": {
            "legacyActivePlanId": str((active_plan or {}).get("planId") or ""),
            "historyRewritten": False,
            "appendOnlyEvidencePreserved": True,
        },
    }


def _experiment_planning_status(
    team_id: str,
    rounds: list[dict[str, Any]],
    candidate_store: dict[str, Any],
    plan_store: dict[str, Any],
) -> dict[str, Any]:
    s = _service()
    experiment_rounds = [item for item in rounds if str(item.get("stageType") or "") == "experiment"]
    latest_experiment = s._latest_stage_round(experiment_rounds)
    latest_collection = s._latest_stage_round([item for item in rounds if str(item.get("stageType") or "") == "knowledge_collection"])
    latest_iteration = s._latest_stage_round([item for item in rounds if str(item.get("stageType") or "") == "iteration"])
    hypothesis_candidates = s._experiment_hypothesis_summaries(candidate_store)
    ready_hypotheses = [item for item in hypothesis_candidates if item.get("valid") and not item.get("missingExperimentPlanFields")]
    plans = s._experiment_plans(plan_store)
    active_plan = s._active_experiment_plan(plan_store)
    lifecycle_projection = s._experiment_lifecycle_projection(
        team_id=team_id,
        latest_collection=latest_collection,
        latest_experiment=latest_experiment,
        latest_iteration=latest_iteration,
        candidate_store=candidate_store,
        plans=plans,
        active_plan=active_plan,
    )
    official_model_evidence_store = s._load_program_official_model_evidence_store(team_id)
    challenge_program_projection = build_challenge_program_projection(
        legacy_lifecycle=lifecycle_projection,
        public_config=s.load_public_config(),
        official_model_evidence=s._official_model_evidence_entries(official_model_evidence_store),
        compatibility_case_registry=_load_challenge_program_case_registry(),
        question_run_summary=challenge_question_run_summary(team_id),
    )
    gaps = s._experiment_planning_gaps(
        latest_experiment=latest_experiment,
        hypothesis_candidates=hypothesis_candidates,
        ready_hypotheses=ready_hypotheses,
        active_plan=active_plan,
    )
    status = "blocked"
    active_full_run = active_plan.get("activeFullRunResult") if isinstance((active_plan or {}).get("activeFullRunResult"), dict) else None
    active_full_run_status = str((active_full_run or {}).get("status") or "").strip().lower()
    knowledge_ingestion = active_plan.get("knowledgeIngestion") if isinstance((active_plan or {}).get("knowledgeIngestion"), dict) else None
    knowledge_ingestion_status = str((knowledge_ingestion or {}).get("status") or "").strip().lower()
    if latest_experiment and active_plan and knowledge_ingestion_status in {
        "ingested",
        "knowledge_steward_notified",
        "knowledge_steward_wake_pending",
        "knowledge_steward_notification_failed",
    }:
        status = knowledge_ingestion_status
    elif latest_experiment and active_plan and active_full_run_status == "passed":
        status = "ready_for_knowledge_ingestion"
    elif latest_experiment and active_plan and active_full_run_status in {"failed", "needs_review"}:
        status = "full_run_needs_review"
    elif latest_experiment and active_plan and bool((active_plan.get("readiness") or {}).get("readyForFullRun")):
        status = "ready_for_full_run"
    elif latest_experiment and active_plan and bool((active_plan.get("readiness") or {}).get("readyForSmoke")):
        status = "ready_for_smoke"
    elif latest_experiment and active_plan:
        status = "planned"
    elif latest_experiment and ready_hypotheses:
        status = "ready_to_plan"
    elif latest_experiment:
        status = "needs_hypothesis"
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "teamId": team_id,
        "status": status,
        "latestExperimentRound": latest_experiment,
        "latestKnowledgeCollectionRound": latest_collection,
        "activePlan": active_plan,
        "plans": plans[-12:],
        "lifecycleProjection": lifecycle_projection,
        "challengeProgramProjection": challenge_program_projection,
        "hypothesisCandidates": hypothesis_candidates[:24],
        "readyHypothesisCandidates": ready_hypotheses[:24],
        "gaps": gaps,
        "summary": {
            "experimentRoundCount": len(experiment_rounds),
            "planCount": len(plans),
            "hypothesisCandidateCount": len(hypothesis_candidates),
            "readyHypothesisCandidateCount": len(ready_hypotheses),
            "gapCount": len(gaps),
            "activePlanId": str(active_plan.get("planId") or "") if active_plan else "",
            "activeFullRunResultId": str((active_plan or {}).get("activeFullRunResultId") or "") if active_plan else "",
            "knowledgeIngestionStatus": str(((active_plan or {}).get("knowledgeIngestion") or {}).get("status") or "") if active_plan and isinstance(active_plan.get("knowledgeIngestion"), dict) else "",
            "activeDesignPlanId": lifecycle_projection["stage2"]["activeDesignPlanId"],
            "frozenDesignRevision": lifecycle_projection["stage2"]["frozenDesignRevision"],
            "activeIterationId": lifecycle_projection["stage3"]["activeIterationId"],
            "bestCandidateId": lifecycle_projection["stage3"]["bestCandidateId"],
            "bestValidatedResultId": lifecycle_projection["stage3"]["bestValidatedResultId"],
            "latestDiagnosticStatus": lifecycle_projection["stage3"]["latestDiagnosticStatus"],
        },
        "readiness": {
            "readyToPlan": bool(latest_experiment and ready_hypotheses),
            "readyForSmoke": bool((active_plan or {}).get("readiness", {}).get("readyForSmoke")),
            "readyForFullRun": bool((active_plan or {}).get("readiness", {}).get("readyForFullRun")),
            "readyForKnowledgeIngestion": bool((active_plan or {}).get("readiness", {}).get("readyForKnowledgeIngestion")),
            "reason": s._experiment_planning_readiness_reason(latest_experiment, ready_hypotheses, active_plan),
        },
        "boundaries": s._experiment_planning_boundaries(),
        "storagePath": s._relative_path(s._experiment_plan_store_path(team_id)),
        "nextActions": s._experiment_planning_next_actions(active_plan=active_plan, gaps=gaps),
        "updatedAt": str(plan_store.get("updatedAt") or ""),
    }


def _select_experiment_stage_round(payload: dict[str, Any], rounds: list[dict[str, Any]]) -> dict[str, Any]:
    s = _service()
    research_project_id = s._trim_text(
        payload.get("researchProjectId"),
        max_length=160,
    )
    eligible_rounds = [
        item
        for item in rounds
        if str(item.get("stageType") or "") == "experiment"
        and (
            not research_project_id
            or s._trim_text(item.get("researchProjectId"), max_length=160)
            == research_project_id
        )
    ]
    explicit_round_id = s._trim_text(payload.get("stageRoundId"), max_length=160)
    if explicit_round_id:
        stage_round = s._find_stage_round(eligible_rounds, explicit_round_id)
        if stage_round is None:
            raise s.TeamWorkflowOrchestrationError("Experiment stage round not found.")
        return stage_round
    active_round = s._active_stage_round(eligible_rounds, "experiment")
    if active_round:
        return active_round
    latest_round = s._latest_stage_round(eligible_rounds)
    if latest_round:
        return latest_round
    raise s.TeamWorkflowOrchestrationError("Start an experiment planning stage round before drafting an experiment plan.")


def _select_experiment_hypothesis_candidates(candidate_store: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, Any]]:
    s = _service()
    candidates = s._experiment_hypothesis_candidates(candidate_store)
    explicit_ids = s._normalize_text_list(payload.get("hypothesisCandidateIds"), max_items=16, max_length=160)
    if explicit_ids:
        by_id = {str(item.get("candidateId") or ""): item for item in candidates}
        selected = [by_id[item_id] for item_id in explicit_ids if item_id in by_id]
        if len(selected) != len(explicit_ids):
            raise s.TeamWorkflowOrchestrationError("One or more hypothesis candidates were not found.")
        return selected
    ready = [
        item
        for item in candidates
        if s.validate_candidate_record(item).get("valid") is True
        and not s._experiment_hypothesis_missing_fields(item)
        and not s._candidate_is_archived(item)
    ]
    return ready[:8]


def _build_experiment_plan_record(
    team_id: str,
    workflow: dict[str, Any],
    stage_round: dict[str, Any],
    selected_hypotheses: list[dict[str, Any]],
    payload: dict[str, Any],
    *,
    created_by_agent: str,
) -> dict[str, Any]:
    s = _service()
    now = s.utc_now_iso()
    hypothesis_summaries = [s._experiment_hypothesis_summary(item) for item in selected_hypotheses]
    payload_plan = payload.get("experimentPlan") if isinstance(payload.get("experimentPlan"), dict) else {}
    payload_method_config = payload.get("methodConfig") if isinstance(payload.get("methodConfig"), dict) else {}
    payload_metric_contract = (
        payload.get("metricContract")
        if isinstance(payload.get("metricContract"), dict)
        else {}
    )
    dataset = next(
        (
            text
            for value in (
                payload.get("dataset"),
                payload_plan.get("dataset"),
                payload_method_config.get("dataset"),
                *[
                    item.get("experimentPlan", {}).get("dataset")
                    for item in hypothesis_summaries
                ],
            )
            if (
                text := _experiment_plan_field_text(
                    value,
                    preferred_keys=("name", "dataset", "label", "id"),
                    max_length=500,
                )
            )
        ),
        "",
    )
    metric = next(
        (
            text
            for value in (
                payload.get("metric"),
                payload_plan.get("metric"),
                payload_metric_contract.get("primaryMetric"),
                *[
                    item.get("experimentPlan", {}).get("metric")
                    for item in hypothesis_summaries
                ],
            )
            if (
                text := _experiment_plan_field_text(
                    value,
                    preferred_keys=("primaryMetric", "name", "metric", "label"),
                    max_length=500,
                )
            )
        ),
        "",
    )
    baseline = next(
        (
            text
            for value in (
                payload.get("baseline"),
                payload_plan.get("baseline"),
                payload_method_config.get("baseline"),
                *[
                    item.get("experimentPlan", {}).get("baseline")
                    for item in hypothesis_summaries
                ],
                *[item.get("baseline") for item in hypothesis_summaries],
            )
            if (
                text := _experiment_plan_field_text(
                    value,
                    preferred_keys=("name", "baseline", "label", "id"),
                    max_length=500,
                )
            )
        ),
        "",
    )
    smoke_plan = next(
        (
            text
            for value in (
                payload.get("smokePlan"),
                payload_plan.get("smokePlan"),
                payload_method_config.get("smokePlan"),
                *[
                    item.get("experimentPlan", {}).get("smokePlan")
                    for item in hypothesis_summaries
                ],
            )
            if (
                text := _experiment_plan_field_text(
                    value,
                    preferred_keys=("protocol", "smokePlan", "summary", "label"),
                    max_length=1200,
                )
            )
        ),
        "",
    )
    plan_id = s._new_record_id("exp-plan")
    hypothesis_refs = [str(item.get("candidateId") or "") for item in selected_hypotheses if item.get("candidateId")]
    evidence_refs = s._dedupe_text_values(
        [
            s._first_non_empty_text(ref.get("id"), ref.get("evidenceRef"), ref.get("sourceRef"))
            for item in hypothesis_summaries
            for ref in list(item.get("evidenceRefs") or [])
            if isinstance(ref, dict)
        ],
    )
    research_question = s._first_non_empty_text(
        payload.get("researchQuestion"),
        stage_round.get("goal"),
        stage_round.get("topic"),
        *[item.get("hypothesis") for item in hypothesis_summaries],
    )
    legacy_experiment_plan = {
        "dataset": dataset,
        "metric": metric,
        "baseline": baseline,
        "smokePlan": smoke_plan,
    }
    contract = s.experiment_contract.build_experiment_contract(
        plan_id=plan_id,
        team_id=team_id,
        research_question=research_question,
        payload=payload,
        legacy_plan=legacy_experiment_plan,
        hypothesis_refs=hypothesis_refs,
        evidence_refs=evidence_refs,
    )
    contract_validation = s.experiment_contract.validate_experiment_contract(contract)
    checklist = s._experiment_plan_checklist(
        stage_round=stage_round,
        hypothesis_summaries=hypothesis_summaries,
        dataset=dataset,
        metric=metric,
        baseline=baseline,
        smoke_plan=smoke_plan,
        active_baseline_artifact=None,
    )
    ready_for_plan_review = all(item["status"] == "pass" for item in checklist if item["item"] != "active_baseline_record")
    blockers = [item["item"] for item in checklist if item["status"] != "pass"]
    iteration_contract = contract.get("iterationContract") if isinstance(contract.get("iterationContract"), dict) else {}
    source_proposal_id = s._trim_text(iteration_contract.get("sourceProposalId"), max_length=160)
    design_gate = None
    if contract_validation.get("valid") is True:
        design_gate = {
            "status": "draft",
            "requiresExplicitFreeze": True,
            "source": "native_v2_plan",
            "sourceLoopId": "",
            "sourceDecisionId": "",
            "sourceProposalId": "",
            "sourceIdempotencyKey": "",
            "frozenAt": "",
            "frozenByAgent": "",
        }
    if source_proposal_id:
        if design_gate is None:
            design_gate = {
                "status": "draft",
                "requiresExplicitFreeze": True,
                "source": "research_loop_decision",
                "sourceLoopId": "",
                "sourceDecisionId": "",
                "sourceProposalId": "",
                "sourceIdempotencyKey": "",
                "frozenAt": "",
                "frozenByAgent": "",
            }
        design_gate.update(
            {
                "source": "research_loop_decision",
                "sourceLoopId": s._trim_text(iteration_contract.get("sourceLoopId"), max_length=160),
                "sourceDecisionId": s._trim_text(iteration_contract.get("sourceDecisionId"), max_length=160),
                "sourceProposalId": source_proposal_id,
                "sourceIdempotencyKey": s._trim_text(iteration_contract.get("sourceIdempotencyKey"), max_length=240),
            }
        )
    record = {
        "schemaVersion": s.SCHEMA_VERSION,
        "planId": plan_id,
        "teamId": team_id,
        "workflowId": workflow.get("workflowId", s.DEFAULT_WORKFLOW_ID),
        "stageRoundId": stage_round.get("stageRoundId", ""),
        "stageRoundNumber": stage_round.get("roundNumber", 0),
        "status": "draft",
        "title": s._trim_text(payload.get("title"), max_length=240) or f"Experiment plan for {stage_round.get('topic') or 'Challenge Cup'}",
        "topic": stage_round.get("topic", ""),
        "goal": stage_round.get("goal", ""),
        "selectedHypotheses": hypothesis_summaries,
        "hypothesisCandidateIds": hypothesis_refs,
        "upstreamRoundIds": list(stage_round.get("upstreamRoundIds") or []),
        "experimentContract": contract,
        "contractValidation": contract_validation,
        "contractMigration": {
            "status": "native_v2",
            "sourceSchemaVersion": s.experiment_contract.SCHEMA_VERSION,
            "targetSchemaVersion": s.experiment_contract.SCHEMA_VERSION,
            "missingFields": list(contract_validation.get("missingFields") or []),
            "persistOnNextMutation": False,
        },
        "compatibility": {
            "legacyExperimentPlanProjection": "read_only_derived",
            "removalTrigger": "Teams experiment card and all API clients consume experimentContract schema v2",
        },
        "experimentPlan": legacy_experiment_plan,
        "baselineSelection": {
            "baseline": baseline,
            "status": "planned_not_validated" if baseline else "missing",
            "activeBaselineReady": False,
            "reason": "Baseline is selected from candidate evidence, but no reproducible active baseline artifact has been registered yet."
            if baseline
            else "No baseline selected yet.",
        },
        "successMetrics": s._dedupe_text_values([metric]),
        "riskControls": {
            "autoExecution": False,
            "requiresUserDecision": True,
            "smokeGateRequired": True,
            "fullRunBlockedUntil": blockers,
        },
        "readinessChecklist": checklist,
        "readiness": {
            "readyForPlanReview": ready_for_plan_review,
            "readyForSmoke": False,
            "readyForFullRun": False,
            "blockers": blockers,
        },
        "notes": s._trim_text(payload.get("notes"), max_length=4000),
        "createdByAgent": created_by_agent,
        "createdFromTaskId": s._trim_text(
            payload.get("createdFromTaskId"),
            max_length=160,
        ),
        "createdFromSessionId": s._trim_text(
            payload.get("createdFromSessionId"),
            max_length=160,
        ),
        "createdFromTurnId": s._trim_text(
            payload.get("createdFromTurnId"),
            max_length=200,
        ),
        "createdAt": now,
        "updatedAt": now,
    }
    if design_gate is not None:
        record["designGate"] = design_gate
    return record


def _experiment_hypothesis_candidates(candidate_store: dict[str, Any]) -> list[dict[str, Any]]:
    s = _service()
    candidates = [
        item
        for item in list(candidate_store.get("candidates") or [])
        if isinstance(item, dict)
        and str(item.get("candidateType") or "") == "algorithm_hypothesis"
        and not s._candidate_is_archived(item)
    ]
    return sorted(candidates, key=lambda item: (str(item.get("updatedAt") or ""), str(item.get("candidateId") or "")), reverse=True)


def _experiment_hypothesis_summaries(candidate_store: dict[str, Any]) -> list[dict[str, Any]]:
    s = _service()
    return [s._experiment_hypothesis_summary(item) for item in s._experiment_hypothesis_candidates(candidate_store)]


def _experiment_hypothesis_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    output = metadata.get("output") if isinstance(metadata.get("output"), dict) else {}
    experiment_plan = output.get("experimentPlan") if isinstance(output.get("experimentPlan"), dict) else {}
    validation = s.validate_candidate_record(candidate)
    missing_fields = [field for field in s.EXPERIMENT_PLAN_REQUIRED_FIELDS if not s._has_value(experiment_plan.get(field))]
    return {
        "candidateId": str(candidate.get("candidateId") or ""),
        "title": str(candidate.get("title") or ""),
        "summary": str(candidate.get("summary") or ""),
        "currentWorkflowNode": str(candidate.get("currentWorkflowNode") or ""),
        "currentState": str(candidate.get("currentState") or ""),
        "qualityStatus": str(candidate.get("qualityStatus") or ""),
        "valid": validation.get("valid") is True,
        "validationIssueCount": len(validation.get("issues") or []),
        "hypothesis": s._trim_text(output.get("hypothesis"), max_length=1000),
        "baseline": s._trim_text(output.get("baseline"), max_length=500),
        "expectedBenefit": s._trim_text(output.get("expectedBenefit"), max_length=1000),
        "expectedComputeCost": s._trim_text(output.get("expectedComputeCost"), max_length=1000),
        "experimentPlan": {
            "dataset": s._trim_text(experiment_plan.get("dataset"), max_length=500),
            "metric": s._trim_text(experiment_plan.get("metric"), max_length=500),
            "baseline": s._trim_text(experiment_plan.get("baseline"), max_length=500),
            "smokePlan": s._trim_text(experiment_plan.get("smokePlan"), max_length=1200),
        },
        "missingExperimentPlanFields": missing_fields,
        "sourceRefs": s._normalize_ref_list(candidate.get("sourceRefs") or output.get("sourceRefs"), max_items=12),
        "evidenceRefs": s._normalize_ref_list(candidate.get("evidenceRefs") or output.get("evidenceRefs"), max_items=12),
        "updatedAt": str(candidate.get("updatedAt") or ""),
    }


def _experiment_hypothesis_missing_fields(candidate: dict[str, Any]) -> list[str]:
    s = _service()
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    output = metadata.get("output") if isinstance(metadata.get("output"), dict) else {}
    experiment_plan = output.get("experimentPlan") if isinstance(output.get("experimentPlan"), dict) else {}
    return [field for field in s.EXPERIMENT_PLAN_REQUIRED_FIELDS if not s._has_value(experiment_plan.get(field))]


def _find_experiment_plan(plan_store: dict[str, Any], plan_id: str) -> dict[str, Any] | None:
    for plan in list(plan_store.get("plans") or []):
        if isinstance(plan, dict) and str(plan.get("planId") or "") == plan_id:
            return plan
    return None


def _experiment_baseline_artifact_record(
    plan: dict[str, Any],
    payload: dict[str, Any],
    *,
    registered_by_agent: str,
) -> dict[str, Any]:
    s = _service()
    experiment_plan = plan.get("experimentPlan") if isinstance(plan.get("experimentPlan"), dict) else {}
    baseline_selection = plan.get("baselineSelection") if isinstance(plan.get("baselineSelection"), dict) else {}
    artifact_path = s._trim_text(payload.get("artifactPath"), max_length=500)
    reproduction_command = s._trim_text(payload.get("reproductionCommand"), max_length=1200)
    if not artifact_path:
        raise s.TeamWorkflowOrchestrationError("Baseline artifact path is required.")
    if not reproduction_command:
        raise s.TeamWorkflowOrchestrationError("Baseline reproduction command is required.")
    now = s.utc_now_iso()
    return {
        "artifactId": s._new_record_id("baseline-artifact"),
        "status": "registered",
        "baseline": s._first_non_empty_text(payload.get("baselineName"), baseline_selection.get("baseline"), experiment_plan.get("baseline")),
        "dataset": s._first_non_empty_text(payload.get("datasetRef"), experiment_plan.get("dataset")),
        "metric": s._first_non_empty_text(payload.get("metricName"), experiment_plan.get("metric")),
        "metricValue": s._trim_text(payload.get("metricValue"), max_length=240),
        "artifactPath": artifact_path,
        "evidenceRef": s._trim_text(payload.get("evidenceRef"), max_length=500),
        "reproductionCommand": reproduction_command,
        "evaluationCommand": s._trim_text(payload.get("evaluationCommand"), max_length=1200),
        "sourceRefs": s._normalize_ref_list(payload.get("sourceRefs"), max_items=12),
        "evidenceRefs": s._normalize_ref_list(payload.get("evidenceRefs"), max_items=12),
        "notes": s._trim_text(payload.get("notes"), max_length=4000),
        "metadata": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
        "registeredByAgent": registered_by_agent,
        "registeredAt": now,
    }


def _experiment_smoke_result_record(
    plan: dict[str, Any],
    payload: dict[str, Any],
    *,
    recorded_by_agent: str,
) -> dict[str, Any]:
    s = _service()
    baseline_selection = plan.get("baselineSelection") if isinstance(plan.get("baselineSelection"), dict) else {}
    active_baseline_artifact = (
        baseline_selection.get("activeBaselineArtifact")
        if isinstance(baseline_selection.get("activeBaselineArtifact"), dict)
        else None
    )
    if not active_baseline_artifact:
        raise s.TeamWorkflowOrchestrationError("Register an active baseline artifact before recording smoke results.")
    experiment_plan = plan.get("experimentPlan") if isinstance(plan.get("experimentPlan"), dict) else {}
    status = s._trim_text(payload.get("status"), max_length=80).lower() or "needs_review"
    if status not in s.EXPERIMENT_SMOKE_RESULT_STATUSES:
        raise s.TeamWorkflowOrchestrationError(f"Unsupported smoke result status: {status}")
    metric_value = s._trim_text(payload.get("metricValue"), max_length=240)
    result_path = s._trim_text(payload.get("resultPath") or payload.get("artifactPath"), max_length=500)
    log_ref = s._trim_text(payload.get("logRef") or payload.get("evidenceRef"), max_length=500)
    if not metric_value:
        raise s.TeamWorkflowOrchestrationError("Smoke result metric value is required.")
    if not result_path and not log_ref:
        raise s.TeamWorkflowOrchestrationError("Smoke result path or log reference is required.")
    now = s.utc_now_iso()
    gate_decision = {
        "passed": "promote_to_full_run",
        "failed": "reject_or_repair",
        "needs_review": "needs_more_evidence",
    }[status]
    return {
        "smokeResultId": s._new_record_id("smoke-result"),
        "status": status,
        "gateDecision": gate_decision,
        "planId": str(plan.get("planId") or ""),
        "baselineArtifactId": str(active_baseline_artifact.get("artifactId") or ""),
        "baselineMetricValue": s._first_non_empty_text(payload.get("baselineMetricValue"), active_baseline_artifact.get("metricValue")),
        "metricName": s._first_non_empty_text(payload.get("metricName"), active_baseline_artifact.get("metric"), experiment_plan.get("metric")),
        "metricValue": metric_value,
        "delta": s._trim_text(payload.get("delta"), max_length=240),
        "resultPath": result_path,
        "logRef": log_ref,
        "evaluationCommand": s._trim_text(payload.get("evaluationCommand") or payload.get("command"), max_length=1200),
        "sourceRefs": s._normalize_ref_list(payload.get("sourceRefs"), max_items=12),
        "evidenceRefs": s._normalize_ref_list(payload.get("evidenceRefs"), max_items=12),
        "notes": s._trim_text(payload.get("notes"), max_length=4000),
        "metadata": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
        "recordedByAgent": recorded_by_agent,
        "recordedAt": now,
    }


def _experiment_full_run_result_record(
    plan: dict[str, Any],
    payload: dict[str, Any],
    *,
    recorded_by_agent: str,
) -> dict[str, Any]:
    s = _service()
    active_smoke_result = plan.get("activeSmokeResult") if isinstance(plan.get("activeSmokeResult"), dict) else None
    if not active_smoke_result or str(active_smoke_result.get("status") or "").strip().lower() != "passed":
        raise s.TeamWorkflowOrchestrationError("Record a passing smoke result before recording full-run results.")
    if not bool((plan.get("readiness") or {}).get("readyForFullRun")):
        raise s.TeamWorkflowOrchestrationError("Experiment plan is not ready for full-run result recording.")
    status = s._trim_text(payload.get("status"), max_length=80).lower() or "needs_review"
    if status not in s.EXPERIMENT_FULL_RUN_RESULT_STATUSES:
        raise s.TeamWorkflowOrchestrationError(f"Unsupported full-run result status: {status}")
    metric_value = s._trim_text(payload.get("metricValue"), max_length=240)
    result_path = s._trim_text(payload.get("resultPath") or payload.get("artifactPath"), max_length=500)
    log_ref = s._trim_text(payload.get("logRef") or payload.get("evidenceRef"), max_length=500)
    if not metric_value:
        raise s.TeamWorkflowOrchestrationError("Full-run result metric value is required.")
    if not result_path and not log_ref:
        raise s.TeamWorkflowOrchestrationError("Full-run result path or log reference is required.")
    baseline_selection = plan.get("baselineSelection") if isinstance(plan.get("baselineSelection"), dict) else {}
    active_baseline_artifact = (
        baseline_selection.get("activeBaselineArtifact")
        if isinstance(baseline_selection.get("activeBaselineArtifact"), dict)
        else {}
    )
    experiment_plan = plan.get("experimentPlan") if isinstance(plan.get("experimentPlan"), dict) else {}
    now = s.utc_now_iso()
    gate_decision = {
        "passed": "ready_for_knowledge_review",
        "failed": "reject_or_repair",
        "needs_review": "needs_more_evidence",
    }[status]
    return {
        "fullRunResultId": s._new_record_id("full-run-result"),
        "status": status,
        "gateDecision": gate_decision,
        "planId": str(plan.get("planId") or ""),
        "smokeResultId": str(active_smoke_result.get("smokeResultId") or ""),
        "baselineArtifactId": str(active_baseline_artifact.get("artifactId") or ""),
        "baselineMetricValue": s._first_non_empty_text(payload.get("baselineMetricValue"), active_baseline_artifact.get("metricValue")),
        "smokeMetricValue": s._first_non_empty_text(payload.get("smokeMetricValue"), active_smoke_result.get("metricValue")),
        "metricName": s._first_non_empty_text(payload.get("metricName"), active_smoke_result.get("metricName"), active_baseline_artifact.get("metric"), experiment_plan.get("metric")),
        "metricValue": metric_value,
        "delta": s._trim_text(payload.get("delta"), max_length=240),
        "resultPath": result_path,
        "logRef": log_ref,
        "configPath": s._trim_text(payload.get("configPath"), max_length=500),
        "reproductionCommand": s._trim_text(payload.get("reproductionCommand"), max_length=1200),
        "evaluationCommand": s._trim_text(payload.get("evaluationCommand") or payload.get("command"), max_length=1200),
        "sourceRefs": s._normalize_ref_list(payload.get("sourceRefs"), max_items=12),
        "evidenceRefs": s._normalize_ref_list(payload.get("evidenceRefs"), max_items=12),
        "notes": s._trim_text(payload.get("notes"), max_length=4000),
        "metadata": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
        "recordedByAgent": recorded_by_agent,
        "recordedAt": now,
    }


def _experiment_result_ingestion_pack_record(
    plan: dict[str, Any],
    payload: dict[str, Any],
    *,
    knowledge_base_id: str,
    target_domain: str,
    requested_by_agent: str,
) -> dict[str, Any]:
    s = _service()
    active_full_run = plan.get("activeFullRunResult") if isinstance(plan.get("activeFullRunResult"), dict) else None
    if not active_full_run or str(active_full_run.get("status") or "").strip().lower() != "passed":
        raise s.TeamWorkflowOrchestrationError("Record a passing full-run result before requesting knowledge ingestion.")
    experiment_plan = plan.get("experimentPlan") if isinstance(plan.get("experimentPlan"), dict) else {}
    baseline_selection = plan.get("baselineSelection") if isinstance(plan.get("baselineSelection"), dict) else {}
    active_baseline_artifact = (
        baseline_selection.get("activeBaselineArtifact")
        if isinstance(baseline_selection.get("activeBaselineArtifact"), dict)
        else {}
    )
    active_smoke_result = plan.get("activeSmokeResult") if isinstance(plan.get("activeSmokeResult"), dict) else {}
    now = s.utc_now_iso()
    artifact_refs = [
        {
            "type": "baseline_artifact",
            "id": str(active_baseline_artifact.get("artifactId") or ""),
            "path": str(active_baseline_artifact.get("artifactPath") or ""),
        },
        {
            "type": "smoke_result",
            "id": str(active_smoke_result.get("smokeResultId") or ""),
            "path": str(active_smoke_result.get("resultPath") or ""),
            "logRef": str(active_smoke_result.get("logRef") or ""),
        },
        {
            "type": "full_run_result",
            "id": str(active_full_run.get("fullRunResultId") or ""),
            "path": str(active_full_run.get("resultPath") or ""),
            "logRef": str(active_full_run.get("logRef") or ""),
            "configPath": str(active_full_run.get("configPath") or ""),
        },
    ]
    selected_hypotheses = [item for item in list(plan.get("selectedHypotheses") or []) if isinstance(item, dict)]
    return {
        "packId": s._new_record_id("experiment-result-pack"),
        "kind": "challenge_cup_experiment_result_pack",
        "status": "ready_for_knowledge_steward",
        "planId": str(plan.get("planId") or ""),
        "teamId": str(plan.get("teamId") or ""),
        "stageRoundId": str(plan.get("stageRoundId") or ""),
        "fullRunResultId": str(active_full_run.get("fullRunResultId") or ""),
        "knowledgeBaseId": knowledge_base_id,
        "targetDomain": target_domain,
        "title": s._trim_text(payload.get("title"), max_length=240) or f"Experiment result for {plan.get('title') or plan.get('topic') or 'Challenge Cup'}",
        "summary": s._trim_text(payload.get("summary"), max_length=4000)
        or f"Full-run {active_full_run.get('status')} result: {active_full_run.get('metricName') or experiment_plan.get('metric')} = {active_full_run.get('metricValue')}.",
        "hypothesisCandidateIds": [str(item.get("candidateId") or "") for item in selected_hypotheses if item.get("candidateId")],
        "selectedHypotheses": selected_hypotheses,
        "experimentPlan": {
            "dataset": s._trim_text(experiment_plan.get("dataset"), max_length=500),
            "metric": s._trim_text(experiment_plan.get("metric"), max_length=500),
            "baseline": s._trim_text(experiment_plan.get("baseline"), max_length=500),
            "smokePlan": s._trim_text(experiment_plan.get("smokePlan"), max_length=1200),
        },
        "metrics": {
            "baselineMetricValue": str(active_full_run.get("baselineMetricValue") or ""),
            "smokeMetricValue": str(active_full_run.get("smokeMetricValue") or ""),
            "fullRunMetricName": str(active_full_run.get("metricName") or ""),
            "fullRunMetricValue": str(active_full_run.get("metricValue") or ""),
            "delta": str(active_full_run.get("delta") or ""),
            "verdict": "supports" if str(active_full_run.get("status") or "") == "passed" else "inconclusive",
        },
        "artifactRefs": [item for item in artifact_refs if item.get("id") or item.get("path") or item.get("logRef")],
        "sourceRefs": s._normalize_ref_list(payload.get("sourceRefs") or active_full_run.get("sourceRefs"), max_items=12),
        "evidenceRefs": s._normalize_ref_list(payload.get("evidenceRefs") or active_full_run.get("evidenceRefs"), max_items=12),
        "notes": s._trim_text(payload.get("notes"), max_length=4000),
        "metadata": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
        "officialBoundary": {
            "currentWritesOfficialKnowledge": False,
            "currentWritesOfficialRag": False,
            "currentWritesOfficialGraph": False,
            "rawLogsStoredOutsideRag": True,
            "ragUsesCuratedSummaryOnly": True,
            "finalIngestionOwnedByKnowledgeSteward": True,
        },
        "requestedByAgent": requested_by_agent,
        "createdAt": now,
    }


def _notify_knowledge_steward_for_experiment_result(
    team_id: str,
    *,
    steward_agent_id: str,
    requester_agent_id: str,
    experiment_result_pack: dict[str, Any],
    knowledge_base_id: str,
    target_domain: str,
    wake_target: bool,
) -> dict[str, Any]:
    s = _service()
    pack_id = str(experiment_result_pack.get("packId") or "")
    full_run_result_id = str(experiment_result_pack.get("fullRunResultId") or "")
    plan_id = str(experiment_result_pack.get("planId") or "")
    activation = {
        "status": "disabled",
        "targetAgentId": steward_agent_id,
        "messageId": "",
        "threadId": "",
        "wakeRequested": bool(wake_target),
        "wakeStatus": "not_requested",
        "delivery": None,
        "metadata": {
            "kind": "challenge_cup_experiment_result_ingestion_request",
            "teamId": team_id,
            "planId": plan_id,
            "experimentResultPackId": pack_id,
            "fullRunResultId": full_run_result_id,
            "knowledgeBaseId": knowledge_base_id,
            "targetDomain": target_domain,
        },
    }
    if not steward_agent_id:
        activation["status"] = "skipped_missing_steward_agent"
        return activation

    target_agent = s.agent_directory_service.get_agent(steward_agent_id, include_archived=True)
    if not target_agent:
        activation["status"] = "skipped_missing_steward_agent"
        return activation
    if str(target_agent.get("status") or "active").strip().lower() == "archived":
        activation["status"] = "skipped_archived_steward_agent"
        return activation

    source_agent_id = requester_agent_id if requester_agent_id and s.agent_directory_service.get_agent(requester_agent_id, include_archived=True) else ""
    controlled_pack = {
        "packId": pack_id,
        "kind": str(experiment_result_pack.get("kind") or ""),
        "teamId": team_id,
        "planId": plan_id,
        "fullRunResultId": full_run_result_id,
        "knowledgeBaseId": knowledge_base_id,
        "targetDomain": target_domain,
        "title": str(experiment_result_pack.get("title") or ""),
        "summary": str(experiment_result_pack.get("summary") or ""),
        "selectedHypotheses": list(experiment_result_pack.get("selectedHypotheses") or []),
        "experimentPlan": dict(experiment_result_pack.get("experimentPlan") or {}),
        "metrics": dict(experiment_result_pack.get("metrics") or {}),
        "artifactRefs": list(experiment_result_pack.get("artifactRefs") or []),
        "sourceRefs": list(experiment_result_pack.get("sourceRefs") or []),
        "evidenceRefs": list(experiment_result_pack.get("evidenceRefs") or []),
        "notes": str(experiment_result_pack.get("notes") or ""),
        "officialBoundary": dict(experiment_result_pack.get("officialBoundary") or {}),
    }
    controlled_pack_json = json.dumps(
        controlled_pack,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    try:
        inbox_source = s.team_knowledge_service.collect_source_to_inbox(
            "team",
            team_id,
            source_type="runtime_evidence_refinement",
            source_ref={
                "kind": "challenge_cup_experiment_result_pack",
                "teamId": team_id,
                "planId": plan_id,
                "experimentResultPackId": pack_id,
                "fullRunResultId": full_run_result_id,
                "artifactRefs": list(controlled_pack["artifactRefs"]),
            },
            original_content=controlled_pack_json,
            original_filename=(
                f"{s._safe_token(pack_id, default='experiment-result-pack', max_length=96)}.json"
            ),
            source_created_at=str(experiment_result_pack.get("createdAt") or ""),
            captured_by=requester_agent_id or "team_workflow",
            evidence_range={
                "kind": "experiment_result_pack",
                "fullRunResultId": full_run_result_id,
                "artifactCount": len(controlled_pack["artifactRefs"]),
                "evidenceRefCount": len(controlled_pack["evidenceRefs"]),
            },
            title=str(experiment_result_pack.get("title") or "Challenge Cup experiment result"),
            summary=str(experiment_result_pack.get("summary") or ""),
            actor_agent_id=steward_agent_id,
        )
    except (
        s.team_knowledge_service.TeamKnowledgeError,
        s.team_knowledge_service.TeamKnowledgeNotFoundError,
    ) as exc:
        activation["status"] = "source_staging_failed"
        activation["error"] = str(exc)
        return activation
    inbox_source_id = str(inbox_source.get("inboxSourceId") or "")
    activation["inboxSourceId"] = inbox_source_id
    activation["metadata"]["inboxSourceId"] = inbox_source_id
    activation["metadata"]["ownerType"] = "team"
    activation["metadata"]["ownerId"] = team_id
    activation["metadata"]["requiredTool"] = "knowledge_ingestion_tool"
    content = "\n".join(
        [
            "[挑战杯实验结果入库请求]",
            f"团队: {team_id}",
            f"实验计划: {plan_id}",
            f"实验结果包: {pack_id}",
            f"Full-run 结果: {full_run_result_id}",
            f"Team source inbox: {inbox_source_id}",
            f"目标知识库: {knowledge_base_id}",
            f"知识域: {target_domain}",
            "",
            (
                "受控 experimentResultPack 已在本消息末尾完整提供；"
                "不要读取本地 workflow 文件，也不要向其他 Agent 索要同一上下文。"
            ),
            (
                "请复核 hypothesis、experimentPlan、metrics、artifactRefs、"
                "sourceRefs、evidenceRefs 和 officialBoundary。"
            ),
            "证据充分时，调用 knowledge_ingestion_tool，并传入：",
            f'- knowledge_base_id="{knowledge_base_id}"',
            '- source_type="runtime_evidence_refinement"',
            (
                f'- inbox_source_id="{inbox_source_id}", owner_type="team", '
                f'owner_id="{team_id}", review_decision="accepted"'
            ),
            (
                "- proposal_title/proposal_summary/proposal_content "
                "仅写入带适用范围和限制的整理结论"
            ),
            (
                "- resolution_note 记录证据审查结论；"
                "原始日志和大文件只保留 artifactRefs 路径引用"
            ),
            (
                "证据不足时仍调用 knowledge_ingestion_tool，将 review_decision 设为 rejected，"
                "并在 resolution_note 说明缺口。"
            ),
            (
                "本任务无需调用 agent_message_tool；最终回复必须报告 ingestion status、"
                "inboxSourceId、KnowledgeItem 或拒绝原因。"
            ),
            "",
            "experimentResultPack JSON:",
            controlled_pack_json,
        ]
    )
    thread_id = f"challenge-cup-experiment-ingestion:{team_id}:{pack_id}"
    message_summary = f"挑战杯实验结果包 {pack_id} 请求最终入库。"
    try:
        message, delivery, kernel_result = s._submit_team_workflow_inbox_via_kernel(
            target_agent_id=steward_agent_id,
            content=content,
            source_agent_id=source_agent_id,
            thread_id=thread_id,
            kind="challenge_cup_experiment_result_ingestion_request",
            summary=message_summary,
            created_by=requester_agent_id or "team_workflow",
            wake_target=wake_target,
            metadata={
                **activation["metadata"],
                "requesterAgentId": requester_agent_id,
                "expectedAction": "review_experiment_result_pack_to_team_knowledge",
                "officialBoundary": dict(experiment_result_pack.get("officialBoundary") or {}),
            },
        )
    except Exception as exc:
        activation["status"] = "message_failed"
        activation["error"] = str(exc)
        return activation

    activation.update(
        {
            "status": "message_written",
            "messageId": str(message.get("messageId") or message.get("eventId") or ""),
            "threadId": str(message.get("threadId") or ""),
            "message": message,
            "kernel": s._team_workflow_kernel_summary(kernel_result),
        }
    )
    if wake_target:
        activation["delivery"] = delivery
        activation["wakeStatus"] = str((delivery or {}).get("wakeStatus") or "unknown")
        if activation["wakeStatus"] == "started":
            activation["status"] = "agent_wake_started"
        else:
            activation["status"] = f"agent_wake_{activation['wakeStatus']}"
    return activation


def _refresh_experiment_plan_readiness(plan: dict[str, Any]) -> None:
    s = _service()
    experiment_plan = plan.get("experimentPlan") if isinstance(plan.get("experimentPlan"), dict) else {}
    baseline_selection = plan.get("baselineSelection") if isinstance(plan.get("baselineSelection"), dict) else {}
    active_baseline_artifact = baseline_selection.get("activeBaselineArtifact") if isinstance(baseline_selection.get("activeBaselineArtifact"), dict) else None
    checklist = s._experiment_plan_checklist(
        stage_round={"stageRoundId": plan.get("stageRoundId", "")} if plan.get("stageRoundId") else {},
        hypothesis_summaries=[item for item in list(plan.get("selectedHypotheses") or []) if isinstance(item, dict)],
        dataset=s._trim_text(experiment_plan.get("dataset"), max_length=500),
        metric=s._trim_text(experiment_plan.get("metric"), max_length=500),
        baseline=s._trim_text(experiment_plan.get("baseline") or baseline_selection.get("baseline"), max_length=500),
        smoke_plan=s._trim_text(experiment_plan.get("smokePlan"), max_length=1200),
        active_baseline_artifact=active_baseline_artifact,
    )
    smoke_blockers = [item["item"] for item in checklist if item["status"] != "pass"]
    active_smoke_result = s._active_experiment_smoke_evidence(plan)
    active_smoke_status = s._trim_text((active_smoke_result or {}).get("status"), max_length=80).lower()
    active_full_run_result = plan.get("activeFullRunResult") if isinstance(plan.get("activeFullRunResult"), dict) else None
    active_full_run_status = s._trim_text((active_full_run_result or {}).get("status"), max_length=80).lower()
    if smoke_blockers:
        full_run_blockers = smoke_blockers
    elif active_smoke_status == "passed":
        full_run_blockers = []
    else:
        full_run_blockers = ["smoke_result"]
    knowledge_blockers = [] if active_full_run_status == "passed" else ["full_run_result"]
    plan["readinessChecklist"] = checklist
    plan["readiness"] = {
        "readyForPlanReview": all(item["status"] == "pass" for item in checklist if item["item"] != "active_baseline_record"),
        "readyForSmoke": not smoke_blockers,
        "readyForFullRun": not full_run_blockers,
        "readyForKnowledgeIngestion": not knowledge_blockers,
        "blockers": full_run_blockers,
        "knowledgeBlockers": knowledge_blockers,
    }
    risk_controls = plan.get("riskControls") if isinstance(plan.get("riskControls"), dict) else {}
    risk_controls["autoExecution"] = False
    risk_controls["requiresUserDecision"] = True
    risk_controls["smokeGateRequired"] = True
    risk_controls["fullRunBlockedUntil"] = full_run_blockers
    risk_controls["activeSmokeResultStatus"] = active_smoke_status
    risk_controls["activeSmokeEvidenceKind"] = (
        "registered_result" if isinstance(plan.get("activeSmokeResult"), dict) else "runner_result"
        if isinstance(plan.get("activeSmokeRun"), dict)
        else ""
    )
    risk_controls["knowledgeIngestionBlockedUntil"] = knowledge_blockers
    risk_controls["activeFullRunResultStatus"] = active_full_run_status
    plan["riskControls"] = risk_controls
    s.experiment_contract.sync_plan_record_contract_status(plan)


def _active_experiment_smoke_evidence(plan: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(plan, dict):
        return None
    registered = plan.get("activeSmokeResult")
    if isinstance(registered, dict):
        return registered
    runner = plan.get("activeSmokeRun")
    return runner if isinstance(runner, dict) else None


def _experiment_plan_checklist(
    *,
    stage_round: dict[str, Any],
    hypothesis_summaries: list[dict[str, Any]],
    dataset: str,
    metric: str,
    baseline: str,
    smoke_plan: str,
    active_baseline_artifact: dict[str, Any] | None,
) -> list[dict[str, str]]:
    s = _service()
    artifact_note = ""
    if active_baseline_artifact:
        artifact_note = s._trim_text(
            active_baseline_artifact.get("artifactPath") or active_baseline_artifact.get("evidenceRef"),
            max_length=1200,
        )
    return [
        s._experiment_checklist_item("experiment_stage_round", "实验轮次", bool(stage_round), "Experiment planning stage round is available."),
        s._experiment_checklist_item("algorithm_hypothesis", "算法假设", bool(hypothesis_summaries), f"{len(hypothesis_summaries)} hypothesis candidate(s) selected."),
        s._experiment_checklist_item("dataset", "数据集", bool(dataset), dataset or "Dataset is missing."),
        s._experiment_checklist_item("metric", "指标", bool(metric), metric or "Metric is missing."),
        s._experiment_checklist_item("baseline", "Baseline", bool(baseline), baseline or "Baseline is missing."),
        s._experiment_checklist_item("smoke_plan", "Smoke gate", bool(smoke_plan), smoke_plan or "Smoke plan is missing."),
        s._experiment_checklist_item(
            "active_baseline_record",
            "Active baseline",
            bool(active_baseline_artifact),
            artifact_note or "Active baseline artifact is not registered.",
        ),
    ]


def _experiment_checklist_item(item: str, label: str, passed: bool, note: str) -> dict[str, str]:
    s = _service()
    return {
        "item": item,
        "label": label,
        "status": "pass" if passed else "needs_attention",
        "note": s._trim_text(note, max_length=1200),
    }


def _experiment_planning_gaps(
    *,
    latest_experiment: dict[str, Any] | None,
    hypothesis_candidates: list[dict[str, Any]],
    ready_hypotheses: list[dict[str, Any]],
    active_plan: dict[str, Any] | None,
) -> list[dict[str, str]]:
    s = _service()
    gaps: list[dict[str, str]] = []
    active_plan_validation = (
        active_plan.get("contractValidation")
        if isinstance((active_plan or {}).get("contractValidation"), dict)
        else {}
    )
    active_plan_readiness = (
        active_plan.get("readiness")
        if isinstance((active_plan or {}).get("readiness"), dict)
        else {}
    )
    active_plan_review_ready = bool(
        active_plan
        and active_plan_validation.get("valid") is True
        and active_plan_readiness.get("readyForPlanReview") is True
    )
    if not latest_experiment:
        gaps.append({"code": "missing_experiment_stage_round", "severity": "blocked", "message": "需要先启动实验规划轮次。"})
    if not hypothesis_candidates:
        gaps.append({"code": "missing_algorithm_hypotheses", "severity": "needs_evidence", "message": "还没有 algorithm_hypothesis 候选可转成实验。"})
    elif not ready_hypotheses:
        gaps.append(
            {
                "code": "incomplete_experiment_plan",
                "severity": "needs_attention",
                "message": "已有算法假设，但仍需完成假设审查并补齐 dataset、metric、baseline 与 smokePlan。",
            }
        )
    if latest_experiment and not active_plan:
        gaps.append({"code": "missing_experiment_plan_draft", "severity": "pending", "message": "实验轮次已启动，但还没有 draft plan 账本记录。"})
    if active_plan and not active_plan_review_ready and not any(
        item.get("code") in {"missing_algorithm_hypotheses", "incomplete_experiment_plan"}
        for item in gaps
    ):
        gaps.append(
            {
                "code": "experiment_design_not_review_ready",
                "severity": "needs_attention",
                "message": "实验计划草稿尚未通过合同校验与设计审查，不能进入基线或执行门禁。",
            }
        )
    if active_plan_review_ready and not bool((active_plan.get("baselineSelection") or {}).get("activeBaselineReady")):
        gaps.append({"code": "active_baseline_not_registered", "severity": "needs_attention", "message": "已有计划草稿，但 active baseline artifact 仍未登记，不能进入 full run。"})
    elif active_plan and bool((active_plan.get("readiness") or {}).get("readyForSmoke")) and not bool((active_plan.get("readiness") or {}).get("readyForFullRun")):
        active_smoke_result = s._active_experiment_smoke_evidence(active_plan)
        if active_smoke_result:
            gaps.append({"code": "smoke_result_not_passed", "severity": "needs_attention", "message": "smoke 结果已登记但尚未通过，full run 继续阻塞。"})
        else:
            gaps.append({"code": "smoke_result_not_recorded", "severity": "pending", "message": "active baseline artifact 已登记；等待显式 smoke run 或 smoke 结果登记。"})
    if active_plan and bool((active_plan.get("readiness") or {}).get("readyForFullRun")):
        active_full_run_result = active_plan.get("activeFullRunResult") if isinstance(active_plan.get("activeFullRunResult"), dict) else None
        if active_full_run_result and str(active_full_run_result.get("status") or "").strip().lower() != "passed":
            gaps.append({"code": "full_run_result_not_passed", "severity": "needs_attention", "message": "full-run 结果已登记但尚未通过，不能进入正式知识入库。"})
        elif not active_full_run_result:
            gaps.append({"code": "full_run_result_not_recorded", "severity": "pending", "message": "smoke 已通过；等待显式 full-run 结果登记。"})
        elif not isinstance(active_plan.get("knowledgeIngestion"), dict):
            gaps.append({"code": "experiment_result_not_submitted_to_knowledge", "severity": "pending", "message": "full-run 结果已通过；等待生成实验结果包并通知知识库管理员。"})
    return gaps


def _experiment_planning_readiness_reason(
    latest_experiment: dict[str, Any] | None,
    ready_hypotheses: list[dict[str, Any]],
    active_plan: dict[str, Any] | None,
) -> str:
    s = _service()
    if not latest_experiment:
        return "需要先启动实验规划轮次。"
    active_smoke_result = s._active_experiment_smoke_evidence(active_plan)
    active_smoke_status = s._trim_text((active_smoke_result or {}).get("status"), max_length=80).lower()
    knowledge_ingestion = active_plan.get("knowledgeIngestion") if isinstance((active_plan or {}).get("knowledgeIngestion"), dict) else None
    if active_plan and s._trim_text((knowledge_ingestion or {}).get("status"), max_length=80).lower() == "ingested":
        return "实验结论已完成正式知识入库，实验账本与知识证据已对齐。"
    if active_plan and knowledge_ingestion:
        return "实验结果包已进入知识库管理员入库请求链路；正式知识仍等待知识治理门禁。"
    active_full_run = active_plan.get("activeFullRunResult") if isinstance((active_plan or {}).get("activeFullRunResult"), dict) else None
    active_full_run_status = s._trim_text((active_full_run or {}).get("status"), max_length=80).lower()
    if active_plan and active_full_run_status == "passed":
        return "full-run evidence 已通过；可以生成实验结果包并通知知识库管理员。"
    if active_plan and active_full_run_status:
        return "full-run evidence 已登记但尚未通过；需要复核或修复后再进入知识入库。"
    if active_plan and bool((active_plan.get("readiness") or {}).get("readyForFullRun")):
        return "smoke evidence 已通过；可以进入显式 full-run 决策，但本接口不自动训练。"
    if active_plan and active_smoke_status:
        return "smoke result 已登记但尚未通过；需要复核、修订或重跑，full run 继续阻塞。"
    if active_plan and bool((active_plan.get("readiness") or {}).get("readyForSmoke")):
        return "active baseline artifact 已登记；可进入 smoke gate，但 full run 仍等待 smoke 结果。"
    if active_plan:
        validation = active_plan.get("contractValidation") if isinstance(active_plan.get("contractValidation"), dict) else {}
        readiness = active_plan.get("readiness") if isinstance(active_plan.get("readiness"), dict) else {}
        if readiness.get("readyForPlanReview") is not True:
            return "已有实验计划草稿，但缺少可审查的 algorithm_hypothesis；需先完成假设修订与选择。"
        if validation.get("valid") is not True:
            return "已有实验计划草稿，但实验合同仍不完整；需先补齐并通过设计审查。"
        return "已有实验计划草稿；下一步补 active baseline artifact 与 smoke 结果。"
    if ready_hypotheses:
        return "已有完整 algorithm_hypothesis，可生成实验计划草稿。"
    return "实验轮次已存在，但缺少完整 algorithm_hypothesis 候选。"


def _experiment_planning_next_actions(*, active_plan: dict[str, Any] | None, gaps: list[dict[str, str]]) -> list[str]:
    s = _service()
    gap_codes = {item.get("code") for item in gaps}
    knowledge_ingestion = (
        active_plan.get("knowledgeIngestion")
        if isinstance((active_plan or {}).get("knowledgeIngestion"), dict)
        else {}
    )
    if s._trim_text(knowledge_ingestion.get("status"), max_length=80).lower() == "ingested":
        return ["实验结论已完成正式知识入库；后续迭代应引用该 KnowledgeItem 与证据锚点。"]
    if active_plan and isinstance(active_plan.get("knowledgeIngestion"), dict):
        return ["等待知识库管理员复核实验结果入库包。", "在知识库管理员批准精炼知识项之前，原始日志保持在 RAG 之外。"]
    if "missing_experiment_stage_round" in gap_codes:
        return ["Start the experiment planning stage round.", "Keep training execution disabled until a plan is reviewed."]
    if (
        "missing_algorithm_hypotheses" in gap_codes
        or "incomplete_experiment_plan" in gap_codes
        or "experiment_design_not_review_ready" in gap_codes
    ):
        return ["Review upstream paper notes, mechanism mappings, and algorithm_hypothesis candidates.", "Repair candidate experimentPlan fields before drafting a plan."]
    if "active_baseline_not_registered" in gap_codes:
        return ["Review the draft plan checklist.", "Register an active baseline artifact before smoke or full-run execution."]
    if "smoke_result_not_recorded" in gap_codes:
        return ["Run or record a smoke result using the registered active baseline artifact.", "Keep full-run execution blocked until smoke evidence is reviewed."]
    if "smoke_result_not_passed" in gap_codes:
        return ["Review the recorded smoke evidence.", "Repair the candidate or record a passing smoke result before full-run execution."]
    if "full_run_result_not_recorded" in gap_codes:
        return ["Run or record a full-run result using the passed smoke evidence.", "Keep knowledge ingestion blocked until full-run evidence is recorded."]
    if "full_run_result_not_passed" in gap_codes:
        return ["Review the full-run evidence.", "Repair the experiment or record a passing full-run result before requesting knowledge ingestion."]
    if "experiment_result_not_submitted_to_knowledge" in gap_codes:
        return ["生成实验结果入库审核包。", "通知知识库管理员进行最终 Team Knowledge 入库审核。"]
    if active_plan:
        return ["Review the passed smoke evidence.", "Make a separate explicit decision before any full-run execution."]
    return ["Draft an experiment plan from ready algorithm hypotheses.", "Do not auto-run training."]


def _experiment_planning_boundaries() -> dict[str, bool | str]:
    return {
        "autoExecution": False,
        "writesFormalKnowledge": False,
        "writesRag": False,
        "writesOfficialGraph": False,
        "createsExperimentAttempt": False,
        "requiresUserDecision": True,
        "boundary": "experiment_planning_ledger_only_not_training_execution",
    }


def _experiment_plans(plan_store: dict[str, Any]) -> list[dict[str, Any]]:
    plans = [item for item in list(plan_store.get("plans") or []) if isinstance(item, dict)]
    return sorted(plans, key=lambda item: (str(item.get("updatedAt") or ""), str(item.get("planId") or "")))


def _active_experiment_plan(plan_store: dict[str, Any]) -> dict[str, Any] | None:
    s = _service()
    plans = s._experiment_plans(plan_store)
    active_plan_id = str(plan_store.get("activePlanId") or "")
    if active_plan_id:
        for plan in plans:
            if str(plan.get("planId") or "") == active_plan_id:
                return plan
    return plans[-1] if plans else None


def _experiment_plan_store_path(team_id: str) -> Path:
    s = _service()
    return s._team_workflow_root(team_id) / "experiment_plans" / "index.json"
