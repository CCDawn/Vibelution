"""Deterministic stress and uncertainty projections for completed A-share runs.

Cost scenarios replay the exact saved decisions through the existing execution
engines. They do not call an LLM and do not represent model retraining or a
new decision process. The uncertainty interval is conditional on the one
observed out-of-sample return path.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from . import basket_data, engine, evaluation, portfolio_engine
from .data import BacktestDataError, BacktestInputError, BacktestSnapshot

_COST_MULTIPLIERS = (Decimal(1), Decimal("1.5"), Decimal(2))
_MIN_HAC_OBSERVATIONS = 252
_ANNUAL_SESSIONS = 252
_Z_95 = 1.959963984540054
_HAC_LAG_CAP = 63
_SCENARIO_METRIC_KEYS = (
    "totalReturnPct",
    "benchmarkReturnPct",
    "excessReturnPct",
    "maxDrawdownPct",
    "tradeCount",
    "fees",
    "commissionFees",
    "stampDuty",
    "slippageCost",
    "benchmarkFees",
    "benchmarkSlippageCost",
    "grossTurnover",
    "transferFees",
    "handlingFees",
    "regulatoryFees",
    "brokerCommissionFees",
    "benchmarkTransferFees",
)


def evaluate_advanced_evaluation(
    snapshot: BacktestSnapshot | basket_data.BasketSnapshot,
    params: Mapping[str, Any],
    public_decisions: Sequence[Mapping[str, Any]],
    equity: Sequence[Mapping[str, Any]],
    *,
    out_of_sample_start_date: str | None,
) -> dict[str, Any]:
    """Build read-only cost and return-uncertainty projections for one run."""
    normalized = engine._normalize_params(params)
    normalized_params = {
        key: float(value) if isinstance(value, Decimal) else value
        for key, value in normalized.items()
    }
    return {
        "schemaVersion": 1,
        "basis": "frozen_decisions",
        "outOfSampleStartDate": out_of_sample_start_date,
        "costStress": evaluate_cost_stress(
            snapshot,
            normalized_params,
            public_decisions,
            out_of_sample_start_date=out_of_sample_start_date,
        ),
        "returnUncertainty": evaluate_return_uncertainty(
            equity,
            initial_cash=float(normalized["initialCash"]),
            out_of_sample_start_date=out_of_sample_start_date,
        ),
        "notice": (
            "费用情景沿用已保存的模型决策，仅重放撮合；策略、模型、提示或决策频率变化需要独立完整回测。"
            "统计区间只描述这条冻结样本外收益序列，不包含模型调用随机性、训练知识偏差或未来行情不确定性。"
        ),
    }


def evaluate_cost_stress(
    snapshot: BacktestSnapshot | basket_data.BasketSnapshot,
    params: Mapping[str, Any],
    public_decisions: Sequence[Mapping[str, Any]],
    *,
    out_of_sample_start_date: str | None,
) -> dict[str, Any]:
    """Replay a fixed 1x/1.5x/2x modeled-cost grid without model calls."""
    normalized = engine._normalize_params(params)
    decisions = _engine_decisions(snapshot, public_decisions)
    scenarios: list[dict[str, Any]] = []

    for multiplier in _COST_MULTIPLIERS:
        stressed = dict(normalized)
        for key in ("commissionBps", "minimumCommission", "slippageBps"):
            stressed[key] = normalized[key] * multiplier
        scenario_params = {
            key: float(value) if isinstance(value, Decimal) else value
            for key, value in stressed.items()
        }
        scenario_id = {
            Decimal(1): "baseline",
            Decimal("1.5"): "cost_1_5x",
            Decimal(2): "cost_2x",
        }[multiplier]
        try:
            result = _simulate(snapshot, scenario_params, decisions)
            windowed = (
                evaluation.evaluate_windows(
                    result["equity"],
                    result["orders"],
                    initial_cash=float(normalized["initialCash"]),
                    out_of_sample_start_date=out_of_sample_start_date,
                )
                if out_of_sample_start_date is not None
                else None
            )
            scenarios.append(
                {
                    "id": scenario_id,
                    "status": "available",
                    "costMultiplier": float(multiplier),
                    "commissionBps": float(stressed["commissionBps"]),
                    "minimumCommission": float(stressed["minimumCommission"]),
                    "slippageBps": float(stressed["slippageBps"]),
                    "metrics": _select_metrics(result.get("metrics")),
                    "outOfSampleMetrics": (
                        _select_metrics(windowed["outOfSample"].get("metrics"))
                        if windowed
                        else None
                    ),
                    "error": None,
                }
            )
        except BacktestDataError as exc:
            # A failure at baseline means the saved run cannot be reproduced;
            # do not turn an invalid authority into a partial stress report.
            if multiplier == Decimal(1):
                raise
            scenarios.append(
                {
                    "id": scenario_id,
                    "status": "unavailable",
                    "costMultiplier": float(multiplier),
                    "commissionBps": float(stressed["commissionBps"]),
                    "minimumCommission": float(stressed["minimumCommission"]),
                    "slippageBps": float(stressed["slippageBps"]),
                    "metrics": None,
                    "outOfSampleMetrics": None,
                    "error": str(exc),
                }
            )

    statuses = {str(item["status"]) for item in scenarios}
    status = "available" if statuses == {"available"} else "partial"
    return {
        "status": status,
        "scenarios": scenarios,
        "notice": (
            "1×为原回测费用；1.5×和2×同时放大佣金、最低佣金与滑点，历史印花税仍按成交日规则计算。"
            "各情景和买入持有基准使用同一套费用。过户费、监管费及未建模市场冲击不在该模型内。"
        ),
    }


def evaluate_return_uncertainty(
    equity: Sequence[Mapping[str, Any]],
    *,
    initial_cash: float,
    out_of_sample_start_date: str | None,
) -> dict[str, Any]:
    """Estimate a Newey-West HAC interval for annualized OOS log excess return."""
    _finite(initial_cash, "initialCash", positive=True)
    rows = _validate_equity(equity)
    if out_of_sample_start_date is None:
        return _uncertainty_unavailable("未设置预先冻结的样本外起点，不计算统计区间")
    if not isinstance(out_of_sample_start_date, str):
        raise BacktestInputError("样本外起点必须是有效交易日")
    try:
        parsed = date.fromisoformat(out_of_sample_start_date)
    except ValueError as exc:
        raise BacktestInputError("样本外起点必须是有效交易日") from exc
    if parsed.isoformat() != out_of_sample_start_date:
        raise BacktestInputError("样本外起点必须是有效交易日")
    dates = [str(row["date"]) for row in rows]
    if out_of_sample_start_date not in dates:
        raise BacktestInputError("样本外起点必须是区间内的交易日")
    boundary = dates.index(out_of_sample_start_date)
    if boundary == 0:
        raise BacktestInputError("样本外起点前必须至少保留一个交易日")

    active_log_returns: list[float] = []
    for previous, current in zip(rows[boundary - 1 : -1], rows[boundary:]):
        previous_equity = _finite(previous.get("equity"), "前日净值", positive=True)
        previous_benchmark = _finite(
            previous.get("benchmarkEquity"), "前日基准净值", positive=True
        )
        current_equity = _finite(current.get("equity"), "净值", positive=True)
        current_benchmark = _finite(
            current.get("benchmarkEquity"), "基准净值", positive=True
        )
        active = (
            math.log(current_equity)
            - math.log(previous_equity)
            - math.log(current_benchmark)
            + math.log(previous_benchmark)
        )
        if not math.isfinite(active):
            raise BacktestInputError("样本外超额收益序列无效")
        active_log_returns.append(active)

    observations = len(active_log_returns)
    if observations < _MIN_HAC_OBSERVATIONS:
        return {
            "status": "insufficient_sample",
            "method": "newey_west_hac",
            "metric": "annualized_log_excess_return_pct",
            "confidenceLevel": 0.95,
            "observations": observations,
            "lag": None,
            "pointEstimatePct": None,
            "lowerPct": None,
            "upperPct": None,
            "error": f"样本外仅有{observations}个交易日，至少需要{_MIN_HAC_OBSERVATIONS}个交易日才显示统计区间",
            "notice": _HAC_NOTICE,
        }

    mean = sum(active_log_returns) / observations
    lag = min(
        _HAC_LAG_CAP,
        max(1, math.floor(4 * (observations / 100) ** (2 / 9))),
    )
    centered = [value - mean for value in active_log_returns]
    long_run_variance = sum(value * value for value in centered) / observations
    for offset in range(1, lag + 1):
        covariance = (
            sum(
                centered[index] * centered[index - offset]
                for index in range(offset, observations)
            )
            / observations
        )
        bartlett_weight = 1 - offset / (lag + 1)
        long_run_variance += 2 * bartlett_weight * covariance
    variance_of_mean = long_run_variance / observations
    if not math.isfinite(variance_of_mean) or variance_of_mean <= 0:
        return {
            "status": "unavailable",
            "method": "newey_west_hac",
            "metric": "annualized_log_excess_return_pct",
            "confidenceLevel": 0.95,
            "observations": observations,
            "lag": lag,
            "pointEstimatePct": None,
            "lowerPct": None,
            "upperPct": None,
            "error": "样本外序列无法估计正的长期方差，统计区间不可用",
            "notice": _HAC_NOTICE,
        }

    standard_error = math.sqrt(variance_of_mean)
    try:
        point, lower, upper = (
            _annualized_log_return(mean),
            _annualized_log_return(mean - _Z_95 * standard_error),
            _annualized_log_return(mean + _Z_95 * standard_error),
        )
    except (OverflowError, ValueError) as exc:
        raise BacktestInputError("样本外统计区间超出可计算范围") from exc
    return {
        "status": "available",
        "method": "newey_west_hac",
        "metric": "annualized_log_excess_return_pct",
        "confidenceLevel": 0.95,
        "observations": observations,
        "lag": lag,
        "pointEstimatePct": point,
        "lowerPct": lower,
        "upperPct": upper,
        "error": None,
        "notice": _HAC_NOTICE,
    }


def _simulate(
    snapshot: BacktestSnapshot | basket_data.BasketSnapshot,
    params: Mapping[str, Any],
    decisions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if isinstance(snapshot, basket_data.BasketSnapshot):
        return portfolio_engine.simulate(snapshot, params, decisions)
    return engine.simulate(snapshot, params, decisions)


def _engine_decisions(
    snapshot: BacktestSnapshot | basket_data.BasketSnapshot,
    public_decisions: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(public_decisions, Sequence) or isinstance(
        public_decisions, (str, bytes)
    ):
        raise BacktestInputError("冻结AI决策必须是列表")
    basket = isinstance(snapshot, basket_data.BasketSnapshot)
    converted: list[dict[str, Any]] = []
    for raw in public_decisions:
        if not isinstance(raw, Mapping):
            raise BacktestInputError("冻结AI决策行必须是对象")
        item: dict[str, Any] = {
            "date": raw.get("date"),
            "reason": raw.get("reason"),
        }
        if raw.get("inputHash") is not None:
            item["inputHash"] = raw["inputHash"]
        if raw.get("decisionHash") is not None:
            item["outputHash"] = raw["decisionHash"]
        if raw.get("confidence") is not None:
            item["confidence"] = raw["confidence"]
        if basket:
            weights = raw.get("targetWeights")
            if not isinstance(weights, Mapping):
                raise BacktestInputError("组合冻结决策必须包含完整目标权重")
            item["targetWeights"] = {
                str(symbol): _weight_ratio(weight, f"targetWeights.{symbol}")
                for symbol, weight in weights.items()
            }
        else:
            item["targetWeight"] = _weight_ratio(
                raw.get("targetWeight"), "targetWeight"
            )
        converted.append(item)
    return converted


def _weight_ratio(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise BacktestInputError(f"{label}必须是0到100的百分比")
    try:
        weight = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError, OverflowError) as exc:
        raise BacktestInputError(f"{label}必须是0到100的百分比") from exc
    if not weight.is_finite() or weight < 0 or weight > 100:
        raise BacktestInputError(f"{label}必须是0到100的百分比")
    return float(weight / Decimal(100))


def _select_metrics(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    return {key: raw.get(key) for key in _SCENARIO_METRIC_KEYS if key in raw}


def _validate_equity(equity: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    if not isinstance(equity, Sequence) or isinstance(equity, (str, bytes)):
        raise BacktestInputError("样本外评估净值必须是交易日行列表")
    rows = list(equity)
    if not rows:
        raise BacktestInputError("样本外评估净值不能为空")
    previous_date = ""
    for row in rows:
        if not isinstance(row, Mapping):
            raise BacktestInputError("样本外评估净值行必须是对象")
        raw_date = row.get("date")
        if not isinstance(raw_date, str):
            raise BacktestInputError("样本外评估净值日期无效")
        try:
            parsed = date.fromisoformat(raw_date)
        except ValueError as exc:
            raise BacktestInputError("样本外评估净值日期无效") from exc
        if parsed.isoformat() != raw_date or (
            previous_date and raw_date <= previous_date
        ):
            raise BacktestInputError("样本外评估净值日期必须严格递增且不重复")
        previous_date = raw_date
        _finite(row.get("equity"), "equity", positive=True)
        _finite(row.get("benchmarkEquity"), "benchmarkEquity", positive=True)
    return rows


def _finite(value: Any, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise BacktestInputError(f"{label}必须是有限数值")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise BacktestInputError(f"{label}必须是有限数值") from exc
    if not math.isfinite(number) or number < 0 or (positive and number <= 0):
        raise BacktestInputError(f"{label}必须是有效数值")
    return number


def _annualized_log_return(daily_log_return: float) -> float:
    return math.expm1(daily_log_return * _ANNUAL_SESSIONS) * 100


def _uncertainty_unavailable(error: str) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "method": "newey_west_hac",
        "metric": "annualized_log_excess_return_pct",
        "confidenceLevel": 0.95,
        "observations": 0,
        "lag": None,
        "pointEstimatePct": None,
        "lowerPct": None,
        "upperPct": None,
        "error": error,
        "notice": _HAC_NOTICE,
    }


_HAC_NOTICE = (
    "95%区间使用样本外日对数超额收益的Newey–West HAC估计与Bartlett权重，"
    "带宽按样本量规则选择；至少252个样本外交易日。区间仅反映该冻结历史序列的抽样误差，"
    "不表示模型成功概率、未来收益概率或统计显著结论。"
)


__all__ = [
    "evaluate_advanced_evaluation",
    "evaluate_cost_stress",
    "evaluate_return_uncertainty",
]
