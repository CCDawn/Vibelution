"""Turn-local tracking for tool futures that may outlive a cancelled call."""

from __future__ import annotations

import time
from concurrent.futures import Future
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from threading import Condition
from typing import Any, Iterator


_CURRENT_TOOL_EXECUTION_SCOPE: ContextVar["ToolExecutionScope | None"] = ContextVar(
    "current_tool_execution_scope",
    default=None,
)


@dataclass
class ToolExecutionScope:
    """Track physical tool execution until every registered future settles."""

    session_id: str
    turn_id: str
    created_at_monotonic: float = field(default_factory=time.monotonic)
    _condition: Condition = field(default_factory=Condition, init=False, repr=False)
    _pending: dict[Future[Any], str] = field(default_factory=dict, init=False, repr=False)
    _sealed: bool = field(default=False, init=False, repr=False)

    def register(self, future: Future[Any], *, tool_name: str = "") -> None:
        """Register a future before cancellation or timeout can return."""

        with self._condition:
            if self._sealed:
                raise RuntimeError("tool execution scope is sealed")
            self._pending[future] = str(tool_name or "").strip()
        future.add_done_callback(self._future_completed)

    def _future_completed(self, future: Future[Any]) -> None:
        with self._condition:
            self._pending.pop(future, None)
            self._condition.notify_all()

    def seal(self) -> None:
        """Prevent new registrations once the owning turn stops scheduling tools."""

        with self._condition:
            self._sealed = True
            self._condition.notify_all()

    @property
    def pending_count(self) -> int:
        with self._condition:
            return len(self._pending)

    @property
    def sealed(self) -> bool:
        with self._condition:
            return self._sealed

    def is_quiescent(self) -> bool:
        with self._condition:
            return self._sealed and not self._pending

    def wait_for_quiescence(self, timeout: float | None = None) -> bool:
        """Wait until sealed and physically idle; return False on timeout."""

        deadline = None if timeout is None else time.monotonic() + max(0.0, float(timeout))
        with self._condition:
            while not (self._sealed and not self._pending):
                if deadline is None:
                    self._condition.wait()
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(timeout=remaining)
            return True

    def snapshot(self) -> dict[str, Any]:
        """Return bounded identity/count facts without tool arguments or results."""

        with self._condition:
            return {
                "sessionId": self.session_id,
                "turnId": self.turn_id,
                "sealed": self._sealed,
                "pendingCount": len(self._pending),
                "pendingTools": [
                    name
                    for name in list(dict.fromkeys(self._pending.values()))[:8]
                    if name
                ],
                "ageMs": max(0, int((time.monotonic() - self.created_at_monotonic) * 1000)),
            }


def current_tool_execution_scope() -> ToolExecutionScope | None:
    return _CURRENT_TOOL_EXECUTION_SCOPE.get()


@contextmanager
def tool_execution_scope(scope: ToolExecutionScope) -> Iterator[ToolExecutionScope]:
    token: Token[ToolExecutionScope | None] = _CURRENT_TOOL_EXECUTION_SCOPE.set(scope)
    try:
        yield scope
    finally:
        _CURRENT_TOOL_EXECUTION_SCOPE.reset(token)


def register_current_tool_future(future: Future[Any], *, tool_name: str = "") -> bool:
    """Register with the current turn scope, if the caller installed one."""

    scope = current_tool_execution_scope()
    if scope is None:
        return False
    scope.register(future, tool_name=tool_name)
    return True
