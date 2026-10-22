from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import core.chat.turn_journal as turn_journal
import core.infrastructure.file_lock as file_lock
from core.chat.conversation_invariant import check_conversation_payload_invariant
from core.chat.turn_journal import (
    EVENT_ASSISTANT_MESSAGE,
    EVENT_ASSISTANT_ITEM_COMMITTED,
    EVENT_BRANCH_REBASE,
    EVENT_TOOL_RESULT,
    EVENT_TURN_COMPLETED,
    EVENT_USER_MESSAGE,
    TurnJournalEvent,
    append_turn_event,
    fold_active_events,
    latest_open_turn_id,
    latest_turn_sequence,
    load_latest_turn_events_for_preview,
    load_turn_events,
    model_messages_from_events,
    model_visible_messages_from_events,
    rewrite_turn_events,
    session_turn_items_from_events,
    turn_journal_path,
)
from tests.helpers.managed_processes import managed_processes


@pytest.fixture(autouse=True)
def _isolated_data_home(tmp_path, monkeypatch):
    data_home = tmp_path / "operator-data"
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(data_home))
    return data_home


def test_stopped_assistant_event_projects_explicit_interruption_metadata():
    event = TurnJournalEvent(
        schema_version=1,
        event_id="event-stopped",
        session_id="session-stopped",
        turn_id="turn-stopped",
        sequence=1,
        event_type=EVENT_ASSISTANT_MESSAGE,
        status="stopped",
        timestamp="2026-07-20T00:00:00",
        source="test",
        payload={
            "content": "本轮已按请求停止。",
            "toolCalls": [
                {
                    "id": "call-stopped",
                    "name": "code_symbol_tool",
                    "status": "stopped",
                }
            ],
        },
    )

    messages = model_visible_messages_from_events([event])

    assert len(messages) == 1
    assert messages[0]["metadata"]["interrupted"] is True


def test_completed_assistant_event_does_not_project_interruption_metadata():
    event = TurnJournalEvent(
        schema_version=1,
        event_id="event-completed",
        session_id="session-completed",
        turn_id="turn-completed",
        sequence=1,
        event_type=EVENT_ASSISTANT_MESSAGE,
        status="completed",
        timestamp="2026-07-20T00:00:00",
        source="test",
        payload={"content": "已完成。"},
    )

    messages = model_visible_messages_from_events([event])

    assert len(messages) == 1
    assert messages[0]["metadata"]["interrupted"] is False


def test_completed_turn_usage_enriches_canonical_assistant_message():
    assistant_event = TurnJournalEvent(
        schema_version=1,
        event_id="event-assistant-canonical",
        session_id="session-usage",
        turn_id="turn-usage",
        sequence=1,
        event_type=EVENT_ASSISTANT_ITEM_COMMITTED,
        status="completed",
        timestamp="2026-08-01T00:00:00",
        source="test",
        payload={
            "kind": "assistant_message",
            "channel": "answer",
            "phase": "final_answer",
            "text": "CACHE-PROBE-B-OK",
            "invocationId": "invocation-usage",
            "itemId": "item-usage",
            "revision": 1,
        },
    )
    terminal_event = TurnJournalEvent(
        schema_version=1,
        event_id="event-turn-completed",
        session_id="session-usage",
        turn_id="turn-usage",
        sequence=2,
        event_type=EVENT_TURN_COMPLETED,
        status="completed",
        timestamp="2026-08-01T00:00:01",
        source="test",
        payload={
            "llmUsage": {
                "source": "provider_usage",
                "inputTokens": 15418,
                "outputTokens": 9,
                "totalTokens": 15427,
                "cachedInputTokens": 15360,
                "cacheReadInputTokens": 15360,
                "uncachedInputTokens": 58,
                "cacheHitRate": 15360 / 15418,
            }
        },
    )

    messages = model_visible_messages_from_events([assistant_event, terminal_event])

    assert len(messages) == 1
    assert messages[0]["content"] == "CACHE-PROBE-B-OK"
    assert messages[0]["metadata"]["llmUsage"]["source"] == "provider_usage"
    assert messages[0]["metadata"]["llmUsage"]["cachedInputTokens"] == 15360


def test_concurrent_process_appends_keep_sequences_unique_and_contiguous(tmp_path):
    process_count = 6
    events_per_process = 12
    start_file = tmp_path / "start"
    worker = "\n".join(
        [
            "import os",
            "import time",
            "from pathlib import Path",
            "from core.chat.turn_journal import EVENT_USER_MESSAGE, append_turn_event",
            "start = Path(os.environ['TURN_JOURNAL_START_FILE'])",
            "while not start.exists():",
            "    time.sleep(0.005)",
            "worker_id = os.environ['TURN_JOURNAL_WORKER_ID']",
            f"for index in range({events_per_process}):",
            "    append_turn_event(",
            "        Path(os.environ['TURN_JOURNAL_PROJECT_ROOT']),",
            "        'session-concurrent',",
            "        f'turn-{worker_id}',",
            "        EVENT_USER_MESSAGE,",
            "        payload={'content': f'{worker_id}:{index}'},",
            "    )",
        ]
    )
    with managed_processes() as processes:
        for worker_id in range(process_count):
            env = os.environ.copy()
            env.update(
                {
                    "TURN_JOURNAL_PROJECT_ROOT": str(tmp_path),
                    "TURN_JOURNAL_START_FILE": str(start_file),
                    "TURN_JOURNAL_WORKER_ID": str(worker_id),
                }
            )
            processes.append(
                subprocess.Popen(
                    [sys.executable, "-c", worker],
                    cwd=Path(__file__).resolve().parents[1],
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            )

        start_file.touch()
        failures = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=30)
            if process.returncode:
                failures.append(
                    {"returncode": process.returncode, "stdout": stdout, "stderr": stderr}
                )
        assert failures == []

    events = load_turn_events(tmp_path, "session-concurrent")
    expected_count = process_count * events_per_process
    assert len(events) == expected_count
    assert [event.sequence for event in events] == list(range(1, expected_count + 1))
    assert len({event.event_id for event in events}) == expected_count


