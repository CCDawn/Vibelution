"""Hypothesis-first orchestration chain (HF-4).

Owns the append-only chain ledger that wires the hypothesis-first event chain:

- selection -> first hypothesis-review meeting auto-open (round 1), with the
  room ``roundId`` <-> ``meetingRoundId`` two-way binding produced by
  ``meeting_runtime.open_hypothesis_review_meeting``;
- meeting closure -> ``request_new_evidence`` decisions carrying a valid
  ``searchEnvelope`` create stage-1 collection through the existing
  ``research_knowledge_collection_facade`` and dispatch its existing background
  search runner (idempotent per child run; the facade itself stays idempotent
  by scopeHash and no graph recursion happens here);
- child collection handoff -> parent run ``hypothesis_design`` readiness
  re-check (always outside any writer transaction) plus the next review
  meeting auto-open with a continuous lineage chain;
- ``chain_state`` read model consumed by the readiness evaluators for the
  ``hypothesis_first_meeting_open`` / ``knowledge_gap_pending`` /
  ``hypothesis_round_unconverged`` / ``template_baseline_missing`` blockers.

The chain ledger is a JSONL store next to the other ``research_workflow``
stores.  It never writes to the workflow ledger directly; parent runs are only
nudged through the command service with deterministic idempotency keys, so
replays after an interruption never duplicate attempts, meetings, or
collection requests.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.infrastructure import developer_sandbox
from core.research.workflow.contracts import ContractValidationError, scope_hash_for
from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID

SCHEMA_VERSION = 1
DEFAULT_ROUND_BUDGET = 3
MAX_ROUND_BUDGET = 5
COLLECTION_REQUEST_KIND = "collection_request"
REVIEW_ROUND_LINK_KIND = "review_round_link"
CANDIDATE_KIND = "hypothesis_candidate"
QUESTION_RESET_AUDIT_KIND = "question_reset_audit"
REQUEST_EVIDENCE_DECISION = "request_new_evidence"
HYPOTHESIS_REVIEW_MEETING_TYPE = "hypothesis_review"
CANDIDATE_GENERATION_MEETING_TYPE = "hypothesis_candidate_generation"
HYPOTHESIS_DESIGN_NODE_ID = "hypothesis_design"
_HYPOTHESIS_FIRST_WORKFLOW = "hypothesis_first"
_DEFAULT_BRANCH = "main"
_OPERATOR_AGENT_ID = "operator"
_SCOPE_FIELDS = ("program", "theme", "campaign", "question", "branch", "workflow")
_TERMINAL_RUN_STATUSES = frozenset({"succeeded", "failed", "cancelled", "archived"})
_ACTIVE_ATTEMPT_STATUSES = frozenset(
    {"starting", "dispatching", "running", "waiting_human"}
)
_ACTIVE_MEETING_STATUSES = frozenset({"open", "summarizing", "awaiting_approval"})
_ACTIVE_COLLECTION_STATUSES = frozenset(
    {"pending", "queued", "starting", "dispatching", "running", "collecting"}
)

PROJECT_ROOT = Path(__file__).resolve().parents[5]
_LOCK = threading.RLock()
_RECOVERY_LOCKS: dict[str, threading.Lock] = {}


class HypothesisFirstChainError(RuntimeError):
    """Base error for hypothesis-first chain orchestration."""


class HypothesisFirstChainNotFoundError(HypothesisFirstChainError):
    """Raised when a chain record (collection request / link) does not exist."""


class StaleDigestError(HypothesisFirstChainError):
    """Raised when approve-digest receives a stale digest content hash."""

    def __init__(self, message: str, *, expected: str = "", actual: str = ""):
        super().__init__(message)
        self.code = "stale_digest"
        self.expected = expected
        self.actual = actual


# ---------------------------------------------------------------------------
# storage primitives (same discipline as hypothesis_selection)


def _project_root() -> Path:
    return Path(PROJECT_ROOT)


def _safe_team_id(team_id: str) -> str:
    from core.web.services.team_workflow.storage_ids import safe_storage_component

    return safe_storage_component(team_id, fallback="team")


def _question_requested_evidence(team_id: str, question_id: str) -> bool:
    """True when this question's persisted review decisions asked for evidence.

    A ``request_new_evidence`` decision (valid or not) proves the discussion
    wanted collection, so the collection-ready waiver must not apply.  Scope
    by question through the decision's meeting round: decision records carry
    no question field, and a team-wide scan would let one question's request
    block every other question's waiver (fatal for the 125-question batch).
    """
    from core.web.services.team_workflow import meeting_rounds

    normalized_question = str(question_id or "").strip().upper()
    if not normalized_question:
        return False
    try:
        question_by_meeting = {
            str(meeting.get("meetingRoundId") or ""): str(
                meeting.get("question") or ""
            ).upper()
            for meeting in meeting_rounds.list_meeting_rounds(team_id)["meetings"]
        }
    except Exception:
        # Unreadable meetings fail closed: cannot prove the request belongs to
        # another question, so do not waive.
        return True
    root = developer_sandbox.seeded_sandbox_workspace_path(
        _project_root(),
        "teams",
        _safe_team_id(team_id),
    )
    decisions_path = root / "research_workflow" / "decision_records.jsonl"
    if not decisions_path.exists():
        return False
    try:
        records = _read_jsonl(decisions_path)
    except OSError:
        # Unreadable decision store fails closed, matching the unreadable
        # meetings branch above: an existing evidence request cannot be
        # disproven, so the waiver must not apply.
        return True
    return any(
        str(record.get("decision") or "") == "request_new_evidence"
        and question_by_meeting.get(
            str(record.get("meetingRoundId") or ""), normalized_question
        )
        == normalized_question
        for record in records
    )


def _storage_path(team_id: str) -> Path:
    root = developer_sandbox.seeded_sandbox_workspace_path(
        _project_root(),
        "teams",
        _safe_team_id(team_id),
    )
    return root / "research_workflow" / "hypothesis_first_chain.jsonl"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    from core.web.services.team_workflow.storage_durability import read_jsonl_tolerant

    return read_jsonl_tolerant(path)


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    from core.web.services.team_workflow.storage_durability import append_jsonl_locked

    append_jsonl_locked(path, record)


def _latest_by_id(
    records: list[dict[str, Any]], field: str, record_id: str
) -> dict[str, Any] | None:
    matched = [record for record in records if str(record.get(field) or "") == record_id]
    return matched[-1] if matched else None


def _normalized_str_list(value: Any) -> list[str]:
    return [str(item or "").strip() for item in list(value or []) if str(item or "").strip()]


def _rewrite_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    """Replace one JSONL ledger atomically after a scoped reset has been checked."""
    from .atomic_fs import atomic_write_text

    payload = "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for record in records
    )
    atomic_write_text(path, payload)


def _latest_records(records: list[dict[str, Any]], field: str) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        record_id = str(record.get(field) or "").strip()
        if record_id:
            latest[record_id] = record
    return latest


def _question_reset_snapshot(team_id: str, question_id: str) -> dict[str, Any]:
    """Read the exact question-owned artifacts before a guarded reset.

    The question is the ownership boundary. Meeting digests, decisions and
    hypothesis rounds do not always carry ``questionId`` themselves, so they
    are reached only through this question's meeting ids.  This prevents one
    question's cleanup from sweeping unrelated team research.
    """
    from core.web.services.team_workflow import (
        hypothesis_rounds,
        hypothesis_selection,
        meeting_rounds,
    )

    normalized_question_id = str(question_id or "").strip().upper()
    chain_records = _read_jsonl(_storage_path(team_id))
    selection_records = hypothesis_selection._read_jsonl(hypothesis_selection._storage_path(team_id))
    meeting_records = meeting_rounds._read_jsonl(meeting_rounds._rounds_path(team_id))
    digest_records = meeting_rounds._read_jsonl(meeting_rounds._digests_path(team_id))
    decision_records = meeting_rounds._read_jsonl(meeting_rounds._decisions_path(team_id))
    hypothesis_round_records = hypothesis_rounds._read_jsonl(
        hypothesis_rounds._storage_path(team_id)
    )

    meeting_latest = _latest_records(meeting_records, "meetingRoundId")
    chain_links = [
        record
        for record in chain_records
        if str(record.get("recordKind") or "") == REVIEW_ROUND_LINK_KIND
        and str(record.get("questionId") or "").strip().upper() == normalized_question_id
    ]
    linked_meeting_ids = {
        str(record.get("meetingRoundId") or "").strip()
        for record in chain_links
        if str(record.get("meetingRoundId") or "").strip()
    }
    target_meeting_ids = {
        meeting_id
        for meeting_id, meeting in meeting_latest.items()
        if str(meeting.get("question") or "").strip().upper() == normalized_question_id
    } | linked_meeting_ids
    target_meetings = {
        meeting_id: meeting_latest[meeting_id]
        for meeting_id in target_meeting_ids
        if meeting_id in meeting_latest
    }
    target_selection_ids = {
        str(record.get("selectionId") or "").strip()
        for record in selection_records
        if str(record.get("questionId") or "").strip().upper() == normalized_question_id
        and str(record.get("selectionId") or "").strip()
    }
    target_rounds = {
        round_id: record
        for round_id, record in _latest_records(hypothesis_round_records, "roundId").items()
        if str(record.get("question") or "").strip().upper() == normalized_question_id
        or any(
            isinstance(ref, Mapping)
            and str(ref.get("kind") or "") == "meeting_round"
            and str(ref.get("id") or "").strip() in target_meeting_ids
            for ref in list(record.get("meetingRefs") or [])
        )
    }

    target_chain_records = [
        record
        for record in chain_records
        if str(record.get("recordKind") or "") != QUESTION_RESET_AUDIT_KIND
        and str(record.get("questionId") or "").strip().upper() == normalized_question_id
    ]
    candidate_ids = {
        str(record.get("candidateId") or "").strip()
        for record in target_chain_records
        if str(record.get("recordKind") or "") == CANDIDATE_KIND
        and str(record.get("candidateId") or "").strip()
    }
    target_collection_requests = [
        record
        for record in _collection_requests(chain_records)
        if str(record.get("questionId") or "").strip().upper() == normalized_question_id
    ]
    request_ids = {
        str(record.get("requestId") or "").strip()
        for record in target_collection_requests
        if str(record.get("requestId") or "").strip()
    }
    collection_run_ids = {
        str(record.get("collectionRunId") or "").strip()
        for record in target_collection_requests
        if str(record.get("collectionRunId") or "").strip()
    }
    impact = {
        "candidateCount": len(candidate_ids),
        "selectionCount": len(target_selection_ids),
        "meetingCount": len(target_meetings),
        "hypothesisRoundCount": len(target_rounds),
        "collectionRequestCount": len(request_ids),
        "collectionRunCount": 0,
    }
    active_meetings = [
        meeting_id
        for meeting_id, meeting in target_meetings.items()
        if str(meeting.get("status") or "").strip().lower() in _ACTIVE_MEETING_STATUSES
    ]
    active_requests = [
        request_id
        for request_id, request in _latest_records(
            [
                record
                for record in target_chain_records
                if str(record.get("recordKind") or "") == COLLECTION_REQUEST_KIND
            ],
            "requestId",
        ).items()
        # A legacy pending request with no child run cannot represent work that
        # can still mutate data. Keep the guard for every linked active request,
        # while allowing that unlinked residue to be reset.
        if str(request.get("status") or "").strip().lower() in _ACTIVE_COLLECTION_STATUSES
        and str(request.get("collectionRunId") or "").strip()
    ]
    return {
        "questionId": normalized_question_id,
        "chainRecords": chain_records,
        "selectionRecords": selection_records,
        "meetingRecords": meeting_records,
        "digestRecords": digest_records,
        "decisionRecords": decision_records,
        "hypothesisRoundRecords": hypothesis_round_records,
        "targetMeetingIds": target_meeting_ids,
        "targetRoundIds": set(target_rounds),
        "collectionRunIds": collection_run_ids,
        "impact": impact,
        "activeMeetingIds": active_meetings,
        "activeRequestIds": active_requests,
    }


def preview_question_reset(team_id: str, question_id: str) -> dict[str, Any]:
    """Return a non-mutating, question-scoped reset preview for the confirm UI."""
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    snapshot = _question_reset_snapshot(normalized_team_id, question_id)
    from core.web.services.team_workflow.source_collection import (
        runs as source_collection_runs,
    )

    active_meetings = list(snapshot["activeMeetingIds"])
    active_requests = list(snapshot["activeRequestIds"])
    collection_preview = source_collection_runs.preview_source_collection_runs_reset(
        normalized_team_id,
        set(snapshot["collectionRunIds"]),
    )
    snapshot["impact"]["collectionRunCount"] = int(collection_preview.get("runCount") or 0)
    if active_meetings:
        blocking_reason = "本题仍有进行中的讨论，请先结束或停止讨论后再重置。"
    elif active_requests:
        blocking_reason = "本题的资料搜集仍在进行，请等待结束或先停止任务。"
    elif not collection_preview.get("canReset"):
        blocking_reason = str(collection_preview.get("blockingReason") or "本题资料运行暂不能重置。")
    else:
        blocking_reason = ""
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "questionId": snapshot["questionId"],
        "canReset": not blocking_reason,
        "blockingReason": blocking_reason,
        "impact": snapshot["impact"],
    }


def reset_question_chain(
    team_id: str,
    question_id: str,
    *,
    confirmation_question_id: str,
) -> dict[str, Any]:
    """Delete only one question's completed hypothesis-first working artifacts.

    The title/question archive and all other questions are intentionally outside
    this operation.  A successful reset leaves a compact audit event, then
    directs the product back to candidate generation.
    """
    from core.web.services.team_service import assert_team_exists
    from core.web.services.team_workflow import (
        hypothesis_rounds,
        hypothesis_selection,
        meeting_rounds,
    )
    from core.web.services.team_workflow.source_collection import (
        runs as source_collection_runs,
    )

    normalized_team_id = assert_team_exists(team_id)
    normalized_question_id = str(question_id or "").strip().upper()
    if not normalized_question_id:
        raise HypothesisFirstChainError("Question id is required.")
    if str(confirmation_question_id or "").strip().upper() != normalized_question_id:
        raise HypothesisFirstChainError("请输入当前题号后再确认重置。")

    with _LOCK, hypothesis_selection._LOCK, meeting_rounds._LOCK, hypothesis_rounds._LOCK:
        snapshot = _question_reset_snapshot(normalized_team_id, normalized_question_id)
        if snapshot["activeMeetingIds"]:
            raise HypothesisFirstChainError("本题仍有进行中的讨论，请先结束或停止讨论后再重置。")
        if snapshot["activeRequestIds"]:
            raise HypothesisFirstChainError("本题的资料搜集仍在进行，请等待结束或先停止任务。")

        source_preview = source_collection_runs.preview_source_collection_runs_reset(
            normalized_team_id,
            set(snapshot["collectionRunIds"]),
        )
        if not source_preview.get("canReset"):
            raise HypothesisFirstChainError(
                str(source_preview.get("blockingReason") or "本题资料运行暂不能重置。")
            )
        snapshot["impact"]["collectionRunCount"] = int(source_preview.get("runCount") or 0)
        target_meeting_ids = set(snapshot["targetMeetingIds"])
        target_round_ids = set(snapshot["targetRoundIds"])
        chain_records = [
            record
            for record in snapshot["chainRecords"]
            if not (
                str(record.get("recordKind") or "") != QUESTION_RESET_AUDIT_KIND
                and str(record.get("questionId") or "").strip().upper() == normalized_question_id
            )
        ]
        audit_record = {
            "schemaVersion": SCHEMA_VERSION,
            "recordKind": QUESTION_RESET_AUDIT_KIND,
            "resetId": f"hf-reset-{_stable_hash({'teamId': normalized_team_id, 'questionId': normalized_question_id, 'at': _utc_now()})[:16]}",
            "questionId": normalized_question_id,
            "resetAt": _utc_now(),
            "removed": dict(snapshot["impact"]),
        }
        chain_records.append(audit_record)
        selection_records = [
            record
            for record in snapshot["selectionRecords"]
            if str(record.get("questionId") or "").strip().upper() != normalized_question_id
        ]
        meeting_records = [
            record
            for record in snapshot["meetingRecords"]
            if str(record.get("meetingRoundId") or "").strip() not in target_meeting_ids
        ]
        digest_records = [
            record
            for record in snapshot["digestRecords"]
            if str(record.get("meetingRoundId") or "").strip() not in target_meeting_ids
        ]
        decision_records = [
            record
            for record in snapshot["decisionRecords"]
            if str(record.get("meetingRoundId") or "").strip() not in target_meeting_ids
        ]
        hypothesis_round_records = [
            record
            for record in snapshot["hypothesisRoundRecords"]
            if str(record.get("roundId") or "").strip() not in target_round_ids
        ]
        writes = (
            (_storage_path(normalized_team_id), chain_records),
            (hypothesis_selection._storage_path(normalized_team_id), selection_records),
            (meeting_rounds._rounds_path(normalized_team_id), meeting_records),
            (meeting_rounds._digests_path(normalized_team_id), digest_records),
            (meeting_rounds._decisions_path(normalized_team_id), decision_records),
            (hypothesis_rounds._storage_path(normalized_team_id), hypothesis_round_records),
        )
        originals = {
            path: path.read_text(encoding="utf-8") if path.exists() else ""
            for path, _records_to_write in writes
        }
        try:
            for path, records_to_write in writes:
                _rewrite_jsonl(path, records_to_write)
            # Source runs are the final destructive step.  A ledger write
            # failure must leave the collection data untouched; a late source
            # guard must restore these ledgers before it is surfaced.
            source_collection_runs.reset_source_collection_runs_for_question(
                normalized_team_id,
                set(snapshot["collectionRunIds"]),
            )
        except Exception as exc:
            for path, original in originals.items():
                try:
                    from .atomic_fs import atomic_write_text

                    atomic_write_text(path, original)
                except OSError:
                    pass
            if isinstance(exc, OSError):
                raise HypothesisFirstChainError("本题运行重置失败，原数据已尝试恢复。") from exc
            raise

    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "questionId": normalized_question_id,
        "removed": dict(snapshot["impact"]),
        "nextAction": {"targetNodeId": "hf_generation", "label": "生成候选假说"},
    }


# ---------------------------------------------------------------------------
# chain ledger reads


def _records(team_id: str) -> list[dict[str, Any]]:
    with _LOCK:
        return _read_jsonl(_storage_path(team_id))


def _collection_requests(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        if str(record.get("recordKind") or "") != COLLECTION_REQUEST_KIND:
            continue
        latest[str(record.get("requestId") or "")] = record
    return sorted(latest.values(), key=lambda item: str(item.get("createdAt") or ""))


def _review_round_links(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for record in records:
        if str(record.get("recordKind") or "") != REVIEW_ROUND_LINK_KIND:
            continue
        latest[str(record.get("linkId") or "")] = record
    return sorted(latest.values(), key=lambda item: int(item.get("roundIndex") or 0))


def list_collection_requests(team_id: str, *, question_id: str = "") -> dict[str, Any]:
    """List the latest record of every collection request, newest-last."""
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_question_id = str(question_id or "").strip().upper()
    requests = _collection_requests(_records(normalized_team_id))
    if normalized_question_id:
        requests = [
            record
            for record in requests
            if str(record.get("questionId") or "").upper() == normalized_question_id
        ]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "requestCount": len(requests),
        "requests": requests,
        "storagePath": str(_storage_path(normalized_team_id)),
    }


def list_review_round_links(team_id: str, *, question_id: str = "") -> dict[str, Any]:
    """List review-round lineage links ordered by round index."""
    from core.web.services.team_service import assert_team_exists

    normalized_team_id = assert_team_exists(team_id)
    normalized_question_id = str(question_id or "").strip().upper()
    links = _review_round_links(_records(normalized_team_id))
    if normalized_question_id:
        links = [
            record
            for record in links
            if str(record.get("questionId") or "").upper() == normalized_question_id
        ]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "linkCount": len(links),
        "links": links,
        "storagePath": str(_storage_path(normalized_team_id)),
    }


# ---------------------------------------------------------------------------
# meeting opening (selection -> round 1; handoff -> round N)


def _resolve_hypothesis_participants(
    team_id: str,
    room_id: str,
    meeting_type: str,
) -> dict[str, Any]:
    from core.web.services.team_workflow import meeting_runtime

    return meeting_runtime.resolve_hypothesis_meeting_participants(
        team_id, room_id, meeting_type
    )


def _record_review_round_link(
    team_id: str,
    *,
    meeting_round_id: str,
    previous_meeting_round_id: str,
    selection_id: str,
    collection_request_id: str,
    question_id: str,
    round_index: int,
    round_budget: int = DEFAULT_ROUND_BUDGET,
) -> dict[str, Any]:
    link_id = f"hf-link-{_stable_hash({'meetingRoundId': meeting_round_id, 'roundIndex': round_index})[:16]}"
    record = {
        "schemaVersion": SCHEMA_VERSION,
        "recordKind": REVIEW_ROUND_LINK_KIND,
        "linkId": link_id,
        "meetingRoundId": meeting_round_id,
        "previousMeetingRoundId": previous_meeting_round_id,
        "selectionId": selection_id,
        "collectionRequestId": collection_request_id,
        "questionId": question_id,
        "roundIndex": round_index,
        # Persist the effective budget so chain_state reads the raised limit
        # (links written before this field fall back to the default).
        "roundBudget": int(round_budget or DEFAULT_ROUND_BUDGET),
        "createdAt": _utc_now(),
    }
    with _LOCK:
        records = _read_jsonl(_storage_path(team_id))
        existing = _latest_by_id(
            [item for item in records if str(item.get("recordKind") or "") == REVIEW_ROUND_LINK_KIND],
            "meetingRoundId",
            meeting_round_id,
        )
        if existing is not None:
            for key in ("previousMeetingRoundId", "collectionRequestId", "selectionId", "roundIndex", "roundBudget"):
                existing_value = existing.get(key)
                # Links written before roundBudget existed replay fine.
                if key == "roundBudget" and existing_value is None:
                    continue
                if existing_value != record.get(key):
                    raise HypothesisFirstChainError(
                        f"review round link for {meeting_round_id} is already bound to different content"
                    )
            return existing
        _append_jsonl(_storage_path(team_id), record)
    return record


def open_review_meeting_for_selection(
    team_id: str,
    selection: Mapping[str, Any],
    *,
    agent_runner: Any = None,
    background: bool = True,
    round_index: int = 1,
    previous_meeting_round_id: str = "",
    collection_request_id: str = "",
    meeting_round_id: str = "",
    round_budget: int = DEFAULT_ROUND_BUDGET,
) -> dict[str, Any]:
    """Open (or reuse) one hypothesis-review meeting for a selection record.

    Participants derive from the team's linked chat room; the meeting id is
    deterministic per selection/round so replays reuse instead of duplicating.
    """
    from core.web.services import team_service
    from core.web.services.team_workflow import meeting_rounds, meeting_runtime

    normalized_team_id = team_service.assert_team_exists(team_id)
    selection_record = dict(selection)
    selection_id = str(selection_record.get("selectionId") or "").strip()
    if not selection_id:
        raise ContractValidationError("selection requires a selectionId")
    question_id = str(selection_record.get("questionId") or "").strip()
    if not question_id:
        raise ContractValidationError("selection requires a questionId")
    normalized_round_index = max(1, int(round_index or 1))
    normalized_meeting_round_id = (
        str(meeting_round_id or "").strip()
        or f"hf-review-{selection_id}-r{normalized_round_index}"
    )
    normalized_previous_id = str(previous_meeting_round_id or "").strip()
    normalized_request_id = str(collection_request_id or "").strip()

    try:
        existing_round = meeting_rounds.get_meeting_round(
            normalized_team_id, normalized_meeting_round_id
        )["meetingRound"]
    except meeting_rounds.ResearchMeetingRoundNotFoundError:
        existing_round = None
    if (
        isinstance(existing_round, Mapping)
        and str(existing_round.get("meetingType") or "").strip().lower()
        == HYPOTHESIS_REVIEW_MEETING_TYPE
        and _normalized_str_list(existing_round.get("chatRoomRoundIds"))
    ):
        link = _record_review_round_link(
            normalized_team_id,
            meeting_round_id=normalized_meeting_round_id,
            previous_meeting_round_id=normalized_previous_id,
            selection_id=selection_id,
            collection_request_id=normalized_request_id,
            question_id=question_id,
            round_index=normalized_round_index,
            round_budget=round_budget,
        )
        bound_round_ids = _normalized_str_list(existing_round.get("chatRoomRoundIds"))
        return {
            "schemaVersion": meeting_rounds.SCHEMA_VERSION,
            "teamId": normalized_team_id,
            "status": "reused",
            "meetingRound": existing_round,
            "roomId": str(existing_round.get("linkedChatRoomId") or ""),
            "roundId": bound_round_ids[-1],
            "chatRoomRoundIds": bound_round_ids,
            "link": link,
        }

    _team, room_id = meeting_runtime._ensure_linked_room(normalized_team_id)
    participant_resolution = _resolve_hypothesis_participants(
        normalized_team_id, room_id, HYPOTHESIS_REVIEW_MEETING_TYPE
    )

    extra_refs: list[str] = []
    if normalized_previous_id:
        extra_refs.append(f"meeting_round:{normalized_previous_id}")
    if normalized_request_id:
        extra_refs.append(f"collection_request:{normalized_request_id}")

    payload: dict[str, Any] = {
        key: selection_record.get(key)
        for key in (*_SCOPE_FIELDS, "agentId", "mode")
        if selection_record.get(key) is not None
    }
    payload.update(
        {
            "selectionId": selection_id,
            "questionId": question_id,
            "selectedCandidateIds": list(selection_record.get("selectedCandidateIds") or []),
            "decidedBy": str(selection_record.get("decidedBy") or ""),
            "meetingRoundId": normalized_meeting_round_id,
            **participant_resolution,
            "inputArtifactRefs": extra_refs,
        }
    )
    candidate_contexts = _build_round_candidates(
        normalized_team_id,
        {
            "question": question_id,
            "discussionItemRefs": [
                f"hypothesis_candidate:{candidate_id}"
                for candidate_id in payload["selectedCandidateIds"]
            ],
        },
    )
    opened = meeting_runtime.open_hypothesis_review_meeting(
        normalized_team_id,
        payload,
        agent_runner=agent_runner,
        background=background,
        candidate_contexts=candidate_contexts,
    )
    link = _record_review_round_link(
        normalized_team_id,
        meeting_round_id=normalized_meeting_round_id,
        previous_meeting_round_id=normalized_previous_id,
        selection_id=selection_id,
        collection_request_id=normalized_request_id,
        question_id=question_id,
        round_index=normalized_round_index,
        round_budget=round_budget,
    )
    return {
        **opened,
        "roundIndex": normalized_round_index,
        "link": link,
    }


def _selection_id_from_meeting(meeting_round: Mapping[str, Any]) -> str:
    for ref in _normalized_str_list(meeting_round.get("inputArtifactRefs")):
        if ref.startswith("hypothesis_selection:"):
            return ref.split(":", 1)[-1].strip()
    return ""


# ---------------------------------------------------------------------------
# round-0 candidate generation (cold start for catalog questions)
# ---------------------------------------------------------------------------


def _question_scope_envelope(team_id: str, question_id: str) -> dict[str, str]:
    """Derive the server-authoritative scope envelope for one catalog question.

    Mirrors the selection-context route: the frozen program registry supplies
    theme/campaign when the question is registered; otherwise a dev theme is
    resolved so DEV teams can still run the hypothesis-first chain.
    """
    from core.web.services.team_workflow.research_scope import (
        frozen_theme_registry,
        resolve_theme_contract,
    )

    normalized_question_id = str(question_id or "").strip().upper()
    theme_record = next(
        (
            record
            for record in frozen_theme_registry().values()
            if str(record.get("questionId") or "").upper() == normalized_question_id
        ),
        None,
    )
    if theme_record is not None:
        contract = resolve_theme_contract(
            team_id,
            theme_id=str(theme_record.get("themeId") or ""),
            campaign_id=str(theme_record.get("campaignId") or ""),
        )
    else:
        contract = resolve_theme_contract(
            team_id,
            theme_id=f"dev-{normalized_question_id.lower()}",
            campaign_id="dev-campaign",
        )
    if contract.is_dev_theme():
        mode = "dev"
    elif contract.is_activated():
        mode = "formal"
    else:
        mode = "platform"
    return {
        "program": contract.programId,
        "theme": contract.themeId,
        "campaign": contract.campaignId,
        "question": normalized_question_id,
        "branch": _DEFAULT_BRANCH,
        "workflow": _HYPOTHESIS_FIRST_WORKFLOW,
        "agentId": _OPERATOR_AGENT_ID,
        "mode": mode,
    }


def _question_generation_meetings(team_id: str, question_id: str) -> list[dict[str, Any]]:
    from core.web.services.team_workflow import meeting_rounds

    meetings = meeting_rounds.list_meeting_rounds(team_id)["meetings"]
    return [
        meeting
        for meeting in meetings
        if str(meeting.get("meetingType") or "") == CANDIDATE_GENERATION_MEETING_TYPE
        and str(meeting.get("question") or "").upper() == question_id.upper()
    ]


_TRAIL_CACHE: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
_TRAIL_CACHE_MAX_ENTRIES = 32


def _trail_source_stamp(team_id: str) -> float:
    """Newest mtime across the stores the trail reads."""
    root = developer_sandbox.seeded_sandbox_workspace_path(
        _project_root(), "teams", _safe_team_id(team_id)
    ) / "research_workflow"
    stamp = 0.0
    for name in ("meeting_rounds.jsonl", "hypothesis_first_chain.jsonl"):
        try:
            stamp = max(stamp, (root / name).stat().st_mtime)
        except OSError:
            continue
    # Trail content also comes from bound chat-room rounds; a growing room
    # without a meeting-record write must still invalidate the trail cache.
    try:
        from core.ui.chat_state import chat_state_path

        chat_root = chat_state_path(_project_root()).parent
        for child in chat_root.glob("*.json"):
            stamp = max(stamp, child.stat().st_mtime)
    except Exception:  # noqa: BLE001 - cache stamp must never fail the trail
        pass
    return stamp


def candidate_evidence_trail(
    team_id: str,
    question_id: str,
    *,
    excerpt_chars: int = 240,
) -> dict[str, Any]:
    """Per-candidate trail of discussion messages that cite it.

    Cold-start candidates carry no structured ``supporting_evidence_refs``;
    their real evidence lives in the generation and review speeches that
    mention the candidate id alongside literature anchors (PaperQA2-style
    click-through, built on data that exists). Each trail entry is a cited
    excerpt: meeting label, speaker, message id, and a window around the
    candidate mention.
    """
    from core.web.services import team_service
    from core.web.services.team_workflow import meeting_rounds

    normalized_team_id = team_service.assert_team_exists(team_id)
    normalized_question_id = str(question_id or "").strip().upper()
    if not normalized_question_id:
        raise ContractValidationError("questionId is required")

    cache_key = (normalized_team_id, normalized_question_id)
    source_stamp = _trail_source_stamp(normalized_team_id)
    cached = _TRAIL_CACHE.get(cache_key)
    if cached is not None and cached[0] == source_stamp:
        return cached[1]

    candidates = [
        record
        for record in _records(normalized_team_id)
        if str(record.get("recordKind") or "") == CANDIDATE_KIND
        and str(record.get("questionId") or "").upper() == normalized_question_id
    ]
    candidate_ids = [
        str(record.get("candidateId") or "").strip()
        for record in candidates
        if str(record.get("candidateId") or "").strip()
    ]

    trail: dict[str, list[dict[str, Any]]] = {cid: [] for cid in candidate_ids}
    meetings = meeting_rounds.list_meeting_rounds(normalized_team_id)["meetings"]
    question_meetings = [
        meeting
        for meeting in meetings
        if str(meeting.get("question") or "").upper() == normalized_question_id
        and str(meeting.get("meetingType") or "")
        in {CANDIDATE_GENERATION_MEETING_TYPE, HYPOTHESIS_REVIEW_MEETING_TYPE}
    ]
    for meeting in question_meetings:
        meeting_round_id = str(meeting.get("meetingRoundId") or "")
        label = (
            "候选生成"
            if str(meeting.get("meetingType") or "") == CANDIDATE_GENERATION_MEETING_TYPE
            else f"评审 {meeting_round_id.rsplit('-', 1)[-1]}"
        )
        for message in meeting_rounds.completed_meeting_source_messages(meeting):
            content = str(message.get("content") or "")
            message_id = str(message.get("messageId") or "")
            speaker = (
                str(message.get("speakerTitle") or "").strip()
                or str(message.get("participantId") or "").strip()
                or "participant"
            )
            for cid in candidate_ids:
                index = content.find(cid)
                if index < 0:
                    continue
                start = max(0, index - excerpt_chars // 3)
                excerpt = content[start : start + excerpt_chars].strip()
                trail[cid].append(
                    {
                        "meetingRoundId": meeting_round_id,
                        "meetingLabel": label,
                        "messageId": message_id,
                        "speaker": speaker,
                        "excerpt": excerpt,
                        "createdAt": str(message.get("createdAt") or ""),
                    }
                )

    for entries in trail.values():
        entries.sort(key=lambda item: str(item.get("createdAt") or ""))

    result = {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "questionId": normalized_question_id,
        "trails": [
            {"candidateId": cid, "entries": trail[cid]}
            for cid in candidate_ids
        ],
        "storagePath": str(_storage_path(normalized_team_id)),
    }
    if len(_TRAIL_CACHE) >= _TRAIL_CACHE_MAX_ENTRIES:
        _TRAIL_CACHE.clear()
    _TRAIL_CACHE[cache_key] = (source_stamp, result)
    return result


def list_hypothesis_candidates(team_id: str, *, question_id: str = "") -> dict[str, Any]:
    """List ledger-registered hypothesis candidates (round-0 output)."""
    from core.web.services import team_service

    normalized_team_id = team_service.assert_team_exists(team_id)
    normalized_question_id = str(question_id or "").strip().upper()
    candidates = [
        record
        for record in _records(normalized_team_id)
        if str(record.get("recordKind") or "") == CANDIDATE_KIND
        and (
            not normalized_question_id
            or str(record.get("questionId") or "").upper() == normalized_question_id
        )
    ]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "candidateCount": len(candidates),
        "candidates": candidates,
        "storagePath": str(_storage_path(normalized_team_id)),
    }


def _candidate_id_for(question_id: str, meeting_round_id: str, statement: str) -> str:
    digest = _stable_hash(
        {
            "questionId": question_id,
            "meetingRoundId": meeting_round_id,
            "statement": statement,
        }
    )
    return f"{question_id.lower()}-c{digest[:8]}"


def _append_generation_candidates(
    team_id: str,
    meeting_round: Mapping[str, Any],
    proposals: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Register digest proposals as selectable candidates (idempotent)."""
    meeting_round_id = str(meeting_round.get("meetingRoundId") or "")
    question_id = str(meeting_round.get("question") or "").strip().upper()
    appended: list[dict[str, Any]] = []
    with _LOCK:
        records = _read_jsonl(_storage_path(team_id))
        existing_by_id = {
            str(record.get("candidateId") or ""): record
            for record in records
            if str(record.get("recordKind") or "") == CANDIDATE_KIND
        }
        for proposal in proposals:
            statement = str(proposal.get("statement") or "").strip()
            if not statement:
                continue
            candidate_id = _candidate_id_for(question_id, meeting_round_id, statement)
            existing = existing_by_id.get(candidate_id)
            if existing is not None:
                appended.append(existing)
                continue
            record = {
                "schemaVersion": SCHEMA_VERSION,
                "recordKind": CANDIDATE_KIND,
                "candidateId": candidate_id,
                "questionId": question_id,
                "statement": statement,
                "rationale": str(proposal.get("rationale") or "").strip(),
                "proposedBy": str(proposal.get("proposedBy") or "").strip(),
                "meetingRoundId": meeting_round_id,
                "createdAt": _utc_now(),
            }
            _append_jsonl(_storage_path(team_id), record)
            existing_by_id[candidate_id] = record
            appended.append(record)
    return appended


