"""Point-in-time A-share daily data snapshots for the finance backtest.

Tencent's CN ``day`` series contains unadjusted prices. Its qfq series is used
only as an integrity signal: material changes in the qfq/raw factor inside the
requested interval block legacy price-only runs. Opt-in cash-dividend runs
require a complete official-notice artifact and matching amount/date proof;
unsupported or unresolved actions still block execution.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from core.web.services import financial_market_service as market

from .transport import HistoricalReadError, read_historical

_SOURCE = "腾讯财经"
_SOURCE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
_QUOTE_URL = "https://gu.qq.com/{symbol}/gp"
_PROVIDER_LIMIT = 640
_PROVIDER_MAX_ROWS = _PROVIDER_LIMIT + 1  # Tencent's inclusive range can return 641 rows.
_MAX_BACKTEST_DAYS = 20 * 366
_MAX_TRADING_DAYS = 5_000
_DEFAULT_WARMUP_BARS = 252
_MAX_WARMUP_BARS = 252
_MAX_BOUNDARY_DISTANCE_DAYS = 10
_BEIJING = ZoneInfo("Asia/Shanghai")
_CALENDAR_SYMBOL = "sh000001"


class BacktestDataError(ValueError):
    """Historical data cannot support a complete, trustworthy backtest."""

    code = "backtest_data_unavailable"
    status_code = 422

    def __init__(self, message: str, *, metadata: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.metadata = dict(metadata or {})


class BacktestInputError(BacktestDataError):
    """The requested backtest range or input is outside supported bounds."""

    code = "invalid_backtest_input"


class CorporateActionUnsupported(BacktestDataError):
    """A corporate-action adjustment was detected but cannot be simulated."""

    code = "corporate_action_unsupported"

    def __init__(self, dates: tuple[str, ...]) -> None:
        super().__init__(
            "所选区间检测到分红、送转或其他公司行动；当前撮合引擎不能准确处理其现金与股数变化，已阻断回测。",
            metadata={"actionsStatus": "blocked", "actionDates": list(dates)},
        )
        self.action_dates = dates


@dataclass(frozen=True, slots=True)
class Candle:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True, slots=True)
class BacktestCoverage:
    requestedStartDate: str
    requestedEndDate: str
    actualStartDate: str
    actualEndDate: str
    availableStartDate: str
    availableEndDate: str
    tradingDays: int
    warmupBars: int
    providerWindows: tuple[Mapping[str, Any], ...]
    tradingCalendarStatus: str
    calendarSymbol: str
    complete: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "requestedStartDate": self.requestedStartDate,
            "requestedEndDate": self.requestedEndDate,
            "actualStartDate": self.actualStartDate,
            "actualEndDate": self.actualEndDate,
            "availableStartDate": self.availableStartDate,
            "availableEndDate": self.availableEndDate,
            "tradingDays": self.tradingDays,
            "warmupBars": self.warmupBars,
            "providerWindows": [dict(item) for item in self.providerWindows],
            "tradingCalendarStatus": self.tradingCalendarStatus,
            "calendarSymbol": self.calendarSymbol,
            "complete": self.complete,
        }


@dataclass(frozen=True, slots=True)
class BacktestSnapshot:
    symbol: str
    start_date: str
    end_date: str
    candles: tuple[Candle, ...]
    warmup_candles: tuple[Candle, ...]
    source: str
    source_url: str
    fetched_at: str
    data_hash: str
    coverage: BacktestCoverage
    actions_status: str
    action_dates: tuple[str, ...]
    notice: tuple[str, ...]
    corporate_actions: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a detached JSON-safe projection for job persistence and review."""
        result = {
            "symbol": self.symbol,
            "startDate": self.start_date,
            "endDate": self.end_date,
            "candles": [asdict(item) for item in self.candles],
            "warmupCandles": [asdict(item) for item in self.warmup_candles],
            "source": self.source,
            "sourceUrl": self.source_url,
            "fetchedAt": self.fetched_at,
            "dataHash": self.data_hash,
            "coverage": self.coverage.to_dict(),
            "actionsStatus": self.actions_status,
            "actionDates": list(self.action_dates),
            "notice": list(self.notice),
            "adjustment": "raw",
        }
        if self.corporate_actions is not None:
            from copy import deepcopy
            result["corporateActions"] = deepcopy(dict(self.corporate_actions))
        return result


