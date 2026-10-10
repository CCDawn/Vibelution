"""Point-in-time, integrity-checked snapshots for multi-asset backtests."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from core.web.services import financial_market_service as market
from core.web.services.financial_backtest import data as single_data

_SCHEMA_VERSION = 2
_MAX_BASKET_SYMBOLS = 10


@dataclass(frozen=True, slots=True)
class BasketSnapshot:
    """Frozen per-symbol snapshots that share one complete session calendar."""

    symbols: tuple[str, ...]
    assets: Mapping[str, single_data.BacktestSnapshot]
    session_dates: tuple[str, ...]
    start_date: str
    end_date: str
    data_hash: str
    source: str
    notice: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a detached JSON-safe projection suitable for persisted jobs."""
        return {
            "schemaVersion": _SCHEMA_VERSION,
            "symbols": list(self.symbols),
            "assets": {
                symbol: self.assets[symbol].to_dict() for symbol in self.symbols
            },
            "sessionDates": list(self.session_dates),
            "startDate": self.start_date,
            "endDate": self.end_date,
            "dataHash": self.data_hash,
            "source": self.source,
            "notice": list(self.notice),
        }


def _canonical_symbols(symbols: Sequence[str]) -> tuple[str, ...]:
    if not isinstance(symbols, Sequence) or isinstance(symbols, (str, bytes)):
        raise single_data.BacktestInputError("symbols必须是股票代码列表")
    if not symbols:
        raise single_data.BacktestInputError("组合至少需要一只A股")
    if len(symbols) > _MAX_BASKET_SYMBOLS:
        raise single_data.BacktestInputError(f"组合最多支持{_MAX_BASKET_SYMBOLS}只A股")
    normalized: list[str] = []
    for value in symbols:
        if not isinstance(value, str) or not value.strip():
            raise single_data.BacktestInputError("symbols必须只包含有效股票代码")
        try:
            normalized.append(market.normalize_a_share_symbol(value))
        except market.MarketDataError as exc:
            raise single_data.BacktestInputError(f"股票代码无效：{value}") from exc
    if len(set(normalized)) != len(normalized):
        raise single_data.BacktestInputError("symbols包含重复股票代码")
    return tuple(sorted(normalized))


