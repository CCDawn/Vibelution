import json
from datetime import date, datetime
from urllib.request import Request
from zoneinfo import ZoneInfo

import pytest

from core.web.services.financial_research import official_filings
from core.web.services.financial_research.official_filings import (
    ANNUAL_CATEGORY,
    FILING_SOURCE,
    Q1_CATEGORY,
    Q3_CATEGORY,
    REQUEST_TIMEOUT_SECONDS,
    SEMIANNUAL_CATEGORY,
    OfficialFilingLookupError,
    accepted_annual_filing,
    filing_for_report_period,
    lookup_annual_filings,
    lookup_periodic_filings,
    lookup_screen_filings,
    mentions_annual_report,
    periodic_reprint_kind,
)


def test_filing_for_report_period_keeps_only_the_same_period():
    semi = {
        "kind": "semiannual",
        "title": "贵州茅台2026年半年度报告",
        "url": "https://static.cninfo.com.cn/finalpage/2026-08-28/1225000001.PDF",
        "announcedOn": "2026-08-28",
        "source": FILING_SOURCE,
    }
    old_semi = {
        **semi,
        "title": "贵州茅台2025年半年度报告",
        "announcedOn": "2025-08-28",
        "url": "https://static.cninfo.com.cn/finalpage/2025-08-28/1225000002.PDF",
    }
    early = {
        **semi,
        "announcedOn": "2026-06-01",
        "url": "https://static.cninfo.com.cn/finalpage/2026-06-01/1225000003.PDF",
    }
    annual = {
        "kind": "annual",
        "title": "贵州茅台2025年年度报告",
        "url": PDF,
        "announcedOn": "2026-04-17",
        "source": FILING_SOURCE,
    }
    summary = {**semi, "title": "贵州茅台2026年半年度报告摘要"}
    rows = [old_semi, annual, early, summary, semi]
    found = filing_for_report_period(rows, "2026-06-30", cutoff=date(2026, 10, 5))
    assert found is not None
    assert found["url"] == semi["url"]
    assert filing_for_report_period(rows, "2026-03-31", cutoff=date(2026, 10, 5)) is None
    assert filing_for_report_period(rows, "2026-06-15", cutoff=date(2026, 10, 5)) is None
    assert filing_for_report_period(rows, "2026-06-30", cutoff=date(2026, 7, 1)) is None
    annual_match = filing_for_report_period(rows, "2025-12-31", cutoff=date(2026, 10, 5))
    assert annual_match is not None
    assert annual_match["url"] == PDF
    assert filing_for_report_period([summary], "2026-06-30") is None


def test_mentions_annual_report_includes_summaries_and_spaced_titles():
    assert mentions_annual_report("贵州茅台2025年年度报告")
    assert mentions_annual_report("贵州茅台2025年年度报告摘要")
    assert mentions_annual_report("年 度 报 告")
    assert mentions_annual_report("年度报告") is True
    assert not mentions_annual_report("贵州茅台2026年半年度报告")
    assert not mentions_annual_report("关于召开股东大会的通知")
    assert not mentions_annual_report(None)
    assert periodic_reprint_kind("贵州茅台2026年半年度报告摘要") == "semiannual"
    assert periodic_reprint_kind("2026年一季度报告") == "q1"
    assert periodic_reprint_kind("贵州茅台2025年第三季度报告") == "q3"
    assert periodic_reprint_kind("2025年三季度报告") == "q3"


PDF = "https://static.cninfo.com.cn/finalpage/2026-04-17/1225114741.PDF"
LIVE_ANNOUNCED_MS = 1776355200000


def _ms(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp() * 1000)


class _Body:
    def __init__(self, payload, url):
        self.payload = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode()
        self.url = url

    def read(self, amount):
        return self.payload[:amount]

    def geturl(self):
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _announcement(title, adjunct, announced_ms, code="600519"):
    return {
        "announcementTitle": title,
        "adjunctUrl": adjunct,
        "announcementTime": announced_ms,
        "secCode": code,
    }


