from __future__ import annotations

from copy import deepcopy
from typing import Any

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
    assert package["citationChecks"]
    assert {
        item["sourceUrl"]
        for item in package["citationChecks"]
        if item.get("status") == "passed"
    } == {item["source_url"] for item in output["evidence"]}
    assert all(item["evidenceId"] for item in package["citationChecks"])
    assert package["packageId"].startswith("rrp-v2:run-sci-096:sci-096:")


def test_citation_checks_preserve_unverified_evidence_as_failed() -> None:
    output = _output(96)
    evidence = deepcopy(output["evidence"])
    evidence[0]["verification_status"] = "unverified"

    checks = result_package_v2._citation_checks(evidence)

    assert checks[0] == {
        "evidenceId": evidence[0]["evidence_id"],
        "sourceUrl": evidence[0]["source_url"],
        "verificationStatus": "unverified",
        "status": "failed",
    }
    assert all(item["status"] == "passed" for item in checks[1:])


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


# ---------------------------------------- canonical claim-evidence projection


def _claim_evidence_card(**overrides: Any) -> dict[str, Any]:
    """Shape of a canonical ``ClaimEvidenceStore`` record.

    The fact anchor is persisted as ``quote``; support and verification live
    in ``supportLevel``/``reviewStatus``.  No ``fact``/``claim``/``relation``/
    ``verification_status`` keys exist on the stored record.
    """
    card = {
        "schemaVersion": 1,
        "claimEvidenceId": "ce-anchor",
        "claimId": "claim-1",
        "candidateId": "candidate-1",
        "sourceId": "abstract-block-1",
        "locator": {"kind": "citation", "url": "abstract-block-1"},
        "quote": "The universe performs at most 10^120 operations on 10^90 bits.",
        "evidenceKind": "primary_result",
        "reasoningRole": "fact",
        "supportLevel": "supports",
        "reviewStatus": "pending",
    }
    card.update(overrides)
    return card


def _claim_evidence_artifacts(cards: list[dict]) -> tuple[dict, dict[str, dict]]:
    expected, artifacts = _authority_sections()
    artifacts["source_candidate_batch"] = {
        "candidates": [
            {
                "candidateId": "candidate-1",
                "title": "Computational Capacity of the Universe",
                "sourceKind": "paper",
                "sourceUrl": "https://doi.org/10.1103/PhysRevLett.88.237901",
                "retrievedAt": "2026-09-02T17:14:45Z",
            },
            {
                "candidateId": "candidate-2",
                "title": "Dennard scaling",
                "sourceKind": "url",
                "sourceUrl": "https://en.wikipedia.org/wiki/Dennard_scaling",
                "updatedAt": "2026-09-02T17:15:45Z",
            },
        ]
    }
    artifacts["evidence_card_batch"] = {
        "teamId": "research-team",
        "sourceCollectionRunId": "source-sci-096",
        "evidenceCards": cards,
        "cardCount": len(cards),
    }
    return expected, artifacts


def _build_v2_with_artifacts(monkeypatch, artifacts: dict[str, dict]) -> dict:
    expected = _authority_sections()[0]
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
    return result_package_v2.build_challenge_result_package_v2(
        generic_package={"runId": "run-sci-096", "factChainHash": "f" * 64},
        record=_record(),
        team_id="research-team",
        workflow_run_id="run-sci-096",
        source_collection_run_id="source-sci-096",
    )


def test_v2_projects_claim_evidence_quote_as_fact(monkeypatch) -> None:
    _, artifacts = _claim_evidence_artifacts(
        [
            _claim_evidence_card(claimEvidenceId="ce-supports", supportLevel="supports"),
            _claim_evidence_card(
                claimEvidenceId="ce-contradicts",
                candidateId="candidate-1",
                quote="Landauer's principle has been falsified.",
                supportLevel="contradicts",
                reviewStatus="accepted",
            ),
            _claim_evidence_card(
                claimEvidenceId="ce-insufficient",
                candidateId="candidate-2",
                quote="The page mentions Dennard scaling without sources.",
                supportLevel="insufficient",
                reviewStatus="pending",
            ),
        ]
    )

    package = _build_v2_with_artifacts(monkeypatch, artifacts)
    output = package["challengeQuestionOutput"]

    assert challenge_question_runs._schema_issues(output) == []
    evidence = {item["evidence_id"]: item for item in output["evidence"]}
    # The verbatim quote is the fact anchor; nothing is synthesized.
    assert evidence["ce-supports"]["fact"] == (
        "The universe performs at most 10^120 operations on 10^90 bits."
    )
    assert evidence["ce-supports"]["relation"] == "supports"
    assert evidence["ce-supports"]["verification_status"] == "unverified"
    assert evidence["ce-supports"]["source_type"] == "peer_reviewed_paper"
    assert evidence["ce-supports"]["retrieved_at"] == "2026-09-02T17:14:45Z"
    assert evidence["ce-contradicts"]["relation"] == "challenges"
    assert evidence["ce-contradicts"]["verification_status"] == "human_verified"
    assert evidence["ce-insufficient"]["relation"] == "context"
    assert evidence["ce-insufficient"]["source_type"] == "other"
    assert evidence["ce-insufficient"]["retrieved_at"] == "2026-09-02T17:15:45Z"
    # Fail-closed floor: pending review state can never pass a citation check.
    checks = {item["evidenceId"]: item["status"] for item in package["citationChecks"]}
    assert checks["ce-supports"] == "failed"
    assert checks["ce-insufficient"] == "failed"
    assert checks["ce-contradicts"] == "passed"


