import json
from datetime import date

from core.web.services.financial_research.as_of import (
    redact_research_history,
    redact_research_prompt,
    research_analysis_date_context,
)
from core.web.services.financial_team import runs
from tools import research_search_backends, research_search_tools
from tools.financial_market_tools import (
    financial_market_screen_tool,
    financial_market_snapshot_tool,
)


REQUEST = "请研究 贵州茅台（600519，上交所），分析日期 2024-12-31，使用 Markdown 二级标题整理研究报告。"
QUOTE = (
    "行情快照（腾讯财经，可能延迟）：2026-09-30T16:14:58+08:00，价格 1258.62 元，涨跌 1.86%。"
    "这是带时点的报价，不是已审核财报证据。"
)


def test_model_prompt_drops_a_quote_newer_than_the_analysis_date():
    text = f"{REQUEST}\n{QUOTE}"
    redacted = redact_research_prompt(text)
    assert isinstance(redacted, str)
    assert "1258.62" not in redacted
    assert "行情快照晚于分析日期 2024-12-31，未作为本次研究依据。" in redacted
    assert redact_research_prompt(text.replace("2026-09-30", "2024-12-31")) == text.replace(
        "2026-09-30", "2024-12-31"
    )


def test_follow_up_history_keeps_the_analysis_date_and_hides_the_late_quote():
    history = [
        {"role": "user", "content": f"{REQUEST}\n{QUOTE}"},
        {"role": "assistant", "content": "先看年报。"},
    ]
    redacted = redact_research_history(history)
    assert redacted is not history
    assert "1258.62" not in redacted[0]["content"]
    assert history[0]["content"].endswith("不是已审核财报证据。")
    with research_analysis_date_context("现金流如何？", history):
        from core.web.services.financial_research.as_of import active_cutoff

        assert active_cutoff() == date(2024, 12, 31)


def test_news_search_drops_items_after_the_analysis_date(monkeypatch):
    def collect(query, providers, max_results):
        assert "2024-12-31" in query
        assert "2026" not in query
        return {
            "query": query,
            "results": [
                {
                    "title": "当年披露",
                    "url": "https://news.example/old",
                    "snippet": "年报",
                    "provider": "google_news_rss",
                    "published": "Mon, 30 Dec 2024 00:00:00 GMT",
                },
                {
                    "title": "后来的新闻",
                    "url": "https://news.example/new",
                    "snippet": "新动态",
                    "provider": "google_news_rss",
                    "published": "Fri, 03 Oct 2026 00:00:00 GMT",
                },
                {
                    "title": "没有日期",
                    "url": "https://news.example/undated",
                    "snippet": "未知",
                    "provider": "searxng",
                    "published": "",
                },
            ],
            "providers": [{"provider": "google_news_rss", "status": "ok", "resultCount": 3}],
            "rejectedCount": 0,
            "rawResultCount": 3,
        }

    monkeypatch.setattr(research_search_backends, "collect_provider_results", collect)
    with research_analysis_date_context(REQUEST):
        rendered = research_search_tools.news_search("贵州茅台", date_hint="2026")
    assert "当年披露" in rendered
    assert "后来的新闻" not in rendered
    assert "没有日期" not in rendered
    assert "已略过 2 条" in rendered


def test_news_search_without_an_analysis_date_keeps_the_existing_query(monkeypatch):
    captured = {}

    def collect(query, providers, max_results):
        captured["query"] = query
        return {"query": query, "results": [], "providers": [], "rejectedCount": 0, "rawResultCount": 0}

    monkeypatch.setattr(research_search_backends, "collect_provider_results", collect)
    monkeypatch.setattr(research_search_tools, "public_web_search", lambda **kwargs: kwargs["query"])
    assert research_search_tools.news_search("贵州茅台") == "贵州茅台 2026" + research_search_tools._domain_query(
        research_search_tools._CN_NEWS_DOMAINS
    )
    assert captured["query"] == "贵州茅台 2026"


