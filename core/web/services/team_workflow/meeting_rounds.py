"""Append-only meeting round service with closure artifacts.

Closing a meeting round always produces a ``MeetingDigest``, at least one
``DecisionRecord``, and one ``PersonalMemoryCandidate`` for every participating
agent.  Repeated close/recovery is idempotent: identical inputs reuse the
existing artifacts instead of duplicating them.  No chat room or research
runtime is involved.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.infrastructure import developer_sandbox
from core.research.workflow.contracts import (
    ContractValidationError,
    DecisionRecord,
    MeetingDigest,
    MeetingRound,
    scope_hash_for,
)

SCHEMA_VERSION = 1
DEFAULT_MODE = "formal"
_LOCK = threading.RLock()
_SCOPE_FIELDS = ("program", "theme", "campaign", "question", "branch", "workflow")

PROJECT_ROOT = Path(__file__).resolve().parents[4]


class ResearchMeetingRoundError(RuntimeError):
    """Base error for meeting round persistence."""


class ResearchMeetingRoundNotFoundError(ResearchMeetingRoundError):
    """Raised when a meeting round does not exist."""


def _project_root() -> Path:
    return Path(PROJECT_ROOT)


def _safe_team_id(team_id: str) -> str:
    return (
        "".join(
            character if character.isalnum() or character in "._-" else "_"
            for character in str(team_id or "")
        )[:96]
        or "team"
    )


def _team_workspace_root(team_id: str) -> Path:
    return developer_sandbox.seeded_sandbox_workspace_path(
        _project_root(),
        "teams",
        _safe_team_id(team_id),
    )


def _kind_path(team_id: str, kind: str) -> Path:
    return _team_workspace_root(team_id) / "research_workflow" / f"{kind}.jsonl"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ResearchMeetingRoundError(
                f"Invalid meeting round JSONL at line {line_number}."
            ) from exc
        if not isinstance(payload, dict):
            raise ResearchMeetingRoundError(
                f"Invalid meeting round record at line {line_number}."
            )
        records.append(payload)
    return records


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    line = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(existing)
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def _resolve_scope(payload: Mapping[str, Any]) -> dict[str, str]:
    identity: dict[str, str] = {}
    for field in _SCOPE_FIELDS:
        value = str(payload.get(field) or "").strip()
        if not value:
            raise ContractValidationError(
                f"scope requires a non-empty '{field}' field"
            )
        identity[field] = value
    agent_id = str(payload.get("agentId") or "").strip()
    if not agent_id:
        raise ContractValidationError("scope requires a non-empty agentId")
    mode = str(payload.get("mode") or "").strip().lower() or DEFAULT_MODE
    if mode not in {"formal", "dev", "platform"}:
        raise ContractValidationError(f"unsupported scope mode: {mode}")
    scope_hash = scope_hash_for(**identity, agent_id=agent_id, mode=mode)
    return {**identity, "agentId": agent_id, "mode": mode, "scopeHash": scope_hash}


def _latest_by_id(records: list[dict[str, Any]], field: str, record_id: str) -> dict[str, Any] | None:
    matched = [record for record in records if str(record.get(field) or "") == record_id]
    return matched[-1] if matched else None


def _rounds_path(team_id: str) -> Path:
    return _kind_path(team_id, "meeting_rounds")


def _digests_path(team_id: str) -> Path:
    return _kind_path(team_id, "meeting_digests")


def _decisions_path(team_id: str) -> Path:
    return _kind_path(team_id, "decision_records")


def _meeting_definition(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: record.get(key)
        for key in (
            "meetingRoundId",
            "program",
            "theme",
            "campaign",
            "question",
            "branch",
            "workflow",
            "agentId",
            "mode",
            "scopeHash",
            "meetingType",
            "participants",
            "discussionItemRefs",
            "status",
        )
    }


def _closure_hash(payload: Mapping[str, Any]) -> str:
    return _stable_hash(
        {
            "summary": str(payload.get("summary") or "").strip(),
            "discussionTopics": list(payload.get("discussionTopics") or []),
            "decisions": list(payload.get("decisions") or []),
            "closedBy": str(payload.get("closedBy") or "").strip(),
            "memoryClass": str(payload.get("memoryClass") or "personal_reflection"),
            "memorySummaries": dict(payload.get("memorySummaries"))
            if isinstance(payload.get("memorySummaries"), Mapping)
            else {},
            "reusePolicy": str(payload.get("reusePolicy") or "advisory_only"),
            "evidenceStatus": str(payload.get("evidenceStatus") or "unverified"),
            "accepted": bool(payload.get("accepted")),
        }
    )


def create_meeting_round(team_id: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Create one append-only meeting round with an explicit participant list."""
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    request = dict(payload) if isinstance(payload, Mapping) else {}
    scope = _resolve_scope(request)
    now = _utc_now()
    requested_status = str(request.get("status") or "open").strip().lower()
    if requested_status != "open":
        raise ContractValidationError(
            "a meeting round must be created open and closed through close_meeting_round"
        )
    meeting_round_id = (
        str(request.get("meetingRoundId") or "").strip()
        or f"meeting-{_stable_hash({'scopeHash': scope['scopeHash'], 'meetingType': str(request.get('meetingType') or ''), 'startedAt': now})[:16]}"
    )
    record: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "meetingRoundId": meeting_round_id,
        **scope,
        "meetingType": str(request.get("meetingType") or "hypothesis_review").strip().lower(),
        "participants": [str(item or "").strip() for item in list(request.get("participants") or []) if str(item or "").strip()],
        "discussionItemRefs": [str(item or "").strip() for item in list(request.get("discussionItemRefs") or []) if str(item or "").strip()],
        "status": "open",
        "startedAt": str(request.get("startedAt") or "").strip() or now,
        "closedAt": str(request.get("closedAt") or "").strip(),
        "closedBy": str(request.get("closedBy") or "").strip(),
    }
    if not record["participants"]:
        raise ContractValidationError("a meeting round requires at least one participant")
    parsed = MeetingRound.from_dict(record)
    with _LOCK:
        existing = _latest_by_id(_read_jsonl(_rounds_path(normalized_team_id)), "meetingRoundId", meeting_round_id)
        if existing is not None and existing.get("schemaVersion") is not None:
            if _meeting_definition(existing) != _meeting_definition(record):
                raise ResearchMeetingRoundError(
                    "meeting round id is already bound to different content"
                )
            return {
                "schemaVersion": SCHEMA_VERSION,
                "teamId": normalized_team_id,
                "status": "reused",
                "meetingRound": existing,
                "storagePath": str(_rounds_path(normalized_team_id)),
            }
        _append_jsonl(_rounds_path(normalized_team_id), record)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "status": "created",
        "meetingRound": record,
        "storagePath": str(_rounds_path(normalized_team_id)),
    }


