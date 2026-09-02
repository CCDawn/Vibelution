"""Append-only meeting round service with closure artifacts.

Closing a meeting round always produces a ``MeetingDigest``, at least one
``DecisionRecord``, and one ``PersonalMemoryCandidate`` for every participating
agent.  Repeated close/recovery is idempotent: identical inputs reuse the
existing artifacts instead of duplicating them.

Schema v2 (requirements §15.1/§15.3) adds the four-state lifecycle
``open -> summarizing -> awaiting_approval -> closed``: a room-bound meeting
(hypothesis-first ``hypothesis_review`` rounds) is summarized from its linked
chat-room messages into a Coordinator digest draft, a human approves the
draft, and only then are the closure artifacts written.  The approval gate
enforces the §15.4 completion conditions fail-closed (disagreements, risks,
and action items from the source messages must survive into the digest;
decisions need evidence refs; action items need role owners; the digest must
link back to real room messages).  Legacy non-room-bound meetings keep the
original direct ``close_meeting_round`` path.  No research runtime is
involved; chat-room access is read-only except for the binding metadata the
runtime writes through ``bind_meeting_chat_room_round``.

For model-backed drafts, the Coordinator owns an open Markdown narrative.
Explicit meeting-protocol facts remain source-owned in ``factLedger`` and are
projected into the legacy top-level buckets for current consumers. The model
is not asked to regenerate those facts.

DEV fixture convention: the deterministic digest drafter and the closure
gate share a marker convention over room message content — ``AGREE:``,
``DISAGREE:``, ``RISK:``, ``ACTION: <ownerRoleId> | <action>``,
``KNOWLEDGE:`` — and a bare ``pass`` marks a speaker with no new content.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
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
from core.web.services.team_workflow.meeting_message_payload import (
    structured_protocol_from_message,
)

SCHEMA_VERSION = 2
LEGACY_DIGEST_SCHEMA_VERSION = 1
DEFAULT_MODE = "formal"
_LOCK = threading.RLock()
# Bounded waits for the module lock (2026-09 ghost-lock incident): every
# acquirer must either enter within its budget or fail with a structured
# timeout instead of blocking its thread forever.  Writers persist under the
# lock (append + fsync) and get the larger budget; readers only parse JSONL.
DEFAULT_WRITE_LOCK_TIMEOUT_SECONDS = 60.0
DEFAULT_READ_LOCK_TIMEOUT_SECONDS = 10.0
_WRITE_LOCK_TIMEOUT_ENV = "VIBELUTION_MEETING_ROUNDS_WRITE_LOCK_TIMEOUT_SECONDS"
_READ_LOCK_TIMEOUT_ENV = "VIBELUTION_MEETING_ROUNDS_READ_LOCK_TIMEOUT_SECONDS"
_SCOPE_FIELDS = ("program", "theme", "campaign", "question", "branch", "workflow")

_MARKER_PREFIXES = (
    "AGREE",
    "DISAGREE",
    "RISK",
    "ACTION",
    "KNOWLEDGE",
    "CANDIDATE",
    "EVIDENCE_REQUEST",
)
_PASS_TOKENS = {"pass", "pass.", "pass。"}
_MARKER_LINE_PATTERN = re.compile(
    r"^(?:[-*+]\s+)?(?P<emphasis>\*\*|__)?(?P<marker>[A-Z_]+)\s*:\s*(?P<value>.+)$",
    re.IGNORECASE,
)

PROJECT_ROOT = Path(__file__).resolve().parents[4]


class ResearchMeetingRoundError(RuntimeError):
    """Base error for meeting round persistence."""


class ResearchMeetingRoundNotFoundError(ResearchMeetingRoundError):
    """Raised when a meeting round does not exist."""


class MeetingRoundsLockTimeoutError(ResearchMeetingRoundError):
    """Raised when acquiring the module lock exceeds its bounded wait.

    Carries the waiter identity (``caller``) and the budget it exceeded
    (``waited_seconds``) so the route layer can surface a structured 503 and
    the timeout event can pin down where the next ghost-lock wait happened.
    """

    code = "meeting_rounds_lock_timeout"

    def __init__(self, *, caller: str, timeout_seconds: float) -> None:
        self.caller = str(caller)
        self.waited_seconds = float(timeout_seconds)
        super().__init__(
            f"meeting rounds lock wait exceeded {self.waited_seconds:.1f}s "
            f"(caller={self.caller})"
        )


def _lock_timeout_seconds(env_var: str, default_seconds: float) -> float:
    raw = str(os.environ.get(env_var) or "").strip()
    if not raw:
        return default_seconds
    try:
        value = float(raw)
    except ValueError:
        return default_seconds
    return value if value > 0 else default_seconds


def _record_lock_timeout_scene(exc: MeetingRoundsLockTimeoutError) -> None:
    """Best-effort ghost-lock evidence: waiter identity and wait budget."""

    try:
        from core.web.services.runtime_scene_service import (
            record_runtime_scene_event_quietly,
        )

        record_runtime_scene_event_quietly(
            "team_workflow",
            "meeting_rounds_lock",
            "meeting_rounds.lock_timeout",
            message="Bounded meeting rounds lock wait expired without entering.",
            level="error",
            outcome="failed",
            fields={
                "caller": exc.caller,
                "waitedSeconds": exc.waited_seconds,
            },
            lifecycle=True,
        )
    except Exception:  # noqa: BLE001 - diagnostics must never alter control flow
        return


@contextmanager
def _bounded_lock(caller: str, *, timeout_seconds: float) -> Iterator[None]:
    # RLock reentrancy is preserved: a same-thread reacquire returns True
    # immediately, and each enter releases exactly once.
    if not _LOCK.acquire(timeout=timeout_seconds):
        exc = MeetingRoundsLockTimeoutError(
            caller=caller, timeout_seconds=timeout_seconds
        )
        _record_lock_timeout_scene(exc)
        raise exc
    try:
        yield
    finally:
        _LOCK.release()


@contextmanager
def _write_lock(caller: str) -> Iterator[None]:
    with _bounded_lock(
        caller,
        timeout_seconds=_lock_timeout_seconds(
            _WRITE_LOCK_TIMEOUT_ENV, DEFAULT_WRITE_LOCK_TIMEOUT_SECONDS
        ),
    ):
        yield


@contextmanager
def _read_lock(caller: str) -> Iterator[None]:
    with _bounded_lock(
        caller,
        timeout_seconds=_lock_timeout_seconds(
            _READ_LOCK_TIMEOUT_ENV, DEFAULT_READ_LOCK_TIMEOUT_SECONDS
        ),
    ):
        yield


def _project_root() -> Path:
    return Path(PROJECT_ROOT)


def _safe_team_id(team_id: str) -> str:
    from core.web.services.team_workflow.storage_ids import safe_storage_component

    return safe_storage_component(team_id, fallback="team")


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
    from core.web.services.team_workflow.storage_durability import read_jsonl_tolerant

    return read_jsonl_tolerant(path)


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    from core.web.services.team_workflow.storage_durability import append_jsonl_locked

    append_jsonl_locked(path, record)


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


def _normalized_str_list(value: Any) -> list[str]:
    return [str(item or "").strip() for item in list(value or []) if str(item or "").strip()]


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
            "stage",
            "roundType",
            "agenda",
            "agendaQuestions",
            "agendaRules",
            "rounds",
            "participantRoleIds",
            "teamRoleContractVersion",
            "participantPolicyVersion",
            "roleContractFingerprint",
            "participantRoleSnapshot",
            "resolutionHash",
            "inputArtifactRefs",
            "linkedChatRoomId",
            "modelInvocationReceiptAuthority",
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


def _approval_closure_hash(payload: Mapping[str, Any], digest_draft: Mapping[str, Any]) -> str:
    return _stable_hash(
        {
            "closure": _closure_hash(payload),
            "digestDraft": _stable_hash(dict(digest_draft)),
        }
    )


def create_meeting_round(team_id: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Create one append-only meeting round with an explicit participant list."""
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    request = dict(payload) if isinstance(payload, Mapping) else {}
    scope = _resolve_scope(request)
    now = _utc_now()
    server_created_at_ms = int(
        datetime.fromisoformat(now.replace("Z", "+00:00")).timestamp() * 1000
    )
    requested_status = str(request.get("status") or "open").strip().lower()
    if requested_status != "open":
        raise ContractValidationError(
            "a meeting round must be created open and closed through close_meeting_round"
        )
    meeting_type = str(request.get("meetingType") or "hypothesis_review").strip().lower()
    candidate_authority = str(request.get("candidateAuthority") or "").strip().lower()
    if candidate_authority not in {
        "",
        "exploratory_draft",
        "formal_grounded_candidate",
    }:
        raise ContractValidationError("candidateAuthority is invalid")
    try:
        revision_ordinal = int(request.get("revisionOrdinal") or 0)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError("revisionOrdinal must be an integer") from exc
    if revision_ordinal < 0:
        raise ContractValidationError("revisionOrdinal must be non-negative")
    participant_role_ids = _normalized_str_list(request.get("participantRoleIds"))
    participant_role_snapshot = [
        dict(item) if isinstance(item, Mapping) else item
        for item in list(request.get("participantRoleSnapshot") or [])
    ]
    participant_contract_seed = {
        "teamRoleContractVersion": request.get("teamRoleContractVersion") or 0,
        "participantPolicyVersion": request.get("participantPolicyVersion") or 0,
        "roleContractFingerprint": str(
            request.get("roleContractFingerprint") or ""
        ).strip().lower(),
        "participantRoleIds": participant_role_ids,
        "participantRoleSnapshot": participant_role_snapshot,
        "resolutionHash": str(request.get("resolutionHash") or "").strip().lower(),
    }
    meeting_round_id = (
        str(request.get("meetingRoundId") or "").strip()
        or f"meeting-{_stable_hash({'scopeHash': scope['scopeHash'], 'meetingType': meeting_type, 'startedAt': now, **participant_contract_seed})[:16]}"
    )
    record: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "meetingRoundId": meeting_round_id,
        **scope,
        "meetingType": meeting_type,
        "participants": _normalized_str_list(request.get("participants")),
        "discussionItemRefs": _normalized_str_list(request.get("discussionItemRefs")),
        "status": "open",
        "startedAt": str(request.get("startedAt") or "").strip() or now,
        "serverCreatedAtMs": server_created_at_ms,
        "closedAt": "",
        "closedBy": "",
        "stage": str(request.get("stage") or "").strip().lower(),
        "roundType": str(request.get("roundType") or "").strip().lower(),
        "agenda": _normalized_str_list(request.get("agenda")),
        "agendaQuestions": _normalized_str_list(request.get("agendaQuestions")),
        "agendaRules": _normalized_str_list(request.get("agendaRules")),
        "rounds": request.get("rounds") if request.get("rounds") is not None else 3,
        "participantRoleIds": participant_role_ids,
        "teamRoleContractVersion": request.get("teamRoleContractVersion")
        if request.get("teamRoleContractVersion") is not None
        else 0,
        "participantPolicyVersion": request.get("participantPolicyVersion")
        if request.get("participantPolicyVersion") is not None
        else 0,
        "roleContractFingerprint": str(
            request.get("roleContractFingerprint") or ""
        ).strip().lower(),
        "participantRoleSnapshot": participant_role_snapshot,
        "resolutionHash": str(request.get("resolutionHash") or "").strip().lower(),
        "inputArtifactRefs": _normalized_str_list(request.get("inputArtifactRefs")),
        "linkedChatRoomId": str(request.get("linkedChatRoomId") or "").strip(),
        "chatRoomRoundIds": [],
        **(
            {
                "candidateAuthority": candidate_authority,
                "allowedEvidenceRefs": _normalized_str_list(
                    request.get("allowedEvidenceRefs")
                ),
                "exploratoryDraftRefs": _normalized_str_list(
                    request.get("exploratoryDraftRefs")
                ),
                "knowledgePackageRefs": _normalized_str_list(
                    request.get("knowledgePackageRefs")
                ),
                "revisionOrdinal": revision_ordinal,
            }
            if candidate_authority
            else {}
        ),
        **(
            {
                "modelInvocationReceiptAuthority": dict(
                    request["modelInvocationReceiptAuthority"]
                ),
            }
            if isinstance(request.get("modelInvocationReceiptAuthority"), Mapping)
            else {}
        ),
    }
    if isinstance(record.get("modelInvocationReceiptAuthority"), Mapping):
        from core.web.services.team_workflow.challenge_deadline_policy import (
            derive_meeting_deadline_policy,
        )
        from core.web.services.team_workflow.research_runtime.challenge_turn_policy import (
            current_challenge_task_deadline_at_ms,
        )

        record.update(
            derive_meeting_deadline_policy(
                normalized_team_id,
                record,
                server_created_at_ms=server_created_at_ms,
                outer_deadline_at_ms=current_challenge_task_deadline_at_ms(),
            )
        )
    if not record["participants"]:
        raise ContractValidationError("a meeting round requires at least one participant")
    parsed = MeetingRound.from_dict(record)
    record["rounds"] = parsed.rounds
    with _write_lock("create_meeting_round"):
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


