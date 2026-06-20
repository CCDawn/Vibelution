import pytest

from core.web.services import research_loop_service, team_service


def _use_tmp_project_root(tmp_path, monkeypatch):
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(research_loop_service, "PROJECT_ROOT", tmp_path)


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
