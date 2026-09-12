"""Ledger backed budget bridge for operator discussion model calls.

The operator discussion budget is frozen in the existing ``budget_receipts``
row.  The row is the only source of reservation and usage facts: this module
adds the currency projection while the shared budget adapter keeps the native
token projection in the same Ledger transaction.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from core.research.operator_optimization.model_budget_contracts import (
    OperatorDiscussionBudget,
    OperatorModelCallBudget,
    OperatorModelPrice,
)
from core.research.workflow.ledger import WorkflowLedgerStore

from ..research_runtime.budget_authority_adapter import record_budget_usage_in_uow
from ..research_runtime.ids import new_id


MONEY_ZERO = Decimal("0")
TOKENS_PER_MILLION = Decimal("1000000")
OPERATOR_MODEL_BUDGET_SCHEMA_VERSION = 1
OPERATOR_MODEL_BUDGET_KIND = "operator_model_budget"
_BUDGET_RECEIPT_COLUMNS = (
    "receipt_id",
    "run_id",
    "node_run_id",
    "reservation_id",
    "stage_id",
    "policy_hash",
    "reserved_json",
    "settled_json",
    "status",
    "created_at_ms",
    "updated_at_ms",
)
_TERMINAL_STATUSES = frozenset({"released", "failed", "voided"})
_KNOWN_OUTCOMES = frozenset(
    {"succeeded", "failed", "retried", "timeout", "cancelled", "blocked", "unknown"}
)


class ModelBudgetError(RuntimeError):
    """Fail closed at the operator model budget boundary."""

    def __init__(self, message: str, *, code: str = "operator_model_budget_error") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class OperatorBudgetSpec:
    budget: OperatorModelCallBudget
    budget_kind: str
    model_cost_limit: Decimal
    currency: str
    model_ref: str | None
    prices: tuple[OperatorModelPrice, ...]
    authorized: bool | None = None


def _identity(value: Any, label: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ModelBudgetError(
            f"{label} is required", code="operator_budget_binding_missing"
        )
    return result


def _counter(value: Any, label: str, *, allow_none: bool = False) -> int | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ModelBudgetError(
            f"{label} must be a non-negative integer",
            code="operator_model_usage_invalid",
        )
    return int(value)


def _money(value: Any, label: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ModelBudgetError(
            f"{label} must be a finite decimal amount",
            code="operator_model_money_invalid",
        )
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ModelBudgetError(
            f"{label} must be a finite decimal amount",
            code="operator_model_money_invalid",
        ) from exc
    if not result.is_finite() or result < MONEY_ZERO or (positive and result <= MONEY_ZERO):
        kind = "positive" if positive else "non-negative"
        raise ModelBudgetError(
            f"{label} must be a finite {kind} amount",
            code="operator_model_money_invalid",
        )
    return result


def _money_text(value: Decimal) -> str:
    normalized = value.normalize()
    return "0" if normalized == MONEY_ZERO else format(normalized, "f")


def _discussion(
    value: OperatorDiscussionBudget | Mapping[str, Any] | None,
) -> OperatorDiscussionBudget:
    if value is None:
        raise ModelBudgetError(
            "operator discussion budget is required; no generic token fallback is allowed",
            code="operator_model_budget_missing",
        )
    if isinstance(value, OperatorDiscussionBudget):
        return value
    try:
        return OperatorDiscussionBudget.model_validate(value)
    except Exception as exc:  # pydantic validation is part of this boundary
        raise ModelBudgetError(
            f"operator discussion budget is invalid: {exc}",
            code="operator_model_budget_invalid",
        ) from exc


def _call_budget(
    value: OperatorModelCallBudget | Mapping[str, Any] | None,
    *,
    kind: str,
) -> OperatorModelCallBudget:
    if value is None:
        raise ModelBudgetError(
            f"operator {kind} budget is required; no implicit budget fallback is allowed",
            code="operator_model_budget_missing",
        )
    if isinstance(value, OperatorModelCallBudget):
        return value
    try:
        return OperatorModelCallBudget.model_validate(value)
    except Exception as exc:
        raise ModelBudgetError(
            f"operator {kind} budget is invalid: {exc}",
            code="operator_model_budget_invalid",
        ) from exc


def _prices(discussion: OperatorDiscussionBudget) -> tuple[OperatorModelPrice, ...]:
    seen: set[str] = set()
    prices: list[OperatorModelPrice] = []
    for price in discussion.prices:
        model_ref = _identity(price.modelRef, "prices.modelRef")
        if model_ref in seen:
            raise ModelBudgetError(
                f"model {model_ref!r} has duplicate frozen prices",
                code="operator_model_price_ambiguous",
            )
        seen.add(model_ref)
        prices.append(price)
    if not prices:
        raise ModelBudgetError(
            "operator discussion budget has no frozen model prices",
            code="operator_model_price_missing",
        )
    return tuple(prices)


def _price(discussion: OperatorDiscussionBudget, model_ref: str) -> OperatorModelPrice:
    normalized = _identity(model_ref, "model_ref")
    matches = [item for item in _prices(discussion) if item.modelRef == normalized]
    if not matches:
        raise ModelBudgetError(
            f"model {normalized!r} has no frozen operator price",
            code="operator_model_price_missing",
        )
    return matches[0]


def _tokens(value: Any, label: str) -> int:
    result = _counter(value, label)
    assert result is not None
    return result


def _cost_for_price(price: OperatorModelPrice, input_tokens: int, output_tokens: int) -> Decimal:
    input_rate = _money(price.inputPerMillion, "inputPerMillion")
    output_rate = _money(price.outputPerMillion, "outputPerMillion")
    return (
        Decimal(input_tokens) * input_rate / TOKENS_PER_MILLION
        + Decimal(output_tokens) * output_rate / TOKENS_PER_MILLION
    ).normalize()


def calculate_model_cost(
    discussion_budget: OperatorDiscussionBudget | Mapping[str, Any],
    *,
    model_ref: str,
    input_tokens: int,
    output_tokens: int,
) -> Decimal:
    """Calculate cost from the frozen input/output rates."""

    discussion = _discussion(discussion_budget)
    input_count = _tokens(input_tokens, "input_tokens")
    output_count = _tokens(output_tokens, "output_tokens")
    if output_count > discussion.maxOutputTokensPerCall:
        raise ModelBudgetError(
            "output token count exceeds the frozen per-call limit",
            code="operator_model_output_limit_reached",
        )
    if input_count + output_count > discussion.tokenLimit:
        raise ModelBudgetError(
            "token count exceeds the frozen discussion limit",
            code="operator_model_token_limit_reached",
        )
    return _cost_for_price(_price(discussion, model_ref), input_count, output_count)


def calculate_max_reserved_cost(
    discussion_budget: OperatorDiscussionBudget | Mapping[str, Any],
    *,
    model_ref: str | None = None,
) -> Decimal:
    """Return the worst case amount for the frozen discussion call window."""

    discussion = _call_budget(discussion_budget, kind="discussion")
    max_output = min(
        discussion.tokenLimit,
        discussion.maxCalls * discussion.maxOutputTokensPerCall,
    )
    prices = (_price(discussion, model_ref),) if model_ref else _prices(discussion)
    bounds: list[Decimal] = []
    for price in prices:
        input_rate = _money(price.inputPerMillion, "inputPerMillion")
        output_rate = _money(price.outputPerMillion, "outputPerMillion")
        all_input = Decimal(discussion.tokenLimit) * input_rate
        capped_output = (
            Decimal(discussion.tokenLimit - max_output) * input_rate
            + Decimal(max_output) * output_rate
        )
        bounds.append(max(all_input, capped_output) / TOKENS_PER_MILLION)
    return max(bounds).normalize()


def build_operator_budget_policy(
    discussion_budget: OperatorDiscussionBudget | Mapping[str, Any],
    *,
    stage_id: str = "execution_iteration",
) -> dict[str, Any]:
    """Build the explicit token/call limits for the native budget adapter."""

    discussion = _discussion(discussion_budget)
    stage = {
        "tokens": discussion.tokenLimit,
        "toolCalls": discussion.maxCalls,
        "wallClockSeconds": 0,
    }
    return {
        "tokens": discussion.tokenLimit,
        "toolCalls": discussion.maxCalls,
        "wallClockSeconds": 0,
        "maxRetries": max(0, discussion.maxCalls - 1),
        "stageBudgets": {str(stage_id).strip() or "execution_iteration": stage},
    }


def _campaign_value(budget: Any, key: str) -> Any:
    if isinstance(budget, Mapping):
        return budget.get(key)
    return getattr(budget, key, None)


def _spec(
    *,
    discussion_budget: OperatorDiscussionBudget | Mapping[str, Any] | None,
    knowledge_budget: OperatorModelCallBudget | Mapping[str, Any] | None = None,
    model_cost_limit: Any,
    campaign_currency: str | None,
    model_ref: str | None,
    authorized: bool | None = None,
    campaign_budget: Any = None,
    budget_kind: str | None = None,
) -> OperatorBudgetSpec:
    """Normalize one explicit call budget and the frozen campaign fields."""

    if budget_kind is None:
        budget_kind = "knowledge" if knowledge_budget is not None else "discussion"
    if budget_kind not in {"discussion", "knowledge"}:
        raise ModelBudgetError("operator model budget kind is invalid", code="operator_model_budget_invalid")

    if campaign_budget is not None:
        if budget_kind == "knowledge":
            if knowledge_budget is None:
                knowledge_budget = _campaign_value(campaign_budget, "knowledge")
        elif discussion_budget is None:
            discussion_budget = _campaign_value(campaign_budget, "discussion")
        if model_cost_limit is None:
            model_cost_limit = _campaign_value(campaign_budget, "modelCostLimit")
        if campaign_currency is None:
            campaign_currency = _campaign_value(campaign_budget, "currency")
        if authorized is None:
            raw_authorized = _campaign_value(campaign_budget, "authorized")
            if raw_authorized is not None:
                authorized = bool(raw_authorized)

    if budget_kind == "knowledge":
        if discussion_budget is not None:
            raise ModelBudgetError("knowledge budget cannot use discussion budget", code="operator_model_budget_contract_conflict")
        budget = _call_budget(knowledge_budget, kind="knowledge")
    else:
        budget = _discussion(discussion_budget)
    if authorized is False:
        raise ModelBudgetError(
            "operator model budget is not authorized",
            code="operator_model_budget_unauthorized",
        )
    limit = _money(model_cost_limit, "model_cost_limit", positive=True)
    currency = str(campaign_currency or "").strip().upper()
    if currency not in {"CNY", "USD"}:
        raise ModelBudgetError(
            "campaign currency must be CNY or USD",
            code="operator_model_currency_invalid",
        )
    frozen_prices = _prices(budget)
    if any(str(item.currency) != currency for item in frozen_prices):
        raise ModelBudgetError(
            "campaign currency differs from a frozen model price currency",
            code="operator_model_currency_mismatch",
        )
    selected_model = _price(budget, model_ref).modelRef if model_ref else None
    return OperatorBudgetSpec(
        budget=budget,
        budget_kind=budget_kind,
        model_cost_limit=limit,
        currency=currency,
        model_ref=selected_model,
        prices=frozen_prices,
        authorized=authorized,
    )


def _row_mapping(row: Any) -> dict[str, Any]:
    if row is None:
        raise ModelBudgetError(
            "operator model budget receipt is missing",
            code="operator_model_receipt_missing",
        )
    return dict(zip(_BUDGET_RECEIPT_COLUMNS, row, strict=True))


def _json_object(raw: Any, label: str) -> dict[str, Any]:
    if raw in (None, ""):
        return {}
    try:
        value = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ModelBudgetError(
            f"{label} is not valid JSON", code="operator_model_receipt_corrupt"
        ) from exc
    if not isinstance(value, dict):
        raise ModelBudgetError(
            f"{label} must be a JSON object", code="operator_model_receipt_corrupt"
        )
    return value


def _operator_metadata(
    payload: Mapping[str, Any], *, required: bool = True
) -> dict[str, Any] | None:
    raw = payload.get("operatorModelBudget")
    if raw is None and not required:
        return None
    if not isinstance(raw, Mapping):
        raise ModelBudgetError(
            "operatorModelBudget projection is missing or corrupt",
            code="operator_model_receipt_corrupt",
        )
    result = dict(raw)
    if (
        result.get("schemaVersion") != OPERATOR_MODEL_BUDGET_SCHEMA_VERSION
        or result.get("kind") != OPERATOR_MODEL_BUDGET_KIND
    ):
        raise ModelBudgetError(
            "operatorModelBudget projection header is invalid",
            code="operator_model_receipt_corrupt",
        )
    return result


def _metadata_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    metadata = _operator_metadata(_json_object(row.get("reserved_json"), "reserved_json"))
    assert metadata is not None
    return metadata


def _invocation_map(metadata: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    raw = metadata.get("invocations")
    if raw is None:
        return {}
    if not isinstance(raw, Mapping) or any(not isinstance(item, Mapping) for item in raw.values()):
        raise ModelBudgetError(
            "operator invocation projection is corrupt",
            code="operator_model_receipt_corrupt",
        )
    return {str(key): dict(value) for key, value in raw.items()}


def _dynamic_metadata(
    metadata: Mapping[str, Any],
    invocations: Mapping[str, Mapping[str, Any]],
    *,
    force_unsettled: bool = False,
) -> dict[str, Any]:
    actual = MONEY_ZERO
    estimated = MONEY_ZERO
    known = MONEY_ZERO
    tokens_used = 0
    unsettled = force_unsettled
    for entry in invocations.values():
        input_tokens = _tokens(entry.get("inputTokens", 0), "invocation.inputTokens")
        output_tokens = _tokens(entry.get("outputTokens", 0), "invocation.outputTokens")
        if bool(entry.get("tokensKnown", True)):
            tokens_used += input_tokens + output_tokens
        raw_amount = entry.get("amount")
        cost_status = str(entry.get("costStatus") or "unsettled")
        if raw_amount not in (None, ""):
            amount = _money(raw_amount, "invocation.amount")
            if cost_status == "settled" and not bool(entry.get("usageEstimated")):
                actual += amount
                known += amount
            else:
                estimated += amount
                unsettled = True
        else:
            unsettled = True
        unsettled = unsettled or cost_status != "settled"

    result = dict(metadata)
    reserved = _money(result.get("reservedAmount", "0"), "operatorModelBudget.reservedAmount")
    result.update(
        {
            "invocations": {str(key): dict(value) for key, value in invocations.items()},
            "callsUsed": len(invocations),
            "tokensUsed": tokens_used,
            "knownAmount": _money_text(known),
            "estimatedAmount": _money_text(estimated),
            "actualAmount": _money_text(actual),
            "costStatus": "unsettled" if unsettled else "settled",
        }
    )
    if unsettled:
        result["unsettledAmount"] = _money_text(reserved)
    else:
        result["unsettledAmount"] = "0"
        result["releasedAmount"] = _money_text(max(MONEY_ZERO, reserved - actual))
    return result


def _summary(
    row: Mapping[str, Any], metadata: Mapping[str, Any], *, idempotent: bool
) -> dict[str, Any]:
    current = _dynamic_metadata(
        metadata,
        _invocation_map(metadata),
        force_unsettled=str(row.get("status") or "reserved") != "settled",
    )
    model_refs = [
        str(item.get("modelRef"))
        for item in current.get("prices", [])
        if isinstance(item, Mapping) and str(item.get("modelRef") or "").strip()
    ]
    model_ref = str(current.get("modelRef") or "")
    if not model_ref and len(model_refs) == 1:
        model_ref = model_refs[0]
    return {
        "reservationId": str(row.get("reservation_id") or ""),
        "receiptId": str(row.get("receipt_id") or ""),
        "runId": str(row.get("run_id") or ""),
        "nodeRunId": str(row.get("node_run_id") or ""),
        "optimizationCampaignId": str(current.get("optimizationCampaignId") or ""),
        "roundId": str(current.get("roundId") or ""),
        "modelRef": model_ref,
        "modelRefs": model_refs,
        "priceVersion": str(current.get("priceVersion") or ""),
        "currency": str(current.get("currency") or ""),
        "reservedAmount": _money(
            current.get("reservedAmount", "0"), "operatorModelBudget.reservedAmount"
        ),
        "actualAmount": _money(
            current.get("actualAmount", "0"), "operatorModelBudget.actualAmount"
        ),
        "knownAmount": _money(
            current.get("knownAmount", "0"), "operatorModelBudget.knownAmount"
        ),
        "estimatedAmount": _money(
            current.get("estimatedAmount", "0"), "operatorModelBudget.estimatedAmount"
        ),
        "costStatus": str(current.get("costStatus") or "unsettled"),
        "status": str(row.get("status") or "reserved"),
        "callsUsed": int(current.get("callsUsed") or 0),
        "tokensUsed": int(current.get("tokensUsed") or 0),
        "idempotent": idempotent,
        "maxCalls": int(current.get("maxCalls") or 0),
        "tokenLimit": int(current.get("tokenLimit") or 0),
        "maxOutputTokensPerCall": int(current.get("maxOutputTokensPerCall") or 0),
    }


def _load_row(uow: Any, reservation_id: str) -> dict[str, Any]:
    row = uow.repository.execute(
        "SELECT receipt_id, run_id, node_run_id, reservation_id, stage_id, "
        "policy_hash, reserved_json, settled_json, status, created_at_ms, "
        "updated_at_ms FROM budget_receipts WHERE reservation_id = ?",
        (reservation_id,),
    ).fetchone()
    return _row_mapping(row)


def _check_parent_node(uow: Any, *, run_id: str, node_run_id: str) -> None:
    if uow.repository.get_run(run_id) is None:
        raise ModelBudgetError(
            f"workflow run {run_id} is missing", code="operator_parent_run_missing"
        )
    row = uow.repository.execute(
        "SELECT run_id FROM node_attempts WHERE node_run_id = ?", (node_run_id,)
    ).fetchone()
    if row is None or str(row[0] or "") != run_id:
        raise ModelBudgetError(
            "operator model budget requires its actual parent NodeRun",
            code="operator_parent_node_missing",
        )


def _check_binding(
    metadata: Mapping[str, Any],
    *,
    run_id: str,
    node_run_id: str,
    campaign_id: str | None = None,
    round_id: str | None = None,
    model_ref: str | None = None,
    currency: str | None = None,
    budget_kind: str | None = None,
) -> None:
    for key, expected in (
        ("parentRunId", run_id),
        ("parentNodeRunId", node_run_id),
        ("optimizationCampaignId", campaign_id),
        ("roundId", round_id),
        ("currency", currency),
        ("budgetKind", budget_kind),
    ):
        if expected not in (None, "") and str(metadata.get(key) or "") != str(expected):
            raise ModelBudgetError(
                f"operator model budget {key} binding differs",
                code="operator_model_binding_mismatch",
            )
    if model_ref:
        allowed = {
            str(item.get("modelRef") or "")
            for item in metadata.get("prices", [])
            if isinstance(item, Mapping)
        }
        if model_ref not in allowed:
            raise ModelBudgetError(
                "operator model budget modelRef binding differs",
                code="operator_model_binding_mismatch",
            )


def _write_payload(
    uow: Any,
    row: Mapping[str, Any],
    payload: Mapping[str, Any],
    *,
    status: str,
    now_ms: int,
) -> None:
    uow.repository.update_budget_receipt(
        str(row["receipt_id"]),
        status=status,
        now_ms=now_ms,
        settled_json=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    )


def _reservation_metadata(
    *,
    spec: OperatorBudgetSpec,
    campaign_id: str,
    round_id: str,
    run_id: str,
    node_run_id: str,
    reserved_amount: Decimal,
) -> dict[str, Any]:
    frozen_prices = [
        {
            "modelRef": str(price.modelRef),
            "priceVersion": str(price.priceVersion),
            "currency": str(price.currency),
            "inputPerMillion": float(price.inputPerMillion),
            "outputPerMillion": float(price.outputPerMillion),
        }
        for price in spec.prices
    ]
    first = spec.prices[0]
    return {
        "schemaVersion": OPERATOR_MODEL_BUDGET_SCHEMA_VERSION,
        "kind": OPERATOR_MODEL_BUDGET_KIND,
        "budgetKind": spec.budget_kind,
        "optimizationCampaignId": campaign_id,
        "roundId": round_id,
        "parentRunId": run_id,
        "parentNodeRunId": node_run_id,
        "modelRef": spec.model_ref or str(first.modelRef),
        "modelRefs": [str(price.modelRef) for price in spec.prices],
        "priceVersion": str(first.priceVersion),
        "priceVersions": [str(price.priceVersion) for price in spec.prices],
        "prices": frozen_prices,
        "currency": spec.currency,
        "modelCostLimit": _money_text(spec.model_cost_limit),
        "tokenLimit": spec.budget.tokenLimit,
        "maxOutputTokensPerCall": spec.budget.maxOutputTokensPerCall,
        "maxCalls": spec.budget.maxCalls,
        "reservedAmount": _money_text(reserved_amount),
        "costStatus": "unsettled",
        "costBasis": "frozen_price_upper_bound",
        "knownAmount": "0",
        "estimatedAmount": "0",
        "actualAmount": "0",
        "unsettledAmount": _money_text(reserved_amount),
        "callsUsed": 0,
        "tokensUsed": 0,
        "invocations": {},
    }


def _reserved_payload(
    metadata: Mapping[str, Any], *, spec: OperatorBudgetSpec
) -> dict[str, Any]:
    limits = {
        "tokens": spec.budget.tokenLimit,
        "toolCalls": spec.budget.maxCalls,
        "seconds": 0,
        "retries": max(0, spec.budget.maxCalls - 1),
    }
    return {
        "schemaVersion": OPERATOR_MODEL_BUDGET_SCHEMA_VERSION,
        "reserved": {"estimatedTokens": spec.budget.tokenLimit, **limits},
        "limits": limits,
        "operatorModelBudget": dict(metadata),
        "source": "operator-model-budget",
    }


def _campaign_committed_amounts(
    uow: Any,
    *,
    campaign_id: str,
    currency: str,
    model_cost_limit: Decimal,
) -> Decimal:
    rows = uow.repository.execute(
        "SELECT receipt_id, run_id, node_run_id, reservation_id, stage_id, "
        "policy_hash, reserved_json, settled_json, status, created_at_ms, "
        "updated_at_ms FROM budget_receipts"
    ).fetchall()
    committed = MONEY_ZERO
    for raw_row in rows:
        row = _row_mapping(raw_row)
        reserved = _json_object(row.get("reserved_json"), "reserved_json")
        metadata = _operator_metadata(reserved, required=False)
        if metadata is None or str(metadata.get("optimizationCampaignId") or "") != campaign_id:
            continue
        if str(metadata.get("currency") or "").upper() != currency:
            raise ModelBudgetError(
                "operator campaign contains receipts in multiple currencies",
                code="operator_model_currency_mismatch",
            )
        if _money(metadata.get("modelCostLimit"), "operatorModelBudget.modelCostLimit", positive=True) != model_cost_limit:
            raise ModelBudgetError(
                "operator campaign budget limit differs from its frozen receipt",
                code="operator_model_budget_contract_conflict",
            )
        if str(row.get("status") or "") == "released":
            continue
        settled = _json_object(row.get("settled_json"), "settled_json")
        settled_metadata = _operator_metadata(settled, required=False)
        if settled_metadata is not None and str(settled_metadata.get("costStatus") or "") == "settled":
            committed += _money(
                settled_metadata.get("actualAmount", "0"),
                "operatorModelBudget.actualAmount",
            )
        else:
            committed += _money(
                metadata.get("reservedAmount", "0"),
                "operatorModelBudget.reservedAmount",
            )
    return committed


def reserve_model_budget_in_uow(
    uow: Any,
    *,
    run_id: str,
    node_run_id: str,
    optimization_campaign_id: str,
    round_id: str,
    discussion_budget: OperatorDiscussionBudget | Mapping[str, Any] | None = None,
    knowledge_budget: OperatorModelCallBudget | Mapping[str, Any] | None = None,
    model_cost_limit: Any = None,
    campaign_currency: str | None = None,
    model_ref: str | None = None,
    policy_hash: str = "",
    reservation_id: str | None = None,
    authorized: bool | None = None,
    campaign_budget: Any = None,
    budget_kind: str | None = None,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Atomically reserve the operator discussion upper bound."""

    run_id = _identity(run_id, "run_id")
    node_run_id = _identity(node_run_id, "node_run_id")
    campaign_id = _identity(optimization_campaign_id, "optimization_campaign_id")
    round_id = _identity(round_id, "round_id")
    spec = _spec(
        discussion_budget=discussion_budget,
        knowledge_budget=knowledge_budget,
        model_cost_limit=model_cost_limit,
        campaign_currency=campaign_currency,
        model_ref=model_ref,
        authorized=authorized,
        campaign_budget=campaign_budget,
        budget_kind=budget_kind,
    )
    reservation_key = _identity(reservation_id or f"reservation-{node_run_id}", "reservation_id")
    reserved_amount = calculate_max_reserved_cost(spec.budget)
    timestamp = int(now_ms if now_ms is not None else time.time() * 1000)

    _check_parent_node(uow, run_id=run_id, node_run_id=node_run_id)
    existing_row = uow.repository.execute(
        "SELECT receipt_id, run_id, node_run_id, reservation_id, stage_id, "
        "policy_hash, reserved_json, settled_json, status, created_at_ms, "
        "updated_at_ms FROM budget_receipts WHERE reservation_id = ?",
        (reservation_key,),
    ).fetchone()
    if existing_row is not None:
        existing = _row_mapping(existing_row)
        existing_metadata = _metadata_from_row(existing)
        _check_binding(
            existing_metadata,
            run_id=run_id,
            node_run_id=node_run_id,
            campaign_id=campaign_id,
            round_id=round_id,
            model_ref=spec.model_ref,
            currency=spec.currency,
            budget_kind=spec.budget_kind,
        )
        if str(existing.get("policy_hash") or "") != str(policy_hash or ""):
            raise ModelBudgetError(
                "operator reservation policy hash differs on replay",
                code="operator_model_binding_mismatch",
            )
        settled_metadata = _operator_metadata(
            _json_object(existing.get("settled_json"), "settled_json"), required=False
        )
        return _summary(existing, settled_metadata or existing_metadata, idempotent=True)

    committed = _campaign_committed_amounts(
        uow,
        campaign_id=campaign_id,
        currency=spec.currency,
        model_cost_limit=spec.model_cost_limit,
    )
    if committed + reserved_amount > spec.model_cost_limit:
        raise ModelBudgetError(
            "operator campaign model-cost limit would be exceeded by this reservation",
            code="operator_model_budget_limit_reached",
        )
    metadata = _reservation_metadata(
        spec=spec,
        campaign_id=campaign_id,
        round_id=round_id,
        run_id=run_id,
        node_run_id=node_run_id,
        reserved_amount=reserved_amount,
    )
    payload = _reserved_payload(metadata, spec=spec)
    receipt_id = new_id("br")
    uow.repository.insert_budget_receipt(
        receipt_id=receipt_id,
        run_id=run_id,
        node_run_id=node_run_id,
        reservation_id=reservation_key,
        stage_id="execution_iteration",
        policy_hash=str(policy_hash or ""),
        reserved_json=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        created_at_ms=timestamp,
    )
    return _summary(
        {
            "receipt_id": receipt_id,
            "run_id": run_id,
            "node_run_id": node_run_id,
            "reservation_id": reservation_key,
            "stage_id": "execution_iteration",
            "policy_hash": str(policy_hash or ""),
            "reserved_json": json.dumps(payload, ensure_ascii=False),
            "settled_json": None,
            "status": "reserved",
        },
        metadata,
        idempotent=False,
    )


