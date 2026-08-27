"""Contract tests for the evolution-lineage artifact.

Covers decision #3 of the 13-decision contract: automatic revision is bounded
at two rounds with ``auto_revision_exhausted`` as a mandatory exception-review
marker, and decision #2 caps finalists at three.  Every lineage invariant is
enforced fail-closed (illegal sequences are rejected at construction, never
silently repaired), ``system_policy`` actors are recorded verbatim without
impersonating a human operator, and the writer is append-only and
replay-idempotent over the artifact store.
"""

from __future__ import annotations

from typing import Any

import pytest

from core.research.workflow.contracts import ContractValidationError
from core.research.workflow.contracts import evolution_lineage as contract
from core.research.workflow.contracts.evolution_lineage import (
    EVOLUTION_LINEAGE_SCHEMA_VERSION,
    EvolutionLineage,
    evolution_lineage_summary,
    mandatory_exception_review_required,
)
from core.web.services.team_workflow.research_runtime import (
    evolution_lineage_writer as writer,
)
from core.web.services.team_workflow.research_runtime import workflow_artifact_store


# ---------------------------------------------------------------------------
# Event fixtures
# ---------------------------------------------------------------------------


def _event(
    event_id: str,
    candidate_id: str,
    kind: str,
    *,
    round_id: str = "round-1",
    reason: str = "deterministic projection",
    occurred_at: str = "2026-08-28T00:00:00Z",
    actor: str = "system_policy",
    revision_attempt: int = 0,
    parent_candidate_id: str = "",
    successor_candidate_id: str = "",
    evidence_refs: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "eventId": event_id,
        "candidateId": candidate_id,
        "kind": kind,
        "roundId": round_id,
        "reason": reason,
        "occurredAt": occurred_at,
        "actor": actor,
        "revisionAttempt": revision_attempt,
        "parentCandidateId": parent_candidate_id,
        "successorCandidateId": successor_candidate_id,
        "evidenceRefs": evidence_refs or [],
    }


def _lineage(events: list[dict[str, Any]], **overrides: Any) -> dict[str, Any]:
    return {
        "schemaVersion": EVOLUTION_LINEAGE_SCHEMA_VERSION,
        "lineageId": "evolution-lineage:q-1:round-1",
        "questionId": "q-1",
        "roundId": "round-1",
        "events": events,
        **overrides,
    }


_SCREENING_REF = [{"kind": "screening_artifact", "ref": "screening:q-1:H1"}]
_FORK_REF = [{"kind": "fork_run", "ref": "run-fork-1"}]


def _happy_path_events() -> list[dict[str, Any]]:
    """Introduced -> revised(1) -> revised(2) -> finalist -> converged."""

    return [
        _event("evt-1", "H1", "introduced"),
        _event(
            "evt-2",
            "H1r1",
            "revised",
            revision_attempt=1,
            parent_candidate_id="H1",
            reason="screening gap: evidenceSupport",
            evidence_refs=_SCREENING_REF,
        ),
        _event(
            "evt-3",
            "H1r2",
            "revised",
            revision_attempt=2,
            parent_candidate_id="H1r1",
            reason="pairwise disagreement on falsifiability",
            evidence_refs=[{"kind": "disagreement_artifact", "ref": "disagreement:round-1"}],
        ),
        _event("evt-4", "H1r2", "advanced"),
        _event("evt-5", "H1r2", "finalist"),
        _event("evt-6", "H1r2", "converged", actor="human_operator"),
    ]


# ---------------------------------------------------------------------------
# Contract: legal sequences
# ---------------------------------------------------------------------------


def test_happy_path_lineage_round_trips() -> None:
    lineage = EvolutionLineage.from_dict(_lineage(_happy_path_events()))
    assert lineage.max_revision_round() == 2
    assert EvolutionLineage.from_dict(lineage.to_dict()) == lineage