def test_journal_file_lock_delegates_to_shared_file_lock_helper(
    tmp_path, monkeypatch
):
    """The journal file lock is a thin wrapper over the shared file-lock helper.

    It must keep the journal's own lock path convention, pass the patient
    journal timeout through, and still leave the sidecar seeded with exactly
    one lock byte. The seed-inside-the-lock discipline itself is covered by
    ``tests/test_file_lock.py``.
    """

    journal_path = tmp_path / "session-lock-seed.jsonl"
    lock_path = journal_path.with_name(f"{journal_path.name}.lock")
    seen: dict[str, object] = {}
    real_locked_sidecar = file_lock.locked_sidecar

    def spy_locked_sidecar(path, *, timeout, **kwargs):
        seen["path"] = Path(path)
        seen["timeout"] = timeout
        return real_locked_sidecar(path, timeout=timeout, **kwargs)

    monkeypatch.setattr(turn_journal, "locked_sidecar", spy_locked_sidecar)

    with turn_journal._journal_file_lock(journal_path):
        pass

    assert seen["path"] == journal_path
    assert seen["timeout"] == turn_journal._JOURNAL_LOCK_TIMEOUT_SECONDS
    assert lock_path.stat().st_size == 1


def test_append_flushes_and_fsyncs_before_return(tmp_path, monkeypatch):
    fsynced_fds: list[int] = []
    real_fsync = os.fsync

    def record_fsync(fd: int) -> None:
        fsynced_fds.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(turn_journal.os, "fsync", record_fsync)

    append_turn_event(
        tmp_path,
        "session-fsync",
        "turn-1",
        EVENT_USER_MESSAGE,
        payload={"content": "durable"},
    )

    assert fsynced_fds
    assert load_turn_events(tmp_path, "session-fsync")[0].payload == {"content": "durable"}


def test_post_terminal_write_raises_dedicated_error_and_reports_settled_turn(tmp_path):
    append_turn_event(tmp_path, "session-settled", "turn-1", EVENT_USER_MESSAGE, payload={"content": "hi"})
    assert turn_journal.turn_has_terminal_event(tmp_path, "session-settled", "turn-1") is False

    append_turn_event(
        tmp_path,
        "session-settled",
        "turn-1",
        turn_journal.EVENT_TURN_INTERRUPTED,
        status="interrupted",
        payload={"reason": "detail_loaded_after_restart"},
    )

    assert turn_journal.turn_has_terminal_event(tmp_path, "session-settled", "turn-1") is True
    with pytest.raises(turn_journal.TurnJournalPostTerminalWriteError) as excinfo:
        append_turn_event(
            tmp_path,
            "session-settled",
            "turn-1",
            EVENT_ASSISTANT_ITEM_COMMITTED,
            payload={"kind": "reasoning", "text": "late"},
        )
    assert isinstance(excinfo.value, ValueError)
    assert "after terminal event" in str(excinfo.value)


def test_turn_has_terminal_event_ignores_unknown_and_empty_turns(tmp_path):
    append_turn_event(tmp_path, "session-settled", "turn-1", EVENT_USER_MESSAGE, payload={"content": "hi"})

    assert turn_journal.turn_has_terminal_event(tmp_path, "session-settled", "") is False
    assert turn_journal.turn_has_terminal_event(tmp_path, "session-settled", "turn-other") is False
    assert turn_journal.turn_has_terminal_event(tmp_path, "session-missing", "turn-1") is False


