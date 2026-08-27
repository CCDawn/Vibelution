"""R4.5 single-question lineage projection: aggregation, degradation, route.

Covers the full chain projection (evolution events + per-candidate review
disagreement + per-candidate claim belief + claim→evidence reference graph),
the per-segment degradation contract (a missing segment never fails the whole
projection), the optional run/round scoping, and the thin GET route wiring.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from core.research.workflow.contracts import ContractValidationError, scope_hash_for
from core.web.routes.team_workflows import research_runtime as research_runtime_routes
from core.web.services.team_workflow.research_runtime import (
    question_lineage_service,
)
from core.web.services.team_workflow.research_runtime.question_lineage_service import (
    SEGMENT_NAMES,
    project_question_lineage,
)

_TEAM = "team-1"
_QUESTION = "SCI-091"
_SCOPE_FIELDS = {
    "program": "XH-202619",
    "theme": "cc-gpu-operator-001",
    "campaign": "cc-campaign-gpu-operator-001",
    "question": _QUESTION,
    "branch": "main",
    "workflow": "hypothesis_and_plan",
}


def _scope_hash() -> str:
    return scope_hash_for(**_SCOPE_FIELDS, agent_id="agent-evaluator", mode="formal")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _lineage_event(
    event_id: str,
    candidate_id: str,
    kind: str,
    *,
    revision_attempt: int = 0,
    parent_candidate_id: str = "",
    evidence_refs: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "eventId": event_id,
        "candidateId": candidate_id,
        "kind": kind,
        "roundId": "round-1",
        "reason": "deterministic projection",
        "occurredAt": "2026-08-28T00:00:00Z",
        "actor": "system_policy",
        "revisionAttempt": revision_attempt,
        "parentCandidateId": parent_candidate_id,
        "successorCandidateId": "",
        "evidenceRefs": evidence_refs or [],
    }


def _lineage_payload(
    events: list[dict[str, Any]], *, round_id: str = "round-1"
) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "artifactKind": "evolution_lineage",
        "lineageId": f"evolution-lineage:{_QUESTION}:{round_id}",
        "teamId": _TEAM,
        "workflowRunId": "wf-1",
        "nodeRunId": "node-1",
        "questionId": _QUESTION,
        "roundId": round_id,
        "events": events,
    }


def _lineage_row(
    payload: dict[str, Any],
    record_id: str = "rec-lineage-1",
    *,
    workflow_run_id: str = "wf-1",
) -> dict[str, Any]:
    return {
        "recordId": record_id,
        "teamId": _TEAM,
        "kind": "evolution_lineage",
        "workflowRunId": workflow_run_id,
        "payload": payload,
    }


def _disagreement_row(
    record_id: str,
    pairs: list[dict[str, Any]],
    *,
    escalation_required: bool = True,
) -> dict[str, Any]:
    axes = sorted({axis for pair in pairs for axis in pair["inconsistentAxes"]})
    return {
        "recordId": record_id,
        "teamId": _TEAM,
        "kind": "review_disagreement",
        "workflowRunId": "wf-1",
        "payload": {
            "schemaVersion": 1,
            "artifactKind": "review_disagreement",
            "teamId": _TEAM,
            "workflowRunId": "wf-1",
            "reviewRoundId": "round-1",
            "reviewContextId": "ctx-1",
            "candidatePairs": pairs,
            "reviewerScoreRefs": [],
            "disagreementAxes": axes,
            "disagreementMetrics": [
                {"axis": axis, "directionInconsistencyCount": 1} for axis in axes
            ],
            "escalation": {
                "required": escalation_required,
                "reason": "direction conflict" if axes else "",
                "status": "flagged_only",
            },
        },
    }


def _pair(
    comparison_id: str,
    left: str,
    right: str,
    axes: list[str],
    outcome: str = "left_wins",
) -> dict[str, Any]:
    return {
        "comparisonId": comparison_id,
        "leftCandidateId": left,
        "rightCandidateId": right,
        "outcome": outcome,
        "inconsistentAxes": axes,
    }


def _claim_row(
    claim_id: str,
    refs: list[dict[str, Any]],
    *,
    status: str = "proposed",
    question: str = _QUESTION,
) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "claimId": claim_id,
        "claim": f"Claim {claim_id} statement.",
        **_SCOPE_FIELDS,
        "question": question,
        "agentId": "agent-evaluator",
        "mode": "formal",
        "scopeHash": _scope_hash(),
        "status": status,
        "source": "agent",
        "evidenceRefs": refs,
        "counterEvidenceRefs": [],
        "supersedesClaimId": "",
        "retractsClaimId": "",
        "meetingPromotionAllowed": False,
        "createdBy": "agent-evaluator",
        "createdAt": "2026-08-28T00:00:00Z",
    }


def _ref(
    evidence_id: str,
    *,
    review: str = "accepted",
    support: str = "supports",
) -> dict[str, Any]:
    return {
        "claimEvidenceId": evidence_id,
        "scopeHash": _scope_hash(),
        "reviewStatus": review,
        "supportLevel": support,
        "sourceId": f"artifact:{evidence_id}",
    }


class _FakeEvidenceStore:
    """Stands in for ClaimEvidenceStore; injects canned team records."""

    records_by_team: dict[str, list[dict[str, Any]]] = {}
    raise_on_list = False

    def __init__(self, project_root: Any) -> None:
        self.project_root = project_root

    def list(self, team_id: str, **_: Any) -> list[dict[str, Any]]:
        if self.raise_on_list:
            raise OSError("claim evidence store unavailable")
        return list(self.records_by_team.get(team_id, []))


def _evidence_record(
    evidence_id: str,
    candidate_id: str,
    *,
    review: str = "accepted",
    support: str = "supports",
) -> dict[str, Any]:
    return {
        "claimEvidenceId": evidence_id,
        "claimId": "claim-1",
        "candidateId": candidate_id,
        "sourceId": f"artifact:{evidence_id}",
        "reviewStatus": review,
        "supportLevel": support,
        "scopeHash": _scope_hash(),
    }


def _install_store(
    monkeypatch: pytest.MonkeyPatch,
    *,
    lineage_rows: list[dict[str, Any]] | None = None,
    disagreement_rows: list[dict[str, Any]] | None = None,
    claims: list[dict[str, Any]] | None = None,
    evidence_records: list[dict[str, Any]] | None = None,
    evidence_raises: bool = False,
    list_raises: bool = False,
) -> None:
    lineage_rows = lineage_rows or []
    disagreement_rows = disagreement_rows or []

    def fake_list(team_id: str, *, kind: str, workflow_run_id: str = "", **_: Any):
        if list_raises:
            raise OSError("artifact store unavailable")
        if workflow_run_id:
            rows = [
                row for row in lineage_rows + disagreement_rows
                if row.get("workflowRunId") == workflow_run_id
            ]
        else:
            rows = lineage_rows + disagreement_rows
        wanted = "evolution_lineage" if kind == "evolution_lineage" else kind
        return [dict(row) for row in rows if row.get("kind") == wanted]

    monkeypatch.setattr(question_lineage_service, "list_workflow_artifacts", fake_list)

    from core.web.services.team_workflow import claim_ledger as claim_ledger_service

    monkeypatch.setattr(
        claim_ledger_service,
        "list_claims",
        lambda team_id: {
            "schemaVersion": 1,
            "teamId": team_id,
            "claimCount": len(claims or []),
            "claims": list(claims or []),
            "storagePath": "<fake>",
        },
    )

    store = type(
        "_Store",
        (_FakeEvidenceStore,),
        {
            "records_by_team": {_TEAM: list(evidence_records or [])},
            "raise_on_list": evidence_raises,
        },
    )
    monkeypatch.setattr("core.research.evidence.ClaimEvidenceStore", store)


# ---------------------------------------------------------------------------
# Full chain
# ---------------------------------------------------------------------------


def _full_chain_store(monkeypatch: pytest.MonkeyPatch) -> None:
    lineage = _lineage_row(
        _lineage_payload(
            [
                _lineage_event("evt-1", "H1", "introduced"),
                _lineage_event(
                    "evt-2",
                    "H1r1",
                    "revised",
                    revision_attempt=1,
                    parent_candidate_id="H1",
                    evidence_refs=[{"kind": "disagreement_artifact", "ref": "dis:round-1"}],
                ),
                _lineage_event("evt-3", "H1r1", "finalist"),
            ]
        )
    )
    disagreement = _disagreement_row(
        "rec-dis-1",
        [_pair("cmp-1", "H1", "H2", ["falsifiability"])],
    )
    claims = [
        _claim_row(
            "claim-1",
            [
                _ref("ce-1"),
                _ref("ce-2", review="accepted", support="contradicts"),
            ],
        ),
        _claim_row("claim-2", [_ref("ce-3", review="pending")]),
    ]
    evidence = [
        _evidence_record("ce-1", "H1"),
        _evidence_record("ce-2", "H1r1", support="contradicts"),
        _evidence_record("ce-3", "H2", review="pending"),
    ]
    _install_store(
        monkeypatch,
        lineage_rows=[lineage],
        disagreement_rows=[disagreement],
        claims=claims,
        evidence_records=evidence,
    )


def test_full_chain_projection_has_all_segments_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    _full_chain_store(monkeypatch)

    result = project_question_lineage(team_id=_TEAM, question_id=_QUESTION)

    assert result["schemaVersion"] == 1
    assert result["questionId"] == _QUESTION
    assert result["boundaries"] == {"readOnly": True}
    assert result["degradedSegments"] == []
    assert sorted(result["segments"].keys()) == sorted(SEGMENT_NAMES)
    for name in SEGMENT_NAMES:
        assert result["segments"][name]["status"] == "ready", name

    evolution = result["segments"]["evolution"]
    assert evolution["lineageCount"] == 1
    events = evolution["lineages"][0]["events"]
    assert [event["eventId"] for event in events] == ["evt-1", "evt-2", "evt-3"]
    assert evolution["lineages"][0]["summary"]["finalistCandidateIds"] == ["H1r1"]

    disagreement = result["segments"]["reviewDisagreement"]
    assert disagreement["artifactCount"] == 1
    h1 = disagreement["candidates"]["H1"]
    assert h1["pairCount"] == 1
    assert h1["pairs"][0]["opposedCandidateId"] == "H2"
    assert h1["pairs"][0]["artifactRef"] == "rec-dis-1"
    assert h1["escalationRequired"] is True
    assert disagreement["candidates"]["H2"]["pairCount"] == 1

    belief = result["segments"]["claimBelief"]
    assert belief["claimCount"] == 2
    by_claim = {claim["claimId"]: claim for claim in belief["claims"]}
    assert by_claim["claim-1"]["beliefState"] == "disputed"
    assert by_claim["claim-1"]["candidateIds"] == ["H1", "H1r1"]
    assert by_claim["claim-2"]["beliefState"] == "weakly_supported"
    assert by_claim["claim-2"]["pendingSupportCount"] == 1
    assert belief["candidates"]["H1"]["beliefStates"] == {"disputed": 1}
    assert belief["beliefTableHash"]

    graph = result["segments"]["evidenceGraph"]
    edges = {(edge["source"], edge["target"]): edge for edge in graph["edges"]}
    assert edges[("claim:claim-1", "evidence:ce-1")]["kind"] == "supports"
    assert edges[("claim:claim-1", "evidence:ce-1")]["accepted"] is True
    assert edges[("claim:claim-1", "evidence:ce-2")]["kind"] == "contradicts"
    assert graph["nodeCount"] == len(graph["nodes"]) == 5
    assert graph["edgeCount"] == 3


# ---------------------------------------------------------------------------
# Degradation
# ---------------------------------------------------------------------------


def test_missing_evolution_segment_degrades_only_that_segment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disagreement = _disagreement_row("rec-dis-1", [_pair("cmp-1", "H1", "H2", ["novelty"])])
    _install_store(
        monkeypatch,
        lineage_rows=[],
        disagreement_rows=[disagreement],
        claims=[_claim_row("claim-1", [_ref("ce-1")])],
        evidence_records=[_evidence_record("ce-1", "H1")],
    )

    result = project_question_lineage(team_id=_TEAM, question_id=_QUESTION)

    assert result["degradedSegments"] == ["evolution"]
    assert result["segments"]["evolution"] == {
        "status": "missing",
        "missingReason": "evolution_lineage_artifact_missing",
    }
    assert result["segments"]["reviewDisagreement"]["status"] == "ready"
    assert result["segments"]["claimBelief"]["status"] == "ready"
    assert result["segments"]["evidenceGraph"]["status"] == "ready"


def test_claims_for_other_questions_degrade_belief_and_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    other = _claim_row("claim-other", [], question="SCI-999")
    _install_store(monkeypatch, claims=[other])

    result = project_question_lineage(team_id=_TEAM, question_id=_QUESTION)

    assert result["degradedSegments"] == [
        "evolution",
        "reviewDisagreement",
        "claimBelief",
        "evidenceGraph",
    ]
    assert result["segments"]["claimBelief"]["missingReason"] == (
        "claim_ledger_empty_for_question"
    )
    assert result["segments"]["evidenceGraph"]["missingReason"] == (
        "claim_ledger_empty_for_question"
    )


def test_store_failure_labels_every_segment(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_store(
        monkeypatch,
        lineage_rows=[_lineage_row(_lineage_payload([_lineage_event("evt-1", "H1", "introduced")]))],
        claims=[_claim_row("claim-1", [_ref("ce-1")])],
        list_raises=True,
    )

    result = project_question_lineage(team_id=_TEAM, question_id=_QUESTION)

    # The artifact store is down (both artifact segments degrade) while the
    # claim ledger fake still serves claims — belief/graph must stay ready.
    assert result["degradedSegments"] == ["evolution", "reviewDisagreement"]
    assert (
        result["segments"]["evolution"]["missingReason"]
        == "evolution_lineage_projection_failed"
    )
    assert (
        result["segments"]["reviewDisagreement"]["missingReason"]
        == "review_disagreement_projection_failed"
    )
    assert result["segments"]["claimBelief"]["status"] == "ready"
    assert result["segments"]["evidenceGraph"]["status"] == "ready"


def test_claim_ledger_failure_degrades_belief_and_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_store(monkeypatch, claims=[])
    from core.web.services.team_workflow import claim_ledger as claim_ledger_service

    def broken_list_claims(_team_id: str) -> dict[str, Any]:
        raise RuntimeError("team store unavailable")

    monkeypatch.setattr(claim_ledger_service, "list_claims", broken_list_claims)

    result = project_question_lineage(team_id=_TEAM, question_id=_QUESTION)

    assert result["segments"]["claimBelief"]["missingReason"] == "claim_ledger_unavailable"
    assert (
        result["segments"]["evidenceGraph"]["missingReason"]
        == "claim_ledger_unavailable"
    )
    assert result["segments"]["claimBelief"]["status"] == "missing"
    assert result["segments"]["evidenceGraph"]["status"] == "missing"


def test_blank_ids_return_all_missing_without_store_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("blank ids must not touch any store")

    monkeypatch.setattr(question_lineage_service, "list_workflow_artifacts", unexpected)

    result = project_question_lineage(team_id="", question_id=_QUESTION)

    assert result["degradedSegments"] == list(SEGMENT_NAMES)
    for name in SEGMENT_NAMES:
        assert result["segments"][name]["missingReason"] == "team_or_question_id_missing"


def test_evidence_store_failure_keeps_belief_from_ref_snapshots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_store(
        monkeypatch,
        claims=[_claim_row("claim-1", [_ref("ce-1")])],
        evidence_raises=True,
    )

    result = project_question_lineage(team_id=_TEAM, question_id=_QUESTION)

    belief = result["segments"]["claimBelief"]
    assert belief["status"] == "ready"
    assert belief["evidenceStoreAvailable"] is False
    # The claim ref itself says accepted+supports, so belief is still derivable.
    assert belief["claims"][0]["beliefState"] == "supported"
    assert belief["candidates"] == {}


# ---------------------------------------------------------------------------
# Scoping and payload resilience
# ---------------------------------------------------------------------------


def test_round_and_run_filters_scope_the_lineage_segment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    round_one = _lineage_row(
        _lineage_payload([_lineage_event("evt-1", "H1", "introduced")]),
        record_id="rec-r1",
    )
    round_two_payload = _lineage_payload(
        [_lineage_event("evt-2", "H2", "introduced")], round_id="round-2"
    )
    round_two_payload["workflowRunId"] = "wf-2"
    round_two = _lineage_row(round_two_payload, record_id="rec-r2", workflow_run_id="wf-2")
    _install_store(monkeypatch, lineage_rows=[round_one, round_two])

    scoped = project_question_lineage(
        team_id=_TEAM, question_id=_QUESTION, round_id="round-2"
    )
    assert scoped["segments"]["evolution"]["lineageCount"] == 1
    assert scoped["segments"]["evolution"]["lineages"][0]["recordId"] == "rec-r2"

    run_scoped = project_question_lineage(
        team_id=_TEAM, question_id=_QUESTION, workflow_run_id="wf-2"
    )
    assert run_scoped["segments"]["evolution"]["lineages"][0]["recordId"] == "rec-r2"

    unscoped = project_question_lineage(team_id=_TEAM, question_id=_QUESTION)
    assert unscoped["segments"]["evolution"]["lineageCount"] == 2


def test_contract_invalid_lineage_keeps_events_but_degrades_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No opening `introduced` event → the contract must reject the payload;
    # the projection still shows the raw events with a degraded summary.
    invalid = _lineage_row(
        _lineage_payload([_lineage_event("evt-1", "H1", "finalist")]),
    )
    _install_store(monkeypatch, lineage_rows=[invalid])

    with pytest.raises(ContractValidationError):
        from core.research.workflow.contracts.evolution_lineage import EvolutionLineage

        EvolutionLineage.from_dict(invalid["payload"])

    result = project_question_lineage(team_id=_TEAM, question_id=_QUESTION)

    evolution = result["segments"]["evolution"]
    assert evolution["status"] == "ready"
    assert evolution["lineages"][0]["events"][0]["eventId"] == "evt-1"
    assert evolution["lineages"][0]["summary"]["summaryDegraded"] is True
    assert evolution["lineages"][0]["summary"]["eventCount"] == 1


def test_disagreement_without_pairs_reports_missing_segment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty = _disagreement_row("rec-dis-empty", [], escalation_required=False)
    _install_store(monkeypatch, disagreement_rows=[empty])

    result = project_question_lineage(team_id=_TEAM, question_id=_QUESTION)

    assert result["segments"]["reviewDisagreement"] == {
        "status": "missing",
        "missingReason": "review_disagreement_artifact_missing",
    }


# ---------------------------------------------------------------------------
# Thin GET route
# ---------------------------------------------------------------------------


def _client() -> TestClient:
    from core.web.app import create_app
    from core.web.control import CONTROL_TOKEN_HEADER, get_control_token

    return TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


def test_question_lineage_route_wires_query_params(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_projection(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "schemaVersion": 1,
            "teamId": kwargs["team_id"],
            "questionId": kwargs["question_id"],
            "workflowRunId": kwargs["workflow_run_id"],
            "roundId": kwargs["round_id"],
            "degradedSegments": ["evolution"],
            "segments": {
                "evolution": {"status": "missing", "missingReason": "x"},
                "reviewDisagreement": {"status": "ready"},
                "claimBelief": {"status": "ready"},
                "evidenceGraph": {"status": "ready"},
            },
        }

    monkeypatch.setattr(
        research_runtime_routes, "project_question_lineage", fake_projection
    )
    response = _client().get(
        f"/api/research/questions/{_QUESTION}/lineage",
        params={"teamId": _TEAM, "runId": "wf-9", "roundId": "round-3"},
    )

    assert response.status_code == 200
    body = response.json()
    assert captured == {
        "team_id": _TEAM,
        "question_id": _QUESTION,
        "workflow_run_id": "wf-9",
        "round_id": "round-3",
    }
    assert body["degradedSegments"] == ["evolution"]
    assert body["segments"]["claimBelief"] == {"status": "ready"}


def test_question_lineage_route_requires_team_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        research_runtime_routes,
        "project_question_lineage",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("missing teamId must be rejected by validation")
        ),
    )
    response = _client().get(f"/api/research/questions/{_QUESTION}/lineage")

    assert response.status_code == 422
