"""Runtime-injected budget window resolver for the session budget preflight.

The session turn worker must not reach into the production runtime singleton
to resolve the Workflow Ledger budget authority: an embedded runtime (tests,
tooling) never registers the singleton, so every formal invocation would fail
closed with ``challenge_budget_authority_unavailable`` even though a perfectly
valid Ledger store owns the receipt. Dependency direction: the runtime that
assembles the adapter execution path injects a resolver bound to its own
store; the session worker consumes the injection and keeps the production
singleton only as a backward-compatible fallback. Fail-closed semantics are
unchanged: with no injection and no production runtime, a challenge-scope
invocation still hard-fails.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

BudgetWindowResolver = Callable[[str, str, str], dict[str, Any]]

_RESOLVER_LOCK = threading.Lock()
_RESOLVER: BudgetWindowResolver | None = None
_RESOLVER_STORE: object | None = None


def configure_budget_window_resolver(
    resolver: BudgetWindowResolver,
    *,
    store: object | None = None,
) -> None:
    """Register the runtime-owned budget window resolver (idempotent replace).

    Called at runtime assembly (``build_workflow_runtime``), so production
    startup and embedded runtimes both inject their own store. The most
    recently assembled runtime wins, mirroring the ``_PRODUCTION`` singleton
    semantics this injection replaces. ``store`` is the identity the owner
    passes to :func:`release_budget_window_resolver_for_store` on close.
    """

    global _RESOLVER, _RESOLVER_STORE
    with _RESOLVER_LOCK:
        _RESOLVER = resolver
        _RESOLVER_STORE = store


def release_budget_window_resolver_for_store(store: object) -> None:
    """Clear the injection only when it is still bound to this store."""

    global _RESOLVER, _RESOLVER_STORE
    with _RESOLVER_LOCK:
        if _RESOLVER_STORE is store:
            _RESOLVER = None
            _RESOLVER_STORE = None


def injected_budget_window_resolver() -> BudgetWindowResolver | None:
    """The runtime-injected resolver, or ``None`` when nothing was injected."""

    with _RESOLVER_LOCK:
        return _RESOLVER


def injected_research_runtime_store() -> Any | None:
    """The Ledger store owned by the injected runtime, or ``None``.

    The formal receipt persistence path shares the same wrong dependency the
    budget window had: it needs the runtime's Ledger store and must not depend
    on the production singleton registration to find it.
    """

    with _RESOLVER_LOCK:
        return _RESOLVER_STORE
