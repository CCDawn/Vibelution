"""Personal lossless episodic memory (P0).

Authority is the existing MemoryPolicy ``episodicEventsPath``
(``workspace/agents/{id}/events/episodic_events.jsonl``). Writes append JSONL
and never call an LLM. Derived ``summaries.jsonl`` is out of scope; this
module must not create summaries, project-memory proposals, or public
experience files.

Supersede keeps the original line and only fills ``validUntil`` /
``supersededByEpisodeId``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
EPISODE_KINDS = {"note", "preference", "session_fact", "private_note"}
REF_TYPES = {"session", "path", "card", "item"}
MAX_TEXT_LINES = 40
MAX_REFS = 16
DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 200


def _service():
    from core.web.services import agent_directory_service

    return agent_directory_service


def _normalize_kind(kind: str) -> str:
    s = _service()
    normalized = str(kind or "").strip().lower() or "note"
    if normalized not in EPISODE_KINDS:
        raise s.AgentDirectoryError(f"Unsupported episodic event kind: {kind}")
    return normalized


def _normalize_refs(refs: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    s = _service()
    normalized: list[dict[str, str]] = []
    for item in list(refs or []):
        if not isinstance(item, dict):
            raise s.AgentDirectoryError("Episode ref must be an object.")
        ref_type = str(item.get("type") or "").strip()
        ref_id = str(item.get("id") or "").strip()
        if not ref_type and not ref_id:
            continue
        if ref_type not in REF_TYPES:
            raise s.AgentDirectoryError(f"Unsupported episode ref type: {ref_type}")
        if not ref_id:
            raise s.AgentDirectoryError("Episode ref id is required.")
        normalized.append({"type": ref_type, "id": ref_id})
        if len(normalized) >= MAX_REFS:
            break
    return normalized


def _episodic_events_path(agent: dict[str, Any]) -> Path:
    s = _service()
    agent_id = str(agent.get("agentId") or "").strip()
    policy = s.resolve_memory_policy_for_agent(agent_id) if agent_id else {}
    declared = str((policy or {}).get("episodicEventsPath") or "").strip()
    if declared:
        return s._resolve_project_path(declared)
    return s._agent_workspace_event_path(agent, "episodic_events.jsonl")


def _load_agent(agent_id: str) -> dict[str, Any]:
    s = _service()
    agent = s.get_agent(agent_id, include_archived=True)
    if not agent:
        raise s.AgentNotFoundError(f"Agent not found: {agent_id}")
    return agent


def _is_current(item: dict[str, Any]) -> bool:
    return str(item.get("validUntil") or "").strip() == ""


def append_episodic_event(
    agent_id: str,
    *,
    kind: str = "note",
    text: str,
    refs: list[dict[str, Any]] | None = None,
    occurred_at: str = "",
) -> dict[str, Any]:
    """Append one private episode. Hot path: JSONL only, no LLM."""
    s = _service()
    agent = _load_agent(agent_id)
    normalized_text = s.trim_lines(str(text or ""), max_lines=MAX_TEXT_LINES)
    if not normalized_text:
        raise s.AgentDirectoryError("Episodic event text is required.")
    now = s.utc_now_iso()
    occurred = str(occurred_at or "").strip() or now
    episode_id = s._new_event_id("episode")
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "episodeId": episode_id,
        "eventId": episode_id,
        "agentId": str(agent.get("agentId") or "").strip(),
        "occurredAt": occurred,
        "kind": _normalize_kind(kind),
        "text": normalized_text,
        "refs": _normalize_refs(refs),
        "validFrom": now,
        "validUntil": "",
        "supersededByEpisodeId": "",
    }
    path = _episodic_events_path(agent)
    s._append_jsonl(path, payload)
    s._record_memory_event("episodic_event.appended", payload, agent_id=payload["agentId"])
    return payload


def supersede_episodic_event(
    agent_id: str,
    episode_id: str,
    *,
    successor_episode_id: str = "",
) -> dict[str, Any]:
    """Invalidate one episode in place. Does not delete the JSONL line."""
    s = _service()
    agent = _load_agent(agent_id)
    normalized_episode_id = str(episode_id or "").strip()
    if not normalized_episode_id:
        raise s.AgentEpisodicEventNotFoundError("Episodic event id is required.")
    path = _episodic_events_path(agent)
    events = s._read_jsonl(path)
    successor = str(successor_episode_id or "").strip()
    now = s.utc_now_iso()
    for item in events:
        if str(item.get("episodeId") or item.get("eventId") or "").strip() != normalized_episode_id:
            continue
        if _is_current(item):
            item["validUntil"] = now
            item["supersededByEpisodeId"] = successor
            s._write_jsonl(path, events)
            s._record_memory_event(
                "episodic_event.superseded",
                item,
                agent_id=str(agent.get("agentId") or ""),
                lifecycle=True,
            )
        return item
    raise s.AgentEpisodicEventNotFoundError(f"Episodic event not found: {episode_id}")


def list_current_episodic_events(agent_id: str, *, limit: int = DEFAULT_LIST_LIMIT) -> list[dict[str, Any]]:
    """Newest-first current episodes (``validUntil`` empty). No vector search."""
    s = _service()
    agent = _load_agent(agent_id)
    bounded = max(1, min(MAX_LIST_LIMIT, int(limit or DEFAULT_LIST_LIMIT)))
    current = [item for item in s._read_jsonl(_episodic_events_path(agent)) if _is_current(item)]
    current.sort(
        key=lambda item: (
            str(item.get("occurredAt") or ""),
            str(item.get("validFrom") or ""),
            str(item.get("episodeId") or ""),
        ),
        reverse=True,
    )
    return current[:bounded]
