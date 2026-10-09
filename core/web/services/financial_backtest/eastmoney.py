"""Bounded raw/qfq Eastmoney daily windows with explicit request adjustment."""
from __future__ import annotations

import json
from datetime import date
from urllib.parse import urlencode

from .transport import HistoricalReadError, read_historical


def fetch_window(symbol: str, start: date, end: date, adjustment: str) -> list[list[str]]:
    from .data import BacktestDataError

    if adjustment not in {"none", "qfq"}:
        raise BacktestDataError("东方财富复权模式无效")
    market_id = 1 if symbol.startswith("sh") else 0
    code = symbol[2:]
    params = {
        "secid": f"{market_id}.{code}", "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56", "klt": "101",
        "fqt": "1" if adjustment == "qfq" else "0",
        "beg": start.strftime("%Y%m%d"), "end": end.strftime("%Y%m%d"), "lmt": "640",
    }
    context = f"{symbol} {start.isoformat()}至{end.isoformat()} · {adjustment}"
    try:
        raw = read_historical("https://push2his.eastmoney.com/api/qt/stock/kline/get?" + urlencode(params))
        payload = json.loads(raw)
    except HistoricalReadError as exc:
        raise BacktestDataError(f"东方财富历史日K读取失败（{context}）：{exc}") from exc
    except (TypeError, json.JSONDecodeError) as exc:
        raise BacktestDataError(f"东方财富历史日K格式无效（{context}）") from exc
    if not isinstance(payload, dict) or type(payload.get("rc")) is not int or payload["rc"] != 0:
        raise BacktestDataError(f"东方财富历史日K状态无效（{context}）")
    item = payload.get("data")
    if not isinstance(item, dict) or item.get("code") != code or type(item.get("market")) is not int or item["market"] != market_id:
        raise BacktestDataError(f"东方财富历史日K股票身份无效（{context}）")
    rows = item.get("klines")
    if not isinstance(rows, list) or len(rows) > 641:
        raise BacktestDataError(f"东方财富历史日K行数或格式无效（{context}）")
    result = []
    for row in rows:
        if not isinstance(row, str) or len(row) > 512:
            raise BacktestDataError(f"东方财富历史日K行格式无效（{context}）")
        parts = row.split(",")
        if len(parts) != 6:
            raise BacktestDataError(f"东方财富历史日K字段数无效（{context}）")
        # Volume is in lots, matching the shared OHLCV parser input.
        result.append(parts)
    return result
