"""Neutral Team intents use native generic admission, never a second scheduler."""
from __future__ import annotations

import copy
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from core.web.services.external_management.contracts import SCOPES
from core.web.services.external_management.service import (
    ManagementError,
    ManagementService,
    TargetIdentity,
)
from core.web.services.team_workflow.generic import native, runtime, store
from core.web.services.team_workflow.generic import service as workflows
from tests.test_configured_agent_creation import configured_env as _configured_env

configured_env = _configured_env

BINDING = {"projectId": "project", "instanceId": "instance"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    from core.web.services.team_workflow import one_shot

    teams, created, calls = {}, {}, []
    monkeypatch.setattr(store.team_store, "_teams_root", lambda: tmp_path / "teams")
    monkeypatch.setattr(store.team_store, "_load_index", lambda: {"teams": list(teams.values())})
    monkeypatch.setattr(workflows, "_wake", lambda: None)
    monkeypatch.setattr(runtime, "_ADMITTING", True)
    monkeypatch.setattr(runtime, "_STOP", threading.Event())
    monkeypatch.setattr(native, "validate_owner", lambda team_id, agent_id: None)

    class Gateway:
        failure = ""

        def recipe_fingerprint(self, template_id):
            assert template_id == "dev-team"
            return "frozen-template"

        def materialize(self, parameters, marker):
            intents = list((tmp_path / "management" / "team-requests").glob("*.json"))
            assert len(intents) == 1 and json.loads(intents[0].read_text())["phase"] == "materialization_pending"
            calls.append("materialize")
            if self.failure == "before_team":
                raise RuntimeError("partial role Agent already exists")
            agents = [{"agentId": "agent-" + role, "metadata": {"teamTemplateRole": role}}
                      for role, _, _ in one_shot._ROLES]
            team = {"teamId": "team-1", "teamSource": marker["teamSource"], "status": "active",
                    "members": [{"agentId": agent["agentId"]} for agent in agents]}
            teams["team-1"] = team
            created[marker["requestKey"]] = {"team": team, "createdAgents": agents}
            if self.failure == "materialized_ack":
                raise RuntimeError("lost materialization acknowledgement")

        def recover(self, marker, recipe_fingerprint):
            assert recipe_fingerprint == "frozen-template"
            if self.failure == "incomplete":
                return None
            return copy.deepcopy(created.get(marker["requestKey"]))

        def owns(self, team_id, marker):
            return teams.get(team_id, {}).get("teamSource") == marker["teamSource"]

    gateway = Gateway()
    identity = lambda: TargetIdentity(BINDING, "native-root")
    management = ManagementService(tmp_path / "management", identity=identity, native=None, teams=gateway)
    grant = management.bind({"client_id": "launcher", "expected_binding": BINDING,
                             "scopes": [scope for scope in SCOPES if scope not in {"agents:create:files", "teams:results:read"}]})
    args = (grant["subject_id"], grant["subject_capability"])
    payload = {"request_id": "request-1", "expected_binding": BINDING,
               "parameters": {"name": "Team", "goal": "Produce verified evidence", "template_id": "dev-team"}}
    return SimpleNamespace(service=management, gateway=gateway, args=args, payload=payload, teams=teams,
                           created=created, calls=calls, root=tmp_path, identity=identity)


def invoke(env):
    return env.service.invoke(*env.args, "team_run", env.payload)


def test_neutral_team_admission_and_restart_receipt_use_one_native_run(env):
    result = invoke(env)
    assert result["status"] == "completed" and result["verified"] and result["phase"] == "started"
    assert result["teamRun"]["status"] == "running" and result["resumeAllowed"] is False
    restarted = ManagementService(env.root / "management", identity=env.identity, native=None, teams=env.gateway)
    assert restarted.team_receipt(*env.args, "request-1")["teamRun"]["runId"] == result["teamRun"]["runId"]
    assert invoke(env)["teamRun"]["runId"] == result["teamRun"]["runId"]
    assert env.calls == ["materialize"]
    assert len(list((env.root / "teams/team-1/generic-workflows/runs").glob("*.json"))) == 1


def test_concurrent_same_intent_materializes_once(env):
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: invoke(env), range(4)))
    assert all(item["verified"] for item in results)
    assert len({item["teamRun"]["runId"] for item in results}) == 1
    assert env.calls == ["materialize"]


