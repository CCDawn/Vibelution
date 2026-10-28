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

    def _check_owner(self):
        if self.closed or self._pid != os.getpid() or self._thread != threading.get_ident():
            raise ReminderReceiptError("legacy_reminder_owner_closed")

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
        # Settlement belongs to the live store which made the reservation.
        # Reopening an old day creates a different owner and can never make
        # its token valid; retaining such stores also exhausts the day limit.
        store = self._owned_attempt(day, event_key, token)
        receipt = store.record_submitted(event_key, token, channel=channel)
        self.outstanding[day].pop(event_key)
        return {"schemaVersion": 1, "eventKey": event_key,
                "state": receipt["state"], "channel": receipt["channel"]}

    def _owned_attempt(self, day, event_key, token):
        digest = hashlib.sha256(token.encode("ascii")).hexdigest()
        store = self.stores.get(day)
        if store is None or not secrets.compare_digest(self.outstanding.get(day, {}).get(event_key, ""), digest):
            raise ReminderReceiptError("receipt_attempt_owner_required")
        return store

    def abandon(self, request: dict) -> dict:
        """Forget this attempt's live capability without changing its ledger.

        The caller must stop the dispatch before invoking this. A pending row
        stays uncertain; neither a later settlement nor a resend is authorized.
        """
        self._check_owner()
        day, event_key = _request(request, {"sourceKey", "eventId", "attemptToken"})
        token = request["attemptToken"]
        if not isinstance(token, str) or not _TOKEN.fullmatch(token):
            raise ReminderReceiptError("legacy_reminder_request_invalid")
        self._owned_attempt(day, event_key, token)
        self.outstanding[day].pop(event_key)
        return {"schemaVersion": 1, "eventKey": event_key, "state": "abandoned"}

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
