"""Template-driven research loop orchestration service."""

from __future__ import annotations

import json
import re
import threading
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.infrastructure import developer_sandbox
from core.web.services import team_service
from core.web.services.runtime_scene_service import record_runtime_scene_event


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_VERSION = 1
STORE_KIND = "team_research_loop_store"
DEFAULT_TEMPLATE_ID = "algorithm_model_experiment"
DEFAULT_OWNER_AGENT_ID = "Research Coordination Agent"
MAX_LOOP_RECORDS = 80
MAX_EVIDENCE_RECORDS = 80
MAX_DECISION_RECORDS = 40
_SAFE_ID_FRAGMENT = re.compile(r"[^A-Za-z0-9_.-]+")
_LOCK = threading.RLock()


class ResearchLoopError(ValueError):
    """Raised when a Research Loop request is invalid."""


RESEARCH_LOOP_TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        "templateId": "algorithm_model_experiment",
        "templateKind": "algorithm_model",
        "label": "Algorithm model experiment",
        "labelZh": "算法模型验证",
        "description": "Use when the research question needs a model, baseline, dataset, and metric comparison.",
        "problemFits": ["algorithm_hypothesis", "model_ablation", "training_or_inference_change"],
        "requiredInputs": ["researchQuestion", "baseline", "dataset", "metric"],
        "requiredEvidenceTypes": ["baseline_artifact", "dataset_benchmark", "metric_report"],
        "decisionGates": ["baseline_comparable", "dataset_traceable", "metric_interpretable"],
        "defaultIterationActions": ["revise hypothesis", "tighten baseline", "run full result ledger manually"],
    },
    {
        "templateId": "simulation_experiment",
        "templateKind": "simulation",
        "label": "Simulation experiment",
        "labelZh": "仿真模拟验证",
        "description": "Use when the research question needs a controllable simulated environment or scenario.",
        "problemFits": ["simulated_environment", "agent_behavior", "mechanism_stress_test"],
        "requiredInputs": ["researchQuestion", "simulatorOrScenario", "metric"],
        "requiredEvidenceTypes": ["simulation_environment", "simulation_result", "metric_report"],
        "decisionGates": ["environment_reproducible", "scenario_matches_claim", "metric_interpretable"],
        "defaultIterationActions": ["adjust simulator assumptions", "add scenario sweep", "compare against baseline policy"],
    },
    {
        "templateId": "dataset_benchmark",
        "templateKind": "dataset",
        "label": "Dataset benchmark",
        "labelZh": "数据集基准验证",
        "description": "Use when the research question is best tested on a named dataset or benchmark split.",
        "problemFits": ["dataset_run", "benchmark_table", "leaderboard_like_eval"],
        "requiredInputs": ["researchQuestion", "dataset", "metric"],
        "requiredEvidenceTypes": ["dataset_snapshot", "benchmark_result", "metric_report"],
        "decisionGates": ["dataset_version_fixed", "evaluation_script_traceable", "metric_interpretable"],
        "defaultIterationActions": ["fix data split", "add ablation", "record full-run result manually"],
    },
    {
        "templateId": "environment_probe",
        "templateKind": "environment",
        "label": "Environment probe",
        "labelZh": "实验环境探针",
        "description": "Use when the first uncertainty is whether the experiment environment can be prepared.",
        "problemFits": ["dependency_setup", "hardware_or_runtime_check", "smoke_validation"],
        "requiredInputs": ["researchQuestion", "environmentTarget"],
        "requiredEvidenceTypes": ["environment_spec", "smoke_log"],
        "decisionGates": ["dependencies_listed", "smoke_result_recorded"],
        "defaultIterationActions": ["pin environment", "narrow smoke case", "switch to benchmark or simulation template"],
    },
    {
        "templateId": "deep_research_review",
        "templateKind": "research_review",
        "label": "Deep research review",
        "labelZh": "深度资料审查",
        "description": "Use when the next step is literature or project evidence synthesis before experiments.",
        "problemFits": ["literature_review", "project_reuse_review", "claim_triage"],
        "requiredInputs": ["researchQuestion", "sourceRefs"],
        "requiredEvidenceTypes": ["source_evidence", "review_matrix"],
        "decisionGates": ["source_traceable", "claims_separated_from_inference"],
        "defaultIterationActions": ["narrow research question", "promote to algorithm or simulation template"],
    },
    {
        "templateId": "paper_claim_audit",
        "templateKind": "claim_audit",
        "label": "Paper claim audit",
        "labelZh": "论文结论复核",
        "description": "Use when a paper claim must be checked against method, evidence, and replication notes.",
        "problemFits": ["paper_claim", "replication_check", "method_limit"],
        "requiredInputs": ["researchQuestion", "paperOrClaimRef"],
        "requiredEvidenceTypes": ["claim_trace", "replication_note"],
        "decisionGates": ["claim_has_page_anchor", "replication_boundary_explicit"],
        "defaultIterationActions": ["request stronger evidence", "map claim to experiment template"],
    },
)

