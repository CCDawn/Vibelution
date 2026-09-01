from __future__ import annotations

import copy
import hashlib
import json

import pytest

from core.research.workflow.contracts._validation import ContractValidationError
from core.research.workflow.contracts.hypothesis_fragment import (
    HypothesisFragment,
    canonical_fragment_payload,
)
from core.web.services.team_workflow.research_runtime.hypothesis_fragment_aggregator import (
    aggregate_hypothesis_fragments,
)
from core.web.services.team_workflow.research_runtime.hypothesis_fragment_writer import (
    record_hypothesis_fragment,
)


def _hash(payload: dict) -> str:
    body = {key: value for key, value in payload.items() if key != "contentHash"}
    return hashlib.sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _fragment(candidate_id: str, *, order: int = 0, **overrides) -> dict:
    payload = {
        "schemaVersion": 2,
        "kind": "hypothesis_fragment",
        "workflowRunId": "run-1",
        "workflowNodeId": "hypothesis_design",
        "nodeRunId": "node-run-1",
        "selectionId": "selection-1",
        "candidateId": candidate_id,
        "sessionId": f"child-{candidate_id}",
        "sessionAttempt": 1,
        "taskId": f"task-{candidate_id}",
        "statement": f"statement-{candidate_id}",
        "mechanism": f"mechanism-{candidate_id}",
        "novelty_basis": f"novelty basis-{candidate_id}",
        "predictions": [f"prediction-{candidate_id}"],
        "falsificationCriteria": [f"falsify-{candidate_id}"],
        "evidenceRefs": [f"evidence-{candidate_id}"],
        "counterEvidenceRefs": ["allowed-counter"],
        "boundary_conditions": [f"boundary-{candidate_id}"],
        "scores": {
            "novelty": 0.8,
            "competitionFit": 0.7,
            "falsifiability": 0.9,
            "evidenceSupport": 0.6,
            "feasibility": 0.75,
        },
        "provenance": {
            "source": "child_session",
            "candidateOrder": order,
        },
    }
    payload.update(overrides)
    payload["contentHash"] = _hash(payload)
    return payload


def _context() -> dict:
    return {
        "task": {
            "taskId": "task-hyp-a",
            "taskKind": "hypothesis_design",
            "workflowRunId": "run-1",
            "workflowNodeId": "hypothesis_design",
            "nodeRunId": "node-run-1",
            "selectionId": "selection-1",
            "candidateId": "hyp-a",
            "sessionId": "child-hyp-a",
            "sessionAttempt": 1,
        },
        "hypothesisInput": {
            "status": "ready",
            "allowedEvidenceRefs": ["allowed-counter"],
        },
    }


def test_fragment_contract_requires_hash_and_preserves_scope() -> None:
    parsed = HypothesisFragment.from_dict(_fragment("hyp-a"))

    assert parsed.workflowRunId == "run-1"
    assert parsed.workflowNodeId == "hypothesis_design"
    assert parsed.nodeRunId == "node-run-1"
    assert parsed.selectionId == "selection-1"
    assert parsed.candidateId == "hyp-a"
    assert parsed.novelty_basis == "novelty basis-hyp-a"
    assert parsed.boundary_conditions == ("boundary-hyp-a",)
    assert parsed.provenance["source"] == "child_session"

    malformed = _fragment("hyp-a")
    malformed["contentHash"] = "0" * 64
    with pytest.raises(ContractValidationError, match="contentHash"):
        HypothesisFragment.from_dict(malformed)


@pytest.mark.parametrize("missing", ["novelty_basis", "boundary_conditions"])
def test_fragment_contract_fails_closed_without_explicit_v2_semantics(
    missing: str,
) -> None:
    malformed = _fragment("hyp-a")
    malformed.pop(missing)
    malformed["contentHash"] = _hash(malformed)

    with pytest.raises(ContractValidationError, match=missing):
        HypothesisFragment.from_dict(malformed)


def test_fragment_contract_rejects_conflicting_v2_aliases() -> None:
    malformed = _fragment("hyp-a")
    malformed["noveltyBasis"] = "a different novelty basis"
    malformed["contentHash"] = _hash(malformed)

    with pytest.raises(ContractValidationError, match="aliases"):
        canonical_fragment_payload(malformed)


