"""Project dated original index tool data into untrusted team references."""

from __future__ import annotations

import json
import math
from datetime import date, datetime

from core.web.services.financial_market.indices import INDEX_NAMES
from core.web.services.financial_research.as_of import explicit_iso_date, published_date

TOOL_NAME = "financial_index_context_tool"


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate index evidence key")
        result[key] = value
    return result


def _number(value: object, *, positive: bool = False) -> bool:
    try:
        return (type(value) in {int, float} and math.isfinite(value)
                and (not positive or value > 0))
    except OverflowError:
        return False


def index_reference(output: str, status: str, cutoff: date) -> dict | None:
    if not isinstance(output, str) or not isinstance(status, str):
        return None
    if status.lower() not in {"completed", "success", "partial", "degraded", "done", "succeeded"}:
        return None
    if len(output.encode("utf-8", errors="replace")) > 32_000:
        return None
    try:
        payload = json.loads(output, object_pairs_hook=_unique_object)
    except (TypeError, ValueError, RecursionError):
        return None
    if (not isinstance(payload, dict) or payload.get("ok") is not True
        or payload.get("source") != "腾讯财经" or payload.get("status") not in ("available", "partial")
        or payload.get("priceUnit") != "points" or payload.get("adjustment") != "raw_index"
        or not isinstance(payload.get("items"), list) or len(payload["items"]) > 5):
        return None
    requested = payload.get("requestedCutoff")
    if requested is not None:
        requested_day = explicit_iso_date(requested)
        if requested_day is None or requested_day > cutoff:
            return None
    items = []
    coverage = []
    seen = set()
    for row in payload["items"]:
        if not isinstance(row, dict) or not isinstance(row.get("symbol"), str) or row["symbol"] not in INDEX_NAMES:
            return None
        symbol = row["symbol"]
        if symbol in seen:
            return None
        seen.add(symbol)
        if row.get("status") not in ("available", "partial", "unavailable"):
            return None
        coverage.append({"symbol": symbol, "status": row.get("status")})
        quote = row.get("quote")
        if row.get("status") not in ("available", "partial") or not isinstance(quote, dict):
            continue
        basis = row.get("basis")
        if basis not in ("quote", "daily_close"):
            continue
        if row.get("sourceUrl") != f"https://gu.qq.com/{symbol}/gp":
            continue
        observation = quote.get("timestamp") or quote.get("date")
        try:
            observed_day = published_date(observation)
        except OverflowError:
            continue
        if (observed_day is None or observed_day > (explicit_iso_date(requested) if requested else cutoff)
            or not _number(quote.get("price"), positive=True)):
            continue
        if basis == "daily_close" and (quote.get("timestamp") or explicit_iso_date(quote.get("date")) is None):
            continue
        if basis == "quote" and not quote.get("timestamp"):
            continue
        if quote.get("timestamp"):
            if not isinstance(quote["timestamp"], str):
                continue
            try:
                if datetime.fromisoformat(quote["timestamp"].replace("Z", "+00:00")).tzinfo is None:
                    continue
            except (TypeError, ValueError):
                continue
        projected_quote = {"price": quote["price"]}
        for key in ("previousClose", "open", "high", "low", "change", "changePercent"):
            value = quote.get(key)
            if value is not None:
                if not _number(value, positive=key in {"previousClose", "open", "high", "low"}):
                    break
                projected_quote[key] = value
        else:
            if all(key in projected_quote for key in ("open", "high", "low")) and not (
                projected_quote["low"] <= min(projected_quote["open"], projected_quote["price"])
                <= max(projected_quote["open"], projected_quote["price"]) <= projected_quote["high"]
            ):
                continue
            projected_quote["timestamp" if quote.get("timestamp") else "date"] = observation
            candles = row.get("candles", [])
            if not isinstance(candles, list) or len(candles) > 20:
                continue
            valid_bars = []
            prior = None
            for bar in candles:
                if not isinstance(bar, dict):
                    break
                day = explicit_iso_date(bar.get("date"))
                if day is None or day > observed_day or (prior is not None and day <= prior):
                    break
                if not all(_number(bar.get(key), positive=True) for key in ("open", "close", "high", "low")):
                    break
                if not bar["low"] <= min(bar["open"], bar["close"]) <= max(bar["open"], bar["close"]) <= bar["high"]:
                    break
                valid_bars.append({key: bar[key] for key in ("date", "open", "close", "high", "low")})
                prior = day
            else:
                if basis == "daily_close" and valid_bars and (
                    valid_bars[-1]["date"] != quote["date"] or valid_bars[-1]["close"] != quote["price"]
                ):
                    continue
                omitted = row.get("omittedCandleCount", 0)
                if type(omitted) is not int or omitted < 0:
                    continue
                items.append({"symbol": symbol, "name": INDEX_NAMES[symbol],
                              "sourceUrl": row["sourceUrl"], "priceUnit": "points",
                              "basis": basis, "quote": projected_quote,
                              "candles": valid_bars[-5:],
                              "omittedCandleCount": omitted + max(0, len(valid_bars) - 5)})
    if not items:
        return None
    return {"source": "腾讯财经", "researchDate": cutoff.isoformat(), "items": items,
            "coverage": coverage, "sectorCoverage": "unavailable",
            "verification": "dated original index tool output; untrusted public reference; not audited filing values"}
