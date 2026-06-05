"""Reusable Team templates for demo and onboarding flows."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.chat.chat_task_types import trim_lines

from . import agent_directory_service, chat_room_service, session_service, team_service
from .runtime_scene_service import record_runtime_scene_event


PROJECT_ROOT = Path(__file__).resolve().parents[3]
MEDICAL_CONSULTATION_TEMPLATE_ID = "medical-consultation-demo"
HELETECH_MATERNAL_DIGITAL_HEALTH_TEMPLATE_ID = "heletech-maternal-digital-health-demo"


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
            llm_bindings=session_service.llm_bindings_for_profile_id("primary"),
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
        _medical_consultation_template(),
        _heletech_maternal_digital_health_template(),
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
    return {
        "allowedTools": list(policy.get("allowedTools") or []),
        "preferredTools": list(policy.get("preferredTools") or []),
        "writeScopes": list(policy.get("writeScopes") or []),
    }


def _medical_consultation_template() -> dict[str, Any]:
    return {
        "templateId": MEDICAL_CONSULTATION_TEMPLATE_ID,
        "name": "医疗问诊 Demo 团队",
        "defaultTeamName": "医疗问诊 Demo 团队",
        "description": "演示用户与问诊团队在同一个群聊中完成症状采集、风险分诊、专科建议和安全合并输出。",
        "purpose": "用于演示协同问诊、风险分诊、症状采集和就医建议，不替代医生诊断治疗。",
        "safetyLevel": "triage_only",
        "memberIdPrefix": "medical-demo",
        "agentMetadata": {"medicalTriageDemo": True},
        "chatRoom": {
            "mode": "medical_consultation_panel",
            "purpose": "medical_triage",
            "config": {"medicalTriageDemo": True},
        },
        "canvas": {
            "nodePrefix": "medical",
            "positions": [(120, 210), (400, 80), (400, 330), (680, 210)],
            "edges": [
                {"id": "host-risk", "source": "medical-1", "target": "medical-2", "type": "communication", "label": "红旗风险优先"},
                {"id": "host-intake", "source": "medical-1", "target": "medical-3", "type": "communication", "label": "最少必要追问"},
                {"id": "host-specialist", "source": "medical-1", "target": "medical-4", "type": "communication", "label": "专科方向"},
                {"id": "risk-host", "source": "medical-2", "target": "medical-1", "type": "supports", "label": "安全审查"},
                {"id": "intake-host", "source": "medical-3", "target": "medical-1", "type": "supports", "label": "信息回填"},
                {"id": "specialist-host", "source": "medical-4", "target": "medical-1", "type": "supports", "label": "结论合并"},
            ],
        },
        "roles": [
            _medical_role(
                "medical_host_synthesizer",
                "问诊主持 / 结果整理",
                "控制问诊节奏，合并团队意见并输出最终问诊总结。",
                "问诊主持 Agent",
                "稳健、克制、面向用户，先澄清再总结。",
            ),
            _medical_role(
                "medical_risk_safety",
                "风险分诊 / 安全审查",
                "优先识别急症红旗信号，审查越权诊断、处方、剂量和危险遗漏。",
                "风险分诊 Agent",
                "风险优先、宁可保守，不给确定诊断或治疗承诺。",
            ),
            _medical_role(
                "medical_intake",
                "症状采集员",
                "补齐年龄、性别、主诉、持续时间、伴随症状、既往史、用药和过敏史。",
                "症状采集 Agent",
                "问题少而准，一次只追问最少必要信息。",
            ),
            _medical_role(
                "medical_specialist_advisor",
                "全科/专科顾问",
                "给出可能方向、建议科室和就医准备，不做确定诊断。",
                "全科顾问 Agent",
                "解释清楚但不武断，强调就医科室和观察重点。",
            ),
        ],
    }


def _heletech_maternal_digital_health_template() -> dict[str, Any]:
    return {
        "templateId": HELETECH_MATERNAL_DIGITAL_HEALTH_TEMPLATE_ID,
        "name": "和乐妇幼数字健康 Demo 团队",
        "defaultTeamName": "和乐妇幼数字健康 Demo 团队",
        "description": "面向杭州和乐科技展示妇幼全程产品线、智慧专科系统、区域妇幼大数据和远程医疗协同方案。",
        "purpose": "用于演示妇幼数字健康方案协作，围绕专科电子病历、母子健康手册、云上妇幼、智慧科研和交付合规形成可展示方案。",
        "safetyLevel": "demo_advisory",
        "memberIdPrefix": "heletech-demo",
        "agentMetadata": {"heletechMaternalDigitalHealthDemo": True},
        "chatRoom": {
            "mode": "round_robin",
            "purpose": "meeting",
            "config": {"heletechMaternalDigitalHealthDemo": True},
        },
        "canvas": {
            "nodePrefix": "heletech",
            "positions": [(120, 230), (420, 60), (420, 210), (420, 360), (720, 230)],
            "edges": [
                {"id": "host-business", "source": "heletech-1", "target": "heletech-2", "type": "communication", "label": "妇幼业务场景"},
                {"id": "host-emr", "source": "heletech-1", "target": "heletech-3", "type": "communication", "label": "专科系统集成"},
                {"id": "host-data", "source": "heletech-1", "target": "heletech-4", "type": "communication", "label": "科研与区域平台"},
                {"id": "host-safety", "source": "heletech-1", "target": "heletech-5", "type": "communication", "label": "合规交付审查"},
                {"id": "business-host", "source": "heletech-2", "target": "heletech-1", "type": "supports", "label": "流程建议"},
                {"id": "emr-host", "source": "heletech-3", "target": "heletech-1", "type": "supports", "label": "集成说明"},
                {"id": "data-host", "source": "heletech-4", "target": "heletech-1", "type": "supports", "label": "数据价值"},
                {"id": "safety-host", "source": "heletech-5", "target": "heletech-1", "type": "supports", "label": "风险收口"},
            ],
        },
        "roles": [
            _heletech_role(
                "heletech_solution_host",
                "方案主持",
                "方案编排",
                "拆解客户问题，组织各岗位围绕妇幼数字健康场景给出可合并的展示方案。",
                "方案主持 Agent",
                "稳健、清晰、面向企业展示，先定义场景再合并结论。",
                ["方案编排", "妇幼数字健康", "企业演示"],
            ),
            _heletech_role(
                "heletech_maternal_child_business",
                "妇幼业务顾问",
                "妇幼流程",
                "负责孕前、孕产、儿童保健、免疫接种、高危孕产妇和新生儿救治等业务流程建议。",
                "妇幼业务顾问 Agent",
                "熟悉妇幼业务路径，能把临床管理流程转成演示步骤。",
                ["妇幼保健", "高危孕产妇管理", "母子健康手册"],
            ),
            _heletech_role(
                "heletech_emr_his_integration",
                "病历集成顾问",
                "病历集成",
                "说明专科电子病历、HIS 嵌入、数据同步、重点指标展示和标准文书导出。",
                "病历集成顾问 Agent",
                "技术表达克制准确，强调系统衔接和医生使用效率。",
                ["专科电子病历", "HIS 集成", "标准文书"],
            ),
            _heletech_role(
                "heletech_research_data_platform",
                "数据科研顾问",
                "科研数据",
                "负责妇幼大数据中心、智慧科研、远程会诊、远程培训和医联体协同价值表达。",
                "数据科研顾问 Agent",
                "善于把数据平台价值落到科研效率、区域协同和资源下沉。",
                ["智慧科研", "妇幼大数据", "远程医疗"],
            ),
            _heletech_role(
                "heletech_delivery_compliance",
                "合规交付顾问",
                "合规交付",
                "审查医疗边界、隐私合规、上线交付风险和展示话术，确保方案不过度承诺。",
                "合规交付顾问 Agent",
                "风险优先、表达保守，负责把演示方案收束到可交付边界。",
                ["医疗合规", "隐私保护", "交付风险"],
            ),
        ],
    }


def _medical_role(role_key: str, role: str, purpose: str, agent_name: str, style: str) -> dict[str, Any]:
    return {
        "roleKey": role_key,
        "role": role,
        "purpose": purpose,
        "agentName": agent_name,
        "personaProfile": {
            "personality": style,
            "communicationStyle": "简洁、同理、避免恐吓，不使用确定性诊断语气。",
            "background": "医疗问诊 Demo 团队成员，仅用于分诊与就医准备演示。",
            "identityNotes": "不能替代医生面诊、检查、诊断或治疗。",
            "expertise": ["医疗分诊", "问诊协作", "用户沟通"],
        },
        "taskProfile": {
            "mission": purpose,
            "responsibilities": purpose,
            "preferredTasks": "参与 medical_triage 群聊，按岗位给出简短、可合并的问诊意见。",
            "avoidTasks": "不得给出确定诊断、处方、剂量、停药/换药指令或保证性结论。",
            "successCriteria": "帮助用户获得风险等级、可能方向、建议科室、补充信息、立即就医条件和免责声明。",
            "constraints": "只读演示 Agent；不执行文件、Git、部署、进化或工具注册操作。",
            "deliverables": "一段可被主持合并的岗位意见。",
        },
    }


def _heletech_role(
    role_key: str,
    role: str,
    purpose: str,
    responsibilities: str,
    agent_name: str,
    style: str,
    expertise: list[str],
) -> dict[str, Any]:
    return {
        "roleKey": role_key,
        "role": role,
        "purpose": purpose,
        "responsibilities": [responsibilities],
        "agentName": agent_name,
        "personaProfile": {
            "personality": style,
            "communicationStyle": "简洁、专业、面向医院与企业展示，不夸大产品能力。",
            "background": "和乐妇幼数字健康 Demo 团队成员，围绕智慧专科系统与数字健康服务做方案协作演示。",
            "identityNotes": "提供产品方案与演示建议，不替代真实医疗诊断、真实项目交付承诺或法律合规意见。",
            "expertise": expertise,
        },
        "taskProfile": {
            "mission": responsibilities,
            "responsibilities": responsibilities,
            "preferredTasks": "参与 meeting 群聊，按岗位给出简短、可合并的妇幼数字健康方案意见。",
            "avoidTasks": "不得输出确定诊断、处方、剂量、真实患者隐私处理、真实项目报价或无法验证的公司承诺。",
            "successCriteria": "帮助用户获得场景拆解、产品能力映射、数据与科研价值、交付风险和最终展示话术。",
            "constraints": "只读演示 Agent；不执行文件、Git、部署、数据库写入、真实接口调用或权限配置操作。",
            "deliverables": "一段可被方案主持合并的岗位意见。",
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
