"""Materialize portable public presets through the native Agent/Session owners.

The bundle contains configuration, never operator identities or conversations.
Only assets created here and still carrying an unfinished seed marker may be
repaired. Existing identities (including archived ones) remain operator-owned.
"""
from __future__ import annotations

import base64
import json
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any

from config.settings import get_config

PRESET_ROOT = Path(__file__).with_name("presets")
PUBLIC_PRESET_VERSION = 1
_SEED_LOCK = threading.RLock()


def load_public_agent_presets() -> list[dict[str, Any]]:
    payload = json.loads((PRESET_ROOT / "catalog.json").read_text(encoding="utf-8"))
    if payload.get("schemaVersion") != PUBLIC_PRESET_VERSION:
        raise ValueError("Unsupported public Agent preset schema")
    presets = payload.get("presets")
    if not isinstance(presets, list):
        raise ValueError("Public Agent presets must be an array")
    keys: set[str] = set()
    for preset in presets:
        if not isinstance(preset, dict):
            raise ValueError("Invalid public Agent preset")
        key = str(preset.get("key") or "").strip()
        if not key or key in keys or not str(preset.get("displayName") or "").strip():
            raise ValueError("Public Agent presets require unique keys and display names")
        keys.add(key)
    return presets


def _model_bindings(preset: dict[str, Any]) -> dict[str, Any]:
    from core.web.services import session_service

    bindings = deepcopy(session_service.default_session_llm_bindings())
    preferred = preset.get("preferredLlmBindings") or {}
    config = get_config()
    for slot, binding in preferred.items():
        if not isinstance(binding, dict):
            continue
        reference = str(binding.get("modelId") or "").strip()
        if not reference:
            continue
        try:
            canonical = config.llm.resolve_model_ref(reference)
        except (KeyError, ValueError):
            continue
        if canonical and canonical in config.llm.model_library:
            bindings[slot] = {"modelId": canonical}
    return bindings


def _find_existing(agents: list[dict[str, Any]], preset: dict[str, Any]) -> dict[str, Any] | None:
    marked = [agent for agent in agents
              if (agent.get("metadata") or {}).get("publicPresetKey") == preset["key"]
              and (agent.get("metadata") or {}).get("publicPresetVersion") == PUBLIC_PRESET_VERSION]
    matches = marked or [agent for agent in agents
                         if agent.get("displayName") == preset["displayName"]
                         and str(agent.get("roleKey") or "") == str(preset.get("roleKey") or "")
                         and (not preset.get("matchCreatedBy")
                              or agent.get("createdBy") == preset["matchCreatedBy"])]
    return next((agent for agent in matches if agent.get("status") != "archived"),
                matches[0] if matches else None)


def _install_avatar(agent_id: str, asset: str) -> None:
    from core.web.services import agent_directory_service as directory

    root = PRESET_ROOT.resolve()
    path = (root / asset).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Public Agent avatar must be inside its preset bundle")
    content_type = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                    ".webp": "image/webp"}.get(path.suffix.lower())
    if not content_type:
        raise ValueError("Unsupported public Agent avatar format")
    directory.store_agent_avatar_image(
        agent_id, filename=path.name, content_type=content_type,
        data_base64=base64.b64encode(path.read_bytes()).decode("ascii"),
    )


def _prompt_template_id(preset: dict[str, Any]) -> str:
    if not str(preset.get("promptContent") or "").strip():
        return preset.get("promptTemplateId") or "prompt-chat-default"
    from core.web.services import prompt_template_service

    template_id = f"prompt-public-{preset['key']}"
    if prompt_template_service.get_prompt_template(template_id) is None:
        prompt_template_service.update_prompt_template(
            template_id, name=preset["displayName"],
            category=preset.get("primaryMode") or "general", source_path="",
            content=preset["promptContent"],
        )
    return template_id


def _finish_seed(agent: dict[str, Any], preset: dict[str, Any]) -> None:
    from core.web.services import agent_directory_service as directory, session_service

    metadata: dict[str, Any] = {
        "publicPresetPreferredLlmBindings": deepcopy(preset.get("preferredLlmBindings") or {}),
        "llmModelParameters": deepcopy(preset.get("llmModelParameters") or {}),
    }
    bundles = (preset.get("metadata") or {}).get("creationToolBundleIds")
    if isinstance(bundles, list):
        metadata["creationToolBundleIds"] = deepcopy(bundles)
    # Native role-less chat Agents remain profileless. Only the Companion's
    # existing plugin-scoped marker opts its native chat identity into persona.
    if preset.get("companion"):
        metadata["creationToolBundleIds"] = ["virtual_human_life"]
    agent_id = agent["agentId"]
    directory.update_agent_instance(
        agent_id, permission_preset="request_approval", metadata=metadata,
        prompt_template_id=_prompt_template_id(preset),
        persona_profile=deepcopy(preset.get("personaProfile") or {}),
        task_profile=deepcopy(preset.get("taskProfile") or {}),
        tool_policy=deepcopy(preset.get("toolPolicy") or {}),
        memory_policy=deepcopy(preset.get("memoryPolicy") or {}),
        reasoning_effort_by_slot=deepcopy(preset.get("reasoningEffortBySlot") or {}),
    )
    if preset.get("avatarAsset"):
        _install_avatar(agent_id, preset["avatarAsset"])
    if not agent.get("directSessionId"):
        session_service.ensure_agent_direct_session(
            agent_id=agent_id, title=agent["displayName"], created_by="deployment_bootstrap",
        )
    if preset.get("companion"):
        from .companion_preset import ensure_public_companion

        ensure_public_companion(agent_id, deepcopy(preset["companion"]))
    directory.update_agent_instance(agent_id, metadata={"publicPresetSeedComplete": True})


def ensure_public_agent_presets() -> dict[str, Any]:
    """Create missing presets and resume only interrupted, owned seed records."""
    from core.web.services import agent_directory_service as directory

    presets = load_public_agent_presets()
    with _SEED_LOCK:
        agents = directory.list_agents(include_archived=True, detail="summary")
        created: list[str] = []
        ids: list[str] = []
        for preset in presets:
            agent = _find_existing(agents, preset)
            if agent is None:
                agent = directory.create_agent_instance(
                    display_name=preset["displayName"],
                    llm_bindings=_model_bindings(preset),
                    primary_mode=preset.get("primaryMode") or "chat",
                    role_key=preset.get("roleKey") or "",
                    prompt_template_id=_prompt_template_id(preset),
                    created_by="deployment_bootstrap",
                    initial_tool_policy=deepcopy(preset.get("toolPolicy") or {}),
                    metadata={"publicPresetKey": preset["key"],
                              "publicPresetVersion": PUBLIC_PRESET_VERSION,
                              "publicPresetSeedComplete": False},
                )
                agents.append(agent)
                created.append(agent["agentId"])
            metadata = agent.get("metadata") or {}
            if (agent.get("status") != "archived"
                    and metadata.get("publicPresetKey") == preset["key"]
                    and metadata.get("publicPresetVersion") == PUBLIC_PRESET_VERSION
                    and metadata.get("publicPresetSeedComplete") is False):
                _finish_seed(agent, preset)
            ids.append(agent["agentId"])
        return {"publicPresetAgentIds": ids, "createdAgentIds": created}
