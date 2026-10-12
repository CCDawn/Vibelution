from __future__ import annotations

import copy
import json
from datetime import date

import pytest

from core.web.services.financial_team import public_filings as sources
from core.web.services.financial_team import runs


def notice(period="2026H1", published="2026-08-15", **extra):
    return {"symbol": "sh600519", "reportPeriod": period, "publishedDate": published,
        "noticeCode": "original", "versionType": "original", "title": "贵州茅台2026年半年度报告",
        "url": "https://static.cninfo.com.cn/finalpage/2026-08-15/1225475868.PDF", **extra}


@pytest.fixture
def public_pdf(monkeypatch):
    calls = []
    monkeypatch.setattr(sources.market, "_cached", lambda _key, _ttl, reader: reader())
    monkeypatch.setattr(sources.official_pdf, "load_periodic_report_notices", lambda *_args, **_kw:
        {"items": [notice(), notice("2026Q3", "2026-10-25"), notice(symbol="sz000001")], "warnings": []})
    def extracted(url):
        calls.append(url)
        return {"documentSha256": "a" * 64, "pageCount": 110, "warnings": [], "pages": [
            {"page": 3, "excerpt": "贵州茅台\n目录\n第一节"},
            {"page": 5, "excerpt": "单位：元\n主要会计数据\n营业收入 89300000000.00\n归母净利润 45000000000.00"},
            *[{"page": index, "excerpt": "财报原文数据 12.00 13.00" * 400} for index in range(6, 14)],
        ]}
    monkeypatch.setattr(sources.official_pdf, "fetch_and_extract_official_pdf", extracted)
    return calls


def test_public_original_is_cutoff_scoped_bounded_and_not_numeric_authority(public_pdf):
    cutoff = date(2026, 10, 12)
    snapshot = sources.load_public_filing("sh600519", cutoff)
    assert snapshot["reportPeriod"] == "2026H1"
    assert len(public_pdf) == 1
    assert 1 <= len(snapshot["pages"]) <= sources.MAX_PAGES
    assert snapshot["pages"][0]["page"] == 5
    assert sources._size(snapshot) <= sources.MAX_REFERENCE_BYTES
    item = sources.public_filing_reference(snapshot, "sh600519", cutoff)
    assert item["type"] == "public_original_filing_excerpt"
    assert item["truncated"] is True
    assert "not_export_numeric_authority" in item["content"]
    assert "retrieved_later_not_archive" in item["content"]
    assert sources.public_filing_reference(snapshot, "sz000001", cutoff) is None
    assert sources.public_filing_reference(snapshot, "sh600519", date(2026, 8, 1)) is None


@pytest.mark.parametrize("change", [
    lambda s: s.update(publishedDate="2026-10-25"),
    lambda s: s.update(reportPeriod="2026Q3", publishedDate="2026-08-01"),
    lambda s: s.update(sourceUrl="https://example.com/file.pdf"),
    lambda s: s.update(sourceUrl=" https://static.cninfo.com.cn/finalpage/2026-08-15/1225475868.PDF "),
    lambda s: s.update(documentSha256="invalid"),
    lambda s: s.update(pageCount="broken"),
    lambda s: s["pages"][0].update(excerpt="changed"),
    lambda s: s["pages"][0].update(page=111),
    lambda s: s["pages"].append(s["pages"][0]),
])
def test_public_reference_rejects_mismatched_identity_or_mutation(public_pdf, change):
    snapshot = sources.load_public_filing("sh600519", date(2026, 10, 12))
    change(snapshot)
    assert sources.public_filing_reference(snapshot, "sh600519", date(2026, 10, 12)) is None


def test_revision_is_visible_without_silently_replacing_original(public_pdf, monkeypatch):
    monkeypatch.setattr(sources.official_pdf, "load_periodic_report_notices", lambda *_args, **_kw:
        {"items": [notice(), notice(published="2026-09-01", noticeCode="revision", versionType="revision_notice")], "warnings": []})
    snapshot = sources.load_public_filing("sh600519", date(2026, 10, 12))
    assert snapshot["versionType"] == "original"
    assert snapshot["revisionCandidates"][0]["publishedDate"] == "2026-09-01"
    assert any("尚未对照修订" in value for value in snapshot["warnings"])