def test_rewrite_failure_preserves_original_parseable_journal(tmp_path, monkeypatch):
    append_turn_event(
        tmp_path,
        "session-rewrite",
        "turn-1",
        EVENT_USER_MESSAGE,
        payload={"content": "original"},
    )
    path = turn_journal_path(tmp_path, "session-rewrite")
    original_bytes = path.read_bytes()
    replacement = TurnJournalEvent(
        schema_version=2,
        event_id="replacement-000001",
        session_id="session-rewrite",
        turn_id="turn-2",
        sequence=1,
        event_type=EVENT_USER_MESSAGE,
        status="recorded",
        timestamp="2026-07-27T00:00:00Z",
        source="test",
        payload={"content": "replacement"},
    )

    def fail_replace(_source, _target):
        raise OSError("injected replace failure")

    monkeypatch.setattr(turn_journal.os, "replace", fail_replace)
    rewrite_turn_events(tmp_path, "session-rewrite", [replacement])

    assert path.read_bytes() == original_bytes
    assert [event.payload for event in load_turn_events(tmp_path, "session-rewrite")] == [
        {"content": "original"}
    ]
    assert [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert list(path.parent.glob("turn_journal.jsonl.*.tmp")) == []


def test_rewrite_preserves_monotonic_sequence_watermark(tmp_path):
    events = [
        append_turn_event(
            tmp_path,
            "session-watermark",
            "turn-1",
            EVENT_USER_MESSAGE,
            payload={"content": f"message-{index}"},
        )
        for index in range(5)
    ]
    assert [event.sequence for event in events] == [1, 2, 3, 4, 5]
    path = turn_journal_path(tmp_path, "session-watermark")

    rewrite_turn_events(tmp_path, "session-watermark", events[:2])

    # The rewrite dropped sequences 3..5; cursors already published must stay valid.
    assert latest_turn_sequence(tmp_path, "session-watermark") == 5
    turn_journal._forget_sequence(path)
    assert latest_turn_sequence(tmp_path, "session-watermark") == 5

    next_event = append_turn_event(
        tmp_path,
        "session-watermark",
        "turn-2",
        EVENT_USER_MESSAGE,
        payload={"content": "edited"},
    )
    assert next_event.sequence == 6
    assert [event.sequence for event in load_turn_events(tmp_path, "session-watermark")] == [1, 2, 6]


def test_empty_rewrite_keeps_sequence_watermark(tmp_path):
    events = [
        append_turn_event(
            tmp_path,
            "session-watermark-empty",
            "turn-1",
            EVENT_USER_MESSAGE,
            payload={"content": f"message-{index}"},
        )
        for index in range(3)
    ]
    assert events[-1].sequence == 3

    rewrite_turn_events(tmp_path, "session-watermark-empty", [])

    assert latest_turn_sequence(tmp_path, "session-watermark-empty") == 3
    next_event = append_turn_event(
        tmp_path,
        "session-watermark-empty",
        "turn-2",
        EVENT_USER_MESSAGE,
        payload={"content": "after-unlink"},
    )
    assert next_event.sequence == 4


def _append_large_message(project_root: Path, session_id: str, turn_id: str, marker: str) -> TurnJournalEvent:
    # Large enough that the rewritten journal ends up bigger than any prefix
    # cached before the rewrite, so the stale read path takes the "file grew"
    # branch instead of the shrink branch.
    return append_turn_event(
        project_root,
        session_id,
        turn_id,
        EVENT_USER_MESSAGE,
        payload={"content": f"{marker}-{'x' * 8192}"},
    )


def test_rewrite_in_another_process_does_not_resurrect_dropped_events(tmp_path):
    """A reader's cached prefix must not survive a foreign rewrite-and-extend.

    Simulates two processes against one journal: the local read caches the
    prefix, a foreign process rewrites the file (trimming events) and
    re-extends it past the cached size, and the local reader then replays.
    ``rewrite_turn_events`` only forgets the rewriting process's own cache, so
    the pre-rewrite entry is restored here to reproduce what the other
    process's memory still holds.
    """
    session_id = "session-cross-process-rewrite"
    events = [
        append_turn_event(
            tmp_path,
            session_id,
            "turn-1",
            EVENT_USER_MESSAGE,
            payload={"content": f"message-{index}"},
        )
        for index in range(5)
    ]
    path = turn_journal_path(tmp_path, session_id)

    first_read = load_turn_events(tmp_path, session_id)
    assert [event.sequence for event in first_read] == [1, 2, 3, 4, 5]
    stale_cache_entry = dict(turn_journal._TURN_EVENTS_PREFIX_CACHE[str(path)])

    rewrite_turn_events(tmp_path, session_id, events[:2])
    assert turn_journal._sequence_watermark_path(path).exists()
    appended = _append_large_message(tmp_path, session_id, "turn-2", "post-rewrite")
    assert appended.sequence == 6
    # The rewritten-and-extended file must be bigger than the stale cached
    # prefix, otherwise the load path would discard the cache for shrinking
    # anyway and the test would not exercise the growth branch.
    assert path.stat().st_size > int(stale_cache_entry["size"])
    turn_journal._TURN_EVENTS_PREFIX_CACHE[str(path)] = stale_cache_entry

    reloaded = load_turn_events(tmp_path, session_id)

    assert [event.sequence for event in reloaded] == [1, 2, 6]
    assert all("message-2" not in str(event.payload) for event in reloaded)


def test_rewrite_watermark_force_touch_invalidates_prefix_cache_without_value_increase(tmp_path):
    """A rewrite must move the watermark epoch even at an equal value.

    The first rewrite creates the watermark (0 -> N), so its write alone moves
    the epoch. This covers the harder case: a later rewrite whose watermark
    value does not increase. Without ``force_touch`` the watermark file mtime
    would stay put and the foreign reader below would keep trusting its stale
    prefix once the file is re-extended past the cached size.
    """
    session_id = "session-rewrite-epoch"
    events = [
        append_turn_event(
            tmp_path,
            session_id,
            "turn-1",
            EVENT_USER_MESSAGE,
            payload={"content": f"message-{index}"},
        )
        for index in range(4)
    ]
    path = turn_journal_path(tmp_path, session_id)
    watermark_path = turn_journal._sequence_watermark_path(path)

    assert load_turn_events(tmp_path, session_id)
    rewrite_turn_events(tmp_path, session_id, events[:2])
    assert watermark_path.exists()

    # Foreign reader re-reads after the first rewrite: its cache is now keyed
    # on the live watermark signature.
    second_read = load_turn_events(tmp_path, session_id)
    assert [event.sequence for event in second_read] == [1, 2]
    stale_cache_entry = dict(turn_journal._TURN_EVENTS_PREFIX_CACHE[str(path)])
    assert tuple(stale_cache_entry["watermark_signature"]) == turn_journal._sequence_file_signature(watermark_path)

    # Second rewrite keeps one fewer event; the watermark value stays 4, so
    # only a forced touch moves the epoch.
    rewrite_turn_events(tmp_path, session_id, events[:1])
    appended = _append_large_message(tmp_path, session_id, "turn-2", "post-second-rewrite")
    assert appended.sequence == 5
    assert turn_journal._read_sequence_watermark(path) == 4
    assert path.stat().st_size > int(stale_cache_entry["size"])
    turn_journal._TURN_EVENTS_PREFIX_CACHE[str(path)] = stale_cache_entry

    reloaded = load_turn_events(tmp_path, session_id)

    assert [event.sequence for event in reloaded] == [1, 5]
    assert all("message-1" not in str(event.payload) for event in reloaded)


def test_pure_append_still_reuses_cached_prefix_event_objects(tmp_path):
    """Without a rewrite, prefix reuse must stay on the fast path.

    The cached prefix objects are returned by identity, so this fails if the
    watermark-epoch check starts invalidating on plain appends (which never
    touch the watermark file).
    """
    session_id = "session-append-reuse"
    for index in range(3):
        append_turn_event(
            tmp_path,
            session_id,
            "turn-1",
            EVENT_USER_MESSAGE,
            payload={"content": f"message-{index}"},
        )

    first = load_turn_events(tmp_path, session_id)
    assert [event.sequence for event in first] == [1, 2, 3]

    append_turn_event(
        tmp_path,
        session_id,
        "turn-1",
        EVENT_USER_MESSAGE,
        payload={"content": "message-3"},
    )
    second = load_turn_events(tmp_path, session_id)

    assert [event.sequence for event in second] == [1, 2, 3, 4]
    assert second[:3] == list(first)
    assert all(second[index] is first[index] for index in range(3))


def test_prefix_reuse_parses_only_the_appended_tail(tmp_path, monkeypatch):
    """Incremental replay: a pure append must parse only the new tail bytes.

    The acceptance path reloads the ledger after every turn append; the whole
    point of the prefix cache is that the reload resumes from the previously
    parsed byte offset instead of re-parsing the full file.
    """
    session_id = "session-tail-parse"
    for index in range(3):
        append_turn_event(
            tmp_path,
            session_id,
            "turn-1",
            EVENT_USER_MESSAGE,
            payload={"content": f"message-{index}"},
        )
    first = load_turn_events(tmp_path, session_id)
    cached_after_first = dict(turn_journal._TURN_EVENTS_PREFIX_CACHE[str(turn_journal_path(tmp_path, session_id))])

    offsets: list[int] = []
    real_parse = turn_journal._parse_journal_segment

    def spy_parse(handle, *, start_offset):
        offsets.append(int(start_offset))
        return real_parse(handle, start_offset=start_offset)

    monkeypatch.setattr(turn_journal, "_parse_journal_segment", spy_parse)

    append_turn_event(
        tmp_path,
        session_id,
        "turn-1",
        EVENT_USER_MESSAGE,
        payload={"content": "message-3"},
    )
    second = load_turn_events(tmp_path, session_id)

    assert offsets == [int(cached_after_first["size"])]
    assert [event.sequence for event in second] == [1, 2, 3, 4]
    assert all(second[index] is first[index] for index in range(3))


def test_watermark_signature_change_alone_forces_full_reparse(tmp_path, monkeypatch):
    """A watermark epoch change invalidates the cached prefix even without growth.

    ``rewrite_turn_events`` force-touches the watermark to publish the rewrite
    epoch to other processes. A reader whose cache still keys on the old
    watermark signature must fall back to a full re-parse — never stitch its
    stale prefix onto a rewritten file — while the replayed events stay
    identical when the file itself was untouched.
    """
    session_id = "session-watermark-epoch-only"
    for index in range(3):
        append_turn_event(
            tmp_path,
            session_id,
            "turn-1",
            EVENT_USER_MESSAGE,
            payload={"content": f"message-{index}"},
        )
    first = load_turn_events(tmp_path, session_id)
    assert [event.sequence for event in first] == [1, 2, 3]

    offsets: list[int] = []
    real_parse = turn_journal._parse_journal_segment

    def spy_parse(handle, *, start_offset):
        offsets.append(int(start_offset))
        return real_parse(handle, start_offset=start_offset)

    monkeypatch.setattr(turn_journal, "_parse_journal_segment", spy_parse)

    # No append happens here: only the watermark file appears (signature moves
    # from the missing-file sentinel to a real stat), which must defeat the
    # prefix cache entirely.
    turn_journal._write_sequence_watermark(
        turn_journal_path(tmp_path, session_id),
        max(1, turn_journal._read_sequence_watermark(turn_journal_path(tmp_path, session_id))),
        force_touch=True,
    )
    second = load_turn_events(tmp_path, session_id)

    assert offsets == [0]
    assert [event.sequence for event in second] == [1, 2, 3]
    assert [(event.event_type, event.payload.get("content")) for event in second] == [
        (event.event_type, event.payload.get("content")) for event in first
    ]


def test_concurrent_append_and_load_keeps_replay_consistent(tmp_path):
    """Writers and readers on one journal never corrupt the replay."""

    from concurrent.futures import ThreadPoolExecutor

    session_id = "session-concurrent-replay"
    appends_per_writer = 12
    writer_count = 4

    def write_batch(writer_index: int) -> None:
        for index in range(appends_per_writer):
            append_turn_event(
                tmp_path,
                session_id,
                f"turn-{writer_index}",
                EVENT_USER_MESSAGE,
                payload={"content": f"w{writer_index}-{index}"},
            )

    def read_repeatedly() -> None:
        for _ in range(12):
            load_turn_events(tmp_path, session_id)

    with ThreadPoolExecutor(max_workers=writer_count + 2) as pool:
        futures = [pool.submit(write_batch, index) for index in range(writer_count)]
        futures.extend(pool.submit(read_repeatedly) for _ in range(2))
        for future in futures:
            future.result(timeout=60)

    final = load_turn_events(tmp_path, session_id)
    assert len(final) == writer_count * appends_per_writer
    sequences = [event.sequence for event in final]
    assert sorted(sequences) == list(range(1, len(final) + 1))
    assert all(event.event_type == EVENT_USER_MESSAGE for event in final)
    assert all(str(event.payload.get("content") or "").strip() for event in final)


def test_latest_turn_sequence_stat_fast_path_skips_journal_locks(tmp_path, monkeypatch):
    """Warm sequence probes return from stat without thread or sidecar locks.

    The acceptance chain probes the latest sequence several times per submit;
    each probe used to queue on the journal thread lock plus the cross-process
    sidecar lock. A matching cached (journal, watermark) stat signature must
    answer without either lock, and any foreign append must miss, lock once,
    and refresh the cache for the following probes.
    """
    import contextlib

    session_id = "session-seq-fastpath"
    append_turn_event(tmp_path, session_id, "turn-1", EVENT_USER_MESSAGE, payload={"content": "one"})
    append_turn_event(tmp_path, session_id, "turn-1", EVENT_USER_MESSAGE, payload={"content": "two"})
    # Warm the cache through the locked authoritative read once.
    assert latest_turn_sequence(tmp_path, session_id) == 2

    lock_calls: list[int] = []
    real_locked_sidecar = turn_journal.locked_sidecar

    def spy_locked_sidecar(path, *, timeout, **kwargs):
        lock_calls.append(1)
        return real_locked_sidecar(path, timeout=timeout, **kwargs)

    monkeypatch.setattr(turn_journal, "locked_sidecar", spy_locked_sidecar)
    thread_lock_calls: list[int] = []
    real_thread_lock = turn_journal._journal_thread_lock

    @contextlib.contextmanager
    def spy_thread_lock(target):
        thread_lock_calls.append(1)
        with real_thread_lock(target):
            yield

    monkeypatch.setattr(turn_journal, "_journal_thread_lock", spy_thread_lock)

    assert latest_turn_sequence(tmp_path, session_id) == 2
    assert not lock_calls
    assert not thread_lock_calls

    # Foreign append (raw bytes, bypassing the in-process cache update) moves
    # the stat signature: exactly one locked read, then the fresh value.
    with turn_journal_path(tmp_path, session_id).open("ab") as handle:
        handle.write(
            b'{"schemaVersion":2,"eventId":"foreign-9","sessionId":"session-seq-fastpath",'
            b'"turnId":"turn-1","sequence":9,"eventType":"user_message","status":"recorded",'
            b'"timestamp":"2026-10-22T00:00:00+00:00","source":"foreign","payload":{}}\n'
        )
        handle.flush()

    assert latest_turn_sequence(tmp_path, session_id) == 9
    assert len(lock_calls) == 1
    assert len(thread_lock_calls) == 1

    # The locked read refreshed the cache: probes are lock-free again.
    assert latest_turn_sequence(tmp_path, session_id) == 9
    assert len(lock_calls) == 1
    assert len(thread_lock_calls) == 1


def test_append_turn_events_batch_keeps_single_lock_order_and_fsync(tmp_path, monkeypatch):
    """The acceptance scaffold batch: one lock section, order and durability kept."""
    session_id = "session-batch-append"
    lock_calls: list[int] = []
    real_locked_sidecar = turn_journal.locked_sidecar

    def spy_locked_sidecar(path, *, timeout, **kwargs):
        lock_calls.append(1)
        return real_locked_sidecar(path, timeout=timeout, **kwargs)

    monkeypatch.setattr(turn_journal, "locked_sidecar", spy_locked_sidecar)
    fsynced_fds: list[int] = []
    real_fsync = os.fsync

    def record_fsync(fd: int) -> None:
        fsynced_fds.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(turn_journal.os, "fsync", record_fsync)

    events = turn_journal.append_turn_events(
        tmp_path,
        session_id,
        "turn-1",
        (
            {
                "event_type": turn_journal.EVENT_TURN_STARTED,
                "status": "running",
                "payload": {"source": "submit"},
                "source": "test",
                "visible_in_model": False,
                "correlation_id": "submission-1",
            },
            {
                "event_type": EVENT_USER_MESSAGE,
                "status": "recorded",
                "payload": {"content": "hello"},
                "source": "test",
                "correlation_id": "submission-1",
            },
        ),
    )

    # One sidecar acquisition for both appends; append order preserved.
    assert [event.event_type for event in events] == [
        turn_journal.EVENT_TURN_STARTED,
        EVENT_USER_MESSAGE,
    ]
    assert [event.sequence for event in events] == [1, 2]
    assert len(lock_calls) == 1
    # Durability semantics per event: user content fsyncs exactly once,
    # turn_started stays flush-only (deferred).
    assert len(fsynced_fds) == 1

    loaded = load_turn_events(tmp_path, session_id)
    assert [event.event_type for event in loaded] == [
        turn_journal.EVENT_TURN_STARTED,
        EVENT_USER_MESSAGE,
    ]


def test_append_turn_events_empty_specs_is_a_no_op(tmp_path):
    session_id = "session-batch-empty"

    assert turn_journal.append_turn_events(tmp_path, session_id, "turn-1", []) == []
    assert load_turn_events(tmp_path, session_id) == []


def test_append_turn_events_shadow_violation_records_and_still_writes(tmp_path):
    """Shadow-mode violations must not stop the batch.

    A pristine turn receiving a tool-phase event is illegal per the transition
    table but shadow by default: the hook observes it and the write proceeds.
    The agent's hidden-tool-block path relies on exactly this (it journals a
    ``tool_call_started`` as the turn's first event when no scaffold exists).
    """
    violations: list[dict] = []
    turn_journal.set_turn_transition_guard_hook(violations.append)
    try:
        session_id = "session-batch-shadow"
        events = turn_journal.append_turn_events(
            tmp_path,
            session_id,
            "turn-1",
            (
                {
                    "event_type": turn_journal.EVENT_TOOL_CALL_STARTED,
                    "status": "blocked",
                    "payload": {"toolCall": {"name": "hidden_tool", "status": "blocked"}},
                    "source": "agent_hidden_tool_block",
                    "tool_call_id": "call-1",
                    "correlation_id": "call-1",
                    "source_kind": "agent_tool_visibility",
                },
                {
                    "event_type": turn_journal.EVENT_TOOL_RESULT,
                    "status": "blocked",
                    "payload": {"toolCall": {"name": "hidden_tool", "result": "blocked"}},
                    "source": "agent_hidden_tool_block",
                    "tool_call_id": "call-1",
                    "correlation_id": "call-1",
                    "source_kind": "agent_tool_visibility",
                },
            ),
        )

        # Both events are written despite the pristine-tool phase violation.
        assert [event.event_type for event in events] == [
            turn_journal.EVENT_TOOL_CALL_STARTED,
            turn_journal.EVENT_TOOL_RESULT,
        ]
        assert [event.sequence for event in events] == [1, 2]
        shadow_records = [
            record
            for record in violations
            if record.get("mode") == turn_journal.TURN_TRANSITION_GUARD_SHADOW
        ]
        assert len(shadow_records) == 1
        assert shadow_records[0]["eventType"] == turn_journal.EVENT_TOOL_CALL_STARTED

        loaded = load_turn_events(tmp_path, session_id)
        assert [event.event_type for event in loaded] == [
            turn_journal.EVENT_TOOL_CALL_STARTED,
            turn_journal.EVENT_TOOL_RESULT,
        ]
    finally:
        turn_journal.set_turn_transition_guard_hook(None)


def test_append_turn_events_failure_keeps_durable_prefix_and_raises(tmp_path, monkeypatch):
    """Batch failure semantics match sequential appends: prefix stays, raise wins."""
    violations: list[dict] = []
    turn_journal.set_turn_transition_guard_hook(violations.append)
    try:
        session_id = "session-batch-failure"
        append_turn_event(tmp_path, session_id, "turn-1", EVENT_USER_MESSAGE, payload={"content": "hi"})
        append_turn_event(
            tmp_path,
            session_id,
            "turn-1",
            turn_journal.EVENT_TURN_INTERRUPTED,
            status="interrupted",
            payload={"reason": "settled"},
        )

        # Case 1: the second spec hits the post-terminal guard for the settled
        # turn; the first spec (turn-2 scaffold) must remain durably written.
        with pytest.raises(turn_journal.TurnJournalPostTerminalWriteError):
            turn_journal.append_turn_events(
                tmp_path,
                session_id,
                "turn-2",
                (
                    {
                        "event_type": turn_journal.EVENT_TURN_STARTED,
                        "status": "running",
                        "payload": {},
                        "source": "test",
                        "visible_in_model": False,
                    },
                    {
                        "event_type": EVENT_USER_MESSAGE,
                        "status": "recorded",
                        "payload": {"content": "late"},
                        "turn_id": "turn-1",
                        "source": "test",
                    },
                ),
            )
        loaded = load_turn_events(tmp_path, session_id)
        assert any(
            event.turn_id == "turn-2" and event.event_type == turn_journal.EVENT_TURN_STARTED
            for event in loaded
        )
        assert not any(
            event.turn_id == "turn-1"
            and event.event_type == EVENT_USER_MESSAGE
            and str(event.payload.get("content") or "") == "late"
            for event in loaded
        )

        # Case 2: a duplicate terminal for the settled turn is a hard rejection;
        # the batch writes nothing and raises the dedicated error.
        before = len(load_turn_events(tmp_path, session_id))
        with pytest.raises(turn_journal.TurnJournalIllegalTransitionError):
            turn_journal.append_turn_events(
                tmp_path,
                session_id,
                "turn-1",
                (
                    {
                        "event_type": turn_journal.EVENT_TURN_COMPLETED,
                        "status": "completed",
                        "payload": {},
                        "source": "test",
                    },
                ),
            )
        assert len(load_turn_events(tmp_path, session_id)) == before
        hard_records = [
            record
            for record in violations
            if record.get("mode") == turn_journal.TURN_TRANSITION_GUARD_ENFORCE
        ]
        assert hard_records, "hard rejection must reach the telemetry hook"
    finally:
        turn_journal.set_turn_transition_guard_hook(None)


def test_loading_missing_journal_has_no_filesystem_side_effect(tmp_path):
    path = turn_journal_path(tmp_path, "session-missing")

    assert load_turn_events(tmp_path, "session-missing") == []
    assert not path.parent.exists()


def _incident_shape_event(sequence: int, event_type: str, payload: dict, **kwargs) -> TurnJournalEvent:
    return TurnJournalEvent(
        schema_version=1,
        event_id=f"event-empty-{sequence}",
        session_id="session-empty-tool-result",
        turn_id="turn-empty-tool-result",
        sequence=sequence,
        event_type=event_type,
        status="completed",
        timestamp="2026-09-10T08:16:00Z",
        source="test",
        payload=payload,
        **kwargs,
    )


def test_empty_tool_result_with_call_id_keeps_placeholder_and_closes_provider_chain():
    """Regression: session-20260910-170320-944065 empty glob_tool result.

    An EVENT_TOOL_RESULT whose body is empty must still close the assistant
    tool_call at replay; dropping it degraded the chain into
    historical_unresolved_tool_call and the fail-closed send invariant
    permanently rejected every later send for the session.
    """

    events = [
        _incident_shape_event(1, EVENT_USER_MESSAGE, {"content": "帮我找一下文件"}),
        _incident_shape_event(
            2,
            EVENT_ASSISTANT_MESSAGE,
            {
                "content": "",
                "toolCalls": [
                    {
                        "id": "call_01_incident",
                        "name": "glob_tool",
                        "arguments": {"pattern": "**/*.md"},
                    }
                ],
            },
        ),
        _incident_shape_event(
            3,
            EVENT_TOOL_RESULT,
            {
                "toolCall": {
                    "id": "call_01_incident",
                    "name": "glob_tool",
                    "status": "done",
                    "result": [],
                }
            },
            tool_call_id="call_01_incident",
            correlation_id="call_01_incident",
        ),
        _incident_shape_event(4, EVENT_ASSISTANT_MESSAGE, {"content": "没有找到匹配文件。"}),
        _incident_shape_event(5, EVENT_TURN_COMPLETED, {}),
    ]

    model_messages = model_messages_from_events(events)

    assistant_calls = [
        call["id"]
        for message in model_messages
        for call in message.get("tool_calls") or []
        if isinstance(call, dict)
    ]
    assert assistant_calls == ["call_01_incident"]
    tool_messages = [message for message in model_messages if message.get("role") == "tool"]
    assert [message["tool_call_id"] for message in tool_messages] == ["call_01_incident"]
    assert tool_messages[0]["content"] == "（空结果）工具已执行但未返回可见输出。"
    kinds = [str((message.get("metadata") or {}).get("kind") or "") for message in model_messages]
    assert "historical_unresolved_tool_call" not in kinds

    result = check_conversation_payload_invariant(list(model_messages))
    assert result.ok, f"{result.error_type}: {result.message}"


def test_empty_unlinked_tool_result_event_is_still_dropped():
    events = [
        _incident_shape_event(1, EVENT_USER_MESSAGE, {"content": "普通问题"}),
        _incident_shape_event(2, EVENT_TOOL_RESULT, {"result": []}),
        _incident_shape_event(3, EVENT_ASSISTANT_MESSAGE, {"content": "已处理。"}),
        _incident_shape_event(4, EVENT_TURN_COMPLETED, {}),
    ]

    messages = model_visible_messages_from_events(events)

    contents = [str(message.get("content") or "") for message in messages]
    assert "帮我" not in "".join(contents)
    assert "（空结果）工具已执行但未返回可见输出。" not in contents
    assert "已处理。" in contents
    assert [str(message.get("role") or "") for message in messages] == ["user", "assistant"]


def _branch_event(
    event_id: str,
    turn_id: str,
    sequence: int,
    event_type: str,
    *,
    payload: dict | None = None,
    parent_event_id: str = "",
) -> TurnJournalEvent:
    return TurnJournalEvent(
        schema_version=2,
        event_id=event_id,
        session_id="session-branch",
        turn_id=turn_id,
        sequence=sequence,
        event_type=event_type,
        status="recorded",
        timestamp=f"2026-09-12T00:00:{sequence:02d}",
        source="test",
        payload=dict(payload or {}),
        parent_event_id=parent_event_id,
    )


def _rebase_event(
    sequence: int,
    from_event_id: str,
    *,
    operation: str = "edit",
    event_id: str = "event-rebase",
) -> TurnJournalEvent:
    return _branch_event(
        event_id,
        "turn-new",
        sequence,
        EVENT_BRANCH_REBASE,
        payload={
            "operation": operation,
            "branchId": "branch-1",
            "fromEventId": from_event_id,
            "replacedTurnIds": [],
        },
        parent_event_id=from_event_id,
    )


def _fold_fixture() -> list[TurnJournalEvent]:
    return [
        _branch_event("event-u1", "turn-1", 1, EVENT_USER_MESSAGE, payload={"content": "原始需求"}),
        _branch_event("event-a1", "turn-1", 2, EVENT_ASSISTANT_MESSAGE, payload={"content": "原始回答"}),
        _branch_event("event-u2", "turn-2", 3, EVENT_USER_MESSAGE, payload={"content": "后续追问"}),
        _branch_event("event-a2", "turn-2", 4, EVENT_ASSISTANT_MESSAGE, payload={"content": "后续回答"}),
    ]


def test_unknown_event_type_stays_readable_and_invisible_to_replay(tmp_path):
    append_turn_event(
        tmp_path, "session-unknown", "turn-1", EVENT_USER_MESSAGE, status="recorded", payload={"content": "问题"}
    )
    append_turn_event(
        tmp_path, "session-unknown", "turn-1", "future_schema_event", status="recorded", payload={"future": True}
    )
    append_turn_event(
        tmp_path, "session-unknown", "turn-1", EVENT_ASSISTANT_MESSAGE, status="completed", payload={"content": "回答"}
    )

    events = load_turn_events(tmp_path, "session-unknown")

    assert [event.event_type for event in events] == [
        EVENT_USER_MESSAGE,
        "future_schema_event",
        EVENT_ASSISTANT_MESSAGE,
    ]
    visible = model_visible_messages_from_events(events)
    assert [str(message.get("content") or "") for message in visible] == ["问题", "回答"]
    model_messages = model_messages_from_events(events)
    assert [str(message.get("content") or "") for message in model_messages] == ["问题", "回答"]


def test_unknown_event_type_marks_preview_unsafe_for_canonical_fallback(tmp_path):
    append_turn_event(
        tmp_path, "session-preview", "turn-1", EVENT_USER_MESSAGE, status="recorded", payload={"content": "问题"}
    )
    append_turn_event(
        tmp_path, "session-preview", "turn-1", "future_schema_event", status="recorded", payload={}
    )
    append_turn_event(
        tmp_path, "session-preview", "turn-1", EVENT_ASSISTANT_MESSAGE, status="completed", payload={"content": "回答"}
    )

    events, _reached_start, safe = load_latest_turn_events_for_preview(tmp_path, "session-preview")

    assert safe is False
    assert not any(event.event_type == "future_schema_event" for event in events)


def test_fold_active_events_is_identity_without_rebase():
    events = _fold_fixture()

    assert fold_active_events(events) == events


def test_fold_active_events_cuts_superseded_segment_after_fork_point():
    events = [
        *_fold_fixture(),
        _rebase_event(5, "event-a1"),
        _branch_event("event-u2b", "turn-3", 6, EVENT_USER_MESSAGE, payload={"content": "编辑后的需求"}),
    ]

    active = fold_active_events(events)

    assert [event.event_id for event in active] == ["event-u1", "event-a1", "event-u2b"]


def test_fold_active_events_supports_nested_rebase():
    events = [
        *_fold_fixture(),
        _rebase_event(5, "event-a1", event_id="event-rebase-1"),
        _branch_event("event-u2b", "turn-3", 6, EVENT_USER_MESSAGE, payload={"content": "编辑后的需求"}),
        _branch_event("event-a2b", "turn-3", 7, EVENT_ASSISTANT_MESSAGE, payload={"content": "新回答"}),
        _rebase_event(8, "event-u1", event_id="event-rebase-2"),
        _branch_event("event-u1c", "turn-4", 9, EVENT_USER_MESSAGE, payload={"content": "重开"}),
    ]

    active = fold_active_events(events)

    assert [event.event_id for event in active] == ["event-u1", "event-u1c"]


def test_fold_active_events_empty_fork_point_clears_history():
    events = [
        *_fold_fixture(),
        _rebase_event(5, ""),
        _branch_event("event-u1b", "turn-3", 6, EVENT_USER_MESSAGE, payload={"content": "从零开始"}),
    ]

    active = fold_active_events(events)

    assert [event.event_id for event in active] == ["event-u1b"]


def test_fold_active_events_keeps_path_when_fork_point_is_missing():
    events = [
        *_fold_fixture(),
        _rebase_event(5, "event-missing"),
    ]

    active = fold_active_events(events)

    assert [event.event_id for event in active] == [event.event_id for event in _fold_fixture()]


def test_fold_active_events_head_select_restores_superseded_branch():
    events = [
        *_fold_fixture(),
        _rebase_event(5, "event-a1", event_id="event-rebase-1"),
        _branch_event("event-u2b", "turn-3", 6, EVENT_USER_MESSAGE, payload={"content": "编辑后的需求"}),
        _branch_event("event-a2b", "turn-3", 7, EVENT_ASSISTANT_MESSAGE, payload={"content": "新回答"}),
        _rebase_event(8, "event-a2", operation="head_select", event_id="event-rebase-2"),
    ]

    active = fold_active_events(events)

    assert [event.event_id for event in active] == ["event-u1", "event-a1", "event-u2", "event-a2"]


def test_fold_active_events_head_select_then_new_message_continues_from_target():
    events = [
        *_fold_fixture(),
        _rebase_event(5, "event-a1", event_id="event-rebase-1"),
        _branch_event("event-u2b", "turn-3", 6, EVENT_USER_MESSAGE, payload={"content": "编辑后的需求"}),
        _branch_event("event-a2b", "turn-3", 7, EVENT_ASSISTANT_MESSAGE, payload={"content": "新回答"}),
        _rebase_event(8, "event-a2", operation="head_select", event_id="event-rebase-2"),
        _branch_event("event-u3", "turn-4", 9, EVENT_USER_MESSAGE, payload={"content": "沿旧分支继续"}),
    ]

    active = fold_active_events(events)

    assert [event.event_id for event in active] == [
        "event-u1",
        "event-a1",
        "event-u2",
        "event-a2",
        "event-u3",
    ]


def test_fold_active_events_head_select_to_active_tip_is_idempotent():
    events = [
        *_fold_fixture(),
        _rebase_event(5, "event-a2", operation="head_select", event_id="event-rebase-1"),
    ]

    active = fold_active_events(events)

    assert [event.event_id for event in active] == ["event-u1", "event-a1", "event-u2", "event-a2"]


def test_fold_active_events_head_select_to_unknown_event_keeps_current_path():
    events = [
        *_fold_fixture(),
        _rebase_event(5, "event-missing", operation="head_select", event_id="event-rebase-1"),
    ]

    active = fold_active_events(events)

    assert [event.event_id for event in active] == [event.event_id for event in _fold_fixture()]


def test_fold_active_events_ignores_unknown_rebase_operation():
    events = [
        *_fold_fixture(),
        _rebase_event(5, "event-a1", operation="future_operation"),
    ]

    active = fold_active_events(events)

    assert [event.event_id for event in active] == ["event-u1", "event-a1", "event-u2", "event-a2"]


def test_turn_items_follow_the_active_branch():
    events = [
        _branch_event("event-u1", "turn-1", 1, EVENT_USER_MESSAGE, payload={"content": "原始需求"}),
        _branch_event("event-a1", "turn-1", 2, EVENT_ASSISTANT_MESSAGE, payload={"content": "原始回答"}),
        _branch_event("event-ts2", "turn-2", 3, "turn_started", payload={}),
        _branch_event("event-u2", "turn-2", 4, EVENT_USER_MESSAGE, payload={"content": "后续追问"}),
        _branch_event(
            "event-item2",
            "turn-2",
            5,
            EVENT_ASSISTANT_ITEM_COMMITTED,
            payload={"kind": "assistant_message", "text": "后续回答", "itemId": "item-2", "revision": 1},
        ),
        _rebase_event(6, "event-a1", event_id="event-rebase"),
        _branch_event("event-ts3", "turn-3", 7, "turn_started", payload={}),
        _branch_event("event-u3", "turn-3", 8, EVENT_USER_MESSAGE, payload={"content": "编辑后的需求"}),
        _branch_event(
            "event-item3",
            "turn-3",
            9,
            EVENT_ASSISTANT_ITEM_COMMITTED,
            payload={"kind": "assistant_message", "text": "新回答", "itemId": "item-3", "revision": 1},
        ),
    ]

    items = session_turn_items_from_events(events)

    assert [item["text"] for item in items] == ["新回答"]


def test_latest_open_turn_id_ignores_superseded_open_turn():
    events = [
        _branch_event("event-ts1", "turn-1", 1, "turn_started", payload={}),
        _branch_event("event-u1", "turn-1", 2, EVENT_USER_MESSAGE, payload={"content": "原始需求"}),
        _rebase_event(3, "", event_id="event-rebase"),
    ]

    assert latest_open_turn_id(events) == ""


def test_latest_open_turn_id_ignores_completed_turn_after_head_select():
    events = [
        _branch_event("event-ts1", "turn-1", 1, "turn_started", payload={}),
        _branch_event(
            "event-u1",
            "turn-1",
            2,
            EVENT_USER_MESSAGE,
            parent_event_id="event-ts1",
            payload={"content": "原始需求"},
        ),
        _branch_event(
            "event-a1",
            "turn-1",
            3,
            EVENT_ASSISTANT_MESSAGE,
            parent_event_id="event-u1",
            payload={"content": "原始回答"},
        ),
        _branch_event(
            "event-tc1",
            "turn-1",
            4,
            EVENT_TURN_COMPLETED,
            parent_event_id="event-a1",
            payload={},
        ),
        _rebase_event(5, "event-u1", event_id="event-rebase-1"),
        _branch_event(
            "event-u2b",
            "turn-new",
            6,
            EVENT_USER_MESSAGE,
            parent_event_id="event-rebase-1",
            payload={"content": "编辑后需求"},
        ),
        _branch_event(
            "event-a2b",
            "turn-new",
            7,
            EVENT_ASSISTANT_MESSAGE,
            parent_event_id="event-u2b",
            payload={"content": "编辑后回答"},
        ),
        _branch_event(
            "event-tc2",
            "turn-new",
            8,
            EVENT_TURN_COMPLETED,
            parent_event_id="event-a2b",
            payload={},
        ),
        _rebase_event(9, "event-a1", operation="head_select", event_id="event-rebase-2"),
    ]

    active = fold_active_events(events)

    assert [event.event_id for event in active] == ["event-ts1", "event-u1", "event-a1"]
    assert latest_open_turn_id(events) == ""


def test_sequence_cache_key_resolves_each_path_once(tmp_path, monkeypatch):
    """Warm _sequence_cache_key hits must not re-resolve; paths stay isolated."""

    turn_journal._SEQUENCE_RESOLVED_PATH_CACHE.clear()
    calls = {"count": 0}
    original_resolve = Path.resolve

    def counting_resolve(self, *args, **kwargs):
        calls["count"] += 1
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", counting_resolve)

    path = tmp_path / "session-a" / "turn_journal.jsonl"
    first = turn_journal._sequence_cache_key(path)
    assert calls["count"] == 1
    assert turn_journal._sequence_cache_key(path) == first
    assert calls["count"] == 1

    other = tmp_path / "session-b" / "turn_journal.jsonl"
    second = turn_journal._sequence_cache_key(other)
    assert calls["count"] == 2
    assert second != first

    monkeypatch.undo()
    assert first == str(path.resolve())
    assert second == str(other.resolve())
    turn_journal._SEQUENCE_RESOLVED_PATH_CACHE.clear()


def test_sequence_cache_key_oserror_fallback_is_not_cached(tmp_path, monkeypatch):
    """A transient resolve failure keeps retrying instead of freezing a key."""

    turn_journal._SEQUENCE_RESOLVED_PATH_CACHE.clear()

    def raising_resolve(self, *args, **kwargs):
        raise OSError("resolve unavailable")

    monkeypatch.setattr(Path, "resolve", raising_resolve)
    path = tmp_path / "session-fallback" / "turn_journal.jsonl"
    assert turn_journal._sequence_cache_key(path) == str(path)
    assert str(path) not in turn_journal._SEQUENCE_RESOLVED_PATH_CACHE

    monkeypatch.undo()
    assert turn_journal._sequence_cache_key(path) == str(path.resolve())
    turn_journal._SEQUENCE_RESOLVED_PATH_CACHE.clear()
