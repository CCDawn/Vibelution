"""Public disclosure adapters keep source, period, and units verifiable."""

from urllib.parse import parse_qs, urlparse

import pytest

from core.web.services.financial_research import disclosures


def _indicator_row(**overrides):
    return {
        "SECUCODE": "NVDA.O",
        "SECURITY_CODE": "NVDA",
        "REPORT_DATE": "2026-07-26 00:00:00",
        "STD_REPORT_DATE": "2026-06-30 00:00:00",
        "NOTICE_DATE": "2026-08-26 00:00:00",
        "DATE_TYPE_CODE": "008",
        "REPORT_TYPE": "2026/Q2",
        "CURRENCY": "美元",
        "CURRENCY_ABBR": "USD",
        "OPERATE_INCOME": 96_221_000_000,
        "GROSS_PROFIT": 72_142_000_000,
        "PARENT_HOLDER_NETPROFIT": 59_688_000_000,
        "BASIC_EPS": 2.47,
        "GROSS_PROFIT_RATIO": 74.97,
        "NET_PROFIT_RATIO": 62.03,
        "ROE_AVG": 28.12,
        "DEBT_ASSET_RATIO": 28.5,
        **overrides,
    }


def _eastmoney_payload(rows):
    return {"success": True, "result": {"data": rows}}


def test_hkex_uses_internal_stock_id_and_returns_official_pdf(monkeypatch):
    monkeypatch.setattr(
        disclosures,
        "_load_cached",
        lambda _key, _ttl, loader: loader(),
    )
    requested_urls = []

    def read_json(url, **_kwargs):
        requested_urls.append(url)
        if "activestock_sehk_e.json" in url:
            return [{"c": "00700", "i": "7609"}]
        return {
            "result": [
                {
                    "LONG_TEXT": "Quarterly Results",
                    "FILE_LINK": "/listedco/listconews/sehk/2026/0101/202601010001.pdf",
                    "DATE_TIME": "01/01/2026 18:30",
                    "NEWS_ID": "12345",
                }
            ]
        }

    monkeypatch.setattr(disclosures, "_read_json", read_json)

    result = disclosures._load_hk_announcements({"symbol": "hk00700"})

    search = next(url for url in requested_urls if "titleSearchServlet.do" in url)
    assert parse_qs(urlparse(search).query)["stockId"] == ["7609"]
    assert result["items"][0]["url"].endswith("/202601010001.pdf")


def test_hk_fundamentals_uses_report_list_currency_for_the_matching_period(
    monkeypatch,
):
    monkeypatch.setattr(disclosures, "_load_hk_indicator_rows", lambda _code: [
        {
            "REPORT_DATE": "2025-12-31",
            "NOTICE_DATE": "2026-03-19",
            "CURRENCY": "HKD",
            "OPERATE_INCOME": 100,
            "HOLDER_PROFIT": 20,
            "BASIC_EPS": 1.5,
            "ROE_AVG": 12,
        }
    ])
    monkeypatch.setattr(
        disclosures,
        "_load_hk_report_currencies",
        lambda _code: {"2025-12-31": "人民币"},
    )

    result = disclosures._load_hk_fundamentals({"symbol": "hk00700"})

    units = {item["key"]: item["unit"] for item in result["items"]}
    assert units["OPERATE_INCOME"] == "CNY"
    assert units["BASIC_EPS"] == "CNY/股"
    assert units["ROE_AVG"] == "%"


def test_sec_fundamentals_selects_facts_for_the_submitted_accession_and_period():
    cik = "0000320193"
    accession = "0000320193-26-000001"
    old_accession = "0000320193-25-000002"
    submissions = {
        "filings": {
            "recent": {
                "form": ["10-Q", "10-K"],
                "filingDate": ["2026-07-30", "2025-10-31"],
                "reportDate": ["2026-06-30", "2025-09-30"],
                "accessionNumber": [accession, old_accession],
                "primaryDocument": ["q2.htm", "fy.htm"],
                "primaryDocDescription": ["Quarterly Report", "Annual Report"],
            }
        }
    }
    facts = {
        "facts": {
            "us-gaap": {
                "Assets": {
                    "units": {
                        "USD": [
                            {
                                "accn": old_accession,
                                "form": "10-K",
                                "end": "2025-09-30",
                                "val": 10,
                            },
                            {
                                "accn": accession,
                                "form": "10-Q",
                                "end": "2026-06-30",
                                "val": 20,
                            },
                        ]
                    }
                },
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "accn": accession,
                                "form": "10-Q",
                                "start": "2026-04-01",
                                "end": "2026-06-30",
                                "filed": "2026-07-30",
                                "val": 50,
                            }
                        ]
                    }
                },
            }
        }
    }

    result = disclosures._load_us_fundamentals(cik, facts, submissions)

    assert result["reportDate"] == "2026-06-30"
    assert result["publishedAt"] == "2026-07-30"
    assert {item["key"]: item["value"] for item in result["items"]} == {
        "revenue": 50,
        "assets": 20,
    }


