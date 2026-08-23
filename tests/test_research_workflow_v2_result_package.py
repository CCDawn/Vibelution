from __future__ import annotations

from copy import deepcopy
from typing import Any

from core.web.services.team_workflow.research_runtime.human_gate_artifacts import (
    canonical_sha256,
)
from core.web.services.team_workflow.research_runtime.result_package_v2 import (
    assess_challenge_question_output_v2_readiness,
)
from tests.test_challenge_question_runs import _output


def _manifest(artifact_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifactId": artifact_id,
        "contentHash": canonical_sha256(payload),
        "schemaVersion": "1.0.0",
        "producerNodeRunId": "node-run-canonical",
        "producerAttempt": 1,
        "inputSnapshotHash": "a" * 64,
        "configHash": "b" * 64,
        "environmentSnapshotHash": "c" * 64,
        "toolVersionHash": "d" * 64,
        "sourceArtifactIds": [],
        "cacheDisposition": "produced",
        "createdAt": "2026-08-23T00:00:00Z",
    }


def _record(*, include_projection_blob: bool = True) -> tuple[dict[str, Any], dict[str, Any]]:
    output = deepcopy(_output(96))
    run_id = output["run"]["run_id"]
    payloads: dict[str, dict[str, Any]] = {
        "evidence_card_batch:canonical": {
            "runId": run_id,
            "evidenceCards": [{"evidenceId": "E1", "claim": "bounded claim"}],
        },
        "hypothesis_set:canonical": {
            "runId": run_id,
            "candidates": [{"hypothesisId": "H1", "statement": "bounded hypothesis"}],
        },
    }
    if include_projection_blob:
        payloads["run_artifacts:canonical"] = {
            "runId": run_id,
            "challengeQuestionOutputV2": output,
        }
    manifests = [
        _manifest(artifact_id, payload)
        for artifact_id, payload in payloads.items()
    ]
    record = {
        "runId": run_id,
        "workflowId": "challenge-cup-research-v2",
        "workflowVersionId": "workflow-version-v2.1",
        "teamId": "research-team",
        "projectId": output["scope"]["research_project_id"],
        "status": "succeeded",
        "inputSnapshot": {
            "questionId": output["identity"]["question_id"],
            "themeId": output["scope"]["theme_id"],
            "campaignId": output["scope"]["campaign_id"],
            "researchProjectId": output["scope"]["research_project_id"],
            "memoryScope": output["scope"]["memory_scope"],
        },
        "artifactManifests": manifests,
        "artifactPayloads": payloads,
    }
    ledger = {
        "runId": run_id,
        "boundaries": {"readOnly": True, "writesWorkflowRun": False},
        "canonicalArtifactRefs": [manifest["artifactId"] for manifest in manifests],
    }
    return record, ledger


def test_complete_v2_blob_is_not_its_own_authority() -> None:
    record, ledger = _record(include_projection_blob=True)

    result = assess_challenge_question_output_v2_readiness(
        record,
        research_ledger=ledger,
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "NEEDS_CONTEXT"
    assert result["output"] is None
    assert any(
        item["code"] == "self_referential_projection"
        for item in result["blockers"]
    )
    assert {
        "problem_understanding",
        "dimension_reviews",
        "feedback_iterations",
        "research_plan",
    } <= set(result["readiness"]["missing_business_groups"])


def test_missing_independent_business_artifacts_returns_needs_context() -> None:
    record, ledger = _record(include_projection_blob=False)

    result = assess_challenge_question_output_v2_readiness(
        record,
        research_ledger=ledger,
    )

    assert result["status"] == "blocked"
    assert result["output"] is None
    assert result["readiness"]["producer_available"] is False
    assert {
        "problem_understanding",
        "dimension_reviews",
        "feedback_iterations",
        "research_plan",
    } <= set(result["readiness"]["missing_business_groups"])
    assert any(
        item["code"] == "independent_authority_missing"
        and item["field"] == "business_groups.problem_understanding"
        for item in result["blockers"]
    )


def test_tampered_artifact_is_blocked_before_readiness_assessment() -> None:
    record, ledger = _record(include_projection_blob=False)
    artifact_id = "hypothesis_set:canonical"
    record["artifactPayloads"][artifact_id]["candidates"][0]["statement"] = "tampered"

    result = assess_challenge_question_output_v2_readiness(
        record,
        research_ledger=ledger,
    )

    assert result["status"] == "blocked"
    assert any(
        item["code"] == "artifact_hash_mismatch"
        and item["field"] == artifact_id
        for item in result["blockers"]
    )
    assert result["output"] is None


def test_readiness_result_is_deterministic_and_never_publishes_output() -> None:
    record, ledger = _record(include_projection_blob=False)

    first = assess_challenge_question_output_v2_readiness(
        record,
        research_ledger=ledger,
    )
    second = assess_challenge_question_output_v2_readiness(
        record,
        research_ledger=ledger,
    )

    assert first == second
    assert first["output"] is None
    assert first["idempotency_key"].startswith(
        f"{record['runId']}:{record['inputSnapshot']['questionId']}:v2-readiness:"
    )
