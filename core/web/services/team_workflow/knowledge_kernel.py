"""Knowledge private kernel for team workflow.

Claim scope: knowledge ingestion helpers, steward notify/payloads, candidate graph
builders, coordination queues, paper-note/source-quality private helpers, and
related background runners used by ``knowledge.py``.

Public knowledge APIs remain in ``knowledge.py``. Late-bound facade keeps
monkeypatches stable.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import urllib.parse
from copy import deepcopy
from pathlib import Path
from typing import Any


def _service():
    from core.web.services import team_workflow_orchestration_service

    return team_workflow_orchestration_service


def _source_collection_stage_candidate_graph_materialization_child_summary(summary: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    return {
        "status": s._trim_text(summary.get("status"), max_length=80),
        "candidateGraphId": s._trim_text(summary.get("candidateGraphId"), max_length=160),
        "createdCandidateGraphCount": s._source_collection_count(summary.get("createdCandidateGraphCount")),
        "reusedCandidateGraph": bool(summary.get("reusedCandidateGraph")),
        "nodeCount": s._source_collection_count(summary.get("nodeCount")),
        "edgeCount": s._source_collection_count(summary.get("edgeCount")),
        "missingLinkCount": s._source_collection_count(summary.get("missingLinkCount")),
        "unreviewedNodeCount": s._source_collection_count(summary.get("unreviewedNodeCount")),
        "inputCandidateCount": s._source_collection_count(summary.get("inputCandidateCount")),
        "filteredCandidateCount": s._source_collection_count(summary.get("filteredCandidateCount")),
        "ingestionFingerprint": s._trim_text(summary.get("ingestionFingerprint"), max_length=160),
        "failedCandidateGraphCount": s._source_collection_count(summary.get("failedCandidateGraphCount")),
        "failedCandidateGraphs": s._bounded_log_items(summary.get("failedCandidateGraphs"), ("reason", "errorType", "error"), max_items=24),
    }


def _source_collection_stage_knowledge_ingestion_materialization_child_summary(summary: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    return {
        "status": s._trim_text(summary.get("status"), max_length=80),
        "stewardPackCandidateId": s._trim_text(summary.get("stewardPackCandidateId"), max_length=160),
        "knowledgeBaseId": s._trim_text(summary.get("knowledgeBaseId"), max_length=160),
        "approvedCandidateCount": s._source_collection_count(summary.get("approvedCandidateCount")),
        "approvedCandidateIds": s._bounded_text_items(summary.get("approvedCandidateIds"), max_items=40, max_length=160),
        "formalKnowledgeItemCount": s._source_collection_count(summary.get("formalKnowledgeItemCount")),
        "formalKnowledgeItemIds": s._bounded_text_items(summary.get("formalKnowledgeItemIds"), max_items=40, max_length=160),
        "writesFormalKnowledge": bool(summary.get("writesFormalKnowledge")),
        "confidence": summary.get("confidence") if isinstance(summary.get("confidence"), (int, float)) else 0.0,
        "sourceReviewStatus": s._trim_text(summary.get("sourceReviewStatus"), max_length=80),
        "knowledgeSubmissionStatus": s._trim_text(summary.get("knowledgeSubmissionStatus"), max_length=80),
        "knowledgeReviewStatus": s._trim_text(summary.get("knowledgeReviewStatus"), max_length=80),
        "createdKnowledgeBaseId": s._trim_text(summary.get("createdKnowledgeBaseId"), max_length=160),
        "skippedCount": s._source_collection_count(summary.get("skippedCount")),
        "failedCount": s._source_collection_count(summary.get("failedCount")),
        "skipped": s._bounded_log_items(summary.get("skipped"), ("reason", "decision", "confidence", "candidateIds"), max_items=24),
        "failed": s._bounded_log_items(summary.get("failed"), ("reason", "errorType", "error"), max_items=24),
    }


def _source_collection_stage_knowledge_ingestion_child_log_payload(
    *,
    team_id: str,
    run_id: str,
    task: dict[str, Any],
    summary: dict[str, Any],
    decision: dict[str, Any],
) -> dict[str, Any]:
    s = _service()
    materialized = s._source_collection_stage_knowledge_ingestion_materialization_child_summary(summary)
    steps = [
        {
            "stageId": "auto_ingest_gate",
            "status": "passed" if materialized["status"] == "completed" else materialized["status"],
            "decision": s._safe_token(decision.get("decision"), default="", max_length=80),
            "confidence": materialized["confidence"],
        },
        {
            "stageId": "candidate_scope",
            "status": "completed" if materialized["approvedCandidateCount"] else materialized["status"],
            "approvedCandidateCount": materialized["approvedCandidateCount"],
            "approvedCandidateIds": materialized["approvedCandidateIds"],
        },
        {
            "stageId": "knowledge_base",
            "status": "created" if materialized["createdKnowledgeBaseId"] else ("reused" if materialized["knowledgeBaseId"] else materialized["status"]),
            "knowledgeBaseId": materialized["knowledgeBaseId"],
            "createdKnowledgeBaseId": materialized["createdKnowledgeBaseId"],
        },
        {
            "stageId": "steward_pack",
            "status": "completed" if materialized["stewardPackCandidateId"] else materialized["status"],
            "stewardPackCandidateId": materialized["stewardPackCandidateId"],
        },
        {
            "stageId": "source_gate",
            "status": materialized["sourceReviewStatus"],
            "knowledgeBaseId": materialized["knowledgeBaseId"],
        },
        {
            "stageId": "knowledge_gate",
            "status": materialized["knowledgeSubmissionStatus"] or materialized["knowledgeReviewStatus"],
            "knowledgeBaseId": materialized["knowledgeBaseId"],
        },
        {
            "stageId": "official_sync",
            "status": "completed" if materialized["formalKnowledgeItemCount"] else materialized["status"],
            "formalKnowledgeItemCount": materialized["formalKnowledgeItemCount"],
            "formalKnowledgeItemIds": materialized["formalKnowledgeItemIds"],
        },
    ]
    return {
        "kind": "source_collection_stage_knowledge_ingestion_materialization",
        "teamId": s._trim_text(team_id, max_length=160),
        "runId": s._trim_text(run_id, max_length=160),
        "taskId": s._trim_text(task.get("taskId"), max_length=160),
        "stageId": s._trim_text(task.get("stageId"), max_length=80),
        "agentId": s._trim_text(task.get("agentId"), max_length=160),
        "status": materialized["status"],
        "stewardPackCandidateId": materialized["stewardPackCandidateId"],
        "knowledgeBaseId": materialized["knowledgeBaseId"],
        "approvedCandidateIds": materialized["approvedCandidateIds"],
        "formalKnowledgeItemIds": materialized["formalKnowledgeItemIds"],
        "skipped": materialized["skipped"],
        "failed": materialized["failed"],
        "steps": steps,
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
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_candidate_graph_id = s._trim_text(candidate_graph_id, max_length=160)
    if not normalized_candidate_graph_id:
        return
    normalized_stage_id = s._normalize_source_collection_stage_id(task.get("stageId"), default="relations")
    normalized_agent_role = s._normalize_source_collection_agent_role(task.get("agentRole")) or "source_relation_mapper"
    writeback_ref = {
        "taskId": s._trim_text(task.get("taskId"), max_length=160),
        "runId": s._trim_text(task.get("runId"), max_length=160),
        "stageId": normalized_stage_id,
        "agentId": s._trim_text(task.get("agentId"), max_length=160),
        "agentRole": normalized_agent_role,
        "status": s._trim_text(writeback.get("status"), max_length=80),
        "summary": s._trim_text(writeback.get("summary"), max_length=1000),
        "recordedAt": s._trim_text(writeback.get("recordedAt"), max_length=120),
        "recordedByAgent": s._trim_text(writeback.get("recordedByAgent"), max_length=160),
        "result": {"candidateGraph": s._normalize_metadata(agent_graph)} if agent_graph else {},
    }
    with s._WORKFLOW_LOCK:
        candidate_store = s._load_candidate_store(normalized_team_id)
        changed = False
        for candidate in list(candidate_store.get("candidates") or []):
            if not isinstance(candidate, dict) or str(candidate.get("candidateId") or "") != normalized_candidate_graph_id:
                continue
            metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
            metadata = dict(metadata)
            existing_refs = metadata.get("stageTaskWritebacks") if isinstance(metadata.get("stageTaskWritebacks"), list) else []
            refs = [
                item for item in existing_refs
                if isinstance(item, dict) and s._trim_text(item.get("taskId"), max_length=160) != writeback_ref["taskId"]
            ]
            refs.append(writeback_ref)
            response_graph = graph_response.get("graph") if isinstance(graph_response.get("graph"), dict) else {}
            graph = response_graph or (metadata.get("graph") if isinstance(metadata.get("graph"), dict) else {})
            if graph:
                graph = dict(graph)
                graph_summary = graph.get("summary") if isinstance(graph.get("summary"), dict) else {}
                graph_summary = dict(graph_summary)
                graph_summary["stageId"] = normalized_stage_id
                graph_summary["stageAgentRole"] = normalized_agent_role
                graph["summary"] = graph_summary
                metadata["graph"] = graph
            agent_process = metadata.get("agentProcess") if isinstance(metadata.get("agentProcess"), list) else []
            if agent_process:
                normalized_process: list[dict[str, Any]] = []
                for process in agent_process:
                    if not isinstance(process, dict):
                        continue
                    item = dict(process)
                    if s._normalize_source_collection_agent_role(item.get("agentRole")) == normalized_agent_role:
                        item["agentRole"] = normalized_agent_role
                    if s._normalize_source_collection_stage_id(item.get("stage"), default="") == normalized_stage_id:
                        item["stage"] = normalized_stage_id
                    normalized_process.append(item)
                metadata["agentProcess"] = normalized_process
            metadata["agentWriteback"] = writeback_ref
            metadata["stageTaskWritebacks"] = refs[-24:]
            metadata["sourceCollectionStageTaskId"] = writeback_ref["taskId"]
            metadata["sourceCollectionRunId"] = writeback_ref["runId"]
            metadata["workflowStage"] = normalized_stage_id
            metadata["stageAgentRole"] = normalized_agent_role
            metadata["reusedCandidateGraph"] = bool(graph_response.get("reusedCandidateGraph"))
            candidate["metadata"] = metadata
            candidate["updatedAt"] = s.utc_now_iso()
            changed = True
            break
        if changed:
            candidate_store["updatedAt"] = s.utc_now_iso()
            s._write_json(s._candidate_store_path(normalized_team_id), candidate_store)


def _research_review_checklist(candidate: dict[str, Any]) -> tuple[dict[str, bool], list[str]]:
    """对单个候选做科研审稿 checklist，返回 (checklist, blockingRiskFlags)。"""
    s = _service()
    candidate_type = str(candidate.get("candidateType") or "")
    cpayload = candidate.get("payload") if isinstance(candidate.get("payload"), dict) else {}
    cmeta = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    model_output = cmeta.get("output") if isinstance(cmeta.get("output"), dict) else {}

    def field(name: str) -> Any:
        return candidate.get(name) or cpayload.get(name) or model_output.get(name) or cmeta.get(name)

    evidence = candidate.get("evidenceRefs") or cpayload.get("evidenceRefs") or model_output.get("evidenceRefs")
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


def _team_aggregate_workflow_scope() -> dict[str, Any]:
    s = _service()
    return {
        "kind": "team_aggregate",
        "runId": "",
        "includesHistorical": True,
        "eligibleForPhaseCloseGate": False,
    }


def _notify_knowledge_steward_for_ingestion(
    team_id: str,
    *,
    steward_agent_id: str,
    requester_agent_id: str,
    steward_candidate_id: str,
    knowledge_base_id: str,
    target_domain: str,
    wake_target: bool,
    scoped_knowledge_base_id: str = "",
) -> dict[str, Any]:
    s = _service()
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
            "scopedKnowledgeBaseId": scoped_knowledge_base_id,
            "targetDomain": target_domain,
        },
    }
    if not steward_agent_id:
        activation["status"] = "skipped_missing_steward_agent"
        s._record_knowledge_steward_activation_event(team_id, steward_candidate_id, activation)
        return activation

    target_agent = s.agent_directory_service.get_agent(steward_agent_id, include_archived=True)
    if not target_agent:
        activation["status"] = "skipped_missing_steward_agent"
        s._record_knowledge_steward_activation_event(team_id, steward_candidate_id, activation)
        return activation
    if str(target_agent.get("status") or "active").strip().lower() == "archived":
        activation["status"] = "skipped_archived_steward_agent"
        s._record_knowledge_steward_activation_event(team_id, steward_candidate_id, activation)
        return activation

    source_agent_id = requester_agent_id if requester_agent_id and s.agent_directory_service.get_agent(requester_agent_id, include_archived=True) else ""
    content = "\n".join(
        [
            "[挑战杯团队知识入库请求]",
            f"团队: {team_id}",
            f"待入库知识包: {steward_candidate_id}",
            f"目标知识库: {knowledge_base_id}",
            f"目标知识库唯一定位: {scoped_knowledge_base_id or knowledge_base_id}",
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
        message, delivery, kernel_result = s._submit_team_workflow_inbox_via_kernel(
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
        s._record_knowledge_steward_activation_event(team_id, steward_candidate_id, activation)
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
    s._record_knowledge_steward_activation_event(team_id, steward_candidate_id, activation)
    return activation


def _record_knowledge_steward_activation_event(
    team_id: str,
    steward_candidate_id: str,
    activation: dict[str, Any],
) -> None:
    s = _service()
    status = s._trim_text(activation.get("status"), max_length=120) or "unknown"
    failed = status == "message_failed" or status.startswith("skipped_")
    s._record_workflow_event(
        "knowledge_collection.steward_notification_failed" if failed else "knowledge_collection.steward_notification_completed",
        team_id,
        level="warning" if failed else "info",
        outcome="failed" if failed else "completed",
        fields={
            "stewardPackCandidateId": steward_candidate_id,
            "targetAgentId": s._trim_text(activation.get("targetAgentId"), max_length=160),
            "knowledgeBaseId": s._trim_text((activation.get("metadata") or {}).get("knowledgeBaseId"), max_length=128)
            if isinstance(activation.get("metadata"), dict)
            else "",
            "status": status,
            "messageId": s._trim_text(activation.get("messageId"), max_length=160),
            "threadId": s._trim_text(activation.get("threadId"), max_length=240),
            "wakeRequested": bool(activation.get("wakeRequested")),
            "wakeStatus": s._trim_text(activation.get("wakeStatus"), max_length=120),
            "turnId": s._trim_text((activation.get("delivery") or {}).get("turnId"), max_length=160)
            if isinstance(activation.get("delivery"), dict)
            else "",
            "errorType": s._trim_text(activation.get("errorType"), max_length=160),
        },
        child_log_path=f"artifacts/knowledge-steward-{s._safe_token(steward_candidate_id, default='candidate', max_length=96)}-notification.jsonl",
        child_log_payload={
            "kind": "knowledge_steward_ingestion_notification",
            "teamId": team_id,
            "stewardPackCandidateId": steward_candidate_id,
            "targetAgentId": s._trim_text(activation.get("targetAgentId"), max_length=160),
            "knowledgeBaseId": s._trim_text((activation.get("metadata") or {}).get("knowledgeBaseId"), max_length=128)
            if isinstance(activation.get("metadata"), dict)
            else "",
            "status": status,
            "messageId": s._trim_text(activation.get("messageId"), max_length=160),
            "threadId": s._trim_text(activation.get("threadId"), max_length=240),
            "wakeRequested": bool(activation.get("wakeRequested")),
            "wakeStatus": s._trim_text(activation.get("wakeStatus"), max_length=120),
            "turnId": s._trim_text((activation.get("delivery") or {}).get("turnId"), max_length=160)
            if isinstance(activation.get("delivery"), dict)
            else "",
            "kernel": activation.get("kernel") if isinstance(activation.get("kernel"), dict) else {},
            "errorType": s._trim_text(activation.get("errorType"), max_length=160),
        },
    )


def _knowledge_steward_activation_log_payload(activation: dict[str, Any] | None) -> dict[str, Any]:
    s = _service()
    if not isinstance(activation, dict):
        return {}
    delivery = activation.get("delivery") if isinstance(activation.get("delivery"), dict) else {}
    metadata = activation.get("metadata") if isinstance(activation.get("metadata"), dict) else {}
    return {
        "status": s._trim_text(activation.get("status"), max_length=120),
        "targetAgentId": s._trim_text(activation.get("targetAgentId"), max_length=160),
        "knowledgeBaseId": s._trim_text(metadata.get("knowledgeBaseId"), max_length=128),
        "messageId": s._trim_text(activation.get("messageId"), max_length=160),
        "threadId": s._trim_text(activation.get("threadId"), max_length=240),
        "wakeRequested": bool(activation.get("wakeRequested")),
        "wakeStatus": s._trim_text(activation.get("wakeStatus"), max_length=120),
        "turnId": s._trim_text(delivery.get("turnId"), max_length=160),
        "kernel": activation.get("kernel") if isinstance(activation.get("kernel"), dict) else {},
        "errorType": s._trim_text(activation.get("errorType"), max_length=160),
    }


def _resolve_team_review_agent_id(team: dict[str, Any], *, exclude_agent_id: str = "") -> str:
    """Resolve a team member that can act as the knowledge-review authority.

    Separation of duties: the steward proposes; a distinct coordinator/lead
    member reviews and applies. Returns the matched member agentId, or "" when
    the team has no coordinator/lead member to act as reviewer.
    """
    s = _service()
    excluded = str(exclude_agent_id or "").strip()
    members = team.get("members") if isinstance(team, dict) else None
    if not isinstance(members, list):
        return ""
    for hint in s._TEAM_REVIEW_ROLE_HINTS:
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


def _knowledge_ingestion_work_run_store() -> Any:
    s = _service()
    return s.work_run_store.WorkRunStore(root=s.work_run_store.WORK_RUNS_DIR)


def _persist_knowledge_ingestion_work_run(
    team_id: str,
    run_id: str,
    *,
    status: str,
    current_phase: str,
    summary: str,
    active: bool,
    result: dict[str, Any] | None = None,
    completion_steps: list[dict[str, Any]] | None = None,
    flow_visualization: dict[str, Any] | None = None,
    source_run_id: str = "",
    error: str = "",
    error_type: str = "",
) -> dict[str, Any]:
    s = _service()
    now = s.utc_now_iso()
    snapshot: dict[str, Any] = {
        "runId": run_id,
        "runKind": s.KNOWLEDGE_INGESTION_WORK_RUN_KIND,
        "kind": s.KNOWLEDGE_INGESTION_WORK_RUN_KIND,
        "status": status,
        "currentPhase": current_phase,
        "stageType": "knowledge_ingestion",
        "teamId": team_id,
        "summary": s._trim_text(summary, max_length=500),
        "currentTask": s._trim_text(summary, max_length=500),
        "updatedAt": now,
    }
    result_source_run_id = (result or {}).get("sourceRunId") if isinstance(result, dict) else ""
    normalized_source_run_id = s._trim_text(source_run_id or result_source_run_id, max_length=160)
    if normalized_source_run_id:
        snapshot["sourceRunId"] = normalized_source_run_id
    normalized_completion_steps = s._knowledge_collection_completion_steps_for_snapshot(result, completion_steps)
    if normalized_completion_steps:
        snapshot["completionSteps"] = normalized_completion_steps
    if isinstance(flow_visualization, dict):
        snapshot["flowVisualization"] = flow_visualization
    elif normalized_completion_steps:
        snapshot["flowVisualization"] = s._knowledge_collection_completion_flow_visualization(
            status,
            steps=normalized_completion_steps,
            result=result,
            error=error,
            error_type=error_type,
        )
    if not active:
        snapshot["finishedAt"] = now
    if isinstance(result, dict):
        result_summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
        snapshot["result"] = {
            "status": s._trim_text(result.get("status"), max_length=80),
            "formalKnowledgeItemCount": s._source_collection_count(result_summary.get("formalKnowledgeItemCount")),
            "knowledgeBaseId": s._trim_text(result_summary.get("knowledgeBaseId"), max_length=128),
            "scopedKnowledgeBaseId": s._trim_text(result_summary.get("scopedKnowledgeBaseId"), max_length=256),
            "stewardPackCandidateId": s._trim_text(result_summary.get("stewardPackCandidateId"), max_length=160),
        }
    if error:
        snapshot["error"] = s._trim_text(error, max_length=500)
    if error_type:
        snapshot["errorType"] = s._trim_text(error_type, max_length=120)
    return s._knowledge_ingestion_work_run_store().persist_snapshot(
        s.KNOWLEDGE_INGESTION_WORK_RUN_KIND,
        snapshot,
        active_run_id=run_id if active else "",
    )


def _knowledge_ingestion_snapshot_is_active(snapshot: dict[str, Any] | None, team_id: str) -> bool:
    s = _service()
    if not isinstance(snapshot, dict):
        return False
    if s._trim_text(snapshot.get("teamId"), max_length=160) != team_id:
        return False
    status = s._trim_text(snapshot.get("status"), max_length=80).lower()
    current_phase = s._trim_text(snapshot.get("currentPhase"), max_length=80).lower()
    return status in {"queued", "running"} or current_phase in {"queued", "running"}


def _decorate_knowledge_ingestion_work_run_snapshot(snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
    s = _service()
    if not isinstance(snapshot, dict):
        return None
    payload = dict(snapshot)
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    raw_steps = payload.get("completionSteps") if isinstance(payload.get("completionSteps"), list) else []
    steps = s._knowledge_collection_completion_steps_for_snapshot(result, raw_steps)
    status = s._trim_text(payload.get("status"), max_length=120) or "unknown"
    error = s._trim_text(payload.get("error"), max_length=500)
    error_type = s._trim_text(payload.get("errorType"), max_length=160)
    run_id = s._trim_text(payload.get("runId"), max_length=160)
    source_run_id = s._trim_text(payload.get("sourceRunId"), max_length=160)
    existing_flow = payload.get("flowVisualization") if isinstance(payload.get("flowVisualization"), dict) else None
    existing_flow_nodes = existing_flow.get("nodes") if isinstance(existing_flow, dict) and isinstance(existing_flow.get("nodes"), list) else []
    official_knowledge_completed = any(
        s._trim_text(step.get("stageId"), max_length=120) == "official_knowledge"
        and s._knowledge_collection_flow_step_status(step.get("status")) == "completed"
        for step in steps
    )
    stale_completed_flow = (
        isinstance(existing_flow, dict)
        and s._knowledge_collection_flow_step_status(status) == "completed"
        and official_knowledge_completed
        and any(
            isinstance(node, dict)
            and s._trim_text(node.get("stageId"), max_length=120) == "ingestion"
            and s._knowledge_collection_flow_step_status(node.get("status")) != "completed"
            for node in existing_flow_nodes
        )
    )
    if isinstance(existing_flow, dict) and not stale_completed_flow:
        return payload
    should_backfill_flow = bool(steps) or bool(source_run_id) or run_id.startswith("knowledge-completion")
    if not steps and s._knowledge_collection_flow_step_status(status) == "failed":
        steps = [s._knowledge_collection_failed_step_for_snapshot(payload)]
        should_backfill_flow = True
    if should_backfill_flow or stale_completed_flow:
        payload["flowVisualization"] = s._knowledge_collection_completion_flow_visualization(
            status,
            steps=steps,
            result=result,
            error=error,
            error_type=error_type,
        )
    return payload


def _knowledge_collection_failed_step_for_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    phase = s._trim_text(snapshot.get("currentPhase") or snapshot.get("stageType"), max_length=120).lower()
    if "search" in phase or "collection" in phase:
        stage_id = "remaining_search"
    elif "candidate" in phase or "extract" in phase:
        stage_id = "candidate_extraction"
    elif "screen" in phase or "quality" in phase or "review" in phase:
        stage_id = "source_review"
    elif "graph" in phase:
        stage_id = "candidate_graph"
    else:
        stage_id = "knowledge_ingestion"
    step = s._knowledge_collection_completion_step(
        stage_id,
        "failed",
        error_type=s._trim_text(snapshot.get("errorType"), max_length=160),
    )
    error = s._trim_text(snapshot.get("error"), max_length=300)
    if error:
        step["detail"] = error
    return step


def _knowledge_ingestion_background_response(team_id: str, snapshot: dict[str, Any], *, already_running: bool) -> dict[str, Any]:
    s = _service()
    return {
        "schemaVersion": s.SCHEMA_VERSION,
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


def _knowledge_collection_completion_payload(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    s = _service()
    request_payload = dict(payload) if isinstance(payload, dict) else {}
    request_payload.update(
        {
            "autoCreateKnowledgeBase": True,
            "autoSubmit": True,
            "autoReviewSource": True,
            "autoApprove": True,
            "notifyStewardAgent": False,
            "wakeStewardAgent": False,
            "backgroundExecution": True,
        }
    )
    return request_payload


def _knowledge_collection_completion_step(
    stage_id: str,
    status: str,
    *,
    input_count: int = 0,
    output_count: int = 0,
    artifact_id: str = "",
    error_type: str = "",
) -> dict[str, Any]:
    s = _service()
    step = {
        "stageId": stage_id,
        "status": s._trim_text(status, max_length=120) or "unknown",
        "inputCount": s._source_collection_count(input_count),
        "outputCount": s._source_collection_count(output_count),
    }
    if artifact_id:
        step["artifactId"] = s._trim_text(artifact_id, max_length=160)
    if error_type:
        step["errorType"] = s._trim_text(error_type, max_length=160)
    return step


def _knowledge_base_raw_id(value: Any) -> str:
    s = _service()
    text = s._trim_text(value, max_length=256)
    parts = text.split(":", 2)
    if len(parts) == 3 and parts[0] in {"team", "agent"} and parts[1] and parts[2]:
        return parts[2]
    return text


def _knowledge_base_scoped_id_for_team(team_id: str, value: Any, base: dict[str, Any] | None = None) -> str:
    s = _service()
    if isinstance(base, dict):
        scoped = s._trim_text(base.get("scopedKnowledgeBaseId"), max_length=256)
        if scoped:
            return scoped
    text = s._trim_text(value, max_length=256)
    if not text:
        return ""
    parts = text.split(":", 2)
    if len(parts) == 3 and parts[0] in {"team", "agent"} and parts[1] and parts[2]:
        return text
    return f"team:{team_id}:{text}"


def _knowledge_collection_completion_steps_for_snapshot(
    result: dict[str, Any] | None = None,
    steps: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    s = _service()
    payload = result if isinstance(result, dict) else {}
    normalized_steps = [dict(item) for item in list(steps or []) if isinstance(item, dict)]
    if not normalized_steps:
        normalized_steps = [dict(item) for item in list(payload.get("completionSteps") or []) if isinstance(item, dict)]
    if not normalized_steps and payload:
        normalized_steps = s._knowledge_collection_completion_steps_from_result(payload)
    ingestion = payload.get("ingestion") if isinstance(payload.get("ingestion"), dict) else {}
    ingestion_steps = [dict(item) for item in list(ingestion.get("steps") or []) if isinstance(item, dict)]
    seen_stage_ids = {
        s._trim_text(item.get("stageId"), max_length=120)
        for item in normalized_steps
        if s._trim_text(item.get("stageId"), max_length=120)
    }
    for step in ingestion_steps:
        stage_id = s._trim_text(step.get("stageId"), max_length=120)
        if stage_id and stage_id not in seen_stage_ids:
            normalized_steps.append(step)
            seen_stage_ids.add(stage_id)
    return normalized_steps[:48]


def _knowledge_collection_flow_step_status(value: Any) -> str:
    s = _service()
    status = s._trim_text(value, max_length=120).lower()
    if status in {"failed", "blocked", "error", "agent_notification_failed"} or status.startswith("failed"):
        return "failed"
    if status in {"running", "in_progress", "queued", "started"} or status.endswith("_running"):
        return "running"
    if status in {
        "pending",
        "pending_review",
        "needs_review",
        "needs_revision",
        "precheck_ready",
        "agent_notified",
        "agent_wake_pending",
        "message_written",
        "agent_wake_started",
    }:
        return "pending"
    if status in {"completed", "complete", "applied", "approved", "official_synced", "synced", "ready"}:
        return "completed"
    if status == "skipped":
        return "skipped"
    return status or "queued"


def _knowledge_collection_flow_node_status(step_statuses: list[str]) -> str:
    s = _service()
    if not step_statuses:
        return "queued"
    if any(status == "failed" for status in step_statuses):
        return "failed"
    if any(status == "running" for status in step_statuses):
        return "running"
    if any(status == "pending" for status in step_statuses):
        return "pending"
    if any(status == "completed" for status in step_statuses):
        return "completed"
    if all(status == "skipped" for status in step_statuses):
        return "skipped"
    return step_statuses[-1] or "queued"


def _knowledge_collection_completion_flow_visualization(
    status: str,
    *,
    steps: list[dict[str, Any]] | None = None,
    result: dict[str, Any] | None = None,
    error: str = "",
    error_type: str = "",
) -> dict[str, Any]:
    s = _service()
    normalized_steps = s._knowledge_collection_completion_steps_for_snapshot(result, steps)
    steps_by_stage_id: dict[str, list[dict[str, Any]]] = {}
    for step in normalized_steps:
        stage_id = s._trim_text(step.get("stageId"), max_length=120)
        if not stage_id:
            continue
        steps_by_stage_id.setdefault(stage_id, []).append(step)
    nodes: list[dict[str, Any]] = []
    current_stage_id = ""
    for stage in s._KNOWLEDGE_COLLECTION_COMPLETION_FLOW_STAGES:
        stage_step_ids = set(stage["stepIds"])
        stage_steps = [
            step
            for step_id, items in steps_by_stage_id.items()
            if step_id in stage_step_ids
            for step in items
        ]
        step_statuses = [s._knowledge_collection_flow_step_status(step.get("status")) for step in stage_steps]
        node_status = s._knowledge_collection_flow_node_status(step_statuses)
        if stage["stageId"] == "ingestion" and node_status == "pending":
            official_knowledge_completed = any(
                s._trim_text(step.get("stageId"), max_length=120) == "official_knowledge"
                and s._knowledge_collection_flow_step_status(step.get("status")) == "completed"
                for step in stage_steps
            )
            if official_knowledge_completed:
                node_status = "completed"
        node_error_type = next(
            (s._trim_text(step.get("errorType"), max_length=160) for step in stage_steps if s._trim_text(step.get("errorType"), max_length=160)),
            "",
        )
        node = {
            "stageId": stage["stageId"],
            "label": stage["label"],
            "agentRole": stage["agentRole"],
            "status": node_status,
            "inputCount": sum(s._source_collection_count(step.get("inputCount")) for step in stage_steps),
            "outputCount": sum(s._source_collection_count(step.get("outputCount")) for step in stage_steps),
            "artifactIds": [
                s._trim_text(step.get("artifactId"), max_length=160)
                for step in stage_steps
                if s._trim_text(step.get("artifactId"), max_length=160)
            ][:12],
            "detail": next(
                (s._trim_text(step.get("detail"), max_length=300) for step in reversed(stage_steps) if s._trim_text(step.get("detail"), max_length=300)),
                "",
            ),
            "errorType": node_error_type,
        }
        if node_status in {"running", "failed", "pending"} and not current_stage_id:
            current_stage_id = node["stageId"]
        nodes.append(node)
    flow_status = s._trim_text(status, max_length=120) or "unknown"
    if flow_status == "running" and not any(node["status"] == "running" for node in nodes):
        for node in nodes:
            if node["status"] not in {"completed", "skipped"}:
                node["status"] = "running"
                current_stage_id = node["stageId"]
                break
    if flow_status == "completed":
        for node in nodes:
            if node["status"] == "queued":
                node["status"] = "completed"
    return {
        "kind": "knowledge_collection_completion",
        "schemaVersion": s.SCHEMA_VERSION,
        "status": flow_status,
        "currentStageId": current_stage_id,
        "nodes": nodes,
        "error": s._trim_text(error, max_length=500),
        "errorType": s._trim_text(error_type, max_length=160),
    }


def _knowledge_collection_completion_log_payload(
    team_id: str,
    run_id: str,
    result: dict[str, Any] | None = None,
    *,
    status: str = "",
    source_run_id: str = "",
    steps: list[dict[str, Any]] | None = None,
    error_type: str = "",
) -> dict[str, Any]:
    s = _service()
    payload = result if isinstance(result, dict) else {}
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    ingestion = payload.get("ingestion") if isinstance(payload.get("ingestion"), dict) else {}
    ingestion_summary = ingestion.get("summary") if isinstance(ingestion.get("summary"), dict) else {}
    normalized_steps = [item for item in list(steps or payload.get("completionSteps") or []) if isinstance(item, dict)]
    if not normalized_steps and payload:
        normalized_steps = s._knowledge_collection_completion_steps_from_result(payload)
    knowledge_base_id = s._trim_text(summary.get("knowledgeBaseId") or ingestion_summary.get("knowledgeBaseId"), max_length=160)
    formal_count = s._source_collection_count(summary.get("formalKnowledgeItemCount") or ingestion_summary.get("formalKnowledgeItemCount"))
    return {
        "kind": "knowledge_collection_completion",
        "teamId": team_id,
        "runId": run_id,
        "status": s._trim_text(status or payload.get("status"), max_length=120) or "unknown",
        "sourceRunId": s._trim_text(source_run_id or payload.get("sourceRunId"), max_length=160),
        "steps": normalized_steps[:24],
        "truncatedStepCount": max(0, len(normalized_steps) - 24),
        "searchExecutionCount": s._source_collection_count(summary.get("searchExecutionCount") or len(payload.get("searchExecutions") or [])),
        "extractedCandidateCount": s._source_collection_count(summary.get("extractedCandidateCount")),
        "formalKnowledgeItemCount": formal_count,
        "knowledgeBaseId": knowledge_base_id,
        "errorType": s._trim_text(error_type, max_length=160),
    }


def _knowledge_collection_completion_steps_from_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    s = _service()
    search_executions = [item for item in list(result.get("searchExecutions") or []) if isinstance(item, dict)]
    last_search = search_executions[-1] if search_executions else {}
    search_summary = last_search.get("summary") if isinstance(last_search.get("summary"), dict) else {}
    extraction = result.get("extraction") if isinstance(result.get("extraction"), dict) else {}
    ingestion = result.get("ingestion") if isinstance(result.get("ingestion"), dict) else {}
    ingestion_summary = ingestion.get("summary") if isinstance(ingestion.get("summary"), dict) else {}
    return [
        s._knowledge_collection_completion_step(
            "remaining_search",
            s._trim_text(last_search.get("status"), max_length=120) if last_search else "skipped",
            input_count=len(search_executions),
            output_count=s._source_collection_count(search_summary.get("recordCount")),
        ),
        s._knowledge_collection_completion_step(
            "candidate_extraction",
            s._trim_text(extraction.get("status"), max_length=120) if extraction else "skipped",
            input_count=s._source_collection_count(extraction.get("importedCount"))
            + s._source_collection_count(extraction.get("skippedCount"))
            + s._source_collection_count(extraction.get("failedCount")),
            output_count=s._source_collection_count(extraction.get("importedCount")),
        ),
        s._knowledge_collection_completion_step(
            "knowledge_ingestion",
            s._trim_text(ingestion.get("status"), max_length=120) if ingestion else "skipped",
            input_count=s._source_collection_count((ingestion_summary or {}).get("approvedSourceCandidateCount")),
            output_count=s._source_collection_count(ingestion_summary.get("formalKnowledgeItemCount")),
            artifact_id=s._trim_text(ingestion_summary.get("knowledgeBaseId"), max_length=160),
        ),
    ]


def _attach_knowledge_completion_failure_payload(
    exc: Exception,
    *,
    team_id: str,
    run_id: str = "",
    source_run_id: str = "",
    steps: list[dict[str, Any]] | None = None,
    failed_stage_id: str = "",
) -> Exception:
    s = _service()
    normalized_steps = [item for item in list(steps or []) if isinstance(item, dict)]
    if failed_stage_id:
        normalized_steps.append(
            s._knowledge_collection_completion_step(
                failed_stage_id,
                "failed",
                error_type=type(exc).__name__,
            )
        )
    setattr(
        exc,
        "completion_log_payload",
        s._knowledge_collection_completion_log_payload(
            team_id,
            run_id,
            status="failed",
            source_run_id=source_run_id,
            steps=normalized_steps,
            error_type=type(exc).__name__,
        ),
    )
    return exc


def _run_knowledge_collection_completion_background(team_id: str, run_id: str, payload: dict[str, Any]) -> None:
    s = _service()
    running_steps = [s._knowledge_collection_completion_step("remaining_search", "running")]
    try:
        s._persist_knowledge_ingestion_work_run(
            team_id,
            run_id,
            status="running",
            current_phase="running",
            summary="知识搜集一键完成正在执行：资料寻找、资料提炼、资料关系整理和资料入库。",
            active=True,
            completion_steps=running_steps,
            flow_visualization=s._knowledge_collection_completion_flow_visualization("running", steps=running_steps),
            source_run_id=s._trim_text(payload.get("runId") or payload.get("sourceRunId"), max_length=160),
        )
        result = s.run_knowledge_collection_completion(team_id, payload)
    except Exception as exc:
        failure_payload = getattr(exc, "completion_log_payload", {})
        if not isinstance(failure_payload, dict):
            failure_payload = {}
        failure_steps = s._knowledge_collection_completion_steps_for_snapshot(steps=[
            item for item in list(failure_payload.get("steps") or []) if isinstance(item, dict)
        ])
        failure_source_run_id = s._trim_text(
            failure_payload.get("sourceRunId") or payload.get("runId") or payload.get("sourceRunId"),
            max_length=160,
        )
        s._persist_knowledge_ingestion_work_run(
            team_id,
            run_id,
            status="failed",
            current_phase="failed",
            summary=s._trim_text(exc, max_length=300) or "知识搜集一键完成失败。",
            active=False,
            completion_steps=failure_steps,
            flow_visualization=s._knowledge_collection_completion_flow_visualization(
                "failed",
                steps=failure_steps,
                error=str(exc),
                error_type=type(exc).__name__,
            ),
            source_run_id=failure_source_run_id,
            error=s._trim_text(exc, max_length=500),
            error_type=type(exc).__name__,
        )
        s._record_workflow_event(
            "knowledge_collection.completion_background_failed",
            team_id,
            fields={"runId": run_id, "errorType": type(exc).__name__, "error": s._trim_text(exc, max_length=500)},
            level="warning",
            outcome="failed",
            child_log_path=f"artifacts/knowledge-collection-{s._safe_token(run_id, default='run', max_length=96)}-completion.jsonl",
            child_log_payload=getattr(
                exc,
                "completion_log_payload",
                s._knowledge_collection_completion_log_payload(
                    team_id,
                    run_id,
                    status="failed",
                    source_run_id=s._trim_text(payload.get("runId") or payload.get("sourceRunId"), max_length=160),
                    error_type=type(exc).__name__,
                ),
            ),
        )
        return
    result_summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    formal_count = s._source_collection_count(result_summary.get("formalKnowledgeItemCount"))
    terminal_status = s._trim_text(result.get("status"), max_length=80) or "completed"
    completion_steps = s._knowledge_collection_completion_steps_for_snapshot(result)
    s._persist_knowledge_ingestion_work_run(
        team_id,
        run_id,
        status="completed" if formal_count > 0 else terminal_status,
        current_phase="completed" if formal_count > 0 else terminal_status,
        summary=(
            f"知识搜集一键完成：正式 KnowledgeItem {formal_count} 条。"
            if formal_count > 0
            else f"知识搜集一键完成结束：{terminal_status}。"
        ),
        active=False,
        result=result,
        completion_steps=completion_steps,
        flow_visualization=s._knowledge_collection_completion_flow_visualization(
            "completed" if formal_count > 0 else terminal_status,
            steps=completion_steps,
            result=result,
        ),
        source_run_id=s._trim_text(result.get("sourceRunId"), max_length=160),
    )
    s._record_workflow_event(
        "knowledge_collection.completion_background_completed",
        team_id,
        fields={
            "runId": run_id,
            "status": terminal_status,
            "sourceRunId": s._trim_text(result.get("sourceRunId"), max_length=160),
            "searchExecutionCount": s._source_collection_count(result_summary.get("searchExecutionCount")),
            "formalKnowledgeItemCount": formal_count,
        },
        child_log_path=f"artifacts/knowledge-collection-{s._safe_token(run_id, default='run', max_length=96)}-completion.jsonl",
        child_log_payload=s._knowledge_collection_completion_log_payload(
            team_id,
            run_id,
            result,
            status=terminal_status,
        ),
    )


def _run_knowledge_collection_ingestion_background(team_id: str, run_id: str, payload: dict[str, Any]) -> None:
    s = _service()
    try:
        result = s.run_knowledge_collection_ingestion(team_id, payload)
    except Exception as exc:
        s._persist_knowledge_ingestion_work_run(
            team_id,
            run_id,
            status="failed",
            current_phase="failed",
            summary=s._trim_text(exc, max_length=300) or "资料入库后台执行失败。",
            active=False,
            error=s._trim_text(exc, max_length=500),
            error_type=type(exc).__name__,
        )
        s._record_workflow_event(
            "knowledge_collection.ingestion_background_failed",
            team_id,
            fields={"runId": run_id, "errorType": type(exc).__name__, "error": s._trim_text(exc, max_length=500)},
        )
        return
    result_summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    formal_count = s._source_collection_count(result_summary.get("formalKnowledgeItemCount"))
    terminal_status = s._trim_text(result.get("status"), max_length=80) or "completed"
    s._persist_knowledge_ingestion_work_run(
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
    s._record_workflow_event(
        "knowledge_collection.ingestion_background_completed",
        team_id,
        fields={"runId": run_id, "status": terminal_status, "formalKnowledgeItemCount": formal_count},
    )


def _local_research_output_state(task_type: str, valid: bool) -> str:
    s = _service()
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
    s = _service()
    nodes = [s._candidate_graph_node(candidate) for candidate in candidates]
    node_ids = {node["candidateId"] for node in nodes}
    edges: list[dict[str, str]] = []
    missing_links: list[dict[str, str]] = []
    for candidate in candidates:
        source_id = str(candidate.get("candidateId") or "")
        if not source_id:
            continue
        for edge in s._candidate_graph_edges(candidate):
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
        "schemaVersion": s.SCHEMA_VERSION,
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
        "createdAt": s.utc_now_iso(),
    }


def _candidate_graph_node(candidate: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    output = metadata.get("output") if isinstance(metadata.get("output"), dict) else {}
    validation = s.validate_candidate_record(candidate)
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
    s = _service()
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    rejection_archive = metadata.get("rejectionArchive") if isinstance(metadata.get("rejectionArchive"), dict) else {}
    return (
        str(candidate.get("currentState") or "") in s.ARCHIVED_CANDIDATE_STATES
        or str(candidate.get("currentWorkflowNode") or "") in s.ARCHIVED_WORKFLOW_NODES
        or str(rejection_archive.get("status") or "") == "archived"
    )


def _candidate_graph_edges(candidate: dict[str, Any]) -> list[dict[str, str]]:
    s = _service()
    source_id = str(candidate.get("candidateId") or "")
    candidate_type = str(candidate.get("candidateType") or "")
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    output = metadata.get("output") if isinstance(metadata.get("output"), dict) else {}
    edges: list[dict[str, str]] = []
    if candidate_type == "neuro_mechanism":
        for target_id in s._normalize_id_values(output.get("paperNoteIds")):
            edges.append(s._candidate_graph_edge(source_id, target_id, "supported_by_paper_note"))
    if candidate_type == "mechanism_mapping":
        for target_id in s._normalize_id_values(output.get("neuroMechanismIds")):
            edges.append(s._candidate_graph_edge(source_id, target_id, "maps_from_neuro_mechanism"))
    if candidate_type == "algorithm_hypothesis":
        for target_id in s._normalize_id_values(output.get("mechanismMappingIds")):
            edges.append(s._candidate_graph_edge(source_id, target_id, "inspired_by_mapping"))
        for target_id in s._normalize_id_values(output.get("neuroMechanismIds")):
            edges.append(s._candidate_graph_edge(source_id, target_id, "inspired_by_neuro_mechanism"))
    if candidate_type == "review_record":
        for target_id in s._normalize_id_values(output.get("candidateIds") or output.get("reviewedCandidateIds")):
            edges.append(s._candidate_graph_edge(source_id, target_id, "reviews_candidate"))
    return edges


def _candidate_graph_edge(source_id: str, target_id: str, relation: str) -> dict[str, str]:
    s = _service()
    return {
        "sourceCandidateId": source_id,
        "targetCandidateId": target_id,
        "relation": relation,
        "edgeState": "candidate_only",
    }


def _candidate_ready_for_agent_graph(candidate: dict[str, Any]) -> bool:
    s = _service()
    if not s._candidate_allowed_for_agent_graph_input(candidate):
        return False
    candidate_type = str(candidate.get("candidateType") or "")
    current_state = str(candidate.get("currentState") or "")
    quality_status = str(candidate.get("qualityStatus") or "")
    if current_state in s.ARCHIVED_CANDIDATE_STATES or quality_status in s.SOURCE_QUALITY_REJECTED_STATUSES:
        return False
    if candidate_type == "source_manifest":
        return s._source_quality_bucket(candidate) == "approved"
    if candidate_type not in {"paper_note", "neuro_mechanism", "mechanism_mapping", "algorithm_hypothesis", "review_record"}:
        return False
    if current_state.endswith("_needs_revision") or quality_status in {"needs_revision", "source_quality_needs_revision"}:
        return False
    validation = s.validate_candidate_record(candidate)
    return bool(validation.get("valid"))


def _candidate_allowed_for_agent_graph_input(candidate: dict[str, Any]) -> bool:
    s = _service()
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
    s = _service()
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
    s = _service()
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    ingestion = metadata.get("knowledgeCollectionIngestion") if isinstance(metadata.get("knowledgeCollectionIngestion"), dict) else {}
    output = metadata.get("output") if isinstance(metadata.get("output"), dict) else {}
    output_ingestion = output.get("knowledgeCollectionIngestion") if isinstance(output.get("knowledgeCollectionIngestion"), dict) else {}
    return s._trim_text(ingestion.get("fingerprint") or output_ingestion.get("fingerprint") or candidate.get("ingestionFingerprint"), max_length=80)


def _find_reusable_candidate_graph(candidate_store: dict[str, Any], fingerprint: str) -> dict[str, Any] | None:
    s = _service()
    candidates = [
        item
        for item in list(candidate_store.get("candidates") or [])
        if isinstance(item, dict)
        and str(item.get("candidateType") or "") == "candidate_graph"
        and not s._candidate_is_archived(item)
        and s._candidate_knowledge_collection_fingerprint(item) == fingerprint
    ]
    return s._latest_candidate_record(candidates)


def _find_reusable_steward_pack(candidate_store: dict[str, Any], fingerprint: str) -> dict[str, Any] | None:
    s = _service()
    reusable_states = {"steward_pack_draft", "pending_source_review", "pending_review"}
    candidates = [
        item
        for item in list(candidate_store.get("candidates") or [])
        if isinstance(item, dict)
        and str(item.get("candidateType") or "") != "candidate_graph"
        and not s._candidate_is_archived(item)
        and (
            str(item.get("currentWorkflowNode") or "") == "steward_ingestion"
            or str((item.get("metadata") if isinstance(item.get("metadata"), dict) else {}).get("taskType") or "") == "steward_pack_draft"
        )
        and str(item.get("currentState") or "") in reusable_states
        and s._candidate_knowledge_collection_fingerprint(item) == fingerprint
    ]
    return s._latest_candidate_record(candidates)


def _latest_candidate_record(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    s = _service()
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
    s = _service()
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
    s = _service()
    candidate_type = str(candidate.get("candidateType") or "candidate")
    return {
        "type": candidate_type,
        "id": str(candidate.get("candidateId") or ""),
        "label": s._source_manifest_label(candidate),
    }


def _build_knowledge_ingestion_precheck_output(
    team_id: str,
    workflow_id: str,
    selected_candidates: list[dict[str, Any]],
    latest_graph: dict[str, Any] | None,
    *,
    target_domain: str,
) -> dict[str, Any]:
    s = _service()
    candidate_ids = [str(item.get("candidateId") or "") for item in selected_candidates if item.get("candidateId")]
    source_refs = [s._candidate_precheck_ref(item) for item in selected_candidates[:32]]
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
                "label": s._trim_text(latest_graph.get("title"), max_length=240) or "Candidate graph snapshot",
            }
        )
    source_ids = [str(item.get("candidateId") or "") for item in selected_candidates if str(item.get("candidateType") or "") == "source_manifest"]
    local_ids = [str(item.get("candidateId") or "") for item in selected_candidates if str(item.get("candidateType") or "") != "source_manifest"]
    claims = []
    for item in selected_candidates[:24]:
        label = s._source_manifest_label(item)
        summary = s._trim_text(item.get("summary"), max_length=600)
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
            "content": "；".join(s._source_manifest_label(item) for item in selected_candidates[:12]),
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
    s = _service()
    source_path = s._trim_text(candidate.get("sourcePath"), max_length=2000)
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    metadata_path = s._trim_text(metadata.get("path") or metadata.get("sourcePath"), max_length=2000)
    return source_path or metadata_path


def _source_manifest_label(candidate: dict[str, Any]) -> str:
    s = _service()
    return (
        s._trim_text(candidate.get("title"), max_length=240)
        or s._trim_text(candidate.get("sourceUrl"), max_length=240)
        or s._trim_text(candidate.get("sourcePath"), max_length=240)
        or s._trim_text(candidate.get("candidateId"), max_length=128)
        or "source_manifest"
    )


def _knowledge_ingestion_candidate_summary(
    candidates: list[dict[str, Any]],
    candidate_reports: list[dict[str, Any]],
    candidate_graph: dict[str, Any],
) -> dict[str, int]:
    s = _service()
    non_graph_candidates = [item for item in candidates if str(item.get("candidateType") or "") != "candidate_graph"]
    source_candidates = [item for item in non_graph_candidates if str(item.get("candidateType") or "") == "source_manifest"]
    source_ready = [
        item
        for item in source_candidates
        if str(item.get("qualityStatus") or "") in s.SOURCE_QUALITY_APPROVED_STATUSES
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
    pending_ingestion = [item for item in non_graph_candidates if s._candidate_knowledge_ingestion_status(item) == "pending_review"]
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
    archived_count = sum(1 for item in non_graph_candidates if s._candidate_is_archived(item))
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
    s = _service()
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
    s = _service()
    return [
        s._knowledge_ingestion_stage(
            "source_collection",
            "知识搜集",
            candidate_summary["sourceCandidateCount"],
            ready=candidate_summary["sourceReadyCount"] > 0,
            warning=candidate_summary["invalidCandidateCount"] > 0,
            blocked=candidate_summary["sourceCandidateCount"] == 0,
            next_action="register_candidate_source",
            reason="至少需要一个可分析的来源候选。",
        ),
        s._knowledge_ingestion_stage(
            "candidate_screening",
            "候选筛选",
            candidate_summary["localDraftCandidateCount"],
            ready=candidate_summary["localDraftCandidateCount"] > 0,
            warning=candidate_summary["unreviewedNodeCount"] > 0 or candidate_summary["missingLinkCount"] > 0,
            blocked=candidate_summary["sourceReadyCount"] == 0,
            next_action="run_local_research_model_tasks",
            reason="需要从来源生成 paper_note、机制、映射、算法假设或预审记录。",
        ),
        s._knowledge_ingestion_stage(
            "steward_pack",
            "入库包生成",
            candidate_summary["stewardPackCandidateCount"],
            ready=candidate_summary["stewardPackCandidateCount"] > 0,
            warning=candidate_summary["pendingKnowledgeReviewCandidateCount"] > 0,
            blocked=candidate_summary["localDraftCandidateCount"] == 0,
            next_action="draft_steward_pack",
            reason="需要由知识治理边界生成 steward pack，不能直接写正式知识。",
        ),
        s._knowledge_ingestion_stage(
            "knowledge_review",
            "团队知识库审核",
            knowledge_summary["proposalCount"],
            ready=knowledge_summary["formalKnowledgeItemCount"] > 0,
            warning=knowledge_summary["pendingProposalCount"] > 0,
            blocked=candidate_summary["stewardPackCandidateCount"] > 0 and knowledge_summary["proposalCount"] == 0,
            next_action="submit_or_review_refinement_proposal",
            reason="正式团队知识库必须经 refinement proposal 审核。",
        ),
        s._knowledge_ingestion_stage(
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
    s = _service()
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
    s = _service()
    items: list[dict[str, Any]] = []
    if candidate_summary["sourceCandidateCount"] == 0:
        items.append(
            s._knowledge_ingestion_action_item(
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
            s._knowledge_ingestion_action_item(
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
            s._knowledge_ingestion_action_item(
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
            s._knowledge_ingestion_action_item(
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
        if str(item.get("candidateType") or "") != "candidate_graph" and s._candidate_knowledge_ingestion_status(item) == "pending_review"
    ]
    pending_source_candidates = [
        item
        for item in candidates
        if str(item.get("candidateType") or "") != "candidate_graph" and s._candidate_knowledge_ingestion_status(item) == "pending_source_review"
    ]
    for candidate in pending_source_candidates[:12]:
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        ingestion = metadata.get("knowledgeIngestion") if isinstance(metadata.get("knowledgeIngestion"), dict) else {}
        items.append(
            s._knowledge_ingestion_action_item(
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
            s._knowledge_ingestion_action_item(
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
            s._knowledge_ingestion_action_item(
                "steward_pack_not_submitted",
                "pending",
                "已有 steward pack 候选，但尚未进入团队知识库 proposal 队列。",
                "s.submit_steward_pack_to_knowledge_ingestion",
                "steward_ingestion",
            )
        )
    if knowledge_summary["formalKnowledgeItemCount"] > 0 and candidate_summary["officialGraphSyncedCandidateCount"] == 0:
        items.append(
            s._knowledge_ingestion_action_item(
                "formal_knowledge_without_official_graph",
                "needs_review",
                "已有正式知识项，但科研图谱同步记录尚未完成。",
                "inspect_official_research_graph_metadata",
                "official_sync",
            )
        )
    if not items and candidate_summary["officialGraphSyncedCandidateCount"] > 0:
        items.append(
            s._knowledge_ingestion_action_item(
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
    s = _service()
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
    s = _service()
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
    s = _service()
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
    s = _service()
    candidate_by_id = {str(candidate.get("candidateId") or ""): candidate for candidate in candidates}
    transfer_queue = [
        s._coordination_item(
            candidate_by_id.get(str(transfer.get("candidateId") or "")),
            validation_reports,
            queue="pending_transfer",
            transfer=transfer,
            reason=str(transfer.get("reason") or ""),
        )
        for transfer in requested_transfers
    ]
    rework_queue = [
        s._coordination_item(candidate, validation_reports, queue="needs_rework", reason=s._coordination_candidate_reason(candidate, validation_reports))
        for candidate in candidates
        if s._candidate_needs_rework(candidate, validation_reports)
    ]
    stewardship_queue = [
        s._coordination_item(candidate, validation_reports, queue="stewardship", reason=s._coordination_candidate_reason(candidate, validation_reports))
        for candidate in candidates
        if str(candidate.get("currentState") or "") in {"steward_pack_draft", "steward_pending_knowledge_review", "approved_to_ingest"}
    ]
    blocked_queue = [
        s._coordination_item(candidate, validation_reports, queue="blocked", reason=s._coordination_candidate_reason(candidate, validation_reports))
        for candidate in candidates
        if s._candidate_is_coordination_blocked(candidate, validation_reports)
    ]
    active_queue = [
        s._coordination_item(candidate, validation_reports, queue="active", reason=s._coordination_candidate_reason(candidate, validation_reports))
        for candidate in candidates
        if not s._candidate_needs_rework(candidate, validation_reports)
        and not s._candidate_is_coordination_blocked(candidate, validation_reports)
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
    s = _service()
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
        "byWorkflowNode": s._coordination_count_by(candidates, "currentWorkflowNode"),
        "byState": s._coordination_count_by(candidates, "currentState"),
        "byQualityStatus": s._coordination_count_by(candidates, "qualityStatus"),
    }


def _coordination_action_items(summary: dict[str, Any], queues: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    s = _service()
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
    s = _service()
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
    s = _service()
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
        "reason": s._trim_text(reason, max_length=1000),
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
    item["communicationBrief"] = s._coordination_communication_brief(item)
    return item


def _candidate_is_coordination_blocked(candidate: dict[str, Any], validation_reports: dict[str, dict[str, Any]]) -> bool:
    s = _service()
    state = str(candidate.get("currentState") or "")
    quality_status = str(candidate.get("qualityStatus") or "")
    if "blocked" in state or quality_status in {"broken_links", "source_manifest_invalid"}:
        return True
    validation = validation_reports.get(str(candidate.get("candidateId") or ""))
    return bool(validation and any(issue.get("severity") == "error" for issue in validation.get("issues") or []))


def _coordination_candidate_reason(candidate: dict[str, Any], validation_reports: dict[str, dict[str, Any]]) -> str:
    s = _service()
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
    s = _service()
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
        "recommendedSender": s.DEFAULT_OWNER_AGENT_ID,
        "nextAction": "Use the linked team room or Project Agent Bus to send selected briefs after coordinator review.",
        "summaryLine": (
            f"{len(briefs)} coordination brief(s), "
            f"{summary['pendingTransferCount']} pending transfer(s), "
            f"{summary['reworkCandidateCount']} rework item(s)."
        ),
    }


def _coordination_communication_brief(item: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    queue = str(item.get("queue") or "")
    node = str(item.get("currentWorkflowNode") or item.get("fromNode") or "")
    state = str(item.get("currentState") or "")
    target_agent = s._coordination_target_agent_role(queue, node, state)
    channel = "team_linked_room" if queue == "pending_transfer" else "project_agent_bus"
    subject = s._trim_text(s._coordination_brief_subject(item, target_agent), max_length=180)
    message = s._trim_text(s._coordination_brief_message(item, target_agent), max_length=1200)
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
    s = _service()
    if queue == "pending_transfer":
        return s.DEFAULT_OWNER_AGENT_ID
    if queue == "stewardship" or node == "steward_ingestion" or "steward" in state:
        return "知识库管理员"
    if node in {"knowledge_collection", "source_screening"} or state.startswith("source_"):
        return "资料寻找 Agent"
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
    return s.DEFAULT_OWNER_AGENT_ID


def _coordination_brief_subject(item: dict[str, Any], target_agent: str) -> str:
    s = _service()
    title = str(item.get("title") or item.get("candidateType") or item.get("candidateId") or "workflow item")
    if item.get("transferId"):
        return f"Transfer decision needed: {item.get('fromNode') or '-'} -> {item.get('toNode') or '-'}"
    return f"{target_agent} follow-up needed: {title}"


def _coordination_brief_message(item: dict[str, Any], target_agent: str) -> str:
    s = _service()
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
    s = _service()
    counts: dict[str, int] = {}
    for candidate in candidates:
        key = str(candidate.get(field) or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _knowledge_ingestion_knowledge_bases(knowledge_overview: dict[str, Any]) -> list[dict[str, Any]]:
    s = _service()
    bases: list[dict[str, Any]] = []
    for base in list(knowledge_overview.get("knowledgeBases") or []):
        if not isinstance(base, dict):
            continue
        stats = base.get("stats") if isinstance(base.get("stats"), dict) else {}
        bases.append(
            {
                "knowledgeBaseId": str(base.get("knowledgeBaseId") or ""),
                "scopedKnowledgeBaseId": str(base.get("scopedKnowledgeBaseId") or ""),
                "ownerType": str(base.get("ownerType") or ""),
                "ownerId": str(base.get("ownerId") or ""),
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
    s = _service()
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    ingestion = metadata.get("knowledgeIngestion") if isinstance(metadata.get("knowledgeIngestion"), dict) else {}
    return str(ingestion.get("status") or "")


def _source_manifest_source_ref(candidate: dict[str, Any]) -> dict[str, str]:
    s = _service()
    source_kind = s._trim_text(candidate.get("sourceKind"), max_length=80) or "source_manifest"
    return {
        "type": source_kind,
        "id": s._trim_text(candidate.get("candidateId"), max_length=240),
        "label": s._source_manifest_label(candidate),
    }


def _ready_source_extraction(candidate: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    extraction = metadata.get("sourceExtraction") if isinstance(metadata.get("sourceExtraction"), dict) else {}
    if extraction.get("status") != "extracted":
        raise s.TeamWorkflowOrchestrationError("Source extraction must be completed before paper_note autodraft.")
    page_anchors = extraction.get("pageAnchors")
    if not isinstance(page_anchors, list) or not page_anchors:
        raise s.TeamWorkflowOrchestrationError("Source extraction must include pageAnchors before paper_note autodraft.")
    if not s._trim_text(extraction.get("excerpt"), max_length=24_000):
        raise s.TeamWorkflowOrchestrationError("Source extraction must include excerpt before paper_note autodraft.")
    return extraction


def _ready_content_extraction_evidence_ledger(candidate: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    content_extraction = metadata.get("contentExtraction") if isinstance(metadata.get("contentExtraction"), dict) else {}
    ledger = content_extraction.get("evidenceLedger") if isinstance(content_extraction.get("evidenceLedger"), dict) else {}
    if s._trim_text(ledger.get("status"), max_length=80) != "evidence_ready":
        return {}
    return s._normalize_local_research_evidence_ledger(ledger)


def _source_extraction_evidence_refs(candidate: dict[str, Any], extraction: dict[str, Any], *, anchor_ids: set[str] | None = None) -> list[dict[str, str]]:
    s = _service()
    source_label = s._source_manifest_label(candidate)
    refs: list[dict[str, str]] = []
    for anchor in list(extraction.get("pageAnchors") or [])[:32]:
        if not isinstance(anchor, dict):
            continue
        page = int(anchor.get("page") or 0)
        anchor_id = s._source_extraction_anchor_id(candidate, anchor)
        if anchor_ids is not None and anchor_id not in anchor_ids:
            continue
        label = s._trim_text(anchor.get("label"), max_length=120) or (f"p. {page}" if page else "page anchor")
        if anchor_id or label:
            refs.append(
                {
                    "type": "pdf_page",
                    "id": anchor_id,
                    "label": f"{source_label} {label}".strip(),
                }
            )
    return refs


def _merge_local_research_refs(*groups: list[dict[str, str]], max_items: int) -> list[dict[str, str]]:
    s = _service()
    merged: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for group in groups:
        for ref in group:
            if not isinstance(ref, dict):
                continue
            normalized = {
                "type": s._trim_text(ref.get("type"), max_length=80),
                "id": s._trim_text(ref.get("id"), max_length=240),
                "label": s._trim_text(ref.get("label"), max_length=240),
            }
            key = (normalized["type"], normalized["id"], normalized["label"])
            if key in seen or not any(key):
                continue
            seen.add(key)
            merged.append(normalized)
            if len(merged) >= max_items:
                return merged
    return merged


def _build_paper_note_chunks(
    candidate: dict[str, Any],
    extraction: dict[str, Any],
    *,
    max_pages_per_chunk: int,
    max_chars_per_chunk: int,
) -> list[dict[str, Any]]:
    s = _service()
    anchors = [
        item
        for item in list(extraction.get("pageAnchors") or [])
        if isinstance(item, dict) and s._trim_text(item.get("text"), max_length=max_chars_per_chunk)
    ]
    anchors = sorted(anchors, key=lambda item: int(item.get("page") or 0))
    chunks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_chars = 0
    for anchor in anchors:
        text_chars = len(s._trim_text(anchor.get("text"), max_length=max_chars_per_chunk))
        if current and (len(current) >= max_pages_per_chunk or current_chars + text_chars > max_chars_per_chunk):
            chunks.append(current)
            current = []
            current_chars = 0
            if len(chunks) >= s.PAPER_NOTE_CHUNK_MAX_CHUNKS:
                break
        current.append(anchor)
        current_chars += text_chars
    if current and len(chunks) < s.PAPER_NOTE_CHUNK_MAX_CHUNKS:
        chunks.append(current)

    source_token = s._safe_token(candidate.get("candidateId"), default="source", max_length=48)
    planned_chunks: list[dict[str, Any]] = []
    for index, chunk_anchors in enumerate(chunks, start=1):
        pages = [int(anchor.get("page") or 0) for anchor in chunk_anchors if int(anchor.get("page") or 0) > 0]
        page_scope = s._page_scope_from_anchors(chunk_anchors)
        anchor_ids = [s._source_extraction_anchor_id(candidate, anchor) for anchor in chunk_anchors]
        excerpt = s._excerpt_from_page_anchors(chunk_anchors, max_chars=min(max_chars_per_chunk, 2000))
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
                "evidenceRefs": s._source_extraction_evidence_refs(candidate, {"pageAnchors": chunk_anchors}),
                "excerptChars": sum(len(s._trim_text(anchor.get("text"), max_length=max_chars_per_chunk)) for anchor in chunk_anchors),
                "excerptPreview": s._trim_text(excerpt, max_length=700),
                "paperNoteCandidateId": "",
                "taskId": "",
                "updatedAt": "",
            }
        )
    return planned_chunks


def _paper_note_chunk_by_id(candidate: dict[str, Any], chunk_id: str) -> dict[str, Any] | None:
    s = _service()
    plan = s._candidate_paper_note_chunk_plan(candidate)
    if plan is None:
        return None
    for chunk in list(plan.get("chunks") or []):
        if isinstance(chunk, dict) and str(chunk.get("chunkId") or "") == chunk_id:
            return chunk
    return None


def _page_anchors_for_paper_note_chunk(candidate: dict[str, Any], extraction: dict[str, Any], chunk: dict[str, Any] | None) -> list[dict[str, Any]]:
    s = _service()
    if not chunk:
        return []
    anchor_ids = set(s._normalize_id_values(chunk.get("anchorIds")))
    return [
        anchor
        for anchor in list(extraction.get("pageAnchors") or [])
        if isinstance(anchor, dict) and (s._source_extraction_anchor_id(candidate, anchor) in anchor_ids)
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
    s = _service()
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
        "status": s._paper_note_chunk_plan_status(chunks),
        "updatedAt": updated_at,
    }
    return next_plan


def _paper_note_chunk_plan_status(chunks: list[dict[str, Any]]) -> str:
    s = _service()
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
    s = _service()
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    extraction = metadata.get("sourceExtraction") if isinstance(metadata.get("sourceExtraction"), dict) else {}
    return extraction.get("status") == "extracted" and isinstance(extraction.get("pageAnchors"), list) and bool(extraction.get("pageAnchors"))


def _candidate_paper_note_chunk_plan(candidate: dict[str, Any]) -> dict[str, Any] | None:
    s = _service()
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    plan = metadata.get("paperNoteChunkPlan") if isinstance(metadata.get("paperNoteChunkPlan"), dict) else None
    return plan


def _paper_note_chunk_plan_summary(candidate: dict[str, Any]) -> dict[str, Any] | None:
    s = _service()
    plan = s._candidate_paper_note_chunk_plan(candidate)
    if plan is None:
        return None
    chunks = [item for item in list(plan.get("chunks") or []) if isinstance(item, dict)]
    drafted_count = sum(1 for item in chunks if str(item.get("status") or "") == "drafted")
    needs_revision_count = sum(1 for item in chunks if str(item.get("status") or "") == "needs_revision")
    return {
        "planId": str(plan.get("planId") or ""),
        "status": s._paper_note_chunk_plan_status(chunks),
        "sourceCandidateId": str(candidate.get("candidateId") or ""),
        "sourceTitle": str(candidate.get("title") or s._source_manifest_label(candidate)),
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
    s = _service()
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
    s = _service()
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    assessment = metadata.get("sourceQualityAssessment") if isinstance(metadata.get("sourceQualityAssessment"), dict) else None
    return assessment


def _source_quality_bucket(candidate: dict[str, Any]) -> str:
    s = _service()
    assessment = s._candidate_source_quality_assessment(candidate)
    decision = str((assessment or {}).get("decision") or "")
    quality_status = str(candidate.get("qualityStatus") or "")
    current_state = str(candidate.get("currentState") or "")
    if assessment is None and quality_status == "pending_screening":
        return "pending"
    if decision == "approved" or quality_status in s.SOURCE_QUALITY_APPROVED_STATUSES or current_state == "source_screened":
        return "approved"
    if decision == "rejected" or quality_status in s.SOURCE_QUALITY_REJECTED_STATUSES or current_state == "rejected":
        return "rejected"
    if decision == "needs_revision" or quality_status in s.SOURCE_QUALITY_NEEDS_REVISION_STATUSES or current_state in {"source_needs_confirmation", "source_needs_quality_revision"}:
        return "needs_revision"
    return "pending"


def _source_quality_scores(candidate: dict[str, Any], payload: dict[str, Any], validation: dict[str, Any]) -> dict[str, int]:
    s = _service()
    defaults = s._default_source_quality_scores(candidate, validation)
    scores = {
        "relevance": s._payload_score(payload, "relevanceScore", defaults["relevance"]),
        "reliability": s._payload_score(payload, "reliabilityScore", defaults["reliability"]),
        "accessibility": s._payload_score(payload, "accessibilityScore", defaults["accessibility"]),
        "extractionReadiness": s._payload_score(payload, "extractionReadinessScore", defaults["extractionReadiness"]),
    }
    scores["overall"] = int(round(sum(scores.values()) / len(scores)))
    return scores


def _default_source_quality_scores(candidate: dict[str, Any], validation: dict[str, Any]) -> dict[str, int]:
    s = _service()
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    source_kind = s._trim_text(candidate.get("sourceKind"), max_length=80).lower()
    source_url = s._trim_text(candidate.get("sourceUrl"), max_length=2000)
    source_path = s._trim_text(candidate.get("sourcePath") or metadata.get("sourcePath") or metadata.get("path"), max_length=2000)
    summary = s._trim_text(candidate.get("summary") or metadata.get("summary"), max_length=4000)
    title = s._trim_text(candidate.get("title"), max_length=240)
    tags = " ".join(s._normalize_text_list(candidate.get("tags"), max_items=24, max_length=80)).lower()
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
    if s._trim_text(candidate.get("sha256") or metadata.get("sha256") or metadata.get("hash"), max_length=128):
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
        "relevance": s._clamp_score(relevance),
        "reliability": s._clamp_score(reliability),
        "accessibility": s._clamp_score(accessibility),
        "extractionReadiness": s._clamp_score(extraction_readiness),
    }


def _default_source_quality_decision(scores: dict[str, int], validation: dict[str, Any]) -> str:
    s = _service()
    if not validation.get("valid"):
        return "needs_revision"
    if scores["overall"] >= 70 and min(scores["relevance"], scores["reliability"], scores["accessibility"]) >= 55:
        return "approved"
    return "needs_revision"


def _source_quality_candidate_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    assessment = s._candidate_source_quality_assessment(candidate) or {}
    scores = assessment.get("scores") if isinstance(assessment.get("scores"), dict) else {}
    return {
        "candidateId": str(candidate.get("candidateId") or ""),
        "title": str(candidate.get("title") or s._source_manifest_label(candidate)),
        "sourceKind": str(candidate.get("sourceKind") or ""),
        "currentState": str(candidate.get("currentState") or ""),
        "qualityStatus": str(candidate.get("qualityStatus") or ""),
        "bucket": s._source_quality_bucket(candidate),
        "decision": str(assessment.get("decision") or ""),
        "overallScore": int(scores.get("overall") or 0),
        "scores": {
            "relevance": int(scores.get("relevance") or 0),
            "reliability": int(scores.get("reliability") or 0),
            "accessibility": int(scores.get("accessibility") or 0),
            "extractionReadiness": int(scores.get("extractionReadiness") or 0),
        },
        "hasReadyExtraction": s._source_candidate_has_ready_extraction(candidate),
        "requiredFixes": s._normalize_text_list(assessment.get("requiredFixes"), max_items=12, max_length=240),
        "riskFlags": s._normalize_text_list(assessment.get("riskFlags"), max_items=12, max_length=120),
        "updatedAt": str(candidate.get("updatedAt") or candidate.get("createdAt") or ""),
        "assessedAt": str(assessment.get("assessedAt") or ""),
    }


def _source_quality_batch_assessment_summary(candidate: dict[str, Any], assessment: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    scores = assessment.get("scores") if isinstance(assessment.get("scores"), dict) else {}
    return {
        "candidateId": str(candidate.get("candidateId") or assessment.get("candidateId") or ""),
        "title": str(candidate.get("title") or assessment.get("sourceLabel") or ""),
        "assessmentId": str(assessment.get("assessmentId") or ""),
        "decision": str(assessment.get("decision") or ""),
        "overallScore": int(scores.get("overall") or 0),
        "requiredFixes": s._normalize_text_list(assessment.get("requiredFixes"), max_items=12, max_length=240),
        "riskFlags": s._normalize_text_list(assessment.get("riskFlags"), max_items=12, max_length=120),
        "currentState": str(candidate.get("currentState") or ""),
        "qualityStatus": str(candidate.get("qualityStatus") or ""),
        "assessedAt": str(assessment.get("assessedAt") or ""),
    }


def _source_quality_action_items(
    source_candidates: list[dict[str, Any]],
    unassessed: list[dict[str, Any]],
    needs_revision: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    s = _service()
    if not source_candidates:
        return [
            {
                "code": "source_quality_no_sources",
                "severity": "blocked",
                "message": "还没有 source_manifest 可供资料提炼和审查。",
                "nextAction": "先启动资料搜索或手工回写 DataRecord 并导入 source_manifest。",
                "candidateId": "",
            }
        ]
    items: list[dict[str, Any]] = [
        {
            "code": "source_quality_pending_assessment",
            "severity": "needs_review",
            "message": f"{item.get('title') or s._source_manifest_label(item)} 等待资料提炼 Agent 审查。",
            "nextAction": "调用 source-quality/assess，给出 approved 或 needs_revision。",
            "candidateId": str(item.get("candidateId") or ""),
        }
        for item in unassessed[:6]
    ]
    for item in needs_revision[:6]:
        assessment = s._candidate_source_quality_assessment(item) or {}
        required_fixes = s._normalize_text_list(assessment.get("requiredFixes"), max_items=3, max_length=160)
        items.append(
            {
                "code": "source_quality_needs_revision",
                "severity": "needs_revision",
                "message": f"{item.get('title') or s._source_manifest_label(item)} 需要补充资料质量信息。",
                "nextAction": "；".join(required_fixes) if required_fixes else "补来源、权限、sha256、摘要、页码锚点或相关性说明后重新评估。",
                "candidateId": str(item.get("candidateId") or ""),
            }
        )
    return items[:12]


def _source_quality_next_actions(decision: str) -> list[str]:
    s = _service()
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
        "将资料退回资料寻找 Agent 补充来源或剔除。",
        "Re-run source-quality/assess after source path, permission, citation, or relevance gaps are fixed.",
    ]


def _resolve_source_path(source_path: str) -> Path:
    s = _service()
    path = Path(source_path)
    if not path.is_absolute():
        path = s._project_root() / path
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise s.SourceExtractionError("missing_file", "Local source file was not found.") from exc
    if not resolved.is_file():
        raise s.SourceExtractionError("missing_file", "Local source path is not a file.")
    if resolved.suffix.lower() != ".pdf":
        raise s.SourceExtractionError("unsupported_source_kind", "Only local PDF extraction is supported in this slice.")
    return resolved


def _sha256_file(path: Path) -> str:
    s = _service()
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise s.SourceExtractionError("read_failed", "Local source file could not be read.") from exc
    return digest.hexdigest()


def _extract_pdf_page_anchors(
    path: Path,
    *,
    page_scope: str,
    max_pages: int,
    max_chars_per_page: int,
) -> list[dict[str, Any]]:
    s = _service()
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception as exc:
        raise s.SourceExtractionError("pdf_extractor_unavailable", "pypdf is not installed, so PDF text extraction is unavailable.") from exc
    try:
        reader = PdfReader(str(path))
        pages = list(reader.pages)
    except Exception as exc:
        raise s.SourceExtractionError("pdf_open_failed", "PDF could not be opened for text extraction.") from exc
    page_numbers = s._page_numbers_from_scope(page_scope, total_pages=len(pages), max_pages=max_pages)
    anchors: list[dict[str, Any]] = []
    source_token = s._safe_token(path.stem, default="pdf", max_length=80)
    for page_number in page_numbers:
        try:
            text = pages[page_number - 1].extract_text() or ""
        except Exception:
            text = ""
        normalized_text = s._compact_text(text, max_length=max_chars_per_page)
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


def _page_scope_from_anchors(page_anchors: list[dict[str, Any]]) -> str:
    s = _service()
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
    s = _service()
    chunks: list[str] = []
    for anchor in page_anchors:
        if not isinstance(anchor, dict):
            continue
        page = int(anchor.get("page") or 0)
        text = s._compact_text(anchor.get("text"), max_length=max_chars)
        if page and text:
            chunks.append(f"[p. {page}]\n{text}")
    return s._trim_text("\n\n".join(chunks), max_length=max_chars)


def _normalize_id_values(value: Any) -> list[str]:
    s = _service()
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value[:64]:
        text = s._trim_text(item, max_length=160)
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _validate_paper_note_output(output: dict[str, Any]) -> list[dict[str, str]]:
    s = _service()
    issues: list[dict[str, str]] = []
    key_findings = output.get("keyFindings")
    if not isinstance(key_findings, list) or not key_findings:
        issues.append({"severity": "error", "code": "missing_key_findings", "message": "paper_note requires at least one keyFinding."})
        return issues
    for index, finding in enumerate(key_findings):
        if not isinstance(finding, dict):
            issues.append({"severity": "error", "code": "invalid_key_finding", "message": f"keyFindings[{index}] must be an object."})
            continue
        if not s._has_value(finding.get("finding") or finding.get("claim") or finding.get("summary")):
            issues.append({"severity": "error", "code": "missing_key_finding_text", "message": f"keyFindings[{index}] requires finding text."})
        if not s._has_citation_anchor(finding):
            issues.append({"severity": "error", "code": "missing_key_finding_citation", "message": f"keyFindings[{index}] requires sourceRef and page/citation anchor."})
    citations = output.get("citations")
    if not isinstance(citations, list) or not citations:
        issues.append({"severity": "error", "code": "missing_citations", "message": "paper_note requires citations."})
    elif not any(s._has_citation_anchor(item) for item in citations if isinstance(item, dict)):
        issues.append({"severity": "error", "code": "missing_citation_anchor", "message": "At least one citation must include sourceRef and page/citation anchor."})
    return issues


def _validate_paper_note_candidate(candidate: dict[str, Any]) -> list[dict[str, str]]:
    s = _service()
    issues: list[dict[str, str]] = []
    if not s._normalize_ref_list(candidate.get("sourceRefs"), max_items=32):
        issues.append({"severity": "error", "code": "missing_source_refs", "message": "paper_note must keep sourceRefs."})
    if not s._normalize_ref_list(candidate.get("evidenceRefs"), max_items=32):
        issues.append({"severity": "warning", "code": "missing_evidence_refs", "message": "paper_note should include evidenceRefs before mechanism extraction."})
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    output = metadata.get("output") if isinstance(metadata.get("output"), dict) else {}
    if output:
        issues.extend(s._validate_paper_note_output(output))
    return issues


def _validate_neuro_mechanism_output(output: dict[str, Any]) -> list[dict[str, str]]:
    s = _service()
    issues: list[dict[str, str]] = []
    paper_note_ids = output.get("paperNoteIds")
    if not isinstance(paper_note_ids, list) or not any(s._has_value(item) for item in paper_note_ids):
        issues.append({"severity": "error", "code": "missing_paper_note_ids", "message": "neuro_mechanism requires at least one paperNoteId."})
    if not s._has_value(output.get("description")):
        issues.append({"severity": "error", "code": "missing_mechanism_description", "message": "neuro_mechanism requires description."})
    if not s._has_value(output.get("experimentalPhenomena")):
        issues.append({"severity": "error", "code": "missing_experimental_phenomena", "message": "neuro_mechanism requires experimentalPhenomena."})
    if not s._has_neuro_term_or_unknown(output.get("brainSystems")):
        issues.append({"severity": "error", "code": "missing_brain_systems", "message": "neuro_mechanism requires brainSystems or explicit unknown."})
    if not s._has_neuro_term_or_unknown(output.get("cognitiveFunctions")):
        issues.append({"severity": "error", "code": "missing_cognitive_functions", "message": "neuro_mechanism requires cognitiveFunctions or explicit unknown."})
    if s._requires_terminology_uncertain(output) and not s._risk_flags_include(output, "terminology_uncertain"):
        issues.append({"severity": "error", "code": "terminology_uncertain_not_flagged", "message": "Unknown or uncertain neuro terms must include terminology_uncertain."})
    confidence = output.get("confidence")
    if not isinstance(confidence, (int, float)) or confidence < 0 or confidence > 1:
        issues.append({"severity": "error", "code": "invalid_confidence", "message": "confidence must be a number between 0 and 1."})
    return issues


def _validate_mechanism_mapping_output(output: dict[str, Any]) -> list[dict[str, str]]:
    s = _service()
    issues: list[dict[str, str]] = []
    mechanism_ids = output.get("neuroMechanismIds")
    if not isinstance(mechanism_ids, list) or not any(s._has_value(item) for item in mechanism_ids):
        issues.append({"severity": "error", "code": "missing_neuro_mechanism_ids", "message": "mechanism_mapping requires at least one neuroMechanismId."})
    if not s._has_value(output.get("computationalAbstraction")):
        issues.append({"severity": "error", "code": "missing_computational_abstraction", "message": "mechanism_mapping requires computationalAbstraction."})
    if not s._has_value(output.get("factLayer")):
        issues.append({"severity": "error", "code": "missing_fact_layer", "message": "mechanism_mapping must separate paper facts in factLayer."})
    if not s._has_value(output.get("inferenceLayer")):
        issues.append({"severity": "error", "code": "missing_inference_layer", "message": "mechanism_mapping must separate project inference in inferenceLayer."})
    if "overAnalogyRisk" not in output:
        issues.append({"severity": "error", "code": "missing_over_analogy_risk", "message": "mechanism_mapping requires overAnalogyRisk."})
    elif s._is_over_analogy_risky(output.get("overAnalogyRisk")) and not s._risk_flags_include(output, "over_analogy_risk"):
        issues.append({"severity": "error", "code": "over_analogy_risk_not_flagged", "message": "High or unresolved analogy risk must include over_analogy_risk."})
    if not s._has_value(output.get("engineeringImplication")):
        issues.append({"severity": "error", "code": "missing_engineering_implication", "message": "mechanism_mapping requires engineeringImplication."})
    return issues


def _validate_algorithm_hypothesis_output(output: dict[str, Any]) -> list[dict[str, str]]:
    s = _service()
    issues: list[dict[str, str]] = []
    mapping_ids = output.get("mechanismMappingIds")
    mechanism_ids = output.get("neuroMechanismIds")
    if not s._has_any_list_value(mapping_ids) and not s._has_any_list_value(mechanism_ids):
        issues.append({"severity": "error", "code": "missing_upstream_mechanism_refs", "message": "algorithm_hypothesis requires mechanismMappingIds or neuroMechanismIds."})
    if not s._has_value(output.get("hypothesis")):
        issues.append({"severity": "error", "code": "missing_hypothesis", "message": "algorithm_hypothesis requires hypothesis."})
    for field, code in (
        ("baseline", "missing_baseline"),
        ("expectedBenefit", "missing_expected_benefit"),
        ("expectedComputeCost", "missing_expected_compute_cost"),
    ):
        if not s._has_value(output.get(field)):
            issues.append({"severity": "error", "code": code, "message": f"algorithm_hypothesis requires {field}."})
    experiment_plan = output.get("experimentPlan")
    if not isinstance(experiment_plan, dict) or not experiment_plan:
        issues.append({"severity": "error", "code": "missing_experiment_plan", "message": "algorithm_hypothesis requires experimentPlan."})
    else:
        for field in ("dataset", "metric", "baseline", "smokePlan"):
            if not s._has_value(experiment_plan.get(field)):
                issues.append({"severity": "error", "code": "incomplete_experiment_plan", "message": f"experimentPlan requires {field}."})
    return issues


def _validate_review_prefilter_output(output: dict[str, Any]) -> list[dict[str, str]]:
    s = _service()
    issues: list[dict[str, str]] = []
    if not s._has_any_list_value(output.get("candidateIds")):
        issues.append({"severity": "error", "code": "missing_review_candidate_ids", "message": "review_prefilter requires candidateIds."})
    checklist = output.get("checklist")
    if not isinstance(checklist, list) or not checklist:
        issues.append({"severity": "error", "code": "missing_review_checklist", "message": "review_prefilter requires checklist."})
    else:
        for index, item in enumerate(checklist):
            if not isinstance(item, dict):
                issues.append({"severity": "error", "code": "invalid_review_checklist_item", "message": f"checklist[{index}] must be an object."})
                continue
            if not s._has_value(item.get("item") or item.get("name") or item.get("check")):
                issues.append({"severity": "error", "code": "missing_review_checklist_item", "message": f"checklist[{index}] requires item text."})
            if not s._has_value(item.get("status") or item.get("result")):
                issues.append({"severity": "error", "code": "missing_review_checklist_status", "message": f"checklist[{index}] requires status/result."})
    if not s._has_value(output.get("comments")):
        issues.append({"severity": "error", "code": "missing_review_comments", "message": "review_prefilter requires comments."})
    required_changes = output.get("requiredChanges")
    if not isinstance(required_changes, list):
        issues.append({"severity": "error", "code": "invalid_required_changes", "message": "review_prefilter requiredChanges must be a list."})
    needs_decision = output.get("needsDecision")
    if not isinstance(needs_decision, bool):
        issues.append({"severity": "error", "code": "invalid_needs_decision", "message": "review_prefilter needsDecision must be boolean."})
    return issues


def _validate_review_record_candidate(candidate: dict[str, Any]) -> list[dict[str, str]]:
    s = _service()
    issues: list[dict[str, str]] = []
    if not s._normalize_ref_list(candidate.get("sourceRefs"), max_items=32):
        issues.append({"severity": "error", "code": "missing_source_refs", "message": "review_record must keep sourceRefs."})
    if not s._normalize_ref_list(candidate.get("evidenceRefs"), max_items=32):
        issues.append({"severity": "error", "code": "missing_evidence_refs", "message": "review_record requires evidenceRefs."})
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    output = metadata.get("output") if isinstance(metadata.get("output"), dict) else {}
    if output:
        if "decision" in output:
            issues.append({"severity": "error", "code": "final_decision_not_allowed", "message": "review_record prefilter must not include final decision."})
        task_type = str(metadata.get("taskType") or "")
        if task_type == "steward_pack_draft":
            issues.extend(s._validate_steward_pack_output(output))
        else:
            issues.extend(s._validate_review_prefilter_output(output))
    return issues


def _validate_steward_pack_output(output: dict[str, Any]) -> list[dict[str, str]]:
    s = _service()
    issues: list[dict[str, str]] = []
    if not s._has_any_list_value(output.get("candidateIds")):
        issues.append({"severity": "error", "code": "missing_steward_candidate_ids", "message": "steward_pack requires candidateIds."})
    for field, code in (
        ("targetDomain", "missing_target_domain"),
        ("sourceTrace", "missing_source_trace"),
        ("riskSummary", "missing_risk_summary"),
        ("proposalPayload", "missing_proposal_payload"),
        ("ratingSuggestion", "missing_rating_suggestion"),
    ):
        if not s._has_value(output.get(field)):
            issues.append({"severity": "error", "code": code, "message": f"steward_pack requires {field}."})
    if output.get("approvalRequired") is not True:
        issues.append({"severity": "error", "code": "approval_required_not_true", "message": "steward_pack must set approvalRequired=true."})
    if s._has_value(output.get("officialSync")) or output.get("applyNow") is True or output.get("writeOfficialGraph") is True:
        issues.append({"severity": "error", "code": "official_write_not_allowed", "message": "steward_pack draft must not request immediate official write or graph sync."})
    return issues


def _steward_pack_ingestion_payload(
    team_id: str,
    candidate: dict[str, Any],
    output: dict[str, Any],
    *,
    proposed_by_agent_id: str,
) -> dict[str, Any]:
    s = _service()
    proposal_payload = output.get("proposalPayload") if isinstance(output.get("proposalPayload"), dict) else {}
    source_trace = output.get("sourceTrace") if isinstance(output.get("sourceTrace"), dict) else {}
    source_ref = {
        "agentId": proposed_by_agent_id,
        "teamId": team_id,
        "candidateId": str(candidate.get("candidateId") or ""),
        "workflowId": str(candidate.get("workflowId") or ""),
        "taskType": "steward_pack_draft",
        "targetDomain": s._trim_text(output.get("targetDomain"), max_length=160),
        "candidateIds": s._normalize_text_list(output.get("candidateIds"), max_items=32, max_length=160),
        "sourceTrace": s._normalize_metadata(source_trace),
    }
    title = (
        s._trim_text(proposal_payload.get("title"), max_length=240)
        or s._trim_text(candidate.get("title"), max_length=240)
        or "Challenge Cup steward ingestion proposal"
    )
    summary = s._trim_text(proposal_payload.get("summary") or output.get("riskSummary") or candidate.get("summary"), max_length=4000)
    content_payload = {
        "proposalPayload": s._normalize_metadata(proposal_payload),
        "ratingSuggestion": s._normalize_metadata(output.get("ratingSuggestion") if isinstance(output.get("ratingSuggestion"), dict) else {}),
        "riskSummary": s._trim_text(output.get("riskSummary"), max_length=4000),
        "claims": output.get("claims") if isinstance(output.get("claims"), list) else [],
        "uncertainty": output.get("uncertainty") if isinstance(output.get("uncertainty"), list) else [],
        "sourceTrace": s._normalize_metadata(source_trace),
        "approvalRequired": True,
        "officialBoundary": {
            "writesOfficialKnowledge": False,
            "writesOfficialRag": False,
            "writesOfficialGraph": False,
        },
    }
    content = json.dumps(content_payload, ensure_ascii=False, indent=2, sort_keys=True)
    tags = ["challenge-cup", "steward-pack", "pending-review", s._trim_text(output.get("targetDomain"), max_length=80)]
    return {
        "sourceRef": source_ref,
        "evidenceRange": {
            "sourceRefs": s._normalize_ref_list(output.get("sourceRefs"), max_items=32),
            "evidenceRefs": s._normalize_ref_list(output.get("evidenceRefs"), max_items=32),
        },
        "sourceTitle": f"Steward pack source: {title}",
        "sourceSummary": summary,
        "excerpt": s._trim_text(output.get("riskSummary"), max_length=12000) or summary or title,
        "proposalTitle": title,
        "proposalSummary": summary,
        "proposalContent": content,
        "tags": [item for item in s._normalize_text_list(tags, max_items=8, max_length=80) if item],
    }


def _steward_pack_rating_suggestion_payload(
    output: dict[str, Any],
    proposal: Any,
    proposed_by_agent_id: str,
) -> dict[str, Any] | None:
    s = _service()
    if not isinstance(proposal, dict):
        return None
    proposal_id = s._trim_text(proposal.get("proposalId"), max_length=160)
    if not proposal_id:
        return None
    rating = output.get("ratingSuggestion") if isinstance(output.get("ratingSuggestion"), dict) else {}
    if not rating:
        return None
    importance_level = s._normalize_rating_enum(
        rating.get("importanceLevel") or rating.get("importance") or rating.get("rating"),
        {"low", "medium", "high", "critical"},
        default="medium",
    )
    stability = s._normalize_rating_enum(rating.get("stability"), {"temporary", "evolving", "stable", "deprecated"}, default="evolving")
    review_priority = s._normalize_rating_enum(
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
    reason = s._trim_text(rating.get("reason") or rating.get("markingReason") or output.get("riskSummary"), max_length=2000)
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
    s = _service()
    normalized_source_id = s._trim_text(source_suggestion_id, max_length=160)
    normalized_item_id = s._trim_text(knowledge_item_id, max_length=160)
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
        suggestions_response = s.team_knowledge_service.list_rating_suggestions(
            knowledge_base_id,
            agent_id=reviewed_by_agent_id,
        )
    except (s.team_knowledge_service.TeamKnowledgeError, s.team_knowledge_service.TeamKnowledgeNotFoundError) as exc:
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
        source_review = s.team_knowledge_service.review_rating_suggestion(
            knowledge_base_id,
            normalized_source_id,
            status="applied",
            reviewed_by_agent_id=reviewed_by_agent_id,
            resolution_note=resolution_note or "Migrated from steward pack proposal rating suggestion.",
        )
        target_suggestion = s.team_knowledge_service.create_rating_suggestion(
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
    except (TypeError, ValueError, s.team_knowledge_service.TeamKnowledgeError, s.team_knowledge_service.TeamKnowledgeNotFoundError) as exc:
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
    s = _service()
    normalized_item_ids = s._normalize_id_values(knowledge_item_ids)
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
    candidate_ids = s._normalize_id_values(output.get("candidateIds"))
    source_ids = s._normalize_id_values(source_trace.get("sourceIds") or source_trace.get("paperIds"))
    paper_note_ids = s._normalize_id_values(source_trace.get("paperNoteIds"))
    neuro_mechanism_ids = s._normalize_id_values(source_trace.get("neuroMechanismIds"))
    mechanism_mapping_ids = s._normalize_id_values(source_trace.get("mechanismMappingIds"))
    algorithm_hypothesis_ids = s._normalize_id_values(source_trace.get("algorithmHypothesisIds") or output.get("algorithmHypothesisIds"))
    review_record_ids = s._normalize_id_values(source_trace.get("reviewRecordIds"))
    candidate_graph_id = s._trim_text(source_trace.get("candidateGraphId"), max_length=160)
    if not algorithm_hypothesis_ids and candidate_ids:
        algorithm_hypothesis_ids = [item for item in candidate_ids if "hypothesis" in item.lower()]
    edges: list[dict[str, str]] = []
    for source_id in source_ids:
        edges.append(s._official_research_graph_edge(source_id, primary_item_id, "supports", source_type="source", target_type="knowledge_item"))
    for paper_note_id in paper_note_ids:
        edges.append(s._official_research_graph_edge(paper_note_id, primary_item_id, "supports", source_type="paper_note", target_type="knowledge_item"))
    for mechanism_id in neuro_mechanism_ids:
        edges.append(s._official_research_graph_edge(mechanism_id, primary_item_id, "supports", source_type="neuro_mechanism", target_type="knowledge_item"))
    for mapping_id in mechanism_mapping_ids:
        edges.append(s._official_research_graph_edge(mapping_id, primary_item_id, "maps_to", source_type="mechanism_mapping", target_type="knowledge_item"))
    for hypothesis_id in algorithm_hypothesis_ids:
        edges.append(s._official_research_graph_edge(hypothesis_id, primary_item_id, "inspires", source_type="algorithm_hypothesis", target_type="knowledge_item"))
    for candidate_id in candidate_ids:
        edges.append(s._official_research_graph_edge(candidate_id, primary_item_id, "approved_for_ingestion", source_type="candidate", target_type="knowledge_item"))
    for review_id in review_record_ids:
        edges.append(s._official_research_graph_edge(review_id, primary_item_id, "approved_for_ingestion", source_type="review_record", target_type="knowledge_item"))
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
        "targetDomain": s._trim_text(output.get("targetDomain"), max_length=160),
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
    s = _service()
    return {
        "sourceId": source_id,
        "sourceType": source_type,
        "targetId": target_id,
        "targetType": target_type,
        "relation": relation,
        "edgeState": "official_synced",
    }


def _normalize_steward_review_decision(value: Any) -> str:
    s = _service()
    normalized = s._trim_text(value, max_length=32).lower().replace("-", "_").replace(" ", "_")
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
        raise s.TeamWorkflowOrchestrationError("Steward ingestion review decision must be approved or rejected.")
    return normalized


def _validate_candidate_graph_candidate(candidate: dict[str, Any]) -> list[dict[str, str]]:
    s = _service()
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


def _normalize_optional_bool(value: Any) -> bool | None:
    s = _service()
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


def _load_transfer_records(team_id: str) -> list[dict[str, Any]]:
    s = _service()
    path = s._transfer_records_path(team_id)
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
    s = _service()
    path = s._transfer_records_path(team_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(transfer, ensure_ascii=False, sort_keys=True) + "\n")


def _write_transfer_records(team_id: str, transfers: list[dict[str, Any]]) -> None:
    s = _service()
    path = s._transfer_records_path(team_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in transfers)
    path.write_text(payload, encoding="utf-8")


def _find_candidate(candidate_store: dict[str, Any], candidate_id: str) -> dict[str, Any] | None:
    s = _service()
    for item in list(candidate_store.get("candidates") or []):
        if isinstance(item, dict) and str(item.get("candidateId") or "") == candidate_id:
            return item
    return None


def _find_transfer(transfers: list[dict[str, Any]], transfer_id: str) -> dict[str, Any] | None:
    s = _service()
    for item in transfers:
        if str(item.get("transferId") or "") == transfer_id:
            return item
    return None


def _normalize_local_research_task_type(value: Any) -> str:
    s = _service()
    normalized = s._trim_text(value, max_length=80)
    if normalized not in s.LOCAL_RESEARCH_TASKS:
        raise s.TeamWorkflowOrchestrationError("Local research model task type is invalid.")
    return normalized


def _source_collection_team_agent_ids(team: dict[str, Any], roles: list[str], payload: dict[str, Any]) -> dict[str, str]:
    s = _service()
    explicit_agent_ids = payload.get("agentIds") if isinstance(payload.get("agentIds"), dict) else {}
    mapped: dict[str, str] = {}
    for role in roles:
        explicit = s._trim_text(explicit_agent_ids.get(role), max_length=160)
        if explicit:
            mapped[role] = explicit
    canvas = team.get("canvas") if isinstance(team.get("canvas"), dict) else {}
    nodes = canvas.get("nodes") if isinstance(canvas.get("nodes"), list) else []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        role = s._normalize_source_collection_agent_role(node.get("role"))
        agent_id = s._trim_text(node.get("agentId"), max_length=160)
        if role in roles and agent_id and role not in mapped:
            mapped[role] = agent_id
    return mapped


def _source_collection_prompt_cache_partition(team_id: str, role: str, *, model_id: str) -> str:
    s = _service()
    normalized_role = s._SAFE_ID_FRAGMENT.sub("-", str(role or "agent").strip().lower()).strip("-") or "agent"
    raw = "|".join(
        [
            s.SOURCE_COLLECTION_PROMPT_CACHE_SCOPE,
            str(team_id or "").strip(),
            str(role or "").strip(),
            str(model_id or "").strip(),
        ]
    )
    digest = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:12]
    return s.developer_sandbox.sandbox_prompt_cache_partition(
        f"research-team-{normalized_role}-{digest}",
        surface="team",
        project_root=s.PROJECT_ROOT,
    )


def _source_collection_candidate_trace_run_id(candidate: dict[str, Any]) -> str:
    s = _service()
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    imported_from = metadata.get("importedFromDataRecord") if isinstance(metadata.get("importedFromDataRecord"), dict) else {}
    return (
        s._trim_text(imported_from.get("runId"), max_length=160)
        or s._trim_text(metadata.get("sourceCollectionRunId"), max_length=160)
    )


def _source_collection_candidate_graph_matches_run(candidate: dict[str, Any], source_candidate_ids: set[str]) -> bool:
    s = _service()
    if not source_candidate_ids:
        return False
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    generated_ids = set(s._normalize_id_values(metadata.get("generatedFromCandidateIds")))
    ingestion = metadata.get("knowledgeCollectionIngestion") if isinstance(metadata.get("knowledgeCollectionIngestion"), dict) else {}
    input_ids = set(s._normalize_id_values(ingestion.get("inputCandidateIds")))
    graph = metadata.get("graph") if isinstance(metadata.get("graph"), dict) else {}
    graph_node_ids = {
        s._trim_text(item.get("candidateId"), max_length=160)
        for item in list(graph.get("nodes") or [])
        if isinstance(item, dict) and s._trim_text(item.get("candidateId"), max_length=160)
    }
    return bool((generated_ids | input_ids | graph_node_ids) & source_candidate_ids)


def _source_collection_steward_candidate_matches_run(candidate: dict[str, Any], source_candidate_ids: set[str]) -> bool:
    s = _service()
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
    candidate_ids = set(s._normalize_id_values(output.get("candidateIds")))
    source_trace = output.get("sourceTrace") if isinstance(output.get("sourceTrace"), dict) else {}
    candidate_ids.update(s._normalize_id_values(source_trace.get("sourceCandidateIds") or source_trace.get("sourceIds")))
    return bool(candidate_ids & source_candidate_ids)


def _stage_coordination_contract(team: dict[str, Any], stage_round: dict[str, Any], *, trigger: str = "manual") -> dict[str, Any]:
    s = _service()
    linked_room_id = s._trim_text(team.get("linkedChatRoomId"), max_length=160)
    stage_type = str(stage_round.get("stageType") or "")
    topic = str(stage_round.get("topic") or "")
    linked_room = s.chat_room_service.get_chat_room_compact(linked_room_id) if linked_room_id else None
    room_mode = s._trim_text((linked_room or {}).get("mode"), max_length=80) or "round_robin"
    normalized_trigger = s._trim_text(trigger, max_length=80) or "manual"
    memory_context = stage_round.get("memoryContext") if isinstance(stage_round.get("memoryContext"), dict) else {}
    return {
        "contractKind": "team_coordination_round_contract",
        "linkedChatRoomId": linked_room_id,
        "stageRoundId": stage_round.get("stageRoundId", ""),
        "stageType": stage_type,
        "topic": f"{s._stage_label(stage_type)}：{topic}",
        "purpose": s._stage_coordination_purpose(stage_type),
        "mode": room_mode,
        "autoStarted": False,
        "trigger": normalized_trigger,
        "expectedAction": "Start a lightweight team coordination round only after an explicit user action.",
        "config": {
            "source": f"research_stage_{normalized_trigger}",
            "teamId": team.get("teamId", ""),
            "stageRoundId": stage_round.get("stageRoundId", ""),
            "sourceRunIds": list(stage_round.get("sourceRunIds") or []),
            "memoryContextId": str(memory_context.get("contextId") or ""),
            "memoryContext": s.deepcopy(memory_context),
        },
    }


def _stage_coordination_manual_pending_result(contract: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    return {
        "started": False,
        "roomId": s._trim_text(contract.get("linkedChatRoomId"), max_length=160),
        "reason": "Team coordination is available but was not auto-started. Use the explicit coordination action when discussion is needed.",
        "errorType": "",
        "skipped": True,
        "skipReason": "manual_only",
    }


def _try_start_stage_coordination_round(team: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    linked_room_id = s._trim_text(contract.get("linkedChatRoomId"), max_length=160)
    if not linked_room_id:
        return {
            "started": False,
            "reason": "Team has no linked chat room.",
            "errorType": "missing_linked_chat_room",
        }
    try:
        round_payload = s.chat_room_service.start_chat_room_round(
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
            "reason": s._trim_text(str(exc), max_length=500),
            "errorType": type(exc).__name__,
        }
    return {
        "started": True,
        "roomId": str(round_payload.get("roomId") or linked_room_id),
        "roundId": str(round_payload.get("roundId") or round_payload.get("activeRoundId") or ""),
        "status": str(round_payload.get("status") or ""),
    }


def _research_memory_knowledge_results(
    team_id: str,
    *,
    research_question: str,
    actor_agent_id: str,
) -> tuple[list[dict[str, Any]], str]:
    s = _service()
    normalized_actor_id = s._trim_text(actor_agent_id, max_length=160)
    if not normalized_actor_id.startswith("agent-"):
        try:
            normalized_actor_id = s._source_collection_owner_agent_id(s.team_service.get_team(team_id), {})
        except Exception:
            normalized_actor_id = ""
    retrieval_status = "completed"
    knowledge_results: list[dict[str, Any]] = []
    try:
        knowledge_payload = s.team_knowledge_service.search_knowledge_items(
            agent_id=normalized_actor_id,
            team_id=team_id,
            query=s._trim_text(research_question, max_length=1200),
            search_mode="bm25",
            limit=6,
        )
        knowledge_results = [
            item
            for item in list(knowledge_payload.get("results") or [])
            if isinstance(item, dict)
        ]
    except Exception:
        retrieval_status = "unavailable"
    return knowledge_results, retrieval_status


def _stage_coordination_purpose(stage_type: str) -> str:
    s = _service()
    if stage_type == "knowledge_collection":
        return "围绕资料搜索范围、query seeds、角色分工和结果回写合同进行团队协调。"
    if stage_type == "experiment":
        return "围绕实验目标、baseline、指标和风险控制进行团队规划，不自动执行实验。"
    return "围绕实验反馈、缺口、改动范围和下一轮目标进行团队规划，不自动进入下一轮。"


def _load_official_model_evidence_store(team_id: str) -> dict[str, Any]:
    s = _service()
    path = s._official_model_evidence_store_path(team_id)
    store = s._read_json(path)
    if store.get("storeKind") == "official_model_evidence_store" and isinstance(store.get("evidence"), list):
        return store
    now = s.utc_now_iso()
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "storeKind": "official_model_evidence_store",
        "teamId": team_id,
        "evidence": [],
        "createdAt": now,
        "updatedAt": now,
    }


def _official_model_evidence_entries(store: dict[str, Any]) -> list[dict[str, Any]]:
    s = _service()
    return [item for item in list(store.get("evidence") or []) if isinstance(item, dict)]


def _build_official_model_evidence_record(
    team_id: str,
    workflow: dict[str, Any],
    candidate_store: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    s = _service()
    candidate_id = s._trim_text(payload.get("candidateId"), max_length=128)
    candidate = s._find_candidate_by_id(candidate_store, candidate_id) if candidate_id else None
    candidate_metadata = candidate.get("metadata") if isinstance((candidate or {}).get("metadata"), dict) else {}
    candidate_output = candidate_metadata.get("output") if isinstance(candidate_metadata.get("output"), dict) else {}
    task_type = s._normalize_official_model_task_type(payload.get("taskType") or candidate_metadata.get("taskType"))
    workflow_node = s._trim_text(payload.get("workflowNode"), max_length=120)
    if not workflow_node and task_type:
        workflow_node = str((s.LOCAL_RESEARCH_TASKS.get(task_type) or {}).get("workflowNode") or "")
    if not workflow_node and candidate:
        workflow_node = s._trim_text(candidate.get("currentWorkflowNode"), max_length=120)
    if not task_type and workflow_node:
        task_type = s._official_model_task_type_from_node(workflow_node)
    if not (task_type or workflow_node or candidate_id):
        raise s.TeamWorkflowOrchestrationError("Model evidence requires taskType, workflowNode, or candidateId.")

    model_id = s._trim_text(payload.get("modelId") or candidate_metadata.get("modelId"), max_length=160) or s.LOCAL_RESEARCH_MODEL_ID
    now = s.utc_now_iso()
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "evidenceId": s._new_record_id("model-evidence"),
        "teamId": team_id,
        "workflowId": workflow["workflowId"],
        "workflowKind": workflow["workflowKind"],
        "taskType": task_type,
        "workflowNode": workflow_node or str((s.LOCAL_RESEARCH_TASKS.get(task_type) or {}).get("workflowNode") or ""),
        "candidateId": candidate_id,
        "stageRoundId": s._trim_text(payload.get("stageRoundId"), max_length=128),
        "sourceRunId": s._trim_text(payload.get("sourceRunId"), max_length=128),
        "taskId": s._trim_text(payload.get("taskId"), max_length=128),
        "modelProvider": s._infer_official_model_provider(payload.get("modelProvider") or payload.get("provider"), model_id),
        "modelId": model_id,
        "modelName": s._trim_text(payload.get("modelName") or s.LOCAL_RESEARCH_MODEL_NAME, max_length=240),
        "modelProfileId": s._trim_text(payload.get("modelProfileId"), max_length=160),
        "evidenceKind": s._normalize_official_model_evidence_kind(payload.get("evidenceKind")),
        "artifactPath": s._trim_text(payload.get("artifactPath"), max_length=500),
        "screenshotPath": s._trim_text(payload.get("screenshotPath"), max_length=500),
        "logRef": s._trim_text(payload.get("logRef"), max_length=500),
        "promptSummary": s._trim_text(payload.get("promptSummary"), max_length=1200),
        "outputSummary": s._trim_text(payload.get("outputSummary") or candidate_output.get("nextAction") or (candidate or {}).get("summary"), max_length=1200),
        "sourceRefs": s._normalize_ref_list(payload.get("sourceRefs") or (candidate or {}).get("sourceRefs"), max_items=32),
        "evidenceRefs": s._normalize_ref_list(payload.get("evidenceRefs") or (candidate or {}).get("evidenceRefs"), max_items=32),
        "status": s._trim_text(payload.get("status"), max_length=80) or "registered",
        "recordedByAgent": s._trim_text(payload.get("recordedByAgent") or payload.get("createdByAgent"), max_length=160),
        "metadata": s._normalize_metadata(payload.get("metadata")),
        "officialBoundary": s._official_model_evidence_boundary(),
        "createdAt": now,
        "updatedAt": now,
    }


def _official_model_evidence_from_candidates(candidate_store: dict[str, Any], workflow: dict[str, Any]) -> list[dict[str, Any]]:
    s = _service()
    evidence: list[dict[str, Any]] = []
    for candidate in [item for item in list(candidate_store.get("candidates") or []) if isinstance(item, dict)]:
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        task_type = s._normalize_official_model_task_type(metadata.get("taskType"))
        model_id = s._trim_text(metadata.get("modelId"), max_length=160)
        team_id = str(candidate.get("teamId") or "")
        if not task_type or not model_id or not team_id:
            continue
        evidence.append(
            {
                "schemaVersion": s.SCHEMA_VERSION,
                "evidenceId": f"candidate-output:{candidate.get('candidateId')}",
                "teamId": team_id,
                "workflowId": workflow["workflowId"],
                "workflowKind": workflow["workflowKind"],
                "taskType": task_type,
                "workflowNode": str(candidate.get("currentWorkflowNode") or (s.LOCAL_RESEARCH_TASKS.get(task_type) or {}).get("workflowNode") or ""),
                "candidateId": str(candidate.get("candidateId") or ""),
                "stageRoundId": "",
                "sourceRunId": "",
                "taskId": "",
                "modelProvider": s._infer_official_model_provider(metadata.get("modelProvider"), model_id),
                "modelId": model_id,
                "modelName": s.LOCAL_RESEARCH_MODEL_NAME,
                "modelProfileId": "",
                "evidenceKind": "candidate_output",
                "artifactPath": "",
                "screenshotPath": "",
                "logRef": s._relative_path(s._candidate_store_path(team_id)),
                "promptSummary": "",
                "outputSummary": s._trim_text(candidate.get("summary"), max_length=1200),
                "sourceRefs": s._normalize_ref_list(candidate.get("sourceRefs"), max_items=32),
                "evidenceRefs": s._normalize_ref_list(candidate.get("evidenceRefs"), max_items=32),
                "status": "derived_from_candidate_store",
                "recordedByAgent": str(candidate.get("createdByAgent") or ""),
                "metadata": {"derived": True},
                "officialBoundary": s._official_model_evidence_boundary(),
                "createdAt": str(candidate.get("createdAt") or ""),
                "updatedAt": str(candidate.get("updatedAt") or candidate.get("createdAt") or ""),
            }
        )
    return evidence


def _dedupe_official_model_evidence(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    s = _service()
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
    s = _service()
    coverage: list[dict[str, Any]] = []
    for spec in s.OFFICIAL_MODEL_EVIDENCE_REQUIRED_TASKS:
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
                "providers": s._count_by_field(matches, "modelProvider"),
                "latestEvidenceId": latest_evidence_id,
            }
        )
    return coverage


def _official_model_evidence_action_items(missing_nodes: list[dict[str, Any]], summary: dict[str, int]) -> list[dict[str, Any]]:
    s = _service()
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
    s = _service()
    return {
        "candidateOnly": True,
        "writesFormalKnowledge": False,
        "writesRag": False,
        "writesOfficialGraph": False,
        "requiresStewardApproval": True,
        "boundary": "model_evidence_only_not_formal_knowledge",
    }


def _normalize_official_model_task_type(value: Any) -> str:
    s = _service()
    normalized = s._trim_text(value, max_length=80)
    if not normalized:
        return ""
    if normalized in s.LOCAL_RESEARCH_TASKS:
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
    s = _service()
    normalized = s._trim_text(value, max_length=120)
    for task_type, spec in s.LOCAL_RESEARCH_TASKS.items():
        if str(spec.get("workflowNode") or "") == normalized:
            return task_type
    return s._normalize_official_model_task_type(normalized)


def _normalize_official_model_evidence_kind(value: Any) -> str:
    s = _service()
    normalized = s._trim_text(value, max_length=80)
    return normalized if normalized in s.OFFICIAL_MODEL_EVIDENCE_KINDS else "invocation_log"


def _infer_official_model_provider(value: Any, model_id: str) -> str:
    s = _service()
    explicit = s._trim_text(value, max_length=120)
    if explicit:
        return explicit
    key = model_id.lower()
    if model_id == s.LOCAL_RESEARCH_MODEL_ID or "qwen" in key:
        return "local_qwen"
    if "bailian" in key or "百炼" in model_id:
        return "bailian"
    if "dashscope" in key:
        return "dashscope"
    return "model_runtime"


def _count_by_field(items: list[dict[str, Any]], field: str) -> dict[str, int]:
    s = _service()
    counts: dict[str, int] = {}
    for item in items:
        key = s._trim_text(item.get(field), max_length=120) or "unknown"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _local_research_llm_client(model_id: str, *, llm_client_factory: Any = None) -> Any:
    s = _service()
    normalized_model_id = s._trim_text(model_id, max_length=160) or s.LOCAL_RESEARCH_MODEL_ID
    public_config = s.load_public_config()
    llm = public_config.setdefault("llm", {})
    profiles = llm.setdefault("profiles", {})
    if not isinstance(profiles, dict):
        raise s.TeamWorkflowOrchestrationError("llm.profiles must be an object.")
    profiles[s.LOCAL_RESEARCH_INVOKE_PROFILE_ID] = {"label": "Challenge Cup Local Research Model", "model_ref": normalized_model_id}
    try:
        # schema-v2 keeps canonical models under llm.providers.*.models and only
        # materializes llm.model_library while building the effective runtime
        # config.  Let the shared projection resolve canonical refs and aliases
        # instead of rejecting every v2 model against the legacy public field.
        config = s.build_effective_config(public_config)
    except (KeyError, TypeError, ValueError) as exc:
        raise s.TeamWorkflowOrchestrationError(
            f"Local research model is not configured: {normalized_model_id}"
        ) from exc
    factory = llm_client_factory or s.LLMClient
    return factory(config=config, profile_id=s.LOCAL_RESEARCH_INVOKE_PROFILE_ID)


def _local_research_model_messages(task: dict[str, Any]) -> list[dict[str, str]]:
    s = _service()
    user_payload = {
        "taskId": task.get("taskId", ""),
        "taskType": task.get("taskType", ""),
        "workflowNode": task.get("workflowNode", ""),
        "targetCandidateType": task.get("targetCandidateType", ""),
        "sourceRefs": task.get("sourceRefs", []),
        "evidenceRefs": task.get("evidenceRefs", []),
        "candidateRefs": task.get("candidateRefs", []),
        "excerpt": task.get("excerpt", ""),
        "evidenceLedger": task.get("evidenceLedger", {}),
        "outputContract": task.get("outputContract", {}),
    }
    return [
        {
            "role": "system",
            "content": s._local_research_model_instruction(str(task.get("taskType") or "")),
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
    s = _service()
    for source, text in (("content", content), ("reasoning_content", reasoning_content)):
        parsed = s._parse_first_json_object(text)
        if parsed is not None:
            return parsed, source
    return None, ""


def _local_research_model_instruction(task_type: str) -> str:
    s = _service()
    task = s.LOCAL_RESEARCH_TASKS[s._normalize_local_research_task_type(task_type)]
    return (
        f"You are {s.LOCAL_RESEARCH_MODEL_ROLE}. Task: {task['purpose']} "
        "Return only a JSON object. Preserve sourceRefs and evidenceRefs. "
        "Mark weak evidence as weak_evidence. Mark uncertain terminology as terminology_uncertain. "
        "For mechanism-to-algorithm analogies, separate factLayer from inferenceLayer. "
        "Do not write final review decisions, official Team Knowledge, RAG entries, or official graph sync."
    )


def _local_research_model_boundaries() -> list[str]:
    s = _service()
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


def _normalize_local_research_evidence_ledger(value: Any) -> dict[str, Any]:
    s = _service()
    if not isinstance(value, dict):
        return {}
    status = s._trim_text(value.get("status"), max_length=80)
    if status != "evidence_ready":
        return {}
    return {
        "status": status,
        "claims": s._normalize_metadata_list(value.get("claims"), max_items=12),
        "keyFindings": s._normalize_metadata_list(value.get("keyFindings") or value.get("key_findings"), max_items=12),
        "citations": s._normalize_metadata_list(value.get("citations"), max_items=12),
        "sourceRefs": s._normalize_ref_list(value.get("sourceRefs") or value.get("source_refs"), max_items=24),
        "evidenceRefs": s._normalize_ref_list(value.get("evidenceRefs") or value.get("evidence_refs"), max_items=24),
        "limitations": s._normalize_text_list(value.get("limitations"), max_items=12, max_length=500),
        "uncertainty": s._normalize_text_list(value.get("uncertainty"), max_items=12, max_length=500),
        "riskFlags": s._normalize_text_list(value.get("riskFlags") or value.get("risk_flags"), max_items=12, max_length=120),
        "supportLevel": s._trim_text(value.get("supportLevel") or value.get("support_level"), max_length=80),
        "nextAction": s._trim_text(value.get("nextAction") or value.get("next_action"), max_length=120),
    }


def _workflow_log_sample_values(
    items: list[dict[str, Any]],
    key: str,
    *,
    limit: int = 8,
    max_length: int = 160,
) -> list[str]:
    s = _service()
    values: list[str] = []
    for item in items:
        if len(values) >= limit:
            break
        if not isinstance(item, dict):
            continue
        text = s._trim_text(item.get(key), max_length=max_length)
        if text and text not in values:
            values.append(text)
    return values


def _workflow_log_count_sample(
    counts: dict[str, int],
    *,
    limit: int = 8,
    max_key_length: int = 80,
) -> dict[str, int]:
    s = _service()
    sampled: list[tuple[str, int]] = []
    if not isinstance(counts, dict):
        return {}
    for key, value in counts.items():
        label = s._trim_text(key, max_length=max_key_length)
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
    limit: int = 8,
) -> list[str]:
    s = _service()
    queue_items = queues.get(queue_name)
    if not isinstance(queue_items, list):
        return []
    return s._workflow_log_sample_values(queue_items, "candidateId", limit=limit)


def _read_json(path: Path) -> dict[str, Any]:
    s = _service()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _candidate_store_path(team_id: str) -> Path:
    s = _service()
    return s._team_workflow_root(team_id) / "candidate_store" / "index.json"


def _transfer_records_path(team_id: str) -> Path:
    s = _service()
    return s._team_workflow_root(team_id) / "transfer_recordjsonl"


def _official_model_evidence_store_path(team_id: str) -> Path:
    s = _service()
    return s._team_workflow_root(team_id) / "official_model_evidence" / "index.json"
