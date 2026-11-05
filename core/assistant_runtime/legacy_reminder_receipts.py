"""Private, durable attempt ownership for negotiated legacy reminder sources.

This component neither authenticates a source nor enables reminder takeover.
Its caller must be the trusted Electron-main adapter, which binds sourceKey to
an authorized physical source, instance and PA agent. Tokens never go to a
renderer. The owner and every call must stay on one dedicated thread.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path

from .migration_io import pinned_target_directory
from .reminder_receipts import ReminderReceiptError, ReminderReceiptStore

_SOURCE = re.compile(r"[a-f0-9]{64}\Z")
_EVENT = re.compile(r"affair-reminder:[A-Za-z0-9._:-]{1,103}:([0-9]{8})\Z")
_TOKEN = re.compile(r"[a-f0-9]{64}\Z")
_CHANNELS = {"assistant_window", "system_notification", "attention_fallback"}
_OWNER = "legacy-reminders-v1"
_CAPACITY = 4096
_MAX_OPEN_DAYS = 32
_MAX_INVENTORY_DAYS = 4096
_MAX_INVENTORY_RECORDS = 20000
_EVENT_KEY = re.compile(r"legacy:[a-f0-9]{64}\Z")


def _request(value, fields):
    if not isinstance(value, dict) or set(value) != fields:
        raise ReminderReceiptError("legacy_reminder_request_invalid")
    source, event = value["sourceKey"], value["eventId"]
    if (not isinstance(source, str) or not _SOURCE.fullmatch(source)
            or not isinstance(event, str) or len(event) > 128):
        raise ReminderReceiptError("legacy_reminder_request_invalid")
    match = _EVENT.fullmatch(event)
    if not match:
        raise ReminderReceiptError("legacy_reminder_request_invalid")
    day = match.group(1)
    try:
        datetime.strptime(day, "%Y%m%d")
    except ValueError:
        raise ReminderReceiptError("legacy_reminder_request_invalid") from None
    packed = json.dumps([source, event], ensure_ascii=True, separators=(",", ":"))
    event_key = "legacy:" + hashlib.sha256(packed.encode("ascii")).hexdigest()
    return day, event_key


class LegacyReminderReceipts:
    """A private per-host-lifetime owner; close only after main drains sends."""

    def __init__(self, directory: Path, *, clock=None):
        self.directory = Path(directory)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.stores = {}
        self.outstanding = {}
        self.closed = False
        self._pid = os.getpid()
        self._thread = threading.get_ident()
        self.recovered_superseded_attempts = self._recover_superseded_attempts()

    def _check_owner(self):
        if self.closed or self._pid != os.getpid() or self._thread != threading.get_ident():
            raise ReminderReceiptError("legacy_reminder_owner_closed")

    def _recover_superseded_attempts(self) -> int:
        """One-time startup recovery for pending attempts that cannot be live.

        The attempt token hash is durable in each pending row, so the trusted
        desktop can settle or abandon a same-day attempt after this host
        restarts. An attempt in a day directory OLDER than today, however,
        cannot belong to any in-flight notification: reservations and their
        settlements happen inside the event's own UTC day, and historical
        days are fenced from settlement by design. This owner therefore
        treats older-day pending attempts as abandoned exactly once, at
        startup: their stored token hash is replaced so a retained token can
        never confirm them late, while the row itself stays pending -
        unknown, never marked delivered, and never authorized for a resend.

        Re-reserving (re-delivery) is deliberately rejected: a pending row's
        delivery outcome is unknown, and re-sending a possibly delivered
        reminder is the one outcome this ledger must never produce. Corrupt
        or unreadable days are skipped - recovery must never make startup
        fail where it previously succeeded, and those days keep failing
        closed for reads as before.
        """
        now = self.clock()
        if (not isinstance(now, datetime) or now.tzinfo is None
                or not self.directory.is_dir()):
            return 0
        today = now.astimezone(timezone.utc).strftime("%Y%m%d")
        retired = 0
        for day in sorted(p.name for p in self.directory.iterdir()):
            if not re.fullmatch(r"[0-9]{8}", day) or day >= today:
                continue
            try:
                store = ReminderReceiptStore(self.directory / day, owner_id=_OWNER,
                                             maximum=_CAPACITY, create=False)
                store.__enter__()
            except ReminderReceiptError:
                continue
            try:
                retired += store.retire_pending_attempts()
            finally:
                try:
                    store.__exit__(None, None, None)
                except ReminderReceiptError:
                    # A day whose close fails stays exactly as readable or
                    # unreadable as it was before this recovery.
                    pass
        return retired

    def _retire_old(self, day: str):
        for previous in list(self.stores):
            if previous != day and not self.outstanding.get(previous):
                self.outstanding.pop(previous, None)
                self.stores.pop(previous).__exit__(None, None, None)

    def _store(self, day: str, *, create: bool):
        self._check_owner()
        if day in self.stores:
            return self.stores[day]
        if len(self.stores) >= _MAX_OPEN_DAYS:
            # An RPC can commit a reservation yet never return its token.
            # At capacity, retire the oldest live owner without touching its
            # durable pending/inflight rows. Late settlement then fails closed.
            previous = next(iter(self.stores))
            self.outstanding.pop(previous, None)
            self.stores.pop(previous).__exit__(None, None, None)
        with pinned_target_directory(self.directory, create=create):
            path = self.directory / day
            fresh = False
            if create:
                try:
                    path.mkdir()
                    fresh = True
                except FileExistsError:
                    pass
            store = ReminderReceiptStore(path, owner_id=_OWNER, maximum=_CAPACITY, create=fresh)
            store.__enter__()
        self.stores[day] = store
        return store

    def reserve(self, request: dict) -> dict:
        self._check_owner()
        day, event_key = _request(request, {"sourceKey", "eventId"})
        now = self.clock()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise ReminderReceiptError("legacy_reminder_clock_invalid")
        if day != now.astimezone(timezone.utc).strftime("%Y%m%d"):
            raise ReminderReceiptError("legacy_reminder_day_invalid")
        self._retire_old(day)
        reservation = self._store(day, create=True).reserve(event_key)
        result = {"schemaVersion": 1, "eventKey": event_key,
                  "state": "reserved" if reservation["created"] else reservation["state"]}
        if reservation["created"]:
            result["attemptToken"] = reservation["attemptToken"]
            self.outstanding.setdefault(day, {})[event_key] = hashlib.sha256(
                reservation["attemptToken"].encode("ascii")).hexdigest()
        elif reservation.get("channel") is not None:
            result["channel"] = reservation["channel"]
        return result

    def settle(self, request: dict) -> dict:
        self._check_owner()
        day, event_key = _request(request, {"sourceKey", "eventId", "attemptToken", "channel"})
        token, channel = request["attemptToken"], request["channel"]
        if (not isinstance(token, str) or not _TOKEN.fullmatch(token)
                or not isinstance(channel, str) or channel not in _CHANNELS):
            raise ReminderReceiptError("legacy_reminder_request_invalid")
        # Submission ownership stays bound to the live store which made the
        # reservation: only that context attests that the one authorized send
        # actually returned. A replacement host must not confirm a submission
        # it did not supervise, so an attempt whose owner context died stays
        # pending and unknown (the desktop then abandons it, which works
        # across restarts below, and reconciliation acknowledges the row as
        # unknown - never as delivered, never replayed). Reopening another
        # day's ledger is equally refused, and exhausting the day limit must
        # not be reachable through settlement.
        store = self.stores.get(day)
        if store is None:
            raise ReminderReceiptError("receipt_attempt_owner_required")
        receipt = store.record_submitted(event_key, token, channel=channel)
        self.outstanding.get(day, {}).pop(event_key, None)
        return {"schemaVersion": 1, "eventKey": event_key,
                "state": receipt["state"], "channel": receipt["channel"]}

    def abandon(self, request: dict) -> dict:
        """Destroy this attempt's settlement capability, durably.

        The caller must stop the dispatch before invoking this. The token is
        verified against the hash persisted with the pending row, so the
        desktop can abandon an attempt whose reservation was made by a
        previous host lifetime - the window that used to leave such attempts
        permanently unconfirmable and un-abandonable. The pending row itself
        stays uncertain (state and channel untouched): neither a later
        settlement nor a resend is authorized, and the stored hash is rotated
        so that verdict survives any number of restarts.
        """
        self._check_owner()
        day, event_key = _request(request, {"sourceKey", "eventId", "attemptToken"})
        token = request["attemptToken"]
        if not isinstance(token, str) or not _TOKEN.fullmatch(token):
            raise ReminderReceiptError("legacy_reminder_request_invalid")
        store = self.stores.get(day)
        if store is None:
            # Only the current day's own ledger is reopened, and only for the
            # deliberate capability destruction above; historical days stay
            # fenced from every token-bearing call.
            if day != self.clock().astimezone(timezone.utc).strftime("%Y%m%d"):
                raise ReminderReceiptError("receipt_attempt_owner_required")
            store = self._store(day, create=False)
        store.abandon_attempt(event_key, token)
        self.outstanding.get(day, {}).pop(event_key, None)
        return {"schemaVersion": 1, "eventKey": event_key, "state": "abandoned"}

    def inventory(self) -> dict:
        """Read all historical evidence, never claiming delivery or quiescence.

        The private caller must keep a global admission barrier for *all*
        writers throughout this call and the matching Electron inventory.
        This method does not acquire that barrier or certify other processes.
        Missing or malformed namespaces fail closed; an absent receipt root is
        empty only while its existing parent is pinned by this call.
        """
        self._check_owner()
        records = []
        with pinned_target_directory(self.directory.parent):
            if not self.directory.exists() and not self.directory.is_symlink():
                return {"schemaVersion": 1, "records": [], "senders": 0}
            with pinned_target_directory(self.directory):
                days = sorted(p.name for p in self.directory.iterdir())
                if len(days) > _MAX_INVENTORY_DAYS:
                    raise ReminderReceiptError("legacy_reminder_inventory_limit")
                for day in days:
                    if not re.fullmatch(r"[0-9]{8}", day):
                        raise ReminderReceiptError("legacy_reminder_inventory_invalid")
                    try:
                        datetime.strptime(day, "%Y%m%d")
                    except ValueError:
                        raise ReminderReceiptError("legacy_reminder_inventory_invalid") from None
                senders = 0
                for day in days:
                    store = self.stores.get(day)
                    owned = store is not None
                    if not owned:
                        store = ReminderReceiptStore(self.directory / day, owner_id=_OWNER,
                                                     maximum=_CAPACITY, create=False)
                        store.__enter__()
                    try:
                        with store._transaction() as conn:
                            rows = list(conn.execute("SELECT event_id,state,channel FROM reminder_receipts ORDER BY event_id"))
                            inflight = list(conn.execute("SELECT event_id,sender_id,epoch FROM receipt_inflight"))
                            owners = list(conn.execute("SELECT sender_id,epoch FROM receipt_senders"))
                            if (len(rows) > _CAPACITY or len(inflight) > _CAPACITY or len(owners) > _CAPACITY
                                    or len(records) + len(rows) > _MAX_INVENTORY_RECORDS
                                    or senders + len(owners) > _MAX_INVENTORY_RECORDS):
                                raise ReminderReceiptError("legacy_reminder_inventory_limit")
                            owner_ids = set()
                            for sender, epoch in owners:
                                if not isinstance(sender, str) or not _TOKEN.fullmatch(sender) or epoch != 1 or sender in owner_ids:
                                    raise ReminderReceiptError("legacy_reminder_inventory_invalid")
                                owner_ids.add(sender)
                            inflight_ids = set()
                            for event_key, sender, epoch in inflight:
                                if (not isinstance(event_key, str) or not _EVENT_KEY.fullmatch(event_key)
                                        or event_key in inflight_ids or sender not in owner_ids or epoch != 1):
                                    raise ReminderReceiptError("legacy_reminder_inventory_invalid")
                                inflight_ids.add(event_key)
                            row_ids = set()
                            for event_key, state, channel in rows:
                                if (not isinstance(event_key, str) or not _EVENT_KEY.fullmatch(event_key)
                                        or event_key in row_ids or state not in {"pending", "submitted", "opened"}
                                        or (state == "pending" and channel is not None)
                                        or (state != "pending" and channel not in _CHANNELS)):
                                    raise ReminderReceiptError("legacy_reminder_inventory_invalid")
                                row_ids.add(event_key)
                                records.append({"day": day, "eventKey": event_key, "state": state,
                                                "channel": channel, "inflight": event_key in inflight_ids})
                            if not inflight_ids.issubset(row_ids):
                                raise ReminderReceiptError("legacy_reminder_inventory_invalid")
                            senders += len(owner_ids)
                    finally:
                        if not owned:
                            store.__exit__(None, None, None)
                if sorted(p.name for p in self.directory.iterdir()) != days:
                    raise ReminderReceiptError("legacy_reminder_inventory_changed")
        return {"schemaVersion": 1, "records": records, "senders": senders}

    def close(self):
        if self.closed:
            return
        self._check_owner()
        self.closed = True
        error = None
        for day in list(self.stores):
            try:
                self.stores.pop(day).__exit__(None, None, None)
            except Exception as caught:
                error = caught
        if error is not None:
            raise error
