"""Recovery bindings opt in without granting tools or replacing task authority."""
from __future__ import annotations

import copy
import importlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest

from core.web.services.team_workflow.generic import native, service, store
from core.web.services.team_workflow.generic.native import recovery as native_recovery
from tests.test_generic_team_workflows import definition, env, tick
from tests.test_generic_workflow_recovery import repair_definition


@pytest.fixture
def bound_env(env, monkeypatch):
    from core.web.services import agent_directory_service as directory
    from core.web.services import personal_assistant_service as assistant
    from core.web.services import agent_tool_governance_service as grants

    ids = ("agent-a", "assistant", "director", "developer", "reviewer")
    env.teams["team-a"]["members"] = [{"agentId": value} for value in ids]
    agents = {value: {"agentId": value, "status": "active", "primaryMode": "chat",
                      "permissionPreset": "default", "roleKey": "",
                      "toolPolicy": {"allowedTools": ["read_file_tool"], "writeScopes": []}}
              for value in ids}
    monkeypatch.setattr(directory, "get_agent", lambda value, **kwargs: copy.deepcopy(agents.get(value)))
    monkeypatch.setattr(assistant, "get_personal_assistant", lambda: {
        "assistant": {"agentId": "assistant", "setupStatus": "ready"}})
    monkeypatch.setattr(grants, "temporary_granted_tools_for_agent", lambda *args, **kwargs: [])
    service.save_flow("team-a", "repair-flow", {"flow": repair_definition(), "expectedRevision": 0})
    service.save_flow("team-a", "flow-a", {"flow": definition(), "expectedRevision": 0})
    env.agents = agents
    return env


def payload(**updates):
    request = {"expectedRevision": 1, "repairFlowId": "repair-flow", "assistantAgentId": "assistant",
               "directorAgentId": "director", "developerAgentId": "developer", "reviewerAgentId": "reviewer",
               "acknowledgeAutomaticRecovery": True, "replaySafety": "idempotent"}
    request.update(updates)
    return request


def module():
    return importlib.import_module("core.web.services.team_workflow.generic.binding")


def test_binding_uses_existing_flow_authority_and_does_not_grant_permissions(bound_env):
    before = copy.deepcopy(bound_env.agents)
    result = module().bind_recovery("team-a", "flow-a", payload())
    assert result["status"] == "ready"
    assert result["assistantAgentId"] == "assistant"
    assert result["developerAgentId"] == "developer"
    assert result["automaticLocalIntegration"] is False
    source = store.read(store.path("team-a", "flows", "flow-a"))
    assert source["revision"] == 2
    policy = source["failureRecovery"]
    assert policy["bindingId"] and policy["expiresAt"]
    assert policy["repairFlowRevision"] == 1
    assert set(policy["agentPolicyFingerprints"]) == set(bound_env.agents)
    assert bound_env.agents == before
    assert service.list_runs("team-a")["runs"] == []


def test_binding_requires_explicit_opt_in_and_distinct_roles(bound_env):
    with pytest.raises((store.WorkflowError, ValueError)):
        module().bind_recovery("team-a", "flow-a", payload(acknowledgeAutomaticRecovery=False))
    with pytest.raises((store.WorkflowError, ValueError)):
        module().bind_recovery("team-a", "flow-a", payload(developerAgentId="reviewer"))
    assert store.read(store.path("team-a", "flows", "flow-a"))["revision"] == 1


def test_readiness_is_pure_and_revocation_is_compare_and_swap(bound_env):
    assert module().get_recovery_binding("team-a", "flow-a")["status"] == "unbound"
    module().bind_recovery("team-a", "flow-a", payload())
    target = store.path("team-a", "flows", "flow-a")
    before = store.read(target)
    module().get_recovery_binding("team-a", "flow-a")
    assert store.read(target) == before
    with pytest.raises(store.Conflict):
        module().revoke_recovery("team-a", "flow-a", {"expectedRevision": 1})
    assert module().revoke_recovery("team-a", "flow-a", {"expectedRevision": 2})["status"] == "unbound"
    assert store.read(target)["failureRecovery"] is None


