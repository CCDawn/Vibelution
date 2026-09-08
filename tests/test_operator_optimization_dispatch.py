from types import SimpleNamespace

import pytest

pytest_plugins = ("tests.test_operator_optimization_budget",)

from core.research.operator_optimization.cuda_worker import CudaTrialRequest
from core.research.operator_optimization.measurement import OperatorMeasurement
from core.research.workflow.contracts._canonical import sha256_hex
from core.web.services.team_workflow.operator_optimization import dispatch, executor
from core.web.services.team_workflow.operator_optimization.store import (
    CampaignConflict,
    read_campaign,
)


@pytest.fixture
def trial(activity, monkeypatch):
    request = CudaTrialRequest(protocol={"protocolId": "p1", "split": "tuning", "cases": [
        {"caseId": "c1", "rows": 2, "columns": 32, "dtype": "float32", "seed": 1}]},
        baseline={"implementation": "torch_softmax"}, parent={"implementation": "torch_softmax"},
        candidate={"implementation": "torch_softmax"}, campaign_id=activity[2], run_id="run1",
        measurement_id="trial1", expected_environment_hash="a" * 64, max_seconds=40)
    calls = []
    def execute(req, **kwargs):
        calls.append(req)
        return OperatorMeasurement(measurementId=req.measurement_id, optimizationCampaignId=req.campaign_id,
            runId=req.run_id, protocolHash=sha256_hex(req.protocol.model_dump(mode="json")), workloadHash="b" * 64,
            environmentHash="a" * 64, baselineSourceHash="c" * 64, parentSourceHash="c" * 64,
            candidateSourceHash="c" * 64, deviceName="Fixture", status="failed",
            failureReason="fixture compiler failure", gpuSeconds=3)
    monkeypatch.setattr(dispatch, "execute_cuda_trial", execute)
    return request, calls


def test_failed_trial_persists_settles_and_replays_without_execution(activity, trial):
    request, calls = trial
    first = dispatch.dispatch_trial(*activity[:2], request, device_name="Fixture")
    assert dispatch.dispatch_trial(*activity[:2], request, device_name="Fixture") == first
    assert len(calls) == 1
    reservation = read_campaign(*activity).gpuReservations[0]
    assert reservation.consumedSeconds == 3
    assert reservation.outcome == "failed"
    assert reservation.measurementRef == first


def test_retry_after_settlement_interruption_uses_saved_receipt(activity, trial, monkeypatch):
    request, calls = trial
    settle = dispatch.settle_gpu_usage
    monkeypatch.setattr(dispatch, "settle_gpu_usage", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("interrupted")))
    with pytest.raises(RuntimeError, match="interrupted"):
        dispatch.dispatch_trial(*activity[:2], request, device_name="Fixture")
    monkeypatch.setattr(dispatch, "settle_gpu_usage", settle)
    dispatch.dispatch_trial(*activity[:2], request, device_name="Fixture")
    assert len(calls) == 1
    assert read_campaign(*activity).gpuReservations[0].consumedSeconds == 3


def test_admitted_without_receipt_never_automatically_reexecutes(activity, trial, monkeypatch):
    request, _ = trial
    monkeypatch.setattr(dispatch, "execute_cuda_trial", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("crash")))
    with pytest.raises(RuntimeError, match="crash"):
        dispatch.dispatch_trial(*activity[:2], request, device_name="Fixture")
    with pytest.raises(CampaignConflict, match="reconcile"):
        dispatch.dispatch_trial(*activity[:2], request, device_name="Fixture")
    assert read_campaign(*activity).gpuReservations[0].consumedSeconds is None