_TEMPLATES_BY_ID = {template["templateId"]: template for template in RESEARCH_LOOP_TEMPLATES}
DECISION_STATUS_BY_VALUE = {
    "promote_to_iteration": "ready_for_iteration",
    "repair_and_repeat": "iteration_planned",
    "needs_more_evidence": "needs_more_evidence",
    "reject_or_archive": "rejected",
    "accept_for_writeup": "accepted_for_writeup",
}
EVIDENCE_STATUSES = {"passed", "failed", "needs_review", "not_applicable"}


def list_research_loop_templates() -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "templates": [deepcopy(template) for template in RESEARCH_LOOP_TEMPLATES],
        "defaultTemplateId": DEFAULT_TEMPLATE_ID,
        "boundaries": _research_loop_boundaries(),
    }


def get_research_loop_status(team_id: str) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    team = team_service.get_team(normalized_team_id)
    with _LOCK:
        store = _load_research_loop_store(normalized_team_id)
        loops = [_refresh_loop_readiness(loop) for loop in _loop_records(store)]
        store["loops"] = loops
        active_loop = _find_loop(store, str(store.get("activeLoopId") or ""))
        if active_loop is None and loops:
            active_loop = loops[-1]
            store["activeLoopId"] = active_loop["loopId"]
        store["updatedAt"] = utc_now_iso()
        _write_json(_research_loop_store_path(normalized_team_id), store)
    return _status_payload(normalized_team_id, team, store, active_loop=active_loop)


