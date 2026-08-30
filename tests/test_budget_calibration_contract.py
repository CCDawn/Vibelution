"""Formal budget calibration contract (challenge-cup node budget gate).

The Agent node attempt reservation must derive from the explicit budget
contract (task budgetRequest > frozen stage budget > 2,000,000 fallback),
stage admission must stay admissible for later attempts after a real node
settles, and the invocation preflight must reject fail-closed with
machine-readable detail instead of silently clamping output to an unusable
sliver.
"""

from __future__ import annotations

import json
from pathlib import Path

from core.research.workflow.contracts import PendingAction
from core.research.workflow.models import ActorKind
from core.web.services.team_workflow.research_runtime.budget_authority_adapter import (
    DEFAULT_AGENT_NODE_RESERVE_TOKENS,
    DEFAULT_STAGE_TOKENS,
    settle_budget_authority,
)
from core.web.services.team_workflow.research_runtime.real_domain_ports import (
    RealDomainPorts,
    resolve_agent_reserve_tokens,
)
from tests._support.command_helpers import CommandHarness

FALLBACK_TOKENS = 2_000_000
REAL_NODE_USAGE = 294_131


def _action(node_id: str = "source_finding", node_run_id: str | None = None):
    return PendingAction(
        action_id=f"act-budget-{node_id}",
        run_id="run-test",
        node_run_id=node_run_id or f"nr-run-test-{node_id}-a1",
        node_id=node_id,
        attempt=1,
        actor_kind=ActorKind.AGENT,
        action_kind="start_agent_task",
        input_snapshot_hash="a" * 64,
        input_artifact_refs=(),
        binding_snapshot_id=None,
        budget_policy_hash="p-1",
    )


def _seed_attempt(harness: CommandHarness, action: PendingAction) -> None:
    from tests._support.workflow_ledger_helpers import (
        build_attempt_record,
        build_command_record,
    )

    def mutate(uow):
        if uow.repository.get_command("cmd-budget") is None:
            uow.repository.insert_command(
                build_command_record(
                    command_id="cmd-budget",
                    run_id=action.run_id,
                    idempotency_key="cmd-budget",
                )
            )
        if uow.repository.get_attempt(action.node_run_id) is None:
            uow.repository.insert_attempt(
                build_attempt_record(
                    action.node_run_id,
                    run_id=action.run_id,
                    node_id=action.node_id,
                    attempt=1,
                    status="dispatching",
                    command_id="cmd-budget",
                )
            )

    harness.store.submit(mutate, force_flush=True).result(timeout=10)


def _write_snapshot(harness: CommandHarness, budget_policy: dict | None) -> None:
    snapshot: dict = {"snapshotHash": "a" * 64}
    if budget_policy is not None:
        snapshot["budgetPolicy"] = budget_policy

    def mutate(uow):
        uow.repository.execute(
            "UPDATE workflow_runs SET input_snapshot_json = ? WHERE run_id = ?",
            (json.dumps(snapshot), "run-test"),
        )

    harness.store.submit(mutate, force_flush=True).result(timeout=10)


def _reserved_estimate(harness: CommandHarness, reservation_id: str) -> dict:
    row = harness.store.submit(
        lambda uow: uow.repository.execute(
            "SELECT reserved_json FROM budget_receipts WHERE reservation_id = ?",
            (reservation_id,),
        ).fetchone(),
        force_flush=True,
    ).result(timeout=10)
    assert row is not None
    return json.loads(row[0])


# --------------------------------------------------------------------- ①


def test_missing_contract_reserves_conservative_fallback(tmp_path: Path) -> None:
    """No budget contract -> the 2M fallback, never the old flat 25K."""
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        action = _action()
        _seed_attempt(harness, action)
        ports = RealDomainPorts(harness.store)
        reservation = ports.reserve_budget(action=action, estimate_tokens=25_000)
        assert reservation["reserved"]["estimatedTokens"] == FALLBACK_TOKENS
        assert reservation["limits"]["tokens"] == DEFAULT_STAGE_TOKENS
        stored = _reserved_estimate(harness, reservation["reservationId"])
        assert stored["reserved"]["estimatedTokens"] == FALLBACK_TOKENS
        assert stored["reserved"]["estimatedTokens"] != 25_000
    finally:
        harness.close()


def test_preflight_keeps_output_usable_for_real_node_input(monkeypatch) -> None:
    """A 24K real-node input against a contract-scale reservation keeps the
    full profile output space (>= the usable floor)."""
    from core.web.services.session import worker as session_worker

    monkeypatch.setattr(
        session_worker,
        "_challenge_budget_window",
        lambda _ctx: {"status": "reserved", "remaining": FALLBACK_TOKENS},
    )
    decision = session_worker._challenge_invocation_budget_preflight(
        {},
        estimated_input_tokens=24_000,
        max_output_tokens=32_768,
    )
    assert decision["maxOutputTokens"] == 32_768
    assert (
        decision["maxOutputTokens"]
        >= session_worker.MIN_INVOCATION_OUTPUT_TOKENS
    )
    assert session_worker.MIN_INVOCATION_OUTPUT_TOKENS == 4_096


