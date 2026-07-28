"""Conversation / agent directory index helpers for sessions.

Claim scope: create/select/query chat sessions, ensure direct session binding,
conversation agent metadata, and conversation index repair.

Late-bound facade keeps monkeypatches stable.
"""

from __future__ import annotations

import json
import re
import threading
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from core.web.services import agent_directory_service


def _service():
    from core.web.services import session_service

    return session_service


def _ensure_conversation_workspace_metadata(conversation: dict[str, Any]) -> bool:
    s = _service()
    conversation_id = str(conversation.get("conversation_id") or s.DEFAULT_CHAT_CONVERSATION_ID).strip()
    if not conversation_id:
        return False
    workspace_path = s._session_workspace_relative_path(conversation_id)
    s._ensure_session_workspace(conversation_id)
    changed = conversation.get("workspace_path") != workspace_path
    if changed:
        conversation["workspace_path"] = workspace_path
    return changed


def _conversation_index_kind_from_raw(raw: dict[str, Any]) -> tuple[str, str]:
    s = _service()
    raw_kind = str(raw.get("conversation_index_kind") or raw.get("conversationIndexKind") or "").strip()
    return raw_kind, s.agent_directory_service.normalize_conversation_index_kind(raw_kind)


def _conversation_index_classification(
    raw: dict[str, Any],
    agent: dict[str, Any] | None,
    *,
    hidden_team_member_agent_ids: set[str] | None = None,
) -> dict[str, Any]:
    s = _service()
    raw_kind, normalized_raw_kind = s._conversation_index_kind_from_raw(raw)
    errors: list[str] = []
    if raw_kind and not normalized_raw_kind:
        errors.append("invalid_conversation_index_kind")

    agent_classification = (
        s.agent_directory_service.agent_conversation_index_classification(
            agent,
            hidden_team_member_agent_ids=hidden_team_member_agent_ids,
        )
        if isinstance(agent, dict)
        else {"kind": s.agent_directory_service.CONVERSATION_INDEX_KIND_HIDDEN, "errors": []}
    )
    agent_kind = str(agent_classification.get("kind") or "").strip()
    agent_errors = list(agent_classification.get("errors") or [])

    if normalized_raw_kind:
        kind = normalized_raw_kind
        if (
            isinstance(agent, dict)
            and agent_kind
            and agent_kind not in {
                s.agent_directory_service.CONVERSATION_INDEX_KIND_HIDDEN,
                s.agent_directory_service.CONVERSATION_INDEX_KIND_INVALID,
            }
            and agent_kind != kind
        ):
            errors.append("conversation_agent_index_kind_conflict")
    elif isinstance(agent, dict) and agent_kind != s.agent_directory_service.CONVERSATION_INDEX_KIND_HIDDEN:
        kind = agent_kind
        errors.extend(agent_errors)
    else:
        kind = s.agent_directory_service.CONVERSATION_INDEX_KIND_INVALID
        errors.append("missing_conversation_index_kind")

    if kind in {
        agent_directory_service.CONVERSATION_INDEX_KIND_PERSONAL_AGENT,
        s.agent_directory_service.CONVERSATION_INDEX_KIND_TEAM_AGENT,
    } and not isinstance(agent, dict):
        errors.append("agent_required_for_agent_index_kind")
    if kind == s.agent_directory_service.CONVERSATION_INDEX_KIND_TEAM_AGENT and isinstance(agent, dict):
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        has_team_marker = bool(
            str(metadata.get("teamId") or "").strip()
            or str(metadata.get("challengeCupTeamId") or "").strip()
            or str(metadata.get("knowledgeExpansionTeamId") or "").strip()
        )
        if not has_team_marker:
            errors.append("team_agent_missing_team_id")
    if kind == s.agent_directory_service.CONVERSATION_INDEX_KIND_INVALID:
        errors.extend(agent_errors)

    errors = sorted(set(str(item) for item in errors if str(item or "").strip()))
    if errors and kind != s.agent_directory_service.CONVERSATION_INDEX_KIND_HIDDEN:
        kind = s.agent_directory_service.CONVERSATION_INDEX_KIND_INVALID
    return {"kind": kind, "errors": errors}


def repair_conversation_index_records() -> dict[str, Any]:
    """Explicitly migrate legacy direct-agent conversation index records.

    This is intentionally not part of the read path. Missing or invalid records
    still surface as invalid until this migration is called.
    """
    s = _service()

    s._sync_agent_directory_project_root()
    hidden_team_member_agent_ids = s._agent_directory_stub_hidden_team_member_ids()
    state = s.agent_directory_service.load_state()
    agents = list(state.get("agents") or []) if isinstance(state.get("agents"), list) else []
    repaired_agents: list[dict[str, str]] = []
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        repair_kind = s._legacy_agent_conversation_index_repair_kind(
            agent,
            hidden_team_member_agent_ids=hidden_team_member_agent_ids,
        )
        if not repair_kind:
            continue
        s._apply_agent_conversation_index_repair_metadata(agent, repair_kind)
        agent["updatedAt"] = s.agent_directory_service.utc_now_iso()
        repaired_agents.append(
            {
                "agentId": str(agent.get("agentId") or "").strip(),
                "directSessionId": str(agent.get("directSessionId") or "").strip(),
                "kind": repair_kind,
            }
        )
    if repaired_agents:
        state["agents"] = agents
        s.agent_directory_service.save_state(state)

    payload = s.load_chat_state(s.PROJECT_ROOT)
    conversations = payload.get("conversations")
    repaired_conversations: list[dict[str, str]] = []
    agent_by_id = {
        str(agent.get("agentId") or "").strip(): agent
        for agent in agents
        if isinstance(agent, dict) and str(agent.get("agentId") or "").strip()
    }
    if isinstance(conversations, list):
        for conversation in conversations:
            if not isinstance(conversation, dict):
                continue
            raw_kind, normalized_raw_kind = s._conversation_index_kind_from_raw(conversation)
            if raw_kind and not normalized_raw_kind:
                continue
            agent_id = str(conversation.get("agent_id") or conversation.get("agentId") or "").strip()
            agent = agent_by_id.get(agent_id)
            if not isinstance(agent, dict):
                continue
            agent_classification = s.agent_directory_service.agent_conversation_index_classification(
                agent,
                hidden_team_member_agent_ids=hidden_team_member_agent_ids,
            )
            agent_kind = str(agent_classification.get("kind") or "").strip()
            if agent_kind not in {
                agent_directory_service.CONVERSATION_INDEX_KIND_PERSONAL_AGENT,
                s.agent_directory_service.CONVERSATION_INDEX_KIND_TEAM_AGENT,
                s.agent_directory_service.CONVERSATION_INDEX_KIND_HIDDEN,
            }:
                continue
            if normalized_raw_kind == agent_kind and s._conversation_repair_flags_match_kind(conversation, agent_kind):
                continue
            s._apply_conversation_index_repair_fields(conversation, agent_kind)
            repaired_conversations.append(
                {
                    "sessionId": str(conversation.get("conversation_id") or "").strip(),
                    "agentId": agent_id,
                    "kind": agent_kind,
                }
            )
    if repaired_conversations:
        s.save_chat_state(s.PROJECT_ROOT, payload)

    if repaired_agents or repaired_conversations:
        s._invalidate_session_list_cache()
    result = {
        "changed": bool(repaired_agents or repaired_conversations),
        "agentCount": len(repaired_agents),
        "conversationCount": len(repaired_conversations),
        "agents": repaired_agents,
        "conversations": repaired_conversations,
    }
    if result["changed"]:
        try:
            s.record_runtime_scene_event(
                "conversation",
                "session_lifecycle",
                "conversation.index.repaired",
                level="info",
                outcome="succeeded",
                message="Conversation index records repaired.",
                fields={
                    "agentCount": result["agentCount"],
                    "conversationCount": result["conversationCount"],
                },
                lifecycle=True,
            )
        except Exception:
            pass
    return result


def _legacy_agent_conversation_index_repair_kind(
    agent: dict[str, Any],
    *,
    hidden_team_member_agent_ids: set[str],
) -> str:
    s = _service()
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    raw_kind = str(agent.get("conversationIndexKind") or metadata.get("conversationIndexKind") or "").strip()
    agent_id = str(agent.get("agentId") or "").strip()
    creation_spec = metadata.get("creationSpec") if isinstance(metadata.get("creationSpec"), dict) else {}
    created_by = str(agent.get("createdBy") or creation_spec.get("source") or "").strip()
    if raw_kind:
        # API-created direct Agents used to inherit the generic user_chat
        # default. That classification is invalid for a direct Agent and hid
        # the record from the personal-Agent directory. Other explicit kinds
        # remain authoritative and are never rewritten by this repair.
        if not (
            raw_kind == agent_directory_service.CONVERSATION_INDEX_KIND_USER_CHAT
            and created_by == "api_agents"
        ):
            return ""
    if created_by in s.agent_directory_service.INTERNAL_RECOVERY_DIRECT_SESSION_CREATED_BY:
        return s.agent_directory_service.CONVERSATION_INDEX_KIND_HIDDEN
    if created_by == "session_repair":
        return agent_directory_service.CONVERSATION_INDEX_KIND_PERSONAL_AGENT
    role_key = str(agent.get("roleKey") or "").strip()
    has_team_marker = bool(
        str(metadata.get("teamId") or "").strip()
        or str(metadata.get("challengeCupTeamId") or "").strip()
        or str(metadata.get("knowledgeExpansionTeamId") or "").strip()
        or (agent_id and agent_id in hidden_team_member_agent_ids)
    )
    looks_team_owned = (
        has_team_marker
        or role_key.startswith("challenge_cup_")
        or role_key.startswith("knowledge_expansion_")
        or created_by in s.agent_directory_service.TEAM_PRIVATE_DIRECT_SESSION_CREATED_BY
    )
    if looks_team_owned:
        return s.agent_directory_service.CONVERSATION_INDEX_KIND_TEAM_AGENT
    if (
        created_by == "user"
        and str(agent.get("status") or "active").strip() != "archived"
        and str(agent.get("primaryMode") or "").strip() == "chat"
        and not role_key
        and str(agent.get("directSessionId") or "").strip()
    ):
        return agent_directory_service.CONVERSATION_INDEX_KIND_PERSONAL_AGENT
    if created_by == "api_agents" and str(agent.get("directSessionId") or "").strip():
        return agent_directory_service.CONVERSATION_INDEX_KIND_PERSONAL_AGENT
    return ""