def reserve_model_budget(store: WorkflowLedgerStore | None, **kwargs: Any) -> dict[str, Any]:
    """Store wrapper for :func:`reserve_model_budget_in_uow`."""

    _spec(
        discussion_budget=kwargs.get("discussion_budget"),
        knowledge_budget=kwargs.get("knowledge_budget"),
        model_cost_limit=kwargs.get("model_cost_limit"),
        campaign_currency=kwargs.get("campaign_currency"),
        model_ref=kwargs.get("model_ref"),
        authorized=kwargs.get("authorized"),
        campaign_budget=kwargs.get("campaign_budget"),
        budget_kind=kwargs.get("budget_kind"),
    )
    if store is None:
        raise ModelBudgetError(
            "a WorkflowLedgerStore is required for model budget reservation",
            code="operator_model_store_missing",
        )
    return store.submit(
        lambda uow: reserve_model_budget_in_uow(uow, **kwargs), force_flush=True
    ).result(timeout=30)


def _usage_fields(
    *,
    usage: Mapping[str, Any] | None,
    model_ref: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
    usage_known: bool | None,
    usage_estimated: bool,
    outcome: str,
) -> dict[str, Any]:
    source = dict(usage or {})
    token_source = source.get("tokenUsage")
    if not isinstance(token_source, Mapping):
        token_source = source

    def read(current: int | None, *keys: str) -> tuple[int | None, bool]:
        if current is not None:
            return _tokens(current, keys[0]) , True
        for key in keys:
            if token_source.get(key) is not None:
                return _tokens(token_source[key], key), True
        return None, False

    input_count, input_present = read(input_tokens, "inputTokens", "input_tokens", "promptTokens")
    output_count, output_present = read(
        output_tokens, "outputTokens", "output_tokens", "completionTokens"
    )
    if input_count is None:
        input_count = 0
    if output_count is None:
        output_count = 0
    if usage_known is None:
        usage_known = input_present or output_present or any(
            key in token_source for key in ("totalTokens", "total_tokens")
        )
    if not isinstance(usage_known, bool):
        raise ModelBudgetError(
            "usage_known must be boolean", code="operator_model_usage_invalid"
        )
    if "usageEstimated" in source:
        usage_estimated = bool(source["usageEstimated"])
    if "usage_estimated" in source:
        usage_estimated = bool(source["usage_estimated"])
    resolved_model = str(
        model_ref or source.get("modelRef") or source.get("model") or ""
    ).strip()
    resolved_outcome = str(source.get("outcome") or outcome or "unknown").strip().lower()
    if resolved_outcome not in _KNOWN_OUTCOMES:
        resolved_outcome = "unknown"
    return {
        "modelRef": resolved_model,
        "inputTokens": input_count,
        "outputTokens": output_count,
        "usageKnown": usage_known,
        "usageEstimated": bool(usage_estimated),
        "outcome": resolved_outcome,
    }


