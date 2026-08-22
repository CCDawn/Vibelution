"""T5 RED: reconciliation — read-only scans surface stuck attempts without
mutating anything."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from core.research.workflow.challenge_cup_runtime import ChallengeCupGraphCoordinator
from core.research.workflow.ledger.reconciliation import (
    run_ledger_reconciliation,
    run_readonly_reconciliation,
)
from core.web.services.team_workflow.research_runtime import graph_dispatch_worker
from core.web.services.team_workflow.research_runtime.graph_dispatch_worker import (
    GraphDispatchWorker,
)
from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import (
    FIXED_NOW_MS,
    build_event_record,
    build_run_record,
)


def _created_run_reconciliation_payload() -> dict[str, str]:
    return {
        "terminalReason": "dispatch_never_started",
        "reason": "created run exceeded START_NODE deadline without an attempt",
        "reconciliation": "created_without_start",
    }


def _created_run_worker(harness: CommandHarness, tmp_path: Path) -> GraphDispatchWorker:
    return GraphDispatchWorker(
        store=harness.store,
        coordinator=ChallengeCupGraphCoordinator(tmp_path / "checkpoints.sqlite"),
        now_provider=lambda: FIXED_NOW_MS + 2_000,
        start_deadline_ms=1_000,
    )


def test_terminal_run_with_pending_outbox_found(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        harness.service.submit(harness.request(idempotency_key="ui:key-1"))

        def cancel(uow):
            uow.repository.update_run_status(
                "run-test", "research-team", "cancelled", FIXED_NOW_MS
            )

        harness.store.submit(cancel, force_flush=True).result(timeout=10)
        findings = run_readonly_reconciliation(harness.store)
        assert any(f.kind == "terminal_run_pending_outbox" for f in findings)
    finally:
        harness.close()


def _seed_attempt(harness: CommandHarness, node_run_id: str, status: str) -> None:
    from tests._support.workflow_ledger_helpers import (
        build_attempt_record,
        build_command_record,
    )

    def mutate(uow):
        if uow.repository.get_command("cmd-driver") is None:
            uow.repository.insert_command(
                build_command_record(
                    command_id="cmd-driver", run_id="run-test", idempotency_key="cmd-driver"
                )
            )
        uow.repository.insert_attempt(
            build_attempt_record(
                node_run_id=node_run_id,
                run_id="run-test",
                node_id="source_finding",
                attempt=1,
                status=status,
                command_id="cmd-driver",
                started_at_ms=FIXED_NOW_MS,
            )
        )

    harness.store.submit(mutate, force_flush=True).result(timeout=10)


def test_stuck_starting_attempt_found(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        # 无 outbox 的 starting attempt（崩溃残留）。
        _seed_attempt(harness, "nr-stuck", "starting")
        findings = run_ledger_reconciliation(harness.store, run_ids=["run-test"])
        assert any(f.kind == "starting_without_outbox" for f in findings)
    finally:
        harness.close()


def test_stuck_dispatching_attempt_found(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        _seed_attempt(harness, "nr-dispatching", "dispatching")
        findings = run_ledger_reconciliation(harness.store, run_ids=["run-test"])
        assert any(f.kind == "dispatching_without_adapter" for f in findings)
    finally:
        harness.close()


def test_reconciliation_is_readonly(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        _seed_attempt(harness, "nr-stuck", "starting")
        run_ledger_reconciliation(harness.store, run_ids=["run-test"])
        run = harness.store.get_run("run-test")
        assert run is not None and run.run_version == 1
        assert harness.store.latest_event_sequence("run-test") == 1
    finally:
        harness.close()


def test_created_run_reconciliation_rejects_reused_run_created_event_id(
    tmp_path: Path,
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    run_id = "run-created-event-conflict"
    event_id = f"evt-dispatch-never-started-{run_id}"
    try:
        def seed(uow) -> None:
            uow.repository.insert_run(
                build_run_record(
                    run_id=run_id,
                    status="created",
                    last_event_sequence=1,
                    created_at_ms=FIXED_NOW_MS,
                )
            )
            uow.repository.insert_event(
                build_event_record(
                    1,
                    run_id=run_id,
                    event_id=event_id,
                    event_type="run_created",
                )
            )

        harness.store.submit(seed, force_flush=True).result(timeout=10)
        before_run = harness.store.get_run(run_id)
        before_events = harness.store.list_events(run_id)
        before_attempts = harness.store.list_attempts(run_id)

        with pytest.raises(RuntimeError, match="event ID conflict"):
            _created_run_worker(harness, tmp_path).run_once()

        assert harness.store.get_run(run_id) == before_run
        assert harness.store.list_events(run_id) == before_events
        assert harness.store.list_attempts(run_id) == before_attempts
        assert harness.store.latest_event_sequence(run_id) == 1
    finally:
        harness.close()


def test_created_run_reconciliation_accepts_exact_semantic_event_replay(
    tmp_path: Path,
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    run_id = "run-created-event-replay"
    event_id = f"evt-dispatch-never-started-{run_id}"
    try:
        def seed(uow) -> None:
            uow.repository.insert_run(
                build_run_record(
                    run_id=run_id,
                    status="created",
                    last_event_sequence=2,
                    created_at_ms=FIXED_NOW_MS,
                )
            )
            uow.repository.insert_event(
                build_event_record(
                    1,
                    run_id=run_id,
                    event_id=f"evt-created-{run_id}",
                    event_type="run_created",
                )
            )
            replay = build_event_record(
                2,
                run_id=run_id,
                event_id=event_id,
                event_type="run_failed",
                correlation_id=run_id,
            )
            uow.repository.insert_event(
                replace(
                    replay,
                    actor_json=json.dumps(
                        {"actorId": "graph-worker", "actorType": "system"},
                        indent=2,
                    ),
                    payload_json=json.dumps(
                        _created_run_reconciliation_payload(),
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
            )

        harness.store.submit(seed, force_flush=True).result(timeout=10)
        worker = _created_run_worker(harness, tmp_path)

        assert worker.run_once() == 1

        failed = harness.store.get_run(run_id)
        assert failed is not None
        assert failed.status == "failed"
        assert failed.terminal_reason == "dispatch_never_started"
        assert failed.run_version == 1
        assert failed.last_event_sequence == 2
        assert harness.store.list_attempts(run_id) == []
        assert [event.event_id for event in harness.store.list_events(run_id)] == [
            f"evt-created-{run_id}",
            event_id,
        ]
        assert worker.run_once() == 0
    finally:
        harness.close()


@pytest.mark.parametrize(
    "legacy_conflict",
    ["actor", "correlation", "payload", "causation", "event_type", "run_version"],
)
def test_created_run_reconciliation_rejects_legacy_identity_conflict_without_mutation(
    tmp_path: Path, legacy_conflict: str
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    run_id = f"run-created-legacy-{legacy_conflict}"
    event_id = f"evt-dispatch-never-started-{run_id}"
    try:
        def seed(uow) -> None:
            uow.repository.insert_run(
                build_run_record(
                    run_id=run_id,
                    status="created",
                    last_event_sequence=2,
                    created_at_ms=FIXED_NOW_MS,
                )
            )
            uow.repository.insert_event(
                build_event_record(
                    1,
                    run_id=run_id,
                    event_id=f"evt-created-{run_id}",
                    event_type="run_created",
                )
            )
            replay = build_event_record(
                2,
                run_id=run_id,
                event_id=event_id,
                event_type="run_failed",
            )
            if legacy_conflict == "actor":
                replay = replace(
                    replay,
                    actor_json=json.dumps(
                        {"actorType": "system", "actorId": "untrusted-writer"}
                    ),
                )
            elif legacy_conflict == "correlation":
                replay = replace(replay, correlation_id="corr-conflict")
            elif legacy_conflict == "causation":
                replay = replace(replay, causation_id="cause-conflict")
            elif legacy_conflict == "event_type":
                replay = replace(replay, event_type="run_created")
            elif legacy_conflict == "run_version":
                replay = replace(replay, run_version=2)
            else:
                replay = replace(
                    replay,
                    payload_json=json.dumps({"sequence": 2, "tampered": True}),
                )
            uow.repository.insert_event(replay)

        harness.store.submit(seed, force_flush=True).result(timeout=10)
        before_run = harness.store.get_run(run_id)
        before_events = harness.store.list_events(run_id)
        before_attempts = harness.store.list_attempts(run_id)

        with pytest.raises(RuntimeError, match="event ID conflict"):
            _created_run_worker(harness, tmp_path).run_once()

        assert harness.store.get_run(run_id) == before_run
        assert harness.store.list_events(run_id) == before_events
        assert harness.store.list_attempts(run_id) == before_attempts
        assert harness.store.latest_event_sequence(run_id) == 2
    finally:
        harness.close()


@pytest.mark.parametrize(
    ("existing_causation_id", "expected_causation_id"),
    [
        pytest.param("", None, id="legacy-empty-existing-vs-current-none"),
        pytest.param(None, "", id="current-none-existing-vs-legacy-empty"),
    ],
)
def test_created_run_reconciliation_rejects_causation_presence_conflict_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    existing_causation_id: str | None,
    expected_causation_id: str | None,
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    run_id = "run-created-causation-conflict"
    event_id = f"evt-dispatch-never-started-{run_id}"
    original_event_record_for = graph_dispatch_worker._event_record_for

    def expected_event_record_for(**kwargs):
        return replace(
            original_event_record_for(**kwargs),
            causation_id=expected_causation_id,
        )

    monkeypatch.setattr(
        graph_dispatch_worker,
        "_event_record_for",
        expected_event_record_for,
    )
    try:
        def seed(uow) -> None:
            uow.repository.insert_run(
                build_run_record(
                    run_id=run_id,
                    status="created",
                    last_event_sequence=2,
                    created_at_ms=FIXED_NOW_MS,
                )
            )
            uow.repository.insert_event(
                build_event_record(
                    1,
                    run_id=run_id,
                    event_id=f"evt-created-{run_id}",
                    event_type="run_created",
                )
            )
            replay = build_event_record(
                2,
                run_id=run_id,
                event_id=event_id,
                event_type="run_failed",
                correlation_id=run_id,
            )
            uow.repository.insert_event(
                replace(
                    replay,
                    causation_id=existing_causation_id,
                    actor_json=json.dumps(
                        {"actorId": "graph-worker", "actorType": "system"}
                    ),
                    payload_json=json.dumps(
                        _created_run_reconciliation_payload(),
                        ensure_ascii=False,
                    ),
                )
            )

        harness.store.submit(seed, force_flush=True).result(timeout=10)
        before_run = harness.store.get_run(run_id)
        before_events = harness.store.list_events(run_id)
        before_attempts = harness.store.list_attempts(run_id)

        with pytest.raises(RuntimeError, match="event ID conflict"):
            _created_run_worker(harness, tmp_path).run_once()

        assert harness.store.get_run(run_id) == before_run
        assert harness.store.list_events(run_id) == before_events
        assert harness.store.list_attempts(run_id) == before_attempts
        assert harness.store.latest_event_sequence(run_id) == 2
    finally:
        harness.close()
