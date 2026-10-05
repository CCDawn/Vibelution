"""Public facade for native financial multi-analyst collaboration."""

from core.web.services.financial_team import (
    FinancialTeamConflictError,
    FinancialTeamError,
    FinancialTeamNotFoundError,
    FinancialTeamRunConflictError,
    FinancialTeamRunError,
    FinancialTeamRunNotFoundError,
    FinancialTeamRunNotReadyError,
    create_financial_team_run,
    get_financial_team,
    get_financial_team_run,
    list_financial_team_runs,
    provision_financial_team,
    record_financial_team_turn,
    submit_financial_team_debate,
    submit_financial_team_primary_role,
    submit_financial_team_synthesis,
)

__all__ = [
    "FinancialTeamConflictError",
    "FinancialTeamError",
    "FinancialTeamNotFoundError",
    "FinancialTeamRunConflictError",
    "FinancialTeamRunError",
    "FinancialTeamRunNotFoundError",
    "FinancialTeamRunNotReadyError",
    "create_financial_team_run",
    "get_financial_team",
    "get_financial_team_run",
    "list_financial_team_runs",
    "provision_financial_team",
    "record_financial_team_turn",
    "submit_financial_team_debate",
    "submit_financial_team_primary_role",
    "submit_financial_team_synthesis",
]
