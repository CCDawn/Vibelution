"""Pure source-collection status and stage-card projections."""

from __future__ import annotations

from typing import Any

from .source_collection_common import normalize_metadata, source_collection_count, trim_text
from .source_collection_stage_tasks import SOURCE_COLLECTION_STAGE_SESSION_TASK_ACTIVE_STATUSES


def source_collection_summary_payload_status(
    run_id: str,
    *,
    run_status: dict[str, Any],
    active_work_run: dict[str, Any],
    stage_round_ref: dict[str, Any],
    projection: dict[str, Any],
) -> str:
    if not trim_text(run_id, max_length=160):
        return "idle"
    if active_work_run:
        return "active"
    latest_tasks = projection.get("latestTasks") if isinstance(projection.get("latestTasks"), dict) else {}
    for task in latest_tasks.values():
        if not isinstance(task, dict):
            continue
        task_status = trim_text(task.get("status"), max_length=80).lower()
        if task_status in {"queued", "running", "accepted"}:
            return "active"
    lifecycle_status = trim_text(run_status.get("runStatus"), max_length=80).lower()
    if lifecycle_status in {"collecting", "processing"} and not stage_round_ref:
        return "active"
    return "ready"


def source_collection_stage_card_projection(
    stage_id: str,
    tasks: list[dict[str, Any]],
    *,
    artifact_count: int,
    input_count: int,
    output_count: int,
    pending_count: int,
    artifact_status: str,
    artifact_summary: str,
    historical_task_count: int = 0,
    extra_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    latest_task = latest_source_collection_stage_task(tasks)
    has_verified_completed_task = any(
        trim_text(task.get("status"), max_length=80).lower() == "completed"
        and isinstance(task.get("completionGate"), dict)
        and bool(task["completionGate"].get("passed"))
        for task in tasks
        if isinstance(task, dict)
    )
    agent_status = trim_text(latest_task.get("status"), max_length=80).lower() if latest_task else "not_started"
    coverage_summary = source_collection_stage_task_coverage_summary(latest_task or {})
    coverage_missing = source_collection_count(coverage_summary.get("missing")) + source_collection_count(coverage_summary.get("invalid"))
    coverage_incomplete = bool(coverage_summary.get("applicable")) and not bool(coverage_summary.get("complete"))
    effective_pending_count = max(pending_count, coverage_missing)
    current_total = max(
        0,
        source_collection_count(artifact_count),
        source_collection_count(output_count) + effective_pending_count,
    )
    current_processed = max(0, current_total - effective_pending_count) if current_total else 0
    current_coverage_summary = source_collection_stage_current_coverage_summary(
        stage_id,
        coverage_summary,
        current_total=current_total,
        current_processed=current_processed,
        effective_pending_count=effective_pending_count,
    )
    task_completed = agent_status == "completed"
    task_interrupted = agent_status == "interrupted"
    task_settled = agent_status in {"completed", "needs_review"}
    task_blocked = agent_status in {"blocked", "failed"}
    artifact_ready = artifact_status == "ready" and artifact_count > 0
    artifact_complete = artifact_ready and effective_pending_count <= 0 and not coverage_incomplete
    if agent_status in {"running", "queued"}:
        card_status = "agent_running"
    elif task_interrupted:
        card_status = "agent_interrupted"
    elif task_blocked and artifact_complete and has_verified_completed_task:
        card_status = "closed_loop"
    elif task_blocked and artifact_ready:
        card_status = "artifact_ready_agent_blocked"
    elif task_blocked:
        card_status = "agent_blocked"
    elif task_completed and artifact_complete:
        card_status = "closed_loop"
    elif task_settled and effective_pending_count > 0 and artifact_count > 0:
        card_status = "partial_current_inputs"
    elif task_settled and artifact_ready:
        card_status = "artifact_ready_agent_needs_review"
    elif task_settled:
        card_status = "agent_done_artifact_pending"
    elif artifact_complete:
        card_status = "artifact_ready_no_latest_agent_task"
    elif effective_pending_count > 0 or input_count > 0:
        card_status = "pending"
    else:
        card_status = "idle"
    next_actions = latest_task.get("nextActions") if latest_task and isinstance(latest_task.get("nextActions"), list) else []
    result = latest_task.get("result") if latest_task and isinstance(latest_task.get("result"), dict) else {}
    result_keys = sorted(str(key) for key in result.keys()) if result else []
    normalized_extra_counts = {
        trim_text(key, max_length=80): source_collection_count(value)
        for key, value in dict(extra_counts or {}).items()
        if trim_text(key, max_length=80)
    }
    action_readiness = source_collection_stage_action_readiness(
        stage_id,
        card_status,
        agent_status,
        artifact_count=artifact_count,
        input_count=input_count,
        output_count=output_count,
        pending_count=effective_pending_count,
    )
    return {
        "stageId": stage_id,
        "status": card_status,
        "isClosedLoop": card_status == "closed_loop",
        "userStatusLabel": source_collection_stage_user_status_label(
            stage_id,
            card_status,
            current_coverage_summary=current_coverage_summary,
        ),
        "userSummary": source_collection_stage_user_summary(
            stage_id,
            card_status,
            artifact_summary,
            latest_task=latest_task,
            current_coverage_summary=current_coverage_summary,
            action_readiness=action_readiness,
        ),
        "actionReadiness": action_readiness,
        "agentTaskStatus": agent_status,
        "artifactStatus": artifact_status,
        "artifactSummary": artifact_summary,
        "currentCoverageSummary": current_coverage_summary,
        "counts": {
            "input": input_count,
            "artifact": artifact_count,
            "output": output_count,
            "pending": effective_pending_count,
            "task": len(tasks),
            "historicalTask": max(0, source_collection_count(historical_task_count)),
            **normalized_extra_counts,
        },
        "latestTask": source_collection_stage_task_card_summary(latest_task) if latest_task else {},
        "resultKeys": result_keys,
        "nextActions": [trim_text(item, max_length=500) for item in next_actions if trim_text(item, max_length=500)][:6],
        "blockingReasons": source_collection_stage_card_blocking_reasons(
            card_status,
            artifact_status,
            artifact_count,
            effective_pending_count,
            coverage_summary,
            current_coverage_summary=current_coverage_summary,
        ),
    }


def source_collection_stage_current_coverage_summary(
    stage_id: str,
    task_coverage_summary: dict[str, Any],
    *,
    current_total: int,
    current_processed: int,
    effective_pending_count: int,
) -> dict[str, Any]:
    if current_total <= 0:
        return {}
    task_coverage = task_coverage_summary if isinstance(task_coverage_summary, dict) else {}
    task_total = source_collection_count(task_coverage.get("total"))
    task_processed = source_collection_count(task_coverage.get("processed"))
    task_missing = source_collection_count(task_coverage.get("missing"))
    task_invalid = source_collection_count(task_coverage.get("invalid"))
    task_covers_current_inputs = (
        bool(task_coverage.get("applicable"))
        and bool(task_coverage.get("complete"))
        and task_total == current_total
        and task_processed >= current_total
        and task_missing <= 0
        and task_invalid <= 0
    )
    if task_covers_current_inputs:
        return {
            "applicable": True,
            "coverageKind": trim_text(task_coverage.get("coverageKind"), max_length=120)
            or f"{stage_id}_current_inputs",
            "complete": True,
            "total": current_total,
            "processed": current_total,
            "missing": 0,
            "invalid": 0,
            "blocked": source_collection_count(task_coverage.get("blocked")),
            "duplicate": source_collection_count(task_coverage.get("duplicate")),
        }
    return {
        "applicable": True,
        "coverageKind": f"{stage_id}_current_inputs",
        "complete": effective_pending_count <= 0,
        "total": current_total,
        "processed": min(current_processed, current_total),
        "missing": max(0, effective_pending_count),
        "invalid": 0,
        "blocked": 0,
        "duplicate": 0,
    }


def latest_source_collection_stage_task(tasks: list[dict[str, Any]]) -> dict[str, Any] | None:
    valid = [item for item in tasks if isinstance(item, dict)]
    if not valid:
        return None
    return sorted(valid, key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""))[-1]


