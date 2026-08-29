"""Stable lightweight NPC profiles; NPCs never become Agents."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from .causal_contracts import CAUSAL_SCHEMA_VERSION


def _iso(value: datetime) -> str:
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return normalized.astimezone(timezone.utc).isoformat()


def upsert_npc(
    catalog: dict[str, Any],
    *,
    npc_id: str,
    display_name: str,
    role: str,
    traits: list[str],
    source_kind: str,
    source_ref: str,
    now: datetime,
) -> dict[str, Any]:
    result = deepcopy(catalog) if isinstance(catalog, dict) else {}
    result["schemaVersion"] = CAUSAL_SCHEMA_VERSION
    result["npcs"] = [item for item in list(result.get("npcs") or []) if isinstance(item, dict)]
    normalized_id = str(npc_id or "").strip()[:160]
    name = str(display_name or "").strip()[:160]
    kind = str(source_kind or "").strip()[:40]
    ref = str(source_ref or "").strip()[:240]
    if not normalized_id or not name or not ref:
        raise ValueError("NPC profile requires id, display name, and source reference.")
    if kind not in {"lived_event", "relationship_event", "operator"}:
        raise ValueError("NPC source kind is not allowed.")
    npc = next(
        (item for item in result["npcs"] if str(item.get("npcId") or "") == normalized_id),
        None,
    )
    if npc is None:
        npc = {
            "npcId": normalized_id,
            "kind": "npc",
            "displayName": name,
            "role": str(role or "").strip()[:200],
            "traits": [],
            "sourceRefs": [],
            "createdAt": _iso(now),
        }
        result["npcs"].append(npc)
    npc["displayName"] = name
    npc["role"] = str(role or npc.get("role") or "").strip()[:200]
    merged_traits = [str(item).strip()[:80] for item in list(npc.get("traits") or []) if str(item).strip()]
    for trait in traits:
        normalized = str(trait or "").strip()[:80]
        if normalized and normalized not in merged_traits:
            merged_traits.append(normalized)
    npc["traits"] = merged_traits[:16]
    refs = [str(item).strip()[:240] for item in list(npc.get("sourceRefs") or []) if str(item).strip()]
    if ref not in refs:
        refs.append(ref)
    npc["sourceRefs"] = refs[:32]
    npc["updatedAt"] = _iso(now)
    result["updatedAt"] = _iso(now)
    return result


__all__ = ["upsert_npc"]
