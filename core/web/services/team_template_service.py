"""Reusable Team templates for demo and onboarding flows."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.chat.chat_task_types import trim_lines

from . import agent_directory_service, chat_room_service, session_service, team_service
from .team import role_definition_service
from .runtime_scene_service import record_runtime_scene_event


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEV_TEAM_TEMPLATE_ID = "dev-team"
# dev-team 模板的角色声明来自声明式角色文件层（workspace 共享角色库），
# 顺序即成员行 / 画布节点顺序（规划师 → 开发 A → 开发 B → 评审员）。
DEV_TEAM_ROLE_KEYS: tuple[str, str, str, str] = (
    "dev_team_planner",
    "dev_team_developer_a",
    "dev_team_developer_b",
    "dev_team_reviewer",
)
TEAM_TEMPLATE_REQUIRED_ALLOWED_TOOLS = ("agent_message_tool",)


class TeamTemplateError(ValueError):
    """Raised when a Team template request is invalid."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_team_templates() -> dict[str, Any]:
    templates = [_template_to_summary(template) for template in _all_templates()]
    return {
        "schemaVersion": 1,
        "templates": templates,
        "summary": {"templateCount": len(templates)},
        "updatedAt": utc_now_iso(),
    }


def get_team_template(template_id: str) -> dict[str, Any]:
    template = _resolve_template(template_id)
    return dict(template)


def instantiate_team_template(template_id: str, *, name: str = "") -> dict[str, Any]:
    template = _resolve_template(template_id)
    _sync_project_roots()
    created_agents: list[dict[str, Any]] = []
    members: list[dict[str, Any]] = []
    for index, role in enumerate(template["roles"], start=1):
        session = session_service.create_chat_session(
            title=str(role["agentName"]),
            llm_bindings=session_service.default_session_llm_bindings(),
            created_by="team_template",
        )
        agent_id = str(session.get("agentId") or "").strip()
        if not agent_id:
            raise TeamTemplateError(f"Template role did not create an Agent: {role['role']}")
        agent = agent_directory_service.update_agent_instance(
            agent_id,
            display_name=str(role["agentName"]),
            primary_mode="chat",
            role_key=str(role["roleKey"]),
            tool_policy=_role_tool_policy(role),
            persona_profile=role["personaProfile"],
            task_profile=role["taskProfile"],
            metadata={
                "teamTemplateId": template["templateId"],
                "teamTemplateRole": role["roleKey"],
                **dict(template.get("agentMetadata") or {}),
            },
        )
        created_agents.append(agent)
        members.append(
            {
                "memberId": f"{template.get('memberIdPrefix') or 'template-member'}-{index}",
                "agentId": agent["agentId"],
                "role": role["role"],
                "purpose": role["purpose"],
                "responsibilities": list(role.get("responsibilities") or []),
            }
        )

    team = team_service.create_team(
        name=trim_lines(name or "", max_lines=1).strip() or str(template["defaultTeamName"]),
        description=str(template["description"]),
        purpose=str(template["purpose"]),
        members=members,
        team_kind="template_demo",
        team_category="演示业务团队",
        team_source="team_template",
        team_template_id=str(template["templateId"]),
    )
    room_id = str(team.get("linkedChatRoomId") or "").strip()
    if room_id:
        room = chat_room_service.update_chat_room(
            room_id,
            mode=str(template["chatRoom"]["mode"]),
            purpose=str(template["chatRoom"]["purpose"]),
            config={
                **dict((team.get("linkedChatRoom") or {}) if isinstance(team.get("linkedChatRoom"), dict) else {}),
                "source": "team_template",
                "teamId": team["teamId"],
                "teamTemplateId": template["templateId"],
                **dict(template.get("chatRoom", {}).get("config") or {}),
            },
        )
        team = team_service.get_team(team["teamId"])
        team["linkedChatRoom"] = {
            **dict(team.get("linkedChatRoom") or {}),
            "mode": room.get("mode"),
            "purpose": room.get("purpose"),
        }

    canvas = _template_canvas(template, team["teamId"], created_agents, members)
    team_service.save_team_canvas(team["teamId"], canvas)
    team = team_service.get_team(team["teamId"])
    _record_template_event("team_template.instantiated", template, team, created_agents)
    return {
        "schemaVersion": 1,
        "template": _template_to_summary(template),
        "team": team,
        "createdAgents": created_agents,
        "linkedChatRoom": team.get("linkedChatRoom"),
        "updatedAt": utc_now_iso(),
    }