def _ensure_transition_from(
    meeting_round: Mapping[str, Any], expected: str, target: str
) -> None:
    """Pin the exact source status for one lifecycle action (fail closed)."""

    current = str(meeting_round.get("status") or "").strip().lower()
    if current != expected:
        raise ContractValidationError(
            f"meeting status transition {current or '<unknown>'} -> {target} is not allowed"
        )


def _load_meeting_round(normalized_team_id: str, meeting_round_id: str) -> dict[str, Any]:
    records = _read_jsonl(_rounds_path(normalized_team_id))
    meeting_round = _latest_by_id(records, "meetingRoundId", meeting_round_id)
    if meeting_round is None:
        raise ResearchMeetingRoundNotFoundError("Meeting round not found.")
    return meeting_round


def _append_round_record(normalized_team_id: str, record: dict[str, Any]) -> dict[str, Any]:
    MeetingRound.from_dict(record)
    _append_jsonl(_rounds_path(normalized_team_id), record)
    return record


def persist_meeting_discussion_scope(
    team_id: str,
    meeting_round_id: str,
    *,
    discussion_scope: Mapping[str, Any],
    discussion_scope_hash: str,
    scope_authority: str,
) -> dict[str, Any]:
    """Append the canonical discussion-scope projection to one meeting.

    This is the owning write facade used by meeting_runtime; callers cannot
    replace lifecycle fields or create a second MeetingRound identity.
    """

    from core.research.workflow.contracts.discussion_scope import (
        PREFORMAL_CANDIDATE_REVIEW_SCOPE_KIND,
        WorkflowDiscussionScopeV1,
    )
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_meeting_id = str(meeting_round_id or "").strip()
    if (
        isinstance(discussion_scope, Mapping)
        and str(discussion_scope.get("kind") or "").strip()
        == PREFORMAL_CANDIDATE_REVIEW_SCOPE_KIND
    ):
        return persist_preformal_meeting_discussion_scope(
            normalized_team_id,
            normalized_meeting_id,
            discussion_scope=discussion_scope,
            discussion_scope_hash=discussion_scope_hash,
            scope_authority=scope_authority,
        )
    scope = WorkflowDiscussionScopeV1.from_mapping(discussion_scope)
    normalized_hash = str(discussion_scope_hash or "").strip().lower()
    if normalized_hash != scope.scope_hash:
        raise ContractValidationError(
            "discussionScopeHash does not match the discussion scope"
        )
    with _write_lock("persist_meeting_discussion_scope"):
        meeting = _load_meeting_round(normalized_team_id, normalized_meeting_id)
        existing = meeting.get("discussionScope")
        if isinstance(existing, Mapping):
            existing_scope = WorkflowDiscussionScopeV1.from_mapping(existing)
            if existing_scope.key != scope.key:
                raise ContractValidationError(
                    "meeting is already bound to a different discussion scope"
                )
            return meeting
        updated = {
            **meeting,
            "discussionScope": scope.to_dict(),
            "discussionScopeHash": scope.scope_hash,
            "scopeAuthority": str(scope_authority or "").strip(),
            "researchProjectId": scope.researchProjectId,
            "workflowRunId": scope.workflowRunId,
            "workflowNodeId": scope.workflowNodeId,
            "updatedAt": _utc_now(),
        }
        _append_round_record(normalized_team_id, updated)
    return updated


def persist_preformal_meeting_discussion_scope(
    team_id: str,
    meeting_round_id: str,
    *,
    discussion_scope: Mapping[str, Any],
    discussion_scope_hash: str,
    scope_authority: str,
) -> dict[str, Any]:
    """Append an exact preformal candidate binding to a legacy meeting.

    Preformal review meetings intentionally have no formal workflow run.  The
    binding is therefore kept as an append-only projection beside the legacy
    ``MeetingRound`` fields, using the same writer and lifecycle lock as the
    formal scope projection.
    """

    from core.research.workflow.contracts.discussion_scope import (
        PreformalCandidateReviewScopeV1,
    )
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_meeting_id = str(meeting_round_id or "").strip()
    scope = PreformalCandidateReviewScopeV1.from_mapping(discussion_scope)
    normalized_hash = str(discussion_scope_hash or "").strip().lower()
    if normalized_hash != scope.scope_hash:
        raise ContractValidationError(
            "discussionScopeHash does not match the preformal discussion scope"
        )
    with _write_lock("persist_preformal_meeting_discussion_scope"):
        meeting = _load_meeting_round(normalized_team_id, normalized_meeting_id)
        existing = meeting.get("discussionScope")
        if isinstance(existing, Mapping):
            try:
                existing_scope = PreformalCandidateReviewScopeV1.from_mapping(existing)
            except (ContractValidationError, TypeError, ValueError) as exc:
                raise ContractValidationError(
                    "meeting already carries a non-preformal discussion scope"
                ) from exc
            if existing_scope.key != scope.key:
                raise ContractValidationError(
                    "meeting is already bound to a different discussion scope"
                )
            existing_hash = str(
                meeting.get("discussionScopeHash") or ""
            ).strip().lower()
            if existing_hash and existing_hash != scope.scope_hash:
                raise ContractValidationError(
                    "meeting preformal discussionScopeHash does not match its scope"
                )
            return meeting
        updated = {
            **meeting,
            "discussionScope": scope.to_dict(),
            "discussionScopeHash": scope.scope_hash,
            "scopeAuthority": str(scope_authority or "").strip(),
            "preformalDiscussion": True,
            "selectionId": scope.selectionId,
            "candidateId": scope.candidateId,
            "roomId": scope.roomId,
            "updatedAt": _utc_now(),
        }
        _append_round_record(normalized_team_id, updated)
    return updated


