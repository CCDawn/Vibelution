from __future__ import annotations

from tests._support.team_workflow.helpers import *  # noqa: F403


def _draft_complete_proxy_plan(team_id: str) -> dict:
    stage = team_workflow_orchestration_service.start_research_stage_round(
        team_id,
        {
            "stageType": "experiment",
            "topic": "bounded engineering proxy validation",
        },
    )
    return team_workflow_orchestration_service.create_experiment_plan(
        team_id,
        {
            "stageRoundId": stage["stageRound"]["stageRoundId"],
            "title": "Bounded proxy design v1",
            "createdByAgent": "Experiment Planning Agent",
            "researchQuestion": "Can the bounded reconstruction workflow beat its fixed baseline?",
            "researchMode": "hypothesis_and_plan",
            "experimentPurpose": {
                "primaryPurpose": "feasibility",
                "secondaryPurposes": [],
            },
            "experimentMethod": "model_training_inference",
            "objective": "Validate only the reproducible engineering proxy workflow.",
            "constraints": [
                "No biological or clinical claim.",
                "No automatic training or promotion.",
            ],
            "methodConfig": {
                "dataset": "synthetic_structured_8x8_proxy",
                "model": "iterative_visible_residual_correction",
                "baseline": "one_shot_pca_reconstruction",
                "seeds": [42],
                "budget": "CPU-only, one deterministic seed",
                "smokePlan": "predictive_coding_reconstruction_proxy; seed=42",
            },
            "metricContract": {
                "primaryMetric": "reconstruction_mse_delta",
                "metrics": [
                    {
                        "name": "reconstruction_mse_delta",
                        "direction": "maximize",
                    }
                ],
            },
            "decisionContract": {
                "successCriteria": ["reconstruction_mse_delta exceeds 0.001"],
                "failureCriteria": ["reconstruction_mse_delta is not positive"],
                "inconclusiveCriteria": ["the bounded runner is unavailable"],
            },
            "artifactContract": {
                "requiredArtifacts": ["metric summary", "artifact hash"],
            },
            "reproducibilityContract": {
                "seeds": [42],
                "environmentRefs": ["local-cpu"],
            },
        },
    )


