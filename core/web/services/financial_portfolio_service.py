"""Read-only portfolio research derived from an Agent's paper ledger."""

from __future__ import annotations

import math
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from itertools import combinations, pairwise
from typing import Any
from urllib.parse import urlencode

from core.web.services import financial_market_service as market
from core.web.services import financial_paper_service as paper

MAX_ANALYZED_POSITIONS = 12
MAX_CONCURRENT_CANDLE_FETCHES = 3
ANALYSIS_DEADLINE_SECONDS = 10.0
MIN_CORRELATION_OBSERVATIONS = 20
CORRELATION_ALERT_THRESHOLD = 0.7
_CANDLE_CACHE_SECONDS = 300

_CANDLE_CAPACITY = threading.BoundedSemaphore(MAX_CONCURRENT_CANDLE_FETCHES)


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


def _money(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _percent(numerator: Decimal | None, denominator: Decimal | None) -> str | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    value = numerator * Decimal(100) / denominator
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _load_daily_return_series(symbol: str) -> dict[str, float]:
    """Read only adjusted daily candles, reusing the market service's bounded cache."""
    url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?" + urlencode(
        {"param": f"{symbol},day,,,120,qfq"}
    )
    candles = market._cached(
        ("candles", symbol, "day"),
        _CANDLE_CACHE_SECONDS,
        lambda: market.parse_candles(market._read(url), symbol, "day"),
    )
    returns: dict[str, float] = {}
    for previous, current in pairwise(candles):
        previous_close = float(previous["close"])
        current_close = float(current["close"])
        if previous_close > 0 and math.isfinite(current_close):
            returns[str(current["date"])] = current_close / previous_close - 1.0
    return returns


def _pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < MIN_CORRELATION_OBSERVATIONS:
        return None
    left_mean = math.fsum(left) / len(left)
    right_mean = math.fsum(right) / len(right)
    left_centered = [value - left_mean for value in left]
    right_centered = [value - right_mean for value in right]
    left_square_sum = math.fsum(value * value for value in left_centered)
    right_square_sum = math.fsum(value * value for value in right_centered)
    denominator = math.sqrt(left_square_sum * right_square_sum)
    if not math.isfinite(denominator) or denominator <= 1e-15:
        return None
    coefficient = (
        math.fsum(
            left_value * right_value
            for left_value, right_value in zip(left_centered, right_centered)
        )
        / denominator
    )
    return round(max(-1.0, min(1.0, coefficient)), 6)


def _position_row(position: dict[str, Any]) -> tuple[dict[str, Any], Decimal | None]:
    market_value = _decimal(position.get("marketValueYuan"))
    return (
        {
            "symbol": str(position.get("symbol") or ""),
            "ticker": str(position.get("ticker") or ""),
            "name": str(position.get("name") or ""),
            "market": str(position.get("market") or ""),
            "quantity": int(position.get("quantity") or 0),
            "markPriceYuan": _money(_decimal(position.get("markPriceYuan"))),
            "marketValueYuan": _money(market_value),
            "unrealizedPnlYuan": _money(_decimal(position.get("unrealizedPnlYuan"))),
            "valuationStatus": str(position.get("valuationStatus") or "unavailable"),
            "quoteTimestamp": str(position.get("quoteTimestamp") or ""),
            "quoteFetchedAt": str(position.get("quoteFetchedAt") or ""),
            "source": str(position.get("source") or "腾讯财经"),
            "sourceUrl": str(position.get("sourceUrl") or ""),
            "returnSeriesStatus": "not_valued",
        },
        market_value,
    )


