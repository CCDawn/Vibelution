import json
from types import SimpleNamespace

import pytest

from tests.test_operator_optimization_budget import activity
from core.research.operator_optimization.contracts import ArtifactRef
from core.research.operator_optimization.candidate import (
    CudaCandidate,
    CudaCandidateArtifact,
    CudaCandidateRef,
    source_hash,
)
from core.research.workflow.contracts._canonical import sha256_hex
from core.web.services.team_workflow.operator_optimization import rounds
from core.web.services.team_workflow.operator_optimization.store import read_campaign, update_campaign, CampaignConflict
from core.web.services.team_workflow.research_runtime.run_creation import create_run as actual_create_run


@pytest.fixture
def ready(activity, monkeypatch):
    team, project, cid = activity
    def put(kind, payload, *, artifact_identity=""):
        row = rounds.artifacts.put_workflow_artifact(team, kind=kind, workflow_run_id="run1",
            payload=payload, artifact_identity=artifact_identity)
        envelope = rounds.load_scoped_artifact_payload(kind, team_id=team, workflow_run_id="run1", authority_run_id="run1")
        return ArtifactRef(artifactId=row["recordId"], kind=kind, sha256=sha256_hex(envelope))
    baseline = put("operator_baseline", {"status": "succeeded", "optimizationCampaignId": cid})
    environment = put("operator_environment", {"deviceName": "fixture"})
    protocol = put("operator_measurement_protocol", {"protocolId": "p1"})
    candidate = CudaCandidate(implementation="torch_softmax")
    candidate_payload = CudaCandidateArtifact(
        candidateId="baseline-candidate",
        optimizationCampaignId=cid,
        runId="run1",
        candidate=candidate,
        sourceHash=source_hash(candidate),
    ).model_dump(mode="json")
    candidate_artifact = put("operator_candidate", candidate_payload, artifact_identity="baseline-candidate")
    candidate_ref = CudaCandidateRef(
        artifactId=candidate_artifact.artifactId,
        runId="run1",
        sha256=candidate_artifact.sha256,
        candidate=candidate,
        sourceHash=source_hash(candidate),
    )
    campaign = read_campaign(*activity)
    campaign = update_campaign(*activity, expected_version=campaign.revision, command_key="ready",
        command={"fixture": True}, transform=lambda c: c.model_copy(update={
            "baselineRef": baseline, "baselineCandidateRef": candidate_ref, "baselineRunId": "run1",
            "budget": c.budget.model_copy(update={"modelCostLimit": 10})}))
    run = SimpleNamespace(run_id="run1", team_id=team, project_id=project, status="succeeded",
        input_snapshot_json=json.dumps({"environmentSnapshotRef": environment.sha256,
            "evaluationContract": {"protocolArtifactHash": protocol.sha256,
                "protocolArtifactKind": "operator_measurement_protocol",
                "protocolHash": sha256_hex({"protocolId": "p1"})},
            "datasetRefs": ["workload-hash"]}))
    monkeypatch.setattr(rounds.run_creation, "get_write_store", lambda: SimpleNamespace(get_run=lambda _: run))
    calls = []
    monkeypatch.setattr(rounds.run_creation, "create_run", lambda *args, **kwargs: calls.append((args, kwargs)))
    return campaign, run, calls


def test_round_pins_baseline_evidence_and_replays_once(activity, ready):
    campaign, run, calls = ready
    kwargs = dict(expected_version=campaign.revision, command_key="round1")
    first = rounds.prepare_round(*activity, **kwargs)
    assert rounds.prepare_round(*activity, **kwargs) == first
    assert len(calls) == 1
    assert first.rounds[0].ordinal == 1
    assert first.rounds[0].parentCandidateRef == campaign.baselineCandidateRef
    assert first.rounds[0].baselineCandidateRef == campaign.baselineCandidateRef
    snapshot = calls[0][1]["run_input"]
    context = snapshot["researchObjectiveContract"]
    assert context["observationRefs"] == [campaign.baselineRef.model_dump(mode="json")]
    assert context["roundId"] == first.rounds[0].roundId
    assert snapshot["projectId"] == activity[1]
    assert context["baselineRef"] == campaign.baselineRef.model_dump(mode="json")
    assert context["baselineCandidateRef"] == campaign.baselineCandidateRef.model_dump(mode="json")
    assert first.rounds[0].protocolRef.kind == "operator_measurement_protocol"
    envelope = rounds.load_scoped_artifact_payload("operator_environment", team_id=activity[0],
        workflow_run_id=first.activeRunId, authority_run_id=first.activeRunId,
        content_hash=snapshot["environmentSnapshotRef"])
    assert envelope is not None


def test_unfinished_baseline_does_not_create_round(activity, ready):
    campaign, run, calls = ready
    run.status = "running"
    with pytest.raises(CampaignConflict, match="has not completed"):
        rounds.prepare_round(*activity, expected_version=campaign.revision, command_key="round1")
    assert calls == []


def test_missing_or_tampered_baseline_blocks_round(activity, ready, monkeypatch):
    campaign, run, calls = ready
    original = rounds.load_scoped_artifact_payload
    monkeypatch.setattr(rounds, "load_scoped_artifact_payload", lambda kind, **kwargs:
        None if kind == "operator_baseline" else original(kind, **kwargs))
    with pytest.raises(CampaignConflict, match="cannot be verified"):
        rounds.prepare_round(*activity, expected_version=campaign.revision, command_key="round1")
    assert calls == []


def test_second_round_requires_previous_feedback(activity, ready):
    campaign, run, calls = ready
    first = rounds.prepare_round(*activity, expected_version=campaign.revision, command_key="round1")
    run.run_id = first.activeRunId
    with pytest.raises(CampaignConflict, match="requires canonical feedback"):
        rounds.prepare_round(*activity, expected_version=first.revision, command_key="round2")
    assert len(calls) == 1


def test_changed_project_cannot_supply_previous_run(activity, ready):
    campaign, run, calls = ready
    run.project_id = "other"
    with pytest.raises(CampaignConflict, match="another project"):
        rounds.prepare_round(*activity, expected_version=campaign.revision, command_key="round1")
    assert calls == []


def test_round_creates_real_ledger_on_discussion_node(activity, ready, tmp_path, monkeypatch):
    from tests._support.workflow_ledger_helpers import open_ledger_store
    from core.research.workflow.models import AgentBindingLayers
    campaign, baseline_run, calls = ready
    ledger = open_ledger_store(tmp_path / "round-ledger.sqlite")
    class Store:
        def get_run(self, run_id):
            return baseline_run if run_id == "run1" else ledger.get_run(run_id)
        def __getattr__(self, name):
            return getattr(ledger, name)
    monkeypatch.setattr(rounds.run_creation, "get_write_store", lambda: Store())
    monkeypatch.setattr(rounds.run_creation, "create_run", actual_create_run)
    monkeypatch.setattr(rounds.run_creation, "research_workflow_data_root", lambda: tmp_path)
    monkeypatch.setattr(rounds.run_creation, "effective_binding_layers", lambda *a:
        AgentBindingLayers(workflowDefaults={"experiment_planner": "planner-fixture"}))
    try:
        created = rounds.prepare_round(*activity, expected_version=campaign.revision, command_key="round-real")
        run = ledger.get_run(created.activeRunId)
        assert run.workflow_id == "operator-optimization"
        assert run.active_node_id == "optimization_discussion"
        assert run.project_id == activity[1]
        assert run.status == "created"
    finally:
        ledger.close()
