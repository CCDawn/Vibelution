"""Read-only Agent configuration workspace aggregation."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from core.orchestration.context_engine import list_agent_runs_for_agent

from . import chat_room_service, config_service
from .agent_directory_service import agent_persona_profile_has_content
from .agent_directory_service import agent_task_profile_has_content
from .agent_directory_service import AGENT_LLM_BINDING_SLOTS
from .agent_directory_service import agent_dialogue_model_id
from .agent_directory_service import list_agents
from .agent_directory_service import list_agent_policy_options
from .agent_directory_service import normalize_agent_llm_bindings
from .agent_mode_binding_service import get_mode_bindings_payload, mode_binding_path
from .prompt_template_service import list_prompt_templates, prompt_template_path
from .runtime_scene_service import record_runtime_scene_event


SCHEMA_VERSION = 1
AGENT_LLM_SLOT_DEFINITIONS = (
    {
        "slot": "dialogue",
        "label": "对话模型",
        "description": "处理用户对话、工具规划和主回复生成。",
        "required": True,
        "requiresImageInput": False,
    },
    {
        "slot": "mentalModel",
        "label": "心智模型",
        "description": "用于心智状态、长期偏好和自我解释相关推理。",
        "required": False,
        "requiresImageInput": False,
    },
    {
        "slot": "summary",
        "label": "摘要模型",
        "description": "用于会话压缩、运行摘要和交接材料整理。",
        "required": False,
        "requiresImageInput": False,
    },
    {
        "slot": "subagentPlanning",
        "label": "子 Agent 规划",
        "description": "用于拆解委派任务、确定子 Agent 目标和边界。",
        "required": False,
        "requiresImageInput": False,
    },
    {
        "slot": "subagentExecution",
        "label": "子 Agent 执行",
        "description": "用于执行被委派的窄任务和返回结构化证据。",
        "required": False,
        "requiresImageInput": False,
    },
    {
        "slot": "vision",
        "label": "视觉理解",
        "description": "用于图片输入、截图分析和多模态理解。",
        "required": False,
        "requiresImageInput": True,
    },
)
AGENT_LLM_SLOT_REFS = {item["slot"]: item for item in AGENT_LLM_SLOT_DEFINITIONS}


def get_agent_config_workspace() -> dict[str, Any]:
    """Return a read-only workspace that explains every persistent Agent once."""

    timings: dict[str, float] = {}
    load_modes: dict[str, str] = {}
    total_started = perf_counter()
    agents = _timed_stage(timings, "list_agents", lambda: list_agents(include_archived=True))
    active_agent_options = [_agent_option(agent) for agent in agents if str(agent.get("status") or "active").strip() != "archived"]
    mode_bindings = _timed_stage(
        timings,
        "mode_bindings",
        lambda: get_mode_bindings_payload(agent_options=active_agent_options),
    )
    prompt_workspace = _timed_stage(timings, "prompt_templates", _safe_prompt_workspace)
    config_workspace = _timed_stage(timings, "model_config", _safe_config_workspace)
    chat_rooms = _timed_stage(timings, "chat_rooms", _safe_chat_rooms)
    teams = _timed_stage(timings, "teams", _safe_teams)
    policy_options = _timed_stage(timings, "policy_options", _safe_policy_options)

    agent_refs = {str(agent.get("agentId") or ""): agent for agent in agents if str(agent.get("agentId") or "")}
    active_agent_ids = {
        agent_id
        for agent_id, agent in agent_refs.items()
        if str(agent.get("status") or "active").strip() != "archived"
    }
    prompt_refs = {
        str(item.get("promptTemplateId") or item.get("templateId") or ""): item
        for item in prompt_workspace.get("templates") or []
        if str(item.get("promptTemplateId") or item.get("templateId") or "")
    }
    model_options = list(config_workspace.get("modelOptions") or [])
    agent_model_choices = _agent_model_choices(model_options)
    model_refs = {
        str(item.get("modelId") or ""): item
        for item in agent_model_choices
        if str(item.get("modelId") or "")
    }

    references = _timed_stage(
        timings,
        "derive_references",
        lambda: _derive_references(
            agents=agents,
            mode_bindings=mode_bindings,
            chat_rooms=chat_rooms,
            teams=teams,
            active_agent_ids=active_agent_ids,
        ),
    )
    health = _timed_stage(
        timings,
        "derive_health",
        lambda: _derive_health(
            agents=agents,
            prompt_refs=prompt_refs,
            model_refs=model_refs,
            mode_bindings=mode_bindings,
            chat_rooms=chat_rooms,
            teams=teams,
            active_agent_ids=active_agent_ids,
        ),
    )
    issues_by_agent = _issues_by_agent(health["issues"])
    runtime_status_by_agent = _timed_stage(timings, "runtime_statuses", lambda: _derive_runtime_statuses(agents))
    enriched_agents = [
        {
            **agent,
            "dialogueModel": model_refs.get(agent_dialogue_model_id(agent)),
            "llmBindingModels": _llm_binding_model_refs(agent.get("llmBindings"), model_refs),
            "promptTemplate": prompt_refs.get(str(agent.get("promptTemplateId") or "")),
            "references": references.get(str(agent.get("agentId") or ""), []),
            "agentBoundary": _derive_agent_boundary(
                agent,
                references=references.get(str(agent.get("agentId") or ""), []),
            ),
            "health": issues_by_agent.get(str(agent.get("agentId") or ""), []),
            "runtimeStatus": runtime_status_by_agent.get(str(agent.get("agentId") or ""), _default_runtime_status(agent)),
        }
        for agent in agents
    ]
    groups = _timed_stage(timings, "derive_groups", lambda: _derive_groups(enriched_agents))
    summary = _timed_stage(timings, "summary", lambda: _summary(enriched_agents, groups, health["issues"], chat_rooms, teams, mode_bindings))
    timings["total"] = round((perf_counter() - total_started) * 1000, 1)
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": _now(),
        "storage": {
            "agentRegistryPath": "workspace/agents/agents.json",
            "modeBindingPath": _relative_path(mode_binding_path()),
            "promptTemplatePath": _relative_path(prompt_template_path()),
        },
        "summary": summary,
        "groups": groups,
        "agents": enriched_agents,
        "modeBindings": mode_bindings.get("modes") or {},
        "promptTemplates": prompt_workspace.get("templates") or [],
        "agentLlmSlots": _agent_llm_slots(),
        "agentModelChoices": agent_model_choices,
        "modelOptions": config_workspace.get("modelOptions") or [],
        "toolPolicies": policy_options.get("toolPolicies") or [],
        "memoryPolicies": policy_options.get("memoryPolicies") or [],
        "chatRooms": _compact_chat_rooms(chat_rooms),
        "teams": _compact_teams(teams),
        "references": references,
        "health": health,
        "repairWarnings": {
            "modeBindings": list(mode_bindings.get("repairWarnings") or []),
            "promptTemplates": list(prompt_workspace.get("repairWarnings") or []),
        },
    }
    load_modes["chatRooms"] = "compact"
    load_modes["teams"] = "compact"
    _record_workspace_loaded(summary, timings=timings, load_modes=load_modes)
    return payload


def _derive_references(
    *,
    agents: list[dict[str, Any]],
    mode_bindings: dict[str, Any],
    chat_rooms: list[dict[str, Any]],
    teams: list[dict[str, Any]],
    active_agent_ids: set[str],
) -> dict[str, list[dict[str, Any]]]:
    references: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for agent in agents:
        agent_id = str(agent.get("agentId") or "").strip()
        direct_session_id = str(agent.get("directSessionId") or "").strip()
        if agent_id and direct_session_id:
            references[agent_id].append(
                _reference(
                    "direct_session",
                    source_id=direct_session_id,
                    source_label=str(agent.get("displayName") or direct_session_id),
                    field="directSessionId",
                    route="/chat",
                )
            )

    for mode, binding in dict(mode_bindings.get("modes") or {}).items():
        if not isinstance(binding, dict):
            continue
        mode_label = str(mode or "").strip()
        default_agent_id = str(binding.get("defaultAgentId") or "").strip()
        if default_agent_id:
            references[default_agent_id].append(
                _reference("mode_default", source_id=mode_label, source_label=f"{mode_label} default", mode=mode_label)
            )
        for agent_id in _string_list(binding.get("availableAgentIds")):
            references[agent_id].append(
                _reference("mode_available", source_id=mode_label, source_label=f"{mode_label} available", mode=mode_label)
            )
        for agent_id in _string_list(binding.get("pool")):
            references[agent_id].append(
                _reference("mode_pool", source_id=mode_label, source_label=f"{mode_label} pool", mode=mode_label)
            )
        for key, agent_id in dict(binding.get("slots") or {}).items():
            normalized_agent_id = str(agent_id or "").strip()
            if normalized_agent_id:
                references[normalized_agent_id].append(
                    _reference(
                        "mode_slot",
                        source_id=mode_label,
                        source_label=f"{mode_label}.{key}",
                        mode=mode_label,
                        field=str(key),
                    )
                )
        for key, agent_id in dict(binding.get("flowBindings") or {}).items():
            normalized_agent_id = str(agent_id or "").strip()
            if normalized_agent_id:
                references[normalized_agent_id].append(
                    _reference(
                        "flow_binding",
                        source_id=mode_label,
                        source_label=f"{mode_label}.{key}",
                        mode=mode_label,
                        field=str(key),
                    )
                )

    for room in chat_rooms:
        room_id = str(room.get("roomId") or "").strip()
        room_title = str(room.get("title") or room_id).strip()
        for participant in list(room.get("participants") or []):
            if not isinstance(participant, dict):
                continue
            agent_id = str(participant.get("agentId") or "").strip()
            if not agent_id:
                continue
            references[agent_id].append(
                _reference(
                    "chat_room",
                    source_id=room_id,
                    source_label=room_title,
                    field=str(participant.get("participantId") or ""),
                    route=f"/chat?room={room_id}" if room_id else "/chat",
                    status="active" if agent_id in active_agent_ids else "stale",
                )
            )

    for team in teams:
        team_id = str(team.get("teamId") or "").strip()
        team_name = str(team.get("name") or team_id).strip()
        team_status = str(team.get("status") or "active").strip()
        for member in list(team.get("members") or []):
            if not isinstance(member, dict):
                continue
            agent_id = str(member.get("agentId") or "").strip()
            if not agent_id:
                continue
            references[agent_id].append(
                _reference(
                    "team",
                    source_id=team_id,
                    source_label=team_name,
                    field=str(member.get("role") or member.get("memberId") or ""),
                    route="/teams",
                    status="active" if team_status != "archived" and agent_id in active_agent_ids else "stale",
                )
            )
    return {agent_id: _dedupe_references(items) for agent_id, items in references.items()}


def _derive_health(
    *,
    agents: list[dict[str, Any]],
    prompt_refs: dict[str, dict[str, Any]],
    model_refs: dict[str, dict[str, Any]],
    mode_bindings: dict[str, Any],
    chat_rooms: list[dict[str, Any]],
    teams: list[dict[str, Any]],
    active_agent_ids: set[str],
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    for agent in agents:
        agent_id = str(agent.get("agentId") or "").strip()
        status = str(agent.get("status") or "active").strip()
        if status == "archived":
            continue

        bindings = normalize_agent_llm_bindings(agent.get("llmBindings"))
        for slot in _agent_llm_slots():
            slot_key = str(slot.get("slot") or "").strip()
            binding = bindings.get(slot_key) if isinstance(bindings.get(slot_key), dict) else {}
            model_id = str((binding or {}).get("modelId") or "").strip()
            slot_label = str(slot.get("label") or slot_key).strip() or slot_key
            if not model_id:
                if bool(slot.get("required")):
                    issues.append(
                        _agent_issue(
                            agent,
                            "blocking",
                            f"missing_llm_slot_{slot_key}",
                            f"Agent 未选择{slot_label}",
                            f"这个 Agent 的 {slot_key} 槽位没有绑定模型库模型。",
                        )
                    )
                continue
            if model_id not in model_refs:
                issues.append(
                    _agent_issue(
                        agent,
                        "blocking" if bool(slot.get("required")) else "warning",
                        f"missing_llm_slot_model_ref_{slot_key}",
                        f"{slot_label}不存在",
                        f"{slot_key} 槽位引用的模型库键 {model_id} 不存在或已被删除。",
                    )
                )
                continue
            model = model_refs[model_id]
            if bool(slot.get("requiresImageInput")) and model.get("supportsImageInput") is False:
                issues.append(
                    _agent_issue(
                        agent,
                        "warning",
                        f"llm_slot_model_missing_vision_{slot_key}",
                        f"{slot_label}不支持图片输入",
                        f"{slot_key} 槽位绑定的模型 {model_id} 标记为不支持图片输入。",
                    )
                )
            if bool(model.get("requiresApiKey")) and not bool(model.get("apiKeyConfigured")):
                issues.append(
                    _agent_issue(
                        agent,
                        "warning",
                        f"missing_llm_slot_api_key_{slot_key}",
                        f"{slot_label}密钥未就绪",
                        f"{slot_key} 槽位绑定的模型库键 {model_id} 当前没有可用密钥。",
                    )
                )

        prompt_template_id = str(agent.get("promptTemplateId") or "").strip()
        if not prompt_template_id:
            issues.append(_agent_issue(agent, "warning", "missing_prompt_template_id", "Agent 未绑定提示词模板", "promptTemplateId 为空。"))
        elif prompt_template_id not in prompt_refs:
            issues.append(
                _agent_issue(
                    agent,
                    "warning",
                    "missing_prompt_template",
                    "提示词模板不存在",
                    f"promptTemplateId={prompt_template_id} 没有出现在提示词模板索引中。",
                )
            )
        else:
            prompt = prompt_refs[prompt_template_id]
            if str(prompt.get("sourcePath") or "").strip() and not bool(prompt.get("sourceExists", False)):
                issues.append(
                    _agent_issue(
                        agent,
                        "warning",
                        "missing_prompt_source",
                        "提示词源文件缺失",
                        f"{prompt_template_id} 指向的 sourcePath 不存在。",
                    )
                )

        if not str(agent.get("directSessionId") or "").strip():
            issues.append(_agent_issue(agent, "warning", "missing_direct_session", "缺少直连会话", "群聊和主动唤醒需要一个可恢复的 directSessionId。"))
        if not str(agent.get("workspacePath") or "").strip():
            issues.append(_agent_issue(agent, "blocking", "missing_workspace", "缺少独立工作区", "workspacePath 为空。"))
        territory = agent.get("workspaceTerritory") if isinstance(agent.get("workspaceTerritory"), dict) else {}
        legacy_workspace = str(territory.get("legacyWorkspacePath") or "").strip()
        if legacy_workspace:
            issues.append(
                _agent_issue(
                    agent,
                    "info",
                    "legacy_workspace_retained",
                    "保留了历史会话工作区",
                    f"旧路径 {legacy_workspace} 已保留为兼容引用；新的默认写入进入 Agent 私有领地。",
                )
            )
        if not str(agent.get("toolPolicyId") or "").strip():
            issues.append(_agent_issue(agent, "warning", "missing_tool_policy", "缺少工具权限策略", "toolPolicyId 为空。"))
        if not str(agent.get("memoryPolicyId") or "").strip():
            issues.append(_agent_issue(agent, "warning", "missing_memory_policy", "缺少记忆策略", "memoryPolicyId 为空。"))
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        boundary = _derive_agent_boundary(agent)
        onboarding_missing = _onboarding_missing_for_boundary(agent, boundary)
        if onboarding_missing:
            missing = _string_list(onboarding_missing)
            issues.append(
                _agent_issue(
                    agent,
                    "warning",
                    "agent_onboarding_incomplete",
                    "Agent 建档未完成",
                    "还需要补齐：" + "、".join(_creation_field_label(item) for item in missing) + "。",
                )
            )

        pending_inbox_count = _safe_int(agent.get("agentInboxPendingCount"))
        if pending_inbox_count > 0:
            issues.append(
                _agent_issue(
                    agent,
                    "info",
                    "pending_inbox_messages",
                    "有待处理 Agent 消息",
                    f"当前有 {pending_inbox_count} 条 inbox 消息等待消费。",
                )
            )

    for warning in list(mode_bindings.get("repairWarnings") or []):
        if not isinstance(warning, dict):
            continue
        issues.append(
            {
                "severity": "warning",
                "code": "stale_mode_binding",
                "agentId": str(warning.get("agentId") or "").strip(),
                "title": "模式绑定引用了缺失 Agent",
                "detail": f"{warning.get('mode') or '-'} / {warning.get('field') or '-'} 已在读取时修复。",
                "source": "mode_binding",
                "action": "检查 Agent Center 的模式归属并重新保存。",
            }
        )

    for room in chat_rooms:
        for participant in list(room.get("participants") or []):
            if not isinstance(participant, dict):
                continue
            agent_id = str(participant.get("agentId") or "").strip()
            if agent_id and agent_id not in active_agent_ids:
                issues.append(
                    {
                        "severity": "warning",
                        "code": "stale_chat_room_participant",
                        "agentId": agent_id,
                        "title": "群聊成员引用了不可用 Agent",
                        "detail": f"{room.get('title') or room.get('roomId') or '-'} 中的成员 agentId={agent_id} 不在活跃 Agent 列表中。",
                        "source": "chat_room",
                        "action": "在群聊管理中替换或移除该成员。",
                    }
                )

    for team in teams:
        for member in list(team.get("members") or []):
            if not isinstance(member, dict):
                continue
            agent_id = str(member.get("agentId") or "").strip()
            if agent_id and agent_id not in active_agent_ids:
                issues.append(
                    {
                        "severity": "warning",
                        "code": "stale_team_member",
                        "agentId": agent_id,
                        "title": "团队成员引用了不可用 Agent",
                        "detail": f"{team.get('name') or team.get('teamId') or '-'} 中的成员 agentId={agent_id} 不在活跃 Agent 列表中。",
                        "source": "team",
                        "action": "在团队画布中替换或解绑该成员。",
                    }
                )

    blocking = [item for item in issues if item.get("severity") == "blocking"]
    warnings = [item for item in issues if item.get("severity") == "warning"]
    return {
        "status": "blocked" if blocking else "warning" if warnings else "ok",
        "issues": issues,
        "counts": {
            "blocking": len(blocking),
            "warning": len(warnings),
            "info": sum(1 for item in issues if item.get("severity") == "info"),
        },
        "byAgent": _issues_by_agent(issues),
    }


def _derive_groups(agents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    group_ids = [
        ("active", "活跃 Agent", "status", "当前可被业务页面引用或调度的 Agent。"),
        ("needs_review", "需要处理", "status", "存在阻塞或警告健康项的活跃 Agent。"),
        ("archived", "已归档", "status", "只保留历史数据、不再进入可用池的 Agent。"),
        ("work_session", "会话工作 Agent", "boundary", "面向项目开发、调试和实现任务的 Codex-like 会话执行体。"),
        ("team_role", "团队角色 Agent", "boundary", "拥有人物/任务档案并进入团队、科研或业务组织结构的 Agent。"),
        ("system_role", "系统角色 Agent", "boundary", "由自进化、监督进化等系统流程固定管理的 Agent。"),
        ("service_role", "服务维护 Agent", "boundary", "负责知识、工具、记忆或平台维护的非人物团队成员 Agent。"),
        ("chat", "会话模式", "mode", "属于 Chat 运行模式或会话可用池的 Agent。"),
        ("research", "科研模式", "mode", "属于 Research 运行模式或科研池的 Agent。"),
        ("supervised_evolution", "监督进化模式", "mode", "占用监督进化模式引用的 Agent。"),
        ("self_evolution", "自进化模式", "mode", "占用自进化模式引用的 Agent。"),
        ("group_chat", "群聊引用", "reference", "被一个或多个群聊引用的 Agent。"),
        ("team", "团队引用", "reference", "被一个或多个团队画布引用的 Agent。"),
    ]
    groups: list[dict[str, Any]] = []
    for group_id, label, section, description in group_ids:
        agent_ids = [agent["agentId"] for agent in agents if _agent_in_group(agent, group_id)]
        groups.append(
            {
                "id": group_id,
                "label": label,
                "section": section,
                "description": description,
                "agentIds": agent_ids,
                "count": len(agent_ids),
                "healthCount": sum(
                    1
                    for agent in agents
                    if agent["agentId"] in agent_ids
                    and any(item.get("severity") in {"blocking", "warning"} for item in list(agent.get("health") or []))
                ),
            }
        )
    return groups


def _agent_in_group(agent: dict[str, Any], group_id: str) -> bool:
    status = str(agent.get("status") or "active").strip()
    if group_id == "active":
        return status != "archived"
    if group_id == "all":
        return True
    if group_id == "archived":
        return status == "archived"
    if status == "archived":
        return False
    boundary = agent.get("agentBoundary") if isinstance(agent.get("agentBoundary"), dict) else {}
    if group_id in {"work_session", "team_role", "system_role", "service_role"}:
        return str(boundary.get("type") or "").strip() == group_id
    references = list(agent.get("references") or [])
    if group_id == "group_chat":
        return any(item.get("kind") == "chat_room" for item in references)
    if group_id == "team":
        return any(item.get("kind") == "team" for item in references)
    if group_id == "needs_review":
        return any(item.get("severity") in {"blocking", "warning"} for item in list(agent.get("health") or []))
    if str(agent.get("primaryMode") or "").strip() == group_id:
        return True
    return any(item.get("mode") == group_id for item in references)


def _derive_agent_boundary(agent: dict[str, Any], *, references: list[dict[str, Any]] | None = None) -> dict[str, str]:
    status = str(agent.get("status") or "active").strip()
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    refs = references if references is not None else list(agent.get("references") or [])
    ref_kinds = {str(item.get("kind") or "").strip() for item in refs if isinstance(item, dict)}
    ref_modes = {str(item.get("mode") or "").strip() for item in refs if isinstance(item, dict)}
    primary_mode = str(agent.get("primaryMode") or "general").strip() or "general"
    role_key = str(agent.get("roleKey") or "").strip()
    created_by = str(agent.get("createdBy") or metadata.get("createdBy") or "").strip()

    if status == "archived":
        return {
            "type": "archived",
            "label": "已归档 Agent",
            "ownership": "archive",
            "directSessionRole": "historical_recovery",
            "reason": "agent_archived",
            "configurationSurface": "archive",
            "requiresPersonaProfile": "false",
            "requiresTaskProfile": "false",
            "requiresTeamMembership": "false",
        }

    system_markers = (
        primary_mode in {"self_evolution", "supervised_evolution"}
        or bool(str(metadata.get("selfEvolutionRole") or "").strip())
        or bool(str(metadata.get("supervisedRole") or "").strip())
        or "self_evolution" in ref_modes
        or "supervised_evolution" in ref_modes
    )
    if system_markers:
        return {
            "type": "system_role",
            "label": "系统角色 Agent",
            "ownership": "system",
            "directSessionRole": "recovery_channel",
            "reason": primary_mode if primary_mode in {"self_evolution", "supervised_evolution"} else "system_mode_reference",
            "configurationSurface": "system_role",
            "requiresPersonaProfile": "true",
            "requiresTaskProfile": "true",
            "requiresTeamMembership": "true",
        }

    service_markers = (
        role_key in {"knowledge_steward"}
        or "steward" in role_key
        or bool(str(metadata.get("systemRole") or "").strip())
        or str(metadata.get("protected") or "").lower() == "true"
    )
    if service_markers:
        return {
            "type": "service_role",
            "label": "服务维护 Agent",
            "ownership": "service",
            "directSessionRole": "recovery_channel" if str(agent.get("directSessionId") or "").strip() else "none",
            "reason": role_key or "service_metadata",
            "configurationSurface": "service",
            "requiresPersonaProfile": "false",
            "requiresTaskProfile": "true",
            "requiresTeamMembership": "false",
        }

    has_team_ref = "team" in ref_kinds
    research_markers = primary_mode == "research" or "research" in ref_modes or role_key.startswith("research_")
    if has_team_ref or research_markers:
        return {
            "type": "team_role",
            "label": "团队角色 Agent",
            "ownership": "team",
            "directSessionRole": "recovery_channel",
            "reason": "team_reference" if has_team_ref else "research_mode",
            "configurationSurface": "team_role",
            "requiresPersonaProfile": "true",
            "requiresTaskProfile": "true",
            "requiresTeamMembership": "true",
        }

    chat_default = any(
        isinstance(item, dict)
        and item.get("kind") == "mode_default"
        and str(item.get("mode") or "").strip() == "chat"
        for item in refs
    )
    chat_available = primary_mode == "chat" or "chat" in ref_modes
    created_by_session = created_by in {"user", "api_agents", "session_repair", "session_agent_binding", "session_delete_rebind"}
    if chat_available and not has_team_ref:
        return {
            "type": "work_session",
            "label": "会话工作 Agent",
            "ownership": "user",
            "directSessionRole": "primary_entry" if chat_default or created_by_session else "recovery_channel",
            "reason": "chat_default" if chat_default else "chat_mode_without_team",
            "configurationSurface": "work_session",
            "requiresPersonaProfile": "false",
            "requiresTaskProfile": "false",
            "requiresTeamMembership": "false",
        }

    return {
        "type": "service_role",
        "label": "服务维护 Agent",
        "ownership": "service",
        "directSessionRole": "recovery_channel" if str(agent.get("directSessionId") or "").strip() else "none",
        "reason": "unassigned_active_agent",
        "configurationSurface": "service",
        "requiresPersonaProfile": "false",
        "requiresTaskProfile": "true",
        "requiresTeamMembership": "false",
    }


def _summary(
    agents: list[dict[str, Any]],
    groups: list[dict[str, Any]],
    issues: list[dict[str, Any]],
    chat_rooms: list[dict[str, Any]],
    teams: list[dict[str, Any]],
    mode_bindings: dict[str, Any],
) -> dict[str, Any]:
    active_agents = [item for item in agents if str(item.get("status") or "active").strip() != "archived"]
    return {
        "agentCount": len(agents),
        "activeAgentCount": len(active_agents),
        "archivedAgentCount": len(agents) - len(active_agents),
        "runningAgentCount": sum(
            1
            for item in active_agents
            if str((item.get("runtimeStatus") or {}).get("state") or "").strip() == "running"
        ),
        "blockedAgentCount": sum(
            1
            for item in active_agents
            if str((item.get("runtimeStatus") or {}).get("state") or "").strip() in {"blocked", "failed"}
        ),
        "modeCount": len(dict(mode_bindings.get("modes") or {})),
        "chatRoomCount": len(chat_rooms),
        "teamCount": len([item for item in teams if str(item.get("status") or "active") != "archived"]),
        "groupCount": len(groups),
        "healthIssueCount": len(issues),
        "blockingIssueCount": sum(1 for item in issues if item.get("severity") == "blocking"),
        "warningIssueCount": sum(1 for item in issues if item.get("severity") == "warning"),
        "inboxPendingCount": sum(_safe_int(item.get("agentInboxPendingCount")) for item in agents),
    }


def _derive_runtime_statuses(agents: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    statuses: dict[str, dict[str, Any]] = {}
    for agent in agents:
        agent_id = str(agent.get("agentId") or "").strip()
        if not agent_id:
            continue
        statuses[agent_id] = _runtime_status_for_agent(agent)
    return statuses


def _runtime_status_for_agent(agent: dict[str, Any]) -> dict[str, Any]:
    base = _default_runtime_status(agent)
    agent_id = str(agent.get("agentId") or "").strip()
    if not agent_id or base["state"] == "archived":
        return base
    try:
        history = list_agent_runs_for_agent(agent_id, limit=6)
    except Exception as exc:
        return {
            **base,
            "state": "unknown",
            "label": "Unknown",
            "reason": "run_history_unavailable",
            "summary": type(exc).__name__,
        }
    snapshots = [item for item in [*(history.get("runs") or []), *(history.get("subAgentRuns") or [])] if isinstance(item, dict)]
    if not snapshots:
        return base
    snapshots.sort(key=_runtime_snapshot_sort_key, reverse=True)
    active = next((item for item in snapshots if _runtime_state_from_status(str(item.get("status") or item.get("currentPhase") or "")) == "running"), None)
    latest = active or snapshots[0]
    state = _runtime_state_from_status(str(latest.get("status") or latest.get("currentPhase") or ""))
    return {
        "state": state,
        "label": _runtime_state_label(state),
        "reason": str(latest.get("status") or latest.get("currentPhase") or state).strip() or state,
        "runId": str(latest.get("runId") or "").strip(),
        "runKind": str(latest.get("runKind") or "").strip(),
        "sessionId": str(latest.get("sessionId") or latest.get("parentSessionId") or agent.get("directSessionId") or "").strip(),
        "summary": str(latest.get("summary") or "").strip(),
        "updatedAt": str(
            latest.get("updatedAt")
            or latest.get("finishedAt")
            or latest.get("endedAt")
            or latest.get("startedAt")
            or latest.get("createdAt")
            or agent.get("updatedAt")
            or ""
        ).strip(),
    }


def _default_runtime_status(agent: dict[str, Any]) -> dict[str, Any]:
    status = str(agent.get("status") or "active").strip().lower()
    if status == "archived":
        return {
            "state": "archived",
            "label": "Archived",
            "reason": "agent_archived",
            "runId": "",
            "runKind": "",
            "sessionId": str(agent.get("directSessionId") or "").strip(),
            "summary": "",
            "updatedAt": str(agent.get("updatedAt") or "").strip(),
        }
    return {
        "state": "idle",
        "label": "Idle",
        "reason": "no_recent_runs",
        "runId": "",
        "runKind": "",
        "sessionId": str(agent.get("directSessionId") or "").strip(),
        "summary": "",
        "updatedAt": str(agent.get("updatedAt") or "").strip(),
    }


def _runtime_state_from_status(status: str) -> str:
    normalized = str(status or "").strip().lower()
    if normalized in {"queued", "running", "stopping", "paused"}:
        return "running"
    if normalized in {"failed", "error", "timeout"}:
        return "failed"
    if normalized in {"blocked", "needs_continue", "needs_input", "waiting", "paused_limit"}:
        return "blocked"
    if normalized in {"stopped", "cancelled", "stopped_by_user"}:
        return "stopped"
    return "idle"


def _runtime_state_label(state: str) -> str:
    return {
        "running": "Running",
        "failed": "Failed",
        "blocked": "Blocked",
        "stopped": "Stopped",
        "archived": "Archived",
        "unknown": "Unknown",
        "idle": "Idle",
    }.get(str(state or "idle"), "Idle")


def _runtime_snapshot_sort_key(snapshot: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(snapshot.get("updatedAt") or ""),
        str(snapshot.get("finishedAt") or snapshot.get("endedAt") or ""),
        str(snapshot.get("startedAt") or snapshot.get("createdAt") or ""),
        str(snapshot.get("runId") or ""),
    )


def _compact_chat_rooms(rooms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "roomId": str(room.get("roomId") or "").strip(),
            "title": str(room.get("title") or "").strip(),
            "mode": str(room.get("mode") or "").strip(),
            "status": str(room.get("status") or "").strip(),
            "activeRoundId": str(room.get("activeRoundId") or "").strip(),
            "agentIds": [
                str(participant.get("agentId") or "").strip()
                for participant in list(room.get("participants") or [])
                if isinstance(participant, dict) and str(participant.get("agentId") or "").strip()
            ],
            "participantCount": len(list(room.get("participants") or [])),
            "roundCount": len(list(room.get("rounds") or [])),
            "updatedAt": str(room.get("updatedAt") or "").strip(),
        }
        for room in rooms
    ]


def _compact_teams(teams: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "teamId": str(team.get("teamId") or "").strip(),
            "name": str(team.get("name") or "").strip(),
            "purpose": str(team.get("purpose") or "").strip(),
            "status": str(team.get("status") or "").strip(),
            "agentIds": [
                str(member.get("agentId") or "").strip()
                for member in list(team.get("members") or [])
                if isinstance(member, dict) and str(member.get("agentId") or "").strip()
            ],
            "memberCount": len(list(team.get("members") or [])),
            "updatedAt": str(team.get("updatedAt") or "").strip(),
        }
        for team in teams
    ]


def _safe_prompt_workspace() -> dict[str, Any]:
    try:
        return list_prompt_templates(include_inactive=True)
    except Exception as exc:
        _record_workspace_error("agent_config.prompt_templates.load_failed", exc)
        return {"templates": [], "repairWarnings": [{"source": "prompt_templates", "error": type(exc).__name__}]}


def _safe_config_workspace() -> dict[str, Any]:
    try:
        return config_service.get_config_workspace()
    except Exception as exc:
        _record_workspace_error("agent_config.models.load_failed", exc)
        return {"profileCards": [], "modelOptions": []}


def _safe_chat_rooms() -> list[dict[str, Any]]:
    try:
        return chat_room_service.list_chat_rooms_compact()
    except Exception as exc:
        _record_workspace_error("agent_config.chat_rooms.load_failed", exc)
        return []


def _safe_teams() -> list[dict[str, Any]]:
    try:
        from . import team_service

        return list(team_service.list_teams_compact(include_archived=True).get("teams") or [])
    except Exception as exc:
        _record_workspace_error("agent_config.teams.load_failed", exc)
        return []


def _safe_policy_options() -> dict[str, list[dict[str, Any]]]:
    try:
        return list_agent_policy_options()
    except Exception as exc:
        _record_workspace_error("agent_config.policies.load_failed", exc)
        return {"toolPolicies": [], "memoryPolicies": []}


def _agent_llm_slots() -> list[dict[str, Any]]:
    ordered_slots = []
    for slot in AGENT_LLM_BINDING_SLOTS:
        definition = dict(AGENT_LLM_SLOT_REFS.get(slot) or {})
        if not definition:
            definition = {
                "slot": slot,
                "label": slot,
                "description": "",
                "required": False,
                "requiresImageInput": False,
            }
        ordered_slots.append(definition)
    return ordered_slots


def _agent_model_choices(model_options: list[Any]) -> list[dict[str, Any]]:
    choices: list[dict[str, Any]] = []
    seen: set[str] = set()
    for option in model_options:
        if not isinstance(option, dict):
            continue
        model_id = str(option.get("model_id") or option.get("modelId") or "").strip()
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        provider = option.get("provider") if isinstance(option.get("provider"), dict) else {}
        provider_kind = str(option.get("provider_kind") or provider.get("kind") or "").strip()
        api_key_configured = bool(option.get("api_key_configured", False))
        requires_api_key = bool(provider.get("requires_api_key", provider_kind != "local"))
        choice = {
            "modelId": model_id,
            "label": str(option.get("label") or option.get("model") or model_id).strip() or model_id,
            "model": str(option.get("model") or "").strip(),
            "providerKind": provider_kind,
            "providerBaseUrl": str(provider.get("base_url") or "").strip(),
            "source": str(option.get("source") or "").strip(),
            "apiKeyEnv": str(option.get("api_key_env") or "").strip(),
            "apiKeyConfigured": api_key_configured,
            "apiKeyState": str(option.get("api_key_state") or "").strip(),
            "requiresApiKey": requires_api_key,
            "missingApiKey": requires_api_key and not api_key_configured,
            "supportsImageInput": option.get("supports_image_input"),
            "capabilityStatus": str(option.get("capability_status") or "").strip(),
            "capabilitySource": str(option.get("capability_source") or "").strip(),
        }
        choices.append(choice)
    choices.sort(key=lambda item: (str(item.get("label") or "").lower(), str(item.get("modelId") or "").lower()))
    return choices


def _llm_binding_model_refs(bindings: Any, model_refs: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any] | None]:
    normalized = normalize_agent_llm_bindings(bindings)
    return {
        slot: model_refs.get(str(binding.get("modelId") or "").strip())
        for slot, binding in normalized.items()
        if isinstance(binding, dict)
    }


def _agent_option(agent: dict[str, Any]) -> dict[str, Any]:
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    return {
        "agentId": str(agent.get("agentId") or "").strip(),
        "agentCode": str(agent.get("agentCode") or "").strip(),
        "displayName": str(agent.get("displayName") or "").strip(),
        "primaryMode": str(agent.get("primaryMode") or "general").strip() or "general",
        "roleKey": str(agent.get("roleKey") or "").strip(),
        "llmBindings": normalize_agent_llm_bindings(agent.get("llmBindings")),
        "promptTemplateId": str(agent.get("promptTemplateId") or "").strip(),
        "directSessionId": str(agent.get("directSessionId") or "").strip(),
        "metadata": dict(metadata),
    }


def _timed_stage(timings: dict[str, float], name: str, fn: Any) -> Any:
    started = perf_counter()
    try:
        return fn()
    finally:
        timings[name] = round((perf_counter() - started) * 1000, 1)


def _agent_issue(agent: dict[str, Any], severity: str, code: str, title: str, detail: str) -> dict[str, Any]:
    return {
        "severity": severity,
        "code": code,
        "agentId": str(agent.get("agentId") or "").strip(),
        "agentCode": str(agent.get("agentCode") or "").strip(),
        "title": title,
        "detail": detail,
        "source": "agent",
        "action": "在 Agent Center 编辑这个 Agent 的统一配置。",
    }


def _issues_by_agent(issues: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for issue in issues:
        agent_id = str(issue.get("agentId") or "").strip()
        if agent_id:
            grouped[agent_id].append(issue)
    return dict(grouped)


def _creation_field_label(field: str) -> str:
    labels = {
        "displayName": "功能名",
        "llmBindings": "对话模型",
        "primaryMode": "使用位置",
        "roleKey": "角色键",
        "promptTemplateId": "提示词",
        "personaProfile": "人物档案",
        "taskProfile": "任务档案",
        "toolPolicy": "工具包",
        "memoryPolicy": "记忆策略",
    }
    return labels.get(field, field)


def _onboarding_missing_for_boundary(agent: dict[str, Any], boundary: dict[str, str]) -> list[str]:
    boundary_type = str(boundary.get("type") or "").strip()
    if boundary_type == "work_session":
        return []

    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    raw_missing = [
        str(item).strip()
        for item in list(metadata.get("onboardingMissing") or [])
        if str(item).strip()
    ]
    skip = {"personaProfile", "taskProfile"}
    if boundary_type in {"team_role", "system_role"}:
        skip = set()
    elif boundary_type == "service_role":
        skip = {"personaProfile"}

    missing = [item for item in raw_missing if item not in skip]
    if "personaProfile" not in skip and not agent_persona_profile_has_content(_agent_persona_profile(agent)):
        missing.append("personaProfile")
    if "taskProfile" not in skip and not agent_task_profile_has_content(_agent_task_profile(agent)):
        missing.append("taskProfile")
    return _string_list(missing)


def _agent_persona_profile(agent: dict[str, Any]) -> dict[str, Any]:
    profile = agent.get("personaProfile")
    if isinstance(profile, dict):
        return profile
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    profile = metadata.get("personaProfile")
    return profile if isinstance(profile, dict) else {}


def _agent_task_profile(agent: dict[str, Any]) -> dict[str, Any]:
    profile = agent.get("taskProfile")
    if isinstance(profile, dict):
        return profile
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    profile = metadata.get("taskProfile")
    return profile if isinstance(profile, dict) else {}


def _reference(
    kind: str,
    *,
    source_id: str,
    source_label: str,
    mode: str = "",
    field: str = "",
    route: str = "",
    status: str = "active",
) -> dict[str, str]:
    return {
        "kind": kind,
        "sourceId": str(source_id or "").strip(),
        "sourceLabel": str(source_label or "").strip(),
        "mode": str(mode or "").strip(),
        "field": str(field or "").strip(),
        "route": str(route or "").strip(),
        "status": str(status or "active").strip() or "active",
    }


def _dedupe_references(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str, str]] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        key = (
            str(item.get("kind") or ""),
            str(item.get("sourceId") or ""),
            str(item.get("mode") or ""),
            str(item.get("field") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(dict(item))
    return result


def _string_list(values: Any) -> list[str]:
    if values is None or isinstance(values, (str, bytes)):
        return []
    try:
        iterator = iter(values)
    except TypeError:
        return []
    result: list[str] = []
    seen: set[str] = set()
    for value in iterator:
        item = str(value or "").strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _relative_path(path_func: Any) -> str:
    try:
        path = path_func()
    except Exception:
        return ""
    try:
        return path.as_posix()
    except AttributeError:
        return str(path)


def _record_workspace_loaded(
    summary: dict[str, Any],
    *,
    timings: dict[str, float] | None = None,
    load_modes: dict[str, str] | None = None,
) -> None:
    try:
        record_runtime_scene_event(
            "agent_configuration",
            "workspace",
            "agent_config.workspace.loaded",
            message="Agent config workspace loaded.",
            level="info",
            outcome="observed",
            fields={
                "agentCount": summary.get("agentCount", 0),
                "activeAgentCount": summary.get("activeAgentCount", 0),
                "modeCount": summary.get("modeCount", 0),
                "chatRoomCount": summary.get("chatRoomCount", 0),
                "healthIssueCount": summary.get("healthIssueCount", 0),
                "timingsMs": dict(timings or {}),
                "loadModes": dict(load_modes or {}),
            },
            lifecycle=False,
        )
    except Exception:
        return


def _record_workspace_error(event_code: str, exc: Exception) -> None:
    try:
        record_runtime_scene_event(
            "agent_configuration",
            "workspace",
            event_code,
            message=event_code,
            level="warning",
            outcome="failed",
            fields={"errorType": type(exc).__name__},
        )
    except Exception:
        return


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
