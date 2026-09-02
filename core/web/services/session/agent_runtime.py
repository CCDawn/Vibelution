"""Session agent binding / prompt snapshot / LLM runtime helpers.

Claim scope: acquire chat agent, prompt snapshots, agent binding recovery,
image-input capability checks, and session LLM runtime diagnostics events.

Late-bound facade keeps monkeypatches stable.
"""

from __future__ import annotations

import copy

import hashlib

import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Mapping

SESSION_LLM_SLOT_DIALOGUE = "dialogue"


def _service():
    from core.web.services import session_service

    return session_service


def _agent_from_lookup(
    agent_by_id: dict[str, dict[str, Any]] | None,
    agent_id: str,
) -> dict[str, Any] | None:
    s = _service()
    normalized = str(agent_id or "").strip()
    if not normalized:
        return None
    if agent_by_id is not None:
        agent = agent_by_id.get(normalized)
        return agent if isinstance(agent, dict) else None
    return s.get_agent(normalized)


def _recover_active_direct_session_agent(
    session_id: str,
    *,
    agent_by_id: dict[str, dict[str, Any]] | None,
    preferred_agent_id: str = "",
) -> dict[str, Any] | None:
    s = _service()
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id or not isinstance(agent_by_id, dict):
        return None
    normalized_preferred_agent_id = str(preferred_agent_id or "").strip()
    preferred_agent = s._agent_from_lookup(agent_by_id, normalized_preferred_agent_id) if normalized_preferred_agent_id else None
    if (
        isinstance(preferred_agent, dict)
        and str(preferred_agent.get("status") or "active").strip().lower() != "archived"
        and str(preferred_agent.get("directSessionId") or "").strip() == normalized_session_id
    ):
        return preferred_agent
    for agent in agent_by_id.values():
        if not isinstance(agent, dict):
            continue
        if str(agent.get("status") or "active").strip().lower() == "archived":
            continue
        if str(agent.get("directSessionId") or "").strip() == normalized_session_id:
            return agent
    return None


def _session_agent_is_available(summary: dict[str, Any]) -> bool:
    s = _service()
    return bool(str(summary.get("agentId") or "").strip()) and not bool(summary.get("agentMissing"))


def _release_other_direct_session_agents(session_id: str, *, keep_agent_id: str) -> None:
    s = _service()
    normalized_session_id = str(session_id or "").strip()
    normalized_keep_agent_id = str(keep_agent_id or "").strip()
    if not normalized_session_id or not normalized_keep_agent_id:
        return
    try:
        directory_state = s.agent_directory_service.load_state()
    except Exception:
        return
    for item in directory_state.get("agents") or []:
        if not isinstance(item, dict):
            continue
        agent_id = str(item.get("agentId") or "").strip()
        if not agent_id or agent_id == normalized_keep_agent_id:
            continue
        if str(item.get("status") or "active").strip().lower() == "archived":
            continue
        if str(item.get("directSessionId") or "").strip() != normalized_session_id:
            continue
        s.update_agent_instance(
            agent_id,
            direct_session_id="",
            metadata={"previousDirectSessionId": normalized_session_id},
        )


def _normalize_session_agent_llm_bindings(value: Any) -> dict[str, dict[str, str]]:
    s = _service()
    normalized = s.agent_directory_service.normalize_agent_llm_bindings(value)
    if s.agent_dialogue_model_id({"llmBindings": normalized}):
        return normalized
    default_model_id = s._default_session_dialogue_model_id()
    if default_model_id:
        normalized["dialogue"] = {"modelId": default_model_id}
    return normalized


def default_session_llm_bindings() -> dict[str, dict[str, str]]:
    s = _service()
    return s._normalize_session_agent_llm_bindings(None)


def _session_agent_reasoning_effort(agent: dict[str, Any] | None, slot: str = SESSION_LLM_SLOT_DIALOGUE) -> str:
    s = _service()
    metadata = agent.get("metadata") if isinstance(agent, dict) and isinstance(agent.get("metadata"), dict) else {}
    by_slot = metadata.get("llmReasoningEffort") if isinstance(metadata.get("llmReasoningEffort"), dict) else {}
    return str(by_slot.get(slot) or "").strip().lower()


def _session_llm_model_choices() -> list[dict[str, Any]]:
    s = _service()
    from core.web.services.agent_model_candidate_service import list_agent_model_candidates

    default_model_id = s._default_session_dialogue_model_id()
    choices = copy.deepcopy(list_agent_model_candidates().get("candidates") or [])
    for choice in choices:
        choice["isDefault"] = str(choice.get("modelId") or "").strip() == default_model_id
        values = [
            str(value or "").strip().lower()
            for value in list(choice.get("reasoningEffortValues") or [])
            if str(value or "").strip()
        ]
        choice["reasoningEffortValues"] = values
        provided_options = choice.get("reasoningEffortOptions") if isinstance(choice.get("reasoningEffortOptions"), list) else []
        option_by_value = {
            str(item.get("value") or "").strip().lower(): item
            for item in provided_options
            if isinstance(item, dict) and str(item.get("value") or "").strip()
        }
        choice["reasoningEffortOptions"] = [
            {
                "value": value,
                "label": str((option_by_value.get(value) or {}).get("label") or {
                    "low": "低",
                    "medium": "中",
                    "high": "高",
                }.get(value, value)).strip(),
                "description": str((option_by_value.get(value) or {}).get("description") or {
                    "low": "更快响应，适合直接问题",
                    "medium": "平衡速度与推理深度",
                    "high": "更深推理，适合复杂任务",
                }.get(value, "")).strip(),
            }
            for value in values
        ]
        requested_default = str(choice.get("defaultReasoningEffort") or "").strip().lower()
        choice["defaultReasoningEffort"] = requested_default if requested_default in values else "medium" if "medium" in values else (values[0] if values else "")
    return choices