def _frozen_price(metadata: Mapping[str, Any], model_ref: str) -> dict[str, Any]:
    normalized = _identity(model_ref, "model_ref")
    prices = metadata.get("prices")
    if not isinstance(prices, list):
        raise ModelBudgetError(
            "operator reservation has no frozen model prices",
            code="operator_model_receipt_corrupt",
        )
    matches = [
        dict(item)
        for item in prices
        if isinstance(item, Mapping) and str(item.get("modelRef") or "") == normalized
    ]
    if not matches:
        raise ModelBudgetError(
            "invocation model is outside the frozen reservation price list",
            code="operator_model_identity_mismatch",
        )
    return matches[0]


def _validate_invocation(metadata: Mapping[str, Any], fields: Mapping[str, Any]) -> dict[str, Any]:
    selected = _frozen_price(metadata, _identity(fields.get("modelRef"), "model_ref"))
    if str(selected.get("currency") or "") != str(metadata.get("currency") or ""):
        raise ModelBudgetError(
            "invocation model price currency differs from the reservation",
            code="operator_model_currency_mismatch",
        )
    input_count = _tokens(fields.get("inputTokens", 0), "input_tokens")
    output_count = _tokens(fields.get("outputTokens", 0), "output_tokens")
    admission = bool(fields.get("usageEstimated"))
    # Limits gate new consumption. Observed provider usage is an accounting
    # fact even if the estimate or the provider's output limit was exceeded.
    if admission and output_count > int(metadata.get("maxOutputTokensPerCall") or 0):
        raise ModelBudgetError(
            "invocation output exceeds the frozen per-call limit",
            code="operator_model_output_limit_reached",
        )
    if admission and input_count + output_count > int(
        metadata.get("tokenLimit") or 0
    ):
        raise ModelBudgetError(
            "invocation tokens exceed the frozen discussion limit",
            code="operator_model_token_limit_reached",
        )
    return selected


