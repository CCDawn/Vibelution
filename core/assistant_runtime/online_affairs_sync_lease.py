"""Private, generation-bound lease for already-imported affairs synchronization.

This module exposes no endpoint or model action. A host integrating it must
provide a nonblocking guard that authenticates the generation and native Turn,
holds the same authority against registry revocation and stop until exit, and
is acquired before the native lock. The guard must not wait for a worker that
is waiting for the native lock. First import and other migration capabilities
retain their independent offline-only checks.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Lock, get_ident
from typing import Callable

from .migration_io import MigrationIOError
from .migration_profile import OfflineMigrationProfileLease


@dataclass(frozen=True)
class OnlineAffairsSyncLease:
    """An unforgeable-in-context lease, valid only on its admitting thread."""

    root: Path
    agent_id: str
    session_id: str
    generation: str
    turn_id: str
    baseline_migration_id: str
    _scope: tuple[tuple[str, str], ...]
    _owner: "OnlineAffairsSyncOwner"
    _thread_id: int

    @property
    def source_scope(self) -> dict[str, str]:
        return dict(self._scope)

    def check(self) -> None:
        from . import native
        from core.infrastructure.native_runtime import assistant_native_root
        from core.web.services.session import directory_runtime

        if (self._owner._active is not self or self._thread_id != get_ident()
                or self._owner._revoked.is_set()
                or self.generation != self._owner.generation
                or native._STOP_REQUESTED.is_set() or not native._STARTED
                or native._OFFLINE_MIGRATION or native._AGENT_ID != self.agent_id
                or native._SESSION_ID != self.session_id or assistant_native_root() != self.root
                or directory_runtime.directory_store_project_root() != self.root):
            raise RuntimeError("online_affairs_sync_lease_unavailable")


def check_affairs_sync_lease(lease: object, *, source_scope=None, baseline_migration_id=None) -> None:
    """Checker for prepare/reconcile only; never used by first import/reminders."""
    if not isinstance(lease, (OfflineMigrationProfileLease, OnlineAffairsSyncLease)):
        raise MigrationIOError("affairs_profile_lease_required")
    if isinstance(lease, OnlineAffairsSyncLease) and (
            source_scope != lease.source_scope or baseline_migration_id != lease.baseline_migration_id):
        raise MigrationIOError("affairs_profile_lease_required")
    try:
        lease.check()
    except RuntimeError:
        raise MigrationIOError("affairs_profile_lease_required") from None


class OnlineAffairsSyncOwner:
    """An instance is owned by exactly one trusted live host generation.

    ``try_guard(generation, turn_id)`` must return a *nonblocking* context
    manager held across the operation. It must reject stale registrations,
    revoked approvals and inactive/mismatched native Turns. Host stop and
    registry changes must serialize on the same guard. A caller must never
    acquire this guard while holding ``native._LOCK``.
    """

    def __init__(self, generation: str, try_guard: Callable):
        from .migration_affairs import _token

        if not _token(generation) or not callable(try_guard):
            raise ValueError("online_affairs_sync_owner_invalid")
        self.generation = generation
        self._try_guard = try_guard
        self._gate = Lock()
        self._revoked = Event()
        self._active: OnlineAffairsSyncLease | None = None

    def revoke(self) -> bool:
        """Fence new/checkpointed work without waiting under native locks.

        False means an admitted operation is still draining. A host must not
        acknowledge stop/revocation as complete until ``drained()`` is true.
        """
        self._revoked.set()
        return self.drained()

    def drained(self) -> bool:
        if not self._gate.acquire(blocking=False):
            return False
        self._gate.release()
        return True

    @contextmanager
    def admit(self, *, generation: str, turn_id: str, baseline_migration_id: str,
              source_scope: dict[str, str]):
        """Try one online synchronization; no first import or path admission."""
        from . import native
        from .migration_affairs import _token
        from .migration_affairs_conflicts import _scope, locked_affairs_target, verified_affairs_baseline_locked
        from core.infrastructure.native_runtime import assistant_native_root
        from core.web.services.session import directory_runtime

        scope = _scope(source_scope)
        if (generation != self.generation or not _token(turn_id)
                or not _token(baseline_migration_id) or self._revoked.is_set()):
            raise MigrationIOError("online_affairs_sync_unavailable")
        # Required global order: host generation/Turn guard -> owner gate ->
        # native._LOCK -> migration and ledger locks inside prepare/reconcile.
        with self._try_guard(generation, turn_id):
            if not self._gate.acquire(blocking=False):
                raise MigrationIOError("online_affairs_sync_busy")
            acquired = False
            try:
                if self._revoked.is_set() or not native._LOCK.acquire(blocking=False):
                    raise MigrationIOError("online_affairs_sync_busy")
                acquired = True
                root = assistant_native_root()
                if (self._revoked.is_set() or native._STOP_REQUESTED.is_set()
                        or not native._STARTED or native._OFFLINE_MIGRATION
                        or not native._AGENT_ID or not native._SESSION_ID
                        or directory_runtime.directory_store_project_root() != root):
                    raise MigrationIOError("online_affairs_sync_unavailable")
                # This follows the complete authenticated chain to a published
                # first-import receipt; directory existence alone is not proof.
                with locked_affairs_target(root, target_agent_id=native._AGENT_ID) as target:
                    verified_affairs_baseline_locked(root, baseline_migration_id, scope, native._AGENT_ID, target=target)
                lease = OnlineAffairsSyncLease(root, native._AGENT_ID, native._SESSION_ID,
                    generation, turn_id, baseline_migration_id, tuple(sorted(scope.items())), self, get_ident())
                self._active = lease
                check_affairs_sync_lease(lease, source_scope=scope, baseline_migration_id=baseline_migration_id)
                yield lease
            finally:
                self._active = None
                if acquired:
                    native._LOCK.release()
                self._gate.release()
