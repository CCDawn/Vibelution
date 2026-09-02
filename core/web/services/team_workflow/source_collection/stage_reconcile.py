"""Source-collection stage reconcile / projection kernel.

Claim scope: stage cards projection, session-task reconcile after turns,
repair missing rounds, task messages/tool progress, and closely-coupled
stage support helpers used by ``stages.py``.

Public stage entrypoints remain in ``stages.py``. Writeback materialize and
search execution stay in their own packs. Late-bound facade keeps monkeypatches
stable.
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

from ..source_collection_common import project_source_version_families
from .stage_writeback_prompt_contracts import stage_writeback_prompt_lines


def _service():
    from core.web.services import team_workflow_orchestration_service

    return team_workflow_orchestration_service


def _source_collection_stage_task_writeback_contract(
    team_id: str,
    run_id: str,
    task_id: str,
    *,
    stage_id: str,
    agent_id: str,
    agent_role: str,
    allowed_relation_endpoint_ids: list[str] | None = None,
) -> dict[str, Any]:
    s = _service()
    return s._source_collection_stage_task_writeback_contract_payload(
        team_id,
        run_id,
        task_id,
        stage_id=stage_id,
        agent_id=agent_id,
        agent_role=agent_role,
        schema_version=s.SCHEMA_VERSION,
        allowed_relation_endpoint_ids=allowed_relation_endpoint_ids,
    )


def _normalize_source_collection_stage_id(value: Any, *, default: str = "finding") -> str:
    s = _service()
    stage_id = s._trim_text(value, max_length=80)
    if not stage_id:
        return default
    return stage_id


def _normalize_source_collection_agent_role(value: Any) -> str:
    s = _service()
    return s._trim_text(value, max_length=80)


def _ensure_source_collection_stage_agent_direct_session(
    agent: dict[str, Any],
    *,
    stage_id: str,
    agent_role: str,
) -> dict[str, Any]:
    del stage_id, agent_role
    return agent


def _source_collection_stage_session_previous_round_evidence(
    session_id: str,
    *,
    run_id: str,
) -> dict[str, str]:
    s = _service()
    normalized_session_id = s._trim_text(session_id, max_length=160)
    normalized_run_id = s._trim_text(run_id, max_length=160)
    if not normalized_session_id:
        return {}
    detail = s.session_service.get_session_detail(normalized_session_id)
    if not isinstance(detail, dict):
        return {}
    for message in reversed(list(detail.get("messages") or [])):
        if not isinstance(message, dict):
            continue
        metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        kind = s._trim_text(metadata.get("kind"), max_length=120)
        if kind not in {s.SOURCE_COLLECTION_STAGE_SESSION_TASK_KIND, "source_collection_agent_context"}:
            continue
        message_run_id = (
            s._trim_text(metadata.get("runId"), max_length=160)
            or s._trim_text(metadata.get("sourceCollectionRunId"), max_length=160)
            or s._trim_text(metadata.get("sourceCollectionStageRunId"), max_length=160)
        )
        if not message_run_id:
            continue
        if normalized_run_id and message_run_id == normalized_run_id:
            continue
        message_team_id = s._trim_text(metadata.get("teamId"), max_length=160)
        return {
            "previousDirectSessionId": normalized_session_id,
            "previousSourceRunId": message_run_id,
            "previousTeamId": message_team_id,
            "previousMessageKind": kind,
            "previousMessageId": s._trim_text(message.get("id"), max_length=160),
            "previousStageId": s._trim_text(metadata.get("stageId"), max_length=80),
        }
    return {}


def _ensure_source_collection_stage_agent_session_isolated(
    agent: dict[str, Any],
    *,
    team_id: str,
    run_id: str,
    stage_id: str,
    agent_role: str,
) -> tuple[dict[str, Any], dict[str, str]]:
    del team_id, run_id, stage_id, agent_role
    return agent, {
        "status": "not_required",
        "reason": "research_project_agent_session_registry",
    }


def _attach_source_collection_stage_card_projections(team_id: str, rounds: list[dict[str, Any]]) -> None:
    s = _service()
    for stage_round in rounds:
        if not isinstance(stage_round, dict) or str(stage_round.get("stageType") or "") != "knowledge_collection":
            continue
        source_run_ids = [str(item) for item in list(stage_round.get("sourceRunIds") or []) if str(item or "").strip()]
        if not source_run_ids:
            continue
        projection = s._source_collection_stage_cards_projection(team_id, source_run_ids[-1])
        stage_round["sourceCollectionStageCards"] = projection.get("cards", [])
        stage_round["sourceCollectionStageCardSummary"] = projection.get("summary", {})


def _source_collection_stage_session_task_store_path(team_id: str, run_id: str) -> Path:
    s = _service()
    return s._source_collection_storage_artifact_paths(team_id, run_id)["runDirectory"] / "stage_session_tasks.json"


def _find_source_collection_context_message(session_id: str, context_key: str) -> dict[str, Any] | None:
    s = _service()
    detail = s.session_service.get_session_detail(session_id)
    if not isinstance(detail, dict):
        raise s.TeamWorkflowOrchestrationError(f"Session not found: {session_id}")
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


def _source_collection_stage_session_task_boundaries(*, stage_id: str = "", agent_role: str = "") -> dict[str, bool]:
    s = _service()
    can_materialize_formal_knowledge = s._source_collection_stage_can_materialize_formal_knowledge(stage_id, agent_role)
    return {
        "writesFormalKnowledge": can_materialize_formal_knowledge,
        "writesRag": False,
        "writesOfficialGraph": can_materialize_formal_knowledge,
        "updatesStageTaskResult": True,
        "requiresStructuredWriteback": True,
    }


def _source_collection_memory_steward_action_packet(
    source_candidates: list[dict[str, Any]],
    *,
    writeback_contract: dict[str, Any],
) -> dict[str, Any]:
    s = _service()
    bucket_counts = {"approved": 0, "pending": 0, "rejected": 0, "needs_revision": 0}
    approved_candidates: list[dict[str, Any]] = []
    deferred_candidate_ids: dict[str, list[str]] = {
        "pending": [],
        "rejected": [],
        "needs_revision": [],
    }
    for candidate in [item for item in source_candidates if isinstance(item, dict)]:
        bucket = s._source_quality_bucket(candidate)
        if bucket not in bucket_counts:
            bucket = "pending"
        bucket_counts[bucket] += 1
        candidate_id = s._trim_text(candidate.get("candidateId"), max_length=160)
        if bucket == "approved":
            approved_candidates.append(candidate)
        elif candidate_id and bucket in deferred_candidate_ids:
            deferred_candidate_ids[bucket].append(candidate_id)

    approved_summaries = [
        s._source_collection_context_candidate_summary(item)
        for item in approved_candidates[:40]
    ]
    approved_candidate_ids = [
        item["candidateId"]
        for item in approved_summaries
        if s._trim_text(item.get("candidateId"), max_length=160)
    ]
    recommended_status = "completed" if approved_candidate_ids else "blocked"
    summary = (
        f"资料入库 Agent 通过 {len(approved_candidate_ids)} 条 source_quality_approved 候选，按治理门禁写回。"
        if approved_candidate_ids
        else "本轮没有 source_quality_approved 候选可入库，写回 blocked 并等待资料提炼完成。"
    )
    result_skeleton = {
        "approvedCandidateIds": approved_candidate_ids,
        "candidate_summary": {
            "approved": {
                "count": len(approved_candidate_ids),
                "candidateIds": approved_candidate_ids,
                "candidates": approved_summaries,
            },
            "deferredCounts": {
                "pending": bucket_counts["pending"],
                "rejected": bucket_counts["rejected"],
                "needs_revision": bucket_counts["needs_revision"],
            },
        },
        "steward_assessment": {
            "decision": "approved" if approved_candidate_ids else "blocked",
            "reason": (
                "Only source_quality_approved candidates are eligible for governed ingestion."
            ),
        },
    }
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "packetKind": "knowledge_steward_approved_candidate_action",
        "action": "writeback_approved_candidates" if approved_candidate_ids else "writeback_blocked_no_approved_candidates",
        "recommendedStatus": recommended_status,
        "summary": summary,
        "approvedCandidateIds": approved_candidate_ids,
        "approvedCandidateCount": len(approved_candidate_ids),
        "visibleApprovedCandidateCount": len(approved_summaries),
        "candidateInventoryCounts": bucket_counts,
        "deferredCandidateCounts": {
            "pending": bucket_counts["pending"],
            "rejected": bucket_counts["rejected"],
            "needs_revision": bucket_counts["needs_revision"],
        },
        "deferredCandidateIds": {key: value[:40] for key, value in deferred_candidate_ids.items()},
        "doNotInferHiddenOrTruncatedCandidates": True,
        "doNotReviewPendingCandidates": True,
        "writebackTool": "source_collection_stage_writeback_tool",
        "writebackContractTaskId": s._trim_text(writeback_contract.get("taskId"), max_length=160),
        "writebackResultSkeleton": result_skeleton,
        "instructions": [
            "Only use approvedCandidateIds from this packet for formal knowledge ingestion writeback.",
            "Do not infer hidden or truncated candidates from counts, candidatePage, or earlier chat history.",
            "Do not continue screening pending/rejected/needs_revision candidates in this memory-stage task.",
            "Always call source_collection_stage_writeback_tool; natural-language-only answers do not complete the task.",
        ],
    }


def _normalize_source_collection_stage_session_task_status(value: Any) -> str:
    s = _service()
    normalized = s._trim_text(value, max_length=80).lower()
    return normalized if normalized in s.SOURCE_COLLECTION_STAGE_SESSION_TASK_STATUSES else "needs_review"


def _load_source_collection_stage_session_task_store(team_id: str, run_id: str) -> dict[str, Any]:
    s = _service()
    path = s._source_collection_stage_session_task_store_path(team_id, run_id)
    payload = s._read_json(path) if path.exists() else {}
    if not isinstance(payload.get("tasks"), list):
        # 兼容读取：修复前账本可能错位落在活跃项目根；属主项目优先，缺失时回查。
        legacy_path = (
            s._team_workflow_root(team_id)
            / "source_collection_runs"
            / s._safe_token(run_id, default="run", max_length=96)
            / "stage_session_tasks.json"
        )
        if legacy_path != path and legacy_path.exists():
            payload = s._read_json(legacy_path)
    if isinstance(payload.get("tasks"), list):
        return payload
    now = s.utc_now_iso()
    return {
        "schemaVersion": s.SCHEMA_VERSION,
        "teamId": team_id,
        "runId": run_id,
        "storeKind": "source_collection_stage_session_tasks",
        "tasks": [],
        "createdAt": now,
        "updatedAt": now,
    }


def _write_source_collection_stage_session_task_store(team_id: str, run_id: str, store: dict[str, Any]) -> None:
    s = _service()
    store["teamId"] = team_id
    store["runId"] = run_id
    store["updatedAt"] = s.utc_now_iso()
    s._write_json(s._source_collection_stage_session_task_store_path(team_id, run_id), store)


def _source_collection_stage_session_tasks(team_id: str, run_id: str) -> list[dict[str, Any]]:
    s = _service()
    store = s._load_source_collection_stage_session_task_store(team_id, run_id)
    return [item for item in list(store.get("tasks") or []) if isinstance(item, dict)]


def _reconcile_source_collection_stage_session_task_turn_status(task: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    status = s._trim_text(task.get("status"), max_length=80).lower()
    if status not in s.SOURCE_COLLECTION_STAGE_SESSION_TASK_STATUSES:
        return task
    # An explicit task-level failure (failed + failureCode) is a deliberate
    # terminal marker: turn-terminal failure propagation and the
    # missing-session recovery path both write it.  A writeback status
    # recorded earlier in the same turn must not resurrect the task, because
    # the formal replay reads exactly this failed+failureCode state to decide
    # a fresh-session retry.  A formal retry resets the whole task record, so
    # this guard never blocks a legitimate retry.
    if status == "failed" and s._trim_text(task.get("failureCode"), max_length=120):
        return task
    writeback = task.get("writeback") if isinstance(task.get("writeback"), dict) else {}
    writeback_status = s._trim_text(writeback.get("status"), max_length=80).lower() if writeback else ""
    if writeback_status and writeback_status not in s.SOURCE_COLLECTION_STAGE_SESSION_TASK_STATUSES:
        writeback_status = ""
    settled_status = writeback_status or status
    if settled_status in s.SOURCE_COLLECTION_STAGE_SESSION_TASK_ACTIVE_STATUSES:
        return task
    turn = task.get("turn") if isinstance(task.get("turn"), dict) else {}
    if not turn or s._trim_text(turn.get("status"), max_length=80).lower() == settled_status:
        return task
    next_task = dict(task)
    next_task["status"] = settled_status
    next_turn = dict(turn)
    next_turn["status"] = settled_status
    next_task["turn"] = next_turn
    return next_task


def _reconcile_source_collection_stage_session_task_retry_coverage(
    team_id: str,
    run_id: str,
    task: dict[str, Any],
) -> dict[str, Any]:
    s = _service()
    if not s._trim_text(task.get("retrySourceTaskId"), max_length=160):
        return task
    writeback = task.get("writeback") if isinstance(task.get("writeback"), dict) else {}
    current_result = writeback.get("result") if isinstance(writeback.get("result"), dict) else {}
    if not current_result and isinstance(task.get("result"), dict):
        current_result = task["result"]
    if not current_result:
        return task
    merged_result = s._merge_source_collection_stage_writeback_result_payload(
        team_id,
        run_id,
        task,
        current_result,
    )
    coverage_writeback = dict(writeback)
    coverage_writeback["result"] = merged_result
    coverage_summary = s._source_collection_stage_writeback_candidate_coverage(
        team_id,
        run_id,
        task,
        coverage_writeback,
    )
    existing_coverage = (
        writeback.get("coverageSummary")
        if isinstance(writeback.get("coverageSummary"), dict)
        else {}
    )
    if merged_result == current_result and coverage_summary == existing_coverage:
        return task
    next_task = dict(task)
    next_writeback = dict(writeback)
    next_result = dict(task.get("result")) if isinstance(task.get("result"), dict) else {}
    next_writeback["result"] = merged_result
    next_writeback["coverageSummary"] = coverage_summary
    next_writeback["invalidCandidateIds"] = list(coverage_summary.get("invalidCandidateIds") or [])
    next_writeback["invalidRecordIds"] = list(coverage_summary.get("invalidRecordIds") or [])
    next_result.update(merged_result)
    next_result["coverageSummary"] = coverage_summary
    next_task["writeback"] = next_writeback
    next_task["result"] = next_result
    next_task["updatedAt"] = s.utc_now_iso()
    return next_task


def _reconcile_source_collection_stage_session_tasks(team_id: str) -> bool:
    s = _service()
    changed = False
    for runs_root in s._source_collection_task_store_search_roots(team_id):
        if not runs_root.exists():
            continue
        for task_store_path in runs_root.glob("*/stage_session_tasks.json"):
            run_id = task_store_path.parent.name
            changed = s._reconcile_source_collection_stage_session_tasks_for_run(team_id, run_id) or changed
    return changed


def _reconcile_source_collection_stage_session_tasks_for_run(team_id: str, run_id: str) -> bool:
    s = _service()
    normalized_run_id = s._trim_text(run_id, max_length=160)
    if not normalized_run_id:
        return False
    task_store_path = s._source_collection_stage_session_task_store_path(team_id, normalized_run_id)
    if not task_store_path.exists():
        return False
    store = s._read_json(task_store_path)
    tasks = [item for item in list(store.get("tasks") or []) if isinstance(item, dict)]
    if not tasks:
        return False
    changed = s._repair_missing_source_collection_stage_round(team_id, normalized_run_id, tasks)
    next_tasks: list[dict[str, Any]] = []
    store_changed = False
    conversation_events_by_session: dict[str, list[Any]] = {}
    for task in tasks:
        reconciled = s._reconcile_source_collection_stage_session_task_turn_status(task)
        reconciled = s._reconcile_source_collection_stage_session_task_from_turn_result(
            reconciled,
            conversation_events_by_session=conversation_events_by_session,
        )
        reconciled = s._reconcile_source_collection_stage_session_task_retry_coverage(
            team_id,
            normalized_run_id,
            reconciled,
        )
        reconciled = s._reconcile_source_collection_stage_session_task_sources(team_id, normalized_run_id, reconciled)
        reconciled = s._reconcile_source_collection_stage_session_task_completion_gate(
            team_id,
            normalized_run_id,
            reconciled,
            conversation_events_by_session=conversation_events_by_session,
        )
        next_tasks.append(reconciled)
        store_changed = store_changed or reconciled is not task
    if store_changed:
        store["tasks"] = next_tasks
        s._write_source_collection_stage_session_task_store(team_id, normalized_run_id, store)
        for task in next_tasks:
            if s._trim_text(task.get("status"), max_length=80) not in {"running", "queued"}:
                s._sync_stage_round_with_source_collection_stage_task(team_id, normalized_run_id, task)
        changed = True
    return changed


def _reconcile_source_collection_stage_session_task(team_id: str, run_id: str, task: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    conversation_events_by_session: dict[str, list[Any]] = {}
    reconciled = s._reconcile_source_collection_stage_session_task_turn_status(task)
    reconciled = s._reconcile_source_collection_stage_session_task_from_turn_result(
        reconciled,
        conversation_events_by_session=conversation_events_by_session,
    )
    reconciled = s._reconcile_source_collection_stage_session_task_retry_coverage(team_id, run_id, reconciled)
    reconciled = s._reconcile_source_collection_stage_session_task_sources(team_id, run_id, reconciled)
    reconciled = s._reconcile_source_collection_stage_session_task_completion_gate(
        team_id,
        run_id,
        reconciled,
        conversation_events_by_session=conversation_events_by_session,
    )
    if reconciled == task:
        return task
    s._upsert_source_collection_stage_session_task(team_id, run_id, reconciled)
    if s._trim_text(reconciled.get("status"), max_length=80) not in {"running", "queued"}:
        s._sync_stage_round_with_source_collection_stage_task(team_id, run_id, reconciled)
    return reconciled


def _source_collection_stage_session_task_with_continuation_turn(
    task: dict[str, Any],
    *,
    session_id: str,
    turn_id: str,
) -> dict[str, Any] | None:
    s = _service()
    normalized_session_id = s._trim_text(session_id, max_length=160)
    normalized_turn_id = s._trim_text(turn_id, max_length=200)
    if not isinstance(task, dict) or not normalized_session_id or not normalized_turn_id:
        return None
    turn = task.get("turn") if isinstance(task.get("turn"), dict) else {}
    task_session_id = s._trim_text(task.get("sessionId") or turn.get("sessionId"), max_length=160)
    if task_session_id and normalized_session_id != task_session_id:
        return None
    task_id = s._trim_text(task.get("taskId"), max_length=160)
    if not task_id:
        return None
    if not s._source_collection_stage_session_task_turn_references_task(task, normalized_session_id, normalized_turn_id):
        return None

    previous_turn_id = s._trim_text(turn.get("turnId"), max_length=200)
    next_task = dict(task)
    next_turn = dict(turn)
    if previous_turn_id and previous_turn_id != normalized_turn_id:
        next_turn["previousTurnId"] = previous_turn_id
    next_turn["turnId"] = normalized_turn_id
    next_turn["sessionId"] = normalized_session_id
    next_turn["status"] = s._trim_text(task.get("status"), max_length=80) or s._trim_text(turn.get("status"), max_length=80)
    turn_ids = s._source_collection_stage_task_turn_ids(task)
    if previous_turn_id:
        turn_ids.append(previous_turn_id)
    turn_ids.append(normalized_turn_id)
    deduped_turn_ids = s._source_collection_stage_task_turn_id_sequence(turn_ids)
    next_turn["turnIds"] = deduped_turn_ids
    next_task["turnIds"] = deduped_turn_ids
    next_task["turn"] = next_turn
    next_task["sessionId"] = normalized_session_id
    next_task["updatedAt"] = s.utc_now_iso()

    agent_id = s._trim_text(task.get("agentId"), max_length=160)
    turn_result = s._source_collection_stage_session_task_turn_result(agent_id, normalized_session_id, normalized_turn_id) if agent_id else {}
    if turn_result:
        result_status = s._source_collection_stage_task_status_from_turn_result(turn_result)
        if result_status not in {"running", "queued"}:
            next_turn["status"] = result_status
            next_task["reconciledFromTurn"] = {
                "turnId": normalized_turn_id,
                "previousTurnId": previous_turn_id,
                "status": s._trim_text(turn_result.get("status"), max_length=80),
                "resultEventId": s._trim_text(turn_result.get("eventId"), max_length=160),
                "createdAt": s._trim_text(turn_result.get("createdAt"), max_length=120),
                "reconciledAt": next_task["updatedAt"],
            }
            writeback = next_task.get("writeback") if isinstance(next_task.get("writeback"), dict) else {}
            next_summary = s._trim_text(writeback.get("summary"), max_length=4000) or s._trim_text(turn_result.get("summary"), max_length=4000)
            if next_summary:
                next_task["summary"] = next_summary
    return next_task


def _source_collection_stage_task_turn_ids(task: dict[str, Any]) -> list[str]:
    s = _service()
    turn = task.get("turn") if isinstance(task.get("turn"), dict) else {}
    raw_values: list[Any] = []
    if isinstance(task.get("turnIds"), list):
        raw_values.extend(task.get("turnIds") or [])
    if isinstance(turn.get("turnIds"), list):
        raw_values.extend(turn.get("turnIds") or [])
    for key in ("previousTurnId", "turnId"):
        raw_values.append(turn.get(key))
    return [
        s._trim_text(value, max_length=200)
        for value in raw_values
        if s._trim_text(value, max_length=200)
    ]


def _source_collection_stage_task_turn_id_sequence(values: list[Any]) -> list[str]:
    s = _service()
    result: list[str] = []
    for value in values:
        text = s._trim_text(value, max_length=200)
        if text and text not in result:
            result.append(text)
    return result[-12:]


def _source_collection_stage_session_task_turn_references_task(
    task: dict[str, Any],
    session_id: str,
    turn_id: str,
) -> bool:
    s = _service()
    task_id = s._trim_text(task.get("taskId"), max_length=160)
    if not task_id:
        return False
    try:
        events = s.load_conversation_events(s._project_root(), session_id)
    except Exception:
        return False
    for event in events:
        if s._trim_text(getattr(event, "turn_id", ""), max_length=200) != turn_id:
            continue
        metadata = s._source_collection_stage_event_metadata(event)
        if s._source_collection_stage_task_id_from_metadata(metadata) == task_id:
            return True
        for tool_call in s._source_collection_stage_tool_calls_from_event(event):
            if s._source_collection_stage_task_id_from_tool_call(tool_call) == task_id:
                return True
    return False


def _source_collection_stage_task_id_from_metadata(metadata: dict[str, Any]) -> str:
    s = _service()
    if not isinstance(metadata, dict):
        return ""
    writeback_contract = metadata.get("writebackContract") if isinstance(metadata.get("writebackContract"), dict) else {}
    return (
        s._trim_text(metadata.get("sourceCollectionStageTaskId"), max_length=160)
        or s._trim_text(metadata.get("taskId"), max_length=160)
        or s._trim_text(writeback_contract.get("taskId"), max_length=160)
    )


def _source_collection_stage_task_id_from_tool_call(tool_call: dict[str, Any]) -> str:
    s = _service()
    if not isinstance(tool_call, dict):
        return ""
    args = s._source_collection_stage_tool_call_args(tool_call)
    result = tool_call.get("result") if isinstance(tool_call.get("result"), dict) else {}
    return (
        s._trim_text(args.get("task_id"), max_length=160)
        or s._trim_text(args.get("taskId"), max_length=160)
        or s._trim_text(result.get("taskId"), max_length=160)
    )


def _repair_missing_source_collection_stage_round(team_id: str, run_id: str, tasks: list[dict[str, Any]]) -> bool:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_run_id = s._normalize_required_id(run_id, "Data processing run id is required.")
    with s._WORKFLOW_LOCK:
        store = s._load_stage_round_store(normalized_team_id)
        rounds = s._stage_rounds(store)
        existing = s._latest_stage_round(
            [
                item
                for item in rounds
                if str(item.get("stageType") or "") == "knowledge_collection"
                and normalized_run_id in {str(source_run_id) for source_run_id in list(item.get("sourceRunIds") or [])}
            ]
        )
        if existing is not None:
            return False
    try:
        s.team_service.assert_team_exists(normalized_team_id)
        run = s.data_processing_service.get_processing_run(normalized_run_id)
        assignments_payload = s.data_processing_service.list_collection_assignments(normalized_run_id)
        run_status = s.data_processing_service.get_processing_status(normalized_run_id)
    except (s.team_service.TeamServiceError, s.data_processing_service.DataProcessingError):
        return False
    scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
    metadata = run.get("metadata") if isinstance(run.get("metadata"), dict) else {}
    if s._trim_text(scope.get("teamId") or metadata.get("teamId"), max_length=128) not in {"", normalized_team_id}:
        return False
    if (
        s._trim_text(metadata.get("startedFrom"), max_length=160) != "team_workflow_source_collection"
        and s._trim_text(scope.get("workflowStage"), max_length=120) != "knowledge_collection"
        and not tasks
    ):
        return False
    with s._WORKFLOW_LOCK:
        store = s._load_stage_round_store(normalized_team_id)
        rounds = s._stage_rounds(store)
        existing = s._latest_stage_round(
            [
                item
                for item in rounds
                if str(item.get("stageType") or "") == "knowledge_collection"
                and normalized_run_id in {str(source_run_id) for source_run_id in list(item.get("sourceRunIds") or [])}
            ]
        )
        if existing is not None:
            return False
        workflow = s._load_or_create_workflow(normalized_team_id)
        assignments = [
            item for item in list(assignments_payload.get("assignments") or [])
            if isinstance(item, dict)
        ]
        run_status_summary = run_status.get("summary") if isinstance(run_status.get("summary"), dict) else {}
        candidate_store = s._load_candidate_store(normalized_team_id)
        run_candidate_count = s._source_collection_candidate_count_for_run(candidate_store, normalized_run_id)
        round_number = s._normalize_int(scope.get("researchStageRoundNumber"), default=s._stage_round_number(rounds, "knowledge_collection"), minimum=1, maximum=10000)
        stage_round_id = (
            s._trim_text(scope.get("researchStageRoundId"), max_length=160)
            or s._new_record_id("stage-repaired")
        )
        now = s.utc_now_iso()
        search_execution = {
            "runId": normalized_run_id,
            "status": s._trim_text(run.get("status"), max_length=80) or s._trim_text(run_status.get("runStatus"), max_length=80),
            "resultStatus": s._trim_text(run_status.get("runStatus"), max_length=80),
            "executionMode": "repaired_from_source_run",
            "accepted": False,
            "provider": s.SOURCE_COLLECTION_SEARCH_PROVIDER_CROSSREF,
            "recordCount": s._source_collection_count(run_status_summary.get("recordCount")),
            "remainingQueryCount": s._source_collection_count(run_status_summary.get("openAssignmentCount")),
            "summary": "Recovered knowledge-collection stage round from source collection run and stage task records.",
            "updatedAt": now,
        }
        task_refs = s._source_collection_stage_task_refs(normalized_run_id, tasks)
        stage_status = s._source_collection_stage_round_status_from_task_refs(
            {"status": "running", "sourceCollectionSearchExecution": search_execution},
            task_refs,
        )
        if not task_refs:
            stage_status = s._source_collection_stage_round_status_after_search(
                str(search_execution.get("status") or ""),
                result={},
                run_status_summary=run_status_summary,
                source_collection_summary={},
                run_candidate_count=run_candidate_count,
            )
        stage_round = {
            "schemaVersion": s.SCHEMA_VERSION,
            "stageRoundId": stage_round_id,
            "teamId": normalized_team_id,
            "stageType": "knowledge_collection",
            "roundNumber": round_number,
            "status": stage_status,
            "title": s._trim_text(run.get("title"), max_length=180) or f"{s.RESEARCH_STAGE_DEFAULTS['knowledge_collection']['title']} {round_number}",
            "topic": s._trim_text(scope.get("topic") or metadata.get("topic"), max_length=500) or s._stage_default_topic("knowledge_collection", None),
            "goal": s._trim_text(scope.get("goal") or metadata.get("goal"), max_length=1000) or s._stage_default_goal("knowledge_collection", None),
            "requestedByAgent": s._trim_text(metadata.get("requestedByAgent"), max_length=160) or s.DEFAULT_OWNER_AGENT_ID,
            "ownerAgentId": s._trim_text(metadata.get("ownerAgentId"), max_length=160) or s.DEFAULT_OWNER_AGENT_ID,
            "upstreamRoundIds": s._normalize_text_list(scope.get("upstreamRoundIds"), max_items=24, max_length=160),
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
            "querySeeds": s._normalize_text_list(scope.get("querySeeds") or metadata.get("querySeeds"), max_items=40, max_length=220),
            "suggestedQuerySeeds": [],
            "inputRefs": s._normalize_text_list(scope.get("inputRefs"), max_items=120, max_length=240),
            "searchLanguages": s._source_collection_search_languages(scope.get("searchLanguages")),
            "sourceTypes": s._source_collection_source_types(scope.get("sourceTypes")),
            "maxResultsPerQuery": s._normalize_int(scope.get("maxResultsPerQuery"), default=s.SOURCE_COLLECTION_DEFAULT_MAX_RESULTS_PER_QUERY, minimum=1, maximum=100),
            "workflowItemRef": {"candidateId": normalized_run_id, "currentNode": "knowledge_collection"},
            "dataSearchPlanRef": scope.get("dataSearchPlanRef") if isinstance(scope.get("dataSearchPlanRef"), dict) else {},
            "sourceCollectionSearchExecution": search_execution,
            "sourceCollectionSummary": {
                "recordCount": s._source_collection_count(run_status_summary.get("recordCount")),
                "candidateCount": run_candidate_count,
                "assignmentCount": len(assignments),
                "openAssignmentCount": s._source_collection_count(run_status_summary.get("openAssignmentCount")),
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
            "boundaries": s._research_stage_boundaries(),
            "createdAt": s._trim_text(run.get("createdAt"), max_length=120) or now,
            "updatedAt": now,
        }
        stage_round["teamMemoryRecord"] = s._stage_memory_record(stage_round, workflow)
        stage_round["teamMemoryRecordId"] = stage_round["teamMemoryRecord"]["recordId"]
        store["rounds"] = rounds + [stage_round]
        store["updatedAt"] = now
        workflow["activeWorkflowItems"] = s._upsert_active_item(
            workflow.get("activeWorkflowItems"),
            candidate_id=normalized_run_id,
            current_node="knowledge_collection",
            status=f"source_collection_{stage_status}",
            transfer_id="",
        )
        workflow["updatedAt"] = now
        s._write_json(s._stage_round_store_path(normalized_team_id), store)
        s._write_json(s._workflow_path(normalized_team_id), workflow)
    s._record_workflow_event(
        "research_stage_round.repaired_from_source_collection_run",
        normalized_team_id,
        fields={
            "runId": normalized_run_id,
            "stageRoundId": stage_round_id,
            "status": stage_status,
            "taskCount": len(task_refs),
            "recordCount": s._source_collection_count(run_status_summary.get("recordCount")),
            "candidateCount": run_candidate_count,
        },
    )
    return True


def _source_collection_stage_task_refs(run_id: str, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    s = _service()
    refs: list[dict[str, Any]] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        refs.append(
            {
                "taskId": s._trim_text(task.get("taskId"), max_length=160),
                "runId": run_id,
                "stageId": s._trim_text(task.get("stageId"), max_length=80),
                "agentId": s._trim_text(task.get("agentId"), max_length=160),
                "agentRole": s._trim_text(task.get("agentRole"), max_length=80),
                "sessionId": s._trim_text(task.get("sessionId"), max_length=160),
                "status": s._trim_text(task.get("status"), max_length=80),
                "summary": s._trim_text(task.get("summary"), max_length=500),
                "updatedAt": s._trim_text(task.get("updatedAt"), max_length=120),
            }
        )
    return sorted(refs, key=lambda item: str(item.get("updatedAt") or ""))


def _source_collection_stage_cards_projection(
    team_id: str,
    run_id: str,
    *,
    run_status: dict[str, Any] | None = None,
    run: dict[str, Any] | None = None,
) -> dict[str, Any]:
    s = _service()
    normalized_team_id = s._normalize_required_id(team_id, "Team id is required.")
    normalized_run_id = s._trim_text(run_id, max_length=160)
    if not normalized_run_id:
        return {"runId": "", "cards": [], "latestTasks": {}, "summary": {"closedLoopCount": 0, "stageCount": 0}}
    resolved_run_status = run_status if isinstance(run_status, dict) else None
    if resolved_run_status is None:
        try:
            resolved_run_status = s.data_processing_service.get_processing_status(normalized_run_id)
        except s.data_processing_service.DataProcessingError:
            resolved_run_status = {}
    run_summary = resolved_run_status.get("summary") if isinstance(resolved_run_status.get("summary"), dict) else {}
    raw_record_count = s._source_collection_count(run_summary.get("recordCount"))
    active_record_count = raw_record_count
    excluded_source_count = 0
    try:
        projection_run = run if isinstance(run, dict) and s._trim_text(run.get("runId"), max_length=160) == normalized_run_id else s.data_processing_service.get_processing_run(normalized_run_id)
        projection_records_payload = s.data_processing_service.list_records(normalized_run_id)
        projection_records = [item for item in list(projection_records_payload.get("records") or []) if isinstance(item, dict)]
        active_projection_records, excluded_source_summary = s._source_collection_filter_active_records(
            normalized_team_id,
            projection_run,
            projection_records,
        )
        raw_record_count = len(projection_records)
        active_record_count = len(active_projection_records)
        excluded_source_count = s._source_collection_count(excluded_source_summary.get("excludedCount"))
    except s.data_processing_service.DataProcessingError:
        pass
    assignment_stage_summary: dict[str, int] = {}
    try:
        assignments_payload = s.data_processing_service.list_collection_assignments(normalized_run_id)
        projection_assignments = [
            item for item in list(assignments_payload.get("assignments") or [])
            if isinstance(item, dict)
        ]
        assignment_stage_summary = s._source_collection_assignment_stage_summary(projection_assignments)
    except s.data_processing_service.DataProcessingError:
        assignment_stage_summary = {}
    finding_open_assignment_count = (
        s._source_collection_count(assignment_stage_summary.get("searchOpenAssignmentCount"))
        if assignment_stage_summary
        else s._source_collection_count(run_summary.get("openAssignmentCount"))
    )
    downstream_open_assignment_count = s._source_collection_count(
        assignment_stage_summary.get("downstreamOpenAssignmentCount")
    )
    with s._WORKFLOW_LOCK:
        candidate_store = s._load_candidate_store(normalized_team_id)
    all_candidates = [item for item in list(candidate_store.get("candidates") or []) if isinstance(item, dict)]
    active_candidates = [item for item in all_candidates if not s._candidate_is_archived(item)]
    source_candidates = [
        item for item in all_candidates
        if str(item.get("candidateType") or "") == "source_manifest"
        and s._source_collection_candidate_trace_run_id(item) == normalized_run_id
    ]
    projected_source_candidates, source_family_summary = project_source_version_families(source_candidates)
    reviewable_source_candidates = [
        item
        for item in projected_source_candidates
        if not (
            isinstance(item.get("sourceVersionFamily"), dict)
            and item["sourceVersionFamily"].get("state") == "superseded"
        )
    ]
    assessed_sources = [
        item
        for item in reviewable_source_candidates
        if s._candidate_source_quality_assessment(item) is not None
    ]
    approved_sources = [
        item for item in reviewable_source_candidates
        if s._source_quality_bucket(item) == "approved"
    ]
    needs_revision_sources = [
        item for item in reviewable_source_candidates
        if s._source_quality_bucket(item) == "needs_revision"
    ]
    rejected_sources = [
        item for item in reviewable_source_candidates
        if s._source_quality_bucket(item) == "rejected"
    ]
    unassessed_sources = [
        item for item in reviewable_source_candidates
        if s._source_quality_bucket(item) == "pending"
    ]
    extraction_pending_count = len(needs_revision_sources) + len(unassessed_sources)
    source_candidate_ids = {
        s._trim_text(item.get("candidateId"), max_length=160)
        for item in source_candidates
        if s._trim_text(item.get("candidateId"), max_length=160)
    }
    graph_candidates = [
        item for item in active_candidates
        if str(item.get("candidateType") or "") == "candidate_graph"
        and s._source_collection_candidate_graph_matches_run(item, source_candidate_ids)
    ]
    latest_graph = s._latest_candidate_record(graph_candidates)
    latest_graph_metadata = latest_graph.get("metadata") if isinstance((latest_graph or {}).get("metadata"), dict) else {}
    latest_graph_payload = latest_graph_metadata.get("graph") if isinstance(latest_graph_metadata.get("graph"), dict) else {}
    graph_summary = latest_graph_payload.get("summary") if isinstance(latest_graph_payload.get("summary"), dict) else {}
    steward_candidates = [
        item
        for item in active_candidates
        if s._source_collection_steward_candidate_matches_run(item, source_candidate_ids)
    ]
    steward_pack_count = len(steward_candidates)
    formal_synced_count = sum(
        1
        for item in steward_candidates
        if str(item.get("currentState") or "") in {"official_synced", "formal_knowledge_synced"}
    )
    pending_steward_pack_count = max(0, steward_pack_count - formal_synced_count)
    tasks = s._source_collection_stage_session_tasks(normalized_team_id, normalized_run_id)
    tasks_by_stage: dict[str, list[dict[str, Any]]] = {}
    for task in tasks:
        stage_id = s._normalize_source_collection_stage_id(task.get("stageId"), default="")
        if stage_id in s.SOURCE_COLLECTION_AGENT_CONTEXT_STAGE_ROLES:
            tasks_by_stage.setdefault(stage_id, []).append(task)
    current_agent_ids_by_stage = (
        s._source_collection_current_stage_agent_ids_by_stage(normalized_team_id, tasks_by_stage.keys())
        if tasks_by_stage
        else {}
    )
    stage_task_groups = {
        stage_id: s._source_collection_stage_tasks_for_current_team(
            normalized_team_id,
            stage_id,
            stage_tasks,
            current_agent_ids=current_agent_ids_by_stage.get(stage_id),
        )
        for stage_id, stage_tasks in tasks_by_stage.items()
    }
    stage_task_groups = s._source_collection_stage_task_groups_after_completion_supersession(
        stage_task_groups,
        s._source_collection_completion_superseded_stage_cutoffs(normalized_team_id, normalized_run_id),
    )
    finding_has_verified_completed_task = any(
        s._trim_text(task.get("status"), max_length=80).lower() == "completed"
        and isinstance(task.get("completionGate"), dict)
        and bool(task["completionGate"].get("passed"))
        for task in stage_task_groups.get("finding", ([], []))[0]
        if isinstance(task, dict)
    )
    finding_effective_open_assignment_count = (
        0 if finding_has_verified_completed_task else finding_open_assignment_count
    )
    cards = [
        s._source_collection_stage_card_projection(
            "finding",
            stage_task_groups.get("finding", ([], []))[0],
            artifact_count=active_record_count,
            input_count=s._source_collection_count(run_summary.get("assignmentCount")),
            output_count=active_record_count,
            pending_count=finding_effective_open_assignment_count,
            artifact_status="ready" if active_record_count > 0 else "empty",
            artifact_summary=f"{active_record_count} active DataRecord records; {excluded_source_count} excluded; {finding_open_assignment_count} search assignments remain.",
            historical_task_count=len(stage_task_groups.get("finding", ([], []))[1]),
            extra_counts={
                "excluded": excluded_source_count,
                "rawRecord": raw_record_count,
                "searchOpenAssignment": finding_open_assignment_count,
                "downstreamOpenAssignment": downstream_open_assignment_count,
            },
        ),
        s._source_collection_stage_card_projection(
            "extraction",
            stage_task_groups.get("extraction", ([], []))[0],
            artifact_count=max(len(reviewable_source_candidates), len(assessed_sources)),
            input_count=active_record_count,
            output_count=len(approved_sources),
            pending_count=(
                extraction_pending_count
                if reviewable_source_candidates
                else max(0, active_record_count - len(source_candidates))
            ),
            artifact_status=(
                "ready"
                if reviewable_source_candidates and extraction_pending_count <= 0
                else ("partial" if reviewable_source_candidates or assessed_sources else "empty")
            ),
            artifact_summary=(
                f"{len(source_candidates)} source_manifest records; "
                f"{len(reviewable_source_candidates)} current sources; "
                f"{len(assessed_sources)}/{len(reviewable_source_candidates)} assessed; "
                f"{len(approved_sources)} approved; "
                f"{len(needs_revision_sources)} need material supplements; "
                f"{len(rejected_sources)} rejected; "
                f"{source_family_summary['supersededRecordCount']} superseded; "
                f"{excluded_source_count} excluded."
            ),
            historical_task_count=len(stage_task_groups.get("extraction", ([], []))[1]),
            extra_counts={
                "excluded": excluded_source_count,
                "rawRecord": raw_record_count,
                "independent": len(reviewable_source_candidates),
                "superseded": source_family_summary["supersededRecordCount"],
                "needsRevision": len(needs_revision_sources),
                "rejected": len(rejected_sources),
                "unassessed": len(unassessed_sources),
            },
        ),
        s._source_collection_stage_card_projection(
            "relations",
            stage_task_groups.get("relations", ([], []))[0],
            artifact_count=s._source_collection_count(graph_summary.get("nodeCount")),
            input_count=len(approved_sources),
            output_count=s._source_collection_count(graph_summary.get("edgeCount")),
            pending_count=0 if graph_summary else len(approved_sources),
            artifact_status="ready" if graph_summary else "empty",
            artifact_summary=f"{s._source_collection_count(graph_summary.get('nodeCount'))} graph nodes; {s._source_collection_count(graph_summary.get('edgeCount'))} graph edges.",
            historical_task_count=len(stage_task_groups.get("relations", ([], []))[1]),
        ),
        s._source_collection_stage_card_projection(
            "ingestion",
            stage_task_groups.get("ingestion", ([], []))[0],
            artifact_count=max(steward_pack_count, formal_synced_count),
            input_count=len(approved_sources),
            output_count=formal_synced_count,
            pending_count=pending_steward_pack_count if steward_pack_count else len(approved_sources),
            artifact_status="ready" if formal_synced_count else ("partial" if steward_pack_count else "empty"),
            artifact_summary=f"{steward_pack_count} 个入库审核包；{formal_synced_count} 个正式知识同步标记。",
            historical_task_count=len(stage_task_groups.get("ingestion", ([], []))[1]),
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
            "recordCount": active_record_count,
            "rawRecordCount": raw_record_count,
            "excludedSourceCount": excluded_source_count,
            "sourceCandidateCount": len(source_candidates),
            "independentSourceCandidateCount": len(reviewable_source_candidates),
            "supersededSourceCandidateCount": source_family_summary["supersededRecordCount"],
            "assessedSourceCandidateCount": len(assessed_sources),
            "approvedSourceCandidateCount": len(approved_sources),
            "needsRevisionSourceCandidateCount": len(needs_revision_sources),
            "rejectedSourceCandidateCount": len(rejected_sources),
            "unassessedSourceCandidateCount": len(unassessed_sources),
            "graphNodeCount": s._source_collection_count(graph_summary.get("nodeCount")),
            "stewardPackCount": steward_pack_count,
            "formalKnowledgeSyncCount": formal_synced_count,
        },
    }


def _source_collection_stage_tasks_for_current_team(
    team_id: str,
    stage_id: str,
    tasks: list[dict[str, Any]],
    *,
    current_agent_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    s = _service()
    valid_tasks = [item for item in tasks if isinstance(item, dict)]
    if current_agent_ids is None:
        current_agent_ids = s._source_collection_current_stage_agent_ids(team_id, stage_id)
    if not current_agent_ids:
        return valid_tasks, []
    current: list[dict[str, Any]] = []
    historical: list[dict[str, Any]] = []
    for task in valid_tasks:
        agent_id = s._trim_text(task.get("agentId"), max_length=160)
        if agent_id and agent_id in current_agent_ids:
            current.append(task)
        else:
            historical.append(task)
    return current, historical


def _source_collection_stage_task_groups_after_completion_supersession(
    stage_task_groups: dict[str, tuple[list[dict[str, Any]], list[dict[str, Any]]]],
    stage_cutoffs: dict[str, str],
) -> dict[str, tuple[list[dict[str, Any]], list[dict[str, Any]]]]:
    s = _service()
    if not stage_cutoffs:
        return stage_task_groups
    result: dict[str, tuple[list[dict[str, Any]], list[dict[str, Any]]]] = {}
    for stage_id, group in stage_task_groups.items():
        current, historical = group
        cutoff = s._trim_text(stage_cutoffs.get(stage_id), max_length=120)
        if not cutoff:
            result[stage_id] = (current, historical)
            continue
        next_current: list[dict[str, Any]] = []
        superseded: list[dict[str, Any]] = []
        for task in current:
            if s._source_collection_stage_task_superseded_by_completion(task, cutoff):
                superseded.append(task)
            else:
                next_current.append(task)
        result[stage_id] = (next_current, [*historical, *superseded])
    return result


def _source_collection_stage_task_superseded_by_completion(task: dict[str, Any], completion_updated_at: str) -> bool:
    s = _service()
    status = s._trim_text(task.get("status"), max_length=80).lower()
    if status in {"completed", "needs_review"}:
        return False
    task_updated_at = s._trim_text(task.get("updatedAt") or task.get("createdAt"), max_length=120)
    if not task_updated_at:
        return True
    return s._workflow_timestamp_sort_key(task_updated_at) < s._workflow_timestamp_sort_key(completion_updated_at)


def _reconcile_source_collection_stage_session_task_sources(team_id: str, run_id: str, task: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    writeback = task.get("writeback") if isinstance(task.get("writeback"), dict) else {}
    if not writeback:
        return task
    status = s._trim_text(writeback.get("status") or task.get("status"), max_length=80).lower()
    if status not in s.SOURCE_COLLECTION_STAGE_WRITEBACK_MATERIALIZED_STATUSES:
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
    existing_status = s._trim_text(existing_summary.get("status"), max_length=80).lower()
    if not existing_status or existing_status == "failed":
        materialized_sources = s._materialize_source_collection_stage_writeback_sources(
            team_id,
            run_id,
            task,
            writeback,
        )
        next_writeback["materializedSources"] = materialized_sources
        next_result["materializedSources"] = materialized_sources
        changed = True
        s._record_workflow_event(
            "source_collection.stage_session_task_sources_reconciled",
            team_id,
            fields={
                "runId": run_id,
                "taskId": s._trim_text(task.get("taskId"), max_length=160),
                "stageId": s._trim_text(task.get("stageId"), max_length=80),
                "agentId": s._trim_text(task.get("agentId"), max_length=160),
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
    existing_quality_status = s._trim_text(existing_quality_summary.get("status"), max_length=80).lower()
    should_reconcile_quality = (
        (
            s._normalize_source_collection_stage_id(task.get("stageId"), default="") == "extraction"
            or s._normalize_source_collection_agent_role(task.get("agentRole")) == "source_extractor"
        )
        and bool(s._source_collection_stage_writeback_candidate_decisions(result))
    )
    if should_reconcile_quality and existing_quality_status in {"", "failed", "no_assessable_decisions"}:
        materialized_quality = s._materialize_source_collection_stage_writeback_quality(
            team_id,
            run_id,
            task,
            writeback,
        )
        next_writeback["materializedSourceQuality"] = materialized_quality
        next_result["materializedSourceQuality"] = materialized_quality
        changed = True

    existing_graph_summary = writeback.get("materializedCandidateGraph") if isinstance(writeback.get("materializedCandidateGraph"), dict) else {}
    existing_graph_status = s._trim_text(existing_graph_summary.get("status"), max_length=80).lower()
    existing_graph_edge_count = s._source_collection_count(existing_graph_summary.get("edgeCount"))
    agent_graph = s._source_collection_stage_writeback_agent_graph_payload(
        result if isinstance(result, dict) else {}
    )
    claimed_graph_edge_count = len(s._source_collection_agent_graph_edges(agent_graph))
    relation_edges_need_reconciliation = claimed_graph_edge_count > 0 and existing_graph_edge_count <= 0
    should_reconcile_graph = (
        (
            s._normalize_source_collection_stage_id(task.get("stageId"), default="") == "relations"
            or s._normalize_source_collection_agent_role(task.get("agentRole")) == "source_relation_mapper"
        )
        and isinstance(result.get("candidateGraph"), dict)
    )
    if should_reconcile_graph and (
        not existing_graph_status
        or existing_graph_status == "failed"
        or relation_edges_need_reconciliation
    ):
        materialized_graph = s._materialize_source_collection_stage_writeback_candidate_graph(
            team_id,
            run_id,
            task,
            writeback,
        )
        next_writeback["materializedCandidateGraph"] = materialized_graph
        next_result["materializedCandidateGraph"] = materialized_graph
        changed = True

    existing_ingestion_summary = (
        writeback.get("materializedKnowledgeIngestion")
        if isinstance(writeback.get("materializedKnowledgeIngestion"), dict)
        else {}
    )
    existing_ingestion_status = s._trim_text(
        existing_ingestion_summary.get("status"), max_length=80
    ).lower()
    can_reconcile_ingestion = (
        s._source_collection_stage_can_materialize_formal_knowledge(
            s._normalize_source_collection_stage_id(task.get("stageId"), default=""),
            s._normalize_source_collection_agent_role(task.get("agentRole")),
        )
    )
    has_approved_ingestion_candidates = bool(
        s._source_collection_stage_writeback_approved_candidate_ids(result, writeback)
    )
    if (
        can_reconcile_ingestion
        and has_approved_ingestion_candidates
        and existing_ingestion_status
        in {
            "",
            "no_steward_pack",
            "source_quality_pending",
            "no_current_run_candidates",
        }
    ):
        materialized_ingestion = s._materialize_source_collection_stage_writeback_knowledge_ingestion(
            team_id,
            run_id,
            task,
            writeback,
        )
        next_writeback["materializedKnowledgeIngestion"] = materialized_ingestion
        next_result["materializedKnowledgeIngestion"] = materialized_ingestion
        changed = True
        s._record_workflow_event(
            "source_collection.stage_session_task_knowledge_ingestion_reconciled",
            team_id,
            fields={
                "runId": run_id,
                "taskId": s._trim_text(task.get("taskId"), max_length=160),
                "stageId": s._trim_text(task.get("stageId"), max_length=80),
                "agentId": s._trim_text(task.get("agentId"), max_length=160),
                "previousStatus": existing_ingestion_status or "missing",
                "status": s._trim_text(
                    materialized_ingestion.get("status"), max_length=80
                ),
                "approvedCandidateCount": s._source_collection_count(
                    materialized_ingestion.get("approvedCandidateCount")
                ),
                "formalKnowledgeItemCount": s._source_collection_count(
                    materialized_ingestion.get("formalKnowledgeItemCount")
                ),
            },
            level=(
                "warning"
                if s._trim_text(materialized_ingestion.get("status"), max_length=80)
                == "failed"
                else "info"
            ),
            outcome=(
                s._trim_text(materialized_ingestion.get("status"), max_length=80)
                or "reconciled"
            ),
            lifecycle=(
                s._trim_text(materialized_ingestion.get("status"), max_length=80)
                == "failed"
            ),
        )

    if not changed:
        return task
    next_task["writeback"] = next_writeback
    next_task["result"] = next_result
    next_task["updatedAt"] = s.utc_now_iso()
    return next_task


def _reconcile_source_collection_stage_session_task_completion_gate(
    team_id: str,
    run_id: str,
    task: dict[str, Any],
    *,
    conversation_events_by_session: dict[str, list[Any]] | None = None,
) -> dict[str, Any]:
    s = _service()
    writeback = task.get("writeback") if isinstance(task.get("writeback"), dict) else {}
    if not writeback:
        return task
    result = task.get("result") if isinstance(task.get("result"), dict) else {}
    coverage_summary = (
        writeback.get("coverageSummary")
        if isinstance(writeback.get("coverageSummary"), dict)
        else result.get("coverageSummary")
        if isinstance(result.get("coverageSummary"), dict)
        else {}
    )
    materialized_sources = (
        writeback.get("materializedSources")
        if isinstance(writeback.get("materializedSources"), dict)
        else result.get("materializedSources")
        if isinstance(result.get("materializedSources"), dict)
        else {}
    )
    materialized_content_extraction = (
        writeback.get("materializedContentExtraction")
        if isinstance(writeback.get("materializedContentExtraction"), dict)
        else result.get("materializedContentExtraction")
        if isinstance(result.get("materializedContentExtraction"), dict)
        else {}
    )
    materialized_source_quality = (
        writeback.get("materializedSourceQuality")
        if isinstance(writeback.get("materializedSourceQuality"), dict)
        else result.get("materializedSourceQuality")
        if isinstance(result.get("materializedSourceQuality"), dict)
        else {}
    )
    materialized_candidate_graph = (
        writeback.get("materializedCandidateGraph")
        if isinstance(writeback.get("materializedCandidateGraph"), dict)
        else result.get("materializedCandidateGraph")
        if isinstance(result.get("materializedCandidateGraph"), dict)
        else {}
    )
    materialized_knowledge_ingestion = (
        writeback.get("materializedKnowledgeIngestion")
        if isinstance(writeback.get("materializedKnowledgeIngestion"), dict)
        else result.get("materializedKnowledgeIngestion")
        if isinstance(result.get("materializedKnowledgeIngestion"), dict)
        else {}
    )
    closure_summary = s._source_collection_stage_writeback_closure_summary(
        task,
        writeback,
        coverage_summary=coverage_summary,
        materialized_sources=materialized_sources,
        materialized_content_extraction=materialized_content_extraction,
        materialized_source_quality=materialized_source_quality,
        materialized_candidate_graph=materialized_candidate_graph,
        materialized_knowledge_ingestion=materialized_knowledge_ingestion,
        conversation_events_by_session=conversation_events_by_session,
    )
    task_checklist = [
        item for item in list(task.get("taskChecklist") or [])
        if isinstance(item, dict)
    ]
    task_tool_progress = closure_summary.get("taskToolProgress") if isinstance(closure_summary.get("taskToolProgress"), dict) else {}
    completion_gate = s._source_collection_stage_completion_gate(
        task_checklist=task_checklist,
        artifact_complete=bool(closure_summary.get("artifactComplete")),
        task_checklist_complete=bool(closure_summary.get("taskChecklistComplete")),
    )
    closure_summary["completionGate"] = completion_gate
    closure_summary["completionGatePassed"] = bool(completion_gate.get("passed"))

    requested_status = s._trim_text(
        writeback.get("agentRequestedStatus") or writeback.get("requestedStatus") or writeback.get("status") or task.get("status"),
        max_length=80,
    ).lower()
    current_status = s._trim_text(task.get("status"), max_length=80).lower()
    next_status = current_status
    if requested_status == "completed":
        next_status = "completed" if completion_gate.get("passed") else "needs_review"
    elif current_status == "completed" and not completion_gate.get("passed"):
        next_status = "needs_review"

    existing_closure = (
        writeback.get("closureSummary")
        if isinstance(writeback.get("closureSummary"), dict)
        else result.get("closureSummary")
        if isinstance(result.get("closureSummary"), dict)
        else {}
    )
    if (
        existing_closure == closure_summary
        and task.get("taskToolProgress") == task_tool_progress
        and task.get("completionGate") == completion_gate
        and current_status == next_status
    ):
        return task

    next_task = dict(task)
    next_writeback = dict(writeback)
    next_result = dict(result)
    next_writeback.setdefault("agentRequestedStatus", requested_status or current_status)
    next_writeback["status"] = next_status
    next_writeback["closureSummary"] = closure_summary
    next_result["closureSummary"] = closure_summary
    next_task["status"] = next_status
    next_task["writeback"] = next_writeback
    next_task["result"] = next_result
    next_task["taskToolProgress"] = task_tool_progress or s._source_collection_stage_task_tool_progress(task_checklist)
    next_task["completionGate"] = completion_gate
    next_turn = next_task.get("turn") if isinstance(next_task.get("turn"), dict) else {}
    if next_turn:
        updated_turn = dict(next_turn)
        updated_turn["status"] = next_status
        next_task["turn"] = updated_turn
    next_task["updatedAt"] = s.utc_now_iso()
    if current_status != next_status:
        s._record_workflow_event(
            "source_collection.stage_session_task_completion_gate_reconciled",
            team_id,
            fields={
                "runId": run_id,
                "taskId": s._trim_text(task.get("taskId"), max_length=160),
                "stageId": s._trim_text(task.get("stageId"), max_length=80),
                "previousStatus": current_status,
                "status": next_status,
                "completionGatePassed": bool(completion_gate.get("passed")),
                "taskChecklistComplete": bool(completion_gate.get("taskChecklistComplete")),
                "artifactComplete": bool(completion_gate.get("artifactComplete")),
            },
            level="info",
            outcome=next_status,
            lifecycle=True,
        )
    return next_task


def _reconcile_source_collection_stage_session_task_from_turn_result(
    task: dict[str, Any],
    *,
    conversation_events_by_session: dict[str, list[Any]] | None = None,
) -> dict[str, Any]:
    s = _service()
    status = s._trim_text(task.get("status"), max_length=80).lower()
    if status not in {"running", "queued"}:
        return task
    turn = task.get("turn") if isinstance(task.get("turn"), dict) else {}
    turn_id = s._trim_text(turn.get("turnId"), max_length=200)
    session_id = s._trim_text(task.get("sessionId") or turn.get("sessionId"), max_length=160)
    agent_id = s._trim_text(task.get("agentId"), max_length=160)
    if not turn_id or not session_id or not agent_id:
        return task
    turn_result = s._source_collection_stage_session_task_turn_result(
        agent_id,
        session_id,
        turn_id,
        conversation_events_by_session=conversation_events_by_session,
    )
    if not turn_result:
        return task
    next_status = s._source_collection_stage_task_status_from_turn_result(turn_result)
    if next_status in {"running", "queued"}:
        return task
    now = s.utc_now_iso()
    next_task = dict(task)
    next_task["status"] = next_status
    next_task["summary"] = s._trim_text(turn_result.get("summary"), max_length=500) or s._trim_text(task.get("summary"), max_length=500)
    next_task["updatedAt"] = now
    next_task["reconciledFromTurn"] = {
        "turnId": turn_id,
        "status": s._trim_text(turn_result.get("status"), max_length=80),
        "resultEventId": s._trim_text(turn_result.get("eventId"), max_length=160),
        "createdAt": s._trim_text(turn_result.get("createdAt"), max_length=120),
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
    s._record_workflow_event(
        "source_collection_stage_session_task.reconciled_from_turn",
        s._trim_text(task.get("teamId"), max_length=128),
        fields={
            "runId": s._trim_text(task.get("runId"), max_length=128),
            "taskId": s._trim_text(task.get("taskId"), max_length=160),
            "stageId": s._trim_text(task.get("stageId"), max_length=80),
            "agentId": agent_id,
            "sessionId": session_id,
            "turnId": turn_id,
            "previousStatus": status,
            "status": next_status,
        },
    )
    return next_task


def _source_collection_stage_session_task_turn_result(
    agent_id: str,
    session_id: str,
    turn_id: str,
    *,
    conversation_events_by_session: dict[str, list[Any]] | None = None,
) -> dict[str, Any]:
    s = _service()
    events_path = s.developer_sandbox.seeded_sandbox_workspace_path(
        s._project_root(),
        "agents",
        s._safe_token(agent_id, default="agent", max_length=160),
        "events",
        "agent_turn_results.jsonl",
    )
    for item in reversed(s._read_jsonl(events_path)):
        if s._trim_text(item.get("runId"), max_length=200) != turn_id:
            continue
        if s._trim_text(item.get("sessionId"), max_length=160) != session_id:
            continue
        return item
    events = s._source_collection_stage_conversation_events(
        session_id,
        conversation_events_by_session=conversation_events_by_session,
    )
    ledger_result = s._source_collection_stage_session_task_turn_journal_result(session_id, turn_id, events=events)
    if ledger_result:
        return ledger_result
    snapshot_result = s._source_collection_stage_session_task_completion_snapshot_result(session_id, turn_id)
    if snapshot_result:
        return snapshot_result
    return {}


def _source_collection_stage_conversation_events(
    session_id: str,
    *,
    conversation_events_by_session: dict[str, list[Any]] | None = None,
) -> list[Any]:
    s = _service()
    normalized_session_id = s._trim_text(session_id, max_length=160)
    if not normalized_session_id:
        return []
    if conversation_events_by_session is not None and normalized_session_id in conversation_events_by_session:
        return conversation_events_by_session[normalized_session_id]
    try:
        events = s.load_conversation_events(s._project_root(), normalized_session_id)
    except Exception:
        events = []
    if conversation_events_by_session is not None:
        conversation_events_by_session[normalized_session_id] = events
    return events


def _source_collection_stage_session_task_turn_journal_result(
    session_id: str,
    turn_id: str,
    *,
    events: list[Any] | None = None,
) -> dict[str, Any]:
    s = _service()
    if events is None:
        events = s._source_collection_stage_conversation_events(session_id)
    normalized_turn_id = s._trim_text(turn_id, max_length=200)
    if not normalized_turn_id:
        return {}
    for event in reversed(events):
        event_turn_id = s._trim_text(getattr(event, "turn_id", ""), max_length=200)
        if event_turn_id != normalized_turn_id:
            continue
        event_type = s._trim_text(getattr(event, "event_type", ""), max_length=80)
        status = s._trim_text(getattr(event, "status", ""), max_length=80).lower()
        payload = getattr(event, "payload", {})
        if not isinstance(payload, dict):
            payload = {}
        next_status = ""
        fallback_summary = ""
        if event_type == "turn_interrupted" or (
            event_type == "assistant_message" and status in {"interrupted", "stopped"}
        ):
            next_status = "interrupted"
            fallback_summary = "Agent 私聊已中断，尚未完成阶段写回。"
        elif event_type == "assistant_message" and status in {"cancelled", "canceled", "superseded"}:
            next_status = "cancelled"
            fallback_summary = "Agent 私聊已取消。"
        elif event_type == "turn_failed" or (event_type == "assistant_message" and status in {"failed", "error"}):
            next_status = "failed"
            fallback_summary = "Agent 私聊执行失败。"
        if not next_status:
            continue
        return {
            "eventId": s._trim_text(getattr(event, "event_id", ""), max_length=160),
            "runId": normalized_turn_id,
            "sessionId": s._trim_text(session_id, max_length=160),
            "status": next_status,
            "summary": (
                s._trim_text(payload.get("summary"), max_length=500)
                or s._trim_text(payload.get("content"), max_length=500)
                or s._trim_text(payload.get("error"), max_length=500)
                or s._trim_text(payload.get("reason"), max_length=500)
                or fallback_summary
            ),
            "createdAt": s._trim_text(getattr(event, "timestamp", ""), max_length=120),
            "source": "conversation_ledger",
        }
    return {}


def _source_collection_stage_session_task_completion_snapshot_result(session_id: str, turn_id: str) -> dict[str, Any]:
    s = _service()
    try:
        snapshot = s.session_service.get_session_turn_completion_snapshot(session_id, turn_id)
    except Exception:
        return {}
    if not isinstance(snapshot, dict) or not bool(snapshot.get("terminal")):
        return {}
    terminal_status = s._trim_text(snapshot.get("terminalStatus") or snapshot.get("lastTurnStatus"), max_length=80).lower()
    if not terminal_status:
        return {}
    if terminal_status in {"running", "queued"} or bool(snapshot.get("isRunning")):
        return {}
    # ``lastTurnStatus`` is conversation-level state.  Without a message tied
    # to this turn it may describe an older completed turn while the current
    # background task has only emitted an intermediate tool failure.
    if snapshot.get("completionSource") == "last_turn_status" and not s._trim_text(
        snapshot.get("assistantText"), max_length=500
    ):
        return {}
    if terminal_status in {"failed", "failed_provider", "failed_runtime", "error"}:
        next_status = "failed"
        fallback_summary = "Agent 私聊执行失败。"
    elif terminal_status in {"cancelled", "canceled", "superseded"}:
        next_status = "cancelled"
        fallback_summary = "Agent 私聊已取消。"
    else:
        next_status = "interrupted"
        fallback_summary = "Agent 私聊已结束，但尚未完成阶段写回。"
    assistant_text = s._trim_text(snapshot.get("assistantText"), max_length=500)
    return {
        "eventId": s._trim_text(snapshot.get("completionSource"), max_length=160) or "session_completion_snapshot",
        "runId": s._trim_text(turn_id, max_length=200),
        "sessionId": s._trim_text(session_id, max_length=160),
        "status": next_status,
        "summary": assistant_text or fallback_summary,
        "createdAt": "",
        "source": "session_completion_snapshot",
    }


def _source_collection_stage_task_status_from_turn_result(turn_result: dict[str, Any]) -> str:
    s = _service()
    status = s._trim_text(turn_result.get("status"), max_length=80).lower()
    summary = s._trim_text(turn_result.get("summary"), max_length=2000).lower()
    if status in {"failed", "error", "failed_runtime", "failed_provider", "timeout"}:
        return "failed"
    if status in {"interrupted", "stopped", "stopped_by_user", "needs_continue"}:
        return "interrupted"
    if status in {"cancelled", "canceled", "superseded"}:
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
    s = _service()
    imported_record_ids: set[str] = set()
    for candidate in source_candidates:
        if not isinstance(candidate, dict):
            continue
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        imported_from = metadata.get("importedFromDataRecord") if isinstance(metadata.get("importedFromDataRecord"), dict) else {}
        record_id = s._trim_text(imported_from.get("recordId"), max_length=128)
        if record_id:
            imported_record_ids.add(record_id)

    def score(record: dict[str, Any]) -> tuple[int, str]:
        record_id = s._trim_text(record.get("recordId"), max_length=128)
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        source_ref = s._trim_text(record.get("sourceRef"), max_length=2000)
        raw_location = s._trim_text(record.get("rawLocation"), max_length=2000)
        quality = record.get("qualitySignals") if isinstance(record.get("qualitySignals"), dict) else {}
        value = 0
        if stage_id == "candidate" and record_id not in imported_record_ids:
            value += 60
        if s._source_collection_extract_doi(source_ref, raw_location, metadata.get("doi")):
            value += 30
        if s._looks_like_url(source_ref) or s._looks_like_url(raw_location):
            value += 20
        if s._trim_text(record.get("title"), max_length=240):
            value += 8
        if s._trim_text(record.get("summary"), max_length=1000):
            value += 8
        if quality:
            value += 4
        return (-value, s._trim_text(record.get("createdAt"), max_length=120) or record_id)

    return sorted([item for item in records if isinstance(item, dict)], key=score)


def _rank_source_collection_context_candidates(
    candidates: list[dict[str, Any]],
    *,
    stage_id: str,
) -> list[dict[str, Any]]:
    s = _service()
    def score(candidate: dict[str, Any]) -> tuple[int, str, str]:
        bucket = s._source_quality_bucket(candidate)
        value = 0
        if stage_id == "screening" and bucket == "pending":
            value -= 40
        elif stage_id == "screening" and bucket in {"needs_revision", "rejected"}:
            value -= 10
        title = s._trim_text(candidate.get("title"), max_length=240)
        if title:
            value -= 4
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        if s._trim_text(metadata.get("doi") or candidate.get("sourceUrl") or candidate.get("sourcePath"), max_length=1000):
            value -= 4
        return (
            value,
            s._trim_text(candidate.get("updatedAt"), max_length=120),
            s._trim_text(candidate.get("candidateId"), max_length=128),
        )

    return sorted([item for item in candidates if isinstance(item, dict)], key=score)


def _source_collection_context_run_summary(
    run: dict[str, Any],
    run_status: dict[str, Any],
    active_work_run: dict[str, Any],
) -> dict[str, Any]:
    s = _service()
    scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
    metadata = run.get("metadata") if isinstance(run.get("metadata"), dict) else {}
    summary = run_status.get("summary") if isinstance(run_status.get("summary"), dict) else {}
    return {
        "runId": s._trim_text(run.get("runId"), max_length=128),
        "title": s._trim_text(run.get("title") or metadata.get("title") or scope.get("topic"), max_length=240),
        "topic": s._trim_text(scope.get("topic"), max_length=240),
        "goal": s._trim_text(scope.get("goal"), max_length=500),
        "status": s._trim_text(run.get("status") or run_status.get("status") or active_work_run.get("status"), max_length=80),
        "currentPhase": s._trim_text(active_work_run.get("currentPhase") or summary.get("currentPhase"), max_length=120),
        "summary": s._trim_text(active_work_run.get("summary") or summary.get("summary"), max_length=500),
    }


def _source_collection_context_task_summary(task: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    if not task:
        return {}
    result = task.get("result") if isinstance(task.get("result"), dict) else {}
    writeback = task.get("writeback") if isinstance(task.get("writeback"), dict) else {}
    closure_summary = (
        writeback.get("closureSummary")
        if isinstance(writeback.get("closureSummary"), dict)
        else result.get("closureSummary") if isinstance(result.get("closureSummary"), dict) else {}
    )
    return {
        "taskId": s._trim_text(task.get("taskId"), max_length=160),
        "stageId": s._trim_text(task.get("stageId"), max_length=80),
        "agentId": s._trim_text(task.get("agentId"), max_length=160),
        "agentRole": s._trim_text(task.get("agentRole"), max_length=80),
        "sessionId": s._trim_text(task.get("sessionId"), max_length=160),
        "status": s._trim_text(task.get("status"), max_length=80),
        "title": s._trim_text(task.get("title"), max_length=240),
        "summary": s._trim_text(task.get("summary"), max_length=500),
        "createdAt": s._trim_text(task.get("createdAt"), max_length=120),
        "updatedAt": s._trim_text(task.get("updatedAt"), max_length=120),
        "taskToolProgress": task.get("taskToolProgress") if isinstance(task.get("taskToolProgress"), dict) else {},
        "completionGate": task.get("completionGate") if isinstance(task.get("completionGate"), dict) else {},
        "closureSummary": closure_summary,
    }


def _source_collection_context_assignment_summary(assignment: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    return {
        "assignmentId": s._trim_text(assignment.get("assignmentId"), max_length=128),
        "agentId": s._trim_text(assignment.get("agentId"), max_length=160),
        "agentRole": s._trim_text(assignment.get("agentRole"), max_length=80),
        "status": s._trim_text(assignment.get("status"), max_length=80),
        "purpose": s._trim_text(assignment.get("purpose"), max_length=500),
    }


def _source_collection_context_record_summary(record: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    metadata_trace = metadata.get("sourceCollectionTrace") if isinstance(metadata.get("sourceCollectionTrace"), dict) else {}
    record_trace = record.get("collectionTrace") if isinstance(record.get("collectionTrace"), dict) else {}
    trace = {**record_trace, **metadata_trace}
    source_ref = s._trim_text(record.get("sourceRef"), max_length=1000)
    raw_location = s._trim_text(record.get("rawLocation"), max_length=1000)
    doi = s._source_collection_extract_doi(source_ref, raw_location, metadata.get("doi"))
    source_url = source_ref if s._looks_like_url(source_ref) else (raw_location if s._looks_like_url(raw_location) else "")
    return {
        "recordId": s._trim_text(record.get("recordId"), max_length=128),
        "title": s._trim_text(record.get("title"), max_length=240),
        "summary": s._trim_text(record.get("summary"), max_length=1200),
        "sourceType": s._trim_text(record.get("sourceType"), max_length=80),
        "sourceRef": source_ref,
        "rawLocation": raw_location,
        "sourceUrl": source_url,
        "doi": doi,
        "containerTitle": s._trim_text(metadata.get("containerTitle"), max_length=240),
        "issued": s._trim_text(metadata.get("issued"), max_length=80),
        "searchProvider": s._trim_text(metadata.get("searchProvider") or trace.get("searchProvider"), max_length=80),
        "query": s._trim_text(trace.get("query") or metadata.get("query"), max_length=500),
        "assignmentId": s._trim_text(trace.get("assignmentId") or metadata.get("assignmentId"), max_length=128),
        "identityKey": s._source_collection_record_identity_key(record),
        "qualitySignals": s._normalize_metadata(record.get("qualitySignals")),
    }


def _source_collection_context_candidate_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    imported_from = metadata.get("importedFromDataRecord") if isinstance(metadata.get("importedFromDataRecord"), dict) else {}
    content_extraction = metadata.get("contentExtraction") if isinstance(metadata.get("contentExtraction"), dict) else {}
    return {
        "candidateId": s._trim_text(candidate.get("candidateId"), max_length=128),
        "candidateType": s._trim_text(candidate.get("candidateType"), max_length=80),
        "title": s._trim_text(candidate.get("title"), max_length=240),
        "summary": s._trim_text(candidate.get("summary"), max_length=1200),
        "sourceKind": s._trim_text(candidate.get("sourceKind"), max_length=80),
        "sourceUrl": s._trim_text(candidate.get("sourceUrl") or metadata.get("sourceUrl"), max_length=1000),
        "sourcePath": s._trim_text(candidate.get("sourcePath") or metadata.get("sourcePath"), max_length=1000),
        "doi": s._trim_text(metadata.get("doi") or imported_from.get("doi"), max_length=240),
        "sourceRecordId": s._trim_text(metadata.get("sourceRecordId") or imported_from.get("recordId"), max_length=128),
        "sourceIdentityKey": s._trim_text(metadata.get("sourceIdentityKey") or imported_from.get("sourceIdentityKey"), max_length=160),
        "status": s._trim_text(candidate.get("status"), max_length=80),
        "currentState": s._trim_text(candidate.get("currentState"), max_length=80),
        "qualityStatus": s._trim_text(candidate.get("qualityStatus"), max_length=80),
        "qualityBucket": s._source_quality_bucket(candidate),
        "latestAssessment": s._normalize_metadata(s._candidate_source_quality_assessment(candidate) or {}),
        "contentExtraction": s._normalize_metadata(content_extraction),
        "validation": s._normalize_metadata(candidate.get("validation")),
    }


def _source_collection_stage_retry_focus(
    task: dict[str, Any],
    candidates: list[dict[str, Any]],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    s = _service()
    if not isinstance(task, dict) or not task:
        return {}
    coverage = s._source_collection_stage_task_coverage_summary(task)
    if not isinstance(coverage, dict) or not bool(coverage.get("applicable")) or bool(coverage.get("complete")):
        return {}
    candidate_ids = {
        s._trim_text(item.get("candidateId"), max_length=160)
        for item in candidates
        if s._trim_text(item.get("candidateId"), max_length=160)
    }
    record_ids = {
        s._trim_text(item.get("recordId"), max_length=160)
        for item in records
        if s._trim_text(item.get("recordId"), max_length=160)
    }
    missing_candidate_ids = [
        item
        for item in s._normalize_text_list(coverage.get("missingCandidateIds"), max_items=500, max_length=160)
        if item in candidate_ids
    ]
    missing_record_ids = [
        item
        for item in s._normalize_text_list(coverage.get("missingRecordIds"), max_items=500, max_length=160)
        if item in record_ids
    ]
    if not missing_candidate_ids and not missing_record_ids:
        return {}
    return {
        "mode": "missing_stage_coverage",
        "sourceTaskId": s._trim_text(task.get("taskId"), max_length=160),
        "coverageKind": s._trim_text(coverage.get("coverageKind"), max_length=80),
        "total": s._source_collection_count(coverage.get("total")),
        "processed": s._source_collection_count(coverage.get("processed")),
        "missing": s._source_collection_count(coverage.get("missing")),
        "invalid": s._source_collection_count(coverage.get("invalid")),
        "missingCandidateIds": missing_candidate_ids[:120],
        "missingRecordIds": missing_record_ids[:120],
        "retryInstruction": "只补这些缺失 ID；不要重新处理 processedCandidateIds / processedRecordIds。",
    }


def _source_collection_stage_evidence_retry_focus(
    task: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    s = _service()
    if not isinstance(task, dict) or not task:
        return {}
    coverage = s._source_collection_stage_task_coverage_summary(task)
    blocked_ids = set(
        s._normalize_text_list(coverage.get("blockedCandidateIds"), max_items=500, max_length=160)
        if isinstance(coverage, dict)
        else []
    )
    evidence_gap_ids: list[str] = []
    for candidate in candidates:
        candidate_id = s._trim_text(candidate.get("candidateId"), max_length=160)
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        extraction = metadata.get("contentExtraction") if isinstance(metadata.get("contentExtraction"), dict) else {}
        evidence_ledger = (
            extraction.get("evidenceLedger")
            if isinstance(extraction.get("evidenceLedger"), dict)
            else {}
        )
        evidence_ready = (
            s._trim_text(extraction.get("evidenceStatus"), max_length=80) == "evidence_ready"
            or s._trim_text(evidence_ledger.get("status"), max_length=80) == "evidence_ready"
            or s._source_collection_extraction_has_evidence_anchor(extraction)
            or s._source_collection_extraction_has_evidence_anchor(evidence_ledger)
        )
        explicit_gap = s._trim_text(extraction.get("evidenceStatus"), max_length=80) == "missing_evidence_anchor"
        if candidate_id and not evidence_ready and (explicit_gap or candidate_id in blocked_ids):
            evidence_gap_ids.append(candidate_id)
    if not evidence_gap_ids:
        return {}
    return {
        "mode": "missing_evidence_anchor",
        "sourceTaskId": s._trim_text(task.get("taskId"), max_length=160),
        "missingEvidenceAnchorCount": len(evidence_gap_ids),
        "evidenceGapCandidateIds": evidence_gap_ids[:120],
        "retryInstruction": "只补这些候选的证据锚点；不要重做已有 evidence_ready 结果，也不要把摘要元数据写成全文证据。",
    }


def _find_source_collection_stage_session_task(team_id: str, run_id: str, *, idempotency_key: str) -> dict[str, Any] | None:
    s = _service()
    key = s._trim_text(idempotency_key, max_length=240)
    if not key:
        return None
    for item in s._source_collection_stage_session_tasks(team_id, run_id):
        if s._trim_text(item.get("idempotencyKey"), max_length=240) == key:
            return item
    return None


def _find_source_collection_stage_session_task_by_id(team_id: str, task_id: str) -> tuple[dict[str, Any] | None, str]:
    s = _service()
    normalized_task_id = s._trim_text(task_id, max_length=160)
    if not normalized_task_id:
        return None, ""
    # 跨项目根扫描：账本可能存于任一研究项目的 workspace（含修复前错位落盘）。
    for runs_root in s._source_collection_task_store_search_roots(team_id):
        if not runs_root.exists():
            continue
        for path in runs_root.glob("*/stage_session_tasks.json"):
            run_id = path.parent.name
            store = s._read_json(path)
            for item in list(store.get("tasks") or []):
                if isinstance(item, dict) and s._trim_text(item.get("taskId"), max_length=160) == normalized_task_id:
                    return item, run_id
    return None, ""


def _upsert_source_collection_stage_session_task(team_id: str, run_id: str, task: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    task_id = s._trim_text(task.get("taskId"), max_length=160)
    if not task_id:
        raise s.TeamWorkflowOrchestrationError("Stage session task id is required.")
    with s._WORKFLOW_LOCK:
        store = s._load_source_collection_stage_session_task_store(team_id, run_id)
        tasks = [item for item in list(store.get("tasks") or []) if isinstance(item, dict)]
        next_tasks: list[dict[str, Any]] = []
        replaced = False
        for item in tasks:
            if s._trim_text(item.get("taskId"), max_length=160) == task_id:
                next_tasks.append(dict(task))
                replaced = True
            else:
                next_tasks.append(item)
        if not replaced:
            next_tasks.append(dict(task))
        store["tasks"] = next_tasks
        s._write_source_collection_stage_session_task_store(team_id, run_id, store)
    return task


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
    s = _service()
    key_scope = f"{team_id}:{run_id}:{stage_id}:{agent_id}:{agent_role or 'agent'}"
    if requested_key:
        key_digest = hashlib.sha256(requested_key.encode("utf-8", errors="replace")).hexdigest()[:24]
        return s._trim_text(f"stage_task:{key_scope}:request:{key_digest}", max_length=240)
    return s._trim_text(f"stage_task:{key_scope}:task:{task_id}", max_length=240)


def _source_collection_stage_task_tool_progress_from_trace(
    task: dict[str, Any],
    task_checklist: list[dict[str, Any]] | None,
    *,
    artifact_complete: bool = False,
    conversation_events_by_session: dict[str, list[Any]] | None = None,
) -> dict[str, Any]:
    s = _service()
    checklist = [item for item in list(task_checklist or []) if isinstance(item, dict)]
    progress = s._source_collection_stage_task_tool_progress(checklist)
    if not checklist:
        progress.update({"traceAvailable": False, "taskCreateObserved": False, "toolCallCount": 0})
        return progress
    turn = task.get("turn") if isinstance(task.get("turn"), dict) else {}
    session_id = s._trim_text(task.get("sessionId") or turn.get("sessionId"), max_length=160)
    turn_id = s._trim_text(turn.get("turnId"), max_length=200)
    if not session_id:
        progress.update({"traceAvailable": False, "taskCreateObserved": False, "toolCallCount": 0})
        return progress
    try:
        events = s._source_collection_stage_conversation_events(
            session_id,
            conversation_events_by_session=conversation_events_by_session,
        )
    except Exception as exc:  # pragma: no cover - defensive for corrupt ledgers
        progress.update(
            {
                "traceAvailable": False,
                "traceError": s._trim_text(str(exc), max_length=240),
                "taskCreateObserved": False,
                "toolCallCount": 0,
            }
        )
        return progress
    start_sequence = s._source_collection_stage_task_trace_start_sequence(events, task)
    end_sequence = s._source_collection_stage_task_trace_end_sequence(events, task, start_sequence)
    tool_calls: list[dict[str, Any]] = []
    for event in events:
        sequence = s._normalize_int(getattr(event, "sequence", 0), default=0, minimum=0, maximum=10_000_000)
        if start_sequence:
            if sequence and sequence < start_sequence:
                continue
            if end_sequence and sequence and sequence >= end_sequence:
                continue
        else:
            event_turn_id = s._trim_text(getattr(event, "turn_id", ""), max_length=200)
            if turn_id and event_turn_id and event_turn_id != turn_id:
                continue
        tool_calls.extend(s._source_collection_stage_tool_calls_from_event(event))

    checklist_binding = task.get("checklistBinding") if isinstance(task.get("checklistBinding"), dict) else {}
    if s._trim_text(checklist_binding.get("mode"), max_length=80) == "stage_task":
        successful_tool_names = {
            s._source_collection_stage_tool_call_name(tool_call)
            for tool_call in tool_calls
            if s._source_collection_stage_tool_call_succeeded(tool_call)
        }
        attempted_tool_names = {
            s._source_collection_stage_tool_call_name(tool_call)
            for tool_call in tool_calls
        }
        persisted_writeback_after_turn = s._source_collection_stage_persisted_writeback_after_turn(task)
        writeback_observed = (
            "source_collection_stage_writeback_tool" in successful_tool_names
            or persisted_writeback_after_turn
        )
        task_create_observed = False
        completed_ids: set[str] = set()
        checklist_by_id = {
            s._trim_text(item.get("id"), max_length=120): item
            for item in checklist
            if s._trim_text(item.get("id"), max_length=120)
        }
        checklist_by_order = {
            s._normalize_int(item.get("order"), default=index, minimum=1, maximum=1000): item
            for index, item in enumerate(checklist, start=1)
        }
        for tool_call in tool_calls:
            name = s._source_collection_stage_tool_call_name(tool_call)
            if not s._source_collection_stage_tool_call_succeeded(tool_call):
                continue
            if name == "task_create_tool":
                task_create_observed = True
                continue
            if name != "task_update_tool":
                continue
            args = s._source_collection_stage_tool_call_args(tool_call)
            if s._normalize_optional_bool(args.get("is_completed") or args.get("isCompleted")) is not True:
                continue
            item_id = s._source_collection_stage_task_tool_item_id(args, checklist_by_id, checklist_by_order)
            if item_id:
                completed_ids.add(item_id)
        for item in checklist:
            item_id = s._trim_text(item.get("id"), max_length=120)
            required_tool = s._trim_text(item.get("requiredTool"), max_length=160)
            if not item_id:
                continue
            if required_tool == "source_collection_stage_writeback_tool":
                item_complete = bool(writeback_observed and artifact_complete)
            elif required_tool:
                item_complete = (
                    required_tool in attempted_tool_names
                    if required_tool == "web_fetch_tool"
                    else required_tool in successful_tool_names
                )
                if (
                    not item_complete
                    and required_tool == "batch_web_search_tool"
                    and writeback_observed
                    and artifact_complete
                ):
                    item_complete = True
                if item_complete and "page" in item_id:
                    # finding 的 page_existing_sources 已改为单读语义：一次成功的
                    # source_collection_context_tool 调用即勾，不再要求翻页读完或等
                    # 产物完成；extraction 的 page_candidate_inputs 保持原门禁。
                    item_complete = (
                        True
                        if item_id == "page_existing_sources"
                        else bool(artifact_complete)
                    )
            else:
                item_complete = bool(writeback_observed and artifact_complete)
            if item_complete:
                completed_ids.add(item_id)
        progress = s._source_collection_stage_task_tool_progress(checklist, completed_ids=completed_ids)
        progress.update(
            {
                "traceAvailable": True,
                "bindingMode": "stage_task",
                "taskCreateObserved": task_create_observed,
                "toolCallCount": len(tool_calls),
                "completedByEvidence": progress.get("completed", 0),
                "artifactComplete": bool(artifact_complete),
            }
        )
        call_sources = {
            s._trim_text(tool_call.get("__source"), max_length=80)
            for tool_call in tool_calls
            if s._trim_text(tool_call.get("__source"), max_length=80)
        }
        if call_sources:
            progress["sources"] = sorted(call_sources)
            if call_sources == {"feedback_events"}:
                progress["source"] = "feedback_events"
        if persisted_writeback_after_turn:
            progress["persistedWritebackAfterTurn"] = True
            progress["source"] = "persisted_writeback_after_turn"
            progress["sources"] = sorted({*progress.get("sources", []), "persisted_writeback_after_turn"})
        if not progress.get("complete"):
            progress["pendingReason"] = "stage_evidence_incomplete"
        return progress

    task_create_observed = False
    completed_ids: set[str] = set()
    checklist_by_id = {
        s._trim_text(item.get("id"), max_length=120): item
        for item in checklist
        if s._trim_text(item.get("id"), max_length=120)
    }
    checklist_by_order = {
        s._normalize_int(item.get("order"), default=index, minimum=1, maximum=1000): item
        for index, item in enumerate(checklist, start=1)
    }
    for tool_call in tool_calls:
        name = s._source_collection_stage_tool_call_name(tool_call)
        if name not in {"task_create_tool", "task_update_tool"}:
            continue
        if not s._source_collection_stage_tool_call_succeeded(tool_call):
            continue
        args = s._source_collection_stage_tool_call_args(tool_call)
        if name == "task_create_tool":
            task_create_observed = True
            continue
        if s._normalize_optional_bool(args.get("is_completed") or args.get("isCompleted")) is not True:
            continue
        item_id = s._source_collection_stage_task_tool_item_id(args, checklist_by_id, checklist_by_order)
        if item_id:
            completed_ids.add(item_id)

    progress = s._source_collection_stage_task_tool_progress(checklist, completed_ids=completed_ids)
    call_sources = {
        s._trim_text(tool_call.get("__source"), max_length=80)
        for tool_call in tool_calls
        if s._trim_text(tool_call.get("__source"), max_length=80)
    }
    progress.update(
        {
            "traceAvailable": True,
            "taskCreateObserved": task_create_observed,
            "toolCallCount": len(tool_calls),
            "completedByTrace": progress.get("completed", 0),
        }
    )
    if call_sources:
        progress["sources"] = sorted(call_sources)
        if call_sources == {"feedback_events"}:
            progress["source"] = "feedback_events"
    progress["complete"] = bool(progress.get("complete")) and task_create_observed
    if not task_create_observed:
        progress["pendingReason"] = "task_create_tool_not_observed"
    elif not progress["complete"]:
        progress["pendingReason"] = "task_update_tool_items_pending"
    return progress


def _source_collection_stage_persisted_writeback_after_turn(task: dict[str, Any]) -> bool:
    s = _service()
    writeback = task.get("writeback") if isinstance(task.get("writeback"), dict) else {}
    reconciled_from_turn = (
        task.get("reconciledFromTurn")
        if isinstance(task.get("reconciledFromTurn"), dict)
        else {}
    )
    if not writeback or not reconciled_from_turn:
        return False
    reconciled_status = s._trim_text(reconciled_from_turn.get("status"), max_length=80).lower()
    if reconciled_status not in {"completed", "interrupted", "needs_continue", "needs_review"}:
        return False
    recorded_at = s._trim_text(writeback.get("recordedAt"), max_length=120)
    reconciled_at = s._trim_text(reconciled_from_turn.get("reconciledAt"), max_length=120)
    return bool(recorded_at and reconciled_at and recorded_at >= reconciled_at)


def _source_collection_stage_task_trace_start_sequence(events: list[Any], task: dict[str, Any]) -> int:
    s = _service()
    if not isinstance(task, dict):
        return 0
    task_id = s._trim_text(task.get("taskId"), max_length=160)
    turn = task.get("turn") if isinstance(task.get("turn"), dict) else {}
    turn_id = s._trim_text(turn.get("turnId"), max_length=200)
    fallback_sequence = 0
    for event in events:
        sequence = s._normalize_int(getattr(event, "sequence", 0), default=0, minimum=0, maximum=10_000_000)
        metadata = s._source_collection_stage_event_metadata(event)
        event_task_id = s._trim_text(metadata.get("sourceCollectionStageTaskId"), max_length=160)
        if task_id and event_task_id == task_id:
            return sequence
        event_turn_id = s._trim_text(getattr(event, "turn_id", ""), max_length=200)
        if not fallback_sequence and turn_id and event_turn_id == turn_id:
            fallback_sequence = sequence
    return fallback_sequence


def _source_collection_stage_task_trace_end_sequence(
    events: list[Any],
    task: dict[str, Any],
    start_sequence: int,
) -> int:
    s = _service()
    if not start_sequence or not isinstance(task, dict):
        return 0
    task_id = s._trim_text(task.get("taskId"), max_length=160)
    for event in events:
        sequence = s._normalize_int(getattr(event, "sequence", 0), default=0, minimum=0, maximum=10_000_000)
        if sequence <= start_sequence:
            continue
        metadata = s._source_collection_stage_event_metadata(event)
        if s._trim_text(metadata.get("kind"), max_length=120) != s.SOURCE_COLLECTION_STAGE_SESSION_TASK_KIND:
            continue
        event_task_id = s._trim_text(metadata.get("sourceCollectionStageTaskId"), max_length=160)
        if event_task_id and event_task_id != task_id:
            return sequence
    return 0


def _source_collection_stage_event_metadata(event: Any) -> dict[str, Any]:
    s = _service()
    payload = getattr(event, "payload", {}) if event is not None else {}
    if not isinstance(payload, dict):
        return {}
    for raw in (
        payload.get("metadata"),
        (payload.get("message") if isinstance(payload.get("message"), dict) else {}).get("metadata"),
        (payload.get("content") if isinstance(payload.get("content"), dict) else {}).get("metadata"),
    ):
        if isinstance(raw, dict):
            return dict(raw)
    return {}


def _source_collection_stage_tool_calls_from_event(event: Any) -> list[dict[str, Any]]:
    s = _service()
    payload = getattr(event, "payload", {}) if event is not None else {}
    if not isinstance(payload, dict):
        return []
    raw_calls: list[Any] = []
    for key in ("toolCall", "tool_call"):
        if isinstance(payload.get(key), dict):
            raw_calls.append(payload[key])
    for key in ("toolCalls", "tool_calls", "tools"):
        if isinstance(payload.get(key), list):
            raw_calls.extend(payload[key])
    message = payload.get("message") if isinstance(payload.get("message"), dict) else {}
    if message:
        for key in ("toolCall", "tool_call"):
            if isinstance(message.get(key), dict):
                raw_calls.append(message[key])
        for key in ("toolCalls", "tool_calls", "tools"):
            if isinstance(message.get(key), list):
                raw_calls.extend(message[key])
    if not raw_calls and s._source_collection_stage_tool_call_name(payload):
        raw_calls.append(payload)
    raw_feedback_events: list[Any] = []
    for key in ("feedbackEvents", "feedback_events"):
        if isinstance(payload.get(key), list):
            raw_feedback_events.extend(payload[key])
        if isinstance(message.get(key), list):
            raw_feedback_events.extend(message[key])

    event_type = s._trim_text(getattr(event, "event_type", ""), max_length=80)
    normalized_calls: list[dict[str, Any]] = []
    for raw in raw_calls:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        if event_type:
            item.setdefault("__eventType", event_type)
        normalized_calls.append(item)
    for raw in raw_feedback_events:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        if s._trim_text(item.get("kind"), max_length=80).lower() != "tool":
            continue
        if not s._source_collection_stage_tool_call_name(item):
            continue
        if event_type:
            item.setdefault("__eventType", event_type)
        item["__source"] = "feedback_events"
        normalized_calls.append(item)
    return normalized_calls


def _source_collection_stage_tool_call_name(tool_call: dict[str, Any]) -> str:
    s = _service()
    if not isinstance(tool_call, dict):
        return ""
    return s._trim_text(tool_call.get("name") or tool_call.get("toolName") or tool_call.get("tool_name"), max_length=160)


def _source_collection_stage_tool_call_args(tool_call: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    if not isinstance(tool_call, dict):
        return {}
    raw_args = tool_call.get("args")
    if raw_args is None:
        raw_args = tool_call.get("arguments")
    if isinstance(raw_args, dict):
        return dict(raw_args)
    if isinstance(raw_args, str):
        text = raw_args.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def _source_collection_stage_tool_call_succeeded(tool_call: dict[str, Any]) -> bool:
    s = _service()
    if not isinstance(tool_call, dict):
        return False
    status = s._trim_text(
        tool_call.get("status")
        or tool_call.get("semanticStatus")
        or tool_call.get("semantic_status")
        or tool_call.get("transportStatus")
        or tool_call.get("transport_status"),
        max_length=80,
    ).lower()
    if status in {"failed", "failure", "error", "timeout", "timed_out", "blocked", "cancelled", "canceled", "no_result", "interrupted"}:
        return False
    if status in {"done", "success", "succeeded", "completed", "finished", "ready", "degraded", "observed", "returned"}:
        return True
    event_type = s._trim_text(tool_call.get("__eventType"), max_length=80)
    has_result = any(str(tool_call.get(key) or "").strip() for key in ("result", "summary", "resultPreview", "result_preview"))
    return event_type == "tool_result" and has_result


def _source_collection_stage_task_tool_item_id(
    args: dict[str, Any],
    checklist_by_id: dict[str, dict[str, Any]],
    checklist_by_order: dict[int, dict[str, Any]],
) -> str:
    s = _service()
    raw_task_id = args.get("task_id")
    if raw_task_id is None:
        raw_task_id = args.get("taskId")
    if raw_task_id is None:
        raw_task_id = args.get("id")
    task_id = s._trim_text(raw_task_id, max_length=160)
    if task_id in checklist_by_id:
        return task_id
    match = re.search(r"\d+", task_id)
    if match:
        item = checklist_by_order.get(s._normalize_int(match.group(0), default=0, minimum=0, maximum=1000))
        item_id = s._trim_text(item.get("id") if isinstance(item, dict) else "", max_length=120)
        if item_id:
            return item_id
    description = s._trim_text(args.get("description"), max_length=500)
    if description:
        for item_id, item in checklist_by_id.items():
            if description == s._trim_text(item.get("description"), max_length=500):
                return item_id
    return ""


def _source_collection_stage_task_chat_route(session_id: str, *, return_to: str, return_label: str) -> str:
    s = _service()
    params = urllib.parse.urlencode(
        {
            key: value
            for key, value in {
                "session": s._trim_text(session_id, max_length=160),
                "returnTo": s._trim_text(return_to, max_length=1000),
                "returnLabel": s._trim_text(return_label, max_length=240),
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
    s = _service()
    run_scope = run.get("scope") if isinstance(run.get("scope"), dict) else {}
    run_metadata = run.get("metadata") if isinstance(run.get("metadata"), dict) else {}
    status_summary = run_status.get("summary") if isinstance(run_status.get("summary"), dict) else {}
    assignment_summary = s._source_collection_assignment_stage_summary(assignments)
    open_matching_assignments = s._source_collection_open_assignments(matching_assignments)
    stage_label = {
        "finding": "资料寻找",
        "extraction": "资料提炼",
        "relations": "资料关系整理",
        "ingestion": "资料入库",
    }.get(stage_id, stage_id)
    role_label = {
        "source_finder": "资料寻找 Agent",
        "source_extractor": "资料提炼 Agent",
        "source_relation_mapper": "资料关系整理 Agent",
        "source_ingestor": "资料入库 Agent",
    }.get(agent_role, agent_role or "未标注")
    active_summary = s._trim_text(active_work_run.get("summary"), max_length=240) if active_work_run else ""
    run_title = s._trim_text(run.get("title") or run_scope.get("topic") or run_metadata.get("title"), max_length=180)
    topic = s._trim_text(run_scope.get("topic"), max_length=240)
    goal = s._trim_text(run_scope.get("goal"), max_length=320)
    agent_name = s._trim_text(agent.get("displayName") or agent.get("name") or agent.get("id"), max_length=160)
    lines = [
        "## 知识搜集上下文",
        f"- 团队：{s._trim_text(team.get('name') or team.get('teamId'), max_length=160)}",
        f"- 当前 Agent：{agent_name}",
        f"- 当前阶段：{stage_label}",
        f"- 角色：{role_label}",
        f"- 运行：{s._trim_text(run.get('runId'), max_length=160)}",
    ]
    if run_title:
        lines.append(f"- 标题：{run_title}")
    if topic:
        lines.append(f"- 主题：{topic}")
    if goal:
        lines.append(f"- 目标：{goal}")
    status_text = s._trim_text(run.get("status") or run_status.get("status") or active_work_run.get("status"), max_length=80)
    phase_text = s._trim_text(active_work_run.get("currentPhase") or status_summary.get("currentPhase"), max_length=80)
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
    next_actions = s._source_collection_agent_context_next_actions(stage_id, len(records), len(source_candidates), len(open_matching_assignments))
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


def _source_collection_stage_previous_attempt_lines(previous_task: dict[str, Any] | None) -> list[str]:
    s = _service()
    if not isinstance(previous_task, dict) or not previous_task:
        return []
    writeback = previous_task.get("writeback") if isinstance(previous_task.get("writeback"), dict) else {}
    result = previous_task.get("result") if isinstance(previous_task.get("result"), dict) else {}
    closure = (
        writeback.get("closureSummary")
        if isinstance(writeback.get("closureSummary"), dict)
        else result.get("closureSummary") if isinstance(result.get("closureSummary"), dict) else {}
    )
    task_status = s._trim_text(previous_task.get("status"), max_length=80)
    user_status = s._trim_text(closure.get("userStatus"), max_length=80)
    if user_status == "success" or (task_status in {"completed", "closed_loop"} and not closure):
        return []
    if not closure and task_status not in {"interrupted", "needs_review", "blocked", "failed"}:
        return []
    coverage = (
        closure.get("coverageSummary")
        if isinstance(closure.get("coverageSummary"), dict)
        else s._source_collection_stage_task_coverage_summary(previous_task)
    )
    invalid_ids = list(closure.get("invalidIds") or [])
    if not invalid_ids and isinstance(coverage, dict):
        invalid_ids = [
            *list(coverage.get("invalidRecordIds") or []),
            *list(coverage.get("invalidCandidateIds") or []),
        ]
    progress = s._trim_text(closure.get("progressLabel"), max_length=200)
    if not progress and isinstance(coverage, dict) and coverage:
        stage_id = s._normalize_source_collection_stage_id(previous_task.get("stageId"), default="")
        action = "提炼" if stage_id == "extraction" else "处理"
        progress = f"{action} {s._source_collection_count(coverage.get('processed'))}/{s._source_collection_count(coverage.get('total'))}"
    message = s._trim_text(closure.get("message"), max_length=700) or s._trim_text(previous_task.get("summary"), max_length=700)
    retry_instruction = s._trim_text(closure.get("retryInstruction") or closure.get("nextAction"), max_length=1000)
    status_label = "已中断，需要继续" if task_status == "interrupted" else (task_status or user_status or "unknown")
    lines = [
        "## 上一轮结果",
        f"- 上一轮任务：{s._trim_text(previous_task.get('taskId'), max_length=160)}；状态：{status_label}。",
    ]
    if progress:
        lines.append(f"- 覆盖进度：{progress}。")
    if message:
        reason_label = "中断/待补原因" if task_status == "interrupted" else "失败/待补原因"
        lines.append(f"- {reason_label}：{message}")
    normalized_invalid_ids = [s._trim_text(item, max_length=160) for item in invalid_ids[:8] if s._trim_text(item, max_length=160)]
    if normalized_invalid_ids:
        lines.append("- 未匹配 ID：" + "、".join(normalized_invalid_ids))
    missing_ids: list[str] = []
    if isinstance(coverage, dict):
        missing_ids = [
            *s._normalize_text_list(coverage.get("missingCandidateIds"), max_items=8, max_length=160),
            *s._normalize_text_list(coverage.get("missingRecordIds"), max_items=8, max_length=160),
        ][:8]
    if missing_ids:
        lines.append("- 待补 ID：" + "、".join(missing_ids))
    if retry_instruction:
        lines.append(f"- 本轮重试建议：{retry_instruction}")
    lines.append("- 本轮必须基于工具返回的真实 recordId/candidateId 重新覆盖缺口，不要复用上一轮短 ID 或聚合占位符。")
    return lines


# Link audit A2: finding retry attempts re-ran queries the previous attempt
# had already searched and judged invalid (observed as a 17-step DOI guess
# spiral). The injected memory is strictly bounded so it cannot bloat the
# prompt across deep retry chains.
_FINDING_QUERY_MEMORY_MAX_ITEMS = 30
_FINDING_QUERY_MEMORY_ITEM_MAX_LENGTH = 200
_FINDING_QUERY_MEMORY_REASON_MAX_LENGTH = 120


def _source_collection_finding_prior_query_memory_message(
    prior_tasks: list[dict[str, Any]],
) -> str:
    """Render prior finding attempts' retrieval memory for a formal retry.

    Collects queries from ``result.searchTrace[]`` and locators from
    ``result.invalidSources[]`` of prior failed finding attempts, deduped
    case/whitespace-insensitively and bounded (30 items, 200 chars each).
    Newest attempt wins first so the bound keeps the most recent memory.
    The block is a "do not repeat" memory only; it deliberately carries no
    invitation to keep searching or paginate (single-read contract).
    """
    s = _service()
    from .stage_session import _AUTO_FORMAL_RETRY_STATUSES

    memory_tasks = [
        item
        for item in prior_tasks
        if isinstance(item, dict)
        and s._normalize_source_collection_stage_id(item.get("stageId"), default="") == "finding"
        and s._trim_text(item.get("status"), max_length=80).lower() in _AUTO_FORMAL_RETRY_STATUSES
    ]
    if not memory_tasks:
        return ""
    memory_tasks.sort(
        key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""),
        reverse=True,
    )

    def _memory_key(value: str) -> str:
        return " ".join(value.split()).casefold()

    queries: list[str] = []
    seen_queries: set[str] = set()
    invalid_entries: list[str] = []
    seen_invalid: set[str] = set()
    for task in memory_tasks:
        writeback = task.get("writeback") if isinstance(task.get("writeback"), dict) else {}
        result = task.get("result") if isinstance(task.get("result"), dict) else {}
        for container in (result, writeback):
            trace = container.get("searchTrace")
            if isinstance(trace, list):
                for item in trace:
                    if len(queries) >= _FINDING_QUERY_MEMORY_MAX_ITEMS:
                        break
                    if not isinstance(item, dict):
                        continue
                    query = s._trim_text(
                        item.get("query"),
                        max_length=_FINDING_QUERY_MEMORY_ITEM_MAX_LENGTH,
                    )
                    query_key = _memory_key(query)
                    if not query or query_key in seen_queries:
                        continue
                    seen_queries.add(query_key)
                    queries.append(query)
            invalid_sources = container.get("invalidSources")
            if isinstance(invalid_sources, list):
                for item in invalid_sources:
                    if len(invalid_entries) >= _FINDING_QUERY_MEMORY_MAX_ITEMS:
                        break
                    if not isinstance(item, dict):
                        continue
                    locator = s._trim_text(
                        item.get("url")
                        or item.get("sourceUrl")
                        or item.get("locator")
                        or item.get("doi")
                        or item.get("DOI")
                        or item.get("sourceRef"),
                        max_length=_FINDING_QUERY_MEMORY_ITEM_MAX_LENGTH,
                    )
                    locator_key = _memory_key(locator)
                    if not locator or locator_key in seen_invalid:
                        continue
                    seen_invalid.add(locator_key)
                    reason = s._trim_text(
                        item.get("reason") or item.get("failureReason"),
                        max_length=_FINDING_QUERY_MEMORY_REASON_MAX_LENGTH,
                    )
                    invalid_entries.append(f"{locator}（原因：{reason}）" if reason else locator)
        if (
            len(queries) >= _FINDING_QUERY_MEMORY_MAX_ITEMS
            and len(invalid_entries) >= _FINDING_QUERY_MEMORY_MAX_ITEMS
        ):
            break
    if not queries and not invalid_entries:
        return ""
    lines = ["", "## 上一轮检索记忆（不要重复）"]
    if queries:
        lines.append(
            "- 上一轮 attempt 已检索过以下 query，不要原样或仅换大小写/编码/URL 形状重复执行："
        )
        lines.extend(f"  - {query}" for query in queries)
    if invalid_entries:
        lines.append("- 上一轮已把以下来源判为无效，不要重试同一 locator 或其变体：")
        lines.extend(f"  - {entry}" for entry in invalid_entries)
    lines.append(
        "- 边界：以上是已试检索记忆，只用于避免重复无效检索；不是继续检索或翻页补读的邀请。"
    )
    return "\n".join(lines)


def _source_collection_stage_task_has_missing_coverage(task: dict[str, Any] | None) -> bool:
    s = _service()
    if not isinstance(task, dict) or not task:
        return False
    coverage = s._source_collection_stage_task_coverage_summary(task)
    if not isinstance(coverage, dict) or not bool(coverage.get("applicable")):
        return False
    if bool(coverage.get("complete")):
        return False
    return bool(s._source_collection_count(coverage.get("missing")) or coverage.get("missingCandidateIds") or coverage.get("missingRecordIds"))


def _source_collection_stage_task_needs_writeback_resume(task: dict[str, Any] | None) -> bool:
    s = _service()
    if not isinstance(task, dict) or not task:
        return False
    if s._source_collection_stage_task_has_missing_coverage(task):
        return False
    task_status = s._trim_text(task.get("status"), max_length=80)
    if task_status not in {"interrupted", "stopped"}:
        return False
    writeback = task.get("writeback") if isinstance(task.get("writeback"), dict) else {}
    result = task.get("result") if isinstance(task.get("result"), dict) else {}
    closure = (
        writeback.get("closureSummary")
        if isinstance(writeback.get("closureSummary"), dict)
        else result.get("closureSummary") if isinstance(result.get("closureSummary"), dict) else {}
    )
    if s._trim_text(closure.get("artifactStatus"), max_length=120) != "interrupted_before_writeback":
        return False
    progress = (
        closure.get("taskToolProgress")
        if isinstance(closure.get("taskToolProgress"), dict)
        else task.get("taskToolProgress") if isinstance(task.get("taskToolProgress"), dict) else {}
    )
    total = s._source_collection_count(progress.get("total"))
    completed = s._source_collection_count(progress.get("completed"))
    completed_ids = {
        s._trim_text(item, max_length=120)
        for item in list(progress.get("completedIds") or [])
        if s._trim_text(item, max_length=120)
    }
    checklist_binding = task.get("checklistBinding") if isinstance(task.get("checklistBinding"), dict) else {}
    if s._trim_text(checklist_binding.get("mode"), max_length=80) == "stage_task":
        return bool(completed_ids)
    stage_id = s._normalize_source_collection_stage_id(task.get("stageId"), default="")
    writeback_checkpoint_by_stage = {
        "finding": "write_candidate_leads",
        "extraction": "write_extractions",
        "relations": "write_candidate_graph",
        "ingestion": "write_ingestion_decision",
    }
    writeback_checkpoint = writeback_checkpoint_by_stage.get(stage_id)
    return bool(
        writeback_checkpoint and writeback_checkpoint in completed_ids
        or (total > 1 and completed >= total - 1)
    )


def _source_collection_stage_task_context_mode(
    *,
    stage_id: str,
    agent_role: str,
    previous_task: dict[str, Any] | None,
    source_candidates: list[dict[str, Any]] | None = None,
) -> str:
    s = _service()
    can_materialize_formal_knowledge = s._source_collection_stage_can_materialize_formal_knowledge(stage_id, agent_role)
    if stage_id == "extraction" and not can_materialize_formal_knowledge:
        if s._source_collection_stage_task_has_missing_coverage(previous_task):
            return "retry_missing"
        if s._source_collection_stage_evidence_retry_focus(
            previous_task or {},
            list(source_candidates or []),
        ):
            return "retry_evidence"
        return "evidence"
    if stage_id == "relations":
        return "evidence"
    return "compact"


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
    task_checklist: list[dict[str, Any]],
    previous_task: dict[str, Any] | None = None,
    context_mode: str = "",
) -> str:
    s = _service()
    can_materialize_formal_knowledge = s._source_collection_stage_can_materialize_formal_knowledge(stage_id, agent_role)
    boundary_text = (
        "边界：这是资料入库任务，会立即要求当前 Agent 在本会话执行；"
        "对本轮已通过候选调用 source_collection_stage_writeback_tool 写回 approved 候选结果后，"
        "后端会复用 Team Knowledge source review、proposal review/apply gate 创建正式 KnowledgeItem；"
        "不要绕过该治理门禁直接写库、写 RAG 或改 ACL。"
        if can_materialize_formal_knowledge
        else (
            "边界：这是阶段任务启动消息，会立即要求当前 Agent 在本会话执行；"
            "正式知识库、RAG 和官方图谱写入仍由资料入库阶段控制。"
        )
    )
    context = s._source_collection_agent_context_message(
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
    task_title = s._source_collection_stage_task_title(stage_id)
    contract_json = json.dumps(writeback_contract, ensure_ascii=False, sort_keys=True)
    writeback_resume = s._source_collection_stage_task_needs_writeback_resume(previous_task)
    context_mode = s._trim_text(context_mode, max_length=40) or s._source_collection_stage_task_context_mode(
        stage_id=stage_id,
        agent_role=agent_role,
        previous_task=previous_task,
        source_candidates=source_candidates,
    )
    context_tool_payload = {
        "team_id": writeback_contract.get("teamId", ""),
        "run_id": writeback_contract.get("runId", ""),
        "stage_id": writeback_contract.get("stageId", stage_id),
        "task_id": writeback_contract.get("taskId", ""),
        "max_records": 5,
        "include_candidates": True,
        "record_offset": 0,
        "record_limit": 25,
        "candidate_offset": 0,
        "candidate_limit": 25,
        "context_mode": context_mode,
    }
    if can_materialize_formal_knowledge:
        context_tool_payload["candidate_limit"] = 80
    if writeback_resume:
        context_tool_payload["record_limit"] = 80
        context_tool_payload["candidate_limit"] = 80
    context_tool_json = json.dumps(context_tool_payload, ensure_ascii=False, sort_keys=True)
    task_tool_payload = [
        {"id": item.get("id"), "description": item.get("description")}
        for item in task_checklist
        if isinstance(item, dict) and s._trim_text(item.get("id"), max_length=120)
    ]
    task_tool_json = json.dumps(task_tool_payload, ensure_ascii=False, sort_keys=True)
    task_checklist_lines = [
        f"- {item.get('order', index)}. [{s._trim_text(item.get('id'), max_length=120)}] {s._trim_text(item.get('description'), max_length=300)}"
        + (f"；工具：`{s._trim_text(item.get('requiredTool'), max_length=120)}`" if s._trim_text(item.get("requiredTool"), max_length=120) else "")
        for index, item in enumerate(task_checklist, start=1)
        if isinstance(item, dict)
    ]
    previous_attempt_lines = s._source_collection_stage_previous_attempt_lines(previous_task)
    previous_attempt_block = [*previous_attempt_lines, ""] if previous_attempt_lines else []
    evidence_remediation_contract = (
        writeback_contract.get("evidenceRemediationContract")
        if isinstance(writeback_contract.get("evidenceRemediationContract"), dict)
        else {}
    )
    remediation_scope_ids = s._normalize_text_list(
        evidence_remediation_contract.get("scopeCandidateIds"),
        max_items=120,
        max_length=160,
    )
    remediation_lines = (
        [
            "- 本轮是正式证据修复 child Run；只处理冻结的 scopeCandidateIds，禁止扩展检索范围。",
            f"- 必须为每个 scopeCandidateId 调用一次 `web_fetch_tool` 抓取其既有 DOI/URL，并在 `evidenceFetchAttempts[]` 记录 candidateId、locator、status、toolName；失败时同时写 failureCode。冻结范围：{json.dumps(remediation_scope_ids, ensure_ascii=False)}",
            "- 所有既有定位符均尝试后，仍证据不足才允许写 `needs_review`；不得跳过抓取直接沿用上一轮结论。",
        ]
        if evidence_remediation_contract
        else []
    )
    if can_materialize_formal_knowledge:
        pagination_lines = [
            "- 本任务是资料入库：读取一次 `source_collection_context_tool` 后，如果返回 `stewardActionPacket.approvedCandidateIds` 和 `writebackResultSkeleton`，优先立刻调用 `source_collection_stage_writeback_tool` 写回，不要先重读全部资料。",
            "- 不要因为 `recordPage.hasMore=true` 或 `candidatePage.hasMore=true` 自动翻完整批次；只有缺少真实 approvedCandidateIds、writebackResultSkeleton 或入库证据时，才按 nextOffset 补读必要页。",
        ]
    elif writeback_resume:
        pagination_lines = [
            "- 本轮是写回恢复：如果当前会话上下文中已有完整结论和真实 ID，优先直接调用 `source_collection_stage_writeback_tool` 回写，不要先重读全部资料。",
            "- 只有缺少真实 recordId/candidateId 或证据时，才调用上面的 `source_collection_context_tool` 做一次性 ID 核对；不要因为 `candidatePage.hasMore=true` 自动翻完整批次。",
            "- 写回恢复阶段禁止调用 `web_fetch_tool` 或搜索工具；既有链接抓取失败应保留原决定并标记 `needs_more_info`，随后立即结构化写回。",
        ]
    elif stage_id == "finding":
        # finding 闭合化第一步（O4）：单读指令，不再邀请按 nextOffset 补读。
        pagination_lines = [
            "- 本阶段一次性读取当前批上下文即可开始检索：单次 `source_collection_context_tool` 调用即满足检查清单，不需要按 `candidatePage.nextOffset` / `recordPage.nextOffset` 翻页补读存量候选。",
            "- 存量覆盖由系统在写回后评估；把检索精力放在新资料、`searchTrace[]` 和按批写回上。",
        ]
    else:
        pagination_lines = [
            "- 已有真实 recordId 与证据锚点的原始资料不要重复读取；覆盖检查清单要求后即可回写，`recordPage.hasMore=true` 仅表示还有剩余条目。",
            "- 已有真实 candidateId 与证据锚点的候选不要重复读取；覆盖检查清单要求后即可回写，`candidatePage.hasMore=true` 仅表示还有剩余条目。",
            "- 确实缺少 ID 或证据时，才按 `recordPage.nextOffset` / `candidatePage.nextOffset` 补读必要页；不得虚构截断内容。",
        ]
    stage_writeback_lines = stage_writeback_prompt_lines(stage_id)
    return "\n".join(
        [
            f"## 资料搜集阶段任务：{task_title}",
            "",
            context,
            "",
            *previous_attempt_block,
            "## 阶段检查清单",
            "- 本阶段 checklist 已由后端绑定，系统会根据阶段工具结果和结构化写回证据自动更新；不要调用通用 `task_list_tool`、`task_create_tool` 或 `task_update_tool` 复制清单。",
            *task_checklist_lines,
            "- 最后一项只会在 `source_collection_stage_writeback_tool` 成功且产物门禁通过后完成；如果仍未通过，请在写回中说明缺失证据。",
            "- 如果任一检查项无法完成，不要自然语言声称完成；调用 `source_collection_stage_writeback_tool` 写入 blocked/failed/needs_review 和失败原因。",
            "",
            "## 执行要求",
            f"- 先调用 `source_collection_context_tool` 读取本轮受控资料上下文，参数如下：`{context_tool_json}`。",
            "- 在本会话里完成当前阶段任务，并把可审查的结论、证据引用和下一步写清楚。",
            (
                "- 本轮是覆盖缺口重试：`context_mode=retry_missing` 只返回上一轮未覆盖 ID；只补 `retryFocus.missingCandidateIds` / `missingRecordIds`，不要重做已处理资料。"
                if context_mode == "retry_missing"
                else "- 本轮是证据缺口重试：`context_mode=retry_evidence` 只返回 `retryFocus.evidenceGapCandidateIds`；保留原决定，仅补真实证据锚点。"
                if context_mode == "retry_evidence"
                else "- 本轮使用证据上下文：逐页读取真实 ID、受控摘要和 `evidenceRefs`；摘要只代表搜集阶段保存的摘要/元数据，不等于全文。"
            ),
            *pagination_lines,
            *stage_writeback_lines,
            *remediation_lines,
            "- 可以分批调用 `source_collection_stage_writeback_tool`，系统会按真实 `candidateId` / `recordId` 累计上一批结果；不要因为 compact 返回未展开完整数组而重复提交同一大包。",
            (
                "- 资料提炼阶段若受控摘要不足，但 `candidates[].sourceUrl` 或 `doi` 存在，可用 `web_fetch_tool` 仅抓取该既有定位符补证；"
                "不要扩展检索方向、生成新候选或调用搜索工具。当前批读取完毕后一次性补证（可连续调用 `web_fetch_tool`），随后以 1-2 次回写完成本批结果；抓取失败后再标记 `needs_more_info`。"
                if stage_id == "extraction" and context_mode in {"evidence", "retry_evidence"} and not writeback_resume
                else ""
            ),
            "- 只有确认没有摘要、正文、可验证内容或明显跑题时，才写 `decision=exclude` 和 `excludeReason=no_effective_content/out_of_scope/unobtainable`；这些来源会被移出后续流程并记录，避免下次重复搜到。",
            "- 如果上下文返回 `excludedSourceSummary.excludedCount>0`，表示这些资料已从本轮活跃流程移出，不要再次处理或把它们算作待补资料。",
            "- 不要推断截断或隐藏资料；不要把 `remaining_11_candidates`、短 ID 或聚合占位符当作 recordId/candidateId。",
            "- 不要使用 `web_fetch_tool` 读取 `file://` 本地路径或 localhost 回写接口；本地资料上下文只通过 `source_collection_context_tool` 获取。",
            (
                "- 本任务是资料入库：只处理 source_quality_approved 的本轮 approved 候选；优先使用 `source_collection_context_tool` 返回的 `stewardActionPacket.approvedCandidateIds` 和 `writebackResultSkeleton` 写回。"
                if can_materialize_formal_knowledge
                else "- 不要直接写正式 Team Knowledge、RAG 或官方图谱；只能按候选层和结构化回写合同提交结果。"
            ),
            (
                "- 不要推断截断或隐藏候选；pending/rejected/needs_revision 只作为 deferredCandidateCounts 汇报，不要在资料入库阶段继续审查或补全它们。"
                if can_materialize_formal_knowledge
                else "- 当前非入库阶段只提交阶段结果，不处理知识入库。"
            ),
            "- 完成后必须调用 `source_collection_stage_writeback_tool` 回写；不要让自然语言回复成为唯一结果来源。",
            "- 如果上下文不足、工具失败或无法完成，请调用 `source_collection_stage_writeback_tool` 写入 status=blocked 或 failed，并说明原因。",
            "",
            "## 结构化回写合同",
            f"```json\n{contract_json}\n```",
        ]
    )


def _sync_stage_round_with_source_collection_stage_task(team_id: str, run_id: str, task: dict[str, Any]) -> None:
    s = _service()
    now = s.utc_now_iso()
    with s._WORKFLOW_LOCK:
        store = s._load_stage_round_store(team_id)
        rounds = s._stage_rounds(store)
        stage_round = s._latest_stage_round(
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
            and s._trim_text(item.get("taskId"), max_length=160) != s._trim_text(task.get("taskId"), max_length=160)
        ]
        task_ref = {
            "taskId": s._trim_text(task.get("taskId"), max_length=160),
            "runId": run_id,
            "stageId": s._trim_text(task.get("stageId"), max_length=80),
            "agentId": s._trim_text(task.get("agentId"), max_length=160),
            "agentRole": s._trim_text(task.get("agentRole"), max_length=80),
            "sessionId": s._trim_text(task.get("sessionId"), max_length=160),
            "status": s._trim_text(task.get("status"), max_length=80),
            "summary": s._trim_text(task.get("summary"), max_length=500),
            "updatedAt": s._trim_text(task.get("updatedAt"), max_length=120) or now,
        }
        task_refs.append(task_ref)
        stage_round["sourceCollectionStageSessionTasks"] = sorted(task_refs, key=lambda item: str(item.get("updatedAt") or ""))
        stage_round["updatedAt"] = now
        stage_round["status"] = s._source_collection_stage_round_status_from_task_refs(
            stage_round,
            stage_round["sourceCollectionStageSessionTasks"],
        )
        workflow = s._load_or_create_workflow(team_id)
        stage_round["teamMemoryRecord"] = s._stage_memory_record(stage_round, workflow)
        stage_round["teamMemoryRecordId"] = stage_round["teamMemoryRecord"]["recordId"]
        store["updatedAt"] = now
        workflow["activeWorkflowItems"] = s._upsert_active_item(
            workflow.get("activeWorkflowItems"),
            candidate_id=run_id,
            current_node="knowledge_collection",
            status=f"source_collection_stage_task_{task_ref['status']}",
            transfer_id="",
        )
        workflow["updatedAt"] = now
        s._write_json(s._stage_round_store_path(team_id), store)
        s._write_json(s._workflow_path(team_id), workflow)


def _latest_stage_round(rounds: list[dict[str, Any]]) -> dict[str, Any] | None:
    s = _service()
    if not rounds:
        return None
    # Reconciliation deliberately records a fresh ``updatedAt`` when an older
    # round is superseded.  That audit update must not make the historical
    # round become the current stage projection again.
    return max(
        rounds,
        key=lambda item: (
            s._trim_text(item.get("status"), max_length=80).lower() != "superseded",
            s._source_collection_count(item.get("roundNumber")),
            s._workflow_timestamp_sort_key(item.get("createdAt")),
            s._workflow_timestamp_sort_key(item.get("updatedAt")),
            s._trim_text(item.get("stageRoundId"), max_length=160),
        ),
    )


def _stage_round_number(rounds: list[dict[str, Any]], stage_type: str) -> int:
    s = _service()
    return 1 + sum(1 for item in rounds if str(item.get("stageType") or "") == stage_type)


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
    s = _service()
    required_tools = list(s.SOURCE_COLLECTION_STAGE_REQUIRED_TOOLS)
    if agent_role in s.SOURCE_COLLECTION_SEARCH_EXECUTION_AGENT_ROLES:
        required_tools.extend(s.SOURCE_COLLECTION_SEARCH_REQUIRED_TOOLS)
    try:
        policy = s.agent_directory_service.resolve_tool_policy_for_agent(agent_id, session_id=session_id)
    except Exception as exc:
        s._record_workflow_event(
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
    s._record_workflow_event(
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
