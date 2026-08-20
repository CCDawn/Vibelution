"""Durability regression tests for team workflow JSONL stores.

Audit findings: (1) the read-modify-write append raced across processes —
two writers each replayed onto a stale snapshot and the last replace
silently dropped the other's records; (2) one corrupt line made every
read raise, bricking team state with no repair path.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from core.web.services.team_workflow.storage_durability import (
    append_jsonl_locked,
    inter_process_lock,
    read_jsonl_tolerant,
)

_WORKER_SCRIPT = """
import sys
sys.path.insert(0, {root!r})
from core.web.services.team_workflow.storage_durability import append_jsonl_locked
from pathlib import Path
store = Path({store!r})
for index in range({count}):
    append_jsonl_locked(store, {{"worker": {worker}, "index": index}})
print("done", {worker})
"""


def test_concurrent_append_across_processes_loses_nothing(tmp_path: Path) -> None:
    store = tmp_path / "teams" / "t1" / "chain.jsonl"
    root = str(Path(__file__).resolve().parents[1])
    workers = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                _WORKER_SCRIPT.format(root=root, store=str(store), count=40, worker=n),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        for n in range(3)
    ]
    for index in range(40):
        append_jsonl_locked(store, {"worker": "main", "index": index})
    for worker in workers:
        _, stderr = worker.communicate(timeout=60)
        assert worker.returncode == 0, stderr.decode("utf-8", "replace")

    records = read_jsonl_tolerant(store)
    assert len(records) == 160
    by_worker: dict[str, int] = {}
    for record in records:
        by_worker[str(record["worker"])] = by_worker.get(str(record["worker"]), 0) + 1
    assert by_worker == {"main": 40, "0": 40, "1": 40, "2": 40}


def test_corrupt_line_is_quarantined_and_reading_stays_stable(tmp_path: Path) -> None:
    store = tmp_path / "chain.jsonl"
    store.write_text(
        '{"a": 1}\n'
        "NOT JSON AT ALL\n"
        '{"a": 2}\n'
        '"a bare string is not a record"\n',
        encoding="utf-8",
    )
    records = read_jsonl_tolerant(store)
    assert [record["a"] for record in records] == [1, 2]

    quarantine = store.with_name(store.name + ".corrupt")
    assert quarantine.exists()
    quarantined = quarantine.read_text(encoding="utf-8").splitlines()
    assert "NOT JSON AT ALL" in quarantined
    assert '"a bare string is not a record"' in quarantined

    # Idempotent: a second read does not duplicate quarantine entries.
    again = read_jsonl_tolerant(store)
    assert [record["a"] for record in again] == [1, 2]
    assert len(quarantine.read_text(encoding="utf-8").splitlines()) == 2


def test_missing_store_reads_empty_and_lock_releases(tmp_path: Path) -> None:
    store = tmp_path / "missing.jsonl"
    assert read_jsonl_tolerant(store) == []
    with inter_process_lock(store):
        pass  # lock acquires and releases cleanly on a fresh path
    assert (tmp_path / "missing.jsonl.lock").exists()
