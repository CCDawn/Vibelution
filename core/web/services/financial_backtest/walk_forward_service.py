"""Owner-scoped A-share rolling backtest orchestration over frozen snapshots."""

from __future__ import annotations

import copy
import logging
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import NAMESPACE_URL, uuid4, uuid5

from core.web.services import runtime_task_registry
from core.web.services.financial_backtest import basket_data, data
from core.web.services.financial_backtest import service as backtest_service
from core.web.services.financial_backtest.contract import (
    MAX_RUNS_PER_AGENT,
    MAX_TOKENS,
    FinancialBacktestConflict,
    FinancialBacktestNotFound,
    canonical_uuid,
    deterministic_run_id,
    normalize_preview_request,
    sha256_json,
)
from core.web.services.financial_backtest.store import FinancialBacktestStore, default_store

from .walk_forward import build_folds, normalize_walk_forward_request, select_candidate
from .walk_forward_data import session_dates, slice_snapshot
from .walk_forward_projection import (
    build_walk_forward_export as _build_walk_forward_export,
    project_metrics as _project_metrics,
    project_walk_forward,
)
from .walk_forward_store import WalkForwardStore, WalkForwardWorkflowCommitError

_LOG = logging.getLogger(__name__)
_WORKFLOW_ACTIVE = {"queued", "running", "stop_requested"}
_RUN_ACTIVE = {"queued", "running", "stop_requested"}
_WORKFLOW_TERMINAL = {"stopped", "paused_unknown", "completed", "failed", "blocked"}
_NOTICE_BASE = (
    "这是回顾性滚动研究：来源回测的行情、策略和结果可能已被查看，不能视为盲测。"
    "仅使用来源回测冻结的A股日线快照；训练窗按超额收益选参，测试窗只评估胜出候选，"
    "测试结果不回流到同折选参。首个测试日收盘作出决策，按现有撮合规则下一交易日开盘成交。"
)


