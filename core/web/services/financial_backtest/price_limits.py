"""Frozen user-supplied A-share daily price-limit evidence.

The artifact records user-supplied values and provenance metadata only. A URL,
host allowlist, timestamp, or content hash does not prove that the source is
official, complete, or authentic. This module is deliberately offline and
never infers a limit from a stock category or a percentage band.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlsplit

from core.web.services import financial_market_service as market
from core.web.services.financial_backtest.data import BacktestInputError

LEGACY_LIMIT_MODEL = "candidate_bands_v1"
SUPPLIED_LIMIT_MODEL = "supplied_daily_limits_v1"

_SCHEMA_VERSION = 1
_MAX_RECORDS = 5_000
_MAX_PRICE = Decimal(10_000_000)
_CENT = Decimal("0.01")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PRICE_RE = re.compile(r"^(?:0|[1-9]\d{0,7})(?:\.\d{1,2})?$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_UTC_TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$"
)
_ARTIFACT_FIELDS = {"schemaVersion", "symbol", "source", "records"}
_SOURCE_FIELDS = {"url", "sha256", "fetchedAt"}
_RECORD_FIELDS = {"date", "upper", "lower"}
_SOURCE_HOSTS = ("sse.com.cn", "szse.cn", "bse.cn", "cninfo.com.cn")


def normalize_limit_model(payload: Mapping[str, Any] | None) -> str:
    """Resolve an opt-in limit model while preserving legacy defaults."""

    if payload is None:
        return LEGACY_LIMIT_MODEL
    if not isinstance(payload, Mapping):
        raise BacktestInputError("回测参数必须是对象")
    camel = "priceLimitModel"
    snake = "price_limit_model"
    if camel in payload and snake in payload and payload[camel] != payload[snake]:
        raise BacktestInputError("priceLimitModel与price_limit_model不能同时指定不同值")
    value = payload[camel] if camel in payload else payload.get(snake)
    if value is None:
        return LEGACY_LIMIT_MODEL
    if not isinstance(value, str) or value not in {
        LEGACY_LIMIT_MODEL,
        SUPPLIED_LIMIT_MODEL,
    }:
        raise BacktestInputError("priceLimitModel不是支持的涨跌停模型")
    return value


def freeze_price_limits(
    payload: Mapping[str, Any],
    symbol: str,
    dates: Sequence[str],
    candles: Sequence[Any],
) -> dict[str, Any]:
    """Canonicalize and hash a user-supplied daily limit artifact offline."""

    if not isinstance(payload, Mapping):
        raise BacktestInputError("涨跌停快照必须是对象")
    allowed_fields = _ARTIFACT_FIELDS | {"artifactHash"}
    if set(payload) != _ARTIFACT_FIELDS and set(payload) != allowed_fields:
        raise BacktestInputError("涨跌停快照字段不完整或包含未知字段")

    normalized = _canonical_artifact(payload, expected_symbol=symbol)
    _validate_coverage_and_candles(normalized["records"], dates, candles)
    if "artifactHash" in payload:
        supplied_hash = payload["artifactHash"]
        if not isinstance(supplied_hash, str) or not _SHA256_RE.fullmatch(supplied_hash):
            raise BacktestInputError("涨跌停快照摘要无效")
        if supplied_hash != _artifact_hash(normalized):
            raise BacktestInputError("涨跌停快照摘要与内容不匹配")
    normalized["artifactHash"] = _artifact_hash(normalized)
    return copy.deepcopy(normalized)


def validate_price_limits(
    artifact: Mapping[str, Any],
    symbol: str,
    dates: Sequence[str],
    candles: Sequence[Any],
) -> dict[str, Any]:
    """Verify the full frozen contract and every supplied OHLC bound."""

    if not isinstance(artifact, Mapping) or set(artifact) != (
        _ARTIFACT_FIELDS | {"artifactHash"}
    ):
        raise BacktestInputError("涨跌停快照格式或字段无效")
    supplied_hash = artifact.get("artifactHash")
    if not isinstance(supplied_hash, str) or not _SHA256_RE.fullmatch(supplied_hash):
        raise BacktestInputError("涨跌停快照摘要无效")

    normalized = _canonical_artifact(artifact, expected_symbol=symbol)
    expected_dates = _expected_dates(dates)
    record_dates = [row["date"] for row in normalized["records"]]
    if record_dates != expected_dates:
        raise BacktestInputError("涨跌停快照日期必须与回测K线日期完整一致")
    if supplied_hash != _artifact_hash(normalized):
        raise BacktestInputError("涨跌停快照摘要与内容不匹配")
    _validate_coverage_and_candles(normalized["records"], expected_dates, candles)
    normalized["artifactHash"] = supplied_hash
    return copy.deepcopy(normalized)


def slice_price_limits(
    artifact: Mapping[str, Any], dates: Sequence[str]
) -> dict[str, Any]:
    """Return a rehashed artifact containing exactly the requested subset."""

    normalized = _canonical_artifact(artifact)
    supplied_hash = artifact.get("artifactHash") if isinstance(artifact, Mapping) else None
    if not isinstance(supplied_hash, str) or not _SHA256_RE.fullmatch(supplied_hash):
        raise BacktestInputError("涨跌停快照摘要无效")
    if supplied_hash != _artifact_hash(normalized):
        raise BacktestInputError("涨跌停快照摘要与内容不匹配")

    selected_dates = _expected_dates(dates)
    indexed = {record["date"]: record for record in normalized["records"]}
    if any(day not in indexed for day in selected_dates):
        raise BacktestInputError("滚动窗口日期超出涨跌停快照覆盖范围")
    sliced = {
        **normalized,
        "records": [copy.deepcopy(indexed[day]) for day in selected_dates],
    }
    sliced["artifactHash"] = _artifact_hash(sliced)
    return copy.deepcopy(sliced)


def locked_reason(candle: Any, side: str, record: Mapping[str, Any]) -> str | None:
    """Block a buy/sell opened exactly at its supplied daily limit price."""

    if not isinstance(side, str) or side not in {"buy", "sell"}:
        raise BacktestInputError("涨跌停检查交易方向必须是buy或sell")
    if not isinstance(record, Mapping):
        raise BacktestInputError("涨跌停日记录必须是对象")
    bound = record.get("upper" if side == "buy" else "lower")
    if bound is None:
        return None
    try:
        limit_price = _price_decimal(bound, "涨跌停价格")
        open_price = _candle_decimal(_candle_value(candle, "open"), "开盘价")
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise BacktestInputError("涨跌停开盘价或限价无效") from exc
    if side == "buy" and open_price == limit_price:
        return "open_at_supplied_limit_up"
    if side == "sell" and open_price == limit_price:
        return "open_at_supplied_limit_down"
    return None


def _canonical_artifact(
    payload: Mapping[str, Any], *, expected_symbol: str | None = None
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise BacktestInputError("涨跌停快照必须是对象")
    fields = set(payload)
    if fields != _ARTIFACT_FIELDS and fields != (_ARTIFACT_FIELDS | {"artifactHash"}):
        raise BacktestInputError("涨跌停快照字段不完整或包含未知字段")
    if type(payload.get("schemaVersion")) is not int or payload["schemaVersion"] != _SCHEMA_VERSION:
        raise BacktestInputError("涨跌停快照版本不受支持")
    symbol = _canonical_symbol(payload.get("symbol"))
    if expected_symbol is not None and symbol != _canonical_symbol(expected_symbol):
        raise BacktestInputError("涨跌停快照标的与回测标的不匹配")

    records = payload.get("records")
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        raise BacktestInputError("涨跌停日记录必须是列表")
    if not records or len(records) > _MAX_RECORDS:
        raise BacktestInputError("涨跌停日记录数量必须为1到5000条")
    canonical_records = [_canonical_record(row) for row in records]
    record_dates = [row["date"] for row in canonical_records]
    if len(record_dates) != len(set(record_dates)):
        raise BacktestInputError("涨跌停日记录日期重复")
    if record_dates != sorted(record_dates):
        raise BacktestInputError("涨跌停日记录必须按日期排序")
    canonical_records.sort(key=lambda row: row["date"])

    return {
        "schemaVersion": _SCHEMA_VERSION,
        "symbol": symbol,
        "source": _canonical_source(payload.get("source")),
        "records": canonical_records,
    }


def _canonical_source(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != _SOURCE_FIELDS:
        raise BacktestInputError("涨跌停来源字段无效")
    url = value.get("url")
    if not isinstance(url, str) or len(url) > 2_048 or not url or any(
        ord(char) < 33 or ord(char) == 127 for char in url
    ):
        raise BacktestInputError("涨跌停来源URL无效")
    if "#" in url or "\\" in url:
        raise BacktestInputError("涨跌停来源URL不能包含片段或反斜线")
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise BacktestInputError("涨跌停来源URL无效") from exc
    if (
        parsed.scheme != "https"
        or not host
        or host.endswith(".")
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or not any(host == allowed or host.endswith(f".{allowed}") for allowed in _SOURCE_HOSTS)
    ):
        raise BacktestInputError("涨跌停来源URL必须是允许域名下的HTTPS地址")

    raw_digest = value.get("sha256")
    if not isinstance(raw_digest, str) or not _SHA256_RE.fullmatch(raw_digest):
        raise BacktestInputError("涨跌停来源sha256无效")
    fetched_at = _utc_timestamp(value.get("fetchedAt"))
    return {"url": url, "sha256": raw_digest.lower(), "fetchedAt": fetched_at}


def _canonical_record(value: Any) -> dict[str, str | None]:
    if not isinstance(value, Mapping) or set(value) != _RECORD_FIELDS:
        raise BacktestInputError("涨跌停日记录字段无效")
    day = _date_text(value.get("date"), "涨跌停日期")
    upper_raw, lower_raw = value.get("upper"), value.get("lower")
    if upper_raw is None or lower_raw is None:
        if upper_raw is not None or lower_raw is not None:
            raise BacktestInputError("无限幅记录的upper和lower必须同时为null")
        return {"date": day, "upper": None, "lower": None}
    upper = _price_decimal(upper_raw, "涨停价")
    lower = _price_decimal(lower_raw, "跌停价")
    if upper < lower:
        raise BacktestInputError("涨停价不能低于跌停价")
    return {
        "date": day,
        "upper": _price_text(upper),
        "lower": _price_text(lower),
    }


def _validate_coverage_and_candles(
    records: Sequence[Mapping[str, Any]], dates: Sequence[str], candles: Sequence[Any]
) -> None:
    expected_dates = _expected_dates(dates)
    if [row["date"] for row in records] != expected_dates:
        raise BacktestInputError("涨跌停快照日期必须与回测K线日期完整一致")
    if not isinstance(candles, Sequence) or isinstance(candles, (str, bytes)):
        raise BacktestInputError("回测K线必须是列表")
    if len(candles) != len(expected_dates) or len(candles) > _MAX_RECORDS:
        raise BacktestInputError("涨跌停快照日期必须与回测K线日期完整一致")
    for record, expected_day, candle in zip(records, expected_dates, candles, strict=True):
        candle_day = _date_text(_candle_value(candle, "date"), "回测K线日期")
        if candle_day != expected_day:
            raise BacktestInputError("回测K线日期必须按快照日期顺序完整一致")
        lower, upper = record["lower"], record["upper"]
        lower_price = Decimal(lower) if lower is not None else None
        upper_price = Decimal(upper) if upper is not None else None
        for field in ("open", "high", "low", "close"):
            price = _candle_decimal(_candle_value(candle, field), f"K线{field}")
            if lower_price is not None and upper_price is not None and (
                price < lower_price or price > upper_price
            ):
                raise BacktestInputError("回测K线OHLC超出用户提供的涨跌停边界")


def _expected_dates(values: Sequence[str]) -> list[str]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise BacktestInputError("涨跌停覆盖日期必须是列表")
    if not values or len(values) > _MAX_RECORDS:
        raise BacktestInputError("涨跌停覆盖日期数量必须为1到5000天")
    dates = [_date_text(value, "涨跌停覆盖日期") for value in values]
    if dates != sorted(set(dates)):
        raise BacktestInputError("涨跌停覆盖日期必须唯一并按日期排序")
    return dates


def _date_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        raise BacktestInputError(f"{label}必须是YYYY-MM-DD日期")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise BacktestInputError(f"{label}无效") from exc
    if parsed.isoformat() != value:
        raise BacktestInputError(f"{label}格式无效")
    return value


def _price_decimal(value: Any, label: str) -> Decimal:
    if not isinstance(value, str) or not _PRICE_RE.fullmatch(value):
        raise BacktestInputError(f"{label}必须是精确到分的正十进制字符串")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise BacktestInputError(f"{label}无效") from exc
    if not result.is_finite() or result <= 0 or result > _MAX_PRICE:
        raise BacktestInputError(f"{label}必须大于0且不超过10000000")
    if result.quantize(_CENT) != result:
        raise BacktestInputError(f"{label}精度不能超过分")
    return result


def _price_text(value: Decimal) -> str:
    return format(value.quantize(_CENT), ".2f")


def _candle_decimal(value: Any, label: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal, str)):
        raise BacktestInputError(f"{label}必须是有限数值")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise BacktestInputError(f"{label}必须是有限数值") from exc
    if not parsed.is_finite():
        raise BacktestInputError(f"{label}必须是有限数值")
    return parsed


def _candle_value(candle: Any, field: str) -> Any:
    if isinstance(candle, Mapping):
        if field not in candle:
            raise BacktestInputError(f"回测K线缺少{field}")
        return candle[field]
    if not hasattr(candle, field):
        raise BacktestInputError(f"回测K线缺少{field}")
    return getattr(candle, field)


def _canonical_symbol(value: Any) -> str:
    if not isinstance(value, str):
        raise BacktestInputError("涨跌停快照A股标的无效")
    try:
        return market.normalize_a_share_symbol(value)
    except (market.MarketDataError, TypeError, ValueError) as exc:
        raise BacktestInputError("涨跌停快照A股标的无效") from exc


def _utc_timestamp(value: Any) -> str:
    if not isinstance(value, str) or not _UTC_TIMESTAMP_RE.fullmatch(value):
        raise BacktestInputError("涨跌停来源fetchedAt必须是UTC ISO时间")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BacktestInputError("涨跌停来源fetchedAt无效") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise BacktestInputError("涨跌停来源fetchedAt必须是UTC时间")
    normalized = parsed.astimezone(timezone.utc)
    timestamp = normalized.strftime("%Y-%m-%dT%H:%M:%S")
    if normalized.microsecond:
        fraction = f"{normalized.microsecond:06d}".rstrip("0")
        timestamp += f".{fraction}"
    return f"{timestamp}Z"


def _artifact_hash(artifact: Mapping[str, Any]) -> str:
    # Lazy import keeps contract.py free to use this module without a cycle.
    from core.web.services.financial_backtest.contract import sha256_json

    return sha256_json(
        {
            "schemaVersion": artifact["schemaVersion"],
            "symbol": artifact["symbol"],
            "source": artifact["source"],
            "records": artifact["records"],
        }
    )
