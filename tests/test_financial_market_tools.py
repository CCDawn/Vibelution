import json
from datetime import date, timedelta

import pytest

from core.infrastructure.tool_result import DEFAULT_MAX_CHARS, infer_tool_business_success
from core.web.services import financial_market_service as market
from core.web.services import financial_research_service as research
from tools.financial_market_tools import (
    MAX_RESULT_CHARS,
    MAX_SCREEN_RESULT_CHARS,
    financial_market_screen_tool,
    financial_market_snapshot_tool,
)


def quote(symbol="sz000001"):
    return {
        "symbol": symbol,
        "ticker": symbol[2:],
        "name": "平安银行",
        "market": "深交所",
        "price": 12.34,
        "previousClose": 12.1,
        "open": 12.2,
        "high": 12.5,
        "low": 12.0,
        "change": 0.24,
        "changePercent": 1.98,
        "volumeLots": 12345,
        "turnoverYuan": 150000000.0,
        "timestamp": "2026-10-05T15:00:00+08:00",
    }


def candle(day, close=12.34):
    return {
        "date": day,
        "open": 12.1,
        "close": close,
        "high": 12.5,
        "low": 12.0,
        "volumeLots": 12345,
    }


def snapshot(symbol="sz000001", candles=None, candle_error=""):
    return {
        "stock": quote(symbol),
        "candles": [candle("2026-10-03"), candle("2026-10-05", 12.34)] if candles is None else candles,
        "period": "day",
        "adjustment": "qfq",
        "source": "腾讯财经",
        "sourceUrl": f"https://gu.qq.com/{symbol}/gp",
        "fetchedAt": "2026-10-05T07:00:00+00:00",
        "candleError": candle_error,
    }


def result_json(*args, **kwargs):
    raw = financial_market_snapshot_tool(*args, **kwargs)
    assert len(raw) <= MAX_RESULT_CHARS
    return json.loads(raw)


def test_valid_request_delegates_explicit_ticker_and_preserves_provenance_and_units(monkeypatch):
    calls = []

    def get_stock_snapshot(ticker, period):
        calls.append((ticker, period))
        return snapshot(ticker)

    monkeypatch.setattr(market, "get_stock_snapshot", get_stock_snapshot)

    result = result_json("SZ000001", "week", 1)

    assert calls == [("sz000001", "week")]
    assert result["ok"] is True
    assert infer_tool_business_success(json.dumps(result, ensure_ascii=False)) is True
    assert result["status"] == "partial"
    assert result["ticker"] == "sz000001"
    assert result["requestedLimit"] == 1
    assert result["availableCandleCount"] == 2
    assert result["returnedCandleCount"] == 1
    assert result["omittedCandleCount"] == 1
    assert result["source"] == "腾讯财经"
    assert result["sourceUrl"] == "https://gu.qq.com/sz000001/gp"
    assert result["fetchedAt"] == "2026-10-05T07:00:00+00:00"
    assert result["quote"]["timestamp"] == "2026-10-05T15:00:00+08:00"
    assert result["adjustment"] == "qfq"
    assert result["priceUnit"] == "元"
    assert result["volumeUnit"] == "手（1手=100股）"
    assert result["period"] == "week"
    assert result["candles"]["columns"] == ["date", "open", "close", "high", "low", "volumeLots"]
    assert result["candles"]["rows"] == [["2026-10-05", 12.1, 12.34, 12.5, 12.0, 12345]]


@pytest.mark.parametrize(
    ("ticker", "expected"),
    [("600519", "sh600519"), ("000001", "sz000001"), ("430047", "bj430047")],
)
def test_six_digit_ticker_is_normalized_by_market_service(monkeypatch, ticker, expected):
    calls = []

    def get_stock_snapshot(symbol, period):
        calls.append((symbol, period))
        return snapshot(symbol)

    monkeypatch.setattr(market, "get_stock_snapshot", get_stock_snapshot)

    result = result_json(ticker)

    assert calls == [(expected, "day")]
    assert result["ticker"] == expected
    assert result["ok"] is True


