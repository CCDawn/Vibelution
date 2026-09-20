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


def test_inter_process_lock_survives_max_path_run_directories(tmp_path: Path) -> None:
    """2026-09-09 production failure: live run directory (233 chars) plus the
    35-char ``knowledge_ingestion_materialize`` lock name pushed the lock path
    to 270 > MAX_PATH; with LongPathsEnabled=0 ``open`` raised FileNotFoundError
    errno 2 even though the parent directory existed."""
    from core.web.services.team_workflow.storage_durability import (
        _windows_extended_length_path,
    )

    # Grow a nested chain until the lock file path clears the Win32 ceiling,
    # mirroring how deep live instance data roots sit near the limit.
    component = "d" * 60
    directory = tmp_path
    while len(str(directory / component / "knowledge_ingestion_materialize.lock")) < 270:
        directory = directory / component
    lock_store = directory / "knowledge_ingestion_materialize"

    with inter_process_lock(lock_store):
        pass  # must acquire and release instead of FileNotFoundError

    lock_file = _windows_extended_length_path(
        lock_store.with_name(lock_store.name + ".lock")
    )
    assert lock_file.exists()

    # Short lock paths round-trip unchanged so existing identities stay stable.
    short = tmp_path / "chain.jsonl.lock"
    assert _windows_extended_length_path(short) == short


def test_evidence_trail_cache_serves_repeated_reads_and_invalidates(tmp_path: Path, monkeypatch) -> None:
    """P3-8: the trail computation caches per (team, question) on store mtime."""
    from core.web.services.team_workflow import meeting_rounds
    from core.web.services.team_workflow.research_runtime import hypothesis_first_chain as chain

    from core.web.services import team_service

    chain._TRAIL_CACHE.clear()
    monkeypatch.setattr(team_service, "assert_team_exists", lambda _t: "t")
    monkeypatch.setattr(chain, "_records", lambda _team: [])
    list_calls = {"count": 0}

    def fake_list_meetings(_team_id, **_kwargs):
        list_calls["count"] += 1
        return {"meetings": []}

    monkeypatch.setattr(meeting_rounds, "list_meeting_rounds", fake_list_meetings)

    stamps = iter([1.0, 1.0, 2.0])
    monkeypatch.setattr(chain, "_trail_source_stamp", lambda _team: next(stamps))

    first = chain.candidate_evidence_trail("t", "SCI-001")
    assert first["trails"] == []
    assert list_calls["count"] == 1

    # Same store stamp -> served from cache; the meetings store is not re-scanned.
    chain.candidate_evidence_trail("t", "SCI-001")
    assert list_calls["count"] == 1

    # Store changed -> recompute.
    chain.candidate_evidence_trail("t", "SCI-001")
    assert list_calls["count"] == 2


# ---------------------------------------------------------------------------
# true-append primitives: parity, torn-line tolerance, compaction races
# ---------------------------------------------------------------------------


def test_append_record_output_is_byte_identical_to_whole_file_append(tmp_path: Path) -> None:
    """The locked true append must produce exactly the old algorithm's bytes."""
    from core.web.services.team_workflow.storage_durability import append_record

    records = [
        {"b": 1, "a": "plain"},
        {"unicode": "会议纪要·候选假说", "n": 2},
        {"nested": {"z": [1, 2, {"k": "v"}], "y": None}},
        {},
    ]
    new_store = tmp_path / "new.jsonl"
    old_store = tmp_path / "old.jsonl"
    for record in records:
        append_record(new_store, record)
        # The previous whole-file algorithm, verbatim.
        import json as _json
        import os as _os
        import tempfile as _tempfile

        line = _json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        existing = old_store.read_text(encoding="utf-8") if old_store.exists() else ""
        fd, name = _tempfile.mkstemp(prefix=".old.", suffix=".tmp", dir=tmp_path)
        with _os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(existing)
            handle.write(line)
        _os.replace(name, old_store)
    assert new_store.read_bytes() == old_store.read_bytes()


def test_append_record_scales_with_line_not_file(tmp_path: Path) -> None:
    """Appending to a multi-megabyte store must not rewrite the file.

    The whole-file append rewrote the store per record; the true append
    must complete 2000 appends against a 5 MB store in a bounded time that
    a rewrite-per-append could not meet (5 MB x 2000 rewrites >> budget).
    """
    from core.web.services.team_workflow.storage_durability import append_record

    store = tmp_path / "big.jsonl"
    filler = {"pad": "x" * 512}
    for _ in range(10_000):  # ~5 MB
        append_record(store, filler)
    size_before = store.stat().st_size
    assert size_before > 4_000_000

    import time as _time

    started = _time.monotonic()
    for index in range(2_000):
        append_record(store, {"i": index})
    elapsed = _time.monotonic() - started
    # 2000 O(line) appends with fsync land well under 30s; 2000 whole-file
    # rewrites of a 5 MB store would need minutes of pure IO.
    assert elapsed < 30.0
    assert store.stat().st_size > size_before
    records = read_jsonl_tolerant(store)
    assert len(records) == 12_000


def test_torn_trailing_line_survives_appends_and_quarantine(tmp_path: Path) -> None:
    """A crash-torn last line quarantines on read; later appends stay healthy."""
    from core.web.services.team_workflow.storage_durability import append_record

    store = tmp_path / "torn.jsonl"
    append_record(store, {"ok": 1})
    with open(store, "a", encoding="utf-8") as handle:
        handle.write('{"torn": "trunc')  # no newline, invalid JSON tail

    records = read_jsonl_tolerant(store)
    assert records == [{"ok": 1}]
    append_record(store, {"ok": 2})
    records = read_jsonl_tolerant(store)
    assert records == [{"ok": 1}, {"ok": 2}]


def test_transform_records_does_not_lose_racing_append(tmp_path: Path) -> None:
    """Compaction via transform_records cannot drop a concurrent append."""
    from core.web.services.team_workflow.storage_durability import (
        append_record,
        transform_records,
    )

    store = tmp_path / "race.jsonl"
    for index in range(50):
        append_record(store, {"i": index})
    worker = subprocess.Popen(
        [
            sys.executable,
            "-c",
            _WORKER_SCRIPT.format(
                root=str(Path(__file__).resolve().parents[1]),
                store=str(store),
                count=20,
                worker=99,
            ),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    # Dedupe-compaction in a tight loop while the racer appends.  Each
    # transform locks read+rewrite, so a racer record either landed before
    # a read (kept by the identity transform) or appends after a rewrite
    # (kept on disk).  Losing rows is structurally impossible.
    import time as _time

    deadline = _time.monotonic() + 5.0
    while worker.poll() is None and _time.monotonic() < deadline:
        transform_records(store, lambda rows: rows)
        _time.sleep(0.01)
    _, stderr = worker.communicate(timeout=60)
    assert worker.returncode == 0, stderr.decode("utf-8", "replace")

    records = read_jsonl_tolerant(store)
    racer_indexes = sorted(
        r["index"] for r in records if r.get("worker") == 99
    )
    assert racer_indexes == list(range(20))
