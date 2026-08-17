"""Shared Agent catalog operations for HTTP routes and governed tools."""

from __future__ import annotations

from typing import Any

from core.web.services import agent_config_change_service
from core.web.services import agent_directory_service
from core.web.services import session_service
from core.web.services.agent_config_workspace_service import invalidate_agent_config_workspace_cache
from core.web.services.agent_directory_service import (
    AgentDirectoryError,
    CONVERSATION_INDEX_KIND_PERSONAL_AGENT,
    get_agent,
    update_agent_avatar,
    update_agent_instance,
)


def validate_agent_create_request(
    *,
    display_name: str,
    llm_bindings: dict[str, Any],
    primary_mode: str,
    role_key: str,
    prompt_template_id: str,
    persona_profile: dict[str, Any],
    task_profile: dict[str, Any],
    tool_policy: dict[str, Any],
) -> None:
    missing: list[str] = []
    normalized_primary_mode = str(primary_mode or "").strip()
    is_work_session = normalized_primary_mode in {"", "chat"}
    if not str(display_name or "").strip():
        missing.append("功能名")
    if not agent_directory_service.agent_dialogue_model_id({"llmBindings": llm_bindings}):
        missing.append("对话模型")
    if not normalized_primary_mode:
        missing.append("使用位置")
    if not is_work_session and not str(role_key or "").strip():
        missing.append("角色键")
    if not str(prompt_template_id or "").strip():
        missing.append("提示词")
    if not is_work_session and not agent_directory_service.agent_persona_profile_has_content(persona_profile):
        missing.append("人物档案")
    if not is_work_session and not agent_directory_service.agent_task_profile_has_content(task_profile):
        missing.append("任务档案")
    allowed_tools = tool_policy.get("allowedTools") if isinstance(tool_policy, dict) else []
    if not is_work_session and (
        not isinstance(allowed_tools, list)
        or not any(str(item or "").strip() for item in allowed_tools)
    ):
        missing.append("工具包")
    if missing:
        raise AgentDirectoryError("Agent 创建信息不完整，请补齐：" + "、".join(missing) + "。")


def create_agent_from_catalog_request(
    *,
    display_name: str,
    llm_bindings: dict[str, Any] | None = None,
    primary_mode: str = "",
    role_key: str = "",
    prompt_template_id: str = "",
    context_compression_policy: dict[str, Any] | None = None,
    tool_policy: dict[str, Any] | None = None,
    persona_profile: dict[str, Any] | None = None,
    task_profile: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    avatar_image_path: str = "",
    source: str = "api_agents",
) -> dict[str, Any]:
    normalized_display_name = str(display_name or "").strip()
    normalized_llm_bindings = agent_directory_service.normalize_agent_llm_bindings(llm_bindings or {})
    normalized_persona_profile = dict(persona_profile or {})
    normalized_task_profile = dict(task_profile or {})
    normalized_tool_policy = dict(tool_policy or {})
    normalized_metadata = dict(metadata or {})

    validate_agent_create_request(
        display_name=normalized_display_name,
        llm_bindings=normalized_llm_bindings,
        primary_mode=primary_mode,
        role_key=role_key,
        prompt_template_id=prompt_template_id,
        persona_profile=normalized_persona_profile,
        task_profile=normalized_task_profile,
        tool_policy=normalized_tool_policy,
    )

    session = session_service.create_chat_session(
        title=normalized_display_name,
        llm_bindings=normalized_llm_bindings,
        created_by=source,
        conversation_index_kind=CONVERSATION_INDEX_KIND_PERSONAL_AGENT,
    )
    agent_id = str(session.get("agentId") or "").strip()
    agent = get_agent(agent_id) if agent_id else None
    if not agent:
        raise AgentDirectoryError("Agent was not created for the direct session.")

    if normalized_metadata:
        agent = update_agent_instance(agent_id, metadata=normalized_metadata)
    if primary_mode or role_key or prompt_template_id or context_compression_policy:
        runtime_policy_updates: dict[str, Any] = {}
        if context_compression_policy:
            runtime_policy_updates["context_compression_policy"] = context_compression_policy
        agent = update_agent_instance(
            agent_id,
            llm_bindings=normalized_llm_bindings,
            primary_mode=primary_mode or None,
            role_key=role_key or None,
            prompt_template_id=prompt_template_id or None,
            **runtime_policy_updates,
        )
    if normalized_persona_profile:
        agent = update_agent_instance(agent_id, persona_profile=normalized_persona_profile)
    if normalized_task_profile:
        agent = update_agent_instance(agent_id, task_profile=normalized_task_profile)
    if normalized_tool_policy:
        agent = update_agent_instance(agent_id, tool_policy=normalized_tool_policy)

    avatar_path = str(avatar_image_path or "").strip()
    if avatar_path:
        agent = update_agent_avatar(agent_id, avatar_image_path=avatar_path)
    invalidate_agent_config_workspace_cache()
    return agent


_AGENT_UPDATE_FIELD_MAP = {
    "displayName": "display_name",
    "llmBindings": "llm_bindings",
    "primaryMode": "primary_mode",
    "roleKey": "role_key",
    "promptTemplateId": "prompt_template_id",
    "toolPolicyId": "tool_policy_id",
    "memoryPolicyId": "memory_policy_id",
    "toolPolicy": "tool_policy",
    "memoryPolicy": "memory_policy",
    "contextCompressionPolicy": "context_compression_policy",
    "delegationPolicy": "delegation_policy",
    "supervisionPolicy": "supervision_policy",
    "reasoningEffortBySlot": "reasoning_effort_by_slot",
    "permissionPreset": "permission_preset",
    "personaProfile": "persona_profile",
    "taskProfile": "task_profile",
    "metadata": "metadata",
}


def update_agent_from_catalog_request(
    agent_id: str,
    *,
    updates: dict[str, Any],
    expected_updated_at: str = "",
    expected_config_revision: int | None = None,
    source_draft_id: str = "",
    source: str = "agent_update_tool",
) -> dict[str, Any]:
    """Update non-lifecycle Agent configuration through the authoritative directory service."""

    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        raise AgentDirectoryError("Agent id is required.")
    if not isinstance(updates, dict) or not updates:
        raise AgentDirectoryError("At least one Agent update field is required.")

    unknown_fields = sorted(set(updates).difference(_AGENT_UPDATE_FIELD_MAP))
    if unknown_fields:
        if "status" in unknown_fields:
            raise AgentDirectoryError("Agent lifecycle status must use agent_archive_tool; status is not accepted here.")
        raise AgentDirectoryError("Unsupported Agent update fields: " + ", ".join(unknown_fields))

    current = get_agent(normalized_agent_id, include_archived=True)
    if current is None:
        raise agent_directory_service.AgentNotFoundError(f"Agent not found: {normalized_agent_id}")

    update_kwargs = {
        _AGENT_UPDATE_FIELD_MAP[field]: value
        for field, value in updates.items()
    }
    updated = update_agent_instance(
        normalized_agent_id,
        **update_kwargs,
        expected_updated_at=str(expected_updated_at or "").strip(),
        expected_config_revision=expected_config_revision,
    )
    revision = agent_config_change_service.record_agent_config_revision(
        normalized_agent_id,
        before=current,
        after=updated,
        source=str(source or "agent_update_tool").strip() or "agent_update_tool",
        source_draft_id=str(source_draft_id or "").strip(),
    )
    invalidate_agent_config_workspace_cache()
    return {
        **updated,
        **({"publishedConfigChange": revision} if revision else {}),
    }