def _token_sum(invocations: Mapping[str, Mapping[str, Any]]) -> int:
    return sum(
        _tokens(item.get("inputTokens", 0), "invocation.inputTokens")
        + _tokens(item.get("outputTokens", 0), "invocation.outputTokens")
        for item in invocations.values()
        if bool(item.get("tokensKnown", True))
    )


def _entry(metadata: Mapping[str, Any], fields: Mapping[str, Any]) -> dict[str, Any]:
    input_count = _tokens(fields.get("inputTokens", 0), "input_tokens")
    output_count = _tokens(fields.get("outputTokens", 0), "output_tokens")
    selected = _frozen_price(metadata, _identity(fields.get("modelRef"), "model_ref"))
    usage_known = bool(fields.get("usageKnown"))
    estimated = bool(fields.get("usageEstimated"))
    result: dict[str, Any] = {
        "modelRef": str(selected.get("modelRef") or ""),
        "priceVersion": str(selected.get("priceVersion") or ""),
        "currency": str(selected.get("currency") or ""),
        "inputTokens": input_count,
        "outputTokens": output_count,
        "tokensKnown": usage_known,
        "usageEstimated": estimated,
        "outcome": str(fields.get("outcome") or "unknown"),
        "costStatus": "unsettled",
    }
    if usage_known:
        result["amount"] = _money_text(
            _cost_for_price(
                OperatorModelPrice.model_validate(selected), input_count, output_count
            )
        )
        result["costStatus"] = "unsettled" if estimated else "settled"
    return result


