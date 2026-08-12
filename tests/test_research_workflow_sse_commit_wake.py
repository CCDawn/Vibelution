"""T6.6E: Formal SSE wakes on Ledger commit without relying on 1s wait."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from core.web.services.team_workflow.research_runtime.event_stream_service import (
    WorkflowEventStreamService,
)
from core.web.services.team_workflow.research_runtime.formal_read_runtime import (
    get_event_stream_service,
    reset_formal_read_runtime_for_tests,
    wake_stream_readers,
)
from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import FIXED_NOW_MS, build_event_record


def test_wake_stream_readers_notifies_formal_sse_waiters(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(run_id="run-wake")
        reset_formal_read_runtime_for_tests(
            store=harness.store,
            readiness_service=harness.readiness,
            readiness_context=lambda: harness.context,
        )
        stream = WorkflowEventStreamService(
            store=harness.store,
            notifier=get_event_stream_service().notifier,
        )

        frames: list[str] = []
        started = threading.Event()
        done = threading.Event()

        def reader() -> None:
            started.set()
            for frame in stream.iter_sse(
                team_id="research-team",
                run_id="run-wake",
                after_sequence=1,
                wait_timeout_seconds=30.0,
                heartbeat_seconds=60.0,
            ):
                if frame.startswith(":"):
                    continue
                frames.append(frame)
                done.set()
                break

        thread = threading.Thread(target=reader, daemon=True)
        thread.start()
        assert started.wait(2)
        time.sleep(0.05)

        def mutate(uow):
            uow.repository.insert_event(
                build_event_record(
                    sequence=2,
                    run_id="run-wake",
                    run_version=2,
                    event_type="node_running",
                    event_id="evt-wake-1",
                )
            )
            uow.repository.execute(
                "UPDATE workflow_runs SET last_event_sequence = 2, "
                "run_version = 2, updated_at_ms = ? WHERE run_id = ?",
                (FIXED_NOW_MS + 5, "run-wake"),
            )
            uow.after_commit(wake_stream_readers)

        started_at = time.monotonic()
        harness.store.submit(mutate, force_flush=True).result(timeout=10)
        assert done.wait(5), "SSE waiter should wake on commit notify"
        elapsed = time.monotonic() - started_at
        assert elapsed < 5.0, elapsed
        assert any("node_running" in frame for frame in frames)
        thread.join(timeout=2)
    finally:
        reset_formal_read_runtime_for_tests()
        harness.close()