def source_collection_stage_task_card_summary(task: dict[str, Any]) -> dict[str, Any]:
    writeback = task.get("writeback") if isinstance(task.get("writeback"), dict) else {}
    result = task.get("result") if isinstance(task.get("result"), dict) else {}
    evidence_refs = task.get("evidenceRefs") if isinstance(task.get("evidenceRefs"), list) else []
    next_actions = task.get("nextActions") if isinstance(task.get("nextActions"), list) else []
    return {
        "taskId": trim_text(task.get("taskId"), max_length=160),
        "stageId": trim_text(task.get("stageId"), max_length=80),
        "agentId": trim_text(task.get("agentId"), max_length=160),
        "agentRole": trim_text(task.get("agentRole"), max_length=80),
        "sessionId": trim_text(task.get("sessionId"), max_length=160),
        "status": trim_text(task.get("status"), max_length=80),
        "summary": trim_text(task.get("summary"), max_length=1000),
        "updatedAt": trim_text(task.get("updatedAt"), max_length=120),
        "resultKeys": sorted(str(key) for key in result.keys()),
        "evidenceRefCount": len(evidence_refs),
        "nextActionCount": len(next_actions),
        "coverageSummary": source_collection_stage_task_coverage_summary(task),
        "invalidCandidateIds": (
            list(writeback.get("invalidCandidateIds") or [])
            if isinstance(writeback.get("invalidCandidateIds"), list)
            else list(result.get("invalidCandidateIds") or []) if isinstance(result.get("invalidCandidateIds"), list) else []
        )[:80],
        "invalidRecordIds": (
            list(writeback.get("invalidRecordIds") or [])
            if isinstance(writeback.get("invalidRecordIds"), list)
            else list(result.get("invalidRecordIds") or []) if isinstance(result.get("invalidRecordIds"), list) else []
        )[:80],
        "closureSummary": (
            writeback.get("closureSummary")
            if isinstance(writeback.get("closureSummary"), dict)
            else result.get("closureSummary") if isinstance(result.get("closureSummary"), dict) else {}
        ),
        "taskToolRequired": bool(task.get("taskToolRequired")),
        "taskChecklist": [
            item for item in list(task.get("taskChecklist") or [])
            if isinstance(item, dict)
        ][:12],
        "taskToolProgress": (
            task.get("taskToolProgress")
            if isinstance(task.get("taskToolProgress"), dict)
            else {}
        ),
        "completionGate": (
            task.get("completionGate")
            if isinstance(task.get("completionGate"), dict)
            else {}
        ),
        "materializedSources": writeback.get("materializedSources") if isinstance(writeback.get("materializedSources"), dict) else {},
        "materializedContentExtraction": writeback.get("materializedContentExtraction") if isinstance(writeback.get("materializedContentExtraction"), dict) else {},
        "materializedKnowledgeIngestion": writeback.get("materializedKnowledgeIngestion") if isinstance(writeback.get("materializedKnowledgeIngestion"), dict) else {},
    }