def _native_replacement(
    payload: dict[str, Any], invocation_id: str, entry: Mapping[str, Any]
) -> None:
    raw_invocations = payload.get("invocations")
    if not isinstance(raw_invocations, Mapping):
        return
    prior = raw_invocations.get(invocation_id)
    if not isinstance(prior, Mapping):
        return
    invocations = {str(key): dict(value) for key, value in raw_invocations.items()}
    invocations[invocation_id].update(
        {
            "inputTokens": entry["inputTokens"],
            "outputTokens": entry["outputTokens"],
            "tokens": entry["inputTokens"] + entry["outputTokens"],
            "usageEstimated": entry["usageEstimated"],
        }
    )
    usage_raw = payload.get("usage")
    usage = dict(usage_raw) if isinstance(usage_raw, Mapping) else {}
    totals = {
        "inputTokens": 0,
        "outputTokens": 0,
        "cachedInputTokens": 0,
        "uncachedInputTokens": 0,
        "reasoningTokens": 0,
        "toolCalls": 0,
        "wallClockSeconds": 0,
    }
    for item in invocations.values():
        for key in totals:
            totals[key] += _tokens(item.get(key, 0), f"invocation.{key}")
    usage.update(totals)
    usage["tokens"] = totals["inputTokens"] + totals["outputTokens"]
    usage["usageEstimated"] = any(
        bool(item.get("usageEstimated")) for item in invocations.values()
    )
    payload["invocations"] = invocations
    payload["usage"] = usage


