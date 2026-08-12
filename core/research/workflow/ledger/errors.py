"""Workflow Ledger error hierarchy (fail closed, no fallback)."""

from __future__ import annotations


class WorkflowLedgerError(RuntimeError):
    """Base class for all Workflow Ledger failures."""


class WorkflowLedgerUnavailableError(WorkflowLedgerError):
    """The configured runtime cannot safely host the ledger database."""


class WorkflowLedgerSchemaError(WorkflowLedgerError):
    """Schema unsupported, drifted or checksum mismatch."""


class WorkflowLedgerMigrationError(WorkflowLedgerError):
    """A schema migration failed and was rolled back."""


class WorkflowLedgerCorruptionError(WorkflowLedgerError):
    """integrity_check or content validation detected corruption."""


class WorkflowLedgerBackpressureError(WorkflowLedgerError):
    """Writer queue is full or timed out."""


class WorkflowLedgerClosedError(WorkflowLedgerError):
    """The ledger store has been closed."""


class WorkflowLedgerConflictError(WorkflowLedgerError):
    """Optimistic concurrency or uniqueness conflict."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class RunVersionConflictError(WorkflowLedgerConflictError):
    def __init__(self, detail: str = "expectedRunVersion is stale") -> None:
        super().__init__("run_version_conflict", detail)


class IdempotencyConflictError(WorkflowLedgerConflictError):
    def __init__(self, detail: str = "same idempotency key with a different request") -> None:
        super().__init__("idempotency_conflict", detail)


class CommandNotAllowedError(WorkflowLedgerConflictError):
    def __init__(self, detail: str = "command not allowed in current state") -> None:
        super().__init__("command_not_allowed", detail)