def source_run(bound_env, **updates):
    module().bind_recovery("team-a", "flow-a", payload(**updates))
    return tick(service.start_run("team-a", "flow-a", {
        "expectedRevision": 2, "idempotencyKey": "bound-run", "values": {"subject": "原任务"}}), 2)


def fail_source(bound_env, run):
    bound_env.sessions.finish(run["attempts"][-1], status="failed_runtime", content="")
    run = tick(run)
    from core.web.services.team_workflow.generic.recovery import reconcile_recovery
    reconcile_recovery("team-a", run["id"])
    return service.get_run("team-a", run["id"])


def test_revocation_fences_child_admission_before_recovery_scan(bound_env):
    run = fail_source(bound_env, source_run(bound_env, maxAttempts=1))
    child_id = run["recovery"]["repairRunId"]
    before = len(bound_env.sessions.submitted)
    module().revoke_recovery("team-a", "flow-a", {"expectedRevision": 2})
    service.reconcile_run("team-a", child_id)
    assert len(bound_env.sessions.submitted) == before
    assert service.get_run("team-a", child_id)["status"] == "stopped"
    assert service.get_run("team-a", run["id"])["recovery"]["status"] == "blocked"


def test_policy_expansion_cannot_be_inherited_by_a_queued_source_replay(bound_env):
    run = fail_source(bound_env, source_run(bound_env))
    assert run["recovery"]["status"] == "retrying"
    before = len(bound_env.sessions.submitted)
    bound_env.agents["agent-a"]["toolPolicy"]["allowedTools"].append("write_file_tool")
    service.reconcile_run("team-a", run["id"])
    run = service.get_run("team-a", run["id"])
    assert run["status"] == "stopped"
    assert run["recovery"]["reason"] == "recovery_role_policy_changed"
    assert len(bound_env.sessions.submitted) == before


def test_expired_binding_is_readable_but_cannot_start_or_dispatch(bound_env, monkeypatch):
    result = module().bind_recovery("team-a", "flow-a", payload())
    monkeypatch.setattr(module(), "utc_now", lambda: datetime.fromisoformat(result["expiresAt"]) + timedelta(seconds=1))
    assert module().get_recovery_binding("team-a", "flow-a")["status"] == "expired"
    with pytest.raises(store.Conflict):
        service.start_run("team-a", "flow-a", {
            "expectedRevision": 2, "idempotencyKey": "expired", "values": {"subject": "原任务"}})
    assert service.list_runs("team-a")["runs"] == []


def test_recipe_changes_require_rebinding_and_do_not_mutate_existing_authorization(bound_env):
    result = module().bind_recovery("team-a", "flow-a", payload())
    service.save_flow("team-a", "repair-flow", {
        "flow": repair_definition(name="变更后的修复方案"), "expectedRevision": 1})
    assert module().get_recovery_binding("team-a", "flow-a")["reason"] == "recovery_recipe_changed"
    with pytest.raises(store.Conflict):
        service.start_run("team-a", "flow-a", {
            "expectedRevision": 2, "idempotencyKey": "changed", "values": {"subject": "原任务"}})
    assert store.read(store.path("team-a", "flows", "flow-a"))["failureRecovery"]["bindingId"] == result["bindingId"]