def _reservation_ids(reservation: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        _identity(reservation.get("reservationId"), "reservation_id"),
        str(reservation.get("runId") or "").strip(),
        str(reservation.get("nodeRunId") or "").strip(),
    )


def _record_or_admit_in_uow(
    uow: Any,
    *,
    reservation: Mapping[str, Any],
    invocation_id: str,
    fields: Mapping[str, Any],
    now_ms: int,
) -> dict[str, Any]:
    reservation_id, expected_run, expected_node = _reservation_ids(reservation)
    invocation_id = _identity(invocation_id, "invocation_id")
    row = _load_row(uow, reservation_id)
    if expected_run and str(row.get("run_id") or "") != expected_run:
        raise ModelBudgetError(
            "operator reservation run binding differs",
            code="operator_model_binding_mismatch",
        )
    if expected_node and str(row.get("node_run_id") or "") != expected_node:
        raise ModelBudgetError(
            "operator reservation NodeRun binding differs",
            code="operator_model_binding_mismatch",
        )
    if str(row.get("status") or "") in _TERMINAL_STATUSES:
        raise ModelBudgetError(
            f"operator reservation is terminal ({row.get('status')})",
            code="operator_model_budget_terminal",
        )
    reserved_payload = _json_object(row.get("reserved_json"), "reserved_json")
    reserved_metadata = _operator_metadata(reserved_payload)
    assert reserved_metadata is not None
    settled_payload = _json_object(row.get("settled_json"), "settled_json")
    current_metadata = _operator_metadata(settled_payload, required=False) or reserved_metadata
    invocations = _invocation_map(current_metadata)

    incoming_model = str(fields.get("modelRef") or "").strip()
    if not incoming_model:
        frozen_models = [
            str(item.get("modelRef") or "")
            for item in current_metadata.get("prices", [])
            if isinstance(item, Mapping) and str(item.get("modelRef") or "").strip()
        ]
        if len(frozen_models) != 1:
            raise ModelBudgetError(
                "invocation model is required when the reservation freezes multiple models",
                code="operator_model_route_missing",
            )
        incoming_model = frozen_models[0]
    fields = {**fields, "modelRef": incoming_model}
    _validate_invocation(current_metadata, fields)

    existing = invocations.get(invocation_id)
    if existing is not None:
        if str(existing.get("costStatus") or "") == "settled" and not bool(
            existing.get("usageEstimated")
        ):
            same = (
                str(existing.get("modelRef") or "") == incoming_model
                and _tokens(existing.get("inputTokens", 0), "invocation.inputTokens")
                == _tokens(fields.get("inputTokens", 0), "input_tokens")
                and _tokens(existing.get("outputTokens", 0), "invocation.outputTokens")
                == _tokens(fields.get("outputTokens", 0), "output_tokens")
                and str(existing.get("outcome") or "")
                == str(fields.get("outcome") or "")
            )
            if not same:
                raise ModelBudgetError(
                    "operator invocation replay conflicts with its first usage",
                    code="operator_invocation_replay_conflict",
                )
            return _summary(row, current_metadata, idempotent=True)

        previous_pair = (
            _tokens(existing.get("inputTokens", 0), "invocation.inputTokens"),
            _tokens(existing.get("outputTokens", 0), "invocation.outputTokens"),
        )
        incoming_pair = (
            _tokens(fields.get("inputTokens", 0), "input_tokens"),
            _tokens(fields.get("outputTokens", 0), "output_tokens"),
        )
        if (
            bool(existing.get("tokensKnown", True))
            and bool(fields.get("usageKnown"))
            and previous_pair != incoming_pair
            and not bool(existing.get("usageEstimated"))
        ):
            raise ModelBudgetError(
                "operator invocation replay conflicts with its first usage",
                code="operator_invocation_replay_conflict",
            )
        updated = _entry(current_metadata, fields)
        working = dict(invocations)
        working[invocation_id] = updated
        if bool(fields.get("usageEstimated")) and _token_sum(working) > int(current_metadata.get("tokenLimit") or 0):
            raise ModelBudgetError(
                "operator discussion token limit reached",
                code="operator_model_token_limit_reached",
            )
        settled_payload = dict(settled_payload)
        _native_replacement(settled_payload, invocation_id, updated)
        settled_payload["operatorModelBudget"] = _dynamic_metadata(current_metadata, working)
        _write_payload(uow, row, settled_payload, status="reserved", now_ms=now_ms)
        return _summary(
            {**row, "settled_json": json.dumps(settled_payload)},
            settled_payload["operatorModelBudget"],
            idempotent=False,
        )

    if bool(fields.get("usageEstimated")) and len(invocations) >= int(current_metadata.get("maxCalls") or 0):
        raise ModelBudgetError(
            "operator discussion call limit reached",
            code="operator_model_call_limit_reached",
        )
    candidate = _entry(current_metadata, fields)
    working = {**invocations, invocation_id: candidate}
    if bool(fields.get("usageEstimated")) and _token_sum(working) > int(current_metadata.get("tokenLimit") or 0):
        raise ModelBudgetError(
            "operator discussion token limit reached",
            code="operator_model_token_limit_reached",
        )
    record_budget_usage_in_uow(
        uow,
        run_id=str(row["run_id"]),
        node_run_id=str(row["node_run_id"]),
        reservation_id=reservation_id,
        invocation_id=invocation_id,
        input_tokens=candidate["inputTokens"] if bool(fields.get("usageKnown")) else 0,
        output_tokens=candidate["outputTokens"] if bool(fields.get("usageKnown")) else 0,
        tool_calls=1,
        usage_estimated=bool(fields.get("usageEstimated")) or not bool(fields.get("usageKnown")),
    )
    fresh_row = _load_row(uow, reservation_id)
    fresh_payload = _json_object(fresh_row.get("settled_json"), "settled_json")
    fresh_metadata = _operator_metadata(fresh_payload, required=False) or current_metadata
    fresh_invocations = _invocation_map(fresh_metadata)
    fresh_invocations[invocation_id] = candidate
    updated_metadata = _dynamic_metadata(fresh_metadata, fresh_invocations)
    fresh_payload["operatorModelBudget"] = updated_metadata
    fresh_payload["source"] = "operator-model-budget"
    _write_payload(uow, fresh_row, fresh_payload, status="reserved", now_ms=now_ms)
    return _summary(
        {**fresh_row, "settled_json": json.dumps(fresh_payload)},
        updated_metadata,
        idempotent=False,
    )


