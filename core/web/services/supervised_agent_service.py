"""Persistent AgentInstance alignment for supervised evolution roles."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.ui.chat_state import load_chat_state, save_chat_state

from . import agent_directory_service, session_service
from . import agent_mode_binding_service
from .runtime_scene_service import record_runtime_scene_event


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class SupervisedAgentBindingError(ValueError):
    """Raised when a supervised fixed role cannot resolve its bound Agent."""


@dataclass(frozen=True)
class SupervisedAgentRole:
    role: str
    label: str


SUPERVISED_AGENT_ROLES: tuple[SupervisedAgentRole, ...] = (
    SupervisedAgentRole("baseline", "监督进化基线 Agent"),
    SupervisedAgentRole("candidate", "监督进化候选 Agent"),
    SupervisedAgentRole("reviewer", "监督进化评审 Agent"),
    SupervisedAgentRole("auditor", "监督进化审计 Agent"),
    SupervisedAgentRole("judge", "监督进化裁决 Agent"),
)
CORE_SUPERVISED_AGENT_ROLES = {"judge"}
PREFERRED_SUPERVISED_MODEL_IDS = (
    "xiaomi_mimo_v2_5_pro_token_plan",
    "generated_xiaomi_mimo_v2_5_cdff497b2d9b",
    "xiaomi_mimo_v2_5_multimodal",
)


def ensure_supervised_agent_instances() -> list[dict[str, Any]]:
    """Ensure supervised evolution roles are visible as persistent AgentInstances."""

    project_root = Path(PROJECT_ROOT).resolve()
    previous_session_root = session_service.PROJECT_ROOT
    previous_agent_root = agent_directory_service.PROJECT_ROOT
    previous_binding_root = agent_mode_binding_service.PROJECT_ROOT
    session_service.PROJECT_ROOT = project_root
    agent_directory_service.PROJECT_ROOT = project_root
    agent_mode_binding_service.PROJECT_ROOT = project_root
    original_active_session_id = _active_session_id(project_root)
    ensured: list[dict[str, Any]] = []
    changed_roles: list[str] = []
    try:
        for role in SUPERVISED_AGENT_ROLES:
            try:
                agent, changed = _ensure_supervised_role(role)
            except Exception as exc:
                _record_supervised_agent_event(
                    "supervised.agent_instance.sync_failed",
                    role=role,
                    level="warning",
                    outcome="failed",
                    fields={"errorType": type(exc).__name__, "message": str(exc)},
                )
                continue
            if not agent:
                continue
            ensured.append(agent)
            if changed:
                changed_roles.append(role.role)
        if changed_roles:
            _restore_active_session(project_root, original_active_session_id)
            try:
                record_runtime_scene_event(
                    "agent_directory",
                    "agent",
                    "supervised.agent_instance.synced",
                    message="Supervised evolution agent instances synced",
                    level="info",
                    outcome="written",
                    fields={
                        "roleCount": len(SUPERVISED_AGENT_ROLES),
                        "changedRoles": changed_roles,
                        "agentIds": [str(agent.get("agentId") or "") for agent in ensured],
                    },
                    lifecycle=True,
                )
            except Exception:
                pass
        _sync_supervised_mode_binding(ensured, preserve_existing_slots=True)
    finally:
        session_service.PROJECT_ROOT = previous_session_root
        agent_directory_service.PROJECT_ROOT = previous_agent_root
        agent_mode_binding_service.PROJECT_ROOT = previous_binding_root
    return ensured


def _supervised_role_llm_bindings(role: str) -> dict[str, dict[str, str]]:
    model_id = _supervised_role_model_id(role)
    if model_id:
        return {"dialogue": {"modelId": model_id}}
    return session_service.default_session_llm_bindings()


def _supervised_role_model_id(role: str) -> str:
    normalized_role = str(role or "").strip()
    config = _current_config()
    profile_ids = []
    if normalized_role:
        profile_ids.append(f"supervised_{normalized_role}")
    for profile_id in profile_ids:
        try:
            profile = config.llm.get_profile(profile_id=profile_id)
            model_id, _entry = config.llm.get_model_library_entry_for_profile(profile)
        except Exception:
            continue
        normalized_model_id = str(model_id or "").strip()
        if normalized_model_id:
            return normalized_model_id
    preferred_model_id = _preferred_supervised_model_id(config)
    if preferred_model_id:
        return preferred_model_id
    try:
        profile = config.llm.get_profile(profile_id="primary")
        model_id, _entry = config.llm.get_model_library_entry_for_profile(profile)
    except Exception:
        return ""
    return str(model_id or "").strip()


def _preferred_supervised_model_id(config: Any) -> str:
    try:
        model_library = getattr(config.llm, "model_library", {}) or {}
    except Exception:
        return ""
    if not isinstance(model_library, dict):
        return ""
    for model_id in PREFERRED_SUPERVISED_MODEL_IDS:
        if model_id in model_library:
            return model_id
    try:
        providers = getattr(config.llm, "providers", {}) or {}
    except Exception:
        providers = {}
    if not isinstance(providers, dict):
        providers = {}
    for model_id, item in model_library.items():
        if not isinstance(item, dict):
            continue
        provider_id = str(item.get("provider_id") or "").strip()
        provider = providers.get(provider_id)
        provider_kind = str(getattr(provider, "kind", "") or "").strip().lower()
        if provider_kind == "xiaomi":
            return str(model_id or "").strip()
    return ""


def supervised_agent_bindings() -> dict[str, dict[str, Any]]:
    """Return run-safe AgentInstance bindings keyed by supervised role."""

    raw_slots = _raw_supervised_mode_slots()
    raw_registry = _load_raw_agent_registry_state()
    config = _current_config()
    try:
        model_library_ids = _configured_model_library_ids(config)
    except TypeError:
        model_library_ids = _configured_model_library_ids()
    _assert_raw_supervised_slot_dialogue_bindings(raw_slots, raw_registry, model_library_ids=model_library_ids)
    ensure_supervised_agent_instances()
    raw_agents = {
        str(agent.get("agentId") or "").strip(): agent
        for agent in (_load_raw_agent_registry_state().get("agents") or [])
        if isinstance(agent, dict) and str(agent.get("agentId") or "").strip()
    }
    bindings: dict[str, dict[str, Any]] = {}
    mode_payload = agent_mode_binding_service.get_mode_bindings_payload()
    supervised_mode = (mode_payload.get("modes") or {}).get("supervised_evolution")
    slots = supervised_mode.get("slots") if isinstance(supervised_mode, dict) else {}
    for role in [item.role for item in SUPERVISED_AGENT_ROLES]:
        raw_agent_id = str(raw_slots.get(role) or "").strip()
        if raw_agent_id and not agent_directory_service.get_agent(raw_agent_id, include_archived=False):
            _record_supervised_binding_failure(role, agent_id=raw_agent_id, reason="missing_or_archived_slot_agent")
            raise SupervisedAgentBindingError(
                f"Supervised role slot points to an archived or missing Agent: {role} ({raw_agent_id})"
            )
        stale_warning = _supervised_slot_warning(mode_payload, role)
        if stale_warning:
            agent_id = str(stale_warning.get("agentId") or "").strip()
            _record_supervised_binding_failure(role, agent_id=agent_id, reason="missing_or_archived_slot_agent")
            raise SupervisedAgentBindingError(
                f"Supervised role slot points to an archived or missing Agent: {role} ({agent_id or 'unknown'})"
            )
        agent_id = str((slots or {}).get(role) or "").strip()
        if not agent_id:
            _record_supervised_binding_failure(role, agent_id="", reason="missing_slot_agent")
            raise SupervisedAgentBindingError(f"Supervised role slot is not configured: {role}")
        agent = agent_directory_service.get_agent(agent_id, include_archived=False)
        if not agent:
            _record_supervised_binding_failure(role, agent_id=agent_id, reason="missing_or_archived_slot_agent")
            raise SupervisedAgentBindingError(f"Supervised role slot points to an archived or missing Agent: {role} ({agent_id})")
        raw_agent = raw_agents.get(agent_id) if isinstance(raw_agents.get(agent_id), dict) else agent
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        llm_bindings = agent_directory_service.normalize_agent_llm_bindings(raw_agent.get("llmBindings"))
        dialogue_model_id = agent_directory_service.agent_dialogue_model_id({"llmBindings": llm_bindings})
        if not dialogue_model_id:
            _record_supervised_binding_failure(role, agent_id=agent_id, reason="missing_dialogue_llm_binding")
            raise SupervisedAgentBindingError(
                f"Supervised role Agent is missing required dialogue LLM binding: {role} ({agent_id})"
            )
        if model_library_ids and dialogue_model_id not in model_library_ids:
            _record_supervised_binding_failure(
                role,
                agent_id=agent_id,
                reason="unresolved_dialogue_model_reference",
                model_id=dialogue_model_id,
            )
            raise SupervisedAgentBindingError(
                f"Supervised role Agent dialogue model is not present in model library: {role} ({agent_id}) modelId={dialogue_model_id}"
            )
        if _config_model_library_contains(config, dialogue_model_id):
            _assert_supervised_binding_model_ready(
                role,
                agent_id=agent_id,
                model_id=dialogue_model_id,
                config=config,
            )
        bindings[role] = {
            "agentId": str(agent.get("agentId") or "").strip(),
            "agentCode": str(agent.get("agentCode") or "").strip(),
            "displayName": str(agent.get("displayName") or "").strip(),
            "primaryMode": str(agent.get("primaryMode") or "").strip(),
            "roleKey": str(agent.get("roleKey") or role).strip() or role,
            "llmBindings": llm_bindings,
            "dialogueModelId": dialogue_model_id,
            "llmSlot": "dialogue",
            "promptTemplateId": str(agent.get("promptTemplateId") or "").strip(),
            "directSessionId": str(agent.get("directSessionId") or "").strip(),
            "workspacePath": str(agent.get("workspacePath") or "").strip(),
            "toolPolicyId": str(agent.get("toolPolicyId") or "").strip(),
            "memoryPolicyId": str(agent.get("memoryPolicyId") or "").strip(),
            "role": role,
            "roleLabel": str(metadata.get("supervisedRoleLabel") or role).strip(),
        }
    return bindings


def _current_config() -> Any:
    from config.settings import get_config

    return get_config()


def _load_raw_agent_registry_state() -> dict[str, Any]:
    try:
        payload = json.loads(agent_directory_service.registry_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _configured_model_library_ids(config: Any | None = None) -> set[str]:
    try:
        resolved_config = config or _current_config()
        model_library = getattr(resolved_config.llm, "model_library", {}) or {}
    except Exception:
        return set()
    if not isinstance(model_library, dict):
        return set()
    return {str(model_id or "").strip() for model_id in model_library.keys() if str(model_id or "").strip()}


def _config_model_library_contains(config: Any, model_id: str) -> bool:
    try:
        model_library = getattr(config.llm, "model_library", {}) or {}
    except Exception:
        return False
    return isinstance(model_library, dict) and str(model_id or "").strip() in model_library


def _assert_supervised_binding_model_ready(
    role: str,
    *,
    agent_id: str,
    model_id: str,
    config: Any,
) -> None:
    try:
        from core.llm.agent_runtime import config_for_agent_llm_model

        runtime_config = config_for_agent_llm_model(
            config,
            model_id=model_id,
            runtime_profile_id="primary",
            slot="dialogue",
        )
        profile = runtime_config.llm.get_profile(profile_id="primary")
        provider = runtime_config.llm.get_provider(profile.provider_id)
        api_key = runtime_config.get_api_key_for_profile(profile_id="primary")
        api_key_source = runtime_config.llm.get_api_key_source_label_for_profile(profile_id="primary")
        api_key_env = str(getattr(profile, "api_key_env", "") or "").strip()
        if bool(getattr(provider, "requires_api_key", True)) and not api_key:
            _record_supervised_binding_failure(
                role,
                agent_id=agent_id,
                reason="missing_dialogue_model_api_key",
                model_id=model_id,
                extra_fields={
                    "apiKeyEnv": api_key_env,
                    "apiKeySource": api_key_source,
                    "providerKind": str(getattr(provider, "kind", "") or "").strip(),
                },
            )
            raise SupervisedAgentBindingError(
                f"Supervised role Agent dialogue model has no configured API key: {role} ({agent_id}) modelId={model_id} apiKeyEnv={api_key_env or 'unknown'}"
            )
    except SupervisedAgentBindingError:
        raise
    except Exception as exc:
        _record_supervised_binding_failure(
            role,
            agent_id=agent_id,
            reason="dialogue_model_resolution_failed",
            model_id=model_id,
            extra_fields={"errorType": type(exc).__name__, "message": str(exc)},
        )
        raise SupervisedAgentBindingError(
            f"Supervised role Agent dialogue model cannot be resolved: {role} ({agent_id}) modelId={model_id}: {type(exc).__name__}: {exc}"
        ) from exc


def _assert_raw_supervised_slot_dialogue_bindings(
    raw_slots: dict[str, str],
    raw_registry: dict[str, Any],
    *,
    model_library_ids: set[str] | None = None,
) -> None:
    if not raw_slots:
        return
    raw_agents = {
        str(agent.get("agentId") or "").strip(): agent
        for agent in (raw_registry.get("agents") or [])
        if isinstance(agent, dict) and str(agent.get("agentId") or "").strip()
    }
    for role, agent_id in raw_slots.items():
        normalized_role = str(role or "").strip()
        normalized_agent_id = str(agent_id or "").strip()
        if not normalized_role or not normalized_agent_id:
            continue
        agent = raw_agents.get(normalized_agent_id)
        if not isinstance(agent, dict):
            continue
        raw_bindings = agent.get("llmBindings") if isinstance(agent.get("llmBindings"), dict) else {}
        dialogue = raw_bindings.get("dialogue") if isinstance(raw_bindings.get("dialogue"), dict) else {}
        model_id = str(dialogue.get("modelId") or "").strip()
        if model_id:
            if model_library_ids and model_id not in model_library_ids:
                _record_supervised_binding_failure(
                    normalized_role,
                    agent_id=normalized_agent_id,
                    reason="unresolved_dialogue_model_reference",
                    model_id=model_id,
                )
                raise SupervisedAgentBindingError(
                    f"Supervised role Agent dialogue model is not present in model library: {normalized_role} ({normalized_agent_id}) modelId={model_id}"
                )
            continue
        _record_supervised_binding_failure(
            normalized_role,
            agent_id=normalized_agent_id,
            reason="missing_dialogue_llm_binding",
        )
        raise SupervisedAgentBindingError(
            f"Supervised role Agent is missing required dialogue LLM binding: {normalized_role} ({normalized_agent_id})"
        )


def _raw_supervised_mode_slots() -> dict[str, str]:
    path = agent_mode_binding_service.mode_binding_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    for item in payload.get("bindings") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("mode") or "").strip() != "supervised_evolution":
            continue
        slots = item.get("slots") if isinstance(item.get("slots"), dict) else {}
        return {str(key): str(value or "").strip() for key, value in slots.items()}
    return {}


def _supervised_slot_warning(mode_payload: dict[str, Any], role: str) -> dict[str, str] | None:
    expected_field = f"slots.{role}"
    for warning in mode_payload.get("repairWarnings") or []:
        if not isinstance(warning, dict):
            continue
        if str(warning.get("mode") or "").strip() != "supervised_evolution":
            continue
        if str(warning.get("field") or "").strip() == expected_field:
            return {str(key): str(value or "") for key, value in warning.items()}
    return None


def _record_supervised_binding_failure(
    role: str,
    *,
    agent_id: str,
    reason: str,
    model_id: str = "",
    extra_fields: dict[str, Any] | None = None,
) -> None:
    fields = {
        "mode": "supervised_evolution",
        "slot": str(role or "").strip(),
        "roleKey": str(role or "").strip(),
        "agentId": str(agent_id or "").strip(),
        "modelId": str(model_id or "").strip(),
        "source": "ModeBinding.slots",
        "reason": str(reason or "").strip(),
    }
    if extra_fields:
        fields.update(extra_fields)
    try:
        record_runtime_scene_event(
            "agent_runtime",
            "supervised_evolution",
            "agent_runtime.resolve_failed",
            message="Supervised evolution role Agent resolution failed",
            level="error",
            outcome="failed",
            fields=fields,
            lifecycle=True,
        )
    except Exception:
        return
def _sync_supervised_mode_binding(agents: list[dict[str, Any]], *, preserve_existing_slots: bool = False) -> None:
    active_agents = [
        agent
        for agent in agents
        if str(agent.get("agentId") or "").strip()
        and str(agent.get("status") or "active").strip() != "archived"
    ]
    active_agent_ids = [str(agent.get("agentId") or "").strip() for agent in active_agents]
    slots = {}
    excluded_slots: list[str] | None = None
    if preserve_existing_slots:
        try:
            payload = agent_mode_binding_service.get_mode_bindings_payload()
            mode = (payload.get("modes") or {}).get("supervised_evolution") or {}
            existing = mode.get("slots")
            if isinstance(existing, dict):
                slots.update({str(key): str(value or "").strip() for key, value in existing.items()})
            excluded_slots = [
                str(item or "").strip()
                for item in mode.get("excludedSlots") or []
                if str(item or "").strip() and str(item or "").strip() not in CORE_SUPERVISED_AGENT_ROLES
            ]
        except Exception:
            slots = {}
            excluded_slots = None
    for agent in active_agents:
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        role = str(metadata.get("supervisedRole") or agent.get("roleKey") or "").strip()
        agent_id = str(agent.get("agentId") or "").strip()
        if role and agent_id and not slots.get(role):
            slots[role] = agent_id
    if not active_agent_ids:
        return
    try:
        existing_mode: dict[str, Any] = {}
        try:
            existing_payload = agent_mode_binding_service.get_mode_bindings_payload()
            existing_mode = (existing_payload.get("modes") or {}).get("supervised_evolution") or {}
        except Exception:
            existing_mode = {}
        active_agent_id_set = set(active_agent_ids)
        excluded_agent_ids = []
        for raw_agent_id in list(existing_mode.get("excludedAgentIds") or []):
            agent_id = str(raw_agent_id or "").strip()
            if not agent_id or agent_id in active_agent_id_set:
                continue
            if not agent_directory_service.get_agent(agent_id, include_archived=False):
                continue
            excluded_agent_ids.append(agent_id)
        agent_mode_binding_service.update_mode_binding(
            "supervised_evolution",
            default_agent_id=active_agent_ids[0],
            available_agent_ids=active_agent_ids,
            slots=slots,
            excluded_agent_ids=excluded_agent_ids,
            excluded_slots=excluded_slots,
        )
    except Exception as exc:
        _record_supervised_agent_event(
            "supervised.agent_instance.mode_binding_sync_failed",
            role=SupervisedAgentRole("multi", "监督进化成员"),
            level="error",
            outcome="failed",
            fields={"errorType": type(exc).__name__, "message": str(exc)},
        )
        return


def _ensure_supervised_role(role: SupervisedAgentRole) -> tuple[dict[str, Any] | None, bool]:
    existing = _find_agent_by_supervised_role(role.role)
    changed = False
    seed_llm_bindings = _supervised_role_llm_bindings(role.role)
    if role.role not in CORE_SUPERVISED_AGENT_ROLES and _supervised_role_slot_excluded(role.role):
        _record_supervised_agent_event(
            "supervised.agent_instance.sync_skipped_excluded_slot",
            role=role,
            level="info",
            outcome="skipped",
            fields={
                "reason": "mode_binding_slot_excluded",
                "agentId": str((existing or {}).get("agentId") or "").strip(),
            },
        )
        return None, False
    if not existing:
        session_detail = session_service.create_chat_session(
            title=role.label,
            llm_bindings=seed_llm_bindings,
            created_by="supervised_evolution",
        )
        agent_id = str(session_detail.get("agentId") or "").strip()
        existing = agent_directory_service.get_agent(agent_id) if agent_id else None
        if not existing:
            raise RuntimeError(f"Supervised agent was not created for role: {role.role}")
        changed = True
    if str(existing.get("status") or "active").strip() == "archived":
        if role.role in CORE_SUPERVISED_AGENT_ROLES:
            existing = agent_directory_service.reactivate_agent_instance(
                str(existing.get("agentId") or ""),
                reason="core_supervised_role_required",
                metadata={"protected": True},
            )
            changed = True
        else:
            _record_supervised_agent_event(
                "supervised.agent_instance.sync_skipped_archived",
                role=role,
                level="info",
                outcome="skipped",
                fields={
                    "reason": "agent_archived",
                    "agentId": str(existing.get("agentId") or "").strip(),
                },
            )
            return None, False
    if str(existing.get("status") or "active").strip() == "archived":
        _record_supervised_agent_event(
            "supervised.agent_instance.sync_skipped_archived",
            role=role,
            level="info",
            outcome="skipped",
            fields={
                "reason": "agent_archived",
                "agentId": str(existing.get("agentId") or "").strip(),
            },
        )
        return None, False

    metadata = dict(existing.get("metadata") or {})
    existing_llm_bindings = agent_directory_service.normalize_agent_llm_bindings(existing.get("llmBindings"))
    expected_llm_bindings = agent_directory_service.normalize_agent_llm_bindings(seed_llm_bindings)
    existing_dialogue_model_id = agent_directory_service.agent_dialogue_model_id(
        {"llmBindings": existing_llm_bindings}
    )
    expected_metadata = {
        "agentMode": "supervised_evolution",
        "configSurface": "model_config",
        "fixedRole": True,
        "protected": role.role in CORE_SUPERVISED_AGENT_ROLES,
        "supervisedRole": role.role,
        "supervisedRoleLabel": role.label,
        "functionalDisplayName": role.label,
    }
    needs_update = any(metadata.get(key) != value for key, value in expected_metadata.items())
    if needs_update:
        existing = agent_directory_service.update_agent_instance(
            str(existing.get("agentId") or ""),
            primary_mode="supervised_evolution",
            role_key=role.role,
            prompt_template_id=f"prompt-supervised-{role.role}",
            metadata=expected_metadata,
            status="active",
        )
        changed = True
    if expected_llm_bindings and not existing_dialogue_model_id:
        existing = agent_directory_service.update_agent_instance(
            str(existing.get("agentId") or ""),
            llm_bindings=expected_llm_bindings,
        )
        changed = True

    direct_session_id = str(existing.get("directSessionId") or "").strip()
    if direct_session_id:
        try:
            session_service.update_chat_session(
                direct_session_id,
                title=role.label,
            )
        except Exception:
            pass
    return existing, changed


def _supervised_role_slot_excluded(role: str) -> bool:
    normalized = str(role or "").strip()
    if not normalized:
        return False
    try:
        payload = agent_mode_binding_service.get_mode_bindings_payload()
        mode = (payload.get("modes") or {}).get("supervised_evolution") or {}
        excluded_slots = {str(item or "").strip() for item in list(mode.get("excludedSlots") or [])}
        return normalized in excluded_slots
    except Exception:
        return False


def _find_agent_by_supervised_role(role: str) -> dict[str, Any] | None:
    normalized = str(role or "").strip()
    if not normalized:
        return None
    for agent in agent_directory_service.list_agents(include_archived=True):
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        if str(metadata.get("supervisedRole") or "").strip() == normalized:
            return agent
    return None


def _active_session_id(project_root: Path) -> str:
    try:
        return str(load_chat_state(project_root).get("active_conversation_id") or "").strip()
    except Exception:
        return ""


def _restore_active_session(project_root: Path, session_id: str) -> None:
    normalized = str(session_id or "").strip()
    if not normalized:
        return
    try:
        state = load_chat_state(project_root)
        conversations = state.get("conversations") if isinstance(state.get("conversations"), list) else []
        if any(str(item.get("conversation_id") or "").strip() == normalized for item in conversations if isinstance(item, dict)):
            state["active_conversation_id"] = normalized
            save_chat_state(project_root, state)
    except Exception:
        return


def _record_supervised_agent_event(
    event_code: str,
    *,
    role: SupervisedAgentRole,
    level: str,
    outcome: str,
    fields: dict[str, Any] | None = None,
) -> None:
    try:
        record_runtime_scene_event(
            "agent_directory",
            "agent",
            event_code,
            message=event_code,
            level=level,
            outcome=outcome,
            fields={
                "supervisedRole": role.role,
                "supervisedRoleLabel": role.label,
                **dict(fields or {}),
            },
            lifecycle=True,
        )
    except Exception:
        return
