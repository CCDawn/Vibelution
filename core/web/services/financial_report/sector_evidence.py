"""Whitelist current public sector references from the guarded stock tool."""

from __future__ import annotations

import math
import re
from datetime import date, datetime

from core.web.services.financial_market.sectors import _industry_directory_url
from core.web.services.financial_market.tencent import (
    MarketDataError,
    normalize_a_share_symbol,
)
from core.web.services.financial_research.as_of import explicit_iso_date, published_date


def _time(value: object, cutoff: date) -> str | None:
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
        day = published_date(value)
        return value if instant.tzinfo is not None and day is not None and day <= cutoff else None
    except (ValueError, OverflowError):
        return None


def _label(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip() or len(value) > 50:
        return None
    if any(ord(char) < 32 or char in "<>" for char in value):
        return None
    return value


def _number(value: object, *, positive: bool = False) -> bool:
    try:
        return type(value) in {int, float} and math.isfinite(value) and (not positive or value > 0)
    except OverflowError:
        return False


def _quote(value: dict, cutoff: date, url: str, fetched: str) -> dict | None:
    name = _label(value.get("name"))
    timestamp = _time(value.get("timestamp"), cutoff)
    if (name is None or timestamp is None or value.get("sourceUrl") != url
        or not _number(value.get("price"), positive=True) or not _number(value.get("changePercent"))):
        return None
    if datetime.fromisoformat(timestamp.replace("Z", "+00:00")) > datetime.fromisoformat(fetched.replace("Z", "+00:00")):
        return None
    return {"name": name, "price": value["price"], "changePercent": value["changePercent"],
            "timestamp": timestamp, "sourceUrl": url}


def sector_reference(value: object, symbol: str, cutoff: date) -> dict | None:
    if (not isinstance(value, dict) or value.get("status") not in ("available", "partial")
        or value.get("symbol") != symbol or value.get("source") != "东方财富"
        or value.get("sourceUrl") != f"https://quote.eastmoney.com/{symbol}.html"):
        return None
    fetched = _time(value.get("fetchedAt"), cutoff)
    # The classification was observed now; an old quote time never proves
    # the old membership. Only same-day research may consume this context.
    if fetched is None or published_date(fetched) != cutoff:
        return None
    requested = value.get("requestedCutoff")
    if requested is not None and explicit_iso_date(requested) != cutoff:
        return None
    industry = value.get("industry")
    if not isinstance(industry, dict) or industry.get("taxonomy") != "eastmoney":
        return None
    label = _label(industry.get("label"))
    if label is None or industry.get("classificationObservedAt") != fetched:
        return None
    stock_time = _time(industry.get("stockQuoteTimestamp"), cutoff)
    result = {"symbol": symbol, "source": "东方财富", "sourceUrl": value["sourceUrl"],
              "fetchedAt": fetched, "status": "partial", "industry": {
                  "label": label, "taxonomy": "eastmoney", "classificationObservedAt": fetched,
                  "stockQuoteTimestamp": stock_time},
              "synchronous": False, "board": None, "peers": [],
              "conceptCoverage": "unavailable", "historyCoverage": "unavailable",
              "peerCoverage": "unavailable",
              "verification": "untrusted current public sector reference; provider classification; not filing values or historical membership"}
    board = value.get("board")
    if isinstance(board, dict) and isinstance(board.get("code"), str) and re.fullmatch(r"BK[0-9]{1,6}", board["code"]):
        quote = _quote(board, cutoff, _industry_directory_url(), fetched)
        if quote is not None and quote["name"] == label:
            result["board"] = {"code": board["code"], "priceUnit": "points", **quote}
    peers = value.get("peers")
    if isinstance(peers, list) and len(peers) <= 5 and result["board"] is not None:
        seen = set()
        for peer in peers:
            if not isinstance(peer, dict) or not isinstance(peer.get("symbol"), str):
                continue
            try:
                canonical = normalize_a_share_symbol(peer["symbol"])
            except (MarketDataError, ValueError):
                continue
            if canonical != peer["symbol"] or canonical in seen or canonical == symbol:
                continue
            quote = _quote(peer, cutoff, f"https://quote.eastmoney.com/{canonical}.html", fetched)
            if quote is not None:
                seen.add(canonical)
                result["peers"].append({"symbol": canonical, "priceUnit": "CNY/share", **quote})
        if result["peers"]:
            result["peerCoverage"] = "partial"
    return result