def _build_digest(meeting_round: dict[str, Any], request: dict[str, Any], now: str) -> dict[str, Any]:
    summary = str(request.get("summary") or "").strip()
    if not summary:
        raise ContractValidationError("closing a meeting round requires a summary")
    digest_id = f"digest-{_stable_hash({'meetingRoundId': meeting_round['meetingRoundId'], 'scopeHash': meeting_round['scopeHash'], 'summary': summary})[:16]}"
    return {
        "schemaVersion": SCHEMA_VERSION,
        "digestId": digest_id,
        "meetingRoundId": str(meeting_round["meetingRoundId"]),
        "scopeHash": str(meeting_round["scopeHash"]),
        "summary": summary,
        "participantAgentIds": list(meeting_round.get("participants") or []),
        "discussionTopics": [
            str(item or "").strip() for item in list(request.get("discussionTopics") or []) if str(item or "").strip()
        ],
        "decisionRefs": [
            str(item or "").strip() for item in list(request.get("decisionRefs") or []) if str(item or "").strip()
        ],
        "closedBy": str(request.get("closedBy") or "").strip(),
        "createdAt": now,
    }


def _build_decision(meeting_round: dict[str, Any], raw: Mapping[str, Any], now: str) -> dict[str, Any]:
    decision = str(raw.get("decision") or "").strip().lower()
    if not decision:
        raise ContractValidationError("each decision requires a decision kind")
    candidate_refs = [str(item or "").strip() for item in list(raw.get("candidateRefs") or []) if str(item or "").strip()]
    evidence_refs = [str(item or "").strip() for item in list(raw.get("evidenceRefs") or []) if str(item or "").strip()]
    decision_id = f"decision-{_stable_hash({'meetingRoundId': meeting_round['meetingRoundId'], 'scopeHash': meeting_round['scopeHash'], 'decision': decision, 'candidateRefs': candidate_refs, 'evidenceRefs': evidence_refs})[:16]}"
    return {
        "schemaVersion": SCHEMA_VERSION,
        "decisionId": decision_id,
        "meetingRoundId": str(meeting_round["meetingRoundId"]),
        "scopeHash": str(meeting_round["scopeHash"]),
        "decision": decision,
        "rationale": str(raw.get("rationale") or "").strip(),
        "decidedBy": str(raw.get("decidedBy") or "").strip(),
        "candidateRefs": candidate_refs,
        "evidenceRefs": evidence_refs,
        "status": str(raw.get("status") or "adopted").strip().lower(),
        "createdAt": now,
    }