@pytest.mark.parametrize("previous_resolved", [False, True])
def test_revoked_failure_retains_correct_issue_and_count_without_dispatch(bound_env, previous_resolved):
    run = source_run(bound_env, maxAttempts=1)
    bound_env.sessions.finish(run["attempts"][-1], status="failed_runtime", content="")
    run = tick(run)
    if previous_resolved:
        target = store.path("team-a", "runs", run["id"])
        record = store.read(target)
        from core.web.services.team_workflow.generic.models import RecoveryState
        record["recovery"] = RecoveryState(issueId="issue-previous", nodeId="previous", status="resolved").model_dump()
        store.write(target, record)
    module().revoke_recovery("team-a", "flow-a", {"expectedRevision": 2})
    from core.web.services.team_workflow.generic.recovery import reconcile_recovery
    reconcile_recovery("team-a", run["id"])
    record = store.read(store.path("team-a", "runs", run["id"]))
    state = record["recovery"]
    assert state["status"] == "blocked"
    assert state["nodeId"] == "work" and state["failureCount"] == 1
    assert state["sourceAttemptKey"] == run["attempts"][-1]["key"]
    assert state["issueId"] == "issue-" + service.digest(["team-a", run["id"], "work"])[:40]
    assert state["repairRunId"] == ""
    reconcile_recovery("team-a", run["id"])
    assert store.read(store.path("team-a", "runs", run["id"])) == record


@pytest.mark.parametrize("repair_child", [False, True])
def test_revoke_serializes_with_inflight_automatic_admission(bound_env, monkeypatch, repair_child):
    run = fail_source(bound_env, source_run(bound_env, maxAttempts=1 if repair_child else 3))
    run_id = run["recovery"]["repairRunId"] if repair_child else run["id"]
    entered, release, revoke_waiting, revoked = (threading.Event() for _ in range(4))
    original_create, original_lock = native.create, store.locked
    source_path = store.path("team-a", "flows", "flow-a")
    def slow_create(*args):
        entered.set()
        assert release.wait(4)
        return original_create(*args)
    @contextmanager
    def observed_lock(path):
        if path == source_path and threading.current_thread().name.startswith("revoker"):
            revoke_waiting.set()
        with original_lock(path):
            yield
    def revoke():
        result = module().revoke_recovery("team-a", "flow-a", {"expectedRevision": 2})
        revoked.set()
        return result
    monkeypatch.setattr(native, "create", slow_create)
    monkeypatch.setattr(store, "locked", observed_lock)
    with ThreadPoolExecutor(max_workers=1) as admissions, ThreadPoolExecutor(max_workers=1, thread_name_prefix="revoker") as revocations:
        admission = admissions.submit(service.reconcile_run, "team-a", run_id)
        assert entered.wait(4)
        revocation = revocations.submit(revoke)
        try:
            assert revoke_waiting.wait(4)
            assert not revoked.wait(0.1)
        finally:
            release.set()
        admission.result(timeout=4)
        assert revocation.result(timeout=4)["status"] == "unbound"
    submitted = len(bound_env.sessions.submitted)
    service.reconcile_run("team-a", run_id)
    assert len(bound_env.sessions.submitted) == submitted
    assert service.get_run("team-a", run_id)["status"] == "stopped"


@pytest.mark.parametrize("change", ["expiry", "policy"])
def test_authorization_is_rechecked_after_native_session_creation(bound_env, monkeypatch, change):
    run = fail_source(bound_env, source_run(bound_env, maxAttempts=1))
    original_create = native.create
    def changed_create(*args):
        result = original_create(*args)
        if change == "expiry":
            expiry = run["flow"]["failureRecovery"]["expiresAt"]
            monkeypatch.setattr(module(), "utc_now", lambda: datetime.fromisoformat(expiry) + timedelta(seconds=1))
        else:
            bound_env.agents["director"]["toolPolicy"]["allowedTools"].append("write_file_tool")
        return result
    monkeypatch.setattr(native, "create", changed_create)
    before = len(bound_env.sessions.submitted)
    service.reconcile_run("team-a", run["recovery"]["repairRunId"])
    assert len(bound_env.sessions.submitted) == before


