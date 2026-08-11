"""Read-only import bridge from the legacy Agent registry into SQLite."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from core.web.services.agent_config_authority import canonical_agent_config_payload

from .repository import ConversationRepository


class AgentConfigImportError(ValueError):
    """The supplied legacy Agent registry cannot be imported safely."""


class LegacyAgentConfigImporter:
    """Explicit, read-only importer for one legacy ``agents.json`` snapshot.

    The caller must supply the source path. This deliberately has no default
    production path and does not establish SQLite as the live config authority.
    """

    def __init__(
        self,
        repository: ConversationRepository,
        *,
        source: str = "legacy_agents_json",
    ) -> None:
        self._repository = repository
        self._source = str(source).strip() or "legacy_agents_json"

    def import_file(
        self,
        source_path: Path,
        *,
        timeout: float = 5,
    ) -> dict[str, Any]:
        path = Path(source_path).expanduser().resolve(strict=True)
        raw_source = path.read_bytes()
        snapshots = _snapshots_from_source(raw_source, source=self._source)
        outcomes = self._repository.import_agent_config_snapshots(snapshots).result(
            timeout=timeout
        )
        return {
            "sourcePath": str(path),
            "sourceSha256": hashlib.sha256(raw_source).hexdigest(),
            "created": sum(outcome["action"] == "created" for outcome in outcomes),
            "revised": sum(outcome["action"] == "revised" for outcome in outcomes),
            "reused": sum(outcome["action"] == "reused" for outcome in outcomes),
            "agents": outcomes,
        }


def _snapshots_from_source(
    raw_source: bytes,
    *,
    source: str,
) -> list[dict[str, Any]]:
    try:
        decoded = raw_source.decode("utf-8")
        document = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AgentConfigImportError("Agent registry must be valid UTF-8 JSON.") from exc
    if not isinstance(document, Mapping):
        raise AgentConfigImportError("Agent registry root must be an object.")
    agents = document.get("agents")
    if not isinstance(agents, list):
        raise AgentConfigImportError("Agent registry requires an agents list.")

    snapshots: list[dict[str, Any]] = []
    seen_agent_ids: set[str] = set()
    for index, raw_agent in enumerate(agents):
        if not isinstance(raw_agent, Mapping):
            raise AgentConfigImportError(f"Agent at index {index} must be an object.")
        agent = dict(raw_agent)
        raw_agent_id = agent.get("agentId")
        if not isinstance(raw_agent_id, str) or not raw_agent_id.strip():
            raise AgentConfigImportError(f"Agent at index {index} requires a non-empty agentId.")
        agent_id = raw_agent_id.strip()
        if agent_id in seen_agent_ids:
            raise AgentConfigImportError(f"Agent registry contains duplicate agentId: {agent_id}")
        seen_agent_ids.add(agent_id)
        canonical_config = canonical_agent_config_payload(agent)
        snapshots.append(
            {
                "agent_id": agent_id,
                "display_name": str(agent.get("displayName") or agent_id).strip()
                or agent_id,
                "kind": str(agent.get("kind") or "assistant").strip() or "assistant",
                "status": str(canonical_config["status"]),
                "config": canonical_config,
                "source": source,
            }
        )
    return snapshots
