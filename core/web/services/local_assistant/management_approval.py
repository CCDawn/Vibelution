"""Native-only management consent; project ACLs and execution remain authoritative."""
from __future__ import annotations

import json

from pydantic import ValidationError


# A closed list prevents newly added actions from silently inheriting autonomy.
_ROUTINE = frozenset({
    "agent_create", "agent_update", "agent_avatar", "session_pin", "team_create",
    "team_member_add", "team_member_remove", "team_update", "team_run", "flow_save",
    "flow_start", "knowledge_ingest", "knowledge_acl_revoke", "dispatch_write",
    "dispatch_cancel", "dispatch_derived", "delegation_goal_create", "delegation_goal_revoke",
    "authorization_reduce", "authorization_revoke",
    "agent_parameters_update", "agent_prompt_update",
})
_DESTRUCTIVE = frozenset({"agent_archive", "agent_purge", "agent_purge_batch", "team_archive", "project_lifecycle",
                          "branch_cleanup_execute"})
_EXPLICIT = frozenset({"authorization_upgrade", "agent_tool_policy_update", "knowledge_acl_grant",
                       "config_update", "reminder_handoff_recover"})
_READS = frozenset({"delegation_goal_get", "delegation_goal_list", "branch_cleanup_plan"})


def parse_arguments(raw: str) -> dict:
    """Use the same unambiguous object for consent and native execution."""
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate management argument")
            result[key] = value
        return result

    def invalid_constant(_value):
        raise ValueError("Non-finite management argument")

    if not isinstance(raw, str) or len(raw) > 16000:
        raise ValueError("Invalid management arguments")
    try:
        value = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid_constant)
    except (TypeError, RecursionError) as exc:
        raise ValueError("Invalid management arguments") from exc
    if not isinstance(value, dict):
        raise ValueError("Management arguments must be an object")
    return value


def _risk(action: str, parameters: dict) -> str:
    from core.assistant_runtime import actions
    from core.assistant_runtime.provider_approval import PROVIDER_APPROVAL_ACTIONS, validate_provider_model_resolve

    if action in PROVIDER_APPROVAL_ACTIONS:
        validate_provider_model_resolve(parameters)
        return "write"

    managed = actions._management_contracts()
    if action in managed:
        model = managed[action][0]
    elif action == "project_lifecycle":
        model = actions.ProjectLifecycle
    elif action == "reminder_handoff_recover":
        model = actions.HistoryImport
    else:
        if action not in {"branch_cleanup_plan", "branch_cleanup_execute"}:
            raise ValueError("Unclassified management action")
        from core.web.services.local_assistant import branch_cleanup_actions
        model = branch_cleanup_actions.BranchCleanupPlan if action == "branch_cleanup_plan" \
            else branch_cleanup_actions.BranchCleanupExecute
    values = model.model_validate(parameters, strict=True).model_dump()
    # These existing projections additionally validate complete, displayable
    # identities and exact cascade scopes before any mode can skip a prompt.
    if action in {"agent_archive", "agent_purge", "agent_purge_batch"}:
        getattr(actions, f"{action}_approval_summary")(parameters)
    from core.assistant_runtime.platform_approval import PLATFORM_MANAGEMENT_ACTIONS, platform_management_approval_summary
    if action in PLATFORM_MANAGEMENT_ACTIONS:
        platform_management_approval_summary(action, parameters)
    if action in _EXPLICIT:
        return "explicit"
    if action in _READS:
        return "read"
    if action in _DESTRUCTIVE:
        return "destructive"
    if action == "runtime_command":
        return "explicit" if values["command"] == "confirm" else "execute"
    if action == "research_command":
        return "explicit" if values["command"] == "resolve_human_task" else "execute"
    if action == "agent_dispatch_access_set":
        return "explicit" if values["enabled"] else "execute"
    if action in _ROUTINE:
        return "destructive" if action == "agent_create" and values.get("capability_preset") else "execute"
    raise ValueError("Unclassified management action")


def approval_requirement(runtime: dict, tool_args: dict) -> tuple[str, str] | None:
    """Snapshot policy at entry; already pending requests still need a decision.

    This only removes the native manage-tool consent requirement. Neither this
    function nor a saved mode grants project scopes or authorizes side effects.
    """
    try:
        if set(tool_args) != {"action", "arguments_json"} or not isinstance(tool_args["action"], str):
            raise ValueError("Invalid management call")
        risk = _risk(tool_args["action"], parse_arguments(tool_args["arguments_json"]))
    except (ValueError, TypeError, KeyError, RuntimeError, RecursionError, ValidationError):
        return "always", "destructive"
    if risk == "read":
        return None
    if risk == "explicit":
        return "always", "destructive"
    from core.assistant_runtime.provider_approval import PROVIDER_APPROVAL_ACTIONS
    if tool_args["action"] in PROVIDER_APPROVAL_ACTIONS:
        return "always", risk
    try:
        from .management_permissions import read
        mode = read(runtime.get("agentId", ""))["preset"]
    except (ValueError, TypeError, KeyError, RuntimeError, OSError):
        mode = "request_approval"
    if mode == "full_access" or mode == "auto_review" and risk == "execute":
        return None
    return "always", risk