def _session_agent_id_snapshot(session_id: str) -> str:
    s = _service()
    normalized_session_id = str(session_id or "").strip()
    if not s._ensure_session_conversation_record(
        normalized_session_id,
        source="session.agent_id.snapshot",
    ):
        raise s.SessionNotFoundError(f"Session not found: {normalized_session_id}")
    with s._CHAT_STATE_LOCK:
        conversation = s.load_session_chat_state(s.PROJECT_ROOT, normalized_session_id)
        if conversation is None:
            raise s.SessionNotFoundError(f"Session not found: {normalized_session_id}")
        return str(conversation.get("agent_id") or conversation.get("agentId") or "").strip()


def get_session_llm_options(session_id: str) -> dict[str, Any]:
    s = _service()
    if not s._ensure_session_conversation_record(
        str(session_id or "").strip(),
        source="session.llm_options",
    ):
        raise s.SessionNotFoundError(f"Session not found: {str(session_id or '').strip()}")
    current_reasoning_effort = s._session_reasoning_effort_snapshot(session_id)
    model = s._session_fixed_model_choice(session_id)
    return {
        "sessionId": str(session_id or "").strip(),
        "currentModelId": str(model.get("modelRef") or model.get("modelId") or "").strip(),
        "currentReasoningEffort": s.normalize_reasoning_effort(current_reasoning_effort),
        "model": model,
    }


def _normalize_session_agent_profile_id(value: Any) -> str:
    s = _service()
    normalized = str(value or "").strip()
    return normalized or s.DEFAULT_SESSION_AGENT_PROFILE_ID


def llm_bindings_for_profile_id(profile_id: Any) -> dict[str, dict[str, str]]:
    s = _service()
    normalized_profile_id = s._normalize_session_agent_profile_id(profile_id)
    try:
        config = s.get_config()
        profile = config.llm.get_profile(profile_id=normalized_profile_id)
        model_id, _entry = config.llm.get_model_library_entry_for_profile(profile)
    except Exception:
        model_id = ""
    normalized = {"dialogue": {"modelId": str(model_id or "").strip()}} if str(model_id or "").strip() else {}
    return s._normalize_session_agent_llm_bindings(normalized)


def _session_agent_config_for_llm_bindings(agent_instance: dict[str, Any] | None) -> Any:
    s = _service()
    return s._session_agent_config_for_llm_slot(agent_instance, s.SESSION_LLM_SLOT_DIALOGUE)


def _resolve_session_agent_llm(
    agent_instance: dict[str, Any] | None,
    llm_slot: str,
    *,
    reasoning_effort: str | None = None,
) -> Any:
    s = _service()
    normalized_slot = str(llm_slot or "").strip() or s.SESSION_LLM_SLOT_DIALOGUE
    try:
        return s.resolve_agent_llm(
            agent_instance,
            normalized_slot,
            config=s.get_config(),
            runtime_profile_id= "primary",
            fallback_to_dialogue=normalized_slot != "dialogue",
            reasoning_effort_override=reasoning_effort,
        )
    except s.AgentLlmResolutionError as exc:
        raise s.SessionValidationError(str(exc)) from exc


def _session_agent_config_for_llm_slot(agent_instance: dict[str, Any] | None, llm_slot: str) -> Any:
    s = _service()
    return s._resolve_session_agent_llm(agent_instance, llm_slot).config


def _agent_prompt_snapshot_matches_agent(
    snapshot: Any,
    *,
    agent_id: str,
    prompt_template_id: str,
    builtin_content_version: int = 0,
    chat_base_prompt_version: int = 0,
    core_prompt_schema_version: int = 0,
) -> bool:
    s = _service()
    if not isinstance(snapshot, dict):
        return False
    if str(snapshot.get("reason") or "").strip():
        return False
    if str(snapshot.get("agentId") or "").strip() != str(agent_id or "").strip():
        return False
    if str(snapshot.get("promptTemplateId") or snapshot.get("templateId") or "").strip() != str(prompt_template_id or "").strip():
        return False
    try:
        snapshot_builtin_content_version = max(0, int(snapshot.get("builtinContentVersion") or 0))
    except (TypeError, ValueError):
        snapshot_builtin_content_version = 0
    try:
        snapshot_chat_base_prompt_version = max(0, int(snapshot.get("chatBasePromptVersion") or 0))
    except (TypeError, ValueError):
        snapshot_chat_base_prompt_version = 0
    try:
        snapshot_core_prompt_schema_version = max(0, int(snapshot.get("corePromptSchemaVersion") or 0))
    except (TypeError, ValueError):
        snapshot_core_prompt_schema_version = 0
    snapshot_core_prompt_names = tuple(
        str(item.get("name") or "").strip().upper()
        for item in list(snapshot.get("corePrompts") or [])
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    )
    return (
        max(0, int(builtin_content_version or 0)) <= snapshot_builtin_content_version
        and max(0, int(chat_base_prompt_version or 0)) <= snapshot_chat_base_prompt_version
        and max(0, int(core_prompt_schema_version or 0)) <= snapshot_core_prompt_schema_version
        and (
            max(0, int(core_prompt_schema_version or 0)) == 0
            or snapshot_core_prompt_names == tuple(s.prompt_template_service.CORE_PROMPT_NAMES)
        )
    )


