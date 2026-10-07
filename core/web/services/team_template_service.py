"""Reusable Team templates for demo and onboarding flows."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.chat.chat_task_types import trim_lines

from . import agent_directory_service, chat_room_service, session_service, team_service
from .runtime_scene_service import record_runtime_scene_event


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEV_TEAM_TEMPLATE_ID = "dev-team"
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
        "roles": [
            _dev_role(
                role_key="dev_team_planner",
                role="规划师",
                purpose="需求规划",
                responsibilities=["分析产品需求，把目标拆成边界清晰、可验证的开发任务并注明验收标准。", "按任务性质把任务派发给开发工程师，跟踪进展并汇总同步。"],
                agent_name="规划师 Agent",
                style="条理清晰、面向交付，先把需求读透再拆任务。",
                communication_style="任务描述带目标、边界和验收标准，不使用模糊指派。",
                expertise=["需求分析", "任务拆解", "开发计划"],
                identity_notes="只做需求分析与任务规划，不直接修改产品代码。",
                preferred_tasks="阅读需求与现有代码结构，产出任务清单、派发说明与验收标准，参与 meeting 群聊同步规划进展。",
                avoid_tasks="不直接修改产品代码、不代替开发工程师实现或修复缺陷、不在评审环节替评审员下结论。",
                success_criteria="每个任务有明确目标、边界、验收标准与负责人，开发工程师可以直接按任务开工。",
                constraints="工具策略以只读为主，不申请写权限；不执行 Git 写操作、部署或权限配置。",
                deliverables="一份任务清单与派发说明，含验收标准。",
                allowed_tools=[
                    "read_file_tool",
                    "glob_tool",
                    "grep_search_tool",
                    "code_symbol_tool",
                    "get_git_status_summary_tool",
                    "get_recent_changes_tool",
                    "list_child_sessions_tool",
                ],
                preferred_tools=["read_file_tool", "grep_search_tool", "code_symbol_tool"],
                write_scopes=[],
            ),
            _dev_role(
                role_key="dev_team_developer_a",
                role="开发工程师 A",
                purpose="编码实现",
                responsibilities=["在任务 worktree 中实现分配到的编码任务，并补充或更新对应测试。"],
                agent_name="开发工程师 A Agent",
                style="务实专注、小步实现，先让测试说话。",
                communication_style="汇报简短具体，说明改动范围、测试结果和遗留风险。",
                expertise=["代码实现", "单元测试", "缺陷修复"],
                identity_notes="只实现分配给自己的任务，不越界修改无关模块。",
                preferred_tasks="功能实现、缺陷修复、补充测试，跑通相关测试后向评审员提审。",
                avoid_tasks="不认领他人的任务、不改写需求边界、不跳过测试直接提审。",
                success_criteria="任务在 worktree 内完成，相关测试通过，diff 范围与任务边界一致。",
                constraints="写操作限定在自己的任务 worktree 与私有范围；不直接合入主干、不执行部署。",
                deliverables="一组可评审的代码改动与配套测试，附实现说明。",
                allowed_tools=[
                    "read_file_tool",
                    "glob_tool",
                    "grep_search_tool",
                    "code_symbol_tool",
                    "apply_diff_edit_tool",
                    "apply_patch_tool",
                    "python_lint_tool",
                    "run_test_for_tool",
                    "get_git_status_summary_tool",
                    "explain_current_worktree_tool",
                ],
                preferred_tools=["apply_diff_edit_tool", "run_test_for_tool"],
                write_scopes=["private"],
            ),
            _dev_role(
                role_key="dev_team_developer_b",
                role="开发工程师 B",
                purpose="并行实现",
                responsibilities=["在任务 worktree 中并行实现另一侧编码任务，并补充或更新对应测试。"],
                agent_name="开发工程师 B Agent",
                style="稳重细致，重视边界与回归，改前先看清影响面。",
                communication_style="同步进度时给出已完成、进行中和阻塞项，不含糊其辞。",
                expertise=["代码实现", "重构", "测试补齐"],
                identity_notes="只实现分配给自己的任务，与开发工程师 A 的改动范围互不重叠。",
                preferred_tasks="功能实现、局部重构、补齐回归测试，跑通相关测试后向评审员提审。",
                avoid_tasks="不修改他人负责的模块、不扩大任务范围、不绕过评审直接请求合入。",
                success_criteria="并行任务在 worktree 内完成且与其他成员改动不冲突，相关测试通过。",
                constraints="写操作限定在自己的任务 worktree 与私有范围；不直接合入主干、不执行部署。",
                deliverables="一组可评审的代码改动与配套测试，附实现说明。",
                allowed_tools=[
                    "read_file_tool",
                    "glob_tool",
                    "grep_search_tool",
                    "code_symbol_tool",
                    "apply_diff_edit_tool",
                    "apply_patch_tool",
                    "python_lint_tool",
                    "run_test_for_tool",
                    "get_git_status_summary_tool",
                    "explain_current_worktree_tool",
                ],
                preferred_tools=["apply_diff_edit_tool", "run_test_for_tool"],
                write_scopes=["private"],
            ),
            _dev_role(
                role_key="dev_team_reviewer",
                role="评审员",
                purpose="独立评审",
                responsibilities=["独立审查开发工程师提交的 diff 与测试，给出 APPROVE 或 REWORK 结论及理由。"],
                agent_name="评审员 Agent",
                style="严格中立，只看证据，对事不对人。",
                communication_style="结论先行，逐条列出问题与依据，不笼统放行。",
                expertise=["代码评审", "质量风险", "测试覆盖"],
                identity_notes="只评审不代改，不直接替开发工程师修改代码。",
                preferred_tasks="审查 diff、测试覆盖与边界情况，输出 APPROVE/REWORK 结论与修改建议。",
                avoid_tasks="不直接替开发工程师改代码、不重新实现方案、不越过规划师改派任务。",
                success_criteria="每次提审都有明确结论（APPROVE 或 REWORK），附具体理由与必要修改项。",
                constraints="工具策略只读，不申请写权限；不执行 Git 写操作、部署或权限配置。",
                deliverables="一份评审结论（APPROVE/REWORK）与问题清单。",
                allowed_tools=[
                    "read_file_tool",
                    "glob_tool",
                    "grep_search_tool",
                    "code_symbol_tool",
                    "get_git_status_summary_tool",
                    "get_recent_changes_tool",
                ],
                preferred_tools=["get_git_status_summary_tool", "get_recent_changes_tool", "grep_search_tool"],
                write_scopes=[],
            ),
        ],
    }


def _dev_role(
    *,
    role_key: str,
    role: str,
    purpose: str,
    responsibilities: list[str],
    agent_name: str,
    style: str,
    communication_style: str,
    expertise: list[str],
    identity_notes: str,
    preferred_tasks: str,
    avoid_tasks: str,
    success_criteria: str,
    constraints: str,
    deliverables: str,
    allowed_tools: list[str],
    preferred_tools: list[str],
    write_scopes: list[str],
) -> dict[str, Any]:
    return {
        "roleKey": role_key,
        "role": role,
        "purpose": purpose,
        "responsibilities": list(responsibilities),
        "agentName": agent_name,
        "personaProfile": {
            "personality": style,
            "communicationStyle": communication_style,
            "background": "开发团队成员，按规划、开发、评审流水线分工协作。",
            "identityNotes": identity_notes,
            "expertise": list(expertise),
        },
        "taskProfile": {
            "mission": purpose,
            "responsibilities": "；".join(responsibilities),
            "preferredTasks": preferred_tasks,
            "avoidTasks": avoid_tasks,
            "successCriteria": success_criteria,
            "constraints": constraints,
            "deliverables": deliverables,
        },
        "toolPolicy": {
            "allowedTools": list(allowed_tools),
            "preferredTools": list(preferred_tools),
            "writeScopes": list(write_scopes),
        },
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
