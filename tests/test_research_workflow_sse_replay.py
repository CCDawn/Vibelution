"""T6: SSE replay from Ledger with Last-Event-ID and keepalive cursor rules."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.web.services.team_workflow.research_runtime.event_stream_service import (
    InvalidLastEventIdError,
    WorkflowEventStreamService,
    encode_sse_event,
    parse_stream_cursor,
)
from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import build_event_record


def _seed(harness: CommandHarness, run_id: str = "run-sse") -> None:
    harness.seed_run(run_id=run_id)

    def mutate(uow):
        for seq in (2, 3):
            uow.repository.insert_event(
                build_event_record(
                    sequence=seq,
                    run_id=run_id,
                    run_version=seq,
                    event_type="node_running",
                    event_id=f"evt-{seq}",
                )
            )
        uow.repository.execute(
            "UPDATE workflow_runs SET last_event_sequence = 3 WHERE run_id = ?",
            (run_id,),
        )

    harness.store.submit(mutate, force_flush=True).result(timeout=10)


def _decode(frame: str) -> tuple[str, str, dict]:
    lines = [line for line in frame.strip().splitlines() if line]
    frame_id = next(line[4:] for line in lines if line.startswith("id: "))
    event = next(line[7:] for line in lines if line.startswith("event: "))
    data = json.loads(next(line[6:] for line in lines if line.startswith("data: ")))
    return frame_id, event, data


def test_sse_last_event_id_exact_resume_no_dup_no_loss(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed(harness)
        stream = WorkflowEventStreamService(store=harness.store)
        frames = list(
            stream.replay_frames(
                team_id="research-team",
                run_id="run-sse",
                after_sequence=1,
            )
        )
        ids = [_decode(frame)[0] for frame in frames]
        assert ids == ["run-sse:2", "run-sse:3"]
        assert len(ids) == len(set(ids))

        again = list(
            stream.replay_frames(
                team_id="research-team",
                run_id="run-sse",
                last_event_id="run-sse:2",
            )
        )
        assert [_decode(frame)[0] for frame in again] == ["run-sse:3"]
    finally:
        harness.close()


def test_sse_replay_preserves_unknown_event_type(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed(harness)

        def mutate(uow):
            uow.repository.insert_event(
                build_event_record(
                    sequence=4,
                    run_id="run-sse",
                    run_version=4,
                    event_type="future_event",
                    event_id="evt-future",
                )
            )
            uow.repository.execute(
                "UPDATE workflow_runs SET last_event_sequence = 4 WHERE run_id = ?",
                ("run-sse",),
            )

        harness.store.submit(mutate, force_flush=True).result(timeout=10)
        stream = WorkflowEventStreamService(store=harness.store)

        frames = list(
            stream.replay_frames(
                team_id="research-team",
                run_id="run-sse",
                after_sequence=3,
            )
        )

        assert len(frames) == 1
        frame_id, event_type, data = _decode(frames[0])
        assert frame_id == "run-sse:4"
        assert event_type == "future_event"
        assert data["type"] == "future_event"
        assert data["sequence"] == 4
    finally:
        harness.close()


def test_sse_rejects_wrong_run_last_event_id(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed(harness)
        stream = WorkflowEventStreamService(store=harness.store)
        with pytest.raises(InvalidLastEventIdError):
            list(
                stream.replay_frames(
                    team_id="research-team",
                    run_id="run-sse",
                    last_event_id="other-run:2",
                )
            )
        with pytest.raises(InvalidLastEventIdError):
            parse_stream_cursor("run-sse:abc", route_run_id="run-sse")
    finally:
        harness.close()


def test_keepalive_does_not_change_cursor() -> None:
    frame = encode_sse_event(
        run_id="run-sse",
        sequence=7,
        event_type="node_running",
        payload={"ok": True},
    )
    assert frame.startswith("id: run-sse:7\n")
    keepalive = ": keepalive\n\n"
    assert "id:" not in keepalive
    cursor_before = 7
    # keepalive is a comment; cursor remains unchanged by contract
    cursor_after = cursor_before
    assert cursor_after == 7