def _ensure_session_agent_prompt_snapshot(
    session_id: str,
    agent: dict[str, Any] | None,
    *,
    snapshot_hint: dict[str, Any] | None = None,
    interrupt_checker: Any = None,
) -> dict[str, Any]:
    from core.orchestration.context_engine import raise_if_agent_context_interrupted

    s = _service()
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id or not isinstance(agent, dict):
        return {}
    agent_id = str(agent.get("agentId") or "").strip()
    prompt_template_id = str(agent.get("promptTemplateId") or "").strip()
    if not agent_id or not prompt_template_id:
        return {}
    include_chat_base = str(agent.get("primaryMode") or "").strip().lower() == "chat"
    raise_if_agent_context_interrupted(
        interrupt_checker,
        stage="prepare_prompt_snapshot.versions",
    )
    required_versions = s.prompt_template_service.get_agent_prompt_snapshot_versions(
        prompt_template_id,
        include_chat_base=include_chat_base,
    )
    match_kwargs = {
        "agent_id": agent_id,
        "prompt_template_id": prompt_template_id,
        "builtin_content_version": required_versions.get("builtinContentVersion", 0),
        "chat_base_prompt_version": required_versions.get("chatBasePromptVersion", 0),
        "core_prompt_schema_version": required_versions.get("corePromptSchemaVersion", 0),
    }
    if s._agent_prompt_snapshot_matches_agent(snapshot_hint, **match_kwargs):
        s._record_session_prompt_snapshot_event(
            normalized_session_id,
            agent_id=agent_id,
            snapshot=snapshot_hint,
            outcome="reused",
        )
        return dict(snapshot_hint)
    with s._CHAT_STATE_LOCK:
        conversation = s.load_session_chat_state(s.PROJECT_ROOT, normalized_session_id)
        if conversation is None:
            return {}
        existing = conversation.get("agentPromptSnapshot")
        if s._agent_prompt_snapshot_matches_agent(existing, **match_kwargs):
            s._record_session_prompt_snapshot_event(
                normalized_session_id,
                agent_id=agent_id,
                snapshot=existing,
                outcome="reused",
            )
            return dict(existing)
        had_existing_snapshot = isinstance(existing, dict)
    raise_if_agent_context_interrupted(
        interrupt_checker,
        stage="prepare_prompt_snapshot.before_build",
    )
    snapshot = s.prompt_template_service.build_agent_prompt_snapshot(
        prompt_template_id,
        agent_id=agent_id,
        agent_code=str(agent.get("agentCode") or "").strip(),
        agent_display_name=str(agent.get("displayName") or "").strip(),
        core_prompt_root=Path(__file__).resolve().parents[4],
        include_chat_base=include_chat_base,
    )
    raise_if_agent_context_interrupted(
        interrupt_checker,
        stage="prepare_prompt_snapshot.after_build",
    )
    if str(snapshot.get("reason") or "").strip():
        s._record_session_prompt_snapshot_event(
            normalized_session_id,
            agent_id=agent_id,
            snapshot=snapshot,
            outcome="failed",
        )
        return dict(snapshot)
    with s._CHAT_STATE_LOCK:
        conversation = s.load_session_chat_state(s.PROJECT_ROOT, normalized_session_id)
        if conversation is None:
            return dict(snapshot)
        existing = conversation.get("agentPromptSnapshot")
        if s._agent_prompt_snapshot_matches_agent(existing, **match_kwargs):
            s._record_session_prompt_snapshot_event(
                normalized_session_id,
                agent_id=agent_id,
                snapshot=existing,
                outcome="reused",
            )
            return dict(existing)
        conversation["agentPromptSnapshot"] = dict(snapshot)
        conversation["updated_at"] = s._now_timestamp()
        s.save_session_chat_state(s.PROJECT_ROOT, normalized_session_id, conversation)
        s._record_session_prompt_snapshot_event(
            normalized_session_id,
            agent_id=agent_id,
            snapshot=snapshot,
            outcome="refreshed" if had_existing_snapshot else "created",
        )
        return dict(snapshot)


def _render_agent_prompt_snapshot_block(snapshot: Any) -> str:
    s = _service()
    return s.prompt_template_service.render_agent_prompt_snapshot_system_block(snapshot if isinstance(snapshot, dict) else None)


def _prompt_snapshot_context_segment(snapshot_block: str, snapshot: Any) -> dict[str, Any] | None:
    s = _service()
    text = str(snapshot_block or "").strip()
    if not text:
        return None
    return {
        "key": "agent_prompt_snapshot",
        "block": text,
        "placement": "cache_prefix",
        "stability": "session_static",
        "chars": len(text),
        "hash": hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:16],
        "promptTemplateId": str((snapshot or {}).get("promptTemplateId") or "").strip() if isinstance(snapshot, dict) else "",
        "contentHash": str((snapshot or {}).get("contentHash") or "").strip() if isinstance(snapshot, dict) else "",
    }