def normalize_team_template_instances(template_id: str = "") -> dict[str, Any]:
    """Repair active template-created Teams so compact UI fields stay compact."""

    normalized_template_id = str(template_id or "").strip()
    templates = [
        template
        for template in _all_templates()
        if not normalized_template_id or str(template.get("templateId") or "").strip() == normalized_template_id
    ]
    if normalized_template_id and not templates:
        raise TeamTemplateError(f"Team template not found: {template_id}")
    _sync_project_roots()
    repaired_team_ids: list[str] = []
    repaired_room_ids: list[str] = []
    for template in templates:
        role_by_member_id = {
            f"{template.get('memberIdPrefix') or 'template-member'}-{index}": role
            for index, role in enumerate(template.get("roles") or [], start=1)
            if isinstance(role, dict)
        }
        for team in list(team_service.list_teams(include_archived=True).get("teams") or []):
            if not _team_matches_template(team, template):
                continue
            team_id = str(team.get("teamId") or "").strip()
            members = _normalized_template_members(team.get("members"), role_by_member_id)
            if members != team.get("members"):
                updated = team_service.update_team(team_id, members=members)
                repaired_team_ids.append(str(updated.get("teamId") or team_id))
                team = updated
            canvas = team_service.get_team_canvas(team_id)
            if _repair_template_canvas(canvas, role_by_member_id):
                team_service.save_team_canvas(team_id, canvas)
                if team_id not in repaired_team_ids:
                    repaired_team_ids.append(team_id)
            room_id = str(team.get("linkedChatRoomId") or "").strip()
            room = chat_room_service.get_chat_room_detail(room_id) if room_id else None
            if room and _repair_template_room_participants(room, role_by_member_id):
                participant_session_ids = [
                    str(item.get("sessionId") or item.get("directSessionId") or "").strip()
                    for item in list(room.get("participants") or [])
                    if isinstance(item, dict) and str(item.get("sessionId") or item.get("directSessionId") or "").strip()
                ]
                participant_contexts = {
                    str(item.get("agentId") or "").strip(): {
                        key: item.get(key)
                        for key in ("teamId", "teamName", "teamPurpose", "teamRole", "teamMemberPurpose", "teamResponsibilities")
                        if item.get(key) not in (None, "")
                    }
                    for item in list(room.get("participants") or [])
                    if isinstance(item, dict) and str(item.get("agentId") or "").strip()
                }
                chat_room_service.update_chat_room(
                    room_id,
                    participant_session_ids=participant_session_ids,
                    participant_contexts_by_agent_id=participant_contexts,
                    allow_empty_participants=True,
                    mode=str(room.get("mode") or "round_robin"),
                    purpose=str(room.get("purpose") or "discussion"),
                    config=dict(room.get("config") or {}),
                )
                repaired_room_ids.append(room_id)
    return {
        "schemaVersion": 1,
        "templateId": normalized_template_id,
        "repairedTeamIds": sorted(set(repaired_team_ids)),
        "repairedRoomIds": sorted(set(repaired_room_ids)),
        "updatedAt": utc_now_iso(),
    }


def _resolve_template(template_id: str) -> dict[str, Any]:
    normalized = str(template_id or "").strip()
    for template in _all_templates():
        if normalized == template["templateId"]:
            return template
    raise TeamTemplateError(f"Team template not found: {template_id}")


def _team_matches_template(team: dict[str, Any], template: dict[str, Any]) -> bool:
    prefix = str(template.get("memberIdPrefix") or "").strip()
    if not prefix:
        return False
    return any(
        str(member.get("memberId") or "").strip().startswith(f"{prefix}-")
        for member in list(team.get("members") or [])
        if isinstance(member, dict)
    )


