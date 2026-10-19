"""Recovery delegates scope, never operator identity or a fabricated effect."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from core.web.services.team_workflow.generic import binding, service, store
from core.web.services.team_workflow.generic.models import StartRun
from tests.test_generic_team_workflows import env, tick  # noqa: F401
from tests.test_generic_workflow_binding import bound_env, payload  # noqa: F401
from tests.test_generic_workflow_recovery import fail, scan


def scope(**updates):
    return {"acknowledge": True, "allowedFiles": ["core/example.py"],
            "teamId": "team-a", "validForSeconds": 600, **updates}


def test_start_contract_accepts_only_explicit_exact_file_delegation():
    request = {"values": {}, "expectedRevision": 1, "idempotencyKey": "request"}
    assert StartRun.model_validate({**request, "localIntegration": scope()}).localIntegration is not None
    for invalid in (scope(acknowledge=False), scope(allowedFiles=["core/*"]), scope(validForSeconds=3601)):
        with pytest.raises(ValueError):
            StartRun.model_validate({**request, "localIntegration": invalid})


@pytest.fixture
def bridge(bound_env, monkeypatch):
    from core.web.services.team_workflow.generic import code_repair

    binding.bind_recovery("team-a", "flow-a", payload(maxAttempts=1))
    grants, children, calls = [], {}, []

    def issue(record, request):
        grants.append(deepcopy(request))
        return {"authorizationId": "trusted-grant", "operatorId": "operator", "runId": record["id"],
            "allowedFiles": request["allowedFiles"], "teamId": "team-a", "revoked": False,
            "requestDigest": code_repair.request_digest(request),
            "expiresAt": (datetime.now(timezone.utc) + timedelta(seconds=600)).isoformat(),
            "principals": {role: {"agentId": agent} for role, agent in (
                ("observer", "director"), ("executor", "developer"), ("reviewer", "reviewer"))}}

    class Orchestrator:
        def start_recovery(self, request, *, source, run_id):
            if run_id not in children:
                calls.append((deepcopy(request), deepcopy(source), run_id))
                children[run_id] = {"runId": run_id, "status": "running", "phase": "planning",
                                    "_recoverySource": deepcopy(source)}
            return deepcopy(children[run_id])

        def get(self, run_id):
            return deepcopy(children.get(run_id))

        def get_recovery(self, run_id, *, source):
            child = self.get(run_id)
            if child is not None and child["_recoverySource"] != source:
                raise ValueError("source mismatch")
            return child

        def cancel_recovery(self, run_id, *, source):
            calls.append(("cancel", run_id))
            if run_id in children:
                children[run_id]["status"] = "stopped"

    monkeypatch.setattr(code_repair, "_issue_scope", issue)
    monkeypatch.setattr(code_repair, "_orchestrator", lambda: Orchestrator())
    request = {"expectedRevision": 2, "values": {"subject": "SECRET original user input"},
               "idempotencyKey": "scoped-source", "localIntegration": scope()}
    run = tick(service.start_run("team-a", "flow-a", request), 2)
    return bound_env, run, request, children, calls, grants


def test_grant_is_private_and_idempotency_cannot_change_its_scope(bridge):
    _env, run, request, _children, _calls, grants = bridge
    assert "_codeRepairAuthorization" not in run
    assert store.read(store.path("team-a", "runs", run["id"]))["_codeRepairAuthorization"]["operatorId"] == "operator"
    assert service.start_run("team-a", "flow-a", request)["id"] == run["id"]
    assert len(grants) == 1
    with pytest.raises(store.Conflict):
        service.start_run("team-a", "flow-a", {**request, "localIntegration": scope(allowedFiles=["core/other.py"])})


def test_exhausted_failure_queues_one_candidate_and_never_native_developer(bridge):
    env, run, _request, children, calls, _grants = bridge
    run = scan(fail(env, run), 4)
    assert run["recovery"]["codeRepairRunId"]
    assert len(calls) == len(children) == 1
    assert len(env.sessions.submitted) == 1
    assert len(service.list_runs("team-a")["runs"]) == 1
    assert "SECRET" not in calls[0][0]["goal"]
    assert calls[0][0]["localIntegration"]["allowedFiles"] == ["core/example.py"]


def test_lost_queue_response_recovers_same_child_identity(bridge, monkeypatch):
    from core.web.services.team_workflow.generic import code_repair
    env, run, _request, children, calls, _grants = bridge
    original = code_repair._orchestrator()

    class Lost:
        get = original.get
        def start_recovery(self, *args, **kwargs):
            original.start_recovery(*args, **kwargs)
            raise OSError("lost response")
    monkeypatch.setattr(code_repair, "_orchestrator", lambda: Lost())
    run = scan(fail(env, run))
    monkeypatch.setattr(code_repair, "_orchestrator", lambda: original)
    run = scan(run, 3)
    assert len(calls) == len(children) == 1
    assert run["recovery"]["status"] == "repairing"


@pytest.mark.parametrize("status", ["completed", "partial", "running"])
def test_integration_fact_waits_for_deployment_and_never_claims_effect(bridge, status):
    env, run, _request, children, _calls, _grants = bridge
    run = scan(fail(env, run), 2)
    child = children[run["recovery"]["codeRepairRunId"]]
    sha = "a" * 40
    child.update(status=status, phase="cleanup_pending", candidate={"headCommit": sha},
                 independentReview={"candidateCommit": sha, "reviewerAgentId": "reviewer"},
                 integration={"status": "committed", "mechanism": "git_merge_ff", "commitSha": sha})
    run = scan(run)
    assert run["recovery"]["status"] == "awaiting_deployment"
    assert f"git:{sha}" in run["recovery"]["evidenceRefs"]
    assert run["status"] == "failed" and len(env.sessions.submitted) == 1


def test_revoked_binding_cancels_exact_code_child(bridge):
    env, run, _request, children, calls, _grants = bridge
    run = scan(fail(env, run), 2)
    child_id = run["recovery"]["codeRepairRunId"]
    binding.revoke_recovery("team-a", "flow-a", {"expectedRevision": 2})
    run = scan(run)
    assert run["recovery"]["status"] == "blocked"
    assert children[child_id]["status"] == "stopped"
    assert ("cancel", child_id) in calls


@pytest.fixture
def real_child(bridge, monkeypatch):
    from core.runtime_manager.work_run_store import WorkRunStore
    from core.web.services.self_evolution_local_integration import AuthorizedLocalIntegration
    from core.web.services.self_evolution_autonomous_loop_service import AutonomousLoopHooks, SelfEvolutionAutonomousLoopService
    from core.web.services.team_workflow.research_runtime.operator_authorization import server_operator_scope
    from core.web.services.team_workflow.generic import code_repair

    env, run, request, _children, _calls, _grants = bridge
    agents = {agent_id: {"agentId": agent_id, "status": "active", "permissionPreset": "request_approval",
                         "resolvedToolPolicy": {"policyId": f"policy-{agent_id}", "allowedTools": ["grep_search_tool"]}}
              for agent_id in ("director", "developer", "reviewer")}
    work_runs = WorkRunStore(root=env.tmp_path / "real-workruns")
    adapter = AuthorizedLocalIntegration(store=work_runs, project_root=env.tmp_path,
        load_bindings=lambda: {role: {"agentId": agent} for role, agent in (
            ("observer", "director"), ("executor", "developer"), ("reviewer", "reviewer"))},
        get_agent=lambda key: deepcopy(agents.get(key)), get_team=lambda key: deepcopy(env.teams.get(key)))
    target = store.path("team-a", "runs", run["id"])
    record = store.read(target)
    with server_operator_scope("trusted-http-operator", roles=("operator",)):
        grant = adapter.authorize({"runId": run["id"], "request": {"localIntegration": request["localIntegration"]}})
    record["_codeRepairAuthorization"] = grant
    store.write(target, record)
    # Queue only the durable parent intent, without dispatching fake WorkRuns.
    run = scan(fail(env, run))
    record = store.read(target)
    unused = lambda context: {}
    child_service = SelfEvolutionAutonomousLoopService(store=work_runs,
        hooks=AutonomousLoopHooks(observe=unused, plan=unused, evolve=unused, integrate=unused,
                                 cleanup=unused, authorize=adapter.authorize, review=unused,
                                 check_authorization=adapter.check))
    child_request = {"goal": "Repair by native evidence refs", "localIntegration": request["localIntegration"]}
    source = record["_codeRepairSource"]
    child_id = record["recovery"]["codeRepairRunId"]
    child = child_service.queue_recovery(child_request, source=source, run_id=child_id)
    return env, run, adapter, child_service, child, child_request, source, grant


def test_real_authority_delegates_without_operator_and_keeps_exact_deadline(real_child):
    _env, _run, adapter, actor, child, request, source, grant = real_child
    adapter.check(child)
    delegated = child["localIntegrationAuthorization"]
    assert delegated["operatorId"] == "trusted-http-operator"
    assert delegated["expiresAt"] == grant["expiresAt"]
    assert delegated["allowedFiles"] == grant["allowedFiles"]
    assert delegated["runId"] == child["runId"] != grant["runId"]
    assert actor.queue_recovery(request, source=source, run_id=child["runId"]) == child
    with pytest.raises(ValueError):
        actor.queue_recovery({**request, "localIntegration": scope(validForSeconds=700)},
                             source=source, run_id=child["runId"])


@pytest.mark.parametrize("change", ["stop", "revoke", "expiry", "source_move", "scope"])
def test_real_child_fences_changes_to_its_parent_authorization(real_child, change):
    from core.web.services.self_evolution_local_integration import RUN_KIND
    _env, run, adapter, _actor, child, _request, source, _grant = real_child
    target = store.path("team-a", "runs", run["id"])
    parent = store.read(target)
    if change == "stop":
        parent["stopRequested"] = True
    elif change == "revoke":
        binding.revoke_recovery("team-a", "flow-a", {"expectedRevision": 2})
    elif change == "expiry":
        parent["_codeRepairAuthorization"]["expiresAt"] = "2020-01-01T00:00:00+00:00"
    elif change == "source_move":
        parent["attempts"][-1]["key"] = "new-native-attempt"
    else:
        child["request"]["localIntegration"]["allowedFiles"] = ["core/other.py"]
        adapter.store.persist_snapshot(RUN_KIND, child, active_run_id=child["runId"])
    store.write(target, parent)
    with pytest.raises(ValueError):
        adapter.check(child)


def test_exact_child_cancel_does_not_retire_other_evolution_runs(real_child):
    _env, _run, _adapter, actor, child, _request, source, _grant = real_child
    with pytest.raises(ValueError):
        actor.cancel_recovery(child["runId"], source={**source, "issueId": "wrong-issue"})
    assert actor.cancel_recovery(child["runId"], source=source)["status"] == "stopped"
    assert actor.queue({"goal": "unrelated manual candidate"})["status"] == "queued"


def test_code_repair_authorization_cannot_be_forged_through_http_headers(bound_env, monkeypatch):
    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient
    from core.web.routes.generic_team_workflows import register_generic_team_workflow_routes
    from core.web import control

    monkeypatch.setattr(control, "validate_control_request", lambda _request: "invalid token")
    router = APIRouter()
    register_generic_team_workflow_routes(router)
    app = FastAPI()
    app.include_router(router)
    response = TestClient(app).post("/teams/team-a/workflows/flow-a/runs", json={
        "values": {}, "expectedRevision": 1, "idempotencyKey": "forged", "localIntegration": scope()},
        headers={"X-Vibelution-Operator-Id": "operator", "X-Vibelution-Operator-Roles": "operator"})
    assert response.status_code == 403
    assert not service.list_runs("team-a")["runs"]


def test_start_cannot_issue_root_authorization_without_trusted_operator(bound_env, monkeypatch):
    from core.web.services import self_evolution_local_integration as local
    binding.bind_recovery("team-a", "flow-a", payload())
    monkeypatch.setattr(local, "current_server_operator", lambda: None)
    with pytest.raises(PermissionError):
        service.start_run("team-a", "flow-a", {"values": {"subject": "request"}, "expectedRevision": 2,
            "idempotencyKey": "no-operator", "localIntegration": scope()})
    assert not service.list_runs("team-a")["runs"]


def test_candidate_busy_then_timeout_without_child_does_not_permanently_block_retry(bridge, monkeypatch):
    from core.web.services.self_evolution_autonomous_loop_service import AutonomousLoopConflictError
    from core.web.services.team_workflow.generic import code_repair
    env, run, _request, children, _calls, _grants = bridge
    actor = code_repair._orchestrator()
    def busy(*_args, **_kwargs):
        raise AutonomousLoopConflictError("candidate busy")
    monkeypatch.setattr(actor, "start_recovery", busy)
    monkeypatch.setattr(code_repair, "_orchestrator", lambda: actor)
    run = scan(fail(env, run), 2)
    assert run["recovery"]["reason"] == "code_repair_candidate_busy" and not children
    target = store.path("team-a", "runs", run["id"])
    parent = store.read(target)
    parent["_recoveryQueuedAt"] = "2020-01-01T00:00:00+00:00"
    store.write(target, parent)
    run = scan(run)
    assert run["recovery"]["reason"] == "repair_timeout"
    run = service.command_run("team-a", run["id"], {"action": "retry", "expectedRevision": run["revision"]})
    assert tick(run)["status"] == "running"


def test_unreadable_child_snapshot_is_not_treated_as_absent(real_child):
    from core.web.services.self_evolution_local_integration import RUN_KIND
    _env, _run, adapter, actor, child, request, source, _grant = real_child
    path = adapter.store.runs_dir(RUN_KIND) / f"{child['runId']}.json"
    path.write_text("{invalid", encoding="utf-8")
    with pytest.raises(ValueError):
        actor.get_recovery(child["runId"], source=source)
    with pytest.raises(ValueError):
        actor.queue_recovery(request, source=source, run_id=child["runId"])
    assert not path.exists()


def test_deployment_confirmation_runs_only_reviewer_then_source_still_must_succeed(bridge):
    import json
    env, run, _request, children, _calls, _grants = bridge
    run = scan(fail(env, run), 2)
    sha = "a" * 40
    children[run["recovery"]["codeRepairRunId"]].update(status="completed", candidate={"headCommit": sha},
        independentReview={"candidateCommit": sha, "reviewerAgentId": "reviewer"},
        integration={"status": "committed", "mechanism": "git_merge_ff", "commitSha": sha})
    run = scan(run)
    run = service.command_run("team-a", run["id"], {"action": "confirm_deployment",
        "expectedRevision": run["revision"], "evidenceRef": "deployment:user-confirmed"})
    run = scan(run)
    child = service.get_run("team-a", run["recovery"]["repairRunId"])
    assert [step["owner"] for step in child["flow"]["steps"]] == ["reviewer"]
    child = tick(child)
    env.sessions.finish(child["attempts"][-1], content=json.dumps({"verdict": "passed", "effectVerified": True,
        "deploymentRequired": False, "evidenceRefs": ["runtime:checked-effect"]}))
    tick(child, 2)
    run = scan(run)
    assert run["recovery"]["status"] == "replaying"
    assert run["status"] == "running"
    run = tick(run)
    env.sessions.finish(run["attempts"][-1])
    run = scan(tick(run))
    assert run["recovery"]["status"] == "resolved"


@pytest.mark.parametrize("phase", ["integrate", "cleanup"])
def test_cancel_during_atomic_hook_preserves_completed_side_effects(tmp_path, phase):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from tests.test_self_evolution_autonomous_loop_service import _delegated_service, _delegated_request

    entered, release = threading.Event(), threading.Event()
    def integrate(context):
        if phase == "integrate":
            entered.set()
            assert release.wait(5)
        return {"status": "committed", "mechanism": "git_merge_ff", "baseCommit": context["candidate"]["baseCommit"],
                "commitSha": context["candidate"]["headCommit"], "candidateVariantId": context["candidate"]["variantId"],
                "changedFiles": [item["path"] for item in context["candidate"]["changedFiles"]],
                "rollbackManifestPath": "manifest.json", "committedAt": "2026-10-19T00:00:00+00:00"}

    def cleanup(_context):
        entered.set()
        assert release.wait(5)
        return {"status": "cleaned", "worktreeRemoved": True, "localBranchDeleted": True}

    actor, _calls = _delegated_service(tmp_path, integrate=integrate, cleanup=cleanup)
    source = {"runId": "parent", "issueId": "issue"}
    actor.queue_recovery(_delegated_request(), source=source, run_id="code-child")
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(actor.run_until_review, "code-child")
        try:
            assert entered.wait(5)
            pending = actor.cancel_recovery("code-child", source=source)
            assert pending["status"] == "running" and pending["stopRequested"]
            assert pending["_recoveryExecutionSettled"] is False
        finally:
            release.set()
        future.result(timeout=5)
    final = actor.load("code-child")
    assert final["status"] == "stopped" and final["_recoveryExecutionSettled"] is True
    assert final["integration"]["status"] == "committed"
    if phase == "cleanup":
        assert final["cleanup"]["status"] == "cleaned"


def test_cancel_does_not_allow_replay_before_developer_hook_returns(bridge, tmp_path, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from types import SimpleNamespace
    from tests.test_self_evolution_autonomous_loop_service import _delegated_service, _delegated_request
    from core.web.services.team_workflow.generic import code_repair, recovery

    env, run, _request, _children, _calls, _grants = bridge
    run = scan(fail(env, run))
    parent = store.read(store.path("team-a", "runs", run["id"]))
    child_id = parent["recovery"]["codeRepairRunId"]
    entered, release = threading.Event(), threading.Event()
    def evolve(_context):
        entered.set()
        assert release.wait(5)
        raise RuntimeError("cancelled native writer returned")
    actor, _calls = _delegated_service(tmp_path, evolve=evolve)
    actor.queue_recovery(_delegated_request(), source=parent["_codeRepairSource"], run_id=child_id)
    monkeypatch.setattr(code_repair, "_orchestrator", lambda: SimpleNamespace(get_recovery=actor.get_recovery))
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(actor.run_until_review, child_id)
        try:
            assert entered.wait(5)
            actor.cancel_recovery(child_id, source=parent["_codeRepairSource"])
            # A duplicate resume cannot certify another still-running owner.
            actor.run_until_review(child_id)
            with pytest.raises(store.Conflict, match="尚未确认结束"):
                recovery.ensure_child_settled("team-a", parent)
        finally:
            release.set()
        future.result(timeout=5)
    recovery.ensure_child_settled("team-a", parent)
