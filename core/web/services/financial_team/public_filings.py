"""Public original-PDF context for analysts; never reads private knowledge ACLs."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone

from core.web.services import financial_market_service as market
from core.web.services.financial_backtest import official_pdf

MAX_REFERENCE_BYTES = 7_000
MAX_PAGES = 4
MAX_PAGE_CHARS = 1_100


def _period_end(value: object) -> date | None:
    match = re.fullmatch(r"(20\d{2})(FY|H1|H2|Q[1-4])", str(value or ""))
    if not match:
        return None
    month, day = {"FY": (12, 31), "H1": (6, 30), "H2": (12, 31),
        "Q1": (3, 31), "Q2": (6, 30), "Q3": (9, 30), "Q4": (12, 31)}[match[2]]
    return date(int(match[1]), month, day)


def _day(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _size(value: dict) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def load_public_filing(symbol: str, cutoff: date) -> dict:
    canonical = market.normalize_a_share_symbol(symbol)
    return market._cached(("team-public-original-v2", canonical, cutoff.isoformat()),
        300, lambda: _load(canonical, cutoff))


def _load(symbol: str, cutoff: date) -> dict:
    result = {"status": "unavailable", "ticker": symbol, "researchDate": cutoff.isoformat(),
        "source": official_pdf.SOURCE, "fetchedAt": datetime.now(timezone.utc).isoformat(),
        "pages": [], "warnings": []}
    try:
        directory = official_pdf.load_periodic_report_notices(symbol, cutoff=cutoff)
        result["warnings"] = list(directory.get("warnings") or [])[:6]
        candidates = []
        for row in directory.get("items") or []:
            if not isinstance(row, dict) or row.get("symbol") != symbol:
                continue
            period = _period_end(row.get("reportPeriod"))
            published = _day(row.get("publishedDate"))
            if period and published and period <= published <= cutoff:
                candidates.append((period, published, str(row.get("noticeCode") or ""), row))
        if not candidates:
            result["warnings"].append("研究日期内未取得可识别报告期的官方完整财报。")
            return result
        latest_period = max(value[0] for value in candidates)
        same_period = [value for value in candidates if value[0] == latest_period]
        originals = [value for value in same_period if value[3].get("versionType") == "original"]
        notice = max(originals or same_period, key=lambda value: value[:3])[3]
        url = official_pdf.validate_official_pdf_url(notice["url"])
        if not url:
            raise official_pdf.OfficialPdfError("非官方原文链接")
        parsed = official_pdf.fetch_and_extract_official_pdf(url)
        result.update({"sourceUrl": url, "title": str(notice["title"])[:240],
            "reportPeriod": notice["reportPeriod"], "publishedDate": notice["publishedDate"],
            "versionType": notice["versionType"], "documentSha256": parsed["documentSha256"],
            "pageCount": parsed["pageCount"], "status": "partial",
            "verification": "public_original_excerpt; not_reviewed; not_export_numeric_authority",
            "historicalAvailability": "disclosure_date_only; retrieved_later_not_archive"})
        result["warnings"] = [*result["warnings"], "仅为有限页码摘录，未覆盖完整财报；未自动审核入库。",
            "原件在本次研究时读取，披露日期不是历史快照存档证明。"]
        revisions = [value[3] for value in same_period if value[3].get("versionType") == "revision_notice"]
        unmapped_revisions = [row for row in directory.get("items") or []
            if isinstance(row, dict) and row.get("symbol") == symbol
            and row.get("versionType") == "unmapped_revision_notice"
            and (published := _day(row.get("publishedDate"))) is not None and published <= cutoff]
        result["revisionCandidates"] = [{key: row.get(key) for key in
            ("title", "url", "publishedDate", "reportPeriod")} for row in revisions[:3]]
        result["unmappedRevisionCandidates"] = [{key: row.get(key) for key in
            ("title", "url", "publishedDate", "reportPeriod")} for row in unmapped_revisions[:3]]
        result["revisionStatus"] = "same_period_candidates" if revisions else (
            "unmapped_candidates" if unmapped_revisions else "none_in_returned_directory")
        if revisions:
            result["warnings"].append("存在修订候选，尚未对照修订内容；不得将原版数字表述为已确认的最新口径。")
        if unmapped_revisions:
            result["warnings"].append("更正公告尚未映射报告期，不能确认是否影响本期；空的同报告期候选不表示没有更正，原版数字不代表已确认的最新口径。")
        result["warnings"].extend(str(value)[:240] for value in (parsed.get("warnings") or [])[:3])
        for page in parsed.get("pages") or []:
            text = str(page.get("excerpt") or "")
            if re.search(r"(?:^|\n)\s*(?:目录|(?:第.{1,5}节\s*)?释义)\s*(?:\n|$)", text):
                continue
            excerpt = text[:MAX_PAGE_CHARS]
            if len(text) > MAX_PAGE_CHARS and "\n" in excerpt:
                excerpt = excerpt.rsplit("\n", 1)[0]
            row = {"page": page["page"], "excerpt": excerpt,
                "excerptSha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest()}
            proposed = {**result, "pages": [*result["pages"], row]}
            if _size(proposed) <= MAX_REFERENCE_BYTES:
                result["pages"].append(row)
            if len(result["pages"]) == MAX_PAGES:
                break
        if not result["pages"]:
            result["status"] = "unavailable"
            result["warnings"].append("没有预算内可读取的原文页。")
        return result
    except (official_pdf.OfficialPdfError, OSError, ValueError, TypeError, KeyError):
        result["status"] = "unavailable"
        result["pages"] = []
        result["warnings"] = ["官方财报读取失败；不以模型内容或当前摘要替代原文。"]
        return result


def public_filing_reference(snapshot: object, symbol: str, cutoff: date) -> dict | None:
    """Recheck cached public context without creating synthetic tool results."""
    if not isinstance(snapshot, dict) or snapshot.get("status") != "partial":
        return None
    if snapshot.get("ticker") != symbol or snapshot.get("researchDate") != cutoff.isoformat():
        return None
    period, published = _period_end(snapshot.get("reportPeriod")), _day(snapshot.get("publishedDate"))
    if not period or not published or not period <= published <= cutoff:
        return None
    try:
        validated_url = official_pdf.validate_official_pdf_url(snapshot.get("sourceUrl"))
        if not validated_url or validated_url != snapshot.get("sourceUrl"):
            return None
    except official_pdf.OfficialPdfError:
        return None
    if not re.fullmatch(r"[a-f0-9]{64}", str(snapshot.get("documentSha256") or "")):
        return None
    pages = snapshot.get("pages")
    page_count = snapshot.get("pageCount")
    if (type(page_count) is not int or not 1 <= page_count <= 100_000
        or not isinstance(pages, list) or not 1 <= len(pages) <= MAX_PAGES):
        return None
    seen = set()
    for row in pages:
        if not isinstance(row, dict):
            return None
        page, excerpt = row.get("page"), row.get("excerpt")
        if (type(page) is not int or not 1 <= page <= page_count or page in seen
            or not isinstance(excerpt, str) or not 0 < len(excerpt) <= MAX_PAGE_CHARS
            or hashlib.sha256(excerpt.encode("utf-8")).hexdigest() != row.get("excerptSha256")):
            return None
        seen.add(page)
    if _size(snapshot) > MAX_REFERENCE_BYTES:
        return None
    return {"source": official_pdf.SOURCE, "type": "public_original_filing_excerpt",
        "content": json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")), "truncated": True}
