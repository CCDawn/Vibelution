"""T6: durable workflow event replay from Ledger (monotonic sequence)."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.web.services.team_workflow.research_runtime.event_replay_service import (
    WorkflowEventReplayService,
)
from core.web.services.team_workflow.research_runtime.query_service import (
    TeamScopeMismatchError,
)
from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import FIXED_NOW_MS, build_event_record


def _seed_events(harness: CommandHarness, run_id: str = "run-evt") -> None:
    harness.seed_run(run_id=run_id)

    def mutate(uow):
        for seq, etype in (
            (2, "command_accepted"),
            (3, "node_starting"),
            (4, "node_running"),
        ):
            uow.repository.insert_event(
                build_event_record(
                    sequence=seq,
                    run_id=run_id,
                    run_version=seq,
                    event_type=etype,
                    event_id=f"evt-{seq}-{run_id}",
                )
            )
        uow.repository.execute(
            "UPDATE workflow_runs SET last_event_sequence = 4, updated_at_ms = ? "
            "WHERE run_id = ?",
            (FIXED_NOW_MS + 10, run_id),
        )

    harness.store.submit(mutate, force_flush=True).result(timeout=10)


def test_events_are_monotonic_scoped_and_after_sequence(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_events(harness)
        replay = WorkflowEventReplayService(store=harness.store)
        page = replay.list_events(
            team_id="research-team",
            run_id="run-evt",
            after_sequence=0,
        )
        sequences = [item.sequence for item in page.events]
        assert sequences == [1, 2, 3, 4]
        assert len(sequences) == len(set(sequences))
        assert all(item.run_id == "run-evt" for item in page.events)
        assert all(item.team_id == "research-team" for item in page.events)

        after = replay.list_events(
            team_id="research-team",
            run_id="run-evt",
            after_sequence=2,
        )
        assert [item.sequence for item in after.events] == [3, 4]
        assert after.latest_event_sequence == 4
        assert after.after_sequence == 2
        assert after.last_returned_sequence == 4
        assert after.has_more is False
        assert after.next_after_sequence is None
    finally:
        harness.close()


def test_event_page_pagination_fields(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_events(harness)
        replay = WorkflowEventReplayService(store=harness.store)
        page = replay.list_events(
            team_id="research-team",
            run_id="run-evt",
            after_sequence=0,
            limit=2,
        )
        assert [item.sequence for item in page.events] == [1, 2]
        assert page.after_sequence == 0
        assert page.last_returned_sequence == 2
        assert page.latest_event_sequence == 4
        assert page.has_more is True
        assert page.next_after_sequence == 2
        payload = page.to_dict()
        assert payload["hasMore"] is True
        assert payload["nextAfterSequence"] == 2
        assert payload["lastReturnedSequence"] == 2
    finally:
        harness.close()


def test_events_reject_team_mismatch_and_do_not_cross_runs(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_events(harness, run_id="run-a")
        _seed_events(harness, run_id="run-b")
        replay = WorkflowEventReplayService(store=harness.store)
        with pytest.raises(TeamScopeMismatchError):
            replay.list_events(team_id="other-team", run_id="run-a", after_sequence=0)
        page = replay.list_events(
            team_id="research-team",
            run_id="run-a",
            after_sequence=0,
        )
        assert {item.run_id for item in page.events} == {"run-a"}
        assert all(item.team_id == "research-team" for item in page.events)
    finally:
        harness.close()
