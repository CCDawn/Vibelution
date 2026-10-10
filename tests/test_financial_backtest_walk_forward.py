from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest

from core.web.services import agent_model_candidate_service
from core.web.services.financial_backtest import (
    basket_data,
    data,
    service as backtest_service,
    walk_forward,
    walk_forward_data,
    walk_forward_service,
)
from core.web.services.financial_backtest.contract import (
    FinancialBacktestConflict,
    deterministic_run_id,
)
from core.web.services.financial_backtest.store import FinancialBacktestStore
from core.web.services.financial_backtest.walk_forward_store import WalkForwardStore
from tests.test_financial_backtest_integration import (
    _AGENT_ID,
    _MODEL_ID,
    _NOW,
    _install_scenario,
    _preview_payload,
)


def _weekdays(start: str, count: int) -> tuple[str, ...]:
    current = date.fromisoformat(start)
    result: list[str] = []
    while len(result) < count:
        if current.weekday() < 5:
            result.append(current.isoformat())
        current += timedelta(days=1)
    return tuple(result)


def _snapshot(days: tuple[str, ...], symbol: str = "sh600000") -> data.BacktestSnapshot:
    candles = tuple(
        data.Candle(day, 10 + i / 10, 10.5 + i / 10, 9.5 + i / 10, 10 + i / 10, 100_000)
        for i, day in enumerate(days)
    )
    coverage = data.BacktestCoverage(
        requestedStartDate=days[0],
        requestedEndDate=days[-1],
        actualStartDate=days[0],
        actualEndDate=days[-1],
        availableStartDate=days[0],
        availableEndDate=days[-1],
        tradingDays=len(days),
        warmupBars=0,
        providerWindows=(),
        tradingCalendarStatus="tencent_index_checked",
        calendarSymbol="sh000001",
        complete=True,
    )
    snapshot = data.BacktestSnapshot(
        symbol=symbol,
        start_date=days[0],
        end_date=days[-1],
        candles=candles,
        warmup_candles=(),
        source="fixture",
        source_url=f"https://example.invalid/{symbol}",
        fetched_at="2024-01-10T16:00:00+08:00",
        data_hash=data._stable_hash(candles, symbol, days[0], days[-1]),
        coverage=coverage,
        actions_status="factor_check_passed",
        action_dates=(),
        notice=("离线测试数据",),
    )
    data.validate_snapshot(snapshot)
    return snapshot


def _install_candidates(monkeypatch: pytest.MonkeyPatch, model_id: str = _MODEL_ID) -> dict:
    payload = {
        "operatorConfigHash": "operator-config-v1",
        "candidates": [
            {
                "modelId": model_id,
                "modelRef": model_id,
                "model": model_id.split("/", 1)[-1],
                "providerId": model_id.split("/", 1)[0],
                "source": "pinned",
                "runtimeSelectable": True,
                "slotCompatibility": {"dialogue": {"allowed": True}},
            }
        ],
    }
    monkeypatch.setattr(
        agent_model_candidate_service,
        "list_agent_model_candidates",
        lambda: deepcopy(payload),
    )
    return payload


def _completed_source_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    days: tuple[str, ...],
) -> tuple[FinancialBacktestStore, str, data.BacktestSnapshot]:
    snapshot = _snapshot(days)
    store, _snapshot_value, _prepared = _install_scenario(
        monkeypatch, tmp_path, snapshot=snapshot
    )
    payload = {
        **_preview_payload(),
        "startDate": days[0],
        "endDate": days[-1],
        "maxDecisions": 500,
    }
    preview = backtest_service.create_financial_backtest_preview(
        _AGENT_ID,
        payload,
        store=store,
        data_loader=lambda _request: snapshot,
        now_provider=lambda: _NOW,
    )
    source = backtest_service.start_financial_backtest_run(
        _AGENT_ID,
        str(uuid4()),
        preview["previewId"],
        store=store,
        now_provider=lambda: _NOW,
    )
    store.update_run(
        _AGENT_ID,
        source["runId"],
        lambda run: run.update(
            status="completed",
            metrics={
                "totalReturnPct": 1.0,
                "benchmarkReturnPct": 0.5,
                "excessReturnPct": 0.5,
                "maxDrawdownPct": 0.0,
            },
            tokensUsed=0,
            budgetTokensCommitted=0,
            tokenAccounting="measured",
        ),
    )
    return store, source["runId"], snapshot


