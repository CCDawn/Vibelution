from dataclasses import replace
import threading

import pytest

from tests.test_self_evolution_autonomous_loop_service import _build_service
from core.web.services.self_evolution_autonomous_loop_service import AutonomousLoopConflictError


def _service(tmp_path):
    service, calls = _build_service(tmp_path)
    service._hooks = replace(service._hooks, authorize=lambda context: {
        "runId": context["runId"], "operatorId": "operator", "authorizationId": "grant",
        "allowedFiles": context["request"]["localIntegration"]["allowedFiles"],
    }, review=lambda context: {"candidate": context["candidate"], "independentReview": {
        "verdict": "passed", "candidateCommit": context["candidate"]["headCommit"],
        "sessionId": "review-session", "turnId": "review-turn", "reviewerAgentId": "reviewer",
        "evidenceRefs": ["source:core/example.py"],
    }}, check_authorization=lambda context: None)
    return service, calls


def _request():
    return {"goal": "bounded improvement", "localIntegration": {
        "acknowledge": True, "allowedFiles": ["core/example.py", "tests/test_example.py"],
        "teamId": "team-1", "validForSeconds": 300,
    }}


def test_campaign_child_exact_admission_is_idempotent_and_keeps_private_source(tmp_path):
    service, _ = _service(tmp_path)
    source = {"campaignId": "campaign-1", "round": 1, "childRunId": "campaign-1-round-1"}
    first = service.queue_campaign(_request(), source=source, run_id=source["childRunId"])
    assert first["_campaignSource"] == source
    assert first["_campaignExecutionSettled"] is True
    assert service.queue_campaign(_request(), source=source, run_id=source["childRunId"]) == first
    with pytest.raises(AutonomousLoopConflictError):
        service.get_campaign(source["childRunId"], source={**source, "round": 2})


def test_campaign_cancellation_is_exact_and_does_not_retire_shared_service(tmp_path):
    service, _ = _service(tmp_path)
    source = {"campaignId": "campaign-1", "round": 1, "childRunId": "campaign-1-round-1"}
    service.queue_campaign(_request(), source=source, run_id=source["childRunId"])
    assert service.cancel_campaign(source["childRunId"], source=source)["status"] == "stopped"
    assert service.run_until_review(source["childRunId"])["_campaignExecutionSettled"] is True
    assert service.queue({"goal": "separate operator task"})["status"] == "queued"


def test_public_queue_cannot_install_campaign_source(tmp_path):
    service, _ = _service(tmp_path)
    run = service.queue({"goal": "operator task", "_campaignSource": {"campaignId": "forged"}})
    assert "_campaignSource" not in run


def test_stopped_but_unsettled_child_blocks_another_candidate(tmp_path):
    service, _ = _service(tmp_path)
    source = {"campaignId": "campaign-1", "round": 1, "childRunId": "campaign-1-round-1"}
    queued = service.queue_campaign(_request(), source=source, run_id=source["childRunId"])
    queued.update(status="stopped", _campaignExecutionSettled=False)
    service._store.persist_snapshot(queued["runKind"], queued, active_run_id="")
    with pytest.raises(AutonomousLoopConflictError, match="not settled"):
        service.queue({"goal": "another candidate"})


@pytest.mark.parametrize("atomic_phase", ["integrating", "cleanup_pending"])
def test_other_service_cancel_during_atomic_phase_preserves_receipt(tmp_path, atomic_phase):
    service, _ = _service(tmp_path)
    entered, release = threading.Event(), threading.Event()
    original = service._hooks
    def evolve(context):
        result = original.evolve(context)
        result["baseCommit"] = "b" * 40
        return result
    def integrate(context):
        result = original.integrate(context)
        result["commitSha"] = context["candidate"]["headCommit"]
        if atomic_phase == "integrating":
            entered.set()
            assert release.wait(3)
        return result
    def cleanup(context):
        entered.set()
        assert release.wait(3)
        return original.cleanup(context)
    service._hooks = replace(original, evolve=evolve, integrate=integrate,
                             cleanup=cleanup if atomic_phase == "cleanup_pending" else original.cleanup)
    other, _ = _service(tmp_path)
    source = {"campaignId": "campaign-1", "round": 1, "childRunId": "campaign-1-round-1"}
    service.queue_campaign(_request(), source=source, run_id=source["childRunId"])
    worker = threading.Thread(target=service.run_until_review, args=(source["childRunId"],))
    worker.start()
    try:
        assert entered.wait(3)
        stopping = other.cancel_campaign(source["childRunId"], source=source)
        assert stopping["status"] == "running"
        assert stopping["stopRequested"] is True
        assert stopping["_campaignExecutionSettled"] is False
    finally:
        release.set()
        worker.join(4)
    assert not worker.is_alive()
    result = service.get_campaign(source["childRunId"], source=source)
    assert result["status"] == "stopped"
    assert result["integration"]["status"] == "committed"
    assert result["integration"]["commitSha"] == "a" * 40
    assert result["_campaignExecutionSettled"] is True
    if atomic_phase == "cleanup_pending":
        assert result["cleanup"]["status"] == "cleaned"


@pytest.mark.parametrize("owner_alive", [False, True])
def test_startup_proven_merge_cleanup_settles_dead_owner_only(tmp_path, owner_alive):
    service, _ = _service(tmp_path)
    source = {"campaignId": "campaign-1", "round": 1, "childRunId": "campaign-1-round-1"}
    snapshot = service.queue_campaign(_request(), source=source, run_id=source["childRunId"])
    candidate = service._hooks.evolve(snapshot)
    candidate["baseCommit"] = "b" * 40
    snapshot.update(status="running", phase="integrating", candidate=candidate,
                    _campaignExecutionSettled=False)
    service._store.persist_snapshot(snapshot["runKind"], snapshot, active_run_id=snapshot["runId"])
    recovered = service._hooks.integrate(snapshot)
    recovered["commitSha"] = candidate["headCommit"]
    service._hooks = replace(service._hooks, recover_integration=lambda context: recovered)
    service._process_alive = lambda value: owner_alive
    result = service.reconcile_interrupted_on_startup()
    if owner_alive:
        assert result["_campaignExecutionSettled"] is False
        assert result["phase"] == "integrating"
    else:
        assert result["integration"]["commitSha"] == candidate["headCommit"]
        assert result["cleanup"]["status"] == "cleaned"
        assert result["_campaignExecutionSettled"] is True
        assert service.queue({"goal": "another candidate"})["status"] == "queued"
