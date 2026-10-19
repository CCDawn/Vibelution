from copy import deepcopy
from datetime import datetime, timedelta, timezone
import threading
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from core.runtime_manager.work_run_store import WorkRunStore
from core.web.services.self_evolution_local_integration import _digest
from core.web.services.self_evolution_local_integration import LocalIntegrationError
from core.web.services.self_evolution_campaign_service import (
    CampaignConflictError, CampaignValidationError, RUN_KIND,
    SelfEvolutionCampaignService, delegated_authorization, source_guard,
)


def request(**changes):
    return {"goal": "repair exact file", "rounds": 3, "idempotencyKey": "request-1",
            "localIntegration": {"acknowledge": True, "allowedFiles": ["core/example.py"],
                                 "teamId": "existing-team", "validForSeconds": 120}, **changes}


def test_recovery_preserves_queued_campaign_owned_by_live_process(env):
    service, child, _, _, _ = env
    queued = service.queue(request())
    service._alive = lambda pid: True
    assert service.recover_active() == queued
    assert child.calls == []


class Child:
    def __init__(self):
        self.records = {}
        self.calls = []
        self.status = "completed"
        self.on_run = lambda: None

    def queue_campaign(self, request, *, source, run_id):
        grant = delegated_authorization({"runId": run_id, "request": request, "_campaignSource": source})
        self.calls.append(("queue", run_id))
        self.records[run_id] = {"runId": run_id, "request": deepcopy(request), "_campaignSource": source,
                                "localIntegrationAuthorization": grant, "status": "queued"}
        return deepcopy(self.records[run_id])

    def run_until_review(self, run_id):
        self.on_run()
        self.records[run_id].update(status=self.status, _campaignExecutionSettled=True,
                                   integration={"status": "committed", "commitSha": "a" * 40},
                                   cleanup={"status": "cleaned", "worktreeRemoved": True, "localBranchDeleted": True})

    def get_campaign(self, run_id, *, source):
        item = self.records.get(run_id)
        if item is not None:
            assert item["_campaignSource"] == source
        return deepcopy(item)

    def cancel_campaign(self, run_id, *, source):
        self.calls.append(("cancel", run_id))
        return self.get_campaign(run_id, source=source)


@pytest.fixture
def env(tmp_path):
    clock = [datetime.now(timezone.utc)]
    issued = []
    def authorize(context):
        issued.append(context)
        local = context["request"]["localIntegration"]
        return {"authorizationId": "grant-1", "operatorId": "operator", "runId": context["runId"],
                "issuedAt": clock[0].isoformat(), "expiresAt": (clock[0] + timedelta(seconds=120)).isoformat(),
                "revoked": False, "allowedFiles": local["allowedFiles"], "teamId": local["teamId"],
                "principals": {role: {"agentId": role, "fingerprint": role} for role in ("observer", "executor", "reviewer")},
                "requestDigest": _digest(local)}
    child = Child()
    store = WorkRunStore(root=tmp_path / "work-runs")
    actor = SelfEvolutionCampaignService(store=store, child=child, authorize=authorize, now=lambda: clock[0])
    return actor, child, store, clock, issued


def test_success_continues_three_rounds_with_one_unrenewed_grant(env):
    actor, child, _, _, issued = env
    queued = actor.queue(request())
    result = actor.run(queued["runId"])
    assert result["status"] == "completed"
    assert result["_campaignExecutionSettled"] is True
    assert len(result["rounds"]) == 3
    assert len(issued) == 1
    assert [run for kind, run in child.calls if kind == "queue"] == [f'{queued["runId"]}-round-{n}' for n in range(1, 4)]
    assert {r["localIntegrationAuthorization"]["expiresAt"] for r in child.records.values()} == {result["localIntegrationAuthorization"]["expiresAt"]}


@pytest.mark.parametrize("status", ["failed", "partial", "running", "awaiting_user_approval"])
def test_unverified_outcome_never_starts_another_round(env, status):
    actor, child, *_ = env
    child.status = status
    result = actor.run(actor.queue(request())["runId"])
    assert result["status"] == ("stopping" if status in {"running", "awaiting_user_approval"} else "stopped")
    assert len(child.records) == 1