def test_market_snapshot_omits_a_quote_and_candles_after_the_analysis_date(monkeypatch):
    monkeypatch.setattr(
        "core.web.services.financial_market_service.get_stock_snapshot",
        lambda symbol, period: {
            "stock": {
                "symbol": symbol,
                "timestamp": "2026-10-05T15:00:00+08:00",
                "price": 12.34,
            },
            "candles": [
                {"date": "2024-12-30", "open": 1, "close": 2, "high": 3, "low": 0.5, "volumeLots": 10},
                {"date": "2026-10-05", "open": 12.1, "close": 12.34, "high": 12.5, "low": 12.0, "volumeLots": 20},
            ],
            "source": "腾讯财经",
            "sourceUrl": f"https://gu.qq.com/{symbol}/gp",
            "fetchedAt": "2026-10-05T07:00:00+00:00",
            "candleError": "",
        },
    )
    with research_analysis_date_context(REQUEST):
        result = json.loads(financial_market_snapshot_tool("sh600519", "day", 20))
    assert result["quote"] is None
    assert result["candles"]["rows"] == [["2024-12-30", 1, 2, 3, 0.5, 10]]
    assert "未返回该报价" in result["message"]
    assert "12.34" not in result["message"]


def test_market_screen_without_a_trade_date_is_not_evidence_for_an_earlier_analysis_date(monkeypatch):
    def unexpected_lookup(*_args, **_kwargs):
        raise AssertionError("cleared screen must not look up filings")

    monkeypatch.setattr("tools.financial_market_tools.lookup_annual_filings", unexpected_lookup)
    monkeypatch.setattr(
        "core.web.services.financial_research_service.screen_stocks",
        lambda **kwargs: {
            "source": "新浪财经",
            "sourceUrl": "https://vip.stock.finance.sina.com.cn/mkt/#hs_a",
            "fetchedAt": "2026-10-07T01:00:00+00:00",
            "dataDate": None,
            "dataTime": "15:00:00",
            "coverage": {
                "providerTotal": 1,
                "loaded": 1,
                "complete": True,
                "failedPages": [],
                "invalidRows": 0,
                "duplicateRows": 0,
                "totalFiltered": 1,
            },
            "items": [
                {
                    "symbol": "sh600519",
                    "ticker": "600519",
                    "name": "贵州茅台",
                    "market": "上交所",
                    "price": 1258.62,
                    "changePercent": 1.2,
                    "peRatio": 20,
                    "pbRatio": 7,
                    "volumeLots": 100,
                    "turnoverYuan": 1000,
                    "timeOfDay": "15:00:00",
                }
            ],
        },
    )
    with research_analysis_date_context(REQUEST):
        result = json.loads(financial_market_screen_tool(limit=5))
    assert result["items"] == []
    assert result["returnedCount"] == 0
    assert "未作为本次研究依据" in result["message"]
    assert "1258.62" not in json.dumps(result)


def test_public_fundamentals_after_the_research_date_are_omitted(monkeypatch):
    monkeypatch.setattr(
        runs.public_research,
        "stock_research",
        lambda symbol: {
            "fundamentals": {
                "status": "available",
                "source": "公开财务指标源",
                "sourceUrl": "https://example.test/fundamentals",
                "fetchedAt": "2026-10-05T09:30:00+08:00",
                "reportDate": "2026-06-30",
                "publishedAt": "2026-08-28",
                "items": [
                    {
                        "label": "营业收入",
                        "value": "123.4",
                        "unit": "亿元",
                        "reportDate": "2026-06-30",
                        "publishedAt": "2026-08-28",
                    }
                ],
            }
        },
    )
    with research_analysis_date_context("研究日期：2024-12-31"):
        late = runs._public_fundamentals_snapshot("sh600519")
    assert late["items"] == []
    assert late["status"] == "unavailable"
    assert "123.4" not in runs._format_public_fundamentals(late)
    with research_analysis_date_context("研究日期：2026-10-05"):
        kept = runs._public_fundamentals_snapshot("sh600519")
    assert kept["items"][0]["value"] == "123.4"