@pytest.mark.parametrize(
    ("ticker", "period", "limit"),
    [
        (None, "day", 20),
        ("https://example.com", "day", 20),
        ("贵州茅台", "day", 20),
        ("123456", "day", 20),
        ("sh000001", "day", 20),
        ("sz600519", "day", 20),
        ("bj600519", "day", 20),
        ("sz000001", "minute", 20),
        ("sz000001", "DAY", 20),
        ("sz000001", "day", True),
        ("sz000001", "day", False),
        ("sz000001", "day", 1.5),
        ("sz000001", "day", "20"),
        ("sz000001", "day", None),
        ("sz000001", "day", 0),
        ("sz000001", "day", 121),
    ],
)
def test_invalid_inputs_never_call_market_provider(monkeypatch, ticker, period, limit):
    calls = []
    monkeypatch.setattr(market, "get_stock_snapshot", lambda *args: calls.append(args))

    result = result_json(ticker, period, limit)

    assert result["ok"] is False
    assert infer_tool_business_success(json.dumps(result, ensure_ascii=False)) is False
    assert result["status"] == "invalid_request"
    assert calls == []


def test_quote_failure_returns_unavailable_without_exception_url_or_fake_data(monkeypatch):
    def fail(*args):
        raise market.MarketDataError("request failed at https://private.example/path?token=secret")

    monkeypatch.setattr(market, "get_stock_snapshot", fail)

    raw = financial_market_snapshot_tool("sh600519")
    result = json.loads(raw)

    assert result["status"] == "unavailable"
    assert result["ok"] is False
    assert result["errorCode"] == "market_data_error"
    assert infer_tool_business_success(raw) is False
    assert result["quote"] is None
    assert result["candles"]["rows"] == []
    assert result["requestedLimit"] == 20
    assert "private.example" not in raw
    assert "secret" not in raw
    assert "Traceback" not in raw
    assert "暂不可用" in result["message"]


def test_unexpected_provider_failure_is_redacted(monkeypatch):
    monkeypatch.setattr(
        market,
        "get_stock_snapshot",
        lambda *args: (_ for _ in ()).throw(RuntimeError("https://private.example/path")),
    )

    raw = financial_market_snapshot_tool("sh600519")
    result = json.loads(raw)

    assert result["ok"] is False
    assert result["errorCode"] == "provider_error"
    assert "private.example" not in raw


def test_stock_not_found_has_a_safe_specific_error_code(monkeypatch):
    def fail(*args):
        raise market.StockNotFound("provider detail https://private.example/lookup")

    monkeypatch.setattr(market, "get_stock_snapshot", fail)

    raw = financial_market_snapshot_tool("sh600519")
    result = json.loads(raw)

    assert result["ok"] is False
    assert result["status"] == "unavailable"
    assert result["errorCode"] == "stock_not_found"
    assert "private.example" not in raw


def test_candle_failure_keeps_quote_and_returns_safe_partial_result(monkeypatch):
    monkeypatch.setattr(
        market,
        "get_stock_snapshot",
        lambda ticker, period: snapshot(ticker, candles=[], candle_error="provider URL https://bad.example"),
    )

    raw = financial_market_snapshot_tool("sh600519", "month", 5)
    result = json.loads(raw)

    assert result["ok"] is True
    assert infer_tool_business_success(raw) is True
    assert result["status"] == "partial"
    assert result["quote"]["timestamp"] == "2026-10-05T15:00:00+08:00"
    assert result["candles"]["rows"] == []
    assert result["availableCandleCount"] == 0
    assert result["returnedCandleCount"] == 0
    assert "bad.example" not in raw
    assert "暂不可用" in result["candleError"]


def test_known_service_candle_error_is_preserved(monkeypatch):
    message = "K 线数据无效，请重试"
    monkeypatch.setattr(
        market,
        "get_stock_snapshot",
        lambda ticker, period: snapshot(ticker, candles=[], candle_error=message),
    )

    result = result_json("sh600519")

    assert result["status"] == "partial"
    assert result["ok"] is True
    assert result["candleError"] == message