@pytest.mark.parametrize("failure", ["before_team", "incomplete"])
def test_partial_or_incomplete_materialization_never_rebuilds(env, failure):
    env.gateway.failure = failure
    assert invoke(env)["status"] == "unknown"
    receipt = env.service.team_receipt(*env.args, "request-1")
    assert receipt["resumeAllowed"] is False and receipt["phase"] == "materialization_pending"
    assert invoke(env)["status"] == "unknown" and env.calls == ["materialize"]


def test_materialization_ack_loss_recovers_only_known_team_and_requires_explicit_resume(env):
    env.gateway.failure = "materialized_ack"
    first = invoke(env)
    assert first["status"] == "unknown" and first["resumeAllowed"]
    receipt = env.service.team_receipt(*env.args, "request-1")
    assert receipt["phase"] == "materialized" and receipt["resumeAllowed"]
    assert not list((env.root / "teams/team-1/generic-workflows/runs").glob("*.json"))
    assert invoke(env)["verified"] and env.calls == ["materialize"]


def test_scope_binding_and_subject_are_not_run_identifiers(env):
    invoke(env)
    other = env.service.bind({"client_id": "other", "expected_binding": BINDING,
                              "scopes": [scope for scope in SCOPES if scope not in {"agents:create:files", "teams:results:read"}]})
    with pytest.raises(ManagementError, match="REQUEST_UNAVAILABLE"):
        env.service.team_receipt(other["subject_id"], other["subject_capability"], "request-1")
    env.service.identity = lambda: TargetIdentity({**BINDING, "instanceId": "different"}, "native-root")
    with pytest.raises(ManagementError, match="TARGET_BINDING_CHANGED"):
        env.service.team_receipt(*env.args, "request-1")


def test_team_schema_governance_and_no_prototype_scope_upgrade(env):
    from core.web.services.external_management.contracts import contracts
    assert contracts()["team_run"]["governed"] is True
    assert SCOPES[:14] == ("agents:read", "agents:create", "agents:update", "agents:avatar", "agents:archive",
                      "teams:run", "teams:read", "teams:directory:read", "rooms:read", "platform:describe", "sessions:read", "sessions:pin", "sessions:parameters:read", "legacy:receipts:read")
    assert {"tasks:read", "source:read"}.issubset(SCOPES)
    for injected in ({"owner": "fake"}, {"governed": True}, {"nativeApproval": True}, {"runtime": {}}, {"url": "http://local"}):
        payload = copy.deepcopy(env.payload)
        payload["parameters"].update(injected)
        with pytest.raises(ManagementError, match="INVALID_INPUT"):
            env.service.invoke(*env.args, "team_run", payload)
    grant = env.service.bind({"client_id": "prototype", "expected_binding": BINDING, "scopes": list(SCOPES[:4])})
    with pytest.raises(ManagementError, match="SCOPE_DENIED"):
        env.service.invoke(grant["subject_id"], grant["subject_capability"], "team_run", env.payload)
    with pytest.raises(ManagementError, match="SUBJECT_GRANT_CONFLICT"):
        env.service.bind({"client_id": "prototype", "expected_binding": BINDING, "scopes": list(SCOPES)})
    assert not env.calls


@pytest.mark.parametrize("committed", [False, True])
def test_flow_save_ack_loss_is_read_only_until_original_request_resumes(env, monkeypatch, committed):
    save = workflows.save_flow
    calls = []

    def fail(*args):
        calls.append("save")
        if committed:
            save(*args)
        raise RuntimeError("save acknowledgement lost")

    monkeypatch.setattr(workflows, "save_flow", fail)
    result = invoke(env)
    assert result["status"] == "unknown" and result["resumeAllowed"]
    expected = "flow_saved" if committed else "materialized"
    assert result["phase"] == expected
    original_files = {path: path.read_bytes() for path in env.root.rglob("*.json")}
    assert env.service.team_receipt(*env.args, "request-1")["phase"] == expected
    assert original_files == {path: path.read_bytes() for path in env.root.rglob("*.json")}
    assert calls == ["save"]
    monkeypatch.setattr(workflows, "save_flow", save)
    assert invoke(env)["verified"] and env.calls == ["materialize"]


