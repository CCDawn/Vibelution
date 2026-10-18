"""Reviewed Companion preferences backed by native Agent episodic memory.

The native Agent episodic event remains the only preference authority. This
module validates a closed, versioned envelope, derives bounded projections and
coordinates native supersede operations plus value-free reconciliation
receipts. It does not own a second preference store and never calls an LLM.

The same module owns the confirmable preference-proposal state machine and the
Agent-scoped dialogue settings. Proposals store references only (no user text
copy); only an accepted proposal may reach native episodic memory through the
existing manager, and rejected/ignored proposals never change the character.
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

PREFERENCE_PROPOSAL_SCHEMA_VERSION = 1
PREFERENCE_PROPOSAL_STATUSES = ("pending", "accepted", "rejected", "expired")
PREFERENCE_PROPOSAL_PENDING_TTL_DAYS = 7
PREFERENCE_PROPOSAL_LEDGER_LIMIT = 20
# Dialogue preference settings surface (PRD 32.11): stable backend enums the
# Companion UI maps to human behaviour words; the words never enter storage.
COMPANION_DIALOGUE_SETTINGS_SCHEMA_VERSION = 1
SPEAKING_INITIATIVES = ("restrained", "natural", "talkative")
QUESTION_INITIATIVES = ("few", "natural", "proactive")
PREFERENCE_PROPOSAL_MODES = ("ask_first", "manual_only")

# Proposal types (PRD 32.9 closed enum) mapped onto the reviewed native
# preference kinds they may finalize into once the user accepts.
PREFERENCE_PROPOSAL_TYPE_TO_KIND = {
    "verbosity": "response_length",
    "question_initiative": "question_tolerance",
    "address": "address",
    "humor": "humor",
    "proactive_contact": "proactive_frequency",
}

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


def normalize_companion_preference_proposal(
    preference_type: str,
    candidate_value: object,
) -> tuple[str, Any]:
    """Validate one proposal candidate against its closed native target."""

    normalized_type = str(preference_type or "").strip().lower()
    if normalized_type not in PREFERENCE_PROPOSAL_TYPE_TO_KIND:
        raise CompanionPreferenceError(
            f"Unsupported Companion preference proposal type: {preference_type}"
        )
    native_kind = PREFERENCE_PROPOSAL_TYPE_TO_KIND[normalized_type]
    try:
        value = normalize_companion_preference_value(native_kind, candidate_value)
    except CompanionPreferenceError as exc:
        raise CompanionPreferenceError(
            f"Unsupported candidate value for Companion preference proposal "
            f"{normalized_type}: {candidate_value}"
        ) from exc
    return normalized_type, value


def _proposal_row(row: Mapping[str, Any]) -> dict[str, Any] | None:
    if not isinstance(row, Mapping):
        return None
    proposal_id = str(row.get("proposalId") or "").strip()
    agent_id = str(row.get("agentId") or "").strip()
    preference_type = str(row.get("preferenceType") or "").strip().lower()
    status = str(row.get("status") or "").strip().lower()
    if (
        not proposal_id
        or not agent_id
        or preference_type not in PREFERENCE_PROPOSAL_TYPE_TO_KIND
        or status not in PREFERENCE_PROPOSAL_STATUSES
    ):
        return None
    try:
        _, value = normalize_companion_preference_proposal(
            preference_type, row.get("candidateValue")
        )
    except CompanionPreferenceError:
        return None
    return {
        "proposalId": proposal_id,
        "agentId": agent_id,
        "preferenceType": preference_type,
        "candidateValue": deepcopy(value),
        "sourceTurnId": str(row.get("sourceTurnId") or "").strip(),
        "status": status,
        "receiptId": str(row.get("receiptId") or "").strip(),
        "createdAt": str(row.get("createdAt") or "").strip(),
        "expiresAt": str(row.get("expiresAt") or "").strip(),
        "decidedAt": str(row.get("decidedAt") or "").strip(),
        "updatedAt": str(row.get("updatedAt") or "").strip(),
        "transitionReason": str(row.get("transitionReason") or "").strip(),
    }


def _iso_timestamp(value: object) -> str:
    from datetime import datetime

    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=None)
    return parsed.isoformat()


def _proposal_expired(row: Mapping[str, Any], *, now_iso: str) -> bool:
    if str(row.get("status") or "") != "pending":
        return False
    expires_at = _iso_timestamp(row.get("expiresAt"))
    if not expires_at or not now_iso:
        return False
    return str(now_iso) >= expires_at


def project_companion_preference_proposals(
    rows: Iterable[Mapping[str, Any]],
    *,
    agent_id: str,
    now_iso: str = "",
) -> dict[str, Any]:
    """Fold the append-only proposal ledger into its latest-row projection.

    Later rows win per ``proposalId``; stale ``pending`` rows are reported as
    ``expired`` (lazily, without rewriting history). The projection contains
    references and bounded enum values only - never user text.
    """

    normalized_agent_id = str(agent_id or "").strip()
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        decoded = _proposal_row(row)
        if decoded is None or decoded["agentId"] != normalized_agent_id:
            continue
        latest[decoded["proposalId"]] = decoded
    proposals: list[dict[str, Any]] = []
    expired_ids: list[str] = []
    for proposal in latest.values():
        if _proposal_expired(proposal, now_iso=now_iso):
            expired_ids.append(proposal["proposalId"])
            proposals.append({**proposal, "status": "expired", "transitionReason": "ignored"})
        else:
            proposals.append(deepcopy(proposal))
    proposals.sort(key=lambda item: (item["status"] != "pending", item["createdAt"]))
    return {
        "schemaVersion": PREFERENCE_PROPOSAL_SCHEMA_VERSION,
        "proposals": proposals[:PREFERENCE_PROPOSAL_LEDGER_LIMIT],
        "lazilyExpiredProposalIds": expired_ids,
    }


def new_companion_preference_proposal_row(
    agent_id: str,
    *,
    preference_type: str,
    candidate_value: object,
    source_turn_id: str,
    now_iso: str,
    ttl_days: int = PREFERENCE_PROPOSAL_PENDING_TTL_DAYS,
) -> dict[str, Any]:
    """Build one pending proposal row; callers append it to the ledger."""

    from datetime import datetime, timedelta

    normalized_type, value = normalize_companion_preference_proposal(
        preference_type, candidate_value
    )
    normalized_turn_id = str(source_turn_id or "").strip()
    if not normalized_turn_id:
        raise CompanionPreferenceError(
            "Companion preference proposals require the native user Turn."
        )
    created = _iso_timestamp(now_iso)
    if not created:
        raise CompanionPreferenceError(
            "Companion preference proposals require an ISO timestamp."
        )
    parsed = datetime.fromisoformat(created)
    expires = parsed + timedelta(days=max(1, int(ttl_days)))
    if parsed.tzinfo is not None:
        expires = expires.astimezone(parsed.tzinfo)
    return {
        "proposalId": f"companion-preference-proposal:{uuid.uuid4().hex[:20]}",
        "agentId": str(agent_id or "").strip(),
        "preferenceType": normalized_type,
        "candidateValue": deepcopy(value),
        "sourceTurnId": normalized_turn_id,
        "status": "pending",
        "receiptId": "",
        "createdAt": created,
        "expiresAt": expires.isoformat(),
        "decidedAt": "",
        "updatedAt": created,
        "transitionReason": "",
    }


def companion_preference_proposal_transition_row(
    proposal: Mapping[str, Any],
    *,
    status: str,
    now_iso: str,
    receipt_id: str = "",
    transition_reason: str = "",
) -> dict[str, Any]:
    """Build the ledger row for one proposal state transition."""

    normalized_status = str(status or "").strip().lower()
    if normalized_status not in PREFERENCE_PROPOSAL_STATUSES:
        raise CompanionPreferenceError(
            f"Unsupported Companion preference proposal status: {status}"
        )
    current = str(proposal.get("status") or "").strip().lower()
    allowed = {
        "pending": {"accepted", "rejected", "expired"},
        "accepted": set(),
        "rejected": set(),
        "expired": set(),
    }
    if normalized_status == current:
        raise CompanionPreferenceError(
            "Companion preference proposal is already decided."
        )
    if normalized_status not in allowed.get(current, set()):
        raise CompanionPreferenceError(
            f"Companion preference proposal cannot move from {current} to {normalized_status}."
        )
    return {
        **deepcopy(dict(proposal)),
        "status": normalized_status,
        "receiptId": str(receipt_id or proposal.get("receiptId") or "").strip(),
        "decidedAt": (
            str(now_iso) if normalized_status in {"accepted", "rejected"} else ""
        ),
        "updatedAt": str(now_iso),
        "transitionReason": str(transition_reason or "")[:120],
    }


def normalize_companion_dialogue_settings(
    payload: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Normalize the three Agent-scoped dialogue settings with defaults."""

    source = payload if isinstance(payload, Mapping) else {}
    speaking = str(source.get("speakingInitiative") or "natural").strip().lower()
    question = str(source.get("questionInitiative") or "natural").strip().lower()
    proposal_mode = str(
        source.get("preferenceProposalMode") or "ask_first"
    ).strip().lower()
    return {
        "schemaVersion": COMPANION_DIALOGUE_SETTINGS_SCHEMA_VERSION,
        "speakingInitiative": (
            speaking if speaking in SPEAKING_INITIATIVES else "natural"
        ),
        "questionInitiative": (
            question if question in QUESTION_INITIATIVES else "natural"
        ),
        "preferenceProposalMode": (
            proposal_mode if proposal_mode in PREFERENCE_PROPOSAL_MODES else "ask_first"
        ),
        "updatedAt": str(source.get("updatedAt") or "").strip(),
    }


