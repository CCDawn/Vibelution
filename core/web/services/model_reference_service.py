"""LLM model reference lifecycle helpers.

This module keeps deletion and rebinding decisions grounded in the same
workspace-wide reference index. Historical supervision artifacts are reported
for visibility, but they are not treated as blockers.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
_HISTORICAL_REFERENCE_LIMIT = 50
_ACTIVE_RUN_STATUSES = {"", "active", "queued", "running", "paused", "stopping", "started", "in_progress"}


class ModelReferenceConflictError(ValueError):
    """Raised when a model delete would leave live references behind."""

    def __init__(self, impact: dict[str, Any]):
        self.impact = impact
        model_id = str(impact.get("modelId") or "").strip()
        live_count = int(impact.get("liveReferenceCount") or 0)
        super().__init__(
            f"Cannot delete LLM model {model_id!r}: {live_count} live reference(s) still point to it."
        )


def _normalized_model_id(value: Any) -> str:
    return str(value or "").strip()


def _display_path(path: Path, project_root: Path) -> str:
    try:
        return str(path.relative_to(project_root)).replace("\\", "/")
    except ValueError:
        return str(path)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _reference(
    *,
    source: str,
    source_path: str,
    path: str,
    field: str,
    owner_type: str,
    owner_id: str = "",
    label: str = "",
    historical: bool = False,
) -> dict[str, Any]:
    return {
        "source": source,
        "sourcePath": source_path,
        "path": path,
        "field": field,
        "ownerType": owner_type,
        "ownerId": owner_id,
        "label": label,
        "historical": historical,
    }


def _append_if_model_ref(
    refs: list[dict[str, Any]],
    model_id: str,
    value: Any,
    *,
    source: str,
    source_path: str,
    path: str,
    field: str,
    owner_type: str,
    owner_id: str = "",
    label: str = "",
    historical: bool = False,
) -> None:
    if _normalized_model_id(value) != model_id:
        return
    refs.append(
        _reference(
            source=source,
            source_path=source_path,
            path=path,
            field=field,
            owner_type=owner_type,
            owner_id=owner_id,
            label=label,
            historical=historical,
        )
    )


def _scan_llm_bindings(
    refs: list[dict[str, Any]],
    model_id: str,
    bindings: Any,
    *,
    source: str,
    source_path: str,
    base_path: str,
    owner_type: str,
    owner_id: str = "",
    label: str = "",
    historical: bool = False,
) -> None:
    if not isinstance(bindings, dict):
        return
    for slot, binding in sorted(bindings.items(), key=lambda item: str(item[0])):
        if not isinstance(binding, dict):
            continue
        slot_key = str(slot or "").strip()
        _append_if_model_ref(
            refs,
            model_id,
            binding.get("modelId"),
            source=source,
            source_path=source_path,
            path=f"{base_path}.{slot_key}.modelId",
            field=f"llmBindings.{slot_key}.modelId",
            owner_type=owner_type,
            owner_id=owner_id,
            label=label,
            historical=historical,
        )


def _scan_agent_binding_payload(
    refs: list[dict[str, Any]],
    model_id: str,
    payload: Any,
    *,
    source: str,
    source_path: str,
    base_path: str,
    owner_type: str,
    owner_id: str = "",
    label: str = "",
) -> None:
    if not isinstance(payload, dict):
        return
    _append_if_model_ref(
        refs,
        model_id,
        payload.get("dialogueModelId"),
        source=source,
        source_path=source_path,
        path=f"{base_path}.dialogueModelId",
        field="dialogueModelId",
        owner_type=owner_type,
        owner_id=owner_id,
        label=label,
    )
    _scan_llm_bindings(
        refs,
        model_id,
        payload.get("llmBindings"),
        source=source,
        source_path=source_path,
        base_path=f"{base_path}.llmBindings",
        owner_type=owner_type,
        owner_id=owner_id,
        label=label,
    )


def _scan_public_config_refs(refs: list[dict[str, Any]], model_id: str, public_config: dict[str, Any]) -> None:
    llm = public_config.get("llm", {}) if isinstance(public_config, dict) else {}
    profiles = llm.get("profiles", {}) if isinstance(llm, dict) else {}
    if isinstance(profiles, dict):
        for profile_id, profile in sorted(profiles.items(), key=lambda item: str(item[0])):
            if not isinstance(profile, dict):
                continue
            profile_key = str(profile_id or "").strip()
            _append_if_model_ref(
                refs,
                model_id,
                profile.get("model_ref"),
                source="public_config",
                source_path="config.toml",
                path=f"llm.profiles.{profile_key}.model_ref",
                field="model_ref",
                owner_type="llm_profile",
                owner_id=profile_key,
                label=str(profile.get("label") or profile_key).strip(),
            )

    tools = public_config.get("tools", {}) if isinstance(public_config, dict) else {}
    image2 = tools.get("image2", {}) if isinstance(tools, dict) else {}
    if isinstance(image2, dict):
        _append_if_model_ref(
            refs,
            model_id,
            image2.get("default_model_ref"),
            source="public_config",
            source_path="config.toml",
            path="tools.image2.default_model_ref",
            field="default_model_ref",
            owner_type="tool_default",
            owner_id="tools.image2",
        )

    git = public_config.get("git", {}) if isinstance(public_config, dict) else {}
    if isinstance(git, dict):
        _append_if_model_ref(
            refs,
            model_id,
            git.get("commit_message_model_ref"),
            source="public_config",
            source_path="config.toml",
            path="git.commit_message_model_ref",
            field="commit_message_model_ref",
            owner_type="git",
            owner_id="commit_message",
        )


def _scan_agent_registry_refs(refs: list[dict[str, Any]], model_id: str, project_root: Path) -> None:
    path = project_root / "workspace" / "agents" / "agents.json"
    source_path = _display_path(path, project_root)
    payload = _load_json(path)
    agents = payload.get("agents") if isinstance(payload, dict) else None
    if not isinstance(agents, list):
        return
    for index, agent in enumerate(agents):
        if not isinstance(agent, dict):
            continue
        agent_id = _normalized_model_id(agent.get("agentId") or agent.get("id")) or str(index)
        label = str(agent.get("displayName") or agent.get("name") or agent_id).strip()
        for field in ("dialogueModelId", "agentTemplateLabel"):
            _append_if_model_ref(
                refs,
                model_id,
                agent.get(field),
                source="agent_registry",
                source_path=source_path,
                path=f"agents[{index}].{field}",
                field=field,
                owner_type="agent",
                owner_id=agent_id,
                label=label,
            )
        _scan_llm_bindings(
            refs,
            model_id,
            agent.get("llmBindings"),
            source="agent_registry",
            source_path=source_path,
            base_path=f"agents[{index}].llmBindings",
            owner_type="agent",
            owner_id=agent_id,
            label=label,
        )


def _scan_chat_room_refs(refs: list[dict[str, Any]], model_id: str, project_root: Path) -> None:
    path = project_root / "workspace" / "chat_rooms" / "chat_rooms.json"
    source_path = _display_path(path, project_root)
    payload = _load_json(path)
    rooms = payload.get("rooms") if isinstance(payload, dict) else None
    if not isinstance(rooms, list):
        return
    for room_index, room in enumerate(rooms):
        if not isinstance(room, dict):
            continue
        room_id = _normalized_model_id(room.get("roomId") or room.get("id")) or str(room_index)
        participants = room.get("participants")
        if not isinstance(participants, list):
            continue
        for participant_index, participant in enumerate(participants):
            if not isinstance(participant, dict):
                continue
            participant_id = _normalized_model_id(
                participant.get("participantId") or participant.get("agentId") or participant.get("sessionId")
            ) or str(participant_index)
            owner_id = f"{room_id}:{participant_id}"
            label = str(participant.get("title") or participant.get("agentCode") or participant_id).strip()
            base_path = f"rooms[{room_index}].participants[{participant_index}]"
            for field in ("dialogueModelId", "agentTemplateLabel"):
                _append_if_model_ref(
                    refs,
                    model_id,
                    participant.get(field),
                    source="chat_room_registry",
                    source_path=source_path,
                    path=f"{base_path}.{field}",
                    field=field,
                    owner_type="chat_room_participant",
                    owner_id=owner_id,
                    label=label,
                )
            _scan_llm_bindings(
                refs,
                model_id,
                participant.get("llmBindings"),
                source="chat_room_registry",
                source_path=source_path,
                base_path=f"{base_path}.llmBindings",
                owner_type="chat_room_participant",
                owner_id=owner_id,
                label=label,
            )


def _active_supervised_snapshot_path(project_root: Path) -> Path | None:
    index_path = project_root / ".runtime" / "runtime-manager" / "work_runs" / "supervised" / "index.json"
    index = _load_json(index_path)
    active_run_id = _normalized_model_id(index.get("activeRunId")) if isinstance(index, dict) else ""
    if not active_run_id:
        return None
    return index_path.parent / "runs" / f"{active_run_id}.json"


def _scan_active_supervised_run_refs(refs: list[dict[str, Any]], model_id: str, project_root: Path) -> None:
    path = _active_supervised_snapshot_path(project_root)
    if path is None:
        return
    source_path = _display_path(path, project_root)
    payload = _load_json(path)
    if not payload:
        return
    status = str(payload.get("status") or "").strip().lower()
    if status not in _ACTIVE_RUN_STATUSES:
        return
    run_id = _normalized_model_id(payload.get("runId") or path.stem)
    _scan_agent_binding_payload(
        refs,
        model_id,
        payload.get("currentAgentBinding"),
        source="active_supervised_run",
        source_path=source_path,
        base_path="currentAgentBinding",
        owner_type="supervised_run",
        owner_id=run_id,
        label="currentAgentBinding",
    )
    agent_bindings = payload.get("agentBindings")
    if not isinstance(agent_bindings, dict):
        return
    for role, binding in sorted(agent_bindings.items(), key=lambda item: str(item[0])):
        role_key = str(role or "").strip()
        _scan_agent_binding_payload(
            refs,
            model_id,
            binding,
            source="active_supervised_run",
            source_path=source_path,
            base_path=f"agentBindings.{role_key}",
            owner_type="supervised_run_role",
            owner_id=f"{run_id}:{role_key}",
            label=role_key,
        )


def _scan_historical_supervised_refs(
    refs: list[dict[str, Any]], model_id: str, project_root: Path, *, limit: int = _HISTORICAL_REFERENCE_LIMIT
) -> None:
    base = project_root / "workspace" / "supervised_evolution"
    if not base.exists():
        return
    candidates: list[tuple[str, Path]] = []
    for source_name, subdir in (("supervised_decision", "decisions"), ("supervised_session", "sessions")):
        root = base / subdir
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.json"), key=lambda item: str(item)):
            candidates.append((source_name, path))
    for source_name, path in candidates:
        if len(refs) >= limit:
            return
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if model_id not in text:
            continue
        refs.append(
            _reference(
                source=source_name,
                source_path=_display_path(path, project_root),
                path="$",
                field="json",
                owner_type="supervised_artifact",
                owner_id=path.stem,
                historical=True,
            )
        )


def scan_model_references(
    model_id: str,
    *,
    public_config: dict[str, Any] | None = None,
    project_root: Path | str | None = None,
    include_public_config: bool = True,
) -> dict[str, Any]:
    """Return live and historical references to a model library id."""

    normalized_model_id = _normalized_model_id(model_id)
    root = Path(project_root) if project_root is not None else PROJECT_ROOT
    live_refs: list[dict[str, Any]] = []
    historical_refs: list[dict[str, Any]] = []
    if not normalized_model_id:
        return {
            "modelId": "",
            "liveReferences": [],
            "historicalReferences": [],
            "liveReferenceCount": 0,
            "historicalReferenceCount": 0,
            "blocking": False,
        }
    if include_public_config and isinstance(public_config, dict):
        _scan_public_config_refs(live_refs, normalized_model_id, public_config)
    _scan_agent_registry_refs(live_refs, normalized_model_id, root)
    _scan_chat_room_refs(live_refs, normalized_model_id, root)
    _scan_active_supervised_run_refs(live_refs, normalized_model_id, root)
    _scan_historical_supervised_refs(historical_refs, normalized_model_id, root)
    return {
        "modelId": normalized_model_id,
        "liveReferences": live_refs,
        "historicalReferences": historical_refs,
        "liveReferenceCount": len(live_refs),
        "historicalReferenceCount": len(historical_refs),
        "blocking": bool(live_refs),
    }


def assert_model_delete_safe(
    model_id: str,
    *,
    public_config: dict[str, Any] | None = None,
    project_root: Path | str | None = None,
    include_public_config: bool = True,
) -> dict[str, Any]:
    impact = scan_model_references(
        model_id,
        public_config=public_config,
        project_root=project_root,
        include_public_config=include_public_config,
    )
    if impact["liveReferenceCount"]:
        raise ModelReferenceConflictError(impact)
    return impact


def _replace_public_config_refs(public_config: dict[str, Any], from_model_id: str, to_model_id: str) -> list[dict[str, Any]]:
    updated_refs: list[dict[str, Any]] = []
    llm = public_config.get("llm", {}) if isinstance(public_config, dict) else {}
    profiles = llm.get("profiles", {}) if isinstance(llm, dict) else {}
    if isinstance(profiles, dict):
        for profile_id, profile in sorted(profiles.items(), key=lambda item: str(item[0])):
            if not isinstance(profile, dict) or _normalized_model_id(profile.get("model_ref")) != from_model_id:
                continue
            profile["model_ref"] = to_model_id
            updated_refs.append(
                _reference(
                    source="public_config",
                    source_path="config.toml",
                    path=f"llm.profiles.{profile_id}.model_ref",
                    field="model_ref",
                    owner_type="llm_profile",
                    owner_id=str(profile_id),
                )
            )
    tools = public_config.get("tools", {}) if isinstance(public_config, dict) else {}
    image2 = tools.get("image2", {}) if isinstance(tools, dict) else {}
    if isinstance(image2, dict) and _normalized_model_id(image2.get("default_model_ref")) == from_model_id:
        image2["default_model_ref"] = to_model_id
        updated_refs.append(
            _reference(
                source="public_config",
                source_path="config.toml",
                path="tools.image2.default_model_ref",
                field="default_model_ref",
                owner_type="tool_default",
                owner_id="tools.image2",
            )
        )
    git = public_config.get("git", {}) if isinstance(public_config, dict) else {}
    if isinstance(git, dict) and _normalized_model_id(git.get("commit_message_model_ref")) == from_model_id:
        git["commit_message_model_ref"] = to_model_id
        updated_refs.append(
            _reference(
                source="public_config",
                source_path="config.toml",
                path="git.commit_message_model_ref",
                field="commit_message_model_ref",
                owner_type="git",
                owner_id="commit_message",
            )
        )
    return updated_refs


def _replace_llm_binding_refs(
    bindings: Any,
    from_model_id: str,
    to_model_id: str,
    *,
    source: str,
    source_path: str,
    base_path: str,
    owner_type: str,
    owner_id: str,
) -> list[dict[str, Any]]:
    updated_refs: list[dict[str, Any]] = []
    if not isinstance(bindings, dict):
        return updated_refs
    for slot, binding in sorted(bindings.items(), key=lambda item: str(item[0])):
        if not isinstance(binding, dict) or _normalized_model_id(binding.get("modelId")) != from_model_id:
            continue
        slot_key = str(slot or "").strip()
        binding["modelId"] = to_model_id
        updated_refs.append(
            _reference(
                source=source,
                source_path=source_path,
                path=f"{base_path}.{slot_key}.modelId",
                field=f"llmBindings.{slot_key}.modelId",
                owner_type=owner_type,
                owner_id=owner_id,
            )
        )
    return updated_refs


def _replace_workspace_agent_refs(path: Path, project_root: Path, from_model_id: str, to_model_id: str) -> tuple[list[dict[str, Any]], bool]:
    payload = _load_json(path)
    agents = payload.get("agents") if isinstance(payload, dict) else None
    if not isinstance(agents, list):
        return [], False
    source_path = _display_path(path, project_root)
    updated_refs: list[dict[str, Any]] = []
    for index, agent in enumerate(agents):
        if not isinstance(agent, dict):
            continue
        agent_id = _normalized_model_id(agent.get("agentId") or agent.get("id")) or str(index)
        for field in ("dialogueModelId", "agentTemplateLabel"):
            if _normalized_model_id(agent.get(field)) != from_model_id:
                continue
            agent[field] = to_model_id
            updated_refs.append(
                _reference(
                    source="agent_registry",
                    source_path=source_path,
                    path=f"agents[{index}].{field}",
                    field=field,
                    owner_type="agent",
                    owner_id=agent_id,
                )
            )
        updated_refs.extend(
            _replace_llm_binding_refs(
                agent.get("llmBindings"),
                from_model_id,
                to_model_id,
                source="agent_registry",
                source_path=source_path,
                base_path=f"agents[{index}].llmBindings",
                owner_type="agent",
                owner_id=agent_id,
            )
        )
    if updated_refs:
        _write_json(path, payload)
    return updated_refs, bool(updated_refs)


def _replace_workspace_chat_room_refs(path: Path, project_root: Path, from_model_id: str, to_model_id: str) -> tuple[list[dict[str, Any]], bool]:
    payload = _load_json(path)
    rooms = payload.get("rooms") if isinstance(payload, dict) else None
    if not isinstance(rooms, list):
        return [], False
    source_path = _display_path(path, project_root)
    updated_refs: list[dict[str, Any]] = []
    for room_index, room in enumerate(rooms):
        if not isinstance(room, dict):
            continue
        room_id = _normalized_model_id(room.get("roomId") or room.get("id")) or str(room_index)
        participants = room.get("participants")
        if not isinstance(participants, list):
            continue
        for participant_index, participant in enumerate(participants):
            if not isinstance(participant, dict):
                continue
            participant_id = _normalized_model_id(
                participant.get("participantId") or participant.get("agentId") or participant.get("sessionId")
            ) or str(participant_index)
            owner_id = f"{room_id}:{participant_id}"
            base_path = f"rooms[{room_index}].participants[{participant_index}]"
            for field in ("dialogueModelId", "agentTemplateLabel"):
                if _normalized_model_id(participant.get(field)) != from_model_id:
                    continue
                participant[field] = to_model_id
                updated_refs.append(
                    _reference(
                        source="chat_room_registry",
                        source_path=source_path,
                        path=f"{base_path}.{field}",
                        field=field,
                        owner_type="chat_room_participant",
                        owner_id=owner_id,
                    )
                )
            updated_refs.extend(
                _replace_llm_binding_refs(
                    participant.get("llmBindings"),
                    from_model_id,
                    to_model_id,
                    source="chat_room_registry",
                    source_path=source_path,
                    base_path=f"{base_path}.llmBindings",
                    owner_type="chat_room_participant",
                    owner_id=owner_id,
                )
            )
    if updated_refs:
        _write_json(path, payload)
    return updated_refs, bool(updated_refs)


def rebind_model_references(
    from_model_id: str,
    to_model_id: str,
    *,
    public_config: dict[str, Any] | None = None,
    project_root: Path | str | None = None,
    update_workspace: bool = True,
) -> dict[str, Any]:
    """Replace live references from one model id to another.

    Historical supervised decision/session artifacts are never rewritten.
    """

    normalized_from = _normalized_model_id(from_model_id)
    normalized_to = _normalized_model_id(to_model_id)
    if not normalized_from:
        raise ValueError("from_model_id is required")
    if not normalized_to:
        raise ValueError("to_model_id is required")
    if normalized_from == normalized_to:
        raise ValueError("from_model_id and to_model_id must differ")

    root = Path(project_root) if project_root is not None else PROJECT_ROOT
    updated_public_config = copy.deepcopy(public_config) if isinstance(public_config, dict) else None
    impact_before = scan_model_references(normalized_from, public_config=updated_public_config, project_root=root)
    updated_refs: list[dict[str, Any]] = []
    workspace_files_changed: list[str] = []

    if isinstance(updated_public_config, dict):
        updated_refs.extend(_replace_public_config_refs(updated_public_config, normalized_from, normalized_to))

    if update_workspace:
        agent_path = root / "workspace" / "agents" / "agents.json"
        refs, changed = _replace_workspace_agent_refs(agent_path, root, normalized_from, normalized_to)
        updated_refs.extend(refs)
        if changed:
            workspace_files_changed.append(_display_path(agent_path, root))
        room_path = root / "workspace" / "chat_rooms" / "chat_rooms.json"
        refs, changed = _replace_workspace_chat_room_refs(room_path, root, normalized_from, normalized_to)
        updated_refs.extend(refs)
        if changed:
            workspace_files_changed.append(_display_path(room_path, root))

    impact_after = scan_model_references(normalized_from, public_config=updated_public_config, project_root=root)
    return {
        "fromModelId": normalized_from,
        "toModelId": normalized_to,
        "publicConfig": updated_public_config,
        "impactBefore": impact_before,
        "impactAfter": impact_after,
        "updatedReferences": updated_refs,
        "updatedReferenceCount": len(updated_refs),
        "workspaceFilesChanged": workspace_files_changed,
    }


__all__ = [
    "ModelReferenceConflictError",
    "assert_model_delete_safe",
    "rebind_model_references",
    "scan_model_references",
]
