"""Read-only Agent configuration workspace aggregation."""

from __future__ import annotations

import copy
import threading
from collections import defaultdict
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Callable, Iterable

from core.llm.reasoning_effort import GPT_REASONING_EFFORT_VALUES, model_supports_gpt_reasoning_effort
from core.orchestration.context_engine import list_agent_runs_for_agents

from . import chat_room_service, config_service
from .agent_directory_service import agent_persona_profile_has_content
from .agent_directory_service import agent_task_profile_has_content
from .agent_directory_service import AGENT_LLM_BINDING_SLOTS
from .agent_directory_service import SESSION_AGENT_VISIBILITY_PENDING
from .agent_directory_service import agent_dialogue_model_id
from .agent_directory_service import build_agent_policy_options
from .agent_directory_service import list_agents
from .agent_directory_service import list_agent_policy_options
from .agent_directory_service import normalize_agent_llm_bindings
from .agent_directory_service import registry_path
from .agent_directory_service import session_agent_visibility
from .agent_mode_binding_service import get_mode_bindings_payload, mode_binding_path
from .prompt_template_service import list_prompt_templates, prompt_template_path
from .runtime_scene_service import record_runtime_scene_event


SCHEMA_VERSION = 1
RUNTIME_HISTORY_LOAD_ERROR_KEY = "__load_error__"
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
HEALTH_LOG_CODE_LIMIT = 12
HEALTH_LOG_AGENT_LIMIT = 12
HEALTH_LOG_SAMPLE_LIMIT = 8
EMPTY_TOOL_POLICY_ID = "default"
MUTATING_AGENT_TOOLS = {
    "apply_patch_tool",
    "apply_diff_edit_tool",
    "write_file_tool",
    "cli_tool",
    "cli_agent_run_tool",
    "run_test_for_tool",
    "python_lint_tool",
}
RESEARCH_SOURCE_ROLE_KEYS = {
    "ai_search_scope_lead",
    "global_primary_sources",
    "cn_primary_sources",
    "signal_quality_gate",
}
WORKSPACE_CACHE_TTL_SECONDS = 3.0
_WORKSPACE_CACHE_LOCK = threading.Lock()
_WORKSPACE_CACHE_PAYLOAD: dict[str, Any] | None = None
_WORKSPACE_CACHE_KEY: tuple[Any, ...] | None = None
_WORKSPACE_CACHE_CREATED_AT = 0.0


def get_agent_config_workspace(*, use_cache: bool = False, include_runtime: bool = True) -> dict[str, Any]:
    """Return a read-only workspace that explains every persistent Agent once."""

    if use_cache:
        return _get_agent_config_workspace_cached(include_runtime=include_runtime)
    return _build_agent_config_workspace(
        include_runtime=include_runtime,
        cache_diagnostics={"enabled": False, "hit": False},
    )


def invalidate_agent_config_workspace_cache() -> None:
    """Clear the short-lived Agent config workspace cache after known mutations."""

    global _WORKSPACE_CACHE_PAYLOAD, _WORKSPACE_CACHE_KEY, _WORKSPACE_CACHE_CREATED_AT
    with _WORKSPACE_CACHE_LOCK:
        _WORKSPACE_CACHE_PAYLOAD = None
        _WORKSPACE_CACHE_KEY = None
        _WORKSPACE_CACHE_CREATED_AT = 0.0


def _get_agent_config_workspace_cached(*, include_runtime: bool) -> dict[str, Any]:
    global _WORKSPACE_CACHE_PAYLOAD, _WORKSPACE_CACHE_KEY, _WORKSPACE_CACHE_CREATED_AT

    wait_started = perf_counter()
    with _WORKSPACE_CACHE_LOCK:
        wait_ms = round((perf_counter() - wait_started) * 1000, 1)
        now = perf_counter()
        cache_key = _workspace_cache_key(include_runtime=include_runtime)
        if (
            _WORKSPACE_CACHE_PAYLOAD is not None
            and _WORKSPACE_CACHE_KEY == cache_key
            and now - _WORKSPACE_CACHE_CREATED_AT <= WORKSPACE_CACHE_TTL_SECONDS
        ):
            return _with_cache_diagnostics(
                _WORKSPACE_CACHE_PAYLOAD,
                enabled=True,
                hit=True,
                wait_ms=wait_ms,
                age_ms=round((now - _WORKSPACE_CACHE_CREATED_AT) * 1000, 1),
            )
        payload = _build_agent_config_workspace(
            include_runtime=include_runtime,
            cache_diagnostics={
                "enabled": True,
                "hit": False,
                "waitMs": wait_ms,
                "ttlSeconds": WORKSPACE_CACHE_TTL_SECONDS,
            }
        )
        cache_key = _workspace_cache_key(include_runtime=include_runtime)
        _WORKSPACE_CACHE_PAYLOAD = copy.deepcopy(payload)
        _WORKSPACE_CACHE_KEY = cache_key
        _WORKSPACE_CACHE_CREATED_AT = perf_counter()
        return _with_cache_diagnostics(
            payload,
            enabled=True,
            hit=False,
            wait_ms=wait_ms,
            age_ms=0.0,
        )


