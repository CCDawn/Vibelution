"""Team workflow orchestration and candidate-store service."""

from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config.public_config import build_effective_config, load_public_config
from core.llm import LLMClient
from core.web.services import team_service
from core.web.services.runtime_scene_service import record_runtime_scene_event


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_VERSION = 1
WORKFLOW_KIND_CHALLENGE_CUP_RESEARCH = "challenge_cup_research"
DEFAULT_OWNER_AGENT_ID = "Research Coordination Agent"
DEFAULT_WORKFLOW_ID = "challenge-cup-research-flow"
ALLOWED_WORKFLOW_KINDS = {WORKFLOW_KIND_CHALLENGE_CUP_RESEARCH}
CANDIDATE_TYPES = {
    "source_manifest",
    "paper_note",
    "neuro_mechanism",
    "mechanism_mapping",
    "algorithm_hypothesis",
    "review_record",
    "candidate_graph",
}
TRANSFER_DECISIONS = {"approved", "rejected", "returned"}
LOCAL_RESEARCH_MODEL_ID = "houmo_qwen35_9b_agent"
LOCAL_RESEARCH_MODEL_NAME = "bossAGI-standard / qwen3.5-9b"
LOCAL_RESEARCH_MODEL_ROLE = "Local Research Worker Model"
LOCAL_RESEARCH_CONTEXT_WINDOW = 32_000
LOCAL_RESEARCH_EVIDENCE_TOKEN_TARGET = "18k-22k"
LOCAL_RESEARCH_INVOKE_PROFILE_ID = "__challenge_cup_local_research_model"
LOCAL_RESEARCH_OUTPUT_FIELDS = (
    "candidateType",
    "sourceRefs",
    "evidenceRefs",
    "claims",
    "uncertainty",
    "riskFlags",
    "confidence",
    "nextAction",
    "requiresReview",
)
LOCAL_RESEARCH_TASKS = {
    "source_screening": {
        "workflowNode": "knowledge_collection",
        "targetCandidateType": "source_manifest",
        "purpose": "判断资料是否与神经机制启发神经网络算法相关。",
        "requiredOutput": ("candidateType", "sourceRefs", "evidenceRefs", "claims", "riskFlags", "confidence", "nextAction", "requiresReview"),
    },
    "paper_note_draft": {
        "workflowNode": "paper_note",
        "targetCandidateType": "paper_note",
        "purpose": "从资料片段生成 paper_note 草稿，保留 keyFindings、methods、limitations、uncertainty。",
        "requiredOutput": (*LOCAL_RESEARCH_OUTPUT_FIELDS, "keyFindings", "methods", "limitations", "citations"),
    },
    "neuro_mechanism_extract": {
        "workflowNode": "neuro_mechanism",
        "targetCandidateType": "neuro_mechanism",
        "purpose": "从 paper_note 与关键原文片段抽取 neuro_mechanism 候选。",
        "requiredOutput": (
            *LOCAL_RESEARCH_OUTPUT_FIELDS,
            "paperNoteIds",
            "description",
            "brainSystems",
            "cognitiveFunctions",
            "experimentalPhenomena",
            "authorInterpretation",
            "projectInterpretation",
        ),
    },
    "mechanism_mapping": {
        "workflowNode": "mechanism_mapping",
        "targetCandidateType": "mechanism_mapping",
        "purpose": "把神经机制映射为计算抽象，区分 factLayer、inferenceLayer 和 overAnalogyRisk。",
        "requiredOutput": (
            *LOCAL_RESEARCH_OUTPUT_FIELDS,
            "neuroMechanismIds",
            "computationalAbstraction",
            "factLayer",
            "inferenceLayer",
            "overAnalogyRisk",
            "engineeringImplication",
        ),
    },
    "algorithm_hypothesis_draft": {
        "workflowNode": "algorithm_hypothesis",
        "targetCandidateType": "algorithm_hypothesis",
        "purpose": "生成可审查 algorithm_hypothesis 草稿，必须包含 baseline 与 experimentPlan。",
        "requiredOutput": (
            *LOCAL_RESEARCH_OUTPUT_FIELDS,
            "mechanismMappingIds",
            "hypothesis",
            "baseline",
            "expectedBenefit",
            "expectedComputeCost",
            "experimentPlan",
        ),
    },
    "review_prefilter": {
        "workflowNode": "research_review",
        "targetCandidateType": "review_record",
        "purpose": "做 review prefilter，输出 riskFlags、requiredChanges 和 needsDecision，不写最终 review.decision。",
        "requiredOutput": (*LOCAL_RESEARCH_OUTPUT_FIELDS, "candidateIds", "checklist", "comments", "requiredChanges", "needsDecision"),
    },
    "steward_pack_draft": {
        "workflowNode": "steward_ingestion",
        "targetCandidateType": "review_record",
        "purpose": "生成 proposal/ingestion pack 草稿，供 Knowledge Steward Agent 复核。",
        "requiredOutput": (
            *LOCAL_RESEARCH_OUTPUT_FIELDS,
            "candidateIds",
            "targetDomain",
            "sourceTrace",
            "riskSummary",
            "proposalPayload",
            "ratingSuggestion",
            "approvalRequired",
        ),
    },
}
_SAFE_ID_FRAGMENT = re.compile(r"[^A-Za-z0-9_.-]+")
_WORKFLOW_LOCK = threading.RLock()


