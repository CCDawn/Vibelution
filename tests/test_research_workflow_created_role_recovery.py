"""Focused recovery coverage for created runs and frozen role bindings."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from core.research.workflow.challenge_cup_runtime import ChallengeCupGraphCoordinator
from core.web.services.team_workflow.research_runtime.graph_dispatch_worker import (
    GraphDispatchWorker,
)
from core.web.services.team_workflow.research_runtime.team_role_source import (
    heal_agent_binding_from_sibling_freeze,
)
from tests._support.workflow_ledger_helpers import (
    FIXED_NOW_MS,
    build_attempt_record,
    build_command_record,
    build_event_record,
    build_run_record,
    open_ledger_store,
)


def _worker(store, tmp_path: Path) -> GraphDispatchWorker:
    return GraphDispatchWorker(
        store=store,
        coordinator=ChallengeCupGraphCoordinator(tmp_path / "checkpoints.sqlite"),
        now_provider=lambda: FIXED_NOW_MS + 2_000,
        start_deadline_ms=1_000,
    )


def test_created_run_without_attempt_is_failed_once(tmp_path: Path) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        run = build_run_record(
            run_id="run-created-never-started",
            status="created",
            last_event_sequence=1,
            created_at_ms=FIXED_NOW_MS,
        )

        def seed(uow) -> None:
            uow.repository.insert_run(run)
            uow.repository.insert_event(
                build_event_record(
                    1,
                    run_id=run.run_id,
                    event_id=f"evt-created-{run.run_id}",
                )
            )

        store.submit(seed, force_flush=True).result(timeout=10)
        worker = _worker(store, tmp_path)

        assert worker.run_once() == 1
        failed = store.get_run(run.run_id)
        assert failed is not None
        assert failed.status == "failed"
        assert failed.terminal_reason == "dispatch_never_started"
        events = store.list_events(run.run_id)
        assert [event.event_type for event in events] == ["run_created", "run_failed"]
        assert json.loads(events[-1].payload_json)["terminalReason"] == (
            "dispatch_never_started"
        )

        worker.run_once()
        assert len(store.list_events(run.run_id)) == 2
    finally:
        store.close()


def test_hypothesis_first_prelude_without_attempt_is_not_reaped(
    tmp_path: Path,
) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        run = replace(
            build_run_record(
                run_id="run-hypothesis-first-prelude",
                status="created",
                last_event_sequence=1,
                created_at_ms=FIXED_NOW_MS,
            ),
            input_snapshot_json=json.dumps(
                {
                    "researchObjectiveContract": {
                        "hypothesisFirst": True,
                    }
                }
            ),
        )

        def seed(uow) -> None:
            uow.repository.insert_run(run)
            uow.repository.insert_event(
                build_event_record(
                    1,
                    run_id=run.run_id,
                    event_id=f"evt-created-{run.run_id}",
                )
            )

        store.submit(seed, force_flush=True).result(timeout=10)

        assert _worker(store, tmp_path).run_once() == 0
        current = store.get_run(run.run_id)
        assert current is not None
        assert current.status == "created"
        assert current.terminal_reason is None
        assert [event.event_type for event in store.list_events(run.run_id)] == [
            "run_created"
        ]
    finally:
        store.close()


def test_created_run_with_node_attempt_is_not_reaped(tmp_path: Path) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        run = build_run_record(
            run_id="run-created-with-attempt",
            status="created",
            last_event_sequence=1,
            created_at_ms=FIXED_NOW_MS,
        )

        def seed(uow) -> None:
            uow.repository.insert_run(run)
            uow.repository.insert_event(
                build_event_record(
                    1,
                    run_id=run.run_id,
                    event_id=f"evt-created-{run.run_id}",
                )
            )
            uow.repository.insert_command(
                build_command_record(
                    command_id="cmd-created-with-attempt",
                    run_id=run.run_id,
                )
            )
            uow.repository.insert_attempt(
                build_attempt_record(
                    node_run_id="nr-created-with-attempt",
                    run_id=run.run_id,
                    command_id="cmd-created-with-attempt",
                )
            )

        store.submit(seed, force_flush=True).result(timeout=10)
        worker = _worker(store, tmp_path)

        worker.run_once()
        current = store.get_run(run.run_id)
        assert current is not None and current.status == "created"
        assert current.terminal_reason is None
        assert len(store.list_events(run.run_id)) == 1
    finally:
        store.close()


def test_created_repair_accepts_exact_failed_event_replay(tmp_path: Path) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        run = build_run_record(
            run_id="run-created-replay",
            status="created",
            last_event_sequence=2,
            created_at_ms=FIXED_NOW_MS,
        )
        event_id = f"evt-dispatch-never-started-{run.run_id}"
        payload = {
            "terminalReason": "dispatch_never_started",
            "reason": "created run exceeded START_NODE deadline without an attempt",
            "reconciliation": "created_without_start",
        }

        def seed(uow) -> None:
            uow.repository.insert_run(run)
            uow.repository.insert_event(
                build_event_record(
                    1,
                    run_id=run.run_id,
                    event_id=f"evt-created-{run.run_id}",
                )
            )
            replay = build_event_record(
                2,
                run_id=run.run_id,
                run_version=run.run_version,
                event_type="run_failed",
                event_id=event_id,
                correlation_id=run.run_id,
            )
            uow.repository.insert_event(
                replace(
                    replay,
                    actor_json=json.dumps(
                        {"actorType": "system", "actorId": "graph-worker"}
                    ),
                    payload_json=json.dumps(payload, ensure_ascii=False),
                )
            )

        store.submit(seed, force_flush=True).result(timeout=10)
        worker = _worker(store, tmp_path)

        assert worker.run_once() == 1
        failed = store.get_run(run.run_id)
        assert failed is not None and failed.status == "failed"
        assert failed.terminal_reason == "dispatch_never_started"
        assert failed.last_event_sequence == 2
        assert len(store.list_events(run.run_id)) == 2
        assert worker.run_once() == 0
    finally:
        store.close()


def test_created_repair_rejects_run_event_sequence_mismatch(tmp_path: Path) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        run = build_run_record(
            run_id="run-created-sequence-mismatch",
            status="created",
            last_event_sequence=2,
            created_at_ms=FIXED_NOW_MS,
        )

        def seed(uow) -> None:
            uow.repository.insert_run(run)
            uow.repository.insert_event(
                build_event_record(
                    1,
                    run_id=run.run_id,
                    event_id=f"evt-created-{run.run_id}",
                )
            )

        store.submit(seed, force_flush=True).result(timeout=10)
        worker = _worker(store, tmp_path)

        with pytest.raises(RuntimeError, match="sequence conflict"):
            worker.run_once()
        current = store.get_run(run.run_id)
        assert current is not None and current.status == "created"
        assert current.last_event_sequence == 2
        assert len(store.list_events(run.run_id)) == 1
    finally:
        store.close()


@pytest.mark.parametrize("conflict", ["run_version", "actor", "correlation", "causation", "payload"])
def test_created_repair_rejects_conflicting_failed_event_replay(
    tmp_path: Path, conflict: str
) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        run = build_run_record(
            run_id=f"run-created-replay-{conflict}",
            status="created",
            last_event_sequence=2,
            created_at_ms=FIXED_NOW_MS,
        )
        event_id = f"evt-dispatch-never-started-{run.run_id}"
        payload = {
            "terminalReason": "dispatch_never_started",
            "reason": "created run exceeded START_NODE deadline without an attempt",
            "reconciliation": "created_without_start",
        }

        def seed(uow) -> None:
            uow.repository.insert_run(run)
            uow.repository.insert_event(
                build_event_record(
                    1,
                    run_id=run.run_id,
                    event_id=f"evt-created-{run.run_id}",
                )
            )
            replay = build_event_record(
                2,
                run_id=run.run_id,
                run_version=run.run_version,
                event_type="run_failed",
                event_id=event_id,
                correlation_id=run.run_id,
            )
            overrides = {
                "actor_json": json.dumps(
                    {"actorType": "system", "actorId": "not-graph-worker"}
                ),
                "correlation_id": "wrong-correlation",
                "causation_id": "",
                "payload_json": json.dumps({"terminalReason": "other"}),
                "run_version": run.run_version + 1,
            }
            uow.repository.insert_event(
                replace(
                    replay,
                    actor_json=json.dumps(
                        {"actorType": "system", "actorId": "graph-worker"}
                    )
                    if conflict != "actor"
                    else overrides["actor_json"],
                    correlation_id=(
                        run.run_id
                        if conflict != "correlation"
                        else overrides["correlation_id"]
                    ),
                    causation_id=(
                        None if conflict != "causation" else overrides["causation_id"]
                    ),
                    payload_json=(
                        json.dumps(payload, ensure_ascii=False)
                        if conflict != "payload"
                        else overrides["payload_json"]
                    ),
                    run_version=(
                        run.run_version
                        if conflict != "run_version"
                        else overrides["run_version"]
                    ),
                )
            )

        store.submit(seed, force_flush=True).result(timeout=10)
        worker = _worker(store, tmp_path)

        with pytest.raises(RuntimeError, match="conflicts with dispatch_never_started"):
            worker.run_once()
        current = store.get_run(run.run_id)
        assert current is not None and current.status == "created"
        assert current.last_event_sequence == 2
        assert len(store.list_events(run.run_id)) == 2
    finally:
        store.close()


def test_sibling_healing_is_role_scoped_and_unbound_is_explicit() -> None:
    same_role = {
        "agentBindingSnapshot": [
            {
                "nodeId": "protocol_design",
                "agentId": "agent-planner",
                "roleKey": "EXPERIMENT_PLANNER",
            }
        ]
    }
    healed = heal_agent_binding_from_sibling_freeze(same_role, "hypothesis_design")
    assert healed is not None
    assert healed["agentId"] == "agent-planner"
    assert healed["roleKey"] == "experiment_planner"

    cross_role = {
        "agentBindingSnapshot": [
            {
                "nodeId": "source_finding",
                "agentId": "agent-search",
                "roleKey": "source_finder",
            }
        ]
    }
    assert heal_agent_binding_from_sibling_freeze(cross_role, "hypothesis_design") is None
    assert heal_agent_binding_from_sibling_freeze({}, "hypothesis_design") is None
