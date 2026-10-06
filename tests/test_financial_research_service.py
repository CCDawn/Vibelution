"""Bounded public market screening and source-dated stock research contracts."""

import json
import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.web.routes.financial_research import router
from core.web.services import financial_research_service as research


@pytest.fixture(autouse=True)
def clear_screen_cache():
    research._SCREEN_CACHE = None
    yield
    research._SCREEN_CACHE = None


def sina_row(code: str = "600519", **overrides):
    return {
        "symbol": f"sh{code}",
        "code": code,
        "name": "测试股票",
        "trade": "10.25",
        "pricechange": "0.25",
        "changepercent": "2.5",
        "volume": "10000",
        "amount": "1025000",
        "open": "10.0",
        "high": "10.3",
        "low": "9.9",
        "settlement": "10.0",
        "per": "12.3",
        "pb": "1.4",
        "mktcap": "987654321",
        "ticktime": "14:55:00",
        **overrides,
    }


def test_sina_screen_keeps_unknown_market_cap_unit_null():
    row = research._screen_identity(sina_row())
    assert row["volumeLots"] == 100
    assert row["turnoverYuan"] == 1_025_000
    assert row["totalMarketCapYuan"] is None
    assert row["timeOfDay"] == "14:55:00"


def test_sina_screen_maps_beijing_codes_in_the_hs_a_pool():
    row = research._screen_identity(sina_row("920000", symbol="bj920000"))
    assert row["symbol"] == "bj920000"
    assert row["market"] == "北交所"


def test_partial_screen_reports_loaded_subset_and_filters_only_known_values(
    monkeypatch,
):
    monkeypatch.setattr(
        research,
        "_read_sina",
        lambda url: json.dumps("81") if "StockCount" in url else "[]",
    )

    def page_rows(page):
        if page == 2:
            raise research.FinancialResearchDataError("page offline")
        return [
            sina_row(f"{600001 + index:06d}", name=f"股票{index}", per=str(index + 1))
            for index in range(80)
        ]

    monkeypatch.setattr(research, "_sina_screen_page", page_rows)
    snapshot = research._load_screen_universe()
    assert snapshot["coverage"] == {
        "providerTotal": 81,
        "loaded": 80,
        "complete": False,
        "failedPages": [2],
        "invalidRows": 0,
        "duplicateRows": 0,
    }

    monkeypatch.setattr(research, "_screen_universe", lambda: snapshot)
    result = research.screen_stocks(min_pe=10, sort_by="changePercent", page_size=5)
    assert result["resultScope"] == "loaded_subset"
    assert result["coverage"]["totalFiltered"] == 71
    assert len(result["items"]) == 5
    assert all(item["peRatio"] >= 10 for item in result["items"])
    assert result["dataDate"] is None and result["dataTime"] == "14:55:00"


def test_complete_screen_reports_provider_universe_scope(monkeypatch):
    stock = research._screen_identity(sina_row())
    monkeypatch.setattr(
        research,
        "_screen_universe",
        lambda: {
            "stocks": [stock],
            "coverage": {
                "providerTotal": 1,
                "loaded": 1,
                "complete": True,
                "failedPages": [],
                "invalidRows": 0,
                "duplicateRows": 0,
            },
            "dataDate": None,
            "dataTime": "14:55:00",
            "cacheKey": "sina:hs_a:14:55:00",
            "cacheSeconds": research.SCREEN_CACHE_SECONDS,
            "fetchedAt": "2026-10-05T01:00:00+00:00",
        },
    )

    result = research.screen_stocks()

    assert result["resultScope"] == "provider_universe"


def test_pb_and_turnover_screen_excludes_unknowns_and_keeps_missing_sort_values_last(monkeypatch):
    stocks = [research._screen_identity(sina_row(f"60000{index}", pb=pb, amount=amount)) for index, (pb, amount) in enumerate([("2", "500000"), ("1", "2000000"), ("", "3000000")], start=1)]
    stocks[2].pop("pbRatio")
    monkeypatch.setattr(research, "_screen_universe", lambda: {
        "stocks": stocks, "coverage": {"complete": True, "loaded": 3, "providerTotal": 3},
        "fetchedAt": "2026-10-06T00:00:00Z", "dataDate": None, "dataTime": None,
        "cacheKey": "test", "cacheSeconds": 60,
    })
    for direction, expected in [("asc", ["600002", "600001", "600003"]), ("desc", ["600001", "600002", "600003"])]:
        assert [row["ticker"] for row in research.screen_stocks(sort_by="pbRatio", direction=direction)["items"]] == expected
    result = research.screen_stocks(min_pb=0.5, max_pb=1.5, min_turnover_yuan=1_000_000, max_turnover_yuan=2_500_000)
    assert [row["ticker"] for row in result["items"]] == ["600002"]


