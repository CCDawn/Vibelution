"""Failure recovery is driven by durable workflow attempts and native Turns."""
from __future__ import annotations

import importlib
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from core.web.services.team_workflow.generic import native, runtime, service, store
from core.web.services.team_workflow.generic.models import Flow
from tests.test_generic_team_workflows import definition, env, start, tick


@pytest.fixture
def recovery_env(env):
    env.teams["team-a"]["members"].extend(
        {"agentId": agent_id} for agent_id in ("director", "developer", "reviewer")
    )
    return env


def repair_definition(**overrides):
    flow = definition(
        id="repair-flow", name="故障修复",
        fields=[{"id": "incident", "label": "故障", "kind": "paragraph", "required": True}],
        steps=[
            {"id": "diagnose", "label": "诊断", "kind": "agent", "owner": "director", "instruction": "定位故障"},
            {"id": "develop", "label": "修复", "kind": "agent", "owner": "developer", "instruction": "修复故障"},
            {"id": "verify", "label": "验收", "kind": "agent", "owner": "reviewer", "instruction": "独立验收"},
        ],
    )
    flow.update(overrides)
    return flow


def policy(**overrides):
    value = {"repairFlowId": "repair-flow", "directorAgentId": "director", "reviewerAgentId": "reviewer",
             "replaySafety": "idempotent", "maxAttempts": 3, "maxRepairAttempts": 2}
    value.update(overrides)
    return value


def configured(recovery_env, **overrides):
    service.save_flow("team-a", "repair-flow", {"flow": repair_definition(), "expectedRevision": 0})
    service.save_flow("team-a", "flow-a", {
        "flow": definition(failureRecovery=policy(**overrides)), "expectedRevision": 0,
    })
    return tick(start(), 2)


def scan(run, count=1):
    recovery = importlib.import_module("core.web.services.team_workflow.generic.recovery")
    for _ in range(count):
        recovery.reconcile_recovery("team-a", run["id"])
    return service.get_run("team-a", run["id"])


def fail(env, run, code="provider_error"):
    attempt = run["attempts"][-1]
    env.sessions.finish(attempt, status="failed_runtime", content="")
    env.sessions.turns[attempt["key"]]["terminalProblemCode"] = code
    return tick(run)


def child_of(run):
    return service.get_run("team-a", run["recovery"]["repairRunId"])


def finish_repair(env, run, verdict=None):
    child = child_of(run)
    result = verdict if verdict is not None else {
        "verdict": "passed", "deploymentRequired": False,
        "effectVerified": True, "evidenceRefs": ["test:repair-effect"],
    }
    for owner in ("director", "developer", "reviewer"):
        child = tick(child)
        attempt = child["attempts"][-1]
        assert attempt["agentId"] == owner
        content = result if isinstance(result, str) else json.dumps(result)
        env.sessions.finish(attempt, content=content if owner == "reviewer" else "修复证据")
        child = tick(child)
    assert tick(child)["status"] == "completed"
    return scan(run)


def escalated(env, **overrides):
    return scan(fail(env, configured(env, maxAttempts=1, **overrides)))


def test_three_real_failures_create_exactly_one_durable_repair_run(recovery_env):
    run = configured(recovery_env)
    for number in range(1, 4):
        run = fail(recovery_env, run)
        assert run["attempts"][-1]["failureCode"] == "provider_error"
        run = scan(run, 3)
        assert run["recovery"]["failureCount"] == number
        if number < 3:
            run = tick(run)
            assert len(run["attempts"]) == number + 1
    state = run["recovery"]
    assert state["repairAttempts"] == 1 and state["repairRunId"]
    assert state["nodeId"] == "work"
    child = service.get_run("team-a", state["repairRunId"])
    assert child["flow"]["id"] == "repair-flow"
    assert set(child["values"]) == {"incident"}
    assert run["id"] in child["values"]["incident"]
    before = store.read(store.path("team-a", "runs", run["id"]))
    scan(run, 5)
    assert store.read(store.path("team-a", "runs", run["id"])) == before
    assert len(service.list_runs("team-a")["runs"]) == 2


def test_policy_defaults_and_bounded_attempts():
    value = policy()
    for key in ("replaySafety", "maxAttempts", "maxRepairAttempts"):
        value.pop(key)
    parsed = Flow.model_validate(definition(failureRecovery=value)).model_dump()["failureRecovery"]
    assert parsed["replaySafety"] == "unknown"
    assert parsed["maxAttempts"] == 3 and parsed["maxRepairAttempts"] == 2
    assert parsed["repairTimeoutSeconds"] == 1800