def test_busy_device_releases_admission_and_allows_retry(activity, trial, monkeypatch):
    request, _ = trial
    calls = []

    def execute(req, **kwargs):
        calls.append(req)
        if len(calls) <= 2:
            raise BlockingIOError("device busy")
        return OperatorMeasurement(
            measurementId=req.measurement_id,
            optimizationCampaignId=req.campaign_id,
            runId=req.run_id,
            protocolHash=sha256_hex(req.protocol.model_dump(mode="json")),
            workloadHash="b" * 64,
            environmentHash="a" * 64,
            baselineSourceHash="c" * 64,
            parentSourceHash="c" * 64,
            candidateSourceHash="c" * 64,
            deviceName="Fixture",
            status="failed",
            failureReason="fixture compiler failure",
            gpuSeconds=3,
        )

    monkeypatch.setattr(dispatch, "execute_cuda_trial", execute)
    for _ in range(2):
        with pytest.raises(BlockingIOError, match="device busy"):
            dispatch.dispatch_trial(*activity[:2], request, device_name="Fixture")
        assert read_campaign(*activity).gpuReservations == ()

    dispatch.dispatch_trial(*activity[:2], request, device_name="Fixture")
    assert len(calls) == 3
    reservation = read_campaign(*activity).gpuReservations[0]
    assert reservation.consumedSeconds == 3
    assert reservation.outcome == "failed"


def test_worker_start_failure_is_recorded_and_settled_without_gpu_cost(activity, trial, monkeypatch):
    request, _ = trial

    def fail_start(*args, **kwargs):
        raise FileNotFoundError("cuda worker executable missing")

    monkeypatch.setattr(executor.subprocess, "Popen", fail_start)
    monkeypatch.setattr(dispatch, "execute_cuda_trial", executor.execute_cuda_trial)
    ref = dispatch.dispatch_trial(*activity[:2], request, device_name="Fixture")
    envelope = dispatch.load_scoped_artifact_payload(
        ref.kind,
        team_id=activity[0],
        workflow_run_id=request.run_id,
        authority_run_id=request.run_id,
        record_id=ref.artifactId,
        content_hash=ref.sha256,
    )
    assert envelope["payload"]["status"] == "failed"
    assert envelope["payload"]["gpuSeconds"] == 0
    reservation = read_campaign(*activity).gpuReservations[0]
    assert reservation.consumedSeconds == 0
    assert reservation.outcome == "failed"
    assert dispatch.dispatch_trial(*activity[:2], request, device_name="Fixture") == ref


def test_trial_identity_rejects_changed_input(activity, trial):
    request, calls = trial
    dispatch.dispatch_trial(*activity[:2], request, device_name="Fixture")
    with pytest.raises(CampaignConflict, match="different frozen"):
        dispatch.dispatch_trial(*activity[:2], request.model_copy(update={"max_seconds": 41}), device_name="Fixture")
    assert len(calls) == 1


def test_system_baseline_dispatch_uses_operator_bridge(monkeypatch):
    from core.web.services.team_workflow.research_runtime import (
        real_domain_ports as ports,
    )
    calls = []
    monkeypatch.setattr(dispatch, "dispatch_baseline", lambda action, snapshot: calls.append(action.run_id))
    monkeypatch.setattr(ports, "_collect_system_artifact_refs", lambda **kwargs: [{"kind": "operator_baseline"}])
    refs, meta = ports._execute_real_system_action(SimpleNamespace(node_id="operator_baseline", run_id="run1", action_id="a1"),
        input_snapshot={"teamId": "team1"}, required_kinds=("operator_baseline",))
    assert calls == ["run1"]
    assert refs == [{"kind": "operator_baseline"}]
    assert meta["runnerId"] == "operator_cuda_v1"


def test_concurrent_dispatch_spends_only_once(activity, trial):
    from concurrent.futures import ThreadPoolExecutor
    request, calls = trial
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: dispatch.dispatch_trial(*activity[:2], request, device_name="Fixture"), range(2)))
    assert results[0] == results[1]
    assert len(calls) == 1