def _parse_date(value: Any, label: str) -> date:
    if not isinstance(value, str):
        raise BacktestInputError(f"{label}必须是YYYY-MM-DD日期")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise BacktestInputError(f"{label}必须是YYYY-MM-DD日期") from exc
    if parsed.isoformat() != value:
        raise BacktestInputError(f"{label}必须是YYYY-MM-DD日期")
    return parsed


def _request_values(payload: Mapping[str, Any], today: date) -> tuple[str, date, date, int]:
    try:
        symbol = market.normalize_a_share_symbol(str(payload.get("symbol") or ""))
    except market.MarketDataError as exc:
        raise BacktestInputError(str(exc)) from exc
    requested_start = _parse_date(payload.get("startDate"), "startDate")
    requested_end = _parse_date(payload.get("endDate"), "endDate")
    if requested_start > requested_end:
        raise BacktestInputError("startDate不能晚于endDate")
    if requested_start > today or requested_end >= today:
        raise BacktestInputError("历史回测日期必须早于北京时间今天")
    if (requested_end - requested_start).days > _MAX_BACKTEST_DAYS:
        raise BacktestInputError("回测日期跨度最多20年，不能自动截断区间")

    raw_warmup = payload.get("warmupBars", _DEFAULT_WARMUP_BARS)
    if isinstance(raw_warmup, bool):
        raise BacktestInputError("warmupBars必须是0到252之间的整数")
    try:
        warmup_bars = int(raw_warmup)
    except (TypeError, ValueError, OverflowError) as exc:
        raise BacktestInputError("warmupBars必须是0到252之间的整数") from exc
    if warmup_bars != raw_warmup or not 0 <= warmup_bars <= _MAX_WARMUP_BARS:
        raise BacktestInputError("warmupBars必须是0到252之间的整数")
    return symbol, requested_start, requested_end, warmup_bars


def _query_years(start: date, end: date) -> tuple[tuple[date, date], ...]:
    windows: list[tuple[date, date]] = []
    first_year = max(1990, start.year)
    for year in range(first_year, end.year + 1):
        left = date(year, 1, 1)
        right = min(end, date(year, 12, 31))
        if left <= right:
            windows.append((left, right))
    return tuple(windows)


def _fetch_window(symbol: str, start: date, end: date, adjustment: str) -> list[list[str]]:
    param = f"{symbol},day,{start.isoformat()},{end.isoformat()},{_PROVIDER_LIMIT},{adjustment}"
    url = _SOURCE_URL + "?" + urlencode({"param": param})
    kind = "交易日历" if symbol == _CALENDAR_SYMBOL else ("前复权校验" if adjustment == "qfq" else "原始价格")
    context = f"{symbol} {start.isoformat()}至{end.isoformat()} · {kind}"
    try:
        raw = read_historical(url)
        payload = json.loads(raw)
    except HistoricalReadError as exc:
        raise BacktestDataError(f"腾讯历史日K读取失败（{context}）：{exc}") from exc
    except (json.JSONDecodeError, TypeError) as exc:
        raise BacktestDataError(f"腾讯历史日K格式无效（{context}）") from exc
    if not isinstance(payload, dict) or type(payload.get("code")) is not int or payload["code"] != 0:
        raise BacktestDataError(f"腾讯历史日K返回无效状态（{context}）")
    stocks = payload.get("data")
    if not isinstance(stocks, dict):
        raise BacktestDataError(f"腾讯历史日K股票映射格式无效（{context}）")
    stock = stocks.get(symbol)
    if stock is None:
        return []
    if not isinstance(stock, dict):
        raise BacktestDataError(f"腾讯历史日K缺少请求股票（{context}）")
    key = "qfqday" if adjustment == "qfq" else "day"
    rows = stock.get(key)
    if rows is None:
        return []
    if not isinstance(rows, list) or len(rows) > _PROVIDER_MAX_ROWS:
        raise BacktestDataError(f"腾讯历史日K超出单窗上限或格式无效（{context}）")
    if any(not isinstance(row, list) or len(row) < 6 for row in rows):
        raise BacktestDataError(f"腾讯历史日K行格式无效（{context}）")
    return rows


