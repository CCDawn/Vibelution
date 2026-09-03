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


def _patch_hypothesis_authorities(monkeypatch, round_candidates, chain_candidates) -> None:
    from core.web.services.team_workflow import hypothesis_rounds
    from core.web.services.team_workflow.research_runtime import hypothesis_first_chain

    monkeypatch.setattr(
        hypothesis_rounds,
        "get_hypothesis_round",
        lambda team_id, round_id: {"teamId": team_id, "round": {"roundId": round_id, "candidates": round_candidates}},
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


def test_v2_build_projects_full_stage_one_authority_end_to_end(monkeypatch) -> None:
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
        "research_plan": {
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

    package = result_package_v2.build_challenge_result_package_v2(
        generic_package={"runId": "run-sci-096", "factChainHash": "f" * 64},
        record=_record(),
        team_id="research-team",
        workflow_run_id="run-sci-096",
        source_collection_run_id="source-sci-096",
    )
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
