"""Private reminder receipts, not a scheduler or a migration/cutover capability.

The caller keeps this context open for its entire notification-owner lifetime.
Native Windows handles pin every directory plus both SQLite leaves; short
BEGIN IMMEDIATE transactions arbitrate IDs and a database-owned capacity limit.
Only a newly committed reservation permits ONE external submission attempt.
Any existing pending record requires reconciliation, never automatic replay.
Submission is not evidence that a person saw a notification; opened records
require an actual interaction callback from the trusted delivery owner.

PERSIST/FULL delegates journal recovery and Windows flushes to the project's
bundled APSW/SQLite. This protects against process crashes under SQLite's normal
filesystem assumptions, not hostile same-user byte writes or faulty hardware.
No ordinary Session database/schema, legacy executor or product switch is used.
"""
from __future__ import annotations

import ctypes
import hashlib
import os
import re
import secrets
import threading
from contextlib import ExitStack, contextmanager
from pathlib import Path

import apsw

from .migration_io import pinned_target_directory, validate_path
from core.web.services.personal_assistant_project.windows_read import _api, _verify


class ReminderReceiptError(RuntimeError):
    """Stable content-free failure; callers must not convert errors to a resend."""


_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_HEX = re.compile(r"[a-f0-9]{64}\Z")
_CHANNELS = {"assistant_window", "system_notification", "attention_fallback"}
_META_SQL = """CREATE TABLE receipt_meta (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    owner_id TEXT NOT NULL,
    maximum INTEGER NOT NULL CHECK(maximum BETWEEN 1 AND 4096)
) STRICT"""
_ATTEMPT_SQL = """CREATE TABLE reminder_receipts (
    event_id TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL CHECK(length(token_hash)=64),
    state TEXT NOT NULL CHECK(state IN ('pending','submitted','opened')),
    channel TEXT,
    CHECK((state='pending' AND channel IS NULL) OR
          (state IN ('submitted','opened') AND channel IN
           ('assistant_window','system_notification','attention_fallback')))
) STRICT"""


def _token(value) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ReminderReceiptError("receipt_invalid_identity")
    return value


@contextmanager
def _pin_leaf(path: Path, *, create: bool):
    # Same verified native leaf lease as migration_io.pinned_mutable_file,
    # but OPEN_EXISTING on restart must not silently recreate a missing ledger.
    api = _api()
    handle = api.CreateFileW(str(path), 0x80000000, 3, None,
                             4 if create else 3, 0x00200000, None)
    if handle is None or handle == ctypes.c_void_p(-1).value:
        raise ReminderReceiptError("receipt_leaf_unavailable")
    try:
        _verify(api, handle, path, directory=False)
        yield
    finally:
        api.CloseHandle(handle)


