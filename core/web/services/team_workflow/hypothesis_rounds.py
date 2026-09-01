"""Append-only hypothesis round service for the Challenge Cup D04 loop.

Creates and closes hypothesis review rounds as pure offline artifacts under the
team workspace.  Closing a round fails closed when the round is incomplete
(less than two substantially different candidates, missing review dimension,
missing pair comparison, incomplete Pareto, missing MetaReview, or missing
meeting refs).  No chat room or research runtime is touched.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.infrastructure import developer_sandbox
from core.research.workflow.contracts import (
    ContractValidationError,
    HypothesisRound,
    review_call_budget_for,
    scope_hash_for,
)
from core.web.services.team_workflow.jsonl_quarantine import (
    read_jsonl_with_quarantine,
)

SCHEMA_VERSION = 1
DEFAULT_MODE = "formal"
FAILURE_SCHEMA_VERSION = 1
FAILURE_RECORD_KIND = "hypothesis_round_failure"
FAILURE_OPEN_STATUSES = ("failed", "blocked")
RESOLVED_FAILURE_STATUS = "resolved"
_LOCK = threading.RLock()
# In-flight generation guard for content-addressed round ids.  This lock only
# protects membership mutations of the registry set below; it is never held
# across the review executor, the ledger append, or any acquisition of
# ``_LOCK``, so the two locks never nest and no ordering between them exists
# (deadlock-free by construction).  The registry is process-local: across
# processes the append-only ``create_hypothesis_round`` idempotency check
# remains the final backstop.
_IN_FLIGHT_LOCK = threading.Lock()
_IN_FLIGHT_GENERATIONS: set[tuple[str, str]] = set()
_SCOPE_FIELDS = ("program", "theme", "campaign", "question", "branch", "workflow")

PROJECT_ROOT = Path(__file__).resolve().parents[4]


class ResearchHypothesisRoundError(RuntimeError):
    """Base error for hypothesis round persistence."""


class ResearchHypothesisRoundNotFoundError(ResearchHypothesisRoundError):
    """Raised when a hypothesis round does not exist."""


class ResearchHypothesisRoundGenerationInProgressError(ResearchHypothesisRoundError):
    """Raised when the same content-addressed round is already generating.

    Carries the claiming identity so callers can report a structured
    wait/reuse rejection (no review budget was spent by the rejected
    trigger) instead of a generic persistence failure.
    """

    def __init__(self, team_id: str, round_id: str) -> None:
        self.team_id = str(team_id)
        self.round_id = str(round_id)
        super().__init__(
            f"hypothesis round {self.round_id} is already being generated "
            "for this team; wait for the in-flight attempt to finish — it "
            "stores the round under the same round id for reuse"
        )


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


def _read_store(path: Path) -> tuple[list[dict[str, Any]], int]:
    """Read the ledger, quarantining corrupt lines instead of failing closed.

    One torn write must not permanently brick every round read with a 422,
    so bad lines are isolated to an append-only sidecar and reported through
    ``corruptQuarantinedLineCount`` while the original file stays untouched
    for concurrent appenders.
    """
    return read_jsonl_with_quarantine(path)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return _read_store(path)[0]


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


def _normalized_str_list(value: Any) -> list[str]:
    return [str(item or "").strip() for item in list(value or []) if str(item or "").strip()]


def _claim_round_generation(team_id: str, round_id: str) -> bool:
    """Atomically claim the in-flight generation slot for one round id.

    Returns ``False`` when another generation for ``(team_id, round_id)`` is
    already running in this process, so the caller can fail fast with a
    structured rejection instead of double-spending the review budget.
    """
    key = (str(team_id), str(round_id))
    with _IN_FLIGHT_LOCK:
        if key in _IN_FLIGHT_GENERATIONS:
            return False
        _IN_FLIGHT_GENERATIONS.add(key)
        return True


def _release_round_generation(team_id: str, round_id: str) -> None:
    """Release the in-flight generation slot claimed by this process."""
    with _IN_FLIGHT_LOCK:
        _IN_FLIGHT_GENERATIONS.discard((str(team_id), str(round_id)))


def _storage_path(team_id: str) -> Path:
    return _kind_path(team_id, "hypothesis_rounds")


def _round_definition(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return immutable round fields used to detect conflicting id reuse."""
    return {
        key: record.get(key)
        for key in (
            "roundId",
            "program",
            "theme",
            "campaign",
            "question",
            "branch",
            "workflow",
            "agentId",
            "mode",
            "scopeHash",
            "status",
            "candidates",
            "pairwiseComparisons",
            "pareto",
            "metaReview",
            "reviewContextId",
            "executionMode",
            "positionSeed",
            "roles",
            "modelInvocationReceipts",
            "reviewCallBudget",
            "revisionEnvelope",
            "lineage",
            "meetingRefs",
        )
    }


