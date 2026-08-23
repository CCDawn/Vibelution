from __future__ import annotations

from copy import deepcopy

import pytest

from core.web.services.team_workflow import challenge_question_runs
from core.web.services.team_workflow.research_runtime import result_package_v2
from tests.test_challenge_question_runs import _output


def _authority_sections() -> tuple[dict, dict[str, dict]]:
    output = _output(96)
    artifacts = {
        "problem_understanding": deepcopy(output["problem_understanding"]),
        "source_candidate_batch": {"candidates": []},
        "evidence_card_batch": {"evidence": deepcopy(output["evidence"])},
        "hypothesis_set": {
            "hypotheses": deepcopy(output["hypotheses"]),
            "selection": deepcopy(output["selection"]),
            "finalSummary": deepcopy(output["result_classification"]["final_summary"]),
            "competitionResultView": deepcopy(output["competition_result_view"]),
        },
        "dimension_reviews": {
            "dimensionReviews": deepcopy(output["dimension_reviews"]),
        },
        "research_plan": {"researchPlan": deepcopy(output["research_plan"])},
    }
    return output, artifacts


def _record() -> dict:
    return {
        "runId": "run-sci-096",
        "teamId": "research-team",
        "createdAt": "2026-07-23T00:00:00Z",
        "completedAt": "2026-07-23T00:10:00Z",
        "workflowVersionId": "challenge-cup@2.1",
        "inputSnapshot": {
            "questionId": "SCI-096",
            "themeId": "theme-sci-096",
            "campaignId": "campaign-sci-096",
            "projectId": "project-sci-096",
            "memoryScope": "same_theme",
        },
    }


def test_v2_producer_embeds_one_schema_valid_pending_candidate(monkeypatch) -> None:
    expected, artifacts = _authority_sections()
    monkeypatch.setattr(
        result_package_v2,
        "_artifact_payload",
        lambda kind, **_kwargs: deepcopy(artifacts[kind]),
    )
    monkeypatch.setattr(
        result_package_v2,
        "_feedback_iterations",
        lambda **_kwargs: deepcopy(expected["feedback_iterations"]),
    )
    monkeypatch.setattr(
        result_package_v2,
        "_model_run",
        lambda *_args, **_kwargs: {
            **deepcopy(expected["run"]),
            "run_id": "run-sci-096",
        },
    )

    package = result_package_v2.build_challenge_result_package_v2(
        generic_package={
            "runId": "run-sci-096",
            "teamId": "research-team",
            "factChainHash": "f" * 64,
            "packageId": "old",
            "packageRef": "old",
            "contentHash": "0" * 64,
        },
        record=_record(),
        team_id="research-team",
        workflow_run_id="run-sci-096",
        source_collection_run_id="source-sci-096",
    )

    output = package["challengeQuestionOutput"]
    assert challenge_question_runs._schema_issues(output) == []
    assert output["result_classification"]["classification"] == "proposal_only"
    assert output["result_classification"]["actual_execution"] is False
    assert output["review"]["human_review_status"] == "pending"
    assert output["submission"] == {
        "eligible": False,
        "projection_version": "1.0-review.1",
        "blockers": ["human_review_pending"],
    }
    assert package["citationChecks"] == []
    assert package["packageId"].startswith("rrp-v2:run-sci-096:sci-096:")


def test_v2_producer_fails_closed_without_canonical_final_summary(monkeypatch) -> None:
    expected, artifacts = _authority_sections()
    artifacts["hypothesis_set"].pop("finalSummary")
    monkeypatch.setattr(
        result_package_v2,
        "_artifact_payload",
        lambda kind, **_kwargs: deepcopy(artifacts[kind]),
    )
    monkeypatch.setattr(
        result_package_v2,
        "_feedback_iterations",
        lambda **_kwargs: deepcopy(expected["feedback_iterations"]),
    )
    monkeypatch.setattr(result_package_v2, "_model_run", lambda *_a, **_k: deepcopy(expected["run"]))

    with pytest.raises(result_package_v2.ResultPackageV2Error, match="final_summary"):
        result_package_v2.build_challenge_result_package_v2(
            generic_package={"runId": "run-sci-096"},
            record=_record(),
            team_id="research-team",
            workflow_run_id="run-sci-096",
            source_collection_run_id="source-sci-096",
        )


def test_shared_registry_reads_new_canonical_kinds(monkeypatch) -> None:
    from core.web.services.team_workflow.research_runtime import (
        artifact_readback_registry,
    )

    calls: list[str] = []
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.workflow_artifact_store.load_workflow_artifact_payload",
        lambda kind, **_kwargs: calls.append(kind) or {"kind": kind},
    )
    for kind in ("dimension_reviews", "feedback_iterations"):
        assert artifact_readback_registry.resolve_artifact_authority(kind) is not None
        assert artifact_readback_registry.load_scoped_artifact_payload(
            kind,
            team_id="research-team",
            authority_run_id="source-sci-096",
            workflow_run_id="run-sci-096",
        ) == {"kind": kind}
    assert calls == ["dimension_reviews", "feedback_iterations"]
