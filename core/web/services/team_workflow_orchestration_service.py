"""Team workflow orchestration and candidate-store service."""

from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config.public_config import build_effective_config, load_public_config
from core.llm import LLMClient
from core.web.services import team_knowledge_service, team_service
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
ARCHIVED_CANDIDATE_STATES = {"rejected", "archived"}
ARCHIVED_WORKFLOW_NODES = {"rejection_archive"}
LOCAL_RESEARCH_MODEL_ID = "houmo_qwen35_9b_agent"
LOCAL_RESEARCH_MODEL_NAME = "bossAGI-standard / qwen3.5-9b"
LOCAL_RESEARCH_MODEL_ROLE = "Local Research Worker Model"
LOCAL_RESEARCH_CONTEXT_WINDOW = 32_000
LOCAL_RESEARCH_EVIDENCE_TOKEN_TARGET = "18k-22k"
LOCAL_RESEARCH_INVOKE_PROFILE_ID = "__challenge_cup_local_research_model"
SOURCE_EXTRACTION_DEFAULT_MAX_PAGES = 24
SOURCE_EXTRACTION_HARD_MAX_PAGES = 64
SOURCE_EXTRACTION_DEFAULT_MAX_CHARS_PER_PAGE = 1800
SOURCE_EXTRACTION_HARD_MAX_CHARS_PER_PAGE = 6000
SOURCE_EXTRACTION_EXCERPT_MAX_CHARS = 12000
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