def admit_model_invocation_in_uow(
    uow: Any,
    *,
    reservation: Mapping[str, Any],
    invocation_id: str,
    model_ref: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    usage: Mapping[str, Any] | None = None,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Atomically claim one invocation slot before the provider call."""

    fields = _usage_fields(
        usage=usage,
        model_ref=model_ref,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        usage_known=True,
        usage_estimated=True,
        outcome="unknown",
    )
    result = _record_or_admit_in_uow(
        uow,
        reservation=reservation,
        invocation_id=invocation_id,
        fields=fields,
        now_ms=int(now_ms if now_ms is not None else time.time() * 1000),
    )
    result["admitted"] = True
    return result


def admit_model_invocation(store: WorkflowLedgerStore, **kwargs: Any) -> dict[str, Any]:
    """Store wrapper for the native pre-call admission hook."""

    return store.submit(
        lambda uow: admit_model_invocation_in_uow(uow, **kwargs), force_flush=True
    ).result(timeout=30)


def record_model_invocation_usage_in_uow(
    uow: Any,
    *,
    reservation: Mapping[str, Any],
    invocation_id: str,
    model_ref: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    usage: Mapping[str, Any] | None = None,
    usage_known: bool | None = None,
    usage_estimated: bool = False,
    outcome: str = "succeeded",
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Record one invocation; estimated and unknown usage remains unsettled."""

    fields = _usage_fields(
        usage=usage,
        model_ref=model_ref,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        usage_known=usage_known,
        usage_estimated=usage_estimated,
        outcome=outcome,
    )
    return _record_or_admit_in_uow(
        uow,
        reservation=reservation,
        invocation_id=invocation_id,
        fields=fields,
        now_ms=int(now_ms if now_ms is not None else time.time() * 1000),
    )


def record_model_invocation_usage(
    store: WorkflowLedgerStore, **kwargs: Any
) -> dict[str, Any]:
    """Store wrapper for :func:`record_model_invocation_usage_in_uow`."""

    return store.submit(
        lambda uow: record_model_invocation_usage_in_uow(uow, **kwargs),
        force_flush=True,
    ).result(timeout=30)


def settle_model_budget_in_uow(
    uow: Any,
    *,
    reservation: Mapping[str, Any],
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Settle known currency amounts and retain unresolved reservations."""

    reservation_id, expected_run, expected_node = _reservation_ids(reservation)
    row = _load_row(uow, reservation_id)
    if expected_run and str(row.get("run_id") or "") != expected_run:
        raise ModelBudgetError(
            "operator reservation run binding differs",
            code="operator_model_binding_mismatch",
        )
    if expected_node and str(row.get("node_run_id") or "") != expected_node:
        raise ModelBudgetError(
            "operator reservation NodeRun binding differs",
            code="operator_model_binding_mismatch",
        )
    status = str(row.get("status") or "")
    if status == "settled":
        payload = _json_object(row.get("settled_json"), "settled_json")
        metadata = _operator_metadata(payload)
        assert metadata is not None
        return _summary(row, metadata, idempotent=True)
    if status in _TERMINAL_STATUSES:
        raise ModelBudgetError(
            f"operator reservation is terminal ({status})",
            code="operator_model_budget_terminal",
        )
    reserved_payload = _json_object(row.get("reserved_json"), "reserved_json")
    reserved_metadata = _operator_metadata(reserved_payload)
    assert reserved_metadata is not None
    settled_payload = _json_object(row.get("settled_json"), "settled_json")
    current = _operator_metadata(settled_payload, required=False) or reserved_metadata
    invocations = _invocation_map(current)
    updated = _dynamic_metadata(current, invocations)
    settled_payload["operatorModelBudget"] = updated
    settled_payload["source"] = "operator-model-budget"
    timestamp = int(now_ms if now_ms is not None else time.time() * 1000)
    if updated.get("costStatus") != "settled" or not invocations:
        _write_payload(uow, row, settled_payload, status="reserved", now_ms=timestamp)
        return _summary(
            {**row, "settled_json": json.dumps(settled_payload)},
            updated,
            idempotent=False,
        )
    _write_payload(uow, row, settled_payload, status="settled", now_ms=timestamp)
    return _summary(
        {**row, "status": "settled", "settled_json": json.dumps(settled_payload)},
        updated,
        idempotent=False,
    )


def settle_model_budget(store: WorkflowLedgerStore, **kwargs: Any) -> dict[str, Any]:
    """Store wrapper for :func:`settle_model_budget_in_uow`."""

    return store.submit(
        lambda uow: settle_model_budget_in_uow(uow, **kwargs), force_flush=True
    ).result(timeout=30)


def finish_model_budget_in_uow(uow: Any, *, reservation: Mapping[str, Any],
                               unused_status: str, now_ms: int) -> str:
    """Release unused capacity; preserve all admitted calls awaiting usage."""
    result = settle_model_budget_in_uow(uow, reservation=reservation, now_ms=now_ms)
    if result["callsUsed"] == 0 and result["status"] == "reserved":
        uow.repository.update_budget_receipt(result["receiptId"], status=unused_status,
            now_ms=now_ms)
        return unused_status
    return result["status"]


__all__ = [
    "ModelBudgetError",
    "OperatorBudgetSpec",
    "OPERATOR_MODEL_BUDGET_KIND",
    "OPERATOR_MODEL_BUDGET_SCHEMA_VERSION",
    "admit_model_invocation",
    "admit_model_invocation_in_uow",
    "build_operator_budget_policy",
    "calculate_max_reserved_cost",
    "calculate_model_cost",
    "record_model_invocation_usage",
    "record_model_invocation_usage_in_uow",
    "reserve_model_budget",
    "reserve_model_budget_in_uow",
    "settle_model_budget",
    "settle_model_budget_in_uow",
]