@pytest.mark.parametrize("bounds", [
    {"min_pb": 2, "max_pb": 1}, {"min_pb": float("nan")},
    {"max_turnover_yuan": float("inf")}, {"min_turnover_yuan": -1},
    {"min_turnover_yuan": 2, "max_turnover_yuan": 1},
])
def test_advanced_screen_rejects_invalid_bounds_before_reading_provider(monkeypatch, bounds):
    def unavailable():
        pytest.fail("Invalid conditions must not load the public stock pool")
    monkeypatch.setattr(research, "_screen_universe", unavailable)
    with pytest.raises(research.FinancialResearchInputError):
        research.screen_stocks(**bounds)


def test_screen_loader_deadline_bounds_slow_pages_and_reports_every_missing_page(
    monkeypatch,
):
    monkeypatch.setattr(research, "SCREEN_PAGE_SIZE", 1)
    monkeypatch.setattr(research, "SCREEN_UNIVERSE_DEADLINE_SECONDS", 0.05)
    monkeypatch.setattr(research, "_read_sina", lambda _url: "10")
    release_pages = threading.Event()
    started_any_page = threading.Event()
    started_pages: list[int] = []
    started_lock = threading.Lock()

    class DeadlineClock:
        now = 0.0

        def monotonic(self):
            return self.now

    deadline_clock = DeadlineClock()
    shutdown_calls = []
    real_executor = research.ThreadPoolExecutor

    class TrackingExecutor(real_executor):
        def shutdown(self, wait=True, *, cancel_futures=False):
            shutdown_calls.append((wait, cancel_futures))
            super().shutdown(wait=wait, cancel_futures=cancel_futures)

    def slow_page(page: int):
        with started_lock:
            started_pages.append(page)
            started_any_page.set()
        release_pages.wait(timeout=0.5)
        return [sina_row(f"{600000 + page:06d}")]

    def advance_to_deadline(futures, timeout=None, return_when=None):
        assert started_any_page.wait(timeout=0.5)
        deadline_clock.now = research.SCREEN_UNIVERSE_DEADLINE_SECONDS
        return set(), set(futures)

    monkeypatch.setattr(research, "time", deadline_clock)
    monkeypatch.setattr(research, "ThreadPoolExecutor", TrackingExecutor)
    monkeypatch.setattr(research, "wait", advance_to_deadline)
    monkeypatch.setattr(research, "_sina_screen_page", slow_page)
    started_at = time.monotonic()
    snapshot = research._load_screen_universe()
    elapsed = time.monotonic() - started_at
    release_pages.set()

    assert elapsed < 0.5, (elapsed, started_pages, snapshot["coverage"])
    assert 0 < len(started_pages) <= 3
    assert shutdown_calls == [(False, True)]
    assert snapshot["coverage"]["loaded"] == 0
    assert snapshot["coverage"]["complete"] is False
    assert snapshot["coverage"]["failedPages"] == list(range(1, 11))


def test_screen_loader_deadline_includes_provider_count_request(monkeypatch):
    monkeypatch.setattr(research, "SCREEN_PAGE_SIZE", 1)
    monkeypatch.setattr(research, "SCREEN_UNIVERSE_DEADLINE_SECONDS", 0.02)
    page_calls = []

    def slow_count(_url: str) -> str:
        time.sleep(0.04)
        return "3"

    monkeypatch.setattr(research, "_read_sina", slow_count)
    monkeypatch.setattr(
        research,
        "_sina_screen_page",
        lambda page: page_calls.append(page) or [sina_row(f"{600000 + page:06d}")],
    )

    snapshot = research._load_screen_universe()

    assert page_calls == []
    assert snapshot["coverage"]["loaded"] == 0
    assert snapshot["coverage"]["failedPages"] == [1, 2, 3]


def quote_wire():
    fields = [""] * 50
    values = {
        1: "贵州茅台",
        2: "600519",
        3: "1258.62",
        4: "1235.58",
        5: "1239.53",
        6: "38331",
        30: "20260930161458",
        31: "23.04",
        32: "1.86",
        33: "1268",
        34: "1236.05",
        37: "479725",
        39: "19.32",
        45: "15733.78",
        46: "6.26",
    }
    for index, value in values.items():
        fields[index] = value
    return 'v_sh600519="' + "~".join(fields) + '";'


