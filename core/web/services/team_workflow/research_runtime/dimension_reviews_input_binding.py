"""Deterministic input bindings that let the fail-closed ``dimension_reviews``
writer accept hypothesis-first chain rounds.

The writer (``dimension_reviews_artifact_writer``) requires two things the
generation chain historically never produced: a 64-hex ``inputSnapshotHash``
binding, and per-row canonical typed evidence refs.  This module is the single
authority for both derivations.  Everything here is deterministic over real
persisted records — recomputable means auditable — and never invents content:

1. ``inputSnapshotHash`` is ``canonical_sha256`` over the round's complete
   input identity: team, question, selection, scope hash, the ordered bound
   meetings with their digest content hashes and decision ids, and the stable
   per-candidate review scopes.  Generation computes it from the exact inputs
   the review consumed; the audit path recomputes it from the stored round
   plus the meeting/digest stores and must observe the identical value.
2. Bare review-row citations (``candidate-…`` chat citations emitted by the
   reflection runner) are mapped to readable canonical
   ``evidence_card_batch://…`` refs resolved through the team's
   ClaimEvidenceStore — the same store authority the writer's read-back
   verifies by content hash.  Already-canonical refs pass through untouched;
   a citation that resolves to no scoped evidence cards is left as-is (the
   writer then blocks with its own precise code), and rows without any
   citation are never filled in — reconstructing evidence the reviewer never
   cited would be fabrication, not derivation.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, Sequence

from .artifact_readback_registry import (
    build_canonical_ref,
    load_scoped_artifact_payload,
    parse_canonical_ref,
)
from .dimension_reviews_artifact_writer import _candidate_scope
from .human_gate_artifacts import canonical_sha256

SNAPSHOT_KIND = "hypothesis_round_input_snapshot"
SNAPSHOT_SCHEMA_VERSION = 1

# The readable canonical authority for one cited evidence candidate: the
# claim-evidence card batch of the source-collection run holding its cards.
_EVIDENCE_CARD_KIND = "evidence_card_batch"


def selection_id_from_meeting(meeting: Mapping[str, Any]) -> str:
    """Extract the ``hypothesis_selection:`` ref from a meeting's inputs.

    Mirrors ``hypothesis_first_chain._selection_id_from_meeting``; duplicated
    on purpose because that chain module imports this package's services and
    a reverse import would be circular.
    """

    for ref in _string_list(meeting.get("inputArtifactRefs")):
        if ref.startswith("hypothesis_selection:"):
            return ref.split(":", 1)[-1].strip()
    return ""


def _text(value: Any) -> str:
    return str(value or "").strip()


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _text(item)
        if text and text not in seen:
            result.append(text)
            seen.add(text)
    return result


def round_input_snapshot_hash(
    *,
    team_id: Any,
    question_id: Any,
    selection_id: Any,
    scope_hash: Any,
    meetings: Sequence[Mapping[str, Any]],
    digests: Sequence[Mapping[str, Any]],
    decisions: Sequence[Mapping[str, Any]],
    candidates: Sequence[Mapping[str, Any]],
) -> str:
    """Hash the exact authoritative inputs one hypothesis review round ran on.

    ``meetings``/``digests``/``decisions``/``candidates`` are the ordered,
    already-resolved records from the generation path.  Only identity and
    stable-content fields enter the hash so an auditor can recompute it from
    the stored round: meeting/digest/decision ids (also persisted on the
    round's ``meetingRefs``), digest content hashes (persisted digest store),
    and the writer's own stable candidate scope projection.
    """

    return canonical_sha256(
        {
            "kind": SNAPSHOT_KIND,
            "schemaVersion": SNAPSHOT_SCHEMA_VERSION,
            "teamId": _text(team_id),
            "questionId": _text(question_id).upper(),
            "selectionId": _text(selection_id),
            "scopeHash": _text(scope_hash),
            "meetingRoundIds": [
                _text(item.get("meetingRoundId")) for item in meetings if isinstance(item, Mapping)
            ],
            "meetingDigestIds": [
                _text(item.get("digestId")) for item in digests if isinstance(item, Mapping)
            ],
            "meetingDigestContentHashes": [
                _text(item.get("contentHash")) for item in digests if isinstance(item, Mapping)
            ],
            "meetingDecisionIds": [
                _text(item.get("decisionId")) for item in decisions if isinstance(item, Mapping)
            ],
            "candidates": [
                _candidate_scope(item) for item in candidates if isinstance(item, Mapping)
            ],
        }
    )


def recompute_round_input_snapshot_hash(
    team_id: str,
    round_record: Mapping[str, Any],
    *,
    meetings: Sequence[Mapping[str, Any]] | None = None,
) -> str:
    """Recompute the snapshot hash from the stored round (audit path).

    Resolves meeting refs, digest content hashes and the selection id from
    the durable stores exactly as generation did, then hashes the same
    binding.  Returns ``""`` (never a substitute value) when any referenced
    record no longer resolves — the writer stays fail-closed on an empty
    hash.
    """

    from core.web.services.team_workflow import meeting_rounds as _meeting_rounds

    round_id = _text(round_record.get("roundId"))
    if not round_id:
        return ""
    resolved_meetings: list[dict[str, Any]] = list(
        meeting for meeting in (meetings or []) if isinstance(meeting, Mapping)
    )
    meeting_round_ids: list[str] = []
    meeting_digest_ids: list[str] = []
    meeting_decision_ids: list[str] = []
    for ref in list(round_record.get("meetingRefs") or []):
        if not isinstance(ref, Mapping):
            continue
        kind = _text(ref.get("kind"))
        ref_id = _text(ref.get("id"))
        if not ref_id:
            continue
        if kind == "meeting_round":
            meeting_round_ids.append(ref_id)
        elif kind == "meeting_digest":
            meeting_digest_ids.append(ref_id)
        elif kind == "decision_record":
            meeting_decision_ids.append(ref_id)
    if not resolved_meetings:
        resolved_meetings = []
        for meeting_id in meeting_round_ids:
            try:
                meeting = _meeting_rounds.get_meeting_round(team_id, meeting_id)[
                    "meetingRound"
                ]
            except Exception:  # noqa: BLE001 - unresolvable input stays fail-closed
                return ""
            resolved_meetings.append(dict(meeting))
    if not meeting_round_ids:
        meeting_round_ids = [
            _text(item.get("meetingRoundId")) for item in resolved_meetings
        ]
    else:
        # The binding order is the round's own meetingRefs order (the order
        # generation hashed), never the caller's fan-in projection order.
        by_id = {
            _text(item.get("meetingRoundId")): item for item in resolved_meetings
        }
        if any(meeting_id not in by_id for meeting_id in meeting_round_ids):
            return ""
        resolved_meetings = [by_id[meeting_id] for meeting_id in meeting_round_ids]
    digest_records = _meeting_rounds._read_jsonl(
        _meeting_rounds._digests_path(team_id)
    )
    digests: list[dict[str, Any]] = []
    for digest_id in meeting_digest_ids:
        digest = _meeting_rounds._latest_by_id(
            digest_records, "digestId", digest_id
        )
        if digest is None:
            return ""
        digests.append(dict(digest))
    decisions: list[dict[str, Any]] = [
        {"decisionId": decision_id} for decision_id in meeting_decision_ids
    ]
    selection_id = ""
    for meeting in resolved_meetings:
        selection_id = selection_id_from_meeting(meeting)
        if selection_id:
            break
    return round_input_snapshot_hash(
        team_id=team_id,
        question_id=round_record.get("question"),
        selection_id=selection_id,
        scope_hash=round_record.get("scopeHash"),
        meetings=resolved_meetings,
        digests=digests,
        decisions=decisions,
        candidates=[
            item
            for item in list(round_record.get("candidates") or [])
            if isinstance(item, Mapping)
        ],
    )


def evidence_batch_ref_for_run(team_id: str, run_id: str) -> str:
    """Content-addressed ref of one run's scoped claim-evidence card batch.

    Uses the exact loader the writer's read-back verification uses, so the
    hash in the ref is the hash read-back recomputes.  Returns ``""`` when
    the run holds no strictly-scoped evidence cards.
    """

    normalized_run = _text(run_id)
    if not normalized_run:
        return ""
    payload = load_scoped_artifact_payload(
        _EVIDENCE_CARD_KIND,
        team_id=_text(team_id),
        authority_run_id=normalized_run,
    )
    if not payload:
        return ""
    return build_canonical_ref(
        kind=_EVIDENCE_CARD_KIND,
        team_id=_text(team_id),
        authority_run_id=normalized_run,
        content_hash=canonical_sha256(payload),
    )


def canonicalize_dimension_review_evidence(
    team_id: str,
    review: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Project a round's review rows onto canonical evidence refs.

    Returns a deep-copied projection in which every bare ``candidate-…``
    citation that resolves to real scoped evidence cards is replaced by the
    readable ``evidence_card_batch://…`` ref of the run holding those cards.
    Already-canonical refs and unresolvable refs pass through unchanged (the
    writer judges them), and citation-less rows are left empty on purpose.

    The report is deterministic and bounded; ``unresolvedRefs`` lists the
    exact citations a later audit should expect to see blocked.
    """

    from core.research.evidence import ClaimEvidenceStore
    from core.infrastructure.path_containment import PROJECT_ROOT

    report: dict[str, Any] = {
        "resolvedCitations": {},
        "unresolvedRefs": [],
        "rowsWithoutRefs": 0,
        "canonicalRefsPassedThrough": 0,
    }
    citation_refs: dict[str, list[str]] = {}

    def _resolve(citation: str) -> list[str]:
        if citation in citation_refs:
            return citation_refs[citation]
        refs: list[str] = []
        try:
            cards = ClaimEvidenceStore(PROJECT_ROOT).list(
                team_id, candidate_id=citation
            )
        except Exception:  # noqa: BLE001 - unreadable store leaves the ref as-is
            cards = []
        run_ids = sorted(
            {
                _text(card.get("sourceCollectionRunId"))
                for card in cards
                if isinstance(card, Mapping) and _text(card.get("sourceCollectionRunId"))
            }
        )
        for run_id in run_ids:
            ref = evidence_batch_ref_for_run(team_id, run_id)
            if ref:
                refs.append(ref)
        citation_refs[citation] = refs
        return refs

    def _walk(rows: Any) -> Any:
        if not isinstance(rows, (list, tuple)):
            return rows
        projected: list[Any] = []
        for row in rows:
            if not isinstance(row, Mapping):
                projected.append(row)
                continue
            new_row = dict(row)
            raw_refs = new_row.get("evidence_refs")
            if raw_refs is None:
                raw_refs = new_row.get("evidenceRefs")
            refs = _string_list(raw_refs)
            if not refs:
                if isinstance(raw_refs, (list, tuple)):
                    report["rowsWithoutRefs"] += 1
                projected.append(new_row)
                continue
            output_refs: list[str] = []
            for ref in refs:
                if parse_canonical_ref(ref) is not None:
                    report["canonicalRefsPassedThrough"] += 1
                    output_refs.append(ref)
                    continue
                mapped = _resolve(ref)
                if mapped:
                    report["resolvedCitations"].setdefault(ref, mapped)
                    output_refs.extend(mapped)
                else:
                    if ref not in report["unresolvedRefs"]:
                        report["unresolvedRefs"].append(ref)
                    output_refs.append(ref)
            new_row["evidence_refs"] = list(dict.fromkeys(output_refs))
            new_row.pop("evidenceRefs", None)
            projected.append(new_row)
        return projected

    projection = deepcopy(dict(review))
    direct = projection.get("dimensionReviews") or projection.get("dimension_reviews")
    if isinstance(direct, (list, tuple)):
        projection["dimensionReviews"] = _walk(direct)
        projection.pop("dimension_reviews", None)
    nested_candidates = projection.get("candidates")
    if isinstance(nested_candidates, list):
        new_candidates: list[Any] = []
        for candidate in nested_candidates:
            if not isinstance(candidate, Mapping):
                new_candidates.append(candidate)
                continue
            new_candidate = dict(candidate)
            nested = new_candidate.get("dimensionReviews") or new_candidate.get(
                "dimension_reviews"
            )
            if isinstance(nested, (list, tuple)):
                new_candidate["dimensionReviews"] = _walk(nested)
                new_candidate.pop("dimension_reviews", None)
            new_candidates.append(new_candidate)
        projection["candidates"] = new_candidates
    report["resolvedCitationCount"] = len(report["resolvedCitations"])
    return projection, report


__all__ = [
    "SNAPSHOT_KIND",
    "SNAPSHOT_SCHEMA_VERSION",
    "canonicalize_dimension_review_evidence",
    "evidence_batch_ref_for_run",
    "recompute_round_input_snapshot_hash",
    "round_input_snapshot_hash",
    "selection_id_from_meeting",
]
