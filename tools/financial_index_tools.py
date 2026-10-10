"""Fixed A-share index context, with native research cutoff and bounded JSON."""

from __future__ import annotations

import copy
import json

from core.web.services import financial_market_service as market
from core.web.services.financial_research.as_of import active_cutoff

MAX_RESULT_CHARS = 3_200


def _encode(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def financial_index_context_tool(limit: int = 2) -> str:
    """Read five fixed indices; historical context never falls back to live quotes."""
    if type(limit) is not int or not 2 <= limit <= 20:
        return _encode({"ok": False, "status": "invalid_request", "errorCode": "invalid_limit",
                        "message": "limit 必须为2到20之间的整数。"})
    cutoff = active_cutoff()
    try:
        payload = copy.deepcopy(market.get_index_context(cutoff=cutoff, limit=limit))
        payload["ok"] = payload.get("status") in {"available", "partial"}
        payload["evidenceTrust"] = "untrusted_public_market_data"
        payload["requestedLimit"] = limit
        for item in payload.get("items", []):
            item["omittedCandleCount"] = 0
        # Preserve all five coverage states and source times. Clip only trailing
        # history, never serialize a sliced or invalid JSON tool result.
        encoded = _encode(payload)
        while len(encoded) > MAX_RESULT_CHARS:
            candidates = [item for item in payload.get("items", []) if item.get("candles")]
            if not candidates:
                break
            item = max(candidates, key=lambda row: len(row["candles"]))
            item["candles"].pop(0)
            item["omittedCandleCount"] += 1
            encoded = _encode(payload)
        if len(encoded) <= MAX_RESULT_CHARS:
            return encoded
    except (market.MarketDataError, TypeError, ValueError, KeyError, AttributeError):
        pass
    return _encode({"ok": False, "status": "unavailable", "source": "腾讯财经",
                    "requestedCutoff": cutoff.isoformat() if cutoff else None,
                    "message": "指数数据无法在来源与输出预算内核验，本次未返回指数。"})
