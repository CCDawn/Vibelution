"""Canonical experiment-method contract and deterministic adapter discovery.

This module is intentionally independent from the web layer.  It owns the
generic research experiment vocabulary; Challenge Cup and predictive-coding
details belong in research profiles and fixtures, not in these registries.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


SCHEMA_VERSION = 2

RESEARCH_MODES = (
    "hypothesis_and_plan",
    "experiment_feedback",
    "full_research_loop",
)
EXPERIMENT_PURPOSES = (
    "feasibility",
    "baseline_comparison",
    "falsification",
    "ablation",
    "replication",
    "robustness",
)

_RESEARCH_MODE_DESCRIPTORS: tuple[dict[str, str], ...] = (
    {"modeId": "hypothesis_and_plan", "labelZh": "A 假设与计划", "labelEn": "A Hypothesis and plan"},
    {"modeId": "experiment_feedback", "labelZh": "B 实验与反馈", "labelEn": "B Experiment and feedback"},
    {"modeId": "full_research_loop", "labelZh": "A+B 完整闭环", "labelEn": "A+B Full research loop"},
)

_PURPOSE_DESCRIPTORS: tuple[dict[str, str], ...] = (
    {"purposeId": "feasibility", "labelZh": "可行性验证", "labelEn": "Feasibility"},
    {"purposeId": "baseline_comparison", "labelZh": "基线比较", "labelEn": "Baseline comparison"},
    {"purposeId": "falsification", "labelZh": "假设证伪", "labelEn": "Falsification"},
    {"purposeId": "ablation", "labelZh": "消融分析", "labelEn": "Ablation"},
    {"purposeId": "replication", "labelZh": "复现实验", "labelEn": "Replication"},
    {"purposeId": "robustness", "labelZh": "稳健性验证", "labelEn": "Robustness"},
)

CONTRACT_STATUSES = {
    "draft",
    "validating",
    "needs_input",
    "adapter_unavailable",
    "ready_for_prepare",
    "prepared",
    "smoke_running",
    "smoke_review",
    "ready_for_full_run",
    "full_run_running",
    "result_review",
    "needs_revision",
    "rejected",
    "iteration_proposed",
    "superseded",
    "archived",
}

_METHODS: tuple[dict[str, Any], ...] = (
    {
        "methodId": "model_training_inference",
        "labelZh": "模型训练/推理",
        "labelEn": "Model training / inference",
        "requiredConfigFields": ["dataset", "model", "baseline", "seeds", "budget", "smokePlan"],
    },
    {
        "methodId": "dataset_analysis_benchmark",
        "labelZh": "数据分析/基准",
        "labelEn": "Dataset analysis / benchmark",
        "requiredConfigFields": ["sources", "dataSchema", "transform", "split"],
    },
    {
        "methodId": "numerical_simulation",
        "labelZh": "数值仿真",
        "labelEn": "Numerical simulation",
        "requiredConfigFields": ["simulator", "scenario", "parameters", "replicates"],
    },
    {
        "methodId": "statistical_causal_test",
        "labelZh": "统计/因果检验",
        "labelEn": "Statistical / causal test",
        "requiredConfigFields": [
            "nullHypothesis",
            "alternativeHypothesis",
            "sample",
            "test",
            "alpha",
            "effectMeasure",
            "confounders",
        ],
    },
    {
        "methodId": "theoretical_symbolic_validation",
        "labelZh": "理论/公式验证",
        "labelEn": "Theoretical / symbolic validation",
        "requiredConfigFields": ["assumptions", "derivationTarget", "boundaryConditions", "counterexamplePlan"],
    },
    {
        "methodId": "external_instrument_experiment",
        "labelZh": "仪器或外部实验",
        "labelEn": "Instrument or external experiment",
        "requiredConfigFields": [
            "protocol",
            "instrumentOrFacility",
            "samplingPlan",
            "approvalStatus",
            "operator",
            "resultImportContract",
        ],
    },
)

_METHODS_BY_ID = {item["methodId"]: item for item in _METHODS}

# These are deliberately advertised as smoke-only.  They must never satisfy a
# formal full-run request or make the UI claim that a real experiment runner is
# available.
_ADAPTERS: tuple[dict[str, Any], ...] = (
    {
        "adapterId": "fashion_mnist_predictive_coding_multi_seed",
        "adapterVersion": "1.0.0",
        "method": "model_training_inference",
        "executionMode": "local_process",
        "capabilities": ["validate", "prepare", "smoke", "full_run", "collect"],
        "availability": "available",
        "unavailableReason": "Requires an explicit local CPU environment, existing FashionMNIST data, and a multi-seed run configuration.",
        "formalResult": True,
        "requiresExplicitSelection": True,
        "priority": 110,
    },
    {
        "adapterId": "synthetic_classification_baseline_vs_variant",
        "adapterVersion": "1.0.0",
        "method": "model_training_inference",
        "executionMode": "local_process",
        "capabilities": ["validate", "smoke", "collect"],
        "availability": "available",
        "unavailableReason": "",
        "formalResult": False,
        "priority": 100,
    },
    {
        "adapterId": "predictive_coding_reconstruction_proxy",
        "adapterVersion": "1.0.0",
        "method": "model_training_inference",
        "executionMode": "local_process",
        "capabilities": ["validate", "smoke", "collect"],
        "availability": "available",
        "unavailableReason": "Proxy-only smoke adapter; not formal predictive-coding evidence.",
        "formalResult": False,
        "priority": 90,
    },
)

_ADAPTERS_BY_ID = {item["adapterId"]: item for item in _ADAPTERS}


class ExperimentContractError(ValueError):
    """Raised when an experiment plan violates the generic method contract."""


def list_experiment_methods() -> list[dict[str, Any]]:
    return [deepcopy(item) for item in _METHODS]


def list_research_modes() -> list[dict[str, str]]:
    return [deepcopy(item) for item in _RESEARCH_MODE_DESCRIPTORS]


def list_experiment_purposes() -> list[dict[str, str]]:
    return [deepcopy(item) for item in _PURPOSE_DESCRIPTORS]


def list_experiment_adapters() -> list[dict[str, Any]]:
    return [deepcopy(item) for item in _ADAPTERS]


def build_experiment_contract(
    *,
    plan_id: str,
    team_id: str,
    research_question: str,
    payload: dict[str, Any] | None,
    legacy_plan: dict[str, Any] | None,
    hypothesis_refs: list[str] | None = None,
    evidence_refs: list[str] | None = None,
) -> dict[str, Any]:
    request = payload if isinstance(payload, dict) else {}
    legacy = legacy_plan if isinstance(legacy_plan, dict) else {}
    method_id = _text(request.get("experimentMethod")) or "model_training_inference"
    research_mode = _text(request.get("researchMode")) or "full_research_loop"
    purpose = _normalize_purpose(request.get("experimentPurpose") or request.get("purpose"), method_id)
    method_config = _method_config(method_id, request.get("methodConfig"), legacy)
    metric_contract = _metric_contract(request.get("metricContract"), legacy)
    adapter_selection = resolve_adapter_selection(
        method_id,
        research_mode,
        requested_adapter_id=_text(request.get("requestedAdapterId")),
    )
    contract: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "planId": _text(plan_id),
        "revision": _positive_int(request.get("revision"), default=1),
        "teamId": _text(team_id),
        "researchProfileId": _text(request.get("researchProfileId")) or "generic-research",
        "researchMode": research_mode,
        "purpose": purpose,
        "experimentMethod": method_id,
        "adapterSelection": adapter_selection,
        "researchQuestion": _text(research_question),
        "objective": _text(request.get("objective")),
        "hypothesisRefs": _unique_text(hypothesis_refs),
        "evidenceRefs": _unique_text(evidence_refs),
        "constraints": _unique_text(request.get("constraints")),
        "methodConfig": method_config,
        "metricContract": metric_contract,
        "decisionContract": _decision_contract(request.get("decisionContract")),
        "artifactContract": _artifact_contract(request.get("artifactContract")),
        "reproducibilityContract": _reproducibility_contract(
            request.get("reproducibilityContract"),
            method_config,
        ),
        "iterationContract": _iteration_contract(request.get("iterationContract")),
        "supersedesPlanId": _text(request.get("supersedesPlanId")),
        "status": _text(request.get("status")) or "draft",
    }
    recommendation = request.get("recommendation")
    if isinstance(recommendation, dict) and recommendation:
        contract["recommendation"] = deepcopy(recommendation)
    return contract


def resolve_adapter_selection(
    method_id: str,
    research_mode: str,
    *,
    requested_adapter_id: str = "",
) -> dict[str, Any]:
    if research_mode == "hypothesis_and_plan" and not requested_adapter_id:
        return _unresolved_adapter("", "Execution Adapter is not required until experiment-feedback execution is selected.")
    required = _required_adapter_capabilities(research_mode)
    candidates = [
        item
        for item in _ADAPTERS
        if item.get("method") == method_id and not item.get("requiresExplicitSelection")
    ]
    requested = _ADAPTERS_BY_ID.get(requested_adapter_id) if requested_adapter_id else None
    if requested_adapter_id:
        if requested is None:
            return _unresolved_adapter(requested_adapter_id, f"Unknown Adapter: {requested_adapter_id}.")
        if requested.get("method") != method_id:
            return _unresolved_adapter(requested_adapter_id, "Requested Adapter does not support the selected experiment method.")
        candidates = [requested]

    available = []
    missing_by_adapter: dict[str, list[str]] = {}
    for descriptor in candidates:
        if descriptor.get("availability") != "available":
            continue
        missing = sorted(required - set(descriptor.get("capabilities") or []))
        if missing:
            missing_by_adapter[str(descriptor.get("adapterId") or "")] = missing
            continue
        available.append(descriptor)
    if available:
        resolved = sorted(available, key=lambda item: (-int(item.get("priority") or 0), str(item.get("adapterId") or "")))[0]
        return {
            "requestedAdapterId": requested_adapter_id,
            "resolvedAdapterId": str(resolved.get("adapterId") or ""),
            "resolvedAdapterVersion": str(resolved.get("adapterVersion") or ""),
            "selectionSource": "user_override" if requested_adapter_id else "system_priority",
            "unavailableReason": "",
        }

    missing_capabilities = sorted({capability for values in missing_by_adapter.values() for capability in values})
    if missing_capabilities:
        reason = f"No Adapter satisfies required capabilities: {', '.join(missing_capabilities)}."
    else:
        reason = f"No available Adapter is registered for method {method_id}."
    return _unresolved_adapter(requested_adapter_id, reason)


def validate_experiment_contract(contract: dict[str, Any] | None) -> dict[str, Any]:
    value = contract if isinstance(contract, dict) else {}
    missing: list[str] = []
    errors: list[str] = []
    for field in (
        "planId",
        "teamId",
        "researchProfileId",
        "researchMode",
        "purpose",
        "experimentMethod",
        "adapterSelection",
        "researchQuestion",
        "methodConfig",
        "metricContract",
        "decisionContract",
        "artifactContract",
        "reproducibilityContract",
        "iterationContract",
        "status",
    ):
        if field not in value or value.get(field) in (None, ""):
            missing.append(field)
    if value.get("schemaVersion") != SCHEMA_VERSION:
        errors.append(f"schemaVersion must be {SCHEMA_VERSION}.")
    if value.get("researchMode") not in RESEARCH_MODES:
        errors.append(f"Unsupported researchMode: {value.get('researchMode')!r}.")
    method_id = _text(value.get("experimentMethod"))
    method = _METHODS_BY_ID.get(method_id)
    if method is None:
        errors.append(f"Unsupported experimentMethod: {method_id!r}.")
    purpose = value.get("purpose") if isinstance(value.get("purpose"), dict) else {}
    primary_purpose = purpose.get("primaryPurpose")
    if primary_purpose not in EXPERIMENT_PURPOSES:
        errors.append(f"Unsupported primary experiment purpose: {primary_purpose!r}.")
    for item in purpose.get("secondaryPurposes") or []:
        if item not in EXPERIMENT_PURPOSES:
            errors.append(f"Unsupported secondary experiment purpose: {item!r}.")
    method_config = value.get("methodConfig") if isinstance(value.get("methodConfig"), dict) else {}
    if method is not None:
        for field in method.get("requiredConfigFields") or []:
            field_value = method_config.get(field)
            allow_empty_list = method_id == "statistical_causal_test" and field == "confounders"
            if field not in method_config or field_value in (None, "") or (field_value == [] and not allow_empty_list):
                missing.append(f"methodConfig.{field}")
    metric_contract = value.get("metricContract") if isinstance(value.get("metricContract"), dict) else {}
    if not _text(metric_contract.get("primaryMetric")):
        missing.append("metricContract.primaryMetric")
    if not isinstance(metric_contract.get("metrics"), list) or not metric_contract.get("metrics"):
        missing.append("metricContract.metrics")
    decision_contract = value.get("decisionContract") if isinstance(value.get("decisionContract"), dict) else {}
    for field in ("successCriteria", "failureCriteria", "inconclusiveCriteria"):
        if not isinstance(decision_contract.get(field), list) or not decision_contract.get(field):
            missing.append(f"decisionContract.{field}")
    missing = sorted(set(missing))
    adapter_selection = value.get("adapterSelection") if isinstance(value.get("adapterSelection"), dict) else {}
    valid = not missing and not errors
    adapter_available = bool(adapter_selection.get("resolvedAdapterId"))
    return {
        "valid": valid,
        "errors": errors,
        "missingFields": missing,
        "methodId": method_id,
        "adapterAvailable": adapter_available,
        "readyForExecution": valid and adapter_available and value.get("researchMode") != "hypothesis_and_plan",
        "adapterUnavailableReason": _text(adapter_selection.get("unavailableReason")),
    }


def require_valid_experiment_contract(contract: dict[str, Any]) -> dict[str, Any]:
    validation = validate_experiment_contract(contract)
    if validation["valid"]:
        return validation
    details = [*validation["errors"], *[f"Missing required field: {item}." for item in validation["missingFields"]]]
    raise ExperimentContractError(" ".join(details) or "Experiment contract is invalid.")


def migrate_legacy_plan_record(plan: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(plan)
    existing = result.get("experimentContract")
    if isinstance(existing, dict) and existing.get("schemaVersion") == SCHEMA_VERSION:
        return result
    legacy_plan = result.get("experimentPlan") if isinstance(result.get("experimentPlan"), dict) else {}
    contract = build_experiment_contract(
        plan_id=_text(result.get("planId")),
        team_id=_text(result.get("teamId")),
        research_question=_text(result.get("goal")) or _text(result.get("topic")) or "Legacy experiment question requires review.",
        payload={
            "researchProfileId": _text(result.get("researchProfileId")) or "legacy-generic-research",
            "researchMode": _text(result.get("researchMode")) or "full_research_loop",
            "experimentPurpose": result.get("purpose") or {},
            "experimentMethod": _text(result.get("experimentMethod")) or "model_training_inference",
            "methodConfig": result.get("methodConfig") if isinstance(result.get("methodConfig"), dict) else {},
            "metricContract": result.get("metricContract") if isinstance(result.get("metricContract"), dict) else {},
            "revision": result.get("revision") or 1,
            "status": contract_status_from_legacy(result.get("status")),
        },
        legacy_plan=legacy_plan,
        hypothesis_refs=result.get("hypothesisCandidateIds") or [],
        evidence_refs=result.get("evidenceRefs") or [],
    )
    validation = validate_experiment_contract(contract)
    result["experimentContract"] = contract
    result["contractMigration"] = {
        "status": "projected_from_v1",
        "sourceSchemaVersion": _positive_int(result.get("schemaVersion"), default=1),
        "targetSchemaVersion": SCHEMA_VERSION,
        "missingFields": validation["missingFields"],
        "persistOnNextMutation": True,
    }
    result["compatibility"] = {
        "legacyExperimentPlanProjection": "read_only",
        "removalTrigger": "Teams experiment card and all API clients consume experimentContract schema v2",
    }
    return result


def project_plan_store_contracts(store: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(store)
    result["plans"] = [migrate_legacy_plan_record(item) for item in result.get("plans") or [] if isinstance(item, dict)]
    return result


def sync_plan_record_contract_status(plan: dict[str, Any]) -> None:
    contract = plan.get("experimentContract")
    if not isinstance(contract, dict):
        return
    contract["status"] = contract_status_from_legacy(plan.get("status"))
    plan["contractValidation"] = validate_experiment_contract(contract)


def contract_status_from_legacy(value: Any) -> str:
    status = _text(value).lower()
    if status in CONTRACT_STATUSES:
        return status
    if status == "baseline_ready":
        return "ready_for_prepare"
    if status == "smoke_passed":
        return "ready_for_full_run"
    if status in {"smoke_needs_review", "smoke_partial"}:
        return "smoke_review"
    if status.startswith("smoke_"):
        return "needs_revision"
    if status in {"full_run_passed", "full_run_needs_review"}:
        return "result_review"
    if status.startswith("full_run_"):
        return "needs_revision"
    if status.startswith("knowledge_steward_") or status == "ready_for_knowledge_ingestion":
        return "result_review"
    return "draft"


def _normalize_purpose(value: Any, method_id: str) -> dict[str, Any]:
    purpose = value if isinstance(value, dict) else {}
    default_by_method = {
        "model_training_inference": "baseline_comparison",
        "dataset_analysis_benchmark": "baseline_comparison",
        "numerical_simulation": "robustness",
        "statistical_causal_test": "falsification",
        "theoretical_symbolic_validation": "falsification",
        "external_instrument_experiment": "feasibility",
    }
    primary = _text(purpose.get("primaryPurpose")) or default_by_method.get(method_id, "feasibility")
    return {
        "primaryPurpose": primary,
        "secondaryPurposes": _unique_text(purpose.get("secondaryPurposes")),
    }


def _method_config(method_id: str, explicit: Any, legacy: dict[str, Any]) -> dict[str, Any]:
    config = deepcopy(explicit) if isinstance(explicit, dict) else {}
    if method_id == "model_training_inference":
        for field in ("dataset", "baseline", "smokePlan"):
            if not config.get(field) and legacy.get(field):
                config[field] = legacy[field]
    return config


def _metric_contract(value: Any, legacy: dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, dict) and value:
        return deepcopy(value)
    metric = _text(legacy.get("metric"))
    return {
        "primaryMetric": metric,
        "metrics": [{"name": metric, "direction": "descriptive"}] if metric else [],
    }


def _decision_contract(value: Any) -> dict[str, Any]:
    if isinstance(value, dict) and value:
        return deepcopy(value)
    return {
        "successCriteria": [],
        "failureCriteria": [],
        "inconclusiveCriteria": [],
    }


def _artifact_contract(value: Any) -> dict[str, Any]:
    if isinstance(value, dict) and value:
        return deepcopy(value)
    return {
        "requiredArtifacts": ["resolved configuration", "bounded result ledger"],
        "requiredLogTypes": ["environment", "execution", "decision"],
    }


def _reproducibility_contract(value: Any, method_config: dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, dict) and value:
        return deepcopy(value)
    seeds = method_config.get("seeds") if isinstance(method_config.get("seeds"), list) else []
    return {
        "seeds": list(seeds),
        "captureEnvironment": True,
        "captureInputHash": True,
        "captureConfigHash": True,
        "reproductionCommand": "",
    }


def _iteration_contract(value: Any) -> dict[str, Any]:
    if isinstance(value, dict) and value:
        return deepcopy(value)
    return {
        "requiresResultConclusion": True,
        "requiresFeedbackSignals": True,
        "requiresPlanDiff": True,
    }


def _required_adapter_capabilities(research_mode: str) -> set[str]:
    if research_mode == "hypothesis_and_plan":
        return {"validate"}
    return {"validate", "prepare", "smoke", "full_run", "collect"}


def _unresolved_adapter(requested_adapter_id: str, reason: str) -> dict[str, str]:
    return {
        "requestedAdapterId": requested_adapter_id,
        "resolvedAdapterId": "",
        "resolvedAdapterVersion": "",
        "selectionSource": "unresolved",
        "unavailableReason": reason,
    }


def _text(value: Any) -> str:
    return str(value or "").strip()


def _unique_text(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    result: list[str] = []
    for item in value:
        normalized = _text(item)
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def _positive_int(value: Any, *, default: int) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return default
    return normalized if normalized > 0 else default
