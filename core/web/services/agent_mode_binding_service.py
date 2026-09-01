"""Mode-to-Agent binding store for configurable Agent runtimes."""

from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.infrastructure import developer_sandbox

from .agent_directory_service import (
    SESSION_AGENT_VISIBILITY_ACTIVE,
    SESSION_AGENT_VISIBILITY_PENDING,
    get_agent,
    list_agents,
    session_agent_visibility,
)
from .runtime_scene_service import record_runtime_scene_event


PROJECT_ROOT = Path(__file__).resolve().parents[3]
MODE_BINDING_VERSION = 1
MODE_BINDING_PATH = developer_sandbox.formal_workspace_path(PROJECT_ROOT, "agent_config", "mode_bindings.json")
_DEFAULT_MODE_BINDING_PATH = MODE_BINDING_PATH
MODE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{1,63}$")
MODE_SLOT_KEYS = {
    "supervised_evolution": {"baseline", "candidate", "reviewer", "auditor", "judge"},
    "self_evolution": {"executor", "reviewer", "observer"},
}


class AgentModeBindingError(ValueError):
    """Raised when a mode binding update is invalid."""


DEFAULT_MODE_BINDINGS: tuple[dict[str, Any], ...] = (
    {"mode": "chat", "defaultAgentId": "", "availableAgentIds": [], "pool": [], "flowBindings": {}, "slots": {}, "excludedAgentIds": []},
    {"mode": "research", "defaultAgentId": "", "availableAgentIds": [], "pool": [], "flowBindings": {}, "slots": {}, "excludedAgentIds": []},
    {
        "mode": "supervised_evolution",
        "defaultAgentId": "",
        "availableAgentIds": [],
        "pool": [],
        "flowBindings": {},
        "slots": {"baseline": "", "candidate": "", "reviewer": "", "auditor": "", "judge": ""},
        "excludedAgentIds": [],
        "excludedSlots": [],
    },
    {
        "mode": "self_evolution",
        "defaultAgentId": "",
        "availableAgentIds": [],
        "pool": [],
        "flowBindings": {},
        "slots": {"executor": "", "reviewer": "", "observer": ""},
        "excludedAgentIds": [],
        "excludedSlots": [],
    },
)


