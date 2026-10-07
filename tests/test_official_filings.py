import json
from datetime import date, datetime
from urllib.request import Request
from zoneinfo import ZoneInfo

import pytest

from core.web.services.financial_research import official_filings
from core.web.services.financial_research.official_filings import (
    ANNUAL_CATEGORY,
    FILING_SOURCE,
    REQUEST_TIMEOUT_SECONDS,
    OfficialFilingLookupError,
    accepted_annual_filing,
    lookup_annual_filings,
    mentions_annual_report,
)


def test_mentions_annual_report_includes_summaries_and_spaced_titles():
    assert mentions_annual_report("贵州茅台2025年年度报告")
    assert mentions_annual_report("贵州茅台2025年年度报告摘要")
    assert mentions_annual_report("年 度 报 告")
    assert mentions_annual_report("年度报告") is True
    assert not mentions_annual_report("关于召开股东大会的通知")
    assert not mentions_annual_report(None)


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
    assert accepted_annual_filing({**good, "url": "https://user@static.cninfo.com.cn/finalpage/2026-04-17/1.PDF"}, cutoff=None) is None
    assert accepted_annual_filing({**good, "url": "http://static.cninfo.com.cn/finalpage/2026-04-17/1.PDF"}, cutoff=None) is None
    assert accepted_annual_filing({**good, "url": PDF + "?download=1"}, cutoff=None) is None
