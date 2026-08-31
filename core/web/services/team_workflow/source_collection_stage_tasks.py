"""Pure source-collection stage task helpers."""

from __future__ import annotations

import urllib.parse
from typing import Any, Iterable

from .source_collection_common import (
    normalize_source_collection_agent_role,
    normalize_source_collection_stage_id,
    source_collection_count,
    trim_text,
)


SOURCE_COLLECTION_STAGE_SESSION_TASK_STATUSES = {
    "queued",
    "running",
    "completed",
    "needs_review",
    "blocked",
    "failed",
    "cancelled",
    "interrupted",
}
SOURCE_COLLECTION_STAGE_SESSION_TASK_ACTIVE_STATUSES = {"queued", "running"}

# 闭集枚举上限：契约里允许列出的端点 candidateId 数量，超出时截断并在
# 契约里显式标注 truncated，让 Agent 用分页上下文补全。
MAX_RELATION_ENDPOINT_ENUM_IDS = 500


def source_collection_relations_allowed_endpoint_ids(
    source_candidates: Iterable[Any] | None,
) -> list[str]:
    """Extract the deduplicated candidateId closed set for relations tasks."""
    seen: set[str] = set()
    ordered: list[str] = []
    for item in list(source_candidates or []):
        if not isinstance(item, dict):
            continue
        candidate_id = trim_text(item.get("candidateId"), max_length=160)
        if not candidate_id or candidate_id in seen:
            continue
        seen.add(candidate_id)
        ordered.append(candidate_id)
    return ordered


def _source_collection_relations_result_contract(
    allowed_endpoint_ids: Iterable[str],
) -> dict[str, Any]:
    endpoint_ids: list[str] = []
    seen: set[str] = set()
    for value in allowed_endpoint_ids:
        candidate_id = trim_text(value, max_length=160)
        if not candidate_id or candidate_id in seen:
            continue
        seen.add(candidate_id)
        endpoint_ids.append(candidate_id)
    truncated = len(endpoint_ids) > MAX_RELATION_ENDPOINT_ENUM_IDS
    if truncated:
        endpoint_ids = endpoint_ids[:MAX_RELATION_ENDPOINT_ENUM_IDS]
    return {
        "acceptedCollections": [
            "candidateGraph",
            "candidateRelations",
            "themeNodes",
            "sourceThemeEdges",
            "topicRelations",
            "missingLinks",
        ],
        "edgeIdentityFields": ["sourceCandidateId", "targetCandidateId", "relation"],
        "endpointPolicy": {
            # LlamaIndex SchemaLLMPathExtractor 式闭集：优先只输出注册表中的
            # 完整 candidateId； Neo4j graphrag Entity Resolution 式兜底：
            # 语义端点由服务端确定性解析到注册表节点。
            "mode": "closed_set_ids_plus_declared_themes_with_semantic_fallback",
            "allowedEndpointIds": endpoint_ids,
            "allowedEndpointIdCount": len(endpoint_ids),
            "allowedEndpointIdsTruncated": truncated,
            "semanticEndpoints": {
                "allowedInputs": [
                    "候选标题（服务端规范化后匹配注册表）",
                    "已声明主题的主题 ID、主题 ID 裸值或主题 label",
                ],
                "resolution": "deterministic_exact_or_normalized_match_only",
                "unresolvedOutcome": (
                    "edgeDroppedToMissingLinksAndCountedAsDanglingEdge"
                ),
            },
            "hubDeclarationRule": (
                "主题/主张类枢纽必须先在同一轮回写的 themeNodes[] 中声明"
                "（带 themeId 和 label），再在边上引用；未声明的逻辑枢纽端点"
                "（如 rh_claim）会被丢弃并阻塞下游 knowledge_ingestion。"
            ),
        },
    }


def source_collection_stage_can_materialize_formal_knowledge(stage_id: str, agent_role: str) -> bool:
    return (
        normalize_source_collection_stage_id(stage_id, default="") == "ingestion"
        and normalize_source_collection_agent_role(agent_role) == "source_ingestor"
    )


