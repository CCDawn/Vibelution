"""Personal assistant identity and public platform projection over native services."""

from __future__ import annotations

import hashlib
import json
import threading

from core.web.services import agent_directory_service as directory
from core.web.services import pet_activity_service, session_service
from core.web.services.session_archive_service import conversation_is_archived

PROFILE = "personal_assistant_v1"
ROLE = "personal_assistant"
TOOLS = (
    "personal_assistant_overview_tool",
    "personal_assistant_manage_tool",
    "append_personal_memory_tool",
    "supersede_personal_memory_tool",
)
LEGACY_POLICY = {
    "allowedTools": list(TOOLS),
    "preferredTools": list(TOOLS),
    "networkAccess": "none",
    "mutationAccess": "controlled",
    "maxCallsPerTurn": 8,
}
POLICY = {**LEGACY_POLICY, "writeScopes": ["private"]}
PERSONA = {
    "personality": "温和、可靠，尊重用户的偏好和注意力。",
    "communicationStyle": "用中文先讲结论，说明观察依据和需要用户决定的事项。",
    "identityNotes": "个人助理，以大肥鲸形象陪伴用户；页面和桌面模式共享同一身份、会话和记忆。",
    "expertise": ["个人事务", "目标与偏好", "平台管理"],
}
TASK = {
    "mission": "协助用户安排事务、推进目标，并管理 Vibelution 平台。",
    "responsibilities": "读取平台公开状态，主动提出有依据的建议；收到用户指令后通过授权工具执行并报告结果。",
    "constraints": "观察不等于执行授权。删除、重启和权限变更须逐次确认具体对象与影响，等待原生工具审批；不得绕过策略、使用任意命令或读取其他 Agent 的私密记忆和会话正文。桌面模式不扩大权限。",
    "preferredTasks": "事务梳理、目标跟进、平台状态解释、Agent 和任务管理。",
    "avoidTasks": "未经指令改变平台；用推测冒充执行结果；重复创建已存在的助理。",
}
_LOCK = threading.RLock()
COMPOSER_STARTERS = (
    {
        "heading": "平台概况",
        "command": "看看平台有哪些正在运行、等待确认或异常的任务，给我处理建议。先观察，不执行操作。",
    },
    {
        "heading": "安排事务",
        "command": "帮我梳理今天要做的事情，按重要程度和时间安排。",
    },
    {
        "heading": "目标跟进",
        "command": "和我一起确定近期目标，并拆出今天可以完成的一步。",
    },
)


def composer_starters_for_agent(
    agent_id: str, session_id: str
) -> list[dict[str, str]] | None:
    """Presentation override only for this profile's canonical direct Session."""
    candidate = directory.get_agent(agent_id)
    if (
        not candidate
        or (candidate.get("metadata") or {}).get("personalAssistantProfile") != PROFILE
    ):
        return None
    agent = _profile_agent()
    if (
        not agent
        or agent.get("status") != "active"
        or agent["agentId"] != agent_id
        or agent.get("directSessionId") != session_id
    ):
        return None
    return [dict(row) for row in COMPOSER_STARTERS]


def _profile_agent() -> dict | None:
    matches = [
        row
        for row in directory.list_agents(include_archived=True, detail="config")
        if (row.get("metadata") or {}).get("personalAssistantProfile") == PROFILE
    ]
    if len(matches) > 1:
        raise directory.AgentStateConflictError(
            "多个个人助理身份需要在 Agent 管理中核对。"
        )
    agent = matches[0] if matches else None
    if agent and (
        agent.get("roleKey") != ROLE or agent.get("primaryMode") != "general"
    ):
        raise directory.AgentStateConflictError(
            "个人助理身份配置已更改，请在 Agent 管理中核对。"
        )
    return agent


def _session_row(agent: dict) -> dict | None:
    session_id = str(agent.get("directSessionId") or "").strip()
    return (
        session_service.load_session_chat_state(
            session_service.PROJECT_ROOT, session_id
        )
        if session_id
        else None
    )


def _owns_session(agent: dict, row: dict | None) -> bool:
    return (
        bool(row)
        and str(row.get("agentId") or row.get("agent_id") or "") == agent["agentId"]
        and not conversation_is_archived(row)
    )


def _needs_default_policy_upgrade(agent: dict) -> bool:
    """Recognize only the untouched, private v1 assistant provisioning policy."""
    policy_id = "tool-" + agent["agentId"]
    if (
        agent.get("createdBy") != "user_personal_assistant"
        or agent.get("toolPolicyId") != policy_id
    ):
        return False
    expected = directory.normalize_tool_policy(LEGACY_POLICY, policy_id)
    version = (agent.get("toolPolicy") or {}).get("policyVersion")
    pending = (agent.get("metadata") or {}).get("personalAssistantSetup") != "ready"
    expected["policyVersion"] = 1 if pending and version == 1 else 2
    return agent.get("toolPolicy") == expected


def _project(agent: dict) -> dict:
    ready = (agent.get("metadata") or {}).get("personalAssistantSetup") == "ready"
    valid = _owns_session(agent, _session_row(agent))
    return {
        "agentId": agent["agentId"],
        "displayName": agent["displayName"],
        "directSessionId": str(agent.get("directSessionId") or "") if valid else "",
        "status": "active",
        "setupStatus": "ready"
        if ready and valid and not _needs_default_policy_upgrade(agent)
        else "session_missing"
        if ready and not valid
        else "setup_required",
        "renderer": "whale",
        "profile": PROFILE,
    }