def test_idempotency_is_stable_and_conflicting_request_is_rejected(env):
    actor, _, _, _, issued = env
    first = actor.queue(request())
    assert actor.queue(request()) == first
    assert len(issued) == 1
    with pytest.raises(CampaignConflictError):
        actor.queue(request(rounds=2))


def test_expiry_during_child_stops_next_round(env):
    actor, child, _, clock, _ = env
    child.on_run = lambda: clock.__setitem__(0, clock[0] + timedelta(seconds=121))
    result = actor.run(actor.queue(request())["runId"])
    assert result["status"] == "stopped"
    assert len(child.records) == 1


@pytest.mark.parametrize("changes", [{"rounds": True}, {"rounds": 0}, {"rounds": 11},
                                    {"idempotencyKey": ""}, {"idempotencyKey": "x" * 121},
                                    {"localIntegration": None}, {"_campaignSource": {}}])
def test_invalid_campaign_does_not_issue_authority(env, changes):
    actor, _, _, _, issued = env
    with pytest.raises(CampaignValidationError):
        actor.queue(request(**changes))
    assert issued == []


def test_second_active_campaign_is_rejected(env):
    actor, *_ = env
    actor.queue(request())
    with pytest.raises(CampaignConflictError):
        actor.queue(request(idempotencyKey="another"))


def test_missing_snapshot_cannot_mint_new_grant_even_after_index_retention(env):
    actor, _, store, _, issued = env
    queued = actor.queue(request())
    (store.runs_dir(RUN_KIND) / f'{queued["runId"]}.json').unlink()
    store.save_run_index(RUN_KIND, recent_run_ids=[])
    with pytest.raises(CampaignValidationError):
        actor.queue(request())
    assert len(issued) == 1


def test_cancel_fences_delegation_and_targets_only_own_child(env):
    actor, child, *_ = env
    queued = actor.queue(request())
    child.on_run = lambda: actor.cancel(queued["runId"])
    result = actor.run(queued["runId"])
    assert result["stopReason"] == "cancelled"
    assert len(child.records) == 1
    record = next(iter(child.records.values()))
    assert ("cancel", record["runId"]) in child.calls
    with pytest.raises(LocalIntegrationError):
        delegated_authorization(record)


def test_timer_can_cancel_blocking_child_and_second_worker_is_rejected(env):
    actor, child, _, clock, _ = env
    queued = actor.queue(request())
    entered, released = threading.Event(), threading.Event()
    def block():
        entered.set()
        assert released.wait(5)
    child.on_run = block
    thread = threading.Thread(target=actor.run, args=(queued["runId"],))
    thread.start()
    try:
        assert entered.wait(5)
        with pytest.raises(CampaignConflictError):
            actor.run(queued["runId"])
        clock[0] += timedelta(seconds=121)
        assert actor.check_deadline(queued["runId"])["stopRequested"] is True
        assert any(kind == "cancel" for kind, _ in child.calls)
    finally:
        released.set()
        thread.join(5)
    assert not thread.is_alive()
    assert len(child.records) == 1


def test_final_source_guard_serializes_cancel_without_child_lock_deadlock(env):
    actor, child, *_ = env
    queued = actor.queue(request())
    held, release, cancelled = threading.Event(), threading.Event(), threading.Event()
    def hook():
        context = next(iter(child.records.values()))
        with source_guard(context):
            held.set()
            assert release.wait(5)
    child.on_run = hook
    worker = threading.Thread(target=actor.run, args=(queued["runId"],))
    worker.start()
    assert held.wait(5)
    cancellation = threading.Thread(target=lambda: (actor.cancel(queued["runId"]), cancelled.set()))
    cancellation.start()
    assert not cancelled.wait(.05)
    release.set()
    worker.join(5)
    cancellation.join(5)
    assert not worker.is_alive() and not cancellation.is_alive()
    assert cancelled.is_set()