def test_configured_successful_source_never_creates_a_spurious_incident(recovery_env):
    run = configured(recovery_env)
    assert scan(run, 3)["recovery"] is None
    recovery_env.sessions.finish(run["attempts"][-1])
    run = scan(tick(run), 3)
    assert run["recovery"] is None
    assert len(service.list_runs("team-a")["runs"]) == 1


@pytest.mark.parametrize("patch", [
    {"maxAttempts": 0}, {"maxAttempts": 4},
    {"maxRepairAttempts": 0}, {"maxRepairAttempts": 4},
    {"replaySafety": "assumed_safe"},
])
def test_policy_rejects_unbounded_or_unclassified_replay(patch):
    with pytest.raises(ValidationError):
        Flow.model_validate(definition(failureRecovery=policy(**patch)))


@pytest.mark.parametrize("mutation", [
    "too_short", "wrong_director", "wrong_reviewer", "reviewer_develops",
    "same_director_reviewer", "director_develops", "extra_input", "wrong_input", "recursive",
])
def test_invalid_repair_template_is_rejected_before_source_dispatch(recovery_env, mutation):
    repair = repair_definition()
    recovery_policy = policy()
    if mutation == "too_short":
        repair["steps"].pop(1)
    elif mutation == "wrong_director":
        repair["steps"][0]["owner"] = "developer"
    elif mutation == "wrong_reviewer":
        repair["steps"][-1]["owner"] = "developer"
    elif mutation == "reviewer_develops":
        repair["steps"][1]["owner"] = "reviewer"
    elif mutation == "same_director_reviewer":
        recovery_policy["reviewerAgentId"] = "director"
        repair["steps"][-1]["owner"] = "director"
    elif mutation == "director_develops":
        repair["steps"][1]["owner"] = "director"
    elif mutation == "extra_input":
        repair["fields"].append({"id": "extra", "label": "额外", "kind": "text"})
    elif mutation == "wrong_input":
        repair["fields"][0]["id"] = "subject"
    elif mutation == "recursive":
        repair["failureRecovery"] = policy()
    service.save_flow("team-a", "repair-flow", {"flow": repair, "expectedRevision": 0})
    service.save_flow("team-a", "flow-a", {
        "flow": definition(failureRecovery=recovery_policy), "expectedRevision": 0,
    })
    with pytest.raises(store.WorkflowError):
        start()
    assert not service.list_runs("team-a")["runs"]
    assert not recovery_env.sessions.submitted


def test_duplicate_scans_do_not_count_one_failure_more_than_once(recovery_env):
    run = fail(recovery_env, configured(recovery_env))
    run = scan(run, 10)
    assert run["recovery"]["failureCount"] == 1
    assert run["recovery"]["repairAttempts"] == 0
    assert len(service.list_runs("team-a")["runs"]) == 1
    run = tick(run)
    assert len(run["attempts"]) == 2
    assert len(recovery_env.sessions.submitted) == 2


def test_runtime_restart_discovers_failed_persisted_run_without_request_side_dispatch(recovery_env):
    run = fail(recovery_env, configured(recovery_env, maxAttempts=1))
    assert len(service.list_runs("team-a")["runs"]) == 1
    runtime.reconcile_all()
    restored = service.get_run("team-a", run["id"])
    assert restored["recovery"]["repairAttempts"] == 1
    child_id = restored["recovery"]["repairRunId"]
    for _ in range(4):
        runtime.reconcile_all()
    assert service.get_run("team-a", run["id"])["recovery"]["repairRunId"] == child_id
    assert len(service.list_runs("team-a")["runs"]) == 2


def test_restart_recovers_child_create_ack_without_duplicate_repair(recovery_env, monkeypatch):
    run = fail(recovery_env, configured(recovery_env, maxAttempts=1))
    original = service.create_repair_run

    def accepted_then_error(*args, **kwargs):
        original(*args, **kwargs)
        raise OSError("repair create receipt lost")

    monkeypatch.setattr(service, "create_repair_run", accepted_then_error)
    runtime.reconcile_all()
    persisted = service.get_run("team-a", run["id"])
    child_id = persisted["recovery"]["repairRunId"]
    assert child_id and len(service.list_runs("team-a")["runs"]) == 2
    monkeypatch.setattr(service, "create_repair_run", original)
    for _ in range(5):
        runtime.reconcile_all()
    restored = service.get_run("team-a", run["id"])
    assert restored["recovery"]["repairRunId"] == child_id
    assert restored["recovery"]["repairAttempts"] == 1
    assert len(service.list_runs("team-a")["runs"]) == 2
    assert len(recovery_env.sessions.submitted) == 2  # source and one director Turn


