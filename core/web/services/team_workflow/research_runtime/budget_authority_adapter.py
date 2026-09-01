"""Ledger-backed budget authority adapter (T5.1-5).

Reuses the frozen Run budgetPolicy and budget_receipts table as the single
budget fact source for the formal Workflow Ledger runtime. Does not create a
second budget store.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from typing import Any

from core.research.workflow.contracts import PendingAction
from core.research.workflow.ledger import WorkflowLedgerStore

from .budget_contract import (
    DEFAULT_FORMAL_TOKEN_BUDGET,
    DEFAULT_MAX_RETRIES,
    DEFAULT_STAGE_TOKENS,
    DEFAULT_TOOL_CALLS,
    DEFAULT_WALL_CLOCK_SECONDS,
)
from .ids import new_id

# Per-Agent-node-attempt reservation fallback (the turn-budget scale), used
# only when neither a task budgetRequest nor a frozen stage budget exists.
DEFAULT_AGENT_NODE_RESERVE_TOKENS = DEFAULT_FORMAL_TOKEN_BUDGET

# ``settled_json`` is the existing budget-receipt projection column.  Keep the
# invocation index deliberately bounded: an exhausted index fails closed
# instead of evicting an id and risking a duplicate charge after a retry.
MAX_RECORDED_INVOCATIONS = 256

_STAGE_BY_NODE: dict[str, str] = {
    "problem_understanding": "knowledge_collection",
    "source_finding": "knowledge_collection",
    "source_extraction": "knowledge_collection",
    "evidence_relations": "knowledge_collection",
    "knowledge_ingestion": "knowledge_collection",
    "knowledge_handoff": "knowledge_collection",
    "hypothesis_design": "experiment_design",
    "protocol_design": "experiment_design",
    "protocol_review": "experiment_design",
    "protocol_freeze": "experiment_design",
    "smoke_gate": "experiment_design",
    "controlled_run": "execution_iteration",
    "result_evaluation": "execution_iteration",
    "iteration_decision": "execution_iteration",
    "version_governance": "execution_iteration",
    "candidate_promotion": "execution_iteration",
    "result_package": "execution_iteration",
}


class BudgetAuthorityError(RuntimeError):
    def __init__(self, message: str, *, code: str = "budget_error") -> None:
        super().__init__(message)
        self.code = code


def stage_for_node(node_id: str) -> str:
    return _STAGE_BY_NODE.get(node_id, "execution_iteration")


def _positive_policy_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return int(value)


def _policy_limits(
    snapshot: dict[str, Any],
    stage_id: str,
    *,
    operator_limits: Mapping[str, Any] | None = None,
) -> dict[str, int]:
    policy = snapshot.get("budgetPolicy") or {}
    stage_budgets = policy.get("stageBudgets") or {}
    stage = stage_budgets.get(stage_id) if isinstance(stage_budgets, dict) else {}
    if not isinstance(stage, dict):
        stage = {}
    tokens = int(stage.get("tokens") or policy.get("tokens") or DEFAULT_STAGE_TOKENS)
    tool_calls = int(
        stage.get("toolCalls") or policy.get("toolCalls") or DEFAULT_TOOL_CALLS
    )
    seconds = int(
        stage.get("wallClockSeconds")
        or policy.get("wallClockSeconds")
        or DEFAULT_WALL_CLOCK_SECONDS
    )
    # Retry vocabulary is dual-read: run snapshots historically carry
    # ``autoRetries`` while newer surfaces (and extend_budget) write
    # ``maxRetries``.  Reading only one key silently dropped the other and
    # fell back to the default (T3).
    retries = int(
        policy.get("maxRetries") or policy.get("autoRetries") or DEFAULT_MAX_RETRIES
    )

    # ``safety_limits_json`` is the operator-owned, auditable extension delta
    # for an immutable run snapshot.  It may only widen capacity; it never
    # rewrites or lowers the frozen launch contract.
    override = operator_limits if isinstance(operator_limits, Mapping) else {}
    stage_tokens = override.get("stageTokens")
    stage_token_override = (
        _positive_policy_int(stage_tokens.get(stage_id))
        if isinstance(stage_tokens, Mapping)
        else None
    )
    tool_override = _positive_policy_int(override.get("toolCalls"))
    seconds_override = _positive_policy_int(override.get("wallClockSeconds"))
    retries_override = _positive_policy_int(override.get("maxRetries"))
    if retries_override is None:
        retries_override = _positive_policy_int(override.get("autoRetries"))
    if stage_token_override is not None:
        tokens = max(tokens, stage_token_override)
    if tool_override is not None:
        tool_calls = max(tool_calls, tool_override)
    if seconds_override is not None:
        seconds = max(seconds, seconds_override)
    if retries_override is not None:
        retries = max(retries, retries_override)
    return {
        "tokens": tokens,
        "toolCalls": tool_calls,
        "seconds": seconds,
        "retries": retries,
    }


def _positive_contract_tokens(value: object) -> int | None:
    return _positive_policy_int(value)


def stage_budget_tokens(snapshot: Mapping[str, Any] | None, node_id: str) -> int | None:
    """Explicit frozen budget for the node's stage from the run contract.

    Priority: ``budgetPolicy.stageBudgets[stage].tokens`` then the run-level
    ``budgetPolicy.tokens``.  Returns ``None`` when the snapshot carries no
    budget contract at all; callers then fall back to
    ``DEFAULT_AGENT_NODE_RESERVE_TOKENS`` instead of a flat per-node constant.
    """

    policy = (
        snapshot.get("budgetPolicy")
        if isinstance(snapshot, Mapping)
        else None
    )
    if not isinstance(policy, Mapping):
        return None
    stage_budgets = policy.get("stageBudgets")
    stage = (
        stage_budgets.get(stage_for_node(node_id))
        if isinstance(stage_budgets, Mapping)
        else None
    )
    if isinstance(stage, Mapping):
        tokens = _positive_contract_tokens(stage.get("tokens"))
        if tokens is not None:
            return tokens
    return _positive_contract_tokens(policy.get("tokens"))


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


def _identity(value: object, label: str) -> str:
    identity = str(value or "").strip()
    if not identity:
        raise BudgetAuthorityError(
            f"{label} is required", code="budget_binding_missing"
        )
    return identity


def _counter(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise BudgetAuthorityError(
            f"{label} must be a non-negative integer",
            code="budget_usage_invalid",
        )
    return int(value)


def _payload(raw: object, *, label: str) -> dict[str, Any]:
    if raw in (None, ""):
        return {}
    try:
        decoded = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise BudgetAuthorityError(
            f"{label} is not valid JSON", code="budget_receipt_corrupt"
        ) from exc
    if not isinstance(decoded, dict):
        raise BudgetAuthorityError(
            f"{label} must be a JSON object", code="budget_receipt_corrupt"
        )
    return decoded


def _optional_counter(payload: Mapping[str, Any], *keys: str) -> tuple[int, bool]:
    for key in keys:
        if key in payload and payload[key] is not None:
            return _counter(payload[key], key), True
    return 0, False


def _reserved_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    nested = payload.get("reserved")
    return nested if isinstance(nested, Mapping) else payload


def _reserved_tokens(payload: Mapping[str, Any]) -> int:
    inner = _reserved_payload(payload)
    value, present = _optional_counter(inner, "estimatedTokens", "tokens")
    return value if present else 0


def _stage_limit(payload: Mapping[str, Any], *, fallback: int) -> int:
    limits = payload.get("limits")
    if isinstance(limits, Mapping):
        value, present = _optional_counter(limits, "tokens", "stageLimit")
        if present:
            return value
    value, present = _optional_counter(payload, "stageLimit", "stage_limit")
    return value if present else fallback


def _usage_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    usage = payload.get("usage")
    return usage if isinstance(usage, Mapping) else {}


def _usage_tokens(payload: Mapping[str, Any]) -> int:
    usage = _usage_payload(payload)
    value, present = _optional_counter(usage, "tokens", "totalTokens", "total_tokens")
    if present:
        return value
    input_tokens, _ = _optional_counter(usage, "inputTokens", "input_tokens", "promptTokens")
    output_tokens, _ = _optional_counter(
        usage, "outputTokens", "output_tokens", "completionTokens"
    )
    if input_tokens or output_tokens:
        return input_tokens + output_tokens
    invocations = payload.get("invocations")
    if isinstance(invocations, Mapping):
        return sum(
            _invocation_tokens(item)
            for item in invocations.values()
            if isinstance(item, Mapping)
        )
    return 0


def _invocation_tokens(invocation: Mapping[str, Any]) -> int:
    value, present = _optional_counter(
        invocation, "tokens", "totalTokens", "total_tokens"
    )
    if present:
        return value
    input_tokens, _ = _optional_counter(
        invocation, "inputTokens", "input_tokens", "promptTokens"
    )
    output_tokens, _ = _optional_counter(
        invocation, "outputTokens", "output_tokens", "completionTokens"
    )
    return input_tokens + output_tokens


def _row_mapping(row: tuple[Any, ...]) -> dict[str, Any]:
    return dict(zip(_BUDGET_RECEIPT_COLUMNS, row, strict=True))


def _assert_row_binding(
    row: Mapping[str, Any], *, run_id: str, node_run_id: str, reservation_id: str
) -> None:
    if (
        str(row.get("run_id") or "") != run_id
        or str(row.get("node_run_id") or "") != node_run_id
        or str(row.get("reservation_id") or "") != reservation_id
    ):
        raise BudgetAuthorityError(
            "budget receipt three-way binding mismatch",
            code="budget_binding_mismatch",
        )


def _window_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    reserved = _payload(row.get("reserved_json"), label="reserved_json")
    settled = _payload(row.get("settled_json"), label="settled_json")
    reserved_tokens = _reserved_tokens(reserved)
    used_tokens = _usage_tokens(settled)
    stage_limit = _stage_limit(
        reserved,
        fallback=max(DEFAULT_STAGE_TOKENS, reserved_tokens),
    )
    return {
        "runId": str(row.get("run_id") or ""),
        "nodeRunId": str(row.get("node_run_id") or ""),
        "reservationId": str(row.get("reservation_id") or ""),
        "stageId": str(row.get("stage_id") or ""),
        "reserved": reserved_tokens,
        "used": used_tokens,
        "remaining": max(0, reserved_tokens - used_tokens),
        "stageLimit": stage_limit,
        "status": str(row.get("status") or ""),
    }


def _reservation_result(
    row: Mapping[str, Any],
    *,
    action: PendingAction,
    fallback_limits: Mapping[str, int],
    idempotent: bool,
) -> dict[str, Any]:
    reserved_payload = _payload(row.get("reserved_json"), label="reserved_json")
    inner = _reserved_payload(reserved_payload)
    limits = reserved_payload.get("limits")
    if not isinstance(limits, Mapping):
        limits = dict(fallback_limits)
    else:
        limits = dict(limits)
    return {
        "reservationId": str(row.get("reservation_id") or ""),
        "receiptId": str(row.get("receipt_id") or ""),
        "actionId": action.action_id,
        "nodeRunId": str(row.get("node_run_id") or ""),
        "stageId": str(row.get("stage_id") or ""),
        "policyHash": str(row.get("policy_hash") or action.budget_policy_hash or ""),
        "reserved": dict(inner),
        "status": str(row.get("status") or "reserved"),
        "limits": limits,
        "idempotent": idempotent,
    }


def read_node_budget_window(
    store: WorkflowLedgerStore,
    run_id: str,
    node_run_id: str,
    reservation_id: str,
) -> dict[str, Any]:
    """Read one immutable budget snapshot from the Ledger receipt.

    The function intentionally performs no write and never falls back to a
    legacy WorkflowRunStore or run JSON.  ``reserved`` is this node's token
    reservation, ``used`` is the accumulated input+output usage, and
    ``stageLimit`` is the frozen stage admission limit.
    """
    run_id = _identity(run_id, "run_id")
    node_run_id = _identity(node_run_id, "node_run_id")
    reservation_id = _identity(reservation_id, "reservation_id")
    row = store.read(
        lambda repo: repo.execute(
            "SELECT receipt_id, run_id, node_run_id, reservation_id, stage_id, "
            "policy_hash, reserved_json, settled_json, status, created_at_ms, "
            "updated_at_ms FROM budget_receipts WHERE reservation_id = ?",
            (reservation_id,),
        ).fetchone()
    )
    if row is None:
        raise BudgetAuthorityError(
            f"budget receipt missing for {reservation_id}",
            code="budget_receipt_missing",
        )
    mapped = _row_mapping(row)
    _assert_row_binding(
        mapped,
        run_id=run_id,
        node_run_id=node_run_id,
        reservation_id=reservation_id,
    )
    return _window_from_row(mapped)


def _stage_admitted_tokens(row: Mapping[str, Any]) -> int:
    status = str(row.get("status") or "")
    if status in {"released", "voided", "failed"}:
        return 0
    reserved = _payload(row.get("reserved_json"), label="reserved_json")
    reserved_tokens = _reserved_tokens(reserved)
    if status == "reserved":
        # A live reservation occupies its whole admission estimate until it
        # settles, even if some per-invocation usage has already been written.
        return reserved_tokens
    settled = _payload(row.get("settled_json"), label="settled_json")
    usage_tokens = _usage_tokens(settled)
    usage = _usage_payload(settled)
    has_usage_observation = bool(usage) or bool(settled.get("invocations"))
    # Old receipts may have been marked settled without a usage projection;
    # retain conservative admission rather than silently freeing capacity.
    return usage_tokens if has_usage_observation else reserved_tokens


def reserve_budget_authority(
    store: WorkflowLedgerStore,
    *,
    action: PendingAction,
    estimate_tokens: int,
    input_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    snapshot = dict(input_snapshot or {})
    stage_id = stage_for_node(action.node_id)
    reservation_id = f"reservation-{action.node_run_id}"
    estimate = max(0, int(estimate_tokens))

    now_ms = int(time.time() * 1000)
    receipt_id = new_id("br")

    def mutate(uow):
        run = uow.repository.get_run(action.run_id)
        if run is None:
            raise BudgetAuthorityError(
                f"workflow run not found: {action.run_id}",
                code="budget_binding_missing",
            )
        operator_limits = _payload(
            run.safety_limits_json,
            label="workflow_runs.safety_limits_json",
        )
        limits = _policy_limits(
            snapshot,
            stage_id,
            operator_limits=operator_limits,
        )
        # Keep the idempotency lookup, stage admission check, and INSERT in
        # this one writer transaction.  A read-before-submit check permits two
        # concurrent callers to over-reserve the same stage.
        existing_row = uow.repository.execute(
            "SELECT receipt_id, run_id, node_run_id, reservation_id, stage_id, "
            "policy_hash, reserved_json, settled_json, status, created_at_ms, "
            "updated_at_ms FROM budget_receipts WHERE reservation_id = ?",
            (reservation_id,),
        ).fetchone()
        if existing_row is not None:
            existing = _row_mapping(existing_row)
            _assert_row_binding(
                existing,
                run_id=action.run_id,
                node_run_id=action.node_run_id,
                reservation_id=reservation_id,
            )
            if str(existing.get("stage_id") or "") != stage_id:
                raise BudgetAuthorityError(
                    "budget receipt stage binding mismatch",
                    code="budget_binding_mismatch",
                )
            # Existing reserved/settled receipt for this reservation wins,
            # preserving the original estimate and its frozen limits.
            return _reservation_result(
                existing,
                action=action,
                fallback_limits=limits,
                idempotent=True,
            )

        stage_rows = uow.repository.execute(
            "SELECT receipt_id, run_id, node_run_id, reservation_id, stage_id, "
            "policy_hash, reserved_json, settled_json, status, created_at_ms, "
            "updated_at_ms FROM budget_receipts "
            "WHERE run_id = ? AND stage_id = ?",
            (action.run_id, stage_id),
        ).fetchall()
        admitted = sum(
            _stage_admitted_tokens(_row_mapping(row)) for row in stage_rows
        )
        # Per-run stage cumulative ceiling semantics (chosen over a pure
        # concurrency guard): live reservations occupy their full estimate and
        # settled attempts occupy their real usage, so a finished attempt
        # releases its estimate weight (K8s ResourceQuota "completed pods
        # release" semantics) and one real node can never permanently lock the
        # stage. Invariant: the stage limit must stay >= one attempt's
        # legitimate consumption x (1 + autoRetries) — the 2M default versus a
        # real ~300K node keeps that true, while the old 250K default (below
        # one real attempt) violated it.
        stage_remaining = max(0, int(limits["tokens"]) - admitted)
        if stage_remaining <= 0:
            raise BudgetAuthorityError(
                f"stage token limit exceeded for {stage_id}: "
                f"consumed={admitted} estimate={estimate} limit={limits['tokens']}",
                code="budget_safety_limit_reached",
            )
        # The per-attempt reservation is the contract estimate capped by the
        # stage's remaining capacity. A serial stage must keep later attempts
        # and retries admissible after earlier attempts settle their real
        # usage (a settled real node consumes ~300K), while live+settled
        # admission still never exceeds the frozen stage limit. A stage with
        # no remaining capacity is rejected fail-closed above. The estimate is
        # only an admission hint; settled usage remains the sole authority.
        effective_estimate = min(estimate, stage_remaining)
        reserved_payload = {
            "estimatedTokens": effective_estimate,
            "tokens": effective_estimate,
            "toolCalls": 1,
            "seconds": 60,
            "retries": 0,
        }

        uow.repository.insert_budget_receipt(
            receipt_id=receipt_id,
            run_id=action.run_id,
            node_run_id=action.node_run_id,
            reservation_id=reservation_id,
            stage_id=stage_id,
            policy_hash=action.budget_policy_hash or "",
            reserved_json=json.dumps(
                {"reserved": reserved_payload, "limits": limits},
                ensure_ascii=False,
            ),
            created_at_ms=now_ms,
        )
        inserted = {
            "receipt_id": receipt_id,
            "run_id": action.run_id,
            "node_run_id": action.node_run_id,
            "reservation_id": reservation_id,
            "stage_id": stage_id,
            "policy_hash": action.budget_policy_hash or "",
            "reserved_json": json.dumps(
                {"reserved": reserved_payload, "limits": limits},
                ensure_ascii=False,
            ),
            "settled_json": None,
            "status": "reserved",
            "created_at_ms": now_ms,
            "updated_at_ms": now_ms,
        }
        return _reservation_result(
            inserted,
            action=action,
            fallback_limits=limits,
            idempotent=False,
        )

    return store.submit(mutate, force_flush=True).result(timeout=30)


def _usage_estimated(payload: Mapping[str, Any]) -> bool:
    for key in ("usageEstimated", "usage_estimated"):
        if key not in payload or payload[key] is None:
            continue
        if not isinstance(payload[key], bool):
            raise BudgetAuthorityError(
                f"{key} must be boolean", code="budget_usage_invalid"
            )
        return bool(payload[key])
    return False


def _validated_usage(usage: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(usage, Mapping):
        raise BudgetAuthorityError(
            "usage must be a JSON object", code="budget_usage_invalid"
        )
    result = dict(usage)
    # Validate known token counters while retaining provider-specific metadata
    # (tool calls, wall-clock seconds, and so on) for the final settlement.
    for key in (
        "tokens",
        "totalTokens",
        "total_tokens",
        "inputTokens",
        "input_tokens",
        "promptTokens",
        "outputTokens",
        "output_tokens",
        "completionTokens",
        "reasoningTokens",
        "reasoning_tokens",
        "cachedInputTokens",
        "cached_input_tokens",
        "uncachedInputTokens",
        "uncached_input_tokens",
        "toolCalls",
        "tool_calls",
        "wallClockSeconds",
        "wall_clock_seconds",
    ):
        if key in result and result[key] is not None:
            _counter(result[key], key)
    estimated = _usage_estimated(result)
    if "usageEstimated" not in result and "usage_estimated" in result:
        result["usageEstimated"] = estimated
    return result


def _merge_usage_projection(
    current_payload: Mapping[str, Any],
    incoming_usage: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    current_usage_raw = current_payload.get("usage")
    current_usage = (
        dict(current_usage_raw) if isinstance(current_usage_raw, Mapping) else {}
    )
    invocations_raw = current_payload.get("invocations")
    if invocations_raw is None:
        invocations: dict[str, dict[str, Any]] = {}
    elif isinstance(invocations_raw, Mapping):
        invocations = {
            str(key): dict(value)
            for key, value in invocations_raw.items()
            if isinstance(value, Mapping)
        }
        if len(invocations) != len(invocations_raw):
            raise BudgetAuthorityError(
                "budget invocation projection is corrupt",
                code="budget_receipt_corrupt",
            )
    else:
        raise BudgetAuthorityError(
            "budget invocation projection is corrupt",
            code="budget_receipt_corrupt",
        )

    prior_tokens = _usage_tokens({"usage": current_usage, "invocations": invocations})
    prior_input, _ = _optional_counter(
        current_usage, "inputTokens", "input_tokens", "promptTokens"
    )
    prior_output, _ = _optional_counter(
        current_usage, "outputTokens", "output_tokens", "completionTokens"
    )
    prior_reasoning, _ = _optional_counter(
        current_usage, "reasoningTokens", "reasoning_tokens"
    )
    incoming = dict(incoming_usage)
    incoming_tokens = _usage_tokens({"usage": incoming})
    incoming_input, incoming_input_present = _optional_counter(
        incoming, "inputTokens", "input_tokens", "promptTokens"
    )
    incoming_output, incoming_output_present = _optional_counter(
        incoming, "outputTokens", "output_tokens", "completionTokens"
    )
    incoming_reasoning, _ = _optional_counter(
        incoming, "reasoningTokens", "reasoning_tokens"
    )
    supplemental_counters = (
        ("cachedInputTokens", ("cachedInputTokens", "cached_input_tokens")),
        ("uncachedInputTokens", ("uncachedInputTokens", "uncached_input_tokens")),
        ("toolCalls", ("toolCalls", "tool_calls")),
        ("wallClockSeconds", ("wallClockSeconds", "wall_clock_seconds")),
    )

    has_prior_actual = bool(invocations) or any(
        key in current_usage
        for key in (
            "tokens",
            "totalTokens",
            "total_tokens",
            "inputTokens",
            "input_tokens",
            "outputTokens",
            "output_tokens",
        )
    )
    if not has_prior_actual:
        merged_usage = incoming
    else:
        # Per-invocation provider usage is the authoritative cumulative value.
        # A final estimate must never replace it.  A non-estimated final usage
        # may fill a missing provider observation, so merge it conservatively.
        incoming_is_estimated = _usage_estimated(incoming)
        merged_usage = dict(incoming)
        if incoming_is_estimated:
            merged_input = prior_input
            merged_output = prior_output
            merged_reasoning = prior_reasoning
            merged_tokens = prior_tokens
        else:
            merged_input = max(prior_input, incoming_input)
            merged_output = max(prior_output, incoming_output)
            merged_reasoning = max(prior_reasoning, incoming_reasoning)
            merged_tokens = max(prior_tokens, incoming_tokens)
        if "inputTokens" in current_usage or incoming_input_present:
            merged_usage["inputTokens"] = merged_input
        if "outputTokens" in current_usage or incoming_output_present:
            merged_usage["outputTokens"] = merged_output
        if "reasoningTokens" in current_usage or "reasoning_tokens" in current_usage or incoming_reasoning:
            merged_usage["reasoningTokens"] = merged_reasoning
        # ``tokens`` is billable input + output.  Reasoning is a separately
        # observed completion detail and is intentionally never added here.
        merged_usage["tokens"] = merged_tokens
        if "usageEstimated" in current_usage:
            merged_usage["usageEstimated"] = bool(current_usage["usageEstimated"])

    for canonical_key, aliases in supplemental_counters:
        prior_value, prior_present = _optional_counter(current_usage, *aliases)
        incoming_value, incoming_present = _optional_counter(incoming, *aliases)
        if incoming_present:
            merged_usage[canonical_key] = max(prior_value, incoming_value)
        elif prior_present:
            merged_usage[canonical_key] = prior_value

    payload = dict(current_payload)
    payload["usage"] = merged_usage
    payload["invocations"] = invocations
    payload.setdefault("source", "budget-authority-adapter")
    return payload, invocations


def _result_with_projection(
    row: Mapping[str, Any],
    payload: Mapping[str, Any],
    *,
    invocation_id: str,
    idempotent: bool,
) -> dict[str, Any]:
    synthetic = dict(row)
    synthetic["settled_json"] = json.dumps(payload, ensure_ascii=False)
    result = _window_from_row(synthetic)
    result.update(
        {
            "invocationId": invocation_id,
            "idempotent": idempotent,
            "usage": dict(_usage_payload(payload)),
        }
    )
    return result


def record_budget_usage_in_uow(
    uow: Any,
    *,
    run_id: str,
    node_run_id: str,
    reservation_id: str,
    invocation_id: str,
    input_tokens: int = 0,
    cached_input_tokens: int = 0,
    uncached_input_tokens: int = 0,
    output_tokens: int = 0,
    reasoning_tokens: int = 0,
    tool_calls: int = 0,
    wall_clock_seconds: int = 0,
    usage_estimated: bool = False,
) -> dict[str, Any]:
    """Append one provider invocation inside an existing Ledger transaction.

    ``invocation_id`` is the idempotency key.  The projection is stored in the
    receipt's existing ``settled_json`` column, keeping the Workflow Ledger as
    the sole budget authority and keeping conversation state untouched.  The
    caller owns commit/rollback so receipt delivery intent and usage can share
    one transaction.
    """
    run_id = _identity(run_id, "run_id")
    node_run_id = _identity(node_run_id, "node_run_id")
    reservation_id = _identity(reservation_id, "reservation_id")
    invocation_id = _identity(invocation_id, "invocation_id")
    input_count = _counter(input_tokens, "input_tokens")
    cached_input_count = _counter(cached_input_tokens, "cached_input_tokens")
    uncached_input_count = _counter(uncached_input_tokens, "uncached_input_tokens")
    output_count = _counter(output_tokens, "output_tokens")
    reasoning_count = _counter(reasoning_tokens, "reasoning_tokens")
    tool_call_count = _counter(tool_calls, "tool_calls")
    wall_clock_count = _counter(wall_clock_seconds, "wall_clock_seconds")
    if cached_input_count + uncached_input_count > input_count:
        raise BudgetAuthorityError(
            "cached and uncached input tokens exceed input_tokens",
            code="budget_usage_invalid",
        )
    if not isinstance(usage_estimated, bool):
        raise BudgetAuthorityError(
            "usage_estimated must be boolean", code="budget_usage_invalid"
        )

    invocation_usage = {
        "inputTokens": input_count,
        "cachedInputTokens": cached_input_count,
        "uncachedInputTokens": uncached_input_count,
        "outputTokens": output_count,
        "reasoningTokens": reasoning_count,
        "toolCalls": tool_call_count,
        "wallClockSeconds": wall_clock_count,
        # Provider reasoning tokens are a completion detail and are already
        # included in outputTokens for the relay response.
        "tokens": input_count + output_count,
        "usageEstimated": usage_estimated,
    }

    row = uow.repository.execute(
        "SELECT receipt_id, run_id, node_run_id, reservation_id, stage_id, "
        "policy_hash, reserved_json, settled_json, status, created_at_ms, "
        "updated_at_ms FROM budget_receipts WHERE reservation_id = ?",
        (reservation_id,),
    ).fetchone()
    if row is None:
        raise BudgetAuthorityError(
            f"budget receipt missing for {reservation_id}",
            code="budget_receipt_missing",
        )
    mapped = _row_mapping(row)
    _assert_row_binding(
        mapped,
        run_id=run_id,
        node_run_id=node_run_id,
        reservation_id=reservation_id,
    )
    current_payload = _payload(mapped.get("settled_json"), label="settled_json")
    invocations_raw = current_payload.get("invocations")
    if invocations_raw is None:
        existing_invocations: Mapping[str, Any] = {}
    elif isinstance(invocations_raw, Mapping):
        existing_invocations = invocations_raw
    else:
        raise BudgetAuthorityError(
            "budget invocation projection is corrupt",
            code="budget_receipt_corrupt",
        )
    if invocation_id in existing_invocations:
        return _result_with_projection(
            mapped,
            current_payload,
            invocation_id=invocation_id,
            idempotent=True,
        )
    if str(mapped.get("status") or "") not in {"reserved", "consumed"}:
        raise BudgetAuthorityError(
            f"budget receipt {reservation_id} is terminal "
            f"({mapped.get('status')}); cannot record usage",
            code="budget_usage_terminal",
        )
    if len(existing_invocations) >= MAX_RECORDED_INVOCATIONS:
        raise BudgetAuthorityError(
            "budget invocation projection capacity exhausted",
            code="budget_usage_projection_full",
        )

    invocation_map = dict(existing_invocations)
    invocation_map[invocation_id] = invocation_usage
    working = dict(current_payload)
    working["invocations"] = invocation_map
    prior_usage_raw = working.get("usage")
    prior_usage = (
        dict(prior_usage_raw) if isinstance(prior_usage_raw, Mapping) else {}
    )
    prior_tokens = _usage_tokens(
        {"usage": prior_usage, "invocations": existing_invocations}
    )
    prior_input, _ = _optional_counter(
        prior_usage, "inputTokens", "input_tokens", "promptTokens"
    )
    prior_output, _ = _optional_counter(
        prior_usage, "outputTokens", "output_tokens", "completionTokens"
    )
    prior_reasoning, _ = _optional_counter(
        prior_usage, "reasoningTokens", "reasoning_tokens"
    )
    prior_cached, _ = _optional_counter(
        prior_usage, "cachedInputTokens", "cached_input_tokens"
    )
    prior_uncached, _ = _optional_counter(
        prior_usage, "uncachedInputTokens", "uncached_input_tokens"
    )
    prior_tool_calls, _ = _optional_counter(prior_usage, "toolCalls", "tool_calls")
    prior_wall_clock, _ = _optional_counter(
        prior_usage, "wallClockSeconds", "wall_clock_seconds"
    )
    aggregate = dict(prior_usage)
    aggregate.update(
        {
            "inputTokens": prior_input + input_count,
            "cachedInputTokens": prior_cached + cached_input_count,
            "uncachedInputTokens": prior_uncached + uncached_input_count,
            "outputTokens": prior_output + output_count,
            "reasoningTokens": prior_reasoning + reasoning_count,
            "toolCalls": prior_tool_calls + tool_call_count,
            "wallClockSeconds": prior_wall_clock + wall_clock_count,
            "tokens": prior_tokens + input_count + output_count,
            "usageEstimated": _usage_estimated(prior_usage) or usage_estimated,
        }
    )
    working["usage"] = aggregate
    working["source"] = "budget-authority-adapter"
    updated_json = json.dumps(working, ensure_ascii=False)
    uow.repository.update_budget_receipt(
        str(mapped["receipt_id"]),
        status=str(mapped.get("status") or "reserved"),
        now_ms=int(time.time() * 1000),
        settled_json=updated_json,
    )
    mapped["settled_json"] = updated_json
    return _result_with_projection(
        mapped,
        working,
        invocation_id=invocation_id,
        idempotent=False,
    )


def record_budget_usage(
    store: WorkflowLedgerStore,
    **kwargs: Any,
) -> dict[str, Any]:
    """Atomically append one provider invocation to a Ledger receipt."""

    return store.submit(
        lambda uow: record_budget_usage_in_uow(uow, **kwargs),
        force_flush=True,
    ).result(timeout=30)


def settle_budget_authority_in_uow(
    uow: Any,
    *,
    reservation: dict[str, Any],
    usage: dict[str, Any],
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Settle inside an existing Ledger transaction without losing usage."""

    reservation_id = _identity(
        reservation.get("reservationId"), "reservation_id"
    )
    expected_run_id = str(
        reservation.get("runId") or reservation.get("run_id") or ""
    ).strip()
    expected_node_run_id = str(
        reservation.get("nodeRunId") or reservation.get("node_run_id") or ""
    ).strip()
    incoming_usage = _validated_usage(usage)
    resolved_now_ms = int(now_ms if now_ms is not None else time.time() * 1000)

    row = uow.repository.execute(
        "SELECT receipt_id, run_id, node_run_id, reservation_id, stage_id, "
        "policy_hash, reserved_json, settled_json, status, created_at_ms, "
        "updated_at_ms FROM budget_receipts WHERE reservation_id = ?",
        (reservation_id,),
    ).fetchone()
    if row is None:
        raise BudgetAuthorityError(
            f"budget receipt missing for {reservation_id}",
            code="budget_settle_missing",
        )
    mapped = _row_mapping(row)
    if expected_run_id and str(mapped.get("run_id") or "") != expected_run_id:
        raise BudgetAuthorityError(
            "budget receipt three-way binding mismatch",
            code="budget_binding_mismatch",
        )
    if expected_node_run_id and str(mapped.get("node_run_id") or "") != expected_node_run_id:
        raise BudgetAuthorityError(
            "budget receipt three-way binding mismatch",
            code="budget_binding_mismatch",
        )
    current = str(mapped.get("status") or "")
    current_payload = _payload(
        mapped.get("settled_json"), label="settled_json"
    )
    if current == "settled":
        # Settlement is idempotent; never replace a committed cumulative
        # usage projection with a later estimate.
        return {
            **_window_from_row(mapped),
            "receiptId": str(mapped.get("receipt_id") or ""),
            "status": "settled",
            "idempotent": True,
            "usage": dict(_usage_payload(current_payload)),
        }
    if current in {"released", "voided", "failed"}:
        raise BudgetAuthorityError(
            f"budget receipt {reservation_id} is terminal ({current}); cannot settle",
            code="budget_settle_terminal",
        )

    merged_payload, _ = _merge_usage_projection(
        current_payload,
        incoming_usage,
    )
    settled_json = json.dumps(merged_payload, ensure_ascii=False)
    uow.repository.update_budget_receipt(
        str(mapped["receipt_id"]),
        status="settled",
        now_ms=resolved_now_ms,
        settled_json=settled_json,
    )
    mapped["status"] = "settled"
    mapped["settled_json"] = settled_json
    return {
        **_window_from_row(mapped),
        "receiptId": str(mapped.get("receipt_id") or ""),
        "status": "settled",
        "idempotent": False,
        "usage": dict(_usage_payload(merged_payload)),
    }


