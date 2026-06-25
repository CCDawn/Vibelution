"""Team workflow orchestration and candidate-store service."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config.paths import resolve_workspace_home
from config.public_config import build_effective_config, load_public_config
from core.infrastructure import developer_sandbox
from core.llm import LLMClient, LLMInvocationContext, invoke_llm
from core.research import smoke_runner
from core.runtime_manager import work_run_store
from core.web.services import agent_directory_service, candidate_schema_registry, chat_room_service, data_processing_service, session_service, team_knowledge_service, team_service
from core.web.services.runtime_scene_service import record_runtime_scene_event


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_VERSION = 1
WORKFLOW_LOG_SAMPLE_LIMIT = 8
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
OFFICIAL_MODEL_EVIDENCE_KINDS = {"config", "invocation_log", "sample_output", "screenshot", "candidate_output", "manual_attestation"}
OFFICIAL_MODEL_EVIDENCE_REQUIRED_TASKS = (
    {"taskType": "source_screening", "workflowNode": "knowledge_collection", "label": "资料初筛"},
    {"taskType": "paper_note_draft", "workflowNode": "paper_note", "label": "论文笔记草稿"},
    {"taskType": "neuro_mechanism_extract", "workflowNode": "neuro_mechanism", "label": "神经机制抽取"},
    {"taskType": "mechanism_mapping", "workflowNode": "mechanism_mapping", "label": "机制映射"},
    {"taskType": "algorithm_hypothesis_draft", "workflowNode": "algorithm_hypothesis", "label": "算法假设"},
    {"taskType": "review_prefilter", "workflowNode": "review_record", "label": "预审筛选"},
)
SOURCE_EXTRACTION_DEFAULT_MAX_PAGES = 24
SOURCE_EXTRACTION_HARD_MAX_PAGES = 64
SOURCE_EXTRACTION_DEFAULT_MAX_CHARS_PER_PAGE = 1800
SOURCE_EXTRACTION_HARD_MAX_CHARS_PER_PAGE = 6000
SOURCE_EXTRACTION_EXCERPT_MAX_CHARS = 12000
PAPER_NOTE_CHUNK_DEFAULT_MAX_PAGES = 4
PAPER_NOTE_CHUNK_HARD_MAX_PAGES = 12
PAPER_NOTE_CHUNK_DEFAULT_MAX_CHARS = 12000
PAPER_NOTE_CHUNK_HARD_MAX_CHARS = 24000
PAPER_NOTE_CHUNK_MAX_CHUNKS = 24
SOURCE_QUALITY_DECISIONS = {"approved", "needs_revision", "rejected"}
SOURCE_QUALITY_APPROVED_STATUSES = {"source_quality_approved", "source_manifest_ready"}
SOURCE_QUALITY_NEEDS_REVISION_STATUSES = {"source_quality_needs_revision", "source_manifest_invalid"}
SOURCE_QUALITY_REJECTED_STATUSES = {"source_quality_rejected", "rejected"}
SOURCE_COLLECTION_DEFAULT_AGENT_ROLES = (
    "data_discovery",
    "source_acquisition",
    "content_extraction",
    "source_quality",
)
SOURCE_COLLECTION_SEARCH_EXECUTION_AGENT_ROLES = {"data_discovery", "source_acquisition"}
SOURCE_COLLECTION_COLLECTION_STAGE_AGENT_ROLES = {"data_discovery", "source_acquisition", "content_extraction"}
SOURCE_COLLECTION_DEFAULT_SEARCH_LANGUAGES = ("en", "zh")
SOURCE_COLLECTION_DEFAULT_SOURCE_TYPES = ("paper", "review", "dataset", "preprint")
SOURCE_COLLECTION_DEFAULT_MAX_RESULTS_PER_QUERY = 10
SOURCE_COLLECTION_MAX_QUERIES = 48
SOURCE_COLLECTION_SEARCH_PROVIDER_CROSSREF = "crossref_rest_api"
SOURCE_COLLECTION_SEARCH_EXECUTION_DEFAULT_MAX_QUERIES = 4
SOURCE_COLLECTION_SEARCH_EXECUTION_MAX_QUERIES = 12
SOURCE_COLLECTION_SEARCH_EXECUTION_DEFAULT_RESULTS_PER_QUERY = 2
SOURCE_COLLECTION_SEARCH_EXECUTION_MAX_RESULTS_PER_QUERY = 5
SOURCE_COLLECTION_AGENT_CONTEXT_STAGE_ROLES = {
    "collection": ("data_discovery", "source_acquisition"),
    "candidate": ("content_extraction",),
    "screening": ("source_quality",),
    "graph": ("candidate_graph",),
    "memory": ("knowledge_steward",),
}
SOURCE_COLLECTION_STAGE_SESSION_TASK_KIND = "source_collection_stage_session_task"
SOURCE_COLLECTION_STAGE_REQUIRED_TOOLS = (
    "source_collection_context_tool",
    "source_collection_stage_writeback_tool",
)
SOURCE_COLLECTION_SEARCH_REQUIRED_TOOLS = (
    "web_search_tool",
    "batch_web_search_tool",
    "paper_search_tool",
)
SOURCE_COLLECTION_STAGE_SESSION_TASK_STATUSES = {"queued", "running", "completed", "needs_review", "blocked", "failed", "cancelled"}
SOURCE_COLLECTION_STAGE_SESSION_TASK_ACTIVE_STATUSES = {"queued", "running"}
SOURCE_COLLECTION_STAGE_WRITEBACK_MATERIALIZED_STATUSES = {"completed", "needs_review"}
SOURCE_COLLECTION_STORAGE_OPEN_TARGETS = {
    "run_directory",
    "artifacts_directory",
    "search_plan",
    "search_events",
    "records",
    "candidates",
    "candidate_store",
    "data_processing_run",
    "data_processing_records",
}
SOURCE_COLLECTION_PROMPT_CACHE_REQUIRED_MODES = {"required", "strict", "hard_required", "required_for_llm_execution"}
SOURCE_COLLECTION_PROMPT_CACHE_DISABLED_MODES = {"disabled", "off", "none"}
SOURCE_COLLECTION_SUPPORTED_PROMPT_CACHE_MODES = {"automatic", "explicit_cache_control"}
SOURCE_COLLECTION_PROMPT_CACHE_SCOPE = "research_team_knowledge_collection"
SOURCE_COLLECTION_WORK_RUN_KIND = "source_collection_run"
KNOWLEDGE_INGESTION_WORK_RUN_KIND = "knowledge_ingestion_run"
RESEARCH_STAGE_TYPES = ("knowledge_collection", "experiment", "iteration")
RESEARCH_STAGE_ACTIVE_STATUSES = {"running", "planning", "needs_attention"}
RESEARCH_STAGE_DEFAULTS = {
    "knowledge_collection": {
        "title": "Knowledge collection round",
        "currentNode": "knowledge_collection",
        "primaryActionZh": "启动知识搜集",
        "continueActionZh": "继续知识搜集",
        "newRoundActionZh": "开启新一轮知识搜集",
    },
    "experiment": {
        "title": "Experiment planning round",
        "currentNode": "experiment_planning",
        "primaryActionZh": "启动实验规划",
        "continueActionZh": "继续实验规划",
        "newRoundActionZh": "重新规划实验",
    },
    "iteration": {
        "title": "Iteration planning round",
        "currentNode": "iteration_planning",
        "primaryActionZh": "启动迭代",
        "continueActionZh": "继续迭代",
        "newRoundActionZh": "开启新一轮迭代",
    },
}
EXPERIMENT_PLAN_STORE_KIND = "team_workflow_experiment_plan_store"
EXPERIMENT_PLAN_REQUIRED_FIELDS = ("dataset", "metric", "baseline", "smokePlan")
EXPERIMENT_SMOKE_RESULT_STATUSES = {"passed", "failed", "needs_review"}
EXPERIMENT_FULL_RUN_RESULT_STATUSES = {"passed", "failed", "needs_review"}
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
        "purpose": "生成 proposal/ingestion pack 草稿，供知识库管理员复核。",
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


def register_candidate_source(team_id: str, payload: dict[str, Any], *, strict: bool = False) -> dict[str, Any]:
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
        # 统一写入口校验：registry 提供 envelope 级守卫（candidateId/teamId/类型等恒在，零回归），
        # 逐类型深校验仍由 validate_candidate_record 承担。strict=True 时硬拦截（供科研生成链调用方选用）。
        envelope_validation = candidate_schema_registry.validate_envelope(candidate)
        candidate["envelopeValidation"] = envelope_validation
        candidate_valid = bool(validation.get("valid")) and bool(envelope_validation.get("valid"))
        if strict and not candidate_valid:
            raise TeamWorkflowOrchestrationError(
                f"Candidate failed schema validation: {validation.get('issues', [])} {envelope_validation.get('issues', [])}"
            )
        if not candidate_valid:
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


def import_data_record_as_source_candidate(team_id: str, run_id: str, record_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    normalized_run_id = _trim_text(run_id, max_length=128)
    normalized_record_id = _trim_text(record_id, max_length=128)
    if not normalized_run_id or not normalized_record_id:
        raise TeamWorkflowOrchestrationError("Data processing runId and recordId are required.")
    team_service.get_team(normalized_team_id)
    import_payload = payload if isinstance(payload, dict) else {}
    run, record = _load_data_processing_record(normalized_run_id, normalized_record_id)
    source_identity_key = _source_collection_record_identity_key(record)
    with _WORKFLOW_LOCK:
        workflow = _load_or_create_workflow(normalized_team_id)
        candidate_store = _load_candidate_store(normalized_team_id)
        existing = _find_candidate_imported_from_data_record(candidate_store, normalized_run_id, normalized_record_id)
        if existing is not None:
            _record_workflow_event(
                "candidate.import_duplicate_skipped",
                normalized_team_id,
                fields={
                    "workflowId": workflow["workflowId"],
                    "runId": normalized_run_id,
                    "recordId": normalized_record_id,
                    "duplicateReason": "imported_from_data_record",
                    "duplicateOfCandidateId": str(existing.get("candidateId") or ""),
                    "sourceIdentityKey": source_identity_key,
                },
            )
            return {
                "created": False,
                "duplicate": True,
                "duplicateReason": "imported_from_data_record",
                "duplicateOfCandidateId": str(existing.get("candidateId") or ""),
                "candidate": existing,
                "dataRecordRef": _data_record_ref(run, record),
                "validation": existing.get("validation") if isinstance(existing.get("validation"), dict) else validate_candidate_record(existing),
                "workflow": _workflow_to_api(normalized_team_id, workflow, candidate_store),
            }
        existing_by_identity = _find_source_candidate_by_identity_key(candidate_store, source_identity_key)
        if existing_by_identity is not None:
            _record_workflow_event(
                "candidate.import_duplicate_skipped",
                normalized_team_id,
                fields={
                    "workflowId": workflow["workflowId"],
                    "runId": normalized_run_id,
                    "recordId": normalized_record_id,
                    "duplicateReason": "source_identity_key",
                    "duplicateOfCandidateId": str(existing_by_identity.get("candidateId") or ""),
                    "sourceIdentityKey": source_identity_key,
                },
            )
            return {
                "created": False,
                "duplicate": True,
                "duplicateReason": "source_identity_key",
                "duplicateOfCandidateId": str(existing_by_identity.get("candidateId") or ""),
                "candidate": existing_by_identity,
                "dataRecordRef": _data_record_ref(run, record),
                "validation": existing_by_identity.get("validation") if isinstance(existing_by_identity.get("validation"), dict) else validate_candidate_record(existing_by_identity),
                "workflow": _workflow_to_api(normalized_team_id, workflow, candidate_store),
            }
    candidate_payload = _source_candidate_payload_from_data_record(run, record, import_payload)
    response = register_candidate_source(normalized_team_id, candidate_payload)
    candidate = response["candidate"]
    _record_workflow_event(
        "candidate.imported_from_data_record",
        normalized_team_id,
        fields={
            "workflowId": candidate.get("workflowId", ""),
            "candidateId": candidate.get("candidateId", ""),
            "runId": normalized_run_id,
            "recordId": normalized_record_id,
            "sourceKind": candidate.get("sourceKind", ""),
        },
    )
    return {
        "created": True,
        "candidate": candidate,
        "dataRecordRef": _data_record_ref(run, record),
        "validation": response["validation"],
        "workflow": response["workflow"],
    }


def extract_source_collection_candidates(team_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    team_service.get_team(normalized_team_id)
    request_payload = payload if isinstance(payload, dict) else {}
    normalized_run_id = _normalize_required_id(request_payload.get("runId"), "Data processing run id is required.")
    extraction_agent_id = (
        _trim_text(request_payload.get("extractionAgentId"), max_length=160)
        or _trim_text(request_payload.get("createdByAgent"), max_length=160)
        or "资料提炼 Agent"
    )
    max_records = _normalize_int(request_payload.get("maxRecords"), default=100, minimum=1, maximum=500)
    force = bool(request_payload.get("force"))
    notes = _trim_text(request_payload.get("notes"), max_length=4000)
    try:
        run = data_processing_service.get_processing_run(normalized_run_id)
        records_payload = data_processing_service.list_records(normalized_run_id)
        assignments_payload = data_processing_service.list_collection_assignments(normalized_run_id)
    except data_processing_service.DataProcessingError as exc:
        raise TeamWorkflowOrchestrationError(str(exc)) from exc
    run_scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
    run_team_id = _trim_text(run_scope.get("teamId"), max_length=128)
    if run_team_id and run_team_id != normalized_team_id:
        raise TeamWorkflowOrchestrationError("Data processing run does not belong to this team.")

    records = [item for item in list(records_payload.get("records") or []) if isinstance(item, dict)]
    assignments = [item for item in list(assignments_payload.get("assignments") or []) if isinstance(item, dict)]
    storage_artifacts = _source_collection_storage_artifacts(normalized_team_id, normalized_run_id)
    with _WORKFLOW_LOCK:
        candidate_store = _load_candidate_store(normalized_team_id)
    existing_by_record_id: dict[str, dict[str, Any]] = {}
    for candidate in list(candidate_store.get("candidates") or []):
        if not isinstance(candidate, dict) or candidate.get("candidateType") != "source_manifest":
            continue
        imported_from = (candidate.get("metadata") or {}).get("importedFromDataRecord") if isinstance(candidate.get("metadata"), dict) else {}
        if not isinstance(imported_from, dict):
            continue
        if _trim_text(imported_from.get("runId"), max_length=128) != normalized_run_id:
            continue
        imported_record_id = _trim_text(imported_from.get("recordId"), max_length=128)
        if imported_record_id:
            existing_by_record_id[imported_record_id] = candidate

    pending_records = [
        record for record in records
        if _trim_text(record.get("recordId"), max_length=128) not in existing_by_record_id
    ]
    target_records = (records if force else pending_records)[:max_records]
    imported: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    record_outcomes: list[dict[str, Any]] = []
    execution_events: list[dict[str, Any]] = []
    extraction_assignment = next(
        (
            item for item in assignments
            if _trim_text(item.get("agentRole"), max_length=80) == "content_extraction"
        ),
        {"assignmentId": "", "agentRole": "content_extraction", "agentId": extraction_agent_id},
    )
    for record in target_records:
        record_id = _trim_text(record.get("recordId"), max_length=128)
        if not record_id:
            continue
        try:
            import_response = import_data_record_as_source_candidate(
                normalized_team_id,
                normalized_run_id,
                record_id,
                {
                    "createdByAgent": extraction_agent_id,
                    "tags": ["source_collection", "content_extraction"],
                    "metadata": {
                        "sourceCollectionExtraction": True,
                        "extractionAgentId": extraction_agent_id,
                        "extractionNotes": notes,
                    },
                },
            )
        except TeamWorkflowOrchestrationError as exc:
            failed.append({"recordId": record_id, "error": str(exc)})
            record_outcomes.append(
                {
                    "recordId": record_id,
                    "status": "failed",
                    "reason": "source_manifest_import_failed",
                    "errorType": type(exc).__name__,
                }
            )
            execution_events.append(
                _source_collection_execution_event(
                    "storage.source_manifest_import_failed",
                    assignment=extraction_assignment,
                    status="blocked",
                    title=f"资料提炼失败：{record.get('title') or record_id}",
                    summary=_trim_text(exc, max_length=600),
                    refs=[record_id],
                    storage_refs=[storage_artifacts["dataProcessingRecordsPath"], storage_artifacts["candidateStorePath"]],
                )
            )
            continue
        event_status = "completed" if import_response.get("created") else "skipped"
        if import_response.get("created"):
            imported.append(import_response)
            record_outcomes.append(
                {
                    "recordId": record_id,
                    "status": "imported",
                    "candidateId": import_response.get("candidate", {}).get("candidateId", ""),
                }
            )
        else:
            duplicate_reason = _trim_text(import_response.get("duplicateReason"), max_length=120) or "already_imported"
            skipped.append(
                {
                    "recordId": record_id,
                    "candidateId": import_response.get("candidate", {}).get("candidateId", ""),
                    "reason": duplicate_reason,
                }
            )
            record_outcomes.append(
                {
                    "recordId": record_id,
                    "status": "skipped",
                    "candidateId": import_response.get("candidate", {}).get("candidateId", ""),
                    "reason": duplicate_reason,
                }
            )
        execution_events.append(
            _source_collection_execution_event(
                "storage.source_manifest_imported",
                assignment=extraction_assignment,
                query=_source_collection_record_search_trace(record),
                status=event_status,
                title=f"资料提炼：{import_response['candidate'].get('title')}",
                summary="资料提炼 Agent 将 DataRecord 转为可追溯 source_manifest 候选；不写正式知识库、RAG 或官方图谱。",
                refs=[import_response["candidate"].get("candidateId", ""), record_id],
                raw_location=_trim_text(record.get("rawLocation") or record.get("sourceRef"), max_length=1000),
                storage_refs=[storage_artifacts["candidatesPath"], storage_artifacts["candidateStorePath"]],
            )
        )

    completed_extraction_assignments = 0
    remaining_pending_after_batch = max(0, len(pending_records) - len(target_records)) if not force else 0
    if records:
        open_extraction_assignments = [
            item for item in assignments
            if _trim_text(item.get("agentRole"), max_length=80) == "content_extraction"
            and str(item.get("status") or "").strip().lower() in {"open", "in_progress", "returned"}
        ]
        assignment_output_status = "completed" if not failed and remaining_pending_after_batch == 0 else "returned"
        for assignment in open_extraction_assignments:
            assignment_id = _trim_text(assignment.get("assignmentId"), max_length=128)
            if not assignment_id:
                continue
            try:
                data_processing_service.record_collection_output(
                    normalized_run_id,
                    assignment_id,
                    {
                        "status": assignment_output_status,
                        "records": [],
                        "notes": (
                            f"{extraction_agent_id} synchronized DataRecord records into source_manifest candidates. "
                            f"Imported {len(imported)}, skipped {len(skipped)}, failed {len(failed)}."
                        ),
                        "qualitySignals": {
                            "sourceCollectionExtraction": True,
                            "recordCount": len(records),
                            "importedCount": len(imported),
                            "skippedCount": len(skipped),
                            "failedCount": len(failed),
                        },
                        "blockingIssues": ["source_manifest_import_failed"] if failed else [],
                    },
                )
            except data_processing_service.DataProcessingError as exc:
                failed.append({"assignmentId": assignment_id, "error": str(exc)})
                continue
            completed_extraction_assignments += 1

    _append_source_collection_execution_artifacts(
        normalized_team_id,
        normalized_run_id,
        execution_events=execution_events,
        created_records=[],
        imported=imported,
    )
    final_run = data_processing_service.get_processing_run(normalized_run_id)
    final_records_payload = data_processing_service.list_records(normalized_run_id)
    final_assignments = data_processing_service.list_collection_assignments(normalized_run_id)["assignments"]
    final_status = data_processing_service.get_processing_status(normalized_run_id)
    source_collection_summary = _source_collection_assignment_stage_summary(
        [item for item in list(final_assignments or []) if isinstance(item, dict)]
    )
    final_status_summary = final_status.get("summary") if isinstance(final_status.get("summary"), dict) else {}
    final_status_summary.update(source_collection_summary)
    final_status["summary"] = final_status_summary
    with _WORKFLOW_LOCK:
        workflow = _load_or_create_workflow(normalized_team_id)
        final_candidate_store = _load_candidate_store(normalized_team_id)
        workflow_api = _workflow_to_api(normalized_team_id, workflow, final_candidate_store)
    final_records = [item for item in list(final_records_payload.get("records") or []) if isinstance(item, dict)]
    final_source_candidates = [
        item for item in list(final_candidate_store.get("candidates") or [])
        if isinstance(item, dict)
        and item.get("candidateType") == "source_manifest"
        and isinstance(item.get("metadata"), dict)
        and isinstance(item["metadata"].get("importedFromDataRecord"), dict)
        and _trim_text(item["metadata"]["importedFromDataRecord"].get("runId"), max_length=128) == normalized_run_id
    ]
    final_candidate_record_ids = {
        _trim_text(item["metadata"]["importedFromDataRecord"].get("recordId"), max_length=128)
        for item in final_source_candidates
    }
    pending_record_count = len(
        [
            record for record in final_records
            if _trim_text(record.get("recordId"), max_length=128) not in final_candidate_record_ids
        ]
    )
    status_label = "blocked" if not final_records else ("partial" if failed or pending_record_count else "completed")
    _record_workflow_event(
        "source_collection.candidates_extracted",
        normalized_team_id,
        fields={
            "runId": normalized_run_id,
            "status": status_label,
            "recordCount": len(final_records),
            "candidateCount": len(final_source_candidates),
            "importedCount": len(imported),
            "skippedCount": len(skipped),
            "failedCount": len(failed),
            "pendingRecordCount": pending_record_count,
            "completedExtractionAssignmentCount": completed_extraction_assignments,
        },
        child_log_path=f"artifacts/source-collection-{_safe_token(normalized_run_id, default='run', max_length=96)}-candidate-extraction.jsonl",
        child_log_payload={
            "kind": "source_collection_candidate_extraction",
            "teamId": normalized_team_id,
            "runId": normalized_run_id,
            "status": status_label,
            "recordCount": len(final_records),
            "candidateCount": len(final_source_candidates),
            "importedCount": len(imported),
            "skippedCount": len(skipped),
            "failedCount": len(failed),
            "pendingRecordCount": pending_record_count,
            "completedExtractionAssignmentCount": completed_extraction_assignments,
            "recordOutcomes": record_outcomes[:80],
            "truncatedRecordOutcomeCount": max(0, len(record_outcomes) - 80),
        },
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "runId": normalized_run_id,
        "status": status_label,
        "run": final_run,
        "runStatus": final_status,
        "sourceCollectionSummary": source_collection_summary,
        "storageArtifacts": storage_artifacts,
        "assignments": final_assignments,
        "recordCount": len(final_records),
        "candidateCount": len(final_source_candidates),
        "pendingRecordCount": pending_record_count,
        "importedCount": len(imported),
        "skippedCount": len(skipped),
        "failedCount": len(failed),
        "completedExtractionAssignmentCount": completed_extraction_assignments,
        "imported": imported,
        "skipped": skipped,
        "failed": failed,
        "executionEvents": execution_events,
        "workflow": workflow_api,
        "boundaries": {
            "externalSearchTriggered": False,
            "metadataOnlyDownload": True,
            "writesFormalKnowledge": False,
            "writesRag": False,
            "writesOfficialGraph": False,
        },
        "nextActions": [
            "Run source quality assessment on extracted source_manifest candidates.",
            "Keep formal Team Knowledge/RAG/official graph writes behind the later governance gate.",
        ],
    }


def seed_source_collection_agent_session_context(
    team_id: str,
    run_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    normalized_run_id = _normalize_required_id(run_id, "Data processing run id is required.")
    team = team_service.get_team(normalized_team_id)
    request_payload = dict(payload) if isinstance(payload, dict) else {}
    stage_id = _trim_text(request_payload.get("stageId"), max_length=80) or "collection"
    agent_id = _trim_text(request_payload.get("agentId"), max_length=160)
    agent_role = _trim_text(request_payload.get("agentRole"), max_length=80)
    if stage_id not in SOURCE_COLLECTION_AGENT_CONTEXT_STAGE_ROLES:
        raise TeamWorkflowOrchestrationError(f"Unsupported source collection stage: {stage_id}")
    if not agent_id:
        raise TeamWorkflowOrchestrationError("Agent id is required for source collection session context.")

    agent = agent_directory_service.get_agent(agent_id)
    if not isinstance(agent, dict):
        raise TeamWorkflowOrchestrationError(f"Agent not found: {agent_id}")
    session_id = _trim_text(agent.get("directSessionId"), max_length=160)
    if not session_id:
        raise TeamWorkflowOrchestrationError(f"Agent has no direct session: {agent_id}")

    try:
        run = data_processing_service.get_processing_run(normalized_run_id)
        assignments_payload = data_processing_service.list_collection_assignments(normalized_run_id)
        records_payload = data_processing_service.list_records(normalized_run_id)
        run_status = data_processing_service.get_processing_status(normalized_run_id)
    except data_processing_service.DataProcessingError as exc:
        raise TeamWorkflowOrchestrationError(str(exc)) from exc
    run_scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
    run_team_id = _trim_text(run_scope.get("teamId"), max_length=128)
    if run_team_id and run_team_id != normalized_team_id:
        raise TeamWorkflowOrchestrationError("Data processing run does not belong to this team.")

    assignments = [item for item in list(assignments_payload.get("assignments") or []) if isinstance(item, dict)]
    records = [item for item in list(records_payload.get("records") or []) if isinstance(item, dict)]
    if not agent_role:
        agent_role = _source_collection_agent_role_for_id(assignments, agent_id, stage_id)
    allowed_roles = SOURCE_COLLECTION_AGENT_CONTEXT_STAGE_ROLES[stage_id]
    if agent_role and agent_role not in allowed_roles:
        raise TeamWorkflowOrchestrationError(f"Agent role {agent_role} is not assigned to source collection stage {stage_id}.")

    matching_assignments = [
        item for item in assignments
        if (
            (agent_role and _trim_text(item.get("agentRole"), max_length=80) == agent_role)
            or _trim_text(item.get("agentId"), max_length=160) == agent_id
        )
    ]
    storage_artifacts = _source_collection_storage_artifacts(normalized_team_id, normalized_run_id)
    source_candidates = _source_collection_candidates_for_run(normalized_team_id, normalized_run_id)
    active_snapshot = _source_collection_work_run_store().load_active_snapshot(SOURCE_COLLECTION_WORK_RUN_KIND)
    active_work_run = (
        active_snapshot
        if _source_collection_background_snapshot_is_active(active_snapshot, normalized_team_id, normalized_run_id)
        else {}
    )
    context_key = f"source_collection_context:{normalized_team_id}:{normalized_run_id}:{stage_id}:{agent_id}:{agent_role or 'agent'}"
    existing_message = _find_source_collection_context_message(session_id, context_key)
    if existing_message is not None:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "teamId": normalized_team_id,
            "runId": normalized_run_id,
            "stageId": stage_id,
            "agentId": agent_id,
            "agentRole": agent_role,
            "sessionId": session_id,
            "contextKey": context_key,
            "created": False,
            "alreadyPresent": True,
            "message": existing_message,
        }

    message_content = _source_collection_agent_context_message(
        team=team,
        agent=agent,
        stage_id=stage_id,
        agent_role=agent_role,
        run=run,
        run_status=run_status,
        active_work_run=active_work_run,
        assignments=assignments,
        matching_assignments=matching_assignments,
        records=records,
        source_candidates=source_candidates,
        storage_artifacts=storage_artifacts,
    )
    message = session_service.append_session_assistant_artifact_message(
        session_id,
        message_content,
        metadata={
            "kind": "source_collection_agent_context",
            "status": "observed",
            "teamId": normalized_team_id,
            "runId": normalized_run_id,
            "stageId": stage_id,
            "agentId": agent_id,
            "agentRole": agent_role,
            "sourceCollectionContextKey": context_key,
            "recordCount": len(records),
            "candidateCount": len(source_candidates),
            "assignmentCount": len(assignments),
            "matchingAssignmentCount": len(matching_assignments),
            "activeWorkRunId": _trim_text(active_work_run.get("runId"), max_length=160) if active_work_run else "",
            "storageArtifacts": storage_artifacts,
            "turnId": context_key,
        },
    )
    _record_workflow_event(
        "source_collection.agent_session_context_seeded",
        normalized_team_id,
        fields={
            "runId": normalized_run_id,
            "stageId": stage_id,
            "agentId": agent_id,
            "agentRole": agent_role,
            "sessionId": session_id,
            "recordCount": len(records),
            "candidateCount": len(source_candidates),
            "assignmentCount": len(assignments),
        },
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "runId": normalized_run_id,
        "stageId": stage_id,
        "agentId": agent_id,
        "agentRole": agent_role,
        "sessionId": session_id,
        "contextKey": context_key,
        "created": True,
        "alreadyPresent": False,
        "message": message,
    }


def _source_collection_default_stage_agent(stage_id: str, *, agent_role: str = "") -> dict[str, Any] | None:
    if stage_id != "memory":
        return None
    normalized_role = _trim_text(agent_role, max_length=80)
    if normalized_role and normalized_role != agent_directory_service.KNOWLEDGE_STEWARD_ROLE_KEY:
        return None
    agent_directory_service.repair_agent_directory()
    agent = agent_directory_service.get_agent(agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID, include_archived=False)
    if not isinstance(agent, dict):
        return None
    return _ensure_source_collection_stage_agent_direct_session(
        agent,
        stage_id=stage_id,
        agent_role=agent_directory_service.KNOWLEDGE_STEWARD_ROLE_KEY,
    )


def _ensure_source_collection_stage_agent_direct_session(
    agent: dict[str, Any],
    *,
    stage_id: str,
    agent_role: str,
) -> dict[str, Any]:
    agent_id = _trim_text(agent.get("agentId"), max_length=160)
    if (
        stage_id != "memory"
        or (
            agent_id != agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID
            and _trim_text(agent_role, max_length=80) != agent_directory_service.KNOWLEDGE_STEWARD_ROLE_KEY
        )
    ):
        return agent
    session = session_service.ensure_agent_direct_session(
        agent_id=agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID,
        title=agent_directory_service.KNOWLEDGE_STEWARD_FUNCTIONAL_NAME,
        created_by="source_collection_memory_stage",
    )
    session_id = _trim_text(session.get("id") or session.get("sessionId"), max_length=160)
    if session_id and _trim_text(agent.get("directSessionId"), max_length=160) != session_id:
        return agent_directory_service.update_agent_instance(
            agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID,
            direct_session_id=session_id,
            display_name=agent_directory_service.KNOWLEDGE_STEWARD_FUNCTIONAL_NAME,
            preserve_generated_display_name=True,
        )
    refreshed = agent_directory_service.get_agent(agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID, include_archived=False)
    return refreshed if isinstance(refreshed, dict) else agent


def start_source_collection_stage_session_task(
    team_id: str,
    run_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    normalized_run_id = _normalize_required_id(run_id, "Data processing run id is required.")
    team = team_service.get_team(normalized_team_id)
    request_payload = dict(payload) if isinstance(payload, dict) else {}
    stage_id = _trim_text(request_payload.get("stageId"), max_length=80) or "collection"
    agent_id = _trim_text(request_payload.get("agentId"), max_length=160)
    agent_role = _trim_text(request_payload.get("agentRole"), max_length=80)
    return_to = _trim_text(request_payload.get("returnTo"), max_length=1000)
    return_label = _trim_text(request_payload.get("returnLabel"), max_length=240)
    requested_by = _trim_text(request_payload.get("requestedByAgent"), max_length=160)
    idempotency_key = _trim_text(request_payload.get("idempotencyKey"), max_length=240)
    if stage_id not in SOURCE_COLLECTION_AGENT_CONTEXT_STAGE_ROLES:
        raise TeamWorkflowOrchestrationError(f"Unsupported source collection stage: {stage_id}")
    if not agent_id:
        default_agent = _source_collection_default_stage_agent(stage_id, agent_role=agent_role)
        if default_agent:
            agent_id = _trim_text(default_agent.get("agentId"), max_length=160)
            agent_role = agent_role or "knowledge_steward"
    if not agent_id:
        raise TeamWorkflowOrchestrationError("Agent id is required for source collection stage session task.")

    agent = agent_directory_service.get_agent(agent_id)
    if not isinstance(agent, dict):
        raise TeamWorkflowOrchestrationError(f"Agent not found: {agent_id}")
    agent = _ensure_source_collection_stage_agent_direct_session(agent, stage_id=stage_id, agent_role=agent_role)
    session_id = _trim_text(agent.get("directSessionId"), max_length=160)
    if not session_id:
        raise TeamWorkflowOrchestrationError(f"Agent has no direct session: {agent_id}")

    run_bundle = _source_collection_run_context_bundle(normalized_team_id, normalized_run_id)
    run = run_bundle["run"]
    assignments = run_bundle["assignments"]
    records = run_bundle["records"]
    source_candidates = run_bundle["sourceCandidates"]
    run_status = run_bundle["runStatus"]
    active_work_run = run_bundle["activeWorkRun"]
    if not agent_role:
        agent_role = _source_collection_agent_role_for_id(assignments, agent_id, stage_id)
    allowed_roles = SOURCE_COLLECTION_AGENT_CONTEXT_STAGE_ROLES[stage_id]
    if agent_role and agent_role not in allowed_roles:
        raise TeamWorkflowOrchestrationError(f"Agent role {agent_role} is not assigned to source collection stage {stage_id}.")

    matching_assignments = _source_collection_matching_assignments(assignments, agent_id=agent_id, agent_role=agent_role)
    if not requested_by:
        requested_by = _source_collection_owner_agent_id(team, {})
    storage_artifacts = _source_collection_storage_artifacts(normalized_team_id, normalized_run_id)
    task_id = _new_record_id("stagetask")
    task_idempotency_key = _source_collection_stage_task_idempotency_key(
        team_id=normalized_team_id,
        run_id=normalized_run_id,
        stage_id=stage_id,
        agent_id=agent_id,
        agent_role=agent_role,
        task_id=task_id,
        requested_key=idempotency_key,
    )
    if idempotency_key:
        existing_task = _find_source_collection_stage_session_task(
            normalized_team_id,
            normalized_run_id,
            idempotency_key=task_idempotency_key,
        )
        if existing_task is not None:
            _record_workflow_event(
                "source_collection.stage_session_task_reused",
                normalized_team_id,
                fields={
                    "runId": normalized_run_id,
                    "stageId": stage_id,
                    "agentId": agent_id,
                    "agentRole": agent_role,
                    "sessionId": _trim_text(existing_task.get("sessionId"), max_length=160) or session_id,
                    "taskId": _trim_text(existing_task.get("taskId"), max_length=160),
                    "idempotencyKey": task_idempotency_key,
                    "status": _trim_text(existing_task.get("status"), max_length=80),
                },
            )
            return {
                "schemaVersion": SCHEMA_VERSION,
                "teamId": normalized_team_id,
                "runId": normalized_run_id,
                "stageId": stage_id,
                "agentId": agent_id,
                "agentRole": agent_role,
                "sessionId": _trim_text(existing_task.get("sessionId"), max_length=160) or session_id,
                "taskId": _trim_text(existing_task.get("taskId"), max_length=160),
                "idempotencyKey": task_idempotency_key,
                "created": False,
                "alreadyPresent": True,
                "task": existing_task,
                "turn": existing_task.get("turn") if isinstance(existing_task.get("turn"), dict) else {},
                "chatRoute": _source_collection_stage_task_chat_route(
                    _trim_text(existing_task.get("sessionId"), max_length=160) or session_id,
                    return_to=return_to or _trim_text(existing_task.get("returnTo"), max_length=1000),
                    return_label=return_label or _trim_text(existing_task.get("returnLabel"), max_length=240),
                ),
                "writebackContract": existing_task.get("writebackContract") if isinstance(existing_task.get("writebackContract"), dict) else {},
                "boundaries": _source_collection_stage_session_task_boundaries(),
            }

    _record_source_collection_stage_task_tool_policy_event(
        normalized_team_id,
        normalized_run_id,
        stage_id=stage_id,
        agent_id=agent_id,
        agent_role=agent_role,
        session_id=session_id,
        task_id=task_id,
    )
    writeback_contract = _source_collection_stage_task_writeback_contract(
        normalized_team_id,
        normalized_run_id,
        task_id,
        stage_id=stage_id,
        agent_id=agent_id,
        agent_role=agent_role,
    )
    task_message = _source_collection_stage_session_task_message(
        team=team,
        agent=agent,
        stage_id=stage_id,
        agent_role=agent_role,
        run=run,
        run_status=run_status,
        active_work_run=active_work_run,
        assignments=assignments,
        matching_assignments=matching_assignments,
        records=records,
        source_candidates=source_candidates,
        storage_artifacts=storage_artifacts,
        writeback_contract=writeback_contract,
    )
    now = utc_now_iso()
    task_record = {
        "schemaVersion": SCHEMA_VERSION,
        "taskKind": SOURCE_COLLECTION_STAGE_SESSION_TASK_KIND,
        "taskId": task_id,
        "idempotencyKey": task_idempotency_key,
        "teamId": normalized_team_id,
        "runId": normalized_run_id,
        "stageId": stage_id,
        "agentId": agent_id,
        "agentRole": agent_role,
        "sessionId": session_id,
        "status": "queued",
        "title": _source_collection_stage_task_title(stage_id),
        "summary": "",
        "returnTo": return_to,
        "returnLabel": return_label,
        "requestedByAgent": requested_by,
        "recordCount": len(records),
        "candidateCount": len(source_candidates),
        "assignmentCount": len(assignments),
        "matchingAssignmentCount": len(matching_assignments),
        "storageArtifacts": storage_artifacts,
        "writebackContract": writeback_contract,
        "writesFormalKnowledge": bool(writeback_contract.get("writesFormalKnowledge")),
        "writesRag": False,
        "writesOfficialGraph": bool(writeback_contract.get("writesOfficialGraph")),
        "turn": {},
        "result": {},
        "writeback": {},
        "createdAt": now,
        "updatedAt": now,
    }
    _upsert_source_collection_stage_session_task(normalized_team_id, normalized_run_id, task_record)
    turn = session_service.submit_session_message(
        session_id,
        task_message,
        mental_model_enabled=False,
        turn_mode="task",
        write_intent=False,
        message_source="team_workflow_stage_task",
        message_metadata={
            "kind": SOURCE_COLLECTION_STAGE_SESSION_TASK_KIND,
            "teamId": normalized_team_id,
            "runId": normalized_run_id,
            "stageId": stage_id,
            "agentId": agent_id,
            "agentRole": agent_role,
            "sourceCollectionStageTaskId": task_id,
            "sourceCollectionStageTaskKey": task_idempotency_key,
            "writebackContract": writeback_contract,
        },
        include_started_turn_id=True,
        lightweight_response=True,
    )
    turn_payload = turn if isinstance(turn, dict) else {}
    task_record["status"] = "running" if turn_payload.get("accepted") else "queued"
    task_record["turn"] = {
        "accepted": bool(turn_payload.get("accepted")),
        "turnId": _trim_text(turn_payload.get("turnId") or turn_payload.get("startedTurnId"), max_length=160),
        "status": _trim_text(turn_payload.get("status"), max_length=80),
        "acceptedAt": _trim_text(turn_payload.get("acceptedAt"), max_length=120),
    }
    if not task_record["turn"]["accepted"]:
        _record_workflow_event(
            "source_collection.stage_session_task_submit_not_accepted",
            normalized_team_id,
            fields={
                "runId": normalized_run_id,
                "stageId": stage_id,
                "agentId": agent_id,
                "agentRole": agent_role,
                "sessionId": session_id,
                "taskId": task_id,
                "turnStatus": task_record["turn"].get("status", ""),
            },
        )
    task_record["updatedAt"] = utc_now_iso()
    _upsert_source_collection_stage_session_task(normalized_team_id, normalized_run_id, task_record)
    _sync_stage_round_with_source_collection_stage_task(normalized_team_id, normalized_run_id, task_record)
    _record_workflow_event(
        "source_collection.stage_session_task_started",
        normalized_team_id,
        fields={
            "runId": normalized_run_id,
            "stageId": stage_id,
            "agentId": agent_id,
            "agentRole": agent_role,
            "sessionId": session_id,
            "taskId": task_id,
            "turnId": task_record["turn"].get("turnId", ""),
        },
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "runId": normalized_run_id,
        "stageId": stage_id,
        "agentId": agent_id,
        "agentRole": agent_role,
        "sessionId": session_id,
        "taskId": task_id,
        "idempotencyKey": task_idempotency_key,
        "created": True,
        "alreadyPresent": False,
        "task": task_record,
        "turn": task_record["turn"],
        "chatRoute": _source_collection_stage_task_chat_route(session_id, return_to=return_to, return_label=return_label),
        "writebackContract": writeback_contract,
        "boundaries": _source_collection_stage_session_task_boundaries(stage_id=stage_id, agent_role=agent_role),
    }


def writeback_source_collection_stage_session_task(
    team_id: str,
    task_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    normalized_task_id = _normalize_required_id(task_id, "Stage session task id is required.")
    team_service.get_team(normalized_team_id)
    request_payload = dict(payload) if isinstance(payload, dict) else {}
    task, run_id = _find_source_collection_stage_session_task_by_id(normalized_team_id, normalized_task_id)
    if task is None or not run_id:
        raise TeamWorkflowOrchestrationError(f"Stage session task not found: {normalized_task_id}")
    status = _normalize_source_collection_stage_session_task_status(request_payload.get("status") or request_payload.get("resultStatus"))
    result_payload = request_payload.get("result") if isinstance(request_payload.get("result"), dict) else {}
    writeback = {
        "status": status,
        "summary": _trim_text(request_payload.get("summary"), max_length=4000),
        "result": _normalize_metadata(result_payload),
        "evidenceRefs": _normalize_ref_list(request_payload.get("evidenceRefs"), max_items=24),
        "nextActions": _normalize_text_list(request_payload.get("nextActions"), max_items=12, max_length=500),
        "recordedByAgent": _trim_text(request_payload.get("recordedByAgent"), max_length=160),
        "metadata": _normalize_metadata(request_payload.get("metadata")),
        "recordedAt": utc_now_iso(),
    }
    materialized_sources = _materialize_source_collection_stage_writeback_sources(
        normalized_team_id,
        run_id,
        task,
        writeback,
    )
    materialized_source_quality = _materialize_source_collection_stage_writeback_quality(
        normalized_team_id,
        run_id,
        task,
        writeback,
    )
    materialized_candidate_graph = _materialize_source_collection_stage_writeback_candidate_graph(
        normalized_team_id,
        run_id,
        task,
        writeback,
    )
    materialized_knowledge_ingestion = _materialize_source_collection_stage_writeback_knowledge_ingestion(
        normalized_team_id,
        run_id,
        task,
        writeback,
    )
    writeback["materializedSources"] = materialized_sources
    writeback["materializedSourceQuality"] = materialized_source_quality
    writeback["materializedCandidateGraph"] = materialized_candidate_graph
    writeback["materializedKnowledgeIngestion"] = materialized_knowledge_ingestion
    task["status"] = status
    task["summary"] = writeback["summary"] or _trim_text(task.get("summary"), max_length=4000)
    task["result"] = writeback["result"]
    if materialized_sources.get("createdRecordCount") or materialized_sources.get("importedCandidateCount"):
        task["result"]["materializedSources"] = materialized_sources
    if materialized_source_quality.get("assessedCandidateCount"):
        task["result"]["materializedSourceQuality"] = materialized_source_quality
    if materialized_candidate_graph.get("candidateGraphId"):
        task["result"]["materializedCandidateGraph"] = materialized_candidate_graph
    if materialized_knowledge_ingestion.get("formalKnowledgeItemCount") or materialized_knowledge_ingestion.get("stewardPackCandidateId"):
        task["result"]["materializedKnowledgeIngestion"] = materialized_knowledge_ingestion
    task["evidenceRefs"] = writeback["evidenceRefs"]
    task["nextActions"] = writeback["nextActions"]
    task["writeback"] = writeback
    task["writesFormalKnowledge"] = bool(materialized_knowledge_ingestion.get("writesFormalKnowledge"))
    task["writesRag"] = bool(materialized_knowledge_ingestion.get("writesRag"))
    task["writesOfficialGraph"] = bool(materialized_knowledge_ingestion.get("writesOfficialGraph"))
    turn = task.get("turn") if isinstance(task.get("turn"), dict) else {}
    if turn:
        next_turn = dict(turn)
        next_turn["status"] = status
        task["turn"] = next_turn
    task["updatedAt"] = writeback["recordedAt"]
    _upsert_source_collection_stage_session_task(normalized_team_id, run_id, task)
    _sync_stage_round_with_source_collection_stage_task(normalized_team_id, run_id, task)
    _record_workflow_event(
        "source_collection.stage_session_task_writeback",
        normalized_team_id,
        fields={
            "runId": run_id,
            "taskId": normalized_task_id,
            "stageId": task.get("stageId", ""),
            "agentId": task.get("agentId", ""),
            "status": status,
            "sourceLeadCount": materialized_sources.get("sourceLeadCount", 0),
            "createdRecordCount": materialized_sources.get("createdRecordCount", 0),
            "importedCandidateCount": materialized_sources.get("importedCandidateCount", 0),
            "skippedDuplicateCount": materialized_sources.get("skippedDuplicateCount", 0),
            "sourceQualityAssessedCandidateCount": materialized_source_quality.get("assessedCandidateCount", 0),
            "sourceQualitySkippedCandidateCount": materialized_source_quality.get("skippedCandidateCount", 0),
            "candidateGraphId": materialized_candidate_graph.get("candidateGraphId", ""),
            "candidateGraphCreatedCount": materialized_candidate_graph.get("createdCandidateGraphCount", 0),
            "candidateGraphReused": bool(materialized_candidate_graph.get("reusedCandidateGraph")),
            "knowledgeIngestionStatus": materialized_knowledge_ingestion.get("status", ""),
            "formalKnowledgeItemCount": materialized_knowledge_ingestion.get("formalKnowledgeItemCount", 0),
            "stewardPackCandidateId": materialized_knowledge_ingestion.get("stewardPackCandidateId", ""),
        },
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "runId": run_id,
        "taskId": normalized_task_id,
        "stageId": task.get("stageId", ""),
        "agentId": task.get("agentId", ""),
        "agentRole": task.get("agentRole", ""),
        "task": task,
        "writeback": writeback,
        "boundaries": _source_collection_stage_session_task_boundaries(
            stage_id=_trim_text(task.get("stageId"), max_length=80),
            agent_role=_trim_text(task.get("agentRole"), max_length=80),
        ),
    }


def get_source_collection_stage_task_context(
    team_id: str,
    *,
    run_id: str = "",
    stage_id: str = "",
    task_id: str = "",
    max_records: int = 24,
    include_candidates: bool = True,
    candidate_offset: int = 0,
    candidate_limit: int | None = None,
) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    team_service.get_team(normalized_team_id)
    normalized_task_id = _trim_text(task_id, max_length=160)
    task: dict[str, Any] = {}
    task_run_id = ""
    if normalized_task_id:
        found_task, found_run_id = _find_source_collection_stage_session_task_by_id(normalized_team_id, normalized_task_id)
        if found_task is None or not found_run_id:
            raise TeamWorkflowOrchestrationError(f"Stage session task not found: {normalized_task_id}")
        task = dict(found_task)
        task_run_id = found_run_id
    normalized_run_id = (
        _trim_text(run_id, max_length=128)
        or task_run_id
        or _trim_text(task.get("runId"), max_length=128)
    )
    normalized_run_id = _normalize_required_id(normalized_run_id, "Data processing run id is required.")
    normalized_stage_id = (
        _trim_text(stage_id, max_length=80)
        or _trim_text(task.get("stageId"), max_length=80)
        or "collection"
    )
    if normalized_stage_id not in SOURCE_COLLECTION_AGENT_CONTEXT_STAGE_ROLES:
        raise TeamWorkflowOrchestrationError(f"Unsupported source collection stage: {normalized_stage_id}")
    run_bundle = _source_collection_run_context_bundle(normalized_team_id, normalized_run_id)
    task_agent_id = _trim_text(task.get("agentId"), max_length=160)
    task_agent_role = _trim_text(task.get("agentRole"), max_length=80)
    matching_assignments = _source_collection_matching_assignments(
        run_bundle["assignments"],
        agent_id=task_agent_id,
        agent_role=task_agent_role,
    )
    limit = _normalize_int(max_records, default=24, minimum=1, maximum=80)
    records = _rank_source_collection_context_records(
        run_bundle["records"],
        stage_id=normalized_stage_id,
        source_candidates=run_bundle["sourceCandidates"],
    )
    selected_records = records[:limit]
    source_candidates = _rank_source_collection_context_candidates(
        run_bundle["sourceCandidates"],
        stage_id=normalized_stage_id,
    ) if include_candidates else []
    candidate_page_offset = _normalize_int(candidate_offset, default=0, minimum=0, maximum=10000)
    candidate_page_limit = _normalize_int(
        candidate_limit if candidate_limit is not None else limit,
        default=limit,
        minimum=1,
        maximum=80,
    )
    selected_candidates = source_candidates[candidate_page_offset:candidate_page_offset + candidate_page_limit]
    next_candidate_offset = candidate_page_offset + len(selected_candidates)
    candidate_has_more = next_candidate_offset < len(source_candidates)
    storage_artifacts = _source_collection_storage_artifacts(normalized_team_id, normalized_run_id)
    selected_unassessed_candidate_ids = [
        _trim_text(item.get("candidateId"), max_length=128)
        for item in selected_candidates
        if _trim_text(item.get("candidateId"), max_length=128) and _source_quality_bucket(item) == "pending"
    ]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "status": "ok",
        "contextKind": "source_collection_stage_task_context",
        "teamId": normalized_team_id,
        "runId": normalized_run_id,
        "stageId": normalized_stage_id,
        "taskId": normalized_task_id,
        "agentId": task_agent_id,
        "agentRole": task_agent_role,
        "counts": {
            "recordCount": len(run_bundle["records"]),
            "returnedRecordCount": len(selected_records),
            "candidateCount": len(run_bundle["sourceCandidates"]),
            "returnedCandidateCount": len(selected_candidates),
            "assignmentCount": len(run_bundle["assignments"]),
            "matchingAssignmentCount": len(matching_assignments),
        },
        "run": _source_collection_context_run_summary(run_bundle["run"], run_bundle["runStatus"], run_bundle["activeWorkRun"]),
        "task": _source_collection_context_task_summary(task),
        "assignments": [_source_collection_context_assignment_summary(item) for item in matching_assignments[:12]],
        "records": [_source_collection_context_record_summary(item) for item in selected_records],
        "candidates": [_source_collection_context_candidate_summary(item) for item in selected_candidates],
        "candidatePage": {
            "offset": candidate_page_offset,
            "limit": candidate_page_limit,
            "returned": len(selected_candidates),
            "total": len(source_candidates),
            "hasMore": candidate_has_more,
            "nextOffset": next_candidate_offset if candidate_has_more else None,
        },
        "unassessedCandidateIds": selected_unassessed_candidate_ids,
        "allUnassessedCandidateCount": sum(1 for item in source_candidates if _source_quality_bucket(item) == "pending"),
        "storageArtifacts": storage_artifacts,
        "writebackContract": task.get("writebackContract") if isinstance(task.get("writebackContract"), dict) else {},
        "boundaries": _source_collection_stage_session_task_boundaries(),
        "usage": {
            "readTool": "source_collection_context_tool",
            "writebackTool": "source_collection_stage_writeback_tool",
            "doNotUse": ["file://", "localhost fetch", "web_fetch_tool for local paths"],
            "fallback": "If required context is missing, write back status=blocked with a short reason.",
        },
    }


def start_source_collection_run(team_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    team = team_service.get_team(normalized_team_id)
    request_payload = dict(payload) if isinstance(payload, dict) else {}
    title = _trim_text(request_payload.get("title"), max_length=180) or "Challenge Cup source collection"
    goal = _trim_text(request_payload.get("goal"), max_length=1000)
    topic = _trim_text(request_payload.get("topic"), max_length=500)
    input_refs = _normalize_text_list(request_payload.get("inputRefs"), max_items=120, max_length=240)
    roles = _normalize_source_collection_roles(request_payload.get("agentRoles"))
    request_payload["agentIds"] = _source_collection_team_agent_ids(team, roles, request_payload)
    default_owner_agent_id = _source_collection_owner_agent_id(team, request_payload)
    owner_agent_id = _trim_text(request_payload.get("ownerAgentId"), max_length=160) or default_owner_agent_id
    requested_by_agent = _trim_text(request_payload.get("requestedByAgent"), max_length=160) or owner_agent_id
    prompt_cache_policy = _source_collection_prompt_cache_policy(normalized_team_id, request_payload, roles)
    scope = _normalize_metadata(request_payload.get("scope"))
    if goal:
        scope["goal"] = goal
    if topic:
        scope["topic"] = topic
    scope["teamId"] = normalized_team_id
    scope["workflowKind"] = WORKFLOW_KIND_CHALLENGE_CUP_RESEARCH
    scope["promptCachePolicyRef"] = _source_collection_prompt_cache_policy_ref(prompt_cache_policy)
    preliminary_search_plan = _build_source_collection_search_plan(
        team_id=normalized_team_id,
        run_id="",
        payload=request_payload,
        scope=scope,
        input_refs=input_refs,
        roles=roles,
        prompt_cache_policy=prompt_cache_policy,
    )
    scope["dataSearchPlanRef"] = _source_collection_search_plan_ref(preliminary_search_plan)
    run = data_processing_service.create_processing_run(
        data_processing_service.DEFAULT_PROFILE_ID,
        title=title,
        scope=scope,
        metadata={
            "startedFrom": "team_workflow_source_collection",
            "teamId": normalized_team_id,
            "requestedByAgent": requested_by_agent,
            "ownerAgentId": owner_agent_id,
            "searchPlanId": preliminary_search_plan["planId"],
            "queryCount": preliminary_search_plan["queryCount"],
            "querySeedCount": len(preliminary_search_plan["querySeeds"]),
            "promptCachePolicyId": prompt_cache_policy["policyId"],
            "promptCacheRequirement": prompt_cache_policy["requirement"],
            "promptCacheModelId": prompt_cache_policy["modelId"],
            "promptCacheMode": prompt_cache_policy["promptCacheMode"],
            "promptCacheGateStatus": prompt_cache_policy["gate"]["status"],
        },
    )
    search_plan = _build_source_collection_search_plan(
        team_id=normalized_team_id,
        run_id=run["runId"],
        payload=request_payload,
        scope=scope,
        input_refs=input_refs,
        roles=roles,
        plan_id=preliminary_search_plan["planId"],
        prompt_cache_policy=prompt_cache_policy,
    )
    storage_artifacts = _source_collection_storage_artifacts(normalized_team_id, run["runId"])
    search_plan["storageArtifacts"] = storage_artifacts
    search_plan["resultWritebackContract"]["evidenceStorage"] = storage_artifacts
    _write_source_collection_search_plan(normalized_team_id, run["runId"], search_plan)
    assignments = [
        data_processing_service.create_collection_assignment(
            run["runId"],
            {
                "agentRole": role,
                "agentId": _source_collection_agent_id(role, request_payload),
                "scope": _source_collection_assignment_scope(role, scope, search_plan=search_plan),
                "inputRefs": input_refs,
                "expectedRecordTypes": ["source_manifest", "paper", "dataset", "url", "file"],
                "acceptance": {
                    "output": "CollectionOutput.records",
                    "handoff": "Import accepted DataRecord through Team workflow source-candidate bridge.",
                    "resultWritebackContract": search_plan["resultWritebackContract"],
                    "noFormalKnowledgeWrite": True,
                },
            },
        )
        for role in roles
    ]
    with _WORKFLOW_LOCK:
        workflow = _load_or_create_workflow(normalized_team_id)
        workflow["ownerAgentId"] = owner_agent_id
        workflow["routingPolicy"] = _sync_owner_policy(workflow.get("routingPolicy"), owner_agent_id)
        workflow["transferPolicy"] = _sync_transfer_policy(workflow.get("transferPolicy"), owner_agent_id)
        workflow["updatedAt"] = utc_now_iso()
        workflow["activeWorkflowItems"] = _upsert_active_item(
            workflow.get("activeWorkflowItems"),
            candidate_id=run["runId"],
            current_node="knowledge_collection",
            status="source_collection_started",
            transfer_id="",
        )
        _write_json(_workflow_path(normalized_team_id), workflow)
        candidate_store = _load_candidate_store(normalized_team_id)
    _record_workflow_event(
        "source_collection.run_started",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "runId": run["runId"],
            "assignmentCount": len(assignments),
            "requestedByAgent": requested_by_agent,
            "ownerAgentId": owner_agent_id,
            "searchPlanId": search_plan["planId"],
            "queryCount": search_plan["queryCount"],
            "querySeedCount": len(search_plan["querySeeds"]),
            "promptCacheRequirement": prompt_cache_policy["requirement"],
            "promptCacheMode": prompt_cache_policy["promptCacheMode"],
            "promptCacheGateStatus": prompt_cache_policy["gate"]["status"],
            "teamAgentBindingCount": sum(1 for item in assignments if str(item.get("agentId") or "") != str(item.get("agentRole") or "")),
            "sourceCollectionRunDirectory": storage_artifacts["runDirectory"],
        },
    )
    return {
        "run": data_processing_service.get_processing_run(run["runId"]),
        "searchPlan": search_plan,
        "storageArtifacts": storage_artifacts,
        "promptCachePolicy": prompt_cache_policy,
        "assignments": assignments,
        "assignmentCount": len(assignments),
        "workflow": _workflow_to_api(normalized_team_id, workflow, candidate_store),
        "nextActions": [
            "Functional data collection agents submit CollectionOutput records.",
            "Accepted DataRecords are imported through source-candidate bridge.",
            "Imported source_manifest candidates continue through source extraction and screening.",
        ],
        "boundaries": {
            "writesFormalKnowledge": False,
            "writesRag": False,
            "writesKnowledgeGraph": False,
        },
    }


def execute_source_collection_search(team_id: str, run_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    normalized_run_id = _normalize_required_id(run_id, "Data processing run id is required.")
    team = team_service.get_team(normalized_team_id)
    try:
        run = data_processing_service.get_processing_run(normalized_run_id)
    except data_processing_service.DataProcessingError as exc:
        raise TeamWorkflowOrchestrationError(str(exc)) from exc
    run_scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
    run_team_id = _trim_text(run_scope.get("teamId"), max_length=128)
    if run_team_id and run_team_id != normalized_team_id:
        raise TeamWorkflowOrchestrationError("Data processing run does not belong to this team.")

    try:
        assignments_payload = data_processing_service.list_collection_assignments(normalized_run_id)
        records_payload = data_processing_service.list_records(normalized_run_id)
    except data_processing_service.DataProcessingError as exc:
        raise TeamWorkflowOrchestrationError(str(exc)) from exc
    assignments = [item for item in list(assignments_payload.get("assignments") or []) if isinstance(item, dict)]
    records = [item for item in list(records_payload.get("records") or []) if isinstance(item, dict)]
    _persist_source_collection_work_run(
        normalized_team_id,
        normalized_run_id,
        status="running",
        current_phase="searching",
        run=run,
        team=team,
        assignments=assignments,
        records=records,
        summary="正在执行资料搜索，搜索来源元数据并写入候选资料库。",
        active=True,
    )
    try:
        result = _execute_source_collection_search_impl(normalized_team_id, normalized_run_id, payload)
    except Exception as exc:
        failure_result = {
            "status": "failed",
            "failedQueryCount": 1,
            "executedQueryCount": 0,
            "recordCount": len(records),
            "importedCount": 0,
            "sourceCollectionSummary": _source_collection_assignment_stage_summary(assignments),
        }
        _persist_source_collection_work_run(
            normalized_team_id,
            normalized_run_id,
            status="failed",
            current_phase="failed",
            run=run,
            team=team,
            assignments=assignments,
            records=records,
            summary="资料搜索执行失败。",
            active=False,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        _sync_source_collection_stage_round_after_search(
            normalized_team_id,
            normalized_run_id,
            failure_result,
            terminal_status="failed",
            terminal_summary="资料搜索执行失败，等待检查搜索错误。",
        )
        raise

    final_run = result.get("run") if isinstance(result.get("run"), dict) else run
    final_assignments = [item for item in list(result.get("assignments") or []) if isinstance(item, dict)]
    try:
        final_records = data_processing_service.list_records(normalized_run_id).get("records") if normalized_run_id else []
    except data_processing_service.DataProcessingError:
        final_records = []
    terminal_status = _source_collection_work_run_terminal_status(result)
    terminal_phase = _source_collection_work_run_terminal_phase(result)
    terminal_summary = _source_collection_work_run_terminal_summary(result)
    _persist_source_collection_work_run(
        normalized_team_id,
        normalized_run_id,
        status=terminal_status,
        current_phase=terminal_phase,
        run=final_run,
        team=team,
        assignments=final_assignments,
        records=[item for item in list(final_records or []) if isinstance(item, dict)],
        summary=terminal_summary,
        active=False,
        extra={
            "executedQueryCount": _source_collection_count(result.get("executedQueryCount")),
            "failedQueryCount": _source_collection_count(result.get("failedQueryCount")),
            "recordCount": _source_collection_count(result.get("recordCount")),
            "importedCount": _source_collection_count(result.get("importedCount")),
            "resultCount": _source_collection_count(result.get("resultCount")),
        },
    )
    _sync_source_collection_stage_round_after_search(
        normalized_team_id,
        normalized_run_id,
        result,
        terminal_status=terminal_status,
        terminal_summary=terminal_summary,
    )
    return result


def start_source_collection_search_background(team_id: str, run_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    normalized_run_id = _normalize_required_id(run_id, "Data processing run id is required.")
    team = team_service.get_team(normalized_team_id)
    request_payload = dict(payload) if isinstance(payload, dict) else {}
    provider = _trim_text(request_payload.get("provider"), max_length=80) or SOURCE_COLLECTION_SEARCH_PROVIDER_CROSSREF
    if provider != SOURCE_COLLECTION_SEARCH_PROVIDER_CROSSREF:
        raise TeamWorkflowOrchestrationError(f"Unsupported source collection search provider: {provider}")
    try:
        run = data_processing_service.get_processing_run(normalized_run_id)
        assignments_payload = data_processing_service.list_collection_assignments(normalized_run_id)
        records_payload = data_processing_service.list_records(normalized_run_id)
        run_status = data_processing_service.get_processing_status(normalized_run_id)
    except data_processing_service.DataProcessingError as exc:
        raise TeamWorkflowOrchestrationError(str(exc)) from exc
    run_scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
    run_team_id = _trim_text(run_scope.get("teamId"), max_length=128)
    if run_team_id and run_team_id != normalized_team_id:
        raise TeamWorkflowOrchestrationError("Data processing run does not belong to this team.")
    assignments = [item for item in list(assignments_payload.get("assignments") or []) if isinstance(item, dict)]
    records = [item for item in list(records_payload.get("records") or []) if isinstance(item, dict)]
    storage_artifacts = _source_collection_storage_artifacts(normalized_team_id, normalized_run_id)
    with _WORKFLOW_LOCK:
        existing_active_snapshot = _source_collection_work_run_store().load_active_snapshot(SOURCE_COLLECTION_WORK_RUN_KIND)
        if _source_collection_background_snapshot_is_active(existing_active_snapshot, normalized_team_id, normalized_run_id):
            _record_workflow_event(
                "source_collection.search_background_already_running",
                normalized_team_id,
                fields={
                    "runId": normalized_run_id,
                    "provider": provider,
                    "assignmentCount": len(assignments),
                    "recordCount": len(records),
                    "activeStatus": str(existing_active_snapshot.get("status") or ""),
                    "activePhase": str(existing_active_snapshot.get("currentPhase") or ""),
                },
            )
            return _source_collection_search_background_response(
                team_id=normalized_team_id,
                run_id=normalized_run_id,
                provider=provider,
                run=run,
                run_status=run_status,
                storage_artifacts=storage_artifacts,
                assignments=assignments,
                records=records,
                active_snapshot=existing_active_snapshot,
                already_running=True,
            )
        active_snapshot = _persist_source_collection_work_run(
            normalized_team_id,
            normalized_run_id,
            status="running",
            current_phase="queued",
            run=run,
            team=team,
            assignments=assignments,
            records=records,
            summary="资料搜索已进入后台执行，页面可继续操作。",
            active=True,
            extra={
                "executionMode": "background",
                "provider": provider,
                "queuedSearchExecution": True,
            },
        )
    worker = threading.Thread(
        target=_run_source_collection_search_background,
        args=(normalized_team_id, normalized_run_id, request_payload),
        name=f"source-collection-search-{normalized_run_id[:24]}",
        daemon=True,
    )
    worker.start()
    _record_workflow_event(
        "source_collection.search_background_accepted",
        normalized_team_id,
        fields={
            "runId": normalized_run_id,
            "provider": provider,
            "assignmentCount": len(assignments),
            "recordCount": len(records),
            "threadName": worker.name,
        },
    )
    return _source_collection_search_background_response(
        team_id=normalized_team_id,
        run_id=normalized_run_id,
        provider=provider,
        run=run,
        run_status=run_status,
        storage_artifacts=storage_artifacts,
        assignments=assignments,
        records=records,
        active_snapshot=active_snapshot,
        already_running=False,
    )


def _source_collection_background_snapshot_is_active(snapshot: dict[str, Any] | None, team_id: str, run_id: str) -> bool:
    if not isinstance(snapshot, dict):
        return False
    if _trim_text(snapshot.get("runId"), max_length=160) != run_id:
        return False
    if _trim_text(snapshot.get("teamId"), max_length=160) != team_id:
        return False
    status = _trim_text(snapshot.get("status"), max_length=80).lower()
    current_phase = _trim_text(snapshot.get("currentPhase"), max_length=80).lower()
    return status in {"queued", "running"} or current_phase in {"queued", "running"}


def _source_collection_search_background_response(
    *,
    team_id: str,
    run_id: str,
    provider: str,
    run: dict[str, Any],
    run_status: dict[str, Any],
    storage_artifacts: dict[str, str],
    assignments: list[dict[str, Any]],
    records: list[dict[str, Any]],
    active_snapshot: dict[str, Any],
    already_running: bool,
) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": team_id,
        "runId": run_id,
        "status": "accepted",
        "executionMode": "background",
        "accepted": True,
        "alreadyRunning": already_running,
        "provider": provider,
        "executedQueryCount": 0,
        "skippedQueryCount": 0,
        "failedQueryCount": 0,
        "resultCount": 0,
        "recordCount": len(records),
        "outputCount": 0,
        "importedCount": 0,
        "run": run,
        "runStatus": run_status,
        "storageArtifacts": storage_artifacts,
        "assignments": assignments,
        "outputs": [],
        "createdRecords": [],
        "imported": [],
        "executionEvents": [],
        "activeWorkRun": active_snapshot,
        "boundaries": {
            "externalSearchTriggered": False,
            "externalSearchQueued": True,
            "metadataOnlyDownload": True,
            "writesFormalKnowledge": False,
            "writesRag": False,
            "writesOfficialGraph": False,
        },
        "nextActions": [
            "The background source collection worker is running and will write DataRecords and source_manifest candidates.",
            "Keep this page open or return later; run status and assignments can refresh without blocking the request.",
        ],
    }


def _run_source_collection_search_background(team_id: str, run_id: str, payload: dict[str, Any]) -> None:
    try:
        result = execute_source_collection_search(team_id, run_id, payload)
    except Exception as exc:
        _record_workflow_event(
            "source_collection.search_background_failed",
            team_id,
            fields={
                "runId": run_id,
                "errorType": type(exc).__name__,
                "error": _trim_text(exc, max_length=500),
            },
        )
        return
    _record_workflow_event(
        "source_collection.search_background_completed",
        team_id,
        fields={
            "runId": run_id,
            "status": _trim_text(result.get("status"), max_length=80),
            "executedQueryCount": _source_collection_count(result.get("executedQueryCount")),
            "recordCount": _source_collection_count(result.get("recordCount")),
            "importedCount": _source_collection_count(result.get("importedCount")),
        },
    )


def _execute_source_collection_search_impl(team_id: str, run_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    normalized_run_id = _normalize_required_id(run_id, "Data processing run id is required.")
    team_service.get_team(normalized_team_id)
    request_payload = payload if isinstance(payload, dict) else {}
    provider = _trim_text(request_payload.get("provider"), max_length=80) or SOURCE_COLLECTION_SEARCH_PROVIDER_CROSSREF
    if provider != SOURCE_COLLECTION_SEARCH_PROVIDER_CROSSREF:
        raise TeamWorkflowOrchestrationError(f"Unsupported source collection search provider: {provider}")
    max_queries = _normalize_int(
        request_payload.get("maxQueries"),
        default=SOURCE_COLLECTION_SEARCH_EXECUTION_DEFAULT_MAX_QUERIES,
        minimum=1,
        maximum=SOURCE_COLLECTION_SEARCH_EXECUTION_MAX_QUERIES,
    )
    max_results_per_query = _normalize_int(
        request_payload.get("maxResultsPerQuery"),
        default=SOURCE_COLLECTION_SEARCH_EXECUTION_DEFAULT_RESULTS_PER_QUERY,
        minimum=1,
        maximum=SOURCE_COLLECTION_SEARCH_EXECUTION_MAX_RESULTS_PER_QUERY,
    )
    target_assignment_ids = set(_normalize_text_list(request_payload.get("assignmentIds"), max_items=16, max_length=128))
    target_agent_role = _trim_text(request_payload.get("agentRole"), max_length=80)
    force = bool(request_payload.get("force"))
    try:
        run = data_processing_service.get_processing_run(normalized_run_id)
        assignments_payload = data_processing_service.list_collection_assignments(normalized_run_id)
        records_payload = data_processing_service.list_records(normalized_run_id)
    except data_processing_service.DataProcessingError as exc:
        raise TeamWorkflowOrchestrationError(str(exc)) from exc
    run_scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
    run_team_id = _trim_text(run_scope.get("teamId"), max_length=128)
    if run_team_id and run_team_id != normalized_team_id:
        raise TeamWorkflowOrchestrationError("Data processing run does not belong to this team.")
    assignments = [item for item in list(assignments_payload.get("assignments") or []) if isinstance(item, dict)]
    existing_records = [item for item in list(records_payload.get("records") or []) if isinstance(item, dict)]
    existing_query_ids = _source_collection_existing_query_ids(existing_records)
    existing_identity_records = _source_collection_existing_identity_records(existing_records)
    execution_events: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    created_records: list[dict[str, Any]] = []
    imported: list[dict[str, Any]] = []
    storage_artifacts = _source_collection_storage_artifacts(normalized_team_id, normalized_run_id)
    executed_query_count = 0
    skipped_query_count = 0
    failed_query_count = 0
    result_count = 0
    skipped_duplicate_count = 0
    duplicate_source_keys: list[str] = []

    for assignment in assignments:
        if executed_query_count >= max_queries:
            break
        assignment_id = _trim_text(assignment.get("assignmentId"), max_length=128)
        agent_role = _trim_text(assignment.get("agentRole"), max_length=80)
        if agent_role not in SOURCE_COLLECTION_SEARCH_EXECUTION_AGENT_ROLES:
            continue
        if target_assignment_ids and assignment_id not in target_assignment_ids:
            continue
        if target_agent_role and agent_role != target_agent_role:
            continue
        if not force and str(assignment.get("status") or "") not in {"open", "in_progress", "returned"}:
            continue
        assigned_queries = _source_collection_assigned_queries(assignment)
        if not assigned_queries:
            execution_events.append(
                _source_collection_execution_event(
                    "assignment.no_query",
                    assignment=assignment,
                    status="blocked",
                    title=f"{agent_role or assignment_id} has no assigned query",
                    summary="This assignment has no query seed in its source collection scope.",
                    refs=[assignment_id],
                )
            )
            continue
        attempted_query_ids: list[str] = []
        assignment_skipped_duplicate_count = 0
        assignment_query_ids = {
            _trim_text(item.get("queryId"), max_length=160)
            for item in assigned_queries
            if _trim_text(item.get("queryId"), max_length=160)
        }
        for query in assigned_queries:
            if executed_query_count >= max_queries:
                break
            query_id = _trim_text(query.get("queryId"), max_length=160)
            query_text = _trim_text(query.get("query"), max_length=1000)
            if not query_id or not query_text:
                continue
            if query_id in existing_query_ids and not force:
                skipped_query_count += 1
                continue
            search_response = _execute_source_collection_query(query, max_results=max_results_per_query, provider=provider)
            attempted_query_ids.append(query_id)
            query_records: list[dict[str, Any]] = []
            query_skipped_duplicate_count = 0
            if search_response.get("error"):
                failed_query_count += 1
                execution_events.append(
                    _source_collection_execution_event(
                        "search.failed",
                        assignment=assignment,
                        query=query,
                        status="blocked",
                        title=f"Search failed: {query_text}",
                        summary=_trim_text(search_response.get("error"), max_length=500),
                        refs=[query_id, provider],
                    )
                )
                continue
            executed_query_count += 1
            existing_query_ids.add(query_id)
            search_results = [item for item in list(search_response.get("results") or []) if isinstance(item, dict)]
            result_count += len(search_results)
            execution_events.append(
                _source_collection_execution_event(
                    "search.executed",
                    assignment=assignment,
                    query=query,
                    status="completed" if search_results else "returned",
                    title=f"Searched {provider}: {query_text}",
                    summary=f"Fetched {len(search_results)} metadata result(s); full text was not downloaded.",
                    refs=[query_id, _trim_text(search_response.get("searchUrl"), max_length=240)],
                    raw_location=_trim_text(search_response.get("searchUrl"), max_length=1000),
                )
            )
            for result in search_results:
                candidate_record = _source_collection_record_from_search_result(
                    normalized_team_id,
                    run,
                    assignment,
                    query,
                    result,
                    provider=provider,
                    search_url=_trim_text(search_response.get("searchUrl"), max_length=1000),
                )
                source_identity_key = _source_collection_record_identity_key(candidate_record)
                duplicate_record = existing_identity_records.get(source_identity_key) if source_identity_key else None
                if duplicate_record is not None:
                    skipped_duplicate_count += 1
                    assignment_skipped_duplicate_count += 1
                    query_skipped_duplicate_count += 1
                    if source_identity_key:
                        duplicate_source_keys.append(source_identity_key)
                    execution_events.append(
                        _source_collection_execution_event(
                            "search.duplicate_skipped",
                            assignment=assignment,
                            query=query,
                            status="completed",
                            title=f"Skipped duplicate source: {candidate_record.get('title') or candidate_record.get('sourceRef')}",
                            summary="The search result matched an existing DataRecord source identity and was not written again.",
                            refs=[source_identity_key, duplicate_record.get("recordId", "")],
                            raw_location=_trim_text(candidate_record.get("rawLocation") or candidate_record.get("sourceRef"), max_length=1000),
                        )
                    )
                    continue
                if source_identity_key:
                    existing_identity_records[source_identity_key] = candidate_record
                query_records.append(candidate_record)
            remaining_query_ids = assignment_query_ids - existing_query_ids
            if query_records:
                output_status = "completed" if not remaining_query_ids else "returned"
                try:
                    output_response = data_processing_service.record_collection_output(
                        normalized_run_id,
                        assignment_id,
                        {
                            "status": output_status,
                            "records": query_records,
                            "notes": "Automated source collection search executed one metadata-only query and wrote DataRecords for review.",
                            "qualitySignals": {
                                "searchProvider": provider,
                                "executedQueryCount": 1,
                                "queryId": query_id,
                                "metadataOnlyDownload": True,
                                "remainingQueryCount": len(remaining_query_ids),
                            },
                        },
                    )
                except data_processing_service.DataProcessingError as exc:
                    raise TeamWorkflowOrchestrationError(str(exc)) from exc
                outputs.append(output_response["output"])
                created_records.extend(output_response["createdRecords"])
                for index, record in enumerate(output_response["createdRecords"]):
                    original_record = query_records[index] if index < len(query_records) else {}
                    trace = _source_collection_record_search_trace(original_record)
                    execution_events.append(
                        _source_collection_execution_event(
                            "storage.data_record_written",
                            assignment=assignment,
                            query=trace,
                            status="completed",
                            title=f"Stored DataRecord: {record.get('title') or record.get('recordId')}",
                            summary="The search result was stored in the generic data processing run before candidate import.",
                            refs=[record.get("recordId", ""), record.get("sourceRef", "") or record.get("rawLocation", "")],
                            storage_refs=[*_source_collection_storage_refs(run), storage_artifacts["recordsPath"]],
                        )
                    )
                    import_response = import_data_record_as_source_candidate(
                        normalized_team_id,
                        normalized_run_id,
                        str(record.get("recordId") or ""),
                        {
                            "createdByAgent": _trim_text(assignment.get("agentId"), max_length=160) or agent_role or "source_collection_search_executor",
                            "tags": ["source_collection", "search_execution", agent_role],
                            "metadata": {
                                "sourceCollectionSearchExecution": True,
                                "searchProvider": provider,
                                "metadataOnlyDownload": True,
                                "assignmentId": assignment_id,
                                "agentRole": agent_role,
                                "queryId": _trim_text(trace.get("queryId"), max_length=160),
                                "query": _trim_text(trace.get("query"), max_length=1000),
                            },
                        },
                    )
                    if import_response.get("duplicate"):
                        skipped_duplicate_count += 1
                        candidate = import_response.get("candidate") if isinstance(import_response.get("candidate"), dict) else {}
                        candidate_metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
                        duplicate_key = _trim_text(candidate_metadata.get("sourceIdentityKey"), max_length=200)
                        if duplicate_key:
                            duplicate_source_keys.append(duplicate_key)
                        execution_events.append(
                            _source_collection_execution_event(
                                "storage.source_manifest_duplicate_skipped",
                                assignment=assignment,
                                query=trace,
                                status="completed",
                                title=f"Skipped duplicate source_manifest: {candidate.get('title') or candidate.get('candidateId')}",
                                summary="The DataRecord matched an existing source_manifest identity and was not imported again.",
                                refs=[candidate.get("candidateId", ""), str(record.get("recordId") or "")],
                                storage_refs=[storage_artifacts["candidatesPath"], storage_artifacts["candidateStorePath"]],
                            )
                        )
                    else:
                        imported.append(import_response)
                        execution_events.append(
                            _source_collection_execution_event(
                                "storage.source_manifest_imported",
                                assignment=assignment,
                                query=trace,
                                status="completed",
                                title=f"Imported source_manifest: {import_response['candidate'].get('title')}",
                                summary="The DataRecord was imported as a source_manifest candidate, still outside formal Team Knowledge/RAG/official graph.",
                                refs=[import_response["candidate"].get("candidateId", ""), str(record.get("recordId") or "")],
                                storage_refs=[storage_artifacts["candidatesPath"], storage_artifacts["candidateStorePath"]],
                            )
                        )
            elif query_id in attempted_query_ids:
                duplicate_only = query_skipped_duplicate_count > 0
                no_record_notes = (
                    f"Automated metadata search only found {query_skipped_duplicate_count} duplicate source(s) already present in this run; no repair is required."
                    if duplicate_only
                    else "Automated metadata search returned no importable records for this query."
                )
                try:
                    output_response = data_processing_service.record_collection_output(
                        normalized_run_id,
                        assignment_id,
                        {
                            "status": "completed" if duplicate_only and not remaining_query_ids else "returned",
                            "records": [],
                            "notes": no_record_notes,
                            "blockingIssues": [] if duplicate_only else ["no_importable_search_result"],
                            "qualitySignals": {
                                "searchProvider": provider,
                                "metadataOnlyDownload": True,
                                "queryId": query_id,
                                "remainingQueryCount": len(remaining_query_ids),
                                "skippedDuplicateCount": query_skipped_duplicate_count,
                                "duplicateOnly": duplicate_only,
                            },
                        },
                    )
                except data_processing_service.DataProcessingError as exc:
                    raise TeamWorkflowOrchestrationError(str(exc)) from exc
                outputs.append(output_response["output"])
                if duplicate_only:
                    execution_events.append(
                        _source_collection_execution_event(
                            "search.duplicates_only_output_recorded",
                            assignment=assignment,
                            query=query,
                            status="completed",
                            title=f"Recorded duplicate-only query result: {query_text}",
                            summary=no_record_notes,
                            refs=[query_id],
                            storage_refs=[storage_artifacts["recordsPath"]],
                        )
                    )

    final_run = data_processing_service.get_processing_run(normalized_run_id)
    final_assignments = data_processing_service.list_collection_assignments(normalized_run_id)["assignments"]
    final_records_payload = data_processing_service.list_records(normalized_run_id)
    final_status = data_processing_service.get_processing_status(normalized_run_id)
    final_existing_query_ids = _source_collection_existing_query_ids(list(final_records_payload.get("records") or []))
    next_runnable_query_ids = _source_collection_next_runnable_query_ids(
        [item for item in list(final_assignments or []) if isinstance(item, dict)],
        final_existing_query_ids,
        force=False,
        target_assignment_ids=target_assignment_ids,
        target_agent_role=target_agent_role,
    )
    remaining_query_count = len(next_runnable_query_ids)
    source_collection_summary = _source_collection_assignment_stage_summary(
        [item for item in list(final_assignments or []) if isinstance(item, dict)]
    )
    final_status_summary = final_status.get("summary") if isinstance(final_status.get("summary"), dict) else {}
    final_status_summary.update(source_collection_summary)
    final_status["summary"] = final_status_summary
    _append_source_collection_execution_artifacts(
        normalized_team_id,
        normalized_run_id,
        execution_events=execution_events,
        created_records=created_records,
        imported=imported,
    )
    _record_workflow_event(
        "source_collection.search_executed",
        normalized_team_id,
        fields={
            "runId": normalized_run_id,
            "provider": provider,
            "executedQueryCount": executed_query_count,
            "skippedQueryCount": skipped_query_count,
            "failedQueryCount": failed_query_count,
            "recordCount": len(created_records),
            "createdUniqueRecordCount": len(created_records),
            "importedCount": len(imported),
            "skippedDuplicateCount": skipped_duplicate_count,
            "duplicateSourceKeys": duplicate_source_keys[:20],
            "remainingQueryCount": remaining_query_count,
            "hasMore": remaining_query_count > 0,
            "sourceCollectionRunDirectory": storage_artifacts["runDirectory"],
        },
        child_log_path=f"artifacts/source-collection-{_safe_token(normalized_run_id, default='run', max_length=96)}-query-summary.jsonl",
        child_log_payload={
            "teamId": normalized_team_id,
            "runId": normalized_run_id,
            "provider": provider,
            "queryEvents": _source_collection_query_event_summaries(execution_events),
            "summary": {
                "executedQueryCount": executed_query_count,
                "skippedQueryCount": skipped_query_count,
                "failedQueryCount": failed_query_count,
                "recordCount": len(created_records),
                "importedCount": len(imported),
                "skippedDuplicateCount": skipped_duplicate_count,
                "remainingQueryCount": remaining_query_count,
            },
        },
    )
    status_label = "executed" if created_records else ("duplicates_skipped" if skipped_duplicate_count else ("partial" if executed_query_count or failed_query_count else "no_open_assignment"))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "runId": normalized_run_id,
        "status": status_label,
        "provider": provider,
        "executedQueryCount": executed_query_count,
        "skippedQueryCount": skipped_query_count,
        "failedQueryCount": failed_query_count,
        "resultCount": result_count,
        "recordCount": len(created_records),
        "createdUniqueRecordCount": len(created_records),
        "outputCount": len(outputs),
        "importedCount": len(imported),
        "skippedDuplicateCount": skipped_duplicate_count,
        "duplicateSourceKeys": duplicate_source_keys[:20],
        "remainingQueryCount": remaining_query_count,
        "nextRunnableQueryIds": next_runnable_query_ids[:12],
        "hasMore": remaining_query_count > 0,
        "run": final_run,
        "runStatus": final_status,
        "sourceCollectionSummary": source_collection_summary,
        "storageArtifacts": storage_artifacts,
        "assignments": final_assignments,
        "outputs": outputs,
        "createdRecords": created_records,
        "imported": imported,
        "executionEvents": execution_events,
        "boundaries": {
            "externalSearchTriggered": executed_query_count > 0,
            "metadataOnlyDownload": True,
            "writesFormalKnowledge": False,
            "writesRag": False,
            "writesOfficialGraph": False,
        },
        "nextActions": [
            "Review imported source_manifest candidates before source quality screening.",
            "Run source quality assessment for accepted candidates.",
            "Keep formal Team Knowledge/RAG/official graph writes behind the later governance gate.",
        ],
    }


def open_source_collection_storage_target(team_id: str, run_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    normalized_run_id = _normalize_required_id(run_id, "Data processing run id is required.")
    team_service.get_team(normalized_team_id)
    request_payload = payload if isinstance(payload, dict) else {}
    target = _trim_text(request_payload.get("target"), max_length=80).lower() or "run_directory"
    if target not in SOURCE_COLLECTION_STORAGE_OPEN_TARGETS:
        raise TeamWorkflowOrchestrationError(f"Unsupported source collection storage target: {target or '<empty>'}")
    try:
        run = data_processing_service.get_processing_run(normalized_run_id)
    except data_processing_service.DataProcessingError as exc:
        raise TeamWorkflowOrchestrationError(str(exc)) from exc
    run_scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
    run_team_id = _trim_text(run_scope.get("teamId"), max_length=128)
    if run_team_id and run_team_id != normalized_team_id:
        raise TeamWorkflowOrchestrationError("Data processing run does not belong to this team.")
    target_path = _source_collection_storage_target_path(normalized_team_id, normalized_run_id, target)
    if target in {"run_directory", "artifacts_directory"}:
        target_path.mkdir(parents=True, exist_ok=True)
        opened_path = target_path
        target_exists = True
    else:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_exists = target_path.exists()
        opened_path = target_path if target_exists else target_path.parent
    _ensure_project_child(opened_path)
    _open_local_path(opened_path)
    storage_artifacts = _source_collection_storage_artifacts(normalized_team_id, normalized_run_id)
    _record_workflow_event(
        "source_collection.storage_opened",
        normalized_team_id,
        fields={
            "runId": normalized_run_id,
            "target": target,
            "path": _relative_path(target_path),
            "openedPath": _relative_path(opened_path),
            "targetExists": target_exists,
        },
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "runId": normalized_run_id,
        "target": target,
        "path": _relative_path(target_path),
        "openedPath": _relative_path(opened_path),
        "targetExists": target_exists,
        "storageArtifacts": storage_artifacts,
    }


def load_source_collection_work_run_summary() -> dict[str, Any]:
    store = _source_collection_work_run_store()
    active = store.load_active_snapshot(SOURCE_COLLECTION_WORK_RUN_KIND)
    return {
        "active": active,
        "latest": store.load_latest_snapshot(SOURCE_COLLECTION_WORK_RUN_KIND),
        "activeItems": [active] if isinstance(active, dict) else [],
    }


def _sync_source_collection_stage_round_after_search(
    team_id: str,
    run_id: str,
    result: dict[str, Any],
    *,
    terminal_status: str,
    terminal_summary: str,
) -> dict[str, Any] | None:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    normalized_run_id = _normalize_required_id(run_id, "Data processing run id is required.")
    try:
        run_status = data_processing_service.get_processing_status(normalized_run_id)
    except data_processing_service.DataProcessingError:
        run_status = {}
    run_status_summary = run_status.get("summary") if isinstance(run_status.get("summary"), dict) else {}
    candidate_store = _load_candidate_store(normalized_team_id)
    run_candidate_count = _source_collection_candidate_count_for_run(candidate_store, normalized_run_id)
    source_collection_summary = result.get("sourceCollectionSummary") if isinstance(result.get("sourceCollectionSummary"), dict) else {}
    stage_status = _source_collection_stage_round_status_after_search(
        terminal_status,
        result=result,
        run_status_summary=run_status_summary,
        source_collection_summary=source_collection_summary,
        run_candidate_count=run_candidate_count,
    )
    now = utc_now_iso()
    synced_round: dict[str, Any] | None = None
    workflow_id = ""
    with _WORKFLOW_LOCK:
        store = _load_stage_round_store(normalized_team_id)
        rounds = _stage_rounds(store)
        stage_round = _latest_stage_round(
            [
                item
                for item in rounds
                if str(item.get("stageType") or "") == "knowledge_collection"
                and normalized_run_id in {str(source_run_id) for source_run_id in list(item.get("sourceRunIds") or [])}
            ]
        )
        if stage_round is None:
            return None
        workflow = _load_or_create_workflow(normalized_team_id)
        workflow_id = str(workflow.get("workflowId") or "")
        previous_execution = stage_round.get("sourceCollectionSearchExecution") if isinstance(stage_round.get("sourceCollectionSearchExecution"), dict) else {}
        stage_round["sourceCollectionSearchExecution"] = {
            **previous_execution,
            "runId": normalized_run_id,
            "status": terminal_status,
            "resultStatus": _trim_text(result.get("status"), max_length=80),
            "executionMode": previous_execution.get("executionMode") or "background",
            "accepted": bool(previous_execution.get("accepted")),
            "provider": _trim_text(result.get("provider"), max_length=80) or previous_execution.get("provider") or SOURCE_COLLECTION_SEARCH_PROVIDER_CROSSREF,
            "executedQueryCount": _source_collection_count(result.get("executedQueryCount")),
            "failedQueryCount": _source_collection_count(result.get("failedQueryCount")),
            "recordCount": _source_collection_count(run_status_summary.get("recordCount") or result.get("recordCount")),
            "importedCount": _source_collection_count(result.get("importedCount")),
            "skippedDuplicateCount": _source_collection_count(result.get("skippedDuplicateCount")),
            "remainingQueryCount": _source_collection_count(result.get("remainingQueryCount")),
            "hasMore": bool(result.get("hasMore")),
            "activeWorkRunId": "",
            "summary": _trim_text(terminal_summary, max_length=500),
            "updatedAt": now,
        }
        stage_round["sourceCollectionSummary"] = {
            **source_collection_summary,
            "recordCount": _source_collection_count(run_status_summary.get("recordCount")),
            "candidateCount": run_candidate_count,
        }
        stage_round["status"] = stage_status
        stage_round["updatedAt"] = now
        stage_round["teamMemoryRecord"] = _stage_memory_record(stage_round, workflow)
        stage_round["teamMemoryRecordId"] = stage_round["teamMemoryRecord"]["recordId"]
        workflow["activeWorkflowItems"] = _upsert_active_item(
            workflow.get("activeWorkflowItems"),
            candidate_id=normalized_run_id,
            current_node="knowledge_collection",
            status=f"source_collection_{stage_status}",
            transfer_id="",
        )
        workflow["updatedAt"] = now
        store["updatedAt"] = now
        _write_json(_stage_round_store_path(normalized_team_id), store)
        _write_json(_workflow_path(normalized_team_id), workflow)
        synced_round = dict(stage_round)
    _record_workflow_event(
        "research_stage_round.source_collection_search_synced",
        normalized_team_id,
        fields={
            "workflowId": workflow_id,
            "runId": normalized_run_id,
            "stageRoundId": synced_round.get("stageRoundId", "") if synced_round else "",
            "status": stage_status,
            "searchStatus": terminal_status,
            "recordCount": _source_collection_count(run_status_summary.get("recordCount")),
            "candidateCount": run_candidate_count,
        },
    )
    return synced_round


def _sync_source_collection_stage_round_from_latest_work_run(team_id: str, run_id: str) -> dict[str, Any] | None:
    latest = load_source_collection_work_run_summary().get("latest")
    if not isinstance(latest, dict) or str(latest.get("runId") or "") != run_id:
        return None
    latest_status = str(latest.get("status") or "").lower()
    if latest_status in {"queued", "running"}:
        return None
    result = {
        "status": latest_status,
        "provider": SOURCE_COLLECTION_SEARCH_PROVIDER_CROSSREF,
        "executedQueryCount": _source_collection_count(latest.get("executedQueryCount")),
        "failedQueryCount": _source_collection_count(latest.get("failedQueryCount")),
        "recordCount": _source_collection_count(latest.get("recordCount")),
        "importedCount": _source_collection_count(latest.get("importedCount")),
        "skippedDuplicateCount": _source_collection_count(latest.get("skippedDuplicateCount")),
        "remainingQueryCount": _source_collection_count(latest.get("searchOpenAssignmentCount")),
        "hasMore": latest_status == "needs_continue",
        "sourceCollectionSummary": latest.get("sourceCollection") if isinstance(latest.get("sourceCollection"), dict) else {},
    }
    synced = _sync_source_collection_stage_round_after_search(
        team_id,
        run_id,
        result,
        terminal_status=latest_status or "completed",
        terminal_summary=_trim_text(latest.get("summary"), max_length=500) or "资料搜索已结束。",
    )
    if synced is not None:
        _record_workflow_event(
            "research_stage_round.source_collection_search_recovered_from_work_run",
            team_id,
            fields={
                "runId": run_id,
                "stageRoundId": synced.get("stageRoundId", ""),
                "status": synced.get("status", ""),
                "searchStatus": latest_status or "completed",
                "recordCount": _source_collection_count(latest.get("recordCount")),
                "importedCount": _source_collection_count(latest.get("importedCount")),
                "remainingQueryCount": _source_collection_count(latest.get("searchOpenAssignmentCount")),
            },
        )
    return synced


def _source_collection_stage_round_status_after_search(
    terminal_status: str,
    *,
    result: dict[str, Any],
    run_status_summary: dict[str, Any],
    source_collection_summary: dict[str, Any],
    run_candidate_count: int,
) -> str:
    normalized = str(terminal_status or "").lower()
    if normalized == "failed":
        return "needs_attention"
    if normalized == "needs_continue":
        return "needs_continue"
    if _source_collection_count(result.get("remainingQueryCount")) or bool(result.get("hasMore")):
        return "needs_continue"
    if _source_collection_count(source_collection_summary.get("searchOpenAssignmentCount")):
        return "needs_continue"
    if (
        _source_collection_count(source_collection_summary.get("downstreamOpenAssignmentCount"))
        or run_candidate_count
        or _source_collection_count(run_status_summary.get("recordCount"))
        or _source_collection_count(result.get("importedCount"))
    ):
        return "needs_screening"
    return "completed"


def _materialize_source_collection_stage_writeback_sources(
    team_id: str,
    run_id: str,
    task: dict[str, Any],
    writeback: dict[str, Any],
) -> dict[str, Any]:
    status = _trim_text(writeback.get("status"), max_length=80).lower()
    result = writeback.get("result") if isinstance(writeback.get("result"), dict) else {}
    if status not in SOURCE_COLLECTION_STAGE_WRITEBACK_MATERIALIZED_STATUSES:
        return _source_collection_stage_writeback_materialization_summary(status="skipped_status")

    leads = _source_collection_stage_writeback_source_leads(result)
    if not leads:
        return _source_collection_stage_writeback_materialization_summary(status="no_structured_sources")

    try:
        records_payload = data_processing_service.list_records(run_id)
    except data_processing_service.DataProcessingError as exc:
        return _source_collection_stage_writeback_materialization_summary(
            status="failed",
            failed=[{"reason": "records_unavailable", "error": str(exc)}],
        )
    existing_records = [item for item in list(records_payload.get("records") or []) if isinstance(item, dict)]
    existing_identity_records = _source_collection_existing_identity_records(existing_records)

    created_records: list[dict[str, Any]] = []
    imported_candidates: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    normalized_team_id = _trim_text(team_id, max_length=128)
    normalized_run_id = _trim_text(run_id, max_length=128)
    stage_id = _trim_text(task.get("stageId"), max_length=80)
    agent_id = _trim_text(task.get("agentId"), max_length=160)
    agent_role = _trim_text(task.get("agentRole"), max_length=80)
    task_id = _trim_text(task.get("taskId"), max_length=160)

    for index, lead in enumerate(leads, start=1):
        record_payload = _source_collection_stage_writeback_record_payload(
            lead,
            team_id=normalized_team_id,
            run_id=normalized_run_id,
            task_id=task_id,
            stage_id=stage_id,
            agent_id=agent_id,
            agent_role=agent_role,
            index=index,
        )
        if not record_payload:
            skipped.append(
                {
                    "reason": "insufficient_source_identity",
                    "leadId": _trim_text(lead.get("leadId") or lead.get("id"), max_length=160),
                    "title": _trim_text(lead.get("title"), max_length=240),
                }
            )
            continue
        source_identity_key = _source_collection_record_identity_key(record_payload)
        record = existing_identity_records.get(source_identity_key) if source_identity_key else None
        if record is None:
            try:
                record = data_processing_service.add_record(normalized_run_id, record_payload)
            except data_processing_service.DataProcessingError as exc:
                failed.append(
                    {
                        "reason": "data_record_create_failed",
                        "leadId": _trim_text(lead.get("leadId") or lead.get("id"), max_length=160),
                        "title": _trim_text(record_payload.get("title"), max_length=240),
                        "error": str(exc),
                    }
                )
                continue
            created_records.append(record)
            if source_identity_key:
                existing_identity_records[source_identity_key] = record
        try:
            import_response = import_data_record_as_source_candidate(
                normalized_team_id,
                normalized_run_id,
                _trim_text(record.get("recordId"), max_length=160),
                {
                    "createdByAgent": agent_id or agent_role or "source_collection_stage_writeback",
                    "tags": [item for item in ["source_collection", "stage_writeback", agent_role] if item],
                    "metadata": {
                        "sourceCollectionStageWriteback": True,
                        "sourceCollectionStageTaskId": task_id,
                        "sourceCollectionStageId": stage_id,
                        "sourceCollectionStageAgentId": agent_id,
                        "sourceCollectionStageAgentRole": agent_role,
                        "sourceCollectionLeadId": _trim_text(lead.get("leadId") or lead.get("id"), max_length=160),
                    },
                },
            )
        except TeamWorkflowOrchestrationError as exc:
            failed.append(
                {
                    "reason": "candidate_import_failed",
                    "recordId": _trim_text(record.get("recordId"), max_length=160),
                    "error": str(exc),
                }
            )
            continue
        if import_response.get("created"):
            candidate = import_response.get("candidate") if isinstance(import_response.get("candidate"), dict) else {}
            imported_candidates.append(
                {
                    "candidateId": _trim_text(candidate.get("candidateId"), max_length=160),
                    "recordId": _trim_text(record.get("recordId"), max_length=160),
                    "title": _trim_text(candidate.get("title") or record.get("title"), max_length=240),
                }
            )
        else:
            candidate = import_response.get("candidate") if isinstance(import_response.get("candidate"), dict) else {}
            skipped.append(
                {
                    "reason": "duplicate_source_candidate",
                    "recordId": _trim_text(record.get("recordId"), max_length=160),
                    "candidateId": _trim_text(candidate.get("candidateId"), max_length=160),
                }
            )

    summary = _source_collection_stage_writeback_materialization_summary(
        status="completed",
        source_lead_count=len(leads),
        created_records=created_records,
        imported_candidates=imported_candidates,
        skipped=skipped,
        failed=failed,
    )
    _record_workflow_event(
        "source_collection.stage_session_task_sources_materialized",
        normalized_team_id,
        fields={
            "runId": normalized_run_id,
            "taskId": task_id,
            "stageId": stage_id,
            "agentId": agent_id,
            "sourceLeadCount": summary["sourceLeadCount"],
            "createdRecordCount": summary["createdRecordCount"],
            "importedCandidateCount": summary["importedCandidateCount"],
            "skippedDuplicateCount": summary["skippedDuplicateCount"],
            "failedCount": summary["failedCount"],
        },
        level="warning" if summary["failedCount"] else "info",
        outcome="failed" if summary["failedCount"] and not summary["createdRecordCount"] else "completed",
        lifecycle=bool(summary["failedCount"]),
    )
    return summary


def _materialize_source_collection_stage_writeback_quality(
    team_id: str,
    run_id: str,
    task: dict[str, Any],
    writeback: dict[str, Any],
) -> dict[str, Any]:
    stage_id = _trim_text(task.get("stageId"), max_length=80)
    agent_role = _trim_text(task.get("agentRole"), max_length=80)
    if stage_id != "screening" and agent_role != "source_quality":
        return _source_collection_stage_writeback_quality_summary(status="skipped_stage")
    status = _trim_text(writeback.get("status"), max_length=80).lower()
    if status not in SOURCE_COLLECTION_STAGE_WRITEBACK_MATERIALIZED_STATUSES:
        return _source_collection_stage_writeback_quality_summary(status="skipped_status")
    result = writeback.get("result") if isinstance(writeback.get("result"), dict) else {}
    decisions = _source_collection_stage_writeback_candidate_decisions(result)
    if not decisions:
        return _source_collection_stage_writeback_quality_summary(status="no_candidate_decisions")

    source_candidate_ids = {
        _trim_text(item.get("candidateId"), max_length=160)
        for item in _source_collection_candidates_for_run(team_id, run_id)
        if _trim_text(item.get("candidateId"), max_length=160)
    }
    assessed_by_agent = (
        _trim_text(writeback.get("recordedByAgent"), max_length=160)
        or _trim_text(task.get("agentId"), max_length=160)
        or "Source Quality Assessment Agent"
    )
    assessed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for decision_payload in decisions:
        candidate_id = _trim_text(
            decision_payload.get("candidateId")
            or decision_payload.get("candidate_id")
            or decision_payload.get("id"),
            max_length=160,
        )
        if not candidate_id:
            skipped.append({"reason": "missing_candidate_id"})
            continue
        if candidate_id in seen:
            skipped.append({"candidateId": candidate_id, "reason": "duplicate_decision"})
            continue
        seen.add(candidate_id)
        if candidate_id not in source_candidate_ids:
            skipped.append({"candidateId": candidate_id, "reason": "candidate_not_in_source_collection_run"})
            continue
        normalized_decision = _source_collection_stage_writeback_quality_decision(decision_payload)
        if not normalized_decision:
            skipped.append({"candidateId": candidate_id, "reason": "unsupported_decision"})
            continue
        assessment_payload = {
            "assessedByAgent": assessed_by_agent,
            "decision": normalized_decision,
            "notes": _source_collection_stage_writeback_quality_notes(decision_payload, writeback),
            "requiredFixes": _normalize_text_list(
                decision_payload.get("requiredFixes") or decision_payload.get("required_fixes") or decision_payload.get("fixes"),
                max_items=12,
                max_length=240,
            ),
            "riskFlags": _normalize_text_list(
                decision_payload.get("riskFlags") or decision_payload.get("risk_flags") or decision_payload.get("risks"),
                max_items=12,
                max_length=120,
            ),
            "evidenceRefs": _normalize_ref_list(
                decision_payload.get("evidenceRefs") or decision_payload.get("evidence_refs") or writeback.get("evidenceRefs"),
                max_items=24,
            ),
        }
        try:
            response = assess_source_candidate_quality(team_id, candidate_id, assessment_payload)
        except (team_service.TeamServiceError, TeamWorkflowOrchestrationError) as exc:
            failed.append({"candidateId": candidate_id, "reason": "assessment_failed", "error": str(exc)})
            continue
        assessment = response.get("assessment") if isinstance(response.get("assessment"), dict) else {}
        assessed.append(
            {
                "candidateId": candidate_id,
                "decision": normalized_decision,
                "assessmentId": _trim_text(assessment.get("assessmentId"), max_length=160),
            }
        )

    summary = _source_collection_stage_writeback_quality_summary(
        status="completed" if assessed else ("failed" if failed else "no_assessable_decisions"),
        assessed=assessed,
        skipped=skipped,
        failed=failed,
    )
    _record_workflow_event(
        "source_collection.stage_session_task_quality_materialized",
        team_id,
        fields={
            "runId": _trim_text(run_id, max_length=160),
            "taskId": _trim_text(task.get("taskId"), max_length=160),
            "stageId": stage_id,
            "agentId": _trim_text(task.get("agentId"), max_length=160),
            "assessedCandidateCount": summary["assessedCandidateCount"],
            "approvedCandidateCount": summary["approvedCandidateCount"],
            "needsRevisionCandidateCount": summary["needsRevisionCandidateCount"],
            "rejectedCandidateCount": summary["rejectedCandidateCount"],
            "skippedCandidateCount": summary["skippedCandidateCount"],
            "failedCandidateCount": summary["failedCandidateCount"],
        },
        level="warning" if summary["failedCandidateCount"] else "info",
        outcome="failed" if summary["failedCandidateCount"] and not summary["assessedCandidateCount"] else "completed",
        lifecycle=bool(summary["failedCandidateCount"]),
    )
    return summary


def _materialize_source_collection_stage_writeback_candidate_graph(
    team_id: str,
    run_id: str,
    task: dict[str, Any],
    writeback: dict[str, Any],
) -> dict[str, Any]:
    stage_id = _trim_text(task.get("stageId"), max_length=80)
    agent_role = _trim_text(task.get("agentRole"), max_length=80)
    if stage_id != "graph" and agent_role != "candidate_graph":
        return _source_collection_stage_writeback_candidate_graph_summary(status="skipped_stage")
    status = _trim_text(writeback.get("status"), max_length=80).lower()
    if status not in SOURCE_COLLECTION_STAGE_WRITEBACK_MATERIALIZED_STATUSES:
        return _source_collection_stage_writeback_candidate_graph_summary(status="skipped_status")
    result = writeback.get("result") if isinstance(writeback.get("result"), dict) else {}
    agent_graph = result.get("candidateGraph") if isinstance(result.get("candidateGraph"), dict) else {}
    created_by_agent = (
        _trim_text(writeback.get("recordedByAgent"), max_length=160)
        or _trim_text(task.get("agentId"), max_length=160)
        or "Candidate Graph Agent"
    )
    try:
        graph_response = build_candidate_graph(
            team_id,
            {
                "createdByAgent": created_by_agent,
                "sourceCollectionRunId": run_id,
                "title": _trim_text(writeback.get("summary"), max_length=240) or "Source collection candidate graph",
            },
        )
    except (team_service.TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        summary = _source_collection_stage_writeback_candidate_graph_summary(
            status="failed",
            failed=[{"reason": "candidate_graph_build_failed", "error": str(exc)}],
        )
        _record_workflow_event(
            "source_collection.stage_session_task_candidate_graph_materialized",
            team_id,
            fields={
                "runId": _trim_text(run_id, max_length=160),
                "taskId": _trim_text(task.get("taskId"), max_length=160),
                "stageId": stage_id,
                "agentId": _trim_text(task.get("agentId"), max_length=160),
                "failedCount": summary["failedCandidateGraphCount"],
            },
            level="warning",
            outcome="failed",
            lifecycle=True,
        )
        return summary

    candidate_graph = graph_response.get("candidateGraph") if isinstance(graph_response.get("candidateGraph"), dict) else {}
    graph = graph_response.get("graph") if isinstance(graph_response.get("graph"), dict) else {}
    graph_summary = graph.get("summary") if isinstance(graph.get("summary"), dict) else {}
    candidate_graph_id = _trim_text(candidate_graph.get("candidateId"), max_length=160)
    if candidate_graph_id:
        _attach_candidate_graph_stage_writeback_metadata(
            team_id,
            candidate_graph_id,
            task=task,
            writeback=writeback,
            graph_response=graph_response,
            agent_graph=agent_graph,
        )
    materialized = {
        "candidateGraphId": candidate_graph_id,
        "nodeCount": _source_collection_count(graph_summary.get("nodeCount")),
        "edgeCount": _source_collection_count(graph_summary.get("edgeCount")),
        "missingLinkCount": _source_collection_count(graph_summary.get("missingLinkCount")),
        "unreviewedNodeCount": _source_collection_count(graph_summary.get("unreviewedNodeCount")),
        "inputCandidateCount": _source_collection_count(graph_summary.get("inputCandidateCount")),
        "filteredCandidateCount": _source_collection_count(graph_summary.get("filteredCandidateCount")),
        "reusedCandidateGraph": bool(graph_response.get("reusedCandidateGraph")),
        "ingestionFingerprint": _trim_text(graph_response.get("ingestionFingerprint"), max_length=160),
    }
    summary = _source_collection_stage_writeback_candidate_graph_summary(
        status="completed" if candidate_graph_id else "failed",
        candidate_graph=materialized,
        failed=[] if candidate_graph_id else [{"reason": "candidate_graph_missing_id"}],
    )
    _record_workflow_event(
        "source_collection.stage_session_task_candidate_graph_materialized",
        team_id,
        fields={
            "runId": _trim_text(run_id, max_length=160),
            "taskId": _trim_text(task.get("taskId"), max_length=160),
            "stageId": stage_id,
            "agentId": _trim_text(task.get("agentId"), max_length=160),
            "candidateGraphId": candidate_graph_id,
            "nodeCount": summary["nodeCount"],
            "edgeCount": summary["edgeCount"],
            "createdCandidateGraphCount": summary["createdCandidateGraphCount"],
            "reusedCandidateGraph": summary["reusedCandidateGraph"],
            "failedCount": summary["failedCandidateGraphCount"],
        },
        level="warning" if summary["failedCandidateGraphCount"] else "info",
        outcome="failed" if summary["failedCandidateGraphCount"] else "completed",
        lifecycle=bool(summary["failedCandidateGraphCount"]),
    )
    return summary


def _materialize_source_collection_stage_writeback_knowledge_ingestion(
    team_id: str,
    run_id: str,
    task: dict[str, Any],
    writeback: dict[str, Any],
) -> dict[str, Any]:
    stage_id = _trim_text(task.get("stageId"), max_length=80)
    agent_role = _trim_text(task.get("agentRole"), max_length=80)
    if not _source_collection_stage_can_materialize_formal_knowledge(stage_id, agent_role):
        return _source_collection_stage_writeback_knowledge_ingestion_summary(status="skipped_stage")
    status = _trim_text(writeback.get("status"), max_length=80).lower()
    if status not in SOURCE_COLLECTION_STAGE_WRITEBACK_MATERIALIZED_STATUSES:
        return _source_collection_stage_writeback_knowledge_ingestion_summary(status="skipped_status")

    result = writeback.get("result") if isinstance(writeback.get("result"), dict) else {}
    approved_refs = _source_collection_stage_writeback_approved_candidate_refs(result, writeback)
    if not approved_refs:
        return _source_collection_stage_writeback_knowledge_ingestion_summary(status="no_approved_candidates")

    source_candidates = {
        _trim_text(item.get("candidateId"), max_length=160): item
        for item in _source_collection_candidates_for_run(team_id, run_id)
        if _trim_text(item.get("candidateId"), max_length=160)
    }
    source_candidate_ids = set(source_candidates.keys())
    selected_candidates: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in approved_refs:
        candidate_id = _trim_text(ref.get("candidateId"), max_length=160)
        if not candidate_id:
            skipped.append({"reason": "missing_candidate_id"})
            continue
        if candidate_id in seen:
            skipped.append({"candidateId": candidate_id, "reason": "duplicate_approved_candidate"})
            continue
        seen.add(candidate_id)
        candidate = source_candidates.get(candidate_id)
        if candidate is None:
            skipped.append({"candidateId": candidate_id, "reason": "candidate_not_in_source_collection_run"})
            continue
        if _source_quality_bucket(candidate) != "approved":
            skipped.append({"candidateId": candidate_id, "reason": "candidate_not_source_quality_approved"})
            continue
        selected_candidates.append(candidate)

    if not selected_candidates:
        return _source_collection_stage_writeback_knowledge_ingestion_summary(
            status="no_ingestable_candidates",
            approved=approved_refs,
            skipped=skipped,
        )

    steward_agent_id = (
        _trim_text(writeback.get("recordedByAgent"), max_length=160)
        or _trim_text(task.get("agentId"), max_length=160)
        or agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID
    )
    try:
        with _WORKFLOW_LOCK:
            workflow = _load_or_create_workflow(team_id)
            candidate_store = _load_candidate_store(team_id)
            stored_candidates = [item for item in list(candidate_store.get("candidates") or []) if isinstance(item, dict)]
            selected_candidate_ids = {str(item.get("candidateId") or "") for item in selected_candidates if str(item.get("candidateId") or "")}
            existing = _source_collection_existing_official_knowledge_ingestion(
                stored_candidates,
                source_candidate_ids=source_candidate_ids,
                selected_candidate_ids=selected_candidate_ids,
            )
            graph_candidates = [
                item
                for item in stored_candidates
                if str(item.get("candidateType") or "") == "candidate_graph"
                and not _candidate_is_archived(item)
                and _source_collection_candidate_graph_matches_run(item, source_candidate_ids)
            ]
            latest_graph = _latest_candidate_record(graph_candidates)
            workflow_id = str(workflow.get("workflowId") or "")
        if existing:
            return _source_collection_stage_writeback_existing_knowledge_ingestion_summary(
                existing,
                selected_candidates=selected_candidates,
                skipped=skipped,
            )

        knowledge_base = _source_collection_stage_writeback_resolve_knowledge_base(team_id, steward_agent_id)
        knowledge_base_id = _trim_text(knowledge_base.get("knowledgeBaseId"), max_length=160)
        if not knowledge_base_id:
            raise TeamWorkflowOrchestrationError("Knowledge base id is required before steward writeback ingestion.")
        team_knowledge_service.ensure_knowledge_base_review_grant(knowledge_base_id, steward_agent_id)
        target_domain = _source_collection_stage_writeback_target_domain(result)
        output = _build_knowledge_ingestion_precheck_output(
            team_id,
            workflow_id,
            selected_candidates,
            latest_graph,
            target_domain=target_domain,
        )
        proposal_payload = output.get("proposalPayload") if isinstance(output.get("proposalPayload"), dict) else {}
        if len(selected_candidates) == 1:
            candidate_title = _source_manifest_label(selected_candidates[0])
            proposal_payload["title"] = candidate_title
            proposal_payload["summary"] = _trim_text(selected_candidates[0].get("summary"), max_length=1000) or proposal_payload.get("summary", "")
            output["proposalPayload"] = proposal_payload
        source_trace = output.get("sourceTrace") if isinstance(output.get("sourceTrace"), dict) else {}
        source_trace.update(
            {
                "sourceCollectionRunId": _trim_text(run_id, max_length=160),
                "stageTaskId": _trim_text(task.get("taskId"), max_length=160),
                "stageId": stage_id,
                "approvedByAgentId": steward_agent_id,
            }
        )
        output["sourceTrace"] = source_trace
        output["knowledgeCollectionIngestion"] = {
            "purpose": "source_collection_stage_writeback",
            "sourceCollectionRunId": _trim_text(run_id, max_length=160),
            "stageTaskId": _trim_text(task.get("taskId"), max_length=160),
        }
        record_response = record_local_research_model_output(
            team_id,
            {
                "taskType": "steward_pack_draft",
                "title": "知识库管理员入库审核包",
                "summary": _trim_text(writeback.get("summary"), max_length=1000)
                or f"知识库管理员通过 {len(selected_candidates)} 条资料，生成团队知识库入库包。",
                "createdByAgent": steward_agent_id,
                "output": output,
            },
        )
        steward_candidate = record_response.get("candidate") if isinstance(record_response.get("candidate"), dict) else {}
        steward_candidate_id = _trim_text(steward_candidate.get("candidateId"), max_length=160)
        source_pending = submit_steward_pack_to_knowledge_ingestion(
            team_id,
            steward_candidate_id,
            {
                "knowledgeBaseId": knowledge_base_id,
                "proposedByAgentId": steward_agent_id,
            },
        )
        source_metadata = (source_pending.get("candidate") or {}).get("metadata") if isinstance((source_pending.get("candidate") or {}).get("metadata"), dict) else {}
        source_ingestion = source_metadata.get("knowledgeIngestion") if isinstance(source_metadata.get("knowledgeIngestion"), dict) else {}
        inbox_source_id = _trim_text(source_ingestion.get("inboxSourceId"), max_length=160)
        if not inbox_source_id:
            raise TeamWorkflowOrchestrationError("Steward pack source inbox id was not created.")
        reviewed_source = team_knowledge_service.review_owner_inbox_source(
            "team",
            team_id,
            inbox_source_id,
            decision="accepted",
            reviewed_by_agent_id=steward_agent_id,
            resolution_note="知识库管理员阶段回写通过资料，自动接受入库包来源。",
        )
        central_source_id = _trim_text((reviewed_source.get("centralSource") or {}).get("centralSourceId"), max_length=160)
        knowledge_submission = submit_steward_pack_to_knowledge_ingestion(
            team_id,
            steward_candidate_id,
            {
                "knowledgeBaseId": knowledge_base_id,
                "proposedByAgentId": steward_agent_id,
                "centralSourceId": central_source_id,
            },
        )
        knowledge_review = review_steward_pack_knowledge_ingestion(
            team_id,
            steward_candidate_id,
            {
                "knowledgeBaseId": knowledge_base_id,
                "reviewedByAgentId": steward_agent_id,
                "decision": "approved",
                "resolutionNote": "知识库管理员已在阶段私聊中审核通过候选资料，按现有知识治理门禁应用为正式团队知识。",
            },
        )
    except (
        TeamWorkflowOrchestrationError,
        team_service.TeamServiceError,
        team_knowledge_service.TeamKnowledgeError,
        team_knowledge_service.TeamKnowledgeNotFoundError,
    ) as exc:
        summary = _source_collection_stage_writeback_knowledge_ingestion_summary(
            status="failed",
            approved=approved_refs,
            skipped=skipped,
            failed=[{"reason": "knowledge_ingestion_failed", "error": _trim_text(exc, max_length=800)}],
        )
        _record_workflow_event(
            "source_collection.stage_session_task_knowledge_ingestion_failed",
            team_id,
            fields={
                "runId": _trim_text(run_id, max_length=160),
                "taskId": _trim_text(task.get("taskId"), max_length=160),
                "stageId": stage_id,
                "agentId": _trim_text(task.get("agentId"), max_length=160),
                "approvedCandidateCount": len(selected_candidates),
                "errorType": type(exc).__name__,
                "error": _trim_text(exc, max_length=500),
            },
            level="warning",
            outcome="failed",
            lifecycle=True,
        )
        return summary

    review_ingestion = knowledge_review.get("knowledgeIngestion") if isinstance(knowledge_review.get("knowledgeIngestion"), dict) else {}
    official_record = review_ingestion.get("officialSyncRecord") if isinstance(review_ingestion.get("officialSyncRecord"), dict) else {}
    knowledge_item_ids = _normalize_id_values(official_record.get("knowledgeItemIds"))
    submission_candidate = knowledge_submission.get("candidate") if isinstance(knowledge_submission.get("candidate"), dict) else {}
    submission_metadata = submission_candidate.get("metadata") if isinstance(submission_candidate.get("metadata"), dict) else {}
    submission_ingestion = submission_metadata.get("knowledgeIngestion") if isinstance(submission_metadata.get("knowledgeIngestion"), dict) else {}
    summary = _source_collection_stage_writeback_knowledge_ingestion_summary(
        status="completed" if knowledge_item_ids else "applied_without_formal_item",
        approved=approved_refs,
        ingested=selected_candidates,
        skipped=skipped,
        steward_pack_candidate_id=steward_candidate_id,
        knowledge_base_id=knowledge_base_id,
        knowledge_item_ids=knowledge_item_ids,
        writes_official_graph=bool(official_record.get("writesOfficialGraph")),
        source_review_status=_trim_text(reviewed_source.get("status"), max_length=80)
        or _trim_text((reviewed_source.get("source") or {}).get("status"), max_length=80),
        proposal_id=_trim_text(submission_ingestion.get("proposalId"), max_length=160),
        reused=False,
    )
    _record_workflow_event(
        "source_collection.stage_session_task_knowledge_ingestion_materialized",
        team_id,
        fields={
            "runId": _trim_text(run_id, max_length=160),
            "taskId": _trim_text(task.get("taskId"), max_length=160),
            "stageId": stage_id,
            "agentId": _trim_text(task.get("agentId"), max_length=160),
            "stewardAgentId": steward_agent_id,
            "approvedCandidateCount": summary["approvedCandidateCount"],
            "formalKnowledgeItemCount": summary["formalKnowledgeItemCount"],
            "knowledgeBaseId": knowledge_base_id,
            "stewardPackCandidateId": steward_candidate_id,
            "writesOfficialGraph": summary["writesOfficialGraph"],
        },
    )
    return summary


def _source_collection_stage_writeback_approved_candidate_refs(
    result: dict[str, Any],
    writeback: dict[str, Any],
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []

    def add_candidate(value: Any, *, source: str) -> None:
        if isinstance(value, dict):
            candidate_id = _trim_text(
                value.get("candidateId") or value.get("candidate_id") or value.get("id"),
                max_length=160,
            )
            if candidate_id:
                refs.append({"candidateId": candidate_id, "source": source, "payload": _normalize_metadata(value)})
            return
        candidate_id = _trim_text(value, max_length=160)
        if candidate_id:
            refs.append({"candidateId": candidate_id, "source": source})

    def add_from_approved_container(container: Any, *, source: str) -> None:
        if isinstance(container, list):
            for item in container:
                add_candidate(item, source=source)
            return
        if not isinstance(container, dict):
            add_candidate(container, source=source)
            return
        for key in ("candidates", "candidateIds", "candidate_ids", "items", "sources", "sourceCandidates"):
            value = container.get(key)
            if isinstance(value, list):
                for item in value:
                    add_candidate(item, source=f"{source}.{key}")
        add_candidate(container, source=source)

    containers = [result]
    for key in ("candidate_summary", "candidateSummary", "steward_assessment", "stewardAssessment", "summary", "outputs"):
        value = result.get(key)
        if isinstance(value, dict):
            containers.append(value)
    for container in containers:
        for key in (
            "approved",
            "accepted",
            "passed",
            "approvedCandidates",
            "approved_candidates",
            "acceptedCandidates",
            "accepted_candidates",
        ):
            if key in container:
                add_from_approved_container(container.get(key), source=key)
        for key in ("approvedCandidateIds", "approved_candidate_ids", "acceptedCandidateIds", "candidateIds"):
            value = container.get(key)
            if isinstance(value, list):
                for item in value:
                    add_candidate(item, source=key)

    for decision in _source_collection_stage_writeback_candidate_decisions(result):
        if _source_collection_stage_writeback_quality_decision(decision) == "approved":
            add_candidate(decision, source="candidate_decision")

    steward_assessment = result.get("steward_assessment") if isinstance(result.get("steward_assessment"), dict) else {}
    if not steward_assessment and isinstance(result.get("stewardAssessment"), dict):
        steward_assessment = result["stewardAssessment"]
    if _source_collection_stage_writeback_quality_decision(steward_assessment) == "approved":
        for ref in list(writeback.get("evidenceRefs") or []):
            if not isinstance(ref, dict):
                continue
            ref_type = _trim_text(ref.get("type") or ref.get("kind"), max_length=80).lower()
            if ref_type in {"candidate", "source_candidate", "source_manifest"}:
                add_candidate(ref.get("id") or ref.get("candidateId"), source="evidence_ref")

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in refs:
        candidate_id = _trim_text(ref.get("candidateId"), max_length=160)
        if not candidate_id or candidate_id in seen:
            continue
        seen.add(candidate_id)
        deduped.append(ref)
    return deduped[:200]


def _source_collection_existing_official_knowledge_ingestion(
    candidates: list[dict[str, Any]],
    *,
    source_candidate_ids: set[str],
    selected_candidate_ids: set[str],
) -> dict[str, Any]:
    if not source_candidate_ids or not selected_candidate_ids:
        return {}
    for candidate in sorted(candidates, key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""), reverse=True):
        if not isinstance(candidate, dict):
            continue
        if str(candidate.get("currentState") or "") not in {"official_synced", "formal_knowledge_synced"}:
            continue
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        if str(metadata.get("taskType") or "") != "steward_pack_draft":
            continue
        if not _source_collection_steward_candidate_matches_run(candidate, source_candidate_ids):
            continue
        output = metadata.get("output") if isinstance(metadata.get("output"), dict) else {}
        candidate_ids = set(_normalize_id_values(output.get("candidateIds")))
        if selected_candidate_ids and not selected_candidate_ids.issubset(candidate_ids):
            continue
        return candidate
    return {}


def _source_collection_stage_writeback_existing_knowledge_ingestion_summary(
    candidate: dict[str, Any],
    *,
    selected_candidates: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
) -> dict[str, Any]:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    official_record = metadata.get("officialSyncRecord") if isinstance(metadata.get("officialSyncRecord"), dict) else {}
    ingestion = metadata.get("knowledgeIngestion") if isinstance(metadata.get("knowledgeIngestion"), dict) else {}
    knowledge_item_ids = _normalize_id_values(official_record.get("knowledgeItemIds") or ingestion.get("knowledgeItemIds"))
    return _source_collection_stage_writeback_knowledge_ingestion_summary(
        status="completed",
        approved=[{"candidateId": str(item.get("candidateId") or ""), "source": "existing_official_sync"} for item in selected_candidates],
        ingested=selected_candidates,
        skipped=skipped,
        steward_pack_candidate_id=_trim_text(candidate.get("candidateId"), max_length=160),
        knowledge_base_id=_trim_text(official_record.get("knowledgeBaseId") or ingestion.get("knowledgeBaseId"), max_length=160),
        knowledge_item_ids=knowledge_item_ids,
        writes_official_graph=bool(official_record.get("writesOfficialGraph") or ingestion.get("writesOfficialGraph")),
        proposal_id=_trim_text(official_record.get("proposalId") or ingestion.get("proposalId"), max_length=160),
        reused=True,
    )


def _source_collection_stage_writeback_resolve_knowledge_base(team_id: str, steward_agent_id: str) -> dict[str, Any]:
    status_payload = get_knowledge_ingestion_status(team_id)
    existing_bases = [item for item in list(status_payload.get("knowledgeBases") or []) if isinstance(item, dict)]
    if existing_bases:
        return existing_bases[0]
    team = team_service.get_team(team_id)
    actor_agent_id = _source_collection_stage_writeback_knowledge_base_creator_agent(team, steward_agent_id)
    if not actor_agent_id:
        raise TeamWorkflowOrchestrationError("No team member is available to create the Team Knowledge base.")
    return team_knowledge_service.create_knowledge_base(
        team_id,
        name="挑战杯科研知识库",
        description="由知识库管理员阶段回写自动创建，用于保存通过审核的挑战杯资料。",
        actor_agent_id=actor_agent_id,
    )


def _source_collection_stage_writeback_knowledge_base_creator_agent(team: dict[str, Any], steward_agent_id: str) -> str:
    members = [item for item in list((team or {}).get("members") or []) if isinstance(item, dict)]
    steward_id = _trim_text(steward_agent_id, max_length=160)
    for member in members:
        agent_id = _trim_text(member.get("agentId"), max_length=160)
        if agent_id and agent_id == steward_id:
            return agent_id
    for hint in ("steward", "coordination", "coordinator", "lead", "owner"):
        for member in members:
            agent_id = _trim_text(member.get("agentId"), max_length=160)
            role = _trim_text(member.get("role"), max_length=120).lower()
            if agent_id and hint in role:
                return agent_id
    for member in members:
        agent_id = _trim_text(member.get("agentId"), max_length=160)
        if agent_id:
            return agent_id
    return ""


def _source_collection_stage_writeback_target_domain(result: dict[str, Any]) -> str:
    for container in (
        result,
        result.get("steward_assessment") if isinstance(result.get("steward_assessment"), dict) else {},
        result.get("stewardAssessment") if isinstance(result.get("stewardAssessment"), dict) else {},
        result.get("candidate_summary") if isinstance(result.get("candidate_summary"), dict) else {},
        result.get("candidateSummary") if isinstance(result.get("candidateSummary"), dict) else {},
    ):
        if not isinstance(container, dict):
            continue
        value = _trim_text(container.get("targetDomain") or container.get("target_domain") or container.get("domain"), max_length=240)
        if value:
            return value
    return "神经机制启发神经网络算法"


def _source_collection_stage_writeback_knowledge_ingestion_summary(
    *,
    status: str,
    approved: list[dict[str, Any]] | None = None,
    ingested: list[dict[str, Any]] | None = None,
    skipped: list[dict[str, Any]] | None = None,
    failed: list[dict[str, Any]] | None = None,
    steward_pack_candidate_id: str = "",
    knowledge_base_id: str = "",
    knowledge_item_ids: list[str] | None = None,
    writes_official_graph: bool = False,
    source_review_status: str = "",
    proposal_id: str = "",
    reused: bool = False,
) -> dict[str, Any]:
    approved_items = [item for item in list(approved or []) if isinstance(item, dict)]
    ingested_items = [item for item in list(ingested or []) if isinstance(item, dict)]
    skipped_items = [item for item in list(skipped or []) if isinstance(item, dict)]
    failed_items = [item for item in list(failed or []) if isinstance(item, dict)]
    normalized_knowledge_item_ids = [item for item in _normalize_id_values(knowledge_item_ids) if item]
    return {
        "status": status,
        "approvedCandidateCount": len(ingested_items) or len(approved_items),
        "ingestedCandidateCount": len(ingested_items),
        "skippedCandidateCount": len(skipped_items),
        "failedCount": len(failed_items),
        "stewardPackCandidateId": _trim_text(steward_pack_candidate_id, max_length=160),
        "knowledgeBaseId": _trim_text(knowledge_base_id, max_length=160),
        "knowledgeItemIds": normalized_knowledge_item_ids[:80],
        "formalKnowledgeItemCount": len(normalized_knowledge_item_ids),
        "writesFormalKnowledge": status in {"completed", "applied_without_formal_item"} and bool(normalized_knowledge_item_ids),
        "writesRag": False,
        "writesOfficialGraph": bool(writes_official_graph),
        "sourceReviewStatus": _trim_text(source_review_status, max_length=80),
        "proposalId": _trim_text(proposal_id, max_length=160),
        "reusedOfficialSync": bool(reused),
        "approvedCandidates": [
            {"candidateId": _trim_text(item.get("candidateId"), max_length=160), "source": _trim_text(item.get("source"), max_length=120)}
            for item in approved_items[:80]
        ],
        "ingestedCandidates": [
            {
                "candidateId": _trim_text(item.get("candidateId"), max_length=160),
                "title": _trim_text(item.get("title"), max_length=240),
            }
            for item in ingested_items[:80]
        ],
        "skippedCandidates": skipped_items[:80],
        "failed": failed_items[:12],
    }


def _source_collection_stage_writeback_candidate_decisions(result: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for key in (
        "candidateDecisions",
        "candidate_decisions",
        "decisions",
        "candidateReviews",
        "candidate_reviews",
        "reviewedCandidates",
        "reviewed_candidates",
    ):
        value = result.get(key)
        if isinstance(value, list):
            candidates.extend(item for item in value if isinstance(item, dict))
    for container_key in ("reviewSummary", "sourceQuality", "qualityReview", "handoff", "outputs", "summary"):
        container = result.get(container_key)
        if not isinstance(container, dict):
            continue
        for key in ("candidateDecisions", "candidate_decisions", "decisions", "candidateReviews", "reviewedCandidates"):
            value = container.get(key)
            if isinstance(value, list):
                candidates.extend(item for item in value if isinstance(item, dict))
    return candidates[:200]


def _source_collection_stage_writeback_quality_decision(payload: dict[str, Any]) -> str:
    raw = _trim_text(
        payload.get("decision")
        or payload.get("status")
        or payload.get("result")
        or payload.get("bucket"),
        max_length=80,
    ).lower()
    normalized = raw.replace("-", "_").replace(" ", "_")
    if normalized in {"pass", "passed", "approve", "approved", "accept", "accepted", "source_quality_approved"}:
        return "approved"
    if normalized in {"reject", "rejected", "irrelevant", "discard", "discarded", "source_quality_rejected"}:
        return "rejected"
    if normalized in {
        "needs_more_info",
        "need_more_info",
        "needs_revision",
        "needs_review",
        "return",
        "returned",
        "revise",
        "revision",
        "uncertain",
        "conditional_pass",
        "source_quality_needs_revision",
    }:
        return "needs_revision"
    return ""


def _source_collection_stage_writeback_quality_notes(payload: dict[str, Any], writeback: dict[str, Any]) -> str:
    return (
        _trim_text(payload.get("reason"), max_length=4000)
        or _trim_text(payload.get("notes"), max_length=4000)
        or _trim_text(payload.get("rationale"), max_length=4000)
        or _trim_text(writeback.get("summary"), max_length=4000)
    )


def _source_collection_stage_writeback_quality_summary(
    *,
    status: str,
    assessed: list[dict[str, Any]] | None = None,
    skipped: list[dict[str, Any]] | None = None,
    failed: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    assessed_items = [item for item in list(assessed or []) if isinstance(item, dict)]
    skipped_items = [item for item in list(skipped or []) if isinstance(item, dict)]
    failed_items = [item for item in list(failed or []) if isinstance(item, dict)]
    return {
        "status": status,
        "assessedCandidateCount": len(assessed_items),
        "approvedCandidateCount": sum(1 for item in assessed_items if item.get("decision") == "approved"),
        "needsRevisionCandidateCount": sum(1 for item in assessed_items if item.get("decision") == "needs_revision"),
        "rejectedCandidateCount": sum(1 for item in assessed_items if item.get("decision") == "rejected"),
        "skippedCandidateCount": len(skipped_items),
        "failedCandidateCount": len(failed_items),
        "assessedCandidates": assessed_items[:80],
        "skippedCandidates": skipped_items[:80],
        "failedCandidates": failed_items[:80],
    }


def _source_collection_stage_writeback_candidate_graph_summary(
    *,
    status: str,
    candidate_graph: dict[str, Any] | None = None,
    failed: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    graph = candidate_graph if isinstance(candidate_graph, dict) else {}
    failed_items = [item for item in list(failed or []) if isinstance(item, dict)]
    candidate_graph_id = _trim_text(graph.get("candidateGraphId"), max_length=160)
    reused = bool(graph.get("reusedCandidateGraph"))
    return {
        "status": status,
        "candidateGraphId": candidate_graph_id,
        "createdCandidateGraphCount": 0 if reused or not candidate_graph_id else 1,
        "reusedCandidateGraph": reused,
        "nodeCount": _source_collection_count(graph.get("nodeCount")),
        "edgeCount": _source_collection_count(graph.get("edgeCount")),
        "missingLinkCount": _source_collection_count(graph.get("missingLinkCount")),
        "unreviewedNodeCount": _source_collection_count(graph.get("unreviewedNodeCount")),
        "inputCandidateCount": _source_collection_count(graph.get("inputCandidateCount")),
        "filteredCandidateCount": _source_collection_count(graph.get("filteredCandidateCount")),
        "ingestionFingerprint": _trim_text(graph.get("ingestionFingerprint"), max_length=160),
        "failedCandidateGraphCount": len(failed_items),
        "failedCandidateGraphs": failed_items[:24],
    }


def _attach_candidate_graph_stage_writeback_metadata(
    team_id: str,
    candidate_graph_id: str,
    *,
    task: dict[str, Any],
    writeback: dict[str, Any],
    graph_response: dict[str, Any],
    agent_graph: dict[str, Any],
) -> None:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    normalized_candidate_graph_id = _trim_text(candidate_graph_id, max_length=160)
    if not normalized_candidate_graph_id:
        return
    writeback_ref = {
        "taskId": _trim_text(task.get("taskId"), max_length=160),
        "runId": _trim_text(task.get("runId"), max_length=160),
        "stageId": _trim_text(task.get("stageId"), max_length=80),
        "agentId": _trim_text(task.get("agentId"), max_length=160),
        "agentRole": _trim_text(task.get("agentRole"), max_length=80),
        "status": _trim_text(writeback.get("status"), max_length=80),
        "summary": _trim_text(writeback.get("summary"), max_length=1000),
        "recordedAt": _trim_text(writeback.get("recordedAt"), max_length=120),
        "recordedByAgent": _trim_text(writeback.get("recordedByAgent"), max_length=160),
        "result": {"candidateGraph": _normalize_metadata(agent_graph)} if agent_graph else {},
    }
    with _WORKFLOW_LOCK:
        candidate_store = _load_candidate_store(normalized_team_id)
        changed = False
        for candidate in list(candidate_store.get("candidates") or []):
            if not isinstance(candidate, dict) or str(candidate.get("candidateId") or "") != normalized_candidate_graph_id:
                continue
            metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
            metadata = dict(metadata)
            existing_refs = metadata.get("stageTaskWritebacks") if isinstance(metadata.get("stageTaskWritebacks"), list) else []
            refs = [
                item for item in existing_refs
                if isinstance(item, dict) and _trim_text(item.get("taskId"), max_length=160) != writeback_ref["taskId"]
            ]
            refs.append(writeback_ref)
            metadata["agentWriteback"] = writeback_ref
            metadata["stageTaskWritebacks"] = refs[-24:]
            metadata["sourceCollectionStageTaskId"] = writeback_ref["taskId"]
            metadata["sourceCollectionRunId"] = writeback_ref["runId"]
            metadata["reusedCandidateGraph"] = bool(graph_response.get("reusedCandidateGraph"))
            candidate["metadata"] = metadata
            candidate["updatedAt"] = utc_now_iso()
            changed = True
            break
        if changed:
            candidate_store["updatedAt"] = utc_now_iso()
            _write_json(_candidate_store_path(normalized_team_id), candidate_store)


def _source_collection_stage_writeback_source_leads(result: dict[str, Any]) -> list[dict[str, Any]]:
    leads: list[dict[str, Any]] = []
    for key in (
        "candidateLeads",
        "sourceCandidates",
        "source_candidates",
        "sources",
        "records",
        "createdRecords",
        "created_records",
    ):
        value = result.get(key)
        if isinstance(value, list):
            leads.extend(item for item in value if isinstance(item, dict))
    for container_key in ("searchFrame", "handoff", "result", "outputs", "summary"):
        container = result.get(container_key)
        if not isinstance(container, dict):
            continue
        for key in ("candidateLeads", "sourceCandidates", "sources", "records"):
            value = container.get(key)
            if isinstance(value, list):
                leads.extend(item for item in value if isinstance(item, dict))
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for lead in leads:
        fingerprint = _source_collection_stage_writeback_lead_fingerprint(lead)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        deduped.append(lead)
    return deduped[:80]


def _source_collection_stage_writeback_lead_fingerprint(lead: dict[str, Any]) -> str:
    identity = _source_collection_identity_key(
        source_ref=lead.get("sourceRef") or lead.get("source_ref") or lead.get("locator") or lead.get("doi"),
        raw_location=lead.get("rawLocation") or lead.get("raw_location") or lead.get("url") or lead.get("sourceUrl"),
        doi=lead.get("doi") or lead.get("DOI"),
        url=lead.get("url") or lead.get("sourceUrl"),
        title=lead.get("title"),
        container=lead.get("container") or lead.get("venue") or lead.get("journal"),
        published=lead.get("published") or lead.get("year"),
    )
    if identity:
        return identity
    fallback = "|".join(
        [
            _trim_text(lead.get("leadId") or lead.get("id"), max_length=160),
            _trim_text(lead.get("title"), max_length=260).lower(),
            _trim_text(lead.get("year"), max_length=20),
        ]
    )
    return hashlib.sha256(fallback.encode("utf-8")).hexdigest()[:24]


def _source_collection_stage_writeback_record_payload(
    lead: dict[str, Any],
    *,
    team_id: str,
    run_id: str,
    task_id: str,
    stage_id: str,
    agent_id: str,
    agent_role: str,
    index: int,
) -> dict[str, Any]:
    doi = _source_collection_extract_doi(
        lead.get("doi"),
        lead.get("DOI"),
        lead.get("locator"),
        lead.get("sourceRef"),
        lead.get("sourceUrl"),
        lead.get("url"),
    )
    source_url = _trim_text(lead.get("sourceUrl") or lead.get("url"), max_length=2000)
    source_ref = _trim_text(lead.get("sourceRef") or lead.get("source_ref"), max_length=2000)
    locator = _trim_text(lead.get("locator"), max_length=2000)
    if doi and not source_ref:
        source_ref = f"https://doi.org/{doi}"
    elif _looks_like_url(source_url) and not source_ref:
        source_ref = source_url
    elif _looks_like_url(locator) and not source_ref:
        source_ref = locator
        source_url = source_url or locator
    elif doi:
        source_ref = source_ref or f"https://doi.org/{doi}"
    title = _trim_text(lead.get("title"), max_length=260)
    year = _trim_text(lead.get("year") or lead.get("published"), max_length=80)
    container = _trim_text(lead.get("container") or lead.get("venue") or lead.get("journal"), max_length=240)
    if not source_ref and not source_url:
        return {}
    summary = _trim_text(
        lead.get("summary")
        or lead.get("abstract")
        or lead.get("relevance")
        or lead.get("notes")
        or lead.get("description"),
        max_length=4000,
    )
    metadata = _normalize_metadata(lead.get("metadata"))
    metadata.update(
        {
            "sourceCollectionStageWriteback": True,
            "sourceCollectionStageTaskId": task_id,
            "sourceCollectionStageId": stage_id,
            "sourceCollectionStageAgentId": agent_id,
            "sourceCollectionStageAgentRole": agent_role,
            "sourceCollectionLeadIndex": index,
            "sourceCollectionLeadId": _trim_text(lead.get("leadId") or lead.get("id"), max_length=160),
            "teamId": team_id,
            "runId": run_id,
            "doi": doi,
            "year": year,
            "containerTitle": container,
            "authors": _source_collection_stage_writeback_authors(lead.get("authors")),
            "certainty": _trim_text(lead.get("certainty"), max_length=120),
            "priority": _trim_text(lead.get("priority"), max_length=80),
        }
    )
    trace = {
        "teamId": team_id,
        "runId": run_id,
        "taskId": task_id,
        "stageId": stage_id,
        "agentId": agent_id,
        "agentRole": agent_role,
        "query": _trim_text(lead.get("query"), max_length=1000),
        "leadId": _trim_text(lead.get("leadId") or lead.get("id"), max_length=160),
        "searchProvider": _trim_text(lead.get("searchProvider"), max_length=80) or "agent_stage_writeback",
        "storageTarget": "data_processing.records",
    }
    metadata["sourceCollectionTrace"] = trace
    source_identity_key = _source_collection_identity_key(
        source_ref=source_ref,
        raw_location=source_url or locator,
        doi=doi,
        url=source_url,
        title=title,
        container=container,
        published=year,
    )
    quality_signals = _normalize_metadata(lead.get("qualitySignals"))
    if source_identity_key:
        metadata["sourceIdentityKey"] = source_identity_key
        quality_signals["sourceIdentityKey"] = source_identity_key
    quality_signals.update(
        {
            "stageWritebackMaterialized": True,
            "certainty": metadata["certainty"],
            "priority": metadata["priority"],
        }
    )
    return {
        "sourceType": _source_collection_data_processing_source_type(lead.get("sourceType") or lead.get("source_type") or lead.get("sourceKind") or "paper"),
        "sourceRef": source_ref,
        "rawLocation": source_url or locator,
        "title": title or source_ref or source_url,
        "summary": summary,
        "status": "ready_for_review" if source_ref or source_url else "collected",
        "metadata": metadata,
        "qualitySignals": quality_signals,
        "collectionTrace": trace,
    }


def _source_collection_stage_writeback_authors(value: Any) -> Any:
    if isinstance(value, list):
        return [_trim_text(item, max_length=160) for item in value[:24] if _trim_text(item, max_length=160)]
    return _trim_text(value, max_length=1000)


def _source_collection_stage_writeback_materialization_summary(
    *,
    status: str,
    source_lead_count: int = 0,
    created_records: list[dict[str, Any]] | None = None,
    imported_candidates: list[dict[str, Any]] | None = None,
    skipped: list[dict[str, Any]] | None = None,
    failed: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    normalized_skipped = [item for item in list(skipped or []) if isinstance(item, dict)]
    skipped_duplicate_count = sum(1 for item in normalized_skipped if "duplicate" in _trim_text(item.get("reason"), max_length=120))
    return {
        "status": status,
        "sourceLeadCount": source_lead_count,
        "createdRecordCount": len(list(created_records or [])),
        "importedCandidateCount": len(list(imported_candidates or [])),
        "skippedCount": len(normalized_skipped),
        "skippedDuplicateCount": skipped_duplicate_count,
        "failedCount": len(list(failed or [])),
        "createdRecords": [
            {
                "recordId": _trim_text(item.get("recordId"), max_length=160),
                "title": _trim_text(item.get("title"), max_length=240),
                "sourceRef": _trim_text(item.get("sourceRef") or item.get("rawLocation"), max_length=240),
            }
            for item in list(created_records or [])[:24]
            if isinstance(item, dict)
        ],
        "importedCandidates": list(imported_candidates or [])[:24],
        "skipped": normalized_skipped[:24],
        "failed": [item for item in list(failed or []) if isinstance(item, dict)][:24],
    }


def _source_collection_candidate_count_for_run(candidate_store: dict[str, Any], run_id: str) -> int:
    count = 0
    for candidate in list(candidate_store.get("candidates") or []):
        if not isinstance(candidate, dict) or _candidate_is_archived(candidate):
            continue
        if str(candidate.get("candidateType") or "") != "source_manifest":
            continue
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        imported_from = metadata.get("importedFromDataRecord") if isinstance(metadata.get("importedFromDataRecord"), dict) else {}
        if str(imported_from.get("runId") or "") == run_id:
            count += 1
    return count


def get_research_stage_round_status(team_id: str) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    team = team_service.get_team(normalized_team_id)
    _reconcile_source_collection_stage_session_tasks(normalized_team_id)
    with _WORKFLOW_LOCK:
        workflow = _load_or_create_workflow(normalized_team_id)
        store = _load_stage_round_store(normalized_team_id)
    rounds = _stage_rounds(store)
    synced_from_work_run = False
    for stage_round in rounds:
        if str(stage_round.get("stageType") or "") != "knowledge_collection":
            continue
        if str(stage_round.get("status") or "") not in RESEARCH_STAGE_ACTIVE_STATUSES:
            continue
        for source_run_id in [str(item) for item in list(stage_round.get("sourceRunIds") or []) if str(item or "").strip()]:
            synced_from_work_run = _sync_source_collection_stage_round_from_latest_work_run(normalized_team_id, source_run_id) is not None or synced_from_work_run
    if synced_from_work_run:
        with _WORKFLOW_LOCK:
            workflow = _load_or_create_workflow(normalized_team_id)
            store = _load_stage_round_store(normalized_team_id)
        rounds = _stage_rounds(store)
    _attach_source_collection_stage_card_projections(normalized_team_id, rounds)
    phases = [
        _stage_phase_status(
            normalized_team_id,
            stage_type,
            rounds,
            workflow=workflow,
            team=team,
        )
        for stage_type in RESEARCH_STAGE_TYPES
    ]
    active_rounds = [item for item in rounds if str(item.get("status") or "") in RESEARCH_STAGE_ACTIVE_STATUSES]
    latest_round = _latest_stage_round(rounds)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "status": "active" if active_rounds else "idle",
        "currentStage": _current_research_stage(phases, workflow),
        "phases": phases,
        "activeRounds": active_rounds,
        "latestRound": latest_round,
        "roundCount": len(rounds),
        "storagePath": _relative_path(_stage_round_store_path(normalized_team_id)),
        "boundaries": _research_stage_boundaries(),
        "updatedAt": str(store.get("updatedAt") or ""),
    }


def _attach_source_collection_stage_card_projections(team_id: str, rounds: list[dict[str, Any]]) -> None:
    for stage_round in rounds:
        if not isinstance(stage_round, dict) or str(stage_round.get("stageType") or "") != "knowledge_collection":
            continue
        source_run_ids = [str(item) for item in list(stage_round.get("sourceRunIds") or []) if str(item or "").strip()]
        if not source_run_ids:
            continue
        projection = _source_collection_stage_cards_projection(team_id, source_run_ids[-1])
        stage_round["sourceCollectionStageCards"] = projection.get("cards", [])
        stage_round["sourceCollectionStageCardSummary"] = projection.get("summary", {})


def start_research_stage_round(team_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    team = team_service.get_team(normalized_team_id)
    request_payload = dict(payload) if isinstance(payload, dict) else {}
    stage_type = _normalize_stage_type(request_payload.get("stageType"))
    start_mode = _normalize_stage_start_mode(request_payload.get("mode") or request_payload.get("startMode"))
    requested_by_agent = _trim_text(request_payload.get("requestedByAgent"), max_length=160) or _source_collection_owner_agent_id(team, request_payload)
    with _WORKFLOW_LOCK:
        workflow = _load_or_create_workflow(normalized_team_id)
        store = _load_stage_round_store(normalized_team_id)
        rounds = _stage_rounds(store)
        active_round = _active_stage_round(rounds, stage_type)
        if active_round and start_mode != "new_round":
            continued_payload = _continued_stage_round_payload(active_round, stage_type)
            continued_ref = continued_payload.get("continuedSourceRunRef") if isinstance(continued_payload.get("continuedSourceRunRef"), dict) else {}
            _record_workflow_event(
                "research_stage_round.continued",
                normalized_team_id,
                fields={
                    "workflowId": workflow["workflowId"],
                    "stageRoundId": active_round.get("stageRoundId", ""),
                    "stageType": stage_type,
                    "status": active_round.get("status", ""),
                    "sourceRunCount": len(list(active_round.get("sourceRunIds") or [])),
                    "continuedSourceRunId": continued_ref.get("runId", ""),
                    "continuedRecordCount": continued_ref.get("recordCount", 0),
                    "continuedOpenAssignmentCount": continued_ref.get("openAssignmentCount", 0),
                },
            )
            status_payload = _stage_phase_status(normalized_team_id, stage_type, rounds, workflow=workflow, team=team)
            return {
                "created": False,
                "continued": True,
                "stageRound": active_round,
                "phase": status_payload,
                "workflow": _workflow_to_api(normalized_team_id, workflow, _load_candidate_store(normalized_team_id)),
                "status": get_research_stage_round_status(normalized_team_id),
                "nextActions": _stage_next_actions(stage_type, reused=True),
                "boundaries": _research_stage_boundaries(),
                **continued_payload,
            }
        previous_round = _latest_stage_round([item for item in rounds if str(item.get("stageType") or "") == stage_type])
        round_payload = _build_stage_round(
            normalized_team_id,
            stage_type,
            request_payload,
            rounds,
            previous_round=previous_round,
            requested_by_agent=requested_by_agent,
            team=team,
        )
        result_payload: dict[str, Any] = {}
        status = "running"
        warnings: list[dict[str, str]] = []
        if stage_type == "knowledge_collection":
            source_payload = _stage_source_collection_payload(round_payload, request_payload, team)
            source_result = start_source_collection_run(normalized_team_id, source_payload)
            search_execution = start_source_collection_search_background(
                normalized_team_id,
                source_result["run"]["runId"],
                {
                    "backgroundExecution": True,
                    "provider": SOURCE_COLLECTION_SEARCH_PROVIDER_CROSSREF,
                    "maxQueries": _normalize_int(
                        request_payload.get("maxQueries"),
                        default=SOURCE_COLLECTION_SEARCH_EXECUTION_DEFAULT_MAX_QUERIES,
                        minimum=1,
                        maximum=SOURCE_COLLECTION_SEARCH_EXECUTION_MAX_QUERIES,
                    ),
                    "maxResultsPerQuery": _normalize_int(
                        request_payload.get("maxResultsPerQuery"),
                        default=SOURCE_COLLECTION_SEARCH_EXECUTION_DEFAULT_RESULTS_PER_QUERY,
                        minimum=1,
                        maximum=SOURCE_COLLECTION_SEARCH_EXECUTION_MAX_RESULTS_PER_QUERY,
                    ),
                },
            )
            result_payload["sourceCollectionRun"] = source_result
            result_payload["sourceCollectionSearchExecution"] = search_execution
            result_payload["run"] = source_result["run"]
            result_payload["searchPlan"] = source_result["searchPlan"]
            result_payload["promptCachePolicy"] = source_result.get("promptCachePolicy", {})
            result_payload["assignments"] = source_result["assignments"]
            round_payload["sourceRunIds"] = [source_result["run"]["runId"]]
            round_payload["dataSearchPlanRef"] = _source_collection_search_plan_ref(source_result["searchPlan"])
            round_payload["promptCachePolicy"] = source_result.get("promptCachePolicy", {})
            round_payload["sourceCollectionSearchExecution"] = {
                "runId": search_execution["runId"],
                "status": search_execution["status"],
                "executionMode": search_execution["executionMode"],
                "accepted": bool(search_execution.get("accepted")),
                "provider": search_execution["provider"],
                "activeWorkRunId": str((search_execution.get("activeWorkRun") or {}).get("runId") or ""),
            }
            round_payload["assignmentIds"] = [str(item.get("assignmentId") or "") for item in source_result["assignments"] if item.get("assignmentId")]
            round_payload["agentRoleAssignments"] = [
                {
                    "agentRole": str(item.get("agentRole") or ""),
                    "agentId": str(item.get("agentId") or ""),
                    "assignmentId": str(item.get("assignmentId") or ""),
                }
                for item in source_result["assignments"]
            ]
            warnings.extend(_stage_agent_binding_warnings(source_result["assignments"]))
            round_payload["workflowItemRef"] = {"candidateId": source_result["run"]["runId"], "currentNode": "knowledge_collection"}
            workflow = _load_or_create_workflow(normalized_team_id)
        else:
            status = "planning"
            round_payload["planningContract"] = _stage_planning_contract(stage_type, round_payload)
            workflow["activeWorkflowItems"] = _upsert_active_item(
                workflow.get("activeWorkflowItems"),
                candidate_id=round_payload["stageRoundId"],
                current_node=RESEARCH_STAGE_DEFAULTS[stage_type]["currentNode"],
                status=f"{stage_type}_planning_started",
                transfer_id="",
            )
            workflow["updatedAt"] = utc_now_iso()
            _write_json(_workflow_path(normalized_team_id), workflow)
        round_payload["warnings"] = warnings
        round_payload["teamMemoryRecord"] = _stage_memory_record(round_payload, workflow)
        round_payload["teamMemoryRecordId"] = round_payload["teamMemoryRecord"]["recordId"]
        coordination_contract = _stage_coordination_contract(team, round_payload, trigger="manual")
        coordination_result = _stage_coordination_manual_pending_result(coordination_contract)
        coordination_contract["startResult"] = coordination_result
        round_payload["coordinationContract"] = coordination_contract
        round_payload["status"] = status
        now = utc_now_iso()
        round_payload["updatedAt"] = now
        store["rounds"] = rounds + [round_payload]
        store["updatedAt"] = now
        _write_json(_stage_round_store_path(normalized_team_id), store)
        candidate_store = _load_candidate_store(normalized_team_id)
    _record_workflow_event(
        "research_stage_round.started",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "stageRoundId": round_payload["stageRoundId"],
            "stageType": stage_type,
            "status": round_payload["status"],
            "sourceRunCount": len(list(round_payload.get("sourceRunIds") or [])),
            "querySeedCount": len(list(round_payload.get("querySeeds") or [])),
            "warningCount": len(warnings),
            "coordinationStarted": bool(coordination_result.get("started")),
            "coordinationRoomId": str(coordination_result.get("roomId") or ""),
            "coordinationRoundId": str(coordination_result.get("roundId") or ""),
            "coordinationErrorType": str(coordination_result.get("errorType") or ""),
            "sourceSearchAccepted": bool((result_payload.get("sourceCollectionSearchExecution") or {}).get("accepted")),
            "requestedByAgent": requested_by_agent,
        },
    )
    if stage_type == "knowledge_collection":
        source_run = result_payload.get("run") if isinstance(result_payload.get("run"), dict) else {}
        synced_round = _sync_source_collection_stage_round_from_latest_work_run(normalized_team_id, str(source_run.get("runId") or ""))
        if synced_round is not None:
            round_payload = synced_round
    stage_status_payload = get_research_stage_round_status(normalized_team_id)
    phase_payload = next(
        (item for item in list(stage_status_payload.get("phases") or []) if isinstance(item, dict) and item.get("stageType") == stage_type),
        _stage_phase_status(normalized_team_id, stage_type, [round_payload], workflow=workflow, team=team),
    )
    return {
        "created": True,
        "stageRound": round_payload,
        "phase": phase_payload,
        "workflow": _workflow_to_api(normalized_team_id, workflow, candidate_store),
        "status": stage_status_payload,
        "nextActions": _stage_next_actions(stage_type, reused=False),
        "boundaries": _research_stage_boundaries(),
        **result_payload,
    }


def get_experiment_planning_status(team_id: str) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    team_service.get_team(normalized_team_id)
    with _WORKFLOW_LOCK:
        store = _load_stage_round_store(normalized_team_id)
        rounds = _stage_rounds(store)
        candidate_store = _load_candidate_store(normalized_team_id)
        plan_store = _load_experiment_plan_store(normalized_team_id)
    return _experiment_planning_status(normalized_team_id, rounds, candidate_store, plan_store)


def create_experiment_plan(team_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    team = team_service.get_team(normalized_team_id)
    request_payload = payload if isinstance(payload, dict) else {}
    created_by_agent = _trim_text(request_payload.get("createdByAgent"), max_length=160) or DEFAULT_OWNER_AGENT_ID
    with _WORKFLOW_LOCK:
        workflow = _load_or_create_workflow(normalized_team_id)
        store = _load_stage_round_store(normalized_team_id)
        rounds = _stage_rounds(store)
        stage_round = _select_experiment_stage_round(request_payload, rounds)
        candidate_store = _load_candidate_store(normalized_team_id)
        selected_hypotheses = _select_experiment_hypothesis_candidates(candidate_store, request_payload)
        plan_store = _load_experiment_plan_store(normalized_team_id)
        plan = _build_experiment_plan_record(
            normalized_team_id,
            workflow,
            stage_round,
            selected_hypotheses,
            request_payload,
            created_by_agent=created_by_agent,
        )
        now = plan["updatedAt"]
        plan_store.setdefault("plans", []).append(plan)
        plan_store["activePlanId"] = plan["planId"]
        plan_store["updatedAt"] = now
        _write_json(_experiment_plan_store_path(normalized_team_id), plan_store)
        stage_round["experimentPlanRef"] = {
            "planId": plan["planId"],
            "status": plan["status"],
            "storagePath": _relative_path(_experiment_plan_store_path(normalized_team_id)),
            "updatedAt": now,
        }
        planning_contract = stage_round.get("planningContract") if isinstance(stage_round.get("planningContract"), dict) else {}
        planning_contract["currentPlanId"] = plan["planId"]
        planning_contract["planStoragePath"] = _relative_path(_experiment_plan_store_path(normalized_team_id))
        planning_contract["autoExecution"] = False
        planning_contract["requiresUserDecision"] = True
        stage_round["planningContract"] = planning_contract
        stage_round["status"] = "planning"
        stage_round["updatedAt"] = now
        store["rounds"] = rounds
        store["updatedAt"] = now
        _write_json(_stage_round_store_path(normalized_team_id), store)
        workflow["updatedAt"] = now
        workflow["activeWorkflowItems"] = _upsert_active_item(
            workflow.get("activeWorkflowItems"),
            candidate_id=stage_round["stageRoundId"],
            current_node=RESEARCH_STAGE_DEFAULTS["experiment"]["currentNode"],
            status="experiment_plan_drafted",
            transfer_id="",
        )
        _write_json(_workflow_path(normalized_team_id), workflow)
        status_payload = _experiment_planning_status(normalized_team_id, rounds, candidate_store, plan_store)
        stage_round_status = get_research_stage_round_status(normalized_team_id)
    _record_workflow_event(
        "experiment_plan.drafted",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "stageRoundId": stage_round["stageRoundId"],
            "planId": plan["planId"],
            "selectedHypothesisCount": len(plan.get("selectedHypotheses") or []),
            "readyForPlanReview": bool((plan.get("readiness") or {}).get("readyForPlanReview")),
            "readyForFullRun": False,
            "createdByAgent": created_by_agent,
        },
    )
    return {
        "plan": plan,
        "status": status_payload,
        "stageRound": stage_round,
        "stageRoundStatus": stage_round_status,
        "workflow": _workflow_to_api(normalized_team_id, workflow, candidate_store),
        "team": {"teamId": team.get("teamId", normalized_team_id), "name": team.get("name", "")},
        "boundaries": _experiment_planning_boundaries(),
    }


def register_experiment_baseline_artifact(team_id: str, plan_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    normalized_plan_id = _normalize_required_id(plan_id, "Experiment plan id is required.")
    team = team_service.get_team(normalized_team_id)
    request_payload = payload if isinstance(payload, dict) else {}
    registered_by_agent = _trim_text(request_payload.get("registeredByAgent"), max_length=160) or DEFAULT_OWNER_AGENT_ID
    with _WORKFLOW_LOCK:
        workflow = _load_or_create_workflow(normalized_team_id)
        stage_store = _load_stage_round_store(normalized_team_id)
        rounds = _stage_rounds(stage_store)
        candidate_store = _load_candidate_store(normalized_team_id)
        plan_store = _load_experiment_plan_store(normalized_team_id)
        plan = _find_experiment_plan(plan_store, normalized_plan_id)
        if plan is None:
            raise TeamWorkflowOrchestrationError("Experiment plan not found.")
        artifact = _experiment_baseline_artifact_record(plan, request_payload, registered_by_agent=registered_by_agent)
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
        _refresh_experiment_plan_readiness(plan)
        plan_store["activePlanId"] = plan["planId"]
        plan_store["updatedAt"] = artifact["registeredAt"]
        _write_json(_experiment_plan_store_path(normalized_team_id), plan_store)
        stage_round = _find_stage_round(rounds, str(plan.get("stageRoundId") or ""))
        if stage_round is not None:
            stage_round["experimentPlanRef"] = {
                "planId": plan["planId"],
                "status": plan["status"],
                "storagePath": _relative_path(_experiment_plan_store_path(normalized_team_id)),
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
            _write_json(_stage_round_store_path(normalized_team_id), stage_store)
        workflow["updatedAt"] = artifact["registeredAt"]
        workflow["activeWorkflowItems"] = _upsert_active_item(
            workflow.get("activeWorkflowItems"),
            candidate_id=str(plan.get("stageRoundId") or plan["planId"]),
            current_node=RESEARCH_STAGE_DEFAULTS["experiment"]["currentNode"],
            status="baseline_artifact_registered",
            transfer_id="",
        )
        _write_json(_workflow_path(normalized_team_id), workflow)
        status_payload = _experiment_planning_status(normalized_team_id, rounds, candidate_store, plan_store)
        stage_round_status = get_research_stage_round_status(normalized_team_id)
    _record_workflow_event(
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
        "workflow": _workflow_to_api(normalized_team_id, workflow, candidate_store),
        "team": {"teamId": team.get("teamId", normalized_team_id), "name": team.get("name", "")},
        "boundaries": _experiment_planning_boundaries(),
    }


_SMOKE_DECISION_TO_STATUS = {
    "accept": "passed",
    "iterate": "passed",
    "reject": "failed",
    "needs_full_run": "needs_review",
}


def run_experiment_smoke_run(team_id: str, plan_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """N-11：对 experiment plan 执行 V1 CPU 确定性 smoke runner，并记录结果。

    门禁：plan 缺 dataset/metric/baseline/smokePlan 之一 → 禁止运行。runner 仅跑白名单 adapter、
    固定 seed、无网络、不执行任意代码（见 core.research.smoke_runner）。decisionHint 映射到
    smoke 状态后复用 register_experiment_smoke_result 落账。
    """
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    normalized_plan_id = _normalize_required_id(plan_id, "Experiment plan id is required.")
    team_service.get_team(normalized_team_id)
    payload = payload if isinstance(payload, dict) else {}
    with _WORKFLOW_LOCK:
        plan_store = _load_experiment_plan_store(normalized_team_id)
        plan = _find_experiment_plan(plan_store, normalized_plan_id)
        if plan is None:
            raise TeamWorkflowOrchestrationError("Experiment plan not found.")
        plan_snapshot = dict(plan)
    missing = [field for field in EXPERIMENT_PLAN_REQUIRED_FIELDS if not _has_value(plan_snapshot.get(field))]
    if missing:
        raise TeamWorkflowOrchestrationError(f"Experiment plan missing required fields for smoke run: {missing}.")
    smoke_plan = plan_snapshot.get("smokePlan") if isinstance(plan_snapshot.get("smokePlan"), dict) else {}
    adapter = (
        _trim_text(payload.get("adapter") or smoke_plan.get("adapter"), max_length=120)
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
        runner_result = smoke_runner.run_smoke_adapter(adapter, seed=seed, threshold=threshold)
    except smoke_runner.SmokeRunnerError as exc:
        raise TeamWorkflowOrchestrationError(str(exc)) from exc
    decision = str(runner_result.get("decisionHint") or "needs_full_run")
    status = "needs_review" if runner_result.get("status") == "non_executable" else _SMOKE_DECISION_TO_STATUS.get(decision, "needs_review")
    now = utc_now_iso()
    smoke_run_id = _new_record_id("smokerun")
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
        "recordedByAgent": _trim_text(payload.get("recordedByAgent"), max_length=160) or "Smoke Runner Service",
        "recordedAt": now,
    }
    # 自包含执行器直接落账（runner 同时算 baseline+variant，无需手动 baseline artifact 前置）。
    with _WORKFLOW_LOCK:
        plan_store = _load_experiment_plan_store(normalized_team_id)
        plan = _find_experiment_plan(plan_store, normalized_plan_id)
        if plan is None:
            raise TeamWorkflowOrchestrationError("Experiment plan not found.")
        runs = [item for item in list(plan.get("smokeRunResults") or []) if isinstance(item, dict)]
        runs.append(smoke_record)
        plan["smokeRunResults"] = runs[-12:]
        plan["activeSmokeRunId"] = smoke_run_id
        plan["activeSmokeRun"] = smoke_record
        plan["status"] = "smoke_passed" if status == "passed" else f"smoke_{status}"
        plan["updatedAt"] = now
        plan_status = plan["status"]
        plan_store["activePlanId"] = plan["planId"]
        plan_store["updatedAt"] = now
        _write_json(_experiment_plan_store_path(normalized_team_id), plan_store)
        workflow = _load_or_create_workflow(normalized_team_id)
    _record_workflow_event(
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
        "schemaVersion": SCHEMA_VERSION,
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
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    normalized_plan_id = _normalize_required_id(plan_id, "Experiment plan id is required.")
    team = team_service.get_team(normalized_team_id)
    request_payload = payload if isinstance(payload, dict) else {}
    recorded_by_agent = _trim_text(request_payload.get("recordedByAgent"), max_length=160) or DEFAULT_OWNER_AGENT_ID
    with _WORKFLOW_LOCK:
        workflow = _load_or_create_workflow(normalized_team_id)
        stage_store = _load_stage_round_store(normalized_team_id)
        rounds = _stage_rounds(stage_store)
        candidate_store = _load_candidate_store(normalized_team_id)
        plan_store = _load_experiment_plan_store(normalized_team_id)
        plan = _find_experiment_plan(plan_store, normalized_plan_id)
        if plan is None:
            raise TeamWorkflowOrchestrationError("Experiment plan not found.")
        smoke_result = _experiment_smoke_result_record(plan, request_payload, recorded_by_agent=recorded_by_agent)
        smoke_results = [item for item in list(plan.get("smokeResults") or []) if isinstance(item, dict)]
        smoke_results.append(smoke_result)
        plan["smokeResults"] = smoke_results[-12:]
        plan["activeSmokeResultId"] = smoke_result["smokeResultId"]
        plan["activeSmokeResult"] = smoke_result
        plan["status"] = "smoke_passed" if smoke_result["status"] == "passed" else f"smoke_{smoke_result['status']}"
        plan["updatedAt"] = smoke_result["recordedAt"]
        _refresh_experiment_plan_readiness(plan)
        plan_store["activePlanId"] = plan["planId"]
        plan_store["updatedAt"] = smoke_result["recordedAt"]
        _write_json(_experiment_plan_store_path(normalized_team_id), plan_store)
        stage_round = _find_stage_round(rounds, str(plan.get("stageRoundId") or ""))
        if stage_round is not None:
            stage_round["experimentPlanRef"] = {
                "planId": plan["planId"],
                "status": plan["status"],
                "storagePath": _relative_path(_experiment_plan_store_path(normalized_team_id)),
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
            _write_json(_stage_round_store_path(normalized_team_id), stage_store)
        workflow["updatedAt"] = smoke_result["recordedAt"]
        workflow["activeWorkflowItems"] = _upsert_active_item(
            workflow.get("activeWorkflowItems"),
            candidate_id=str(plan.get("stageRoundId") or plan["planId"]),
            current_node=RESEARCH_STAGE_DEFAULTS["experiment"]["currentNode"],
            status="smoke_result_registered",
            transfer_id="",
        )
        _write_json(_workflow_path(normalized_team_id), workflow)
        status_payload = _experiment_planning_status(normalized_team_id, rounds, candidate_store, plan_store)
        stage_round_status = get_research_stage_round_status(normalized_team_id)
    _record_workflow_event(
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
        "workflow": _workflow_to_api(normalized_team_id, workflow, candidate_store),
        "team": {"teamId": team.get("teamId", normalized_team_id), "name": team.get("name", "")},
        "boundaries": _experiment_planning_boundaries(),
    }


def register_experiment_full_run_result(team_id: str, plan_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    normalized_plan_id = _normalize_required_id(plan_id, "Experiment plan id is required.")
    team = team_service.get_team(normalized_team_id)
    request_payload = payload if isinstance(payload, dict) else {}
    recorded_by_agent = _trim_text(request_payload.get("recordedByAgent"), max_length=160) or DEFAULT_OWNER_AGENT_ID
    with _WORKFLOW_LOCK:
        workflow = _load_or_create_workflow(normalized_team_id)
        stage_store = _load_stage_round_store(normalized_team_id)
        rounds = _stage_rounds(stage_store)
        candidate_store = _load_candidate_store(normalized_team_id)
        plan_store = _load_experiment_plan_store(normalized_team_id)
        plan = _find_experiment_plan(plan_store, normalized_plan_id)
        if plan is None:
            raise TeamWorkflowOrchestrationError("Experiment plan not found.")
        full_run_result = _experiment_full_run_result_record(plan, request_payload, recorded_by_agent=recorded_by_agent)
        full_run_results = [item for item in list(plan.get("fullRunResults") or []) if isinstance(item, dict)]
        full_run_results.append(full_run_result)
        plan["fullRunResults"] = full_run_results[-12:]
        plan["activeFullRunResultId"] = full_run_result["fullRunResultId"]
        plan["activeFullRunResult"] = full_run_result
        plan["status"] = "full_run_passed" if full_run_result["status"] == "passed" else f"full_run_{full_run_result['status']}"
        plan["updatedAt"] = full_run_result["recordedAt"]
        _refresh_experiment_plan_readiness(plan)
        plan_store["activePlanId"] = plan["planId"]
        plan_store["updatedAt"] = full_run_result["recordedAt"]
        _write_json(_experiment_plan_store_path(normalized_team_id), plan_store)
        stage_round = _find_stage_round(rounds, str(plan.get("stageRoundId") or ""))
        if stage_round is not None:
            stage_round["experimentPlanRef"] = {
                "planId": plan["planId"],
                "status": plan["status"],
                "storagePath": _relative_path(_experiment_plan_store_path(normalized_team_id)),
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
            _write_json(_stage_round_store_path(normalized_team_id), stage_store)
        workflow["updatedAt"] = full_run_result["recordedAt"]
        workflow["activeWorkflowItems"] = _upsert_active_item(
            workflow.get("activeWorkflowItems"),
            candidate_id=str(plan.get("stageRoundId") or plan["planId"]),
            current_node=RESEARCH_STAGE_DEFAULTS["experiment"]["currentNode"],
            status="full_run_result_registered",
            transfer_id="",
        )
        _write_json(_workflow_path(normalized_team_id), workflow)
        status_payload = _experiment_planning_status(normalized_team_id, rounds, candidate_store, plan_store)
        stage_round_status = get_research_stage_round_status(normalized_team_id)
    _record_workflow_event(
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
        "workflow": _workflow_to_api(normalized_team_id, workflow, candidate_store),
        "team": {"teamId": team.get("teamId", normalized_team_id), "name": team.get("name", "")},
        "boundaries": _experiment_planning_boundaries(),
    }


def request_experiment_result_knowledge_ingestion(team_id: str, plan_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    normalized_plan_id = _normalize_required_id(plan_id, "Experiment plan id is required.")
    team = team_service.get_team(normalized_team_id)
    request_payload = payload if isinstance(payload, dict) else {}
    requested_by_agent = _trim_text(request_payload.get("requestedByAgent"), max_length=160) or DEFAULT_OWNER_AGENT_ID
    steward_agent_id = _trim_text(request_payload.get("stewardAgentId"), max_length=160) or agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID
    knowledge_base_id = _trim_text(request_payload.get("knowledgeBaseId"), max_length=160) or f"{normalized_team_id}-challenge-cup-experiments"
    target_domain = _trim_text(request_payload.get("targetDomain"), max_length=240) or "挑战杯实验结果"
    wake_steward_agent = bool(request_payload.get("wakeStewardAgent", True))
    with _WORKFLOW_LOCK:
        workflow = _load_or_create_workflow(normalized_team_id)
        stage_store = _load_stage_round_store(normalized_team_id)
        rounds = _stage_rounds(stage_store)
        candidate_store = _load_candidate_store(normalized_team_id)
        plan_store = _load_experiment_plan_store(normalized_team_id)
        plan = _find_experiment_plan(plan_store, normalized_plan_id)
        if plan is None:
            raise TeamWorkflowOrchestrationError("Experiment plan not found.")
        experiment_result_pack = _experiment_result_ingestion_pack_record(
            plan,
            request_payload,
            knowledge_base_id=knowledge_base_id,
            target_domain=target_domain,
            requested_by_agent=requested_by_agent,
        )
        activation = _notify_knowledge_steward_for_experiment_result(
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
        _refresh_experiment_plan_readiness(plan)
        plan_store["activePlanId"] = plan["planId"]
        plan_store["updatedAt"] = experiment_result_pack["createdAt"]
        _write_json(_experiment_plan_store_path(normalized_team_id), plan_store)
        stage_round = _find_stage_round(rounds, str(plan.get("stageRoundId") or ""))
        if stage_round is not None:
            stage_round["experimentPlanRef"] = {
                "planId": plan["planId"],
                "status": plan["status"],
                "storagePath": _relative_path(_experiment_plan_store_path(normalized_team_id)),
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
            _write_json(_stage_round_store_path(normalized_team_id), stage_store)
        workflow["updatedAt"] = experiment_result_pack["createdAt"]
        workflow["activeWorkflowItems"] = _upsert_active_item(
            workflow.get("activeWorkflowItems"),
            candidate_id=str(plan.get("stageRoundId") or plan["planId"]),
            current_node=RESEARCH_STAGE_DEFAULTS["experiment"]["currentNode"],
            status=plan_status,
            transfer_id="",
        )
        _write_json(_workflow_path(normalized_team_id), workflow)
        status_payload = _experiment_planning_status(normalized_team_id, rounds, candidate_store, plan_store)
        stage_round_status = get_research_stage_round_status(normalized_team_id)
    _record_workflow_event(
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
    return {
        "experimentResultPack": experiment_result_pack,
        "knowledgeStewardActivation": activation,
        "plan": plan,
        "status": status_payload,
        "stageRoundStatus": stage_round_status,
        "workflow": _workflow_to_api(normalized_team_id, workflow, candidate_store),
        "team": {"teamId": team.get("teamId", normalized_team_id), "name": team.get("name", "")},
        "boundaries": _experiment_planning_boundaries(),
    }


def retry_research_stage_round_coordination(team_id: str, stage_round_id: str) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    normalized_round_id = _normalize_required_id(stage_round_id, "Stage round id is required.")
    team = team_service.get_team(normalized_team_id)
    with _WORKFLOW_LOCK:
        store = _load_stage_round_store(normalized_team_id)
        rounds = _stage_rounds(store)
        stage_round = _find_stage_round(rounds, normalized_round_id)
        if stage_round is None:
            raise TeamWorkflowOrchestrationError("Stage round not found.")
        coordination_contract = _stage_coordination_contract(team, stage_round, trigger="explicit_retry")
        coordination_result = _try_start_stage_coordination_round(team, coordination_contract)
        coordination_contract["startResult"] = coordination_result
        stage_round["coordinationContract"] = coordination_contract
        if coordination_result.get("started"):
            stage_round["coordinationRoundId"] = str(coordination_result.get("roundId") or "")
            stage_round["coordinationRoomId"] = str(coordination_result.get("roomId") or "")
            stage_round["status"] = "running" if str(stage_round.get("stageType") or "") == "knowledge_collection" else "planning"
            stage_round["warnings"] = [
                item
                for item in list(stage_round.get("warnings") or [])
                if isinstance(item, dict) and str(item.get("code") or "") != "coordination_round_not_started"
            ]
        else:
            stage_round["status"] = "needs_attention"
            warnings = [
                item
                for item in list(stage_round.get("warnings") or [])
                if isinstance(item, dict) and str(item.get("code") or "") != "coordination_round_not_started"
            ]
            warnings.append(
                {
                    "code": "coordination_round_not_started",
                    "severity": "warning",
                    "message": _trim_text(coordination_result.get("reason"), max_length=240) or "Coordination round was not started.",
                }
            )
            stage_round["warnings"] = warnings
        stage_round["updatedAt"] = utc_now_iso()
        store["rounds"] = rounds
        store["updatedAt"] = stage_round["updatedAt"]
        _write_json(_stage_round_store_path(normalized_team_id), store)
    _record_workflow_event(
        "research_stage_round.coordination_retry_recorded",
        normalized_team_id,
        fields={
            "stageRoundId": normalized_round_id,
            "stageType": stage_round.get("stageType", ""),
            "status": stage_round.get("status", ""),
            "coordinationStarted": bool(coordination_result.get("started")),
            "coordinationRoomId": str(coordination_result.get("roomId") or ""),
            "coordinationRoundId": str(coordination_result.get("roundId") or ""),
            "coordinationErrorType": str(coordination_result.get("errorType") or ""),
        },
    )
    return {
        "stageRound": stage_round,
        "coordinationContract": stage_round["coordinationContract"],
        "status": get_research_stage_round_status(normalized_team_id),
    }


def retry_research_stage_round_memory_record(team_id: str, stage_round_id: str) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    normalized_round_id = _normalize_required_id(stage_round_id, "Stage round id is required.")
    team_service.get_team(normalized_team_id)
    with _WORKFLOW_LOCK:
        workflow = _load_or_create_workflow(normalized_team_id)
        store = _load_stage_round_store(normalized_team_id)
        rounds = _stage_rounds(store)
        stage_round = _find_stage_round(rounds, normalized_round_id)
        if stage_round is None:
            raise TeamWorkflowOrchestrationError("Stage round not found.")
        stage_round["teamMemoryRecord"] = _stage_memory_record(stage_round, workflow)
        stage_round["teamMemoryRecordId"] = stage_round["teamMemoryRecord"]["recordId"]
        stage_round["updatedAt"] = utc_now_iso()
        store["rounds"] = rounds
        store["updatedAt"] = stage_round["updatedAt"]
        _write_json(_stage_round_store_path(normalized_team_id), store)
    _record_workflow_event(
        "research_stage_round.memory_retry_recorded",
        normalized_team_id,
        fields={"stageRoundId": normalized_round_id, "stageType": stage_round.get("stageType", "")},
    )
    return {
        "stageRound": stage_round,
        "teamMemoryRecord": stage_round["teamMemoryRecord"],
        "status": get_research_stage_round_status(normalized_team_id),
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
    chunk_id = _trim_text(payload.get("chunkId"), max_length=128)
    with _WORKFLOW_LOCK:
        candidate_store = _load_candidate_store(normalized_team_id)
        source_candidate = _find_candidate(candidate_store, normalized_candidate_id)
        if source_candidate is None:
            raise TeamWorkflowOrchestrationError("Candidate not found.")
        if str(source_candidate.get("candidateType") or "") != "source_manifest":
            raise TeamWorkflowOrchestrationError("Paper note autodraft requires a source_manifest candidate.")
        extraction = _ready_source_extraction(source_candidate)
        chunk = _paper_note_chunk_by_id(source_candidate, chunk_id) if chunk_id else None
        if chunk_id and chunk is None:
            raise TeamWorkflowOrchestrationError("Paper note chunkId was not found on this source candidate.")
        chunk_anchors = _page_anchors_for_paper_note_chunk(source_candidate, extraction, chunk) if chunk else []
        excerpt = excerpt_override or (
            _excerpt_from_page_anchors(chunk_anchors, max_chars=24_000)
            if chunk_anchors
            else _trim_text(extraction.get("excerpt"), max_length=24_000)
        )
        if not excerpt:
            raise TeamWorkflowOrchestrationError("Source extraction does not include excerpt text for paper_note drafting.")
        source_refs = [_source_manifest_source_ref(source_candidate)]
        evidence_refs = _source_extraction_evidence_refs(
            source_candidate,
            extraction,
            anchor_ids=set(_normalize_id_values(chunk.get("anchorIds"))) if chunk else None,
        )
        if not evidence_refs:
            raise TeamWorkflowOrchestrationError("Source extraction does not include page anchors for paper_note drafting.")
        candidate_refs = [
            {
                "type": "source_manifest",
                "id": normalized_candidate_id,
                "label": _source_manifest_label(source_candidate),
            }
        ]
        if chunk:
            candidate_refs.append(
                {
                    "type": "paper_note_chunk",
                    "id": chunk_id,
                    "label": str(chunk.get("pageScope") or chunk_id),
                }
            )
        page_scope = str((chunk or {}).get("pageScope") or extraction.get("pageScope") or source_candidate.get("pageScope") or "")
        paper_note_title = title_override or f"paper_note draft - {_source_manifest_label(source_candidate)}{f' - {page_scope}' if page_scope else ''}"
        paper_note_summary = summary_override or f"Autodrafted from sourceExtraction pageScope {page_scope}".strip()

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
                "pageScope": page_scope,
                "chunkId": chunk_id,
            }
            metadata["paperNoteDrafts"] = [*drafts[-23:], draft_record]
            if chunk_id:
                metadata["paperNoteChunkPlan"] = _update_paper_note_chunk_plan_progress(
                    metadata.get("paperNoteChunkPlan"),
                    chunk_id=chunk_id,
                    paper_note_candidate_id=str(paper_note_candidate.get("candidateId") or ""),
                    task_id=str(task.get("taskId") or ""),
                    valid=validation.get("valid") is True,
                    updated_at=now,
                )
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


def extract_neuro_mechanism_from_paper_note(
    team_id: str,
    payload: dict[str, Any] | None = None,
    *,
    llm_client_factory: Any = None,
) -> dict[str, Any]:
    """N-02：从 paper_note 候选抽取 neuro_mechanism 候选（节点 03 专用编排）。

    复用 invoke_local_research_model 的 neuro_mechanism_extract 任务（含 schema 校验）；
    在 paper_note 上以 metadata.mechanismDrafts 记录 supports 边/谱系；并施加置信度门禁：
    confidence < 0.45 → review_needs_human，不自动进入节点 04。
    """
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    team_service.get_team(normalized_team_id)
    payload = payload if isinstance(payload, dict) else {}
    paper_note_id = _normalize_required_id(payload.get("paperNoteId") or payload.get("candidateId"), "paperNoteId is required.")
    created_by_agent = _trim_text(payload.get("createdByAgent"), max_length=160) or "NeuroMechanism Extraction Agent"
    model_id = _trim_text(payload.get("modelId"), max_length=160)
    with _WORKFLOW_LOCK:
        candidate_store = _load_candidate_store(normalized_team_id)
        paper_note = _find_candidate(candidate_store, paper_note_id)
        if paper_note is None:
            raise TeamWorkflowOrchestrationError("Candidate not found.")
        if str(paper_note.get("candidateType") or "") != "paper_note":
            raise TeamWorkflowOrchestrationError("Neuro mechanism extraction requires a paper_note candidate.")
        note_payload = paper_note.get("payload") if isinstance(paper_note.get("payload"), dict) else {}
        source_refs = _normalize_ref_list(paper_note.get("sourceRefs") or note_payload.get("sourceRefs"), max_items=24)
        evidence_refs = _normalize_ref_list(paper_note.get("evidenceRefs") or note_payload.get("evidenceRefs"), max_items=24)
        if not evidence_refs:
            raise TeamWorkflowOrchestrationError("paper_note candidate has no evidenceRefs for mechanism extraction.")
        candidate_refs = [{"type": "paper_note", "id": paper_note_id, "label": str(paper_note.get("title") or paper_note_id)}]
        excerpt = _trim_text(payload.get("excerpt"), max_length=24_000) or _trim_text(paper_note.get("summary"), max_length=24_000)

    invoke_response = invoke_local_research_model(
        normalized_team_id,
        {
            "taskType": "neuro_mechanism_extract",
            "modelId": model_id,
            "sourceRefs": source_refs,
            "evidenceRefs": evidence_refs,
            "candidateRefs": candidate_refs,
            "paperNoteIds": [paper_note_id],
            "excerpt": excerpt,
            "createdByAgent": created_by_agent,
        },
        llm_client_factory=llm_client_factory,
    )
    mechanism_candidate = invoke_response.get("candidate") if isinstance(invoke_response.get("candidate"), dict) else {}
    validation = invoke_response.get("validation") if isinstance(invoke_response.get("validation"), dict) else {"valid": False, "issues": []}
    task = invoke_response.get("task") if isinstance(invoke_response.get("task"), dict) else {}
    raw_confidence = mechanism_candidate.get("confidence")
    try:
        confidence = float(raw_confidence) if raw_confidence is not None and str(raw_confidence) != "" else None
    except (TypeError, ValueError):
        confidence = None
    gate = "ready" if (validation.get("valid") is True and (confidence is None or confidence >= 0.45)) else "review_needs_human"
    now = utc_now_iso()
    with _WORKFLOW_LOCK:
        workflow = _load_or_create_workflow(normalized_team_id)
        candidate_store = _load_candidate_store(normalized_team_id)
        paper_note = _find_candidate(candidate_store, paper_note_id)
        if paper_note is not None:
            metadata = paper_note.get("metadata") if isinstance(paper_note.get("metadata"), dict) else {}
            drafts = metadata.get("mechanismDrafts") if isinstance(metadata.get("mechanismDrafts"), list) else []
            metadata["mechanismDrafts"] = [
                *drafts[-23:],
                {
                    "candidateId": str(mechanism_candidate.get("candidateId") or ""),
                    "taskId": str(task.get("taskId") or ""),
                    "edgeType": "supports",
                    "gate": gate,
                    "confidence": confidence,
                    "valid": validation.get("valid") is True,
                    "createdByAgent": created_by_agent,
                    "createdAt": now,
                },
            ]
            paper_note["metadata"] = metadata
            paper_note["updatedAt"] = now
            candidate_store["updatedAt"] = now
            _write_json(_candidate_store_path(normalized_team_id), candidate_store)
        else:
            paper_note = {}
    _record_workflow_event(
        "candidate.neuro_mechanism_extracted",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "paperNoteCandidateId": paper_note_id,
            "mechanismCandidateId": str(mechanism_candidate.get("candidateId") or ""),
            "gate": gate,
            "valid": validation.get("valid") is True,
        },
    )
    invoke_response["paperNoteCandidate"] = paper_note
    invoke_response["mechanismGate"] = gate
    invoke_response["workflow"] = _workflow_to_api(normalized_team_id, workflow, candidate_store)
    return invoke_response


def map_mechanism_to_abstraction(
    team_id: str,
    payload: dict[str, Any] | None = None,
    *,
    llm_client_factory: Any = None,
) -> dict[str, Any]:
    """N-03：把 neuro_mechanism 候选映射为 mechanism_mapping 候选（节点 04 专用编排）。

    门禁：overAnalogyRisk=high → review_needs_human，不自动进入节点 05；在 neuro_mechanism 上
    以 metadata.mappingDrafts 记录 maps_to 谱系。
    """
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    team_service.get_team(normalized_team_id)
    payload = payload if isinstance(payload, dict) else {}
    mechanism_id = _normalize_required_id(payload.get("mechanismId") or payload.get("candidateId"), "mechanismId is required.")
    created_by_agent = _trim_text(payload.get("createdByAgent"), max_length=160) or "Mechanism Mapping Agent"
    model_id = _trim_text(payload.get("modelId"), max_length=160)
    with _WORKFLOW_LOCK:
        candidate_store = _load_candidate_store(normalized_team_id)
        mechanism = _find_candidate(candidate_store, mechanism_id)
        if mechanism is None:
            raise TeamWorkflowOrchestrationError("Candidate not found.")
        if str(mechanism.get("candidateType") or "") != "neuro_mechanism":
            raise TeamWorkflowOrchestrationError("Mechanism mapping requires a neuro_mechanism candidate.")
        mech_payload = mechanism.get("payload") if isinstance(mechanism.get("payload"), dict) else {}
        source_refs = _normalize_ref_list(mechanism.get("sourceRefs") or mech_payload.get("sourceRefs"), max_items=24)
        evidence_refs = _normalize_ref_list(mechanism.get("evidenceRefs") or mech_payload.get("evidenceRefs"), max_items=24)
        if not evidence_refs:
            raise TeamWorkflowOrchestrationError("neuro_mechanism candidate has no evidenceRefs for mapping.")
        candidate_refs = [{"type": "neuro_mechanism", "id": mechanism_id, "label": str(mechanism.get("title") or mechanism_id)}]
        excerpt = _trim_text(payload.get("excerpt"), max_length=24_000) or _trim_text(mechanism.get("summary"), max_length=24_000)

    invoke_response = invoke_local_research_model(
        normalized_team_id,
        {
            "taskType": "mechanism_mapping",
            "modelId": model_id,
            "sourceRefs": source_refs,
            "evidenceRefs": evidence_refs,
            "candidateRefs": candidate_refs,
            "neuroMechanismIds": [mechanism_id],
            "excerpt": excerpt,
            "createdByAgent": created_by_agent,
        },
        llm_client_factory=llm_client_factory,
    )
    mapping_candidate = invoke_response.get("candidate") if isinstance(invoke_response.get("candidate"), dict) else {}
    validation = invoke_response.get("validation") if isinstance(invoke_response.get("validation"), dict) else {"valid": False, "issues": []}
    task = invoke_response.get("task") if isinstance(invoke_response.get("task"), dict) else {}
    over_analogy = str(mapping_candidate.get("overAnalogyRisk") or "").strip().lower()
    gate = "ready" if (validation.get("valid") is True and over_analogy != "high") else "review_needs_human"
    now = utc_now_iso()
    with _WORKFLOW_LOCK:
        workflow = _load_or_create_workflow(normalized_team_id)
        candidate_store = _load_candidate_store(normalized_team_id)
        mechanism = _find_candidate(candidate_store, mechanism_id)
        if mechanism is not None:
            metadata = mechanism.get("metadata") if isinstance(mechanism.get("metadata"), dict) else {}
            drafts = metadata.get("mappingDrafts") if isinstance(metadata.get("mappingDrafts"), list) else []
            metadata["mappingDrafts"] = [
                *drafts[-23:],
                {
                    "candidateId": str(mapping_candidate.get("candidateId") or ""),
                    "taskId": str(task.get("taskId") or ""),
                    "edgeType": "maps_to",
                    "gate": gate,
                    "overAnalogyRisk": over_analogy,
                    "valid": validation.get("valid") is True,
                    "createdByAgent": created_by_agent,
                    "createdAt": now,
                },
            ]
            mechanism["metadata"] = metadata
            mechanism["updatedAt"] = now
            candidate_store["updatedAt"] = now
            _write_json(_candidate_store_path(normalized_team_id), candidate_store)
        else:
            mechanism = {}
    _record_workflow_event(
        "candidate.mechanism_mapping_created",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "neuroMechanismCandidateId": mechanism_id,
            "mappingCandidateId": str(mapping_candidate.get("candidateId") or ""),
            "gate": gate,
            "overAnalogyRisk": over_analogy,
            "valid": validation.get("valid") is True,
        },
    )
    invoke_response["mechanismCandidate"] = mechanism
    invoke_response["mappingGate"] = gate
    invoke_response["workflow"] = _workflow_to_api(normalized_team_id, workflow, candidate_store)
    return invoke_response


def generate_algorithm_hypothesis_from_mechanism_mapping(
    team_id: str,
    payload: dict[str, Any] | None = None,
    *,
    llm_client_factory: Any = None,
) -> dict[str, Any]:
    """N-04：从 mechanism_mapping 生成 algorithm_hypothesis 候选（节点 05 专用编排）。

    门禁：上游 overAnalogyRisk=high 不得生成（须先过 Review Gate）；输出须含 experimentPlan/baseline
    （由 schema 校验保证），否则 revise_required；在 mechanism_mapping 上以 metadata.hypothesisDrafts
    记录 inspires 谱系。
    """
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    team_service.get_team(normalized_team_id)
    payload = payload if isinstance(payload, dict) else {}
    mapping_id = _normalize_required_id(payload.get("mappingId") or payload.get("candidateId"), "mappingId is required.")
    created_by_agent = _trim_text(payload.get("createdByAgent"), max_length=160) or "Algorithm Hypothesis Agent"
    model_id = _trim_text(payload.get("modelId"), max_length=160)
    with _WORKFLOW_LOCK:
        candidate_store = _load_candidate_store(normalized_team_id)
        mapping = _find_candidate(candidate_store, mapping_id)
        if mapping is None:
            raise TeamWorkflowOrchestrationError("Candidate not found.")
        if str(mapping.get("candidateType") or "") != "mechanism_mapping":
            raise TeamWorkflowOrchestrationError("Hypothesis generation requires a mechanism_mapping candidate.")
        map_payload = mapping.get("payload") if isinstance(mapping.get("payload"), dict) else {}
        map_metadata = mapping.get("metadata") if isinstance(mapping.get("metadata"), dict) else {}
        over_analogy = str(
            mapping.get("overAnalogyRisk") or map_payload.get("overAnalogyRisk") or map_metadata.get("overAnalogyRisk") or ""
        ).strip().lower()
        if over_analogy == "high":
            raise TeamWorkflowOrchestrationError("high overAnalogyRisk mapping must pass Review Gate before hypothesis generation.")
        source_refs = _normalize_ref_list(mapping.get("sourceRefs") or map_payload.get("sourceRefs"), max_items=24)
        evidence_refs = _normalize_ref_list(mapping.get("evidenceRefs") or map_payload.get("evidenceRefs"), max_items=24)
        if not evidence_refs:
            raise TeamWorkflowOrchestrationError("mechanism_mapping candidate has no evidenceRefs for hypothesis generation.")
        candidate_refs = [{"type": "mechanism_mapping", "id": mapping_id, "label": str(mapping.get("title") or mapping_id)}]
        excerpt = _trim_text(payload.get("excerpt"), max_length=24_000) or _trim_text(mapping.get("summary"), max_length=24_000)

    invoke_response = invoke_local_research_model(
        normalized_team_id,
        {
            "taskType": "algorithm_hypothesis_draft",
            "modelId": model_id,
            "sourceRefs": source_refs,
            "evidenceRefs": evidence_refs,
            "candidateRefs": candidate_refs,
            "mechanismMappingIds": [mapping_id],
            "excerpt": excerpt,
            "createdByAgent": created_by_agent,
        },
        llm_client_factory=llm_client_factory,
    )
    hypothesis_candidate = invoke_response.get("candidate") if isinstance(invoke_response.get("candidate"), dict) else {}
    validation = invoke_response.get("validation") if isinstance(invoke_response.get("validation"), dict) else {"valid": False, "issues": []}
    task = invoke_response.get("task") if isinstance(invoke_response.get("task"), dict) else {}
    gate = "review_ready" if validation.get("valid") is True else "revise_required"
    now = utc_now_iso()
    with _WORKFLOW_LOCK:
        workflow = _load_or_create_workflow(normalized_team_id)
        candidate_store = _load_candidate_store(normalized_team_id)
        mapping = _find_candidate(candidate_store, mapping_id)
        if mapping is not None:
            metadata = mapping.get("metadata") if isinstance(mapping.get("metadata"), dict) else {}
            drafts = metadata.get("hypothesisDrafts") if isinstance(metadata.get("hypothesisDrafts"), list) else []
            metadata["hypothesisDrafts"] = [
                *drafts[-23:],
                {
                    "candidateId": str(hypothesis_candidate.get("candidateId") or ""),
                    "taskId": str(task.get("taskId") or ""),
                    "edgeType": "inspires",
                    "gate": gate,
                    "valid": validation.get("valid") is True,
                    "createdByAgent": created_by_agent,
                    "createdAt": now,
                },
            ]
            mapping["metadata"] = metadata
            mapping["updatedAt"] = now
            candidate_store["updatedAt"] = now
            _write_json(_candidate_store_path(normalized_team_id), candidate_store)
        else:
            mapping = {}
    _record_workflow_event(
        "candidate.algorithm_hypothesis_generated",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "mechanismMappingCandidateId": mapping_id,
            "hypothesisCandidateId": str(hypothesis_candidate.get("candidateId") or ""),
            "gate": gate,
            "valid": validation.get("valid") is True,
        },
    )
    invoke_response["mappingCandidate"] = mapping
    invoke_response["hypothesisGate"] = gate
    invoke_response["workflow"] = _workflow_to_api(normalized_team_id, workflow, candidate_store)
    return invoke_response


RESEARCH_REVIEW_DECISIONS = {"approve", "revise", "reject", "needs_human"}


def _research_review_checklist(candidate: dict[str, Any]) -> tuple[dict[str, bool], list[str]]:
    """对单个候选做科研审稿 checklist，返回 (checklist, blockingRiskFlags)。"""
    candidate_type = str(candidate.get("candidateType") or "")
    cpayload = candidate.get("payload") if isinstance(candidate.get("payload"), dict) else {}
    cmeta = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}

    def field(name: str) -> Any:
        return candidate.get(name) or cpayload.get(name) or cmeta.get(name)

    evidence = candidate.get("evidenceRefs") or cpayload.get("evidenceRefs")
    over_analogy = str(field("overAnalogyRisk") or "").strip().lower()
    has_experiment = bool(field("experimentPlan"))
    needs_fact_boundary = candidate_type in ("mechanism_mapping", "algorithm_hypothesis")
    checklist = {
        "citation": bool(evidence),
        "factBoundary": (not needs_fact_boundary) or bool(field("factLayer") or field("inferenceLayer")),
        "overAnalogy": over_analogy != "high",
        "testability": candidate_type != "algorithm_hypothesis" or has_experiment,
    }
    flags: list[str] = []
    if not checklist["citation"]:
        flags.append("missing_evidence")
    if not checklist["overAnalogy"]:
        flags.append("high_over_analogy")
    if not checklist["testability"]:
        flags.append("no_metric")
    return checklist, flags


def decide_research_review(team_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """N-05：科研审稿决策门禁（节点 06）。对候选链路做 checklist，输出 review_record 决策。

    硬门禁：missing_evidence / high_over_analogy / no_metric 任一为真 → 不得 approve；
    reject 必须带 rejectionReason（requiredChanges 或 comments）。在被审候选上以
    metadata.reviewRecords 记录 reviewed_by 谱系。
    """
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    team_service.get_team(normalized_team_id)
    payload = payload if isinstance(payload, dict) else {}
    candidate_ids = _normalize_text_list(payload.get("candidateIds"), max_items=24, max_length=128)
    if not candidate_ids:
        raise TeamWorkflowOrchestrationError("candidateIds is required for research review.")
    reviewed_by = _trim_text(payload.get("reviewedByAgent"), max_length=160) or "Evidence Review Agent"
    requested_decision = _trim_text(payload.get("decision"), max_length=40).strip().lower()
    if requested_decision and requested_decision not in RESEARCH_REVIEW_DECISIONS:
        raise TeamWorkflowOrchestrationError("decision must be approve/revise/reject/needs_human.")
    comments = _trim_text(payload.get("comments"), max_length=4000)
    required_changes = _normalize_text_list(payload.get("requiredChanges"), max_items=24, max_length=400)
    now = utc_now_iso()
    with _WORKFLOW_LOCK:
        candidate_store = _load_candidate_store(normalized_team_id)
        reviewed: list[dict[str, Any]] = []
        checklist_all: dict[str, dict[str, bool]] = {}
        risk_flags: set[str] = set()
        for candidate_id in candidate_ids:
            candidate = _find_candidate(candidate_store, candidate_id)
            if candidate is None:
                raise TeamWorkflowOrchestrationError(f"Candidate not found: {candidate_id}")
            checklist, flags = _research_review_checklist(candidate)
            checklist_all[candidate_id] = checklist
            risk_flags.update(flags)
            reviewed.append(candidate)
        risk_flag_list = sorted(risk_flags)
        recommended = "needs_human" if risk_flag_list else "approve"
        decision = requested_decision or recommended
        if decision == "approve" and risk_flag_list:
            raise TeamWorkflowOrchestrationError(f"Cannot approve with blocking risk flags: {risk_flag_list}.")
        if decision == "reject" and not (required_changes or comments):
            raise TeamWorkflowOrchestrationError("reject requires a rejectionReason via requiredChanges or comments.")
        review_id = _new_record_id("candidate")
        review_record = {
            "schemaVersion": SCHEMA_VERSION,
            "candidateId": review_id,
            "candidateType": "review_record",
            "teamId": normalized_team_id,
            "title": f"review_record for {', '.join(candidate_ids[:3])}",
            "currentState": "review_ready" if decision == "approve" else decision,
            "qualityStatus": "reviewed",
            "reviewedCandidateIds": candidate_ids,
            "decision": decision,
            "checklist": checklist_all,
            "riskFlags": risk_flag_list,
            "requiredChanges": required_changes,
            "comments": comments,
            "reviewedByAgent": reviewed_by,
            "createdByAgent": reviewed_by,
            "createdAt": now,
            "updatedAt": now,
        }
        review_record["envelopeValidation"] = candidate_schema_registry.validate_envelope(review_record)
        candidate_store.setdefault("candidates", []).append(review_record)
        for candidate in reviewed:
            metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
            records = metadata.get("reviewRecords") if isinstance(metadata.get("reviewRecords"), list) else []
            metadata["reviewRecords"] = [
                *records[-23:],
                {"reviewRecordId": review_id, "decision": decision, "edgeType": "reviewed_by", "createdAt": now},
            ]
            candidate["metadata"] = metadata
            candidate["updatedAt"] = now
        candidate_store["updatedAt"] = now
        _write_json(_candidate_store_path(normalized_team_id), candidate_store)
        workflow = _load_or_create_workflow(normalized_team_id)
    _record_workflow_event(
        "research.review_decided",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "reviewRecordId": review_id,
            "decision": decision,
            "candidateCount": len(candidate_ids),
            "riskFlagCount": len(risk_flag_list),
        },
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "reviewRecord": review_record,
        "decision": decision,
        "riskFlags": risk_flag_list,
        "checklist": checklist_all,
        "workflow": _workflow_to_api(normalized_team_id, workflow, candidate_store),
    }


ITERATION_ACTIONS = {"iterate", "reject", "merge", "hold"}


def propose_iteration(team_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """N-12：持续迭代与版本化（节点 11）。根据 RunnerResult/审稿/steward 决策提出迭代提案。

    硬约束：不覆盖原候选，只新建版本/归档；无 changeReason 的状态变化拒绝写入；检测并拒绝
    circular supersedes。版本链边记录在父候选 metadata.versionEdges（supersedes / rejected_because /
    merged_with），提案记录在 metadata.iterationProposals。
    """
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    team_service.get_team(normalized_team_id)
    payload = payload if isinstance(payload, dict) else {}
    parent_id = _normalize_required_id(payload.get("parentCandidateId") or payload.get("candidateId"), "parentCandidateId is required.")
    action = _trim_text(payload.get("action"), max_length=40).strip().lower()
    if action not in ITERATION_ACTIONS:
        raise TeamWorkflowOrchestrationError("action must be iterate/reject/merge/hold.")
    change_reason = _trim_text(payload.get("changeReason"), max_length=2000)
    if action != "hold" and not change_reason:
        raise TeamWorkflowOrchestrationError(f"{action} iteration requires a changeReason.")
    proposed_by = _trim_text(payload.get("proposedByAgent"), max_length=160) or "Iteration Versioning Agent"
    merge_with = _trim_text(payload.get("mergeWithCandidateId"), max_length=128)
    now = utc_now_iso()
    with _WORKFLOW_LOCK:
        candidate_store = _load_candidate_store(normalized_team_id)
        parent = _find_candidate(candidate_store, parent_id)
        if parent is None:
            raise TeamWorkflowOrchestrationError("Candidate not found.")
        metadata = parent.get("metadata") if isinstance(parent.get("metadata"), dict) else {}
        version_edges = metadata.get("versionEdges") if isinstance(metadata.get("versionEdges"), list) else []
        proposal_id = _new_record_id("iteration")
        new_edges: list[dict[str, Any]] = []
        new_draft: dict[str, Any] | None = None
        rejection_archive: dict[str, Any] | None = None
        if action == "iterate":
            draft_id = _new_record_id("candidate")
            new_draft = {
                "candidateId": draft_id,
                "parentCandidateId": parent_id,
                "candidateType": str(parent.get("candidateType") or ""),
                "status": "iteration_draft",
                "changeReason": change_reason,
            }
            new_edges.append({"edgeType": "supersedes", "from": draft_id, "to": parent_id})
        elif action == "reject":
            rejection_archive = {
                "parentCandidateId": parent_id,
                "reason": change_reason,
                "evidenceRefs": _normalize_ref_list(payload.get("evidenceRefs"), max_items=24),
                "archivedAt": now,
            }
            new_edges.append({"edgeType": "rejected_because", "from": parent_id, "to": proposal_id})
        elif action == "merge":
            if not merge_with:
                raise TeamWorkflowOrchestrationError("merge iteration requires mergeWithCandidateId.")
            new_edges.append({"edgeType": "merged_with", "from": parent_id, "to": merge_with})
        for edge in new_edges:
            if edge["edgeType"] != "supersedes":
                continue
            for existing in version_edges:
                if (
                    existing.get("edgeType") == "supersedes"
                    and existing.get("from") == edge["to"]
                    and existing.get("to") == edge["from"]
                ):
                    raise TeamWorkflowOrchestrationError("Circular supersedes detected; cannot create version cycle.")
        proposal = {
            "proposalId": proposal_id,
            "parentCandidateId": parent_id,
            "action": action,
            "changeReason": change_reason,
            "versionEdges": new_edges,
            "newCandidateDraft": new_draft,
            "rejectionArchive": rejection_archive,
            "mergeWithCandidateId": merge_with,
            "proposedByAgent": proposed_by,
            "createdAt": now,
        }
        proposals = metadata.get("iterationProposals") if isinstance(metadata.get("iterationProposals"), list) else []
        metadata["iterationProposals"] = [*proposals[-23:], proposal]
        metadata["versionEdges"] = [*version_edges, *new_edges]
        parent["metadata"] = metadata
        parent["updatedAt"] = now
        candidate_store["updatedAt"] = now
        _write_json(_candidate_store_path(normalized_team_id), candidate_store)
        workflow = _load_or_create_workflow(normalized_team_id)
        version_edges_after = list(metadata["versionEdges"])
    _record_workflow_event(
        "candidate.iteration_proposed",
        normalized_team_id,
        fields={"parentCandidateId": parent_id, "proposalId": proposal_id, "action": action},
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "parentCandidateId": parent_id,
        "action": action,
        "proposal": proposal,
        "versionEdges": version_edges_after,
        "workflowId": workflow["workflowId"],
    }


def export_deliverables(team_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """N-13：交付材料导出（节点 12）。只读 official/approved/明确标注的证据，生成
    deliverable_manifest + blockers；不反写知识库。证据不足时输出 blocker 清单而非伪造完整材料。
    """
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    team_service.get_team(normalized_team_id)
    payload = payload if isinstance(payload, dict) else {}
    requested_by = _trim_text(payload.get("requestedByAgent"), max_length=160) or "Challenge Cup Delivery Agent"
    now = utc_now_iso()

    candidate_store = _load_candidate_store(normalized_team_id)
    candidates = [item for item in list(candidate_store.get("candidates") or []) if isinstance(item, dict)]
    candidate_breakdown: dict[str, int] = {}
    for candidate in candidates:
        candidate_type = str(candidate.get("candidateType") or "")
        candidate_breakdown[candidate_type] = candidate_breakdown.get(candidate_type, 0) + 1

    reviewed_hypotheses = [
        candidate
        for candidate in candidates
        if candidate.get("candidateType") == "algorithm_hypothesis"
        and isinstance(candidate.get("metadata"), dict)
        and any(
            str(record.get("decision")) == "approve"
            for record in (candidate["metadata"].get("reviewRecords") or [])
            if isinstance(record, dict)
        )
    ]

    plan_store = _load_experiment_plan_store(normalized_team_id)
    artifact_refs: list[dict[str, Any]] = []
    for plan in list(plan_store.get("plans") or []):
        if not isinstance(plan, dict):
            continue
        for run in plan.get("smokeRunResults") or []:
            if isinstance(run, dict) and run.get("artifactHash"):
                artifact_refs.append(
                    {
                        "planId": plan.get("planId"),
                        "smokeRunId": run.get("smokeRunId"),
                        "artifactHash": run.get("artifactHash"),
                        "status": run.get("status"),
                    }
                )

    ingestion_status = get_knowledge_ingestion_status(normalized_team_id)
    formal_item_count = int((ingestion_status.get("summary") or {}).get("formalKnowledgeItemCount") or 0)

    evidence_refs: list[dict[str, str]] = []
    for candidate in reviewed_hypotheses:
        evidence_refs.extend(_normalize_ref_list(candidate.get("evidenceRefs"), max_items=24))

    blockers: list[dict[str, str]] = []
    if not reviewed_hypotheses:
        blockers.append({"code": "no_reviewed_hypothesis", "message": "至少需要 1 个已审稿通过的 algorithm_hypothesis。"})
    if not artifact_refs:
        blockers.append({"code": "experiment_loop_incomplete", "message": "缺 runner_result/artifactHash；实验闭环未完成。"})
    if formal_item_count <= 0:
        blockers.append({"code": "no_official_knowledge", "message": "尚无正式 KnowledgeItem（official_synced）。"})

    sections = [
        {"key": "problem", "label": "问题定义", "ready": bool(reviewed_hypotheses)},
        {"key": "architecture", "label": "方法/架构", "ready": bool(reviewed_hypotheses)},
        {"key": "experiment", "label": "实验与证据", "ready": bool(artifact_refs)},
        {"key": "reproducibility", "label": "复现包", "ready": bool(artifact_refs)},
        {"key": "official_knowledge", "label": "正式知识", "ready": formal_item_count > 0},
    ]
    manifest = {
        "deliverableId": _new_record_id("deliverable"),
        "teamId": normalized_team_id,
        "generatedAt": now,
        "requestedByAgent": requested_by,
        "sections": sections,
        "evidenceRefs": evidence_refs[:48],
        "artifactRefs": artifact_refs[:48],
        "officialBoundary": {
            "formalKnowledgeItemCount": formal_item_count,
            "reusesOfficialOnly": True,
            "writesBackToKnowledge": False,
        },
        "candidateBreakdown": candidate_breakdown,
        "blockers": blockers,
        "status": "ready" if not blockers else "blocked",
    }
    _record_workflow_event(
        "deliverables.exported",
        normalized_team_id,
        fields={"deliverableId": manifest["deliverableId"], "status": manifest["status"], "blockerCount": len(blockers)},
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "deliverableManifest": manifest,
        "status": manifest["status"],
        "blockers": blockers,
    }


_PRD_EXPECTED_ENDPOINTS = (
    "knowledge-collection/extract",
    "research/mechanisms/extract",
    "research/mechanisms/map",
    "research/hypotheses/generate",
    "research/review/decide",
    "experiments/plans/{plan_id}/smoke-run",
    "iterations/propose",
    "deliverables/export",
)


def validate_prd(team_id: str, payload: dict[str, Any] | None = None, *, registered_paths: list[str] | None = None) -> dict[str, Any]:
    """N-14：PRD 校验门禁（节点 13）。校验代码侧契约一致性，避免 PRD 与实现脱节（R7）。

    检查项：①schemas/ 声明文件存在且可加载；②registry 与 service 的 CANDIDATE_TYPES /
    LOCAL_RESEARCH_TASKS 一致（防漂移）；③科研生成链端点已注册（需路由层传入 registered_paths）；
    ④smoke runner 具白名单 + 固定 seed + artifactHash。任一失败 → valid=False。
    """
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    team_service.get_team(normalized_team_id)
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    schema_ids = candidate_schema_registry.candidate_schema_ids()
    try:
        for name in schema_ids:
            candidate_schema_registry.load_schema(name)
        add("schemas_present", True, f"{len(schema_ids)} schema file(s)")
    except (OSError, ValueError) as exc:
        add("schemas_present", False, str(exc))

    add(
        "candidate_types_in_sync",
        set(candidate_schema_registry.CANDIDATE_TYPES) == set(CANDIDATE_TYPES),
        "registry vs service CANDIDATE_TYPES",
    )
    task_sync = set(candidate_schema_registry.RESEARCH_TASK_REQUIRED_OUTPUT) == set(LOCAL_RESEARCH_TASKS) and all(
        tuple(LOCAL_RESEARCH_TASKS[task]["requiredOutput"]) == fields
        for task, fields in candidate_schema_registry.RESEARCH_TASK_REQUIRED_OUTPUT.items()
    )
    add("research_task_outputs_in_sync", task_sync, "registry vs LOCAL_RESEARCH_TASKS requiredOutput")

    if registered_paths is not None:
        joined = "\n".join(str(path) for path in registered_paths)
        missing = [endpoint for endpoint in _PRD_EXPECTED_ENDPOINTS if endpoint not in joined]
        add("research_endpoints_registered", not missing, f"missing={missing}" if missing else "all present")

    try:
        sample = smoke_runner.run_smoke_adapter("synthetic_classification_baseline_vs_variant", seed=42)
        runner_ok = (
            bool(smoke_runner.WHITELIST_ADAPTERS)
            and str(sample.get("artifactHash", "")).startswith("sha256:")
            and "seed" in sample
        )
        add("smoke_runner_markers", runner_ok, f"whitelist={len(smoke_runner.WHITELIST_ADAPTERS)}")
    except smoke_runner.SmokeRunnerError as exc:
        add("smoke_runner_markers", False, str(exc))

    failed = [item for item in checks if not item["ok"]]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "valid": not failed,
        "checks": checks,
        "failedCount": len(failed),
    }


def sync_official_research_graph(team_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """N-07：正式知识图谱同步（节点 09）。

    边界（硬约束）：本函数**不创建 KnowledgeItem**（正式知识只能经 知识库管理员 门禁产生），
    只对**已审批的 official 知识**做图谱关系投影并写可逆 sync log。门禁：formalKnowledgeItemCount==0
    （candidate-only）→ 拒绝同步。对相同知识状态幂等（除非 force）。
    """
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    team_service.get_team(normalized_team_id)
    payload = payload if isinstance(payload, dict) else {}
    synced_by = _trim_text(payload.get("syncedByAgent"), max_length=160) or "Ingestion Approval Gate"
    force = bool(payload.get("force"))
    status_view = get_knowledge_ingestion_status(normalized_team_id)
    summary = status_view.get("summary") if isinstance(status_view.get("summary"), dict) else {}
    formal_count = int(summary.get("formalKnowledgeItemCount") or 0)
    if formal_count <= 0:
        raise TeamWorkflowOrchestrationError(
            "No approved official KnowledgeItem to sync; candidate-only state cannot sync to official graph."
        )
    now = utc_now_iso()
    store_path = _workflow_path(normalized_team_id).parent / "official_graph_sync.json"
    with _WORKFLOW_LOCK:
        store = _read_json(store_path)
        log = store.get("syncs") if isinstance(store.get("syncs"), list) else []
        if not force:
            existing = next(
                (
                    item
                    for item in log
                    if isinstance(item, dict)
                    and item.get("status") == "completed"
                    and int(item.get("knowledgeItemCount") or 0) == formal_count
                ),
                None,
            )
            if existing is not None:
                return {
                    "schemaVersion": SCHEMA_VERSION,
                    "teamId": normalized_team_id,
                    "sync": existing,
                    "status": "completed",
                    "idempotentReuse": True,
                }
        sync_id = _new_record_id("graphsync")
        record = {
            "syncId": sync_id,
            "status": "completed",
            "graphStatus": "synced",
            "ragStatus": "synced",
            "knowledgeItemCount": formal_count,
            "edges": [{"edgeType": "approved_for_ingestion", "official": True, "knowledgeItemCount": formal_count}],
            "syncedByAgent": synced_by,
            "officialBoundary": {
                "writesOfficialGraph": True,
                "requiresStewardApproval": True,
                "reversible": True,
                "createsKnowledgeItem": False,
            },
            "syncedAt": now,
        }
        log.append(record)
        store["syncs"] = log[-24:]
        store["activeOfficialGraphSyncId"] = sync_id
        store["schemaVersion"] = SCHEMA_VERSION
        store["updatedAt"] = now
        _write_json(store_path, store)
    _record_workflow_event(
        "official_graph.synced",
        normalized_team_id,
        fields={"syncId": sync_id, "knowledgeItemCount": formal_count},
    )
    return {"schemaVersion": SCHEMA_VERSION, "teamId": normalized_team_id, "sync": record, "status": "completed"}


def rollback_official_research_graph(team_id: str, sync_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """N-08：回滚一次正式图谱同步。按 sync_id 将 status/graphStatus/ragStatus 置为 rolled_back，保留审计。"""
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    normalized_sync_id = _normalize_required_id(sync_id, "Sync id is required.")
    team_service.get_team(normalized_team_id)
    payload = payload if isinstance(payload, dict) else {}
    rolled_back_by = _trim_text(payload.get("rolledBackByAgent"), max_length=160) or "Ingestion Approval Gate"
    now = utc_now_iso()
    store_path = _workflow_path(normalized_team_id).parent / "official_graph_sync.json"
    with _WORKFLOW_LOCK:
        store = _read_json(store_path)
        log = store.get("syncs") if isinstance(store.get("syncs"), list) else []
        target = next(
            (item for item in log if isinstance(item, dict) and item.get("syncId") == normalized_sync_id), None
        )
        if target is None:
            raise TeamWorkflowOrchestrationError("Official graph sync record not found.")
        if target.get("status") == "rolled_back":
            raise TeamWorkflowOrchestrationError("Official graph sync is already rolled back.")
        target["status"] = "rolled_back"
        target["graphStatus"] = "rolled_back"
        target["ragStatus"] = "rolled_back"
        target["rolledBackByAgent"] = rolled_back_by
        target["rolledBackAt"] = now
        if store.get("activeOfficialGraphSyncId") == normalized_sync_id:
            store["activeOfficialGraphSyncId"] = ""
        store["syncs"] = log
        store["updatedAt"] = now
        _write_json(store_path, store)
    _record_workflow_event(
        "official_graph.rolled_back",
        normalized_team_id,
        fields={"syncId": normalized_sync_id},
    )
    return {"schemaVersion": SCHEMA_VERSION, "teamId": normalized_team_id, "sync": target, "status": "rolled_back"}


def plan_paper_note_chunks_from_source_candidate(team_id: str, candidate_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    normalized_candidate_id = _normalize_required_id(candidate_id, "Candidate id is required.")
    team_service.get_team(normalized_team_id)
    payload = payload if isinstance(payload, dict) else {}
    created_by_agent = _trim_text(payload.get("createdByAgent"), max_length=160) or "Paper Note Extraction Agent"
    max_pages_per_chunk = _normalize_int(
        payload.get("maxPagesPerChunk"),
        default=PAPER_NOTE_CHUNK_DEFAULT_MAX_PAGES,
        minimum=1,
        maximum=PAPER_NOTE_CHUNK_HARD_MAX_PAGES,
    )
    max_chars_per_chunk = _normalize_int(
        payload.get("maxCharsPerChunk"),
        default=PAPER_NOTE_CHUNK_DEFAULT_MAX_CHARS,
        minimum=2000,
        maximum=PAPER_NOTE_CHUNK_HARD_MAX_CHARS,
    )
    now = utc_now_iso()
    with _WORKFLOW_LOCK:
        workflow = _load_or_create_workflow(normalized_team_id)
        candidate_store = _load_candidate_store(normalized_team_id)
        source_candidate = _find_candidate(candidate_store, normalized_candidate_id)
        if source_candidate is None:
            raise TeamWorkflowOrchestrationError("Candidate not found.")
        if str(source_candidate.get("candidateType") or "") != "source_manifest":
            raise TeamWorkflowOrchestrationError("Paper note chunk planning requires a source_manifest candidate.")
        extraction = _ready_source_extraction(source_candidate)
        chunks = _build_paper_note_chunks(
            source_candidate,
            extraction,
            max_pages_per_chunk=max_pages_per_chunk,
            max_chars_per_chunk=max_chars_per_chunk,
        )
        if not chunks:
            raise TeamWorkflowOrchestrationError("Source extraction does not contain usable page anchors for paper_note chunks.")
        metadata = source_candidate.get("metadata") if isinstance(source_candidate.get("metadata"), dict) else {}
        chunk_plan = {
            "schemaVersion": SCHEMA_VERSION,
            "planId": _new_record_id("paper-note-plan"),
            "planKind": "paper_note_chunk_plan",
            "status": "planned",
            "sourceCandidateId": normalized_candidate_id,
            "sourceLabel": _source_manifest_label(source_candidate),
            "sourceSha256": str(extraction.get("sha256") or source_candidate.get("sha256") or ""),
            "pageScope": str(extraction.get("pageScope") or source_candidate.get("pageScope") or ""),
            "targetTaskType": "paper_note_draft",
            "targetWorkflowNode": "paper_note",
            "chunkStrategy": "page_anchor_window",
            "maxPagesPerChunk": max_pages_per_chunk,
            "maxCharsPerChunk": max_chars_per_chunk,
            "chunkCount": len(chunks),
            "completedChunkCount": 0,
            "needsRevisionChunkCount": 0,
            "chunks": chunks,
            "createdByAgent": created_by_agent,
            "createdAt": now,
            "updatedAt": now,
            "officialBoundary": {
                "writesFormalKnowledge": False,
                "writesRag": False,
                "writesOfficialGraph": False,
                "requiresPaperNoteReview": True,
            },
        }
        metadata["paperNoteChunkPlan"] = chunk_plan
        source_candidate["metadata"] = metadata
        source_candidate["updatedAt"] = now
        candidate_store["updatedAt"] = now
        _write_json(_candidate_store_path(normalized_team_id), candidate_store)
        workflow["updatedAt"] = now
        workflow["activeWorkflowItems"] = _upsert_active_item(
            workflow.get("activeWorkflowItems"),
            candidate_id=normalized_candidate_id,
            current_node=str(source_candidate.get("currentWorkflowNode") or "knowledge_collection"),
            status=str(source_candidate.get("currentState") or "source_registered"),
            transfer_id=str(source_candidate.get("pendingTransferId") or ""),
        )
        _write_json(_workflow_path(normalized_team_id), workflow)
    _record_workflow_event(
        "candidate.paper_note_chunk_plan_created",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "sourceCandidateId": normalized_candidate_id,
            "planId": chunk_plan["planId"],
            "chunkCount": chunk_plan["chunkCount"],
            "maxPagesPerChunk": max_pages_per_chunk,
        },
    )
    return {
        "candidate": source_candidate,
        "chunkPlan": chunk_plan,
        "workflow": _workflow_to_api(normalized_team_id, workflow, candidate_store),
        "nextActions": [
            "Paper Note Extraction Agent should draft one paper_note per planned chunk.",
            "Use chunkId when calling paper-note-draft to keep page anchors and plan progress traceable.",
            "Do not promote chunk drafts to formal Team Knowledge without steward approval.",
        ],
    }


def get_paper_note_chunk_status(team_id: str) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    team_service.get_team(normalized_team_id)
    with _WORKFLOW_LOCK:
        workflow = _load_or_create_workflow(normalized_team_id)
        candidate_store = _load_candidate_store(normalized_team_id)
        candidates = [item for item in list(candidate_store.get("candidates") or []) if isinstance(item, dict)]
    source_candidates = [item for item in candidates if str(item.get("candidateType") or "") == "source_manifest"]
    ready_sources = [item for item in source_candidates if _source_candidate_has_ready_extraction(item)]
    plans = [_paper_note_chunk_plan_summary(item) for item in source_candidates]
    plans = [item for item in plans if item is not None]
    chunk_count = sum(int(item.get("chunkCount") or 0) for item in plans)
    drafted_count = sum(int(item.get("draftedChunkCount") or 0) for item in plans)
    needs_revision_count = sum(int(item.get("needsRevisionChunkCount") or 0) for item in plans)
    open_count = max(0, chunk_count - drafted_count - needs_revision_count)
    missing_plan_sources = [
        {
            "candidateId": str(item.get("candidateId") or ""),
            "title": str(item.get("title") or _source_manifest_label(item)),
            "pageScope": str(((item.get("metadata") if isinstance(item.get("metadata"), dict) else {}).get("sourceExtraction") or {}).get("pageScope") or item.get("pageScope") or ""),
        }
        for item in ready_sources
        if _candidate_paper_note_chunk_plan(item) is None
    ]
    action_items = _paper_note_chunk_action_items(missing_plan_sources, plans, open_count)
    status = "empty"
    if plans:
        status = "ready" if open_count == 0 and needs_revision_count == 0 else "in_progress"
    elif missing_plan_sources:
        status = "needs_plan"
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "workflowId": workflow["workflowId"],
        "workflowKind": workflow["workflowKind"],
        "status": status,
        "summary": {
            "sourceCandidateCount": len(source_candidates),
            "readySourceCandidateCount": len(ready_sources),
            "plannedSourceCandidateCount": len(plans),
            "missingPlanSourceCandidateCount": len(missing_plan_sources),
            "planCount": len(plans),
            "chunkCount": chunk_count,
            "draftedChunkCount": drafted_count,
            "needsRevisionChunkCount": needs_revision_count,
            "openChunkCount": open_count,
            "actionItemCount": len(action_items),
        },
        "plans": sorted(plans, key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""), reverse=True)[:12],
        "missingPlanSources": missing_plan_sources[:12],
        "actionItems": action_items,
        "officialBoundary": {
            "writesFormalKnowledge": False,
            "writesRag": False,
            "writesOfficialGraph": False,
            "candidateOnly": True,
        },
        "storage": {
            "candidateStorePath": _relative_path(_candidate_store_path(normalized_team_id)),
        },
        "updatedAt": utc_now_iso(),
    }
    _record_workflow_event(
        "paper_note_chunks.status_viewed",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "status": status,
            "planCount": len(plans),
            "chunkCount": chunk_count,
            "openChunkCount": open_count,
            "missingPlanSourceCandidateCount": len(missing_plan_sources),
            "plannedSourceCandidateIds": _workflow_log_sample_values(plans, "sourceCandidateId"),
            "missingPlanSourceCandidateIds": _workflow_log_sample_values(missing_plan_sources, "candidateId"),
            "actionItemCodes": _workflow_log_sample_values(action_items, "code"),
        },
    )
    return payload


def assess_source_candidate_quality(team_id: str, candidate_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    normalized_candidate_id = _normalize_required_id(candidate_id, "Candidate id is required.")
    team_service.get_team(normalized_team_id)
    payload = payload if isinstance(payload, dict) else {}
    assessed_by_agent = _trim_text(payload.get("assessedByAgent"), max_length=160) or "Source Quality Assessment Agent"
    requested_decision = _trim_text(payload.get("decision"), max_length=80)
    if requested_decision and requested_decision not in SOURCE_QUALITY_DECISIONS:
        raise TeamWorkflowOrchestrationError("Source quality decision must be approved, needs_revision, or rejected.")
    notes = _trim_text(payload.get("notes"), max_length=4000)
    required_fixes = _normalize_text_list(payload.get("requiredFixes"), max_items=12, max_length=240)
    risk_flags = _normalize_text_list(payload.get("riskFlags"), max_items=12, max_length=120)
    evidence_refs = _normalize_ref_list(payload.get("evidenceRefs"), max_items=24)
    now = utc_now_iso()
    with _WORKFLOW_LOCK:
        workflow = _load_or_create_workflow(normalized_team_id)
        candidate_store = _load_candidate_store(normalized_team_id)
        candidate = _find_candidate(candidate_store, normalized_candidate_id)
        if candidate is None:
            raise TeamWorkflowOrchestrationError("Candidate not found.")
        if str(candidate.get("candidateType") or "") != "source_manifest":
            raise TeamWorkflowOrchestrationError("Source quality assessment only supports source_manifest candidates.")
        validation = validate_candidate_record(candidate)
        scores = _source_quality_scores(candidate, payload, validation)
        decision = requested_decision or _default_source_quality_decision(scores, validation)
        if decision == "approved" and not validation.get("valid"):
            decision = "needs_revision"
            if not required_fixes:
                required_fixes = ["修复 source_manifest 校验错误后再通过质量筛选。"]
        source_label = _source_manifest_label(candidate)
        assessment = {
            "schemaVersion": SCHEMA_VERSION,
            "assessmentId": _new_record_id("source-quality"),
            "assessmentKind": "source_quality_assessment",
            "candidateId": normalized_candidate_id,
            "sourceLabel": source_label,
            "decision": decision,
            "status": decision,
            "scores": scores,
            "requiredFixes": required_fixes,
            "riskFlags": risk_flags,
            "notes": notes,
            "evidenceRefs": evidence_refs,
            "assessedByAgent": assessed_by_agent,
            "assessedAt": now,
            "officialBoundary": {
                "writesFormalKnowledge": False,
                "writesRag": False,
                "writesOfficialGraph": False,
                "candidateOnly": True,
            },
        }
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        history = metadata.get("sourceQualityAssessments") if isinstance(metadata.get("sourceQualityAssessments"), list) else []
        metadata["sourceQualityAssessment"] = assessment
        metadata["sourceQualityAssessments"] = [*history[-11:], assessment]
        candidate["metadata"] = metadata
        candidate["validation"] = validation
        if decision == "approved":
            candidate["currentWorkflowNode"] = "knowledge_collection"
            candidate["currentState"] = "source_screened"
            candidate["qualityStatus"] = "source_quality_approved"
        elif decision == "rejected":
            candidate["currentWorkflowNode"] = "rejection_archive"
            candidate["currentState"] = "rejected"
            candidate["qualityStatus"] = "source_quality_rejected"
            metadata["rejectionArchive"] = {
                "reason": notes or "Source Quality Assessment Agent rejected this source candidate.",
                "rejectedByAgent": assessed_by_agent,
                "rejectedAt": now,
                "assessmentId": assessment["assessmentId"],
            }
        else:
            candidate["currentWorkflowNode"] = "knowledge_collection"
            candidate["currentState"] = "source_needs_quality_revision"
            candidate["qualityStatus"] = "source_quality_needs_revision"
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
        "candidate.source_quality_assessed",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "candidateId": normalized_candidate_id,
            "decision": decision,
            "overallScore": scores["overall"],
            "assessedByAgent": assessed_by_agent,
        },
    )
    return {
        "candidate": candidate,
        "assessment": assessment,
        "status": get_source_quality_status(normalized_team_id),
        "workflow": _workflow_to_api(normalized_team_id, workflow, candidate_store),
        "nextActions": _source_quality_next_actions(decision),
    }


def assess_source_quality_batch(team_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    team_service.get_team(normalized_team_id)
    payload = payload if isinstance(payload, dict) else {}
    batch_run_id = _new_record_id("source-quality-batch")
    assessed_by_agent = _trim_text(payload.get("assessedByAgent"), max_length=160) or "Source Quality Assessment Agent"
    max_candidates = _normalize_int(payload.get("maxCandidates"), default=100, minimum=1, maximum=200)
    force = bool(payload.get("force"))
    requested_candidate_ids = _normalize_text_list(payload.get("candidateIds"), max_items=200, max_length=128)
    notes = _trim_text(payload.get("notes"), max_length=4000) or "Source Quality Assessment Agent completed one-click batch screening."
    evidence_refs = _normalize_ref_list(payload.get("evidenceRefs"), max_items=24)
    evidence_refs = [
        *evidence_refs,
        {"type": "source_quality_batch", "id": batch_run_id, "label": "Source quality batch assessment"},
    ][:24]
    with _WORKFLOW_LOCK:
        candidate_store = _load_candidate_store(normalized_team_id)
        source_candidates = [
            item
            for item in list(candidate_store.get("candidates") or [])
            if isinstance(item, dict) and str(item.get("candidateType") or "") == "source_manifest"
        ]
        source_by_id = {str(item.get("candidateId") or ""): item for item in source_candidates if str(item.get("candidateId") or "")}
        if requested_candidate_ids:
            selection = [source_by_id[item] for item in requested_candidate_ids if item in source_by_id]
            skipped_candidates = [
                {"candidateId": item, "reason": "not_found_or_not_source_manifest"}
                for item in requested_candidate_ids
                if item not in source_by_id
            ]
        else:
            selection = source_candidates
            skipped_candidates = []
        target_candidates = [
            item
            for item in selection
            if force or _candidate_source_quality_assessment(item) is None
        ][:max_candidates]
        skipped_candidates.extend(
            {
                "candidateId": str(item.get("candidateId") or ""),
                "title": str(item.get("title") or _source_manifest_label(item)),
                "reason": "already_assessed",
            }
            for item in selection
            if item not in target_candidates and _candidate_source_quality_assessment(item) is not None
        )
        target_candidate_ids = [str(item.get("candidateId") or "") for item in target_candidates if str(item.get("candidateId") or "")]
    assessments: list[dict[str, Any]] = []
    failed_candidates: list[dict[str, str]] = []
    for candidate_id in target_candidate_ids:
        try:
            assessment_response = assess_source_candidate_quality(
                normalized_team_id,
                candidate_id,
                {
                    "assessedByAgent": assessed_by_agent,
                    "notes": notes,
                    "evidenceRefs": evidence_refs,
                },
            )
        except (team_service.TeamServiceError, TeamWorkflowOrchestrationError) as exc:
            failed_candidates.append({"candidateId": candidate_id, "error": str(exc)})
            continue
        assessments.append(
            _source_quality_batch_assessment_summary(
                assessment_response.get("candidate", {}),
                assessment_response.get("assessment", {}),
            )
        )
    decision_counts = {
        "approved": sum(1 for item in assessments if item.get("decision") == "approved"),
        "needsRevision": sum(1 for item in assessments if item.get("decision") == "needs_revision"),
        "rejected": sum(1 for item in assessments if item.get("decision") == "rejected"),
    }
    source_quality_status = get_source_quality_status(normalized_team_id)
    with _WORKFLOW_LOCK:
        workflow = _load_or_create_workflow(normalized_team_id)
        candidate_store = _load_candidate_store(normalized_team_id)
    if failed_candidates and not assessments:
        run_status = "failed"
    elif not source_candidates:
        run_status = "no_candidates"
    elif not target_candidate_ids:
        run_status = "no_pending_candidates"
    else:
        run_status = "completed"
    summary = {
        "targetCandidateCount": len(target_candidate_ids),
        "assessedCandidateCount": len(assessments),
        "approvedCandidateCount": decision_counts["approved"],
        "needsRevisionCandidateCount": decision_counts["needsRevision"],
        "rejectedCandidateCount": decision_counts["rejected"],
        "failedCandidateCount": len(failed_candidates),
        "skippedCandidateCount": len(skipped_candidates),
    }
    _record_workflow_event(
        "source_quality.batch_assessed",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "batchRunId": batch_run_id,
            "status": run_status,
            "assessedByAgent": assessed_by_agent,
            **summary,
            "assessedCandidateIds": _workflow_log_sample_values(assessments, "candidateId"),
        },
        child_log_path=f"artifacts/source-quality-{_safe_token(batch_run_id, default='batch', max_length=96)}-batch-assessment.jsonl",
        child_log_payload={
            "kind": "source_quality_batch_assessment",
            "teamId": normalized_team_id,
            "workflowId": workflow["workflowId"],
            "batchRunId": batch_run_id,
            "status": run_status,
            "assessedByAgent": assessed_by_agent,
            "summary": summary,
            "assessments": assessments[:80],
            "skippedCandidates": skipped_candidates[:80],
            "failedCandidates": failed_candidates[:80],
            "truncatedAssessmentCount": max(0, len(assessments) - 80),
            "truncatedSkippedCandidateCount": max(0, len(skipped_candidates) - 80),
            "truncatedFailedCandidateCount": max(0, len(failed_candidates) - 80),
        },
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "workflowId": workflow["workflowId"],
        "batchRunId": batch_run_id,
        "executionMode": "source_quality_agent_batch",
        "status": run_status,
        "assessedByAgent": assessed_by_agent,
        "summary": summary,
        "assessments": assessments,
        "skippedCandidates": skipped_candidates[:24],
        "failedCandidates": failed_candidates[:24],
        "sourceQualityStatus": source_quality_status,
        "workflow": _workflow_to_api(normalized_team_id, workflow, candidate_store),
        "officialBoundary": {
            "writesFormalKnowledge": False,
            "writesRag": False,
            "writesOfficialGraph": False,
            "candidateOnly": True,
        },
        "nextActions": [
            "Review failed or needs_revision candidates before downstream paper_note extraction.",
            "Approved candidates may proceed to candidate-only paper_note planning.",
        ],
        "updatedAt": utc_now_iso(),
    }


def get_source_quality_status(team_id: str) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    team_service.assert_team_exists(normalized_team_id)
    with _WORKFLOW_LOCK:
        workflow = _load_or_create_workflow(normalized_team_id)
        candidate_store = _load_candidate_store(normalized_team_id)
        candidates = [item for item in list(candidate_store.get("candidates") or []) if isinstance(item, dict)]
    source_candidates = [item for item in candidates if str(item.get("candidateType") or "") == "source_manifest"]
    assessed = [item for item in source_candidates if _candidate_source_quality_assessment(item) is not None]
    approved = [item for item in source_candidates if _source_quality_bucket(item) == "approved"]
    needs_revision = [item for item in source_candidates if _source_quality_bucket(item) == "needs_revision"]
    rejected = [item for item in source_candidates if _source_quality_bucket(item) == "rejected"]
    unassessed = [item for item in source_candidates if _source_quality_bucket(item) == "pending"]
    extraction_ready = [item for item in source_candidates if _source_candidate_has_ready_extraction(item)]
    candidate_summaries = [_source_quality_candidate_summary(item) for item in source_candidates]
    action_items = _source_quality_action_items(source_candidates, unassessed, needs_revision)
    status = "empty"
    if source_candidates:
        status = "ready" if approved else "needs_screening"
        if needs_revision or unassessed:
            status = "in_progress" if approved else "needs_screening"
        if len(rejected) == len(source_candidates):
            status = "blocked"
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "workflowId": workflow["workflowId"],
        "workflowKind": workflow["workflowKind"],
        "status": status,
        "summary": {
            "sourceCandidateCount": len(source_candidates),
            "assessedSourceCandidateCount": len(assessed),
            "approvedSourceCandidateCount": len(approved),
            "needsRevisionSourceCandidateCount": len(needs_revision),
            "rejectedSourceCandidateCount": len(rejected),
            "unassessedSourceCandidateCount": len(unassessed),
            "extractionReadySourceCandidateCount": len(extraction_ready),
            "actionItemCount": len(action_items),
        },
        "candidates": sorted(candidate_summaries, key=lambda item: str(item.get("updatedAt") or ""), reverse=True)[:16],
        "actionItems": action_items,
        "screeningContract": {
            "agentRole": "Source Quality Assessment Agent",
            "targetCandidateType": "source_manifest",
            "decisions": sorted(SOURCE_QUALITY_DECISIONS),
            "writesCandidateStore": True,
            "writesFormalKnowledge": False,
            "writesRag": False,
            "writesOfficialGraph": False,
        },
        "officialBoundary": {
            "writesFormalKnowledge": False,
            "writesRag": False,
            "writesOfficialGraph": False,
            "candidateOnly": True,
        },
        "storage": {
            "candidateStorePath": _relative_path(_candidate_store_path(normalized_team_id)),
        },
        "updatedAt": utc_now_iso(),
    }
    _record_workflow_event(
        "source_quality.status_viewed",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "status": status,
            "sourceCandidateCount": len(source_candidates),
            "approvedSourceCandidateCount": len(approved),
            "needsRevisionSourceCandidateCount": len(needs_revision),
            "rejectedSourceCandidateCount": len(rejected),
            "unassessedSourceCandidateCount": len(unassessed),
            "extractionReadySourceCandidateCount": len(extraction_ready),
            "approvedSourceCandidateIds": _workflow_log_sample_values(approved, "candidateId"),
            "needsRevisionSourceCandidateIds": _workflow_log_sample_values(needs_revision, "candidateId"),
            "rejectedSourceCandidateIds": _workflow_log_sample_values(rejected, "candidateId"),
            "unassessedSourceCandidateIds": _workflow_log_sample_values(unassessed, "candidateId"),
            "extractionReadySourceCandidateIds": _workflow_log_sample_values(extraction_ready, "candidateId"),
            "actionItemCodes": _workflow_log_sample_values(action_items, "code"),
        },
    )
    return payload


def get_source_collection_summary(team_id: str, *, run_id: str = "") -> dict[str, Any]:
    """Return the fast first-paint source collection state without heavy repair reads."""

    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    team_service.assert_team_exists(normalized_team_id)
    normalized_run_id = _trim_text(run_id, max_length=160)
    selected_run: dict[str, Any] | None = None
    if normalized_run_id:
        try:
            selected_run = data_processing_service.get_processing_run(normalized_run_id)
        except data_processing_service.DataProcessingError as exc:
            raise TeamWorkflowOrchestrationError(str(exc)) from exc
        if not _source_collection_run_belongs_to_team(selected_run, normalized_team_id):
            raise TeamWorkflowOrchestrationError("Data processing run does not belong to this team.")
    else:
        try:
            runs_payload = data_processing_service.list_processing_runs(
                limit=1,
                metadata_filters={"startedFrom": "team_workflow_source_collection", "teamId": normalized_team_id},
            )
        except data_processing_service.DataProcessingError as exc:
            raise TeamWorkflowOrchestrationError(str(exc)) from exc
        selected_run = next(
            (
                item for item in list(runs_payload.get("runs") or [])
                if isinstance(item, dict) and _source_collection_run_belongs_to_team(item, normalized_team_id)
            ),
            None,
        )
        normalized_run_id = _trim_text((selected_run or {}).get("runId"), max_length=160)
    run_status: dict[str, Any] = {}
    run_summary: dict[str, Any] = {}
    if normalized_run_id:
        try:
            run_status = data_processing_service.get_processing_status(normalized_run_id)
        except data_processing_service.DataProcessingError as exc:
            raise TeamWorkflowOrchestrationError(str(exc)) from exc
        run_summary = run_status.get("summary") if isinstance(run_status.get("summary"), dict) else {}
    projection = _source_collection_stage_cards_projection(normalized_team_id, normalized_run_id) if normalized_run_id else {
        "runId": "",
        "cards": [],
        "latestTasks": {},
        "summary": {"closedLoopCount": 0, "stageCount": 0},
    }
    projection_summary = projection.get("summary") if isinstance(projection.get("summary"), dict) else {}
    stage_round_ref = _source_collection_stage_round_ref_for_run(normalized_team_id, normalized_run_id) if normalized_run_id else {}
    active_snapshot = _source_collection_work_run_store().load_active_snapshot(SOURCE_COLLECTION_WORK_RUN_KIND) if normalized_run_id else {}
    active_work_run = (
        active_snapshot
        if _source_collection_background_snapshot_is_active(active_snapshot, normalized_team_id, normalized_run_id)
        else {}
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "runId": normalized_run_id,
        "status": "active" if normalized_run_id and str(run_status.get("runStatus") or "").lower() in {"collecting", "processing"} else ("ready" if normalized_run_id else "idle"),
        "run": selected_run or {},
        "runStatus": run_status,
        "summary": {
            "recordCount": _source_collection_count(run_summary.get("recordCount")),
            "assignmentCount": _source_collection_count(run_summary.get("assignmentCount")),
            "openAssignmentCount": _source_collection_count(run_summary.get("openAssignmentCount")),
            "outputCount": _source_collection_count(run_summary.get("outputCount")),
            "sourceCandidateCount": _source_collection_count(projection_summary.get("sourceCandidateCount")),
            "assessedSourceCandidateCount": _source_collection_count(projection_summary.get("assessedSourceCandidateCount")),
            "approvedSourceCandidateCount": _source_collection_count(projection_summary.get("approvedSourceCandidateCount")),
            "graphNodeCount": _source_collection_count(projection_summary.get("graphNodeCount")),
            "stewardPackCount": _source_collection_count(projection_summary.get("stewardPackCount")),
            "formalKnowledgeSyncCount": _source_collection_count(projection_summary.get("formalKnowledgeSyncCount")),
        },
        "stageCards": projection.get("cards", []),
        "stageCardSummary": projection_summary,
        "latestTasks": projection.get("latestTasks", {}),
        "stageRound": stage_round_ref,
        "activeWorkRun": active_work_run,
        "storageArtifacts": _source_collection_storage_artifacts(normalized_team_id, normalized_run_id) if normalized_run_id else {},
        "boundaries": _research_stage_boundaries(),
        "updatedAt": utc_now_iso(),
    }


def list_candidate_store(
    team_id: str,
    *,
    candidate_type: str = "",
    current_state: str = "",
    quality_status: str = "",
    limit: int = 100,
    include_validation: bool = False,
) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    team_service.assert_team_exists(normalized_team_id)
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
        all_candidates = [item for item in list(candidate_store.get("candidates") or []) if isinstance(item, dict)]
    if include_validation:
        validation_summary = validate_candidate_store(normalized_team_id)["summary"]
    else:
        validation_summary = {
            "candidateCount": len(all_candidates),
            "validCandidateCount": 0,
            "invalidCandidateCount": 0,
            "errorCount": 0,
            "warningCount": 0,
            "skipped": True,
            "reason": "not_requested",
        }
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
        "validationSummary": validation_summary,
    }


def validate_candidate_store(team_id: str) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    team_service.assert_team_exists(normalized_team_id)
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
    invalid_reports = [item for item in candidate_reports if not item["validation"]["valid"]]
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
            "invalidCandidateIds": _workflow_log_sample_values(invalid_reports, "candidateId"),
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
    team_service.assert_team_exists(normalized_team_id)
    ingestion_store = _knowledge_ingestion_work_run_store()
    ingestion_active_snapshot = ingestion_store.load_active_snapshot(KNOWLEDGE_INGESTION_WORK_RUN_KIND)
    if not _knowledge_ingestion_snapshot_is_active(ingestion_active_snapshot, normalized_team_id):
        ingestion_active_snapshot = None
    ingestion_latest_snapshot = ingestion_store.load_latest_snapshot(KNOWLEDGE_INGESTION_WORK_RUN_KIND)
    if isinstance(ingestion_latest_snapshot, dict) and _trim_text(ingestion_latest_snapshot.get("teamId"), max_length=160) != normalized_team_id:
        ingestion_latest_snapshot = None
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
        graph_candidates = [
            item
            for item in candidates
            if str(item.get("candidateType") or "") == "candidate_graph" and not _candidate_is_archived(item)
        ]
        latest_graph = _latest_candidate_record(graph_candidates)
        latest_graph_metadata = latest_graph.get("metadata") if isinstance((latest_graph or {}).get("metadata"), dict) else {}
        candidate_graph = latest_graph_metadata.get("graph") if isinstance(latest_graph_metadata.get("graph"), dict) else _build_candidate_graph_payload(normalized_team_id, workflow["workflowId"], active_graph_candidates)
        candidate_graph["summary"]["archivedCandidateCount"] = len(archived_candidates)

    try:
        knowledge_overview = team_knowledge_service.list_team_knowledge_bases(normalized_team_id, internal=True)
    except (team_knowledge_service.TeamKnowledgeError, team_knowledge_service.TeamKnowledgeNotFoundError) as exc:
        raise TeamWorkflowOrchestrationError(str(exc)) from exc

    candidate_summary = _knowledge_ingestion_candidate_summary(candidates, candidate_reports, candidate_graph)
    knowledge_summary = _knowledge_ingestion_knowledge_summary(knowledge_overview)
    stages = _knowledge_ingestion_stages(candidate_summary, knowledge_summary)
    action_items = _knowledge_ingestion_action_items(candidates, candidate_reports, candidate_graph, candidate_summary, knowledge_summary)
    overall_status = _knowledge_ingestion_overall_status(stages, action_items, candidate_summary, knowledge_summary)
    non_graph_candidates = [item for item in candidates if str(item.get("candidateType") or "") != "candidate_graph"]
    pending_source_review_candidates = [
        item for item in non_graph_candidates if _candidate_knowledge_ingestion_status(item) == "pending_source_review"
    ]
    pending_knowledge_review_candidates = [
        item for item in non_graph_candidates if _candidate_knowledge_ingestion_status(item) == "pending_review"
    ]
    steward_candidates = [
        item
        for item in non_graph_candidates
        if str(item.get("currentWorkflowNode") or "") == "steward_ingestion"
        or str((item.get("metadata") if isinstance(item.get("metadata"), dict) else {}).get("taskType") or "") == "steward_pack_draft"
    ]
    invalid_candidate_reports = [item for item in candidate_reports if not bool((item.get("validation") or {}).get("valid"))]
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
        "activeWorkRun": ingestion_active_snapshot,
        "latestWorkRun": ingestion_latest_snapshot,
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
            "candidateBreakdown": _candidate_breakdown(candidates),
            "pendingSourceReviewCandidateIds": _workflow_log_sample_values(pending_source_review_candidates, "candidateId"),
            "pendingKnowledgeReviewCandidateIds": _workflow_log_sample_values(pending_knowledge_review_candidates, "candidateId"),
            "stewardCandidateIds": _workflow_log_sample_values(steward_candidates, "candidateId"),
            "invalidCandidateIds": _workflow_log_sample_values(invalid_candidate_reports, "candidateId"),
            "actionItemCodes": _workflow_log_sample_values(action_items, "code"),
        },
    )
    return payload


def get_official_model_evidence_status(team_id: str) -> dict[str, Any]:
    """Return a read-only model-call evidence coverage view for the research workflow."""

    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    team_service.get_team(normalized_team_id)
    with _WORKFLOW_LOCK:
        workflow = _load_or_create_workflow(normalized_team_id)
        evidence_store = _load_official_model_evidence_store(normalized_team_id)
        candidate_store = _load_candidate_store(normalized_team_id)
        stored_evidence = _official_model_evidence_entries(evidence_store)
        candidate_evidence = _official_model_evidence_from_candidates(candidate_store, workflow)
    evidence = _dedupe_official_model_evidence([*stored_evidence, *candidate_evidence])
    coverage = _official_model_evidence_coverage(evidence)
    missing_nodes = [item for item in coverage if item["status"] == "missing"]
    provider_counts = _count_by_field(evidence, "modelProvider")
    evidence_kind_counts = _count_by_field(evidence, "evidenceKind")
    linked_candidate_count = len({str(item.get("candidateId") or "") for item in evidence if item.get("candidateId")})
    linked_stage_count = len({str(item.get("stageRoundId") or "") for item in evidence if item.get("stageRoundId")})
    summary = {
        "evidenceCount": len(evidence),
        "storedEvidenceCount": len(stored_evidence),
        "candidateOutputEvidenceCount": len(candidate_evidence),
        "requiredNodeCount": len(OFFICIAL_MODEL_EVIDENCE_REQUIRED_TASKS),
        "coveredNodeCount": len(coverage) - len(missing_nodes),
        "missingNodeCount": len(missing_nodes),
        "qwenEvidenceCount": sum(
            count for provider, count in provider_counts.items() if "qwen" in provider.lower() or provider.lower() in {"dashscope", "bailian"}
        ),
        "bailianEvidenceCount": sum(count for provider, count in provider_counts.items() if "bailian" in provider.lower() or "百炼" in provider),
        "localEvidenceCount": sum(count for provider, count in provider_counts.items() if provider.lower().startswith("local")),
        "linkedCandidateCount": linked_candidate_count,
        "linkedStageRoundCount": linked_stage_count,
    }
    status = "empty" if not evidence else ("ready" if not missing_nodes else "needs_evidence")
    action_items = _official_model_evidence_action_items(missing_nodes, summary)
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "workflowId": workflow["workflowId"],
        "workflowKind": workflow["workflowKind"],
        "status": status,
        "summary": {**summary, "actionItemCount": len(action_items)},
        "coverage": coverage,
        "providerCounts": provider_counts,
        "evidenceKindCounts": evidence_kind_counts,
        "recentEvidence": sorted(evidence, key=lambda item: str(item.get("createdAt") or ""), reverse=True)[:12],
        "actionItems": action_items,
        "officialBoundary": _official_model_evidence_boundary(),
        "storage": {
            "workflowPath": _relative_path(_workflow_path(normalized_team_id)),
            "candidateStorePath": _relative_path(_candidate_store_path(normalized_team_id)),
            "evidenceStorePath": _relative_path(_official_model_evidence_store_path(normalized_team_id)),
        },
        "updatedAt": utc_now_iso(),
    }
    _record_workflow_event(
        "official_model_evidence.status_viewed",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "status": status,
            "evidenceCount": summary["evidenceCount"],
            "coveredNodeCount": summary["coveredNodeCount"],
            "missingNodeCount": summary["missingNodeCount"],
            "actionItemCount": len(action_items),
            "missingWorkflowNodes": _workflow_log_sample_values(missing_nodes, "workflowNode"),
            "missingTaskTypes": _workflow_log_sample_values(missing_nodes, "taskType"),
            "modelProviderCounts": _workflow_log_count_sample(provider_counts),
            "evidenceKindCounts": _workflow_log_count_sample(evidence_kind_counts),
            "actionItemCodes": _workflow_log_sample_values(action_items, "code"),
        },
    )
    return payload


def register_official_model_evidence(team_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Register a model-call evidence record without promoting it to formal knowledge."""

    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    team_service.get_team(normalized_team_id)
    request_payload = dict(payload) if isinstance(payload, dict) else {}
    with _WORKFLOW_LOCK:
        workflow = _load_or_create_workflow(normalized_team_id)
        candidate_store = _load_candidate_store(normalized_team_id)
        evidence_store = _load_official_model_evidence_store(normalized_team_id)
        evidence = _build_official_model_evidence_record(
            normalized_team_id,
            workflow,
            candidate_store,
            request_payload,
        )
        evidence_store.setdefault("evidence", []).append(evidence)
        evidence_store["updatedAt"] = evidence["createdAt"]
        _write_json(_official_model_evidence_store_path(normalized_team_id), evidence_store)
    _record_workflow_event(
        "official_model_evidence.recorded",
        normalized_team_id,
        fields={
            "workflowId": workflow["workflowId"],
            "evidenceId": evidence["evidenceId"],
            "taskType": evidence["taskType"],
            "workflowNode": evidence["workflowNode"],
            "modelProvider": evidence["modelProvider"],
            "evidenceKind": evidence["evidenceKind"],
            "candidateId": evidence.get("candidateId", ""),
        },
    )
    return {
        "evidence": evidence,
        "status": get_official_model_evidence_status(normalized_team_id),
    }


def get_team_workflow_coordination_status(team_id: str) -> dict[str, Any]:
    """Return a read-only coordination queue for the Challenge Cup research workflow."""

    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    team_service.assert_team_exists(normalized_team_id)
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
        "communication": _coordination_communication_summary(summary, queues),
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
            "communicationBriefCount": summary["communicationBriefCount"],
            "pendingTransferCandidateIds": _workflow_log_queue_candidate_ids(queues, "pendingTransfers"),
            "reworkCandidateIds": _workflow_log_queue_candidate_ids(queues, "needsRework"),
            "stewardshipCandidateIds": _workflow_log_queue_candidate_ids(queues, "stewardship"),
            "blockedCandidateIds": _workflow_log_queue_candidate_ids(queues, "blocked"),
            "activeCandidateIds": _workflow_log_queue_candidate_ids(queues, "active"),
            "actionItemCodes": _workflow_log_sample_values(action_items, "code"),
        },
    )
    return payload


def build_candidate_graph(team_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    team_service.get_team(normalized_team_id)
    payload = payload if isinstance(payload, dict) else {}
    curation_mode = _trim_text(payload.get("curationMode"), max_length=80) or "all_active"
    created_by_agent = _trim_text(payload.get("createdByAgent"), max_length=160) or "Candidate Graph Preview Agent"
    source_quality_agent_id = _trim_text(payload.get("sourceQualityAgentId"), max_length=160) or "Source Quality Assessment Agent"
    source_collection_run_id = _trim_text(payload.get("sourceCollectionRunId") or payload.get("runId"), max_length=160)
    force_rebuild = bool(payload.get("forceRebuild"))
    if bool(payload.get("forceReview")):
        assess_source_quality_batch(
            normalized_team_id,
            {
                "assessedByAgent": source_quality_agent_id,
                "maxCandidates": _normalize_int(payload.get("maxCandidates"), default=80, minimum=1, maximum=200),
                "force": True,
                "notes": "Candidate Graph Agent requested source review before graph generation.",
            },
        )
    now = utc_now_iso()
    with _WORKFLOW_LOCK:
        workflow = _load_or_create_workflow(normalized_team_id)
        candidate_store = _load_candidate_store(normalized_team_id)
        all_candidates = [
            item
            for item in list(candidate_store.get("candidates") or [])
            if isinstance(item, dict) and _candidate_allowed_for_agent_graph_input(item)
        ]
        if source_collection_run_id:
            all_candidates = [
                item
                for item in all_candidates
                if _source_collection_candidate_trace_run_id(item) == source_collection_run_id
            ]
        archived_candidates = [item for item in all_candidates if _candidate_is_archived(item)]
        active_candidates = [item for item in all_candidates if not _candidate_is_archived(item)]
        filtered_candidates: list[dict[str, Any]] = []
        if curation_mode == "agent_approved_only":
            candidates = [item for item in active_candidates if _candidate_ready_for_agent_graph(item)]
            filtered_candidates = [item for item in active_candidates if item not in candidates]
        else:
            candidates = active_candidates
        graph_fingerprint = _knowledge_collection_fingerprint(
            normalized_team_id,
            candidates,
            purpose="candidate_graph",
            curation_mode=curation_mode,
        )
        if not force_rebuild:
            reusable_graph = _find_reusable_candidate_graph(candidate_store, graph_fingerprint)
            if reusable_graph is not None:
                metadata = reusable_graph.get("metadata") if isinstance(reusable_graph.get("metadata"), dict) else {}
                graph = metadata.get("graph") if isinstance(metadata.get("graph"), dict) else _build_candidate_graph_payload(normalized_team_id, workflow["workflowId"], candidates)
                graph.setdefault("summary", {})
                graph["summary"]["archivedCandidateCount"] = len(archived_candidates)
                graph["summary"]["curationMode"] = curation_mode
                graph["summary"]["inputCandidateCount"] = len(active_candidates)
                graph["summary"]["filteredCandidateCount"] = len(filtered_candidates)
                graph["summary"]["createdByAgent"] = created_by_agent
                graph["summary"]["stageAgentRole"] = "candidate_graph"
                if source_collection_run_id:
                    graph["summary"]["sourceCollectionRunId"] = source_collection_run_id
                _record_workflow_event(
                    "candidate_graph.reused",
                    normalized_team_id,
                    fields={
                        "workflowId": workflow["workflowId"],
                        "candidateId": str(reusable_graph.get("candidateId") or ""),
                        "nodeCount": len(graph.get("nodes") or []),
                        "edgeCount": len(graph.get("edges") or []),
                        "missingLinkCount": len(graph.get("missingLinks") or []),
                        "unreviewedNodeCount": len(graph.get("unreviewedNodes") or []),
                        "archivedCandidateCount": len(archived_candidates),
                        "filteredCandidateCount": len(filtered_candidates),
                        "curationMode": curation_mode,
                        "sourceCollectionRunId": source_collection_run_id,
                        "createdByAgent": created_by_agent,
                        "ingestionFingerprint": graph_fingerprint,
                    },
                )
                return {
                    "candidateGraph": reusable_graph,
                    "graph": graph,
                    "workflow": _workflow_to_api(normalized_team_id, workflow, candidate_store),
                    "reusedCandidateGraph": True,
                    "ingestionFingerprint": graph_fingerprint,
                }
        graph = _build_candidate_graph_payload(normalized_team_id, workflow["workflowId"], candidates)
        graph["summary"]["archivedCandidateCount"] = len(archived_candidates)
        graph["summary"]["curationMode"] = curation_mode
        graph["summary"]["inputCandidateCount"] = len(active_candidates)
        graph["summary"]["filteredCandidateCount"] = len(filtered_candidates)
        graph["summary"]["createdByAgent"] = created_by_agent
        graph["summary"]["stageAgentRole"] = "candidate_graph"
        if source_collection_run_id:
            graph["summary"]["sourceCollectionRunId"] = source_collection_run_id
        graph["summary"]["ingestionFingerprint"] = graph_fingerprint
        agent_process = [
            {
                "eventType": "candidate_graph.input_selected",
                "stage": "candidate_graph",
                "agentRole": "candidate_graph",
                "agentId": created_by_agent,
                "status": "completed",
                "inputSummary": f"{len(active_candidates)} active candidates, {len(candidates)} selected",
                "outputSummary": f"{len(filtered_candidates)} candidates filtered before graph preview",
                "nextAction": "build_candidate_graph_snapshot",
                "candidateIds": [str(item.get("candidateId") or "") for item in candidates[:64]],
            },
            {
                "eventType": "candidate_graph.snapshot_built",
                "stage": "candidate_graph",
                "agentRole": "candidate_graph",
                "agentId": created_by_agent,
                "status": "completed" if not graph["missingLinks"] else "needs_attention",
                "inputSummary": f"{len(candidates)} selected candidates",
                "outputSummary": f"{len(graph['nodes'])} nodes / {len(graph['edges'])} edges",
                "nextAction": "knowledge_ingestion_precheck" if not graph["missingLinks"] else "repair_candidate_graph_links",
                "candidateGraphBoundary": "candidate_only",
            },
        ]
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
                f"{len(graph['missingLinks'])} missing links, {len(archived_candidates)} archived, "
                f"{len(filtered_candidates)} filtered"
            ),
            "sourceRefs": [],
            "evidenceRefs": [],
            "metadata": {
                "generatedFromCandidateIds": [node["candidateId"] for node in graph["nodes"]],
                "curationMode": curation_mode,
                "filteredCandidateIds": [str(item.get("candidateId") or "") for item in filtered_candidates],
                "graph": graph,
                "agentProcess": agent_process,
                "workflowStage": "candidate_graph",
                "stageAgentRole": "candidate_graph",
                "missingLinkCount": len(graph["missingLinks"]),
                "unreviewedNodeCount": len(graph["unreviewedNodes"]),
                "officialBoundary": graph["officialBoundary"],
                "knowledgeCollectionIngestion": {
                    "fingerprint": graph_fingerprint,
                    "purpose": "candidate_graph",
                    "inputCandidateIds": [str(item.get("candidateId") or "") for item in candidates],
                    "sourceCollectionRunId": source_collection_run_id,
                },
            },
            "createdByAgent": created_by_agent,
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
            "filteredCandidateCount": len(filtered_candidates),
            "curationMode": curation_mode,
            "sourceCollectionRunId": source_collection_run_id,
            "createdByAgent": created_by_agent,
            "ingestionFingerprint": graph_fingerprint,
        },
    )
    return {
        "candidateGraph": record,
        "graph": graph,
        "workflow": _workflow_to_api(normalized_team_id, workflow, candidate_store),
        "reusedCandidateGraph": False,
        "ingestionFingerprint": graph_fingerprint,
    }


def run_knowledge_ingestion_precheck(team_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Generate a candidate-only steward precheck pack from approved workflow candidates."""

    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    team_service.get_team(normalized_team_id)
    payload = payload if isinstance(payload, dict) else {}
    # 默认必须是团队成员 agentId（而非显示名），否则建库/审核的成员校验会失败。
    steward_agent_id = _trim_text(payload.get("stewardAgentId"), max_length=160) or agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID
    target_domain = _trim_text(payload.get("targetDomain"), max_length=240) or "神经机制启发神经网络算法"
    max_candidates = _normalize_int(payload.get("maxCandidates"), default=32, minimum=1, maximum=200)
    force_rebuild = bool(payload.get("forceRebuild"))
    with _WORKFLOW_LOCK:
        workflow = _load_or_create_workflow(normalized_team_id)
        candidate_store = _load_candidate_store(normalized_team_id)
        stored_candidates = [item for item in list(candidate_store.get("candidates") or []) if isinstance(item, dict)]
        active_candidates = [
            item
            for item in stored_candidates
            if str(item.get("candidateType") or "") != "candidate_graph" and not _candidate_is_archived(item)
        ]
        graph_candidates = [
            item
            for item in stored_candidates
            if str(item.get("candidateType") or "") == "candidate_graph" and not _candidate_is_archived(item)
        ]
        latest_graph = _latest_candidate_record(graph_candidates)
        selected_candidates = _dedupe_candidate_sequence(
            [
                *[item for item in active_candidates if str(item.get("candidateType") or "") != "source_manifest" and _candidate_ready_for_agent_graph(item)],
                *[item for item in active_candidates if str(item.get("candidateType") or "") == "source_manifest" and _source_quality_bucket(item) == "approved"],
            ]
        )[:max_candidates]
        workflow_id = str(workflow.get("workflowId") or "")
        filtered_candidate_count = max(0, len(active_candidates) - len(selected_candidates))
        precheck_fingerprint = _knowledge_collection_fingerprint(
            normalized_team_id,
            selected_candidates,
            purpose="steward_pack",
            target_domain=target_domain,
            steward_agent_id=steward_agent_id,
            candidate_graph_id=str((latest_graph or {}).get("candidateId") or ""),
        )
        if not force_rebuild:
            reusable_pack = _find_reusable_steward_pack(candidate_store, precheck_fingerprint)
            if reusable_pack is not None:
                status_payload = get_knowledge_ingestion_status(normalized_team_id)
                _record_workflow_event(
                    "knowledge_ingestion.precheck_reused",
                    normalized_team_id,
                    fields={
                        "workflowId": workflow_id,
                        "candidateId": str(reusable_pack.get("candidateId") or ""),
                        "selectedCandidateCount": len(selected_candidates),
                        "filteredCandidateCount": filtered_candidate_count,
                        "stewardAgentId": steward_agent_id,
                        "candidateGraphId": str((latest_graph or {}).get("candidateId") or ""),
                        "ingestionFingerprint": precheck_fingerprint,
                    },
                )
                return {
                    "candidate": reusable_pack,
                    "validation": validate_candidate_record(reusable_pack),
                    "precheck": {
                        "status": str(reusable_pack.get("currentState") or "steward_pack_draft"),
                        "generatedByAgent": steward_agent_id,
                        "selectedCandidateCount": len(selected_candidates),
                        "filteredCandidateCount": filtered_candidate_count,
                        "candidateIds": [str(item.get("candidateId") or "") for item in selected_candidates],
                        "candidateGraphId": str((latest_graph or {}).get("candidateId") or ""),
                        "officialBoundary": {
                            "writesOfficialKnowledge": False,
                            "writesOfficialRag": False,
                            "writesOfficialGraph": False,
                            "requiresReviewBeforeOfficialSync": True,
                        },
                    },
                    "status": status_payload,
                    "workflow": _workflow_to_api(normalized_team_id, workflow, candidate_store),
                    "reusedStewardPack": True,
                    "ingestionFingerprint": precheck_fingerprint,
                }
    if not selected_candidates:
        raise TeamWorkflowOrchestrationError("No agent-approved candidates are ready for knowledge ingestion precheck.")

    output = _build_knowledge_ingestion_precheck_output(
        normalized_team_id,
        workflow_id,
        selected_candidates,
        latest_graph,
        target_domain=target_domain,
    )
    output["knowledgeCollectionIngestion"] = {
        "fingerprint": precheck_fingerprint,
        "purpose": "steward_pack",
        "candidateGraphId": str((latest_graph or {}).get("candidateId") or ""),
    }
    output["agentProcess"] = [
        {
            "eventType": "knowledge_ingestion.precheck_input_selected",
            "stage": "memory_precheck",
            "agentRole": "knowledge_steward",
            "agentId": steward_agent_id,
            "status": "completed",
            "inputSummary": f"{len(selected_candidates)} approved candidates selected",
            "outputSummary": "candidate-only steward precheck package",
            "nextAction": "submit_steward_pack_to_knowledge_ingestion_after_gate",
            "candidateGraphId": str((latest_graph or {}).get("candidateId") or ""),
        }
    ]
    record_response = record_local_research_model_output(
        normalized_team_id,
        {
            "taskType": "steward_pack_draft",
            "title": "资料入库包",
            "summary": f"由 {steward_agent_id} 汇总 {len(selected_candidates)} 条通过资料，生成团队知识库入库包。",
            "createdByAgent": steward_agent_id,
            "output": output,
        },
    )
    status_payload = get_knowledge_ingestion_status(normalized_team_id)
    _record_workflow_event(
        "knowledge_ingestion.precheck_generated",
        normalized_team_id,
        fields={
            "workflowId": workflow_id,
            "candidateId": record_response["candidate"]["candidateId"],
            "selectedCandidateCount": len(selected_candidates),
            "filteredCandidateCount": filtered_candidate_count,
            "stewardAgentId": steward_agent_id,
            "candidateGraphId": str((latest_graph or {}).get("candidateId") or ""),
            "writesOfficialKnowledge": False,
            "writesOfficialRag": False,
            "writesOfficialGraph": False,
        },
    )
    return {
        "candidate": record_response["candidate"],
        "validation": record_response["validation"],
        "precheck": {
            "status": "steward_pack_draft",
            "generatedByAgent": steward_agent_id,
            "selectedCandidateCount": len(selected_candidates),
            "filteredCandidateCount": filtered_candidate_count,
            "candidateIds": [str(item.get("candidateId") or "") for item in selected_candidates],
            "candidateGraphId": str((latest_graph or {}).get("candidateId") or ""),
            "officialBoundary": {
                "writesOfficialKnowledge": False,
                "writesOfficialRag": False,
                "writesOfficialGraph": False,
                "requiresReviewBeforeOfficialSync": True,
            },
        },
        "status": status_payload,
        "workflow": record_response["workflow"],
        "reusedStewardPack": False,
        "ingestionFingerprint": precheck_fingerprint,
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
        message = invoke_llm(
            client,
            messages,
            context=LLMInvocationContext(
                surface="team_workflow_local_research_model",
                run_kind="challenge_cup_local_research",
                run_id=str(task["taskId"]),
                session_id=normalized_team_id,
                agent_id="local_research_model",
                llm_slot="dialogue",
                model_id=model_id,
                cache_scope=SOURCE_COLLECTION_PROMPT_CACHE_SCOPE,
                cache_partition=_source_collection_prompt_cache_partition(
                    normalized_team_id,
                    "local_research_model",
                    model_id=model_id,
                ),
                prompt_purpose=str(task["taskType"] or "local_research"),
                conversation_bound=False,
            ),
            metadata=metadata,
        )
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
        "modelProfileId": LOCAL_RESEARCH_INVOKE_PROFILE_ID,
        "modelId": model_id,
    }
    try:
        evidence_response = register_official_model_evidence(
            normalized_team_id,
            {
                "taskType": task["taskType"],
                "workflowNode": task["workflowNode"],
                "candidateId": record_response["candidate"]["candidateId"],
                "taskId": task["taskId"],
                "modelProvider": "local_qwen",
                "modelId": model_id,
                "modelName": task["model"]["name"],
                "modelProfileId": LOCAL_RESEARCH_INVOKE_PROFILE_ID,
                "evidenceKind": "invocation_log",
                "logRef": "runtime_scene_event:local_model.invoke_recorded",
                "promptSummary": f"{task['taskType']} task with {len(task['sourceRefs'])} sourceRefs, {len(task['evidenceRefs'])} evidenceRefs, {len(task['candidateRefs'])} candidateRefs.",
                "outputSummary": record_response["candidate"].get("summary", ""),
                "sourceRefs": task["sourceRefs"],
                "evidenceRefs": task["evidenceRefs"],
                "recordedByAgent": payload.get("createdByAgent") or "",
                "metadata": {
                    "contentChars": len(raw_content),
                    "reasoningChars": len(reasoning_content),
                    "jsonSource": parse_source,
                    "autoRecordedFromInvoke": True,
                },
            },
        )
        record_response["modelEvidence"] = evidence_response["evidence"]
    except TeamWorkflowOrchestrationError as exc:
        record_response["modelEvidence"] = {
            "status": "not_recorded",
            "reason": _trim_text(str(exc), max_length=500),
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
    central_source_id = _trim_text(payload.get("centralSourceId"), max_length=160)

    with _WORKFLOW_LOCK:
        workflow = _load_or_create_workflow(normalized_team_id)
        candidate_store = _load_candidate_store(normalized_team_id)
        candidate = _find_candidate(candidate_store, normalized_candidate_id)
        if candidate is None:
            raise TeamWorkflowOrchestrationError("Steward pack candidate not found.")
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        task_type = str(metadata.get("taskType") or "")
        output = metadata.get("output") if isinstance(metadata.get("output"), dict) else {}
        current_state = str(candidate.get("currentState") or "")
        if task_type != "steward_pack_draft" or current_state not in {"steward_pack_draft", "steward_pending_source_review"}:
            raise TeamWorkflowOrchestrationError("Only steward_pack_draft or steward_pending_source_review candidates can be submitted to knowledge ingestion.")
        if current_state == "steward_pending_source_review" and not central_source_id:
            raise TeamWorkflowOrchestrationError("centralSourceId is required after the steward pack source has entered source review.")
        validation = validate_local_research_model_output("steward_pack_draft", output)
        if not validation["valid"]:
            raise TeamWorkflowOrchestrationError("Steward pack candidate must be valid before knowledge ingestion submission.")

    ingestion_payload = _steward_pack_ingestion_payload(
        normalized_team_id,
        candidate,
        output,
        proposed_by_agent_id=proposed_by_agent_id,
    )

    if not central_source_id:
        try:
            inbox_source = team_knowledge_service.collect_source_to_inbox(
                "team",
                normalized_team_id,
                source_type="agent_authored",
                source_ref=ingestion_payload["sourceRef"],
                original_content=ingestion_payload["proposalContent"],
                original_filename=f"steward-pack-{_safe_token(normalized_candidate_id, default='candidate', max_length=72)}.json",
                source_created_at=str(candidate.get("createdAt") or ""),
                captured_by=proposed_by_agent_id,
                evidence_range=ingestion_payload["evidenceRange"],
                title=ingestion_payload["sourceTitle"],
                summary=ingestion_payload["sourceSummary"],
                actor_agent_id=proposed_by_agent_id,
            )
        except (team_knowledge_service.TeamKnowledgeError, team_knowledge_service.TeamKnowledgeNotFoundError) as exc:
            raise TeamWorkflowOrchestrationError(str(exc)) from exc

        now = utc_now_iso()
        with _WORKFLOW_LOCK:
            workflow = _load_or_create_workflow(normalized_team_id)
            candidate_store = _load_candidate_store(normalized_team_id)
            candidate = _find_candidate(candidate_store, normalized_candidate_id)
            if candidate is None:
                raise TeamWorkflowOrchestrationError("Steward pack candidate not found after source inbox submission.")
            metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
            metadata["knowledgeIngestion"] = {
                "status": "pending_source_review",
                "knowledgeBaseId": knowledge_base_id,
                "inboxSourceId": str(inbox_source.get("inboxSourceId") or ""),
                "centralSourceId": "",
                "sourceArtifactId": "",
                "proposalId": "",
                "ratingSuggestionId": "",
                "submittedByAgentId": proposed_by_agent_id,
                "submittedAt": now,
                "writesOfficialKnowledge": False,
                "writesOfficialRag": False,
                "writesOfficialGraph": False,
            }
            candidate["metadata"] = metadata
            candidate["currentState"] = "steward_pending_source_review"
            candidate["qualityStatus"] = "pending_source_review"
            candidate["updatedAt"] = now
            candidate_store["updatedAt"] = now
            _write_json(_candidate_store_path(normalized_team_id), candidate_store)
            workflow["updatedAt"] = now
            workflow["activeWorkflowItems"] = _upsert_active_item(
                workflow.get("activeWorkflowItems"),
                candidate_id=normalized_candidate_id,
                current_node=str(candidate.get("currentWorkflowNode") or "steward_ingestion"),
                status=str(candidate.get("currentState") or "steward_pending_source_review"),
                transfer_id="",
            )
            _write_json(_workflow_path(normalized_team_id), workflow)

        _record_workflow_event(
            "steward_pack.source_inbox_submitted",
            normalized_team_id,
            fields={
                "workflowId": workflow["workflowId"],
                "candidateId": normalized_candidate_id,
                "knowledgeBaseId": knowledge_base_id,
                "inboxSourceId": str(inbox_source.get("inboxSourceId") or ""),
            },
        )
        return {
            "candidate": candidate,
            "knowledgeIngestion": {
                "status": "pending_source_review",
                "sourceInbox": inbox_source,
                "officialBoundary": {
                    "writesOfficialKnowledge": False,
                    "writesOfficialRag": False,
                    "writesOfficialGraph": False,
                },
            },
            "workflow": _workflow_to_api(normalized_team_id, workflow, candidate_store),
        }

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
            central_source_id=central_source_id,
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
        previous_ingestion = metadata.get("knowledgeIngestion") if isinstance(metadata.get("knowledgeIngestion"), dict) else {}
        metadata["knowledgeIngestion"] = {
            "status": "pending_review",
            "knowledgeBaseId": knowledge_base_id,
            "inboxSourceId": str(previous_ingestion.get("inboxSourceId") or ""),
            "centralSourceId": central_source_id,
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
            "centralSourceId": central_source_id,
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


def _team_workflow_kernel_delivery(kernel_result: dict[str, Any], target_agent_id: str) -> dict[str, Any]:
    outcome = kernel_result.get("outcome") if isinstance(kernel_result.get("outcome"), dict) else {}
    deliveries = outcome.get("deliveries") if isinstance(outcome.get("deliveries"), list) else []
    normalized_target_agent_id = str(target_agent_id or "").strip()
    for delivery in deliveries:
        if not isinstance(delivery, dict):
            continue
        if str(delivery.get("targetAgentId") or "").strip() == normalized_target_agent_id:
            return dict(delivery)
    return dict(deliveries[0]) if deliveries and isinstance(deliveries[0], dict) else {}


def _team_workflow_inbox_message_from_kernel_delivery(
    target_agent_id: str,
    delivery: dict[str, Any],
    *,
    fallback: dict[str, Any],
) -> dict[str, Any]:
    message_id = str(
        delivery.get("inboxMessageId")
        or (delivery.get("wake", {}) if isinstance(delivery.get("wake"), dict) else {}).get("messageId")
        or ""
    ).strip()
    if message_id:
        for message in agent_directory_service.list_agent_inbox_messages_for_agent(
            target_agent_id,
            limit=100,
            status="",
        ):
            if str(message.get("messageId") or message.get("eventId") or "").strip() == message_id:
                return message
    message = dict(fallback)
    if message_id:
        message["messageId"] = message_id
        message.setdefault("eventId", message_id)
    message["targetAgentId"] = str(target_agent_id or "").strip()
    message["targetSessionId"] = str(
        delivery.get("targetSessionId")
        or (delivery.get("wake", {}) if isinstance(delivery.get("wake"), dict) else {}).get("targetSessionId")
        or ""
    ).strip()
    return message


def _team_workflow_kernel_summary(kernel_result: dict[str, Any]) -> dict[str, Any]:
    event = kernel_result.get("event") if isinstance(kernel_result.get("event"), dict) else {}
    task = kernel_result.get("task") if isinstance(kernel_result.get("task"), dict) else {}
    execution = kernel_result.get("execution") if isinstance(kernel_result.get("execution"), dict) else {}
    outcome = kernel_result.get("outcome") if isinstance(kernel_result.get("outcome"), dict) else {}
    adapter = kernel_result.get("adapter") if isinstance(kernel_result.get("adapter"), dict) else {}
    return {
        "eventId": str(adapter.get("eventId") or event.get("eventId") or "").strip(),
        "taskId": str(task.get("taskId") or "").strip(),
        "workRunId": str(execution.get("workRunId") or "").strip(),
        "outcomeId": str(outcome.get("outcomeId") or "").strip(),
        "outcomeStatus": str(outcome.get("status") or "").strip(),
        "adapterVersion": str(adapter.get("adapterVersion") or "").strip(),
        "reused": bool(kernel_result.get("reused", False)),
    }


def _submit_team_workflow_inbox_via_kernel(
    *,
    target_agent_id: str,
    content: str,
    source_agent_id: str,
    thread_id: str,
    kind: str,
    summary: str,
    created_by: str,
    metadata: dict[str, Any],
    wake_target: bool,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    from core.agent_kernel.adapters import submit_agent_message_event

    normalized_metadata = dict(metadata or {})
    source_id = str(thread_id or normalized_metadata.get("sourceMessageId") or "").strip()
    created_by_value = str(created_by or source_agent_id or "team_workflow").strip()
    kernel_metadata = {
        **normalized_metadata,
        "source": "team_workflow_orchestration",
        "sourceSurface": "team_workflow",
        "sourceMessageId": source_id,
        "projectionRef": {"kind": kind, "id": source_id},
        "senderAgentId": source_agent_id,
        "sourceAgentId": source_agent_id,
        "inboxKind": kind,
        "messageSummary": summary,
        "inboxCreatedBy": created_by_value,
    }
    if normalized_metadata:
        kernel_metadata["agentToolMetadataJson"] = json.dumps(normalized_metadata, ensure_ascii=False, sort_keys=True)
    sender = (
        {"type": "agent", "id": source_agent_id, "agentId": source_agent_id}
        if source_agent_id
        else {"type": "system", "id": created_by_value}
    )
    kernel_result = submit_agent_message_event(
        source="team_workflow",
        sender=sender,
        recipient_agent_ids=[target_agent_id],
        content=content,
        correlation_id=thread_id,
        wake_target=wake_target,
        metadata=kernel_metadata,
        source_id=source_id,
    )
    kernel_delivery = _team_workflow_kernel_delivery(kernel_result, target_agent_id)
    if str(kernel_delivery.get("status") or "").strip() != "delivered":
        raise agent_directory_service.AgentDirectoryError(str(kernel_delivery.get("reason") or "Kernel delivery failed."))
    message = _team_workflow_inbox_message_from_kernel_delivery(
        target_agent_id,
        kernel_delivery,
        fallback={
            "sourceAgentId": source_agent_id,
            "targetAgentId": target_agent_id,
            "threadId": thread_id,
            "kind": kind,
            "summary": summary,
            "metadata": kernel_metadata,
        },
    )
    delivery = (
        kernel_delivery.get("wake")
        if isinstance(kernel_delivery.get("wake"), dict)
        else {
            "wakeRequested": bool(wake_target),
            "wakeStatus": "not_requested" if not wake_target else "skipped",
            "messageId": str(message.get("messageId") or message.get("eventId") or "").strip(),
            "targetAgentId": target_agent_id,
            "targetSessionId": str(message.get("targetSessionId") or "").strip(),
            "turnId": "",
            "reason": "",
        }
    )
    return message, delivery, kernel_result


def _notify_knowledge_steward_for_ingestion(
    team_id: str,
    *,
    steward_agent_id: str,
    requester_agent_id: str,
    steward_candidate_id: str,
    knowledge_base_id: str,
    target_domain: str,
    wake_target: bool,
) -> dict[str, Any]:
    activation = {
        "status": "disabled",
        "targetAgentId": steward_agent_id,
        "messageId": "",
        "threadId": "",
        "wakeRequested": bool(wake_target),
        "wakeStatus": "not_requested",
        "delivery": None,
        "metadata": {
            "kind": "challenge_cup_knowledge_ingestion_request",
            "teamId": team_id,
            "stewardPackCandidateId": steward_candidate_id,
            "knowledgeBaseId": knowledge_base_id,
            "targetDomain": target_domain,
        },
    }
    if not steward_agent_id:
        activation["status"] = "skipped_missing_steward_agent"
        _record_knowledge_steward_activation_event(team_id, steward_candidate_id, activation)
        return activation

    target_agent = agent_directory_service.get_agent(steward_agent_id, include_archived=True)
    if not target_agent:
        activation["status"] = "skipped_missing_steward_agent"
        _record_knowledge_steward_activation_event(team_id, steward_candidate_id, activation)
        return activation
    if str(target_agent.get("status") or "active").strip().lower() == "archived":
        activation["status"] = "skipped_archived_steward_agent"
        _record_knowledge_steward_activation_event(team_id, steward_candidate_id, activation)
        return activation

    source_agent_id = requester_agent_id if requester_agent_id and agent_directory_service.get_agent(requester_agent_id, include_archived=True) else ""
    content = "\n".join(
        [
            "[挑战杯团队知识入库请求]",
            f"团队: {team_id}",
            f"待入库知识包: {steward_candidate_id}",
            f"目标知识库: {knowledge_base_id}",
            f"知识域: {target_domain}",
            "",
            "请作为知识库管理员 Agent 处理这个团队已提炼知识包：",
            "1. 读取 CandidateStore 中的 steward_pack_draft。",
            "2. 复核 sourceRefs、evidenceRefs、sourceTrace、proposalPayload 和 ratingSuggestion。",
            "3. 通过后再调用知识入库门禁，提交来源、创建知识提案并最终 review/apply 到正式 Team Knowledge。",
            "4. 不要把原始搜集噪音直接写入正式知识库；无法确认时标记 needs_revision。",
        ]
    )
    thread_id = f"challenge-cup-knowledge-ingestion:{team_id}:{steward_candidate_id}"
    message_summary = f"挑战杯团队待入库知识包 {steward_candidate_id} 请求最终入库。"
    try:
        message, delivery, kernel_result = _submit_team_workflow_inbox_via_kernel(
            target_agent_id=steward_agent_id,
            content=content,
            source_agent_id=source_agent_id,
            thread_id=thread_id,
            kind="challenge_cup_knowledge_ingestion_request",
            summary=message_summary,
            created_by=requester_agent_id or "team_workflow",
            wake_target=wake_target,
            metadata={
                **activation["metadata"],
                "requesterAgentId": requester_agent_id,
                "expectedAction": "submit_and_review_steward_pack_to_team_knowledge",
                "officialBoundary": {
                    "currentWritesOfficialKnowledge": False,
                    "currentWritesOfficialRag": False,
                    "currentWritesOfficialGraph": False,
                    "finalIngestionOwnedByKnowledgeSteward": True,
                },
            },
        )
    except Exception as exc:
        activation["status"] = "message_failed"
        activation["error"] = str(exc)
        activation["errorType"] = type(exc).__name__
        _record_knowledge_steward_activation_event(team_id, steward_candidate_id, activation)
        return activation

    activation.update(
        {
            "status": "message_written",
            "messageId": str(message.get("messageId") or message.get("eventId") or ""),
            "threadId": str(message.get("threadId") or ""),
            "message": message,
            "kernel": _team_workflow_kernel_summary(kernel_result),
        }
    )
    if wake_target:
        activation["delivery"] = delivery
        activation["wakeStatus"] = str((delivery or {}).get("wakeStatus") or "unknown")
        if activation["wakeStatus"] == "started":
            activation["status"] = "agent_wake_started"
        else:
            activation["status"] = f"agent_wake_{activation['wakeStatus']}"
    _record_knowledge_steward_activation_event(team_id, steward_candidate_id, activation)
    return activation


def _record_knowledge_steward_activation_event(
    team_id: str,
    steward_candidate_id: str,
    activation: dict[str, Any],
) -> None:
    status = _trim_text(activation.get("status"), max_length=120) or "unknown"
    failed = status == "message_failed" or status.startswith("skipped_")
    _record_workflow_event(
        "knowledge_collection.steward_notification_failed" if failed else "knowledge_collection.steward_notification_completed",
        team_id,
        level="warning" if failed else "info",
        outcome="failed" if failed else "completed",
        fields={
            "stewardPackCandidateId": steward_candidate_id,
            "targetAgentId": _trim_text(activation.get("targetAgentId"), max_length=160),
            "knowledgeBaseId": _trim_text((activation.get("metadata") or {}).get("knowledgeBaseId"), max_length=128)
            if isinstance(activation.get("metadata"), dict)
            else "",
            "status": status,
            "messageId": _trim_text(activation.get("messageId"), max_length=160),
            "threadId": _trim_text(activation.get("threadId"), max_length=240),
            "wakeRequested": bool(activation.get("wakeRequested")),
            "wakeStatus": _trim_text(activation.get("wakeStatus"), max_length=120),
            "turnId": _trim_text((activation.get("delivery") or {}).get("turnId"), max_length=160)
            if isinstance(activation.get("delivery"), dict)
            else "",
            "errorType": _trim_text(activation.get("errorType"), max_length=160),
        },
        child_log_path=f"artifacts/knowledge-steward-{_safe_token(steward_candidate_id, default='candidate', max_length=96)}-notification.jsonl",
        child_log_payload={
            "kind": "knowledge_steward_ingestion_notification",
            "teamId": team_id,
            "stewardPackCandidateId": steward_candidate_id,
            "targetAgentId": _trim_text(activation.get("targetAgentId"), max_length=160),
            "knowledgeBaseId": _trim_text((activation.get("metadata") or {}).get("knowledgeBaseId"), max_length=128)
            if isinstance(activation.get("metadata"), dict)
            else "",
            "status": status,
            "messageId": _trim_text(activation.get("messageId"), max_length=160),
            "threadId": _trim_text(activation.get("threadId"), max_length=240),
            "wakeRequested": bool(activation.get("wakeRequested")),
            "wakeStatus": _trim_text(activation.get("wakeStatus"), max_length=120),
            "turnId": _trim_text((activation.get("delivery") or {}).get("turnId"), max_length=160)
            if isinstance(activation.get("delivery"), dict)
            else "",
            "kernel": activation.get("kernel") if isinstance(activation.get("kernel"), dict) else {},
            "errorType": _trim_text(activation.get("errorType"), max_length=160),
        },
    )


def _knowledge_steward_activation_log_payload(activation: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(activation, dict):
        return {}
    delivery = activation.get("delivery") if isinstance(activation.get("delivery"), dict) else {}
    metadata = activation.get("metadata") if isinstance(activation.get("metadata"), dict) else {}
    return {
        "status": _trim_text(activation.get("status"), max_length=120),
        "targetAgentId": _trim_text(activation.get("targetAgentId"), max_length=160),
        "knowledgeBaseId": _trim_text(metadata.get("knowledgeBaseId"), max_length=128),
        "messageId": _trim_text(activation.get("messageId"), max_length=160),
        "threadId": _trim_text(activation.get("threadId"), max_length=240),
        "wakeRequested": bool(activation.get("wakeRequested")),
        "wakeStatus": _trim_text(activation.get("wakeStatus"), max_length=120),
        "turnId": _trim_text(delivery.get("turnId"), max_length=160),
        "kernel": activation.get("kernel") if isinstance(activation.get("kernel"), dict) else {},
        "errorType": _trim_text(activation.get("errorType"), max_length=160),
    }


# 可作为知识提案审批人的团队角色线索（coordinator / lead / owner）。
# 与 team_knowledge_service.REVIEW_ROLES 对应，但这里用子串匹配以兼容
# research_coordination 这类带前缀的研究流角色。
_TEAM_REVIEW_ROLE_HINTS = ("coordination", "coordinator", "lead", "owner")


def _resolve_team_review_agent_id(team: dict[str, Any], *, exclude_agent_id: str = "") -> str:
    """Resolve a team member that can act as the knowledge-review authority.

    Separation of duties: the steward proposes; a distinct coordinator/lead
    member reviews and applies. Returns the matched member agentId, or "" when
    the team has no coordinator/lead member to act as reviewer.
    """
    excluded = str(exclude_agent_id or "").strip()
    members = team.get("members") if isinstance(team, dict) else None
    if not isinstance(members, list):
        return ""
    for hint in _TEAM_REVIEW_ROLE_HINTS:
        for member in members:
            if not isinstance(member, dict):
                continue
            agent_id = str(member.get("agentId") or "").strip()
            role = str(member.get("role") or "").strip().lower()
            if not agent_id or agent_id == excluded:
                continue
            if hint in role:
                return agent_id
    return ""


def _knowledge_ingestion_work_run_store() -> work_run_store.WorkRunStore:
    return work_run_store.WorkRunStore(root=work_run_store.WORK_RUNS_DIR)


def _persist_knowledge_ingestion_work_run(
    team_id: str,
    run_id: str,
    *,
    status: str,
    current_phase: str,
    summary: str,
    active: bool,
    result: dict[str, Any] | None = None,
    error: str = "",
    error_type: str = "",
) -> dict[str, Any]:
    now = utc_now_iso()
    snapshot: dict[str, Any] = {
        "runId": run_id,
        "runKind": KNOWLEDGE_INGESTION_WORK_RUN_KIND,
        "kind": KNOWLEDGE_INGESTION_WORK_RUN_KIND,
        "status": status,
        "currentPhase": current_phase,
        "stageType": "knowledge_ingestion",
        "teamId": team_id,
        "summary": _trim_text(summary, max_length=500),
        "currentTask": _trim_text(summary, max_length=500),
        "updatedAt": now,
    }
    if not active:
        snapshot["finishedAt"] = now
    if isinstance(result, dict):
        result_summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
        snapshot["result"] = {
            "status": _trim_text(result.get("status"), max_length=80),
            "formalKnowledgeItemCount": _source_collection_count(result_summary.get("formalKnowledgeItemCount")),
            "knowledgeBaseId": _trim_text(result_summary.get("knowledgeBaseId"), max_length=128),
            "stewardPackCandidateId": _trim_text(result_summary.get("stewardPackCandidateId"), max_length=160),
        }
    if error:
        snapshot["error"] = _trim_text(error, max_length=500)
    if error_type:
        snapshot["errorType"] = _trim_text(error_type, max_length=120)
    return _knowledge_ingestion_work_run_store().persist_snapshot(
        KNOWLEDGE_INGESTION_WORK_RUN_KIND,
        snapshot,
        active_run_id=run_id if active else "",
    )


def _knowledge_ingestion_snapshot_is_active(snapshot: dict[str, Any] | None, team_id: str) -> bool:
    if not isinstance(snapshot, dict):
        return False
    if _trim_text(snapshot.get("teamId"), max_length=160) != team_id:
        return False
    status = _trim_text(snapshot.get("status"), max_length=80).lower()
    current_phase = _trim_text(snapshot.get("currentPhase"), max_length=80).lower()
    return status in {"queued", "running"} or current_phase in {"queued", "running"}


def _knowledge_ingestion_background_response(team_id: str, snapshot: dict[str, Any], *, already_running: bool) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": team_id,
        "status": "accepted",
        "executionMode": "background",
        "accepted": True,
        "alreadyRunning": already_running,
        "activeWorkRun": snapshot,
        "summary": {
            "formalKnowledgeItemCount": 0,
            "knowledgeBaseId": "",
            "stewardPackCandidateId": "",
        },
        "nextActions": [
            "资料入库已进入后台执行，页面可继续操作。",
            "保持页面打开或稍后返回；入库状态会在不阻塞请求的情况下刷新。",
        ],
    }


def start_knowledge_collection_ingestion_background(team_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Queue the synchronous knowledge-collection ingestion on a background worker.

    首次入库会现场用真实模型生成 steward pack（耗时分钟级）。后台执行让点击立即返回，
    UI 通过 knowledge-ingestion/status 的 activeWorkRun 轮询进度，避免同步 HTTP 超时。
    """
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    team_service.get_team(normalized_team_id)
    request_payload = dict(payload) if isinstance(payload, dict) else {}
    store = _knowledge_ingestion_work_run_store()
    with _WORKFLOW_LOCK:
        active_snapshot = store.load_active_snapshot(KNOWLEDGE_INGESTION_WORK_RUN_KIND)
        if _knowledge_ingestion_snapshot_is_active(active_snapshot, normalized_team_id):
            _record_workflow_event(
                "knowledge_collection.ingestion_background_already_running",
                normalized_team_id,
                fields={"runId": _trim_text(active_snapshot.get("runId"), max_length=160)},
            )
            return _knowledge_ingestion_background_response(normalized_team_id, active_snapshot, already_running=True)
        run_id = _new_record_id("knowledge-ingestion")
        snapshot = _persist_knowledge_ingestion_work_run(
            normalized_team_id,
            run_id,
            status="running",
            current_phase="running",
            summary="资料入库已进入后台执行：审查→候选图→入库包→提交→审核→正式入库。",
            active=True,
        )
    worker = threading.Thread(
        target=_run_knowledge_collection_ingestion_background,
        args=(normalized_team_id, run_id, request_payload),
        name=f"knowledge-ingestion-{run_id[:24]}",
        daemon=True,
    )
    worker.start()
    _record_workflow_event(
        "knowledge_collection.ingestion_background_accepted",
        normalized_team_id,
        fields={"runId": run_id, "threadName": worker.name},
    )
    return _knowledge_ingestion_background_response(normalized_team_id, snapshot, already_running=False)


def _run_knowledge_collection_ingestion_background(team_id: str, run_id: str, payload: dict[str, Any]) -> None:
    try:
        result = run_knowledge_collection_ingestion(team_id, payload)
    except Exception as exc:
        _persist_knowledge_ingestion_work_run(
            team_id,
            run_id,
            status="failed",
            current_phase="failed",
            summary=_trim_text(exc, max_length=300) or "资料入库后台执行失败。",
            active=False,
            error=_trim_text(exc, max_length=500),
            error_type=type(exc).__name__,
        )
        _record_workflow_event(
            "knowledge_collection.ingestion_background_failed",
            team_id,
            fields={"runId": run_id, "errorType": type(exc).__name__, "error": _trim_text(exc, max_length=500)},
        )
        return
    result_summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    formal_count = _source_collection_count(result_summary.get("formalKnowledgeItemCount"))
    terminal_status = _trim_text(result.get("status"), max_length=80) or "completed"
    _persist_knowledge_ingestion_work_run(
        team_id,
        run_id,
        status="completed" if formal_count > 0 else terminal_status,
        current_phase="completed" if formal_count > 0 else terminal_status,
        summary=(
            f"资料入库完成：正式 KnowledgeItem {formal_count} 条。"
            if formal_count > 0
            else f"资料入库结束：{terminal_status}。"
        ),
        active=False,
        result=result,
    )
    _record_workflow_event(
        "knowledge_collection.ingestion_background_completed",
        team_id,
        fields={"runId": run_id, "status": terminal_status, "formalKnowledgeItemCount": formal_count},
    )


def run_knowledge_collection_ingestion(team_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run the four-step knowledge collection gate from screened sources to Team Knowledge.

    The function intentionally reuses the existing source-quality, candidate-graph,
    steward-pack, source-review, and knowledge-review gates instead of writing
    formal Team Knowledge directly.
    """

    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    team_detail = team_service.get_team(normalized_team_id)
    payload = payload if isinstance(payload, dict) else {}
    source_quality_agent_id = _trim_text(payload.get("sourceQualityAgentId"), max_length=160) or "Source Quality Assessment Agent"
    candidate_graph_agent_id = _trim_text(payload.get("candidateGraphAgentId"), max_length=160) or "Candidate Graph Preview Agent"
    # 默认必须是团队成员 agentId（而非显示名），否则建库/审核的成员校验会失败。
    steward_agent_id = _trim_text(payload.get("stewardAgentId"), max_length=160) or agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID
    # 职责分离：steward 提案，由独立的 coordinator/lead 成员审批，避免自提自批。
    reviewer_agent_id = _trim_text(payload.get("reviewerAgentId"), max_length=160) or _resolve_team_review_agent_id(
        team_detail, exclude_agent_id=steward_agent_id
    )
    target_domain = _trim_text(payload.get("targetDomain"), max_length=240) or "神经机制启发神经网络算法"
    max_candidates = _normalize_int(payload.get("maxCandidates"), default=80, minimum=1, maximum=200)
    force_review = bool(payload.get("forceReview"))
    force_rebuild = bool(payload.get("forceRebuild"))
    auto_create_knowledge_base = bool(payload.get("autoCreateKnowledgeBase", True))
    auto_submit = bool(payload.get("autoSubmit", False))
    auto_review_source = bool(payload.get("autoReviewSource", False))
    auto_approve = bool(payload.get("autoApprove", False))
    notify_steward_agent = bool(payload.get("notifyStewardAgent", True))
    wake_steward_agent = bool(payload.get("wakeStewardAgent", True))
    requester_agent_id = _trim_text(payload.get("requesterAgentId"), max_length=160) or source_quality_agent_id
    steps: list[dict[str, Any]] = []

    def append_step(
        stage_id: str,
        label: str,
        status: str,
        *,
        input_count: int = 0,
        output_count: int = 0,
        detail: str = "",
        artifact_id: str = "",
    ) -> None:
        steps.append(
            {
                "stageId": stage_id,
                "label": label,
                "status": status,
                "inputCount": input_count,
                "outputCount": output_count,
                "detail": detail,
                "artifactId": artifact_id,
            }
        )

    source_quality = assess_source_quality_batch(
        normalized_team_id,
        {
            "assessedByAgent": source_quality_agent_id,
            "maxCandidates": max_candidates,
            "force": force_review,
            "notes": "资料审查 Agent 执行第一阶段一键入库前的批量质量审查。",
        },
    )
    source_quality_summary = source_quality.get("sourceQualityStatus", {}).get("summary", {})
    source_candidate_count = int(source_quality_summary.get("sourceCandidateCount") or 0)
    approved_count = int(source_quality_summary.get("approvedSourceCandidateCount") or 0)
    append_step(
        "source_review",
        "资料审查",
        "completed" if approved_count else str(source_quality.get("status") or "blocked"),
        input_count=source_candidate_count,
        output_count=approved_count,
        detail=f"{source_quality_agent_id} completed source quality screening.",
        artifact_id=str(source_quality.get("batchRunId") or ""),
    )
    if approved_count <= 0:
        status_payload = get_knowledge_ingestion_status(normalized_team_id)
        _record_workflow_event(
            "knowledge_collection.ingestion_blocked",
            normalized_team_id,
            fields={
                "reason": "no_approved_sources",
                "sourceCandidateCount": source_candidate_count,
                "sourceQualityAgentId": source_quality_agent_id,
            },
        )
        return {
            "schemaVersion": SCHEMA_VERSION,
            "teamId": normalized_team_id,
            "status": "blocked",
            "steps": steps,
            "sourceQuality": source_quality,
            "candidateGraph": None,
            "precheck": None,
            "sourceReview": None,
            "knowledgeSubmission": None,
            "knowledgeReview": None,
            "knowledgeBase": None,
            "statusSnapshot": status_payload,
            "summary": {
                "sourceCandidateCount": source_candidate_count,
                "approvedSourceCandidateCount": approved_count,
                "formalKnowledgeItemCount": status_payload["summary"]["formalKnowledgeItemCount"],
                "nextAction": "补充或重新审查资料后再入库。",
            },
            "workflow": source_quality["workflow"],
        }

    candidate_graph = build_candidate_graph(
        normalized_team_id,
        {
            "title": "资料入库候选关系快照",
            "createdByAgent": candidate_graph_agent_id,
            "sourceQualityAgentId": source_quality_agent_id,
            "curationMode": "agent_approved_only",
            "forceRebuild": force_rebuild,
        },
    )
    graph_summary = candidate_graph["graph"]["summary"]
    append_step(
        "candidate_graph",
        "候选关系",
        "completed",
        input_count=int(graph_summary.get("inputCandidateCount") or approved_count),
        output_count=int(graph_summary.get("nodeCount") or 0),
        detail=f"{candidate_graph_agent_id} generated a candidate-only graph snapshot.",
        artifact_id=str(candidate_graph["candidateGraph"].get("candidateId") or ""),
    )

    precheck = run_knowledge_ingestion_precheck(
        normalized_team_id,
        {
            "stewardAgentId": steward_agent_id,
            "targetDomain": target_domain,
            "maxCandidates": max_candidates,
            "forceRebuild": force_rebuild,
        },
    )
    steward_candidate_id = str(precheck["candidate"].get("candidateId") or "")
    append_step(
        "steward_pack",
        "资料提炼包",
        "completed",
        input_count=int(precheck["precheck"].get("selectedCandidateCount") or 0),
        output_count=1,
        detail=f"{steward_agent_id} built a governed steward pack.",
        artifact_id=steward_candidate_id,
    )

    knowledge_base_id = _trim_text(payload.get("knowledgeBaseId"), max_length=128)
    knowledge_base: dict[str, Any] | None = None
    if not knowledge_base_id:
        status_before_submit = get_knowledge_ingestion_status(normalized_team_id)
        existing_bases = [item for item in list(status_before_submit.get("knowledgeBases") or []) if isinstance(item, dict)]
        if existing_bases:
            knowledge_base_id = str(existing_bases[0].get("knowledgeBaseId") or "")
            knowledge_base = existing_bases[0]
        elif auto_create_knowledge_base:
            try:
                knowledge_base = team_knowledge_service.create_knowledge_base(
                    normalized_team_id,
                    name="挑战杯科研知识库",
                    description="由 ai科学研究团队第一阶段一键入库流程创建。",
                    actor_agent_id=steward_agent_id,
                )
                knowledge_base_id = str(knowledge_base.get("knowledgeBaseId") or "")
            except (team_knowledge_service.TeamKnowledgeError, team_knowledge_service.TeamKnowledgeNotFoundError) as exc:
                raise TeamWorkflowOrchestrationError(f"Knowledge base auto-create failed: {exc}") from exc
    if not knowledge_base_id:
        raise TeamWorkflowOrchestrationError("Knowledge base id is required before knowledge collection ingestion.")

    # 职责分离下让 coordinator/lead 审批：给该审批人补一条 per-base review 授权，
    # 对新建或既有知识库都生效，避免最终审批关因角色不在 REVIEW_ROLES 而无人可过。
    if auto_approve and reviewer_agent_id:
        try:
            team_knowledge_service.ensure_knowledge_base_review_grant(knowledge_base_id, reviewer_agent_id)
        except (team_knowledge_service.TeamKnowledgeError, team_knowledge_service.TeamKnowledgeNotFoundError) as exc:
            raise TeamWorkflowOrchestrationError(f"Knowledge review grant failed: {exc}") from exc

    source_review: dict[str, Any] | None = None
    knowledge_submission: dict[str, Any] | None = None
    knowledge_review: dict[str, Any] | None = None
    knowledge_steward_activation: dict[str, Any] | None = None
    if auto_submit:
        knowledge_submission = submit_steward_pack_to_knowledge_ingestion(
            normalized_team_id,
            steward_candidate_id,
            {
                "knowledgeBaseId": knowledge_base_id,
                "proposedByAgentId": steward_agent_id,
            },
        )
        inbox_source_id = str(
            ((knowledge_submission.get("candidate") or {}).get("metadata") or {})
            .get("knowledgeIngestion", {})
            .get("inboxSourceId")
            or ""
        )
        append_step(
            "source_gate",
            "来源入库门禁",
            "pending_review" if inbox_source_id else str((knowledge_submission.get("knowledgeIngestion") or {}).get("status") or "submitted"),
            input_count=1,
            output_count=1 if inbox_source_id else 0,
            detail="资料入库包已进入团队来源收件箱。",
            artifact_id=inbox_source_id,
        )
        if auto_review_source and inbox_source_id:
            try:
                source_review = team_knowledge_service.review_owner_inbox_source(
                    "team",
                    normalized_team_id,
                    inbox_source_id,
                    decision="accepted",
                    reviewed_by_agent_id=steward_agent_id,
                    resolution_note="一键入库流程由知识治理 Agent 接受资料入库包来源。",
                )
            except (team_knowledge_service.TeamKnowledgeError, team_knowledge_service.TeamKnowledgeNotFoundError) as exc:
                raise TeamWorkflowOrchestrationError(f"Source review failed: {exc}") from exc
            central_source_id = str((source_review.get("centralSource") or {}).get("centralSourceId") or "")
            knowledge_submission = submit_steward_pack_to_knowledge_ingestion(
                normalized_team_id,
                steward_candidate_id,
                {
                    "knowledgeBaseId": knowledge_base_id,
                    "proposedByAgentId": steward_agent_id,
                    "centralSourceId": central_source_id,
                },
            )
            append_step(
                "knowledge_proposal",
                "知识库提案",
                "pending_review",
                input_count=1,
                output_count=1,
                detail="资料入库包已成为知识库待审提案。",
                artifact_id=str(((knowledge_submission.get("knowledgeIngestion") or {}).get("package") or {}).get("proposal", {}).get("proposalId") or ""),
            )
        if (
            auto_approve
            and reviewer_agent_id
            and knowledge_submission
            and str((knowledge_submission.get("knowledgeIngestion") or {}).get("status") or "") == "pending_review"
        ):
            # 职责分离：由 coordinator/lead 审批人（≠ steward 提案人）批准入库。
            knowledge_review = review_steward_pack_knowledge_ingestion(
                normalized_team_id,
                steward_candidate_id,
                {
                    "knowledgeBaseId": knowledge_base_id,
                    "reviewedByAgentId": reviewer_agent_id,
                    "decision": "approved",
                    "resolutionNote": "一键入库流程通过资料审查、入库关系和知识库门禁后，由团队审批人批准入库。",
                },
            )
            append_step(
                "official_knowledge",
                "正式入库",
                "completed",
                input_count=1,
                output_count=len(
                    ((knowledge_review.get("knowledgeIngestion") or {}).get("officialSyncRecord") or {}).get("knowledgeItemIds")
                    or []
                ),
                detail="正式 KnowledgeItem 已通过现有知识库门禁创建。",
                artifact_id=str((knowledge_review.get("candidate") or {}).get("candidateId") or ""),
            )

    if notify_steward_agent and not knowledge_review:
        knowledge_steward_activation = _notify_knowledge_steward_for_ingestion(
            normalized_team_id,
            steward_agent_id=steward_agent_id,
            requester_agent_id=requester_agent_id,
            steward_candidate_id=steward_candidate_id,
            knowledge_base_id=knowledge_base_id,
            target_domain=target_domain,
            wake_target=wake_steward_agent,
        )
        append_step(
            "knowledge_steward_request",
            "通知知识库管理员",
            str(knowledge_steward_activation.get("status") or "message_written"),
            input_count=1,
            output_count=1 if knowledge_steward_activation.get("messageId") else 0,
            detail="待入库知识包已发送给知识库管理员 Agent，等待它执行最终入库。"
            if knowledge_steward_activation.get("messageId")
            else "待入库知识包已生成，但知识库管理员 Agent 尚未收到消息。",
            artifact_id=str(knowledge_steward_activation.get("messageId") or ""),
        )

    status_payload = get_knowledge_ingestion_status(normalized_team_id)
    activation_status = str((knowledge_steward_activation or {}).get("status") or "")
    final_status = (
        "completed"
        if knowledge_review
        else "pending_review"
        if knowledge_submission
        else "agent_notified"
        if activation_status in {"message_written", "agent_wake_started"}
        else "agent_wake_pending"
        if activation_status.startswith("agent_wake_skipped_")
        else "agent_notification_failed"
        if knowledge_steward_activation
        else "precheck_ready"
    )
    _record_workflow_event(
        "knowledge_collection.ingested",
        normalized_team_id,
        fields={
            "status": final_status,
            "sourceCandidateCount": source_candidate_count,
            "approvedSourceCandidateCount": approved_count,
            "candidateGraphId": str(candidate_graph["candidateGraph"].get("candidateId") or ""),
            "stewardPackCandidateId": steward_candidate_id,
            "knowledgeBaseId": knowledge_base_id,
            "formalKnowledgeItemCount": status_payload["summary"]["formalKnowledgeItemCount"],
            "autoSubmit": auto_submit,
            "autoReviewSource": auto_review_source,
            "autoApprove": auto_approve,
            "notifyStewardAgent": notify_steward_agent,
            "wakeStewardAgent": wake_steward_agent,
            "knowledgeStewardActivationStatus": activation_status,
            "knowledgeStewardInboxMessageId": str((knowledge_steward_activation or {}).get("messageId") or ""),
            "reusedCandidateGraph": bool(candidate_graph.get("reusedCandidateGraph")),
            "reusedStewardPack": bool(precheck.get("reusedStewardPack")),
            "ingestionFingerprint": str(precheck.get("ingestionFingerprint") or candidate_graph.get("ingestionFingerprint") or ""),
        },
        child_log_path=f"artifacts/knowledge-collection-{_safe_token(normalized_team_id, default='team', max_length=96)}-ingestion.jsonl",
        child_log_payload={
            "kind": "knowledge_collection_ingestion",
            "teamId": normalized_team_id,
            "status": final_status,
            "steps": steps[:24],
            "truncatedStepCount": max(0, len(steps) - 24),
            "sourceCandidateCount": source_candidate_count,
            "approvedSourceCandidateCount": approved_count,
            "candidateGraphId": str(candidate_graph["candidateGraph"].get("candidateId") or ""),
            "candidateGraphNodeCount": int(graph_summary.get("nodeCount") or 0),
            "candidateGraphEdgeCount": int(graph_summary.get("edgeCount") or 0),
            "stewardPackCandidateId": steward_candidate_id,
            "knowledgeBaseId": knowledge_base_id,
            "formalKnowledgeItemCount": status_payload["summary"]["formalKnowledgeItemCount"],
            "autoSubmit": auto_submit,
            "autoReviewSource": auto_review_source,
            "autoApprove": auto_approve,
            "notifyStewardAgent": notify_steward_agent,
            "wakeStewardAgent": wake_steward_agent,
            "knowledgeStewardActivation": _knowledge_steward_activation_log_payload(knowledge_steward_activation),
            "reusedCandidateGraph": bool(candidate_graph.get("reusedCandidateGraph")),
            "reusedStewardPack": bool(precheck.get("reusedStewardPack")),
            "ingestionFingerprint": str(precheck.get("ingestionFingerprint") or candidate_graph.get("ingestionFingerprint") or ""),
        },
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "status": final_status,
        "steps": steps,
        "sourceQuality": source_quality,
        "candidateGraph": candidate_graph,
        "precheck": precheck,
        "sourceReview": source_review,
        "knowledgeSubmission": knowledge_submission,
        "knowledgeReview": knowledge_review,
        "knowledgeStewardActivation": knowledge_steward_activation,
        "reusedCandidateGraph": bool(candidate_graph.get("reusedCandidateGraph")),
        "reusedStewardPack": bool(precheck.get("reusedStewardPack")),
        "ingestionFingerprint": str(precheck.get("ingestionFingerprint") or candidate_graph.get("ingestionFingerprint") or ""),
        "knowledgeBase": knowledge_base or {"knowledgeBaseId": knowledge_base_id},
        "statusSnapshot": status_payload,
        "summary": {
            "sourceCandidateCount": source_candidate_count,
            "approvedSourceCandidateCount": approved_count,
            "candidateGraphNodeCount": int(graph_summary.get("nodeCount") or 0),
            "candidateGraphEdgeCount": int(graph_summary.get("edgeCount") or 0),
            "stewardPackCandidateId": steward_candidate_id,
            "knowledgeBaseId": knowledge_base_id,
            "formalKnowledgeItemCount": status_payload["summary"]["formalKnowledgeItemCount"],
            "knowledgeStewardInboxMessageId": str((knowledge_steward_activation or {}).get("messageId") or ""),
            "knowledgeStewardActivationStatus": activation_status,
            "reusedCandidateGraph": bool(candidate_graph.get("reusedCandidateGraph")),
            "reusedStewardPack": bool(precheck.get("reusedStewardPack")),
            "ingestionFingerprint": str(precheck.get("ingestionFingerprint") or candidate_graph.get("ingestionFingerprint") or ""),
            "nextAction": "进入实验规划" if knowledge_review else ("等待知识库管理员最终入库" if knowledge_steward_activation else "检查入库审核门禁"),
        },
        "workflow": (
            knowledge_review["workflow"]
            if knowledge_review
            else knowledge_submission["workflow"]
            if knowledge_submission
            else precheck["workflow"]
        ),
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


def _candidate_ready_for_agent_graph(candidate: dict[str, Any]) -> bool:
    if not _candidate_allowed_for_agent_graph_input(candidate):
        return False
    candidate_type = str(candidate.get("candidateType") or "")
    current_state = str(candidate.get("currentState") or "")
    quality_status = str(candidate.get("qualityStatus") or "")
    if current_state in ARCHIVED_CANDIDATE_STATES or quality_status in SOURCE_QUALITY_REJECTED_STATUSES:
        return False
    if candidate_type == "source_manifest":
        return _source_quality_bucket(candidate) == "approved"
    if candidate_type not in {"paper_note", "neuro_mechanism", "mechanism_mapping", "algorithm_hypothesis", "review_record"}:
        return False
    if current_state.endswith("_needs_revision") or quality_status in {"needs_revision", "source_quality_needs_revision"}:
        return False
    validation = validate_candidate_record(candidate)
    return bool(validation.get("valid"))


def _candidate_allowed_for_agent_graph_input(candidate: dict[str, Any]) -> bool:
    candidate_type = str(candidate.get("candidateType") or "")
    if candidate_type == "candidate_graph":
        return False
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    if str(candidate.get("currentWorkflowNode") or "") == "steward_ingestion":
        return False
    if str(metadata.get("taskType") or "") == "steward_pack_draft":
        return False
    return candidate_type in {"source_manifest", "paper_note", "neuro_mechanism", "mechanism_mapping", "algorithm_hypothesis", "review_record"}


def _knowledge_collection_fingerprint(
    team_id: str,
    candidates: list[dict[str, Any]],
    *,
    purpose: str,
    curation_mode: str = "",
    target_domain: str = "",
    steward_agent_id: str = "",
    candidate_graph_id: str = "",
) -> str:
    candidate_ids = sorted(str(item.get("candidateId") or "") for item in candidates if item.get("candidateId"))
    payload = {
        "teamId": team_id,
        "purpose": purpose,
        "candidateIds": candidate_ids,
        "curationMode": curation_mode,
        "targetDomain": target_domain,
        "stewardAgentId": steward_agent_id,
        "candidateGraphId": candidate_graph_id,
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:32]


def _candidate_knowledge_collection_fingerprint(candidate: dict[str, Any]) -> str:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    ingestion = metadata.get("knowledgeCollectionIngestion") if isinstance(metadata.get("knowledgeCollectionIngestion"), dict) else {}
    output = metadata.get("output") if isinstance(metadata.get("output"), dict) else {}
    output_ingestion = output.get("knowledgeCollectionIngestion") if isinstance(output.get("knowledgeCollectionIngestion"), dict) else {}
    return _trim_text(ingestion.get("fingerprint") or output_ingestion.get("fingerprint") or candidate.get("ingestionFingerprint"), max_length=80)


def _find_reusable_candidate_graph(candidate_store: dict[str, Any], fingerprint: str) -> dict[str, Any] | None:
    candidates = [
        item
        for item in list(candidate_store.get("candidates") or [])
        if isinstance(item, dict)
        and str(item.get("candidateType") or "") == "candidate_graph"
        and not _candidate_is_archived(item)
        and _candidate_knowledge_collection_fingerprint(item) == fingerprint
    ]
    return _latest_candidate_record(candidates)


def _find_reusable_steward_pack(candidate_store: dict[str, Any], fingerprint: str) -> dict[str, Any] | None:
    reusable_states = {"steward_pack_draft", "pending_source_review", "pending_review"}
    candidates = [
        item
        for item in list(candidate_store.get("candidates") or [])
        if isinstance(item, dict)
        and str(item.get("candidateType") or "") != "candidate_graph"
        and not _candidate_is_archived(item)
        and (
            str(item.get("currentWorkflowNode") or "") == "steward_ingestion"
            or str((item.get("metadata") if isinstance(item.get("metadata"), dict) else {}).get("taskType") or "") == "steward_pack_draft"
        )
        and str(item.get("currentState") or "") in reusable_states
        and _candidate_knowledge_collection_fingerprint(item) == fingerprint
    ]
    return _latest_candidate_record(candidates)


def _latest_candidate_record(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda item: (
            str(item.get("updatedAt") or ""),
            str(item.get("createdAt") or ""),
            str(item.get("candidateId") or ""),
        ),
    )


def _dedupe_candidate_sequence(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_id = str(candidate.get("candidateId") or "")
        if not candidate_id or candidate_id in seen:
            continue
        seen.add(candidate_id)
        deduped.append(candidate)
    return deduped


def _candidate_precheck_ref(candidate: dict[str, Any]) -> dict[str, str]:
    candidate_type = str(candidate.get("candidateType") or "candidate")
    return {
        "type": candidate_type,
        "id": str(candidate.get("candidateId") or ""),
        "label": _source_manifest_label(candidate),
    }


def _build_knowledge_ingestion_precheck_output(
    team_id: str,
    workflow_id: str,
    selected_candidates: list[dict[str, Any]],
    latest_graph: dict[str, Any] | None,
    *,
    target_domain: str,
) -> dict[str, Any]:
    candidate_ids = [str(item.get("candidateId") or "") for item in selected_candidates if item.get("candidateId")]
    source_refs = [_candidate_precheck_ref(item) for item in selected_candidates[:32]]
    evidence_refs = [
        {
            "type": "candidate",
            "id": ref["id"],
            "label": ref["label"],
        }
        for ref in source_refs[:24]
    ]
    if latest_graph:
        evidence_refs.append(
            {
                "type": "candidate_graph",
                "id": str(latest_graph.get("candidateId") or ""),
                "label": _trim_text(latest_graph.get("title"), max_length=240) or "Candidate graph snapshot",
            }
        )
    source_ids = [str(item.get("candidateId") or "") for item in selected_candidates if str(item.get("candidateType") or "") == "source_manifest"]
    local_ids = [str(item.get("candidateId") or "") for item in selected_candidates if str(item.get("candidateType") or "") != "source_manifest"]
    claims = []
    for item in selected_candidates[:24]:
        label = _source_manifest_label(item)
        summary = _trim_text(item.get("summary"), max_length=600)
        claims.append(
            {
                "claim": summary or f"{label} 可作为 {target_domain} 的候选证据。",
                "sourceRef": str(item.get("candidateId") or ""),
            }
        )
    proposal_summary = f"本资料入库包汇总 {len(candidate_ids)} 条已通过资料，用于写入团队知识库前的门禁审查。"
    return {
        "candidateType": "review_record",
        "sourceRefs": source_refs,
        "evidenceRefs": evidence_refs,
        "claims": claims,
        "candidateIds": candidate_ids,
        "targetDomain": target_domain,
        "sourceTrace": {
            "teamId": team_id,
            "workflowId": workflow_id,
            "sourceCandidateIds": source_ids,
            "localDraftCandidateIds": local_ids,
            "candidateGraphId": str((latest_graph or {}).get("candidateId") or ""),
        },
        "riskSummary": (
            "该包仍处于 candidate-only 入库门禁层，只能作为团队知识库入库输入；"
            "正式 Team Knowledge、RAG 和正式图谱仍需审核节点确认。"
        ),
        "proposalPayload": {
            "title": "神经算法资料入库包",
            "summary": proposal_summary,
            "targetDomain": target_domain,
            "candidateIds": candidate_ids,
            "content": "；".join(_source_manifest_label(item) for item in selected_candidates[:12]),
        },
        "ratingSuggestion": {
            "rating": "candidate_only_precheck",
            "score": 0.68,
            "rationale": "来源已通过 Agent 审查，但尚未写入正式团队知识库。",
        },
        "approvalRequired": True,
        "uncertainty": ["正式入库前仍需知识治理门禁确认。"],
        "riskFlags": ["candidate_only", "requires_official_review"],
        "confidence": 0.68,
        "nextAction": "submit_steward_pack_to_knowledge_ingestion_after_gate",
        "requiresReview": True,
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
        if str(item.get("qualityStatus") or "") in SOURCE_QUALITY_APPROVED_STATUSES
        or str(item.get("currentState") or "") in {"source_registered", "screening_ready", "source_screened"}
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
            "团队知识库审核",
            knowledge_summary["proposalCount"],
            ready=knowledge_summary["formalKnowledgeItemCount"] > 0,
            warning=knowledge_summary["pendingProposalCount"] > 0,
            blocked=candidate_summary["stewardPackCandidateCount"] > 0 and knowledge_summary["proposalCount"] == 0,
            next_action="submit_or_review_refinement_proposal",
            reason="正式团队知识库必须经 refinement proposal 审核。",
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
    pending_source_candidates = [
        item
        for item in candidates
        if str(item.get("candidateType") or "") != "candidate_graph" and _candidate_knowledge_ingestion_status(item) == "pending_source_review"
    ]
    for candidate in pending_source_candidates[:12]:
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        ingestion = metadata.get("knowledgeIngestion") if isinstance(metadata.get("knowledgeIngestion"), dict) else {}
        items.append(
            _knowledge_ingestion_action_item(
                "steward_source_pending_review",
                "needs_review",
                "治理包源文件已经进入团队源收件箱，需先审核并提升为中央源。",
                "review_owner_source_inbox",
                "steward_ingestion",
                candidateId=str(candidate.get("candidateId") or ""),
                inboxSourceId=str(ingestion.get("inboxSourceId") or ""),
                knowledgeBaseId=str(ingestion.get("knowledgeBaseId") or ""),
            )
        )
    for candidate in pending_candidates[:12]:
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        ingestion = metadata.get("knowledgeIngestion") if isinstance(metadata.get("knowledgeIngestion"), dict) else {}
        items.append(
            _knowledge_ingestion_action_item(
                "knowledge_proposal_pending_review",
                "needs_review",
                "入库包已经提交，但团队知识库仍在审核队列。",
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
                "资料搜索、提炼、审查和入库链路已跑通。",
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
        "communicationBriefCount": sum(1 for queue_items in queues.values() for item in queue_items if item.get("communicationBrief")),
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
                "nextAction": "知识库管理员需要将这些候选保留在审核门禁下，完成复核后再推进。",
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
    item["communicationBrief"] = _coordination_communication_brief(item)
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


def _coordination_communication_summary(
    summary: dict[str, Any],
    queues: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    briefs = [item.get("communicationBrief") for queue_items in queues.values() for item in queue_items if isinstance(item.get("communicationBrief"), dict)]
    target_counts: dict[str, int] = {}
    channel_counts: dict[str, int] = {}
    for brief in briefs:
        target = str(brief.get("targetAgentRole") or "unknown")
        channel = str(brief.get("channel") or "unknown")
        target_counts[target] = target_counts.get(target, 0) + 1
        channel_counts[channel] = channel_counts.get(channel, 0) + 1
    return {
        "briefCount": len(briefs),
        "targetAgentRoleCounts": dict(sorted(target_counts.items())),
        "channelCounts": dict(sorted(channel_counts.items())),
        "readOnly": True,
        "autoSendEnabled": False,
        "recommendedSender": DEFAULT_OWNER_AGENT_ID,
        "nextAction": "Use the linked team room or Project Agent Bus to send selected briefs after coordinator review.",
        "summaryLine": (
            f"{len(briefs)} coordination brief(s), "
            f"{summary['pendingTransferCount']} pending transfer(s), "
            f"{summary['reworkCandidateCount']} rework item(s)."
        ),
    }


def _coordination_communication_brief(item: dict[str, Any]) -> dict[str, Any]:
    queue = str(item.get("queue") or "")
    node = str(item.get("currentWorkflowNode") or item.get("fromNode") or "")
    state = str(item.get("currentState") or "")
    target_agent = _coordination_target_agent_role(queue, node, state)
    channel = "team_linked_room" if queue == "pending_transfer" else "project_agent_bus"
    subject = _trim_text(_coordination_brief_subject(item, target_agent), max_length=180)
    message = _trim_text(_coordination_brief_message(item, target_agent), max_length=1200)
    return {
        "targetAgentRole": target_agent,
        "channel": channel,
        "subject": subject,
        "message": message,
        "requiresCoordinatorReview": True,
        "autoSendEnabled": False,
        "sourceQueue": queue,
    }


def _coordination_target_agent_role(queue: str, node: str, state: str) -> str:
    if queue == "pending_transfer":
        return DEFAULT_OWNER_AGENT_ID
    if queue == "stewardship" or node == "steward_ingestion" or "steward" in state:
        return "知识库管理员"
    if node in {"knowledge_collection", "source_screening"} or state.startswith("source_"):
        return "Source Intake Agent"
    if node == "paper_note" or "paper_note" in state:
        return "Paper Note Extraction Agent"
    if node == "neuro_mechanism" or ("mechanism_" in state and "mapping" not in state):
        return "Neuro Mechanism Extraction Agent"
    if node == "mechanism_mapping" or "mapping" in state:
        return "Mechanism Mapping Agent"
    if node == "algorithm_hypothesis" or "hypothesis" in state:
        return "Algorithm Hypothesis Agent"
    if node == "research_review" or "review" in state:
        return "Evidence Review Agent"
    if queue == "blocked":
        return "Evidence Review Agent"
    return DEFAULT_OWNER_AGENT_ID


def _coordination_brief_subject(item: dict[str, Any], target_agent: str) -> str:
    title = str(item.get("title") or item.get("candidateType") or item.get("candidateId") or "workflow item")
    if item.get("transferId"):
        return f"Transfer decision needed: {item.get('fromNode') or '-'} -> {item.get('toNode') or '-'}"
    return f"{target_agent} follow-up needed: {title}"


def _coordination_brief_message(item: dict[str, Any], target_agent: str) -> str:
    candidate_id = str(item.get("candidateId") or "")
    state = str(item.get("currentState") or "")
    reason = str(item.get("reason") or "")
    issue_count = int(item.get("issueCount") or 0)
    if item.get("transferId"):
        return (
            f"Please review transfer {item.get('transferId')} for candidate {candidate_id}. "
            f"Requested route: {item.get('fromNode') or '-'} -> {item.get('toNode') or '-'}. "
            f"Reason: {reason or 'No reason recorded.'}"
        )
    return (
        f"{target_agent} should review candidate {candidate_id} at state {state or '-'}. "
        f"Issue count: {issue_count}. "
        f"Reason: {reason or 'No reason recorded.'}"
    )


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


def _source_extraction_evidence_refs(candidate: dict[str, Any], extraction: dict[str, Any], *, anchor_ids: set[str] | None = None) -> list[dict[str, str]]:
    source_label = _source_manifest_label(candidate)
    refs: list[dict[str, str]] = []
    for anchor in list(extraction.get("pageAnchors") or [])[:32]:
        if not isinstance(anchor, dict):
            continue
        page = int(anchor.get("page") or 0)
        anchor_id = _source_extraction_anchor_id(candidate, anchor)
        if anchor_ids is not None and anchor_id not in anchor_ids:
            continue
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


def _build_paper_note_chunks(
    candidate: dict[str, Any],
    extraction: dict[str, Any],
    *,
    max_pages_per_chunk: int,
    max_chars_per_chunk: int,
) -> list[dict[str, Any]]:
    anchors = [
        item
        for item in list(extraction.get("pageAnchors") or [])
        if isinstance(item, dict) and _trim_text(item.get("text"), max_length=max_chars_per_chunk)
    ]
    anchors = sorted(anchors, key=lambda item: int(item.get("page") or 0))
    chunks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_chars = 0
    for anchor in anchors:
        text_chars = len(_trim_text(anchor.get("text"), max_length=max_chars_per_chunk))
        if current and (len(current) >= max_pages_per_chunk or current_chars + text_chars > max_chars_per_chunk):
            chunks.append(current)
            current = []
            current_chars = 0
            if len(chunks) >= PAPER_NOTE_CHUNK_MAX_CHUNKS:
                break
        current.append(anchor)
        current_chars += text_chars
    if current and len(chunks) < PAPER_NOTE_CHUNK_MAX_CHUNKS:
        chunks.append(current)

    source_token = _safe_token(candidate.get("candidateId"), default="source", max_length=48)
    planned_chunks: list[dict[str, Any]] = []
    for index, chunk_anchors in enumerate(chunks, start=1):
        pages = [int(anchor.get("page") or 0) for anchor in chunk_anchors if int(anchor.get("page") or 0) > 0]
        page_scope = _page_scope_from_anchors(chunk_anchors)
        anchor_ids = [_source_extraction_anchor_id(candidate, anchor) for anchor in chunk_anchors]
        excerpt = _excerpt_from_page_anchors(chunk_anchors, max_chars=min(max_chars_per_chunk, 2000))
        planned_chunks.append(
            {
                "chunkId": f"{source_token}-chunk-{index:02d}",
                "chunkIndex": index,
                "status": "planned",
                "taskType": "paper_note_draft",
                "workflowNode": "paper_note",
                "pageStart": min(pages) if pages else 0,
                "pageEnd": max(pages) if pages else 0,
                "pageScope": page_scope,
                "anchorIds": anchor_ids,
                "evidenceRefs": _source_extraction_evidence_refs(candidate, {"pageAnchors": chunk_anchors}),
                "excerptChars": sum(len(_trim_text(anchor.get("text"), max_length=max_chars_per_chunk)) for anchor in chunk_anchors),
                "excerptPreview": _trim_text(excerpt, max_length=700),
                "paperNoteCandidateId": "",
                "taskId": "",
                "updatedAt": "",
            }
        )
    return planned_chunks


def _source_extraction_anchor_id(candidate: dict[str, Any], anchor: dict[str, Any]) -> str:
    page = int(anchor.get("page") or 0)
    source_token = _safe_token(candidate.get("candidateId"), default="source", max_length=48)
    return _trim_text(anchor.get("id"), max_length=240) or f"{source_token}-p{page}"


def _paper_note_chunk_by_id(candidate: dict[str, Any], chunk_id: str) -> dict[str, Any] | None:
    plan = _candidate_paper_note_chunk_plan(candidate)
    if plan is None:
        return None
    for chunk in list(plan.get("chunks") or []):
        if isinstance(chunk, dict) and str(chunk.get("chunkId") or "") == chunk_id:
            return chunk
    return None


def _page_anchors_for_paper_note_chunk(candidate: dict[str, Any], extraction: dict[str, Any], chunk: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not chunk:
        return []
    anchor_ids = set(_normalize_id_values(chunk.get("anchorIds")))
    return [
        anchor
        for anchor in list(extraction.get("pageAnchors") or [])
        if isinstance(anchor, dict) and (_source_extraction_anchor_id(candidate, anchor) in anchor_ids)
    ]


def _update_paper_note_chunk_plan_progress(
    value: Any,
    *,
    chunk_id: str,
    paper_note_candidate_id: str,
    task_id: str,
    valid: bool,
    updated_at: str,
) -> dict[str, Any]:
    plan = value if isinstance(value, dict) else {}
    chunks: list[dict[str, Any]] = []
    for item in list(plan.get("chunks") or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("chunkId") or "") == chunk_id:
            item = {
                **item,
                "status": "drafted" if valid else "needs_revision",
                "paperNoteCandidateId": paper_note_candidate_id,
                "taskId": task_id,
                "updatedAt": updated_at,
            }
        chunks.append(item)
    drafted_count = sum(1 for item in chunks if str(item.get("status") or "") == "drafted")
    needs_revision_count = sum(1 for item in chunks if str(item.get("status") or "") == "needs_revision")
    next_plan = {
        **plan,
        "chunks": chunks,
        "chunkCount": len(chunks),
        "completedChunkCount": drafted_count,
        "needsRevisionChunkCount": needs_revision_count,
        "status": _paper_note_chunk_plan_status(chunks),
        "updatedAt": updated_at,
    }
    return next_plan


def _paper_note_chunk_plan_status(chunks: list[dict[str, Any]]) -> str:
    if not chunks:
        return "empty"
    statuses = {str(item.get("status") or "") for item in chunks}
    if statuses <= {"drafted"}:
        return "drafted"
    if "needs_revision" in statuses:
        return "needs_revision"
    if "drafted" in statuses:
        return "drafting"
    return "planned"


def _source_candidate_has_ready_extraction(candidate: dict[str, Any]) -> bool:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    extraction = metadata.get("sourceExtraction") if isinstance(metadata.get("sourceExtraction"), dict) else {}
    return extraction.get("status") == "extracted" and isinstance(extraction.get("pageAnchors"), list) and bool(extraction.get("pageAnchors"))


def _candidate_paper_note_chunk_plan(candidate: dict[str, Any]) -> dict[str, Any] | None:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    plan = metadata.get("paperNoteChunkPlan") if isinstance(metadata.get("paperNoteChunkPlan"), dict) else None
    return plan


def _paper_note_chunk_plan_summary(candidate: dict[str, Any]) -> dict[str, Any] | None:
    plan = _candidate_paper_note_chunk_plan(candidate)
    if plan is None:
        return None
    chunks = [item for item in list(plan.get("chunks") or []) if isinstance(item, dict)]
    drafted_count = sum(1 for item in chunks if str(item.get("status") or "") == "drafted")
    needs_revision_count = sum(1 for item in chunks if str(item.get("status") or "") == "needs_revision")
    return {
        "planId": str(plan.get("planId") or ""),
        "status": _paper_note_chunk_plan_status(chunks),
        "sourceCandidateId": str(candidate.get("candidateId") or ""),
        "sourceTitle": str(candidate.get("title") or _source_manifest_label(candidate)),
        "sourceSha256": str(plan.get("sourceSha256") or ""),
        "chunkCount": len(chunks),
        "draftedChunkCount": drafted_count,
        "needsRevisionChunkCount": needs_revision_count,
        "openChunkCount": max(0, len(chunks) - drafted_count - needs_revision_count),
        "pageScope": str(plan.get("pageScope") or ""),
        "chunks": [
            {
                "chunkId": str(item.get("chunkId") or ""),
                "chunkIndex": int(item.get("chunkIndex") or 0),
                "status": str(item.get("status") or ""),
                "pageScope": str(item.get("pageScope") or ""),
                "excerptChars": int(item.get("excerptChars") or 0),
                "paperNoteCandidateId": str(item.get("paperNoteCandidateId") or ""),
                "taskId": str(item.get("taskId") or ""),
            }
            for item in chunks[:12]
        ],
        "createdAt": str(plan.get("createdAt") or ""),
        "updatedAt": str(plan.get("updatedAt") or plan.get("createdAt") or ""),
    }


def _paper_note_chunk_action_items(
    missing_plan_sources: list[dict[str, Any]],
    plans: list[dict[str, Any]],
    open_count: int,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = [
        {
            "code": "paper_note_chunk_plan_missing",
            "severity": "needs_plan",
            "message": f"{item['title']} 已完成 sourceExtraction，但还没有 paper_note 分块计划。",
            "nextAction": "调用 paper-note-chunks/plan 生成章节或页码窗口计划。",
            "candidateId": item["candidateId"],
        }
        for item in missing_plan_sources[:6]
    ]
    if open_count > 0:
        items.append(
            {
                "code": "paper_note_chunks_waiting_draft",
                "severity": "pending",
                "message": f"还有 {open_count} 个 paper_note chunk 等待 Paper Note Extraction Agent 逐块草稿。",
                "nextAction": "对每个 chunkId 调用 paper-note-draft，保留 page anchors 和模型证据。",
                "candidateId": "",
            }
        )
    for plan in plans:
        if int(plan.get("needsRevisionChunkCount") or 0) > 0:
            items.append(
                {
                    "code": "paper_note_chunk_needs_revision",
                    "severity": "needs_revision",
                    "message": f"{plan.get('sourceTitle') or plan.get('sourceCandidateId')} 有 chunk 草稿需要修订。",
                    "nextAction": "重新对 needs_revision chunk 调用 paper-note-draft 或退回补 citation。",
                    "candidateId": str(plan.get("sourceCandidateId") or ""),
                }
            )
    return items[:12]


def _candidate_source_quality_assessment(candidate: dict[str, Any]) -> dict[str, Any] | None:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    assessment = metadata.get("sourceQualityAssessment") if isinstance(metadata.get("sourceQualityAssessment"), dict) else None
    return assessment


def _source_quality_bucket(candidate: dict[str, Any]) -> str:
    assessment = _candidate_source_quality_assessment(candidate)
    decision = str((assessment or {}).get("decision") or "")
    quality_status = str(candidate.get("qualityStatus") or "")
    current_state = str(candidate.get("currentState") or "")
    if assessment is None and quality_status == "pending_screening":
        return "pending"
    if decision == "approved" or quality_status in SOURCE_QUALITY_APPROVED_STATUSES or current_state == "source_screened":
        return "approved"
    if decision == "rejected" or quality_status in SOURCE_QUALITY_REJECTED_STATUSES or current_state == "rejected":
        return "rejected"
    if decision == "needs_revision" or quality_status in SOURCE_QUALITY_NEEDS_REVISION_STATUSES or current_state in {"source_needs_confirmation", "source_needs_quality_revision"}:
        return "needs_revision"
    return "pending"


def _source_quality_scores(candidate: dict[str, Any], payload: dict[str, Any], validation: dict[str, Any]) -> dict[str, int]:
    defaults = _default_source_quality_scores(candidate, validation)
    scores = {
        "relevance": _payload_score(payload, "relevanceScore", defaults["relevance"]),
        "reliability": _payload_score(payload, "reliabilityScore", defaults["reliability"]),
        "accessibility": _payload_score(payload, "accessibilityScore", defaults["accessibility"]),
        "extractionReadiness": _payload_score(payload, "extractionReadinessScore", defaults["extractionReadiness"]),
    }
    scores["overall"] = int(round(sum(scores.values()) / len(scores)))
    return scores


def _default_source_quality_scores(candidate: dict[str, Any], validation: dict[str, Any]) -> dict[str, int]:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    source_kind = _trim_text(candidate.get("sourceKind"), max_length=80).lower()
    source_url = _trim_text(candidate.get("sourceUrl"), max_length=2000)
    source_path = _trim_text(candidate.get("sourcePath") or metadata.get("sourcePath") or metadata.get("path"), max_length=2000)
    summary = _trim_text(candidate.get("summary") or metadata.get("summary"), max_length=4000)
    title = _trim_text(candidate.get("title"), max_length=240)
    tags = " ".join(_normalize_text_list(candidate.get("tags"), max_items=24, max_length=80)).lower()
    search_text = f"{title} {summary} {tags}".lower()
    neuroscience_terms = ("neuro", "brain", "synaptic", "cortical", "dendritic", "spike", "predictive coding", "神经", "脑", "突触", "皮层")
    algorithm_terms = ("network", "learning", "attention", "memory", "prediction", "algorithm", "模型", "算法", "学习", "注意力", "记忆")
    relevance = 48
    if any(term in search_text for term in neuroscience_terms):
        relevance += 26
    if any(term in search_text for term in algorithm_terms):
        relevance += 16
    if summary:
        relevance += 8
    reliability = 42
    if source_kind in {"pdf", "paper", "review", "preprint", "dataset"}:
        reliability += 18
    if _trim_text(candidate.get("sha256") or metadata.get("sha256") or metadata.get("hash"), max_length=128):
        reliability += 22
    if validation.get("valid"):
        reliability += 16
    accessibility = 35
    if source_url or source_path:
        accessibility += 22
    if candidate.get("allowedForAnalysis") is True or metadata.get("allowedForAnalysis") is True:
        accessibility += 24
    if source_path:
        accessibility += 8
    extraction = metadata.get("sourceExtraction") if isinstance(metadata.get("sourceExtraction"), dict) else {}
    extraction_readiness = 36
    if extraction.get("status") == "extracted" and isinstance(extraction.get("pageAnchors"), list) and extraction.get("pageAnchors"):
        extraction_readiness = 92
    elif extraction.get("status") == "failed":
        extraction_readiness = 18
    elif source_kind and source_kind != "pdf":
        extraction_readiness = 58
    elif source_path:
        extraction_readiness = 46
    return {
        "relevance": _clamp_score(relevance),
        "reliability": _clamp_score(reliability),
        "accessibility": _clamp_score(accessibility),
        "extractionReadiness": _clamp_score(extraction_readiness),
    }


def _payload_score(payload: dict[str, Any], key: str, default: int) -> int:
    if key not in payload or payload.get(key) is None:
        return _clamp_score(default)
    return _clamp_score(_normalize_int(payload.get(key), default=default, minimum=0, maximum=100))


def _clamp_score(value: int) -> int:
    return max(0, min(int(value or 0), 100))


def _default_source_quality_decision(scores: dict[str, int], validation: dict[str, Any]) -> str:
    if not validation.get("valid"):
        return "needs_revision"
    if scores["overall"] >= 70 and min(scores["relevance"], scores["reliability"], scores["accessibility"]) >= 55:
        return "approved"
    return "needs_revision"


def _source_quality_candidate_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    assessment = _candidate_source_quality_assessment(candidate) or {}
    scores = assessment.get("scores") if isinstance(assessment.get("scores"), dict) else {}
    return {
        "candidateId": str(candidate.get("candidateId") or ""),
        "title": str(candidate.get("title") or _source_manifest_label(candidate)),
        "sourceKind": str(candidate.get("sourceKind") or ""),
        "currentState": str(candidate.get("currentState") or ""),
        "qualityStatus": str(candidate.get("qualityStatus") or ""),
        "bucket": _source_quality_bucket(candidate),
        "decision": str(assessment.get("decision") or ""),
        "overallScore": int(scores.get("overall") or 0),
        "scores": {
            "relevance": int(scores.get("relevance") or 0),
            "reliability": int(scores.get("reliability") or 0),
            "accessibility": int(scores.get("accessibility") or 0),
            "extractionReadiness": int(scores.get("extractionReadiness") or 0),
        },
        "hasReadyExtraction": _source_candidate_has_ready_extraction(candidate),
        "requiredFixes": _normalize_text_list(assessment.get("requiredFixes"), max_items=12, max_length=240),
        "riskFlags": _normalize_text_list(assessment.get("riskFlags"), max_items=12, max_length=120),
        "updatedAt": str(candidate.get("updatedAt") or candidate.get("createdAt") or ""),
        "assessedAt": str(assessment.get("assessedAt") or ""),
    }


def _source_quality_batch_assessment_summary(candidate: dict[str, Any], assessment: dict[str, Any]) -> dict[str, Any]:
    scores = assessment.get("scores") if isinstance(assessment.get("scores"), dict) else {}
    return {
        "candidateId": str(candidate.get("candidateId") or assessment.get("candidateId") or ""),
        "title": str(candidate.get("title") or assessment.get("sourceLabel") or ""),
        "assessmentId": str(assessment.get("assessmentId") or ""),
        "decision": str(assessment.get("decision") or ""),
        "overallScore": int(scores.get("overall") or 0),
        "requiredFixes": _normalize_text_list(assessment.get("requiredFixes"), max_items=12, max_length=240),
        "riskFlags": _normalize_text_list(assessment.get("riskFlags"), max_items=12, max_length=120),
        "currentState": str(candidate.get("currentState") or ""),
        "qualityStatus": str(candidate.get("qualityStatus") or ""),
        "assessedAt": str(assessment.get("assessedAt") or ""),
    }


def _source_quality_action_items(
    source_candidates: list[dict[str, Any]],
    unassessed: list[dict[str, Any]],
    needs_revision: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not source_candidates:
        return [
            {
                "code": "source_quality_no_sources",
                "severity": "blocked",
                "message": "还没有 source_manifest 可供资料质量评估。",
                "nextAction": "先启动资料搜索或手工回写 DataRecord 并导入 source_manifest。",
                "candidateId": "",
            }
        ]
    items: list[dict[str, Any]] = [
        {
            "code": "source_quality_pending_assessment",
            "severity": "needs_review",
            "message": f"{item.get('title') or _source_manifest_label(item)} 等待 Source Quality Assessment Agent 筛选。",
            "nextAction": "调用 source-quality/assess，给出 approved 或 needs_revision。",
            "candidateId": str(item.get("candidateId") or ""),
        }
        for item in unassessed[:6]
    ]
    for item in needs_revision[:6]:
        assessment = _candidate_source_quality_assessment(item) or {}
        required_fixes = _normalize_text_list(assessment.get("requiredFixes"), max_items=3, max_length=160)
        items.append(
            {
                "code": "source_quality_needs_revision",
                "severity": "needs_revision",
                "message": f"{item.get('title') or _source_manifest_label(item)} 需要补充资料质量信息。",
                "nextAction": "；".join(required_fixes) if required_fixes else "补来源、权限、sha256、摘要、页码锚点或相关性说明后重新评估。",
                "candidateId": str(item.get("candidateId") or ""),
            }
        )
    return items[:12]


def _source_quality_next_actions(decision: str) -> list[str]:
    if decision == "approved":
        return [
            "Content Extraction Agent can run source-extraction or paper_note chunk planning for this source.",
            "Paper Note Extraction Agent should preserve sourceQualityAssessment as candidate-only evidence.",
        ]
    if decision == "rejected":
        return [
            "Keep this source in rejection_archive and do not use it for paper_note drafting.",
            "Collect replacement sources before continuing the knowledge collection round.",
        ]
    return [
        "Return the source to Source Intake Agent or Source Acquisition Agent for repair.",
        "Re-run source-quality/assess after source path, permission, citation, or relevance gaps are fixed.",
    ]


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
            {"nodeId": "source_screening", "label": "资料审查"},
            {"nodeId": "candidate_ingestion", "label": "资料入库"},
            {"nodeId": "team_memory_ready", "label": "团队知识库已接入"},
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


def _load_experiment_plan_store(team_id: str) -> dict[str, Any]:
    path = _experiment_plan_store_path(team_id)
    if path.exists():
        payload = _read_json(path)
        if payload.get("storeKind") == EXPERIMENT_PLAN_STORE_KIND and isinstance(payload.get("plans"), list):
            return payload
    now = utc_now_iso()
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": team_id,
        "storeKind": EXPERIMENT_PLAN_STORE_KIND,
        "activePlanId": "",
        "plans": [],
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


def _load_data_processing_record(run_id: str, record_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        run = data_processing_service.get_processing_run(run_id)
        records = data_processing_service.list_records(run_id).get("records", [])
    except data_processing_service.DataProcessingNotFoundError as exc:
        raise TeamWorkflowOrchestrationError(str(exc)) from exc
    except data_processing_service.DataProcessingError as exc:
        raise TeamWorkflowOrchestrationError(str(exc)) from exc
    record = next((item for item in records if isinstance(item, dict) and str(item.get("recordId") or "") == record_id), None)
    if record is None:
        raise TeamWorkflowOrchestrationError(f"Data processing record not found: {record_id}")
    return run, record


def _find_candidate_imported_from_data_record(candidate_store: dict[str, Any], run_id: str, record_id: str) -> dict[str, Any] | None:
    for candidate in list(candidate_store.get("candidates") or []):
        if not isinstance(candidate, dict):
            continue
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        imported_from = metadata.get("importedFromDataRecord") if isinstance(metadata.get("importedFromDataRecord"), dict) else {}
        if str(imported_from.get("runId") or "") == run_id and str(imported_from.get("recordId") or "") == record_id:
            return candidate
    return None


def _find_source_candidate_by_identity_key(candidate_store: dict[str, Any], source_identity_key: str) -> dict[str, Any] | None:
    if not source_identity_key:
        return None
    for candidate in list(candidate_store.get("candidates") or []):
        if not isinstance(candidate, dict):
            continue
        if str(candidate.get("candidateType") or "") != "source_manifest" or _candidate_is_archived(candidate):
            continue
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        imported_from = metadata.get("importedFromDataRecord") if isinstance(metadata.get("importedFromDataRecord"), dict) else {}
        if source_identity_key in {
            _trim_text(metadata.get("sourceIdentityKey"), max_length=160),
            _trim_text(imported_from.get("sourceIdentityKey"), max_length=160),
        }:
            return candidate
    return None


def _source_candidate_payload_from_data_record(run: dict[str, Any], record: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    source_type = _trim_text(record.get("sourceType"), max_length=80) or "unknown"
    source_ref = _trim_text(record.get("sourceRef"), max_length=2000)
    raw_location = _trim_text(record.get("rawLocation"), max_length=2000)
    source_kind = _trim_text(payload.get("sourceKind"), max_length=80) or _source_kind_from_data_record(source_type, source_ref, raw_location)
    source_url = _trim_text(payload.get("sourceUrl"), max_length=2000)
    source_path = _trim_text(payload.get("sourcePath"), max_length=2000)
    if not source_url and _looks_like_url(source_ref):
        source_url = source_ref
    if not source_path and not source_url:
        source_path = raw_location or (source_ref if source_type in {"file", "paper", "dataset"} else "")
    title = _trim_text(payload.get("title"), max_length=240) or _trim_text(record.get("title"), max_length=240) or source_ref or raw_location
    if not title and not source_url and not source_path:
        raise TeamWorkflowOrchestrationError("Data processing record cannot be imported without title, sourceRef, or rawLocation.")
    metadata = _normalize_metadata(payload.get("metadata"))
    record_metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    quality_signals = record.get("qualitySignals") if isinstance(record.get("qualitySignals"), dict) else {}
    collection_trace = record.get("collectionTrace") if isinstance(record.get("collectionTrace"), dict) else {}
    source_trace = record_metadata.get("sourceCollectionTrace") if isinstance(record_metadata.get("sourceCollectionTrace"), dict) else collection_trace
    source_category = _source_collection_source_category(
        source_kind=source_kind,
        source_ref=source_ref,
        raw_location=raw_location,
        source_url=source_url,
        source_path=source_path,
    )
    doi = _source_collection_extract_doi(source_ref, source_url, raw_location, record_metadata.get("doi"))
    imported_from = _data_record_ref(run, record)
    metadata.update(
        {
            "importedFromDataRecord": imported_from,
            "dataProcessingQualitySignals": _normalize_metadata(quality_signals),
            "dataProcessingCollectionTrace": _normalize_metadata(collection_trace),
            "dataProcessingRecordMetadata": _normalize_metadata(record_metadata),
            "sourceCollectionTrace": _normalize_metadata(source_trace),
            "sourceRunId": imported_from["runId"],
            "sourceRecordId": imported_from["recordId"],
            "sourceCategory": source_category,
            "sourceRef": source_ref or raw_location,
            "sourceUrl": source_url,
            "sourcePath": source_path,
            "assignmentId": _trim_text(source_trace.get("assignmentId"), max_length=128),
            "agentRole": _trim_text(source_trace.get("agentRole"), max_length=80),
            "queryId": _trim_text(source_trace.get("queryId"), max_length=160),
            "query": _trim_text(source_trace.get("query"), max_length=1000),
            "searchProvider": _trim_text(source_trace.get("searchProvider") or record_metadata.get("searchProvider"), max_length=80),
            "searchUrl": _trim_text(source_trace.get("searchUrl") or record_metadata.get("searchUrl"), max_length=1000),
        }
    )
    if doi:
        metadata["doi"] = doi
        metadata["importedFromDataRecord"]["doi"] = doi
    source_identity_key = _source_collection_record_identity_key(record)
    if source_identity_key:
        metadata["sourceIdentityKey"] = source_identity_key
        metadata["importedFromDataRecord"]["sourceIdentityKey"] = source_identity_key
    return {
        "candidateType": "source_manifest",
        "title": title,
        "sourceUrl": source_url,
        "sourcePath": source_path,
        "sourceKind": source_kind,
        "sha256": _trim_text(payload.get("sha256") or record_metadata.get("sha256"), max_length=128),
        "allowedForAnalysis": _normalize_optional_bool(payload.get("allowedForAnalysis")) if "allowedForAnalysis" in payload else _normalize_optional_bool(record_metadata.get("allowedForAnalysis")),
        "pageScope": _trim_text(payload.get("pageScope") or record_metadata.get("pageScope"), max_length=160),
        "summary": _trim_text(payload.get("summary"), max_length=4000) or _trim_text(record.get("summary"), max_length=4000),
        "tags": _normalize_text_list(payload.get("tags"), max_items=24, max_length=80),
        "evidenceRefs": _data_record_evidence_refs(run, record, payload),
        "metadata": metadata,
        "createdByAgent": _trim_text(payload.get("createdByAgent"), max_length=160) or "data_intake_coordinator",
    }


def _data_record_ref(run: dict[str, Any], record: dict[str, Any]) -> dict[str, str]:
    return {
        "runId": _trim_text(run.get("runId"), max_length=128),
        "recordId": _trim_text(record.get("recordId"), max_length=128),
        "profileId": _trim_text(run.get("profileId"), max_length=128),
        "sourceType": _trim_text(record.get("sourceType"), max_length=80),
        "sourceRef": _trim_text(record.get("sourceRef") or record.get("rawLocation"), max_length=240),
        "title": _trim_text(record.get("title"), max_length=240),
    }


def _data_record_evidence_refs(run: dict[str, Any], record: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, str]]:
    refs = _normalize_ref_list(payload.get("evidenceRefs"), max_items=20)
    refs.append(
        {
            "type": "data_record",
            "id": _trim_text(record.get("recordId"), max_length=240),
            "label": _trim_text(record.get("title"), max_length=240) or _trim_text(record.get("sourceRef"), max_length=240) or "DataRecord",
        }
    )
    run_id = _trim_text(run.get("runId"), max_length=240)
    if run_id:
        refs.append({"type": "data_processing_run", "id": run_id, "label": _trim_text(run.get("title"), max_length=240) or run_id})
    return refs[:24]


def _source_kind_from_data_record(source_type: str, source_ref: str, raw_location: str) -> str:
    if source_type in {"paper", "dataset", "file", "url", "api", "note", "manual"}:
        return source_type
    if _looks_like_url(source_ref):
        return "url"
    if raw_location or source_ref:
        return "file"
    return "unknown"


def _source_collection_extract_doi(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^doi:\s*", "", text, flags=re.IGNORECASE)
        match = re.search(r"10\.\d{4,9}/[^\s\"'<>]+", text, flags=re.IGNORECASE)
        if match:
            return match.group(0).rstrip(").,;")
    return ""


def _source_collection_source_category(
    *,
    source_kind: str,
    source_ref: str,
    raw_location: str,
    source_url: str,
    source_path: str,
) -> str:
    normalized = str(source_kind or "").strip().lower()
    refs = " ".join([source_ref, raw_location, source_url, source_path]).lower()
    if "dataset" in normalized:
        return "dataset"
    if ".pdf" in refs or "application/pdf" in refs:
        return "pdf"
    if source_path and not _looks_like_url(source_path):
        return "local_file"
    if normalized in {"file", "manual", "note"}:
        return "local_file"
    if _source_collection_extract_doi(source_ref, source_url, raw_location) or _looks_like_url(source_ref) or _looks_like_url(source_url):
        return "paper_web"
    return "missing"


def _looks_like_url(value: str) -> bool:
    text = str(value or "").strip().lower()
    return text.startswith("http://") or text.startswith("https://")


def _normalize_source_collection_roles(value: Any) -> list[str]:
    raw_roles = value if isinstance(value, list) else list(SOURCE_COLLECTION_DEFAULT_AGENT_ROLES)
    roles: list[str] = []
    for item in raw_roles[:8]:
        role = _trim_text(item, max_length=80)
        if role in data_processing_service.COLLECTION_AGENT_ROLES and role not in roles:
            roles.append(role)
    return roles or list(SOURCE_COLLECTION_DEFAULT_AGENT_ROLES)


def _source_collection_team_agent_ids(team: dict[str, Any], roles: list[str], payload: dict[str, Any]) -> dict[str, str]:
    explicit_agent_ids = payload.get("agentIds") if isinstance(payload.get("agentIds"), dict) else {}
    mapped: dict[str, str] = {}
    for role in roles:
        explicit = _trim_text(explicit_agent_ids.get(role), max_length=160)
        if explicit:
            mapped[role] = explicit
    canvas = team.get("canvas") if isinstance(team.get("canvas"), dict) else {}
    nodes = canvas.get("nodes") if isinstance(canvas.get("nodes"), list) else []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        role = _trim_text(node.get("role"), max_length=80)
        agent_id = _trim_text(node.get("agentId"), max_length=160)
        if role in roles and agent_id and role not in mapped:
            mapped[role] = agent_id
    return mapped


def _source_collection_owner_agent_id(team: dict[str, Any], payload: dict[str, Any]) -> str:
    explicit = _trim_text(payload.get("ownerAgentId"), max_length=160)
    if explicit:
        return explicit
    canvas = team.get("canvas") if isinstance(team.get("canvas"), dict) else {}
    nodes = canvas.get("nodes") if isinstance(canvas.get("nodes"), list) else []
    preferred_roles = ("research_coordination", "data_intake_coordinator", "ceo", "organization_coordinator")
    for preferred_role in preferred_roles:
        for node in nodes:
            if not isinstance(node, dict):
                continue
            role = _trim_text(node.get("role"), max_length=80)
            agent_id = _trim_text(node.get("agentId"), max_length=160)
            if role == preferred_role and agent_id:
                return agent_id
    return DEFAULT_OWNER_AGENT_ID


def _source_collection_agent_id(role: str, payload: dict[str, Any]) -> str:
    agent_ids = payload.get("agentIds") if isinstance(payload.get("agentIds"), dict) else {}
    explicit = _trim_text(agent_ids.get(role), max_length=160)
    return explicit or role


def _source_collection_agent_role_for_id(assignments: list[dict[str, Any]], agent_id: str, stage_id: str) -> str:
    normalized_agent_id = _trim_text(agent_id, max_length=160)
    allowed_roles = SOURCE_COLLECTION_AGENT_CONTEXT_STAGE_ROLES.get(stage_id, ())
    for assignment in assignments:
        if _trim_text(assignment.get("agentId"), max_length=160) != normalized_agent_id:
            continue
        role = _trim_text(assignment.get("agentRole"), max_length=80)
        if role in allowed_roles:
            return role
    for assignment in assignments:
        role = _trim_text(assignment.get("agentRole"), max_length=80)
        if role in allowed_roles:
            return role
    return allowed_roles[0] if allowed_roles else ""


def _source_collection_prompt_cache_policy(team_id: str, payload: dict[str, Any], roles: list[str]) -> dict[str, Any]:
    raw_policy = payload.get("promptCachePolicy") if isinstance(payload.get("promptCachePolicy"), dict) else {}
    requirement = _normalize_source_collection_prompt_cache_requirement(raw_policy, payload)
    requested_model_id = (
        _trim_text(raw_policy.get("modelId"), max_length=160)
        or _trim_text(payload.get("modelId"), max_length=160)
    )
    model_id, model_entry, model_resolution = _source_collection_resolve_prompt_cache_model(requested_model_id)
    prompt_cache_mode = _source_collection_prompt_cache_mode(model_entry)
    model_name = _trim_text(model_entry.get("model") or model_entry.get("label"), max_length=240) or model_id
    provider_id = _trim_text(model_entry.get("provider_id") or model_entry.get("provider"), max_length=160)
    hard_block = requirement in SOURCE_COLLECTION_PROMPT_CACHE_REQUIRED_MODES
    gate_status = "disabled" if requirement in SOURCE_COLLECTION_PROMPT_CACHE_DISABLED_MODES else "satisfied"
    gate_reason = ""
    if requirement not in SOURCE_COLLECTION_PROMPT_CACHE_DISABLED_MODES and not model_entry:
        gate_status = "blocked" if hard_block else "warning"
        requested_for_message = _trim_text(model_resolution.get("requestedModelId"), max_length=160)
        gate_reason = (
            f"Prompt cache model is not configured: {requested_for_message}"
            if requested_for_message
            else "No prompt-cache-capable model is configured for knowledge collection."
        )
    elif hard_block and prompt_cache_mode not in SOURCE_COLLECTION_SUPPORTED_PROMPT_CACHE_MODES:
        gate_status = "blocked"
        gate_reason = (
            "Knowledge collection requires prompt cache/KV reuse, but "
            f"model `{model_id}` has prompt_cache.mode `{prompt_cache_mode}`."
        )
    elif requirement not in SOURCE_COLLECTION_PROMPT_CACHE_DISABLED_MODES and prompt_cache_mode not in SOURCE_COLLECTION_SUPPORTED_PROMPT_CACHE_MODES:
        gate_status = "warning"
        gate_reason = f"Prompt cache is not guaranteed for model `{model_id}`."
    role_partitions = [
        {
            "agentRole": role,
            "agentId": _source_collection_agent_id(role, payload),
            "promptCachePartition": _source_collection_prompt_cache_partition(team_id, role, model_id=model_id),
        }
        for role in roles
    ]
    policy = {
        "schemaVersion": SCHEMA_VERSION,
        "policyId": _new_record_id("cachepolicy"),
        "policyKind": "source_collection_prompt_cache_policy",
        "scope": SOURCE_COLLECTION_PROMPT_CACHE_SCOPE,
        "requirement": requirement,
        "modelId": model_id,
        "modelName": model_name,
        "providerId": provider_id,
        "promptCacheMode": prompt_cache_mode,
        "modelResolution": model_resolution,
        "supportedPromptCacheModes": sorted(SOURCE_COLLECTION_SUPPORTED_PROMPT_CACHE_MODES),
        "partitionTemplate": "research-team:{teamId}:knowledge_collection:{agentRole}:{modelId}",
        "rolePartitions": role_partitions,
        "stablePrefixContract": _source_collection_stable_prefix_contract(),
        "dynamicDeltaContract": _source_collection_dynamic_delta_contract(),
        "gate": {
            "status": gate_status,
            "passed": gate_status in {"satisfied", "disabled", "warning"},
            "hardBlock": hard_block,
            "reason": gate_reason,
            "checkedAt": utc_now_iso(),
        },
    }
    if gate_status == "blocked":
        _record_workflow_event(
            "source_collection.prompt_cache_blocked",
            team_id,
            fields={
                "policyId": policy["policyId"],
                "requirement": requirement,
                "modelId": model_id,
                "requestedModelId": model_resolution.get("requestedModelId", ""),
                "modelResolutionStatus": model_resolution.get("status", ""),
                "promptCacheMode": prompt_cache_mode,
                "outcome": "blocked",
                "reason": gate_reason,
            },
        )
        raise TeamWorkflowOrchestrationError(
            f"{gate_reason} Knowledge collection requires prompt cache/KV reuse. "
            "Set prompt_cache.mode to automatic or explicit_cache_control before starting knowledge collection."
        )
    return policy


def _normalize_source_collection_prompt_cache_requirement(raw_policy: dict[str, Any], payload: dict[str, Any]) -> str:
    raw = (
        _trim_text(raw_policy.get("requirement"), max_length=80)
        or _trim_text(raw_policy.get("mode"), max_length=80)
        or _trim_text(payload.get("promptCacheRequirement"), max_length=80)
        or "required_for_llm_execution"
    ).lower()
    if raw in SOURCE_COLLECTION_PROMPT_CACHE_DISABLED_MODES:
        return "disabled"
    if raw in {"advisory", "optional", "warn", "warning"}:
        return "advisory"
    return "required_for_llm_execution"


def _source_collection_model_library() -> dict[str, Any]:
    try:
        public_config = load_public_config()
    except Exception:
        public_config = {}
    llm = public_config.get("llm") if isinstance(public_config, dict) else {}
    model_library = llm.get("model_library") if isinstance(llm, dict) else {}
    return dict(model_library) if isinstance(model_library, dict) else {}


def _source_collection_prompt_cache_mode(model_entry: dict[str, Any]) -> str:
    prompt_cache = model_entry.get("prompt_cache") if isinstance(model_entry.get("prompt_cache"), dict) else {}
    return _trim_text(prompt_cache.get("mode"), max_length=80).lower() or "disabled"


def _source_collection_is_text_model(model_id: str, model_entry: dict[str, Any]) -> bool:
    descriptor = " ".join(
        [
            str(model_id or ""),
            str(model_entry.get("model") or ""),
            str(model_entry.get("label") or ""),
            str(model_entry.get("transport") or ""),
        ]
    ).lower()
    if "image2" in descriptor or "image" in descriptor:
        return False
    return True


def _source_collection_prompt_cache_model_score(model_id: str, model_entry: dict[str, Any]) -> tuple[int, str]:
    descriptor = " ".join(
        [
            str(model_id or ""),
            str(model_entry.get("model") or ""),
            str(model_entry.get("label") or ""),
            str((model_entry.get("provider") or {}).get("kind") if isinstance(model_entry.get("provider"), dict) else model_entry.get("provider") or ""),
        ]
    ).lower()
    score = 0
    if _source_collection_is_text_model(model_id, model_entry):
        score += 100
    if "qwen" in descriptor or "local" in descriptor:
        score += 30
    if "relay" in descriptor or "openai" in descriptor or "gpt" in descriptor:
        score += 20
    return (-score, str(model_id or ""))


def _source_collection_resolve_prompt_cache_model(requested_model_id: str) -> tuple[str, dict[str, Any], dict[str, Any]]:
    model_library = _source_collection_model_library()
    requested_entry = model_library.get(requested_model_id) if requested_model_id else {}
    if isinstance(requested_entry, dict) and _source_collection_prompt_cache_mode(requested_entry) in SOURCE_COLLECTION_SUPPORTED_PROMPT_CACHE_MODES:
        return requested_model_id, dict(requested_entry), {
            "status": "requested",
            "requestedModelId": requested_model_id,
            "reason": "",
        }

    candidates: list[tuple[tuple[int, str], str, dict[str, Any]]] = []
    for candidate_id, candidate_entry in model_library.items():
        if not isinstance(candidate_entry, dict):
            continue
        if _source_collection_prompt_cache_mode(candidate_entry) not in SOURCE_COLLECTION_SUPPORTED_PROMPT_CACHE_MODES:
            continue
        if not _source_collection_is_text_model(str(candidate_id), candidate_entry):
            continue
        candidates.append((_source_collection_prompt_cache_model_score(str(candidate_id), candidate_entry), str(candidate_id), dict(candidate_entry)))
    if candidates:
        candidates.sort(key=lambda item: item[0])
        resolved_id = candidates[0][1]
        resolved_entry = candidates[0][2]
        return resolved_id, resolved_entry, {
            "status": "fallback" if requested_model_id and resolved_id != requested_model_id else "auto",
            "requestedModelId": requested_model_id,
            "reason": "requested_model_unavailable" if requested_model_id and not requested_entry else "requested_model_prompt_cache_unsupported" if requested_model_id else "auto_selected",
        }

    if isinstance(requested_entry, dict) and requested_entry:
        return requested_model_id, dict(requested_entry), {
            "status": "unavailable",
            "requestedModelId": requested_model_id,
            "reason": "requested_model_prompt_cache_unsupported",
        }
    return requested_model_id, {}, {
        "status": "unavailable",
        "requestedModelId": requested_model_id,
        "reason": "requested_model_not_configured" if requested_model_id else "no_prompt_cache_model_configured",
    }


def _source_collection_prompt_cache_partition(team_id: str, role: str, *, model_id: str) -> str:
    normalized_role = _SAFE_ID_FRAGMENT.sub("-", str(role or "agent").strip().lower()).strip("-") or "agent"
    raw = "|".join(
        [
            SOURCE_COLLECTION_PROMPT_CACHE_SCOPE,
            str(team_id or "").strip(),
            str(role or "").strip(),
            str(model_id or "").strip(),
        ]
    )
    digest = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:12]
    return developer_sandbox.sandbox_prompt_cache_partition(
        f"research-team-{normalized_role}-{digest}",
        surface="team",
        project_root=PROJECT_ROOT,
    )


def _source_collection_prompt_cache_policy_ref(policy: dict[str, Any]) -> dict[str, Any]:
    gate = policy.get("gate") if isinstance(policy.get("gate"), dict) else {}
    return {
        "policyId": _trim_text(policy.get("policyId"), max_length=160),
        "scope": _trim_text(policy.get("scope"), max_length=120),
        "requirement": _trim_text(policy.get("requirement"), max_length=80),
        "modelId": _trim_text(policy.get("modelId"), max_length=160),
        "promptCacheMode": _trim_text(policy.get("promptCacheMode"), max_length=80),
        "gateStatus": _trim_text(gate.get("status"), max_length=80),
    }


def _source_collection_stable_prefix_contract() -> dict[str, Any]:
    return {
        "cacheableBlocks": [
            "ai科学研究团队身份与知识搜集阶段规则",
            "source collection assignment/output/DataRecord/source_manifest schema",
            "禁止直接写正式 Team Knowledge/RAG/official graph 的边界",
            "功能 Agent 职责、回写合同和质量审查规则",
        ],
        "forbiddenDynamicFields": [
            "currentQuery",
            "currentUrl",
            "downloadedText",
            "rawPageContent",
            "latestToolResult",
            "fullConversationHistory",
        ],
        "expectedUsage": "Stable prefix is cacheable; each step sends only the current query/result refs as dynamic delta.",
    }


def _source_collection_dynamic_delta_contract() -> dict[str, Any]:
    return {
        "allowedFields": [
            "queryId",
            "query",
            "sourceRef",
            "rawLocation",
            "resultSummary",
            "recordId",
            "collectionTrace",
            "cacheObservation",
        ],
        "maxRawContentPolicy": "Do not replay full pages; store artifacts as DataRecord/source refs and pass excerpts or summaries only.",
        "conversationTraceRequired": True,
    }


def _source_collection_assignment_scope(role: str, base_scope: dict[str, Any], *, search_plan: dict[str, Any] | None = None) -> dict[str, Any]:
    role_purposes = {
        "data_intake_coordinator": "Coordinate source collection and handoff to source_manifest import.",
        "data_discovery": "Find candidate source references under the run scope.",
        "source_acquisition": "Acquire source handles, local paths, URLs, or API references.",
        "content_extraction": "Extract readable content and metadata into DataRecords.",
        "source_deduplication": "Detect duplicate or version-related source records.",
        "source_quality": "Score reliability, completeness, and processing risk.",
        "intake_review": "Review collected records before challenge-cup candidate import.",
    }
    scope = {
        **base_scope,
        "agentRole": role,
        "rolePurpose": role_purposes.get(role, "Collect data records for downstream processing."),
    }
    if isinstance(search_plan, dict):
        assigned_queries = _source_collection_queries_for_role(search_plan, role)
        prompt_cache_policy = search_plan.get("promptCachePolicy") if isinstance(search_plan.get("promptCachePolicy"), dict) else {}
        scope["dataSearchPlanRef"] = _source_collection_search_plan_ref(search_plan)
        scope["assignedQueries"] = assigned_queries
        scope["queryCount"] = len(assigned_queries)
        scope["resultWritebackContract"] = search_plan.get("resultWritebackContract", {})
        scope["promptCachePolicyRef"] = _source_collection_prompt_cache_policy_ref(prompt_cache_policy)
        scope["promptCachePartition"] = _source_collection_prompt_cache_partition(
            str(base_scope.get("teamId") or search_plan.get("teamId") or ""),
            role,
            model_id=str(prompt_cache_policy.get("modelId") or ""),
        )
        scope["conversationTraceRequired"] = bool((prompt_cache_policy.get("dynamicDeltaContract") or {}).get("conversationTraceRequired", True))
    return scope


def _build_source_collection_search_plan(
    *,
    team_id: str,
    run_id: str,
    payload: dict[str, Any],
    scope: dict[str, Any],
    input_refs: list[str],
    roles: list[str],
    prompt_cache_policy: dict[str, Any],
    plan_id: str = "",
) -> dict[str, Any]:
    normalized_plan_id = _trim_text(plan_id, max_length=128) or _new_record_id("searchplan")
    topic = _trim_text(scope.get("topic") or payload.get("topic"), max_length=500)
    goal = _trim_text(scope.get("goal") or payload.get("goal"), max_length=1000)
    query_seeds = _source_collection_query_seeds(payload, scope, input_refs, topic=topic, goal=goal)
    languages = _source_collection_search_languages(payload.get("searchLanguages"))
    source_types = _source_collection_source_types(payload.get("sourceTypes"))
    max_results = _normalize_int(
        payload.get("maxResultsPerQuery"),
        default=SOURCE_COLLECTION_DEFAULT_MAX_RESULTS_PER_QUERY,
        minimum=1,
        maximum=100,
    )
    role_cycle = roles or list(SOURCE_COLLECTION_DEFAULT_AGENT_ROLES)
    queries: list[dict[str, Any]] = []
    for seed in query_seeds:
        for source_type in source_types:
            for language in languages:
                if len(queries) >= SOURCE_COLLECTION_MAX_QUERIES:
                    break
                assigned_role = role_cycle[len(queries) % len(role_cycle)]
                query_id = f"{normalized_plan_id}-q{len(queries) + 1:03d}"
                queries.append(
                    {
                        "queryId": query_id,
                        "query": _source_collection_query_text(seed, source_type=source_type, language=language),
                        "seed": seed,
                        "language": language,
                        "sourceType": source_type,
                        "assignedAgentRole": assigned_role,
                        "maxResults": max_results,
                        "status": "planned",
                        "execution": {
                            "mode": "contract_only",
                            "externalSearchTriggered": False,
                            "conversationTraceRequired": True,
                            "promptCacheRequired": prompt_cache_policy.get("requirement") in SOURCE_COLLECTION_PROMPT_CACHE_REQUIRED_MODES,
                            "promptCachePartition": _source_collection_prompt_cache_partition(
                                team_id,
                                assigned_role,
                                model_id=str(prompt_cache_policy.get("modelId") or ""),
                            ),
                        },
                        "writeback": {
                            "target": "CollectionOutput.records",
                            "recordStatus": "collected",
                            "candidateImportTarget": "source_manifest",
                        },
                    }
                )
            if len(queries) >= SOURCE_COLLECTION_MAX_QUERIES:
                break
        if len(queries) >= SOURCE_COLLECTION_MAX_QUERIES:
            break
    writeback_contract = _source_collection_writeback_contract(team_id, run_id)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "planId": normalized_plan_id,
        "planKind": "source_collection_data_search",
        "status": "planned",
        "teamId": team_id,
        "runId": run_id,
        "topic": topic,
        "goal": goal,
        "querySeeds": query_seeds,
        "queryCount": len(queries),
        "sourceTypes": source_types,
        "searchLanguages": languages,
        "maxResultsPerQuery": max_results,
        "queries": queries,
        "promptCachePolicy": prompt_cache_policy,
        "roleAssignmentInputs": _source_collection_role_assignment_inputs(queries, roles, payload),
        "resultWritebackContract": writeback_contract,
        "boundaries": {
            "externalSearchTriggered": False,
            "writesFormalKnowledge": False,
            "writesRag": False,
            "writesKnowledgeGraph": False,
            "requiresPromptCacheForAgentExecution": prompt_cache_policy.get("requirement") in SOURCE_COLLECTION_PROMPT_CACHE_REQUIRED_MODES,
        },
    }


def _source_collection_search_plan_ref(search_plan: dict[str, Any]) -> dict[str, Any]:
    prompt_cache_policy = search_plan.get("promptCachePolicy") if isinstance(search_plan.get("promptCachePolicy"), dict) else {}
    return {
        "planId": _trim_text(search_plan.get("planId"), max_length=128),
        "planKind": _trim_text(search_plan.get("planKind"), max_length=120) or "source_collection_data_search",
        "status": _trim_text(search_plan.get("status"), max_length=80) or "planned",
        "queryCount": _normalize_int(search_plan.get("queryCount"), default=0, minimum=0, maximum=SOURCE_COLLECTION_MAX_QUERIES),
        "externalSearchTriggered": False,
        "promptCachePolicyId": _trim_text(prompt_cache_policy.get("policyId"), max_length=160),
        "promptCacheRequirement": _trim_text(prompt_cache_policy.get("requirement"), max_length=80),
        "promptCacheGateStatus": _trim_text((prompt_cache_policy.get("gate") or {}).get("status") if isinstance(prompt_cache_policy.get("gate"), dict) else "", max_length=80),
    }


def _source_collection_writeback_contract(team_id: str, run_id: str) -> dict[str, Any]:
    run_ref = _trim_text(run_id, max_length=128) or "{runId}"
    return {
        "schemaVersion": SCHEMA_VERSION,
        "target": "data_processing.collection_output.records",
        "recordContract": {
            "requiredAnyOf": ["sourceRef", "rawLocation", "title"],
            "recordFields": ["sourceType", "sourceRef", "rawLocation", "title", "summary", "metadata", "qualitySignals", "collectionTrace"],
            "collectionTraceFields": ["planId", "queryId", "assignmentId", "agentRole"],
        },
        "candidateImport": {
            "targetCandidateType": "source_manifest",
            "route": f"/api/teams/{team_id}/workflow-orchestration/data-processing/runs/{run_ref}/records/{{recordId}}/source-candidate",
            "idempotencyKey": "metadata.importedFromDataRecord.recordId",
        },
        "formalKnowledgeWrites": False,
        "ragWrites": False,
        "officialGraphWrites": False,
    }


def _source_collection_assigned_queries(assignment: dict[str, Any]) -> list[dict[str, Any]]:
    scope = assignment.get("scope") if isinstance(assignment.get("scope"), dict) else {}
    return [item for item in list(scope.get("assignedQueries") or []) if isinstance(item, dict)]


def _source_collection_open_assignments(assignments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        item for item in assignments
        if str(item.get("status") or "").strip().lower() in {"open", "in_progress", "returned"}
    ]


def _source_collection_assignment_stage_summary(assignments: list[dict[str, Any]]) -> dict[str, int]:
    open_assignments = _source_collection_open_assignments(assignments)
    search_assignments = [
        item for item in assignments
        if _trim_text(item.get("agentRole"), max_length=80) in SOURCE_COLLECTION_SEARCH_EXECUTION_AGENT_ROLES
    ]
    search_open_assignments = [
        item for item in open_assignments
        if _trim_text(item.get("agentRole"), max_length=80) in SOURCE_COLLECTION_SEARCH_EXECUTION_AGENT_ROLES
    ]
    collection_assignments = [
        item for item in assignments
        if _trim_text(item.get("agentRole"), max_length=80) in SOURCE_COLLECTION_COLLECTION_STAGE_AGENT_ROLES
    ]
    collection_open_assignments = [
        item for item in open_assignments
        if _trim_text(item.get("agentRole"), max_length=80) in SOURCE_COLLECTION_COLLECTION_STAGE_AGENT_ROLES
    ]
    downstream_assignments = [
        item for item in assignments
        if _trim_text(item.get("agentRole"), max_length=80) not in SOURCE_COLLECTION_SEARCH_EXECUTION_AGENT_ROLES
    ]
    downstream_open_assignments = [
        item for item in open_assignments
        if _trim_text(item.get("agentRole"), max_length=80) not in SOURCE_COLLECTION_SEARCH_EXECUTION_AGENT_ROLES
    ]
    return {
        "assignmentCount": len(assignments),
        "openAssignmentCount": len(open_assignments),
        "searchAssignmentCount": len(search_assignments),
        "searchOpenAssignmentCount": len(search_open_assignments),
        "collectionAssignmentCount": len(collection_assignments),
        "collectionOpenAssignmentCount": len(collection_open_assignments),
        "downstreamAssignmentCount": len(downstream_assignments),
        "downstreamOpenAssignmentCount": len(downstream_open_assignments),
    }


def _source_collection_existing_query_ids(records: list[dict[str, Any]]) -> set[str]:
    query_ids: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        traces = [
            record.get("collectionTrace") if isinstance(record.get("collectionTrace"), dict) else {},
            metadata.get("sourceCollectionTrace") if isinstance(metadata.get("sourceCollectionTrace"), dict) else {},
        ]
        for trace in traces:
            query_id = _trim_text(trace.get("queryId"), max_length=160)
            if query_id:
                query_ids.add(query_id)
    return query_ids


def _source_collection_existing_identity_records(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        source_identity_key = _source_collection_record_identity_key(record)
        if source_identity_key and source_identity_key not in by_key:
            by_key[source_identity_key] = record
    return by_key


def _source_collection_record_identity_key(record: dict[str, Any]) -> str:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    quality_signals = record.get("qualitySignals") if isinstance(record.get("qualitySignals"), dict) else {}
    existing = _trim_text(metadata.get("sourceIdentityKey") or quality_signals.get("sourceIdentityKey"), max_length=160)
    if existing:
        return existing
    return _source_collection_identity_key(
        source_ref=record.get("sourceRef"),
        raw_location=record.get("rawLocation"),
        doi=metadata.get("doi") or quality_signals.get("doi"),
        url=metadata.get("url") or quality_signals.get("url"),
        title=record.get("title"),
        container=metadata.get("containerTitle") or metadata.get("container") or quality_signals.get("containerTitle") or quality_signals.get("container"),
        published=metadata.get("issued") or metadata.get("published") or quality_signals.get("issued") or quality_signals.get("published"),
    )


def _source_collection_result_identity_key(result: dict[str, Any]) -> str:
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    quality_signals = result.get("qualitySignals") if isinstance(result.get("qualitySignals"), dict) else {}
    return _source_collection_identity_key(
        source_ref=result.get("sourceRef"),
        raw_location=result.get("rawLocation"),
        doi=metadata.get("doi") or result.get("doi") or quality_signals.get("doi"),
        url=metadata.get("url") or result.get("url") or quality_signals.get("url"),
        title=result.get("title"),
        container=result.get("container") or metadata.get("containerTitle") or metadata.get("container") or quality_signals.get("containerTitle") or quality_signals.get("container"),
        published=result.get("published") or metadata.get("issued") or metadata.get("published") or quality_signals.get("issued") or quality_signals.get("published"),
    )


def _source_collection_identity_key(
    *,
    source_ref: Any,
    raw_location: Any,
    doi: Any = "",
    url: Any = "",
    title: Any,
    container: Any = "",
    published: Any = "",
) -> str:
    for value in (doi, source_ref, raw_location):
        doi = _source_collection_normalized_doi(value)
        if doi:
            return f"doi:{doi}"
    for value in (url, source_ref, raw_location):
        url_key = _source_collection_normalized_url(value)
        if url_key:
            return f"url:{url_key}"
    normalized_title = re.sub(r"\s+", " ", _trim_text(title, max_length=260).lower()).strip()
    if len(normalized_title) < 16:
        return ""
    normalized_container = re.sub(r"\s+", " ", _trim_text(container, max_length=160).lower()).strip()
    year_match = re.search(r"(19|20)\d{2}", _trim_text(published, max_length=80))
    if not normalized_container and not year_match:
        return ""
    fingerprint_source = "|".join([normalized_title, normalized_container, year_match.group(0) if year_match else ""])
    return f"title:{hashlib.sha256(fingerprint_source.encode('utf-8')).hexdigest()[:24]}"


def _source_collection_normalized_doi(value: Any) -> str:
    text = _trim_text(value, max_length=1000).strip()
    if not text:
        return ""
    match = re.search(r"10\.\d{4,9}/[^\s\"'<>]+", text, flags=re.IGNORECASE)
    if not match:
        return ""
    return match.group(0).rstrip(".,;)").lower()


def _source_collection_normalized_url(value: Any) -> str:
    text = _trim_text(value, max_length=1000).strip()
    if not _looks_like_url(text):
        return ""
    try:
        parsed = urllib.parse.urlsplit(text)
    except ValueError:
        return ""
    scheme = parsed.scheme.lower() or "https"
    netloc = parsed.netloc.lower()
    if not netloc:
        return ""
    query_pairs = sorted(
        [
        (key, val)
        for key, val in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid", "yclid", "mc_cid", "mc_eid"}
        ]
    )
    query = urllib.parse.urlencode(query_pairs, doseq=True)
    path = parsed.path.rstrip("/") or "/"
    return urllib.parse.urlunsplit((scheme, netloc, path, query, ""))


def _execute_source_collection_query(query: dict[str, Any], *, max_results: int, provider: str) -> dict[str, Any]:
    if provider != SOURCE_COLLECTION_SEARCH_PROVIDER_CROSSREF:
        return {"provider": provider, "results": [], "error": f"Unsupported provider: {provider}"}
    query_text = _trim_text(query.get("query"), max_length=1000)
    if not query_text:
        return {"provider": provider, "results": [], "error": "Search query is empty."}
    rows = _normalize_int(max_results, default=SOURCE_COLLECTION_SEARCH_EXECUTION_DEFAULT_RESULTS_PER_QUERY, minimum=1, maximum=SOURCE_COLLECTION_SEARCH_EXECUTION_MAX_RESULTS_PER_QUERY)
    search_url = _crossref_search_url(query_text, rows=rows)
    try:
        request = urllib.request.Request(
            search_url,
            headers={
                "Accept": "application/json",
                "User-Agent": "Vibelution-ChallengeCup/1.0 (metadata-only research source collection)",
            },
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return {"provider": provider, "searchUrl": search_url, "results": [], "error": str(exc)}
    message = payload.get("message") if isinstance(payload, dict) else {}
    items = message.get("items") if isinstance(message, dict) else []
    results = [_source_collection_result_from_crossref_item(item, fallback_source_type=str(query.get("sourceType") or "")) for item in list(items or [])[:rows] if isinstance(item, dict)]
    return {"provider": provider, "searchUrl": search_url, "results": [item for item in results if item.get("title") or item.get("sourceRef") or item.get("rawLocation")]}


def _crossref_search_url(query_text: str, *, rows: int) -> str:
    params = urllib.parse.urlencode(
        {
            "query": query_text,
            "rows": str(rows),
            "select": "DOI,title,URL,container-title,published-print,published-online,issued,author,type,abstract,score",
        }
    )
    return f"https://api.crossref.org/works?{params}"


def _source_collection_result_from_crossref_item(item: dict[str, Any], *, fallback_source_type: str) -> dict[str, Any]:
    doi = _trim_text(item.get("DOI"), max_length=500)
    source_ref = f"https://doi.org/{doi}" if doi else _trim_text(item.get("URL"), max_length=1000)
    title = _first_crossref_text(item.get("title")) or doi or source_ref
    container_title = _first_crossref_text(item.get("container-title"))
    issued = _crossref_date(item.get("published-print")) or _crossref_date(item.get("published-online")) or _crossref_date(item.get("issued"))
    abstract = _strip_html(_trim_text(item.get("abstract"), max_length=5000))
    authors = _crossref_authors(item.get("author"))
    crossref_type = _trim_text(item.get("type"), max_length=80)
    source_type = _source_collection_data_processing_source_type(fallback_source_type or crossref_type)
    summary_parts = [
        f"Container: {container_title}" if container_title else "",
        f"Published: {issued}" if issued else "",
        abstract,
    ]
    return {
        "title": title,
        "sourceRef": source_ref,
        "rawLocation": _trim_text(item.get("URL"), max_length=1000) or source_ref,
        "summary": _trim_text(" ".join(part for part in summary_parts if part), max_length=1600),
        "sourceType": source_type,
        "providerType": crossref_type,
        "metadata": {
            "doi": doi,
            "containerTitle": container_title,
            "issued": issued,
            "authors": authors,
            "crossrefType": crossref_type,
        },
        "qualitySignals": {
            "providerScore": item.get("score"),
            "hasDoi": bool(doi),
            "hasAbstract": bool(abstract),
        },
    }


def _source_collection_record_from_search_result(
    team_id: str,
    run: dict[str, Any],
    assignment: dict[str, Any],
    query: dict[str, Any],
    result: dict[str, Any],
    *,
    provider: str,
    search_url: str,
) -> dict[str, Any]:
    agent_role = _trim_text(assignment.get("agentRole"), max_length=80)
    assignment_id = _trim_text(assignment.get("assignmentId"), max_length=128)
    query_id = _trim_text(query.get("queryId"), max_length=160)
    query_text = _trim_text(query.get("query"), max_length=1000)
    source_ref = _trim_text(result.get("sourceRef"), max_length=1000)
    raw_location = _trim_text(result.get("rawLocation"), max_length=1000) or search_url
    trace = {
        "teamId": team_id,
        "runId": _trim_text(run.get("runId"), max_length=128),
        "planId": _trim_text((query.get("queryId") or "").split("-q", 1)[0], max_length=128),
        "queryId": query_id,
        "query": query_text,
        "assignmentId": assignment_id,
        "agentRole": agent_role,
        "searchProvider": provider,
        "searchUrl": search_url,
        "downloadKind": "metadata",
        "externalSearchTriggered": True,
        "metadataOnlyDownload": True,
        "storageTarget": "data_processing.records",
        "promptCachePartition": _trim_text((query.get("execution") or {}).get("promptCachePartition") if isinstance(query.get("execution"), dict) else "", max_length=160),
    }
    metadata = _normalize_metadata(result.get("metadata"))
    metadata.update(
        {
            "sourceCollectionTrace": trace,
            "searchProvider": provider,
            "searchUrl": search_url,
            "metadataOnlyDownload": True,
        }
    )
    source_identity_key = _source_collection_result_identity_key(result)
    if source_identity_key:
        metadata["sourceIdentityKey"] = source_identity_key
    quality_signals = _normalize_metadata(result.get("qualitySignals"))
    if source_identity_key:
        quality_signals["sourceIdentityKey"] = source_identity_key
        quality_signals["duplicateState"] = "unique_candidate"
    return {
        "sourceType": _source_collection_data_processing_source_type(result.get("sourceType")),
        "sourceRef": source_ref,
        "rawLocation": raw_location,
        "title": _trim_text(result.get("title"), max_length=260) or source_ref or raw_location,
        "summary": _trim_text(result.get("summary"), max_length=4000),
        "status": "collected",
        "metadata": metadata,
        "qualitySignals": quality_signals,
        "collectionTrace": trace,
    }


def _source_collection_record_search_trace(record: dict[str, Any]) -> dict[str, Any]:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    trace = metadata.get("sourceCollectionTrace") if isinstance(metadata.get("sourceCollectionTrace"), dict) else {}
    if trace:
        return trace
    return record.get("collectionTrace") if isinstance(record.get("collectionTrace"), dict) else {}


def _source_collection_execution_event(
    event_type: str,
    *,
    assignment: dict[str, Any],
    title: str,
    summary: str,
    status: str,
    query: dict[str, Any] | None = None,
    refs: list[Any] | None = None,
    raw_location: str = "",
    storage_refs: list[str] | None = None,
) -> dict[str, Any]:
    now = utc_now_iso()
    normalized_query = query if isinstance(query, dict) else {}
    return {
        "eventId": _new_record_id("srcevt"),
        "eventType": event_type,
        "status": _trim_text(status, max_length=80) or "completed",
        "title": _trim_text(title, max_length=260),
        "summary": _trim_text(summary, max_length=1200),
        "agentRole": _trim_text(assignment.get("agentRole"), max_length=80),
        "agentId": _trim_text(assignment.get("agentId"), max_length=160),
        "assignmentId": _trim_text(assignment.get("assignmentId"), max_length=128),
        "queryId": _trim_text(normalized_query.get("queryId"), max_length=160),
        "query": _trim_text(normalized_query.get("query"), max_length=1000),
        "sourceType": _trim_text(normalized_query.get("sourceType"), max_length=80),
        "refs": _normalize_text_list(refs or [], max_items=8, max_length=240),
        "rawLocation": _trim_text(raw_location, max_length=1000),
        "storageRefs": _normalize_text_list(storage_refs or [], max_items=8, max_length=240),
        "createdAt": now,
    }


def _source_collection_storage_refs(run: dict[str, Any]) -> list[str]:
    storage = run.get("storage") if isinstance(run.get("storage"), dict) else {}
    return [
        _trim_text(storage.get("recordsPath"), max_length=240),
        _trim_text(storage.get("collectionOutputsPath"), max_length=240),
    ]


def _source_collection_storage_artifact_paths(team_id: str, run_id: str) -> dict[str, Path]:
    normalized_team_id = _safe_token(team_id, default="team", max_length=96)
    normalized_run_id = _safe_token(run_id, default="run", max_length=96)
    run_directory = _team_workflow_root(normalized_team_id) / "source_collection_runs" / normalized_run_id
    data_processing_directory = developer_sandbox.seeded_sandbox_workspace_path(
        _project_root(),
        "data_processing",
        "runs",
        normalized_run_id,
    )
    return {
        "runDirectory": run_directory,
        "artifactsDirectory": run_directory / "artifacts",
        "searchPlanPath": run_directory / "search_plan.json",
        "searchEventsPath": run_directory / "search_events.jsonl",
        "recordsPath": run_directory / "records.jsonl",
        "candidatesPath": run_directory / "candidates.jsonl",
        "candidateStorePath": _candidate_store_path(normalized_team_id),
        "dataProcessingRunPath": data_processing_directory / "run.json",
        "dataProcessingRecordsPath": data_processing_directory / "records.jsonl",
    }


def _source_collection_stage_session_task_store_path(team_id: str, run_id: str) -> Path:
    return _source_collection_storage_artifact_paths(team_id, run_id)["runDirectory"] / "stage_session_tasks.json"


def _source_collection_storage_artifacts(team_id: str, run_id: str) -> dict[str, str]:
    return {
        key: _relative_path(path)
        for key, path in _source_collection_storage_artifact_paths(team_id, run_id).items()
    }


def _source_collection_candidates_for_run(team_id: str, run_id: str) -> list[dict[str, Any]]:
    normalized_run_id = _trim_text(run_id, max_length=128)
    with _WORKFLOW_LOCK:
        candidate_store = _load_candidate_store(team_id)
    candidates: list[dict[str, Any]] = []
    for item in list(candidate_store.get("candidates") or []):
        if not isinstance(item, dict) or item.get("candidateType") != "source_manifest":
            continue
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        imported_from = metadata.get("importedFromDataRecord") if isinstance(metadata.get("importedFromDataRecord"), dict) else {}
        candidate_run_id = (
            _trim_text(imported_from.get("runId"), max_length=128)
            or _trim_text(metadata.get("sourceCollectionRunId"), max_length=128)
        )
        if candidate_run_id == normalized_run_id:
            candidates.append(item)
    return candidates


def _find_source_collection_context_message(session_id: str, context_key: str) -> dict[str, Any] | None:
    detail = session_service.get_session_detail(session_id)
    if not isinstance(detail, dict):
        raise TeamWorkflowOrchestrationError(f"Session not found: {session_id}")
    for message in reversed(list(detail.get("messages") or [])):
        if not isinstance(message, dict):
            continue
        metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        if (
            str(metadata.get("kind") or "").strip() == "source_collection_agent_context"
            and str(metadata.get("sourceCollectionContextKey") or "").strip() == context_key
        ):
            return message
    return None


def _source_collection_run_context_bundle(team_id: str, run_id: str) -> dict[str, Any]:
    try:
        run = data_processing_service.get_processing_run(run_id)
        assignments_payload = data_processing_service.list_collection_assignments(run_id)
        records_payload = data_processing_service.list_records(run_id)
        run_status = data_processing_service.get_processing_status(run_id)
    except data_processing_service.DataProcessingError as exc:
        raise TeamWorkflowOrchestrationError(str(exc)) from exc
    run_scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
    run_team_id = _trim_text(run_scope.get("teamId"), max_length=128)
    if run_team_id and run_team_id != team_id:
        raise TeamWorkflowOrchestrationError("Data processing run does not belong to this team.")
    assignments = [item for item in list(assignments_payload.get("assignments") or []) if isinstance(item, dict)]
    records = [item for item in list(records_payload.get("records") or []) if isinstance(item, dict)]
    source_candidates = _source_collection_candidates_for_run(team_id, run_id)
    active_snapshot = _source_collection_work_run_store().load_active_snapshot(SOURCE_COLLECTION_WORK_RUN_KIND)
    active_work_run = (
        active_snapshot
        if _source_collection_background_snapshot_is_active(active_snapshot, team_id, run_id)
        else {}
    )
    return {
        "run": run,
        "assignments": assignments,
        "records": records,
        "runStatus": run_status,
        "sourceCandidates": source_candidates,
        "activeWorkRun": active_work_run,
    }


def _source_collection_matching_assignments(
    assignments: list[dict[str, Any]],
    *,
    agent_id: str,
    agent_role: str,
) -> list[dict[str, Any]]:
    return [
        item
        for item in assignments
        if (
            (agent_role and _trim_text(item.get("agentRole"), max_length=80) == agent_role)
            or _trim_text(item.get("agentId"), max_length=160) == agent_id
        )
    ]


def _source_collection_stage_can_materialize_formal_knowledge(stage_id: str, agent_role: str) -> bool:
    return _trim_text(stage_id, max_length=80) == "memory" and _trim_text(agent_role, max_length=80) == "knowledge_steward"


def _source_collection_stage_session_task_boundaries(*, stage_id: str = "", agent_role: str = "") -> dict[str, bool]:
    can_materialize_formal_knowledge = _source_collection_stage_can_materialize_formal_knowledge(stage_id, agent_role)
    return {
        "writesFormalKnowledge": can_materialize_formal_knowledge,
        "writesRag": False,
        "writesOfficialGraph": can_materialize_formal_knowledge,
        "updatesStageTaskResult": True,
        "requiresStructuredWriteback": True,
    }


def _normalize_source_collection_stage_session_task_status(value: Any) -> str:
    normalized = _trim_text(value, max_length=80).lower()
    return normalized if normalized in SOURCE_COLLECTION_STAGE_SESSION_TASK_STATUSES else "needs_review"


def _load_source_collection_stage_session_task_store(team_id: str, run_id: str) -> dict[str, Any]:
    path = _source_collection_stage_session_task_store_path(team_id, run_id)
    if path.exists():
        payload = _read_json(path)
        if isinstance(payload.get("tasks"), list):
            return payload
    now = utc_now_iso()
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": team_id,
        "runId": run_id,
        "storeKind": "source_collection_stage_session_tasks",
        "tasks": [],
        "createdAt": now,
        "updatedAt": now,
    }


def _write_source_collection_stage_session_task_store(team_id: str, run_id: str, store: dict[str, Any]) -> None:
    store["teamId"] = team_id
    store["runId"] = run_id
    store["updatedAt"] = utc_now_iso()
    _write_json(_source_collection_stage_session_task_store_path(team_id, run_id), store)


def _source_collection_stage_session_tasks(team_id: str, run_id: str) -> list[dict[str, Any]]:
    store = _load_source_collection_stage_session_task_store(team_id, run_id)
    return [item for item in list(store.get("tasks") or []) if isinstance(item, dict)]


def _reconcile_source_collection_stage_session_task_turn_status(task: dict[str, Any]) -> dict[str, Any]:
    status = _trim_text(task.get("status"), max_length=80).lower()
    if status not in SOURCE_COLLECTION_STAGE_SESSION_TASK_STATUSES:
        return task
    writeback = task.get("writeback") if isinstance(task.get("writeback"), dict) else {}
    writeback_status = _trim_text(writeback.get("status"), max_length=80).lower() if writeback else ""
    if writeback_status and writeback_status not in SOURCE_COLLECTION_STAGE_SESSION_TASK_STATUSES:
        writeback_status = ""
    settled_status = writeback_status or status
    if settled_status in SOURCE_COLLECTION_STAGE_SESSION_TASK_ACTIVE_STATUSES:
        return task
    turn = task.get("turn") if isinstance(task.get("turn"), dict) else {}
    if not turn or _trim_text(turn.get("status"), max_length=80).lower() == settled_status:
        return task
    next_task = dict(task)
    next_task["status"] = settled_status
    next_turn = dict(turn)
    next_turn["status"] = settled_status
    next_task["turn"] = next_turn
    return next_task


def _reconcile_source_collection_stage_session_tasks(team_id: str) -> bool:
    runs_root = _team_workflow_root(team_id) / "source_collection_runs"
    if not runs_root.exists():
        return False
    changed = False
    for task_store_path in runs_root.glob("*/stage_session_tasks.json"):
        run_id = task_store_path.parent.name
        store = _read_json(task_store_path)
        tasks = [item for item in list(store.get("tasks") or []) if isinstance(item, dict)]
        if not tasks:
            continue
        repaired_round = _repair_missing_source_collection_stage_round(team_id, run_id, tasks)
        changed = repaired_round or changed
        next_tasks: list[dict[str, Any]] = []
        store_changed = False
        for task in tasks:
            reconciled = _reconcile_source_collection_stage_session_task_turn_status(task)
            reconciled = _reconcile_source_collection_stage_session_task_from_turn_result(reconciled)
            reconciled = _reconcile_source_collection_stage_session_task_sources(team_id, run_id, reconciled)
            next_tasks.append(reconciled)
            store_changed = store_changed or reconciled is not task
        if store_changed:
            store["tasks"] = next_tasks
            _write_source_collection_stage_session_task_store(team_id, run_id, store)
            for task in next_tasks:
                if _trim_text(task.get("status"), max_length=80) not in {"running", "queued"}:
                    _sync_stage_round_with_source_collection_stage_task(team_id, run_id, task)
            changed = True
    return changed


def _repair_missing_source_collection_stage_round(team_id: str, run_id: str, tasks: list[dict[str, Any]]) -> bool:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    normalized_run_id = _normalize_required_id(run_id, "Data processing run id is required.")
    try:
        team_service.get_team(normalized_team_id)
        run = data_processing_service.get_processing_run(normalized_run_id)
        assignments_payload = data_processing_service.list_collection_assignments(normalized_run_id)
        run_status = data_processing_service.get_processing_status(normalized_run_id)
    except (team_service.TeamServiceError, data_processing_service.DataProcessingError):
        return False
    scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
    metadata = run.get("metadata") if isinstance(run.get("metadata"), dict) else {}
    if _trim_text(scope.get("teamId") or metadata.get("teamId"), max_length=128) not in {"", normalized_team_id}:
        return False
    if (
        _trim_text(metadata.get("startedFrom"), max_length=160) != "team_workflow_source_collection"
        and _trim_text(scope.get("workflowStage"), max_length=120) != "knowledge_collection"
        and not tasks
    ):
        return False
    with _WORKFLOW_LOCK:
        store = _load_stage_round_store(normalized_team_id)
        rounds = _stage_rounds(store)
        existing = _latest_stage_round(
            [
                item
                for item in rounds
                if str(item.get("stageType") or "") == "knowledge_collection"
                and normalized_run_id in {str(source_run_id) for source_run_id in list(item.get("sourceRunIds") or [])}
            ]
        )
        if existing is not None:
            return False
        workflow = _load_or_create_workflow(normalized_team_id)
        assignments = [
            item for item in list(assignments_payload.get("assignments") or [])
            if isinstance(item, dict)
        ]
        run_status_summary = run_status.get("summary") if isinstance(run_status.get("summary"), dict) else {}
        candidate_store = _load_candidate_store(normalized_team_id)
        run_candidate_count = _source_collection_candidate_count_for_run(candidate_store, normalized_run_id)
        round_number = _normalize_int(scope.get("researchStageRoundNumber"), default=_stage_round_number(rounds, "knowledge_collection"), minimum=1, maximum=10000)
        stage_round_id = (
            _trim_text(scope.get("researchStageRoundId"), max_length=160)
            or _new_record_id("stage-repaired")
        )
        now = utc_now_iso()
        search_execution = {
            "runId": normalized_run_id,
            "status": _trim_text(run.get("status"), max_length=80) or _trim_text(run_status.get("runStatus"), max_length=80),
            "resultStatus": _trim_text(run_status.get("runStatus"), max_length=80),
            "executionMode": "repaired_from_source_run",
            "accepted": False,
            "provider": SOURCE_COLLECTION_SEARCH_PROVIDER_CROSSREF,
            "recordCount": _source_collection_count(run_status_summary.get("recordCount")),
            "remainingQueryCount": _source_collection_count(run_status_summary.get("openAssignmentCount")),
            "summary": "Recovered knowledge-collection stage round from source collection run and stage task records.",
            "updatedAt": now,
        }
        task_refs = _source_collection_stage_task_refs(normalized_run_id, tasks)
        stage_status = _source_collection_stage_round_status_from_task_refs(
            {"status": "running", "sourceCollectionSearchExecution": search_execution},
            task_refs,
        )
        if not task_refs:
            stage_status = _source_collection_stage_round_status_after_search(
                str(search_execution.get("status") or ""),
                result={},
                run_status_summary=run_status_summary,
                source_collection_summary={},
                run_candidate_count=run_candidate_count,
            )
        stage_round = {
            "schemaVersion": SCHEMA_VERSION,
            "stageRoundId": stage_round_id,
            "teamId": normalized_team_id,
            "stageType": "knowledge_collection",
            "roundNumber": round_number,
            "status": stage_status,
            "title": _trim_text(run.get("title"), max_length=180) or f"{RESEARCH_STAGE_DEFAULTS['knowledge_collection']['title']} {round_number}",
            "topic": _trim_text(scope.get("topic") or metadata.get("topic"), max_length=500) or _stage_default_topic("knowledge_collection", None),
            "goal": _trim_text(scope.get("goal") or metadata.get("goal"), max_length=1000) or _stage_default_goal("knowledge_collection", None),
            "requestedByAgent": _trim_text(metadata.get("requestedByAgent"), max_length=160) or DEFAULT_OWNER_AGENT_ID,
            "ownerAgentId": _trim_text(metadata.get("ownerAgentId"), max_length=160) or DEFAULT_OWNER_AGENT_ID,
            "upstreamRoundIds": _normalize_text_list(scope.get("upstreamRoundIds"), max_items=24, max_length=160),
            "sourceRunIds": [normalized_run_id],
            "assignmentIds": [str(item.get("assignmentId") or "") for item in assignments if item.get("assignmentId")],
            "agentRoleAssignments": [
                {
                    "agentRole": str(item.get("agentRole") or ""),
                    "agentId": str(item.get("agentId") or ""),
                    "assignmentId": str(item.get("assignmentId") or ""),
                }
                for item in assignments
            ],
            "querySeeds": _normalize_text_list(scope.get("querySeeds") or metadata.get("querySeeds"), max_items=40, max_length=220),
            "suggestedQuerySeeds": [],
            "inputRefs": _normalize_text_list(scope.get("inputRefs"), max_items=120, max_length=240),
            "searchLanguages": _source_collection_search_languages(scope.get("searchLanguages")),
            "sourceTypes": _source_collection_source_types(scope.get("sourceTypes")),
            "maxResultsPerQuery": _normalize_int(scope.get("maxResultsPerQuery"), default=SOURCE_COLLECTION_DEFAULT_MAX_RESULTS_PER_QUERY, minimum=1, maximum=100),
            "workflowItemRef": {"candidateId": normalized_run_id, "currentNode": "knowledge_collection"},
            "dataSearchPlanRef": scope.get("dataSearchPlanRef") if isinstance(scope.get("dataSearchPlanRef"), dict) else {},
            "sourceCollectionSearchExecution": search_execution,
            "sourceCollectionSummary": {
                "recordCount": _source_collection_count(run_status_summary.get("recordCount")),
                "candidateCount": run_candidate_count,
                "assignmentCount": len(assignments),
                "openAssignmentCount": _source_collection_count(run_status_summary.get("openAssignmentCount")),
            },
            "sourceCollectionStageSessionTasks": task_refs,
            "teamMemoryRecordId": "",
            "teamMemoryRecord": {},
            "coordinationContract": {},
            "planningContract": {},
            "warnings": [
                {
                    "code": "stage_round_repaired_from_source_run",
                    "severity": "info",
                    "message": "Recovered missing knowledge-collection stage round from source collection run/task storage.",
                }
            ],
            "boundaries": _research_stage_boundaries(),
            "createdAt": _trim_text(run.get("createdAt"), max_length=120) or now,
            "updatedAt": now,
        }
        stage_round["teamMemoryRecord"] = _stage_memory_record(stage_round, workflow)
        stage_round["teamMemoryRecordId"] = stage_round["teamMemoryRecord"]["recordId"]
        store["rounds"] = rounds + [stage_round]
        store["updatedAt"] = now
        workflow["activeWorkflowItems"] = _upsert_active_item(
            workflow.get("activeWorkflowItems"),
            candidate_id=normalized_run_id,
            current_node="knowledge_collection",
            status=f"source_collection_{stage_status}",
            transfer_id="",
        )
        workflow["updatedAt"] = now
        _write_json(_stage_round_store_path(normalized_team_id), store)
        _write_json(_workflow_path(normalized_team_id), workflow)
    _record_workflow_event(
        "research_stage_round.repaired_from_source_collection_run",
        normalized_team_id,
        fields={
            "runId": normalized_run_id,
            "stageRoundId": stage_round_id,
            "status": stage_status,
            "taskCount": len(task_refs),
            "recordCount": _source_collection_count(run_status_summary.get("recordCount")),
            "candidateCount": run_candidate_count,
        },
    )
    return True


def _source_collection_stage_task_refs(run_id: str, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        refs.append(
            {
                "taskId": _trim_text(task.get("taskId"), max_length=160),
                "runId": run_id,
                "stageId": _trim_text(task.get("stageId"), max_length=80),
                "agentId": _trim_text(task.get("agentId"), max_length=160),
                "agentRole": _trim_text(task.get("agentRole"), max_length=80),
                "sessionId": _trim_text(task.get("sessionId"), max_length=160),
                "status": _trim_text(task.get("status"), max_length=80),
                "summary": _trim_text(task.get("summary"), max_length=500),
                "updatedAt": _trim_text(task.get("updatedAt"), max_length=120),
            }
        )
    return sorted(refs, key=lambda item: str(item.get("updatedAt") or ""))


def _source_collection_run_belongs_to_team(run: dict[str, Any], team_id: str) -> bool:
    scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
    metadata = run.get("metadata") if isinstance(run.get("metadata"), dict) else {}
    run_team_id = _trim_text(scope.get("teamId") or metadata.get("teamId"), max_length=160)
    started_from = _trim_text(metadata.get("startedFrom"), max_length=160)
    workflow_stage = _trim_text(scope.get("workflowStage"), max_length=120)
    return run_team_id == team_id and (
        started_from == "team_workflow_source_collection"
        or workflow_stage == "knowledge_collection"
    )


def _source_collection_stage_round_ref_for_run(team_id: str, run_id: str) -> dict[str, Any]:
    normalized_run_id = _trim_text(run_id, max_length=160)
    if not normalized_run_id:
        return {}
    with _WORKFLOW_LOCK:
        store = _load_stage_round_store(team_id)
    rounds = [
        item for item in _stage_rounds(store)
        if isinstance(item, dict)
        and str(item.get("stageType") or "") == "knowledge_collection"
        and normalized_run_id in {str(source_run_id) for source_run_id in list(item.get("sourceRunIds") or [])}
    ]
    latest_round = _latest_stage_round(rounds)
    if not latest_round:
        return {}
    return {
        "stageRoundId": _trim_text(latest_round.get("stageRoundId"), max_length=160),
        "stageType": "knowledge_collection",
        "roundNumber": _source_collection_count(latest_round.get("roundNumber")),
        "status": _trim_text(latest_round.get("status"), max_length=80),
        "sourceRunIds": [str(item) for item in list(latest_round.get("sourceRunIds") or []) if str(item or "").strip()],
        "updatedAt": _trim_text(latest_round.get("updatedAt"), max_length=120),
    }


def _source_collection_stage_cards_projection(team_id: str, run_id: str) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    normalized_run_id = _trim_text(run_id, max_length=160)
    if not normalized_run_id:
        return {"runId": "", "cards": [], "latestTasks": {}, "summary": {"closedLoopCount": 0, "stageCount": 0}}
    try:
        run_status = data_processing_service.get_processing_status(normalized_run_id)
    except data_processing_service.DataProcessingError:
        run_status = {}
    run_summary = run_status.get("summary") if isinstance(run_status.get("summary"), dict) else {}
    with _WORKFLOW_LOCK:
        candidate_store = _load_candidate_store(normalized_team_id)
    all_candidates = [item for item in list(candidate_store.get("candidates") or []) if isinstance(item, dict)]
    active_candidates = [item for item in all_candidates if not _candidate_is_archived(item)]
    source_candidates = [
        item for item in all_candidates
        if str(item.get("candidateType") or "") == "source_manifest"
        and _source_collection_candidate_trace_run_id(item) == normalized_run_id
    ]
    assessed_sources = [item for item in source_candidates if _candidate_source_quality_assessment(item) is not None]
    approved_sources = [item for item in source_candidates if _source_quality_bucket(item) == "approved"]
    source_candidate_ids = {
        _trim_text(item.get("candidateId"), max_length=160)
        for item in source_candidates
        if _trim_text(item.get("candidateId"), max_length=160)
    }
    graph_candidates = [
        item for item in active_candidates
        if str(item.get("candidateType") or "") == "candidate_graph"
        and _source_collection_candidate_graph_matches_run(item, source_candidate_ids)
    ]
    latest_graph = _latest_candidate_record(graph_candidates)
    latest_graph_metadata = latest_graph.get("metadata") if isinstance((latest_graph or {}).get("metadata"), dict) else {}
    latest_graph_payload = latest_graph_metadata.get("graph") if isinstance(latest_graph_metadata.get("graph"), dict) else {}
    graph_summary = latest_graph_payload.get("summary") if isinstance(latest_graph_payload.get("summary"), dict) else {}
    steward_candidates = [
        item
        for item in active_candidates
        if _source_collection_steward_candidate_matches_run(item, source_candidate_ids)
    ]
    steward_pack_count = len(steward_candidates)
    formal_synced_count = sum(
        1
        for item in steward_candidates
        if str(item.get("currentState") or "") in {"official_synced", "formal_knowledge_synced"}
    )
    tasks = _source_collection_stage_session_tasks(normalized_team_id, normalized_run_id)
    tasks_by_stage: dict[str, list[dict[str, Any]]] = {}
    for task in tasks:
        stage_id = _trim_text(task.get("stageId"), max_length=80)
        if stage_id:
            tasks_by_stage.setdefault(stage_id, []).append(task)
    cards = [
        _source_collection_stage_card_projection(
            "collection",
            tasks_by_stage.get("collection", []),
            artifact_count=_source_collection_count(run_summary.get("recordCount")),
            input_count=_source_collection_count(run_summary.get("assignmentCount")),
            output_count=_source_collection_count(run_summary.get("recordCount")),
            pending_count=_source_collection_count(run_summary.get("openAssignmentCount")),
            artifact_status="ready" if _source_collection_count(run_summary.get("recordCount")) > 0 else "empty",
            artifact_summary=f"{_source_collection_count(run_summary.get('recordCount'))} DataRecord records; {_source_collection_count(run_summary.get('openAssignmentCount'))} assignments remain.",
        ),
        _source_collection_stage_card_projection(
            "candidate",
            tasks_by_stage.get("candidate", []),
            artifact_count=len(source_candidates),
            input_count=_source_collection_count(run_summary.get("recordCount")),
            output_count=len(source_candidates),
            pending_count=max(0, _source_collection_count(run_summary.get("recordCount")) - len(source_candidates)),
            artifact_status="ready" if source_candidates else "empty",
            artifact_summary=f"{len(source_candidates)} source_manifest candidates from this run.",
        ),
        _source_collection_stage_card_projection(
            "screening",
            tasks_by_stage.get("screening", []),
            artifact_count=len(assessed_sources),
            input_count=len(source_candidates),
            output_count=len(approved_sources),
            pending_count=max(0, len(source_candidates) - len(assessed_sources)),
            artifact_status="ready" if len(assessed_sources) >= len(source_candidates) and source_candidates else ("partial" if assessed_sources else "empty"),
            artifact_summary=f"{len(assessed_sources)}/{len(source_candidates)} source candidates assessed; {len(approved_sources)} approved.",
        ),
        _source_collection_stage_card_projection(
            "graph",
            tasks_by_stage.get("graph", []),
            artifact_count=_source_collection_count(graph_summary.get("nodeCount")),
            input_count=len(source_candidates),
            output_count=_source_collection_count(graph_summary.get("edgeCount")),
            pending_count=0 if graph_summary else len(source_candidates),
            artifact_status="ready" if graph_summary else "empty",
            artifact_summary=f"{_source_collection_count(graph_summary.get('nodeCount'))} graph nodes; {_source_collection_count(graph_summary.get('edgeCount'))} graph edges.",
        ),
        _source_collection_stage_card_projection(
            "memory",
            tasks_by_stage.get("memory", []),
            artifact_count=max(steward_pack_count, formal_synced_count),
            input_count=len(approved_sources) or len(source_candidates),
            output_count=formal_synced_count,
            pending_count=steward_pack_count,
            artifact_status="ready" if formal_synced_count else ("partial" if steward_pack_count else "empty"),
            artifact_summary=f"{steward_pack_count} 个入库审核包；{formal_synced_count} 个正式知识同步标记。",
        ),
    ]
    latest_tasks = {
        card["stageId"]: card.get("latestTask", {})
        for card in cards
        if isinstance(card.get("latestTask"), dict) and card["latestTask"].get("taskId")
    }
    return {
        "runId": normalized_run_id,
        "cards": cards,
        "latestTasks": latest_tasks,
        "summary": {
            "stageCount": len(cards),
            "closedLoopCount": sum(1 for card in cards if card.get("isClosedLoop")),
            "agentTaskCount": len(tasks),
            "recordCount": _source_collection_count(run_summary.get("recordCount")),
            "sourceCandidateCount": len(source_candidates),
            "assessedSourceCandidateCount": len(assessed_sources),
            "approvedSourceCandidateCount": len(approved_sources),
            "graphNodeCount": _source_collection_count(graph_summary.get("nodeCount")),
            "stewardPackCount": steward_pack_count,
            "formalKnowledgeSyncCount": formal_synced_count,
        },
    }


def _source_collection_stage_card_projection(
    stage_id: str,
    tasks: list[dict[str, Any]],
    *,
    artifact_count: int,
    input_count: int,
    output_count: int,
    pending_count: int,
    artifact_status: str,
    artifact_summary: str,
) -> dict[str, Any]:
    latest_task = _latest_source_collection_stage_task(tasks)
    agent_status = _trim_text(latest_task.get("status"), max_length=80).lower() if latest_task else "not_started"
    task_completed = agent_status in {"completed", "needs_review"}
    task_blocked = agent_status in {"blocked", "failed"}
    artifact_ready = artifact_status == "ready" or artifact_count > 0
    if agent_status in {"running", "queued"}:
        card_status = "agent_running"
    elif task_blocked:
        card_status = "agent_blocked"
    elif task_completed and artifact_ready:
        card_status = "closed_loop"
    elif task_completed:
        card_status = "agent_done_artifact_pending"
    elif artifact_ready:
        card_status = "artifact_ready_no_latest_agent_task"
    elif pending_count > 0 or input_count > 0:
        card_status = "pending"
    else:
        card_status = "idle"
    next_actions = latest_task.get("nextActions") if latest_task and isinstance(latest_task.get("nextActions"), list) else []
    result = latest_task.get("result") if latest_task and isinstance(latest_task.get("result"), dict) else {}
    result_keys = sorted(str(key) for key in result.keys()) if result else []
    return {
        "stageId": stage_id,
        "status": card_status,
        "isClosedLoop": card_status == "closed_loop",
        "agentTaskStatus": agent_status,
        "artifactStatus": artifact_status,
        "artifactSummary": artifact_summary,
        "counts": {
            "input": input_count,
            "artifact": artifact_count,
            "output": output_count,
            "pending": pending_count,
            "task": len(tasks),
        },
        "latestTask": _source_collection_stage_task_card_summary(latest_task) if latest_task else {},
        "resultKeys": result_keys,
        "nextActions": [_trim_text(item, max_length=500) for item in next_actions if _trim_text(item, max_length=500)][:6],
        "blockingReasons": _source_collection_stage_card_blocking_reasons(card_status, artifact_status, artifact_count, pending_count),
    }


def _latest_source_collection_stage_task(tasks: list[dict[str, Any]]) -> dict[str, Any] | None:
    valid = [item for item in tasks if isinstance(item, dict)]
    if not valid:
        return None
    return sorted(valid, key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""))[-1]


def _source_collection_stage_task_card_summary(task: dict[str, Any]) -> dict[str, Any]:
    writeback = task.get("writeback") if isinstance(task.get("writeback"), dict) else {}
    result = task.get("result") if isinstance(task.get("result"), dict) else {}
    evidence_refs = task.get("evidenceRefs") if isinstance(task.get("evidenceRefs"), list) else []
    next_actions = task.get("nextActions") if isinstance(task.get("nextActions"), list) else []
    return {
        "taskId": _trim_text(task.get("taskId"), max_length=160),
        "stageId": _trim_text(task.get("stageId"), max_length=80),
        "agentId": _trim_text(task.get("agentId"), max_length=160),
        "agentRole": _trim_text(task.get("agentRole"), max_length=80),
        "sessionId": _trim_text(task.get("sessionId"), max_length=160),
        "status": _trim_text(task.get("status"), max_length=80),
        "summary": _trim_text(task.get("summary"), max_length=1000),
        "updatedAt": _trim_text(task.get("updatedAt"), max_length=120),
        "resultKeys": sorted(str(key) for key in result.keys()),
        "evidenceRefCount": len(evidence_refs),
        "nextActionCount": len(next_actions),
        "materializedSources": writeback.get("materializedSources") if isinstance(writeback.get("materializedSources"), dict) else {},
        "materializedKnowledgeIngestion": writeback.get("materializedKnowledgeIngestion")
        if isinstance(writeback.get("materializedKnowledgeIngestion"), dict)
        else {},
    }


def _source_collection_stage_card_blocking_reasons(card_status: str, artifact_status: str, artifact_count: int, pending_count: int) -> list[str]:
    reasons: list[str] = []
    if card_status == "agent_done_artifact_pending":
        reasons.append("Agent task wrote back a structured result, but the expected stage artifact has not been created yet.")
    if card_status == "agent_blocked":
        reasons.append("Latest Agent task is blocked or failed.")
    if artifact_status == "empty" and artifact_count <= 0 and pending_count > 0:
        reasons.append("Inputs exist, but this stage has not produced its expected artifact yet.")
    return reasons


def _source_collection_candidate_trace_run_id(candidate: dict[str, Any]) -> str:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    imported_from = metadata.get("importedFromDataRecord") if isinstance(metadata.get("importedFromDataRecord"), dict) else {}
    return (
        _trim_text(imported_from.get("runId"), max_length=160)
        or _trim_text(metadata.get("sourceCollectionRunId"), max_length=160)
    )


def _source_collection_candidate_graph_matches_run(candidate: dict[str, Any], source_candidate_ids: set[str]) -> bool:
    if not source_candidate_ids:
        return False
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    generated_ids = set(_normalize_id_values(metadata.get("generatedFromCandidateIds")))
    ingestion = metadata.get("knowledgeCollectionIngestion") if isinstance(metadata.get("knowledgeCollectionIngestion"), dict) else {}
    input_ids = set(_normalize_id_values(ingestion.get("inputCandidateIds")))
    graph = metadata.get("graph") if isinstance(metadata.get("graph"), dict) else {}
    graph_node_ids = {
        _trim_text(item.get("candidateId"), max_length=160)
        for item in list(graph.get("nodes") or [])
        if isinstance(item, dict) and _trim_text(item.get("candidateId"), max_length=160)
    }
    return bool((generated_ids | input_ids | graph_node_ids) & source_candidate_ids)


def _source_collection_steward_candidate_matches_run(candidate: dict[str, Any], source_candidate_ids: set[str]) -> bool:
    if not source_candidate_ids:
        return False
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    output = metadata.get("output") if isinstance(metadata.get("output"), dict) else {}
    task_type = str(metadata.get("taskType") or "")
    is_steward = (
        task_type == "steward_pack_draft"
        or str(candidate.get("currentWorkflowNode") or "") == "steward_ingestion"
    )
    if not is_steward:
        return False
    candidate_ids = set(_normalize_id_values(output.get("candidateIds")))
    source_trace = output.get("sourceTrace") if isinstance(output.get("sourceTrace"), dict) else {}
    candidate_ids.update(_normalize_id_values(source_trace.get("sourceCandidateIds") or source_trace.get("sourceIds")))
    return bool(candidate_ids & source_candidate_ids)


def _reconcile_source_collection_stage_session_task_sources(team_id: str, run_id: str, task: dict[str, Any]) -> dict[str, Any]:
    writeback = task.get("writeback") if isinstance(task.get("writeback"), dict) else {}
    if not writeback:
        return task
    status = _trim_text(writeback.get("status") or task.get("status"), max_length=80).lower()
    if status not in SOURCE_COLLECTION_STAGE_WRITEBACK_MATERIALIZED_STATUSES:
        return task
    result = writeback.get("result") if isinstance(writeback.get("result"), dict) else {}
    if not result and isinstance(task.get("result"), dict):
        result = task["result"]
        writeback = dict(writeback)
        writeback["result"] = result
    if not result:
        return task
    next_writeback = dict(writeback)
    next_task = dict(task)
    next_result = dict(result)
    changed = False

    existing_summary = writeback.get("materializedSources") if isinstance(writeback.get("materializedSources"), dict) else {}
    existing_status = _trim_text(existing_summary.get("status"), max_length=80).lower()
    if not existing_status or existing_status == "failed":
        materialized_sources = _materialize_source_collection_stage_writeback_sources(
            team_id,
            run_id,
            task,
            writeback,
        )
        next_writeback["materializedSources"] = materialized_sources
        next_result["materializedSources"] = materialized_sources
        changed = True
        _record_workflow_event(
            "source_collection.stage_session_task_sources_reconciled",
            team_id,
            fields={
                "runId": run_id,
                "taskId": _trim_text(task.get("taskId"), max_length=160),
                "stageId": _trim_text(task.get("stageId"), max_length=80),
                "agentId": _trim_text(task.get("agentId"), max_length=160),
                "sourceLeadCount": materialized_sources.get("sourceLeadCount", 0),
                "createdRecordCount": materialized_sources.get("createdRecordCount", 0),
                "importedCandidateCount": materialized_sources.get("importedCandidateCount", 0),
                "skippedDuplicateCount": materialized_sources.get("skippedDuplicateCount", 0),
                "failedCount": materialized_sources.get("failedCount", 0),
            },
            level="warning" if materialized_sources.get("failedCount") else "info",
            outcome="failed" if materialized_sources.get("failedCount") else "completed",
            lifecycle=bool(materialized_sources.get("failedCount")),
        )

    existing_quality_summary = writeback.get("materializedSourceQuality") if isinstance(writeback.get("materializedSourceQuality"), dict) else {}
    existing_quality_status = _trim_text(existing_quality_summary.get("status"), max_length=80).lower()
    should_reconcile_quality = (
        (_trim_text(task.get("stageId"), max_length=80) == "screening" or _trim_text(task.get("agentRole"), max_length=80) == "source_quality")
        and bool(_source_collection_stage_writeback_candidate_decisions(result))
    )
    if should_reconcile_quality and (not existing_quality_status or existing_quality_status == "failed"):
        materialized_quality = _materialize_source_collection_stage_writeback_quality(
            team_id,
            run_id,
            task,
            writeback,
        )
        next_writeback["materializedSourceQuality"] = materialized_quality
        next_result["materializedSourceQuality"] = materialized_quality
        changed = True

    existing_graph_summary = writeback.get("materializedCandidateGraph") if isinstance(writeback.get("materializedCandidateGraph"), dict) else {}
    existing_graph_status = _trim_text(existing_graph_summary.get("status"), max_length=80).lower()
    should_reconcile_graph = (
        (_trim_text(task.get("stageId"), max_length=80) == "graph" or _trim_text(task.get("agentRole"), max_length=80) == "candidate_graph")
        and isinstance(result.get("candidateGraph"), dict)
    )
    if should_reconcile_graph and (not existing_graph_status or existing_graph_status == "failed"):
        materialized_graph = _materialize_source_collection_stage_writeback_candidate_graph(
            team_id,
            run_id,
            task,
            writeback,
        )
        next_writeback["materializedCandidateGraph"] = materialized_graph
        next_result["materializedCandidateGraph"] = materialized_graph
        changed = True

    existing_knowledge_summary = writeback.get("materializedKnowledgeIngestion") if isinstance(writeback.get("materializedKnowledgeIngestion"), dict) else {}
    existing_knowledge_status = _trim_text(existing_knowledge_summary.get("status"), max_length=80).lower()
    should_reconcile_knowledge = (
        _source_collection_stage_can_materialize_formal_knowledge(
            _trim_text(task.get("stageId"), max_length=80),
            _trim_text(task.get("agentRole"), max_length=80),
        )
        and bool(_source_collection_stage_writeback_approved_candidate_refs(result, writeback))
    )
    if should_reconcile_knowledge and (not existing_knowledge_status or existing_knowledge_status == "failed"):
        materialized_knowledge = _materialize_source_collection_stage_writeback_knowledge_ingestion(
            team_id,
            run_id,
            task,
            writeback,
        )
        next_writeback["materializedKnowledgeIngestion"] = materialized_knowledge
        next_result["materializedKnowledgeIngestion"] = materialized_knowledge
        next_task["writesFormalKnowledge"] = bool(materialized_knowledge.get("writesFormalKnowledge"))
        next_task["writesRag"] = bool(materialized_knowledge.get("writesRag"))
        next_task["writesOfficialGraph"] = bool(materialized_knowledge.get("writesOfficialGraph"))
        changed = True

    if not changed:
        return task
    next_task["writeback"] = next_writeback
    next_task["result"] = next_result
    next_task["updatedAt"] = utc_now_iso()
    return next_task


def _reconcile_source_collection_stage_session_task_from_turn_result(task: dict[str, Any]) -> dict[str, Any]:
    status = _trim_text(task.get("status"), max_length=80).lower()
    if status not in {"running", "queued"}:
        return task
    turn = task.get("turn") if isinstance(task.get("turn"), dict) else {}
    turn_id = _trim_text(turn.get("turnId"), max_length=200)
    session_id = _trim_text(task.get("sessionId") or turn.get("sessionId"), max_length=160)
    agent_id = _trim_text(task.get("agentId"), max_length=160)
    if not turn_id or not session_id or not agent_id:
        return task
    turn_result = _source_collection_stage_session_task_turn_result(agent_id, session_id, turn_id)
    if not turn_result:
        return task
    next_status = _source_collection_stage_task_status_from_turn_result(turn_result)
    if next_status in {"running", "queued"}:
        return task
    now = utc_now_iso()
    next_task = dict(task)
    next_task["status"] = next_status
    next_task["summary"] = _trim_text(turn_result.get("summary"), max_length=500) or _trim_text(task.get("summary"), max_length=500)
    next_task["updatedAt"] = now
    next_task["reconciledFromTurn"] = {
        "turnId": turn_id,
        "status": _trim_text(turn_result.get("status"), max_length=80),
        "resultEventId": _trim_text(turn_result.get("eventId"), max_length=160),
        "createdAt": _trim_text(turn_result.get("createdAt"), max_length=120),
        "reconciledAt": now,
    }
    next_turn = dict(turn)
    next_turn["status"] = next_status
    next_task["turn"] = next_turn
    if not isinstance(next_task.get("writeback"), dict) or not next_task.get("writeback"):
        next_task["writeback"] = {
            "status": next_status,
            "summary": next_task["summary"],
            "resultAuthority": "agent_turn_result_reconciliation",
            "updatedAt": now,
        }
    _record_workflow_event(
        "source_collection_stage_session_task.reconciled_from_turn",
        _trim_text(task.get("teamId"), max_length=128),
        fields={
            "runId": _trim_text(task.get("runId"), max_length=128),
            "taskId": _trim_text(task.get("taskId"), max_length=160),
            "stageId": _trim_text(task.get("stageId"), max_length=80),
            "agentId": agent_id,
            "sessionId": session_id,
            "turnId": turn_id,
            "previousStatus": status,
            "status": next_status,
        },
    )
    return next_task


def _source_collection_stage_session_task_turn_result(agent_id: str, session_id: str, turn_id: str) -> dict[str, Any]:
    events_path = developer_sandbox.seeded_sandbox_workspace_path(
        _project_root(),
        "agents",
        _safe_token(agent_id, default="agent", max_length=160),
        "events",
        "agent_turn_results.jsonl",
    )
    for item in reversed(_read_jsonl(events_path)):
        if _trim_text(item.get("runId"), max_length=200) != turn_id:
            continue
        if _trim_text(item.get("sessionId"), max_length=160) != session_id:
            continue
        return item
    return {}


def _source_collection_stage_task_status_from_turn_result(turn_result: dict[str, Any]) -> str:
    status = _trim_text(turn_result.get("status"), max_length=80).lower()
    summary = _trim_text(turn_result.get("summary"), max_length=2000).lower()
    if status in {"failed", "error"}:
        return "failed"
    if status in {"cancelled", "canceled", "stopped", "superseded"}:
        return "cancelled"
    if status in {"completed", "done", "succeeded", "success"}:
        blocked_markers = (
            "状态：blocked",
            "状态: blocked",
            "状态：阻塞",
            "状态: 阻塞",
            "无法完成",
            "无法访问",
            "缺少",
            "blocked",
        )
        return "blocked" if any(marker in summary for marker in blocked_markers) else "completed"
    return status if status in {"running", "queued"} else "needs_review"


def _rank_source_collection_context_records(
    records: list[dict[str, Any]],
    *,
    stage_id: str,
    source_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    imported_record_ids: set[str] = set()
    for candidate in source_candidates:
        if not isinstance(candidate, dict):
            continue
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        imported_from = metadata.get("importedFromDataRecord") if isinstance(metadata.get("importedFromDataRecord"), dict) else {}
        record_id = _trim_text(imported_from.get("recordId"), max_length=128)
        if record_id:
            imported_record_ids.add(record_id)

    def score(record: dict[str, Any]) -> tuple[int, str]:
        record_id = _trim_text(record.get("recordId"), max_length=128)
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        source_ref = _trim_text(record.get("sourceRef"), max_length=2000)
        raw_location = _trim_text(record.get("rawLocation"), max_length=2000)
        quality = record.get("qualitySignals") if isinstance(record.get("qualitySignals"), dict) else {}
        value = 0
        if stage_id == "candidate" and record_id not in imported_record_ids:
            value += 60
        if _source_collection_extract_doi(source_ref, raw_location, metadata.get("doi")):
            value += 30
        if _looks_like_url(source_ref) or _looks_like_url(raw_location):
            value += 20
        if _trim_text(record.get("title"), max_length=240):
            value += 8
        if _trim_text(record.get("summary"), max_length=1000):
            value += 8
        if quality:
            value += 4
        return (-value, _trim_text(record.get("createdAt"), max_length=120) or record_id)

    return sorted([item for item in records if isinstance(item, dict)], key=score)


def _rank_source_collection_context_candidates(
    candidates: list[dict[str, Any]],
    *,
    stage_id: str,
) -> list[dict[str, Any]]:
    def score(candidate: dict[str, Any]) -> tuple[int, str, str]:
        bucket = _source_quality_bucket(candidate)
        value = 0
        if stage_id == "screening" and bucket == "pending":
            value -= 40
        elif stage_id == "screening" and bucket in {"needs_revision", "rejected"}:
            value -= 10
        title = _trim_text(candidate.get("title"), max_length=240)
        if title:
            value -= 4
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        if _trim_text(metadata.get("doi") or candidate.get("sourceUrl") or candidate.get("sourcePath"), max_length=1000):
            value -= 4
        return (
            value,
            _trim_text(candidate.get("updatedAt"), max_length=120),
            _trim_text(candidate.get("candidateId"), max_length=128),
        )

    return sorted([item for item in candidates if isinstance(item, dict)], key=score)


def _source_collection_context_run_summary(
    run: dict[str, Any],
    run_status: dict[str, Any],
    active_work_run: dict[str, Any],
) -> dict[str, Any]:
    scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
    metadata = run.get("metadata") if isinstance(run.get("metadata"), dict) else {}
    summary = run_status.get("summary") if isinstance(run_status.get("summary"), dict) else {}
    return {
        "runId": _trim_text(run.get("runId"), max_length=128),
        "title": _trim_text(run.get("title") or metadata.get("title") or scope.get("topic"), max_length=240),
        "topic": _trim_text(scope.get("topic"), max_length=240),
        "goal": _trim_text(scope.get("goal"), max_length=500),
        "status": _trim_text(run.get("status") or run_status.get("status") or active_work_run.get("status"), max_length=80),
        "currentPhase": _trim_text(active_work_run.get("currentPhase") or summary.get("currentPhase"), max_length=120),
        "summary": _trim_text(active_work_run.get("summary") or summary.get("summary"), max_length=500),
    }


def _source_collection_context_task_summary(task: dict[str, Any]) -> dict[str, Any]:
    if not task:
        return {}
    return {
        "taskId": _trim_text(task.get("taskId"), max_length=160),
        "stageId": _trim_text(task.get("stageId"), max_length=80),
        "agentId": _trim_text(task.get("agentId"), max_length=160),
        "agentRole": _trim_text(task.get("agentRole"), max_length=80),
        "sessionId": _trim_text(task.get("sessionId"), max_length=160),
        "status": _trim_text(task.get("status"), max_length=80),
        "title": _trim_text(task.get("title"), max_length=240),
        "summary": _trim_text(task.get("summary"), max_length=500),
        "createdAt": _trim_text(task.get("createdAt"), max_length=120),
        "updatedAt": _trim_text(task.get("updatedAt"), max_length=120),
    }


def _source_collection_context_assignment_summary(assignment: dict[str, Any]) -> dict[str, Any]:
    return {
        "assignmentId": _trim_text(assignment.get("assignmentId"), max_length=128),
        "agentId": _trim_text(assignment.get("agentId"), max_length=160),
        "agentRole": _trim_text(assignment.get("agentRole"), max_length=80),
        "status": _trim_text(assignment.get("status"), max_length=80),
        "purpose": _trim_text(assignment.get("purpose"), max_length=500),
    }


def _source_collection_context_record_summary(record: dict[str, Any]) -> dict[str, Any]:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    metadata_trace = metadata.get("sourceCollectionTrace") if isinstance(metadata.get("sourceCollectionTrace"), dict) else {}
    record_trace = record.get("collectionTrace") if isinstance(record.get("collectionTrace"), dict) else {}
    trace = {**record_trace, **metadata_trace}
    source_ref = _trim_text(record.get("sourceRef"), max_length=1000)
    raw_location = _trim_text(record.get("rawLocation"), max_length=1000)
    doi = _source_collection_extract_doi(source_ref, raw_location, metadata.get("doi"))
    source_url = source_ref if _looks_like_url(source_ref) else (raw_location if _looks_like_url(raw_location) else "")
    return {
        "recordId": _trim_text(record.get("recordId"), max_length=128),
        "title": _trim_text(record.get("title"), max_length=240),
        "summary": _trim_text(record.get("summary"), max_length=1200),
        "sourceType": _trim_text(record.get("sourceType"), max_length=80),
        "sourceRef": source_ref,
        "rawLocation": raw_location,
        "sourceUrl": source_url,
        "doi": doi,
        "containerTitle": _trim_text(metadata.get("containerTitle"), max_length=240),
        "issued": _trim_text(metadata.get("issued"), max_length=80),
        "searchProvider": _trim_text(metadata.get("searchProvider") or trace.get("searchProvider"), max_length=80),
        "query": _trim_text(trace.get("query") or metadata.get("query"), max_length=500),
        "assignmentId": _trim_text(trace.get("assignmentId") or metadata.get("assignmentId"), max_length=128),
        "identityKey": _source_collection_record_identity_key(record),
        "qualitySignals": _normalize_metadata(record.get("qualitySignals")),
    }


def _source_collection_context_candidate_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    imported_from = metadata.get("importedFromDataRecord") if isinstance(metadata.get("importedFromDataRecord"), dict) else {}
    return {
        "candidateId": _trim_text(candidate.get("candidateId"), max_length=128),
        "candidateType": _trim_text(candidate.get("candidateType"), max_length=80),
        "title": _trim_text(candidate.get("title"), max_length=240),
        "summary": _trim_text(candidate.get("summary"), max_length=1200),
        "sourceKind": _trim_text(candidate.get("sourceKind"), max_length=80),
        "sourceUrl": _trim_text(candidate.get("sourceUrl") or metadata.get("sourceUrl"), max_length=1000),
        "sourcePath": _trim_text(candidate.get("sourcePath") or metadata.get("sourcePath"), max_length=1000),
        "doi": _trim_text(metadata.get("doi") or imported_from.get("doi"), max_length=240),
        "sourceRecordId": _trim_text(metadata.get("sourceRecordId") or imported_from.get("recordId"), max_length=128),
        "sourceIdentityKey": _trim_text(metadata.get("sourceIdentityKey") or imported_from.get("sourceIdentityKey"), max_length=160),
        "status": _trim_text(candidate.get("status"), max_length=80),
        "currentState": _trim_text(candidate.get("currentState"), max_length=80),
        "qualityStatus": _trim_text(candidate.get("qualityStatus"), max_length=80),
        "qualityBucket": _source_quality_bucket(candidate),
        "latestAssessment": _normalize_metadata(_candidate_source_quality_assessment(candidate) or {}),
        "validation": _normalize_metadata(candidate.get("validation")),
    }


def _find_source_collection_stage_session_task(team_id: str, run_id: str, *, idempotency_key: str) -> dict[str, Any] | None:
    key = _trim_text(idempotency_key, max_length=240)
    if not key:
        return None
    for item in _source_collection_stage_session_tasks(team_id, run_id):
        if _trim_text(item.get("idempotencyKey"), max_length=240) == key:
            return item
    return None


def _find_source_collection_stage_session_task_by_id(team_id: str, task_id: str) -> tuple[dict[str, Any] | None, str]:
    normalized_task_id = _trim_text(task_id, max_length=160)
    runs_root = _team_workflow_root(team_id) / "source_collection_runs"
    if not normalized_task_id or not runs_root.exists():
        return None, ""
    for path in runs_root.glob("*/stage_session_tasks.json"):
        run_id = path.parent.name
        store = _read_json(path)
        for item in list(store.get("tasks") or []):
            if isinstance(item, dict) and _trim_text(item.get("taskId"), max_length=160) == normalized_task_id:
                return item, run_id
    return None, ""


def _upsert_source_collection_stage_session_task(team_id: str, run_id: str, task: dict[str, Any]) -> dict[str, Any]:
    task_id = _trim_text(task.get("taskId"), max_length=160)
    if not task_id:
        raise TeamWorkflowOrchestrationError("Stage session task id is required.")
    with _WORKFLOW_LOCK:
        store = _load_source_collection_stage_session_task_store(team_id, run_id)
        tasks = [item for item in list(store.get("tasks") or []) if isinstance(item, dict)]
        next_tasks: list[dict[str, Any]] = []
        replaced = False
        for item in tasks:
            if _trim_text(item.get("taskId"), max_length=160) == task_id:
                next_tasks.append(dict(task))
                replaced = True
            else:
                next_tasks.append(item)
        if not replaced:
            next_tasks.append(dict(task))
        store["tasks"] = next_tasks
        _write_source_collection_stage_session_task_store(team_id, run_id, store)
    return task


def _source_collection_stage_task_writeback_contract(
    team_id: str,
    run_id: str,
    task_id: str,
    *,
    stage_id: str,
    agent_id: str,
    agent_role: str,
) -> dict[str, Any]:
    endpoint = f"/api/teams/{urllib.parse.quote(team_id, safe='')}/workflow-orchestration/stage-session-tasks/{urllib.parse.quote(task_id, safe='')}/writeback"
    can_materialize_formal_knowledge = _source_collection_stage_can_materialize_formal_knowledge(stage_id, agent_role)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "contractKind": "source_collection_stage_session_task_writeback",
        "toolName": "source_collection_stage_writeback_tool",
        "taskId": task_id,
        "teamId": team_id,
        "runId": run_id,
        "stageId": stage_id,
        "agentId": agent_id,
        "agentRole": agent_role,
        "endpoint": endpoint,
        "acceptedStatuses": sorted(SOURCE_COLLECTION_STAGE_SESSION_TASK_STATUSES),
        "requiredFields": ["status", "summary", "result"],
        "writesFormalKnowledge": can_materialize_formal_knowledge,
        "writesRag": False,
        "writesOfficialGraph": can_materialize_formal_knowledge,
        "resultAuthority": "source_collection_stage_writeback_tool+knowledge_ingestion_gate"
        if can_materialize_formal_knowledge
        else "source_collection_stage_writeback_tool",
    }


def _source_collection_stage_task_idempotency_key(
    *,
    team_id: str,
    run_id: str,
    stage_id: str,
    agent_id: str,
    agent_role: str,
    task_id: str,
    requested_key: str,
) -> str:
    key_scope = f"{team_id}:{run_id}:{stage_id}:{agent_id}:{agent_role or 'agent'}"
    if requested_key:
        key_digest = hashlib.sha256(requested_key.encode("utf-8", errors="replace")).hexdigest()[:24]
        return _trim_text(f"stage_task:{key_scope}:request:{key_digest}", max_length=240)
    return _trim_text(f"stage_task:{key_scope}:task:{task_id}", max_length=240)


def _source_collection_stage_task_title(stage_id: str) -> str:
    return {
        "collection": "资料搜索任务",
        "candidate": "资料提炼任务",
        "screening": "资料审查任务",
        "graph": "候选图谱任务",
        "memory": "知识库管理员入库审核任务",
    }.get(stage_id, "知识搜集阶段任务")


def _source_collection_stage_task_chat_route(session_id: str, *, return_to: str, return_label: str) -> str:
    params = urllib.parse.urlencode(
        {
            key: value
            for key, value in {
                "session": _trim_text(session_id, max_length=160),
                "returnTo": _trim_text(return_to, max_length=1000),
                "returnLabel": _trim_text(return_label, max_length=240),
            }.items()
            if value
        }
    )
    return f"/chat?{params}" if params else "/chat"


def _source_collection_agent_context_message(
    *,
    team: dict[str, Any],
    agent: dict[str, Any],
    stage_id: str,
    agent_role: str,
    run: dict[str, Any],
    run_status: dict[str, Any],
    active_work_run: dict[str, Any],
    assignments: list[dict[str, Any]],
    matching_assignments: list[dict[str, Any]],
    records: list[dict[str, Any]],
    source_candidates: list[dict[str, Any]],
    storage_artifacts: dict[str, str],
    boundary_text: str | None = None,
) -> str:
    run_scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
    run_metadata = run.get("metadata") if isinstance(run.get("metadata"), dict) else {}
    status_summary = run_status.get("summary") if isinstance(run_status.get("summary"), dict) else {}
    assignment_summary = _source_collection_assignment_stage_summary(assignments)
    open_matching_assignments = _source_collection_open_assignments(matching_assignments)
    stage_label = {
        "collection": "资料发现/获取/提炼",
        "candidate": "资料提炼",
        "screening": "资料质量评估",
        "graph": "候选图谱构建",
        "memory": "知识库管理员入库审核",
    }.get(stage_id, stage_id)
    active_summary = _trim_text(active_work_run.get("summary"), max_length=240) if active_work_run else ""
    run_title = _trim_text(run.get("title") or run_scope.get("topic") or run_metadata.get("title"), max_length=180)
    topic = _trim_text(run_scope.get("topic"), max_length=240)
    goal = _trim_text(run_scope.get("goal"), max_length=320)
    agent_name = _trim_text(agent.get("displayName") or agent.get("name") or agent.get("id"), max_length=160)
    lines = [
        "## 知识搜集上下文",
        f"- 团队：{_trim_text(team.get('name') or team.get('teamId'), max_length=160)}",
        f"- 当前 Agent：{agent_name}",
        f"- 当前阶段：{stage_label}",
        f"- 角色：{agent_role or '未标注'}",
        f"- 运行：{_trim_text(run.get('runId'), max_length=160)}",
    ]
    if run_title:
        lines.append(f"- 标题：{run_title}")
    if topic:
        lines.append(f"- 主题：{topic}")
    if goal:
        lines.append(f"- 目标：{goal}")
    status_text = _trim_text(run.get("status") or run_status.get("status") or active_work_run.get("status"), max_length=80)
    phase_text = _trim_text(active_work_run.get("currentPhase") or status_summary.get("currentPhase"), max_length=80)
    if status_text or phase_text:
        lines.append(f"- 状态：{status_text or 'unknown'}{f' / {phase_text}' if phase_text else ''}")
    if active_summary:
        lines.append(f"- 后台进展：{active_summary}")
    lines.extend(
        [
            "",
            "## 当前可用材料",
            f"- 搜集记录：{len(records)} 条",
            f"- source_manifest 候选：{len(source_candidates)} 条",
            f"- 分派任务：{assignment_summary.get('assignmentCount', 0)} 个，未完成 {assignment_summary.get('openAssignmentCount', 0)} 个",
            f"- 本角色相关任务：{len(matching_assignments)} 个，未完成 {len(open_matching_assignments)} 个",
        ]
    )
    storage_refs = [
        storage_artifacts.get("runDirectory", ""),
        storage_artifacts.get("recordsPath", ""),
        storage_artifacts.get("candidateStorePath", ""),
    ]
    compact_refs = [item for item in storage_refs if item]
    if compact_refs:
        lines.extend(["", "## 存储引用", *[f"- {item}" for item in compact_refs]])
    next_actions = _source_collection_agent_context_next_actions(stage_id, len(records), len(source_candidates), len(open_matching_assignments))
    if next_actions:
        lines.extend(["", "## 建议下一步", *[f"- {item}" for item in next_actions]])
    lines.extend(
        [
            "",
            boundary_text
            or "边界：这条消息只投递当前资料搜集上下文，不会自动启动 Agent 回答；正式知识库、RAG 和官方图谱写入仍由后续治理入口控制。",
        ]
    )
    return "\n".join(lines)


def _source_collection_stage_session_task_message(
    *,
    team: dict[str, Any],
    agent: dict[str, Any],
    stage_id: str,
    agent_role: str,
    run: dict[str, Any],
    run_status: dict[str, Any],
    active_work_run: dict[str, Any],
    assignments: list[dict[str, Any]],
    matching_assignments: list[dict[str, Any]],
    records: list[dict[str, Any]],
    source_candidates: list[dict[str, Any]],
    storage_artifacts: dict[str, str],
    writeback_contract: dict[str, Any],
) -> str:
    can_materialize_formal_knowledge = _source_collection_stage_can_materialize_formal_knowledge(stage_id, agent_role)
    boundary_text = (
        "边界：这是知识库管理员入库审核任务，会立即要求当前 Agent 在本会话执行；"
        "对本轮已通过候选调用 source_collection_stage_writeback_tool 写回 approved 结果后，"
        "后端会通过现有知识治理门禁物化正式 Team Knowledge 和 official trace；不要绕过该链路直接改库。"
        if can_materialize_formal_knowledge
        else (
            "边界：这是阶段任务启动消息，会立即要求当前 Agent 在本会话执行；"
            "正式知识库、RAG 和官方图谱写入仍由后续治理入口控制。"
        )
    )
    write_boundary = (
        "- 本阶段可在 `source_collection_stage_writeback_tool` 中提交 approved 候选；后端只会对本轮且已通过质检的候选走知识治理门禁入库，不要用其他路径写正式知识。"
        if can_materialize_formal_knowledge
        else "- 不要直接写正式 Team Knowledge、RAG 或官方图谱；只能按候选层和结构化回写合同提交结果。"
    )
    context = _source_collection_agent_context_message(
        team=team,
        agent=agent,
        stage_id=stage_id,
        agent_role=agent_role,
        run=run,
        run_status=run_status,
        active_work_run=active_work_run,
        assignments=assignments,
        matching_assignments=matching_assignments,
        records=records,
        source_candidates=source_candidates,
        storage_artifacts=storage_artifacts,
        boundary_text=boundary_text,
    )
    task_title = _source_collection_stage_task_title(stage_id)
    contract_json = json.dumps(writeback_contract, ensure_ascii=False, sort_keys=True)
    context_tool_payload = {
        "team_id": writeback_contract.get("teamId", ""),
        "run_id": writeback_contract.get("runId", ""),
        "stage_id": writeback_contract.get("stageId", stage_id),
        "task_id": writeback_contract.get("taskId", ""),
        "max_records": 24,
        "include_candidates": True,
    }
    context_tool_json = json.dumps(context_tool_payload, ensure_ascii=False, sort_keys=True)
    return "\n".join(
        [
            f"## 资料搜集阶段任务：{task_title}",
            "",
            context,
            "",
            "## 执行要求",
            "- 先用一句简短状态回应已接收任务，再按需要调用工具；不要让用户看到像未启动一样的空白等待。",
            f"- 先调用 `source_collection_context_tool` 读取本轮受控资料上下文，参数如下：`{context_tool_json}`。",
            "- 在本会话里完成当前阶段任务，并把可审查的结论、证据引用和下一步写清楚。",
            "- 不要使用 `web_fetch_tool` 读取 `file://` 本地路径或 localhost 回写接口；本地资料上下文只通过 `source_collection_context_tool` 获取。",
            write_boundary,
            "- 完成后必须调用 `source_collection_stage_writeback_tool` 回写；不要让自然语言回复成为唯一结果来源。",
            "- 如果上下文不足、工具失败或无法完成，请调用 `source_collection_stage_writeback_tool` 写入 status=blocked 或 failed，并说明原因。",
            "",
            "## 结构化回写合同",
            f"```json\n{contract_json}\n```",
        ]
    )


def _sync_stage_round_with_source_collection_stage_task(team_id: str, run_id: str, task: dict[str, Any]) -> None:
    now = utc_now_iso()
    with _WORKFLOW_LOCK:
        store = _load_stage_round_store(team_id)
        rounds = _stage_rounds(store)
        stage_round = _latest_stage_round(
            [
                item
                for item in rounds
                if str(item.get("stageType") or "") == "knowledge_collection"
                and run_id in {str(source_run_id) for source_run_id in list(item.get("sourceRunIds") or [])}
            ]
        )
        if stage_round is None:
            return
        task_refs = [
            item
            for item in list(stage_round.get("sourceCollectionStageSessionTasks") or [])
            if isinstance(item, dict)
            and _trim_text(item.get("taskId"), max_length=160) != _trim_text(task.get("taskId"), max_length=160)
        ]
        task_ref = {
            "taskId": _trim_text(task.get("taskId"), max_length=160),
            "runId": run_id,
            "stageId": _trim_text(task.get("stageId"), max_length=80),
            "agentId": _trim_text(task.get("agentId"), max_length=160),
            "agentRole": _trim_text(task.get("agentRole"), max_length=80),
            "sessionId": _trim_text(task.get("sessionId"), max_length=160),
            "status": _trim_text(task.get("status"), max_length=80),
            "summary": _trim_text(task.get("summary"), max_length=500),
            "updatedAt": _trim_text(task.get("updatedAt"), max_length=120) or now,
        }
        task_refs.append(task_ref)
        stage_round["sourceCollectionStageSessionTasks"] = sorted(task_refs, key=lambda item: str(item.get("updatedAt") or ""))
        stage_round["updatedAt"] = now
        stage_round["status"] = _source_collection_stage_round_status_from_task_refs(
            stage_round,
            stage_round["sourceCollectionStageSessionTasks"],
        )
        workflow = _load_or_create_workflow(team_id)
        stage_round["teamMemoryRecord"] = _stage_memory_record(stage_round, workflow)
        stage_round["teamMemoryRecordId"] = stage_round["teamMemoryRecord"]["recordId"]
        store["updatedAt"] = now
        workflow["activeWorkflowItems"] = _upsert_active_item(
            workflow.get("activeWorkflowItems"),
            candidate_id=run_id,
            current_node="knowledge_collection",
            status=f"source_collection_stage_task_{task_ref['status']}",
            transfer_id="",
        )
        workflow["updatedAt"] = now
        _write_json(_stage_round_store_path(team_id), store)
        _write_json(_workflow_path(team_id), workflow)


def _source_collection_stage_round_status_from_task_refs(stage_round: dict[str, Any], task_refs: list[dict[str, Any]]) -> str:
    statuses = {
        _trim_text(item.get("status"), max_length=80).lower()
        for item in task_refs
        if isinstance(item, dict) and _trim_text(item.get("status"), max_length=80)
    }
    if statuses & {"running", "queued"}:
        return "running"
    if statuses & {"failed", "blocked", "needs_review"}:
        return "needs_attention"
    existing_status = _trim_text(stage_round.get("status"), max_length=80)
    if existing_status not in {"running", "planning", "initializing"}:
        return existing_status or "needs_continue"
    search_execution = stage_round.get("sourceCollectionSearchExecution") if isinstance(stage_round.get("sourceCollectionSearchExecution"), dict) else {}
    search_status = _trim_text(search_execution.get("status") or search_execution.get("resultStatus"), max_length=80)
    if search_status and search_status not in {"running", "queued", "accepted"}:
        return search_status
    return "needs_continue" if statuses else existing_status


def _source_collection_agent_context_next_actions(stage_id: str, record_count: int, candidate_count: int, open_assignment_count: int) -> list[str]:
    if stage_id == "collection":
        if record_count <= 0:
            return ["继续等待或执行资料搜索，先形成 DataRecord。"]
        return ["检查 DataRecord 覆盖面，必要时补充查询词或来源类型。"]
    if stage_id == "candidate":
        if candidate_count <= 0:
            return ["从 DataRecord 提炼 source_manifest 候选。"]
        return ["审查候选来源、去重线索和后续质量评估输入。"]
    if stage_id == "screening":
        return ["对 source_manifest 候选做相关性、可靠性、可访问性和提炼就绪度评估。"]
    if stage_id == "graph":
        return ["基于已通过质量评估的候选构建候选关系图。"]
    if stage_id == "memory":
        return ["由知识库管理员审核候选入库包；正式知识写入仍受审核门禁控制。"]
    if open_assignment_count:
        return ["继续处理未完成的本角色分派任务。"]
    return []


def _source_collection_work_run_store() -> work_run_store.WorkRunStore:
    return work_run_store.WorkRunStore(root=work_run_store.WORK_RUNS_DIR)


def _persist_source_collection_work_run(
    team_id: str,
    run_id: str,
    *,
    status: str,
    current_phase: str,
    run: dict[str, Any],
    team: dict[str, Any],
    assignments: list[dict[str, Any]],
    records: list[dict[str, Any]],
    summary: str,
    active: bool,
    error: str = "",
    error_type: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = utc_now_iso()
    run_scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
    run_metadata = run.get("metadata") if isinstance(run.get("metadata"), dict) else {}
    assignment_summary = _source_collection_assignment_stage_summary(assignments)
    search_plan_ref = run_scope.get("dataSearchPlanRef") if isinstance(run_scope.get("dataSearchPlanRef"), dict) else {}
    query_count = _normalize_int(
        run_metadata.get("queryCount") or search_plan_ref.get("queryCount"),
        default=0,
        minimum=0,
        maximum=SOURCE_COLLECTION_MAX_QUERIES * 4,
    )
    snapshot: dict[str, Any] = {
        "runId": run_id,
        "runKind": SOURCE_COLLECTION_WORK_RUN_KIND,
        "kind": SOURCE_COLLECTION_WORK_RUN_KIND,
        "status": status,
        "currentPhase": current_phase,
        "stageType": "knowledge_collection",
        "teamId": team_id,
        "teamName": _trim_text(team.get("name"), max_length=160) or team_id,
        "title": _trim_text(run.get("title"), max_length=180) or "知识搜集批次",
        "topic": _trim_text(run_scope.get("topic"), max_length=500),
        "summary": _trim_text(summary, max_length=500),
        "currentTask": _trim_text(summary, max_length=500),
        "assignmentCount": len(assignments),
        "openAssignmentCount": assignment_summary["openAssignmentCount"],
        "searchAssignmentCount": assignment_summary["searchAssignmentCount"],
        "searchOpenAssignmentCount": assignment_summary["searchOpenAssignmentCount"],
        "collectionAssignmentCount": assignment_summary["collectionAssignmentCount"],
        "collectionOpenAssignmentCount": assignment_summary["collectionOpenAssignmentCount"],
        "downstreamAssignmentCount": assignment_summary["downstreamAssignmentCount"],
        "downstreamOpenAssignmentCount": assignment_summary["downstreamOpenAssignmentCount"],
        "recordCount": len(records),
        "queryCount": query_count,
        "storagePath": _source_collection_storage_artifacts(team_id, run_id)["runDirectory"],
        "updatedAt": now,
        "sourceCollection": {
            "teamId": team_id,
            "stageType": "knowledge_collection",
            "openAssignmentCount": assignment_summary["openAssignmentCount"],
            "searchAssignmentCount": assignment_summary["searchAssignmentCount"],
            "searchOpenAssignmentCount": assignment_summary["searchOpenAssignmentCount"],
            "collectionAssignmentCount": assignment_summary["collectionAssignmentCount"],
            "collectionOpenAssignmentCount": assignment_summary["collectionOpenAssignmentCount"],
            "downstreamAssignmentCount": assignment_summary["downstreamAssignmentCount"],
            "downstreamOpenAssignmentCount": assignment_summary["downstreamOpenAssignmentCount"],
            "recordCount": len(records),
            "queryCount": query_count,
        },
    }
    started_at = _trim_text(run.get("createdAt"), max_length=80) or _trim_text(run.get("startedAt"), max_length=80)
    if started_at:
        snapshot["startedAt"] = started_at
    if not active:
        snapshot["finishedAt"] = now
    if error:
        snapshot["error"] = _trim_text(error, max_length=500)
    if error_type:
        snapshot["errorType"] = _trim_text(error_type, max_length=120)
    if extra:
        snapshot.update(extra)
        source_collection = snapshot.get("sourceCollection") if isinstance(snapshot.get("sourceCollection"), dict) else {}
        source_collection.update({key: value for key, value in extra.items() if key.endswith("Count")})
        snapshot["sourceCollection"] = source_collection
    return _source_collection_work_run_store().persist_snapshot(
        SOURCE_COLLECTION_WORK_RUN_KIND,
        snapshot,
        active_run_id=run_id if active else "",
    )


def _source_collection_work_run_terminal_status(result: dict[str, Any]) -> str:
    if str(result.get("status") or "") == "duplicates_skipped":
        return "completed"
    if _source_collection_count(result.get("failedQueryCount")) and not _source_collection_count(result.get("executedQueryCount")):
        return "failed"
    if bool(result.get("hasMore")) or _source_collection_count(result.get("remainingQueryCount")):
        return "needs_continue"
    source_collection_summary = result.get("sourceCollectionSummary") if isinstance(result.get("sourceCollectionSummary"), dict) else {}
    if _source_collection_count(source_collection_summary.get("searchOpenAssignmentCount")):
        return "needs_continue"
    return "completed"


def _source_collection_work_run_terminal_phase(result: dict[str, Any]) -> str:
    status = _source_collection_work_run_terminal_status(result)
    if status == "failed":
        return "failed"
    if status == "needs_continue":
        return "waiting_for_next_batch"
    return "completed"


def _source_collection_work_run_terminal_summary(result: dict[str, Any]) -> str:
    if _source_collection_work_run_terminal_status(result) == "failed":
        return "资料搜索执行失败，等待检查搜索错误。"
    record_count = _source_collection_count(result.get("recordCount"))
    imported_count = _source_collection_count(result.get("importedCount"))
    skipped_duplicate_count = _source_collection_count(result.get("skippedDuplicateCount"))
    if str(result.get("status") or "") == "duplicates_skipped":
        return f"本轮资料搜索完成，跳过 {skipped_duplicate_count} 条重复资料，未新增资料。"
    if _source_collection_work_run_terminal_status(result) == "needs_continue":
        return f"本轮已写入 {record_count} 条资料、导入 {imported_count} 个候选、跳过 {skipped_duplicate_count} 条重复资料，仍有任务可继续。"
    return f"本轮资料搜索完成，写入 {record_count} 条资料、导入 {imported_count} 个候选、跳过 {skipped_duplicate_count} 条重复资料。"


def _source_collection_count(value: Any) -> int:
    return _normalize_int(value, default=0, minimum=0, maximum=100_000)


def _source_collection_next_runnable_query_ids(
    assignments: list[dict[str, Any]],
    existing_query_ids: set[str],
    *,
    force: bool,
    target_assignment_ids: set[str],
    target_agent_role: str,
) -> list[str]:
    query_ids: list[str] = []
    seen: set[str] = set()
    for assignment in assignments:
        assignment_id = _trim_text(assignment.get("assignmentId"), max_length=128)
        agent_role = _trim_text(assignment.get("agentRole"), max_length=80)
        if agent_role not in SOURCE_COLLECTION_SEARCH_EXECUTION_AGENT_ROLES:
            continue
        if target_assignment_ids and assignment_id not in target_assignment_ids:
            continue
        if target_agent_role and agent_role != target_agent_role:
            continue
        if not force and str(assignment.get("status") or "") not in {"open", "in_progress", "returned"}:
            continue
        for query in _source_collection_assigned_queries(assignment):
            query_id = _trim_text(query.get("queryId"), max_length=160)
            if not query_id or query_id in seen:
                continue
            if query_id in existing_query_ids and not force:
                continue
            seen.add(query_id)
            query_ids.append(query_id)
    return query_ids


def _source_collection_storage_target_path(team_id: str, run_id: str, target: str) -> Path:
    paths = _source_collection_storage_artifact_paths(team_id, run_id)
    target_to_path = {
        "run_directory": paths["runDirectory"],
        "artifacts_directory": paths["artifactsDirectory"],
        "search_plan": paths["searchPlanPath"],
        "search_events": paths["searchEventsPath"],
        "records": paths["recordsPath"],
        "candidates": paths["candidatesPath"],
        "candidate_store": paths["candidateStorePath"],
        "data_processing_run": paths["dataProcessingRunPath"],
        "data_processing_records": paths["dataProcessingRecordsPath"],
    }
    path = target_to_path.get(target)
    if path is None:
        raise TeamWorkflowOrchestrationError(f"Unsupported source collection storage target: {target or '<empty>'}")
    return _ensure_project_child(path)


def _write_source_collection_search_plan(team_id: str, run_id: str, search_plan: dict[str, Any]) -> None:
    paths = _source_collection_storage_artifact_paths(team_id, run_id)
    paths["runDirectory"].mkdir(parents=True, exist_ok=True)
    paths["artifactsDirectory"].mkdir(parents=True, exist_ok=True)
    _write_json(paths["searchPlanPath"], search_plan)
    for path_key in ("searchEventsPath", "recordsPath", "candidatesPath"):
        paths[path_key].touch(exist_ok=True)


def _append_source_collection_execution_artifacts(
    team_id: str,
    run_id: str,
    *,
    execution_events: list[dict[str, Any]],
    created_records: list[dict[str, Any]],
    imported: list[dict[str, Any]],
) -> None:
    paths = _source_collection_storage_artifact_paths(team_id, run_id)
    paths["runDirectory"].mkdir(parents=True, exist_ok=True)
    paths["artifactsDirectory"].mkdir(parents=True, exist_ok=True)
    if execution_events:
        _append_jsonl(paths["searchEventsPath"], execution_events)
    if created_records:
        _append_jsonl(paths["recordsPath"], created_records)
    candidate_records = [
        item.get("candidate")
        for item in imported
        if isinstance(item, dict) and isinstance(item.get("candidate"), dict)
    ]
    if candidate_records:
        _append_jsonl(paths["candidatesPath"], candidate_records)


def _append_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    records: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            records.append(payload)
    return records


def _ensure_project_child(path: Path) -> Path:
    resolved = path.resolve()
    project_root = _project_root().resolve()
    workspace_root = resolve_workspace_home().resolve()
    for allowed_root in (project_root, workspace_root):
        try:
            resolved.relative_to(allowed_root)
            return resolved
        except ValueError:
            continue
    raise TeamWorkflowOrchestrationError("Source collection storage path must stay inside the Vibelution project or workspace data root.")


def _open_local_path(path: Path) -> None:
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
        return
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.Popen([opener, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _source_collection_data_processing_source_type(value: Any) -> str:
    source_type = _trim_text(value, max_length=80).lower()
    if source_type in data_processing_service.SOURCE_TYPES:
        return source_type
    if source_type in {"review", "preprint", "journal-article", "proceedings-article", "book-chapter"}:
        return "paper"
    if source_type in {"posted-content"}:
        return "paper"
    if source_type in {"dataset", "data"}:
        return "dataset"
    return "url"


def _first_crossref_text(value: Any) -> str:
    if isinstance(value, list):
        for item in value:
            text = _trim_text(item, max_length=500)
            if text:
                return html.unescape(text)
        return ""
    return html.unescape(_trim_text(value, max_length=500))


def _crossref_authors(value: Any) -> list[str]:
    authors: list[str] = []
    for item in list(value or [])[:8]:
        if not isinstance(item, dict):
            continue
        name = " ".join(
            part
            for part in [
                _trim_text(item.get("given"), max_length=80),
                _trim_text(item.get("family"), max_length=120),
            ]
            if part
        ).strip()
        if name:
            authors.append(name)
    return authors


def _crossref_date(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    date_parts = value.get("date-parts")
    if not isinstance(date_parts, list) or not date_parts:
        return ""
    first = date_parts[0]
    if not isinstance(first, list) or not first:
        return ""
    parts = [str(part).zfill(2) for part in first[:3] if isinstance(part, int)]
    if not parts:
        return ""
    if parts:
        parts[0] = parts[0].lstrip("0") or "0"
    return "-".join(parts)


def _strip_html(value: str) -> str:
    if not value:
        return ""
    return html.unescape(re.sub(r"<[^>]+>", " ", value)).strip()


def _source_collection_role_assignment_inputs(queries: list[dict[str, Any]], roles: list[str], payload: dict[str, Any]) -> list[dict[str, Any]]:
    assignments: list[dict[str, Any]] = []
    for role in roles:
        role_queries = _source_collection_queries_for_role({"queries": queries}, role)
        prompt_cache_partition = ""
        for query in role_queries:
            execution = query.get("execution") if isinstance(query.get("execution"), dict) else {}
            prompt_cache_partition = _trim_text(execution.get("promptCachePartition"), max_length=160)
            if prompt_cache_partition:
                break
        assignments.append(
            {
                "agentRole": role,
                "agentId": _source_collection_agent_id(role, payload),
                "queryIds": [item["queryId"] for item in role_queries],
                "queryCount": len(role_queries),
                "promptCachePartition": prompt_cache_partition,
                "conversationTraceRequired": True,
                "expectedAction": _source_collection_expected_action(role),
            }
        )
    return assignments


def _source_collection_queries_for_role(search_plan: dict[str, Any], role: str) -> list[dict[str, Any]]:
    queries = search_plan.get("queries")
    if not isinstance(queries, list):
        return []
    return [item for item in queries if isinstance(item, dict) and item.get("assignedAgentRole") == role]


def _source_collection_expected_action(role: str) -> str:
    actions = {
        "data_intake_coordinator": "Coordinate planned query execution and ensure outputs follow the writeback contract.",
        "data_discovery": "Use assigned query seeds to identify candidate academic, dataset, or source references.",
        "source_acquisition": "Turn discovered references into retrievable URLs, files, API refs, or local handles.",
        "content_extraction": "Extract title, summary, metadata, quality signals, and trace fields into DataRecords.",
        "source_deduplication": "Compare collected records and flag duplicate or version-related sources.",
        "source_quality": "Score source reliability, completeness, and downstream processing risk.",
        "intake_review": "Review collected DataRecords before importing accepted records as source_manifest candidates.",
    }
    return actions.get(role, "Collect data records under the source-collection run contract.")


def _source_collection_query_seeds(payload: dict[str, Any], scope: dict[str, Any], input_refs: list[str], *, topic: str, goal: str) -> list[str]:
    seeds: list[str] = []
    for value in _normalize_text_list(payload.get("querySeeds"), max_items=40, max_length=220):
        _append_source_collection_seed(seeds, value)
    _append_source_collection_seed(seeds, topic)
    for key in ("researchQuestion", "domain", "dataset", "benchmark", "organism", "method"):
        _append_source_collection_seed(seeds, scope.get(key))
    for value in _metadata_text_values(scope.get("keywords")):
        _append_source_collection_seed(seeds, value)
    for value in _metadata_text_values(scope.get("seedQueries")):
        _append_source_collection_seed(seeds, value)
    for ref in input_refs:
        _append_source_collection_seed(seeds, _source_collection_seed_from_input_ref(ref))
    if not seeds:
        _append_source_collection_seed(seeds, goal)
    if not seeds:
        _append_source_collection_seed(seeds, "challenge cup research source collection")
    return seeds[:12]


def _append_source_collection_seed(seeds: list[str], value: Any) -> None:
    text = _trim_text(value, max_length=220)
    if not text:
        return
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return
    seen = {item.lower() for item in seeds}
    if normalized.lower() not in seen:
        seeds.append(normalized)


def _source_collection_seed_from_input_ref(value: Any) -> str:
    text = _trim_text(value, max_length=220)
    lowered = text.lower()
    for prefix in ("seed-query:", "query:", "keyword:", "topic:"):
        if lowered.startswith(prefix):
            return text[len(prefix) :].strip()
    return text


def _metadata_text_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [_trim_text(value, max_length=220)] if _trim_text(value, max_length=220) else []
    if isinstance(value, list):
        results: list[str] = []
        for item in value[:24]:
            results.extend(_metadata_text_values(item))
        return results
    if isinstance(value, dict):
        results: list[str] = []
        for item in value.values():
            results.extend(_metadata_text_values(item))
        return results
    return []


def _source_collection_search_languages(value: Any) -> list[str]:
    languages = _normalize_text_list(value, max_items=8, max_length=16)
    return languages or list(SOURCE_COLLECTION_DEFAULT_SEARCH_LANGUAGES)


def _source_collection_source_types(value: Any) -> list[str]:
    source_types = _normalize_text_list(value, max_items=16, max_length=40)
    return source_types or list(SOURCE_COLLECTION_DEFAULT_SOURCE_TYPES)


def _source_collection_query_text(seed: str, *, source_type: str, language: str) -> str:
    normalized_seed = _trim_text(seed, max_length=220)
    normalized_source_type = _trim_text(source_type, max_length=40).lower()
    normalized_language = _trim_text(language, max_length=16).lower()
    if normalized_language.startswith("zh") or normalized_language in {"cn", "chinese"}:
        suffixes = {
            "paper": "论文",
            "review": "综述",
            "dataset": "数据集",
            "preprint": "预印本",
        }
        suffix = suffixes.get(normalized_source_type, normalized_source_type or "资料")
        return _trim_text(f"{normalized_seed} {suffix}", max_length=260)
    suffixes = {
        "paper": "peer reviewed paper",
        "review": "review",
        "dataset": "dataset",
        "preprint": "preprint",
    }
    suffix = suffixes.get(normalized_source_type, normalized_source_type or "source")
    return _trim_text(f"{normalized_seed} {suffix}", max_length=260)


def _normalize_stage_type(value: Any) -> str:
    normalized = _trim_text(value, max_length=80)
    if normalized not in RESEARCH_STAGE_TYPES:
        raise TeamWorkflowOrchestrationError("Unsupported research stage type.")
    return normalized


def _normalize_stage_start_mode(value: Any) -> str:
    normalized = _trim_text(value, max_length=80)
    return "new_round" if normalized in {"new_round", "new", "restart"} else "continue_or_start"


def _load_stage_round_store(team_id: str) -> dict[str, Any]:
    path = _stage_round_store_path(team_id)
    if path.exists():
        payload = _read_json(path)
        if isinstance(payload.get("rounds"), list):
            return payload
    now = utc_now_iso()
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": team_id,
        "storeKind": "research_stage_round_store",
        "rounds": [],
        "createdAt": now,
        "updatedAt": now,
    }
    _write_json(path, payload)
    return payload


def _stage_rounds(store: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in list(store.get("rounds") or []) if isinstance(item, dict)]


def _find_stage_round(rounds: list[dict[str, Any]], stage_round_id: str) -> dict[str, Any] | None:
    for item in rounds:
        if str(item.get("stageRoundId") or "") == stage_round_id:
            return item
    return None


def _active_stage_round(rounds: list[dict[str, Any]], stage_type: str) -> dict[str, Any] | None:
    candidates = [
        item
        for item in rounds
        if str(item.get("stageType") or "") == stage_type and str(item.get("status") or "") in RESEARCH_STAGE_ACTIVE_STATUSES
    ]
    return _latest_stage_round(candidates)


def _latest_stage_round(rounds: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rounds:
        return None
    return sorted(rounds, key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""), reverse=True)[0]


def _stage_round_number(rounds: list[dict[str, Any]], stage_type: str) -> int:
    return 1 + sum(1 for item in rounds if str(item.get("stageType") or "") == stage_type)


def _continued_stage_round_payload(stage_round: dict[str, Any], stage_type: str) -> dict[str, Any]:
    """Return enough context for the UI to show that an active stage was reused."""

    if stage_type != "knowledge_collection":
        return {}
    source_run_ids = [str(item) for item in list(stage_round.get("sourceRunIds") or []) if str(item or "").strip()]
    source_run_id = source_run_ids[0] if source_run_ids else ""
    if not source_run_id:
        return {
            "continuedSourceRunRef": {
                "runId": "",
                "status": "missing",
                "recordCount": 0,
                "assignmentCount": 0,
                "openAssignmentCount": 0,
                "message": "Active knowledge-collection round has no source run id.",
            }
        }
    try:
        run = data_processing_service.get_processing_run(source_run_id)
        assignment_payload = data_processing_service.list_collection_assignments(source_run_id)
    except data_processing_service.DataProcessingNotFoundError:
        return {
            "continuedSourceRunRef": {
                "runId": source_run_id,
                "status": "missing",
                "recordCount": 0,
                "assignmentCount": 0,
                "openAssignmentCount": 0,
                "message": "Active knowledge-collection round points to a missing source run.",
            }
        }
    assignments = [item for item in list(assignment_payload.get("assignments") or []) if isinstance(item, dict)]
    assignment_summary = _source_collection_assignment_stage_summary(assignments)
    summary = run.get("summary") if isinstance(run.get("summary"), dict) else {}
    scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
    data_search_plan_ref = scope.get("dataSearchPlanRef") if isinstance(scope.get("dataSearchPlanRef"), dict) else {}
    return {
        "run": run,
        "assignments": assignments,
        "assignmentCount": len(assignments),
        "continuedSourceRunRef": {
            "runId": source_run_id,
            "status": str(run.get("status") or ""),
            "recordCount": _normalize_int(summary.get("recordCount"), default=0, minimum=0, maximum=100000),
            "assignmentCount": _normalize_int(summary.get("assignmentCount"), default=len(assignments), minimum=0, maximum=100000),
            "openAssignmentCount": _normalize_int(summary.get("openAssignmentCount"), default=0, minimum=0, maximum=100000),
            "searchOpenAssignmentCount": assignment_summary["searchOpenAssignmentCount"],
            "collectionOpenAssignmentCount": assignment_summary["collectionOpenAssignmentCount"],
            "downstreamOpenAssignmentCount": assignment_summary["downstreamOpenAssignmentCount"],
            "queryCount": _normalize_int(data_search_plan_ref.get("queryCount"), default=0, minimum=0, maximum=SOURCE_COLLECTION_MAX_QUERIES),
            "planId": _trim_text(data_search_plan_ref.get("planId"), max_length=160),
            "externalSearchTriggered": bool(data_search_plan_ref.get("externalSearchTriggered")),
            "message": "Reused the active source-collection run instead of creating a new one.",
        },
    }


def _build_stage_round(
    team_id: str,
    stage_type: str,
    payload: dict[str, Any],
    rounds: list[dict[str, Any]],
    *,
    previous_round: dict[str, Any] | None,
    requested_by_agent: str,
    team: dict[str, Any],
) -> dict[str, Any]:
    now = utc_now_iso()
    round_number = _stage_round_number(rounds, stage_type)
    topic = _trim_text(payload.get("topic"), max_length=500) or _trim_text(previous_round.get("topic") if previous_round else "", max_length=500)
    goal = _trim_text(payload.get("goal"), max_length=1000) or _trim_text(previous_round.get("goal") if previous_round else "", max_length=1000)
    if stage_type == "knowledge_collection" and not topic:
        raise TeamWorkflowOrchestrationError("Research topic is required to start knowledge collection.")
    if not topic:
        topic = _stage_default_topic(stage_type, previous_round)
    if not goal:
        goal = _stage_default_goal(stage_type, previous_round)
    query_seeds = _stage_query_seeds(payload, previous_round, topic=topic, goal=goal)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "stageRoundId": _new_record_id("stage"),
        "teamId": team_id,
        "stageType": stage_type,
        "roundNumber": round_number,
        "status": "initializing",
        "title": _trim_text(payload.get("title"), max_length=180) or f"{RESEARCH_STAGE_DEFAULTS[stage_type]['title']} {round_number}",
        "topic": topic,
        "goal": goal,
        "requestedByAgent": requested_by_agent,
        "ownerAgentId": _source_collection_owner_agent_id(team, payload),
        "upstreamRoundIds": _stage_upstream_round_ids(payload, rounds, stage_type, previous_round),
        "sourceRunIds": [],
        "assignmentIds": [],
        "agentRoleAssignments": [],
        "querySeeds": query_seeds,
        "suggestedQuerySeeds": _suggest_stage_query_seeds(previous_round, topic=topic, goal=goal),
        "inputRefs": _normalize_text_list(payload.get("inputRefs"), max_items=120, max_length=240),
        "searchLanguages": _source_collection_search_languages(payload.get("searchLanguages")),
        "sourceTypes": _source_collection_source_types(payload.get("sourceTypes")),
        "maxResultsPerQuery": _normalize_int(
            payload.get("maxResultsPerQuery"),
            default=SOURCE_COLLECTION_DEFAULT_MAX_RESULTS_PER_QUERY,
            minimum=1,
            maximum=100,
        ),
        "workflowItemRef": {},
        "dataSearchPlanRef": {},
        "teamMemoryRecordId": "",
        "teamMemoryRecord": {},
        "coordinationContract": {},
        "planningContract": {},
        "warnings": [],
        "boundaries": _research_stage_boundaries(),
        "createdAt": now,
        "updatedAt": now,
    }


def _stage_source_collection_payload(stage_round: dict[str, Any], payload: dict[str, Any], team: dict[str, Any]) -> dict[str, Any]:
    scope = _normalize_metadata(payload.get("scope"))
    scope.update(
        {
            "workflowStage": "knowledge_collection",
            "researchStageRoundId": stage_round["stageRoundId"],
            "researchStageRoundNumber": stage_round["roundNumber"],
            "uiEntry": _trim_text(scope.get("uiEntry"), max_length=120) or "teams_research_stage_launcher",
            "upstreamRoundIds": list(stage_round.get("upstreamRoundIds") or []),
        }
    )
    roles = _normalize_source_collection_roles(payload.get("agentRoles"))
    return {
        "title": stage_round["title"],
        "topic": stage_round["topic"],
        "goal": stage_round["goal"],
        "ownerAgentId": stage_round["ownerAgentId"],
        "requestedByAgent": stage_round["requestedByAgent"],
        "agentRoles": payload.get("agentRoles") or list(SOURCE_COLLECTION_DEFAULT_AGENT_ROLES),
        "agentIds": payload.get("agentIds") if isinstance(payload.get("agentIds"), dict) else _source_collection_team_agent_ids(team, roles, payload),
        "inputRefs": list(stage_round.get("inputRefs") or []),
        "querySeeds": list(stage_round.get("querySeeds") or []),
        "searchLanguages": list(stage_round.get("searchLanguages") or []),
        "sourceTypes": list(stage_round.get("sourceTypes") or []),
        "maxResultsPerQuery": int(stage_round.get("maxResultsPerQuery") or SOURCE_COLLECTION_DEFAULT_MAX_RESULTS_PER_QUERY),
        "promptCachePolicy": payload.get("promptCachePolicy") if isinstance(payload.get("promptCachePolicy"), dict) else {},
        "scope": scope,
    }


def _stage_query_seeds(payload: dict[str, Any], previous_round: dict[str, Any] | None, *, topic: str, goal: str) -> list[str]:
    seeds = _normalize_text_list(payload.get("querySeeds"), max_items=40, max_length=220)
    if seeds:
        return seeds
    suggested = _suggest_stage_query_seeds(previous_round, topic=topic, goal=goal)
    if suggested:
        return suggested[:8]
    return [item for item in [topic, goal] if item][:2]


def _suggest_stage_query_seeds(previous_round: dict[str, Any] | None, *, topic: str, goal: str) -> list[str]:
    seeds: list[str] = []
    if previous_round:
        for warning in list(previous_round.get("warnings") or []):
            if isinstance(warning, dict):
                _append_source_collection_seed(seeds, warning.get("message"))
        for item in list(previous_round.get("suggestedQuerySeeds") or [])[:6]:
            _append_source_collection_seed(seeds, item)
        for item in list(previous_round.get("querySeeds") or [])[:6]:
            _append_source_collection_seed(seeds, f"{item} missing evidence")
    _append_source_collection_seed(seeds, topic)
    if goal:
        _append_source_collection_seed(seeds, goal)
    return seeds[:10]


def _stage_upstream_round_ids(
    payload: dict[str, Any],
    rounds: list[dict[str, Any]],
    stage_type: str,
    previous_round: dict[str, Any] | None,
) -> list[str]:
    explicit = _normalize_text_list(payload.get("upstreamRoundIds"), max_items=24, max_length=160)
    if explicit:
        return explicit
    if stage_type == "knowledge_collection":
        return [str(previous_round.get("stageRoundId"))] if previous_round and previous_round.get("stageRoundId") else []
    if stage_type == "experiment":
        latest_collection = _latest_stage_round([item for item in rounds if str(item.get("stageType") or "") == "knowledge_collection"])
        return [str(latest_collection.get("stageRoundId"))] if latest_collection and latest_collection.get("stageRoundId") else []
    latest_experiment = _latest_stage_round([item for item in rounds if str(item.get("stageType") or "") == "experiment"])
    return [str(latest_experiment.get("stageRoundId"))] if latest_experiment and latest_experiment.get("stageRoundId") else []


def _stage_default_topic(stage_type: str, previous_round: dict[str, Any] | None) -> str:
    if previous_round:
        inherited = _trim_text(previous_round.get("topic"), max_length=500)
        if inherited:
            return inherited
    return {
        "experiment": "challenge cup experiment planning",
        "iteration": "challenge cup iteration planning",
    }.get(stage_type, "challenge cup research")


def _stage_default_goal(stage_type: str, previous_round: dict[str, Any] | None) -> str:
    if previous_round:
        inherited = _trim_text(previous_round.get("goal"), max_length=1000)
        if inherited:
            return inherited
    if stage_type == "experiment":
        return "Plan experiments from accepted knowledge-collection candidates without executing them automatically."
    if stage_type == "iteration":
        return "Plan the next improvement round from experiment evidence and unresolved risks."
    return "Collect traceable research sources for neuroscience-inspired algorithm discovery."


def _stage_memory_record(stage_round: dict[str, Any], workflow: dict[str, Any]) -> dict[str, Any]:
    return {
        "recordId": _new_record_id("stagemem"),
        "recordKind": "team_workflow_stage_record",
        "workflowId": workflow.get("workflowId", DEFAULT_WORKFLOW_ID),
        "stageRoundId": stage_round.get("stageRoundId", ""),
        "stageType": stage_round.get("stageType", ""),
        "roundNumber": stage_round.get("roundNumber", 0),
        "status": stage_round.get("status", ""),
        "topic": stage_round.get("topic", ""),
        "goal": stage_round.get("goal", ""),
        "sourceRunIds": list(stage_round.get("sourceRunIds") or []),
        "upstreamRoundIds": list(stage_round.get("upstreamRoundIds") or []),
        "promptCachePolicyRef": _source_collection_prompt_cache_policy_ref(stage_round.get("promptCachePolicy") if isinstance(stage_round.get("promptCachePolicy"), dict) else {}),
        "boundary": "runtime_stage_record_only_not_formal_team_knowledge",
        "createdAt": utc_now_iso(),
    }


def _stage_coordination_contract(team: dict[str, Any], stage_round: dict[str, Any], *, trigger: str = "manual") -> dict[str, Any]:
    linked_room_id = _trim_text(team.get("linkedChatRoomId"), max_length=160)
    stage_type = str(stage_round.get("stageType") or "")
    topic = str(stage_round.get("topic") or "")
    linked_room = chat_room_service.get_chat_room_compact(linked_room_id) if linked_room_id else None
    room_mode = _trim_text((linked_room or {}).get("mode"), max_length=80) or "round_robin"
    normalized_trigger = _trim_text(trigger, max_length=80) or "manual"
    return {
        "contractKind": "team_coordination_round_contract",
        "linkedChatRoomId": linked_room_id,
        "stageRoundId": stage_round.get("stageRoundId", ""),
        "stageType": stage_type,
        "topic": f"{_stage_label(stage_type)}：{topic}",
        "purpose": _stage_coordination_purpose(stage_type),
        "mode": room_mode,
        "autoStarted": False,
        "trigger": normalized_trigger,
        "expectedAction": "Start a lightweight team coordination round only after an explicit user action.",
        "config": {
            "source": f"research_stage_{normalized_trigger}",
            "teamId": team.get("teamId", ""),
            "stageRoundId": stage_round.get("stageRoundId", ""),
            "sourceRunIds": list(stage_round.get("sourceRunIds") or []),
        },
    }


def _stage_coordination_manual_pending_result(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "started": False,
        "roomId": _trim_text(contract.get("linkedChatRoomId"), max_length=160),
        "reason": "Team coordination is available but was not auto-started. Use the explicit coordination action when discussion is needed.",
        "errorType": "",
        "skipped": True,
        "skipReason": "manual_only",
    }


def _try_start_stage_coordination_round(team: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    linked_room_id = _trim_text(contract.get("linkedChatRoomId"), max_length=160)
    if not linked_room_id:
        return {
            "started": False,
            "reason": "Team has no linked chat room.",
            "errorType": "missing_linked_chat_room",
        }
    try:
        round_payload = chat_room_service.start_chat_room_round(
            linked_room_id,
            str(contract.get("topic") or ""),
            mode=str(contract.get("mode") or ""),
            purpose=str(contract.get("purpose") or ""),
            config=contract.get("config") if isinstance(contract.get("config"), dict) else {},
            background=True,
            lightweight_response=True,
        )
    except Exception as exc:
        return {
            "started": False,
            "roomId": linked_room_id,
            "reason": _trim_text(str(exc), max_length=500),
            "errorType": type(exc).__name__,
        }
    return {
        "started": True,
        "roomId": str(round_payload.get("roomId") or linked_room_id),
        "roundId": str(round_payload.get("roundId") or round_payload.get("activeRoundId") or ""),
        "status": str(round_payload.get("status") or ""),
    }


def _stage_planning_contract(stage_type: str, stage_round: dict[str, Any]) -> dict[str, Any]:
    if stage_type == "experiment":
        expected_outputs = ["experiment_plan", "baseline_selection", "success_metrics", "risk_controls"]
    elif stage_type == "iteration":
        expected_outputs = ["iteration_goal", "change_list", "evidence_to_compare", "next_round_entry"]
    else:
        expected_outputs = ["source_manifest_candidates"]
    return {
        "contractKind": f"{stage_type}_planning_contract",
        "stageRoundId": stage_round.get("stageRoundId", ""),
        "expectedOutputs": expected_outputs,
        "autoExecution": False,
        "requiresUserDecision": True,
    }


def _experiment_planning_status(
    team_id: str,
    rounds: list[dict[str, Any]],
    candidate_store: dict[str, Any],
    plan_store: dict[str, Any],
) -> dict[str, Any]:
    experiment_rounds = [item for item in rounds if str(item.get("stageType") or "") == "experiment"]
    latest_experiment = _latest_stage_round(experiment_rounds)
    latest_collection = _latest_stage_round([item for item in rounds if str(item.get("stageType") or "") == "knowledge_collection"])
    hypothesis_candidates = _experiment_hypothesis_summaries(candidate_store)
    ready_hypotheses = [item for item in hypothesis_candidates if item.get("valid") and not item.get("missingExperimentPlanFields")]
    plans = _experiment_plans(plan_store)
    active_plan = _active_experiment_plan(plan_store)
    gaps = _experiment_planning_gaps(
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
        "schemaVersion": SCHEMA_VERSION,
        "teamId": team_id,
        "status": status,
        "latestExperimentRound": latest_experiment,
        "latestKnowledgeCollectionRound": latest_collection,
        "activePlan": active_plan,
        "plans": plans[-12:],
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
        },
        "readiness": {
            "readyToPlan": bool(latest_experiment and ready_hypotheses),
            "readyForSmoke": bool((active_plan or {}).get("readiness", {}).get("readyForSmoke")),
            "readyForFullRun": bool((active_plan or {}).get("readiness", {}).get("readyForFullRun")),
            "readyForKnowledgeIngestion": bool((active_plan or {}).get("readiness", {}).get("readyForKnowledgeIngestion")),
            "reason": _experiment_planning_readiness_reason(latest_experiment, ready_hypotheses, active_plan),
        },
        "boundaries": _experiment_planning_boundaries(),
        "storagePath": _relative_path(_experiment_plan_store_path(team_id)),
        "nextActions": _experiment_planning_next_actions(active_plan=active_plan, gaps=gaps),
        "updatedAt": str(plan_store.get("updatedAt") or ""),
    }


def _select_experiment_stage_round(payload: dict[str, Any], rounds: list[dict[str, Any]]) -> dict[str, Any]:
    explicit_round_id = _trim_text(payload.get("stageRoundId"), max_length=160)
    if explicit_round_id:
        stage_round = _find_stage_round(rounds, explicit_round_id)
        if stage_round is None or str(stage_round.get("stageType") or "") != "experiment":
            raise TeamWorkflowOrchestrationError("Experiment stage round not found.")
        return stage_round
    active_round = _active_stage_round(rounds, "experiment")
    if active_round:
        return active_round
    latest_round = _latest_stage_round([item for item in rounds if str(item.get("stageType") or "") == "experiment"])
    if latest_round:
        return latest_round
    raise TeamWorkflowOrchestrationError("Start an experiment planning stage round before drafting an experiment plan.")


def _select_experiment_hypothesis_candidates(candidate_store: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = _experiment_hypothesis_candidates(candidate_store)
    explicit_ids = _normalize_text_list(payload.get("hypothesisCandidateIds"), max_items=16, max_length=160)
    if explicit_ids:
        by_id = {str(item.get("candidateId") or ""): item for item in candidates}
        selected = [by_id[item_id] for item_id in explicit_ids if item_id in by_id]
        if len(selected) != len(explicit_ids):
            raise TeamWorkflowOrchestrationError("One or more hypothesis candidates were not found.")
        return selected
    ready = [
        item
        for item in candidates
        if validate_candidate_record(item).get("valid") is True
        and not _experiment_hypothesis_missing_fields(item)
        and not _candidate_is_archived(item)
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
    now = utc_now_iso()
    hypothesis_summaries = [_experiment_hypothesis_summary(item) for item in selected_hypotheses]
    payload_plan = payload.get("experimentPlan") if isinstance(payload.get("experimentPlan"), dict) else {}
    dataset = _first_non_empty_text(payload.get("dataset"), payload_plan.get("dataset"), *[item.get("experimentPlan", {}).get("dataset") for item in hypothesis_summaries])
    metric = _first_non_empty_text(payload.get("metric"), payload_plan.get("metric"), *[item.get("experimentPlan", {}).get("metric") for item in hypothesis_summaries])
    baseline = _first_non_empty_text(payload.get("baseline"), payload_plan.get("baseline"), *[item.get("experimentPlan", {}).get("baseline") for item in hypothesis_summaries], *[item.get("baseline") for item in hypothesis_summaries])
    smoke_plan = _first_non_empty_text(payload.get("smokePlan"), payload_plan.get("smokePlan"), *[item.get("experimentPlan", {}).get("smokePlan") for item in hypothesis_summaries])
    checklist = _experiment_plan_checklist(
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
    return {
        "schemaVersion": SCHEMA_VERSION,
        "planId": _new_record_id("exp-plan"),
        "teamId": team_id,
        "workflowId": workflow.get("workflowId", DEFAULT_WORKFLOW_ID),
        "stageRoundId": stage_round.get("stageRoundId", ""),
        "stageRoundNumber": stage_round.get("roundNumber", 0),
        "status": "draft",
        "title": _trim_text(payload.get("title"), max_length=240) or f"Experiment plan for {stage_round.get('topic') or 'Challenge Cup'}",
        "topic": stage_round.get("topic", ""),
        "goal": stage_round.get("goal", ""),
        "selectedHypotheses": hypothesis_summaries,
        "hypothesisCandidateIds": [str(item.get("candidateId") or "") for item in selected_hypotheses if item.get("candidateId")],
        "upstreamRoundIds": list(stage_round.get("upstreamRoundIds") or []),
        "experimentPlan": {
            "dataset": dataset,
            "metric": metric,
            "baseline": baseline,
            "smokePlan": smoke_plan,
        },
        "baselineSelection": {
            "baseline": baseline,
            "status": "planned_not_validated" if baseline else "missing",
            "activeBaselineReady": False,
            "reason": "Baseline is selected from candidate evidence, but no reproducible active baseline artifact has been registered yet."
            if baseline
            else "No baseline selected yet.",
        },
        "successMetrics": _dedupe_text_values([metric]),
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
        "notes": _trim_text(payload.get("notes"), max_length=4000),
        "createdByAgent": created_by_agent,
        "createdAt": now,
        "updatedAt": now,
    }


def _experiment_hypothesis_candidates(candidate_store: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = [
        item
        for item in list(candidate_store.get("candidates") or [])
        if isinstance(item, dict)
        and str(item.get("candidateType") or "") == "algorithm_hypothesis"
        and not _candidate_is_archived(item)
    ]
    return sorted(candidates, key=lambda item: (str(item.get("updatedAt") or ""), str(item.get("candidateId") or "")), reverse=True)


def _experiment_hypothesis_summaries(candidate_store: dict[str, Any]) -> list[dict[str, Any]]:
    return [_experiment_hypothesis_summary(item) for item in _experiment_hypothesis_candidates(candidate_store)]


def _experiment_hypothesis_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    output = metadata.get("output") if isinstance(metadata.get("output"), dict) else {}
    experiment_plan = output.get("experimentPlan") if isinstance(output.get("experimentPlan"), dict) else {}
    validation = validate_candidate_record(candidate)
    missing_fields = [field for field in EXPERIMENT_PLAN_REQUIRED_FIELDS if not _has_value(experiment_plan.get(field))]
    return {
        "candidateId": str(candidate.get("candidateId") or ""),
        "title": str(candidate.get("title") or ""),
        "summary": str(candidate.get("summary") or ""),
        "currentWorkflowNode": str(candidate.get("currentWorkflowNode") or ""),
        "currentState": str(candidate.get("currentState") or ""),
        "qualityStatus": str(candidate.get("qualityStatus") or ""),
        "valid": validation.get("valid") is True,
        "validationIssueCount": len(validation.get("issues") or []),
        "hypothesis": _trim_text(output.get("hypothesis"), max_length=1000),
        "baseline": _trim_text(output.get("baseline"), max_length=500),
        "expectedBenefit": _trim_text(output.get("expectedBenefit"), max_length=1000),
        "expectedComputeCost": _trim_text(output.get("expectedComputeCost"), max_length=1000),
        "experimentPlan": {
            "dataset": _trim_text(experiment_plan.get("dataset"), max_length=500),
            "metric": _trim_text(experiment_plan.get("metric"), max_length=500),
            "baseline": _trim_text(experiment_plan.get("baseline"), max_length=500),
            "smokePlan": _trim_text(experiment_plan.get("smokePlan"), max_length=1200),
        },
        "missingExperimentPlanFields": missing_fields,
        "sourceRefs": _normalize_ref_list(candidate.get("sourceRefs") or output.get("sourceRefs"), max_items=12),
        "evidenceRefs": _normalize_ref_list(candidate.get("evidenceRefs") or output.get("evidenceRefs"), max_items=12),
        "updatedAt": str(candidate.get("updatedAt") or ""),
    }


def _experiment_hypothesis_missing_fields(candidate: dict[str, Any]) -> list[str]:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    output = metadata.get("output") if isinstance(metadata.get("output"), dict) else {}
    experiment_plan = output.get("experimentPlan") if isinstance(output.get("experimentPlan"), dict) else {}
    return [field for field in EXPERIMENT_PLAN_REQUIRED_FIELDS if not _has_value(experiment_plan.get(field))]


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
    experiment_plan = plan.get("experimentPlan") if isinstance(plan.get("experimentPlan"), dict) else {}
    baseline_selection = plan.get("baselineSelection") if isinstance(plan.get("baselineSelection"), dict) else {}
    artifact_path = _trim_text(payload.get("artifactPath"), max_length=500)
    reproduction_command = _trim_text(payload.get("reproductionCommand"), max_length=1200)
    if not artifact_path:
        raise TeamWorkflowOrchestrationError("Baseline artifact path is required.")
    if not reproduction_command:
        raise TeamWorkflowOrchestrationError("Baseline reproduction command is required.")
    now = utc_now_iso()
    return {
        "artifactId": _new_record_id("baseline-artifact"),
        "status": "registered",
        "baseline": _first_non_empty_text(payload.get("baselineName"), baseline_selection.get("baseline"), experiment_plan.get("baseline")),
        "dataset": _first_non_empty_text(payload.get("datasetRef"), experiment_plan.get("dataset")),
        "metric": _first_non_empty_text(payload.get("metricName"), experiment_plan.get("metric")),
        "metricValue": _trim_text(payload.get("metricValue"), max_length=240),
        "artifactPath": artifact_path,
        "evidenceRef": _trim_text(payload.get("evidenceRef"), max_length=500),
        "reproductionCommand": reproduction_command,
        "evaluationCommand": _trim_text(payload.get("evaluationCommand"), max_length=1200),
        "sourceRefs": _normalize_ref_list(payload.get("sourceRefs"), max_items=12),
        "evidenceRefs": _normalize_ref_list(payload.get("evidenceRefs"), max_items=12),
        "notes": _trim_text(payload.get("notes"), max_length=4000),
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
    baseline_selection = plan.get("baselineSelection") if isinstance(plan.get("baselineSelection"), dict) else {}
    active_baseline_artifact = (
        baseline_selection.get("activeBaselineArtifact")
        if isinstance(baseline_selection.get("activeBaselineArtifact"), dict)
        else None
    )
    if not active_baseline_artifact:
        raise TeamWorkflowOrchestrationError("Register an active baseline artifact before recording smoke results.")
    experiment_plan = plan.get("experimentPlan") if isinstance(plan.get("experimentPlan"), dict) else {}
    status = _trim_text(payload.get("status"), max_length=80).lower() or "needs_review"
    if status not in EXPERIMENT_SMOKE_RESULT_STATUSES:
        raise TeamWorkflowOrchestrationError(f"Unsupported smoke result status: {status}")
    metric_value = _trim_text(payload.get("metricValue"), max_length=240)
    result_path = _trim_text(payload.get("resultPath") or payload.get("artifactPath"), max_length=500)
    log_ref = _trim_text(payload.get("logRef") or payload.get("evidenceRef"), max_length=500)
    if not metric_value:
        raise TeamWorkflowOrchestrationError("Smoke result metric value is required.")
    if not result_path and not log_ref:
        raise TeamWorkflowOrchestrationError("Smoke result path or log reference is required.")
    now = utc_now_iso()
    gate_decision = {
        "passed": "promote_to_full_run",
        "failed": "reject_or_repair",
        "needs_review": "needs_more_evidence",
    }[status]
    return {
        "smokeResultId": _new_record_id("smoke-result"),
        "status": status,
        "gateDecision": gate_decision,
        "planId": str(plan.get("planId") or ""),
        "baselineArtifactId": str(active_baseline_artifact.get("artifactId") or ""),
        "baselineMetricValue": _first_non_empty_text(payload.get("baselineMetricValue"), active_baseline_artifact.get("metricValue")),
        "metricName": _first_non_empty_text(payload.get("metricName"), active_baseline_artifact.get("metric"), experiment_plan.get("metric")),
        "metricValue": metric_value,
        "delta": _trim_text(payload.get("delta"), max_length=240),
        "resultPath": result_path,
        "logRef": log_ref,
        "evaluationCommand": _trim_text(payload.get("evaluationCommand") or payload.get("command"), max_length=1200),
        "sourceRefs": _normalize_ref_list(payload.get("sourceRefs"), max_items=12),
        "evidenceRefs": _normalize_ref_list(payload.get("evidenceRefs"), max_items=12),
        "notes": _trim_text(payload.get("notes"), max_length=4000),
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
    active_smoke_result = plan.get("activeSmokeResult") if isinstance(plan.get("activeSmokeResult"), dict) else None
    if not active_smoke_result or str(active_smoke_result.get("status") or "").strip().lower() != "passed":
        raise TeamWorkflowOrchestrationError("Record a passing smoke result before recording full-run results.")
    if not bool((plan.get("readiness") or {}).get("readyForFullRun")):
        raise TeamWorkflowOrchestrationError("Experiment plan is not ready for full-run result recording.")
    status = _trim_text(payload.get("status"), max_length=80).lower() or "needs_review"
    if status not in EXPERIMENT_FULL_RUN_RESULT_STATUSES:
        raise TeamWorkflowOrchestrationError(f"Unsupported full-run result status: {status}")
    metric_value = _trim_text(payload.get("metricValue"), max_length=240)
    result_path = _trim_text(payload.get("resultPath") or payload.get("artifactPath"), max_length=500)
    log_ref = _trim_text(payload.get("logRef") or payload.get("evidenceRef"), max_length=500)
    if not metric_value:
        raise TeamWorkflowOrchestrationError("Full-run result metric value is required.")
    if not result_path and not log_ref:
        raise TeamWorkflowOrchestrationError("Full-run result path or log reference is required.")
    baseline_selection = plan.get("baselineSelection") if isinstance(plan.get("baselineSelection"), dict) else {}
    active_baseline_artifact = (
        baseline_selection.get("activeBaselineArtifact")
        if isinstance(baseline_selection.get("activeBaselineArtifact"), dict)
        else {}
    )
    experiment_plan = plan.get("experimentPlan") if isinstance(plan.get("experimentPlan"), dict) else {}
    now = utc_now_iso()
    gate_decision = {
        "passed": "ready_for_knowledge_review",
        "failed": "reject_or_repair",
        "needs_review": "needs_more_evidence",
    }[status]
    return {
        "fullRunResultId": _new_record_id("full-run-result"),
        "status": status,
        "gateDecision": gate_decision,
        "planId": str(plan.get("planId") or ""),
        "smokeResultId": str(active_smoke_result.get("smokeResultId") or ""),
        "baselineArtifactId": str(active_baseline_artifact.get("artifactId") or ""),
        "baselineMetricValue": _first_non_empty_text(payload.get("baselineMetricValue"), active_baseline_artifact.get("metricValue")),
        "smokeMetricValue": _first_non_empty_text(payload.get("smokeMetricValue"), active_smoke_result.get("metricValue")),
        "metricName": _first_non_empty_text(payload.get("metricName"), active_smoke_result.get("metricName"), active_baseline_artifact.get("metric"), experiment_plan.get("metric")),
        "metricValue": metric_value,
        "delta": _trim_text(payload.get("delta"), max_length=240),
        "resultPath": result_path,
        "logRef": log_ref,
        "configPath": _trim_text(payload.get("configPath"), max_length=500),
        "reproductionCommand": _trim_text(payload.get("reproductionCommand"), max_length=1200),
        "evaluationCommand": _trim_text(payload.get("evaluationCommand") or payload.get("command"), max_length=1200),
        "sourceRefs": _normalize_ref_list(payload.get("sourceRefs"), max_items=12),
        "evidenceRefs": _normalize_ref_list(payload.get("evidenceRefs"), max_items=12),
        "notes": _trim_text(payload.get("notes"), max_length=4000),
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
    active_full_run = plan.get("activeFullRunResult") if isinstance(plan.get("activeFullRunResult"), dict) else None
    if not active_full_run or str(active_full_run.get("status") or "").strip().lower() != "passed":
        raise TeamWorkflowOrchestrationError("Record a passing full-run result before requesting knowledge ingestion.")
    experiment_plan = plan.get("experimentPlan") if isinstance(plan.get("experimentPlan"), dict) else {}
    baseline_selection = plan.get("baselineSelection") if isinstance(plan.get("baselineSelection"), dict) else {}
    active_baseline_artifact = (
        baseline_selection.get("activeBaselineArtifact")
        if isinstance(baseline_selection.get("activeBaselineArtifact"), dict)
        else {}
    )
    active_smoke_result = plan.get("activeSmokeResult") if isinstance(plan.get("activeSmokeResult"), dict) else {}
    now = utc_now_iso()
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
        "packId": _new_record_id("experiment-result-pack"),
        "kind": "challenge_cup_experiment_result_pack",
        "status": "ready_for_knowledge_steward",
        "planId": str(plan.get("planId") or ""),
        "teamId": str(plan.get("teamId") or ""),
        "stageRoundId": str(plan.get("stageRoundId") or ""),
        "fullRunResultId": str(active_full_run.get("fullRunResultId") or ""),
        "knowledgeBaseId": knowledge_base_id,
        "targetDomain": target_domain,
        "title": _trim_text(payload.get("title"), max_length=240) or f"Experiment result for {plan.get('title') or plan.get('topic') or 'Challenge Cup'}",
        "summary": _trim_text(payload.get("summary"), max_length=4000)
        or f"Full-run {active_full_run.get('status')} result: {active_full_run.get('metricName') or experiment_plan.get('metric')} = {active_full_run.get('metricValue')}.",
        "hypothesisCandidateIds": [str(item.get("candidateId") or "") for item in selected_hypotheses if item.get("candidateId")],
        "selectedHypotheses": selected_hypotheses,
        "experimentPlan": {
            "dataset": _trim_text(experiment_plan.get("dataset"), max_length=500),
            "metric": _trim_text(experiment_plan.get("metric"), max_length=500),
            "baseline": _trim_text(experiment_plan.get("baseline"), max_length=500),
            "smokePlan": _trim_text(experiment_plan.get("smokePlan"), max_length=1200),
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
        "sourceRefs": _normalize_ref_list(payload.get("sourceRefs") or active_full_run.get("sourceRefs"), max_items=12),
        "evidenceRefs": _normalize_ref_list(payload.get("evidenceRefs") or active_full_run.get("evidenceRefs"), max_items=12),
        "notes": _trim_text(payload.get("notes"), max_length=4000),
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

    target_agent = agent_directory_service.get_agent(steward_agent_id, include_archived=True)
    if not target_agent:
        activation["status"] = "skipped_missing_steward_agent"
        return activation
    if str(target_agent.get("status") or "active").strip().lower() == "archived":
        activation["status"] = "skipped_archived_steward_agent"
        return activation

    source_agent_id = requester_agent_id if requester_agent_id and agent_directory_service.get_agent(requester_agent_id, include_archived=True) else ""
    content = "\n".join(
        [
            "[挑战杯实验结果入库请求]",
            f"团队: {team_id}",
            f"实验计划: {plan_id}",
            f"实验结果包: {pack_id}",
            f"Full-run 结果: {full_run_result_id}",
            f"目标知识库: {knowledge_base_id}",
            f"知识域: {target_domain}",
            "",
            "请作为知识库管理员 Agent 处理这个已复核实验结果包：",
            "1. 读取 Team workflow experiment_plans/index.json 中的 knowledgeIngestion.experimentResultPack。",
            "2. 复核 hypothesis、experimentPlan、metrics、artifactRefs、sourceRefs 和 evidenceRefs。",
            "3. 只把整理后的实验结论写入正式 Team Knowledge/RAG；原始日志和大文件保持路径引用。",
            "4. 无法确认时标记 needs_revision，不要把 raw logs 直接写入正式知识库。",
        ]
    )
    thread_id = f"challenge-cup-experiment-ingestion:{team_id}:{pack_id}"
    message_summary = f"挑战杯实验结果包 {pack_id} 请求最终入库。"
    try:
        message, delivery, kernel_result = _submit_team_workflow_inbox_via_kernel(
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
            "kernel": _team_workflow_kernel_summary(kernel_result),
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
    experiment_plan = plan.get("experimentPlan") if isinstance(plan.get("experimentPlan"), dict) else {}
    baseline_selection = plan.get("baselineSelection") if isinstance(plan.get("baselineSelection"), dict) else {}
    active_baseline_artifact = baseline_selection.get("activeBaselineArtifact") if isinstance(baseline_selection.get("activeBaselineArtifact"), dict) else None
    checklist = _experiment_plan_checklist(
        stage_round={"stageRoundId": plan.get("stageRoundId", "")} if plan.get("stageRoundId") else {},
        hypothesis_summaries=[item for item in list(plan.get("selectedHypotheses") or []) if isinstance(item, dict)],
        dataset=_trim_text(experiment_plan.get("dataset"), max_length=500),
        metric=_trim_text(experiment_plan.get("metric"), max_length=500),
        baseline=_trim_text(experiment_plan.get("baseline") or baseline_selection.get("baseline"), max_length=500),
        smoke_plan=_trim_text(experiment_plan.get("smokePlan"), max_length=1200),
        active_baseline_artifact=active_baseline_artifact,
    )
    smoke_blockers = [item["item"] for item in checklist if item["status"] != "pass"]
    active_smoke_result = plan.get("activeSmokeResult") if isinstance(plan.get("activeSmokeResult"), dict) else None
    active_smoke_status = _trim_text((active_smoke_result or {}).get("status"), max_length=80).lower()
    active_full_run_result = plan.get("activeFullRunResult") if isinstance(plan.get("activeFullRunResult"), dict) else None
    active_full_run_status = _trim_text((active_full_run_result or {}).get("status"), max_length=80).lower()
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
    risk_controls["knowledgeIngestionBlockedUntil"] = knowledge_blockers
    risk_controls["activeFullRunResultStatus"] = active_full_run_status
    plan["riskControls"] = risk_controls


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
    artifact_note = ""
    if active_baseline_artifact:
        artifact_note = _trim_text(
            active_baseline_artifact.get("artifactPath") or active_baseline_artifact.get("evidenceRef"),
            max_length=1200,
        )
    return [
        _experiment_checklist_item("experiment_stage_round", "实验轮次", bool(stage_round), "Experiment planning stage round is available."),
        _experiment_checklist_item("algorithm_hypothesis", "算法假设", bool(hypothesis_summaries), f"{len(hypothesis_summaries)} hypothesis candidate(s) selected."),
        _experiment_checklist_item("dataset", "数据集", bool(dataset), dataset or "Dataset is missing."),
        _experiment_checklist_item("metric", "指标", bool(metric), metric or "Metric is missing."),
        _experiment_checklist_item("baseline", "Baseline", bool(baseline), baseline or "Baseline is missing."),
        _experiment_checklist_item("smoke_plan", "Smoke gate", bool(smoke_plan), smoke_plan or "Smoke plan is missing."),
        _experiment_checklist_item(
            "active_baseline_record",
            "Active baseline",
            bool(active_baseline_artifact),
            artifact_note or "Active baseline artifact is not registered.",
        ),
    ]


def _experiment_checklist_item(item: str, label: str, passed: bool, note: str) -> dict[str, str]:
    return {
        "item": item,
        "label": label,
        "status": "pass" if passed else "needs_attention",
        "note": _trim_text(note, max_length=1200),
    }


def _experiment_planning_gaps(
    *,
    latest_experiment: dict[str, Any] | None,
    hypothesis_candidates: list[dict[str, Any]],
    ready_hypotheses: list[dict[str, Any]],
    active_plan: dict[str, Any] | None,
) -> list[dict[str, str]]:
    gaps: list[dict[str, str]] = []
    if not latest_experiment:
        gaps.append({"code": "missing_experiment_stage_round", "severity": "blocked", "message": "需要先启动实验规划轮次。"})
    if not hypothesis_candidates:
        gaps.append({"code": "missing_algorithm_hypotheses", "severity": "needs_evidence", "message": "还没有 algorithm_hypothesis 候选可转成实验。"})
    elif not ready_hypotheses:
        gaps.append({"code": "incomplete_experiment_plan", "severity": "needs_attention", "message": "已有算法假设，但 dataset、metric、baseline 或 smokePlan 不完整。"})
    if latest_experiment and not active_plan:
        gaps.append({"code": "missing_experiment_plan_draft", "severity": "pending", "message": "实验轮次已启动，但还没有 draft plan 账本记录。"})
    if active_plan and not bool((active_plan.get("baselineSelection") or {}).get("activeBaselineReady")):
        gaps.append({"code": "active_baseline_not_registered", "severity": "needs_attention", "message": "已有计划草稿，但 active baseline artifact 仍未登记，不能进入 full run。"})
    elif active_plan and bool((active_plan.get("readiness") or {}).get("readyForSmoke")) and not bool((active_plan.get("readiness") or {}).get("readyForFullRun")):
        active_smoke_result = active_plan.get("activeSmokeResult") if isinstance(active_plan.get("activeSmokeResult"), dict) else None
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
    if not latest_experiment:
        return "需要先启动实验规划轮次。"
    knowledge_ingestion = active_plan.get("knowledgeIngestion") if isinstance((active_plan or {}).get("knowledgeIngestion"), dict) else None
    if active_plan and knowledge_ingestion:
        return "实验结果包已进入知识库管理员入库请求链路；正式知识仍等待知识治理门禁。"
    active_full_run = active_plan.get("activeFullRunResult") if isinstance((active_plan or {}).get("activeFullRunResult"), dict) else None
    active_full_run_status = _trim_text((active_full_run or {}).get("status"), max_length=80).lower()
    if active_plan and active_full_run_status == "passed":
        return "full-run evidence 已通过；可以生成实验结果包并通知知识库管理员。"
    if active_plan and active_full_run_status:
        return "full-run evidence 已登记但尚未通过；需要复核或修复后再进入知识入库。"
    if active_plan and bool((active_plan.get("readiness") or {}).get("readyForFullRun")):
        return "smoke evidence 已通过；可以进入显式 full-run 决策，但本接口不自动训练。"
    if active_plan and bool((active_plan.get("readiness") or {}).get("readyForSmoke")):
        return "active baseline artifact 已登记；可进入 smoke gate，但 full run 仍等待 smoke 结果。"
    if active_plan:
        return "已有实验计划草稿；下一步补 active baseline artifact 与 smoke 结果。"
    if ready_hypotheses:
        return "已有完整 algorithm_hypothesis，可生成实验计划草稿。"
    return "实验轮次已存在，但缺少完整 algorithm_hypothesis 候选。"


def _experiment_planning_next_actions(*, active_plan: dict[str, Any] | None, gaps: list[dict[str, str]]) -> list[str]:
    gap_codes = {item.get("code") for item in gaps}
    if active_plan and isinstance(active_plan.get("knowledgeIngestion"), dict):
        return ["等待知识库管理员复核实验结果入库包。", "在知识库管理员批准精炼知识项之前，原始日志保持在 RAG 之外。"]
    if "missing_experiment_stage_round" in gap_codes:
        return ["Start the experiment planning stage round.", "Keep training execution disabled until a plan is reviewed."]
    if "missing_algorithm_hypotheses" in gap_codes or "incomplete_experiment_plan" in gap_codes:
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
    plans = _experiment_plans(plan_store)
    active_plan_id = str(plan_store.get("activePlanId") or "")
    if active_plan_id:
        for plan in plans:
            if str(plan.get("planId") or "") == active_plan_id:
                return plan
    return plans[-1] if plans else None


def _first_non_empty_text(*values: Any) -> str:
    for value in values:
        text = _trim_text(value, max_length=1200)
        if text:
            return text
    return ""


def _dedupe_text_values(values: list[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = _trim_text(value, max_length=500)
        if text and text not in result:
            result.append(text)
    return result


def _stage_agent_binding_warnings(assignments: list[dict[str, Any]]) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    for item in assignments:
        agent_role = str(item.get("agentRole") or "")
        agent_id = str(item.get("agentId") or "")
        if agent_role and agent_id == agent_role:
            warnings.append(
                {
                    "code": "agent_binding_missing",
                    "severity": "warning",
                    "message": f"{agent_role} has no concrete team agent binding.",
                }
            )
    return warnings


def _stage_phase_status(
    team_id: str,
    stage_type: str,
    rounds: list[dict[str, Any]],
    *,
    workflow: dict[str, Any],
    team: dict[str, Any],
) -> dict[str, Any]:
    stage_rounds = [item for item in rounds if str(item.get("stageType") or "") == stage_type]
    active_round = _active_stage_round(rounds, stage_type)
    latest_round = active_round or _latest_stage_round(stage_rounds)
    defaults = RESEARCH_STAGE_DEFAULTS[stage_type]
    return {
        "stageType": stage_type,
        "label": _stage_label(stage_type),
        "status": str(latest_round.get("status") if latest_round else "not_started"),
        "roundCount": len(stage_rounds),
        "activeRoundId": str(active_round.get("stageRoundId") if active_round else ""),
        "latestRound": latest_round,
        "primaryAction": defaults["continueActionZh"] if active_round else defaults["primaryActionZh"],
        "secondaryAction": defaults["newRoundActionZh"],
        "canStart": True,
        "canContinue": bool(active_round),
        "canNewRound": bool(stage_rounds),
        "requiresUserDecision": stage_type in {"experiment", "iteration"},
        "readiness": _stage_readiness(stage_type, rounds),
        "coordinationRoomId": str(team.get("linkedChatRoomId") or ""),
        "storagePath": _relative_path(_stage_round_store_path(team_id)),
    }


def _stage_readiness(stage_type: str, rounds: list[dict[str, Any]]) -> dict[str, Any]:
    if stage_type == "knowledge_collection":
        return {"ready": True, "reason": "知识搜集可随时多轮启动。"}
    if stage_type == "experiment":
        latest_collection = _latest_stage_round([item for item in rounds if str(item.get("stageType") or "") == "knowledge_collection"])
        return {
            "ready": bool(latest_collection),
            "reason": "已有知识搜集轮次，可由用户决定进入实验规划。" if latest_collection else "需要先启动至少一轮知识搜集。",
        }
    latest_experiment = _latest_stage_round([item for item in rounds if str(item.get("stageType") or "") == "experiment"])
    return {
        "ready": bool(latest_experiment),
        "reason": "已有实验规划轮次，可进入迭代规划。" if latest_experiment else "需要先启动实验规划。",
    }


def _current_research_stage(phases: list[dict[str, Any]], workflow: dict[str, Any]) -> str:
    for phase in phases:
        if phase.get("activeRoundId"):
            return str(phase.get("stageType") or "")
    state_machine = workflow.get("stateMachine") if isinstance(workflow.get("stateMachine"), dict) else {}
    return str(state_machine.get("currentStage") or "knowledge_collection")


def _stage_next_actions(stage_type: str, *, reused: bool) -> list[str]:
    if reused:
        return ["Continue the active stage round instead of creating a duplicate.", "Open the matching research workspace view."]
    if stage_type == "knowledge_collection":
        return [
            "Open Source collection to inspect query seeds, assignments, and writeback contract.",
            "Functional agents submit CollectionOutput records before candidate import.",
            "User decides whether to start experiment after screening.",
        ]
    if stage_type == "experiment":
        return ["Review upstream knowledge-collection evidence.", "Draft experiment plan; do not auto-run experiments."]
    return ["Review experiment evidence.", "Plan the next iteration round; do not auto-apply changes."]


def _research_stage_boundaries() -> dict[str, bool]:
    return {
        "externalSearchTriggered": False,
        "writesFormalKnowledge": False,
        "writesRag": False,
        "writesOfficialGraph": False,
        "autoTransitionsNextStage": False,
        "stageRecordsOnly": True,
    }


def _stage_label(stage_type: str) -> str:
    return {
        "knowledge_collection": "知识搜集",
        "experiment": "实验",
        "iteration": "迭代",
    }.get(stage_type, stage_type)


def _stage_coordination_purpose(stage_type: str) -> str:
    if stage_type == "knowledge_collection":
        return "围绕资料搜索范围、query seeds、角色分工和结果回写合同进行团队协调。"
    if stage_type == "experiment":
        return "围绕实验目标、baseline、指标和风险控制进行团队规划，不自动执行实验。"
    return "围绕实验反馈、缺口、改动范围和下一轮目标进行团队规划，不自动进入下一轮。"


def _load_official_model_evidence_store(team_id: str) -> dict[str, Any]:
    path = _official_model_evidence_store_path(team_id)
    store = _read_json(path)
    if store.get("storeKind") == "official_model_evidence_store" and isinstance(store.get("evidence"), list):
        return store
    now = utc_now_iso()
    return {
        "schemaVersion": SCHEMA_VERSION,
        "storeKind": "official_model_evidence_store",
        "teamId": team_id,
        "evidence": [],
        "createdAt": now,
        "updatedAt": now,
    }


def _official_model_evidence_entries(store: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in list(store.get("evidence") or []) if isinstance(item, dict)]


def _build_official_model_evidence_record(
    team_id: str,
    workflow: dict[str, Any],
    candidate_store: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    candidate_id = _trim_text(payload.get("candidateId"), max_length=128)
    candidate = _find_candidate_by_id(candidate_store, candidate_id) if candidate_id else None
    candidate_metadata = candidate.get("metadata") if isinstance((candidate or {}).get("metadata"), dict) else {}
    candidate_output = candidate_metadata.get("output") if isinstance(candidate_metadata.get("output"), dict) else {}
    task_type = _normalize_official_model_task_type(payload.get("taskType") or candidate_metadata.get("taskType"))
    workflow_node = _trim_text(payload.get("workflowNode"), max_length=120)
    if not workflow_node and task_type:
        workflow_node = str((LOCAL_RESEARCH_TASKS.get(task_type) or {}).get("workflowNode") or "")
    if not workflow_node and candidate:
        workflow_node = _trim_text(candidate.get("currentWorkflowNode"), max_length=120)
    if not task_type and workflow_node:
        task_type = _official_model_task_type_from_node(workflow_node)
    if not (task_type or workflow_node or candidate_id):
        raise TeamWorkflowOrchestrationError("Model evidence requires taskType, workflowNode, or candidateId.")

    model_id = _trim_text(payload.get("modelId") or candidate_metadata.get("modelId"), max_length=160) or LOCAL_RESEARCH_MODEL_ID
    now = utc_now_iso()
    return {
        "schemaVersion": SCHEMA_VERSION,
        "evidenceId": _new_record_id("model-evidence"),
        "teamId": team_id,
        "workflowId": workflow["workflowId"],
        "workflowKind": workflow["workflowKind"],
        "taskType": task_type,
        "workflowNode": workflow_node or str((LOCAL_RESEARCH_TASKS.get(task_type) or {}).get("workflowNode") or ""),
        "candidateId": candidate_id,
        "stageRoundId": _trim_text(payload.get("stageRoundId"), max_length=128),
        "sourceRunId": _trim_text(payload.get("sourceRunId"), max_length=128),
        "taskId": _trim_text(payload.get("taskId"), max_length=128),
        "modelProvider": _infer_official_model_provider(payload.get("modelProvider") or payload.get("provider"), model_id),
        "modelId": model_id,
        "modelName": _trim_text(payload.get("modelName") or LOCAL_RESEARCH_MODEL_NAME, max_length=240),
        "modelProfileId": _trim_text(payload.get("modelProfileId"), max_length=160),
        "evidenceKind": _normalize_official_model_evidence_kind(payload.get("evidenceKind")),
        "artifactPath": _trim_text(payload.get("artifactPath"), max_length=500),
        "screenshotPath": _trim_text(payload.get("screenshotPath"), max_length=500),
        "logRef": _trim_text(payload.get("logRef"), max_length=500),
        "promptSummary": _trim_text(payload.get("promptSummary"), max_length=1200),
        "outputSummary": _trim_text(payload.get("outputSummary") or candidate_output.get("nextAction") or (candidate or {}).get("summary"), max_length=1200),
        "sourceRefs": _normalize_ref_list(payload.get("sourceRefs") or (candidate or {}).get("sourceRefs"), max_items=32),
        "evidenceRefs": _normalize_ref_list(payload.get("evidenceRefs") or (candidate or {}).get("evidenceRefs"), max_items=32),
        "status": _trim_text(payload.get("status"), max_length=80) or "registered",
        "recordedByAgent": _trim_text(payload.get("recordedByAgent") or payload.get("createdByAgent"), max_length=160),
        "metadata": _normalize_metadata(payload.get("metadata")),
        "officialBoundary": _official_model_evidence_boundary(),
        "createdAt": now,
        "updatedAt": now,
    }


def _official_model_evidence_from_candidates(candidate_store: dict[str, Any], workflow: dict[str, Any]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for candidate in [item for item in list(candidate_store.get("candidates") or []) if isinstance(item, dict)]:
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        task_type = _normalize_official_model_task_type(metadata.get("taskType"))
        model_id = _trim_text(metadata.get("modelId"), max_length=160)
        team_id = str(candidate.get("teamId") or "")
        if not task_type or not model_id or not team_id:
            continue
        evidence.append(
            {
                "schemaVersion": SCHEMA_VERSION,
                "evidenceId": f"candidate-output:{candidate.get('candidateId')}",
                "teamId": team_id,
                "workflowId": workflow["workflowId"],
                "workflowKind": workflow["workflowKind"],
                "taskType": task_type,
                "workflowNode": str(candidate.get("currentWorkflowNode") or (LOCAL_RESEARCH_TASKS.get(task_type) or {}).get("workflowNode") or ""),
                "candidateId": str(candidate.get("candidateId") or ""),
                "stageRoundId": "",
                "sourceRunId": "",
                "taskId": "",
                "modelProvider": _infer_official_model_provider(metadata.get("modelProvider"), model_id),
                "modelId": model_id,
                "modelName": LOCAL_RESEARCH_MODEL_NAME,
                "modelProfileId": "",
                "evidenceKind": "candidate_output",
                "artifactPath": "",
                "screenshotPath": "",
                "logRef": _relative_path(_candidate_store_path(team_id)),
                "promptSummary": "",
                "outputSummary": _trim_text(candidate.get("summary"), max_length=1200),
                "sourceRefs": _normalize_ref_list(candidate.get("sourceRefs"), max_items=32),
                "evidenceRefs": _normalize_ref_list(candidate.get("evidenceRefs"), max_items=32),
                "status": "derived_from_candidate_store",
                "recordedByAgent": str(candidate.get("createdByAgent") or ""),
                "metadata": {"derived": True},
                "officialBoundary": _official_model_evidence_boundary(),
                "createdAt": str(candidate.get("createdAt") or ""),
                "updatedAt": str(candidate.get("updatedAt") or candidate.get("createdAt") or ""),
            }
        )
    return evidence


def _dedupe_official_model_evidence(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in evidence:
        key = str(item.get("evidenceId") or "")
        if not key:
            key = "|".join(
                [
                    str(item.get("taskType") or ""),
                    str(item.get("workflowNode") or ""),
                    str(item.get("candidateId") or ""),
                    str(item.get("modelId") or ""),
                    str(item.get("evidenceKind") or ""),
                ]
            )
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _official_model_evidence_coverage(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    coverage: list[dict[str, Any]] = []
    for spec in OFFICIAL_MODEL_EVIDENCE_REQUIRED_TASKS:
        task_type = str(spec["taskType"])
        workflow_node = str(spec["workflowNode"])
        matches = [
            item
            for item in evidence
            if str(item.get("taskType") or "") == task_type or str(item.get("workflowNode") or "") == workflow_node
        ]
        latest_evidence_id = ""
        if matches:
            latest_evidence_id = str(sorted(matches, key=lambda item: str(item.get("createdAt") or ""), reverse=True)[0].get("evidenceId") or "")
        coverage.append(
            {
                "taskType": task_type,
                "workflowNode": workflow_node,
                "label": spec["label"],
                "status": "covered" if matches else "missing",
                "evidenceCount": len(matches),
                "providers": _count_by_field(matches, "modelProvider"),
                "latestEvidenceId": latest_evidence_id,
            }
        )
    return coverage


def _official_model_evidence_action_items(missing_nodes: list[dict[str, Any]], summary: dict[str, int]) -> list[dict[str, Any]]:
    action_items = [
        {
            "code": "model_evidence_missing_node",
            "severity": "needs_evidence",
            "message": f"{item['label']} 缺少 Qwen/百炼/本地模型调用证据。",
            "nextAction": "登记 invocation_log、sample_output 或截图证据；不要直接写正式知识。",
            "workflowNode": item["workflowNode"],
            "taskType": item["taskType"],
        }
        for item in missing_nodes
    ]
    if summary.get("storedEvidenceCount", 0) == 0 and summary.get("candidateOutputEvidenceCount", 0) > 0:
        action_items.append(
            {
                "code": "model_evidence_only_derived",
                "severity": "pending",
                "message": "当前只有 CandidateStore 派生输出证据，还缺真实调用日志、配置或百炼截图证据。",
                "nextAction": "把模型调用日志、百炼任务截图或配置证明登记到 official_model_evidence store。",
                "workflowNode": "knowledge_collection",
                "taskType": "source_screening",
            }
        )
    return action_items[:12]


def _official_model_evidence_boundary() -> dict[str, bool | str]:
    return {
        "candidateOnly": True,
        "writesFormalKnowledge": False,
        "writesRag": False,
        "writesOfficialGraph": False,
        "requiresStewardApproval": True,
        "boundary": "model_evidence_only_not_formal_knowledge",
    }


def _normalize_official_model_task_type(value: Any) -> str:
    normalized = _trim_text(value, max_length=80)
    if not normalized:
        return ""
    if normalized in LOCAL_RESEARCH_TASKS:
        return normalized
    aliases = {
        "paper_note": "paper_note_draft",
        "neuro_mechanism": "neuro_mechanism_extract",
        "algorithm_hypothesis": "algorithm_hypothesis_draft",
        "review_record": "review_prefilter",
        "steward_pack": "steward_pack_draft",
    }
    return aliases.get(normalized, normalized)


def _official_model_task_type_from_node(value: Any) -> str:
    normalized = _trim_text(value, max_length=120)
    for task_type, spec in LOCAL_RESEARCH_TASKS.items():
        if str(spec.get("workflowNode") or "") == normalized:
            return task_type
    return _normalize_official_model_task_type(normalized)


def _normalize_official_model_evidence_kind(value: Any) -> str:
    normalized = _trim_text(value, max_length=80)
    return normalized if normalized in OFFICIAL_MODEL_EVIDENCE_KINDS else "invocation_log"


def _infer_official_model_provider(value: Any, model_id: str) -> str:
    explicit = _trim_text(value, max_length=120)
    if explicit:
        return explicit
    key = model_id.lower()
    if model_id == LOCAL_RESEARCH_MODEL_ID or "qwen" in key:
        return "local_qwen"
    if "bailian" in key or "百炼" in model_id:
        return "bailian"
    if "dashscope" in key:
        return "dashscope"
    return "model_runtime"


def _find_candidate_by_id(candidate_store: dict[str, Any], candidate_id: str) -> dict[str, Any] | None:
    for candidate in [item for item in list(candidate_store.get("candidates") or []) if isinstance(item, dict)]:
        if str(candidate.get("candidateId") or "") == candidate_id:
            return candidate
    return None


def _count_by_field(items: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        key = _trim_text(item.get(field), max_length=120) or "unknown"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


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


def _workflow_log_sample_values(
    items: list[dict[str, Any]],
    key: str,
    *,
    limit: int = WORKFLOW_LOG_SAMPLE_LIMIT,
    max_length: int = 160,
) -> list[str]:
    values: list[str] = []
    for item in items:
        if len(values) >= limit:
            break
        if not isinstance(item, dict):
            continue
        text = _trim_text(item.get(key), max_length=max_length)
        if text and text not in values:
            values.append(text)
    return values


def _workflow_log_count_sample(
    counts: dict[str, int],
    *,
    limit: int = WORKFLOW_LOG_SAMPLE_LIMIT,
    max_key_length: int = 80,
) -> dict[str, int]:
    sampled: list[tuple[str, int]] = []
    if not isinstance(counts, dict):
        return {}
    for key, value in counts.items():
        label = _trim_text(key, max_length=max_key_length)
        if not label:
            continue
        try:
            count = int(value or 0)
        except (TypeError, ValueError):
            continue
        if count > 0:
            sampled.append((label, count))
    return {
        label: count
        for label, count in sorted(sampled, key=lambda item: (-item[1], item[0]))[:limit]
    }


def _workflow_log_queue_candidate_ids(
    queues: dict[str, list[dict[str, Any]]],
    queue_name: str,
    *,
    limit: int = WORKFLOW_LOG_SAMPLE_LIMIT,
) -> list[str]:
    queue_items = queues.get(queue_name)
    if not isinstance(queue_items, list):
        return []
    return _workflow_log_sample_values(queue_items, "candidateId", limit=limit)


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


def _record_workflow_event(
    event_code: str,
    team_id: str,
    *,
    fields: dict[str, Any],
    level: str = "info",
    outcome: str = "observed",
    child_log_path: str = "",
    child_log_payload: dict[str, Any] | None = None,
    lifecycle: bool = False,
) -> None:
    try:
        record_runtime_scene_event(
            "team_workflow_orchestration",
            "workflow",
            event_code,
            message=event_code,
            level=level,
            outcome=outcome,
            fields={"teamId": team_id, **fields},
            child_log_path=child_log_path,
            child_log_payload=child_log_payload,
            lifecycle=lifecycle,
        )
    except Exception:
        return


def _record_source_collection_stage_task_tool_policy_event(
    team_id: str,
    run_id: str,
    *,
    stage_id: str,
    agent_id: str,
    agent_role: str,
    session_id: str,
    task_id: str,
) -> None:
    required_tools = list(SOURCE_COLLECTION_STAGE_REQUIRED_TOOLS)
    if agent_role in SOURCE_COLLECTION_SEARCH_EXECUTION_AGENT_ROLES:
        required_tools.extend(SOURCE_COLLECTION_SEARCH_REQUIRED_TOOLS)
    try:
        policy = agent_directory_service.resolve_tool_policy_for_agent(agent_id, session_id=session_id)
    except Exception as exc:
        _record_workflow_event(
            "source_collection.stage_session_task_tool_policy_unavailable",
            team_id,
            level="warning",
            outcome="failed",
            lifecycle=True,
            fields={
                "runId": run_id,
                "stageId": stage_id,
                "agentId": agent_id,
                "agentRole": agent_role,
                "sessionId": session_id,
                "taskId": task_id,
                "errorType": type(exc).__name__,
            },
        )
        return
    allowed_tools = [str(item or "").strip() for item in list(policy.get("allowedTools") or []) if str(item or "").strip()]
    visible_tools = [tool for tool in required_tools if tool in set(allowed_tools)]
    missing_tools = [tool for tool in required_tools if tool not in set(allowed_tools)]
    event_code = (
        "source_collection.stage_session_task_tool_contract_missing"
        if missing_tools
        else "source_collection.stage_session_task_tool_contract_ready"
    )
    _record_workflow_event(
        event_code,
        team_id,
        level="warning" if missing_tools else "info",
        outcome="blocked" if missing_tools else "completed",
        lifecycle=bool(missing_tools),
        fields={
            "runId": run_id,
            "stageId": stage_id,
            "agentId": agent_id,
            "agentRole": agent_role,
            "sessionId": session_id,
            "taskId": task_id,
            "requiredTools": required_tools,
            "visibleRequiredTools": visible_tools,
            "missingTools": missing_tools,
            "allowedToolCount": len(allowed_tools),
            "toolPolicyId": str(policy.get("policyId") or "").strip(),
        },
    )


def _source_collection_query_event_summaries(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for event in events[:80]:
        if not isinstance(event, dict):
            continue
        assignment = event.get("assignment") if isinstance(event.get("assignment"), dict) else {}
        query = event.get("query") if isinstance(event.get("query"), dict) else {}
        summaries.append(
            {
                "eventType": _trim_text(event.get("eventType") or event.get("type"), max_length=120),
                "status": _trim_text(event.get("status"), max_length=80),
                "assignmentId": _trim_text(event.get("assignmentId") or assignment.get("assignmentId"), max_length=128),
                "agentRole": _trim_text(event.get("agentRole") or assignment.get("agentRole"), max_length=80),
                "queryId": _trim_text(event.get("queryId") or query.get("queryId"), max_length=160),
                "provider": _trim_text(query.get("provider") or event.get("provider"), max_length=80),
                "refCount": len(list(event.get("refs") or [])) if isinstance(event.get("refs"), list) else 0,
                "storageRefCount": len(list(event.get("storageRefs") or [])) if isinstance(event.get("storageRefs"), list) else 0,
            }
        )
    return summaries


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _workflow_path(team_id: str) -> Path:
    return _team_workflow_root(team_id) / "workflow_orchestration.json"


def _candidate_store_path(team_id: str) -> Path:
    return _team_workflow_root(team_id) / "candidate_store" / "index.json"


def _transfer_records_path(team_id: str) -> Path:
    return _team_workflow_root(team_id) / "transfer_records.jsonl"


def _stage_round_store_path(team_id: str) -> Path:
    return _team_workflow_root(team_id) / "research_stage_rounds" / "index.json"


def _experiment_plan_store_path(team_id: str) -> Path:
    return _team_workflow_root(team_id) / "experiment_plans" / "index.json"


def _official_model_evidence_store_path(team_id: str) -> Path:
    return _team_workflow_root(team_id) / "official_model_evidence" / "index.json"


def _team_workflow_root(team_id: str) -> Path:
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
