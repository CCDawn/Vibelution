"""Private Launcher reminder owner for profiles without affairs imports.

The caller owns a single dedicated thread for this object's entire lifetime.
Only a committed reservation is returned to Electron main; an uncertain result
is never retried. Daily ledgers retain deduplication records across restarts.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from .migration_io import pinned_target_directory
from .reminder_receipts import ReminderReceiptError, ReminderReceiptStore

_EVENT = re.compile(r"reminder:([0-9]{8}):[a-f0-9]{64}\Z")
_ITEM = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}\Z")
_DAILY_CAPACITY = 4096


class LauncherReminders:
    def __init__(self, root: Path, agent_id: str):
        self.root = Path(root)
        self.agent_id = agent_id
        self.owner = "assistant-" + hashlib.sha256(agent_id.encode()).hexdigest()
        self.stores = {}
        self.outstanding = {}

    def _no_import(self):
        # Import creates this directory before publishing any ledger change.
        # Host owns the same OS lock that offline migration requires.
        path = self.root / "affairs_migrations"
        if path.exists() or path.is_symlink():
            raise ReminderReceiptError("reminder_imported_profile_blocked")

    def _store(self, day: str, *, create: bool):
        if day in self.stores:
            return self.stores[day]
        base = self.root / "reminder_receipts"
        with pinned_target_directory(base, create=create):
            directory = base / day
            fresh = False
            if create:
                try:
                    directory.mkdir()
                    fresh = True
                except FileExistsError:
                    pass
            store = ReminderReceiptStore(directory, owner_id=self.owner, maximum=_DAILY_CAPACITY, create=fresh)
            store.__enter__()
        self.stores[day] = store
        return store

    def _retire_old(self, current_day):
        for day in list(self.stores):
            if day != current_day and not self.outstanding.get(day):
                self.stores.pop(day).__exit__(None, None, None)

    def next(self):
        self._no_import()
        from . import native
        from core.web.services import personal_affairs_service as affairs
        with native._session_command():
            if native._AGENT_ID != self.agent_id or affairs.PROJECT_ROOT != self.root:
                raise ReminderReceiptError("reminder_identity_changed")
            service = affairs.get_personal_affairs_service()
            expected = self.root / "agents" / self.agent_id / "plugins" / "personal-affairs"
            if service.store.plugin_root(self.agent_id) != expected:
                raise ReminderReceiptError("reminder_identity_changed")
            items = service.list_items(self.agent_id).get("items", [])
            day = datetime.now(timezone.utc).strftime("%Y%m%d")
            self._retire_old(day)
            for item in items:
                if item.get("status") != "open" or item.get("dueState") not in {"today", "overdue"}:
                    continue
                item_id = item.get("itemId")
                if not isinstance(item_id, str) or not _ITEM.fullmatch(item_id):
                    raise ReminderReceiptError("reminder_item_invalid")
                # Electron's limit is measured in UTF-16 code units; 50 Python
                # characters plus the prefix always fit even for astral text.
                title = " ".join(str(item.get("title") or "").split())[:50] or "事务"
                due = str(item.get("dueAt") or "").strip()
                # Validate text before spending the one allowed reservation.
                try:
                    (title + due).encode("utf-8")
                except UnicodeEncodeError:
                    raise ReminderReceiptError("reminder_item_invalid") from None
                event_id = "reminder:" + day + ":" + hashlib.sha256(item_id.encode()).hexdigest()
                store = self._store(day, create=True)
                reservation = store.reserve(event_id)
                if not reservation["created"]:
                    continue
                self.outstanding.setdefault(day, set()).add(event_id)
                return {"schemaVersion": 1, "event": {
                    "id": event_id, "kind": "affair_reminder",
                    "severity": "high" if item.get("dueState") == "overdue" else "medium",
                    "title": "事务提醒：" + title,
                    "body": ("截止 " + due if due else "已到期")[:80],
                    # The main process owns navigation to the Launcher assistant;
                    # the Workbench affairs route identifies a different profile.
                    "targetUrl": "",
                    "attemptToken": reservation["attemptToken"],
                }}
        return {"schemaVersion": 1, "event": None}

    def settle(self, event_id: str, token: str, channel: str, *, opened: bool):
        self._no_import()
        match = _EVENT.fullmatch(event_id) if isinstance(event_id, str) else None
        if not match:
            raise ReminderReceiptError("reminder_event_invalid")
        store = self._store(match.group(1), create=False)
        if not opened:
            result = store.record_submitted(event_id, token, channel=channel)
            self.outstanding.get(match.group(1), set()).discard(event_id)
            self._retire_old(datetime.now(timezone.utc).strftime("%Y%m%d"))
            return result
        try:
            result = store.record_opened(event_id, token, channel=channel)
        except ReminderReceiptError as error:
            if str(error) != "receipt_attempt_owner_required":
                raise
            result = store.record_recovered_opened(event_id, token, channel=channel)
        self._retire_old(datetime.now(timezone.utc).strftime("%Y%m%d"))
        return result

    def close(self):
        error = None
        for day in list(self.stores):
            try:
                self.stores.pop(day).__exit__(None, None, None)
            except Exception as caught:
                error = caught
        if error is not None:
            raise error
