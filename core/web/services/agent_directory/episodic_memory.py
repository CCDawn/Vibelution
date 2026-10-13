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

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from core.infrastructure.atomic_io import atomic_write_text
from core.infrastructure.file_lock import cross_process_file_lock

SCHEMA_VERSION = 1
EPISODE_KINDS = {"note", "preference", "session_fact", "private_note"}
REF_TYPES = {"session", "path", "card", "item"}
MAX_TEXT_LINES = 40
MAX_REFS = 16
DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 200
PROMPT_LIST_LIMIT = 8
PROMPT_TEXT_LINES = 8


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


def _require_memory_policy_enabled(agent: dict[str, Any]) -> None:
    """Write-side gate for the per-agent memory switch (memoryPolicy.enabled).

    Service-level on purpose: both the personal-memory tools and any direct
    service caller go through here. Disabling stops writes only; existing
    episodes are never deleted or migrated.
    """
    s = _service()
    agent_id = str(agent.get("agentId") or "").strip()
    if not agent_id:
        return
    policy = s.resolve_memory_policy_for_agent(agent_id)
    if not bool(policy.get("enabled", True)):
        raise s.AgentDirectoryError(
            f"Personal memory is disabled for agent {agent_id} (memoryPolicy.enabled=false); "
            "episodic memory writes are blocked."
        )


def _is_current(item: dict[str, Any]) -> bool:
    return str(item.get("validUntil") or "").strip() == ""


def _read_jsonl_for_transaction(path: Path) -> list[dict[str, Any]]:
    """Fail closed before a rewrite if the authoritative JSONL cannot be read."""
    s = _service()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise s.AgentDirectoryError(
                f"Episodic event store has invalid JSON on line {line_number}; mutation was not applied."
            ) from exc
        if not isinstance(payload, dict):
            raise s.AgentDirectoryError(
                f"Episodic event store has a non-object record on line {line_number}; mutation was not applied."
            )
        events.append(payload)
    return events


def _new_episode_payload(
    agent: dict[str, Any],
    *,
    kind: str,
    text: str,
    refs: list[dict[str, Any]] | None,
    occurred_at: str,
) -> dict[str, Any]:
    s = _service()
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
    return payload


class EpisodicMemoryTransaction:
    """In-memory edits held under the episode file lock until atomic commit."""

    def __init__(self, agent: dict[str, Any], path: Path, events: list[dict[str, Any]]) -> None:
        self.agent = agent
        self.path = path
        self.events = events
        self._dirty = False
        self._appended: list[dict[str, Any]] = []
        self._superseded: list[dict[str, Any]] = []

    def append(
        self,
        *,
        kind: str = "note",
        text: str,
        refs: list[dict[str, Any]] | None = None,
        occurred_at: str = "",
    ) -> dict[str, Any]:
        payload = _new_episode_payload(
            self.agent,
            kind=kind,
            text=text,
            refs=refs,
            occurred_at=occurred_at,
        )
        self.events.append(payload)
        self._appended.append(payload)
        self._dirty = True
        return payload

    def supersede(
        self,
        episode_id: str,
        *,
        successor_episode_id: str = "",
    ) -> dict[str, Any]:
        s = _service()
        normalized_episode_id = str(episode_id or "").strip()
        if not normalized_episode_id:
            raise s.AgentEpisodicEventNotFoundError("Episodic event id is required.")
        successor = str(successor_episode_id or "").strip()
        for item in self.events:
            if str(item.get("episodeId") or item.get("eventId") or "").strip() != normalized_episode_id:
                continue
            if _is_current(item):
                item["validUntil"] = s.utc_now_iso()
                item["supersededByEpisodeId"] = successor
                self._superseded.append(item)
                self._dirty = True
            return item
        raise s.AgentEpisodicEventNotFoundError(f"Episodic event not found: {episode_id}")

    def commit(self) -> None:
        if not self._dirty:
            return
        serialized = "".join(
            json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n"
            for item in self.events
            if isinstance(item, dict)
        )
        atomic_write_text(self.path, serialized, strict_replace=True)
        s = _service()
        s.record_agent_api_hydration_event_file_changed(self.path)
        agent_id = str(self.agent.get("agentId") or "")
        for item in self._appended:
            s._record_memory_event("episodic_event.appended", item, agent_id=agent_id)
        for item in self._superseded:
            s._record_memory_event(
                "episodic_event.superseded",
                item,
                agent_id=agent_id,
                lifecycle=True,
            )


@contextmanager
def episodic_transaction(
    agent_id: str,
    *,
    require_enabled: bool = True,
) -> Iterator[EpisodicMemoryTransaction]:
    """Serialize episode edits across threads and processes; commit on clean exit."""
    s = _service()
    agent = _load_agent(agent_id)
    path = _episodic_events_path(agent)
    with cross_process_file_lock(path):
        if require_enabled:
            _require_memory_policy_enabled(agent)
        transaction = EpisodicMemoryTransaction(agent, path, _read_jsonl_for_transaction(path))
        yield transaction
        if require_enabled and transaction._dirty:
            _require_memory_policy_enabled(agent)
        transaction.commit()


def append_episodic_event(
    agent_id: str,
    *,
    kind: str = "note",
    text: str,
    refs: list[dict[str, Any]] | None = None,
    occurred_at: str = "",
) -> dict[str, Any]:
    """Append one private episode. Hot path: JSONL only, no LLM."""
    with episodic_transaction(agent_id) as transaction:
        return transaction.append(kind=kind, text=text, refs=refs, occurred_at=occurred_at)


def supersede_episodic_event(
    agent_id: str,
    episode_id: str,
    *,
    successor_episode_id: str = "",
) -> dict[str, Any]:
    """Invalidate one episode in place. Does not delete the JSONL line."""
    with episodic_transaction(agent_id) as transaction:
        return transaction.supersede(episode_id, successor_episode_id=successor_episode_id)


def list_episodic_events(
    agent_id: str,
    *,
    include_superseded: bool = False,
) -> list[dict[str, Any]]:
    """Read full episode history, newest-first, with no truncation."""
    s = _service()
    agent = _load_agent(agent_id)
    path = _episodic_events_path(agent)
    with cross_process_file_lock(path):
        events = s._read_jsonl(path)
    if not include_superseded:
        events = [item for item in events if _is_current(item)]
    events.sort(
        key=lambda item: (
            str(item.get("occurredAt") or ""),
            str(item.get("validFrom") or ""),
            str(item.get("episodeId") or ""),
        ),
        reverse=True,
    )
    return events


def list_current_episodic_events(agent_id: str, *, limit: int = DEFAULT_LIST_LIMIT) -> list[dict[str, Any]]:
    """Newest-first current episodes (``validUntil`` empty). No vector search."""
    bounded = max(1, min(MAX_LIST_LIMIT, int(limit or DEFAULT_LIST_LIMIT)))
    return list_episodic_events(agent_id, include_superseded=False)[:bounded]