def persist_challenge_meeting_deadline_policy(
    team_id: str,
    meeting_round_id: str,
) -> dict[str, Any]:
    """Append one server-derived deadline policy to a Challenge meeting.

    Formal meetings normally receive the policy in their creation record;
    preformal meetings become identifiable only after their validated scope is
    appended.  Existing fixed-300s records are upgraded here without changing
    the logical meeting identity or using caller-supplied timestamps.
    """

    from core.web.services.team_service import assert_team_exists
    from core.web.services.team_workflow.challenge_deadline_policy import (
        DEADLINE_POLICY_VERSION,
        derive_meeting_deadline_policy,
        is_challenge_meeting,
    )
    from core.web.services.team_workflow.research_runtime.challenge_turn_policy import (
        current_challenge_task_deadline_at_ms,
    )

    normalized_team_id = assert_team_exists(team_id)
    normalized_meeting_id = str(meeting_round_id or "").strip()
    with _write_lock("persist_challenge_meeting_deadline_policy"):
        meeting = _load_meeting_round(normalized_team_id, normalized_meeting_id)
        if not is_challenge_meeting(meeting):
            return meeting
        if (
            str(meeting.get("deadlinePolicyVersion") or "").strip()
            == DEADLINE_POLICY_VERSION
            and int(meeting.get("challengeDeadlineAtMs") or 0) > 0
        ):
            return meeting
        server_created_at_ms = int(meeting.get("serverCreatedAtMs") or 0)
        if server_created_at_ms <= 0:
            # Legacy records did not persist a trustworthy server clock.  The
            # migration starts a fresh meeting window at the first governed
            # execution rather than trusting caller-controlled ``startedAt``.
            server_created_at_ms = int(
                datetime.now(timezone.utc).timestamp() * 1000
            )
        updated = {
            **meeting,
            "serverCreatedAtMs": server_created_at_ms,
            **derive_meeting_deadline_policy(
                normalized_team_id,
                meeting,
                server_created_at_ms=server_created_at_ms,
                outer_deadline_at_ms=current_challenge_task_deadline_at_ms(),
            ),
            "updatedAt": _utc_now(),
        }
        _append_round_record(normalized_team_id, updated)
    return updated


def bind_meeting_chat_room_round(
    team_id: str,
    meeting_round_id: str,
    room_id: str,
    round_id: str,
) -> dict[str, Any]:
    """Bind one chat-room discussion round to an open meeting round (both ways).

    The meeting record carries ``linkedChatRoomId``/``chatRoomRoundIds``; the
    room round carries ``config.meetingRoundId`` (set by the caller when it
    starts the round).  Rebinding the same pair is a no-op.
    """
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_round_id = str(meeting_round_id or "").strip()
    normalized_room_id = str(room_id or "").strip()
    normalized_room_round_id = str(round_id or "").strip()
    if not normalized_round_id:
        raise ResearchMeetingRoundError("Meeting round id is required.")
    if not normalized_room_id or not normalized_room_round_id:
        raise ContractValidationError("binding a meeting round requires roomId and roundId")
    with _write_lock("bind_meeting_chat_room_round"):
        meeting_round = _load_meeting_round(normalized_team_id, normalized_round_id)
        status = str(meeting_round.get("status") or "").strip().lower()
        if status != "open":
            raise ResearchMeetingRoundError(
                "only an open meeting round can bind a chat room discussion round"
            )
        linked_room_id = str(meeting_round.get("linkedChatRoomId") or "").strip()
        if linked_room_id and linked_room_id != normalized_room_id:
            raise ResearchMeetingRoundError(
                "meeting round is already bound to a different chat room"
            )
        bound_round_ids = _normalized_str_list(meeting_round.get("chatRoomRoundIds"))
        if linked_room_id == normalized_room_id and normalized_room_round_id in bound_round_ids:
            return {
                "schemaVersion": SCHEMA_VERSION,
                "teamId": normalized_team_id,
                "status": "reused",
                "meetingRound": meeting_round,
                "storagePath": str(_rounds_path(normalized_team_id)),
            }
        updated = dict(meeting_round)
        updated["linkedChatRoomId"] = normalized_room_id
        updated["chatRoomRoundIds"] = [*bound_round_ids, normalized_room_round_id]
        updated["updatedAt"] = _utc_now()
        _append_round_record(normalized_team_id, updated)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "status": "bound",
        "meetingRound": updated,
        "storagePath": str(_rounds_path(normalized_team_id)),
    }