def test_v2_claim_evidence_card_without_fact_anchor_fails_closed(monkeypatch) -> None:
    _, artifacts = _claim_evidence_artifacts(
        [_claim_evidence_card(quote=" ")]
    )

    with pytest.raises(result_package_v2.ResultPackageV2Error, match="evidence.fact"):
        _build_v2_with_artifacts(monkeypatch, artifacts)


def test_v2_evidence_card_with_unknown_candidate_fails_closed(monkeypatch) -> None:
    _, artifacts = _claim_evidence_artifacts(
        [_claim_evidence_card(candidateId="candidate-missing")]
    )

    with pytest.raises(
        result_package_v2.ResultPackageV2Error,
        match="candidate-missing missing from source_candidate_batch",
    ):
        _build_v2_with_artifacts(monkeypatch, artifacts)


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


def test_proposal_base_does_not_claim_actual_execution() -> None:
    record = {
        **_record(),
        "workflowId": "challenge-cup-research",
        "projectId": "project-sci-096",
        "terminalReason": "proposal_ready_for_review",
        "artifactManifests": [
            {"artifactId": "hypothesis_set:formal-hash"},
        ],
    }
    record["inputSnapshot"].update(
        {
            "snapshotHash": "a" * 64,
            "constraintSnapshot": {"formalWrites": False},
        }
    )

    assert result_package_v2.is_proposal_only_challenge_run(record) is True
    package = result_package_v2.build_proposal_result_package_base(record)
    assert package["resultClassification"] == {
        "classification": "proposal_only",
        "actualExecution": False,
    }
    assert "officialVersion" not in package


def test_scope_accepts_the_real_frozen_research_scope_shape() -> None:
    scope = result_package_v2._scope(
        {
            "projectId": "project-sci-096",
            "researchScopeEnvelope": {
                "theme": "theme-sci-096",
                "campaign": "campaign-sci-096",
                "branch": "branch-sci-096",
            },
        }
    )
    assert scope == {
        "theme_id": "theme-sci-096",
        "campaign_id": "campaign-sci-096",
        "research_project_id": "project-sci-096",
        "memory_scope": "same_theme",
        "hypothesis_branch_id": "branch-sci-096",
    }


def test_feedback_iterations_follow_revision_parent_lineage(monkeypatch) -> None:
    monkeypatch.setattr(
        result_package_v2,
        "list_workflow_artifacts",
        lambda *_args, **_kwargs: [
            {
                "workflowRunId": "run-root",
                "sourceCollectionRunId": "source-sci-096",
                "payload": {
                    "parentRunId": "run-root",
                    "childRunId": "run-child-1",
                    "feedbackIteration": {"round": 1},
                },
            },
            {
                "workflowRunId": "run-child-1",
                "sourceCollectionRunId": "source-sci-096",
                "payload": {
                    "parentRunId": "run-child-1",
                    "childRunId": "run-child-2",
                    "feedbackIteration": {"round": 2},
                },
            },
        ],
    )
    assert result_package_v2._feedback_iterations(
        team_id="research-team",
        workflow_run_id="run-child-2",
        authority_run_id="source-sci-096",
    ) == [{"round": 1}, {"round": 2}]


def test_feedback_iterations_accept_two_phase_same_run_lineage(monkeypatch) -> None:
    monkeypatch.setattr(
        result_package_v2,
        "list_workflow_artifacts",
        lambda *_args, **_kwargs: [
            {
                "workflowRunId": "run-stage-one",
                "sourceCollectionRunId": "source-sci-096",
                "payload": {
                    "schemaVersion": 1,
                    "nodeId": "iteration_decision",
                    "feedbackIteration": {"round": 9},
                },
            },
            {
                "workflowRunId": "run-stage-one",
                "sourceCollectionRunId": "source-sci-096",
                "payload": {
                    "schemaVersion": 2,
                    "nodeId": "hypothesis_design",
                    "iterationRound": 2,
                    "revisionPhase": "review_revision",
                    "revisionEnvelope": {
                        "phase": "review_revision",
                        "parentOutput": {"refs": ["hypothesis:r1"], "sha256": "b" * 64},
                        "childOutput": {"refs": ["hypothesis:r2"], "sha256": "c" * 64},
                    },
                    "feedbackIteration": {"round": 2, "changes": ["reviewed"]},
                },
            },
            {
                "workflowRunId": "run-stage-one",
                "sourceCollectionRunId": "source-sci-096",
                "payload": {
                    "schemaVersion": 2,
                    "nodeId": "hypothesis_design",
                    "iterationRound": 1,
                    "revisionPhase": "grounded_revision",
                    "revisionEnvelope": {
                        "phase": "grounded_revision",
                        "parentOutput": {"refs": ["hypothesis:r0"], "sha256": "a" * 64},
                        "childOutput": {"refs": ["hypothesis:r1"], "sha256": "b" * 64},
                    },
                    "feedbackIteration": {"round": 1, "changes": ["grounded"]},
                },
            },
        ],
    )

    assert result_package_v2._feedback_iterations(
        team_id="research-team",
        workflow_run_id="run-stage-one",
        authority_run_id="source-sci-096",
    ) == [
        {"round": 1, "changes": ["grounded"]},
        {"round": 2, "changes": ["reviewed"]},
    ]


