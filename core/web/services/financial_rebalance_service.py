"""Public facade for research-linked paper portfolio proposals."""

from core.web.services.financial_rebalance.service import (
    approve_proposal,
    create_proposal,
    get_proposal,
    list_proposals,
    preview_proposal,
)

__all__ = ["approve_proposal", "create_proposal", "get_proposal", "list_proposals", "preview_proposal"]