def _build_agent_config_workspace(
    *,
    include_runtime: bool,
    cache_diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    timings: dict[str, float] = {}
    load_modes: dict[str, str] = {}
    total_started = perf_counter()
    agents = _timed_stage(timings, "list_agents", lambda: list_agents(include_archived=True, detail="config"))
    active_agent_options = [_agent_option(agent) for agent in agents if str(agent.get("status") or "active").strip() != "archived"]
    mode_bindings = _timed_stage(
        timings,
        "mode_bindings",
        lambda: get_mode_bindings_payload(agent_options=active_agent_options),
    )
    prompt_workspace = _timed_stage(timings, "prompt_templates", _safe_prompt_workspace)
    config_workspace = _timed_stage(timings, "model_config", _safe_config_workspace)
    chat_rooms = _timed_stage(timings, "chat_rooms", lambda: _safe_chat_rooms_for_agents(agents))
    teams = _timed_stage(timings, "teams", lambda: _visible_agent_config_teams(_safe_teams()))
    policy_options = _timed_stage(timings, "policy_options", lambda: _safe_policy_options(agents=agents))

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
    if include_runtime:
        runtime_histories = _timed_stage(timings, "runtime_histories", lambda: _load_runtime_histories(agents))
        runtime_status_by_agent = _timed_stage(
            timings,
            "runtime_statuses",
            lambda: _derive_runtime_statuses(agents, histories_by_agent=runtime_histories),
        )
        load_modes["runtimeStatuses"] = "batched"
    else:
        timings["runtime_histories"] = 0.0
        timings["runtime_statuses"] = 0.0
        runtime_status_by_agent = {}
        load_modes["runtimeStatuses"] = "skipped"
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
    team_indexes = _timed_stage(
        timings,
        "derive_team_indexes",
        lambda: _derive_team_indexes(teams, agents=enriched_agents),
    )
    summary = _timed_stage(timings, "summary", lambda: _summary(enriched_agents, groups, health["issues"], chat_rooms, teams, mode_bindings))
    timings["total"] = round((perf_counter() - total_started) * 1000, 1)
    load_modes["chatRooms"] = "compact"
    load_modes["teams"] = "graph_references"
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": _now(),
        "storage": {
            "agentRegistryPath": _relative_path(registry_path),
            "modeBindingPath": _relative_path(mode_binding_path()),
            "promptTemplatePath": _relative_path(prompt_template_path()),
        },
        "summary": summary,
        "groups": groups,
        "teamIndexes": team_indexes,
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
        "diagnostics": {
            "timingsMs": dict(timings),
            "loadModes": dict(load_modes),
            "cache": dict(cache_diagnostics or {}),
        },
    }
    _record_workspace_loaded(summary, timings=timings, load_modes=load_modes, issues=health["issues"])
    _record_model_reference_resolution(health["issues"])
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


def _prompt_template_has_runtime_content(prompt: dict[str, Any]) -> bool:
    try:
        return int(prompt.get("contentLength") or 0) > 0
    except (TypeError, ValueError):
        return bool(str(prompt.get("contentPreview") or "").strip())


def _agent_has_system_fixed_role(agent: dict[str, Any]) -> bool:
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    if bool(metadata.get("fixedRole")):
        return True
    if str(agent.get("primaryMode") or "").strip() in {"self_evolution", "supervised_evolution"}:
        return True
    return any(
        str(metadata.get(key) or "").strip()
        for key in ("selfEvolutionRole", "supervisedRole", "systemRole", "aiSearchRole")
    )


def _is_research_source_role(agent: dict[str, Any]) -> bool:
    role_key = str(agent.get("roleKey") or "").strip()
    return str(agent.get("primaryMode") or "").strip() == "research" and role_key in RESEARCH_SOURCE_ROLE_KEYS


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
                        f"unresolved_model_reference_{slot_key}",
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
            if not _prompt_template_has_runtime_content(prompt) and prompt_template_id != "prompt-chat-default":
                issues.append(
                    _agent_issue(
                        agent,
                        "warning",
                        "empty_prompt_template_content",
                        "提示词模板内容为空",
                        f"{prompt_template_id} 没有可注入的模板内容；运行时只会使用 Agent 身份档案，Prompt Template 段为空。",
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
        tool_policy = agent.get("toolPolicy") if isinstance(agent.get("toolPolicy"), dict) else {}
        allowed_tools = [str(item or "").strip() for item in list(tool_policy.get("allowedTools") or []) if str(item or "").strip()]
        if _agent_has_system_fixed_role(agent) and str(agent.get("toolPolicyId") or "").strip() == EMPTY_TOOL_POLICY_ID:
            issues.append(
                _agent_issue(
                    agent,
                    "warning",
                    "default_empty_tool_policy_for_fixed_role",
                    "系统角色仍使用默认空工具策略",
                    "固定系统 Agent 应绑定显式 no-tools 策略或角色专用最小工具策略，避免把未配置误显示为已配置。",
                )
            )
        risky_tools = sorted(set(allowed_tools).intersection(MUTATING_AGENT_TOOLS))
        if _is_research_source_role(agent) and risky_tools:
            issues.append(
                _agent_issue(
                    agent,
                    "warning",
                    "research_source_tool_policy_too_broad",
                    "研究索引角色工具权限过宽",
                    "这个角色只应使用检索、知识查询和 Agent 消息工具；当前包含高风险工具：" + "、".join(risky_tools[:8]) + "。",
                )
            )
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

    for room in chat_rooms:
        if str(room.get("status") or "active").strip() == "archived":
            continue
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
                        "detail": f"{room.get('title') or room.get('roomId') or '-'} 中的成员 agentId={agent_id} 不在可用 Agent 列表中。",
                        "source": "chat_room",
                        "action": "在群聊管理中替换或移除该成员。",
                    }
                )
            _extend_chat_room_participant_model_issues(
                issues,
                room=room,
                participant=participant,
                model_refs=model_refs,
                active_agent_ids=active_agent_ids,
            )

    for team in teams:
        if str(team.get("status") or "active").strip().lower() == "archived":
            continue
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
                        "detail": f"{team.get('name') or team.get('teamId') or '-'} 中的成员 agentId={agent_id} 不在可用 Agent 列表中。",
                        "source": "team",
                        "action": "在团队画布中替换或解绑该成员。",
                    }
                )
    issues.extend(_duplicate_team_name_issues(teams))

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
        ("active", "可用 Agent", "status", "当前可被业务页面引用或调度的 Agent。"),
        ("needs_review", "需要处理", "status", "存在阻塞或警告健康项的可用 Agent。"),
        ("archived", "已归档", "status", "只保留历史数据、不再进入可用池的 Agent。"),
        ("work_session", "会话入口 Agent", "boundary", "面向项目开发、调试和实现任务的 Codex-like 会话执行体。"),
        ("team_role", "团队/科研角色 Agent", "boundary", "拥有人物/任务档案并进入团队、科研或业务组织结构的 Agent。"),
        ("system_role", "系统进化 Agent", "boundary", "由自进化、监督进化等系统流程固定管理的 Agent。"),
        ("service_role", "平台服务 Agent", "boundary", "负责知识、工具、记忆或平台维护的非人物团队成员 Agent。"),
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