def test_fragment_writer_fails_closed_on_unapproved_counter_evidence() -> None:
    payload = _fragment("hyp-a", counterEvidenceRefs=["not-allowed"])

    with pytest.raises(ValueError, match="allowed evidence"):
        record_hypothesis_fragment(
            team_id="team-1",
            task_context=_context(),
            payload=payload,
        )


def test_fragment_identity_is_unique_per_node_run_for_retry_rebinding() -> None:
    first_context = _context()
    first_payload = _fragment("hyp-a")
    first = record_hypothesis_fragment(
        team_id="team-1",
        task_context=first_context,
        payload=first_payload,
    )
    retry_context = copy.deepcopy(first_context)
    retry_context["task"]["nodeRunId"] = "node-run-2"
    retry_payload = _fragment("hyp-a", nodeRunId="node-run-2")
    retry = record_hypothesis_fragment(
        team_id="team-1",
        task_context=retry_context,
        payload=retry_payload,
    )

    assert first["artifact"]["recordId"] != retry["artifact"]["recordId"]
    assert first["artifact"]["recordId"].endswith(":node-run-1:1")
    assert retry["artifact"]["recordId"].endswith(":node-run-2:1")


def _persist_fragment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    *,
    team_id: str,
    task_context: dict,
    payload: dict,
):
    from core.web.services.team_workflow.research_runtime import workflow_artifact_store

    monkeypatch.setattr(workflow_artifact_store, "PROJECT_ROOT", tmp_path)
    return record_hypothesis_fragment(
        team_id=team_id,
        task_context=task_context,
        payload=payload,
        persist=True,
        artifact_sink=workflow_artifact_store.put_workflow_artifact,
    )