def open_candidate_generation_meeting(
    team_id: str,
    question_id: str,
    *,
    agent_runner: Any = None,
    background: bool = True,
) -> dict[str, Any]:
    """Open (or reuse) the round-0 candidate-generation discussion.

    Deterministic per scope/question/attempt: replays reuse the open meeting
    instead of duplicating the discussion, and a closed attempt that already
    registered candidates is reused as-is.  Only a closed attempt that
    produced nothing rolls to a fresh per-attempt id so regeneration stays
    possible.  A terminal attempt with no successful discussion evidence is
    superseded before the next attempt opens.  Participants come from the
    team's linked chat room, same as review meetings.
    """
    from core.web.services import team_service
    from core.web.services.team_workflow import meeting_rounds, meeting_runtime

    normalized_team_id = team_service.assert_team_exists(team_id)
    scope = _question_scope_envelope(normalized_team_id, question_id)
    normalized_question_id = scope["question"]
    scope_hash = scope_hash_for(
        **{field: scope[field] for field in _SCOPE_FIELDS},
        agent_id=scope["agentId"],
        mode=scope["mode"],
    )
    meetings = _question_generation_meetings(normalized_team_id, normalized_question_id)
    open_meeting = next(
        (
            meeting
            for meeting in meetings
            if str(meeting.get("status") or "")
            in {"open", "summarizing", "awaiting_approval"}
        ),
        None,
    )
    if (
        open_meeting is not None
        and str(open_meeting.get("status") or "").strip().lower()
        in {"open", "summarizing"}
        and _normalized_str_list(open_meeting.get("chatRoomRoundIds"))
        and not meeting_rounds.running_bound_round_ids(open_meeting)
        and not meeting_rounds.completed_meeting_source_messages(open_meeting)
    ):
        meeting_rounds.supersede_empty_discussion_meeting(
            normalized_team_id,
            str(open_meeting.get("meetingRoundId") or ""),
        )
        meetings = _question_generation_meetings(
            normalized_team_id, normalized_question_id
        )
        open_meeting = None
    if open_meeting is not None and _normalized_str_list(
        open_meeting.get("chatRoomRoundIds")
    ):
        bound_round_ids = _normalized_str_list(open_meeting.get("chatRoomRoundIds"))
        return {
            "schemaVersion": SCHEMA_VERSION,
            "teamId": normalized_team_id,
            "status": "reused",
            "meetingRound": open_meeting,
            "roomId": str(open_meeting.get("linkedChatRoomId") or ""),
            "roundId": bound_round_ids[-1],
            "chatRoomRoundIds": bound_round_ids,
            "questionId": normalized_question_id,
        }
    if open_meeting is None and meetings:
        # All attempts are closed.  When candidates were registered the latest
        # closed meeting is the answer and replays reuse it; a closed attempt
        # that produced nothing must not block a fresh attempt, so the new
        # meeting gets a deterministic per-attempt id instead of reopening the
        # closed record.
        # Crash between the closure write and the candidate registration left
        # a closed meeting whose proposals never landed; re-register them
        # (idempotent) instead of forcing a whole new generation discussion.
        _heal_generation_candidates(normalized_team_id, meetings[-1])
        candidate_count = len(
            list_hypothesis_candidates(
                normalized_team_id, question_id=normalized_question_id
            )["candidates"]
        )
        # A single candidate can never satisfy the >=2 selection floor; reuse
        # only when the registered set is actually selectable, otherwise let a
        # fresh generation attempt run instead of dead-locking the question.
        has_candidates = candidate_count >= 2
        if has_candidates:
            existing = meetings[-1]
            return {
                "schemaVersion": SCHEMA_VERSION,
                "teamId": normalized_team_id,
                "status": "reused",
                "meetingRound": existing,
                "roomId": str(existing.get("linkedChatRoomId") or ""),
                "chatRoomRoundIds": _normalized_str_list(existing.get("chatRoomRoundIds")),
            }
    base_id = f"hf-candgen-{scope_hash[:16]}"
    if open_meeting is not None:
        meeting_round_id = str(open_meeting.get("meetingRoundId") or "")
    else:
        attempt = len(meetings) + 1
        meeting_round_id = base_id if attempt == 1 else f"{base_id}-a{attempt}"
    _team, room_id = meeting_runtime._ensure_linked_room(normalized_team_id)
    participant_resolution = _resolve_hypothesis_participants(
        normalized_team_id, room_id, CANDIDATE_GENERATION_MEETING_TYPE
    )
    payload = {
        **scope,
        "questionId": normalized_question_id,
        "meetingRoundId": meeting_round_id,
        **participant_resolution,
    }
    opened = meeting_runtime.open_candidate_generation_meeting(
        normalized_team_id,
        payload,
        agent_runner=agent_runner,
        background=background,
    )
    return {
        **opened,
        "questionId": normalized_question_id,
    }