def _normalized_template_members(members: Any, role_by_member_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for member in list(members or []):
        if not isinstance(member, dict):
            continue
        next_member = dict(member)
        role = role_by_member_id.get(str(next_member.get("memberId") or "").strip())
        if role:
            next_member["role"] = str(role.get("role") or next_member.get("role") or "").strip()
            next_member["purpose"] = str(role.get("purpose") or next_member.get("purpose") or "").strip()
            responsibilities = list(role.get("responsibilities") or [])
            if responsibilities:
                next_member["responsibilities"] = responsibilities
        normalized.append(next_member)
    return normalized


def _repair_template_canvas(canvas: dict[str, Any], role_by_member_id: dict[str, dict[str, Any]]) -> bool:
    changed = False
    roles = list(role_by_member_id.values())
    for index, node in enumerate(list(canvas.get("nodes") or [])):
        if not isinstance(node, dict) or index >= len(roles):
            continue
        role = roles[index]
        next_role = str(role.get("role") or "").strip()
        next_purpose = str(role.get("purpose") or "").strip()
        if node.get("label") != next_role:
            node["label"] = next_role
            changed = True
        if node.get("role") != next_role:
            node["role"] = next_role
            changed = True
        if node.get("purpose") != next_purpose:
            node["purpose"] = next_purpose
            changed = True
    return changed


def _repair_template_room_participants(room: dict[str, Any], role_by_member_id: dict[str, dict[str, Any]]) -> bool:
    changed = False
    roles = list(role_by_member_id.values())
    for index, participant in enumerate(list(room.get("participants") or [])):
        if not isinstance(participant, dict) or index >= len(roles):
            continue
        role = roles[index]
        next_role = str(role.get("role") or "").strip()
        next_purpose = str(role.get("purpose") or "").strip()
        next_responsibilities = list(role.get("responsibilities") or [])
        if participant.get("teamRole") != next_role:
            participant["teamRole"] = next_role
            changed = True
        if participant.get("teamMemberPurpose") != next_purpose:
            participant["teamMemberPurpose"] = next_purpose
            changed = True
        if participant.get("teamResponsibilities") != next_responsibilities:
            participant["teamResponsibilities"] = next_responsibilities
            changed = True
    return changed


def _all_templates() -> list[dict[str, Any]]:
    return [
        _dev_team_template(),
    ]


def _template_to_summary(template: dict[str, Any]) -> dict[str, Any]:
    return {
        "templateId": template["templateId"],
        "name": template["name"],
        "description": template["description"],
        "purpose": template["purpose"],
        "defaultTeamName": template["defaultTeamName"],
        "roleCount": len(template.get("roles") or []),
        "chatRoom": dict(template.get("chatRoom") or {}),
        "safetyLevel": template.get("safetyLevel", ""),
    }


def _role_tool_policy(role: dict[str, Any]) -> dict[str, Any]:
    policy = dict(role.get("toolPolicy") or {})
    allowed_tools = _dedupe_tool_names([*TEAM_TEMPLATE_REQUIRED_ALLOWED_TOOLS, *list(policy.get("allowedTools") or [])])
    return {
        "allowedTools": allowed_tools,
        "preferredTools": _dedupe_tool_names(policy.get("preferredTools") or []),
        "writeScopes": list(policy.get("writeScopes") or []),
    }


def _dedupe_tool_names(values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in list(values or []):
        name = str(value or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        result.append(name)
    return result


def _dev_team_template() -> dict[str, Any]:
    # 角色定义从角色文件层读取（经 team_format.validate_role_definition 门禁，
    # 畸形文件 fail-closed）；workspace/agents/agents.json 仍是运行时模型与
    # 提示词权威，instantiate 只做单向物化。
    return {
        "templateId": DEV_TEAM_TEMPLATE_ID,
        "name": "开发团队",
        "defaultTeamName": "开发团队",
        "description": "四角色软件开发团队模板：规划师把需求拆成任务并派发，两名开发工程师在各自 worktree 实现并写测试，评审员独立审查 diff 并给出结论。",
        "purpose": "按规划、开发、评审的流水线组织开发分工：规划师负责需求分析与任务派发，开发工程师负责编码实现与测试，评审员负责独立审查与质量把关；群聊按计划分派模式推进，规划师完成规划后用 @成员角色名 指派下一轮负责人，未指派时由规划师继续规划。",
        "safetyLevel": "dev_collaboration",
        "memberIdPrefix": "dev-team",
        "agentMetadata": {"devTeamTemplate": True},
        "chatRoom": {
            "mode": "planned",
            "purpose": "meeting",
            "config": {"devTeamTemplate": True, "managerTeamRole": "规划师"},
        },
        "canvas": {
            "nodePrefix": "dev-team-node",
            "positions": [(400, 60), (160, 260), (640, 260), (400, 460)],
            "edges": [
                {"id": "planner-dev-a", "source": "dev-team-node-1", "target": "dev-team-node-2", "type": "delegates_to", "label": "任务派发"},
                {"id": "planner-dev-b", "source": "dev-team-node-1", "target": "dev-team-node-3", "type": "delegates_to", "label": "任务派发"},
                {"id": "dev-a-reviewer", "source": "dev-team-node-2", "target": "dev-team-node-4", "type": "reports_to", "label": "提审"},
                {"id": "dev-b-reviewer", "source": "dev-team-node-3", "target": "dev-team-node-4", "type": "reports_to", "label": "提审"},
            ],
        },
        "roles": role_definition_service.load_role_definitions(DEV_TEAM_ROLE_KEYS, project_root=PROJECT_ROOT),
    }


def _template_canvas(
    template: dict[str, Any],
    team_id: str,
    agents: list[dict[str, Any]],
    members: list[dict[str, Any]],
) -> dict[str, Any]:
    now = utc_now_iso()
    canvas_spec = dict(template.get("canvas") or {})
    node_prefix = str(canvas_spec.get("nodePrefix") or "template")
    positions = list(canvas_spec.get("positions") or [])
    nodes: list[dict[str, Any]] = []
    for index, (agent, member) in enumerate(zip(agents, members, strict=False)):
        x, y = positions[index] if index < len(positions) else (120 + index * 220, 210)
        nodes.append(
            {
                "id": f"{node_prefix}-{index + 1}",
                "label": str(member.get("role") or agent.get("displayName") or ""),
                "type": "agent",
                "status": "bound",
                "x": x,
                "y": y,
                "agentId": str(agent.get("agentId") or ""),
                "agentCode": str(agent.get("agentCode") or ""),
                "agentName": str(agent.get("displayName") or ""),
                "role": str(member.get("role") or ""),
                "purpose": str(member.get("purpose") or ""),
                "responsibilities": list(member.get("responsibilities") or []),
            }
        )
    return {
        "schemaVersion": 1,
        "canvasKind": "team_organization_canvas",
        "teamId": team_id,
        "updatedAt": now,
        "viewport": {"x": 0, "y": 0, "zoom": 1},
        "nodes": nodes,
        "edges": list(canvas_spec.get("edges") or []),
    }


def _sync_project_roots() -> None:
    for service in (agent_directory_service, session_service, team_service, chat_room_service):
        if getattr(service, "PROJECT_ROOT", None) != PROJECT_ROOT:
            service.PROJECT_ROOT = PROJECT_ROOT


def _record_template_event(
    event_name: str,
    template: dict[str, Any],
    team: dict[str, Any],
    agents: list[dict[str, Any]],
) -> None:
    try:
        record_runtime_scene_event(
            "team_template",
            "template",
            event_name,
            fields={
                "templateId": template.get("templateId"),
                "teamId": team.get("teamId"),
                "agentCount": len(agents),
                "linkedChatRoomId": team.get("linkedChatRoomId"),
                "mode": (team.get("linkedChatRoom") or {}).get("mode") if isinstance(team.get("linkedChatRoom"), dict) else "",
                "purpose": (team.get("linkedChatRoom") or {}).get("purpose") if isinstance(team.get("linkedChatRoom"), dict) else "",
            },
            outcome="created",
            lifecycle=True,
        )
    except Exception:
        pass