class SourceExtractionError(ValueError):
    """Raised when local source extraction cannot produce page anchors."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


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


def extract_candidate_source_pages(team_id: str, candidate_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    normalized_candidate_id = _normalize_required_id(candidate_id, "Candidate id is required.")
    team_service.get_team(normalized_team_id)
    payload = payload if isinstance(payload, dict) else {}
    created_by_agent = _trim_text(payload.get("createdByAgent"), max_length=160) or "Source Extraction Agent"
    max_pages = _normalize_int(payload.get("maxPages"), default=SOURCE_EXTRACTION_DEFAULT_MAX_PAGES, minimum=1, maximum=SOURCE_EXTRACTION_HARD_MAX_PAGES)
    max_chars_per_page = _normalize_int(
        payload.get("maxCharsPerPage"),
        default=SOURCE_EXTRACTION_DEFAULT_MAX_CHARS_PER_PAGE,
        minimum=200,
        maximum=SOURCE_EXTRACTION_HARD_MAX_CHARS_PER_PAGE,
    )
    page_scope_override = _trim_text(payload.get("pageScope"), max_length=160)
    allowed_override = _normalize_optional_bool(payload.get("allowedForAnalysis")) if "allowedForAnalysis" in payload else None
    now = utc_now_iso()
    with _WORKFLOW_LOCK:
        workflow = _load_or_create_workflow(normalized_team_id)
        candidate_store = _load_candidate_store(normalized_team_id)
        candidate = _find_candidate(candidate_store, normalized_candidate_id)
        if candidate is None:
            raise TeamWorkflowOrchestrationError("Candidate not found.")
        if str(candidate.get("candidateType") or "") != "source_manifest":
            raise TeamWorkflowOrchestrationError("Source extraction only supports source_manifest candidates.")
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        source_path = _source_manifest_path(candidate)
        if not source_path:
            raise TeamWorkflowOrchestrationError("Source manifest does not include a local sourcePath.")
        if page_scope_override:
            candidate["pageScope"] = page_scope_override
            metadata["pageScope"] = page_scope_override
        if allowed_override is not None:
            candidate["allowedForAnalysis"] = allowed_override
            metadata["allowedForAnalysis"] = allowed_override
        try:
            resolved_source_path = _resolve_source_path(source_path)
            sha256 = _sha256_file(resolved_source_path)
            page_anchors = _extract_pdf_page_anchors(
                resolved_source_path,
                page_scope=page_scope_override or _trim_text(candidate.get("pageScope") or metadata.get("pageScope"), max_length=160),
                max_pages=max_pages,
                max_chars_per_page=max_chars_per_page,
            )
            if not page_anchors:
                raise SourceExtractionError("empty_extraction", "PDF extraction produced no page text.")
            page_scope = _page_scope_from_anchors(page_anchors)
            extraction = {
                "status": "extracted",
                "sourceKind": "pdf",
                "sourcePath": str(resolved_source_path),
                "sha256": sha256,
                "pageScope": page_scope,
                "pageAnchors": page_anchors,
                "excerpt": _excerpt_from_page_anchors(page_anchors, max_chars=SOURCE_EXTRACTION_EXCERPT_MAX_CHARS),
                "extractor": "pypdf",
                "extractedByAgent": created_by_agent,
                "extractedAt": now,
                "limits": {
                    "maxPages": max_pages,
                    "maxCharsPerPage": max_chars_per_page,
                },
            }
            candidate["sha256"] = sha256
            candidate["pageScope"] = page_scope
            candidate["sourceKind"] = _trim_text(candidate.get("sourceKind"), max_length=80) or "pdf"
            metadata["sha256"] = sha256
            metadata["pageScope"] = page_scope
            metadata["sourceExtraction"] = extraction
        except SourceExtractionError as exc:
            extraction = {
                "status": "failed",
                "sourcePath": source_path,
                "errorCode": exc.code,
                "message": exc.message,
                "extractedByAgent": created_by_agent,
                "extractedAt": now,
                "limits": {
                    "maxPages": max_pages,
                    "maxCharsPerPage": max_chars_per_page,
                },
            }
            metadata["sourceExtraction"] = extraction
        candidate["metadata"] = metadata
        validation = validate_candidate_record(candidate)
        candidate["validation"] = validation
        if validation["valid"]:
            candidate["currentState"] = "source_registered"
            candidate["qualityStatus"] = "source_manifest_ready"
        else:
            candidate["currentState"] = "source_needs_confirmation"
            candidate["qualityStatus"] = "source_manifest_invalid"
        candidate["updatedAt"] = now
        candidate_store["updatedAt"] = now
        _write_json(_candidate_store_path(normalized_team_id), candidate_store)
        workflow["updatedAt"] = now
        workflow["activeWorkflowItems"] = _upsert_active_item(
            workflow.get("activeWorkflowItems"),
            candidate_id=normalized_candidate_id,
            current_node=str(candidate.get("currentWorkflowNode") or "knowledge_collection"),
            status=str(candidate.get("currentState") or ""),
            transfer_id=str(candidate.get("pendingTransferId") or ""),
        )
        _write_json(_workflow_path(normalized_team_id), workflow)
    _record_workflow_event(
        "candidate.source_extracted",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "candidateId": normalized_candidate_id,
            "status": str(extraction.get("status") or ""),
            "pageAnchorCount": len(extraction.get("pageAnchors") or []) if isinstance(extraction.get("pageAnchors"), list) else 0,
            "errorCode": str(extraction.get("errorCode") or ""),
        },
    )
    return {
        "candidate": candidate,
        "sourceExtraction": extraction,
        "validation": validation,
        "workflow": _workflow_to_api(normalized_team_id, workflow, candidate_store),
    }


def draft_paper_note_from_source_candidate(
    team_id: str,
    candidate_id: str,
    payload: dict[str, Any] | None = None,
    *,
    llm_client_factory: Any = None,
) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    normalized_candidate_id = _normalize_required_id(candidate_id, "Candidate id is required.")
    team_service.get_team(normalized_team_id)
    payload = payload if isinstance(payload, dict) else {}
    created_by_agent = _trim_text(payload.get("createdByAgent"), max_length=160) or "Paper Note Extraction Agent"
    model_id = _trim_text(payload.get("modelId"), max_length=160)
    title_override = _trim_text(payload.get("title"), max_length=240)
    summary_override = _trim_text(payload.get("summary"), max_length=4000)
    excerpt_override = _trim_text(payload.get("excerpt"), max_length=24_000)
    with _WORKFLOW_LOCK:
        candidate_store = _load_candidate_store(normalized_team_id)
        source_candidate = _find_candidate(candidate_store, normalized_candidate_id)
        if source_candidate is None:
            raise TeamWorkflowOrchestrationError("Candidate not found.")
        if str(source_candidate.get("candidateType") or "") != "source_manifest":
            raise TeamWorkflowOrchestrationError("Paper note autodraft requires a source_manifest candidate.")
        extraction = _ready_source_extraction(source_candidate)
        excerpt = excerpt_override or _trim_text(extraction.get("excerpt"), max_length=24_000)
        if not excerpt:
            raise TeamWorkflowOrchestrationError("Source extraction does not include excerpt text for paper_note drafting.")
        source_refs = [_source_manifest_source_ref(source_candidate)]
        evidence_refs = _source_extraction_evidence_refs(source_candidate, extraction)
        if not evidence_refs:
            raise TeamWorkflowOrchestrationError("Source extraction does not include page anchors for paper_note drafting.")
        candidate_refs = [
            {
                "type": "source_manifest",
                "id": normalized_candidate_id,
                "label": _source_manifest_label(source_candidate),
            }
        ]
        paper_note_title = title_override or f"paper_note draft - {_source_manifest_label(source_candidate)}"
        paper_note_summary = summary_override or f"Autodrafted from sourceExtraction pageScope {extraction.get('pageScope') or source_candidate.get('pageScope') or ''}".strip()

    invoke_response = invoke_local_research_model(
        normalized_team_id,
        {
            "taskType": "paper_note_draft",
            "modelId": model_id,
            "sourceRefs": source_refs,
            "evidenceRefs": evidence_refs,
            "candidateRefs": candidate_refs,
            "excerpt": excerpt,
            "title": paper_note_title,
            "summary": paper_note_summary,
            "createdByAgent": created_by_agent,
        },
        llm_client_factory=llm_client_factory,
    )
    paper_note_candidate = invoke_response.get("candidate") if isinstance(invoke_response.get("candidate"), dict) else {}
    validation = invoke_response.get("validation") if isinstance(invoke_response.get("validation"), dict) else {"valid": False, "issues": []}
    task = invoke_response.get("task") if isinstance(invoke_response.get("task"), dict) else {}
    now = utc_now_iso()
    with _WORKFLOW_LOCK:
        workflow = _load_or_create_workflow(normalized_team_id)
        candidate_store = _load_candidate_store(normalized_team_id)
        source_candidate = _find_candidate(candidate_store, normalized_candidate_id)
        if source_candidate is not None:
            metadata = source_candidate.get("metadata") if isinstance(source_candidate.get("metadata"), dict) else {}
            drafts = metadata.get("paperNoteDrafts") if isinstance(metadata.get("paperNoteDrafts"), list) else []
            draft_record = {
                "candidateId": str(paper_note_candidate.get("candidateId") or ""),
                "taskId": str(task.get("taskId") or ""),
                "status": "drafted" if validation.get("valid") is True else "needs_revision",
                "createdByAgent": created_by_agent,
                "createdAt": now,
                "sourceExtractionSha256": str(extraction.get("sha256") or source_candidate.get("sha256") or ""),
                "pageScope": str(extraction.get("pageScope") or source_candidate.get("pageScope") or ""),
            }
            metadata["paperNoteDrafts"] = [*drafts[-23:], draft_record]
            source_candidate["metadata"] = metadata
            source_candidate["updatedAt"] = now
            candidate_store["updatedAt"] = now
            _write_json(_candidate_store_path(normalized_team_id), candidate_store)
        else:
            source_candidate = {}
    _record_workflow_event(
        "candidate.paper_note_autodrafted",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "sourceCandidateId": normalized_candidate_id,
            "paperNoteCandidateId": str(paper_note_candidate.get("candidateId") or ""),
            "valid": validation.get("valid") is True,
            "issueCount": len(validation.get("issues") or []) if isinstance(validation.get("issues"), list) else 0,
        },
    )
    invoke_response["sourceCandidate"] = source_candidate
    invoke_response["workflow"] = _workflow_to_api(normalized_team_id, workflow, candidate_store)
    return invoke_response


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


def get_knowledge_ingestion_status(team_id: str) -> dict[str, Any]:
    """Return a read-only status view for the Challenge Cup knowledge ingestion funnel."""

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
                "currentWorkflowNode": str(candidate.get("currentWorkflowNode") or ""),
                "currentState": str(candidate.get("currentState") or ""),
                "qualityStatus": str(candidate.get("qualityStatus") or ""),
                "validation": validate_candidate_record(candidate),
            }
            for candidate in candidates
        ]
        active_graph_candidates = [
            item
            for item in candidates
            if str(item.get("candidateType") or "") != "candidate_graph" and not _candidate_is_archived(item)
        ]
        archived_candidates = [
            item
            for item in candidates
            if str(item.get("candidateType") or "") != "candidate_graph" and _candidate_is_archived(item)
        ]
        candidate_graph = _build_candidate_graph_payload(normalized_team_id, workflow["workflowId"], active_graph_candidates)
        candidate_graph["summary"]["archivedCandidateCount"] = len(archived_candidates)

    try:
        knowledge_overview = team_knowledge_service.list_team_knowledge_bases(normalized_team_id)
    except (team_knowledge_service.TeamKnowledgeError, team_knowledge_service.TeamKnowledgeNotFoundError) as exc:
        raise TeamWorkflowOrchestrationError(str(exc)) from exc

    candidate_summary = _knowledge_ingestion_candidate_summary(candidates, candidate_reports, candidate_graph)
    knowledge_summary = _knowledge_ingestion_knowledge_summary(knowledge_overview)
    stages = _knowledge_ingestion_stages(candidate_summary, knowledge_summary)
    action_items = _knowledge_ingestion_action_items(candidates, candidate_reports, candidate_graph, candidate_summary, knowledge_summary)
    overall_status = _knowledge_ingestion_overall_status(stages, action_items, candidate_summary, knowledge_summary)
    summary = {
        **candidate_summary,
        **knowledge_summary,
        "actionItemCount": len(action_items),
    }
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "workflowId": workflow["workflowId"],
        "workflowKind": workflow["workflowKind"],
        "status": overall_status,
        "summary": summary,
        "stages": stages,
        "actionItems": action_items,
        "candidateBreakdown": _candidate_breakdown(candidates),
        "candidateGraphSummary": candidate_graph["summary"],
        "officialBoundary": {
            "candidateStoreOfficialState": "candidate_only_until_steward_approval",
            "teamKnowledgeRequiresReview": True,
            "candidateGraphWritesOfficialGraph": False,
            "formalKnowledgeItemCreated": summary["formalKnowledgeItemCount"] > 0,
            "writesOfficialKnowledge": summary["officialSyncedCandidateCount"] > 0,
            "writesOfficialRag": False,
            "writesOfficialGraph": summary["officialGraphSyncedCandidateCount"] > 0,
            "graphStatus": "official_research_trace_synced"
            if summary["officialGraphSyncedCandidateCount"] > 0
            else "candidate_graph_preview_only",
            "ragStatus": "queryable_via_reviewed_team_knowledge"
            if summary["formalKnowledgeItemCount"] > 0
            else "not_synced",
        },
        "knowledgeBases": _knowledge_ingestion_knowledge_bases(knowledge_overview),
        "storage": {
            "workflowPath": _relative_path(_workflow_path(normalized_team_id)),
            "candidateStorePath": _relative_path(_candidate_store_path(normalized_team_id)),
            "transferRecordsPath": _relative_path(_transfer_records_path(normalized_team_id)),
        },
        "updatedAt": utc_now_iso(),
    }
    _record_workflow_event(
        "knowledge_ingestion.status_viewed",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "status": overall_status,
            "candidateCount": summary["candidateCount"],
            "pendingProposalCount": summary["pendingProposalCount"],
            "formalKnowledgeItemCount": summary["formalKnowledgeItemCount"],
            "actionItemCount": summary["actionItemCount"],
        },
    )
    return payload


def get_team_workflow_coordination_status(team_id: str) -> dict[str, Any]:
    """Return a read-only coordination queue for the Challenge Cup research workflow."""

    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    team_service.get_team(normalized_team_id)
    with _WORKFLOW_LOCK:
        workflow = _load_or_create_workflow(normalized_team_id)
        candidate_store = _load_candidate_store(normalized_team_id)
        transfers = _load_transfer_records(normalized_team_id)
        candidates = [item for item in list(candidate_store.get("candidates") or []) if isinstance(item, dict)]

    validation_reports = {str(candidate.get("candidateId") or ""): validate_candidate_record(candidate) for candidate in candidates}
    requested_transfers = [transfer for transfer in transfers if str(transfer.get("status") or "") == "requested"]
    active_candidates = [candidate for candidate in candidates if str(candidate.get("candidateType") or "") != "candidate_graph" and not _candidate_is_archived(candidate)]
    archived_candidates = [candidate for candidate in candidates if str(candidate.get("candidateType") or "") != "candidate_graph" and _candidate_is_archived(candidate)]
    queues = _coordination_queues(active_candidates, requested_transfers, validation_reports)
    summary = _coordination_summary(active_candidates, archived_candidates, requested_transfers, queues)
    action_items = _coordination_action_items(summary, queues)
    status = _coordination_status(summary, action_items)
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "workflowId": workflow["workflowId"],
        "workflowKind": workflow["workflowKind"],
        "status": status,
        "ownerAgentId": workflow.get("ownerAgentId") or DEFAULT_OWNER_AGENT_ID,
        "summary": summary,
        "queues": queues,
        "actionItems": action_items,
        "coordinationPolicy": {
            "coordinationAgentId": str(workflow.get("routingPolicy", {}).get("coordinationAgentId") or workflow.get("ownerAgentId") or DEFAULT_OWNER_AGENT_ID),
            "organizingAgentId": str(workflow.get("ownerAgentId") or DEFAULT_OWNER_AGENT_ID),
            "functionalAgentsMayRequestTransfer": bool(workflow.get("routingPolicy", {}).get("functionalAgentsMayRequestTransfer")),
            "requiresUserConfirmation": bool(workflow.get("transferPolicy", {}).get("requiresUserConfirmation")),
            "finalStateWriter": str(workflow.get("routingPolicy", {}).get("finalStateWriter") or workflow.get("ownerAgentId") or DEFAULT_OWNER_AGENT_ID),
            "readOnlyStatus": True,
            "autoTransferEnabled": False,
        },
        "storage": {
            "workflowPath": _relative_path(_workflow_path(normalized_team_id)),
            "candidateStorePath": _relative_path(_candidate_store_path(normalized_team_id)),
            "transferRecordsPath": _relative_path(_transfer_records_path(normalized_team_id)),
        },
        "updatedAt": utc_now_iso(),
    }
    _record_workflow_event(
        "coordination.status_viewed",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "status": status,
            "activeCandidateCount": summary["activeCandidateCount"],
            "pendingTransferCount": summary["pendingTransferCount"],
            "reworkCandidateCount": summary["reworkCandidateCount"],
            "blockedCandidateCount": summary["blockedCandidateCount"],
            "actionItemCount": summary["actionItemCount"],
        },
    )
    return payload


def build_candidate_graph(team_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    team_service.get_team(normalized_team_id)
    payload = payload if isinstance(payload, dict) else {}
    now = utc_now_iso()
    with _WORKFLOW_LOCK:
        workflow = _load_or_create_workflow(normalized_team_id)
        candidate_store = _load_candidate_store(normalized_team_id)
        all_candidates = [
            item
            for item in list(candidate_store.get("candidates") or [])
            if isinstance(item, dict) and str(item.get("candidateType") or "") != "candidate_graph"
        ]
        archived_candidates = [item for item in all_candidates if _candidate_is_archived(item)]
        candidates = [item for item in all_candidates if not _candidate_is_archived(item)]
        graph = _build_candidate_graph_payload(normalized_team_id, workflow["workflowId"], candidates)
        graph["summary"]["archivedCandidateCount"] = len(archived_candidates)
        record = {
            "schemaVersion": SCHEMA_VERSION,
            "candidateId": _new_record_id("candidate-graph"),
            "candidateType": "candidate_graph",
            "teamId": normalized_team_id,
            "workflowId": workflow["workflowId"],
            "title": _trim_text(payload.get("title"), max_length=240) or "Candidate graph snapshot",
            "sourceKind": "candidate_graph_builder",
            "summary": (
                f"{len(graph['nodes'])} nodes, {len(graph['edges'])} edges, "
                f"{len(graph['missingLinks'])} missing links, {len(archived_candidates)} archived"
            ),
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
            "archivedCandidateCount": len(archived_candidates),
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
                "targetState": _trim_text(payload.get("targetState"), max_length=120),
                "decisionMetadata": _normalize_metadata(payload.get("metadata")),
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
            current_node = target_node or current_node
            candidate["currentWorkflowNode"] = current_node
            candidate["currentState"] = _trim_text(payload.get("targetState"), max_length=120) or "returned_for_rework"
            candidate["qualityStatus"] = "needs_revision"
            candidate["lastTransferId"] = normalized_transfer_id
            candidate.pop("pendingTransferId", None)
        else:
            current_node = "rejection_archive"
            candidate["currentWorkflowNode"] = current_node
            candidate["currentState"] = "rejected"
            candidate["qualityStatus"] = "rejected"
            candidate["lastTransferId"] = normalized_transfer_id
            metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
            metadata["rejectionArchive"] = {
                "status": "archived",
                "transferId": normalized_transfer_id,
                "fromNode": transfer.get("fromNode", ""),
                "toNode": transfer.get("toNode", ""),
                "reason": transfer.get("reason", ""),
                "decisionNote": transfer.get("decisionNote", ""),
                "decidedByAgent": decided_by_agent,
                "archivedAt": now,
                "reopenRequiresTransfer": True,
            }
            candidate["metadata"] = metadata
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
                "targetState": candidate["currentState"],
                "metadata": transfer.get("metadata", {}),
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
            "targetState": candidate["currentState"],
            "archiveStatus": "archived" if decision == "rejected" else "",
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


def submit_steward_pack_to_knowledge_ingestion(team_id: str, candidate_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    normalized_candidate_id = _normalize_required_id(candidate_id, "Candidate id is required.")
    team_service.get_team(normalized_team_id)
    knowledge_base_id = _normalize_required_id(payload.get("knowledgeBaseId"), "Knowledge base id is required.")
    proposed_by_agent_id = _normalize_required_id(payload.get("proposedByAgentId"), "Proposed by Agent id is required.")

    with _WORKFLOW_LOCK:
        workflow = _load_or_create_workflow(normalized_team_id)
        candidate_store = _load_candidate_store(normalized_team_id)
        candidate = _find_candidate(candidate_store, normalized_candidate_id)
        if candidate is None:
            raise TeamWorkflowOrchestrationError("Steward pack candidate not found.")
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        task_type = str(metadata.get("taskType") or "")
        output = metadata.get("output") if isinstance(metadata.get("output"), dict) else {}
        if task_type != "steward_pack_draft" or str(candidate.get("currentState") or "") != "steward_pack_draft":
            raise TeamWorkflowOrchestrationError("Only steward_pack_draft candidates can be submitted to knowledge ingestion.")
        validation = validate_local_research_model_output("steward_pack_draft", output)
        if not validation["valid"]:
            raise TeamWorkflowOrchestrationError("Steward pack candidate must be valid before knowledge ingestion submission.")

    ingestion_payload = _steward_pack_ingestion_payload(
        normalized_team_id,
        candidate,
        output,
        proposed_by_agent_id=proposed_by_agent_id,
    )
    try:
        ingestion_package = team_knowledge_service.create_ingestion_package(
            knowledge_base_id,
            source_type="agent_authored",
            source_ref=ingestion_payload["sourceRef"],
            source_created_at=str(candidate.get("createdAt") or ""),
            captured_by=proposed_by_agent_id,
            evidence_range=ingestion_payload["evidenceRange"],
            source_title=ingestion_payload["sourceTitle"],
            source_summary=ingestion_payload["sourceSummary"],
            excerpt=ingestion_payload["excerpt"],
            proposed_by_agent_id=proposed_by_agent_id,
            proposal_title=ingestion_payload["proposalTitle"],
            proposal_summary=ingestion_payload["proposalSummary"],
            proposal_content=ingestion_payload["proposalContent"],
            tags=ingestion_payload["tags"],
        )
    except (team_knowledge_service.TeamKnowledgeError, team_knowledge_service.TeamKnowledgeNotFoundError) as exc:
        raise TeamWorkflowOrchestrationError(str(exc)) from exc

    rating_result: dict[str, Any] | None = None
    rating_payload = _steward_pack_rating_suggestion_payload(output, ingestion_package.get("proposal"), proposed_by_agent_id)
    if rating_payload is not None:
        try:
            rating_result = team_knowledge_service.create_rating_suggestion(knowledge_base_id, **rating_payload)
        except team_knowledge_service.TeamKnowledgeError:
            rating_result = None

    now = utc_now_iso()
    with _WORKFLOW_LOCK:
        workflow = _load_or_create_workflow(normalized_team_id)
        candidate_store = _load_candidate_store(normalized_team_id)
        candidate = _find_candidate(candidate_store, normalized_candidate_id)
        if candidate is None:
            raise TeamWorkflowOrchestrationError("Steward pack candidate not found after ingestion submission.")
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        metadata["knowledgeIngestion"] = {
            "status": "pending_review",
            "knowledgeBaseId": knowledge_base_id,
            "sourceArtifactId": str((ingestion_package.get("sourceArtifact") or {}).get("sourceArtifactId") or ""),
            "proposalId": str((ingestion_package.get("proposal") or {}).get("proposalId") or ""),
            "ratingSuggestionId": str((rating_result or {}).get("suggestionId") or ""),
            "submittedByAgentId": proposed_by_agent_id,
            "submittedAt": now,
            "writesOfficialKnowledge": False,
            "writesOfficialRag": False,
            "writesOfficialGraph": False,
        }
        candidate["metadata"] = metadata
        candidate["currentState"] = "steward_pending_knowledge_review"
        candidate["qualityStatus"] = "pending_knowledge_review"
        candidate["updatedAt"] = now
        candidate_store["updatedAt"] = now
        _write_json(_candidate_store_path(normalized_team_id), candidate_store)
        workflow["updatedAt"] = now
        workflow["activeWorkflowItems"] = _upsert_active_item(
            workflow.get("activeWorkflowItems"),
            candidate_id=normalized_candidate_id,
            current_node=str(candidate.get("currentWorkflowNode") or "steward_ingestion"),
            status=str(candidate.get("currentState") or "steward_pending_knowledge_review"),
            transfer_id="",
        )
        _write_json(_workflow_path(normalized_team_id), workflow)

    _record_workflow_event(
        "steward_pack.knowledge_ingestion_submitted",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "candidateId": normalized_candidate_id,
            "knowledgeBaseId": knowledge_base_id,
            "proposalId": str((ingestion_package.get("proposal") or {}).get("proposalId") or ""),
            "sourceArtifactId": str((ingestion_package.get("sourceArtifact") or {}).get("sourceArtifactId") or ""),
            "ratingSuggestionCreated": rating_result is not None,
        },
    )
    return {
        "candidate": candidate,
        "knowledgeIngestion": {
            "status": "pending_review",
            "package": ingestion_package,
            "ratingSuggestion": rating_result,
            "officialBoundary": {
                "writesOfficialKnowledge": False,
                "writesOfficialRag": False,
                "writesOfficialGraph": False,
            },
        },
        "workflow": _workflow_to_api(normalized_team_id, workflow, candidate_store),
    }


def review_steward_pack_knowledge_ingestion(team_id: str, candidate_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    normalized_candidate_id = _normalize_required_id(candidate_id, "Candidate id is required.")
    team_service.get_team(normalized_team_id)
    knowledge_base_id = _normalize_required_id(payload.get("knowledgeBaseId"), "Knowledge base id is required.")
    reviewed_by_agent_id = _normalize_required_id(payload.get("reviewedByAgentId"), "Reviewed by Agent id is required.")
    decision = _normalize_steward_review_decision(payload.get("decision"))
    resolution_note = _trim_text(payload.get("resolutionNote"), max_length=2000)

    with _WORKFLOW_LOCK:
        workflow = _load_or_create_workflow(normalized_team_id)
        candidate_store = _load_candidate_store(normalized_team_id)
        candidate = _find_candidate(candidate_store, normalized_candidate_id)
        if candidate is None:
            raise TeamWorkflowOrchestrationError("Steward pack candidate not found.")
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        ingestion = metadata.get("knowledgeIngestion") if isinstance(metadata.get("knowledgeIngestion"), dict) else {}
        if str(candidate.get("currentState") or "") != "steward_pending_knowledge_review":
            raise TeamWorkflowOrchestrationError("Only steward_pending_knowledge_review candidates can be reviewed by the ingestion approval gate.")
        if str(ingestion.get("knowledgeBaseId") or "") != knowledge_base_id:
            raise TeamWorkflowOrchestrationError("Knowledge base id does not match the steward pack ingestion record.")
        proposal_id = str(ingestion.get("proposalId") or "").strip()
        if not proposal_id:
            raise TeamWorkflowOrchestrationError("Steward pack ingestion record is missing proposalId.")
        output = metadata.get("output") if isinstance(metadata.get("output"), dict) else {}

    review_status = "applied" if decision == "approved" else "rejected"
    try:
        review_result = team_knowledge_service.review_refinement_proposal(
            knowledge_base_id,
            proposal_id,
            status=review_status,
            reviewed_by_agent_id=reviewed_by_agent_id,
            resolution_note=resolution_note,
        )
    except (team_knowledge_service.TeamKnowledgeError, team_knowledge_service.TeamKnowledgeNotFoundError) as exc:
        raise TeamWorkflowOrchestrationError(str(exc)) from exc

    now = utc_now_iso()
    item = review_result.get("item") if isinstance(review_result.get("item"), dict) else None
    batch = review_result.get("batch") if isinstance(review_result.get("batch"), dict) else None
    proposal = review_result.get("proposal") if isinstance(review_result.get("proposal"), dict) else {}
    knowledge_item_ids = [str(item.get("knowledgeItemId") or "")] if item else []
    knowledge_item_ids = [item_id for item_id in knowledge_item_ids if item_id]
    batch_id = str((batch or {}).get("batchId") or "")
    official_research_graph = _official_research_graph_record(
        output,
        knowledge_item_ids=knowledge_item_ids,
        proposal_id=proposal_id,
        batch_id=batch_id,
        knowledge_base_id=knowledge_base_id,
        reviewed_by_agent_id=reviewed_by_agent_id,
        reviewed_at=now,
        decision=decision,
    )
    if decision == "approved" and item and official_research_graph["status"] == "synced":
        try:
            item = team_knowledge_service.update_knowledge_item_metadata(
                knowledge_base_id,
                knowledge_item_ids[0],
                metadata_patch={"officialResearchGraph": official_research_graph},
                actor_agent_id=reviewed_by_agent_id,
            )
            review_result["item"] = item
        except (team_knowledge_service.TeamKnowledgeError, team_knowledge_service.TeamKnowledgeNotFoundError) as exc:
            official_research_graph = {
                **official_research_graph,
                "status": "metadata_update_failed",
                "error": str(exc),
            }
    if decision == "approved":
        rating_migration = _migrate_steward_pack_rating_suggestion(
            knowledge_base_id,
            source_suggestion_id=str(ingestion.get("ratingSuggestionId") or ""),
            knowledge_item_id=knowledge_item_ids[0] if knowledge_item_ids else "",
            reviewed_by_agent_id=reviewed_by_agent_id,
            resolution_note=resolution_note,
        )
    else:
        rating_migration = {
            "status": "skipped",
            "reason": "decision_not_approved",
            "sourceSuggestionId": str(ingestion.get("ratingSuggestionId") or ""),
            "targetSuggestionId": "",
            "knowledgeItemId": "",
        }
    writes_official_graph = decision == "approved" and str(official_research_graph.get("status") or "") == "synced"
    next_state = "official_synced" if decision == "approved" else "steward_needs_revision"
    quality_status = "approved" if decision == "approved" else "rejected_by_gate"
    official_record = {
        "status": "official_synced" if decision == "approved" else "rejected_by_gate",
        "decision": decision,
        "knowledgeBaseId": knowledge_base_id,
        "proposalId": proposal_id,
        "batchId": batch_id,
        "knowledgeItemIds": knowledge_item_ids,
        "ratingSuggestionId": str(ingestion.get("ratingSuggestionId") or ""),
        "ratingSuggestionMigration": rating_migration,
        "officialResearchGraph": official_research_graph,
        "reviewedByAgentId": reviewed_by_agent_id,
        "reviewedAt": now,
        "resolutionNote": resolution_note,
        "formalKnowledgeItemCreated": decision == "approved" and bool(knowledge_item_ids),
        "writesOfficialKnowledge": decision == "approved",
        "writesOfficialRag": False,
        "writesOfficialGraph": writes_official_graph,
        "ragStatus": "queryable_via_reviewed_team_knowledge" if decision == "approved" else "not_synced",
        "graphStatus": "official_research_trace_synced" if writes_official_graph else ("visible_via_memory_knowledge_graph" if decision == "approved" else "not_synced"),
    }

    with _WORKFLOW_LOCK:
        workflow = _load_or_create_workflow(normalized_team_id)
        candidate_store = _load_candidate_store(normalized_team_id)
        candidate = _find_candidate(candidate_store, normalized_candidate_id)
        if candidate is None:
            raise TeamWorkflowOrchestrationError("Steward pack candidate not found after approval gate review.")
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        ingestion = metadata.get("knowledgeIngestion") if isinstance(metadata.get("knowledgeIngestion"), dict) else {}
        ingestion.update(
            {
                "status": official_record["status"],
                "decision": decision,
                "proposalStatus": str(proposal.get("status") or ""),
                "batchId": batch_id,
                "knowledgeItemIds": knowledge_item_ids,
                "ratingSuggestionMigration": rating_migration,
                "officialResearchGraph": official_research_graph,
                "reviewedByAgentId": reviewed_by_agent_id,
                "reviewedAt": now,
                "resolutionNote": resolution_note,
                "writesOfficialKnowledge": decision == "approved",
                "writesOfficialRag": False,
                "writesOfficialGraph": writes_official_graph,
            }
        )
        metadata["knowledgeIngestion"] = ingestion
        metadata["officialSyncRecord"] = official_record
        candidate["metadata"] = metadata
        candidate["currentState"] = next_state
        candidate["qualityStatus"] = quality_status
        candidate["updatedAt"] = now
        candidate_store["updatedAt"] = now
        _write_json(_candidate_store_path(normalized_team_id), candidate_store)
        workflow["updatedAt"] = now
        workflow["activeWorkflowItems"] = _upsert_active_item(
            workflow.get("activeWorkflowItems"),
            candidate_id=normalized_candidate_id,
            current_node=str(candidate.get("currentWorkflowNode") or "steward_ingestion"),
            status=str(candidate.get("currentState") or next_state),
            transfer_id="",
        )
        _write_json(_workflow_path(normalized_team_id), workflow)

    _record_workflow_event(
        "steward_pack.knowledge_ingestion_reviewed",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "candidateId": normalized_candidate_id,
            "knowledgeBaseId": knowledge_base_id,
            "proposalId": proposal_id,
            "decision": decision,
            "knowledgeItemCount": len(knowledge_item_ids),
            "ratingSuggestionMigrationStatus": str(rating_migration.get("status") or ""),
            "officialResearchGraphStatus": str(official_research_graph.get("status") or ""),
            "officialResearchGraphEdgeCount": int((official_research_graph.get("summary") or {}).get("edgeCount") or 0),
        },
    )
    return {
        "candidate": candidate,
        "knowledgeIngestion": {
            "status": official_record["status"],
            "decision": decision,
            "review": review_result,
            "officialSyncRecord": official_record,
        },
        "workflow": _workflow_to_api(normalized_team_id, workflow, candidate_store),
    }


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


def _candidate_is_archived(candidate: dict[str, Any]) -> bool:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    rejection_archive = metadata.get("rejectionArchive") if isinstance(metadata.get("rejectionArchive"), dict) else {}
    return (
        str(candidate.get("currentState") or "") in ARCHIVED_CANDIDATE_STATES
        or str(candidate.get("currentWorkflowNode") or "") in ARCHIVED_WORKFLOW_NODES
        or str(rejection_archive.get("status") or "") == "archived"
    )


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


def _source_manifest_path(candidate: dict[str, Any]) -> str:
    source_path = _trim_text(candidate.get("sourcePath"), max_length=2000)
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    metadata_path = _trim_text(metadata.get("path") or metadata.get("sourcePath"), max_length=2000)
    return source_path or metadata_path


def _source_manifest_label(candidate: dict[str, Any]) -> str:
    return (
        _trim_text(candidate.get("title"), max_length=240)
        or _trim_text(candidate.get("sourceUrl"), max_length=240)
        or _trim_text(candidate.get("sourcePath"), max_length=240)
        or _trim_text(candidate.get("candidateId"), max_length=128)
        or "source_manifest"
    )


def _knowledge_ingestion_candidate_summary(
    candidates: list[dict[str, Any]],
    candidate_reports: list[dict[str, Any]],
    candidate_graph: dict[str, Any],
) -> dict[str, int]:
    non_graph_candidates = [item for item in candidates if str(item.get("candidateType") or "") != "candidate_graph"]
    source_candidates = [item for item in non_graph_candidates if str(item.get("candidateType") or "") == "source_manifest"]
    source_ready = [
        item
        for item in source_candidates
        if str(item.get("qualityStatus") or "") == "source_manifest_ready"
        or str(item.get("currentState") or "") in {"source_registered", "screening_ready"}
    ]
    local_candidates = [
        item
        for item in non_graph_candidates
        if str(item.get("candidateType") or "") in {"paper_note", "neuro_mechanism", "mechanism_mapping", "algorithm_hypothesis", "review_record"}
    ]
    steward_candidates = [
        item
        for item in non_graph_candidates
        if str(item.get("currentWorkflowNode") or "") == "steward_ingestion"
        or str((item.get("metadata") if isinstance(item.get("metadata"), dict) else {}).get("taskType") or "") == "steward_pack_draft"
    ]
    pending_ingestion = [item for item in non_graph_candidates if _candidate_knowledge_ingestion_status(item) == "pending_review"]
    official_synced = [item for item in non_graph_candidates if str(item.get("currentState") or "") == "official_synced"]
    official_graph_synced = [
        item
        for item in official_synced
        if bool(
            ((item.get("metadata") if isinstance(item.get("metadata"), dict) else {}).get("officialSyncRecord") or {}).get(
                "writesOfficialGraph"
            )
        )
    ]
    archived_count = sum(1 for item in non_graph_candidates if _candidate_is_archived(item))
    invalid_count = sum(1 for item in candidate_reports if not bool((item.get("validation") or {}).get("valid")))
    return {
        "candidateCount": len(non_graph_candidates),
        "sourceCandidateCount": len(source_candidates),
        "sourceReadyCount": len(source_ready),
        "localDraftCandidateCount": len(local_candidates),
        "stewardPackCandidateCount": len(steward_candidates),
        "pendingKnowledgeReviewCandidateCount": len(pending_ingestion),
        "officialSyncedCandidateCount": len(official_synced),
        "officialGraphSyncedCandidateCount": len(official_graph_synced),
        "archivedCandidateCount": archived_count,
        "invalidCandidateCount": invalid_count,
        "missingLinkCount": int((candidate_graph.get("summary") or {}).get("missingLinkCount") or 0),
        "unreviewedNodeCount": int((candidate_graph.get("summary") or {}).get("unreviewedNodeCount") or 0),
    }


def _knowledge_ingestion_knowledge_summary(knowledge_overview: dict[str, Any]) -> dict[str, int]:
    bases = [item for item in list(knowledge_overview.get("knowledgeBases") or []) if isinstance(item, dict)]
    pending_proposals = 0
    proposal_count = 0
    formal_items = 0
    source_artifacts = 0
    for base in bases:
        stats = base.get("stats") if isinstance(base.get("stats"), dict) else {}
        pending_proposals += int(stats.get("pendingProposalCount") or 0)
        proposal_count += int(stats.get("proposalCount") or 0)
        formal_items += int(stats.get("itemCount") or 0)
        source_artifacts += int(stats.get("sourceArtifactCount") or 0)
    return {
        "knowledgeBaseCount": len(bases),
        "sourceArtifactCount": source_artifacts,
        "proposalCount": proposal_count,
        "pendingProposalCount": pending_proposals,
        "formalKnowledgeItemCount": formal_items,
    }


def _knowledge_ingestion_stages(candidate_summary: dict[str, int], knowledge_summary: dict[str, int]) -> list[dict[str, Any]]:
    return [
        _knowledge_ingestion_stage(
            "source_collection",
            "知识搜集",
            candidate_summary["sourceCandidateCount"],
            ready=candidate_summary["sourceReadyCount"] > 0,
            warning=candidate_summary["invalidCandidateCount"] > 0,
            blocked=candidate_summary["sourceCandidateCount"] == 0,
            next_action="register_candidate_source",
            reason="至少需要一个可分析的来源候选。",
        ),
        _knowledge_ingestion_stage(
            "candidate_screening",
            "候选筛选",
            candidate_summary["localDraftCandidateCount"],
            ready=candidate_summary["localDraftCandidateCount"] > 0,
            warning=candidate_summary["unreviewedNodeCount"] > 0 or candidate_summary["missingLinkCount"] > 0,
            blocked=candidate_summary["sourceReadyCount"] == 0,
            next_action="run_local_research_model_tasks",
            reason="需要从来源生成 paper_note、机制、映射、算法假设或预审记录。",
        ),
        _knowledge_ingestion_stage(
            "steward_pack",
            "入库包生成",
            candidate_summary["stewardPackCandidateCount"],
            ready=candidate_summary["stewardPackCandidateCount"] > 0,
            warning=candidate_summary["pendingKnowledgeReviewCandidateCount"] > 0,
            blocked=candidate_summary["localDraftCandidateCount"] == 0,
            next_action="draft_steward_pack",
            reason="需要由知识治理边界生成 steward pack，不能直接写正式知识。",
        ),
        _knowledge_ingestion_stage(
            "knowledge_review",
            "共享记忆审核",
            knowledge_summary["proposalCount"],
            ready=knowledge_summary["formalKnowledgeItemCount"] > 0,
            warning=knowledge_summary["pendingProposalCount"] > 0,
            blocked=candidate_summary["stewardPackCandidateCount"] > 0 and knowledge_summary["proposalCount"] == 0,
            next_action="submit_or_review_refinement_proposal",
            reason="正式团队共享记忆必须经 refinement proposal 审核。",
        ),
        _knowledge_ingestion_stage(
            "official_sync",
            "图谱同步边界",
            candidate_summary["officialSyncedCandidateCount"],
            ready=candidate_summary["officialGraphSyncedCandidateCount"] > 0,
            warning=knowledge_summary["formalKnowledgeItemCount"] > 0
            and candidate_summary["officialGraphSyncedCandidateCount"] == 0,
            blocked=knowledge_summary["formalKnowledgeItemCount"] == 0,
            next_action="approve_steward_ingestion_gate",
            reason="候选图只是预览，正式图谱同步只来自审核后的知识项元数据。",
        ),
    ]


def _knowledge_ingestion_stage(
    stage_id: str,
    label: str,
    count: int,
    *,
    ready: bool,
    warning: bool,
    blocked: bool,
    next_action: str,
    reason: str,
) -> dict[str, Any]:
    if blocked:
        status_value = "blocked"
    elif ready and warning:
        status_value = "needs_review"
    elif ready:
        status_value = "ready"
    elif warning:
        status_value = "needs_review"
    else:
        status_value = "pending"
    return {
        "stageId": stage_id,
        "label": label,
        "status": status_value,
        "count": count,
        "nextAction": next_action if status_value != "ready" else "",
        "reason": "" if status_value == "ready" else reason,
    }


def _knowledge_ingestion_action_items(
    candidates: list[dict[str, Any]],
    candidate_reports: list[dict[str, Any]],
    candidate_graph: dict[str, Any],
    candidate_summary: dict[str, int],
    knowledge_summary: dict[str, int],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if candidate_summary["sourceCandidateCount"] == 0:
        items.append(
            _knowledge_ingestion_action_item(
                "source_collection_empty",
                "blocked",
                "知识搜集还没有候选来源。",
                "register_candidate_source",
                "knowledge_collection",
            )
        )
    for report in candidate_reports:
        validation = report.get("validation") if isinstance(report.get("validation"), dict) else {}
        if bool(validation.get("valid")):
            continue
        items.append(
            _knowledge_ingestion_action_item(
                "candidate_validation_failed",
                "needs_revision",
                f"{report.get('candidateType') or 'candidate'} has validation issues.",
                "repair_candidate_record",
                str(report.get("currentWorkflowNode") or ""),
                candidateId=str(report.get("candidateId") or ""),
                issueCount=len(validation.get("issues") or []) if isinstance(validation.get("issues"), list) else 0,
            )
        )
    if candidate_summary["missingLinkCount"] > 0:
        items.append(
            _knowledge_ingestion_action_item(
                "candidate_graph_missing_links",
                "needs_evidence",
                "候选图存在缺失引用，进入正式入库前需要补齐来源链。",
                "repair_candidate_graph_links",
                "candidate_graph",
                issueCount=candidate_summary["missingLinkCount"],
            )
        )
    if candidate_summary["unreviewedNodeCount"] > 0:
        items.append(
            _knowledge_ingestion_action_item(
                "candidate_graph_unreviewed_nodes",
                "needs_review",
                "候选图仍有需要预审或正式审核的节点。",
                "run_review_prefilter",
                "research_review",
                issueCount=candidate_summary["unreviewedNodeCount"],
            )
        )
    pending_candidates = [
        item
        for item in candidates
        if str(item.get("candidateType") or "") != "candidate_graph" and _candidate_knowledge_ingestion_status(item) == "pending_review"
    ]
    for candidate in pending_candidates[:12]:
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        ingestion = metadata.get("knowledgeIngestion") if isinstance(metadata.get("knowledgeIngestion"), dict) else {}
        items.append(
            _knowledge_ingestion_action_item(
                "knowledge_proposal_pending_review",
                "needs_review",
                "入库包已经提交，但共享记忆仍在审核队列。",
                "review_refinement_proposal",
                "steward_ingestion",
                candidateId=str(candidate.get("candidateId") or ""),
                proposalId=str(ingestion.get("proposalId") or ""),
                knowledgeBaseId=str(ingestion.get("knowledgeBaseId") or ""),
            )
        )
    if candidate_summary["stewardPackCandidateCount"] > 0 and knowledge_summary["proposalCount"] == 0:
        items.append(
            _knowledge_ingestion_action_item(
                "steward_pack_not_submitted",
                "pending",
                "已有 steward pack 候选，但尚未进入团队知识库 proposal 队列。",
                "submit_steward_pack_to_knowledge_ingestion",
                "steward_ingestion",
            )
        )
    if knowledge_summary["formalKnowledgeItemCount"] > 0 and candidate_summary["officialGraphSyncedCandidateCount"] == 0:
        items.append(
            _knowledge_ingestion_action_item(
                "formal_knowledge_without_official_graph",
                "needs_review",
                "已有正式知识项，但科研图谱同步记录尚未完成。",
                "inspect_official_research_graph_metadata",
                "official_sync",
            )
        )
    if not items and candidate_summary["officialGraphSyncedCandidateCount"] > 0:
        items.append(
            _knowledge_ingestion_action_item(
                "knowledge_ingestion_operational",
                "ready",
                "知识搜集、筛选、共享记忆和图谱同步链路已跑通。",
                "",
                "official_sync",
            )
        )
    return items[:24]


def _knowledge_ingestion_action_item(
    code: str,
    severity: str,
    message: str,
    next_action: str,
    workflow_node: str,
    **extra: Any,
) -> dict[str, Any]:
    payload = {
        "code": code,
        "severity": severity,
        "message": message,
        "nextAction": next_action,
        "workflowNode": workflow_node,
    }
    for key, value in extra.items():
        if value not in ("", None, [], {}):
            payload[key] = value
    return payload


def _knowledge_ingestion_overall_status(
    stages: list[dict[str, Any]],
    action_items: list[dict[str, Any]],
    candidate_summary: dict[str, int],
    knowledge_summary: dict[str, int],
) -> str:
    severities = {str(item.get("severity") or "") for item in action_items}
    if "blocked" in severities:
        return "blocked"
    if "needs_revision" in severities:
        return "needs_revision"
    if "needs_review" in severities or "needs_evidence" in severities or knowledge_summary["pendingProposalCount"] > 0:
        return "needs_review"
    if candidate_summary["officialGraphSyncedCandidateCount"] > 0:
        return "ready"
    if candidate_summary["candidateCount"] > 0:
        return "in_progress"
    return "empty"


def _candidate_breakdown(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    by_type: dict[str, int] = {}
    by_state: dict[str, int] = {}
    by_quality: dict[str, int] = {}
    for candidate in candidates:
        if str(candidate.get("candidateType") or "") == "candidate_graph":
            continue
        candidate_type = str(candidate.get("candidateType") or "unknown")
        state = str(candidate.get("currentState") or "unknown")
        quality = str(candidate.get("qualityStatus") or "unknown")
        by_type[candidate_type] = by_type.get(candidate_type, 0) + 1
        by_state[state] = by_state.get(state, 0) + 1
        by_quality[quality] = by_quality.get(quality, 0) + 1
    return {
        "byType": dict(sorted(by_type.items())),
        "byState": dict(sorted(by_state.items())),
        "byQualityStatus": dict(sorted(by_quality.items())),
    }


def _coordination_queues(
    candidates: list[dict[str, Any]],
    requested_transfers: list[dict[str, Any]],
    validation_reports: dict[str, dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    candidate_by_id = {str(candidate.get("candidateId") or ""): candidate for candidate in candidates}
    transfer_queue = [
        _coordination_item(
            candidate_by_id.get(str(transfer.get("candidateId") or "")),
            validation_reports,
            queue="pending_transfer",
            transfer=transfer,
            reason=str(transfer.get("reason") or ""),
        )
        for transfer in requested_transfers
    ]
    rework_queue = [
        _coordination_item(candidate, validation_reports, queue="needs_rework", reason=_coordination_candidate_reason(candidate, validation_reports))
        for candidate in candidates
        if _candidate_needs_rework(candidate, validation_reports)
    ]
    stewardship_queue = [
        _coordination_item(candidate, validation_reports, queue="stewardship", reason=_coordination_candidate_reason(candidate, validation_reports))
        for candidate in candidates
        if str(candidate.get("currentState") or "") in {"steward_pack_draft", "steward_pending_knowledge_review", "approved_to_ingest"}
    ]
    blocked_queue = [
        _coordination_item(candidate, validation_reports, queue="blocked", reason=_coordination_candidate_reason(candidate, validation_reports))
        for candidate in candidates
        if _candidate_is_coordination_blocked(candidate, validation_reports)
    ]
    active_queue = [
        _coordination_item(candidate, validation_reports, queue="active", reason=_coordination_candidate_reason(candidate, validation_reports))
        for candidate in candidates
        if not _candidate_needs_rework(candidate, validation_reports)
        and not _candidate_is_coordination_blocked(candidate, validation_reports)
        and str(candidate.get("currentState") or "") not in {"steward_pending_knowledge_review", "approved_to_ingest", "official_synced"}
    ]
    return {
        "pendingTransfers": transfer_queue,
        "needsRework": rework_queue,
        "stewardship": stewardship_queue,
        "blocked": blocked_queue,
        "active": active_queue[:12],
    }


def _coordination_summary(
    candidates: list[dict[str, Any]],
    archived_candidates: list[dict[str, Any]],
    requested_transfers: list[dict[str, Any]],
    queues: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    active_count = len(candidates)
    return {
        "candidateCount": active_count + len(archived_candidates),
        "activeCandidateCount": active_count,
        "archivedCandidateCount": len(archived_candidates),
        "pendingTransferCount": len(requested_transfers),
        "reworkCandidateCount": len(queues["needsRework"]),
        "stewardshipCandidateCount": len(queues["stewardship"]),
        "blockedCandidateCount": len(queues["blocked"]),
        "activeQueueCount": len(queues["active"]),
        "actionItemCount": 0,
        "byWorkflowNode": _coordination_count_by(candidates, "currentWorkflowNode"),
        "byState": _coordination_count_by(candidates, "currentState"),
        "byQualityStatus": _coordination_count_by(candidates, "qualityStatus"),
    }


def _coordination_action_items(summary: dict[str, Any], queues: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    action_items: list[dict[str, Any]] = []
    if summary["pendingTransferCount"] > 0:
        action_items.append(
            {
                "code": "transfer_decision_pending",
                "severity": "needs_review",
                "message": f"{summary['pendingTransferCount']} transfer request(s) need the coordination agent decision.",
                "nextAction": "Research Coordination Agent should approve, return, or reject the requested transfer.",
                "queue": "pendingTransfers",
            }
        )
    if summary["reworkCandidateCount"] > 0:
        action_items.append(
            {
                "code": "candidate_rework_pending",
                "severity": "needs_revision",
                "message": f"{summary['reworkCandidateCount']} candidate(s) need upstream rework.",
                "nextAction": "Route each candidate to the smallest upstream functional agent with requiredChanges.",
                "queue": "needsRework",
            }
        )
    if summary["blockedCandidateCount"] > 0:
        action_items.append(
            {
                "code": "coordination_blocked_candidates",
                "severity": "blocked",
                "message": f"{summary['blockedCandidateCount']} candidate(s) are blocked by invalid evidence or missing links.",
                "nextAction": "Resolve validation errors before requesting another workflow transfer.",
                "queue": "blocked",
            }
        )
    if summary["stewardshipCandidateCount"] > 0:
        action_items.append(
            {
                "code": "stewardship_queue_ready",
                "severity": "needs_review",
                "message": f"{summary['stewardshipCandidateCount']} stewardship item(s) are waiting for governance review or sync.",
                "nextAction": "Knowledge Steward Agent should keep these under approval gate until reviewed.",
                "queue": "stewardship",
            }
        )
    summary["actionItemCount"] = len(action_items)
    return action_items


def _coordination_status(summary: dict[str, Any], action_items: list[dict[str, Any]]) -> str:
    if summary["activeCandidateCount"] == 0 and summary["archivedCandidateCount"] == 0:
        return "empty"
    if any(str(item.get("severity") or "") == "blocked" for item in action_items):
        return "blocked"
    if summary["pendingTransferCount"] > 0:
        return "needs_transfer_decision"
    if summary["reworkCandidateCount"] > 0:
        return "needs_rework"
    if summary["stewardshipCandidateCount"] > 0:
        return "stewardship_review"
    return "in_progress"


def _coordination_item(
    candidate: dict[str, Any] | None,
    validation_reports: dict[str, dict[str, Any]],
    *,
    queue: str,
    transfer: dict[str, Any] | None = None,
    reason: str = "",
) -> dict[str, Any]:
    candidate_id = str((candidate or {}).get("candidateId") or (transfer or {}).get("candidateId") or "")
    validation = validation_reports.get(candidate_id) or {"valid": True, "issues": []}
    item = {
        "queue": queue,
        "candidateId": candidate_id,
        "candidateType": str((candidate or {}).get("candidateType") or ""),
        "title": str((candidate or {}).get("title") or ""),
        "currentWorkflowNode": str((candidate or {}).get("currentWorkflowNode") or (transfer or {}).get("fromNode") or ""),
        "currentState": str((candidate or {}).get("currentState") or ""),
        "qualityStatus": str((candidate or {}).get("qualityStatus") or ""),
        "valid": bool(validation.get("valid", True)),
        "issueCount": len(validation.get("issues") or []),
        "reason": _trim_text(reason, max_length=1000),
        "updatedAt": str((candidate or {}).get("updatedAt") or (transfer or {}).get("updatedAt") or ""),
    }
    if transfer:
        item.update(
            {
                "transferId": str(transfer.get("transferId") or ""),
                "fromNode": str(transfer.get("fromNode") or ""),
                "toNode": str(transfer.get("toNode") or ""),
                "requestedByAgent": str(transfer.get("requestedByAgent") or ""),
            }
        )
    return item


def _candidate_needs_rework(candidate: dict[str, Any], validation_reports: dict[str, dict[str, Any]]) -> bool:
    state = str(candidate.get("currentState") or "")
    quality_status = str(candidate.get("qualityStatus") or "")
    if "needs_revision" in state or quality_status == "needs_revision":
        return True
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    output = metadata.get("output") if isinstance(metadata.get("output"), dict) else {}
    if isinstance(output.get("requiredChanges"), list) and output.get("requiredChanges"):
        return True
    validation = validation_reports.get(str(candidate.get("candidateId") or ""))
    return bool(validation and not validation.get("valid", True))


def _candidate_is_coordination_blocked(candidate: dict[str, Any], validation_reports: dict[str, dict[str, Any]]) -> bool:
    state = str(candidate.get("currentState") or "")
    quality_status = str(candidate.get("qualityStatus") or "")
    if "blocked" in state or quality_status in {"broken_links", "source_manifest_invalid"}:
        return True
    validation = validation_reports.get(str(candidate.get("candidateId") or ""))
    return bool(validation and any(issue.get("severity") == "error" for issue in validation.get("issues") or []))


def _coordination_candidate_reason(candidate: dict[str, Any], validation_reports: dict[str, dict[str, Any]]) -> str:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    output = metadata.get("output") if isinstance(metadata.get("output"), dict) else {}
    required_changes = output.get("requiredChanges") if isinstance(output.get("requiredChanges"), list) else []
    if required_changes:
        return "; ".join(str(item) for item in required_changes[:3] if str(item).strip())
    validation = validation_reports.get(str(candidate.get("candidateId") or ""))
    if validation:
        errors = [issue for issue in validation.get("issues") or [] if issue.get("severity") == "error"]
        if errors:
            return str(errors[0].get("message") or errors[0].get("code") or "")
    return str(candidate.get("summary") or candidate.get("currentState") or candidate.get("qualityStatus") or "")


def _coordination_count_by(candidates: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for candidate in candidates:
        key = str(candidate.get(field) or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _knowledge_ingestion_knowledge_bases(knowledge_overview: dict[str, Any]) -> list[dict[str, Any]]:
    bases: list[dict[str, Any]] = []
    for base in list(knowledge_overview.get("knowledgeBases") or []):
        if not isinstance(base, dict):
            continue
        stats = base.get("stats") if isinstance(base.get("stats"), dict) else {}
        bases.append(
            {
                "knowledgeBaseId": str(base.get("knowledgeBaseId") or ""),
                "name": str(base.get("name") or ""),
                "status": str(base.get("status") or ""),
                "stats": {
                    "sourceArtifactCount": int(stats.get("sourceArtifactCount") or 0),
                    "proposalCount": int(stats.get("proposalCount") or 0),
                    "pendingProposalCount": int(stats.get("pendingProposalCount") or 0),
                    "itemCount": int(stats.get("itemCount") or 0),
                    "batchCount": int(stats.get("batchCount") or 0),
                },
            }
        )
    return bases


def _candidate_knowledge_ingestion_status(candidate: dict[str, Any]) -> str:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    ingestion = metadata.get("knowledgeIngestion") if isinstance(metadata.get("knowledgeIngestion"), dict) else {}
    return str(ingestion.get("status") or "")


def _source_manifest_source_ref(candidate: dict[str, Any]) -> dict[str, str]:
    source_kind = _trim_text(candidate.get("sourceKind"), max_length=80) or "source_manifest"
    return {
        "type": source_kind,
        "id": _trim_text(candidate.get("candidateId"), max_length=240),
        "label": _source_manifest_label(candidate),
    }


def _ready_source_extraction(candidate: dict[str, Any]) -> dict[str, Any]:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    extraction = metadata.get("sourceExtraction") if isinstance(metadata.get("sourceExtraction"), dict) else {}
    if extraction.get("status") != "extracted":
        raise TeamWorkflowOrchestrationError("Source extraction must be completed before paper_note autodraft.")
    page_anchors = extraction.get("pageAnchors")
    if not isinstance(page_anchors, list) or not page_anchors:
        raise TeamWorkflowOrchestrationError("Source extraction must include pageAnchors before paper_note autodraft.")
    if not _trim_text(extraction.get("excerpt"), max_length=24_000):
        raise TeamWorkflowOrchestrationError("Source extraction must include excerpt before paper_note autodraft.")
    return extraction


def _source_extraction_evidence_refs(candidate: dict[str, Any], extraction: dict[str, Any]) -> list[dict[str, str]]:
    source_label = _source_manifest_label(candidate)
    refs: list[dict[str, str]] = []
    for anchor in list(extraction.get("pageAnchors") or [])[:32]:
        if not isinstance(anchor, dict):
            continue
        page = int(anchor.get("page") or 0)
        anchor_id = _trim_text(anchor.get("id"), max_length=240) or f"{candidate.get('candidateId')}-p{page}"
        label = _trim_text(anchor.get("label"), max_length=120) or (f"p. {page}" if page else "page anchor")
        if anchor_id or label:
            refs.append(
                {
                    "type": "pdf_page",
                    "id": anchor_id,
                    "label": f"{source_label} {label}".strip(),
                }
            )
    return refs


def _resolve_source_path(source_path: str) -> Path:
    path = Path(source_path)
    if not path.is_absolute():
        path = _project_root() / path
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise SourceExtractionError("missing_file", "Local source file was not found.") from exc
    if not resolved.is_file():
        raise SourceExtractionError("missing_file", "Local source path is not a file.")
    if resolved.suffix.lower() != ".pdf":
        raise SourceExtractionError("unsupported_source_kind", "Only local PDF extraction is supported in this slice.")
    return resolved


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise SourceExtractionError("read_failed", "Local source file could not be read.") from exc
    return digest.hexdigest()


def _extract_pdf_page_anchors(
    path: Path,
    *,
    page_scope: str,
    max_pages: int,
    max_chars_per_page: int,
) -> list[dict[str, Any]]:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception as exc:
        raise SourceExtractionError("pdf_extractor_unavailable", "pypdf is not installed, so PDF text extraction is unavailable.") from exc
    try:
        reader = PdfReader(str(path))
        pages = list(reader.pages)
    except Exception as exc:
        raise SourceExtractionError("pdf_open_failed", "PDF could not be opened for text extraction.") from exc
    page_numbers = _page_numbers_from_scope(page_scope, total_pages=len(pages), max_pages=max_pages)
    anchors: list[dict[str, Any]] = []
    source_token = _safe_token(path.stem, default="pdf", max_length=80)
    for page_number in page_numbers:
        try:
            text = pages[page_number - 1].extract_text() or ""
        except Exception:
            text = ""
        normalized_text = _compact_text(text, max_length=max_chars_per_page)
        if not normalized_text:
            continue
        anchors.append(
            {
                "type": "pdf_page",
                "id": f"{source_token}-p{page_number}",
                "label": f"p. {page_number}",
                "page": page_number,
                "text": normalized_text,
            }
        )
    return anchors


def _page_numbers_from_scope(page_scope: str, *, total_pages: int, max_pages: int) -> list[int]:
    if total_pages <= 0 or max_pages <= 0:
        return []
    normalized_scope = _trim_text(page_scope, max_length=160)
    if not normalized_scope:
        return list(range(1, min(total_pages, max_pages) + 1))
    page_numbers: list[int] = []
    for part in re.split(r"[,;，；\s]+", normalized_scope):
        token = part.strip()
        if not token:
            continue
        range_match = re.fullmatch(r"(\d+)\s*[-~]\s*(\d+)", token)
        if range_match:
            start = int(range_match.group(1))
            end = int(range_match.group(2))
            if start > end:
                start, end = end, start
            page_numbers.extend(range(start, end + 1))
        elif token.isdigit():
            page_numbers.append(int(token))
    normalized: list[int] = []
    for number in page_numbers:
        if 1 <= number <= total_pages and number not in normalized:
            normalized.append(number)
        if len(normalized) >= max_pages:
            break
    return normalized or list(range(1, min(total_pages, max_pages) + 1))


def _page_scope_from_anchors(page_anchors: list[dict[str, Any]]) -> str:
    pages = [int(anchor.get("page") or 0) for anchor in page_anchors if isinstance(anchor, dict) and int(anchor.get("page") or 0) > 0]
    if not pages:
        return ""
    pages = sorted(set(pages))
    ranges: list[str] = []
    start = pages[0]
    previous = pages[0]
    for page in pages[1:]:
        if page == previous + 1:
            previous = page
            continue
        ranges.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = page
    ranges.append(str(start) if start == previous else f"{start}-{previous}")
    return ",".join(ranges)


def _excerpt_from_page_anchors(page_anchors: list[dict[str, Any]], *, max_chars: int) -> str:
    chunks: list[str] = []
    for anchor in page_anchors:
        if not isinstance(anchor, dict):
            continue
        page = int(anchor.get("page") or 0)
        text = _compact_text(anchor.get("text"), max_length=max_chars)
        if page and text:
            chunks.append(f"[p. {page}]\n{text}")
    return _trim_text("\n\n".join(chunks), max_length=max_chars)


def _compact_text(value: Any, *, max_length: int) -> str:
    text = str(value or "").replace("\x00", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:max_length]


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
        extraction = metadata.get("sourceExtraction") if isinstance(metadata.get("sourceExtraction"), dict) else {}
        if extraction:
            extraction_status = _trim_text(extraction.get("status"), max_length=80)
            if extraction_status == "failed":
                issues.append({"severity": "error", "code": "source_extraction_failed", "message": "PDF source_manifest extraction failed and needs confirmation before screening."})
            elif extraction_status == "extracted" and not isinstance(extraction.get("pageAnchors"), list):
                issues.append({"severity": "error", "code": "missing_page_anchors", "message": "PDF source_manifest extraction must include pageAnchors."})
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


def _steward_pack_ingestion_payload(
    team_id: str,
    candidate: dict[str, Any],
    output: dict[str, Any],
    *,
    proposed_by_agent_id: str,
) -> dict[str, Any]:
    proposal_payload = output.get("proposalPayload") if isinstance(output.get("proposalPayload"), dict) else {}
    source_trace = output.get("sourceTrace") if isinstance(output.get("sourceTrace"), dict) else {}
    source_ref = {
        "agentId": proposed_by_agent_id,
        "teamId": team_id,
        "candidateId": str(candidate.get("candidateId") or ""),
        "workflowId": str(candidate.get("workflowId") or ""),
        "taskType": "steward_pack_draft",
        "targetDomain": _trim_text(output.get("targetDomain"), max_length=160),
        "candidateIds": _normalize_text_list(output.get("candidateIds"), max_items=32, max_length=160),
        "sourceTrace": _normalize_metadata(source_trace),
    }
    title = (
        _trim_text(proposal_payload.get("title"), max_length=240)
        or _trim_text(candidate.get("title"), max_length=240)
        or "Challenge Cup steward ingestion proposal"
    )
    summary = _trim_text(proposal_payload.get("summary") or output.get("riskSummary") or candidate.get("summary"), max_length=4000)
    content_payload = {
        "proposalPayload": _normalize_metadata(proposal_payload),
        "ratingSuggestion": _normalize_metadata(output.get("ratingSuggestion") if isinstance(output.get("ratingSuggestion"), dict) else {}),
        "riskSummary": _trim_text(output.get("riskSummary"), max_length=4000),
        "claims": output.get("claims") if isinstance(output.get("claims"), list) else [],
        "uncertainty": output.get("uncertainty") if isinstance(output.get("uncertainty"), list) else [],
        "sourceTrace": _normalize_metadata(source_trace),
        "approvalRequired": True,
        "officialBoundary": {
            "writesOfficialKnowledge": False,
            "writesOfficialRag": False,
            "writesOfficialGraph": False,
        },
    }
    content = json.dumps(content_payload, ensure_ascii=False, indent=2, sort_keys=True)
    tags = ["challenge-cup", "steward-pack", "pending-review", _trim_text(output.get("targetDomain"), max_length=80)]
    return {
        "sourceRef": source_ref,
        "evidenceRange": {
            "sourceRefs": _normalize_ref_list(output.get("sourceRefs"), max_items=32),
            "evidenceRefs": _normalize_ref_list(output.get("evidenceRefs"), max_items=32),
        },
        "sourceTitle": f"Steward pack source: {title}",
        "sourceSummary": summary,
        "excerpt": _trim_text(output.get("riskSummary"), max_length=12000) or summary or title,
        "proposalTitle": title,
        "proposalSummary": summary,
        "proposalContent": content,
        "tags": [item for item in _normalize_text_list(tags, max_items=8, max_length=80) if item],
    }


def _steward_pack_rating_suggestion_payload(
    output: dict[str, Any],
    proposal: Any,
    proposed_by_agent_id: str,
) -> dict[str, Any] | None:
    if not isinstance(proposal, dict):
        return None
    proposal_id = _trim_text(proposal.get("proposalId"), max_length=160)
    if not proposal_id:
        return None
    rating = output.get("ratingSuggestion") if isinstance(output.get("ratingSuggestion"), dict) else {}
    if not rating:
        return None
    importance_level = _normalize_rating_enum(
        rating.get("importanceLevel") or rating.get("importance") or rating.get("rating"),
        {"low", "medium", "high", "critical"},
        default="medium",
    )
    stability = _normalize_rating_enum(rating.get("stability"), {"temporary", "evolving", "stable", "deprecated"}, default="evolving")
    review_priority = _normalize_rating_enum(
        rating.get("reviewPriority") or rating.get("priority"),
        {"normal", "elevated", "urgent"},
        default="elevated",
    )
    confidence = rating.get("confidence")
    if confidence is None:
        confidence = output.get("confidence")
    try:
        normalized_confidence = max(0.0, min(1.0, float(confidence if confidence is not None else 0.7)))
    except (TypeError, ValueError):
        normalized_confidence = 0.7
    reason = _trim_text(rating.get("reason") or rating.get("markingReason") or output.get("riskSummary"), max_length=2000)
    return {
        "suggested_by_agent_id": proposed_by_agent_id,
        "target_type": "proposal",
        "proposal_id": proposal_id,
        "importance_level": importance_level,
        "confidence": normalized_confidence,
        "stability": stability,
        "review_priority": review_priority,
        "marking_reason": reason,
    }


def _migrate_steward_pack_rating_suggestion(
    knowledge_base_id: str,
    *,
    source_suggestion_id: str,
    knowledge_item_id: str,
    reviewed_by_agent_id: str,
    resolution_note: str,
) -> dict[str, Any]:
    normalized_source_id = _trim_text(source_suggestion_id, max_length=160)
    normalized_item_id = _trim_text(knowledge_item_id, max_length=160)
    if not normalized_source_id:
        return {
            "status": "skipped",
            "reason": "missing_source_rating_suggestion",
            "sourceSuggestionId": "",
            "targetSuggestionId": "",
            "knowledgeItemId": normalized_item_id,
        }
    if not normalized_item_id:
        return {
            "status": "skipped",
            "reason": "missing_knowledge_item",
            "sourceSuggestionId": normalized_source_id,
            "targetSuggestionId": "",
            "knowledgeItemId": "",
        }
    try:
        suggestions_response = team_knowledge_service.list_rating_suggestions(
            knowledge_base_id,
            agent_id=reviewed_by_agent_id,
        )
    except (team_knowledge_service.TeamKnowledgeError, team_knowledge_service.TeamKnowledgeNotFoundError) as exc:
        return {
            "status": "failed",
            "reason": "source_lookup_failed",
            "error": str(exc),
            "sourceSuggestionId": normalized_source_id,
            "targetSuggestionId": "",
            "knowledgeItemId": normalized_item_id,
        }
    source_suggestion = next(
        (
            item
            for item in suggestions_response.get("suggestions", [])
            if str(item.get("suggestionId") or "") == normalized_source_id
        ),
        None,
    )
    if not isinstance(source_suggestion, dict):
        return {
            "status": "skipped",
            "reason": "source_not_found",
            "sourceSuggestionId": normalized_source_id,
            "targetSuggestionId": "",
            "knowledgeItemId": normalized_item_id,
        }
    if str(source_suggestion.get("status") or "") != "pending":
        return {
            "status": "skipped",
            "reason": "source_not_pending",
            "sourceSuggestionId": normalized_source_id,
            "sourceStatus": str(source_suggestion.get("status") or ""),
            "targetSuggestionId": "",
            "knowledgeItemId": normalized_item_id,
        }
    try:
        source_review = team_knowledge_service.review_rating_suggestion(
            knowledge_base_id,
            normalized_source_id,
            status="applied",
            reviewed_by_agent_id=reviewed_by_agent_id,
            resolution_note=resolution_note or "Migrated from steward pack proposal rating suggestion.",
        )
        target_suggestion = team_knowledge_service.create_rating_suggestion(
            knowledge_base_id,
            suggested_by_agent_id=str(source_suggestion.get("suggestedByAgentId") or reviewed_by_agent_id),
            target_type="knowledge_item",
            knowledge_item_id=normalized_item_id,
            importance_level=str(source_suggestion.get("importanceLevel") or "medium"),
            confidence=float(source_suggestion.get("confidence") if source_suggestion.get("confidence") is not None else 0.7),
            stability=str(source_suggestion.get("stability") or "evolving"),
            review_priority=str(source_suggestion.get("reviewPriority") or "elevated"),
            marking_reason=str(source_suggestion.get("markingReason") or ""),
        )
    except (TypeError, ValueError, team_knowledge_service.TeamKnowledgeError, team_knowledge_service.TeamKnowledgeNotFoundError) as exc:
        return {
            "status": "failed",
            "reason": "target_creation_failed",
            "error": str(exc),
            "sourceSuggestionId": normalized_source_id,
            "targetSuggestionId": "",
            "knowledgeItemId": normalized_item_id,
        }
    return {
        "status": "migrated",
        "sourceSuggestionId": normalized_source_id,
        "sourceStatus": str((source_review.get("suggestion") or {}).get("status") or ""),
        "targetSuggestionId": str(target_suggestion.get("suggestionId") or ""),
        "targetStatus": str(target_suggestion.get("status") or ""),
        "targetType": str(target_suggestion.get("targetType") or ""),
        "knowledgeItemId": normalized_item_id,
    }


def _official_research_graph_record(
    output: dict[str, Any],
    *,
    knowledge_item_ids: list[str],
    proposal_id: str,
    batch_id: str,
    knowledge_base_id: str,
    reviewed_by_agent_id: str,
    reviewed_at: str,
    decision: str,
) -> dict[str, Any]:
    normalized_item_ids = _normalize_id_values(knowledge_item_ids)
    if decision != "approved":
        return {
            "status": "not_synced",
            "reason": "decision_not_approved",
            "graphKind": "formal_research_trace",
            "knowledgeItemIds": [],
            "edges": [],
            "summary": {"edgeCount": 0},
        }
    if not normalized_item_ids:
        return {
            "status": "not_synced",
            "reason": "missing_knowledge_item",
            "graphKind": "formal_research_trace",
            "knowledgeItemIds": [],
            "edges": [],
            "summary": {"edgeCount": 0},
        }
    source_trace = output.get("sourceTrace") if isinstance(output.get("sourceTrace"), dict) else {}
    primary_item_id = normalized_item_ids[0]
    candidate_ids = _normalize_id_values(output.get("candidateIds"))
    source_ids = _normalize_id_values(source_trace.get("sourceIds") or source_trace.get("paperIds"))
    paper_note_ids = _normalize_id_values(source_trace.get("paperNoteIds"))
    neuro_mechanism_ids = _normalize_id_values(source_trace.get("neuroMechanismIds"))
    mechanism_mapping_ids = _normalize_id_values(source_trace.get("mechanismMappingIds"))
    algorithm_hypothesis_ids = _normalize_id_values(source_trace.get("algorithmHypothesisIds") or output.get("algorithmHypothesisIds"))
    review_record_ids = _normalize_id_values(source_trace.get("reviewRecordIds"))
    candidate_graph_id = _trim_text(source_trace.get("candidateGraphId"), max_length=160)
    if not algorithm_hypothesis_ids and candidate_ids:
        algorithm_hypothesis_ids = [item for item in candidate_ids if "hypothesis" in item.lower()]
    edges: list[dict[str, str]] = []
    for source_id in source_ids:
        edges.append(_official_research_graph_edge(source_id, primary_item_id, "supports", source_type="source", target_type="knowledge_item"))
    for paper_note_id in paper_note_ids:
        edges.append(_official_research_graph_edge(paper_note_id, primary_item_id, "supports", source_type="paper_note", target_type="knowledge_item"))
    for mechanism_id in neuro_mechanism_ids:
        edges.append(_official_research_graph_edge(mechanism_id, primary_item_id, "supports", source_type="neuro_mechanism", target_type="knowledge_item"))
    for mapping_id in mechanism_mapping_ids:
        edges.append(_official_research_graph_edge(mapping_id, primary_item_id, "maps_to", source_type="mechanism_mapping", target_type="knowledge_item"))
    for hypothesis_id in algorithm_hypothesis_ids:
        edges.append(_official_research_graph_edge(hypothesis_id, primary_item_id, "inspires", source_type="algorithm_hypothesis", target_type="knowledge_item"))
    for candidate_id in candidate_ids:
        edges.append(_official_research_graph_edge(candidate_id, primary_item_id, "approved_for_ingestion", source_type="candidate", target_type="knowledge_item"))
    for review_id in review_record_ids:
        edges.append(_official_research_graph_edge(review_id, primary_item_id, "approved_for_ingestion", source_type="review_record", target_type="knowledge_item"))
    deduped_edges: list[dict[str, str]] = []
    seen_edges: set[tuple[str, str, str]] = set()
    for edge in edges:
        edge_key = (edge["sourceId"], edge["targetId"], edge["relation"])
        if edge_key in seen_edges:
            continue
        seen_edges.add(edge_key)
        deduped_edges.append(edge)
    return {
        "status": "synced",
        "graphKind": "formal_research_trace",
        "knowledgeBaseId": knowledge_base_id,
        "knowledgeItemIds": normalized_item_ids,
        "proposalId": proposal_id,
        "batchId": batch_id,
        "candidateGraphId": candidate_graph_id,
        "targetDomain": _trim_text(output.get("targetDomain"), max_length=160),
        "reviewedByAgentId": reviewed_by_agent_id,
        "reviewedAt": reviewed_at,
        "edges": deduped_edges,
        "sourceTrace": {
            "sourceIds": source_ids,
            "paperNoteIds": paper_note_ids,
            "neuroMechanismIds": neuro_mechanism_ids,
            "mechanismMappingIds": mechanism_mapping_ids,
            "algorithmHypothesisIds": algorithm_hypothesis_ids,
            "reviewRecordIds": review_record_ids,
            "candidateIds": candidate_ids,
        },
        "officialBoundary": {
            "writesOfficialKnowledge": True,
            "writesOfficialRag": False,
            "writesOfficialGraph": True,
            "candidateGraphPromoted": bool(deduped_edges),
        },
        "summary": {
            "edgeCount": len(deduped_edges),
            "sourceCount": len(source_ids),
            "candidateCount": len(candidate_ids),
        },
    }


def _official_research_graph_edge(source_id: str, target_id: str, relation: str, *, source_type: str, target_type: str) -> dict[str, str]:
    return {
        "sourceId": source_id,
        "sourceType": source_type,
        "targetId": target_id,
        "targetType": target_type,
        "relation": relation,
        "edgeState": "official_synced",
    }


def _normalize_rating_enum(value: Any, allowed: set[str], *, default: str) -> str:
    normalized = _trim_text(value, max_length=80).lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "reviewable": "medium",
        "needs_review": "elevated",
        "pending_review": "elevated",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in allowed else default


def _normalize_steward_review_decision(value: Any) -> str:
    normalized = _trim_text(value, max_length=32).lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "apply": "approved",
        "applied": "approved",
        "approve": "approved",
        "accepted": "approved",
        "reject": "rejected",
        "declined": "rejected",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in {"approved", "rejected"}:
        raise TeamWorkflowOrchestrationError("Steward ingestion review decision must be approved or rejected.")
    return normalized


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


def _normalize_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


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