def _create_workflow(
    store: FinancialBacktestStore,
    source_run_id: str,
    *,
    candidates: list[dict],
    train_sessions: int = 2,
    test_sessions: int = 2,
    step_sessions: int = 2,
    max_tokens: int = 2_000_000,
) -> dict:
    return walk_forward_service.create_walk_forward_preview(
        _AGENT_ID,
        source_run_id,
        {
            "trainSessions": train_sessions,
            "testSessions": test_sessions,
            "stepSessions": step_sessions,
            "maxTokens": max_tokens,
            "candidates": candidates,
        },
        store=store,
        now_provider=lambda: _NOW,
    )


def _candidate_rows(*percentages: int) -> list[dict[str, int | str]]:
    return [
        {"candidateId": f"cap-{value}", "maxPositionPct": value}
        for value in percentages
    ]


def _quiet_workflow_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(walk_forward_service, "_sync_runtime_task", lambda *args, **kwargs: None)


def test_request_supports_four_distinct_candidates_and_fold_gaps_are_explicit():
    candidates = _candidate_rows(0, 35, 65, 100)
    normalized = walk_forward.normalize_walk_forward_request(
        {
            "trainSessions": 2,
            "testSessions": 2,
            "stepSessions": 3,
            "candidates": candidates,
        }
    )
    assert len(normalized["candidates"]) == 4
    assert normalized["candidates"][0] == {
        "candidateId": "cap-0",
        "maxPositionPct": 0,
    }

    days = _weekdays("2024-01-02", 9)
    folds, dropped = walk_forward.build_folds(
        days,
        {"trainSessions": 2, "testSessions": 2, "stepSessions": 3},
    )
    assert len(folds) == 2
    assert folds[0]["testEndIndex"] < folds[1]["testStartIndex"]
    assert folds[1]["testStartIndex"] - folds[0]["testEndIndex"] - 1 == 1
    assert dropped == 2
    assert walk_forward.select_candidate(
        candidates,
        {row["candidateId"]: {"excessReturnPct": 2.0} for row in candidates},
    ) == "cap-0"


def test_slice_snapshot_keeps_only_prior_warmup_and_purges_training_end_fill():
    days = _weekdays("2024-01-02", 270)
    snapshot = _snapshot(days)
    sliced = walk_forward_data.slice_snapshot(snapshot, 260, 262)

    assert len(sliced.warmup_candles) == 252
    assert sliced.warmup_candles[-1].date == days[259]
    assert sliced.candles[0].date == days[260]
    assert all(row.date < sliced.candles[0].date for row in sliced.warmup_candles)
    assert sliced.data_hash == data._stable_hash(
        (*sliced.warmup_candles, *sliced.candles),
        sliced.symbol,
        sliced.start_date,
        sliced.end_date,
    )

    fold = {"trainStartIndex": 0, "trainEndIndex": 1}
    train = walk_forward_data.slice_snapshot(
        _snapshot(days[:4]), fold["trainStartIndex"], fold["trainEndIndex"]
    )
    schedule = backtest_service._build_schedule(
        train,
        {"params": {"decisionInterval": 1, "maxDecisions": 10}},
    )
    assert schedule == (train.candles[0].date,)
    assert train.candles[-1].date not in schedule


