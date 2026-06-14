"""Team workflow orchestration and candidate-store service."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config.public_config import build_effective_config, load_public_config
from core.llm import LLMClient, LLMInvocationContext, invoke_llm
from core.runtime_manager import work_run_store
from core.web.services import chat_room_service, data_processing_service, team_knowledge_service, team_service
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
SOURCE_COLLECTION_DEFAULT_SEARCH_LANGUAGES = ("en", "zh")
SOURCE_COLLECTION_DEFAULT_SOURCE_TYPES = ("paper", "review", "dataset", "preprint")
SOURCE_COLLECTION_DEFAULT_MAX_RESULTS_PER_QUERY = 10
SOURCE_COLLECTION_MAX_QUERIES = 48
SOURCE_COLLECTION_SEARCH_PROVIDER_CROSSREF = "crossref_rest_api"
SOURCE_COLLECTION_SEARCH_EXECUTION_DEFAULT_MAX_QUERIES = 4
SOURCE_COLLECTION_SEARCH_EXECUTION_MAX_QUERIES = 12
SOURCE_COLLECTION_SEARCH_EXECUTION_DEFAULT_RESULTS_PER_QUERY = 2
SOURCE_COLLECTION_SEARCH_EXECUTION_MAX_RESULTS_PER_QUERY = 5
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


def import_data_record_as_source_candidate(team_id: str, run_id: str, record_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    normalized_run_id = _trim_text(run_id, max_length=128)
    normalized_record_id = _trim_text(record_id, max_length=128)
    if not normalized_run_id or not normalized_record_id:
        raise TeamWorkflowOrchestrationError("Data processing runId and recordId are required.")
    team_service.get_team(normalized_team_id)
    import_payload = payload if isinstance(payload, dict) else {}
    run, record = _load_data_processing_record(normalized_run_id, normalized_record_id)
    with _WORKFLOW_LOCK:
        workflow = _load_or_create_workflow(normalized_team_id)
        candidate_store = _load_candidate_store(normalized_team_id)
        existing = _find_candidate_imported_from_data_record(candidate_store, normalized_run_id, normalized_record_id)
        if existing is not None:
            return {
                "created": False,
                "candidate": existing,
                "dataRecordRef": _data_record_ref(run, record),
                "validation": existing.get("validation") if isinstance(existing.get("validation"), dict) else validate_candidate_record(existing),
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
        summary="正在执行资料搜集，搜索来源元数据并写入候选资料库。",
        active=True,
    )
    try:
        result = _execute_source_collection_search_impl(normalized_team_id, normalized_run_id, payload)
    except Exception as exc:
        _persist_source_collection_work_run(
            normalized_team_id,
            normalized_run_id,
            status="failed",
            current_phase="failed",
            run=run,
            team=team,
            assignments=assignments,
            records=records,
            summary="资料搜集执行失败。",
            active=False,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        raise

    final_run = result.get("run") if isinstance(result.get("run"), dict) else run
    final_assignments = [item for item in list(result.get("assignments") or []) if isinstance(item, dict)]
    try:
        final_records = data_processing_service.list_records(normalized_run_id).get("records") if normalized_run_id else []
    except data_processing_service.DataProcessingError:
        final_records = []
    _persist_source_collection_work_run(
        normalized_team_id,
        normalized_run_id,
        status=_source_collection_work_run_terminal_status(result),
        current_phase=_source_collection_work_run_terminal_phase(result),
        run=final_run,
        team=team,
        assignments=final_assignments,
        records=[item for item in list(final_records or []) if isinstance(item, dict)],
        summary=_source_collection_work_run_terminal_summary(result),
        active=False,
        extra={
            "executedQueryCount": _source_collection_count(result.get("executedQueryCount")),
            "failedQueryCount": _source_collection_count(result.get("failedQueryCount")),
            "recordCount": _source_collection_count(result.get("recordCount")),
            "importedCount": _source_collection_count(result.get("importedCount")),
            "resultCount": _source_collection_count(result.get("resultCount")),
        },
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
    active_snapshot = _persist_source_collection_work_run(
        normalized_team_id,
        normalized_run_id,
        status="running",
        current_phase="queued",
        run=run,
        team=team,
        assignments=assignments,
        records=records,
        summary="资料搜集已进入后台执行，页面可继续操作。",
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
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "runId": normalized_run_id,
        "status": "accepted",
        "executionMode": "background",
        "accepted": True,
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
            "The background source collection worker will write DataRecords and source_manifest candidates.",
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
    existing_query_ids = _source_collection_existing_query_ids(list(records_payload.get("records") or []))
    execution_events: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    created_records: list[dict[str, Any]] = []
    imported: list[dict[str, Any]] = []
    storage_artifacts = _source_collection_storage_artifacts(normalized_team_id, normalized_run_id)
    executed_query_count = 0
    skipped_query_count = 0
    failed_query_count = 0
    result_count = 0

    for assignment in assignments:
        if executed_query_count >= max_queries:
            break
        assignment_id = _trim_text(assignment.get("assignmentId"), max_length=128)
        agent_role = _trim_text(assignment.get("agentRole"), max_length=80)
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
        assignment_records: list[dict[str, Any]] = []
        attempted_query_ids: list[str] = []
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
                assignment_records.append(
                    _source_collection_record_from_search_result(
                        normalized_team_id,
                        run,
                        assignment,
                        query,
                        result,
                        provider=provider,
                        search_url=_trim_text(search_response.get("searchUrl"), max_length=1000),
                    )
                )
        if assignment_records:
            assignment_query_ids = {
                _trim_text(item.get("queryId"), max_length=160)
                for item in assigned_queries
                if _trim_text(item.get("queryId"), max_length=160)
            }
            remaining_query_ids = assignment_query_ids - existing_query_ids
            output_status = "completed" if not remaining_query_ids else "returned"
            try:
                output_response = data_processing_service.record_collection_output(
                    normalized_run_id,
                    assignment_id,
                    {
                        "status": output_status,
                        "records": assignment_records,
                        "notes": "Automated source collection search executed metadata-only queries and wrote DataRecords for review.",
                        "qualitySignals": {
                            "searchProvider": provider,
                            "executedQueryCount": len(attempted_query_ids),
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
                original_record = assignment_records[index] if index < len(assignment_records) else {}
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
        elif attempted_query_ids:
            try:
                output_response = data_processing_service.record_collection_output(
                    normalized_run_id,
                    assignment_id,
                    {
                        "status": "returned",
                        "records": [],
                        "notes": "Automated metadata search returned no importable records for this assignment.",
                        "blockingIssues": ["no_importable_search_result"],
                        "qualitySignals": {"searchProvider": provider, "metadataOnlyDownload": True},
                    },
                )
            except data_processing_service.DataProcessingError as exc:
                raise TeamWorkflowOrchestrationError(str(exc)) from exc
            outputs.append(output_response["output"])

    final_run = data_processing_service.get_processing_run(normalized_run_id)
    final_assignments = data_processing_service.list_collection_assignments(normalized_run_id)["assignments"]
    final_status = data_processing_service.get_processing_status(normalized_run_id)
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
            "importedCount": len(imported),
            "sourceCollectionRunDirectory": storage_artifacts["runDirectory"],
        },
    )
    status_label = "executed" if created_records else ("partial" if executed_query_count or failed_query_count else "no_open_assignment")
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
        "outputCount": len(outputs),
        "importedCount": len(imported),
        "run": final_run,
        "runStatus": final_status,
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


def get_research_stage_round_status(team_id: str) -> dict[str, Any]:
    normalized_team_id = _normalize_required_id(team_id, "Team id is required.")
    team = team_service.get_team(normalized_team_id)
    with _WORKFLOW_LOCK:
        workflow = _load_or_create_workflow(normalized_team_id)
        store = _load_stage_round_store(normalized_team_id)
    rounds = _stage_rounds(store)
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
        coordination_contract = _stage_coordination_contract(team, round_payload)
        coordination_result = _try_start_stage_coordination_round(team, coordination_contract)
        coordination_contract["startResult"] = coordination_result
        round_payload["coordinationContract"] = coordination_contract
        if not coordination_result.get("started"):
            warnings.append(
                {
                    "code": "coordination_round_not_started",
                    "severity": "warning",
                    "message": _trim_text(coordination_result.get("reason"), max_length=240) or "Coordination round was not started.",
                }
            )
            status = "needs_attention"
        else:
            round_payload["coordinationRoundId"] = str(coordination_result.get("roundId") or "")
            round_payload["coordinationRoomId"] = str(coordination_result.get("roomId") or "")
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
    return {
        "created": True,
        "stageRound": round_payload,
        "phase": _stage_phase_status(normalized_team_id, stage_type, store["rounds"], workflow=workflow, team=team),
        "workflow": _workflow_to_api(normalized_team_id, workflow, candidate_store),
        "status": get_research_stage_round_status(normalized_team_id),
        "nextActions": _stage_next_actions(stage_type, reused=False),
        "boundaries": _research_stage_boundaries(),
        **result_payload,
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
        coordination_contract = _stage_coordination_contract(team, stage_round)
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
        except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
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
    team_service.get_team(normalized_team_id)
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
        return "Knowledge Steward Agent"
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
                "nextAction": "先启动资料搜集或手工回写 DataRecord 并导入 source_manifest。",
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
    metadata.update(
        {
            "importedFromDataRecord": _data_record_ref(run, record),
            "dataProcessingQualitySignals": _normalize_metadata(quality_signals),
            "dataProcessingCollectionTrace": _normalize_metadata(collection_trace),
            "dataProcessingRecordMetadata": _normalize_metadata(record_metadata),
        }
    )
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
    return f"research-team-{normalized_role}-{digest}"


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
    return {
        "sourceType": _source_collection_data_processing_source_type(result.get("sourceType")),
        "sourceRef": source_ref,
        "rawLocation": raw_location,
        "title": _trim_text(result.get("title"), max_length=260) or source_ref or raw_location,
        "summary": _trim_text(result.get("summary"), max_length=4000),
        "status": "collected",
        "metadata": metadata,
        "qualitySignals": _normalize_metadata(result.get("qualitySignals")),
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
    data_processing_directory = _project_root() / "workspace" / "data_processing" / "runs" / normalized_run_id
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


def _source_collection_storage_artifacts(team_id: str, run_id: str) -> dict[str, str]:
    return {
        key: _relative_path(path)
        for key, path in _source_collection_storage_artifact_paths(team_id, run_id).items()
    }


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
    open_assignments = [
        item for item in assignments
        if str(item.get("status") or "").strip().lower() in {"open", "in_progress", "returned"}
    ]
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
        "openAssignmentCount": len(open_assignments),
        "recordCount": len(records),
        "queryCount": query_count,
        "storagePath": _source_collection_storage_artifacts(team_id, run_id)["runDirectory"],
        "updatedAt": now,
        "sourceCollection": {
            "teamId": team_id,
            "stageType": "knowledge_collection",
            "openAssignmentCount": len(open_assignments),
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
    if _source_collection_count(result.get("failedQueryCount")) and not _source_collection_count(result.get("executedQueryCount")):
        return "failed"
    run_status = result.get("runStatus") if isinstance(result.get("runStatus"), dict) else {}
    summary = run_status.get("summary") if isinstance(run_status.get("summary"), dict) else {}
    if _source_collection_count(summary.get("openAssignmentCount")):
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
        return "资料搜集执行失败，等待检查搜索错误。"
    record_count = _source_collection_count(result.get("recordCount"))
    imported_count = _source_collection_count(result.get("importedCount"))
    if _source_collection_work_run_terminal_status(result) == "needs_continue":
        return f"本轮已写入 {record_count} 条资料、导入 {imported_count} 个候选，仍有任务可继续。"
    return f"本轮资料搜集完成，写入 {record_count} 条资料、导入 {imported_count} 个候选。"


def _source_collection_count(value: Any) -> int:
    return _normalize_int(value, default=0, minimum=0, maximum=100_000)


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


def _ensure_project_child(path: Path) -> Path:
    resolved = path.resolve()
    project_root = _project_root().resolve()
    try:
        resolved.relative_to(project_root)
    except ValueError as exc:
        raise TeamWorkflowOrchestrationError("Source collection storage path must stay inside the Vibelution project.") from exc
    return resolved


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


def _stage_coordination_contract(team: dict[str, Any], stage_round: dict[str, Any]) -> dict[str, Any]:
    linked_room_id = _trim_text(team.get("linkedChatRoomId"), max_length=160)
    stage_type = str(stage_round.get("stageType") or "")
    topic = str(stage_round.get("topic") or "")
    linked_room = chat_room_service.get_chat_room_compact(linked_room_id) if linked_room_id else None
    room_mode = _trim_text((linked_room or {}).get("mode"), max_length=80) or "round_robin"
    return {
        "contractKind": "team_coordination_round_contract",
        "linkedChatRoomId": linked_room_id,
        "stageRoundId": stage_round.get("stageRoundId", ""),
        "stageType": stage_type,
        "topic": f"{_stage_label(stage_type)}：{topic}",
        "purpose": _stage_coordination_purpose(stage_type),
        "mode": room_mode,
        "autoStarted": True,
        "expectedAction": "Start a lightweight background team coordination round for this stage.",
        "config": {
            "source": "research_stage_launcher",
            "teamId": team.get("teamId", ""),
            "stageRoundId": stage_round.get("stageRoundId", ""),
            "sourceRunIds": list(stage_round.get("sourceRunIds") or []),
        },
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
        return "围绕资料搜集范围、query seeds、角色分工和结果回写合同进行团队协调。"
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


def _stage_round_store_path(team_id: str) -> Path:
    return _team_workflow_root(team_id) / "research_stage_rounds" / "index.json"


def _official_model_evidence_store_path(team_id: str) -> Path:
    return _team_workflow_root(team_id) / "official_model_evidence" / "index.json"


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