def test_result_budget_trims_oldest_candles_and_keeps_newest_with_valid_json(monkeypatch):
    first = date(2026, 1, 1)
    candles = [
        candle((first + timedelta(days=index)).isoformat(), close=12.123456789 + index)
        for index in range(120)
    ]
    monkeypatch.setattr(market, "get_stock_snapshot", lambda ticker, period: snapshot(ticker, candles=candles))

    raw = financial_market_snapshot_tool("sz000001", limit=120)
    result = json.loads(raw)
    rows = result["candles"]["rows"]

    assert len(raw) <= MAX_RESULT_CHARS
    assert result["ok"] is True
    assert result["status"] == "partial"
    assert result["requestedLimit"] == 120
    assert result["availableCandleCount"] == 120
    assert 0 < result["returnedCandleCount"] < 120
    assert result["omittedCandleCount"] == 120 - result["returnedCandleCount"]
    assert rows[-1][0] == candles[-1]["date"]
    assert rows[0][0] == candles[-result["returnedCandleCount"]]["date"]


def test_adapter_budget_is_below_native_tool_result_limit():
    assert MAX_RESULT_CHARS <= DEFAULT_MAX_CHARS
    assert MAX_SCREEN_RESULT_CHARS <= DEFAULT_MAX_CHARS


def test_market_screen_tool_passes_filters_and_preserves_source_coverage(monkeypatch):
    calls = []
    screen = {
        "source": "新浪财经",
        "sourceUrl": "https://vip.stock.finance.sina.com.cn/mkt/#hs_a",
        "fetchedAt": "2026-10-05T07:00:00+00:00",
        "dataDate": None,
        "dataTime": "15:00:00",
        "resultScope": "loaded_subset",
        "coverage": {
            "providerTotal": 6000,
            "loaded": 5920,
            "complete": False,
            "failedPages": [2],
            "invalidRows": 0,
            "duplicateRows": 0,
            "totalFiltered": 1,
        },
        "items": [{
            "symbol": "sh600519",
            "ticker": "600519",
            "name": "贵州茅台",
            "market": "上交所",
            "price": 1600.0,
            "changePercent": 1.2,
            "peRatio": 25.0,
            "pbRatio": 8.0,
            "volumeLots": 1234,
            "turnoverYuan": 1900000000.0,
            "timeOfDay": "15:00:00",
            "totalMarketCapYuan": None,
        }],
    }

    def screen_stocks(**kwargs):
        calls.append(kwargs)
        return screen

    monkeypatch.setattr(research, "screen_stocks", screen_stocks)
    raw = financial_market_screen_tool(
        min_price=100,
        max_change_percent=8,
        min_pe=5,
        max_pb=10,
        min_turnover_yuan=1_000_000,
        sort_by="turnoverYuan",
        direction="asc",
        limit=2,
    )
    result = json.loads(raw)

    assert calls == [{
        "min_price": 100,
        "max_price": None,
        "min_change_percent": None,
        "max_change_percent": 8,
        "min_pe": 5,
        "max_pe": None,
        "min_volume_lots": None,
        "min_pb": None,
        "max_pb": 10,
        "min_turnover_yuan": 1_000_000,
        "max_turnover_yuan": None,
        "sort_by": "turnoverYuan",
        "direction": "asc",
        "page": 1,
        "page_size": 2,
    }]
    assert len(raw) <= MAX_SCREEN_RESULT_CHARS
    assert result["ok"] is True and result["status"] == "partial"
    assert result["resultScope"] == "loaded_subset"
    assert result["coverage"]["failedPages"] == [2]
    assert result["requestedFilters"] == {
        "min_price": 100,
        "max_change_percent": 8,
        "min_pe": 5,
        "max_pb": 10,
        "min_turnover_yuan": 1_000_000,
    }
    assert result["source"] == "新浪财经"
    assert result["fetchedAt"] != result["dataTime"]
    assert result["dataDate"] is None
    assert result["items"][0]["symbol"] == "sh600519"
    assert "totalMarketCapYuan" not in result["items"][0]
    assert "交易日期" in result["notice"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"min_price": float("nan")},
        {"min_volume_lots": True},
        {"min_turnover_yuan": -1},
        {"min_price": 20, "max_price": 10},
        {"limit": 21},
        {"sort_by": "marketCap"},
    ],
)
def test_market_screen_tool_rejects_invalid_criteria_before_provider_call(kwargs, monkeypatch):
    calls = []
    monkeypatch.setattr(research, "screen_stocks", lambda **values: calls.append(values) or {})

    result = json.loads(financial_market_screen_tool(**kwargs))

    assert result["ok"] is False
    assert result["status"] == "invalid_request"
    assert calls == []
