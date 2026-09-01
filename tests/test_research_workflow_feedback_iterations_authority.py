"""Narrow contract tests for canonical feedback-iteration authority.

The shared artifact store registration is owned by the v2 integration lane, so
these tests replace its two functions with an in-memory append-only double.
They are intentionally not executed by this worker; the parent integration
session runs the focused suite after both authority slices are merged.
"""

from __future__ import annotations

from typing import Any

from core.web.services.team_workflow.research_runtime import (
    feedback_iterations_artifact_writer as writer,
)


def _evidence(round_value: int = 1) -> dict[str, Any]:
    return {
        "team_id": "team-feedback",
        "workflow_run_id": "run-feedback",
        "node_run_id": "nr-run-feedback-iteration-a1",
        "question_id": "SCI-125",
        "iteration_round": round_value,
        "feedback": {
            "trigger": "The evaluator requested an explicit control boundary.",
            "human_feedback": "Keep the claim limited to the measured population.",
            "input_refs": ["dimension_reviews://team-feedback/run-feedback/review-hash"],
            "input_hash": "a" * 64,
        },
        "revision": {
            "changes": ["Added the matched control and narrowed the claim."],
            "unresolved_issues": ["External validity remains open."],
            "output_refs": ["protocol_draft://team-feedback/run-feedback/revised-hash"],
            "output_hash": "b" * 64,
            "status": "completed",
        },
        "source_collection_run_id": "source-feedback",
        "parent_run_id": "run-feedback",
        "child_run_id": "run-feedback-child",
        "decision_id": "decision-feedback-1",
    }


def _node_seven_evidence(
    *,
    round_value: int,
    revision_phase: str,
) -> dict[str, Any]:
    evidence = _evidence(round_value=round_value)
    return {
        **evidence,
        "node_id": "hypothesis_design",
        "revision_phase": revision_phase,
        "parent_run_id": "",
        "child_run_id": "",
        "decision_id": "",
    }


def test_node_seven_revision_envelope_preserves_identity_phase_and_hash_bound_outputs(
    monkeypatch,
) -> None:
    rows: list[dict[str, Any]] = []

    monkeypatch.setattr(writer, "list_workflow_artifacts", lambda *args, **kwargs: rows)

    def fake_put(team_id: str, **kwargs):
        record = {
            "recordId": kwargs["artifact_identity"],
            "contentHash": writer.canonical_sha256(kwargs["payload"]),
            "payload": kwargs["payload"],
        }
        rows.append(record)
        return record

    monkeypatch.setattr(writer, "put_workflow_artifact", fake_put)

    grounded = writer.write_feedback_iterations_artifact(
        **_node_seven_evidence(
            round_value=1,
            revision_phase="grounded_revision",
        )
    )
    reviewed = writer.write_feedback_iterations_artifact(
        **_node_seven_evidence(
            round_value=2,
            revision_phase="review_revision",
        )
    )

    assert grounded["status"] == "recorded"
    assert reviewed["status"] == "recorded"
    assert [row["payload"]["nodeId"] for row in rows] == [
        "hypothesis_design",
        "hypothesis_design",
    ]
    assert [row["payload"]["revisionPhase"] for row in rows] == [
        "grounded_revision",
        "review_revision",
    ]
    assert rows[0]["payload"]["revisionEnvelope"] == {
        "phase": "grounded_revision",
        "parentOutput": {
            "refs": _evidence()["feedback"]["input_refs"],
            "sha256": "a" * 64,
        },
        "childOutput": {
            "refs": _evidence()["revision"]["output_refs"],
            "sha256": "b" * 64,
        },
    }


