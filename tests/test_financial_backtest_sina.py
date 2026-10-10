"""Sina JSONP source contracts; these tests never access the live provider."""

import json
from datetime import date
from urllib.parse import parse_qs, urlsplit

import pytest

from core.web.services.financial_backtest import data, sina


def _jsonp(payload, assignment: str | None = None) -> str:
    prefix = f"{assignment}" if assignment else ""
    return f"{prefix}=({json.dumps(payload, separators=(',', ':'))});"


def _bar(day: str, *, volume: int = 12_345, price: str = "10.00") -> dict:
    return {
        "day": day,
        "open": price,
        "high": "11.00",
        "low": "9.00",
        "close": "10.50",
        "volume": volume,
    }


def _factor_wire(symbol: str, factors: list[dict]) -> str:
    payload = json.dumps({"data": factors, "total": len(factors)}, separators=(",", ":"))
    return f"var {symbol}qfq={payload};\n/* provider metadata */"


def _install_reader(monkeypatch, stock_rows, calendar_rows=None, factors=None):
    calls: list[str] = []

    def read(url: str) -> str:
        calls.append(url)
        if url.endswith("/qfq.js"):
            symbol = url.split("/company/", 1)[1].split("/", 1)[0]
            return _factor_wire(symbol, factors or [])
        params = parse_qs(urlsplit(url).query)
        symbol = params["symbol"][0]
        rows = calendar_rows if symbol == "sh000001" and calendar_rows is not None else stock_rows
        return _jsonp(rows)

    monkeypatch.setattr(sina, "read_historical", read)
    return calls


def _week_rows(*, include_all: bool = True) -> list[dict]:
    days = ["2025-10-31", "2025-11-03", "2025-11-04", "2025-11-05", "2025-11-06", "2025-11-07"]
    if not include_all:
        days.remove("2025-11-04")
    return [_bar(day, volume=21_935_399 + index) for index, day in enumerate(days)]


def _calendar_rows(*, include_all: bool = True) -> list[dict]:
    days = ["2025-10-31", "2025-11-03", "2025-11-04", "2025-11-05", "2025-11-06", "2025-11-07"]
    if not include_all:
        days.remove("2025-11-04")
    return [
        {
            "day": day,
            "open": "3000.00",
            "high": "3010.00",
            "low": "2990.00",
            "close": "3005.00",
            "volume": 1_000_000,
        }
        for day in days
    ]


def _prepare(monkeypatch, stock_rows, calendar_rows=None, factors=None):
    _install_reader(monkeypatch, stock_rows, calendar_rows, factors)
    return data._prepare_data(
        {
            "symbol": "bj920185",
            "startDate": "2025-11-03",
            "endDate": "2025-11-07",
            "warmupBars": 0,
        },
        today="2026-01-01",
        fetcher=sina.fetch_window,
        provider="sina",
    )


def test_fetch_window_filters_requested_dates_and_preserves_share_volume(monkeypatch):
    raw_rows = [_bar(day) for day in (
        "2025-10-31", "2025-11-03", "2025-11-04", "2025-11-05",
        "2025-11-06", "2025-11-07", "2025-11-10",
    )]
    calls = _install_reader(monkeypatch, raw_rows)

    rows = sina.fetch_window("bj920185", date(2025, 11, 3), date(2025, 11, 7), "none")

    assert len(calls) == 1
    params = parse_qs(urlsplit(calls[0]).query)
    assert params == {
        "symbol": ["bj920185"],
        "scale": ["240"],
        "ma": ["no"],
        "datalen": ["1023"],
    }
    assert [row[0] for row in rows] == [
        "2025-11-03", "2025-11-04", "2025-11-05", "2025-11-06", "2025-11-07"
    ]
    parsed = data._parse_rows(rows, "bj920185")
    assert parsed[0]["volume"] == 12_345


def test_fetch_window_accepts_only_sinas_fixed_kline_preamble(monkeypatch):
    preamble = "/*<script>location.href='//sina.com';</script>*/\n"
    monkeypatch.setattr(
        sina,
        "read_historical",
        lambda _url: preamble + _jsonp([_bar("2025-11-03")]),
    )

    rows = sina.fetch_window("bj920185", date(2025, 11, 3), date(2025, 11, 3), "none")

    assert [row[0] for row in rows] == ["2025-11-03"]


@pytest.mark.parametrize(
    "body",
    [
        "not JSONP",
        "=({day:'2025-11-03'});",
        "=(NaN);",
        "=([]);alert(1)",
    ],
)
def test_rejects_bad_jsonp_without_evaluating_javascript(monkeypatch, body):
    monkeypatch.setattr(sina, "read_historical", lambda _url: body)
    with pytest.raises(data.BacktestDataError):
        sina.fetch_window("bj920185", date(2025, 11, 3), date(2025, 11, 7), "none")


def test_rejects_negative_volume(monkeypatch):
    _install_reader(monkeypatch, [_bar("2025-11-03", volume=-1)])

    with pytest.raises(data.BacktestDataError, match="成交量校验失败"):
        sina.fetch_window("bj920185", date(2025, 11, 3), date(2025, 11, 7), "none")