def create_walk_forward_preview(
    agent_id: str,
    source_run_id: str,
    payload: Mapping[str, Any],
    *,
    store: FinancialBacktestStore | None = None,
    walk_store: WalkForwardStore | None = None,
    now_provider: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Freeze a rolling plan from one completed, owner-frozen price-only run."""
    selected_store = store or default_store()
    selected_walk_store = walk_store or WalkForwardStore(selected_store)
    backtest_service._require_owner(agent_id)
    source_id = canonical_uuid(source_run_id, "来源回测标识")
    source_run = selected_store.load_run(agent_id, source_id)
    _validate_source_run(agent_id, source_run, source_id)
    snapshot = backtest_service._load_run_snapshot(agent_id, source_run, selected_store)
    request = normalize_walk_forward_request(payload)
    folds, dropped_sessions = build_folds(session_dates(snapshot), request)
    planned_run_count = len(folds) * (len(request["candidates"]) + 1)
    _check_new_run_capacity(selected_store, agent_id, planned_run_count)

    model_id, model_fingerprint, candidate_source = _freeze_model(agent_id, source_run)
    workflow_id = str(uuid4())
    stage_requests = _stage_requests(agent_id, workflow_id, folds, request["candidates"])
    stage_budgets: dict[str, dict[str, Any]] = {}
    estimated_tokens = 0
    retry_reserve_tokens = 0
    for fold in folds:
        train_snapshot = slice_snapshot(
            snapshot, int(fold["trainStartIndex"]), int(fold["trainEndIndex"])
        )
        test_snapshot = slice_snapshot(
            snapshot, int(fold["testStartIndex"]), int(fold["testEndIndex"])
        )
        train_budgets: dict[str, int] = {}
        train_estimates: dict[str, int] = {}
        test_budgets: dict[str, int] = {}
        test_estimates: dict[str, int] = {}
        for candidate in request["candidates"]:
            candidate_id = str(candidate["candidateId"])
            train_estimates[candidate_id] = _estimate_stage_tokens(
                source_run, train_snapshot, candidate, model_id
            )
            test_estimates[candidate_id] = _estimate_stage_tokens(
                source_run, test_snapshot, candidate, model_id
            )
            train_budgets[candidate_id] = _stage_budget_with_retry_reserve(
                train_estimates[candidate_id]
            )
            test_budgets[candidate_id] = _stage_budget_with_retry_reserve(
                test_estimates[candidate_id]
            )
        test_reserve = max(test_budgets.values())
        test_estimate_reserve = max(test_estimates.values())
        estimated_tokens += sum(train_budgets.values()) + test_reserve
        retry_reserve_tokens += sum(train_estimates.values()) + test_estimate_reserve
        stage_budgets[str(fold["foldId"])] = {
            "train": train_budgets,
            "trainEstimate": train_estimates,
            "test": test_budgets,
            "testEstimate": test_estimates,
            "testReserve": test_reserve,
            "testEstimateReserve": test_estimate_reserve,
            "retryReserveTokens": sum(train_estimates.values()) + test_estimate_reserve,
        }
    if estimated_tokens > request["maxTokens"]:
        raise FinancialBacktestConflict(
            f"滚动验证预估需要{estimated_tokens:,} tokens，超过总预算{request['maxTokens']:,} tokens"
        )

    now = backtest_service._now(now_provider)
    plan = {
        "schemaVersion": 1,
        "sourceRunId": source_id,
        "sourceDataHash": str(source_run.get("dataHash") or ""),
        "sourceParamsHash": str(source_run.get("paramsHash") or ""),
        "sourceModelId": model_id,
        "sourceModelFingerprint": model_fingerprint,
        "sourceModelCandidateSource": candidate_source,
        "sourceParams": copy.deepcopy(dict(source_run.get("params") or {})),
        "request": copy.deepcopy(request),
        "candidates": copy.deepcopy(request["candidates"]),
        "folds": folds,
        "stageBudgets": stage_budgets,
        "stageRequests": stage_requests,
        "plannedRunCount": planned_run_count,
        "selectionMetric": "metrics.excessReturnPct",
        "selectionRule": "每折只用训练run的excessReturnPct，数值越高越优",
        "tieBreakRule": "excessReturnPct相同时按candidateId升序",
        "testWindowRule": (
            "测试窗不重叠；stepSessions大于testSessions时，跨测试窗间隔不计入测试指标，"
            "但可能进入后续训练；不足完整测试窗的尾部不纳入评估"
        ),
        "retryReserveRule": "每个计划执行的子回测预算为单次估算的2倍，含一次完整子任务重试余量",
        "retryReserveTokens": retry_reserve_tokens,
        "dataBoundaryRule": "训练窗终日收盘只作为观察边界，不生成越界到测试窗的训练成交",
    }
    plan_hash = sha256_json(plan)
    notice = _NOTICE_BASE
    if dropped_sessions:
        notice += f" 末尾有{dropped_sessions}个交易日不足一个完整训练加测试窗，已明确舍弃。"
    if len(folds) > 1 and request["stepSessions"] > request["testSessions"]:
        gap = request["stepSessions"] - request["testSessions"]
        notice += (
            f" 相邻测试窗间有{gap}个交易日不计入任何测试窗指标；这些日期可能进入后续训练。"
        )
    notice += " 预估预算已包含每个实际执行子任务一次完整重试的预留额度。"
    workflow = {
        "agentId": str(agent_id),
        "workflowId": workflow_id,
        "sourceRunId": source_id,
        "status": "preview",
        "planHash": plan_hash,
        "trainSessions": request["trainSessions"],
        "testSessions": request["testSessions"],
        "stepSessions": request["stepSessions"],
        "maxTokens": request["maxTokens"],
        "estimatedTokens": estimated_tokens,
        "candidates": copy.deepcopy(request["candidates"]),
        "folds": [
            {
                "foldId": str(fold["foldId"]),
                "trainStart": str(fold["trainStart"]),
                "trainEnd": str(fold["trainEnd"]),
                "testStart": str(fold["testStart"]),
                "testEnd": str(fold["testEnd"]),
                "selectedCandidateId": None,
                "testRunId": None,
                "status": "pending",
                "metrics": None,
            }
            for fold in folds
        ],
        "activeRunId": None,
        "terminalReason": None,
        "createdAt": backtest_service._iso(now),
        "updatedAt": backtest_service._iso(now),
        "notice": notice,
        "plan": plan,
        "execution": {
            "foldIndex": 0,
            "stage": "train",
            "activeStage": None,
            "trainRunIds": {},
            "trainMetrics": {},
            "stopIntent": False,
        },
    }
    selected_walk_store.create(agent_id, workflow)
    return project_walk_forward(workflow, store=selected_store)


def start_walk_forward(
    agent_id: str,
    workflow_id: str,
    *,
    store: FinancialBacktestStore | None = None,
    walk_store: WalkForwardStore | None = None,
    now_provider: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    selected_store = store or default_store()
    selected_walk_store = walk_store or WalkForwardStore(selected_store)
    backtest_service._require_owner(agent_id)
    with selected_walk_store.locked(agent_id, workflow_id) as workflow:
        status = str(workflow.get("status") or "")
        if status in _WORKFLOW_ACTIVE:
            return project_walk_forward(workflow, store=selected_store)
        if status != "preview":
            raise FinancialBacktestConflict("当前滚动验证状态不能启动")
        snapshot = _verify_frozen_plan(agent_id, workflow, selected_store)
        _verify_source_and_model(agent_id, workflow, snapshot)
        _check_workflow_capacity(agent_id, workflow, selected_store)
        workflow["status"] = "queued"
        workflow["terminalReason"] = None
        workflow["updatedAt"] = backtest_service._iso(backtest_service._now(now_provider))
        _sync_runtime_task(agent_id, workflow, rearm=True)
        return project_walk_forward(workflow, store=selected_store)


def get_walk_forward(
    agent_id: str,
    workflow_id: str,
    *,
    store: FinancialBacktestStore | None = None,
    walk_store: WalkForwardStore | None = None,
) -> dict[str, Any]:
    _require_owner(agent_id)
    selected_store = store or default_store()
    record = (walk_store or WalkForwardStore(selected_store)).load(agent_id, workflow_id)
    return project_walk_forward(record, store=selected_store)


def list_walk_forward_workflows(
    agent_id: str,
    *,
    store: FinancialBacktestStore | None = None,
    walk_store: WalkForwardStore | None = None,
) -> dict[str, Any]:
    _require_owner(agent_id)
    selected_store = store or default_store()
    selected = walk_store or WalkForwardStore(selected_store)
    child_runs = selected_store.list_runs(agent_id)
    return {
        "items": [
            project_walk_forward(row, child_runs=child_runs)
            for row in selected.list(agent_id)
        ]
    }


def stop_walk_forward(
    agent_id: str,
    workflow_id: str,
    *,
    store: FinancialBacktestStore | None = None,
    walk_store: WalkForwardStore | None = None,
    now_provider: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    selected_store = store or default_store()
    selected_walk_store = walk_store or WalkForwardStore(selected_store)
    backtest_service._require_owner(agent_id)
    with selected_walk_store.locked(agent_id, workflow_id) as workflow:
        status = str(workflow.get("status") or "")
        if status in _WORKFLOW_TERMINAL:
            return project_walk_forward(workflow, store=selected_store)
        execution = workflow.get("execution") if isinstance(workflow.get("execution"), dict) else {}
        execution["stopIntent"] = True
        _apply_workflow_stop_intent(
            agent_id,
            workflow,
            selected_store,
            default_reason=(
                "用户停止了尚未启动的滚动验证"
                if status == "preview"
                else "用户停止了滚动验证，后续折不会启动"
            ),
        )
        workflow["execution"] = execution
        workflow["updatedAt"] = backtest_service._iso(backtest_service._now(now_provider))
        _sync_runtime_task(agent_id, workflow)
        return project_walk_forward(workflow, store=selected_store)


def resume_walk_forward(
    agent_id: str,
    workflow_id: str,
    *,
    store: FinancialBacktestStore | None = None,
    walk_store: WalkForwardStore | None = None,
    now_provider: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    selected_store = store or default_store()
    selected_walk_store = walk_store or WalkForwardStore(selected_store)
    backtest_service._require_owner(agent_id)
    with selected_walk_store.locked(agent_id, workflow_id) as workflow:
        if str(workflow.get("status") or "") not in {"stopped", "paused_unknown", "failed"}:
            raise FinancialBacktestConflict("当前滚动验证状态不能恢复")
        snapshot = _verify_frozen_plan(agent_id, workflow, selected_store)
        _verify_source_and_model(agent_id, workflow, snapshot)
        if not str(workflow.get("activeRunId") or ""):
            _reconcile_current_child(agent_id, workflow, selected_store)
        active_run_id = str(workflow.get("activeRunId") or "")
        if active_run_id:
            child = selected_store.load_run(agent_id, active_run_id)
            child_status = str(child.get("status") or "")
            if child_status == "paused_unknown":
                raise FinancialBacktestConflict(
                    "为避免未知调用重复计费，请先通过普通回测恢复接口确认该子任务，再恢复滚动验证"
                )
            if child_status == "stopped":
                backtest_service.resume_financial_backtest_run(
                    agent_id, active_run_id, store=selected_store
                )
            elif child_status in {"failed", "blocked"}:
                raise FinancialBacktestConflict("当前回测子任务已失败或阻断，不能继续滚动验证")
            elif child_status not in _RUN_ACTIVE | {"completed"}:
                raise FinancialBacktestConflict("当前回测子任务状态无法恢复")
        _check_workflow_capacity(agent_id, workflow, selected_store)
        execution = workflow.get("execution") if isinstance(workflow.get("execution"), dict) else {}
        execution["stopIntent"] = False
        execution.pop("advanceErrorStatus", None)
        execution.pop("advanceErrorReason", None)
        workflow["execution"] = execution
        workflow["status"] = "queued"
        workflow["terminalReason"] = None
        workflow["updatedAt"] = backtest_service._iso(backtest_service._now(now_provider))
        _sync_runtime_task(agent_id, workflow, rearm=True)
        return project_walk_forward(workflow, store=selected_store)


def advance_walk_forward_workflows(
    agent_id: str,
    *,
    store: FinancialBacktestStore | None = None,
    walk_store: WalkForwardStore | None = None,
    now_provider: Callable[[], datetime] | None = None,
    limit: int = 1,
) -> int:
    """Advance at most ``limit`` owner workflows without making model calls."""
    selected_store = store or default_store()
    selected_walk_store = walk_store or WalkForwardStore(selected_store)
    try:
        records = selected_walk_store.list(agent_id)
    except FinancialBacktestNotFound:
        return 0
    active = [row for row in records if str(row.get("status") or "") in _WORKFLOW_ACTIVE]
    active.sort(key=lambda row: (str(row.get("createdAt") or ""), str(row.get("workflowId") or "")))
    processed = 0
    for row in active[: max(1, min(int(limit), 8))]:
        workflow_id = str(row.get("workflowId") or "")
        if not workflow_id:
            continue
        try:
            changed = _advance_one(
                agent_id,
                workflow_id,
                selected_store,
                selected_walk_store,
                now_provider=now_provider,
            )
        except WalkForwardWorkflowCommitError as exc:
            # A child may already be durable while this workflow transition is
            # not. Leave the last durable workflow state intact; the next pass
            # will reconcile the stage's deterministic request ID before it can
            # create another child.
            _LOG.warning("A-share walk-forward transition will be reconciled on retry: %s", exc)
            changed = False
        except Exception as exc:  # Keep the shared runtime worker alive; persist a bounded failure.
            _LOG.exception("A-share walk-forward advancement failed")
            changed = _record_advance_error(
                agent_id,
                workflow_id,
                selected_store,
                selected_walk_store,
                exc,
                now_provider=now_provider,
            )
        if changed:
            processed += 1
    return processed


def export_walk_forward(
    agent_id: str,
    workflow_id: str,
    *,
    store: FinancialBacktestStore | None = None,
    walk_store: WalkForwardStore | None = None,
) -> dict[str, Any]:
    """Export verified frozen evidence through the bounded projection module."""
    _require_owner(agent_id)
    selected_store = store or default_store()
    selected_walk_store = walk_store or WalkForwardStore(selected_store)
    workflow = selected_walk_store.load(agent_id, workflow_id)
    _verify_plan_hash(workflow)
    projected = project_walk_forward(workflow, store=selected_store)
    return _build_walk_forward_export(workflow, projected)

def _advance_one(
    agent_id: str,
    workflow_id: str,
    selected_store: FinancialBacktestStore,
    selected_walk_store: WalkForwardStore,
    *,
    now_provider: Callable[[], datetime] | None,
) -> bool:
    changed = False
    with selected_walk_store.locked(agent_id, workflow_id) as workflow:
        if str(workflow.get("status") or "") not in _WORKFLOW_ACTIVE:
            return False
        snapshot = _verify_frozen_plan(agent_id, workflow, selected_store)
        _verify_source_and_model(agent_id, workflow, snapshot)
        execution = workflow.get("execution")
        if not isinstance(execution, dict):
            raise FinancialBacktestConflict("滚动验证执行状态损坏")

        if bool(execution.get("stopIntent")) or str(workflow.get("status") or "") == "stop_requested":
            _apply_workflow_stop_intent(
                agent_id,
                workflow,
                selected_store,
                default_reason="用户停止了滚动验证，后续折不会启动",
            )
            workflow["updatedAt"] = backtest_service._iso(backtest_service._now(now_provider))
            _sync_runtime_task(agent_id, workflow)
            return True

        active_run_id = str(workflow.get("activeRunId") or "")
        if active_run_id:
            child = selected_store.load_run(agent_id, active_run_id)
            child_status = str(child.get("status") or "")
            if child_status in _RUN_ACTIVE:
                if workflow.get("status") != "running":
                    workflow["status"] = "running"
                    workflow["updatedAt"] = backtest_service._iso(backtest_service._now(now_provider))
                    _sync_runtime_task(agent_id, workflow)
                    changed = True
                return changed
            if child_status == "paused_unknown":
                workflow["status"] = "paused_unknown"
                workflow["terminalReason"] = "子回测模型调用结果未知，需按普通回测流程确认后才能继续"
                workflow["updatedAt"] = backtest_service._iso(backtest_service._now(now_provider))
                _sync_runtime_task(agent_id, workflow)
                return True
            if child_status != "completed":
                if child_status == "stopped":
                    workflow["status"] = "stopped"
                    workflow["terminalReason"] = "回测子任务已停止；可恢复后继续该折"
                elif child_status in {"blocked", "failed"}:
                    workflow["status"] = child_status
                    workflow["terminalReason"] = str(child.get("terminalReason") or "回测子任务未完成")
                else:
                    workflow["status"] = "failed"
                    workflow["terminalReason"] = "回测子任务进入无法识别的终态"
                workflow["updatedAt"] = backtest_service._iso(backtest_service._now(now_provider))
                _sync_runtime_task(agent_id, workflow)
                return True
            _record_child_completion(workflow, child)
            workflow["activeRunId"] = None
            execution["activeStage"] = None
            changed = True

        folds = workflow.get("plan", {}).get("folds") if isinstance(workflow.get("plan"), Mapping) else None
        candidates = workflow.get("plan", {}).get("candidates") if isinstance(workflow.get("plan"), Mapping) else None
        if not isinstance(folds, list) or not isinstance(candidates, list):
            raise FinancialBacktestConflict("滚动验证冻结计划缺少折或候选")
        fold_index = int(execution.get("foldIndex") or 0)
        if fold_index >= len(folds):
            workflow["status"] = "completed"
            workflow["terminalReason"] = None
            workflow["updatedAt"] = backtest_service._iso(backtest_service._now(now_provider))
            _sync_runtime_task(agent_id, workflow)
            return True
        fold_plan = folds[fold_index]
        fold_id = str(fold_plan.get("foldId") or "")
        if not fold_id:
            raise FinancialBacktestConflict("滚动验证折标识无效")

        stage = str(execution.get("stage") or "train")
        train_metrics = execution.setdefault("trainMetrics", {})
        if not isinstance(train_metrics, dict):
            raise FinancialBacktestConflict("训练候选评分记录损坏")
        fold_train_metrics = train_metrics.setdefault(fold_id, {})
        if not isinstance(fold_train_metrics, dict):
            raise FinancialBacktestConflict("训练候选评分记录损坏")
        if stage == "train":
            missing = [
                candidate
                for candidate in candidates
                if str(candidate.get("candidateId") or "") not in fold_train_metrics
            ]
            if missing:
                candidate = missing[0]
                _start_child(
                    agent_id,
                    workflow,
                    snapshot,
                    fold_plan,
                    candidate,
                    "train",
                    selected_store,
                    now_provider=now_provider,
                )
                changed = True
            else:
                selected_id = select_candidate(candidates, fold_train_metrics)
                _set_fold_selection(workflow, fold_id, selected_id)
                execution["stage"] = "test"
                stage = "test"
                changed = True
        if stage == "test":
            selected_id = next(
                (
                    str(row.get("selectedCandidateId") or "")
                    for row in workflow.get("folds", [])
                    if isinstance(row, Mapping) and str(row.get("foldId") or "") == fold_id
                ),
                "",
            )
            candidate = next(
                (row for row in candidates if str(row.get("candidateId") or "") == selected_id),
                None,
            )
            if candidate is None:
                raise FinancialBacktestConflict("训练阶段尚未确定测试候选")
            _start_child(
                agent_id,
                workflow,
                snapshot,
                fold_plan,
                candidate,
                "test",
                selected_store,
                now_provider=now_provider,
            )
            changed = True
        workflow["execution"] = execution
        workflow["status"] = "running"
        workflow["updatedAt"] = backtest_service._iso(backtest_service._now(now_provider))
        _sync_runtime_task(agent_id, workflow)
        return changed


def _record_child_completion(workflow: dict[str, Any], child: Mapping[str, Any]) -> None:
    execution = workflow.get("execution")
    active_stage = execution.get("activeStage") if isinstance(execution, Mapping) else None
    if not isinstance(execution, dict) or not isinstance(active_stage, Mapping):
        raise FinancialBacktestConflict("完成的回测子任务缺少阶段关联，工作流已阻断")
    if str(active_stage.get("runId") or "") != str(child.get("runId") or ""):
        raise FinancialBacktestConflict("回测子任务与冻结阶段关联不匹配")
    fold_id = str(active_stage.get("foldId") or "")
    candidate_id = str(active_stage.get("candidateId") or "")
    stage = str(active_stage.get("stage") or "")
    metrics = _completed_metrics(child)
    if stage == "train":
        train_metrics = execution.setdefault("trainMetrics", {})
        fold_metrics = train_metrics.setdefault(fold_id, {})
        if candidate_id in fold_metrics:
            if fold_metrics[candidate_id] != metrics:
                raise FinancialBacktestConflict("训练候选已记录不同结果，不能重复覆盖")
        else:
            fold_metrics[candidate_id] = metrics
        run_ids = execution.setdefault("trainRunIds", {})
        fold_runs = run_ids.setdefault(fold_id, {})
        existing = fold_runs.get(candidate_id)
        run_id = str(child.get("runId") or "")
        if existing and str(existing) != run_id:
            raise FinancialBacktestConflict("训练候选运行标识发生变化")
        fold_runs[candidate_id] = run_id
        execution["stage"] = "train"
        return
    if stage == "test":
        folds = workflow.get("folds")
        fold = next(
            (row for row in folds if isinstance(row, dict) and str(row.get("foldId") or "") == fold_id),
            None,
        ) if isinstance(folds, list) else None
        if fold is None or str(fold.get("selectedCandidateId") or "") != candidate_id:
            raise FinancialBacktestConflict("测试候选与训练阶段选择不匹配")
        fold["testRunId"] = str(child.get("runId") or "")
        fold["metrics"] = metrics
        fold["status"] = "completed"
        execution["foldIndex"] = int(execution.get("foldIndex") or 0) + 1
        execution["stage"] = "train"
        return
    raise FinancialBacktestConflict("回测子任务阶段无效")


def _start_child(
    agent_id: str,
    workflow: dict[str, Any],
    source_snapshot: data.BacktestSnapshot | basket_data.BasketSnapshot,
    fold: Mapping[str, Any],
    candidate: Mapping[str, Any],
    stage: str,
    selected_store: FinancialBacktestStore,
    *,
    now_provider: Callable[[], datetime] | None,
) -> None:
    workflow_id = str(workflow.get("workflowId") or "")
    fold_id = str(fold.get("foldId") or "")
    candidate_id = str(candidate.get("candidateId") or "")
    candidate_index = candidate_id
    plan = workflow.get("plan") if isinstance(workflow.get("plan"), Mapping) else {}
    client_request_id = _stage_client_request_id(plan, fold_id, stage, candidate_index)
    if not client_request_id:
        raise FinancialBacktestConflict("冻结计划缺少子回测幂等标识")
    _check_workflow_capacity(agent_id, workflow, selected_store)

    # A previous transition may have saved the ordinary child but failed to
    # save this workflow's activeRunId. Reattach that frozen child before any
    # preview/model work, including when it is already completed or unknown.
    child_run_id = deterministic_run_id(agent_id, client_request_id)
    try:
        existing_child = selected_store.load_run(agent_id, child_run_id)
    except FinancialBacktestNotFound:
        existing_child = None
    if existing_child is not None:
        _validate_planned_child_run(agent_id, client_request_id, existing_child)
        _attach_child_to_workflow(
            workflow,
            fold_id=fold_id,
            candidate_id=candidate_id,
            stage=stage,
            client_request_id=client_request_id,
            run_id=str(existing_child.get("runId") or ""),
        )
        return

    if stage == "train":
        start_index, end_index = int(fold["trainStartIndex"]), int(fold["trainEndIndex"])
        stage_budget = int(plan["stageBudgets"][fold_id]["train"][candidate_id])
    else:
        start_index, end_index = int(fold["testStartIndex"]), int(fold["testEndIndex"])
        stage_budget = int(plan["stageBudgets"][fold_id]["test"][candidate_id])
    sliced = slice_snapshot(source_snapshot, start_index, end_index)
    request = _stage_request(workflow, sliced, candidate, stage_budget)
    source_id = str(workflow.get("sourceRunId") or "")
    model_id = str(plan.get("sourceModelId") or "")
    candidate_source = str(plan.get("sourceModelCandidateSource") or "")
    preview = backtest_service._create_preview(
        agent_id,
        request,
        selected_store,
        model_id=model_id,
        snapshot=sliced,
        schedule=backtest_service._build_schedule(sliced, request),
        now_provider=now_provider,
        source_run_id=source_id,
        model_candidate_source=candidate_source,
    )
    if not preview.get("canStart"):
        raise FinancialBacktestConflict(
            str(preview.get("blockReason") or "回测子任务预览未通过预算校验")
        )
    child = backtest_service.start_financial_backtest_run(
        agent_id,
        client_request_id,
        str(preview["previewId"]),
        store=selected_store,
        now_provider=now_provider,
    )
    run_id = str(child.get("runId") or "")
    if not run_id:
        raise FinancialBacktestConflict("回测子任务未返回运行标识")
    _attach_child_to_workflow(
        workflow,
        fold_id=fold_id,
        candidate_id=candidate_id,
        stage=stage,
        client_request_id=client_request_id,
        run_id=run_id,
    )


def _stage_client_request_id(
    plan: Mapping[str, Any], fold_id: str, stage: str, candidate_id: str
) -> str:
    request_map = plan.get("stageRequests") if isinstance(plan.get("stageRequests"), Mapping) else {}
    request_for_fold = request_map.get(fold_id) if isinstance(request_map.get(fold_id), Mapping) else {}
    stage_map = request_for_fold.get(stage) if isinstance(request_for_fold.get(stage), Mapping) else {}
    return str(stage_map.get(candidate_id) or "")


def _attach_child_to_workflow(
    workflow: dict[str, Any],
    *,
    fold_id: str,
    candidate_id: str,
    stage: str,
    client_request_id: str,
    run_id: str,
) -> None:
    execution = workflow.get("execution")
    if not isinstance(execution, dict):
        raise FinancialBacktestConflict("滚动验证执行状态损坏")
    active_stage = {
        "stage": stage,
        "foldId": fold_id,
        "candidateId": candidate_id,
        "clientRequestId": client_request_id,
        "runId": run_id,
    }
    execution["activeStage"] = active_stage
    if stage == "train":
        train_run_ids = execution.setdefault("trainRunIds", {})
        fold_run_ids = train_run_ids.setdefault(fold_id, {})
        existing = fold_run_ids.get(candidate_id)
        if existing and str(existing) != run_id:
            raise FinancialBacktestConflict("训练候选运行标识发生变化")
        fold_run_ids[candidate_id] = run_id
    workflow["execution"] = execution
    workflow["activeRunId"] = run_id
    workflow["status"] = "running"


def _current_stage_target(
    workflow: dict[str, Any],
) -> tuple[Mapping[str, Any], Mapping[str, Any], str] | None:
    """Resolve the only child that can be created at the durable workflow cursor."""
    plan = workflow.get("plan") if isinstance(workflow.get("plan"), Mapping) else {}
    folds = plan.get("folds") if isinstance(plan.get("folds"), list) else []
    candidates = plan.get("candidates") if isinstance(plan.get("candidates"), list) else []
    execution = workflow.get("execution")
    if not isinstance(execution, dict):
        raise FinancialBacktestConflict("滚动验证执行状态损坏")
    fold_index = int(execution.get("foldIndex") or 0)
    if fold_index < 0 or fold_index >= len(folds) or not candidates:
        return None
    fold_plan = folds[fold_index]
    if not isinstance(fold_plan, Mapping):
        raise FinancialBacktestConflict("滚动验证冻结折损坏")
    fold_id = str(fold_plan.get("foldId") or "")
    if not fold_id:
        raise FinancialBacktestConflict("滚动验证折标识无效")

    stage = str(execution.get("stage") or "train")
    metrics = execution.get("trainMetrics")
    train_metrics = metrics.get(fold_id) if isinstance(metrics, Mapping) else {}
    if not isinstance(train_metrics, Mapping):
        raise FinancialBacktestConflict("训练候选评分记录损坏")
    if stage == "train":
        missing = [
            candidate
            for candidate in candidates
            if isinstance(candidate, Mapping)
            and str(candidate.get("candidateId") or "") not in train_metrics
        ]
        if missing:
            return fold_plan, missing[0], "train"
        selected_id = select_candidate(candidates, train_metrics)
        _set_fold_selection(workflow, fold_id, selected_id)
        execution["stage"] = "test"
        stage = "test"
    if stage != "test":
        raise FinancialBacktestConflict("回测子任务阶段无效")

    selected_id = ""
    fold_rows = workflow.get("folds")
    if isinstance(fold_rows, list):
        selected_id = next(
            (
                str(row.get("selectedCandidateId") or "")
                for row in fold_rows
                if isinstance(row, Mapping) and str(row.get("foldId") or "") == fold_id
            ),
            "",
        )
    if not selected_id:
        selected_id = select_candidate(candidates, train_metrics)
        _set_fold_selection(workflow, fold_id, selected_id)
    candidate = next(
        (
            row
            for row in candidates
            if isinstance(row, Mapping) and str(row.get("candidateId") or "") == selected_id
        ),
        None,
    )
    if candidate is None:
        raise FinancialBacktestConflict("训练阶段尚未确定测试候选")
    return fold_plan, candidate, "test"


def _reconcile_current_child(
    agent_id: str,
    workflow: dict[str, Any],
    selected_store: FinancialBacktestStore,
) -> Mapping[str, Any] | None:
    """Attach a durable child at the current frozen cursor without rerunning it."""
    target = _current_stage_target(workflow)
    if target is None:
        return None
    fold, candidate, stage = target
    fold_id = str(fold.get("foldId") or "")
    candidate_id = str(candidate.get("candidateId") or "")
    plan = workflow.get("plan") if isinstance(workflow.get("plan"), Mapping) else {}
    request_id = _stage_client_request_id(plan, fold_id, stage, candidate_id)
    if not request_id:
        raise FinancialBacktestConflict("冻结计划缺少子回测幂等标识")
    run_id = deterministic_run_id(agent_id, request_id)
    try:
        child = selected_store.load_run(agent_id, run_id)
    except FinancialBacktestNotFound:
        return None
    _validate_planned_child_run(agent_id, request_id, child)
    _attach_child_to_workflow(
        workflow,
        fold_id=fold_id,
        candidate_id=candidate_id,
        stage=stage,
        client_request_id=request_id,
        run_id=str(child.get("runId") or ""),
    )
    return child


def _planned_child_records(
    agent_id: str,
    workflow: Mapping[str, Any],
    selected_store: FinancialBacktestStore,
) -> list[dict[str, Any]]:
    """Load existing runs addressed by the frozen deterministic stage IDs."""
    plan = workflow.get("plan") if isinstance(workflow.get("plan"), Mapping) else {}
    request_map = plan.get("stageRequests") if isinstance(plan.get("stageRequests"), Mapping) else {}
    records: list[dict[str, Any]] = []
    seen_requests: set[str] = set()
    for fold_id, raw_fold in sorted(request_map.items(), key=lambda pair: str(pair[0])):
        if not isinstance(raw_fold, Mapping):
            raise FinancialBacktestConflict("冻结计划缺少子回测阶段清单")
        for stage in ("train", "test"):
            stage_map = raw_fold.get(stage)
            if not isinstance(stage_map, Mapping):
                raise FinancialBacktestConflict("冻结计划缺少子回测阶段清单")
            for candidate_id, raw_request_id in sorted(
                stage_map.items(), key=lambda pair: str(pair[0])
            ):
                request_id = str(raw_request_id or "")
                if not request_id or request_id in seen_requests:
                    raise FinancialBacktestConflict("冻结计划子回测幂等标识缺失或重复")
                seen_requests.add(request_id)
                run_id = deterministic_run_id(agent_id, request_id)
                try:
                    child = selected_store.load_run(agent_id, run_id)
                except FinancialBacktestNotFound:
                    continue
                _validate_planned_child_run(agent_id, request_id, child)
                records.append(
                    {
                        "foldId": str(fold_id),
                        "candidateId": str(candidate_id),
                        "stage": stage,
                        "clientRequestId": request_id,
                        "run": child,
                    }
                )
    return records


def _record_is_unattached(
    workflow: Mapping[str, Any], record: Mapping[str, Any]
) -> bool:
    run = record.get("run") if isinstance(record.get("run"), Mapping) else {}
    run_id = str(run.get("runId") or "")
    if not run_id:
        return False
    if run_id == str(workflow.get("activeRunId") or ""):
        return True
    execution = workflow.get("execution") if isinstance(workflow.get("execution"), Mapping) else {}
    fold_id = str(record.get("foldId") or "")
    candidate_id = str(record.get("candidateId") or "")
    if record.get("stage") == "train":
        train_runs = execution.get("trainRunIds") if isinstance(execution.get("trainRunIds"), Mapping) else {}
        fold_runs = train_runs.get(fold_id) if isinstance(train_runs.get(fold_id), Mapping) else {}
        return str(fold_runs.get(candidate_id) or "") != run_id
    folds = workflow.get("folds") if isinstance(workflow.get("folds"), list) else []
    recorded_test_id = next(
        (
            str(row.get("testRunId") or "")
            for row in folds
            if isinstance(row, Mapping) and str(row.get("foldId") or "") == fold_id
        ),
        "",
    )
    return recorded_test_id != run_id


def _apply_workflow_stop_intent(
    agent_id: str,
    workflow: dict[str, Any],
    selected_store: FinancialBacktestStore,
    *,
    default_reason: str,
) -> None:
    """Stop every persisted child for this plan, including an unattached orphan."""
    execution = workflow.get("execution")
    if not isinstance(execution, dict):
        raise FinancialBacktestConflict("滚动验证执行状态损坏")
    execution["stopIntent"] = True
    records = _planned_child_records(agent_id, workflow, selected_store)
    pending = [row for row in records if _record_is_unattached(workflow, row)]
    for row in pending:
        child = row["run"]
        child_id = str(child.get("runId") or "")
        child_status = str(child.get("status") or "")
        if child_id and child_status in _RUN_ACTIVE and child_status != "stop_requested":
            try:
                backtest_service.request_financial_backtest_stop(
                    agent_id, child_id, store=selected_store
                )
            except Exception:
                _LOG.exception("Could not stop an A-share walk-forward child after stop intent")

    refreshed: list[dict[str, Any]] = []
    for row in pending:
        child_id = str(row["run"].get("runId") or "")
        try:
            row = {**row, "run": selected_store.load_run(agent_id, child_id)}
        except Exception:
            _LOG.exception("Could not reload an A-share walk-forward child after stop intent")
        refreshed.append(row)
    active = [row for row in refreshed if str(row["run"].get("status") or "") in _RUN_ACTIVE]
    unknown = [row for row in refreshed if str(row["run"].get("status") or "") == "paused_unknown"]

    target = None
    active_run_id = str(workflow.get("activeRunId") or "")
    target = next(
        (row for row in refreshed if str(row["run"].get("runId") or "") == active_run_id),
        None,
    )
    if target is None:
        target = active[0] if active else (unknown[0] if unknown else (refreshed[0] if refreshed else None))
    if target is not None and not active_run_id:
        try:
            if str(target.get("stage") or "") == "test":
                expected = _current_stage_target(workflow)
                if expected is None or (
                    str(expected[0].get("foldId") or "") != str(target.get("foldId") or "")
                    or str(expected[1].get("candidateId") or "") != str(target.get("candidateId") or "")
                    or expected[2] != "test"
                ):
                    raise FinancialBacktestConflict("未关联测试子回测与当前训练胜出候选不匹配")
            _attach_child_to_workflow(
                workflow,
                fold_id=str(target["foldId"]),
                candidate_id=str(target["candidateId"]),
                stage=str(target["stage"]),
                client_request_id=str(target["clientRequestId"]),
                run_id=str(target["run"].get("runId") or ""),
            )
        except FinancialBacktestConflict:
            # Preserve the stop request even when evidence cannot be safely
            # projected back onto the workflow cursor.
            _LOG.exception("Could not attach an A-share child while stopping its workflow")

    error_status = str(execution.get("advanceErrorStatus") or "")
    error_reason = str(execution.get("advanceErrorReason") or "")
    if active:
        workflow["status"] = "stop_requested"
        workflow["terminalReason"] = "正在等待已创建回测子任务安全停止"
    elif unknown:
        workflow["status"] = "paused_unknown"
        workflow["terminalReason"] = "子回测存在结果未知的模型调用；需先按普通回测流程确认后再继续"
    elif error_status in {"failed", "blocked"}:
        workflow["status"] = error_status
        workflow["terminalReason"] = error_reason[:500] or default_reason
    else:
        workflow["status"] = "stopped"
        workflow["terminalReason"] = default_reason
    workflow["execution"] = execution


def _stage_request(
    workflow: Mapping[str, Any],
    snapshot: data.BacktestSnapshot | basket_data.BasketSnapshot,
    candidate: Mapping[str, Any],
    max_tokens: int,
) -> dict[str, Any]:
    plan = workflow.get("plan") if isinstance(workflow.get("plan"), Mapping) else {}
    params = plan.get("sourceParams") if isinstance(plan.get("sourceParams"), Mapping) else {}
    model_id = str(plan.get("sourceModelId") or "")
    strategy = str(params.get("strategy") or "").strip()
    if not strategy:
        raise FinancialBacktestConflict("来源回测缺少冻结策略，无法生成滚动子任务")
    payload: dict[str, Any] = {
        "symbol": snapshot.symbol if isinstance(snapshot, data.BacktestSnapshot) else None,
        "symbols": list(snapshot.symbols) if isinstance(snapshot, basket_data.BasketSnapshot) else None,
        "startDate": snapshot.start_date,
        "endDate": snapshot.end_date,
        "outOfSampleStartDate": None,
        "strategy": strategy,
        "initialCash": params.get("initialCash", 100_000),
        "maxPositionPct": int(candidate["maxPositionPct"]),
        "decisionInterval": params.get("decisionInterval", 5),
        "commissionBps": params.get("commissionBps", 3),
        "minimumCommission": params.get("minimumCommission", 5),
        "slippageBps": params.get("slippageBps", 5),
        "maxDecisions": params.get("maxDecisions", 500),
        "maxTokens": max(512, int(max_tokens)),
        "modelId": model_id,
        "researchInput": "price_only",
    }
    if "maxParticipationPct" in params:
        payload["maxParticipationPct"] = params["maxParticipationPct"]
    if "quantityRuleVersion" in params:
        payload["quantityRuleVersion"] = params["quantityRuleVersion"]
    request = normalize_preview_request(payload)
    # Match older A-share runs that predate explicit participation/quantity fields.
    if "maxParticipationPct" not in params:
        request["params"].pop("maxParticipationPct", None)
    if "quantityRuleVersion" not in params:
        request["params"].pop("quantityRuleVersion", None)
    return request


def _estimate_stage_tokens(
    source_run: Mapping[str, Any],
    snapshot: data.BacktestSnapshot | basket_data.BasketSnapshot,
    candidate: Mapping[str, Any],
    model_id: str,
) -> int:
    workflow_stub = {
        "plan": {
            "sourceModelId": model_id,
            "sourceParams": dict(source_run.get("params") or {}),
        }
    }
    request = _stage_request(workflow_stub, snapshot, candidate, MAX_TOKENS)
    schedule = backtest_service._build_schedule(snapshot, request)
    params = {
        **dict(request["params"]),
        "strategy": request["strategy"],
        "maxTokens": request["maxTokens"],
        "outOfSampleStartDate": backtest_service._out_of_sample_start_date(snapshot),
    }
    estimated, _reserved_output, _reservation = backtest_service._estimate_budget(
        snapshot, params, schedule
    )
    if estimated < 512 or estimated > MAX_TOKENS:
        raise FinancialBacktestConflict("单个滚动子任务的预算估算超出支持范围")
    return int(estimated)


def _stage_budget_with_retry_reserve(estimated_tokens: int) -> int:
    """Allocate one full-stage retry allowance without exceeding child limits."""
    if (
        isinstance(estimated_tokens, bool)
        or not isinstance(estimated_tokens, int)
        or estimated_tokens < 512
    ):
        raise FinancialBacktestConflict("滚动子任务的单次预算估算无效")
    allocated = estimated_tokens * 2
    if allocated > MAX_TOKENS:
        raise FinancialBacktestConflict(
            "单个滚动子任务加上一次完整重试预留后超过子回测预算上限"
        )
    return allocated


def _validate_source_run(
    agent_id: str, source_run: Mapping[str, Any], source_run_id: str
) -> None:
    if str(source_run.get("agentId") or "") != str(agent_id):
        raise FinancialBacktestNotFound("来源回测不存在")
    if str(source_run.get("runId") or "") != source_run_id:
        raise FinancialBacktestNotFound("来源回测不存在")
    if str(source_run.get("status") or "") != "completed":
        raise FinancialBacktestConflict("只有已完成的A股回测可以创建滚动验证")
    if str(source_run.get("researchInput") or "price_only") != "price_only":
        raise FinancialBacktestConflict("滚动验证首版只支持纯行情输入；公告研究来源不能混入冻结折")
    if not str(source_run.get("dataHash") or "") or not str(source_run.get("paramsHash") or ""):
        raise FinancialBacktestConflict("来源回测缺少冻结行情或参数摘要")
    if not str(source_run.get("modelId") or "") or not str(source_run.get("modelFingerprint") or ""):
        raise FinancialBacktestConflict("来源回测缺少冻结模型身份")


def _freeze_model(
    agent_id: str, source_run: Mapping[str, Any]
) -> tuple[str, str, str]:
    model_id = str(source_run.get("modelId") or "")
    if backtest_service._source_run_id(source_run):
        candidate_source = backtest_service._validate_candidate_model(model_id)
    else:
        _agent, bound_model_id = backtest_service._require_owner_and_model(agent_id, model_id)
        if bound_model_id != model_id:
            raise FinancialBacktestConflict("来源回测模型已不再绑定给炒股智能体")
        candidate_source = backtest_service._validate_candidate_model(model_id)
    fingerprint = backtest_service._model_fingerprint(model_id)
    if fingerprint != str(source_run.get("modelFingerprint") or ""):
        raise FinancialBacktestConflict("来源回测模型配置已变化，不能以新配置伪装复跑")
    return model_id, fingerprint, candidate_source


def _verify_source_and_model(
    agent_id: str,
    workflow: Mapping[str, Any],
    snapshot: data.BacktestSnapshot | basket_data.BasketSnapshot,
) -> None:
    plan = workflow.get("plan") if isinstance(workflow.get("plan"), Mapping) else {}
    source_id = str(workflow.get("sourceRunId") or "")
    if source_id != str(plan.get("sourceRunId") or ""):
        raise FinancialBacktestConflict("来源回测标识与冻结计划不一致")
    backtest_service._require_owner(agent_id)
    model_id = str(plan.get("sourceModelId") or "")
    if not model_id:
        raise FinancialBacktestConflict("冻结计划缺少模型身份")
    if str(snapshot.data_hash) != str(plan.get("sourceDataHash") or ""):
        raise FinancialBacktestConflict("冻结来源行情摘要已变化")
    if str(plan.get("sourceModelCandidateSource") or ""):
        candidate_source = backtest_service._validate_candidate_model(model_id)
        if candidate_source != str(plan.get("sourceModelCandidateSource") or ""):
            raise FinancialBacktestConflict("来源模型候选资格已变化，不能继续滚动验证")
    else:
        _agent, bound_model_id = backtest_service._require_owner_and_model(agent_id, model_id)
        if bound_model_id != model_id:
            raise FinancialBacktestConflict("炒股智能体绑定模型已变化，不能继续滚动验证")
    if backtest_service._model_fingerprint(model_id) != str(plan.get("sourceModelFingerprint") or ""):
        raise FinancialBacktestConflict("冻结模型配置已变化，不能继续滚动验证")


def _verify_frozen_plan(
    agent_id: str, workflow: Mapping[str, Any], selected_store: FinancialBacktestStore
) -> data.BacktestSnapshot | basket_data.BasketSnapshot:
    _verify_plan_hash(workflow)
    plan = workflow.get("plan")
    if not isinstance(plan, Mapping):
        raise FinancialBacktestConflict("滚动验证冻结计划缺失")
    source = selected_store.load_run(agent_id, str(workflow.get("sourceRunId") or ""))
    _validate_source_run(agent_id, source, str(workflow.get("sourceRunId") or ""))
    if (
        str(source.get("dataHash") or "") != str(plan.get("sourceDataHash") or "")
        or str(source.get("paramsHash") or "") != str(plan.get("sourceParamsHash") or "")
        or dict(source.get("params") or {}) != dict(plan.get("sourceParams") or {})
    ):
        raise FinancialBacktestConflict("来源回测与冻结滚动计划不一致")
    payload = selected_store.load_snapshot(agent_id, str(plan.get("sourceDataHash") or ""))
    from core.web.services.financial_backtest.runtime import _restore_snapshot

    snapshot = _restore_snapshot(payload)
    if snapshot.data_hash != str(plan.get("sourceDataHash") or ""):
        raise FinancialBacktestConflict("冻结行情摘要校验失败")
    return snapshot


def _verify_plan_hash(workflow: Mapping[str, Any]) -> None:
    plan = workflow.get("plan")
    if not isinstance(plan, Mapping):
        raise FinancialBacktestConflict("滚动验证冻结计划缺失")
    if sha256_json(plan) != str(workflow.get("planHash") or ""):
        raise FinancialBacktestConflict("滚动验证冻结计划摘要校验失败")


def _stage_requests(
    agent_id: str,
    workflow_id: str,
    folds: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    requests: dict[str, Any] = {}
    for fold in folds:
        fold_id = str(fold["foldId"])
        requests[fold_id] = {"train": {}, "test": {}}
        for candidate in candidates:
            candidate_id = str(candidate["candidateId"])
            for stage in ("train", "test"):
                client_request_id = str(
                    uuid5(
                        NAMESPACE_URL,
                        f"vibelution:financial-walk-forward:{workflow_id}:{fold_id}:{stage}:{candidate_id}",
                    )
                )
                requests[fold_id][stage][candidate_id] = client_request_id
    return requests


def _check_new_run_capacity(
    selected_store: FinancialBacktestStore, agent_id: str, planned_runs: int
) -> None:
    current = len(selected_store.list_runs(agent_id))
    if current + planned_runs > MAX_RUNS_PER_AGENT:
        raise FinancialBacktestConflict(
            f"该智能体剩余回测容量不足：滚动验证需要预留{planned_runs}个子回测，当前上限为{MAX_RUNS_PER_AGENT}"
        )


def _check_workflow_capacity(
    agent_id: str, workflow: Mapping[str, Any], selected_store: FinancialBacktestStore
) -> None:
    plan = workflow.get("plan") if isinstance(workflow.get("plan"), Mapping) else {}
    requests = plan.get("stageRequests") if isinstance(plan.get("stageRequests"), Mapping) else {}
    folds = plan.get("folds") if isinstance(plan.get("folds"), list) else []
    candidates = plan.get("candidates") if isinstance(plan.get("candidates"), list) else []
    expected_total = int(plan.get("plannedRunCount") or 0)
    candidate_ids = {
        str(candidate.get("candidateId") or "")
        for candidate in candidates
        if isinstance(candidate, Mapping)
    }
    if (
        not folds
        or len(candidate_ids) != len(candidates)
        or expected_total != len(folds) * (len(candidates) + 1)
        or set(requests) != {str(fold.get("foldId") or "") for fold in folds if isinstance(fold, Mapping)}
    ):
        raise FinancialBacktestConflict("滚动验证冻结计划的子回测容量清单无效")

    run_rows = selected_store.list_runs(agent_id)
    runs_by_request: dict[str, Mapping[str, Any]] = {}
    for run in run_rows:
        request_id = str(run.get("clientRequestId") or "")
        if not request_id:
            continue
        if request_id in runs_by_request and str(runs_by_request[request_id].get("runId") or "") != str(run.get("runId") or ""):
            raise FinancialBacktestConflict("同一幂等请求对应多个回测子任务，冻结计划无法安全恢复")
        runs_by_request[request_id] = run

    execution = workflow.get("execution") if isinstance(workflow.get("execution"), Mapping) else {}
    all_train_metrics = execution.get("trainMetrics") if isinstance(execution.get("trainMetrics"), Mapping) else {}
    existing_planned = 0
    for fold in folds:
        fold_id = str(fold.get("foldId") or "")
        stage_map = requests.get(fold_id)
        if not isinstance(stage_map, Mapping):
            raise FinancialBacktestConflict("冻结计划缺少子回测阶段清单")
        train_map = stage_map.get("train") if isinstance(stage_map.get("train"), Mapping) else {}
        test_map = stage_map.get("test") if isinstance(stage_map.get("test"), Mapping) else {}
        if set(train_map) != candidate_ids or set(test_map) != candidate_ids:
            raise FinancialBacktestConflict("冻结计划的候选子回测清单不完整")

        for candidate_id in sorted(candidate_ids):
            request_id = str(train_map.get(candidate_id) or "")
            if not request_id:
                raise FinancialBacktestConflict("冻结计划缺少训练子回测幂等标识")
            run = runs_by_request.get(request_id)
            if run is not None:
                _validate_planned_child_run(agent_id, request_id, run)
                existing_planned += 1

        existing_tests = [
            (candidate_id, str(test_map.get(candidate_id) or ""), runs_by_request.get(str(test_map.get(candidate_id) or "")))
            for candidate_id in sorted(candidate_ids)
            if runs_by_request.get(str(test_map.get(candidate_id) or "")) is not None
        ]
        if len(existing_tests) > 1:
            raise FinancialBacktestConflict("同一折出现多个测试子任务，冻结计划无法安全恢复")
        if existing_tests:
            candidate_id, request_id, run = existing_tests[0]
            _validate_planned_child_run(agent_id, request_id, run)
            selected_id = str(fold.get("selectedCandidateId") or "")
            if not selected_id:
                fold_metrics = all_train_metrics.get(fold_id)
                try:
                    selected_id = select_candidate(candidates, fold_metrics)
                except (TypeError, ValueError) as exc:
                    raise FinancialBacktestConflict("已有测试子任务但无法从冻结训练结果复核胜出候选") from exc
            if selected_id != candidate_id:
                raise FinancialBacktestConflict("已有测试子任务与训练阶段胜出候选不匹配")
            existing_planned += 1

    if existing_planned > expected_total:
        raise FinancialBacktestConflict("已存在的子回测数量超过冻结计划")
    remaining = expected_total - existing_planned
    current_runs = len(run_rows)
    if current_runs + remaining > MAX_RUNS_PER_AGENT:
        raise FinancialBacktestConflict(
            f"滚动验证子回测容量不足：剩余阶段需要{remaining}个运行名额，当前上限为{MAX_RUNS_PER_AGENT}"
        )


def _validate_planned_child_run(
    agent_id: str, request_id: str, run: Mapping[str, Any]
) -> None:
    if (
        str(run.get("clientRequestId") or "") != request_id
        or str(run.get("runId") or "") != deterministic_run_id(agent_id, request_id)
    ):
        raise FinancialBacktestConflict("已有子回测与冻结计划的幂等身份不匹配")


def _set_fold_selection(workflow: dict[str, Any], fold_id: str, selected_id: str) -> None:
    folds = workflow.get("folds")
    if not isinstance(folds, list):
        raise FinancialBacktestConflict("滚动验证折列表损坏")
    fold = next(
        (row for row in folds if isinstance(row, dict) and str(row.get("foldId") or "") == fold_id),
        None,
    )
    if fold is None:
        raise FinancialBacktestConflict("滚动验证折不存在")
    existing = fold.get("selectedCandidateId")
    if existing and str(existing) != selected_id:
        raise FinancialBacktestConflict("冻结训练结果产生了不一致的候选选择")
    fold["selectedCandidateId"] = selected_id
    fold["status"] = "testing"


def _completed_metrics(run: Mapping[str, Any]) -> dict[str, float | None]:
    metrics = run.get("metrics")
    if not isinstance(metrics, Mapping):
        raise FinancialBacktestConflict("已完成的子回测缺少指标，不能用于选参或测试评估")
    projected = _project_metrics(metrics)
    if projected.get("excessReturnPct") is None:
        raise FinancialBacktestConflict("已完成的子回测缺少有效超额收益，不能用于选参")
    return projected


def _require_owner(agent_id: str) -> dict[str, Any]:
    return backtest_service._require_owner(agent_id)


def _sync_runtime_task(
    agent_id: str, workflow: Mapping[str, Any], *, rearm: bool = False
) -> None:
    """Register the workflow itself for active-work guards, separate from child runs."""
    workflow_id = str(workflow.get("workflowId") or "").strip()
    if not workflow_id:
        return
    task_id = f"financial-walk-forward-{workflow_id}"
    status = str(workflow.get("status") or "").strip().lower()
    terminal = status in _WORKFLOW_TERMINAL
    registry_status = "blocked" if status == "paused_unknown" else status
    task_store = runtime_task_registry.default_store()
    current = task_store.load_state(task_id)
    metadata = {
        "agentId": str(agent_id),
        "workflowId": workflow_id,
        "publicStatus": status,
        "activeRunId": str(workflow.get("activeRunId") or ""),
    }
    if not current:
        initial_status = "running" if status in {"running", "stop_requested"} else "queued"
        snapshot = runtime_task_registry.new_snapshot(
            kind=runtime_task_registry.KIND_RESEARCH_TASK,
            task_id=task_id,
            status=initial_status,
            label="股票A股滚动回测",
            backgrounding_disabled=True,
        )
        snapshot.update(
            {
                "coordinationOwner": "financial_walk_forward",
                "financialWalkForward": metadata,
            }
        )
        current, _created = task_store.register_task_if_absent(snapshot)
    if (
        current.get("coordinationOwner") != "financial_walk_forward"
        or (current.get("financialWalkForward") or {}).get("agentId") != str(agent_id)
    ):
        raise FinancialBacktestConflict("滚动验证工作流标识已被其他任务占用")

    def refresh(snapshot: dict[str, Any]) -> dict[str, Any]:
        snapshot["financialWalkForward"] = metadata
        if terminal:
            snapshot["status"] = registry_status
            snapshot["completedAt"] = backtest_service._iso(backtest_service._now())
            snapshot["terminalReason"] = str(workflow.get("terminalReason") or status)
        else:
            snapshot["status"] = "running" if status in {"running", "stop_requested"} else "queued"
            if rearm:
                snapshot["completedAt"] = ""
                snapshot["stopInitiator"] = None
                snapshot["stopRequestedAt"] = ""
                snapshot["terminalReason"] = ""
        return snapshot

    task_store.update_task(task_id, refresh)
    if status == "stop_requested":
        task_store.request_stop(task_id, "user")
    elif terminal:
        terminal_status = registry_status if registry_status in runtime_task_registry.TERMINAL_STATUSES else "failed"
        task_store.mark_task_terminal(
            task_id,
            status=terminal_status,
            stop_initiator="user" if status == "stopped" else None,
            reason=str(workflow.get("terminalReason") or status),
        )


def _record_advance_error(
    agent_id: str,
    workflow_id: str,
    selected_store: FinancialBacktestStore,
    selected_walk_store: WalkForwardStore,
    error: Exception,
    *,
    now_provider: Callable[[], datetime] | None,
) -> bool:
    reason = (
        str(error)
        if isinstance(error, (FinancialBacktestConflict, data.BacktestDataError))
        else "滚动验证阶段失败，请检查来源冻结数据和回测子任务"
    )
    status = "blocked" if isinstance(error, (FinancialBacktestConflict, data.BacktestDataError)) else "failed"
    try:
        with selected_walk_store.locked(agent_id, workflow_id) as workflow:
            if str(workflow.get("status") or "") in _WORKFLOW_TERMINAL:
                return False
            execution = workflow.get("execution")
            if not isinstance(execution, dict):
                execution = {}
            execution["advanceErrorStatus"] = status
            execution["advanceErrorReason"] = reason[:500]
            execution["stopIntent"] = True
            workflow["execution"] = execution
            _apply_workflow_stop_intent(
                agent_id,
                workflow,
                selected_store,
                default_reason=reason[:500],
            )
            workflow["updatedAt"] = backtest_service._iso(backtest_service._now(now_provider))
            _sync_runtime_task(agent_id, workflow)
        return True
    except Exception:
        _LOG.exception("Could not persist A-share walk-forward failure")
        return False


__all__ = [
    "advance_walk_forward_workflows",
    "create_walk_forward_preview",
    "export_walk_forward",
    "get_walk_forward",
    "list_walk_forward_workflows",
    "project_walk_forward",
    "resume_walk_forward",
    "start_walk_forward",
    "stop_walk_forward",
]
