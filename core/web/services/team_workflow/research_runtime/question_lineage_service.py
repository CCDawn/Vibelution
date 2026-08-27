"""Single-question full-chain lineage projection (read-only).

R4.5: aggregate the whole per-question evolution chain — candidate evolution
events, per-candidate review-disagreement summaries, per-candidate claim
belief states, and the claim→evidence reference graph — into one browsable
projection behind the question lineage panel.

Sources (all read-only consumers of already-written canonical artifacts):

- ``evolution_lineage`` workflow artifacts (per questionId/roundId event
  stream, written by :mod:`.evolution_lineage_writer`);
- ``review_disagreement`` workflow artifacts (candidate pair disagreement
  projections, written by :mod:`.review_independence_artifact_writer`);
- the team claim ledger (question-scoped claims with evidence refs) and the
  claim-evidence store (the claimEvidenceId → candidateId bridge);
- :func:`.claim_belief_service.evaluate_claim_belief` for the five-state
  belief table over the scoped claims.

This module never writes and never re-runs a review, screening, or revision.
Degradation is per segment: a segment whose sources are absent or unreadable
becomes ``{"status": "missing", "missingReason": ...}`` so the panel can show
the remaining chain with an honest gap label instead of failing the whole
projection.  Every list is bounded; the projection is display-shaped data,
never a decision.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from core.research.workflow.contracts import ContractValidationError
from core.research.workflow.contracts.claim_ledger import ClaimLedgerEntry
from core.research.workflow.contracts.evolution_lineage import (
    EvolutionLineage,
    evolution_lineage_summary,
)

from .claim_belief_service import evaluate_claim_belief
from .workflow_artifact_store import list_workflow_artifacts

SCHEMA_VERSION = 1

EVOLUTION_SEGMENT = "evolution"
DISAGREEMENT_SEGMENT = "reviewDisagreement"
BELIEF_SEGMENT = "claimBelief"
EVIDENCE_GRAPH_SEGMENT = "evidenceGraph"
SEGMENT_NAMES = (
    EVOLUTION_SEGMENT,
    DISAGREEMENT_SEGMENT,
    BELIEF_SEGMENT,
    EVIDENCE_GRAPH_SEGMENT,
)

_LINEAGE_ARTIFACT_KIND = "evolution_lineage"
_DISAGREEMENT_ARTIFACT_KIND = "review_disagreement"

# Display bounds: the panel is a bounded read view, not an export.
_MAX_LINEAGE_ARTIFACTS = 20
_MAX_DISAGREEMENT_ARTIFACTS = 50
_MAX_DISAGREEMENT_PAIRS_PER_CANDIDATE = 20
_MAX_CLAIMS = 500
_MAX_CLAIM_TEXT = 240
_MAX_EVIDENCE_RECORDS = 2000
_MAX_EDGES_PER_CLAIM = 40

_READY = "ready"
_MISSING = "missing"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[str] = []
    for item in value:
        text = _text(item)
        if text and text not in result:
            result.append(text)
    return result


def _missing(reason: str) -> dict[str, Any]:
    return {"status": _MISSING, "missingReason": reason}


def _plain_counts(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Fallback summary when the stored payload fails contract re-validation."""
    kind_counts: Counter[str] = Counter()
    actor_counts: Counter[str] = Counter()
    for event in events:
        kind_counts[_text(event.get("kind"))] += 1
        actor_counts[_text(event.get("actor"))] += 1
    return {
        "eventCount": len(events),
        "kindCounts": dict(sorted(kind_counts.items())),
        "actorCounts": dict(sorted(actor_counts.items())),
        "systemPolicyEventCount": actor_counts.get("system_policy", 0),
        "summaryDegraded": True,
    }