def _closure_hash(payload: Mapping[str, Any]) -> str:
    return _stable_hash(
        {
            "pairwiseComparisons": list(payload.get("pairwiseComparisons") or []),
            "pareto": dict(payload.get("pareto")) if isinstance(payload.get("pareto"), Mapping) else {},
            "metaReview": dict(payload.get("metaReview")) if isinstance(payload.get("metaReview"), Mapping) else {},
            "meetingRefs": list(payload.get("meetingRefs") or []),
            "closedBy": str(payload.get("closedBy") or "").strip(),
        }
    )


def create_hypothesis_round(team_id: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Create one append-only hypothesis review round and fail closed on defects."""
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    request = dict(payload) if isinstance(payload, Mapping) else {}
    scope = _resolve_scope(request)
    now = _utc_now()
    candidates = list(request.get("candidates") or [])
    if not candidates:
        raise ContractValidationError(
            "a hypothesis round requires at least two candidates"
        )
    seed_payload = {
        "scopeHash": scope["scopeHash"],
        "candidateIds": sorted(
            str(item.get("candidateId") or "") for item in candidates if isinstance(item, dict)
        ),
        "createdAt": now,
    }
    round_id = str(request.get("roundId") or "").strip() or f"hround-{_stable_hash(seed_payload)[:16]}"
    record: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "roundId": round_id,
        **scope,
        "status": str(request.get("status") or "open").strip().lower(),
        "candidates": candidates,
        "pairwiseComparisons": list(request.get("pairwiseComparisons") or []),
        "pareto": dict(request.get("pareto")) if isinstance(request.get("pareto"), Mapping) else {
            "paretoFrontCandidateIds": [],
            "dominatedCandidateIds": [],
            "analystAgentId": str(request.get("analystAgentId") or "").strip(),
            "notes": "",
        },
        "metaReview": dict(request.get("metaReview")) if isinstance(request.get("metaReview"), Mapping) else {
            "metaReviewId": f"meta-{_stable_hash({'roundId': round_id, 'createdAt': now})[:12]}",
            "reviewerAgentId": str(request.get("metaReviewerAgentId") or "").strip(),
            "recommendationCandidateId": "",
            "rationale": "",
            "riskNotes": "",
            "accepted": False,
        },
        "lineage": list(request.get("lineage") or []),
        "meetingRefs": list(request.get("meetingRefs") or []),
        "createdAt": now,
        "closedAt": str(request.get("closedAt") or "").strip(),
        "closedBy": str(request.get("closedBy") or "").strip(),
    }
    review_context_id = str(request.get("reviewContextId") or "").strip()
    if review_context_id:
        record.update(
            {
                "reviewContextId": review_context_id,
                "executionMode": str(request.get("executionMode") or "dev")
                .strip()
                .lower(),
                "positionSeed": str(request.get("positionSeed") or "").strip(),
                "roles": dict(request.get("roles"))
                if isinstance(request.get("roles"), Mapping)
                else {},
                "modelInvocationReceipts": [
                    dict(item)
                    for item in list(request.get("modelInvocationReceipts") or [])
                    if isinstance(item, Mapping)
                ],
            }
        )
    if isinstance(request.get("reviewCallBudget"), Mapping) and request[
        "reviewCallBudget"
    ]:
        record["reviewCallBudget"] = dict(request["reviewCallBudget"])
    if isinstance(request.get("revisionEnvelope"), Mapping):
        record["revisionEnvelope"] = dict(request["revisionEnvelope"])
    # Fail closed before persistence: parse validates shape, completeness of
    # candidates and scope; a complete round must pass validate_complete().
    parsed = HypothesisRound.from_dict(record)
    if parsed.status in {"reviewed", "closed"}:
        parsed.validate_complete()
    with _LOCK:
        records = _read_jsonl(_storage_path(normalized_team_id))
        existing = _latest_by_id(records, "roundId", round_id)
        if existing is not None and existing.get("schemaVersion") is not None:
            if _round_definition(existing) != _round_definition(record):
                raise ResearchHypothesisRoundError(
                    "hypothesis round id is already bound to different content"
                )
            return {
                "schemaVersion": SCHEMA_VERSION,
                "teamId": normalized_team_id,
                "status": "reused",
                "round": existing,
                "storagePath": str(_storage_path(normalized_team_id)),
            }
        _append_jsonl(_storage_path(normalized_team_id), record)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "status": "created",
        "round": record,
        "storagePath": str(_storage_path(normalized_team_id)),
    }


def close_hypothesis_round(
    team_id: str,
    round_id: str,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Close one round with complete pair/Pareto/MetaReview/meeting evidence.

    Idempotent: closing an already-closed round with the same closure content
    returns the existing record instead of appending a duplicate.
    """
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_round_id = str(round_id or "").strip()
    if not normalized_round_id:
        raise ResearchHypothesisRoundError("Hypothesis round id is required.")
    request = dict(payload) if isinstance(payload, Mapping) else {}
    with _LOCK:
        records = _read_jsonl(_storage_path(normalized_team_id))
        open_round = _latest_by_id(records, "roundId", normalized_round_id)
        if open_round is None:
            raise ResearchHypothesisRoundNotFoundError("Hypothesis round not found.")
        if str(open_round.get("status") or "") in {"reviewed", "closed"}:
            requested_closure_hash = _closure_hash(request)
            if str(open_round.get("closureHash") or "") != requested_closure_hash:
                raise ResearchHypothesisRoundError(
                    "closed hypothesis round cannot be reused with different closure content"
                )
            return {
                "schemaVersion": SCHEMA_VERSION,
                "teamId": normalized_team_id,
                "status": "reused",
                "closed": True,
                "round": open_round,
                "storagePath": str(_storage_path(normalized_team_id)),
            }
        now = _utc_now()
        closed_record = dict(open_round)
        closed_record["status"] = "closed"
        closed_record["pairwiseComparisons"] = list(request.get("pairwiseComparisons") or [])
        closed_record["pareto"] = dict(request.get("pareto")) if isinstance(request.get("pareto"), Mapping) else {}
        if "metaReview" in request:
            closed_record["metaReview"] = dict(request["metaReview"])
        elif "metaReviewerAgentId" in request:
            meta_review = dict(closed_record["metaReview"])
            meta_review["reviewerAgentId"] = str(request.get("metaReviewerAgentId") or "").strip()
            meta_review["recommendationCandidateId"] = str(
                request.get("recommendationCandidateId") or ""
            ).strip()
            meta_review["rationale"] = str(request.get("metaRationale") or "").strip()
            meta_review["riskNotes"] = str(request.get("metaRiskNotes") or "").strip()
            meta_review["accepted"] = bool(request.get("metaAccepted"))
            closed_record["metaReview"] = meta_review
        closed_record["meetingRefs"] = list(request.get("meetingRefs") or closed_record.get("meetingRefs") or [])
        closed_record["closedAt"] = now
        closed_record["closedBy"] = str(request.get("closedBy") or "").strip()
        closed_record["closureHash"] = _closure_hash(request)
        parsed = HypothesisRound.from_dict(closed_record)
        parsed.validate_complete()
        _append_jsonl(_storage_path(normalized_team_id), closed_record)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "status": "created",
        "closed": True,
        "round": closed_record,
        "storagePath": str(_storage_path(normalized_team_id)),
    }