def source_collection_stage_task_coverage_summary(task: dict[str, Any]) -> dict[str, Any]:
    writeback = task.get("writeback") if isinstance(task.get("writeback"), dict) else {}
    result = task.get("result") if isinstance(task.get("result"), dict) else {}
    coverage = writeback.get("coverageSummary") if isinstance(writeback.get("coverageSummary"), dict) else {}
    if not coverage:
        coverage = result.get("coverageSummary") if isinstance(result.get("coverageSummary"), dict) else {}
    return normalize_metadata(coverage)


def source_collection_stage_card_blocking_reasons(
    card_status: str,
    artifact_status: str,
    artifact_count: int,
    pending_count: int,
    coverage_summary: dict[str, Any] | None = None,
    *,
    current_coverage_summary: dict[str, Any] | None = None,
) -> list[str]:
    reasons: list[str] = []
    coverage = coverage_summary if isinstance(coverage_summary, dict) else {}
    current_coverage = current_coverage_summary if isinstance(current_coverage_summary, dict) else {}
    if card_status == "partial_current_inputs" and bool(current_coverage.get("applicable")):
        processed = source_collection_count(current_coverage.get("processed"))
        total = source_collection_count(current_coverage.get("total"))
        blocked = source_collection_count(current_coverage.get("blocked"))
        if bool(current_coverage.get("complete")):
            reasons.append(
                f"当前批次已处理 {processed}/{total}，"
                + (f"其中 {blocked} 条需要补充证据。" if blocked > 0 else "但结果尚未全部转为可用阶段产物。")
            )
        else:
            reasons.append(
                "当前阶段覆盖不足："
                f"已处理 {processed}/{total}，"
                f"{source_collection_count(current_coverage.get('missing'))} 条待补。"
            )
    if bool(coverage.get("applicable")) and not bool(coverage.get("complete")):
        reasons.append(
            "Agent 回写覆盖不完整："
            f"已处理 {source_collection_count(coverage.get('processed'))}/{source_collection_count(coverage.get('total'))}，"
            f"{source_collection_count(coverage.get('missing'))} 条待补，"
            f"{source_collection_count(coverage.get('invalid'))} 个 ID 未匹配。"
        )
    if card_status == "agent_interrupted":
        reasons.append("最近一次 Agent 会话在阶段写回前中断，需要继续这次任务或重试。")
    if card_status == "agent_done_artifact_pending":
        reasons.append("Agent task wrote back a structured result, but the expected stage artifact has not been created yet.")
    if card_status == "artifact_ready_agent_blocked":
        reasons.append("Ready artifact exists, but the latest Agent task is blocked or failed.")
    if card_status == "agent_blocked":
        reasons.append("Latest Agent task is blocked or failed.")
    if artifact_status == "empty" and artifact_count <= 0 and pending_count > 0:
        reasons.append("Inputs exist, but this stage has not produced its expected artifact yet.")
    return reasons


