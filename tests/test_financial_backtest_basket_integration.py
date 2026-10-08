from __future__ import annotations

import csv
import io
import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest

from core.web.routes.financial_backtest_models import FinancialBacktestRun
from core.web.services import agent_directory_service
from core.web.services import financial_backtest_service as api
from core.web.services.financial_backtest import (
    basket_data,
    data,
    decision,
    runtime,
    service,
)
from core.web.services.financial_backtest.store import FinancialBacktestStore

_AGENT_ID = "finance-basket-integration-agent"
_MODEL_ID = "provider/model"
_NOW = datetime(2024, 1, 20, 12, 0, tzinfo=timezone.utc)


def _basket_snapshot(symbol_count: int = 2) -> basket_data.BasketSnapshot:
    first = date(2024, 1, 2)
    days: list[str] = []
    current = first
    while len(days) < 5:
        if current.weekday() < 5:
            days.append(current.isoformat())
        current += timedelta(days=1)

    assets: dict[str, data.BacktestSnapshot] = {}
    for index in range(symbol_count):
        symbol = f"sh600{index:03d}"
        initial_price = 10.0 + index * 5
        candles = tuple(
            data.Candle(day, initial_price + index, initial_price + index + 1,
                        initial_price + index - 1, initial_price + index, 100_000)
            for index, day in enumerate(days)
        )
        assets[symbol] = data.BacktestSnapshot(
            symbol=symbol,
            start_date=days[0],
            end_date=days[-1],
            candles=candles,
            warmup_candles=(),
            source="fixture",
            source_url=f"https://example.invalid/{symbol}",
            fetched_at="2024-01-08T16:00:00+08:00",
            data_hash=data._stable_hash(candles, symbol, days[0], days[-1]),
            coverage=data.BacktestCoverage(
                requestedStartDate=days[0],
                requestedEndDate=days[-1],
                actualStartDate=days[0],
                actualEndDate=days[-1],
                availableStartDate=days[0],
                availableEndDate=days[-1],
                tradingDays=len(candles),
                warmupBars=0,
                providerWindows=(),
                tradingCalendarStatus="tencent_index_checked",
                calendarSymbol="sh000001",
                complete=True,
            ),
            actions_status="factor_check_passed",
            action_dates=(),
            notice=("offline integration fixture",),
        )
    symbols = tuple(sorted(assets))
    return basket_data.BasketSnapshot(
        symbols=symbols,
        assets=assets,
        session_dates=tuple(days),
        start_date=days[0],
        end_date=days[-1],
        data_hash=basket_data._stable_basket_hash(
            symbols, assets, tuple(days), days[0], days[-1]
        ),
        source="fixture",
        notice=("fixture notice",),
    )