REUSABLE_ROUND_STATUSES = frozenset({"reviewed", "closed"})


def find_reusable_hypothesis_round(
    team_id: str, round_id: str
) -> dict[str, Any] | None:
    """Return the latest stored record for ``round_id`` when it is reusable.

    The round id is content-addressed, so a stored completed record
    (``reviewed``/``closed``) means the full review executor already ran for
    exactly this round identity and a new generation attempt can reuse the
    stored round without spending review calls.  The round ledger never
    stores failed attempts (those live in the sibling failure ledger), but
    the explicit status allowlist keeps any future failed/superseded status
    fail-closed toward regeneration instead of silently replaying a dead
    record.  Open (incomplete) records are deliberately not reusable: a
    generation must never present an unfinished artifact as the outcome of a
    completed review.
    """
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_round_id = str(round_id or "").strip()
    if not normalized_round_id:
        return None
    with _LOCK:
        records = _read_jsonl(_storage_path(normalized_team_id))
        record = _latest_by_id(records, "roundId", normalized_round_id)
    if record is None or str(record.get("status") or "") not in REUSABLE_ROUND_STATUSES:
        return None
    return record


def _reuse_generation_result(
    team_id: str, round_record: Mapping[str, Any]
) -> dict[str, Any]:
    """Build the generate-path response for an already-stored round.

    Mirrors the shape of a freshly generated result (including the ``review``
    projection reconstructed from the stored immutable round) so callers
    cannot distinguish a reuse replay from the original generation.
    """
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": team_id,
        "status": "reused",
        "round": round_record,
        "storagePath": str(_storage_path(team_id)),
        "closed": str(round_record.get("status") or "") == "closed",
        "review": {
            "contextId": str(round_record.get("reviewContextId") or ""),
            "positionSeed": str(round_record.get("positionSeed") or ""),
            "roles": dict(round_record.get("roles"))
            if isinstance(round_record.get("roles"), Mapping)
            else {},
            "executionMode": str(round_record.get("executionMode") or ""),
        },
    }