def _source_collection_extraction_result_contract() -> dict[str, Any]:
    return {
        "acceptedCollections": [
            "candidateExtractions",
            "recordExtractions",
            "evidenceFetchAttempts",
        ],
        "requiredItemFields": ["decision"],
        "candidateIdentityField": "candidateId",
        "recordIdentityField": "recordId",
        "sourceLocatorFields": ["sourceRefs"],
        "evidenceAnchorFields": ["evidenceRefs", "claims", "keyFindings", "citations"],
        "locatorOnlyTypes": ["doi", "url", "uri", "paper"],
        "locatorOnlySatisfiesEvidenceAnchor": False,
        "claimAnchorRule": {
            "required": ["sourceRef"],
            "oneOf": ["page", "pageRange", "citation", "evidenceRef"],
        },
        "acceptedEvidenceRefTypes": [
            "page",
            "pdf_page",
            "page_anchor",
            "record_anchor",
            "section",
            "paragraph",
            "html_paragraph",
            "quote",
            "citation",
            "excerpt",
            "abstract",
            "sentence",
            "line",
            "table",
            "figure",
            "timestamp",
        ],
        "missingAnchorBehavior": "preserve_decision_and_mark_missing_evidence_anchor",
        "evidenceFetchAttemptFields": [
            "candidateId",
            "locator",
            "status",
            "toolName",
        ],
        "challengeV2Evidence": {
            "mode": "challenge_v2_fail_closed",
            "requiredFields": [
                "title",
                "source_type",
                "source_url",
                "retrieved_at",
                "fact",
                "relation",
                "verification_status",
            ],
            "optionalFields": ["doi", "date", "limitations"],
            "acceptedSourceTypes": [
                "peer_reviewed_paper",
                "preprint",
                "dataset",
                "standard",
                "official_document",
                "book",
                "other",
            ],
            "acceptedRelations": [
                "supports",
                "challenges",
                "context",
                "method",
                "boundary",
            ],
            "acceptedVerificationStatuses": [
                "unverified",
                "metadata_checked",
                "full_text_checked",
                "human_verified",
            ],
            "linkage": {
                "requiredOneOf": ["candidateId", "recordId"],
                "sourceIdMustEqual": "candidateId_or_recordId",
                "urlCannotBeIdentity": True,
            },
            "noInferenceFrom": [
                "sourceKind",
                "source_url",
                "doi",
                "summary",
                "valueSummary",
            ],
            "legacyCompatibility": {
                "available": True,
                "mode": "legacy",
                "mustBeExplicit": True,
            },
        },
    }