def _setup(monkeypatch: pytest.MonkeyPatch, tmp_path):
    agent = {
        "agentId": _AGENT_ID,
        "status": "active",
        "metadata": {
            "financialAssistantProfile": "financial_assistant_v1",
            "financialAssistantSetup": "ready",
        },
    }
    monkeypatch.setattr(
        agent_directory_service,
        "get_agent",
        lambda agent_id: dict(agent) if agent_id == _AGENT_ID else None,
    )
    monkeypatch.setattr(agent_directory_service, "agent_dialogue_model_id", lambda _agent: _MODEL_ID)
    monkeypatch.setattr(service, "_model_fingerprint", lambda _model_id: "frozen-model")
    monkeypatch.setattr(runtime, "_model_fingerprint", lambda _model_id: "frozen-model")
    monkeypatch.setattr(service, "_sync_runtime_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(runtime, "_sync_runtime_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(runtime, "_record_event", lambda *args, **kwargs: None)
    store = FinancialBacktestStore(
        path_resolver=lambda owner_id: tmp_path / owner_id / "ai-backtests"
    )
    snapshot = _basket_snapshot()
    return store, snapshot


def _start_basket_run(store, snapshot):
    preview = api.create_financial_backtest_preview(
        _AGENT_ID,
        {
            "symbols": list(snapshot.symbols),
            "startDate": snapshot.start_date,
            "endDate": snapshot.end_date,
            "strategy": "basket recovery integration test",
            "initialCash": 100_000,
            "maxPositionPct": 100,
            "decisionInterval": 1,
            "slippageBps": 0,
            "maxTokens": 2_000_000,
        },
        store=store,
        data_loader=lambda _request: snapshot,
        now_provider=lambda: _NOW,
    )
    started = api.start_financial_backtest_run(
        _AGENT_ID,
        str(uuid4()),
        preview["previewId"],
        store=store,
        now_provider=lambda: _NOW,
    )
    return preview, started


def _basket_decision(decision_input):
    result = {
        "date": decision_input["asOfDate"],
        "targetWeights": {symbol: 25 for symbol in decision_input["symbols"]},
        "reason": "recovery integration decision",
        "modelId": _MODEL_ID,
        "inputHash": service.sha256_json(decision_input),
        "tokens": 43,
        "tokenAccounting": "measured",
    }
    result["decisionHash"] = service.sha256_json(result)
    return result


def _snapshot_with_unfilled_benchmark_symbol(snapshot):
    assets = dict(snapshot.assets)
    symbol = snapshot.symbols[-1]
    asset = assets[symbol]
    expensive_candles = tuple(
        replace(
            candle,
            open=candle.open * 1_000_000,
            high=candle.high * 1_000_000,
            low=candle.low * 1_000_000,
            close=candle.close * 1_000_000,
        )
        for candle in asset.candles
    )
    assets[symbol] = replace(
        asset,
        candles=expensive_candles,
        data_hash=data._stable_hash(
            expensive_candles, symbol, asset.start_date, asset.end_date
        ),
    )
    result = replace(
        snapshot,
        assets=assets,
        data_hash=basket_data._stable_basket_hash(
            snapshot.symbols,
            assets,
            snapshot.session_dates,
            snapshot.start_date,
            snapshot.end_date,
        ),
    )
    basket_data.validate_basket_snapshot(result)
    return result


def test_basket_backtest_preview_worker_evaluation_recovery_and_export(monkeypatch, tmp_path):
    store, snapshot = _setup(monkeypatch, tmp_path)
    payload = {
        "symbols": ["sh600000", "sh600001"],
        "startDate": snapshot.start_date,
        "endDate": snapshot.end_date,
        "strategy": "共同交易日收盘后决定下一日组合目标仓位",
        "initialCash": 100_000,
        "maxPositionPct": 100,
        "decisionInterval": 1,
        "slippageBps": 0,
        "maxTokens": 2_000_000,
    }
    default_preview = api.create_financial_backtest_preview(
        _AGENT_ID,
        payload,
        store=store,
        data_loader=lambda _request: snapshot,
        now_provider=lambda: _NOW,
    )

    assert default_preview["outOfSampleStartDate"] == snapshot.session_dates[4]
    explicit_date = snapshot.session_dates[3]
    preview = api.create_financial_backtest_preview(
        _AGENT_ID,
        {**payload, "outOfSampleStartDate": explicit_date},
        store=store,
        data_loader=lambda _request: snapshot,
        now_provider=lambda: _NOW,
    )

    assert preview["symbol"] is None
    assert preview["symbols"] == ["sh600000", "sh600001"]
    assert preview["outOfSampleStartDate"] == explicit_date
    assert preview["params"]["outOfSampleStartDate"] == explicit_date
    assert preview["paramsHash"] != default_preview["paramsHash"]
    persisted_snapshot = store.load_snapshot(_AGENT_ID, preview["dataHash"])
    assert persisted_snapshot["schemaVersion"] == 1
    assert persisted_snapshot["basketSnapshot"]["schemaVersion"] == 2
    assert set(persisted_snapshot["basketSnapshot"]["assets"]) == set(snapshot.symbols)

    started = api.start_financial_backtest_run(
        _AGENT_ID, str(uuid4()), preview["previewId"], store=store, now_provider=lambda: _NOW
    )
    model_inputs: list[dict] = []
    runtime_reservations: list[int] = []
    original_runtime_reserve = runtime.reserve_decision_call

    def capture_reservation(messages):
        value = original_runtime_reserve(messages)
        runtime_reservations.append(value)
        return value

    monkeypatch.setattr(runtime, "reserve_decision_call", capture_reservation)

    def decide(**kwargs):
        decision_input = dict(kwargs["decision_input"])
        model_inputs.append(decision_input)
        symbols = decision_input["symbols"]
        decision = {
            "date": decision_input["asOfDate"],
            "targetWeights": {symbol: 50 for symbol in symbols},
            "reason": "按分散配置持有组合",
            "modelId": _MODEL_ID,
            "inputHash": service.sha256_json(decision_input),
            "tokens": 43,
            "tokenAccounting": "measured",
        }
        decision["decisionHash"] = service.sha256_json(decision)
        return decision

    worker = runtime.FinancialBacktestWorker(
        store=store,
        assistant_loader=lambda: [_AGENT_ID],
        decision_runner=decide,
        worker_id="basket-integration-worker",
    )
    assert worker.process_pending_once(stop_requested=lambda: False) == 1

    completed = api.get_financial_backtest_run(_AGENT_ID, started["runId"], store=store)
    assert completed["status"] == "completed", (
        completed.get("errorCode"),
        completed.get("terminalReason"),
        store.load_run(_AGENT_ID, started["runId"]).get("reservationPlan"),
        runtime_reservations,
    )
    assert completed["symbol"] is None
    assert completed["symbols"] == ["sh600000", "sh600001"]
    assert completed["evaluation"]["outOfSampleStartDate"] == explicit_date
    assert completed["evaluation"]["inSample"]["tradingDays"] == 3
    assert completed["evaluation"]["outOfSample"]["tradingDays"] == 2
    assert completed["params"]["outOfSampleStartDate"] == explicit_date
    assert all("targetWeights" in row and "targetWeight" not in row for row in completed["decisions"])
    assert all(set(row["targetWeights"]) == set(snapshot.symbols) for row in completed["decisions"])
    assert all(
        bar["date"] <= request["asOfDate"]
        for request in model_inputs
        for symbol_bars in request["dailyBarsBySymbol"].values()
        for bar in symbol_bars
    )
    assert all("outOfSampleStartDate" not in request for request in model_inputs)
    dto = FinancialBacktestRun.model_validate(completed)
    assert dto.status == "completed"
    assert "snapshot" not in completed

    exported = api.export_financial_backtest_run(_AGENT_ID, started["runId"], "json", store=store)
    export_body = json.loads(exported["content"])
    assert exported["schemaVersion"] == 2
    assert export_body["schemaVersion"] == 2
    assert export_body["evaluation"] == completed["evaluation"]
    assert export_body["symbols"] == list(snapshot.symbols)
    assert export_body["snapshot"]["schemaVersion"] == 2
    assert export_body["snapshot"]["dataHash"] == snapshot.data_hash
    assert set(export_body["snapshot"]["assets"]) == set(snapshot.symbols)
    assert all(export_body["snapshot"]["assets"][symbol]["candles"] for symbol in snapshot.symbols)

    csv_export = api.export_financial_backtest_run(
        _AGENT_ID, started["runId"], "csv", store=store
    )
    csv_rows = list(csv.reader(io.StringIO(csv_export["content"])))
    equity_header_index = next(
        index
        for index, row in enumerate(csv_rows)
        if row[:1] == ["date"]
        and {"positions", "marketValues", "benchmarkPositions"}.issubset(row)
    )
    equity_row = next(row for row in csv_rows[equity_header_index + 1 :] if row)
    exported_equity = dict(zip(csv_rows[equity_header_index], equity_row))
    for field in ("positions", "marketValues", "benchmarkPositions"):
        assert json.loads(exported_equity[field]) == export_body["equity"][0][field]

    original_load_snapshot = store.load_snapshot

    def corrupt_export_snapshot(agent_id, data_hash):
        stored = original_load_snapshot(agent_id, data_hash)
        stored["basketSnapshot"]["assets"][snapshot.symbols[0]]["candles"][0]["close"] += 0.01
        return stored

    monkeypatch.setattr(store, "load_snapshot", corrupt_export_snapshot)
    with pytest.raises(service.FinancialBacktestStoreError, match="快照校验失败"):
        api.export_financial_backtest_run(_AGENT_ID, started["runId"], "json", store=store)
    monkeypatch.setattr(store, "load_snapshot", original_load_snapshot)

    monkeypatch.setattr(service, "MAX_RESULT_CHARS", 100)
    with pytest.raises(service.FinancialBacktestConflict, match="超过安全大小限制"):
        api.export_financial_backtest_run(_AGENT_ID, started["runId"], "json", store=store)


def test_basket_stop_resume_restores_completed_weights_without_recalling_successful_date(monkeypatch, tmp_path):
    store, snapshot = _setup(monkeypatch, tmp_path)
    preview, started = _start_basket_run(store, snapshot)
    schedule = preview["decisionSchedule"]
    initial_calls: list[str] = []

    def stop_after_first_decision(**kwargs):
        decision_input = dict(kwargs["decision_input"])
        result = _basket_decision(decision_input)
        initial_calls.append(result["date"])
        store.update_run(
            _AGENT_ID,
            started["runId"],
            lambda run: run.__setitem__("status", "stop_requested"),
        )
        return result

    first_worker = runtime.FinancialBacktestWorker(
        store=store,
        assistant_loader=lambda: [_AGENT_ID],
        decision_runner=stop_after_first_decision,
        worker_id="basket-worker-before-resume",
    )
    assert first_worker.process_pending_once(stop_requested=lambda: False) == 1
    stopped = api.get_financial_backtest_run(_AGENT_ID, started["runId"], store=store)
    assert stopped["status"] == "stopped"
    assert [item["date"] for item in stopped["decisions"]] == [schedule[0]]
    assert stopped["decisions"][0]["targetWeights"] == {
        symbol: 25.0 for symbol in snapshot.symbols
    }

    resumed = api.resume_financial_backtest_run(
        _AGENT_ID, started["runId"], store=store
    )
    assert resumed["status"] == "queued"
    assert resumed["decisions"][0]["targetWeights"] == {
        symbol: 25.0 for symbol in snapshot.symbols
    }
    resumed_calls: list[str] = []

    def decide_remaining(**kwargs):
        result = _basket_decision(dict(kwargs["decision_input"]))
        resumed_calls.append(result["date"])
        return result

    restarted_worker = runtime.FinancialBacktestWorker(
        store=store,
        assistant_loader=lambda: [_AGENT_ID],
        decision_runner=decide_remaining,
        worker_id="basket-worker-after-resume",
    )
    assert restarted_worker.process_pending_once(stop_requested=lambda: False) == 1

    completed = api.get_financial_backtest_run(_AGENT_ID, started["runId"], store=store)
    assert completed["status"] == "completed"
    assert initial_calls == [schedule[0]]
    assert resumed_calls == list(schedule[1:])
    assert [item["date"] for item in completed["decisions"]] == list(schedule)
    assert completed["decisions"][0]["targetWeights"] == {
        symbol: 25.0 for symbol in snapshot.symbols
    }


def test_basket_unknown_decision_resume_requires_confirmation_and_keeps_prior_weights(monkeypatch, tmp_path):
    store, snapshot = _setup(monkeypatch, tmp_path)
    preview, started = _start_basket_run(store, snapshot)
    schedule = preview["decisionSchedule"]
    calls: list[str] = []
    uncertain_attempts = 0

    def decide_with_one_unknown(**kwargs):
        nonlocal uncertain_attempts
        decision_input = dict(kwargs["decision_input"])
        date_value = decision_input["asOfDate"]
        calls.append(date_value)
        if date_value == schedule[1] and uncertain_attempts == 0:
            uncertain_attempts += 1
            raise TimeoutError("provider outcome is unknown")
        return _basket_decision(decision_input)

    first_worker = runtime.FinancialBacktestWorker(
        store=store,
        assistant_loader=lambda: [_AGENT_ID],
        decision_runner=decide_with_one_unknown,
        worker_id="basket-worker-unknown",
    )
    assert first_worker.process_pending_once(stop_requested=lambda: False) == 1
    paused = api.get_financial_backtest_run(_AGENT_ID, started["runId"], store=store)
    assert paused["status"] == "paused_unknown"
    assert paused["uncertainDecisionDate"] == schedule[1]
    assert [item["date"] for item in paused["decisions"]] == [schedule[0]]
    assert paused["decisions"][0]["targetWeights"] == {
        symbol: 25.0 for symbol in snapshot.symbols
    }

    with pytest.raises(service.FinancialBacktestConflict):
        api.resume_financial_backtest_run(
            _AGENT_ID,
            started["runId"],
            retry_unknown_decision_date=schedule[1],
            store=store,
        )
    resumed = api.resume_financial_backtest_run(
        _AGENT_ID,
        started["runId"],
        retry_unknown_decision_date=schedule[1],
        confirm_possible_duplicate_charge=True,
        store=store,
    )
    assert resumed["status"] == "queued"
    assert resumed["decisions"][0]["targetWeights"] == {
        symbol: 25.0 for symbol in snapshot.symbols
    }

    retry_worker = runtime.FinancialBacktestWorker(
        store=store,
        assistant_loader=lambda: [_AGENT_ID],
        decision_runner=decide_with_one_unknown,
        worker_id="basket-worker-after-unknown-resume",
    )
    assert retry_worker.process_pending_once(stop_requested=lambda: False) == 1
    completed = api.get_financial_backtest_run(_AGENT_ID, started["runId"], store=store)
    assert completed["status"] == "completed"
    assert calls == [schedule[0], schedule[1], *schedule[1:]]
    assert [item["date"] for item in completed["decisions"]] == list(schedule)
    assert completed["decisions"][0]["targetWeights"] == {
        symbol: 25.0 for symbol in snapshot.symbols
    }


def test_basket_benchmark_fill_status_survives_runtime_run_export_and_dto(monkeypatch, tmp_path):
    store, snapshot = _setup(monkeypatch, tmp_path)
    snapshot = _snapshot_with_unfilled_benchmark_symbol(snapshot)
    _preview, started = _start_basket_run(store, snapshot)
    worker = runtime.FinancialBacktestWorker(
        store=store,
        assistant_loader=lambda: [_AGENT_ID],
        decision_runner=lambda **kwargs: _basket_decision(dict(kwargs["decision_input"])),
        worker_id="basket-benchmark-status-worker",
    )

    assert worker.process_pending_once(stop_requested=lambda: False) == 1
    completed = api.get_financial_backtest_run(_AGENT_ID, started["runId"], store=store)

    assert completed["status"] == "completed"
    assert completed["benchmarkStatus"] == "partial_cash_sleeves"
    assert completed["unfilledBenchmarkSymbols"] == [snapshot.symbols[-1]]
    dto = FinancialBacktestRun.model_validate(completed)
    assert dto.benchmarkStatus == "partial_cash_sleeves"
    assert dto.unfilledBenchmarkSymbols == [snapshot.symbols[-1]]
    summary = service.project_summary(store.load_run(_AGENT_ID, started["runId"]))
    assert summary["benchmarkStatus"] == "partial_cash_sleeves"
    assert summary["unfilledBenchmarkSymbols"] == [snapshot.symbols[-1]]
    export_body = json.loads(
        api.export_financial_backtest_run(
            _AGENT_ID, started["runId"], "json", store=store
        )["content"]
    )
    assert export_body["benchmarkStatus"] == "partial_cash_sleeves"
    assert export_body["unfilledBenchmarkSymbols"] == [snapshot.symbols[-1]]


def test_basket_snapshot_restore_rejects_unknown_or_incomplete_child_schema():
    from core.web.services.financial_backtest.contract import FinancialBacktestConflict
    from core.web.services.financial_backtest.runtime import _restore_snapshot

    with pytest.raises(FinancialBacktestConflict, match="快照"):
        _restore_snapshot({"dataHash": "a" * 64, "basketSnapshot": {"schemaVersion": 3}})
    with pytest.raises(FinancialBacktestConflict, match="快照"):
        _restore_snapshot(
            {
                "dataHash": "a" * 64,
                "basketSnapshot": {"schemaVersion": 2, "symbols": ["sh600000"]},
            }
        )


def test_basket_decision_parser_requires_exact_complete_percentage_map():
    parsed = decision._parse_basket_output(
        json.dumps({"targetWeights": {"sh600000": 25, "sh600001": 75}, "reason": "分散配置"}),
        symbols=["sh600000", "sh600001"],
        max_position_pct=100,
    )
    assert parsed["targetWeights"] == {"sh600000": 25.0, "sh600001": 75.0}
    for invalid in (
        {"targetWeights": {"sh600000": 50}, "reason": "缺少股票"},
        {"targetWeights": {"sh600000": 60, "sh600001": 50}, "reason": "权重超限"},
    ):
        with pytest.raises(data.BacktestInputError):
            decision._parse_basket_output(
                json.dumps(invalid),
                symbols=["sh600000", "sh600001"],
                max_position_pct=100,
            )


def test_ten_symbol_budget_estimate_includes_every_asset(monkeypatch):
    from core.web.services.financial_backtest import portfolio_engine

    snapshot = _basket_snapshot(symbol_count=10)
    params = {
        "strategy": "按全部标的逐日行情统一决定组合仓位",
        "initialCash": 100_000,
        "maxPositionPct": 100,
        "decisionInterval": 1,
        "commissionBps": 3,
        "minimumCommission": 5,
        "slippageBps": 0,
        "maxDecisions": 500,
        "maxTokens": 2_000_000,
    }
    captured: list[dict] = []
    original_builder = service.build_basket_decision_input

    def capture(*args, **kwargs):
        value = original_builder(*args, **kwargs)
        captured.append(value)
        return value

    monkeypatch.setattr(service, "build_basket_decision_input", capture)
    schedule = portfolio_engine.build_decision_schedule(snapshot, params)
    estimated, output, reservation_plan = service._estimate_budget(snapshot, params, schedule)

    assert output == len(schedule) * decision.MAX_OUTPUT_TOKENS_PER_DECISION
    assert estimated == sum(reservation_plan.values())
    assert len(captured) == len(schedule)
    assert all(len(item["symbols"]) == 10 for item in captured)
    assert all(set(item["dailyBarsBySymbol"]) == set(snapshot.symbols) for item in captured)
    assert all(value > 1024 + 512 * 10 for value in reservation_plan.values())
