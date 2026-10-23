"""Scoped personal manager tools delegating to the existing governed operations."""

from __future__ import annotations

import json

from core.web.services import agent_directory_service as directory
from core.web.services import personal_assistant_service as service
from tools import project_operation_tools as operations


def _identity() -> dict:
    runtime = directory.current_agent_runtime()
    agent_id = str(runtime.get("agentId") or "").strip()
    session_id = str(runtime.get("sessionId") or "").strip()
    agent = directory.get_agent(agent_id) if agent_id else None
    if (
        not agent
        or agent.get("status") != "active"
        or agent.get("roleKey") != service.ROLE
        or agent.get("primaryMode") != "general"
        or (agent.get("metadata") or {}).get("personalAssistantProfile")
        != service.PROFILE
    ):
        raise ValueError("此工具仅供已绑定的个人助理使用。")
    if (
        not session_id
        or session_id != agent.get("directSessionId")
        or not service._owns_session(agent, service._session_row(agent))
    ):
        raise ValueError("个人助理原生会话身份不匹配。")
    canonical = service.get_personal_assistant()["assistant"]
    if (
        not canonical
        or canonical["agentId"] != agent_id
        or canonical["setupStatus"] != "ready"
    ):
        raise ValueError("个人助理唯一身份未就绪。")
    return runtime


def _error(message: str) -> str:
    return json.dumps(
        {"ok": False, "status": "blocked", "message": message}, ensure_ascii=False
    )


def _query_identity() -> tuple[dict, str]:
    """Allow the bundled coordinator's public reads, without manager identity."""
    from core.web.services.agent_directory.bootstrap import (
        PLATFORM_PLANNER_PRESET,
        PLATFORM_PLANNER_ROLE_KEY,
    )

    runtime = directory.current_agent_runtime()
    agent_id = str(runtime.get("agentId") or "").strip()
    session_id = str(runtime.get("sessionId") or "").strip()
    agent = directory.get_agent(agent_id) if agent_id else None
    if (
        agent
        and agent.get("status") == "active"
        and agent.get("primaryMode") == "chat"
        and agent.get("roleKey") == PLATFORM_PLANNER_ROLE_KEY
        and (agent.get("metadata") or {}).get("builtinPreset") == PLATFORM_PLANNER_PRESET
    ):
        if (
            not session_id
            or session_id != agent.get("directSessionId")
            or not service._owns_session(agent, service._session_row(agent))
        ):
            raise ValueError("平台规划师原生会话身份不匹配。")
        return runtime, "platform_planner"
    return _identity(), "assistant"


def personal_assistant_query_tool(resource: str = "index", operation: str = "list", object_id: str = "",
                                  query: str = "", path: str = "", offset: int = 0, limit: int = 20,
                                  line: int = 1, max_lines: int = 80) -> str:
    """Read registered sources for the canonical assistant or bundled planner."""
    try:
        runtime, caller = _query_identity()
    except (ValueError, TypeError, directory.AgentDirectoryError):
        return _error("个人助理或平台规划师原生身份未就绪，请先核对绑定。")
    from core.web.services.personal_assistant_project.query import query_project

    return json.dumps(query_project(runtime, caller=caller, resource=resource, operation=operation, object_id=object_id,
        query=query, path=path, offset=offset, limit=limit, line=line, max_lines=max_lines), ensure_ascii=False)


def personal_assistant_platform_api_tool(path: str = "index", query: str = "", tag: str = "") -> str:
    """Read platform management state through the loopback workbench API (GET-only)."""
    try:
        _identity()
    except (ValueError, TypeError, directory.AgentDirectoryError):
        return _error("个人助理原生身份或配置未就绪，请先核对绑定。")
    from core.web.services.personal_assistant_platform_api import (
        platform_api_get,
        platform_api_index,
    )

    normalized = str(path or "").strip()
    if normalized == "index":
        return json.dumps(platform_api_index(tag=tag), ensure_ascii=False)
    return json.dumps(platform_api_get(normalized, query=query), ensure_ascii=False)


def _receipt(raw: str) -> str:
    """Preserve native outcome and object ids without returning private objects."""
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise TypeError("管理操作未返回有效回执。")
    allowed = {
        "ok",
        "status",
        "message",
        "error",
        "agentId",
        "sessionId",
        "turnId",
        "directSessionId",
        "deletedSessionId",
        "knowledgeBaseId",
        "knowledgeItemId",
        "targetAgentId",
        "actorAgentId",
        "teamId",
        "flowId",
        "runId",
        "bindingId",
        "expiresAt",
    }
    return json.dumps(
        {
            key: value
            for key, value in result.items()
            if key in allowed and isinstance(value, (str, bool, int, float, type(None)))
        },
        ensure_ascii=False,
    )


