"""Reviewed Companion preferences backed by native Agent episodic memory.

The native Agent episodic event remains the only preference authority. This
module validates a closed, versioned envelope, derives bounded projections and
coordinates native supersede operations plus value-free reconciliation
receipts. It does not own a second preference store and never calls an LLM.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable, Mapping
from copy import deepcopy
from typing import Any, Callable

PREFERENCE_ENVELOPE_PREFIX = "VIBELUTION_COMPANION_PREFERENCE_V1:"
PREFERENCE_SCHEMA_VERSION = 1
REVIEWED_STATUSES = {"user_confirmed", "operator_reviewed"}
PREFERENCE_ORDER = (
    "address",
    "response_length",
    "question_tolerance",
    "humor",
    "proactive_frequency",
    "interests",
    "privacy",
)

_ENUM_VALUES = {
    "response_length": {"brief", "compact", "balanced", "detailed"},
    "question_tolerance": {"low", "normal", "high"},
    "humor": {"off", "light", "natural"},
    "proactive_frequency": {"low", "normal", "high"},
    "privacy": {"never_mention_memory", "relevant_only"},
}


class CompanionPreferenceError(ValueError):
    """Raised when a preference envelope is outside the closed contract."""


class CompanionPreferencePersistenceError(RuntimeError):
    """Raised when native episodic memory cannot complete reconciliation."""


def _normalize_kind(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in PREFERENCE_ORDER:
        raise CompanionPreferenceError(f"Unsupported Companion preference: {value}")
    return normalized


def normalize_companion_preference_value(kind: str, value: object) -> object:
    normalized_kind = _normalize_kind(kind)
    if normalized_kind == "address":
        normalized = " ".join(str(value or "").split())[:40]
        if not normalized:
            raise CompanionPreferenceError("Companion address preference is required.")
        return normalized
    if normalized_kind == "interests":
        source = value if isinstance(value, list) else [value]
        items: list[str] = []
        for item in source:
            normalized = " ".join(str(item or "").split())[:80]
            if normalized and normalized not in items:
                items.append(normalized)
            if len(items) >= 12:
                break
        if not items:
            raise CompanionPreferenceError("At least one Companion interest is required.")
        return items
    normalized = str(value or "").strip().lower()
    if normalized not in _ENUM_VALUES[normalized_kind]:
        raise CompanionPreferenceError(
            f"Unsupported value for Companion preference {normalized_kind}: {value}"
        )
    return normalized


def encode_companion_preference_episode(
    preference_kind: str,
    value: object,
    *,
    review_status: str = "user_confirmed",
) -> str:
    """Encode a reviewed preference into a bounded native episode text."""

    normalized_status = str(review_status or "").strip().lower()
    if normalized_status not in REVIEWED_STATUSES:
        # Unreviewed envelopes may exist in imported/native memory, but this
        # writer never creates them.
        if normalized_status != "inferred":
            raise CompanionPreferenceError(
                f"Unsupported Companion preference review status: {review_status}"
            )
    normalized_kind = _normalize_kind(preference_kind)
    payload = {
        "schemaVersion": PREFERENCE_SCHEMA_VERSION,
        "preferenceKind": normalized_kind,
        "reviewStatus": normalized_status,
        "sensitive": False,
        "value": normalize_companion_preference_value(normalized_kind, value),
    }
    return PREFERENCE_ENVELOPE_PREFIX + json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _decode_episode(agent_id: str, episode: Mapping[str, Any]) -> dict[str, Any] | None:
    if str(episode.get("agentId") or "").strip() != agent_id:
        return None
    if str(episode.get("kind") or "").strip().lower() != "preference":
        return None
    if str(episode.get("validUntil") or "").strip():
        return None
    text = str(episode.get("text") or "")
    if not text.startswith(PREFERENCE_ENVELOPE_PREFIX):
        return None
    try:
        payload = json.loads(text.removeprefix(PREFERENCE_ENVELOPE_PREFIX))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    if int(payload.get("schemaVersion") or 0) != PREFERENCE_SCHEMA_VERSION:
        return None
    if str(payload.get("reviewStatus") or "") not in REVIEWED_STATUSES:
        return None
    if bool(payload.get("sensitive")):
        return None
    try:
        kind = _normalize_kind(payload.get("preferenceKind"))
        value = normalize_companion_preference_value(kind, payload.get("value"))
    except CompanionPreferenceError:
        return None
    episode_id = str(episode.get("episodeId") or episode.get("eventId") or "").strip()
    if not episode_id:
        return None
    return {
        "preferenceKind": kind,
        "value": value,
        "episodeId": episode_id,
        "reviewStatus": str(payload.get("reviewStatus") or ""),
        "occurredAt": str(episode.get("occurredAt") or ""),
    }


def project_companion_preferences(
    agent_id: str,
    episodes: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Project at most one current reviewed card for each closed slot."""

    normalized_agent_id = str(agent_id or "").strip()
    current: dict[str, dict[str, Any]] = {}
    for episode in episodes:
        if not isinstance(episode, Mapping):
            continue
        decoded = _decode_episode(normalized_agent_id, episode)
        if decoded is None:
            continue
        # Native listers are newest-first.  The first valid current episode is
        # authoritative; duplicates remain visible only in native history.
        current.setdefault(str(decoded["preferenceKind"]), decoded)
    cards = [deepcopy(current[kind]) for kind in PREFERENCE_ORDER if kind in current]
    return {
        "schemaVersion": PREFERENCE_SCHEMA_VERSION,
        "cards": cards,
        "values": {item["preferenceKind"]: deepcopy(item["value"]) for item in cards},
    }


