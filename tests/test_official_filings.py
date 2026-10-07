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


def test_lookup_prefers_the_full_annual_report_and_the_exchange_column(monkeypatch):
    calls = []

    def fake(path, fields):
        calls.append((path, dict(fields)))
        if path.endswith("topSearch/query"):
            orgs = {"600519": "gssh0600519", "000001": "gssz0000001", "830799": "gfbj0830799"}
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
    found = lookup_annual_filings(["sh600519", "000001", "830799", "1600519", "600519"], cutoff=date(2026, 10, 6))

    assert set(found) == {"600519", "000001", "830799"}
    assert found["600519"] == {
        "title": "6005192025年年度报告",
        "url": PDF,
        "announcedOn": "2026-04-17",
        "source": FILING_SOURCE,
    }
    columns = {fields["stock"].split(",", 1)[0]: fields["column"] for path, fields in calls if path.endswith("hisAnnouncement/query")}
    assert columns == {"600519": "sse", "000001": "szse", "830799": "bj"}
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