def _derive_team_indexes(teams: list[dict[str, Any]], *, agents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    agents_by_id = {
        str(agent.get("agentId") or "").strip(): agent
        for agent in agents
        if isinstance(agent, dict) and str(agent.get("agentId") or "").strip()
    }

    def visible_member_ids(members: list[dict[str, Any]]) -> list[str]:
        member_ids = _unique_string_list(member.get("agentId") for member in members)
        return [
            agent_id
            for agent_id in member_ids
            if agent_id in agents_by_id and str(agents_by_id[agent_id].get("status") or "active").strip() != "archived"
        ]

    def health_count(agent_ids: list[str]) -> int:
        return sum(
            1
            for agent_id in agent_ids
            if any(
                item.get("severity") in {"blocking", "warning"}
                for item in list(agents_by_id.get(agent_id, {}).get("health") or [])
            )
        )

    team_indexes: list[dict[str, Any]] = []
    source_scope_indexes: list[dict[str, Any]] = []
    for team in teams:
        if not isinstance(team, dict):
            continue
        team_id = str(team.get("teamId") or "").strip()
        status = str(team.get("status") or "active").strip()
        if not team_id or status == "archived":
            continue
        members = [member for member in list(team.get("members") or []) if isinstance(member, dict)]
        agent_ids = visible_member_ids(members)
        if not agent_ids:
            continue
        team_name = str(team.get("name") or team_id).strip()
        team_category = str(team.get("teamCategory") or "").strip()
        purpose = str(team.get("purpose") or team.get("description") or "").strip()
        team_indexes.append(
            {
                "id": f"team:{team_id}",
                "label": team_name,
                "section": "team_index",
                "description": _join_nonempty([team_category, purpose], separator=" / "),
                "agentIds": agent_ids,
                "count": len(agent_ids),
                "healthCount": health_count(agent_ids),
                "teamId": team_id,
                "teamKind": str(team.get("teamKind") or "").strip(),
                "teamCategory": team_category,
                "source": "team",
            }
        )
        source_scope_indexes.extend(
            _derive_source_scope_indexes(
                team,
                members=members,
                visible_member_ids=agent_ids,
                health_count=health_count,
            )
        )
    return _collapse_duplicate_team_indexes(team_indexes, health_count=health_count) + source_scope_indexes


def _collapse_duplicate_team_indexes(
    indexes: list[dict[str, Any]],
    *,
    health_count: Callable[[list[str]], int],
) -> list[dict[str, Any]]:
    by_label: dict[str, list[dict[str, Any]]] = defaultdict(list)
    order: list[str] = []
    for index in indexes:
        label_key = _normalized_team_index_label(index)
        if not label_key:
            label_key = str(index.get("id") or "").strip()
        if label_key not in by_label:
            order.append(label_key)
        by_label[label_key].append(index)

    collapsed: list[dict[str, Any]] = []
    for label_key in order:
        items = by_label[label_key]
        if len(items) <= 1:
            collapsed.append(items[0])
            continue
        items = sorted(items, key=lambda item: str(item.get("teamId") or item.get("id") or "").strip())
        first = items[0]
        agent_ids = _unique_string_list(
            agent_id
            for item in items
            for agent_id in list(item.get("agentIds") or [])
        )
        team_ids = _unique_string_list(item.get("teamId") for item in items)
        team_kinds = _unique_string_list(item.get("teamKind") for item in items)
        team_categories = _unique_string_list(item.get("teamCategory") for item in items)
        collapsed.append(
            {
                **first,
                "id": f"{first.get('id')}:duplicate-name-group",
                "description": f"检测到 {len(items)} 个同名团队，已合并显示，避免 Agent Center 左侧索引重复。",
                "agentIds": agent_ids,
                "count": len(agent_ids),
                "healthCount": health_count(agent_ids),
                "teamId": str(first.get("teamId") or "").strip(),
                "teamKind": team_kinds[0] if len(team_kinds) == 1 else "mixed",
                "teamCategory": team_categories[0] if len(team_categories) == 1 else "mixed",
                "source": "duplicate_team_name",
                "duplicateTeamCount": len(items),
                "duplicateTeamIds": team_ids,
            }
        )
    return collapsed


def _normalized_team_index_label(index: dict[str, Any]) -> str:
    return " ".join(str(index.get("label") or "").strip().casefold().split())


def _duplicate_team_name_issues(teams: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    display_names: dict[str, str] = {}
    for team in teams:
        if not isinstance(team, dict):
            continue
        if str(team.get("status") or "active").strip().lower() == "archived":
            continue
        team_id = str(team.get("teamId") or "").strip()
        name = str(team.get("name") or "").strip()
        key = " ".join(name.casefold().split())
        if not team_id or not key:
            continue
        display_names.setdefault(key, name)
        by_name[key].append(team)
    issues: list[dict[str, Any]] = []
    for key, items in by_name.items():
        if len(items) <= 1:
            continue
        team_ids = _unique_string_list(team.get("teamId") for team in items)
        display_name = display_names.get(key) or key
        issues.append(
            {
                "severity": "warning",
                "code": "duplicate_team_name",
                "agentId": "",
                "title": "存在同名团队",
                "detail": f"{display_name} 有 {len(items)} 个 active 团队：{', '.join(team_ids[:8])}{'...' if len(team_ids) > 8 else ''}。",
                "source": "team",
                "action": "在 Teams 页面确认是否需要合并、重命名或归档重复团队。",
            }
        )
    return issues


def _visible_agent_config_teams(teams: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Agent Center indexes are Agent-centric, so empty teams are not useful filters."""

    visible: list[dict[str, Any]] = []
    for team in list(teams or []):
        if not isinstance(team, dict):
            continue
        if str(team.get("status") or "active").strip().lower() == "archived":
            continue
        members = [member for member in list(team.get("members") or []) if isinstance(member, dict)]
        if not any(str(member.get("agentId") or "").strip() for member in members):
            continue
        visible.append(team)
    return visible


def _derive_source_scope_indexes(
    team: dict[str, Any],
    *,
    members: list[dict[str, Any]],
    visible_member_ids: list[str],
    health_count: Callable[[list[str]], int],
) -> list[dict[str, Any]]:
    scope = _safe_team_source_scope(team)
    if not isinstance(scope, dict):
        return []
    team_id = str(team.get("teamId") or "").strip()
    team_name = str(team.get("name") or team_id).strip()
    if not team_id:
        return []
    indexes: list[dict[str, Any]] = []
    for group in list(scope.get("groups") or []):
        if not isinstance(group, dict):
            continue
        group_id = str(group.get("groupId") or "").strip()
        if not group_id:
            continue
        owner_role = str(group.get("ownerRole") or "").strip()
        owner_agent_ids = _unique_string_list(
            member.get("agentId")
            for member in members
            if owner_role and str(member.get("role") or "").strip() == owner_role
        )
        owner_agent_ids = [agent_id for agent_id in owner_agent_ids if agent_id in visible_member_ids]
        agent_ids = owner_agent_ids or visible_member_ids
        source_count = _safe_int(group.get("sourceCount"))
        base_label = str(group.get("label") or group_id).strip()
        indexes.append(
            {
                "id": f"source:{team_id}:{group_id}",
                "label": f"{base_label} · {source_count} 源" if source_count else base_label,
                "section": "source_scope",
                "description": _join_nonempty(
                    [
                        team_name,
                        str(group.get("tier") or "").strip(),
                        str(group.get("description") or "").strip(),
                    ],
                    separator=" / ",
                ),
                "agentIds": agent_ids,
                "count": len(agent_ids),
                "healthCount": health_count(agent_ids),
                "teamId": team_id,
                "sourceScopeGroupId": group_id,
                "sourceCount": source_count,
                "enabledByDefault": bool(group.get("enabledByDefault")),
                "evidenceRole": str(group.get("evidenceRole") or "").strip(),
                "source": "source_scope",
            }
        )
    return indexes


def _safe_team_source_scope(team: dict[str, Any]) -> dict[str, Any] | None:
    if str(team.get("teamKind") or "").strip() != "ai_search":
        return None
    try:
        from . import team_service

        fields = team_service._ai_search_source_scope_api_fields(team)  # type: ignore[attr-defined]
        scope = fields.get("sourceScope") if isinstance(fields, dict) else None
        return scope if isinstance(scope, dict) else None
    except Exception as exc:
        _record_workspace_error("agent_config.team_source_scope.load_failed", exc)
        return None


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
            "label": "系统进化 Agent",
            "ownership": "system",
            "directSessionRole": "recovery_channel",
            "reason": primary_mode if primary_mode in {"self_evolution", "supervised_evolution"} else "system_mode_reference",
            "configurationSurface": "system_role",
            "requiresPersonaProfile": "true",
            "requiresTaskProfile": "true",
            "requiresTeamMembership": "true",
        }

    has_team_ref = "team" in ref_kinds
    research_markers = primary_mode == "research" or "research" in ref_modes or role_key.startswith("research_")
    if has_team_ref or research_markers:
        return {
            "type": "team_role",
            "label": "团队/科研角色 Agent",
            "ownership": "team",
            "directSessionRole": "recovery_channel",
            "reason": "team_reference" if has_team_ref else "research_mode",
            "configurationSurface": "team_role",
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
            "label": "平台服务 Agent",
            "ownership": "service",
            "directSessionRole": "recovery_channel" if str(agent.get("directSessionId") or "").strip() else "none",
            "reason": role_key or "service_metadata",
            "configurationSurface": "service",
            "requiresPersonaProfile": "false",
            "requiresTaskProfile": "true",
            "requiresTeamMembership": "false",
        }

    chat_default = any(
        isinstance(item, dict)
        and item.get("kind") == "mode_default"
        and str(item.get("mode") or "").strip() == "chat"
        for item in refs
    )
    chat_available = primary_mode == "chat" or "chat" in ref_modes
    created_by_session = created_by in {"user", "api_agents", "session_repair", "session_agent_binding", "session_delete_rebind"}
    activity_gated_session_source = created_by != "api_agents"
    if (
        chat_available
        and not has_team_ref
        and activity_gated_session_source
        and session_agent_visibility(agent) == SESSION_AGENT_VISIBILITY_PENDING
    ):
        return {
            "type": "service_role",
            "label": "待激活会话 Agent",
            "ownership": "service",
            "directSessionRole": "pending_activity",
            "reason": "empty_direct_session",
            "configurationSurface": "service",
            "requiresPersonaProfile": "false",
            "requiresTaskProfile": "false",
            "requiresTeamMembership": "false",
        }
    if chat_available and not has_team_ref:
        return {
            "type": "work_session",
            "label": "会话入口 Agent",
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
        "label": "平台服务 Agent",
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
    actionable_issues = [item for item in issues if item.get("severity") in {"blocking", "warning"}]
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
        "healthIssueCount": len(actionable_issues),
        "blockingIssueCount": sum(1 for item in issues if item.get("severity") == "blocking"),
        "warningIssueCount": sum(1 for item in issues if item.get("severity") == "warning"),
        "inboxPendingCount": sum(_safe_int(item.get("agentInboxPendingCount")) for item in agents),
    }


def _load_runtime_histories(agents: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    agent_ids = [
        str(agent.get("agentId") or "").strip()
        for agent in agents
        if str(agent.get("agentId") or "").strip()
        and str(agent.get("status") or "active").strip().lower() != "archived"
    ]
    if not agent_ids:
        return {}
    try:
        payload = list_agent_runs_for_agents(agent_ids, limit=6)
    except Exception as exc:
        _record_workspace_error("agent_config.runtime_histories.load_failed", exc)
        return {RUNTIME_HISTORY_LOAD_ERROR_KEY: {"errorType": type(exc).__name__}}
    histories = payload.get("agents") if isinstance(payload, dict) else {}
    return {str(agent_id): history for agent_id, history in dict(histories or {}).items() if isinstance(history, dict)}


def _derive_runtime_statuses(
    agents: list[dict[str, Any]],
    *,
    histories_by_agent: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    statuses: dict[str, dict[str, Any]] = {}
    histories = dict(histories_by_agent or {})
    load_error = histories.get(RUNTIME_HISTORY_LOAD_ERROR_KEY)
    histories_provided = histories_by_agent is not None
    for agent in agents:
        agent_id = str(agent.get("agentId") or "").strip()
        if not agent_id:
            continue
        if isinstance(load_error, dict) and str(agent.get("status") or "active").strip().lower() != "archived":
            base = _default_runtime_status(agent)
            statuses[agent_id] = {
                **base,
                "state": "unknown",
                "label": "Unknown",
                "reason": "run_history_unavailable",
                "summary": str(load_error.get("errorType") or "RuntimeHistoryLoadError"),
            }
            continue
        statuses[agent_id] = _runtime_status_for_agent(
            agent,
            history=histories.get(agent_id, {}) if histories_provided else None,
        )
    return statuses


def _runtime_status_for_agent(agent: dict[str, Any], *, history: dict[str, Any] | None = None) -> dict[str, Any]:
    base = _default_runtime_status(agent)
    agent_id = str(agent.get("agentId") or "").strip()
    if not agent_id or base["state"] == "archived":
        return base
    try:
        if history is None:
            history = list_agent_runs_for_agents([agent_id], limit=6).get("agents", {}).get(agent_id, {})
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
    direct_session_id = str(agent.get("directSessionId") or "").strip()
    current_snapshots = (
        [item for item in snapshots if _runtime_snapshot_session_id(item) == direct_session_id]
        if direct_session_id
        else list(snapshots)
    )
    stale_snapshots = [item for item in snapshots if item not in current_snapshots] if direct_session_id else []
    if not current_snapshots:
        if stale_snapshots:
            latest_stale = stale_snapshots[0]
            _record_stale_runtime_snapshot_ignored(agent, latest_stale, stale_count=len(stale_snapshots))
            return {
                **base,
                "reason": "no_current_direct_session_runs",
                "staleRuntimeRunCount": len(stale_snapshots),
                "latestHistoricalRunId": str(latest_stale.get("runId") or "").strip(),
                "latestHistoricalSessionId": _runtime_snapshot_session_id(latest_stale),
                "latestHistoricalUpdatedAt": str(
                    latest_stale.get("updatedAt")
                    or latest_stale.get("finishedAt")
                    or latest_stale.get("endedAt")
                    or latest_stale.get("startedAt")
                    or latest_stale.get("createdAt")
                    or ""
                ).strip(),
            }
        return base
    active = next(
        (
            item
            for item in current_snapshots
            if _runtime_state_from_status(str(item.get("status") or item.get("currentPhase") or "")) == "running"
        ),
        None,
    )
    latest = active or current_snapshots[0]
    state = _runtime_state_from_status(str(latest.get("status") or latest.get("currentPhase") or ""))
    return {
        "state": state,
        "label": _runtime_state_label(state),
        "reason": str(latest.get("status") or latest.get("currentPhase") or state).strip() or state,
        "runId": str(latest.get("runId") or "").strip(),
        "runKind": str(latest.get("runKind") or "").strip(),
        "sessionId": _runtime_snapshot_session_id(latest) or direct_session_id,
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
        "staleRuntimeRunCount": len(stale_snapshots),
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


def _runtime_snapshot_session_id(snapshot: dict[str, Any]) -> str:
    return str(snapshot.get("sessionId") or snapshot.get("parentSessionId") or "").strip()


def _record_stale_runtime_snapshot_ignored(agent: dict[str, Any], snapshot: dict[str, Any], *, stale_count: int) -> None:
    record_runtime_scene_event(
        "agent_config",
        "runtime_status",
        "agent_config.runtime_status_stale_run_ignored",
        message="Ignored stale Agent run snapshot while deriving current direct-session runtime status.",
        fields={
            "agentId": str(agent.get("agentId") or "").strip(),
            "directSessionId": str(agent.get("directSessionId") or "").strip(),
            "runId": str(snapshot.get("runId") or "").strip(),
            "snapshotSessionId": _runtime_snapshot_session_id(snapshot),
            "staleRuntimeRunCount": max(0, int(stale_count or 0)),
        },
    )


def _extend_chat_room_participant_model_issues(
    issues: list[dict[str, Any]],
    *,
    room: dict[str, Any],
    participant: dict[str, Any],
    model_refs: dict[str, dict[str, Any]],
    active_agent_ids: set[str],
) -> None:
    seen: set[tuple[str, str]] = set()
    reported_model_ids: set[str] = set()
    room_label = str(room.get("title") or room.get("roomId") or "-").strip() or "-"
    participant_id = str(participant.get("participantId") or "").strip()
    agent_id = str(participant.get("agentId") or "").strip()
    enabled = bool(participant.get("enabled", True))
    bindings = normalize_agent_llm_bindings(participant.get("llmBindings"))
    for slot_key, binding in bindings.items():
        if not isinstance(binding, dict):
            continue
        model_id = str(binding.get("modelId") or "").strip()
        if not model_id or model_id in model_refs:
            continue
        key = (slot_key, model_id)
        if key in seen:
            continue
        seen.add(key)
        reported_model_ids.add(model_id)
        slot_label = str(AGENT_LLM_SLOT_REFS.get(slot_key, {}).get("label") or slot_key).strip() or slot_key
        issues.append(
            {
                "severity": "blocking" if enabled and agent_id in active_agent_ids else "warning",
                "code": "unresolved_chat_room_participant_model_reference",
                "agentId": agent_id,
                "title": "群聊成员模型不存在",
                "detail": (
                    f"{room_label} 中成员 {agent_id or participant_id or '-'} "
                    f"缓存的 {slot_label} 模型库键 {model_id} 不存在或已被删除。"
                ),
                "source": "chat_room",
                "action": "在群聊或 Agent Center 中重新选择该成员的对话模型。",
            }
        )

    dialogue_model_id = str(participant.get("dialogueModelId") or "").strip()
    if (
        dialogue_model_id
        and dialogue_model_id not in model_refs
        and dialogue_model_id not in reported_model_ids
        and ("dialogueModelId", dialogue_model_id) not in seen
    ):
        issues.append(
            {
                "severity": "blocking" if enabled and agent_id in active_agent_ids else "warning",
                "code": "unresolved_chat_room_participant_model_reference",
                "agentId": agent_id,
                "title": "群聊成员模型不存在",
                "detail": (
                    f"{room_label} 中成员 {agent_id or participant_id or '-'} "
                    f"缓存的 dialogueModelId 模型库键 {dialogue_model_id} 不存在或已被删除。"
                ),
                "source": "chat_room",
                "action": "在群聊或 Agent Center 中重新选择该成员的对话模型。",
            }
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
        return {"modelOptions": []}


def _safe_chat_rooms_for_agents(agents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    try:
        return _safe_chat_rooms(agents=agents)
    except TypeError as exc:
        if "unexpected keyword argument" not in str(exc):
            raise
        return _safe_chat_rooms()


def _safe_chat_rooms(*, agents: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    try:
        from . import team_service

        team_service.repair_archived_team_chat_rooms()
        agent_refs = _agent_refs_by_id(agents or [])
        agents_by_session_id = _agent_refs_by_direct_session_id(agents or [])
        return [
            _compact_chat_room_for_workspace(
                room,
                agent_refs=agent_refs,
                agents_by_session_id=agents_by_session_id,
            )
            for room in chat_room_service.list_chat_rooms_compact()
        ]
    except Exception as exc:
        _record_workspace_error("agent_config.chat_rooms.load_failed", exc)
        return []


def _safe_teams() -> list[dict[str, Any]]:
    try:
        from . import team_service

        return list(team_service.list_team_graph_references(include_archived=True).get("teams") or [])
    except Exception as exc:
        _record_workspace_error("agent_config.teams.load_failed", exc)
        return []


def _compact_chat_room_for_workspace(
    room: dict[str, Any],
    *,
    agent_refs: dict[str, dict[str, Any]] | None = None,
    agents_by_session_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    participants = [item for item in list(room.get("participants") or []) if isinstance(item, dict)]
    return {
        "roomId": str(room.get("roomId") or "").strip(),
        "title": str(room.get("title") or "").strip(),
        "mode": str(room.get("mode") or "").strip(),
        "status": str(room.get("status") or "").strip(),
        "activeRoundId": str(room.get("activeRoundId") or "").strip(),
        "agentIds": [
            str(participant.get("agentId") or "").strip()
            for participant in participants
            if str(participant.get("agentId") or "").strip()
        ],
        "participants": [
            _compact_chat_room_participant_for_workspace(
                participant,
                agent_refs=agent_refs,
                agents_by_session_id=agents_by_session_id,
            )
            for participant in participants
        ],
        "participantCount": len(participants),
        "roundCount": len(list(room.get("rounds") or [])),
        "updatedAt": str(room.get("updatedAt") or "").strip(),
    }


def _compact_chat_room_participant_for_workspace(
    participant: dict[str, Any],
    *,
    agent_refs: dict[str, dict[str, Any]] | None = None,
    agents_by_session_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    agent = _workspace_participant_agent(
        participant,
        agent_refs=agent_refs,
        agents_by_session_id=agents_by_session_id,
    )
    llm_bindings = participant.get("llmBindings") if isinstance(participant.get("llmBindings"), dict) else {}
    if agent:
        llm_bindings = normalize_agent_llm_bindings(agent.get("llmBindings"))
    return {
        "participantId": str(participant.get("participantId") or "").strip(),
        "sessionId": str(participant.get("sessionId") or "").strip(),
        "agentId": str((agent or {}).get("agentId") or participant.get("agentId") or "").strip(),
        "agentCode": str((agent or {}).get("agentCode") or participant.get("agentCode") or "").strip(),
        "displayName": str(participant.get("displayName") or "").strip(),
        "enabled": bool(participant.get("enabled", True)),
        "dialogueModelId": str(agent_dialogue_model_id(agent) if agent else participant.get("dialogueModelId") or "").strip(),
        "llmBindings": llm_bindings,
    }


def _agent_refs_by_id(agents: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(agent.get("agentId") or "").strip(): agent
        for agent in agents
        if isinstance(agent, dict) and str(agent.get("agentId") or "").strip()
    }


def _agent_refs_by_direct_session_id(agents: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(agent.get("directSessionId") or "").strip(): agent
        for agent in agents
        if isinstance(agent, dict) and str(agent.get("directSessionId") or "").strip()
    }


def _workspace_participant_agent(
    participant: dict[str, Any],
    *,
    agent_refs: dict[str, dict[str, Any]] | None = None,
    agents_by_session_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    agent_id = str(participant.get("agentId") or "").strip()
    if agent_id and agent_refs:
        agent = agent_refs.get(agent_id)
        if isinstance(agent, dict):
            return agent
    session_ids = {
        str(participant.get("sessionId") or "").strip(),
        str(participant.get("directSessionId") or "").strip(),
    }
    session_ids.discard("")
    if agents_by_session_id:
        for session_id in session_ids:
            agent = agents_by_session_id.get(session_id)
            if isinstance(agent, dict):
                return agent
    return None


def _safe_policy_options(*, agents: list[dict[str, Any]] | None = None) -> dict[str, list[dict[str, Any]]]:
    try:
        if agents is not None:
            return build_agent_policy_options(agents=agents)
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
        supports_reasoning_effort = model_supports_gpt_reasoning_effort(
            model=option.get("model"),
            provider_kind=provider_kind,
            transport=option.get("transport"),
            compat_mode=provider.get("compat_mode"),
            provider_api=option.get("resolved_provider_api") or option.get("provider_api") or provider.get("api"),
        )
        choice = {
            "modelId": model_id,
            "label": str(option.get("label") or option.get("model") or model_id).strip() or model_id,
            "model": str(option.get("model") or "").strip(),
            "contextWindow": int(option.get("contextWindow") or 0),
            "providerKind": provider_kind,
            "transport": str(option.get("transport") or "").strip(),
            "providerBaseUrl": str(provider.get("base_url") or "").strip(),
            "source": str(option.get("source") or "").strip(),
            "apiKeyEnv": str(option.get("api_key_env") or "").strip(),
            "apiKeyConfigured": api_key_configured,
            "apiKeyState": str(option.get("api_key_state") or "").strip(),
            "requiresApiKey": requires_api_key,
            "missingApiKey": requires_api_key and not api_key_configured,
            "supportsImageInput": option.get("supports_image_input"),
            "supportsReasoningEffort": supports_reasoning_effort,
            "reasoningEffortValues": list(GPT_REASONING_EFFORT_VALUES) if supports_reasoning_effort else [],
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


def _unique_string_list(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _join_nonempty(values: Iterable[str], *, separator: str) -> str:
    return separator.join(str(value or "").strip() for value in values if str(value or "").strip())


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _workspace_cache_key(*, include_runtime: bool) -> tuple[Any, ...]:
    return (
        SCHEMA_VERSION,
        bool(include_runtime),
        _path_signature(registry_path),
        _path_signature(mode_binding_path),
        _path_signature(prompt_template_path),
    )


def _path_signature(path_func: Any) -> tuple[str, int, int]:
    try:
        raw_path = path_func() if callable(path_func) else path_func
        stat = raw_path.stat()
        return (raw_path.as_posix(), int(stat.st_mtime_ns), int(stat.st_size))
    except Exception:
        try:
            raw_path = path_func() if callable(path_func) else path_func
            return (raw_path.as_posix(), 0, -1)
        except Exception:
            return ("", 0, -1)


def _with_cache_diagnostics(
    payload: dict[str, Any],
    *,
    enabled: bool,
    hit: bool,
    wait_ms: float,
    age_ms: float,
) -> dict[str, Any]:
    result = copy.deepcopy(payload)
    diagnostics = result.get("diagnostics") if isinstance(result.get("diagnostics"), dict) else {}
    cache = diagnostics.get("cache") if isinstance(diagnostics.get("cache"), dict) else {}
    diagnostics["cache"] = {
        **cache,
        "enabled": enabled,
        "hit": hit,
        "waitMs": wait_ms,
        "ageMs": age_ms,
        "ttlSeconds": WORKSPACE_CACHE_TTL_SECONDS,
    }
    result["diagnostics"] = diagnostics
    return result


def _relative_path(path_func: Any) -> str:
    try:
        path = path_func() if callable(path_func) else path_func
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
    issues: list[dict[str, Any]] | None = None,
) -> None:
    health_log_summary = _health_issue_log_summary(issues or [])
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
                "blockingIssueCount": summary.get("blockingIssueCount", 0),
                "warningIssueCount": summary.get("warningIssueCount", 0),
                **health_log_summary,
                "timingsMs": dict(timings or {}),
                "loadModes": dict(load_modes or {}),
            },
            lifecycle=False,
        )
    except Exception:
        return


def _health_issue_log_summary(issues: list[dict[str, Any]]) -> dict[str, Any]:
    severity_counts: dict[str, int] = {}
    code_counts: dict[str, int] = {}
    affected_agent_ids: list[str] = []
    blocking_agent_ids: list[str] = []
    warning_agent_ids: list[str] = []
    samples: list[dict[str, str]] = []

    for issue in issues:
        if not isinstance(issue, dict):
            continue
        severity = str(issue.get("severity") or "unknown").strip() or "unknown"
        code = str(issue.get("code") or "unknown").strip() or "unknown"
        agent_id = str(issue.get("agentId") or "").strip()
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
        code_counts[code] = code_counts.get(code, 0) + 1
        if agent_id:
            _append_unique_limited(affected_agent_ids, agent_id, HEALTH_LOG_AGENT_LIMIT)
            if severity == "blocking":
                _append_unique_limited(blocking_agent_ids, agent_id, HEALTH_LOG_AGENT_LIMIT)
            elif severity == "warning":
                _append_unique_limited(warning_agent_ids, agent_id, HEALTH_LOG_AGENT_LIMIT)
        if len(samples) < HEALTH_LOG_SAMPLE_LIMIT:
            sample = {
                "severity": severity,
                "code": code,
            }
            if agent_id:
                sample["agentId"] = agent_id
            source = str(issue.get("source") or "").strip()
            if source:
                sample["source"] = source
            title = str(issue.get("title") or "").strip()
            if title:
                sample["title"] = title
            samples.append(sample)

    top_codes = sorted(code_counts.items(), key=lambda item: (-item[1], item[0]))[:HEALTH_LOG_CODE_LIMIT]
    return {
        "healthIssueSeverityCounts": dict(sorted(severity_counts.items())),
        "healthIssueTopCodes": [{"code": code, "count": count} for code, count in top_codes],
        "healthIssueAffectedAgentIds": affected_agent_ids,
        "healthIssueBlockingAgentIds": blocking_agent_ids,
        "healthIssueWarningAgentIds": warning_agent_ids,
        "healthIssueSamples": samples,
    }


def _append_unique_limited(values: list[str], value: str, limit: int) -> None:
    if len(values) >= limit or value in values:
        return
    values.append(value)


def _record_model_reference_resolution(issues: list[dict[str, Any]]) -> None:
    unresolved = [
        issue
        for issue in issues
        if str(issue.get("code") or "").strip().startswith("unresolved_model_reference")
        or str(issue.get("code") or "").strip() == "unresolved_chat_room_participant_model_reference"
    ]
    unresolved_codes = _dedupe_string_values(str(issue.get("code") or "").strip() for issue in unresolved)
    unresolved_agent_ids = _dedupe_string_values(str(issue.get("agentId") or "").strip() for issue in unresolved)
    unresolved_model_ids = _dedupe_unresolved_model_ids(unresolved)
    try:
        record_runtime_scene_event(
            "agent_config",
            "model_binding",
            "agent_config.model_references.resolved" if not unresolved else "agent_config.model_references.unresolved",
            message=(
                "Agent LLM binding model references are resolved."
                if not unresolved
                else "Agent LLM binding model references still contain unresolved model ids."
            ),
            level="info" if not unresolved else "warning",
            outcome="resolved" if not unresolved else "observed",
            fields={
                "unresolvedCount": len(unresolved),
                "unresolvedCodeCount": len(unresolved_codes),
                "unresolvedAgentCount": len(unresolved_agent_ids),
                "unresolvedModelCount": len(unresolved_model_ids),
                "unresolvedCodes": unresolved_codes[:20],
                "unresolvedAgentIds": unresolved_agent_ids[:20],
                "unresolvedModelIds": unresolved_model_ids[:20],
            },
            lifecycle=False,
        )
    except Exception:
        return


def _dedupe_unresolved_model_ids(issues: list[dict[str, Any]]) -> list[str]:
    values: list[str] = []
    for issue in issues:
        detail = str(issue.get("detail") or "")
        marker = "模型库键 "
        if marker not in detail:
            continue
        tail = detail.split(marker, 1)[1]
        model_id = tail.split(" ", 1)[0].strip(" 。.")
        if model_id:
            values.append(model_id)
    return _dedupe_string_values(values)


def _dedupe_string_values(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


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
