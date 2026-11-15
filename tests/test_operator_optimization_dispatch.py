import json
import os
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

pytest_plugins = ("tests.test_operator_optimization_budget",)

from core.research.operator_optimization.cuda_worker import CudaMeasurementIdentity, CudaTrialRequest
from core.research.operator_optimization.measurement import OperatorMeasurement, MeasurementProtocolRef
from core.research.operator_optimization.contracts import BaselineVersion
from core.research.workflow.contracts._canonical import sha256_hex
from core.web.services.team_workflow.operator_optimization import dispatch, executor
from core.web.services.team_workflow.operator_optimization.store import (
    CampaignConflict,
    read_campaign,
)


def failed_measurement(request):
    identity = CudaMeasurementIdentity.from_request(request, "Fixture")
    return OperatorMeasurement(**identity.model_dump(), status="failed",
        failureReason="fixture compiler failure", gpuSeconds=3)


@pytest.fixture(autouse=True)
def isolated_device_lease(tmp_path, monkeypatch):
    monkeypatch.setattr(executor.tempfile, "gettempdir", lambda: str(tmp_path))


@pytest.fixture
def trial(activity, monkeypatch):
    request = CudaTrialRequest(protocol={"protocolId": "p1", "split": "tuning", "cases": [
        {"caseId": "c1", "rows": 2, "columns": 32, "dtype": "float32", "seed": 1}]},
        baseline={"implementation": "torch_softmax"}, parent={"implementation": "torch_softmax"},
        candidate={"implementation": "torch_softmax"}, campaign_id=activity[2], run_id="run1",
        measurement_id="trial1", expected_environment_hash="a" * 64, max_seconds=40)
    calls = []
    def execute(req, **kwargs):
        with kwargs["start_fence"]():
            calls.append(req)
        return failed_measurement(req)
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


@pytest.mark.skipif(os.name != "nt", reason="Windows MAX_PATH regression")
def test_trial_intent_supports_deep_windows_project_path(activity, trial, tmp_path, monkeypatch):
    root = tmp_path / ("project-" + "a" * 70) / ("workspace-" + "b" * 70)
    monkeypatch.setattr(dispatch, "campaign_root", lambda *_: root)
    request, calls = trial
    first = dispatch.dispatch_trial(*activity[:2], request, device_name="Fixture")
    assert dispatch.dispatch_trial(*activity[:2], request, device_name="Fixture") == first
    assert len(calls) == 1
    assert read_campaign(*activity).gpuReservations[0].measurementRef == first


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
    def crash_after_launch(*args, **kwargs):
        with kwargs["start_fence"]():
            pass
        raise RuntimeError("crash")

    monkeypatch.setattr(dispatch, "execute_cuda_trial", crash_after_launch)
    with pytest.raises(RuntimeError, match="crash"):
        dispatch.dispatch_trial(*activity[:2], request, device_name="Fixture")
    monkeypatch.setattr(dispatch, "execute_cuda_trial", lambda *a, **k: pytest.fail("must not spawn"))
    with pytest.raises(CampaignConflict, match="reconcile"):
        dispatch.dispatch_trial(*activity[:2], request, device_name="Fixture")
    with pytest.raises(CampaignConflict, match="no verifiable terminal receipt"):
        dispatch.reconcile_run_gpu_receipts(*activity, request.run_id)
    assert read_campaign(*activity).gpuReservations[0].consumedSeconds is None


def test_busy_device_releases_admission_and_allows_retry(activity, trial, monkeypatch):
    request, _ = trial
    calls = []

    def execute(req, **kwargs):
        calls.append(req)
        if len(calls) <= 2:
            raise BlockingIOError("device busy")
        with kwargs["start_fence"]():
            pass
        return failed_measurement(req)

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


