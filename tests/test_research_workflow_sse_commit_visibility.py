"""T6: SSE only exposes committed Ledger events (after-commit visibility)."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from core.web.services.team_workflow.research_runtime.event_stream_service import (
    WorkflowEventStreamService,
)
from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import FIXED_NOW_MS, build_event_record


def test_uncommitted_event_not_visible_until_commit(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(run_id="run-vis")
        harness_notifier = _Notifier()
        stream = WorkflowEventStreamService(
            store=harness.store,
            notifier=harness_notifier,
        )

        barrier = threading.Barrier(2)
        inserted = threading.Event()
        committed = threading.Event()

        def writer() -> None:
            def mutate(uow):
                uow.repository.insert_event(
                    build_event_record(
                        sequence=2,
                        run_id="run-vis",
                        run_version=2,
                        event_type="node_running",
                        event_id="evt-uncommitted-then-commit",
                    )
                )
                uow.repository.execute(
                    "UPDATE workflow_runs SET last_event_sequence = 2, "
                    "updated_at_ms = ? WHERE run_id = ?",
                    (FIXED_NOW_MS + 5, "run-vis"),
                )
                inserted.set()
                barrier.wait(timeout=5)
                # Still inside the writer transaction until this returns.
                # Visibility must remain false until commit completes.
                assert harness.store.latest_event_sequence("run-vis") == 1
                uow.after_commit(harness_notifier.notify)

            harness.store.submit(mutate, force_flush=True).result(timeout=10)
            committed.set()
            harness_notifier.notify()

        thread = threading.Thread(target=writer, daemon=True)
        thread.start()
        assert inserted.wait(5)

        # Before commit: ledger read pool must not see sequence 2.
        before = list(
            stream.replay_frames(
                team_id="research-team",
                run_id="run-vis",
                after_sequence=1,
            )
        )
        assert before == []
        assert harness.store.latest_event_sequence("run-vis") == 1

        barrier.wait(timeout=5)
        thread.join(timeout=5)
        assert committed.wait(5)

        after = list(
            stream.replay_frames(
                team_id="research-team",
                run_id="run-vis",
                after_sequence=1,
            )
        )
        assert len(after) == 1
        assert "id: run-vis:2" in after[0]
        assert harness.store.latest_event_sequence("run-vis") == 2
    finally:
        harness.close()


class _Notifier:
    def __init__(self) -> None:
        self._cond = threading.Condition()

    def notify(self) -> None:
        with self._cond:
            self._cond.notify_all()

    def wait(self, timeout: float) -> bool:
        with self._cond:
            return self._cond.wait(timeout=timeout)
