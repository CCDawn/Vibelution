"""Atomic, simulation-only rebalance batches for a financial Agent."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime
from typing import Any
from uuid import UUID, uuid5

from core.web.services import financial_market_service as market

from . import ledger as paper_ledger

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_BATCH_ORDERS = 40
_MAX_METADATA_BYTES = 16 * 1024
_REPORT_REFERENCE_IDS = {
    "id",
    "reportId",
    "sessionId",
    "turnId",
    "sourceSessionId",
    "sourceTurnId",
}
_REPORT_CONTENT_FIELDS = {"answer", "body", "content", "markdown", "prompt", "text"}


def _normalize_batch_id(value: str) -> tuple[str, UUID]:
    try:
        parsed = UUID(str(value or "").strip())
    except (AttributeError, TypeError, ValueError) as exc:
        raise paper_ledger.InvalidPaperOrderError("batchId 必须是有效 UUID") from exc
    return str(parsed), parsed


def _normalize_sha256(value: str, field_name: str) -> str:
    normalized = str(value or "").strip().lower()
    if not _SHA256_RE.fullmatch(normalized):
        raise paper_ledger.InvalidPaperOrderError(f"{field_name} 必须是 SHA-256")
    return normalized


def _ledger_fingerprint(payload: dict[str, Any]) -> str:
    """Fingerprint the account state only; proposal/batch history is excluded."""
    state = {
        key: payload[key]
        for key in ("account", "positions", "orders")
    }
    canonical = json.dumps(
        state,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _batch_from_ledger(
    payload: dict[str, Any], batch_id: str, request_hash: str
) -> dict[str, Any] | None:
    batches = payload.get("rebalanceBatches", [])
    for batch in reversed(batches):
        if not isinstance(batch, dict) or batch.get("batchId") != batch_id:
            continue
        if batch.get("requestHash") != request_hash:
            raise paper_ledger.IdempotencyConflictError(
                "batchId 已用于不同的调仓请求"
            )
        return copy.deepcopy(batch)
    return None


def _normalize_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise paper_ledger.InvalidPaperOrderError("metadata 必须是对象")
    if set(value) - {"proposalId", "planHash", "reports", "reportRefs"}:
        raise paper_ledger.InvalidPaperOrderError("metadata 只允许方案和报告引用")
    if "reports" in value and "reportRefs" in value:
        raise paper_ledger.InvalidPaperOrderError("metadata 不能重复提供报告引用")
    try:
        canonical = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise paper_ledger.InvalidPaperOrderError("metadata 必须是有限 JSON 数据") from exc
    if len(canonical.encode("utf-8")) > _MAX_METADATA_BYTES:
        raise paper_ledger.InvalidPaperOrderError("metadata 超出允许大小")
    metadata = json.loads(canonical)
    proposal_id = metadata.get("proposalId")
    if proposal_id is not None and (
        not isinstance(proposal_id, str) or not proposal_id.strip() or len(proposal_id) > 160
    ):
        raise paper_ledger.InvalidPaperOrderError("proposalId 无效")
    plan_hash = metadata.get("planHash")
    if plan_hash is not None:
        metadata["planHash"] = _normalize_sha256(plan_hash, "planHash")
    reports_key = "reportRefs" if "reportRefs" in metadata else "reports"
    reports = metadata.get(reports_key, [])
    if not isinstance(reports, list) or len(reports) > 20:
        raise paper_ledger.InvalidPaperOrderError("reports 必须是至多 20 项的引用列表")
    for reference in reports:
        if not isinstance(reference, dict) or not any(
            key in _REPORT_REFERENCE_IDS for key in reference
        ):
            raise paper_ledger.InvalidPaperOrderError("reports 只能保存报告引用")
        if any(str(key).lower() in _REPORT_CONTENT_FIELDS for key in reference):
            raise paper_ledger.InvalidPaperOrderError("reports 不得保存报告正文")
    return metadata


def _normalize_quotes(values: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(values, dict):
        raise paper_ledger.InvalidPaperOrderError("quotes 必须是服务端报价对象")
    normalized: dict[str, dict[str, Any]] = {}
    for raw_symbol, raw_quote in values.items():
        try:
            symbol = market.normalize_a_share_symbol(str(raw_symbol))
        except market.MarketDataError:
            # A quote map may include research candidates outside the A-share
            # paper ledger. Only symbols actually selected for an order matter.
            continue
        if not isinstance(raw_quote, dict) or raw_quote.get("symbol") != symbol:
            raise paper_ledger.InvalidPaperOrderError("服务端报价与股票代码不匹配")
        try:
            price = paper_ledger._money(raw_quote["priceYuan"])
            quote = {
                "symbol": symbol,
                "ticker": str(raw_quote["ticker"]),
                "name": str(raw_quote["name"]),
                "market": str(raw_quote["market"]),
                "priceYuan": paper_ledger._money_text(price),
                "timestamp": str(raw_quote["timestamp"]),
                "fetchedAt": str(raw_quote["fetchedAt"]),
                "source": str(raw_quote["source"]),
                "sourceUrl": str(raw_quote["sourceUrl"]),
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise paper_ledger.InvalidPaperOrderError("服务端报价信息不完整") from exc
        if price <= 0 or not all(
            quote[key]
            for key in (
                "ticker",
                "name",
                "market",
                "timestamp",
                "fetchedAt",
                "source",
                "sourceUrl",
            )
        ):
            raise paper_ledger.InvalidPaperOrderError("服务端报价信息不完整")
        if symbol in normalized:
            raise paper_ledger.InvalidPaperOrderError("quotes 包含重复股票代码")
        normalized[symbol] = quote
    return normalized


def _normalize_orders(
    values: Any, batch_uuid: UUID
) -> list[dict[str, Any]]:
    if not isinstance(values, list) or len(values) > _MAX_BATCH_ORDERS:
        raise paper_ledger.InvalidPaperOrderError(
            f"orders 必须是至多 {_MAX_BATCH_ORDERS} 项的列表"
        )
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for index, value in enumerate(values):
        if not isinstance(value, dict) or set(value) != {
            "symbol",
            "side",
            "quantity",
            "reason",
        }:
            raise paper_ledger.InvalidPaperOrderError(
                "每笔调仓订单只允许 symbol、side、quantity、reason"
            )
        # A temporary deterministic UUID lets the existing order validator own
        # symbol, side, quantity, and reason normalization in one place.
        temporary_id = str(uuid5(batch_uuid, f"normalize:{index}"))
        _, symbol, quantity, reason, _ = paper_ledger._normalize_order(
            temporary_id,
            value["symbol"],
            value["side"],
            value["quantity"],
            value["reason"],
        )
        side = str(value["side"] or "").strip().lower()
        identity = (symbol, side)
        if identity in seen:
            raise paper_ledger.InvalidPaperOrderError(
                "一个调仓批次不能重复包含同一股票和方向"
            )
        seen.add(identity)
        normalized.append(
            {
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "reason": reason,
            }
        )
    # This makes cash use, error selection, and the written ledger deterministic.
    return sorted(
        normalized,
        key=lambda item: (0 if item["side"] == paper_ledger.SELL else 1, item["symbol"]),
    )


def read_rebalance_context(agent_id: str) -> dict[str, Any]:
    """Return the current account fingerprint and quantities used for planning."""
    _, _, payload = paper_ledger._load_existing(agent_id)
    positions: list[dict[str, Any]] = []
    for symbol, row in sorted(payload["positions"].items()):
        lots = [
            lot
            for lot in row.get("lots", [])
            if int(lot.get("remainingQuantity") or 0) > 0
        ]
        quantity = sum(int(lot.get("remainingQuantity") or 0) for lot in lots)
        if quantity <= 0:
            continue
        sellable = (
            paper_ledger._available_quantity(lots)
            if paper_ledger._canonical_paper_symbol(symbol)
            else 0
        )
        position = {
            "symbol": symbol,
            "quantity": quantity,
            "sellableQuantity": sellable,
        }
        if row.get("name"):
            position["name"] = str(row["name"])
        positions.append(position)
    return {
        "agentId": payload["agentId"],
        "accountId": payload["account"]["accountId"],
        "cashYuan": paper_ledger._money_text(payload["account"].get("cashYuan", "0")),
        "positions": positions,
        "ledgerFingerprint": _ledger_fingerprint(payload),
    }


def find_rebalance(
    agent_id: str, batch_id: str, request_hash: str
) -> dict[str, Any] | None:
    """Find a completed batch before callers spend time refreshing market data."""
    normalized_id, _ = _normalize_batch_id(batch_id)
    normalized_hash = _normalize_sha256(request_hash, "requestHash")
    _, _, payload = paper_ledger._load_existing(agent_id)
    return _batch_from_ledger(payload, normalized_id, normalized_hash)


def execute_rebalance(
    agent_id: str,
    *,
    batch_id: str,
    request_hash: str,
    expected_ledger_fingerprint: str,
    orders: list[dict[str, Any]],
    quotes: dict[str, dict[str, Any]],
    metadata: dict[str, Any],
    expires_at: str | None = None,
) -> dict[str, Any]:
    """Apply an approved quote-frozen batch with one lock and one ledger write."""
    normalized_id, batch_uuid = _normalize_batch_id(batch_id)
    normalized_hash = _normalize_sha256(request_hash, "requestHash")

    agent, path, payload_before = paper_ledger._load_existing(agent_id)
    agent_id = str(agent["agentId"])
    previous = _batch_from_ledger(payload_before, normalized_id, normalized_hash)
    if previous is not None:
        return previous

    with paper_ledger._transaction_lock(path):
        current_agent = paper_ledger._financial_agent(agent_id)
        if paper_ledger._ledger_path(current_agent) != path:
            raise paper_ledger.PaperAccountConflictError(
                "模拟账户工作区已变化，请重新读取账户后再调仓"
            )
        payload = paper_ledger._load_ledger(path, agent_id)
        if payload is None:
            raise paper_ledger.AccountNotOpenedError("尚未开设模拟账户")
        previous = _batch_from_ledger(payload, normalized_id, normalized_hash)
        if previous is not None:
            return previous

        expected_fingerprint = _normalize_sha256(
            expected_ledger_fingerprint, "expectedLedgerFingerprint"
        )
        current_fingerprint = _ledger_fingerprint(payload)
        if current_fingerprint != expected_fingerprint:
            raise paper_ledger.PaperAccountConflictError(
                "模拟账户已变化，请重新预览并批准调仓"
            )

        normalized_orders = _normalize_orders(orders, batch_uuid)
        normalized_quotes = _normalize_quotes(quotes)
        for order in normalized_orders:
            if order["symbol"] not in normalized_quotes:
                raise paper_ledger.InvalidPaperOrderError(
                    f"缺少 {order['symbol']} 的服务端报价"
                )
        normalized_metadata = _normalize_metadata(metadata)

        working = copy.deepcopy(payload)
        working.setdefault("rebalanceBatches", [])
        before_cash = paper_ledger._money(working["account"].get("cashYuan", "0"))
        execution_time = paper_ledger._utc_now()
        if expires_at is not None:
            try:
                expiry = datetime.fromisoformat(expires_at)
            except (TypeError, ValueError) as exc:
                raise paper_ledger.InvalidPaperOrderError(
                    "expiresAt 必须是有效的带时区时间"
                ) from exc
            if expiry.tzinfo is None or expiry.utcoffset() is None:
                raise paper_ledger.InvalidPaperOrderError(
                    "expiresAt 必须是有效的带时区时间"
                )
            if execution_time >= expiry:
                raise paper_ledger.PaperAccountConflictError(
                    "调仓报价已过期，请重新检查行情与风控"
                )
        applied_orders: list[dict[str, Any]] = []
        for order in normalized_orders:
            stable_client_order_id = str(
                uuid5(batch_uuid, f"{order['symbol']}:{order['side']}")
            )
            applied = paper_ledger.apply_order_to_ledger(
                working,
                client_order_id=stable_client_order_id,
                symbol=order["symbol"],
                side=order["side"],
                quantity=order["quantity"],
                reason=order["reason"],
                quote=normalized_quotes[order["symbol"]],
                order_time=execution_time,
            )
            applied_orders.append(
                {
                    key: value
                    for key, value in applied.items()
                    if key != "requestFingerprint"
                }
            )

        batch = {
            "batchId": normalized_id,
            "requestHash": normalized_hash,
            "createdAt": paper_ledger._utc_text(execution_time),
            "accountId": working["account"]["accountId"],
            "orders": applied_orders,
            "metadata": normalized_metadata,
            "beforeCashYuan": paper_ledger._money_text(before_cash),
            "afterCashYuan": paper_ledger._money_text(
                working["account"].get("cashYuan", "0")
            ),
            "ledgerFingerprint": expected_fingerprint,
            "resultingLedgerFingerprint": _ledger_fingerprint(working),
            "simulationOnly": True,
        }
        working["rebalanceBatches"].append(batch)
        paper_ledger._write_ledger(path, working)

    paper_ledger.record_runtime_scene_event_quietly(
        "finance",
        "paper_rebalance",
        "finance.paper_rebalance.recorded",
        outcome="recorded",
        lifecycle=True,
        fields={
            "agentId": agent_id,
            "accountId": batch["accountId"],
            "batchId": normalized_id,
            "orderCount": len(applied_orders),
            "simulationOnly": True,
        },
    )
    return copy.deepcopy(batch)
