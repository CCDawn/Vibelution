from __future__ import annotations

from copy import deepcopy
from typing import Any

from core.web.services.financial_backtest import runtime

_DATE = "2024-01-02"


class MemoryStore:
    def __init__(self, run: dict[str, Any]) -> None:
        self.run = deepcopy(run)

    def load_run(self, agent_id: str, run_id: str) -> dict[str, Any]:
        return deepcopy(self.run)

    def update_run(self, agent_id: str, run_id: str, mutator):
        result = mutator(self.run)
        return deepcopy(self.run), result

    def load_snapshot(self, agent_id: str, data_hash: str) -> dict[str, Any]:
        return {}

    def acquire_runner_lease(self, *args: Any, **kwargs: Any) -> bool:
        return True

    def release_runner_lease(self, *args: Any, **kwargs: Any) -> None:
        return None


def _run(**updates: Any) -> dict[str, Any]:
    return {
        "agentId": "finance-agent",
        "runId": "run-1",
        "status": "running",
        "decisionSchedule": [_DATE],
        "decisionCount": 1,
        "completedDecisionCount": 0,
        "callsUsed": 0,
        "decisions": [],
        "params": {"maxPositionPct": 100},
        "modelId": "model-1",
        "maxTokens": 1_000,
        "budgetTokensCommitted": 0,
        "reservationPlan": {_DATE: 100},
        "dataHash": "a" * 64,
        "progress": 0,
        "uncertainDecisionDate": None,
        "decisionSubmission": None,
        **updates,
    }


def _worker(store: MemoryStore, decision_runner=None) -> runtime.FinancialBacktestWorker:
    return runtime.FinancialBacktestWorker(
        store=store,
        assistant_loader=lambda: ["finance-agent"],
        decision_runner=decision_runner or (lambda **kwargs: {}),
        worker_id="worker-1",
    )


def test_unknown_attempt_commits_its_frozen_reservation_once(monkeypatch):
    monkeypatch.setattr(runtime, "_sync_runtime_task", lambda *args, **kwargs: None)
    store = MemoryStore(
        _run(
            decisionSubmission={
                "status": "submitting",
                "date": _DATE,
                "attemptId": "attempt-1",
                "workerId": "worker-1",
                "estimatedTokens": 100,
            }
        )
    )
    worker = _worker(store)

    worker._mark_unknown(
        "finance-agent",
        "run-1",
        _DATE,
        "provider_timeout",
        expected_attempt_id="attempt-1",
    )

    assert store.run["status"] == "paused_unknown"
    assert store.run["budgetTokensCommitted"] == 100
    assert store.run["decisionSubmission"]["budgetReservationCommitted"] is True

    worker._mark_unknown(
        "finance-agent",
        "run-1",
        _DATE,
        "duplicate_recovery",
        expected_attempt_id="attempt-1",
    )
    assert store.run["budgetTokensCommitted"] == 100


def test_unknown_retry_keeps_both_attempt_reservations_in_hard_budget(monkeypatch):
    monkeypatch.setattr(runtime, "_sync_runtime_task", lambda *args, **kwargs: None)
    store = MemoryStore(
        _run(
            maxTokens=250,
            budgetTokensCommitted=100,
            uncertainDecisionDate=_DATE,
            resumeUnknownDecisionDate=_DATE,
            decisionSubmission={
                "status": "unknown",
                "date": _DATE,
                "attempt": 1,
                "attemptId": "attempt-1",
                "estimatedTokens": 100,
                "budgetReservationCommitted": True,
            },
        )
    )
    worker = _worker(store)

    retry_id = worker._mark_submitting(
        "finance-agent",
        "run-1",
        decision_date=_DATE,
        input_hash="input-hash",
        attempt=2,
        estimated_tokens=100,
        started_at="2024-01-03T00:00:00Z",
    )

    assert retry_id
    assert store.run["budgetTokensCommitted"] == 200
    assert store.run["decisionSubmission"]["attempt"] == 2

    worker._mark_unknown(
        "finance-agent",
        "run-1",
        _DATE,
        "retry_timeout",
        expected_attempt_id=retry_id,
    )
    assert store.run["budgetTokensCommitted"] == 200