def _stable_basket_hash(
    symbols: tuple[str, ...],
    assets: Mapping[str, single_data.BacktestSnapshot],
    session_dates: tuple[str, ...],
    start_date: str,
    end_date: str,
) -> str:
    payload = {
        "schemaVersion": _SCHEMA_VERSION,
        "symbols": list(symbols),
        "startDate": start_date,
        "endDate": end_date,
        "sessionDates": list(session_dates),
        "assetHashes": {symbol: assets[symbol].data_hash for symbol in symbols},
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def prepare_basket_data(
    symbols: Sequence[str],
    start_date: str,
    end_date: str,
    *,
    warmup_bars: int = 252,
    today: date | datetime | str | None = None,
    data_source: str = "tencent",
    corporate_action_policy: str = "block",
) -> BasketSnapshot:
    """Prepare and freeze every asset through the existing single-stock gate."""
    canonical = _canonical_symbols(symbols)
    if data_source == "auto":
        from dataclasses import replace
        failures: dict[str, str] = {}
        for provider in ("tencent", "eastmoney", "sina"):
            try:
                snapshot = prepare_basket_data(canonical, start_date, end_date, warmup_bars=warmup_bars, today=today, data_source=provider, corporate_action_policy=corporate_action_policy)
            except (single_data.BacktestInputError, single_data.CorporateActionUnsupported):
                raise
            except single_data.BacktestDataError as exc:
                failures[provider] = str(exc)[:500]
                continue
            if failures:
                return replace(snapshot, notice=snapshot.notice + (f"主来源未通过，整个组合改用{snapshot.source}重新取得完整快照；未跨来源拼接。",))
            return snapshot
        raise single_data.BacktestDataError(
            "组合公开历史来源均未通过。" + "；".join(f"{name}：{reason}" for name, reason in failures.items()),
            metadata={"sourceFailures": failures},
        )
    assets: dict[str, single_data.BacktestSnapshot] = {}
    shared_dates: tuple[str, ...] | None = None
    for symbol in canonical:
        snapshot = single_data.prepare_data(
            {
                "symbol": symbol,
                "startDate": start_date,
                "endDate": end_date,
                "warmupBars": warmup_bars,
                "dataSource": data_source,
                "corporateActionPolicy": corporate_action_policy,
            },
            today=today,
        )
        single_data.validate_snapshot(snapshot)
        if snapshot.symbol != symbol:
            raise single_data.BacktestDataError("组合快照资产代码与请求不一致")
        dates = tuple(candle.date for candle in snapshot.candles)
        if shared_dates is None:
            shared_dates = dates
        elif dates != shared_dates:
            raise single_data.BacktestDataError(
                "组合资产的交易日历或区间覆盖不一致，无法安全撮合。",
                metadata={
                    "calendarStatus": "asset_mismatch",
                    "symbol": symbol,
                    "expectedStartDate": shared_dates[0] if shared_dates else None,
                    "expectedEndDate": shared_dates[-1] if shared_dates else None,
                    "actualStartDate": dates[0] if dates else None,
                    "actualEndDate": dates[-1] if dates else None,
                },
            )
        assets[symbol] = snapshot

    if not shared_dates:
        raise single_data.BacktestDataError("组合区间没有共同完整交易日")
    first = assets[canonical[0]]
    snapshot = BasketSnapshot(
        symbols=canonical,
        assets=assets,
        session_dates=shared_dates,
        start_date=shared_dates[0],
        end_date=shared_dates[-1],
        data_hash=_stable_basket_hash(
            canonical, assets, shared_dates, shared_dates[0], shared_dates[-1]
        ),
        source=first.source,
        notice=tuple(
            dict.fromkeys(
                [notice for asset in assets.values() for notice in asset.notice]
                + ["组合回测要求所有股票通过相同完整交易日历与区间覆盖校验。"]
            )
        ),
    )
    validate_basket_snapshot(snapshot)
    return snapshot


def validate_basket_snapshot(snapshot: BasketSnapshot) -> None:
    """Fail closed when any asset, shared date, coverage, or basket hash drifts."""
    if not isinstance(snapshot, BasketSnapshot):
        raise single_data.BacktestDataError("组合回测数据快照类型无效")
    if not isinstance(snapshot.symbols, tuple) or not snapshot.symbols:
        raise single_data.BacktestDataError("组合快照股票代码列表无效")
    try:
        canonical = _canonical_symbols(snapshot.symbols)
    except single_data.BacktestInputError as exc:
        raise single_data.BacktestDataError("组合快照股票代码列表无效") from exc
    if canonical != snapshot.symbols:
        raise single_data.BacktestDataError("组合快照股票代码未规范化或未按规范排序")
    if not isinstance(snapshot.assets, Mapping) or set(snapshot.assets) != set(
        snapshot.symbols
    ):
        raise single_data.BacktestDataError("组合快照资产映射与股票代码列表不一致")
    if not isinstance(snapshot.session_dates, tuple) or not snapshot.session_dates:
        raise single_data.BacktestDataError("组合快照共同交易日历无效")
    try:
        parsed_dates = tuple(
            date.fromisoformat(value) for value in snapshot.session_dates
        )
    except (TypeError, ValueError) as exc:
        raise single_data.BacktestDataError("组合快照包含无效交易日") from exc
    if any(
        parsed.isoformat() != value
        for parsed, value in zip(parsed_dates, snapshot.session_dates, strict=True)
    ):
        raise single_data.BacktestDataError("组合快照交易日格式无效")
    if tuple(sorted(set(snapshot.session_dates))) != snapshot.session_dates:
        raise single_data.BacktestDataError("组合快照交易日重复或乱序")
    if (
        snapshot.start_date != snapshot.session_dates[0]
        or snapshot.end_date != snapshot.session_dates[-1]
    ):
        raise single_data.BacktestDataError("组合快照区间边界与共同交易日历不一致")

    requested_ranges: set[tuple[str, str]] = set()
    for symbol in snapshot.symbols:
        asset = snapshot.assets[symbol]
        if (
            not isinstance(asset, single_data.BacktestSnapshot)
            or asset.symbol != symbol
        ):
            raise single_data.BacktestDataError("组合快照资产代码与映射键不一致")
        single_data.validate_snapshot(asset)
        asset_dates = tuple(candle.date for candle in asset.candles)
        if (
            asset.start_date != snapshot.start_date
            or asset.end_date != snapshot.end_date
            or asset_dates != snapshot.session_dates
        ):
            raise single_data.BacktestDataError(
                "组合资产的交易日历或区间覆盖不一致，无法安全撮合。",
                metadata={"calendarStatus": "asset_mismatch", "symbol": symbol},
            )
        requested_ranges.add(
            (asset.coverage.requestedStartDate, asset.coverage.requestedEndDate)
        )
    if len(requested_ranges) != 1:
        raise single_data.BacktestDataError("组合资产的请求覆盖区间不一致")
    if not isinstance(snapshot.source, str) or not snapshot.source:
        raise single_data.BacktestDataError("组合快照行情来源无效")
    if not isinstance(snapshot.notice, tuple) or any(
        not isinstance(item, str) for item in snapshot.notice
    ):
        raise single_data.BacktestDataError("组合快照说明格式无效")
    expected_hash = _stable_basket_hash(
        snapshot.symbols,
        snapshot.assets,
        snapshot.session_dates,
        snapshot.start_date,
        snapshot.end_date,
    )
    if snapshot.data_hash != expected_hash:
        raise single_data.BacktestDataError("组合快照行情摘要校验失败")


def _restore_asset_snapshot(payload: Mapping[str, Any]) -> single_data.BacktestSnapshot:
    try:
        coverage_payload = payload["coverage"]
        if not isinstance(coverage_payload, Mapping):
            raise TypeError("coverage must be an object")
        provider_windows = coverage_payload["providerWindows"]
        if not isinstance(provider_windows, Sequence) or isinstance(
            provider_windows, (str, bytes)
        ):
            raise TypeError("providerWindows must be a list")
        coverage_values = dict(coverage_payload)
        coverage_values["providerWindows"] = tuple(
            dict(item) for item in provider_windows
        )
        return single_data.BacktestSnapshot(
            symbol=payload["symbol"],
            start_date=payload["startDate"],
            end_date=payload["endDate"],
            candles=tuple(
                single_data.Candle(**dict(item)) for item in payload["candles"]
            ),
            warmup_candles=tuple(
                single_data.Candle(**dict(item)) for item in payload["warmupCandles"]
            ),
            source=payload["source"],
            source_url=payload["sourceUrl"],
            fetched_at=payload["fetchedAt"],
            data_hash=payload["dataHash"],
            coverage=single_data.BacktestCoverage(**coverage_values),
            actions_status=payload["actionsStatus"],
            action_dates=tuple(payload["actionDates"]),
            notice=tuple(payload["notice"]),
            corporate_actions=payload.get("corporateActions"),
            price_limits=payload.get("priceLimits"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise single_data.BacktestDataError("组合快照序列化资产格式无效") from exc


def restore_basket_snapshot(payload: Mapping[str, Any]) -> BasketSnapshot:
    """Restore a persisted JSON projection and revalidate all frozen data."""
    if not isinstance(payload, Mapping):
        raise single_data.BacktestDataError("组合快照序列化格式无效")
    if (
        type(payload.get("schemaVersion")) is not int
        or payload["schemaVersion"] != _SCHEMA_VERSION
    ):
        raise single_data.BacktestDataError("组合快照schemaVersion必须为2")
    try:
        raw_symbols = payload["symbols"]
        if not isinstance(raw_symbols, Sequence) or isinstance(
            raw_symbols, (str, bytes)
        ):
            raise TypeError("symbols must be a list")
        symbols = tuple(raw_symbols)
        raw_assets = payload["assets"]
        if not isinstance(raw_assets, Mapping):
            raise TypeError("assets must be an object")
        if set(raw_assets) != set(symbols):
            raise TypeError("assets keys must match symbols")
        assets = {
            symbol: _restore_asset_snapshot(raw_assets[symbol]) for symbol in symbols
        }
        snapshot = BasketSnapshot(
            symbols=symbols,
            assets=assets,
            session_dates=tuple(payload["sessionDates"]),
            start_date=payload["startDate"],
            end_date=payload["endDate"],
            data_hash=payload["dataHash"],
            source=payload["source"],
            notice=tuple(payload["notice"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise single_data.BacktestDataError("组合快照序列化格式无效") from exc
    validate_basket_snapshot(snapshot)
    return snapshot


basket_snapshot_from_dict = restore_basket_snapshot


__all__ = [
    "BasketSnapshot",
    "basket_snapshot_from_dict",
    "prepare_basket_data",
    "restore_basket_snapshot",
    "validate_basket_snapshot",
]