def needs_candidate_generation(team_id: str, question_id: str) -> bool:
    """True when the question has no selectable candidates and no generation meeting."""
    from core.web.services.team_workflow import hypothesis_selection

    # _approved_candidate_ids already unions the approved artifact and the
    # chain-ledger candidates, so a non-empty set means selection can start.
    if hypothesis_selection._approved_candidate_ids(team_id, question_id):
        return False
    return not _question_generation_meetings(team_id, question_id)


def _generation_proposals_from_digest(digest: Any) -> list[dict[str, Any]]:
    if not isinstance(digest, Mapping):
        return []
    return [
        dict(item)
        for item in list(digest.get("proposedCandidates") or [])
        if isinstance(item, Mapping)
    ]


def _generation_proposals_from_messages(
    meeting_round: Mapping[str, Any],
) -> list[dict[str, Any]]:
    from core.web.services.team_workflow import meeting_rounds

    markers = meeting_rounds.extract_discussion_markers(
        meeting_rounds.meeting_source_messages(meeting_round)
    )
    return [
        dict(item)
        for item in list(markers.get("proposedCandidates") or [])
        if isinstance(item, Mapping)
    ]


def _heal_generation_candidates(team_id: str, closed_meeting: Mapping[str, Any]) -> None:
    if str(closed_meeting.get("status") or "") != "closed":
        return
    digest = closed_meeting.get("digest")
    if not isinstance(digest, Mapping):
        digest = closed_meeting.get("digestDraft")
    proposals = _generation_proposals_from_digest(digest)
    if not proposals:
        proposals = _generation_proposals_from_messages(closed_meeting)
    if proposals:
        _append_generation_candidates(team_id, closed_meeting, proposals)


