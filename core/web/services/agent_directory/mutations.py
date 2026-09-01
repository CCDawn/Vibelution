"""Agent directory create/update/avatar mutation helpers.

Claim scope: create/update agent instance, LLM binding replace, avatar
store/resolve, and related record events.

Serializer wrappers for create/update stay on the facade.

Late-bound facade keeps monkeypatches stable.
"""

from __future__ import annotations

import base64
import binascii
import re
import secrets
import time
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

from ..agent_config_authority import (
    materialize_agent_config_identity,
    normalize_permission_preset,
)
from .avatar_model_defaults import model_default_avatar_filename

# Local default for signature evaluation (facade remains SSOT).
DEFAULT_AGENT_PRIMARY_MODE = "chat"


def _service():
    from core.web.services import agent_directory_service

    return agent_directory_service


def update_agent_instance(
    agent_id: str,
    *,
    display_name: str | None = None,
    direct_session_id: str | None = None,
    llm_bindings: dict[str, Any] | None = None,
    primary_mode: str | None = None,
    role_key: str | None = None,
    prompt_template_id: str | None = None,
    tool_policy_id: str | None = None,
    memory_policy_id: str | None = None,
    tool_policy: dict[str, Any] | None = None,
    memory_policy: dict[str, Any] | None = None,
    context_compression_policy: dict[str, Any] | None = None,
    delegation_policy: dict[str, Any] | None = None,
    supervision_policy: dict[str, Any] | None = None,
    reasoning_effort_by_slot: dict[str, Any] | None = None,
    permission_preset: str | None = None,
    persona_profile: dict[str, Any] | None = None,
    task_profile: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    status: str | None = None,
    preserve_generated_display_name: bool = False,
    expected_updated_at: str = "",
    expected_config_revision: int | None = None,
    expected_tool_policy_fingerprint: str = "",
    confirm_shared_tool_policy: bool = False,
) -> dict[str, Any]:
    s = _service()
    updated_tool_policy: dict[str, Any] | None = None
    updated_memory_policy: dict[str, Any] | None = None
    updated_delegation_policy: dict[str, Any] | None = None
    updated_supervision_policy: dict[str, Any] | None = None
    updated_persona_profile: dict[str, Any] | None = None
    updated_task_profile: dict[str, Any] | None = None
    with s._STATE_LOCK:
        state = s.load_state()
        agent = s._find_agent(state, agent_id)
        if agent is None:
            raise s.AgentNotFoundError(f"Agent not found: {agent_id}")
        try:
            current_config_revision = max(
                0,
                int(agent.get("configRevision") or 0),
            )
        except (TypeError, ValueError):
            current_config_revision = 0
        try:
            current_config_schema_version = max(
                0,
                int(agent.get("configSchemaVersion") or 0),
            )
        except (TypeError, ValueError):
            current_config_schema_version = 0
        legacy_config_snapshot = (
            current_config_revision == 0
            and current_config_schema_version < 2
        )
        if (
            expected_config_revision is not None
            and current_config_revision != int(expected_config_revision)
        ):
            raise s.AgentStateConflictError(
                "Agent configuration revision changed. Refresh and retry."
            )
        expected_agent_revision = str(expected_updated_at or "").strip()
        if expected_agent_revision and str(agent.get("updatedAt") or "").strip() != expected_agent_revision:
            raise s.AgentStateConflictError("Agent configuration changed after this editor was opened. Refresh and retry.")
        materialize_agent_config_identity(agent)
        previous_config_hash = str(agent.get("configHash") or "").strip()
        if display_name is not None:
            title = s.trim_lines(display_name or "", max_lines=1).strip()
            if not title:
                raise s.AgentDirectoryError("Agent display name is required.")
            metadata_payload = dict(agent.get("metadata") or {})
            if preserve_generated_display_name:
                current_display_name = str(agent.get("displayName") or "").strip()
                metadata_payload = s._with_functional_display_name(metadata_payload, title)
                if not current_display_name or s._display_name_needs_responsibility_repair(current_display_name, {**agent, "metadata": metadata_payload}):
                    agent["displayName"] = s._agent_public_display_name(
                        title,
                        existing_agents=state.get("agents") or [],
                        agent_id=str(agent.get("agentId") or ""),
                        metadata=metadata_payload,
                    )
                    metadata_payload = s._mark_display_name_responsibility(metadata_payload, force=True)
                else:
                    metadata_payload = s._mark_display_name_responsibility(metadata_payload)
            else:
                agent["displayName"] = title[:120].rstrip()
                metadata_payload["functionalDisplayName"] = agent["displayName"]
                metadata_payload["displayNameSource"] = "user"
            agent["metadata"] = metadata_payload
        if llm_bindings is not None:
            agent["llmBindings"] = s.normalize_agent_llm_bindings(llm_bindings)
        if direct_session_id is not None:
            normalized_direct_session_id = str(direct_session_id or "").strip()
            s._ensure_active_direct_session_available(
                state,
                normalized_direct_session_id,
                agent_id=str(agent.get("agentId") or "").strip(),
            )
            agent["directSessionId"] = normalized_direct_session_id
        if primary_mode is not None:
            agent["primaryMode"] = s._normalize_primary_mode(primary_mode)
        if role_key is not None:
            agent["roleKey"] = s._normalize_role_key(role_key)
        if prompt_template_id is not None:
            agent["promptTemplateId"] = s._normalize_prompt_template_id(prompt_template_id)
        if metadata is not None:
            current = dict(agent.get("metadata") or {})
            current.update(dict(metadata or {}))
            agent["metadata"] = current
        if reasoning_effort_by_slot is not None:
            metadata_payload = dict(agent.get("metadata") or {})
            metadata_payload["llmReasoningEffort"] = {
                str(slot or "").strip(): str(effort or "").strip().lower()
                for slot, effort in dict(reasoning_effort_by_slot or {}).items()
                if str(slot or "").strip() and str(effort or "").strip()
            }
            agent["metadata"] = metadata_payload
        if permission_preset is not None:
            try:
                agent["permissionPreset"] = normalize_permission_preset(
                    permission_preset,
                    strict=True,
                )
            except ValueError as exc:
                raise s.AgentDirectoryError(str(exc)) from exc
        if status is not None:
            normalized_status = str(status or "").strip() or "active"
            if normalized_status not in {"active", "archived"}:
                raise s.AgentDirectoryError("Unsupported AgentInstance status.")
            if normalized_status == "archived" and s._agent_archive_protected(agent):
                raise s.AgentDirectoryError("Protected core Agent cannot be archived.")
            agent["status"] = normalized_status
        if tool_policy_id is not None:
            normalized_policy_id = str(tool_policy_id or "").strip() or s.DEFAULT_TOOL_POLICY_ID
            policies = s._tool_policies(state)
            if normalized_policy_id not in policies:
                raise s.AgentDirectoryError(f"Unknown ToolPolicy: {normalized_policy_id}")
            agent["toolPolicyId"] = normalized_policy_id
            updated_tool_policy = s.normalize_tool_policy(
                policies[normalized_policy_id],
                normalized_policy_id,
            )
            agent["toolPolicy"] = updated_tool_policy
        if memory_policy_id is not None:
            normalized_memory_policy_id = str(memory_policy_id or "").strip()
            policies = s._memory_policies(state)
            if not normalized_memory_policy_id or normalized_memory_policy_id not in policies:
                raise s.AgentDirectoryError(f"Unknown MemoryPolicy: {normalized_memory_policy_id}")
            agent["memoryPolicyId"] = normalized_memory_policy_id
            workspace_path = str(
                agent.get("workspacePath")
                or s._agent_workspace_relative_path(str(agent["agentId"]))
            ).strip()
            updated_memory_policy = s.normalize_memory_policy(
                policies[normalized_memory_policy_id],
                normalized_memory_policy_id,
                workspace_path,
            )
            agent["memoryPolicy"] = updated_memory_policy
        if tool_policy is not None:
            policy_id = str(agent.get("toolPolicyId") or s.DEFAULT_TOOL_POLICY_ID).strip() or s.DEFAULT_TOOL_POLICY_ID
            if policy_id == s.DEFAULT_TOOL_POLICY_ID:
                policy_id = f"tool-{agent['agentId']}"
                agent["toolPolicyId"] = policy_id
            current_tool_policy = s.normalize_tool_policy(
                agent.get("toolPolicy")
                if isinstance(agent.get("toolPolicy"), dict)
                else s.default_tool_policy(policy_id),
                policy_id,
            )
            expected_policy_fingerprint = str(expected_tool_policy_fingerprint or "").strip()
            if expected_policy_fingerprint and s.tool_policy_fingerprint(current_tool_policy) != expected_policy_fingerprint:
                raise s.AgentStateConflictError("ToolPolicy changed after this editor was opened. Refresh and retry.")
            updated_tool_policy = s.normalize_tool_policy(
                {**s.default_tool_policy(policy_id), **dict(tool_policy or {})},
                policy_id,
            )
            updated_tool_policy["policyVersion"] = int(current_tool_policy.get("policyVersion") or 1) + 1
            agent["toolPolicy"] = updated_tool_policy
        if memory_policy is not None:
            policy_id = str(agent.get("memoryPolicyId") or "").strip() or f"memory-{agent['agentId']}"
            if policy_id == s.DEFAULT_MEMORY_POLICY_ID:
                policy_id = f"memory-{agent['agentId']}"
                agent["memoryPolicyId"] = policy_id
            workspace_path = s._agent_workspace_relative_path(str(agent["agentId"]))
            agent["workspacePath"] = workspace_path
            s._ensure_agent_workspace(workspace_path)
            base_policy = (
                agent.get("memoryPolicy")
                if isinstance(agent.get("memoryPolicy"), dict)
                else s.default_memory_policy(policy_id, workspace_path)
            )
            updated_memory_policy = s.normalize_memory_policy(
                {**base_policy, **dict(memory_policy or {})},
                policy_id,
                workspace_path,
            )
            agent["memoryPolicyId"] = policy_id
            agent["memoryPolicy"] = updated_memory_policy
        if context_compression_policy is not None:
            normalized_context_policy = s.normalize_agent_context_compression_policy(
                context_compression_policy
            )
            if normalized_context_policy.get("mode") != "custom":
                if not legacy_config_snapshot:
                    raise s.AgentDirectoryError(
                        "Agent context compression policy must be explicit."
                    )
                normalized_context_policy = (
                    s.materialize_agent_context_compression_policy(
                        normalized_context_policy,
                        creation_default=s._context_compression_base_policy_for_agents(),
                    )
                )
            agent["contextCompressionPolicy"] = normalized_context_policy
        if delegation_policy is not None:
            metadata_payload = dict(agent.get("metadata") or {})
            updated_delegation_policy = s.normalize_delegation_policy(delegation_policy)
            metadata_payload["delegationPolicy"] = updated_delegation_policy
            agent["metadata"] = metadata_payload
        if supervision_policy is not None:
            metadata_payload = dict(agent.get("metadata") or {})
            updated_supervision_policy = s.normalize_supervision_policy(supervision_policy)
            metadata_payload["supervisionPolicy"] = updated_supervision_policy
            agent["metadata"] = metadata_payload
        if persona_profile is not None:
            metadata_payload = dict(agent.get("metadata") or {})
            if s._is_profileless_session_agent(agent):
                metadata_payload.pop("personaProfile", None)
            else:
                updated_persona_profile = s.normalize_persona_profile(persona_profile)
                metadata_payload["personaProfile"] = updated_persona_profile
                if s._persona_profile_has_content(updated_persona_profile):
                    metadata_payload.pop("personaProfileDefaultsDisabled", None)
                else:
                    metadata_payload["personaProfileDefaultsDisabled"] = True
            agent["metadata"] = metadata_payload
        if task_profile is not None:
            metadata_payload = dict(agent.get("metadata") or {})
            if s._is_profileless_session_agent(agent):
                metadata_payload.pop("taskProfile", None)
            else:
                updated_task_profile = s.normalize_task_profile(task_profile)
                metadata_payload["taskProfile"] = updated_task_profile
                if s._task_profile_has_content(updated_task_profile):
                    metadata_payload.pop("taskProfileDefaultsDisabled", None)
                else:
                    metadata_payload["taskProfileDefaultsDisabled"] = True
            agent["metadata"] = metadata_payload
        s._refresh_agent_onboarding_metadata(state, agent)
        s._ensure_agent_default_avatar(agent)
        materialize_agent_config_identity(
            agent,
            increment_if_changed=True,
            previous_hash=previous_config_hash,
        )
        agent["updatedAt"] = s.utc_now_iso()
        s.save_state(state)
    s._record_agent_event("agent.updated", agent)
    if updated_tool_policy is not None:
        s._record_agent_tool_policy_event(agent, updated_tool_policy)
    if updated_memory_policy is not None:
        s._record_agent_memory_policy_event(agent, updated_memory_policy)
    if updated_delegation_policy is not None:
        s._record_agent_delegation_policy_event(agent, updated_delegation_policy)
    if updated_supervision_policy is not None:
        s._record_agent_supervision_policy_event(agent, updated_supervision_policy)
    if updated_persona_profile is not None:
        s._record_agent_persona_profile_event(agent, updated_persona_profile)
    if updated_task_profile is not None:
        s._record_agent_task_profile_event(agent, updated_task_profile)
    return s._agent_to_api(agent)