def test_sec_10q_hides_ytd_values_when_no_discrete_quarter_fact_exists():
    accession = "0000320193-26-000001"
    submissions = {
        "filings": {
            "recent": {
                "form": ["10-Q"],
                "filingDate": ["2026-07-30"],
                "reportDate": ["2026-06-30"],
                "accessionNumber": [accession],
                "primaryDocument": ["q2.htm"],
                "primaryDocDescription": ["Quarterly Report"],
            }
        }
    }
    facts = {
        "facts": {
            "us-gaap": {
                "Assets": {
                    "units": {
                        "USD": [
                            {
                                "accn": accession,
                                "form": "10-Q",
                                "end": "2026-06-30",
                                "val": 500,
                            }
                        ]
                    }
                },
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "accn": accession,
                                "form": "10-Q",
                                "start": "2026-01-01",
                                "end": "2026-06-30",
                                "filed": "2026-07-30",
                                "val": 300,
                            }
                        ]
                    }
                },
            }
        }
    }

    result = disclosures._load_us_fundamentals("0000320193", facts, submissions)

    metrics = {item["key"]: item["value"] for item in result["items"]}
    assert metrics == {"assets": 500}
    assert "独立季度值" in result["error"]
    assert "未用年初至今累计值替代" in result["error"]


def test_read_json_rejects_https_to_http_downgrade_before_reading(monkeypatch):
    class DowngradedResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def geturl(self):
            return "http://data.sec.gov/test.json"

        def read(self, _size):
            pytest.fail("A downgraded HTTP response body must never be read")

    monkeypatch.setattr(disclosures, "urlopen", lambda *_args, **_kwargs: DowngradedResponse())

    with pytest.raises(disclosures.FinancialDisclosureDataError, match="非 HTTPS"):
        disclosures._read_json("https://data.sec.gov/test.json", source="SEC EDGAR")


def test_us_fallback_limits_rows_and_selects_latest_non_cumulative_period(monkeypatch):
    calls = []

    def read_json(url, **_kwargs):
        calls.append(url)
        query = parse_qs(urlparse(url).query)
        if query.get("reportName") == [disclosures.US_EASTMONEY_PROFILE_REPORT]:
            assert query["filter"] == ['(SECURITY_CODE="NVDA")']
            return _eastmoney_payload(
                [{"SECURITY_CODE": "NVDA", "SECUCODE": "NVDA.O"}]
            )
        assert query["reportName"] == [disclosures.US_EASTMONEY_INDICATOR_REPORT]
        assert query["pageSize"] == ["12"]
        return _eastmoney_payload(
            [
                _indicator_row(
                    REPORT_TYPE="2026/Q6",
                    DATE_TYPE_CODE="002",
                    PARENT_HOLDER_NETPROFIT=118_010_000_000,
                ),
                _indicator_row(),
                _indicator_row(
                    REPORT_DATE="2026-04-26",
                    NOTICE_DATE="2026-05-20",
                    REPORT_TYPE="2026/Q1",
                    DATE_TYPE_CODE="003",
                    OPERATE_INCOME=81_615_000_000,
                ),
            ]
        )

    monkeypatch.setattr(disclosures, "_load_cached", lambda _key, _ttl, loader: loader())
    monkeypatch.setattr(disclosures, "_read_json", read_json)

    result = disclosures._load_us_eastmoney_fundamentals(
        {"symbol": "usNVDA", "ticker": "NVDA.OQ"}
    )

    assert len(calls) == 2
    assert result["source"] == disclosures.US_EASTMONEY_SOURCE
    assert result["reportDate"] == "2026-07-26"
    assert result["publishedAt"] == "2026-08-26"
    metrics = {item["key"]: item for item in result["items"]}
    assert metrics["revenue"]["value"] == 96_221_000_000
    assert metrics["revenue"]["unit"] == "USD"
    assert metrics["basicEps"]["unit"] == "USD/股"
    assert metrics["grossMargin"]["unit"] == "%"


