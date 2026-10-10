"""Bind supplied daily limits to frozen prices without certifying their source."""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from . import basket_data, data
from .price_limits import (
    SUPPLIED_LIMIT_MODEL,
    freeze_price_limits,
    normalize_limit_model,
)

LIMIT_NOTICE = (
    "逐日限价由导入文件提供，尚未独立核验原文及历史ST/上市状态；"
    "来源链接和哈希只用于追溯，不能证明真实性。开盘触及对应限价时保守拒单，"
    "不证明开盘竞价流动性或排队成交能力。"
)


def validate_limit_binding(snapshot: Any, params: Mapping[str, Any]) -> None:
    assets = list(snapshot.assets.values()) if isinstance(snapshot, basket_data.BasketSnapshot) else [snapshot]
    wants_limits = normalize_limit_model(params) == SUPPLIED_LIMIT_MODEL
    if any((getattr(asset, "price_limits", None) is not None) != wants_limits for asset in assets):
        raise data.BacktestInputError("限价模型与冻结逐日限价不匹配")


def bind_price_limits(snapshot: Any, request: Mapping[str, Any]) -> Any:
    params = request["params"]
    if normalize_limit_model(params) != SUPPLIED_LIMIT_MODEL:
        validate_limit_binding(snapshot, params)
        return snapshot
    supplied = request.get("dailyPriceLimits")
    if supplied is None:
        validate_limit_binding(snapshot, params)
        return snapshot
    if isinstance(snapshot, basket_data.BasketSnapshot):
        basket_data.validate_basket_snapshot(snapshot)
    else:
        data.validate_snapshot(snapshot)
    assets = snapshot.assets if isinstance(snapshot, basket_data.BasketSnapshot) else {snapshot.symbol: snapshot}
    if not isinstance(supplied, list) or len(supplied) != len(assets):
        raise data.BacktestInputError("逐日限价必须逐一覆盖全部回测股票")
    supplied_assets = {}
    for item in supplied:
        if not isinstance(item, Mapping) or not isinstance(item.get("symbol"), str) or item["symbol"] not in assets or item["symbol"] in supplied_assets:
            raise data.BacktestInputError("逐日限价股票身份重复或与回测不符")
        supplied_assets[item["symbol"]] = item
    updated = {}
    for symbol, asset in assets.items():
        artifact = freeze_price_limits(supplied_assets[symbol], symbol, tuple(row.date for row in asset.candles), asset.candles)
        if asset.price_limits is not None and asset.price_limits != artifact:
            raise data.BacktestInputError("不能替换已有冻结限价")
        updated[symbol] = replace(
            asset, price_limits=artifact,
            data_hash=data._stable_hash(asset.warmup_candles + asset.candles, symbol, asset.start_date, asset.end_date, asset.corporate_actions, artifact),
            notice=asset.notice if LIMIT_NOTICE in asset.notice else asset.notice + (LIMIT_NOTICE,),
        )
        data.validate_snapshot(updated[symbol])
    if isinstance(snapshot, basket_data.BasketSnapshot):
        result = replace(snapshot, assets=updated, data_hash=basket_data._stable_basket_hash(snapshot.symbols, updated, snapshot.session_dates, snapshot.start_date, snapshot.end_date), notice=snapshot.notice if LIMIT_NOTICE in snapshot.notice else snapshot.notice + (LIMIT_NOTICE,))
        basket_data.validate_basket_snapshot(result)
        return result
    return updated[snapshot.symbol]


def limit_record(snapshot: data.BacktestSnapshot, day: str) -> Mapping[str, Any] | None:
    if snapshot.price_limits is None:
        return None
    records = snapshot.price_limits["records"]
    index = bisect_left(records, day, key=lambda record: record["date"])
    if index < len(records) and records[index]["date"] == day:
        return records[index]
    raise data.BacktestInputError("冻结逐日限价缺少撮合日期")
