"""T1 RED: concurrency — conditional runVersion bump under concurrent
submission, monotonic event sequences, one winner per version."""

from __future__ import annotations

from pathlib import Path

from core.research.workflow.ledger import RunVersionConflictError
from tests._support.workflow_ledger_helpers import (
    build_event_record,
    build_run_record,
    open_ledger_store,
)


def test_concurrent_expected_version_exactly_one_winner(tmp_path: Path) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3", queue_size=128)
    try:
        store.submit(
            lambda uow: uow.repository.insert_run(build_run_record(run_version=1)),
            force_flush=True,
        ).result(timeout=10)

        import concurrent.futures

        def attempt(index: int):
            def mutate(uow):
                bumped = uow.repository.bump_run_version(
                    "run-test", "research-team", expected_version=1, event_count=1, now_ms=index
                )
                if bumped is None:
                    raise RunVersionConflictError()
                uow.repository.insert_event(
                    build_event_record(
                        sequence=bumped[1],
                        run_version=bumped[0],
                        event_id=f"evt-{index}",
                        correlation_id=f"corr-{index}",
                    )
                )
                return bumped

            return store.submit(mutate, force_flush=True).result(timeout=10)

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(attempt, index) for index in range(8)]
            winners = []
            conflicts = 0
            for future in futures:
                try:
                    result = future.result()
                    if isinstance(result, tuple):
                        winners.append(result)
                except RunVersionConflictError:
                    conflicts += 1

        assert len(winners) == 1
        assert conflicts == 7
        run = store.get_run("run-test")
        assert run is not None
        assert run.run_version == 2
        assert run.last_event_sequence == 1
        assert store.latest_event_sequence("run-test") == 1
    finally:
        store.close()


def test_sequential_bumps_allocate_monotonic_sequences(tmp_path: Path) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        store.submit(
            lambda uow: uow.repository.insert_run(build_run_record(run_version=1)),
            force_flush=True,
        ).result(timeout=10)
        for index in range(5):
            def mutate(uow, i=index):
                bumped = uow.repository.bump_run_version(
                    "run-test", "research-team", expected_version=i + 1, event_count=2, now_ms=i
                )
                assert bumped is not None
                uow.repository.insert_event(
                    build_event_record(
                        sequence=bumped[1] - 1, run_version=bumped[0], event_id=f"evt-{i}-a"
                    )
                )
                uow.repository.insert_event(
                    build_event_record(
                        sequence=bumped[1], run_version=bumped[0], event_id=f"evt-{i}-b"
                    )
                )

            store.submit(mutate, force_flush=True).result(timeout=10)

        events = store.list_events("run-test")
        sequences = [event.sequence for event in events]
        assert sequences == list(range(1, 11))
        run = store.get_run("run-test")
        assert run is not None and run.run_version == 6
    finally:
        store.close()


def test_stale_version_returns_none(tmp_path: Path) -> None:
    store = open_ledger_store(tmp_path / "ledger.sqlite3")
    try:
        store.submit(
            lambda uow: uow.repository.insert_run(build_run_record(run_version=5)),
            force_flush=True,
        ).result(timeout=10)

        def mutate(uow):
            return uow.repository.bump_run_version(
                "run-test", "research-team", expected_version=3, event_count=1, now_ms=1
            )

        result = store.submit(mutate, force_flush=True).result(timeout=10)
        assert result is None
    finally:
        store.close()
