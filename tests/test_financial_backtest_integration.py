from __future__ import annotations

import csv
import json
from dataclasses import replace
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from core.web.routes.financial_backtest_models import FinancialBacktestRun
from core.web.services import agent_directory_service
from core.web.services import financial_backtest_service as api
from core.web.services.financial_backtest import data, runtime, service
from core.web.services.financial_backtest.store import FinancialBacktestStore

_AGENT_ID = "finance-backtest-integration-agent"
_MODEL_ID = "provider/model"
_DAY_ONE = "2024-01-02"
_DAY_TWO = "2024-01-03"
_DAY_THREE = "2024-01-04"
_FINGERPRINT = "frozen-model-fingerprint"
_NOW = datetime(2024, 1, 10, 12, 0, tzinfo=timezone.utc)


def _snapshot() -> data.BacktestSnapshot:
    candles = (
        data.Candle(_DAY_ONE, 10.0, 10.5, 9.5, 10.0, 100_000),
        data.Candle(_DAY_TWO, 10.0, 11.0, 9.5, 10.5, 100_000),
        data.Candle(_DAY_THREE, 10.5, 11.2, 10.0, 10.8, 100_000),
    )
    coverage = data.BacktestCoverage(
        requestedStartDate=_DAY_ONE,
        requestedEndDate=_DAY_THREE,
        actualStartDate=_DAY_ONE,
        actualEndDate=_DAY_THREE,
        availableStartDate=_DAY_ONE,
        availableEndDate=_DAY_THREE,
        tradingDays=len(candles),
        warmupBars=0,
        providerWindows=(
            {
                "startDate": _DAY_ONE,
                "endDate": _DAY_THREE,
                "rawBars": len(candles),
                "qfqBars": len(candles),
                "calendarBars": len(candles),
            },
        ),
        tradingCalendarStatus="tencent_index_checked",
        calendarSymbol="sh000001",
        complete=True,
    )
    return data.BacktestSnapshot(
        symbol="sh600000",
        start_date=_DAY_ONE,
        end_date=_DAY_THREE,
        candles=candles,
        warmup_candles=(),
        source="腾讯财经 fixture",
        source_url="https://example.invalid/quote/sh600000",
        fetched_at="2024-01-04T16:00:00+08:00",
        data_hash=data._stable_hash(candles, "sh600000", _DAY_ONE, _DAY_THREE),
        coverage=coverage,
        actions_status="factor_check_passed",
        action_dates=(),
        notice=("仅用于离线集成测试",),
    )


