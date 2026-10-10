"""Public-input normalization and stable hashing for AI backtest jobs."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from datetime import date
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from core.web.services import financial_market_service as market
from core.web.services.financial_backtest.data import BacktestInputError

PREVIEW_TTL_SECONDS = 60 * 60
MAX_STRATEGY_CHARS = 4_000
MAX_DECISIONS = 500
DEFAULT_MAX_TOKENS = 500_000
MIN_MAX_TOKENS = 512
MAX_TOKENS = 2_000_000
MAX_OUTPUT_TOKENS_PER_DECISION = 512
MAX_CONTEXT_BARS = 252
MAX_RESULT_CHARS = 8_000_000
MAX_RUNS_PER_AGENT = 200

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class FinancialBacktestError(ValueError):
    """Base error for AI backtest API/service failures."""

    code = "financial_backtest_error"
    status_code = 422


class FinancialBacktestNotFound(FinancialBacktestError):
    code = "not_found"
    status_code = 404


class FinancialBacktestConflict(FinancialBacktestError):
    code = "conflict"
    status_code = 409


class FinancialBacktestStoreError(FinancialBacktestError):
    code = "store_error"
    status_code = 500


def normalize_preview_request(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise BacktestInputError("回测请求必须是对象")
    raw_symbol = payload.get("symbol")
    raw_symbols = payload.get("symbols")
    if raw_symbol is not None and raw_symbols is not None:
        raise BacktestInputError("symbol与symbols不能同时传入，请选其一")
    if raw_symbols is not None:
        if not isinstance(raw_symbols, (list, tuple)) or isinstance(raw_symbols, (str, bytes)):
            raise BacktestInputError("symbols必须是股票代码列表")
        if not raw_symbols or len(raw_symbols) > 10:
            raise BacktestInputError("组合股票数量必须为1到10只")
        normalized_symbols: list[str] = []
        for value in raw_symbols:
            if not isinstance(value, str) or not value.strip():
                raise BacktestInputError("symbols必须只包含有效股票代码")
            try:
                normalized_symbols.append(market.normalize_a_share_symbol(value))
            except market.MarketDataError as exc:
                raise BacktestInputError(f"股票代码无效：{value}") from exc
        if len(set(normalized_symbols)) != len(normalized_symbols):
            raise BacktestInputError("symbols包含重复股票代码")
        symbols = sorted(normalized_symbols)
        symbol = None
        mode = "basket"
    else:
        symbol = str(raw_symbol or "").strip()
        if not symbol:
            raise BacktestInputError("请传入symbol或symbols其中一个字段")
        symbols = []
        mode = "single"
    start_date = _iso_date(payload.get("startDate"), "startDate")
    end_date = _iso_date(payload.get("endDate"), "endDate")
    out_of_sample_start_date = (
        None
        if payload.get("outOfSampleStartDate") is None
        else _iso_date(payload.get("outOfSampleStartDate"), "outOfSampleStartDate")
    )
    if start_date > end_date:
        raise BacktestInputError("startDate不能晚于endDate")
    strategy = payload.get("strategy")
    if not isinstance(strategy, str) or not strategy.strip():
        raise BacktestInputError("请填写本次回测策略")
    strategy = strategy.strip()
    if len(strategy) > MAX_STRATEGY_CHARS:
        raise BacktestInputError(f"策略最多{MAX_STRATEGY_CHARS}个字符")

    quantity_rule = payload.get("quantityRuleVersion", "ashare_quantity_v2")
    if quantity_rule not in ("ashare_quantity_v2", "legacy_100_v1"):
        raise BacktestInputError("quantityRuleVersion不是支持的撮合股数规则")
    params = {
        "quantityRuleVersion": quantity_rule,
        "initialCash": _number(payload.get("initialCash", 100_000), "initialCash", 1_000, 100_000_000),
        "maxPositionPct": _number(payload.get("maxPositionPct", 100), "maxPositionPct", 0, 100),
        "maxParticipationPct": _number(payload.get("maxParticipationPct", 1), "maxParticipationPct", 0.1, 100),
        "decisionInterval": _integer(payload.get("decisionInterval", 5), "decisionInterval", 1, 252),
        "commissionBps": _number(payload.get("commissionBps", 3), "commissionBps", 0, 100),
        "minimumCommission": _number(payload.get("minimumCommission", 5), "minimumCommission", 0, 10_000),
        "slippageBps": _number(payload.get("slippageBps", 5), "slippageBps", 0, 100),
        "maxDecisions": _integer(payload.get("maxDecisions", MAX_DECISIONS), "maxDecisions", 1, MAX_DECISIONS),
    }
    max_tokens = _integer(payload.get("maxTokens", DEFAULT_MAX_TOKENS), "maxTokens", MIN_MAX_TOKENS, MAX_TOKENS)
    model_id = str(payload.get("modelId") or "").strip()
    data_source = payload.get("dataSource", "tencent")
    if data_source not in {"tencent", "eastmoney", "sina", "auto"}:
        raise BacktestInputError("dataSource必须是tencent、eastmoney、sina或auto")
    research_input = payload.get("researchInput", "price_only")
    action_policy = payload.get("corporateActionPolicy", "block")
    if action_policy not in {"block", "verified_cash_dividends"}:
        raise BacktestInputError("corporateActionPolicy不是支持的公司行动策略")
    if action_policy != "block":
        params["corporateActionPolicy"] = action_policy
    if research_input not in {"price_only", "announcements", "financial_reports"}:
        raise BacktestInputError("researchInput必须是price_only、announcements或financial_reports")
    if len(model_id) > 160:
        raise BacktestInputError("modelId无效")
    return {
        "mode": mode,
        "symbol": symbol,
        "symbols": symbols,
        "startDate": start_date,
        "endDate": end_date,
        "outOfSampleStartDate": out_of_sample_start_date,
        "strategy": strategy,
        "params": params,
        "maxTokens": max_tokens,
        "modelId": model_id or None,
        "dataSource": data_source,
        "researchInput": research_input,
        "corporateActionPolicy": action_policy,
    }


def canonical_request_id(value: Any) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise BacktestInputError("clientRequestId必须是UUID") from exc


def canonical_uuid(value: Any, label: str) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise BacktestInputError(f"{label}无效") from exc


def deterministic_run_id(agent_id: str, request_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"vibelution:financial-ai-backtest:{agent_id}:{request_id}"))


def sha256_json(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def is_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.fullmatch(value))


def decision_dates(candles: list[Mapping[str, Any]] | tuple[Any, ...], interval: int) -> list[str]:
    """Exact close-time schedule; the final candle cannot execute next-open."""
    return [str(row.date if hasattr(row, "date") else row.get("date")) for row in candles[0:max(0, len(candles) - 1):interval]]


def project_status(status: Any) -> str:
    allowed = {"queued", "running", "stop_requested", "stopped", "paused_unknown", "completed", "failed", "blocked"}
    normalized = str(status or "").strip().lower()
    return normalized if normalized in allowed else "failed"


def _iso_date(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        raise BacktestInputError(f"{label}必须是YYYY-MM-DD日期")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise BacktestInputError(f"{label}必须是YYYY-MM-DD日期") from exc
    if parsed.isoformat() != value:
        raise BacktestInputError(f"{label}必须是YYYY-MM-DD日期")
    return value


def _number(value: Any, label: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool):
        raise BacktestInputError(f"{label}必须是{minimum}到{maximum}之间的数值")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise BacktestInputError(f"{label}必须是{minimum}到{maximum}之间的数值") from exc
    if not math.isfinite(number) or number < minimum or number > maximum:
        raise BacktestInputError(f"{label}必须是{minimum}到{maximum}之间的数值")
    return number


def _integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise BacktestInputError(f"{label}必须是{minimum}到{maximum}之间的整数")
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise BacktestInputError(f"{label}必须是{minimum}到{maximum}之间的整数") from exc
    if number != value or number < minimum or number > maximum:
        raise BacktestInputError(f"{label}必须是{minimum}到{maximum}之间的整数")
    return number


__all__ = [
    "DEFAULT_MAX_TOKENS",
    "MAX_CONTEXT_BARS",
    "MAX_DECISIONS",
    "MAX_OUTPUT_TOKENS_PER_DECISION",
    "MAX_RESULT_CHARS",
    "MAX_RUNS_PER_AGENT",
    "MAX_STRATEGY_CHARS",
    "MAX_TOKENS",
    "MIN_MAX_TOKENS",
    "PREVIEW_TTL_SECONDS",
    "FinancialBacktestConflict",
    "FinancialBacktestError",
    "FinancialBacktestNotFound",
    "FinancialBacktestStoreError",
    "canonical_request_id",
    "canonical_uuid",
    "decision_dates",
    "deterministic_run_id",
    "is_sha256",
    "normalize_preview_request",
    "project_status",
    "sha256_json",
]