def test_us_fallback_hides_currency_values_when_currency_is_unverified(monkeypatch):
    row = _indicator_row(CURRENCY_ABBR="XYZ", CURRENCY="unknown")
    monkeypatch.setattr(disclosures, "_load_cached", lambda _key, _ttl, loader: loader())
    monkeypatch.setattr(
        disclosures,
        "_read_json",
        lambda url, **_kwargs: (
            _eastmoney_payload(
                [{"SECURITY_CODE": "NVDA", "SECUCODE": "NVDA.O"}]
            )
            if parse_qs(urlparse(url).query).get("reportName")
            == [disclosures.US_EASTMONEY_PROFILE_REPORT]
            else _eastmoney_payload([row])
        ),
    )

    result = disclosures._load_us_eastmoney_fundamentals({"symbol": "usNVDA"})

    keys = {item["key"] for item in result["items"]}
    assert "revenue" not in keys
    assert "basicEps" not in keys
    assert "grossMargin" in keys
    assert "USD" not in {item["unit"] for item in result["items"]}
    assert "币种未能核实" in result["error"]


def test_us_report_currency_rejects_conflicting_explicit_currency_fields():
    assert (
        disclosures._us_report_currency(
            {"CURRENCY_ABBR": "USD", "CURRENCY": "人民币"}
        )
        is None
    )


def test_us_sec_failure_uses_eastmoney_and_keeps_sec_announcement_entry(monkeypatch):
    def read_sec(url, **_kwargs):
        if url.startswith("https://data.sec.gov/submissions/"):
            raise disclosures.FinancialDisclosureDataError("SEC EDGAR 暂时不可用")
        pytest.fail(f"Unexpected request: {url}")

    fallback = {
        "status": "available",
        "source": disclosures.US_EASTMONEY_SOURCE,
        "sourceUrl": "https://emweb.eastmoney.com/PC_USF10/pages/index.html?code=NVDA",
        "fetchedAt": "2026-10-06T00:00:00+00:00",
        "reportDate": "2026-07-26",
        "publishedAt": "2026-08-26",
        "error": None,
        "items": [],
    }
    monkeypatch.setattr(disclosures, "_sec_ticker_ids", lambda: {"NVDA": ("0001045810", "NVIDIA")})
    monkeypatch.setattr(disclosures, "_read_json", read_sec)
    monkeypatch.setattr(
        disclosures,
        "_load_us_eastmoney_fundamentals",
        lambda _stock: dict(fallback),
    )

    facets = disclosures.fetch_international_facets({"symbol": "usNVDA"})

    assert facets["announcements"]["status"] == "unavailable"
    assert "sec.gov/edgar/browse" in facets["announcements"]["sourceUrl"]
    fundamentals = facets["fundamentals"]
    assert fundamentals["status"] == "available"
    assert fundamentals["source"] == disclosures.US_EASTMONEY_SOURCE
    assert "PC_USF10" in fundamentals["sourceUrl"]
    assert "SEC EDGAR 主源失败" in fundamentals["error"]
    assert "未经 SEC 核验" in fundamentals["error"]


def test_fallback_note_reports_both_sources_when_eastmoney_is_unavailable():
    result = disclosures._with_sec_fallback_note(
        {
            "status": "unavailable",
            "source": disclosures.US_EASTMONEY_SOURCE,
            "sourceUrl": "https://emweb.eastmoney.com/PC_USF10/pages/index.html",
            "error": "东方财富 USF10 未找到该美股代码",
        },
        "SEC EDGAR 暂时不可用",
    )

    assert result["status"] == "unavailable"
    assert "SEC EDGAR 主源失败" in result["error"]
    assert "东方财富 USF10 备用源失败" in result["error"]


@pytest.mark.parametrize(
    ("stock", "expected"),
    [
        ({"symbol": "usNVDA", "ticker": "NVDA.OQ"}, "NVDA"),
        ({"symbol": "usBRK.B"}, "BRK-B"),
    ],
)
def test_us_ticker_maps_provider_suffix_for_sec(stock, expected):
    assert disclosures._us_ticker(stock) == expected


def test_us_eastmoney_share_class_uses_underscore_security_code():
    assert disclosures._us_eastmoney_ticker_candidates({"symbol": "usBRK.B"}) == [
        "BRK_B"
    ]
