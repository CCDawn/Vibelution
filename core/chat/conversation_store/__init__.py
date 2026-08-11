"""Canonical SQLite conversation-store infrastructure (not yet live-wired)."""

from .database import (
    ConversationStoreError,
    ConversationStoreLockedError,
    ConversationStoreMigrationError,
    ConversationStoreSchemaError,
    ConversationStoreUnavailableError,
    SqliteWalRuntimeAssessment,
    assess_sqlite_wal_runtime,
)
from .importer import AgentConfigImportError, LegacyAgentConfigImporter
from .repository import ConversationRepository, ConversationUnitOfWork
from .store import ConversationStore
from .writer import (
    ConversationBackpressureError,
    ConversationWriter,
    ConversationWriterClosedError,
)

__all__ = [
    "AgentConfigImportError",
    "ConversationBackpressureError",
    "ConversationRepository",
    "ConversationStore",
    "ConversationStoreError",
    "ConversationStoreLockedError",
    "ConversationStoreMigrationError",
    "ConversationStoreSchemaError",
    "ConversationStoreUnavailableError",
    "ConversationUnitOfWork",
    "ConversationWriter",
    "ConversationWriterClosedError",
    "LegacyAgentConfigImporter",
    "SqliteWalRuntimeAssessment",
    "assess_sqlite_wal_runtime",
]
