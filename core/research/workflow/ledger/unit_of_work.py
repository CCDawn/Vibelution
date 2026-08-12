"""Transaction-scoped repository + after-commit registry (spec 7.1)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .repository import WorkflowLedgerRepository


class WorkflowLedgerUnitOfWork:
    """Binds one repository to the current transaction and collects
    after-commit callbacks (SSE notification must only run after commit)."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection
        self.repository = WorkflowLedgerRepository(connection)
        self._after_commit: list[Callable[[], None]] = []
        self._committed = False
        self._rolled_back = False

    def after_commit(self, callback: Callable[[], None]) -> None:
        self._after_commit.append(callback)

    def take_after_commit(self) -> list[Callable[[], None]]:
        callbacks = self._after_commit
        self._after_commit = []
        return callbacks

    def mark_committed(self) -> None:
        self._committed = True

    def mark_rolled_back(self) -> None:
        self._rolled_back = True

    @property
    def has_after_commit(self) -> bool:
        return bool(self._after_commit)

    @property
    def committed(self) -> bool:
        return self._committed

    @property
    def rolled_back(self) -> bool:
        return self._rolled_back