class ReminderReceiptStore:
    """Trusted host-only, single-thread context; no public/model-facing action.

    create=True is explicit first provisioning, never a recovery fallback.
    Reopen uses create=False and the same owner_id/maximum. A missing, foreign
    or corrupt database fails closed. Keep the context alive through send and
    receipt callbacks; close SQLite before releasing its native pin handles.
    """

    def __init__(self, directory: Path, *, owner_id: str, maximum: int = 4096,
                 create: bool = False, busy_timeout_ms: int = 1000):
        try:
            self.directory = validate_path(Path(directory))
        except (ValueError, OSError):
            raise ReminderReceiptError("receipt_invalid_directory") from None
        self.owner_id = _token(owner_id)
        if (type(maximum) is not int or not 1 <= maximum <= 4096
                or type(create) is not bool or type(busy_timeout_ms) is not int
                or not 1 <= busy_timeout_ms <= 5000):
            raise ReminderReceiptError("receipt_invalid_options")
        self.maximum, self.create, self.busy_timeout_ms = maximum, create, busy_timeout_ms
        self._connection = None
        self._stack = None
        self._used = False
        self._owned = {}
        self._pid, self._thread = os.getpid(), threading.get_ident()

    def __enter__(self):
        if (self._used or self._pid != os.getpid()
                or self._thread != threading.get_ident()):
            raise ReminderReceiptError("receipt_lifecycle_invalid")
        self._used = True
        stack = ExitStack()
        try:
            stack.enter_context(pinned_target_directory(self.directory, create=self.create))
            allowed = {"reminders.sqlite3", "reminders.sqlite3-journal"}
            if any(path.name not in allowed for path in self.directory.iterdir()):
                raise ReminderReceiptError("receipt_namespace_invalid")
            for name in sorted(allowed):
                stack.enter_context(_pin_leaf(self.directory / name, create=self.create))
            # A foreign WAL header could make SQLite open unpinned -wal/-shm
            # leaves before PRAGMA journal_mode runs. This owner accepts only
            # its bounded rollback-mode database, or explicit empty creation.
            for name in sorted(allowed):
                if (self.directory / name).stat().st_size > 16 * 1024 * 1024:
                    raise ReminderReceiptError("receipt_file_budget_exceeded")
            with (self.directory / "reminders.sqlite3").open("rb") as stream:
                header = stream.read(100)
            if (not header and not self.create) or (header and (
                    len(header) != 100 or header[:16] != b"SQLite format 3\0"
                    or header[18:20] != b"\x01\x01")):
                raise ReminderReceiptError("receipt_header_invalid")
            connection = apsw.Connection(str(self.directory / "reminders.sqlite3"),
                                         flags=apsw.SQLITE_OPEN_READWRITE)
            stack.callback(connection.close)
            connection.set_busy_timeout(self.busy_timeout_ms)
            if list(connection.execute("PRAGMA journal_mode=PERSIST")) != [("persist",)]:
                raise ReminderReceiptError("receipt_journal_unavailable")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("PRAGMA temp_store=MEMORY")
            connection.execute("PRAGMA trusted_schema=OFF")
            if list(connection.execute("PRAGMA synchronous")) != [(2,)]:
                raise ReminderReceiptError("receipt_sync_unavailable")
            self._connection, self._stack = connection, stack
            with self._transaction() as conn:
                schema = list(conn.execute("SELECT type,name,sql FROM sqlite_schema "
                                           "WHERE name NOT GLOB 'sqlite_*' ORDER BY name"))
                version = list(conn.execute("PRAGMA user_version"))[0][0]
                if not schema and version == 0 and self.create:
                    conn.execute(_META_SQL)
                    conn.execute(_ATTEMPT_SQL)
                    conn.execute("INSERT INTO receipt_meta VALUES (1,?,?)", (self.owner_id, self.maximum))
                    conn.execute("PRAGMA user_version=1")
                else:
                    expected = [("table", "receipt_meta", _META_SQL),
                                ("table", "reminder_receipts", _ATTEMPT_SQL)]
                    if schema != expected or version != 1:
                        raise ReminderReceiptError("receipt_schema_invalid")
                if list(conn.execute("SELECT * FROM receipt_meta")) != [(1, self.owner_id, self.maximum)]:
                    raise ReminderReceiptError("receipt_owner_or_capacity_mismatch")
                if list(conn.execute("PRAGMA quick_check")) != [("ok",)]:
                    raise ReminderReceiptError("receipt_integrity_failed")
            return self
        except Exception as error:
            self._connection = self._stack = None
            try:
                stack.close()
            except Exception:
                raise ReminderReceiptError("receipt_close_unavailable") from None
            if isinstance(error, ReminderReceiptError):
                raise
            raise ReminderReceiptError("receipt_open_unavailable") from None

    def __exit__(self, exc_type, exc, traceback):
        stack, self._stack = self._stack, None
        self._connection = None
        self._owned.clear()
        if stack is not None:
            try:
                stack.close()
            except Exception:
                if exc is None:
                    raise ReminderReceiptError("receipt_close_unavailable") from None

    def _active(self):
        if (self._connection is None or self._pid != os.getpid()
                or self._thread != threading.get_ident()):
            raise ReminderReceiptError("receipt_owner_context_required")
        return self._connection

    @contextmanager
    def _transaction(self):
        conn = self._active()
        committing = False
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            committing = True
            conn.execute("COMMIT")
        except Exception as error:
            try:
                if not conn.get_autocommit():
                    conn.execute("ROLLBACK")
            except apsw.Error:
                # A broken owner is unusable; retain every recorded attempt.
                self._connection = None
            if isinstance(error, ReminderReceiptError):
                raise
            if committing:
                raise ReminderReceiptError("receipt_commit_outcome_unknown") from None
            if isinstance(error, (apsw.BusyError, apsw.LockedError)):
                raise ReminderReceiptError("receipt_store_busy") from None
            raise ReminderReceiptError("receipt_store_unavailable") from None

    @staticmethod
    def _public(row):
        return {"eventId": row[0], "state": row[1], "channel": row[2],
                "pendingVerification": row[1] != "opened",
                "interactionObserved": row[1] == "opened"}

    def reserve(self, event_id: str) -> dict:
        """Only created=True after COMMIT permits one external submission.

        Existing records and all exceptions forbid automatic replay. Raw token
        is returned only to this winning owner and never appears in read APIs.
        """
        event_id = _token(event_id)
        raw = secrets.token_hex(32)
        digest = hashlib.sha256(raw.encode("ascii")).hexdigest()
        with self._transaction() as conn:
            rows = list(conn.execute("SELECT event_id,state,channel FROM reminder_receipts WHERE event_id=?", (event_id,)))
            if rows:
                result = {"created": False, **self._public(rows[0])}
            else:
                maximum = list(conn.execute("SELECT maximum FROM receipt_meta WHERE singleton=1"))[0][0]
                if list(conn.execute("SELECT count(*) FROM reminder_receipts"))[0][0] >= maximum:
                    raise ReminderReceiptError("receipt_capacity_exceeded")
                conn.execute("INSERT INTO reminder_receipts VALUES (?,?,'pending',NULL)", (event_id, digest))
                result = {"created": True, **self._public((event_id, "pending", None)), "attemptToken": raw}
        if result["created"]:
            self._owned[event_id] = digest
        return result

    def record_submitted(self, event_id: str, attempt_token: str, *, channel: str) -> dict:
        """Native send/show accepted the attempt; this is not a seen receipt."""
        return self._record(event_id, attempt_token, channel, "submitted")

    def record_opened(self, event_id: str, attempt_token: str, *, channel: str) -> dict:
        """Trusted owner supplies an actual interaction callback, not a timer."""
        return self._record(event_id, attempt_token, channel, "opened")

    @staticmethod
    def _attempt_digest(event_id, token, channel):
        event_id = _token(event_id)
        if (not isinstance(token, str) or not _HEX.fullmatch(token)
                or not isinstance(channel, str) or channel not in _CHANNELS):
            raise ReminderReceiptError("receipt_invalid_attempt")
        return event_id, hashlib.sha256(token.encode("ascii")).hexdigest()

    def record_recovered_opened(self, event_id: str, attempt_token: str, *, channel: str) -> dict:
        """Trusted native owner retained the original token AND click callback.

        This host-only entry must never be exposed as a model action or a
        renderer-supplied 'clicked' flag. The raw token is a private bearer
        capability returned only by the original winning reservation; reads
        cannot recover it. A replacement host can confirm that callback only
        against its persisted hash and already-bound, unchanged channel.
        Unbound pending attempts remain unknown. Confirmation grants neither
        submission ownership nor permission to resend the original reminder.
        """
        event_id, digest = self._attempt_digest(event_id, attempt_token, channel)
        with self._transaction() as conn:
            rows = list(conn.execute("SELECT token_hash,state,channel FROM reminder_receipts WHERE event_id=?", (event_id,)))
            if not rows or not secrets.compare_digest(rows[0][0], digest):
                raise ReminderReceiptError("receipt_attempt_owner_required")
            _, _, previous_channel = rows[0]
            if previous_channel is None:
                raise ReminderReceiptError("receipt_channel_unconfirmed")
            if previous_channel != channel:
                raise ReminderReceiptError("receipt_channel_conflict")
            conn.execute("UPDATE reminder_receipts SET state='opened' WHERE event_id=?", (event_id,))
        return self._public((event_id, "opened", previous_channel))

    def _record(self, event_id, token, channel, state):
        event_id, digest = self._attempt_digest(event_id, token, channel)
        if not secrets.compare_digest(self._owned.get(event_id, ""), digest):
            raise ReminderReceiptError("receipt_attempt_owner_required")
        with self._transaction() as conn:
            rows = list(conn.execute("SELECT token_hash,state,channel FROM reminder_receipts WHERE event_id=?", (event_id,)))
            if not rows or not secrets.compare_digest(rows[0][0], digest):
                raise ReminderReceiptError("receipt_attempt_owner_required")
            _, current, previous_channel = rows[0]
            if previous_channel is not None and previous_channel != channel:
                raise ReminderReceiptError("receipt_channel_conflict")
            final = "opened" if current == "opened" else state
            conn.execute("UPDATE reminder_receipts SET state=?,channel=? WHERE event_id=?", (final, channel, event_id))
        return self._public((event_id, final, channel))

    def get(self, event_id: str) -> dict | None:
        event_id = _token(event_id)
        try:
            rows = list(self._active().execute("SELECT event_id,state,channel FROM reminder_receipts WHERE event_id=?", (event_id,)))
        except apsw.Error:
            raise ReminderReceiptError("receipt_store_unavailable") from None
        return self._public(rows[0]) if rows else None

    def pending(self, *, limit: int = 100) -> list[dict]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ReminderReceiptError("receipt_invalid_limit")
        try:
            rows = list(self._active().execute("SELECT event_id,state,channel FROM reminder_receipts "
                                               "WHERE state!='opened' ORDER BY event_id LIMIT ?", (limit,)))
        except apsw.Error:
            raise ReminderReceiptError("receipt_store_unavailable") from None
        return [self._public(row) for row in rows]