def get_personal_assistant() -> dict:
    """Pure read: provisioning and missing Session repair require explicit POST."""
    agent = _profile_agent()
    return {
        "assistant": _project(agent)
        if agent and agent.get("status") == "active"
        else None
    }


def create_personal_assistant(display_name: str = "个人助理") -> dict:
    name = str(display_name or "").strip()
    if not name or len(name) > 80 or any(ord(char) < 32 for char in name):
        raise directory.AgentDirectoryError("请输入 1–80 字的单行名称。")
    with _LOCK:
        agent = _profile_agent()
        created = agent is None
        if agent is None:
            agent = directory.create_agent_instance(
                display_name=name,
                primary_mode="general",
                role_key=ROLE,
                prompt_template_id="prompt-chat-default",
                created_by="user_personal_assistant",
                initial_tool_policy=POLICY,
                llm_bindings=session_service.default_session_llm_bindings(),
                metadata={
                    "personalAssistantProfile": PROFILE,
                    "personalAssistantSetup": "pending",
                    "personaProfile": PERSONA,
                    "taskProfile": TASK,
                },
            )
        if agent.get("status") != "active":
            raise directory.AgentStateConflictError(
                "个人助理已归档，请在 Agent 管理中确认是否恢复。"
            )
        row = _session_row(agent)
        if row and not _owns_session(agent, row):
            raise directory.AgentStateConflictError(
                "个人助理会话已归档或属于其他 Agent，请先核对绑定。"
            )
        pending = (agent.get("metadata") or {}).get("personalAssistantSetup") != "ready"
        if pending and created:
            directory.update_agent_instance(
                agent["agentId"],
                persona_profile=PERSONA,
                task_profile=TASK,
                tool_policy=POLICY,
                delegation_policy={"allowSubagents": False, "allowWakeMessages": False},
            )
        elif _needs_default_policy_upgrade(agent):
            # Explicit provisioning upgrades only the unmodified legacy policy.
            # User-authored policies and all persona/task fields remain intact.
            directory.update_agent_instance(
                agent["agentId"],
                tool_policy=POLICY,
                expected_tool_policy_fingerprint=directory.tool_policy_fingerprint(
                    agent["toolPolicy"]
                ),
            )
        if not row:
            # Native service owns unbinding/recreation of deleted direct Sessions.
            session_service.ensure_agent_direct_session(
                agent_id=agent["agentId"],
                title=agent["displayName"],
                created_by="personal_assistant",
            )
        if pending:
            directory.update_agent_instance(
                agent["agentId"], metadata={"personalAssistantSetup": "ready"}
            )
        return {
            "assistant": _project(
                directory.get_agent(agent["agentId"], include_archived=True)
            )
        }


def get_platform_overview(*, offset: int = 0, limit: int = 100) -> dict:
    """Public summaries only; no transcript, prompt, tool arguments or config."""
    if (
        type(offset) is not int
        or offset < 0
        or type(limit) is not int
        or not 1 <= limit <= 100
    ):
        raise ValueError("概览 offset 必须为非负整数，limit 必须为 1–100。")
    agents = directory.list_agents(detail="summary")
    sessions = session_service.list_sessions()
    activity = pet_activity_service.get_pet_activity()
    live = {row["sessionId"]: row for row in activity["sessions"]}
    attention = [
        {
            "id": row["sessionId"],
            "kind": "approval" if row["tone"] == "approval" else "error",
            "title": row["title"],
            "sessionId": row["sessionId"],
        }
        for row in activity["sessions"]
        if row["tone"] in {"approval", "error"}
    ]
    public = {
        "counts": {
            "agents": len(agents),
            "sessions": len(sessions),
            "running": sum(row["tone"] == "running" for row in live.values()),
            "waiting": sum(row["tone"] == "approval" for row in live.values()),
            "failed": sum(row["tone"] == "error" for row in live.values()),
        },
        "agents": [
            {
                "id": row["agentId"],
                "displayName": row["displayName"],
                "status": row["status"],
            }
            for row in agents
        ],
        "sessions": [
            {
                "id": row["id"],
                "agentId": str(row.get("agentId") or ""),
                "title": pet_activity_service._safe_session_title(
                    row.get("title"),
                    session_id=row["id"],
                    agent_name=row.get("agentDisplayName"),
                ),
                "status": str(row.get("status") or ""),
                "turnId": session_service._current_session_turn_id(row["id"]),
                "currentPhase": str(
                    live.get(row["id"], {}).get("phase")
                    or row.get("currentPhase")
                    or "idle"
                ),
            }
            for row in sessions
        ],
        "attention": attention,
    }
    revision = hashlib.sha256(
        json.dumps(public, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    end = offset + limit
    return {
        "generatedAt": activity["generatedAt"],
        "counts": public["counts"],
        "agents": public["agents"][offset:end],
        "sessions": public["sessions"][offset:end],
        "attention": attention[offset:end],
        "pagination": {
            "offset": offset,
            "limit": limit,
            "revision": revision,
            "nextOffset": end if end < max(len(agents), len(sessions), len(attention)) else None,
        },
    }
