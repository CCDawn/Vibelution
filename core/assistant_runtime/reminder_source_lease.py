"""Private, bounded leases for existing legacy reminder source files.

This is deliberately *not* complete source authority: Windows directory share
locks do not prevent creating a previously absent routing marker. The caller
must separately fence route creation, registry changes, unmanaged senders and
host death before using a lease in a delivery decision. It grants no cutover.
The caller never supplies paths, agent IDs or a ledger digest.
"""
from __future__ import annotations

import os
import math
import re
import secrets
import threading
import time
from contextlib import ExitStack
from pathlib import Path

from .migration_io import MigrationIOError
from .reminder_source_identity import observe_reminder_source
from core.infrastructure.reminder_source_mutex import trusted_reminder_source_mutex_key
from core.infrastructure.reminder_route_gate import HeldRouteGate
from core.web.services.personal_assistant_project.windows_read import _locked_source

_TOKEN = re.compile(r"[a-f0-9]{64}\Z")
_MAX_LEASES = 16
_MAX_TTL_MS = 10000


class ReminderSourceLeaseOwner:
    """A host-lifetime private owner; acquisition never takes the source mutex.

    Electron holds its source mutex for the whole operation. A single host
    instance owns this object and calls revoke_all before routing/registry
    mutations and close before stopping. Outstanding file handles remain pinned
    until release, expiry, owner close, or OS process exit. This class does not
    guarantee that a future caller will check, nor protect an absent marker.
    """

    def __init__(self, dispatch, preview, *, clock=time.monotonic):
        if getattr(preview, "_dispatch", None) is not dispatch:
            raise MigrationIOError("reminder_lease_unavailable")
        self._dispatch, self._preview, self._clock = dispatch, preview, clock
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._leases = {}
        self._permits = {}
        self._pending_permit_ids = set()
        self._retired_permit_ids = set()
        self._releasing_permit_ids = set()
        self._failed_release_ids = set()
        self._pending = 0
        self._epoch = 0
        self._revoking = False
        self._closed = False
        self._pid = os.getpid()

    def _active(self):
        if self._closed or self._revoking or self._pid != os.getpid():
            raise MigrationIOError("reminder_lease_owner_closed")

    def acquire_permit(self, project_id: str, revision: int, permit_id: str | None = None) -> dict:
        """Hold route gate and file pins until explicit sender settlement.

        A revoke immediately rejects new checks/admissions but keeps existing
        pins until their holders explicitly release. No lease expiry claims a
        possibly in-flight notification has stopped. Caller must separately
        hold the same source mutex as all upgraded senders and affairs writers.
        """
        if permit_id is None:
            permit_id = secrets.token_hex(32)
        if type(permit_id) is not str or _TOKEN.fullmatch(permit_id) is None:
            raise MigrationIOError("reminder_lease_request_invalid")
        with self._condition:
            self._active()
            if permit_id in self._retired_permit_ids or permit_id in self._pending_permit_ids:
                raise MigrationIOError("reminder_lease_unavailable")
            existing = self._permits.get(permit_id)
            if existing is not None:
                observation, _, gate, key, bound_project, bound_revision = existing
                if bound_project != project_id or bound_revision != revision:
                    raise MigrationIOError("reminder_lease_unavailable")
                gate.check()
                if trusted_reminder_source_mutex_key(observation) != key:
                    raise MigrationIOError("reminder_lease_changed")
                return {"schemaVersion": 1, "permitId": permit_id, "ledgerKey": key,
                        "coverage": "cooperating_route_writers", "unmanagedSenders": "unknown", "readyForCutover": False}
            if len(self._leases) + len(self._permits) + self._pending >= _MAX_LEASES:
                raise MigrationIOError("reminder_lease_capacity")
            if len(self._retired_permit_ids) >= 4096:
                raise MigrationIOError("reminder_lease_capacity")
            if type(revision) is not int or self._dispatch._registry_revision != revision:
                raise MigrationIOError("reminder_lease_request_invalid")
            root = self._dispatch._admitted_projects().get(project_id)
            if root is None:
                raise MigrationIOError("reminder_lease_unavailable")
            self._pending += 1
            self._pending_permit_ids.add(permit_id)
            epoch = self._epoch
        gate = observation = None
        stack = ExitStack()
        published = False
        try:
            gate = HeldRouteGate(root)
            gate.check()
            observation = observe_reminder_source(self._dispatch, self._preview, project_id, revision)
            with self._preview._lock:
                observation._check()
                row = self._preview._previews[observation._token]
                if Path(row[3]) != Path(root):
                    raise MigrationIOError("reminder_lease_changed")
                ledger = Path(root) / "agents" / observation.agent_id / "plugins/personal-affairs/affairs/items.jsonl"
                paths = {snapshot.path for snapshot in row[7]}
                paths.add(ledger)
                for path in sorted(paths, key=lambda value: str(value).casefold()):
                    stack.enter_context(_locked_source(Path(path.anchor), path, directory=False,
                                                       allow_child_replacement=True))
                key = trusted_reminder_source_mutex_key(observation)
                gate.check()
                observation._check()
            with self._condition:
                self._active()
                if epoch != self._epoch or permit_id in self._retired_permit_ids:
                    raise MigrationIOError("reminder_lease_revoked")
                self._permits[permit_id] = (observation, stack, gate, key, project_id, revision)
                published = True
                return {"schemaVersion": 1, "permitId": permit_id, "ledgerKey": key,
                        "coverage": "cooperating_route_writers", "unmanagedSenders": "unknown", "readyForCutover": False}
        finally:
            try:
                if not published:
                    try:
                        stack.close()
                    finally:
                        try:
                            if observation is not None:
                                observation.close()
                        finally:
                            if gate is not None:
                                gate.release()
            finally:
                with self._condition:
                    self._pending -= 1
                    self._pending_permit_ids.discard(permit_id)
                    self._condition.notify_all()

    def check_permit(self, token: str) -> dict:
        if type(token) is not str or _TOKEN.fullmatch(token) is None:
            raise MigrationIOError("reminder_lease_request_invalid")
        with self._lock:
            self._active()
            row = self._permits.get(token)
            if row is None:
                raise MigrationIOError("reminder_lease_unavailable")
        observation, _, gate, key, _, _ = row
        try:
            gate.check()
            if trusted_reminder_source_mutex_key(observation) != key:
                raise MigrationIOError("reminder_lease_changed")
            gate.check()
        except Exception:
            # Retain pins until explicit release, even after failed check.
            raise MigrationIOError("reminder_lease_changed") from None
        with self._lock:
            self._active()
            if self._permits.get(token) is not row:
                raise MigrationIOError("reminder_lease_unavailable")
            return {"schemaVersion": 1, "ledgerKey": key, "coverage": "cooperating_route_writers",
                    "unmanagedSenders": "unknown", "readyForCutover": False}

    def release_permit(self, token: str) -> None:
        if type(token) is not str or _TOKEN.fullmatch(token) is None:
            raise MigrationIOError("reminder_lease_request_invalid")
        with self._condition:
            if token in self._retired_permit_ids:
                while token in self._pending_permit_ids or token in self._releasing_permit_ids:
                    self._condition.wait()
                if token in self._failed_release_ids:
                    raise MigrationIOError("reminder_lease_unavailable")
                return
            if len(self._retired_permit_ids) >= 4096:
                raise MigrationIOError("reminder_lease_capacity")
            self._retired_permit_ids.add(token)
            self._releasing_permit_ids.add(token)
            try:
                while token in self._pending_permit_ids:
                    self._condition.wait()
                row = self._permits.pop(token, None)
                if row is None:
                    return
                observation, stack, gate, _, _, _ = row
                try:
                    stack.close()
                finally:
                    try:
                        observation.close()
                    finally:
                        gate.release()
            except BaseException:
                self._failed_release_ids.add(token)
                raise
            finally:
                self._releasing_permit_ids.discard(token)
                self._condition.notify_all()

    def acquire(self, project_id: str, revision: int, ttl_ms: int) -> dict:
        if type(ttl_ms) is not int or not 100 <= ttl_ms <= _MAX_TTL_MS:
            raise MigrationIOError("reminder_lease_request_invalid")
        with self._lock:
            self._active()
            if len(self._leases) + len(self._permits) + self._pending >= _MAX_LEASES:
                raise MigrationIOError("reminder_lease_capacity")
            self._pending += 1
            epoch = self._epoch
        observation = None
        stack = ExitStack()
        published = False
        try:
            observation = observe_reminder_source(self._dispatch, self._preview, project_id, revision)
            # Pin only paths obtained from the verified private preview.
            with self._preview._lock:
                observation._check()
                row = self._preview._previews[observation._token]
                root, snapshots = Path(row[3]), row[7]
                ledger = root / "agents" / observation.agent_id / "plugins/personal-affairs/affairs/items.jsonl"
                paths = {snapshot.path for snapshot in snapshots}
                paths.add(ledger)
                for path in sorted(paths, key=lambda value: str(value).casefold()):
                    stack.enter_context(_locked_source(Path(path.anchor), path, directory=False,
                                                       allow_child_replacement=True))
                key = trusted_reminder_source_mutex_key(observation)
                observation._check()
            with self._lock:
                self._active()
                if epoch != self._epoch:
                    raise MigrationIOError("reminder_lease_revoked")
                token = secrets.token_hex(32)
                deadline = self._clock() + ttl_ms / 1000
                timer = threading.Timer(ttl_ms / 1000, self._expire, args=(token,))
                timer.daemon = True
                self._leases[token] = (observation, stack, deadline, timer, key)
                try:
                    timer.start()
                except BaseException:
                    self._leases.pop(token, None)
                    raise
                published = True
                return {"schemaVersion": 1, "leaseId": token, "ledgerKey": key,
                        "ttlMs": ttl_ms, "coverage": "existing_files_only", "readyForCutover": False}
        finally:
            try:
                if not published:
                    try:
                        stack.close()
                    finally:
                        if observation is not None:
                            observation.close()
            finally:
                with self._condition:
                    self._pending -= 1
                    self._condition.notify_all()

    def _discard(self, token):
        row = self._leases.pop(token, None)
        if row is not None:
            observation, stack, _, timer, _ = row
            timer.cancel()
            try:
                stack.close()
            finally:
                observation.close()

    def _expire(self, token):
        with self._lock:
            self._discard(token)

    def check(self, token: str) -> dict:
        if type(token) is not str or _TOKEN.fullmatch(token) is None:
            raise MigrationIOError("reminder_lease_request_invalid")
        with self._lock:
            self._active()
            row = self._leases.get(token)
            if row is None:
                raise MigrationIOError("reminder_lease_unavailable")
            observation, _, deadline, _, key = row
            if self._clock() >= deadline:
                self._discard(token)
                raise MigrationIOError("reminder_lease_expired")
        try:
            if trusted_reminder_source_mutex_key(observation) != key:
                raise MigrationIOError("reminder_lease_changed")
        except Exception:
            with self._lock:
                if self._leases.get(token) is row:
                    self._discard(token)
            raise
        with self._lock:
            self._active()
            if self._leases.get(token) is not row:
                raise MigrationIOError("reminder_lease_unavailable")
            if self._clock() >= deadline:
                self._discard(token)
                raise MigrationIOError("reminder_lease_expired")
            remaining_ms = math.floor((deadline - self._clock()) * 1000)
            if remaining_ms < 1:
                self._discard(token)
                raise MigrationIOError("reminder_lease_expired")
            return {"schemaVersion": 1, "ledgerKey": key, "coverage": "existing_files_only",
                    "remainingMs": remaining_ms, "readyForCutover": False}

    def release(self, token: str) -> None:
        if type(token) is not str or _TOKEN.fullmatch(token) is None:
            raise MigrationIOError("reminder_lease_request_invalid")
        with self._lock:
            self._active()
            if token not in self._leases:
                raise MigrationIOError("reminder_lease_unavailable")
            self._discard(token)

    def begin_revocation(self) -> None:
        with self._condition:
            self._active()
            self._epoch += 1
            self._revoking = True
            for token in list(self._leases):
                self._discard(token)

    def wait_revocation(self) -> None:
        with self._condition:
            if not self._revoking:
                raise MigrationIOError("reminder_lease_owner_closed")
            while self._pending or self._permits:
                self._condition.wait()

    def end_revocation(self) -> None:
        with self._condition:
            if not self._revoking or self._pending or self._permits:
                raise MigrationIOError("reminder_lease_unavailable")
            self._revoking = False
            self._condition.notify_all()

    def revoke_all(self) -> None:
        self.begin_revocation()
        try:
            self.wait_revocation()
        finally:
            self.end_revocation()

    def close(self) -> None:
        with self._condition:
            if self._pid != os.getpid():
                raise MigrationIOError("reminder_lease_owner_closed")
            while self._revoking:
                self._condition.wait()
            if self._closed:
                while self._pending or self._permits:
                    self._condition.wait()
                return
            self._closed = True
            self._epoch += 1
            for token in list(self._leases):
                self._discard(token)
            while self._pending or self._permits:
                self._condition.wait()
