"""Agent directory residual ops: inbox, workspace, ensure-session, profile defaults.

Claim scope: inbox/group-context messages, workspace territory writes,
ensure/reactivate agent for session, steward/fixed-role/challenge defaults,
and project-memory proposals still on the facade.

Serializer wrappers for ensure/reactivate stay on the facade.

Late-bound facade keeps monkeypatches stable.
"""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import stat
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# Local default for signature evaluation (facade remains SSOT).
DEFAULT_AGENT_PRIMARY_MODE = "chat"

_source_authority_ref_fn = None
_projection_edit_contract_fn = None


def _service():
    from core.web.services import agent_directory_service

    return agent_directory_service


def _active_agent_for_direct_session(
    state: dict[str, Any],
    session_id: str,
    *,
    exclude_agent_id: str = "",
) -> dict[str, Any] | None:
    s = _service()
    normalized = str(session_id or "").strip()
    excluded = str(exclude_agent_id or "").strip()
    if not normalized:
        return None
    for item in state.get("agents") or []:
        if not isinstance(item, dict):
            continue
        agent_id = str(item.get("agentId") or "").strip()
        if excluded and agent_id == excluded:
            continue
        if str(item.get("status") or "active").strip().lower() == "archived":
            continue
        if str(item.get("directSessionId") or "").strip() == normalized:
            return item
    return None


def _active_agent_prompt_template_id(agent: dict[str, Any]) -> str:
    s = _service()
    return s._normalize_prompt_template_id(
        agent.get("promptTemplateId")
        or s._agent_metadata_prompt_template_id(agent)
        or s._infer_agent_prompt_template_id(agent)
    )


def _active_chat_session_id() -> str:
    s = _service()
    try:
        payload = s.load_chat_state(s._active_project_root())
    except Exception:
        return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("active_conversation_id") or "").strip()


def _agent_context_window_limit(
    agent: dict[str, Any] | None,
    *,
    hydration: Any | None = None,
) -> int:
    s = _service()
    model_id = s.agent_dialogue_model_id(agent) if isinstance(agent, dict) else ""
    if not model_id:
        return 0
    if hydration is not None:
        return int(hydration.model_context_window_limits_by_model_id.get(model_id) or 0)
    try:
        from config import get_config
        from config.public_config import resolve_llm_model_context_window

        config = get_config()
        model_library = getattr(config.llm, "model_library", {}) or {}
        entry = model_library.get(model_id) if isinstance(model_library, dict) else None
        if not isinstance(entry, dict):
            return 0
        provider = None
        provider_id = str(entry.get("provider_id") or "").strip()
        if provider_id:
            provider = config.llm.get_provider(provider_id)
        return resolve_llm_model_context_window(entry, provider)
    except Exception:
        return 0


def _agent_from_runtime_env(agent_id: str) -> dict[str, Any]:
    s = _service()
    agent = s.get_agent(agent_id) or {}
    env_bindings = s._agent_llm_bindings_from_runtime_env()
    if not env_bindings:
        return agent
    payload = dict(agent) if isinstance(agent, dict) else {}
    payload["agentId"] = str(payload.get("agentId") or agent_id or "").strip()
    payload["llmBindings"] = {
        **s.normalize_agent_llm_bindings(payload.get("llmBindings")),
        **env_bindings,
    }
    payload.setdefault("directSessionId", str(os.environ.get("VIBELUTION_AGENT_DIRECT_SESSION_ID") or "").strip())
    payload.setdefault("workspacePath", str(os.environ.get("VIBELUTION_AGENT_WORKSPACE_PATH") or "").strip())
    metadata = dict(payload.get("metadata") or {})
    supervised_role = str(os.environ.get("VIBELUTION_SUPERVISED_ROLE") or "").strip()
    if supervised_role:
        metadata.setdefault("supervisedRole", supervised_role)
    if metadata:
        payload["metadata"] = metadata
    return payload


def _agent_inbox_messages_for_agent(
    agent: dict[str, Any],
    *,
    hydration: Any | None = None,
    limit: int = 8,
    status: str = "pending",
) -> list[dict[str, Any]]:
    s = _service()
    agent_id = str(agent.get("agentId") or "").strip()
    if hydration is None:
        return s.list_agent_inbox_messages_for_agent(agent_id, limit=limit, status=status)
    messages = list(hydration.agent_inbox_messages_by_agent.get(agent_id) or [])
    normalized_status = str(status or "").strip().lower()
    if normalized_status:
        messages = [
            item for item in messages
            if str(item.get("status") or "pending").strip().lower() == normalized_status
        ]
    return messages[-max(1, int(limit or 1)) :]


def _agent_inbox_pending_count_for_agent(
    agent: dict[str, Any],
    *,
    hydration: Any | None = None,
    status: str = "pending",
) -> int:
    s = _service()
    agent_id = str(agent.get("agentId") or "").strip()
    if hydration is None:
        return s.count_agent_inbox_messages_for_agent(agent_id, status=status)
    normalized_status = str(status or "").strip().lower()
    if normalized_status == "pending" and agent_id in hydration.agent_inbox_pending_count_by_agent:
        return hydration.agent_inbox_pending_count_by_agent[agent_id]
    messages = list(hydration.agent_inbox_messages_by_agent.get(agent_id) or [])
    if not normalized_status:
        return len(messages)
    count = sum(
        1
        for item in messages
        if str(item.get("status") or "pending").strip().lower() == normalized_status
    )
    if normalized_status == "pending":
        hydration.agent_inbox_pending_count_by_agent[agent_id] = count
    return count


def _agent_inbox_thread_id(source_agent: dict[str, Any] | None, target_agent: dict[str, Any]) -> str:
    s = _service()
    source_id = str((source_agent or {}).get("agentId") or "external").strip() or "external"
    target_id = str(target_agent.get("agentId") or "target").strip() or "target"
    return f"agent:{source_id}->{target_id}"


def _agent_llm_bindings_from_runtime_env() -> dict[str, dict[str, str]]:
    s = _service()
    bindings: dict[str, dict[str, str]] = {}
    raw_bindings = str(os.environ.get("VIBELUTION_AGENT_LLM_BINDINGS_JSON") or "").strip()
    if raw_bindings:
        try:
            payload = json.loads(raw_bindings)
        except json.JSONDecodeError as exc:
            raise s.AgentDirectoryError("Runtime Agent LLM bindings env is not valid JSON.") from exc
        bindings = s.normalize_agent_llm_bindings(payload)
    model_id = str(os.environ.get("VIBELUTION_AGENT_LLM_MODEL_ID") or "").strip()
    if model_id:
        slot = str(os.environ.get("VIBELUTION_AGENT_LLM_SLOT") or s.DEFAULT_AGENT_LLM_SLOT).strip() or s.DEFAULT_AGENT_LLM_SLOT
        bindings[slot] = {"modelId": model_id}
    return bindings


def _agent_message_source_label(message: dict[str, Any]) -> str:
    s = _service()
    code = str(message.get("sourceAgentCode") or "").strip()
    name = str(message.get("sourceAgentName") or "").strip()
    source_id = str(message.get("sourceAgentId") or "").strip()
    if code and name:
        return f"{code} · {name}"
    return name or code or source_id or str(message.get("createdBy") or "external").strip() or "external"


def _agent_metadata_conversation_index_updates(kind: Any) -> dict[str, Any]:
    s = _service()
    normalized = s.normalize_conversation_index_kind(kind)
    if normalized not in {
        s.CONVERSATION_INDEX_KIND_PERSONAL_AGENT,
        s.CONVERSATION_INDEX_KIND_TEAM_AGENT,
        s.CONVERSATION_INDEX_KIND_HIDDEN,
    }:
        return {}
    updates: dict[str, Any] = {
        "conversationIndexKind": normalized,
        "conversationIndexVisibility": s._conversation_index_visibility_for_kind(normalized),
    }
    if normalized in {s.CONVERSATION_INDEX_KIND_TEAM_AGENT, s.CONVERSATION_INDEX_KIND_HIDDEN}:
        updates["showInSessionIndex"] = False
    return updates


def _agent_metadata_prompt_template_id(agent: dict[str, Any]) -> str:
    s = _service()
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    return s._normalize_prompt_template_id(metadata.get("promptTemplateId"))


