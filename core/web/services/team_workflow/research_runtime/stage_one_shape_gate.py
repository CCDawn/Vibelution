"""Launch-shape conditional demands for the stage-one closure gate.

The stage-one completion policy is one frozen, hash-pinned resource for every
authorized question, so its ``requiredArtifactKinds`` list cannot know which
launch shape a concrete run used.  Hypothesis-first chain launches
(``researchObjectiveContract.hypothesisFirst``) start from a source collection
and run their review chain in dev/platform mode, and three of the policy's
authorities are structurally tied to facts such a launch never produces:

- ``stage1_research_plan`` and ``competition_alignment`` are exact projections
  of ONE already-approved Challenge-Cup question artifact.  A chain launch
  never creates a challenge question run, so no approved question authority
  exists to project; the canonical writer refuses every other source, and
  inventing one would be fabrication.
- ``dimension_reviews`` rows written by the chain's dev-mode review runner cite
  the claim-evidence ledger (and some rows cite no explicit refs at all).  The
  canonical writer only accepts addressable, readable canonical artifact refs,
  so the persisted rows can never satisfy it — even though the complete
  seven-dimension audit itself is persisted verbatim on the accepted round
  record, where it stays queryable.

For exactly these kinds, and only for hypothesis-first launches, this module
downgrades the gate demand to *conditionally required*: a kind stays required
whenever its authority is actually readable or its source authority exists,
and a question-driven run is never downgraded.  Everything else keeps its
fail-closed demand; no blocker is waived without persisted evidence, and no
payload is ever faked.

The same doctrine covers the policy's ``requiredReceiptStages``: chain meeting
calls are structurally unable to register run-bound receipts (they run before
the formal run exists), so :func:`downgraded_stage_one_receipt_stages` waives
exactly that demand — only with hash-anchored meeting digests and the complete
persisted review audit on the accepted round.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

# Kinds projected from the approved question authority: their ONLY source is
# the approved question artifact, so they are undemandable when that authority
# does not exist for the run's question.
QUESTION_AUTHORITY_PROJECTED_KINDS: tuple[str, ...] = (
    "stage1_research_plan",
    "competition_alignment",
)

# Kind whose audit rows are persisted complete on the accepted chain round but
# whose evidence citations are not canonically addressable by the writer.
ROUND_ROW_BACKED_KINDS: tuple[str, ...] = ("dimension_reviews",)

# Downgrade reason codes surfaced in materialization reports and gate logs.
REASON_QUESTION_AUTHORITY_SOURCE_ABSENT = "stage_one_question_authority_source_absent"
REASON_ROUND_ROWS_PERSISTED_ON_CHAIN_ROUND = "dimension_reviews_rows_persisted_on_chain_round"
REASON_MEETING_MODEL_EVIDENCE_PERSISTED = "hypothesis_first_meeting_model_evidence_persisted"


def is_hypothesis_first_launch(input_snapshot: Mapping[str, Any] | None) -> bool:
    """True when the frozen run snapshot marks a hypothesis-first chain launch."""
    if not isinstance(input_snapshot, Mapping):
        return False
    objective = input_snapshot.get("researchObjectiveContract")
    return isinstance(objective, Mapping) and objective.get("hypothesisFirst") is True


def _kind_readable(
    kind: str,
    *,
    team_id: str,
    workflow_run_id: str,
    source_collection_run_id: str,
) -> bool:
    """Mirror the closure readback probe used by the completion gate."""
    from .artifact_readback_registry import load_scoped_artifact_payload

    try:
        payload = load_scoped_artifact_payload(
            kind,
            team_id=team_id,
            authority_run_id=str(source_collection_run_id or workflow_run_id or "").strip(),
            workflow_run_id=str(workflow_run_id or "").strip(),
        )
    except Exception:  # noqa: BLE001 - unreadable means still demandable
        return False
    return isinstance(payload, Mapping) and bool(payload.get("payload"))


def _approved_question_authority_present(team_id: str, question_id: str) -> bool:
    """Fail-closed authority existence check: uncertainty counts as present."""
    from core.web.services.team_workflow.research_runtime import question_launch

    try:
        detail = question_launch._approved_details(team_id).get(str(question_id or "").upper())
    except Exception:  # noqa: BLE001 - never downgrade on an uncertain lookup
        return True
    return isinstance(detail, Mapping) and bool(detail)


def _accepted_round_rows_complete(team_id: str, question_id: str) -> bool:
    """True when the latest accepted round carries the complete audit rows.

    "Complete" mirrors the canonical writer's row contract minus the canonical
    evidence-ref requirement: at least two uniquely identified candidates, and
    every required review dimension present for each with a rating, rationale,
    and reviewer.  The rows themselves stay the persisted authority.
    """
    from core.research.competition.question_result_package import (
        REQUIRED_REVIEW_DIMENSIONS,
        REVIEW_DIMENSION_RATINGS,
    )

    from .hypothesis_first_chain import _question_hypothesis_rounds

    try:
        rounds = _question_hypothesis_rounds(team_id, question_id)
    except Exception:  # noqa: BLE001 - unreadable chain keeps the demand
        return False
    accepted = [
        round_record
        for round_record in rounds
        if str(round_record.get("status") or "") == "closed"
        and isinstance(round_record.get("metaReview"), Mapping)
        and round_record["metaReview"].get("accepted") is True
    ]
    if not accepted:
        return False
    candidates = [
        dict(item)
        for item in (accepted[-1].get("candidates") or [])
        if isinstance(item, Mapping)
    ]
    candidate_ids = {
        str(item.get("candidateId") or "").strip()
        for item in candidates
        if str(item.get("candidateId") or "").strip()
    }
    if len(candidate_ids) < 2:
        return False
    allowed_ratings = set(REVIEW_DIMENSION_RATINGS)
    for candidate_id in candidate_ids:
        candidate = next(
            (
                item
                for item in candidates
                if str(item.get("candidateId") or "").strip() == candidate_id
            ),
            None,
        )
        rows = [
            dict(row)
            for row in ((candidate or {}).get("dimensionReviews") or [])
            if isinstance(row, Mapping)
        ]
        by_dimension = {
            str(row.get("dimension") or "").strip(): row for row in rows
        }
        for dimension in REQUIRED_REVIEW_DIMENSIONS:
            row = by_dimension.get(dimension)
            if row is None:
                return False
            if (
                str(row.get("rating") or "").strip().lower()
                not in allowed_ratings
                or not str(row.get("rationale") or "").strip()
                or not str(
                    row.get("reviewer")
                    or row.get("reviewerId")
                    or row.get("reviewerAgentId")
                    or ""
                ).strip()
            ):
                return False
    return True


def _accepted_round_meeting_digest_evidence(team_id: str, question_id: str) -> bool:
    """True when the accepted round's closed meetings carry approved digests.

    Chain meetings never register run-bound ``ModelInvocationReceipts`` — the
    speaker calls run in dev/platform meeting scope, bound to the meeting and
    its chat room, not to the formal run that starts afterwards.  What does
    persist is the model product itself: a closed meeting's approved digest is
    hash-anchored (``contentHash``) and cites the real discussion messages
    (``sourceMessageRefs``).  Every closed meeting bound to the accepted round
    must resolve to such a digest; anything unreadable or unanchored keeps the
    receipt demand — fail-closed.
    """
    from core.web.services.team_workflow import meeting_rounds as meeting_rounds_service

    from .hypothesis_first_chain import _question_hypothesis_rounds

    try:
        rounds = _question_hypothesis_rounds(team_id, question_id)
    except Exception:  # noqa: BLE001 - unreadable chain keeps the demand
        return False
    accepted = [
        round_record
        for round_record in rounds
        if str(round_record.get("status") or "") == "closed"
        and isinstance(round_record.get("metaReview"), Mapping)
        and round_record["metaReview"].get("accepted") is True
    ]
    if not accepted:
        return False
    meeting_ids = {
        str(ref.get("id") or "").strip()
        for ref in list(accepted[-1].get("meetingRefs") or [])
        if isinstance(ref, Mapping)
        and str(ref.get("kind") or "") == "meeting_round"
        and str(ref.get("id") or "").strip()
    }
    if not meeting_ids:
        return False
    try:
        bound_meetings = [
            meeting
            for meeting in meeting_rounds_service.list_meeting_rounds(team_id)["meetings"]
            if isinstance(meeting, Mapping)
            and str(meeting.get("meetingRoundId") or "") in meeting_ids
            and str(meeting.get("status") or "") == "closed"
        ]
        digest_rows = meeting_rounds_service._read_jsonl(
            meeting_rounds_service._digests_path(team_id)
        )
    except Exception:  # noqa: BLE001 - unreadable evidence keeps the demand
        return False
    if not bound_meetings:
        return False
    digests = {
        str(row.get("digestId") or ""): row
        for row in digest_rows
        if isinstance(row, Mapping) and str(row.get("digestId") or "")
    }
    for meeting in bound_meetings:
        digest = digests.get(str(meeting.get("digestId") or ""))
        if not isinstance(digest, Mapping):
            return False
        content_hash = str(digest.get("contentHash") or "").strip().lower()
        if len(content_hash) != 64 or any(
            char not in "0123456789abcdef" for char in content_hash
        ):
            return False
        if not meeting_rounds_service._normalized_str_list(
            digest.get("sourceMessageRefs")
        ):
            return False
    return True


def downgraded_stage_one_receipt_stages(
    required_stages: Sequence[str],
    *,
    team_id: str,
    question_id: str,
    input_snapshot: Mapping[str, Any] | None,
) -> dict[str, str]:
    """Return ``{stage: reason}`` for run-bound receipt demands a chain launch
    structurally cannot meet.

    The stage-one policy demands one run-bound ``ModelInvocationReceipt`` per
    required stage, scope-pinned to the closing run.  Hypothesis-first chain
    launches run their meeting calls before the formal run exists, so no such
    receipt can ever be registered.  For exactly those launches — never a
    question-driven run — the demand is downgraded to conditionally required:
    it stays demanded whenever the accepted round's persisted evidence is
    incomplete, and it is only waived when BOTH the complete review audit rows
    and every bound meeting's hash-anchored approved digest exist.  Any doubt
    keeps the receipt demand — fail-closed.
    """
    team = str(team_id or "").strip()
    question = str(question_id or "").strip().upper()
    stages = [
        str(stage or "").strip().lower()
        for stage in required_stages
        if str(stage or "").strip()
    ]
    if not team or not question or not stages:
        return {}
    if not is_hypothesis_first_launch(input_snapshot):
        return {}
    if not _accepted_round_rows_complete(team, question):
        return {}
    if not _accepted_round_meeting_digest_evidence(team, question):
        return {}
    return {stage: REASON_MEETING_MODEL_EVIDENCE_PERSISTED for stage in stages}


def downgraded_stage_one_kinds(
    required_kinds: Sequence[str],
    *,
    team_id: str,
    question_id: str,
    input_snapshot: Mapping[str, Any] | None,
    source_collection_run_id: str = "",
    workflow_run_id: str = "",
) -> dict[str, str]:
    """Return ``{kind: reason}`` for policy kinds this launch shape cannot demand.

    The downgrade never fires for a question-driven run, never fires for a kind
    whose authority is already readable, and never fires when the underlying
    evidence check is uncertain (the demand stays — fail-closed).  Every
    returned reason names the persisted fact that justifies the waiver.
    """
    team = str(team_id or "").strip()
    question = str(question_id or "").strip().upper()
    kinds = [str(kind or "").strip() for kind in required_kinds if str(kind or "").strip()]
    if not team or not question or not kinds:
        return {}
    if not is_hypothesis_first_launch(input_snapshot):
        return {}

    downgrades: dict[str, str] = {}
    for kind in kinds:
        if kind not in QUESTION_AUTHORITY_PROJECTED_KINDS and kind not in ROUND_ROW_BACKED_KINDS:
            continue
        if _kind_readable(
            kind,
            team_id=team,
            workflow_run_id=workflow_run_id,
            source_collection_run_id=source_collection_run_id,
        ):
            # A readable authority always wins over a downgrade.
            continue
        if kind in QUESTION_AUTHORITY_PROJECTED_KINDS:
            if not _approved_question_authority_present(team, question):
                downgrades[kind] = REASON_QUESTION_AUTHORITY_SOURCE_ABSENT
        elif kind in ROUND_ROW_BACKED_KINDS:
            if _accepted_round_rows_complete(team, question):
                downgrades[kind] = REASON_ROUND_ROWS_PERSISTED_ON_CHAIN_ROUND
    return downgrades


def drop_downgraded_kinds(
    required_kinds: Sequence[str],
    downgrades: Mapping[str, str],
) -> tuple[str, ...]:
    """Keep input order minus downgraded kinds (duplicates collapsed)."""
    return tuple(
        dict.fromkeys(
            kind
            for kind in (str(item or "").strip() for item in required_kinds)
            if kind and kind not in downgrades
        )
    )


__all__ = [
    "QUESTION_AUTHORITY_PROJECTED_KINDS",
    "REASON_MEETING_MODEL_EVIDENCE_PERSISTED",
    "REASON_QUESTION_AUTHORITY_SOURCE_ABSENT",
    "REASON_ROUND_ROWS_PERSISTED_ON_CHAIN_ROUND",
    "ROUND_ROW_BACKED_KINDS",
    "downgraded_stage_one_kinds",
    "downgraded_stage_one_receipt_stages",
    "drop_downgraded_kinds",
    "is_hypothesis_first_launch",
]
