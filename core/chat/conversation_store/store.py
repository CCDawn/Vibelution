"""Lifecycle facade for the isolated canonical conversation store."""

from __future__ import annotations

from pathlib import Path
from typing import Self

from .database import ConversationDatabase
from .repository import ConversationRepository
from .writer import ConversationWriter


class ConversationStore:
    def __init__(
        self,
        database_path: Path,
        *,
        queue_capacity: int = 2048,
        max_batch_size: int = 32,
        max_batch_delay_ms: int = 5,
        busy_timeout_ms: int = 250,
    ) -> None:
        self.database = ConversationDatabase(
            database_path,
            busy_timeout_ms=busy_timeout_ms,
        )
        self.writer = ConversationWriter(
            self.database,
            queue_capacity=queue_capacity,
            max_batch_size=max_batch_size,
            max_batch_delay_ms=max_batch_delay_ms,
        )
        self.repository = ConversationRepository(self.database, self.writer)
        self._open = False

    def open(self) -> dict[str, object]:
        if self._open:
            return self.database.metadata()
        metadata = self.database.initialize()
        self.writer.start()
        self._open = True
        return metadata

    def close(self, *, timeout: float = 5) -> None:
        if not self._open:
            return
        self.writer.close(timeout=timeout)
        self._open = False

    def __enter__(self) -> Self:
        self.open()
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()