@pytest.mark.parametrize("committed", [False, True])
def test_start_ack_loss_reuses_exact_native_idempotency_and_goal(env, monkeypatch, committed):
    start = workflows.start_run
    keys = []

    def fail(team_id, flow_id, payload):
        keys.append(copy.deepcopy(payload))
        if committed:
            start(team_id, flow_id, payload)
        raise RuntimeError("start acknowledgement lost")

    monkeypatch.setattr(workflows, "start_run", fail)
    first = invoke(env)
    assert first["verified"] is committed
    before = list(keys)
    receipt = env.service.team_receipt(*env.args, "request-1")
    assert receipt["verified"] is committed and keys == before
    monkeypatch.setattr(workflows, "start_run", start)
    result = invoke(env)
    assert result["verified"] and env.calls == ["materialize"]
    assert keys == [{"values": {"goal": env.payload["parameters"]["goal"]}, "expectedRevision": 1, "idempotencyKey": "request-1"}]
    assert result["teamRun"]["runId"] == "run-" + workflows.digest([result["teamRun"]["flowId"], "request-1"])[:40]


@pytest.mark.parametrize("tamper", ["flow", "goal", "native_fingerprint", "source"])
def test_tampered_native_evidence_is_never_verified_or_resumable(env, tamper):
    result = invoke(env)
    team_id, run_id = result["teamRun"]["teamId"], result["teamRun"]["runId"]
    if tamper == "source":
        env.teams[team_id]["teamSource"] = "another-subject"
    elif tamper == "flow":
        target = store.path(team_id, "runs", run_id)
        record = store.read(target)
        record["flow"]["steps"][0]["instruction"] = "Different frozen instruction"
        store.write(target, record)
    else:
        target = store.path(team_id, "runs", run_id)
        record = store.read(target)
        if tamper == "goal":
            record["values"]["goal"] = "Different goal"
        else:
            record["_createFingerprint"] = "different key"
        store.write(target, record)
    for receipt in (env.service.team_receipt(*env.args, "request-1"), invoke(env)):
        assert receipt["status"] == "unknown" and not receipt["verified"] and not receipt["resumeAllowed"]
    assert env.calls == ["materialize"]


def test_accepted_run_uses_frozen_flow_even_after_normal_current_config_edits(env):
    result = invoke(env)
    view = result["teamRun"]
    target = store.path(view["teamId"], "flows", view["flowId"])
    record = store.read(target)
    record["revision"] = 2
    record["steps"][0]["instruction"] = "Ordinary later editor change"
    store.write(target, record)
    env.gateway.failure = "incomplete"  # Today's role config does not replace accepted Session snapshots.
    assert env.service.team_receipt(*env.args, "request-1")["teamRun"]["runId"] == view["runId"]
    assert invoke(env)["verified"] and env.calls == ["materialize"]


def test_request_conflict_cannot_materialize_new_agents(env):
    invoke(env)
    env.payload["parameters"]["goal"] = "Changed parameters"
    with pytest.raises(ManagementError, match="IDEMPOTENCY_CONFLICT"):
        invoke(env)
    assert env.calls == ["materialize"]


def test_conflicting_saved_flow_before_start_never_overwrites_or_starts(env, monkeypatch):
    env.gateway.failure = "materialized_ack"
    first = invoke(env)
    from core.web.services.team_workflow import one_shot
    from core.web.services.team_workflow.generic.models import SaveFlow
    flow = one_shot._flow(first["teamRun"]["flowId"], next(iter(env.created.values())))
    flow.steps[0].instruction = "A conflicting definition"
    workflows.save_flow("team-1", flow.id, SaveFlow(flow=flow, expectedRevision=0).model_dump(exclude_none=True))
    monkeypatch.setattr(workflows, "start_run", lambda *_args: pytest.fail("conflicting flow must not start"))
    monkeypatch.setattr(workflows, "save_flow", lambda *_args: pytest.fail("conflicting flow must not overwrite"))
    for response in (env.service.team_receipt(*env.args, "request-1"), invoke(env)):
        assert response["status"] == "unknown" and not response["resumeAllowed"]
    assert env.calls == ["materialize"]