def _apply_agent_conversation_index_repair_metadata(agent: dict[str, Any], kind: str) -> None:
    s = _service()
    metadata = dict(agent.get("metadata") or {})
    metadata["conversationIndexKind"] = kind
    metadata["conversationIndexVisibility"] = s._conversation_index_visibility_for_kind(kind)
    if kind in {
        s.agent_directory_service.CONVERSATION_INDEX_KIND_TEAM_AGENT,
        s.agent_directory_service.CONVERSATION_INDEX_KIND_HIDDEN,
    }:
        metadata["showInSessionIndex"] = False
    if kind == s.agent_directory_service.CONVERSATION_INDEX_KIND_TEAM_AGENT:
        metadata.setdefault("directSessionVisibility", "active_session")
        if s._agent_needs_ai_search_team_marker(agent, metadata):
            metadata.setdefault("teamId", s._ai_search_team_id_for_repair())
    agent["metadata"] = metadata


def _conversation_repair_flags_match_kind(conversation: dict[str, Any], kind: str) -> bool:
    s = _service()
    hidden_flag = bool(conversation.get("hidden_from_index") or conversation.get("hiddenFromIndex"))
    if kind == s.agent_directory_service.CONVERSATION_INDEX_KIND_HIDDEN:
        return hidden_flag
    return not hidden_flag


def _apply_conversation_index_repair_fields(conversation: dict[str, Any], kind: str) -> None:
    s = _service()
    conversation["conversation_index_kind"] = kind
    conversation["conversationIndexKind"] = kind
    if kind == s.agent_directory_service.CONVERSATION_INDEX_KIND_HIDDEN:
        conversation["hidden_from_index"] = True
        conversation["hiddenFromIndex"] = True
    else:
        conversation["hidden_from_index"] = False
        conversation["hiddenFromIndex"] = False


def _conversation_index_visibility_for_kind(kind: str) -> str:
    s = _service()
    if kind == s.agent_directory_service.CONVERSATION_INDEX_KIND_TEAM_AGENT:
        return s.agent_directory_service.CONVERSATION_INDEX_VISIBILITY_TEAM_PRIVATE
    if kind == s.agent_directory_service.CONVERSATION_INDEX_KIND_HIDDEN:
        return s.agent_directory_service.CONVERSATION_INDEX_VISIBILITY_HIDDEN
    return s.agent_directory_service.CONVERSATION_INDEX_VISIBILITY_USER_VISIBLE


def _conversation_index_visibility_for_classification(
    kind: str,
    agent: dict[str, Any] | None,
    *,
    hidden_team_member_agent_ids: set[str] | None = None,
) -> str:
    s = _service()
    normalized_kind = str(kind or "").strip()
    if normalized_kind and normalized_kind != s.agent_directory_service.CONVERSATION_INDEX_KIND_INVALID:
        return s._conversation_index_visibility_for_kind(normalized_kind)
    if isinstance(agent, dict):
        return s.agent_directory_service.agent_conversation_index_visibility(
            agent,
            hidden_team_member_agent_ids=hidden_team_member_agent_ids,
        )
    return s.agent_directory_service.CONVERSATION_INDEX_VISIBILITY_USER_VISIBLE


def _raw_conversation_session_kind(conversation: dict[str, Any]) -> str:
    s = _service()
    return s._normalize_session_kind(conversation.get("session_kind") or conversation.get("sessionKind"))


def _raw_conversation_root_session_id(conversation: dict[str, Any], conversation_id: str) -> str:
    s = _service()
    parent_session_id = str(conversation.get("parent_session_id") or conversation.get("parentSessionId") or "").strip()
    root_session_id = str(conversation.get("root_session_id") or conversation.get("rootSessionId") or "").strip()
    if root_session_id:
        return root_session_id
    if s._raw_conversation_session_kind(conversation) == "child" and parent_session_id:
        return parent_session_id
    return conversation_id


def _conversation_agent_direct_session_is_allowed(
    *,
    conversation: dict[str, Any],
    conversation_id: str,
    direct_session_id: str,
) -> bool:
    s = _service()
    if not direct_session_id or direct_session_id == conversation_id:
        return True
    if str(conversation.get("session_role") or conversation.get("sessionRole") or "").strip() == "workspace":
        return True
    session_kind = s._raw_conversation_session_kind(conversation)
    if session_kind == "child":
        root_id = s._raw_conversation_root_session_id(conversation, conversation_id)
        parent_id = str(conversation.get("parent_session_id") or conversation.get("parentSessionId") or "").strip()
        return direct_session_id in {root_id, parent_id}
    return False


def _repair_conversation_agent_legacy_model_fields(
    conversation: dict[str, Any],
    *,
    conversation_id: str,
    agent_id: str,
    agent: dict[str, Any] | None = None,
) -> bool:
    s = _service()
    previous_fields = {
        "agent_profile_id": str(conversation.get("agent_profile_id") or "").strip(),
        "agentProfileId": str(conversation.get("agentProfileId") or "").strip(),
        "agentTemplateId": str(conversation.get("agentTemplateId") or "").strip(),
        "agentTemplateLabel": str(conversation.get("agentTemplateLabel") or "").strip(),
    }
    changed = False
    for key in ("agent_profile_id", "agentProfileId", "agentTemplateId", "agentTemplateLabel"):
        if key in conversation:
            conversation.pop(key, None)
            changed = True
    if changed:
        s._record_session_agent_legacy_model_fields_repaired_event(
            conversation_id,
            agent_id=agent_id,
            previous_fields=previous_fields,
            prompt_template_id=str((agent or {}).get("promptTemplateId") or "").strip(),
            role_key=str((agent or {}).get("roleKey") or "").strip(),
        )
    return changed