# --------------------------------------------------------------------- ②


def test_resolve_agent_reserve_tokens_priority_order() -> None:
    """Explicit task budget > stage budget > run policy tokens > fallback."""
    stage_snapshot = {
        "budgetPolicy": {
            "stageBudgets": {"knowledge_collection": {"tokens": 500_000}}
        }
    }
    policy_snapshot = {"budgetPolicy": {"tokens": 300_000}}

    def lookup(value: int | None):
        return lambda _run_id, _node_run_id: value

    assert (
        resolve_agent_reserve_tokens(
            stage_snapshot,
            run_id="run-test",
            node_id="source_finding",
            node_run_id="nr-1",
            budget_request_lookup=lookup(777_777),
        )
        == 777_777
    )
    assert (
        resolve_agent_reserve_tokens(
            stage_snapshot,
            run_id="run-test",
            node_id="source_finding",
            node_run_id="nr-1",
            budget_request_lookup=lookup(None),
        )
        == 500_000
    )
    assert (
        resolve_agent_reserve_tokens(
            policy_snapshot,
            run_id="run-test",
            node_id="source_finding",
            node_run_id="nr-1",
            budget_request_lookup=lookup(None),
        )
        == 300_000
    )
    assert (
        resolve_agent_reserve_tokens(
            {},
            run_id="run-test",
            node_id="source_finding",
            node_run_id="nr-1",
            budget_request_lookup=lookup(None),
        )
        == DEFAULT_AGENT_NODE_RESERVE_TOKENS
    )
    # Count-style or invalid token values never arm a token reservation.
    for invalid in (0, -5, True):
        assert (
            resolve_agent_reserve_tokens(
                stage_snapshot,
                run_id="run-test",
                node_id="source_finding",
                node_run_id="nr-1",
                budget_request_lookup=lookup(invalid),
            )
            == 500_000
        )


def test_reserve_estimate_priority_end_to_end(tmp_path: Path) -> None:
    """The persisted receipt carries the contract estimate, task-first."""
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        _write_snapshot(
            harness,
            {"stageBudgets": {"knowledge_collection": {"tokens": 1_000_000}}},
        )
        action = _action()
        _seed_attempt(harness, action)
        ports = RealDomainPorts(harness.store)

        from core.web.services.team_workflow.research_runtime import (
            real_domain_ports as ports_module,
        )

        original = ports_module._task_budget_request_tokens
        ports_module._task_budget_request_tokens = (
            lambda run_id, node_run_id: 777_777
        )
        try:
            reservation = ports.reserve_budget(
                action=action, estimate_tokens=25_000
            )
        finally:
            ports_module._task_budget_request_tokens = original
        # The explicit task budget wins over both the stage budget and the
        # fallback (stage capacity is large enough that the admission cap
        # does not bind).
        assert reservation["reserved"]["estimatedTokens"] == 777_777
    finally:
        harness.close()


# --------------------------------------------------------------------- ③


def test_stage_admission_allows_next_attempt_after_real_node_settles(
    tmp_path: Path,
) -> None:
    """A settled real-scale node (~294K) must not lock the stage for the next
    attempt; the stage limit keeps satisfying
    limit >= one attempt x (1 + autoRetries)."""
    from core.web.services.team_workflow.research_runtime.budget_authority_adapter import (
        record_budget_usage,
    )

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        first = _action("source_finding", "nr-run-test-source_finding-a1")
        second = _action("source_extraction", "nr-run-test-source_extraction-a2")
        _seed_attempt(harness, first)
        _seed_attempt(harness, second)
        ports = RealDomainPorts(harness.store)

        reservation = ports.reserve_budget(
            action=first, estimate_tokens=25_000
        )
        assert reservation["reserved"]["estimatedTokens"] == FALLBACK_TOKENS
        record_budget_usage(
            harness.store,
            run_id=first.run_id,
            node_run_id=first.node_run_id,
            reservation_id=reservation["reservationId"],
            invocation_id="inv-real-node",
            input_tokens=196_000,
            output_tokens=98_131,
        )
        settled = settle_budget_authority(
            harness.store,
            reservation={
                "reservationId": reservation["reservationId"],
                "runId": first.run_id,
                "nodeRunId": first.node_run_id,
            },
            usage={"tokens": REAL_NODE_USAGE},
        )
        assert settled["status"] == "settled"

        # The next attempt in the same stage must be admitted (RED on the old
        # contract: 294_131 + 25_000 > 250_000 rejected permanently).
        next_reservation = ports.reserve_budget(
            action=second, estimate_tokens=25_000
        )
        assert next_reservation["status"] == "reserved"
        # The derived estimate is capped by the stage's remaining capacity.
        assert next_reservation["reserved"]["estimatedTokens"] == (
            FALLBACK_TOKENS - REAL_NODE_USAGE
        )
        # Stage-limit invariant: limit >= one real attempt x (1 + retries).
        assert next_reservation["limits"]["tokens"] >= REAL_NODE_USAGE * 3
    finally:
        harness.close()


