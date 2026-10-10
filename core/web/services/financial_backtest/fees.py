"""Historical A-share transaction fees for deterministic backtests.

The legacy model intentionally preserves the original commission/stamp-duty
semantics so frozen runs do not change their identity. The opt-in verified
model covers Shanghai and Shenzhen A shares from 2015-08-01 and keeps exchange
charges inside the customer commission instead of double-counting them.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from core.web.services import financial_market_service as market
from core.web.services.financial_backtest.data import BacktestInputError

LEGACY_FEE_MODEL = "legacy_commission_stamp_v1"
VERIFIED_FEE_MODEL = "verified_ashare_fees_v1"
VERIFIED_FEE_START = date(2015, 8, 1)

_MONEY_QUANTUM = Decimal("0.01")
_BPS = Decimal(10000)
_COMMISSION_MINIMUM_YUAN = Decimal(5)
_COMMISSION_MAX_RATE = Decimal("0.003")  # 3 per mille, the legal ceiling.
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Rates are ratios of notional, not per-mille values. Keep this schedule as the
# sole authority for both simulation and the user-visible audit projection.
_STAMP_DUTY_CHANGES = (
    (date(2023, 8, 28), Decimal("0.0005"), Decimal(0)),
    (date(2008, 9, 19), Decimal("0.001"), Decimal(0)),
    (date(2008, 4, 24), Decimal("0.001"), Decimal("0.001")),
    (date(2007, 5, 30), Decimal("0.003"), Decimal("0.003")),
    (date(2005, 1, 24), Decimal("0.001"), Decimal("0.001")),
)
_HANDLING_FEE_CHANGES = (
    (date(2015, 8, 1), Decimal("0.0000487")),
    (date(2023, 8, 28), Decimal("0.0000341")),
)
_TRANSFER_FEE_CHANGES = (
    (date(2015, 8, 1), Decimal("0.00002")),
    (date(2022, 4, 29), Decimal("0.00001")),
)
_REGULATORY_FEE_RATE = Decimal("0.00002")

_COMMISSION_URL = (
    "https://www.chinatax.gov.cn/chinatax/n810341/n810765/n812203/"
    "200202/c1209808/content.html"
)
_STAMP_2008_RATE_URL = (
    "https://www.mof.gov.cn/zhengwuxinxi/caizhengxinwen/200805/"
    "t20080519_29133.htm"
)
_STAMP_2008_SIDE_URL = (
    "https://www.mof.gov.cn/zhengwuxinxi/caizhengxinwen/200809/"
    "t20080919_76432.htm"
)
_STAMP_2023_URL = "https://www.mof.gov.cn/jrttts/202308/t20230828_3904235.htm"
_TRANSFER_HISTORY_URL = "https://m.chinaclear.cn/zdjs/dsj/about_dsj.shtml"
_SSE_2015_URL = (
    "https://www.sse.com.cn/lawandrules/sselawsrules/repeal/rules/c/"
    "c_20211231_5674670.shtml"
)
_SZSE_2015_URL = "https://www.szse.cn/disclosure/notice/general/t20150730_501531.html"
_SSE_2023_URL = (
    "https://www.sse.com.cn/services/tradingservice/charge/ssecharge/c/"
    "c_20230818_5725343.shtml"
)
_SZSE_2023_URL = "https://www.szse.cn/disclosure/notice/t20230818_602805.html"
_SSE_CURRENT_FEES_URL = "https://www.sse.com.cn/services/tradingservice/charge/taxfee/"
_SZSE_CURRENT_FEES_URL = "https://www.szse.cn/www/marketServices/deal/payFees/"


def _as_decimal(value: Any, label: str) -> Decimal:
    if isinstance(value, bool):
        raise BacktestInputError(f"{label}必须是有效数值")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise BacktestInputError(f"{label}必须是有效数值") from exc
    if not result.is_finite():
        raise BacktestInputError(f"{label}必须是有效数值")
    return result


def _money(value: Decimal) -> Decimal:
    return value.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _iso_day(value: Any, label: str) -> date:
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        raise BacktestInputError(f"{label}必须是YYYY-MM-DD日期")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise BacktestInputError(f"{label}必须是YYYY-MM-DD日期") from exc
    if parsed.isoformat() != value:
        raise BacktestInputError(f"{label}必须是YYYY-MM-DD日期")
    return parsed


def _param(params: Mapping[str, Any], camel: str, snake: str, default: Any) -> Any:
    if camel in params and snake in params and params[camel] != params[snake]:
        raise BacktestInputError(f"{camel}与{snake}不能同时指定不同值")
    return params[camel] if camel in params else params.get(snake, default)


def normalize_fee_model(params: Mapping[str, Any] | None) -> str:
    """Resolve the opt-in fee model, defaulting without changing legacy hashes."""
    if params is None:
        return LEGACY_FEE_MODEL
    if not isinstance(params, Mapping):
        raise BacktestInputError("回测参数必须是对象")
    value = _param(params, "feeModel", "fee_model", LEGACY_FEE_MODEL)
    if value is None:
        return LEGACY_FEE_MODEL
    if not isinstance(value, str) or value not in {
        LEGACY_FEE_MODEL,
        VERIFIED_FEE_MODEL,
    }:
        raise BacktestInputError("feeModel不是支持的交易费用模型")
    return value


def stamp_duty_rate(trade_date: str, side: str) -> Decimal:
    """Return the historical A-share stamp-duty ratio for a buy or sell."""
    day = _iso_day(trade_date, "tradeDate")
    if side not in {"buy", "sell"}:
        raise BacktestInputError("交易方向必须是buy或sell")
    for effective, seller_rate, buyer_rate in _STAMP_DUTY_CHANGES:
        if day >= effective:
            return seller_rate if side == "sell" else buyer_rate
    # Preserve the original engine's earliest supported fallback rate.
    return Decimal("0.001")


def stamp_duty(notional: Decimal, trade_date: str, side: str) -> Decimal:
    """Return stamp duty rounded to cents using the simulation convention."""
    amount = _as_decimal(notional, "notional")
    return _money(amount * stamp_duty_rate(trade_date, side))


def _effective_rate(day: date, changes: Sequence[tuple[date, Decimal]]) -> Decimal:
    applicable = [rate for effective, rate in changes if day >= effective]
    if not applicable:
        raise BacktestInputError("所选日期早于已核验的A股费用费率范围")
    return applicable[-1]


def _handling_fee_rate(day: date) -> Decimal:
    return _effective_rate(day, _HANDLING_FEE_CHANGES)


def _transfer_fee_rate(day: date) -> Decimal:
    return _effective_rate(day, _TRANSFER_FEE_CHANGES)


def _commission_floor_rate(day: date) -> Decimal:
    return _handling_fee_rate(day) + _REGULATORY_FEE_RATE


def _validate_verified_terms(
    start: date,
    end: date,
    commission_bps: Any,
    minimum_commission: Any,
) -> None:
    if start < VERIFIED_FEE_START:
        raise BacktestInputError("verified A股费用模型仅支持2015-08-01及之后的沪深交易")
    if start > end:
        raise BacktestInputError("startDate不能晚于endDate")

    rate_bps = _as_decimal(commission_bps, "commissionBps")
    minimum = _as_decimal(minimum_commission, "minimumCommission")
    floor_rate = max(_commission_floor_rate(start), _commission_floor_rate(end))
    floor_bps = floor_rate * _BPS
    if rate_bps < floor_bps or rate_bps > _COMMISSION_MAX_RATE * _BPS:
        raise BacktestInputError(
            "verified费用模型的commissionBps必须覆盖区间内经手费与证管费，且不超过30bps"
        )
    if minimum < _COMMISSION_MINIMUM_YUAN:
        raise BacktestInputError("verified费用模型的minimumCommission不得低于5元")


def _normalize_supported_symbol(symbol: Any) -> str:
    if not isinstance(symbol, str) or not symbol.strip():
        raise BacktestInputError("verified费用模型需要有效的沪深A股代码")
    try:
        normalized = market.normalize_a_share_symbol(symbol)
    except market.MarketDataError as exc:
        raise BacktestInputError(f"股票代码无效：{symbol}") from exc
    ticker = normalized[2:]
    shanghai = normalized.startswith("sh") and ticker.startswith(
        ("600", "601", "603", "605", "688", "689")
    )
    shenzhen = normalized.startswith("sz") and ticker.startswith(
        ("000", "001", "002", "003", "300", "301")
    )
    if not (shanghai or shenzhen):
        raise BacktestInputError("verified费用模型当前仅支持沪深A股，不含指数、B股及北交所")
    return normalized


def _normalize_symbols(symbols: Sequence[str]) -> list[str]:
    if not isinstance(symbols, Sequence) or isinstance(symbols, (str, bytes)):
        raise BacktestInputError("symbols必须是股票代码列表")
    if not symbols or len(symbols) > 10:
        raise BacktestInputError("verified费用审计需要1到10只沪深A股")
    normalized = sorted(_normalize_supported_symbol(symbol) for symbol in symbols)
    if len(set(normalized)) != len(normalized):
        raise BacktestInputError("symbols包含重复股票代码")
    return normalized


def validate_fee_window(
    symbol: str,
    start: str,
    end: str,
    params: Mapping[str, Any] | None,
) -> None:
    """Fail closed when the verified schedule cannot cover a requested run."""
    if normalize_fee_model(params) != VERIFIED_FEE_MODEL:
        return
    _normalize_supported_symbol(symbol)
    start_day = _iso_day(start, "startDate")
    end_day = _iso_day(end, "endDate")
    if start_day > end_day:
        raise BacktestInputError("startDate不能晚于endDate")
    _validate_verified_terms(
        start_day,
        end_day,
        _param(params or {}, "commissionBps", "commission_bps", 3),
        _param(params or {}, "minimumCommission", "minimum_commission", 5),
    )
    # Validate that every date in the window has a known handling and transfer
    # rate. The selected endpoints are sufficient because schedules are flat
    # between their explicit effective dates.
    _handling_fee_rate(start_day)
    _handling_fee_rate(end_day)
    _transfer_fee_rate(start_day)
    _transfer_fee_rate(end_day)
def calculate_fees(
    notional: Decimal,
    trade_date: str,
    side: str,
    symbol: str,
    commission_rate: Decimal,
    minimum_commission: Decimal,
    fee_model: str,
) -> dict[str, Decimal]:
    """Calculate one simulated order's fee breakdown for the selected model."""
    if fee_model not in {LEGACY_FEE_MODEL, VERIFIED_FEE_MODEL}:
        raise BacktestInputError("feeModel不是支持的交易费用模型")
    amount = _as_decimal(notional, "notional")
    rate = _as_decimal(commission_rate, "commissionRate")
    minimum = _as_decimal(minimum_commission, "minimumCommission")
    day = _iso_day(trade_date, "tradeDate")
    stamp_rate = stamp_duty_rate(trade_date, side)
    commission = (
        Decimal(0)
        if rate == 0 or amount <= 0
        else _money(max(minimum, amount * rate))
    )
    stamp = _money(amount * stamp_rate)

    if fee_model == LEGACY_FEE_MODEL:
        transfer = Decimal("0.00")
        return {
            "commission": commission,
            "stampDuty": stamp,
            "transferFee": transfer,
            "fee": commission + stamp,
        }

    _normalize_supported_symbol(symbol)
    _validate_verified_terms(day, day, rate * _BPS, minimum)
    if amount < 0:
        raise BacktestInputError("verified费用模型的notional不能为负数")
    handling = _money(amount * _handling_fee_rate(day))
    regulatory = _money(amount * _REGULATORY_FEE_RATE)
    transfer = _money(amount * _transfer_fee_rate(day))
    # Do not silently increase the customer's configured gross commission to
    # reconcile separately rounded line items. Broker settlement rounding is
    # unverified, so this case must fail closed instead of adding a cent.
    if handling + regulatory > commission:
        raise BacktestInputError(
            "交易经手费与证管费分项舍入后超过配置的总佣金；券商清算取分规则未核实，"
            "请提高commissionBps或停止本次回测"
        )
    broker = commission - handling - regulatory
    fee = commission + transfer + stamp
    return {
        "commission": commission,
        "stampDuty": stamp,
        "transferFee": transfer,
        "handlingFee": handling,
        "regulatoryFee": regulatory,
        "brokerCommission": broker,
        "fee": fee,
    }