def _close_generation_meeting(
    team_id: str,
    meeting_round: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Approve a candidate-generation closure and register its proposals."""
    from core.web.services.team_workflow import meeting_rounds

    normalized_team_id = team_id
    normalized_round_id = str(meeting_round.get("meetingRoundId") or "")
    request = dict(payload)
    digest_draft = (
        dict(meeting_round.get("digestDraft"))
        if isinstance(meeting_round.get("digestDraft"), Mapping)
        else {}
    )
    proposals = _generation_proposals_from_digest(digest_draft)
    if not proposals:
        proposals = _generation_proposals_from_messages(meeting_round)
        if proposals:
            # A stale or raced summary draft may have dropped this field.  Feed
            # the recovered proposals into the approved digest as well as the
            # chain ledger so the closure remains self-describing and replayable.
            request["proposedCandidates"] = proposals
    if not [item for item in list(request.get("decisions") or []) if isinstance(item, Mapping)]:
        # The §15.4 closure gate requires at least one decision; for a
        # generation round the decision IS the proposed candidate list, so
        # synthesize it from the digest when the approver did not pass one.
        candidate_refs = [
            str(item.get("candidateId") or "").strip()
            for item in proposals
            if str(item.get("candidateId") or "").strip()
        ]
        source_refs = _normalized_str_list(digest_draft.get("sourceMessageRefs"))
        request["decisions"] = [
            {
                "decision": "propose_candidates",
                "rationale": f"第 0 轮候选生成讨论产出 {len(proposals)} 条候选假说",
                "decidedBy": str(request.get("closedBy") or "").strip() or _OPERATOR_AGENT_ID,
                "candidateRefs": candidate_refs,
                "evidenceRefs": source_refs[:1] or [f"meeting_round:{normalized_round_id}"],
                "status": "adopted",
            }
        ]
    result = meeting_rounds.approve_meeting_closure(
        normalized_team_id, normalized_round_id, request
    )
    closed_record = result["meetingRound"]
    candidates = _append_generation_candidates(
        normalized_team_id, closed_record, proposals
    )
    return {
        **result,
        "candidates": candidates,
        "candidateCount": len(candidates),
    }


def _normalize_budget(budget: Any) -> int:
    if budget is None:
        return DEFAULT_ROUND_BUDGET
    try:
        normalized = int(budget)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"round budget must be an integer: {budget!r}") from exc
    if normalized < 1 or normalized > MAX_ROUND_BUDGET:
        raise ValueError(
            f"round budget must stay within 1..{MAX_ROUND_BUDGET}: {normalized}"
        )
    return normalized


def reopen_failed_review_meeting(
    team_id: str,
    meeting_round_id: str,
    *,
    agent_runner: Any = None,
    background: bool = True,
    budget: Any = None,
) -> dict[str, Any]:
    """Restart one review round whose discussion produced no successful speech.

    The recovery a blocked summarize surfaces as ``重新发起讨论`` for review
    rounds: the failed attempt is superseded (append-only, no digest) and the
    next budget-gated round opens with the same selection lineage.  Guards
    live in ``meeting_rounds.supersede_empty_discussion_meeting`` — only a
    terminal round with zero completed messages may be recovered this way.
    """
    from core.web.services import team_service
    from core.web.services.team_workflow import meeting_rounds

    normalized_team_id = team_service.assert_team_exists(team_id)
    normalized_round_id = str(meeting_round_id or "").strip()
    if not normalized_round_id:
        raise HypothesisFirstChainError("meeting_round_id is required.")
    meeting_round = meeting_rounds.get_meeting_round(
        normalized_team_id, normalized_round_id
    )["meetingRound"]
    if str(meeting_round.get("meetingType") or "") != HYPOTHESIS_REVIEW_MEETING_TYPE:
        raise HypothesisFirstChainError(
            "reopen-failed-discussion only applies to hypothesis_review meetings."
        )
    superseded = meeting_rounds.supersede_empty_discussion_meeting(
        normalized_team_id,
        normalized_round_id,
        actor="operator:failed-discussion-restart",
    )
    reopened = open_next_review_meeting(
        normalized_team_id,
        previous_meeting_round_id=normalized_round_id,
        agent_runner=agent_runner,
        background=background,
        budget=budget,
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "status": "reopened",
        "openStatus": str(reopened.get("status") or ""),
        "supersededMeetingRound": superseded.get("meetingRound") or {},
        **{
            key: value
            for key, value in reopened.items()
            if key not in {"schemaVersion", "teamId", "status"}
        },
    }


def open_next_review_meeting(
    team_id: str,
    *,
    previous_meeting_round_id: str,
    collection_request_id: str = "",
    agent_runner: Any = None,
    background: bool = True,
    budget: Any = None,
) -> dict[str, Any]:
    """Open the next review round after knowledge back-fill, budget-gated.

    The default budget is three discussion rounds; a human may raise it to at
    most five.  Once the budget is reached no further meeting opens and the
    result reports ``budget_exhausted`` so a manual decision happens instead.
    """
    from core.web.services import team_service
    from core.web.services.team_workflow import hypothesis_selection as selections
    from core.web.services.team_workflow import meeting_rounds

    normalized_team_id = team_service.assert_team_exists(team_id)
    previous_id = str(previous_meeting_round_id or "").strip()
    if not previous_id:
        raise HypothesisFirstChainError("previous_meeting_round_id is required.")
    normalized_request_id = str(collection_request_id or "").strip()
    previous = meeting_rounds.get_meeting_round(normalized_team_id, previous_id)[
        "meetingRound"
    ]
    selection_id = _selection_id_from_meeting(previous)
    if not selection_id:
        raise HypothesisFirstChainError(
            f"meeting round {previous_id} carries no hypothesis_selection ref"
        )
    selection = selections.get_hypothesis_selection(normalized_team_id, selection_id)[
        "selection"
    ]

    if normalized_request_id:
        existing_link = next(
            (
                link
                for link in _review_round_links(_records(normalized_team_id))
                if str(link.get("collectionRequestId") or "") == normalized_request_id
            ),
            None,
        )
        if existing_link is not None:
            meeting = meeting_rounds.get_meeting_round(
                normalized_team_id, str(existing_link.get("meetingRoundId") or "")
            )["meetingRound"]
            return {
                "schemaVersion": SCHEMA_VERSION,
                "teamId": normalized_team_id,
                "status": "reused",
                "meetingRound": meeting,
                "roundIndex": int(existing_link.get("roundIndex") or 0),
                "link": existing_link,
            }

    links = [
        link
        for link in _review_round_links(_records(normalized_team_id))
        if str(link.get("selectionId") or "") == selection_id
    ]
    round_index = max((int(link.get("roundIndex") or 0) for link in links), default=0) + 1
    effective_budget = _normalize_budget(budget)
    if round_index > effective_budget:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "teamId": normalized_team_id,
            "status": "budget_exhausted",
            "roundIndex": round_index,
            "budget": effective_budget,
            "selectionId": selection_id,
            "previousMeetingRoundId": previous_id,
        }
    return open_review_meeting_for_selection(
        normalized_team_id,
        selection,
        agent_runner=agent_runner,
        background=background,
        round_index=round_index,
        previous_meeting_round_id=previous_id,
        collection_request_id=normalized_request_id,
        round_budget=effective_budget,
    )


# ---------------------------------------------------------------------------
# closure -> collection trigger


def _decision_id_for(meeting_round: Mapping[str, Any], raw: Mapping[str, Any]) -> str:
    """Recompute the persisted DecisionRecord id for one raw closure decision."""
    from core.web.services.team_workflow import meeting_rounds

    candidate_refs = _normalized_str_list(raw.get("candidateRefs"))
    evidence_refs = _normalized_str_list(raw.get("evidenceRefs"))
    return f"decision-{meeting_rounds._stable_hash({'meetingRoundId': meeting_round['meetingRoundId'], 'scopeHash': meeting_round['scopeHash'], 'decision': str(raw.get('decision') or '').strip().lower(), 'candidateRefs': candidate_refs, 'evidenceRefs': evidence_refs})[:16]}"


def _scope_envelope_for_meeting(meeting_round: Mapping[str, Any]) -> dict[str, str]:
    """Rebuild the facade scope envelope from the meeting's validated scope."""
    from core.web.services.team_workflow import research_scope as scope_service

    identity = {
        field: str(meeting_round.get(field) or "").strip() for field in _SCOPE_FIELDS
    }
    agent_id = str(meeting_round.get("agentId") or "").strip()
    mode = str(meeting_round.get("mode") or "").strip().lower()
    scope_hash = str(meeting_round.get("scopeHash") or "").strip()
    expected = scope_hash_for(**identity, agent_id=agent_id, mode=mode)
    if not scope_hash or scope_hash != expected:
        raise HypothesisFirstChainError(
            "meeting round scopeHash does not match its scope identity"
        )
    return {
        **identity,
        "agentId": agent_id,
        "mode": mode,
        "scopeHash": scope_hash,
        "artifactLocator": scope_service._artifact_locator(identity, scope_hash),
        "ledgerRoot": scope_service._ledger_root(identity, scope_hash),
        "cacheKey": scope_service._cache_key(identity, agent_id, scope_hash),
    }


def _request_hash(
    meeting_round: Mapping[str, Any],
    decision_id: str,
    envelope: Mapping[str, Any],
    requirements: Mapping[str, Any],
    writeback_policy: Mapping[str, Any],
) -> str:
    return _stable_hash(
        {
            "meetingRoundId": str(meeting_round.get("meetingRoundId") or ""),
            "decisionId": decision_id,
            "searchEnvelope": dict(envelope),
            "requirements": dict(requirements),
            "writebackPolicy": dict(writeback_policy),
        }
    )


def _append_collection_request(
    team_id: str,
    meeting_round: Mapping[str, Any],
    decision_id: str,
    envelope: Mapping[str, Any],
    requirements: Mapping[str, Any],
    writeback_policy: Mapping[str, Any],
    collection_run_id: str,
) -> dict[str, Any]:
    request_hash = _request_hash(
        meeting_round, decision_id, envelope, requirements, writeback_policy
    )
    request_id = f"hfcr-{request_hash[:16]}"
    record = {
        "schemaVersion": SCHEMA_VERSION,
        "recordKind": COLLECTION_REQUEST_KIND,
        "requestId": request_id,
        "requestHash": request_hash,
        "status": "pending",
        "meetingRoundId": str(meeting_round.get("meetingRoundId") or ""),
        "decisionId": decision_id,
        "questionId": str(meeting_round.get("question") or ""),
        **{field: str(meeting_round.get(field) or "") for field in _SCOPE_FIELDS},
        "agentId": str(meeting_round.get("agentId") or ""),
        "mode": str(meeting_round.get("mode") or ""),
        "scopeHash": str(meeting_round.get("scopeHash") or ""),
        "searchEnvelope": dict(envelope),
        "requirements": dict(requirements),
        "writebackPolicy": dict(writeback_policy),
        "collectionRunId": str(collection_run_id or ""),
        "collectionRunStatus": "",
        "createdAt": _utc_now(),
        "handedOffAt": "",
        "handoffRef": "",
        "handoffError": {},
    }
    with _LOCK:
        records = _read_jsonl(_storage_path(team_id))
        existing = _latest_by_id(
            [item for item in records if item.get("recordKind") == COLLECTION_REQUEST_KIND],
            "requestId",
            request_id,
        )
        if existing is not None:
            if str(existing.get("requestHash") or "") != request_hash:
                raise HypothesisFirstChainError(
                    f"collection request {request_id} is already bound to different content"
                )
            return existing
        _append_jsonl(_storage_path(team_id), record)
    return record


def _find_request_for_decision(
    team_id: str, meeting_round_id: str, decision_id: str
) -> dict[str, Any] | None:
    for record in _collection_requests(_records(team_id)):
        if (
            str(record.get("meetingRoundId") or "") == meeting_round_id
            and str(record.get("decisionId") or "") == decision_id
        ):
            return record
    return None


def _process_collection_decisions(
    team_id: str,
    meeting_round: Mapping[str, Any],
    close_result: Mapping[str, Any],
    request: Mapping[str, Any],
) -> dict[str, Any]:
    from core.web.services.team_workflow.source_collection import facade
    from core.web.services.team_workflow.source_collection import (
        runs as source_collection_runs,
    )

    persisted_ids = {
        str(item.get("decisionId") or "")
        for item in list(close_result.get("decisions") or [])
        if isinstance(item, Mapping)
    }
    requests_out: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    start_candidates: dict[str, list[dict[str, Any]]] = {}
    raw_decisions = [
        item for item in list(request.get("decisions") or []) if isinstance(item, Mapping)
    ]
    for raw in raw_decisions:
        if str(raw.get("decision") or "").strip().lower() != REQUEST_EVIDENCE_DECISION:
            continue
        decision_id = _decision_id_for(meeting_round, raw)
        if decision_id not in persisted_ids:
            skipped.append(
                {"decisionId": decision_id, "reason": "decision_not_persisted"}
            )
            continue
        existing = _find_request_for_decision(
            team_id, str(meeting_round.get("meetingRoundId") or ""), decision_id
        )
        if existing is not None:
            requests_out.append(existing)
            continue
        try:
            envelope = facade._normalize_search_envelope(
                raw.get("searchEnvelope"), require_keywords=True
            )
        except Exception as exc:  # noqa: BLE001 - closure stays visible and retryable
            reason = (
                "search_envelope_missing"
                if getattr(exc, "code", "") == "search_keywords_required"
                else "search_envelope_invalid"
            )
            skipped.append(
                {"decisionId": decision_id, "reason": reason, "error": str(exc)}
            )
            continue
        try:
            requirements = facade._normalize_requirements(raw.get("requirements"))
            writeback_policy = facade._normalize_writeback_policy(
                raw.get("writebackPolicy")
            )
        except Exception as exc:
            skipped.append(
                {
                    "decisionId": decision_id,
                    "reason": "collection_payload_invalid",
                    "error": str(exc),
                }
            )
            continue
        scope_envelope = _scope_envelope_for_meeting(meeting_round)
        ensured = facade.research_knowledge_collection_facade(
            action="ensure",
            scope=scope_envelope,
            searchEnvelope=envelope,
            requirements=requirements,
            writebackPolicy=writeback_policy,
            team_id=team_id,
        )
        locator = ensured.get("locator") if isinstance(ensured.get("locator"), Mapping) else {}
        record = _append_collection_request(
            team_id,
            meeting_round,
            decision_id,
            envelope,
            requirements,
            writeback_policy,
            str(locator.get("runId") or ""),
        )
        requests_out.append(record)
        collection_run_id = str(record.get("collectionRunId") or "").strip()
        if not collection_run_id:
            failed = _update_collection_request(
                team_id,
                str(record.get("requestId") or ""),
                status="failed",
                collectionRunStatus="failed",
                startError={
                    "code": "collection_run_missing",
                    "message": "资料搜集子运行未创建，无法启动搜索。",
                },
            )
            requests_out[-1] = failed
            continue
        start_candidates.setdefault(collection_run_id, []).append(record)

    for collection_run_id, records in start_candidates.items():
        try:
            source_collection_runs.start_source_collection_search_background(
                team_id,
                collection_run_id,
                {"backgroundExecution": True},
            )
        except Exception as exc:
            start_error = {
                "code": "search_start_failed",
                "message": str(exc) or type(exc).__name__,
            }
            failed_by_request_id = {
                str(record.get("requestId") or ""): _update_collection_request(
                    team_id,
                    str(record.get("requestId") or ""),
                    status="failed",
                    collectionRunStatus="failed",
                    startError=start_error,
                )
                for record in records
            }
            requests_out = [
                failed_by_request_id.get(str(record.get("requestId") or ""), record)
                for record in requests_out
            ]
    return {"requests": requests_out, "skipped": skipped}


# ---------------------------------------------------------------------------
# closure -> HypothesisRound generation (HF-3 executor entry point)


def _build_round_candidates(
    team_id: str, meeting_round: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Assemble review inputs for the candidates discussed in one meeting.

    The authoritative source is the approved v2 question artifact (the same
    read path HF-1 selection validation uses): ``statement`` maps to the
    required ``claim``, ``mechanism`` to ``rationale``, and ``novelty_basis``
    to ``differenceFromAlternatives`` when present (HF-3 otherwise applies its
    default fallback wording).
    """
    from core.web.services.team_workflow.research_runtime import question_launch

    candidate_ids = [
        ref.split(":", 1)[1].strip()
        for ref in _normalized_str_list(meeting_round.get("discussionItemRefs"))
        if ref.startswith("hypothesis_candidate:") and ref.split(":", 1)[1].strip()
    ]
    question_id = str(meeting_round.get("question") or "").strip()
    detail = question_launch._approved_details(team_id).get(question_id.upper())
    if detail is None:
        ledger_candidates = list_hypothesis_candidates(team_id, question_id=question_id)[
            "candidates"
        ]
        artifact_by_id = {
            str(item.get("candidateId") or "").strip(): {
                "hypothesis_id": str(item.get("candidateId") or "").strip(),
                "statement": str(item.get("statement") or item.get("claim") or "").strip(),
                "mechanism": str(item.get("rationale") or "").strip(),
                "novelty_basis": str(item.get("differenceFromAlternatives") or "").strip(),
            }
            for item in ledger_candidates
            if isinstance(item, Mapping)
        }
    else:
        output = detail.get("output") if isinstance(detail.get("output"), Mapping) else {}
        hypotheses = [
            item
            for item in list(output.get("hypotheses") or [])
            if isinstance(item, Mapping)
        ]
        artifact_by_id = {
            str(item.get("hypothesis_id") or "").strip(): item for item in hypotheses
        }
    candidates: list[dict[str, Any]] = []
    for candidate_id in candidate_ids:
        artifact = artifact_by_id.get(candidate_id) or {}
        candidate: dict[str, Any] = {
            "candidateId": candidate_id,
            "claim": str(artifact.get("statement") or "").strip(),
            "rationale": str(artifact.get("mechanism") or "").strip(),
        }
        difference = str(artifact.get("novelty_basis") or "").strip()
        if difference:
            candidate["differenceFromAlternatives"] = difference
        candidates.append(candidate)
    return candidates


def _generate_hypothesis_round(
    team_id: str,
    meeting_round: Mapping[str, Any],
    *,
    reflection_runner: Any = None,
    pairwise_runner: Any = None,
    pareto_runner: Any = None,
    metareview_runner: Any = None,
) -> dict[str, Any]:
    """Best-effort HypothesisRound generation after one review closure.

    Mirrors the auto-open failure semantics: the closed meeting is an
    append-only fact, so a generation failure is reported structurally and
    never rolls the closure back; the readiness layer keeps blocking on
    ``hypothesis_round_unconverged`` until a round converges (fail-closed).
    Replays reuse the already-generated round through HF-3 idempotency.
    """
    try:
        from core.web.services.team_workflow import hypothesis_rounds
        from core.web.services.team_workflow import (
            hypothesis_selection as selections,
        )

        meeting_round_id = str(meeting_round.get("meetingRoundId") or "").strip()
        selection_id = _selection_id_from_meeting(meeting_round)
        if not selection_id:
            raise HypothesisFirstChainError(
                "meeting carries no hypothesis_selection ref"
            )
        selection = selections.get_hypothesis_selection(team_id, selection_id)[
            "selection"
        ]
        if str(selection.get("scopeHash") or "") != str(
            meeting_round.get("scopeHash") or ""
        ) or str(selection.get("questionId") or "").upper() != str(
            meeting_round.get("question") or ""
        ).upper():
            raise HypothesisFirstChainError(
                "selection scope/question does not match the meeting scope"
            )
        candidates = _build_round_candidates(team_id, meeting_round)
        result = hypothesis_rounds.generate_hypothesis_round_from_meeting(
            team_id,
            meeting_round_id,
            {"candidates": candidates},
            reflection_runner=reflection_runner,
            pairwise_runner=pairwise_runner,
            pareto_runner=pareto_runner,
            metareview_runner=metareview_runner,
        )
        round_record = result.get("round") if isinstance(result.get("round"), Mapping) else {}
        return {
            "status": str(result.get("status") or ""),
            "roundId": str(round_record.get("roundId") or ""),
            "round": dict(round_record),
            "closed": True,
        }
    except Exception as exc:  # closure fact stays; report the side effect
        return {
            "status": "failed",
            "error": str(exc),
            "errorType": type(exc).__name__,
        }


def _update_collection_request(
    team_id: str, request_id: str, **fields: Any
) -> dict[str, Any]:
    with _LOCK:
        records = _read_jsonl(_storage_path(team_id))
        latest = _latest_by_id(
            [item for item in records if item.get("recordKind") == COLLECTION_REQUEST_KIND],
            "requestId",
            request_id,
        )
        if latest is None:
            raise HypothesisFirstChainNotFoundError(
                f"Collection request {request_id} not found."
            )
        updated = {**latest, **fields}
        _append_jsonl(_storage_path(team_id), updated)
        return updated


def _scope_envelope_for_collection_request(
    request: Mapping[str, Any],
) -> dict[str, str]:
    """Rebuild the validated facade scope from the immutable request fields."""
    identity = {
        field: str(request.get(field) or "").strip() for field in _SCOPE_FIELDS
    }
    agent_id = str(request.get("agentId") or "").strip()
    mode = str(request.get("mode") or "").strip().lower()
    if not all(identity.values()) or not agent_id or not mode:
        raise HypothesisFirstChainError(
            "collection request scope is incomplete and cannot be recovered"
        )
    expected_hash = scope_hash_for(
        **identity,
        agent_id=agent_id,
        mode=mode,
    )
    stored_hash = str(request.get("scopeHash") or "").strip()
    if stored_hash and stored_hash != expected_hash:
        raise HypothesisFirstChainError(
            "collection request scopeHash does not match its scope identity"
        )
    # Older requests did not persist derived locators. They are pure functions
    # of the request identity, so deriving them here preserves the original
    # scope without introducing a second source of truth.
    return {
        **identity,
        "agentId": agent_id,
        "mode": mode,
        "scopeHash": stored_hash or expected_hash,
        "artifactLocator": (
            f"research-artifact://{identity['program']}/{identity['theme']}/"
            f"{identity['campaign']}/{identity['branch']}/{identity['question']}/"
            f"{stored_hash or expected_hash}"
        ),
        "ledgerRoot": (
            f"research-ledger://{identity['program']}/{identity['theme']}/"
            f"{identity['campaign']}/{stored_hash or expected_hash}"
        ),
        "cacheKey": f"scope:{stored_hash or expected_hash}:{identity['branch']}:{agent_id}",
    }


def _recover_collection_request_locked(
    team_id: str,
    request_id: str,
) -> dict[str, Any]:
    """Idempotently bind and restart one orphaned hypothesis collection request.

    The request is the durable idempotency key. Existing candidates, selections,
    meetings and review records are never rewritten; only the request's child
    run binding and collection status are appended.
    """
    from core.web.services import team_service
    from core.web.services.team_workflow.source_collection import facade
    from core.web.services.team_workflow.source_collection import runs as source_collection_runs

    normalized_team_id = team_service.assert_team_exists(team_id)
    normalized_request_id = str(request_id or "").strip()
    if not normalized_request_id:
        raise HypothesisFirstChainError("Collection request id is required.")
    request = _latest_by_id(
        [
            item
            for item in _records(normalized_team_id)
            if item.get("recordKind") == COLLECTION_REQUEST_KIND
        ],
        "requestId",
        normalized_request_id,
    )
    if request is None:
        raise HypothesisFirstChainNotFoundError(
            f"Collection request {normalized_request_id} not found."
        )
    if str(request.get("status") or "").strip().lower() == "handed_off":
        return {
            "schemaVersion": SCHEMA_VERSION,
            "teamId": normalized_team_id,
            "status": "reused",
            "request": request,
            "reused": True,
        }
    existing_run_id = str(request.get("collectionRunId") or "").strip()
    if (
        str(request.get("status") or "").strip().lower() == "pending"
        and existing_run_id
        and str(request.get("collectionRunStatus") or "").strip().lower()
        in {"starting", "running"}
    ):
        return {
            "schemaVersion": SCHEMA_VERSION,
            "teamId": normalized_team_id,
            "status": "reused",
            "request": request,
            "reused": True,
        }

    scope = _scope_envelope_for_collection_request(request)
    search_envelope = request.get("searchEnvelope") if isinstance(request.get("searchEnvelope"), Mapping) else {}
    requirements = request.get("requirements") if isinstance(request.get("requirements"), Mapping) else {}
    writeback_policy = request.get("writebackPolicy") if isinstance(request.get("writebackPolicy"), Mapping) else {}
    ensured = facade.research_knowledge_collection_facade(
        action="ensure",
        scope=scope,
        searchEnvelope=search_envelope,
        requirements=requirements,
        writebackPolicy=writeback_policy,
        team_id=normalized_team_id,
    )
    locator = ensured.get("locator") if isinstance(ensured.get("locator"), Mapping) else {}
    run_id = str(locator.get("runId") or "").strip()
    if not run_id:
        updated = _update_collection_request(
            normalized_team_id,
            normalized_request_id,
            status="failed",
            collectionRunStatus="failed",
            startError={
                "code": "collection_run_missing",
                "message": "资料搜集子运行未创建，无法启动搜索。",
            },
        )
        return {
            "schemaVersion": SCHEMA_VERSION,
            "teamId": normalized_team_id,
            "status": "collection_recovery",
            "request": updated,
            "reused": False,
        }

    previous_run_id = str(request.get("collectionRunId") or "").strip()
    _update_collection_request(
        normalized_team_id,
        normalized_request_id,
        status="pending",
        collectionRunId=run_id,
        collectionRunStatus="starting",
        startError={},
    )
    try:
        source_collection_runs.start_source_collection_search_background(
            normalized_team_id,
            run_id,
            {"backgroundExecution": True},
        )
    except Exception as exc:  # noqa: BLE001 - request remains visibly retryable
        failed = _update_collection_request(
            normalized_team_id,
            normalized_request_id,
            status="failed",
            collectionRunStatus="failed",
            startError={
                "code": "search_start_failed",
                "message": str(exc) or type(exc).__name__,
            },
        )
        return {
            "schemaVersion": SCHEMA_VERSION,
            "teamId": normalized_team_id,
            "status": "collection_recovery",
            "request": failed,
            "reused": bool(previous_run_id == run_id),
            "error": str(exc),
        }
    updated = _update_collection_request(
        normalized_team_id,
        normalized_request_id,
        status="pending",
        collectionRunStatus="running",
        startError={},
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "status": "reused" if previous_run_id == run_id else "recovered",
        "request": updated,
        "reused": bool(previous_run_id == run_id),
    }


def _collection_recovery_lock(team_id: str, request_id: str) -> threading.Lock:
    key = f"{team_id}\x00{request_id}"
    with _LOCK:
        return _RECOVERY_LOCKS.setdefault(key, threading.Lock())


def recover_collection_request(
    team_id: str,
    request_id: str,
) -> dict[str, Any]:
    """Serialize recovery for one durable request without holding the ledger lock."""
    from core.web.services import team_service

    normalized_team_id = team_service.assert_team_exists(team_id)
    normalized_request_id = str(request_id or "").strip()
    if not normalized_request_id:
        raise HypothesisFirstChainError("Collection request id is required.")
    with _collection_recovery_lock(normalized_team_id, normalized_request_id):
        return _recover_collection_request_locked(
            normalized_team_id,
            normalized_request_id,
        )


def _requests_for_collection_run(
    team_id: str, collection_run_id: str
) -> list[dict[str, Any]]:
    run_id = str(collection_run_id or "").strip()
    if not run_id:
        return []
    return [
        record
        for record in _collection_requests(_records(team_id))
        if str(record.get("collectionRunId") or "") == run_id
    ]


def _merge_evidence_requests(
    requests: list[Mapping[str, Any]],
    *,
    closed_by: str,
    meeting_round_id: str,
) -> dict[str, Any]:
    keywords: list[str] = []
    source_types: list[str] = []
    evidence_levels: list[str] = []
    candidate_refs: list[str] = []
    evidence_refs: list[str] = []
    rationales: list[str] = []
    requirements: dict[str, Any] = {}
    writeback_policy: dict[str, Any] = {}

    def _extend_unique(target: list[str], values: Any) -> None:
        for item in _normalized_str_list(values):
            if item not in target:
                target.append(item)

    for raw in requests:
        envelope = raw.get("searchEnvelope") if isinstance(raw.get("searchEnvelope"), Mapping) else {}
        _extend_unique(keywords, envelope.get("keywords"))
        _extend_unique(source_types, envelope.get("sourceTypes"))
        _extend_unique(evidence_levels, envelope.get("evidenceLevels"))
        _extend_unique(candidate_refs, raw.get("candidateRefs"))
        _extend_unique(evidence_refs, raw.get("evidenceRefs"))
        rationale = str(raw.get("rationale") or "").strip()
        if rationale:
            rationales.append(rationale)
        if isinstance(raw.get("requirements"), Mapping):
            requirements.update(dict(raw.get("requirements") or {}))
        if isinstance(raw.get("writebackPolicy"), Mapping):
            writeback_policy.update(dict(raw.get("writebackPolicy") or {}))
    return {
        "decision": REQUEST_EVIDENCE_DECISION,
        "rationale": "；".join(rationales) or "确认本轮搜集范围",
        "decidedBy": closed_by,
        "candidateRefs": candidate_refs,
        "evidenceRefs": evidence_refs or [f"meeting_round:{meeting_round_id}"],
        "status": "adopted",
        "searchEnvelope": {
            "keywords": keywords,
            "sourceTypes": source_types,
            "evidenceLevels": evidence_levels,
        },
        "requirements": requirements,
        "writebackPolicy": writeback_policy,
    }


def approve_meeting_digest(
    team_id: str,
    meeting_round_id: str,
    *,
    closed_by: str,
    expected_digest_content_hash: str,
    runtime: Any = None,
) -> dict[str, Any]:
    """Confirm the current digest draft and apply generation/review side effects."""

    from core.web.services import team_service
    from core.web.services.team_workflow import meeting_rounds, meeting_runtime

    normalized_team_id = team_service.assert_team_exists(team_id)
    normalized_round_id = str(meeting_round_id or "").strip()
    if not normalized_round_id:
        raise HypothesisFirstChainError("Meeting round id is required.")
    closed_by_id = str(closed_by or "").strip()
    if not closed_by_id:
        raise HypothesisFirstChainError("closedBy is required.")
    expected_hash = str(expected_digest_content_hash or "").strip()
    if not expected_hash:
        raise HypothesisFirstChainError("expectedDigestContentHash is required.")
    meeting_round = meeting_rounds.get_meeting_round(normalized_team_id, normalized_round_id)[
        "meetingRound"
    ]
    draft = (
        dict(meeting_round.get("digestDraft"))
        if isinstance(meeting_round.get("digestDraft"), Mapping)
        else {}
    )
    actual_hash = str(draft.get("contentHash") or "").strip()
    if not draft or str(meeting_round.get("status") or "") != "awaiting_approval":
        raise HypothesisFirstChainError(
            "approve-digest requires a meeting in awaiting_approval with a digest draft"
        )
    if actual_hash != expected_hash:
        raise StaleDigestError(
            "digest content hash is stale; reload the draft and confirm again",
            expected=expected_hash,
            actual=actual_hash,
        )
    meeting_type = str(meeting_round.get("meetingType") or "")
    if meeting_type == CANDIDATE_GENERATION_MEETING_TYPE:
        return _close_generation_meeting(
            normalized_team_id,
            meeting_round,
            {"closedBy": closed_by_id, "decisions": []},
        )
    if meeting_type != HYPOTHESIS_REVIEW_MEETING_TYPE:
        raise HypothesisFirstChainError(
            "approve-digest only handles hypothesis review or candidate generation meetings"
        )
    source_refs = _normalized_str_list(draft.get("sourceMessageRefs"))
    raw_requests = [
        item for item in list(draft.get("evidenceRequests") or []) if isinstance(item, Mapping)
    ]
    validation_errors = [
        dict(item)
        for item in list(draft.get("validationErrors") or [])
        if isinstance(item, Mapping)
    ]
    valid_requests: list[dict[str, Any]] = []
    for raw in raw_requests:
        normalized, errors = meeting_runtime.validate_evidence_request_draft(
            raw, meeting_round, source_refs=source_refs
        )
        validation_errors.extend(errors)
        if normalized is not None:
            valid_requests.append(normalized)
    attempted = bool(raw_requests) or bool(draft.get("validationErrors"))
    if attempted and not valid_requests:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "teamId": normalized_team_id,
            "status": "awaiting_approval",
            "closed": False,
            "meetingRound": meeting_round,
            "digestDraft": draft,
            "validationErrors": validation_errors,
        }
    if valid_requests:
        decisions = [
            _merge_evidence_requests(
                valid_requests,
                closed_by=closed_by_id,
                meeting_round_id=normalized_round_id,
            )
        ]
    else:
        decisions = [
            {
                "decision": "close_round",
                "rationale": "本轮评审确认现有结论，不再启动新的资料搜集",
                "decidedBy": closed_by_id,
                "candidateRefs": [
                    ref.split(":", 1)[-1]
                    for ref in _normalized_str_list(meeting_round.get("discussionItemRefs"))
                    if ref.startswith("hypothesis_candidate:")
                ],
                "evidenceRefs": source_refs[:1] or [f"meeting_round:{normalized_round_id}"],
                "status": "adopted",
            }
        ]
    return close_review_meeting(
        normalized_team_id,
        normalized_round_id,
        {"closedBy": closed_by_id, "decisions": decisions},
        runtime=runtime,
    )


def notify_collection_run_terminal(
    team_id: str,
    collection_run_id: str,
    terminal_status: str,
) -> dict[str, Any]:
    """Bridge a source-collection terminal status into the hypothesis-first chain.

    Must be called outside workflow/ledger writer locks. Only ``completed``
    handoffs; ``failed`` / ``needs_continue`` stay in collection recovery.
    """
    from core.web.services import team_service

    normalized_team_id = team_service.assert_team_exists(team_id)
    run_id = str(collection_run_id or "").strip()
    status = str(terminal_status or "").strip().lower()
    if not run_id:
        return {"status": "ignored", "reason": "missing_collection_run_id"}
    requests = _requests_for_collection_run(normalized_team_id, run_id)
    if not requests:
        return {"status": "ignored", "reason": "no_bound_request"}
    if status in {"failed", "needs_continue"}:
        updated = [
            _update_collection_request(
                normalized_team_id,
                str(record.get("requestId") or ""),
                collectionRunStatus=status,
            )
            for record in requests
        ]
        return {
            "status": "collection_recovery",
            "requests": updated,
            "request": updated[-1] if updated else {},
        }
    if status != "completed":
        return {"status": "ignored", "reason": "non_completed"}
    last: dict[str, Any] = {"status": "ignored"}
    for record in requests:
        request_id = str(record.get("requestId") or "")
        if not request_id:
            continue
        if str(record.get("status") or "") == "handed_off":
            last = record_collection_handoff(
                normalized_team_id,
                request_id,
                handoff_ref=str(record.get("handoffRef") or f"source_collection_run:{run_id}"),
            )
            last["status"] = "reused"
            continue
        try:
            last = record_collection_handoff(
                normalized_team_id,
                request_id,
                handoff_ref=f"source_collection_run:{run_id}",
            )
            _update_collection_request(
                normalized_team_id,
                request_id,
                collectionRunStatus="completed",
                handoffError={},
            )
            last["request"] = {
                **dict(last.get("request") or {}),
                "collectionRunStatus": "completed",
                "handoffError": {},
            }
        except Exception as exc:
            updated = _update_collection_request(
                normalized_team_id,
                request_id,
                status="handoff_pending",
                collectionRunStatus="completed",
                handoffError={
                    "code": "handoff_failed",
                    "message": str(exc),
                },
            )
            last = {
                "schemaVersion": SCHEMA_VERSION,
                "teamId": normalized_team_id,
                "status": "handoff_pending",
                "request": updated,
                "error": str(exc),
            }
    return last


def close_review_meeting(
    team_id: str,
    meeting_round_id: str,
    payload: Mapping[str, Any] | None = None,
    *,
    runtime: Any = None,
    reflection_runner: Any = None,
    pairwise_runner: Any = None,
    pareto_runner: Any = None,
    metareview_runner: Any = None,
) -> dict[str, Any]:
    """Approve one hypothesis-review closure, then apply chain effects.

    ``request_new_evidence`` decisions with a valid ``searchEnvelope`` start or
    reuse a stage-1 collection run through the facade; decisions without one
    are reported as skipped and never trigger collection.  A HypothesisRound
    is then generated from the closed meeting through the HF-3 executor
    (idempotent per meeting; failures are reported under ``hypothesisRound``
    without rolling the closure back).  When a runtime is provided the parent
    runs' ``hypothesis_design`` readiness is re-checked outside any writer
    transaction.
    """
    from core.web.services import team_service
    from core.web.services.team_workflow import meeting_rounds

    normalized_team_id = team_service.assert_team_exists(team_id)
    normalized_round_id = str(meeting_round_id or "").strip()
    if not normalized_round_id:
        raise HypothesisFirstChainError("Meeting round id is required.")
    meeting_round = meeting_rounds.get_meeting_round(normalized_team_id, normalized_round_id)[
        "meetingRound"
    ]
    request = dict(payload) if isinstance(payload, Mapping) else {}
    meeting_type = str(meeting_round.get("meetingType") or "")
    if meeting_type == CANDIDATE_GENERATION_MEETING_TYPE:
        return _close_generation_meeting(normalized_team_id, meeting_round, request)
    if meeting_type != HYPOTHESIS_REVIEW_MEETING_TYPE:
        raise HypothesisFirstChainError(
            "close_review_meeting only handles hypothesis_review rounds."
        )
    result = meeting_rounds.approve_meeting_closure(
        normalized_team_id, normalized_round_id, request
    )
    closed_record = result["meetingRound"]
    collection = _process_collection_decisions(
        normalized_team_id, closed_record, result, request
    )
    hypothesis_round = _generate_hypothesis_round(
        normalized_team_id,
        closed_record,
        reflection_runner=reflection_runner,
        pairwise_runner=pairwise_runner,
        pareto_runner=pareto_runner,
        metareview_runner=metareview_runner,
    )
    resume = None
    if runtime is not None:
        resume = resume_parent_runs(
            normalized_team_id,
            question_id=str(closed_record.get("question") or ""),
            runtime=runtime,
            trigger=f"close:{normalized_round_id}",
        )
    return {
        **result,
        "collection": collection,
        "hypothesisRound": hypothesis_round,
        "resume": resume,
    }


# ---------------------------------------------------------------------------
# handoff -> parent resume + next round


def record_collection_handoff(
    team_id: str,
    request_id: str,
    *,
    handoff_ref: str = "",
    runtime: Any = None,
    agent_runner: Any = None,
    background: bool = True,
    budget: Any = None,
) -> dict[str, Any]:
    """Record one child collection run's knowledge handoff (idempotent).

    Marks the request ``handed_off``, auto-opens the next review meeting
    (budget-gated, lineage-linked), and re-checks the parent runs'
    ``hypothesis_design`` readiness outside any writer transaction.
    """
    from core.web.services import team_service

    normalized_team_id = team_service.assert_team_exists(team_id)
    normalized_request_id = str(request_id or "").strip()
    if not normalized_request_id:
        raise HypothesisFirstChainError("request_id is required.")
    with _LOCK:
        records = _read_jsonl(_storage_path(normalized_team_id))
        latest = _latest_by_id(
            [item for item in records if item.get("recordKind") == COLLECTION_REQUEST_KIND],
            "requestId",
            normalized_request_id,
        )
        if latest is None:
            raise HypothesisFirstChainNotFoundError(
                f"Collection request {normalized_request_id} not found."
            )
        reused = str(latest.get("status") or "") == "handed_off"
        if not reused:
            latest = {
                **latest,
                "status": "handed_off",
                "handedOffAt": _utc_now(),
                "handoffRef": str(handoff_ref or "").strip(),
            }
            _append_jsonl(_storage_path(normalized_team_id), latest)
    next_meeting = open_next_review_meeting(
        normalized_team_id,
        previous_meeting_round_id=str(latest.get("meetingRoundId") or ""),
        collection_request_id=normalized_request_id,
        agent_runner=agent_runner,
        background=background,
        budget=budget,
    )
    resume = None
    if runtime is not None:
        resume = resume_parent_runs(
            normalized_team_id,
            question_id=str(latest.get("questionId") or ""),
            runtime=runtime,
            trigger=f"handoff:{normalized_request_id}",
        )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "status": "reused" if reused else "handed_off",
        "request": latest,
        "nextMeeting": next_meeting,
        "resume": resume,
    }


# ---------------------------------------------------------------------------
# parent run readiness re-check (writer-transaction-external, T5 discipline)


def _input_snapshot(run: Any) -> dict[str, Any]:
    try:
        snapshot = json.loads(str(getattr(run, "input_snapshot_json", "") or "{}"))
    except (TypeError, ValueError):
        return {}
    return snapshot if isinstance(snapshot, dict) else {}


def is_hypothesis_first_snapshot(snapshot: Mapping[str, Any]) -> bool:
    """The hypothesis-first marker lives inside researchObjectiveContract."""
    objective = snapshot.get("researchObjectiveContract")
    return isinstance(objective, Mapping) and objective.get("hypothesisFirst") is True


def resume_parent_runs(
    team_id: str,
    *,
    question_id: str,
    runtime: Any,
    trigger: str,
) -> dict[str, Any]:
    """Re-evaluate ``hypothesis_design`` for hypothesis-first parent runs.

    Runs entirely outside the writer transaction: readiness is evaluated on
    the caller thread, then a START/RETRY command is submitted with a
    deterministic idempotency key so identical triggers replay instead of
    duplicating attempts.
    """
    normalized_question_id = str(question_id or "").strip().upper()
    normalized_trigger = str(trigger or "").strip() or "manual"
    results: list[dict[str, Any]] = []
    runs = runtime.store.list_runs_for_team(team_id, CHALLENGE_CUP_WORKFLOW_ID)
    for run in runs:
        if str(getattr(run, "status", "") or "") in _TERMINAL_RUN_STATUSES:
            continue
        snapshot = _input_snapshot(run)
        if not is_hypothesis_first_snapshot(snapshot):
            continue
        run_question = str(
            snapshot.get("questionId") or getattr(run, "question_id", "") or ""
        ).upper()
        if normalized_question_id and run_question and run_question != normalized_question_id:
            continue
        results.append(_resume_one_run(runtime, run, normalized_trigger))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": team_id,
        "questionId": normalized_question_id,
        "trigger": normalized_trigger,
        "runs": results,
    }


def _resume_one_run(runtime: Any, run: Any, trigger: str) -> dict[str, Any]:
    from core.research.workflow.contracts import (
        ActorRef,
        CommandRequest,
        WorkflowCommandKind,
    )

    entry: dict[str, Any] = {"runId": run.run_id}
    idempotency_key = f"hf-chain:{run.run_id}:{HYPOTHESIS_DESIGN_NODE_ID}:{trigger}"
    existing = runtime.store.get_command_by_idempotency(run.run_id, idempotency_key)
    if existing is not None:
        # Identical trigger: replay the original command verbatim (kind and
        # expected version come from the stored record so the request hash
        # matches); the service validates consistency and never re-executes.
        replay = CommandRequest(
            command_id=f"cmd-hf-chain-{_stable_hash({'runId': run.run_id, 'trigger': trigger})[:16]}",
            run_id=run.run_id,
            team_id=run.team_id,
            command=WorkflowCommandKind(str(existing.command_kind)),
            node_id=HYPOTHESIS_DESIGN_NODE_ID,
            expected_run_version=int(existing.expected_run_version),
            idempotency_key=idempotency_key,
            payload={},
            requested_by=ActorRef("system", "hypothesis-first-chain"),
            requested_at_ms=0,
        )
        try:
            receipt = runtime.command_service.submit(replay)
        except Exception as exc:
            entry["action"] = "skipped"
            entry["error"] = str(exc)
            entry["errorType"] = type(exc).__name__
            return entry
        entry["action"] = "replayed"
        entry["commandId"] = receipt.command_id
        entry["receiptStatus"] = receipt.status
        return entry

    latest = runtime.store.latest_attempt(run.run_id, HYPOTHESIS_DESIGN_NODE_ID)
    if latest is not None and str(latest.status) in _ACTIVE_ATTEMPT_STATUSES:
        entry["action"] = "already_active"
        entry["attemptId"] = latest.attempt_id
        return entry
    if latest is not None and str(latest.status) == "succeeded":
        entry["action"] = "already_succeeded"
        entry["attemptId"] = latest.attempt_id
        return entry

    command_kind = (
        WorkflowCommandKind.START_NODE
        if latest is None
        else WorkflowCommandKind.RETRY_NODE
    )
    fresh = runtime.store.get_run(run.run_id)
    expected_version = int(fresh.run_version if fresh is not None else run.run_version)
    request = CommandRequest(
        command_id=f"cmd-hf-chain-{_stable_hash({'runId': run.run_id, 'trigger': trigger})[:16]}",
        run_id=run.run_id,
        team_id=run.team_id,
        command=command_kind,
        node_id=HYPOTHESIS_DESIGN_NODE_ID,
        expected_run_version=expected_version,
        idempotency_key=idempotency_key,
        payload={},
        requested_by=ActorRef("system", "hypothesis-first-chain"),
        requested_at_ms=0,
    )
    readiness = runtime.readiness.evaluate(
        team_id=run.team_id,
        run_id=run.run_id,
        node_id=HYPOTHESIS_DESIGN_NODE_ID,
        context=runtime.readiness_context,
        use_cache=False,
    )
    entry["ready"] = readiness.ready
    entry["blockers"] = [blocker.code for blocker in readiness.blockers]
    if not readiness.ready:
        entry["action"] = "not_ready"
        return entry
    try:
        receipt = runtime.command_service.submit(request)
    except Exception as exc:
        entry["action"] = "skipped"
        entry["error"] = str(exc)
        entry["errorType"] = type(exc).__name__
        return entry
    entry["action"] = (
        "started" if command_kind is WorkflowCommandKind.START_NODE else "retried"
    )
    entry["commandId"] = receipt.command_id
    entry["receiptStatus"] = receipt.status
    return entry


# ---------------------------------------------------------------------------
# chain state read model (readiness evaluators)


def _question_meetings(team_id: str, question_id: str) -> list[dict[str, Any]]:
    from core.web.services.team_workflow import meeting_rounds

    meetings = meeting_rounds.list_meeting_rounds(team_id)["meetings"]
    return [
        meeting
        for meeting in meetings
        if str(meeting.get("meetingType") or "") == HYPOTHESIS_REVIEW_MEETING_TYPE
        and str(meeting.get("question") or "").upper() == question_id.upper()
    ]


def _question_hypothesis_rounds(team_id: str, question_id: str) -> list[dict[str, Any]]:
    from core.web.services.team_workflow import hypothesis_rounds

    rounds = hypothesis_rounds.list_hypothesis_rounds(team_id)["rounds"]
    return [
        item
        for item in rounds
        if str(item.get("question") or "").upper() == question_id.upper()
    ]


def _question_template_baselines(team_id: str, question_id: str) -> list[dict[str, Any]]:
    from core.web.services.team_workflow import research_templates

    baselines = research_templates.list_template_baselines(team_id)["baselines"]
    return [
        item
        for item in baselines
        if str(item.get("question") or "").upper() == question_id.upper()
        and str(item.get("status") or "") == "frozen"
    ]


def chain_state(team_id: str, question_id: str) -> dict[str, Any]:
    """Aggregate the hypothesis-first chain state for one scoped question.

    Read-only; used by the readiness evaluators.  Association is by the scope
    ``question`` field (one hypothesis-first chain per team/question in DEV).
    """
    from core.web.services import team_service
    from core.web.services.team_workflow import hypothesis_selection as selections

    normalized_team_id = team_service.assert_team_exists(team_id)
    normalized_question_id = str(question_id or "").strip().upper()
    records = _records(normalized_team_id)
    links = [
        link
        for link in _review_round_links(records)
        if str(link.get("questionId") or "").upper() == normalized_question_id
    ]
    requests = [
        request
        for request in _collection_requests(records)
        if str(request.get("questionId") or "").upper() == normalized_question_id
    ]
    meetings = _question_meetings(normalized_team_id, normalized_question_id)
    meeting_by_id = {
        str(meeting.get("meetingRoundId") or ""): meeting for meeting in meetings
    }
    selection_id = ""
    # links are sorted by roundIndex; the CURRENT selection must come from the
    # newest appended link record, not the max-roundIndex one (a fresh
    # selection's round 1 would otherwise lose to the previous selection's
    # final round).
    question_links_append_order = [
        item
        for item in records
        if str(item.get("recordKind") or "") == REVIEW_ROUND_LINK_KIND
        and str(item.get("questionId") or "").upper() == normalized_question_id
    ]
    if question_links_append_order:
        selection_id = str(question_links_append_order[-1].get("selectionId") or "")
    if not selection_id:
        try:
            scope = _question_scope_envelope(
                normalized_team_id,
                normalized_question_id,
            )
            scope["scopeHash"] = scope_hash_for(
                **{field: scope[field] for field in _SCOPE_FIELDS},
                agent_id=scope["agentId"],
                mode=scope["mode"],
            )
            latest_selection = selections.get_latest_hypothesis_selection(
                normalized_team_id,
                normalized_question_id,
                scope=scope,
            )
        except selections.ResearchHypothesisSelectionError:
            latest_selection = {}
        selection = latest_selection.get("selection") or {}
        selection_id = str(selection.get("selectionId") or "")

    first_meeting_id = ""
    if links:
        first_link = next(
            (link for link in links if int(link.get("roundIndex") or 0) == 1), links[0]
        )
        first_meeting_id = str(first_link.get("meetingRoundId") or "")
    elif meetings:
        first_meeting_id = str(meetings[0].get("meetingRoundId") or "")
    first_meeting = meeting_by_id.get(first_meeting_id) or {}
    first_meeting_closed = (
        bool(first_meeting)
        and str(first_meeting.get("status") or "") == "closed"
    )
    selection_links = (
        [item for item in links if str(item.get("selectionId") or "") == selection_id]
        if selection_id
        else []
    )
    # Review meetings of superseded selections must not block collection
    # readiness forever; only the current selection's meetings count (plus
    # generation meetings, which are per-question and not selection-scoped).
    current_selection_meeting_ids = {
        str(link.get("meetingRoundId") or "") for link in selection_links
    }
    open_meeting_ids = [
        str(meeting.get("meetingRoundId") or "")
        for meeting in meetings
        if str(meeting.get("status") or "") != "closed"
        and (
            str(meeting.get("meetingType") or "") != HYPOTHESIS_REVIEW_MEETING_TYPE
            or not current_selection_meeting_ids
            or str(meeting.get("meetingRoundId") or "") in current_selection_meeting_ids
        )
    ]
    pending_requests = [
        request for request in requests if str(request.get("status") or "") != "handed_off"
    ]

    rounds = _question_hypothesis_rounds(normalized_team_id, normalized_question_id)
    latest_round = rounds[-1] if rounds else {}
    latest_round_id = str(latest_round.get("roundId") or "")
    latest_round_closed = str(latest_round.get("status") or "") == "closed"
    meta_review = (
        dict(latest_round.get("metaReview"))
        if isinstance(latest_round.get("metaReview"), Mapping)
        else {}
    )
    latest_meeting_ids = {
        str(ref.get("id") or "")
        for ref in list(latest_round.get("meetingRefs") or [])
        if isinstance(ref, Mapping) and str(ref.get("kind") or "") == "meeting_round"
    }
    new_requests_this_round = [
        request
        for request in requests
        if str(request.get("meetingRoundId") or "") in latest_meeting_ids
    ]
    converged = bool(
        latest_round
        and latest_round_closed
        and bool(meta_review.get("accepted"))
        and not new_requests_this_round
        and not pending_requests
    )
    if not latest_round:
        convergence_detail = "尚无闭环的假说评审轮次"
    elif not latest_round_closed:
        convergence_detail = f"最近一轮 {latest_round_id} 尚未 closed"
    elif not bool(meta_review.get("accepted")):
        convergence_detail = f"最近一轮 {latest_round_id} 的 MetaReview 未 accepted"
    elif new_requests_this_round:
        convergence_detail = f"最近一轮 {latest_round_id} 产生了新的搜集决策"
    elif pending_requests:
        convergence_detail = "仍有待交接的搜集请求"
    else:
        convergence_detail = "converged"

    baselines = _question_template_baselines(normalized_team_id, normalized_question_id)
    # Budget authority lives on the current selection's links: raised limits
    # are persisted per round, and exhaustion counts only this selection's
    # rounds (superseded/older selections must not fake budget_exhausted).
    selection_round_index = max(
        (int(item.get("roundIndex") or 0) for item in selection_links), default=0
    )
    budget = max(
        [int(item.get("roundBudget") or 0) for item in selection_links]
        + [DEFAULT_ROUND_BUDGET]
    )
    candidates = [
        record
        for record in records
        if str(record.get("recordKind") or "") == CANDIDATE_KIND
        and str(record.get("questionId") or "").upper() == normalized_question_id
    ]
    generation_meetings = _question_generation_meetings(
        normalized_team_id, normalized_question_id
    )
    generation_meeting = generation_meetings[-1] if generation_meetings else {}
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": normalized_team_id,
        "questionId": normalized_question_id,
        "selectionId": selection_id,
        "meetingCount": len(meetings),
        "firstMeetingId": first_meeting_id,
        "firstMeetingClosed": first_meeting_closed,
        "openMeetingIds": open_meeting_ids,
        "collectionRequests": requests,
        "collectionRequestCount": len(requests),
        "pendingCollectionCount": len(pending_requests),
        # A closed, converged review chain that never asked for more
        # evidence is itself a discussion decision: "no additional collection
        # needed". Treating only handed-off requests as ready wedged live
        # flows whose reviews legitimately concluded the anchors suffice. A
        # round that DID request evidence (even with an invalid envelope)
        # keeps blocking — that request must be repaired, not waived.
        "collectionReady": bool(first_meeting_closed and requests)
        or bool(
            converged
            and not open_meeting_ids
            and first_meeting_closed
            and not _question_requested_evidence(
                normalized_team_id, normalized_question_id
            )
        ),
        "hypothesisRoundCount": len(rounds),
        "latestHypothesisRoundId": latest_round_id,
        "hypothesisConverged": converged,
        "convergenceDetail": convergence_detail,
        "roundBudget": budget,
        "budgetExhausted": bool(not converged and selection_round_index >= budget),
        "templateBaselineExists": bool(baselines),
        "templateBaselineIds": [
            str(item.get("baselineId") or "") for item in baselines
        ],
        "candidateCount": len(candidates),
        "generationMeetingId": str(generation_meeting.get("meetingRoundId") or ""),
        "generationMeetingStatus": str(generation_meeting.get("status") or ""),
    }