def test_removed_child_member_cannot_receive_new_native_work(recovery_env):
    run = escalated(recovery_env)
    child = tick(child_of(run))
    assert child["attempts"][-1]["agentId"] == "director"
    recovery_env.sessions.finish(child["attempts"][-1])
    tick(child)
    recovery_env.teams["team-a"]["members"] = [
        member for member in recovery_env.teams["team-a"]["members"] if member["agentId"] != "developer"
    ]
    before = len(recovery_env.sessions.submitted)
    for _ in range(6):
        runtime.reconcile_all()
    restored = service.get_run("team-a", run["id"])
    assert restored["recovery"]["status"] != "resolved"
    assert len(restored["attempts"]) == 1
    assert len(recovery_env.sessions.submitted) == before
    for item in service.list_runs("team-a")["runs"]:
        assert all(attempt["agentId"] != "developer" for attempt in item["attempts"])


@pytest.mark.parametrize("after_repair", [False, True])
def test_unknown_native_execution_identity_never_replays_source(recovery_env, monkeypatch, after_repair):
    run = escalated(recovery_env) if after_repair else fail(recovery_env, configured(recovery_env))
    monkeypatch.setattr(native, "recovery", lambda attempt: "unknown_blocked")
    run = finish_repair(recovery_env, run) if after_repair else scan(run, 3)
    assert len(tick(scan(run, 3), 3)["attempts"]) == 1
    assert run["recovery"]["status"] != "resolved"


def test_different_failure_code_resets_streak_but_total_budget_still_escalates(recovery_env):
    run = configured(recovery_env)
    for index, code in enumerate(("provider_error", "network_error", "policy_error"), 1):
        run = scan(fail(recovery_env, run, code))
        assert run["recovery"]["failureCount"] == 1
        if index < 3:
            run = tick(run)
    assert run["recovery"]["repairAttempts"] == 1
    assert run["recovery"]["repairRunId"]
    assert len(run["attempts"]) == 3


def test_unknown_safety_never_automatically_replays_source(recovery_env):
    run = scan(fail(recovery_env, configured(recovery_env, replaySafety="unknown")), 10)
    tick(run, 3)
    assert len(service.get_run("team-a", run["id"])["attempts"]) == 1


def test_repair_uses_frozen_template_even_after_flow_definition_changes(recovery_env):
    run = configured(recovery_env, maxAttempts=1)
    service.save_flow("team-a", "repair-flow", {
        "flow": repair_definition(name="已编辑的新版本", steps=[]), "expectedRevision": 1,
    })
    run = scan(fail(recovery_env, run))
    child = child_of(run)
    assert child["flow"]["revision"] == 1
    assert child["flow"]["name"] == "故障修复"
    assert [step["owner"] for step in child["flow"]["steps"]] == ["director", "developer", "reviewer"]


@pytest.mark.parametrize("safety", ["read_only", "idempotent"])
def test_passed_repair_only_resolves_after_new_source_attempt_succeeds(recovery_env, safety):
    run = escalated(recovery_env, replaySafety=safety)
    run = finish_repair(recovery_env, run)
    assert run["recovery"]["status"] != "resolved"
    assert run["recovery"]["evidenceRefs"]
    assert run["recovery"]["reviewerSessionId"]
    assert run["recovery"]["reviewerTurnId"]
    run = tick(run)
    assert len(run["attempts"]) == 2
    assert run["attempts"][-1]["key"] != run["attempts"][0]["key"]
    assert run["recovery"]["status"] != "resolved"
    recovery_env.sessions.finish(run["attempts"][-1])
    run = scan(tick(run))
    assert run["recovery"]["status"] == "resolved"


def test_successful_repair_of_unknown_replay_waits_for_human_decision(recovery_env):
    run = finish_repair(recovery_env, escalated(recovery_env, replaySafety="unknown"))
    assert run["recovery"]["status"] == "awaiting_replay_decision"
    assert len(tick(run, 3)["attempts"]) == 1


