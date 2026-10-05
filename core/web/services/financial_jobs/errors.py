"""Errors raised by the financial research jobs service."""


class FinancialJobError(RuntimeError):
    """Base error for bounded finance job operations."""


class FinancialJobNotFoundError(FinancialJobError):
    """The Agent, schedule, or batch does not exist for this owner."""


class FinancialJobConflictError(FinancialJobError):
    """A safe state transition cannot be made from the current snapshot."""


class FinancialJobValidationError(FinancialJobError):
    """The submitted finance job does not satisfy its contract."""


class FinancialJobStoreError(FinancialJobError):
    """Persisted schedule state is corrupt or belongs to another owner."""
