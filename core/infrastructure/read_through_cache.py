"""Read-through cache with TTL reuse and single-flight collapse.

Polling surfaces are re-requested on a short interval by the workbench shell
while one computation can take seconds.  Without a read-through layer every
poll pays the full cost again and concurrent callers queue behind each other;
during the 2026-11-16 startup storm that pattern starved unrelated routes
(session create waited behind repeated full-ledger aggregates).

Two properties are load-bearing:

* TTL reuse - a value computed within ``ttl_seconds`` is returned without
  recomputing, so a poll interval shorter than the compute cost stops being a
  queue multiplier.
* Single-flight - callers that arrive while one computation for the same key
  is running wait for that result instead of starting a second one.  A failed
  computation is never shared: waiters fall through and compute their own
  value, and the leader's exception only reaches the leader.

The cache owns storage, not mutation.  Callers that store mutable payloads
must copy on the way out (and on the way in if the producer hands out shared
objects) so a consumer cannot corrupt the cached value.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any


class ReadThroughCache:
    """Thread-safe TTL cache that collapses concurrent same-key computes."""

    def __init__(
        self,
        *,
        name: str,
        wait_timeout_seconds: float = 30.0,
        clock: Callable[[], float] | None = None,
        max_entries: int = 128,
    ) -> None:
        self.name = str(name or "cache")
        self._wait_timeout_seconds = float(wait_timeout_seconds)
        self._clock = clock or time.monotonic
        self._max_entries = max(1, int(max_entries))
        self._condition = threading.Condition()
        self._entries: dict[str, dict[str, Any]] = {}
        self._flights: dict[str, dict[str, Any]] = {}
        self._generation = 0
        self._hits = 0
        self._joins = 0
        self._misses = 0

    def get_or_compute(
        self,
        key: str,
        compute: Callable[[], Any],
        ttl_seconds: float,
        *,
        should_cache: Callable[[Any], bool] | None = None,
    ) -> Any:
        """Return the cached value, joining or leading one computation."""

        now = self._clock()
        leader_generation = 0
        leader = False
        with self._condition:
            entry = self._entries.get(key)
            if entry is not None and now - float(entry["at"]) <= float(ttl_seconds):
                self._hits += 1
                return entry["value"]
            flight = self._flights.get(key)
            if flight is None:
                self._generation += 1
                leader_generation = self._generation
                self._flights[key] = {
                    "inflight": True,
                    "generation": leader_generation,
                }
                leader = True
            else:
                leader = False
                wait_generation = int(flight["generation"])
                # The wait budget is wall-clock, never the injectable business
                # clock: a frozen clock would otherwise turn the deadline into
                # an endless loop instead of a bounded wait.
                deadline = time.monotonic() + self._wait_timeout_seconds
                while flight["inflight"]:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    self._condition.wait(remaining)
                if not flight["inflight"]:
                    shared = self._entries.get(key)
                    if shared is not None and shared["generation"] == wait_generation:
                        self._joins += 1
                        return shared["value"]
                # Leader failed or the wait timed out: compute our own value
                # instead of inheriting an unknown outcome.

        self._misses += 1
        try:
            value = compute()
        except BaseException:
            if leader:
                self._release_flight(key)
            raise
        if leader:
            self._store(key, value, leader_generation, should_cache)
        return value

    def _store(
        self,
        key: str,
        value: Any,
        generation: int,
        should_cache: Callable[[Any], bool] | None,
    ) -> None:
        try:
            cacheable = True if should_cache is None else bool(should_cache(value))
        except Exception:  # noqa: BLE001 - a broken predicate must not break the read
            cacheable = False
        with self._condition:
            if cacheable:
                self._entries[key] = {
                    "value": value,
                    "at": self._clock(),
                    "generation": generation,
                }
                self._trim_locked()
            ended = self._flights.pop(key, None)
            if ended is not None:
                ended["inflight"] = False
            self._condition.notify_all()

    def _release_flight(self, key: str) -> None:
        with self._condition:
            ended = self._flights.pop(key, None)
            if ended is not None:
                ended["inflight"] = False
            self._condition.notify_all()

    def _trim_locked(self) -> None:
        overflow = len(self._entries) - self._max_entries
        if overflow <= 0:
            return
        oldest = sorted(self._entries.items(), key=lambda item: float(item[1]["at"]))
        for stale_key, _ in oldest[:overflow]:
            self._entries.pop(stale_key, None)

    def clear(self) -> None:
        """Drop cached values and in-flight bookkeeping (test isolation)."""

        with self._condition:
            self._entries.clear()
            self._flights.clear()
            self._hits = 0
            self._joins = 0
            self._misses = 0

    def stats(self) -> dict[str, int]:
        with self._condition:
            return {
                "hits": self._hits,
                "joins": self._joins,
                "misses": self._misses,
                "entries": len(self._entries),
                "flights": len(self._flights),
            }
