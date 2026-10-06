"""Market provenance, OHLC/units, bounded identifiers and API failure semantics."""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.web.routes.financial_assistant import router
from core.web.routes.financial_research import MarketQuoteResponse
from core.web.services import financial_market_service as market


def quote_wire():
    fields = [""] * 50
    for index, value in {1: "贵州茅台", 2: "600519", 3: "1258.62", 4: "1235.58", 5: "1239.53", 6: "38331", 30: "20260930161458", 31: "23.04", 32: "1.86", 33: "1268", 34: "1236.05", 37: "479725", 39: "19.32", 45: "15733.78", 46: "6.26"}.items():
        fields[index] = value
    return 'v_sh600519="' + "~".join(fields) + '";'


def market_quote_wire(symbol, values):
    fields = [""] * 50
    for index, value in values.items():
        fields[index] = value
    return f'v_{symbol}="' + "~".join(fields) + '";'


def hk_quote_wire():
    return market_quote_wire(
        "hk00700",
        {
            1: "腾讯控股", 2: "00700", 3: "427.400", 4: "423.000",
            5: "426.400", 6: "5754171", 30: "2026/10/06 13:39:52",
            31: "4.400", 32: "1.04", 33: "429.200", 34: "425.600",
            37: "2456211762.980", 39: "15.61", 45: "38861.7963",
            46: "TENCENT",
        },
    )


def us_quote_wire():
    return market_quote_wire(
        "usAAPL",
        {
            1: "苹果", 2: "AAPL.OQ", 3: "332.89", 4: "333.69",
            5: "332.82", 6: "34400850", 30: "2026-10-05 16:00:02",
            31: "-0.80", 32: "-0.24", 33: "336.21", 34: "331.65",
            35: "USD", 37: "11469849196", 39: "38.18",
            45: "48582.56580", 46: "Apple Inc.",
        },
    )


def candles_wire(rows=None, symbol="sh600519", key="qfqday"):
    if rows is None:
        rows = [["2026-09-30", "1239.53", "1258.62", "1268", "1236.05", "38331"]]
    return json.dumps({"code": 0, "data": {symbol: {key: rows}}})


@pytest.fixture(autouse=True)
def clear_cache():
    market._CACHE.clear()
    yield
    market._CACHE.clear()


def test_quote_preserves_exchange_time_and_explicit_units():
    row = market.parse_quote(quote_wire(), "sh600519")
    assert row["timestamp"] == "2026-09-30T16:14:58+08:00"
    assert row["marketCode"] == "CN" and row["currency"] == "CNY"
    assert row["priceUnit"] == "CNY/share" and row["volume"] == 3_833_100
    assert row["volumeUnit"] == "shares" and row["marketTimeZone"] == "Asia/Shanghai"
    assert row["volumeLots"] == 38331
    assert row["turnoverYuan"] == 4_797_250_000
    assert row["turnover"] == row["turnoverYuan"]
    assert row["marketCap"] == row["totalMarketCapYuan"]
    assert row["totalMarketCapYuan"] == 1_573_378_000_000
    assert row["peRatio"] == 19.32 and row["pbRatio"] == 6.26


@pytest.mark.parametrize("value", ["../../secret", "https://example.com", "sh600519?url=foo", "sz600519", "sh000001", "sh600519,sz000001", "123456"])
def test_identifiers_cannot_change_provider_url(value):
    with pytest.raises(market.MarketDataError):
        market.normalize_symbol(value)


def test_candles_are_ordered_and_keep_provider_ohlc_and_lots():
    assert market.parse_candles(candles_wire(), "sh600519", "day") == [{"date": "2026-09-30", "open": 1239.53, "close": 1258.62, "high": 1268, "low": 1236.05, "volume": 3_833_100, "volumeUnit": "shares", "volumeLots": 38331}]
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
    assert market.search_stocks("maotai") == [{"symbol": "sh600519", "ticker": "600519", "name": "贵州茅台", "market": "上交所", "marketCode": "CN", "currency": "CNY", "marketTimeZone": "Asia/Shanghai"}]


def test_market_symbols_keep_canonical_prefixes_and_a_share_guard():
    assert market.normalize_symbol("600519") == "sh600519"
    assert market.normalize_symbol("hk700") == "hk00700"
    assert market.normalize_symbol("usAAPL") == "usAAPL"
    assert market.normalize_symbol("usBRK.B") == "usBRK.B"
    assert market.normalize_symbol("usAAPL.OQ") == "usAAPL"
    assert market.normalize_a_share_symbol("600519") == "sh600519"
    for symbol in ("hk00700", "usAAPL", "AAPL"):
        with pytest.raises(market.MarketDataError):
            market.normalize_a_share_symbol(symbol)