def expression_preferences(projection: Mapping[str, Any] | None) -> dict[str, Any]:
    """Map reviewed cards to the existing bounded expression contract."""

    values = (projection or {}).get("values")
    if not isinstance(values, Mapping):
        return {}
    question_tolerance = str(values.get("question_tolerance") or "")
    humor = str(values.get("humor") or "")
    privacy = str(values.get("privacy") or "")
    proactive_frequency = str(values.get("proactive_frequency") or "")
    return {
        "preferredAddress": str(values.get("address") or "")[:40],
        "responseLength": str(values.get("response_length") or ""),
        "questionsAllowed": question_tolerance != "low",
        "humorAllowed": humor != "off",
        "memoryMentionsAllowed": privacy != "never_mention_memory",
        "proactiveFrequency": proactive_frequency,
    }


class CompanionPreferenceManager:
    """Coordinate native episode reconciliation and receipt-only plugin writes."""

    def __init__(
        self,
        *,
        episodic_writer: Callable[..., Mapping[str, Any]] | None,
        episodic_lister: Callable[[str], list[dict[str, Any]]],
        episodic_superseder: Callable[..., Mapping[str, Any]] | None,
        receipt_appender: Callable[[str, dict[str, Any]], None],
        now_iso: Callable[[], str],
    ) -> None:
        self._writer = episodic_writer
        self._lister = episodic_lister
        self._superseder = episodic_superseder
        self._receipt_appender = receipt_appender
        self._now_iso = now_iso

    def project(self, agent_id: str) -> dict[str, Any]:
        return project_companion_preferences(agent_id, self._lister(agent_id))

    def _receipt(
        self,
        agent_id: str,
        *,
        operation: str,
        preference_kind: str,
        episode_id: str,
        superseded_episode_id: str = "",
    ) -> dict[str, Any]:
        receipt = {
            "receiptId": f"preference-reconciliation-{uuid.uuid4().hex[:16]}",
            "agentId": str(agent_id).strip(),
            "operation": operation,
            "preferenceKind": preference_kind,
            "episodeId": episode_id,
            "supersededEpisodeId": superseded_episode_id,
            "recordedAt": self._now_iso(),
        }
        try:
            self._receipt_appender(agent_id, receipt)
        except Exception as exc:  # noqa: BLE001 - receipt is not preference authority
            return {
                **receipt,
                "recorded": False,
                "recordingError": type(exc).__name__,
            }
        return {**receipt, "recorded": True}

    def upsert(
        self,
        agent_id: str,
        *,
        preference_kind: str,
        value: object,
    ) -> dict[str, Any]:
        if self._writer is None or self._superseder is None:
            raise CompanionPreferencePersistenceError(
                "Native Agent episodic memory is unavailable."
            )
        normalized_kind = _normalize_kind(preference_kind)
        current = self.project(agent_id)
        existing = next(
            (
                item
                for item in list(current.get("cards") or [])
                if str(item.get("preferenceKind") or "") == normalized_kind
            ),
            None,
        )
        encoded = encode_companion_preference_episode(
            normalized_kind,
            value,
            review_status="user_confirmed",
        )
        try:
            created = self._writer(
                str(agent_id).strip(),
                kind="preference",
                text=encoded,
                refs=[{"type": "card", "id": f"companion-preference:{normalized_kind}"}],
                occurred_at=self._now_iso(),
            )
        except Exception as exc:  # noqa: BLE001 - native memory adapter boundary
            raise CompanionPreferencePersistenceError(
                "Could not write the native preference memory."
            ) from exc
        created_episode_id = str((created or {}).get("episodeId") or "").strip()
        if not created_episode_id:
            raise CompanionPreferencePersistenceError(
                "Native preference memory did not return an episode id."
            )
        old_episode_id = str((existing or {}).get("episodeId") or "").strip()
        if old_episode_id:
            try:
                self._superseder(
                    str(agent_id).strip(),
                    old_episode_id,
                    successor_episode_id=created_episode_id,
                )
            except Exception as exc:  # noqa: BLE001 - native memory adapter boundary
                try:
                    self._superseder(str(agent_id).strip(), created_episode_id)
                except Exception:
                    # The native authority remains observable and repairable;
                    # never invent a plugin-side tombstone as a second truth.
                    pass
                raise CompanionPreferencePersistenceError(
                    "Could not supersede the previous native preference memory."
                ) from exc
        receipt = self._receipt(
            agent_id,
            operation="correct" if old_episode_id else "create",
            preference_kind=normalized_kind,
            episode_id=created_episode_id,
            superseded_episode_id=old_episode_id,
        )
        projected = self.project(agent_id)
        preference = next(
            (
                item
                for item in list(projected.get("cards") or [])
                if str(item.get("episodeId") or "") == created_episode_id
            ),
            {},
        )
        return {"preference": deepcopy(preference), "receipt": receipt}

    def delete(self, agent_id: str, *, preference_kind: str) -> dict[str, Any]:
        if self._superseder is None:
            raise CompanionPreferencePersistenceError(
                "Native Agent episodic memory is unavailable."
            )
        normalized_kind = _normalize_kind(preference_kind)
        current = self.project(agent_id)
        existing = next(
            (
                item
                for item in list(current.get("cards") or [])
                if str(item.get("preferenceKind") or "") == normalized_kind
            ),
            None,
        )
        if not existing:
            return {"preferenceKind": normalized_kind, "deleted": False}
        episode_id = str(existing.get("episodeId") or "").strip()
        try:
            self._superseder(str(agent_id).strip(), episode_id)
        except Exception as exc:  # noqa: BLE001 - native memory adapter boundary
            raise CompanionPreferencePersistenceError(
                "Could not delete the native preference memory."
            ) from exc
        receipt = self._receipt(
            agent_id,
            operation="delete",
            preference_kind=normalized_kind,
            episode_id=episode_id,
        )
        return {
            "preferenceKind": normalized_kind,
            "episodeId": episode_id,
            "deleted": True,
            "receipt": receipt,
        }


__all__ = [
    "CompanionPreferenceError",
    "CompanionPreferenceManager",
    "CompanionPreferencePersistenceError",
    "PREFERENCE_ENVELOPE_PREFIX",
    "PREFERENCE_ORDER",
    "encode_companion_preference_episode",
    "expression_preferences",
    "normalize_companion_preference_value",
    "project_companion_preferences",
]
