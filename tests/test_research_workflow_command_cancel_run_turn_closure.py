"""cancel_run closes in-flight chat turns bound to a cancelled research run.

Regression coverage: cancel_run used to only move the ledger run to
``cancelled`` and never stopped the in-flight session turns, so
``work_runs/chat_turn`` snapshots stayed ``running`` with a pinned
``index.activeRunId`` and the desktop active-work guard blocked restart/stop
until the 30-minute projection reconciler ran.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from core.research.workflow.contracts import WorkflowCommandKind
from core.runtime_manager import work_run_store as work_run_store_module
from core.web.services import session_service
from core.web.services.team_workflow.research_runtime.cancel_run_cleanup import (
    CancelRunCleanupWorker,
    build_cancel_run_cleanup_record,
)
from core.web.services.team_workflow.research_runtime.store import WorkflowRunStore
from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import (
    build_attempt_record,
    build_command_record,
    build_outbox_record,
    open_ledger_store,
)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


@pytest.fixture()
def file_run_store(tmp_path, monkeypatch) -> WorkflowRunStore:
    """Point the JSON run-record store used by cancel_run closure at tmp."""
    root = tmp_path / "run_store"
    monkeypatch.setenv("VIBELUTION_RESEARCH_WORKFLOW_RUN_STORE", str(root))
    return WorkflowRunStore()


def _seed_file_run(
    store: WorkflowRunStore,
    run_id: str = "run-cancel",
    *,
    subtasks: list[dict[str, Any]] | None = None,
    binding_snapshots: list[dict[str, Any]] | None = None,
) -> None:
    store.create_run(
        {
            "runId": run_id,
            "workflowId": "challenge-cup",
            "status": "running",
            "taskBundles": [
                {
                    "bundleId": "bundle-1",
                    "status": "running",
                    "subtasks": subtasks
                    or [
                        {
                            "subtaskId": "st-1",
                            "status": "running",
                            "sessionId": "session-a",
                            "turnId": "turn-a",
                        },
                        {
                            "subtaskId": "st-2",
                            "status": "succeeded",
                            "sessionId": "session-b",
                            "turnId": "turn-b",
                        },
                    ],
                }
            ],
            "bindingSnapshots": binding_snapshots
            or [
                {
                    "snapshotId": "snap-1",
                    "sessionId": "session-a",
                    "taskId": "task-1",
                    "turnId": "turn-d",
                }
            ],
            "nodeRuns": [],
            "events": [],
            "commandReceipts": [],
        }
    )


def _submit_cancel(harness: CommandHarness, *, idempotency_key: str, run_id: str = "run-cancel"):
    return harness.service.submit(
        harness.request(
            command=WorkflowCommandKind.CANCEL_RUN,
            node_id=None,
            run_id=run_id,
            idempotency_key=idempotency_key,
            payload={"reason": "operator cancelled"},
        )
    )


def _seed_budget_receipt(
    harness: CommandHarness,
    *,
    run_id: str = "run-cancel",
    receipt_id: str = "br-cancel",
    settled: dict[str, Any] | None = None,
) -> None:
    def mutate(uow):
        command_id = f"cmd-budget-{run_id}"
        node_run_id = f"nr-{run_id}-problem_understanding-a1"
        if uow.repository.get_command(command_id) is None:
            uow.repository.insert_command(
                build_command_record(
                    command_id=command_id,
                    run_id=run_id,
                    idempotency_key=f"budget:{run_id}",
                )
            )
        if uow.repository.get_attempt(node_run_id) is None:
            uow.repository.insert_attempt(
                build_attempt_record(
                    node_run_id,
                    run_id=run_id,
                    node_id="problem_understanding",
                    status="running",
                    command_id=command_id,
                )
            )
        uow.repository.insert_budget_receipt(
            receipt_id=receipt_id,
            run_id=run_id,
            node_run_id=node_run_id,
            reservation_id=f"reservation-{node_run_id}",
            stage_id="execution_iteration",
            policy_hash="policy-cancel",
            reserved_json=json.dumps(
                {"reserved": {"tokens": 50_000}, "limits": {"tokens": 50_000}}
            ),
            created_at_ms=1_750_000_000_000,
        )
        if settled is not None:
            uow.repository.update_budget_receipt(
                receipt_id,
                status="reserved",
                now_ms=1_750_000_000_001,
                settled_json=json.dumps(settled),
            )

    harness.store.submit(mutate, force_flush=True).result(timeout=10)


class _FakeWorkRunStore:
    """Dict-backed stand-in for session_service._WORK_RUN_STORE."""

    def __init__(self, snapshots: dict[str, dict[str, Any]] | None = None) -> None:
        self._snapshots = dict(snapshots or {})

    def load_snapshot(self, run_kind: str, run_id: str) -> dict[str, Any] | None:
        assert run_kind == "chat_turn"
        return self._snapshots.get(str(run_id))


def test_cancel_run_stops_inflight_turns_and_skips_terminal_ones(
    tmp_path, monkeypatch, file_run_store
):
    """(a) In-flight subtask turns are stopped; terminal subtasks and turns
    with a terminal chat_turn snapshot are never touched."""
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    fake_store = _FakeWorkRunStore(
        {
            # Binding turn already finished normally: closure must skip it.
            "turn-d": {
                "runId": "turn-d",
                "sessionId": "session-a",
                "status": "completed",
                "finishedAt": _iso(datetime.now(timezone.utc)),
            }
        }
    )
    monkeypatch.setattr(session_service, "_WORK_RUN_STORE", fake_store)
    monkeypatch.setattr(session_service, "_is_session_running", lambda session_id: True)

    stops: list[tuple[str, str]] = []

    def fake_stop(session_id: str, *, expected_turn_id: str = "") -> dict[str, Any]:
        stops.append((session_id, expected_turn_id))
        return {"id": session_id}

    monkeypatch.setattr(session_service, "request_stop_session_turn", fake_stop)
    persisted: list[dict[str, Any]] = []
    monkeypatch.setattr(
        session_service,
        "_persist_chat_turn_work_run",
        lambda **kwargs: persisted.append(kwargs),
    )

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(run_id="run-cancel", status="running")
        _seed_file_run(file_run_store)
        receipt = _submit_cancel(harness, idempotency_key="cancel-key-1")
        run = harness.store.get_run("run-cancel")
    finally:
        harness.close()

    assert receipt.status == "accepted"
    # Running subtask (turn-a) stopped; succeeded subtask (turn-b) skipped;
    # binding turn-d skipped via its terminal snapshot.
    assert stops == [("session-a", "turn-a")]
    assert persisted == []
    assert run is not None
    assert run.status == "cancelled"


def test_cancel_run_side_effect_failure_keeps_command_accepted(
    tmp_path, monkeypatch, file_run_store
):
    """(b) A failing stop side effect must not fail the cancel command."""
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_WORK_RUN_STORE", _FakeWorkRunStore())
    monkeypatch.setattr(session_service, "_is_session_running", lambda session_id: True)

    def failing_stop(session_id: str, *, expected_turn_id: str = "") -> dict[str, Any]:
        raise RuntimeError("simulated stop failure")

    monkeypatch.setattr(session_service, "request_stop_session_turn", failing_stop)

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(run_id="run-cancel", status="running")
        _seed_file_run(file_run_store)
        receipt = _submit_cancel(harness, idempotency_key="cancel-key-1")
        run = harness.store.get_run("run-cancel")
    finally:
        harness.close()

    assert receipt.status == "accepted"
    assert run is not None
    assert run.status == "cancelled"


def test_cancel_run_side_effect_record_read_failure_keeps_command_accepted(
    tmp_path, monkeypatch, file_run_store
):
    """(b) Even failing to read the run record must not break the command."""
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)

    def failing_collect(run_id: str):
        raise RuntimeError("simulated record read failure")

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.command_service."
        "_collect_cancel_run_turn_pairs",
        failing_collect,
    )

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(run_id="run-cancel", status="running")
        receipt = _submit_cancel(harness, idempotency_key="cancel-key-1")
    finally:
        harness.close()

    assert receipt.status == "accepted"


def test_cancel_run_closes_stale_snapshot_when_session_not_running(
    tmp_path, monkeypatch, file_run_store
):
    """(c) When the in-process running set lost the session, the closure
    writes the terminal chat_turn snapshot via the canonical writer and
    clears index.activeRunId."""
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    work_runs_root = tmp_path / "work_runs"
    monkeypatch.setattr(
        work_run_store_module, "WORK_RUNS_DIR", work_runs_root
    )
    real_store = work_run_store_module.WorkRunStore(root=work_runs_root)
    monkeypatch.setattr(session_service, "_WORK_RUN_STORE", real_store)

    turn_id = "turn-a"
    now = datetime.now(timezone.utc)
    real_store.persist_snapshot(
        "chat_turn",
        {
            "runId": turn_id,
            "runKind": "chat_turn",
            "sessionId": "session-a",
            "status": "running",
            "currentPhase": "running",
            "startedAt": _iso(now - timedelta(minutes=5)),
            "updatedAt": _iso(now - timedelta(minutes=1)),
            "finishedAt": "",
        },
        active_run_id=turn_id,
    )
    assert real_store.load_run_index("chat_turn")["activeRunId"] == turn_id

    # Simulate the process-local running set having forgotten the session.
    with session_service._RUNNING_SESSIONS_LOCK:
        session_service._RUNNING_SESSION_IDS.discard("session-a")
        session_service._SESSION_ACTIVE_TURN_IDS.pop("session-a", None)
    monkeypatch.setattr(session_service, "_is_session_running", lambda session_id: False)

    stops: list[tuple[str, str]] = []

    def unexpected_stop(session_id: str, *, expected_turn_id: str = "") -> dict[str, Any]:
        stops.append((session_id, expected_turn_id))
        return {"id": session_id}

    monkeypatch.setattr(session_service, "request_stop_session_turn", unexpected_stop)

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(run_id="run-cancel", status="running")
        _seed_file_run(file_run_store)
        receipt = _submit_cancel(harness, idempotency_key="cancel-key-1")
    finally:
        harness.close()

    assert receipt.status == "accepted"
    assert stops == []
    latest = real_store.load_snapshot("chat_turn", turn_id)
    assert latest is not None
    assert latest["status"] == "stopped"
    assert str(latest.get("finishedAt") or "").strip()
    index = real_store.load_run_index("chat_turn")
    assert str(index.get("activeRunId") or "") != turn_id
    assert real_store.load_active_snapshot("chat_turn") is None


def test_cancel_run_replay_does_not_repeat_side_effect(
    tmp_path, monkeypatch, file_run_store
):
    """(d) The same idempotencyKey replays the receipt without re-stopping."""
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_WORK_RUN_STORE", _FakeWorkRunStore())
    monkeypatch.setattr(session_service, "_is_session_running", lambda session_id: True)

    stops: list[tuple[str, str]] = []

    def fake_stop(session_id: str, *, expected_turn_id: str = "") -> dict[str, Any]:
        stops.append((session_id, expected_turn_id))
        return {"id": session_id}

    monkeypatch.setattr(session_service, "request_stop_session_turn", fake_stop)

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(run_id="run-cancel", status="running")
        _seed_file_run(file_run_store)
        first = _submit_cancel(harness, idempotency_key="cancel-key-1")
        replay = _submit_cancel(harness, idempotency_key="cancel-key-1")
        cleanup_rows = [
            item
            for item in harness.store.list_pending_outbox("run-cancel")
            if item.idempotency_key == "cancel_run_cleanup:run-cancel"
        ]
    finally:
        harness.close()

    assert first.status == "accepted"
    assert replay.status == "accepted"
    assert replay.command_id == first.command_id
    assert replay.accepted_run_version == first.accepted_run_version
    # Exactly the first submit's side effect (running subtask turn-a plus the
    # binding turn-d); the replayed command adds no further stops.
    assert stops == [("session-a", "turn-a"), ("session-a", "turn-d")]
    assert len(cleanup_rows) == 1


def test_cancel_run_persists_cleanup_intent_for_retry(
    tmp_path, monkeypatch, file_run_store
):
    """The cancellation transaction must leave a durable cleanup intent."""
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "_WORK_RUN_STORE", _FakeWorkRunStore())
    # Keep this test at the transaction boundary: the resident worker owns
    # the external stop side effect and will consume the pending action later.
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.command_service."
        "WorkflowCommandService._close_cancel_run_inflight_turns",
        lambda *_args, **_kwargs: None,
    )

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(run_id="run-cancel", status="running")
        _seed_file_run(file_run_store)
        receipt = _submit_cancel(harness, idempotency_key="cancel-key-1")
        rows = harness.store.submit(
            lambda uow: uow.repository.execute(
                "SELECT action_kind, idempotency_key, status, payload_json "
                "FROM outbox_actions WHERE run_id = ?",
                ("run-cancel",),
            ).fetchall(),
            force_flush=True,
        ).result(timeout=10)
    finally:
        harness.close()

    assert receipt.status == "accepted"
    assert len(rows) == 1
    action_kind, idempotency_key, status, payload_json = rows[0]
    assert action_kind == "reconcile"
    assert idempotency_key == "cancel_run_cleanup:run-cancel"
    assert status == "pending"
    payload = json.loads(payload_json)
    assert payload["kind"] == "cancel_run_chat_turn_cleanup"
    assert payload["runId"] == "run-cancel"


def test_cleanup_worker_does_not_lease_unrelated_reconcile_action(
    tmp_path, monkeypatch
):
    """The cleanup namespace must not consume another ``reconcile`` action."""
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.command_service."
        "_collect_cancel_run_turn_pairs",
        lambda _run_id: [],
    )

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(run_id="run-cancel", status="cancelled")
        cleanup = build_cancel_run_cleanup_record(
            run_id="run-cancel",
            command_id="cmd-cancel",
            now_ms=1_750_000_010_000,
        )
        unrelated = build_outbox_record(
            action_id="act-unrelated-reconcile",
            run_id="run-cancel",
            command_id="cmd-other",
            action_kind="reconcile",
            idempotency_key="reconcile:other-run",
        )

        def insert_actions(uow):
            uow.repository.insert_command(
                build_command_record(
                    command_id="cmd-cancel",
                    run_id="run-cancel",
                    idempotency_key="cancel:key",
                )
            )
            uow.repository.insert_command(
                build_command_record(
                    command_id="cmd-other",
                    run_id="run-cancel",
                    idempotency_key="other:key",
                )
            )
            uow.repository.insert_outbox(cleanup)
            uow.repository.insert_outbox(unrelated)

        harness.store.submit(insert_actions, force_flush=True).result(timeout=10)
        worker = CancelRunCleanupWorker(
            store=harness.store,
            now_provider=lambda: 1_750_000_010_000,
            retry_delay_ms=0,
        )

        assert worker.run_once() == 1
        rows = harness.store.submit(
            lambda uow: uow.repository.execute(
                """
                SELECT idempotency_key, status, lease_owner
                FROM outbox_actions
                ORDER BY action_id
                """
            ).fetchall(),
            force_flush=True,
        ).result(timeout=10)
    finally:
        harness.close()

    assert {
        row[0]: (row[1], row[2])
        for row in rows
    } == {
        "cancel_run_cleanup:run-cancel": ("succeeded", None),
        "reconcile:other-run": ("pending", None),
    }


def test_cleanup_worker_terminalizes_budget_before_acknowledging_cancel(
    tmp_path, monkeypatch
):
    """The durable cancel intent covers both turns and budget receipts."""
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.command_service."
        "_collect_cancel_run_turn_pairs",
        lambda _run_id: [],
    )

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(run_id="run-cancel", status="running")
        _seed_budget_receipt(
            harness,
            settled={
                "invocations": {
                    "inv-cancel": {
                        "inputTokens": 100,
                        "outputTokens": 50,
                        "tokens": 150,
                        "usageEstimated": False,
                    }
                },
                "usage": {
                    "inputTokens": 100,
                    "outputTokens": 50,
                    "tokens": 150,
                    "usageEstimated": False,
                },
            },
        )
        _submit_cancel(harness, idempotency_key="cancel-key-budget")
        worker = CancelRunCleanupWorker(
            store=harness.store,
            now_provider=lambda: 1_750_000_010_000,
            retry_delay_ms=0,
        )

        assert worker.run_once() == 1
        receipt, cleanup = harness.store.read(
            lambda repo: (
                repo.execute(
                    "SELECT status, settled_json FROM budget_receipts WHERE receipt_id = ?",
                    ("br-cancel",),
                ).fetchone(),
                repo.execute(
                    "SELECT status FROM outbox_actions WHERE idempotency_key = ?",
                    ("cancel_run_cleanup:run-cancel",),
                ).fetchone(),
            )
        )
    finally:
        harness.close()

    assert receipt[0] == "settled"
    assert json.loads(receipt[1])["usage"]["tokens"] == 150
    assert cleanup[0] == "succeeded"


def test_cleanup_worker_repairs_budget_after_legacy_cleanup_already_succeeded(
    tmp_path, monkeypatch
):
    """Startup ticks repair cancelled runs whose old cleanup omitted budget."""
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.command_service."
        "_collect_cancel_run_turn_pairs",
        lambda _run_id: [],
    )

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(run_id="run-cancel", status="cancelled")
        _seed_budget_receipt(harness)
        cleanup = build_cancel_run_cleanup_record(
            run_id="run-cancel",
            command_id="cmd-cancel",
            now_ms=1_750_000_000_000,
        )

        def seed_succeeded_cleanup(uow):
            uow.repository.insert_command(
                build_command_record(
                    command_id="cmd-cancel",
                    run_id="run-cancel",
                    idempotency_key="cancel:key",
                )
            )
            uow.repository.insert_outbox(cleanup)
            uow.repository.execute(
                "UPDATE outbox_actions SET status = 'succeeded' WHERE action_id = ?",
                (cleanup.action_id,),
            )

        harness.store.submit(seed_succeeded_cleanup, force_flush=True).result(timeout=10)
        worker = CancelRunCleanupWorker(
            store=harness.store,
            now_provider=lambda: 1_750_000_010_000,
            retry_delay_ms=0,
        )

        assert worker.run_once() == 1
        receipt = harness.store.read(
            lambda repo: repo.execute(
                "SELECT status, settled_json FROM budget_receipts WHERE receipt_id = ?",
                ("br-cancel",),
            ).fetchone()
        )
    finally:
        harness.close()

    assert receipt[0] == "released"
    assert json.loads(receipt[1])["reason"] == "run_cancelled"


def test_cleanup_worker_requeues_transient_stop_then_acknowledges_terminal_turn(
    tmp_path, monkeypatch, file_run_store
):
    """A stop failure is retried from the durable action, not swallowed."""
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    work_runs_root = tmp_path / "work_runs"
    real_store = work_run_store_module.WorkRunStore(root=work_runs_root)
    monkeypatch.setattr(session_service, "_WORK_RUN_STORE", real_store)
    monkeypatch.setattr(session_service, "_is_session_running", lambda _sid: True)
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.command_service."
        "WorkflowCommandService._close_cancel_run_inflight_turns",
        lambda *_args, **_kwargs: None,
    )

    turn_id = "turn-a"
    real_store.persist_snapshot(
        "chat_turn",
        {
            "runId": turn_id,
            "runKind": "chat_turn",
            "sessionId": "session-a",
            "status": "running",
            "currentPhase": "running",
            "startedAt": _iso(datetime.now(timezone.utc)),
            "updatedAt": _iso(datetime.now(timezone.utc)),
            "finishedAt": "",
        },
        active_run_id=turn_id,
    )
    attempts = {"count": 0}

    def stop_then_finish(session_id: str, *, expected_turn_id: str = ""):
        assert session_id == "session-a"
        assert expected_turn_id == turn_id
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("temporary stop transport failure")
        now = _iso(datetime.now(timezone.utc))
        real_store.persist_snapshot(
            "chat_turn",
            {
                **real_store.load_snapshot("chat_turn", turn_id),
                "status": "stopped",
                "currentPhase": "stopped",
                "updatedAt": now,
                "finishedAt": now,
            },
            active_run_id=turn_id,
        )
        return {"currentPhase": "stopped"}

    monkeypatch.setattr(session_service, "request_stop_session_turn", stop_then_finish)

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(run_id="run-cancel", status="running")
        _seed_file_run(
            file_run_store,
            binding_snapshots=[
                {
                    "snapshotId": "snap-1",
                    "sessionId": "session-a",
                    "taskId": "task-1",
                    "turnId": turn_id,
                }
            ],
        )
        _submit_cancel(harness, idempotency_key="cancel-key-1")
        clock = [1_750_000_010_000]
        worker = CancelRunCleanupWorker(
            store=harness.store,
            now_provider=lambda: clock[0],
            retry_delay_ms=0,
        )
        assert worker.run_once() == 1
        pending = harness.store.list_pending_outbox("run-cancel")
        assert len(pending) == 1
        assert pending[0].status == "pending"
        assert attempts["count"] == 1

        clock[0] += 1
        assert worker.run_once() == 1
        row = harness.store.submit(
            lambda uow: uow.repository.execute(
                "SELECT status FROM outbox_actions WHERE idempotency_key = ?",
                ("cancel_run_cleanup:run-cancel",),
            ).fetchone(),
            force_flush=True,
        ).result(timeout=10)
        assert row[0] == "succeeded"
        latest = real_store.load_snapshot("chat_turn", turn_id)
        assert latest is not None and latest["status"] == "stopped"
        assert real_store.load_run_index("chat_turn")["activeRunId"] == ""
    finally:
        harness.close()


def test_cleanup_worker_does_not_ack_live_turn_before_terminal_snapshot(
    tmp_path, monkeypatch, file_run_store
):
    """A stop request that only reaches ``stopping`` remains retryable."""
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    work_runs_root = tmp_path / "work_runs"
    real_store = work_run_store_module.WorkRunStore(root=work_runs_root)
    monkeypatch.setattr(session_service, "_WORK_RUN_STORE", real_store)
    monkeypatch.setattr(session_service, "_is_session_running", lambda _sid: True)
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.command_service."
        "WorkflowCommandService._close_cancel_run_inflight_turns",
        lambda *_args, **_kwargs: None,
    )
    turn_id = "turn-a"
    now = _iso(datetime.now(timezone.utc))
    real_store.persist_snapshot(
        "chat_turn",
        {
            "runId": turn_id,
            "runKind": "chat_turn",
            "sessionId": "session-a",
            "status": "running",
            "currentPhase": "running",
            "startedAt": now,
            "updatedAt": now,
            "finishedAt": "",
        },
        active_run_id=turn_id,
    )

    monkeypatch.setattr(
        session_service,
        "request_stop_session_turn",
        lambda *_args, **_kwargs: {"currentPhase": "stopping"},
    )

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(run_id="run-cancel", status="running")
        _seed_file_run(
            file_run_store,
            binding_snapshots=[
                {
                    "snapshotId": "snap-1",
                    "sessionId": "session-a",
                    "taskId": "task-1",
                    "turnId": turn_id,
                }
            ],
        )
        _submit_cancel(harness, idempotency_key="cancel-key-1")
        worker = CancelRunCleanupWorker(
            store=harness.store,
            now_provider=lambda: 1_750_000_010_000,
            retry_delay_ms=0,
        )
        assert worker.run_once() == 1
        row = harness.store.submit(
            lambda uow: uow.repository.execute(
                "SELECT status FROM outbox_actions WHERE idempotency_key = ?",
                ("cancel_run_cleanup:run-cancel",),
            ).fetchone(),
            force_flush=True,
        ).result(timeout=10)
        assert row[0] == "pending"
        assert real_store.load_snapshot("chat_turn", turn_id)["status"] == "running"
        assert real_store.load_run_index("chat_turn")["activeRunId"] == turn_id
    finally:
        harness.close()


def test_cleanup_worker_recovers_pending_intent_after_store_reopen(
    tmp_path, monkeypatch, file_run_store
):
    """A newly constructed worker resumes an intent left by a prior process."""
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    work_runs_root = tmp_path / "work_runs"
    real_store = work_run_store_module.WorkRunStore(root=work_runs_root)
    monkeypatch.setattr(session_service, "_WORK_RUN_STORE", real_store)
    monkeypatch.setattr(session_service, "_is_session_running", lambda _sid: False)
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.command_service."
        "WorkflowCommandService._close_cancel_run_inflight_turns",
        lambda *_args, **_kwargs: None,
    )
    turn_id = "turn-a"
    now = _iso(datetime.now(timezone.utc))
    real_store.persist_snapshot(
        "chat_turn",
        {
            "runId": turn_id,
            "runKind": "chat_turn",
            "sessionId": "session-a",
            "status": "running",
            "currentPhase": "running",
            "startedAt": now,
            "updatedAt": now,
            "finishedAt": "",
        },
        active_run_id=turn_id,
    )

    ledger_path = tmp_path / "ledger.sqlite3"
    harness = CommandHarness(ledger_path)
    harness.seed_run(run_id="run-cancel", status="running")
    _seed_file_run(
        file_run_store,
        binding_snapshots=[
            {"snapshotId": "snap-1", "sessionId": "session-a", "taskId": "task-1", "turnId": turn_id}
        ],
    )
    _submit_cancel(harness, idempotency_key="cancel-key-1")
    harness.close()

    reopened = open_ledger_store(ledger_path)
    try:
        worker = CancelRunCleanupWorker(
            store=reopened,
            now_provider=lambda: 1_750_000_010_000,
            retry_delay_ms=0,
        )
        assert worker.run_once() == 1
        row = reopened.submit(
            lambda uow: uow.repository.execute(
                "SELECT status FROM outbox_actions WHERE idempotency_key = ?",
                ("cancel_run_cleanup:run-cancel",),
            ).fetchone(),
            force_flush=True,
        ).result(timeout=10)
        assert row[0] == "succeeded"
        latest = real_store.load_snapshot("chat_turn", turn_id)
        assert latest is not None and latest["status"] == "stopped"
        assert real_store.load_run_index("chat_turn")["activeRunId"] == ""
    finally:
        reopened.close()