def _evolution_segment(
    rows: Sequence[Mapping[str, Any]], question: str, scope_round: str
) -> dict[str, Any]:
    matched: list[tuple[Mapping[str, Any], dict[str, Any]]] = []
    for row in rows:
        payload = _mapping(row.get("payload"))
        if _text(payload.get("questionId")) != question:
            continue
        if scope_round and _text(payload.get("roundId")) != scope_round:
            continue
        events = [
            _mapping(item) for item in (payload.get("events") or [])
        ] if isinstance(payload.get("events"), list) else []
        if not events:
            continue
        matched.append((row, payload))
    if not matched:
        return _missing("evolution_lineage_artifact_missing")
    lineages: list[dict[str, Any]] = []
    for row, payload in matched[-_MAX_LINEAGE_ARTIFACTS:]:
        events = [_mapping(item) for item in payload.get("events") or []]
        summary: dict[str, Any]
        try:
            summary = evolution_lineage_summary(EvolutionLineage.from_dict(payload))
        except ContractValidationError:
            summary = _plain_counts(events)
        lineages.append(
            {
                "lineageId": _text(payload.get("lineageId")),
                "roundId": _text(payload.get("roundId")),
                "recordId": _text(row.get("recordId")),
                "eventCount": len(events),
                "events": events,
                "summary": summary,
            }
        )
    return {
        "status": _READY,
        "lineageCount": len(lineages),
        "lineages": lineages,
    }