def test_session_temporary_grant_cannot_expand_automatic_dispatch(bound_env, monkeypatch):
    run = fail_source(bound_env, source_run(bound_env, maxAttempts=1))
    from core.web.services import agent_tool_governance_service as grants
    monkeypatch.setattr(grants, "temporary_granted_tools_for_agent", lambda *args, **kwargs: ["write_file_tool"])
    before = len(bound_env.sessions.submitted)
    service.reconcile_run("team-a", run["recovery"]["repairRunId"])
    child = service.get_run("team-a", run["recovery"]["repairRunId"])
    assert len(bound_env.sessions.submitted) == before
    assert "recovery_session_policy_changed" in child["error"]


def test_flow_runs_are_filtered_before_team_wide_limit(bound_env):
    run = source_run(bound_env)
    target = store.path("team-a", "runs", run["id"])
    record = store.read(target)
    import os
    os.utime(target, (1, 1))
    for index in range(101):
        other = copy.deepcopy(record)
        other["id"], other["flow"]["id"] = f"other-{index}", "unrelated-flow"
        store.write(store.path("team-a", "runs", other["id"]), other)
    assert run["id"] not in {row["id"] for row in service.list_runs("team-a")["runs"]}
    assert [row["id"] for row in service.list_runs("team-a", flow_id="flow-a", limit=20)["runs"]] == [run["id"]]


def test_structured_business_failure_is_retryable_after_native_success(bound_env, monkeypatch):
    source = definition()
    source["steps"][1]["resultContract"] = "outcome_v1"
    service.save_flow("team-a", "flow-a", {"flow": source, "expectedRevision": 1})
    module().bind_recovery("team-a", "flow-a", payload(expectedRevision=2))
    monkeypatch.setattr(native, "recovery", native_recovery)
    monkeypatch.setattr(native, "_detail", lambda attempt: {})
    run = tick(service.start_run("team-a", "flow-a", {
        "expectedRevision": 3, "idempotencyKey": "business-result", "values": {"subject": "检查实际结果"}}), 2)
    bound_env.sessions.finish(run["attempts"][-1], content=json.dumps({
        "taskStatus": "failed", "problemCode": "fixture_missing", "evidenceRefs": ["file:fixture"]}))
    run = tick(run)
    assert run["status"] == "failed"
    assert run["attempts"][-1]["failureOrigin"] == "result_contract"
    assert native_recovery(run["attempts"][-1]) == "safe_new_attempt"
    from core.web.services.team_workflow.generic.recovery import reconcile_recovery
    reconcile_recovery("team-a", run["id"])
    run = tick(service.get_run("team-a", run["id"]))
    assert len(run["attempts"]) == 2
    bound_env.sessions.finish(run["attempts"][-1], content=json.dumps({
        "taskStatus": "succeeded", "evidenceRefs": ["file:fixture-verified"]}))
    run = tick(run)
    reconcile_recovery("team-a", run["id"])
    assert service.get_run("team-a", run["id"])["recovery"]["status"] == "resolved"


def test_binding_route_and_typescript_contract_share_field_names(bound_env):
    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient
    from core.web.routes.generic_team_workflows import register_generic_team_workflow_routes
    from pathlib import Path

    app, router = FastAPI(), APIRouter()
    register_generic_team_workflow_routes(router)
    app.include_router(router)
    endpoint = "/teams/team-a/workflows/flow-a/recovery-binding"
    with TestClient(app) as client:
        assert client.get(endpoint).json()["status"] == "unbound"
        assert client.put(endpoint, json=payload(acknowledgeAutomaticRecovery=False)).status_code == 422
        response = client.put(endpoint, json=payload())
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        ts = (Path(__file__).resolve().parents[1] / "web/src/api/types/genericTeamWorkflow.ts").read_text(encoding="utf-8")
        for key in data:
            assert key in ts, f"Binding DTO is missing {key}"
        assert client.post(endpoint + "/revoke", json={"expectedRevision": 1}).status_code == 409
        assert client.post(endpoint + "/revoke", json={"expectedRevision": 2}).json()["status"] == "unbound"
