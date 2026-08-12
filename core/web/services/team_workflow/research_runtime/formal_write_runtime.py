"""Process-local formal write runtime (Command + create_run).

Fails closed with workflow_ledger_unavailable. Never falls back to JSON.
"""

from __future__ import annotations

import threading

from core.research.workflow.ledger import WorkflowLedgerStore

from .command_service import WorkflowCommandService

_LOCK = threading.Lock()
_COMMAND: WorkflowCommandService | None = None
_STORE: WorkflowLedgerStore | None = None
_MIGRATION_REQUIRED = False


class FormalWriteRuntimeUnavailable(RuntimeError):
    code = "workflow_ledger_unavailable"

    def __init__(self, detail: str = "formal workflow write runtime is not configured") -> None:
        super().__init__(detail)
        self.code = "workflow_ledger_unavailable"


class WorkflowMigrationRequired(RuntimeError):
    code = "workflow_migration_required"

    def __init__(self, detail: str = "workflow ledger migration has not been activated") -> None:
        super().__init__(detail)
        self.code = "workflow_migration_required"


def configure_formal_write_runtime(
    *,
    store: WorkflowLedgerStore,
    command_service: WorkflowCommandService,
    migration_required: bool = False,
) -> None:
    global _COMMAND, _STORE, _MIGRATION_REQUIRED
    with _LOCK:
        _STORE = store
        _COMMAND = command_service
        _MIGRATION_REQUIRED = bool(migration_required)


def reset_formal_write_runtime_for_tests() -> None:
    global _COMMAND, _STORE, _MIGRATION_REQUIRED
    with _LOCK:
        _COMMAND = None
        _STORE = None
        _MIGRATION_REQUIRED = False


def mark_migration_required() -> None:
    global _MIGRATION_REQUIRED
    with _LOCK:
        _MIGRATION_REQUIRED = True


def is_migration_required() -> bool:
    with _LOCK:
        return bool(_MIGRATION_REQUIRED)


def get_command_service() -> WorkflowCommandService:
    with _LOCK:
        if _MIGRATION_REQUIRED:
            raise WorkflowMigrationRequired()
        if _COMMAND is None:
            raise FormalWriteRuntimeUnavailable()
        return _COMMAND


def get_write_store() -> WorkflowLedgerStore:
    with _LOCK:
        if _MIGRATION_REQUIRED:
            raise WorkflowMigrationRequired()
        if _STORE is None:
            raise FormalWriteRuntimeUnavailable()
        return _STORE
