"""T5.1-5 RED: real budget lifecycle + settle failure reconciliation.

reserve_budget must enforce remaining limits from the frozen policy and ledger
consumption. settle failures must raise (adapter worker records a finding),
never silently succeed.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from core.research.workflow.contracts import PendingAction
from core.research.workflow.models import ActorKind
from core.web.services.team_workflow.research_runtime.real_domain_ports import (
    RealDomainPorts,
)
from tests._support.command_helpers import CommandHarness


def _action(node_id: str = "source_finding") -> PendingAction:
    return PendingAction(
        action_id="act-budget",
        run_id="run-test",
        node_run_id=f"nr-run-test-{node_id}-a1",
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


_PROVIDER_USAGE = {
    "source": "canonical_turn_outcome",
    "provider": "autodl",
    "model": "GLM-5.3-flash",
    "inputTokens": 13_668,
    "outputTokens": 598,
    "totalTokens": 14_266,
}


@pytest.mark.parametrize(
    ("canonical_usage", "expected_usage"),
    [
        pytest.param(_PROVIDER_USAGE, _PROVIDER_USAGE, id="canonical"),
        pytest.param(None, {"estimate_tokens": 50_000}, id="estimate-fallback"),
    ],
)
def test_agent_adapter_settles_with_best_available_usage(
    canonical_usage: dict[str, object] | None,
    expected_usage: dict[str, object],
) -> None:
    from core.web.services.team_workflow.research_runtime.adapters.domain_adapters import (
        AgentActionAdapter,
    )
    from core.web.services.team_workflow.research_runtime.domain_ports import (
        AgentTaskHandle,
        AgentTurnResult,
        BindingResolution,
    )

    handle = AgentTaskHandle(
        session_id="session-budget",
        session_attempt=1,
        task_id="task-budget",
        turn_id="turn-budget",
    )

    class _Ports:
        def resolve_binding(self, _action):  # type: ignore[no-untyped-def]
            return BindingResolution(agent_id="agent-budget", role_key="source_finder")

        def reserve_budget(self, *, action, estimate_tokens):  # type: ignore[no-untyped-def]
            assert action == _action()
            assert estimate_tokens == 50_000
            return {"reservationId": "reservation-budget"}

        def create_agent_task(self, *, action):  # type: ignore[no-untyped-def]
            assert action == _action()
            return handle

        def execute_agent_turn(self, *, action, handle):  # type: ignore[no-untyped-def]
            assert action == _action()
            return AgentTurnResult(
                materialized_refs=(),
                handle=handle,
                usage=canonical_usage,
            )

    result = AgentActionAdapter(_Ports(), estimate_tokens=50_000).execute(_action())  # type: ignore[arg-type]

    assert result.usage == expected_usage


def test_reserve_persists_budget_receipt(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        action = _action()
        _seed_attempt(harness, action)
        ports = RealDomainPorts(harness.store)
        reservation = ports.reserve_budget(action=action, estimate_tokens=1000)
        assert reservation["status"] == "reserved"
        assert reservation["reservationId"]
        rows = harness.store.submit(
            lambda uow: uow.repository.execute(
                "SELECT reservation_id, status FROM budget_receipts "
                "WHERE reservation_id = ?",
                (reservation["reservationId"],),
            ).fetchone(),
            force_flush=True,
        ).result(timeout=10)
        assert rows is not None
        assert rows[0] == reservation["reservationId"]
        assert rows[1] == "reserved"
    finally:
        harness.close()


def test_reserve_blocks_when_token_limit_exhausted(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        first = _action()
        second = _action("source_extraction")
        second = replace(
            second,
            action_id="act-budget-2",
            node_run_id="nr-run-test-source_extraction-a2",
        )
        _seed_attempt(harness, first)
        _seed_attempt(harness, second)

        def shrink(uow):
            import json

            run = uow.repository.get_run("run-test")
            snap = json.loads(run.input_snapshot_json or "{}")
            snap["budgetPolicy"] = {
                "tokens": 500,
                "toolCalls": 300,
                "wallClockSeconds": 21600,
                "autoRetries": 2,
                "stageBudgets": {"knowledge_collection": {"tokens": 500}},
            }
            uow.repository.execute(
                "UPDATE workflow_runs SET input_snapshot_json = ? WHERE run_id = ?",
                (json.dumps(snap), "run-test"),
            )

        harness.store.submit(shrink, force_flush=True).result(timeout=10)
        ports = RealDomainPorts(harness.store)
        # The contract-derived estimate (stage budget 500) is admitted for the
        # first attempt, capped to the full stage capacity.
        reservation = ports.reserve_budget(action=first, estimate_tokens=25_000)
        assert reservation["reserved"]["estimatedTokens"] == 500
        # The stage is exhausted: the next attempt is rejected fail-closed.
        with pytest.raises(RuntimeError, match="budget|limit|exceed"):
            ports.reserve_budget(action=second, estimate_tokens=25_000)
    finally:
        harness.close()


def test_settle_updates_receipt_and_rejects_missing(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        action = _action()
        _seed_attempt(harness, action)
        ports = RealDomainPorts(harness.store)
        reservation = ports.reserve_budget(action=action, estimate_tokens=1000)
        ports.settle_budget(
            reservation=reservation,
            usage={"estimate_tokens": 1000, "tokens": 800},
        )
        row = harness.store.submit(
            lambda uow: uow.repository.execute(
                "SELECT status FROM budget_receipts WHERE reservation_id = ?",
                (reservation["reservationId"],),
            ).fetchone(),
            force_flush=True,
        ).result(timeout=10)
        assert row is not None and row[0] == "settled"

        with pytest.raises(RuntimeError, match="budget|settle|missing"):
            ports.settle_budget(
                reservation={"reservationId": "reservation-does-not-exist"},
                usage={"tokens": 1},
            )
    finally:
        harness.close()


def test_release_keeps_intentional_cancel_as_released(tmp_path: Path) -> None:
    from core.web.services.team_workflow.research_runtime.budget_authority_adapter import (
        release_budget_reservation,
    )

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        action = _action()
        _seed_attempt(harness, action)
        ports = RealDomainPorts(harness.store)
        reservation = ports.reserve_budget(action=action, estimate_tokens=1000)
        release_budget_reservation(harness.store, reservation, reason="user_cancel")
        row = harness.store.submit(
            lambda uow: uow.repository.execute(
                "SELECT status FROM budget_receipts WHERE reservation_id = ?",
                (reservation["reservationId"],),
            ).fetchone(),
            force_flush=True,
        ).result(timeout=10)
        assert row is not None and row[0] == "released"
    finally:
        harness.close()


def test_voided_status_exists_for_compensation(tmp_path: Path) -> None:
    from core.research.workflow.transitions import BudgetReceiptStatus
    from core.web.services.team_workflow.research_runtime.budget_authority_adapter import (
        void_budget_reservation,
    )

    assert BudgetReceiptStatus.VOIDED.value == "voided"

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        action = _action()
        _seed_attempt(harness, action)
        ports = RealDomainPorts(harness.store)
        reservation = ports.reserve_budget(action=action, estimate_tokens=1000)
        void_budget_reservation(
            harness.store,
            reservation,
            reason="execute_exception_compensation",
            correlation_id=action.action_id,
        )
        row = harness.store.submit(
            lambda uow: uow.repository.execute(
                "SELECT status, settled_json FROM budget_receipts WHERE reservation_id = ?",
                (reservation["reservationId"],),
            ).fetchone(),
            force_flush=True,
        ).result(timeout=10)
        assert row is not None
        assert row[0] == "voided"
        assert "execute_exception_compensation" in str(row[1] or "")
        assert action.action_id in str(row[1] or "")
    finally:
        harness.close()


def _seed_dispatching_outbox(harness: CommandHarness, action: PendingAction) -> None:
    import json

    from core.research.workflow.ledger import OutboxRecord
    from tests._support.workflow_ledger_helpers import (
        FIXED_NOW_MS,
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
                    started_at_ms=FIXED_NOW_MS,
                )
            )
        uow.repository.insert_outbox(
            OutboxRecord(
                action_id=f"adapter-outbox-{action.action_id}",
                run_id=action.run_id,
                command_id="cmd-budget",
                node_run_id=action.node_run_id,
                action_kind="adapter_dispatch",
                idempotency_key=f"adapter:{action.action_id}",
                payload_json=json.dumps(action.to_dict()),
                status="pending",
                attempt_count=0,
                available_at_ms=FIXED_NOW_MS,
                lease_owner=None,
                lease_expires_at_ms=None,
                last_problem_json=None,
                created_at_ms=FIXED_NOW_MS,
                updated_at_ms=FIXED_NOW_MS,
            )
        )

    harness.store.submit(mutate, force_flush=True).result(timeout=10)


def _budget_receipt_status(harness: CommandHarness, reservation_id: str) -> str | None:
    row = harness.store.submit(
        lambda uow: uow.repository.execute(
            "SELECT status FROM budget_receipts WHERE reservation_id = ?",
            (reservation_id,),
        ).fetchone(),
        force_flush=True,
    ).result(timeout=10)
    return None if row is None else str(row[0])


def test_worker_voids_reserved_receipt_when_execute_returns_failed(
    tmp_path: Path,
) -> None:
    from core.web.services.team_workflow.research_runtime.action_registry import (
        ActionRegistry,
        AdapterPreflight,
        AdapterResult,
        VerifiedDomainResult,
    )
    from core.web.services.team_workflow.research_runtime.adapter_dispatch_worker import (
        AdapterDispatchWorker,
    )

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        action = _action()
        _seed_dispatching_outbox(harness, action)
        ports = RealDomainPorts(harness.store)
        reservation_id = f"reservation-{action.node_run_id}"

        class _FailReturnAdapter:
            action_kind = "start_agent_task"

            def preflight(self, action: PendingAction) -> AdapterPreflight:
                return AdapterPreflight(ready=True)

            def execute(self, action: PendingAction) -> AdapterResult:
                ports.reserve_budget(action=action, estimate_tokens=1000)
                return AdapterResult(
                    action_id=action.action_id,
                    outcome="failed",
                    problem={"code": "injected_execute_failed"},
                )

            def verify(self, action: PendingAction, result: AdapterResult) -> VerifiedDomainResult:
                raise AssertionError("verify must not run after execute failure")

        registry = ActionRegistry()
        registry.register(_FailReturnAdapter())
        worker = AdapterDispatchWorker(
            store=harness.store,
            registry=registry,
            ports=ports,
            successor_fn=lambda _node: (),
        )
        worker.run_once()

        assert _budget_receipt_status(harness, reservation_id) == "voided"
        attempt = harness.store.latest_attempt(action.run_id, action.node_id)
        assert attempt is not None and attempt.status == "failed"
    finally:
        harness.close()


def test_worker_voids_reserved_receipt_on_challenge_deadline_exceeded(
    tmp_path: Path,
) -> None:
    """A fenced (deadline) attempt must not strand its reservation at `reserved`.

    run-cb9422dc4ad0: the ChallengeTaskDeadlineExceeded branch failed the
    attempt without the budget compensation void, so the 2M reserved estimate
    kept occupying the stage admission and every later retry of the same
    run+stage was rejected fail-closed with budget_safety_limit_reached.
    """
    from core.web.services.team_workflow.research_runtime.action_registry import (
        ActionRegistry,
        AdapterPreflight,
        AdapterResult,
    )
    from core.web.services.team_workflow.research_runtime.adapter_dispatch_worker import (
        AdapterDispatchWorker,
    )
    from core.web.services.team_workflow.research_runtime.challenge_turn_policy import (
        ChallengeTaskDeadlineExceeded,
    )

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        action = _action()
        _seed_dispatching_outbox(harness, action)
        ports = RealDomainPorts(harness.store)
        reservation_id = f"reservation-{action.node_run_id}"

        class _DeadlineRaiseAdapter:
            action_kind = "start_agent_task"

            def preflight(self, action: PendingAction) -> AdapterPreflight:
                return AdapterPreflight(ready=True)

            def execute(self, action: PendingAction) -> AdapterResult:
                # Real-incident magnitude: RealDomainPorts resolves the AGENT
                # contract estimate from the seeded run snapshot, whose
                # conservative fallback is 2M -- the reserved admission
                # estimate alone filled the whole default stage limit.
                ports.reserve_budget(action=action, estimate_tokens=2_000_000)
                raise ChallengeTaskDeadlineExceeded(
                    {
                        "code": "challenge_logical_task_deadline_exhausted",
                        "detail": "injected fence timeout",
                    }
                )

        registry = ActionRegistry()
        registry.register(_DeadlineRaiseAdapter())
        worker = AdapterDispatchWorker(
            store=harness.store,
            registry=registry,
            ports=ports,
            successor_fn=lambda _node: (),
        )
        worker.run_once()

        assert _budget_receipt_status(harness, reservation_id) == "voided"
        attempt = harness.store.latest_attempt(action.run_id, action.node_id)
        assert attempt is not None and attempt.status == "failed"

        # With the receipt voided, a later retry attempt of the same run+stage
        # is admissible again: before the fix this reserve was rejected
        # fail-closed with budget_safety_limit_reached because the stranded
        # reserved receipt still occupied its full 2M estimate.
        retry = replace(
            _action("source_extraction"),
            action_id="act-budget-retry",
            node_run_id="nr-run-test-source_extraction-a2",
        )
        _seed_attempt(harness, retry)
        retried = ports.reserve_budget(action=retry, estimate_tokens=17_000)
        assert retried["status"] == "reserved"
        assert retried["reserved"]["estimatedTokens"] == 2_000_000
    finally:
        harness.close()


def test_worker_voids_reserved_receipt_when_verify_raises(tmp_path: Path) -> None:
    from core.web.services.team_workflow.research_runtime.action_registry import (
        ActionRegistry,
        AdapterPreflight,
        AdapterResult,
        VerifiedDomainResult,
    )
    from core.web.services.team_workflow.research_runtime.adapter_dispatch_worker import (
        AdapterDispatchWorker,
    )

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        action = _action()
        _seed_dispatching_outbox(harness, action)
        ports = RealDomainPorts(harness.store)
        reservation_id = f"reservation-{action.node_run_id}"

        class _VerifyRaiseAdapter:
            action_kind = "start_agent_task"

            def preflight(self, action: PendingAction) -> AdapterPreflight:
                return AdapterPreflight(ready=True)

            def execute(self, action: PendingAction) -> AdapterResult:
                reservation = ports.reserve_budget(action=action, estimate_tokens=1000)
                return AdapterResult(
                    action_id=action.action_id,
                    outcome="succeeded",
                    reserved=dict(reservation),
                    usage={"tokens": 1},
                )

            def verify(self, action: PendingAction, result: AdapterResult) -> VerifiedDomainResult:
                raise RuntimeError("injected verify boom")

        registry = ActionRegistry()
        registry.register(_VerifyRaiseAdapter())
        worker = AdapterDispatchWorker(
            store=harness.store,
            registry=registry,
            ports=ports,
            successor_fn=lambda _node: (),
        )
        worker.run_once()

        assert _budget_receipt_status(harness, reservation_id) == "voided"
        attempt = harness.store.latest_attempt(action.run_id, action.node_id)
        assert attempt is not None and attempt.status == "failed"
    finally:
        harness.close()


def test_worker_voids_reserved_receipt_when_verify_returns_blocked(
    tmp_path: Path,
) -> None:
    from core.web.services.team_workflow.research_runtime.action_registry import (
        ActionRegistry,
        AdapterPreflight,
        AdapterResult,
        VerifiedDomainResult,
    )
    from core.web.services.team_workflow.research_runtime.adapter_dispatch_worker import (
        AdapterDispatchWorker,
    )

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        action = _action()
        _seed_dispatching_outbox(harness, action)
        ports = RealDomainPorts(harness.store)
        reservation_id = f"reservation-{action.node_run_id}"

        class _VerifyBlockedAdapter:
            action_kind = "start_agent_task"

            def preflight(self, action: PendingAction) -> AdapterPreflight:
                return AdapterPreflight(ready=True)

            def execute(self, action: PendingAction) -> AdapterResult:
                reservation = ports.reserve_budget(action=action, estimate_tokens=1000)
                return AdapterResult(
                    action_id=action.action_id,
                    outcome="succeeded",
                    reserved=dict(reservation),
                    usage={"tokens": 1},
                )

            def verify(self, action: PendingAction, result: AdapterResult) -> VerifiedDomainResult:
                return VerifiedDomainResult(
                    action_id=action.action_id,
                    outcome="blocked",
                    artifact_receipts=(),
                    anchor=None,
                    budget_receipt=None,
                    problem={"code": "injected_verify_blocked", "detail": "no receipt"},
                )

        registry = ActionRegistry()
        registry.register(_VerifyBlockedAdapter())
        worker = AdapterDispatchWorker(
            store=harness.store,
            registry=registry,
            ports=ports,
            successor_fn=lambda _node: (),
        )
        worker.run_once()

        assert _budget_receipt_status(harness, reservation_id) == "voided"
        attempt = harness.store.latest_attempt(action.run_id, action.node_id)
        assert attempt is not None and attempt.status == "blocked"
    finally:
        harness.close()


def test_settle_failure_marks_reconciliation_required(tmp_path: Path) -> None:
    from core.web.services.team_workflow.research_runtime.action_registry import (
        ActionRegistry,
    )
    from core.web.services.team_workflow.research_runtime.adapter_dispatch_worker import (
        AdapterDispatchWorker,
    )

    class _FailingSettlePorts(RealDomainPorts):
        def settle_budget(self, *, reservation, usage):  # type: ignore[no-untyped-def]
            raise RuntimeError("injected settle failure")

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(status="running")
        action = _action()
        _seed_attempt(harness, action)
        ports = _FailingSettlePorts(harness.store)
        reservation = ports.reserve_budget(action=action, estimate_tokens=1000)

        worker = AdapterDispatchWorker(
            store=harness.store,
            registry=ActionRegistry(),
            ports=ports,
            successor_fn=lambda _node: (),
        )
        outbox = type("Outbox", (), {"action_id": "outbox-budget-settle"})()
        worker._settle_domain_budget(
            outbox, action, reservation, {"tokens": 10}
        )

        assert worker.last_problem is not None
        assert worker.last_problem["code"] == "budget_settle_failed"

        run = harness.store.get_run(action.run_id)
        assert run is not None
        assert run.status == "reconciliation_required"
        assert "budget_settle_failed" in str(run.blocked_problem_json or "")

        attempt = harness.store.submit(
            lambda uow: uow.repository.get_attempt(action.node_run_id),
            force_flush=True,
        ).result(timeout=10)
        assert attempt is not None
        assert "budget_settle_failed" in str(attempt.problem_json or "")

        recovery = harness.store.submit(
            lambda uow: uow.repository.execute(
                "SELECT problem_code, status, evidence_json FROM recovery_records "
                "WHERE run_id = ? AND problem_code = 'budget_settle_failed'",
                (action.run_id,),
            ).fetchone(),
            force_flush=True,
        ).result(timeout=10)
        assert recovery is not None
        assert recovery[0] == "budget_settle_failed"
        assert recovery[1] == "open"
        assert action.node_run_id in str(recovery[2] or "")
    finally:
        harness.close()


def test_read_node_budget_window_uses_ledger_and_validates_binding(
    tmp_path: Path,
) -> None:
    from core.web.services.team_workflow.research_runtime.budget_authority_adapter import (
        BudgetAuthorityError,
        read_node_budget_window,
        record_budget_usage,
    )

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        action = _action()
        _seed_attempt(harness, action)
        ports = RealDomainPorts(harness.store)
        reservation = ports.reserve_budget(action=action, estimate_tokens=25_000)

        before = read_node_budget_window(
            harness.store,
            action.run_id,
            action.node_run_id,
            reservation["reservationId"],
        )
        assert before["reserved"] == 2_000_000
        assert before["used"] == 0
        assert before["remaining"] == 2_000_000
        assert before["stageLimit"] == 2_000_000
        assert before["status"] == "reserved"

        record_budget_usage(
            harness.store,
            run_id=action.run_id,
            node_run_id=action.node_run_id,
            reservation_id=reservation["reservationId"],
            invocation_id="inv-window-1",
            input_tokens=100,
            output_tokens=50,
            reasoning_tokens=20,
        )
        after = read_node_budget_window(
            harness.store,
            action.run_id,
            action.node_run_id,
            reservation["reservationId"],
        )
        assert after["used"] == 150
        assert after["remaining"] == 1_999_850

        with pytest.raises(BudgetAuthorityError, match="binding"):
            read_node_budget_window(
                harness.store,
                action.run_id,
                "node-run-does-not-match",
                reservation["reservationId"],
            )
    finally:
        harness.close()


def test_record_budget_usage_is_exactly_once_and_reasoning_is_not_double_counted(
    tmp_path: Path,
) -> None:
    from core.web.services.team_workflow.research_runtime.budget_authority_adapter import (
        read_node_budget_window,
        record_budget_usage,
    )

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        action = _action()
        _seed_attempt(harness, action)
        ports = RealDomainPorts(harness.store)
        reservation = ports.reserve_budget(action=action, estimate_tokens=1_000)
        kwargs = {
            "run_id": action.run_id,
            "node_run_id": action.node_run_id,
            "reservation_id": reservation["reservationId"],
            "invocation_id": "inv-exactly-once",
            "input_tokens": 100,
            "output_tokens": 50,
            "reasoning_tokens": 20,
        }
        first = record_budget_usage(harness.store, **kwargs)
        duplicate = record_budget_usage(harness.store, **kwargs)

        assert first["idempotent"] is False
        assert duplicate["idempotent"] is True
        window = read_node_budget_window(
            harness.store,
            action.run_id,
            action.node_run_id,
            reservation["reservationId"],
        )
        assert window["used"] == 150
        assert window["remaining"] == 1_999_850
        payload = harness.store.submit(
            lambda uow: uow.repository.execute(
                "SELECT settled_json FROM budget_receipts WHERE reservation_id = ?",
                (reservation["reservationId"],),
            ).fetchone(),
            force_flush=True,
        ).result(timeout=10)
        assert payload is not None
        settled = json.loads(payload[0])
        assert settled["usage"]["reasoningTokens"] == 20
        assert settled["usage"]["tokens"] == 150
        assert list(settled["invocations"]) == ["inv-exactly-once"]
    finally:
        harness.close()


def test_settle_merges_accumulated_usage_instead_of_overwriting_with_estimate(
    tmp_path: Path,
) -> None:
    from core.web.services.team_workflow.research_runtime.budget_authority_adapter import (
        read_node_budget_window,
        record_budget_usage,
        settle_budget_authority,
    )

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        action = _action()
        _seed_attempt(harness, action)
        ports = RealDomainPorts(harness.store)
        reservation = ports.reserve_budget(action=action, estimate_tokens=2_000)
        record_budget_usage(
            harness.store,
            run_id=action.run_id,
            node_run_id=action.node_run_id,
            reservation_id=reservation["reservationId"],
            invocation_id="inv-settle-1",
            input_tokens=300,
            output_tokens=200,
            reasoning_tokens=80,
        )

        settled = settle_budget_authority(
            harness.store,
            reservation={
                "reservationId": reservation["reservationId"],
                "runId": action.run_id,
                "nodeRunId": action.node_run_id,
            },
            usage={"tokens": 1_900, "usage_estimated": True},
        )
        assert settled["status"] == "settled"
        window = read_node_budget_window(
            harness.store,
            action.run_id,
            action.node_run_id,
            reservation["reservationId"],
        )
        assert window["status"] == "settled"
        assert window["used"] == 500
        assert window["remaining"] == 1_999_500
    finally:
        harness.close()


def test_finalize_cancelled_run_budgets_settles_usage_and_releases_unused(
    tmp_path: Path,
) -> None:
    from core.web.services.team_workflow.research_runtime.budget_authority_adapter import (
        finalize_cancelled_run_budget_receipts,
    )

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(run_id="run-cancel", status="cancelled")
        used_action = replace(
            _action(),
            action_id="act-used",
            run_id="run-cancel",
            node_run_id="nr-used",
        )
        unused_action = replace(
            _action("source_extraction"),
            action_id="act-unused",
            run_id="run-cancel",
            node_run_id="nr-unused",
        )
        _seed_attempt(harness, used_action)
        _seed_attempt(harness, unused_action)

        def seed(uow):
            for receipt_id, node_run_id in (
                ("br-used", "nr-used"),
                ("br-unused", "nr-unused"),
            ):
                uow.repository.insert_budget_receipt(
                    receipt_id=receipt_id,
                    run_id="run-cancel",
                    node_run_id=node_run_id,
                    reservation_id=f"reservation-{node_run_id}",
                    stage_id="execution_iteration",
                    policy_hash="policy-cancel",
                    reserved_json=json.dumps({"reserved": {"tokens": 1_000}}),
                    created_at_ms=1_750_000_000_000,
                )
            uow.repository.update_budget_receipt(
                "br-used",
                status="reserved",
                now_ms=1_750_000_000_001,
                settled_json=json.dumps(
                    {
                        "invocations": {
                            "inv-used": {
                                "inputTokens": 80,
                                "outputTokens": 20,
                                "tokens": 100,
                                "usageEstimated": False,
                            }
                        },
                        "usage": {
                            "inputTokens": 80,
                            "outputTokens": 20,
                            "tokens": 100,
                            "usageEstimated": False,
                        },
                    }
                ),
            )

        harness.store.submit(seed, force_flush=True).result(timeout=10)
        first = finalize_cancelled_run_budget_receipts(
            harness.store, "run-cancel", reason="operator_cancelled"
        )
        replay = finalize_cancelled_run_budget_receipts(
            harness.store, "run-cancel", reason="operator_cancelled"
        )
        rows = harness.store.read(
            lambda repo: repo.execute(
                "SELECT receipt_id, status, settled_json FROM budget_receipts "
                "WHERE run_id = ? ORDER BY receipt_id",
                ("run-cancel",),
            ).fetchall()
        )
    finally:
        harness.close()

    assert first == {"settled": 1, "released": 1}
    assert replay == {"settled": 0, "released": 0}
    by_id = {row[0]: (row[1], json.loads(row[2])) for row in rows}
    assert by_id["br-used"][0] == "settled"
    assert by_id["br-used"][1]["usage"]["tokens"] == 100
    assert by_id["br-unused"][0] == "released"
    assert by_id["br-unused"][1]["reason"] == "operator_cancelled"


def test_reserve_stage_admission_is_atomic_under_concurrency(tmp_path: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from core.web.services.team_workflow.research_runtime.budget_authority_adapter import (
        reserve_budget_authority,
    )

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        first = _action()
        second = _action("source_extraction")
        second = replace(
            second,
            action_id="act-budget-2",
            node_run_id="nr-run-test-source_extraction-a2",
        )
        _seed_attempt(harness, first)
        _seed_attempt(harness, second)
        snapshot = {
            "budgetPolicy": {
                "stageBudgets": {"knowledge_collection": {"tokens": 500}}
            }
        }

        def reserve(action: PendingAction):
            return reserve_budget_authority(
                harness.store,
                action=action,
                estimate_tokens=400,
                input_snapshot=snapshot,
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = [pool.submit(reserve, action) for action in (first, second)]
            results = [future.result() for future in outcomes]

        # Under the capacity-capped admission contract both concurrent
        # reservations are admitted, but the second is capped to the stage's
        # remaining capacity: the aggregate can never exceed the frozen stage
        # limit (400 + capped 100 = 500).
        assert all(result["status"] == "reserved" for result in results)
        assert sum(result["reserved"]["estimatedTokens"] for result in results) <= 500
    finally:
        rows = harness.store.submit(
            lambda uow: uow.repository.execute(
                "SELECT reserved_json FROM budget_receipts WHERE run_id = ? AND stage_id = ?",
                ("run-test", "knowledge_collection"),
            ).fetchall(),
            force_flush=True,
        ).result(timeout=10)
        assert len(rows) == 2
        total = sum(json.loads(row[0])["reserved"]["estimatedTokens"] for row in rows)
        assert total <= 500
        harness.close()
