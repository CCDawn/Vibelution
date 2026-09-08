import json

from core.research.operator_optimization.measurement import MeasurementProtocol
from core.web.services import team_service, team_workflow_orchestration_service as service
from core.web.services.team_workflow.operator_optimization import baseline
from core.web.services.team_workflow.operator_optimization.commands import authorize_campaign
from core.web.services.team_workflow.operator_optimization.store import create_campaign
from core.web.services.team_workflow.research_runtime import run_creation
from core.web.services.team_workflow.research_runtime.real_readiness_context import RealDomainReadinessContext
from core.web.services.team_workflow.research_runtime.operator_authorization import server_operator_scope
from core.web.services.team_workflow.research_runtime import workflow_artifact_store as artifacts
from tests._support.team_workflow.cases_experiment import _use_tmp_project_root
from tests._support.workflow_ledger_helpers import open_ledger_store


def test_baseline_setup_creates_scoped_ledger_with_verified_artifacts_once(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    team = team_service.create_team(name="Operator baseline")["teamId"]
    project = service.get_active_research_project(team)["projectId"]
    monkeypatch.setattr(artifacts, "_path", lambda team, kind: tmp_path / "artifacts" / team / f"{kind}.jsonl")
    monkeypatch.setattr(baseline, "inspect_cuda_environment", lambda: {"deviceKind": "cuda", "deviceName": "fixture"})
    ledger = open_ledger_store(tmp_path / "ledger.sqlite")
    monkeypatch.setattr(run_creation, "get_write_store", lambda: ledger)
    monkeypatch.setattr(run_creation, "research_workflow_data_root", lambda: tmp_path)
    monkeypatch.setattr(run_creation, "effective_binding_layers", lambda team, layers: layers)
    campaign = create_campaign(team, project, {"title": "Softmax", "idempotencyKey": "one", "budget": {"gpuSecondsLimit": 60}})
    cid = campaign.optimizationCampaignId
    protocol = MeasurementProtocol(protocolId="p1", split="tuning",
        cases=[dict(caseId="s1", rows=128, columns=512, dtype="float32", seed=1)])
    try:
        with server_operator_scope("owner", roles=("operator",)):
            authorized = authorize_campaign(team, project, cid, expected_version=1, command_key="approve")
            prepared = baseline.prepare_baseline(team, project, cid, protocol=protocol,
                expected_version=authorized.revision, command_key="prepare")
            assert baseline.prepare_baseline(team, project, cid, protocol=protocol,
                expected_version=authorized.revision, command_key="prepare") == prepared
        run = ledger.get_run(prepared.baselineRunId)
        assert run.status == "created"
        assert run.project_id == project
        assert prepared.baselineRef is None
        assert prepared.baselineCandidateRef is not None
        assert prepared.baselineCandidateRef.kind == "operator_candidate"
        assert prepared.baselineCandidateRef.candidate.implementation == "torch_softmax"
        assert not json.loads(run.input_snapshot_json)["catalogScope"]
        state = RealDomainReadinessContext(ledger).operator_campaign_state(team, prepared.baselineRunId)
        assert state["environmentVerified"] and state["protocolFrozen"]
        assert not RealDomainReadinessContext(ledger).operator_campaign_state("other", prepared.baselineRunId)
    finally:
        ledger.close()