def test_plan_derived_engineering_proxy_hypothesis_is_idempotent_and_review_gated(
    tmp_path,
    monkeypatch,
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    source = _draft_complete_proxy_plan(team["teamId"])
    source_plan = source["plan"]
    request = {
        "title": "工程代理假设",
        "hypothesis": (
            "在固定 seed 与相同合成数据下，当前候选重建流程相对固定 baseline "
            "可使 reconstruction_mse_delta 超过预注册阈值。"
        ),
        "claimBoundary": "仅验证实验编排、复现与门禁链路，不支持睡眠、生物神经机制或临床结论。",
        "createdByAgent": "Experiment Planning Agent",
        "idempotencyKey": f"{source_plan['planId']}:engineering-proxy",
    }

    created = team_workflow_orchestration_service.materialize_experiment_proxy_hypothesis(
        team["teamId"],
        source_plan["planId"],
        request,
    )
    replayed = team_workflow_orchestration_service.materialize_experiment_proxy_hypothesis(
        team["teamId"],
        source_plan["planId"],
        request,
    )
    candidate = created["candidate"]

    assert created["status"] == "created"
    assert replayed["status"] == "reused"
    assert replayed["candidate"]["candidateId"] == candidate["candidateId"]
    assert candidate["metadata"]["output"]["hypothesisKind"] == "engineering_proxy"
    assert candidate["metadata"]["output"]["sourcePlanId"] == source_plan["planId"]
    assert candidate["metadata"]["output"]["claimBoundary"] == request["claimBoundary"]
    assert candidate["metadata"]["output"]["experimentPlan"] == source_plan["experimentPlan"]
    assert candidate["metadata"]["validation"]["valid"] is True
    assert created["hypothesisSummary"]["reviewDecision"] == "unreviewed"
    assert created["hypothesisSummary"]["approvedForExperiment"] is False

    blocked_status = team_workflow_orchestration_service.get_experiment_planning_status(
        team["teamId"]
    )
    assert blocked_status["summary"]["readyHypothesisCandidateCount"] == 0
    with pytest.raises(
        team_workflow_orchestration_service.TeamWorkflowOrchestrationError,
        match="approved",
    ):
        team_workflow_orchestration_service.create_experiment_plan_revision_from_hypothesis(
            team["teamId"],
            source_plan_id=source_plan["planId"],
            hypothesis_candidate_id=candidate["candidateId"],
            created_by_agent="Research Coordination Agent",
            idempotency_key=f"{source_plan['planId']}:{candidate['candidateId']}:revision",
        )

    review = team_workflow_orchestration_service.decide_research_review(
        team["teamId"],
        {
            "candidateIds": [candidate["candidateId"]],
            "decision": "approve",
            "reviewedByAgent": "Research Coordination Agent",
            "comments": "The proxy boundary and frozen controls are explicit.",
        },
    )
    approved_status = team_workflow_orchestration_service.get_experiment_planning_status(
        team["teamId"]
    )
    approved_candidate = approved_status["hypothesisCandidates"][0]

    assert review["decision"] == "approve"
    assert review["experimentStatus"]["summary"]["readyHypothesisCandidateCount"] == 1
    assert review["experimentStatus"]["hypothesisCandidates"][0]["approvedForExperiment"] is True
    assert approved_candidate["reviewDecision"] == "approve"
    assert approved_candidate["approvedForExperiment"] is True
    assert approved_status["summary"]["readyHypothesisCandidateCount"] == 1

    unrelated_source = _draft_complete_proxy_plan(team["teamId"])
    with pytest.raises(
        team_workflow_orchestration_service.TeamWorkflowOrchestrationError,
        match="plan it was derived from",
    ):
        team_workflow_orchestration_service.create_experiment_plan_revision_from_hypothesis(
            team["teamId"],
            source_plan_id=unrelated_source["plan"]["planId"],
            hypothesis_candidate_id=candidate["candidateId"],
            created_by_agent="Research Coordination Agent",
            idempotency_key=(
                f"{unrelated_source['plan']['planId']}:"
                f"{candidate['candidateId']}:wrong-source"
            ),
        )

    revision = (
        team_workflow_orchestration_service.create_experiment_plan_revision_from_hypothesis(
            team["teamId"],
            source_plan_id=source_plan["planId"],
            hypothesis_candidate_id=candidate["candidateId"],
            created_by_agent="Research Coordination Agent",
            idempotency_key=f"{source_plan['planId']}:{candidate['candidateId']}:revision",
        )
    )
    revision_replay = (
        team_workflow_orchestration_service.create_experiment_plan_revision_from_hypothesis(
            team["teamId"],
            source_plan_id=source_plan["planId"],
            hypothesis_candidate_id=candidate["candidateId"],
            created_by_agent="Research Coordination Agent",
            idempotency_key=f"{source_plan['planId']}:{candidate['candidateId']}:revision",
        )
    )

    assert revision["status"] == "created"
    assert revision_replay["status"] == "reused"
    assert revision_replay["plan"]["planId"] == revision["plan"]["planId"]
    assert revision["plan"]["planId"] != source_plan["planId"]
    assert revision["plan"]["experimentContract"]["revision"] == 2
    assert revision["plan"]["experimentContract"]["supersedesPlanId"] == source_plan["planId"]
    assert revision["plan"]["hypothesisCandidateIds"] == [candidate["candidateId"]]
    assert revision["plan"]["designGate"]["status"] == "draft"
    assert revision["plan"]["baselineSelection"]["activeBaselineReady"] is False
    assert revision["plan"]["hypothesisSelection"]["reviewRecordId"] == review["reviewRecord"]["candidateId"]
    assert source_plan["designGate"]["status"] == "draft"


def test_unreviewed_complete_hypothesis_cannot_be_selected_for_new_plan(
    tmp_path,
    monkeypatch,
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    source = _draft_complete_proxy_plan(team["teamId"])
    materialized = team_workflow_orchestration_service.materialize_experiment_proxy_hypothesis(
        team["teamId"],
        source["plan"]["planId"],
        {
            "title": "Unreviewed proxy",
            "hypothesis": "The bounded workflow may beat its fixed baseline.",
            "claimBoundary": "Engineering proxy only; no scientific claim.",
            "createdByAgent": "Experiment Planning Agent",
            "idempotencyKey": "unreviewed-proxy",
        },
    )

    with pytest.raises(
        team_workflow_orchestration_service.TeamWorkflowOrchestrationError,
        match="approved",
    ):
        team_workflow_orchestration_service.create_experiment_plan(
            team["teamId"],
            {
                "stageRoundId": source["plan"]["stageRoundId"],
                "hypothesisCandidateIds": [
                    materialized["candidate"]["candidateId"]
                ],
                "createdByAgent": "Research Coordination Agent",
            },
        )


def test_decide_research_review_reads_local_model_output_experiment_plan(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    hypothesis = team_workflow_orchestration_service.record_local_research_model_output(
        team["teamId"],
        {
            "taskType": "algorithm_hypothesis_draft",
            "output": {
                "candidateType": "algorithm_hypothesis",
                "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
                "evidenceRefs": [{"type": "mapping", "id": "mapping-1", "label": "Mapping 1"}],
                "claims": [{"claim": "Iterative correction may help.", "sourceRef": "mapping-1"}],
                "mechanismMappingIds": ["mapping-1"],
                "hypothesis": "Iterative correction improves reconstruction under corruption.",
                "baseline": "matched feedforward autoencoder",
                "expectedBenefit": "lower reconstruction loss",
                "expectedComputeCost": "three extra correction steps",
                "experimentPlan": {
                    "dataset": "controlled corruption benchmark",
                    "metric": "reconstruction NLL",
                    "baseline": "matched feedforward autoencoder",
                    "smokePlan": "single seed, two epochs",
                },
                "factLayer": ["The source describes a hierarchical generative framing."],
                "inferenceLayer": ["The iterative correction module is a project hypothesis."],
                "uncertainty": ["not experimentally validated"],
                "riskFlags": [],
                "confidence": 0.3,
                "nextAction": "send_to_research_review",
                "requiresReview": True,
            },
        },
    )["candidate"]

    response = team_workflow_orchestration_service.decide_research_review(
        team["teamId"],
        {"candidateIds": [hypothesis["candidateId"]], "decision": "approve"},
    )

    assert response["decision"] == "approve"
    assert response["riskFlags"] == []
    assert response["checklist"][hypothesis["candidateId"]]["testability"] is True

def test_run_experiment_smoke_run_executes_records_and_reproducible(tmp_path, monkeypatch):
    """N-11：对 plan 执行 V1 smoke runner，落账并复现（同 seed → artifactHash 一致）。"""
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    team_workflow_orchestration_service.ensure_team_workflow_orchestration(team["teamId"])
    plan_id = _seed_experiment_plan(team["teamId"])
    res = team_workflow_orchestration_service.run_experiment_smoke_run(team["teamId"], plan_id, {"seed": 42})
    assert res["runnerResult"]["status"] == "completed"
    assert res["runnerResult"]["artifactHash"].startswith("sha256:")
    assert res["status"] in {"passed", "failed", "needs_review"}
    assert res["decisionHint"] in {"accept", "iterate", "reject", "needs_full_run"}
    res2 = team_workflow_orchestration_service.run_experiment_smoke_run(team["teamId"], plan_id, {"seed": 42})
    assert res2["runnerResult"]["artifactHash"] == res["runnerResult"]["artifactHash"]

def test_run_experiment_proxy_smoke_cannot_promote_plan_to_passed(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    team_workflow_orchestration_service.ensure_team_workflow_orchestration(team["teamId"])
    plan_id = _seed_experiment_plan(team["teamId"], plan_id="exp_reconstruction_proxy")

    response = team_workflow_orchestration_service.run_experiment_smoke_run(
        team["teamId"],
        plan_id,
        {"adapter": "predictive_coding_reconstruction_proxy", "seed": 42},
    )

    assert response["runnerResult"]["decisionHint"] == "accept"
    assert response["runnerResult"]["proxyOnly"] is True
    assert response["status"] == "needs_review"
    assert response["experimentStatus"] == "smoke_needs_review"
    assert response["smokeRun"]["proxyOnly"] is True
    assert "no_full_run_promotion_from_proxy_only" in response["smokeRun"]["boundaries"]

def test_run_experiment_smoke_run_blocks_missing_baseline(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    plan_id = _seed_experiment_plan(team["teamId"], plan_id="exp_no_baseline", baseline=False)
    with pytest.raises(team_workflow_orchestration_service.TeamWorkflowOrchestrationError):
        team_workflow_orchestration_service.run_experiment_smoke_run(team["teamId"], plan_id, {})

def test_run_experiment_smoke_run_accepts_api_plan_nested_contract(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    plan_store = team_workflow_orchestration_service._load_experiment_plan_store(team["teamId"])
    plan_store["plans"] = [
        {
            "planId": "exp_nested_contract",
            "status": "draft",
            "experimentPlan": {
                "dataset": "synthetic_structured_8x8_proxy",
                "metric": "reconstruction_mse",
                "baseline": "one-shot PCA reconstruction",
                "smokePlan": {"adapter": "predictive_coding_reconstruction_proxy", "seed": 42},
            },
            "updatedAt": "2026-06-25T00:00:00+00:00",
        }
    ]
    plan_store["activePlanId"] = "exp_nested_contract"
    team_workflow_orchestration_service._write_json(
        team_workflow_orchestration_service._experiment_plan_store_path(team["teamId"]),
        plan_store,
    )

    response = team_workflow_orchestration_service.run_experiment_smoke_run(
        team["teamId"],
        "exp_nested_contract",
        {},
    )

    assert response["adapter"] == "predictive_coding_reconstruction_proxy"
    assert response["seed"] == 42
    assert response["status"] == "needs_review"

def test_explicit_design_gate_blocks_smoke_until_plan_is_frozen(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    plan_store = team_workflow_orchestration_service._load_experiment_plan_store(team["teamId"])
    plan_store["plans"] = [
        {
            "planId": "exp_gated_draft",
            "status": "draft",
            "designGate": {"status": "draft", "requiresExplicitFreeze": True},
            "contractValidation": {"valid": True, "missingFields": []},
            "readiness": {"readyForPlanReview": True},
            "experimentPlan": {
                "dataset": "synthetic_structured_8x8_proxy",
                "metric": "reconstruction_mse",
                "baseline": "one-shot PCA reconstruction",
                "smokePlan": {"adapter": "predictive_coding_reconstruction_proxy", "seed": 42},
            },
            "experimentContract": {"schemaVersion": 2, "revision": 2, "status": "draft"},
            "updatedAt": "2026-06-25T00:00:00+00:00",
        }
    ]
    plan_store["activePlanId"] = "exp_gated_draft"
    team_workflow_orchestration_service._write_json(
        team_workflow_orchestration_service._experiment_plan_store_path(team["teamId"]),
        plan_store,
    )

    with pytest.raises(
        team_workflow_orchestration_service.TeamWorkflowOrchestrationError,
        match="frozen",
    ):
        team_workflow_orchestration_service.run_experiment_smoke_run(team["teamId"], "exp_gated_draft", {})
    with pytest.raises(
        team_workflow_orchestration_service.TeamWorkflowOrchestrationError,
        match="frozen",
    ):
        team_workflow_orchestration_service.register_experiment_smoke_result(
            team["teamId"],
            "exp_gated_draft",
            {"status": "passed", "metricName": "reconstruction_mse", "metricValue": "0.1"},
        )

    frozen = team_workflow_orchestration_service.freeze_experiment_design(
        team["teamId"],
        "exp_gated_draft",
        {"frozenByAgent": "Research Coordination Agent"},
    )
    response = team_workflow_orchestration_service.run_experiment_smoke_run(
        team["teamId"],
        "exp_gated_draft",
        {},
    )

    assert frozen["plan"]["designGate"]["status"] == "frozen"
    assert frozen["plan"]["experimentContract"]["status"] == "frozen"
    assert frozen["experimentStatus"]["lifecycleProjection"]["stage2"]["status"] == "frozen"
    assert frozen["experimentStatus"]["lifecycleProjection"]["stage2"]["readyForExecution"] is True
    assert response["status"] == "needs_review"

def test_run_experiment_smoke_run_rejects_non_whitelisted_adapter(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    plan_id = _seed_experiment_plan(team["teamId"], plan_id="exp_bad_adapter")
    with pytest.raises(team_workflow_orchestration_service.TeamWorkflowOrchestrationError):
        team_workflow_orchestration_service.run_experiment_smoke_run(
            team["teamId"], plan_id, {"adapter": "arbitrary_user_code"}
        )

def test_prepare_experiment_full_run_records_preflight_without_starting_execution(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    team_workflow_orchestration_service.ensure_team_workflow_orchestration(team["teamId"])
    plan_id = _seed_formal_full_run_plan(team["teamId"])

    monkeypatch.setattr(
        team_workflow_orchestration_service.formal_runner,
        "prepare_full_run",
        lambda *args, **kwargs: {
            "adapterId": args[0],
            "status": "prepared",
            "seedCount": 3,
            "boundaries": ["user_triggered_only", "manual_result_review_required"],
        },
    )

    response = team_workflow_orchestration_service.prepare_experiment_full_run(
        team["teamId"], plan_id, {"executionConfig": {"pythonExecutable": "C:/runner/python.exe"}}
    )

    assert response["preparation"]["status"] == "prepared"
    assert response["plan"]["status"] == "smoke_passed"
    assert response["boundaries"]["startsFullRun"] is False
    assert response["boundaries"]["requiresResultReview"] is True

def test_execute_experiment_full_run_stores_review_only_artifacts_without_auto_promotion(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")
    team_workflow_orchestration_service.ensure_team_workflow_orchestration(team["teamId"])
    plan_id = _seed_formal_full_run_plan(team["teamId"])

    monkeypatch.setattr(
        team_workflow_orchestration_service.formal_runner,
        "run_full_run",
        lambda *args, **kwargs: {
            "adapterId": args[0],
            "status": "completed",
            "seedCount": 3,
            "resultPath": "C:/experiments/formal-run-result.json",
            "logRef": "C:/experiments/formal-run-log.json",
            "requiresResultReview": True,
            "automaticPromotion": False,
        },
    )

    response = team_workflow_orchestration_service.execute_experiment_full_run(
        team["teamId"], plan_id, {"executionConfig": {"pythonExecutable": "C:/runner/python.exe"}}
    )

    assert response["execution"]["status"] == "completed"
    assert response["execution"]["requiresResultReview"] is True
    assert response["plan"]["status"] == "smoke_passed"
    assert response["plan"]["activeFullRunExecution"]["automaticPromotion"] is False
    assert response["plan"].get("activeFullRunResult") is None

def test_start_experiment_stage_builds_bounded_memory_context_with_negative_shields(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Coordinator", direct_session_id="session-coordinator")
    team = team_service.create_team(
        name="ai科学研究团队",
        members=[{"agentId": agent["agentId"], "role": "research_coordination"}],
    )
    candidate_store = team_workflow_orchestration_service._load_candidate_store(team["teamId"])
    candidate_store["candidates"] = [
        {
            "candidateId": "source-reviewed-1",
            "candidateType": "source_manifest",
            "title": "Reviewed source",
            "currentState": "source_quality_approved",
            "sourceRef": "doi:10.1000/reviewed",
        },
        {
            "candidateId": "hypothesis-ready-1",
            "candidateType": "algorithm_hypothesis",
            "title": "Ready hypothesis",
            "currentState": "hypothesis_candidate",
            "qualityStatus": "prefiltered",
            "claims": [{"claim": "The bounded candidate may improve the masked metric.", "sourceRef": "source-reviewed-1"}],
        },
    ]
    team_workflow_orchestration_service._write_json(
        team_workflow_orchestration_service._candidate_store_path(team["teamId"]),
        candidate_store,
    )
    plan_store = team_workflow_orchestration_service._load_experiment_plan_store(team["teamId"])
    plan_store["plans"] = [
        {
            "planId": "plan-negative-weight-1",
            "title": "weight 1.0 global regression",
            "status": "full_run_needs_review",
            "hypothesisCandidateIds": ["candidate-weight-1"],
            "experimentContract": {
                "schemaVersion": 2,
                "revision": 2,
                "researchQuestion": "Does weight 1.0 improve masked reconstruction?",
                "methodConfig": {
                    "candidateMaskedLossWeight": 1.0,
                    "dataset": "FashionMNIST",
                    "model": "matched autoencoder",
                },
                "constraints": ["same dataset", "same architecture", "only masked loss weight changes"],
                "decisionContract": {"failureCriteria": ["global regression exceeds 0.0005"]},
            },
            "activeFullRunResultId": "full-negative-weight-1",
            "activeFullRunResult": {
                "fullRunResultId": "full-negative-weight-1",
                "status": "needs_review",
                "delta": "global regression",
                "logRef": "artifact:sha256:negative",
            },
        },
        {
            "planId": "plan-best-revision4",
            "title": "weight 0.875 bounded result",
            "status": "ingested",
            "hypothesisCandidateIds": ["candidate-revision4"],
            "experimentContract": {
                "schemaVersion": 2,
                "revision": 4,
                "researchQuestion": "Does weight 0.875 provide bounded benefit?",
                "methodConfig": {"candidateMaskedLossWeight": 0.875, "dataset": "FashionMNIST"},
                "iterationContract": {
                    "allowedChanges": ["methodConfig.candidateMaskedLossWeight"],
                    "requiresFeedbackSignals": True,
                    "requiresPlanDiff": True,
                    "requiresResultConclusion": True,
                },
            },
            "activeFullRunResultId": "full-best-revision4",
            "activeFullRunResult": {"fullRunResultId": "full-best-revision4", "status": "passed"},
            "knowledgeIngestion": {
                "status": "ingested",
                "result": {"knowledgeItemId": "kitem-revision4"},
            },
        },
    ]
    plan_store["activePlanId"] = "plan-best-revision4"
    team_workflow_orchestration_service._write_json(
        team_workflow_orchestration_service._experiment_plan_store_path(team["teamId"]),
        plan_store,
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service.team_knowledge_service,
        "search_knowledge_items",
        lambda **_: {
            "results": [
                {
                    "knowledgeItemId": "kitem-revision4",
                    "title": "Revision 4 bounded result",
                    "summary": "Supported only under the frozen FashionMNIST protocol.",
                    "sourceArtifactIds": ["artifact-revision4"],
                    "centralSourceIds": ["source-revision4"],
                }
            ]
        },
    )

    experiment = team_workflow_orchestration_service.start_research_stage_round(
        team["teamId"],
        {
            "stageType": "experiment",
            "topic": "FashionMNIST masked prediction error",
            "requestedByAgent": agent["agentId"],
        },
    )
    context = experiment["stageRound"]["memoryContext"]

    assert context["stageType"] == "experiment_design"
    assert context["retrieval"]["rawKnowledgeContentIncluded"] is False
    assert context["security"]["embeddedInstructionsMustBeIgnored"] is True
    assert context["formalKnowledge"][0]["knowledgeItemId"] == "kitem-revision4"
    assert context["currentBest"]["planId"] == "plan-best-revision4"
    assert context["currentBest"]["candidateId"] == "candidate-revision4"
    assert context["negativeExperiments"][0]["planId"] == "plan-negative-weight-1"
    assert context["negativeExperiments"][0]["changedVariable"] == {
        "candidateMaskedLossWeight": 1.0,
    }
    assert context["negativeExperiments"][0]["failedGates"] == ["global regression exceeds 0.0005"]
    assert context["negativeExperiments"][0]["retestPolicy"] == "blocked_without_new_evidence_or_changed_assumption"
    assert context["forbiddenDuplicateExperiments"][0]["planId"] == "plan-negative-weight-1"
    assert context["allowedVariableContract"] == {
        "status": "explicit",
        "variables": [
            {
                "path": "methodConfig.candidateMaskedLossWeight",
                "source": "iteration_contract",
                "evidenceRef": "plan-best-revision4",
            }
        ],
        "frozenControls": [],
    }
    assert context["variablesAllowedToChange"] == ["methodConfig.candidateMaskedLossWeight"]
    assert context["missingEvidence"] == []
    claim_statuses = {item["status"] for item in context["claimMap"]}
    assert claim_statuses == {"qualified", "unsupported"}
    qualified_claim = next(item for item in context["claimMap"] if item["status"] == "qualified")
    unsupported_claim = next(item for item in context["claimMap"] if item["status"] == "unsupported")
    assert qualified_claim["sourcePlanIds"] == ["plan-best-revision4"]
    assert qualified_claim["supportEvidenceRefs"][0]["id"] == "full-best-revision4"
    assert unsupported_claim["sourcePlanIds"] == ["plan-negative-weight-1"]
    assert unsupported_claim["counterEvidenceRefs"][0]["id"] == "full-negative-weight-1"
    assert experiment["stageRound"]["planningContract"]["memoryContextId"] == context["contextId"]
    assert experiment["stageRound"]["coordinationContract"]["config"]["memoryContextId"] == context["contextId"]
    assert (
        experiment["stageRound"]["coordinationContract"]["config"]["memoryContext"]["forbiddenDuplicateExperiments"][0]["planId"]
        == "plan-negative-weight-1"
    )
    status = team_workflow_orchestration_service.get_experiment_planning_status(team["teamId"])
    assert status["lifecycleProjection"]["stage2"]["memoryContextSummary"] == {
        "contextId": context["contextId"],
        "knowledgeItemCount": 1,
        "reviewedSourceCount": 1,
        "negativeExperimentCount": 1,
        "successfulRunCount": 1,
        "forbiddenDuplicateExperimentCount": 1,
        "claimCount": 2,
        "claimStatusCounts": {
            "qualified": 1,
            "unsupported": 1,
            "rejected": 0,
            "not_established": 0,
        },
        "allowedVariableCount": 1,
        "allowedVariables": ["methodConfig.candidateMaskedLossWeight"],
        "allowedVariableContract": context["allowedVariableContract"],
        "claimMap": context["claimMap"],
        "claimMapPreview": [
            {
                "claimId": qualified_claim["claimId"],
                "claim": qualified_claim["claim"],
                "status": "qualified",
            },
            {
                "claimId": unsupported_claim["claimId"],
                "claim": unsupported_claim["claim"],
                "status": "unsupported",
            },
        ],
        "missingEvidence": [],
    }

def test_experiment_lifecycle_projection_derives_memory_summary_for_legacy_plans_without_rewriting_history(
    tmp_path,
    monkeypatch,
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="Coordinator",
        direct_session_id="session-coordinator",
    )
    team = team_service.create_team(
        name="ai科学研究团队",
        members=[{"agentId": agent["agentId"], "role": "research_coordination"}],
    )
    candidate_store = team_workflow_orchestration_service._load_candidate_store(team["teamId"])
    candidate_store["candidates"] = [
        {
            "candidateId": "source-reviewed-legacy",
            "candidateType": "source_manifest",
            "title": "Reviewed legacy source",
            "currentState": "source_quality_approved",
            "sourceRef": "doi:10.1000/legacy",
        },
        {
            "candidateId": "candidate-legacy-best",
            "candidateType": "algorithm_hypothesis",
            "title": "Legacy bounded candidate",
            "currentState": "hypothesis_candidate",
            "claims": [{"claim": "The bounded candidate may improve the masked metric.", "sourceRef": "source-reviewed-legacy"}],
        },
    ]
    team_workflow_orchestration_service._write_json(
        team_workflow_orchestration_service._candidate_store_path(team["teamId"]),
        candidate_store,
    )
    plan_store = team_workflow_orchestration_service._load_experiment_plan_store(team["teamId"])
    plan_store["plans"] = [
        {
            "planId": "plan-legacy-negative",
            "title": "Legacy weight 1.0 regression",
            "status": "full_run_needs_review",
            "hypothesisCandidateIds": ["candidate-legacy-negative"],
            "experimentContract": {
                "schemaVersion": 2,
                "revision": 3,
                "researchQuestion": "Does the bounded candidate improve masked reconstruction?",
                "methodConfig": {"candidateMaskedLossWeight": 1.0},
                "decisionContract": {"failureCriteria": ["global regression exceeds 0.0005"]},
            },
            "activeFullRunResult": {
                "fullRunResultId": "full-legacy-negative",
                "status": "needs_review",
                "logRef": "artifact:sha256:legacy-negative",
            },
        },
        {
            "planId": "plan-legacy-best",
            "title": "Legacy bounded result",
            "status": "ingested",
            "hypothesisCandidateIds": ["candidate-legacy-best"],
            "experimentContract": {
                "schemaVersion": 2,
                "revision": 4,
                "researchQuestion": "Does the bounded candidate improve masked reconstruction?",
                "methodConfig": {"candidateMaskedLossWeight": 0.875},
                "constraints": [
                    "same dataset and architecture",
                    "only candidateMaskedLossWeight changes",
                ],
            },
            "contractValidation": {"valid": True},
            "readiness": {"readyForPlanReview": True},
            "activeFullRunResultId": "full-legacy-best",
            "activeFullRunResult": {"fullRunResultId": "full-legacy-best", "status": "passed"},
            "knowledgeIngestion": {
                "status": "ingested",
                "result": {"knowledgeItemId": "kitem-legacy-best"},
            },
        },
    ]
    plan_store["activePlanId"] = "plan-legacy-best"
    team_workflow_orchestration_service._write_json(
        team_workflow_orchestration_service._experiment_plan_store_path(team["teamId"]),
        plan_store,
    )
    knowledge_search_calls: list[dict] = []
    monkeypatch.setattr(
        team_workflow_orchestration_service.team_knowledge_service,
        "search_knowledge_items",
        lambda **kwargs: knowledge_search_calls.append(kwargs)
        or {
            "results": [
                {
                    "knowledgeItemId": "kitem-legacy-best",
                    "title": "Legacy bounded result",
                    "summary": "Supported under the frozen protocol.",
                    "sourceArtifactIds": ["artifact-legacy-best"],
                    "centralSourceIds": ["source-legacy-best"],
                }
            ]
        },
    )

    status = team_workflow_orchestration_service.get_experiment_planning_status(team["teamId"])

    assert status["lifecycleProjection"]["stage2"]["memoryContextSummary"] == {
        "contextId": status["lifecycleProjection"]["stage2"]["memoryContextSummary"]["contextId"],
        "knowledgeItemCount": 1,
        "reviewedSourceCount": 1,
        "negativeExperimentCount": 1,
        "successfulRunCount": 1,
        "forbiddenDuplicateExperimentCount": 1,
        "claimCount": 1,
        "claimStatusCounts": {
            "qualified": 1,
            "unsupported": 0,
            "rejected": 0,
            "not_established": 0,
        },
        "allowedVariableCount": 1,
        "allowedVariables": ["methodConfig.candidateMaskedLossWeight"],
        "allowedVariableContract": status["lifecycleProjection"]["stage2"]["memoryContextSummary"][
            "allowedVariableContract"
        ],
        "claimMap": status["lifecycleProjection"]["stage2"]["memoryContextSummary"]["claimMap"],
        "claimMapPreview": status["lifecycleProjection"]["stage2"]["memoryContextSummary"]["claimMapPreview"],
        "missingEvidence": [],
    }
    assert status["lifecycleProjection"]["stage2"]["memoryContextSummary"]["claimMapPreview"]
    claim_detail = status["lifecycleProjection"]["stage2"]["memoryContextSummary"]["claimMap"][0]
    assert claim_detail["supportEvidenceRefs"][0]["id"] == "full-legacy-best"
    assert claim_detail["counterEvidenceRefs"][0]["id"] == "full-legacy-negative"
    assert set(claim_detail["sourcePlanIds"]) == {"plan-legacy-negative", "plan-legacy-best"}
    assert status["lifecycleProjection"]["stage2"]["memoryContextSummary"]["allowedVariableContract"] == {
        "status": "derived_from_frozen_constraints",
        "variables": [
            {
                "path": "methodConfig.candidateMaskedLossWeight",
                "source": "frozen_constraint",
                "evidenceRef": "plan-legacy-best",
            }
        ],
        "frozenControls": ["same dataset and architecture"],
    }
    assert len(knowledge_search_calls) == 1
    legacy_context = team_workflow_orchestration_service._legacy_research_lifecycle_memory_contexts(
        team_id=team["teamId"],
        candidate_store=candidate_store,
        plans=plan_store["plans"],
        design_plan=plan_store["plans"][1],
        best_plan=plan_store["plans"][1],
        latest_experiment=plan_store["plans"][1],
        latest_iteration=None,
        active_loop=None,
    )["stage2"]
    assert legacy_context["claimMap"][0]["status"] == "qualified"
    assert legacy_context["claimMap"][0]["supportEvidenceRefs"][0]["id"] == "full-legacy-best"
    assert legacy_context["claimMap"][0]["counterEvidenceRefs"][0]["id"] == "full-legacy-negative"
    assert status["lifecycleProjection"]["stage2"]["memoryContextSummary"]["contextId"]
    assert status["lifecycleProjection"]["stage3"]["memoryContextSummary"]["knowledgeItemCount"] == 1
    assert status["lifecycleProjection"]["stage3"]["memoryContextSummary"]["negativeExperimentCount"] == 1
    assert status["lifecycleProjection"]["stage3"]["memoryContextSummary"]["allowedVariables"] == [
        "methodConfig.candidateMaskedLossWeight"
    ]
    persisted_store = team_workflow_orchestration_service._load_experiment_plan_store(team["teamId"])
    assert all("memoryContext" not in plan for plan in persisted_store["plans"])

def test_experiment_plan_draft_uses_ready_algorithm_hypotheses_and_blocks_full_run(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="ai科学研究团队")
    hypothesis = team_workflow_orchestration_service.record_local_research_model_output(
        team["teamId"],
        {
            "taskType": "algorithm_hypothesis_draft",
            "title": "Context gated routing",
            "createdByAgent": "Algorithm Hypothesis Agent",
            "output": {
                "candidateType": "algorithm_hypothesis",
                "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
                "evidenceRefs": [{"type": "mapping", "id": "mapping-1", "label": "Mapping 1"}],
                "claims": [{"claim": "Context-gated routing may improve adaptation.", "sourceRef": "paper-1"}],
                "mechanismMappingIds": ["mapping-1"],
                "hypothesis": "Context-gated routing improves adaptation under shifting tasks.",
                "baseline": "standard MoE router",
                "expectedBenefit": "better task adaptation at equal parameter count",
                "expectedComputeCost": "one small gating MLP and no extra experts",
                "experimentPlan": {
                    "dataset": "synthetic task-switch benchmark",
                    "metric": "validation accuracy and routing entropy",
                    "baseline": "standard MoE router",
                    "smokePlan": "train 200 mini-batches and compare metric direction",
                },
                "uncertainty": [],
                "riskFlags": [],
                "confidence": 0.52,
                "nextAction": "send_to_research_review",
                "requiresReview": True,
            },
        },
    )["candidate"]
    team_workflow_orchestration_service.decide_research_review(
        team["teamId"],
        {
            "candidateIds": [hypothesis["candidateId"]],
            "decision": "approve",
            "reviewedByAgent": "Research Coordination Agent",
        },
    )
    stage = team_workflow_orchestration_service.start_research_stage_round(
        team["teamId"],
        {"stageType": "experiment", "topic": "routing experiment plan"},
    )

    draft = team_workflow_orchestration_service.create_experiment_plan(
        team["teamId"],
        {"stageRoundId": stage["stageRound"]["stageRoundId"], "createdByAgent": "Research Coordination Agent"},
    )
    status = team_workflow_orchestration_service.get_experiment_planning_status(team["teamId"])

    assert draft["plan"]["status"] == "draft"
    assert draft["plan"]["experimentPlan"]["dataset"] == "synthetic task-switch benchmark"
    assert draft["plan"]["experimentPlan"]["metric"] == "validation accuracy and routing entropy"
    assert draft["plan"]["experimentContract"]["schemaVersion"] == 2
    assert draft["plan"]["experimentContract"]["researchMode"] == "full_research_loop"
    assert draft["plan"]["experimentContract"]["experimentMethod"] == "model_training_inference"
    assert draft["plan"]["contractValidation"]["valid"] is False
    assert draft["plan"]["contractValidation"]["missingFields"] == [
        "decisionContract.failureCriteria",
        "decisionContract.inconclusiveCriteria",
        "decisionContract.successCriteria",
        "methodConfig.budget",
        "methodConfig.model",
        "methodConfig.seeds",
    ]
    assert draft["plan"]["baselineSelection"]["activeBaselineReady"] is False
    assert draft["plan"]["readiness"]["readyForPlanReview"] is True
    assert draft["plan"]["readiness"]["readyForSmoke"] is False
    assert "active_baseline_record" in draft["plan"]["readiness"]["blockers"]
    assert draft["stageRound"]["experimentPlanRef"]["planId"] == draft["plan"]["planId"]
    assert draft["stageRound"]["planningContract"]["autoExecution"] is False
    assert status["summary"]["planCount"] == 1
    assert status["summary"]["readyHypothesisCandidateCount"] == 1
    assert any(gap["code"] == "experiment_design_not_review_ready" for gap in status["gaps"])
    assert not any(gap["code"] == "active_baseline_not_registered" for gap in status["gaps"])
    assert status["boundaries"]["autoExecution"] is False
    assert status["boundaries"]["createsExperimentAttempt"] is False


def test_experiment_plan_projects_native_v2_method_fields_into_readiness(
    tmp_path, monkeypatch
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="ai科学研究团队")
    stage = team_workflow_orchestration_service.start_research_stage_round(
        team["teamId"],
        {"stageType": "experiment", "topic": "bounded proxy workflow acceptance"},
    )

    draft = team_workflow_orchestration_service.create_experiment_plan(
        team["teamId"],
        {
            "stageRoundId": stage["stageRound"]["stageRoundId"],
            "createdByAgent": "Experiment Planning Agent",
            "researchQuestion": "Can the bounded offline workflow reproduce its proxy artifact?",
            "researchMode": "hypothesis_and_plan",
            "experimentPurpose": {
                "primaryPurpose": "feasibility",
                "secondaryPurposes": [],
            },
            "experimentMethod": "model_training_inference",
            "requestedAdapterId": "predictive_coding_reconstruction_proxy",
            "methodConfig": {
                "dataset": "synthetic_structured_8x8_proxy",
                "model": "iterative_visible_residual_correction",
                "baseline": "one_shot_pca_reconstruction",
                "seeds": [42],
                "budget": "CPU-only, one deterministic seed",
                "smokePlan": "predictive_coding_reconstruction_proxy; seed=42",
            },
            "metricContract": {
                "primaryMetric": "reconstruction_mse_delta",
                "metrics": [
                    {
                        "name": "reconstruction_mse_delta",
                        "direction": "maximize",
                    }
                ],
            },
            "decisionContract": {
                "successCriteria": ["artifact hash is reproducible"],
                "failureCriteria": ["proxy metric does not improve"],
                "inconclusiveCriteria": ["runner is unavailable"],
            },
        },
    )

    assert draft["plan"]["experimentPlan"] == {
        "dataset": "synthetic_structured_8x8_proxy",
        "metric": "reconstruction_mse_delta",
        "baseline": "one_shot_pca_reconstruction",
        "smokePlan": "predictive_coding_reconstruction_proxy; seed=42",
    }
    assert draft["plan"]["baselineSelection"]["baseline"] == "one_shot_pca_reconstruction"
    assert draft["plan"]["designGate"]["status"] == "draft"
    assert draft["plan"]["designGate"]["requiresExplicitFreeze"] is True
    assert draft["plan"]["designGate"]["source"] == "native_v2_plan"
    checklist = {
        item["item"]: item["status"]
        for item in draft["plan"]["readinessChecklist"]
    }
    assert checklist["dataset"] == "pass"
    assert checklist["metric"] == "pass"
    assert checklist["baseline"] == "pass"
    assert checklist["smoke_plan"] == "pass"
    status = team_workflow_orchestration_service.get_experiment_planning_status(
        team["teamId"]
    )
    assert "algorithm_hypothesis" in status["readiness"]["reason"]
    assert not any(
        gap["code"] == "active_baseline_not_registered"
        for gap in status["gaps"]
    )
    with pytest.raises(
        team_workflow_orchestration_service.TeamWorkflowOrchestrationError,
        match="explicitly frozen",
    ):
        team_workflow_orchestration_service.register_experiment_baseline_artifact(
            team["teamId"],
            draft["plan"]["planId"],
            {
                "artifactPath": "workspace/experiments/baselines/proxy.json",
                "reproductionCommand": "python experiments/run_proxy.py --seed 42",
                "registeredByAgent": "Experiment Planning Agent",
            },
        )


def test_experiment_plan_rejects_blocked_structured_placeholders_as_completed_fields(
    tmp_path, monkeypatch
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="ai科学研究团队")
    stage = team_workflow_orchestration_service.start_research_stage_round(
        team["teamId"],
        {"stageType": "experiment", "topic": "sleep mechanism experiment"},
    )

    draft = team_workflow_orchestration_service.create_experiment_plan(
        team["teamId"],
        {
            "stageRoundId": stage["stageRound"]["stageRoundId"],
            "createdByAgent": "Experiment Planning Agent",
            "dataset": {"status": "blocked", "name": None, "reason": "not selected"},
            "metric": {"status": "draft_blocked", "primaryMetric": None},
            "baseline": {"status": "blocked", "name": None},
            "smokePlan": {"status": "blocked", "protocol": None},
        },
    )

    assert draft["plan"]["experimentPlan"] == {
        "dataset": "",
        "metric": "",
        "baseline": "",
        "smokePlan": "",
    }
    checklist = {
        item["item"]: item["status"]
        for item in draft["plan"]["readinessChecklist"]
    }
    assert checklist["dataset"] == "needs_attention"
    assert checklist["metric"] == "needs_attention"
    assert checklist["baseline"] == "needs_attention"
    assert checklist["smoke_plan"] == "needs_attention"
    assert "{'status':" not in json.dumps(draft["plan"], ensure_ascii=False)


def test_experiment_plan_store_projects_old_structured_placeholders_without_rewrite(
    tmp_path, monkeypatch
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="ai科学研究团队")
    plan_path = team_workflow_orchestration_service._experiment_plan_store_path(
        team["teamId"]
    )
    blocked_repr = "{'status': 'blocked', 'name': None}"
    raw_store = {
        "schemaVersion": 1,
        "storeKind": team_workflow_orchestration_service.EXPERIMENT_PLAN_STORE_KIND,
        "teamId": team["teamId"],
        "activePlanId": "plan-old-structured-placeholder",
        "plans": [
            {
                "planId": "plan-old-structured-placeholder",
                "teamId": team["teamId"],
                "stageRoundId": "stage-old-structured-placeholder",
                "status": "draft",
                "experimentPlan": {
                    "dataset": blocked_repr,
                    "metric": blocked_repr,
                    "baseline": blocked_repr,
                    "smokePlan": blocked_repr,
                },
                "experimentContract": {
                    "schemaVersion": 2,
                    "planId": "plan-old-structured-placeholder",
                    "teamId": team["teamId"],
                    "researchProfileId": "generic-research",
                    "researchMode": "full_research_loop",
                    "purpose": {
                        "primaryPurpose": "feasibility",
                        "secondaryPurposes": [],
                    },
                    "experimentMethod": "model_training_inference",
                    "adapterSelection": {
                        "requestedAdapterId": "",
                        "resolvedAdapterId": "",
                        "resolvedAdapterVersion": "",
                        "selectionSource": "unresolved",
                        "unavailableReason": "No Adapter satisfies required capabilities.",
                    },
                    "researchQuestion": "sleep mechanism experiment",
                    "objective": "",
                    "hypothesisRefs": [],
                    "evidenceRefs": [],
                    "constraints": [],
                    "methodConfig": {
                        "dataset": blocked_repr,
                        "baseline": blocked_repr,
                        "smokePlan": blocked_repr,
                    },
                    "metricContract": {
                        "primaryMetric": blocked_repr,
                        "metrics": [
                            {"name": blocked_repr, "direction": "descriptive"}
                        ],
                    },
                    "decisionContract": {
                        "successCriteria": [],
                        "failureCriteria": [],
                        "inconclusiveCriteria": [],
                    },
                    "artifactContract": {
                        "requiredArtifacts": [],
                        "requiredLogTypes": [],
                    },
                    "reproducibilityContract": {
                        "seeds": [],
                        "captureEnvironment": True,
                        "captureInputHash": True,
                        "captureConfigHash": True,
                        "reproductionCommand": "",
                    },
                    "iterationContract": {
                        "requiresResultConclusion": True,
                        "requiresFeedbackSignals": True,
                        "requiresPlanDiff": True,
                    },
                    "supersedesPlanId": "",
                },
                "selectedHypotheses": [],
                "baselineSelection": {"baseline": blocked_repr},
                "createdAt": "2026-07-29T00:00:00+00:00",
                "updatedAt": "2026-07-29T00:00:00+00:00",
            }
        ],
    }
    team_workflow_orchestration_service._write_json(plan_path, raw_store)

    projected = team_workflow_orchestration_service._load_experiment_plan_store(
        team["teamId"]
    )

    assert projected["plans"][0]["experimentPlan"] == {
        "dataset": "",
        "metric": "",
        "baseline": "",
        "smokePlan": "",
    }
    assert projected["plans"][0]["readiness"]["readyForPlanReview"] is False
    assert (
        projected["plans"][0]["contractMigration"]["projectionRepair"]
        == "structured_placeholder_removed"
    )
    assert team_workflow_orchestration_service._read_json(plan_path) == raw_store


def test_experiment_plan_store_projects_native_v2_contract_without_rewrite(
    tmp_path, monkeypatch
):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="ai科学研究团队")
    plan_path = team_workflow_orchestration_service._experiment_plan_store_path(
        team["teamId"]
    )
    raw_store = {
        "schemaVersion": 2,
        "storeKind": team_workflow_orchestration_service.EXPERIMENT_PLAN_STORE_KIND,
        "teamId": team["teamId"],
        "activePlanId": "plan-native-v2-stale-projection",
        "plans": [
            {
                "planId": "plan-native-v2-stale-projection",
                "teamId": team["teamId"],
                "stageRoundId": "stage-native-v2-stale-projection",
                "status": "draft",
                "experimentPlan": {
                    "dataset": "",
                    "metric": "",
                    "baseline": "",
                    "smokePlan": "",
                },
                "experimentContract": {
                    "schemaVersion": 2,
                    "planId": "plan-native-v2-stale-projection",
                    "teamId": team["teamId"],
                    "status": "draft",
                    "researchMode": "hypothesis_and_plan",
                    "experimentMethod": "model_training_inference",
                    "methodConfig": {
                        "dataset": "synthetic_structured_8x8_proxy",
                        "model": "iterative_visible_residual_correction",
                        "baseline": "one_shot_pca_reconstruction",
                        "seeds": [42],
                        "budget": "CPU-only, one deterministic seed",
                        "smokePlan": "predictive_coding_reconstruction_proxy; seed=42",
                    },
                    "metricContract": {
                        "primaryMetric": "reconstruction_mse_delta",
                        "metrics": [
                            {
                                "name": "reconstruction_mse_delta",
                                "direction": "maximize",
                            }
                        ],
                    },
                    "decisionContract": {
                        "successCriteria": ["artifact hash is reproducible"],
                        "failureCriteria": ["proxy metric does not improve"],
                        "inconclusiveCriteria": ["runner is unavailable"],
                    },
                },
                "contractValidation": {"valid": True, "missingFields": []},
                "selectedHypotheses": [{"candidateId": "candidate-proxy"}],
                "baselineSelection": {"baseline": "", "status": "missing"},
                "createdAt": "2026-07-30T00:00:00+00:00",
                "updatedAt": "2026-07-30T00:00:00+00:00",
            }
        ],
    }
    team_workflow_orchestration_service._write_json(plan_path, raw_store)

    projected = team_workflow_orchestration_service._load_experiment_plan_store(
        team["teamId"]
    )
    projected_plan = projected["plans"][0]

    assert projected_plan["experimentPlan"] == {
        "dataset": "synthetic_structured_8x8_proxy",
        "metric": "reconstruction_mse_delta",
        "baseline": "one_shot_pca_reconstruction",
        "smokePlan": "predictive_coding_reconstruction_proxy; seed=42",
    }
    checklist = {
        item["item"]: item["status"]
        for item in projected_plan["readinessChecklist"]
    }
    assert checklist["dataset"] == "pass"
    assert checklist["metric"] == "pass"
    assert checklist["baseline"] == "pass"
    assert checklist["smoke_plan"] == "pass"
    assert (
        projected_plan["contractMigration"]["projectionRepair"]
        == "canonical_contract_projected"
    )
    assert projected_plan["designGate"]["status"] == "draft"
    assert projected_plan["designGate"]["requiresExplicitFreeze"] is True
    assert projected_plan["designGate"]["source"] == "native_v2_plan"
    assert team_workflow_orchestration_service._read_json(plan_path) == raw_store


def test_experiment_status_separates_frozen_design_best_result_and_latest_diagnostic(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(team_workflow_orchestration_service, "load_public_config", lambda: {"llm": {"providers": {}}})
    team = team_service.create_team(name="ai科学研究团队")
    stage = team_workflow_orchestration_service.start_research_stage_round(
        team["teamId"],
        {"stageType": "experiment", "topic": "masked prediction error"},
    )
    store = team_workflow_orchestration_service._load_experiment_plan_store(team["teamId"])
    store["plans"] = [
        {
            "planId": "exp_revision4",
            "status": "ingested",
            "title": "weight 0.875 bounded confirmation",
            "createdAt": "2026-07-18T00:59:23+08:00",
            "updatedAt": "2026-07-18T20:54:13+08:00",
            "stageRoundId": stage["stageRound"]["stageRoundId"],
            "hypothesisCandidateIds": ["candidate_revision4"],
            "experimentContract": {"schemaVersion": 2, "revision": 4, "status": "result_review"},
            "contractValidation": {"valid": True, "missingFields": []},
            "readiness": {
                "readyForPlanReview": True,
                "readyForSmoke": True,
                "readyForFullRun": True,
                "readyForKnowledgeIngestion": True,
            },
            "activeFullRunResultId": "full_revision4",
            "activeFullRunResult": {"fullRunResultId": "full_revision4", "status": "passed"},
            "knowledgeIngestion": {
                "status": "ingested",
                "result": {"knowledgeItemId": "kitem_revision4"},
            },
        },
        {
            "planId": "exp_diagnostic_revision12",
            "status": "smoke_needs_review",
            "title": "2 to 8 epoch fidelity diagnostic",
            "createdAt": "2026-07-19T20:26:18+08:00",
            "updatedAt": "2026-07-19T20:32:29+08:00",
            "stageRoundId": stage["stageRound"]["stageRoundId"],
            "hypothesisCandidateIds": ["candidate_diagnostic"],
            "experimentContract": {"schemaVersion": 2, "revision": 12, "status": "smoke_review"},
            "contractValidation": {"valid": True, "missingFields": []},
            "readiness": {
                "readyForPlanReview": True,
                "readyForSmoke": True,
                "readyForFullRun": False,
                "readyForKnowledgeIngestion": False,
            },
            "activeSmokeResultId": "smoke_diagnostic",
            "activeSmokeResult": {"smokeResultId": "smoke_diagnostic", "status": "needs_review"},
        },
    ]
    store["activePlanId"] = "exp_diagnostic_revision12"
    team_workflow_orchestration_service._write_json(
        team_workflow_orchestration_service._experiment_plan_store_path(team["teamId"]),
        store,
    )
    loop_path = team_workflow_orchestration_service._team_workflow_root(team["teamId"]) / "research_loops" / "index.json"
    team_workflow_orchestration_service._write_json(
        loop_path,
        {
            "schemaVersion": 1,
            "storeKind": "team_research_loop_store",
            "teamId": team["teamId"],
            "activeLoopId": "loop_external_validity",
            "loops": [
                {
                    "loopId": "loop_external_validity",
                    "status": "accepted_for_writeup",
                    "title": "full dataset external validity",
                    "updatedAt": "2026-07-19T21:55:12+08:00",
                    "linkedExperiment": {
                        "planId": "exp_revision4",
                        "candidateIds": ["candidate_revision4"],
                    },
                    "evidenceRecords": [
                        {
                            "evidenceId": "benchmark_revision4_external",
                            "evidenceType": "benchmark_result",
                            "status": "passed",
                        }
                    ],
                    "decisions": [
                        {
                            "decisionId": "decision_accept_revision4",
                            "decision": "accept_for_writeup",
                            "statusAfterDecision": "accepted_for_writeup",
                        }
                    ],
                }
            ],
        },
    )

    status = team_workflow_orchestration_service.get_experiment_planning_status(team["teamId"])
    lifecycle = status["lifecycleProjection"]
    challenge_program = status["challengeProgramProjection"]

    assert status["summary"]["activePlanId"] == "exp_diagnostic_revision12"
    assert lifecycle["stage2"]["status"] == "frozen"
    assert lifecycle["stage2"]["activeDesignPlanId"] == "exp_diagnostic_revision12"
    assert lifecycle["stage2"]["frozenDesignRevision"] == 12
    assert lifecycle["stage3"]["status"] == "accepted_for_writeup"
    assert lifecycle["stage3"]["activeIterationId"] == "loop_external_validity"
    assert lifecycle["stage3"]["bestCandidateId"] == "candidate_revision4"
    assert lifecycle["stage3"]["bestValidatedResultId"] == "benchmark_revision4_external"
    assert lifecycle["stage3"]["bestValidatedPlanId"] == "exp_revision4"
    assert lifecycle["stage3"]["latestDiagnosticStatus"] == {
        "planId": "exp_diagnostic_revision12",
        "revision": 12,
        "status": "smoke_needs_review",
        "title": "2 to 8 epoch fidelity diagnostic",
    }
    assert challenge_program["program"]["officialQuestionCount"] == 125
    assert challenge_program["stage1ComplianceReadiness"]["status"] == "blocked"
    assert "dashscope_qwen_provider_missing" in challenge_program["stage1ComplianceReadiness"]["blockers"]
    assert challenge_program["stage2BatchGovernance"]["status"] == "blocked_by_stage1"
    assert challenge_program["stage2BatchGovernance"]["batchCount"] == 25
    assert challenge_program["stage2BatchGovernance"]["batchSize"] == 5
    assert challenge_program["stage3DeepResearchDelivery"]["status"] == "partial"
    assert challenge_program["stage3DeepResearchDelivery"]["representativeCaseCount"] == 1
    assert challenge_program["stage3DeepResearchDelivery"]["requiredRepresentativeCaseCount"] == 3
    assert challenge_program["stage3DeepResearchDelivery"]["caseRecords"][0]["internalStatus"] == "accepted_for_writeup"
    assert challenge_program["stage3DeepResearchDelivery"]["caseRecords"][0]["projectCompletionStatus"] == "case_only"
    assert challenge_program["compatibility"]["legacyLifecycleProjectionPreserved"] is True
    assert challenge_program["compatibility"]["historyRewritten"] is False

def test_experiment_design_can_be_frozen_without_any_training_result(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="ai科学研究团队")
    stage = team_workflow_orchestration_service.start_research_stage_round(
        team["teamId"],
        {"stageType": "experiment", "topic": "frozen design only"},
    )
    store = team_workflow_orchestration_service._load_experiment_plan_store(team["teamId"])
    store["plans"] = [
        {
            "planId": "exp_frozen_without_run",
            "status": "draft",
            "title": "preregistered executable design",
            "createdAt": "2026-07-19T20:00:00+08:00",
            "updatedAt": "2026-07-19T20:00:00+08:00",
            "stageRoundId": stage["stageRound"]["stageRoundId"],
            "hypothesisCandidateIds": ["candidate_preregistered"],
            "experimentContract": {"schemaVersion": 2, "revision": 3, "status": "ready_for_prepare"},
            "contractValidation": {"valid": True, "missingFields": []},
            "readiness": {
                "readyForPlanReview": True,
                "readyForSmoke": False,
                "readyForFullRun": False,
                "readyForKnowledgeIngestion": False,
            },
        }
    ]
    store["activePlanId"] = "exp_frozen_without_run"
    team_workflow_orchestration_service._write_json(
        team_workflow_orchestration_service._experiment_plan_store_path(team["teamId"]),
        store,
    )

    status = team_workflow_orchestration_service.get_experiment_planning_status(team["teamId"])
    lifecycle = status["lifecycleProjection"]

    assert lifecycle["stage2"]["status"] == "frozen"
    assert lifecycle["stage2"]["activeDesignPlanId"] == "exp_frozen_without_run"
    assert lifecycle["stage2"]["frozenDesignRevision"] == 3
    assert lifecycle["stage2"]["readyForExecution"] is True
    assert lifecycle["stage3"]["status"] == "not_started"
    assert lifecycle["stage3"]["bestValidatedResultId"] == ""

def test_experiment_baseline_artifact_registration_unlocks_smoke_gate(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="ai科学研究团队")
    hypothesis = team_workflow_orchestration_service.record_local_research_model_output(
        team["teamId"],
        {
            "taskType": "algorithm_hypothesis_draft",
            "title": "Context gated routing",
            "createdByAgent": "Algorithm Hypothesis Agent",
            "output": {
                "candidateType": "algorithm_hypothesis",
                "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
                "evidenceRefs": [{"type": "mapping", "id": "mapping-1", "label": "Mapping 1"}],
                "claims": [{"claim": "Context-gated routing may improve adaptation.", "sourceRef": "paper-1"}],
                "mechanismMappingIds": ["mapping-1"],
                "hypothesis": "Context-gated routing improves adaptation under shifting tasks.",
                "baseline": "standard MoE router",
                "expectedBenefit": "better task adaptation at equal parameter count",
                "expectedComputeCost": "one small gating MLP and no extra experts",
                "experimentPlan": {
                    "dataset": "synthetic task-switch benchmark",
                    "metric": "validation accuracy and routing entropy",
                    "baseline": "standard MoE router",
                    "smokePlan": "train 200 mini-batches and compare metric direction",
                },
                "uncertainty": [],
                "riskFlags": [],
                "confidence": 0.52,
                "nextAction": "send_to_research_review",
                "requiresReview": True,
            },
        },
    )["candidate"]
    team_workflow_orchestration_service.decide_research_review(
        team["teamId"],
        {
            "candidateIds": [hypothesis["candidateId"]],
            "decision": "approve",
            "reviewedByAgent": "Research Coordination Agent",
        },
    )
    stage = team_workflow_orchestration_service.start_research_stage_round(
        team["teamId"],
        {"stageType": "experiment", "topic": "routing experiment plan"},
    )
    draft = team_workflow_orchestration_service.create_experiment_plan(
        team["teamId"],
        {
            "stageRoundId": stage["stageRound"]["stageRoundId"],
            "createdByAgent": "Research Coordination Agent",
            "researchQuestion": "Can context-gated routing improve adaptation?",
            "researchMode": "full_research_loop",
            "experimentMethod": "model_training_inference",
            "requestedAdapterId": "predictive_coding_reconstruction_proxy",
            "methodConfig": {
                "dataset": "synthetic task-switch benchmark",
                "model": "context-gated router",
                "baseline": "standard MoE router",
                "seeds": [42],
                "budget": "CPU-only bounded smoke",
                "smokePlan": "train 200 mini-batches and compare metric direction",
            },
            "metricContract": {
                "primaryMetric": "validation accuracy and routing entropy",
                "metrics": [
                    {
                        "name": "validation accuracy and routing entropy",
                        "direction": "maximize",
                    }
                ],
            },
            "decisionContract": {
                "successCriteria": ["proxy metric improves"],
                "failureCriteria": ["proxy metric regresses"],
                "inconclusiveCriteria": ["proxy runner is unavailable"],
            },
        },
    )
    frozen = team_workflow_orchestration_service.freeze_experiment_design(
        team["teamId"],
        draft["plan"]["planId"],
        {"frozenByAgent": "Experiment Planning Agent"},
    )

    registered = team_workflow_orchestration_service.register_experiment_baseline_artifact(
        team["teamId"],
        draft["plan"]["planId"],
        {
            "artifactPath": "workspace/experiments/baselines/standard-moe-router.json",
            "reproductionCommand": "python experiments/run_baseline.py --config configs/standard_moe_router.yaml",
            "evaluationCommand": "python experiments/evaluate.py --run standard-moe-router",
            "metricValue": "0.71 validation accuracy",
            "registeredByAgent": "Experiment Planning Agent",
        },
    )
    status = team_workflow_orchestration_service.get_experiment_planning_status(team["teamId"])

    assert registered["baselineArtifact"]["artifactPath"].endswith("standard-moe-router.json")
    assert frozen["plan"]["designGate"]["status"] == "frozen"
    assert registered["plan"]["status"] == "baseline_ready"
    assert registered["plan"]["experimentContract"]["status"] == "ready_for_prepare"
    assert registered["plan"]["baselineSelection"]["activeBaselineReady"] is True
    assert registered["plan"]["baselineSelection"]["activeBaselineArtifactId"] == registered["baselineArtifact"]["artifactId"]
    assert registered["plan"]["readiness"]["readyForSmoke"] is True
    assert registered["plan"]["readiness"]["readyForFullRun"] is False
    assert "active_baseline_record" not in registered["plan"]["readiness"]["blockers"]
    assert "smoke_result" in registered["plan"]["readiness"]["blockers"]
    assert registered["stageRoundStatus"]["phases"][1]["latestRound"]["planningContract"]["readyForSmoke"] is True
    assert status["status"] == "ready_for_smoke"
    assert status["readiness"]["readyForSmoke"] is True
    assert not any(gap["code"] == "active_baseline_not_registered" for gap in status["gaps"])
    assert any(gap["code"] == "smoke_result_not_recorded" for gap in status["gaps"])
    assert status["boundaries"]["createsExperimentAttempt"] is False

    proxy = team_workflow_orchestration_service.run_experiment_smoke_run(
        team["teamId"],
        draft["plan"]["planId"],
        {"adapter": "predictive_coding_reconstruction_proxy", "seed": 42},
    )
    status_after_proxy = team_workflow_orchestration_service.get_experiment_planning_status(team["teamId"])

    assert proxy["status"] == "needs_review"
    assert any(gap["code"] == "smoke_result_not_passed" for gap in status_after_proxy["gaps"])
    assert not any(gap["code"] == "smoke_result_not_recorded" for gap in status_after_proxy["gaps"])
    assert "smoke result 已登记但尚未通过" in status_after_proxy["readiness"]["reason"]

def test_experiment_baseline_artifact_requires_artifact_path(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="ai科学研究团队")
    stage = team_workflow_orchestration_service.start_research_stage_round(
        team["teamId"],
        {"stageType": "experiment", "topic": "routing experiment plan"},
    )
    draft = team_workflow_orchestration_service.create_experiment_plan(
        team["teamId"],
        {
            "stageRoundId": stage["stageRound"]["stageRoundId"],
            "dataset": "synthetic task-switch benchmark",
            "metric": "validation accuracy",
            "baseline": "standard MoE router",
            "smokePlan": "train 200 mini-batches",
        },
    )

    with pytest.raises(team_workflow_orchestration_service.TeamWorkflowOrchestrationError, match="Baseline artifact path is required"):
        team_workflow_orchestration_service.register_experiment_baseline_artifact(
            team["teamId"],
            draft["plan"]["planId"],
            {"reproductionCommand": "python experiments/run_baseline.py"},
        )

def test_experiment_smoke_result_registration_unlocks_full_run_gate(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="ai科学研究团队")
    prepared = _create_experiment_plan_with_active_baseline(team["teamId"])

    registered = team_workflow_orchestration_service.register_experiment_smoke_result(
        team["teamId"],
        prepared["baseline"]["plan"]["planId"],
        {
            "status": "passed",
            "metricValue": "0.75 validation accuracy",
            "baselineMetricValue": "0.71 validation accuracy",
            "delta": "+0.04 accuracy",
            "resultPath": "workspace/experiments/smoke/context-gated-routing.json",
            "logRef": "logs/experiments/context-gated-routing-smoke.log",
            "evaluationCommand": "python experiments/evaluate.py --run context-gated-routing-smoke",
            "recordedByAgent": "Experiment Planning Agent",
        },
    )
    status = team_workflow_orchestration_service.get_experiment_planning_status(team["teamId"])

    assert registered["smokeResult"]["status"] == "passed"
    assert registered["smokeResult"]["gateDecision"] == "promote_to_full_run"
    assert registered["plan"]["status"] == "smoke_passed"
    assert registered["plan"]["experimentContract"]["status"] == "ready_for_full_run"
    assert registered["plan"]["activeSmokeResultId"] == registered["smokeResult"]["smokeResultId"]
    assert registered["plan"]["readiness"]["readyForSmoke"] is True
    assert registered["plan"]["readiness"]["readyForFullRun"] is True
    assert registered["plan"]["readiness"]["blockers"] == []
    assert registered["stageRoundStatus"]["phases"][1]["latestRound"]["planningContract"]["readyForFullRun"] is True
    assert status["status"] == "ready_for_full_run"
    assert status["readiness"]["readyForFullRun"] is True
    assert not any(gap["code"] == "smoke_result_not_recorded" for gap in status["gaps"])
    assert status["boundaries"]["createsExperimentAttempt"] is False

def test_experiment_smoke_result_failed_status_keeps_full_run_blocked(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="ai科学研究团队")
    prepared = _create_experiment_plan_with_active_baseline(team["teamId"])

    registered = team_workflow_orchestration_service.register_experiment_smoke_result(
        team["teamId"],
        prepared["baseline"]["plan"]["planId"],
        {
            "status": "failed",
            "metricValue": "0.65 validation accuracy",
            "resultPath": "workspace/experiments/smoke/context-gated-routing-failed.json",
            "recordedByAgent": "Experiment Planning Agent",
        },
    )
    status = team_workflow_orchestration_service.get_experiment_planning_status(team["teamId"])

    assert registered["smokeResult"]["gateDecision"] == "reject_or_repair"
    assert registered["plan"]["readiness"]["readyForSmoke"] is True
    assert registered["plan"]["readiness"]["readyForFullRun"] is False
    assert registered["plan"]["readiness"]["blockers"] == ["smoke_result"]
    assert status["status"] == "ready_for_smoke"
    assert any(gap["code"] == "smoke_result_not_passed" for gap in status["gaps"])

def test_experiment_smoke_result_requires_active_baseline_artifact(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="ai科学研究团队")
    stage = team_workflow_orchestration_service.start_research_stage_round(
        team["teamId"],
        {"stageType": "experiment", "topic": "routing experiment plan"},
    )
    draft = team_workflow_orchestration_service.create_experiment_plan(
        team["teamId"],
        {
            "stageRoundId": stage["stageRound"]["stageRoundId"],
            "dataset": "synthetic task-switch benchmark",
            "metric": "validation accuracy",
            "baseline": "standard MoE router",
            "smokePlan": "train 200 mini-batches",
        },
    )

    with pytest.raises(team_workflow_orchestration_service.TeamWorkflowOrchestrationError, match="Register an active baseline artifact"):
        team_workflow_orchestration_service.register_experiment_smoke_result(
            team["teamId"],
            draft["plan"]["planId"],
            {"status": "passed", "metricValue": "0.75", "resultPath": "workspace/experiments/smoke/result.json"},
        )

def test_experiment_full_run_result_registration_tracks_ledger_without_official_ingestion(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="ai科学研究团队")
    prepared = _create_experiment_plan_with_active_baseline(team["teamId"])
    smoke = team_workflow_orchestration_service.register_experiment_smoke_result(
        team["teamId"],
        prepared["baseline"]["plan"]["planId"],
        {
            "status": "passed",
            "metricValue": "0.75 validation accuracy",
            "resultPath": "workspace/experiments/smoke/context-gated-routing.json",
            "recordedByAgent": "Experiment Planning Agent",
        },
    )

    registered = team_workflow_orchestration_service.register_experiment_full_run_result(
        team["teamId"],
        smoke["plan"]["planId"],
        {
            "status": "passed",
            "metricName": "validation accuracy",
            "metricValue": "0.79 validation accuracy",
            "baselineMetricValue": "0.71 validation accuracy",
            "smokeMetricValue": "0.75 validation accuracy",
            "delta": "+0.08 accuracy",
            "resultPath": "workspace/experiments/full_run/context-gated-routing.json",
            "logRef": "logs/experiments/context-gated-routing-full-run.log",
            "configPath": "workspace/experiments/full_run/context-gated-routing-config.json",
            "recordedByAgent": "Experiment Planning Agent",
        },
    )
    status = team_workflow_orchestration_service.get_experiment_planning_status(team["teamId"])

    assert registered["fullRunResult"]["status"] == "passed"
    assert registered["fullRunResult"]["gateDecision"] == "ready_for_knowledge_review"
    assert registered["fullRunResult"]["smokeResultId"] == smoke["smokeResult"]["smokeResultId"]
    assert registered["plan"]["status"] == "full_run_passed"
    assert registered["plan"]["experimentContract"]["status"] == "result_review"
    assert registered["plan"]["activeFullRunResultId"] == registered["fullRunResult"]["fullRunResultId"]
    assert registered["plan"]["readiness"]["readyForFullRun"] is True
    assert registered["plan"]["readiness"]["readyForKnowledgeIngestion"] is True
    assert registered["plan"]["readiness"]["knowledgeBlockers"] == []
    assert registered["stageRoundStatus"]["phases"][1]["latestRound"]["planningContract"]["readyForKnowledgeIngestion"] is True
    assert status["status"] == "ready_for_knowledge_ingestion"
    assert status["summary"]["activeFullRunResultId"] == registered["fullRunResult"]["fullRunResultId"]
    assert status["boundaries"]["writesFormalKnowledge"] is False
    assert status["boundaries"]["writesRag"] is False
    assert status["boundaries"]["writesOfficialGraph"] is False

def test_experiment_full_run_result_requires_passing_smoke_result(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="ai科学研究团队")
    prepared = _create_experiment_plan_with_active_baseline(team["teamId"])

    with pytest.raises(team_workflow_orchestration_service.TeamWorkflowOrchestrationError, match="passing smoke result"):
        team_workflow_orchestration_service.register_experiment_full_run_result(
            team["teamId"],
            prepared["baseline"]["plan"]["planId"],
            {
                "status": "passed",
                "metricValue": "0.79 validation accuracy",
                "resultPath": "workspace/experiments/full_run/context-gated-routing.json",
            },
        )

def test_experiment_result_knowledge_ingestion_request_notifies_steward_agent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    scene_events = _capture_workflow_events(monkeypatch)
    requester = agent_directory_service.create_agent_instance(display_name="Experiment Planning Agent")
    deliveries = []

    def fake_wake(message):
        deliveries.append(message)
        return {
            "wakeRequested": True,
            "wakeStatus": "started",
            "messageId": message["messageId"],
            "targetAgentId": message["targetAgentId"],
            "targetSessionId": message["targetSessionId"],
            "turnId": "turn-experiment-ingest",
            "reason": "",
        }

    monkeypatch.setattr(session_service, "wake_agent_for_inbox_message", fake_wake)
    team = team_service.create_team(name="ai科学研究团队")
    prepared = _create_experiment_plan_with_active_baseline(team["teamId"])
    smoke = team_workflow_orchestration_service.register_experiment_smoke_result(
        team["teamId"],
        prepared["baseline"]["plan"]["planId"],
        {"status": "passed", "metricValue": "0.75", "resultPath": "workspace/experiments/smoke/result.json"},
    )
    full_run = team_workflow_orchestration_service.register_experiment_full_run_result(
        team["teamId"],
        smoke["plan"]["planId"],
        {"status": "passed", "metricValue": "0.79", "resultPath": "workspace/experiments/full_run/result.json"},
    )

    requested = team_workflow_orchestration_service.request_experiment_result_knowledge_ingestion(
        team["teamId"],
        full_run["plan"]["planId"],
        {
            "requestedByAgent": requester["agentId"],
            "knowledgeBaseId": "research-team-experiment-kb",
            "targetDomain": "挑战杯实验结果",
        },
    )
    inbox_messages = agent_directory_service.list_agent_inbox_messages_for_agent(agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID, status="pending")

    assert requested["status"]["status"] == "knowledge_steward_notified"
    assert requested["plan"]["status"] == "knowledge_steward_notified"
    assert requested["experimentResultPack"]["fullRunResultId"] == full_run["fullRunResult"]["fullRunResultId"]
    assert requested["experimentResultPack"]["officialBoundary"]["currentWritesOfficialKnowledge"] is False
    assert requested["experimentResultPack"]["officialBoundary"]["ragUsesCuratedSummaryOnly"] is True
    assert requested["knowledgeStewardActivation"]["status"] == "agent_wake_started"
    assert requested["knowledgeStewardActivation"]["targetAgentId"] == agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID
    assert requested["knowledgeStewardActivation"]["delivery"]["turnId"] == "turn-experiment-ingest"
    assert requested["knowledgeStewardActivation"]["kernel"]["taskId"]
    assert requested["knowledgeStewardActivation"]["kernel"]["outcomeStatus"] == "succeeded"
    assert requested["knowledgeStewardActivation"]["inboxSourceId"]
    assert deliveries and deliveries[0]["kind"] == "challenge_cup_experiment_result_ingestion_request"
    assert "experimentResultPack JSON:" in deliveries[0]["content"]
    assert "knowledge_ingestion_tool" in deliveries[0]["content"]
    assert "不要读取本地 workflow 文件" in deliveries[0]["content"]
    assert (
        requested["knowledgeStewardActivation"]["inboxSourceId"]
        in deliveries[0]["content"]
    )
    tool_metadata = json.loads(deliveries[0]["metadata"]["agentToolMetadataJson"])
    assert (
        tool_metadata["inboxSourceId"]
        == requested["knowledgeStewardActivation"]["inboxSourceId"]
    )
    assert deliveries[0]["metadata"]["sourceSurface"] == "team_workflow"
    assert deliveries[0]["metadata"]["kernelTaskId"] == requested["knowledgeStewardActivation"]["kernel"]["taskId"]
    assert inbox_messages[0]["messageId"] == requested["knowledgeStewardActivation"]["messageId"]
    assert inbox_messages[0]["metadata"]["sourceSurface"] == "team_workflow"
    assert inbox_messages[0]["metadata"]["kernelTaskId"] == requested["knowledgeStewardActivation"]["kernel"]["taskId"]
    assert inbox_messages[0]["metadata"]["experimentResultPackId"] == requested["experimentResultPack"]["packId"]
    assert inbox_messages[0]["metadata"]["fullRunResultId"] == full_run["fullRunResult"]["fullRunResultId"]
    assert json.loads(inbox_messages[0]["metadata"]["agentToolMetadataJson"])[
        "inboxSourceId"
    ] == requested["knowledgeStewardActivation"]["inboxSourceId"]
    staged_sources = team_knowledge_service.list_owner_source_inbox(
        "team",
        team["teamId"],
        agent_id=agent_directory_service.KNOWLEDGE_STEWARD_AGENT_ID,
        status="pending",
    )
    assert (
        staged_sources["sources"][0]["inboxSourceId"]
        == requested["knowledgeStewardActivation"]["inboxSourceId"]
    )
    assert staged_sources["sources"][0]["sourceRef"]["experimentResultPackId"] == (
        requested["experimentResultPack"]["packId"]
    )
    notification_events = _workflow_scene_events_by_code(scene_events, "experiment_plan.steward_notification_completed")
    assert notification_events
    assert notification_events[-1]["fields"]["status"] == "agent_wake_started"
    assert notification_events[-1]["fields"]["experimentResultPackId"] == requested["experimentResultPack"]["packId"]
    assert notification_events[-1]["child_log_payload"]["kind"] == "experiment_result_steward_notification"
    assert notification_events[-1]["child_log_payload"]["turnId"] == "turn-experiment-ingest"
    assert notification_events[-1]["child_log_payload"]["fullRunResultId"] == full_run["fullRunResult"]["fullRunResultId"]

def test_direct_experiment_ingestion_reconciles_plan_ledger_once(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    scene_events = _capture_workflow_events(monkeypatch)
    requester = agent_directory_service.create_agent_instance(display_name="Experiment Planning Agent")
    steward = agent_directory_service.create_agent_instance(display_name="Knowledge Steward")
    team = team_service.create_team(
        name="ai科学研究团队",
        members=[
            {"agentId": requester["agentId"], "role": "member"},
            {"agentId": steward["agentId"], "role": "lead"},
        ],
    )
    knowledge_base = team_knowledge_service.create_knowledge_base(
        team["teamId"],
        name="Experiment Results",
        actor_agent_id=steward["agentId"],
    )
    knowledge_base_ref = knowledge_base.get("scopedKnowledgeBaseId") or knowledge_base["knowledgeBaseId"]
    agent_directory_service.update_agent_instance(
        steward["agentId"],
        tool_policy={"allowedTools": ["knowledge_ingestion_tool"]},
        memory_policy={"proposeKnowledgeBaseIds": [knowledge_base_ref]},
    )
    monkeypatch.setattr(
        session_service,
        "wake_agent_for_inbox_message",
        lambda message: {
            "wakeRequested": True,
            "wakeStatus": "started",
            "messageId": message["messageId"],
            "targetAgentId": message["targetAgentId"],
            "targetSessionId": message["targetSessionId"],
            "turnId": "turn-experiment-ingest",
            "reason": "",
        },
    )
    prepared = _create_experiment_plan_with_active_baseline(team["teamId"])
    smoke = team_workflow_orchestration_service.register_experiment_smoke_result(
        team["teamId"],
        prepared["baseline"]["plan"]["planId"],
        {"status": "passed", "metricValue": "0.75", "resultPath": "workspace/experiments/smoke/result.json"},
    )
    full_run = team_workflow_orchestration_service.register_experiment_full_run_result(
        team["teamId"],
        smoke["plan"]["planId"],
        {"status": "passed", "metricValue": "0.79", "resultPath": "workspace/experiments/full_run/result.json"},
    )
    requested = team_workflow_orchestration_service.request_experiment_result_knowledge_ingestion(
        team["teamId"],
        full_run["plan"]["planId"],
        {
            "requestedByAgent": requester["agentId"],
            "stewardAgentId": steward["agentId"],
            "knowledgeBaseId": knowledge_base_ref,
            "targetDomain": "挑战杯实验结果",
        },
    )
    inbox_source_id = requested["knowledgeStewardActivation"]["inboxSourceId"]

    with agent_directory_service.active_agent_runtime(steward["agentId"], session_id="session-experiment-ingestion"):
        result = json.loads(
            team_knowledge_tools.knowledge_ingestion_tool(
                knowledge_base_id=knowledge_base_ref,
                source_type="runtime_evidence_refinement",
                source_ref_json=json.dumps(
                    {
                        "experimentResultPackId": requested["experimentResultPack"]["packId"],
                        "planId": requested["plan"]["planId"],
                    }
                ),
                proposal_title="Bounded experiment result",
                proposal_content="Only the reviewed and bounded experiment conclusion enters formal knowledge.",
                inbox_source_id=inbox_source_id,
                owner_type="team",
                owner_id=team["teamId"],
                review_decision="accepted",
                resolution_note="Evidence is complete and bounded.",
            )
        )

    status = team_workflow_orchestration_service.get_experiment_planning_status(team["teamId"])
    reconciliation = result["workflowReconciliation"]
    ingestion = status["activePlan"]["knowledgeIngestion"]
    direct_ingestion = result["directIngestion"]
    assert result["ok"] is True
    assert result["status"] == "ingested"
    assert reconciliation["status"] == "ingested"
    assert reconciliation["updated"] is True
    assert status["status"] == "ingested"
    assert status["activePlan"]["status"] == "ingested"
    assert ingestion["status"] == "ingested"
    assert ingestion["result"]["inboxSourceId"] == inbox_source_id
    assert ingestion["result"]["knowledgeItemId"] == direct_ingestion["item"]["knowledgeItemId"]
    assert ingestion["result"]["centralSourceId"] == direct_ingestion["item"]["centralSourceIds"][0]
    assert ingestion["result"]["sourceArtifactId"] == direct_ingestion["item"]["sourceArtifactIds"][0]
    assert ingestion["result"]["batchId"] == direct_ingestion["batch"]["batchId"]
    assert status["nextActions"] == ["实验结论已完成正式知识入库；后续迭代应引用该 KnowledgeItem 与证据锚点。"]

    replay = team_workflow_orchestration_service.reconcile_experiment_knowledge_ingestion(
        team["teamId"],
        inbox_source_id=inbox_source_id,
        source_ref=result["review"]["source"]["sourceRef"],
        direct_ingestion=direct_ingestion,
        reconciled_by_agent_id=steward["agentId"],
    )
    items = team_knowledge_service.list_knowledge_items(knowledge_base_ref, agent_id=steward["agentId"])
    assert replay["status"] == "ingested"
    assert replay["updated"] is False
    assert replay["reason"] == "already_reconciled"
    assert items["summary"]["itemCount"] == 1
    assert len(_workflow_scene_events_by_code(scene_events, "experiment_plan.knowledge_ingestion_reconciled")) == 1

    conflicting_direct_ingestion = {
        **direct_ingestion,
        "item": {
            **direct_ingestion["item"],
            "knowledgeItemId": "kitem-conflicting-replay",
        },
    }
    conflict = team_workflow_orchestration_service.reconcile_experiment_knowledge_ingestion(
        team["teamId"],
        inbox_source_id=inbox_source_id,
        source_ref=result["review"]["source"]["sourceRef"],
        direct_ingestion=conflicting_direct_ingestion,
        reconciled_by_agent_id=steward["agentId"],
    )
    status_after_conflict = team_workflow_orchestration_service.get_experiment_planning_status(team["teamId"])
    assert conflict["status"] == "ignored"
    assert conflict["updated"] is False
    assert conflict["reason"] == "conflicting_ingestion_evidence"
    assert (
        status_after_conflict["activePlan"]["knowledgeIngestion"]["result"]["knowledgeItemId"]
        == direct_ingestion["item"]["knowledgeItemId"]
    )

def test_experiment_ingestion_reconciliation_rejects_partial_evidence(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="ai科学研究团队")
    prepared = _create_experiment_plan_with_active_baseline(team["teamId"])
    smoke = team_workflow_orchestration_service.register_experiment_smoke_result(
        team["teamId"],
        prepared["baseline"]["plan"]["planId"],
        {"status": "passed", "metricValue": "0.75", "resultPath": "workspace/experiments/smoke/result.json"},
    )
    full_run = team_workflow_orchestration_service.register_experiment_full_run_result(
        team["teamId"],
        smoke["plan"]["planId"],
        {"status": "passed", "metricValue": "0.79", "resultPath": "workspace/experiments/full_run/result.json"},
    )
    requested = team_workflow_orchestration_service.request_experiment_result_knowledge_ingestion(
        team["teamId"],
        full_run["plan"]["planId"],
        {"wakeStewardAgent": False},
    )
    inbox_source_id = requested["knowledgeStewardActivation"]["inboxSourceId"]

    reconciliation = team_workflow_orchestration_service.reconcile_experiment_knowledge_ingestion(
        team["teamId"],
        inbox_source_id=inbox_source_id,
        source_ref={
            "experimentResultPackId": requested["experimentResultPack"]["packId"],
            "planId": requested["plan"]["planId"],
        },
        direct_ingestion={
            "status": "ingested",
            "item": {"knowledgeItemId": "kitem-partial"},
        },
        reconciled_by_agent_id="Knowledge Steward",
    )
    status = team_workflow_orchestration_service.get_experiment_planning_status(team["teamId"])

    assert reconciliation["status"] == "ignored"
    assert reconciliation["updated"] is False
    assert reconciliation["reason"] == "incomplete_direct_ingestion_evidence"
    assert status["status"] == requested["plan"]["status"]
    assert status["activePlan"]["knowledgeIngestion"]["status"] != "ingested"

def test_algorithm_hypothesis_requires_complete_experiment_plan(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="挑战杯科研团队")

    response = team_workflow_orchestration_service.record_local_research_model_output(
        team["teamId"],
        {
            "taskType": "algorithm_hypothesis_draft",
            "output": {
                "candidateType": "algorithm_hypothesis",
                "sourceRefs": [{"type": "paper", "id": "paper-1", "label": "Paper 1"}],
                "evidenceRefs": [{"type": "mapping", "id": "mapping-1", "label": "Mapping 1"}],
                "claims": [{"claim": "Possible algorithm idea", "sourceRef": "paper-1"}],
                "mechanismMappingIds": ["mapping-1"],
                "hypothesis": "Dynamic routing may help.",
                "baseline": "standard MoE router",
                "expectedBenefit": "better adaptation",
                "expectedComputeCost": "small overhead",
                "experimentPlan": {"dataset": "synthetic task-switch benchmark"},
                "uncertainty": [],
                "riskFlags": [],
                "confidence": 0.38,
                "nextAction": "fix_experiment_plan",
                "requiresReview": True,
            },
        },
    )

    assert response["validation"]["valid"] is False
    assert response["candidate"]["currentState"] == "hypothesis_needs_revision"
    assert any(issue["code"] == "incomplete_experiment_plan" for issue in response["validation"]["issues"])


def test_planning_gap_does_not_claim_complete_active_design_fields_are_missing():
    active_plan = {
        "contractValidation": {"valid": True},
        "readiness": {"readyForPlanReview": False},
        "experimentPlan": {
            "dataset": "synthetic_structured_8x8_proxy",
            "metric": "reconstruction_mse_delta",
            "baseline": "one_shot_pca_reconstruction",
            "smokePlan": "predictive_coding_reconstruction_proxy",
        },
    }

    gaps = team_workflow_orchestration_service._experiment_planning_gaps(
        latest_experiment={"roundId": "round-v2"},
        hypothesis_candidates=[{"candidateId": "H1", "valid": False}],
        ready_hypotheses=[],
        active_plan=active_plan,
    )
    actions = team_workflow_orchestration_service._experiment_planning_next_actions(
        active_plan=active_plan,
        gaps=gaps,
    )

    assert gaps == [
        {
            "code": "incomplete_experiment_plan",
            "severity": "needs_attention",
            "message": "已有算法假设候选，但尚未完成审查或选择；需先修订为可审查状态并选择候选。",
        }
    ]
    assert actions == [
        "Review and select an algorithm_hypothesis candidate that is ready for plan review.",
        "Keep the complete active design contract unchanged unless the selected hypothesis requires a new revision.",
    ]