def source_collection_stage_readable_object_label(stage_id: str) -> str:
    labels = {
        "finding": "原始资料",
        "extraction": "候选资料",
        "relations": "资料关系",
        "ingestion": "入库结果",
    }
    return labels.get(stage_id, "可用资料")


def source_collection_stage_recovery_status_label(stage_id: str) -> str:
    labels = {
        "finding": "待继续寻找",
        "extraction": "待补提炼",
        "relations": "待补关系",
        "ingestion": "待补入库",
    }
    return labels.get(stage_id, "待补齐")


def source_collection_stage_action_label(stage_id: str, recommended_action: str = "") -> str:
    if recommended_action == "wait":
        return "等待 Agent 完成"
    if recommended_action == "continue_interrupted":
        return "继续这次任务"
    if stage_id == "finding":
        return "搜索下一批" if recommended_action in {"continue", "retry"} else "开始找资料"
    if stage_id == "extraction":
        return "Agent 继续提炼" if recommended_action in {"continue", "retry"} else "Agent 提炼资料"
    if stage_id == "relations":
        return "Agent 重新整理关系" if recommended_action == "retry" else "Agent 整理关系"
    if stage_id == "ingestion":
        return "Agent 继续入库" if recommended_action in {"continue", "retry"} else "Agent 入库资料"
    return "启动 Agent"


def source_collection_stage_action_readiness(
    stage_id: str,
    card_status: str,
    agent_status: str,
    *,
    artifact_count: int,
    input_count: int,
    output_count: int,
    pending_count: int,
) -> dict[str, Any]:
    if agent_status in SOURCE_COLLECTION_STAGE_SESSION_TASK_ACTIVE_STATUSES or card_status == "agent_running":
        return {
            "canStart": False,
            "reasonCode": "agent_running",
            "disabledReason": "已有 Agent 正在执行",
            "recommendedAction": "wait",
            "actionLabel": source_collection_stage_action_label(stage_id, "wait"),
        }
    if card_status == "agent_interrupted":
        return {
            "canStart": True,
            "reasonCode": "agent_interrupted",
            "disabledReason": "",
            "recommendedAction": "continue",
            "actionLabel": source_collection_stage_action_label(stage_id, "continue_interrupted"),
        }
    has_input = any(
        source_collection_count(value) > 0
        for value in (artifact_count, input_count, output_count, pending_count)
    )
    if not has_input:
        return {
            "canStart": False,
            "reasonCode": "no_stage_input",
            "disabledReason": "当前阶段还没有可执行输入",
            "recommendedAction": "wait",
            "actionLabel": source_collection_stage_action_label(stage_id, "wait"),
        }
    if card_status in {"agent_blocked", "artifact_ready_agent_blocked"}:
        recommended_action = "retry"
    elif card_status in {"partial_current_inputs", "agent_done_artifact_pending", "artifact_ready_agent_needs_review", "pending"}:
        recommended_action = "continue"
    elif card_status in {"closed_loop", "artifact_ready_no_latest_agent_task"}:
        recommended_action = "retry"
    else:
        recommended_action = "start"
    return {
        "canStart": True,
        "reasonCode": "ready",
        "disabledReason": "",
        "recommendedAction": recommended_action,
        "actionLabel": source_collection_stage_action_label(stage_id, recommended_action),
    }


def source_collection_stage_user_status_label(
    stage_id: str,
    card_status: str,
    *,
    current_coverage_summary: dict[str, Any] | None = None,
) -> str:
    if card_status == "agent_running":
        return "Agent 正在处理"
    if card_status == "agent_interrupted":
        return "已中断，需要继续"
    current_coverage = current_coverage_summary if isinstance(current_coverage_summary, dict) else {}
    if bool(current_coverage.get("applicable")) and current_coverage.get("complete") is False:
        return source_collection_stage_recovery_status_label(stage_id)
    labels = {
        "agent_running": "Agent 正在处理",
        "agent_interrupted": "已中断，需要继续",
        "closed_loop": "本阶段已完成",
        "artifact_ready_no_latest_agent_task": "产物已就绪",
        "artifact_ready_agent_blocked": "产物已生成，任务需排查",
        "agent_blocked": "Agent 任务受阻",
        "partial_current_inputs": source_collection_stage_recovery_status_label(stage_id),
        "artifact_ready_agent_needs_review": "产物待复核",
        "agent_done_artifact_pending": "Agent 已回写，仍待产物",
        "pending": "等待本阶段产出",
        "idle": "未开始",
    }
    return labels.get(card_status, "需要处理")