def test_deployment_confirmation_requires_evidence_and_fresh_reviewer_verification(recovery_env):
    run = finish_repair(recovery_env, escalated(recovery_env), {
        "verdict": "passed", "deploymentRequired": True,
        "effectVerified": False, "evidenceRefs": ["test:repair-requires-restart"],
    })
    assert run["recovery"]["status"] == "awaiting_deployment"
    first_child_id = run["recovery"]["repairRunId"]
    for action in ("retry", "confirm_deployment"):
        with pytest.raises((store.WorkflowError, ValidationError)):
            service.command_run("team-a", run["id"], {"action": action, "expectedRevision": run["revision"]})
    assert len(tick(scan(run, 3), 2)["attempts"]) == 1
    run = service.get_run("team-a", run["id"])
    run = service.command_run("team-a", run["id"], {
        "action": "confirm_deployment", "evidenceRef": "launcher:deployment-42",
        "expectedRevision": run["revision"],
    })
    run = scan(run)
    child = child_of(run)
    assert child["id"] != first_child_id
    executable = [step for step in child["flow"]["steps"] if service.executable(step)]
    assert len(executable) == 1 and executable[0]["owner"] == "reviewer"
    assert "launcher:deployment-42" in run["recovery"]["evidenceRefs"]
    assert len(tick(run, 2)["attempts"]) == 1
    child = tick(child)
    assert len(child["attempts"]) == 1 and child["attempts"][0]["agentId"] == "reviewer"
    recovery_env.sessions.finish(child["attempts"][0], content=json.dumps({
        "verdict": "passed", "deploymentRequired": False,
        "effectVerified": True, "evidenceRefs": ["runtime:post-deployment-effect"],
    }))
    tick(child, 2)
    run = scan(run)
    assert run["recovery"]["status"] != "resolved"
    run = tick(run)
    assert len(run["attempts"]) == 2
    recovery_env.sessions.finish(run["attempts"][-1])
    assert scan(tick(run))["recovery"]["status"] == "resolved"


@pytest.mark.parametrize("verdict", [
    "not a JSON review",
    "修复已经完成，应该没有问题。",
    {"verdict": "failed", "deploymentRequired": False, "effectVerified": True, "evidenceRefs": ["test:effect"]},
    {"verdict": "passed", "deploymentRequired": False, "effectVerified": False, "evidenceRefs": ["test:effect"]},
    {"verdict": "passed", "deploymentRequired": False, "effectVerified": True, "evidenceRefs": []},
    {"verdict": "passed", "effectVerified": True, "evidenceRefs": ["test:effect"]},
])
def test_incomplete_or_failed_review_cannot_replay_source(recovery_env, verdict):
    run = finish_repair(recovery_env, escalated(recovery_env), verdict)
    assert run["recovery"]["status"] != "resolved"
    assert len(tick(run, 3)["attempts"]) == 1


@pytest.mark.parametrize("snapshot_patch", [
    {"turnId": "unrelated-turn"}, {"assistantTurnId": "unrelated-turn"},
    {"terminal": False}, {"terminalStatus": "failed_runtime"},
])
def test_review_requires_fresh_successful_exact_turn_snapshot(recovery_env, snapshot_patch):
    run = escalated(recovery_env)
    child = child_of(run)
    for _ in range(2):
        child = tick(child)
        recovery_env.sessions.finish(child["attempts"][-1])
        child = tick(child)
    child = tick(child)
    reviewer = child["attempts"][-1]
    recovery_env.sessions.finish(reviewer, content=json.dumps({
        "verdict": "passed", "deploymentRequired": False,
        "effectVerified": True, "evidenceRefs": ["test:unrelated-turn"],
    }))
    assert tick(child, 2)["status"] == "completed"
    # A completed workflow projection alone is insufficient evidence. Re-read
    # the canonical exact reviewer Turn before authorizing source replay.
    recovery_env.sessions.turns[reviewer["key"]].update(snapshot_patch)
    run = scan(run, 3)
    assert len(tick(run, 3)["attempts"]) == 1
    assert run["recovery"]["status"] != "resolved"


