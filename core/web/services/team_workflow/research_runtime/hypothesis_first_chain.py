"""Hypothesis-first orchestration chain (HF-4).

Owns the append-only chain ledger that wires the hypothesis-first event chain:

- selection -> first hypothesis-review meeting auto-open (round 1), with the
  room ``roundId`` <-> ``meetingRoundId`` two-way binding produced by
  ``meeting_runtime.open_hypothesis_review_meeting``;
- meeting closure -> ``request_new_evidence`` decisions carrying a valid
  ``searchEnvelope`` trigger stage-1 collection through the existing
  ``research_knowledge_collection_facade`` (idempotent per decision; the facade
  itself stays idempotent by scopeHash and no graph recursion happens here);
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
import os
import tempfile
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
REQUEST_EVIDENCE_DECISION = "request_new_evidence"
HYPOTHESIS_REVIEW_MEETING_TYPE = "hypothesis_review"
HYPOTHESIS_DESIGN_NODE_ID = "hypothesis_design"
_SCOPE_FIELDS = ("program", "theme", "campaign", "question", "branch", "workflow")
_TERMINAL_RUN_STATUSES = frozenset({"succeeded", "failed", "cancelled", "archived"})
_ACTIVE_ATTEMPT_STATUSES = frozenset(
    {"starting", "dispatching", "running", "waiting_human"}
)

PROJECT_ROOT = Path(__file__).resolve().parents[5]
_LOCK = threading.RLock()


class HypothesisFirstChainError(RuntimeError):
    """Base error for hypothesis-first chain orchestration."""


class HypothesisFirstChainNotFoundError(HypothesisFirstChainError):
    """Raised when a chain record (collection request / link) does not exist."""


# ---------------------------------------------------------------------------
# storage primitives (same discipline as hypothesis_selection)


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
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise HypothesisFirstChainError(
                f"Invalid hypothesis-first chain JSONL at line {line_number}."
            ) from exc
        if not isinstance(payload, dict):
            raise HypothesisFirstChainError(
                f"Invalid hypothesis-first chain record at line {line_number}."
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


def _latest_by_id(
    records: list[dict[str, Any]], field: str, record_id: str
) -> dict[str, Any] | None:
    matched = [record for record in records if str(record.get(field) or "") == record_id]
    return matched[-1] if matched else None


def _normalized_str_list(value: Any) -> list[str]:
    return [str(item or "").strip() for item in list(value or []) if str(item or "").strip()]


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


def _room_participants(room_id: str) -> list[str]:
    from core.web.services import chat_room_service

    room_detail = chat_room_service.get_chat_room_detail(room_id)
    if room_detail is None:
        raise HypothesisFirstChainError("Team linked chat room not found.")
    return [
        str(item.get("agentId") or "").strip()
        for item in list(room_detail.get("participants") or [])
        if isinstance(item, dict) and str(item.get("agentId") or "").strip()
    ]


def _team_role_by_agent(team_id: str) -> dict[str, str]:
    from core.web.services import team_service

    team = team_service.get_team(team_id)
    return {
        str(member.get("agentId") or "").strip(): str(member.get("role") or "").strip()
        for member in list(team.get("members") or [])
        if isinstance(member, dict) and str(member.get("agentId") or "").strip()
    }


def _record_review_round_link(
    team_id: str,
    *,
    meeting_round_id: str,
    previous_meeting_round_id: str,
    selection_id: str,
    collection_request_id: str,
    question_id: str,
    round_index: int,
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
            for key in ("previousMeetingRoundId", "collectionRequestId", "selectionId", "roundIndex"):
                if existing.get(key) != record.get(key):
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
) -> dict[str, Any]:
    """Open (or reuse) one hypothesis-review meeting for a selection record.

    Participants derive from the team's linked chat room; the meeting id is
    deterministic per selection/round so replays reuse instead of duplicating.
    """
    from core.web.services import team_service
    from core.web.services.team_workflow import meeting_runtime

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

    _team, room_id = meeting_runtime._ensure_linked_room(normalized_team_id)
    participants = _room_participants(room_id)
    if not participants:
        raise ContractValidationError(
            "opening a hypothesis review meeting requires at least one participant"
        )
    role_by_agent = _team_role_by_agent(normalized_team_id)
    participant_role_ids = [
        role_by_agent.get(agent_id) or "member" for agent_id in participants
    ]

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
            "participants": participants,
            "participantRoleIds": participant_role_ids,
            "inputArtifactRefs": extra_refs,
        }
    )
    opened = meeting_runtime.open_hypothesis_review_meeting(
        normalized_team_id,
        payload,
        agent_runner=agent_runner,
        background=background,
    )
    link = _record_review_round_link(
        normalized_team_id,
        meeting_round_id=normalized_meeting_round_id,
        previous_meeting_round_id=normalized_previous_id,
        selection_id=selection_id,
        collection_request_id=normalized_request_id,
        question_id=question_id,
        round_index=normalized_round_index,
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
        "createdAt": _utc_now(),
        "handedOffAt": "",
        "handoffRef": "",
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

    persisted_ids = {
        str(item.get("decisionId") or "")
        for item in list(close_result.get("decisions") or [])
        if isinstance(item, Mapping)
    }
    requests_out: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
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
        except Exception as exc:
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
        raise HypothesisFirstChainError(
            f"question {question_id} has no approved v2 question artifact"
        )
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
    if str(meeting_round.get("meetingType") or "") != HYPOTHESIS_REVIEW_MEETING_TYPE:
        raise HypothesisFirstChainError(
            "close_review_meeting only handles hypothesis_review rounds."
        )
    request = dict(payload) if isinstance(payload, Mapping) else {}
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
    if links:
        selection_id = str(links[-1].get("selectionId") or "")
    if not selection_id:
        try:
            latest_selection = selections.get_latest_hypothesis_selection(
                normalized_team_id, normalized_question_id
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
    open_meeting_ids = [
        str(meeting.get("meetingRoundId") or "")
        for meeting in meetings
        if str(meeting.get("status") or "") != "closed"
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
    budget = DEFAULT_ROUND_BUDGET
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
        "collectionReady": bool(first_meeting_closed and requests),
        "hypothesisRoundCount": len(rounds),
        "latestHypothesisRoundId": latest_round_id,
        "hypothesisConverged": converged,
        "convergenceDetail": convergence_detail,
        "roundBudget": budget,
        "budgetExhausted": bool(not converged and len(meetings) >= budget),
        "templateBaselineExists": bool(baselines),
        "templateBaselineIds": [
            str(item.get("baselineId") or "") for item in baselines
        ],
    }