@pytest.mark.parametrize("receipt_only", [False, True])
def test_receipt_survives_interruption_before_publication(activity, trial, monkeypatch, receipt_only):
    request, calls = trial
    with monkeypatch.context() as patch:
        def crash(*args, **kwargs):
            raise RuntimeError("interrupted before canonical publication")

        patch.setattr(dispatch.artifacts, "put_workflow_artifact", crash)
        with pytest.raises(RuntimeError, match="interrupted before canonical publication"):
            dispatch.dispatch_trial(*activity[:2], request, device_name="Fixture")
    before = read_campaign(*activity)
    assert len(calls) == 1
    assert before.gpuReservations[0].consumedSeconds is None

    @contextmanager
    def no_start_fence():
        pytest.fail("receipt recovery must bypass the start fence")
        yield

    monkeypatch.setattr(dispatch, "execute_cuda_trial", lambda *a, **k: pytest.fail("must not spawn"))
    if receipt_only:
        assert dispatch.reconcile_run_gpu_receipts(*activity, request.run_id)
    ref = dispatch.dispatch_trial(*activity[:2], request, device_name="Fixture", start_fence=no_start_fence)
    after = read_campaign(*activity)
    assert after.gpuReservations[0].measurementRef == ref
    assert after.gpuReservations[0].consumedSeconds == 3
    assert after.revision == before.revision + 1


@pytest.mark.parametrize("tamper_key", ["launchId", "candidateSourceHash"])
def test_recovery_rejects_receipt_from_different_launch_or_frozen_inputs(activity, trial, monkeypatch, tamper_key):
    request, _ = trial
    identity = "operator-trial:" + request.measurement_id
    intent_path = dispatch._intent_path(*activity[:2], identity)
    with monkeypatch.context() as patch:
        patch.setattr(dispatch.artifacts, "put_workflow_artifact",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("interrupted")))
        with pytest.raises(RuntimeError, match="interrupted"):
            dispatch.dispatch_trial(*activity[:2], request, device_name="Fixture")
    path = dispatch._receipt_path(intent_path)
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if tamper_key == "launchId":
        receipt[tamper_key] = "different-launch"
    else:
        receipt["measurement"][tamper_key] = "d" * 64
    path.write_text(json.dumps(receipt), encoding="utf-8")
    monkeypatch.setattr(dispatch, "execute_cuda_trial", lambda *a, **k: pytest.fail("must not spawn"))
    with pytest.raises(CampaignConflict, match="receipt cannot be verified"):
        dispatch.dispatch_trial(*activity[:2], request, device_name="Fixture")
    assert read_campaign(*activity).gpuReservations[0].consumedSeconds is None


@pytest.mark.parametrize("legacy", [False, True])
def test_interruption_after_reserve_has_only_new_intent_no_start_proof(activity, trial, monkeypatch, legacy):
    request, _ = trial
    with monkeypatch.context() as patch:
        reserve = dispatch.reserve_gpu_time
        def interrupt(*args, **kwargs):
            reserve(*args, **kwargs)
            raise RuntimeError("interrupted before spawn")

        patch.setattr(dispatch, "reserve_gpu_time", interrupt)
        with pytest.raises(RuntimeError, match="interrupted before spawn"):
            dispatch.dispatch_trial(*activity[:2], request, device_name="Fixture")
    if legacy:
        path = dispatch._intent_path(*activity[:2], "operator-trial:" + request.measurement_id)
        path.write_text(dispatch._read_intent(path).fingerprint, encoding="utf-8")
        with pytest.raises(CampaignConflict, match="no verifiable terminal receipt"):
            dispatch.reconcile_run_gpu_receipts(*activity, request.run_id)
        assert read_campaign(*activity).gpuReservations[0].consumedSeconds is None
    else:
        assert dispatch.reconcile_run_gpu_receipts(*activity, request.run_id)
        assert read_campaign(*activity).gpuReservations == ()
        dispatch.dispatch_trial(*activity[:2], request, device_name="Fixture")
        assert read_campaign(*activity).gpuReservations[0].consumedSeconds == 3


def test_start_fence_rejection_after_reserve_releases_without_spawn(activity, trial, monkeypatch):
    request, _ = trial
    gated = []

    @contextmanager
    def reject_launch():
        gated.append(True)
        if len(gated) == 2:
            raise CampaignConflict("run cancelled")
        yield

    monkeypatch.setattr(dispatch, "execute_cuda_trial", executor.execute_cuda_trial)
    monkeypatch.setattr(executor.subprocess, "Popen", lambda *a, **k: pytest.fail("must not spawn"))
    with pytest.raises(CampaignConflict, match="run cancelled"):
        dispatch.dispatch_trial(*activity[:2], request, device_name="Fixture", start_fence=reject_launch)
    assert read_campaign(*activity).gpuReservations == ()


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