def test_repair_failures_are_bounded_and_restart_scan_does_not_dispatch_more(recovery_env):
    run = escalated(recovery_env)
    for number in (1, 2):
        child = tick(child_of(run))
        recovery_env.sessions.finish(child["attempts"][-1], status="failed_runtime", content="")
        tick(child)
        run = scan(run)
        if number == 1:
            assert run["recovery"]["repairAttempts"] == 2
    assert run["recovery"]["status"] == "blocked"
    ids = {item["id"] for item in service.list_runs("team-a")["runs"]}
    submitted = len(recovery_env.sessions.submitted)
    for _ in range(5):
        runtime.reconcile_all()
    assert service.get_run("team-a", run["id"])["recovery"]["status"] == "blocked"
    assert {item["id"] for item in service.list_runs("team-a")["runs"]} == ids
    assert len(recovery_env.sessions.submitted) == submitted


def test_stop_blocks_new_repair_dispatch_and_stops_existing_child(recovery_env):
    run = escalated(recovery_env)
    child = tick(child_of(run))
    before = len(recovery_env.sessions.submitted)
    run = service.command_run("team-a", run["id"], {"action": "stop", "expectedRevision": run["revision"]})
    for _ in range(4):
        runtime.reconcile_all()
    run = service.get_run("team-a", run["id"])
    child = service.get_run("team-a", child["id"])
    assert run["stopRequested"] and child["stopRequested"]
    assert child["status"] == "stopped"
    assert len(recovery_env.sessions.submitted) == before
    assert len(service.list_runs("team-a")["runs"]) == 2


def test_stop_before_recovery_scan_never_creates_a_repair_child(recovery_env):
    run = fail(recovery_env, configured(recovery_env, maxAttempts=1))
    run = service.command_run("team-a", run["id"], {"action": "stop", "expectedRevision": run["revision"]})
    before = len(recovery_env.sessions.submitted)
    for _ in range(4):
        runtime.reconcile_all()
    assert service.get_run("team-a", run["id"])["status"] == "stopped"
    assert len(service.list_runs("team-a")["runs"]) == 1
    assert len(recovery_env.sessions.submitted) == before


def test_flow_without_recovery_keeps_existing_manual_failure_semantics(recovery_env):
    service.save_flow("team-a", "flow-a", {"flow": definition(), "expectedRevision": 0})
    run = scan(fail(recovery_env, tick(start(), 2)), 5)
    assert run["status"] == "failed"
    assert run.get("recovery") is None
    assert len(run["attempts"]) == 1
    assert len(service.list_runs("team-a")["runs"]) == 1


def test_uncertain_failed_child_cannot_start_a_second_repair(recovery_env, monkeypatch):
    from core.web.services.team_workflow.generic import native

    run = escalated(recovery_env)
    child = tick(child_of(run))
    original_snapshot = native.snapshot

    def unavailable(attempt):
        if attempt["key"] == child["attempts"][-1]["key"]:
            raise ConnectionError("receipt read unavailable")
        return original_snapshot(attempt)

    monkeypatch.setattr(native, "snapshot", unavailable)
    assert tick(child)["status"] == "failed"
    run = scan(run)
    assert run["recovery"]["status"] == "blocked"
    assert run["recovery"]["reason"] == "repair_execution_uncertain"
    assert run["recovery"]["repairAttempts"] == 1
    assert len(service.list_runs("team-a")["runs"]) == 2
    with pytest.raises(store.Conflict):
        service.command_run("team-a", run["id"], {"action": "retry", "expectedRevision": run["revision"]})


def test_completed_review_with_unavailable_native_receipt_is_visibly_blocked(recovery_env, monkeypatch):
    from core.web.services.team_workflow.generic import native

    run = escalated(recovery_env)
    child = child_of(run)
    for _ in range(3):
        child = tick(child)
        recovery_env.sessions.finish(child["attempts"][-1], content=json.dumps({
            "verdict": "passed", "deploymentRequired": False,
            "effectVerified": True, "evidenceRefs": ["test:effect"],
        }))
        child = tick(child)
    assert tick(child)["status"] == "completed"
    monkeypatch.setattr(native, "snapshot", lambda attempt: (_ for _ in ()).throw(OSError("unavailable")))
    run = scan(run, 3)
    assert run["recovery"]["status"] == "blocked"
    assert run["recovery"]["reason"] == "repair_execution_uncertain"
    assert run["recovery"]["repairAttempts"] == 1
    assert len(service.list_runs("team-a")["runs"]) == 2