def close_meeting_round(
    team_id: str,
    meeting_round_id: str,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Close one meeting round, producing digest, decisions, and memory candidates.

    Idempotent: repeating close with the same content reuses the already
    appended artifacts and the closed round record.
    """
    from core.web.services.team_workflow.personal_memory_candidates import (
        record_personal_memory_candidates,
    )
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_round_id = str(meeting_round_id or "").strip()
    if not normalized_round_id:
        raise ResearchMeetingRoundError("Meeting round id is required.")
    request = dict(payload) if isinstance(payload, Mapping) else {}
    with _LOCK:
        records = _read_jsonl(_rounds_path(normalized_team_id))
        meeting_round = _latest_by_id(records, "meetingRoundId", normalized_round_id)
        if meeting_round is None:
            raise ResearchMeetingRoundNotFoundError("Meeting round not found.")
        if str(meeting_round.get("status") or "") == "closed":
            if str(meeting_round.get("closureHash") or "") != _closure_hash(request):
                raise ResearchMeetingRoundError(
                    "closed meeting round cannot be reused with different closure content"
                )
            digest_id = str(meeting_round.get("digestId") or "").strip()
            digest = (
                _latest_by_id(_read_jsonl(_digests_path(normalized_team_id)), "digestId", digest_id)
                if digest_id
                else None
            )
            decision_refs = list(meeting_round.get("decisionRefs") or [])
            decisions = [
                item
                for item in _read_jsonl(_decisions_path(normalized_team_id))
                if str(item.get("decisionId") or "") in decision_refs
            ]
            return {
                "schemaVersion": SCHEMA_VERSION,
                "teamId": normalized_team_id,
                "status": "reused",
                "closed": True,
                "meetingRound": meeting_round,
                "digest": digest or (meeting_round.get("digest") or {}),
                "decisions": decisions,
                "personalMemoryCandidateRefs": list(
                    meeting_round.get("personalMemoryCandidateRefs") or []
                ),
                "storagePath": str(_rounds_path(normalized_team_id)),
            }
    participants = [str(item or "").strip() for item in list(meeting_round.get("participants") or []) if str(item or "").strip()]
    now = _utc_now()
    digest = _build_digest(meeting_round, request, now)
    raw_decisions = [item for item in list(request.get("decisions") or []) if isinstance(item, Mapping)]
    if not raw_decisions:
        raise ContractValidationError(
            "closing a meeting round requires at least one decision record"
        )
    decisions = [_build_decision(meeting_round, item, now) for item in raw_decisions]
    for decision in decisions:
        DecisionRecord.from_dict(decision)
    digest["decisionRefs"] = [str(item.get("decisionId") or "") for item in decisions]
    MeetingDigest.from_dict(digest)
    with _LOCK:
        appended_digest = _latest_by_id(
            _read_jsonl(_digests_path(normalized_team_id)),
            "digestId",
            digest["digestId"],
        )
        if appended_digest is None:
            _append_jsonl(_digests_path(normalized_team_id), digest)
        else:
            digest = appended_digest
        appended_decisions: list[dict[str, Any]] = []
        for decision in decisions:
            existing_decision = _latest_by_id(
                _read_jsonl(_decisions_path(normalized_team_id)),
                "decisionId",
                decision["decisionId"],
            )
            if existing_decision is None:
                _append_jsonl(_decisions_path(normalized_team_id), decision)
            else:
                decision = existing_decision
            appended_decisions.append(decision)
        decisions = appended_decisions
        memory_result = record_personal_memory_candidates(
            normalized_team_id,
            scope_payload={
                "program": meeting_round.get("program") or "",
                "theme": meeting_round.get("theme") or "",
                "campaign": meeting_round.get("campaign") or "",
                "question": meeting_round.get("question") or "",
                "branch": meeting_round.get("branch") or "",
                "workflow": meeting_round.get("workflow") or "",
                "agentId": meeting_round.get("agentId") or "",
                "mode": meeting_round.get("mode") or "",
            },
            agents=participants,
            source_refs=[
                f"meeting_round:{normalized_round_id}",
                f"meeting_digest:{digest['digestId']}",
                *[f"decision_record:{item['decisionId']}" for item in decisions],
            ],
            memory_class=str(request.get("memoryClass") or "personal_reflection"),
            summaries=request.get("memorySummaries") if isinstance(request.get("memorySummaries"), Mapping) else None,
            reuse_policy=str(request.get("reusePolicy") or "advisory_only"),
            evidence_status=str(request.get("evidenceStatus") or "unverified"),
            accepted=bool(request.get("accepted")),
        )
        closed_record = dict(meeting_round)
        closed_record["status"] = "closed"
        closed_record["closedAt"] = now
        closed_record["closedBy"] = str(request.get("closedBy") or "").strip()
        closed_record["digestId"] = digest["digestId"]
        closed_record["decisionRefs"] = [str(item.get("decisionId") or "") for item in decisions]
        closed_record["personalMemoryCandidateRefs"] = [
            {
                "memoryCandidateId": str(item.get("memoryCandidateId") or ""),
                "agentId": str(item.get("agentId") or ""),
                "theme": str(item.get("theme") or ""),
                "targetTheme": str(item.get("targetTheme") or ""),
            }
            for item in memory_result["candidates"]
        ]
        closed_record["closureHash"] = _closure_hash(request)
        closed_record["updatedAt"] = now
        MeetingRound.from_dict(closed_record)
        _append_jsonl(_rounds_path(normalized_team_id), closed_record)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "status": "created",
        "closed": True,
        "meetingRound": closed_record,
        "digest": digest,
        "decisions": decisions,
        "personalMemoryCandidateRefs": closed_record[
            "personalMemoryCandidateRefs"
        ],
        "memorySummary": {
            "createdCount": memory_result["createdCount"],
            "reusedCount": memory_result["reusedCount"],
        },
        "storagePath": str(_rounds_path(normalized_team_id)),
    }


def list_meeting_rounds(team_id: str) -> dict[str, Any]:
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    with _LOCK:
        records = _read_jsonl(_rounds_path(normalized_team_id))
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        latest[str(record.get("meetingRoundId") or "")] = record
    rows = sorted(latest.values(), key=lambda item: str(item.get("startedAt") or ""))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "meetingCount": len(rows),
        "meetings": rows,
        "storagePath": str(_rounds_path(normalized_team_id)),
    }


def get_meeting_round(team_id: str, meeting_round_id: str) -> dict[str, Any]:
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_round_id = str(meeting_round_id or "").strip()
    with _LOCK:
        records = _read_jsonl(_rounds_path(normalized_team_id))
        record = _latest_by_id(records, "meetingRoundId", normalized_round_id)
    if record is None:
        raise ResearchMeetingRoundNotFoundError("Meeting round not found.")
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "meetingRound": record,
        "storagePath": str(_rounds_path(normalized_team_id)),
    }