def test_unknown_retry_is_blocked_when_old_and_new_reservations_exceed_budget(monkeypatch):
    monkeypatch.setattr(runtime, "_sync_runtime_task", lambda *args, **kwargs: None)
    store = MemoryStore(
        _run(
            maxTokens=199,
            budgetTokensCommitted=100,
            uncertainDecisionDate=_DATE,
            resumeUnknownDecisionDate=_DATE,
            decisionSubmission={
                "status": "unknown",
                "date": _DATE,
                "attempt": 1,
                "attemptId": "attempt-1",
                "estimatedTokens": 100,
                "budgetReservationCommitted": True,
            },
        )
    )
    worker = _worker(store)

    retry_id = worker._mark_submitting(
        "finance-agent",
        "run-1",
        decision_date=_DATE,
        input_hash="input-hash",
        attempt=2,
        estimated_tokens=100,
        started_at="2024-01-03T00:00:00Z",
    )

    assert retry_id == ""
    assert store.run["status"] == "blocked"
    assert store.run["budgetTokensCommitted"] == 100


def test_legacy_unknown_attempt_is_charged_before_retry_budget_check(monkeypatch):
    monkeypatch.setattr(runtime, "_sync_runtime_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(runtime, "_record_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(runtime, "_restore_snapshot", lambda payload: object())
    monkeypatch.setattr(runtime.engine, "portfolio_at", lambda *args, **kwargs: {})
    monkeypatch.setattr(runtime, "build_decision_input", lambda *args, **kwargs: {"asOfDate": _DATE})
    monkeypatch.setattr(runtime, "build_messages", lambda value: [])
    monkeypatch.setattr(runtime, "reserve_decision_call", lambda messages: 100)
    store = MemoryStore(
        _run(
            status="queued",
            maxTokens=150,
            budgetTokensCommitted=0,
            uncertainDecisionDate=_DATE,
            resumeUnknownDecisionDate=_DATE,
            decisionSubmission={
                "status": "unknown",
                "date": _DATE,
                "attempt": 1,
                "attemptId": "legacy-attempt",
                "estimatedTokens": 100,
            },
        )
    )
    calls: list[dict[str, Any]] = []
    worker = _worker(store, decision_runner=lambda **kwargs: calls.append(kwargs) or {})
    monkeypatch.setattr(worker, "_validate_frozen_model", lambda *args, **kwargs: None)
    original_commit_unknown = worker._commit_legacy_unknown_reservation
    migrated: list[bool] = []

    def capture_migration(agent_id: str, run_id: str, run: dict[str, Any]) -> None:
        original_commit_unknown(agent_id, run_id, run)
        migrated.append(store.run["decisionSubmission"]["budgetReservationCommitted"])

    monkeypatch.setattr(worker, "_commit_legacy_unknown_reservation", capture_migration)

    worker._process_run("finance-agent", "run-1", should_stop=lambda: False)

    assert store.run["budgetTokensCommitted"] == 100
    assert migrated == [True]
    assert store.run["status"] == "blocked"
    assert calls == []


def test_measured_retry_replaces_only_its_own_reservation(monkeypatch):
    monkeypatch.setattr(runtime, "_sync_runtime_task", lambda *args, **kwargs: None)
    store = MemoryStore(
        _run(
            budgetTokensCommitted=200,
            decisions=[],
            decisionSubmission={
                "status": "submitting",
                "date": _DATE,
                "attempt": 2,
                "attemptId": "attempt-2",
                "workerId": "worker-1",
                "estimatedTokens": 100,
                "budgetReservationCommitted": True,
            },
        )
    )
    worker = _worker(store)

    accepted = worker._accept_decision(
        "finance-agent",
        "run-1",
        {
            "date": _DATE,
            "targetWeight": 50,
            "reason": "测试",
            "modelId": "model-1",
            "inputHash": "input-hash",
            "decisionHash": "decision-hash",
            "tokens": 60,
            "tokenAccounting": "measured",
        },
        attempt=2,
        attempt_id="attempt-2",
    )

    assert accepted is True
    assert store.run["budgetTokensCommitted"] == 160


def test_stop_racing_with_submission_never_calls_the_model(monkeypatch):
    monkeypatch.setattr(runtime, "_sync_runtime_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(runtime, "_record_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(runtime, "_restore_snapshot", lambda payload: object())
    monkeypatch.setattr(runtime.engine, "portfolio_at", lambda *args, **kwargs: {})
    monkeypatch.setattr(runtime, "build_decision_input", lambda *args, **kwargs: {"asOfDate": _DATE})
    monkeypatch.setattr(runtime, "build_messages", lambda value: [])
    monkeypatch.setattr(runtime, "reserve_decision_call", lambda messages: 100)
    store = MemoryStore(_run())
    calls: list[dict[str, Any]] = []
    worker = _worker(store, decision_runner=lambda **kwargs: calls.append(kwargs) or {})
    monkeypatch.setattr(worker, "_validate_frozen_model", lambda *args, **kwargs: None)
    original_mark_submitting = worker._mark_submitting

    def stop_before_marker(agent_id: str, run_id: str, **fields: Any) -> str:
        store.run["status"] = "stop_requested"
        return original_mark_submitting(agent_id, run_id, **fields)

    monkeypatch.setattr(worker, "_mark_submitting", stop_before_marker)

    worker._process_run("finance-agent", "run-1", should_stop=lambda: False)

    assert calls == []
    assert store.run["status"] == "stopped"
    assert store.run["callsUsed"] == 0
    assert store.run["budgetTokensCommitted"] == 0


def test_worker_does_not_call_model_after_lease_renewal_fails(monkeypatch):
    monkeypatch.setattr(runtime, "_sync_runtime_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(runtime, "_record_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(runtime, "_restore_snapshot", lambda payload: object())
    monkeypatch.setattr(runtime.engine, "portfolio_at", lambda *args, **kwargs: {})
    monkeypatch.setattr(runtime, "build_decision_input", lambda *args, **kwargs: {"asOfDate": _DATE})
    monkeypatch.setattr(runtime, "build_messages", lambda value: [])
    monkeypatch.setattr(runtime, "reserve_decision_call", lambda messages: 100)

    class LeaseLostStore(MemoryStore):
        def acquire_runner_lease(self, *args: Any, **kwargs: Any) -> bool:
            return False

    store = LeaseLostStore(_run())
    calls: list[dict[str, Any]] = []
    worker = _worker(store, decision_runner=lambda **kwargs: calls.append(kwargs) or {})
    monkeypatch.setattr(worker, "_validate_frozen_model", lambda *args, **kwargs: None)

    worker._process_run("finance-agent", "run-1", should_stop=lambda: False)

    assert calls == []
    assert store.run["decisionSubmission"]["status"] == "submitting"
    assert store.run["budgetTokensCommitted"] == 100


def test_model_fingerprint_is_rechecked_for_every_decision_submission(monkeypatch):
    second_date = "2024-01-03"
    monkeypatch.setattr(runtime, "_sync_runtime_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(runtime, "_record_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(runtime, "_restore_snapshot", lambda payload: object())
    monkeypatch.setattr(runtime.engine, "portfolio_at", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        runtime,
        "build_decision_input",
        lambda snapshot, params, *, as_of_date, portfolio: {"asOfDate": as_of_date},
    )
    monkeypatch.setattr(runtime, "build_messages", lambda value: [])
    monkeypatch.setattr(runtime, "reserve_decision_call", lambda messages: 100)
    monkeypatch.setattr(
        runtime.engine,
        "simulate",
        lambda *args, **kwargs: {
            "metrics": {},
            "equity": [],
            "trades": [],
            "orders": [],
            "benchmarkOrders": [],
        },
    )
    store = MemoryStore(
        _run(
            decisionSchedule=[_DATE, second_date],
            decisionCount=2,
            maxTokens=500,
            reservationPlan={_DATE: 100, second_date: 100},
        )
    )
    checked: list[str] = []
    decisions: list[str] = []

    def decision_runner(**kwargs: Any) -> dict[str, Any]:
        decision_input = kwargs["decision_input"]
        decision_date = str(decision_input["asOfDate"])
        decisions.append(decision_date)
        return {
            "date": decision_date,
            "targetWeight": 0,
            "reason": "测试",
            "modelId": "model-1",
            "inputHash": runtime.sha256_json(decision_input),
            "decisionHash": f"hash-{decision_date}",
            "tokens": 10,
            "tokenAccounting": "measured",
        }

    worker = _worker(store, decision_runner=decision_runner)
    monkeypatch.setattr(worker, "_validate_frozen_model", lambda *args, **kwargs: checked.append("checked"))

    worker._process_run("finance-agent", "run-1", should_stop=lambda: False)

    assert decisions == [_DATE, second_date]
    assert len(checked) == 3  # one run-start check and one check before each chargeable call
    assert store.run["status"] == "completed"


def test_fail_known_state_attempt_fence_preserves_a_newer_submission(monkeypatch):
    monkeypatch.setattr(runtime, "_sync_runtime_task", lambda *args, **kwargs: None)
    initial = _run(
        decisionSubmission={
            "status": "submitting",
            "date": _DATE,
            "attemptId": "stale-attempt",
            "workerId": "worker-1",
            "estimatedTokens": 100,
        }
    )

    class SwapAfterReadStore(MemoryStore):
        def load_run(self, agent_id: str, run_id: str) -> dict[str, Any]:
            snapshot = deepcopy(self.run)
            self.run["decisionSubmission"] = {
                "status": "submitting",
                "date": _DATE,
                "attemptId": "new-attempt",
                "workerId": "worker-2",
                "estimatedTokens": 100,
            }
            return snapshot

    store = SwapAfterReadStore(initial)
    worker = _worker(store)

    worker._fail_known_state("finance-agent", "run-1", "worker_crash")

    assert store.run["status"] == "running"
    assert store.run["decisionSubmission"]["attemptId"] == "new-attempt"
    assert store.run["budgetTokensCommitted"] == 0


def test_stale_decision_result_is_discarded_by_attempt_fence(monkeypatch):
    monkeypatch.setattr(runtime, "_sync_runtime_task", lambda *args, **kwargs: None)
    store = MemoryStore(
        _run(
            decisionSubmission={
                "status": "submitting",
                "date": _DATE,
                "attemptId": "new-attempt",
                "workerId": "worker-1",
                "estimatedTokens": 100,
                "budgetReservationCommitted": True,
            }
        )
    )
    worker = _worker(store)

    accepted = worker._accept_decision(
        "finance-agent",
        "run-1",
        {
            "date": _DATE,
            "targetWeight": 50,
            "reason": "旧结果",
            "modelId": "model-1",
            "inputHash": "input-hash",
            "decisionHash": "decision-hash",
            "tokens": 60,
            "tokenAccounting": "measured",
        },
        attempt=1,
        attempt_id="stale-attempt",
    )

    assert accepted is False
    assert store.run["decisions"] == []
    assert store.run["decisionSubmission"]["attemptId"] == "new-attempt"


def test_completed_run_persists_benchmark_orders(monkeypatch):
    monkeypatch.setattr(runtime, "_sync_runtime_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(runtime, "_record_event", lambda *args, **kwargs: None)
    benchmark_orders = [{"date": "2024-01-03", "status": "filled", "side": "buy"}]
    monkeypatch.setattr(
        runtime.engine,
        "simulate",
        lambda *args, **kwargs: {
            "metrics": {"totalReturnPct": 1},
            "equity": [],
            "trades": [],
            "orders": [],
            "benchmarkOrders": benchmark_orders,
        },
    )
    store = MemoryStore(
        _run(
            decisionSchedule=[_DATE],
            decisions=[{"date": _DATE, "targetWeight": 50, "reason": "测试", "inputHash": "hash"}],
        )
    )
    worker = _worker(store)

    worker._complete_run("finance-agent", "run-1", object(), {})

    assert store.run["status"] == "completed"
    assert store.run["benchmarkOrders"] == benchmark_orders
