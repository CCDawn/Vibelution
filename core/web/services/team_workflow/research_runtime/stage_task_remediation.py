"""Narrow automatic remediation derived from canonical Source Collection tasks."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def extraction_quote_anchor_remediation(task: Mapping[str, Any] | None) -> str:
    """Return one correction instruction only for quote-anchor review states."""

    if not isinstance(task, Mapping):
        return ""
    if str(task.get("status") or "").strip().lower() != "needs_review":
        return ""
    if str(task.get("stageId") or "").strip().lower() != "extraction":
        return ""

    result = task.get("result") if isinstance(task.get("result"), Mapping) else {}
    writeback = (
        task.get("writeback") if isinstance(task.get("writeback"), Mapping) else {}
    )
    claim_materialization = (
        task.get("claimMaterialization")
        if isinstance(task.get("claimMaterialization"), Mapping)
        else result.get("claimMaterialization")
        if isinstance(result.get("claimMaterialization"), Mapping)
        else {}
    )
    quote_remediation = (
        task.get("quoteAnchorRemediation")
        if isinstance(task.get("quoteAnchorRemediation"), Mapping)
        else writeback.get("quoteAnchorRemediation")
        if isinstance(writeback.get("quoteAnchorRemediation"), Mapping)
        else {}
    )
    materialized = (
        writeback.get("materializedContentExtraction")
        if isinstance(writeback.get("materializedContentExtraction"), Mapping)
        else {}
    )
    try:
        missing_anchor_count = max(
            0, int(materialized.get("missingEvidenceAnchorCount") or 0)
        )
    except (TypeError, ValueError):
        missing_anchor_count = 0
    remediation_gate = str(claim_materialization.get("gate") or "").strip()
    evidence_review_reason = str(
        writeback.get("evidenceReviewRequiredReason") or ""
    ).strip()
    actionable = bool(quote_remediation) or remediation_gate == "needs_quote_anchor_retry"
    actionable = actionable or (
        evidence_review_reason == "missing_evidence_anchor" and missing_anchor_count > 0
    )
    if not actionable:
        return ""

    detail = str(
        claim_materialization.get("remediation")
        or result.get("claimMaterializationRemediation")
        or quote_remediation.get("instruction")
        or ""
    ).strip()[:2000]
    instruction = (
        "阶段任务的权威状态仍是 needs_review，尚未完成。请继续当前任务："
        "先调用 source_collection_context_tool 读取最新 quotableSources 和修正要求，"
        "每条 claims/keyFindings 必须同时包含逐字 quote、sourceRef 和来源内定位锚"
        "（page、citation 或 evidenceRef）；从 quotableSources 对应原文块读取真实定位信息，"
        "不能只写 quote 或用来源 URL 代替定位锚。然后调用 "
        "source_collection_stage_writeback_tool 重新回写 "
        "status=completed。只有工具返回任务 status=completed 后才能结束。"
    )
    return f"{instruction}\n修正要求：{detail}" if detail else instruction


def source_stage_task_for_node_run(
    *, team_id: str, source_run_id: str, node_run_id: str
) -> dict[str, Any] | None:
    """Resolve exactly one canonical stage task by its frozen node-run identity."""

    normalized_node_run_id = str(node_run_id or "").strip()
    if not normalized_node_run_id:
        return None
    from core.web.services.team_workflow.source_collection.stage_reconcile import (
        _source_collection_stage_session_tasks,
    )

    matches = [
        task
        for task in _source_collection_stage_session_tasks(team_id, source_run_id)
        if isinstance(task, dict)
        and isinstance(task.get("challengeTaskContract"), Mapping)
        and str(task["challengeTaskContract"].get("nodeRunId") or "").strip()
        == normalized_node_run_id
    ]
    return dict(matches[0]) if len(matches) == 1 else None
