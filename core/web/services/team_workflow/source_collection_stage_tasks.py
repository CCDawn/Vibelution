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


SCHEMA_VERSION = 1
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


def source_collection_stage_can_materialize_formal_knowledge(stage_id: str, agent_role: str) -> bool:
    return (
        normalize_source_collection_stage_id(stage_id, default="") == "ingestion"
        and normalize_source_collection_agent_role(agent_role) == "source_ingestor"
    )


def source_collection_stage_task_writeback_contract(
    team_id: str,
    run_id: str,
    task_id: str,
    *,
    stage_id: str,
    agent_id: str,
    agent_role: str,
) -> dict[str, Any]:
    endpoint = f"/api/teams/{urllib.parse.quote(team_id, safe='')}/workflow-orchestration/stage-session-tasks/{urllib.parse.quote(task_id, safe='')}/writeback"
    can_materialize_formal_knowledge = source_collection_stage_can_materialize_formal_knowledge(stage_id, agent_role)
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


def source_collection_stage_task_title(stage_id: str) -> str:
    return {
        "finding": "资料寻找任务",
        "extraction": "资料提炼任务",
        "relations": "资料关系整理任务",
        "ingestion": "资料入库任务",
    }.get(stage_id, "知识搜集阶段任务")


def source_collection_stage_task_checklist(stage_id: str, agent_role: str = "") -> list[dict[str, Any]]:
    normalized_stage_id = normalize_source_collection_stage_id(stage_id, default="finding")
    normalized_agent_role = normalize_source_collection_agent_role(agent_role)
    raw_items_by_stage: dict[str, tuple[tuple[str, str, str], ...]] = {
        "finding": (
            ("read_context", "读取本轮 compact 上下文", "source_collection_context_tool"),
            ("page_existing_sources", "分页检查已有资料和候选", "source_collection_context_tool"),
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
    raw_items = raw_items_by_stage.get(normalized_stage_id, raw_items_by_stage["finding"])
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