def _parse_rows(rows: list[list[str]], symbol: str) -> list[dict[str, Any]]:
    """Pass bounded chunks through Tencent's existing OHLCV parser.

    The parser intentionally keeps ordinary market responses at 120 bars and
    selects CN qfq by default. Here the provider window is already adjustment
    specific; staging at most 120 rows under its daily key preserves the raw
    numbers while reusing its date, OHLC and volume validation.
    """
    parsed: list[dict[str, Any]] = []
    for offset in range(0, len(rows), 120):
        chunk = rows[offset : offset + 120]
        envelope = {"code": 0, "data": {symbol: {"qfqday": chunk}}}
        try:
            parsed.extend(
                market.parse_candles(
                    json.dumps(envelope, ensure_ascii=False, separators=(",", ":")),
                    symbol,
                    "day",
                )
            )
        except market.MarketDataError as exc:
            raise BacktestDataError(f"腾讯历史日K校验失败：{exc}") from exc
    return parsed


def _parse_window(rows: list[list[str]], symbol: str, year: int) -> dict[str, dict[str, Any]]:
    parsed = _parse_rows(rows, symbol)
    by_date: dict[str, dict[str, Any]] = {}
    for row in parsed:
        candle_date = row["date"]
        if candle_date in by_date:
            raise BacktestDataError(f"腾讯历史日K存在重复日期：{candle_date}")
        if not date.fromisoformat(candle_date).year == year:
            raise BacktestDataError(f"腾讯历史日K越过年度窗口：{candle_date}")
        original = next(item for item in rows if item[0] == candle_date)
        row["_providerPrices"] = {
            "open": str(original[1]),
            "close": str(original[2]),
            "high": str(original[3]),
            "low": str(original[4]),
        }
        by_date[candle_date] = row
    return by_date


