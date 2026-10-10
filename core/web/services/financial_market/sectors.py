"""Bounded, current-only A-share sector context from Eastmoney public quotes."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode

from core.web.services.financial_market.tencent import (
    MarketDataError,
    normalize_a_share_symbol,
)

SOURCE_NAME = "东方财富"
_BASE_URL = "https://push2.eastmoney.com"
_QUOTE_PAGE = "https://quote.eastmoney.com"
_UT = "bd1d9ddb04089700cf9c27f6f7426281"
_BOARD_UT = "7eea3edcaed734bea9cbfc24409ed989"
_STOCK_FIELDS = "f2,f3,f12,f13,f14,f100,f124"
_INDUSTRY_FIELDS = "f2,f3,f12,f14,f86"
_PEER_FIELDS = "f2,f3,f12,f13,f14,f124"
_MAX_RESPONSE_CHARS = 1_000_000
_MAX_RESULT_CHARS = 1_600
_MAX_DIRECTORY_ROWS = 500
_MAX_PEER_ROWS = 6
_MAX_PEERS = 5
_CN_TZ = timezone(timedelta(hours=8))
_SAFE_LABEL = re.compile(r"[\u3400-\u9fff\u2160-\u217fA-Za-z0-9*·（）().\-]{1,40}\Z")
_BOARD_CODE = re.compile(r"BK\d{1,6}\Z")


class SectorDataError(ValueError):
    """A public response could not be validated for sector use."""


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _fetched_at(now: datetime) -> str:
    return now.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _source_page(symbol: str) -> str:
    return f"{_QUOTE_PAGE}/{symbol}.html"


def _secid(symbol: str) -> str:
    market = "1" if symbol.startswith("sh") else "0"
    return f"{market}.{symbol[2:]}"


def _stock_quote_url(symbol: str) -> str:
    query = urlencode(
        {
            "ut": _UT,
            "fltt": "2",
            "secids": _secid(symbol),
            "fields": _STOCK_FIELDS,
        }
    )
    return f"{_BASE_URL}/api/qt/ulist.np/get?{query}"


def _industry_directory_url() -> str:
    query = urlencode(
        {
            "pn": "1",
            "pz": str(_MAX_DIRECTORY_ROWS),
            "fltt": "2",
            "fs": "m:90+t:2",
            "fields": _INDUSTRY_FIELDS,
        }
    )
    return f"{_BASE_URL}/api/qt/clist/get?{query}"


def _peer_url(board_code: str) -> str:
    query = urlencode(
        {
            "pn": "1",
            "pz": str(_MAX_PEER_ROWS),
            "po": "1",
            "np": "1",
            "ut": _BOARD_UT,
            "fltt": "2",
            "invt": "2",
            "fid": "f3",
            "fs": f"b:{board_code}",
            "fields": _PEER_FIELDS,
        }
    )
    return f"{_BASE_URL}/api/qt/clist/get?{query}"


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SectorDataError("duplicate_json_key")
        result[key] = value
    return result


def _payload(raw: object) -> dict:
    if not isinstance(raw, str) or not raw or len(raw) > _MAX_RESPONSE_CHARS:
        raise SectorDataError("response_size_or_type")
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except (ValueError, TypeError, RecursionError) as exc:
        raise SectorDataError("invalid_json") from exc
    if not isinstance(value, dict):
        raise SectorDataError("invalid_payload")
    return value


def _rows(raw: object, *, limit: int) -> tuple[list[dict], int | None]:
    payload = _payload(raw)
    data = payload.get("data")
    if not isinstance(data, dict):
        raise SectorDataError("missing_data")
    values = data.get("diff")
    if isinstance(values, list):
        rows = values
    elif isinstance(values, dict):
        rows = list(values.values())
    else:
        raise SectorDataError("missing_rows")
    if len(rows) > limit or any(not isinstance(row, dict) for row in rows):
        raise SectorDataError("invalid_rows")

    total: int | None = None
    raw_total = data.get("total")
    if type(raw_total) is int and raw_total >= 0:
        total = raw_total
    elif isinstance(raw_total, str) and re.fullmatch(r"\d{1,8}", raw_total):
        total = int(raw_total)
    return rows, total


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not _SAFE_LABEL.fullmatch(value):
        return None
    return value


def _number(value: object, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise SectorDataError("invalid_number")
    if isinstance(value, str) and (not value.strip() or len(value) > 32):
        raise SectorDataError("invalid_number")
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise SectorDataError("invalid_number") from exc
    if not math.isfinite(result) or (positive and result <= 0) or abs(result) > 1_000_000_000:
        raise SectorDataError("invalid_number")
    return result


def _percent(value: object) -> float:
    result = _number(value)
    if abs(result) > 1_000:
        raise SectorDataError("invalid_percent")
    return result


def _timestamp(value: object, *, now: datetime) -> str:
    if type(value) is int:
        epoch = value
    elif isinstance(value, str) and re.fullmatch(r"\d{9,12}", value):
        epoch = int(value)
    else:
        raise SectorDataError("invalid_timestamp")
    if epoch < 946684800 or epoch > int(now.timestamp()):
        raise SectorDataError("timestamp_out_of_range")
    try:
        return datetime.fromtimestamp(epoch, tz=_CN_TZ).isoformat(timespec="seconds")
    except (OverflowError, OSError, ValueError) as exc:
        raise SectorDataError("invalid_timestamp") from exc


def _canonical_symbol(code: object, market: object) -> str | None:
    if not isinstance(code, str) or not re.fullmatch(r"\d{6}", code):
        return None
    market_text = str(market).strip()
    prefix = code[0]
    if market_text == "1" and prefix == "6":
        return "sh" + code
    if market_text == "0" and prefix in {"0", "3"}:
        return "sz" + code
    if market_text in {"0", "2"} and prefix in {"4", "8", "9"}:
        return "bj" + code
    return None


def _parse_stock(raw: object, symbol: str, *, now: datetime) -> tuple[str, str | None]:
    rows, _ = _rows(raw, limit=2)
    if len(rows) != 1:
        raise SectorDataError("stock_quote_not_unique")
    row = rows[0]
    if _canonical_symbol(row.get("f12"), row.get("f13")) != symbol:
        raise SectorDataError("stock_code_mismatch")
    label = _text(row.get("f100"))
    if label is None:
        raise SectorDataError("industry_label_unavailable")
    timestamp = None
    try:
        timestamp = _timestamp(row.get("f124"), now=now)
    except SectorDataError:
        # Keep the current vendor label visible, but never present it as a
        # timestamped point-in-time classification.
        pass
    return label, timestamp


def _parse_directory(raw: object, label: str) -> tuple[list[dict], bool]:
    rows, total = _rows(raw, limit=_MAX_DIRECTORY_ROWS)
    complete = total is not None and total == len(rows) and total <= _MAX_DIRECTORY_ROWS
    matches: list[dict] = []
    for row in rows:
        name = _text(row.get("f14"))
        code = row.get("f12")
        if name == label and isinstance(code, str) and _BOARD_CODE.fullmatch(code):
            matches.append(row)
    return matches, complete


def _parse_board(row: dict, directory_url: str, *, now: datetime) -> dict:
    code = row.get("f12")
    name = _text(row.get("f14"))
    if not isinstance(code, str) or not _BOARD_CODE.fullmatch(code) or name is None:
        raise SectorDataError("invalid_board_identity")
    return {
        "code": code,
        "name": name,
        "price": _number(row.get("f2"), positive=True),
        "changePercent": _percent(row.get("f3")),
        # f86 must be present and valid in this response. Its observation in
        # stock/get does not prove clist supplies it; never substitute f124.
        "timestamp": _timestamp(row.get("f86"), now=now),
        "sourceUrl": directory_url,
    }


def _parse_peers(
    raw: object,
    *,
    requested_symbol: str,
    now: datetime,
) -> tuple[list[dict], str, str]:
    rows, total = _rows(raw, limit=_MAX_PEER_ROWS)
    if total is None or total < len(rows) or len(rows) != min(total, _MAX_PEER_ROWS):
        response_complete = False
    else:
        response_complete = True

    peers: list[dict] = []
    seen: set[str] = set()
    invalid_row = False
    for row in rows:
        symbol = _canonical_symbol(row.get("f12"), row.get("f13"))
        if symbol is None:
            invalid_row = True
            continue
        if symbol in seen:
            raise SectorDataError("duplicate_peer")
        seen.add(symbol)
        if symbol == requested_symbol:
            continue
        try:
            name = _text(row.get("f14"))
            if name is None:
                raise SectorDataError("invalid_peer_name")
            peer = {
                "symbol": symbol,
                "name": name,
                "price": _number(row.get("f2"), positive=True),
                "changePercent": _percent(row.get("f3")),
                "timestamp": _timestamp(row.get("f124"), now=now),
                "sourceUrl": _source_page(symbol),
            }
        except SectorDataError:
            invalid_row = True
            continue
        if len(peers) < _MAX_PEERS:
            peers.append(peer)

    expected = min(_MAX_PEERS, max((total or 0) - 1, 0))
    if not response_complete or invalid_row:
        return peers, "partial", "peer_rows_incomplete"
    if len(peers) < expected:
        return peers, ("partial" if peers else "unavailable"), "peer_quotes_incomplete"
    if not peers:
        return peers, "available", "no_peer_members"
    if total is not None and total > _MAX_PEER_ROWS:
        return peers, "partial", "bounded_member_sample"
    return peers, "available", ""


def _coverage(status: str, reason_code: str) -> dict[str, object]:
    result = {"status": status}
    if reason_code:
        result["reasonCode"] = reason_code
    return result


def _result(
    *,
    symbol: str | None,
    fetched_at: str,
    requested_cutoff: str | None,
    status: str,
    reason_code: str,
    industry: dict | None = None,
    board: dict | None = None,
    peers: list[dict] | None = None,
    peer_coverage: dict | None = None,
) -> dict:
    normalized_symbol = symbol or ""
    result = {
        "status": status,
        "symbol": normalized_symbol,
        "source": SOURCE_NAME,
        "sourceUrl": _source_page(normalized_symbol) if normalized_symbol else _QUOTE_PAGE + "/",
        "fetchedAt": fetched_at,
        "requestedCutoff": requested_cutoff,
        "industry": industry,
        "board": board,
        "peers": peers or [],
        "conceptCoverage": _coverage("unavailable", "not_implemented"),
        "peerCoverage": peer_coverage or _coverage("unavailable", "peer_coverage_not_loaded"),
        "historyCoverage": _coverage("unavailable", "unsupported"),
    }
    if reason_code not in {"partial", "coverage_partial"}:
        result["reasonCode"] = reason_code
    return result


def _bounded(result: dict) -> dict:
    while len(json.dumps(result, ensure_ascii=False, separators=(",", ":"))) > _MAX_RESULT_CHARS and result["peers"]:
        result["peers"].pop()
        result["peerCoverage"] = _coverage("partial", "peer_output_limit")
        if result["peers"]:
            result["peerCoverage"]["synchronous"] = False
        result["status"] = "partial"
        result["reasonCode"] = "peer_output_limit"
    if len(json.dumps(result, ensure_ascii=False, separators=(",", ":"))) > _MAX_RESULT_CHARS:
        return _result(
            symbol=result["symbol"] or None,
            fetched_at=result["fetchedAt"],
            requested_cutoff=result.get("requestedCutoff"),
            status="unavailable",
            reason_code="output_limit",
        )
    return result


def _load_current_context(
    normalized: str,
    *,
    now: datetime,
    fetched_at: str,
    requested_cutoff: str | None,
    read: Callable[[str], str],
    cached: Callable[[tuple, int, Callable], object],
) -> dict:
    stock_url = _stock_quote_url(normalized)
    try:
        stock_raw = cached(
            ("eastmoney-sector-stock", normalized),
            30,
            lambda: read(stock_url),
        )
        industry_label, stock_quote_timestamp = _parse_stock(stock_raw, normalized, now=now)
    except (SectorDataError, MarketDataError, OSError, TimeoutError, TypeError, ValueError, RuntimeError):
        return _result(
            symbol=normalized,
            fetched_at=fetched_at,
            requested_cutoff=requested_cutoff,
            status="unavailable",
            reason_code="stock_quote_unavailable",
        )

    industry = {
        "label": industry_label,
        "taxonomy": "eastmoney",
        "stockQuoteTimestamp": stock_quote_timestamp,
        "classificationObservedAt": fetched_at,
    }
    result = _result(
        symbol=normalized,
        fetched_at=fetched_at,
        requested_cutoff=requested_cutoff,
        status="partial",
        reason_code="coverage_partial",
        industry=industry,
    )
    if stock_quote_timestamp is None:
        result["reasonCode"] = "stock_quote_timestamp_unavailable"

    directory_url = _industry_directory_url()
    try:
        directory_raw = cached(
            ("eastmoney-sector-industry-directory",),
            300,
            lambda: read(directory_url),
        )
        matches, directory_complete = _parse_directory(directory_raw, industry_label)
    except (SectorDataError, MarketDataError, OSError, TimeoutError, TypeError, ValueError, RuntimeError):
        result["reasonCode"] = "industry_directory_unavailable"
        return result

    if not directory_complete:
        result["reasonCode"] = "industry_directory_incomplete"
        return result
    if len(matches) != 1:
        result["reasonCode"] = "industry_board_ambiguous" if matches else "industry_board_not_found"
        return result

    board_row = matches[0]
    board_code = board_row.get("f12")
    if not isinstance(board_code, str) or not _BOARD_CODE.fullmatch(board_code):
        result["reasonCode"] = "industry_board_code_invalid"
        return result
    try:
        result["board"] = _parse_board(board_row, directory_url, now=now)
    except SectorDataError:
        # An unverified board price or f86 timestamp suppresses the board
        # quote. Member rows remain separately validated and timestamped.
        result["reasonCode"] = "board_quote_unavailable"

    peer_url = _peer_url(board_code)
    try:
        peer_raw = cached(
            ("eastmoney-sector-peers", board_code),
            60,
            lambda: read(peer_url),
        )
        peers, peer_status, peer_reason = _parse_peers(
            peer_raw,
            requested_symbol=normalized,
            now=now,
        )
        result["peers"] = peers
        result["peerCoverage"] = _coverage(peer_status, peer_reason)
        if peers:
            result["peerCoverage"]["synchronous"] = False
        if peer_status != "available" and result.get("reasonCode", "partial") in {"coverage_partial", "partial"}:
            result["reasonCode"] = peer_reason
    except (SectorDataError, MarketDataError, OSError, TimeoutError, TypeError, ValueError, RuntimeError):
        result["peerCoverage"] = _coverage("unavailable", "peer_data_unavailable")
        if result.get("reasonCode", "partial") in {"coverage_partial", "partial"}:
            result["reasonCode"] = "peer_data_unavailable"

    # Current tags and peers are not a point-in-time backtest universe. The
    # concepts/history gaps keep the overall result visibly partial.
    result["status"] = "partial"
    if result.get("reasonCode") == "coverage_partial":
        result["reasonCode"] = "partial"
    return result


def get_sector_context(
    symbol: str,
    *,
    cutoff: date | None = None,
    read: Callable[[str], str],
    cached: Callable[[tuple, int, Callable], object],
) -> dict:
    """Return only current Eastmoney A-share sector context.

    Historical and non-current cutoffs fail closed before any read. The stock
    quote's f100 is a vendor label observed now; its f124 time describes the
    stock quote and is not a historical industry-membership claim. A final
    Shanghai-date check prevents reads crossing midnight from leaking a new
    day's classification into the request.
    """

    now = _now_utc()
    fetched_at = _fetched_at(now)
    try:
        normalized = normalize_a_share_symbol(symbol)
    except (MarketDataError, TypeError, ValueError):
        return _bounded(
            _result(
                symbol=None,
                fetched_at=fetched_at,
                requested_cutoff=cutoff.isoformat() if type(cutoff) is date else None,
                status="unavailable",
                reason_code="invalid_a_share_symbol",
            )
        )

    requested_cutoff = cutoff.isoformat() if type(cutoff) is date else None
    china_today = now.astimezone(_CN_TZ).date()
    if cutoff is not None and (type(cutoff) is not date or cutoff != china_today):
        return _bounded(
            _result(
                symbol=normalized,
                fetched_at=fetched_at,
                requested_cutoff=requested_cutoff,
                status="unavailable",
                reason_code="cutoff_outside_realtime_window",
            )
        )

    result = _load_current_context(
        normalized,
        now=now,
        fetched_at=fetched_at,
        requested_cutoff=requested_cutoff,
        read=read,
        cached=cached,
    )
    completed_at = _now_utc()
    if completed_at.astimezone(_CN_TZ).date() != china_today:
        result = _result(
            symbol=normalized,
            fetched_at=_fetched_at(completed_at),
            requested_cutoff=requested_cutoff,
            status="unavailable",
            reason_code="china_date_changed_during_read",
        )
    return _bounded(result)


__all__ = ["SectorDataError", "get_sector_context"]
