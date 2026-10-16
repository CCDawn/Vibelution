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
        "targetAgentId",
        "actorAgentId",
    }
    return json.dumps(
        {
            key: value
            for key, value in result.items()
            if key in allowed and isinstance(value, (str, bool, int, float, type(None)))
        },
        ensure_ascii=False,
    )


def personal_assistant_overview_tool(offset: int = 0, limit: int = 100) -> str:
    """Read public platform status without private memories or transcripts."""
    try:
        _identity()
        return json.dumps(
            {"ok": True, **service.get_platform_overview(offset=offset, limit=limit)}, ensure_ascii=False
        )
    except (ValueError, directory.AgentDirectoryError) as exc:
        return _error(str(exc))


def personal_assistant_manage_tool(action: str, arguments_json: str) -> str:
    """Bounded governed operations; native descriptor requires approval every call.

    Actions: agent_create, agent_update, agent_archive, session_create,
    session_update, session_stop, session_delete, knowledge_acl_grant, restart.
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
        # Closed dispatch table; signature binding rejects extra fields before
        # invoking any underlying service. Approval stays in native execution.
        dispatch = {
            "agent_create": operations.agent_create_tool,
            "agent_update": operations.agent_update_tool,
            "agent_archive": operations.agent_archive_tool,
            "session_create": operations.session_create_tool,
            "session_update": operations.session_update_tool,
            "session_stop": operations.session_stop_tool,
            "session_delete": operations.session_delete_tool,
            "knowledge_acl_grant": operations.knowledge_base_acl_grant_tool,
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
