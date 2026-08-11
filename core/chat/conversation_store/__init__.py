"""SQLite control-plane infrastructure for Agent, config, and session metadata.

Conversation messages, turn items, tool output, and terminal truth remain in
the append-only turn journal.  This package intentionally does not provide a
second transcript API.
"""

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
from .repository import (
    AgentConfigRevisionConflictError,
    ConversationRepository,
    ConversationUnitOfWork,
)
from .store import ConversationStore
from .writer import (
    ConversationBackpressureError,
    ConversationWriter,
    ConversationWriterClosedError,
)

__all__ = [
    "AgentConfigImportError",
    "AgentConfigRevisionConflictError",
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
