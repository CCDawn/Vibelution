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
from .importer import (
    AgentConfigImportError,
    ChatStateImportError,
    LegacyAgentConfigImporter,
    LegacyChatStateImporter,
)
from .repository import (
    AgentConfigRevisionConflictError,
    ChatStateRevisionConflictError,
    ConversationRepository,
    ConversationUnitOfWork,
    LAST_PREVIEW_MAX_CHARS,
    directory_cursor_for_row,
    parse_directory_cursor,
    parse_directory_cursor_entry,
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
    "ChatStateImportError",
    "ChatStateRevisionConflictError",
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
    "LAST_PREVIEW_MAX_CHARS",
    "LegacyAgentConfigImporter",
    "LegacyChatStateImporter",
    "SqliteWalRuntimeAssessment",
    "assess_sqlite_wal_runtime",
    "directory_cursor_for_row",
    "parse_directory_cursor",
    "parse_directory_cursor_entry",
]
