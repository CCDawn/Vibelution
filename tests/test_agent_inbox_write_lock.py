# -*- coding: utf-8 -*-
"""Agent inbox JSONL write serialization: append x rewrite must not lose rows.

``agent_inbox_messages.jsonl`` has two writer shapes. Delivery
(``write_agent_inbox_message``) appends one row through ``_append_jsonl``;
consume / read-receipt / revoke / promote read the whole file, mutate rows in
memory and rewrite it through ``_write_jsonl``. Without one shared lock a
rewrite racing an append replaces the file with a snapshot taken before the
append landed (the delivered row vanishes), and two rewrites racing each
other drop whichever receipt was written first. The fix routes every write
of one target file through the same per-target cross-process lock, keeps the
read -> mutate -> rewrite span inside it, and rewrites via temp-file +
``os.replace``. On Windows that replace raises ``PermissionError`` while any
reader still holds a handle on the target, so the rewrite retries briefly and
then re-raises the original error instead of swallowing it.

The concurrency tests drive the real helpers through the public inbox
functions with a fake facade, so the span under test is the production one.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from core.infrastructure.file_lock import cross_process_file_lock
from core.web.services import personal_assistant_dispatch_ledger as dispatch_ledger
from core.web.services.agent_directory import ops_residual, repair_store

AGENT_ID = "agent-inbox-lock"
SESSION_ID = "session-inbox-lock"
INBOX_NAME = "agent_inbox_messages.jsonl"

_IS_WINDOWS = os.name == "nt"


def _read_rows(path: Path) -> list[dict[str, Any]]:
    """Strict reader: every non-empty line must parse (torn lines fail loudly)."""

    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


@pytest.fixture
def inbox_env(tmp_path, monkeypatch):
    """Fake facade that routes JSONL helpers back to the real ops_residual ones.

    Everything the inbox functions need from the facade is stubbed, except the
    three JSONL helpers (append / read / rewrite) and the hydration hook, which
    stay real so the on-disk behaviour under test is the production one.
    """

    workspace = tmp_path / "ws"
    (workspace / "events").mkdir(parents=True)
    path = workspace / "events" / INBOX_NAME
    agent = {
        "agentId": AGENT_ID,
        "agentCode": "A900",
        "displayName": "Inbox Lock Target",
        "directSessionId": SESSION_ID,
        "workspacePath": str(workspace),
    }
    memory_events: list[tuple[Any, ...]] = []

    service = SimpleNamespace(
        get_agent=lambda agent_id, include_archived=False: agent if agent_id == AGENT_ID else None,
        AgentNotFoundError=ValueError,
        AgentMessageNotFoundError=ValueError,
        AgentDirectoryError=ValueError,
        utc_now_iso=lambda: datetime.now(timezone.utc).isoformat(),
        _new_event_id=lambda prefix: f"{prefix}-{threading.get_ident()}-{time.perf_counter_ns()}",
        trim_lines=lambda text, max_lines=4: str(text or "")[:200],
        _safe_metadata=lambda metadata: dict(metadata or {}),
        _agent_inbox_thread_id=lambda src, tgt: "thread-lock",
        _agent_workspace_event_path=lambda target_agent, name: workspace / "events" / name,
        _append_jsonl=ops_residual._append_jsonl,
        _read_jsonl=ops_residual._read_jsonl,
        _write_jsonl=ops_residual._write_jsonl,
        record_agent_api_hydration_event_file_changed=lambda changed_path: None,
        _record_memory_event=lambda *args, **kwargs: memory_events.append((args, kwargs)),
        count_agent_inbox_messages_for_agent=lambda agent_id, status="pending": sum(
            1 for row in _read_rows(path) if str(row.get("status") or "pending") == status
        ),
    )
    monkeypatch.setattr(ops_residual, "_service", lambda: service)
    # Ledger observers are best-effort sqlite side effects outside this lane;
    # keep them out of the timing-sensitive loops.
    monkeypatch.setattr(dispatch_ledger, "record_inbox_message", lambda row: None)
    monkeypatch.setattr(dispatch_ledger, "record_inbox_status_change", lambda *args, **kwargs: None)
    return SimpleNamespace(path=path, agent=agent, service=service, memory_events=memory_events)


def _run_threads(workers: list[threading.Thread], *, join_timeout: float = 60.0) -> None:
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=join_timeout)
    stuck = [worker.name for worker in workers if worker.is_alive()]
    assert not stuck, f"worker threads did not finish: {stuck}"


# --------------------------------------------------------------------------
# Evidence: delivery append x receipt rewrite on the same inbox file.
# --------------------------------------------------------------------------


def test_concurrent_delivery_and_read_receipts_keep_every_row(inbox_env, monkeypatch):
    """Appends racing whole-file rewrites must neither drop rows nor receipts.

    Appenders deliver through ``write_agent_inbox_message``; rewriters mark
    the rows delivered so far as read through ``mark_agent_inbox_messages_read``
    and occasionally consume one through ``consume_agent_inbox_message``.
    Afterwards every delivered id must still be on disk exactly once, every
    line must parse, and every receipt a rewriter reported must be visible.
    """

    appender_count, appends_per_thread = 6, 40
    rewriter_count, rewrites_per_thread = 4, 40
    expected_ids = {f"msg-{thread}-{index}" for thread in range(appender_count) for index in range(appends_per_thread)}

    delivered: list[str] = []
    delivered_guard = threading.Lock()
    reported_read: set[str] = set()
    reported_consumed: set[str] = set()
    reported_guard = threading.Lock()
    failures: list[BaseException] = []
    barrier = threading.Barrier(appender_count + rewriter_count)

    # Force frequent GIL hand-offs so read -> rewrite windows interleave with
    # appends even on a fast machine.
    previous_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-5)

    def appender(thread_index: int) -> None:
        try:
            barrier.wait(timeout=10)
            for index in range(appends_per_thread):
                message_id = f"msg-{thread_index}-{index}"
                ops_residual.write_agent_inbox_message(
                    AGENT_ID,
                    content=f"body {message_id}",
                    message_id=message_id,
                    metadata={"wakeRequested": True},
                )
                with delivered_guard:
                    delivered.append(message_id)
        except BaseException as exc:  # pragma: no cover - surfaced via assertion
            failures.append(exc)

    def rewriter(thread_index: int) -> None:
        try:
            barrier.wait(timeout=10)
            for index in range(rewrites_per_thread):
                with delivered_guard:
                    snapshot = list(delivered)
                if not snapshot:
                    time.sleep(0.001)
                    continue
                if index % 5 == 4:
                    target = snapshot[(thread_index + index) % len(snapshot)]
                    row = ops_residual.consume_agent_inbox_message(AGENT_ID, target, consumed_by_session_id=SESSION_ID)
                    assert row["status"] == "consumed"
                    with reported_guard:
                        reported_consumed.add(target)
                    continue
                receipt = ops_residual.mark_agent_inbox_messages_read(
                    AGENT_ID,
                    snapshot,
                    read_by_session_id=SESSION_ID,
                    read_by_turn_id=f"turn-{thread_index}-{index}",
                )
                with reported_guard:
                    reported_read.update(receipt["readMessageIds"])
        except BaseException as exc:  # pragma: no cover - surfaced via assertion
            failures.append(exc)

    try:
        workers = [threading.Thread(target=appender, args=(i,), name=f"append-{i}") for i in range(appender_count)]
        workers += [threading.Thread(target=rewriter, args=(i,), name=f"rewrite-{i}") for i in range(rewriter_count)]
        _run_threads(workers)
    finally:
        sys.setswitchinterval(previous_interval)

    assert not failures, f"worker raised: {failures[0]!r}"

    rows = _read_rows(inbox_env.path)  # raises on a torn line
    ids_on_disk = [str(row.get("messageId") or "") for row in rows]
    assert len(ids_on_disk) == len(expected_ids), (
        f"lost or duplicated rows: expected {len(expected_ids)} rows, found {len(ids_on_disk)}"
    )
    assert set(ids_on_disk) == expected_ids, (
        f"missing={sorted(expected_ids - set(ids_on_disk))[:10]} extra={sorted(set(ids_on_disk) - expected_ids)[:10]}"
    )
    by_id = {str(row.get("messageId") or ""): row for row in rows}
    missing_receipts = sorted(mid for mid in reported_read if not str(by_id[mid].get("readAt") or "").strip())
    assert not missing_receipts, f"read receipts overwritten by a racing rewrite: {missing_receipts[:10]}"
    lost_consumes = sorted(mid for mid in reported_consumed if str(by_id[mid].get("status") or "") != "consumed")
    assert not lost_consumes, f"consume state overwritten by a racing rewrite: {lost_consumes[:10]}"


# --------------------------------------------------------------------------
# Mechanism: both helpers take the per-target cross-process lock.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("helper", ["_append_jsonl", "_write_jsonl"])
def test_jsonl_helpers_wait_for_the_per_target_file_lock(inbox_env, helper):
    """An append or rewrite must block while another holder owns ``<path>.lock``.

    The holder is a different thread, so the reentrant in-process half of the
    lock does not short-circuit; this proves the helpers really serialize on
    the same sidecar an external ``cross_process_file_lock(path)`` uses.
    """

    path = inbox_env.path
    ops_residual._append_jsonl(path, {"messageId": "seed", "status": "pending"})
    hold_seconds = 0.4
    lock_held = threading.Event()
    release = threading.Event()

    def holder() -> None:
        with cross_process_file_lock(path, timeout=5.0):
            lock_held.set()
            release.wait(timeout=5.0)

    holder_thread = threading.Thread(target=holder, name="lock-holder")
    holder_thread.start()
    assert lock_held.wait(timeout=5.0)
    timer = threading.Timer(hold_seconds, release.set)
    timer.start()
    started = time.perf_counter()
    try:
        if helper == "_append_jsonl":
            ops_residual._append_jsonl(path, {"messageId": "after-lock", "status": "pending"})
        else:
            ops_residual._write_jsonl(path, [{"messageId": "rewritten", "status": "pending"}])
    finally:
        release.set()
        timer.cancel()
        holder_thread.join(timeout=5.0)
    elapsed = time.perf_counter() - started
    assert elapsed >= hold_seconds * 0.8, f"{helper} did not wait for the file lock (took {elapsed:.3f}s)"
    rows = _read_rows(path)
    if helper == "_append_jsonl":
        assert [row["messageId"] for row in rows] == ["seed", "after-lock"]
    else:
        assert [row["messageId"] for row in rows] == ["rewritten"]


def test_read_modify_rewrite_span_is_reentrant_for_the_same_thread(inbox_env):
    """A caller already holding the inbox lock can still consume (no self-deadlock)."""

    path = inbox_env.path
    ops_residual.write_agent_inbox_message(AGENT_ID, content="hello", message_id="msg-reentrant")
    with cross_process_file_lock(path, timeout=5.0):
        row = ops_residual.consume_agent_inbox_message(AGENT_ID, "msg-reentrant", consumed_by_session_id=SESSION_ID)
    assert row["status"] == "consumed"
    assert _read_rows(path)[0]["status"] == "consumed"


# --------------------------------------------------------------------------
# Windows: readers holding a handle make os.replace raise PermissionError.
# --------------------------------------------------------------------------


def _hold_reverse_iterator_handle(path: Path, *, hold_seconds: float, holding: threading.Event) -> threading.Thread:
    """Start the real reverse line iterator, stop after one line, keep it open.

    This is the exact shape of ``_read_recent_jsonl``: a suspended generator
    whose ``with path.open("rb")`` frame is still alive, so the target stays
    open (without ``FILE_SHARE_DELETE``) until the generator is closed.
    """

    def run() -> None:
        iterator = repair_store._iter_text_lines_reverse(path)
        next(iterator)
        holding.set()
        try:
            time.sleep(hold_seconds)
        finally:
            iterator.close()

    thread = threading.Thread(target=run, name="reverse-reader")
    thread.start()
    assert holding.wait(timeout=5.0)
    return thread


@pytest.mark.skipif(not _IS_WINDOWS, reason="os.replace sharing violation is Windows-specific")
def test_os_replace_is_blocked_while_the_reverse_iterator_holds_the_target(inbox_env):
    """Evidence for the trap: a suspended reverse iterator blocks ``os.replace``."""

    path = inbox_env.path
    ops_residual._append_jsonl(path, {"messageId": "seed", "status": "pending"})
    holding = threading.Event()
    reader = _hold_reverse_iterator_handle(path, hold_seconds=0.5, holding=holding)
    replacement = path.with_name("replacement.tmp")
    replacement.write_text('{"messageId": "replacement"}\n', encoding="utf-8")
    try:
        with pytest.raises(PermissionError):
            os.replace(replacement, path)
    finally:
        reader.join(timeout=5.0)
        if replacement.exists():
            replacement.unlink()
    assert _read_rows(path) == [{"messageId": "seed", "status": "pending"}]


@pytest.mark.skipif(not _IS_WINDOWS, reason="os.replace sharing violation is Windows-specific")
def test_rewrite_absorbs_a_transient_reader_handle_on_windows(inbox_env):
    """A rewrite racing a short-lived reader succeeds once the reader lets go."""

    path = inbox_env.path
    ops_residual._append_jsonl(path, {"messageId": "seed", "status": "pending"})
    holding = threading.Event()
    reader = _hold_reverse_iterator_handle(path, hold_seconds=0.3, holding=holding)
    started = time.perf_counter()
    try:
        ops_residual._write_jsonl(path, [{"messageId": "seed", "status": "consumed"}])
        elapsed = time.perf_counter() - started
    finally:
        reader.join(timeout=5.0)
    assert elapsed >= 0.2, f"rewrite finished before the reader released its handle ({elapsed:.3f}s)"
    assert _read_rows(path) == [{"messageId": "seed", "status": "consumed"}]
    assert not list(path.parent.glob(f".{path.name}.*.tmp")), "temp file leaked after retry"


def test_reverse_scan_closes_the_iterator_on_an_early_cap_stop(inbox_env, monkeypatch):
    """``_scan_inbox_reverse`` must close the reverse iterator explicitly.

    Under the old ``nullcontext`` wrap, a scan that stopped at ``cap`` left a
    suspended generator whose ``with path.open("rb")`` frame was still alive;
    only CPython refcounting released the inbox handle (and an exception
    traceback holding the frame would keep it open for good). ``closing``
    closes it the moment the scan exits its ``with`` block, so a concurrent
    inbox rewrite's ``os.replace`` is never blocked by a leftover handle.
    """

    from core.web.services import agent_directory_service as directory
    from core.web.services import personal_assistant_dispatches_service as dispatches_service

    path = inbox_env.path
    for index in range(20):
        ops_residual._append_jsonl(path, {"messageId": f"m{index}", "sourceAgentId": "pa"})

    real_iter = directory._iter_text_lines_reverse
    closed = {"value": False}

    def spy(target: Path):
        inner = real_iter(target)

        class _SpyLines:
            def __iter__(self):
                return iter(inner)

            def close(self):
                closed["value"] = True
                inner.close()

        return _SpyLines()

    monkeypatch.setattr(directory, "_iter_text_lines_reverse", spy)
    matches = dispatches_service._scan_inbox_reverse(path, predicate=lambda row: True, cap=1)
    assert len(matches) == 1, "sanity: cap=1 scan should stop at the newest row"
    assert closed["value"] is True, "reverse iterator was not closed when the scan stopped early"


@pytest.mark.skipif(not _IS_WINDOWS, reason="os.replace sharing violation is Windows-specific")
def test_rewrite_reraises_permission_error_after_bounded_retry(inbox_env, monkeypatch):
    """Past the retry budget the original ``PermissionError`` must surface.

    No in-place fallback, no silent success: the target keeps its previous
    content, the temp file is cleaned up, and the caller sees the error.
    """

    path = inbox_env.path
    ops_residual._append_jsonl(path, {"messageId": "seed", "status": "pending"})
    monkeypatch.setattr(ops_residual, "_JSONL_REPLACE_RETRY_TIMEOUT_SECONDS", 0.2)
    holding = threading.Event()
    reader = _hold_reverse_iterator_handle(path, hold_seconds=1.2, holding=holding)
    started = time.perf_counter()
    try:
        with pytest.raises(PermissionError):
            ops_residual._write_jsonl(path, [{"messageId": "seed", "status": "consumed"}])
        elapsed = time.perf_counter() - started
    finally:
        reader.join(timeout=5.0)
    assert 0.2 <= elapsed < 1.0, f"retry budget not honoured: {elapsed:.3f}s"
    assert _read_rows(path) == [{"messageId": "seed", "status": "pending"}], "target must stay untouched"
    assert not list(path.parent.glob(f".{path.name}.*.tmp")), "temp file leaked after failed replace"


# --------------------------------------------------------------------------
# Contract: public results unchanged.
# --------------------------------------------------------------------------


def test_public_inbox_results_are_unchanged_by_the_lock(inbox_env):
    """Return shapes and the readAt / consumedAt three-state timeline stay as before."""

    path = inbox_env.path
    written = ops_residual.write_agent_inbox_message(AGENT_ID, content="hello", message_id="msg-1")
    assert written["messageId"] == "msg-1"
    assert written["status"] == "pending"
    assert written["readAt"] == ""
    assert written["consumedAt"] == ""

    unread = ops_residual.mark_agent_inbox_messages_read(AGENT_ID, ["missing"], read_by_session_id=SESSION_ID)
    assert unread == {"agentId": AGENT_ID, "readCount": 0, "readMessageIds": []}

    read = ops_residual.mark_agent_inbox_messages_read(AGENT_ID, ["msg-1"], read_by_session_id=SESSION_ID)
    assert read == {"agentId": AGENT_ID, "readCount": 1, "readMessageIds": ["msg-1"]}
    on_disk = _read_rows(path)[0]
    assert on_disk["readAt"] and on_disk["consumedAt"] == ""

    consumed = ops_residual.consume_agent_inbox_message(AGENT_ID, "msg-1", consumed_by_session_id=SESSION_ID)
    assert consumed["status"] == "consumed"
    assert consumed["consumedBySessionId"] == SESSION_ID
    on_disk = _read_rows(path)[0]
    assert on_disk["readAt"] and on_disk["consumedAt"]

    summary = ops_residual.consume_all_agent_inbox_messages(AGENT_ID, consumed_by_session_id=SESSION_ID)
    assert summary == {
        "agentId": AGENT_ID,
        "consumed": True,
        "consumedCount": 0,
        "consumedMessageIds": [],
        "remainingPendingCount": 0,
    }

    with pytest.raises(ValueError):
        ops_residual.consume_agent_inbox_message(AGENT_ID, "missing")

    revoked = ops_residual.revoke_agent_inbox_message(AGENT_ID, "msg-1", reason="cleanup")
    assert revoked["status"] == "revoked"
    assert revoked["promptEligible"] is False
    assert _read_rows(path)[0]["status"] == "revoked"
    # Every write above went through the shared per-target lock sidecar.
    assert (path.parent / f"{path.name}.lock").is_file()