@pytest.mark.parametrize("field", ["request", "grant", "source", "removed_source"])
def test_child_delegation_rejects_changed_canonical_evidence(env, field):
    actor, child, store, *_ = env
    queued = actor.queue(request())
    def validate():
        context = deepcopy(next(iter(child.records.values())))
        if field == "request":
            context["request"]["localIntegration"]["validForSeconds"] = 3600
        elif field == "source":
            context["_campaignSource"]["round"] = 2
        elif field == "removed_source":
            context.pop("_campaignSource")
        else:
            parent = actor.get(queued["runId"])
            parent["localIntegrationAuthorization"]["runId"] = "different-parent"
            store.persist_snapshot(RUN_KIND, parent, active_run_id=parent["runId"])
        with pytest.raises(LocalIntegrationError):
            with source_guard(context):
                delegated_authorization(context)
    child.on_run = validate
    actor.run(queued["runId"])


def test_recovery_preserves_proven_result_without_starting_next_round(env):
    actor, child, store, *_ = env
    queued = actor.queue(request())
    # Simulate a dead worker after the child completed but before recording it.
    source = {"campaignId": queued["runId"], "round": 1,
              "childRunId": queued["runId"] + "-round-1", "storeRoot": str(store.root.resolve())}
    parent = actor.get(queued["runId"])
    parent.update(status="running", _campaignExecutionSettled=False, runtimeOwner={"pid": 123456789})
    parent["rounds"] = [{"runId": source["childRunId"], "round": 1, "source": source, "status": "running"}]
    store.persist_snapshot(RUN_KIND, parent, active_run_id=parent["runId"])
    child.queue_campaign({k: v for k, v in parent["request"].items() if k not in {"rounds", "idempotencyKey"}}, source=source, run_id=source["childRunId"])
    child.run_until_review(source["childRunId"])
    actor._alive = lambda pid: False
    result = actor.recover_active()
    assert result["status"] == "stopped"
    assert result["rounds"][0]["status"] == "completed"
    assert result["rounds"][0]["settled"] is True
    assert len(child.records) == 1


def test_success_without_settlement_or_cleanup_never_continues(env):
    actor, child, *_ = env
    original = child.get_campaign
    def unsettled(run_id, *, source):
        result = original(run_id, source=source)
        if result:
            result["_campaignExecutionSettled"] = False
        return result
    child.get_campaign = unsettled
    result = actor.run(actor.queue(request())["runId"])
    assert result["childUnsettled"] is True
    assert len(child.records) == 1
    with pytest.raises(CampaignConflictError):
        actor.queue(request(idempotencyKey="another"))


def test_cancel_after_intent_before_dispatch_releases_absent_child(env):
    actor, child, *_ = env
    queued = actor.queue(request())
    original = actor.check_deadline
    calls = []
    def cancel_before_dispatch(run_id):
        calls.append(run_id)
        if len(calls) == 2:
            actor.cancel(run_id)
        return original(run_id)
    actor.check_deadline = cancel_before_dispatch
    result = actor.run(queued["runId"])
    assert result["status"] == "stopped"
    assert result["childUnsettled"] is False
    assert result["stopReason"] == "cancelled"
    assert child.records == {}
    assert actor.queue(request(idempotencyKey="next"))["status"] == "queued"


def test_dispatch_exception_after_committed_child_preserves_receipt(env):
    actor, child, *_ = env
    queued = actor.queue(request())
    original = child.queue_campaign
    def committed_then_error(request, *, source, run_id):
        original(request, source=source, run_id=run_id)
        child.records[run_id].update(status="partial", _campaignExecutionSettled=True,
                                    integration={"status": "committed", "commitSha": "b" * 40},
                                    independentReview={"sessionId": "review-session", "turnId": "review-turn"},
                                    cleanup={"status": "pending"})
        raise OSError("dispatch response lost")
    child.queue_campaign = committed_then_error
    result = actor.run(queued["runId"])
    assert result["status"] == "stopped"
    assert result["rounds"][0]["commitSha"] == "b" * 40
    assert result["rounds"][0]["cleanupStatus"] == "pending"
    assert result["rounds"][0]["reviewSessionId"] == "review-session"
    assert len(child.records) == 1