def create_agent_instance(
    *,
    display_name: str = "",
    llm_bindings: dict[str, Any] | None = None,
    primary_mode: str = DEFAULT_AGENT_PRIMARY_MODE,
    role_key: str = "",
    prompt_template_id: str = "",
    direct_session_id: str = "",
    workspace_path: str = "",
    created_by: str = "user",
    metadata: dict[str, Any] | None = None,
    context_compression_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    s = _service()
    with s._STATE_LOCK:
        state = s.repair_agent_directory()
        existing_ids = {
            str(item.get("agentId") or "").strip()
            for item in state.get("agents") or []
            if isinstance(item, dict)
        }
        now = s.utc_now_iso()
        agent_id = s._new_agent_id(existing_ids)
        title = s.trim_lines(display_name or "", max_lines=1).strip() or "Agent"
        metadata_payload = dict(metadata or {})
        public_name = s._agent_public_display_name(
            title,
            existing_agents=state.get("agents") or [],
            agent_id=agent_id,
            metadata=metadata_payload,
        )
        normalized_llm_bindings = s.normalize_agent_llm_bindings(llm_bindings)
        normalized_primary_mode = s._normalize_primary_mode(primary_mode)
        normalized_role_key = s._normalize_role_key(role_key)
        normalized_prompt_template_id = s._normalize_prompt_template_id(prompt_template_id)
        if not normalized_prompt_template_id:
            normalized_prompt_template_id = s._infer_agent_prompt_template_id(
                {
                    "primaryMode": normalized_primary_mode,
                    "roleKey": normalized_role_key,
                    "metadata": metadata_payload,
                    "createdBy": str(created_by or "user").strip() or "user",
                }
            )
        normalized_context_compression_policy = s.materialize_agent_context_compression_policy(
            context_compression_policy,
            creation_default=s.DEFAULT_AGENT_CONTEXT_COMPRESSION_CREATION_POLICY,
        )
        normalized_direct_session_id = str(direct_session_id or "").strip()
        s._ensure_active_direct_session_available(
            state,
            normalized_direct_session_id,
            agent_id=agent_id,
        )
        agent_workspace = workspace_path or s._agent_workspace_relative_path(agent_id)
        s._ensure_agent_workspace(agent_workspace)
        tool_policy_id = s._default_tool_policy_id_for_agent(agent_id, normalized_primary_mode)
        memory_policy_id = f"memory-{agent_id}"
        tool_policy = s._default_tool_policy_for_agent(
            tool_policy_id,
            normalized_primary_mode,
            role_key=normalized_role_key,
        )
        memory_policy = s.default_memory_policy(memory_policy_id, agent_workspace)
        metadata_payload["delegationPolicy"] = s.normalize_delegation_policy(
            metadata_payload.get("delegationPolicy")
            if isinstance(metadata_payload.get("delegationPolicy"), dict)
            else {}
        )
        metadata_payload["supervisionPolicy"] = s.normalize_supervision_policy(
            metadata_payload.get("supervisionPolicy")
            if isinstance(metadata_payload.get("supervisionPolicy"), dict)
            else {}
        )
        metadata_payload = s._with_agent_creation_spec(
            metadata_payload,
            created_by=str(created_by or "user").strip() or "user",
            display_name=title,
            llm_bindings=normalized_llm_bindings,
            primary_mode=normalized_primary_mode,
            role_key=normalized_role_key,
            prompt_template_id=normalized_prompt_template_id,
            tool_policy_id=tool_policy_id,
            tool_policy=tool_policy,
            memory_policy_id=memory_policy_id,
            memory_policy=memory_policy,
            created_at=now,
        )
        metadata_payload = s._mark_display_name_responsibility(
            s._with_functional_display_name(metadata_payload, title),
            force=True,
        )
        if not isinstance(metadata_payload.get("runtimeStatus"), dict):
            from core.runtime_status_flags import default_agent_runtime_status_policy

            metadata_payload["runtimeStatus"] = default_agent_runtime_status_policy()
        agent = {
            "agentId": agent_id,
            "agentCode": s._next_agent_code(state.get("agents") or []),
            "displayName": public_name,
            "kind": s.DEFAULT_AGENT_KIND,
            "primaryMode": normalized_primary_mode,
            "roleKey": normalized_role_key,
            "llmBindings": normalized_llm_bindings,
            "promptTemplateId": normalized_prompt_template_id,
            "directSessionId": normalized_direct_session_id,
            "workspacePath": agent_workspace,
            "toolPolicyId": tool_policy_id,
            "toolPolicy": tool_policy,
            "memoryPolicyId": memory_policy_id,
            "memoryPolicy": memory_policy,
            "contextCompressionPolicy": normalized_context_compression_policy,
            "permissionPreset": "request_approval",
            "createdBy": str(created_by or "user").strip() or "user",
            "status": "active",
            "metadata": metadata_payload,
            "createdAt": now,
            "updatedAt": now,
        }
        materialize_agent_config_identity(agent)
        s._ensure_agent_default_avatar(agent)
        tool_policies = s._tool_policies(state)
        tool_policies[tool_policy_id] = tool_policy
        state["toolPolicies"] = tool_policies
        policies = s._memory_policies(state)
        policies[memory_policy_id] = memory_policy
        state["agents"] = list(state.get("agents") or []) + [agent]
        state["memoryPolicies"] = policies
        s.save_state(state)
    s._record_agent_event("agent.created", agent, lifecycle=True)
    s._record_agent_territory_event("agent_territory.resolved", agent, outcome="created")
    return s._agent_to_api(agent)


def _with_agent_creation_spec(
    metadata: dict[str, Any],
    *,
    created_by: str,
    display_name: str,
    llm_bindings: dict[str, Any],
    primary_mode: str,
    role_key: str,
    prompt_template_id: str,
    tool_policy_id: str,
    memory_policy_id: str,
    tool_policy: dict[str, Any] | None = None,
    memory_policy: dict[str, Any] | None = None,
    created_at: str,
) -> dict[str, Any]:
    s = _service()
    payload = dict(metadata or {})
    persona_profile = s.normalize_persona_profile(payload.get("personaProfile") if isinstance(payload.get("personaProfile"), dict) else {})
    task_profile = s.normalize_task_profile(payload.get("taskProfile") if isinstance(payload.get("taskProfile"), dict) else {})
    is_work_session = s._is_session_agent_primary_mode(primary_mode)
    if is_work_session:
        payload.pop("personaProfile", None)
        payload.pop("taskProfile", None)
    else:
        payload["personaProfile"] = persona_profile
        payload["taskProfile"] = task_profile
    metadata_tool_policy = payload.get("toolPolicy") if isinstance(payload.get("toolPolicy"), dict) else {}
    effective_tool_policy = tool_policy if isinstance(tool_policy, dict) else metadata_tool_policy
    metadata_memory_policy = payload.get("memoryPolicy") if isinstance(payload.get("memoryPolicy"), dict) else {}
    effective_memory_policy = memory_policy if isinstance(memory_policy, dict) else metadata_memory_policy
    missing = s._agent_creation_missing_fields(
        display_name=display_name,
        llm_bindings=llm_bindings,
        primary_mode=primary_mode,
        role_key=role_key,
        prompt_template_id=prompt_template_id,
        persona_profile=persona_profile,
        task_profile=task_profile,
        tool_policy_id=tool_policy_id,
        tool_policy=effective_tool_policy,
        memory_policy_id=memory_policy_id,
        memory_policy=effective_memory_policy,
    )
    required_fields = [
        field
        for field in s.AGENT_CREATION_REQUIRED_FIELDS
        if not is_work_session or field not in {"roleKey", "personaProfile", "taskProfile"}
    ]
    payload["creationSpec"] = {
        "schemaVersion": 1,
        "source": str(created_by or "user").strip() or "user",
        "requiredFields": required_fields,
        "createdAt": created_at,
    }
    payload["onboardingStatus"] = "incomplete" if missing else "complete"
    payload["onboardingMissing"] = missing
    return payload


def store_agent_avatar_image(
    agent_id: str,
    *,
    filename: str,
    content_type: str,
    data_base64: str,
) -> dict[str, Any]:
    s = _service()
    with s._STATE_LOCK:
        state = s.load_state()
        agent = s._find_agent(state, agent_id)
        if agent is None:
            raise s.AgentNotFoundError(f"Agent not found: {agent_id}")
    normalized_type = str(content_type or "").split(";")[0].strip().lower()
    extension = s._AGENT_AVATAR_CONTENT_TYPE_EXTENSIONS.get(normalized_type)
    if not extension:
        raise s.AgentDirectoryError("Agent avatar only supports PNG, JPG, or WebP images.")
    payload = s._decode_agent_avatar_payload(data_base64)
    s._validate_agent_avatar_signature(payload, normalized_type)

    avatar_dir = _agent_custom_avatar_dir().resolve()
    avatar_dir.mkdir(parents=True, exist_ok=True)
    safe_stem = s._sanitize_avatar_stem(filename or agent_id)
    output_name = f"agent-avatar-{int(time.time())}-{secrets.token_hex(4)}-{safe_stem}{extension}"
    output_path = _agent_custom_avatar_file(output_name)
    output_path.write_bytes(payload)
    relative_path = str(s.AGENT_AVATAR_RELATIVE_DIR / output_name)
    updated = s.update_agent_avatar(agent_id, avatar_image_path=relative_path)
    s._record_agent_avatar_uploaded_event(updated, content_type=normalized_type, size_bytes=len(payload))
    return {
        "path": relative_path,
        "url": s.agent_avatar_image_url(relative_path),
        "contentType": normalized_type,
        "sizeBytes": len(payload),
        "agent": updated,
    }


def update_agent_avatar(
    agent_id: str,
    *,
    avatar_image_path: str = "",
    reset_to_default: bool = False,
) -> dict[str, Any]:
    s = _service()
    with s._STATE_LOCK:
        state = s.load_state()
        agent = s._find_agent(state, agent_id)
        if agent is None:
            raise s.AgentNotFoundError(f"Agent not found: {agent_id}")
        metadata = dict(agent.get("metadata") or {})
        if reset_to_default:
            default_path = s._default_agent_avatar_path(agent)
            if not default_path:
                raise s.AgentDirectoryError("No default Agent avatar is available.")
            metadata["avatarImagePath"] = default_path
            metadata["avatarImageSource"] = "default"
        else:
            filename = s.agent_avatar_filename(avatar_image_path)
            if not filename:
                raise s.AgentDirectoryError("Invalid Agent avatar image path.")
            path = s.resolve_agent_avatar_file(filename)
            if not path.exists() or not path.is_file():
                raise s.AgentDirectoryError("Agent avatar image does not exist.")
            metadata["avatarImagePath"] = str(s.AGENT_AVATAR_RELATIVE_DIR / filename)
            metadata["avatarImageSource"] = "custom"
        agent["metadata"] = metadata
        agent["updatedAt"] = s.utc_now_iso()
        s.save_state(state)
    s._record_agent_avatar_updated_event(agent)
    return s._agent_to_api(agent)


def replace_agent_llm_bindings_if_current(
    agent_id: str,
    *,
    expected_updated_at: str,
    llm_bindings: dict[str, Any],
    emit_event: bool = True,
) -> dict[str, Any]:
    """Replace one Agent's model bindings only while its revision is current."""
    s = _service()

    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        raise s.AgentNotFoundError("Agent not found.")
    expected_revision = str(expected_updated_at or "").strip()
    with s._STATE_LOCK:
        state = s.load_state()
        agent = s._find_agent(state, normalized_agent_id)
        if agent is None:
            raise s.AgentNotFoundError("Agent not found.")
        if str(agent.get("updatedAt") or "").strip() != expected_revision:
            raise s.AgentStateConflictError("Agent changed during model promotion.")
        agent["llmBindings"] = s.normalize_agent_llm_bindings(llm_bindings)
        s._ensure_agent_default_avatar(agent)
        agent["updatedAt"] = s.utc_now_iso()
        # Project before persisting so a projection failure cannot leave a write
        # whose revision the transaction participant never received.
        projected = s._agent_to_api(agent)
        s.save_state(state)
    if emit_event:
        s.record_agent_llm_binding_updated_event(projected)
    return projected


def _default_agent_avatar_filename(
    agent: dict[str, Any],
    *,
    available_avatar_filenames: list[str] | None = None,
) -> str:
    s = _service()
    if available_avatar_filenames is not None:
        available = list(available_avatar_filenames)
    else:
        available = s._available_agent_avatar_filenames()
    if not available:
        return ""
    model_default = model_default_avatar_filename(s.agent_dialogue_model_id(agent))
    if model_default in available:
        return model_default
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    # Exact field values beat substring table order for product fixed roles.
    exact_candidates = [
        str(agent.get("roleKey") or "").strip().lower(),
        str(metadata.get("supervisedRole") or "").strip().lower(),
        str(metadata.get("selfEvolutionRole") or "").strip().lower(),
        str(metadata.get("systemRole") or "").strip().lower(),
        str(metadata.get("researchOrgRole") or "").strip().lower(),
    ]
    for exact in exact_candidates:
        if not exact:
            continue
        for tokens, filenames in s.AGENT_AVATAR_ROLE_DEFAULTS:
            if len(tokens) == 1 and tokens[0] == exact:
                for filename in filenames:
                    if filename in available:
                        return filename
    key = s._agent_avatar_match_key(agent)
    for tokens, filenames in s.AGENT_AVATAR_ROLE_DEFAULTS:
        if all(token in key for token in tokens):
            for filename in filenames:
                if filename in available:
                    return filename
    fallback_pool = [filename for filename in s.AGENT_AVATAR_PRIMARY_DEFAULTS if filename in available]
    if not fallback_pool:
        fallback_pool = [filename for filename in s.AGENT_AVATAR_GENERATED_FALLBACKS if filename in available]
    if not fallback_pool:
        fallback_pool = [filename for filename in s.AGENT_AVATAR_FILENAMES if filename in available]
    if not fallback_pool:
        fallback_pool = available
    stable_key = s._normalize_agent_code(agent.get("agentCode")) or str(agent.get("agentId") or "")
    checksum = sum(ord(char) for char in stable_key)
    return fallback_pool[checksum % len(fallback_pool)]


def _record_agent_task_profile_event(agent: dict[str, Any], profile: dict[str, Any]) -> None:
    s = _service()
    try:
        normalized = s.normalize_task_profile(profile)
        s.record_runtime_scene_event(
            "agent_directory",
            "task_profile",
            "agent.task_profile.updated",
            message="Agent task profile was updated.",
            level="info",
            outcome="updated",
            fields={
                "agentId": str(agent.get("agentId") or "").strip(),
                "agentCode": s._normalize_agent_code(agent.get("agentCode")),
                "fieldCount": sum(1 for field in s.AGENT_TASK_PROFILE_FIELDS if normalized.get(field)),
                "taskTypeCount": len(list(normalized.get("taskTypes") or [])),
                "hasMission": bool(str(normalized.get("mission") or "").strip()),
                "hasSuccessCriteria": bool(str(normalized.get("successCriteria") or "").strip()),
                "source": "AgentDirectory",
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_agent_avatar_defaults_event(agents: list[dict[str, Any]]) -> None:
    s = _service()
    try:
        avatar_counts: dict[str, int] = {}
        for agent in agents:
            metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
            avatar_path = s._agent_avatar_path_from_metadata(metadata)
            if avatar_path:
                avatar_counts[avatar_path] = avatar_counts.get(avatar_path, 0) + 1
        s.record_runtime_scene_event(
            "agent_directory",
            "agent_avatar",
            "agent.avatar_defaults_assigned",
            message="Default Agent avatars were assigned from workspace/avatars.",
            level="info",
            outcome="repaired",
            fields={
                "assignedCount": len(agents),
                "avatarPaths": sorted(avatar_counts),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_agent_territory_event(event_code: str, agent: dict[str, Any], *, outcome: str = "observed", level: str = "info") -> None:
    s = _service()
    try:
        territory = s._agent_workspace_territory(agent)
        s.record_runtime_scene_event(
            "agent_directory",
            "territory",
            event_code,
            message=event_code,
            level=level,
            outcome=outcome,
            fields={
                "agentId": str(agent.get("agentId") or "").strip(),
                "agentCode": s._normalize_agent_code(agent.get("agentCode")),
                "privateRoot": str(territory.get("privateRoot") or "").strip(),
                "sharedRoot": str(territory.get("sharedRoot") or "").strip(),
                "defaultWriteScope": str(territory.get("defaultWriteScope") or "").strip(),
                "writeScopeCount": len(list(territory.get("writeScopes") or [])),
                "legacyWorkspace": bool(str(territory.get("legacyWorkspacePath") or "").strip()),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_agent_persona_profile_event(agent: dict[str, Any], profile: dict[str, Any]) -> None:
    s = _service()
    try:
        normalized = s.normalize_persona_profile(profile)
        s.record_runtime_scene_event(
            "agent_directory",
            "persona_profile",
            "agent.persona_profile.updated",
            message="Agent persona profile was updated.",
            level="info",
            outcome="updated",
            fields={
                "agentId": str(agent.get("agentId") or "").strip(),
                "agentCode": s._normalize_agent_code(agent.get("agentCode")),
                "fieldCount": sum(1 for field in s.AGENT_PERSONA_PROFILE_FIELDS if normalized.get(field)),
                "expertiseCount": len(list(normalized.get("expertise") or [])),
                "hasGender": bool(str(normalized.get("gender") or "").strip()),
                "hasAge": bool(str(normalized.get("age") or "").strip()),
                "source": "AgentDirectory",
            },
            lifecycle=True,
        )
    except Exception:
        return


def _ensure_agent_default_avatar(
    agent: dict[str, Any],
    *,
    available_avatar_filenames: list[str] | None = None,
) -> bool:
    s = _service()
    metadata = dict(agent.get("metadata") or {})
    current_path = s._agent_avatar_path_from_metadata(metadata)
    current_source = str(metadata.get("avatarImageSource") or metadata.get("agentAvatarImageSource") or "").strip()
    default_path = s._default_agent_avatar_path(
        agent,
        available_avatar_filenames=available_avatar_filenames,
    )
    if not default_path:
        return False
    # Operator/library ("custom") and any other non-default source are locked while
    # the file still resolves. Missing files fall through so ensure can recover.
    if current_path and current_source and current_source != "default":
        filename = s.agent_avatar_filename(current_path)
        if filename:
            try:
                path = s.resolve_agent_avatar_file(filename)
                if path.exists() and path.is_file():
                    return False
            except (FileNotFoundError, OSError, ValueError):
                pass
    if current_path == default_path and metadata.get("avatarImageSource") == "default":
        return False
    metadata["avatarImagePath"] = default_path
    metadata["avatarImageSource"] = "default"
    agent["metadata"] = metadata
    return True


def resolve_agent_avatar_path_for_projection(
    agent: dict[str, Any],
    *,
    available_avatar_filenames: list[str] | None = None,
) -> str:
    """Path for API projection: custom selection, else configured model logo."""
    s = _service()
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    current_path = s._agent_avatar_path_from_metadata(metadata if isinstance(metadata, dict) else {})
    current_source = str(metadata.get("avatarImageSource") or metadata.get("agentAvatarImageSource") or "").strip()
    if current_path and current_source != "default":
        return current_path
    return s._default_agent_avatar_path(
        agent,
        available_avatar_filenames=available_avatar_filenames,
    )


def _record_agent_event(event_code: str, agent: dict[str, Any], *, lifecycle: bool = False) -> None:
    s = _service()
    try:
        s.record_runtime_scene_event(
            "agent_directory",
            "agent",
            event_code,
            message=event_code,
            level="info",
            outcome="observed",
            fields={
                "agentId": str(agent.get("agentId") or "").strip(),
                "agentCode": s._normalize_agent_code(agent.get("agentCode")),
                "directSessionId": str(agent.get("directSessionId") or "").strip(),
                "primaryMode": s._normalize_primary_mode(agent.get("primaryMode")),
                "roleKey": s._normalize_role_key(agent.get("roleKey")),
                "promptTemplateId": s._normalize_prompt_template_id(agent.get("promptTemplateId")),
                "status": str(agent.get("status") or "").strip(),
            },
            lifecycle=lifecycle,
        )
    except Exception:
        return


def _record_agent_avatar_updated_event(agent: dict[str, Any]) -> None:
    s = _service()
    try:
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        s.record_runtime_scene_event(
            "agent_directory",
            "agent_avatar",
            "agent.avatar_updated",
            message="Agent avatar was updated.",
            level="info",
            outcome="updated",
            fields={
                "agentId": str(agent.get("agentId") or "").strip(),
                "agentCode": s._normalize_agent_code(agent.get("agentCode")),
                "avatarImagePath": s._agent_avatar_path_from_metadata(metadata),
                "avatarImageSource": str(metadata.get("avatarImageSource") or "").strip(),
            },
            lifecycle=True,
        )
    except Exception:
        return


def list_agent_avatar_options(model_id: str = "") -> dict[str, Any]:
    s = _service()
    options: list[dict[str, Any]] = []
    for filename in s._available_agent_avatar_filenames():
        path = str(s.AGENT_AVATAR_RELATIVE_DIR / filename)
        file_path = s.resolve_agent_avatar_file(filename)
        options.append(
            {
                "filename": filename,
                "path": path,
                "url": s.agent_avatar_image_url(path),
                "source": _agent_avatar_source(filename),
                "sizeBytes": file_path.stat().st_size if file_path.exists() else 0,
            }
        )
    model_default_path = s._default_agent_avatar_path(
        {"llmBindings": {s.DEFAULT_AGENT_LLM_SLOT: {"modelId": str(model_id or "").strip()}}}
    )
    model_default = next((option for option in options if option["path"] == model_default_path), None)
    return {
        "directory": str(s.AGENT_AVATAR_RELATIVE_DIR),
        "options": options,
        "count": len(options),
        "modelDefault": model_default,
    }


def _record_agent_avatar_uploaded_event(agent: dict[str, Any], *, content_type: str, size_bytes: int) -> None:
    s = _service()
    try:
        s.record_runtime_scene_event(
            "agent_directory",
            "agent_avatar",
            "agent.avatar_uploaded",
            message="Agent avatar image was uploaded.",
            level="info",
            outcome="uploaded",
            fields={
                "agentId": str(agent.get("agentId") or "").strip(),
                "agentCode": s._normalize_agent_code(agent.get("agentCode")),
                "contentType": str(content_type or "").strip(),
                "sizeBytes": int(size_bytes or 0),
                "storageScope": "config_adjacent",
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_agent_llm_binding_updated_event(agent: dict[str, Any]) -> None:
    s = _service()
    try:
        bindings = s.normalize_agent_llm_bindings(agent.get("llmBindings"))
        s.record_runtime_scene_event(
            "agent_directory",
            "agent_llm_bindings",
            "agent.llm_binding.updated",
            message="Agent model binding was updated.",
            level="info",
            outcome="updated",
            fields={
                "agentId": str(agent.get("agentId") or "").strip(),
                "updatedAt": str(agent.get("updatedAt") or "").strip(),
                "bindingSlots": sorted(bindings),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _canonical_agent_avatar_metadata_path(
    metadata: dict[str, Any],
    agent: dict[str, Any] | None = None,
) -> str:
    s = _service()
    agent_payload = agent if isinstance(agent, dict) else {}
    raw_path = str(
        metadata.get("avatarImagePath")
        or metadata.get("agentAvatarImagePath")
        or metadata.get("avatarPath")
        or agent_payload.get("avatarImagePath")
        or agent_payload.get("agentAvatarImagePath")
        or agent_payload.get("avatarPath")
        or ""
    ).strip()
    filename = s.agent_avatar_filename(raw_path)
    return str(s.AGENT_AVATAR_RELATIVE_DIR / filename) if filename else ""


def agent_avatar_filename(avatar_image_path: object) -> str:
    s = _service()
    value = str(avatar_image_path or "").strip().replace("\\", "/")
    if not value:
        return ""
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        return ""
    if path.parent != s.AGENT_AVATAR_RELATIVE_DIR:
        return ""
    filename = path.name
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", filename):
        return ""
    suffix = Path(filename).suffix.lower()
    if suffix == ".svg" and filename in s.AGENT_AVATAR_MODEL_FILENAMES:
        return filename
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        return ""
    return filename


def _agent_avatar_match_key(agent: dict[str, Any]) -> str:
    """Build a lowercase match haystack for default-avatar rules.

    Specific identity fields are listed first so exact role tokens appear in the
    key even when primaryMode is a broad mode like general/self_evolution.
    """
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    # Prefer specific roles ahead of primaryMode so table order can still use
    # broad mode tokens without them being the only signal.
    parts = [
        agent.get("roleKey"),
        metadata.get("supervisedRole"),
        metadata.get("selfEvolutionRole"),
        metadata.get("systemRole"),
        metadata.get("researchOrgRole"),
        metadata.get("researchAgentKey"),
        metadata.get("functionalDisplayName"),
        agent.get("primaryMode"),
        metadata.get("agentMode"),
    ]
    return " ".join(str(item or "").strip().lower() for item in parts if str(item or "").strip())


def _agent_custom_avatar_dir() -> Path:
    s = _service()
    return (
        Path(s.CONFIG_PATH).expanduser().resolve().parent
        / s.AGENT_AVATAR_CONFIG_DIR_NAME
        / s.AGENT_AVATAR_CONFIG_AGENT_DIR_NAME
    )


def _agent_custom_avatar_file(filename: str) -> Path:
    s = _service()
    safe_filename = s.agent_avatar_filename(str(s.AGENT_AVATAR_RELATIVE_DIR / str(filename or "")))
    if not safe_filename:
        raise FileNotFoundError("invalid Agent avatar image path")
    avatar_dir = _agent_custom_avatar_dir().resolve()
    path = (avatar_dir / safe_filename).resolve()
    if avatar_dir != path.parent:
        raise FileNotFoundError("invalid Agent avatar image path")
    return path


def _agent_avatar_storage_dirs(filename: str = "") -> tuple[tuple[str, Path], ...]:
    s = _service()
    custom = ("custom", _agent_custom_avatar_dir())
    bundled = (
        "bundled",
        Path(s._active_project_root()).resolve() / "assets" / s.AGENT_AVATAR_ASSET_DIR_NAME,
    )
    legacy = ("legacy", s._workspace_path("avatars", seed=False).resolve())
    # Product-owned model marks are immutable defaults: only the bundled asset
    # may represent a configured model, never a same-named custom file.
    if filename in s.AGENT_AVATAR_MODEL_FILENAMES:
        return (bundled,)
    return (
        custom,
        bundled,
        legacy,
    )


def _agent_avatar_source(filename: str) -> str:
    for source, avatar_dir in _agent_avatar_storage_dirs(filename):
        resolved_dir = avatar_dir.resolve()
        path = (resolved_dir / filename).resolve()
        if resolved_dir == path.parent and path.exists() and path.is_file():
            return source
    return "unavailable"


def _available_agent_avatar_filenames() -> list[str]:
    s = _service()
    existing: set[str] = set()
    for source, avatar_dir in _agent_avatar_storage_dirs():
        if not avatar_dir.exists() or not avatar_dir.is_dir():
            continue
        existing.update(
            item.name
            for item in avatar_dir.iterdir()
            if item.is_file()
            and not (source != "bundled" and item.name in s.AGENT_AVATAR_MODEL_FILENAMES)
            and s.agent_avatar_filename(str(s.AGENT_AVATAR_RELATIVE_DIR / item.name))
        )
    ordered = [filename for filename in s.AGENT_AVATAR_FILENAMES if filename in existing]
    extra = sorted(existing.difference(ordered))
    return ordered + extra


def _default_agent_avatar_path(
    agent: dict[str, Any],
    *,
    available_avatar_filenames: list[str] | None = None,
) -> str:
    s = _service()
    filename = s._default_agent_avatar_filename(
        agent,
        available_avatar_filenames=available_avatar_filenames,
    )
    return str(s.AGENT_AVATAR_RELATIVE_DIR / filename) if filename else ""


def _decode_agent_avatar_payload(data_base64: str) -> bytes:
    s = _service()
    try:
        payload = base64.b64decode(str(data_base64 or ""), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise s.AgentDirectoryError("Agent avatar image data is not valid base64.") from exc
    if not payload:
        raise s.AgentDirectoryError("Agent avatar image cannot be empty.")
    if len(payload) > s.MAX_AGENT_AVATAR_IMAGE_BYTES:
        raise s.AgentDirectoryError("Agent avatar image cannot exceed 5MB.")
    return payload


def resolve_agent_avatar_file(filename: str) -> Path:
    s = _service()
    safe_filename = s.agent_avatar_filename(str(s.AGENT_AVATAR_RELATIVE_DIR / str(filename or "")))
    if not safe_filename:
        raise FileNotFoundError("invalid Agent avatar image path")
    storage_dirs = _agent_avatar_storage_dirs(safe_filename)
    for _source, avatar_dir in storage_dirs:
        resolved_dir = avatar_dir.resolve()
        path = (resolved_dir / safe_filename).resolve()
        if resolved_dir != path.parent:
            raise FileNotFoundError("invalid Agent avatar image path")
        if path.exists() and path.is_file():
            return path
    return _agent_custom_avatar_file(safe_filename)


def _validate_agent_avatar_signature(payload: bytes, content_type: str) -> None:
    s = _service()
    if content_type == "image/png" and payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return
    if content_type == "image/jpeg" and payload.startswith(b"\xff\xd8\xff"):
        return
    if content_type == "image/webp" and payload.startswith(b"RIFF") and payload[8:12] == b"WEBP":
        return
    raise s.AgentDirectoryError("Agent avatar image format does not match its content.")


def agent_avatar_image_url(avatar_image_path: object) -> str:
    s = _service()
    filename = s.agent_avatar_filename(avatar_image_path)
    if not filename:
        return ""
    version = s._agent_avatar_image_version(filename)
    suffix = f"?v={version}" if version else ""
    return f"/api/agents/avatar-image/{quote(filename)}{suffix}"


def _agent_avatar_image_version(filename: str) -> str:
    s = _service()
    try:
        path = s.resolve_agent_avatar_file(filename)
        stat = path.stat()
    except (FileNotFoundError, OSError):
        return ""
    return f"{stat.st_mtime_ns:x}-{stat.st_size:x}"


def _agent_avatar_path_from_metadata(metadata: dict[str, Any]) -> str:
    s = _service()
    avatar_path = str(metadata.get("avatarImagePath") or "").strip()
    filename = s.agent_avatar_filename(avatar_path)
    return str(s.AGENT_AVATAR_RELATIVE_DIR / filename) if filename else ""


def record_agent_llm_binding_updated_event(agent: dict[str, Any]) -> None:
    """Emit the bounded durable binding event after a completed write."""
    s = _service()

    s._record_agent_llm_binding_updated_event(agent)


def _sanitize_avatar_stem(filename: str) -> str:
    raw_stem = Path(str(filename or "agent-avatar")).stem.lower()
    stem = re.sub(r"[^a-z0-9_-]+", "-", raw_stem).strip("-_")
    return stem[:40] or "agent-avatar"