def test_summary_reports_kinds_actors_and_exception_marker() -> None:
    lineage = EvolutionLineage.from_dict(_lineage(_happy_path_events()))
    summary = evolution_lineage_summary(lineage)
    assert summary["eventCount"] == 6
    assert summary["kindCounts"] == {
        "advanced": 1,
        "converged": 1,
        "finalist": 1,
        "introduced": 1,
        "revised": 2,
    }
    assert summary["actorCounts"] == {"human_operator": 1, "system_policy": 5}
    assert summary["systemPolicyEventCount"] == 5
    assert summary["revisionRoundCount"] == 2
    assert summary["finalistCandidateIds"] == ["H1r2"]
    assert summary["mandatoryExceptionReview"] == ""
    assert mandatory_exception_review_required(lineage) is False


def test_revision_exhausted_marks_mandatory_exception_review() -> None:
    events = [
        _event("evt-1", "H1", "introduced"),
        _event(
            "evt-2",
            "H1r1",
            "revised",
            revision_attempt=1,
            parent_candidate_id="H1",
            evidence_refs=_FORK_REF,
        ),
        _event(
            "evt-3",
            "H1",
            "revision_exhausted",
            reason="revision budget reached without closing the gap",
        ),
    ]
    lineage = EvolutionLineage.from_dict(_lineage(events))
    assert mandatory_exception_review_required(lineage) is True
    summary = evolution_lineage_summary(lineage)
    assert summary["mandatoryExceptionReview"] == "auto_revision_exhausted"
    assert contract.REVISION_EXHAUSTED_EXCEPTION == "auto_revision_exhausted"


def test_merge_families_can_share_one_lineage() -> None:
    events = [
        _event("evt-1", "H1", "introduced"),
        _event("evt-2", "H2", "introduced"),
        _event("evt-3", "H1", "advanced"),
        _event("evt-4", "H2", "finalist"),
        _event(
            "evt-5",
            "H1",
            "superseded",
            successor_candidate_id="H2",
            reason="merged into the stronger mechanism",
        ),
        _event("evt-6", "H2", "converged"),
    ]
    lineage = EvolutionLineage.from_dict(_lineage(events))
    assert evolution_lineage_summary(lineage)["finalistCandidateIds"] == ["H2"]


def test_three_finalists_are_allowed() -> None:
    events: list[dict[str, Any]] = [
        _event("evt-1", "H1", "introduced"),
        _event("evt-2", "H2", "introduced"),
        _event("evt-3", "H3", "introduced"),
        _event("evt-4", "H1", "finalist"),
        _event("evt-5", "H2", "finalist"),
        _event("evt-6", "H3", "finalist"),
    ]
    lineage = EvolutionLineage.from_dict(_lineage(events))
    assert lineage.events[0].kind == "introduced"


# ---------------------------------------------------------------------------
# Contract: invariant violations (table driven, fail-closed)
# ---------------------------------------------------------------------------


def _revised(
    event_id: str,
    candidate_id: str,
    attempt: int,
    parent: str,
    **overrides: Any,
) -> dict[str, Any]:
    return _event(
        event_id,
        candidate_id,
        "revised",
        revision_attempt=attempt,
        parent_candidate_id=parent,
        evidence_refs=_FORK_REF,
        **overrides,
    )