def _install_scenario(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    snapshot: data.BacktestSnapshot | None = None,
) -> tuple[FinancialBacktestStore, data.BacktestSnapshot, list[dict[str, Any]]]:
    agent = {
        "agentId": _AGENT_ID,
        "status": "active",
        "metadata": {
            "financialAssistantProfile": "financial_assistant_v1",
            "financialAssistantSetup": "ready",
        },
    }
    monkeypatch.setattr(agent_directory_service, "get_agent", lambda agent_id: dict(agent) if agent_id == _AGENT_ID else None)
    monkeypatch.setattr(agent_directory_service, "agent_dialogue_model_id", lambda _agent: _MODEL_ID)
    monkeypatch.setattr(service, "_model_fingerprint", lambda model_id: _FINGERPRINT)
    monkeypatch.setattr(runtime, "_model_fingerprint", lambda model_id: _FINGERPRINT)
    # Runtime-task and event journals are separate global lifecycle surfaces;
    # this test keeps all durable backtest artifacts in its real temporary store.
    monkeypatch.setattr(service, "_sync_runtime_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(runtime, "_sync_runtime_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(runtime, "_record_event", lambda *args, **kwargs: None)

    snapshot = snapshot or _snapshot()
    store = FinancialBacktestStore(path_resolver=lambda owner_id: tmp_path / owner_id / "ai-backtests")
    prepared_requests: list[dict[str, Any]] = []

    def prepare_data(payload: dict[str, Any]) -> data.BacktestSnapshot:
        prepared_requests.append(dict(payload))
        return snapshot

    # The service accepts the same callable used by prepare_data so the test
    # can avoid a network source while preserving the real snapshot validator.
    monkeypatch.setattr(service.data, "prepare_data", prepare_data)
    return store, snapshot, prepared_requests


def _preview_payload() -> dict[str, Any]:
    return {
        "symbol": "600000",
        "startDate": _DAY_ONE,
        "endDate": _DAY_THREE,
        "strategy": "首日买入，次日根据模拟持仓调整",
        "initialCash": 100_000,
        "maxPositionPct": 100,
        "decisionInterval": 1,
        "commissionBps": 3,
        "minimumCommission": 5,
        "slippageBps": 0,
        "maxDecisions": 10,
        "maxTokens": 2_000_000,
    }


def _new_preview(
    store: FinancialBacktestStore,
    *,
    data_loader,
) -> dict[str, Any]:
    return api.create_financial_backtest_preview(
        _AGENT_ID,
        _preview_payload(),
        store=store,
        data_loader=data_loader,
        now_provider=lambda: _NOW,
    )


def _decision(decision_input: dict[str, Any], target_weight: float) -> dict[str, Any]:
    input_hash = service.sha256_json(decision_input)
    payload = {
        "date": str(decision_input["asOfDate"]),
        "targetWeight": target_weight,
        "reason": "按测试策略调整模拟持仓",
        "modelId": _MODEL_ID,
        "inputHash": input_hash,
        "tokens": 37,
        "tokenAccounting": "measured",
    }
    payload["decisionHash"] = service.sha256_json(payload)
    return payload


def test_preview_start_worker_complete_and_export_use_real_disk_store(monkeypatch, tmp_path):
    store, _snapshot_value, prepared_requests = _install_scenario(monkeypatch, tmp_path)
    preview = _new_preview(store, data_loader=service.data.prepare_data)

    assert preview["canStart"] is True
    assert preview["decisionSchedule"] == [_DAY_ONE, _DAY_TWO]
    assert prepared_requests[0]["startDate"] == _DAY_ONE
    assert prepared_requests[0]["endDate"] == _DAY_THREE
    assert store.load_snapshot(_AGENT_ID, preview["dataHash"])["dataHash"] == preview["dataHash"]

    client_request_id = str(uuid4())
    first_start = api.start_financial_backtest_run(
        _AGENT_ID,
        client_request_id,
        preview["previewId"],
        store=store,
        now_provider=lambda: _NOW,
    )
    duplicate_start = api.start_financial_backtest_run(
        _AGENT_ID,
        client_request_id,
        preview["previewId"],
        store=store,
        now_provider=lambda: _NOW,
    )

    assert duplicate_start["runId"] == first_start["runId"]
    assert len(store.list_runs(_AGENT_ID)) == 1
    assert first_start["status"] == "queued"

    decision_inputs: list[dict[str, Any]] = []
    worker_inputs: list[dict[str, Any]] = []
    original_build_input = runtime.build_decision_input

    def capture_worker_input(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = original_build_input(*args, **kwargs)
        worker_inputs.append(result)
        return result

    monkeypatch.setattr(runtime, "build_decision_input", capture_worker_input)

    def infer_decision(**kwargs: Any) -> dict[str, Any]:
        decision_input = dict(kwargs["decision_input"])
        decision_inputs.append(decision_input)
        weight = 100 if decision_input["asOfDate"] == _DAY_ONE else 0
        return _decision(decision_input, weight)

    worker = runtime.FinancialBacktestWorker(
        store=store,
        assistant_loader=lambda: [_AGENT_ID],
        decision_runner=infer_decision,
        worker_id="integration-worker",
    )
    assert worker.process_pending_once(stop_requested=lambda: False) == 1

    completed = api.get_financial_backtest_run(_AGENT_ID, first_start["runId"], store=store)
    assert completed["status"] == "completed", (
        completed.get("errorCode"),
        completed.get("terminalReason"),
        completed.get("tokensUsed"),
        completed.get("maxTokens"),
        store.load_run(_AGENT_ID, first_start["runId"]).get("reservationPlan"),
        [runtime.reserve_decision_call(runtime.build_messages(item)) for item in worker_inputs],
    )
    assert completed["completedDecisionCount"] == 2
    assert completed["callsUsed"] == 2
    assert len(completed["trades"]) == 2
    assert [item["date"] for item in completed["decisions"]] == [_DAY_ONE, _DAY_TWO]
    assert [bar["date"] for bar in decision_inputs[0]["dailyBars"]] == [_DAY_ONE]
    assert [bar["date"] for bar in decision_inputs[1]["dailyBars"]] == [_DAY_ONE, _DAY_TWO]
    assert all(bar["date"] <= item["asOfDate"] for item in decision_inputs for bar in item["dailyBars"])
    assert decision_inputs[1]["portfolio"]["shares"] > 0
    assert decision_inputs[1]["portfolio"]["cash"] < 100_000
    run_dto = FinancialBacktestRun.model_validate(completed)
    assert run_dto.benchmarkOrders

    persisted = store.load_run(_AGENT_ID, first_start["runId"])
    assert persisted["benchmarkOrders"]
    json_export = api.export_financial_backtest_run(_AGENT_ID, first_start["runId"], "json", store=store)
    json_body = json.loads(json_export["content"])
    assert json_export["mediaType"] == "application/json"
    assert json_body["status"] == "completed"
    assert len(json_body["decisions"]) == 2
    assert json_body["benchmarkOrders"] == persisted["benchmarkOrders"]

    csv_export = api.export_financial_backtest_run(_AGENT_ID, first_start["runId"], "csv", store=store)
    rows = list(csv.reader(StringIO(csv_export["content"])))
    assert csv_export["mediaType"] == "text/csv"
    assert rows[0] == ["runId", "symbol", "status", "modelId", "modelConfigHash", "paramsHash", "dataHash"]
    assert any(row and row[0] == first_start["runId"] for row in rows)
    assert any(row[:2] == ["account", "signalDate"] for row in rows)
    assert any(row and row[0] == "benchmark" for row in rows)
    assert any(row[:2] == ["date", "targetWeight"] for row in rows)
    assert any(row[:2] == ["metric", "value"] for row in rows)


def test_stop_then_resume_keeps_successful_decision_and_skips_rebilling(monkeypatch, tmp_path):
    store, _snapshot_value, _prepared_requests = _install_scenario(monkeypatch, tmp_path)
    preview = _new_preview(store, data_loader=service.data.prepare_data)
    client_request_id = str(uuid4())
    started = api.start_financial_backtest_run(
        _AGENT_ID,
        client_request_id,
        preview["previewId"],
        store=store,
        now_provider=lambda: _NOW,
    )
    calls: list[dict[str, Any]] = []

    def infer_decision(**kwargs: Any) -> dict[str, Any]:
        decision_input = dict(kwargs["decision_input"])
        calls.append(decision_input)
        if decision_input["asOfDate"] == _DAY_ONE:
            stopping = api.request_financial_backtest_stop(_AGENT_ID, started["runId"], store=store)
            assert stopping["status"] == "stop_requested"
            assert stopping["startedAt"]
            return _decision(decision_input, 100)
        return _decision(decision_input, 0)

    worker = runtime.FinancialBacktestWorker(
        store=store,
        assistant_loader=lambda: [_AGENT_ID],
        decision_runner=infer_decision,
        worker_id="recovery-worker",
    )

    assert worker.process_pending_once(stop_requested=lambda: False) == 1
    stopped = api.get_financial_backtest_run(_AGENT_ID, started["runId"], store=store)
    assert stopped["status"] == "stopped"
    assert "尚未开始" not in stopped["terminalReason"]
    assert stopped["completedDecisionCount"] == 1
    assert stopped["decisions"][0]["date"] == _DAY_ONE

    resumed = api.resume_financial_backtest_run(_AGENT_ID, started["runId"], store=store)
    assert resumed["status"] == "queued"
    assert worker.process_pending_once(stop_requested=lambda: False) == 1

    completed = api.get_financial_backtest_run(_AGENT_ID, started["runId"], store=store)
    assert completed["status"] == "completed"
    assert completed["completedDecisionCount"] == 2
    assert completed["callsUsed"] == 2
    assert [item["asOfDate"] for item in calls] == [_DAY_ONE, _DAY_TWO]
    assert [item["date"] for item in completed["decisions"]] == [_DAY_ONE, _DAY_TWO]
    assert FinancialBacktestRun.model_validate(completed).status == "completed"


def test_benchmark_retries_after_zero_volume_rejection_and_passes_real_dto(monkeypatch, tmp_path):
    base = _snapshot()
    candles = (base.candles[0], replace(base.candles[1], volume=0), base.candles[2])
    snapshot = replace(
        base,
        candles=candles,
        data_hash=data._stable_hash(candles, base.symbol, base.start_date, base.end_date),
    )
    store, _snapshot_value, _prepared_requests = _install_scenario(
        monkeypatch, tmp_path, snapshot=snapshot
    )
    preview = _new_preview(store, data_loader=service.data.prepare_data)
    started = api.start_financial_backtest_run(
        _AGENT_ID,
        str(uuid4()),
        preview["previewId"],
        store=store,
        now_provider=lambda: _NOW,
    )
    worker = runtime.FinancialBacktestWorker(
        store=store,
        assistant_loader=lambda: [_AGENT_ID],
        decision_runner=lambda **kwargs: _decision(kwargs["decision_input"], 0),
        worker_id="benchmark-dto-worker",
    )

    assert worker.process_pending_once(stop_requested=lambda: False) == 1

    completed = api.get_financial_backtest_run(_AGENT_ID, started["runId"], store=store)
    dto = FinancialBacktestRun.model_validate(completed)
    assert dto.status == "completed"
    assert [order.status for order in dto.benchmarkOrders] == ["rejected", "filled"]
    assert [order.date for order in dto.benchmarkOrders] == [_DAY_TWO, _DAY_THREE]