@pytest.mark.parametrize("phase", ["materialized", "flow_saved", "started"])
def test_ledger_ack_loss_keeps_original_intent_and_native_identity(env, monkeypatch, phase):
    from core.web.services.team_workflow import one_shot
    write = env.service.store.__class__.write
    atomic = one_shot.atomic_write_json
    failed = False

    def lose_store_ack(owner, path, record):
        nonlocal failed
        write(owner, path, record)
        actual = "flow_saved" if record.get("flowSaved") else "materialized" if record.get("teamId") else "pending"
        if phase == actual and not failed:
            failed = True
            raise OSError("lost ledger acknowledgement")

    def lose_started_ack(path, record, **kwargs):
        nonlocal failed
        if record.get("runId") and phase == "started" and not failed:
            failed = True
            raise OSError("native accepted, before local ledger commit")
        atomic(path, record, **kwargs)

    monkeypatch.setattr(env.service.store.__class__, "write", lose_store_ack)
    monkeypatch.setattr(one_shot, "atomic_write_json", lose_started_ack)
    first = invoke(env)
    assert failed
    receipt = env.service.team_receipt(*env.args, "request-1")
    assert receipt["verified"] is (phase == "started")
    assert first["status"] in {"completed", "unknown"}
    assert invoke(env)["verified"] and env.calls == ["materialize"]
    assert len(list((env.root / "teams/team-1/generic-workflows/runs").glob("*.json"))) == 1


def test_recipe_change_before_start_denies_resume_without_new_materialization(env, monkeypatch):
    env.gateway.failure = "materialized_ack"
    assert invoke(env)["resumeAllowed"]
    from core.web.services.team_workflow import one_shot
    monkeypatch.setattr(one_shot, "recipe_fingerprint", lambda: "updated-source-recipe")
    assert not env.service.team_receipt(*env.args, "request-1")["resumeAllowed"]
    assert not invoke(env)["resumeAllowed"] and env.calls == ["materialize"]


def test_receipt_bounds_pointers_and_never_reads_session_content(env, monkeypatch):
    result = invoke(env)
    target = store.path(result["teamRun"]["teamId"], "runs", result["teamRun"]["runId"])
    record = store.read(target)
    attempt = {"key": "attempt-key", "nodeId": "dev_team_planner", "number": 1, "agentId": "agent-dev_team_planner",
               "sessionId": "native-session", "turnId": "native-turn", "status": "completed",
               "failureCode": "PRIVATE ERROR"}
    from core.web.services.team_workflow.generic.models import Attempt
    attempt = Attempt.model_validate(attempt).model_dump()
    record["attempts"] = [dict(attempt, number=index + 1) for index in range(30)]
    record["messages"] = ["PRIVATE TRANSCRIPT"]
    store.write(target, record)
    monkeypatch.setattr(workflows, "artifacts", lambda *_: pytest.fail("Session artifact content read is forbidden"))
    receipt = env.service.team_receipt(*env.args, "request-1")
    assert receipt["verified"] and len(receipt["teamRun"]["attempts"]) == 20
    assert len(receipt["teamRun"]["artifactRefs"]) == 20 and receipt["teamRun"]["attemptsTruncated"]
    rendered = json.dumps(receipt)
    assert "PRIVATE" not in rendered and "goal" not in rendered and "instruction" not in rendered


def test_real_template_recovery_requires_first_record_markers_and_compiled_policy(configured_env, monkeypatch):
    from core.web.services.external_management.team_native import NativeTeamGateway
    from core.web.services.team import team_store
    env = configured_env
    gateway = NativeTeamGateway(env["root"])
    marker = {"subjectType": "operator", "subjectId": "ops-" + "a" * 32, "binding": BINDING,
              "requestKey": "request-key", "requestFingerprint": "request-fingerprint", "teamSource": "external_team:test"}
    recipe = gateway.recipe_fingerprint("dev-team")
    save = env["directory"].save_state
    first_seen = set()

    def observe(state):
        for row in state.get("agents", []):
            if row.get("createdBy") == "team_template" and row["agentId"] not in first_seen:
                first_seen.add(row["agentId"])
                assert row["metadata"]["teamTemplateInstantiation"] == {**marker, "roleKey": row["roleKey"]}
        return save(state)

    monkeypatch.setattr(env["directory"], "save_state", observe)
    gateway.materialize({"name": "Marked Team", "template_id": "dev-team"}, marker)
    recovered = gateway.recover(marker, recipe)
    assert recovered is not None and len(first_seen) == 4
    assert gateway.owns(recovered["team"]["teamId"], marker)
    compiled = gateway.agents.compiled

    def wide(*args):
        config = copy.deepcopy(compiled(*args))
        config["toolPolicy"]["allowedTools"].append("unapproved-wide-tool")
        return config

    monkeypatch.setattr(gateway.agents, "compiled", wide)
    assert gateway.recover(marker, recipe) is None
    monkeypatch.setattr(gateway.agents, "compiled", compiled)
    canvas_path = team_store._team_canvas_path(recovered["team"]["teamId"])
    canvas = team_store._read_json(canvas_path)
    team_store._write_json(canvas_path, {**canvas, "edges": []})
    assert gateway.recover(marker, recipe) is None
    team_store._write_json(canvas_path, canvas)
    before = {path: path.read_bytes() for path in env["root"].rglob("*.json")}
    assert gateway.recover(marker, recipe) is not None
    assert before == {path: path.read_bytes() for path in env["root"].rglob("*.json")}
    # A canonical second source match is ambiguous, even with four valid actors.
    state = team_store._load_index()
    duplicate = copy.deepcopy(state["teams"][0])
    duplicate["teamId"] = "another-team"
    state["teams"].append(duplicate)
    team_store._save_index(state)
    assert gateway.recover(marker, recipe) is None


