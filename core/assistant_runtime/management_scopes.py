"""Project scopes used by Launcher assistant permission planning."""


def read_scopes(action: str) -> list[str] | None:
    return {
        "task_list": ["tasks:read"], "source_read": ["source:read"], "source_search": ["source:read"],
        "agent_get": ["agents:read"], "agent_purge_preview": ["agents:read"], "avatar_options": ["agents:read"],
        "agent_list": ["agents:directory:read"],
        "session_list": ["sessions:read"], "session_get": ["sessions:read"],
        "session_config_get": ["sessions:read"], "session_config_compare": ["sessions:read"],
        "session_parameters_get": ["sessions:parameters:read", "sessions:read"],
        "team_list": ["teams:directory:read"], "team_get": ["teams:directory:read"],
        "team_result": ["teams:results:read"], "flow_result": ["teams:results:read"],
        "runtime_list": ["operations:read"], "runtime_get": ["operations:read"],
        "research_get": ["operations:read"], "team_recovery_get": ["operations:read"], "knowledge_list": ["knowledge:catalog:read"],
        "team_asset_get": ["teams:manage:read"], "team_archive_preview": ["teams:manage:read"],
        "team_status": ["teams:read"],
        "agent_tool_policy_get": ["agents:tool-policy:read"],
        "agent_tool_policy_inspect": ["agents:tool-policy:read"],
        "agent_config_get": ["agents:configuration:read"], "agent_prompt_get": ["agents:configuration:read"],
        "agent_dispatch_access_get": ["agents:dispatch-access:read"],
        "knowledge_acl_get": ["knowledge:acl:read"],
        "flow_list": ["teams:flows:read"], "flow_get": ["teams:flows:read"],
        "team_knowledge_list": ["knowledge:catalog:read", "teams:directory:read"],
        "room_list": ["rooms:read"], "room_get": ["rooms:read"],
        "legacy_observers": ["legacy:receipts:read"], "legacy_receipts": ["legacy:receipts:read"],
        "api_catalog": ["platform:describe"], "api_describe": ["platform:describe"],
    }.get(action)


def plan_project_scopes(actions: list[str]) -> dict[str, list[str]]:
    from core.web.services.external_management.contracts import ACTION_SCOPES

    required = {}
    for name in actions:
        scopes = read_scopes(name)
        if scopes is None:
            if name in {"agents", "dispatch", "receipt", "dispatch_write"}:
                scopes = []
            elif name in ACTION_SCOPES:
                scope = ACTION_SCOPES[name]
                scopes = [scope] if scope else []
                if name == "team_archive":
                    scopes.append("agents:archive")
            else:
                raise ValueError("Unknown project authorization action")
        required[name] = scopes
    return required
