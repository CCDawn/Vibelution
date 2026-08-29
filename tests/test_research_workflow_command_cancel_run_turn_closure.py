"""cancel_run closes in-flight chat turns bound to a cancelled research run.

Regression coverage: cancel_run used to only move the ledger run to
``cancelled`` and never stopped the in-flight session turns, so
``work_runs/chat_turn`` snapshots stayed ``running`` with a pinned
``index.activeRunId`` and the desktop active-work guard blocked restart/stop
until the 30-minute projection reconciler ran.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from core.research.workflow.contracts import WorkflowCommandKind
from core.runtime_manager import work_run_store as work_run_store_module
from core.web.services import session_service
from core.web.services.team_workflow.research_runtime.store import WorkflowRunStore

from tests._support.command_helpers import CommandHarness


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
    finally:
        harness.close()

    assert first.status == "accepted"
    assert replay.status == "accepted"
    assert replay.command_id == first.command_id
    assert replay.accepted_run_version == first.accepted_run_version
    # Exactly the first submit's side effect (running subtask turn-a plus the
    # binding turn-d); the replayed command adds no further stops.
    assert stops == [("session-a", "turn-a"), ("session-a", "turn-d")]