# --------------------------------------------------------------------- ④


def test_preflight_rejects_explicitly_when_output_floor_unreachable(
    monkeypatch,
) -> None:
    """Old-scale reservation (25K) + 24K input -> explicit budget_exhausted,
    never a silent 1K clamp."""
    from core.web.services.session import worker as session_worker

    monkeypatch.setattr(
        session_worker,
        "_challenge_budget_window",
        lambda _ctx: {"status": "reserved", "remaining": 25_000},
    )
    decision = session_worker._challenge_invocation_budget_preflight(
        {},
        estimated_input_tokens=24_000,
        max_output_tokens=32_768,
    )
    assert decision["maxOutputTokens"] == 0
    assert decision["budgetExhausted"] is True
    assert decision["reason"] == "insufficient_budget"
    assert decision["requiredMinOutput"] == 4_096
    assert decision["remainingTokens"] == 25_000
    assert decision["estimatedInputTokens"] == 24_000


def test_preflight_distinguishes_input_overrun_from_output_floor(
    monkeypatch,
) -> None:
    from core.web.services.session import worker as session_worker

    monkeypatch.setattr(
        session_worker,
        "_challenge_budget_window",
        lambda _ctx: {"status": "reserved", "remaining": 30_000},
    )
    overrun = session_worker._challenge_invocation_budget_preflight(
        {},
        estimated_input_tokens=31_000,
        max_output_tokens=32_768,
    )
    assert overrun["maxOutputTokens"] == 0
    assert overrun["budgetExhausted"] is True
    assert overrun["reason"] == "input_exceeds_remaining"

    floor = session_worker._challenge_invocation_budget_preflight(
        {},
        estimated_input_tokens=27_000,
        max_output_tokens=32_768,
    )
    assert floor["maxOutputTokens"] == 0
    assert floor["reason"] == "insufficient_budget"


def test_preflight_output_floor_is_env_configurable(monkeypatch) -> None:
    from core.web.services.session import worker as session_worker

    monkeypatch.setattr(
        session_worker,
        "_challenge_budget_window",
        lambda _ctx: {"status": "reserved", "remaining": 30_000},
    )
    monkeypatch.setenv("VIBELUTION_MIN_INVOCATION_OUTPUT_TOKENS", "8192")
    decision = session_worker._challenge_invocation_budget_preflight(
        {},
        estimated_input_tokens=24_000,
        max_output_tokens=32_768,
    )
    assert decision["maxOutputTokens"] == 0
    assert decision["requiredMinOutput"] == 8192

    monkeypatch.setenv("VIBELUTION_MIN_INVOCATION_OUTPUT_TOKENS", "2048")
    allowed = session_worker._challenge_invocation_budget_preflight(
        {},
        estimated_input_tokens=24_000,
        max_output_tokens=32_768,
    )
    assert allowed["maxOutputTokens"] == 6_000


# ------------------------------------------------------- preserved semantics


def test_reservation_idempotency_reuses_original_estimate(tmp_path: Path) -> None:
    """Same reservation id reuses the original estimate even after the frozen
    snapshot contract changes."""
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        action = _action()
        _seed_attempt(harness, action)
        ports = RealDomainPorts(harness.store)
        first = ports.reserve_budget(action=action, estimate_tokens=25_000)
        assert first["reserved"]["estimatedTokens"] == FALLBACK_TOKENS

        _write_snapshot(
            harness,
            {"stageBudgets": {"knowledge_collection": {"tokens": 500}}},
        )
        second = ports.reserve_budget(action=action, estimate_tokens=25_000)
        assert second["idempotent"] is True
        assert second["reserved"]["estimatedTokens"] == FALLBACK_TOKENS
    finally:
        harness.close()


def test_stage_exhausted_rejects_fail_closed(tmp_path: Path) -> None:
    """A stage with no remaining capacity still rejects fail-closed with the
    existing safety code."""
    import pytest

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        _write_snapshot(
            harness,
            {"stageBudgets": {"knowledge_collection": {"tokens": 500}}},
        )
        first = _action("source_finding", "nr-run-test-source_finding-a1")
        second = _action("source_extraction", "nr-run-test-source_extraction-a2")
        _seed_attempt(harness, first)
        _seed_attempt(harness, second)
        ports = RealDomainPorts(harness.store)
        reservation = ports.reserve_budget(action=first, estimate_tokens=25_000)
        assert reservation["reserved"]["estimatedTokens"] == 500
        with pytest.raises(RuntimeError, match="budget|limit|exceed"):
            ports.reserve_budget(action=second, estimate_tokens=25_000)
    finally:
        harness.close()
