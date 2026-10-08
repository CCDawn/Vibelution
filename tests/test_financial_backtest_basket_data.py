from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, timedelta

import pytest

from core.web.services.financial_backtest import basket_data, data
from core.web.services.financial_backtest.data import (
    BacktestCoverage,
    BacktestSnapshot,
    Candle,
)


def _weekdays(start: str, count: int) -> list[str]:
    current = date.fromisoformat(start)
    days: list[str] = []
    while len(days) < count:
        if current.weekday() < 5:
            days.append(current.isoformat())
        current += timedelta(days=1)
    return days


def _wire_row(day: str, price: float) -> list[str]:
    return [
        day,
        f"{price:.2f}",
        f"{price:.2f}",
        f"{price + 0.5:.2f}",
        f"{price - 0.5:.2f}",
        "100000",
    ]


def _asset_snapshot(symbol: str, days: list[str]) -> BacktestSnapshot:
    candles = tuple(Candle(day, 10.0, 11.0, 9.0, 10.0, 100_000) for day in days)
    return BacktestSnapshot(
        symbol=symbol,
        start_date=days[0],
        end_date=days[-1],
        candles=candles,
        warmup_candles=(),
        source="fixture",
        source_url=f"https://example.invalid/{symbol}",
        fetched_at="2024-01-08T16:00:00+08:00",
        data_hash=data._stable_hash(candles, symbol, days[0], days[-1]),
        coverage=BacktestCoverage(
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
        ),
        actions_status="factor_check_passed",
        action_dates=(),
        notice=("fixture notice",),
    )


def test_prepare_basket_data_canonicalizes_and_round_trips_all_asset_coverage(
    monkeypatch,
):
    days = _weekdays("2024-01-02", 4)
    stock_rows = {
        "sh600000": [
            _wire_row(day, 10 + index / 100) for index, day in enumerate(days)
        ],
        "sh600001": [
            _wire_row(day, 20 + index / 100) for index, day in enumerate(days)
        ],
    }
    calendar_rows = [_wire_row(day, 3_000 + index) for index, day in enumerate(days)]

    def fetch(symbol: str, start: date, end: date, adjustment: str) -> list[list[str]]:
        rows = calendar_rows if symbol == "sh000001" else stock_rows[symbol]
        return [
            row[:] for row in rows if start.isoformat() <= row[0] <= end.isoformat()
        ]

    monkeypatch.setattr(data, "_fetch_window", fetch)

    snapshot = basket_data.prepare_basket_data(
        ["600001", "sh600000"], days[0], days[-1], warmup_bars=0, today="2024-01-08"
    )
    restored = basket_data.restore_basket_snapshot(
        json.loads(json.dumps(snapshot.to_dict(), ensure_ascii=False))
    )

    assert snapshot.symbols == ("sh600000", "sh600001")
    assert snapshot.to_dict()["schemaVersion"] == 2
    assert snapshot.session_dates == tuple(days)
    assert snapshot.start_date == days[0]
    assert snapshot.end_date == days[-1]
    assert restored.to_dict() == snapshot.to_dict()
    assert set(restored.assets) == set(snapshot.symbols)
    assert (
        restored.assets["sh600001"].coverage.to_dict()
        == snapshot.assets["sh600001"].coverage.to_dict()
    )
    assert snapshot.data_hash == restored.data_hash


def test_prepare_basket_data_fails_when_assets_have_different_session_dates(
    monkeypatch,
):
    full = _weekdays("2024-01-02", 4)
    partial = [full[0], full[2], full[3]]
    assets = {
        "sh600000": _asset_snapshot("sh600000", full),
        "sh600001": _asset_snapshot("sh600001", partial),
    }

    def prepare(payload, *, today=None):
        return assets[payload["symbol"]]

    monkeypatch.setattr(basket_data.single_data, "prepare_data", prepare)

    with pytest.raises(
        data.BacktestDataError, match="交易日历或区间覆盖不一致"
    ) as captured:
        basket_data.prepare_basket_data(["600000", "600001"], full[0], full[-1])

    assert captured.value.metadata["calendarStatus"] == "asset_mismatch"
    assert captured.value.metadata["symbol"] == "sh600001"


def test_basket_hash_and_asset_hash_tampering_fail_closed():
    days = _weekdays("2024-01-02", 3)
    assets = {
        "sh600000": _asset_snapshot("sh600000", days),
        "sh600001": _asset_snapshot("sh600001", days),
    }
    original = basket_data.BasketSnapshot(
        symbols=("sh600000", "sh600001"),
        assets=assets,
        session_dates=tuple(days),
        start_date=days[0],
        end_date=days[-1],
        data_hash=basket_data._stable_basket_hash(
            ("sh600000", "sh600001"), assets, tuple(days), days[0], days[-1]
        ),
        source="fixture",
        notice=(),
    )
    basket_data.validate_basket_snapshot(original)

    with pytest.raises(data.BacktestDataError, match="组合快照行情摘要校验失败"):
        basket_data.validate_basket_snapshot(replace(original, data_hash="0" * 64))

    tampered_payload = original.to_dict()
    tampered_payload["assets"]["sh600000"]["candles"][0]["close"] = 10.01
    with pytest.raises(data.BacktestDataError, match="摘要校验失败"):
        basket_data.restore_basket_snapshot(tampered_payload)

    for version in (None, 1, True):
        version_payload = original.to_dict()
        if version is None:
            del version_payload["schemaVersion"]
        else:
            version_payload["schemaVersion"] = version
        with pytest.raises(data.BacktestDataError, match="schemaVersion必须为2"):
            basket_data.restore_basket_snapshot(version_payload)


def test_duplicate_canonical_symbols_are_rejected():
    with pytest.raises(data.BacktestInputError, match="重复股票代码"):
        basket_data.prepare_basket_data(
            ["600000", "sh600000"], "2024-01-02", "2024-01-04"
        )


def test_basket_symbol_limit_is_ten():
    symbols = [f"600{value:03}" for value in range(11)]

    with pytest.raises(data.BacktestInputError, match="最多支持10只A股"):
        basket_data.prepare_basket_data(symbols, "2024-01-02", "2024-01-04")