_VIOLATIONS: list[dict[str, Any]] = [
    {
        "name": "first_event_not_introduced",
        "events": [_event("evt-1", "H1", "advanced")],
        "match": "must open with an introduced event",
    },
    {
        "name": "introduced_after_other_event_for_same_candidate",
        "events": [
            _event("evt-1", "H1", "introduced"),
            _event("evt-2", "H1", "advanced"),
            _event("evt-3", "H1", "introduced"),
        ],
        "match": "introduced must precede",
    },
    {
        "name": "duplicate_event_id",
        "events": [
            _event("evt-1", "H1", "introduced"),
            _event("evt-1", "H1", "advanced"),
        ],
        "match": "event ids must be unique",
    },
    {
        "name": "revision_attempt_skips_parent_chain",
        "events": [
            _event("evt-1", "H1", "introduced"),
            _revised("evt-2", "H1r2", 2, "H1"),
        ],
        "match": "monotonic",
    },
    {
        "name": "revised_with_duplicate_evidence_refs",
        "events": [
            _event("evt-1", "H1", "introduced"),
            _event(
                "evt-2",
                "H1r1",
                "revised",
                revision_attempt=1,
                parent_candidate_id="H1",
                evidence_refs=[
                    {"kind": "fork_run", "ref": "run-fork-1"},
                    {"kind": "fork_run", "ref": "run-fork-1"},
                ],
            ),
        ],
        "match": "evidence references must be distinct",
    },
    {
        "name": "revision_over_ceiling",
        "events": [
            _event("evt-1", "H1", "introduced"),
            _revised("evt-2", "H1r1", 1, "H1"),
            _revised("evt-3", "H1r2", 2, "H1r1"),
            _revised("evt-4", "H1r3", 3, "H1r2"),
        ],
        "match": "bounded at 2 rounds",
    },
    {
        "name": "revision_parent_unknown",
        "events": [
            _event("evt-1", "H1", "introduced"),
            _revised("evt-2", "H1r1", 1, "H9"),
        ],
        "match": "unknown or future parent",
    },
    {
        "name": "revised_after_revision_exhausted",
        "events": [
            _event("evt-1", "H1", "introduced"),
            _revised("evt-2", "H1r1", 1, "H1"),
            _event("evt-3", "H1", "revision_exhausted"),
            _revised("evt-4", "H1r2", 2, "H1r1"),
        ],
        "match": "revision_exhausted",
    },
    {
        "name": "four_finalists",
        "events": [
            _event("evt-1", "H1", "introduced"),
            _event("evt-2", "H2", "introduced"),
            _event("evt-3", "H3", "introduced"),
            _event("evt-4", "H4", "introduced"),
            _event("evt-5", "H1", "finalist"),
            _event("evt-6", "H2", "finalist"),
            _event("evt-7", "H3", "finalist"),
            _event("evt-8", "H4", "finalist"),
        ],
        "match": "at most 3 candidates may reach finalist",
    },
    {
        "name": "superseded_unknown_successor",
        "events": [
            _event("evt-1", "H1", "introduced"),
            _event("evt-2", "H1", "superseded", successor_candidate_id="H9"),
        ],
        "match": "successor inside the same lineage",
    },
    {
        "name": "revised_without_parent",
        "events": [
            _event("evt-1", "H1", "introduced"),
            _revised("evt-2", "H1r1", 1, ""),
        ],
        "match": "requires parentCandidateId",
    },
    {
        "name": "revised_without_evidence",
        "events": [
            _event("evt-1", "H1", "introduced"),
            _event(
                "evt-2",
                "H1r1",
                "revised",
                revision_attempt=1,
                parent_candidate_id="H1",
            ),
        ],
        "match": "at least one evidence reference",
    },
    {
        "name": "revised_targeting_own_parent",
        "events": [
            _event("evt-1", "H1", "introduced"),
            _revised("evt-2", "H1", 1, "H1"),
        ],
        "match": "cannot target its own parent",
    },
    {
        "name": "screened_out_without_screening_evidence",
        "events": [
            _event("evt-1", "H1", "introduced"),
            _event("evt-2", "H1", "screened_out", evidence_refs=_FORK_REF),
        ],
        "match": "screening artifact evidence",
    },
    {
        "name": "superseded_without_successor",
        "events": [
            _event("evt-1", "H1", "introduced"),
            _event("evt-2", "H1", "superseded"),
        ],
        "match": "requires successorCandidateId",
    },
    {
        "name": "non_revised_event_carries_attempt",
        "events": [
            _event("evt-1", "H1", "introduced"),
            _event("evt-2", "H1", "advanced", revision_attempt=1),
        ],
        "match": "must not carry a revisionAttempt",
    },
    {
        "name": "empty_lineage",
        "payload": _lineage([]),
        "match": "non-empty list",
    },
    {
        "name": "unsupported_actor",
        "events": [
            _event("evt-1", "H1", "introduced", actor="auto_executor"),
        ],
        "match": "actor must be one of",
    },
    {
        "name": "unsupported_kind",
        "events": [
            _event("evt-1", "H1", "promoted"),
        ],
        "match": "kind must be one of",
    },
]


# The violation table above is fully specified inline; no post-hoc patching.