def dialogue_settings_preferences(settings: Mapping[str, Any] | None) -> dict[str, Any]:
    """Map dialogue settings onto the bounded expression contract inputs."""

    normalized = normalize_companion_dialogue_settings(settings)
    question = normalized["questionInitiative"]
    speaking = normalized["speakingInitiative"]
    return {
        "questionsAllowed": question != "few",
        "questionInitiative": question,
        "speakingInitiative": speaking,
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
    "COMPANION_DIALOGUE_SETTINGS_SCHEMA_VERSION",
    "PREFERENCE_ENVELOPE_PREFIX",
    "PREFERENCE_ORDER",
    "PREFERENCE_PROPOSAL_LEDGER_LIMIT",
    "PREFERENCE_PROPOSAL_MODES",
    "PREFERENCE_PROPOSAL_PENDING_TTL_DAYS",
    "PREFERENCE_PROPOSAL_SCHEMA_VERSION",
    "PREFERENCE_PROPOSAL_STATUSES",
    "PREFERENCE_PROPOSAL_TYPE_TO_KIND",
    "QUESTION_INITIATIVES",
    "SPEAKING_INITIATIVES",
    "CompanionPreferenceError",
    "CompanionPreferenceManager",
    "CompanionPreferencePersistenceError",
    "companion_preference_proposal_transition_row",
    "dialogue_settings_preferences",
    "encode_companion_preference_episode",
    "expression_preferences",
    "new_companion_preference_proposal_row",
    "normalize_companion_dialogue_settings",
    "normalize_companion_preference_proposal",
    "normalize_companion_preference_value",
    "project_companion_preference_proposals",
    "project_companion_preferences",
]