def source_collection_stage_user_summary(
    stage_id: str,
    card_status: str,
    artifact_summary: str,
    *,
    latest_task: dict[str, Any] | None = None,
    current_coverage_summary: dict[str, Any] | None = None,
    action_readiness: dict[str, Any] | None = None,
) -> str:
    current_coverage = current_coverage_summary if isinstance(current_coverage_summary, dict) else {}
    action = action_readiness if isinstance(action_readiness, dict) else {}
    if card_status == "agent_running":
        return "Agent 正在处理本阶段，请等待结果同步。"
    if card_status == "agent_interrupted":
        latest_summary = trim_text(latest_task.get("summary"), max_length=240) if isinstance(latest_task, dict) else ""
        next_action = trim_text(action.get("actionLabel"), max_length=120) or "继续这次任务"
        detail = latest_summary or "Agent 会话已停止，尚未调用阶段写回工具。"
        return f"{detail} 本阶段已中断，尚未回写最终产物。建议：{next_action}。"
    if (
        card_status == "partial_current_inputs"
        and bool(current_coverage.get("applicable"))
        and bool(current_coverage.get("complete"))
    ):
        processed = source_collection_count(current_coverage.get("processed"))
        total = source_collection_count(current_coverage.get("total"))
        blocked = source_collection_count(current_coverage.get("blocked"))
        next_action = trim_text(action.get("actionLabel"), max_length=120) or source_collection_stage_action_label(stage_id, "continue")
        pending_detail = f"其中 {blocked} 条需要补充证据。" if blocked > 0 else "当前结果仍待复核并转为可用阶段产物。"
        return f"{source_collection_stage_readable_object_label(stage_id)}已处理 {processed}/{total}，{pending_detail}建议：{next_action}。"
    if bool(current_coverage.get("applicable")) and current_coverage.get("complete") is False:
        processed = source_collection_count(current_coverage.get("processed"))
        total = source_collection_count(current_coverage.get("total"))
        missing = source_collection_count(current_coverage.get("missing"))
        invalid = source_collection_count(current_coverage.get("invalid"))
        invalid_text = f"无效 ID {invalid} 条。" if invalid > 0 else ""
        next_action = trim_text(action.get("actionLabel"), max_length=120) or source_collection_stage_action_label(stage_id, "continue")
        return f"{source_collection_stage_readable_object_label(stage_id)}已处理 {processed}/{total}，还有 {missing} 条需要补齐。{invalid_text}建议：{next_action}。"
    closure = {}
    if isinstance(latest_task, dict):
        writeback = latest_task.get("writeback") if isinstance(latest_task.get("writeback"), dict) else {}
        result = latest_task.get("result") if isinstance(latest_task.get("result"), dict) else {}
        closure = (
            writeback.get("closureSummary")
            if isinstance(writeback.get("closureSummary"), dict)
            else result.get("closureSummary")
            if isinstance(result.get("closureSummary"), dict)
            else {}
        )
    if trim_text(closure.get("message"), max_length=500):
        retry_instruction = trim_text(closure.get("retryInstruction") or closure.get("nextAction"), max_length=500)
        return (
            trim_text(closure.get("message"), max_length=500)
            if not retry_instruction
            else f"{trim_text(closure.get('message'), max_length=500)}建议：{retry_instruction}"
        )
    if card_status == "artifact_ready_agent_blocked":
        return f"{source_collection_stage_readable_object_label(stage_id)}已经可用，但最近一次 Agent 任务受阻；可以先查看结果，再决定是否重试。"
    if card_status == "agent_blocked":
        return "最近一次 Agent 任务没有完成。建议进入 Agent 私聊查看原因，或重新启动本阶段。"
    if card_status == "agent_done_artifact_pending":
        next_action = trim_text(action.get("actionLabel"), max_length=120) or source_collection_stage_action_label(stage_id, "continue")
        return f"已收到 Agent 结果，但还没有生成可用{source_collection_stage_readable_object_label(stage_id)}。建议：{next_action}。"
    return artifact_summary