@pytest.mark.parametrize("case", _VIOLATIONS, ids=lambda case: case["name"])
def test_invalid_lineages_are_rejected(case: dict[str, Any]) -> None:
    payload = case.get("payload") or _lineage(list(case["events"]))
    with pytest.raises(ContractValidationError, match=case["match"]):
        EvolutionLineage.from_dict(payload)


def test_contract_ceiling_binds_the_frozen_decisions() -> None:
    assert contract.MAX_REVISION_ROUNDS == 2
    assert contract.FINALIST_LIMIT == 3
    assert contract.EVOLUTION_LINEAGE_EVENT_KINDS == frozenset(
        {
            "introduced",
            "screened_out",
            "revised",
            "revision_exhausted",
            "advanced",
            "finalist",
            "superseded",
            "converged",
        }
    )


# ---------------------------------------------------------------------------
# Contract: system_policy actors are recorded, never impersonated
# ---------------------------------------------------------------------------


def test_system_policy_events_are_recorded_verbatim() -> None:
    events = [
        _event("evt-1", "H1", "introduced", actor="system_policy"),
        _event("evt-2", "H1", "finalist", actor="system_policy"),
    ]
    lineage = EvolutionLineage.from_dict(_lineage(events))
    replayed = EvolutionLineage.from_dict(lineage.to_dict())
    assert [event.actor for event in replayed.events] == [
        "system_policy",
        "system_policy",
    ]
    summary = evolution_lineage_summary(replayed)
    assert summary["actorCounts"] == {"system_policy": 2}
    assert summary["systemPolicyEventCount"] == 2
    # A system-policy finalist is still counted as a system event — the
    # artifact exposes no field that could present it as a human decision.
    assert "human_operator" not in summary["actorCounts"]


def test_human_operator_events_keep_their_actor() -> None:
    events = [
        _event("evt-1", "H1", "introduced", actor="human_operator"),
        _event("evt-2", "H1", "advanced", actor="executor"),
    ]
    summary = evolution_lineage_summary(
        EvolutionLineage.from_dict(_lineage(events))
    )
    assert summary["actorCounts"] == {"executor": 1, "human_operator": 1}
    assert summary["systemPolicyEventCount"] == 0


# ---------------------------------------------------------------------------
# Writer: append-only projection with idempotent replay
# ---------------------------------------------------------------------------


def _fake_store(monkeypatch) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def fake_put(team_id: str, **kwargs):
        identity = kwargs["artifact_identity"]
        for existing in rows:
            if existing["recordId"] == identity:
                assert existing["contentHash"] == writer.canonical_sha256(
                    kwargs["payload"]
                )
                return existing
        record = {
            "recordId": identity,
            "teamId": team_id,
            "kind": kwargs["kind"],
            "workflowRunId": kwargs["workflow_run_id"],
            "sourceCollectionRunId": kwargs["source_collection_run_id"],
            "contentHash": writer.canonical_sha256(kwargs["payload"]),
            "payload": kwargs["payload"],
        }
        rows.append(record)
        return record

    def fake_list(team_id: str, *, kind: str, workflow_run_id: str = "", **_):
        return [
            dict(row)
            for row in rows
            if row["kind"] == kind
            and (not workflow_run_id or row["workflowRunId"] == workflow_run_id)
        ]

    monkeypatch.setattr(writer, "put_workflow_artifact", fake_put)
    monkeypatch.setattr(writer, "list_workflow_artifacts", fake_list)
    return rows


def _forbidden_store(monkeypatch) -> None:
    def unexpected(*args, **kwargs):
        raise AssertionError("blocked projection must not touch the artifact store")

    monkeypatch.setattr(writer, "put_workflow_artifact", unexpected)
    monkeypatch.setattr(writer, "list_workflow_artifacts", unexpected)


def _write(events: list[dict[str, Any]], **overrides: Any) -> dict[str, Any]:
    return writer.write_evolution_lineage_artifact(
        team_id="team-1",
        workflow_run_id="wf-1",
        node_run_id="node-1",
        question_id="q-1",
        round_id="round-1",
        events=events,
        **overrides,
    )


def test_store_kind_is_registered() -> None:
    assert "evolution_lineage" in workflow_artifact_store._SUPPORTED_KINDS