def test_missing_child_dispatch_intent_has_a_persisted_timeout(recovery_env, monkeypatch):
    run = configured(recovery_env, maxAttempts=1)
    original = service.create_repair_run
    monkeypatch.setattr(service, "create_repair_run", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk unavailable")))
    with pytest.raises(OSError):
        scan(fail(recovery_env, run))
    target = store.path("team-a", "runs", run["id"])
    record = store.read(target)
    record["_recoveryQueuedAt"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    store.write(target, record)
    monkeypatch.setattr(service, "create_repair_run", original)
    run = scan(run, 3)
    assert run["recovery"]["status"] == "blocked"
    assert run["recovery"]["reason"] == "repair_timeout"
    assert len(service.list_runs("team-a")["runs"]) == 1


@pytest.mark.parametrize("director_finished", [False, True])
def test_audit_parent_stop_fences_child_dispatch_before_recovery_scan(recovery_env, director_finished):
    run = escalated(recovery_env)
    child = child_of(run)
    if director_finished:
        child = tick(child)
        recovery_env.sessions.finish(child["attempts"][-1])
        child = tick(child)
        assert child["current"] == 1 and len(child["attempts"]) == 1
    else:
        assert not child["attempts"]
    run = service.command_run("team-a", run["id"], {"action": "stop", "expectedRevision": run["revision"]})
    before = len(recovery_env.sessions.submitted)
    # Deliberately bypass recovery scanning: the native dispatcher must fence
    # parent cancellation on its own before beginning the next child step.
    service.reconcile_run("team-a", child["id"])
    stopped = service.get_run("team-a", child["id"])
    assert stopped["stopRequested"] and stopped["status"] == "stopped"
    assert len(recovery_env.sessions.submitted) == before


def test_audit_repair_template_cannot_wait_on_human_approval(recovery_env):
    repair = repair_definition()
    repair["steps"].insert(1, {"id": "approval", "label": "确认", "kind": "human", "owner": "用户"})
    service.save_flow("team-a", "repair-flow", {"flow": repair, "expectedRevision": 0})
    service.save_flow("team-a", "flow-a", {
        "flow": definition(failureRecovery=policy()), "expectedRevision": 0,
    })
    with pytest.raises(store.WorkflowError):
        start()
    assert not service.list_runs("team-a")["runs"]
    assert not recovery_env.sessions.submitted


def test_audit_initial_safe_retry_success_resolves_without_repair(recovery_env):
    run = scan(fail(recovery_env, configured(recovery_env)))
    assert run["recovery"]["repairAttempts"] == 0
    run = tick(run)
    assert len(run["attempts"]) == 2
    recovery_env.sessions.finish(run["attempts"][-1])
    run = scan(tick(run))
    assert run["recovery"]["status"] == "resolved"
    assert run["recovery"]["repairAttempts"] == 0
    assert run["recovery"]["replayedAttemptKey"] == run["attempts"][-1]["key"]
    assert len(service.list_runs("team-a")["runs"]) == 1


def test_audit_unknown_replay_user_retry_success_resolves_without_repair(recovery_env):
    run = scan(fail(recovery_env, configured(recovery_env, replaySafety="unknown")))
    assert len(run["attempts"]) == 1 and run["recovery"]["repairAttempts"] == 0
    run = service.command_run("team-a", run["id"], {"action": "retry", "expectedRevision": run["revision"]})
    run = tick(run)
    assert len(run["attempts"]) == 2
    recovery_env.sessions.finish(run["attempts"][-1])
    run = scan(tick(run))
    assert run["recovery"]["status"] == "resolved"
    assert run["recovery"]["repairAttempts"] == 0
    assert run["recovery"]["replayedAttemptKey"] == run["attempts"][-1]["key"]


def test_audit_repair_timeout_stops_child_and_never_dispatches_more(recovery_env):
    run = escalated(recovery_env, repairTimeoutSeconds=60)
    child = tick(child_of(run))
    target = store.path("team-a", "runs", child["id"])
    record = store.read(target)
    record["createdAt"] = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    store.write(target, record)
    before = len(recovery_env.sessions.submitted)
    run = scan(run)
    assert run["recovery"]["status"] == "blocked"
    assert run["recovery"]["reason"] == "repair_timeout"
    assert child_of(run)["stopRequested"]
    for _ in range(4):
        runtime.reconcile_all()
    assert child_of(run)["status"] == "stopped"
    assert len(recovery_env.sessions.submitted) == before
    assert len(service.list_runs("team-a")["runs"]) == 2


def test_audit_http_policy_recovery_and_deployment_evidence_contract(recovery_env):
    from core.web.routes.generic_team_workflows import register_generic_team_workflow_routes

    app = FastAPI()
    router = APIRouter()
    register_generic_team_workflow_routes(router)
    app.include_router(router)
    with TestClient(app) as client:
        base = "/teams/team-a"
        response = client.put(f"{base}/workflows/repair-flow", json={"flow": repair_definition(), "expectedRevision": 0})
        assert response.status_code == 200
        response = client.put(f"{base}/workflows/flow-a", json={
            "flow": definition(failureRecovery=policy(maxAttempts=1)), "expectedRevision": 0,
        })
        assert response.status_code == 200
        assert response.json()["failureRecovery"]["maxAttempts"] == 1
        response = client.post(f"{base}/workflows/flow-a/runs", json={
            "values": {"subject": "API输入"}, "expectedRevision": 1, "idempotencyKey": "audit-http",
        })
        assert response.status_code == 200
        run = scan(fail(recovery_env, tick(response.json(), 2)))
        run = finish_repair(recovery_env, run, {
            "verdict": "passed", "deploymentRequired": True,
            "effectVerified": False, "evidenceRefs": ["test:http-deployment-needed"],
        })
        endpoint = f"{base}/workflow-runs/{run['id']}"
        response = client.get(endpoint)
        assert response.status_code == 200
        assert response.json()["flow"]["failureRecovery"]["replaySafety"] == "idempotent"
        assert response.json()["recovery"]["status"] == "awaiting_deployment"
        assert not any(key.startswith("_") for key in response.json())
        for patch in ({}, {"evidenceRef": "  "}, {"evidenceRef": "x" * 501}):
            response = client.post(f"{endpoint}/commands", json={
                "action": "confirm_deployment", "expectedRevision": run["revision"], **patch,
            })
            assert response.status_code == 422
        response = client.post(f"{endpoint}/commands", json={
            "action": "confirm_deployment", "evidenceRef": "launcher:http-deployed",
            "expectedRevision": run["revision"] - 1,
        })
        assert response.status_code == 409
        response = client.post(f"{endpoint}/commands", json={
            "action": "confirm_deployment", "evidenceRef": "launcher:http-deployed",
            "expectedRevision": run["revision"],
        })
        assert response.status_code == 200
        assert response.json()["recovery"]["status"] == "repairing"
        assert "launcher:http-deployed" in client.get(endpoint).json()["recovery"]["evidenceRefs"]


def test_audit_recovery_events_contain_references_and_state_without_private_content(recovery_env, monkeypatch):
    recovery = importlib.import_module("core.web.services.team_workflow.generic.recovery")
    events = []
    monkeypatch.setattr(recovery, "record_runtime_scene_event", lambda *args, **kwargs: events.append((args, kwargs)))
    source_input = "private-source-input-should-not-enter-events"
    private_review = "private-review-body-should-not-enter-events"
    service.save_flow("team-a", "repair-flow", {"flow": repair_definition(), "expectedRevision": 0})
    service.save_flow("team-a", "flow-a", {
        "flow": definition(failureRecovery=policy(maxAttempts=1)), "expectedRevision": 0,
    })
    run = scan(fail(recovery_env, tick(start(values={"subject": source_input}), 2)))
    run = finish_repair(recovery_env, run, {
        "verdict": "passed", "deploymentRequired": False,
        "effectVerified": True, "evidenceRefs": [private_review],
    })
    run = tick(run)
    recovery_env.sessions.finish(run["attempts"][-1])
    run = scan(tick(run))
    assert events and events[-1][1]["fields"]["status"] == "resolved"
    allowed = {"teamId", "runId", "issueId", "nodeId", "status", "reason",
               "failureCount", "repairAttempts", "repairRunId"}
    for _, event in events:
        fields = event["fields"]
        assert set(fields) <= allowed
        assert fields["runId"] == run["id"] and fields["teamId"] == "team-a"
        assert isinstance(fields["failureCount"], int) and isinstance(fields["repairAttempts"], int)
    serialized = json.dumps(events)
    assert source_input not in serialized and private_review not in serialized
    assert "assistantText" not in serialized and "evidenceRefs" not in serialized