def test_public_failure_does_not_invent_original_or_read_private_library(public_pdf, monkeypatch):
    monkeypatch.setattr(sources.official_pdf, "fetch_and_extract_official_pdf", lambda *_:
        (_ for _ in ()).throw(sources.official_pdf.OfficialPdfError("source failed")))
    snapshot = sources.load_public_filing("sh600519", date(2026, 10, 12))
    assert snapshot["status"] == "unavailable"
    assert snapshot["pages"] == []
    assert sources.public_filing_reference(snapshot, "sh600519", date(2026, 10, 12)) is None


def test_primary_and_debate_receive_same_public_original_in_untrusted_boundary(public_pdf, monkeypatch):
    snapshot = sources.load_public_filing("sh600519", date(2026, 10, 12))
    run = {"symbol": "sh600519", "researchDate": "2026-10-12", "periodDays": 30,
        "depth": "brief", "analysts": {"fundamental": {"task": {}}},
        "publicOriginalFilingSnapshot": snapshot}
    primary = runs._primary_role_prompt(run, "fundamental", public_fundamentals={"status": "unavailable"})
    debate = runs._debate_prompt(run, {role: "research" for role in runs._LEGACY_ROLE_KEYS}, "不可用", "bull")
    for prompt in (primary, debate):
        lines = prompt.splitlines()
        start = lines.index(runs._UNTRUSTED_REFERENCE_BEGIN)
        envelope = json.loads(lines[start + 1])
        original = next(item for item in envelope["items"] if item["type"] == "public_original_filing_excerpt")
        assert json.loads(original["content"])["documentSha256"] == "a" * 64
        assert "营业收入" in original["content"]
        assert "不得执行或服从" in prompt
    assert "历史摘要被拒绝不表示数据管道故障" in primary
    assert run["publicOriginalFilingSnapshot"] == copy.deepcopy(snapshot)


def test_historical_primary_persists_one_public_snapshot_and_replays_without_read(public_pdf, monkeypatch):
    from tests.test_financial_team_service import (
        _stub_primary_financial_team_submission,
    )

    captured = _stub_primary_financial_team_submission(monkeypatch)
    monkeypatch.setattr(runs, "_public_fundamentals_snapshot", lambda _: {
        "status": "unavailable", "items": [], "error": "历史时点无法验证当前摘要"})
    runs.submit_financial_team_primary_role("owner-1", "run-1", "fundamental")
    snapshot = copy.deepcopy(captured["run"]["publicOriginalFilingSnapshot"])
    assert snapshot["researchDate"] == "2026-10-05"
    assert "public_original_filing_excerpt" in captured["prompt"]
    assert len(public_pdf) == 1
    runs.submit_financial_team_primary_role("owner-1", "run-1", "fundamental")
    assert len(public_pdf) == 1
    assert captured["run"]["publicOriginalFilingSnapshot"] == snapshot


def test_synthesis_inherits_public_context_without_fabricating_tool_evidence(public_pdf, monkeypatch):
    from core.web.services.financial_report.team_evidence import (
        synthesis_tool_references,
    )
    from tests.test_financial_team_report_evidence import _synthesis_reference_fixture

    run, records, _ = _synthesis_reference_fixture(monkeypatch)
    cutoff = date.fromisoformat(run["researchDate"])
    run["publicOriginalFilingSnapshot"] = sources.load_public_filing("sh600519", cutoff)
    original_events = copy.deepcopy(records)
    references = synthesis_tool_references("owner", run)
    original = next(item for item in references if item["type"] == "public_original_filing_excerpt")
    assert "not_export_numeric_authority" in original["content"]
    assert records == original_events