def _rate_segments(
    start: date,
    end: date,
    changes: Sequence[tuple[date, Decimal]],
    *,
    component: str,
    side: str,
) -> list[dict[str, str]]:
    ascending = tuple(sorted(changes, key=lambda item: item[0]))
    result: list[dict[str, str]] = []
    for index, (effective, rate) in enumerate(ascending):
        next_day = ascending[index + 1][0] if index + 1 < len(ascending) else None
        segment_start = max(start, effective)
        segment_end = min(end, next_day - timedelta(days=1) if next_day else end)
        if segment_start <= segment_end:
            result.append(
                {
                    "component": component,
                    "startDate": segment_start.isoformat(),
                    "endDate": segment_end.isoformat(),
                    "rate": str(rate),
                    "side": side,
                }
            )
    return result


def _stamp_rate_segments(start: date, end: date) -> list[dict[str, str]]:
    ascending = tuple(
        sorted(_STAMP_DUTY_CHANGES, key=lambda item: item[0])
    )
    result: list[dict[str, str]] = []
    for index, (effective, seller_rate, buyer_rate) in enumerate(ascending):
        next_day = ascending[index + 1][0] if index + 1 < len(ascending) else None
        segment_start = max(start, effective)
        segment_end = min(end, next_day - timedelta(days=1) if next_day else end)
        if segment_start <= segment_end:
            result.append(
                {
                    "component": "stampDuty",
                    "startDate": segment_start.isoformat(),
                    "endDate": segment_end.isoformat(),
                    "buyerRate": str(buyer_rate),
                    "sellerRate": str(seller_rate),
                    "side": "by_side",
                }
            )
    return result


