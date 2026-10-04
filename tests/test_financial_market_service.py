"""Market provenance, OHLC/units, bounded identifiers and API failure semantics."""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.web.routes.financial_assistant import router
from core.web.services import financial_market_service as market


def quote_wire():
    fields = [""] * 50
    for index, value in {1: "贵州茅台", 2: "600519", 3: "1258.62", 4: "1235.58", 5: "1239.53", 6: "38331", 30: "20260930161458", 31: "23.04", 32: "1.86", 33: "1268", 34: "1236.05", 37: "479725", 39: "19.32", 45: "15733.78", 46: "6.26"}.items():
        fields[index] = value
    return 'v_sh600519="' + "~".join(fields) + '";'


def candles_wire(rows=None):
    return json.dumps({"code": 0, "data": {"sh600519": {"qfqday": rows if rows is not None else [["2026-09-30", "1239.53", "1258.62", "1268", "1236.05", "38331"]]}}})


@pytest.fixture(autouse=True)
def clear_cache():
    market._CACHE.clear()
    yield
    market._CACHE.clear()


def test_quote_preserves_exchange_time_and_explicit_units():
    row = market.parse_quote(quote_wire(), "sh600519")
    assert row["timestamp"] == "2026-09-30T16:14:58+08:00"
    assert row["volumeLots"] == 38331
    assert row["turnoverYuan"] == 4_797_250_000
    assert row["totalMarketCapYuan"] == 1_573_378_000_000
    assert row["peRatio"] == 19.32 and row["pbRatio"] == 6.26


@pytest.mark.parametrize("value", ["../../secret", "https://example.com", "sh600519?url=foo", "sz600519", "sh000001", "sh600519,sz000001", "123456"])
def test_identifiers_cannot_change_provider_url(value):
    with pytest.raises(market.MarketDataError):
        market.normalize_symbol(value)


def test_candles_are_ordered_and_keep_provider_ohlc_and_lots():
    assert market.parse_candles(candles_wire(), "sh600519", "day") == [{"date": "2026-09-30", "open": 1239.53, "close": 1258.62, "high": 1268, "low": 1236.05, "volumeLots": 38331}]
    for rows in [[["2026-09-30", "1", "2", "1", "1", "1"]], [["2026-09-30", "1", "2", "2", "1", "nan"]], [["2026-09-30", "1", "2", "2", "1", "1"]] * 2]:
        with pytest.raises(market.MarketDataError):
            market.parse_candles(candles_wire(rows), "sh600519", "day")


def test_unadjusted_fallback_is_not_presented_as_forward_adjusted():
    raw = json.dumps({"code": 0, "data": {"sh600519": {
        "day": [["2026-09-30", "1239.53", "1258.62", "1268", "1236.05", "38331"]],
    }}})
    with pytest.raises(market.MarketDataError):
        market.parse_candles(raw, "sh600519", "day")


def test_snapshot_keeps_quote_when_chart_fails_and_does_not_invent_candles(monkeypatch):
    def read(url, encoding="utf-8"):
        if "qt.gtimg" in url:
            return quote_wire()
        raise market.MarketDataError("provider offline")
    monkeypatch.setattr(market, "_read", read)
    snapshot = market.get_stock_snapshot("600519")
    assert snapshot["stock"]["price"] == 1258.62
    assert snapshot["candles"] == [] and snapshot["candleError"] == "provider offline"
    assert snapshot["source"] == "腾讯财经" and "延迟" in snapshot["notice"]


def test_stock_search_parses_data_without_evaluating_provider_script(monkeypatch):
    monkeypatch.setattr(market, "_read", lambda *args: r'v_hint="sh~600519~\u8d35\u5dde\u8305\u53f0~gzmt~GP-A^hk~00700~Tencent~tx~GP-H^sh~600519~duplicate~gzmt~GP-A";')
    assert market.search_stocks("maotai") == [{"symbol": "sh600519", "ticker": "600519", "name": "贵州茅台", "market": "上交所"}]


def test_market_route_rejects_invalid_scope_and_exposes_typed_read_only_data(monkeypatch):
    app = FastAPI(); app.include_router(router, prefix="/api")
    client = TestClient(app)
    calls = []
    monkeypatch.setattr(market, "_read", lambda url, *args: calls.append(url) or (quote_wire() if "qt.gtimg" in url else candles_wire()))
    assert client.get("/api/financial-market/stocks/sh000001").status_code == 422
    assert client.get("/api/financial-market/stocks/sh600519?period=minute").status_code == 422
    assert client.get("/api/financial-market/search", params={"query": "https://example.com"}).status_code == 422
    assert calls == []
    response = client.get("/api/financial-market/stocks/sh600519")
    assert response.status_code == 200 and response.json()["candles"][0]["volumeLots"] == 38331
    assert all(set(operations) == {"get"} for path, operations in app.openapi()["paths"].items() if "financial-market" in path)
    monkeypatch.setattr(market, "get_stock_snapshot", lambda *args: (_ for _ in ()).throw(market.MarketDataError("offline")))
    assert client.get("/api/financial-market/stocks/sh600519").json() == {"detail": "offline"}