def get_mode_bindings_payload(
    *,
    agent_options: list[dict[str, Any]] | None = None,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Return repaired mode bindings plus the active Agent index.

    ``project_root`` 为显式解析根；缺省回落模块级 ``PROJECT_ROOT``，保持既有
    调用方行为不变。并发调用方（如 research agent runner）应始终显式传参，
    禁止再依赖模块级 save-swap-restore。
    """

    agents = agent_options if agent_options is not None else _agent_options(project_root=project_root)
    payload = repair_mode_bindings(agent_options=agents, project_root=project_root)
    modes = {
        str(item.get("mode") or ""): _binding_to_api(item)
        for item in payload.get("bindings") or []
        if isinstance(item, dict)
    }
    return {
        "schemaVersion": MODE_BINDING_VERSION,
        "storagePath": _relative_project_path(mode_binding_path(project_root=project_root), project_root=project_root),
        "bindings": modes,
        "modes": modes,
        "agents": agents,
        "agentRefs": {str(agent.get("agentId") or ""): agent for agent in agents},
        "repairWarnings": list(payload.get("repairWarnings") or []),
    }


def update_mode_binding(
    mode: str,
    *,
    default_agent_id: str | None = None,
    available_agent_ids: list[str] | None = None,
    pool: list[str] | None = None,
    flow_bindings: dict[str, str] | None = None,
    slots: dict[str, str] | None = None,
    excluded_agent_ids: list[str] | None = None,
    excluded_slots: list[str] | None = None,
) -> dict[str, Any]:
    """Update one mode binding record and return the repaired payload."""

    normalized_mode = _normalize_mode(mode)
    payload = repair_mode_bindings()
    bindings = list(payload.get("bindings") or [])
    index = next((idx for idx, item in enumerate(bindings) if item.get("mode") == normalized_mode), -1)
    if index < 0:
        bindings.append(_normalize_binding({"mode": normalized_mode}))
        index = len(bindings) - 1
    record = copy.deepcopy(bindings[index])
    if default_agent_id is not None:
        record["defaultAgentId"] = _validate_agent_reference(default_agent_id, allow_blank=True)
    if available_agent_ids is not None:
        record["availableAgentIds"] = _normalize_agent_list(available_agent_ids)
    if pool is not None:
        record["pool"] = _normalize_agent_list(pool)
    if flow_bindings is not None:
        record["flowBindings"] = _normalize_agent_map(flow_bindings)
    if slots is not None:
        record["slots"] = _filter_slots_for_mode(normalized_mode, _normalize_agent_map(slots))
    if excluded_agent_ids is not None:
        record["excludedAgentIds"] = _normalize_agent_list(excluded_agent_ids)
    if excluded_slots is not None:
        record["excludedSlots"] = _safe_key_list(excluded_slots)
    record["updatedAt"] = _now()
    bindings[index] = _normalize_binding(record)
    payload["bindings"] = bindings
    _save_mode_bindings(payload)
    _record_mode_binding_event(
        "mode_binding.updated",
        normalized_mode,
        outcome="updated",
        fields={
            "defaultAgentId": record.get("defaultAgentId") or "",
            "availableAgentCount": len(record.get("availableAgentIds") or []),
            "poolCount": len(record.get("pool") or []),
            "slotCount": len(record.get("slots") or {}),
            "excludedAgentCount": len(record.get("excludedAgentIds") or []),
            "excludedSlotCount": len(record.get("excludedSlots") or []),
        },
    )
    return get_mode_bindings_payload()


def update_agent_mode_membership(
    agent_id: str,
    *,
    chat_default: bool | None = None,
    chat_available: bool | None = None,
    research_pool: bool | None = None,
    supervised_slot: str | None = None,
    self_evolution_slot: str | None = None,
) -> dict[str, Any]:
    """Update the mode binding references for one Agent from the Agent Center card."""

    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id or not get_agent(normalized_agent_id, include_archived=False):
        raise AgentModeBindingError(f"Agent not found or archived: {normalized_agent_id}")
    changed_modes: list[str] = []
    modes = get_mode_bindings_payload().get("modes") or {}

    if chat_default is not None or chat_available is not None:
        chat = dict(modes.get("chat") or {})
        available = _dedupe(chat.get("availableAgentIds") or [])
        excluded = set(_dedupe(chat.get("excludedAgentIds") or []))
        default_agent_id = str(chat.get("defaultAgentId") or "").strip()
        if chat_default is True:
            excluded.discard(normalized_agent_id)
            available = _dedupe([*available, normalized_agent_id])
            default_agent_id = normalized_agent_id
        elif chat_default is False and default_agent_id == normalized_agent_id:
            default_agent_id = ""
        if chat_available is True:
            excluded.discard(normalized_agent_id)
            available = _dedupe([*available, normalized_agent_id])
        elif chat_available is False and chat_default is not True:
            available = [item for item in available if item != normalized_agent_id]
            excluded.add(normalized_agent_id)
            if default_agent_id == normalized_agent_id:
                default_agent_id = ""
        update_mode_binding(
            "chat",
            default_agent_id=default_agent_id,
            available_agent_ids=available,
            excluded_agent_ids=sorted(excluded),
        )
        changed_modes.append("chat")

    if research_pool is not None:
        research = dict(modes.get("research") or {})
        pool = _dedupe(research.get("pool") or [])
        flow_bindings = dict(research.get("flowBindings") or {})
        excluded = set(_dedupe(research.get("excludedAgentIds") or []))
        if research_pool:
            excluded.discard(normalized_agent_id)
            pool = _dedupe([*pool, normalized_agent_id])
        else:
            pool = [item for item in pool if item != normalized_agent_id]
            flow_bindings = {key: value for key, value in flow_bindings.items() if value != normalized_agent_id}
            excluded.add(normalized_agent_id)
        update_mode_binding(
            "research",
            pool=pool,
            flow_bindings=flow_bindings,
            excluded_agent_ids=sorted(excluded),
        )
        changed_modes.append("research")

    if supervised_slot is not None:
        supervised = dict(modes.get("supervised_evolution") or {})
        current_slots = dict(supervised.get("slots") or {})
        previous_slot = _slot_for_agent(current_slots, normalized_agent_id)
        slots = _assign_agent_slot(current_slots, normalized_agent_id, supervised_slot)
        excluded = _slot_exclusions(supervised.get("excludedAgentIds") or [], normalized_agent_id, supervised_slot)
        excluded_slots = _excluded_slots(supervised.get("excludedSlots") or [], supervised_slot, previous_slot=previous_slot)
        update_mode_binding("supervised_evolution", slots=slots, excluded_agent_ids=excluded, excluded_slots=excluded_slots)
        changed_modes.append("supervised_evolution")

    if self_evolution_slot is not None:
        self_evolution = dict(modes.get("self_evolution") or {})
        current_slots = dict(self_evolution.get("slots") or {})
        previous_slot = _slot_for_agent(current_slots, normalized_agent_id)
        slots = _assign_agent_slot(current_slots, normalized_agent_id, self_evolution_slot)
        excluded = _slot_exclusions(self_evolution.get("excludedAgentIds") or [], normalized_agent_id, self_evolution_slot)
        excluded_slots = _excluded_slots(self_evolution.get("excludedSlots") or [], self_evolution_slot, previous_slot=previous_slot)
        update_mode_binding("self_evolution", slots=slots, excluded_agent_ids=excluded, excluded_slots=excluded_slots)
        changed_modes.append("self_evolution")

    if changed_modes:
        _record_mode_binding_event(
            "mode_binding.agent_membership.updated",
            "multi",
            outcome="updated",
            fields={"agentId": normalized_agent_id, "changedModes": changed_modes},
        )
    return get_mode_bindings_payload()


def remove_agent_from_mode_bindings(
    agent_id: str,
    *,
    agent_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Remove one Agent from all mode binding references before safe archival."""

    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        raise AgentModeBindingError("Agent id is required.")
    return remove_agents_from_mode_bindings(
        [normalized_agent_id],
        agent_snapshots_by_agent_id={normalized_agent_id: agent_snapshot} if isinstance(agent_snapshot, dict) else None,
    )


def remove_agents_from_mode_bindings(
    agent_ids: list[str] | None,
    *,
    agent_snapshots_by_agent_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Remove multiple Agents from all mode binding references in one binding update."""

    requested = [str(item or "").strip() for item in list(agent_ids or []) if str(item or "").strip()]
    normalized_agent_ids: list[str] = []
    seen_agent_ids: set[str] = set()
    for agent_id in requested:
        if agent_id in seen_agent_ids:
            continue
        seen_agent_ids.add(agent_id)
        normalized_agent_ids.append(agent_id)
    if not normalized_agent_ids:
        payload = get_mode_bindings_payload()
        payload["removedAgentIds"] = []
        return payload

    snapshots = {
        str(agent_id or "").strip(): dict(snapshot)
        for agent_id, snapshot in dict(agent_snapshots_by_agent_id or {}).items()
        if str(agent_id or "").strip() and isinstance(snapshot, dict)
    }
    for agent_id in normalized_agent_ids:
        if agent_id not in snapshots:
            agent = get_agent(agent_id, include_archived=True)
            if isinstance(agent, dict):
                snapshots[agent_id] = agent
    tombstone_slot_by_agent_and_mode = {
        agent_id: _fixed_role_tombstone_slots(snapshots.get(agent_id))
        for agent_id in normalized_agent_ids
    }
    payload = repair_mode_bindings()
    bindings = list(payload.get("bindings") or [])
    changed_modes: list[str] = []
    removal_warnings: list[dict[str, str]] = []
    next_bindings: list[dict[str, Any]] = []
    agent_id_set = set(normalized_agent_ids)
    for binding in bindings:
        if not isinstance(binding, dict):
            continue
        record = _normalize_binding(binding)
        mode = str(record.get("mode") or "").strip()
        changed = False
        exclude_agent_ids_from_reseed: set[str] = set()
        default_agent_id = str(record.get("defaultAgentId") or "").strip()
        if default_agent_id in agent_id_set:
            record["defaultAgentId"] = ""
            changed = True
            exclude_agent_ids_from_reseed.add(default_agent_id)
            removal_warnings.append({"mode": mode, "field": "defaultAgentId", "agentId": default_agent_id})
        for field in ("availableAgentIds", "pool", "excludedAgentIds"):
            if field == "excludedAgentIds":
                values = [item for item in list(record.get(field) or []) if str(item or "").strip() not in agent_id_set]
            else:
                removed = [str(item or "").strip() for item in list(record.get(field) or []) if str(item or "").strip() in agent_id_set]
                for removed_agent_id in removed:
                    removal_warnings.append({"mode": mode, "field": field, "agentId": removed_agent_id})
                    exclude_agent_ids_from_reseed.add(removed_agent_id)
                values = [item for item in list(record.get(field) or []) if str(item or "").strip() not in agent_id_set]
            if values != list(record.get(field) or []):
                record[field] = values
                changed = True
        flow_bindings = {
            key: value
            for key, value in dict(record.get("flowBindings") or {}).items()
            if str(value or "").strip() not in agent_id_set
        }
        if flow_bindings != dict(record.get("flowBindings") or {}):
            for key, value in dict(record.get("flowBindings") or {}).items():
                removed_agent_id = str(value or "").strip()
                if removed_agent_id in agent_id_set:
                    removal_warnings.append({"mode": mode, "field": f"flowBindings.{key}", "agentId": removed_agent_id})
                    exclude_agent_ids_from_reseed.add(removed_agent_id)
            record["flowBindings"] = flow_bindings
            changed = True
        excluded_slots = set(_safe_key_list(record.get("excludedSlots") or []))
        slots = {}
        for key, value in dict(record.get("slots") or {}).items():
            normalized_key = _safe_key(key)
            removed_agent_id = str(value or "").strip()
            if removed_agent_id in agent_id_set:
                slots[key] = ""
                exclude_agent_ids_from_reseed.add(removed_agent_id)
                removal_warnings.append({"mode": mode, "field": f"slots.{key}", "agentId": removed_agent_id})
                if normalized_key:
                    excluded_slots.add(normalized_key)
            else:
                slots[key] = value
        if slots != dict(record.get("slots") or {}):
            record["slots"] = slots
            record["excludedSlots"] = sorted(excluded_slots)
            changed = True
        for removed_agent_id, tombstone_slot_by_mode in tombstone_slot_by_agent_and_mode.items():
            tombstone_slot = tombstone_slot_by_mode.get(str(record.get("mode") or "").strip())
            if not tombstone_slot:
                continue
            before = set(_safe_key_list(record.get("excludedSlots") or []))
            before.add(tombstone_slot)
            next_excluded_slots = sorted(before)
            if next_excluded_slots != list(record.get("excludedSlots") or []):
                record["excludedSlots"] = next_excluded_slots
                changed = True
            if str(record.get("slots", {}).get(tombstone_slot) or "").strip() == removed_agent_id:
                record["slots"][tombstone_slot] = ""
                changed = True
            exclude_agent_ids_from_reseed.add(removed_agent_id)
        if exclude_agent_ids_from_reseed:
            record["excludedAgentIds"] = _dedupe([*list(record.get("excludedAgentIds") or []), *sorted(exclude_agent_ids_from_reseed)])
        if not record["defaultAgentId"] and record["availableAgentIds"]:
            record["defaultAgentId"] = record["availableAgentIds"][0]
        if changed:
            record["updatedAt"] = _now()
            changed_modes.append(str(record.get("mode") or ""))
        next_bindings.append(_normalize_binding(record))
    if changed_modes:
        payload["bindings"] = next_bindings
        payload["repairWarnings"] = [
            *list(payload.get("repairWarnings") or []),
            *removal_warnings,
        ][-50:]
        _save_mode_bindings(payload)
        _record_mode_binding_event(
            "mode_binding.agent_removed",
            "multi",
            outcome="updated",
            fields={"agentIds": normalized_agent_ids, "agentCount": len(normalized_agent_ids), "changedModes": changed_modes},
        )
    result = get_mode_bindings_payload()
    result["removedAgentIds"] = normalized_agent_ids
    return result


def restore_removed_agents_to_mode_bindings(restore_token: dict[str, Any] | None) -> dict[str, Any]:
    """Restore the exact mode-binding snapshot after a failed archive."""

    token = copy.deepcopy(restore_token) if isinstance(restore_token, dict) else None
    if not token:
        return {"restored": False}
    restored_modes: list[str] = []
    for binding in list(token.get("bindings") or []):
        if not isinstance(binding, dict):
            continue
        mode = str(binding.get("mode") or "").strip()
        if not mode:
            continue
        update_mode_binding(
            mode,
            default_agent_id=str(binding.get("defaultAgentId") or "").strip(),
            available_agent_ids=list(binding.get("availableAgentIds") or []),
            pool=list(binding.get("pool") or []),
            flow_bindings=dict(binding.get("flowBindings") or {}),
            slots=dict(binding.get("slots") or {}),
            excluded_agent_ids=list(binding.get("excludedAgentIds") or []),
            excluded_slots=list(binding.get("excludedSlots") or []),
        )
        restored_modes.append(mode)
    return {"restored": bool(restored_modes), "restoredModes": restored_modes}


def _fixed_role_tombstone_slots(agent: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(agent, dict):
        return {}
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    mode = str(agent.get("primaryMode") or "").strip()
    role = ""
    if mode == "supervised_evolution":
        role = str(metadata.get("supervisedRole") or agent.get("roleKey") or "").strip()
    elif mode == "self_evolution":
        role = str(metadata.get("selfEvolutionRole") or agent.get("roleKey") or "").strip()
    safe_role = _safe_key(role)
    return {mode: safe_role} if mode in {"supervised_evolution", "self_evolution"} and safe_role else {}


def repair_mode_bindings(
    *,
    agent_options: list[dict[str, Any]] | None = None,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Load bindings, seed known modes, and remove stale Agent references."""

    agents = agent_options if agent_options is not None else _agent_options(project_root=project_root)
    active_agent_ids = {
        str(agent.get("agentId") or "").strip()
        for agent in agents
        if str(agent.get("agentId") or "").strip()
    }
    payload = _load_mode_bindings(project_root=project_root)
    bindings_by_mode = _default_binding_map()
    changed = False
    for raw in payload.get("bindings") or []:
        if not isinstance(raw, dict):
            changed = True
            continue
        try:
            record = _normalize_binding(raw)
        except AgentModeBindingError:
            changed = True
            continue
        existing = bindings_by_mode.get(record["mode"], {})
        merged = copy.deepcopy(existing)
        merged.update(record)
        merged["slots"] = _filter_slots_for_mode(
            record["mode"],
            {**dict(existing.get("slots") or {}), **dict(record.get("slots") or {})},
        )
        merged["flowBindings"] = {
            **dict(existing.get("flowBindings") or {}),
            **dict(record.get("flowBindings") or {}),
        }
        merged["excludedAgentIds"] = _dedupe([*list(existing.get("excludedAgentIds") or []), *list(record.get("excludedAgentIds") or [])])
        merged["excludedSlots"] = _safe_key_list([*list(existing.get("excludedSlots") or []), *list(record.get("excludedSlots") or [])])
        bindings_by_mode[record["mode"]] = _normalize_binding(merged)

    existing_warnings = [
        item
        for item in list(payload.get("repairWarnings") or [])
        if isinstance(item, dict) and str(item.get("agentId") or "").strip()
    ]
    seeded = _seed_bindings_from_agents(bindings_by_mode, agents=agents)
    repaired: list[dict[str, Any]] = []
    repair_warnings: list[dict[str, str]] = []
    agents_by_id = {
        str(agent.get("agentId") or "").strip(): agent
        for agent in agents
        if str(agent.get("agentId") or "").strip()
    }
    for binding in seeded.values():
        next_binding, warnings = _repair_agent_references(
            binding,
            active_agent_ids=active_agent_ids,
            agents_by_id=agents_by_id,
        )
        repaired.append(next_binding)
        repair_warnings.extend(warnings)
    current_warnings = repair_warnings[-50:]
    next_payload = {
        "schemaVersion": MODE_BINDING_VERSION,
        "updatedAt": str(payload.get("updatedAt") or _now()),
        "bindings": sorted(repaired, key=lambda item: str(item.get("mode") or "")),
        "repairWarnings": current_warnings,
    }
    if payload.get("schemaVersion") != MODE_BINDING_VERSION:
        changed = True
    if _binding_signature(payload.get("bindings") or []) != _binding_signature(next_payload["bindings"]):
        changed = True
    if existing_warnings[-50:] != current_warnings:
        changed = True
    if repair_warnings:
        changed = True
    if changed or not mode_binding_path(project_root=project_root).exists():
        next_payload["updatedAt"] = _now()
        _save_mode_bindings(next_payload, project_root=project_root)
        _record_mode_binding_event(
            "mode_binding.repaired",
            "",
            outcome="repaired",
            fields={"bindingCount": len(next_payload["bindings"]), "warningCount": len(repair_warnings)},
        )
    return next_payload


def default_mode_binding_state() -> dict[str, Any]:
    """Return the legacy dict-shaped state used by early route/tests."""

    modes = {
        str(item.get("mode") or ""): _binding_to_api(_normalize_binding(copy.deepcopy(item)))
        for item in DEFAULT_MODE_BINDINGS
    }
    return {
        "schemaVersion": MODE_BINDING_VERSION,
        "updatedAt": _now(),
        "modes": modes,
        "repairWarnings": [],
    }


def save_mode_binding_state(state: dict[str, Any]) -> dict[str, Any]:
    """Persist a legacy dict-shaped mode binding state."""

    modes = state.get("modes") if isinstance(state, dict) else {}
    bindings = []
    if isinstance(modes, dict):
        for mode, binding in modes.items():
            raw = dict(binding or {}) if isinstance(binding, dict) else {}
            raw["mode"] = mode
            bindings.append(_normalize_binding(raw))
    else:
        bindings = [_normalize_binding(item) for item in state.get("bindings") or [] if isinstance(item, dict)]
    payload = {
        "schemaVersion": MODE_BINDING_VERSION,
        "updatedAt": _now(),
        "bindings": bindings,
        "repairWarnings": list((state or {}).get("repairWarnings") or [])[-50:] if isinstance(state, dict) else [],
    }
    _save_mode_bindings(payload)
    return payload


def mode_binding_path(*, project_root: Path | None = None) -> Path:
    root = Path(project_root) if project_root is not None else PROJECT_ROOT
    configured_path = Path(MODE_BINDING_PATH)
    current_formal_path = developer_sandbox.formal_workspace_path(root, "agent_config", "mode_bindings.json")
    if configured_path.resolve() not in {
        _DEFAULT_MODE_BINDING_PATH.resolve(),
        current_formal_path.resolve(),
    }:
        return configured_path
    return developer_sandbox.route_workspace_path(
        root,
        "agent_configuration",
        "agent_config",
        "mode_bindings.json",
        intent="state",
        seed=True,
    )


def _seed_bindings_from_agents(
    bindings_by_mode: dict[str, dict[str, Any]],
    *,
    agents: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    by_mode: dict[str, list[str]] = {}
    supervised_slots: dict[str, str] = {}
    self_slots: dict[str, str] = {}
    for agent in agents:
        agent_id = str(agent.get("agentId") or "").strip()
        mode = str(agent.get("primaryMode") or "general").strip() or "general"
        by_mode.setdefault(mode, []).append(agent_id)
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        supervised_role = str(metadata.get("supervisedRole") or agent.get("roleKey") or "").strip()
        if mode == "supervised_evolution" and supervised_role:
            supervised_slots[supervised_role] = agent_id
        if mode == "self_evolution":
            role_key = str(agent.get("roleKey") or "").strip()
            if role_key:
                self_slots[role_key] = agent_id

    _seed_binding(bindings_by_mode, "chat", _chat_seed_agent_ids(agents))
    _seed_binding(bindings_by_mode, "research", by_mode.get("research", []))
    _seed_binding(bindings_by_mode, "supervised_evolution", by_mode.get("supervised_evolution", []), slots=supervised_slots)
    _seed_binding(bindings_by_mode, "self_evolution", by_mode.get("self_evolution", []), slots=self_slots)
    return bindings_by_mode


def _chat_seed_agent_ids(agents: list[dict[str, Any]]) -> list[str]:
    """Seed only enterable chat Agents, not every primary_mode=chat record."""

    seed_ids: list[str] = []
    for agent in agents:
        agent_id = str(agent.get("agentId") or "").strip()
        if not agent_id or not _agent_allowed_in_mode("chat", agent):
            continue
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        creation_spec = metadata.get("creationSpec") if isinstance(metadata.get("creationSpec"), dict) else {}
        created_by = str(agent.get("createdBy") or creation_spec.get("source") or "").strip()
        direct_session_id = str(agent.get("directSessionId") or "").strip()
        if not direct_session_id:
            continue
        if created_by == "api_agents":
            seed_ids.append(agent_id)
            continue
        if bool(metadata.get("showInSessionIndex")):
            seed_ids.append(agent_id)
            continue
        if session_agent_visibility(agent) == SESSION_AGENT_VISIBILITY_ACTIVE:
            seed_ids.append(agent_id)
    return _dedupe(seed_ids)


def _eligible_seed_ids(binding: dict[str, Any], agent_ids: list[str]) -> list[str]:
    excluded = set(_dedupe(binding.get("excludedAgentIds") or []))
    return [agent_id for agent_id in _dedupe(agent_ids) if agent_id not in excluded]


def _seed_binding(
    bindings_by_mode: dict[str, dict[str, Any]],
    mode: str,
    agent_ids: list[str],
    *,
    slots: dict[str, str] | None = None,
) -> None:
    binding = bindings_by_mode.setdefault(mode, _normalize_binding({"mode": mode}))
    seed_ids = _eligible_seed_ids(binding, agent_ids)
    merged_ids = _dedupe([*list(binding.get("availableAgentIds") or []), *seed_ids])
    binding["availableAgentIds"] = merged_ids
    if not binding.get("pool"):
        binding["pool"] = list(seed_ids)
    if not str(binding.get("defaultAgentId") or "").strip() and merged_ids:
        binding["defaultAgentId"] = merged_ids[0]
    if slots:
        excluded = set(_dedupe(binding.get("excludedAgentIds") or []))
        excluded_slots = set(_safe_key_list(binding.get("excludedSlots") or []))
        existing_slots = dict(binding.get("slots") or {})
        for key, value in slots.items():
            safe_key = _safe_key(key)
            if safe_key not in _allowed_slot_keys(mode):
                continue
            if safe_key in excluded_slots:
                continue
            if value in excluded:
                continue
            if not str(existing_slots.get(key) or "").strip():
                existing_slots[safe_key] = value
        binding["slots"] = _filter_slots_for_mode(mode, existing_slots)


def _repair_agent_references(
    binding: dict[str, Any],
    *,
    active_agent_ids: set[str],
    agents_by_id: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    mode = str(binding.get("mode") or "").strip()
    warnings: list[dict[str, str]] = []

    def keep(agent_id: str, field: str) -> str:
        normalized = str(agent_id or "").strip()
        if not normalized:
            return ""
        if normalized in active_agent_ids and _agent_allowed_in_mode(mode, (agents_by_id or {}).get(normalized)):
            return normalized
        warnings.append({"mode": mode, "field": field, "agentId": normalized})
        return ""

    next_binding = _normalize_binding(binding)
    next_binding["defaultAgentId"] = keep(next_binding.get("defaultAgentId") or "", "defaultAgentId")
    next_binding["availableAgentIds"] = [
        agent_id for agent_id in (keep(item, "availableAgentIds") for item in next_binding.get("availableAgentIds") or [])
        if agent_id
    ]
    next_binding["pool"] = [
        agent_id for agent_id in (keep(item, "pool") for item in next_binding.get("pool") or [])
        if agent_id
    ]
    next_binding["flowBindings"] = {
        key: kept
        for key, kept in (
            (key, keep(value, f"flowBindings.{key}"))
            for key, value in dict(next_binding.get("flowBindings") or {}).items()
        )
        if kept
    }
    next_binding["slots"] = _filter_slots_for_mode(
        str(next_binding.get("mode") or ""),
        {
            key: keep(value, f"slots.{key}")
            for key, value in dict(next_binding.get("slots") or {}).items()
        },
    )
    next_binding["excludedAgentIds"] = _dedupe(next_binding.get("excludedAgentIds") or [])
    next_binding["excludedSlots"] = _safe_key_list(next_binding.get("excludedSlots") or [])
    if warnings:
        next_binding["excludedAgentIds"] = _dedupe(
            [*list(next_binding.get("excludedAgentIds") or []), *(item["agentId"] for item in warnings)]
        )
    if not next_binding["defaultAgentId"] and next_binding["availableAgentIds"]:
        next_binding["defaultAgentId"] = next_binding["availableAgentIds"][0]
    if warnings:
        field_counts: dict[str, int] = {}
        unique_agent_ids = _dedupe(item["agentId"] for item in warnings)
        for item in warnings:
            field = str(item.get("field") or "").strip()
            field_counts[field] = field_counts.get(field, 0) + 1
        _record_mode_binding_event(
            "mode_binding.missing_agent",
            mode,
            level="warning",
            outcome="repaired",
            fields={
                "warningCount": len(warnings),
                "uniqueAgentCount": len(unique_agent_ids),
                "agentIds": unique_agent_ids[:12],
                "fieldCounts": field_counts,
                "activeAgentCount": len(active_agent_ids),
                "storagePath": _relative_project_path(mode_binding_path()),
            },
        )
    return next_binding, warnings


def _agent_allowed_in_mode(mode: str, agent: dict[str, Any] | None) -> bool:
    if not isinstance(agent, dict):
        return False
    normalized_mode = _normalize_mode(mode)
    primary_mode = str(agent.get("primaryMode") or "general").strip() or "general"
    role_key = str(agent.get("roleKey") or "").strip()
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    creation_spec = metadata.get("creationSpec") if isinstance(metadata.get("creationSpec"), dict) else {}
    created_by = str(agent.get("createdBy") or creation_spec.get("source") or "").strip()
    if normalized_mode == "chat":
        return (
            primary_mode == "chat"
            and not role_key.startswith("research_")
            and (
                created_by == "api_agents"
                or session_agent_visibility(agent) != SESSION_AGENT_VISIBILITY_PENDING
            )
        )
    if normalized_mode == "research":
        return primary_mode == "research" or role_key.startswith("research_")
    if normalized_mode == "supervised_evolution":
        return primary_mode == "supervised_evolution"
    if normalized_mode == "self_evolution":
        return primary_mode == "self_evolution"
    return primary_mode == normalized_mode


def _binding_to_api(binding: dict[str, Any]) -> dict[str, Any]:
    return {
        "mode": str(binding.get("mode") or "").strip(),
        "defaultAgentId": str(binding.get("defaultAgentId") or "").strip(),
        "availableAgentIds": list(binding.get("availableAgentIds") or []),
        "pool": list(binding.get("pool") or []),
        "flowBindings": dict(binding.get("flowBindings") or {}),
        "slots": dict(binding.get("slots") or {}),
        "excludedAgentIds": list(binding.get("excludedAgentIds") or []),
        "excludedSlots": list(binding.get("excludedSlots") or []),
        "createdAt": str(binding.get("createdAt") or "").strip(),
        "updatedAt": str(binding.get("updatedAt") or "").strip(),
    }


def _agent_options(*, project_root: Path | None = None) -> list[dict[str, Any]]:
    kwargs: dict[str, Any] = {"include_archived": False, "detail": "summary"}
    if project_root is not None:
        # 仅在显式根存在时转发，保持既有 list_agents 桩/子类的签名兼容。
        kwargs["project_root"] = project_root
    return [
        {
            "agentId": str(agent.get("agentId") or "").strip(),
            "agentCode": str(agent.get("agentCode") or "").strip(),
            "displayName": str(agent.get("displayName") or "").strip(),
            "primaryMode": str(agent.get("primaryMode") or "general").strip() or "general",
            "roleKey": str(agent.get("roleKey") or "").strip(),
            "llmBindings": dict(agent.get("llmBindings") or {}) if isinstance(agent.get("llmBindings"), dict) else {},
            "promptTemplateId": str(agent.get("promptTemplateId") or "").strip(),
            "directSessionId": str(agent.get("directSessionId") or "").strip(),
            "metadata": dict(agent.get("metadata") or {}) if isinstance(agent.get("metadata"), dict) else {},
        }
        for agent in list_agents(**kwargs)
    ]


def _load_mode_bindings(*, project_root: Path | None = None) -> dict[str, Any]:
    path = mode_binding_path(project_root=project_root)
    if not path.exists():
        return {"schemaVersion": MODE_BINDING_VERSION, "bindings": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schemaVersion": MODE_BINDING_VERSION, "bindings": []}
    return payload if isinstance(payload, dict) else {"schemaVersion": MODE_BINDING_VERSION, "bindings": []}


def _save_mode_bindings(payload: dict[str, Any], *, project_root: Path | None = None) -> None:
    data = {
        "schemaVersion": MODE_BINDING_VERSION,
        "updatedAt": _now(),
        "bindings": [_normalize_binding(item) for item in payload.get("bindings") or [] if isinstance(item, dict)],
        "repairWarnings": list(payload.get("repairWarnings") or [])[-50:],
    }
    _atomic_write_json(mode_binding_path(project_root=project_root), data)


def _normalize_binding(raw: dict[str, Any]) -> dict[str, Any]:
    mode = _normalize_mode(raw.get("mode"))
    now = _now()
    return {
        "mode": mode,
        "defaultAgentId": str(raw.get("defaultAgentId") or "").strip(),
        "availableAgentIds": _dedupe(raw.get("availableAgentIds") or []),
        "pool": _dedupe(raw.get("pool") or []),
        "flowBindings": _safe_agent_map(raw.get("flowBindings") or {}),
        "slots": _filter_slots_for_mode(mode, _safe_agent_map(raw.get("slots") or {})),
        "excludedAgentIds": _dedupe(raw.get("excludedAgentIds") or []),
        "excludedSlots": _safe_key_list(raw.get("excludedSlots") or []),
        "createdAt": str(raw.get("createdAt") or now).strip(),
        "updatedAt": str(raw.get("updatedAt") or now).strip(),
    }


def _normalize_mode(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if not normalized or not MODE_ID_PATTERN.fullmatch(normalized):
        raise AgentModeBindingError("Invalid mode binding id.")
    return normalized


def _normalize_agent_list(values: list[str]) -> list[str]:
    if not isinstance(values, list):
        raise AgentModeBindingError("Agent id list is required.")
    return _dedupe(_validate_agent_reference(item, allow_blank=False) for item in values)


def _normalize_agent_map(values: dict[str, str]) -> dict[str, str]:
    if not isinstance(values, dict):
        raise AgentModeBindingError("Agent binding map is required.")
    return {
        _safe_key(key): _validate_agent_reference(value, allow_blank=True)
        for key, value in values.items()
        if _safe_key(key)
    }


def _allowed_slot_keys(mode: str) -> set[str]:
    return set(MODE_SLOT_KEYS.get(str(mode or "").strip(), set()))


def _filter_slots_for_mode(mode: str, slots: dict[str, Any]) -> dict[str, str]:
    safe_slots = _safe_agent_map(slots)
    allowed = _allowed_slot_keys(mode)
    if not allowed:
        return safe_slots
    return {key: value for key, value in safe_slots.items() if key in allowed}


def _assign_agent_slot(slots: dict[str, Any], agent_id: str, slot: str) -> dict[str, str]:
    normalized_slot = _safe_key(slot)
    current = _safe_agent_map(slots)
    for key, value in list(current.items()):
        if value == agent_id:
            current[key] = ""
    if normalized_slot:
        current[normalized_slot] = _validate_agent_reference(agent_id, allow_blank=False)
    return current


def _slot_for_agent(slots: dict[str, Any], agent_id: str) -> str:
    for key, value in _safe_agent_map(slots).items():
        if value == agent_id:
            return key
    return ""


def _slot_exclusions(values: Any, agent_id: str, slot: str) -> list[str]:
    excluded = set(_dedupe(values or []))
    if _safe_key(slot):
        excluded.discard(agent_id)
    else:
        excluded.add(agent_id)
    return sorted(excluded)


def _excluded_slots(values: Any, slot: str, *, previous_slot: str = "") -> list[str]:
    excluded = set(_safe_key_list(values or []))
    normalized_slot = _safe_key(slot)
    if normalized_slot:
        excluded.discard(normalized_slot)
    elif previous_slot:
        excluded.add(previous_slot)
    return sorted(excluded)


def _validate_agent_reference(value: Any, *, allow_blank: bool) -> str:
    agent_id = str(value or "").strip()
    if not agent_id:
        if allow_blank:
            return ""
        raise AgentModeBindingError("Agent id is required.")
    if not get_agent(agent_id, include_archived=False):
        raise AgentModeBindingError(f"Agent not found or archived: {agent_id}")
    return agent_id


def _safe_agent_map(values: dict[str, Any]) -> dict[str, str]:
    if not isinstance(values, dict):
        return {}
    return {_safe_key(key): str(value or "").strip() for key, value in values.items() if _safe_key(key)}


def _safe_key(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip().lower()).strip("._-")


def _safe_key_list(values: Any) -> list[str]:
    return _dedupe(_safe_key(item) for item in list(values or []) if _safe_key(item))


def _dedupe(values: Any) -> list[str]:
    if values is None or isinstance(values, (str, bytes)):
        return []
    try:
        iterator = iter(values)
    except TypeError:
        return []
    seen: set[str] = set()
    result: list[str] = []
    for value in iterator:
        item = str(value or "").strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _default_binding_map() -> dict[str, dict[str, Any]]:
    return {
        str(item["mode"]): _normalize_binding(copy.deepcopy(item))
        for item in DEFAULT_MODE_BINDINGS
    }


def _binding_signature(
    bindings: list[Any],
) -> list[tuple[str, str, tuple[str, ...], tuple[str, ...], tuple[tuple[str, str], ...], tuple[tuple[str, str], ...], tuple[str, ...], tuple[str, ...]]]:
    signature = []
    for item in bindings:
        if not isinstance(item, dict):
            continue
        signature.append(
            (
                str(item.get("mode") or ""),
                str(item.get("defaultAgentId") or ""),
                tuple(str(value or "") for value in item.get("availableAgentIds") or []),
                tuple(str(value or "") for value in item.get("pool") or []),
                tuple(sorted((str(key), str(value or "")) for key, value in dict(item.get("flowBindings") or {}).items())),
                tuple(sorted((str(key), str(value or "")) for key, value in dict(item.get("slots") or {}).items())),
                tuple(str(value or "") for value in item.get("excludedAgentIds") or []),
                tuple(str(value or "") for value in item.get("excludedSlots") or []),
            )
        )
    return sorted(signature)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _relative_project_path(path: Path, *, project_root: Path | None = None) -> str:
    root = Path(project_root) if project_root is not None else PROJECT_ROOT
    resolved = path.resolve()
    workspace_root = developer_sandbox.formal_workspace_path(root).resolve()
    try:
        return f"workspace/{resolved.relative_to(workspace_root).as_posix()}"
    except ValueError:
        pass
    sandbox_root = developer_sandbox.sandbox_workspace_path(root)
    if sandbox_root is not None:
        try:
            return f"workspace/{resolved.relative_to(sandbox_root.resolve()).as_posix()}"
        except ValueError:
            pass
    try:
        return resolved.relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return str(path)


def _record_mode_binding_event(
    event_code: str,
    mode: str,
    *,
    level: str = "info",
    outcome: str = "observed",
    fields: dict[str, Any] | None = None,
) -> None:
    try:
        record_runtime_scene_event(
            "agent_configuration",
            "mode_binding",
            event_code,
            message=event_code,
            level=level,
            outcome=outcome,
            fields={"mode": str(mode or "").strip(), **dict(fields or {})},
            lifecycle=True,
        )
    except Exception:
        return


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