@pytest.mark.parametrize("successful", [False, True])
def test_baseline_bridge_verifies_frozen_inputs_and_preserves_failed_receipt(activity, trial, monkeypatch, successful):
    from core.web.services.team_workflow.operator_optimization.store import (
        update_campaign,
    )
    request, calls = trial
    if successful:
        from core.research.operator_optimization.measurement import (
            CaseMeasurement,
            PairedTiming,
        )
        execute = dispatch.execute_cuda_trial
        def complete(req, **kwargs):
            result = execute(req, **kwargs)
            rows = tuple(CaseMeasurement(caseId=case.caseId, correctnessPassed=True, maxAbsoluteError=0,
                timings=tuple(PairedTiming(baselineMs=1, parentMs=1, candidateMs=1) for _ in range(req.protocol.pairs)))
                for case in req.protocol.cases)
            return result.model_copy(update={"status": "succeeded", "failureReason": "", "cases": rows})
        monkeypatch.setattr(dispatch, "execute_cuda_trial", complete)
    campaign = read_campaign(*activity)
    update_campaign(*activity, expected_version=campaign.revision, command_key="baseline-fixture",
        command={"fixture": True}, transform=lambda c: c.model_copy(update={"baselineRunId": "run1"}))
    def put(kind, payload):
        dispatch.artifacts.put_workflow_artifact(activity[0], kind=kind, workflow_run_id="run1", payload=payload)
        envelope = dispatch.load_scoped_artifact_payload(kind, team_id=activity[0], workflow_run_id="run1", authority_run_id="run1")
        return sha256_hex(envelope)
    protocol = request.protocol.model_dump(mode="json")
    from core.research.operator_optimization.candidate import CudaCandidateArtifact, candidate_ref_from_artifact
    candidate = CudaCandidateArtifact.default_baseline(candidate_id="baseline-candidate",
        optimization_campaign_id=activity[2], run_id="run1")
    dispatch.artifacts.put_workflow_artifact(activity[0], kind="operator_candidate", workflow_run_id="run1",
        artifact_identity=candidate.candidateId, payload=candidate.model_dump(mode="json"))
    candidate_envelope = dispatch.load_scoped_artifact_payload("operator_candidate", team_id=activity[0],
        workflow_run_id="run1", authority_run_id="run1", record_id=candidate.candidateId)
    candidate_ref = candidate_ref_from_artifact(candidate_envelope, artifact_id=candidate.candidateId, run_id="run1")
    update_campaign(*activity, expected_version=None, command_key="baseline-candidate-fixture",
        command={"fixture": True}, transform=lambda c: c.model_copy(update={"baselineCandidateRef": candidate_ref}))
    snapshot = {"teamId": activity[0], "projectId": activity[1],
        "researchObjectiveContract": {"optimizationCampaignId": activity[2], "baselineCandidateRef": candidate_ref.model_dump(mode="json")},
        "evaluationContract": {"protocolArtifactHash": put("operator_measurement_protocol", protocol), "protocolHash": sha256_hex(protocol)},
        "environmentSnapshotRef": put("operator_environment", {"deviceName": "Fixture"})}
    for _ in range(2):
        if successful:
            ref = dispatch.dispatch_baseline(SimpleNamespace(run_id="run1"), snapshot)
            assert read_campaign(*activity).baselineRef == ref
        else:
            with pytest.raises(RuntimeError, match="Baseline measurement did not succeed"):
                dispatch.dispatch_baseline(SimpleNamespace(run_id="run1"), snapshot)
    assert len(calls) == 1
    assert read_campaign(*activity).gpuReservations[0].consumedSeconds == 3
    with monkeypatch.context() as patch:
        patch.setattr(dispatch, "source_hash", lambda candidate: "e" * 64)
        with pytest.raises(CampaignConflict, match="current runner"):
            dispatch.dispatch_baseline(SimpleNamespace(run_id="run1"), snapshot)
    assert len(calls) == 1
    snapshot["environmentSnapshotRef"] = "f" * 64
    with pytest.raises(CampaignConflict, match="cannot be verified"):
        dispatch.dispatch_baseline(SimpleNamespace(run_id="run1"), snapshot)
    assert len(calls) == 1
