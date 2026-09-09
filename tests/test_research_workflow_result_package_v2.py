from __future__ import annotations

import json
from copy import deepcopy
from contextlib import nullcontext
from pathlib import Path
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
        },
        "dimension_reviews": {
            "dimensionReviews": deepcopy(output["dimension_reviews"]),
        },
        "research_plan": {"researchPlan": deepcopy(output["research_plan"])},
        "competition_alignment": {
            "competitionResultView": deepcopy(output["competition_result_view"]),
        },
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


def test_v2_producer_fails_closed_without_problem_scope(monkeypatch) -> None:
    expected, artifacts = _authority_sections()
    artifacts["problem_understanding"]["scope"] = ""
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

    with pytest.raises(result_package_v2.ResultPackageV2Error, match="answer_boundary"):
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


def test_v2_source_screened_candidate_projects_metadata_checked_and_human_veto_wins(
    monkeypatch,
) -> None:
    _, artifacts = _claim_evidence_artifacts(
        [
            _claim_evidence_card(claimEvidenceId="ce-screened", supportLevel="supports"),
            _claim_evidence_card(
                claimEvidenceId="ce-rejected",
                candidateId="candidate-2",
                quote="The page mentions Dennard scaling without sources.",
                supportLevel="contradicts",
                reviewStatus="rejected",
            ),
        ]
    )
    # The collection stage screened both sources at the metadata level and
    # persisted the abstract; the source_candidate_batch rows carry that
    # authority verbatim.
    for candidate in artifacts["source_candidate_batch"]["candidates"]:
        candidate["qualityStatus"] = "source_quality_approved"
        candidate["currentState"] = "source_screened"

    package = _build_v2_with_artifacts(monkeypatch, artifacts)
    output = package["challengeQuestionOutput"]

    assert challenge_question_runs._schema_issues(output) == []
    evidence = {item["evidence_id"]: item for item in output["evidence"]}
    # Pending card review + collection-stage-screened source -> the schema's
    # metadata_checked, faithful to the source candidate authority.
    assert evidence["ce-screened"]["verification_status"] == "metadata_checked"
    # A card-level human rejection is never overridden by the source-level
    # authority: the fail-closed floor holds.
    assert evidence["ce-rejected"]["verification_status"] == "unverified"

    checks = {item["evidenceId"]: item["status"] for item in package["citationChecks"]}
    assert checks["ce-screened"] == "passed"
    assert checks["ce-rejected"] == "failed"


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
    """Real stage-one shape: each revision re-grounds on its own review cycle.

    The canonical writer binds ``parentOutput`` to the row's ``inputHash``
    and ``childOutput`` to its ``outputHash``; later rounds are NOT chained
    onto the previous child output.
    """
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
                    "inputHash": "c" * 64,
                    "outputHash": "d" * 64,
                    "revisionEnvelope": {
                        "phase": "review_revision",
                        "parentOutput": {
                            "refs": ["collection_request:r2", "meeting_round:r2"],
                            "sha256": "c" * 64,
                        },
                        "childOutput": {"refs": ["hypothesis:r2"], "sha256": "d" * 64},
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
                    "inputHash": "a" * 64,
                    "outputHash": "b" * 64,
                    "revisionEnvelope": {
                        "phase": "grounded_revision",
                        "parentOutput": {
                            "refs": ["collection_request:r1", "meeting_round:r1"],
                            "sha256": "a" * 64,
                        },
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
    def artifact(
        round_value: int,
        phase: str,
        input_hash: str,
        output_hash: str,
        *,
        envelope_parent_hash: str | None = None,
        envelope_child_hash: str | None = None,
    ) -> dict:
        return {
            "workflowRunId": "run-stage-one",
            "sourceCollectionRunId": "source-sci-096",
            "payload": {
                "schemaVersion": 2,
                "nodeId": "hypothesis_design",
                "iterationRound": round_value,
                "revisionPhase": phase,
                "inputHash": input_hash * 64,
                "outputHash": output_hash * 64,
                "revisionEnvelope": {
                    "phase": phase,
                    "parentOutput": {
                        "refs": [f"hypothesis:{envelope_parent_hash or input_hash}"],
                        "sha256": (envelope_parent_hash or input_hash) * 64,
                    },
                    "childOutput": {
                        "refs": [f"hypothesis:{envelope_child_hash or output_hash}"],
                        "sha256": (envelope_child_hash or output_hash) * 64,
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
            # Round 2's envelope claims a parent hash that is not the row's
            # persisted input hash: the row contradicts its own lineage.
            artifact(2, "review_revision", "c", "d", envelope_parent_hash="e"),
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
    # Official-family deployment ids collapse onto the OFFICIAL_PROVIDERS
    # family token; unknown families stay verbatim (fail-closed downstream).
    assert run["model_provider"] == "dashscope"

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

    record["modelRoutingDecisions"][0].update(
        {
            "providerId": "meoo_x",
            "modelId": "meoo-v2",
            "modelRef": "meoo_x/meoo-v2",
        }
    )
    meoo_run = result_package_v2._model_run(
        record,
        team_id="research-team",
        question_id="SCI-096",
        workflow_run_id="run-sci-096",
        authority_run_id="source-sci-096",
    )

    # A platform marker is not an official-model family: meoo_x keeps its
    # verbatim provider id and only maps its platform.
    assert meoo_run["model_provider"] == "meoo_x"
    assert meoo_run["platform"] == "meoo"


# ------------------------------- stage-one accepted-round hypothesis authority


def _round_candidate(**overrides: Any) -> dict[str, Any]:
    """Shape of one accepted ``hypothesis_rounds`` candidate (real fields)."""
    candidate = {
        "candidateId": "sci-091-cbdbec3a3",
        "claim": "Erase-cost and cooling jointly bound sustained processing rate.",
        "rationale": "Separates the bound into erasure energy and heat removal.",
        "differenceFromAlternatives": "Unlike constant-bound alternatives, the mechanism is separable and measurable.",
        "lineageRefs": ["candidate-2026-e1", "candidate-2026-e2"],
        "noveltyContrast": {"basis": "retrieved", "deltaStatement": "No overlapping prior work found."},
        "scores": {"falsifiability": 0.82},
        "status": "reviewed",
    }
    candidate.update(overrides)
    return candidate


def _chain_candidate(**overrides: Any) -> dict[str, Any]:
    """Shape of one ``hypothesis_first_chain`` hypothesis_candidate record."""
    record = {
        "recordKind": "hypothesis_candidate",
        "candidateId": "sci-091-cbdbec3a3",
        "candidateAuthority": "formal_grounded_candidate",
        "statement": "Erase-cost and cooling jointly bound sustained processing rate.",
        "falsifier": "A peer-reviewed result showing sustained ops/s rising without better cooling.",
        "testablePrediction": "ops/s <= P_cool / (N_e * E_e + overhead).",
        "axisProfile": {
            "mechanism": "Irreversible erasure dissipates energy; cooling bounds sustained power.",
            "boundary": "Applies only to fixed cooling and reliability budgets.",
        },
        "lineageRefs": ["candidate-2026-e1"],
    }
    record.update(overrides)
    return record


def _patch_hypothesis_authorities(
    monkeypatch, round_candidates, chain_candidates, round_extra: dict[str, Any] | None = None
) -> None:
    from core.web.services.team_workflow import hypothesis_rounds
    from core.web.services.team_workflow.research_runtime import hypothesis_first_chain

    round_record: dict[str, Any] = {
        "roundId": "hround-1",
        "candidates": round_candidates,
    }
    if round_extra:
        round_record.update(round_extra)
    monkeypatch.setattr(
        hypothesis_rounds,
        "get_hypothesis_round",
        lambda team_id, round_id: {"teamId": team_id, "round": round_record},
    )
    monkeypatch.setattr(
        hypothesis_first_chain,
        "list_hypothesis_candidates",
        lambda team_id, **_kwargs: {"candidates": chain_candidates},
    )


def test_hypotheses_project_accepted_round_and_chain_authorities(monkeypatch) -> None:
    _patch_hypothesis_authorities(
        monkeypatch,
        [_round_candidate(), _round_candidate(candidateId="sci-091-cf0889b0d")],
        [
            _chain_candidate(),
            _chain_candidate(
                candidateId="sci-091-cf0889b0d",
                falsifier="Sustained throughput approaching Lloyd/cGh bounds would falsify this.",
                axisProfile={"mechanism": "CMOS power density and thermal budgets bind frequency."},
            ),
        ],
    )
    hypotheses = result_package_v2._hypotheses(
        {"candidates": [{"candidateId": "hyp-portfolio-1", "claim": "portfolio"}]},
        team_id="research-team",
        question_id="SCI-091",
        dimension_payload={"reviewRoundId": "hround-1"},
    )

    assert [item["hypothesis_id"] for item in hypotheses] == [
        "sci-091-cbdbec3a3",
        "sci-091-cf0889b0d",
    ]
    first = hypotheses[0]
    assert first["statement"] == "Erase-cost and cooling jointly bound sustained processing rate."
    assert first["falsifiability"] == (
        "A peer-reviewed result showing sustained ops/s rising without better cooling."
    )
    assert first["mechanism"] == (
        "Irreversible erasure dissipates energy; cooling bounds sustained power."
    )
    assert first["novelty_basis"] == (
        "Unlike constant-bound alternatives, the mechanism is separable and measurable."
    )
    assert first["predictions"] == ["ops/s <= P_cool / (N_e * E_e + overhead)."]
    assert first["boundary_conditions"] == [
        "Applies only to fixed cooling and reliability budgets."
    ]
    assert first["supporting_evidence_refs"] == ["candidate-2026-e1", "candidate-2026-e2"]
    assert first["challenging_evidence_refs"] == []


def test_hypothesis_without_chain_falsifier_fails_closed(monkeypatch) -> None:
    _patch_hypothesis_authorities(
        monkeypatch,
        [_round_candidate(), _round_candidate(candidateId="sci-091-cf0889b0d")],
        [
            _chain_candidate(falsifier=" "),
            _chain_candidate(candidateId="sci-091-cf0889b0d"),
        ],
    )

    with pytest.raises(
        result_package_v2.ResultPackageV2Error,
        match="sci-091-cbdbec3a3 is missing falsification criteria",
    ) as exc_info:
        result_package_v2._hypotheses(
            {"candidates": [{"candidateId": "hyp-portfolio-1"}]},
            team_id="research-team",
            question_id="SCI-091",
            dimension_payload={"reviewRoundId": "hround-1"},
        )

    assert exc_info.value.code == "challenge_v2_authority_missing"


def test_hypotheses_fail_closed_without_review_round_reference(monkeypatch) -> None:
    with pytest.raises(
        result_package_v2.ResultPackageV2Error,
        match="reviewRoundId",
    ):
        result_package_v2._hypotheses(
            {"candidates": [{"candidateId": "hyp-portfolio-1"}]},
            team_id="research-team",
            question_id="SCI-091",
            dimension_payload={},
        )


# ------------------------------------ A04: revisionEnvelope final-version binding

_R2_ROW_SELECTED = {
    "candidateId": "sci-091-cbdbec3a3",
    "claim": "REVISED claim: coherence traffic, not raw erase cost, bounds the rate.",
    "testablePrediction": "REVISED prediction: ops/s tracks P_cool/(N_e*E_e).",
    "falsifier": "REVISED falsifier: sustained ops/s with no cooling headroom.",
    "axisProfile": {
        "mechanism": "REVISED mechanism: coherence traffic dominates.",
        "boundary": "REVISED boundary: fixed cooling budget.",
    },
    "lineageRefs": ["candidate-2026-e9"],
}


def _canonical_revision_hash(rows: list[dict[str, Any]]) -> str:
    from core.web.services.team_workflow import hypothesis_review_executor

    return hypothesis_review_executor._stable_hash(
        hypothesis_review_executor.canonical_hypothesis_revision_snapshot(rows)
    )


def _round_revision_envelope(
    *,
    parent_id: str,
    rows: list[dict[str, Any]],
    output_hash: str | None = None,
) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "phase": "review_revision",
        "parentCandidateId": parent_id,
        "revisionReceiptRef": "revision-receipt-1",
        "revision": {
            "changes": ["收窄适用边界"],
            "unresolvedIssues": [],
            "status": "completed",
            "actual": True,
            "outputHash": output_hash or _canonical_revision_hash(rows),
            "output": {"candidates": rows},
        },
    }


def _r2_envelope_round_extra() -> dict[str, Any]:
    sibling = _round_candidate(candidateId="sci-091-cf0889b0d")
    rows = [
        dict(_R2_ROW_SELECTED),
        {
            "candidateId": sibling["candidateId"],
            "claim": sibling["claim"],
        },
    ]
    return {
        "revisionEnvelope": _round_revision_envelope(
            parent_id="sci-091-cbdbec3a3", rows=rows
        )
    }


def test_hypotheses_bind_revision_envelope_r2_as_final_version(monkeypatch) -> None:
    _patch_hypothesis_authorities(
        monkeypatch,
        [_round_candidate(), _round_candidate(candidateId="sci-091-cf0889b0d")],
        [
            _chain_candidate(),
            _chain_candidate(candidateId="sci-091-cf0889b0d"),
        ],
        round_extra=_r2_envelope_round_extra(),
    )
    hypotheses = result_package_v2._hypotheses(
        {"candidates": [{"candidateId": "hyp-portfolio-1", "claim": "portfolio"}]},
        team_id="research-team",
        question_id="SCI-091",
        dimension_payload={"reviewRoundId": "hround-1"},
    )

    final = hypotheses[0]
    assert final["statement"] == _R2_ROW_SELECTED["claim"]
    assert final["predictions"] == [_R2_ROW_SELECTED["testablePrediction"]]
    assert final["falsifiability"] == _R2_ROW_SELECTED["falsifier"]
    assert final["mechanism"] == _R2_ROW_SELECTED["axisProfile"]["mechanism"]
    assert final["boundary_conditions"] == [
        _R2_ROW_SELECTED["axisProfile"]["boundary"]
    ]
    assert final["supporting_evidence_refs"] == _R2_ROW_SELECTED["lineageRefs"]
    # The canonical revision snapshot excludes prose: the parent's novelty
    # statement stays the only persisted novelty basis.
    assert final["novelty_basis"] == (
        "Unlike constant-bound alternatives, the mechanism is separable and measurable."
    )
    # The unselected candidate keeps its R1/chain projection.
    other = hypotheses[1]
    assert other["statement"] == "Erase-cost and cooling jointly bound sustained processing rate."
    assert other["falsifiability"] == (
        "A peer-reviewed result showing sustained ops/s rising without better cooling."
    )


def test_hypotheses_bind_r2_over_candidate_details_fragment_content(monkeypatch) -> None:
    _patch_hypothesis_authorities(
        monkeypatch,
        [_round_candidate(), _round_candidate(candidateId="sci-091-cf0889b0d")],
        [],
        round_extra=_r2_envelope_round_extra(),
    )
    payload = {
        "portfolioId": "p1",
        "candidates": [
            {"candidateId": "sci-091-cbdbec3a3", "claim": "R1 old claim", "scores": {}},
            {
                "candidateId": "sci-091-cf0889b0d",
                "claim": "R1 old claim b",
                "scores": {},
            },
        ],
        "candidateDetails": {
            "sci-091-cbdbec3a3": {
                "statement": "fragment R1 statement a",
                "mechanism": "fragment mechanism a",
                "novelty_basis": "fragment novelty a",
                "predictions": ["fragment prediction a"],
                "falsificationCriteria": ["fragment criteria a"],
                "evidenceRefs": ["ev:1"],
                "counterEvidenceRefs": ["cev:1"],
                "boundary_conditions": ["fragment boundary a"],
            },
            "sci-091-cf0889b0d": {
                "statement": "fragment R1 statement b",
                "mechanism": "fragment mechanism b",
                "novelty_basis": "fragment novelty b",
                "predictions": ["fragment prediction b"],
                "falsificationCriteria": ["fragment criteria b"],
                "evidenceRefs": ["ev:2"],
                "counterEvidenceRefs": ["cev:2"],
                "boundary_conditions": ["fragment boundary b"],
            },
        },
    }
    hypotheses = result_package_v2._hypotheses(
        payload,
        team_id="research-team",
        question_id="SCI-091",
        dimension_payload={"reviewRoundId": "hround-1"},
    )

    # Both branches resolve the same hash-pinned R2 authority for the
    # revised candidate; the unselected candidate keeps its fragment content.
    assert hypotheses[0]["statement"] == _R2_ROW_SELECTED["claim"]
    assert hypotheses[0]["predictions"] == [_R2_ROW_SELECTED["testablePrediction"]]
    assert hypotheses[0]["falsifiability"] == _R2_ROW_SELECTED["falsifier"]
    assert hypotheses[1]["statement"] == "fragment R1 statement b"


def test_hypotheses_fail_closed_on_revision_envelope_hash_mismatch(monkeypatch) -> None:
    sibling = _round_candidate(candidateId="sci-091-cf0889b0d")
    rows = [
        dict(_R2_ROW_SELECTED),
        {"candidateId": sibling["candidateId"], "claim": sibling["claim"]},
    ]
    _patch_hypothesis_authorities(
        monkeypatch,
        [_round_candidate(), sibling],
        [_chain_candidate()],
        round_extra={
            "revisionEnvelope": _round_revision_envelope(
                parent_id="sci-091-cbdbec3a3", rows=rows, output_hash="0" * 64
            )
        },
    )

    with pytest.raises(
        result_package_v2.ResultPackageV2Error, match="outputHash"
    ) as exc_info:
        result_package_v2._hypotheses(
            {"candidates": [{"candidateId": "hyp-portfolio-1", "claim": "portfolio"}]},
            team_id="research-team",
            question_id="SCI-091",
            dimension_payload={"reviewRoundId": "hround-1"},
        )

    assert exc_info.value.code == "challenge_v2_feedback_conflict"


def test_hypotheses_fail_closed_when_r2_body_is_incomplete(monkeypatch) -> None:
    broken_r2 = {**_R2_ROW_SELECTED, "falsifier": ""}
    sibling = _round_candidate(candidateId="sci-091-cf0889b0d")
    rows = [
        dict(broken_r2),
        {"candidateId": sibling["candidateId"], "claim": sibling["claim"]},
    ]
    _patch_hypothesis_authorities(
        monkeypatch,
        [_round_candidate(), sibling],
        [_chain_candidate()],
        round_extra={
            "revisionEnvelope": _round_revision_envelope(
                parent_id="sci-091-cbdbec3a3", rows=rows
            )
        },
    )

    with pytest.raises(
        result_package_v2.ResultPackageV2Error,
        match="final revision \\(R2\\) is missing falsifier",
    ):
        result_package_v2._hypotheses(
            {"candidates": [{"candidateId": "hyp-portfolio-1", "claim": "portfolio"}]},
            team_id="research-team",
            question_id="SCI-091",
            dimension_payload={"reviewRoundId": "hround-1"},
        )


# ------------------------------------------------- stage-one research plan


def test_research_plan_projects_stage_one_proposal_plan() -> None:
    plan = result_package_v2._research_plan(
        {
            "objective": "Bound the question to measurable ops/s calibers.",
            "method": "Separate erasure cost from heat removal.",
            "work_packages": [
                {
                    "work_package_id": "wp-1",
                    "goal": "Settle the theoretical caliber split.",
                    "inputs": ["Is there an upper limit?"],
                    "procedure": ["Compare bound families."],
                    "outputs": ["wp-1 resolution"],
                    "dependencies": [],
                }
            ],
            "human_gate": {
                "required": True,
                "decision": "approved",
                "rationale": "Meta-review accepted; projection stays proposal-only.",
            },
            "proposal_only": True,
        }
    )

    assert plan["objective"] == "Bound the question to measurable ops/s calibers."
    assert plan["work_packages"][0]["work_package_id"] == "wp-1"
    assert plan["human_gate"]["decision"] == "approved"
    # Stage-two protocol sections are genuinely unplanned at stage one.
    for section in (
        "variables",
        "controls",
        "data_and_materials",
        "analysis",
        "success_criteria",
        "failure_criteria",
        "stop_conditions",
        "resources",
        "timeline",
        "risks",
    ):
        assert plan[section] == []


def test_research_plan_fails_closed_without_stage_one_plan_fields() -> None:
    with pytest.raises(
        result_package_v2.ResultPackageV2Error,
        match="research_plan.objective",
    ):
        result_package_v2._research_plan({"method": "Only method carried."})


# --------------------------------------------------------------- final summary


def test_final_summary_projects_canonical_sections() -> None:
    problem = {"scope": "Bounded to known physics and fixed energy budgets."}
    selection = {"selected_hypothesis_id": "sci-091-cbdbec3a3"}
    hypotheses = [
        {
            "hypothesis_id": "sci-091-cbdbec3a3",
            "statement": "Erase-cost and cooling jointly bound sustained processing rate.",
            "supporting_evidence_refs": ["candidate-2026-e1", "candidate-2026-e2"],
        }
    ]
    research_plan = {
        "objective": "Bound the question to measurable ops/s calibers.",
        "work_packages": [{"work_package_id": "wp-1", "goal": "Settle the caliber split."}],
    }
    dimension_payload = {"metaReview": {"riskNotes": "1) overhead quantification missing."}}
    evidence = [
        {"evidence_id": "ce-supports", "relation": "supports"},
        {"evidence_id": "ce-challenges", "relation": "challenges"},
    ]

    summary = result_package_v2._final_summary(
        problem=problem,
        selection=selection,
        hypotheses=hypotheses,
        research_plan=research_plan,
        dimension_payload=dimension_payload,
        evidence=evidence,
    )

    assert summary == {
        "answer_boundary": "Bounded to known physics and fixed energy budgets.",
        "selected_hypothesis": "Erase-cost and cooling jointly bound sustained processing rate.",
        "research_plan_summary": "Bound the question to measurable ops/s calibers.",
        "key_evidence_refs": ["candidate-2026-e1", "candidate-2026-e2"],
        "counterevidence_refs": ["ce-challenges"],
        "limitations": ["1) overhead quantification missing."],
        "next_validation_step": "Settle the caliber split.",
    }


def test_final_summary_fails_closed_without_selected_hypothesis() -> None:
    with pytest.raises(
        result_package_v2.ResultPackageV2Error,
        match="selection references sci-091-missing",
    ):
        result_package_v2._final_summary(
            problem={"scope": "Bounded."},
            selection={"selected_hypothesis_id": "sci-091-missing"},
            hypotheses=[{"hypothesis_id": "sci-091-cbdbec3a3", "statement": "s"}],
            research_plan={"objective": "o", "work_packages": [{"goal": "g"}]},
            dimension_payload={},
            evidence=[],
        )


# ------------------------------------------------------- competition result view


def test_competition_result_view_projects_stage_one_alignment(monkeypatch) -> None:
    artifacts = {
        "competition_alignment": {
            "competitionResultView": {
                "problem_statement": "Is there an upper limit to computer processing speed?",
                "rationale": "Scoped to measurable calibers.",
                "technical_details": "ops/s <= P_cool / (N_e * E_e + overhead).",
                "datasets": {"planned": [], "used": ["arxiv:1412.2166"]},
                "methods": ["Q1 caliber split"],
                "experiments": [],
                "results": ["not executed at stage one"],
                "references": [],
                "paper_title": "Stage-one research proposal",
                "paper_abstract": "The joint erase-cooling bound.",
            }
        }
    }
    monkeypatch.setattr(
        result_package_v2,
        "_artifact_payload",
        lambda kind, **_kwargs: deepcopy(artifacts[kind]),
    )

    view = result_package_v2._competition_result_view(
        team_id="research-team",
        workflow_run_id="run-sci-091",
        authority_run_id="source-sci-091",
    )

    assert view["datasets"] == {"source": ["arxiv:1412.2166"], "target": []}
    assert view["results"] == ["not executed at stage one"]
    assert view["paper_title"] == "Stage-one research proposal"


def test_competition_result_view_fails_closed_without_alignment(monkeypatch) -> None:
    monkeypatch.setattr(
        result_package_v2,
        "_artifact_payload",
        lambda kind, **_kwargs: {"artifactKind": kind},
    )

    with pytest.raises(
        result_package_v2.ResultPackageV2Error,
        match="competition_alignment is missing competition_result_view",
    ):
        result_package_v2._competition_result_view(
            team_id="research-team",
            workflow_run_id="run-sci-091",
            authority_run_id="source-sci-091",
        )


# ------------------------------------------------------ stage-one model route


def _proposal_only_record() -> dict:
    record = _record()
    record["inputSnapshot"]["constraintSnapshot"] = {"formalWrites": False}
    return record


def test_stage_one_model_route_projects_receipt_authority(monkeypatch) -> None:
    receipts = [
        {"provider": "dashscope_main", "model": "qwen3.8-flash", "status": "succeeded"},
        {"provider": "dashscope_main", "model": "qwen3.7-plus", "status": "succeeded"},
    ]
    monkeypatch.setattr(result_package_v2, "list_workflow_artifacts", lambda *_a, **_k: [])
    monkeypatch.setattr(
        result_package_v2,
        "question_model_invocation_receipt_refs",
        lambda *_a, **_k: [
            {"receiptId": "receipt-1", "outcomeKinds": ["candidate"], "nodeRunId": "n1"}
        ],
    )
    monkeypatch.setattr(
        result_package_v2,
        "question_model_invocation_receipts",
        lambda *_a, **_k: deepcopy(receipts),
    )

    run = result_package_v2._model_run(
        _proposal_only_record(),
        team_id="research-team",
        question_id="SCI-091",
        workflow_run_id="run-sci-091",
        authority_run_id="source-sci-091",
    )

    assert run["model_provider"] == "dashscope"
    assert run["model_id"] == "qwen3.7-plus+qwen3.8-flash"
    assert run["platform"] == "aliyun_bailian"


def test_stage_one_model_route_fails_closed_on_ambiguous_provider(monkeypatch) -> None:
    receipts = [
        {"provider": "dashscope_main", "model": "qwen3.8-flash", "status": "succeeded"},
        {"provider": "opencode_go", "model": "deepseek-v4", "status": "succeeded"},
    ]
    monkeypatch.setattr(result_package_v2, "list_workflow_artifacts", lambda *_a, **_k: [])
    monkeypatch.setattr(
        result_package_v2,
        "question_model_invocation_receipt_refs",
        lambda *_a, **_k: [
            {"receiptId": "receipt-1", "outcomeKinds": ["candidate"], "nodeRunId": "n1"}
        ],
    )
    monkeypatch.setattr(
        result_package_v2,
        "question_model_invocation_receipts",
        lambda *_a, **_k: deepcopy(receipts),
    )

    with pytest.raises(
        result_package_v2.ResultPackageV2Error,
        match="unique model provider",
    ) as exc_info:
        result_package_v2._model_run(
            _proposal_only_record(),
            team_id="research-team",
            question_id="SCI-091",
            workflow_run_id="run-sci-091",
            authority_run_id="source-sci-091",
        )

    assert exc_info.value.code == "challenge_v2_model_route_missing"


def test_stage_one_model_route_fails_closed_without_receipts(monkeypatch) -> None:
    monkeypatch.setattr(result_package_v2, "list_workflow_artifacts", lambda *_a, **_k: [])
    monkeypatch.setattr(
        result_package_v2,
        "question_model_invocation_receipt_refs",
        lambda *_a, **_k: [],
    )

    with pytest.raises(
        result_package_v2.ResultPackageV2Error,
        match="no registered model invocation receipts",
    ):
        result_package_v2._model_run(
            _proposal_only_record(),
            team_id="research-team",
            question_id="SCI-091",
            workflow_run_id="run-sci-091",
            authority_run_id="source-sci-091",
        )


# ----------------------------- end-to-end stage-one accepted-round build


@pytest.mark.parametrize("wrong_plan_run", [False, True])
def test_v2_build_projects_full_stage_one_authority_end_to_end(
    monkeypatch, tmp_path, wrong_plan_run
) -> None:
    expected = _authority_sections()[0]
    artifacts = {
        "problem_understanding": {
            "scope": "Bounded to known physics with measurable ops/s calibers.",
            "subquestions": ["Q1 caliber split"],
            "assumptions": ["Computation is physical."],
            "known_unknowns": ["Quantified baselines are unverified."],
            "human_gate": {
                "required": True,
                "decision": "pending",
                "rationale": "Awaiting scope confirmation.",
            },
        },
        "source_candidate_batch": {"candidates": []},
        "evidence_card_batch": {"evidence": deepcopy(expected["evidence"])},
        "hypothesis_set": {
            "candidates": [
                {"candidateId": "hyp-portfolio-1", "claim": "portfolio", "status": "draft"}
            ],
        },
        "dimension_reviews": {
            "reviewRoundId": "hround-1",
            # Round candidates replace the portfolio HYP-1/HYP-2 ids, so the
            # canonical seven-dimension coverage must follow the accepted
            # round candidate ids.
            "dimensionReviews": [
                {
                    **deepcopy(item),
                    "hypothesis_id": (
                        "sci-091-cbdbec3a3"
                        if item["hypothesis_id"] == "HYP-1"
                        else "sci-091-cf0889b0d"
                    ),
                }
                for item in expected["dimension_reviews"]
            ],
            "selection": {
                "selected_hypothesis_id": "sci-091-cbdbec3a3",
                "comparison_method": "multi_dimension_pareto_plus_human_decision",
                "tradeoffs": ["MetaReview rationale."],
                "rejected_hypotheses": [],
                "human_gate": {
                    "required": True,
                    "decision": "pending",
                    "rationale": "Awaiting confirmation.",
                },
            },
            "metaReview": {
                "accepted": True,
                "recommendationCandidateId": "sci-091-cbdbec3a3",
                "riskNotes": "Overhead quantification is missing.",
            },
        },
        "stage1_research_plan": {
            "objective": "Bound the question to measurable ops/s calibers.",
            "method": "Separate erasure cost from heat removal.",
            "work_packages": [
                {
                    "work_package_id": "wp-1",
                    "goal": "Settle the theoretical caliber split.",
                    "inputs": ["Is there an upper limit?"],
                    "procedure": ["Compare bound families."],
                    "outputs": ["wp-1 resolution"],
                    "dependencies": [],
                }
            ],
            "human_gate": {
                "required": True,
                "decision": "approved",
                "rationale": "Meta-review accepted.",
            },
        },
        "competition_alignment": {
            "competitionResultView": {
                "problem_statement": "Is there an upper limit to computer processing speed?",
                "rationale": "Scoped to measurable calibers.",
                "technical_details": "ops/s <= P_cool / (N_e * E_e + overhead).",
                "datasets": {"planned": [], "used": []},
                "methods": ["Q1 caliber split"],
                "experiments": [],
                "results": ["not executed at stage one"],
                "references": [],
                "paper_title": "Stage-one research proposal",
                "paper_abstract": "The joint erase-cooling bound.",
            }
        },
    }
    from core.web.services.team_workflow.research_runtime import workflow_artifact_store

    monkeypatch.setattr(workflow_artifact_store, "_root", lambda: tmp_path)
    monkeypatch.setattr(
        workflow_artifact_store, "resolve_project_workspace_home", lambda _root: tmp_path
    )
    for kind, payload in artifacts.items():
        if kind in {"source_candidate_batch", "evidence_card_batch"}:
            continue
        workflow_artifact_store.put_workflow_artifact(
            "research-team", kind=kind,
            workflow_run_id=(
                "run-other" if wrong_plan_run and kind == "stage1_research_plan"
                else "run-sci-096"
            ),
            source_collection_run_id="source-sci-096", payload=payload,
            artifact_identity=f"test:{kind}",
        )
    canonical_reader = result_package_v2._artifact_payload

    def read_artifact(kind, **kwargs):
        if kind in {"source_candidate_batch", "evidence_card_batch"}:
            return deepcopy(artifacts[kind])
        return canonical_reader(kind, **kwargs)

    monkeypatch.setattr(result_package_v2, "_artifact_payload", read_artifact)
    monkeypatch.setattr(
        result_package_v2,
        "_feedback_iterations",
        lambda **_kwargs: deepcopy(expected["feedback_iterations"]),
    )
    monkeypatch.setattr(
        result_package_v2,
        "_model_run",
        lambda *_a, **_k: {
            **deepcopy(expected["run"]),
            "run_id": "run-sci-096",
        },
    )
    _patch_hypothesis_authorities(
        monkeypatch,
        [_round_candidate(), _round_candidate(candidateId="sci-091-cf0889b0d")],
        [
            _chain_candidate(),
            _chain_candidate(candidateId="sci-091-cf0889b0d"),
        ],
    )

    record = _record()
    record["inputSnapshot"]["constraintSnapshot"] = {"formalWrites": False}
    # A protocol plan cannot substitute for the current stage-one authority.
    workflow_artifact_store.put_workflow_artifact(
        "research-team", kind="research_plan", workflow_run_id="run-sci-096",
        source_collection_run_id="source-sci-096",
        payload={"researchPlan": deepcopy(expected["research_plan"])},
        artifact_identity="test:protocol-plan",
    )
    with (
        pytest.raises(result_package_v2.ResultPackageV2Error, match="stage1_research_plan")
        if wrong_plan_run else nullcontext()
    ):
        package = result_package_v2.build_challenge_result_package_v2(
            generic_package={"runId": "run-sci-096", "factChainHash": "f" * 64},
            record=record,
            team_id="research-team",
            workflow_run_id="run-sci-096",
            source_collection_run_id="source-sci-096",
        )
    if wrong_plan_run:
        return
    output = package["challengeQuestionOutput"]

    assert challenge_question_runs._schema_issues(output) == []
    assert challenge_question_runs._semantic_validation(output)["status"] == "passed"
    assert [item["hypothesis_id"] for item in output["hypotheses"]] == [
        "sci-091-cbdbec3a3",
        "sci-091-cf0889b0d",
    ]
    assert output["hypotheses"][0]["falsifiability"].startswith("A peer-reviewed result")
    final_summary = output["result_classification"]["final_summary"]
    assert final_summary["selected_hypothesis"] == (
        "Erase-cost and cooling jointly bound sustained processing rate."
    )
    assert final_summary["limitations"] == ["Overhead quantification is missing."]
    assert output["competition_result_view"]["datasets"] == {"source": [], "target": []}
    assert output["research_plan"]["work_packages"][0]["work_package_id"] == "wp-1"


# ----------------------------- review-cited multi-run evidence aggregation


def _canonical_batch_ref(run_id: str, digest: str) -> str:
    return f"evidence_card_batch://research-team/{run_id}/{digest * 64}"


def _aggregation_dimension_artifact(cited_refs: list[str]) -> dict:
    expected, _ = _authority_sections()
    return {
        "dimensionReviews": [
            {**deepcopy(row), "evidence_refs": list(cited_refs)}
            for row in expected["dimension_reviews"]
        ]
    }


def _patch_registry_cards(
    monkeypatch,
    cards_by_run: dict[str, list[dict]],
    candidates_by_run: dict[str, list[dict]] | None = None,
) -> list[str]:
    """Strict-scoped per-run loader stand-in; returns the run read log."""

    calls: list[str] = []
    candidates_by_run = candidates_by_run or {}

    def read_scoped(kind, *, team_id, authority_run_id, **_kwargs):
        calls.append(authority_run_id)
        if kind == "source_candidate_batch":
            candidates = candidates_by_run.get(authority_run_id)
            if not candidates:
                return None
            return {
                "teamId": team_id,
                "sourceCollectionRunId": authority_run_id,
                "candidates": deepcopy(candidates),
                "candidateCount": len(candidates),
            }
        assert kind == "evidence_card_batch"
        cards = cards_by_run.get(authority_run_id)
        if not cards:
            return None
        return {
            "teamId": team_id,
            "sourceCollectionRunId": authority_run_id,
            "evidenceCards": deepcopy(cards),
            "cardCount": len(cards),
        }

    monkeypatch.setattr(result_package_v2, "load_scoped_artifact_payload", read_scoped)
    return calls


def _aggregation_artifacts() -> tuple[dict, dict[str, dict]]:
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
    return expected, artifacts


def _build_v2_with_aggregation(
    monkeypatch,
    artifacts: dict[str, dict],
    cards_by_run: dict[str, list[dict]],
    candidates_by_run: dict[str, list[dict]] | None = None,
) -> tuple[dict, list[str]]:
    expected = _authority_sections()[0]

    def read_artifact(kind, **_kwargs):
        if kind not in artifacts:
            raise result_package_v2.ResultPackageV2Error(
                f"canonical artifact is missing: {kind}"
            )
        return deepcopy(artifacts[kind])

    monkeypatch.setattr(result_package_v2, "_artifact_payload", read_artifact)
    registry_calls = _patch_registry_cards(
        monkeypatch, cards_by_run, candidates_by_run
    )
    monkeypatch.setattr(
        result_package_v2,
        "_feedback_iterations",
        lambda **_kwargs: deepcopy(expected["feedback_iterations"]),
    )
    monkeypatch.setattr(
        result_package_v2,
        "_model_run",
        lambda *_a, **_k: {**deepcopy(expected["run"]), "run_id": "run-sci-096"},
    )
    package = result_package_v2.build_challenge_result_package_v2(
        generic_package={"runId": "run-sci-096", "factChainHash": "f" * 64},
        record=_record(),
        team_id="research-team",
        workflow_run_id="run-sci-096",
        source_collection_run_id="source-sci-096",
    )
    return package, registry_calls


def test_cited_evidence_run_ids_keep_sorted_unique_card_batch_refs() -> None:
    payload = {
        "dimensionReviews": [
            {
                "evidence_refs": [
                    _canonical_batch_ref("dprun-run-b", "b"),
                    "candidate-chat-citation",
                    f"research_plan://research-team/run-x/{'c' * 64}",
                ]
            },
            {"evidenceRefs": [_canonical_batch_ref("dprun-run-a", "a")]},
        ],
        "candidates": [
            {
                "dimensionReviews": [
                    {
                        "evidence_refs": [
                            _canonical_batch_ref("dprun-run-b", "b"),
                            "not a canonical ref",
                        ]
                    }
                ]
            }
        ],
    }

    assert result_package_v2._cited_evidence_run_ids(payload) == [
        "dprun-run-a",
        "dprun-run-b",
    ]


def test_aggregated_payload_merges_cited_runs_and_dedupes_card_ids(monkeypatch) -> None:
    shared_card = _claim_evidence_card(
        claimEvidenceId="ce-shared",
        candidateId="candidate-1",
        quote="Shared duplicated anchor.",
    )
    _patch_registry_cards(
        monkeypatch,
        {
            "dprun-run-b": [
                _claim_evidence_card(
                    claimEvidenceId="ce-b-challenges",
                    candidateId="candidate-2",
                    quote="Counter anchor.",
                    supportLevel="contradicts",
                ),
                shared_card,
            ],
            # A cited run without cards contributes nothing.
            "dprun-run-empty": [],
            "dprun-run-a": [
                _claim_evidence_card(claimEvidenceId="ce-a-supports"),
                shared_card,
            ],
        },
    )

    payload = result_package_v2._aggregated_evidence_card_payload(
        team_id="research-team",
        cited_run_ids=["dprun-run-a", "dprun-run-b", "dprun-run-empty"],
    )

    assert payload == {
        "teamId": "research-team",
        "sourceCollectionRunIds": ["dprun-run-a", "dprun-run-b"],
        "evidenceCards": [
            _claim_evidence_card(claimEvidenceId="ce-a-supports"),
            shared_card,
            _claim_evidence_card(
                claimEvidenceId="ce-b-challenges",
                candidateId="candidate-2",
                quote="Counter anchor.",
                supportLevel="contradicts",
            ),
        ],
        "cardCount": 3,
        "aggregatedFromDimensionReviews": True,
    }
    assert result_package_v2._aggregated_evidence_card_payload(
        team_id="research-team",
        cited_run_ids=["dprun-run-empty"],
    ) is None


def test_evidence_card_payload_layers_aggregation_only_after_missing(
    monkeypatch,
) -> None:
    dimension_payload = _aggregation_dimension_artifact(
        [_canonical_batch_ref("dprun-run-a", "a")]
    )
    first_layer = {
        "teamId": "research-team",
        "sourceCollectionRunId": "source-sci-096",
        "evidenceCards": [_claim_evidence_card()],
        "cardCount": 1,
    }
    monkeypatch.setattr(
        result_package_v2,
        "_artifact_payload",
        lambda kind, **_kwargs: deepcopy(first_layer),
    )
    registry_calls = _patch_registry_cards(
        monkeypatch, {"dprun-run-a": [_claim_evidence_card()]}
    )

    # Layer one holds: the aggregation loader is never consulted.
    payload = result_package_v2._evidence_card_payload(
        team_id="research-team",
        workflow_run_id="run-sci-096",
        authority_run_id="source-sci-096",
        dimension_payload=dimension_payload,
    )
    assert payload == first_layer
    assert registry_calls == []

    # Layer one missing: the review-cited aggregation reads the cited run.
    def missing_evidence(kind, **_kwargs):
        raise result_package_v2.ResultPackageV2Error(
            f"canonical artifact is missing: {kind}"
        )

    monkeypatch.setattr(result_package_v2, "_artifact_payload", missing_evidence)
    aggregated = result_package_v2._evidence_card_payload(
        team_id="research-team",
        workflow_run_id="run-sci-096",
        authority_run_id="source-sci-096",
        dimension_payload=dimension_payload,
    )
    assert aggregated["aggregatedFromDimensionReviews"] is True
    assert aggregated["sourceCollectionRunIds"] == ["dprun-run-a"]
    assert aggregated["cardCount"] == 1

    # Nothing aggregatable either: the original fail-closed error stands.
    with pytest.raises(
        result_package_v2.ResultPackageV2Error,
        match="^canonical artifact is missing: evidence_card_batch$",
    ) as exc_info:
        result_package_v2._evidence_card_payload(
            team_id="research-team",
            workflow_run_id="run-sci-096",
            authority_run_id="source-sci-096",
            dimension_payload={"dimensionReviews": [{"evidence_refs": ["E1"]}]},
        )
    assert str(exc_info.value) == "canonical artifact is missing: evidence_card_batch"

    # An empty layer-one payload also falls through to the aggregation, and
    # keeps the original payload (and its own fail-closed error) when the
    # aggregation finds nothing.
    monkeypatch.setattr(
        result_package_v2,
        "_artifact_payload",
        lambda kind, **_kwargs: {"evidence": []},
    )
    empty_fallback = result_package_v2._evidence_card_payload(
        team_id="research-team",
        workflow_run_id="run-sci-096",
        authority_run_id="source-sci-096",
        dimension_payload=dimension_payload,
    )
    assert empty_fallback["aggregatedFromDimensionReviews"] is True
    no_cited_fallback = result_package_v2._evidence_card_payload(
        team_id="research-team",
        workflow_run_id="run-sci-096",
        authority_run_id="source-sci-096",
        dimension_payload={"dimensionReviews": [{"evidence_refs": ["E1"]}]},
    )
    assert no_cited_fallback == {"evidence": []}


def test_v2_build_aggregates_review_cited_evidence_batches(
    monkeypatch,
) -> None:
    """Production SCI-009 shape: the authority run holds no card batch.

    The cards were accumulated across later collection runs, and the
    dimension reviews cite exactly those runs' canonical batch refs.
    """

    _, artifacts = _aggregation_artifacts()
    artifacts["dimension_reviews"] = _aggregation_dimension_artifact(
        [
            _canonical_batch_ref("dprun-run-b", "b"),
            _canonical_batch_ref("dprun-run-a", "a"),
        ]
    )
    del artifacts["evidence_card_batch"]
    cards_by_run = {
        "dprun-run-a": [
            _claim_evidence_card(claimEvidenceId="ce-a-supports"),
            _claim_evidence_card(
                claimEvidenceId="ce-shared",
                quote="Shared duplicated anchor.",
            ),
        ],
        "dprun-run-b": [
            _claim_evidence_card(
                claimEvidenceId="ce-b-challenges",
                candidateId="candidate-2",
                quote="Counter anchor.",
                supportLevel="contradicts",
            ),
            _claim_evidence_card(
                claimEvidenceId="ce-shared",
                quote="Shared duplicated anchor.",
            ),
        ],
    }

    package, registry_calls = _build_v2_with_aggregation(
        monkeypatch, artifacts, cards_by_run
    )
    output = package["challengeQuestionOutput"]

    assert registry_calls == ["dprun-run-a", "dprun-run-b"]
    assert challenge_question_runs._schema_issues(output) == []
    evidence_ids = [item["evidence_id"] for item in output["evidence"]]
    # Cross-run duplicate claimEvidenceId collapses into one evidence row.
    assert sorted(evidence_ids) == ["ce-a-supports", "ce-b-challenges", "ce-shared"]
    assert evidence_ids.index("ce-shared") < evidence_ids.index("ce-b-challenges")
    evidence = {item["evidence_id"]: item for item in output["evidence"]}
    assert evidence["ce-b-challenges"]["relation"] == "challenges"
    assert evidence["ce-a-supports"]["source_type"] == "peer_reviewed_paper"
    checks = {item["evidenceId"]: item for item in package["citationChecks"]}
    assert set(checks) == set(evidence_ids)


def test_v2_single_run_authority_batch_never_invokes_aggregation(monkeypatch) -> None:
    """SCI-091 shape: an authority-run batch is read exactly as before."""

    _, artifacts = _claim_evidence_artifacts([_claim_evidence_card()])
    registry_calls = _patch_registry_cards(monkeypatch, {})

    package = _build_v2_with_artifacts(monkeypatch, artifacts)
    output = package["challengeQuestionOutput"]

    assert challenge_question_runs._schema_issues(output) == []
    assert [item["evidence_id"] for item in output["evidence"]] == ["ce-anchor"]
    assert registry_calls == []


def _hypothesis_role_card(**overrides: Any) -> dict[str, Any]:
    """Stored claim-evidence card bound to a hypothesis candidate id.

    Mirrors the production hypothesis-first store: hypothesis-role cards are
    registered under the hypothesis candidate id, a space disjoint from the
    ``candidate-<ts>-<hex>`` source ids, and the hypothesis_set authority has
    no source metadata — so the collection-stage v2 envelope fields travel on
    the card itself (the projection contract reads card fields first).
    """
    card = {
        "schemaVersion": 1,
        "claimEvidenceId": "ce-hypothesis",
        "claimId": "claim-h1",
        "candidateId": "sci-096-cbf2d69301",
        "sourceId": "https://doi.org/10.1103/PhysRevLett.88.237901",
        "locator": {
            "kind": "citation",
            "anchor": "abstract",
            "url": "https://doi.org/10.1103/PhysRevLett.88.237901",
        },
        "quote": "The universe performs at most 10^120 operations on 10^90 bits.",
        "evidenceKind": "primary_result",
        "reasoningRole": "hypothesis",
        "supportLevel": "supports",
        "reviewStatus": "pending",
        "sourceCollectionRunId": "dprun-run-a",
        "title": "Computational Capacity of the Universe",
        "sourceType": "peer_reviewed_paper",
        "sourceUrl": "https://doi.org/10.1103/PhysRevLett.88.237901",
        "retrievedAt": "2026-09-02T17:14:45Z",
    }
    card.update(overrides)
    return card


def test_v2_aggregated_cards_resolve_hypothesis_level_candidates(
    monkeypatch,
) -> None:
    """Production-shape mirror: two authorities must both be honored.

    The candidates payload carries only source-level ids while the aggregated
    cards cite hypothesis-level ids; the hypothesis_set authority names those
    ids, so the orphan gate passes on real identity instead of loosening.
    """

    _, artifacts = _aggregation_artifacts()
    artifacts["source_candidate_batch"] = {
        "candidates": [
            {
                "candidateId": "candidate-1",
                "title": "Computational Capacity of the Universe",
                "sourceKind": "paper",
                "sourceUrl": "https://doi.org/10.1103/PhysRevLett.88.237901",
                "retrievedAt": "2026-09-02T17:14:45Z",
            }
        ]
    }
    artifacts["hypothesis_set"] = {
        **artifacts["hypothesis_set"],
        "candidates": [
            {
                "candidateId": "sci-096-cbf2d69301",
                "claim": "Erase-cost and cooling jointly bound processing.",
                "status": "reviewed",
            }
        ],
    }
    artifacts["dimension_reviews"] = _aggregation_dimension_artifact(
        [
            _canonical_batch_ref("dprun-run-a", "a"),
            _canonical_batch_ref("dprun-run-b", "b"),
        ]
    )
    del artifacts["evidence_card_batch"]
    cards_by_run = {
        "dprun-run-a": [
            _hypothesis_role_card(claimEvidenceId="ce-hypo-a"),
        ],
        "dprun-run-b": [
            _hypothesis_role_card(
                claimEvidenceId="ce-hypo-b",
                quote="Cooling capacity bounds sustained throughput.",
                supportLevel="contradicts",
                sourceCollectionRunId="dprun-run-b",
            ),
        ],
    }

    package, _ = _build_v2_with_aggregation(monkeypatch, artifacts, cards_by_run)
    output = package["challengeQuestionOutput"]

    assert challenge_question_runs._schema_issues(output) == []
    evidence = {item["evidence_id"]: item for item in output["evidence"]}
    assert set(evidence) == {"ce-hypo-a", "ce-hypo-b"}
    # Card-carried envelope fields project verbatim; pending review keeps the
    # fail-closed verification floor even though the candidate is hypothesis
    # level and has no source-screening authority.
    assert evidence["ce-hypo-a"]["fact"] == (
        "The universe performs at most 10^120 operations on 10^90 bits."
    )
    assert evidence["ce-hypo-a"]["verification_status"] == "unverified"
    assert evidence["ce-hypo-b"]["relation"] == "challenges"
    assert evidence["ce-hypo-a"]["source_type"] == "peer_reviewed_paper"


def test_v2_aggregated_card_with_unknown_candidate_fails_closed(monkeypatch) -> None:
    _, artifacts = _aggregation_artifacts()
    artifacts["dimension_reviews"] = _aggregation_dimension_artifact(
        [_canonical_batch_ref("dprun-run-a", "a")]
    )
    del artifacts["evidence_card_batch"]
    cards_by_run = {
        "dprun-run-a": [
            _hypothesis_role_card(
                claimEvidenceId="ce-orphan",
                candidateId="sci-096-nosuchcandidate",
            ),
        ],
    }

    with pytest.raises(
        result_package_v2.ResultPackageV2Error,
        match="ce-orphan references candidate sci-096-nosuchcandidate "
        "missing from source_candidate_batch",
    ):
        _build_v2_with_aggregation(monkeypatch, artifacts, cards_by_run)


# ------------------------------------------------- lean card envelope projection


def _lean_production_card(**overrides: Any) -> dict[str, Any]:
    """Live-data lean claim-evidence card: no candidateId, no v2 envelope.

    Live verification of the hypothesis-first store found cards carrying only
    ``quote`` / ``sourceId`` (a DOI URL) / a ``kind: "url"`` locator / store
    timestamps / ``evidenceKind`` / ``supportLevel`` — so every envelope field
    the strict evidence projection requires must come from a real authority or
    the build fails closed.
    """
    card = {
        "schemaVersion": 1,
        "claimEvidenceId": "ce-lean-doi",
        "claimId": "claim-h1",
        "sourceId": "https://doi.org/10.1126/science.adr3837",
        "locator": {
            "kind": "url",
            "url": "https://doi.org/10.1126/science.adr3837",
        },
        "quote": "Global plastic waste mismanagement can be cut sharply by 2050.",
        "evidenceKind": "primary_result",
        "supportLevel": "supports",
        "reviewStatus": "pending",
        "createdAt": "2026-09-08T12:30:15.000000+00:00",
        "updatedAt": "2026-09-08T13:05:00.000000+00:00",
    }
    card.update(overrides)
    return card


def _source_manifest_candidate(**overrides: Any) -> dict[str, Any]:
    """Production candidate-store record behind a DOI-shaped lean card.

    Live shape: ``candidateType == "source_manifest"`` with the display title
    and the DOI at top level (``sourceUrl``); some store generations keep both
    under ``metadata`` instead.
    """
    candidate = {
        "candidateId": "candidate-plastic",
        "candidateType": "source_manifest",
        "title": "Pathways to reduce global plastic waste mismanagement",
        "sourceUrl": "https://doi.org/10.1126/science.adr3837",
        "sourceType": "paper",
        "sourceKind": "paper",
        "createdAt": "2026-09-08T12:30:15.000000+00:00",
    }
    candidate.update(overrides)
    return candidate


def _patch_project_candidate_store(
    monkeypatch, tmp_path: Path, records: list[dict] | None
) -> Path:
    """Point the project candidate-store index at a temp workspace.

    Writes ``candidate_store/index.json`` under the workspace root the
    resolver returns; ``records=None`` leaves the store file absent so the
    index comes back empty and the cards keep failing closed.
    """

    if records is not None:
        store_dir = tmp_path / "candidate_store"
        store_dir.mkdir(parents=True)
        (store_dir / "index.json").write_text(
            json.dumps({"candidates": records}), encoding="utf-8"
        )
    monkeypatch.setattr(
        result_package_v2,
        "resolve_research_project_workspace_root",
        lambda team_id, project_id: tmp_path,
    )
    return tmp_path


def test_v2_aggregated_lean_cards_project_envelope_from_project_store(
    monkeypatch, tmp_path
) -> None:
    """Lean DOI cards resolve title/source_url/retrieved_at/source_type.

    The aggregated cards carry no candidateId, so their envelope fields are
    projected only from authorities they already carry: the url locator, the
    store timestamps, and the run owner project's candidate store, which
    resolves the URL-shaped sourceId (title and kind) even when the matching
    record sits on an earlier collection run the reviews never cite.
    """

    _, artifacts = _aggregation_artifacts()
    artifacts["dimension_reviews"] = _aggregation_dimension_artifact(
        [_canonical_batch_ref("dprun-run-a", "a")]
    )
    del artifacts["evidence_card_batch"]
    # Production mirror: the flagship DOI's source_manifest record is scoped
    # to an earlier collection run the dimension reviews never cite — only
    # the project-wide store carries it (top-level sourceKind 'paper').
    earlier_run_record = {
        **_source_manifest_candidate(),
        "sourceCollectionRunId": "dprun-20260908122518684731-earlier",
    }
    metadata_candidate = {
        "candidateId": "candidate-nature",
        "candidateType": "source_manifest",
        "metadata": {
            "title": "Cooling capacity bounds for computation",
            "sourceUrl": "https://doi.org/10.1038/s41586-025-09361-0",
        },
        "createdAt": "2026-09-08T12:30:15.000000+00:00",
    }
    _patch_project_candidate_store(
        monkeypatch, tmp_path, [earlier_run_record, metadata_candidate]
    )
    cards_by_run = {
        "dprun-run-a": [
            _lean_production_card(),
            _lean_production_card(
                claimEvidenceId="ce-lean-nature",
                sourceId="https://doi.org/10.1038/s41586-025-09361-0",
                locator={
                    "kind": "url",
                    "url": "https://doi.org/10.1038/s41586-025-09361-0",
                },
                quote="Cooling capacity bounds sustained throughput.",
            ),
        ],
    }

    package, registry_calls = _build_v2_with_aggregation(
        monkeypatch, artifacts, cards_by_run
    )
    output = package["challengeQuestionOutput"]

    assert challenge_question_runs._schema_issues(output) == []
    # Only the evidence batch is read through the strict scoped loader; the
    # title/kind index deliberately bypasses it for the project store.
    assert registry_calls == ["dprun-run-a"]
    evidence = {item["evidence_id"]: item for item in output["evidence"]}
    assert set(evidence) == {"ce-lean-doi", "ce-lean-nature"}
    plastic = evidence["ce-lean-doi"]
    assert plastic["title"] == "Pathways to reduce global plastic waste mismanagement"
    assert plastic["source_url"] == "https://doi.org/10.1126/science.adr3837"
    assert plastic["retrieved_at"] == "2026-09-08T13:05:00.000000+00:00"
    # The URL-matched production candidate is a screened paper: its sourceKind
    # maps through the existing vocabulary onto the real schema enum value,
    # not the 'other' umbrella.
    assert plastic["source_type"] == "peer_reviewed_paper"
    assert plastic["fact"] == (
        "Global plastic waste mismanagement can be cut sharply by 2050."
    )
    assert plastic["relation"] == "supports"
    assert plastic["verification_status"] == "unverified"
    # metadata.sourceUrl / metadata.title resolve the same way; the kindless
    # metadata candidate has no recognizable kind, so the card falls back to
    # the evidence-kind vocabulary where 'primary_result' lands on the
    # schema's non-authoritative umbrella.
    nature = evidence["ce-lean-nature"]
    assert nature["title"] == "Cooling capacity bounds for computation"
    assert nature["source_url"] == "https://doi.org/10.1038/s41586-025-09361-0"
    assert nature["retrieved_at"] == "2026-09-08T13:05:00.000000+00:00"
    assert nature["source_type"] == "other"
    checks = {item["evidenceId"] for item in package["citationChecks"]}
    assert checks == set(evidence)


def test_v2_aggregated_lean_card_unresolvable_stays_fail_closed(
    monkeypatch, tmp_path
) -> None:
    """Truthful only: unresolvable title or non-url locator keeps failing."""

    _, artifacts = _aggregation_artifacts()
    artifacts["dimension_reviews"] = _aggregation_dimension_artifact(
        [_canonical_batch_ref("dprun-run-a", "a")]
    )
    del artifacts["evidence_card_batch"]
    _patch_project_candidate_store(
        monkeypatch, tmp_path, [_source_manifest_candidate()]
    )

    # A DOI the project store never collected: the title cannot be resolved
    # truthfully, so the strict producer raises instead of inventing.
    cards_by_run = {
        "dprun-run-a": [
            _lean_production_card(
                claimEvidenceId="ce-lean-unknown",
                sourceId="https://doi.org/10.1126/science.unknown",
                locator={
                    "kind": "url",
                    "url": "https://doi.org/10.1126/science.unknown",
                },
            ),
        ],
    }
    with pytest.raises(
        result_package_v2.ResultPackageV2Error,
        match="evidence.title",
    ):
        _build_v2_with_aggregation(monkeypatch, artifacts, cards_by_run)

    # A resolvable title still fails closed when the locator is not a url:
    # no source_url may be fabricated from a citation anchor.
    cards_by_run = {
        "dprun-run-a": [
            _lean_production_card(
                claimEvidenceId="ce-lean-citation",
                locator={
                    "kind": "citation",
                    "anchor": "abstract",
                    "url": "https://doi.org/10.1126/science.adr3837",
                },
            ),
        ],
    }
    with pytest.raises(
        result_package_v2.ResultPackageV2Error,
        match="evidence.source_url",
    ):
        _build_v2_with_aggregation(monkeypatch, artifacts, cards_by_run)

    # A project whose store file is missing yields an empty index — the lean
    # card then keeps the strict fail-closed raise instead of a guessed title.
    _patch_project_candidate_store(monkeypatch, tmp_path / "empty-workspace", None)
    cards_by_run = {
        "dprun-run-a": [_lean_production_card()],
    }
    with pytest.raises(
        result_package_v2.ResultPackageV2Error,
        match="evidence.title",
    ):
        _build_v2_with_aggregation(monkeypatch, artifacts, cards_by_run)


def test_v2_aggregated_candidate_id_cards_keep_id_authority_resolution(
    monkeypatch, tmp_path
) -> None:
    """Cards bound to a candidate id are never URL-projected.

    Even in a batch that also contains lean cards, a candidateId-bearing card
    is returned byte-identical from the aggregated payload and keeps the exact
    id-authority resolution — its title comes from the candidate store by id,
    never from the URL index.
    """

    _, artifacts = _aggregation_artifacts()
    artifacts["dimension_reviews"] = _aggregation_dimension_artifact(
        [_canonical_batch_ref("dprun-run-a", "a")]
    )
    del artifacts["evidence_card_batch"]
    id_bound_card = _claim_evidence_card(claimEvidenceId="ce-id-bound")
    cards_by_run = {
        "dprun-run-a": [
            id_bound_card,
            _lean_production_card(),
        ],
    }
    candidates_by_run = {
        "dprun-run-a": [
            _source_manifest_candidate(),
            {
                "candidateId": "candidate-1",
                "title": "Computational Capacity of the Universe",
                "sourceKind": "paper",
                "sourceUrl": "https://doi.org/10.1103/PhysRevLett.88.237901",
                "retrievedAt": "2026-09-02T17:14:45Z",
            },
        ],
    }

    # Payload level, no research project in scope: the cited runs' scoped
    # batches are the fallback index authority. The id-bound card is
    # byte-identical (no fields added) while the lean card next to it is
    # projected from the scoped candidates.
    registry_calls = _patch_registry_cards(
        monkeypatch, cards_by_run, candidates_by_run
    )
    payload = result_package_v2._aggregated_evidence_card_payload(
        team_id="research-team",
        cited_run_ids=["dprun-run-a"],
    )
    assert registry_calls == ["dprun-run-a", "dprun-run-a"]
    assert payload["evidenceCards"][0] == id_bound_card
    lean_projected = payload["evidenceCards"][1]
    assert lean_projected["title"] == "Pathways to reduce global plastic waste mismanagement"
    assert lean_projected["source_type"] == "peer_reviewed_paper"

    # Build level (frozen scope names the project, so the project store is
    # the index authority): the id-bound card still resolves through the
    # candidate id authority exactly as before the lean projection existed.
    _patch_project_candidate_store(
        monkeypatch, tmp_path, [_source_manifest_candidate()]
    )
    package, _ = _build_v2_with_aggregation(monkeypatch, artifacts, cards_by_run)
    output = package["challengeQuestionOutput"]
    assert challenge_question_runs._schema_issues(output) == []
    evidence = {item["evidence_id"]: item for item in output["evidence"]}
    assert set(evidence) == {"ce-id-bound", "ce-lean-doi"}
    assert evidence["ce-id-bound"]["title"] == "Computational Capacity of the Universe"
    assert evidence["ce-id-bound"]["source_type"] == "peer_reviewed_paper"
    assert evidence["ce-id-bound"]["retrieved_at"] == "2026-09-02T17:14:45Z"


def test_v2_single_run_authority_batch_applies_no_lean_projection(monkeypatch) -> None:
    """The lean projection belongs to the aggregation layer only.

    A lean card inside the authority run's own evidence batch is returned
    byte-identical, no cited-run store read ever happens, and the strict
    evidence projection still fails closed exactly as before.
    """

    lean_card = _lean_production_card()
    _, artifacts = _claim_evidence_artifacts([lean_card])
    monkeypatch.setattr(
        result_package_v2,
        "_artifact_payload",
        lambda kind, **_kwargs: deepcopy(artifacts[kind]),
    )
    registry_calls = _patch_registry_cards(monkeypatch, {})

    payload = result_package_v2._evidence_card_payload(
        team_id="research-team",
        workflow_run_id="run-sci-096",
        authority_run_id="source-sci-096",
        dimension_payload={"dimensionReviews": [{"evidence_refs": ["E1"]}]},
    )
    assert payload["evidenceCards"] == [lean_card]
    assert "source_url" not in payload["evidenceCards"][0]
    assert "retrieved_at" not in payload["evidenceCards"][0]
    assert registry_calls == []

    with pytest.raises(
        result_package_v2.ResultPackageV2Error,
        match="evidence.title",
    ):
        _build_v2_with_artifacts(monkeypatch, artifacts)
    assert registry_calls == []