def _ensure_conversation_agent_metadata(
    conversation: dict[str, Any],
    *,
    agent_by_id: dict[str, dict[str, Any]] | None = None,
) -> bool:
    s = _service()
    s._sync_agent_directory_project_root()
    conversation_id = str(conversation.get("conversation_id") or s.DEFAULT_CHAT_CONVERSATION_ID).strip()
    if not conversation_id:
        return False
    title = str(conversation.get("title") or s.DEFAULT_CHAT_CONVERSATION_TITLE).strip() or s.DEFAULT_CHAT_CONVERSATION_TITLE
    session_workspace = str(conversation.get("workspace_path") or s._session_workspace_relative_path(conversation_id))
    existing_agent_id = str(conversation.get("agent_id") or conversation.get("agentId") or "").strip()
    session_kind = s._raw_conversation_session_kind(conversation)
    agent_status_code = str(conversation.get("agentStatusCode") or "").strip()
    if agent_status_code == "deleted_agent":
        deleted_agent_id = str(
            conversation.get("agent_deleted_id")
            or conversation.get("agentDeletedId")
            or conversation.get("agent_missing_id")
            or conversation.get("agentMissingId")
            or existing_agent_id
            or ""
        ).strip()
        changed = False
        for key in ("agent_id", "agentId"):
            if conversation.get(key) != "":
                conversation[key] = ""
                changed = True
        for key in ("agent_deleted_id", "agentDeletedId", "agent_missing_id", "agentMissingId"):
            if deleted_agent_id and conversation.get(key) != deleted_agent_id:
                conversation[key] = deleted_agent_id
                changed = True
        if conversation.get("agentMissing") is not True:
            conversation["agentMissing"] = True
            changed = True
        if conversation.get("agentStatusCode") != "deleted_agent":
            conversation["agentStatusCode"] = "deleted_agent"
            changed = True
        if conversation.get("agentDirectSessionMismatch"):
            conversation["agentDirectSessionMismatch"] = False
            changed = True
        if conversation.get("agentPrimaryDirectSessionId"):
            conversation["agentPrimaryDirectSessionId"] = ""
            changed = True
        changed = s._repair_conversation_agent_legacy_model_fields(
            conversation,
            conversation_id=conversation_id,
            agent_id=deleted_agent_id,
        ) or changed
        return changed
    existing_agent = s._agent_from_lookup(agent_by_id, existing_agent_id) if existing_agent_id else None
    if existing_agent is None:
        recovered_agent = s._recover_active_direct_session_agent(
            conversation_id,
            agent_by_id=agent_by_id,
            preferred_agent_id=(
                existing_agent_id
                or str(conversation.get("agent_missing_id") or conversation.get("agentMissingId") or "").strip()
            ),
        )
        if recovered_agent is not None:
            existing_agent = recovered_agent
            existing_agent_id = str(recovered_agent.get("agentId") or "").strip()
    default_primary_mode = s.agent_directory_service.DEFAULT_AGENT_PRIMARY_MODE
    primary_mode = str((existing_agent or {}).get("primaryMode") or default_primary_mode).strip() or default_primary_mode
    role_key = str((existing_agent or {}).get("roleKey") or "").strip()
    prompt_template_id = str((existing_agent or {}).get("promptTemplateId") or "").strip()
    if existing_agent_id and not existing_agent:
        changed = False
        if conversation.get("agent_id") != "":
            conversation["agent_id"] = ""
            changed = True
        if conversation.get("agentId") != "":
            conversation["agentId"] = ""
            changed = True
        if conversation.get("agent_missing_id") != existing_agent_id:
            conversation["agent_missing_id"] = existing_agent_id
            changed = True
        if conversation.get("agentMissingId") != existing_agent_id:
            conversation["agentMissingId"] = existing_agent_id
            changed = True
        if conversation.get("agentMissing") is not True:
            conversation["agentMissing"] = True
            changed = True
        if conversation.get("agentStatusCode") != "missing_agent":
            conversation["agentStatusCode"] = "missing_agent"
            changed = True
        if conversation.get("agentDirectSessionMismatch"):
            conversation["agentDirectSessionMismatch"] = False
            changed = True
        changed = s._repair_conversation_agent_legacy_model_fields(
            conversation,
            conversation_id=conversation_id,
            agent_id=existing_agent_id,
        ) or changed
        return changed
    if existing_agent and str(existing_agent.get("status") or "active").strip().lower() == "archived":
        changed = False
        if conversation.get("agent_id") != existing_agent_id:
            conversation["agent_id"] = existing_agent_id
            changed = True
        if conversation.get("agentId") != existing_agent_id:
            conversation["agentId"] = existing_agent_id
            changed = True
        changed = s._repair_conversation_agent_legacy_model_fields(
            conversation,
            conversation_id=conversation_id,
            agent_id=existing_agent_id,
            agent=existing_agent,
        ) or changed
        return changed
    if existing_agent and str(existing_agent.get("directSessionId") or "").strip() == conversation_id:
        changed = False
        recovered_missing_agent = bool(
            conversation.get("agentMissing")
            or conversation.get("agentStatusCode")
            or conversation.get("agent_missing_id")
            or conversation.get("agentMissingId")
        )
        if conversation.get("agent_id") != existing_agent_id:
            conversation["agent_id"] = existing_agent_id
            changed = True
        if conversation.get("agentId") != existing_agent_id:
            conversation["agentId"] = existing_agent_id
            changed = True
        for key in ("agent_missing_id", "agentMissingId"):
            if conversation.get(key):
                conversation[key] = ""
                changed = True
        if conversation.get("agentMissing"):
            conversation["agentMissing"] = False
            changed = True
        if conversation.get("agentStatusCode"):
            conversation["agentStatusCode"] = ""
            changed = True
        changed = s._repair_conversation_agent_legacy_model_fields(
            conversation,
            conversation_id=conversation_id,
            agent_id=existing_agent_id,
            agent=existing_agent,
        ) or changed
        if conversation.get("agentDirectSessionMismatch"):
            conversation["agentDirectSessionMismatch"] = False
            changed = True
        if conversation.get("agentPrimaryDirectSessionId"):
            conversation["agentPrimaryDirectSessionId"] = ""
            changed = True
        if recovered_missing_agent and changed:
            s._record_session_agent_binding_recovered_event(conversation_id, agent_id=existing_agent_id)
        return changed
    if existing_agent:
        changed = False
        if conversation.get("agent_id") != existing_agent_id:
            conversation["agent_id"] = existing_agent_id
            changed = True
        if conversation.get("agentId") != existing_agent_id:
            conversation["agentId"] = existing_agent_id
            changed = True
        changed = s._repair_conversation_agent_legacy_model_fields(
            conversation,
            conversation_id=conversation_id,
            agent_id=existing_agent_id,
            agent=existing_agent,
        ) or changed
        existing_direct_session_id = str(existing_agent.get("directSessionId") or "").strip()
        child_session_ids = s._raw_conversation_child_session_ids(conversation)
        if (
            session_kind != "child"
            and existing_direct_session_id
            and existing_direct_session_id in child_session_ids
        ):
            previous_direct_session_id = existing_direct_session_id
            repaired_agent = s.ensure_agent_for_session(
                conversation_id,
                display_name=title,
                llm_bindings=s.agent_directory_service.normalize_agent_llm_bindings(existing_agent.get("llmBindings")),
                primary_mode=primary_mode,
                role_key=role_key,
                prompt_template_id=prompt_template_id,
                existing_agent_id=existing_agent_id,
                session_workspace_path=session_workspace,
            )
            existing_agent = s._conversation_agent_from_state(repaired_agent)
            if agent_by_id is not None:
                agent_by_id[existing_agent_id] = existing_agent
            existing_direct_session_id = str(existing_agent.get("directSessionId") or "").strip()
            changed = True
            s._record_session_agent_child_direct_binding_repaired_event(
                conversation_id,
                agent_id=existing_agent_id,
                previous_direct_session_id=previous_direct_session_id,
            )
        if s._conversation_agent_direct_session_is_allowed(
            conversation=conversation,
            conversation_id=conversation_id,
            direct_session_id=existing_direct_session_id,
        ):
            if conversation.get("agentDirectSessionMismatch"):
                conversation["agentDirectSessionMismatch"] = False
                changed = True
            if conversation.get("agentPrimaryDirectSessionId"):
                conversation["agentPrimaryDirectSessionId"] = ""
                changed = True
        elif existing_direct_session_id:
            if conversation.get("agentDirectSessionMismatch") is not True:
                conversation["agentDirectSessionMismatch"] = True
                changed = True
            if conversation.get("agentPrimaryDirectSessionId") != existing_direct_session_id:
                conversation["agentPrimaryDirectSessionId"] = existing_direct_session_id
                changed = True
        return changed
    if existing_agent:
        changed = False
        if conversation.get("agent_id") != existing_agent_id:
            conversation["agent_id"] = existing_agent_id
            changed = True
        if conversation.get("agentId") != existing_agent_id:
            conversation["agentId"] = existing_agent_id
            changed = True
        changed = s._repair_conversation_agent_legacy_model_fields(
            conversation,
            conversation_id=conversation_id,
            agent_id=existing_agent_id,
            agent=existing_agent,
        ) or changed
        return changed
    archived_direct_agent = s._archived_agent_for_direct_session(conversation_id) if not existing_agent_id else None
    if archived_direct_agent:
        archived_agent_id = str(archived_direct_agent.get("agentId") or "").strip()
        changed = False
        if conversation.get("agent_id") != archived_agent_id:
            conversation["agent_id"] = archived_agent_id
            changed = True
        if conversation.get("agentId") != archived_agent_id:
            conversation["agentId"] = archived_agent_id
            changed = True
        changed = s._repair_conversation_agent_legacy_model_fields(
            conversation,
            conversation_id=conversation_id,
            agent_id=archived_agent_id,
            agent=archived_direct_agent,
        ) or changed
        return changed
    direct_agent = s._agent_for_direct_session(conversation_id) if not existing_agent_id else None
    if not direct_agent and not s._conversation_requires_agent_materialization(conversation):
        return False
    llm_bindings_for_ensure = (
        s.agent_directory_service.normalize_agent_llm_bindings(existing_agent.get("llmBindings"))
        if existing_agent
        else s.agent_directory_service.normalize_agent_llm_bindings((direct_agent or {}).get("llmBindings"))
    )
    if not llm_bindings_for_ensure and not direct_agent:
        llm_bindings_for_ensure = s._normalize_session_agent_llm_bindings(None)
    agent = s.ensure_agent_for_session(
        conversation_id,
        display_name=title,
        llm_bindings=llm_bindings_for_ensure,
        primary_mode=primary_mode,
        role_key=role_key,
        prompt_template_id=prompt_template_id,
        existing_agent_id=existing_agent_id,
        session_workspace_path=session_workspace,
    )
    agent_id = str(agent.get("agentId") or "").strip()
    if agent_by_id is not None and agent_id:
        agent_by_id[agent_id] = agent
    changed = False
    if agent_id and conversation.get("agent_id") != agent_id:
        conversation["agent_id"] = agent_id
        changed = True
    if agent_id and conversation.get("agentId") != agent_id:
        conversation["agentId"] = agent_id
        changed = True
    changed = s._repair_conversation_agent_legacy_model_fields(
        conversation,
        conversation_id=conversation_id,
        agent_id=agent_id,
        agent=agent,
    ) or changed
    return changed


def _conversation_requires_agent_materialization(conversation: dict[str, Any]) -> bool:
    s = _service()
    if str(conversation.get("agent_id") or conversation.get("agentId") or "").strip():
        return True
    conversation_id = str(conversation.get("conversation_id") or conversation.get("id") or s.DEFAULT_CHAT_CONVERSATION_ID).strip()
    if list(conversation.get("messages") or []):
        return True
    if conversation_id.startswith("session-seed-"):
        return False
    if "workspace_path" not in conversation and "workspacePath" not in conversation:
        return True
    if conversation_id and s._session_ledger_visible_messages(conversation_id):
        return True
    active_task = conversation.get("active_task") or conversation.get("activeTask")
    if isinstance(active_task, dict) and active_task:
        return True
    if str(conversation.get("session_kind") or conversation.get("sessionKind") or "").strip().lower() in {"child", "supervised"}:
        return True
    last_status = str(conversation.get("last_turn_status") or conversation.get("status") or "").strip().lower()
    return last_status not in {"", "ready", "idle"}


