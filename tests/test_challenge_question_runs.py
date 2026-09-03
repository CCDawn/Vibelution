from __future__ import annotations

import json
from copy import deepcopy

import pytest

from core.chat.turn_journal import EVENT_ASSISTANT_ITEM_COMMITTED, append_turn_event
from core.research.competition.question_result_package import canonical_model_policy
from core.research.workflow.contracts.model_invocation_receipt import (
    ModelInvocationReceipt,
)
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
        "schema_version": 2,
        "identity": {
            "catalog_id": "science-125-questions-2021",
            "question_id": question_id,
            "question_en": catalog_question["question_en"],
        },
        "classification": {
            "domain": catalog_question["domain"],
            "specialization_profile_id": "SPEC-COMP-INFO-NEURO-v1",
            "is_specialty_question": catalog_question["domain"] in {"information_science", "neuroscience"},
        },
        "scope": {
            "theme_id": f"theme-{question_id.lower()}",
            "campaign_id": f"campaign-{question_id.lower()}",
            "research_project_id": f"project-{question_id.lower()}",
            "memory_scope": "same_theme",
        },
        "run": {
            "run_id": f"run-{question_id.lower()}",
            "started_at": "2026-07-23T00:00:00Z",
            "completed_at": "2026-07-23T00:10:00Z",
            "model_provider": "dashscope",
            "model_id": "dashscope_main/qwen3.6-plus",
            "platform": "aliyun_bailian",
            "invocation_evidence_refs": ["model-evidence-real-1"],
        },
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
        "result_classification": {
            "status": status,
            "actual_execution": False,
            "classification": "proposal_only",
            "claim_boundary": "A bounded hypothesis and research plan only.",
            "final_summary": {
                "answer_boundary": "This is a research hypothesis, not a solved neural code.",
                "selected_hypothesis": "First falsifiable hypothesis.",
                "research_plan_summary": "Use held-out decoding and controls.",
                "key_evidence_refs": ["E1", "E2"],
                "counterevidence_refs": ["E4"],
                "limitations": ["Public data may not span all circuits."],
                "next_validation_step": "Run preregistered decoder comparison.",
            },
        },
        "competition_result_view": {
            "problem_statement": catalog_question["question_en"],
            "rationale": "The question supports a falsifiable comparison.",
            "technical_details": "Use preregistered held-out decoding and controls.",
            "datasets": {"source": ["Public spike dataset"], "target": ["Versioned analysis dataset"]},
            "paper_title": "A bounded study of neural spike coding",
            "paper_abstract": "We compare two falsifiable accounts with controlled decoding.",
            "methods": ["held-out decoding"],
            "experiments": ["preregistered decoder comparison"],
            "results": ["proposal_only"],
            "references": ["E1", "E2", "E4"],
        },
        "collaboration_refs": {
            "team_id": "research-team",
            "meeting_digest_ids": [],
            "knowledge_item_ids": ["E1", "E2", "E4"],
            "template_version": "challenge-question-v2",
        },
        "review": {
            "human_review_status": human_status,
            "question_review_digest_ids": [],
        },
        "submission": {
            "eligible": approved,
            "projection_version": "1.0-review.1",
            "blockers": [] if approved else ["human_review_pending"],
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


def _challenge_task() -> dict:
    return {
        "taskId": "stage-task-sci-096",
        "runId": "source-run-sci-096",
        "sessionId": "session-sci-096",
        "agentId": "agent-source-finder",
        "agentRole": "source_finder",
        "stageId": "finding",
        "researchProjectId": "project-sci-096",
        "turn": {"turnId": "turn-sci-096"},
        "challengeTaskContract": {
            "questionId": "SCI-096",
            "researchProjectId": "project-sci-096",
            "taskId": "stage-task-sci-096",
            "turnId": "turn-sci-096",
            "effectiveRoute": {
                "modelRef": "dashscope_main/qwen3.6-plus",
                "providerId": "dashscope_main",
                "modelId": "qwen3.6-plus",
            },
            "requiredModelPolicy": canonical_model_policy(
                {
                    "family": "qwen",
                    "providerIds": ["dashscope_main"],
                    "modelIds": ["qwen3.6-plus"],
                    "requireOfficialProvider": True,
                }
            ),
            "evidencePolicy": {"officialEvidenceEligible": True},
        },
    }


def _append_canonical_turn_output(project_root, task: dict, output: dict) -> None:
    append_turn_event(
        project_root,
        task["sessionId"],
        task["turn"]["turnId"],
        EVENT_ASSISTANT_ITEM_COMMITTED,
        status="completed",
        payload={
            "schemaVersion": 2,
            "sessionId": task["sessionId"],
            "turnId": task["turn"]["turnId"],
            "kind": "assistant_message",
            "channel": "answer",
            "phase": "final_answer",
            "terminal": True,
            "text": json.dumps(output, ensure_ascii=False),
        },
        source="canonical_turn_outcome",
        visible_in_model=True,
        projection_kind="session_turn_item_v2",
        provider_role="assistant",
    )


def _isolate_store(tmp_path, monkeypatch) -> None:
    from core.web.services.team_workflow.research_runtime import (
        model_invocation_receipt_registry,
    )

    monkeypatch.setattr(challenge_question_runs, "_workflow_root", lambda _team_id: tmp_path)
    monkeypatch.setattr(
        model_invocation_receipt_registry,
        "resolve_team_program_root",
        lambda _team_id: tmp_path,
    )
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


def test_task_model_evidence_requires_success_and_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(challenge_question_runs, "_project_root", lambda: tmp_path)
    project_root = tmp_path / "project-sci-096"
    monkeypatch.setattr(
        challenge_question_runs,
        "resolve_research_project_workspace_root",
        lambda _team_id, _project_id: project_root,
    )
    task = _challenge_task()
    output = _output()
    output["run"]["run_id"] = task["runId"]
    task["result"] = {
        "outputSha256": "f" * 64,
        "outputRef": "turn-journal://forged/result",
    }
    _append_canonical_turn_output(tmp_path, task, output)
    usage = {
        "source": "canonical_turn_outcome",
        "provider": "dashscope_main",
        "model": "qwen3.6-plus",
        "llmModelId": "dashscope_main/qwen3.6-plus",
        "inputTokens": 100,
        "outputTokens": 80,
        "totalTokens": 180,
    }

    assert (
        challenge_question_runs.register_challenge_task_model_evidence(
            "research-team",
            task,
            final_status="incomplete",
            llm_usage=usage,
        )
        is None
    )
    first = challenge_question_runs.register_challenge_task_model_evidence(
        "research-team",
        task,
        final_status="completed",
        llm_usage=usage,
    )
    repeated = challenge_question_runs.register_challenge_task_model_evidence(
        "research-team",
        task,
        final_status="completed",
        llm_usage=usage,
    )

    assert first == repeated
    store = json.loads((project_root / "official_model_evidence" / "index.json").read_text(encoding="utf-8"))
    assert len(store["evidence"]) == 1
    assert store["evidence"][0]["status"] == "canonical_success"
    assert store["evidence"][0]["outputSha256"] == challenge_question_runs._output_sha256(output)
    assert store["evidence"][0]["outputRef"].startswith("turn-journal://")
    assert store["evidence"][0]["outputRef"] != task["result"]["outputRef"]


def test_flash_task_route_cannot_record_official_canonical_receipt(tmp_path, monkeypatch):
    monkeypatch.setattr(challenge_question_runs, "_project_root", lambda: tmp_path)
    project_root = tmp_path / "project-sci-096"
    monkeypatch.setattr(
        challenge_question_runs,
        "resolve_research_project_workspace_root",
        lambda _team_id, _project_id: project_root,
    )
    task = _challenge_task()
    task["challengeTaskContract"].update(
        {
            "requiredModelPolicy": {
                "providerIds": ["opencode_go"],
                "modelIds": ["deepseek-v4-flash"],
                "requireOfficialProvider": False,
            },
            "effectiveRoute": {
                "modelRef": "opencode_go/deepseek-v4-flash",
                "providerId": "opencode_go",
                "modelId": "deepseek-v4-flash",
            },
            "evidencePolicy": {"officialEvidenceEligible": True},
        }
    )
    output = _output()
    output["run"].update(
        {
            "run_id": task["runId"],
            "model_provider": "opencode_go",
            "model_id": "opencode_go/deepseek-v4-flash",
            "platform": "other_official_tool",
        }
    )
    _append_canonical_turn_output(tmp_path, task, output)
    source_binding = challenge_question_runs._read_canonical_turn_output(
        session_id=task["sessionId"],
        source_run_id=task["runId"],
        task_id=task["taskId"],
        turn_id=task["turn"]["turnId"],
    )
    assert source_binding is not None
    policy_sha256 = "a" * 64
    receipt = ModelInvocationReceipt.from_invocation(
        receipt_id="receipt-flash-generation",
        run_id=task["runId"],
        node_run_id="node-flash-generation",
        scope={
            "questionId": "SCI-096",
            "runId": task["runId"],
            "taskId": task["taskId"],
            "turnId": task["turn"]["turnId"],
            "stageId": "generation",
            "modelPolicySha256": policy_sha256,
        },
        provider="opencode_go",
        model="deepseek-v4-flash",
        requested_model="deepseek-v4-flash",
        request_content={"kind": "bounded-test-request"},
        response_content={"kind": "bounded-test-response"},
        started_at_ms=100,
        finished_at_ms=125,
        token_usage={"input": 20, "output": 10, "total": 30},
        evidence_locator={
            "outputSha256": source_binding["outputSha256"],
            "outputRef": source_binding["outputRef"],
        },
    )
    usage = {
        "source": "provider",
        "provider": "opencode_go",
        "model": "deepseek-v4-flash",
        "llmModelId": "opencode_go/deepseek-v4-flash",
        "inputTokens": 20,
        "outputTokens": 10,
        "totalTokens": 30,
    }

    evidence = challenge_question_runs.register_challenge_task_model_evidence(
        "research-team",
        task,
        final_status="completed",
        llm_usage=usage,
        model_invocation_receipt=receipt,
        stage_id="generation",
        model_policy_sha256=policy_sha256,
    )

    assert evidence is None
    assert not (project_root / "official_model_evidence" / "index.json").exists()


def test_flash_task_policy_is_derived_and_bound_without_qwen_gate(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        challenge_question_runs,
        "resolve_research_project_workspace_root",
        lambda _team_id, _project_id: tmp_path,
    )
    policy = challenge_question_runs.derive_challenge_required_model_policy(
        "opencode_go/deepseek-v4-flash"
    )

    contract = challenge_question_runs.bind_challenge_research_task_model(
        team_id="research-team",
        research_project_id="project-sci-096",
        question_id="SCI-096",
        required_model_policy=policy,
        dialogue_model_id="opencode_go/deepseek-v4-flash",
        model_library={
            "opencode_go/deepseek-v4-flash": {
                "provider_id": "opencode_go",
                "upstream_id": "deepseek-v4-flash",
            }
        },
    )

    assert contract["requiredModelPolicy"] == {
        "providerIds": ["opencode_go"],
        "modelIds": ["deepseek-v4-flash"],
        "requireOfficialProvider": False,
    }
    assert contract["evidencePolicy"]["officialEvidenceEligible"] is False


def test_formal_flash_task_policy_preserves_server_hash_authority(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        challenge_question_runs,
        "resolve_research_project_workspace_root",
        lambda _team_id, _project_id: tmp_path,
    )
    required_policy = canonical_model_policy(
        {
            "family": "deepseek",
            "providerIds": ["opencode_go"],
            "modelIds": ["deepseek-v4-flash"],
            "requireOfficialProvider": False,
        }
    )

    contract = challenge_question_runs.bind_challenge_research_task_model(
        team_id="research-team",
        research_project_id="project-sci-096",
        question_id="SCI-096",
        required_model_policy=required_policy,
        dialogue_model_id="opencode_go/deepseek-v4-flash",
        model_library={
            "opencode_go/deepseek-v4-flash": {
                "provider_id": "opencode_go",
                "upstream_id": "deepseek-v4-flash",
            }
        },
    )

    assert contract["requiredModelPolicy"] == required_policy
    assert contract["modelPolicySha256"] == required_policy["policySha256"]


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
    assert record["validation"]["modelInvocationReceipts"] == "failed"
    assert record["validation"]["modelInvocationReceiptIssue"] == (
        "canonical_result_package_missing"
    )
    assert record["modelInvocationReceiptRefs"] == {}
    assert record["humanGates"]["approvedCount"] == 0
    assert response["summary"]["validCandidateCount"] == 1
    assert response["summary"]["receiptReadyQuestionCount"] == 0
    assert response["summary"]["completedCount"] == 0

    store_path = challenge_question_runs._store_path("research-team")
    store = json.loads(store_path.read_text(encoding="utf-8"))
    store["records"][0]["validation"]["modelInvocationReceipts"] = "passed"
    store_path.write_text(json.dumps(store), encoding="utf-8")

    summary = challenge_question_runs.challenge_question_run_summary("research-team")
    assert summary["receiptReadyQuestionIds"] == []
    assert summary["latestCandidate"]["validation"][
        "modelInvocationReceipts"
    ] == "failed"
    assert summary["latestCandidate"]["validation"][
        "modelInvocationReceiptIssue"
    ] == "canonical_result_package_missing"


def test_get_question_detail_returns_latest_immutable_artifact(tmp_path, monkeypatch):
    _isolate_store(tmp_path, monkeypatch)
    first_output = _output(approved=True)
    first_output["run"]["run_id"] = "sci-096-v1"
    first = challenge_question_runs.register_challenge_question_output(
        "research-team",
        {
            "output": first_output,
            "citationChecks": _citation_checks(first_output),
            "registeredBy": "source-finder-agent",
        },
    )
    second_output = deepcopy(first_output)
    second_output["run"]["run_id"] = "sci-096-v2"
    second_output["feedback_iterations"][0]["changes"] = ["Clarified the evidence boundary."]
    second = challenge_question_runs.register_challenge_question_output(
        "research-team",
        {
            "output": second_output,
            "citationChecks": _citation_checks(second_output),
            "registeredBy": "review-agent",
            "parentRunId": "sci-096-v1",
        },
    )

    detail = challenge_question_runs.get_challenge_question_run_detail(
        "research-team",
        "SCI-096",
    )

    assert detail["questionId"] == "SCI-096"
    assert detail["selectedRunId"] == "sci-096-v2"
    assert detail["record"]["recordId"] == second["record"]["recordId"]
    assert detail["output"]["run"]["run_id"] == "sci-096-v2"
    assert detail["artifact"]["sha256"] == second["record"]["outputSha256"]
    assert detail["artifact"]["immutable"] is True
    assert [item["runId"] for item in detail["runs"]] == ["sci-096-v1", "sci-096-v2"]
    assert detail["runs"][0]["outputSha256"] == first["record"]["outputSha256"]


def test_get_question_detail_can_select_prior_run_without_active_project_fallback(tmp_path, monkeypatch):
    _isolate_store(tmp_path, monkeypatch)
    output = _output(approved=True)
    output["run"]["run_id"] = "sci-096-v1"
    challenge_question_runs.register_challenge_question_output(
        "research-team",
        {
            "output": output,
            "citationChecks": _citation_checks(output),
            "registeredBy": "source-finder-agent",
        },
    )

    detail = challenge_question_runs.get_challenge_question_run_detail(
        "research-team",
        "SCI-096",
        run_id="sci-096-v1",
    )

    assert detail["selectedRunId"] == "sci-096-v1"
    assert detail["output"]["identity"]["question_id"] == "SCI-096"
    assert "researchProjectId" not in detail


def test_v1_artifact_remains_readable_but_never_enters_formal_summary(tmp_path, monkeypatch):
    _isolate_store(tmp_path, monkeypatch)
    legacy_output = {
        "schema_version": 1,
        "catalog_id": "science-125-questions-2021",
        "question_id": "SCI-096",
        "question_en": "What are the coding principles embedded in neuronal spike trains?",
        "run": {"run_id": "legacy-sci-096-v1"},
    }
    output_hash = challenge_question_runs._output_sha256(legacy_output)
    artifact_path = tmp_path / "challenge_program" / "question_runs" / "SCI-096" / "legacy-sci-096-v1.json"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps(legacy_output), encoding="utf-8")
    store_path = tmp_path / "challenge_program" / "question_runs" / "index.json"
    store_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "storeKind": "challenge_question_run_store",
                "teamId": "research-team",
                "records": [
                    {
                        "recordId": "SCI-096:legacy-sci-096-v1",
                        "questionId": "SCI-096",
                        "runId": "legacy-sci-096-v1",
                        "schemaVersion": 1,
                        "status": "approved",
                        "outputSha256": output_hash,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    detail = challenge_question_runs.get_challenge_question_run_detail(
        "research-team",
        "SCI-096",
        run_id="legacy-sci-096-v1",
    )
    summary = challenge_question_runs.challenge_question_run_summary("research-team")

    assert detail["output"]["schema_version"] == 1
    assert detail["output"]["question_id"] == "SCI-096"
    assert summary["validCandidateCount"] == 0
    assert summary["completedQuestionIds"] == []
    assert summary["completedQuestionResults"] == []


def test_get_question_detail_fails_closed_for_unknown_question_or_tampered_artifact(tmp_path, monkeypatch):
    _isolate_store(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="challenge_question_run_not_found"):
        challenge_question_runs.get_challenge_question_run_detail(
            "research-team",
            "SCI-097",
        )

    output = _output(approved=True)
    response = challenge_question_runs.register_challenge_question_output(
        "research-team",
        {
            "output": output,
            "citationChecks": _citation_checks(output),
            "registeredBy": "source-finder-agent",
        },
    )
    artifact = tmp_path / "challenge_program" / "question_runs" / "SCI-096" / "run-sci-096.json"
    artifact.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="challenge_question_run_artifact_mismatch"):
        challenge_question_runs.get_challenge_question_run_detail(
            "research-team",
            "SCI-096",
            run_id=response["record"]["runId"],
        )


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


def test_replay_after_human_review_recognizes_same_canonical_output(
    tmp_path, monkeypatch
):
    """The finalize-time Program readback replays a reviewed run.

    Human review is the one sanctioned post-registration mutation: it writes
    approved gate decisions into the stored artifact and re-hashes the index
    record.  Re-registering the same canonical output (identical once both
    copies are normalised back to pending gates) must stay idempotent instead
    of being rejected as an illicit overwrite, otherwise the stage-one
    finalize's fresh handoff can never read the approved record back.
    """

    _isolate_store(tmp_path, monkeypatch)
    output = _output()
    question_id = output["identity"]["question_id"]
    run_id = output["run"]["run_id"]
    payload = {
        "output": output,
        "citationChecks": _citation_checks(output),
    }
    registered = challenge_question_runs.register_challenge_question_output(
        "research-team", payload
    )
    assert registered["record"]["recordId"] == f"{question_id}:{run_id}"

    artifact_path = challenge_question_runs._artifact_path(
        "research-team", question_id, run_id
    )
    stored = challenge_question_runs._read_json(artifact_path)
    gate = stored["problem_understanding"]["human_gate"]
    gate.update(
        {
            "decision": "approved",
            "rationale": "operator approved",
            "reviewer": "operator:test",
            "decided_at": "2026-09-04T00:00:00Z",
        }
    )
    stored.setdefault("review", {})["human_review_status"] = "approved"
    stored.setdefault("submission", {}).update(
        {"eligible": True, "projection_version": "1.0-review.1", "blockers": []}
    )
    stored.setdefault("audit", {})["human_review_status"] = "approved"
    challenge_question_runs._write_json(artifact_path, stored)

    store = challenge_question_runs._load_store("research-team")
    record = next(
        item
        for item in store["records"]
        if item.get("recordId") == f"{question_id}:{run_id}"
    )
    record["outputSha256"] = challenge_question_runs._output_sha256(stored)
    record["status"] = "approved"
    challenge_question_runs._write_json(challenge_question_runs._store_path("research-team"), store)

    replay = challenge_question_runs.register_challenge_question_output(
        "research-team", payload
    )
    assert replay["idempotent"] is True
    assert replay["record"]["recordId"] == f"{question_id}:{run_id}"
    assert replay["record"]["status"] == "approved"

    # A genuinely different canonical output stays an illicit overwrite.
    changed_output = deepcopy(output)
    changed_output["hypotheses"][0]["statement"] = "An illicit overwrite."
    with pytest.raises(ValueError, match="immutable"):
        challenge_question_runs.register_challenge_question_output(
            "research-team",
            {
                "output": changed_output,
                "citationChecks": _citation_checks(changed_output),
            },
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


def test_summary_excludes_approved_runs_without_receipts_from_completion(
    tmp_path, monkeypatch
):
    _isolate_store(tmp_path, monkeypatch)
    for question_number in (1, 91, 96):
        output = _output(question_number, approved=True)
        registered = challenge_question_runs.register_challenge_question_output(
            "research-team",
            {"output": deepcopy(output), "citationChecks": _citation_checks(output)},
        )
        challenge_question_runs.review_challenge_question_output(
            "research-team",
            output["identity"]["question_id"],
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
    assert summary["receiptReadyQuestionIds"] == []
    assert summary["completedQuestionIds"] == []
    assert summary["approvedDeepExperimentQuestionIds"] == []


def test_five_approved_questions_without_receipts_fail_completion_gate(
    tmp_path, monkeypatch
):
    _isolate_store(tmp_path, monkeypatch)
    for question_number in range(96, 101):
        output = _output(question_number, approved=True)
        registered = challenge_question_runs.register_challenge_question_output(
            "research-team",
            {"output": deepcopy(output), "citationChecks": _citation_checks(output)},
        )
        challenge_question_runs.review_challenge_question_output(
            "research-team",
            output["identity"]["question_id"],
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
    assert summary["validatedQuestionCount"] == 5
    assert summary["validatedQuestionIds"] == ["SCI-096", "SCI-097", "SCI-098", "SCI-099", "SCI-100"]
    assert summary["validatedOutcomeCounts"] == {"approved": 5}
    assert summary["receiptReadyQuestionCount"] == 0
    assert summary["completedCount"] == 0
    assert summary["completedQuestionIds"] == []


def test_deferred_h4_review_preserves_revision_requested_decision(tmp_path, monkeypatch):
    _isolate_store(tmp_path, monkeypatch)
    output = _output(96)
    registered = challenge_question_runs.register_challenge_question_output(
        "research-team",
        {"output": deepcopy(output), "citationChecks": _citation_checks(output)},
    )

    response = challenge_question_runs.review_challenge_question_output(
        "research-team",
        output["identity"]["question_id"],
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
    assert response["summary"]["validatedQuestionCount"] == 1
    assert response["summary"]["validatedQuestionIds"] == ["SCI-096"]
    assert response["summary"]["validatedOutcomeCounts"] == {"needs_revision": 1}
    assert response["summary"]["validatedQuestionResults"][0]["questionId"] == "SCI-096"
    assert response["summary"]["validatedQuestionResults"][0]["humanGates"]["allApproved"] is False


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


def test_canonical_package_accepts_authorized_dashscope_provider_alias():
    policy = canonical_model_policy(
        {
            "family": "qwen",
            "providerIds": ["dashscope_main"],
            "modelIds": ["qwen3.6-plus"],
            "requireOfficialProvider": True,
        }
    )

    assert challenge_question_runs._official_call_from_canonical_package(
        model_policy=policy,
        model_provider="dashscope_main",
        model_ref="dashscope_main/qwen3.6-plus",
        receipt_refs={"generation": {"receipt_id": "receipt-generation"}},
    ) is True


def test_catalog_question_text_mismatch_fails_schema_gate(tmp_path, monkeypatch):
    _isolate_store(tmp_path, monkeypatch)
    output = _output()
    output["identity"]["question_en"] = "A rewritten question that is not the official catalog wording."

    response = challenge_question_runs.register_challenge_question_output(
        "research-team",
        {"output": output, "citationChecks": _citation_checks(output)},
    )

    assert response["record"]["validation"]["schemaValidation"] == "failed"
    assert any(
        issue["path"] == "identity.question_en"
        for issue in response["record"]["validation"]["schemaIssues"]
    )


def test_publish_promotes_only_bound_project_evidence_and_keeps_human_gates_pending(tmp_path, monkeypatch):
    program_root = tmp_path / "program"
    project_root = tmp_path / "project"
    monkeypatch.setattr(challenge_question_runs, "_workflow_root", lambda _team_id: program_root)
    monkeypatch.setattr(
        challenge_question_runs,
        "resolve_research_project_workspace_root",
        lambda _team_id, _project_id: project_root,
    )
    monkeypatch.setattr(challenge_question_runs, "_project_root", lambda: tmp_path)
    monkeypatch.setattr(challenge_question_runs.team_service, "get_team", lambda team_id: {"teamId": team_id})
    monkeypatch.setattr(challenge_question_runs, "record_runtime_scene_event", lambda *args, **kwargs: None)
    project_evidence_path = project_root / "official_model_evidence" / "index.json"
    project_evidence_path.parent.mkdir(parents=True, exist_ok=True)
    project_evidence_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "storeKind": "official_model_evidence_store",
                "teamId": "research-team",
                "evidence": [
                    {
                        "evidenceId": "model-evidence-project-qwen",
                        "teamId": "research-team",
                        "researchProjectId": "research-project-1",
                        "questionId": "SCI-096",
                        "taskId": "stagetask-1",
                        "turnId": "turn-1",
                        "modelProvider": "dashscope",
                        "providerId": "dashscope_main",
                        "modelId": "qwen3.6-plus",
                        "modelRef": "dashscope_main/qwen3.6-plus",
                        "status": "canonical_success",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    output = _output()
    output["run"]["run_id"] = "source-run-sci-096"
    output["run"]["invocation_evidence_refs"] = ["model-evidence-project-qwen"]
    canonical_task = {
        "sessionId": "session-sci-096",
        "turn": {"turnId": "turn-1"},
    }
    _append_canonical_turn_output(tmp_path, canonical_task, output)
    output_ref = challenge_question_runs._canonical_output_ref(
        "session-sci-096", "source-run-sci-096", "stagetask-1", "turn-1"
    )
    output_hash = challenge_question_runs._output_sha256(output)
    project_evidence = {
        "evidenceId": "model-evidence-project-qwen",
        "teamId": "research-team",
        "researchProjectId": "research-project-1",
        "questionId": "SCI-096",
        "sourceRunId": "source-run-sci-096",
        "sourceSessionId": "session-sci-096",
        "taskId": "stagetask-1",
        "turnId": "turn-1",
        "modelProvider": "dashscope",
        "providerId": "dashscope_main",
        "modelId": "qwen3.6-plus",
        "modelRef": "dashscope_main/qwen3.6-plus",
        "status": "canonical_success",
        "outputSha256": output_hash,
        "outputRef": output_ref,
    }
    project_store = json.loads(project_evidence_path.read_text(encoding="utf-8"))
    project_store["evidence"] = [project_evidence]
    project_evidence_path.write_text(json.dumps(project_store), encoding="utf-8")

    publish_payload = {
        "researchProjectId": "research-project-1",
        "questionId": "SCI-096",
        "taskId": "stagetask-1",
        "turnId": "turn-1",
        "projectEvidenceId": "model-evidence-project-qwen",
        "output": output,
        "citationChecks": _citation_checks(output),
        "registeredBy": "publisher-agent",
        "lineageRefs": [output_ref],
    }
    response = challenge_question_runs.publish_research_project_challenge_question_output(
        "research-team", publish_payload
    )
    replayed = challenge_question_runs.publish_research_project_challenge_question_output(
        "research-team", publish_payload
    )

    assert response["record"]["validation"]["schemaValidation"] == "passed"
    assert response["record"]["validation"]["citationValidation"] == "passed"
    assert response["record"]["validation"]["semanticValidation"] == "passed"
    assert response["record"]["validation"]["officialModelCall"] is True
    assert response["record"]["humanGates"]["approvedCount"] == 0
    assert response["humanReviewRequired"] is True
    assert response["projectEvidenceId"] == "model-evidence-project-qwen"
    assert replayed["idempotent"] is True
    program_store = json.loads(
        (program_root / "official_model_evidence" / "index.json").read_text(encoding="utf-8")
    )
    assert len(program_store["evidence"]) == 1
    assert program_store["evidence"][0]["status"] == "published_to_challenge_program"
    assert program_store["evidence"][0]["officialBoundary"]["humanApprovalGranted"] is False

    captured_registration: dict = {}

    def capture_registration(_team_id: str, payload: dict) -> dict:
        captured_registration.update(deepcopy(payload))
        return {"record": {"recordId": "captured"}, "summary": {}}

    monkeypatch.setattr(
        challenge_question_runs,
        "register_challenge_question_output",
        capture_registration,
    )
    package_payload = {
        "schema_version": 2,
        "package_id": "pkg-sci-096-publish-boundary",
    }
    challenge_question_runs.publish_research_project_challenge_question_output(
        "research-team",
        {
            **publish_payload,
            "resultPackage": package_payload,
            "authorizedModelPolicySha256": "f" * 64,
        },
    )

    assert captured_registration["resultPackage"] == package_payload
    assert captured_registration["authorizedModelPolicySha256"] == "f" * 64


def test_publish_rejects_project_evidence_bound_to_another_turn(tmp_path, monkeypatch):
    program_root = tmp_path / "program"
    project_root = tmp_path / "project"
    monkeypatch.setattr(challenge_question_runs, "_workflow_root", lambda _team_id: program_root)
    monkeypatch.setattr(
        challenge_question_runs,
        "resolve_research_project_workspace_root",
        lambda _team_id, _project_id: project_root,
    )
    monkeypatch.setattr(challenge_question_runs.team_service, "get_team", lambda team_id: {"teamId": team_id})
    evidence_path = project_root / "official_model_evidence" / "index.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    output = _output()
    output["run"]["run_id"] = "source-run-sci-096"
    output["run"]["invocation_evidence_refs"] = ["model-evidence-project-qwen"]
    output_hash = challenge_question_runs._output_sha256(output)
    evidence_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "storeKind": "official_model_evidence_store",
                "teamId": "research-team",
                "evidence": [
                    {
                        "evidenceId": "model-evidence-project-qwen",
                        "researchProjectId": "research-project-1",
                        "questionId": "SCI-096",
                        "sourceRunId": "source-run-sci-096",
                        "taskId": "stagetask-1",
                        "turnId": "different-turn",
                        "modelProvider": "dashscope",
                        "providerId": "dashscope_main",
                        "modelId": "qwen3.6-plus",
                        "modelRef": "dashscope_main/qwen3.6-plus",
                        "status": "canonical_success",
                        "outputSha256": output_hash,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="evidence_mismatch"):
        challenge_question_runs.publish_research_project_challenge_question_output(
            "research-team",
            {
                "researchProjectId": "research-project-1",
                "questionId": "SCI-096",
                "taskId": "stagetask-1",
                "turnId": "turn-1",
                "projectEvidenceId": "model-evidence-project-qwen",
                "output": output,
                "citationChecks": _citation_checks(output),
            },
        )

    with pytest.raises(ValueError, match="evidence_mismatch"):
        challenge_question_runs.publish_research_project_challenge_question_output(
            "research-team",
            {
                "researchProjectId": "research-project-1",
                "questionId": "SCI-096",
                "taskId": "different-task",
                "turnId": "turn-1",
                "projectEvidenceId": "model-evidence-project-qwen",
                "output": output,
                "citationChecks": _citation_checks(output),
            },
        )

    assert not (program_root / "official_model_evidence" / "index.json").exists()


def test_publish_rejects_legacy_project_evidence_without_canonical_output_binding(tmp_path, monkeypatch):
    program_root = tmp_path / "program"
    project_root = tmp_path / "project"
    monkeypatch.setattr(challenge_question_runs, "_workflow_root", lambda _team_id: program_root)
    monkeypatch.setattr(
        challenge_question_runs,
        "resolve_research_project_workspace_root",
        lambda _team_id, _project_id: project_root,
    )
    monkeypatch.setattr(challenge_question_runs.team_service, "get_team", lambda team_id: {"teamId": team_id})
    evidence_path = project_root / "official_model_evidence" / "index.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "storeKind": "official_model_evidence_store",
                "teamId": "research-team",
                "evidence": [
                    {
                        "evidenceId": "legacy-evidence",
                        "researchProjectId": "research-project-1",
                        "questionId": "SCI-096",
                        "taskId": "stagetask-1",
                        "turnId": "turn-1",
                        "modelProvider": "dashscope",
                        "providerId": "dashscope_main",
                        "modelId": "qwen3.6-plus",
                        "modelRef": "dashscope_main/qwen3.6-plus",
                        "status": "canonical_success",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="legacy.*re-record|canonical output binding"):
        challenge_question_runs.publish_research_project_challenge_question_output(
            "research-team",
            {
                "researchProjectId": "research-project-1",
                "questionId": "SCI-096",
                "taskId": "stagetask-1",
                "turnId": "turn-1",
                "projectEvidenceId": "legacy-evidence",
                "output": _output(),
                "citationChecks": _citation_checks(_output()),
            },
        )


def test_publish_rejects_output_hash_mismatch_even_when_question_and_model_match(tmp_path, monkeypatch):
    program_root = tmp_path / "program"
    project_root = tmp_path / "project"
    monkeypatch.setattr(challenge_question_runs, "_workflow_root", lambda _team_id: program_root)
    monkeypatch.setattr(
        challenge_question_runs,
        "resolve_research_project_workspace_root",
        lambda _team_id, _project_id: project_root,
    )
    monkeypatch.setattr(challenge_question_runs, "_project_root", lambda: tmp_path)
    monkeypatch.setattr(challenge_question_runs.team_service, "get_team", lambda team_id: {"teamId": team_id})
    evidence_path = project_root / "official_model_evidence" / "index.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    canonical_output = _output()
    canonical_output["run"]["run_id"] = "source-run-sci-096"
    canonical_output["run"]["invocation_evidence_refs"] = ["bound-evidence"]
    canonical_task = {
        "sessionId": "session-sci-096",
        "turn": {"turnId": "turn-1"},
    }
    _append_canonical_turn_output(tmp_path, canonical_task, canonical_output)
    output_ref = challenge_question_runs._canonical_output_ref(
        "session-sci-096", "source-run-sci-096", "stagetask-1", "turn-1"
    )
    different_output = deepcopy(canonical_output)
    different_output["hypotheses"][0]["statement"] = "A different same-model output."
    evidence_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "storeKind": "official_model_evidence_store",
                "teamId": "research-team",
                "evidence": [
                    {
                        "evidenceId": "bound-evidence",
                        "researchProjectId": "research-project-1",
                        "questionId": "SCI-096",
                        "sourceRunId": "source-run-sci-096",
                        "sourceSessionId": "session-sci-096",
                        "taskId": "stagetask-1",
                        "turnId": "turn-1",
                        "modelProvider": "dashscope",
                        "providerId": "dashscope_main",
                        "modelId": "qwen3.6-plus",
                        "modelRef": "dashscope_main/qwen3.6-plus",
                        "status": "canonical_success",
                        "outputSha256": challenge_question_runs._output_sha256(canonical_output),
                        "outputRef": output_ref,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="output_hash_mismatch"):
        challenge_question_runs.publish_research_project_challenge_question_output(
            "research-team",
            {
                "researchProjectId": "research-project-1",
                "questionId": "SCI-096",
                "taskId": "stagetask-1",
                "turnId": "turn-1",
                "projectEvidenceId": "bound-evidence",
                "output": different_output,
                "citationChecks": _citation_checks(different_output),
            },
        )


def test_publish_requires_canonical_output_ref_even_when_hash_matches(tmp_path, monkeypatch):
    program_root = tmp_path / "program"
    project_root = tmp_path / "project"
    monkeypatch.setattr(challenge_question_runs, "_workflow_root", lambda _team_id: program_root)
    monkeypatch.setattr(
        challenge_question_runs,
        "resolve_research_project_workspace_root",
        lambda _team_id, _project_id: project_root,
    )
    monkeypatch.setattr(challenge_question_runs.team_service, "get_team", lambda team_id: {"teamId": team_id})
    evidence_path = project_root / "official_model_evidence" / "index.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    output = _output()
    output["run"]["run_id"] = "source-run-sci-096"
    output["run"]["invocation_evidence_refs"] = ["bound-evidence"]
    output_ref = "challenge-output://research-project-1/source-run-sci-096"
    evidence_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "storeKind": "official_model_evidence_store",
                "teamId": "research-team",
                "evidence": [
                    {
                        "evidenceId": "bound-evidence",
                        "researchProjectId": "research-project-1",
                        "questionId": "SCI-096",
                        "sourceRunId": "source-run-sci-096",
                        "taskId": "stagetask-1",
                        "turnId": "turn-1",
                        "modelProvider": "dashscope",
                        "providerId": "dashscope_main",
                        "modelId": "qwen3.6-plus",
                        "modelRef": "dashscope_main/qwen3.6-plus",
                        "status": "canonical_success",
                        "outputSha256": challenge_question_runs._output_sha256(output),
                        "outputRef": output_ref,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="output_ref_invalid"):
        challenge_question_runs.publish_research_project_challenge_question_output(
            "research-team",
            {
                "researchProjectId": "research-project-1",
                "questionId": "SCI-096",
                "taskId": "stagetask-1",
                "turnId": "turn-1",
                "projectEvidenceId": "bound-evidence",
                "output": output,
                "citationChecks": _citation_checks(output),
                "lineageRefs": [],
            },
        )