def personal_assistant_overview_tool(offset: int = 0, limit: int = 100, team_id: str = "", flow_id: str = "") -> str:
    """Read public platform status without private memories or transcripts."""
    try:
        runtime = _identity()
        if team_id or flow_id:
            if not team_id or not flow_id:
                raise ValueError("查询恢复任务需要同时提供 team_id 和 flow_id。")
            from core.web.services import generic_team_workflow_service as workflow
            binding = workflow.get_recovery_binding(team_id, flow_id)
            if binding["assistantAgentId"] != runtime["agentId"]:
                raise ValueError("该流程未绑定当前个人助理。")
            recent = [{"runId": row["id"], "status": row["status"], "current": row["current"],
                       "revision": row["revision"], "recovery": row.get("recovery")}
                      for row in workflow.list_runs(team_id, flow_id=flow_id, limit=20)["runs"]
                      if row["flow"]["id"] == flow_id][:20]
            return json.dumps({"ok": True, "binding": binding, "recentRuns": recent}, ensure_ascii=False)
        from core.web.services.personal_attention_service import attach_attention_to_overview
        return json.dumps({"ok": True, **attach_attention_to_overview(
            service.get_platform_overview(offset=offset, limit=limit))}, ensure_ascii=False)
    except (ValueError, directory.AgentDirectoryError) as exc:
        return _error(str(exc))


def personal_assistant_manage_tool(action: str, arguments_json: str) -> str:
    """Bounded governed operations; native descriptor requires approval every call.

    Actions: agent_create, agent_update, agent_archive, session_create,
    session_update, session_stop, session_delete, knowledge_acl_grant, restart,
    workflow_recovery_bind, workflow_recovery_revoke, workflow_start,
    team_create, knowledge_ingest, config_update.
    Arguments use the corresponding canonical tool's named parameters.
    No arbitrary API, command, purge, restore, or private data read is accepted.
    """
    try:
        runtime = _identity()
        if len(arguments_json) > 16000:
            raise ValueError("管理参数过长。")
        args = json.loads(arguments_json)
        if not isinstance(args, dict):
            raise TypeError("管理参数必须是 JSON 对象。")
        if action in {"workflow_recovery_bind", "workflow_recovery_revoke", "workflow_start"}:
            return _workflow_action(action, args, runtime)
        # Closed dispatch table; signature binding rejects extra fields before
        # invoking any underlying service. Approval stays in native execution.
        from tools import pa_managed_writes

        dispatch = {
            "agent_create": operations.agent_create_tool,
            "agent_update": operations.agent_update_tool,
            "agent_archive": operations.agent_archive_tool,
            "session_create": operations.session_create_tool,
            "session_update": operations.session_update_tool,
            "session_stop": operations.session_stop_tool,
            "session_delete": operations.session_delete_tool,
            "knowledge_acl_grant": operations.knowledge_base_acl_grant_tool,
            "team_create": pa_managed_writes.team_create_tool,
            "knowledge_ingest": pa_managed_writes.knowledge_ingest_tool,
            "config_update": pa_managed_writes.config_update_tool,
        }
        if action == "restart":
            if (
                set(args) != {"reason"}
                or not isinstance(args["reason"], str)
                or not args["reason"].strip()
            ):
                raise ValueError("重启必须说明原因，只接受 reason。")
            from tools.rebirth_tools import trigger_self_restart_tool

            return trigger_self_restart_tool(
                reason=args["reason"], sessionId=runtime["sessionId"]
            )
        target = dispatch.get(action)
        if target is None:
            raise ValueError("不支持的管理操作。请通过平台对应管理页面处理。")
        # The manager cannot impersonate a knowledge owner.
        if action == "knowledge_acl_grant" and "actor_agent_id" in args:
            raise ValueError("不得冒用其他 Agent 的知识库权限。")
        import inspect

        inspect.signature(target).bind(**args)
        return _receipt(target(**args))
    except (ValueError, TypeError, directory.AgentDirectoryError) as exc:
        return _error(str(exc))


def _workflow_action(action: str, args: dict, runtime: dict) -> str:
    """Closed, approval-preserving handoff; no arbitrary API or actor field."""
    if set(args) != {"team_id", "flow_id", "payload"} or not isinstance(args["payload"], dict):
        raise ValueError("流程操作只接受 team_id、flow_id 和 payload 对象。")
    from core.web.services import generic_team_workflow_service as workflow

    team_id, flow_id = args["team_id"], args["flow_id"]
    payload = dict(args["payload"])
    if action == "workflow_recovery_bind":
        if "assistantAgentId" in payload:
            raise ValueError("个人助理身份由当前原生会话绑定，不能在参数中冒用。")
        payload["assistantAgentId"] = runtime["agentId"]
        result = workflow.bind_recovery(team_id, flow_id, payload)
    else:
        binding = workflow.get_recovery_binding(team_id, flow_id)
        if binding["assistantAgentId"] != runtime["agentId"]:
            raise ValueError("该流程未绑定当前个人助理。")
        if action == "workflow_recovery_revoke":
            result = workflow.revoke_recovery(team_id, flow_id, payload)
        else:
            if binding["status"] != "ready":
                raise ValueError("流程的角色或授权未就绪，不能自动交办。")
            run = workflow.start_run(team_id, flow_id, payload)
            result = {"teamId": team_id, "flowId": flow_id, "runId": run["id"], "status": run["status"]}
    return _receipt(json.dumps({"ok": True, **result}, ensure_ascii=False))
