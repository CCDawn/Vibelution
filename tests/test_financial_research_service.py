"""Bounded public market screening and source-dated stock research contracts."""

import json
import threading
import time
from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.web.routes.financial_research import router
from core.web.services import financial_research_service as research
from core.web.services.financial_research.as_of import (
    published_items_as_of,
    research_analysis_date_context,
)


@pytest.fixture(autouse=True)
def clear_screen_cache():
    research._SCREEN_CACHE = None
    yield
    research._SCREEN_CACHE = None


@pytest.mark.parametrize("complete", [True, False])
def test_partial_universe_refreshes_without_holding_missing_pages_for_ten_minutes(monkeypatch, complete):
    clock, loads = [0.0], []
    monkeypatch.setattr(research.time, "monotonic", lambda: clock[0])

    def load():
        loads.append(clock[0])
        return {"coverage": {"complete": complete}, "fetchedAt": str(len(loads))}

    monkeypatch.setattr(research, "_load_screen_universe", load)
    first = research._screen_universe()
    assert first["cacheSeconds"] == (600 if complete else 60)
    clock[0] = 1.0
    assert research._screen_universe()["fetchedAt"] == "1"
    clock[0] = 61.0
    refreshed = research._screen_universe()
    assert len(loads) == (1 if complete else 2)
    assert refreshed["coverage"]["complete"] is complete
    if complete:
        clock[0] = 601.0
        assert research._screen_universe()["fetchedAt"] == "2"


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
        lambda row, *, cutoff=None: {
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
        lambda row, *, cutoff=None: (_ for _ in ()).throw(
            research.FinancialResearchDataError("公告源暂不可用")
        ),
    )
    monkeypatch.setattr(
        research,
        "_load_fundamentals",
        lambda row, *, cutoff=None: {
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


def _notice_row(title: str, code: str, notice_date: str = "2026-04-17") -> dict:
    return {
        "art_code": code,
        "title_ch": title,
        "notice_date": notice_date,
        "display_time": f"{notice_date} 08:00:00",
        "codes": [{"stock_code": "600519"}],
    }


def _maotai_filing() -> dict[str, str]:
    return {
        "title": "贵州茅台2025年年度报告",
        "url": "https://static.cninfo.com.cn/finalpage/2026-04-17/1225114741.PDF",
        "announcedOn": "2026-04-17",
        "source": "巨潮资讯",
    }


def _announcement_stock() -> dict[str, str]:
    return {
        "symbol": "sh600519",
        "ticker": "600519",
        "name": "贵州茅台",
        "market": "上交所",
    }


def _periodic_filing(kind: str, title: str, day: str, adjunct: str) -> dict[str, str]:
    return {
        "kind": kind,
        "title": title,
        "url": f"https://static.cninfo.com.cn/finalpage/{day}/{adjunct}.PDF",
        "announcedOn": day,
        "source": "巨潮资讯",
    }


def _all_periodic_filings() -> dict[str, list[dict[str, str]]]:
    return {
        "600519": [
            {**_maotai_filing(), "kind": "annual"},
            _periodic_filing("semiannual", "贵州茅台2026年半年度报告", "2026-08-15", "1225475868"),
            _periodic_filing("q1", "贵州茅台2026年一季度报告", "2026-04-25", "1225188741"),
            _periodic_filing("q3", "贵州茅台2025年第三季度报告", "2025-10-30", "1224764517"),
        ]
    }


def _notice_payload() -> dict:
    return {
        "data": {
            "list": [
                _notice_row("贵州茅台2025年年度报告摘要", "AN202604170011"),
                _notice_row("贵州茅台2025年年度报告", "AN202604170012"),
                _notice_row("贵州茅台2026年半年度报告", "AN202608150014", "2026-08-15"),
                _notice_row("贵州茅台2026年一季度报告", "AN202604250015", "2026-04-25"),
                _notice_row("贵州茅台2025年第三季度报告摘要", "AN202510300016", "2025-10-30"),
                _notice_row("关于召开股东大会的通知", "AN202605010013", "2026-05-01"),
            ]
        }
    }


def test_stock_announcements_prefer_cninfo_periodic_reports(monkeypatch):
    calls = []

    def lookup(codes, cutoff=None):
        calls.append((list(codes), cutoff))
        return _all_periodic_filings()

    monkeypatch.setattr(research, "_read_json", lambda url: _notice_payload())
    monkeypatch.setattr(research, "_utc_now", lambda: "2026-10-07T00:00:00+00:00")
    monkeypatch.setattr(research, "lookup_periodic_filings", lookup)

    result = research._load_announcements(_announcement_stock())

    assert calls == [(["600519"], None)]
    assert result["status"] == "available"
    assert result["source"] == "巨潮资讯"
    assert result["sourceUrl"] == "https://www.cninfo.com.cn/"
    assert result["error"] is None
    assert [item["title"] for item in result["items"]] == [
        "贵州茅台2026年半年度报告",
        "贵州茅台2026年一季度报告",
        "贵州茅台2025年年度报告",
        "贵州茅台2025年第三季度报告",
        "关于召开股东大会的通知",
    ]
    by_title = {item["title"]: item for item in result["items"]}
    annual = by_title["贵州茅台2025年年度报告"]
    assert annual["url"] == _maotai_filing()["url"]
    assert annual["articleCode"] == "cninfo-2026-04-17"
    assert annual["publisher"] == "巨潮资讯"
    assert by_title["贵州茅台2026年半年度报告"]["articleCode"] == "cninfo-semiannual-2026-08-15"
    assert by_title["贵州茅台2026年一季度报告"]["articleCode"] == "cninfo-q1-2026-04-25"
    assert by_title["贵州茅台2025年第三季度报告"]["articleCode"] == "cninfo-q3-2025-10-30"
    assert all("eastmoney.com" not in item["url"] for item in result["items"][:4])
    kept = result["items"][-1]
    assert kept["publisher"] == "东方财富"
    assert kept["url"].startswith(
        "https://data.eastmoney.com/notices/detail/600519/AN202605010013"
    )


def test_stock_announcements_omit_periodic_reprints_without_a_cninfo_original(
    monkeypatch,
):
    monkeypatch.setattr(research, "_read_json", lambda url: _notice_payload())
    monkeypatch.setattr(research, "lookup_periodic_filings", lambda codes, cutoff=None: {})

    result = research._load_announcements(_announcement_stock())

    assert result["source"] == "东方财富"
    assert result["sourceUrl"] == "https://data.eastmoney.com/notices/"
    assert result["error"] == "没有核到巨潮资讯年报、半年报、一季报、三季报原文，未列出对应转载。"
    assert [item["title"] for item in result["items"]] == ["关于召开股东大会的通知"]
    assert result["items"][0]["publisher"] == "东方财富"


def test_stock_announcements_name_only_the_missing_periodic_reports(monkeypatch):
    found = _all_periodic_filings()
    found["600519"] = [
        row for row in found["600519"] if row["kind"] in {"annual", "semiannual"}
    ]
    monkeypatch.setattr(research, "_read_json", lambda url: _notice_payload())
    monkeypatch.setattr(research, "lookup_periodic_filings", lambda codes, cutoff=None: found)

    result = research._load_announcements(_announcement_stock())

    assert result["error"] == "没有核到巨潮资讯一季报、三季报原文，未列出对应转载。"
    assert [item["title"] for item in result["items"]] == [
        "贵州茅台2026年半年度报告",
        "贵州茅台2025年年度报告",
        "关于召开股东大会的通知",
    ]


def test_stock_announcements_reject_an_untrusted_periodic_report_url(monkeypatch):
    filing = {**_maotai_filing(), "kind": "annual", "url": "https://evil.example/annual.pdf"}
    monkeypatch.setattr(research, "_read_json", lambda url: _notice_payload())
    monkeypatch.setattr(
        research,
        "lookup_periodic_filings",
        lambda codes, cutoff=None: {"600519": [filing]},
    )

    result = research._load_announcements(_announcement_stock())

    assert result["error"] == "没有核到巨潮资讯年报、半年报、一季报、三季报原文，未列出对应转载。"
    assert all("季度报告" not in item["title"] for item in result["items"])
    assert all("年度报告" not in item["title"] for item in result["items"])
    assert all("evil.example" not in item["url"] for item in result["items"])


def test_stock_announcements_keep_cninfo_reports_when_eastmoney_fails(monkeypatch):
    def boom(url):
        raise OSError("eastmoney down")

    monkeypatch.setattr(research, "_read_json", boom)
    monkeypatch.setattr(
        research,
        "lookup_periodic_filings",
        lambda codes, cutoff=None: _all_periodic_filings(),
    )

    result = research._load_announcements(_announcement_stock())

    assert [item["publisher"] for item in result["items"]] == ["巨潮资讯"] * 4
    assert result["source"] == "巨潮资讯"
    assert result["error"] == "其它公告暂时不可用。"


def test_stock_announcements_fail_when_both_notice_sources_fail(monkeypatch):
    def boom(url):
        raise OSError("eastmoney down")

    def explode(codes, cutoff=None):
        raise RuntimeError("cninfo down")

    monkeypatch.setattr(research, "_read_json", boom)
    monkeypatch.setattr(research, "lookup_periodic_filings", explode)

    with pytest.raises(research.FinancialResearchDataError, match="eastmoney down"):
        research._load_announcements(_announcement_stock())


@pytest.mark.parametrize(
    "dates",
    [
        (None, date(2026, 4, 17)),
        (date(2026, 4, 17), None),
    ],
)
def test_stock_research_captures_cutoff_before_parallel_loaders_and_partitions_cache(
    monkeypatch, dates
):
    stock = _announcement_stock()
    observed_cutoffs = []
    cache = {}
    cache_keys = []

    def cached(key, _ttl, loader):
        cache_keys.append(key)
        if key not in cache:
            cache[key] = loader()
        return cache[key]

    def reader(name):
        def load(_stock, *, cutoff=None):
            observed_cutoffs.append((name, cutoff))
            if name == "fundamentals" and cutoff is not None:
                raise research.FinancialResearchDataError(
                    "历史时点无法验证当前财务汇总"
                )
            return {
                "status": "available",
                "items": [
                    {
                        "title": cutoff.isoformat() if cutoff else "current",
                        "publishedAt": cutoff.isoformat() if cutoff else None,
                    }
                ],
            }

        return load

    monkeypatch.setattr(research, "_eastmoney_stock", lambda _symbol: stock)
    monkeypatch.setattr(research.market, "_cached", cached)
    monkeypatch.setattr(research, "_load_news", reader("news"))
    monkeypatch.setattr(research, "_load_announcements", reader("announcements"))
    monkeypatch.setattr(research, "_load_fundamentals", reader("fundamentals"))

    results = []
    for day in dates:
        prompt = f"分析日期：{day.isoformat()}" if day else ""
        with research_analysis_date_context(prompt):
            result = research.stock_research("sh600519")
        results.append(result)
        assert result["fundamentals"]["status"] == (
            "available" if day is None else "unavailable"
        )

    expected = [
        (name, day)
        for day in dates
        for name in ("news", "announcements", "fundamentals")
    ]
    assert len(observed_cutoffs) == len(expected)
    assert set(observed_cutoffs) == set(expected)
    assert len(cache_keys) == 6
    assert {key[-1] for key in cache_keys} == {"current", "2026-04-17"}
    assert [result["news"]["items"][0]["title"] for result in results] == [
        day.isoformat() if day else "current" for day in dates
    ]


def test_as_of_projection_does_not_mutate_a_shared_cached_result():
    cached_result = {
        "status": "available",
        "items": [
            {"title": "known", "publishedAt": "2026-04-17"},
            {"title": "future", "publishedAt": "2026-04-18"},
            {"title": "unknown", "publishedAt": None},
        ],
    }
    original_items = list(cached_result["items"])

    projected = published_items_as_of(cached_result, date(2026, 4, 17))

    assert [item["title"] for item in projected["items"]] == ["known"]
    assert projected is not cached_result
    assert projected["items"] is not cached_result["items"]
    assert cached_result["items"] == original_items


def test_stock_news_excludes_future_and_unknown_publication_dates(monkeypatch):
    monkeypatch.setattr(
        research,
        "_read_json",
        lambda _url: {
            "result": {
                "cmsArticleWebOld": [
                    {"title": "cutoff day", "date": "2026-04-17 09:00:00"},
                    {"title": "older", "date": "2026-04-16 09:00:00"},
                    {"title": "future", "date": "2026-04-18 09:00:00"},
                    {"title": "unknown", "date": ""},
                ]
            }
        },
    )

    result = research._load_news(_announcement_stock(), cutoff=date(2026, 4, 17))

    assert [item["title"] for item in result["items"]] == ["cutoff day", "older"]


def test_stock_news_pages_past_a_future_only_first_page(monkeypatch):
    page_indices = []

    def read_json(url):
        query = parse_qs(urlparse(url).query)
        params = json.loads(query["param"][0])["param"]["cmsArticleWebOld"]
        page_index = params["pageIndex"]
        page_indices.append(page_index)
        if page_index == 1:
            rows = [
                {"title": f"future-{index}", "date": "2026-04-18 09:00:00"}
                for index in range(research.RESEARCH_NEWS_PAGE_SIZE)
            ]
        else:
            rows = [
                {"title": "older page two", "date": "2026-04-16 09:00:00"},
                {"title": "cutoff page two", "date": "2026-04-17 09:00:00"},
            ]
        return {"result": {"cmsArticleWebOld": rows}}

    monkeypatch.setattr(research, "_read_json", read_json)

    result = research._load_news(_announcement_stock(), cutoff=date(2026, 4, 17))

    assert page_indices == [1, 2]
    assert [item["title"] for item in result["items"]] == [
        "cutoff page two",
        "older page two",
    ]
    assert result["error"] is None


def test_stock_news_marks_a_truncated_historical_search_incomplete(monkeypatch):
    monkeypatch.setattr(research, "RESEARCH_NEWS_PAGE_SIZE", 2)
    monkeypatch.setattr(research, "RESEARCH_HISTORICAL_MAX_PAGES", 2)
    requested_pages = []

    def read_json(url):
        query = parse_qs(urlparse(url).query)
        params = json.loads(query["param"][0])["param"]["cmsArticleWebOld"]
        requested_pages.append(params["pageIndex"])
        return {
            "result": {
                "cmsArticleWebOld": [
                    {"title": f"future-{index}", "date": "2026-04-18 09:00:00"}
                    for index in range(2)
                ]
            }
        }

    monkeypatch.setattr(research, "_read_json", read_json)

    result = research._load_news(_announcement_stock(), cutoff=date(2026, 4, 17))

    assert requested_pages == [1, 2]
    assert result["items"] == []
    assert "历史新闻覆盖不完整" in result["error"]


def test_stock_announcements_apply_cutoff_to_cninfo_and_eastmoney(monkeypatch):
    notice_payload = _notice_payload()
    notice_payload["data"]["list"].append(
        {
            **_notice_row("unknown date notice", "AN202604170017"),
            "display_time": "",
            "notice_date": "",
        }
    )
    calls = []

    def lookup(codes, cutoff=None):
        calls.append((list(codes), cutoff))
        return _all_periodic_filings()

    monkeypatch.setattr(research, "_read_json", lambda _url: notice_payload)
    monkeypatch.setattr(research, "lookup_periodic_filings", lookup)

    result = research._load_announcements(
        _announcement_stock(), cutoff=date(2026, 4, 20)
    )

    assert calls == [(["600519"], date(2026, 4, 20))]
    assert [item["title"] for item in result["items"]] == [
        "贵州茅台2025年年度报告",
        "贵州茅台2025年第三季度报告",
    ]


def test_stock_announcements_page_past_future_only_first_page(monkeypatch):
    page_indices = []
    monkeypatch.setattr(research, "_official_periodic_notices", lambda *_args, **_kwargs: [])

    def read_json(url):
        query = parse_qs(urlparse(url).query)
        page_index = int(query["page_index"][0])
        page_indices.append(page_index)
        if page_index == 1:
            rows = [
                _notice_row(f"future-{index}", f"AN2026041800{index:03d}", "2026-04-18")
                for index in range(research.EASTMONEY_NOTICE_PAGE_SIZE)
            ]
        else:
            rows = [
                _notice_row("older notice on page two", "AN202604160001", "2026-04-16")
            ]
        return {"data": {"list": rows}}

    monkeypatch.setattr(research, "_read_json", read_json)

    result = research._load_announcements(
        _announcement_stock(), cutoff=date(2026, 4, 17)
    )

    assert page_indices == [1, 2]
    assert [item["title"] for item in result["items"]] == [
        "older notice on page two"
    ]
    assert "历史公告覆盖不完整" not in (result["error"] or "")


def test_stock_announcements_disclose_historical_page_cap(monkeypatch):
    monkeypatch.setattr(research, "EASTMONEY_NOTICE_PAGE_SIZE", 2)
    monkeypatch.setattr(research, "RESEARCH_HISTORICAL_MAX_PAGES", 2)
    monkeypatch.setattr(research, "_official_periodic_notices", lambda *_args, **_kwargs: [])

    def read_json(_url):
        return {
            "data": {
                "list": [
                    _notice_row(f"future-{index}", f"AN2026041800{index:03d}", "2026-04-18")
                    for index in range(2)
                ]
            }
        }

    monkeypatch.setattr(research, "_read_json", read_json)

    result = research._load_announcements(
        _announcement_stock(), cutoff=date(2026, 4, 17)
    )

    assert result["items"] == []
    assert "历史公告覆盖不完整" in result["error"]


def test_stock_research_passes_historical_cutoff_into_cninfo_source_query(monkeypatch):
    calls = []

    def read_json(url):
        if "np-anotice-stock.eastmoney.com" in url:
            return _notice_payload()
        if "search-api-web.eastmoney.com" in url:
            return {"result": {"cmsArticleWebOld": []}}
        pytest.fail(f"Unexpected source request: {url}")

    def lookup(codes, cutoff=None):
        calls.append((list(codes), cutoff))
        return _all_periodic_filings()

    monkeypatch.setattr(
        research, "_eastmoney_stock", lambda _symbol: _announcement_stock()
    )
    monkeypatch.setattr(research, "_read_json", read_json)
    monkeypatch.setattr(research, "lookup_periodic_filings", lookup)
    monkeypatch.setattr(research.market, "_cached", lambda _key, _ttl, loader: loader())

    with research_analysis_date_context("分析日期：2026-04-20"):
        result = research.stock_research("sh600519")

    assert calls == [(["600519"], date(2026, 4, 20))]
    assert [item["title"] for item in result["announcements"]["items"]] == [
        "贵州茅台2025年年度报告",
        "贵州茅台2025年第三季度报告",
    ]
    assert result["fundamentals"]["status"] == "unavailable"


def test_historical_a_share_fundamentals_fail_closed_before_provider_read(monkeypatch):
    monkeypatch.setattr(
        research,
        "_read_json",
        lambda _url: pytest.fail("Historical research must not read latest summaries"),
    )

    with pytest.raises(research.FinancialResearchDataError, match="历史时点"):
        research._load_fundamentals(_announcement_stock(), cutoff=date(2026, 4, 17))


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
    monkeypatch.setattr(research, "_load_news", lambda value, *, cutoff=None: news)
    monkeypatch.setattr(research.market, "_cached", lambda key, ttl, reader: reader())
    monkeypatch.setattr(international, "fetch_international_facets", lambda value, *, cutoff=None: called.append((value, cutoff)) or {"announcements": announcements, "fundamentals": fundamentals})
    result = research.stock_research(symbol)
    assert called == [(stock, None)]
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


def test_announcement_publisher_is_optional(monkeypatch):
    app = FastAPI()
    app.include_router(router, prefix="/api")
    official = {
        "title": "贵州茅台2025年年度报告",
        "publishedAt": "2026-04-17",
        "noticeDate": "2026-04-17",
        "url": "https://static.cninfo.com.cn/finalpage/2026-04-17/1225114741.PDF",
        "articleCode": "cninfo-2026-04-17",
        "publisher": "巨潮资讯",
    }
    reprint = {
        "title": "关于召开股东大会的通知",
        "publishedAt": "2026-05-01",
        "noticeDate": "2026-05-01",
        "url": "https://data.eastmoney.com/notices/detail/600519/AN202605010013.html",
        "articleCode": "AN202605010013",
    }
    payload = {
        "stock": {
            "symbol": "sh600519",
            "ticker": "600519",
            "name": "贵州茅台",
            "market": "上交所",
        },
        "news": {
            "status": "available",
            "source": "东方财富",
            "sourceUrl": "https://so.eastmoney.com/news/",
            "fetchedAt": "2026-10-07T00:00:00+00:00",
            "error": None,
            "items": [],
        },
        "announcements": {
            "status": "available",
            "source": "巨潮资讯",
            "sourceUrl": "https://www.cninfo.com.cn/",
            "fetchedAt": "2026-10-07T00:00:00+00:00",
            "error": None,
            "items": [official, reprint],
        },
        "fundamentals": {
            "status": "available",
            "source": "东方财富",
            "sourceUrl": "https://data.eastmoney.com/bbsj/",
            "fetchedAt": "2026-10-07T00:00:00+00:00",
            "reportDate": None,
            "publishedAt": None,
            "error": None,
            "items": [],
        },
    }
    monkeypatch.setattr(research, "stock_research", lambda symbol: payload)
    response = TestClient(app).get("/api/financial-market/stocks/sh600519/research")
    assert response.status_code == 200
    items = response.json()["announcements"]["items"]
    assert items[0]["publisher"] == "巨潮资讯"
    assert items[1]["publisher"] is None