def _agent_prompt_template_binding(agent: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    default_prompt_template_id = s._infer_agent_prompt_template_id(agent)
    active_prompt_template_id = s._active_agent_prompt_template_id(agent)
    customized = bool(
        active_prompt_template_id
        and default_prompt_template_id
        and active_prompt_template_id != default_prompt_template_id
    )
    return {
        "promptTemplateId": active_prompt_template_id,
        "defaultPromptTemplateId": default_prompt_template_id,
        "promptTemplateCustomized": customized,
    }


def _agent_runtime_from_env() -> dict[str, Any]:
    s = _service()
    agent_id = str(os.environ.get("VIBELUTION_AGENT_ID") or "").strip()
    if not agent_id:
        return {}
    session_id = str(os.environ.get("VIBELUTION_AGENT_DIRECT_SESSION_ID") or "").strip()
    supervised_role = str(os.environ.get("VIBELUTION_SUPERVISED_ROLE") or "").strip()
    agent = s._agent_from_runtime_env(agent_id)
    delegation_policy = s.resolve_delegation_policy_for_agent(agent_id)
    tool_policy = s.resolve_tool_policy_for_agent(agent_id, session_id=session_id)
    tool_policy = s._with_runtime_tool_grants(
        tool_policy,
        s.supervised_role_runtime_tools(supervised_role),
        source="supervised_conversation_harness" if supervised_role else "",
    )
    tool_policy = s._effective_agent_tool_policy(tool_policy, delegation_policy)
    return {
        "agentId": agent_id,
        "sessionId": session_id,
        "turnId": "",
        "roomId": "",
        "roundId": "",
        "supervisedRole": supervised_role,
        "agent": agent,
        "toolPolicy": tool_policy,
        "memoryPolicy": s.resolve_memory_policy_for_agent(agent_id),
        "delegationPolicy": delegation_policy,
        "supervisionPolicy": s.resolve_supervision_policy_for_agent(agent_id),
    }


def _agent_workspace_event_path(agent: dict[str, Any], filename: str) -> Path:
    s = _service()
    return s._resolve_project_path(str(agent.get("workspacePath") or "")) / "events" / filename


def _agent_workspace_territory(agent: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    agent_id = str(agent.get("agentId") or "").strip()
    private_root = str(agent.get("workspacePath") or s._agent_workspace_relative_path(agent_id)).strip()
    if not s._is_agent_private_workspace_path(private_root, agent_id):
        private_root = s._agent_workspace_relative_path(agent_id)
    subdirs = {
        subdir: f"{private_root}/{subdir}"
        for subdir in s.AGENT_WORKSPACE_SUBDIRS
    }
    return {
        "schemaVersion": 1,
        "agentId": agent_id,
        "privateRoot": private_root,
        "sharedRoot": s.AGENT_SHARED_WORKSPACE_PATH,
        "defaultWriteScope": "private",
        "readScopes": list(s.AGENT_TERRITORY_READ_SCOPES),
        "writeScopes": list(s.AGENT_TERRITORY_WRITE_SCOPES),
        "subdirs": subdirs,
        "memoryRoot": subdirs.get("memory", ""),
        "eventsRoot": subdirs.get("events", ""),
        "artifactsRoot": subdirs.get("artifacts", ""),
        "scratchRoot": subdirs.get("scratch", ""),
        "inboxRoot": subdirs.get("inbox", ""),
        "outboxRoot": subdirs.get("outbox", ""),
        "runsRoot": subdirs.get("runs", ""),
        "legacyWorkspacePath": str((agent.get("metadata") or {}).get("legacyWorkspacePath") or "").strip()
        if isinstance(agent.get("metadata"), dict)
        else "",
    }


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    s = _service()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    s.record_agent_api_hydration_event_file_changed(path)


def _blocked_decision(tool_name: str, reason: str, policy_id: str, agent_id: str, message: str) -> Any:
    s = _service()
    return s.ToolPolicyDecision(False, message=message, reason=reason, policy_id=policy_id, agent_id=agent_id)


def _clamp_int(value: Any, *, minimum: int, maximum: int, default: int) -> int:
    s = _service()
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _count_pending_agent_inbox_messages_for_agents(agents: list[dict[str, Any]]) -> dict[str, int]:
    s = _service()
    result: dict[str, int] = {}
    for agent in agents:
        agent_id = str(agent.get("agentId") or "").strip()
        if not agent_id:
            continue
        try:
            result[agent_id] = s._count_jsonl_matching_status(
                s._agent_workspace_event_path(agent, "agent_inbox_messages.jsonl"),
                status="pending",
            )
        except Exception as exc:
            s._debug_logger.warning(
                f"Failed to count pending inbox messages for agent={agent_id}. error={type(exc).__name__}: {exc}",
                tag="AGENT_TOOL_DIRECTORY",
            )
            result[agent_id] = 0
    return result


def _ensure_active_direct_session_available(
    state: dict[str, Any],
    session_id: str,
    *,
    agent_id: str,
) -> None:
    s = _service()
    normalized = str(session_id or "").strip()
    if not normalized:
        return
    existing = s._active_agent_for_direct_session(state, normalized, exclude_agent_id=agent_id)
    if existing is None:
        return
    s._record_agent_direct_session_collision_rejected(
        session_id=normalized,
        agent_id=str(agent_id or "").strip(),
        existing_agent=existing,
    )
    existing_agent_id = str(existing.get("agentId") or "").strip()
    raise s.AgentDirectoryError(f"Agent direct session is already bound to another active Agent: {existing_agent_id}")


def _fallback_agent_code(agent_id: Any) -> str:
    s = _service()
    fragment = s._safe_fragment(agent_id)[-3:].upper()
    return f"{s.AGENT_CODE_PREFIX}{fragment or '000'}"


def _find_agent_by_direct_session(state: dict[str, Any], session_id: str) -> dict[str, Any] | None:
    s = _service()
    normalized = str(session_id or "").strip()
    if not normalized:
        return None
    for item in state.get("agents") or []:
        if isinstance(item, dict) and str(item.get("directSessionId") or "").strip() == normalized:
            return item
    return None


def _get_config_value(source: Any, *keys: str, default: Any = None) -> Any:
    s = _service()
    for key in keys:
        if isinstance(source, dict) and key in source:
            return source.get(key)
        if hasattr(source, key):
            return getattr(source, key)
    return default


def _group_context_events_for_agent(
    agent: dict[str, Any],
    *,
    hydration: Any | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    s = _service()
    agent_id = str(agent.get("agentId") or "").strip()
    if hydration is None:
        return s.list_group_context_events_for_agent(agent_id, limit=limit)
    events = list(hydration.group_context_events_by_agent.get(agent_id) or [])
    return events[-max(1, int(limit or 1)) :]


def _jsonl_file_has_records(path: Path) -> bool:
    s = _service()
    try:
        if not path.is_file() or path.stat().st_size <= 0:
            return False
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    return True
    except OSError:
        return False
    return False


def _lexical_project_path(path_value: str) -> Path:
    s = _service()
    raw = str(path_value or "").strip()
    path = Path(raw)
    if path.parts and path.parts[0].lower() == "workspace":
        path = s._workspace_path(*path.parts[1:])
    elif not path.is_absolute():
        path = s._project_root() / path
    return Path(os.path.abspath(path))


def _list_recent_tool_governance_requests_for_agent(agent_id: str, *, limit: int = 6) -> list[dict[str, Any]]:
    s = _service()
    try:
        # Governance service lives under core.web.services, not agent_directory.
        from core.web.services.agent_tool_governance_service import list_tool_governance_requests

        return list_tool_governance_requests(agent_id=agent_id, status="", limit=limit)
    except Exception as exc:
        s._debug_logger.warning(
            f"Failed to list recent tool governance requests for agent={agent_id}, limit={limit}. error={type(exc).__name__}: {exc}",
            tag="AGENT_TOOL_DIRECTORY",
        )
        return []


def _load_recent_tool_governance_requests_for_agents(
    agents: list[dict[str, Any]],
    *,
    limit: int = 6,
) -> dict[str, list[dict[str, Any]]]:
    s = _service()
    result: dict[str, list[dict[str, Any]]] = {}
    for agent in agents:
        agent_id = str(agent.get("agentId") or "").strip()
        if not agent_id:
            continue
        try:
            requests = s._read_tool_governance_requests_for_agent(agent, limit=limit)
        except Exception as exc:
            s._debug_logger.warning(
                f"Failed to read tool governance requests for agent={agent_id}, limit={limit}. error={type(exc).__name__}: {exc}",
                tag="AGENT_TOOL_DIRECTORY",
            )
            requests = []
        requests.sort(
            key=lambda item: (
                str(item.get("createdAt") or ""),
                str(item.get("requestId") or item.get("eventId") or ""),
            ),
            reverse=True,
        )
        result[agent_id] = requests[: max(1, int(limit or 1))]
    return result


def _model_context_window_limits_for_agents(agents: list[dict[str, Any]]) -> dict[str, int]:
    s = _service()
    model_ids = sorted(
        {
            model_id
            for model_id in (s.agent_dialogue_model_id(agent) for agent in list(agents or []) if isinstance(agent, dict))
            if model_id
        }
    )
    if not model_ids:
        return {}
    try:
        from config import get_config
        from config.public_config import resolve_llm_model_context_window

        config = get_config()
        model_library = getattr(config.llm, "model_library", {}) or {}
        result: dict[str, int] = {}
        for model_id in model_ids:
            entry = model_library.get(model_id) if isinstance(model_library, dict) else None
            if not isinstance(entry, dict):
                result[model_id] = 0
                continue
            provider = None
            provider_id = str(entry.get("provider_id") or "").strip()
            if provider_id:
                provider = config.llm.get_provider(provider_id)
            try:
                result[model_id] = int(resolve_llm_model_context_window(entry, provider) or 0)
            except Exception:
                result[model_id] = 0
        return result
    except Exception:
        return {model_id: 0 for model_id in model_ids}


def _new_agent_id(existing_ids: set[str] | None = None) -> str:
    s = _service()
    existing = set(existing_ids or set())
    base = f"agent-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}"
    candidate = base
    suffix = 2
    while candidate in existing:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def _new_event_id(prefix: str) -> str:
    s = _service()
    return f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}"


def _path_has_reparse_component(path: Path, *, stop_at: Path) -> bool:
    s = _service()
    current = Path(os.path.abspath(path))
    boundary = Path(os.path.abspath(stop_at))
    if current != boundary and not current.is_relative_to(boundary):
        return True
    while True:
        try:
            is_reparse_point = s._path_is_reparse_point(current)
        except FileNotFoundError:
            is_reparse_point = False
        except OSError:
            return True
        if is_reparse_point:
            return True
        if current == boundary:
            break
        current = current.parent
    return False


def _path_is_reparse_point(path: Path) -> bool:
    s = _service()
    attributes = int(getattr(path.lstat(), "st_file_attributes", 0) or 0)
    return bool(
        path.is_symlink()
        or attributes & int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    )


def _path_is_within(path: Path, root: Path) -> bool:
    s = _service()
    resolved_path = Path(path).resolve()
    resolved_root = Path(root).resolve()
    return resolved_path == resolved_root or resolved_root in resolved_path.parents


def _projection_edit_contract(kind: str, source_id: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    s = _service()
    global _projection_edit_contract_fn
    if _projection_edit_contract_fn is None:
        from core.agent_kernel.source_authority import projection_edit_contract

        _projection_edit_contract_fn = projection_edit_contract
    return _projection_edit_contract_fn(kind, source_id, metadata)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    s = _service()
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def _read_tool_governance_requests_for_agent(agent: dict[str, Any], *, limit: int | None = None) -> list[dict[str, Any]]:
    s = _service()
    path = s._resolve_project_path(str(agent.get("workspacePath") or "")) / "events" / "tool_governance_requests.jsonl"
    if limit is not None:
        return s._read_recent_jsonl(path, limit=max(1, int(limit or 1)))
    return s._read_jsonl(path)


def _record_agent_direct_session_collision_rejected(
    *,
    session_id: str,
    agent_id: str,
    existing_agent: dict[str, Any],
) -> None:
    s = _service()
    try:
        s.record_runtime_scene_event(
            "agent_directory",
            "agent_direct_session_collision",
            "agent.direct_session_collision.rejected",
            message="Agent directSessionId collision was rejected before saving.",
            level="warning",
            outcome="rejected",
            fields={
                "sessionId": str(session_id or "").strip(),
                "agentId": str(agent_id or "").strip(),
                "existingAgentId": str(existing_agent.get("agentId") or "").strip(),
                "existingAgentCode": s._normalize_agent_code(existing_agent.get("agentCode")),
                "existingStatus": str(existing_agent.get("status") or "active").strip() or "active",
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_agent_list_loaded(
    *,
    include_archived: bool,
    detail: str,
    raw_agent_count: int,
    returned_agent_count: int,
    timings: dict[str, float],
    hydration_timings: dict[str, float],
    repair_cache_hit: bool = False,
) -> None:
    s = _service()
    total_ms = float(timings.get("total") or 0)
    lock_wait_ms = float(timings.get("lock_wait") or 0)
    if total_ms < 1000 and lock_wait_ms < 250:
        return
    try:
        s.record_runtime_scene_event(
            "agent_directory",
            "list_agents",
            "agent_directory.list_agents.slow",
            message="Agent directory list_agents was slow.",
            level="warning" if total_ms >= 3000 or lock_wait_ms >= 1000 else "info",
            outcome="observed",
            fields={
                "includeArchived": bool(include_archived),
                "detail": str(detail or "full"),
                "rawAgentCount": raw_agent_count,
                "returnedAgentCount": returned_agent_count,
                "repairCacheHit": bool(repair_cache_hit),
                "timingsMs": dict(timings),
                "hydrationTimingsMs": dict(hydration_timings),
                "slowestStage": s._slowest_timing_stage(timings),
                "slowestHydrationStage": s._slowest_timing_stage(hydration_timings),
            },
        )
    except Exception:
        return


def _record_agent_territory_write_blocked(
    agent: dict[str, Any],
    decision: Any,
    *,
    purpose: str = "",
) -> None:
    s = _service()
    try:
        s.record_runtime_scene_event(
            "agent_directory",
            "territory",
            "agent_territory.write_blocked",
            message=decision.message or "Agent workspace write blocked.",
            level="warning",
            outcome="blocked",
            fields={
                "agentId": str(agent.get("agentId") or decision.agent_id or "").strip(),
                "agentCode": s._normalize_agent_code(agent.get("agentCode")),
                "path": decision.path,
                "scope": decision.scope,
                "reason": decision.reason,
                "purpose": s.trim_lines(str(purpose or ""), max_lines=1),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_memory_event(event_code: str, payload: dict[str, Any], *, agent_id: str, lifecycle: bool = False) -> None:
    s = _service()
    try:
        s.record_runtime_scene_event(
            "agent_memory",
            "events",
            event_code,
            message=event_code,
            level="info",
            outcome="written",
            fields={
                "agentId": agent_id,
                "eventId": str(payload.get("eventId") or "").strip(),
                "messageId": str(payload.get("messageId") or "").strip(),
                "sourceAgentId": str(payload.get("sourceAgentId") or "").strip(),
                "targetAgentId": str(payload.get("targetAgentId") or agent_id).strip(),
                "sourceRoomId": str(payload.get("sourceRoomId") or "").strip(),
                "sourceRoundId": str(payload.get("sourceRoundId") or "").strip(),
                "status": str(payload.get("status") or "").strip(),
                "promptEligible": bool(payload.get("promptEligible", True)),
            },
            lifecycle=lifecycle,
        )
    except Exception:
        return


def _safe_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    s = _service()
    if not isinstance(metadata, dict):
        return {}
    safe: dict[str, Any] = {}
    for key, value in list(metadata.items())[:32]:
        normalized_key = str(key or "").strip()
        if not normalized_key:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[normalized_key] = value
        elif isinstance(value, (list, tuple)):
            safe[normalized_key] = [
                item if isinstance(item, (str, int, float, bool)) or item is None else str(item)
                for item in list(value)[:24]
            ]
        else:
            safe[normalized_key] = str(value)
    return safe


def _session_workspace_has_activity(session_id: str, *, session_workspace_path: str = "") -> bool:
    s = _service()
    session_id = str(session_id or "").strip()
    candidates: list[Path] = []
    raw_workspace_path = str(session_workspace_path or "").strip()
    if raw_workspace_path:
        candidates.append(s._resolve_project_path(raw_workspace_path))
    if session_id:
        candidates.append(s._workspace_path("sessions", session_id, seed=False))

    seen: set[Path] = set()
    for session_root in candidates:
        resolved = Path(session_root).resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        for relative in s.SESSION_AGENT_ACTIVITY_FILES:
            if s._jsonl_file_has_records(resolved / relative):
                return True
    return False


def _session_workspace_root_exists(session_id: str) -> bool:
    s = _service()
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        return False
    try:
        return s._workspace_path("sessions", normalized_session_id, seed=False).exists()
    except OSError:
        return False


def _slowest_timing_stage(timings: dict[str, float]) -> str:
    s = _service()
    candidates = {
        str(key): float(value or 0)
        for key, value in dict(timings or {}).items()
        if str(key) != "total"
    }
    if not candidates:
        return ""
    return max(candidates.items(), key=lambda item: item[1])[0]


def _source_authority_ref(kind: str, source_id: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    s = _service()
    global _source_authority_ref_fn
    if _source_authority_ref_fn is None:
        from core.agent_kernel.source_authority import source_ref

        _source_authority_ref_fn = source_ref
    return _source_authority_ref_fn(kind, source_id, metadata)


def _tool_governance_requests_for_agent(
    agent_id: str,
    *,
    hydration: Any | None = None,
    limit: int = 6,
) -> list[dict[str, Any]]:
    s = _service()
    if hydration is None:
        return s._list_recent_tool_governance_requests_for_agent(agent_id, limit=limit)
    return list(hydration.tool_governance_requests_by_agent.get(agent_id) or [])[: max(1, int(limit or 1))]


def _with_runtime_tool_grants(
    policy: dict[str, Any],
    grants: Iterable[Any],
    *,
    source: str = "",
) -> dict[str, Any]:
    s = _service()
    runtime_source = str(source or "").strip()
    external_runtime_profile = (
        runtime_source.partition(":")[2]
        if runtime_source.startswith("external_agent_task:")
        else ""
    )
    external_runtime_tools = external_runtime_profile in {
        "read_only",
        "workspace_write",
        "full_access",
    }
    exclusive_runtime_tools = (
        runtime_source == "self_evolution_autonomous_loop" or external_runtime_tools
    )
    runtime_grants = s._tool_name_list(grants or [])
    if not runtime_grants and not exclusive_runtime_tools:
        return policy
    persistent_allowed = s._tool_name_list(policy.get("allowedTools") or [])
    blocked = set(s._tool_name_list(policy.get("blockedTools") or []))
    effective_grants = [tool for tool in runtime_grants if tool and tool not in blocked]
    if exclusive_runtime_tools:
        effective_grant_set = set(effective_grants)
        allowed = (
            [tool for tool in persistent_allowed if tool in effective_grant_set]
            if external_runtime_tools
            else effective_grants
        )
        allowed_set = set(allowed)
        preferred = [
            tool
            for tool in s._tool_name_list(policy.get("preferredTools") or [])
            if tool in allowed_set
        ]
        added = (
            []
            if external_runtime_tools
            else [tool for tool in effective_grants if tool not in persistent_allowed]
        )
        temporary_allowed = added
    else:
        allowed = list(persistent_allowed)
        added = []
        for tool in effective_grants:
            if tool in allowed:
                continue
            allowed.append(tool)
            added.append(tool)
        preferred = s._tool_name_list(policy.get("preferredTools") or [])
        temporary_allowed = s._tool_name_list(
            list(policy.get("temporaryAllowedTools") or []) + added
        )
    grants_mutation = any(tool in s.MUTATING_AGENT_TOOL_NAMES for tool in effective_grants)
    mutation_access = str(policy.get("mutationAccess") or "inherit").strip()
    runtime_mutation_access = (
        "none"
        if external_runtime_profile == "read_only"
        else (
            "controlled"
            if grants_mutation and mutation_access == "none" and not external_runtime_tools
            else mutation_access
        )
    )
    approval_overrides = dict(policy.get("approvalOverrides") or {})
    max_calls_per_turn = policy.get("maxCallsPerTurn")
    runtime_max_calls_per_turn = max_calls_per_turn
    if runtime_source in {
        "self_evolution_autonomous_loop",
        "supervised_conversation_harness",
        "supervised_baseline_self_edit",
    }:
        for tool in effective_grants:
            approval_overrides.setdefault(tool, "never")
    if external_runtime_tools:
        from core.web.services.tool_catalog import metadata_for_tool

        for tool in allowed:
            capabilities = set(metadata_for_tool(tool).get("capabilityTags") or [])
            if "read_only" not in capabilities:
                approval_overrides[tool] = "always"
    if runtime_source == "self_evolution_autonomous_loop":
        try:
            current_max_calls = int(max_calls_per_turn or 0)
        except (TypeError, ValueError):
            current_max_calls = 0
        runtime_max_calls_per_turn = max(current_max_calls, 24)
    if (
        not exclusive_runtime_tools
        and not added
        and runtime_mutation_access == mutation_access
        and approval_overrides == dict(policy.get("approvalOverrides") or {})
        and runtime_max_calls_per_turn == max_calls_per_turn
    ):
        return policy
    return {
        **policy,
        "allowedTools": allowed,
        "preferredTools": preferred,
        "temporaryAllowedTools": temporary_allowed,
        "runtimeToolSource": runtime_source,
        "mutationAccess": runtime_mutation_access,
        "maxCallsPerTurn": runtime_max_calls_per_turn,
        "approvalOverrides": approval_overrides,
    }


def _with_session_terminal_protocol_defaults(agent: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    """Project untouched private chat defaults onto the current session protocol.

    Covers the pre-terminal legacy list, the protocol list from before the
    personal memory tool, the episode-era default that still carried
    generation-handoff memory tools, the narrow-handoff default from
    before supersede, and the episodic-named default from before the
    personal-memory rename. Untouched defaults drop generation-handoff
    tools and add the current personal-memory tools. User-customized
    policies are never widened or narrowed. The projection is
    deterministic and read-only, so persisted ToolPolicy remains the
    single writable source.
    """
    s = _service()

    agent_id = str(agent.get("agentId") or "").strip()
    policy_id = str(agent.get("toolPolicyId") or policy.get("policyId") or "").strip()
    if not agent_id or policy_id != f"tool-{agent_id}":
        return policy
    primary_mode = str(agent.get("primaryMode") or s._infer_agent_primary_mode(agent)).strip()
    if not s._is_session_agent_primary_mode(primary_mode):
        return policy
    allowed = s._tool_name_list(policy.get("allowedTools") or [])
    preferred = s._tool_name_list(policy.get("preferredTools") or [])
    legacy_untouched = (
        allowed == list(s._LEGACY_SESSION_AGENT_ALLOWED_TOOLS)
        and preferred == list(s._LEGACY_SESSION_AGENT_PREFERRED_TOOLS)
    )
    protocol_untouched = (
        allowed == list(s.SESSION_PROTOCOL_ALLOWED_TOOLS)
        and preferred == list(s.SESSION_PROTOCOL_PREFERRED_TOOLS)
    )
    episode_era_untouched = (
        allowed == list(s._EPISODE_ERA_SESSION_AGENT_ALLOWED_TOOLS)
        and preferred == list(s.SESSION_PROTOCOL_PREFERRED_TOOLS)
    )
    narrow_handoff_untouched = (
        allowed == list(s._NARROW_HANDOFF_SESSION_AGENT_ALLOWED_TOOLS)
        and preferred == list(s.DEFAULT_SESSION_AGENT_PREFERRED_TOOLS)
    )
    episodic_named_untouched = (
        allowed == list(s._EPISODIC_NAMED_SESSION_AGENT_ALLOWED_TOOLS)
        and preferred == list(s.DEFAULT_SESSION_AGENT_PREFERRED_TOOLS)
    )
    if not (
        legacy_untouched
        or protocol_untouched
        or episode_era_untouched
        or narrow_handoff_untouched
        or episodic_named_untouched
    ):
        rewritten_allowed = s._rewrite_legacy_personal_memory_tool_names(allowed)
        rewritten_preferred = s._rewrite_legacy_personal_memory_tool_names(preferred)
        if rewritten_allowed == allowed and rewritten_preferred == preferred:
            return policy
        return {
            **policy,
            "allowedTools": rewritten_allowed,
            "preferredTools": rewritten_preferred,
        }
    return {
        **policy,
        "allowedTools": list(s.DEFAULT_SESSION_AGENT_ALLOWED_TOOLS),
        "preferredTools": list(s.DEFAULT_SESSION_AGENT_PREFERRED_TOOLS),
    }


def _without_disabled_agent_tools(policy: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    blocked_tools = s.DISABLED_AGENT_DIRECT_READ_TOOL_NAMES
    allowed = [name for name in s._tool_name_list(policy.get("allowedTools") or []) if name not in blocked_tools]
    preferred = [name for name in s._tool_name_list(policy.get("preferredTools") or []) if name not in blocked_tools]
    temporary_allowed = [
        name for name in s._tool_name_list(policy.get("temporaryAllowedTools") or []) if name not in blocked_tools
    ]
    if (
        allowed == s._tool_name_list(policy.get("allowedTools") or [])
        and preferred == s._tool_name_list(policy.get("preferredTools") or [])
        and temporary_allowed == s._tool_name_list(policy.get("temporaryAllowedTools") or [])
    ):
        return policy
    return {
        **policy,
        "allowedTools": allowed,
        "preferredTools": preferred,
        "temporaryAllowedTools": temporary_allowed,
    }


def _write_jsonl(path: Path, payloads: list[dict[str, Any]]) -> None:
    s = _service()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(item, ensure_ascii=False, sort_keys=True)
        for item in list(payloads or [])
        if isinstance(item, dict)
    ]
    path.write_text(("\n".join(lines) + "\n") if lines else "", encoding="utf-8", newline="\n")
    s.record_agent_api_hydration_event_file_changed(path)


def consume_agent_inbox_message(
    agent_id: str,
    message_id: str,
    *,
    consumed_by_session_id: str = "",
    consumed_by_turn_id: str = "",
) -> dict[str, Any]:
    s = _service()
    agent = s.get_agent(agent_id, include_archived=True)
    if not agent:
        raise s.AgentNotFoundError(f"Agent not found: {agent_id}")
    normalized_message_id = str(message_id or "").strip()
    if not normalized_message_id:
        raise s.AgentMessageNotFoundError("Agent inbox message id is required.")
    path = s._agent_workspace_event_path(agent, "agent_inbox_messages.jsonl")
    messages = s._read_jsonl(path)
    for item in messages:
        if str(item.get("messageId") or item.get("eventId") or "").strip() != normalized_message_id:
            continue
        if str(item.get("status") or "pending").strip().lower() != "consumed":
            item["status"] = "consumed"
            item["consumedAt"] = s.utc_now_iso()
            item["consumedBySessionId"] = str(consumed_by_session_id or agent.get("directSessionId") or "").strip()
            item["consumedByTurnId"] = str(consumed_by_turn_id or "").strip()
            s._write_jsonl(path, messages)
            s._record_memory_event("agent_inbox.message_consumed", item, agent_id=str(agent.get("agentId") or ""), lifecycle=True)
        return item
    raise s.AgentMessageNotFoundError(f"Agent inbox message not found: {message_id}")


def consume_all_agent_inbox_messages(
    agent_id: str,
    *,
    consumed_by_session_id: str = "",
    consumed_by_turn_id: str = "",
) -> dict[str, Any]:
    s = _service()
    agent = s.get_agent(agent_id, include_archived=True)
    if not agent:
        raise s.AgentNotFoundError(f"Agent not found: {agent_id}")
    path = s._agent_workspace_event_path(agent, "agent_inbox_messages.jsonl")
    messages = s._read_jsonl(path)
    now = s.utc_now_iso()
    consumed_ids: list[str] = []
    for item in messages:
        if str(item.get("status") or "pending").strip().lower() == "consumed":
            continue
        item["status"] = "consumed"
        item["consumedAt"] = now
        item["consumedBySessionId"] = str(consumed_by_session_id or agent.get("directSessionId") or "").strip()
        item["consumedByTurnId"] = str(consumed_by_turn_id or "").strip()
        consumed_ids.append(str(item.get("messageId") or item.get("eventId") or "").strip())
    if consumed_ids:
        s._write_jsonl(path, messages)
        s._record_memory_event(
            "agent_inbox.messages_consumed",
            {
                "eventId": s._new_event_id("agentinbox"),
                "messageId": "",
                "targetAgentId": str(agent.get("agentId") or "").strip(),
                "status": "consumed",
                "createdAt": now,
                "metadata": {"consumedCount": len(consumed_ids)},
            },
            agent_id=str(agent.get("agentId") or ""),
            lifecycle=True,
        )
    return {
        "agentId": str(agent.get("agentId") or "").strip(),
        "consumed": True,
        "consumedCount": len(consumed_ids),
        "consumedMessageIds": [item for item in consumed_ids if item],
        "remainingPendingCount": s.count_agent_inbox_messages_for_agent(agent_id, status="pending"),
    }


def count_agent_inbox_messages_for_agent(agent_id: str, *, status: str = "pending") -> int:
    s = _service()
    state = s.load_state()
    agent = s._find_agent(state, agent_id)
    if not agent:
        return 0
    return s._count_jsonl_matching_status(s._agent_workspace_event_path(agent, "agent_inbox_messages.jsonl"), status=status)


def current_agent_runtime() -> dict[str, Any]:
    s = _service()
    context = s._CURRENT_AGENT_RUNTIME.get({})
    if isinstance(context, dict) and context:
        return dict(context)
    env_runtime = s._agent_runtime_from_env()
    if not env_runtime.get("agentId"):
        return {}
    return env_runtime


def disable_group_context_events_for_room(
    source_room_id: str,
    *,
    agent_ids: list[str] | None = None,
    reason: str = "chat_room_reset",
) -> dict[str, Any]:
    s = _service()
    normalized_room_id = str(source_room_id or "").strip()
    if not normalized_room_id:
        return {"sourceRoomId": "", "changedAgentCount": 0, "disabledEventCount": 0}
    target_agent_ids = {
        str(item or "").strip()
        for item in list(agent_ids or [])
        if str(item or "").strip()
    }
    state = s.load_state()
    changed_agent_count = 0
    disabled_event_count = 0
    now = s.utc_now_iso()
    for agent in list(state.get("agents") or []):
        if not isinstance(agent, dict):
            continue
        agent_id = str(agent.get("agentId") or "").strip()
        if target_agent_ids and agent_id not in target_agent_ids:
            continue
        path = s._agent_workspace_event_path(agent, "group_context_events.jsonl")
        events = s._read_jsonl(path)
        changed = False
        agent_disabled_count = 0
        for event in events:
            if str(event.get("sourceRoomId") or "").strip() != normalized_room_id:
                continue
            if not bool(event.get("promptEligible", True)):
                continue
            event["promptEligible"] = False
            event["disabledAt"] = now
            event["disabledReason"] = s.trim_lines(str(reason or "chat_room_reset"), max_lines=1) or "chat_room_reset"
            changed = True
            agent_disabled_count += 1
        if not changed:
            continue
        s._write_jsonl(path, events)
        changed_agent_count += 1
        disabled_event_count += agent_disabled_count
        s._record_memory_event(
            "group_context.disabled_for_room",
            {
                "sourceRoomId": normalized_room_id,
                "targetAgentId": agent_id,
                "disabledEventCount": agent_disabled_count,
                "reason": s.trim_lines(str(reason or "chat_room_reset"), max_lines=1) or "chat_room_reset",
                "disabledAt": now,
            },
            agent_id=agent_id,
            lifecycle=True,
        )
    return {
        "sourceRoomId": normalized_room_id,
        "changedAgentCount": changed_agent_count,
        "disabledEventCount": disabled_event_count,
    }


def effective_visible_tool_names_for_current_agent(tools: Iterable[Any] | None = None) -> list[str]:
    s = _service()
    runtime = s.current_agent_runtime()
    if tools is None:
        try:
            from tools.Key_Tools import create_llm_facing_tools

            tools = create_llm_facing_tools()
        except Exception as exc:
            s._debug_logger.warning(
                f"Failed to build default LLM-facing tool list. Falling back to empty list. error={type(exc).__name__}: {exc}",
                tag="AGENT_TOOL_DIRECTORY",
            )
            tools = []
    visibility = s.compute_effective_tool_visibility(tools or [], policy=runtime.get("toolPolicy") or {})
    visible_tools = list(visibility.visible_tools)
    # Plugin tools require both ToolPolicy permission and an enabled per-Agent
    # binding. A policy entry by itself must not activate a plugin capability.
    from core.agent_plugins.runtime_extensions import (
        filter_agent_plugin_tool_names,
    )

    return filter_agent_plugin_tool_names(
        str(runtime.get("agentId") or "").strip(),
        visible_tools,
        runtime_context=runtime,
    )


def ensure_agent_for_session(
    session_id: str,
    *,
    display_name: str = "",
    llm_bindings: dict[str, Any] | None = None,
    primary_mode: str = DEFAULT_AGENT_PRIMARY_MODE,
    role_key: str = "",
    prompt_template_id: str = "",
    existing_agent_id: str = "",
    session_workspace_path: str = "",
    created_by: str = "session_repair",
    conversation_index_kind: str = "",
) -> dict[str, Any]:
    s = _service()
    normalized_session_id = str(session_id or "").strip()
    if not normalized_session_id:
        raise s.AgentDirectoryError("Session id is required to bind an AgentInstance.")

    with s._STATE_LOCK:
        state = s.repair_agent_directory()
        now = s.utc_now_iso()
        normalized_llm_bindings = s.normalize_agent_llm_bindings(llm_bindings)
        agent = s._find_agent(state, existing_agent_id)
        if agent is None:
            agent = s._find_agent_by_direct_session(state, normalized_session_id)
        if agent is None:
            session_visibility = s._direct_session_visibility(
                normalized_session_id,
                session_workspace_path=session_workspace_path,
            )
            metadata_payload = {
                "legacySessionWorkspacePath": str(session_workspace_path or "").strip(),
                "directSessionVisibility": session_visibility,
            }
            metadata_payload.update(s._agent_metadata_conversation_index_updates(conversation_index_kind))
            if str(created_by or "").strip() == "session_repair":
                metadata_payload.setdefault("conversationIndexKind", s.CONVERSATION_INDEX_KIND_PERSONAL_AGENT)
                metadata_payload.setdefault("conversationIndexVisibility", s.CONVERSATION_INDEX_VISIBILITY_USER_VISIBLE)
            created = s.create_agent_instance(
                display_name=display_name or normalized_session_id,
                llm_bindings=normalized_llm_bindings,
                primary_mode=primary_mode,
                role_key=role_key,
                prompt_template_id=prompt_template_id,
                direct_session_id=normalized_session_id,
                created_by=created_by,
                metadata=metadata_payload,
            )
            return created

        changed = False
        if not s._normalize_agent_code(agent.get("agentCode")):
            agent["agentCode"] = s._next_agent_code(
                state.get("agents") or [],
                exclude_agent_id=str(agent.get("agentId") or ""),
            )
            changed = True
        if str(agent.get("directSessionId") or "").strip() != normalized_session_id:
            s._ensure_active_direct_session_available(
                state,
                normalized_session_id,
                agent_id=str(agent.get("agentId") or "").strip(),
            )
            agent["directSessionId"] = normalized_session_id
            changed = True
        normalized_primary_mode = s._normalize_primary_mode(primary_mode or agent.get("primaryMode") or s.DEFAULT_AGENT_PRIMARY_MODE)
        if str(agent.get("primaryMode") or "").strip() != normalized_primary_mode:
            agent["primaryMode"] = normalized_primary_mode
            changed = True
        normalized_role_key = s._normalize_role_key(role_key or agent.get("roleKey") or s._infer_agent_role_key(agent))
        if str(agent.get("roleKey") or "").strip() != normalized_role_key:
            agent["roleKey"] = normalized_role_key
            changed = True
        normalized_prompt_template_id = s._normalize_prompt_template_id(
            prompt_template_id
            or agent.get("promptTemplateId")
            or s._agent_metadata_prompt_template_id(agent)
            or s._infer_agent_prompt_template_id(agent)
        )
        if str(agent.get("promptTemplateId") or "").strip() != normalized_prompt_template_id:
            agent["promptTemplateId"] = normalized_prompt_template_id
            changed = True
        title = s.trim_lines(display_name or "", max_lines=1).strip()
        if title:
            metadata = s._with_functional_display_name(dict(agent.get("metadata") or {}), title)
            if metadata != agent.get("metadata"):
                agent["metadata"] = metadata
                changed = True
            if s._should_repair_public_display_name(agent):
                responsibility_name = str(metadata.get("functionalDisplayName") or title).strip()
                agent["displayName"] = s._agent_public_display_name(
                    responsibility_name,
                    existing_agents=state.get("agents") or [],
                    agent_id=str(agent.get("agentId") or ""),
                    metadata=metadata,
                )
                agent["metadata"] = s._mark_display_name_responsibility(
                    dict(agent.get("metadata") or {}),
                    force=True,
                )
                changed = True
        if not str(agent.get("displayName") or "").strip():
            agent["displayName"] = s._agent_public_display_name(
                str(
                    (agent.get("metadata") or {}).get("functionalDisplayName")
                    or title
                    or agent.get("agentCode")
                    or agent.get("agentId")
                    or "Agent"
                ),
                existing_agents=state.get("agents") or [],
                agent_id=str(agent.get("agentId") or ""),
                metadata=dict(agent.get("metadata") or {}),
            )
            agent["metadata"] = s._mark_display_name_responsibility(
                dict(agent.get("metadata") or {}),
                force=True,
            )
            changed = True
        if normalized_llm_bindings and s.normalize_agent_llm_bindings(agent.get("llmBindings")) != normalized_llm_bindings:
            agent["llmBindings"] = normalized_llm_bindings
            changed = True
        if str(agent.get("status") or "active").strip() == "archived":
            s._record_agent_event("agent.ensure.skipped_archived", agent, lifecycle=True)
            raise s.AgentArchivedError(f"Archived Agent cannot be ensured for session: {agent.get('agentId') or ''}")
        policy_changed = s._ensure_session_agent_tool_policy(state, agent)
        if policy_changed:
            changed = True
        metadata = dict(agent.get("metadata") or {})
        creation_spec = metadata.get("creationSpec") if isinstance(metadata.get("creationSpec"), dict) else {}
        agent_created_by = str(agent.get("createdBy") or creation_spec.get("source") or "").strip()
        if (
            agent_created_by == "session_repair"
            and not str(agent.get("conversationIndexKind") or metadata.get("conversationIndexKind") or "").strip()
        ):
            metadata["conversationIndexKind"] = s.CONVERSATION_INDEX_KIND_PERSONAL_AGENT
            metadata.setdefault("conversationIndexVisibility", s.CONVERSATION_INDEX_VISIBILITY_USER_VISIBLE)
            agent["metadata"] = metadata
            changed = True
        conversation_index_updates = s._agent_metadata_conversation_index_updates(conversation_index_kind)
        for key, value in conversation_index_updates.items():
            if metadata.get(key) != value:
                metadata[key] = value
                agent["metadata"] = metadata
                changed = True
        legacy_path = str(session_workspace_path or "").strip()
        if legacy_path and metadata.get("legacySessionWorkspacePath") != legacy_path:
            metadata["legacySessionWorkspacePath"] = legacy_path
            agent["metadata"] = metadata
            changed = True
        session_visibility = s._direct_session_visibility(
            normalized_session_id,
            session_workspace_path=str(metadata.get("legacySessionWorkspacePath") or legacy_path),
        )
        if session_visibility != str(metadata.get("directSessionVisibility") or "").strip():
            metadata["directSessionVisibility"] = session_visibility
            agent["metadata"] = metadata
            changed = True
        workspace_path = str(agent.get("workspacePath") or "").strip() or s._agent_workspace_relative_path(str(agent["agentId"]))
        if not agent.get("workspacePath"):
            agent["workspacePath"] = workspace_path
            changed = True
        s._ensure_agent_workspace(workspace_path)
        memory_policy_id = str(agent.get("memoryPolicyId") or "").strip() or f"memory-{agent['agentId']}"
        if str(agent.get("memoryPolicyId") or "").strip() != memory_policy_id:
            agent["memoryPolicyId"] = memory_policy_id
            changed = True
        policies = s._memory_policies(state)
        if memory_policy_id not in policies:
            policies[memory_policy_id] = s.default_memory_policy(memory_policy_id, workspace_path)
            state["memoryPolicies"] = policies
            changed = True
        if changed:
            agent["updatedAt"] = now
            s.save_state(state)
            s._record_agent_event("agent.repaired", agent)
            s._record_agent_territory_event("agent_territory.resolved", agent, outcome="repaired")
    return s._agent_to_api(agent)


def ensure_agent_shared_workspace() -> Path:
    s = _service()
    path = s._resolve_project_path(s.AGENT_SHARED_WORKSPACE_PATH)
    shared_root = s._workspace_path("shared").resolve()
    if path != shared_root:
        raise s.AgentDirectoryError(f"Invalid shared workspace path: {path}")
    for subdir in ("memory", "artifacts", "notes", "logs", "research", "tmp"):
        (path / subdir).mkdir(parents=True, exist_ok=True)
    return path


def evaluate_agent_workspace_write(agent_id: str, path_value: str | Path, *, purpose: str = "") -> Any:
    s = _service()
    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        return s.AgentWorkspaceWriteDecision(
            False,
            path=str(path_value or ""),
            reason="missing_agent",
            message="Agent id is required for workspace writes.",
        )
    agent = s.get_agent(normalized_agent_id, include_archived=True)
    if not agent:
        return s.AgentWorkspaceWriteDecision(
            False,
            path=str(path_value or ""),
            reason="missing_agent",
            message=f"Agent not found: {normalized_agent_id}",
            agent_id=normalized_agent_id,
        )
    territory = s._agent_workspace_territory(agent)
    target = s._resolve_project_path(str(path_value or ""))
    private_root = s._resolve_project_path(str(territory.get("privateRoot") or ""))
    shared_root = s._resolve_project_path(str(territory.get("sharedRoot") or s.AGENT_SHARED_WORKSPACE_PATH))
    tool_policy = agent.get("toolPolicy") if isinstance(agent.get("toolPolicy"), dict) else s.resolve_tool_policy_for_agent(normalized_agent_id)
    write_scopes = set(s._normalize_tool_policy_scopes(tool_policy.get("writeScopes") if isinstance(tool_policy, dict) else []))
    if s._path_is_within(target, private_root):
        return s.AgentWorkspaceWriteDecision(
            True,
            path=s._relative_project_path(target),
            scope="private",
            agent_id=normalized_agent_id,
        )
    if s._path_is_within(target, shared_root):
        if "shared" in write_scopes:
            return s.AgentWorkspaceWriteDecision(
                True,
                path=s._relative_project_path(target),
                scope="shared",
                agent_id=normalized_agent_id,
            )
        decision = s.AgentWorkspaceWriteDecision(
            False,
            path=s._relative_project_path(target),
            scope="shared",
            reason="shared_write_requires_policy",
            message="Shared workspace writes require an explicit shared write policy.",
            agent_id=normalized_agent_id,
        )
        s._record_agent_territory_write_blocked(agent, decision, purpose=purpose)
        return decision
    decision = s.AgentWorkspaceWriteDecision(
        False,
        path=s._relative_project_path(target),
        scope="external",
        reason="outside_agent_territory",
        message="Agent writes must stay inside the Agent private territory unless a policy grants another scope.",
        agent_id=normalized_agent_id,
    )
    s._record_agent_territory_write_blocked(agent, decision, purpose=purpose)
    return decision


def filter_llm_tools_for_current_agent(tools: Iterable[Any]) -> list[Any]:
    s = _service()
    tool_list = list(tools or [])
    visible_names = set(s.effective_visible_tool_names_for_current_agent(tool_list))
    return [
        tool
        for tool in tool_list
        if str(getattr(tool, "name", "") or "").strip() in visible_names
    ]


def list_agent_inbox_messages_for_agent(
    agent_id: str,
    *,
    limit: int = 20,
    status: str = "pending",
    prompt_eligible_only: bool = False,
) -> list[dict[str, Any]]:
    s = _service()
    state = s.load_state()
    agent = s._find_agent(state, agent_id)
    if not agent:
        return []
    path = s._agent_workspace_event_path(agent, "agent_inbox_messages.jsonl")
    messages = s._read_recent_jsonl(path, limit=max(1, int(limit or 1)), status=status)
    normalized_status = str(status or "").strip().lower()
    if normalized_status:
        messages = [
            item for item in messages
            if str(item.get("status") or "pending").strip().lower() == normalized_status
        ]
    if prompt_eligible_only:
        messages = [item for item in messages if bool(item.get("promptEligible", True))]
    return messages[-max(1, int(limit or 1)) :]


def list_agent_policy_options() -> dict[str, list[dict[str, Any]]]:
    """Return lightweight policy options for Agent configuration forms."""
    s = _service()

    with s._STATE_LOCK:
        state = s.repair_agent_directory()
    agents = [item for item in state.get("agents") or [] if isinstance(item, dict)]
    return s.build_agent_policy_options(state=state, agents=agents)


def list_group_context_events_for_agent(agent_id: str, *, limit: int = 8, prompt_eligible_only: bool = False) -> list[dict[str, Any]]:
    s = _service()
    state = s.load_state()
    agent = s._find_agent(state, agent_id)
    if not agent:
        return []
    path = s._resolve_project_path(str(agent.get("workspacePath") or "")) / "events" / "group_context_events.jsonl"
    events = s._read_recent_jsonl(path, limit=max(1, int(limit or 1)))
    if prompt_eligible_only:
        events = [item for item in events if bool(item.get("promptEligible", True))]
    return events[-max(1, int(limit or 1)) :]


def list_project_memory_update_proposals(
    *,
    agent_id: str = "",
    status: str = "pending",
    limit: int = 50,
) -> list[dict[str, Any]]:
    s = _service()
    state = s.load_state()
    normalized_agent_id = str(agent_id or "").strip()
    if normalized_agent_id:
        agents = [s._find_agent(state, normalized_agent_id)]
    else:
        agents = [item for item in state.get("agents") or [] if isinstance(item, dict)]
    normalized_status = str(status or "").strip().lower()
    proposals: list[dict[str, Any]] = []
    for agent in agents:
        if not agent:
            continue
        path = s._agent_workspace_event_path(agent, "project_memory_updates.jsonl")
        for item in s._read_jsonl(path):
            if normalized_status and str(item.get("status") or "pending").strip().lower() != normalized_status:
                continue
            proposals.append(item)
    proposals.sort(
        key=lambda item: (
            str(item.get("createdAt") or ""),
            str(item.get("proposalId") or item.get("eventId") or ""),
        )
    )
    return proposals[: max(1, int(limit or 1))]


def scan_wakeable_agent_inbox_messages() -> dict[str, Any]:
    """Scan active Agent inboxes once without hydrating the Agent API directory."""
    s = _service()

    started_at = time.perf_counter()
    registry_load_started_at = time.perf_counter()
    state = s.load_state()
    registry_load_duration_ms = max(0, int((time.perf_counter() - registry_load_started_at) * 1000))
    agents = [
        dict(item)
        for item in list(state.get("agents") or [])
        if isinstance(item, dict)
        and str(item.get("status") or "active").strip().lower() != "archived"
        and str(item.get("agentId") or "").strip()
    ]
    agents.sort(
        key=lambda item: str(item.get("updatedAt") or item.get("createdAt") or ""),
        reverse=True,
    )
    messages: list[dict[str, Any]] = []
    non_empty_inbox_count = 0
    signature_duration_seconds = 0.0
    inbox_read_duration_seconds = 0.0
    error_count = 0
    error_type_counts: dict[str, int] = {}
    for agent in agents:
        agent_id = str(agent.get("agentId") or "").strip()
        if not str(agent.get("workspacePath") or "").strip():
            agent["workspacePath"] = s._agent_workspace_relative_path(agent_id)
        try:
            path = s._agent_workspace_event_path(agent, "agent_inbox_messages.jsonl")
            signature_started_at = time.perf_counter()
            signature = s._jsonl_signature(path)
            signature_duration_seconds += max(0.0, time.perf_counter() - signature_started_at)
            if not signature[1] or signature[3] <= 0:
                continue
            non_empty_inbox_count += 1
            read_started_at = time.perf_counter()
            message = _wakeable_agent_inbox_message_from_path(path)
            inbox_read_duration_seconds += max(0.0, time.perf_counter() - read_started_at)
            if message is not None:
                messages.append(message)
        except Exception as exc:
            error_count += 1
            error_type = type(exc).__name__
            if len(error_type_counts) < 8 or error_type in error_type_counts:
                error_type_counts[error_type] = int(error_type_counts.get(error_type) or 0) + 1
    return {
        "scannedAgentCount": len(agents),
        "nonEmptyInboxCount": non_empty_inbox_count,
        "wakeableMessageCount": len(messages),
        "messages": messages,
        "errorCount": error_count,
        "errorTypeCounts": error_type_counts,
        "agentRegistryLoadDurationMs": registry_load_duration_ms,
        "inboxSignatureDurationMs": max(0, int(signature_duration_seconds * 1000)),
        "inboxReadDurationMs": max(0, int(inbox_read_duration_seconds * 1000)),
        "durationMs": max(0, int((time.perf_counter() - started_at) * 1000)),
    }


def _wakeable_agent_inbox_message_from_path(path: Path) -> dict[str, Any] | None:
    s = _service()
    for item in s._read_jsonl(path):
        if str(item.get("status") or "pending").strip().lower() != "pending":
            continue
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        if bool(metadata.get("wakeRequested")):
            return item
    return None


def next_wakeable_agent_inbox_message_for_agent(agent_id: str) -> dict[str, Any] | None:
    """Return the oldest pending inbox message that requested an automatic wake."""
    s = _service()

    state = s.load_state()
    agent = s._find_agent(state, agent_id)
    if not agent:
        return None
    path = s._agent_workspace_event_path(agent, "agent_inbox_messages.jsonl")
    return _wakeable_agent_inbox_message_from_path(path)


def normalize_conversation_index_kind(value: Any) -> str:
    s = _service()
    kind = str(value or "").strip()
    if kind in s.CONVERSATION_INDEX_KINDS:
        return kind
    return ""


def reactivate_agent_instance(agent_id: str, *, reason: str = "", metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """Explicitly restore an archived AgentInstance to active status."""
    s = _service()

    with s._STATE_LOCK:
        state = s.load_state()
        agent = s._find_agent(state, agent_id)
        if agent is None:
            raise s.AgentNotFoundError(f"Agent not found: {agent_id}")
        if str(agent.get("status") or "active").strip() != "archived":
            return s._agent_to_api(agent)
        current_metadata = dict(agent.get("metadata") or {})
        if metadata:
            current_metadata.update(dict(metadata))
        if reason:
            current_metadata["reactivatedReason"] = s.trim_lines(str(reason or ""), max_lines=2)
        agent["metadata"] = current_metadata
        agent["status"] = "active"
        agent["updatedAt"] = s.utc_now_iso()
        s.save_state(state)
    s._record_agent_event("agent.reactivated", agent, lifecycle=True)
    return s._agent_to_api(agent)


def registry_path(*, project_root: Path | None = None) -> Path:
    s = _service()
    with s.scoped_project_root(project_root):
        return s._workspace_path("agents", "agents.json")


def resolve_agent_workspace_territory(agent_id: str) -> dict[str, Any]:
    s = _service()
    state = s.load_state()
    agent = s._find_agent(state, agent_id)
    if agent is None:
        return {}
    return s._agent_workspace_territory(agent)


def resolve_project_memory_update_proposal(
    agent_id: str,
    proposal_id: str,
    *,
    status: str,
    resolved_by: str = "",
    resolution_note: str = "",
) -> dict[str, Any]:
    s = _service()
    agent = s.get_agent(agent_id, include_archived=True)
    if not agent:
        raise s.AgentNotFoundError(f"Agent not found: {agent_id}")
    normalized_proposal_id = str(proposal_id or "").strip()
    if not normalized_proposal_id:
        raise s.AgentMemoryProposalNotFoundError("Project memory update proposal id is required.")
    normalized_status = str(status or "").strip().lower()
    if normalized_status not in {"pending", "applied", "rejected", "conflict", "superseded"}:
        raise s.AgentDirectoryError("Unsupported project memory update proposal status.")
    path = s._agent_workspace_event_path(agent, "project_memory_updates.jsonl")
    proposals = s._read_jsonl(path)
    for item in proposals:
        if str(item.get("proposalId") or item.get("eventId") or "").strip() != normalized_proposal_id:
            continue
        item["status"] = normalized_status
        if normalized_status == "pending":
            item["resolvedAt"] = ""
            item["resolvedBy"] = ""
            item["resolutionNote"] = ""
        else:
            item["resolvedAt"] = s.utc_now_iso()
            item["resolvedBy"] = s.trim_lines(str(resolved_by or "coordinator"), max_lines=1) or "coordinator"
            item["resolutionNote"] = s.trim_lines(str(resolution_note or ""), max_lines=4)
        s._write_jsonl(path, proposals)
        s._record_memory_event(
            "project_memory_update.resolved",
            item,
            agent_id=str(agent.get("agentId") or ""),
            lifecycle=True,
        )
        return item
    raise s.AgentMemoryProposalNotFoundError(f"Project memory update proposal not found: {proposal_id}")


def revoke_agent_inbox_message(
    agent_id: str,
    message_id: str,
    *,
    revoked_by: str = "user",
    reason: str = "",
) -> dict[str, Any]:
    s = _service()
    agent = s.get_agent(agent_id, include_archived=True)
    if not agent:
        raise s.AgentNotFoundError(f"Agent not found: {agent_id}")
    normalized_message_id = str(message_id or "").strip()
    if not normalized_message_id:
        raise s.AgentMessageNotFoundError("Agent inbox message id is required.")
    path = s._agent_workspace_event_path(agent, "agent_inbox_messages.jsonl")
    messages = s._read_jsonl(path)
    for item in messages:
        if str(item.get("messageId") or item.get("eventId") or "").strip() != normalized_message_id:
            continue
        if str(item.get("status") or "pending").strip().lower() != "revoked":
            item["status"] = "revoked"
            item["promptEligible"] = False
            item["revokedAt"] = s.utc_now_iso()
            item["revokedBy"] = str(revoked_by or "user").strip() or "user"
            item["revokeReason"] = s.trim_lines(str(reason or ""), max_lines=2)
            s._write_jsonl(path, messages)
            s._record_memory_event("agent_inbox.message_revoked", item, agent_id=str(agent.get("agentId") or ""), lifecycle=True)
        return item
    raise s.AgentMessageNotFoundError(f"Agent inbox message not found: {message_id}")


def utc_now_iso() -> str:
    s = _service()
    return datetime.now(timezone.utc).isoformat()


def write_agent_inbox_message(
    target_agent_id: str,
    *,
    content: str,
    source_agent_id: str = "",
    source_session_id: str = "",
    source_room_id: str = "",
    source_round_id: str = "",
    thread_id: str = "",
    kind: str = "agent_direct_message",
    summary: str = "",
    prompt_eligible: bool = True,
    created_by: str = "agent",
    metadata: dict[str, Any] | None = None,
    target_session_id: str = "",
    message_id: str = "",
) -> dict[str, Any]:
    s = _service()
    target_agent = s.get_agent(target_agent_id, include_archived=False)
    if not target_agent:
        raise s.AgentNotFoundError(f"Agent not found: {target_agent_id}")
    meta = metadata if isinstance(metadata, dict) else {}
    body_preview_only = bool(meta.get("bodyPreviewOnly") or meta.get("ssot") == "session")
    normalized_summary = s.trim_lines(str(summary or ""), max_lines=4).strip()
    normalized_content = str(content or "").strip()
    # SSOT: when session is body authority, inbox stores at most a non-authoritative preview.
    if body_preview_only:
        normalized_content = normalized_summary or s.trim_lines(normalized_content, max_lines=4).strip()
    if not normalized_content and not normalized_summary and not body_preview_only:
        raise s.AgentDirectoryError("Agent inbox message content is required.")
    if not normalized_content and body_preview_only:
        # Index-only row is allowed; keep empty content + summary pointer fields.
        normalized_content = ""
    normalized_source_agent_id = str(source_agent_id or "").strip()
    source_agent = s.get_agent(normalized_source_agent_id, include_archived=True) if normalized_source_agent_id else None
    if normalized_source_agent_id and not source_agent:
        raise s.AgentNotFoundError(f"Source agent not found: {normalized_source_agent_id}")
    now = s.utc_now_iso()
    resolved_message_id = str(message_id or "").strip() or s._new_event_id("agentmsg")
    # Prefer explicit session landing (ADR 0002); fall back to agent direct session.
    resolved_target_session_id = str(target_session_id or "").strip()
    if not resolved_target_session_id:
        resolved_target_session_id = str(meta.get("targetSessionId") or "").strip()
    if not resolved_target_session_id:
        resolved_target_session_id = str(target_agent.get("directSessionId") or "").strip()
    if not normalized_summary:
        normalized_summary = s.trim_lines(normalized_content or resolved_message_id, max_lines=4)
    event_payload = {
        "eventId": resolved_message_id,
        "messageId": resolved_message_id,
        "threadId": str(thread_id or "").strip() or s._agent_inbox_thread_id(source_agent, target_agent),
        "kind": s.trim_lines(str(kind or "agent_direct_message"), max_lines=1).strip() or "agent_direct_message",
        "status": "pending",
        "sourceAgentId": normalized_source_agent_id,
        "sourceAgentCode": str((source_agent or {}).get("agentCode") or "").strip(),
        "sourceAgentName": str((source_agent or {}).get("displayName") or "").strip(),
        "sourceSessionId": str(source_session_id or (source_agent or {}).get("directSessionId") or "").strip(),
        "sourceRoomId": str(source_room_id or "").strip(),
        "sourceRoundId": str(source_round_id or "").strip(),
        "targetAgentId": str(target_agent.get("agentId") or "").strip(),
        "targetAgentCode": str(target_agent.get("agentCode") or "").strip(),
        "targetAgentName": str(target_agent.get("displayName") or "").strip(),
        "targetSessionId": resolved_target_session_id,
        "content": normalized_content,
        "summary": normalized_summary,
        "promptEligible": bool(prompt_eligible),
        "createdBy": str(created_by or "agent").strip() or "agent",
        "createdAt": now,
        "consumedAt": "",
        "consumedBySessionId": "",
        "consumedByTurnId": "",
        "metadata": s._safe_metadata(metadata),
    }
    path = s._agent_workspace_event_path(target_agent, "agent_inbox_messages.jsonl")
    s._append_jsonl(path, event_payload)
    s._record_memory_event("memory.event_written", event_payload, agent_id=str(target_agent.get("agentId") or ""))
    s._record_memory_event("agent_inbox.message_written", event_payload, agent_id=str(target_agent.get("agentId") or ""), lifecycle=True)
    return event_payload


def write_current_tool_observation(
    *,
    tool_name: str,
    status: str,
    summary: str = "",
    arg_keys: list[str] | None = None,
) -> dict[str, Any] | None:
    s = _service()
    runtime = s.current_agent_runtime()
    agent_id = str(runtime.get("agentId") or "").strip()
    if not agent_id:
        return None
    agent = s._find_agent(s.load_state(), agent_id)
    if not agent:
        return None
    event_payload = {
        "eventId": s._new_event_id("toolobs"),
        "agentId": agent_id,
        "sessionId": str(runtime.get("sessionId") or "").strip(),
        "turnId": str(runtime.get("turnId") or "").strip(),
        "roomId": str(runtime.get("roomId") or "").strip(),
        "roundId": str(runtime.get("roundId") or "").strip(),
        "toolName": str(tool_name or "").strip(),
        "status": str(status or "").strip(),
        "summary": s.trim_lines(str(summary or ""), max_lines=4),
        "argKeys": list(arg_keys or [])[:24],
        "createdAt": s.utc_now_iso(),
    }
    path = s._resolve_project_path(str(agent.get("workspacePath") or "")) / "events" / "tool_observations.jsonl"
    s._append_jsonl(path, event_payload)
    s._record_memory_event("memory.event_written", event_payload, agent_id=agent_id)
    return event_payload


def write_group_context_event(agent_id: str, event: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    agent = s.get_agent(agent_id)
    if not agent:
        raise s.AgentNotFoundError(f"Agent not found: {agent_id}")
    workspace = s._resolve_project_path(str(agent.get("workspacePath") or ""))
    events_dir = workspace / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    event_payload = {
        "eventId": str(event.get("eventId") or s._new_event_id("groupctx")).strip(),
        "sourceRoomId": str(event.get("sourceRoomId") or "").strip(),
        "sourceRoundId": str(event.get("sourceRoundId") or "").strip(),
        "targetAgentId": str(agent_id or "").strip(),
        "targetSessionId": str(event.get("targetSessionId") or agent.get("directSessionId") or "").strip(),
        "topic": str(event.get("topic") or "").strip(),
        "summary": s.trim_lines(str(event.get("summary") or ""), max_lines=8),
        "ownMessage": s.trim_lines(str(event.get("ownMessage") or ""), max_lines=8),
        "peerHighlights": list(event.get("peerHighlights") or [])[:12],
        "promptEligible": bool(event.get("promptEligible", True)),
        "createdAt": str(event.get("createdAt") or s.utc_now_iso()).strip(),
    }
    s._append_jsonl(events_dir / "group_context_events.jsonl", event_payload)
    s._record_memory_event("memory.event_written", event_payload, agent_id=agent_id, lifecycle=True)
    s._record_memory_event("group_context.synced", event_payload, agent_id=agent_id, lifecycle=True)
    return event_payload


def write_project_memory_update_proposal(
    agent_id: str,
    *,
    lane_id: str,
    update: str,
    focus: str = "",
    details: str = "",
    related_files: list[str] | None = None,
    source_session_id: str = "",
    source_turn_id: str = "",
) -> dict[str, Any]:
    s = _service()
    agent = s.get_agent(agent_id, include_archived=False)
    if not agent:
        raise s.AgentNotFoundError(f"Agent not found: {agent_id}")
    normalized_lane_id = s.trim_lines(str(lane_id or ""), max_lines=1).strip()
    normalized_update = s.trim_lines(str(update or ""), max_lines=8).strip()
    if not normalized_lane_id:
        raise s.AgentDirectoryError("Project memory update lane id is required.")
    if not normalized_update:
        raise s.AgentDirectoryError("Project memory update summary is required.")
    now = s.utc_now_iso()
    proposal_id = s._new_event_id("memupd")
    event_payload = {
        "eventId": proposal_id,
        "proposalId": proposal_id,
        "kind": "project_memory_update",
        "status": "pending",
        "agentId": str(agent.get("agentId") or "").strip(),
        "agentCode": str(agent.get("agentCode") or "").strip(),
        "agentName": str(agent.get("displayName") or "").strip(),
        "sessionId": str(source_session_id or agent.get("directSessionId") or "").strip(),
        "turnId": str(source_turn_id or "").strip(),
        "laneId": normalized_lane_id,
        "focus": s.trim_lines(str(focus or ""), max_lines=2),
        "update": normalized_update,
        "details": s.trim_lines(str(details or normalized_update), max_lines=12),
        "relatedFiles": s._unique_string_list(list(related_files or []))[:12],
        "createdAt": now,
        "resolvedAt": "",
        "resolvedBy": "",
        "resolutionNote": "",
    }
    path = s._agent_workspace_event_path(agent, "project_memory_updates.jsonl")
    s._append_jsonl(path, event_payload)
    s._record_memory_event("memory.event_written", event_payload, agent_id=str(agent.get("agentId") or ""))
    s._record_memory_event(
        "project_memory_update.proposed",
        event_payload,
        agent_id=str(agent.get("agentId") or ""),
        lifecycle=True,
    )
    return event_payload
