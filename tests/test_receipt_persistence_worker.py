from __future__ import annotations

import json
from pathlib import Path

from core.research.workflow.contracts.model_invocation_receipt import (
    ModelInvocationReceipt,
)
from core.research.workflow.ledger import outbox as outbox_api
from core.web.services.team_workflow.research_runtime import (
    model_invocation_receipt_registry as registry,
)
from core.web.services.team_workflow.research_runtime.budget_authority_adapter import (
    read_node_budget_window,
)
from core.web.services.team_workflow.research_runtime.receipt_persistence import (
    MAX_RECEIPT_PERSISTENCE_LEASE_ATTEMPTS,
    RECEIPT_PERSISTENCE_IDEMPOTENCY_PREFIX,
    ReceiptPersistenceWorker,
    enqueue_question_model_invocation_receipt,
)
from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import (
    FIXED_NOW_MS,
    build_attempt_record,
    build_command_record,
)


def _receipt() -> dict:
    scope = {
        "questionId": "SCI-096",
        "workflowRunId": "run-test",
        "sessionId": "session-1",
        "taskId": "task-1",
        "turnId": "turn-1",
        "formalNodeId": "source_finding",
        "formalNodeRunId": "node-run-1",
        "modelPolicySha256": "a" * 64,
    }
    return ModelInvocationReceipt.from_invocation(
        receipt_id="receipt-1",
        run_id="run-test",
        node_run_id="node-run-1",
        scope=scope,
        provider="relay_autodl",
        model="GLM-5.3-flash",
        requested_model="GLM-5.3-flash",
        request_content={"kind": "bounded"},
        response_content={"kind": "bounded"},
        started_at_ms=100,
        finished_at_ms=120,
        token_usage={
            "inputTokens": 10,
            "cachedInputTokens": 4,
            "outputTokens": 5,
            "totalTokens": 15,
            "reasoningTokens": 3,
        },
        metadata={"outcomeKinds": ["candidate"]},
        evidence_locator={
            **scope,
            "kind": "session_output",
            "outputRef": "session:session-1/turn:turn-1",
            "outputSha256": "b" * 64,
            "receiptId": "receipt-1",
            "invocationId": "invocation-1",
            "attempt": 1,
        },
    ).to_dict()


def _outbox_row(harness: CommandHarness):
    return harness.store.read(
        lambda repo: repo.execute(
            "SELECT action_id, status, lease_owner, payload_json, attempt_count, "
            "last_problem_json "
            "FROM outbox_actions WHERE SUBSTR(idempotency_key, 1, ?) = ?",
            (
                len(RECEIPT_PERSISTENCE_IDEMPOTENCY_PREFIX),
                RECEIPT_PERSISTENCE_IDEMPOTENCY_PREFIX,
            ),
        ).fetchone()
    )


def _seed_budget_receipt(harness: CommandHarness) -> None:
    def mutate(uow):
        uow.repository.insert_command(build_command_record())
        uow.repository.insert_attempt(
            build_attempt_record(node_run_id="node-run-1")
        )
        uow.repository.insert_budget_receipt(
            receipt_id="budget-receipt-1",
            run_id="run-test",
            node_run_id="node-run-1",
            reservation_id="reservation-node-run-1",
            stage_id="knowledge_collection",
            policy_hash="policy-1",
            reserved_json=json.dumps(
                {"reserved": {"estimatedTokens": 25_000, "tokens": 25_000}}
            ),
            created_at_ms=FIXED_NOW_MS,
        )

    harness.store.submit(
        mutate,
        force_flush=True,
    ).result(timeout=5)


