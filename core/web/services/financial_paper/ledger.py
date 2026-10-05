"""Agent-owned paper-trading ledger; no broker or real-account integration."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from core.infrastructure.atomic_io import atomic_write_json
from core.infrastructure.file_lock import cross_process_file_lock
from core.web.services import agent_directory_service as directory
from core.web.services import financial_market_service as market
from core.web.services import financial_research_service as research
from core.web.services.financial_assistant_service import PROFILE, ROLE
from core.web.services.runtime_scene_service import record_runtime_scene_event_quietly

_SCHEMA_VERSION = 1
_INITIAL_CASH = Decimal("1000000.00")
_CENTS = Decimal("0.01")
_COMMISSION_RATE = Decimal("0.0003")
_MIN_COMMISSION = Decimal("5.00")
_SELL_STAMP_DUTY_RATE = Decimal("0.0005")
_MAX_ORDER_QUANTITY = 1_000_000
_MAX_OPEN_POSITIONS = 20
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_MONTH_RE = re.compile(r"^\d{4}-(?:0[1-9]|1[0-2])$")

BUY = "buy"
SELL = "sell"


class FinancialPaperError(ValueError):
    """Base class for user-correctable paper-ledger errors."""


class AccountNotOpenedError(FinancialPaperError):
    pass


class PaperAccountConflictError(FinancialPaperError):
    pass


class InvalidPaperOrderError(FinancialPaperError):
    pass


class IdempotencyConflictError(FinancialPaperError):
    pass


class InsufficientCashError(FinancialPaperError):
    pass


class InsufficientSharesError(FinancialPaperError):
    pass


def _money(value: Decimal | str | float) -> Decimal:
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise InvalidPaperOrderError("金额不是有效数值") from exc
    if not parsed.is_finite():
        raise InvalidPaperOrderError("金额不是有效数值")
    return parsed.quantize(_CENTS, rounding=ROUND_HALF_UP)


def _money_text(value: Decimal | str | float) -> str:
    return format(_money(value), ".2f")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_text(value: datetime | None = None) -> str:
    return (value or _utc_now()).isoformat(timespec="seconds")


def _beijing_date(value: datetime | None = None) -> date:
    return (value or _utc_now()).astimezone(_SHANGHAI).date()


def _beijing_month(value: datetime | None = None) -> str:
    return (value or _utc_now()).astimezone(_SHANGHAI).strftime("%Y-%m")


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _financial_agent(agent_id: str) -> dict[str, Any]:
    normalized = str(agent_id or "").strip()
    if not normalized or len(normalized) > 160:
        raise directory.AgentNotFoundError("金融助手不存在")
    agent = directory.get_agent(normalized, include_archived=True)
    if not agent:
        raise directory.AgentNotFoundError("金融助手不存在")
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    if (
        metadata.get("financialAssistantProfile") != PROFILE
        or agent.get("roleKey") != ROLE
    ):
        raise directory.AgentNotFoundError("该 Agent 不是当前项目的金融助手")
    if agent.get("primaryMode") != "general":
        raise directory.AgentStateConflictError(
            "金融助手身份已更改，请先核对 Agent 配置"
        )
    if agent.get("status") != "active":
        raise directory.AgentStateConflictError("金融助手已归档，模拟账户不可用")
    if metadata.get("financialAssistantSetup") != "ready":
        raise directory.AgentStateConflictError("金融助手尚未完成初始化")
    return agent


def _ensure_within_root(child: Path, root: Path, message: str) -> None:
    def comparable(path: Path) -> Path:
        raw = str(path)
        if raw.lower().startswith("\\\\?\\unc\\"):
            raw = "\\\\" + raw[8:]
        elif raw.startswith("\\\\?\\"):
            raw = raw[4:]
        return Path(os.path.normcase(raw))

    try:
        comparable(child).relative_to(comparable(root))
    except ValueError as exc:
        raise PaperAccountConflictError(message) from exc


def _ledger_path(agent: dict[str, Any]) -> Path:
    agent_id = str(agent.get("agentId") or "").strip()
    territory = directory.resolve_agent_workspace_territory(agent_id)
    private_root = str(territory.get("privateRoot") or "").strip()
    if not private_root or not directory._is_agent_private_workspace_path(
        private_root, agent_id
    ):
        raise PaperAccountConflictError(
            "金融助手的私有工作区不可用，模拟账本已停止读取"
        )
    root = directory._resolve_project_path(private_root)
    artifacts = str((territory.get("subdirs") or {}).get("artifacts") or "").strip()
    if not artifacts:
        raise PaperAccountConflictError("金融助手的私有账本目录不可用")
    artifacts_root = directory._resolve_project_path(artifacts)
    _ensure_within_root(artifacts_root, root, "金融账本路径不在该 Agent 私有工作区内")
    ledger_path = (artifacts_root / "financial-paper" / "ledger.json").resolve()
    _ensure_within_root(ledger_path, root, "金融账本文件不在该 Agent 私有工作区内")
    return ledger_path


@contextmanager
def _transaction_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".transaction.lock")
    with cross_process_file_lock(path, lock_path=lock_path, timeout=20.0):
        yield


def _load_ledger(path: Path, agent_id: str) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PaperAccountConflictError("模拟账本无法读取，未覆盖现有数据") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schemaVersion") != _SCHEMA_VERSION
        or payload.get("agentId") != agent_id
        or not isinstance(payload.get("account"), dict)
        or not isinstance(payload.get("positions"), dict)
        or not isinstance(payload.get("orders"), list)
    ):
        raise PaperAccountConflictError("模拟账本格式或归属不匹配，未覆盖现有数据")
    return payload


def _write_ledger(path: Path, ledger: dict[str, Any]) -> None:
    atomic_write_json(
        path,
        ledger,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        strict_replace=True,
        retry_timeout_seconds=5.0,
    )


def _new_ledger(agent_id: str) -> dict[str, Any]:
    return {
        "schemaVersion": _SCHEMA_VERSION,
        "agentId": agent_id,
        "account": {
            "accountId": str(uuid4()),
            "openedAt": _utc_text(),
            "initialCashYuan": _money_text(_INITIAL_CASH),
            "cashYuan": _money_text(_INITIAL_CASH),
        },
        "positions": {},
        "orders": [],
    }


def _fee_policy() -> dict[str, Any]:
    return {
        "commissionRate": "0.0003",
        "minimumCommissionYuan": _money_text(_MIN_COMMISSION),
        "sellStampDutyRate": "0.0005",
        "transferFeeIncluded": False,
        "description": "模拟口径：佣金按成交额 0.03%，每笔最低 5 元；卖出印花税按成交额 0.05%；暂不计过户费。",
    }


def _t_plus_one_rule() -> str:
    return "模拟 T+1：买入日之后的北京时间自然日可卖出；不判断交易日、周末或节假日。"


def open_account(agent_id: str) -> dict[str, Any]:
    agent = _financial_agent(agent_id)
    path = _ledger_path(agent)
    normalized_id = str(agent["agentId"])
    with _transaction_lock(path):
        ledger = _load_ledger(path, normalized_id)
        if ledger is None:
            ledger = _new_ledger(normalized_id)
            _write_ledger(path, ledger)
            record_runtime_scene_event_quietly(
                "finance",
                "paper_account",
                "finance.paper_account.opened",
                outcome="created",
                lifecycle=True,
                fields={
                    "agentId": normalized_id,
                    "accountId": ledger["account"]["accountId"],
                    "simulationOnly": True,
                },
            )
    return _account_snapshot_from_ledger(ledger, order_limit=50)


def _load_existing(agent_id: str) -> tuple[dict[str, Any], Path, dict[str, Any]]:
    agent = _financial_agent(agent_id)
    path = _ledger_path(agent)
    normalized_id = str(agent["agentId"])
    ledger = _load_ledger(path, normalized_id)
    if ledger is None:
        raise AccountNotOpenedError("尚未开设模拟账户")
    return agent, path, ledger


def get_account_snapshot(agent_id: str, *, order_limit: int = 50) -> dict[str, Any]:
    _, _, ledger = _load_existing(agent_id)
    bounded_limit = max(1, min(int(order_limit), 200))
    return _account_snapshot_from_ledger(ledger, order_limit=bounded_limit)


def _account_snapshot_from_ledger(
    ledger: dict[str, Any], *, order_limit: int
) -> dict[str, Any]:
    account = ledger["account"]
    positions: list[dict[str, Any]] = []
    fresh_all = True
    total_market_value = Decimal("0.00")
    total_cost = Decimal("0.00")
    open_symbols = [
        symbol
        for symbol, row in ledger["positions"].items()
        if any(
            int(lot.get("remainingQuantity") or 0) > 0 for lot in row.get("lots", [])
        )
    ]
    # Valuation needs only quotes. One bounded provider batch avoids fetching
    # a full candle series for every holding and preserves per-symbol failure.
    quote_batch = research.batch_quotes(open_symbols) if open_symbols else None
    for symbol, row in sorted(ledger["positions"].items()):
        lots = [
            lot
            for lot in row.get("lots", [])
            if int(lot.get("remainingQuantity") or 0) > 0
        ]
        quantity = sum(int(lot.get("remainingQuantity") or 0) for lot in lots)
        if quantity <= 0:
            continue
        cost = sum(
            (_money(lot.get("remainingCostYuan", "0")) for lot in lots), Decimal("0.00")
        )
        try:
            quote = _quote_from_batch(symbol, quote_batch)
            price = _money(quote["priceYuan"])
            quote_timestamp = str(quote.get("timestamp") or "")
            quote_fetched_at = str(quote.get("fetchedAt") or "")
            source = str(quote.get("source") or "腾讯财经")
            source_url = str(quote.get("sourceUrl") or "")
            quote_status = "fresh"
            row["lastQuote"] = {
                "priceYuan": _money_text(price),
                "timestamp": quote_timestamp,
                "fetchedAt": quote_fetched_at,
                "source": source,
                "sourceUrl": source_url,
            }
            identity = {
                "ticker": str(quote.get("ticker") or row.get("ticker") or ""),
                "name": str(quote.get("name") or row.get("name") or ""),
                "market": str(quote.get("market") or row.get("market") or ""),
            }
        except (market.MarketDataError, KeyError, TypeError, ValueError):
            quote = (
                row.get("lastQuote") if isinstance(row.get("lastQuote"), dict) else {}
            )
            try:
                price = _money(quote["priceYuan"])
            except (KeyError, FinancialPaperError):
                price = Decimal("0.00")
                fresh_all = False
                quote_status = "unavailable"
            else:
                fresh_all = False
                quote_status = "stale"
            quote_timestamp = str(quote.get("timestamp") or "")
            quote_fetched_at = str(quote.get("fetchedAt") or "")
            source = str(quote.get("source") or "腾讯财经")
            source_url = str(quote.get("sourceUrl") or "")
            identity = {
                key: str(row.get(key) or "") for key in ("ticker", "name", "market")
            }

        market_value = _money(price * quantity) if price > 0 else Decimal("0.00")
        unrealized = _money(market_value - cost) if price > 0 else Decimal("0.00")
        total_market_value += market_value
        total_cost += cost
        positions.append(
            {
                "symbol": symbol,
                **identity,
                "quantity": quantity,
                "availableQuantity": _available_quantity(lots),
                "frozenQuantity": quantity - _available_quantity(lots),
                "averageCostYuan": _money_text(cost / quantity),
                "costBasisYuan": _money_text(cost),
                "markPriceYuan": _money_text(price) if price > 0 else None,
                "marketValueYuan": _money_text(market_value) if price > 0 else None,
                "unrealizedPnlYuan": _money_text(unrealized) if price > 0 else None,
                "valuationStatus": quote_status,
                "quoteTimestamp": quote_timestamp,
                "quoteDate": quote_timestamp[:10] if len(quote_timestamp) >= 10 else "",
                "quoteFetchedAt": quote_fetched_at,
                "source": source,
                "sourceUrl": source_url,
            }
        )

    cash = _money(account.get("cashYuan", "0"))
    initial_cash = _money(account.get("initialCashYuan", _INITIAL_CASH))
    realized = _sum_money(
        _money(order.get("realizedPnlYuan", "0"))
        for order in ledger["orders"]
        if order.get("side") == SELL
    )
    total_fees = _sum_money(
        _money(order.get("totalFeeYuan", "0")) for order in ledger["orders"]
    )
    equity = _money(cash + total_market_value)
    unrealized_total = _money(total_market_value - total_cost)
    latest = [
        {key: value for key, value in order.items() if key != "requestFingerprint"}
        for order in reversed(ledger["orders"][-max(1, order_limit) :])
    ]
    order_count = len(ledger["orders"])
    return {
        "agentId": ledger["agentId"],
        "accountId": account["accountId"],
        "openedAt": account["openedAt"],
        "initialCashYuan": _money_text(initial_cash),
        "cashYuan": _money_text(cash),
        "marketValueYuan": _money_text(total_market_value),
        "equityYuan": _money_text(equity),
        "realizedPnlYuan": _money_text(realized),
        "unrealizedPnlYuan": _money_text(unrealized_total),
        "totalPnlYuan": _money_text(equity - initial_cash),
        "totalFeesYuan": _money_text(total_fees),
        "valuationStatus": "fresh" if fresh_all else "partial",
        "valuationNotice": "估值取腾讯公开最新报价；休市时可能是最近报价。行情不可用时使用最近一次成交报价并标记为过期。"
        if not fresh_all
        else "估值取腾讯公开最新报价；休市时可能是最近报价。",
        "positions": positions,
        "orders": latest,
        "ordersTotal": order_count,
        "ordersLimit": order_limit,
        "ordersTruncated": order_count > len(latest),
        "feePolicy": _fee_policy(),
        "tPlusOneRule": _t_plus_one_rule(),
        "simulationOnly": True,
    }


def _available_quantity(lots: list[dict[str, Any]]) -> int:
    today = _beijing_date()
    total = 0
    for lot in lots:
        remaining = int(lot.get("remainingQuantity") or 0)
        try:
            acquired_day = date.fromisoformat(str(lot.get("acquiredBeijingDate") or ""))
        except ValueError:
            continue
        if acquired_day < today:
            total += remaining
    return total


def _sum_money(values: Any) -> Decimal:
    return _money(sum(values, Decimal("0.00")))


def _request_fingerprint(symbol: str, side: str, quantity: int, reason: str) -> str:
    normalized = json.dumps(
        {"symbol": symbol, "side": side, "quantity": quantity, "reason": reason},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _normalize_order(
    client_order_id: str,
    symbol: str,
    side: str,
    quantity: int,
    reason: str,
) -> tuple[str, str, int, str, str]:
    key = str(client_order_id or "").strip()
    if not key:
        raise InvalidPaperOrderError("clientOrderId 不能为空")
    try:
        key = str(UUID(key))
    except ValueError as exc:
        raise InvalidPaperOrderError("clientOrderId 必须是有效 UUID") from exc
    try:
        normalized_symbol = market.normalize_symbol(symbol)
    except market.MarketDataError as exc:
        raise InvalidPaperOrderError(str(exc)) from exc
    normalized_side = str(side or "").strip().lower()
    if normalized_side not in {BUY, SELL}:
        raise InvalidPaperOrderError("交易方向只能是买入或卖出")
    if (
        isinstance(quantity, bool)
        or not isinstance(quantity, int)
        or quantity < 100
        or quantity > _MAX_ORDER_QUANTITY
        or quantity % 100
    ):
        raise InvalidPaperOrderError("数量须为 100 股的整数倍，且不超过 1,000,000 股")
    normalized_reason = " ".join(str(reason or "").split()).strip()
    if not normalized_reason or len(normalized_reason) > 500:
        raise InvalidPaperOrderError("请填写 1–500 字的模拟交易理由")
    fingerprint = _request_fingerprint(
        normalized_symbol, normalized_side, quantity, normalized_reason
    )
    return key, normalized_symbol, quantity, normalized_reason, fingerprint


def _calculate_fee(gross: Decimal, side: str) -> tuple[Decimal, Decimal]:
    commission = max(_money(gross * _COMMISSION_RATE), _MIN_COMMISSION)
    stamp_duty = (
        _money(gross * _SELL_STAMP_DUTY_RATE) if side == SELL else Decimal("0.00")
    )
    return commission, stamp_duty


def _quote_from_batch(symbol: str, batch: dict[str, Any] | None) -> dict[str, Any]:
    try:
        item = next(
            (
                row
                for row in (batch or {}).get("items", [])
                if row.get("symbol") == symbol
            ),
            None,
        )
        if not item or not isinstance(item.get("quote"), dict):
            raise market.MarketDataError(
                str((item or {}).get("error") or "行情源没有有效的最新报价")
            )
        quote = item["quote"]
        price = _money(quote["price"])
        if price <= 0:
            raise market.MarketDataError("行情源没有有效的最新报价")
        return {
            "symbol": symbol,
            "ticker": str(quote["ticker"]),
            "name": str(quote["name"]),
            "market": str(quote["market"]),
            "priceYuan": _money_text(price),
            "timestamp": str(quote["timestamp"]),
            "fetchedAt": str(batch["fetchedAt"]),
            "source": str(batch["source"]),
            "sourceUrl": f"https://gu.qq.com/{symbol}/gp",
        }
    except (market.MarketDataError, KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, market.MarketDataError):
            raise
        raise market.MarketDataError("行情源返回了不完整的报价") from exc


def _get_quote(symbol: str) -> dict[str, Any]:
    return _quote_from_batch(symbol, research.batch_quotes([symbol]))


def _existing_idempotent_order(
    ledger: dict[str, Any], client_order_id: str, fingerprint: str
) -> dict[str, Any] | None:
    for order in reversed(ledger["orders"]):
        if order.get("clientOrderId") != client_order_id:
            continue
        if order.get("requestFingerprint") != fingerprint:
            raise IdempotencyConflictError("clientOrderId 已用于不同的交易请求")
        return order
    return None


def submit_order(
    agent_id: str,
    *,
    client_order_id: str,
    symbol: str,
    side: Literal["buy", "sell"],
    quantity: int,
    reason: str,
) -> dict[str, Any]:
    agent, path, ledger_before_quote = _load_existing(agent_id)
    normalized_id = str(agent["agentId"])
    key, normalized_symbol, normalized_quantity, normalized_reason, fingerprint = (
        _normalize_order(client_order_id, symbol, side, quantity, reason)
    )
    existing = _existing_idempotent_order(ledger_before_quote, key, fingerprint)
    if existing:
        return _account_snapshot_from_ledger(ledger_before_quote, order_limit=50)

    quote = _get_quote(normalized_symbol)
    price = _money(quote["priceYuan"])
    gross = _money(price * normalized_quantity)
    commission, stamp_duty = _calculate_fee(gross, side)
    total_fee = _money(commission + stamp_duty)
    order_time = _utc_now()
    order_time_text = _utc_text(order_time)
    local_order_day = _beijing_date(order_time).isoformat()

    with _transaction_lock(path):
        ledger = _load_ledger(path, normalized_id)
        if ledger is None:
            raise AccountNotOpenedError("尚未开设模拟账户")
        existing = _existing_idempotent_order(ledger, key, fingerprint)
        if existing:
            return _account_snapshot_from_ledger(ledger, order_limit=50)

        positions: dict[str, Any] = ledger["positions"]
        position = positions.get(normalized_symbol)
        if side == BUY:
            if position is None and len(positions) >= _MAX_OPEN_POSITIONS:
                raise InvalidPaperOrderError(
                    f"最多同时持有 {_MAX_OPEN_POSITIONS} 只股票"
                )
            cash = _money(ledger["account"].get("cashYuan", "0"))
            total_debit = _money(gross + total_fee)
            if total_debit > cash:
                raise InsufficientCashError(
                    f"模拟余额不足：需要 {total_debit:.2f} 元（含费用）"
                )
            if position is None:
                position = {
                    "symbol": normalized_symbol,
                    "ticker": quote["ticker"],
                    "name": quote["name"],
                    "market": quote["market"],
                    "lots": [],
                    "lastQuote": quote,
                }
                positions[normalized_symbol] = position
            position["ticker"], position["name"], position["market"] = (
                quote["ticker"],
                quote["name"],
                quote["market"],
            )
            position["lastQuote"] = quote
            position["lots"].append(
                {
                    "acquiredAt": order_time_text,
                    "acquiredBeijingDate": local_order_day,
                    "remainingQuantity": normalized_quantity,
                    "remainingCostYuan": _money_text(total_debit),
                }
            )
            ledger["account"]["cashYuan"] = _money_text(cash - total_debit)
            realized = Decimal("0.00")
            cash_change = _money(-total_debit)
        else:
            if position is None:
                raise InsufficientSharesError("当前没有该股票的可卖持仓")
            lots = sorted(
                position.get("lots", []),
                key=lambda lot: str(lot.get("acquiredAt") or ""),
            )
            available_lots: list[dict[str, Any]] = []
            for lot in lots:
                try:
                    acquired_day = date.fromisoformat(
                        str(lot.get("acquiredBeijingDate") or "")
                    )
                except ValueError:
                    continue
                if acquired_day < _beijing_date(order_time):
                    available_lots.append(lot)
            available = sum(
                int(lot.get("remainingQuantity") or 0) for lot in available_lots
            )
            if normalized_quantity > available:
                raise InsufficientSharesError(
                    f"可卖 {available} 股；模拟 T+1 按北京时间自然日，今日买入股份次日才可卖"
                )
            needed = normalized_quantity
            allocated_cost = Decimal("0.00")
            for lot in available_lots:
                if needed <= 0:
                    break
                lot_quantity = int(lot.get("remainingQuantity") or 0)
                lot_cost = _money(lot.get("remainingCostYuan", "0"))
                take = min(needed, lot_quantity)
                consumed_cost = (
                    lot_cost
                    if take == lot_quantity
                    else min(
                        lot_cost,
                        _money(lot_cost * Decimal(take) / Decimal(lot_quantity)),
                    )
                )
                lot["remainingQuantity"] = lot_quantity - take
                lot["remainingCostYuan"] = _money_text(lot_cost - consumed_cost)
                allocated_cost += consumed_cost
                needed -= take
            remaining_lots = [
                lot for lot in lots if int(lot.get("remainingQuantity") or 0) > 0
            ]
            net_credit = _money(gross - total_fee)
            cash = _money(ledger["account"].get("cashYuan", "0"))
            ledger["account"]["cashYuan"] = _money_text(cash + net_credit)
            realized = _money(net_credit - allocated_cost)
            cash_change = net_credit
            if remaining_lots:
                position["lots"] = remaining_lots
                position["lastQuote"] = quote
            else:
                positions.pop(normalized_symbol, None)

        order = {
            "orderId": str(uuid4()),
            "clientOrderId": key,
            "requestFingerprint": fingerprint,
            "symbol": normalized_symbol,
            "ticker": quote["ticker"],
            "name": quote["name"],
            "market": quote["market"],
            "side": side,
            "quantity": normalized_quantity,
            "priceYuan": _money_text(price),
            "grossAmountYuan": _money_text(gross),
            "commissionYuan": _money_text(commission),
            "stampDutyYuan": _money_text(stamp_duty),
            "totalFeeYuan": _money_text(total_fee),
            "cashChangeYuan": _money_text(cash_change),
            "realizedPnlYuan": _money_text(realized),
            "reason": normalized_reason,
            "createdAt": order_time_text,
            "beijingDate": local_order_day,
            "quoteSource": quote["source"],
            "quoteSourceUrl": quote["sourceUrl"],
            "quoteTimestamp": quote["timestamp"],
            "quoteDate": quote["timestamp"][:10],
            "quoteFetchedAt": quote["fetchedAt"],
            "priceNotice": "模拟成交按服务端取得的腾讯公开最新报价；下单价非交易所成交回报。",
        }
        ledger["orders"].append(order)
        _write_ledger(path, ledger)
        record_runtime_scene_event_quietly(
            "finance",
            "paper_order",
            "finance.paper_order.recorded",
            outcome="recorded",
            lifecycle=True,
            fields={
                "agentId": normalized_id,
                "accountId": ledger["account"]["accountId"],
                "orderId": order["orderId"],
                "clientOrderId": key,
                "side": side,
                "simulationOnly": True,
            },
        )
    return _account_snapshot_from_ledger(ledger, order_limit=50)


def get_review_snapshot(agent_id: str, *, month: str) -> dict[str, Any]:
    normalized_month = str(month or "").strip()
    if not _MONTH_RE.fullmatch(normalized_month):
        raise InvalidPaperOrderError("月份格式须为 YYYY-MM")
    _, _, ledger = _load_existing(agent_id)
    year, month_number = (int(part) for part in normalized_month.split("-"))
    if year < 1:
        raise InvalidPaperOrderError("月份格式须为有效的 YYYY-MM")
    rows: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "date": "",
            "tradeCount": 0,
            "buyCount": 0,
            "sellCount": 0,
            "buyAmountYuan": Decimal("0.00"),
            "sellAmountYuan": Decimal("0.00"),
            "feesYuan": Decimal("0.00"),
            "realizedPnlYuan": Decimal("0.00"),
        }
    )
    buy_count = sell_count = winning_sells = 0
    all_time_realized = Decimal("0.00")
    all_time_fees = Decimal("0.00")
    month_realized = Decimal("0.00")
    month_fees = Decimal("0.00")
    for order in ledger["orders"]:
        try:
            day = date.fromisoformat(str(order.get("beijingDate") or ""))
        except ValueError:
            try:
                day = (
                    _parse_datetime(str(order.get("createdAt") or ""))
                    .astimezone(_SHANGHAI)
                    .date()
                )
            except (ValueError, TypeError):
                continue
        side = order.get("side")
        fee = _money(order.get("totalFeeYuan", "0"))
        realized = (
            _money(order.get("realizedPnlYuan", "0"))
            if side == SELL
            else Decimal("0.00")
        )
        all_time_fees += fee
        all_time_realized += realized
        if side == BUY:
            buy_count += 1
        elif side == SELL:
            sell_count += 1
            winning_sells += int(realized > 0)
        if (day.year, day.month) != (year, month_number):
            continue
        key = day.isoformat()
        row = rows[key]
        row["date"] = key
        row["tradeCount"] += 1
        row["feesYuan"] += fee
        row["realizedPnlYuan"] += realized
        month_fees += fee
        month_realized += realized
        if side == BUY:
            row["buyCount"] += 1
            row["buyAmountYuan"] += _money(order.get("grossAmountYuan", "0"))
        else:
            row["sellCount"] += 1
            row["sellAmountYuan"] += _money(order.get("grossAmountYuan", "0"))

    account_snapshot = _account_snapshot_from_ledger(ledger, order_limit=1)
    account_snapshot["orders"] = []
    account_snapshot["ordersLimit"] = 0
    account_snapshot["ordersTruncated"] = bool(ledger["orders"])
    days = [
        {
            key: (_money_text(value) if isinstance(value, Decimal) else value)
            for key, value in row.items()
        }
        for _, row in sorted(rows.items())
    ]
    return {
        "account": account_snapshot,
        "month": normalized_month,
        "days": days,
        "summary": {
            "totalTradeCount": len(ledger["orders"]),
            "buyCount": buy_count,
            "sellCount": sell_count,
            "winningSellCount": winning_sells,
            "allTimeRealizedPnlYuan": _money_text(all_time_realized),
            "allTimeFeesYuan": _money_text(all_time_fees),
            "monthTradeCount": sum(int(row["tradeCount"]) for row in rows.values()),
            "monthRealizedPnlYuan": _money_text(month_realized),
            "monthFeesYuan": _money_text(month_fees),
        },
        "feePolicy": _fee_policy(),
        "tPlusOneRule": _t_plus_one_rule(),
        "simulationOnly": True,
    }