def generate_hypothesis_round_from_meeting(
    team_id: str,
    meeting_round_id: str,
    payload: dict[str, Any] | None = None,
    *,
    reflection_runner: Any = None,
    pairwise_runner: Any = None,
    pareto_runner: Any = None,
    metareview_runner: Any = None,
    revision_runner: Any = None,
) -> dict[str, Any]:
    """Generate one closed HypothesisRound after its bound review meetings close.

    The meeting must be a closed ``hypothesis_review`` round whose digest v2
    carries the ``sourceMessageRefs`` evidence trail and whose closure
    decision records all resolve.  The four separated review steps run in
    ``hypothesis_review_executor`` over the bounded review context built by
    ``research_memory_context``; any missing dimension, comparison, Pareto
    classification, or recommendation fails closed before persistence.
    ``payload.meetingRoundIds`` enables the formal candidate-review fan-in:
    every listed meeting remains an independent authority, while their bounded
    digests and decisions are combined only for the review executor. Re-running
    the same ordered group and scope reuses the existing round (append-only
    idempotency).

    Pre-generation dedup: the round id is content-addressed, so it is resolved
    against the ledger before the review executor runs.  A stored completed
    round under the same id is returned directly (zero review calls) instead
    of double-spending the budget and failing at create time with a content
    conflict.  While one generation for a round id is in flight, a concurrent
    trigger fails fast with
    :class:`ResearchHypothesisRoundGenerationInProgressError` (structured
    wait/reuse rejection, never a queued second run); the claim is
    double-checked after acquisition so a trigger that raced the winner's
    create still reuses instead of re-running the executor.

    The executor's explicit DEV/FORMAL fence is driven by the bound meeting's
    server-owned scope ``mode``: only ``mode=formal`` runs ``FORMAL`` (real
    runners + one provider-bound receipt per model call); dev/platform scopes
    and a missing marker fail closed to ``DEV`` fixtures.
    """

    from core.web.services.team_service import assert_team_exists
    from core.web.services.team_workflow import (
        hypothesis_review_executor,
        research_memory_context,
    )
    from core.web.services.team_workflow import meeting_rounds as _meeting_rounds

    normalized_team_id = assert_team_exists(team_id)
    request = dict(payload) if isinstance(payload, Mapping) else {}
    meeting_id = str(meeting_round_id or request.get("meetingRoundId") or "").strip()
    if not meeting_id:
        raise ResearchHypothesisRoundError("meetingRoundId is required")
    requested_meeting_ids = _normalized_str_list(request.get("meetingRoundIds"))
    meeting_ids = requested_meeting_ids or [meeting_id]
    if meeting_id not in meeting_ids:
        raise ResearchHypothesisRoundError(
            "meetingRoundId must be included in meetingRoundIds",
        )
    if len(set(meeting_ids)) != len(meeting_ids):
        raise ResearchHypothesisRoundError("meetingRoundIds contains duplicates")

    # Package-internal read of the meeting stores, matching meeting_runtime.
    # This is a read-only fan-in projection; all source meetings/digests remain
    # canonical and are referenced individually on the resulting round.
    digest_records = _meeting_rounds._read_jsonl(
        _meeting_rounds._digests_path(normalized_team_id)
    )
    decision_records = _meeting_rounds._read_jsonl(
        _meeting_rounds._decisions_path(normalized_team_id)
    )
    meetings: list[dict[str, Any]] = []
    digests: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    meeting_decision_ids: list[list[str]] = []
    for bound_meeting_id in meeting_ids:
        bound_meeting = _meeting_rounds.get_meeting_round(
            normalized_team_id, bound_meeting_id
        )["meetingRound"]
        if str(bound_meeting.get("meetingType") or "") != "hypothesis_review":
            raise ResearchHypothesisRoundError(
                "hypothesis round generation requires hypothesis_review meetings",
            )
        if str(bound_meeting.get("status") or "") != "closed":
            raise ResearchHypothesisRoundError(
                f"hypothesis round generation requires closed meeting {bound_meeting_id}",
            )
        digest_id = str(bound_meeting.get("digestId") or "").strip()
        decision_ids = _normalized_str_list(bound_meeting.get("decisionRefs"))
        if not digest_id or not decision_ids:
            raise ResearchHypothesisRoundError(
                f"closed meeting {bound_meeting_id} is missing digestId or decisionRefs",
            )
        digest = _meeting_rounds._latest_by_id(digest_records, "digestId", digest_id)
        if digest is None:
            raise ResearchHypothesisRoundError(
                f"meeting digest {digest_id} does not resolve",
            )
        if not _normalized_str_list(digest.get("sourceMessageRefs")):
            raise ResearchHypothesisRoundError(
                "hypothesis round generation requires digest v2 sourceMessageRefs",
            )
        resolved_decisions: list[dict[str, Any]] = []
        for decision_id in decision_ids:
            record = _meeting_rounds._latest_by_id(
                decision_records, "decisionId", decision_id
            )
            if record is None:
                raise ResearchHypothesisRoundError(
                    f"decision record {decision_id} does not resolve",
                )
            resolved_decisions.append(record)
        meetings.append(dict(bound_meeting))
        digests.append(dict(digest))
        decisions.extend(resolved_decisions)
        meeting_decision_ids.append(decision_ids)

    meeting = meetings[0]

    selected_ids: list[str] = []
    for bound_meeting in meetings:
        for item in _normalized_str_list(bound_meeting.get("discussionItemRefs")):
            if not item.startswith("hypothesis_candidate:"):
                continue
            candidate_id = item.split(":", 1)[1].strip()
            if not candidate_id:
                continue
            if candidate_id in selected_ids:
                raise ResearchHypothesisRoundError(
                    f"candidate {candidate_id} is bound to multiple review meetings",
                )
            selected_ids.append(candidate_id)
    candidate_inputs = [
        dict(item)
        for item in list(request.get("candidates") or [])
        if isinstance(item, Mapping) and str(item.get("candidateId") or "").strip()
    ]
    input_by_id = {str(item["candidateId"]).strip(): item for item in candidate_inputs}
    missing_inputs = [candidate_id for candidate_id in selected_ids if candidate_id not in input_by_id]
    if missing_inputs:
        raise ResearchHypothesisRoundError(
            "every discussed candidate requires a review input: " + ", ".join(missing_inputs),
        )
    ordered_ids = selected_ids + [
        str(item["candidateId"]).strip()
        for item in candidate_inputs
        if str(item["candidateId"]).strip() not in selected_ids
    ]
    candidates: list[dict[str, Any]] = []
    for candidate_id in ordered_ids:
        item = input_by_id[candidate_id]
        claim = str(item.get("claim") or "").strip()
        if not claim:
            raise ResearchHypothesisRoundError(
                f"candidate {candidate_id} requires a non-empty claim",
            )
        difference = str(item.get("differenceFromAlternatives") or "").strip() or (
            f"{candidate_id} 与其他入选候选的机制路径差异待评审确认"
        )
        candidates.append(
            {
                "candidateId": candidate_id,
                "claim": claim,
                "rationale": str(item.get("rationale") or "").strip(),
                "differenceFromAlternatives": difference,
                "candidateAuthority": str(
                    item.get("candidateAuthority") or ""
                ).strip(),
                "lineageRefs": _normalized_str_list(item.get("lineageRefs")),
                "testablePrediction": str(
                    item.get("testablePrediction") or ""
                ).strip(),
                "falsifier": str(item.get("falsifier") or "").strip(),
                "axisProfile": (
                    dict(item.get("axisProfile"))
                    if isinstance(item.get("axisProfile"), Mapping)
                    else {}
                ),
            }
        )

    participants = _normalized_str_list(meeting.get("participants"))
    role_ids = _normalized_str_list(meeting.get("participantRoleIds"))
    coordinator_agent = ""
    for role, agent in zip(role_ids, participants):
        if role == hypothesis_review_executor.METAREVIEW_ROLE:
            coordinator_agent = agent
            break
    if not coordinator_agent:
        coordinator_agent = str(meeting.get("closedBy") or "").strip()
    if not coordinator_agent:
        raise ResearchHypothesisRoundError(
            "hypothesis review requires a resolvable meeting Coordinator for MetaReview",
        )

    scope = _resolve_scope(
        {
            key: meeting.get(key)
            for key in ("program", "theme", "campaign", "question", "branch", "workflow", "agentId", "mode")
        }
    )
    scope_hash = scope["scopeHash"]
    for bound_meeting in meetings:
        if scope_hash != str(bound_meeting.get("scopeHash") or ""):
            raise ResearchHypothesisRoundError(
                "meeting scope hash mismatch; refusing to generate a hypothesis round",
            )
        if str(bound_meeting.get("question") or "").upper() != str(
            meeting.get("question") or ""
        ).upper():
            raise ResearchHypothesisRoundError(
                "fan-in meetings must belong to the same question",
            )
    round_seed = (
        {"meetingRoundIds": meeting_ids, "scopeHash": scope_hash}
        if requested_meeting_ids
        else {"meetingRoundId": meeting_id, "scopeHash": scope_hash}
    )
    round_id = str(request.get("roundId") or "").strip() or (
        f"hround-{_stable_hash(round_seed)[:12]}"
    )

    # Pre-generation dedup (concurrency guard): both the explicit group id and
    # the derived single-meeting id are content-addressed, so a stored
    # completed round under this id means the review executor already ran for
    # exactly this round identity — reuse it before spending any review calls.
    reusable_round = find_reusable_hypothesis_round(normalized_team_id, round_id)
    if reusable_round is not None:
        return _reuse_generation_result(normalized_team_id, reusable_round)

    closed_prior_rounds = [
        record
        for record in _read_jsonl(_storage_path(normalized_team_id))
        if str(record.get("status") or "") == "closed"
        and str(record.get("scopeHash") or "") == scope_hash
        and str(record.get("roundId") or "") != round_id
    ]
    previous_round_id = str(request.get("previousRoundId") or "").strip()
    prior_round: dict[str, Any] | None = None
    if previous_round_id:
        matched = [
            record
            for record in closed_prior_rounds
            if str(record.get("roundId") or "") == previous_round_id
        ]
        if not matched:
            raise ResearchHypothesisRoundError(
                f"previousRoundId {previous_round_id} does not resolve to a closed round in the same scope",
            )
        prior_round = matched[-1]
    elif closed_prior_rounds:
        prior_round = closed_prior_rounds[-1]

    lineage: list[dict[str, str]] = []
    if prior_round is not None:
        lineage.append({"kind": "round", "id": str(prior_round["roundId"])})
        carried = {
            str(item.get("candidateId") or "")
            for item in list(prior_round.get("candidates") or [])
            if isinstance(item, Mapping)
        }
        lineage.extend(
            {"kind": "candidate", "id": candidate_id}
            for candidate_id in ordered_ids
            if candidate_id not in carried
        )
    else:
        lineage.extend({"kind": "candidate", "id": candidate_id} for candidate_id in ordered_ids)

    aggregate_meeting_id = (
        meeting_id
        if len(meeting_ids) == 1
        else f"meeting-fanin-{_stable_hash({'meetingRoundIds': meeting_ids})[:12]}"
    )
    aggregate_digest_id = (
        str(digests[0].get("digestId") or "")
        if len(digests) == 1
        else f"digest-fanin-{_stable_hash({'digestIds': [item.get('digestId') for item in digests]})[:12]}"
    )

    def _merged_digest_list(field: str) -> list[Any]:
        return [entry for digest in digests for entry in list(digest.get(field) or [])]

    aggregate_digest = {
        "digestId": aggregate_digest_id,
        "summary": "\n\n".join(
            str(item.get("summary") or "").strip() for item in digests
        ).strip(),
        "agendaSummary": "\n\n".join(
            str(item.get("agendaSummary") or "").strip() for item in digests
        ).strip(),
        "agreements": _merged_digest_list("agreements"),
        "disagreements": _merged_digest_list("disagreements"),
        "actionItems": _merged_digest_list("actionItems"),
        "risks": _merged_digest_list("risks"),
        "knowledgeCandidates": _merged_digest_list("knowledgeCandidates"),
        "sourceMessageRefs": [
            ref
            for digest in digests
            for ref in _normalized_str_list(digest.get("sourceMessageRefs"))
        ],
        "contentHash": _stable_hash(
            {
                "digestIds": [item.get("digestId") for item in digests],
                "contentHashes": [item.get("contentHash") for item in digests],
            }
        ),
    }
    aggregate_meeting = {
        **meeting,
        "meetingRoundId": aggregate_meeting_id,
        "discussionItemRefs": [
            ref
            for bound_meeting in meetings
            for ref in _normalized_str_list(bound_meeting.get("discussionItemRefs"))
        ],
    }
    context = research_memory_context.build_hypothesis_review_context(
        meeting_round=aggregate_meeting,
        digest=aggregate_digest,
        decisions=decisions,
        candidates=candidates,
        prior_round=prior_round,
        extra_evidence_refs=_normalized_str_list(request.get("evidenceRefs")),
    )
    # The closed meeting's server-owned scope mode is the explicit execution
    # fence authority: only ``mode=formal`` runs the FORMAL review.  Dev and
    # platform scopes — and any meeting missing the marker — fail closed to
    # the deterministic DEV path; FORMAL is never inferred from runner
    # presence or payload hints.
    review_mode = str(meeting.get("mode") or "").strip().lower()
    execution_mode = (
        hypothesis_review_executor.HypothesisReviewExecutionMode.FORMAL
        if review_mode
        == hypothesis_review_executor.HypothesisReviewExecutionMode.FORMAL.value
        else hypothesis_review_executor.HypothesisReviewExecutionMode.DEV
    )
    if execution_mode is hypothesis_review_executor.HypothesisReviewExecutionMode.FORMAL:
        # FORMAL runners bind every model call to the meeting's server-owned
        # WorkflowRun receipt authority; a formal meeting without one fails
        # closed inside the receipt-bound runner instead of degrading to
        # unattributed model output.
        receipt_authority = meeting.get("modelInvocationReceiptAuthority")
        context["teamId"] = normalized_team_id
        context["questionId"] = str(meeting.get("question") or "")
        context["_modelInvocationReceiptAuthority"] = (
            dict(receipt_authority) if isinstance(receipt_authority, Mapping) else None
        )
    # In-flight guard: claim the round id for this process before the
    # executor runs, double-check the ledger under the claim (a concurrent
    # winner may have stored the round between the pre-read above and this
    # claim), and always release in a finally so a failed run never wedges
    # the round id.  The claim is held only as registry membership; it never
    # nests with _LOCK.
    if not _claim_round_generation(normalized_team_id, round_id):
        raise ResearchHypothesisRoundGenerationInProgressError(
            normalized_team_id, round_id
        )
    try:
        reusable_round = find_reusable_hypothesis_round(
            normalized_team_id, round_id
        )
        if reusable_round is not None:
            return _reuse_generation_result(normalized_team_id, reusable_round)
        # FORMAL passes the exact Stage-1 review call budget it derived from the
        # bounded context; the executor cross-validates the wiring and fails
        # closed on any disagreement before spending a single review call.
        formal_execution = (
            execution_mode is hypothesis_review_executor.HypothesisReviewExecutionMode.FORMAL
        )
        review = hypothesis_review_executor.execute_hypothesis_review(
            context,
            round_id=round_id,
            execution_mode=execution_mode,
            reflection_runner=reflection_runner,
            pairwise_runner=pairwise_runner,
            pareto_runner=pareto_runner,
            metareview_runner=metareview_runner,
            revision_runner=revision_runner,
            reviewer_assignments={"metareview": coordinator_agent},
            position_seed=str(request.get("positionSeed") or "").strip(),
            **(
                {
                    "expected_review_call_budget": review_call_budget_for(
                        len(context.get("candidates") or [])
                    ).to_dict()
                }
                if formal_execution
                else {}
            ),
        )
        meeting_refs: list[dict[str, str]] = []
        for bound_meeting, digest, decision_ids in zip(
            meetings, digests, meeting_decision_ids
        ):
            meeting_refs.extend(
                [
                    {
                        "kind": "meeting_round",
                        "id": str(bound_meeting.get("meetingRoundId") or ""),
                    },
                    {"kind": "meeting_digest", "id": str(digest.get("digestId") or "")},
                    *[
                        {"kind": "decision_record", "id": decision_id}
                        for decision_id in decision_ids
                    ],
                ]
            )
        result = create_hypothesis_round(
            normalized_team_id,
            {
                **scope,
                "roundId": round_id,
                "candidates": review["candidates"],
                "pairwiseComparisons": review["pairwiseComparisons"],
                "pareto": review["pareto"],
                "metaReview": review["metaReview"],
                "reviewContextId": review["reviewContextId"],
                "executionMode": review["executionMode"],
                "positionSeed": review["positionSeed"],
                "roles": review["roles"],
                "modelInvocationReceipts": review.get("modelInvocationReceipts", []),
                "reviewCallBudget": review.get("reviewCallBudget"),
                **(
                    {"revisionEnvelope": dict(review["revisionEnvelope"])}
                    if isinstance(review.get("revisionEnvelope"), Mapping)
                    else {}
                ),
                "meetingRefs": meeting_refs,
                "lineage": lineage,
                "status": "closed",
                "closedBy": coordinator_agent,
                "closedAt": _utc_now(),
            },
        )
        result["closed"] = True
        result["review"] = {
            "contextId": review["reviewContextId"],
            "positionSeed": review["positionSeed"],
            "roles": review["roles"],
            "executionMode": review["executionMode"],
        }
        return result
    finally:
        _release_round_generation(normalized_team_id, round_id)