def _room_rounds_by_id(room_detail: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(room_detail, Mapping):
        return {}
    return {
        str(item.get("roundId") or "").strip(): dict(item)
        for item in list(room_detail.get("rounds") or [])
        if isinstance(item, dict) and str(item.get("roundId") or "").strip()
    }


def _load_bound_room_rounds(meeting_round: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Read the bound chat-room rounds (read-only) for one room-bound meeting."""

    room_id = str(meeting_round.get("linkedChatRoomId") or "").strip()
    round_ids = _normalized_str_list(meeting_round.get("chatRoomRoundIds"))
    if not room_id or not round_ids:
        return {}
    from core.web.services import chat_room_service

    room_detail = chat_room_service.get_chat_room_detail(room_id)
    if room_detail is None:
        raise ResearchMeetingRoundError("Linked chat room not found for the meeting round.")
    rounds_by_id = _room_rounds_by_id(room_detail)
    missing = [round_id for round_id in round_ids if round_id not in rounds_by_id]
    if missing:
        raise ResearchMeetingRoundError(
            f"Linked chat room is missing bound discussion round: {missing[0]}"
        )
    return {round_id: rounds_by_id[round_id] for round_id in round_ids}


def meeting_source_messages(meeting_round: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return the bound room discussion messages in stable round/message order."""

    messages: list[dict[str, Any]] = []
    room_id = str(meeting_round.get("linkedChatRoomId") or "").strip()
    for round_id, room_round in _load_bound_room_rounds(meeting_round).items():
        for message in list(room_round.get("messages") or []):
            if not isinstance(message, dict):
                continue
            entry = dict(message)
            entry["roomId"] = room_id
            entry["roundId"] = round_id
            messages.append(entry)
    return messages


def completed_meeting_source_messages(
    meeting_round: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Return successful, non-pass discussion messages that a digest may cite."""

    return [
        message
        for message in meeting_source_messages(meeting_round)
        if str(message.get("status") or "").strip().lower() == "completed"
        and not is_pass_message(message)
    ]


_EMPTY_DISCUSSION_RECOVERY_TYPES = {
    "hypothesis_candidate_generation",
    "hypothesis_review",
}


def supersede_empty_discussion_meeting(
    team_id: str,
    meeting_round_id: str,
    *,
    actor: str = "system:failed-discussion-recovery",
) -> dict[str, Any]:
    """Close one terminal discussion attempt that produced no citable message.

    Applies to candidate-generation and hypothesis-review rounds alike.  This
    recovery record deliberately carries no digest or decisions: it is an
    abandoned attempt, not an approved research conclusion.  A follow-up
    meeting (fresh generation attempt or next review round) can then open
    without rewriting the append-only history of the failed attempt.
    """

    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_round_id = str(meeting_round_id or "").strip()
    if not normalized_round_id:
        raise ResearchMeetingRoundError("Meeting round id is required.")
    with _read_lock("supersede_empty_discussion_meeting.check"):
        meeting_round = _load_meeting_round(normalized_team_id, normalized_round_id)
    status = str(meeting_round.get("status") or "").strip().lower()
    if status == "closed" and str(meeting_round.get("recoveryReason") or "") == (
        "discussion_has_no_completed_messages"
    ):
        return {
            "schemaVersion": SCHEMA_VERSION,
            "teamId": normalized_team_id,
            "status": "reused",
            "meetingRound": meeting_round,
            "storagePath": str(_rounds_path(normalized_team_id)),
        }
    if (
        str(meeting_round.get("meetingType") or "").strip().lower()
        not in _EMPTY_DISCUSSION_RECOVERY_TYPES
    ):
        raise ResearchMeetingRoundError(
            "only discussion meetings may use empty-discussion recovery"
        )
    if status not in {"open", "summarizing"}:
        raise ResearchMeetingRoundError(
            f"meeting status {status or '<unknown>'} cannot be superseded"
        )
    if running_bound_round_ids(meeting_round):
        raise ResearchMeetingRoundError(
            "discussion round is still running and cannot be superseded"
        )
    if completed_meeting_source_messages(meeting_round):
        raise ResearchMeetingRoundError(
            "discussion produced completed messages and cannot be superseded"
        )

    now = _utc_now()
    closed_record = dict(meeting_round)
    closed_record["status"] = "closed"
    closed_record["closedAt"] = now
    closed_record["closedBy"] = str(actor or "").strip() or "system:failed-discussion-recovery"
    closed_record["recoveryReason"] = "discussion_has_no_completed_messages"
    closed_record["summaryDraftError"] = {
        "code": "discussion_has_no_completed_messages",
        "message": "讨论未产出可引用的成功发言，已结束本次失败尝试",
        "remediationLabel": "重新发起讨论",
    }
    closed_record["updatedAt"] = now
    with _write_lock("supersede_empty_discussion_meeting.commit"):
        latest = _load_meeting_round(normalized_team_id, normalized_round_id)
        if str(latest.get("status") or "").strip().lower() != status:
            raise ResearchMeetingRoundError(
                "meeting status changed while failed-discussion recovery was running"
            )
        _append_round_record(normalized_team_id, closed_record)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "status": "superseded",
        "meetingRound": closed_record,
        "storagePath": str(_rounds_path(normalized_team_id)),
    }


def terminate_meeting_execution(
    team_id: str,
    meeting_round_id: str,
    *,
    reason: str,
    actor: str = "system:challenge-execution-fence",
) -> dict[str, Any]:
    """Close a fenced formal meeting without promoting a partial digest."""

    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_round_id = str(meeting_round_id or "").strip()
    normalized_reason = str(reason or "").strip()
    if not normalized_round_id or not normalized_reason:
        raise ResearchMeetingRoundError("meeting id and terminal reason are required")
    with _write_lock("terminate_meeting_execution"):
        meeting_round = _load_meeting_round(normalized_team_id, normalized_round_id)
        status = str(meeting_round.get("status") or "").strip().lower()
        if status == "closed" and str(meeting_round.get("executionStatus") or "") == "stopped":
            updated = meeting_round
            result_status = "reused"
        else:
            if status not in {"open", "summarizing"}:
                raise ResearchMeetingRoundError(
                    f"meeting status {status or '<unknown>'} cannot be execution-stopped"
                )
            now = _utc_now()
            updated = {
                **meeting_round,
                "status": "closed",
                "closedAt": now,
                "closedBy": str(actor or "").strip()
                or "system:challenge-execution-fence",
                "executionStatus": "stopped",
                "terminalReason": normalized_reason,
                "recoveryReason": normalized_reason,
                "summaryDraftError": {
                    "code": normalized_reason,
                    "message": "正式会议已由服务端执行边界终止，未生成或晋升纪要。",
                    "remediationLabel": "在新的正式运行中重新发起会议",
                },
                "updatedAt": now,
            }
            _append_round_record(normalized_team_id, updated)
            result_status = "stopped"
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "status": result_status,
        "meetingRound": updated,
        "storagePath": str(_rounds_path(normalized_team_id)),
    }


_STOP_DISCUSSION_ELIGIBLE_STATUSES = {
    "open",
    "summarizing",
    "awaiting_approval",
    # Legacy records may expose the terminal markers the V2 recovery
    # projection reads; an operator stop must stay executable for them.
    "blocked",
    "stalled",
}


def stop_discussion_meeting(
    team_id: str,
    meeting_round_id: str,
    *,
    actor: str = "operator:v2-stop-discussion",
    reason: str = "operator_stop_discussion",
) -> dict[str, Any]:
    """Operator stop for one stalled discussion attempt (V2 ``stop_discussion``).

    This is the terminal path for a stuck meeting that already produced
    citable messages: the attempt is closed with ``executionStatus: stopped``
    while the transcript and any produced draft stay untouched.  An attempt
    without citable messages keeps the exact empty-discussion recovery
    semantics of ``supersede_empty_discussion_meeting`` (an abandoned attempt
    carrying no digest or decisions), so one operator command covers both
    shapes without ever raising for a meeting the V2 projection may offer the
    stop action for.
    """

    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_round_id = str(meeting_round_id or "").strip()
    normalized_reason = str(reason or "").strip() or "operator_stop_discussion"
    if not normalized_round_id:
        raise ResearchMeetingRoundError("Meeting round id is required.")
    with _read_lock("stop_discussion_meeting.check"):
        meeting_round = _load_meeting_round(normalized_team_id, normalized_round_id)
    if (
        str(meeting_round.get("meetingType") or "").strip().lower()
        not in _EMPTY_DISCUSSION_RECOVERY_TYPES
    ):
        raise ResearchMeetingRoundError(
            "only discussion meetings may use empty-discussion recovery"
        )
    status = str(meeting_round.get("status") or "").strip().lower()
    if (
        status == "closed"
        and str(meeting_round.get("recoveryReason") or "")
        == "discussion_has_no_completed_messages"
    ):
        return supersede_empty_discussion_meeting(
            normalized_team_id, normalized_round_id, actor=actor
        )
    if (
        status == "closed"
        and str(meeting_round.get("executionStatus") or "") == "stopped"
    ):
        return {
            "schemaVersion": SCHEMA_VERSION,
            "teamId": normalized_team_id,
            "status": "reused",
            "meetingRound": meeting_round,
            "storagePath": str(_rounds_path(normalized_team_id)),
        }
    if status not in _STOP_DISCUSSION_ELIGIBLE_STATUSES:
        raise ResearchMeetingRoundError(
            f"meeting status {status or '<unknown>'} cannot be stopped"
        )
    if running_bound_round_ids(meeting_round):
        raise ResearchMeetingRoundError(
            "discussion round is still running and cannot be stopped"
        )

    now = _utc_now()
    closed_record = dict(meeting_round)
    closed_record["status"] = "closed"
    closed_record["closedAt"] = now
    closed_record["closedBy"] = str(actor or "").strip() or "operator:v2-stop-discussion"
    if completed_meeting_source_messages(meeting_round):
        closed_record["executionStatus"] = "stopped"
        closed_record["terminalReason"] = normalized_reason
        closed_record["recoveryReason"] = normalized_reason
        closed_record["summaryDraftError"] = {
            "code": normalized_reason,
            "message": "讨论已由操作者停止，已产出发言与草稿全部保留。",
            "remediationLabel": "重新发起讨论",
        }
        result_status = "stopped"
    else:
        closed_record["recoveryReason"] = "discussion_has_no_completed_messages"
        closed_record["summaryDraftError"] = {
            "code": "discussion_has_no_completed_messages",
            "message": "讨论未产出可引用的成功发言，已结束本次失败尝试",
            "remediationLabel": "重新发起讨论",
        }
        result_status = "superseded"
    closed_record["updatedAt"] = now
    with _write_lock("stop_discussion_meeting.commit"):
        latest = _load_meeting_round(normalized_team_id, normalized_round_id)
        if str(latest.get("status") or "").strip().lower() != status:
            raise ResearchMeetingRoundError(
                "meeting status changed while the operator stop was running"
            )
        _append_round_record(normalized_team_id, closed_record)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "status": result_status,
        "meetingRound": closed_record,
        "storagePath": str(_rounds_path(normalized_team_id)),
    }


def message_source_ref(message: Mapping[str, Any]) -> str:
    """Stable digest -> room message backlink: ``roomId/roundId/messageId``."""

    return "/".join(
        [
            str(message.get("roomId") or "").strip(),
            str(message.get("roundId") or "").strip(),
            str(message.get("messageId") or "").strip(),
        ]
    )


def is_pass_message(message: Mapping[str, Any]) -> bool:
    return str(message.get("content") or "").strip().lower() in _PASS_TOKENS


def extract_discussion_markers(messages: Sequence[Mapping[str, Any]]) -> dict[str, list[Any]]:
    """Read structured protocol facts, with marker parsing for legacy messages."""

    extracted: dict[str, list[Any]] = {
        "agreements": [],
        "disagreements": [],
        "risks": [],
        "actionItems": [],
        "knowledgeCandidates": [],
        "proposedCandidates": [],
        "evidenceRequests": [],
        "evidenceRequestErrors": [],
    }
    for message in messages:
        if str(message.get("status") or "").strip().lower() != "completed":
            continue
        structured_protocol = structured_protocol_from_message(message)
        if structured_protocol is not None:
            for key in _STRUCTURED_MARKER_KEYS:
                extracted[key].extend(list(structured_protocol.get(key) or []))
            continue
        content = str(message.get("content") or "").strip()
        if not content or is_pass_message(message):
            continue
        speaker = (
            str(message.get("speakerTitle") or "").strip()
            or str(message.get("participantId") or "").strip()
            or "participant"
        )
        for line in content.splitlines():
            text = line.strip()
            if not text:
                continue
            match = _MARKER_LINE_PATTERN.match(text)
            if match is None:
                continue
            marker = str(match.group("marker") or "").strip().upper()
            if marker not in _MARKER_PREFIXES:
                continue
            value = str(match.group("value") or "").strip()
            emphasis = str(match.group("emphasis") or "")
            if emphasis and emphasis in value:
                value = value.replace(emphasis, "", 1).strip()
            if not value:
                continue
            if marker == "AGREE":
                extracted["agreements"].append(value)
            elif marker == "DISAGREE":
                extracted["disagreements"].append(
                    {
                        "issue": value,
                        "positions": [f"{speaker}: {value}"],
                        "unresolvedReason": "讨论中未收敛（fixture 提取）",
                    }
                )
            elif marker == "RISK":
                extracted["risks"].append(value)
            elif marker == "KNOWLEDGE":
                extracted["knowledgeCandidates"].append(value)
            elif marker == "ACTION":
                owner, separator, action = value.partition("|")
                extracted["actionItems"].append(
                    {
                        "ownerRoleId": owner.strip(),
                        "action": (action if separator else owner).strip(),
                        "dueGate": "",
                    }
                )
            elif marker == "CANDIDATE":
                # Formal grounded rows extend the legacy three fields with
                # ``REFS`` and ``CHECK``. Legacy rows remain compatible.
                parts = [part.strip() for part in value.split("|")]
                refs_index = next(
                    (
                        index
                        for index, part in enumerate(parts)
                        if part.upper().startswith("REFS:")
                    ),
                    -1,
                )
                check_index = next(
                    (
                        index
                        for index, part in enumerate(parts)
                        if part.upper().startswith("CHECK:")
                    ),
                    -1,
                )
                marker_indexes = [index for index in (refs_index, check_index) if index >= 0]
                if marker_indexes and len(parts) >= 3:
                    marker_start = min(marker_indexes)
                    candidate_id = parts[0]
                    statement = parts[1]
                    rationale = "|".join(parts[2:marker_start]).strip()
                elif len(parts) >= 3:
                    # The rationale is the last field; the statement may itself
                    # contain '|' characters, so keep everything in between.
                    candidate_id = parts[0]
                    rationale = parts[-1]
                    statement = "|".join(parts[1:-1])
                elif len(parts) == 2:
                    candidate_id, statement = parts[0], parts[1]
                    rationale = ""
                else:
                    candidate_id, statement, rationale = "", parts[0], ""
                proposal = {
                    "candidateId": candidate_id,
                    "statement": statement,
                    "rationale": rationale,
                    "proposedBy": speaker,
                }
                if refs_index >= 0:
                    refs_text = parts[refs_index].partition(":")[2]
                    proposal["lineageRefs"] = [
                        item.strip()
                        for item in re.split(r"[;,，；]", refs_text)
                        if item.strip()
                    ]
                if check_index >= 0:
                    proposal["testablePrediction"] = (
                        parts[check_index].partition(":")[2].strip()
                    )
                extracted["proposedCandidates"].append(proposal)
            elif marker == "EVIDENCE_REQUEST":
                try:
                    if len(value) > _EVIDENCE_REQUEST_MARKER_MAX_CHARS:
                        extracted["evidenceRequestErrors"].append(
                            {
                                "code": "evidence_request_too_large",
                                "message": "EVIDENCE_REQUEST marker exceeds 65536 chars",
                            }
                        )
                        continue
                    parsed = json.loads(value)
                except json.JSONDecodeError:
                    extracted["evidenceRequestErrors"].append(
                        {
                            "code": "evidence_request_json_invalid",
                            "message": "EVIDENCE_REQUEST marker is not valid JSON",
                        }
                    )
                    continue
                if not isinstance(parsed, dict):
                    extracted["evidenceRequestErrors"].append(
                        {
                            "code": "evidence_request_invalid",
                            "message": "EVIDENCE_REQUEST JSON must be an object",
                        }
                    )
                    continue
                extracted["evidenceRequests"].append(parsed)
    extracted["proposedCandidates"] = _canonical_proposed_candidates(
        extracted["proposedCandidates"]
    )
    return extracted


def _canonical_proposed_candidates(value: Any) -> list[dict[str, Any]]:
    """Keep one current proposal per candidate identity in discussion order."""

    canonical: list[dict[str, Any]] = []
    positions_by_id: dict[str, int] = {}
    for raw in list(value or []):
        if not isinstance(raw, Mapping):
            continue
        candidate = dict(raw)
        candidate_id = str(candidate.get("candidateId") or "").strip()
        identity = candidate_id.casefold()
        if not identity:
            canonical.append(candidate)
            continue
        previous_position = positions_by_id.get(identity)
        if previous_position is None:
            positions_by_id[identity] = len(canonical)
            canonical.append(candidate)
            continue
        canonical[previous_position] = candidate
    return canonical


UNSTRUCTURED_DERIVED_FROM = "unstructured"
EMPTY_DIGEST_CAPTURE_MESSAGE = "纪要未捕获讨论内容"
_UNSTRUCTURED_SUMMARY_MAX_CHARS = 240
_STRUCTURED_MARKER_KEYS = (
    "agreements",
    "disagreements",
    "risks",
    "actionItems",
    "knowledgeCandidates",
    "proposedCandidates",
    "evidenceRequests",
)
_EVIDENCE_REQUEST_MARKER_MAX_CHARS = 65536
_DIGEST_CAPTURE_KEYS = (
    "agreements",
    "disagreements",
    "actionItems",
    "knowledgeCandidates",
    "evidenceRequests",
)


def digest_agreement_texts(value: Any) -> list[str]:
    """Normalize marker strings and unstructured objects into digest texts."""

    texts: list[str] = []
    for item in list(value or []):
        if isinstance(item, Mapping):
            text = str(
                item.get("text") or item.get("issue") or item.get("summary") or ""
            ).strip()
        else:
            text = str(item or "").strip()
        if text:
            texts.append(text)
    return texts


def structured_marker_item_count(markers: Mapping[str, Any]) -> int:
    return sum(len(list(markers.get(key) or [])) for key in _STRUCTURED_MARKER_KEYS)


def digest_draft_captured_discussion(draft: Mapping[str, Any]) -> bool:
    return any(list(draft.get(key) or []) for key in _DIGEST_CAPTURE_KEYS)


def _unstructured_summary_text(content: str) -> str:
    collapsed = " ".join(str(content or "").split())
    if len(collapsed) <= _UNSTRUCTURED_SUMMARY_MAX_CHARS:
        return collapsed
    return collapsed[: _UNSTRUCTURED_SUMMARY_MAX_CHARS - 1].rstrip() + "…"


def derive_unstructured_digest_entries(
    messages: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Turn free-form completed speeches into cited summary entries.

    These are not fabricated consensus: each item is a speech excerpt marked
    ``derivedFrom=unstructured`` and linked back to the source message.
    """

    entries: list[dict[str, Any]] = []
    for message in messages:
        if str(message.get("status") or "").strip().lower() != "completed":
            continue
        if structured_protocol_from_message(message) is not None:
            continue
        if is_pass_message(message):
            continue
        content = str(message.get("content") or "").strip()
        if not content:
            continue
        message_id = str(message.get("messageId") or "").strip()
        if not message_id:
            continue
        speaker = (
            str(message.get("speakerTitle") or "").strip()
            or str(message.get("participantId") or "").strip()
            or "participant"
        )
        entries.append(
            {
                "text": _unstructured_summary_text(content),
                "speaker": speaker,
                "derivedFrom": UNSTRUCTURED_DERIVED_FROM,
                "sourceMessageRefs": [message_source_ref(message)],
            }
        )
    return entries


def apply_unstructured_digest_fallback(
    markers: Mapping[str, list[Any]],
    messages: Sequence[Mapping[str, Any]],
) -> dict[str, list[Any]]:
    """Fill agreements with cited speech summaries when marker extraction is empty."""

    merged = {str(key): list(value) for key, value in dict(markers).items()}
    if structured_marker_item_count(merged):
        return merged
    entries = derive_unstructured_digest_entries(messages)
    if entries:
        merged["agreements"] = entries
    return merged


def assert_review_digest_captured_discussion(
    meeting_round: Mapping[str, Any],
    draft: Mapping[str, Any],
    source_messages: Sequence[Mapping[str, Any]],
) -> None:
    """Fail-closed: a review with completed speech cannot approve an empty digest."""

    if str(meeting_round.get("meetingType") or "").strip().lower() != "hypothesis_review":
        return
    completed = [
        message
        for message in source_messages
        if str(message.get("status") or "").strip().lower() == "completed"
        and not is_pass_message(message)
        and str(message.get("content") or "").strip()
    ]
    if not completed:
        return
    if not digest_draft_captured_discussion(draft):
        raise ContractValidationError(EMPTY_DIGEST_CAPTURE_MESSAGE)


def source_message_content_hash(messages: Sequence[Mapping[str, Any]]) -> str:
    """Stable hash of structured facts and compatibility content for draft reuse."""

    return _stable_hash(
        [
            {
                "ref": message_source_ref(message),
                "content": str(message.get("content") or ""),
                "messagePayload": (
                    dict(message.get("messagePayload") or {})
                    if isinstance(message.get("messagePayload"), Mapping)
                    else None
                ),
                "status": str(message.get("status") or "").strip().lower(),
            }
            for message in list(messages or [])
            if isinstance(message, Mapping)
        ]
    )


def running_bound_round_ids(meeting_round: Mapping[str, Any]) -> list[str]:
    """Return bound chat-room round ids that are still in a running status."""

    from core.web.services import chat_room_service

    bound_rounds = _load_bound_room_rounds(meeting_round)
    return [
        round_id
        for round_id, room_round in bound_rounds.items()
        if str(room_round.get("status") or "").strip().lower()
        in chat_room_service.RUNNING_ROUND_STATUSES
    ]


def record_meeting_summary_draft_error(
    team_id: str,
    meeting_round_id: str,
    error: Mapping[str, Any],
) -> dict[str, Any]:
    """Persist a structured draft failure while keeping ``summarizing``."""

    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_round_id = str(meeting_round_id or "").strip()
    if not normalized_round_id:
        raise ResearchMeetingRoundError("Meeting round id is required.")
    with _write_lock("record_meeting_summary_draft_error"):
        meeting_round = _load_meeting_round(normalized_team_id, normalized_round_id)
        updated = dict(meeting_round)
        if str(updated.get("status") or "").strip().lower() == "open":
            updated["status"] = "summarizing"
            updated["summaryStartedAt"] = _utc_now()
        updated["summaryDraftError"] = {
            "code": str(error.get("code") or "summary_draft_failed").strip()
            or "summary_draft_failed",
            "message": str(error.get("message") or "").strip(),
            "remediationLabel": str(error.get("remediationLabel") or "重试生成纪要").strip()
            or "重试生成纪要",
        }
        updated["updatedAt"] = _utc_now()
        _append_round_record(normalized_team_id, updated)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "status": str(updated.get("status") or "summarizing"),
        "meetingRound": updated,
        "summaryDraftError": updated["summaryDraftError"],
        "storagePath": str(_rounds_path(normalized_team_id)),
    }


def begin_meeting_summary(
    team_id: str,
    meeting_round_id: str,
    *,
    actor: str = "",
    human_triggered: bool = False,
) -> dict[str, Any]:
    """Move one open meeting round to ``summarizing`` (discussion finished or human call)."""
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_round_id = str(meeting_round_id or "").strip()
    if not normalized_round_id:
        raise ResearchMeetingRoundError("Meeting round id is required.")
    with _read_lock("begin_meeting_summary.check"):
        meeting_round = _load_meeting_round(normalized_team_id, normalized_round_id)
        _ensure_transition_from(meeting_round, "open", "summarizing")
        bound_round_ids = _normalized_str_list(meeting_round.get("chatRoomRoundIds"))
    if bound_round_ids and not human_triggered:
        from core.web.services import chat_room_service

        bound_rounds = _load_bound_room_rounds(meeting_round)
        running = [
            round_id
            for round_id, room_round in bound_rounds.items()
            if str(room_round.get("status") or "").strip().lower()
            in chat_room_service.RUNNING_ROUND_STATUSES
        ]
        if running:
            raise ResearchMeetingRoundError(
                "discussion round is still running; wait for completion or pass human_triggered=True"
            )
    with _write_lock("begin_meeting_summary.commit"):
        meeting_round = _load_meeting_round(normalized_team_id, normalized_round_id)
        _ensure_transition_from(meeting_round, "open", "summarizing")
        updated = dict(meeting_round)
        updated["status"] = "summarizing"
        updated["summarizedBy"] = str(actor or "").strip()
        updated["summaryStartedAt"] = _utc_now()
        updated["summaryHumanTriggered"] = bool(human_triggered)
        updated["updatedAt"] = updated["summaryStartedAt"]
        _append_round_record(normalized_team_id, updated)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "status": "summarizing",
        "meetingRound": updated,
        "storagePath": str(_rounds_path(normalized_team_id)),
    }


def _validate_digest_draft(draft: Mapping[str, Any]) -> None:
    """Fail closed when a digest draft drops any §15.3/§15.4 required section."""

    missing_keys = [
        key
        for key in (
            "agreements",
            "disagreements",
            "actionItems",
            "risks",
            "knowledgeCandidates",
            "sourceMessageRefs",
        )
        if key not in draft
    ]
    if missing_keys:
        raise ContractValidationError(
            "digest draft is missing required sections: " + ", ".join(missing_keys)
        )
    if not str(draft.get("summary") or "").strip():
        raise ContractValidationError("digest draft requires a summary")
    if not _normalized_str_list(draft.get("sourceMessageRefs")):
        raise ContractValidationError(
            "digest draft sourceMessageRefs must reference at least one source message"
        )


def submit_meeting_digest_draft(
    team_id: str,
    meeting_round_id: str,
    draft: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach a Coordinator digest draft and move ``summarizing -> awaiting_approval``."""
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_round_id = str(meeting_round_id or "").strip()
    if not normalized_round_id:
        raise ResearchMeetingRoundError("Meeting round id is required.")
    normalized_draft = dict(draft) if isinstance(draft, Mapping) else {}
    with _write_lock("submit_meeting_digest_draft"):
        meeting_round = _load_meeting_round(normalized_team_id, normalized_round_id)
        _ensure_transition_from(meeting_round, "summarizing", "awaiting_approval")
        _validate_digest_draft(normalized_draft)
        probe = {
            "digestId": "digest-draft-probe",
            "meetingRoundId": normalized_round_id,
            "scopeHash": str(meeting_round.get("scopeHash") or ""),
            "summary": str(normalized_draft.get("summary") or "").strip(),
            "participantAgentIds": list(meeting_round.get("participants") or []),
            "discussionTopics": _normalized_str_list(normalized_draft.get("discussionTopics")),
            "decisionRefs": ["decision-draft-probe"],
            "closedBy": "draft-probe",
            "createdAt": _utc_now(),
            "agendaSummary": str(normalized_draft.get("agendaSummary") or "").strip(),
            "agreements": digest_agreement_texts(normalized_draft.get("agreements")),
            "disagreements": list(normalized_draft.get("disagreements") or []),
            "actionItems": list(normalized_draft.get("actionItems") or []),
            "risks": list(normalized_draft.get("risks") or []),
            "blockers": list(normalized_draft.get("blockers") or []),
            "knowledgeCandidates": list(normalized_draft.get("knowledgeCandidates") or []),
            "sourceMessageRefs": list(normalized_draft.get("sourceMessageRefs") or []),
            "documentMarkdown": str(normalized_draft.get("documentMarkdown") or ""),
            "documentTemplateId": str(normalized_draft.get("documentTemplateId") or ""),
            "factLedger": dict(normalized_draft.get("factLedger") or {}),
            "contentHash": str(normalized_draft.get("contentHash") or ""),
        }
        MeetingDigest.from_dict(probe)
        normalized_draft["contentHash"] = _digest_content_hash(normalized_draft)
        updated = dict(meeting_round)
        updated["status"] = "awaiting_approval"
        updated["digestDraft"] = normalized_draft
        updated.pop("summaryDraftError", None)
        updated["updatedAt"] = _utc_now()
        _append_round_record(normalized_team_id, updated)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "status": "awaiting_approval",
        "meetingRound": updated,
        "digestDraft": normalized_draft,
        "storagePath": str(_rounds_path(normalized_team_id)),
    }


def reject_meeting_digest_draft(
    team_id: str,
    meeting_round_id: str,
    *,
    actor: str = "",
    reason: str = "",
) -> dict[str, Any]:
    """Human rejects the digest draft: ``awaiting_approval -> summarizing``."""
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_round_id = str(meeting_round_id or "").strip()
    if not normalized_round_id:
        raise ResearchMeetingRoundError("Meeting round id is required.")
    with _write_lock("reject_meeting_digest_draft"):
        meeting_round = _load_meeting_round(normalized_team_id, normalized_round_id)
        _ensure_transition_from(meeting_round, "awaiting_approval", "summarizing")
        updated = dict(meeting_round)
        updated["status"] = "summarizing"
        updated.pop("digestDraft", None)
        updated["draftRejectedBy"] = str(actor or "").strip()
        updated["draftRejectedReason"] = str(reason or "").strip()
        updated["updatedAt"] = _utc_now()
        _append_round_record(normalized_team_id, updated)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "status": "summarizing",
        "meetingRound": updated,
        "storagePath": str(_rounds_path(normalized_team_id)),
    }


def _digest_content_hash(payload: Mapping[str, Any]) -> str:
    return _stable_hash(
        {
            "summary": str(payload.get("summary") or "").strip(),
            "agendaSummary": str(payload.get("agendaSummary") or "").strip(),
            "discussionTopics": _normalized_str_list(payload.get("discussionTopics")),
            "agreements": digest_agreement_texts(payload.get("agreements")),
            "disagreements": list(payload.get("disagreements") or []),
            "actionItems": list(payload.get("actionItems") or []),
            "risks": _normalized_str_list(payload.get("risks")),
            "blockers": _normalized_str_list(payload.get("blockers")),
            "knowledgeCandidates": _normalized_str_list(payload.get("knowledgeCandidates")),
            "sourceMessageRefs": _normalized_str_list(payload.get("sourceMessageRefs")),
            "proposedCandidates": list(payload.get("proposedCandidates") or []),
            "evidenceRequests": list(payload.get("evidenceRequests") or []),
            "documentMarkdown": str(payload.get("documentMarkdown") or "").strip(),
            "documentTemplateId": str(payload.get("documentTemplateId") or "").strip(),
            "factLedger": dict(payload.get("factLedger") or {}),
        }
    )


def _build_digest(meeting_round: dict[str, Any], request: dict[str, Any], now: str) -> dict[str, Any]:
    summary = str(request.get("summary") or "").strip()
    if not summary:
        raise ContractValidationError("closing a meeting round requires a summary")
    digest_id = f"digest-{_stable_hash({'meetingRoundId': meeting_round['meetingRoundId'], 'scopeHash': meeting_round['scopeHash'], 'summary': summary})[:16]}"
    return {
        "schemaVersion": LEGACY_DIGEST_SCHEMA_VERSION,
        "digestId": digest_id,
        "meetingRoundId": str(meeting_round["meetingRoundId"]),
        "scopeHash": str(meeting_round["scopeHash"]),
        "summary": summary,
        "participantAgentIds": list(meeting_round.get("participants") or []),
        "discussionTopics": _normalized_str_list(request.get("discussionTopics")),
        "decisionRefs": _normalized_str_list(request.get("decisionRefs")),
        "closedBy": str(request.get("closedBy") or "").strip(),
        "createdAt": now,
    }


def _build_digest_v2(
    meeting_round: dict[str, Any],
    draft: Mapping[str, Any],
    request: Mapping[str, Any],
    now: str,
) -> dict[str, Any]:
    """Merge the approved draft with human amendments into the final digest."""

    merged: dict[str, Any] = dict(draft)
    for key in (
        "summary",
        "agendaSummary",
        "discussionTopics",
        "agreements",
        "disagreements",
        "actionItems",
        "risks",
        "blockers",
        "knowledgeCandidates",
        "sourceMessageRefs",
        "proposedCandidates",
        "evidenceRequests",
    ):
        if key in request and request.get(key) is not None:
            merged[key] = request.get(key)
    summary = str(merged.get("summary") or "").strip()
    if not summary:
        raise ContractValidationError("closing a meeting round requires a summary")
    digest_id = f"digest-{_stable_hash({'meetingRoundId': meeting_round['meetingRoundId'], 'scopeHash': meeting_round['scopeHash'], 'summary': summary})[:16]}"
    digest = {
        "schemaVersion": SCHEMA_VERSION,
        "digestId": digest_id,
        "meetingRoundId": str(meeting_round["meetingRoundId"]),
        "scopeHash": str(meeting_round["scopeHash"]),
        "summary": summary,
        "participantAgentIds": list(meeting_round.get("participants") or []),
        "discussionTopics": _normalized_str_list(merged.get("discussionTopics")),
        "decisionRefs": _normalized_str_list(merged.get("decisionRefs")),
        "closedBy": str(request.get("closedBy") or "").strip(),
        "createdAt": now,
        "agendaSummary": str(merged.get("agendaSummary") or "").strip(),
        "agreements": digest_agreement_texts(merged.get("agreements")),
        "disagreements": list(merged.get("disagreements") or []),
        "actionItems": list(merged.get("actionItems") or []),
        "risks": _normalized_str_list(merged.get("risks")),
        "blockers": _normalized_str_list(merged.get("blockers")),
        "knowledgeCandidates": _normalized_str_list(merged.get("knowledgeCandidates")),
        "sourceMessageRefs": _normalized_str_list(merged.get("sourceMessageRefs")),
        "proposedCandidates": list(merged.get("proposedCandidates") or []),
        "documentMarkdown": str(merged.get("documentMarkdown") or "").strip(),
        "documentTemplateId": str(merged.get("documentTemplateId") or "").strip(),
        "factLedger": dict(merged.get("factLedger") or {}),
    }
    digest["contentHash"] = _digest_content_hash(digest)
    return digest


def _build_decision(meeting_round: dict[str, Any], raw: Mapping[str, Any], now: str) -> dict[str, Any]:
    decision = str(raw.get("decision") or "").strip().lower()
    if not decision:
        raise ContractValidationError("each decision requires a decision kind")
    candidate_refs = _normalized_str_list(raw.get("candidateRefs"))
    evidence_refs = _normalized_str_list(raw.get("evidenceRefs"))
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


def _marker_text(value: Any) -> str:
    if isinstance(value, Mapping):
        return str(value.get("issue") or value.get("action") or "").strip()
    return str(value or "").strip()


def _assert_markers_preserved(
    digest: Mapping[str, Any],
    markers: Mapping[str, list[Any]],
) -> None:
    digest_disagreements = [
        str(item.get("issue") or "")
        for item in list(digest.get("disagreements") or [])
        if isinstance(item, Mapping)
    ]
    for marker in list(markers.get("disagreements") or []):
        issue = _marker_text(marker)
        if issue and not any(issue in digest_issue for digest_issue in digest_disagreements):
            raise ContractValidationError(
                "a disagreement from the source messages is missing in the meeting digest"
            )
    digest_risks = _normalized_str_list(digest.get("risks"))
    for marker in list(markers.get("risks") or []):
        risk = _marker_text(marker)
        if risk and not any(risk in digest_risk for digest_risk in digest_risks):
            raise ContractValidationError(
                "an unresolved risk from the source messages is missing in the meeting digest"
            )
    digest_actions = [
        str(item.get("action") or "")
        for item in list(digest.get("actionItems") or [])
        if isinstance(item, Mapping)
    ]
    for marker in list(markers.get("actionItems") or []):
        action = _marker_text(marker)
        if action and not any(action in digest_action for digest_action in digest_actions):
            raise ContractValidationError(
                "an action item from the source messages is missing in the meeting digest"
            )


def _assert_closure_conditions(
    meeting_round: Mapping[str, Any],
    digest: Mapping[str, Any],
    decisions: list[dict[str, Any]],
    raw_decisions: Sequence[Mapping[str, Any]],
    source_messages: list[dict[str, Any]],
) -> None:
    """Requirements §15.4 meeting completion conditions, enforced fail-closed."""

    if not str(digest.get("summary") or "").strip() or not decisions:
        raise ContractValidationError(
            "closing a meeting round requires a summary and at least one decision record"
        )
    _assert_markers_preserved(digest, extract_discussion_markers(source_messages))
    for decision in decisions:
        if not list(decision.get("evidenceRefs") or []):
            raise ContractValidationError(
                "each decision record requires at least one evidence ref"
            )
        if (
            str(decision.get("decision") or "").strip().lower() == "request_new_evidence"
            and not list(decision.get("candidateRefs") or [])
        ):
            # ``candidateRefs`` on a request_new_evidence decision name the
            # hypothesis candidates the collection serves — the claim belief
            # gate's aggregation dimension. A decision without them can only
            # fail that gate closed at convergence, so the closure is rejected
            # here before any artifact is persisted. Recovery stays on the
            # existing idempotent closure flow: correct the decision payload
            # (name the served candidates) and re-approve.
            raise ContractValidationError(
                "request_new_evidence decisions require at least one candidateRef: "
                "the claim belief gate aggregates collection evidence on this "
                "candidate dimension, so a decision without candidateRefs can "
                "only fail that gate closed"
            )
    for index, item in enumerate(list(digest.get("actionItems") or [])):
        if not isinstance(item, Mapping):
            raise ContractValidationError(f"actionItems[{index}] must be an object")
        if not str(item.get("ownerRoleId") or "").strip():
            raise ContractValidationError("each action item requires a role owner")
        if not str(item.get("action") or "").strip():
            raise ContractValidationError("each action item requires an action")
    source_refs = _normalized_str_list(digest.get("sourceMessageRefs"))
    if not source_refs:
        raise ContractValidationError(
            "digest sourceMessageRefs must reference at least one source message"
        )
    if source_messages:
        known_message_ids = {
            str(message.get("messageId") or "").strip()
            for message in source_messages
            if str(message.get("messageId") or "").strip()
        }
        for ref in source_refs:
            message_id = ref.rsplit("/", 1)[-1].strip()
            if not message_id or message_id not in known_message_ids:
                raise ContractValidationError(
                    f"digest sourceMessageRefs must reference existing room messages: {ref}"
                )
    for raw in raw_decisions:
        if bool(raw.get("requiresHumanApproval")) and str(raw.get("status") or "").strip().lower() != "pending":
            raise ContractValidationError(
                "decisions that require human approval must be marked pending"
            )


def _persist_closure_artifacts(
    normalized_team_id: str,
    meeting_round: dict[str, Any],
    digest: dict[str, Any],
    decisions: list[dict[str, Any]],
    request: Mapping[str, Any],
    now: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    from core.web.services.team_workflow.personal_memory_candidates import (
        record_personal_memory_candidates,
    )

    with _write_lock("_persist_closure_artifacts"):
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
        participants = _normalized_str_list(meeting_round.get("participants"))
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
                f"meeting_round:{meeting_round['meetingRoundId']}",
                f"meeting_digest:{digest['digestId']}",
                *[f"decision_record:{item['decisionId']}" for item in decisions],
            ],
            memory_class=str(request.get("memoryClass") or "personal_reflection"),
            summaries=request.get("memorySummaries") if isinstance(request.get("memorySummaries"), Mapping) else None,
            reuse_policy=str(request.get("reusePolicy") or "advisory_only"),
            evidence_status=str(request.get("evidenceStatus") or "unverified"),
            accepted=bool(request.get("accepted")),
        )
    return digest, decisions, memory_result


def _closed_record(
    meeting_round: dict[str, Any],
    digest: Mapping[str, Any],
    decisions: list[dict[str, Any]],
    memory_result: Mapping[str, Any],
    request: Mapping[str, Any],
    now: str,
    *,
    closure_hash: str,
) -> dict[str, Any]:
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
    closed_record["closureHash"] = closure_hash
    closed_record["updatedAt"] = now
    return closed_record


def _reused_close_result(
    normalized_team_id: str,
    meeting_round: dict[str, Any],
) -> dict[str, Any]:
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


def approve_meeting_closure(
    team_id: str,
    meeting_round_id: str,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Human confirms the digest draft: ``awaiting_approval -> closed``.

    Runs the §15.4 completion gate fail-closed, then writes the digest,
    decision records, and per-participant memory candidates.  Repeating the
    same approval reuses the existing artifacts (closure hash idempotency).
    """
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_round_id = str(meeting_round_id or "").strip()
    if not normalized_round_id:
        raise ResearchMeetingRoundError("Meeting round id is required.")
    request = dict(payload) if isinstance(payload, Mapping) else {}
    with _read_lock("approve_meeting_closure.check"):
        meeting_round = _load_meeting_round(normalized_team_id, normalized_round_id)
        current = str(meeting_round.get("status") or "").strip().lower()
        if current == "closed":
            digest_draft = (
                dict(meeting_round.get("digestDraft"))
                if isinstance(meeting_round.get("digestDraft"), Mapping)
                else {}
            )
            if str(meeting_round.get("closureHash") or "") != _approval_closure_hash(request, digest_draft):
                raise ResearchMeetingRoundError(
                    "closed meeting round cannot be reused with different closure content"
                )
            return _reused_close_result(normalized_team_id, meeting_round)
        _ensure_transition_from(meeting_round, "awaiting_approval", "closed")
        digest_draft = (
            dict(meeting_round.get("digestDraft"))
            if isinstance(meeting_round.get("digestDraft"), Mapping)
            else {}
        )
        if not digest_draft:
            raise ResearchMeetingRoundError(
                "meeting round has no digest draft; submit one before approval"
            )
    source_messages = meeting_source_messages(meeting_round)
    assert_review_digest_captured_discussion(meeting_round, digest_draft, source_messages)
    now = _utc_now()
    digest = _build_digest_v2(meeting_round, digest_draft, request, now)
    raw_decisions = [item for item in list(request.get("decisions") or []) if isinstance(item, Mapping)]
    if not raw_decisions:
        raise ContractValidationError(
            "closing a meeting round requires at least one decision record"
        )
    decisions = [_build_decision(meeting_round, item, now) for item in raw_decisions]
    for decision in decisions:
        DecisionRecord.from_dict(decision)
    digest["decisionRefs"] = [str(item.get("decisionId") or "") for item in decisions]
    _assert_closure_conditions(meeting_round, digest, decisions, raw_decisions, source_messages)
    MeetingDigest.from_dict(digest)
    digest, decisions, memory_result = _persist_closure_artifacts(
        normalized_team_id, meeting_round, digest, decisions, request, now
    )
    memory_agents = {str(item.get("agentId") or "") for item in memory_result["candidates"]}
    missing_memory_agents = [
        agent_id
        for agent_id in _normalized_str_list(meeting_round.get("participants"))
        if agent_id not in memory_agents
    ]
    if missing_memory_agents:
        raise ContractValidationError(
            "personal memory candidates must cover every participant: " + ", ".join(missing_memory_agents)
        )
    closed_record = _closed_record(
        meeting_round,
        digest,
        decisions,
        memory_result,
        request,
        now,
        closure_hash=_approval_closure_hash(request, digest_draft),
    )
    with _write_lock("approve_meeting_closure.commit"):
        _append_round_record(normalized_team_id, closed_record)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "status": "created",
        "closed": True,
        "meetingRound": closed_record,
        "digest": digest,
        "decisions": decisions,
        "personalMemoryCandidateRefs": closed_record["personalMemoryCandidateRefs"],
        "memorySummary": {
            "createdCount": memory_result["createdCount"],
            "reusedCount": memory_result["reusedCount"],
        },
        "storagePath": str(_rounds_path(normalized_team_id)),
    }


def close_meeting_round(
    team_id: str,
    meeting_round_id: str,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Close one meeting round, producing digest, decisions, and memory candidates.

    Idempotent: repeating close with the same content reuses the already
    appended artifacts and the closed round record.  This direct path stays
    available for legacy non-room-bound meetings; room-bound rounds (the
    hypothesis-first flow) must close through the four-state
    ``begin_meeting_summary -> submit_meeting_digest_draft ->
    approve_meeting_closure`` gate instead.
    """
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_round_id = str(meeting_round_id or "").strip()
    if not normalized_round_id:
        raise ResearchMeetingRoundError("Meeting round id is required.")
    request = dict(payload) if isinstance(payload, Mapping) else {}
    with _read_lock("close_meeting_round.check"):
        meeting_round = _load_meeting_round(normalized_team_id, normalized_round_id)
        current_status = str(meeting_round.get("status") or "").strip().lower()
        if current_status == "closed":
            if str(meeting_round.get("closureHash") or "") != _closure_hash(request):
                raise ResearchMeetingRoundError(
                    "closed meeting round cannot be reused with different closure content"
                )
            return _reused_close_result(normalized_team_id, meeting_round)
        if current_status in {"summarizing", "awaiting_approval"}:
            raise ResearchMeetingRoundError(
                "meeting round is in the approval flow; close it through approve_meeting_closure"
            )
        if str(meeting_round.get("linkedChatRoomId") or "").strip():
            raise ResearchMeetingRoundError(
                "room-bound meeting rounds close through the summarize/approve flow"
            )
    participants = _normalized_str_list(meeting_round.get("participants"))
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
    digest, decisions, memory_result = _persist_closure_artifacts(
        normalized_team_id, meeting_round, digest, decisions, request, now
    )
    closed_record = _closed_record(
        meeting_round,
        digest,
        decisions,
        memory_result,
        request,
        now,
        closure_hash=_closure_hash(request),
    )
    with _write_lock("close_meeting_round.commit"):
        _append_round_record(normalized_team_id, closed_record)
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


def list_meeting_rounds(
    team_id: str,
    *,
    status: str | Sequence[str] | None = None,
) -> dict[str, Any]:
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    statuses = {
        str(item or "").strip().lower()
        for item in (
            list(status) if isinstance(status, (list, tuple, set)) else [status]
        )
        if str(item or "").strip()
    }
    with _read_lock("list_meeting_rounds"):
        records = _read_jsonl(_rounds_path(normalized_team_id))
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        latest[str(record.get("meetingRoundId") or "")] = record
    rows = sorted(
        (
            record
            for record in latest.values()
            if not statuses
            or str(record.get("status") or "").strip().lower() in statuses
        ),
        key=lambda item: str(item.get("startedAt") or ""),
    )
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
    with _read_lock("get_meeting_round"):
        record = _load_meeting_round(normalized_team_id, normalized_round_id)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "meetingRound": record,
        "storagePath": str(_rounds_path(normalized_team_id)),
    }
