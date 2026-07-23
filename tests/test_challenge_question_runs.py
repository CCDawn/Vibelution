from __future__ import annotations

from copy import deepcopy
import json

import pytest

from core.web.services.team_workflow import challenge_question_runs


def _gate(decision: str = "pending") -> dict:
    return {"required": True, "decision": decision, "rationale": "Awaiting or recording explicit human review."}


def _output(question_number: int = 96, *, approved: bool = False) -> dict:
    question_id = f"SCI-{question_number:03d}"
    catalog_question = challenge_question_runs._catalog_question(question_id)
    assert catalog_question is not None
    decision = "approved" if approved else "pending"
    human_status = "passed" if approved else "pending"
    status = "approved" if approved else "review_required"
    evidence = [
        {
            "evidence_id": "E1",
            "title": "Peer reviewed paper one",
            "source_type": "peer_reviewed_paper",
            "source_url": "https://example.org/paper-1",
            "retrieved_at": "2026-07-23T00:00:00Z",
            "fact": "A checked factual statement.",
            "relation": "supports",
            "verification_status": "metadata_checked",
        },
        {
            "evidence_id": "E2",
            "title": "Peer reviewed paper two",
            "source_type": "peer_reviewed_paper",
            "source_url": "https://example.org/paper-2",
            "retrieved_at": "2026-07-23T00:00:00Z",
            "fact": "A second checked factual statement.",
            "relation": "supports",
            "verification_status": "metadata_checked",
        },
        {
            "evidence_id": "E3",
            "title": "Official dataset",
            "source_type": "dataset",
            "source_url": "https://example.org/dataset",
            "retrieved_at": "2026-07-23T00:00:00Z",
            "fact": "A dataset is available for planned validation.",
            "relation": "method",
            "verification_status": "metadata_checked",
        },
        {
            "evidence_id": "E4",
            "title": "Boundary evidence",
            "source_type": "peer_reviewed_paper",
            "source_url": "https://example.org/boundary",
            "retrieved_at": "2026-07-23T00:00:00Z",
            "fact": "The proposed mechanism has a documented boundary.",
            "relation": "challenges",
            "verification_status": "metadata_checked",
        },
    ]
    hypotheses = [
        {
            "hypothesis_id": "HYP-1",
            "statement": "First falsifiable hypothesis.",
            "mechanism": "Mechanism one.",
            "novelty_basis": "Distinct integration of observed variables.",
            "falsifiability": "Rejected when prediction one fails.",
            "predictions": ["Prediction one."],
            "supporting_evidence_refs": ["E1", "E2"],
            "challenging_evidence_refs": ["E4"],
            "boundary_conditions": ["Boundary one."],
        },
        {
            "hypothesis_id": "HYP-2",
            "statement": "Second falsifiable hypothesis.",
            "mechanism": "Mechanism two.",
            "novelty_basis": "Alternative causal account.",
            "falsifiability": "Rejected when prediction two fails.",
            "predictions": ["Prediction two."],
            "supporting_evidence_refs": ["E2", "E3"],
            "challenging_evidence_refs": ["E4"],
            "boundary_conditions": ["Boundary two."],
        },
    ]
    dimensions = [
        "evidence_support",
        "factual_accuracy",
        "novelty",
        "falsifiability",
        "plan_feasibility",
        "risk_and_ethics",
        "counterexample_coverage",
    ]
    reviews = [
        {
            "hypothesis_id": hypothesis["hypothesis_id"],
            "dimension": dimension,
            "rating": "adequate",
            "rationale": f"Independent review for {dimension}.",
            "evidence_refs": ["E1", "E4"],
            "reviewer": "Research Review Agent",
        }
        for hypothesis in hypotheses
        for dimension in dimensions
    ]
    return {
        "schema_version": 1,
        "catalog_id": "science-125-questions-2021",
        "question_id": question_id,
        "question_en": catalog_question["question_en"],
        "run": {
            "run_id": f"run-{question_id.lower()}",
            "started_at": "2026-07-23T00:00:00Z",
            "completed_at": "2026-07-23T00:10:00Z",
            "model_provider": "dashscope",
            "model_id": "dashscope_main/qwen3.6-plus",
            "platform": "aliyun_bailian",
            "invocation_evidence_refs": ["model-evidence-real-1"],
        },
        "status": status,
        "problem_understanding": {
            "scope": "A bounded scientific interpretation.",
            "subquestions": ["Which code families are distinguishable?"],
            "assumptions": ["Recorded spikes are valid observations."],
            "known_unknowns": ["The relevant temporal scale may vary."],
            "human_gate": _gate(decision),
        },
        "evidence": evidence,
        "hypotheses": hypotheses,
        "dimension_reviews": reviews,
        "selection": {
            "selected_hypothesis_id": "HYP-1",
            "comparison_method": "multi_dimension_pareto_plus_human_decision",
            "tradeoffs": ["Evidence strength versus novelty."],
            "rejected_hypotheses": [{"hypothesis_id": "HYP-2", "reason": "Retained as an alternative."}],
            "human_gate": _gate(decision),
        },
        "research_plan": {
            "objective": "Discriminate the two hypotheses.",
            "method": "Compare preregistered decoders and perturbations.",
            "work_packages": [
                {
                    "work_package_id": "WP-1",
                    "goal": "Prepare data and evaluation.",
                    "inputs": ["Public spike data."],
                    "procedure": ["Preprocess without label leakage."],
                    "outputs": ["Versioned analysis dataset."],
                    "dependencies": ["Dataset access."],
                }
            ],
            "variables": ["Decoder family."],
            "controls": ["Rate-matched surrogate."],
            "data_and_materials": ["Public spike dataset."],
            "analysis": ["Cross-validated held-out decoding."],
            "success_criteria": ["Prediction separates hypotheses."],
            "failure_criteria": ["No reliable separation."],
            "stop_conditions": ["Data integrity failure."],
            "resources": ["CPU analysis environment."],
            "timeline": ["Week 1: data audit."],
            "risks": ["Dataset shift."],
            "human_gate": _gate(decision),
        },
        "feedback_iterations": [
            {
                "round": 1,
                "trigger": "Independent review.",
                "input_refs": ["E4"],
                "changes": ["Narrowed the claim boundary."],
                "unresolved_issues": ["Temporal scale dependence."],
                "human_feedback": "Pending final review.",
            }
        ],
        "final_summary": {
            "answer_boundary": "This is a research hypothesis, not a solved neural code.",
            "selected_hypothesis": "First falsifiable hypothesis.",
            "research_plan_summary": "Use held-out decoding and controls.",
            "key_evidence_refs": ["E1", "E2"],
            "counterevidence_refs": ["E4"],
            "limitations": ["Public data may not span all circuits."],
            "next_validation_step": "Run preregistered decoder comparison.",
        },
        "audit": {
            "source_catalog_sha256": "0" * 64,
            "output_sha256": "0" * 64,
            "schema_validation": "pending",
            "citation_validation": "pending",
            "human_review_status": human_status,
        },
    }