def fee_model_audit(
    params: Mapping[str, Any] | None,
    symbols: Sequence[str],
    start: str,
    end: str,
) -> dict[str, Any] | None:
    """Build verified fee provenance; legacy runs deliberately have no audit."""
    fee_model = normalize_fee_model(params)
    if fee_model != VERIFIED_FEE_MODEL:
        return None
    canonical_symbols = _normalize_symbols(symbols)
    start_day = _iso_day(start, "startDate")
    end_day = _iso_day(end, "endDate")
    if start_day > end_day:
        raise BacktestInputError("startDate不能晚于endDate")
    values = params or {}
    commission_bps = _as_decimal(
        _param(values, "commissionBps", "commission_bps", 3), "commissionBps"
    )
    minimum_commission = _as_decimal(
        _param(values, "minimumCommission", "minimum_commission", 5),
        "minimumCommission",
    )
    _validate_verified_terms(start_day, end_day, commission_bps, minimum_commission)
    # Reuse the execution gate so the audit can never describe a range that
    # the engine would reject.
    for symbol in canonical_symbols:
        validate_fee_window(symbol, start, end, values)

    rate_floor_bps = max(
        _commission_floor_rate(start_day), _commission_floor_rate(end_day)
    ) * _BPS
    rates: list[dict[str, str]] = [
        {
            "component": "commission",
            "startDate": start_day.isoformat(),
            "endDate": end_day.isoformat(),
            "rateBps": str(commission_bps),
            "minimumYuan": str(minimum_commission),
            "minimumRateBps": str(rate_floor_bps),
            "maximumRateBps": str(_COMMISSION_MAX_RATE * _BPS),
            "side": "both",
        },
        *_rate_segments(
            start_day,
            end_day,
            _HANDLING_FEE_CHANGES,
            component="handlingFee",
            side="both",
        ),
        {
            "component": "regulatoryFee",
            "startDate": start_day.isoformat(),
            "endDate": end_day.isoformat(),
            "rate": str(_REGULATORY_FEE_RATE),
            "side": "both",
        },
        *_rate_segments(
            start_day,
            end_day,
            _TRANSFER_FEE_CHANGES,
            component="transferFee",
            side="both",
        ),
        *_stamp_rate_segments(start_day, end_day),
    ]
    source_urls = [
        _COMMISSION_URL,
        _STAMP_2008_RATE_URL,
        _STAMP_2008_SIDE_URL,
        _STAMP_2023_URL,
        _SSE_2015_URL,
        _SZSE_2015_URL,
        _TRANSFER_HISTORY_URL,
        _SSE_2023_URL,
        _SZSE_2023_URL,
        _SSE_CURRENT_FEES_URL,
        _SZSE_CURRENT_FEES_URL,
    ]
    return {
        "feeModel": fee_model,
        "version": fee_model,
        "startDate": start_day.isoformat(),
        "endDate": end_day.isoformat(),
        "symbols": canonical_symbols,
        "commissionIncludes": ["证券交易经手费", "证券交易监管费"],
        "roundingStatus": "unverified_broker_settlement",
        "minimumGranularity": "simulated_order",
        "sourceURLs": source_urls,
        "rates": rates,
        "notice": (
            "佣金包含交易经手费和证管费，过户费与印花税另计。按模拟订单计算最低佣金；"
            "A股账户实际清算取分规则未核实，金额按四舍五入到分作为模型约定。"
            "过户费2022年调整以中国结算官网大事记及现行收费表为据，未找到原通知正文官网直链。"
        ),
    }