def settle_budget_authority(
    store: WorkflowLedgerStore,
    *,
    reservation: dict[str, Any],
    usage: dict[str, Any],
) -> dict[str, Any]:
    """Settle a reserved budget while retaining provider usage observations."""

    return store.submit(
        lambda uow: settle_budget_authority_in_uow(
            uow,
            reservation=reservation,
            usage=usage,
        ),
        force_flush=True,
    ).result(timeout=30)


_TERMINAL_BUDGET_STATUSES = frozenset(
    {"settled", "released", "failed", "voided"}
)


def finalize_cancelled_run_budget_receipts(
    store: WorkflowLedgerStore,
    run_id: str,
    *,
    reason: str = "run_cancelled",
) -> dict[str, int]:
    """Terminalize every live budget receipt owned by a cancelled run.

    A provider invocation may finish while ``cancel_run`` is stopping its chat
    turn.  Such a receipt already contains the authoritative invocation usage
    and must be settled, not released.  Reservations with no observed usage
    are intentionally released.  The whole run is handled in one Ledger
    transaction so a cancellation cleanup cannot acknowledge a partial budget
    terminalization.
    """
    normalized_run_id = _identity(run_id, "run_id")
    normalized_reason = str(reason or "run_cancelled").strip() or "run_cancelled"
    now_ms = int(time.time() * 1000)

    def mutate(uow):
        run = uow.repository.get_run(normalized_run_id)
        if run is None:
            raise BudgetAuthorityError(
                f"workflow run missing for {normalized_run_id}",
                code="budget_run_missing",
            )
        if str(run.status or "") != "cancelled":
            raise BudgetAuthorityError(
                f"workflow run {normalized_run_id} is not cancelled",
                code="budget_cancel_state_mismatch",
            )

        counts = {"settled": 0, "released": 0}
        rows = uow.repository.list_budget_receipts_for_run(normalized_run_id)
        for row in rows:
            mapped = _row_mapping(row)
            if str(mapped.get("status") or "") in _TERMINAL_BUDGET_STATUSES:
                continue
            payload = _payload(mapped.get("settled_json"), label="settled_json")
            usage = payload.get("usage")
            invocations = payload.get("invocations")
            if usage is not None and not isinstance(usage, Mapping):
                raise BudgetAuthorityError(
                    "budget usage projection is corrupt",
                    code="budget_receipt_corrupt",
                )
            if invocations is not None and (
                not isinstance(invocations, Mapping)
                or any(not isinstance(item, Mapping) for item in invocations.values())
            ):
                raise BudgetAuthorityError(
                    "budget invocation projection is corrupt",
                    code="budget_receipt_corrupt",
                )
            # Validate every known counter before choosing the terminal state.
            _usage_tokens(payload)
            terminal_status = (
                "settled" if bool(usage) or bool(invocations) else "released"
            )
            payload.update(
                {
                    "reason": normalized_reason,
                    "source": "budget-authority-adapter",
                    "terminal": terminal_status,
                }
            )
            uow.repository.update_budget_receipt(
                str(mapped["receipt_id"]),
                status=terminal_status,
                now_ms=now_ms,
                settled_json=json.dumps(payload, ensure_ascii=False),
            )
            counts[terminal_status] += 1
        return counts

    return store.submit(mutate, force_flush=True).result(timeout=30)