def _disagreement_segment(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    scoped = list(rows)[-_MAX_DISAGREEMENT_ARTIFACTS:]
    if not scoped:
        return _missing("review_disagreement_artifact_missing")
    candidates: dict[str, dict[str, Any]] = {}
    for row in scoped:
        payload = _mapping(row.get("payload"))
        artifact_ref = _text(row.get("recordId")) or _text(payload.get("inputHash"))
        escalation = _mapping(payload.get("escalation"))
        pairs = [
            _mapping(item)
            for item in payload.get("candidatePairs") or []
            if isinstance(item, Mapping)
        ]
        for pair in pairs:
            for side in ("leftCandidateId", "rightCandidateId"):
                candidate_id = _text(pair.get(side))
                if not candidate_id:
                    continue
                entry = candidates.setdefault(
                    candidate_id,
                    {
                        "pairCount": 0,
                        "pairs": [],
                        "disagreementAxes": [],
                        "escalationRequired": False,
                    },
                )
                entry["pairCount"] += 1
                if len(entry["pairs"]) < _MAX_DISAGREEMENT_PAIRS_PER_CANDIDATE:
                    opposed_key = (
                        "rightCandidateId" if side == "leftCandidateId" else "leftCandidateId"
                    )
                    entry["pairs"].append(
                        {
                            "comparisonId": _text(pair.get("comparisonId")),
                            "opposedCandidateId": _text(pair.get(opposed_key)),
                            "outcome": _text(pair.get("outcome")),
                            "inconsistentAxes": _string_list(pair.get("inconsistentAxes")),
                            "artifactRef": artifact_ref,
                        }
                    )
                for axis in _string_list(pair.get("inconsistentAxes")):
                    if axis not in entry["disagreementAxes"]:
                        entry["disagreementAxes"].append(axis)
                if bool(escalation.get("required")):
                    entry["escalationRequired"] = True
    if not candidates:
        return _missing("review_disagreement_artifact_missing")
    return {
        "status": _READY,
        "artifactCount": len(scoped),
        "candidates": dict(sorted(candidates.items())),
    }


def _question_claim_rows(team: str, question: str) -> list[Mapping[str, Any]]:
    """Latest-per-claim ledger rows scoped to one question (read-only)."""
    from core.web.services.team_workflow import claim_ledger as claim_ledger_service

    listing = claim_ledger_service.list_claims(team)
    rows = [
        _mapping(item)
        for item in listing.get("claims") or []
        if isinstance(item, Mapping) and _text(item.get("question")) == question
    ]
    return rows[-_MAX_CLAIMS:]


def _evidence_index(team: str) -> tuple[dict[str, dict[str, Any]], bool]:
    """claimEvidenceId → record for the team (bounded), plus a healthy flag."""
    from core.infrastructure.path_containment import PROJECT_ROOT
    from core.research.evidence import ClaimEvidenceStore

    try:
        records = ClaimEvidenceStore(PROJECT_ROOT).list(team)
    except Exception:
        return {}, False
    index: dict[str, dict[str, Any]] = {}
    for record in records[:_MAX_EVIDENCE_RECORDS]:
        if isinstance(record, Mapping):
            evidence_id = _text(record.get("claimEvidenceId"))
            if evidence_id:
                index[evidence_id] = dict(record)
    return index, True


def _candidate_ids_for_claim(
    row: Mapping[str, Any], evidence_index: Mapping[str, Mapping[str, Any]]
) -> list[str]:
    ids: list[str] = []
    refs = row.get("evidenceRefs")
    if not isinstance(refs, (list, tuple)):
        return ids
    for ref in refs:
        if not isinstance(ref, Mapping):
            continue
        record = evidence_index.get(_text(ref.get("claimEvidenceId")))
        candidate_id = _text(record.get("candidateId")) if record else ""
        if candidate_id and candidate_id not in ids:
            ids.append(candidate_id)
    return ids


def _belief_and_graph_segments(
    entries: list[ClaimLedgerEntry],
    rows: Sequence[Mapping[str, Any]],
    evidence_index: Mapping[str, Mapping[str, Any]],
    evidence_store_healthy: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not entries:
        return _missing("claim_ledger_empty_for_question"), _missing(
            "claim_ledger_empty_for_question"
        )

    try:
        table = evaluate_claim_belief(entries, list(evidence_index.values()))
    except Exception:
        reason = "claim_belief_evaluation_failed"
        return _missing(reason), _missing(reason)

    belief_by_claim = {entry.claimId: entry for entry in table.entries}
    claim_rows: list[dict[str, Any]] = []
    candidate_claims: dict[str, dict[str, Any]] = {}
    graph_nodes: list[dict[str, Any]] = []
    graph_edges: list[dict[str, Any]] = []
    seen_nodes: set[str] = set()

    def add_node(node: dict[str, Any], node_id: str) -> None:
        if node_id in seen_nodes:
            return
        seen_nodes.add(node_id)
        graph_nodes.append(node)

    for row in rows:
        claim_id = _text(row.get("claimId"))
        belief = belief_by_claim.get(claim_id)
        candidate_ids = _candidate_ids_for_claim(row, evidence_index)
        add_node(
            {
                "id": f"claim:{claim_id}",
                "type": "claim",
                "label": _text(row.get("claim"))[:_MAX_CLAIM_TEXT],
                "status": _text(row.get("status")),
            },
            f"claim:{claim_id}",
        )
        if belief is not None:
            claim_rows.append(
                {
                    "claimId": claim_id,
                    "claimText": _text(row.get("claim"))[:_MAX_CLAIM_TEXT],
                    "status": _text(row.get("status")),
                    "source": _text(row.get("source")),
                    "beliefState": belief.beliefState,
                    "acceptedSupportCount": belief.acceptedSupportCount,
                    "acceptedCounterCount": belief.acceptedCounterCount,
                    "pendingSupportCount": belief.pendingSupportCount,
                    "pendingCounterCount": belief.pendingCounterCount,
                    "neutralCount": belief.neutralCount,
                    "supportingEvidenceIds": list(belief.supportingEvidenceIds),
                    "counterEvidenceIds": list(belief.counterEvidenceIds),
                    "lastEvaluatedAt": belief.lastEvaluatedAt,
                    "candidateIds": candidate_ids,
                }
            )
        refs = [
            ref
            for ref in (row.get("evidenceRefs") or [])
            if isinstance(ref, Mapping)
        ]
        for ref in refs[:_MAX_EDGES_PER_CLAIM]:
            evidence_id = _text(ref.get("claimEvidenceId"))
            if not evidence_id:
                continue
            record = evidence_index.get(evidence_id) or {}
            record_candidate = _text(record.get("candidateId"))
            add_node(
                {
                    "id": f"evidence:{evidence_id}",
                    "type": "evidence",
                    "sourceId": _text(record.get("sourceId")),
                    "reviewStatus": _text(ref.get("reviewStatus")),
                    "supportLevel": _text(ref.get("supportLevel")),
                    "candidateIds": [record_candidate] if record_candidate else [],
                },
                f"evidence:{evidence_id}",
            )
            graph_edges.append(
                {
                    "source": f"claim:{claim_id}",
                    "target": f"evidence:{evidence_id}",
                    "kind": _text(ref.get("supportLevel")) or "unverified",
                    "reviewStatus": _text(ref.get("reviewStatus")),
                    "accepted": _text(ref.get("reviewStatus")) == "accepted",
                }
            )

        for candidate_id in candidate_ids:
            entry = candidate_claims.setdefault(
                candidate_id, {"claimIds": [], "beliefStates": {}}
            )
            if claim_id not in entry["claimIds"]:
                entry["claimIds"].append(claim_id)
            if belief is not None:
                states: dict[str, int] = entry["beliefStates"]
                states[belief.beliefState] = states.get(belief.beliefState, 0) + 1

    belief_segment = {
        "status": _READY,
        "claimCount": len(claim_rows),
        "invalidClaimCount": len(rows) - len(claim_rows),
        "evidenceStoreAvailable": evidence_store_healthy,
        "beliefTableHash": table.beliefTableHash,
        "claims": claim_rows,
        "candidates": dict(sorted(candidate_claims.items())),
    }
    graph_segment = {
        "status": _READY,
        "nodeCount": len(graph_nodes),
        "edgeCount": len(graph_edges),
        "nodes": graph_nodes,
        "edges": graph_edges,
    }
    return belief_segment, graph_segment


def project_question_lineage(
    *,
    team_id: Any,
    question_id: Any,
    workflow_run_id: Any = "",
    round_id: Any = "",
) -> dict[str, Any]:
    """Project one question's full claim→evidence→candidate→review→revision chain.

    Pure read: missing or unreadable sources degrade their own segment
    (``status: "missing"`` with a ``missingReason`` code) and are reported in
    ``degradedSegments`` — the projection itself never fails closed.
    """

    team = _text(team_id)
    question = _text(question_id)
    run = _text(workflow_run_id)
    scope_round = _text(round_id)
    if not team or not question:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "teamId": team,
            "questionId": question,
            "workflowRunId": run,
            "roundId": scope_round,
            "boundaries": {"readOnly": True},
            "degradedSegments": list(SEGMENT_NAMES),
            "segments": {
                name: _missing("team_or_question_id_missing")
                for name in SEGMENT_NAMES
            },
        }

    segments: dict[str, dict[str, Any]] = {}

    # --- evolution lineage -------------------------------------------------
    try:
        lineage_rows = list_workflow_artifacts(
            team,
            kind=_LINEAGE_ARTIFACT_KIND,
            workflow_run_id=run,
        )
        segments[EVOLUTION_SEGMENT] = _evolution_segment(
            lineage_rows, question, scope_round
        )
    except Exception:
        segments[EVOLUTION_SEGMENT] = _missing("evolution_lineage_projection_failed")

    # --- review disagreement -----------------------------------------------
    try:
        disagreement_rows = list_workflow_artifacts(
            team,
            kind=_DISAGREEMENT_ARTIFACT_KIND,
            workflow_run_id=run,
        )
        segments[DISAGREEMENT_SEGMENT] = _disagreement_segment(disagreement_rows)
    except Exception:
        segments[DISAGREEMENT_SEGMENT] = _missing(
            "review_disagreement_projection_failed"
        )

    # --- claim belief + evidence graph --------------------------------------
    entries: list[ClaimLedgerEntry] = []
    rows: list[Mapping[str, Any]] = []
    claims_missing: str | None = None
    try:
        rows = _question_claim_rows(team, question)
        if not rows:
            claims_missing = "claim_ledger_empty_for_question"
    except Exception:
        claims_missing = "claim_ledger_unavailable"
    if claims_missing is not None:
        segments[BELIEF_SEGMENT] = _missing(claims_missing)
        segments[EVIDENCE_GRAPH_SEGMENT] = _missing(claims_missing)
    else:
        for row in rows:
            try:
                entries.append(ClaimLedgerEntry.from_dict(dict(row)))
            except ContractValidationError:
                continue
        evidence_index, healthy = _evidence_index(team)
        (
            segments[BELIEF_SEGMENT],
            segments[EVIDENCE_GRAPH_SEGMENT],
        ) = _belief_and_graph_segments(entries, rows, evidence_index, healthy)

    degraded = [
        name
        for name in SEGMENT_NAMES
        if segments.get(name, {}).get("status") != _READY
    ]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "teamId": team,
        "questionId": question,
        "workflowRunId": run,
        "roundId": scope_round,
        "boundaries": {"readOnly": True},
        "degradedSegments": degraded,
        "segments": segments,
    }


__all__ = [
    "BELIEF_SEGMENT",
    "DISAGREEMENT_SEGMENT",
    "EVOLUTION_SEGMENT",
    "EVIDENCE_GRAPH_SEGMENT",
    "SCHEMA_VERSION",
    "SEGMENT_NAMES",
    "project_question_lineage",
]