def test_real_device_lock_contention_releases_unstarted_reservation(activity, trial, tmp_path, monkeypatch):
    request, _ = trial
    monkeypatch.setattr(dispatch, "execute_cuda_trial", executor.execute_cuda_trial)
    monkeypatch.setattr(executor.subprocess, "Popen", lambda *a, **k: pytest.fail("must not spawn"))
    lease = tmp_path / "vibelution-operator-cuda" / "device-0"
    with executor.inter_process_lock(lease):
        with pytest.raises(BlockingIOError, match="worker was not started"):
            dispatch.dispatch_trial(*activity[:2], request, device_name="Fixture")
    assert read_campaign(*activity).gpuReservations == ()


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
    def baseline(action, snapshot, *, start_fence):
        assert callable(start_fence)
        calls.append(action.run_id)

    monkeypatch.setattr(dispatch, "dispatch_baseline", baseline)
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


@pytest.mark.parametrize("outcome", ["failed", "succeeded", "cancel_before_activation"])
def test_baseline_bridge_verifies_frozen_inputs_and_preserves_receipt(activity, trial, monkeypatch, outcome):
    from core.web.services.team_workflow.operator_optimization.store import (
        update_campaign,
    )
    request, calls = trial
    if outcome != "failed":
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
    protocol_artifact_hash = put("operator_measurement_protocol", protocol)
    environment_ref = put("operator_environment", {"deviceName": "Fixture"})
    version_id = "baseline-version-fixture"
    current = read_campaign(*activity)
    update_campaign(*activity, expected_version=current.revision, command_key="baseline-version-fixture",
        command={"fixture": True}, transform=lambda c: c.model_copy(update={"baselineVersions": (
            BaselineVersion(baselineVersionId=version_id, ordinal=1, setupId=c.baselineSetupId,
                runId="run1", environmentRef=environment_ref,
                protocolRef=MeasurementProtocolRef(artifactId="protocol-fixture", runId="run1",
                    sha256=protocol_artifact_hash), baselineCandidateRef=candidate_ref),)}))
    snapshot = {"teamId": activity[0], "projectId": activity[1],
        "researchObjectiveContract": {"optimizationCampaignId": activity[2], "baselineVersionId": version_id,
            "baselineCandidateRef": candidate_ref.model_dump(mode="json")},
        "evaluationContract": {"protocolArtifactHash": protocol_artifact_hash, "protocolHash": sha256_hex(protocol)},
        "environmentSnapshotRef": environment_ref}
    if outcome == "cancel_before_activation":
        fences = []

        @contextmanager
        def cancel_before_activation():
            fences.append(True)
            if len(fences) == 3:
                raise CampaignConflict("run cancelled before baseline activation")
            yield

        with pytest.raises(CampaignConflict, match="before baseline activation"):
            dispatch.dispatch_baseline(
                SimpleNamespace(run_id="run1"), snapshot, start_fence=cancel_before_activation
            )
        cancelled = read_campaign(*activity)
        assert cancelled.baselineRef is None
        assert cancelled.baselineVersions[0].status == "prepared"
        assert cancelled.gpuReservations[0].measurementRef.kind == "operator_baseline"
    for _ in range(2 if outcome != "cancel_before_activation" else 0):
        if outcome == "succeeded":
            ref = dispatch.dispatch_baseline(SimpleNamespace(run_id="run1"), snapshot)
            activated = read_campaign(*activity)
            assert activated.baselineRef == ref
            assert activated.activeBaselineVersionId == version_id
            assert activated.baselineVersions[0].status == "active"
            assert activated.baselineVersions[0].baselineRef == ref
            assert activated.bestCandidateRef == candidate_ref
        else:
            with pytest.raises(RuntimeError, match="Baseline measurement did not succeed"):
                dispatch.dispatch_baseline(SimpleNamespace(run_id="run1"), snapshot)
            unchanged = read_campaign(*activity)
            assert unchanged.activeBaselineVersionId == ""
            assert unchanged.baselineVersions[0].status == "failed"
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