@pytest.mark.parametrize(
    ("symbol", "wire", "market_code", "currency", "unit", "volume", "turnover", "timezone"),
    [
        ("hk00700", hk_quote_wire, "HK", "HKD", "HKD/share", 5_754_171, 2_456_211_762.98, "Asia/Hong_Kong"),
        ("usAAPL", us_quote_wire, "US", "USD", "USD/share", 34_400_850, 11_469_849_196, "America/New_York"),
    ],
)
def test_hk_and_us_quote_units_are_native_and_legacy_yuan_fields_are_null(
    symbol, wire, market_code, currency, unit, volume, turnover, timezone
):
    row = market.parse_quote(wire(), symbol)
    assert row["marketCode"] == market_code and row["currency"] == currency
    assert row["priceUnit"] == unit and row["volume"] == volume
    assert row["volumeUnit"] == "shares" and row["turnover"] == turnover
    assert row["marketTimeZone"] == timezone
    assert row["volumeLots"] is None and row["turnoverYuan"] is None
    assert row["totalMarketCapYuan"] is None and row["marketCap"] is not None
    assert row["pbRatio"] is None
    assert row["timestamp"].endswith("+08:00" if market_code == "HK" else "-04:00")
    response_quote = MarketQuoteResponse.model_validate(row)
    assert response_quote.marketCode == market_code
    assert response_quote.turnoverYuan is None and response_quote.volumeLots is None


def test_us_quote_rejects_unverified_currency_and_dst_ambiguous_time():
    raw = us_quote_wire().replace("USD", "HKD")
    with pytest.raises(market.MarketDataError):
        market.parse_quote(raw, "usAAPL")
    raw = us_quote_wire().replace("2026-10-05 16:00:02", "2026-11-01 01:30:00")
    with pytest.raises(market.MarketDataError):
        market.parse_quote(raw, "usAAPL")


@pytest.mark.parametrize("period", ["day", "week", "month"])
@pytest.mark.parametrize(("symbol", "wire", "market_code", "volume"), [
    ("hk00700", hk_quote_wire, "HK", 5_754_171),
    ("usAAPL", us_quote_wire, "US", 34_400_850),
])
def test_hk_us_period_candles_are_raw_and_use_share_volume(period, symbol, wire, market_code, volume):
    del wire, market_code
    row = ["2026-10-05", "100", "101", "102", "99", str(volume)]
    candles = market.parse_candles(candles_wire([row], symbol, period), symbol, period)
    assert candles == [{"date": "2026-10-05", "open": 100, "close": 101, "high": 102, "low": 99, "volume": volume, "volumeUnit": "shares", "volumeLots": None}]
    assert market.adjustment_for_market("HK" if symbol.startswith("hk") else "US") == "raw"


def test_search_filters_provider_results_by_selected_market(monkeypatch):
    wire = r'v_hint="sh~600519~贵州茅台~gzmt~GP-A^hk~00700~腾讯控股~txkg~GP^us~aapl.oq~苹果~pg~GP";'
    monkeypatch.setattr(market, "_read", lambda *args: wire)
    assert [item["symbol"] for item in market.search_stocks("腾讯", "HK")] == ["hk00700"]
    assert [item["symbol"] for item in market.search_stocks("Apple", "US")] == ["usAAPL"]
    assert [item["symbol"] for item in market.search_stocks("stock", "CN")] == ["sh600519"]


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
    assert response.json()["adjustment"] == "qfq"
    assert client.get("/api/financial-market/search", params={"query": "AAPL", "market": "OTHER"}).status_code == 422
    assert client.get("/api/financial-market/search", params={"query": "AAPL", "market": "US"}).status_code == 200
    def read_hk(url, *args):
        if "smartbox" in url:
            return 'v_hint="hk~00700~腾讯控股~txkg~GP";'
        if "qt.gtimg" in url:
            return hk_quote_wire()
        return candles_wire(
            [["2026-10-06", "426.4", "427.4", "429.2", "425.6", "5754171"]],
            "hk00700",
            "day",
        )

    monkeypatch.setattr(market, "_read", read_hk)
    hk_search = client.get(
        "/api/financial-market/search", params={"query": "腾讯", "market": "HK"}
    )
    assert hk_search.status_code == 200
    assert hk_search.json()[0]["marketCode"] == "HK"
    assert hk_search.json()[0]["currency"] == "HKD"
    hk_snapshot = client.get("/api/financial-market/stocks/hk00700")
    assert hk_snapshot.status_code == 200
    assert hk_snapshot.json()["stock"]["volumeLots"] is None
    assert hk_snapshot.json()["stock"]["turnoverYuan"] is None
    assert hk_snapshot.json()["stock"]["volumeUnit"] == "shares"
    assert hk_snapshot.json()["adjustment"] == "raw"
    assert all(set(operations) == {"get"} for path, operations in app.openapi()["paths"].items() if "financial-market" in path)
    monkeypatch.setattr(market, "get_stock_snapshot", lambda *args: (_ for _ in ()).throw(market.MarketDataError("offline")))
    assert client.get("/api/financial-market/stocks/sh600519").json() == {"detail": "offline"}
