"""Focused contract checks for the independent seven-dimension authority."""

from __future__ import annotations

from copy import deepcopy

from core.web.services.team_workflow.research_runtime import (
    dimension_reviews_artifact_writer as writer,
)


_EVIDENCE_REF = "evidence_card_batch://team-1/source-1/0123456789abcdef0123456789abcdef"
_AUTHORITY = {
    "authorityKind": "workflow_run",
    "teamId": "team-1",
    "questionId": "SCI-001",
    "workflowRunId": "wf-1",
}
_BASE = {
    "team_id": "team-1",
    "workflow_run_id": "wf-1",
    "node_run_id": "node-1",
    "question_id": "SCI-001",
    "selection_id": "selection-1",
    "review_round_id": "round-1",
    "input_refs": ["hypothesis_selection:selection-1", _EVIDENCE_REF],
    "input_snapshot_hash": "a" * 64,
    "candidates": [
        {"candidateId": "H1", "claim": "claim one"},
        {"candidateId": "H2", "claim": "claim two"},
    ],
    "workflow_authority": _AUTHORITY,
}


def _review_rows() -> list[dict[str, str | list[str]]]:
    return [
        {
            "hypothesis_id": candidate,
            "dimension": dimension,
            "rating": "adequate",
            "rationale": f"{candidate} {dimension} rationale",
            "reviewer": "reviewer-1",
            "evidence_refs": [_EVIDENCE_REF],
        }
        for candidate in ("H1", "H2")
        for dimension in writer.REQUIRED_REVIEW_DIMENSIONS
    ]


def test_missing_node_binding_blocks_without_writing(monkeypatch):
    writes = []
    monkeypatch.setattr(writer, "put_workflow_artifact", lambda *args, **kwargs: writes.append(1))
    request = deepcopy(_BASE)
    request["node_run_id"] = ""
    result = writer.materialize_dimension_reviews_authority(**request, review={"dimensionReviews": _review_rows()})

    assert result["status"] == "blocked"
    assert "nodeRunId_missing" in result["blockerCodes"]
    assert writes == []


def test_score_only_review_is_not_promoted(monkeypatch):
    writes = []
    monkeypatch.setattr(writer, "put_workflow_artifact", lambda *args, **kwargs: writes.append(1))
    result = writer.materialize_dimension_reviews_authority(
        **_BASE,
        review={
            "candidates": [
                {"candidateId": "H1", "scores": {dimension: 0.8 for dimension in writer.REQUIRED_REVIEW_DIMENSIONS}},
                {"candidateId": "H2", "scores": {dimension: 0.7 for dimension in writer.REQUIRED_REVIEW_DIMENSIONS}},
            ]
        },
    )

    assert result["status"] == "blocked"
    assert "dimension_reviews_missing" in result["blockerCodes"]
    assert writes == []


def test_missing_or_duplicate_dimension_blocks(monkeypatch):
    writes = []
    monkeypatch.setattr(writer, "put_workflow_artifact", lambda *args, **kwargs: writes.append(1))
    rows = _review_rows()
    rows.pop()
    rows.append(dict(rows[0]))
    result = writer.materialize_dimension_reviews_authority(**_BASE, review={"dimensionReviews": rows})

    assert result["status"] == "blocked"
    assert "dimension_review_duplicate" in result["blockerCodes"]
    assert "dimension_reviews_incomplete" in result["blockerCodes"]
    assert writes == []


def test_complete_explicit_rows_write_deterministically(monkeypatch):
    writes = []

    def fake_put(team_id, **kwargs):
        writes.append((team_id, kwargs))
        return {
            "recordId": kwargs["artifact_identity"],
            "workflowRunId": kwargs["workflow_run_id"],
            "sourceCollectionRunId": kwargs["source_collection_run_id"],
            "contentHash": writer.canonical_sha256(kwargs["payload"]),
        }

    monkeypatch.setattr(writer, "put_workflow_artifact", fake_put)
    monkeypatch.setattr(writer, "read_domain_artifact", lambda ref: object())
    request = {**_BASE, "review": {"dimensionReviews": _review_rows()}}
    first = writer.materialize_dimension_reviews_authority(**request)
    second = writer.materialize_dimension_reviews_authority(**request)

    assert first["status"] == "written"
    assert second["status"] == "written"
    assert first["inputHash"] == second["inputHash"]
    assert first["artifact"]["canonicalRef"] == second["artifact"]["canonicalRef"]
    assert writes[0][1]["artifact_identity"] == writes[1][1]["artifact_identity"]
