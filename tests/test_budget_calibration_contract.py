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

import pytest

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


def _write_safety_limits(harness: CommandHarness, limits: dict) -> None:
    def mutate(uow):
        uow.repository.execute(
            "UPDATE workflow_runs SET safety_limits_json = ? WHERE run_id = ?",
            (json.dumps(limits), "run-test"),
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


def test_real_batch_uses_the_formal_budget_capacity_contract() -> None:
    """The real-batch launcher must not freeze the obsolete 200K contract."""
    from core.web.services.team_workflow.challenge_cup_real_batch import (
        _default_safety_limits,
    )

    limits = _default_safety_limits()
    assert limits == {
        "stageTokens": {
            "knowledge_collection": FALLBACK_TOKENS,
            "experiment_design": FALLBACK_TOKENS,
            "execution_iteration": FALLBACK_TOKENS,
        },
        "toolCalls": 600,
        "wallClockSeconds": 4 * 60 * 60,
        "maxRetries": 3,
    }


def test_launch_stage_capacity_covers_observed_max_attempt() -> None:
    """Every launch stage default must admit the observed worst single real
    attempt with headroom (SCI-091 production: one source_finding attempt
    settled ~407K tokens, metering allowed overrun to 460K+).  A stage limit
    below one real attempt deadlocks the stage after the first settle and
    forces a manual extend_budget, so the 1M calibration floor is a contract.
    The other stages stay at the shared uniform DEFAULT (2M): unchanged."""
    from core.web.services.team_workflow.research_runtime.budget_contract import (
        DEFAULT_STAGE_TOKENS,
        FORMAL_STAGE_IDS,
        default_safety_limits,
    )
    from core.web.services.team_workflow.research_runtime.hypothesis_first_chain import (
        _formal_run_safety_limits,
    )

    OBSERVED_MAX_ATTEMPT_TOKENS = 460_000
    CALIBRATION_FLOOR_TOKENS = 1_000_000

    for limits in (default_safety_limits(), _formal_run_safety_limits()):
        assert set(limits["stageTokens"]) == set(FORMAL_STAGE_IDS)
        assert (
            limits["stageTokens"]["knowledge_collection"] >= CALIBRATION_FLOOR_TOKENS
        )
        for stage_id in FORMAL_STAGE_IDS:
            assert limits["stageTokens"][stage_id] == DEFAULT_STAGE_TOKENS
            assert limits["stageTokens"][stage_id] >= OBSERVED_MAX_ATTEMPT_TOKENS * 2


def test_question_launch_accepts_the_formal_budget_capacity_contract() -> None:
    """The launch validator must accept the same 2M capacity as the runtime."""
    from core.web.services.team_workflow.research_runtime.question_launch import (
        build_safety_budget_policy,
    )

    policy = build_safety_budget_policy(
        {
            "stageTokens": {
                "knowledge_collection": FALLBACK_TOKENS,
                "experiment_design": FALLBACK_TOKENS,
                "execution_iteration": FALLBACK_TOKENS,
            },
            "toolCalls": 600,
            "wallClockSeconds": 4 * 60 * 60,
            "maxRetries": 3,
        }
    )
    assert policy["tokens"] == FALLBACK_TOKENS
    assert policy["stageBudgets"]["knowledge_collection"]["tokens"] == FALLBACK_TOKENS


def test_budget_authority_uses_canonical_stage_and_retry_fields() -> None:
    """Stage mapping and retry limits must match the frozen launch contract."""
    from core.web.services.team_workflow.research_runtime import (
        budget_authority_adapter,
    )

    assert budget_authority_adapter.stage_for_node("problem_understanding") == (
        "knowledge_collection"
    )
    limits = budget_authority_adapter._policy_limits(
        {
            "budgetPolicy": {
                "tokens": FALLBACK_TOKENS,
                "toolCalls": 600,
                "wallClockSeconds": 4 * 60 * 60,
                "maxRetries": 3,
            }
        },
        "knowledge_collection",
    )
    assert limits == {
        "tokens": FALLBACK_TOKENS,
        "toolCalls": 600,
        "seconds": 4 * 60 * 60,
        "retries": 3,
    }


def test_operator_safety_limits_override_legacy_frozen_stage_capacity(
    tmp_path: Path,
) -> None:
    """A formal operator override must affect new receipts without rewriting
    the immutable input snapshot."""
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        frozen_policy = {
            "tokens": 200_000,
            "toolCalls": 600,
            "wallClockSeconds": 4 * 60 * 60,
            "maxRetries": 3,
            "stageBudgets": {
                "knowledge_collection": {"tokens": 200_000},
                "experiment_design": {"tokens": 200_000},
                "execution_iteration": {"tokens": 200_000},
            },
        }
        _write_snapshot(harness, frozen_policy)
        _write_safety_limits(
            harness,
            {
                "stageTokens": {"knowledge_collection": FALLBACK_TOKENS},
                "maxRetries": 3,
            },
        )
        action = _action()
        _seed_attempt(harness, action)

        reservation = RealDomainPorts(harness.store).reserve_budget(
            action=action,
            estimate_tokens=200_000,
        )

        assert reservation["limits"]["tokens"] == FALLBACK_TOKENS
        row = harness.store.submit(
            lambda uow: uow.repository.get_run("run-test"),
            force_flush=True,
        ).result(timeout=10)
        assert json.loads(row.input_snapshot_json)["budgetPolicy"] == frozen_policy
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


def test_preflight_reports_soft_pressure_without_blocking_output(
    monkeypatch,
) -> None:
    """An obsolete 25K reservation is accounting pressure, not permission to
    terminate a progressing formal Agent invocation."""
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
    assert decision["maxOutputTokens"] == 32_768
    assert decision["budgetPressure"] is True
    assert decision["softLimitExceeded"] is True
    assert decision["reason"] == "insufficient_budget"
    assert decision["requiredMinOutput"] == 4_096
    assert decision["remainingTokens"] == 25_000
    assert decision["estimatedInputTokens"] == 24_000


def test_preflight_distinguishes_soft_pressure_reasons_without_blocking(
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
    assert overrun["maxOutputTokens"] == 32_768
    assert overrun["budgetPressure"] is True
    assert overrun["softLimitExceeded"] is True
    assert overrun["reason"] == "input_exceeds_remaining"

    floor = session_worker._challenge_invocation_budget_preflight(
        {},
        estimated_input_tokens=27_000,
        max_output_tokens=32_768,
    )
    assert floor["maxOutputTokens"] == 32_768
    assert floor["budgetPressure"] is True
    assert floor["softLimitExceeded"] is True
    assert floor["reason"] == "insufficient_budget"


def test_preflight_output_floor_only_changes_soft_pressure_metadata(monkeypatch) -> None:
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
    assert decision["maxOutputTokens"] == 32_768
    assert decision["budgetPressure"] is True
    assert decision["requiredMinOutput"] == 8192

    monkeypatch.setenv("VIBELUTION_MIN_INVOCATION_OUTPUT_TOKENS", "2048")
    allowed = session_worker._challenge_invocation_budget_preflight(
        {},
        estimated_input_tokens=24_000,
        max_output_tokens=32_768,
    )
    assert allowed["maxOutputTokens"] == 32_768
    assert allowed["budgetPressure"] is True
    assert allowed["softLimitExceeded"] is False


# ------------------------------------------------------- injected authority


def test_budget_window_prefers_injected_resolver(monkeypatch) -> None:
    """The runtime-assembled resolver wins; the production singleton is never
    consulted when an injection exists (embedded runtimes)."""
    from core.web.services.session import worker as session_worker
    from core.web.services.team_workflow.research_runtime import (
        budget_window_resolver as bwr,
    )

    def _forbidden():
        raise AssertionError("production singleton must not be consulted")

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.runtime_factory.production_workflow_runtime",
        _forbidden,
    )
    calls: list[tuple[str, str, str]] = []

    def resolver(run_id: str, node_run_id: str, reservation_id: str):
        calls.append((run_id, node_run_id, reservation_id))
        return {"status": "reserved", "remaining": 4321}

    store = object()
    bwr.configure_budget_window_resolver(resolver, store=store)
    try:
        window = session_worker._challenge_budget_window(
            {
                "questionStageBinding": {
                    "workflowRunId": "run-injected",
                    "formalNodeRunId": "nr-injected",
                }
            }
        )
        assert window == {"status": "reserved", "remaining": 4321}
        assert calls == [("run-injected", "nr-injected", "reservation-nr-injected")]
    finally:
        bwr.release_budget_window_resolver_for_store(store)
    assert bwr.injected_budget_window_resolver() is None


def test_budget_window_falls_back_to_production_singleton(monkeypatch) -> None:
    """Without injection the pre-production singleton path stays intact."""
    from core.web.services.session import worker as session_worker
    from core.web.services.team_workflow.research_runtime import (
        budget_authority_adapter as baa,
    )
    from core.web.services.team_workflow.research_runtime import (
        budget_window_resolver as bwr,
    )
    from core.web.services.team_workflow.research_runtime import (
        runtime_factory,
    )

    assert bwr.injected_budget_window_resolver() is None

    class _FakeRuntime:
        store = object()

    captured: dict[str, str] = {}

    def fake_read(store, run_id, node_run_id, reservation_id):
        captured["reservationId"] = reservation_id
        return {"status": "reserved", "remaining": 7}

    monkeypatch.setattr(runtime_factory, "production_workflow_runtime", lambda: _FakeRuntime())
    monkeypatch.setattr(baa, "read_node_budget_window", fake_read)
    window = session_worker._challenge_budget_window(
        {
            "questionStageBinding": {
                "workflowRunId": "run-fallback",
                "formalNodeRunId": "nr-fallback",
            }
        }
    )
    assert window == {"status": "reserved", "remaining": 7}
    assert captured["reservationId"] == "reservation-nr-fallback"


def test_budget_window_fails_closed_without_injection_or_singleton(
    monkeypatch,
) -> None:
    """Challenge scope with neither injection nor singleton still fails closed."""
    import pytest

    from core.web.services.session import worker as session_worker
    from core.web.services.team_workflow.research_runtime import (
        runtime_factory,
    )

    monkeypatch.setattr(
        runtime_factory, "production_workflow_runtime", lambda: None
    )
    with pytest.raises(RuntimeError, match="challenge_budget_authority_unavailable"):
        session_worker._challenge_budget_window(
            {
                "questionStageBinding": {
                    "workflowRunId": "run-closed",
                    "formalNodeRunId": "nr-closed",
                }
            }
        )


def test_injected_store_supports_receipt_persistence() -> None:
    """The injected runtime store is exposed for the formal receipt enqueue
    path, so embedded runtimes never need the production singleton."""
    from core.web.services.team_workflow.research_runtime import (
        budget_window_resolver as bwr,
    )

    assert bwr.injected_research_runtime_store() is None
    store = object()

    def resolver(run_id: str, node_run_id: str, reservation_id: str):
        return {"status": "reserved", "remaining": 1}

    bwr.configure_budget_window_resolver(resolver, store=store)
    try:
        assert bwr.injected_research_runtime_store() is store
    finally:
        bwr.release_budget_window_resolver_for_store(store)
    assert bwr.injected_research_runtime_store() is None


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


# --------------------------------------------------------------- readiness
# The readiness budget gate must consume the same facts as the admission
# authority: settled usage is the authority and completion releases the
# estimate weight, while a live reservation still occupies its estimate and
# genuine exhaustion still rejects fail-closed.


def _insert_budget_receipt(
    harness: CommandHarness,
    *,
    receipt_id: str,
    node_id: str,
    node_run_id: str,
    estimate: int,
    status: str = "reserved",
    usage: dict[str, int] | None = None,
) -> None:
    _seed_attempt(harness, _action(node_id, node_run_id))
    reserved_json = json.dumps(
        {
            "reserved": {
                "estimatedTokens": estimate,
                "tokens": estimate,
                "toolCalls": 1,
                "seconds": 60,
                "retries": 0,
            },
            "limits": {
                "tokens": 250_000,
                "toolCalls": 300,
                "seconds": 21_600,
                "retries": 2,
            },
        }
    )

    def mutate(uow):
        uow.repository.insert_budget_receipt(
            receipt_id=receipt_id,
            run_id="run-test",
            node_run_id=node_run_id,
            reservation_id=f"reservation-{node_run_id}",
            stage_id="knowledge_collection",
            policy_hash="p-1",
            reserved_json=reserved_json,
            created_at_ms=1_750_000_000_000,
        )
        if status != "reserved":
            settled: dict = {"usage": usage} if usage is not None else {}
            assert uow.repository.update_budget_receipt(
                receipt_id,
                status=status,
                now_ms=1_750_000_000_001,
                settled_json=json.dumps(settled),
            )

    harness.store.submit(mutate, force_flush=True).result(timeout=10)


def _readiness_budget(harness: CommandHarness):
    from core.web.services.team_workflow.research_runtime.real_readiness_context import (
        RealDomainReadinessContext,
        _budget_consumed_from_ledger,
    )

    consumed = _budget_consumed_from_ledger(harness.store, "run-test")
    context = RealDomainReadinessContext(harness.store)
    return consumed, context.budget_limits("research-team", "run-test")


def test_readiness_consumption_releases_settled_estimates(tmp_path: Path) -> None:
    """Two settled attempts with small real usage keep a serial successor
    admissible even though each reserved the full stage estimate."""
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        _write_snapshot(
            harness,
            {"stageBudgets": {"knowledge_collection": {"tokens": 250_000}}},
        )
        _insert_budget_receipt(
            harness,
            receipt_id="br-readiness-a",
            node_id="source_finding",
            node_run_id="nr-run-test-source_finding-a1",
            estimate=250_000,
            status="settled",
            usage={"tokens": 52_000},
        )
        _insert_budget_receipt(
            harness,
            receipt_id="br-readiness-b",
            node_id="source_extraction",
            node_run_id="nr-run-test-source_extraction-a1",
            estimate=250_000,
            status="settled",
            usage={"tokens": 52_000},
        )
        _insert_budget_receipt(
            harness,
            receipt_id="br-readiness-c",
            node_id="evidence_relations",
            node_run_id="nr-run-test-evidence_relations-a0",
            estimate=900_000,
            status="released",
        )
        consumed, budget = _readiness_budget(harness)
        assert consumed["tokens"] == 104_000
        assert budget.available() == (True, "")
    finally:
        harness.close()


def test_readiness_live_reservation_still_occupies_its_estimate(
    tmp_path: Path,
) -> None:
    """A live reservation occupies its full estimate: live estimate plus
    settled real usage beyond the stage limit still blocks fail-closed."""
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        _write_snapshot(
            harness,
            {"stageBudgets": {"knowledge_collection": {"tokens": 250_000}}},
        )
        _insert_budget_receipt(
            harness,
            receipt_id="br-readiness-live",
            node_id="evidence_relations",
            node_run_id="nr-run-test-evidence_relations-a1",
            estimate=250_000,
        )
        _insert_budget_receipt(
            harness,
            receipt_id="br-readiness-settled",
            node_id="source_extraction",
            node_run_id="nr-run-test-source_extraction-a1",
            estimate=250_000,
            status="settled",
            usage={"tokens": 52_000},
        )
        consumed, budget = _readiness_budget(harness)
        assert consumed["tokens"] == 302_000
        available, reason = budget.available()
        assert available is False
        assert reason == "stage_tokens_limit_reached"
    finally:
        harness.close()


def test_readiness_real_usage_exhaustion_still_rejects(tmp_path: Path) -> None:
    """Settled real usage genuinely beyond the stage limit still rejects the
    readiness gate (the semantic alignment never loosens the gate)."""
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        _write_snapshot(
            harness,
            {"stageBudgets": {"knowledge_collection": {"tokens": 250_000}}},
        )
        _insert_budget_receipt(
            harness,
            receipt_id="br-readiness-x",
            node_id="source_finding",
            node_run_id="nr-run-test-source_finding-a1",
            estimate=250_000,
            status="settled",
            usage={"tokens": 130_000},
        )
        _insert_budget_receipt(
            harness,
            receipt_id="br-readiness-y",
            node_id="source_extraction",
            node_run_id="nr-run-test-source_extraction-a1",
            estimate=250_000,
            status="voided",
            usage={"tokens": 900_000},
        )
        _insert_budget_receipt(
            harness,
            receipt_id="br-readiness-z",
            node_id="evidence_relations",
            node_run_id="nr-run-test-evidence_relations-a1",
            estimate=250_000,
            status="settled",
            usage={"tokens": 130_000},
        )
        consumed, budget = _readiness_budget(harness)
        assert consumed["tokens"] == 260_000
        available, reason = budget.available()
        assert available is False
        assert reason == "stage_tokens_limit_reached"
    finally:
        harness.close()


def test_extend_budget_safety_limits_reopen_exhausted_readiness_window(
    tmp_path: Path,
) -> None:
    """T2: raising this run's own ceiling through extend_budget reopens the
    mid-run readiness gate, so retry is a real in-run exit instead of a
    permanent 412 with run abandonment as the only way out.  The frozen
    snapshot contract stays untouched (per-run, only-widen)."""
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        _write_snapshot(
            harness,
            {"stageBudgets": {"knowledge_collection": {"tokens": 250_000}}},
        )
        _insert_budget_receipt(
            harness,
            receipt_id="br-exit-x",
            node_id="source_finding",
            node_run_id="nr-run-test-source_finding-a1",
            estimate=250_000,
            status="settled",
            usage={"tokens": 130_000},
        )
        _insert_budget_receipt(
            harness,
            receipt_id="br-exit-y",
            node_id="evidence_relations",
            node_run_id="nr-run-test-evidence_relations-a1",
            estimate=250_000,
            status="settled",
            usage={"tokens": 130_000},
        )
        _, exhausted = _readiness_budget(harness)
        assert exhausted.available() == (False, "stage_tokens_limit_reached")

        # Exactly the payload extend_budget persists (only-widen, per run).
        _write_safety_limits(
            harness,
            {"stageTokens": {"knowledge_collection": 300_000}},
        )
        _, reopened = _readiness_budget(harness)
        assert reopened.available() == (True, "")

        # The frozen snapshot contract is untouched: the widening lives only
        # in the operator-owned safety-limits extension.
        row = harness.store.submit(
            lambda uow: uow.repository.get_run("run-test"),
            force_flush=True,
        ).result(timeout=10)
        assert json.loads(row.input_snapshot_json)["budgetPolicy"][
            "stageBudgets"
        ] == {"knowledge_collection": {"tokens": 250_000}}
    finally:
        harness.close()


def test_budget_authority_dual_reads_legacy_and_canonical_retry_fields() -> None:
    """T3: retry limits are dual-read — legacy snapshots carry ``autoRetries``
    while newer surfaces (and extend_budget) write ``maxRetries``; reading
    only one key silently dropped the other back to the default."""
    from core.web.services.team_workflow.research_runtime import (
        budget_authority_adapter,
    )
    from core.web.services.team_workflow.research_runtime.budget_contract import (
        DEFAULT_MAX_RETRIES,
    )

    legacy = budget_authority_adapter._policy_limits(
        {"budgetPolicy": {"tokens": FALLBACK_TOKENS, "autoRetries": 5}},
        "knowledge_collection",
    )
    assert legacy["retries"] == 5

    canonical = budget_authority_adapter._policy_limits(
        {
            "budgetPolicy": {
                "tokens": FALLBACK_TOKENS,
                "autoRetries": 5,
                "maxRetries": 1,
            }
        },
        "knowledge_collection",
    )
    assert canonical["retries"] == 1

    missing = budget_authority_adapter._policy_limits(
        {"budgetPolicy": {"tokens": FALLBACK_TOKENS}},
        "knowledge_collection",
    )
    assert missing["retries"] == DEFAULT_MAX_RETRIES

    # The operator extension accepts both spellings too (only-widen).
    legacy_override = budget_authority_adapter._policy_limits(
        {"budgetPolicy": {"tokens": FALLBACK_TOKENS}},
        "knowledge_collection",
        operator_limits={"autoRetries": 7},
    )
    assert legacy_override["retries"] == 7
    canonical_override = budget_authority_adapter._policy_limits(
        {"budgetPolicy": {"tokens": FALLBACK_TOKENS}},
        "knowledge_collection",
        operator_limits={"maxRetries": 4},
    )
    assert canonical_override["retries"] == 4


def test_readiness_snapshot_dual_reads_retry_vocabulary(tmp_path: Path) -> None:
    """T3: the readiness budget snapshot honors ``maxRetries`` snapshots, not
    just the legacy ``autoRetries`` key (and vice versa)."""
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        _write_snapshot(
            harness,
            {"stageBudgets": {"knowledge_collection": {"tokens": 250_000}}},
        )

        def _auto_retries() -> int:
            _, budget = _readiness_budget(harness)
            return budget.auto_retries

        assert _auto_retries() == 2  # default when neither key is present

        _write_snapshot(
            harness,
            {
                "maxRetries": 4,
                "stageBudgets": {"knowledge_collection": {"tokens": 250_000}},
            },
        )
        assert _auto_retries() == 4

        _write_snapshot(
            harness,
            {
                "autoRetries": 6,
                "stageBudgets": {"knowledge_collection": {"tokens": 250_000}},
            },
        )
        assert _auto_retries() == 6
    finally:
        harness.close()


# ------------------------------------------------- chain launch contract (T4)
# The hypothesis-first chain's ``create_formal_run`` freezes an explicit
# launch contract, and the budget authority treats an explicit contract as
# authoritative (budget_authority_adapter._policy_limits reads the frozen
# stageBudgets before any fallback).  That explicit contract must therefore
# be sourced from the shared budget contract (the 2M calibrated authority),
# never a copied literal: readiness compares run-cumulative settled usage
# against this frozen limit, and the old 250K copy false-rejected
# ``budget_safety_limit_reached`` after 1-2 real nodes (~294K each).


_CREATE_FORMAL_RUN_REQUEST = {
    "actionId": "create-formal-run-v2:round-accepted:1",
    "idempotencyKey": "hf2:create-formal-run:round-accepted:1",
    "expectedStateVersion": "hf2-action:converged-round",
    "command": "create_formal_run",
    "payload": {"hypothesisRoundId": "round-accepted"},
}


def _capture_formal_run_safety_limits(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> dict[str, object]:
    """Drive the real chain ``create_formal_run`` branch and capture the
    ``safety_limits`` the chain freezes into the run contract."""
    from core.research.workflow.definition import (
        build_challenge_cup_workflow_definition,
    )
    from core.research.workflow.definition_registry import definition_identity
    from core.web.services import team_service
    from core.web.services.team_workflow.research_runtime import (
        formal_read_runtime,
        hypothesis_first_chain,
        hypothesis_first_state_v2,
        run_creation,
        runtime_factory,
    )

    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    monkeypatch.setattr(hypothesis_first_chain, "PROJECT_ROOT", tmp_path)
    snapshot = {
        "stateVersion": "hf2-action:converged-round",
        "allowedActions": [
            {
                "kind": "command",
                "actionId": "create-formal-run-v2:round-accepted:1",
                "command": "create_formal_run",
                "payload": {"hypothesisRoundId": "round-accepted"},
                "enabled": True,
                "idempotencyKey": "hf2:create-formal-run:round-accepted:1",
            }
        ],
    }
    monkeypatch.setattr(
        hypothesis_first_state_v2,
        "project_hypothesis_first_state_v2",
        lambda *_args, **_kwargs: snapshot,
    )
    identity = definition_identity(build_challenge_cup_workflow_definition())
    captured: dict[str, object] = {}

    def _capture_create(*_args, **kwargs):
        captured.update(kwargs)
        return {
            "runId": "run-fresh",
            "workflowId": identity.workflowId,
            "workflowVersionId": identity.workflowVersionId,
            "structureHash": identity.structureHash,
            "teamId": "team-1",
            "questionId": "SCI-001",
            "status": "queued",
            "runVersion": 1,
        }

    monkeypatch.setattr(run_creation, "create_question_run", _capture_create)

    class Query:
        def get_snapshot(self, *, team_id: str, run_id: str):
            return {"commandOffers": []}

    monkeypatch.setattr(formal_read_runtime, "get_query_service", lambda: Query())
    monkeypatch.setattr(runtime_factory, "production_workflow_runtime", lambda: None)
    monkeypatch.setattr(
        hypothesis_first_chain,
        "_record_scene_event",
        lambda event_code, **kwargs: None,
    )
    return captured


def test_create_formal_run_freezes_budget_contract_stage_capacity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The explicit create_formal_run stageBudgets must equal the shared
    budget-contract capacity (2M authority), not a copied 250K literal."""
    from core.web.services.team_workflow.research_runtime import (
        hypothesis_first_chain,
    )
    from core.web.services.team_workflow.research_runtime.budget_contract import (
        DEFAULT_FORMAL_TOKEN_BUDGET,
        FORMAL_STAGE_IDS,
        default_safety_limits,
    )

    captured = _capture_formal_run_safety_limits(monkeypatch, tmp_path)
    result = hypothesis_first_chain.execute_v2_command(
        "team-1",
        dict(_CREATE_FORMAL_RUN_REQUEST),
        question_id="SCI-001",
    )

    assert result["result"]["runId"] == "run-fresh"
    limits = captured["safety_limits"]
    assert isinstance(limits, dict)
    assert set(limits["stageTokens"]) == set(FORMAL_STAGE_IDS)
    assert limits["stageTokens"] == default_safety_limits()["stageTokens"]
    assert limits["stageTokens"]["knowledge_collection"] == DEFAULT_FORMAL_TOKEN_BUDGET
    # Regression pin: the stale copied value must never come back.
    assert 250_000 not in limits["stageTokens"].values()


def test_readiness_chain_contract_admits_two_settled_real_nodes(
    tmp_path: Path,
) -> None:
    """With the chain-frozen contract in the snapshot, a run-cumulative
    ~588K settled sequence (two real nodes) must keep readiness available —
    the old 250K contract false-rejected at exactly this point."""
    from core.web.services.team_workflow.research_runtime.budget_contract import (
        DEFAULT_STAGE_TOKENS,
        FORMAL_STAGE_IDS,
    )

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        _write_snapshot(
            harness,
            {
                "stageBudgets": {
                    stage: {"tokens": DEFAULT_STAGE_TOKENS}
                    for stage in FORMAL_STAGE_IDS
                }
            },
        )
        _insert_budget_receipt(
            harness,
            receipt_id="br-chain-a",
            node_id="source_finding",
            node_run_id="nr-run-test-source_finding-a1",
            estimate=250_000,
            status="settled",
            usage={"tokens": REAL_NODE_USAGE},
        )
        _insert_budget_receipt(
            harness,
            receipt_id="br-chain-b",
            node_id="source_extraction",
            node_run_id="nr-run-test-source_extraction-a1",
            estimate=250_000,
            status="settled",
            usage={"tokens": REAL_NODE_USAGE},
        )
        consumed, budget = _readiness_budget(harness)
        assert consumed["tokens"] == 2 * REAL_NODE_USAGE
        # The sequence must exceed the old stale contract so this test
        # actually bites if the chain literal ever regresses to 250K.
        assert consumed["tokens"] > 250_000
        assert budget.available() == (True, "")
    finally:
        harness.close()