def create_research_loop(team_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    team = team_service.get_team(normalized_team_id)
    request_payload = payload if isinstance(payload, dict) else {}
    template_id = _safe_token(request_payload.get("templateId"), default=DEFAULT_TEMPLATE_ID, max_length=96)
    template = _template_by_id(template_id)
    research_question = _trim_text(request_payload.get("researchQuestion"), max_length=2000)
    if not research_question:
        raise ResearchLoopError("Research question is required.")
    now = utc_now_iso()
    created_by_agent = _trim_text(request_payload.get("createdByAgent"), max_length=160) or DEFAULT_OWNER_AGENT_ID
    loop = {
        "schemaVersion": SCHEMA_VERSION,
        "loopId": _new_record_id("research-loop"),
        "teamId": normalized_team_id,
        "templateId": template["templateId"],
        "templateKind": template["templateKind"],
        "templateSnapshot": deepcopy(template),
        "title": _trim_text(request_payload.get("title"), max_length=240) or template["labelZh"],
        "researchQuestion": research_question,
        "status": "planned",
        "createdAt": now,
        "updatedAt": now,
        "createdByAgent": created_by_agent,
        "linkedExperiment": {
            "stageRoundId": _trim_text(request_payload.get("stageRoundId"), max_length=128),
            "planId": _trim_text(request_payload.get("planId"), max_length=128),
            "targetRef": _trim_text(request_payload.get("targetRef"), max_length=500),
            "candidateIds": _trim_list(request_payload.get("candidateIds"), max_items=24, max_length=128),
        },
        "inputs": {
            "inputRefs": _trim_list(request_payload.get("inputRefs"), max_items=80, max_length=500),
            "sourceRefs": _normalize_refs(request_payload.get("sourceRefs"), max_items=24),
            "datasetRefs": _trim_list(request_payload.get("datasetRefs"), max_items=24, max_length=500),
            "environmentRefs": _trim_list(request_payload.get("environmentRefs"), max_items=24, max_length=500),
            "constraints": _trim_text(request_payload.get("constraints"), max_length=4000),
            "metadata": _normalize_metadata(request_payload.get("metadata")),
        },
        "executionPolicy": _manual_execution_policy(),
        "evidenceRecords": [],
        "decisions": [],
        "iterationProposals": [],
        "readiness": {},
        "boundaries": _research_loop_boundaries(),
    }
    _refresh_loop_readiness(loop)
    with _LOCK:
        store = _load_research_loop_store(normalized_team_id)
        loops = _loop_records(store)
        loops.append(loop)
        store["loops"] = loops[-MAX_LOOP_RECORDS:]
        store["activeLoopId"] = loop["loopId"]
        store["updatedAt"] = now
        _write_json(_research_loop_store_path(normalized_team_id), store)
    _record_research_loop_event(
        "research_loop.created",
        normalized_team_id,
        fields={
            "loopId": loop["loopId"],
            "templateId": loop["templateId"],
            "planId": loop["linkedExperiment"]["planId"],
            "stageRoundId": loop["linkedExperiment"]["stageRoundId"],
            "createdByAgent": created_by_agent,
            "autoExecution": False,
        },
    )
    return {
        "loop": loop,
        "status": _status_payload(normalized_team_id, team, store, active_loop=loop),
        "boundaries": _research_loop_boundaries(),
    }


def record_research_loop_evidence(team_id: str, loop_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    normalized_loop_id = _normalize_required_id(loop_id, "Research loop id is required.")
    team = team_service.get_team(normalized_team_id)
    request_payload = payload if isinstance(payload, dict) else {}
    evidence_type = _safe_token(request_payload.get("evidenceType"), default="", max_length=96)
    if not evidence_type:
        raise ResearchLoopError("Evidence type is required.")
    status_value = _safe_token(request_payload.get("status"), default="needs_review", max_length=64)
    if status_value not in EVIDENCE_STATUSES:
        raise ResearchLoopError(f"Unsupported evidence status: {status_value}.")
    if not _has_evidence_payload(request_payload):
        raise ResearchLoopError("Evidence requires at least summary, metric, artifact, dataset, environment, log, or command preview.")
    now = utc_now_iso()
    recorded_by_agent = _trim_text(request_payload.get("recordedByAgent"), max_length=160) or DEFAULT_OWNER_AGENT_ID
    evidence = {
        "evidenceId": _new_record_id("loop-evidence"),
        "evidenceType": evidence_type,
        "status": status_value,
        "summary": _trim_text(request_payload.get("summary"), max_length=4000),
        "metricName": _trim_text(request_payload.get("metricName"), max_length=500),
        "metricValue": _trim_text(request_payload.get("metricValue"), max_length=240),
        "baselineMetricValue": _trim_text(request_payload.get("baselineMetricValue"), max_length=240),
        "delta": _trim_text(request_payload.get("delta"), max_length=240),
        "artifactRefs": _normalize_refs(request_payload.get("artifactRefs"), max_items=24),
        "sourceRefs": _normalize_refs(request_payload.get("sourceRefs"), max_items=24),
        "datasetRefs": _trim_list(request_payload.get("datasetRefs"), max_items=24, max_length=500),
        "environmentRefs": _trim_list(request_payload.get("environmentRefs"), max_items=24, max_length=500),
        "logRefs": _trim_list(request_payload.get("logRefs"), max_items=24, max_length=500),
        "commandPreview": _trim_text(request_payload.get("commandPreview"), max_length=2000),
        "recordedAt": now,
        "recordedByAgent": recorded_by_agent,
        "metadata": _normalize_metadata(request_payload.get("metadata")),
        "executionBoundary": _manual_execution_policy(),
    }
    with _LOCK:
        store = _load_research_loop_store(normalized_team_id)
        loop = _find_loop(store, normalized_loop_id)
        if loop is None:
            raise ResearchLoopError("Research loop not found.")
        records = [item for item in loop.get("evidenceRecords") or [] if isinstance(item, dict)]
        records.append(evidence)
        loop["evidenceRecords"] = records[-MAX_EVIDENCE_RECORDS:]
        loop["updatedAt"] = now
        loop["status"] = "evidence_recorded"
        _refresh_loop_readiness(loop)
        store["activeLoopId"] = loop["loopId"]
        store["updatedAt"] = now
        _write_json(_research_loop_store_path(normalized_team_id), store)
    _record_research_loop_event(
        "research_loop.evidence_recorded",
        normalized_team_id,
        fields={
            "loopId": loop["loopId"],
            "templateId": loop["templateId"],
            "evidenceId": evidence["evidenceId"],
            "evidenceType": evidence_type,
            "status": status_value,
            "readyForDecision": bool((loop.get("readiness") or {}).get("readyForDecision")),
            "recordedByAgent": recorded_by_agent,
            "autoExecution": False,
        },
    )
    return {
        "evidence": evidence,
        "loop": loop,
        "status": _status_payload(normalized_team_id, team, store, active_loop=loop),
        "boundaries": _research_loop_boundaries(),
    }


def record_research_loop_decision(team_id: str, loop_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    normalized_loop_id = _normalize_required_id(loop_id, "Research loop id is required.")
    team = team_service.get_team(normalized_team_id)
    request_payload = payload if isinstance(payload, dict) else {}
    decision_value = _safe_token(request_payload.get("decision"), default="", max_length=96)
    if decision_value not in DECISION_STATUS_BY_VALUE:
        raise ResearchLoopError(f"Unsupported research loop decision: {decision_value}.")
    rationale = _trim_text(request_payload.get("rationale"), max_length=4000)
    if not rationale:
        raise ResearchLoopError("Decision rationale is required.")
    now = utc_now_iso()
    decided_by_agent = _trim_text(request_payload.get("decidedByAgent"), max_length=160) or DEFAULT_OWNER_AGENT_ID
    with _LOCK:
        store = _load_research_loop_store(normalized_team_id)
        loop = _find_loop(store, normalized_loop_id)
        if loop is None:
            raise ResearchLoopError("Research loop not found.")
        _refresh_loop_readiness(loop)
        readiness = loop.get("readiness") if isinstance(loop.get("readiness"), dict) else {}
        if decision_value in {"promote_to_iteration", "accept_for_writeup"} and not readiness.get("readyForDecision"):
            raise ResearchLoopError("Required evidence is incomplete; cannot promote this loop yet.")
        decision = {
            "decisionId": _new_record_id("loop-decision"),
            "decision": decision_value,
            "statusAfterDecision": DECISION_STATUS_BY_VALUE[decision_value],
            "rationale": rationale,
            "createdAt": now,
            "decidedByAgent": decided_by_agent,
            "metadata": _normalize_metadata(request_payload.get("metadata")),
            "executionBoundary": _manual_execution_policy(),
        }
        iteration_proposal = _iteration_proposal_for_decision(loop, decision, request_payload, decided_by_agent=decided_by_agent, created_at=now)
        if iteration_proposal:
            decision["iterationProposalId"] = iteration_proposal["proposalId"]
            proposals = [item for item in loop.get("iterationProposals") or [] if isinstance(item, dict)]
            proposals.append(iteration_proposal)
            loop["iterationProposals"] = proposals[-MAX_DECISION_RECORDS:]
        decisions = [item for item in loop.get("decisions") or [] if isinstance(item, dict)]
        decisions.append(decision)
        loop["decisions"] = decisions[-MAX_DECISION_RECORDS:]
        loop["status"] = decision["statusAfterDecision"]
        loop["updatedAt"] = now
        _refresh_loop_readiness(loop)
        store["activeLoopId"] = loop["loopId"]
        store["updatedAt"] = now
        _write_json(_research_loop_store_path(normalized_team_id), store)
    _record_research_loop_event(
        "research_loop.decision_recorded",
        normalized_team_id,
        fields={
            "loopId": loop["loopId"],
            "templateId": loop["templateId"],
            "decisionId": decision["decisionId"],
            "decision": decision_value,
            "statusAfterDecision": loop["status"],
            "iterationProposalId": str(decision.get("iterationProposalId") or ""),
            "decidedByAgent": decided_by_agent,
            "autoExecution": False,
        },
    )
    return {
        "decision": decision,
        "iterationProposal": iteration_proposal,
        "loop": loop,
        "status": _status_payload(normalized_team_id, team, store, active_loop=loop),
        "boundaries": _research_loop_boundaries(),
    }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _status_payload(team_id: str, team: dict[str, Any], store: dict[str, Any], *, active_loop: dict[str, Any] | None) -> dict[str, Any]:
    loops = [_loop_summary(loop) for loop in _loop_records(store)]
    summary = {
        "totalLoopCount": len(loops),
        "readyForDecisionCount": sum(1 for loop in loops if loop.get("readyForDecision")),
        "readyForIterationCount": sum(1 for loop in loops if loop.get("status") == "ready_for_iteration"),
        "blockedLoopCount": sum(1 for loop in loops if loop.get("status") in {"evidence_incomplete", "needs_more_evidence"}),
    }
    return {
        "schemaVersion": SCHEMA_VERSION,
        "storeKind": STORE_KIND,
        "teamId": team_id,
        "team": {"teamId": team.get("teamId", team_id), "name": team.get("name", "")},
        "activeLoopId": store.get("activeLoopId", ""),
        "activeLoop": active_loop,
        "loops": loops,
        "summary": summary,
        "templates": [deepcopy(template) for template in RESEARCH_LOOP_TEMPLATES],
        "storagePath": _relative_path(_research_loop_store_path(team_id)),
        "nextActions": _research_loop_next_actions(active_loop),
        "boundaries": _research_loop_boundaries(),
    }


def _loop_summary(loop: dict[str, Any]) -> dict[str, Any]:
    readiness = loop.get("readiness") if isinstance(loop.get("readiness"), dict) else {}
    return {
        "loopId": loop.get("loopId", ""),
        "templateId": loop.get("templateId", ""),
        "templateKind": loop.get("templateKind", ""),
        "title": loop.get("title", ""),
        "researchQuestion": loop.get("researchQuestion", ""),
        "status": loop.get("status", ""),
        "updatedAt": loop.get("updatedAt", ""),
        "createdByAgent": loop.get("createdByAgent", ""),
        "evidenceRecordCount": len([item for item in loop.get("evidenceRecords") or [] if isinstance(item, dict)]),
        "decisionCount": len([item for item in loop.get("decisions") or [] if isinstance(item, dict)]),
        "readyForDecision": bool(readiness.get("readyForDecision")),
        "readyForIteration": bool(readiness.get("readyForIteration")),
        "missingEvidenceTypes": list(readiness.get("missingEvidenceTypes") or []),
    }


def _refresh_loop_readiness(loop: dict[str, Any]) -> dict[str, Any]:
    template = loop.get("templateSnapshot") if isinstance(loop.get("templateSnapshot"), dict) else _template_by_id(str(loop.get("templateId") or DEFAULT_TEMPLATE_ID))
    required = [str(item) for item in template.get("requiredEvidenceTypes") or [] if str(item).strip()]
    records = [item for item in loop.get("evidenceRecords") or [] if isinstance(item, dict)]
    present = {str(item.get("evidenceType") or "") for item in records if str(item.get("status") or "") != "not_applicable"}
    missing = [item for item in required if item not in present]
    latest_decision = _latest_decision(loop)
    blockers = []
    if not records:
        blockers.append("record_required_evidence")
    blockers.extend(f"missing_{item}" for item in missing)
    ready_for_decision = bool(records) and not missing
    ready_for_iteration = bool(latest_decision and latest_decision.get("decision") in {"promote_to_iteration", "repair_and_repeat"})
    loop["readiness"] = {
        "requiredEvidenceTypes": required,
        "presentEvidenceTypes": sorted(present),
        "missingEvidenceTypes": missing,
        "evidenceRecordCount": len(records),
        "readyForDecision": ready_for_decision,
        "readyForIteration": ready_for_iteration,
        "blockers": blockers,
    }
    if not latest_decision:
        if not records:
            loop["status"] = "planned"
        elif ready_for_decision:
            loop["status"] = "ready_for_decision"
        else:
            loop["status"] = "evidence_incomplete"
    loop["boundaries"] = _research_loop_boundaries()
    loop["executionPolicy"] = _manual_execution_policy()
    return loop


def _iteration_proposal_for_decision(
    loop: dict[str, Any],
    decision: dict[str, Any],
    payload: dict[str, Any],
    *,
    decided_by_agent: str,
    created_at: str,
) -> dict[str, Any] | None:
    if decision["decision"] not in {"promote_to_iteration", "repair_and_repeat", "needs_more_evidence"}:
        return None
    next_template_id = _safe_token(payload.get("nextTemplateId"), default=str(loop.get("templateId") or DEFAULT_TEMPLATE_ID), max_length=96)
    next_template = _TEMPLATES_BY_ID.get(next_template_id) or _TEMPLATES_BY_ID[DEFAULT_TEMPLATE_ID]
    requested_actions = _trim_list(payload.get("nextActions"), max_items=24, max_length=500)
    next_actions = requested_actions or list(next_template.get("defaultIterationActions") or [])
    return {
        "proposalId": _new_record_id("iteration-proposal"),
        "loopId": loop.get("loopId", ""),
        "sourceDecisionId": decision["decisionId"],
        "status": "proposed",
        "nextTemplateId": next_template["templateId"],
        "nextTemplateKind": next_template["templateKind"],
        "nextActions": next_actions,
        "createdAt": created_at,
        "createdByAgent": decided_by_agent,
        "executionPolicy": _manual_execution_policy(),
    }


def _latest_decision(loop: dict[str, Any]) -> dict[str, Any] | None:
    decisions = [item for item in loop.get("decisions") or [] if isinstance(item, dict)]
    return decisions[-1] if decisions else None


def _research_loop_next_actions(active_loop: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not active_loop:
        return [{"action": "create_research_loop", "label": "Create a template-driven research loop", "requiresUserDecision": True}]
    readiness = active_loop.get("readiness") if isinstance(active_loop.get("readiness"), dict) else {}
    if not readiness.get("readyForDecision"):
        return [
            {
                "action": "record_evidence",
                "label": "Record missing evidence manually",
                "missingEvidenceTypes": list(readiness.get("missingEvidenceTypes") or []),
                "requiresUserDecision": True,
            }
        ]
    return [
        {
            "action": "record_decision",
            "label": "Record review decision and optional iteration proposal",
            "requiresUserDecision": True,
        }
    ]


def _has_evidence_payload(payload: dict[str, Any]) -> bool:
    text_fields = ("summary", "metricName", "metricValue", "baselineMetricValue", "delta", "commandPreview")
    if any(_trim_text(payload.get(field), max_length=32) for field in text_fields):
        return True
    list_fields = ("artifactRefs", "sourceRefs", "datasetRefs", "environmentRefs", "logRefs")
    return any(bool(payload.get(field)) for field in list_fields)


def _template_by_id(template_id: str) -> dict[str, Any]:
    template = _TEMPLATES_BY_ID.get(template_id)
    if template is None:
        raise ResearchLoopError(f"Unsupported research loop template: {template_id}.")
    return deepcopy(template)


def _research_loop_boundaries() -> dict[str, Any]:
    return {
        "executionMode": "manual_record_and_command_preview",
        "autoExecution": False,
        "externalExecution": False,
        "sandboxRunner": False,
        "trainingRunner": False,
        "writesExperimentResult": False,
        "writesFormalTeamKnowledge": False,
        "writesFormalRag": False,
        "writesOfficialGraph": False,
        "requiresUserDecision": True,
    }


def _manual_execution_policy() -> dict[str, Any]:
    return {
        "mode": "manual_record",
        "commandPreviewOnly": True,
        "autoExecution": False,
        "externalExecution": False,
        "sandboxRunner": False,
        "requiresUserDecision": True,
    }


def _load_research_loop_store(team_id: str) -> dict[str, Any]:
    path = _research_loop_store_path(team_id)
    store = _read_json(path)
    if not store:
        now = utc_now_iso()
        return {
            "schemaVersion": SCHEMA_VERSION,
            "storeKind": STORE_KIND,
            "teamId": team_id,
            "activeLoopId": "",
            "loops": [],
            "createdAt": now,
            "updatedAt": now,
        }
    store.setdefault("schemaVersion", SCHEMA_VERSION)
    store.setdefault("storeKind", STORE_KIND)
    store.setdefault("teamId", team_id)
    store.setdefault("activeLoopId", "")
    store["loops"] = _loop_records(store)
    store.setdefault("createdAt", store.get("updatedAt") or utc_now_iso())
    store.setdefault("updatedAt", store.get("createdAt") or utc_now_iso())
    return store


def _loop_records(store: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in list(store.get("loops") or []) if isinstance(item, dict)]


def _find_loop(store: dict[str, Any], loop_id: str) -> dict[str, Any] | None:
    for loop in _loop_records(store):
        if str(loop.get("loopId") or "") == loop_id:
            return loop
    return None


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _research_loop_store_path(team_id: str) -> Path:
    return _team_workspace_root(team_id) / "research_loops" / "index.json"


def _team_workspace_root(team_id: str) -> Path:
    return developer_sandbox.seeded_sandbox_workspace_path(
        _project_root(),
        "teams",
        _safe_token(team_id, default="team", max_length=96),
    )


def _project_root() -> Path:
    root = Path(PROJECT_ROOT).resolve()
    return root.parent if root.name.lower() == "workspace" else root


def _relative_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(_project_root())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _new_record_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"


def _normalize_required_id(value: Any, message: str) -> str:
    normalized = _safe_token(value, default="", max_length=128)
    if not normalized:
        raise ResearchLoopError(message)
    return normalized


def _safe_token(value: Any, *, default: str, max_length: int) -> str:
    text = str(value or "").strip()
    if not text:
        return default
    text = _SAFE_ID_FRAGMENT.sub("-", text).strip(".-_")
    return (text or default)[:max_length]


def _trim_text(value: Any, *, max_length: int) -> str:
    return str(value or "").strip()[:max_length]


def _trim_list(value: Any, *, max_items: int, max_length: int) -> list[str]:
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list):
        items = value
    else:
        return []
    normalized = []
    for item in items:
        text = _trim_text(item, max_length=max_length)
        if text:
            normalized.append(text)
        if len(normalized) >= max_items:
            break
    return normalized


def _normalize_refs(value: Any, *, max_items: int) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        items = [value]
    elif isinstance(value, list):
        items = value
    else:
        return []
    refs: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict):
            ref = {str(key)[:80]: _normalize_metadata_value(val) for key, val in item.items()}
        else:
            text = _trim_text(item, max_length=500)
            ref = {"ref": text} if text else {}
        if ref:
            refs.append(ref)
        if len(refs) >= max_items:
            break
    return refs


def _normalize_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {str(key)[:80]: _normalize_metadata_value(item) for key, item in list(value.items())[:40]}


def _normalize_metadata_value(value: Any) -> Any:
    if isinstance(value, str):
        return _trim_text(value, max_length=1000)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_normalize_metadata_value(item) for item in value[:40]]
    if isinstance(value, dict):
        return _normalize_metadata(value)
    return _trim_text(value, max_length=1000)


def _record_research_loop_event(event_code: str, team_id: str, *, fields: dict[str, Any]) -> None:
    try:
        record_runtime_scene_event(
            "research_loop",
            "workflow",
            event_code,
            message=event_code,
            fields={"teamId": team_id, **fields},
        )
    except Exception:
        return