def source_collection_stage_task_writeback_contract(
    team_id: str,
    run_id: str,
    task_id: str,
    *,
    stage_id: str,
    agent_id: str,
    agent_role: str,
    schema_version: int,
    allowed_relation_endpoint_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    endpoint = f"/api/teams/{urllib.parse.quote(team_id, safe='')}/workflow-orchestration/stage-session-tasks/{urllib.parse.quote(task_id, safe='')}/writeback"
    can_materialize_formal_knowledge = source_collection_stage_can_materialize_formal_knowledge(stage_id, agent_role)
    contract = {
        "schemaVersion": schema_version,
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
    if normalize_source_collection_stage_id(stage_id, default="") == "extraction":
        contract["resultContract"] = _source_collection_extraction_result_contract()
    if normalize_source_collection_stage_id(stage_id, default="") == "relations":
        contract["resultContract"] = _source_collection_relations_result_contract(
            allowed_relation_endpoint_ids or []
        )
    if normalize_source_collection_stage_id(stage_id, default="") == "finding":
        from .source_collection.writeback_materialize import (
            finding_resolved_search_envelope,
        )

        contract["searchEnvelope"] = finding_resolved_search_envelope()
    return contract


def source_collection_stage_task_title(stage_id: str) -> str:
    return {
        "finding": "资料寻找任务",
        "extraction": "资料提炼任务",
        "relations": "资料关系整理任务",
        "ingestion": "资料入库任务",
    }.get(stage_id, "知识搜集阶段任务")


def source_collection_stage_task_checklist(
    stage_id: str,
    agent_role: str = "",
    *,
    evidence_remediation_contract: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    normalized_stage_id = normalize_source_collection_stage_id(stage_id, default="finding")
    normalized_agent_role = normalize_source_collection_agent_role(agent_role)
    raw_items_by_stage: dict[str, tuple[tuple[str, str, str], ...]] = {
        "finding": (
            ("read_context", "读取本轮 compact 上下文", "source_collection_context_tool"),
            ("page_existing_sources", "一次读取当前上下文（单次调用即满足，无需翻页）", "source_collection_context_tool"),
            ("search_and_dedupe_sources", "搜索并去重新资料", "batch_web_search_tool"),
            ("write_candidate_leads", "用 candidateLeads[] 回写新资料", "source_collection_stage_writeback_tool"),
            ("write_invalid_sources", "写入 invalidSources[] 或说明无无效来源", "source_collection_stage_writeback_tool"),
            ("confirm_materialized_sources", "确认新增资料或候选已物化", "source_collection_stage_writeback_tool"),
        ),
        "extraction": (
            ("read_candidates", "读取候选或原始资料上下文", "source_collection_context_tool"),
            ("page_candidate_inputs", "分页覆盖本阶段输入", "source_collection_context_tool"),
            ("extract_and_review_each_source", "逐候选提炼并审查保留/待补/无效", ""),
            ("write_extractions", "回写 candidateExtractions[] 或 recordExtractions[]", "source_collection_stage_writeback_tool"),
            ("confirm_coverage", "确认 coverageSummary 覆盖率和待补原因", "source_collection_stage_writeback_tool"),
        ),
        "relations": (
            ("read_approved_candidates", "读取已通过或已保留候选", "source_collection_context_tool"),
            ("build_candidate_relations", "生成候选级主题、来源和证据关系", ""),
            ("write_candidate_graph", "回写 candidateGraph 候选关系图", "source_collection_stage_writeback_tool"),
            ("confirm_graph_materialized", "确认关系节点和边已物化", "source_collection_stage_writeback_tool"),
        ),
        "ingestion": (
            ("read_ingestion_inputs", "读取已通过候选和关系整理结果", "source_collection_context_tool"),
            ("decide_ingestion_scope", "生成入库通过、退回或阻塞决策", ""),
            ("write_ingestion_decision", "调用入库 writeback 写回审核结果", "source_collection_stage_writeback_tool"),
            ("confirm_formal_knowledge_or_return", "确认正式知识项已生成或明确退回原因", "source_collection_stage_writeback_tool"),
        ),
    }
    raw_items = list(
        raw_items_by_stage.get(normalized_stage_id, raw_items_by_stage["finding"])
    )
    remediation = (
        evidence_remediation_contract
        if isinstance(evidence_remediation_contract, dict)
        else {}
    )
    if (
        normalized_stage_id == "extraction"
        and bool(remediation.get("requiredExistingLocatorFetch"))
    ):
        raw_items.insert(
            2,
            (
                "fetch_existing_locators",
                "逐候选抓取既有 DOI/URL 并记录 evidenceFetchAttempts[]",
                "web_fetch_tool",
            ),
        )
    return [
        {
            "id": item_id,
            "order": index,
            "description": description,
            "requiredTool": required_tool,
            "stageId": normalized_stage_id,
            "agentRole": normalized_agent_role,
        }
        for index, (item_id, description, required_tool) in enumerate(raw_items, start=1)
    ]


def source_collection_evidence_fetch_progress(
    task: dict[str, Any],
    result: dict[str, Any] | None,
) -> dict[str, Any]:
    contract = (
        task.get("evidenceRemediationContract")
        if isinstance(task.get("evidenceRemediationContract"), dict)
        else {}
    )
    required_ids = {
        trim_text(item, max_length=160)
        for item in list(contract.get("scopeCandidateIds") or [])
        if trim_text(item, max_length=160)
    }
    required = bool(contract.get("requiredExistingLocatorFetch") and required_ids)
    attempts = [
        item
        for item in list((result or {}).get("evidenceFetchAttempts") or [])
        if isinstance(item, dict)
    ]
    completed_ids: set[str] = set()
    invalid_ids: list[str] = []
    for item in attempts:
        candidate_id = trim_text(item.get("candidateId"), max_length=160)
        locator = trim_text(item.get("locator"), max_length=1000)
        status = trim_text(item.get("status"), max_length=80).lower()
        tool_name = trim_text(item.get("toolName"), max_length=120)
        failure_code = trim_text(item.get("failureCode"), max_length=160)
        valid = bool(
            candidate_id in required_ids
            and locator
            and tool_name == "web_fetch_tool"
            and status in {"fetched", "failed"}
            and (status != "failed" or failure_code)
        )
        if valid:
            completed_ids.add(candidate_id)
        elif candidate_id:
            invalid_ids.append(candidate_id)
    missing_ids = sorted(required_ids - completed_ids)
    return {
        "required": required,
        "total": len(required_ids),
        "completed": len(completed_ids),
        "complete": not required or not missing_ids,
        "completedCandidateIds": sorted(completed_ids),
        "missingCandidateIds": missing_ids,
        "invalidCandidateIds": sorted(set(invalid_ids)),
    }


def source_collection_stage_task_tool_progress(
    task_checklist: list[dict[str, Any]] | None,
    *,
    completed_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    checklist = [item for item in list(task_checklist or []) if isinstance(item, dict)]
    expected_ids = [
        trim_text(item.get("id"), max_length=120)
        for item in checklist
        if trim_text(item.get("id"), max_length=120)
    ]
    completed = {
        trim_text(item, max_length=120)
        for item in list(completed_ids or [])
        if trim_text(item, max_length=120)
    }
    completed_ordered = [item_id for item_id in expected_ids if item_id in completed]
    pending = [item_id for item_id in expected_ids if item_id not in completed]
    return {
        "required": bool(checklist),
        "total": len(expected_ids),
        "completed": len(completed_ordered),
        "complete": bool(expected_ids) and len(completed_ordered) >= len(expected_ids),
        "completedIds": completed_ordered,
        "pendingIds": pending,
    }


def source_collection_stage_completion_gate(
    *,
    task_checklist: list[dict[str, Any]] | None,
    artifact_complete: bool,
    task_checklist_complete: bool,
) -> dict[str, Any]:
    requires_task_checklist = bool(task_checklist)
    passed = bool(artifact_complete) and (not requires_task_checklist or bool(task_checklist_complete))
    return {
        "requiresTaskChecklist": requires_task_checklist,
        "requiresArtifact": True,
        "taskChecklistComplete": bool(task_checklist_complete),
        "artifactComplete": bool(artifact_complete),
        "passed": passed,
    }


def source_collection_stage_round_status_from_task_refs(
    stage_round: dict[str, Any],
    task_refs: list[dict[str, Any]],
) -> str:
    statuses = {
        trim_text(item.get("status"), max_length=80).lower()
        for item in task_refs
        if isinstance(item, dict) and trim_text(item.get("status"), max_length=80)
    }
    if statuses & {"running", "queued"}:
        return "running"
    if statuses & {"failed", "blocked", "needs_review"}:
        return "needs_attention"
    existing_status = trim_text(stage_round.get("status"), max_length=80)
    if existing_status not in {"running", "planning", "initializing"}:
        return existing_status or "needs_continue"
    search_execution = stage_round.get("sourceCollectionSearchExecution") if isinstance(stage_round.get("sourceCollectionSearchExecution"), dict) else {}
    search_status = trim_text(search_execution.get("status") or search_execution.get("resultStatus"), max_length=80)
    if search_status and search_status not in {"running", "queued", "accepted"}:
        return search_status
    return "needs_continue" if statuses else existing_status
