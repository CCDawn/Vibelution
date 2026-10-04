"""Retirement helpers for session-owned Agent runtimes.

The cache owns idle Agent runtimes. A worker lease owns an in-flight runtime
until that turn's ``finally`` block releases it. Invalidated entries remain
tracked here until their Agent and LLM transports close successfully.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any


_RETIRED_AGENT_ENTRIES: dict[int, dict[str, Any]] = {}


def _service():
    from core.web.services import session_service

    return session_service


def _close_entries(entries: list[dict[str, Any]], *, deadline: float | None = None) -> None:
    for index, entry in enumerate(entries):
        if deadline is not None and time.monotonic() >= float(deadline):
            with _service()._SESSION_AGENT_RUNTIME_CACHE_LOCK:
                for pending_entry in entries[index:]:
                    pending_entry["closeInProgress"] = False
            break
        _close_reserved_entry(entry)


class SessionAgentRuntimeLease:
    """Idempotent worker ownership for one cached or bypassed Agent."""

    def __init__(self, entry: dict[str, Any]) -> None:
        self._entry: dict[str, Any] | None = entry
        self._lock = threading.Lock()

    def release(self) -> None:
        with self._lock:
            entry = self._entry
            self._entry = None
        if entry is None:
            return
        _release_entry(entry)


def retain_runtime_agent_entry_locked(entry: dict[str, Any]) -> SessionAgentRuntimeLease:
    """Add a lease while the session runtime cache lock is held."""

    entry["activeLeases"] = max(0, int(entry.get("activeLeases") or 0)) + 1
    return SessionAgentRuntimeLease(entry)


def retire_runtime_agent_entries_locked(
    entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Mark entries retired while the facade cache lock is held."""

    due: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        entry["retired"] = True
        _RETIRED_AGENT_ENTRIES[id(entry)] = entry
        if int(entry.get("activeLeases") or 0) == 0 and not entry.get("closeInProgress"):
            entry["closeInProgress"] = True
            due.append(entry)
    return due


def close_retired_runtime_agent_entries(
    entries: list[dict[str, Any]],
    *,
    deadline: float | None = None,
) -> None:
    """Attempt reserved closes outside the cache lock; failed owners remain tracked."""

    _close_entries(entries, deadline=deadline)


def _close_reserved_entry(entry: dict[str, Any]) -> bool:
    agent = entry.get("agent")
    try:
        close = getattr(agent, "close", None)
        if callable(close):
            close()
    except Exception as exc:  # noqa: BLE001 - retain ownership for a later retry
        with _service()._SESSION_AGENT_RUNTIME_CACHE_LOCK:
            entry["closeInProgress"] = False
            entry["closeErrorType"] = type(exc).__name__
        logging.getLogger(__name__).warning(
            "Retired session Agent close failed (%s).", type(exc).__name__
        )
        return False

    with _service()._SESSION_AGENT_RUNTIME_CACHE_LOCK:
        entry["closeInProgress"] = False
        entry["closeErrorType"] = ""
        entry["closed"] = True
        _RETIRED_AGENT_ENTRIES.pop(id(entry), None)
    return True


def _release_entry(entry: dict[str, Any]) -> None:
    s = _service()
    due: list[dict[str, Any]] = []
    with s._SESSION_AGENT_RUNTIME_CACHE_LOCK:
        entry["activeLeases"] = max(0, int(entry.get("activeLeases") or 0) - 1)
        if (
            entry.get("retired")
            and entry["activeLeases"] == 0
            and not entry.get("closeInProgress")
        ):
            entry["closeInProgress"] = True
            due.append(entry)
    close_retired_runtime_agent_entries(due)


def retry_retired_session_agents(*, deadline: float | None = None) -> dict[str, int]:
    """Retry closable retired Agents and summarize resources still owned."""

    s = _service()
    due: list[dict[str, Any]] = []
    with s._SESSION_AGENT_RUNTIME_CACHE_LOCK:
        for entry in tuple(_RETIRED_AGENT_ENTRIES.values()):
            if int(entry.get("activeLeases") or 0) == 0 and not entry.get("closeInProgress"):
                entry["closeInProgress"] = True
                due.append(entry)
    _close_entries(due, deadline=deadline)
    with s._SESSION_AGENT_RUNTIME_CACHE_LOCK:
        pending = 0
        failed = 0
        for entry in _RETIRED_AGENT_ENTRIES.values():
            if int(entry.get("activeLeases") or 0) > 0 or entry.get("closeInProgress"):
                pending += 1
            elif entry.get("closeErrorType"):
                failed += 1
            else:
                pending += 1
    return {"pending": pending, "failed": failed}


def retire_session_agent_runtime_cache(
    *,
    close_cache: bool = False,
    session_id: str = "",
    deadline: float | None = None,
) -> dict[str, int]:
    """Remove matching cache entries and keep their owners until close succeeds."""

    s = _service()
    normalized_session_id = str(session_id or "").strip()
    with s._SESSION_AGENT_RUNTIME_CACHE_LOCK:
        if close_cache:
            s._SESSION_AGENT_RUNTIME_CACHE_CLOSED = True
        s._SESSION_AGENT_RUNTIME_CACHE_GENERATION += 1
        if normalized_session_id:
            prefix = f"{normalized_session_id}|"
            keys = [key for key in s._SESSION_AGENT_RUNTIME_CACHE if key.startswith(prefix)]
        else:
            keys = list(s._SESSION_AGENT_RUNTIME_CACHE)
        entries = [s._SESSION_AGENT_RUNTIME_CACHE.pop(key) for key in keys]
        due = retire_runtime_agent_entries_locked(entries)
    _close_entries(due, deadline=deadline)
    return {"removed": len(entries), **retired_session_agent_status()}


def retire_uncached_session_agent(agent: Any) -> None:
    """Retire a one-shot session Agent after its owning operation completes."""

    if agent is None:
        return
    s = _service()
    entry = {
        "agent": agent,
        "fingerprint": "",
        "lastAccess": 0.0,
        "activeLeases": 0,
        "retired": False,
        "closeInProgress": False,
        "closeErrorType": "",
    }
    with s._SESSION_AGENT_RUNTIME_CACHE_LOCK:
        due = retire_runtime_agent_entries_locked([entry])
    _close_entries(due)


def retired_session_agent_status() -> dict[str, int]:
    """Return a bounded count of pending and failed Agent retirements."""

    s = _service()
    with s._SESSION_AGENT_RUNTIME_CACHE_LOCK:
        pending = 0
        failed = 0
        for entry in _RETIRED_AGENT_ENTRIES.values():
            if int(entry.get("activeLeases") or 0) > 0 or entry.get("closeInProgress"):
                pending += 1
            elif entry.get("closeErrorType"):
                failed += 1
            else:
                pending += 1
    return {"pending": pending, "failed": failed}


__all__ = [
    "SessionAgentRuntimeLease",
    "close_retired_runtime_agent_entries",
    "retire_runtime_agent_entries_locked",
    "retain_runtime_agent_entry_locked",
    "retire_session_agent_runtime_cache",
    "retire_uncached_session_agent",
    "retry_retired_session_agents",
    "retired_session_agent_status",
]