def _validate_pair(
    raw_rows: list[list[str]], qfq_rows: list[list[str]], symbol: str, year: int
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    raw = _parse_window(raw_rows, symbol, year)
    qfq = _parse_window(qfq_rows, symbol, year)
    if set(raw) != set(qfq):
        raise BacktestDataError(f"腾讯 raw/qfq 历史日期覆盖不一致（{year}）")
    return raw, qfq


def _calendar_window(rows: list[list[str]], year: int) -> tuple[str, ...]:
    """Validate the Shanghai Composite index dates with the shared candle parser."""
    # The existing parser accepts security symbols only. This temporary parser
    # key is discarded; only dates from the requested sh000001 provider rows
    # are kept as a Tencent-derived exchange-session cross-check.
    parsed = _parse_rows(rows, "sz399001")
    dates = tuple(row["date"] for row in parsed)
    if any(date.fromisoformat(item).year != year for item in dates):
        raise BacktestDataError(f"腾讯交易日历越过年度窗口：{year}")
    if len(set(dates)) != len(dates) or tuple(sorted(dates)) != dates:
        raise BacktestDataError(f"腾讯交易日历存在重复或乱序日期：{year}")
    return dates


def _transformation_intervals(
    raw_prices: Mapping[str, str], qfq_prices: Mapping[str, str],
) -> dict[str, tuple[Decimal, Decimal]]:
    additive_low, additive_high = Decimal("-Infinity"), Decimal("Infinity")
    factor_low, factor_high = Decimal("-Infinity"), Decimal("Infinity")
    for field in ("open", "high", "low", "close"):
        try:
            raw_value = Decimal(raw_prices[field])
            qfq_text = qfq_prices[field]
            qfq_value = Decimal(qfq_text)
            if not raw_value.is_finite() or not qfq_value.is_finite() or raw_value <= 0 or qfq_value <= 0:
                return {}
            decimals = len(qfq_text.partition(".")[2]) if "." in qfq_text else 0
            rounding = Decimal("0.5") * (Decimal(10) ** -decimals)
            additive_low = max(additive_low, qfq_value - raw_value - rounding)
            additive_high = min(additive_high, qfq_value - raw_value + rounding)
            factor_low = max(factor_low, (qfq_value - rounding) / raw_value)
            factor_high = min(factor_high, (qfq_value + rounding) / raw_value)
        except (KeyError, InvalidOperation, TypeError, AttributeError):
            return {}
    result = {}
    if additive_low <= additive_high:
        result["additive"] = (additive_low, additive_high)
    if factor_low <= factor_high:
        result["multiplicative"] = (factor_low, factor_high)
    return result


def _action_dates(
    raw: Mapping[str, Mapping[str, Any]],
    qfq: Mapping[str, Mapping[str, Any]],
    start: date,
    end: date,
) -> tuple[str, ...]:
    dates = sorted(set(raw) & set(qfq))
    transformations: list[tuple[str, dict[str, tuple[Decimal, Decimal]]]] = []
    for candle_date in dates:
        raw_prices = raw[candle_date].get("_providerPrices")
        qfq_prices = qfq[candle_date].get("_providerPrices")
        if not isinstance(raw_prices, Mapping) or not isinstance(qfq_prices, Mapping):
            continue
        # Rounded prices can satisfy both hypotheses on a quiet session. Keep
        # both: choosing additive first can invent an action on the next bar.
        hypotheses = _transformation_intervals(raw_prices, qfq_prices)
        if hypotheses:
            transformations.append((candle_date, hypotheses))
        else:
            parsed_date = date.fromisoformat(candle_date)
            if start <= parsed_date <= end:
                return (candle_date,)

    detected: list[str] = []
    for previous, current in pairwise(transformations):
        _previous_date, previous_models = previous
        current_date, current_models = current
        parsed_date = date.fromisoformat(current_date)
        if parsed_date < start or parsed_date > end:
            continue
        overlap = any(
            max(previous_models[kind][0], current_models[kind][0])
            <= min(previous_models[kind][1], current_models[kind][1])
            for kind in previous_models.keys() & current_models.keys()
        )
        if not overlap:
            detected.append(current_date)
    return tuple(detected)


def _boundary(rows: list[dict[str, Any]], requested: date, side: str) -> dict[str, Any]:
    if side == "start":
        candidates = [row for row in rows if date.fromisoformat(row["date"]) >= requested]
        row = candidates[0] if candidates else None
        distance = (date.fromisoformat(row["date"]) - requested).days if row else None
    else:
        candidates = [row for row in rows if date.fromisoformat(row["date"]) <= requested]
        row = candidates[-1] if candidates else None
        distance = (requested - date.fromisoformat(row["date"])).days if row else None
    if row is None or distance is None or distance > _MAX_BOUNDARY_DISTANCE_DAYS:
        raise BacktestDataError(
            f"{side}Date附近缺少历史日K覆盖，不能截断回测区间",
            metadata={"boundary": side, "requestedDate": requested.isoformat()},
        )
    return row


def _stable_hash(
    rows: tuple[Candle, ...], symbol: str, start: str, end: str,
    corporate_actions: Mapping[str, Any] | None = None,
) -> str:
    payload = {
        "symbol": symbol,
        "adjustment": "raw",
        "startDate": start,
        "endDate": end,
        "candles": [asdict(row) for row in rows],
    }
    if corporate_actions is not None:
        payload["corporateActions"] = dict(corporate_actions)
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def validate_snapshot(snapshot: BacktestSnapshot) -> None:
    """Fail closed if a frozen snapshot is incomplete, corrupt, or out of order."""
    if not isinstance(snapshot, BacktestSnapshot):
        raise BacktestDataError("回测数据快照类型无效")
    if snapshot.corporate_actions is None:
        if snapshot.actions_status != "factor_check_passed" or snapshot.action_dates:
            raise BacktestDataError("回测快照公司行动状态未通过")
    else:
        from .cash_action_snapshot import validate_action_snapshot
        validate_action_snapshot(snapshot)
    if not isinstance(snapshot.coverage, BacktestCoverage):
        raise BacktestDataError("回测快照覆盖信息无效")
    coverage = snapshot.coverage
    if coverage.complete is not True:
        raise BacktestDataError("回测快照数据覆盖不完整")
    if (
        coverage.tradingCalendarStatus not in {"tencent_index_checked", "eastmoney_index_checked", "sina_index_checked"}
        or coverage.calendarSymbol != _CALENDAR_SYMBOL
    ):
        raise BacktestDataError("回测快照未通过交易日历交叉检查")
    if not isinstance(coverage.providerWindows, tuple) or any(
        not isinstance(item, Mapping) for item in coverage.providerWindows
    ):
        raise BacktestDataError("回测快照行情来源窗口格式无效")
    try:
        canonical_symbol = market.normalize_a_share_symbol(snapshot.symbol)
    except (market.MarketDataError, TypeError) as exc:
        raise BacktestDataError("回测快照股票代码无效") from exc
    if canonical_symbol != snapshot.symbol:
        raise BacktestDataError("回测快照股票代码未规范化")
    if not isinstance(snapshot.candles, tuple) or not 1 <= len(snapshot.candles) <= _MAX_TRADING_DAYS:
        raise BacktestDataError("回测快照区间K线数量无效")
    if not isinstance(snapshot.warmup_candles, tuple) or len(snapshot.warmup_candles) > _MAX_WARMUP_BARS:
        raise BacktestDataError("回测快照预热K线数量无效")

    all_rows = snapshot.warmup_candles + snapshot.candles
    prior_day: date | None = None
    for candle in all_rows:
        if not isinstance(candle, Candle):
            raise BacktestDataError("回测快照K线格式无效")
        try:
            parsed_day = date.fromisoformat(candle.date)
        except (TypeError, ValueError) as exc:
            raise BacktestDataError("回测快照包含无效K线日期") from exc
        if parsed_day.isoformat() != candle.date or (prior_day is not None and parsed_day <= prior_day):
            raise BacktestDataError("回测快照K线日期重复或乱序")
        prior_day = parsed_day
        values = (candle.open, candle.high, candle.low, candle.close, candle.volume)
        try:
            finite_values = all(
                not isinstance(value, bool)
                and isinstance(value, (int, float))
                and math.isfinite(float(value))
                for value in values
            )
        except (OverflowError, TypeError, ValueError):
            finite_values = False
        if not finite_values:
            raise BacktestDataError("回测快照包含非有限行情数值")
        if (
            candle.open <= 0
            or candle.close <= 0
            or candle.high <= 0
            or candle.low <= 0
            or candle.volume < 0
            or candle.low > min(candle.open, candle.close)
            or candle.high < max(candle.open, candle.close)
            or candle.low > candle.high
        ):
            raise BacktestDataError("回测快照OHLCV关系无效")

    start_date = snapshot.candles[0].date
    end_date = snapshot.candles[-1].date
    available_start = all_rows[0].date
    try:
        requested_start = date.fromisoformat(coverage.requestedStartDate)
        requested_end = date.fromisoformat(coverage.requestedEndDate)
        actual_start = date.fromisoformat(coverage.actualStartDate)
        actual_end = date.fromisoformat(coverage.actualEndDate)
        available_start_day = date.fromisoformat(coverage.availableStartDate)
        available_end = date.fromisoformat(coverage.availableEndDate)
    except (TypeError, ValueError) as exc:
        raise BacktestDataError("回测快照覆盖日期无效") from exc
    if any(
        parsed.isoformat() != value
        for parsed, value in (
            (requested_start, coverage.requestedStartDate),
            (requested_end, coverage.requestedEndDate),
            (actual_start, coverage.actualStartDate),
            (actual_end, coverage.actualEndDate),
            (available_start_day, coverage.availableStartDate),
            (available_end, coverage.availableEndDate),
        )
    ):
        raise BacktestDataError("回测快照覆盖日期格式无效")
    if (
        requested_start > requested_end
        or not requested_start <= actual_start <= actual_end <= requested_end
        or snapshot.start_date != start_date
        or snapshot.end_date != end_date
        or coverage.actualStartDate != start_date
        or coverage.actualEndDate != end_date
        or coverage.availableStartDate != available_start
        or coverage.availableEndDate != end_date
        or type(coverage.tradingDays) is not int
        or coverage.tradingDays != len(snapshot.candles)
        or type(coverage.warmupBars) is not int
        or coverage.warmupBars != len(snapshot.warmup_candles)
        or (snapshot.warmup_candles and snapshot.warmup_candles[-1].date >= start_date)
    ):
        raise BacktestDataError("回测快照覆盖边界与K线不一致")

    expected_hash = _stable_hash(all_rows, snapshot.symbol, snapshot.start_date, snapshot.end_date, snapshot.corporate_actions)
    if snapshot.data_hash != expected_hash:
        raise BacktestDataError("回测快照行情摘要校验失败")


def prepare_data(
    payload: Mapping[str, Any], *, today: date | datetime | str | None = None
) -> BacktestSnapshot:
    """Select one whole provider snapshot; never splice sources into a series."""
    from dataclasses import replace

    from . import eastmoney, sina

    source = payload.get("dataSource", "tencent")
    if source not in {"tencent", "eastmoney", "sina", "auto"}:
        raise BacktestInputError("dataSource必须是tencent、eastmoney、sina或auto")
    if source == "tencent":
        return _prepare_data(payload, today=today)
    if source in {"eastmoney", "sina"}:
        name = "东方财富" if source == "eastmoney" else "新浪"
        fetch_window = eastmoney.fetch_window if source == "eastmoney" else sina.fetch_window
        try:
            return _prepare_data(payload, today=today, fetcher=fetch_window, provider=source)
        except (BacktestInputError, CorporateActionUnsupported):
            raise
        except BacktestDataError as exc:
            raise BacktestDataError(str(exc).replace("腾讯", name), metadata=exc.metadata) from exc
    failures: dict[str, str] = {}
    for provider in ("tencent", "eastmoney", "sina"):
        try:
            snapshot = prepare_data({**payload, "dataSource": provider}, today=today)
        except (BacktestInputError, CorporateActionUnsupported):
            raise
        except BacktestDataError as exc:
            failures[provider] = str(exc)[:500]
            continue
        if failures:
            return replace(snapshot, notice=snapshot.notice + (f"主来源未通过，本次全部行情改用{snapshot.source}重新验证；未混用来源。",))
        return snapshot
    raise BacktestDataError(
        "公开历史来源均未通过。" + "；".join(f"{name}：{reason}" for name, reason in failures.items()),
        metadata={"sourceFailures": failures},
    )


def _prepare_data(
    payload: Mapping[str, Any], *, today: date | datetime | str | None = None,
    fetcher: Callable | None = None, provider: str = "tencent",
) -> BacktestSnapshot:
    """Fetch and freeze multi-year raw daily candles, without any quote fallback."""
    if today is None:
        cutoff = datetime.now(_BEIJING).date()
    elif isinstance(today, datetime):
        cutoff = today.astimezone(_BEIJING).date() if today.tzinfo else today.date()
    elif isinstance(today, date):
        cutoff = today
    else:
        cutoff = _parse_date(today, "today")

    symbol, requested_start, requested_end, warmup_bars = _request_values(payload, cutoff)
    selected_fetch = fetcher or _fetch_window
    source_names = {"tencent": "腾讯财经", "eastmoney": "东方财富", "sina": "新浪财经"}
    if provider not in source_names:
        raise BacktestInputError("历史行情提供方无效")
    source_name = source_names[provider]
    raw_by_date: dict[str, dict[str, Any]] = {}
    qfq_by_date: dict[str, dict[str, Any]] = {}
    calendar_dates: set[str] = set()
    provider_windows: list[dict[str, Any]] = []

    def fetch_year(window_start: date, window_end: date) -> None:
        raw_rows = selected_fetch(symbol, window_start, window_end, "none")
        qfq_rows = selected_fetch(symbol, window_start, window_end, "qfq")
        calendar_rows = selected_fetch(_CALENDAR_SYMBOL, window_start, window_end, "none")
        raw_window, qfq_window = _validate_pair(raw_rows, qfq_rows, symbol, window_start.year)
        index_dates = _calendar_window(calendar_rows, window_start.year)
        if set(raw_window) & set(raw_by_date):
            raise BacktestDataError("腾讯年度历史窗口存在重叠日期")
        if set(index_dates) & calendar_dates:
            raise BacktestDataError("腾讯指数交易日历年度窗口存在重叠日期")
        raw_by_date.update(raw_window)
        qfq_by_date.update(qfq_window)
        calendar_dates.update(index_dates)
        provider_windows.append(
            {
                "startDate": window_start.isoformat(),
                "endDate": window_end.isoformat(),
                "rawBars": len(raw_rows),
                "qfqBars": len(qfq_rows),
                "calendarBars": len(calendar_rows),
            }
        )

    def has_warmup_and_qfq_baseline() -> bool:
        requested_start_text = requested_start.isoformat()
        warmup_count = sum(day < requested_start_text for day in raw_by_date)
        has_paired_baseline = any(
            day < requested_start_text and day in qfq_by_date for day in raw_by_date
        )
        return warmup_count >= warmup_bars and has_paired_baseline

    # Fetch every year intersecting the requested backtest range first. The
    # first year's January-through-requested-start rows can also serve as
    # warm-up data and the pre-start qfq baseline.
    for window_start, window_end in _query_years(requested_start, requested_end):
        fetch_year(window_start, window_end)

    # Only fetch older, warm-up-only years if the requested years do not yet
    # contain enough raw bars and an explicit pre-start raw/qfq pair. Keep the
    # existing two-year history bound and validate every fetched pair strictly.
    first_warmup_year = max(1990, requested_start.year - 2)
    for year in range(requested_start.year - 1, first_warmup_year - 1, -1):
        if has_warmup_and_qfq_baseline():
            break
        fetch_year(date(year, 1, 1), date(year, 12, 31))

    today_text = cutoff.isoformat()
    completed_dates = sorted(
        candle_date
        for candle_date in raw_by_date
        if candle_date < today_text
        and requested_start <= date.fromisoformat(candle_date) <= requested_end
    )
    all_dates = sorted(
        candle_date
        for candle_date in raw_by_date
        if candle_date < today_text and date.fromisoformat(candle_date) <= requested_end
    )
    requested_calendar = sorted(
        item
        for item in calendar_dates
        if requested_start <= date.fromisoformat(item) <= requested_end and item < today_text
    )
    if not requested_calendar:
        raise BacktestDataError("所选区间没有腾讯上证指数交易日历覆盖")
    if not completed_dates:
        raise BacktestDataError("所选区间没有完整历史日K数据")
    if len(completed_dates) > _MAX_TRADING_DAYS:
        raise BacktestInputError("回测区间最多5000个交易日，不能自动截断区间")

    missing_stock_bars = sorted(set(requested_calendar) - set(completed_dates))
    extra_stock_bars = sorted(set(completed_dates) - set(requested_calendar))
    if missing_stock_bars or extra_stock_bars:
        raise BacktestDataError(
            "股票日K与腾讯上证指数交易日历不一致，可能停牌或行情源缺bar，无法安全撮合；已阻断回测。",
            metadata={
                "tradingCalendarStatus": "mismatch",
                "calendarSymbol": _CALENDAR_SYMBOL,
                "missingStockBarDates": missing_stock_bars[:100],
                "unexpectedStockBarDates": extra_stock_bars[:100],
            },
        )

    start_row = _boundary(
        [{"date": item} for item in requested_calendar], requested_start, "start"
    )
    end_row = _boundary(
        [{"date": item} for item in requested_calendar], requested_end, "end"
    )
    actual_start = date.fromisoformat(start_row["date"])
    actual_end = date.fromisoformat(end_row["date"])
    if actual_start > actual_end:
        raise BacktestDataError("按交易日对齐后没有可回测区间")
    if (requested_end - actual_end).days > _MAX_BOUNDARY_DISTANCE_DAYS:
        raise BacktestDataError("endDate之后缺少近期历史日K，数据源覆盖过旧")

    selected_dates = [
        candle_date
        for candle_date in completed_dates
        if actual_start <= date.fromisoformat(candle_date) <= actual_end
    ]
    prior_dates = [candle_date for candle_date in all_dates if date.fromisoformat(candle_date) < actual_start]
    warmup_dates = prior_dates[-warmup_bars:] if warmup_bars else []
    if len(warmup_dates) < warmup_bars:
        raise BacktestDataError(
            f"所选起始日之前只有{len(warmup_dates)}根完整预热日K，需要{warmup_bars}根"
        )
    if not any(
        candle_date < actual_start.isoformat() and candle_date in qfq_by_date
        for candle_date in raw_by_date
    ):
        raise BacktestDataError("所选起始日之前缺少 raw/qfq 成对基准，无法核验公司行动")

    action_dates = _action_dates(
        raw_by_date, qfq_by_date, actual_start, actual_end
    )
    policy = payload.get("corporateActionPolicy", "block")
    if policy not in {"block", "verified_cash_dividends"}:
        raise BacktestInputError("corporateActionPolicy不是支持的公司行动策略")
    corporate_actions = None
    if policy == "verified_cash_dividends":
        from .cash_action_snapshot import prepare_action_snapshot
        corporate_actions = prepare_action_snapshot(
            symbol, actual_start.isoformat(), actual_end.isoformat(),
            raw_by_date, qfq_by_date, action_dates,
        )
    elif action_dates:
        raise CorporateActionUnsupported(action_dates)

    def make_candle(candle_date: str) -> Candle:
        row = raw_by_date[candle_date]
        return Candle(
            date=candle_date,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row.get("volume") or 0.0),
        )

    candles = tuple(make_candle(candle_date) for candle_date in selected_dates)
    warmup = tuple(make_candle(candle_date) for candle_date in warmup_dates)
    all_snapshot_rows = warmup + candles
    actual_start_text = candles[0].date
    actual_end_text = candles[-1].date
    available_start = all_snapshot_rows[0].date
    available_end = all_snapshot_rows[-1].date
    provider_windows.sort(key=lambda item: (item["startDate"], item["endDate"]))
    coverage = BacktestCoverage(
        requestedStartDate=requested_start.isoformat(),
        requestedEndDate=requested_end.isoformat(),
        actualStartDate=actual_start_text,
        actualEndDate=actual_end_text,
        availableStartDate=available_start,
        availableEndDate=available_end,
        tradingDays=len(candles),
        warmupBars=len(warmup),
        providerWindows=tuple(provider_windows),
        tradingCalendarStatus=f"{provider}_index_checked",
        calendarSymbol=_CALENDAR_SYMBOL,
        complete=True,
    )
    notice = (
        f"使用{source_name} A 股 raw 日线；当日收盘生成决策，下一条已完成交易日开盘撮合。",
        "回测最多20年、5000个区间交易日、252根预热K线；AI决策最多500次。",
        f"逐日覆盖已与{source_name}上证指数 raw 日K日期比对；该指数日历不是交易所官方停牌/复牌审计源。",
        "qfq/raw OHLC量化区间检查复权变换是否变化；此行情接口未提供完整公司行动清单，细小或复杂行动仍可能无法识别。",
    )
    if corporate_actions is not None:
        notice += (
            "现金分红使用冻结官方实施公告和raw/qfq价差双重核验；登记日收盘确定权益，到账日收盘后才增加可用现金。",
            "红利税按FIFO及自然月/年持有期限记账；送转、配股和无法匹配的公司行动仍阻断。公开公告查询覆盖有界，不能替代中国结算账户记录。",
        )
    snapshot = BacktestSnapshot(
        symbol=symbol,
        start_date=actual_start_text,
        end_date=actual_end_text,
        candles=candles,
        warmup_candles=warmup,
        source=source_name,
        source_url=(
            _QUOTE_URL.format(symbol=symbol) if provider == "tencent" else
            f"https://quote.eastmoney.com/{symbol}.html" if provider == "eastmoney" else
            "https://quotes.sina.cn/cn/api/jsonp_v2.php/=/CN_MarketDataService.getKLineData?"
            + urlencode({"symbol": symbol, "scale": "240", "ma": "no", "datalen": "1023"})
        ),
        fetched_at=datetime.now(_BEIJING).isoformat(timespec="seconds"),
        data_hash=_stable_hash(all_snapshot_rows, symbol, actual_start_text, actual_end_text, corporate_actions),
        coverage=coverage,
        actions_status="verified_cash_dividends" if corporate_actions is not None else "factor_check_passed",
        action_dates=action_dates if corporate_actions is not None else (),
        notice=notice,
        corporate_actions=corporate_actions,
    )
    validate_snapshot(snapshot)
    return snapshot


__all__ = [
    "BacktestCoverage",
    "BacktestDataError",
    "BacktestInputError",
    "BacktestSnapshot",
    "Candle",
    "CorporateActionUnsupported",
    "prepare_data",
    "validate_snapshot",
]
