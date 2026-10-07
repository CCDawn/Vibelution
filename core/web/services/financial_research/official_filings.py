"""Read one cninfo annual-report identity for an A-share.

Screening and the stock announcement list both use this lookup. The public
query returns a title, announcement day, and PDF URL. It does not return an
interior page. A missing day, a filing after an explicit cutoff, a summary,
or any URL outside the exchange document hosts is omitted. Lookup failures
stay empty so the caller still returns.
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import date, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

CNINFO_ORIGIN = "https://www.cninfo.com.cn"
CNINFO_PDF_ORIGIN = "https://static.cninfo.com.cn"
ANNUAL_CATEGORY = "category_ndbg_szsh"
FILING_SOURCE = "巨潮资讯"
REQUEST_TIMEOUT_SECONDS = 3
LOOKUP_DEADLINE_SECONDS = 8
MAX_RESPONSE_BYTES = 256 * 1024
MAX_FILING_LOOKUPS = 20
_MIN_ANNOUNCED_MS = 631152000000
_MAX_ANNOUNCED_MS = 4102444800000
_A_SHARE = re.compile(r"(?<!\d)([036489]\d{5})(?!\d)")
_ORG_ID = re.compile(r"^g(?:ssh|ssz|fbj)[0-9]{6,12}$")
_ADJUNCT = re.compile(r"^finalpage/(\d{4}-\d{2}-\d{2})/[A-Za-z0-9][A-Za-z0-9._-]{0,64}\.pdf$", re.IGNORECASE)
_PATHS = {
    "/new/information/topSearch/query",
    "/new/hisAnnouncement/query",
}
_COLUMNS = {"gssh": "sse", "gssz": "szse", "gfbj": "bj"}
_FILING_HOSTS = {
    "static.cninfo.com.cn",
    "www.cninfo.com.cn",
    "www.sse.com.cn",
    "static.sse.com.cn",
    "query.sse.com.cn",
    "www.szse.cn",
    "disc.static.szse.cn",
    "www.bse.cn",
}
_BLOCKED_TITLE = ("摘要", "英文", "取消", "更正", "补充")
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Origin": CNINFO_ORIGIN,
    "Referer": f"{CNINFO_ORIGIN}/new/commonUrl/pageOfSearch?url=disclosure/list/search",
    "X-Requested-With": "XMLHttpRequest",
}


class OfficialFilingLookupError(Exception):
    """A cninfo read failed closed. The message stays generic."""


def annual_filing_code(value: object) -> str:
    if not isinstance(value, str):
        return ""
    match = _A_SHARE.search(value)
    return match.group(1) if match else ""


def mentions_annual_report(value: object) -> bool:
    """True when a notice title is an annual report, including a summary."""

    if not isinstance(value, str):
        return False
    return "年度报告" in re.sub(r"\s+", "", value)


def accepted_annual_filing(value: object, *, cutoff: date | None) -> dict[str, str] | None:
    """Return a compact annual-report identity, or None when it cannot be shown."""

    if not isinstance(value, dict):
        return None
    title = _filing_title(value.get("title"))
    url = _allowed_document_url(value.get("url"))
    announced = _iso_day(value.get("announcedOn"))
    if not title or not url or announced is None:
        return None
    if cutoff is not None and announced > cutoff:
        return None
    record = {"title": title, "url": url, "announcedOn": announced.isoformat()}
    if value.get("source") == FILING_SOURCE:
        record["source"] = FILING_SOURCE
    return record


def lookup_annual_filings(tickers: list[object], *, cutoff: date | None = None) -> dict[str, dict[str, str]]:
    """Look up the latest full annual report for each A-share code.

    At most 20 codes are queried. Each read times out, and the whole batch
    stops waiting after a few seconds. Missing and failed codes are absent.
    """

    codes: list[str] = []
    seen: set[str] = set()
    for raw in tickers:
        code = annual_filing_code(raw)
        if not code or code in seen:
            continue
        seen.add(code)
        codes.append(code)
        if len(codes) >= MAX_FILING_LOOKUPS:
            break
    if not codes:
        return {}
    found: dict[str, dict[str, str]] = {}
    pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="cninfo-filing")
    try:
        futures = {pool.submit(_lookup_one, code, cutoff): code for code in codes}
        done, pending = wait(futures, timeout=LOOKUP_DEADLINE_SECONDS)
        for future in pending:
            future.cancel()
        for future in done:
            code = futures[future]
            try:
                filing = future.result()
            except Exception:
                filing = None
            if isinstance(filing, dict):
                found[code] = filing
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    return found


def _lookup_one(code: str, cutoff: date | None) -> dict[str, str] | None:
    try:
        searched = _post_json("/new/information/topSearch/query", {"keyWord": code})
        located = _org_and_column(searched, code)
        if located is None:
            return None
        org_id, column = located
        payload = _post_json("/new/hisAnnouncement/query", _announcement_fields(code, org_id, column, cutoff))
    except Exception:
        return None
    return _select_filing(payload, code, cutoff)


def _announcement_fields(code: str, org_id: str, column: str, cutoff: date | None) -> dict[str, str]:
    return {
        "pageNum": "1",
        "pageSize": "30",
        "column": column,
        "tabName": "fulltext",
        "plate": "",
        "stock": f"{code},{org_id}",
        "searchkey": "",
        "secid": "",
        "category": ANNUAL_CATEGORY,
        "trade": "",
        "seDate": f"1990-01-01~{cutoff.isoformat()}" if cutoff is not None else "",
        "sortName": "",
        "sortType": "",
        "isHLtitle": "true",
    }


def _org_and_column(payload: object, code: str) -> tuple[str, str] | None:
    if not isinstance(payload, list):
        return None
    matches: list[tuple[bool, str]] = []
    for row in payload:
        if not isinstance(row, dict) or str(row.get("code") or "").strip() != code:
            continue
        if row.get("category") != "A股":
            continue
        org_id = row.get("orgId")
        if not isinstance(org_id, str) or _ORG_ID.fullmatch(org_id) is None:
            continue
        matches.append((_is_delisted(row), org_id))
    if not matches:
        return None
    matches.sort(key=lambda item: item[0])
    org_id = matches[0][1]
    column = _COLUMNS.get(org_id[:4])
    if column is None:
        return None
    return org_id, column


def _select_filing(payload: object, code: str, cutoff: date | None) -> dict[str, str] | None:
    if not isinstance(payload, dict) or not isinstance(payload.get("announcements"), list):
        return None
    best: tuple[date, str, str] | None = None
    for row in payload["announcements"][:30]:
        if not isinstance(row, dict) or str(row.get("secCode") or "").strip() != code:
            continue
        title = _filing_title(row.get("announcementTitle"))
        url = _document_url(row.get("adjunctUrl"))
        announced = _epoch_day(row.get("announcementTime"))
        if not title or not url or announced is None:
            continue
        if cutoff is not None and announced > cutoff:
            continue
        if best is None or announced > best[0]:
            best = (announced, title, url)
    if best is None:
        return None
    return accepted_annual_filing(
        {"title": best[1], "url": best[2], "announcedOn": best[0].isoformat(), "source": FILING_SOURCE},
        cutoff=cutoff,
    )


def _post_json(path: str, fields: dict[str, str]) -> Any:
    if path not in _PATHS:
        raise OfficialFilingLookupError("unexpected path")
    clean: dict[str, str] = {}
    for key, value in fields.items():
        if not isinstance(key, str) or not isinstance(value, str) or any(ord(char) < 32 for char in key + value):
            raise OfficialFilingLookupError("unexpected field")
        clean[key] = value
    request = Request(
        CNINFO_ORIGIN + path,
        data=urlencode(clean).encode("utf-8"),
        headers=_HEADERS,
        method="POST",
    )
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            final = urlsplit(response.geturl())
            if final.scheme != "https" or (final.hostname or "").lower() != "www.cninfo.com.cn":
                raise OfficialFilingLookupError("unexpected host")
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except OfficialFilingLookupError:
        raise
    except HTTPError as exc:
        exc.close()
        raise OfficialFilingLookupError("http") from exc
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise OfficialFilingLookupError("read") from exc
    if len(body) > MAX_RESPONSE_BYTES:
        raise OfficialFilingLookupError("response too large")
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise OfficialFilingLookupError("invalid json") from exc


def _document_url(value: object) -> str:
    if not isinstance(value, str):
        return ""
    match = _ADJUNCT.fullmatch(value.strip())
    if match is None:
        return ""
    try:
        date.fromisoformat(match.group(1))
    except ValueError:
        return ""
    return _allowed_document_url(f"{CNINFO_PDF_ORIGIN}/{value.strip()}")


def _allowed_document_url(value: object) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if not text or len(text) > 240 or any(char.isspace() for char in text) or ".." in text or "\\" in text:
        return ""
    parsed = urlsplit(text)
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.query
        or parsed.fragment
        or host not in _FILING_HOSTS
        or not parsed.path.lower().endswith(".pdf")
    ):
        return ""
    return text


def _filing_title(value: object) -> str:
    if not isinstance(value, str):
        return ""
    text = re.sub(r"<[^>]{0,80}>", "", value)
    text = text.replace("|", " ").replace("[", " ").replace("]", " ").replace("(", "（").replace(")", "）")
    text = re.sub(r"[\r\n]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text or len(text) > 80 or "年度报告" not in text:
        return ""
    if any(word in text for word in _BLOCKED_TITLE):
        return ""
    return text


def _iso_day(value: object) -> date | None:
    if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _epoch_day(value: object) -> date | None:
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    if type(value) is not int or not _MIN_ANNOUNCED_MS <= value <= _MAX_ANNOUNCED_MS:
        return None
    try:
        announced = datetime.fromtimestamp(value / 1000, _SHANGHAI).date()
    except (OverflowError, OSError, ValueError):
        return None
    if announced.year < 1990 or announced.year > 2100:
        return None
    return announced


def _is_delisted(row: dict) -> bool:
    value = row.get("delisted")
    return value is True or str(value).strip().lower() == "true"
