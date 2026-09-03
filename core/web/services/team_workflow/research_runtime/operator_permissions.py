"""Operator roles/permissions for high-impact workflow commands (review P1)."""

from __future__ import annotations

# Roles that may control catalog runs, cancel/fork/rebind, extend budgets, or
# resolve human gates.
OPERATOR_PRIVILEGED_ROLES: frozenset[str] = frozenset(
    {
        "operator",
        "admin",
        "research_lead",
        "team_owner",
        "challenge_operator",
    }
)

HIGH_IMPACT_COMMANDS: frozenset[str] = frozenset(
    {
        "cancel_node",
        "cancel_run",
        "authorize_catalog_run",
        "start_catalog_run",
        "poll_catalog_run",
        "cancel_catalog_run",
        "resolve_human_task",
        "extend_budget",
        "rebind_node",
        "fork_revision",
        "record_g12_calibration",
        "read_g12_calibration",
    }
)


def operator_has_privileged_role(roles: tuple[str, ...] | list[str] | None) -> bool:
    normalized = {
        str(item or "").strip().lower()
        for item in (roles or ())
        if str(item or "").strip()
    }
    return bool(normalized & {role.lower() for role in OPERATOR_PRIVILEGED_ROLES})


def require_operator_permission(
    *,
    operator_id: str,
    roles: tuple[str, ...] | list[str] | None,
    command: str,
) -> None:
    """Raise PermissionError when high-impact command lacks privileged roles."""
    if not str(operator_id or "").strip():
        raise PermissionError("command_forbidden")
    command_key = str(command or "").strip().lower()
    if command_key not in HIGH_IMPACT_COMMANDS:
        return
    if not operator_has_privileged_role(roles):
        raise PermissionError("command_forbidden")