def release_budget_reservation(
    store: WorkflowLedgerStore,
    reservation: dict[str, Any],
    *,
    reason: str = "unused_release",
) -> None:
    """Intentional cancel/release of an unused reservation -> `released`."""
    reservation_id = str(reservation.get("reservationId") or "").strip()
    if not reservation_id:
        return
    now_ms = int(time.time() * 1000)

    def mutate(uow):
        row = uow.repository.execute(
            "SELECT receipt_id, status, settled_json FROM budget_receipts "
            "WHERE reservation_id = ?",
            (reservation_id,),
        ).fetchone()
        if row is None:
            return
        if str(row[1] or "") in _TERMINAL_BUDGET_STATUSES:
            return
        payload = _payload(row[2], label="settled_json")
        payload.update(
            {
                "reason": reason,
                "source": "budget-authority-adapter",
                "terminal": "released",
            }
        )
        uow.repository.update_budget_receipt(
            str(row[0]),
            status="released",
            now_ms=now_ms,
            settled_json=json.dumps(payload, ensure_ascii=False),
        )

    store.submit(mutate, force_flush=True).result(timeout=30)


def void_budget_reservation(
    store: WorkflowLedgerStore,
    reservation: dict[str, Any],
    *,
    reason: str = "compensation_void",
    correlation_id: str | None = None,
) -> None:
    """Crash/compensation path for an unused reservation -> `voided`.

    Architecture 9.3: user cancel without consumption is `released`; abnormal
    compensation is `voided` with reason/correlationId.
    """
    reservation_id = str(reservation.get("reservationId") or "").strip()
    if not reservation_id:
        return
    now_ms = int(time.time() * 1000)
    corr = str(
        correlation_id
        or reservation.get("correlationId")
        or reservation.get("actionId")
        or ""
    ).strip()

    def mutate(uow):
        row = uow.repository.execute(
            "SELECT receipt_id, status, settled_json FROM budget_receipts "
            "WHERE reservation_id = ?",
            (reservation_id,),
        ).fetchone()
        if row is None:
            return
        if str(row[1] or "") in _TERMINAL_BUDGET_STATUSES:
            return
        payload = _payload(row[2], label="settled_json")
        payload.update(
            {
                "reason": reason,
                "source": "budget-authority-adapter",
                "terminal": "voided",
            }
        )
        if corr:
            payload["correlationId"] = corr
        uow.repository.update_budget_receipt(
            str(row[0]),
            status="voided",
            now_ms=now_ms,
            settled_json=json.dumps(payload, ensure_ascii=False),
        )

    store.submit(mutate, force_flush=True).result(timeout=30)