def test_batch_quotes_reuses_existing_quote_parser_and_keeps_per_symbol_errors(
    monkeypatch,
):
    monkeypatch.setattr(research.market, "_cached", lambda key, ttl, loader: loader())
    monkeypatch.setattr(research.market, "_read", lambda *args: quote_wire())
    result = research.batch_quotes(["sh600519", "not-a-stock"])
    assert result["source"] == "腾讯财经"
    assert result["items"][0]["quote"]["totalMarketCapYuan"] == 1_573_378_000_000
    assert result["items"][1]["quote"] is None
    assert result["items"][1]["error"]


def test_batch_quotes_preserves_source_fetch_time_on_cache_hit(monkeypatch):
    entries = {}
    read_calls = []

    def cached(key, _ttl, loader):
        if key not in entries:
            entries[key] = loader()
        return entries[key]

    monkeypatch.setattr(
        research.market,
        "_cached",
        cached,
    )
    monkeypatch.setattr(
        research.market, "_read", lambda *args: read_calls.append(args) or quote_wire()
    )
    monkeypatch.setattr(research, "_utc_now", lambda: "2026-10-05T01:00:00+00:00")

    first = research.batch_quotes(["sh600519"])
    monkeypatch.setattr(research, "_utc_now", lambda: "2026-10-05T01:00:30+00:00")
    second = research.batch_quotes(["sh600519"])

    assert len(read_calls) == 1
    assert first["fetchedAt"] == "2026-10-05T01:00:00+00:00"
    assert second["fetchedAt"] == first["fetchedAt"]


def test_eastmoney_jsonp_news_accepts_callback_without_semicolon(monkeypatch):
    monkeypatch.setattr(
        research.market, "_read", lambda *args: 'callback({"result":{"count":1}})'
    )
    assert research._read_json("https://example.com/fixed-provider-url") == {
        "result": {"count": 1}
    }


def test_stock_research_keeps_each_source_status_and_missing_values(monkeypatch):
    stock = {
        "symbol": "sh600519",
        "ticker": "600519",
        "name": "贵州茅台",
        "market": "上交所",
    }
    monkeypatch.setattr(research, "_eastmoney_stock", lambda symbol: stock)
    monkeypatch.setattr(research.market, "_cached", lambda key, ttl, loader: loader())
    monkeypatch.setattr(
        research,
        "_load_news",
        lambda row: {
            "status": "available",
            "source": "东方财富",
            "sourceUrl": "https://example.com/news",
            "fetchedAt": "2026-10-05T01:00:00+00:00",
            "error": None,
            "items": [],
        },
    )
    monkeypatch.setattr(
        research,
        "_load_announcements",
        lambda row: (_ for _ in ()).throw(
            research.FinancialResearchDataError("公告源暂不可用")
        ),
    )
    monkeypatch.setattr(
        research,
        "_load_fundamentals",
        lambda row: {
            "status": "available",
            "source": "东方财富",
            "sourceUrl": "https://example.com/fundamentals",
            "fetchedAt": "2026-10-05T01:00:00+00:00",
            "reportDate": None,
            "publishedAt": None,
            "error": None,
            "items": [
                {
                    "key": "EPSJB",
                    "label": "每股收益",
                    "value": None,
                    "unit": "元/股",
                    "reportDate": None,
                    "publishedAt": None,
                }
            ],
        },
    )

    result = research.stock_research("sh600519")
    assert result["news"]["status"] == "available"
    assert result["announcements"]["status"] == "unavailable"
    assert result["fundamentals"]["items"][0]["value"] is None
    assert result["fundamentals"]["reportDate"] is None


