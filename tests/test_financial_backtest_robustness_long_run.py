"""Long-run robustness projection and export invariants on synthetic market data."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import tempfile
from copy import deepcopy
from datetime import date, timedelta
from io import StringIO
from pathlib import Path
from uuid import uuid4

import pytest

from core.web.routes.financial_backtest_models import FinancialBacktestRun
from core.web.services.financial_backtest import data, engine, service
from core.web.services.financial_backtest.store import FinancialBacktestStore

_AGENT_ID = "finance-robustness-long-run-test-agent"
_SESSION_COUNT = 500
_OOS_INDEX = 241
_INITIAL_CASH = 100_000.0


def _sessions(count: int) -> list[str]:
    current = date(2024, 1, 2)
    result: list[str] = []
    while len(result) < count:
        if current.weekday() < 5:
            result.append(current.isoformat())
        current += timedelta(days=1)
    return result


def _snapshot() -> data.BacktestSnapshot:
    days = _sessions(_SESSION_COUNT)
    candles: list[data.Candle] = []
    previous_close: float | None = None
    for index, day in enumerate(days):
        close = round(20 + 0.12 * math.sin(index / 4) + 0.002 * index, 2)
        opening = close if previous_close is None else previous_close
        candles.append(
            data.Candle(
                date=day,
                open=opening,
                high=round(max(opening, close) + 0.03, 2),
                low=round(min(opening, close) - 0.03, 2),
                close=close,
                volume=100_000 + (index % 5) * 1_000,
            )
        )
        previous_close = close

    rows = tuple(candles)
    coverage = data.BacktestCoverage(
        requestedStartDate=days[0],
        requestedEndDate=days[-1],
        actualStartDate=days[0],
        actualEndDate=days[-1],
        availableStartDate=days[0],
        availableEndDate=days[-1],
        tradingDays=len(rows),
        warmupBars=0,
        providerWindows=(),
        tradingCalendarStatus="tencent_index_checked",
        calendarSymbol="sh000001",
        complete=True,
    )
    return data.BacktestSnapshot(
        symbol="sh600000",
        start_date=days[0],
        end_date=days[-1],
        candles=rows,
        warmup_candles=(),
        source="合成测试数据",
        source_url="https://example.invalid/synthetic/sh600000",
        fetched_at="2025-12-31T16:00:00+08:00",
        data_hash=data._stable_hash(rows, "sh600000", days[0], days[-1]),
        coverage=coverage,
        actions_status="factor_check_passed",
        action_dates=(),
        notice=(
            "合成数据，仅用于稳健性界面验收；不代表真实行情、实盘收益或前瞻结论。",
        ),
    )


def test_500_session_oos_robustness_and_exports_are_read_only(monkeypatch, tmp_path):
    snapshot = _snapshot()
    days = [candle.date for candle in snapshot.candles]
    boundary = days[_OOS_INDEX]
    params = {
        "initialCash": _INITIAL_CASH,
        "maxPositionPct": 100,
        "decisionInterval": 20,
        "commissionBps": 8,
        "minimumCommission": 5,
        "slippageBps": 0,
        "maxDecisions": 500,
        "outOfSampleStartDate": boundary,
    }
    schedule = engine.build_decision_schedule(snapshot, params)
    decisions = [
        {
            "date": session,
            "targetWeight": 1.0 if index % 2 == 0 else 0.0,
            "reason": "确定性长周期合成策略",
        }
        for index, session in enumerate(schedule)
    ]
    simulation = engine.simulate(snapshot, params, decisions)
    stored_decisions = [
        {
            **decision,
            "targetWeight": decision["targetWeight"] * 100,
            "modelId": "synthetic/deterministic",
            "inputHash": hashlib.sha256(
                f"synthetic-input:{decision['date']}".encode()
            ).hexdigest(),
            "decisionHash": hashlib.sha256(
                f"synthetic-decision:{decision['date']}:{decision['targetWeight']}".encode()
            ).hexdigest(),
        }
        for decision in simulation["decisions"]
    ]

    assert len(simulation["equity"]) == _SESSION_COUNT
    assert len(schedule) == 25
    assert any(order["status"] == "filled" for order in simulation["orders"])
    assert sum(order["fee"] for order in simulation["orders"]) > 0

    run_id = str(uuid4())
    run = {
        "agentId": _AGENT_ID,
        "runId": run_id,
        "clientRequestId": str(uuid4()),
        "requestHash": "synthetic-long-run",
        "mode": "single",
        "symbol": snapshot.symbol,
        "symbols": [snapshot.symbol],
        "status": "completed",
        "progress": 1.0,
        "currentDecisionDate": schedule[-1],
        "decisionSchedule": list(schedule),
        "decisionCount": len(decisions),
        "completedDecisionCount": len(decisions),
        "callsUsed": len(decisions),
        "tokensUsed": 0,
        "estimatedTokens": 0,
        "tokensReserved": 0,
        "maxTokens": 500_000,
        "modelId": "synthetic/deterministic",
        "modelFingerprint": "synthetic-model-fingerprint",
        "paramsHash": "synthetic-params-hash",
        "dataHash": snapshot.data_hash,
        "params": {
            **simulation["parameters"],
            "strategy": "确定性长周期合成策略",
            "maxTokens": 500_000,
            "outOfSampleStartDate": boundary,
        },
        "dateCoverage": snapshot.coverage.to_dict(),
        "assetCoverage": {snapshot.symbol: snapshot.coverage.to_dict()},
        "assetDataHashes": {snapshot.symbol: snapshot.data_hash},
        "assetSources": {
            snapshot.symbol: {
                "source": snapshot.source,
                "sourceUrl": snapshot.source_url,
                "fetchedAt": snapshot.fetched_at,
            }
        },
        "outOfSampleStartDate": boundary,
        "actionsStatus": snapshot.actions_status,
        "actionDates": [],
        "source": snapshot.source,
        "sourceUrl": snapshot.source_url,
        "fetchedAt": snapshot.fetched_at,
        "adjustment": "raw",
        "notice": "\n".join(simulation["notice"]),
        "warnings": [],
        "decisions": stored_decisions,
        "metrics": simulation["metrics"],
        "evaluation": None,
        "equity": simulation["equity"],
        "trades": simulation["trades"],
        "orders": simulation["orders"],
        "benchmarkOrders": simulation["benchmarkOrders"],
        "benchmarkStatus": "invested",
        "unfilledBenchmarkSymbols": [],
        "startedAt": "2025-12-31T08:00:00+00:00",
        "createdAt": "2025-12-31T08:00:00+00:00",
        "updatedAt": "2025-12-31T08:00:00+00:00",
        "completedAt": "2025-12-31T08:01:00+00:00",
        "terminalReason": None,
        "errorCode": None,
        "uncertainDecisionDate": None,
        "tokenAccounting": "estimated",
    }
    store = FinancialBacktestStore(path_resolver=lambda owner: tmp_path / owner)
    store.create_run_if_absent(_AGENT_ID, run, max_runs=1)
    persisted_before = deepcopy(store.load_run(_AGENT_ID, run_id))

    projected = service.project_run(persisted_before)
    dto = FinancialBacktestRun.model_validate(projected)
    robustness = dto.robustness
    assert robustness is not None
    assert robustness.status == "available"
    assert robustness.scope == "out_of_sample"
    assert robustness.evaluatedStartDate == boundary
    assert robustness.evaluatedEndDate == days[-1]
    assert robustness.tradingDays == _SESSION_COUNT - _OOS_INDEX == 259
    assert robustness.completeWindowCount == 4
    assert robustness.partialWindowCount == 1
    assert [window.tradingDays for window in robustness.fixedWindows] == [
        63,
        63,
        63,
        63,
        7,
    ]
    assert [window.complete for window in robustness.fixedWindows] == [
        True,
        True,
        True,
        True,
        False,
    ]
    assert robustness.outperformingWindowRatePct is not None
    assert [window.label for window in robustness.annualWindows] == ["2024", "2025"]
    assert all(window.complete is None for window in robustness.annualWindows)

    first_window = robustness.fixedWindows[0]
    first_index = days.index(first_window.startDate)
    expected_first_return = (
        simulation["equity"][days.index(first_window.endDate)]["equity"]
        / simulation["equity"][first_index - 1]["equity"]
        - 1
    ) * 100
    assert first_window.baselineDate == days[first_index - 1]
    assert first_window.metrics.totalReturnPct == pytest.approx(expected_first_return)
    for window in robustness.fixedWindows:
        expected_fees = sum(
            float(order["fee"])
            for order in simulation["orders"]
            if order["status"] == "filled"
            and order["filledShares"] > 0
            and window.startDate <= order["date"] <= window.endDate
        )
        assert window.metrics.fees == pytest.approx(expected_fees)

    monkeypatch.setattr(service, "_require_owner", lambda owner: {"agentId": owner})
    json_export = service.export_financial_backtest_run(
        _AGENT_ID, run_id, "json", store=store
    )
    json_body = json.loads(json_export["content"])
    assert json_body["robustness"] == dto.model_dump(mode="json")["robustness"]
    assert json_body["equity"] == simulation["equity"]

    csv_export = service.export_financial_backtest_run(
        _AGENT_ID, run_id, "csv", store=store
    )
    csv_rows = list(csv.reader(StringIO(csv_export["content"])))
    assert ["periodEvaluation", "field", "value"] in csv_rows
    # CSV contains separate tables; later advanced-evaluation summary rows
    # must not overwrite the period-evaluation table being asserted here.
    period_start = csv_rows.index(["periodEvaluation", "field", "value"]) + 1
    period_end = next((index for index in range(period_start, len(csv_rows))
                       if not csv_rows[index]), len(csv_rows))
    csv_values = {
        (row[0], row[1]): row[2]
        for row in csv_rows[period_start:period_end]
        if len(row) == 3 and row[0] and row[1]
    }
    assert csv_values[("summary", "status")] == "available"
    assert csv_values[("summary", "scope")] == "out_of_sample"
    assert csv_values[("summary", "tradingDays")] == "259"
    for window in robustness.fixedWindows:
        label = f"fixedWindows:{window.startDate}"
        assert int(csv_values[(label, "tradingDays")]) == window.tradingDays
        assert float(csv_values[(label, "fees")]) == pytest.approx(window.metrics.fees)
        assert float(csv_values[(label, "totalReturnPct")]) == pytest.approx(
            window.metrics.totalReturnPct
        )

    assert store.load_run(_AGENT_ID, run_id) == persisted_before
    if os.environ.get("FINANCE_DEPTH_WRITE_UI_FIXTURE") == "1":
        fixture_path = Path(tempfile.gettempdir()) / "finance-depth-ui-fixture.json"
        fixture_path.write_text(
            json.dumps(dto.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