def test_writer_projects_and_stores_validated_lineage(monkeypatch) -> None:
    rows = _fake_store(monkeypatch)
    result = _write(_happy_path_events())

    assert result["status"] == "written"
    lineage_result = result["evolutionLineage"]
    assert lineage_result["eventCount"] == 6
    assert lineage_result["appendedEventCount"] == 6
    assert lineage_result["revisionRoundCount"] == 2
    assert lineage_result["mandatoryExceptionReview"] is False
    assert lineage_result["summary"]["finalistCandidateIds"] == ["H1r2"]
    payload = rows[0]["payload"]
    assert payload["schemaVersion"] == EVOLUTION_LINEAGE_SCHEMA_VERSION
    assert payload["artifactKind"] == "evolution_lineage"
    assert payload["lineageId"] == "evolution-lineage:q-1:round-1"
    assert payload["inputHash"] == writer.compute_lineage_input_hash(
        team_id="team-1",
        workflow_run_id="wf-1",
        node_run_id="node-1",
        question_id="q-1",
        round_id="round-1",
        events=payload["events"],
    )
    canonical = lineage_result["artifact"]
    assert canonical["canonicalRef"].startswith("evolution_lineage://team-1/wf-1/")


def test_writer_replay_is_idempotent(monkeypatch) -> None:
    rows = _fake_store(monkeypatch)
    first = _write(_happy_path_events())
    replay = _write(_happy_path_events())

    assert first["status"] == "written"
    assert replay["status"] == "written"
    assert replay["evolutionLineage"]["appendedEventCount"] == 0
    assert replay["evolutionLineage"]["artifact"]["canonicalHash"] == (
        first["evolutionLineage"]["artifact"]["canonicalHash"]
    )
    assert len(rows) == 1


def test_writer_appends_onto_stored_lineage(monkeypatch) -> None:
    rows = _fake_store(monkeypatch)
    first_batch = _happy_path_events()[:3]
    second_batch = _happy_path_events()[3:]

    first = _write(first_batch)
    second = _write(second_batch)

    assert first["status"] == "written"
    assert second["status"] == "written"
    assert second["evolutionLineage"]["appendedEventCount"] == 3
    assert second["evolutionLineage"]["eventCount"] == 6
    assert len(rows) == 2
    latest_events = rows[-1]["payload"]["events"]
    assert [event["eventId"] for event in latest_events] == [
        event["eventId"] for event in _happy_path_events()
    ]


def test_writer_blocks_conflicting_replay_of_same_event_id(monkeypatch) -> None:
    rows = _fake_store(monkeypatch)
    first = _write(_happy_path_events()[:3])
    conflicting = _happy_path_events()[:3]
    conflicting[0]["reason"] = "rewritten history"

    result = _write(conflicting)

    assert first["status"] == "written"
    assert result["status"] == "blocked"
    assert "evolution_lineage_event_conflict" in result["blockerCodes"]
    assert len(rows) == 1


def test_writer_blocks_invalid_sequence_without_store_write(monkeypatch) -> None:
    rows = _fake_store(monkeypatch)

    result = _write(
        [
            _event("evt-1", "H1", "introduced"),
            _revised("evt-2", "H1r1", 1, "H1"),
            _revised("evt-3", "H1r2", 2, "H1r1"),
            _revised("evt-4", "H1r3", 3, "H1r2"),
        ]
    )

    assert result["status"] == "blocked"
    assert "evolution_lineage_invalid" in result["blockerCodes"]
    assert result["evolutionLineage"] is None
    assert rows == []


def test_writer_blocks_empty_batch_without_store_access(monkeypatch) -> None:
    _forbidden_store(monkeypatch)
    result = _write([])

    assert result["status"] == "blocked"
    assert "evolution_lineage_events_missing" in result["blockerCodes"]
    assert result["evolutionLineage"] is None


def test_writer_blocks_incomplete_binding_without_store_access(monkeypatch) -> None:
    _forbidden_store(monkeypatch)
    result = writer.write_evolution_lineage_artifact(
        team_id="team-1",
        workflow_run_id="wf-1",
        question_id="q-1",
        round_id="",
        events=_happy_path_events()[:1],
    )

    assert result["status"] == "blocked"
    assert "roundId_missing" in result["blockerCodes"]
