"""Public service facade for the financial Agent's simulation-only ledger."""

from core.web.services.financial_paper import (
    AccountNotOpenedError,
    FinancialPaperError,
    IdempotencyConflictError,
    InsufficientCashError,
    InsufficientSharesError,
    InvalidPaperOrderError,
    PaperAccountConflictError,
    get_account_snapshot,
    get_review_snapshot,
    open_account,
    submit_order,
)

__all__ = [
    "AccountNotOpenedError",
    "FinancialPaperError",
    "IdempotencyConflictError",
    "InsufficientCashError",
    "InsufficientSharesError",
    "InvalidPaperOrderError",
    "PaperAccountConflictError",
    "get_account_snapshot",
    "get_review_snapshot",
    "open_account",
    "submit_order",
]
