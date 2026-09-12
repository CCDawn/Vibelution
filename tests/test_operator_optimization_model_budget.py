"""RED tests for the operator discussion model-budget bridge.

The bridge owns only operator-specific money semantics.  Workflow Ledger
``budget_receipts`` remains the durable source of reservation and settlement
facts; no model provider or receipt registry is involved in these tests.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

import pytest

from core.research.operator_optimization.model_budget_contracts import (
    OperatorDiscussionBudget,
)
from core.web.services.team_workflow.operator_optimization.model_budget import (
    ModelBudgetError,
    admit_model_invocation,
    calculate_model_cost,
    reserve_model_budget,
    settle_model_budget,
    record_model_invocation_usage,
)
from tests._support.workflow_ledger_helpers import (
    build_attempt_record,
    build_command_record,
    open_ledger_store,
)


def _discussion_budget(
    *, token_limit: int = 1_000, max_output: int = 100, max_calls: int = 3
) -> OperatorDiscussionBudget:
    return OperatorDiscussionBudget.model_validate(
        {
            "tokenLimit": token_limit,
            "maxOutputTokensPerCall": max_output,
            "maxCalls": max_calls,
            "prices": [
                {
                    "modelRef": "qwen/operator",
                    "priceVersion": "price-v1",
                    "currency": "USD",
                    "inputPerMillion": 1.0,
                    "outputPerMillion": 2.0,
                }
            ],
        }
    )


def _multi_model_budget() -> OperatorDiscussionBudget:
    return OperatorDiscussionBudget.model_validate(
        {
            "tokenLimit": 1_000,
            "maxOutputTokensPerCall": 100,
            "maxCalls": 3,
            "prices": [
                {
                    "modelRef": "qwen/operator",
                    "priceVersion": "price-v1",
                    "currency": "USD",
                    "inputPerMillion": 1.0,
                    "outputPerMillion": 2.0,
                },
                {
                    "modelRef": "glm/operator",
                    "priceVersion": "price-v2",
                    "currency": "USD",
                    "inputPerMillion": 3.0,
                    "outputPerMillion": 4.0,
                },
            ],
        }
    )


def _seed_parent(store, *, run_id: str, node_run_id: str) -> None:
    from tests._support.workflow_ledger_helpers import build_event_record, build_run_record

    def mutate(uow):
        if uow.repository.get_run(run_id) is None:
            uow.repository.insert_run(build_run_record(run_id=run_id))
            uow.repository.insert_event(
                build_event_record(
                    1,
                    run_id=run_id,
                    event_id=f"event-{run_id}",
                )
            )
        command_id = f"command-{node_run_id}"
        if uow.repository.get_command(command_id) is None:
            uow.repository.insert_command(
                build_command_record(command_id=command_id, run_id=run_id)
            )
        if uow.repository.get_attempt(node_run_id) is None:
            uow.repository.insert_attempt(
                build_attempt_record(
                    node_run_id,
                    run_id=run_id,
                    node_id="optimization_discussion",
                    command_id=command_id,
                    status="dispatching",
                )
            )

    store.submit(mutate, force_flush=True).result(timeout=10)


def _reserve_kwargs(
    *,
    run_id: str = "run-1",
    node_run_id: str = "node-1",
    campaign_id: str = "campaign-1",
    round_id: str = "round-1",
    cost_limit: str = "0.01",
    budget: OperatorDiscussionBudget | None = None,
) -> dict:
    return {
        "run_id": run_id,
        "node_run_id": node_run_id,
        "optimization_campaign_id": campaign_id,
        "round_id": round_id,
        "model_ref": "qwen/operator",
        "discussion_budget": budget or _discussion_budget(),
        "model_cost_limit": Decimal(cost_limit),
        "campaign_currency": "USD",
        "policy_hash": "policy-v1",
    }


def test_missing_discussion_budget_is_rejected_without_a_default():
    kwargs = _reserve_kwargs()
    kwargs["discussion_budget"] = None
    with pytest.raises(ModelBudgetError, match="discussion budget") as exc_info:
        reserve_model_budget(
            None,
            **kwargs,
        )
    assert exc_info.value.code == "operator_model_budget_missing"


@pytest.mark.parametrize("consumed", [False, True])
@pytest.mark.parametrize("operation", ["void", "release", "compensate"])
def test_native_budget_cleanup_preserves_unknown_operator_cost(tmp_path, consumed, operation):
    from core.web.services.team_workflow.research_runtime.budget_authority_adapter import (
        void_budget_reservation, release_budget_reservation,
        compensate_terminal_attempt_reservation_in_uow,
    )
    store = open_ledger_store(tmp_path / "cleanup.sqlite")
    try:
        _seed_parent(store, run_id="run-1", node_run_id="node-1")
        reservation = reserve_model_budget(store, **_reserve_kwargs())
        if consumed:
            admit_model_invocation(store, reservation=reservation, invocation_id="call1",
                model_ref="qwen/operator", input_tokens=20, output_tokens=50)
        if operation == "compensate":
            store.submit(lambda u: compensate_terminal_attempt_reservation_in_uow(u,
                run_id="run-1", node_run_id="node-1", reason="test"), force_flush=True).result()
        else:
            (void_budget_reservation if operation == "void" else release_budget_reservation)(store, reservation)
        status = store.submit(lambda u: u.repository.execute(
            "SELECT status FROM budget_receipts WHERE reservation_id = ?",
            (reservation["reservationId"],)).fetchone()[0]).result()
        assert status == ("reserved" if consumed else "released" if operation == "release" else "voided")
    finally:
        store.close()


def test_cost_uses_frozen_model_price_and_separate_input_output_rates():
    amount = calculate_model_cost(
        _discussion_budget(),
        model_ref="qwen/operator",
        input_tokens=900,
        output_tokens=100,
    )
    assert amount == Decimal("0.0011")


def test_ledger_reservation_records_parent_identity_price_and_unsettled_cost(
    tmp_path: Path,
):
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        _seed_parent(store, run_id="run-1", node_run_id="node-1")
        result = reserve_model_budget(store, **_reserve_kwargs())
        assert result["status"] == "reserved"
        assert result["costStatus"] == "unsettled"
        assert result["currency"] == "USD"
        assert result["reservedAmount"] == Decimal("0.0013")

        row = store.submit(
            lambda uow: uow.repository.execute(
                "SELECT reserved_json, settled_json, status FROM budget_receipts "
                "WHERE reservation_id = ?",
                ("reservation-node-1",),
            ).fetchone(),
            force_flush=True,
        ).result(timeout=10)
        assert row is not None and row[2] == "reserved"
        reserved = json.loads(row[0])
        assert reserved["operatorModelBudget"]["optimizationCampaignId"] == "campaign-1"
        assert reserved["operatorModelBudget"]["parentNodeRunId"] == "node-1"
        assert reserved["operatorModelBudget"]["priceVersion"] == "price-v1"
        assert reserved["operatorModelBudget"]["currency"] == "USD"
        assert row[1] is None
    finally:
        store.close()


def test_one_reservation_charges_each_frozen_model_at_its_own_price(
    tmp_path: Path,
):
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        _seed_parent(store, run_id="run-1", node_run_id="node-1")
        kwargs = _reserve_kwargs(budget=_multi_model_budget(), cost_limit="0.01")
        kwargs["model_ref"] = None
        reservation = reserve_model_budget(store, **kwargs)
        assert reservation["modelRefs"] == ["qwen/operator", "glm/operator"]
        assert reservation["reservedAmount"] == Decimal("0.0033")

        first = record_model_invocation_usage(
            store,
            reservation=reservation,
            invocation_id="invocation-qwen",
            model_ref="qwen/operator",
            input_tokens=100,
            output_tokens=10,
        )
        second = record_model_invocation_usage(
            store,
            reservation=reservation,
            invocation_id="invocation-glm",
            model_ref="glm/operator",
            input_tokens=200,
            output_tokens=20,
        )
        assert first["actualAmount"] == Decimal("0.00012")
        assert second["actualAmount"] == Decimal("0.0008")

        settled = settle_model_budget(store, reservation=reservation)
        assert settled["status"] == "settled"
        assert settled["actualAmount"] == Decimal("0.0008")
    finally:
        store.close()


def test_cross_round_reservations_share_campaign_ceiling_in_one_ledger_transaction(
    tmp_path: Path,
):
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        _seed_parent(store, run_id="run-1", node_run_id="node-1")
        _seed_parent(store, run_id="run-2", node_run_id="node-2")
        first = reserve_model_budget(
            store,
            **_reserve_kwargs(
                run_id="run-1", node_run_id="node-1", round_id="round-1", cost_limit="0.002"
            ),
        )
        assert first["reservedAmount"] == Decimal("0.0013")
        with pytest.raises(ModelBudgetError) as exc_info:
            reserve_model_budget(
                store,
                **_reserve_kwargs(
                    run_id="run-2", node_run_id="node-2", round_id="round-2", cost_limit="0.002"
                ),
            )
        assert exc_info.value.code == "operator_model_budget_limit_reached"
    finally:
        store.close()


def test_concurrent_campaign_reservations_cannot_double_spend(tmp_path: Path):
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        for index in range(3):
            _seed_parent(store, run_id=f"run-{index}", node_run_id=f"node-{index}")

        def attempt(index: int):
            try:
                return reserve_model_budget(
                    store,
                    **_reserve_kwargs(
                        run_id=f"run-{index}",
                        node_run_id=f"node-{index}",
                        round_id=f"round-{index}",
                        cost_limit="0.002",
                    ),
                )
            except ModelBudgetError as exc:
                return exc.code

        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(attempt, range(3)))
        assert sum(isinstance(item, dict) for item in results) == 1
        assert results.count("operator_model_budget_limit_reached") == 2
    finally:
        store.close()


def test_invocation_usage_is_deduplicated_failures_count_and_unknown_stays_reserved(
    tmp_path: Path,
):
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        _seed_parent(store, run_id="run-1", node_run_id="node-1")
        reservation = reserve_model_budget(store, **_reserve_kwargs())
        first = record_model_invocation_usage(
            store,
            reservation=reservation,
            invocation_id="invocation-failed",
            outcome="failed",
            model_ref="qwen/operator",
            input_tokens=400,
            output_tokens=50,
        )
        duplicate = record_model_invocation_usage(
            store,
            reservation=reservation,
            invocation_id="invocation-failed",
            outcome="failed",
            model_ref="qwen/operator",
            input_tokens=400,
            output_tokens=50,
        )
        unknown = record_model_invocation_usage(
            store,
            reservation=reservation,
            invocation_id="invocation-timeout",
            outcome="timeout",
            model_ref="qwen/operator",
            usage_known=False,
        )
        assert first["idempotent"] is False
        assert duplicate["idempotent"] is True
        assert unknown["costStatus"] == "unsettled"
        assert unknown["status"] == "reserved"

        payload = store.submit(
            lambda uow: uow.repository.execute(
                "SELECT settled_json FROM budget_receipts WHERE reservation_id = ?",
                (reservation["reservationId"],),
            ).fetchone(),
            force_flush=True,
        ).result(timeout=10)
        settled = json.loads(payload[0])
        assert len(settled["invocations"]) == 2
        assert settled["operatorModelBudget"]["knownAmount"] == "0.0005"
        assert settled["operatorModelBudget"]["costStatus"] == "unsettled"
    finally:
        store.close()


def test_admission_counts_retries_and_enforces_output_and_total_token_limits(
    tmp_path: Path,
):
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        _seed_parent(store, run_id="run-1", node_run_id="node-1")
        reservation = reserve_model_budget(
            store,
            **_reserve_kwargs(budget=_discussion_budget(token_limit=100, max_output=20, max_calls=2)),
        )
        admitted = admit_model_invocation(
            store,
            reservation=reservation,
            invocation_id="attempt-1",
            model_ref="qwen/operator",
            input_tokens=80,
            output_tokens=20,
        )
        assert admitted["admitted"] is True
        with pytest.raises(ModelBudgetError) as exc_info:
            admit_model_invocation(
                store,
                reservation=reservation,
                invocation_id="attempt-2",
                model_ref="qwen/operator",
                input_tokens=81,
                output_tokens=20,
            )
        assert exc_info.value.code == "operator_model_token_limit_reached"
        with pytest.raises(ModelBudgetError) as exc_info:
            admit_model_invocation(
                store,
                reservation=reservation,
                invocation_id="attempt-3",
                model_ref="qwen/operator",
                input_tokens=1,
                output_tokens=21,
            )
        assert exc_info.value.code == "operator_model_output_limit_reached"
    finally:
        store.close()


def test_settlement_uses_frozen_tokens_and_currency_and_is_idempotent(tmp_path: Path):
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        _seed_parent(store, run_id="run-1", node_run_id="node-1")
        reservation = reserve_model_budget(store, **_reserve_kwargs())
        record_model_invocation_usage(
            store,
            reservation=reservation,
            invocation_id="invocation-ok",
            outcome="succeeded",
            model_ref="qwen/operator",
            input_tokens=900,
            output_tokens=100,
        )
        settled = settle_model_budget(store, reservation=reservation)
        replay = settle_model_budget(store, reservation=reservation)
        assert settled["status"] == "settled"
        assert settled["costStatus"] == "settled"
        assert settled["actualAmount"] == Decimal("0.0011")
        assert replay["idempotent"] is True
        assert replay["actualAmount"] == Decimal("0.0011")

        row = store.submit(
            lambda uow: uow.repository.execute(
                "SELECT status, settled_json FROM budget_receipts WHERE reservation_id = ?",
                (reservation["reservationId"],),
            ).fetchone(),
            force_flush=True,
        ).result(timeout=10)
        assert row[0] == "settled"
        assert json.loads(row[1])["operatorModelBudget"]["currency"] == "USD"
    finally:
        store.close()
