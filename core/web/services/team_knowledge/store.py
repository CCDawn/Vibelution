"""Team knowledge store: paths, JSONL IO, owner context, and id helpers.

Claim scope: knowledge roots, inbox/central paths, JSON/JSONL helpers,
owner context coercion, bases-state load/save, and pure id utilities.
Late-binds ``team_knowledge_service`` for PROJECT_ROOT, schema, errors, and locks.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

from core.chat.chat_task_types import trim_lines


def _service():
    from core.web.services import team_knowledge_service

    return team_knowledge_service


def _iter_existing_knowledge_roots() -> list[Path]:
    s = _service()
    workspace_root = s._route_team_knowledge_workspace_path(seed=True)
    roots: list[Path] = []
    for parent in (workspace_root / "teams", workspace_root / "agents"):
        if not parent.exists():
            continue
        for path in sorted(parent.glob("*/knowledge/knowledge_bases.json")):
            roots.append(path.parent)
    return roots


def _load_knowledge_bases_state_from_path(path: Path) -> dict[str, Any]:
    s = _service()
    if not path.exists():
        return {"schemaVersion": s.SCHEMA_VERSION, "updatedAt": "", "knowledgeBases": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schemaVersion": s.SCHEMA_VERSION, "updatedAt": "", "knowledgeBases": []}
    if not isinstance(payload, dict):
        return {"schemaVersion": s.SCHEMA_VERSION, "updatedAt": "", "knowledgeBases": []}
    knowledge_bases = [item for item in list(payload.get("knowledgeBases") or []) if isinstance(item, dict)]
    return {
        "schemaVersion": int(payload.get("schemaVersion") or s.SCHEMA_VERSION),
        "updatedAt": str(payload.get("updatedAt") or ""),
        "knowledgeBases": knowledge_bases,
    }


def _load_bases_state_for_owner(owner_value: Any) -> dict[str, Any]:
    s = _service()
    path = s._knowledge_bases_path_for_owner(s._coerce_owner_context(owner_value))
    if not path.exists():
        return {"schemaVersion": s.SCHEMA_VERSION, "updatedAt": s.utc_now_iso(), "knowledgeBases": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schemaVersion": s.SCHEMA_VERSION, "updatedAt": s.utc_now_iso(), "knowledgeBases": []}
    if not isinstance(payload, dict):
        return {"schemaVersion": s.SCHEMA_VERSION, "updatedAt": s.utc_now_iso(), "knowledgeBases": []}
    payload.setdefault("schemaVersion", s.SCHEMA_VERSION)
    payload.setdefault("updatedAt", "")
    payload.setdefault("knowledgeBases", [])
    return payload


def _load_bases_state(team_id: str) -> dict[str, Any]:
    s = _service()
    return s._load_bases_state_for_owner(s._owner_context("team", team_id))


def _source_governance_for_owner(owner_value: Any) -> dict[str, Any]:
    s = _service()
    owner = s._coerce_owner_context(owner_value)
    path = s._owner_source_governance_path(owner)
    if not path.exists():
        return {
            "schemaVersion": s.SCHEMA_VERSION,
            "ownerType": owner["ownerType"],
            "ownerId": owner["ownerId"],
            "localStewardAgentIds": [],
            "updatedAt": "",
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return {
        "schemaVersion": int(payload.get("schemaVersion") or s.SCHEMA_VERSION),
        "ownerType": str(payload.get("ownerType") or owner["ownerType"]),
        "ownerId": str(payload.get("ownerId") or owner["ownerId"]),
        "localStewardAgentIds": s._unique_strings(payload.get("localStewardAgentIds") or []),
        "updatedAt": str(payload.get("updatedAt") or ""),
    }


def _save_bases_state_for_owner(owner_value: Any, state: dict[str, Any]) -> None:
    s = _service()
    s._write_json(s._knowledge_bases_path_for_owner(s._coerce_owner_context(owner_value)), state)


def _save_bases_state(team_id: str, state: dict[str, Any]) -> None:
    s = _service()
    s._save_bases_state_for_owner(s._owner_context("team", team_id), state)


def _append_audit(owner_value: Any, action: str, payload: dict[str, Any], *, actor_agent_id: str = "") -> None:
    s = _service()
    owner = s._coerce_owner_context(owner_value)
    s._append_jsonl(
        s._audit_path_for_owner(owner),
        {
            "auditId": s._new_event_id("kaudit"),
            "action": action,
            "actorAgentId": str(actor_agent_id or "").strip(),
            "createdAt": s.utc_now_iso(),
            "payload": {
                "ownerType": payload.get("ownerType") or owner.get("ownerType"),
                "ownerId": payload.get("ownerId") or owner.get("ownerId"),
                "teamId": payload.get("teamId"),
                "agentId": payload.get("agentId"),
                "knowledgeBaseId": payload.get("knowledgeBaseId") or payload.get("targetKnowledgeBaseId"),
                "sourceArtifactId": payload.get("sourceArtifactId"),
                "inboxSourceId": payload.get("inboxSourceId"),
                "centralSourceId": payload.get("centralSourceId"),
                "proposalId": payload.get("proposalId"),
                "batchId": payload.get("batchId"),
                "knowledgeItemId": payload.get("knowledgeItemId"),
                "status": payload.get("status"),
            },
        },
    )


def _find_by_id(items: list[dict[str, Any]], key: str, value: str) -> dict[str, Any] | None:
    s = _service()
    normalized = str(value or "").strip()
    for item in items:
        if isinstance(item, dict) and str(item.get(key) or "").strip() == normalized:
            return item
    return None


def _bounded_dict(payload: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    return {str(key)[:80]: value for key, value in list(payload.items())[:40]}


def _source_hash(source_ref: dict[str, Any], title: str, summary: str) -> str:
    s = _service()
    text = json.dumps({"sourceRef": source_ref, "title": title, "summary": summary}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _source_hash_with_content(source_ref: dict[str, Any], title: str, summary: str, original_content: str) -> str:
    s = _service()
    payload = {
        "sourceRef": source_ref,
        "title": title,
        "summary": summary,
        "originalContent": original_content,
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _find_central_source_by_hash_locked(source_hash: str) -> dict[str, Any]:
    s = _service()
    normalized_hash = str(source_hash or "").strip()
    if not normalized_hash:
        return {}
    for source in s._read_jsonl(s._central_source_registry_path()):
        if str(source.get("sourceHash") or "").strip() == normalized_hash:
            return source
    return {}


def _find_central_source_by_id_locked(central_source_id: str) -> dict[str, Any]:
    s = _service()
    normalized_id = str(central_source_id or "").strip()
    if not normalized_id:
        return {}
    for source in s._read_jsonl(s._central_source_registry_path()):
        if str(source.get("centralSourceId") or "").strip() == normalized_id:
            return source
    return {}


def _rewrite_owner_source_review_queue_locked(owner_value: Any, sources: list[dict[str, Any]]) -> None:
    s = _service()
    pending_sources = [
        source
        for source in sources
        if str(source.get("status") or "") in {"pending", "needs_more_context"}
    ]
    s._write_jsonl(s._owner_source_review_queue_path(owner_value), pending_sources)


def _source_inbox_summary(sources: list[dict[str, Any]]) -> dict[str, Any]:
    s = _service()
    status_counts = {status: 0 for status in sorted(s.SOURCE_INBOX_STATUSES)}
    for source in sources:
        status = str(source.get("status") or "")
        if status in status_counts:
            status_counts[status] += 1
    return {
        "sourceCount": len(sources),
        "pendingSourceCount": status_counts.get("pending", 0),
        "acceptedSourceCount": status_counts.get("accepted", 0),
        "rejectedSourceCount": status_counts.get("rejected", 0),
        "duplicateSourceCount": status_counts.get("duplicate", 0),
        "needsMoreContextSourceCount": status_counts.get("needs_more_context", 0),
        "statusCounts": status_counts,
    }


def _extended_fs_path(path: Path) -> Path:
    """Return a Windows extended-length path for filesystem-only copy/write."""

    resolved = Path(path).resolve()
    if os.name != "nt":
        return resolved
    value = str(resolved)
    if value.startswith("\\\\?\\"):
        return resolved
    if value.startswith("\\\\"):
        return Path(f"\\\\?\\UNC\\{value[2:]}")
    return Path(f"\\\\?\\{value}")


def _safe_source_filename(value: Any, *, default: str) -> str:
    s = _service()
    raw = Path(str(value or "")).name.strip()
    if not raw:
        raw = default
    safe = s._SAFE_ID_FRAGMENT.sub("-", raw).strip(".-_")
    if not safe:
        safe = default
    if "." not in safe and "." in default:
        safe = f"{safe}{Path(default).suffix}"
    return safe[:180]


def _project_relative_path(path: Path) -> str:
    s = _service()
    resolved = path.resolve()
    workspace_root = s._route_team_knowledge_workspace_path(seed=True).resolve()
    try:
        return f"workspace/{resolved.relative_to(workspace_root).as_posix()}"
    except (OSError, ValueError):
        pass
    try:
        return resolved.relative_to(s._project_root().resolve()).as_posix()
    except (OSError, ValueError):
        return str(path)


def _project_path_from_relative(value: str) -> Path:
    s = _service()
    text = str(value or "").strip()
    if not text:
        return Path()
    candidate = Path(text)
    if candidate.parts and candidate.parts[0].lower() == "workspace":
        return s._route_team_knowledge_workspace_path(*candidate.parts[1:], seed=True)
    if not candidate.is_absolute():
        candidate = s._project_root() / candidate
    workspace_root = s._route_team_knowledge_workspace_path(seed=True).resolve()
    try:
        candidate.resolve().relative_to(workspace_root)
        return candidate
    except (OSError, ValueError):
        pass
    try:
        candidate.resolve().relative_to(s._project_root().resolve())
    except (OSError, ValueError):
        return Path()
    return candidate


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    s = _service()
    if not path.exists():
        return []
    items: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                items.append(payload)
    except (OSError, json.JSONDecodeError):
        return []
    return items


def _write_jsonl(path: Path, items: list[dict[str, Any]]) -> None:
    s = _service()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in items if isinstance(item, dict))
    path.write_text(text, encoding="utf-8")


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    s = _service()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    s = _service()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _owner_context(
    owner_type: str,
    owner_id: str,
    *,
    team: dict[str, Any] | None = None,
    agent: dict[str, Any] | None = None,
) -> dict[str, Any]:
    s = _service()
    normalized_type = s._normalize_owner_type(owner_type) or "team"
    normalized_id = str(owner_id or "").strip()
    payload: dict[str, Any] = {
        "ownerType": normalized_type,
        "ownerId": normalized_id,
        "team": team if isinstance(team, dict) else {},
        "agent": agent if isinstance(agent, dict) else {},
    }
    if normalized_type == "team" and not payload["team"] and normalized_id:
        try:
            payload["team"] = s.team_service.get_team(normalized_id)
        except Exception:
            payload["team"] = {"teamId": normalized_id, "name": ""}
    if normalized_type == "agent" and not payload["agent"] and normalized_id:
        try:
            payload["agent"] = s.agent_directory_service.get_agent(normalized_id) or {"agentId": normalized_id}
        except Exception:
            payload["agent"] = {"agentId": normalized_id}
    return payload


def _coerce_owner_context(value: Any) -> dict[str, Any]:
    s = _service()
    if isinstance(value, dict) and str(value.get("ownerType") or "").strip() in s.KNOWLEDGE_OWNER_TYPES:
        raw_type = str(value.get("ownerType") or "")
        return s._owner_context(
            raw_type,
            str(value.get("ownerId") or value.get("teamId") or value.get("agentId") or ""),
            team=value.get("team") if isinstance(value.get("team"), dict) else (value if raw_type == "team" else None),
            agent=value.get("agent") if isinstance(value.get("agent"), dict) else (value if raw_type == "agent" else None),
        )
    if isinstance(value, dict) and str(value.get("teamId") or "").strip():
        return s._owner_context("team", str(value.get("teamId") or ""), team=value)
    if isinstance(value, dict) and str(value.get("agentId") or "").strip():
        return s._owner_context("agent", str(value.get("agentId") or ""), agent=value)
    return s._owner_context("team", str(value or ""))


def _normalize_owner_type(owner_type: Any) -> str:
    s = _service()
    normalized = str(owner_type or "").strip().lower()
    if not normalized:
        return ""
    if normalized not in s.KNOWLEDGE_OWNER_TYPES:
        raise s.TeamKnowledgeError(f"Unsupported knowledge owner type: {owner_type}")
    return normalized


def _iter_knowledge_owners(
    *,
    agent_id: str = "",
    include_archived: bool = True,
    include_all_agents: bool = False,
) -> list[dict[str, Any]]:
    s = _service()
    owners: list[dict[str, Any]] = []
    normalized_agent_id = str(agent_id or "").strip()
    if normalized_agent_id:
        agent = s.agent_directory_service.get_agent(normalized_agent_id, include_archived=include_archived)
        if agent:
            owners.append(s._owner_context("agent", normalized_agent_id, agent=agent))
    elif include_all_agents:
        for agent in s.agent_directory_service.list_agents(include_archived=include_archived):
            agent_id_value = str(agent.get("agentId") or "").strip()
            if agent_id_value:
                owners.append(s._owner_context("agent", agent_id_value, agent=agent))
    for team in s.team_service.list_teams_compact(include_archived=include_archived).get("teams") or []:
        team_id = str(team.get("teamId") or "").strip()
        if team_id:
            owners.append(s._owner_context("team", team_id, team=team))
    return owners


def _knowledge_root(team_id: str) -> Path:
    s = _service()
    return s._route_team_knowledge_workspace_path(
        "teams",
        s._safe_token(team_id, default="team", max_length=96),
        "knowledge",
    )


def _knowledge_root_for_owner(owner_value: Any) -> Path:
    s = _service()
    owner = s._coerce_owner_context(owner_value)
    owner_type = str(owner.get("ownerType") or "team")
    owner_id = str(owner.get("ownerId") or "").strip()
    if owner_type == "agent":
        return s._route_team_knowledge_workspace_path(
            "agents",
            s._safe_token(owner_id, default="agent", max_length=128),
            "knowledge",
        )
    return s._knowledge_root(owner_id)


def _knowledge_bases_path_for_owner(owner_value: Any) -> Path:
    s = _service()
    return s._knowledge_root_for_owner(owner_value) / "knowledge_bases.json"


def _knowledge_bases_path(team_id: str) -> Path:
    s = _service()
    return s._knowledge_root(team_id) / "knowledge_bases.json"


def _source_artifacts_path_for_owner(owner_value: Any) -> Path:
    s = _service()
    return s._knowledge_root_for_owner(owner_value) / "source_artifacts.jsonl"


def _source_artifacts_path(team_id: str) -> Path:
    s = _service()
    return s._knowledge_root(team_id) / "source_artifacts.jsonl"


def _owner_source_governance_path(owner_value: Any) -> Path:
    s = _service()
    return s._knowledge_root_for_owner(owner_value) / "source_governance.json"


def _owner_inbox_root_for_owner(owner_value: Any) -> Path:
    s = _service()
    return s._knowledge_root_for_owner(owner_value) / "inbox"


def _owner_inbox_source_dir(owner_value: Any, inbox_source_id: str) -> Path:
    s = _service()
    safe_id = s._safe_token(inbox_source_id, default="source", max_length=128)
    return s._owner_inbox_root_for_owner(owner_value) / "sources" / safe_id


def _owner_source_index_path(owner_value: Any) -> Path:
    s = _service()
    return s._owner_inbox_root_for_owner(owner_value) / "source_index.jsonl"


def _owner_source_review_queue_path(owner_value: Any) -> Path:
    s = _service()
    return s._owner_inbox_root_for_owner(owner_value) / "review_queue.jsonl"


def _owner_source_rejected_path(owner_value: Any) -> Path:
    s = _service()
    return s._owner_inbox_root_for_owner(owner_value) / "rejected.jsonl"


def _proposals_path_for_owner(owner_value: Any) -> Path:
    s = _service()
    return s._knowledge_root_for_owner(owner_value) / "refinement_proposals.jsonl"


def _proposals_path(team_id: str) -> Path:
    s = _service()
    return s._knowledge_root(team_id) / "refinement_proposals.jsonl"


def _batches_path_for_owner(owner_value: Any) -> Path:
    s = _service()
    return s._knowledge_root_for_owner(owner_value) / "batches.jsonl"


def _batches_path(team_id: str) -> Path:
    s = _service()
    return s._knowledge_root(team_id) / "batches.jsonl"


def _items_path_for_owner(owner_value: Any) -> Path:
    s = _service()
    return s._knowledge_root_for_owner(owner_value) / "items.jsonl"


def _items_path(team_id: str) -> Path:
    s = _service()
    return s._knowledge_root(team_id) / "items.jsonl"


def _audit_path_for_owner(owner_value: Any) -> Path:
    s = _service()
    return s._knowledge_root_for_owner(owner_value) / "audit.jsonl"


def _audit_path(team_id: str) -> Path:
    s = _service()
    return s._knowledge_root(team_id) / "audit.jsonl"


def _rating_suggestions_path_for_owner(owner_value: Any) -> Path:
    s = _service()
    return s._knowledge_root_for_owner(owner_value) / "rating_suggestions.jsonl"


def _rating_suggestions_path(team_id: str) -> Path:
    s = _service()
    return s._knowledge_root(team_id) / "rating_suggestions.jsonl"


def _developer_sandbox_module():
    s = _service()
    from core.infrastructure import developer_sandbox

    return developer_sandbox


def _route_team_knowledge_workspace_path(*parts: str, intent: str = "state", seed: bool = True) -> Path:
    s = _service()
    return s._developer_sandbox_module().route_workspace_path(
        s._project_root(),
        "team_knowledge",
        *parts,
        intent=intent,
        seed=seed,
    )


def _assert_central_source_write_allowed() -> None:
    s = _service()
    s._route_team_knowledge_workspace_path("knowledge", "sources", intent="central_promotion", seed=False)


def _central_knowledge_root() -> Path:
    s = _service()
    return s._route_team_knowledge_workspace_path("knowledge", intent="state", seed=True)


def _central_sources_root() -> Path:
    s = _service()
    return s._central_knowledge_root() / "sources"


def _central_source_accepted_dir() -> Path:
    s = _service()
    return s._central_sources_root() / "accepted"


def _central_source_registry_root() -> Path:
    s = _service()
    return s._central_sources_root() / "registry"


def _central_source_registry_path() -> Path:
    s = _service()
    return s._central_source_registry_root() / "source_registry.jsonl"


def _central_owner_refs_path() -> Path:
    s = _service()
    return s._central_source_registry_root() / "owner_refs.jsonl"


def _central_promotion_log_path() -> Path:
    s = _service()
    return s._central_source_registry_root() / "promotion_log.jsonl"


def _project_root() -> Path:
    s = _service()
    root = Path(s.PROJECT_ROOT).resolve()
    return root.parent if root.name.lower() == "workspace" else root


def _sync_roots() -> None:
    s = _service()
    if s.team_service.PROJECT_ROOT != s.PROJECT_ROOT:
        s.team_service.PROJECT_ROOT = s.PROJECT_ROOT
    if s.chat_room_service.PROJECT_ROOT != s.PROJECT_ROOT:
        s.chat_room_service.PROJECT_ROOT = s.PROJECT_ROOT
    if s.agent_directory_service.PROJECT_ROOT != s.PROJECT_ROOT:
        s.agent_directory_service.PROJECT_ROOT = s.PROJECT_ROOT


def _safe_token(value: Any, *, default: str, max_length: int) -> str:
    s = _service()
    text = str(value or "").strip()
    if not text:
        return default
    text = s._SAFE_ID_FRAGMENT.sub("-", text).strip(".-_")
    return (text or default)[:max_length]


def _owner_scoped_knowledge_base_id(owner_value: Any, knowledge_base_id: str) -> str:
    s = _service()
    owner = s._coerce_owner_context(owner_value)
    owner_type = s._safe_token(owner.get("ownerType"), default="", max_length=32)
    owner_id = s._safe_token(owner.get("ownerId"), default="", max_length=128)
    base_id = s._safe_token(knowledge_base_id, default="", max_length=128)
    if owner_type and owner_id and base_id:
        return f"{owner_type}:{owner_id}:{base_id}"
    return base_id


def _parse_owner_scoped_knowledge_base_id(value: Any) -> tuple[str, str, str]:
    s = _service()
    normalized = str(value or "").strip()
    parts = normalized.split(":", 2)
    if len(parts) == 3 and parts[0].strip() in s.KNOWLEDGE_OWNER_TYPES and parts[1].strip() and parts[2].strip():
        owner_type = s._safe_token(parts[0], default="", max_length=32)
        owner_id = s._safe_token(parts[1], default="", max_length=128)
        base_id = s._safe_token(parts[2], default="", max_length=128)
        return owner_type, owner_id, base_id
    return "", "", s._safe_token(normalized, default="", max_length=128)


def _new_id(prefix: str, existing_ids: set[str], name: str) -> str:
    s = _service()
    base = f"{prefix}-{s._safe_token(name, default=prefix, max_length=42).lower()}"
    candidate = base
    index = 2
    while candidate in existing_ids:
        candidate = f"{base}-{index}"
        index += 1
    return candidate


def _new_event_id(prefix: str) -> str:
    s = _service()
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _unique_strings(values: Any) -> list[str]:
    s = _service()
    raw = [values] if isinstance(values, str) else list(values or [])
    result: list[str] = []
    for item in raw:
        text = trim_lines(str(item or ""), max_lines=1).strip()
        if text and text not in result:
            result.append(text)
    return result