def _collect_return_series(
    selected: list[dict[str, Any]], deadline: float
) -> tuple[dict[str, dict[str, float]], dict[str, str]]:
    pool = ThreadPoolExecutor(
        max_workers=MAX_CONCURRENT_CANDLE_FETCHES,
        thread_name_prefix="financial-portfolio-candles",
    )
    futures: dict[Future[dict[str, float]], str] = {}
    status: dict[str, str] = {}
    series: dict[str, dict[str, float]] = {}
    pending: set[Future[dict[str, float]]] = set()
    try:
        for row in selected:
            symbol = row["symbol"]
            if time.monotonic() >= deadline:
                status[symbol] = "deadline"
                continue
            if not _CANDLE_CAPACITY.acquire(blocking=False):
                status[symbol] = "capacity_skipped"
                continue
            try:
                future = pool.submit(_load_daily_return_series, symbol)
            except RuntimeError:
                _CANDLE_CAPACITY.release()
                status[symbol] = "capacity_skipped"
                continue
            future.add_done_callback(lambda _completed: _CANDLE_CAPACITY.release())
            futures[future] = symbol
            status[symbol] = "pending"

        pending = set(futures)
        while pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            completed, pending = wait(
                pending, timeout=remaining, return_when=FIRST_COMPLETED
            )
            if not completed:
                break
            for future in completed:
                symbol = futures[future]
                try:
                    values = future.result()
                    series[symbol] = values
                    status[symbol] = "available"
                except (
                    market.MarketDataError,
                    KeyError,
                    OSError,
                    TypeError,
                    ValueError,
                ):
                    # Provider error text can contain transport details; expose status only.
                    status[symbol] = "unavailable"

        for future in pending:
            if future.done():
                symbol = futures[future]
                try:
                    values = future.result()
                    series[symbol] = values
                    status[symbol] = "available"
                except (
                    market.MarketDataError,
                    KeyError,
                    OSError,
                    TypeError,
                    ValueError,
                ):
                    status[symbol] = "unavailable"
            else:
                status[futures[future]] = "deadline"
    finally:
        active = any(not future.done() for future in futures)
        pool.shutdown(wait=not active, cancel_futures=active)
    return series, status