def list_hypothesis_rounds(team_id: str) -> dict[str, Any]:
    """List the latest record of every hypothesis round for a team."""
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    with _LOCK:
        records, corrupt_count = _read_store(_storage_path(normalized_team_id))
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        latest[str(record.get("roundId") or "")] = record
    rounds = sorted(latest.values(), key=lambda item: str(item.get("createdAt") or ""))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "roundCount": len(rounds),
        "rounds": rounds,
        "corruptQuarantinedLineCount": corrupt_count,
        "storagePath": str(_storage_path(normalized_team_id)),
    }


def get_hypothesis_round(team_id: str, round_id: str) -> dict[str, Any]:
    """Return the latest record of one hypothesis round."""
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_round_id = str(round_id or "").strip()
    with _LOCK:
        records, corrupt_count = _read_store(_storage_path(normalized_team_id))
        record = _latest_by_id(records, "roundId", normalized_round_id)
    if record is None:
        raise ResearchHypothesisRoundNotFoundError("Hypothesis round not found.")
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "round": record,
        "corruptQuarantinedLineCount": corrupt_count,
        "storagePath": str(_storage_path(normalized_team_id)),
    }


# ---------------------------------------------------------------------------
# failure ledger
#
# ``hypothesis_rounds.jsonl`` is the append-only authority for generated
# rounds; a generation that fails closed must never leave a phantom round
# record there.  Failure traces therefore live in a sibling ledger,
# ``hypothesis_round_failures.jsonl``, so the round store (idempotency,
# lineage resolution, listings) keeps byte-identical behaviour while every
# failed or blocked generation attempt stays visible, correlatable and
# resolvable.