def _record_session_prompt_snapshot_event(
    session_id: str,
    *,
    agent_id: str,
    snapshot: dict[str, Any],
    outcome: str,
) -> None:
    s = _service()
    try:
        s.record_runtime_scene_event(
            "conversation",
            "prompt_snapshot",
            f"session.prompt_snapshot.{str(outcome or 'observed').strip() or 'observed'}",
            level="warning" if outcome == "failed" else "info",
            outcome=str(outcome or "observed").strip() or "observed",
            message="Session Agent prompt snapshot state changed.",
            fields={
                "sessionId": str(session_id or "").strip(),
                "agentId": str(agent_id or "").strip(),
                "promptTemplateId": str(snapshot.get("promptTemplateId") or snapshot.get("templateId") or "").strip(),
                "contentHash": str(snapshot.get("contentHash") or "").strip(),
                "contentLength": int(snapshot.get("contentLength") or len(str(snapshot.get("content") or ""))),
                "category": str(snapshot.get("category") or "").strip(),
                "corePromptSchemaVersion": int(snapshot.get("corePromptSchemaVersion") or 0),
                "corePromptHash": str(snapshot.get("corePromptHash") or "").strip(),
                "corePromptNames": ",".join(
                    str(item.get("name") or "").strip()
                    for item in list(snapshot.get("corePrompts") or [])
                    if isinstance(item, dict) and str(item.get("name") or "").strip()
                ),
                "reason": str(snapshot.get("reason") or "").strip(),
                "source": "session_service",
            },
            child_log_path=f"conversations/{s._safe_session_workspace_token(session_id)}-prompt-snapshots.jsonl",
            child_log_payload={
                "session_id": str(session_id or "").strip(),
                "agent_id": str(agent_id or "").strip(),
                "prompt_template_id": str(snapshot.get("promptTemplateId") or snapshot.get("templateId") or "").strip(),
                "content_hash": str(snapshot.get("contentHash") or "").strip(),
                "content_length": int(snapshot.get("contentLength") or len(str(snapshot.get("content") or ""))),
                "category": str(snapshot.get("category") or "").strip(),
                "core_prompt_schema_version": int(snapshot.get("corePromptSchemaVersion") or 0),
                "core_prompt_hash": str(snapshot.get("corePromptHash") or "").strip(),
                "reason": str(snapshot.get("reason") or "").strip(),
                "outcome": str(outcome or "").strip(),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _session_agent_supports_image_input(
    agent_instance: dict[str, Any] | None,
    *,
    slot: str = "dialogue",
) -> bool | None:
    s = _service()
    model_id = s._session_agent_llm_slot_model_id(agent_instance, slot)
    if not model_id:
        return None
    try:
        config = s.get_config()
        resolved = s.resolve_agent_llm(
            agent_instance,
            slot,
            config=config,
            fallback_to_dialogue=slot != "dialogue",
        )
        capability_records = (
            resolved.resolved_spec.provider_details.get("capabilities", {})
            if resolved.resolved_spec is not None
            and isinstance(resolved.resolved_spec.provider_details, dict)
            else {}
        )
        image_input_record = (
            capability_records.get("image_input")
            if isinstance(capability_records, dict)
            else None
        )
        if isinstance(image_input_record, dict):
            capability_value = str(image_input_record.get("value") or "").strip().lower()
            if capability_value == "supported":
                return True
            if capability_value == "unsupported":
                return False
            if capability_value == "unknown":
                return None
        if resolved.capabilities is not None:
            supports_image_input = resolved.capabilities.supports_image_input
            return supports_image_input if isinstance(supports_image_input, bool) else None
        llm_config = config.llm
    except Exception:
        try:
            llm_config = s.get_config().llm
        except Exception:
            return None
    entry = llm_config.model_library.get(model_id)
    if not isinstance(entry, dict):
        return None
    provider_id = str(entry.get("provider_id") or "").strip()
    try:
        provider = llm_config.get_provider(provider_id)
        lowered_provider = str(getattr(provider, "kind", "") or "").strip().lower()
    except Exception:
        lowered_provider = ""
    return s.model_record_image_input_support(entry, provider_kind=lowered_provider)


def _session_agent_dialogue_model_name(agent_instance: dict[str, Any] | None) -> str:
    s = _service()
    return s._session_agent_llm_model_name(agent_instance, slot= "dialogue")


def _session_agent_llm_slot_model_id(agent_instance: dict[str, Any] | None, slot: str) -> str:
    s = _service()
    normalized_slot = str(slot or "").strip() or s.SESSION_LLM_SLOT_DIALOGUE
    return s.agent_llm_model_id(
        agent_instance,
        normalized_slot,
        fallback_to_dialogue=normalized_slot != "dialogue",
    )


def _session_agent_llm_model_name(agent_instance: dict[str, Any] | None, *, slot: str = SESSION_LLM_SLOT_DIALOGUE) -> str:
    s = _service()
    model_id = s._session_agent_llm_slot_model_id(agent_instance, slot)
    if not model_id:
        return ""
    try:
        entry = s.get_config().llm.model_library.get(model_id)
    except Exception:
        return ""
    if not isinstance(entry, dict):
        return ""
    return str(entry.get("model") or entry.get("label") or model_id).strip()


def _image_input_unsupported_message(lang: str, *, model_name: str = "") -> str:
    s = _service()
    model_label = str(model_name or "").strip() or s.text_for(lang, zh="当前模型", en="current model")
    return s.text_for(
        lang,
        zh=f"当前 Agent 使用的对话模型 `{model_label}` 明确不支持图像输入，所以我没有把图片发送给模型。请在 Agent 管理中切换到支持图像输入的对话模型；需要生成/调整图片时，由对话模型理解上下文后再按工具协议调用 image2 工具。",
        en=f"The current Agent dialogue model `{model_label}` does not support image input, so I did not send the image to the model. Switch this Agent to a vision-capable dialogue model; image generation/editing should be invoked by the dialogue model through the image2 tool protocol after it understands the context.",
    )


def _session_agent_runtime_cache_fingerprint(
    *,
    session_workspace: Path,
    agent_instance: dict[str, Any] | None,
    llm_slot: str,
    resolved_llm: Any | None,
    mode: str,
    prompt_snapshot_hash: str,
) -> str:
    s = _service()
    agent = agent_instance if isinstance(agent_instance, dict) else {}
    config = getattr(resolved_llm, "config", None) or s._session_agent_config_for_llm_slot(agent_instance, llm_slot)
    config_payload = s._session_agent_runtime_config_fingerprint_payload(config)
    semantic_agent_fields = {
        key: agent.get(key)
        for key in (
            "agentId",
            "updatedAt",
            "configRevision",
            "configHash",
            "status",
            "primaryMode",
            "promptTemplateId",
            "profileId",
            "roleKey",
            "llmBindings",
            "contextCompressionPolicy",
            "toolPolicy",
            "capabilities",
            "memoryPolicy",
            "workspacePolicy",
        )
        if key in agent
    }
    raw = json.dumps(
        {
            "workspacePath": str(Path(session_workspace).resolve()),
            "agent": semantic_agent_fields,
            "llmSlot": str(llm_slot or "").strip(),
            "llmModelId": str(getattr(resolved_llm, "model_id", "") or "").strip(),
            "mode": str(mode or "chat").strip(),
            "promptSnapshotHash": str(prompt_snapshot_hash or "").strip(),
            "config": config_payload,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()


def _session_agent_runtime_config_fingerprint_payload(config: Any) -> Any:
    """Keep session runtime reuse tied only to config consumed by chat Agents.

    The AppConfig also contains unrelated runtime domains (for example UI and
    pet state). Including the whole object causes a new Agent and transport on
    ordinary chat turns even when the dialogue model contract is unchanged.
    """
    s = _service()

    if hasattr(config, "model_dump"):
        try:
            raw_payload: Any = config.model_dump(mode="json")
        except (TypeError, ValueError):
            raw_payload = config.model_dump()
    elif hasattr(config, "dict"):
        raw_payload = config.dict()
    elif isinstance(config, Mapping):
        raw_payload = dict(config)
    else:
        return repr(config)
    if not isinstance(raw_payload, Mapping):
        return raw_payload
    return {
        key: raw_payload[key]
        for key in s._SESSION_AGENT_RUNTIME_CONFIG_FINGERPRINT_KEYS
        if key in raw_payload
    }


def _invalidate_session_agent_runtime_cache(session_id: str = "") -> int:
    s = _service()
    normalized_session_id = str(session_id or "").strip()
    removed = 0
    with s._SESSION_AGENT_RUNTIME_CACHE_LOCK:
        if not normalized_session_id:
            removed = len(s._SESSION_AGENT_RUNTIME_CACHE)
            s._SESSION_AGENT_RUNTIME_CACHE.clear()
            return removed
        prefix = f"{normalized_session_id}|"
        for cache_key in [key for key in s._SESSION_AGENT_RUNTIME_CACHE if key.startswith(prefix)]:
            s._SESSION_AGENT_RUNTIME_CACHE.pop(cache_key, None)
            removed += 1
    return removed


def _acquire_chat_agent_for_session(
    session_id: str,
    session_workspace: Path,
    agent_instance: dict[str, Any] | None,
    llm_slot: str = "dialogue",
    resolved_llm: Any | None = None,
    mode: str = "chat",
    prompt_snapshot_hash: str = "",
) -> tuple[Any, dict[str, Any]]:
    s = _service()
    normalized_session_id = str(session_id or "").strip()
    normalized_slot = str(llm_slot or s.SESSION_LLM_SLOT_DIALOGUE).strip() or s.SESSION_LLM_SLOT_DIALOGUE
    normalized_mode = str(mode or "chat").strip() or "chat"
    cache_allowed = bool(normalized_session_id and isinstance(agent_instance, dict) and normalized_mode == "chat")
    if not cache_allowed:
        with s._SESSION_AGENT_RUNTIME_CACHE_LOCK:
            entry_count = len(s._SESSION_AGENT_RUNTIME_CACHE)
        return (
            s._create_chat_agent_for_session(
                session_workspace,
                agent_instance,
                llm_slot=normalized_slot,
                resolved_llm=resolved_llm,
                mode=normalized_mode,
            ),
            {"status": "bypassed", "hit": False, "entryCount": entry_count},
        )

    fingerprint = s._session_agent_runtime_cache_fingerprint(
        session_workspace=session_workspace,
        agent_instance=agent_instance,
        llm_slot=normalized_slot,
        resolved_llm=resolved_llm,
        mode=normalized_mode,
        prompt_snapshot_hash=prompt_snapshot_hash,
    )
    cache_key = f"{normalized_session_id}|{normalized_slot}"
    with s._SESSION_AGENT_RUNTIME_CACHE_LOCK:
        cached = s._SESSION_AGENT_RUNTIME_CACHE.get(cache_key)
        if cached and str(cached.get("fingerprint") or "") == fingerprint:
            cached["lastAccess"] = s._perf_counter()
            runtime_agent = cached.get("agent")
            entry_count = len(s._SESSION_AGENT_RUNTIME_CACHE)
        else:
            runtime_agent = None
            entry_count = len(s._SESSION_AGENT_RUNTIME_CACHE)
    if runtime_agent is not None:
        prepare_reuse = getattr(runtime_agent, "prepare_for_session_turn_reuse", None)
        if callable(prepare_reuse):
            prepare_reuse()
        return runtime_agent, {
            "status": "hit",
            "hit": True,
            "entryCount": entry_count,
        }

    runtime_agent = s._create_chat_agent_for_session(
        session_workspace,
        agent_instance,
        llm_slot=normalized_slot,
        resolved_llm=resolved_llm,
        mode=normalized_mode,
    )
    with s._SESSION_AGENT_RUNTIME_CACHE_LOCK:
        s._SESSION_AGENT_RUNTIME_CACHE[cache_key] = {
            "agent": runtime_agent,
            "fingerprint": fingerprint,
            "lastAccess": s._perf_counter(),
        }
        while len(s._SESSION_AGENT_RUNTIME_CACHE) > s._SESSION_AGENT_RUNTIME_CACHE_MAX_ENTRIES:
            oldest_key = min(
                s._SESSION_AGENT_RUNTIME_CACHE,
                key=lambda key: float(s._SESSION_AGENT_RUNTIME_CACHE.get(key, {}).get("lastAccess") or 0.0),
            )
            s._SESSION_AGENT_RUNTIME_CACHE.pop(oldest_key, None)
        entry_count = len(s._SESSION_AGENT_RUNTIME_CACHE)
    return runtime_agent, {"status": "miss", "hit": False, "entryCount": entry_count}


def _create_chat_agent_for_session(
    session_workspace: Path,
    agent_instance: dict[str, Any] | None,
    llm_slot: str = "dialogue",
    resolved_llm: Any | None = None,
    mode: str = "chat",
) -> Any:
    s = _service()
    agent_config = getattr(resolved_llm, "config", None) or s._session_agent_config_for_llm_slot(agent_instance, llm_slot)
    runtime_agent_binding = None
    if isinstance(agent_instance, dict):
        runtime_agent_binding = {
            key: value
            for key, value in {
                "agentId": str(agent_instance.get("agentId") or "").strip(),
                "directSessionId": str(agent_instance.get("directSessionId") or "").strip(),
                "workspacePath": str(agent_instance.get("workspacePath") or "").strip(),
                "llmSlot": str(llm_slot or SESSION_LLM_SLOT_DIALOGUE).strip() or SESSION_LLM_SLOT_DIALOGUE,
            }.items()
            if value
        }
    runtime_agent = s.call_agent_factory_with_supported_kwargs(
        s.create_chat_agent,
        mode=mode,
        workspace_path=session_workspace,
        config=agent_config,
        runtime_agent_binding=runtime_agent_binding,
    )
    try:
        runtime_agent._allow_session_subagent_auto_delegation = False
    except (AttributeError, TypeError):
        pass
    return runtime_agent


def create_chat_agent(
    workspace_path: str | Path | None = None,
    config: Any | None = None,
    mode: str = "chat",
    runtime_agent_binding: dict[str, Any] | None = None,
) -> Any:
    s = _service()
    runtime_agent = s.create_agent_runtime(
        mode=str(mode or "chat").strip() or "chat",
        workspace_path=str(workspace_path) if workspace_path else None,
        config=config,
        runtime_agent_binding=runtime_agent_binding,
    )
    # Chat-surface runtimes must not treat the raw user prompt as the effective
    # goal: otherwise the whole prompt is re-injected into RUNTIME_GOAL and
    # MEMORY on every turn. Mirrors _create_chat_agent_for_session below so
    # direct factory callers (chat room speakers) get the stable constant goal.
    try:
        runtime_agent._allow_session_subagent_auto_delegation = False
    except (AttributeError, TypeError):
        pass
    return runtime_agent


def _attach_session_llm_runtime_diagnostics(result: Any, diagnostics: dict[str, Any] | None) -> Any:
    s = _service()
    if not isinstance(result, dict) or not isinstance(diagnostics, dict) or not diagnostics:
        return result
    allowed_keys = {
        "llmModelId",
        "runtimeProfileId",
        "providerId",
        "providerKind",
        "model",
    }
    sanitized = {
        str(key): str(value).strip()
        for key, value in diagnostics.items()
        if str(key or "").strip() in allowed_keys and str(value or "").strip()
    }
    if not sanitized:
        return result
    metadata = dict(result.get("metadata") or {}) if isinstance(result.get("metadata"), dict) else {}
    for key, value in sanitized.items():
        metadata.setdefault(key, value)
    result["metadata"] = metadata
    llm_failure = dict(result.get("llm_failure") or {}) if isinstance(result.get("llm_failure"), dict) else {}

    def fill_empty(key: str, value: str) -> None:
        if value and not str(llm_failure.get(key) or "").strip():
            llm_failure[key] = value

    fill_empty("provider", sanitized.get("providerId") or sanitized.get("provider") or "")
    fill_empty("provider_id", sanitized.get("providerId") or "")
    fill_empty("providerId", sanitized.get("providerId") or "")
    fill_empty("provider_kind", sanitized.get("providerKind") or "")
    fill_empty("providerKind", sanitized.get("providerKind") or "")
    fill_empty("model", sanitized.get("model") or "")
    fill_empty("llm_model_id", sanitized.get("llmModelId") or "")
    fill_empty("llmModelId", sanitized.get("llmModelId") or "")
    fill_empty("runtime_profile_id", sanitized.get("runtimeProfileId") or "")
    fill_empty("runtimeProfileId", sanitized.get("runtimeProfileId") or "")
    result["llm_failure"] = llm_failure
    return result


def _session_agent_unavailable_message(reason: str, *, lang: str) -> str:
    s = _service()
    if str(reason or "").strip() == "archived_agent":
        return s.text_for(
            lang,
            zh="当前会话引用的 Agent 已归档，不能继续运行。请在 Agent 管理中心选择 active Agent 或显式恢复后再发送。",
            en="This session references an archived Agent and cannot run. Choose an active Agent in Agent Center or explicitly restore it first.",
        )
    return s.text_for(
        lang,
        zh="当前会话缺少有效 Agent，不能继续运行。请在 Agent 管理中心选择 active Agent 后再发送。",
        en="This session has no valid Agent and cannot run. Choose an active Agent in Agent Center first.",
    )


def _record_session_agent_unavailable_event(
    session_id: str,
    *,
    agent_id: str,
    reason: str,
    agent_status: str = "",
) -> None:
    s = _service()
    normalized_reason = str(reason or "").strip() or "missing_agent"
    event_code = (
        "conversation.turn.blocked_archived_agent"
        if normalized_reason == "archived_agent"
        else "conversation.turn.blocked_missing_agent"
    )
    try:
        s.record_runtime_scene_event(
            "conversation",
            "turn_blocked",
            event_code,
            message="Web chat turn blocked because the session Agent is unavailable.",
            level="warning",
            outcome="blocked",
            fields={
                "sessionId": str(session_id or "").strip(),
                "agentId": str(agent_id or "").strip(),
                "reason": normalized_reason,
                "agentStatus": str(agent_status or "").strip(),
            },
            lifecycle=True,
        )
    except Exception as exc:
        s._debug_logger.warning(
            f"runtime scene unavailable agent log skipped: {type(exc).__name__}: {exc}",
            tag="LOGS",
        )


def _record_session_llm_usage_event(
    session_id: str,
    turn_id: str,
    llm_usage: dict[str, Any] | None,
) -> None:
    s = _service()
    normalized = s._normalize_turn_llm_usage(llm_usage)
    source = str((normalized or {}).get("source") or "missing").strip() or "missing"
    observed = source == "provider_usage"
    fields = {
        "sessionId": str(session_id or "").strip(),
        "turnId": str(turn_id or "").strip(),
        "source": source,
        "inputTokens": int((normalized or {}).get("inputTokens") or 0),
        "outputTokens": int((normalized or {}).get("outputTokens") or 0),
        "totalTokens": int((normalized or {}).get("totalTokens") or 0),
        "cachedInputTokens": int((normalized or {}).get("cachedInputTokens") or 0),
        "cacheReadInputTokens": int((normalized or {}).get("cacheReadInputTokens") or (normalized or {}).get("cachedInputTokens") or 0),
        "cacheCreationInputTokens": int((normalized or {}).get("cacheCreationInputTokens") or 0),
        "uncachedInputTokens": int((normalized or {}).get("uncachedInputTokens") or 0),
        "cacheHitRate": float((normalized or {}).get("cacheHitRate") or 0.0),
        "promptCacheScope": str((normalized or {}).get("promptCacheScope") or "").strip(),
        "promptCachePartition": str((normalized or {}).get("promptCachePartition") or "").strip(),
        "llmModelId": str((normalized or {}).get("llmModelId") or "").strip(),
        "provider": str((normalized or {}).get("provider") or "").strip(),
        "model": str((normalized or {}).get("model") or "").strip(),
    }
    event_code = "conversation.llm_usage.recorded" if observed else "conversation.llm_usage.missing"
    try:
        result = s.record_runtime_scene_event(
            "conversation",
            "llm_usage",
            event_code,
            level="info" if observed else "warning",
            outcome="recorded" if observed else "missing",
            message="Conversation turn LLM usage recorded." if observed else "Conversation turn LLM usage missing.",
            fields=fields,
            child_log_path=f"conversations/{s._safe_session_workspace_token(str(session_id or '').strip())}-turns.jsonl",
            child_log_payload=fields,
            lifecycle=False,
        )
        if isinstance(result, dict) and result.get("accepted") is False:
            reason = str(result.get("reason") or "unknown").strip() or "unknown"
            s._debug_logger.warning(
                (
                    "conversation llm usage runtime scene event rejected: "
                    f"eventCode={event_code} reason={reason} "
                    f"sessionId={fields['sessionId']} turnId={fields['turnId']} "
                    f"source={source} inputTokens={fields['inputTokens']} "
                    f"cachedInputTokens={fields['cachedInputTokens']}"
                ),
                tag="CHAT",
            )
    except Exception:
        return


def _record_session_agent_binding_recovered_event(session_id: str, *, agent_id: str) -> None:
    s = _service()
    try:
        s.record_runtime_scene_event(
            "conversation",
            "agent_binding",
            "conversation.agent_binding.recovered",
            message="Recovered a direct-session Agent binding from stale missing-agent metadata.",
            level="info",
            outcome="recovered",
            fields={
                "sessionId": str(session_id or "").strip(),
                "agentId": str(agent_id or "").strip(),
                "source": "session_agent_metadata_repair",
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_session_agent_child_direct_binding_repaired_event(
    session_id: str,
    *,
    agent_id: str,
    previous_direct_session_id: str,
) -> None:
    s = _service()
    normalized_session_id = str(session_id or "").strip()
    previous_session_id = str(previous_direct_session_id or "").strip()
    try:
        s.record_runtime_scene_event(
            "conversation",
            "session_agent_child_direct_binding_repaired",
            "session.agent_child_direct_binding_repaired",
            level="warning",
            outcome="repaired",
            message="Root session repaired an Agent directSessionId that pointed at one of its child sessions.",
            fields={
                "sessionId": normalized_session_id,
                "agentId": str(agent_id or "").strip(),
                "previousDirectSessionId": previous_session_id,
                "source": "session_child_contract_repair",
            },
            child_log_path=f"conversations/{s._safe_session_workspace_token(normalized_session_id)}-agent-bindings.jsonl",
            child_log_payload={
                "session_id": normalized_session_id,
                "agent_id": str(agent_id or "").strip(),
                "previous_direct_session_id": previous_session_id,
                "source": "session_child_contract_repair",
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_session_agent_binding_updated_event(
    session_id: str,
    *,
    agent_id: str,
    source: str,
    prompt_template_id: str = "",
    role_key: str = "",
) -> None:
    s = _service()
    normalized_session_id = str(session_id or "").strip()
    try:
        s.record_runtime_scene_event(
            "conversation",
            "session_agent_binding_updated",
            "session.agent_binding_updated",
            level="info",
            outcome="updated",
            message="Session Agent binding updated.",
            fields={
                "sessionId": normalized_session_id,
                "agentId": str(agent_id or "").strip(),
                "promptTemplateId": str(prompt_template_id or "").strip(),
                "roleKey": str(role_key or "").strip(),
                "source": str(source or "").strip(),
            },
            child_log_path=f"conversations/{s._safe_session_workspace_token(normalized_session_id)}-agent-bindings.jsonl",
            child_log_payload={
                "session_id": normalized_session_id,
                "agent_id": str(agent_id or "").strip(),
                "prompt_template_id": str(prompt_template_id or "").strip(),
                "role_key": str(role_key or "").strip(),
                "source": str(source or "").strip(),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_session_agent_missing_index_event(
    summary: dict[str, Any],
    *,
    source: str,
) -> None:
    s = _service()
    session_id = str(summary.get("id") or "").strip()
    if not session_id:
        return
    agent_status_code = str(summary.get("agentStatusCode") or "").strip()
    agent_id = str(summary.get("agentId") or summary.get("agentMissingId") or "").strip()
    normalized_source = str(source or "").strip()
    dedupe_key = (str(s.PROJECT_ROOT.resolve()), session_id, agent_id, agent_status_code, normalized_source)
    with s._SESSION_INDEX_EVENT_DEDUPE_LOCK:
        if dedupe_key in s._SESSION_MISSING_INDEX_EVENT_KEYS:
            return
        s._SESSION_MISSING_INDEX_EVENT_KEYS.add(dedupe_key)
    try:
        s.record_runtime_scene_event(
            "conversation",
            "session_agent_missing",
            "session.agent_missing.hidden_from_index",
            level="info",
            outcome="hidden_control",
            message="Known stale session hidden from indexes because its bound Agent is missing or archived.",
            fields={
                "sessionId": session_id,
                "agentId": agent_id,
                "agentStatusCode": agent_status_code,
                "source": normalized_source,
                "hiddenFromIndex": True,
                "controlSignal": True,
            },
            child_log_path=f"conversations/{s._safe_session_workspace_token(session_id)}-agent-bindings.jsonl",
            child_log_payload={
                "session_id": session_id,
                "agent_id": agent_id,
                "agent_status_code": agent_status_code,
                "agent_status_message": s.trim_lines(str(summary.get("agentStatusMessage") or ""), max_lines=2),
                "source": normalized_source,
                "hidden_from_index": True,
                "control_signal": True,
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_session_agent_missing_index_batch_event(
    summaries: list[dict[str, Any]],
    *,
    source: str,
) -> None:
    s = _service()
    normalized_source = str(source or "").strip()
    samples: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    hidden_count = 0
    for summary in list(summaries or []):
        if not isinstance(summary, dict):
            continue
        session_id = str(summary.get("id") or "").strip()
        if not session_id:
            continue
        agent_id = str(summary.get("agentId") or summary.get("agentMissingId") or "").strip()
        agent_status_code = str(summary.get("agentStatusCode") or "").strip()
        dedupe_key = (session_id, agent_id, agent_status_code)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        hidden_count += 1
        if len(samples) < 8:
            samples.append(
                {
                    "sessionId": session_id,
                    "agentId": agent_id,
                    "agentStatusCode": agent_status_code,
                    "agentStatusMessage": s.trim_lines(str(summary.get("agentStatusMessage") or ""), max_lines=2),
                }
            )
    if hidden_count <= 0:
        return
    dedupe_key = (
        str(s.PROJECT_ROOT.resolve()),
        normalized_source,
        hidden_count,
        tuple((item["sessionId"], item["agentId"], item["agentStatusCode"]) for item in samples),
    )
    with s._SESSION_INDEX_EVENT_DEDUPE_LOCK:
        if dedupe_key in s._SESSION_MISSING_INDEX_BATCH_EVENT_KEYS:
            return
        s._SESSION_MISSING_INDEX_BATCH_EVENT_KEYS.add(dedupe_key)
    try:
        s.record_runtime_scene_event(
            "conversation",
            "session_agent_missing_batch",
            "session.agent_missing.hidden_from_index.batch",
            level="info",
            outcome="hidden_control",
            message="Known stale sessions hidden from indexes because their bound Agents are missing or archived.",
            fields={
                "source": normalized_source,
                "hiddenCount": hidden_count,
                "sampleSessions": samples,
                "sampleCount": len(samples),
                "hiddenFromIndex": True,
                "controlSignal": True,
            },
            lifecycle=False,
        )
    except Exception:
        return