def test_basket_slice_rehashes_each_offline_window():
    days = _weekdays("2024-01-02", 5)
    symbols = ("sh600000", "sh600001")
    assets = {symbol: _snapshot(days, symbol) for symbol in symbols}
    source = basket_data.BasketSnapshot(
        symbols=symbols,
        assets=assets,
        session_dates=days,
        start_date=days[0],
        end_date=days[-1],
        data_hash=basket_data._stable_basket_hash(
            symbols, assets, days, days[0], days[-1]
        ),
        source="fixture",
        notice=("离线测试数据",),
    )
    sliced = walk_forward_data.slice_snapshot(source, 1, 3)
    assert sliced.session_dates == days[1:4]
    assert sliced.start_date == days[1]
    assert sliced.end_date == days[3]
    assert all(asset.candles[0].date == days[1] for asset in sliced.assets.values())
    assert sliced.data_hash == basket_data._stable_basket_hash(
        sliced.symbols,
        sliced.assets,
        sliced.session_dates,
        sliced.start_date,
        sliced.end_date,
    )


def test_preview_budget_includes_one_full_retry_for_every_executed_stage(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    days = _weekdays("2024-01-02", 4)
    store, source_id, _snapshot_value = _completed_source_run(monkeypatch, tmp_path, days)
    _install_candidates(monkeypatch)
    _quiet_workflow_runtime(monkeypatch)
    estimates = {0: 5_000, 35: 9_000, 65: 11_000, 100: 15_000}
    monkeypatch.setattr(
        walk_forward_service,
        "_estimate_stage_tokens",
        lambda _source, _snapshot, candidate, _model: estimates[candidate["maxPositionPct"]],
    )

    preview = _create_workflow(
        store,
        source_id,
        candidates=_candidate_rows(0, 35, 65, 100),
        max_tokens=110_000,
    )
    workflow = WalkForwardStore(store).load(_AGENT_ID, preview["workflowId"])
    budgets = workflow["plan"]["stageBudgets"]["fold-001"]

    assert preview["estimatedTokens"] == 110_000
    assert budgets["train"] == {f"cap-{p}": estimates[p] * 2 for p in estimates}
    assert budgets["testReserve"] == 30_000
    assert budgets["retryReserveTokens"] == 55_000
    assert preview["estimatedTokens"] == sum(budgets["train"].values()) + budgets["testReserve"]
    assert "一次完整重试" in preview["notice"]
    assert "不能视为盲测" in preview["notice"]

    with pytest.raises(FinancialBacktestConflict, match="超过总预算"):
        _create_workflow(
            store,
            source_id,
            candidates=_candidate_rows(0, 35, 65, 100),
            max_tokens=109_999,
        )


def test_candidate_source_is_frozen_and_rechecked_before_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    days = _weekdays("2024-01-02", 4)
    store, source_id, _snapshot_value = _completed_source_run(monkeypatch, tmp_path, days)
    candidate_payload = _install_candidates(monkeypatch)
    _quiet_workflow_runtime(monkeypatch)
    preview = _create_workflow(
        store,
        source_id,
        candidates=_candidate_rows(40, 60),
    )
    workflow = WalkForwardStore(store).load(_AGENT_ID, preview["workflowId"])
    assert workflow["plan"]["sourceModelCandidateSource"]

    candidate_payload["operatorConfigHash"] = "operator-config-changed"
    with pytest.raises(FinancialBacktestConflict, match="候选资格已变化"):
        walk_forward_service.start_walk_forward(
            _AGENT_ID,
            preview["workflowId"],
            store=store,
            now_provider=lambda: _NOW,
        )
    assert len(store.list_runs(_AGENT_ID)) == 1


def test_parent_advances_two_folds_and_uses_only_each_fold_training_scores(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    days = _weekdays("2024-01-02", 6)
    store, source_id, _snapshot_value = _completed_source_run(monkeypatch, tmp_path, days)
    _install_candidates(monkeypatch)
    _quiet_workflow_runtime(monkeypatch)
    candidates = _candidate_rows(40, 60)
    preview = _create_workflow(store, source_id, candidates=candidates)
    walk_forward_service.start_walk_forward(
        _AGENT_ID,
        preview["workflowId"],
        store=store,
        now_provider=lambda: _NOW,
    )
    scores = {
        ("fold-001", "cap-40"): 5.0,
        ("fold-001", "cap-60"): 1.0,
        ("fold-002", "cap-40"): 1.0,
        ("fold-002", "cap-60"): 5.0,
    }

    for _ in range(20):
        record = WalkForwardStore(store).load(_AGENT_ID, preview["workflowId"])
        active_id = record.get("activeRunId")
        if active_id:
            child = store.load_run(_AGENT_ID, active_id)
            stage = record["execution"]["activeStage"]
            metric = (
                scores[(stage["foldId"], stage["candidateId"])]
                if stage["stage"] == "train"
                else 99.0
            )
            store.update_run(
                _AGENT_ID,
                active_id,
                lambda run, value=metric: run.update(
                    status="completed",
                    metrics={
                        "totalReturnPct": value,
                        "benchmarkReturnPct": 0.0,
                        "excessReturnPct": value,
                        "maxDrawdownPct": 0.0,
                    },
                    tokensUsed=20,
                    budgetTokensCommitted=120,
                    tokenAccounting="measured",
                ),
            )
        walk_forward_service.advance_walk_forward_workflows(
            _AGENT_ID,
            store=store,
            now_provider=lambda: _NOW,
        )
        current = WalkForwardStore(store).load(_AGENT_ID, preview["workflowId"])
        if current["status"] == "completed":
            break
    else:
        pytest.fail("two-fold walk-forward did not reach completed")

    projected = walk_forward_service.get_walk_forward(
        _AGENT_ID, preview["workflowId"], store=store
    )
    assert [fold["selectedCandidateId"] for fold in projected["folds"]] == [
        "cap-40",
        "cap-60",
    ]
    assert [fold["metrics"]["excessReturnPct"] for fold in projected["folds"]] == [
        99.0,
        99.0,
    ]
    assert len(store.list_runs(_AGENT_ID)) == 1 + 2 * (2 + 1)
    assert projected["tokensUsed"] == 6 * 20
    assert projected["budgetTokensCommitted"] == 6 * 120
    assert projected["tokenUsageEstimated"] is False
    exported = walk_forward_service.export_walk_forward(
        _AGENT_ID, preview["workflowId"], store=store
    )
    exported_plan = exported["plan"]
    source_run = store.load_run(_AGENT_ID, source_id)
    assert exported_plan["sourceModelId"] == source_run["modelId"]
    assert exported_plan["sourceModelFingerprint"] == source_run["modelFingerprint"]
    assert exported_plan["sourceParams"] == source_run["params"]
    assert exported_plan["sourceParams"]["quantityRuleVersion"] == "ashare_quantity_v2"


@pytest.mark.parametrize(
    ("error_type", "hard_crash"),
    [
        pytest.param(RuntimeError, False, id="runtime-write-failure"),
        pytest.param(OSError, False, id="os-write-failure"),
        pytest.param(SystemExit, True, id="hard-process-crash"),
    ],
)
def test_created_child_is_reused_after_transient_parent_write_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path, error_type, hard_crash
):
    days = _weekdays("2024-01-02", 4)
    store, source_id, _snapshot_value = _completed_source_run(monkeypatch, tmp_path, days)
    _install_candidates(monkeypatch)
    _quiet_workflow_runtime(monkeypatch)
    preview = _create_workflow(store, source_id, candidates=_candidate_rows(40, 60))
    walk_forward_service.start_walk_forward(
        _AGENT_ID,
        preview["workflowId"],
        store=store,
        now_provider=lambda: _NOW,
    )
    original_write = store._write
    if hard_crash:
        crash_once = True

        def fail_after_child_once(*_args, **_kwargs):
            nonlocal crash_once
            if crash_once:
                crash_once = False
                raise SystemExit("crash after child durable write")

        monkeypatch.setattr(walk_forward_service, "_sync_runtime_task", fail_after_child_once)
        with pytest.raises(SystemExit, match="crash after child"):
            walk_forward_service.advance_walk_forward_workflows(
                _AGENT_ID,
                store=store,
                now_provider=lambda: _NOW,
            )
    else:
        fail_parent_write_once = True

        def fail_parent_write_once_impl(path, payload, label):
            nonlocal fail_parent_write_once
            if label == "滚动验证工作流" and fail_parent_write_once:
                fail_parent_write_once = False
                raise error_type("one-shot parent workflow write failure")
            return original_write(path, payload, label)

        monkeypatch.setattr(store, "_write", fail_parent_write_once_impl)
        walk_forward_service.advance_walk_forward_workflows(
            _AGENT_ID,
            store=store,
            now_provider=lambda: _NOW,
        )

    record = WalkForwardStore(store).load(_AGENT_ID, preview["workflowId"])
    request_id = record["plan"]["stageRequests"]["fold-001"]["train"]["cap-40"]
    orphan_id = deterministic_run_id(_AGENT_ID, request_id)
    assert record["status"] == "queued"
    assert record["activeRunId"] is None
    assert store.load_run(_AGENT_ID, orphan_id)["clientRequestId"] == request_id
    assert len(store.list_runs(_AGENT_ID)) == 2

    monkeypatch.setattr(store, "_write", original_write)
    walk_forward_service.advance_walk_forward_workflows(
        _AGENT_ID,
        store=store,
        now_provider=lambda: _NOW,
    )
    recovered = WalkForwardStore(store).load(_AGENT_ID, preview["workflowId"])
    assert recovered["activeRunId"] == orphan_id
    assert len(store.list_runs(_AGENT_ID)) == 2


def test_failed_advance_stops_durable_child_and_requires_explicit_resume(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    days = _weekdays("2024-01-02", 4)
    store, source_id, _snapshot_value = _completed_source_run(monkeypatch, tmp_path, days)
    _install_candidates(monkeypatch)
    _quiet_workflow_runtime(monkeypatch)
    preview = _create_workflow(store, source_id, candidates=_candidate_rows(40, 60))
    walk_forward_service.start_walk_forward(
        _AGENT_ID,
        preview["workflowId"],
        store=store,
        now_provider=lambda: _NOW,
    )
    fail_sync_once = True

    def fail_after_child_once(*_args, **_kwargs):
        nonlocal fail_sync_once
        if fail_sync_once:
            fail_sync_once = False
            raise RuntimeError("one-shot runtime registry failure")

    monkeypatch.setattr(walk_forward_service, "_sync_runtime_task", fail_after_child_once)
    walk_forward_service.advance_walk_forward_workflows(
        _AGENT_ID,
        store=store,
        now_provider=lambda: _NOW,
    )

    failed = WalkForwardStore(store).load(_AGENT_ID, preview["workflowId"])
    child_id = deterministic_run_id(
        _AGENT_ID,
        failed["plan"]["stageRequests"]["fold-001"]["train"]["cap-40"],
    )
    assert failed["status"] == "failed"
    assert failed["activeRunId"] == child_id
    assert store.load_run(_AGENT_ID, child_id)["status"] == "stopped"

    resumed = walk_forward_service.resume_walk_forward(
        _AGENT_ID,
        preview["workflowId"],
        store=store,
        now_provider=lambda: _NOW,
    )
    assert resumed["status"] == "queued"
    assert store.load_run(_AGENT_ID, child_id)["status"] == "queued"


def test_user_stop_finds_and_stops_unattached_child_after_parent_write_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    days = _weekdays("2024-01-02", 4)
    store, source_id, _snapshot_value = _completed_source_run(monkeypatch, tmp_path, days)
    _install_candidates(monkeypatch)
    _quiet_workflow_runtime(monkeypatch)
    preview = _create_workflow(store, source_id, candidates=_candidate_rows(40, 60))
    walk_forward_service.start_walk_forward(
        _AGENT_ID,
        preview["workflowId"],
        store=store,
        now_provider=lambda: _NOW,
    )
    original_write = store._write
    fail_parent_write_once = True

    def fail_parent_write_once_impl(path, payload, label):
        nonlocal fail_parent_write_once
        if label == "滚动验证工作流" and fail_parent_write_once:
            fail_parent_write_once = False
            raise RuntimeError("one-shot parent workflow write failure")
        return original_write(path, payload, label)

    monkeypatch.setattr(store, "_write", fail_parent_write_once_impl)
    walk_forward_service.advance_walk_forward_workflows(
        _AGENT_ID,
        store=store,
        now_provider=lambda: _NOW,
    )
    monkeypatch.setattr(store, "_write", original_write)

    before_stop = WalkForwardStore(store).load(_AGENT_ID, preview["workflowId"])
    request_id = before_stop["plan"]["stageRequests"]["fold-001"]["train"]["cap-40"]
    orphan_id = deterministic_run_id(_AGENT_ID, request_id)
    stopped = walk_forward_service.stop_walk_forward(
        _AGENT_ID,
        preview["workflowId"],
        store=store,
        now_provider=lambda: _NOW,
    )
    assert stopped["status"] == "stopped"
    assert stopped["activeRunId"] == orphan_id
    assert store.load_run(_AGENT_ID, orphan_id)["status"] == "stopped"

    resumed = walk_forward_service.resume_walk_forward(
        _AGENT_ID,
        preview["workflowId"],
        store=store,
        now_provider=lambda: _NOW,
    )
    assert resumed["status"] == "queued"
    assert store.load_run(_AGENT_ID, orphan_id)["status"] == "queued"


def test_unknown_child_pauses_without_automatic_retry_and_counts_reserved_budget(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    days = _weekdays("2024-01-02", 4)
    store, source_id, _snapshot_value = _completed_source_run(monkeypatch, tmp_path, days)
    _install_candidates(monkeypatch)
    _quiet_workflow_runtime(monkeypatch)
    preview = _create_workflow(store, source_id, candidates=_candidate_rows(40, 60))
    walk_forward_service.start_walk_forward(
        _AGENT_ID,
        preview["workflowId"],
        store=store,
        now_provider=lambda: _NOW,
    )
    walk_forward_service.advance_walk_forward_workflows(
        _AGENT_ID,
        store=store,
        now_provider=lambda: _NOW,
    )
    record = WalkForwardStore(store).load(_AGENT_ID, preview["workflowId"])
    active_id = str(record["activeRunId"])
    store.update_run(
        _AGENT_ID,
        active_id,
        lambda run: run.update(
            status="paused_unknown",
            tokensUsed=0,
            budgetTokensCommitted=777,
            tokenAccounting="reserved",
            uncertainDecisionDate=run["decisionSchedule"][0],
        ),
    )

    walk_forward_service.advance_walk_forward_workflows(
        _AGENT_ID,
        store=store,
        now_provider=lambda: _NOW,
    )
    paused = walk_forward_service.get_walk_forward(
        _AGENT_ID, preview["workflowId"], store=store
    )
    assert paused["status"] == "paused_unknown"
    assert paused["activeRunId"] == active_id
    assert paused["tokensUsed"] == 0
    assert paused["budgetTokensCommitted"] == 777
    assert paused["tokenUsageEstimated"] is True
    assert len(store.list_runs(_AGENT_ID)) == 2
    with pytest.raises(FinancialBacktestConflict, match="普通回测恢复接口"):
        walk_forward_service.resume_walk_forward(
            _AGENT_ID,
            preview["workflowId"],
            store=store,
        )
