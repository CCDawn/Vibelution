import pytest

from core.web.services import research_loop_service, team_service, team_workflow_orchestration_service


def _use_tmp_project_root(tmp_path, monkeypatch):
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(research_loop_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_workflow_orchestration_service, "PROJECT_ROOT", tmp_path)


def _team(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    return team_service.create_team(name="挑战杯科研团队")


def test_research_loop_templates_keep_execution_boundary_manual():
    templates = research_loop_service.list_research_loop_templates()

    assert templates["defaultTemplateId"] == "algorithm_model_experiment"
    assert {item["templateId"] for item in templates["templates"]} >= {
        "algorithm_model_experiment",
        "simulation_experiment",
        "dataset_benchmark",
        "environment_probe",
    }
    assert templates["boundaries"]["autoExecution"] is False
    assert templates["boundaries"]["sandboxRunner"] is False
    assert templates["boundaries"]["trainingRunner"] is False


def test_research_loop_status_and_lookup_are_project_scoped(
    tmp_path, monkeypatch
):
    team = _team(tmp_path, monkeypatch)
    loop_a = research_loop_service.create_research_loop(
        team["teamId"],
        {
            "researchProjectId": "project-a",
            "researchQuestion": "Question A",
        },
    )["loop"]
    research_loop_service.create_research_loop(
        team["teamId"],
        {
            "researchProjectId": "project-b",
            "researchQuestion": "Question B",
        },
    )

    status = research_loop_service.get_research_loop_status(
        team["teamId"],
        research_project_id="project-a",
    )

    assert loop_a["researchProjectId"] == "project-a"
    assert status["researchProjectId"] == "project-a"
    assert [item["loopId"] for item in status["loops"]] == [loop_a["loopId"]]
    assert (
        research_loop_service.require_research_loop(
            team["teamId"],
            loop_a["loopId"],
            research_project_id="project-a",
        )["loopId"]
        == loop_a["loopId"]
    )
    with pytest.raises(research_loop_service.ResearchLoopError, match="does not belong"):
        research_loop_service.require_research_loop(
            team["teamId"],
            loop_a["loopId"],
            research_project_id="project-b",
        )


def test_research_loop_records_template_evidence_and_iteration_decision(tmp_path, monkeypatch):
    team = _team(tmp_path, monkeypatch)
    created = research_loop_service.create_research_loop(
        team["teamId"],
        {
            "templateId": "simulation_experiment",
            "researchQuestion": "Does the routing policy remain stable in a simulated noisy queue?",
            "stageRoundId": "round-exp-1",
            "planId": "plan-1",
            "createdByAgent": "Experiment Planning Agent",
        },
    )
    loop_id = created["loop"]["loopId"]

    assert created["loop"]["templateId"] == "simulation_experiment"
    assert created["loop"]["boundaries"]["autoExecution"] is False
    assert created["loop"]["readiness"]["missingEvidenceTypes"] == [
        "simulation_environment",
        "simulation_result",
        "metric_report",
    ]

    blocked = research_loop_service.record_research_loop_evidence(
        team["teamId"],
        loop_id,
        {
            "evidenceType": "simulation_environment",
            "status": "passed",
            "summary": "Pinned simulator config and seed list.",
            "environmentRefs": ["workspace/sim/config.json"],
            "recordedByAgent": "Experiment Planning Agent",
        },
    )

    assert blocked["loop"]["status"] == "evidence_incomplete"
    assert blocked["loop"]["readiness"]["readyForDecision"] is False

    with pytest.raises(research_loop_service.ResearchLoopError):
        research_loop_service.record_research_loop_decision(
            team["teamId"],
            loop_id,
            {
                "decision": "promote_to_iteration",
                "rationale": "Premature promotion should be blocked.",
                "decidedByAgent": "Research Coordination Agent",
            },
        )

    for evidence_type in ("simulation_result", "metric_report"):
        research_loop_service.record_research_loop_evidence(
            team["teamId"],
            loop_id,
            {
                "evidenceType": evidence_type,
                "status": "passed",
                "summary": f"{evidence_type} recorded manually.",
                "metricName": "stability",
                "metricValue": "0.91",
                "commandPreview": "python run_simulation.py --dry-summary",
                "recordedByAgent": "Experiment Planning Agent",
            },
        )

    decided = research_loop_service.record_research_loop_decision(
        team["teamId"],
        loop_id,
        {
            "decision": "promote_to_iteration",
            "rationale": "Required environment, result, and metric evidence are recorded.",
            "nextTemplateId": "dataset_benchmark",
            "nextActions": ["compare on held-out benchmark split"],
            "decidedByAgent": "Research Coordination Agent",
        },
    )

    assert decided["loop"]["status"] == "ready_for_iteration"
    assert decided["loop"]["readiness"]["readyForDecision"] is True
    assert decided["iterationProposal"]["nextTemplateId"] == "dataset_benchmark"
    assert decided["iterationProposal"]["executionPolicy"]["externalExecution"] is False


def test_iteration_decision_can_idempotently_create_next_design_draft(tmp_path, monkeypatch):
    team = _team(tmp_path, monkeypatch)
    stage = team_workflow_orchestration_service.start_research_stage_round(
        team["teamId"],
        {"stageType": "experiment", "topic": "bounded routing experiment"},
    )
    plan_store = team_workflow_orchestration_service._load_experiment_plan_store(team["teamId"])
    plan_store["plans"] = [
        {
            "planId": "plan-v4",
            "stageRoundId": stage["stageRound"]["stageRoundId"],
            "title": "validated design v4",
            "status": "ingested",
            "hypothesisCandidateIds": [],
            "experimentPlan": {
                "dataset": "dataset-v1",
                "metric": "macro_f1",
                "baseline": "baseline-v1",
                "smokePlan": "paired smoke",
            },
            "experimentContract": {
                "schemaVersion": 2,
                "revision": 4,
                "researchProfileId": "generic-research",
                "researchMode": "full_research_loop",
                "purpose": {"id": "algorithm_validation"},
                "experimentMethod": "model_training_inference",
                "researchQuestion": "Does the bounded candidate improve macro F1?",
                "objective": "Improve macro F1 without regressing latency.",
                "constraints": ["same dataset", "same baseline"],
                "methodConfig": {"model": "candidate-v4", "seeds": [17], "budget": {"epochs": 4}},
                "metricContract": {"primaryMetric": "macro_f1"},
                "decisionContract": {
                    "successCriteria": ["macro_f1 improves"],
                    "failureCriteria": ["macro_f1 regresses"],
                    "inconclusiveCriteria": ["confidence interval overlaps"],
                },
                "artifactContract": {"requiredArtifacts": ["result.json"]},
                "reproducibilityContract": {"seedPolicy": "fixed"},
                "iterationContract": {"allowedVariableChanges": ["methodConfig.budget.epochs"]},
                "status": "result_review",
            },
            "contractValidation": {"valid": True, "missingFields": []},
            "readiness": {"readyForPlanReview": True},
            "updatedAt": "2026-07-19T00:00:00+08:00",
        }
    ]
    plan_store["activePlanId"] = "plan-v4"
    team_workflow_orchestration_service._write_json(
        team_workflow_orchestration_service._experiment_plan_store_path(team["teamId"]),
        plan_store,
    )
    created = research_loop_service.create_research_loop(
        team["teamId"],
        {
            "templateId": "environment_probe",
            "researchQuestion": "Should the validated design be repaired and repeated?",
            "planId": "plan-v4",
        },
    )
    loop_id = created["loop"]["loopId"]
    for evidence_type in ("environment_spec", "smoke_log"):
        research_loop_service.record_research_loop_evidence(
            team["teamId"],
            loop_id,
            {"evidenceType": evidence_type, "status": "passed", "summary": f"{evidence_type} ready"},
        )

    decided = research_loop_service.record_research_loop_decision(
        team["teamId"],
        loop_id,
        {
            "decision": "repair_and_repeat",
            "rationale": "Increase only the frozen epoch budget and repeat.",
            "nextActions": ["change methodConfig.budget.epochs only"],
            "createNextDesignDraft": True,
            "idempotencyKey": "reuse-latest-iteration-draft",
        },
    )
    draft = decided["nextDesignDraft"]

    assert draft["status"] == "created"
    assert draft["plan"]["experimentContract"]["revision"] == 5
    assert draft["plan"]["experimentContract"]["supersedesPlanId"] == "plan-v4"
    assert draft["plan"]["designGate"]["status"] == "draft"
    assert draft["plan"]["designGate"]["sourceProposalId"] == decided["iterationProposal"]["proposalId"]
    assert draft["plan"]["designGate"]["sourceIdempotencyKey"] == "reuse-latest-iteration-draft"
    assert decided["iterationProposal"]["nextDesignPlanId"] == draft["plan"]["planId"]
    projected = team_workflow_orchestration_service.get_experiment_planning_status(team["teamId"])
    assert projected["lifecycleProjection"]["stage2"]["status"] == "draft"
    assert projected["lifecycleProjection"]["stage2"]["activeDesignPlanId"] == draft["plan"]["planId"]
    assert projected["lifecycleProjection"]["stage2"]["readyForExecution"] is False

    repeated = research_loop_service.record_research_loop_decision(
        team["teamId"],
        loop_id,
        {
            "decision": "repair_and_repeat",
            "rationale": "Increase only the frozen epoch budget and repeat.",
            "nextActions": ["change methodConfig.budget.epochs only"],
            "createNextDesignDraft": True,
            "idempotencyKey": "reuse-latest-iteration-draft",
        },
    )
    plans = team_workflow_orchestration_service.get_experiment_planning_status(team["teamId"])["plans"]

    assert repeated["nextDesignDraft"]["plan"]["planId"] == draft["plan"]["planId"]
    assert len([plan for plan in plans if plan.get("designGate", {}).get("sourceLoopId") == loop_id]) == 1


def test_legacy_iteration_proposal_can_materialize_one_gated_design_draft(tmp_path, monkeypatch):
    team = _team(tmp_path, monkeypatch)
    stage = team_workflow_orchestration_service.start_research_stage_round(
        team["teamId"],
        {"stageType": "experiment", "topic": "legacy iteration handoff"},
    )
    plan_store = team_workflow_orchestration_service._load_experiment_plan_store(team["teamId"])
    plan_store["plans"] = [
        {
            "planId": "plan-v4",
            "stageRoundId": stage["stageRound"]["stageRoundId"],
            "title": "validated design v4",
            "status": "ingested",
            "hypothesisCandidateIds": [],
            "experimentPlan": {
                "dataset": "dataset-v1",
                "metric": "macro_f1",
                "baseline": "baseline-v1",
                "smokePlan": "paired smoke",
            },
            "experimentContract": {
                "schemaVersion": 2,
                "revision": 4,
                "researchProfileId": "generic-research",
                "researchMode": "full_research_loop",
                "purpose": {"id": "algorithm_validation"},
                "experimentMethod": "model_training_inference",
                "researchQuestion": "Does the bounded candidate generalize?",
                "objective": "Validate external generalization.",
                "constraints": ["same baseline"],
                "methodConfig": {"model": "candidate-v4", "seeds": [17]},
                "metricContract": {"primaryMetric": "macro_f1"},
                "decisionContract": {
                    "successCriteria": ["macro_f1 improves"],
                    "failureCriteria": ["macro_f1 regresses"],
                    "inconclusiveCriteria": ["confidence interval overlaps"],
                },
                "artifactContract": {"requiredArtifacts": ["result.json"]},
                "reproducibilityContract": {"seedPolicy": "fixed"},
                "iterationContract": {"allowedVariableChanges": ["dataset"]},
                "status": "result_review",
            },
            "contractValidation": {"valid": True, "missingFields": []},
            "readiness": {"readyForPlanReview": True},
            "updatedAt": "2026-07-19T00:00:00+08:00",
        }
    ]
    plan_store["activePlanId"] = "plan-v4"
    team_workflow_orchestration_service._write_json(
        team_workflow_orchestration_service._experiment_plan_store_path(team["teamId"]),
        plan_store,
    )
    created = research_loop_service.create_research_loop(
        team["teamId"],
        {
            "templateId": "environment_probe",
            "researchQuestion": "Should revision4 advance to a dataset benchmark?",
            "planId": "plan-v4",
        },
    )
    loop_id = created["loop"]["loopId"]
    for evidence_type in ("environment_spec", "smoke_log"):
        research_loop_service.record_research_loop_evidence(
            team["teamId"],
            loop_id,
            {"evidenceType": evidence_type, "status": "passed", "summary": f"{evidence_type} ready"},
        )
    decided = research_loop_service.record_research_loop_decision(
        team["teamId"],
        loop_id,
        {
            "decision": "promote_to_iteration",
            "rationale": "Advance the validated candidate to a dataset benchmark.",
            "nextTemplateId": "dataset_benchmark",
            "nextActions": ["freeze the benchmark dataset and protocol"],
            "createNextDesignDraft": False,
        },
    )
    proposal_id = decided["iterationProposal"]["proposalId"]
    newer_loop = research_loop_service.create_research_loop(
        team["teamId"],
        {
            "templateId": "dataset_benchmark",
            "researchQuestion": "Can the accepted result be prepared for writeup?",
            "planId": "plan-v4",
        },
    )["loop"]
    pending_before = research_loop_service.get_research_loop_status(team["teamId"])["pendingDesignProposals"]

    materialized = research_loop_service.materialize_research_loop_iteration_design(
        team["teamId"],
        loop_id,
        proposal_id,
        {"createdByAgent": "Research Coordination Agent"},
    )
    repeated = research_loop_service.materialize_research_loop_iteration_design(
        team["teamId"],
        loop_id,
        proposal_id,
        {"createdByAgent": "Research Coordination Agent"},
    )

    assert materialized["nextDesignDraft"]["status"] == "created"
    assert repeated["nextDesignDraft"]["status"] == "reused"
    assert repeated["nextDesignDraft"]["plan"]["planId"] == materialized["nextDesignDraft"]["plan"]["planId"]
    assert materialized["iterationProposal"]["nextDesignPlanId"] == materialized["nextDesignDraft"]["plan"]["planId"]
    assert materialized["iterationProposal"]["nextDesignGateStatus"] == "draft"
    assert materialized["decision"]["nextDesignPlanId"] == materialized["nextDesignDraft"]["plan"]["planId"]
    assert materialized["nextDesignDraft"]["plan"]["designGate"]["status"] == "draft"
    assert materialized["nextDesignDraft"]["plan"]["status"] == "draft"
    assert (
        materialized["nextDesignDraft"]["plan"]["experimentContract"]["iterationContract"]["nextTemplateId"]
        == "dataset_benchmark"
    )
    assert materialized["status"]["activeLoopId"] == newer_loop["loopId"]
    assert materialized["status"]["activeLoop"]["loopId"] == newer_loop["loopId"]
    assert len(pending_before) == 1
    assert pending_before[0]["proposalId"] == proposal_id
    assert pending_before[0]["loopId"] == loop_id
    assert pending_before[0]["loopTitle"] == created["loop"]["title"]
    assert pending_before[0]["sourcePlanId"] == "plan-v4"
    assert not pending_before[0].get("nextDesignPlanId")
    assert materialized["status"]["pendingDesignProposals"] == []
    plans = team_workflow_orchestration_service.get_experiment_planning_status(team["teamId"])["plans"]
    assert len([plan for plan in plans if plan.get("designGate", {}).get("sourceProposalId") == proposal_id]) == 1


def test_research_loop_status_persists_to_team_workspace(tmp_path, monkeypatch):
    team = _team(tmp_path, monkeypatch)
    created = research_loop_service.create_research_loop(
        team["teamId"],
        {
            "templateId": "environment_probe",
            "researchQuestion": "Can the benchmark environment be prepared?",
        },
    )

    status = research_loop_service.get_research_loop_status(team["teamId"])

    assert status["activeLoopId"] == created["loop"]["loopId"]
    assert status["summary"]["totalLoopCount"] == 1
    assert status["storagePath"].endswith(f"workspace/teams/{team['teamId']}/research_loops/index.json")
    assert status["nextActions"][0]["action"] == "record_evidence"


def test_research_loop_automatically_carries_stage3_memory_context(tmp_path, monkeypatch):
    team = _team(tmp_path, monkeypatch)
    coordinator = next(
        (
            str(member.get("agentId") or "")
            for member in team.get("members") or []
            if str(member.get("role") or "") == "research_coordination"
        ),
        "",
    )
    workflow_root = research_loop_service._team_workspace_root(team["teamId"])
    research_loop_service._write_json(
        workflow_root / "experiment_plans" / "index.json",
        {
            "storeKind": "challenge_cup_experiment_plan_store",
            "activePlanId": "plan-best",
            "plans": [
                {
                    "planId": "plan-negative",
                    "title": "failed ablation",
                    "status": "smoke_failed",
                    "hypothesisCandidateIds": ["candidate-negative"],
                    "experimentContract": {
                        "schemaVersion": 2,
                        "revision": 5,
                        "methodConfig": {"candidateLossMaskMode": "shifted"},
                        "constraints": ["same seed", "only mask alignment changes"],
                        "decisionContract": {"failureCriteria": ["masked gain gate failed"]},
                    },
                    "activeSmokeResultId": "smoke-negative",
                    "activeSmokeResult": {"smokeResultId": "smoke-negative", "status": "failed"},
                },
                {
                    "planId": "plan-best",
                    "title": "validated candidate",
                    "status": "ingested",
                    "hypothesisCandidateIds": ["candidate-best"],
                    "experimentContract": {
                        "schemaVersion": 2,
                        "revision": 4,
                        "methodConfig": {"candidateMaskedLossWeight": 0.875},
                    },
                    "activeFullRunResultId": "full-best",
                    "activeFullRunResult": {"fullRunResultId": "full-best", "status": "passed"},
                    "knowledgeIngestion": {
                        "status": "ingested",
                        "result": {"knowledgeItemId": "kitem-best"},
                    },
                },
            ],
        },
    )
    monkeypatch.setattr(
        research_loop_service.team_knowledge_service,
        "search_knowledge_items",
        lambda **_: {
            "results": [
                {
                    "knowledgeItemId": "kitem-best",
                    "title": "Validated bounded result",
                    "summary": "Use as the frozen current best.",
                    "sourceArtifactIds": ["artifact-best"],
                    "centralSourceIds": ["source-best"],
                }
            ]
        },
    )

    created = research_loop_service.create_research_loop(
        team["teamId"],
        {
            "templateId": "dataset_benchmark",
            "researchQuestion": "Does the validated candidate generalize to the full dataset?",
            "planId": "plan-best",
            "candidateIds": ["candidate-best"],
            "createdByAgent": coordinator,
        },
    )
    context = created["loop"]["memoryContext"]

    assert context["stageType"] == "experiment_execution_iteration"
    assert context["currentBest"]["planId"] == "plan-best"
    assert context["priorSuccessfulRuns"][0]["resultId"] == "full-best"
    assert context["negativeExperiments"][0]["planId"] == "plan-negative"
    assert context["forbiddenDuplicateExperiments"][0]["candidateIds"] == ["candidate-negative"]
    assert created["loop"]["inputs"]["memoryContextId"] == context["contextId"]