def test_feedback_iterations_reject_discontinuous_same_run_lineage(monkeypatch) -> None:
    def artifact(round_value: int, phase: str, parent_hash: str, child_hash: str) -> dict:
        return {
            "workflowRunId": "run-stage-one",
            "sourceCollectionRunId": "source-sci-096",
            "payload": {
                "schemaVersion": 2,
                "nodeId": "hypothesis_design",
                "iterationRound": round_value,
                "revisionPhase": phase,
                "revisionEnvelope": {
                    "phase": phase,
                    "parentOutput": {
                        "refs": [f"hypothesis:{parent_hash}"],
                        "sha256": parent_hash * 64,
                    },
                    "childOutput": {
                        "refs": [f"hypothesis:{child_hash}"],
                        "sha256": child_hash * 64,
                    },
                },
                "feedbackIteration": {"round": round_value},
            },
        }

    monkeypatch.setattr(
        result_package_v2,
        "list_workflow_artifacts",
        lambda *_args, **_kwargs: [
            artifact(1, "grounded_revision", "a", "b"),
            artifact(2, "review_revision", "c", "d"),
        ],
    )

    with pytest.raises(
        result_package_v2.ResultPackageV2Error,
        match="same-run hypothesis feedback lineage is discontinuous",
    ) as exc_info:
        result_package_v2._feedback_iterations(
            team_id="research-team",
            workflow_run_id="run-stage-one",
            authority_run_id="source-sci-096",
        )

    assert exc_info.value.code == "challenge_v2_feedback_conflict"


def test_feedback_iterations_reject_parent_cycle(monkeypatch) -> None:
    monkeypatch.setattr(
        result_package_v2,
        "list_workflow_artifacts",
        lambda *_args, **_kwargs: [
            {
                "workflowRunId": "run-root",
                "sourceCollectionRunId": "source-sci-096",
                "payload": {
                    "parentRunId": "run-child",
                    "childRunId": "run-root",
                    "feedbackIteration": {"round": 1},
                },
            },
            {
                "workflowRunId": "run-child",
                "sourceCollectionRunId": "source-sci-096",
                "payload": {
                    "parentRunId": "run-root",
                    "childRunId": "run-child",
                    "feedbackIteration": {"round": 2},
                },
            },
        ],
    )

    with pytest.raises(
        result_package_v2.ResultPackageV2Error,
        match="feedback lineage contains a cycle",
    ) as exc_info:
        result_package_v2._feedback_iterations(
            team_id="research-team",
            workflow_run_id="run-child",
            authority_run_id="source-sci-096",
        )

    assert exc_info.value.code == "challenge_v2_feedback_conflict"


def test_model_run_uses_real_receipt_ids_and_final_route(monkeypatch) -> None:
    receipt = {
        "receiptId": "receipt-final",
        "nodeRunId": "node-final",
        "outcomeKinds": ["candidate", "review", "revision", "plan", "final_output"],
        "evidenceLocator": {"kind": "turn_journal"},
    }
    monkeypatch.setattr(result_package_v2, "list_workflow_artifacts", lambda *_a, **_k: [])
    monkeypatch.setattr(
        result_package_v2,
        "question_model_invocation_receipt_refs",
        lambda *_a, **_k: [deepcopy(receipt)],
    )
    record = {
        "createdAt": "2026-07-23T00:00:00Z",
        "modelRoutingDecisions": [
            {
                "nodeRunId": "node-final",
                "providerId": "dashscope_main",
                "modelId": "qwen3.6-plus",
                "modelRef": "dashscope_main/qwen3.6-plus",
            }
        ],
    }
    run = result_package_v2._model_run(
        record,
        team_id="research-team",
        question_id="SCI-096",
        workflow_run_id="run-sci-096",
        authority_run_id="source-sci-096",
    )
    assert run["platform"] == "aliyun_bailian"
    assert run["invocation_evidence_refs"] == [
        "model-invocation-receipt:receipt-final"
    ]

    record["modelRoutingDecisions"][0].update(
        {
            "providerId": "opencode_go",
            "modelId": "deepseek-v4-flash",
            "modelRef": "opencode_go/deepseek-v4-flash",
        }
    )
    flash_run = result_package_v2._model_run(
        record,
        team_id="research-team",
        question_id="SCI-096",
        workflow_run_id="run-sci-096",
        authority_run_id="source-sci-096",
    )

    assert flash_run["model_provider"] == "opencode_go"
    assert flash_run["model_id"] == "opencode_go/deepseek-v4-flash"
    assert flash_run["platform"] == "other_official_tool"