def test_fragment_retry_with_changed_content_uses_new_attempt_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A content-rewriting retry on the same candidate/nodeRun must not conflict."""
    from core.web.services.team_workflow.research_runtime import workflow_artifact_store

    first_context = _context()
    first = _persist_fragment(
        monkeypatch,
        tmp_path,
        team_id="team-1",
        task_context=first_context,
        payload=_fragment("hyp-a", statement="statement-v1"),
    )
    retry_context = copy.deepcopy(first_context)
    retry_context["task"]["sessionAttempt"] = 2
    retry_context["task"]["taskId"] = "task-hyp-a-retry"
    retry = _persist_fragment(
        monkeypatch,
        tmp_path,
        team_id="team-1",
        task_context=retry_context,
        payload=_fragment(
            "hyp-a",
            sessionAttempt=2,
            taskId="task-hyp-a-retry",
            statement="statement-v2",
        ),
    )

    assert first["artifact"]["recordId"] == (
        "hypothesis_fragment:selection-1:hyp-a:node-run-1:1"
    )
    assert retry["artifact"]["recordId"] == (
        "hypothesis_fragment:selection-1:hyp-a:node-run-1:2"
    )
    stored = workflow_artifact_store.list_workflow_artifacts(
        "team-1", kind="hypothesis_fragment", workflow_run_id="run-1"
    )
    assert len(stored) == 2


def test_fragment_same_attempt_replay_returns_the_existing_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from core.web.services.team_workflow.research_runtime import workflow_artifact_store

    context = _context()
    payload = _fragment("hyp-a")
    first = _persist_fragment(
        monkeypatch, tmp_path, team_id="team-1", task_context=context, payload=payload
    )
    replay = _persist_fragment(
        monkeypatch, tmp_path, team_id="team-1", task_context=context, payload=payload
    )

    assert replay["artifact"]["recordId"] == first["artifact"]["recordId"]
    assert replay["artifact"]["contentHash"] == first["artifact"]["contentHash"]
    assert (
        len(
            workflow_artifact_store.list_workflow_artifacts(
                "team-1", kind="hypothesis_fragment", workflow_run_id="run-1"
            )
        )
        == 1
    )


def test_fragment_same_attempt_changed_content_still_conflicts(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from core.web.services.team_workflow.research_runtime.workflow_artifact_store import (
        WorkflowArtifactConflictError,
    )

    context = _context()
    _persist_fragment(
        monkeypatch,
        tmp_path,
        team_id="team-1",
        task_context=context,
        payload=_fragment("hyp-a"),
    )
    with pytest.raises(WorkflowArtifactConflictError):
        _persist_fragment(
            monkeypatch,
            tmp_path,
            team_id="team-1",
            task_context=context,
            payload=_fragment("hyp-a", statement="a rewritten claim within one attempt"),
        )


def test_hypothesis_set_supports_node_run_scoped_artifact_identity() -> None:
    from core.web.services.team_workflow.research_runtime import (
        hypothesis_artifact_writer,
    )

    context = _context()
    context["task"].update(
        {
            "taskId": "task-root",
            "candidateId": "",
            "sourceCollectionRunId": "source-1",
            "sessionId": "root-session",
            "turn": {"turnId": "turn-root"},
        }
    )
    fragments = [
        _fragment("hyp-a", nodeRunId="node-run-2"),
        _fragment("hyp-b", nodeRunId="node-run-2"),
    ]
    captured: dict[str, str] = {}

    def sink(_team_id: str, **kwargs):
        captured["artifact_identity"] = str(kwargs["artifact_identity"])
        return {
            "recordId": kwargs["artifact_identity"],
            "contentHash": "c" * 64,
        }

    original_sink = hypothesis_artifact_writer.put_workflow_artifact
    hypothesis_artifact_writer.put_workflow_artifact = sink
    try:
        result = hypothesis_artifact_writer.record_hypothesis_set_from_fragments(
            team_id="team-1",
            task_context=context,
            selection={
                "selectionId": "selection-1",
                "selectedCandidateIds": ["hyp-a", "hyp-b"],
            },
            fragments=fragments,
            scope={
                "workflowRunId": "run-1",
                "workflowNodeId": "hypothesis_design",
                "nodeRunId": "node-run-2",
            },
            artifact_identity="hypothesis_set:selection-1:node-run-2:v1",
        )
    finally:
        hypothesis_artifact_writer.put_workflow_artifact = original_sink

    assert captured["artifact_identity"] == "hypothesis_set:selection-1:node-run-2:v1"
    assert result["artifact"]["recordId"] == captured["artifact_identity"]


def test_aggregator_orders_by_selection_and_emits_deterministic_portfolio_payload() -> None:
    fragments = [_fragment("hyp-b", order=1), _fragment("hyp-a", order=0)]
    selection = {
        "selectionId": "selection-1",
        "selectedCandidateIds": ["hyp-a", "hyp-b"],
    }

    first = aggregate_hypothesis_fragments(
        selection=selection,
        fragments=fragments,
        scope={
            "workflowRunId": "run-1",
            "workflowNodeId": "hypothesis_design",
            "nodeRunId": "node-run-1",
        },
    )
    second = aggregate_hypothesis_fragments(
        selection=selection,
        fragments=list(reversed(copy.deepcopy(fragments))),
        scope={
            "workflowRunId": "run-1",
            "workflowNodeId": "hypothesis_design",
            "nodeRunId": "node-run-1",
        },
    )

    assert first == second
    assert [item["candidateId"] for item in first["candidates"]] == ["hyp-a", "hyp-b"]
    assert first["aggregationMode"] == "all_required_ordered"
    assert first["candidates"][0]["scores"]["falsifiability"] == 0.9
    assert first["candidateDetails"]["hyp-a"]["novelty_basis"] == (
        "novelty basis-hyp-a"
    )
    assert first["candidateDetails"]["hyp-a"]["boundary_conditions"] == [
        "boundary-hyp-a"
    ]
    assert first["provenance"]["fragmentRefs"] == [
        "hypothesis_fragment:selection-1:hyp-a:node-run-1:1",
        "hypothesis_fragment:selection-1:hyp-b:node-run-1:1",
    ]


@pytest.mark.parametrize(
    "candidate_ids, message",
    [
        (["hyp-a"], "missing"),
        (["hyp-a", "hyp-b", "hyp-b"], "duplicate"),
        (["hyp-a", "hyp-b", "hyp-c"], "outside"),
    ],
)
def test_aggregator_rejects_missing_duplicate_and_out_of_selection_fragments(
    candidate_ids: list[str], message: str
) -> None:
    selection = {
        "selectionId": "selection-1",
        "selectedCandidateIds": ["hyp-a", "hyp-b"],
    }
    fragments = [_fragment(candidate_id) for candidate_id in candidate_ids]

    with pytest.raises(ValueError, match=message):
        aggregate_hypothesis_fragments(
            selection=selection,
            fragments=fragments,
            scope={
                "workflowRunId": "run-1",
                "workflowNodeId": "hypothesis_design",
                "nodeRunId": "node-run-1",
            },
        )


def test_aggregator_takes_latest_attempt_fragment_and_keeps_history() -> None:
    """Superseded retry attempts stay as history; aggregation fans in the latest."""
    superseded = _fragment("hyp-a", statement="statement-v1")
    latest = _fragment(
        "hyp-a",
        sessionAttempt=2,
        taskId="task-hyp-a-retry",
        sessionId="child-hyp-a-retry",
        statement="statement-v2",
    )
    selection = {
        "selectionId": "selection-1",
        "selectedCandidateIds": ["hyp-a", "hyp-b"],
    }

    payload = aggregate_hypothesis_fragments(
        selection=selection,
        fragments=[latest, superseded, _fragment("hyp-b")],
        scope={
            "workflowRunId": "run-1",
            "workflowNodeId": "hypothesis_design",
            "nodeRunId": "node-run-1",
        },
    )

    assert [item["claim"] for item in payload["candidates"]] == [
        "statement-v2",
        "statement-hyp-b",
    ]
    anchor_by_candidate = {
        item["candidateId"]: item for item in payload["candidateSessionAnchors"]
    }
    assert anchor_by_candidate["hyp-a"]["sessionAttempt"] == 2
    assert anchor_by_candidate["hyp-a"]["taskId"] == "task-hyp-a-retry"
    assert anchor_by_candidate["hyp-a"]["fragmentRef"] == (
        "hypothesis_fragment:selection-1:hyp-a:node-run-1:2"
    )
    assert payload["provenance"]["fragmentRefs"] == [
        "hypothesis_fragment:selection-1:hyp-a:node-run-1:2",
        "hypothesis_fragment:selection-1:hyp-b:node-run-1:1",
    ]


def test_aggregator_still_rejects_same_attempt_duplicate_content() -> None:
    mutated = _fragment("hyp-a", statement="a second variant of the same attempt")

    with pytest.raises(ValueError, match="duplicate"):
        aggregate_hypothesis_fragments(
            selection={
                "selectionId": "selection-1",
                "selectedCandidateIds": ["hyp-a"],
            },
            fragments=[_fragment("hyp-a"), mutated],
            scope={
                "workflowRunId": "run-1",
                "workflowNodeId": "hypothesis_design",
                "nodeRunId": "node-run-1",
            },
        )


def test_aggregator_scope_pinned_attempt_still_rejects_other_attempts() -> None:
    latest = _fragment(
        "hyp-a",
        sessionAttempt=2,
        taskId="task-hyp-a-retry",
        sessionId="child-hyp-a-retry",
    )

    with pytest.raises(ValueError, match="scope mismatch"):
        aggregate_hypothesis_fragments(
            selection={
                "selectionId": "selection-1",
                "selectedCandidateIds": ["hyp-a"],
            },
            fragments=[latest],
            scope={
                "workflowRunId": "run-1",
                "workflowNodeId": "hypothesis_design",
                "nodeRunId": "node-run-1",
                "sessionAttempt": 1,
            },
        )


def test_aggregator_rejects_cross_scope_fragment() -> None:
    selection = {
        "selectionId": "selection-1",
        "selectedCandidateIds": ["hyp-a", "hyp-b"],
    }
    foreign = _fragment("hyp-b", workflowRunId="run-foreign")

    with pytest.raises(ValueError, match="scope"):
        aggregate_hypothesis_fragments(
            selection=selection,
            fragments=[_fragment("hyp-a"), foreign],
            scope={
                "workflowRunId": "run-1",
                "workflowNodeId": "hypothesis_design",
                "nodeRunId": "node-run-1",
            },
        )


def test_aggregator_checks_optional_candidate_task_and_session_bindings() -> None:
    with pytest.raises(ValueError, match="taskId"):
        aggregate_hypothesis_fragments(
            selection={
                "selectionId": "selection-1",
                "selectedCandidateIds": ["hyp-a", "hyp-b"],
            },
            fragments=[_fragment("hyp-a"), _fragment("hyp-b")],
            scope={
                "workflowRunId": "run-1",
                "workflowNodeId": "hypothesis_design",
                "nodeRunId": "node-run-1",
                "candidateScopes": {
                    "hyp-b": {"taskId": "task-bound-to-another-child"}
                },
            },
        )