def test_screen_and_quote_routes_are_read_only_typed_and_reject_invalid_ranges(
    monkeypatch,
):
    app = FastAPI()
    app.include_router(router, prefix="/api")
    client = TestClient(app)
    calls = []
    screen = {
        "source": research.SINA_SOURCE,
        "sourceUrl": research.SINA_SCREEN_URL,
        "fetchedAt": "2026-10-05T01:00:00+00:00",
        "dataDate": None,
        "dataTime": "14:55:00",
        "cacheKey": "sina:test",
        "cacheSeconds": 600,
        "coverage": {
            "providerTotal": 1,
            "loaded": 1,
            "complete": True,
            "failedPages": [],
            "invalidRows": 0,
            "duplicateRows": 0,
            "totalFiltered": 1,
        },
        "resultScope": "provider_universe",
        "sortBy": "changePercent",
        "direction": "desc",
        "page": 1,
        "pageSize": 50,
        "items": [research._screen_identity(sina_row())],
        "notice": "日期未提供",
    }
    assert (
        client.get("/api/financial-market/screen?minPrice=12&maxPrice=10").status_code
        == 422
    )
    monkeypatch.setattr(
        research, "screen_stocks", lambda **kwargs: calls.append(kwargs) or screen
    )
    response = client.get(
        "/api/financial-market/screen?minPrice=10&sortBy=changePercent"
    )
    assert response.status_code == 200
    assert response.json()["items"][0]["totalMarketCapYuan"] is None
    assert response.json()["resultScope"] == "provider_universe"
    response_schema = app.openapi()["components"]["schemas"]["MarketScreenResponse"]
    assert response_schema["properties"]["resultScope"]["enum"] == [
        "provider_universe",
        "loaded_subset",
    ]
    assert calls[-1]["min_price"] == 10
    assert all(
        set(methods) == {"get"}
        for path, methods in app.openapi()["paths"].items()
        if "financial-market" in path
    )


@pytest.mark.parametrize("symbol,ticker,market_name", [("hk00700", "00700", "港交所"), ("usNVDA", "NVDA", "NASDAQ")])
def test_international_research_facade_uses_disclosure_adapter_without_hiding_facet_failures(monkeypatch, symbol, ticker, market_name):
    from core.web.services import financial_research as international

    stock = {"symbol": symbol, "ticker": ticker, "name": "研究股票", "market": market_name}
    news = {"status": "available", "source": "新闻源", "sourceUrl": "https://example.com/news", "fetchedAt": "2026-10-06T00:00:00Z", "items": [], "error": None}
    announcements = {**news, "status": "unavailable", "source": "官方披露源", "error": "源暂时不可达"}
    fundamentals = {**news, "source": "财务源", "reportDate": "2026-06-30", "publishedAt": "2026-08-01", "items": [{"key": "revenue", "label": "营业收入", "value": 123, "unit": "USD", "reportDate": "2026-06-30", "publishedAt": "2026-08-01"}]}
    called = []
    monkeypatch.setattr(research, "_eastmoney_stock", lambda value: stock)
    monkeypatch.setattr(research, "_load_news", lambda value: news)
    monkeypatch.setattr(research.market, "_cached", lambda key, ttl, reader: reader())
    monkeypatch.setattr(international, "fetch_international_facets", lambda value: called.append(value) or {"announcements": announcements, "fundamentals": fundamentals})
    result = research.stock_research(symbol)
    assert called == [stock]
    assert result["news"] == news
    assert result["announcements"] == announcements
    assert result["fundamentals"] == fundamentals


def test_research_route_preserves_independent_facets(monkeypatch):
    app = FastAPI()
    app.include_router(router, prefix="/api")
    result = {
        "stock": {
            "symbol": "sh600519",
            "ticker": "600519",
            "name": "贵州茅台",
            "market": "上交所",
        },
        "news": {
            "status": "available",
            "source": "东方财富",
            "sourceUrl": "https://data.eastmoney.com/news/",
            "fetchedAt": "2026-10-05T01:00:00+00:00",
            "error": None,
            "items": [],
        },
        "announcements": {
            "status": "unavailable",
            "source": "东方财富",
            "sourceUrl": "https://data.eastmoney.com/notices/",
            "fetchedAt": "2026-10-05T01:00:00+00:00",
            "error": "公告源暂不可用",
            "items": [],
        },
        "fundamentals": {
            "status": "available",
            "source": "东方财富",
            "sourceUrl": "https://data.eastmoney.com/bbsj/",
            "fetchedAt": "2026-10-05T01:00:00+00:00",
            "reportDate": None,
            "publishedAt": None,
            "error": None,
            "items": [],
        },
    }
    monkeypatch.setattr(research, "stock_research", lambda symbol: result)
    response = TestClient(app).get("/api/financial-market/stocks/sh600519/research")
    assert response.status_code == 200
    assert response.json()["announcements"]["status"] == "unavailable"
    assert response.json()["fundamentals"]["reportDate"] is None
