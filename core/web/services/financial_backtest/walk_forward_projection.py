"""Pure transport and evidence projections for A-share walk-forward runs."""

from __future__ import annotations

import copy
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

from core.web.services.financial_backtest.contract import (
    MAX_RESULT_CHARS,
    FinancialBacktestConflict,
    deterministic_run_id,
)
from core.web.services.financial_backtest.store import FinancialBacktestStore


def build_walk_forward_export(
    workflow: Mapping[str, Any], projected_workflow: Mapping[str, Any]
) -> dict[str, Any]:
    """Build a bounded export from already loaded, verified workflow evidence."""
    execution = workflow.get("execution") if isinstance(workflow.get("execution"), Mapping) else {}
    training_results = execution.get("trainMetrics") if isinstance(execution.get("trainMetrics"), Mapping) else {}
    training_run_ids = execution.get("trainRunIds") if isinstance(execution.get("trainRunIds"), Mapping) else {}
    child_rows: list[dict[str, Any]] = []
    for fold in workflow.get("folds", []) if isinstance(workflow.get("folds"), list) else []:
        fold_id = str(fold.get("foldId") or "") if isinstance(fold, Mapping) else ""
        for candidate_id, run_id in sorted(
            (training_run_ids.get(fold_id) or {}).items()
            if isinstance(training_run_ids.get(fold_id), Mapping)
            else []
        ):
            metrics = (
                training_results.get(fold_id, {}).get(candidate_id)
                if isinstance(training_results.get(fold_id), Mapping)
                else None
            )
            child_rows.append(
                {
                    "foldId": fold_id,
                    "stage": "train",
                    "candidateId": str(candidate_id),
                    "runId": str(run_id),
                    "metrics": copy.deepcopy(metrics),
                }
            )
        if isinstance(fold, Mapping) and fold.get("testRunId"):
            child_rows.append(
                {
                    "foldId": fold_id,
                    "stage": "test",
                    "candidateId": str(fold.get("selectedCandidateId") or ""),
                    "runId": str(fold.get("testRunId") or ""),
                    "metrics": copy.deepcopy(fold.get("metrics")),
                }
            )
    plan = workflow.get("plan") if isinstance(workflow.get("plan"), Mapping) else {}
    export = {
        "schemaVersion": 1,
        "workflow": projected_workflow,
        "plan": {
            "sourceDataHash": plan.get("sourceDataHash"),
            "sourceParamsHash": plan.get("sourceParamsHash"),
            "sourceModelId": plan.get("sourceModelId"),
            "sourceModelFingerprint": plan.get("sourceModelFingerprint"),
            "sourceParams": copy.deepcopy(plan.get("sourceParams")),
            "candidates": copy.deepcopy(plan.get("candidates")),
            "folds": [
                {
                    key: fold[key]
                    for key in (
                        "foldId", "trainStart", "trainEnd", "testStart", "testEnd",
                        "trainStartIndex", "trainEndIndex", "testStartIndex", "testEndIndex",
                    )
                    if isinstance(fold, Mapping) and key in fold
                }
                for fold in plan.get("folds", [])
                if isinstance(fold, Mapping)
            ],
            "stageBudgets": copy.deepcopy(plan.get("stageBudgets")),
            "retryReserveRule": plan.get("retryReserveRule"),
            "retryReserveTokens": plan.get("retryReserveTokens"),
            "selectionMetric": plan.get("selectionMetric"),
            "selectionRule": plan.get("selectionRule"),
            "tieBreakRule": plan.get("tieBreakRule"),
            "dataBoundaryRule": plan.get("dataBoundaryRule"),
        },
        "childResults": child_rows,
    }
    content = json.dumps(export, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    if len(content) > MAX_RESULT_CHARS:
        raise FinancialBacktestConflict("滚动验证JSON导出超过安全大小限制")
    return export


def project_walk_forward(
    workflow: Mapping[str, Any],
    *,
    store: FinancialBacktestStore | None = None,
    child_runs: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return only the typed transport projection, never private execution state."""
    if child_runs is None:
        child_runs = store.list_runs(str(workflow.get("agentId") or "")) if store else []
    token_usage = _project_token_usage(workflow, child_runs)
    folds: list[dict[str, Any]] = []
    for row in workflow.get("folds", []) if isinstance(workflow.get("folds"), list) else []:
        if not isinstance(row, Mapping):
            continue
        folds.append(
            {
                "foldId": str(row.get("foldId") or ""),
                "trainStart": str(row.get("trainStart") or ""),
                "trainEnd": str(row.get("trainEnd") or ""),
                "testStart": str(row.get("testStart") or ""),
                "testEnd": str(row.get("testEnd") or ""),
                "selectedCandidateId": row.get("selectedCandidateId"),
                "testRunId": row.get("testRunId"),
                "status": str(row.get("status") or "pending"),
                "metrics": project_metrics(row.get("metrics")),
            }
        )
    return {
        "agentId": str(workflow.get("agentId") or ""),
        "workflowId": str(workflow.get("workflowId") or ""),
        "sourceRunId": str(workflow.get("sourceRunId") or ""),
        "status": str(workflow.get("status") or "failed"),
        "planHash": str(workflow.get("planHash") or ""),
        "trainSessions": int(workflow.get("trainSessions") or 0),
        "testSessions": int(workflow.get("testSessions") or 0),
        "stepSessions": int(workflow.get("stepSessions") or 0),
        "maxTokens": max(0, int(workflow.get("maxTokens") or 0)),
        "estimatedTokens": max(0, int(workflow.get("estimatedTokens") or 0)),
        "tokensUsed": token_usage["tokensUsed"],
        "budgetTokensCommitted": token_usage["budgetTokensCommitted"],
        "tokenUsageEstimated": token_usage["tokenUsageEstimated"],
        "candidates": [
            {
                "candidateId": str(item.get("candidateId") or ""),
                "maxPositionPct": int(item.get("maxPositionPct") or 0),
            }
            for item in workflow.get("candidates", [])
            if isinstance(item, Mapping)
        ],
        "folds": folds,
        "activeRunId": workflow.get("activeRunId"),
        "terminalReason": workflow.get("terminalReason"),
        "createdAt": str(workflow.get("createdAt") or ""),
        "updatedAt": str(workflow.get("updatedAt") or ""),
        "notice": str(workflow.get("notice") or ""),
    }


def _project_token_usage(
    workflow: Mapping[str, Any], child_runs: Sequence[Mapping[str, Any]]
) -> dict[str, int | bool]:
    """Aggregate every persisted child, including an orphan from a crash window."""
    agent_id = str(workflow.get("agentId") or "")
    plan = workflow.get("plan") if isinstance(workflow.get("plan"), Mapping) else {}
    request_map = plan.get("stageRequests") if isinstance(plan.get("stageRequests"), Mapping) else {}
    planned_request_ids: set[str] = set()
    for stage_map in request_map.values():
        if not isinstance(stage_map, Mapping):
            continue
        for stage in ("train", "test"):
            candidate_map = stage_map.get(stage)
            if isinstance(candidate_map, Mapping):
                planned_request_ids.update(
                    str(value) for value in candidate_map.values() if str(value or "")
                )

    execution = workflow.get("execution") if isinstance(workflow.get("execution"), Mapping) else {}
    active_stage = execution.get("activeStage") if isinstance(execution.get("activeStage"), Mapping) else {}
    active_request_id = str(active_stage.get("clientRequestId") or "")
    if active_request_id:
        planned_request_ids.add(active_request_id)
    planned_run_ids = {
        deterministic_run_id(agent_id, request_id)
        for request_id in planned_request_ids
    } if agent_id else set()
    active_run_id = str(workflow.get("activeRunId") or "")

    seen_run_ids: set[str] = set()
    tokens_used = 0
    committed = 0
    estimated = False
    for run in child_runs:
        run_id = str(run.get("runId") or "")
        request_id = str(run.get("clientRequestId") or "")
        if run_id in seen_run_ids:
            continue
        if request_id not in planned_request_ids and run_id not in planned_run_ids and run_id != active_run_id:
            continue
        seen_run_ids.add(run_id)
        tokens_used += _nonnegative_int(run.get("tokensUsed"))
        committed += _nonnegative_int(run.get("budgetTokensCommitted"))
        accounting = str(run.get("tokenAccounting") or "").lower()
        status = str(run.get("status") or "").lower()
        estimated = estimated or accounting in {"estimated", "reserved"} or status == "paused_unknown"
    return {
        "tokensUsed": tokens_used,
        "budgetTokensCommitted": committed,
        "tokenUsageEstimated": estimated,
    }


def _nonnegative_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return 0


def project_metrics(value: Any) -> dict[str, float | None] | None:
    if not isinstance(value, Mapping):
        return None
    projected: dict[str, float | None] = {}
    for key in (
        "totalReturnPct", "benchmarkReturnPct", "excessReturnPct", "maxDrawdownPct"
    ):
        item = value.get(key)
        if item is None:
            projected[key] = None
        elif isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(float(item)):
            projected[key] = None
        else:
            projected[key] = float(item)
    return projected


__all__ = ["build_walk_forward_export", "project_metrics", "project_walk_forward"]