def test_node_seven_revision_requires_a_supported_explicit_phase(monkeypatch) -> None:
    calls: list[str] = []

    def unexpected(*args, **kwargs):
        calls.append("store")
        raise AssertionError("invalid node-seven evidence must not touch the store")

    monkeypatch.setattr(writer, "list_workflow_artifacts", unexpected)
    monkeypatch.setattr(writer, "put_workflow_artifact", unexpected)

    missing = writer.write_feedback_iterations_artifact(
        **_node_seven_evidence(round_value=1, revision_phase="")
    )
    unsupported = writer.write_feedback_iterations_artifact(
        **_node_seven_evidence(round_value=1, revision_phase="score_adjustment")
    )

    assert missing["status"] == "blocked"
    assert unsupported["status"] == "blocked"
    assert calls == []


def test_missing_explicit_feedback_or_revision_evidence_is_blocked(monkeypatch) -> None:
    calls: list[str] = []

    def unexpected(*args, **kwargs):
        calls.append("store")
        raise AssertionError("blocked validation must not touch the artifact store")

    monkeypatch.setattr(writer, "list_workflow_artifacts", unexpected)
    monkeypatch.setattr(writer, "put_workflow_artifact", unexpected)

    evidence = _evidence()
    result = writer.write_feedback_iterations_artifact(
        **{
            **evidence,
            "feedback": {},
            "revision": {},
        }
    )

    assert result["status"] == "blocked"
    assert "feedback_iteration_evidence_invalid" in result["blockerCodes"]
    assert calls == []


def test_round_is_strictly_increasing_and_replay_is_stable(monkeypatch) -> None:
    rows: list[dict[str, Any]] = []

    def fake_list(*args, **kwargs):
        return list(rows)

    def fake_put(team_id: str, **kwargs):
        identity = kwargs["artifact_identity"]
        for existing in rows:
            if existing["recordId"] == identity:
                assert existing["contentHash"] == writer.canonical_sha256(kwargs["payload"])
                return existing
        record = {
            "recordId": identity,
            "kind": kwargs["kind"],
            "workflowRunId": kwargs["workflow_run_id"],
            "sourceCollectionRunId": kwargs["source_collection_run_id"],
            "contentHash": writer.canonical_sha256(kwargs["payload"]),
            "payload": kwargs["payload"],
        }
        rows.append(record)
        return record

    monkeypatch.setattr(writer, "list_workflow_artifacts", fake_list)
    monkeypatch.setattr(writer, "put_workflow_artifact", fake_put)

    evidence = _evidence()
    first = writer.write_feedback_iterations_artifact(**evidence)
    replay = writer.write_feedback_iterations_artifact(**evidence)
    assert first["status"] == "recorded"
    assert replay["canonicalRef"] == first["canonicalRef"]
    assert len(rows) == 1

    blocked = writer.write_feedback_iterations_artifact(
        **{
            **_evidence(round_value=1),
            "revision": {
                **evidence["revision"],
                "output_hash": "c" * 64,
            },
        }
    )
    assert blocked["status"] == "blocked"
    assert "feedback_iteration_round_conflict" in blocked["blockerCodes"]
    assert len(rows) == 1

    second = writer.write_feedback_iterations_artifact(**_evidence(round_value=2))
    assert second["status"] == "recorded"
    assert [row["payload"]["iterationRound"] for row in rows] == [1, 2]


def test_fork_bridge_does_not_promote_decision_reason_to_feedback() -> None:
    parent = {
        "teamId": "team-feedback",
        "runId": "run-feedback",
        "questionId": "SCI-125",
        "nodeRuns": [
            {
                "nodeId": "iteration_decision",
                "nodeRunId": "nr-run-feedback-iteration-a1",
                "attempt": 1,
            }
        ],
    }
    decision = {
        "decisionKind": "revise_protocol",
        "decisionId": "decision-feedback-1",
        "nodeRunId": "nr-run-feedback-iteration-a1",
        "iterationAttempt": 1,
        "reason": "The protocol needs revision.",
    }

    result = writer.record_feedback_iteration_from_fork(
        parent=parent,
        decision=decision,
        child={"runId": "run-feedback-child"},
    )

    assert result["status"] == "blocked"
    assert "feedback_iteration_actual_evidence_missing" in result["blockerCodes"]