def _citation_checks(output: dict) -> list[dict]:
    return [{"sourceUrl": item["source_url"], "status": "passed"} for item in output["evidence"]]


def _isolate_store(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(challenge_question_runs, "_workflow_root", lambda _team_id: tmp_path)
    monkeypatch.setattr(challenge_question_runs.team_service, "get_team", lambda team_id: {"teamId": team_id})
    monkeypatch.setattr(challenge_question_runs, "record_runtime_scene_event", lambda *args, **kwargs: None)
    evidence_path = tmp_path / "official_model_evidence" / "index.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(
        json.dumps(
            {
                "evidence": [
                    {
                        "evidenceId": "model-evidence-real-1",
                        "modelProvider": "dashscope",
                        "status": "registered",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def test_register_valid_pending_candidate_counts_sample_but_not_completion(tmp_path, monkeypatch):
    _isolate_store(tmp_path, monkeypatch)
    output = _output()

    response = challenge_question_runs.register_challenge_question_output(
        "research-team",
        {
            "output": output,
            "citationChecks": _citation_checks(output),
            "registeredBy": "test-agent",
        },
    )

    record = response["record"]
    assert record["validation"]["schemaValidation"] == "passed"
    assert record["validation"]["citationValidation"] == "passed"
    assert record["validation"]["officialModelCall"] is True
    assert record["humanGates"]["approvedCount"] == 0
    assert response["summary"]["validCandidateCount"] == 1
    assert response["summary"]["completedCount"] == 0


def test_revised_question_run_records_parent_lineage_and_is_immutable(tmp_path, monkeypatch):
    _isolate_store(tmp_path, monkeypatch)
    parent_output = _output()
    challenge_question_runs.register_challenge_question_output(
        "research-team",
        {
            "output": parent_output,
            "citationChecks": _citation_checks(parent_output),
        },
    )
    revised_output = _output()
    revised_output["run"]["run_id"] = "run-sci-096-v2"
    revised_output["hypotheses"][0]["statement"] = "A revised, evidence-bounded hypothesis."
    payload = {
        "output": revised_output,
        "citationChecks": _citation_checks(revised_output),
        "parentRunId": parent_output["run"]["run_id"],
        "lineageRefs": ["experiment-result-1", "qwen-revision-v2"],
    }

    registered = challenge_question_runs.register_challenge_question_output("research-team", payload)
    duplicate = challenge_question_runs.register_challenge_question_output("research-team", payload)

    assert registered["record"]["lineage"] == {
        "relation": "revises",
        "parentRunId": parent_output["run"]["run_id"],
        "refs": ["experiment-result-1", "qwen-revision-v2"],
    }
    assert duplicate["idempotent"] is True
    assert duplicate["record"]["registeredAt"] == registered["record"]["registeredAt"]

    changed_output = deepcopy(revised_output)
    changed_output["hypotheses"][0]["statement"] = "An illicit overwrite."
    with pytest.raises(ValueError, match="immutable"):
        challenge_question_runs.register_challenge_question_output(
            "research-team",
            {**payload, "output": changed_output, "citationChecks": _citation_checks(changed_output)},
        )


def test_revised_question_run_requires_existing_parent(tmp_path, monkeypatch):
    _isolate_store(tmp_path, monkeypatch)
    revised_output = _output()
    revised_output["run"]["run_id"] = "run-sci-096-v2"

    with pytest.raises(ValueError, match="parentRunId was not found"):
        challenge_question_runs.register_challenge_question_output(
            "research-team",
            {
                "output": revised_output,
                "citationChecks": _citation_checks(revised_output),
                "parentRunId": "missing-parent",
            },
        )


def test_five_approved_unique_questions_complete_trial_count(tmp_path, monkeypatch):
    _isolate_store(tmp_path, monkeypatch)
    for question_number in range(96, 101):
        output = _output(question_number, approved=True)
        registered = challenge_question_runs.register_challenge_question_output(
            "research-team",
            {"output": deepcopy(output), "citationChecks": _citation_checks(output)},
        )
        challenge_question_runs.review_challenge_question_output(
            "research-team",
            output["question_id"],
            registered["record"]["runId"],
            {
                "reviewer": "Human Reviewer",
                "rationale": "All four gates were explicitly reviewed.",
                "decisions": {
                    "H1_problem_understanding": "approved",
                    "H2_hypothesis_selection": "approved",
                    "H3_research_plan": "approved",
                    "H4_external_output": "approved",
                },
            },
        )

    summary = challenge_question_runs.challenge_question_run_summary("research-team")
    assert summary["validCandidateCount"] == 5
    assert summary["completedCount"] == 5
    assert summary["completedQuestionIds"] == ["SCI-096", "SCI-097", "SCI-098", "SCI-099", "SCI-100"]


def test_deferred_h4_review_preserves_revision_requested_decision(tmp_path, monkeypatch):
    _isolate_store(tmp_path, monkeypatch)
    output = _output(96)
    registered = challenge_question_runs.register_challenge_question_output(
        "research-team",
        {"output": deepcopy(output), "citationChecks": _citation_checks(output)},
    )

    response = challenge_question_runs.review_challenge_question_output(
        "research-team",
        output["question_id"],
        registered["record"]["runId"],
        {
            "reviewer": "Human Reviewer",
            "rationale": "H1-H3 approved; H4 deferred pending more evidence.",
            "decisions": {
                "H1_problem_understanding": "approved",
                "H2_hypothesis_selection": "approved",
                "H3_research_plan": "approved",
                "H4_external_output": "revision_requested",
            },
        },
    )

    assert response["record"]["status"] == "needs_revision"
    assert response["record"]["humanGates"]["approvedCount"] == 3
    assert response["record"]["humanGates"]["allApproved"] is False
    assert response["record"]["humanGates"]["decisions"]["H4_external_output"] == "revision_requested"
    assert response["output"]["audit"]["human_review_status"] == "revision_requested"
    assert response["summary"]["completedCount"] == 0


def test_registration_cannot_self_approve_human_gates(tmp_path, monkeypatch):
    _isolate_store(tmp_path, monkeypatch)
    output = _output(approved=True)

    response = challenge_question_runs.register_challenge_question_output(
        "research-team",
        {"output": output, "citationChecks": _citation_checks(output)},
    )

    assert response["record"]["status"] == "review_required"
    assert response["record"]["humanGates"]["approvedCount"] == 0
    assert response["summary"]["completedCount"] == 0


def test_unregistered_model_evidence_cannot_satisfy_official_call_gate(tmp_path, monkeypatch):
    _isolate_store(tmp_path, monkeypatch)
    output = _output()
    output["run"]["invocation_evidence_refs"] = ["invented-evidence-id"]

    response = challenge_question_runs.register_challenge_question_output(
        "research-team",
        {"output": output, "citationChecks": _citation_checks(output)},
    )

    assert response["record"]["validation"]["officialModelCall"] is False
    assert response["summary"]["validCandidateCount"] == 0


def test_catalog_question_text_mismatch_fails_schema_gate(tmp_path, monkeypatch):
    _isolate_store(tmp_path, monkeypatch)
    output = _output()
    output["question_en"] = "A rewritten question that is not the official catalog wording."

    response = challenge_question_runs.register_challenge_question_output(
        "research-team",
        {"output": output, "citationChecks": _citation_checks(output)},
    )

    assert response["record"]["validation"]["schemaValidation"] == "failed"
    assert any(
        issue["path"] == "question_en"
        for issue in response["record"]["validation"]["schemaIssues"]
    )
