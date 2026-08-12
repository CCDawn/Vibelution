"""T6.6A: Ledger projection reads must share one SQLite snapshot."""

from __future__ import annotations

import threading
from pathlib import Path

from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import FIXED_NOW_MS, build_event_record


def test_projection_read_ignores_mid_flight_writer_commit(tmp_path: Path) -> None:
    """Writer may commit between SELECTs; one read() must still see one version."""
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(run_id="run-snap", run_version=1)
        started = threading.Event()
        writer_done = threading.Event()
        seen: dict[str, int] = {}

        def reader() -> None:
            def load(repo):
                run = repo.get_run("run-snap")
                assert run is not None
                seen["run_version_before"] = run.run_version
                seen["seq_before"] = repo.latest_event_sequence("run-snap")
                started.set()
                assert writer_done.wait(timeout=10)
                run_after = repo.get_run("run-snap")
                assert run_after is not None
                seen["run_version_after"] = run_after.run_version
                seen["seq_after"] = repo.latest_event_sequence("run-snap")
                return run_after.run_version, repo.latest_event_sequence("run-snap")

            harness.store.read(load)

        def writer() -> None:
            assert started.wait(timeout=10)

            def mutate(uow):
                uow.repository.insert_event(
                    build_event_record(
                        sequence=2,
                        run_id="run-snap",
                        run_version=2,
                        event_type="command_accepted",
                        event_id="evt-mid-flight",
                    )
                )
                uow.repository.execute(
                    "UPDATE workflow_runs SET run_version = 2, last_event_sequence = 2, "
                    "updated_at_ms = ? WHERE run_id = ?",
                    (FIXED_NOW_MS + 1, "run-snap"),
                )

            harness.store.submit(mutate, force_flush=True).result(timeout=10)
            # Confirm a fresh connection already sees the new version.
            assert harness.store.get_run("run-snap").run_version == 2
            writer_done.set()

        threads = [
            threading.Thread(target=reader, daemon=True),
            threading.Thread(target=writer, daemon=True),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)

        assert seen["run_version_before"] == seen["run_version_after"] == 1, seen
        assert seen["seq_before"] == seen["seq_after"] == 1, seen

        next_run = harness.store.get_run("run-snap")
        assert next_run is not None
        assert next_run.run_version == 2
        assert harness.store.latest_event_sequence("run-snap") == 2
    finally:
        harness.close()


def test_nested_read_reuses_same_snapshot(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(run_id="run-nest")

        def outer(repo):
            first = repo.get_run("run-nest")
            assert first is not None

            def inner(inner_repo):
                second = inner_repo.get_run("run-nest")
                assert second is not None
                assert second.run_version == first.run_version
                return second.run_version

            return harness.store.read(inner)

        assert harness.store.read(outer) == 1
    finally:
        harness.close()
