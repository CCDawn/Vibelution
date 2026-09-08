import pytest

from core.research.operator_optimization.contracts import ArtifactRef
from core.research.workflow.contracts._canonical import sha256_hex
from core.web.services import team_service
from core.web.services import team_workflow_orchestration_service as service
from core.web.services.team_workflow.operator_optimization.budget import (
    budget_summary,
    release_gpu_reservation,
    reserve_gpu_time,
    settle_gpu_usage,
)
from core.web.services.team_workflow.operator_optimization.store import (
    CampaignConflict,
    create_campaign,
    read_campaign,
    update_campaign,
)
from core.web.services.team_workflow.research_runtime import (
    workflow_artifact_store as artifacts,
)
from core.web.services.team_workflow.research_runtime.artifact_readback_registry import (
    load_scoped_artifact_payload,
)
from tests._support.team_workflow.cases_experiment import _use_tmp_project_root


@pytest.fixture
def activity(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(artifacts, "_path", lambda team, kind: tmp_path / "artifacts" / team / f"{kind}.jsonl")
    team = team_service.create_team(name="Budget test")["teamId"]
    project = service.get_active_research_project(team)["projectId"]
    c = create_campaign(team, project, {"title": "Softmax", "idempotencyKey": "one",
        "budget": {"gpuSecondsLimit": 100, "trialTimeoutSeconds": 60}})
    c = update_campaign(team, project, c.optimizationCampaignId, expected_version=1, command_key="fixture",
        command={"fixture": True}, transform=lambda c: c.model_copy(update={"status": "running", "activeRunId": "run1",
            "authorizedBy": "fixture", "budget": c.budget.model_copy(update={"authorized": True})}))
    return team, project, c.optimizationCampaignId


def reserve(args, key="trial1", seconds=40):
    return reserve_gpu_time(*args, run_id="run1", reservation_id=key, seconds=seconds,
        protocol_hash="a" * 64, phase="tuning")


def receipt(args, *, seconds=12, status="failed", run="run1", campaign=None):
    payload = {
        "measurementId": "trial1",
        "optimizationCampaignId": campaign or args[2],
        "runId": run,
        "protocolHash": "a" * 64,
        "workloadHash": "b" * 64,
        "environmentHash": "c" * 64,
        "baselineSourceHash": "d" * 64,
        "parentSourceHash": "e" * 64,
        "candidateSourceHash": "f" * 64,
        "runnerId": "operator_cuda_v1",
        "deviceKind": "cuda",
        "deviceName": "Fixture GPU",
        "status": status,
        "failureReason": "compiler failure" if status != "succeeded" else "",
        "gpuSeconds": seconds,
        "cases": [],
    }
    row = artifacts.put_workflow_artifact(args[0], kind="operator_measurement", workflow_run_id="run1", payload=payload)
    envelope = load_scoped_artifact_payload("operator_measurement", team_id=args[0], workflow_run_id="run1", authority_run_id="run1")
    return ArtifactRef(artifactId=row["recordId"], kind="operator_measurement", sha256=sha256_hex(envelope))


def test_reservation_replay_does_not_spend_twice_or_enter_final_reserve(activity):
    one = reserve(activity)
    assert reserve(activity) == one
    assert budget_summary(read_campaign(*activity))["gpuReservedSeconds"] == 40
    with pytest.raises(CampaignConflict):
        reserve(activity, seconds=41)
    reserve(activity, key="trial2")
    with pytest.raises(CampaignConflict, match="budget"):
        reserve(activity, key="trial3", seconds=1)


def test_released_reservation_can_be_retried_without_spending_or_sticking(activity):
    reserve(activity)
    release_gpu_reservation(*activity, reservation_id="trial1", reason="device_busy")
    totals = budget_summary(read_campaign(*activity))
    assert totals["gpuConsumedSeconds"] == 0
    assert totals["gpuReservedSeconds"] == 0

    reserve(activity)
    totals = budget_summary(read_campaign(*activity))
    assert totals["gpuConsumedSeconds"] == 0
    assert totals["gpuReservedSeconds"] == 40


def test_failure_receipt_settles_actual_time_once_even_after_pause(activity):
    reserve(activity)
    c = read_campaign(*activity)
    update_campaign(*activity, expected_version=c.revision, command_key="pause", command={"pause":True},
        transform=lambda c:c.model_copy(update={"status":"paused"}))
    ref = receipt(activity)
    settled = settle_gpu_usage(*activity, reservation_id="trial1", measurement_ref=ref)
    assert settle_gpu_usage(*activity, reservation_id="trial1", measurement_ref=ref) == settled
    totals = budget_summary(read_campaign(*activity))
    assert totals["gpuConsumedSeconds"] == 12
    assert totals["gpuReservedSeconds"] == 0
    assert settled.status == "paused"
    assert settled.gpuReservations[0].outcome == "failed"


def test_overrun_is_recorded_and_blocks_further_work(activity):
    reserve(activity)
    settled = settle_gpu_usage(*activity, reservation_id="trial1", measurement_ref=receipt(activity, seconds=45))
    assert settled.status == "blocked"
    assert budget_summary(settled)["gpuConsumedSeconds"] == 45


def test_other_campaign_receipt_cannot_settle_usage(activity):
    reserve(activity)
    with pytest.raises(CampaignConflict, match="scope"):
        settle_gpu_usage(*activity, reservation_id="trial1", measurement_ref=receipt(activity,campaign="other"))
    assert budget_summary(read_campaign(*activity))["gpuReservedSeconds"] == 40


def test_concurrent_reservations_cannot_oversubscribe(activity):
    from concurrent.futures import ThreadPoolExecutor

    def attempt(index):
        try:
            reserve(activity, key=f"parallel{index}")
            return True
        except CampaignConflict:
            return False

    with ThreadPoolExecutor(max_workers=3) as pool:
        assert sum(pool.map(attempt, range(3))) == 2
    assert budget_summary(read_campaign(*activity))["gpuReservedSeconds"] == 80


def test_final_validation_can_use_its_reserve_without_exceeding_total(activity):
    reserve(activity)
    reserve(activity, key="trial2")
    reserve_gpu_time(*activity, run_id="run1", reservation_id="final", seconds=20,
        protocol_hash="a" * 64, phase="holdout")
    assert budget_summary(read_campaign(*activity))["gpuAvailableSeconds"] == 0
    with pytest.raises(CampaignConflict, match="budget"):
        reserve_gpu_time(*activity, run_id="run1", reservation_id="final2", seconds=1,
            protocol_hash="a" * 64, phase="holdout")


def test_tampered_hash_cannot_release_reserved_time(activity):
    reserve(activity)
    ref = receipt(activity).model_copy(update={"sha256":"0" * 64})
    with pytest.raises(CampaignConflict):
        settle_gpu_usage(*activity, reservation_id="trial1", measurement_ref=ref)
    assert budget_summary(read_campaign(*activity))["gpuReservedSeconds"] == 40


def test_one_measurement_cannot_settle_two_trials(activity):
    reserve(activity)
    reserve(activity, key="trial2")
    ref = receipt(activity)
    settle_gpu_usage(*activity, reservation_id="trial1", measurement_ref=ref)
    with pytest.raises(CampaignConflict, match="scope"):
        settle_gpu_usage(*activity, reservation_id="trial2", measurement_ref=ref)
    totals = budget_summary(read_campaign(*activity))
    assert totals["gpuConsumedSeconds"] == 12 and totals["gpuReservedSeconds"] == 40
