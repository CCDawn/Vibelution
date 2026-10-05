"""Agent-private state store for scheduled perception control and cursors.

Only bounded identifiers, hashes, counters, and native Session references live
here. Prompts and results remain owned by the native Session journal.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Callable

from core.infrastructure.atomic_io import atomic_write_json


SCHEMA_VERSION = 1
STATE_FILENAME = "perception_runtime_state.json"


class AgentPerceptionStateError(RuntimeError):
    """Persisted perception state is unreadable or belongs to another Agent."""


def new_state(agent_id: str) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "agentId": str(agent_id or "").strip(),
        "policyFingerprint": "",
        "status": "idle",
        "nextRunAt": "",
        "topicCursor": 0,
        "dailyRuns": {},
        "activeRun": None,
        "lastRun": None,
        "notifications": [],
        "suppressedNotificationCount": 0,
        "knowledgeCursors": {},
        "pendingKnowledgeCandidates": [],
        "knowledgeScan": {"basesScanned": 0, "pendingCount": 0},
        "lastActivity": None,
        "updatedAt": "",
    }


class AgentPerceptionStore:
    """Small atomic JSON snapshots under each Agent's private workspace."""

    def __init__(self, *, path_resolver: Callable[[dict[str, Any]], str | Path] | None = None) -> None:
        self._path_resolver = path_resolver
        self._locks_guard = threading.Lock()
        self._locks: dict[str, threading.RLock] = {}

    def path_for(self, agent: dict[str, Any]) -> Path:
        agent_id = str(agent.get("agentId") or "").strip()
        if not agent_id:
            raise AgentPerceptionStateError("Agent identity is required for perception state.")
        if self._path_resolver is not None:
            return Path(self._path_resolver(dict(agent))).resolve()
        from core.web.services import agent_directory_service as directory

        territory = directory._agent_workspace_territory(agent)
        private_agent = {**agent, "workspacePath": str(territory.get("privateRoot") or "")}
        return Path(directory._agent_workspace_event_path(private_agent, STATE_FILENAME)).resolve()

    def load(self, agent: dict[str, Any]) -> dict[str, Any]:
        path = self.path_for(agent)
        lock = self._lock_for(path)
        with lock:
            return self._load_unlocked(path, str(agent.get("agentId") or "").strip())

    def save(self, agent: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        path = self.path_for(agent)
        lock = self._lock_for(path)
        with lock:
            normalized = _normalize_state(payload, str(agent.get("agentId") or "").strip())
            atomic_write_json(path, normalized, strict_replace=True)
            return json.loads(json.dumps(normalized, ensure_ascii=False))

    def update(
        self,
        agent: dict[str, Any],
        mutator: Callable[[dict[str, Any]], Any],
    ) -> tuple[dict[str, Any], Any]:
        path = self.path_for(agent)
        agent_id = str(agent.get("agentId") or "").strip()
        lock = self._lock_for(path)
        with lock:
            state = self._load_unlocked(path, agent_id)
            result = mutator(state)
            normalized = _normalize_state(state, agent_id)
            atomic_write_json(path, normalized, strict_replace=True)
            return json.loads(json.dumps(normalized, ensure_ascii=False)), result

    def _load_unlocked(self, path: Path, agent_id: str) -> dict[str, Any]:
        if not path.exists():
            return new_state(agent_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            # Never reset a corrupt daily ledger: doing so could restore spent quota.
            raise AgentPerceptionStateError("Perception state could not be read safely.") from exc
        return _normalize_state(payload, agent_id)

    def _lock_for(self, path: Path) -> threading.RLock:
        key = str(path)
        with self._locks_guard:
            return self._locks.setdefault(key, threading.RLock())


def _normalize_state(payload: Any, agent_id: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise AgentPerceptionStateError("Perception state must be an object.")
    try:
        schema_version = int(payload.get("schemaVersion") or 0)
    except (TypeError, ValueError) as exc:
        raise AgentPerceptionStateError("Perception state version is invalid.") from exc
    if schema_version != SCHEMA_VERSION:
        raise AgentPerceptionStateError("Perception state version is unsupported.")
    if str(payload.get("agentId") or "").strip() != agent_id:
        raise AgentPerceptionStateError("Perception state Agent identity does not match.")
    state = new_state(agent_id)
    for key in state:
        if key in payload:
            state[key] = payload[key]
    if not isinstance(state.get("dailyRuns"), dict):
        raise AgentPerceptionStateError("Perception daily quota ledger is invalid.")
    if not isinstance(state.get("knowledgeCursors"), dict):
        raise AgentPerceptionStateError("Perception knowledge cursor is invalid.")
    if not isinstance(state.get("notifications"), list):
        raise AgentPerceptionStateError("Perception notifications are invalid.")
    if not isinstance(state.get("pendingKnowledgeCandidates"), list):
        raise AgentPerceptionStateError("Perception knowledge candidates are invalid.")
    if state.get("lastActivity") is not None and not isinstance(state.get("lastActivity"), dict):
        raise AgentPerceptionStateError("Perception last activity is invalid.")
    if state.get("activeRun") is not None and not isinstance(state.get("activeRun"), dict):
        raise AgentPerceptionStateError("Perception active run reference is invalid.")
    if state.get("lastRun") is not None and not isinstance(state.get("lastRun"), dict):
        raise AgentPerceptionStateError("Perception last run reference is invalid.")
    try:
        state["topicCursor"] = max(0, int(state.get("topicCursor") or 0))
        state["suppressedNotificationCount"] = max(0, int(state.get("suppressedNotificationCount") or 0))
        for day, count in list(state["dailyRuns"].items()):
            if not isinstance(day, str) or not day or isinstance(count, bool) or int(count) < 0:
                raise ValueError
            state["dailyRuns"][day] = int(count)
    except (TypeError, ValueError) as exc:
        raise AgentPerceptionStateError("Perception counters are invalid.") from exc
    return state


__all__ = [
    "AgentPerceptionStateError",
    "AgentPerceptionStore",
    "SCHEMA_VERSION",
    "STATE_FILENAME",
    "new_state",
]