def test_receipt_intent_and_budget_usage_commit_exactly_once(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        _seed_budget_receipt(harness)

        first = enqueue_question_model_invocation_receipt(
            harness.store,
            team_id="research-team",
            question_id="SCI-096",
            workflow_run_id="run-test",
            receipt=_receipt(),
            now_ms=FIXED_NOW_MS,
        )
        second = enqueue_question_model_invocation_receipt(
            harness.store,
            team_id="research-team",
            question_id="SCI-096",
            workflow_run_id="run-test",
            receipt=_receipt(),
            now_ms=FIXED_NOW_MS + 1,
        )

        window = read_node_budget_window(
            harness.store,
            "run-test",
            "node-run-1",
            "reservation-node-run-1",
        )
        settled = harness.store.read(
            lambda repo: repo.execute(
                "SELECT settled_json FROM budget_receipts WHERE reservation_id = ?",
                ("reservation-node-run-1",),
            ).fetchone()
        )
        settled_payload = json.loads(settled[0])
        assert first["created"] is True
        assert second["created"] is False
        assert window["used"] == 15
        assert window["remaining"] == 24_985
        assert settled_payload["usage"]["reasoningTokens"] == 3
        assert settled_payload["usage"]["cachedInputTokens"] == 4
        assert settled_payload["usage"]["uncachedInputTokens"] == 6
        assert settled_payload["usage"]["toolCalls"] == 1
        assert settled_payload["usage"]["wallClockSeconds"] == 1
        assert len(settled_payload["invocations"]) == 1
    finally:
        harness.close()


def test_registry_failure_survives_restart_and_replays_exactly_once(
    tmp_path: Path,
) -> None:
    ledger_path = tmp_path / "ledger.sqlite3"
    first = CommandHarness(ledger_path)
    try:
        first.seed_run()
        _seed_budget_receipt(first)
        enqueue_question_model_invocation_receipt(
            first.store,
            team_id="research-team",
            question_id="SCI-096",
            workflow_run_id="run-test",
            receipt=_receipt(),
            now_ms=FIXED_NOW_MS,
        )
        calls: list[str] = []

        def unavailable(*_args, **_kwargs):
            calls.append("failed")
            raise OSError("registry unavailable")

        worker = ReceiptPersistenceWorker(
            store=first.store,
            owner_id="receipt-worker-1",
            now_provider=lambda: FIXED_NOW_MS + 1_000,
            register_receipts=unavailable,
        )
        assert worker.run_once() == 1
        assert _outbox_row(first)[1] == "pending"
    finally:
        first.close()

    second = CommandHarness(ledger_path)
    try:
        registered: list[dict] = []

        def register(team_id, **kwargs):
            registered.append({"teamId": team_id, **kwargs})
            return []

        worker = ReceiptPersistenceWorker(
            store=second.store,
            owner_id="receipt-worker-2",
            now_provider=lambda: FIXED_NOW_MS + 3_000,
            register_receipts=register,
        )
        assert worker.run_once() == 1
        assert worker.run_once() == 0
        assert _outbox_row(second)[1] == "succeeded"
        assert calls == ["failed"]
        assert len(registered) == 1
        assert registered[0]["receipts"][0]["receiptId"] == "receipt-1"
    finally:
        second.close()


def test_stale_owner_cannot_write_receipt_after_lease_loss(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        _seed_budget_receipt(harness)
        enqueue_question_model_invocation_receipt(
            harness.store,
            team_id="research-team",
            question_id="SCI-096",
            workflow_run_id="run-test",
            receipt=_receipt(),
            now_ms=FIXED_NOW_MS,
        )
        leased = outbox_api.lease_ready_actions(
            harness.store,
            owner="current-owner",
            now_ms=FIXED_NOW_MS + 1_000,
            limit=1,
            action_kinds=("reconcile",),
            idempotency_prefix=RECEIPT_PERSISTENCE_IDEMPOTENCY_PREFIX,
        )
        assert len(leased) == 1
        registered: list[dict] = []
        worker = ReceiptPersistenceWorker(
            store=harness.store,
            owner_id="stale-owner",
            now_provider=lambda: FIXED_NOW_MS + 2_000,
            register_receipts=lambda *_args, **kwargs: registered.append(kwargs) or [],
        )

        worker._handle(leased[0])

        assert registered == []
        row = _outbox_row(harness)
        assert row[1] == "leased"
        assert row[2] == "current-owner"
    finally:
        harness.close()


def test_uncertain_registry_success_replays_without_duplicate_receipt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        registry,
        "resolve_team_program_root",
        lambda _team_id: tmp_path / "registry",
    )
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        _seed_budget_receipt(harness)
        enqueue_question_model_invocation_receipt(
            harness.store,
            team_id="research-team",
            question_id="SCI-096",
            workflow_run_id="run-test",
            receipt=_receipt(),
            now_ms=FIXED_NOW_MS,
        )
        register_calls = 0

        def register_then_report_uncertain(team_id, **kwargs):
            nonlocal register_calls
            register_calls += 1
            registry.register_question_model_invocation_receipts(team_id, **kwargs)
            raise OSError("registry write outcome was uncertain")

        first = ReceiptPersistenceWorker(
            store=harness.store,
            owner_id="receipt-worker-1",
            now_provider=lambda: FIXED_NOW_MS + 1_000,
            register_receipts=register_then_report_uncertain,
        )
        second = ReceiptPersistenceWorker(
            store=harness.store,
            owner_id="receipt-worker-2",
            now_provider=lambda: FIXED_NOW_MS + 3_000,
        )

        assert first.run_once() == 1
        assert _outbox_row(harness)[1] == "pending"
        assert second.run_once() == 1
        assert _outbox_row(harness)[1] == "succeeded"
        stored = registry.question_model_invocation_receipts(
            "research-team",
            question_id="SCI-096",
            workflow_run_id="run-test",
        )
        assert [item["receiptId"] for item in stored] == ["receipt-1"]
        assert register_calls == 1
    finally:
        harness.close()


def test_registry_io_does_not_hold_workflow_ledger_writer(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        _seed_budget_receipt(harness)
        enqueue_question_model_invocation_receipt(
            harness.store,
            team_id="research-team",
            question_id="SCI-096",
            workflow_run_id="run-test",
            receipt=_receipt(),
            now_ms=FIXED_NOW_MS,
        )

        def register_without_ledger_writer(_team_id, **_kwargs):
            # This submit can complete only when receipt registry I/O runs
            # outside the Ledger single-writer transaction.
            observed = harness.store.submit(
                lambda uow: uow.repository.get_run("run-test"),
                force_flush=False,
            ).result(timeout=2)
            assert observed is not None
            return []

        worker = ReceiptPersistenceWorker(
            store=harness.store,
            owner_id="receipt-worker",
            now_provider=lambda: FIXED_NOW_MS + 1_000,
            register_receipts=register_without_ledger_writer,
        )

        assert worker.run_once() == 1
        assert _outbox_row(harness)[1] == "succeeded"
    finally:
        harness.close()


def test_registry_retry_exhaustion_becomes_terminal_failed(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        _seed_budget_receipt(harness)
        enqueue_question_model_invocation_receipt(
            harness.store,
            team_id="research-team",
            question_id="SCI-096",
            workflow_run_id="run-test",
            receipt=_receipt(),
            now_ms=FIXED_NOW_MS,
        )
        clock = [FIXED_NOW_MS + 1_000]

        def unavailable(*_args, **_kwargs):
            raise OSError("registry unavailable")

        worker = ReceiptPersistenceWorker(
            store=harness.store,
            owner_id="receipt-worker",
            now_provider=lambda: clock[0],
            retry_delay_ms=1,
            register_receipts=unavailable,
        )

        for _attempt in range(MAX_RECEIPT_PERSISTENCE_LEASE_ATTEMPTS):
            assert worker.run_once() == 1
            clock[0] += 10_000

        row = _outbox_row(harness)
        assert row[1] == "failed"
        assert row[4] == MAX_RECEIPT_PERSISTENCE_LEASE_ATTEMPTS
        assert "challenge_receipt_persistence_attempts_exhausted" in str(row[5])
        assert worker.run_once() == 0
    finally:
        harness.close()