def test_reader_accepts_cninfo_json_and_rejects_a_redirect_or_oversize_body(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["body"] = request.data.decode()
        assert isinstance(request, Request)
        return _Body([{"code": "600519"}], request.full_url)

    monkeypatch.setattr(official_filings, "urlopen", fake_urlopen)
    assert official_filings._post_json("/new/information/topSearch/query", {"keyWord": "600519"}) == [{"code": "600519"}]
    assert captured["timeout"] == REQUEST_TIMEOUT_SECONDS
    assert captured["url"] == "https://www.cninfo.com.cn/new/information/topSearch/query"
    assert "keyWord=600519" in captured["body"]

    monkeypatch.setattr(official_filings, "urlopen", lambda request, timeout: _Body([], "https://evil.example/query"))
    with pytest.raises(OfficialFilingLookupError):
        official_filings._post_json("/new/information/topSearch/query", {"keyWord": "600519"})

    monkeypatch.setattr(
        official_filings,
        "urlopen",
        lambda request, timeout: _Body(b"x" * (official_filings.MAX_RESPONSE_BYTES + 2), request.full_url),
    )
    with pytest.raises(OfficialFilingLookupError):
        official_filings._post_json("/new/information/topSearch/query", {"keyWord": "600519"})


def test_org_and_column_accepts_cninfo_nssc_for_the_matching_a_share():
    payload = [
        {"code": "688766", "category": "债券", "orgId": "nssc1000720"},
        {"code": "688765", "category": "A股", "orgId": "nssc1000720"},
        {"code": "688766", "category": "A股", "orgId": "nssc1000720"},
    ]

    assert official_filings._org_and_column(payload, "688766") == (
        "nssc1000720",
        "sse",
    )


@pytest.mark.parametrize(
    ("code", "org_id", "column"),
    [("002656", "9900022094", "szse"), ("300750", "GD165627", "szse"),
     ("920185", "nssc920185", "bj")],
)
def test_modern_issuer_ids_use_the_exact_a_share_code_for_exchange(code, org_id, column):
    payload = [{"code": code, "category": "A股", "orgId": org_id}]
    assert official_filings._org_and_column(payload, code) == (org_id, column)


@pytest.mark.parametrize("org_id", ["9900022094", "GD165627"])
def test_modern_issuer_ids_never_relax_code_or_category_checks(org_id):
    assert official_filings._org_and_column(
        [{"code": "002656", "category": "A股", "orgId": org_id}], "300750"
    ) is None
    assert official_filings._org_and_column(
        [{"code": "300750", "category": "债券", "orgId": org_id}], "300750"
    ) is None


def test_identity_conflicts_fail_closed_and_duplicate_exact_records_are_safe():
    active = {"code": "300750", "category": "A股", "orgId": "GD165627"}
    conflicting = {**active, "orgId": "9900022094"}
    assert official_filings._org_and_column([active, conflicting], "300750") is None
    assert official_filings._org_and_column([active, active], "300750") == ("GD165627", "szse")
    assert official_filings._org_and_column(
        [{**conflicting, "delisted": "true"}, active], "300750"
    ) == ("GD165627", "szse")
    assert official_filings._org_and_column(
        [{**active, "orgId": "gssh0300750"}], "300750"
    ) is None


@pytest.mark.parametrize("org_id", ["9900022094,other", "GD165627&column=sse", "GD165627\n",
                                     "9" * 33, "GD" + "1" * 31, 9900022094])
def test_modern_identity_rejects_transport_injection_and_unbounded_ids(org_id):
    assert official_filings._org_and_column(
        [{"code": "300750", "category": "A股", "orgId": org_id}], "300750"
    ) is None


@pytest.mark.parametrize(("code", "org_id"), [("002656", "9900022094"), ("300750", "GD165627")])
def test_periodic_lookup_passes_modern_identity_to_the_official_directory(monkeypatch, code, org_id):
    calls = []

    def fake(path, fields):
        if path.endswith("topSearch/query"):
            return [{"code": code, "category": "A股", "orgId": org_id}]
        calls.append(dict(fields))
        return {"announcements": [
            _announcement("2024年年度报告", "finalpage/2025-04-03/1223000001.PDF",
                          _ms(date(2025, 4, 3)), code),
            _announcement("2025年年度报告", "finalpage/2026-04-17/1225114741.PDF",
                          LIVE_ANNOUNCED_MS, code),
        ], "hasMore": False}

    monkeypatch.setattr(official_filings, "_post_json", fake)
    found = official_filings.lookup_periodic_filings([code], cutoff=date(2025, 12, 31))
    assert found[code][0]["announcedOn"] == "2025-04-03"
    assert calls
    assert all(fields["stock"] == f"{code},{org_id}" and fields["column"] == "szse"
               and fields["seDate"] == "1990-01-01~2025-12-31" for fields in calls)


@pytest.mark.parametrize(
    "org_id",
    [
        None,
        688766,
        "nssc1000720&category=all",
        "nssc1000720,other",
        "nssc1000720/../",
        'nssc1000720"><script>alert(1)</script>',
        "nssc1000720\n",
        "nssc12345",
        "nssc" + "1" * 13,
    ],
)
def test_org_and_column_rejects_malformed_or_injected_org_ids(org_id):
    payload = [{"code": "688766", "category": "A股", "orgId": org_id}]

    assert official_filings._org_and_column(payload, "688766") is None


def test_org_and_column_rejects_nssc_for_another_security_code_or_market():
    assert official_filings._org_and_column(
        [{"code": "688765", "category": "A股", "orgId": "nssc1000720"}],
        "688766",
    ) is None
    assert official_filings._org_and_column(
        [{"code": "688766", "category": "债券", "orgId": "nssc1000720"}],
        "688766",
    ) is None


def test_lookup_prefers_the_full_annual_report_and_the_exchange_column(monkeypatch):
    calls = []

    def fake(path, fields):
        calls.append((path, dict(fields)))
        if path.endswith("topSearch/query"):
            orgs = {
                "600519": "gssh0600519",
                "000001": "gssz0000001",
                "830799": "gfbj0830799",
                "688766": "nssc1000720",
            }
            code = fields["keyWord"]
            return [
                {"code": "999999", "category": "A股", "orgId": "gssh0999999"},
                {"code": code, "category": "债券", "orgId": orgs[code]},
                {"code": code, "category": "A股", "delisted": "true", "orgId": "gssh0000000"},
                {"code": code, "category": "A股", "delisted": "false", "orgId": orgs[code]},
            ]
        code = fields["stock"].split(",", 1)[0]
        return {"announcements": [
            _announcement(f"{code}2025年年度报告摘要", "finalpage/2026-04-17/1.PDF", LIVE_ANNOUNCED_MS, code),
            _announcement(f"<em>{code}</em>2025年年度报告", "finalpage/2026-04-17/1225114741.PDF", LIVE_ANNOUNCED_MS, code),
            _announcement(f"{code}2024年年度报告", "finalpage/2025-04-03/9.PDF", LIVE_ANNOUNCED_MS - 86400000 * 300, code),
            _announcement(f"{code}2025年年度报告", "https://evil.example/a.PDF", LIVE_ANNOUNCED_MS, code),
            _announcement(f"{code}2025年年度报告", "finalpage/2026-02-30/9.PDF", LIVE_ANNOUNCED_MS, code),
            _announcement(f"{code}2025年年度报告", "finalpage/2026-04-17/9.PDF", True, code),
        ]}

    monkeypatch.setattr(official_filings, "_post_json", fake)
    found = lookup_annual_filings(
        ["sh600519", "000001", "830799", "688766", "1600519", "600519"],
        cutoff=date(2026, 10, 6),
    )

    assert set(found) == {"600519", "000001", "830799", "688766"}
    assert found["600519"] == {
        "title": "6005192025年年度报告",
        "url": PDF,
        "announcedOn": "2026-04-17",
        "source": FILING_SOURCE,
    }
    columns = {fields["stock"].split(",", 1)[0]: fields["column"] for path, fields in calls if path.endswith("hisAnnouncement/query")}
    assert columns == {"600519": "sse", "000001": "szse", "830799": "bj", "688766": "sse"}
    assert any(
        fields["stock"] == "688766,nssc1000720"
        for path, fields in calls
        if path.endswith("hisAnnouncement/query")
    )
    assert {fields["category"] for path, fields in calls if "category" in fields} == {ANNUAL_CATEGORY}
    assert all(fields["seDate"] == "1990-01-01~2026-10-06" for path, fields in calls if "seDate" in fields)


def test_lookup_keeps_the_latest_full_report_on_or_before_the_cutoff(monkeypatch):
    def fake(path, fields):
        if path.endswith("topSearch/query"):
            return [{"code": "600519", "category": "A股", "delisted": "false", "orgId": "gssh0600519"}]
        return {"announcements": [
            _announcement("贵州茅台2025年年度报告", "finalpage/2026-04-17/1225114741.PDF", LIVE_ANNOUNCED_MS),
            _announcement("贵州茅台2024年年度报告", "finalpage/2025-04-03/9.PDF", _ms(date(2025, 4, 3))),
        ]}

    monkeypatch.setattr(official_filings, "_post_json", fake)
    kept = lookup_annual_filings(["600519"], cutoff=date(2026, 4, 16))
    assert kept["600519"]["announcedOn"] == "2025-04-03"
    assert kept["600519"]["title"] == "贵州茅台2024年年度报告"
    assert lookup_annual_filings(["600519"], cutoff=date(2025, 4, 2)) == {}


def test_summary_wrong_code_and_lookup_errors_are_not_filings(monkeypatch):
    def fake(path, fields):
        if path.endswith("topSearch/query"):
            return [{"code": "600519", "category": "A股", "orgId": "gssh0600519"}]
        if fields["stock"].startswith("600519"):
            return {"announcements": [_announcement("贵州茅台2025年年度报告摘要", "finalpage/2026-04-17/1.PDF", LIVE_ANNOUNCED_MS)]}
        raise OfficialFilingLookupError("down")

    monkeypatch.setattr(official_filings, "_post_json", fake)
    assert lookup_annual_filings(["600519", "000001"]) == {}


def test_accepted_filing_rejects_undated_late_and_non_document_urls():
    good = {"title": "贵州茅台2025年年度报告", "url": PDF, "announcedOn": "2026-04-17", "source": FILING_SOURCE}
    assert accepted_annual_filing(good, cutoff=date(2026, 4, 17)) == good
    assert accepted_annual_filing(good, cutoff=date(2026, 4, 16)) is None
    assert accepted_annual_filing({**good, "announcedOn": "2026-02-30"}, cutoff=None) is None
    assert accepted_annual_filing({**good, "title": "贵州茅台2025年年度报告（英文）"}, cutoff=None) is None
    assert accepted_annual_filing({**good, "title": "贵州茅台2026年半年度报告"}, cutoff=None) is None
    assert accepted_annual_filing({**good, "url": "https://user@static.cninfo.com.cn/finalpage/2026-04-17/1.PDF"}, cutoff=None) is None
    assert accepted_annual_filing({**good, "url": "http://static.cninfo.com.cn/finalpage/2026-04-17/1.PDF"}, cutoff=None) is None
    assert accepted_annual_filing({**good, "url": PDF + "?download=1"}, cutoff=None) is None


def test_lookup_periodic_filings_keeps_one_full_report_per_kind(monkeypatch):
    calls = []

    def fake(path, fields):
        calls.append((path, dict(fields)))
        if path.endswith("topSearch/query"):
            orgs = {"600519": "gssh0600519", "830799": "gfbj0830799"}
            code = fields["keyWord"]
            return [{"code": code, "category": "A股", "orgId": orgs[code], "delisted": "false"}]
        code = fields["stock"].split(",", 1)[0]
        category = fields["category"]
        if category == Q1_CATEGORY and code == "600519":
            raise OfficialFilingLookupError("down")
        titles = {
            ANNUAL_CATEGORY: [
                _announcement(f"{code}2025年年度报告摘要", "finalpage/2026-04-17/1.PDF", LIVE_ANNOUNCED_MS, code),
                _announcement(f"{code}2026年半年度报告", "finalpage/2026-08-15/2.PDF", _ms(date(2026, 8, 15)), code),
                _announcement(f"{code}2025年年度报告", "finalpage/2026-04-17/1225114741.PDF", LIVE_ANNOUNCED_MS, code),
            ],
            SEMIANNUAL_CATEGORY: [
                _announcement(f"{code}2026年半年度报告摘要", "finalpage/2026-08-15/3.PDF", _ms(date(2026, 8, 15)), code),
                _announcement(f"{code}2026年半年度报告", "finalpage/2026-08-15/1225475868.PDF", _ms(date(2026, 8, 15)), code),
            ],
            Q1_CATEGORY: [
                _announcement(f"{code}2025年年度报告", "finalpage/2026-04-17/8.PDF", LIVE_ANNOUNCED_MS, code),
                _announcement(f"{code}2026年一季度报告", "finalpage/2026-04-25/1225188741.PDF", _ms(date(2026, 4, 25)), code),
            ],
            Q3_CATEGORY: [
                _announcement(f"{code}2025年第三季度报告", "finalpage/2025-10-30/1224764517.PDF", _ms(date(2025, 10, 30)), code),
                _announcement(f"{code}2024年三季度报告", "finalpage/2024-10-30/9.PDF", _ms(date(2024, 10, 30)), code),
            ],
        }
        return {"announcements": titles[category]}

    monkeypatch.setattr(official_filings, "_post_json", fake)
    found = lookup_periodic_filings(["600519", "830799"])

    maotai = {row["kind"]: row for row in found["600519"]}
    assert set(maotai) == {"annual", "semiannual", "q3"}
    assert maotai["annual"]["title"] == "6005192025年年度报告"
    assert maotai["annual"]["announcedOn"] == "2026-04-17"
    assert maotai["semiannual"]["url"].endswith("/1225475868.PDF")
    assert maotai["q3"]["title"] == "6005192025年第三季度报告"
    assert [row["kind"] for row in found["600519"]] == ["semiannual", "annual", "q3"]
    assert {row["kind"] for row in found["830799"]} == {"annual", "semiannual", "q1", "q3"}
    columns = {
        fields["stock"].split(",", 1)[0]: fields["column"]
        for path, fields in calls
        if path.endswith("hisAnnouncement/query")
    }
    assert columns["600519"] == "sse"
    assert columns["830799"] == "bj"
    categories = {fields["category"] for path, fields in calls if path.endswith("hisAnnouncement/query")}
    assert categories == {ANNUAL_CATEGORY, SEMIANNUAL_CATEGORY, Q1_CATEGORY, Q3_CATEGORY}


def test_lookup_screen_filings_uses_one_joined_query_per_code(monkeypatch):
    calls = []
    joined = ";".join((ANNUAL_CATEGORY, SEMIANNUAL_CATEGORY, Q1_CATEGORY, Q3_CATEGORY))

    def fake(path, fields):
        calls.append((path, dict(fields)))
        if path.endswith("topSearch/query"):
            if fields["keyWord"] == "000001":
                raise OfficialFilingLookupError("down")
            orgs = {"600519": "gssh0600519", "830799": "gfbj0830799"}
            code = fields["keyWord"]
            return [{"code": code, "category": "A股", "orgId": orgs[code], "delisted": "false"}]
        code = fields["stock"].split(",", 1)[0]
        return {"announcements": [
            _announcement(f"{code}2025年年度报告摘要", "finalpage/2026-04-17/1.PDF", LIVE_ANNOUNCED_MS, code),
            _announcement(f"{code}2026年半年度报告", "finalpage/2026-08-15/1225475868.PDF", _ms(date(2026, 8, 15)), code),
            _announcement(f"{code}2025年年度报告", "finalpage/2026-04-17/1225114741.PDF", LIVE_ANNOUNCED_MS, code),
            _announcement(f"{code}2024年年度报告", "finalpage/2025-04-03/9.PDF", _ms(date(2025, 4, 3)), code),
            _announcement(f"{code}2026年第一季度报告", "finalpage/2026-04-25/1225187851.PDF", _ms(date(2026, 4, 25)), code),
            _announcement(f"{code}2026年一季度报告", "finalpage/2026-10-08/8.PDF", _ms(date(2026, 10, 8)), code),
            _announcement(f"{code}2025年第三季度报告", "finalpage/2025-10-30/1224764517.PDF", _ms(date(2025, 10, 30)), code),
            _announcement(f"{code}2025年季度报告", "finalpage/2025-10-30/7.PDF", _ms(date(2025, 10, 30)), code),
            _announcement("其他公司2025年年度报告", "finalpage/2026-04-17/6.PDF", LIVE_ANNOUNCED_MS, "000002"),
        ]}

    monkeypatch.setattr(official_filings, "_post_json", fake)
    found = lookup_screen_filings(["sh600519", "000001", "830799", "1600519"], cutoff=date(2026, 10, 6))

    assert set(found) == {"600519", "830799"}
    maotai = {row["kind"]: row for row in found["600519"]}
    assert set(maotai) == {"annual", "semiannual", "q1", "q3"}
    assert [row["kind"] for row in found["600519"]] == ["annual", "semiannual", "q1", "q3"]
    assert maotai["annual"]["title"] == "6005192025年年度报告"
    assert maotai["annual"]["announcedOn"] == "2026-04-17"
    assert maotai["semiannual"]["url"].endswith("/1225475868.PDF")
    assert maotai["q1"]["title"] == "6005192026年第一季度报告"
    assert maotai["q1"]["announcedOn"] == "2026-04-25"
    assert maotai["q3"]["title"] == "6005192025年第三季度报告"
    queries = [fields for path, fields in calls if path.endswith("hisAnnouncement/query")]
    assert len(queries) == 2
    assert {fields["category"] for fields in queries} == {joined}
    assert {fields["column"] for fields in queries} == {"sse", "bj"}
    assert all(fields["seDate"] == "1990-01-01~2026-10-06" for fields in queries)


def test_lookup_screen_filings_pages_until_all_periodic_kinds_are_found(monkeypatch):
    calls = []

    def fake(path, fields):
        calls.append((path, dict(fields)))
        if path.endswith("topSearch/query"):
            return [
                {
                    "code": "600519",
                    "category": "A股",
                    "orgId": "gssh0600519",
                    "delisted": "false",
                }
            ]
        if fields["pageNum"] == "1":
            return {
                "announcements": [
                    _announcement("6005192025年年度报告", "finalpage/2026-04-17/a.pdf", LIVE_ANNOUNCED_MS),
                    _announcement("6005192026年半年度报告", "finalpage/2026-08-15/b.pdf", _ms(date(2026, 8, 15))),
                    _announcement("6005192026年一季度报告", "finalpage/2026-04-25/c.pdf", _ms(date(2026, 4, 25))),
                    *[
                        _announcement(
                            f"600519关于股东大会的通知{index}",
                            f"finalpage/2026-04-17/other-{index}.pdf",
                            LIVE_ANNOUNCED_MS,
                        )
                        for index in range(27)
                    ],
                ],
                "hasMore": True,
            }
        return {
            "announcements": [
                _announcement("6005192025年第三季度报告", "finalpage/2025-10-30/d.pdf", _ms(date(2025, 10, 30)))
            ],
            "hasMore": False,
        }

    monkeypatch.setattr(official_filings, "_post_json", fake)
    found = lookup_screen_filings(["600519"], cutoff=date(2026, 10, 6))

    assert {row["kind"] for row in found["600519"]} == {
        "annual",
        "semiannual",
        "q1",
        "q3",
    }
    pages = [
        fields["pageNum"]
        for path, fields in calls
        if path.endswith("hisAnnouncement/query")
    ]
    assert pages == ["1", "2"]
    assert all(fields["pageSize"] == str(official_filings.ANNOUNCEMENT_PAGE_SIZE) for path, fields in calls if path.endswith("hisAnnouncement/query"))


def test_lookup_screen_filings_stops_at_the_page_budget(monkeypatch):
    calls = []

    def fake(path, fields):
        calls.append((path, dict(fields)))
        if path.endswith("topSearch/query"):
            return [
                {
                    "code": "600519",
                    "category": "A股",
                    "orgId": "gssh0600519",
                    "delisted": "false",
                }
            ]
        return {
            "announcements": [
                _announcement("600519关于召开股东大会的通知", "finalpage/2026-04-17/a.pdf", LIVE_ANNOUNCED_MS)
            ],
            "hasMore": True,
        }

    monkeypatch.setattr(official_filings, "_post_json", fake)
    assert lookup_screen_filings(["600519"], cutoff=date(2026, 10, 6)) == {}
    pages = [
        fields["pageNum"]
        for path, fields in calls
        if path.endswith("hisAnnouncement/query")
    ]
    assert pages == [str(page) for page in range(1, official_filings.MAX_ANNOUNCEMENT_PAGES + 1)]


def test_lookup_annual_filings_pages_past_unusable_rows(monkeypatch):
    calls = []

    def fake(path, fields):
        calls.append((path, dict(fields)))
        if path.endswith("topSearch/query"):
            return [
                {
                    "code": "600519",
                    "category": "A股",
                    "orgId": "gssh0600519",
                    "delisted": "false",
                }
            ]
        if fields["pageNum"] == "1":
            return {
                "announcements": [
                    *[
                        _announcement(
                            f"6005192025年年度报告摘要{index}",
                            f"finalpage/2026-04-17/summary-{index}.pdf",
                            LIVE_ANNOUNCED_MS,
                        )
                        for index in range(30)
                    ]
                ],
                "hasMore": "true",
            }
        return {
            "announcements": [
                _announcement("6005192024年年度报告", "finalpage/2025-04-03/b.pdf", _ms(date(2025, 4, 3)))
            ],
            "hasMore": False,
        }

    monkeypatch.setattr(official_filings, "_post_json", fake)
    found = lookup_annual_filings(["600519"], cutoff=date(2026, 10, 6))

    assert found["600519"]["title"] == "6005192024年年度报告"
    pages = [
        fields["pageNum"]
        for path, fields in calls
        if path.endswith("hisAnnouncement/query")
    ]
    assert pages == ["1", "2"]