def get_portfolio_research(agent_id: str) -> dict[str, Any]:
    """Project real paper-ledger marks and bounded candle correlations for one Agent."""
    started = time.monotonic()
    deadline = started + ANALYSIS_DEADLINE_SECONDS
    account = paper.get_account_snapshot(agent_id, order_limit=1)

    position_data = [_position_row(row) for row in account.get("positions", [])]
    position_data.sort(
        key=lambda item: item[1] if item[1] is not None else Decimal(-1),
        reverse=True,
    )
    positions = [row for row, _value in position_data]
    values = [_value for _row, _value in position_data]
    equity = _decimal(account.get("equityYuan"))
    cash = _decimal(account.get("cashYuan"))
    market_value = _decimal(account.get("marketValueYuan"))
    valued_complete = all(value is not None for value in values)

    if valued_complete and equity is not None and equity > 0:
        for row, value in zip(positions, values):
            row["weightPercent"] = _percent(value, equity)
    else:
        for row in positions:
            row["weightPercent"] = None

    eligible_rows = [
        row
        for row, value in zip(positions, values)
        if value is not None and value > 0 and row["symbol"]
    ]
    selected = eligible_rows[:MAX_ANALYZED_POSITIONS]
    for row in eligible_rows[MAX_ANALYZED_POSITIONS:]:
        row["returnSeriesStatus"] = "limit_skipped"
    series, series_status = _collect_return_series(selected, deadline)
    for row in positions:
        status = series_status.get(row["symbol"])
        if status:
            row["returnSeriesStatus"] = status

    correlations: list[dict[str, Any]] = []
    insufficient_pairs = 0
    unavailable_pairs = 0
    for left, right in combinations(selected, 2):
        left_symbol = left["symbol"]
        right_symbol = right["symbol"]
        if (
            series_status.get(left_symbol) != "available"
            or series_status.get(right_symbol) != "available"
        ):
            unavailable_pairs += 1
            continue
        left_series = series.get(left_symbol, {})
        right_series = series.get(right_symbol, {})
        common_dates = sorted(left_series.keys() & right_series.keys())
        if len(common_dates) < MIN_CORRELATION_OBSERVATIONS:
            insufficient_pairs += 1
            continue
        coefficient = _pearson(
            [left_series[date] for date in common_dates],
            [right_series[date] for date in common_dates],
        )
        if coefficient is None:
            insufficient_pairs += 1
            continue
        correlations.append(
            {
                "firstSymbol": left_symbol,
                "firstName": left["name"],
                "secondSymbol": right_symbol,
                "secondName": right["name"],
                "correlation": coefficient,
                "observations": len(common_dates),
                "startDate": common_dates[0],
                "endDate": common_dates[-1],
            }
        )
    correlations.sort(key=lambda pair: abs(pair["correlation"]), reverse=True)

    cash_weight = _percent(cash, equity) if valued_complete else None
    position_weights = [
        _decimal(row.get("weightPercent"))
        for row in positions
        if row.get("weightPercent") is not None
    ]
    top_three = (
        sum(position_weights[:3], Decimal(0))
        if valued_complete and position_weights
        else None
    )
    max_weight = max(position_weights) if position_weights else None
    unavailable_symbols = sorted(
        symbol for symbol, status in series_status.items() if status == "unavailable"
    )
    limit_skipped_symbols = [
        row["symbol"] for row in eligible_rows[MAX_ANALYZED_POSITIONS:]
    ]
    summary = {
        "equityYuan": _money(equity),
        "cashYuan": _money(cash),
        "marketValueYuan": _money(market_value),
        "cashWeightPercent": cash_weight,
        "positionCount": len(positions),
        "valuedPositionCount": sum(value is not None for value in values),
        "valuationComplete": valued_complete,
        "maxPositionWeightPercent": _money(max_weight),
        "topThreeWeightPercent": _money(top_three),
        "correlationPairCount": len(correlations),
        "highCorrelationPairCount": sum(
            abs(row["correlation"]) >= CORRELATION_ALERT_THRESHOLD
            for row in correlations
        ),
        "insufficientCorrelationPairCount": insufficient_pairs,
        "unavailableCorrelationPairCount": unavailable_pairs,
    }
    return {
        "agentId": account["agentId"],
        "accountId": account["accountId"],
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "腾讯财经",
        "sourceUrl": "https://gu.qq.com/",
        "adjustment": "qfq",
        "period": "day",
        "simulationOnly": True,
        "summary": summary,
        "positions": positions,
        "correlations": correlations,
        "coverage": {
            "eligiblePositionCount": len(eligible_rows),
            "selectedPositionCount": len(selected),
            "candleLoadedPositionCount": sum(
                series_status.get(row["symbol"]) == "available" for row in selected
            ),
            "candleUnavailablePositionCount": len(unavailable_symbols),
            "budgetSkippedPositionCount": len(limit_skipped_symbols),
            "capacitySkippedPositionCount": sum(
                series_status.get(row["symbol"]) == "capacity_skipped"
                for row in selected
            ),
            "deadlineSkippedPositionCount": sum(
                series_status.get(row["symbol"]) == "deadline" for row in selected
            ),
            "unvaluedPositionCount": len(positions)
            - sum(value is not None for value in values),
            "maxAnalyzedPositions": MAX_ANALYZED_POSITIONS,
            "maxConcurrentFetches": MAX_CONCURRENT_CANDLE_FETCHES,
            "deadlineSeconds": ANALYSIS_DEADLINE_SECONDS,
            "minimumCorrelationObservations": MIN_CORRELATION_OBSERVATIONS,
            "analyzedSymbols": [
                row["symbol"]
                for row in selected
                if series_status.get(row["symbol"]) == "available"
            ],
            "budgetSkippedSymbols": limit_skipped_symbols,
            "unavailableSymbols": unavailable_symbols,
        },
        "notice": (
            "仅分析模拟账本持仓；权重基于当前可用估值快照。相关性使用腾讯财经前复权日线收盘收益，"
            f"至少需要 {MIN_CORRELATION_OBSERVATIONS} 个共同交易日；公开行情可能延迟。"
        ),
    }