def test_cancellation_during_atomic_merge_keeps_commit_receipt(env):
    actor, child, *_ = env
    queued = actor.queue(request())
    def commit_then_cancel():
        current = next(iter(child.records.values()))
        current.update(integration={"status": "committed", "commitSha": "c" * 40},
                       _campaignExecutionSettled=False)
        pending = actor.cancel(queued["runId"])
        assert pending["status"] == "stopping"
        assert pending["childUnsettled"] is True
    child.on_run = commit_then_cancel
    result = actor.run(queued["runId"])
    assert result["status"] == "stopped"
    assert result["rounds"][0]["commitSha"] == "a" * 40
    assert result["childUnsettled"] is False


def test_real_single_loop_owner_runs_each_round_and_settles_before_continuation(env, tmp_path):
    from tests.test_self_evolution_autonomous_loop_service import _build_service
    actor, _, store, *_ = env
    def review(context):
        return {"candidate": {**context["candidate"], "headCommit": "d" * 40},
                "independentReview": {"verdict": "passed", "candidateCommit": "d" * 40,
                                      "reviewerAgentId": "reviewer", "sessionId": "review", "turnId": "turn",
                                      "evidenceRefs": ["test:review"]}}
    child, calls = _build_service(tmp_path, hook_overrides={
        "authorize": delegated_authorization, "review": review,
        "check_authorization": delegated_authorization,
    })
    assert child._store.root == store.root
    actor.child = child
    payload = request(localIntegration={**request()["localIntegration"],
                                        "allowedFiles": ["core/example.py", "tests/test_example.py"]})
    result = actor.run(actor.queue(payload)["runId"])
    assert result["status"] == "completed"
    assert [name for name, _ in calls] == ["observe", "plan", "evolve", "integrate", "cleanup"] * 3
    assert all(item["settled"] is True for item in result["rounds"])
    assert all(child.get_campaign(item["runId"], source=item["source"])["_campaignExecutionSettled"] is True
               for item in result["rounds"])


def _admission_worker(root, key, gate):
    """Independent process entry used only by the admission concurrency test."""
    def authorize(context):
        now = datetime.now(timezone.utc)
        local = context["request"]["localIntegration"]
        return {"authorizationId": "grant", "operatorId": "operator", "runId": context["runId"],
                "issuedAt": now.isoformat(), "expiresAt": (now + timedelta(seconds=120)).isoformat(),
                "revoked": False, "allowedFiles": local["allowedFiles"], "teamId": local["teamId"],
                "principals": {role: {"agentId": role, "fingerprint": role} for role in ("observer", "executor", "reviewer")},
                "requestDigest": _digest(local)}
    actor = SelfEvolutionCampaignService(store=WorkRunStore(root=Path(root)), child=Child(), authorize=authorize)
    deadline = time.monotonic() + 10
    while not Path(gate).exists():
        if time.monotonic() >= deadline:
            raise RuntimeError("test gate timeout")
        time.sleep(.01)
    try:
        actor.queue(request(idempotencyKey=key))
        print("admitted")
    except CampaignConflictError:
        print("conflict")


def test_cross_process_admission_allows_only_one_campaign(tmp_path):
    gate = tmp_path / "ready"
    root = tmp_path / "runs"
    script = ("import sys; from tests.test_self_evolution_campaign_service import _admission_worker; "
              "_admission_worker(*sys.argv[1:])")
    hidden = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    processes = [subprocess.Popen([sys.executable, "-c", script, str(root), key, str(gate)],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, **hidden) for key in ("first", "second")]
    try:
        gate.touch()
        outcomes = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=20)
            assert process.returncode == 0, stderr
            outcomes.append(stdout.strip().splitlines()[-1])
        assert sorted(outcomes) == ["admitted", "conflict"]
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