def test_real_partial_template_never_reenters_native_agent_creation(configured_env, monkeypatch):
    from core.web.services import agent_operation_service as operations
    from core.web.services.external_management.native import NativeAgentGateway
    env = configured_env
    management = ManagementService(env["root"] / "management", identity=lambda: TargetIdentity(BINDING, "canonical"),
                                   native=NativeAgentGateway(env["root"]))
    grant = management.bind({"client_id": "launcher", "expected_binding": BINDING,
                             "scopes": [scope for scope in SCOPES if scope not in {"agents:create:files", "teams:results:read"}]})
    args = grant["subject_id"], grant["subject_capability"]
    payload = {"request_id": "partial", "expected_binding": BINDING, "parameters": {"name": "Partial", "goal": "No model started"}}
    create = operations.create_configured_agent_with_session
    calls = []

    def fail(**kwargs):
        calls.append("role")
        create(**kwargs)
        raise RuntimeError("First role created, before Team exists")

    monkeypatch.setattr(operations, "create_configured_agent_with_session", fail)
    for _ in range(2):
        result = management.invoke(*args, "team_run", payload)
        assert result["status"] == "unknown" and not result["resumeAllowed"]
    assert calls == ["role"]
    marked = [row for row in env["directory"].load_state()["agents"]
              if (row.get("metadata") or {}).get("teamTemplateInstantiation")]
    assert len(marked) == 1
    assert management.team_receipt(*args, "partial")["phase"] == "materialization_pending"


def test_http_operator_capability_binding_and_closed_team_receipt(env, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
    from core.web.routes import launcher_assistant_management as route
    from core.web.services.external_management.contracts import ReceiptResponse
    monkeypatch.setattr(route, "_SERVICE", env.service)
    app = FastAPI()
    app.include_router(route.router, prefix="/api")
    prefix = "/api/v1/launcher-assistant-management"
    with TestClient(app) as client:
        credentials = {route.SUBJECT_HEADER: env.args[0], route.CAPABILITY_HEADER: env.args[1]}
        assert client.post(prefix + "/actions/team_run", headers=credentials, json=env.payload).status_code == 403
        headers = {**credentials, CONTROL_TOKEN_HEADER: get_control_token()}
        assert client.post(prefix + "/actions/team_run", headers={**headers, route.CAPABILITY_HEADER: "bad"}, json=env.payload).status_code == 403
        wrong = copy.deepcopy(env.payload)
        wrong["expected_binding"]["projectId"] = "another"
        assert client.post(prefix + "/actions/team_run", headers=headers, json=wrong).status_code == 409
        assert not env.calls
        response = client.post(prefix + "/actions/team_run", headers=headers, json=env.payload)
        assert response.status_code == 200, response.text
        assert ReceiptResponse.model_validate(response.json()).verified
        for suffix in ("/team-runs/requests/request-1", "/actions/team_run/requests/request-1"):
            assert client.get(prefix + suffix, headers=headers).json()["teamRun"]["runId"] == response.json()["teamRun"]["runId"]
        assert client.get(prefix + "/team-runs/requests/request-1", headers=credentials).status_code == 403
    assert env.calls == ["materialize"]