def test_rejects_fractional_share_volume(monkeypatch):
    _install_reader(monkeypatch, [_bar("2025-11-03", volume="12345.5")])

    with pytest.raises(data.BacktestDataError, match="整数股"):
        sina.fetch_window("bj920185", date(2025, 11, 3), date(2025, 11, 7), "none")


def test_rejects_duplicate_or_out_of_order_daily_bars(monkeypatch):
    _install_reader(monkeypatch, [_bar("2025-11-04"), _bar("2025-11-03")])

    with pytest.raises(data.BacktestDataError, match="重复日期或乱序"):
        sina.fetch_window("bj920185", date(2025, 11, 3), date(2025, 11, 7), "none")


def test_qfq_uses_effective_factor_and_keeps_share_volume(monkeypatch):
    rows = [_bar("2025-11-03", price="10.00"), _bar("2025-11-04", price="10.00")]
    factors = [
        {"d": "1900-01-01", "f": 1},
        {"d": "2025-11-04", "f": 2},
    ]
    calls = _install_reader(monkeypatch, rows, factors=factors)

    adjusted = sina.fetch_window(
        "bj920185", date(2025, 11, 3), date(2025, 11, 4), "qfq"
    )

    assert len(calls) == 2
    assert [row[1] for row in adjusted] == ["10.00", "5.00"]
    assert [data._parse_rows([row], "bj920185")[0]["volume"] for row in adjusted] == [
        12_345, 12_345
    ]


@pytest.mark.parametrize(
    "factors",
    [
        [],
        [{"d": "2025-11-04", "f": 2}],
        [{"d": "1900-01-01", "f": 0}],
    ],
)
def test_missing_or_invalid_qfq_factor_blocks_qfq_rows(monkeypatch, factors):
    _install_reader(monkeypatch, [_bar("2025-11-03")], factors=factors)

    with pytest.raises(data.BacktestDataError, match="因子|覆盖|基准"):
        sina.fetch_window("bj920185", date(2025, 11, 3), date(2025, 11, 3), "qfq")


def test_qfq_factor_assignment_must_match_requested_symbol(monkeypatch):
    def read(url: str) -> str:
        if url.endswith("/qfq.js"):
            payload = json.dumps(
                {"data": [{"d": "1900-01-01", "f": 1}], "total": 1},
                separators=(",", ":"),
            )
            return f"var bj835185qfq={payload};"
        return _jsonp([_bar("2025-11-03")])

    monkeypatch.setattr(sina, "read_historical", read)
    with pytest.raises(data.BacktestDataError, match="因子身份"):
        sina.fetch_window("bj920185", date(2025, 11, 3), date(2025, 11, 3), "qfq")


def test_qfq_assignment_rejects_executable_trailing_javascript(monkeypatch):
    def read(url: str) -> str:
        if url.endswith("/qfq.js"):
            payload = json.dumps(
                {"data": [{"d": "1900-01-01", "f": 1}], "total": 1},
                separators=(",", ":"),
            )
            return f"var bj920185qfq={payload};alert('unexpected');"
        return _jsonp([_bar("2025-11-03")])

    monkeypatch.setattr(sina, "read_historical", read)
    with pytest.raises(data.BacktestDataError, match="赋值边界"):
        sina.fetch_window("bj920185", date(2025, 11, 3), date(2025, 11, 3), "qfq")


def test_prepare_snapshot_uses_sina_source_and_complete_index_calendar(monkeypatch):
    snapshot = _prepare(
        monkeypatch,
        _week_rows(),
        _calendar_rows(),
        [{"d": "1900-01-01", "f": 1}],
    )

    data.validate_snapshot(snapshot)
    assert snapshot.source == "新浪财经"
    assert snapshot.symbol == "bj920185"
    assert snapshot.coverage.tradingCalendarStatus == "sina_index_checked"
    assert snapshot.coverage.calendarSymbol == "sh000001"
    assert snapshot.coverage.requestedStartDate == "2025-11-03"
    assert snapshot.coverage.requestedEndDate == "2025-11-07"
    assert [candle.date for candle in snapshot.candles] == [
        "2025-11-03", "2025-11-04", "2025-11-05", "2025-11-06", "2025-11-07"
    ]


def test_prepare_snapshot_blocks_detected_company_action(monkeypatch):
    factors = [
        {"d": "1900-01-01", "f": 1},
        {"d": "2025-11-05", "f": 2},
    ]
    _install_reader(monkeypatch, _week_rows(), _calendar_rows(), factors)

    with pytest.raises(data.CorporateActionUnsupported):
        data._prepare_data(
            {
                "symbol": "bj920185",
                "startDate": "2025-11-03",
                "endDate": "2025-11-07",
                "warmupBars": 0,
            },
            today="2026-01-01",
            fetcher=sina.fetch_window,
            provider="sina",
        )


def test_prepare_snapshot_blocks_stock_calendar_session_gap(monkeypatch):
    _install_reader(
        monkeypatch,
        _week_rows(include_all=False),
        _calendar_rows(),
        [{"d": "1900-01-01", "f": 1}],
    )

    with pytest.raises(data.BacktestDataError, match="交易日历不一致"):
        data._prepare_data(
            {
                "symbol": "bj920185",
                "startDate": "2025-11-03",
                "endDate": "2025-11-07",
                "warmupBars": 0,
            },
            today="2026-01-01",
            fetcher=sina.fetch_window,
            provider="sina",
        )
