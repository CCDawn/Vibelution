"""Exclusive offline ownership of one native Launcher profile for migration.

This is an operator-side capability, never a model action. It does not freeze
the source or establish cutover; its lock only protects the target profile.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import threading

from core.infrastructure.file_lock import locked_sidecar
from core.infrastructure.native_runtime import assistant_native_root

from .migration_io import check_path, pinned_mutable_file, pinned_target_directory, validate_path


_guard = threading.RLock()
_active = None
_quarantined = None


@dataclass(frozen=True)
class OfflineMigrationProfileLease:
    root: Path
    agent_id: str
    session_id: str
    _thread_id: int

    def check(self) -> None:
        from . import native
        if (self is not _active or self._thread_id != threading.get_ident()
                or assistant_native_root() != self.root or not native._STARTED or not native._OFFLINE_MIGRATION
                or native._AGENT_ID != self.agent_id or native._SESSION_ID != self.session_id):
            raise RuntimeError("offline_migration_lease_unavailable")


@contextmanager
def offline_migration_profile():
    """Acquire the same OS lock as the host *before* native bootstrap.

    ``locked_sidecar`` is deliberately not thread-reentrant, so even a host
    owning the same lock in this process cannot treat a migration as offline.
    Only this context can create a live lease, and it shuts down its own native
    lifecycle on exit. The caller must separately verify all source authority.
    """
    global _active, _quarantined
    root = assistant_native_root()
    lexical = validate_path(Path(os.environ.get("VIBELUTION_ASSISTANT_NATIVE_ROOT", "")))
    check_path(lexical)
    if lexical.resolve() != root:
        raise RuntimeError("offline_migration_profile_changed")
    from . import native
    with _guard:
        if _active is not None or _quarantined is not None or native._STARTED:
            raise RuntimeError("offline_migration_profile_busy")
        with ExitStack() as locks:
            locks.enter_context(pinned_target_directory(root))
            locks.enter_context(pinned_mutable_file(root / "host-owner.lock"))
            locks.enter_context(locked_sidecar(root / "host-owner", timeout=0))
            try:
                projection = native.bootstrap_for_offline_migration(root)
                assistant = projection.get("assistant") or {}
                agent_id, session_id = assistant.get("agentId"), assistant.get("directSessionId")
                if (not isinstance(agent_id, str) or not agent_id or not isinstance(session_id, str) or not session_id
                        or native._AGENT_ID != agent_id or native._SESSION_ID != session_id):
                    raise RuntimeError("offline_migration_identity_unavailable")
                lease = OfflineMigrationProfileLease(root, agent_id, session_id, threading.get_ident())
                _active = lease
                lease.check()
                yield lease
            finally:
                _active = None
                if native._STARTED:
                    try:
                        closed = native.shutdown().get("closed") is True
                    except Exception:
                        closed = False
                    if not closed:
                        # Keep the OS lock and pinned namespace alive until the
                        # owner really drains or this isolated process exits.
                        _quarantined = locks.pop_all()
                        raise RuntimeError("offline_migration_shutdown_unconfirmed") from None


def retry_offline_migration_shutdown() -> bool:
    """Release a quarantined profile only after native shutdown is confirmed."""
    global _quarantined
    from . import native
    with _guard:
        if _quarantined is None:
            return True
        try:
            if native.shutdown().get("closed") is not True:
                return False
        except Exception:
            return False
        locks, _quarantined = _quarantined, None
        locks.close()
        return True
