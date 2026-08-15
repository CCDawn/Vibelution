"""Public structure curation catalog (P0 slice).

Claim scope: ``workspace/knowledge/public`` structure cards, hash freshness,
mixed-read locator allowlist, startup structure budget/dedup, archive/conflict
queues, and proposals. Late-binds ``team_knowledge_service`` for PROJECT_ROOT,
locks, store helpers, errors, and steward permissions.

The public layer is a third read-only search source: catalog hits are
discovery metadata only (``resultType=public_catalog_card``), never
knowledge-item bodies. Opening a card source must go through
``resolve_public_locator``; out-of-scope or escaping locators fail with
``sourceUnavailable: forbidden`` and never fall back to the card summary.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from core.chat.chat_task_types import trim_lines

PUBLIC_STRUCTURE_SCHEMA_VERSION = 2

# A.5 hard budget
STARTUP_STRUCTURE_MAX_CARDS = 24
STARTUP_STRUCTURE_MAX_CHARS = 4000
STARTUP_CARD_WHEN_TO_USE_CHARS = 80
STARTUP_CARD_SUMMARY_CHARS = 0

DEFAULT_PARTITION_QUOTAS = {
    "standards": 6,
    "skills": 6,
    "code_refs": 4,
    "agents": 4,
    "progress": 2,
    "experience": 4,
}
PUBLIC_PARTITIONS = list(DEFAULT_PARTITION_QUOTAS.keys())
PUBLIC_CARD_KINDS = {"partition", "pin", "projection", "experience"}
PUBLIC_VISIBILITIES = {"agent_visible", "hidden", "archived"}
PUBLIC_FRESHNESS_POLICIES = {"auto_project", "steward_review"}
PUBLIC_FRESHNESS_STATUSES = {"current", "stale", "missing"}
PUBLIC_SOURCE_TYPES = {"git_path", "skill", "agent_directory", "progress_index", "central_source", "experience"}
PUBLIC_QUEUE_KINDS = {"freshness", "conflict", "proposal"}
PUBLIC_QUEUE_STATUSES = {"open", "resolved", "dismissed"}
PUBLIC_QUEUE_REASONS = {"stale", "missing", "review_after", "duplicate_locator", "contradicts", "steward_flag"}
PUBLIC_QUEUE_RESOLUTIONS = {"confirm", "rewrite", "archive", "keep_a", "keep_b", "merge", "dismiss"}
PUBLIC_MAX_EXPERIENCE_BYTES = 8 * 1024
PUBLIC_MAX_SUMMARY_CHARS = 240
PUBLIC_MAX_WHEN_TO_USE_CHARS = 240

_PROMPT_MANAGER_EXCLUDED_LOCATORS = {
    "agents.md",
    "core/core_prompt/common.md",
    "core/core_prompt/soul.md",
}
_PROMPT_MANAGER_EXCLUDED_PREFIXES = ("core/core_prompt/",)


class PublicCatalogError(ValueError):
    """Raised when a public catalog request is invalid."""


class PublicCatalogPermissionError(PublicCatalogError):
    """Raised when an actor is not allowed to mutate the public structure."""


class PublicCatalogNotFoundError(PublicCatalogError):
    """Raised when a public catalog resource does not exist."""


class PublicCatalogSourceUnavailableError(PublicCatalogError):
    """Raised when a card source cannot be opened through the allowlist."""

    def __init__(self, reason: str, message: str = "", *, card_id: str = "", locator: str = "") -> None:
        self.reason = str(reason or "").strip()
        self.card_id = str(card_id or "").strip()
        self.locator = str(locator or "").strip()
        super().__init__(message or f"public source unavailable: {self.reason}")


class PublicCatalogConflictError(PublicCatalogError):
    """Raised when a card participates in an open conflict queue event."""


def _service():
    from core.web.services import team_knowledge_service

    return team_knowledge_service


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _public_root() -> Path:
    s = _service()
    return s._central_knowledge_root() / "public"


def _structure_path() -> Path:
    return _public_root() / "structure.json"


def _structure_archive_path() -> Path:
    return _public_root() / "structure.archive.json"


def _queues_path() -> Path:
    return _public_root() / "steward_queues.jsonl"


def _proposals_path() -> Path:
    return _public_root() / "proposals.jsonl"


def _experience_dir() -> Path:
    return _public_root() / "experience"


def _experience_path(card_id: str) -> Path:
    return _experience_dir() / f"{card_id}.md"


def _project_root() -> Path:
    s = _service()
    return s._project_root()


def _read_structure() -> dict[str, Any]:
    path = _structure_path()
    if not path.exists():
        return _default_structure()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default_structure()
    if not isinstance(payload, dict):
        return _default_structure()
    return _normalize_structure(payload)


def _default_structure() -> dict[str, Any]:
    return {
        "schemaVersion": PUBLIC_STRUCTURE_SCHEMA_VERSION,
        "updatedAt": "",
        "budget": {
            "maxCards": STARTUP_STRUCTURE_MAX_CARDS,
            "maxChars": STARTUP_STRUCTURE_MAX_CHARS,
            "partitionQuotas": dict(DEFAULT_PARTITION_QUOTAS),
        },
        "partitions": list(PUBLIC_PARTITIONS),
        "cards": [],
        "edges": [],
    }


def _normalize_structure(payload: dict[str, Any]) -> dict[str, Any]:
    budget = payload.get("budget") if isinstance(payload.get("budget"), dict) else {}
    normalized_budget = {
        "maxCards": _bounded_int(budget.get("maxCards"), default=STARTUP_STRUCTURE_MAX_CARDS, maximum=STARTUP_STRUCTURE_MAX_CARDS),
        "maxChars": _bounded_int(budget.get("maxChars"), default=STARTUP_STRUCTURE_MAX_CHARS, maximum=STARTUP_STRUCTURE_MAX_CHARS),
        "partitionQuotas": {
            str(partition): max(0, int(value or 0))
            for partition, value in (budget.get("partitionQuotas") or {}).items()
            if isinstance(budget.get("partitionQuotas"), dict) and str(partition) in PUBLIC_PARTITIONS
        },
    }
    if not normalized_budget["partitionQuotas"]:
        normalized_budget["partitionQuotas"] = dict(DEFAULT_PARTITION_QUOTAS)
    normalized_budget["partitionQuotas"] = {
        partition: int(normalized_budget["partitionQuotas"].get(partition) or 0)
        for partition in PUBLIC_PARTITIONS
    }
    cards = [_normalize_card(card) for card in list(payload.get("cards") or []) if isinstance(card, dict)]
    return {
        "schemaVersion": int(payload.get("schemaVersion") or PUBLIC_STRUCTURE_SCHEMA_VERSION),
        "updatedAt": str(payload.get("updatedAt") or ""),
        "budget": normalized_budget,
        "partitions": [str(partition) for partition in PUBLIC_PARTITIONS],
        "cards": cards,
        "edges": [edge for edge in list(payload.get("edges") or []) if isinstance(edge, dict)][:200],
    }


def _bounded_int(value: Any, *, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(maximum, parsed))


def _normalize_card(card: dict[str, Any]) -> dict[str, Any]:
    kind = str(card.get("kind") or "pin").strip()
    if kind not in PUBLIC_CARD_KINDS:
        kind = "pin"
    partition = str(card.get("partition") or "").strip()
    if partition not in PUBLIC_PARTITIONS:
        partition = ""
    visibility = str(card.get("visibility") or "agent_visible").strip()
    if visibility not in PUBLIC_VISIBILITIES:
        visibility = "agent_visible"
    freshness_policy = str(card.get("freshnessPolicy") or "steward_review").strip()
    if freshness_policy not in PUBLIC_FRESHNESS_POLICIES:
        freshness_policy = "steward_review"
    freshness = card.get("freshness") if isinstance(card.get("freshness"), dict) else {}
    freshness_status = str(freshness.get("status") or "current").strip()
    if freshness_status not in PUBLIC_FRESHNESS_STATUSES:
        freshness_status = "current"
    source = card.get("source") if isinstance(card.get("source"), dict) else {}
    source_type = str(source.get("type") or "").strip()
    if source_type not in PUBLIC_SOURCE_TYPES:
        source_type = ""
    origin_ref = card.get("originRef")
    if not isinstance(origin_ref, dict):
        origin_ref = None
    contradicts = [str(value or "").strip() for value in list(card.get("contradictsCardIds") or []) if str(value or "").strip()]
    normalized = {
        "cardId": str(card.get("cardId") or "").strip(),
        "kind": kind,
        "partition": partition,
        "title": _bounded_text(str(card.get("title") or ""), 120),
        "whenToUse": _bounded_text(str(card.get("whenToUse") or ""), PUBLIC_MAX_WHEN_TO_USE_CHARS),
        "summary": _bounded_text(str(card.get("summary") or ""), PUBLIC_MAX_SUMMARY_CHARS),
        "stewardWeight": _safe_int(card.get("stewardWeight")),
        "visibility": visibility,
        "source": {
            "type": source_type,
            "locator": str(source.get("locator") or "").strip(),
            "contentHash": str(source.get("contentHash") or "").strip(),
        },
        "originRef": origin_ref,
        "freshnessPolicy": freshness_policy,
        "freshness": {
            "status": freshness_status,
            "observedHash": str(freshness.get("observedHash") or "").strip(),
            "lastCheckedAt": str(freshness.get("lastCheckedAt") or "").strip(),
            "lastRefreshedAt": str(freshness.get("lastRefreshedAt") or "").strip(),
        },
        "reviewAfter": str(card.get("reviewAfter") or "").strip(),
        "contradictsCardIds": contradicts,
        "archivedAt": str(card.get("archivedAt") or "").strip(),
        "archivedReason": str(card.get("archivedReason") or "").strip(),
        "previousHash": str(card.get("previousHash") or "").strip(),
        "createdAt": str(card.get("createdAt") or "").strip(),
        "updatedAt": str(card.get("updatedAt") or "").strip(),
    }
    return {key: value for key, value in normalized.items() if value or key in {"stewardWeight", "originRef"}}


def _bounded_text(value: str, maximum: int) -> str:
    text = trim_lines(str(value or ""), max_lines=6).strip()
    if len(text) <= maximum:
        return text
    return text[: maximum - 3].rstrip() + "..."


def _safe_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


def _write_structure(structure: dict[str, Any]) -> None:
    s = _service()
    structure["schemaVersion"] = PUBLIC_STRUCTURE_SCHEMA_VERSION
    structure["updatedAt"] = utc_now_iso()
    s._write_json(_structure_path(), structure)


def _read_queues() -> list[dict[str, Any]]:
    s = _service()
    return s._read_jsonl(_queues_path())


def _append_queue_event(event: dict[str, Any]) -> None:
    s = _service()
    payload = {
        "queueEventId": str(event.get("queueEventId") or s._new_event_id("cqevt")),
        "queueKind": str(event.get("queueKind") or "freshness").strip(),
        "partition": str(event.get("partition") or "").strip(),
        "cardIds": [str(value or "").strip() for value in list(event.get("cardIds") or []) if str(value or "").strip()],
        "status": str(event.get("status") or "open").strip(),
        "reason": str(event.get("reason") or "").strip(),
        "dedupKey": str(event.get("dedupKey") or "").strip(),
        "openedAt": str(event.get("openedAt") or utc_now_iso()),
        "resolvedAt": str(event.get("resolvedAt") or "").strip(),
        "resolution": str(event.get("resolution") or "").strip(),
        "notes": str(event.get("notes") or "").strip(),
    }
    s._append_jsonl(_queues_path(), payload)


def _open_queue_events(queues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [event for event in queues if str(event.get("status") or "").strip() == "open"]


def _open_queue_event_card_ids(queues: list[dict[str, Any]]) -> set[str]:
    card_ids: set[str] = set()
    for event in _open_queue_events(queues):
        card_ids.update(str(value or "").strip() for value in list(event.get("cardIds") or []))
    return card_ids


def _open_conflict_card_ids(queues: list[dict[str, Any]]) -> set[str]:
    return {
        card_id
        for event in _open_queue_events(queues)
        if str(event.get("queueKind") or "").strip() == "conflict"
        for card_id in list(event.get("cardIds") or [])
    }


def _has_open_event(queues: list[dict[str, Any]], *, queue_kind: str, dedup_key: str) -> bool:
    normalized_key = str(dedup_key or "").strip()
    if not normalized_key:
        return False
    return any(
        str(event.get("queueKind") or "").strip() == queue_kind
        and str(event.get("dedupKey") or "").strip() == normalized_key
        and str(event.get("status") or "").strip() == "open"
        for event in queues
    )


def _read_proposals() -> list[dict[str, Any]]:
    s = _service()
    return s._read_jsonl(_proposals_path())


def _require_structure_steward(actor_agent_id: str, *, internal: bool = False) -> None:
    if internal:
        return
    s = _service()
    if not s._is_global_knowledge_steward(actor_agent_id):
        raise PublicCatalogPermissionError("Only the knowledge base steward can change the public structure.")


def _card_by_id(cards: list[dict[str, Any]], card_id: str) -> dict[str, Any] | None:
    normalized = str(card_id or "").strip()
    for card in cards:
        if str(card.get("cardId") or "").strip() == normalized:
            return card
    return None


# ---------------------------------------------------------------------------
# P1: structure read/write + steward-only partition/pin mutation
# ---------------------------------------------------------------------------


def get_public_catalog(*, agent_id: str = "", internal: bool = False, include_hidden: bool = False) -> dict[str, Any]:
    """Return the public structure. Agents see the searchable set by default."""
    _sync_roots()
    structure = _read_structure()
    queues = _read_queues()
    open_conflict_ids = _open_conflict_card_ids(queues)
    s = _service()
    is_steward = internal or s._is_global_knowledge_steward(agent_id)
    if is_steward or include_hidden:
        cards = structure["cards"]
    else:
        cards = [card for card in structure["cards"] if _card_is_searchable(card, open_conflict_ids)]
    open_events = _open_queue_events(queues)
    return {
        "schemaVersion": PUBLIC_STRUCTURE_SCHEMA_VERSION,
        "updatedAt": structure["updatedAt"] or utc_now_iso(),
        "budget": structure["budget"],
        "partitions": structure["partitions"],
        "cards": cards,
        "edges": structure["edges"],
        "summary": {
            "cardCount": len(structure["cards"]),
            "searchableCardCount": sum(1 for card in structure["cards"] if _card_is_searchable(card, open_conflict_ids)),
            "openQueueEventCount": len(open_events),
            "openConflictCardCount": len(open_conflict_ids),
        },
    }


def save_public_structure(structure: dict[str, Any], *, actor_agent_id: str = "", internal: bool = False) -> dict[str, Any]:
    """Steward-only full structure write (partitions, budget, cards)."""
    _require_structure_steward(actor_agent_id, internal=internal)
    if not isinstance(structure, dict):
        raise PublicCatalogError("Public structure payload must be an object.")
    s = _service()
    with s._LOCK:
        normalized = _normalize_structure(structure)
        if not normalized["partitions"]:
            raise PublicCatalogError("Public structure requires partitions.")
        for card in normalized["cards"]:
            if not card["cardId"]:
                raise PublicCatalogError("Public structure cards require a cardId.")
        _write_structure(normalized)
        _append_public_audit("structure.saved", {"cardCount": len(normalized["cards"])}, actor_agent_id=actor_agent_id)
    return {
        "schemaVersion": PUBLIC_STRUCTURE_SCHEMA_VERSION,
        "updatedAt": normalized["updatedAt"],
        "cardCount": len(normalized["cards"]),
    }


def upsert_public_card(card: dict[str, Any], *, actor_agent_id: str = "", internal: bool = False) -> dict[str, Any]:
    """Steward-only card upsert for partitions, pins, projections, and experience entries."""
    _require_structure_steward(actor_agent_id, internal=internal)
    if not isinstance(card, dict):
        raise PublicCatalogError("Public card payload must be an object.")
    now = utc_now_iso()
    s = _service()
    with s._LOCK:
        structure = _read_structure()
        normalized = _normalize_card(card)
        card_id = str(normalized.get("cardId") or "").strip()
        if not card_id:
            raise PublicCatalogError("Public card requires a cardId.")
        if not normalized["partition"]:
            raise PublicCatalogError("Public card requires a partition.")
        if not normalized["source"]["type"] and normalized["kind"] != "partition":
            raise PublicCatalogError("Public card requires a source type.")
        if normalized["kind"] == "experience":
            _validate_experience_card(normalized)
        existing = _card_by_id(structure["cards"], card_id)
        previous_hash = ""
        if existing:
            previous_hash = str(existing.get("source") or {}).get("contentHash") if isinstance(existing.get("source"), dict) else ""
        normalized["createdAt"] = str(existing.get("createdAt") or now) if existing else now
        normalized["updatedAt"] = now
        if not normalized["source"]["contentHash"]:
            normalized["source"]["contentHash"] = _compute_source_hash(normalized["source"], structure, card_id=card_id) or ""
        normalized["freshness"] = {
            "status": "current",
            "observedHash": normalized["source"]["contentHash"],
            "lastCheckedAt": now,
            "lastRefreshedAt": now,
        }
        replaced = False
        for index, item in enumerate(structure["cards"]):
            if str(item.get("cardId") or "").strip() == card_id:
                structure["cards"][index] = normalized
                replaced = True
                break
        if not replaced:
            structure["cards"].append(normalized)
        _write_structure(structure)
        _append_public_audit(
            "structure.card.upserted",
            {"cardId": card_id, "kind": normalized["kind"], "previousHash": previous_hash},
            actor_agent_id=actor_agent_id,
        )
    return dict(normalized)


def _validate_experience_card(card: dict[str, Any]) -> None:
    source = card.get("source") if isinstance(card.get("source"), dict) else {}
    source_type = str(source.get("type") or "").strip()
    locator = str(source.get("locator") or "").strip()
    if source_type != "experience":
        raise PublicCatalogError("Experience cards require source.type=experience.")
    if locator != f"experience/{card['cardId']}.md":
        raise PublicCatalogError("Experience card locator must be experience/{cardId}.md.")
    path = _experience_path(card["cardId"])
    if not path.exists():
        raise PublicCatalogError("Experience card requires the public experience/{cardId}.md body to exist first.")
    body = _read_experience_body(card["cardId"])
    if body is None:
        raise PublicCatalogError("Experience card body is unreadable.")
    expected_hash = str(source.get("contentHash") or "").strip()
    if expected_hash and expected_hash != _sha256_text(body):
        raise PublicCatalogError("Experience card contentHash does not match the experience body.")


def _read_experience_body(card_id: str) -> str | None:
    try:
        raw = _experience_path(card_id).read_bytes()
    except OSError:
        return None
    if len(raw) > PUBLIC_MAX_EXPERIENCE_BYTES:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


# ---------------------------------------------------------------------------
# P5: archive (no delete API) and conflict queue
# ---------------------------------------------------------------------------


def archive_public_card(card_id: str, *, reason: str = "", actor_agent_id: str = "", internal: bool = False) -> dict[str, Any]:
    """Steward-only archive. Cards stay in structure.json; there is no delete API."""
    _require_structure_steward(actor_agent_id, internal=internal)
    normalized_id = str(card_id or "").strip()
    if not normalized_id:
        raise PublicCatalogNotFoundError("Public card id is required.")
    now = utc_now_iso()
    s = _service()
    with s._LOCK:
        structure = _read_structure()
        card = _card_by_id(structure["cards"], normalized_id)
        if not card:
            raise PublicCatalogNotFoundError("Public card not found.")
        if str(card.get("visibility") or "").strip() == "archived":
            return dict(card)
        source = card.get("source") if isinstance(card.get("source"), dict) else {}
        card["visibility"] = "archived"
        card["archivedAt"] = now
        card["archivedReason"] = _bounded_text(str(reason or "steward archive"), 240)
        card["previousHash"] = str(source.get("contentHash") or "").strip()
        card["updatedAt"] = now
        _write_structure(structure)
        _append_public_audit("structure.card.archived", {"cardId": normalized_id, "reason": card["archivedReason"]}, actor_agent_id=actor_agent_id)
    return dict(card)


def _card_is_searchable(card: dict[str, Any], open_conflict_card_ids: set[str]) -> bool:
    if str(card.get("visibility") or "").strip() != "agent_visible":
        return False
    freshness = card.get("freshness") if isinstance(card.get("freshness"), dict) else {}
    if str(freshness.get("status") or "").strip() != "current":
        return False
    card_id = str(card.get("cardId") or "").strip()
    if card_id in open_conflict_card_ids:
        return False
    return str(card.get("kind") or "").strip() in {"pin", "projection", "experience"}


# ---------------------------------------------------------------------------
# P2: tree refresh, freshness queues, hidden conversion
# ---------------------------------------------------------------------------


def refresh_public_catalog_freshness(*, actor_agent_id: str = "", internal: bool = False) -> dict[str, Any]:
    """Steward-only tree walk: recompute source hashes, mark stale/missing,
    hide affected steward_review cards, and append freshness queue events."""
    _require_structure_steward(actor_agent_id, internal=internal)
    now = utc_now_iso()
    s = _service()
    with s._LOCK:
        structure = _read_structure()
        queues = _read_queues()
        stale_card_ids: list[str] = []
        missing_card_ids: list[str] = []
        refreshed_count = 0
        for card in structure["cards"]:
            if str(card.get("kind") or "").strip() == "partition":
                continue
            observed = _compute_source_hash(card.get("source") or {}, structure, card_id=str(card.get("cardId") or ""))
            policy = str(card.get("freshnessPolicy") or "steward_review").strip()
            visibility = str(card.get("visibility") or "agent_visible").strip()
            if visibility == "archived":
                continue
            if observed is None:
                card["freshness"] = {
                    "status": "missing",
                    "observedHash": "",
                    "lastCheckedAt": now,
                    "lastRefreshedAt": now,
                }
                card["visibility"] = "hidden"
                missing_card_ids.append(str(card.get("cardId") or ""))
                _append_freshness_queue_event(queues, card, reason="missing", now=now)
                continue
            source = card.get("source") if isinstance(card.get("source"), dict) else {}
            content_hash = str(source.get("contentHash") or "").strip()
            changed = observed != content_hash
            if changed and policy == "auto_project":
                # auto projection refreshes L1 metadata; hash-only recheck keeps
                # the current summary (no LLM), marking current on success.
                source = dict(source)
                source["contentHash"] = observed
                card["source"] = source
                card["freshness"] = {
                    "status": "current",
                    "observedHash": observed,
                    "lastCheckedAt": now,
                    "lastRefreshedAt": now,
                }
                card["visibility"] = "agent_visible"
                refreshed_count += 1
                continue
            if changed:
                card["freshness"] = {
                    "status": "stale",
                    "observedHash": observed,
                    "lastCheckedAt": now,
                    "lastRefreshedAt": now,
                }
                card["visibility"] = "hidden"
                stale_card_ids.append(str(card.get("cardId") or ""))
                _append_freshness_queue_event(queues, card, reason="stale", now=now)
                continue
            card["freshness"] = {
                "status": "current",
                "observedHash": observed,
                "lastCheckedAt": now,
                "lastRefreshedAt": now,
            }
            refreshed_count += 1
        conflict_events = _detect_conflicts(structure, queues, now=now)
        _write_structure(structure)
        if stale_card_ids or missing_card_ids or conflict_events:
            _write_queues_with_events(queues)
        _append_public_audit(
            "structure.freshness.refreshed",
            {
                "staleCardCount": len(stale_card_ids),
                "missingCardCount": len(missing_card_ids),
                "conflictEventCount": len(conflict_events),
            },
            actor_agent_id=actor_agent_id,
        )
    return {
        "refreshedCardCount": refreshed_count,
        "staleCardIds": stale_card_ids,
        "missingCardIds": missing_card_ids,
        "conflictEventCount": len(conflict_events) if conflict_events else 0,
        "openFreshnessEventCount": sum(
            1
            for event in _open_queue_events(_read_queues())
            if str(event.get("queueKind") or "").strip() == "freshness"
        ),
    }


def _write_queues_with_events(queues: list[dict[str, Any]]) -> None:
    text = "".join(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n" for event in queues if isinstance(event, dict))
    _queues_path().parent.mkdir(parents=True, exist_ok=True)
    _queues_path().write_text(text, encoding="utf-8")


def _append_freshness_queue_event(queues: list[dict[str, Any]], card: dict[str, Any], *, reason: str, now: str) -> None:
    card_id = str(card.get("cardId") or "").strip()
    dedup_key = f"{reason}:{card_id}"
    if _has_open_event(queues, queue_kind="freshness", dedup_key=dedup_key):
        return
    s = _service()
    queues.append(
        {
            "queueEventId": s._new_event_id("cqevt"),
            "queueKind": "freshness",
            "partition": str(card.get("partition") or "").strip(),
            "cardIds": [card_id],
            "status": "open",
            "reason": reason,
            "dedupKey": dedup_key,
            "openedAt": now,
            "resolvedAt": "",
            "resolution": "",
            "notes": "",
        }
    )


def _compute_source_hash(
    source: dict[str, Any],
    structure: dict[str, Any],
    *,
    card_id: str = "",
) -> str | None:
    if not isinstance(source, dict):
        return None
    source_type = str(source.get("type") or "").strip()
    locator = str(source.get("locator") or "").strip()
    if not source_type or not locator:
        return None
    if source_type in {"git_path", "skill", "progress_index"}:
        path = _resolve_locator_path(locator, source_type)
        if path is None:
            return None
        return _sha256_bytes_file(path)
    if source_type == "agent_directory":
        return _agent_directory_source_hash(locator)
    if source_type == "central_source":
        return _central_source_hash(locator)
    if source_type == "experience":
        body = _read_experience_body(card_id or _locator_card_id(locator))
        return _sha256_text(body) if body is not None else None
    return None


def _locator_card_id(locator: str) -> str:
    text = str(locator or "").strip()
    if text.startswith("experience/"):
        return text[len("experience/") :].removesuffix(".md")
    return ""


def _sha256_text(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def _sha256_bytes_file(path: Path) -> str | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    return hashlib.sha256(raw).hexdigest()


def _agent_directory_source_hash(agent_id: str) -> str | None:
    s = _service()
    try:
        agent = s.agent_directory_service.get_agent(str(agent_id or "").strip())
    except Exception:
        agent = {}
    if not isinstance(agent, dict) or not agent:
        return None
    payload = {
        "updatedAt": str(agent.get("updatedAt") or "").strip(),
        "displayName": str(agent.get("displayName") or "").strip(),
        "roleKey": str(agent.get("roleKey") or "").strip(),
        "primaryMode": str(agent.get("primaryMode") or "").strip(),
    }
    return _sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _central_source_hash(central_source_id: str) -> str | None:
    s = _service()
    source = s._find_central_source_by_id_locked(str(central_source_id or "").strip())
    if not isinstance(source, dict) or not source:
        return None
    source_hash = str(source.get("sourceHash") or "").strip()
    return source_hash or None


# ---------------------------------------------------------------------------
# locator allowlist (lock 23)
# ---------------------------------------------------------------------------


def _normalize_locator(locator: str, *, strip_symbol: bool = True) -> str:
    """Return the normalized repo-relative POSIX locator or empty on escape."""
    text = str(locator or "").strip().replace("\\", "/")
    if not text:
        return ""
    if text.startswith("/"):
        return ""
    if ":" in text:
        return ""
    if strip_symbol and "#" in text:
        text = text.split("#", 1)[0].rstrip("/")
    if not text:
        return ""
    parts = [part for part in PurePosixPath(text).parts if part not in {"", "."}]
    if any(part in {"..", "~"} for part in parts):
        return ""
    if any(":" in part for part in parts):
        return ""
    return "/".join(parts)


def _resolve_locator_path(locator: str, source_type: str) -> Path | None:
    """Resolve an allowlisted locator to a file inside PROJECT_ROOT, or None."""
    normalized = _normalize_locator(locator)
    if not normalized:
        return None
    root = _project_root()
    candidate = (root / normalized).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    if source_type == "skill":
        # Skills must live under a registered skills root; P0 keeps the closed
        # set to project-local skills directories.
        skill_roots = (
            (root / "skills").resolve(),
            _sandbox_skills_root(),
        )
        if not any(_is_relative_to(candidate, skill_root) for skill_root in skill_roots):
            return None
    return candidate


def _sandbox_skills_root() -> Path:
    try:
        from core.infrastructure import developer_sandbox

        return developer_sandbox.seeded_sandbox_workspace_path(_project_root(), "skills").resolve()
    except Exception:
        return Path()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _agent_directory_locator_allowed(locator: str) -> bool:
    normalized = str(locator or "").strip()
    return bool(normalized) and "/" not in normalized and "\\" not in normalized and ":" not in normalized


def resolve_public_locator(
    card: dict[str, Any],
    *,
    agent_id: str = "",
    check_hash: bool = True,
    internal: bool = False,
) -> dict[str, Any]:
    """Resolve a card source through the allowlist and return its content.

    Out-of-scope, escaping, or unknown source types raise
    ``PublicCatalogSourceUnavailableError`` (forbidden) without reading disk
    and without falling back to the card summary. ``hash_mismatch`` marks the
    card stale/hidden and enqueues a freshness event.
    """
    source = card.get("source") if isinstance(card.get("source"), dict) else {}
    source_type = str(source.get("type") or "").strip()
    locator = str(source.get("locator") or "").strip()
    card_id = str(card.get("cardId") or "").strip()
    if source_type not in PUBLIC_SOURCE_TYPES:
        raise PublicCatalogSourceUnavailableError("forbidden", locator=locator, card_id=card_id)
    if source_type in {"git_path", "skill", "progress_index"}:
        path = _resolve_locator_path(locator, source_type)
        if path is None:
            raise PublicCatalogSourceUnavailableError("forbidden", locator=locator, card_id=card_id)
        return _open_file_source(path, card, check_hash=check_hash, card_id=card_id)
    if source_type == "agent_directory":
        if not _agent_directory_locator_allowed(locator):
            raise PublicCatalogSourceUnavailableError("forbidden", locator=locator, card_id=card_id)
        return _open_agent_directory_source(locator, card, check_hash=check_hash, card_id=card_id)
    if source_type == "central_source":
        return _open_central_source(locator, card, check_hash=check_hash, card_id=card_id)
    if source_type == "experience":
        body = _read_experience_body(_locator_card_id(locator) or card_id)
        if body is None:
            raise PublicCatalogSourceUnavailableError("missing", locator=locator, card_id=card_id)
        return _content_result(
            body=body,
            card=card,
            observed_hash=_sha256_text(body),
            check_hash=check_hash,
            card_id=card_id,
        )
    raise PublicCatalogSourceUnavailableError("forbidden", locator=locator, card_id=card_id)


def _open_file_source(path: Path, card: dict[str, Any], *, check_hash: bool, card_id: str) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError:
        raise PublicCatalogSourceUnavailableError("unreadable", locator=str(path), card_id=card_id)
    observed_hash = hashlib.sha256(raw).hexdigest()
    if check_hash:
        _enforce_source_hash(card, observed_hash, card_id=card_id)
    try:
        body = raw.decode("utf-8", errors="replace")
    except Exception:
        body = ""
    source = card.get("source") if isinstance(card.get("source"), dict) else {}
    return {
        "ok": True,
        "cardId": card_id,
        "sourceType": str(source.get("type") or "").strip(),
        "locator": str(path),
        "contentType": "text/plain",
        "content": body,
        "contentHash": observed_hash,
    }


def _open_agent_directory_source(agent_id: str, card: dict[str, Any], *, check_hash: bool, card_id: str) -> dict[str, Any]:
    s = _service()
    try:
        agent = s.agent_directory_service.get_agent(agent_id)
    except Exception:
        agent = {}
    if not isinstance(agent, dict) or not agent:
        raise PublicCatalogSourceUnavailableError("missing", locator=agent_id, card_id=card_id)
    observed_hash = _agent_directory_source_hash(agent_id)
    if check_hash:
        _enforce_source_hash(card, observed_hash or "", card_id=card_id)
    return {
        "ok": True,
        "cardId": card_id,
        "sourceType": "agent_directory",
        "locator": agent_id,
        "contentType": "application/json",
        "content": json.dumps(
            {
                "agentId": agent_id,
                "displayName": str(agent.get("displayName") or "").strip(),
                "roleKey": str(agent.get("roleKey") or "").strip(),
                "primaryMode": str(agent.get("primaryMode") or "").strip(),
                "status": str(agent.get("status") or "").strip(),
                "updatedAt": str(agent.get("updatedAt") or "").strip(),
            },
            ensure_ascii=False,
        ),
        "contentHash": observed_hash or "",
    }


def _open_central_source(central_source_id: str, card: dict[str, Any], *, check_hash: bool, card_id: str) -> dict[str, Any]:
    s = _service()
    source = s._find_central_source_by_id_locked(str(central_source_id or "").strip())
    if not isinstance(source, dict) or not source:
        raise PublicCatalogSourceUnavailableError("missing", locator=central_source_id, card_id=card_id)
    observed_hash = str(source.get("sourceHash") or "").strip()
    if check_hash:
        _enforce_source_hash(card, observed_hash, card_id=card_id)
    local_copies = [copy for copy in list(source.get("localCopies") or []) if isinstance(copy, dict)][:16]
    return {
        "ok": True,
        "cardId": card_id,
        "sourceType": "central_source",
        "locator": central_source_id,
        "contentType": "application/json",
        "content": json.dumps(
            {
                "centralSourceId": str(source.get("centralSourceId") or "").strip(),
                "title": str(source.get("title") or "").strip(),
                "sourceHash": observed_hash,
                "localCopies": local_copies,
            },
            ensure_ascii=False,
        ),
        "contentHash": observed_hash,
    }


def _content_result(*, body: str, card: dict[str, Any], observed_hash: str, check_hash: bool, card_id: str) -> dict[str, Any]:
    if check_hash:
        _enforce_source_hash(card, observed_hash, card_id=card_id)
    source = card.get("source") if isinstance(card.get("source"), dict) else {}
    return {
        "ok": True,
        "cardId": card_id,
        "sourceType": str(source.get("type") or "").strip(),
        "locator": str(source.get("locator") or "").strip(),
        "contentType": "text/markdown",
        "content": body,
        "contentHash": observed_hash,
    }


def _enforce_source_hash(card: dict[str, Any], observed_hash: str, *, card_id: str) -> None:
    source = card.get("source") if isinstance(card.get("source"), dict) else {}
    expected_hash = str(source.get("contentHash") or "").strip()
    if expected_hash and observed_hash != expected_hash:
        _mark_stale_and_enqueue(card_id, observed_hash)
        raise PublicCatalogSourceUnavailableError("hash_mismatch", card_id=card_id)


def _mark_stale_and_enqueue(card_id: str, observed_hash: str) -> None:
    s = _service()
    now = utc_now_iso()
    with s._LOCK:
        structure = _read_structure()
        queues = _read_queues()
        card = _card_by_id(structure["cards"], card_id)
        if not card or str(card.get("visibility") or "").strip() == "archived":
            return
        card["visibility"] = "hidden"
        card["freshness"] = {
            "status": "stale",
            "observedHash": observed_hash,
            "lastCheckedAt": now,
            "lastRefreshedAt": now,
        }
        _write_structure(structure)
        _append_freshness_queue_event(queues, card, reason="stale", now=now)
        _write_queues_with_events(queues)


def open_public_card(card_id: str, *, agent_id: str = "", internal: bool = False) -> dict[str, Any]:
    """Open a card source through the allowlist (mixed read; no summary fallback)."""
    _sync_roots()
    structure = _read_structure()
    card = _card_by_id(structure["cards"], card_id)
    if not card:
        raise PublicCatalogNotFoundError("Public card not found.")
    if str(card.get("visibility") or "").strip() != "agent_visible" and not internal:
        raise PublicCatalogPermissionError("Public card is not agent-visible.")
    return resolve_public_locator(card, agent_id=agent_id, check_hash=True, internal=internal)


# ---------------------------------------------------------------------------
# P5: conflict detection
# ---------------------------------------------------------------------------


def _detect_conflicts(structure: dict[str, Any], queues: list[dict[str, Any]], *, now: str) -> list[dict[str, Any]]:
    s = _service()
    opened: list[dict[str, Any]] = []
    searchable_pins = [
        card
        for card in structure["cards"]
        if str(card.get("kind") or "").strip() == "pin"
        and str(card.get("visibility") or "").strip() == "agent_visible"
        and str((card.get("freshness") or {}).get("status") or "").strip() == "current"
    ]
    by_locator: dict[str, list[dict[str, Any]]] = {}
    for card in searchable_pins:
        source = card.get("source") if isinstance(card.get("source"), dict) else {}
        normalized = _normalize_locator(str(source.get("locator") or "").strip())
        if normalized:
            by_locator.setdefault(normalized, []).append(card)
    for normalized_locator, cards in by_locator.items():
        if len(cards) < 2:
            continue
        seen: set[str] = set()
        for card in cards:
            key = _conflict_signature(card)
            if key in seen:
                continue
            seen.add(key)
        if len(seen) < 2:
            continue
        card_ids = sorted(str(card.get("cardId") or "") for card in cards)
        dedup_key = f"duplicate_locator:{normalized_locator}"
        if _has_open_event(queues, queue_kind="conflict", dedup_key=dedup_key):
            continue
        event = {
            "queueEventId": s._new_event_id("cqevt"),
            "queueKind": "conflict",
            "partition": "",
            "cardIds": card_ids,
            "status": "open",
            "reason": "duplicate_locator",
            "dedupKey": dedup_key,
            "openedAt": now,
            "resolvedAt": "",
            "resolution": "",
            "notes": f"Same locator with different summaries or hashes: {normalized_locator}",
        }
        queues.append(event)
        opened.append(event)
    card_ids_by_id = {str(card.get("cardId") or ""): card for card in structure["cards"]}
    for card in searchable_pins:
        for contradicted_id in list(card.get("contradictsCardIds") or []):
            contradicted = card_ids_by_id.get(str(contradicted_id or "").strip())
            if not contradicted or str(contradicted.get("visibility") or "").strip() != "agent_visible":
                continue
            dedup_key = f"contradicts:{card['cardId']}:{contradicted_id}"
            if _has_open_event(queues, queue_kind="conflict", dedup_key=dedup_key):
                continue
            event = {
                "queueEventId": s._new_event_id("cqevt"),
                "queueKind": "conflict",
                "partition": str(card.get("partition") or "").strip(),
                "cardIds": [str(card.get("cardId") or ""), str(contradicted_id or "")],
                "status": "open",
                "reason": "contradicts",
                "dedupKey": dedup_key,
                "openedAt": now,
                "resolvedAt": "",
                "resolution": "",
                "notes": "Explicit contradicts edge between searchable pins.",
            }
            queues.append(event)
            opened.append(event)
    return opened


def _conflict_signature(card: dict[str, Any]) -> str:
    freshness = card.get("freshness") if isinstance(card.get("freshness"), dict) else {}
    return f"{card.get('summary')}|{freshness.get('observedHash')}"


# ---------------------------------------------------------------------------
# P3: searchable-set search DTO
# ---------------------------------------------------------------------------


def search_public_catalog(*, query: str = "", limit: int = 8, agent_id: str = "") -> dict[str, Any]:
    """Search the catalog haystack (title/whenToUse/summary only)."""
    _sync_roots()
    normalized_query = str(query or "").strip()
    if not normalized_query:
        return {"summary": {"resultCount": 0, "candidateCount": 0}, "results": []}
    structure = _read_structure()
    queues = _read_queues()
    open_conflict_ids = _open_conflict_card_ids(queues)
    searchable = [card for card in structure["cards"] if _card_is_searchable(card, open_conflict_ids)]
    query_tokens = _tokenize_catalog_text(normalized_query)
    matched: list[dict[str, Any]] = []
    for card in searchable:
        haystack = _catalog_haystack(card)
        haystack_tokens = _tokenize_catalog_text(haystack)
        score = _catalog_overlap_score(query_tokens, haystack_tokens)
        if score <= 0:
            continue
        matched.append({"card": card, "score": score})
    matched.sort(key=lambda item: (item["score"], str(item["card"].get("updatedAt") or "")), reverse=True)
    bounded = _bounded_search_limit(limit)
    results = [
        _catalog_result_dto(item["card"], score=item["score"], rank=index + 1)
        for index, item in enumerate(matched[:bounded])
    ]
    return {
        "summary": {
            "resultCount": len(results),
            "candidateCount": len(matched),
            "searchableCardCount": len(searchable),
        },
        "results": results,
    }


def _tokenize_catalog_text(text: str) -> set[str]:
    s = _service()
    return s._tokenize_search_text(str(text or ""))


def _catalog_haystack(card: dict[str, Any]) -> str:
    return "\n".join(
        part
        for part in [
            str(card.get("title") or "").strip(),
            str(card.get("whenToUse") or "").strip(),
            str(card.get("summary") or "").strip(),
        ]
        if part
    )


def _catalog_overlap_score(query_tokens: set[str], haystack_tokens: set[str]) -> float:
    if not query_tokens:
        return 0.0
    return len(query_tokens.intersection(haystack_tokens)) / len(query_tokens)


def _catalog_result_dto(card: dict[str, Any], *, score: float, rank: int) -> dict[str, Any]:
    source = card.get("source") if isinstance(card.get("source"), dict) else {}
    freshness = card.get("freshness") if isinstance(card.get("freshness"), dict) else {}
    origin_ref = card.get("originRef")
    payload: dict[str, Any] = {
        "resultId": f"pubc:{card.get('cardId')}",
        "resultType": "public_catalog_card",
        "cardId": str(card.get("cardId") or "").strip(),
        "kind": str(card.get("kind") or "").strip(),
        "partition": str(card.get("partition") or "").strip(),
        "title": str(card.get("title") or "").strip(),
        "whenToUse": str(card.get("whenToUse") or "").strip(),
        "summary": str(card.get("summary") or "").strip(),
        "locator": str(source.get("locator") or "").strip(),
        "sourceType": str(source.get("type") or "").strip(),
        "contentHash": str(source.get("contentHash") or "").strip(),
        "freshnessStatus": str(freshness.get("status") or "").strip(),
        "originRef": origin_ref if isinstance(origin_ref, dict) else None,
        "openRequired": True,
        "score": score,
        "rank": rank,
    }
    return payload


def _bounded_search_limit(limit: Any) -> int:
    try:
        parsed = int(limit)
    except (TypeError, ValueError):
        parsed = 8
    return max(1, min(25, parsed))


# ---------------------------------------------------------------------------
# P4: startup structure block (hard budget + PromptManager dedup)
# ---------------------------------------------------------------------------


def build_startup_structure_block(*, agent_id: str = "") -> dict[str, Any]:
    """Build the bounded startup structure digest with exclusion set.

    Excluded (lock 21): PromptManager-owned sources (AGENTS.md,
    core/core_prompt/*) and ``agent_directory`` cards. Budget rows:
    ``included=.. omitted=.. excludedStartup=.. budgetChars=..``.
    """
    _sync_roots()
    structure = _read_structure()
    queues = _read_queues()
    open_conflict_ids = _open_conflict_card_ids(queues)
    searchable = [card for card in structure["cards"] if _card_is_searchable(card, open_conflict_ids)]
    included: list[dict[str, Any]] = []
    excluded_count = 0
    for card in searchable:
        if _is_startup_excluded(card):
            excluded_count += 1
            continue
        included.append(card)
    budget = structure.get("budget") if isinstance(structure.get("budget"), dict) else _default_structure()["budget"]
    max_cards = _bounded_int(budget.get("maxCards"), default=STARTUP_STRUCTURE_MAX_CARDS, maximum=STARTUP_STRUCTURE_MAX_CARDS)
    max_chars = _bounded_int(budget.get("maxChars"), default=STARTUP_STRUCTURE_MAX_CHARS, maximum=STARTUP_STRUCTURE_MAX_CHARS)
    quotas = budget.get("partitionQuotas") if isinstance(budget.get("partitionQuotas"), dict) else {}
    selected: list[dict[str, Any]] = []
    for partition in PUBLIC_PARTITIONS:
        partition_cards = [
            card
            for card in included
            if str(card.get("partition") or "").strip() == partition
        ]
        partition_cards.sort(
            key=lambda item: (
                _safe_int(item.get("stewardWeight")),
                str((item.get("freshness") or {}).get("lastRefreshedAt") or item.get("updatedAt") or ""),
            ),
            reverse=True,
        )
        quota = max(0, int(quotas.get(partition) or 0))
        selected.extend(partition_cards[:quota])
    header = _startup_header(included_count=len(included), max_cards=max_cards)
    rows: list[str] = []
    for card in selected:
        if len(rows) >= max_cards:
            break
        row = _startup_card_row(card)
        if not row:
            continue
        candidate_block = "\n".join([header, *rows, row])
        if len(candidate_block) > max_chars:
            break
        rows.append(row)
    included_visible = len(rows)
    omitted = len(searchable) - excluded_count - included_visible
    budget_line = f"included={included_visible} omitted={omitted} excludedStartup={excluded_count} budgetChars={max_chars}"
    block = "\n".join([header, *rows, budget_line]).strip()
    if len(block) > max_chars:
        block = _trim_block_to_budget(block, max_chars)
    return {
        "block": block,
        "budget": {
            "included": included_visible,
            "omitted": omitted,
            "excludedStartup": excluded_count,
            "budgetChars": max_chars,
            "maxCards": max_cards,
            "totalChars": len(block),
        },
        "cards": [
            {
                "cardId": str(card.get("cardId") or "").strip(),
                "title": str(card.get("title") or "").strip(),
                "whenToUse": str(card.get("whenToUse") or "").strip()[:STARTUP_CARD_WHEN_TO_USE_CHARS],
                "locator": str((card.get("source") or {}).get("locator") or "").strip() if isinstance(card.get("source"), dict) else "",
            }
            for card in selected[:included_visible]
        ],
    }


def _startup_header(included_count: int, max_cards: int) -> str:
    return (
        "## Public Structure Catalog (curated; discovery only)\n"
        f"Source: workspace/knowledge/public/structure.json · {included_count} searchable cards within budget {max_cards}\n"
        "Cards are pointers, not authoritative text; open the locator source before acting."
    )


def _startup_card_row(card: dict[str, Any]) -> str:
    source = card.get("source") if isinstance(card.get("source"), dict) else {}
    locator = str(source.get("locator") or "").strip()
    title = str(card.get("title") or "").strip()
    when_to_use = str(card.get("whenToUse") or "").strip()
    when_to_use = when_to_use if len(when_to_use) <= STARTUP_CARD_WHEN_TO_USE_CHARS else when_to_use[: STARTUP_CARD_WHEN_TO_USE_CHARS - 3].rstrip() + "..."
    if not title or not locator:
        return ""
    parts = [f"- {title}"]
    if when_to_use:
        parts.append(when_to_use)
    parts.append(f"locator:{locator}")
    return " | ".join(parts)


def _trim_block_to_budget(block: str, max_chars: int) -> str:
    if len(block) <= max_chars:
        return block
    return block[: max_chars - 3].rstrip() + "..."


def _is_startup_excluded(card: dict[str, Any]) -> bool:
    source = card.get("source") if isinstance(card.get("source"), dict) else {}
    source_type = str(source.get("type") or "").strip()
    if source_type == "agent_directory":
        return True
    locator = _normalize_locator(str(source.get("locator") or "").strip())
    if not locator:
        return False
    normalized = locator.lower()
    if normalized in _PROMPT_MANAGER_EXCLUDED_LOCATORS:
        return True
    return any(normalized.startswith(prefix) for prefix in _PROMPT_MANAGER_EXCLUDED_PREFIXES)


# ---------------------------------------------------------------------------
# proposals (A.2) and queue resolution
# ---------------------------------------------------------------------------


def submit_public_proposal(
    proposal: dict[str, Any],
    *,
    proposed_by_agent_id: str = "",
) -> dict[str, Any]:
    """Append an agent/team promotion proposal. Not visible to development
    agents until the steward accepts it."""
    actor_id = str(proposed_by_agent_id or "").strip()
    if not actor_id:
        raise PublicCatalogPermissionError("A proposing agent id is required.")
    if not isinstance(proposal, dict):
        raise PublicCatalogError("Public proposal payload must be an object.")
    partition = str(proposal.get("partition") or "").strip()
    if partition not in PUBLIC_PARTITIONS:
        raise PublicCatalogError("Public proposal requires a valid partition.")
    title = str(proposal.get("title") or "").strip()
    if not title:
        raise PublicCatalogError("Public proposal requires a title.")
    origin_ref = proposal.get("originRef")
    if not isinstance(origin_ref, dict):
        origin_ref = {}
    source = proposal.get("source") if isinstance(proposal.get("source"), dict) else {}
    now = utc_now_iso()
    s = _service()
    payload = {
        "proposalId": s._new_event_id("pprop"),
        "partition": partition,
        "title": _bounded_text(title, 120),
        "summary": _bounded_text(str(proposal.get("summary") or ""), PUBLIC_MAX_SUMMARY_CHARS),
        "originRef": {
            "layer": str(origin_ref.get("layer") or "").strip(),
            "ownerId": str(origin_ref.get("ownerId") or "").strip(),
            "itemId": str(origin_ref.get("itemId") or origin_ref.get("episodeId") or "").strip(),
        },
        "source": {
            "type": str(source.get("type") or "").strip(),
            "locator": str(source.get("locator") or "").strip(),
        },
        "proposedByAgentId": actor_id,
        "status": "pending",
        "createdAt": now,
        "updatedAt": now,
    }
    with s._LOCK:
        s._append_jsonl(_proposals_path(), payload)
        _append_public_audit("structure.proposal.submitted", {"proposalId": payload["proposalId"], "partition": partition}, actor_agent_id=actor_id)
    return payload


def list_public_proposals(*, internal: bool = False) -> dict[str, Any]:
    proposals = _read_proposals()
    visible = proposals if internal else [proposal for proposal in proposals if str(proposal.get("status") or "").strip() != "pending"]
    return {
        "schemaVersion": PUBLIC_STRUCTURE_SCHEMA_VERSION,
        "summary": {
            "proposalCount": len(proposals),
            "pendingProposalCount": sum(1 for proposal in proposals if str(proposal.get("status") or "").strip() == "pending"),
            "visibleProposalCount": len(visible),
        },
        "proposals": visible,
        "updatedAt": utc_now_iso(),
    }


def resolve_public_proposal(proposal_id: str, *, status: str = "accepted", actor_agent_id: str = "", internal: bool = False) -> dict[str, Any]:
    """Steward-only proposal resolution. Acceptance only writes the catalog
    card via upsert; it never appends item bodies to any items.jsonl."""
    _require_structure_steward(actor_agent_id, internal=internal)
    if str(status or "").strip() not in {"accepted", "rejected"}:
        raise PublicCatalogError("Proposal resolution must be accepted or rejected.")
    now = utc_now_iso()
    s = _service()
    with s._LOCK:
        proposals = _read_proposals()
        proposal = next(
            (item for item in proposals if str(item.get("proposalId") or "").strip() == str(proposal_id or "").strip()),
            None,
        )
        if not proposal:
            raise PublicCatalogNotFoundError("Public proposal not found.")
        proposal["status"] = str(status or "accepted").strip()
        proposal["resolvedByAgentId"] = str(actor_agent_id or "").strip()
        proposal["updatedAt"] = now
        s._write_jsonl(_proposals_path(), proposals)
        _append_public_audit("structure.proposal.resolved", {"proposalId": proposal["proposalId"], "status": proposal["status"]}, actor_agent_id=actor_agent_id)
    return dict(proposal)


def list_catalog_queue_events(*, status: str = "open", agent_id: str = "", internal: bool = False) -> dict[str, Any]:
    _sync_roots()
    normalized_status = str(status or "open").strip().lower()
    if normalized_status not in {"open", "closed", "all"}:
        raise PublicCatalogError(f"Unsupported catalog queue status: {status}")
    events = _read_queues()
    visible: list[dict[str, Any]] = []
    for event in events:
        closed = str(event.get("status") or "").strip() != "open"
        if normalized_status == "all":
            keep = True
        elif normalized_status == "closed":
            keep = closed
        else:
            keep = not closed
        if keep:
            visible.append(event)
    visible.sort(key=lambda item: str(item.get("openedAt") or ""), reverse=True)
    return {
        "schemaVersion": PUBLIC_STRUCTURE_SCHEMA_VERSION,
        "summary": {
            "eventCount": len(visible),
            "openFreshnessCount": sum(1 for event in visible if str(event.get("status") or "").strip() == "open" and str(event.get("queueKind") or "").strip() == "freshness"),
            "openConflictCount": sum(1 for event in visible if str(event.get("status") or "").strip() == "open" and str(event.get("queueKind") or "").strip() == "conflict"),
        },
        "events": visible[:200],
        "updatedAt": utc_now_iso(),
    }


def resolve_catalog_queue_event(
    queue_event_id: str,
    *,
    resolution: str = "confirm",
    actor_agent_id: str = "",
    internal: bool = False,
    notes: str = "",
) -> dict[str, Any]:
    """Steward-only queue resolution. Freshness confirm re-arms the card;
    conflict keep_a/keep_b/merge/archive re-opens one side of the conflict."""
    _require_structure_steward(actor_agent_id, internal=internal)
    if str(resolution or "").strip() not in PUBLIC_QUEUE_RESOLUTIONS:
        raise PublicCatalogError(f"Unsupported catalog queue resolution: {resolution}")
    normalized_event_id = str(queue_event_id or "").strip()
    if not normalized_event_id:
        raise PublicCatalogNotFoundError("Queue event id is required.")
    now = utc_now_iso()
    s = _service()
    with s._LOCK:
        queues = _read_queues()
        event = next(
            (item for item in queues if str(item.get("queueEventId") or "").strip() == normalized_event_id),
            None,
        )
        if not event:
            raise PublicCatalogNotFoundError("Queue event not found.")
        if str(event.get("status") or "").strip() != "open":
            raise PublicCatalogError("Queue event is already closed.")
        event["status"] = "resolved"
        event["resolvedAt"] = now
        event["resolution"] = str(resolution or "").strip()
        if notes:
            event["notes"] = _bounded_text(str(event.get("notes") or "") + " " + notes, 400)
        structure = _read_structure()
        queue_kind = str(event.get("queueKind") or "").strip()
        if queue_kind == "freshness":
            _apply_freshness_resolution(structure, event, resolution=resolution, now=now)
        elif queue_kind == "conflict":
            _apply_conflict_resolution(structure, event, resolution=resolution, now=now)
        _write_structure(structure)
        _write_queues_with_events(queues)
        _append_public_audit(
            "structure.queue.resolved",
            {"queueEventId": normalized_event_id, "resolution": event["resolution"]},
            actor_agent_id=actor_agent_id,
        )
    return dict(event)


def _apply_freshness_resolution(structure: dict[str, Any], event: dict[str, Any], *, resolution: str, now: str) -> None:
    for card_id in list(event.get("cardIds") or []):
        card = _card_by_id(structure["cards"], str(card_id or "").strip())
        if not card or str(card.get("visibility") or "").strip() == "archived":
            continue
        if resolution == "confirm":
            source = card.get("source") if isinstance(card.get("source"), dict) else {}
            observed = str((card.get("freshness") or {}).get("observedHash") or "").strip()
            if not observed:
                continue
            source = dict(source)
            source["contentHash"] = observed
            card["source"] = source
            card["visibility"] = "agent_visible"
            card["freshness"] = {
                "status": "current",
                "observedHash": observed,
                "lastCheckedAt": now,
                "lastRefreshedAt": now,
            }
            card["updatedAt"] = now
        elif resolution == "archive":
            source = card.get("source") if isinstance(card.get("source"), dict) else {}
            card["visibility"] = "archived"
            card["archivedAt"] = now
            card["archivedReason"] = str(event.get("reason") or "steward archive")
            card["previousHash"] = str(source.get("contentHash") or "").strip()
            card["updatedAt"] = now
        else:
            card["visibility"] = "hidden"
            card["updatedAt"] = now


def _apply_conflict_resolution(structure: dict[str, Any], event: dict[str, Any], *, resolution: str, now: str) -> None:
    card_ids = [str(value or "").strip() for value in list(event.get("cardIds") or [])]
    if resolution == "archive":
        for card_id in card_ids:
            card = _card_by_id(structure["cards"], card_id)
            if not card or str(card.get("visibility") or "").strip() == "archived":
                continue
            source = card.get("source") if isinstance(card.get("source"), dict) else {}
            card["visibility"] = "archived"
            card["archivedAt"] = now
            card["archivedReason"] = "conflict resolution: archive"
            card["previousHash"] = str(source.get("contentHash") or "").strip()
            card["updatedAt"] = now
        return
    if resolution == "keep_a" and len(card_ids) >= 2:
        keeper = card_ids[0]
        for card_id in card_ids[1:]:
            card = _card_by_id(structure["cards"], card_id)
            if not card or str(card.get("visibility") or "").strip() == "archived":
                continue
            card["visibility"] = "hidden"
            card["updatedAt"] = now
        card = _card_by_id(structure["cards"], keeper)
        if card and str(card.get("visibility") or "").strip() != "archived":
            card["visibility"] = "agent_visible"
            card["updatedAt"] = now
        return
    if resolution == "keep_b" and len(card_ids) >= 2:
        keeper = card_ids[-1]
        for card_id in card_ids[:-1]:
            card = _card_by_id(structure["cards"], card_id)
            if not card or str(card.get("visibility") or "").strip() == "archived":
                continue
            card["visibility"] = "hidden"
            card["updatedAt"] = now
        card = _card_by_id(structure["cards"], keeper)
        if card and str(card.get("visibility") or "").strip() != "archived":
            card["visibility"] = "agent_visible"
            card["updatedAt"] = now
        return
    for card_id in card_ids:
        card = _card_by_id(structure["cards"], card_id)
        if not card or str(card.get("visibility") or "").strip() == "archived":
            continue
        card["visibility"] = "agent_visible"
        card["updatedAt"] = now


def _append_public_audit(action: str, fields: dict[str, Any], *, actor_agent_id: str = "") -> None:
    s = _service()
    s._append_jsonl(
        _public_root() / "audit.jsonl",
        {
            "auditId": s._new_event_id("pcaudit"),
            "action": action,
            "actorAgentId": str(actor_agent_id or "").strip(),
            "createdAt": utc_now_iso(),
            "payload": {str(key)[:80]: value for key, value in list(fields.items())[:20]},
        },
    )


def _sync_roots() -> None:
    s = _service()
    s._sync_roots()


# ---------------------------------------------------------------------------
# governance projection (A.6, lock 22)
# ---------------------------------------------------------------------------


def _catalog_governance_tasks(status: str = "open") -> list[dict[str, Any]]:
    """Project catalog freshness/conflict/proposal queues into the existing
    governance task shape (no parallel steward overview)."""
    _sync_roots()
    normalized_status = str(status or "open").strip().lower()
    tasks: list[dict[str, Any]] = []
    for event in _read_queues():
        task_closed = str(event.get("status") or "").strip() != "open"
        if not _task_status_matches(task_closed, normalized_status):
            continue
        queue_kind = str(event.get("queueKind") or "").strip()
        task_type = {
            "freshness": "catalog_freshness",
            "conflict": "catalog_conflict",
            "proposal": "catalog_proposal",
        }.get(queue_kind)
        if not task_type:
            continue
        tasks.append(
            {
                "taskId": f"ktask:public:{task_type}:{event.get('queueEventId')}",
                "taskType": task_type,
                "status": "closed" if task_closed else "open",
                "priority": "elevated" if not task_closed else "normal",
                "ownerType": "public",
                "ownerId": "",
                "teamId": "",
                "teamName": "",
                "agentId": "",
                "agentName": "",
                "knowledgeBaseId": "public",
                "knowledgeBaseName": "公共结构策展库",
                "targetId": str(event.get("queueEventId") or "").strip(),
                "targetStatus": str(event.get("reason") or "").strip(),
                "title": _catalog_task_title(queue_kind, event),
                "summary": _catalog_task_summary(queue_kind, event),
                "sourceArtifactIds": [],
                "createdAt": str(event.get("openedAt") or "").strip(),
                "updatedAt": str(event.get("openedAt") or "").strip(),
                "permissions": {
                    "canReview": True,
                    "canRate": False,
                    "canPropose": False,
                },
            }
        )
    for proposal in _read_proposals():
        task_closed = str(proposal.get("status") or "").strip() != "pending"
        if not _task_status_matches(task_closed, normalized_status):
            continue
        tasks.append(
            {
                "taskId": f"ktask:public:catalog_proposal:{proposal.get('proposalId')}",
                "taskType": "catalog_proposal",
                "status": "closed" if task_closed else "open",
                "priority": "elevated" if not task_closed else "normal",
                "ownerType": "public",
                "ownerId": "",
                "teamId": "",
                "teamName": "",
                "agentId": str(proposal.get("proposedByAgentId") or "").strip(),
                "agentName": "",
                "knowledgeBaseId": "public",
                "knowledgeBaseName": "公共结构策展库",
                "targetId": str(proposal.get("proposalId") or "").strip(),
                "targetStatus": str(proposal.get("status") or "").strip(),
                "title": str(proposal.get("title") or "Catalog proposal"),
                "summary": str(proposal.get("summary") or "").strip(),
                "sourceArtifactIds": [],
                "createdAt": str(proposal.get("createdAt") or "").strip(),
                "updatedAt": str(proposal.get("updatedAt") or "").strip(),
                "permissions": {
                    "canReview": True,
                    "canRate": False,
                    "canPropose": False,
                },
            }
        )
    return tasks


def _task_status_matches(closed: bool, normalized_status: str) -> bool:
    if normalized_status == "all":
        return True
    if normalized_status == "closed":
        return closed
    return not closed


def _catalog_task_title(queue_kind: str, event: dict[str, Any]) -> str:
    reason = str(event.get("reason") or "").strip()
    card_ids = ", ".join(str(value or "") for value in list(event.get("cardIds") or [])[:3])
    if queue_kind == "conflict":
        return f"Public catalog conflict: {card_ids}"
    if queue_kind == "proposal":
        return "Public catalog proposal review"
    return f"Public catalog freshness ({reason}): {card_ids}"


def _catalog_task_summary(queue_kind: str, event: dict[str, Any]) -> str:
    if str(event.get("notes") or "").strip():
        return str(event.get("notes") or "").strip()
    return f"{str(event.get('queueKind') or '').strip()} event for {', '.join(str(value or '') for value in list(event.get('cardIds') or [])[:3])}"