def _failure_storage_path(team_id: str) -> Path:
    return _kind_path(team_id, "hypothesis_round_failures")


def _json_safe(value: Any) -> Any:
    """Coerce a context payload into JSON-safe primitives for the ledger."""
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def record_hypothesis_round_failure(
    team_id: str, payload: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Append one failure/blocked trace for a round generation attempt.

    This is a best-effort internal recorder for the generation chain: it
    does not require team existence (the caller already resolved the team
    when the meeting closed) so the failure path keeps the fewest possible
    failure modes.  ``status`` is ``failed`` (generation attempted and
    errored) or ``blocked`` (prerequisites not ready, e.g. sibling reviews
    still open).  Records are append-only; a later successful generation
    resolves matching open records through
    :func:`resolve_hypothesis_round_failures`.
    """
    request = dict(payload) if isinstance(payload, Mapping) else {}
    status = str(request.get("status") or "failed").strip().lower()
    if status not in FAILURE_OPEN_STATUSES:
        raise ResearchHypothesisRoundError(
            f"unsupported hypothesis round failure status: {status}"
        )
    failure_code = str(request.get("failureCode") or "").strip()
    if not failure_code:
        raise ResearchHypothesisRoundError(
            "a hypothesis round failure record requires a non-empty failureCode"
        )
    now = _utc_now()
    meeting_round_ids = _normalized_str_list(request.get("meetingRoundIds"))
    round_index_value = request.get("roundIndex")
    try:
        round_index = int(round_index_value) if round_index_value is not None else None
    except (TypeError, ValueError):
        round_index = None
    failure_id = (
        f"hrfail-{_stable_hash(
            {
                "status": status,
                "failureCode": failure_code,
                "roundId": str(request.get("roundId") or "").strip(),
                "meetingRoundIds": meeting_round_ids,
                "selectionId": str(request.get("selectionId") or "").strip(),
                "createdAt": now,
            }
        )[:12]}"
    )
    context = request.get("context")
    record: dict[str, Any] = {
        "schemaVersion": FAILURE_SCHEMA_VERSION,
        "recordKind": FAILURE_RECORD_KIND,
        "failureId": failure_id,
        "status": status,
        "failureCode": failure_code,
        "reason": str(request.get("reason") or "").strip(),
        "errorType": str(request.get("errorType") or "").strip(),
        "roundId": str(request.get("roundId") or "").strip(),
        "meetingRoundIds": meeting_round_ids,
        "selectionId": str(request.get("selectionId") or "").strip(),
        "roundIndex": round_index,
        "questionId": str(request.get("questionId") or "").strip(),
        "workflowRunId": str(request.get("workflowRunId") or "").strip(),
        "scopeHash": str(request.get("scopeHash") or "").strip(),
        "retryHint": str(request.get("retryHint") or "").strip(),
        "context": _json_safe(context) if isinstance(context, Mapping) else {},
        "createdAt": now,
        "resolvedAt": "",
        "resolvedByRoundId": "",
    }
    with _LOCK:
        _append_jsonl(_failure_storage_path(team_id), record)
    return {
        "schemaVersion": FAILURE_SCHEMA_VERSION,
        "teamId": team_id,
        "status": "recorded",
        "failure": record,
        "storagePath": str(_failure_storage_path(team_id)),
    }


def _latest_failure_records(team_id: str) -> list[dict[str, Any]]:
    records = _read_jsonl(_failure_storage_path(team_id))
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        failure_id = str(record.get("failureId") or "")
        latest[failure_id] = record
    return list(latest.values())


def list_hypothesis_round_failures(
    team_id: str, *, unresolved_only: bool = False
) -> dict[str, Any]:
    """List the latest failure trace of every round generation failure."""
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    with _LOCK:
        records = _latest_failure_records(normalized_team_id)
    open_count = sum(
        1
        for record in records
        if str(record.get("status") or "") in FAILURE_OPEN_STATUSES
    )
    if unresolved_only:
        records = [
            record
            for record in records
            if str(record.get("status") or "") in FAILURE_OPEN_STATUSES
        ]
    records = sorted(records, key=lambda item: str(item.get("createdAt") or ""))
    return {
        "schemaVersion": FAILURE_SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "failureCount": len(records),
        "openFailureCount": open_count,
        "failures": records,
        "storagePath": str(_failure_storage_path(normalized_team_id)),
    }


def resolve_hypothesis_round_failures(
    team_id: str,
    *,
    resolved_by_round_id: str = "",
    round_id: str = "",
    selection_id: str = "",
    round_index: int | None = None,
    meeting_round_ids: list[str] | None = None,
) -> int:
    """Mark open failure records resolved by one successful round generation.

    A record resolves when the successful generation correlates with it by
    round id, by selection id + round index, or by any shared bound meeting
    id.  Resolution appends updated copies (the ledger stays append-only)
    and returns how many open records were resolved.
    """
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    resolved_by_round_id = str(resolved_by_round_id or "").strip()
    normalized_round_id = str(round_id or "").strip()
    normalized_selection_id = str(selection_id or "").strip()
    target_meeting_ids = set(_normalized_str_list(meeting_round_ids))
    with _LOCK:
        records = _latest_failure_records(normalized_team_id)
        resolved: list[dict[str, Any]] = []
        for record in records:
            if str(record.get("status") or "") not in FAILURE_OPEN_STATUSES:
                continue
            matched = bool(
                normalized_round_id
                and str(record.get("roundId") or "") == normalized_round_id
            )
            if (
                not matched
                and normalized_selection_id
                and str(record.get("selectionId") or "") == normalized_selection_id
                and round_index is not None
            ):
                try:
                    matched = int(record.get("roundIndex")) == round_index
                except (TypeError, ValueError):
                    matched = False
            if not matched and target_meeting_ids:
                matched = bool(
                    set(_normalized_str_list(record.get("meetingRoundIds")))
                    & target_meeting_ids
                )
            if matched:
                resolved.append(record)
        if resolved:
            now = _utc_now()
            for record in resolved:
                _append_jsonl(
                    _failure_storage_path(normalized_team_id),
                    {
                        **record,
                        "status": RESOLVED_FAILURE_STATUS,
                        "resolvedAt": now,
                        "resolvedByRoundId": resolved_by_round_id,
                    },
                )
    return len(resolved)
