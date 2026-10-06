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
    submit_financial_team_primary_role as _submit_financial_team_primary_role,
    submit_financial_team_synthesis,
)


def submit_financial_team_primary_role(
    assistant_agent_id: str, run_id: str, role: str
) -> dict:
    """Submit the user-started primary turn and activate its managed successor."""

    accepted = _submit_financial_team_primary_role(assistant_agent_id, run_id, role)
    if str(role or "").strip() in {"market", "fundamental", "news"}:
        from core.web.services.financial_team.coordinator import (
            register_after_primary_acceptance,
        )

        return register_after_primary_acceptance(assistant_agent_id, run_id)
    return accepted


def financial_team_synthesis_recovery_status(
    assistant_agent_id: str, run_id: str
) -> dict:
    """Return the live, fail-closed recovery eligibility for one blocked run."""

    from core.web.services.financial_team.coordinator import FinancialTeamCoordinator

    return FinancialTeamCoordinator().synthesis_recovery_status(assistant_agent_id, run_id)


def recover_financial_team_synthesis(
    assistant_agent_id: str, run_id: str
) -> dict:
    """Resume synthesis on the existing run after coordinator and transcript checks."""

    from core.web.services.financial_team.coordinator import FinancialTeamCoordinator

    return FinancialTeamCoordinator().recover_blocked_synthesis(assistant_agent_id, run_id)

__all__ = [
    "FinancialTeamConflictError",
    "FinancialTeamError",
    "FinancialTeamNotFoundError",
    "FinancialTeamRunConflictError",
    "FinancialTeamRunError",
    "FinancialTeamRunNotFoundError",
    "FinancialTeamRunNotReadyError",
    "create_financial_team_run",
    "financial_team_synthesis_recovery_status",
    "get_financial_team",
    "get_financial_team_run",
    "list_financial_team_runs",
    "provision_financial_team",
    "recover_financial_team_synthesis",
    "record_financial_team_turn",
    "submit_financial_team_debate",
    "submit_financial_team_primary_role",
    "submit_financial_team_synthesis",
]