class TeamWorkflowOrchestrationError(ValueError):
    """Raised when a Team workflow orchestration request is invalid."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_team_workflow_orchestration(team_id: str) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    team_service.get_team(normalized_team_id)
    with _WORKFLOW_LOCK:
        workflow = _load_or_create_workflow(normalized_team_id)
        candidate_store = _load_candidate_store(normalized_team_id)
    return _workflow_to_api(normalized_team_id, workflow, candidate_store)


def ensure_team_workflow_orchestration(
    team_id: str,
    *,
    workflow_kind: str = WORKFLOW_KIND_CHALLENGE_CUP_RESEARCH,
    owner_agent_id: str = DEFAULT_OWNER_AGENT_ID,
) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    normalized_kind = _normalize_workflow_kind(workflow_kind)
    normalized_owner_agent_id = _trim_text(owner_agent_id, max_length=160) or DEFAULT_OWNER_AGENT_ID
    team_service.get_team(normalized_team_id)
    with _WORKFLOW_LOCK:
        path = _workflow_path(normalized_team_id)
        existing = _read_json(path) if path.exists() else {}
        workflow = _default_workflow(
            normalized_team_id,
            workflow_kind=normalized_kind,
            owner_agent_id=normalized_owner_agent_id,
        )
        if existing:
            workflow.update(_repair_workflow(existing, normalized_team_id))
            workflow["workflowKind"] = normalized_kind
            workflow["ownerAgentId"] = normalized_owner_agent_id
            workflow["routingPolicy"] = _sync_owner_policy(workflow.get("routingPolicy"), normalized_owner_agent_id)
            workflow["transferPolicy"] = _sync_transfer_policy(workflow.get("transferPolicy"), normalized_owner_agent_id)
            workflow["updatedAt"] = utc_now_iso()
        _write_json(path, workflow)
        candidate_store = _load_candidate_store(normalized_team_id)
    _record_workflow_event(
        "workflow.ensure",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "workflowKind": workflow["workflowKind"],
            "ownerAgentId": workflow["ownerAgentId"],
        },
    )
    return _workflow_to_api(normalized_team_id, workflow, candidate_store)


def register_candidate_source(team_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    team_service.get_team(normalized_team_id)
    candidate_type = _normalize_candidate_type(payload.get("candidateType") or "source_manifest")
    title = _trim_text(payload.get("title"), max_length=240)
    source_url = _trim_text(payload.get("sourceUrl"), max_length=2000)
    source_path = _trim_text(payload.get("sourcePath"), max_length=2000)
    if not title and not source_url and not source_path:
        raise TeamWorkflowOrchestrationError("Candidate title or sourceUrl is required.")
    now = utc_now_iso()
    with _WORKFLOW_LOCK:
        workflow = _load_or_create_workflow(normalized_team_id)
        candidate_store = _load_candidate_store(normalized_team_id)
        source_kind = _trim_text(payload.get("sourceKind"), max_length=80) or "unknown"
        metadata = _normalize_metadata(payload.get("metadata"))
        candidate = {
            "schemaVersion": SCHEMA_VERSION,
            "candidateId": _new_record_id("candidate"),
            "candidateType": candidate_type,
            "teamId": normalized_team_id,
            "workflowId": workflow["workflowId"],
            "title": title or source_url or source_path,
            "sourceUrl": source_url,
            "sourcePath": source_path,
            "sourceKind": source_kind,
            "sha256": _trim_text(payload.get("sha256"), max_length=128),
            "allowedForAnalysis": _normalize_optional_bool(payload.get("allowedForAnalysis")),
            "pageScope": _trim_text(payload.get("pageScope"), max_length=160),
            "summary": _trim_text(payload.get("summary"), max_length=4000),
            "tags": _normalize_text_list(payload.get("tags"), max_items=24, max_length=80),
            "evidenceRefs": _normalize_ref_list(payload.get("evidenceRefs"), max_items=24),
            "metadata": metadata,
            "createdByAgent": _trim_text(payload.get("createdByAgent"), max_length=160),
            "currentWorkflowNode": "knowledge_collection",
            "currentState": "source_registered",
            "qualityStatus": "pending_screening",
            "createdAt": now,
            "updatedAt": now,
        }
        validation = validate_candidate_record(candidate)
        candidate["validation"] = validation
        if not validation["valid"]:
            candidate["currentState"] = "source_needs_confirmation"
            candidate["qualityStatus"] = "source_manifest_invalid"
        candidate_store.setdefault("candidates", []).append(candidate)
        candidate_store["updatedAt"] = now
        _write_json(_candidate_store_path(normalized_team_id), candidate_store)
        workflow["updatedAt"] = now
        workflow["activeWorkflowItems"] = _upsert_active_item(
            workflow.get("activeWorkflowItems"),
            candidate_id=candidate["candidateId"],
            current_node=candidate["currentWorkflowNode"],
            status=candidate["currentState"],
            transfer_id="",
        )
        _write_json(_workflow_path(normalized_team_id), workflow)
    _record_workflow_event(
        "candidate.registered",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "candidateId": candidate["candidateId"],
            "candidateType": candidate["candidateType"],
            "sourceKind": candidate["sourceKind"],
        },
    )
    return {
        "candidate": candidate,
        "validation": validation,
        "workflow": _workflow_to_api(normalized_team_id, workflow, candidate_store),
    }


def list_candidate_store(
    team_id: str,
    *,
    candidate_type: str = "",
    current_state: str = "",
    quality_status: str = "",
    limit: int = 100,
) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    team_service.get_team(normalized_team_id)
    normalized_candidate_type = _trim_text(candidate_type, max_length=80)
    if normalized_candidate_type:
        normalized_candidate_type = _normalize_candidate_type(normalized_candidate_type)
    normalized_state = _trim_text(current_state, max_length=120)
    normalized_quality = _trim_text(quality_status, max_length=120)
    normalized_limit = max(1, min(int(limit or 100), 500))
    with _WORKFLOW_LOCK:
        workflow = _load_or_create_workflow(normalized_team_id)
        candidate_store = _load_candidate_store(normalized_team_id)
        candidates = _filtered_candidates(
            candidate_store,
            candidate_type=normalized_candidate_type,
            current_state=normalized_state,
            quality_status=normalized_quality,
        )[:normalized_limit]
        validation_report = validate_candidate_store(normalized_team_id)
    return {
        "teamId": normalized_team_id,
        "workflowId": workflow["workflowId"],
        "filters": {
            "candidateType": normalized_candidate_type,
            "currentState": normalized_state,
            "qualityStatus": normalized_quality,
            "limit": normalized_limit,
        },
        "candidates": candidates,
        "candidateCount": len(candidates),
        "store": _workflow_to_api(normalized_team_id, workflow, candidate_store)["candidateStore"],
        "validationSummary": validation_report["summary"],
    }


def validate_candidate_store(team_id: str) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    team_service.get_team(normalized_team_id)
    with _WORKFLOW_LOCK:
        workflow = _load_or_create_workflow(normalized_team_id)
        candidate_store = _load_candidate_store(normalized_team_id)
        candidates = [item for item in list(candidate_store.get("candidates") or []) if isinstance(item, dict)]
        candidate_reports = [
            {
                "candidateId": str(candidate.get("candidateId") or ""),
                "candidateType": str(candidate.get("candidateType") or ""),
                "currentState": str(candidate.get("currentState") or ""),
                "qualityStatus": str(candidate.get("qualityStatus") or ""),
                "validation": validate_candidate_record(candidate),
            }
            for candidate in candidates
        ]
    error_count = sum(1 for item in candidate_reports for issue in item["validation"]["issues"] if issue["severity"] == "error")
    warning_count = sum(1 for item in candidate_reports for issue in item["validation"]["issues"] if issue["severity"] == "warning")
    invalid_count = sum(1 for item in candidate_reports if not item["validation"]["valid"])
    summary = {
        "candidateCount": len(candidate_reports),
        "validCandidateCount": len(candidate_reports) - invalid_count,
        "invalidCandidateCount": invalid_count,
        "errorCount": error_count,
        "warningCount": warning_count,
    }
    _record_workflow_event(
        "candidate_store.validated",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            **summary,
        },
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "workflowId": workflow["workflowId"],
        "summary": summary,
        "candidates": candidate_reports,
        "storagePath": _relative_path(_candidate_store_path(normalized_team_id)),
    }


def build_candidate_graph(team_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    team_service.get_team(normalized_team_id)
    payload = payload if isinstance(payload, dict) else {}
    now = utc_now_iso()
    with _WORKFLOW_LOCK:
        workflow = _load_or_create_workflow(normalized_team_id)
        candidate_store = _load_candidate_store(normalized_team_id)
        candidates = [
            item
            for item in list(candidate_store.get("candidates") or [])
            if isinstance(item, dict) and str(item.get("candidateType") or "") != "candidate_graph"
        ]
        graph = _build_candidate_graph_payload(normalized_team_id, workflow["workflowId"], candidates)
        record = {
            "schemaVersion": SCHEMA_VERSION,
            "candidateId": _new_record_id("candidate-graph"),
            "candidateType": "candidate_graph",
            "teamId": normalized_team_id,
            "workflowId": workflow["workflowId"],
            "title": _trim_text(payload.get("title"), max_length=240) or "Candidate graph snapshot",
            "sourceKind": "candidate_graph_builder",
            "summary": f"{len(graph['nodes'])} nodes, {len(graph['edges'])} edges, {len(graph['missingLinks'])} missing links",
            "sourceRefs": [],
            "evidenceRefs": [],
            "metadata": {
                "generatedFromCandidateIds": [node["candidateId"] for node in graph["nodes"]],
                "graph": graph,
                "missingLinkCount": len(graph["missingLinks"]),
                "unreviewedNodeCount": len(graph["unreviewedNodes"]),
                "officialBoundary": graph["officialBoundary"],
            },
            "createdByAgent": _trim_text(payload.get("createdByAgent"), max_length=160) or "Candidate Graph Preview Agent",
            "currentWorkflowNode": "candidate_graph",
            "currentState": "candidate_graph_visible",
            "qualityStatus": "broken_links" if graph["missingLinks"] else "preview_ready",
            "createdAt": now,
            "updatedAt": now,
        }
        candidate_store.setdefault("candidates", []).append(record)
        candidate_store["updatedAt"] = now
        _write_json(_candidate_store_path(normalized_team_id), candidate_store)
        workflow["updatedAt"] = now
        workflow["activeWorkflowItems"] = _upsert_active_item(
            workflow.get("activeWorkflowItems"),
            candidate_id=record["candidateId"],
            current_node=record["currentWorkflowNode"],
            status=record["currentState"],
            transfer_id="",
        )
        _write_json(_workflow_path(normalized_team_id), workflow)
    _record_workflow_event(
        "candidate_graph.built",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "candidateId": record["candidateId"],
            "nodeCount": len(graph["nodes"]),
            "edgeCount": len(graph["edges"]),
            "missingLinkCount": len(graph["missingLinks"]),
            "unreviewedNodeCount": len(graph["unreviewedNodes"]),
        },
    )
    return {
        "candidateGraph": record,
        "graph": graph,
        "workflow": _workflow_to_api(normalized_team_id, workflow, candidate_store),
    }


def submit_transfer_request(team_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    team_service.get_team(normalized_team_id)
    candidate_id = _normalize_required_id(payload.get("candidateId"), "Candidate id is required.")
    from_node = _trim_text(payload.get("fromNode"), max_length=120)
    to_node = _trim_text(payload.get("toNode"), max_length=120)
    if not from_node or not to_node:
        raise TeamWorkflowOrchestrationError("fromNode and toNode are required.")
    now = utc_now_iso()
    with _WORKFLOW_LOCK:
        workflow = _load_or_create_workflow(normalized_team_id)
        candidate_store = _load_candidate_store(normalized_team_id)
        candidate = _find_candidate(candidate_store, candidate_id)
        if candidate is None:
            raise TeamWorkflowOrchestrationError("Candidate not found.")
        transfer = {
            "schemaVersion": SCHEMA_VERSION,
            "transferId": _new_record_id("transfer"),
            "teamId": normalized_team_id,
            "workflowId": workflow["workflowId"],
            "candidateId": candidate_id,
            "fromNode": from_node,
            "toNode": to_node,
            "status": "requested",
            "requiresUserConfirmation": False,
            "requestedByAgent": _trim_text(payload.get("requestedByAgent"), max_length=160),
            "reason": _trim_text(payload.get("reason"), max_length=4000),
            "evidenceRefs": _normalize_ref_list(payload.get("evidenceRefs"), max_items=24),
            "metadata": _normalize_metadata(payload.get("metadata")),
            "createdAt": now,
            "updatedAt": now,
        }
        _append_transfer_record(normalized_team_id, transfer)
        candidate["pendingTransferId"] = transfer["transferId"]
        candidate["updatedAt"] = now
        candidate_store["updatedAt"] = now
        _write_json(_candidate_store_path(normalized_team_id), candidate_store)
        workflow["updatedAt"] = now
        workflow["activeWorkflowItems"] = _upsert_active_item(
            workflow.get("activeWorkflowItems"),
            candidate_id=candidate_id,
            current_node=from_node,
            status="transfer_requested",
            transfer_id=transfer["transferId"],
        )
        _write_json(_workflow_path(normalized_team_id), workflow)
    _record_workflow_event(
        "transfer.requested",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "candidateId": candidate_id,
            "transferId": transfer["transferId"],
            "fromNode": from_node,
            "toNode": to_node,
            "requestedByAgent": transfer["requestedByAgent"],
        },
    )
    return {
        "transfer": transfer,
        "candidate": candidate,
        "workflow": _workflow_to_api(normalized_team_id, workflow, candidate_store),
    }


def decide_transfer_request(team_id: str, transfer_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    normalized_transfer_id = _normalize_required_id(transfer_id, "Transfer id is required.")
    team_service.get_team(normalized_team_id)
    decision = _trim_text(payload.get("decision"), max_length=32) or "approved"
    if decision not in TRANSFER_DECISIONS:
        raise TeamWorkflowOrchestrationError("Transfer decision is invalid.")
    decided_by_agent = _trim_text(payload.get("decidedByAgent"), max_length=160)
    now = utc_now_iso()
    with _WORKFLOW_LOCK:
        workflow = _load_or_create_workflow(normalized_team_id)
        if decided_by_agent != str(workflow.get("ownerAgentId") or DEFAULT_OWNER_AGENT_ID):
            raise TeamWorkflowOrchestrationError("Only the workflow owner agent can decide transfer requests.")
        candidate_store = _load_candidate_store(normalized_team_id)
        transfers = _load_transfer_records(normalized_team_id)
        transfer = _find_transfer(transfers, normalized_transfer_id)
        if transfer is None:
            raise TeamWorkflowOrchestrationError("Transfer request not found.")
        if str(transfer.get("status") or "") != "requested":
            raise TeamWorkflowOrchestrationError("Transfer request has already been decided.")
        candidate = _find_candidate(candidate_store, str(transfer.get("candidateId") or ""))
        if candidate is None:
            raise TeamWorkflowOrchestrationError("Candidate not found.")
        transfer.update(
            {
                "status": decision,
                "decisionNote": _trim_text(payload.get("decisionNote"), max_length=4000),
                "decidedByAgent": decided_by_agent,
                "decidedAt": now,
                "updatedAt": now,
            }
        )
        target_node = str(transfer.get("toNode") or "").strip()
        current_node = str(transfer.get("fromNode") or "").strip()
        if decision == "approved":
            current_node = target_node
            candidate["currentWorkflowNode"] = target_node
            candidate["currentState"] = _trim_text(payload.get("targetState"), max_length=120) or "transfer_approved"
            candidate["lastTransferId"] = normalized_transfer_id
            candidate.pop("pendingTransferId", None)
        elif decision == "returned":
            candidate["currentState"] = "returned_for_rework"
            candidate.pop("pendingTransferId", None)
        else:
            candidate["currentState"] = "transfer_rejected"
            candidate.pop("pendingTransferId", None)
        candidate["updatedAt"] = now
        candidate.setdefault("transitionHistory", []).append(
            {
                "transferId": normalized_transfer_id,
                "decision": decision,
                "fromNode": transfer.get("fromNode", ""),
                "toNode": transfer.get("toNode", ""),
                "decidedByAgent": decided_by_agent,
                "decidedAt": now,
            }
        )
        candidate_store["updatedAt"] = now
        _write_json(_candidate_store_path(normalized_team_id), candidate_store)
        _write_transfer_records(normalized_team_id, transfers)
        workflow["updatedAt"] = now
        workflow["activeWorkflowItems"] = _upsert_active_item(
            workflow.get("activeWorkflowItems"),
            candidate_id=candidate["candidateId"],
            current_node=current_node,
            status=candidate["currentState"],
            transfer_id="" if decision != "requested" else normalized_transfer_id,
        )
        _write_json(_workflow_path(normalized_team_id), workflow)
    _record_workflow_event(
        "transfer.decided",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "candidateId": candidate["candidateId"],
            "transferId": normalized_transfer_id,
            "decision": decision,
            "decidedByAgent": decided_by_agent,
        },
    )
    return {
        "transfer": transfer,
        "candidate": candidate,
        "workflow": _workflow_to_api(normalized_team_id, workflow, candidate_store),
    }


def build_local_research_model_task(team_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    team_service.get_team(normalized_team_id)
    task_type = _normalize_local_research_task_type(payload.get("taskType"))
    source_refs = _normalize_ref_list(payload.get("sourceRefs"), max_items=32)
    evidence_refs = _normalize_ref_list(payload.get("evidenceRefs"), max_items=32)
    candidate_refs = _normalize_ref_list(payload.get("candidateRefs"), max_items=24)
    excerpt = _trim_text(payload.get("excerpt"), max_length=24_000)
    if not (source_refs or evidence_refs or candidate_refs or excerpt):
        raise TeamWorkflowOrchestrationError("Local research model task requires sourceRefs, evidenceRefs, candidateRefs, or excerpt.")
    task_spec = LOCAL_RESEARCH_TASKS[task_type]
    with _WORKFLOW_LOCK:
        workflow = _load_or_create_workflow(normalized_team_id)
        candidate_store = _load_candidate_store(normalized_team_id)
    task = {
        "schemaVersion": SCHEMA_VERSION,
        "taskId": _new_record_id("local-model-task"),
        "teamId": normalized_team_id,
        "workflowId": workflow["workflowId"],
        "workflowKind": workflow["workflowKind"],
        "taskType": task_type,
        "workflowNode": task_spec["workflowNode"],
        "targetCandidateType": task_spec["targetCandidateType"],
        "model": {
            "modelId": _trim_text(payload.get("modelId"), max_length=160) or LOCAL_RESEARCH_MODEL_ID,
            "name": LOCAL_RESEARCH_MODEL_NAME,
            "role": LOCAL_RESEARCH_MODEL_ROLE,
            "contextWindow": LOCAL_RESEARCH_CONTEXT_WINDOW,
            "evidenceTokenTarget": LOCAL_RESEARCH_EVIDENCE_TOKEN_TARGET,
        },
        "contextBudget": {
            "schemaAndRules": "10%-15%",
            "taskInstruction": "5%-10%",
            "evidence": "55%-65%",
            "candidateContext": "10%-15%",
            "outputReserve": "10%-15%",
        },
        "sourceRefs": source_refs,
        "evidenceRefs": evidence_refs,
        "candidateRefs": candidate_refs,
        "excerpt": excerpt,
        "instruction": _local_research_model_instruction(task_type),
        "outputContract": {
            "format": "json_object",
            "requiredFields": list(task_spec["requiredOutput"]),
            "hardBoundaries": _local_research_model_boundaries(),
        },
        "candidateStore": {
            "candidateCount": len([item for item in list(candidate_store.get("candidates") or []) if isinstance(item, dict)]),
            "storagePath": _relative_path(_candidate_store_path(normalized_team_id)),
        },
        "createdByAgent": _trim_text(payload.get("createdByAgent"), max_length=160),
        "createdAt": utc_now_iso(),
    }
    _record_workflow_event(
        "local_model.task_built",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "taskId": task["taskId"],
            "taskType": task_type,
            "modelId": task["model"]["modelId"],
        },
    )
    return {"task": task, "workflow": _workflow_to_api(normalized_team_id, workflow, candidate_store)}


def record_local_research_model_output(team_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    team_service.get_team(normalized_team_id)
    task_type = _normalize_local_research_task_type(payload.get("taskType"))
    output = payload.get("output")
    if not isinstance(output, dict):
        raise TeamWorkflowOrchestrationError("Local research model output must be a JSON object.")
    validation = validate_local_research_model_output(task_type, output)
    now = utc_now_iso()
    with _WORKFLOW_LOCK:
        workflow = _load_or_create_workflow(normalized_team_id)
        candidate_store = _load_candidate_store(normalized_team_id)
        record = {
            "schemaVersion": SCHEMA_VERSION,
            "candidateId": _new_record_id("local-model-output"),
            "candidateType": str(output.get("candidateType") or LOCAL_RESEARCH_TASKS[task_type]["targetCandidateType"]),
            "teamId": normalized_team_id,
            "workflowId": workflow["workflowId"],
            "title": _trim_text(payload.get("title"), max_length=240) or f"{task_type} draft",
            "sourceKind": "local_research_model_output",
            "summary": _trim_text(output.get("nextAction") or payload.get("summary"), max_length=4000),
            "sourceRefs": _normalize_ref_list(output.get("sourceRefs"), max_items=32),
            "evidenceRefs": _normalize_ref_list(output.get("evidenceRefs"), max_items=32),
            "metadata": {
                "taskType": task_type,
                "modelId": _trim_text(payload.get("modelId"), max_length=160) or LOCAL_RESEARCH_MODEL_ID,
                "validation": validation,
                "output": _normalize_metadata(output),
            },
            "createdByAgent": _trim_text(payload.get("createdByAgent"), max_length=160),
            "currentWorkflowNode": LOCAL_RESEARCH_TASKS[task_type]["workflowNode"],
            "currentState": _local_research_output_state(task_type, validation["valid"]),
            "qualityStatus": "prefiltered" if validation["valid"] else "needs_revision",
            "createdAt": now,
            "updatedAt": now,
        }
        candidate_store.setdefault("candidates", []).append(record)
        candidate_store["updatedAt"] = now
        _write_json(_candidate_store_path(normalized_team_id), candidate_store)
        workflow["updatedAt"] = now
        workflow["activeWorkflowItems"] = _upsert_active_item(
            workflow.get("activeWorkflowItems"),
            candidate_id=record["candidateId"],
            current_node=record["currentWorkflowNode"],
            status=record["currentState"],
            transfer_id="",
        )
        _write_json(_workflow_path(normalized_team_id), workflow)
    _record_workflow_event(
        "local_model.output_recorded",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "candidateId": record["candidateId"],
            "taskType": task_type,
            "valid": validation["valid"],
            "issueCount": len(validation["issues"]),
        },
    )
    return {
        "candidate": record,
        "validation": validation,
        "workflow": _workflow_to_api(normalized_team_id, workflow, candidate_store),
    }


def invoke_local_research_model(team_id: str, payload: dict[str, Any], *, llm_client_factory: Any = None) -> dict[str, Any]:
    task_response = build_local_research_model_task(team_id, payload)
    task = task_response["task"]
    normalized_team_id = str(task["teamId"])
    model_id = str(task["model"]["modelId"] or LOCAL_RESEARCH_MODEL_ID)
    messages = _local_research_model_messages(task)
    metadata = {
        "workflowId": task["workflowId"],
        "taskId": task["taskId"],
        "taskType": task["taskType"],
        "teamId": normalized_team_id,
        "modelId": model_id,
        "surface": "team_workflow_orchestration.local_research_model",
    }
    try:
        client = _local_research_llm_client(model_id, llm_client_factory=llm_client_factory)
        message = client.invoke(messages, metadata=metadata)
    except Exception as exc:
        _record_workflow_event(
            "local_model.invoke_failed",
            normalized_team_id,
            fields={
                "workflowId": task["workflowId"],
                "taskId": task["taskId"],
                "taskType": task["taskType"],
                "modelId": model_id,
                "errorType": type(exc).__name__,
            },
        )
        raise TeamWorkflowOrchestrationError(f"Local research model invoke failed: {type(exc).__name__}") from exc

    raw_content = _trim_text(getattr(message, "content", ""), max_length=24_000)
    reasoning_content = ""
    additional_kwargs = getattr(message, "additional_kwargs", {}) or {}
    if isinstance(additional_kwargs, dict):
        reasoning_content = _trim_text(additional_kwargs.get("reasoning_content"), max_length=24_000)
    parsed_output, parse_source = _extract_json_object_from_model_text(raw_content, reasoning_content)
    if parsed_output is None:
        _record_workflow_event(
            "local_model.output_parse_failed",
            normalized_team_id,
            fields={
                "workflowId": task["workflowId"],
                "taskId": task["taskId"],
                "taskType": task["taskType"],
                "modelId": model_id,
                "contentChars": len(raw_content),
                "reasoningChars": len(reasoning_content),
            },
        )
        raise TeamWorkflowOrchestrationError("Local research model output did not contain a JSON object.")

    record_response = record_local_research_model_output(
        normalized_team_id,
        {
            "taskType": task["taskType"],
            "modelId": model_id,
            "title": payload.get("title") or f"{task['taskType']} draft",
            "summary": payload.get("summary") or "",
            "output": parsed_output,
            "createdByAgent": payload.get("createdByAgent") or "",
        },
    )
    record_response["task"] = task
    record_response["modelResponse"] = {
        "contentChars": len(raw_content),
        "reasoningChars": len(reasoning_content),
        "jsonSource": parse_source,
        "profileId": LOCAL_RESEARCH_INVOKE_PROFILE_ID,
        "modelId": model_id,
    }
    _record_workflow_event(
        "local_model.invoke_recorded",
        normalized_team_id,
        fields={
            "workflowId": task["workflowId"],
            "taskId": task["taskId"],
            "candidateId": record_response["candidate"]["candidateId"],
            "taskType": task["taskType"],
            "modelId": model_id,
            "valid": record_response["validation"]["valid"],
            "jsonSource": parse_source,
        },
    )
    return record_response


def validate_local_research_model_output(task_type: str, output: dict[str, Any]) -> dict[str, Any]:
    normalized_task_type = _normalize_local_research_task_type(task_type)
    issues: list[dict[str, str]] = []
    required_fields = list(LOCAL_RESEARCH_TASKS[normalized_task_type]["requiredOutput"])
    for field in required_fields:
        if field not in output:
            issues.append({"severity": "error", "code": "missing_field", "message": f"Missing required field: {field}"})
    source_refs = output.get("sourceRefs")
    evidence_refs = output.get("evidenceRefs")
    risk_flags = output.get("riskFlags")
    if not isinstance(source_refs, list) or not source_refs:
        issues.append({"severity": "error", "code": "missing_source_refs", "message": "sourceRefs must include at least one source reference."})
    if not isinstance(evidence_refs, list) or not evidence_refs:
        issues.append({"severity": "error", "code": "missing_evidence_refs", "message": "evidenceRefs must include at least one evidence reference."})
    if not isinstance(risk_flags, list):
        issues.append({"severity": "error", "code": "invalid_risk_flags", "message": "riskFlags must be a list."})
    elif not evidence_refs and "weak_evidence" not in [str(item) for item in risk_flags]:
        issues.append({"severity": "error", "code": "weak_evidence_not_flagged", "message": "Missing evidence must be marked as weak_evidence."})
    if normalized_task_type in {"mechanism_mapping", "algorithm_hypothesis_draft"}:
        for field in ("factLayer", "inferenceLayer"):
            if field in required_fields and not _has_value(output.get(field)):
                issues.append({"severity": "error", "code": "missing_fact_inference_layer", "message": f"{field} is required for analogy control."})
    if normalized_task_type == "algorithm_hypothesis_draft" and not _has_value(output.get("experimentPlan")):
        issues.append({"severity": "error", "code": "missing_experiment_plan", "message": "algorithm_hypothesis draft requires experimentPlan."})
    if normalized_task_type == "review_prefilter" and "decision" in output:
        issues.append({"severity": "error", "code": "final_decision_not_allowed", "message": "review_prefilter must not write final review.decision."})
    if normalized_task_type == "paper_note_draft":
        issues.extend(_validate_paper_note_output(output))
    if normalized_task_type == "neuro_mechanism_extract":
        issues.extend(_validate_neuro_mechanism_output(output))
    if normalized_task_type == "mechanism_mapping":
        issues.extend(_validate_mechanism_mapping_output(output))
    if normalized_task_type == "algorithm_hypothesis_draft":
        issues.extend(_validate_algorithm_hypothesis_output(output))
    if normalized_task_type == "review_prefilter":
        issues.extend(_validate_review_prefilter_output(output))
    if normalized_task_type == "steward_pack_draft":
        issues.extend(_validate_steward_pack_output(output))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "taskType": normalized_task_type,
        "valid": not any(item["severity"] == "error" for item in issues),
        "issues": issues,
        "requiredFields": required_fields,
        "hardBoundaries": _local_research_model_boundaries(),
    }


def validate_candidate_record(candidate: dict[str, Any]) -> dict[str, Any]:
    candidate_type = _trim_text(candidate.get("candidateType"), max_length=80)
    issues: list[dict[str, str]] = []
    if not candidate_type:
        issues.append({"severity": "error", "code": "missing_candidate_type", "message": "candidateType is required."})
    elif candidate_type not in CANDIDATE_TYPES:
        issues.append({"severity": "error", "code": "invalid_candidate_type", "message": "candidateType is not supported."})
    if not _has_value(candidate.get("candidateId")):
        issues.append({"severity": "error", "code": "missing_candidate_id", "message": "candidateId is required."})
    if not _has_value(candidate.get("teamId")):
        issues.append({"severity": "error", "code": "missing_team_id", "message": "teamId is required."})
    if candidate_type == "source_manifest":
        issues.extend(_validate_source_manifest(candidate))
    elif candidate_type == "paper_note":
        issues.extend(_validate_paper_note_candidate(candidate))
    elif candidate_type == "neuro_mechanism":
        issues.extend(_validate_neuro_mechanism_candidate(candidate))
    elif candidate_type == "mechanism_mapping":
        issues.extend(_validate_mechanism_mapping_candidate(candidate))
    elif candidate_type == "algorithm_hypothesis":
        issues.extend(_validate_algorithm_hypothesis_candidate(candidate))
    elif candidate_type == "review_record":
        issues.extend(_validate_review_record_candidate(candidate))
    elif candidate_type == "candidate_graph":
        issues.extend(_validate_candidate_graph_candidate(candidate))
    elif candidate_type in {"paper_note", "neuro_mechanism", "mechanism_mapping", "algorithm_hypothesis", "review_record"}:
        if not _normalize_ref_list(candidate.get("sourceRefs"), max_items=32):
            issues.append({"severity": "error", "code": "missing_source_refs", "message": f"{candidate_type} must keep sourceRefs."})
        if not _normalize_ref_list(candidate.get("evidenceRefs"), max_items=32):
            issues.append({"severity": "warning", "code": "missing_evidence_refs", "message": f"{candidate_type} should include evidenceRefs before review."})
    return {
        "schemaVersion": SCHEMA_VERSION,
        "candidateType": candidate_type,
        "valid": not any(item["severity"] == "error" for item in issues),
        "issues": issues,
    }


def _workflow_to_api(
    team_id: str,
    workflow: dict[str, Any],
    candidate_store: dict[str, Any],
) -> dict[str, Any]:
    candidates = [item for item in list(candidate_store.get("candidates") or []) if isinstance(item, dict)]
    return {
        **workflow,
        "candidateStore": {
            "schemaVersion": SCHEMA_VERSION,
            "candidateCount": len(candidates),
            "candidateTypes": sorted({str(item.get("candidateType") or "") for item in candidates if item.get("candidateType")}),
            "updatedAt": str(candidate_store.get("updatedAt") or ""),
            "storagePath": _relative_path(_candidate_store_path(team_id)),
        },
        "transferRecordsPath": _relative_path(_transfer_records_path(team_id)),
        "storagePath": _relative_path(_workflow_path(team_id)),
    }


def _filtered_candidates(
    candidate_store: dict[str, Any],
    *,
    candidate_type: str,
    current_state: str,
    quality_status: str,
) -> list[dict[str, Any]]:
    candidates = [item for item in list(candidate_store.get("candidates") or []) if isinstance(item, dict)]
    filtered: list[dict[str, Any]] = []
    for candidate in candidates:
        if candidate_type and str(candidate.get("candidateType") or "") != candidate_type:
            continue
        if current_state and str(candidate.get("currentState") or "") != current_state:
            continue
        if quality_status and str(candidate.get("qualityStatus") or "") != quality_status:
            continue
        filtered.append(candidate)
    return filtered


def _local_research_output_state(task_type: str, valid: bool) -> str:
    if task_type == "paper_note_draft":
        return "paper_note_draft" if valid else "paper_note_needs_revision"
    if task_type == "neuro_mechanism_extract":
        return "mechanism_candidate" if valid else "mechanism_needs_revision"
    if task_type == "mechanism_mapping":
        return "mechanism_mapping_candidate" if valid else "mapping_needs_revision"
    if task_type == "algorithm_hypothesis_draft":
        return "hypothesis_candidate" if valid else "hypothesis_needs_revision"
    if task_type == "review_prefilter":
        return "review_prefiltered" if valid else "review_needs_revision"
    if task_type == "steward_pack_draft":
        return "steward_pack_draft" if valid else "steward_needs_revision"
    return "local_model_draft_ready" if valid else "local_model_draft_needs_revision"


def _build_candidate_graph_payload(team_id: str, workflow_id: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    nodes = [_candidate_graph_node(candidate) for candidate in candidates]
    node_ids = {node["candidateId"] for node in nodes}
    edges: list[dict[str, str]] = []
    missing_links: list[dict[str, str]] = []
    for candidate in candidates:
        source_id = str(candidate.get("candidateId") or "")
        if not source_id:
            continue
        for edge in _candidate_graph_edges(candidate):
            target_id = edge["targetCandidateId"]
            if target_id in node_ids:
                edges.append(edge)
            else:
                missing_links.append(edge)
    unreviewed_nodes = [
        {
            "candidateId": node["candidateId"],
            "candidateType": node["candidateType"],
            "currentState": node["currentState"],
            "reason": "requires_review_or_not_reviewed",
        }
        for node in nodes
        if node["candidateType"] not in {"source_manifest", "review_record"}
        and (node["requiresReview"] or node["currentState"] not in {"review_prefiltered", "approved_to_ingest", "official_synced"})
    ]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": team_id,
        "workflowId": workflow_id,
        "graphKind": "candidate_only",
        "nodes": nodes,
        "edges": edges,
        "missingLinks": missing_links,
        "unreviewedNodes": unreviewed_nodes,
        "officialBoundary": {
            "writesOfficialKnowledge": False,
            "writesOfficialRag": False,
            "writesOfficialGraph": False,
            "requiresIngestionApproval": True,
        },
        "summary": {
            "nodeCount": len(nodes),
            "edgeCount": len(edges),
            "missingLinkCount": len(missing_links),
            "unreviewedNodeCount": len(unreviewed_nodes),
        },
        "createdAt": utc_now_iso(),
    }


def _candidate_graph_node(candidate: dict[str, Any]) -> dict[str, Any]:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    output = metadata.get("output") if isinstance(metadata.get("output"), dict) else {}
    validation = validate_candidate_record(candidate)
    return {
        "candidateId": str(candidate.get("candidateId") or ""),
        "candidateType": str(candidate.get("candidateType") or ""),
        "title": str(candidate.get("title") or ""),
        "currentWorkflowNode": str(candidate.get("currentWorkflowNode") or ""),
        "currentState": str(candidate.get("currentState") or ""),
        "qualityStatus": str(candidate.get("qualityStatus") or ""),
        "valid": validation["valid"],
        "requiresReview": bool(output.get("requiresReview")) if "requiresReview" in output else str(candidate.get("qualityStatus") or "") != "approved",
        "officialState": "candidate_only",
    }


def _candidate_graph_edges(candidate: dict[str, Any]) -> list[dict[str, str]]:
    source_id = str(candidate.get("candidateId") or "")
    candidate_type = str(candidate.get("candidateType") or "")
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    output = metadata.get("output") if isinstance(metadata.get("output"), dict) else {}
    edges: list[dict[str, str]] = []
    if candidate_type == "neuro_mechanism":
        for target_id in _normalize_id_values(output.get("paperNoteIds")):
            edges.append(_candidate_graph_edge(source_id, target_id, "supported_by_paper_note"))
    if candidate_type == "mechanism_mapping":
        for target_id in _normalize_id_values(output.get("neuroMechanismIds")):
            edges.append(_candidate_graph_edge(source_id, target_id, "maps_from_neuro_mechanism"))
    if candidate_type == "algorithm_hypothesis":
        for target_id in _normalize_id_values(output.get("mechanismMappingIds")):
            edges.append(_candidate_graph_edge(source_id, target_id, "inspired_by_mapping"))
        for target_id in _normalize_id_values(output.get("neuroMechanismIds")):
            edges.append(_candidate_graph_edge(source_id, target_id, "inspired_by_neuro_mechanism"))
    if candidate_type == "review_record":
        for target_id in _normalize_id_values(output.get("candidateIds") or output.get("reviewedCandidateIds")):
            edges.append(_candidate_graph_edge(source_id, target_id, "reviews_candidate"))
    return edges


def _candidate_graph_edge(source_id: str, target_id: str, relation: str) -> dict[str, str]:
    return {
        "sourceCandidateId": source_id,
        "targetCandidateId": target_id,
        "relation": relation,
        "edgeState": "candidate_only",
    }


def _normalize_id_values(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value[:64]:
        text = _trim_text(item, max_length=160)
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _validate_source_manifest(candidate: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    source_kind = _trim_text(candidate.get("sourceKind"), max_length=80)
    source_url = _trim_text(candidate.get("sourceUrl"), max_length=2000)
    source_path = _trim_text(candidate.get("sourcePath"), max_length=2000)
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    metadata_path = _trim_text(metadata.get("path") or metadata.get("sourcePath"), max_length=2000)
    metadata_sha = _trim_text(metadata.get("sha256") or metadata.get("hash"), max_length=128)
    sha256 = _trim_text(candidate.get("sha256"), max_length=128) or metadata_sha
    allowed = candidate.get("allowedForAnalysis")
    if allowed is None and "allowedForAnalysis" in metadata:
        allowed = _normalize_optional_bool(metadata.get("allowedForAnalysis"))
    page_scope = _trim_text(candidate.get("pageScope") or metadata.get("pageScope"), max_length=160)
    if not source_kind or source_kind == "unknown":
        issues.append({"severity": "warning", "code": "unknown_source_kind", "message": "sourceKind should identify pdf, paper, note, or competition_doc."})
    if not (source_url or source_path or metadata_path):
        issues.append({"severity": "error", "code": "missing_source_location", "message": "source_manifest requires sourceUrl, sourcePath, or metadata.path."})
    is_pdf = source_kind == "pdf" or source_path.lower().endswith(".pdf") or metadata_path.lower().endswith(".pdf")
    if is_pdf:
        if not (source_path or metadata_path):
            issues.append({"severity": "error", "code": "missing_pdf_path", "message": "PDF source_manifest requires sourcePath or metadata.path."})
        if not sha256:
            issues.append({"severity": "error", "code": "missing_sha256", "message": "PDF source_manifest requires sha256 before screening."})
        if allowed is not True:
            issues.append({"severity": "error", "code": "analysis_not_allowed", "message": "PDF source_manifest requires allowedForAnalysis=true."})
        if not page_scope:
            issues.append({"severity": "warning", "code": "missing_page_scope", "message": "PDF source_manifest should include pageScope for later citation anchors."})
    return issues


def _validate_paper_note_output(output: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    key_findings = output.get("keyFindings")
    if not isinstance(key_findings, list) or not key_findings:
        issues.append({"severity": "error", "code": "missing_key_findings", "message": "paper_note requires at least one keyFinding."})
        return issues
    for index, finding in enumerate(key_findings):
        if not isinstance(finding, dict):
            issues.append({"severity": "error", "code": "invalid_key_finding", "message": f"keyFindings[{index}] must be an object."})
            continue
        if not _has_value(finding.get("finding") or finding.get("claim") or finding.get("summary")):
            issues.append({"severity": "error", "code": "missing_key_finding_text", "message": f"keyFindings[{index}] requires finding text."})
        if not _has_citation_anchor(finding):
            issues.append({"severity": "error", "code": "missing_key_finding_citation", "message": f"keyFindings[{index}] requires sourceRef and page/citation anchor."})
    citations = output.get("citations")
    if not isinstance(citations, list) or not citations:
        issues.append({"severity": "error", "code": "missing_citations", "message": "paper_note requires citations."})
    elif not any(_has_citation_anchor(item) for item in citations if isinstance(item, dict)):
        issues.append({"severity": "error", "code": "missing_citation_anchor", "message": "At least one citation must include sourceRef and page/citation anchor."})
    return issues


def _validate_paper_note_candidate(candidate: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if not _normalize_ref_list(candidate.get("sourceRefs"), max_items=32):
        issues.append({"severity": "error", "code": "missing_source_refs", "message": "paper_note must keep sourceRefs."})
    if not _normalize_ref_list(candidate.get("evidenceRefs"), max_items=32):
        issues.append({"severity": "warning", "code": "missing_evidence_refs", "message": "paper_note should include evidenceRefs before mechanism extraction."})
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    output = metadata.get("output") if isinstance(metadata.get("output"), dict) else {}
    if output:
        issues.extend(_validate_paper_note_output(output))
    return issues


def _validate_neuro_mechanism_output(output: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    paper_note_ids = output.get("paperNoteIds")
    if not isinstance(paper_note_ids, list) or not any(_has_value(item) for item in paper_note_ids):
        issues.append({"severity": "error", "code": "missing_paper_note_ids", "message": "neuro_mechanism requires at least one paperNoteId."})
    if not _has_value(output.get("description")):
        issues.append({"severity": "error", "code": "missing_mechanism_description", "message": "neuro_mechanism requires description."})
    if not _has_value(output.get("experimentalPhenomena")):
        issues.append({"severity": "error", "code": "missing_experimental_phenomena", "message": "neuro_mechanism requires experimentalPhenomena."})
    if not _has_neuro_term_or_unknown(output.get("brainSystems")):
        issues.append({"severity": "error", "code": "missing_brain_systems", "message": "neuro_mechanism requires brainSystems or explicit unknown."})
    if not _has_neuro_term_or_unknown(output.get("cognitiveFunctions")):
        issues.append({"severity": "error", "code": "missing_cognitive_functions", "message": "neuro_mechanism requires cognitiveFunctions or explicit unknown."})
    if _requires_terminology_uncertain(output) and not _risk_flags_include(output, "terminology_uncertain"):
        issues.append({"severity": "error", "code": "terminology_uncertain_not_flagged", "message": "Unknown or uncertain neuro terms must include terminology_uncertain."})
    confidence = output.get("confidence")
    if not isinstance(confidence, (int, float)) or confidence < 0 or confidence > 1:
        issues.append({"severity": "error", "code": "invalid_confidence", "message": "confidence must be a number between 0 and 1."})
    return issues


def _validate_neuro_mechanism_candidate(candidate: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if not _normalize_ref_list(candidate.get("sourceRefs"), max_items=32):
        issues.append({"severity": "error", "code": "missing_source_refs", "message": "neuro_mechanism must keep sourceRefs."})
    if not _normalize_ref_list(candidate.get("evidenceRefs"), max_items=32):
        issues.append({"severity": "error", "code": "missing_evidence_refs", "message": "neuro_mechanism requires evidenceRefs before mapping."})
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    output = metadata.get("output") if isinstance(metadata.get("output"), dict) else {}
    if output:
        issues.extend(_validate_neuro_mechanism_output(output))
    return issues


def _validate_mechanism_mapping_output(output: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    mechanism_ids = output.get("neuroMechanismIds")
    if not isinstance(mechanism_ids, list) or not any(_has_value(item) for item in mechanism_ids):
        issues.append({"severity": "error", "code": "missing_neuro_mechanism_ids", "message": "mechanism_mapping requires at least one neuroMechanismId."})
    if not _has_value(output.get("computationalAbstraction")):
        issues.append({"severity": "error", "code": "missing_computational_abstraction", "message": "mechanism_mapping requires computationalAbstraction."})
    if not _has_value(output.get("factLayer")):
        issues.append({"severity": "error", "code": "missing_fact_layer", "message": "mechanism_mapping must separate paper facts in factLayer."})
    if not _has_value(output.get("inferenceLayer")):
        issues.append({"severity": "error", "code": "missing_inference_layer", "message": "mechanism_mapping must separate project inference in inferenceLayer."})
    if "overAnalogyRisk" not in output:
        issues.append({"severity": "error", "code": "missing_over_analogy_risk", "message": "mechanism_mapping requires overAnalogyRisk."})
    elif _is_over_analogy_risky(output.get("overAnalogyRisk")) and not _risk_flags_include(output, "over_analogy_risk"):
        issues.append({"severity": "error", "code": "over_analogy_risk_not_flagged", "message": "High or unresolved analogy risk must include over_analogy_risk."})
    if not _has_value(output.get("engineeringImplication")):
        issues.append({"severity": "error", "code": "missing_engineering_implication", "message": "mechanism_mapping requires engineeringImplication."})
    return issues


def _validate_mechanism_mapping_candidate(candidate: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if not _normalize_ref_list(candidate.get("sourceRefs"), max_items=32):
        issues.append({"severity": "error", "code": "missing_source_refs", "message": "mechanism_mapping must keep sourceRefs."})
    if not _normalize_ref_list(candidate.get("evidenceRefs"), max_items=32):
        issues.append({"severity": "error", "code": "missing_evidence_refs", "message": "mechanism_mapping requires evidenceRefs before hypothesis generation."})
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    output = metadata.get("output") if isinstance(metadata.get("output"), dict) else {}
    if output:
        issues.extend(_validate_mechanism_mapping_output(output))
    return issues


def _validate_algorithm_hypothesis_output(output: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    mapping_ids = output.get("mechanismMappingIds")
    mechanism_ids = output.get("neuroMechanismIds")
    if not _has_any_list_value(mapping_ids) and not _has_any_list_value(mechanism_ids):
        issues.append({"severity": "error", "code": "missing_upstream_mechanism_refs", "message": "algorithm_hypothesis requires mechanismMappingIds or neuroMechanismIds."})
    if not _has_value(output.get("hypothesis")):
        issues.append({"severity": "error", "code": "missing_hypothesis", "message": "algorithm_hypothesis requires hypothesis."})
    for field, code in (
        ("baseline", "missing_baseline"),
        ("expectedBenefit", "missing_expected_benefit"),
        ("expectedComputeCost", "missing_expected_compute_cost"),
    ):
        if not _has_value(output.get(field)):
            issues.append({"severity": "error", "code": code, "message": f"algorithm_hypothesis requires {field}."})
    experiment_plan = output.get("experimentPlan")
    if not isinstance(experiment_plan, dict) or not experiment_plan:
        issues.append({"severity": "error", "code": "missing_experiment_plan", "message": "algorithm_hypothesis requires experimentPlan."})
    else:
        for field in ("dataset", "metric", "baseline", "smokePlan"):
            if not _has_value(experiment_plan.get(field)):
                issues.append({"severity": "error", "code": "incomplete_experiment_plan", "message": f"experimentPlan requires {field}."})
    return issues


def _validate_algorithm_hypothesis_candidate(candidate: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if not _normalize_ref_list(candidate.get("sourceRefs"), max_items=32):
        issues.append({"severity": "error", "code": "missing_source_refs", "message": "algorithm_hypothesis must keep sourceRefs."})
    if not _normalize_ref_list(candidate.get("evidenceRefs"), max_items=32):
        issues.append({"severity": "error", "code": "missing_evidence_refs", "message": "algorithm_hypothesis requires evidenceRefs before review."})
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    output = metadata.get("output") if isinstance(metadata.get("output"), dict) else {}
    if output:
        issues.extend(_validate_algorithm_hypothesis_output(output))
    return issues


def _validate_review_prefilter_output(output: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if not _has_any_list_value(output.get("candidateIds")):
        issues.append({"severity": "error", "code": "missing_review_candidate_ids", "message": "review_prefilter requires candidateIds."})
    checklist = output.get("checklist")
    if not isinstance(checklist, list) or not checklist:
        issues.append({"severity": "error", "code": "missing_review_checklist", "message": "review_prefilter requires checklist."})
    else:
        for index, item in enumerate(checklist):
            if not isinstance(item, dict):
                issues.append({"severity": "error", "code": "invalid_review_checklist_item", "message": f"checklist[{index}] must be an object."})
                continue
            if not _has_value(item.get("item") or item.get("name") or item.get("check")):
                issues.append({"severity": "error", "code": "missing_review_checklist_item", "message": f"checklist[{index}] requires item text."})
            if not _has_value(item.get("status") or item.get("result")):
                issues.append({"severity": "error", "code": "missing_review_checklist_status", "message": f"checklist[{index}] requires status/result."})
    if not _has_value(output.get("comments")):
        issues.append({"severity": "error", "code": "missing_review_comments", "message": "review_prefilter requires comments."})
    required_changes = output.get("requiredChanges")
    if not isinstance(required_changes, list):
        issues.append({"severity": "error", "code": "invalid_required_changes", "message": "review_prefilter requiredChanges must be a list."})
    needs_decision = output.get("needsDecision")
    if not isinstance(needs_decision, bool):
        issues.append({"severity": "error", "code": "invalid_needs_decision", "message": "review_prefilter needsDecision must be boolean."})
    return issues


def _validate_review_record_candidate(candidate: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if not _normalize_ref_list(candidate.get("sourceRefs"), max_items=32):
        issues.append({"severity": "error", "code": "missing_source_refs", "message": "review_record must keep sourceRefs."})
    if not _normalize_ref_list(candidate.get("evidenceRefs"), max_items=32):
        issues.append({"severity": "error", "code": "missing_evidence_refs", "message": "review_record requires evidenceRefs."})
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    output = metadata.get("output") if isinstance(metadata.get("output"), dict) else {}
    if output:
        if "decision" in output:
            issues.append({"severity": "error", "code": "final_decision_not_allowed", "message": "review_record prefilter must not include final decision."})
        task_type = str(metadata.get("taskType") or "")
        if task_type == "steward_pack_draft":
            issues.extend(_validate_steward_pack_output(output))
        else:
            issues.extend(_validate_review_prefilter_output(output))
    return issues


def _validate_steward_pack_output(output: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if not _has_any_list_value(output.get("candidateIds")):
        issues.append({"severity": "error", "code": "missing_steward_candidate_ids", "message": "steward_pack requires candidateIds."})
    for field, code in (
        ("targetDomain", "missing_target_domain"),
        ("sourceTrace", "missing_source_trace"),
        ("riskSummary", "missing_risk_summary"),
        ("proposalPayload", "missing_proposal_payload"),
        ("ratingSuggestion", "missing_rating_suggestion"),
    ):
        if not _has_value(output.get(field)):
            issues.append({"severity": "error", "code": code, "message": f"steward_pack requires {field}."})
    if output.get("approvalRequired") is not True:
        issues.append({"severity": "error", "code": "approval_required_not_true", "message": "steward_pack must set approvalRequired=true."})
    if _has_value(output.get("officialSync")) or output.get("applyNow") is True or output.get("writeOfficialGraph") is True:
        issues.append({"severity": "error", "code": "official_write_not_allowed", "message": "steward_pack draft must not request immediate official write or graph sync."})
    return issues


def _validate_candidate_graph_candidate(candidate: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    graph = metadata.get("graph") if isinstance(metadata.get("graph"), dict) else {}
    if not graph:
        issues.append({"severity": "error", "code": "missing_candidate_graph", "message": "candidate_graph requires metadata.graph."})
        return issues
    boundary = graph.get("officialBoundary") if isinstance(graph.get("officialBoundary"), dict) else {}
    if boundary.get("writesOfficialKnowledge") is not False or boundary.get("writesOfficialGraph") is not False:
        issues.append({"severity": "error", "code": "invalid_official_boundary", "message": "candidate_graph must remain candidate_only and cannot write official knowledge or graph."})
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        issues.append({"severity": "error", "code": "invalid_graph_nodes", "message": "candidate_graph nodes must be a list."})
    edges = graph.get("edges")
    if not isinstance(edges, list):
        issues.append({"severity": "error", "code": "invalid_graph_edges", "message": "candidate_graph edges must be a list."})
    missing_links = graph.get("missingLinks")
    if isinstance(missing_links, list) and missing_links and str(candidate.get("qualityStatus") or "") != "broken_links":
        issues.append({"severity": "error", "code": "missing_links_not_flagged", "message": "candidate_graph with missing links must use qualityStatus=broken_links."})
    return issues


def _has_any_list_value(value: Any) -> bool:
    return isinstance(value, list) and any(_has_value(item) for item in value)


def _has_neuro_term_or_unknown(value: Any) -> bool:
    if isinstance(value, list):
        return any(_has_value(item) for item in value)
    text = _trim_text(value, max_length=160).lower()
    return bool(text)


def _requires_terminology_uncertain(output: dict[str, Any]) -> bool:
    terms = [output.get("brainSystems"), output.get("cognitiveFunctions"), output.get("uncertainty")]
    for value in terms:
        values = value if isinstance(value, list) else [value]
        for item in values:
            text = _trim_text(item, max_length=400).lower()
            if text in {"unknown", "uncertain", "不确定", "未知"} or "terminology" in text or "术语" in text:
                return True
    return False


def _risk_flags_include(output: dict[str, Any], flag: str) -> bool:
    risk_flags = output.get("riskFlags")
    return isinstance(risk_flags, list) and flag in {str(item) for item in risk_flags}


def _is_over_analogy_risky(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, dict):
        level = _trim_text(value.get("level") or value.get("severity") or value.get("riskLevel"), max_length=80).lower()
        status = _trim_text(value.get("status"), max_length=80).lower()
        return level in {"high", "critical", "severe", "高", "严重"} or status in {"unresolved", "open", "未解决"}
    if isinstance(value, list):
        return any(_is_over_analogy_risky(item) for item in value)
    text = _trim_text(value, max_length=400).lower()
    return text in {"high", "critical", "severe", "高", "严重"} or "over" in text or "过度" in text or "unsupported" in text or "unresolved" in text


def _has_citation_anchor(value: dict[str, Any]) -> bool:
    source_ref = _trim_text(value.get("sourceRef") or value.get("sourceRefId") or value.get("sourceId"), max_length=240)
    page = _trim_text(value.get("page") or value.get("pageAnchor") or value.get("pageRange"), max_length=120)
    citation = _trim_text(value.get("citation") or value.get("citationAnchor"), max_length=240)
    evidence_ref = _trim_text(value.get("evidenceRef") or value.get("evidenceRefId"), max_length=240)
    return bool(source_ref and (page or citation or evidence_ref))


def _normalize_optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y", "allowed"}:
        return True
    if text in {"false", "0", "no", "n", "denied"}:
        return False
    return None


def _default_workflow(team_id: str, *, workflow_kind: str, owner_agent_id: str) -> dict[str, Any]:
    now = utc_now_iso()
    return {
        "schemaVersion": SCHEMA_VERSION,
        "workflowId": DEFAULT_WORKFLOW_ID,
        "teamId": team_id,
        "workflowKind": workflow_kind,
        "status": "active",
        "ownerAgentId": owner_agent_id,
        "stateMachine": {
            "currentStage": "knowledge_collection",
            "nodes": [
                {"nodeId": "knowledge_collection", "label": "知识搜集"},
                {"nodeId": "source_screening", "label": "资料筛选"},
                {"nodeId": "candidate_ingestion", "label": "候选入库"},
                {"nodeId": "team_memory_ready", "label": "团队共享记忆待接入"},
            ],
            "transitions": [
                {"from": "knowledge_collection", "to": "source_screening"},
                {"from": "source_screening", "to": "candidate_ingestion"},
                {"from": "candidate_ingestion", "to": "team_memory_ready"},
                {"from": "source_screening", "to": "knowledge_collection", "type": "rework"},
                {"from": "candidate_ingestion", "to": "source_screening", "type": "rework"},
            ],
        },
        "routingPolicy": {
            "coordinationAgentId": owner_agent_id,
            "functionalAgentsMayRequestTransfer": True,
            "finalStateWriter": owner_agent_id,
        },
        "transferPolicy": {
            "requiresUserConfirmation": False,
            "requestedBy": "functional_agent",
            "decidedBy": owner_agent_id,
            "recordDecidedByAgent": True,
        },
        "activeWorkflowItems": [],
        "createdAt": now,
        "updatedAt": now,
    }


def _sync_owner_policy(value: Any, owner_agent_id: str) -> dict[str, Any]:
    policy = value if isinstance(value, dict) else {}
    return {
        **policy,
        "coordinationAgentId": owner_agent_id,
        "functionalAgentsMayRequestTransfer": True,
        "finalStateWriter": owner_agent_id,
    }


def _sync_transfer_policy(value: Any, owner_agent_id: str) -> dict[str, Any]:
    policy = value if isinstance(value, dict) else {}
    return {
        **policy,
        "requiresUserConfirmation": False,
        "requestedBy": "functional_agent",
        "decidedBy": owner_agent_id,
        "recordDecidedByAgent": True,
    }


def _repair_workflow(payload: dict[str, Any], team_id: str) -> dict[str, Any]:
    base = _default_workflow(
        team_id,
        workflow_kind=_normalize_workflow_kind(payload.get("workflowKind") or WORKFLOW_KIND_CHALLENGE_CUP_RESEARCH),
        owner_agent_id=_trim_text(payload.get("ownerAgentId"), max_length=160) or DEFAULT_OWNER_AGENT_ID,
    )
    for key in (
        "workflowId",
        "status",
        "stateMachine",
        "routingPolicy",
        "transferPolicy",
        "activeWorkflowItems",
        "createdAt",
        "updatedAt",
    ):
        if key in payload:
            base[key] = payload[key]
    base["schemaVersion"] = SCHEMA_VERSION
    base["teamId"] = team_id
    base["workflowId"] = _trim_text(base.get("workflowId"), max_length=120) or DEFAULT_WORKFLOW_ID
    base["status"] = _trim_text(base.get("status"), max_length=32) or "active"
    if not isinstance(base.get("activeWorkflowItems"), list):
        base["activeWorkflowItems"] = []
    base["routingPolicy"] = _sync_owner_policy(base.get("routingPolicy"), str(base.get("ownerAgentId") or DEFAULT_OWNER_AGENT_ID))
    base["transferPolicy"] = _sync_transfer_policy(base.get("transferPolicy"), str(base.get("ownerAgentId") or DEFAULT_OWNER_AGENT_ID))
    return base


def _load_or_create_workflow(team_id: str) -> dict[str, Any]:
    path = _workflow_path(team_id)
    if path.exists():
        workflow = _repair_workflow(_read_json(path), team_id)
        _write_json(path, workflow)
        return workflow
    workflow = _default_workflow(
        team_id,
        workflow_kind=WORKFLOW_KIND_CHALLENGE_CUP_RESEARCH,
        owner_agent_id=DEFAULT_OWNER_AGENT_ID,
    )
    _write_json(path, workflow)
    _record_workflow_event(
        "workflow.created",
        team_id,
        fields={"workflowId": workflow["workflowId"], "workflowKind": workflow["workflowKind"]},
    )
    return workflow


def _load_candidate_store(team_id: str) -> dict[str, Any]:
    path = _candidate_store_path(team_id)
    if path.exists():
        payload = _read_json(path)
        if isinstance(payload.get("candidates"), list):
            return payload
    now = utc_now_iso()
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": team_id,
        "storeKind": "team_workflow_candidate_store",
        "candidates": [],
        "createdAt": now,
        "updatedAt": now,
    }
    _write_json(path, payload)
    return payload


def _load_transfer_records(team_id: str) -> list[dict[str, Any]]:
    path = _transfer_records_path(team_id)
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            records.append(payload)
    return records


def _append_transfer_record(team_id: str, transfer: dict[str, Any]) -> None:
    path = _transfer_records_path(team_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(transfer, ensure_ascii=False, sort_keys=True) + "\n")


def _write_transfer_records(team_id: str, transfers: list[dict[str, Any]]) -> None:
    path = _transfer_records_path(team_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in transfers)
    path.write_text(payload, encoding="utf-8")


def _find_candidate(candidate_store: dict[str, Any], candidate_id: str) -> dict[str, Any] | None:
    for item in list(candidate_store.get("candidates") or []):
        if isinstance(item, dict) and str(item.get("candidateId") or "") == candidate_id:
            return item
    return None


def _find_transfer(transfers: list[dict[str, Any]], transfer_id: str) -> dict[str, Any] | None:
    for item in transfers:
        if str(item.get("transferId") or "") == transfer_id:
            return item
    return None


def _upsert_active_item(
    items: Any,
    *,
    candidate_id: str,
    current_node: str,
    status: str,
    transfer_id: str,
) -> list[dict[str, Any]]:
    normalized_items = [item for item in list(items or []) if isinstance(item, dict)]
    now = utc_now_iso()
    next_item = {
        "candidateId": candidate_id,
        "currentNode": current_node,
        "status": status,
        "pendingTransferId": transfer_id,
        "updatedAt": now,
    }
    for index, item in enumerate(normalized_items):
        if str(item.get("candidateId") or "") == candidate_id:
            normalized_items[index] = {**item, **next_item}
            return normalized_items
    normalized_items.append(next_item)
    return normalized_items


def _normalize_workflow_kind(value: Any) -> str:
    normalized = _trim_text(value, max_length=80) or WORKFLOW_KIND_CHALLENGE_CUP_RESEARCH
    if normalized not in ALLOWED_WORKFLOW_KINDS:
        raise TeamWorkflowOrchestrationError("Workflow kind is not enabled.")
    return normalized


def _normalize_candidate_type(value: Any) -> str:
    normalized = _trim_text(value, max_length=80) or "source_manifest"
    if normalized not in CANDIDATE_TYPES:
        raise TeamWorkflowOrchestrationError("Candidate type is invalid.")
    return normalized


def _normalize_local_research_task_type(value: Any) -> str:
    normalized = _trim_text(value, max_length=80)
    if normalized not in LOCAL_RESEARCH_TASKS:
        raise TeamWorkflowOrchestrationError("Local research model task type is invalid.")
    return normalized


def _local_research_llm_client(model_id: str, *, llm_client_factory: Any = None) -> Any:
    normalized_model_id = _trim_text(model_id, max_length=160) or LOCAL_RESEARCH_MODEL_ID
    public_config = load_public_config()
    llm = public_config.setdefault("llm", {})
    profiles = llm.setdefault("profiles", {})
    if not isinstance(profiles, dict):
        raise TeamWorkflowOrchestrationError("llm.profiles must be an object.")
    model_library = llm.get("model_library")
    if not isinstance(model_library, dict) or normalized_model_id not in model_library:
        raise TeamWorkflowOrchestrationError(f"Local research model is not configured: {normalized_model_id}")
    profiles[LOCAL_RESEARCH_INVOKE_PROFILE_ID] = {"label": "Challenge Cup Local Research Model", "model_ref": normalized_model_id}
    config = build_effective_config(public_config)
    factory = llm_client_factory or LLMClient
    return factory(config=config, profile_id=LOCAL_RESEARCH_INVOKE_PROFILE_ID)


def _local_research_model_messages(task: dict[str, Any]) -> list[dict[str, str]]:
    user_payload = {
        "taskId": task.get("taskId", ""),
        "taskType": task.get("taskType", ""),
        "workflowNode": task.get("workflowNode", ""),
        "targetCandidateType": task.get("targetCandidateType", ""),
        "sourceRefs": task.get("sourceRefs", []),
        "evidenceRefs": task.get("evidenceRefs", []),
        "candidateRefs": task.get("candidateRefs", []),
        "excerpt": task.get("excerpt", ""),
        "outputContract": task.get("outputContract", {}),
    }
    return [
        {
            "role": "system",
            "content": _local_research_model_instruction(str(task.get("taskType") or "")),
        },
        {
            "role": "user",
            "content": (
                "Create one candidate draft for the Challenge Cup research workflow. "
                "Return exactly one JSON object and no markdown fences. "
                "Use these task inputs:\n"
                f"{json.dumps(user_payload, ensure_ascii=False, indent=2, sort_keys=True)}"
            ),
        },
    ]


def _extract_json_object_from_model_text(content: str, reasoning_content: str = "") -> tuple[dict[str, Any] | None, str]:
    for source, text in (("content", content), ("reasoning_content", reasoning_content)):
        parsed = _parse_first_json_object(text)
        if parsed is not None:
            return parsed, source
    return None, ""


def _parse_first_json_object(text: Any) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, flags=re.IGNORECASE | re.DOTALL)
    candidates = [fenced.group(1)] if fenced else []
    candidates.append(raw)
    sliced = _slice_first_json_object(raw)
    if sliced and sliced not in candidates:
        candidates.append(sliced)
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _slice_first_json_object(text: str) -> str:
    start = text.find("{")
    if start < 0:
        return ""
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return ""


def _local_research_model_instruction(task_type: str) -> str:
    task = LOCAL_RESEARCH_TASKS[_normalize_local_research_task_type(task_type)]
    return (
        f"You are {LOCAL_RESEARCH_MODEL_ROLE}. Task: {task['purpose']} "
        "Return only a JSON object. Preserve sourceRefs and evidenceRefs. "
        "Mark weak evidence as weak_evidence. Mark uncertain terminology as terminology_uncertain. "
        "For mechanism-to-algorithm analogies, separate factLayer from inferenceLayer. "
        "Do not write final review decisions, official Team Knowledge, RAG entries, or official graph sync."
    )


def _local_research_model_boundaries() -> list[str]:
    return [
        "no_official_team_knowledge_write",
        "no_official_rag_write",
        "no_official_graph_sync",
        "no_final_review_decision",
        "must_preserve_source_refs",
        "missing_evidence_requires_weak_evidence",
        "uncertain_terms_require_terminology_uncertain",
        "analogies_require_fact_layer_and_inference_layer",
    ]


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def _normalize_ref_list(value: Any, *, max_items: int) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    refs: list[dict[str, str]] = []
    for item in value[:max_items]:
        if isinstance(item, dict):
            ref_type = _trim_text(item.get("type"), max_length=80)
            ref_id = _trim_text(item.get("id"), max_length=240)
            label = _trim_text(item.get("label"), max_length=240)
            if ref_type or ref_id or label:
                refs.append({"type": ref_type, "id": ref_id, "label": label})
        else:
            label = _trim_text(item, max_length=240)
            if label:
                refs.append({"type": "text", "id": "", "label": label})
    return refs


def _normalize_text_list(value: Any, *, max_items: int, max_length: int) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value[:max_items]:
        text = _trim_text(item, max_length=max_length)
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _normalize_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        _trim_text(key, max_length=80): _normalize_metadata_value(item)
        for key, item in value.items()
        if _trim_text(key, max_length=80)
    }


def _normalize_metadata_value(value: Any) -> Any:
    if isinstance(value, str):
        return _trim_text(value, max_length=1000)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_normalize_metadata_value(item) for item in value[:24]]
    if isinstance(value, dict):
        return _normalize_metadata(value)
    return _trim_text(value, max_length=1000)


def _record_workflow_event(event_code: str, team_id: str, *, fields: dict[str, Any]) -> None:
    try:
        record_runtime_scene_event(
            "team_workflow_orchestration",
            "workflow",
            event_code,
            message=event_code,
            fields={"teamId": team_id, **fields},
        )
    except Exception:
        return


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _workflow_path(team_id: str) -> Path:
    return _team_workflow_root(team_id) / "workflow_orchestration.json"


def _candidate_store_path(team_id: str) -> Path:
    return _team_workflow_root(team_id) / "candidate_store" / "index.json"


def _transfer_records_path(team_id: str) -> Path:
    return _team_workflow_root(team_id) / "transfer_records.jsonl"


def _team_workflow_root(team_id: str) -> Path:
    return _project_root() / "workspace" / "teams" / _safe_token(team_id, default="team", max_length=96)


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
        raise TeamWorkflowOrchestrationError(message)
    return normalized


def _safe_token(value: Any, *, default: str, max_length: int) -> str:
    text = str(value or "").strip()
    if not text:
        return default
    text = _SAFE_ID_FRAGMENT.sub("-", text).strip(".-_")
    return (text or default)[:max_length]


def _trim_text(value: Any, *, max_length: int) -> str:
    text = str(value or "").strip()
    return text[:max_length]