def _sync_agent_directory_project_root() -> None:
    s = _service()
    project_root = Path(__file__).resolve().parents[4]
    if s.agent_directory_service.PROJECT_ROOT != project_root:
        s.agent_directory_service.PROJECT_ROOT = project_root
        s._invalidate_session_list_cache()


def _conversation_agent_from_state(agent: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    agent_id = str(agent.get("agentId") or "").strip()
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    team_identity = s._agent_team_identity(agent, metadata)
    workspace_path = str(agent.get("workspacePath") or "").strip()
    avatar_path = s._agent_avatar_path(agent, metadata)
    llm_bindings = s.agent_directory_service.normalize_agent_llm_bindings(agent.get("llmBindings"))
    return {
        "agentId": agent_id,
        "agentCode": str(agent.get("agentCode") or "").strip(),
        "displayName": str(agent.get("displayName") or "").strip(),
        "kind": str(agent.get("kind") or s.agent_directory_service.DEFAULT_AGENT_KIND).strip()
        or s.agent_directory_service.DEFAULT_AGENT_KIND,
        "primaryMode": str(agent.get("primaryMode") or s.agent_directory_service.DEFAULT_AGENT_PRIMARY_MODE).strip()
        or s.agent_directory_service.DEFAULT_AGENT_PRIMARY_MODE,
        "roleKey": str(agent.get("roleKey") or "").strip(),
        "promptTemplateId": str(agent.get("promptTemplateId") or "").strip(),
        "llmBindings": llm_bindings,
        "directSessionId": str(agent.get("directSessionId") or "").strip(),
        "conversationIndexKind": str(agent.get("conversationIndexKind") or metadata.get("conversationIndexKind") or "").strip(),
        "teamId": str(team_identity.get("teamId") or "").strip(),
        "teamName": str(team_identity.get("teamName") or "").strip(),
        "workspacePath": workspace_path,
        "avatarImagePath": avatar_path,
        "avatarImageUrl": s.agent_directory_service.agent_avatar_image_url(avatar_path),
        "status": str(agent.get("status") or "active").strip() or "active",
        "createdBy": str(agent.get("createdBy") or "").strip(),
        "metadata": dict(metadata),
        "createdAt": str(agent.get("createdAt") or "").strip(),
        "updatedAt": str(agent.get("updatedAt") or "").strip(),
    }


def _get_cached_session_query_sessions(*, now: float) -> list[dict[str, Any]] | None:
    s = _service()
    s._sync_agent_directory_project_root()
    signature = (s._session_list_source_signature(), False)
    if s._repair_agent_direct_session_collisions(source_signature=signature):
        signature = (s._session_list_source_signature(), False)
    cached = s._get_session_list_cache(
        now=now,
        signature=signature,
        allow_stale_matching_signature=True,
    )
    if cached is None:
        return None
    sessions, cache_age_ms, conversation_count, agent_count = cached
    s._record_session_list_loaded_event(
        session_count=len(sessions),
        conversation_count=conversation_count,
        agent_count=agent_count,
        elapsed_ms=s._elapsed_ms(now),
        cache_hit=True,
        cache_age_ms=cache_age_ms,
        cache_ttl_ms=int(round(s._SESSION_LIST_CACHE_TTL_SECONDS * 1000)),
        waited_for_inflight=False,
    )
    return sessions


def query_sessions(
    *,
    limit: int = 50,
    cursor: str = "",
    q: str = "",
    agent_id: str = "",
    session_kind: str = "",
    state: str = "",
    sort: str = "updatedAt_desc",
) -> dict[str, Any]:
    """Return a paginated, filtered session summary payload."""
    s = _service()

    started_at = s._perf_counter()
    sessions = s._get_cached_session_query_sessions(now=started_at)
    if sessions is None:
        sessions = s.list_sessions()
    normalized_limit = s._coerce_session_query_limit(limit)
    normalized_cursor = s._coerce_nonnegative_int(cursor)
    normalized_query = str(q or "").strip().lower()
    normalized_agent_id = str(agent_id or "").strip()
    normalized_session_kind = str(session_kind or "").strip().lower()
    normalized_state = str(state or "").strip().lower()
    normalized_sort = s._normalize_session_query_sort(sort)

    has_filters = bool(normalized_query or normalized_agent_id or normalized_session_kind or normalized_state)
    if not has_filters and normalized_sort == "updatedAt_desc":
        filtered = sessions
    else:
        filtered = [
            item
            for item in sessions
            if s._session_query_matches(
                item,
                query=normalized_query,
                agent_id=normalized_agent_id,
                session_kind=normalized_session_kind,
                state=normalized_state,
            )
        ]
    if normalized_sort != "updatedAt_desc":
        filtered.sort(
            key=s._session_query_sort_key(normalized_sort),
            reverse=normalized_sort.endswith("_desc"),
        )

    total = len(filtered)
    start = min(normalized_cursor, total)
    end = min(start + normalized_limit, total)
    page_items = filtered[start:end]
    next_cursor = str(end) if end < total else ""
    s._record_session_list_query_event(
        result_count=len(page_items),
        matched_count=total,
        total_count=len(sessions),
        limit=normalized_limit,
        cursor=start,
        elapsed_ms=s._elapsed_ms(started_at),
        has_query=bool(normalized_query),
        has_agent_filter=bool(normalized_agent_id),
        has_kind_filter=bool(normalized_session_kind),
        has_state_filter=bool(normalized_state),
        sort=normalized_sort,
    )
    payload = {
        "items": page_items,
        "nextCursor": next_cursor,
        "totalEstimate": total,
        "filters": {
            "q": str(q or "").strip(),
            "agentId": normalized_agent_id,
            "sessionKind": normalized_session_kind,
            "state": normalized_state,
            "sort": normalized_sort,
            "limit": normalized_limit,
            "cursor": str(start) if start > 0 else "",
        },
    }
    try:
        catalog_config = getattr(s.get_config(), "session_catalog", None)
        if str(getattr(catalog_config, "mode", "off") or "off") == "shadow":
            from . import catalog_bridge

            comparison = catalog_bridge.run_session_query_shadow(
                payload,
                request={
                    "limit": normalized_limit,
                    "cursor": str(start) if start > 0 else "",
                    "q": str(q or "").strip(),
                    "agent_id": normalized_agent_id,
                    "session_kind": normalized_session_kind,
                    "state": normalized_state,
                    "sort": normalized_sort,
                },
            )
            s._record_session_catalog_shadow_query_event(
                comparison=comparison,
                limit=normalized_limit,
                cursor=start,
                has_query=bool(normalized_query),
                has_agent_filter=bool(normalized_agent_id),
                has_kind_filter=bool(normalized_session_kind),
                has_state_filter=bool(normalized_state),
                sort=normalized_sort,
            )
    except Exception:
        # Shadow failures must never change the canonical legacy response.
        pass
    return payload


def select_chat_session(session_id: str) -> dict:
    """Make an existing or AgentDirectory direct session the active chat session."""
    s = _service()

    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        raise s.SessionNotFoundError("Session not found")
    s._sync_agent_directory_project_root()
    agent_by_id = s._agent_lookup_for_conversations()
    with s._CHAT_STATE_LOCK:
        payload = s.load_chat_state(s.PROJECT_ROOT)
        conversations = payload.get("conversations")
        if not isinstance(conversations, list):
            conversations = []
            payload["conversations"] = conversations
        changed = False
        conversation = s._find_conversation_entry(payload, normalized_session_id)
        if conversation is None:
            changed = s._materialize_agent_directory_conversation_locked(
                payload,
                normalized_session_id,
                source="s.select_chat_session",
                activate=True,
            )
            if not changed:
                raise s.SessionNotFoundError("Session not found")
            conversation = s._find_conversation_entry(payload, normalized_session_id)
        if conversation is None:
            raise s.SessionNotFoundError("Session not found")
        s._ensure_session_mutable(normalized_session_id, conversation=conversation)
        changed = s._ensure_conversation_workspace_metadata(conversation) or changed
        changed = s._ensure_conversation_agent_metadata(conversation, agent_by_id=agent_by_id) or changed
        previous_active_id = str(payload.get("active_conversation_id") or "").strip()
        if previous_active_id != normalized_session_id:
            payload["active_conversation_id"] = normalized_session_id
            changed = True
        if changed:
            payload["updated_at"] = str(conversation.get("updated_at") or s._now_timestamp())
            s.save_chat_state(s.PROJECT_ROOT, payload)
    s._invalidate_session_list_cache()
    detail = s.get_session_detail(normalized_session_id)
    if detail is None:
        raise s.SessionNotFoundError("Session not found")
    return detail


def create_chat_session(
    *,
    title: str = "",
    agent_id: str = "",
    llm_bindings: dict[str, Any] | None = None,
    created_by: str = "user",
    conversation_index_kind: str = agent_directory_service.CONVERSATION_INDEX_KIND_USER_CHAT,
    experiment_binding: dict[str, Any] | None = None,
) -> dict:
    """Create a new empty chat session and make it active."""
    s = _service()

    lang = s.get_web_language()
    normalized_agent_id = str(agent_id or "").strip()
    normalized_llm_bindings = s._normalize_session_agent_llm_bindings(llm_bindings)
    raw_experiment_binding = experiment_binding if isinstance(experiment_binding, dict) else {}
    try:
        experiment_attempt = max(1, int(raw_experiment_binding.get("attempt") or 1))
    except (TypeError, ValueError):
        experiment_attempt = 1
    normalized_experiment_binding = {
        "teamId": str(raw_experiment_binding.get("teamId") or "").strip()[:160],
        "researchProjectId": str(raw_experiment_binding.get("researchProjectId") or "").strip()[:160],
        "experimentName": str(raw_experiment_binding.get("experimentName") or "").strip()[:160],
        "agentId": str(raw_experiment_binding.get("agentId") or "").strip()[:160],
        "roleKey": str(raw_experiment_binding.get("roleKey") or "").strip()[:80],
        "roleLabel": str(raw_experiment_binding.get("roleLabel") or "").strip()[:80],
        "attempt": experiment_attempt,
        "retryOfSessionId": str(raw_experiment_binding.get("retryOfSessionId") or "").strip()[:160],
        "createdFromTaskId": str(raw_experiment_binding.get("createdFromTaskId") or "").strip()[:160],
        "createdAt": str(raw_experiment_binding.get("createdAt") or "").strip()[:120],
    } if raw_experiment_binding else {}
    binding_agent_id = str(normalized_experiment_binding.get("agentId") or "").strip()
    if binding_agent_id and binding_agent_id != normalized_agent_id:
        raise s.SessionValidationError("Experiment binding Agent id does not match the bound Agent.")
    bound_agent: dict[str, Any] | None = None
    if normalized_agent_id:
        s._sync_agent_directory_project_root()
        bound_agent = s.get_agent(normalized_agent_id, include_archived=False)
        if not bound_agent:
            raise s.SessionValidationError(s._session_agent_unavailable_message("missing_agent", lang=lang))
    with s._CHAT_STATE_LOCK:
        payload = s.load_chat_state(s.PROJECT_ROOT)
        conversations = payload.get("conversations")
        if not isinstance(conversations, list):
            conversations = []
        existing_ids = {
            str(item.get("conversation_id") or "").strip()
            for item in conversations
            if isinstance(item, dict)
        }
        now = s._now_timestamp()
        session_id = s._new_conversation_id(existing_ids)
        normalized_title = s.trim_lines(title or "", max_lines=1).strip() or s.text_for(lang, zh="新会话", en="New session")
        conversation = s._make_empty_conversation(
            session_id,
            title=normalized_title,
            timestamp=now,
            conversation_index_kind=conversation_index_kind,
        )
        s._ensure_conversation_workspace_metadata(conversation)
        if bound_agent is not None:
            conversation.update(
                {
                    "agent_id": normalized_agent_id,
                    "agentId": normalized_agent_id,
                    "session_role": "workspace",
                    "sessionRole": "workspace",
                }
            )
            if normalized_experiment_binding:
                conversation["experiment_binding"] = normalized_experiment_binding
                conversation["experimentBinding"] = normalized_experiment_binding
        else:
            s._sync_agent_directory_project_root()
            agent = s.ensure_agent_for_session(
                session_id,
                display_name=normalized_title,
                llm_bindings=normalized_llm_bindings,
                session_workspace_path=str(conversation.get("workspace_path") or s._session_workspace_relative_path(session_id)),
                created_by=created_by,
                conversation_index_kind=conversation_index_kind,
            )
            normalized_agent_id = str(agent.get("agentId") or "").strip()
            if normalized_agent_id:
                conversation["agent_id"] = normalized_agent_id
                conversation["agentId"] = normalized_agent_id
                conversation["session_role"] = "primary"
                conversation["sessionRole"] = "primary"
        conversations.append(conversation)
        payload["version"] = int(payload.get("version") or s.CHAT_STATE_VERSION)
        payload["active_conversation_id"] = session_id
        payload["updated_at"] = now
        payload["conversations"] = conversations
        s.save_chat_state(s.PROJECT_ROOT, payload)
    s._invalidate_session_list_cache()
    try:
        s.record_runtime_scene_event(
            "conversation",
            "session_lifecycle",
            "conversation.session.created",
            level="info",
            outcome="succeeded",
            message="Chat session created.",
            fields={
                "sessionId": session_id,
                "agentId": normalized_agent_id,
                "sessionRole": "workspace" if bound_agent is not None else "primary",
                "createdAgent": bound_agent is None,
            },
            lifecycle=True,
        )
    except Exception:
        pass
    return s.get_session_detail(session_id) or {}


def ensure_agent_direct_session(
    *,
    agent_id: str,
    title: str = "",
    created_by: str = "agent_direct_session_repair",
    conversation_index_kind: str = agent_directory_service.CONVERSATION_INDEX_KIND_PERSONAL_AGENT,
) -> dict[str, Any]:
    """Ensure an existing Agent has an ordinary direct chat session."""
    s = _service()

    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        raise s.SessionValidationError(s.text_for(s.get_web_language(), zh="缺少 Agent 绑定。", en="Agent binding is missing."))
    agent = s.get_agent(normalized_agent_id, include_archived=False)
    if not agent:
        raise s.SessionValidationError(s._session_agent_unavailable_message("missing_agent", lang=s.get_web_language()))
    current_session_id = str(agent.get("directSessionId") or "").strip()
    if current_session_id and s.get_session_detail(current_session_id):
        return s.get_session_detail(current_session_id) or {}
    lang = s.get_web_language()
    with s._CHAT_STATE_LOCK:
        payload = s.load_chat_state(s.PROJECT_ROOT)
        conversations = payload.get("conversations")
        if not isinstance(conversations, list):
            conversations = []
            payload["conversations"] = conversations
        existing_ids = {
            str(item.get("conversation_id") or "").strip()
            for item in conversations
            if isinstance(item, dict)
        }
        now = s._now_timestamp()
        session_id = s._new_conversation_id(existing_ids)
        display_title = (
            s.trim_lines(title or "", max_lines=1).strip()
            or str(agent.get("displayName") or "").strip()
            or s.text_for(lang, zh="Agent 私聊", en="Agent chat")
        )
        conversation = s._make_empty_conversation(
            session_id,
            title=display_title,
            timestamp=now,
            conversation_index_kind=conversation_index_kind,
        )
        conversation["created_by"] = str(created_by or "agent_direct_session_repair").strip() or "agent_direct_session_repair"
        conversation["createdBy"] = conversation["created_by"]
        s._ensure_conversation_workspace_metadata(conversation)
        s._bind_conversation_to_agent_instance(
            conversation,
            agent,
            session_id=session_id,
            source="s.ensure_agent_direct_session",
            conversation_index_kind=conversation_index_kind,
        )
        conversations.append(conversation)
        payload["version"] = int(payload.get("version") or s.CHAT_STATE_VERSION)
        payload["active_conversation_id"] = session_id
        payload["updated_at"] = now
        payload["conversations"] = conversations
        s.save_chat_state(s.PROJECT_ROOT, payload)
    s._invalidate_session_list_cache()
    return s.get_session_detail(session_id) or {}


def _bind_conversation_to_agent_instance(
    conversation: dict[str, Any],
    agent: dict[str, Any],
    *,
    session_id: str,
    source: str,
    conversation_index_kind: str = "",
) -> None:
    s = _service()
    agent_id = str(agent.get("agentId") or "").strip()
    if not agent_id:
        return
    s._release_other_direct_session_agents(session_id, keep_agent_id=agent_id)
    conversation["agent_id"] = agent_id
    conversation["agentId"] = agent_id
    s._repair_conversation_agent_legacy_model_fields(
        conversation,
        conversation_id=session_id,
        agent_id=agent_id,
        agent=agent,
    )
    try:
        if str(agent.get("directSessionId") or "").strip() != str(session_id or "").strip():
            s.update_agent_instance(agent_id, status="active", metadata={"previousDirectSessionId": str(agent.get("directSessionId") or "").strip()})
            s.agent_directory_service.ensure_agent_for_session(
                session_id,
                display_name=str(agent.get("displayName") or conversation.get("title") or s.DEFAULT_CHAT_CONVERSATION_TITLE),
                llm_bindings=agent.get("llmBindings") if isinstance(agent.get("llmBindings"), dict) else None,
                primary_mode=str(agent.get("primaryMode") or "chat"),
                role_key=str(agent.get("roleKey") or ""),
                prompt_template_id=str(agent.get("promptTemplateId") or ""),
                existing_agent_id=agent_id,
                session_workspace_path=str(conversation.get("workspace_path") or conversation.get("workspacePath") or s._session_workspace_relative_path(session_id)),
                created_by="session_agent_binding",
                conversation_index_kind=conversation_index_kind,
            )
    except s.AgentNotFoundError:
        raise s.SessionValidationError(f"Session Agent not found: {agent_id}") from None
    s._record_session_agent_binding_updated_event(
        session_id,
        agent_id=agent_id,
        source=source,
        prompt_template_id=str(agent.get("promptTemplateId") or "").strip(),
        role_key=str(agent.get("roleKey") or "").strip(),
    )


def _repair_agent_direct_session_collisions(
    *,
    source_signature: tuple[Any, ...] | None = None,
) -> bool:
    s = _service()
    s._sync_agent_directory_project_root()
    signature = source_signature or s._session_list_source_signature()
    with s._DIRECT_SESSION_COLLISION_REPAIR_LOCK:
        if s._DIRECT_SESSION_COLLISION_REPAIR_SIGNATURE == signature:
            return False
    with s._CHAT_STATE_LOCK:
        payload = s.load_chat_state(s.PROJECT_ROOT)
        conversations = payload.get("conversations")
        if not isinstance(conversations, list):
            conversations = []
            payload["conversations"] = conversations
        state = s.agent_directory_service.load_state()
        raw_agents = list(state.get("agents") or []) if isinstance(state.get("agents"), list) else []
        agents = [item for item in raw_agents if isinstance(item, dict)]
        session_to_agents: dict[str, list[dict[str, Any]]] = {}
        for agent in agents:
            if str(agent.get("status") or "active").strip().lower() == "archived":
                continue
            session_id = str(agent.get("directSessionId") or "").strip()
            agent_id = str(agent.get("agentId") or "").strip()
            if not session_id or not agent_id:
                continue
            session_to_agents.setdefault(session_id, []).append(agent)
        duplicate_groups = {
            session_id: items
            for session_id, items in session_to_agents.items()
            if len(items) > 1
        }
        if not duplicate_groups:
            with s._DIRECT_SESSION_COLLISION_REPAIR_LOCK:
                s._DIRECT_SESSION_COLLISION_REPAIR_SIGNATURE = signature
            return False

        existing_session_ids = {
            str(item.get("conversation_id") or "").strip()
            for item in conversations
            if isinstance(item, dict) and str(item.get("conversation_id") or "").strip()
        }
        existing_session_ids.update(
            str(agent.get("directSessionId") or "").strip()
            for agent in agents
            if str(agent.get("directSessionId") or "").strip()
        )
        conversations_by_id = {
            str(item.get("conversation_id") or "").strip(): item
            for item in conversations
            if isinstance(item, dict) and str(item.get("conversation_id") or "").strip()
        }
        now = s._now_timestamp()
        repaired: list[dict[str, str]] = []
        preserved_session_ids: set[str] = set()
        for session_id, colliding_agents in sorted(duplicate_groups.items()):
            owner = s._select_direct_session_collision_owner(
                session_id,
                colliding_agents,
                conversations_by_id.get(session_id),
            )
            owner_id = str(owner.get("agentId") or "").strip()
            preserved_session_ids.add(session_id)
            conversation = conversations_by_id.get(session_id)
            if conversation is not None and owner_id:
                if conversation.get("agent_id") != owner_id:
                    conversation["agent_id"] = owner_id
                if conversation.get("agentId") != owner_id:
                    conversation["agentId"] = owner_id
            for agent in sorted(colliding_agents, key=s._agent_direct_session_collision_repair_sort_key):
                agent_id = str(agent.get("agentId") or "").strip()
                if not agent_id or agent_id == owner_id:
                    continue
                replacement_session_id = s._new_conversation_id(existing_session_ids)
                existing_session_ids.add(replacement_session_id)
                previous_metadata = dict(agent.get("metadata") or {})
                metadata = dict(previous_metadata)
                metadata["previousDirectSessionId"] = session_id
                metadata["directSessionCollisionRepairedAt"] = now
                agent["metadata"] = metadata
                agent["directSessionId"] = replacement_session_id
                agent["updatedAt"] = now
                conversation = s._agent_directory_conversation_record(agent, session_id=replacement_session_id)
                conversations.append(conversation)
                conversations_by_id[replacement_session_id] = conversation
                repaired.append(
                    {
                        "agentId": agent_id,
                        "agentCode": str(agent.get("agentCode") or "").strip(),
                        "previousSessionId": session_id,
                        "replacementSessionId": replacement_session_id,
                    }
                )
        if not repaired:
            return False
        payload["version"] = int(payload.get("version") or s.CHAT_STATE_VERSION)
        payload["updated_at"] = now
        if str(payload.get("active_conversation_id") or "").strip() not in existing_session_ids:
            payload["active_conversation_id"] = str(conversations[0].get("conversation_id") or "").strip() if conversations else ""
        state["agents"] = raw_agents
        s.agent_directory_service.save_state(state)
        s.save_chat_state(s.PROJECT_ROOT, payload)
    s._invalidate_session_list_cache()
    with s._DIRECT_SESSION_COLLISION_REPAIR_LOCK:
        s._DIRECT_SESSION_COLLISION_REPAIR_SIGNATURE = s._session_list_source_signature()
    s._record_agent_direct_session_collision_repaired_event(
        preserved_session_ids=sorted(preserved_session_ids),
        repaired=repaired,
    )
    return True


def _select_direct_session_collision_owner(
    session_id: str,
    agents: list[dict[str, Any]],
    conversation: dict[str, Any] | None,
) -> dict[str, Any]:
    s = _service()
    for agent in agents:
        if (
            str(agent.get("agentId") or "").strip() == s.agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID
            and str(session_id or "").strip() == s.agent_directory_service.KNOWLEDGE_STEWARD_DIRECT_SESSION_ID
        ):
            return agent
    protected_agents = [agent for agent in agents if s._agent_direct_session_collision_owner_protected(agent)]
    if protected_agents:
        return sorted(protected_agents, key=s._agent_direct_session_collision_owner_sort_key)[0]
    bound_agent_id = str((conversation or {}).get("agent_id") or (conversation or {}).get("agentId") or "").strip()
    if bound_agent_id:
        for agent in agents:
            if str(agent.get("agentId") or "").strip() == bound_agent_id:
                return agent
    direct_match = [
        agent
        for agent in agents
        if str(agent.get("directSessionId") or "").strip() == str(session_id or "").strip()
    ]
    candidates = direct_match or list(agents)
    return sorted(candidates, key=s._agent_direct_session_collision_owner_sort_key)[0]


def _agent_direct_session_collision_owner_protected(agent: dict[str, Any]) -> bool:
    s = _service()
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    system_role = str(metadata.get("systemRole") or metadata.get("researchOrgRole") or "").strip()
    return bool(metadata.get("protected")) or system_role in {
        "ceo",
        "organization_advisor",
        s.agent_directory_service.KNOWLEDGE_STEWARD_ROLE_KEY,
    }


def _agent_directory_stub_hidden_from_user_index(
    agent: dict[str, Any],
    hidden_team_member_agent_ids: set[str],
) -> bool:
    """Hide non-user Agent conversation stubs from the ordinary chat index."""
    s = _service()

    classification = s.agent_directory_service.agent_conversation_index_classification(
        agent,
        hidden_team_member_agent_ids=hidden_team_member_agent_ids,
    )
    kind = str(classification.get("kind") or "").strip()
    if kind == s.agent_directory_service.CONVERSATION_INDEX_KIND_HIDDEN:
        return True
    agent_id = str(agent.get("agentId") or "").strip()
    if agent_id and agent_id in hidden_team_member_agent_ids:
        visibility = s.agent_directory_service.agent_conversation_index_visibility(
            agent,
            hidden_team_member_agent_ids=hidden_team_member_agent_ids,
        )
        return visibility == s.agent_directory_service.CONVERSATION_INDEX_VISIBILITY_TEAM_PRIVATE
    return False


def _agent_directory_stub_hidden_team_member_ids() -> set[str]:
    s = _service()
    try:
        from . import team_service

        payload = team_service.list_teams_compact(include_archived=False)
    except Exception:
        return set()
    hidden_agent_ids: set[str] = set()
    for team in list((payload or {}).get("teams") or []):
        if not isinstance(team, dict):
            continue
        source = str(team.get("teamSource") or "").strip()
        kind = str(team.get("teamKind") or "").strip()
        if (
            source not in s._AGENT_DIRECTORY_STUB_HIDDEN_TEAM_SOURCES
            and kind not in s._AGENT_DIRECTORY_STUB_HIDDEN_TEAM_KINDS
        ):
            continue
        for member in list(team.get("members") or []):
            if not isinstance(member, dict):
                continue
            agent_id = str(member.get("agentId") or "").strip()
            if agent_id:
                hidden_agent_ids.add(agent_id)
    return hidden_agent_ids


def _ensure_agent_directory_conversation_materialized(
    session_id: str,
    *,
    source: str,
    activate: bool = False,
) -> bool:
    s = _service()
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return False
    with s._CHAT_STATE_LOCK:
        payload = s.load_chat_state(s.PROJECT_ROOT)
        changed = s._materialize_agent_directory_conversation_locked(
            payload,
            normalized_session_id,
            source=source,
            activate=activate,
        )
        if changed:
            s.save_chat_state(s.PROJECT_ROOT, payload)
        return changed


def _ensure_session_conversation_record(
    session_id: str,
    *,
    source: str,
) -> bool:
    """Ensure chat_state has a conversation row for this session.

    Used by mutations (e.g. reasoning effort) that only write chat_state, while
    list/detail can surface agent-directory or workspace-backed sessions that
    were never (or no longer) indexed in chat_state.
    """
    s = _service()
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return False
    s._ensure_agent_directory_conversation_materialized(
        normalized_session_id,
        source=source,
    )
    with s._CHAT_STATE_LOCK:
        payload = s.load_chat_state(s.PROJECT_ROOT)
        if s._find_conversation_entry(payload, normalized_session_id) is not None:
            return True
        recovered = s._recover_missing_conversation_from_workspace_locked(
            payload,
            normalized_session_id,
            source=source,
        )
        if recovered:
            s.save_chat_state(s.PROJECT_ROOT, payload)
            s._invalidate_session_list_cache()
        return recovered


def _recover_agent_id_from_session_journal(session_id: str) -> str:
    """Best-effort agentId from turn_journal when chat_state entry is missing."""
    s = _service()
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return ""
    try:
        workspace = s._ensure_session_workspace(normalized_session_id)
    except Exception:
        return ""
    journal_path = workspace / "turn_journal.jsonl"
    if not journal_path.is_file():
        return ""
    try:
        # Only scan a bounded prefix — agentId is typically on turn_started.
        with journal_path.open("r", encoding="utf-8", errors="replace") as handle:
            for index, line in enumerate(handle):
                if index >= 40:
                    break
                text = str(line or "").strip()
                if not text:
                    continue
                try:
                    event = json.loads(text)
                except Exception:
                    continue
                if not isinstance(event, dict):
                    continue
                payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
                for raw in (
                    payload.get("agentId"),
                    payload.get("agent_id"),
                    event.get("agentId"),
                    event.get("agent_id"),
                ):
                    agent_id = str(raw or "").strip()
                    if agent_id:
                        return agent_id
    except Exception:
        return ""
    return ""


def _recover_missing_conversation_from_workspace_locked(
    payload: dict[str, Any],
    session_id: str,
    *,
    source: str,
) -> bool:
    """Append a chat_state conversation recovered from on-disk session workspace."""
    s = _service()
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return False
    if s._find_conversation_entry(payload, normalized_session_id) is not None:
        return False
    agent_id = s._recover_agent_id_from_session_journal(normalized_session_id)
    agent = s.get_agent(agent_id, include_archived=True) if agent_id else None
    if isinstance(agent, dict) and agent:
        conversation = s._agent_directory_conversation_record(
            agent,
            session_id=normalized_session_id,
        )
    else:
        # Bare conversation so session-scoped settings (reasoning effort) can persist.
        conversation = s._make_empty_conversation(
            normalized_session_id,
            title=normalized_session_id,
            timestamp=s._now_timestamp(),
        )
        if agent_id:
            conversation["agent_id"] = agent_id
            conversation["agentId"] = agent_id
    conversations = payload.get("conversations")
    if not isinstance(conversations, list):
        conversations = []
        payload["conversations"] = conversations
    conversations.append(conversation)
    payload["version"] = int(payload.get("version") or s.CHAT_STATE_VERSION)
    payload["updated_at"] = str(conversation.get("updated_at") or s._now_timestamp())
    try:
        s.record_runtime_scene_event(
            "conversation",
            "chat_state",
            "conversation.workspace_recovered",
            level="info",
            outcome="recovered",
            message="Recovered missing chat_state conversation from session workspace.",
            fields={
                "sessionId": normalized_session_id,
                "agentId": agent_id,
                "source": str(source or "").strip()[:64],
            },
            lifecycle=True,
        )
    except Exception:
        pass
    return True


def _materialize_agent_directory_conversation_locked(
    payload: dict[str, Any],
    session_id: str,
    *,
    source: str,
    activate: bool = False,
) -> bool:
    s = _service()
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id or s._find_conversation_entry(payload, normalized_session_id) is not None:
        return False
    agent = s._agent_for_direct_session(normalized_session_id)
    if not agent:
        return False
    conversation = s._agent_directory_conversation_record(agent, session_id=normalized_session_id)
    if s._agent_directory_stub_hidden_from_user_index(agent, s._agent_directory_stub_hidden_team_member_ids()):
        conversation["hidden_from_index"] = True
        conversation["hiddenFromIndex"] = True
    conversations = payload.get("conversations")
    if not isinstance(conversations, list):
        conversations = []
        payload["conversations"] = conversations
    conversations.append(conversation)
    payload["version"] = int(payload.get("version") or s.CHAT_STATE_VERSION)
    if activate:
        payload["active_conversation_id"] = normalized_session_id
    payload["updated_at"] = str(conversation.get("updated_at") or s._now_timestamp())
    s._record_agent_directory_conversation_materialized_event(agent, session_id=normalized_session_id, source=source)
    return True


def _agent_directory_conversation_record(agent: dict[str, Any], *, session_id: str) -> dict[str, Any]:
    s = _service()
    timestamp = str(agent.get("updatedAt") or agent.get("createdAt") or "").strip() or s._now_timestamp()
    display_name = str(agent.get("displayName") or agent.get("agentCode") or session_id).strip() or session_id
    classification = s.agent_directory_service.agent_conversation_index_classification(agent)
    conversation = s._make_empty_conversation(
        session_id,
        title=display_name,
        timestamp=timestamp,
        conversation_index_kind=str(classification.get("kind") or ""),
    )
    conversation["agent_id"] = str(agent.get("agentId") or "").strip()
    conversation["agentId"] = str(agent.get("agentId") or "").strip()
    s._ensure_conversation_workspace_metadata(conversation)
    return conversation


def _conversation_agent_deleted_tombstone_matches(conversation: dict[str, Any], *, agent_id: str) -> bool:
    s = _service()
    if not isinstance(conversation, dict):
        return False
    normalized_agent_id = str(agent_id or "").strip()
    tombstone = conversation.get("agentDeletedTombstone") if isinstance(conversation.get("agentDeletedTombstone"), dict) else {}
    tombstone_agent_id = str(tombstone.get("agentId") or "").strip()
    deleted_agent_id = str(conversation.get("agentDeletedId") or conversation.get("agent_deleted_id") or "").strip()
    return bool(normalized_agent_id and (tombstone_agent_id == normalized_agent_id or deleted_agent_id == normalized_agent_id))


def _mark_conversation_agent_deleted(
    conversation: dict[str, Any],
    *,
    session_id: str,
    agent_id: str,
    agent_display_name: str,
    previous_status: str,
    hide_from_index: bool = False,
    timestamp: str,
) -> bool:
    s = _service()
    changed = False
    deleted_agent_id = str(agent_id or "").strip()
    for key in ("agent_id", "agentId"):
        if conversation.get(key) != "":
            conversation[key] = ""
            changed = True
    for key in ("agent_deleted_id", "agentDeletedId", "agent_missing_id", "agentMissingId"):
        if deleted_agent_id and conversation.get(key) != deleted_agent_id:
            conversation[key] = deleted_agent_id
            changed = True
    display_name = s.trim_lines(agent_display_name, max_lines=1).strip()
    if display_name and conversation.get("agentDeletedDisplayName") != display_name:
        conversation["agentDeletedDisplayName"] = display_name
        changed = True
    if conversation.get("agentMissing") is not True:
        conversation["agentMissing"] = True
        changed = True
    if conversation.get("agentStatusCode") != "deleted_agent":
        conversation["agentStatusCode"] = "deleted_agent"
        changed = True
    if hide_from_index:
        if conversation.get("hiddenFromIndex") is not True:
            conversation["hiddenFromIndex"] = True
            changed = True
        if conversation.get("conversationIndexKind") != s.agent_directory_service.CONVERSATION_INDEX_KIND_HIDDEN:
            conversation["conversationIndexKind"] = s.agent_directory_service.CONVERSATION_INDEX_KIND_HIDDEN
            changed = True
        if conversation.get("conversationIndexVisibility") != s.agent_directory_service.CONVERSATION_INDEX_VISIBILITY_HIDDEN:
            conversation["conversationIndexVisibility"] = s.agent_directory_service.CONVERSATION_INDEX_VISIBILITY_HIDDEN
            changed = True
    if conversation.get("agentDirectSessionMismatch"):
        conversation["agentDirectSessionMismatch"] = False
        changed = True
    if conversation.get("agentPrimaryDirectSessionId"):
        conversation["agentPrimaryDirectSessionId"] = ""
        changed = True
    next_tombstone = {
        "agentId": deleted_agent_id,
        "sessionId": str(session_id or "").strip(),
        "deletedAt": str(timestamp or "").strip(),
        "previousStatus": str(previous_status or "").strip(),
        "historyRetention": "preserved_tombstone",
    }
    if dict(conversation.get("agentDeletedTombstone") or {}) != next_tombstone:
        conversation["agentDeletedTombstone"] = next_tombstone
        changed = True
    if str(timestamp or "").strip() and conversation.get("updated_at") != timestamp:
        conversation["updated_at"] = timestamp
        changed = True
    return changed


def _agent_directory_conversation_stub(
    agent: dict[str, Any],
    *,
    session_id: str,
    hidden_team_member_agent_ids: set[str] | None = None,
) -> dict[str, Any]:
    s = _service()
    display_name = str(agent.get("displayName") or agent.get("agentCode") or session_id).strip() or session_id
    hidden_team_member_agent_ids = (
        hidden_team_member_agent_ids
        if hidden_team_member_agent_ids is not None
        else s._agent_directory_stub_hidden_team_member_ids()
    )
    team_identity = {
        "teamId": str(agent.get("teamId") or "").strip(),
        "teamName": str(agent.get("teamName") or "").strip(),
    }
    classification = s.agent_directory_service.agent_conversation_index_classification(
        agent,
        hidden_team_member_agent_ids=hidden_team_member_agent_ids,
    )
    return {
        "id": session_id,
        "title": display_name,
        "agentId": str(agent.get("agentId") or "").strip(),
        "workspacePath": s._session_workspace_relative_path(session_id),
        "messages": [],
        "lastTurnStatus": "",
        "lastTurnError": {},
        "updatedAt": str(agent.get("updatedAt") or agent.get("createdAt") or "").strip(),
        "activeTask": None,
        "conversationIndexVisibility": s.agent_directory_service.agent_conversation_index_visibility(
            agent,
            hidden_team_member_agent_ids=hidden_team_member_agent_ids,
        ),
        "conversationIndexKind": str(classification.get("kind") or "").strip(),
        "conversationIndexErrors": list(classification.get("errors") or []),
        "teamId": team_identity["teamId"],
        "teamName": team_identity["teamName"],
        "_agent": dict(agent),
        "agentDirectoryOnly": True,
    }


def _conversation_agent_dialogue_context_window(cfg: Any, conversation: dict[str, Any] | None) -> int:
    s = _service()
    return s._coerce_nonnegative_int(s._conversation_agent_dialogue_context_window_payload(cfg, conversation).get("limit") or 0)


def _conversation_agent_dialogue_context_window_payload(cfg: Any, conversation: dict[str, Any] | None) -> dict[str, Any]:
    """Resolve max context from model_library / provider config only (no numeric invention)."""
    s = _service()
    agent = s._conversation_agent_for_context_limit(conversation)
    agent_id = str((agent or {}).get("agentId") or "").strip() if isinstance(agent, dict) else ""
    model_id = s.agent_dialogue_model_id(agent)
    if not model_id:
        return {"limit": 0, "modelId": "", "agentId": agent_id, "source": "missing"}
    try:
        entry = getattr(cfg.llm, "model_library", {}).get(model_id)
    except Exception:
        entry = None
    if not isinstance(entry, dict):
        return {"limit": 0, "modelId": model_id, "agentId": agent_id, "source": "missing"}
    explicit_limit = s._first_positive_int(
        entry.get("context_window"),
        entry.get("contextWindow"),
        entry.get("max_model_len"),
        entry.get("context_length"),
    )
    if explicit_limit:
        return {
            "limit": explicit_limit,
            "modelId": model_id,
            "agentId": agent_id,
            "source": "model_library",
        }
    provider_id = str(entry.get("provider_id") or "").strip()
    if not provider_id:
        return {"limit": 0, "modelId": model_id, "agentId": agent_id, "source": "missing"}
    try:
        provider = cfg.llm.get_provider(provider_id)
        provider_limit = int(getattr(provider, "context_window", 0) or 0)
        if provider_limit > 0:
            return {
                "limit": provider_limit,
                "modelId": model_id,
                "agentId": agent_id,
                "source": "provider_config",
            }
        return {"limit": 0, "modelId": model_id, "agentId": agent_id, "source": "missing"}
    except Exception:
        return {"limit": 0, "modelId": model_id, "agentId": agent_id, "source": "missing"}


def _conversation_agent_for_context_limit(conversation: dict[str, Any] | None) -> dict[str, Any] | None:
    s = _service()
    if not isinstance(conversation, dict):
        return None
    cached_agent = conversation.get("_agent")
    if isinstance(cached_agent, dict):
        return cached_agent
    agent_id = str(conversation.get("agentId") or conversation.get("agent_id") or "").strip()
    if not agent_id:
        return None
    return s.get_agent(agent_id)


def _find_conversation_entry(payload: dict[str, Any], session_id: str) -> dict[str, Any] | None:
    s = _service()
    conversations = payload.get("conversations")
    if not isinstance(conversations, list):
        return None
    for item in conversations:
        if not isinstance(item, dict):
            continue
        if str(item.get("conversation_id") or "").strip() == session_id:
            return item
    return None


def _new_conversation_id(existing_ids: set[str] | None = None) -> str:
    s = _service()
    existing = set(existing_ids or set())
    base = f"session-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}"
    candidate = base
    suffix = 2
    while candidate in existing:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def _make_empty_conversation(
    session_id: str,
    *,
    title: str,
    timestamp: str,
    conversation_index_kind: str = agent_directory_service.CONVERSATION_INDEX_KIND_USER_CHAT,
) -> dict[str, Any]:
    s = _service()
    normalized_index_kind = s.agent_directory_service.normalize_conversation_index_kind(conversation_index_kind)
    if not normalized_index_kind:
        normalized_index_kind = s.agent_directory_service.CONVERSATION_INDEX_KIND_INVALID
    normalized_index_visibility = s._conversation_index_visibility_for_kind(normalized_index_kind)
    conversation = {
        "conversation_id": str(session_id or "").strip(),
        "title": str(title or "").strip() or s.DEFAULT_CHAT_CONVERSATION_TITLE,
        "workspace_path": s._session_workspace_relative_path(session_id),
        "updated_at": str(timestamp or "").strip() or s._now_timestamp(),
        "last_turn_status": "ready",
        "last_turn_error": None,
        "active_task": None,
        "conversation_index_kind": normalized_index_kind,
        "conversationIndexKind": normalized_index_kind,
        "conversation_index_visibility": normalized_index_visibility,
        "conversationIndexVisibility": normalized_index_visibility,
    }
    if normalized_index_kind == s.agent_directory_service.CONVERSATION_INDEX_KIND_HIDDEN:
        conversation["hidden_from_index"] = True
        conversation["hiddenFromIndex"] = True
    return conversation


def _record_agent_directory_conversation_index_event(
    agent: dict[str, Any],
    *,
    session_id: str,
) -> None:
    s = _service()
    normalized_session_id = str(session_id or "").strip()
    agent_id = str(agent.get("agentId") or "").strip()
    if not normalized_session_id or not agent_id:
        return
    dedupe_key = (str(s.PROJECT_ROOT.resolve()), normalized_session_id, agent_id)
    with s._SESSION_INDEX_EVENT_DEDUPE_LOCK:
        if dedupe_key in s._AGENT_DIRECTORY_INDEX_EVENT_KEYS:
            return
        s._AGENT_DIRECTORY_INDEX_EVENT_KEYS.add(dedupe_key)
    try:
        s.record_runtime_scene_event(
            "conversation",
            "agent_directory_index",
            "session.agent_directory_index_added",
            level="info",
            outcome="indexed",
            message="Agent Directory direct session added to the conversation index.",
            fields={
                "sessionId": normalized_session_id,
                "agentId": agent_id,
                "agentCode": str(agent.get("agentCode") or "").strip(),
                "primaryMode": str(agent.get("primaryMode") or "").strip(),
                "roleKey": str(agent.get("roleKey") or "").strip(),
                "promptTemplateId": str(agent.get("promptTemplateId") or "").strip(),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_agent_direct_session_collision_repaired_event(
    *,
    preserved_session_ids: list[str],
    repaired: list[dict[str, str]],
) -> None:
    s = _service()
    cleaned = [
        {
            "agentId": str(item.get("agentId") or "").strip(),
            "agentCode": str(item.get("agentCode") or "").strip(),
            "previousSessionId": str(item.get("previousSessionId") or "").strip(),
            "replacementSessionId": str(item.get("replacementSessionId") or "").strip(),
        }
        for item in list(repaired or [])
        if str(item.get("agentId") or "").strip()
    ]
    if not cleaned:
        return
    try:
        s.record_runtime_scene_event(
            "conversation",
            "agent_direct_session_collision",
            "session.agent_direct_session_collision.repaired",
            level="warning",
            outcome="repaired",
            message="Duplicate active Agent directSessionId bindings were repaired before building the session index.",
            fields={
                "preservedSessionId": str((preserved_session_ids or [""])[0] or "").strip(),
                "preservedSessionIds": [str(item or "").strip() for item in list(preserved_session_ids or []) if str(item or "").strip()],
                "repairedCount": len(cleaned),
                "repairedAgents": cleaned[:12],
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_agent_directory_conversation_materialized_event(
    agent: dict[str, Any],
    *,
    session_id: str,
    source: str,
) -> None:
    s = _service()
    try:
        s.record_runtime_scene_event(
            "conversation",
            "agent_directory_materialize",
            "session.agent_directory_conversation_materialized",
            level="info",
            outcome="materialized",
            message="Agent Directory direct session materialized into chat state.",
            fields={
                "sessionId": str(session_id or "").strip(),
                "agentId": str(agent.get("agentId") or "").strip(),
                "agentCode": str(agent.get("agentCode") or "").strip(),
                "primaryMode": str(agent.get("primaryMode") or "").strip(),
                "roleKey": str(agent.get("roleKey") or "").strip(),
                "promptTemplateId": str(agent.get("promptTemplateId") or "").strip(),
                "source": str(source or "").strip(),
            },
            child_log_path=f"conversations/{s._safe_session_workspace_token(session_id)}-agent-bindings.jsonl",
            child_log_payload={
                "session_id": str(session_id or "").strip(),
                "agent_id": str(agent.get("agentId") or "").strip(),
                "agent_code": str(agent.get("agentCode") or "").strip(),
                "source": str(source or "").strip(),
                "action": "materialized_from_agent_directory",
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_session_agent_legacy_model_fields_repaired_event(
    session_id: str,
    *,
    agent_id: str,
    previous_fields: dict[str, str],
    prompt_template_id: str = "",
    role_key: str = "",
) -> None:
    s = _service()
    normalized_session_id = str(session_id or "").strip()
    cleaned_previous = {
        key: s.trim_lines(str(value or ""), max_lines=1)
        for key, value in dict(previous_fields or {}).items()
        if str(value or "").strip()
    }
    try:
        s.record_runtime_scene_event(
            "conversation",
            "session_agent_legacy_model_fields_repaired",
            "session.agent_legacy_model_fields_repaired",
            level="info",
            outcome="repaired",
            message="Session legacy Agent model fields were removed from chat state.",
            fields={
                "sessionId": normalized_session_id,
                "agentId": str(agent_id or "").strip(),
                "removedFieldNames": sorted(cleaned_previous),
                "promptTemplateId": str(prompt_template_id or "").strip(),
                "roleKey": str(role_key or "").strip(),
                "source": "AgentInstance",
            },
            child_log_path=f"conversations/{s._safe_session_workspace_token(normalized_session_id)}-agent-bindings.jsonl",
            child_log_payload={
                "session_id": normalized_session_id,
                "agent_id": str(agent_id or "").strip(),
                "removed_field_names": sorted(cleaned_previous),
                "previous_fields": cleaned_previous,
                "prompt_template_id": str(prompt_template_id or "").strip(),
                "role_key": str(role_key or "").strip(),
                "source": "AgentInstance",
                "action": "legacy_model_fields_removed",
            },
            lifecycle=True,
        )
    except Exception:
        return
