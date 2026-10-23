"""Assistant Team actions use temp state and native workflow/Session seams."""
from __future__ import annotations

import copy
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from core.web.services.team_workflow.generic import native, runtime, service, store
from core.web.services.team_workflow.generic.models import Flow, SaveFlow, StartRun
from tools import pa_team_actions as actions


@pytest.fixture
def env(tmp_path, monkeypatch):
    teams, templates, turns, submitted = {}, [], {}, []
    actor = {"agentId": "personal-assistant", "sessionId": "assistant-session"}
    monkeypatch.setattr(actions.directory, "current_agent_runtime", lambda: actor.copy())
    monkeypatch.setattr(actions.directory, "_workspace_path", lambda *parts: tmp_path.joinpath(*parts))
    monkeypatch.setattr(store.team_store, "_teams_root", lambda: tmp_path / "teams")
    monkeypatch.setattr(store.team_store, "_load_index", lambda: {"teams": list(teams.values())})
    monkeypatch.setattr(service, "_wake", lambda: None)
    monkeypatch.setattr(runtime, "_ADMITTING", True)
    monkeypatch.setattr(runtime, "_STOP", threading.Event())

    def template(template_id, **kwargs):
        # A durable pending record must precede the first native side effect.
        records = list((tmp_path / "personal-assistant-actions" / "teams").glob("*.json"))
        assert any(json.loads(item.read_text())["status"] == "pending" for item in records)
        templates.append((template_id, kwargs))
        team_id = "team-" + str(len(templates))
        agents = [{"agentId": "agent-" + role, "metadata": {"teamTemplateRole": role},
                   "toolPolicy": {"allowedTools": ["agent_message_tool"]},
                   "llmBindings": {"dialogue": {"modelId": "unchanged"}}}
                  for role, _, _ in reversed(actions._ROLES)]
        team = {"teamId": team_id, "teamSource": kwargs["team_source"], "status": "active",
                "members": [{"agentId": agent["agentId"]} for agent in agents]}
        teams[team_id] = copy.deepcopy(team)
        return {"team": team, "createdAgents": agents}

    def owner(team_id, agent_id):
        assert agent_id in {item["agentId"] for item in store.team(team_id)["members"]}

    def create(attempt, run, step):
        return "session-" + step["id"]

    def submit(attempt, prompt):
        submitted.append((copy.deepcopy(attempt), prompt))
        turns[attempt["key"]] = {"turnId": "turn-" + str(len(submitted)), "terminal": False,
                                  "terminalStatus": "", "assistantTurnId": "", "assistantText": ""}
        return turns[attempt["key"]]["turnId"]

    monkeypatch.setattr(actions.team_template_service, "instantiate_team_template", template)
    monkeypatch.setattr(native, "validate_owner", owner)
    monkeypatch.setattr(native, "create", create)
    monkeypatch.setattr(native, "submit", submit)
    monkeypatch.setattr(native, "snapshot", lambda attempt: copy.deepcopy(turns[attempt["key"]]))
    monkeypatch.setattr(native, "lookup_turn", lambda attempt: turns.get(attempt["key"], {}).get("turnId", ""))
    return SimpleNamespace(tmp_path=tmp_path, teams=teams, templates=templates, actor=actor,
                           turns=turns, submitted=submitted, template=template)


def launch(**kwargs):
    return actions.team_run("项目团队", "完成有依据的实现方案", "request-1", **kwargs)


def records(env):
    return [json.loads(path.read_text()) for path in
            (env.tmp_path / "personal-assistant-actions" / "teams").glob("*.json")]


def test_native_contracts_role_mapping_and_no_permission_changes(env, monkeypatch):
    created = []

    def materialize(*args, **kwargs):
        result = env.template(*args, **kwargs)
        created.append((result, copy.deepcopy(result)))
        return result

    monkeypatch.setattr(actions.team_template_service, "instantiate_team_template", materialize)
    result = launch()
    assert result["ok"] and result["status"] == "running"
    run = service.get_run(result["teamId"], result["runId"])
    flow = Flow.model_validate(run["flow"], strict=True)
    SaveFlow.model_validate({"flow": flow.model_dump(), "expectedRevision": 0}, strict=True)
    StartRun.model_validate({"values": run["values"], "expectedRevision": 1,
                             "idempotencyKey": "request-1"}, strict=True)
    assert [(field.id, field.kind, field.required) for field in flow.fields] == [("goal", "text", True)]
    assert [step.id for step in flow.steps] == [role for role, _, _ in actions._ROLES]
    assert [step.owner for step in flow.steps] == ["agent-" + role for role, _, _ in actions._ROLES]
    assert all(step.kind == "agent" and step.resultContract == "text" for step in flow.steps)
    assert flow.failureRecovery is None and "_localIntegration" not in run
    assert created[0][0] == created[0][1]
    assert set(env.templates[0][1]) == {"name", "team_source"}
    assert "goal" not in json.dumps(records(env))


def test_native_execution_follows_all_four_roles_and_passes_previous_results(env):
    result = launch()
    for index, (role, _, _) in enumerate(actions._ROLES):
        service.reconcile_run(result["teamId"], result["runId"])
        attempt, prompt = env.submitted[-1]
        assert attempt["agentId"] == "agent-" + role
        assert "完成有依据的实现方案" in prompt
        if index:
            assert "角色结果" + str(index - 1) in prompt
        turn = env.turns[attempt["key"]]
        turn.update(terminal=True, terminalStatus="completed", assistantTurnId=turn["turnId"],
                    assistantText="角色结果" + str(index))
        service.reconcile_run(result["teamId"], result["runId"])
    service.reconcile_run(result["teamId"], result["runId"])
    summary = actions.team_run_status(result["teamId"], result["runId"])
    assert summary["status"] == "completed" and summary["current"] == 4
    assert summary["stepCount"] == 4 and summary["attemptCount"] == 4
    assert all(item["sessionId"] and item["turnId"] and item["status"] == "completed"
               for item in summary["attempts"])
    assert summary["result"]["content"] == "角色结果3"
    assert summary["result"]["untrustedContent"] is True
    assert "角色结果0" not in json.dumps(summary, ensure_ascii=False)
    assert "角色结果1" not in json.dumps(summary, ensure_ascii=False)
    assert "角色结果2" not in json.dumps(summary, ensure_ascii=False)


def test_replay_and_payload_conflict(env):
    result = launch()
    replay = launch()
    assert replay["runId"] == result["runId"] and replay["reused"]
    conflict = actions.team_run("项目团队", "不同目标", "request-1")
    assert conflict["error"] == "idempotency_conflict"
    assert len(env.templates) == 1
    env.actor["sessionId"] = "other-session"
    assert launch()["teamId"] != result["teamId"]
    assert len(env.templates) == 2


def test_concurrent_requests_materialize_once(env):
    barrier = threading.Barrier(6)

    def invoke(_):
        barrier.wait()
        return launch()

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(invoke, range(6)))
    assert all(item["ok"] for item in results)
    assert len({item["runId"] for item in results}) == 1
    assert len(env.templates) == 1
    assert len(service.list_runs(results[0]["teamId"])["runs"]) == 1


@pytest.mark.parametrize("patch", [{"name": " "}, {"goal": " "}, {"goal": "x" * 12001},
                                   {"request_id": "../bad"}, {"request_id": 123},
                                   {"template_id": "research"}])
def test_invalid_input_never_materializes(env, patch):
    payload = {"name": "项目团队", "goal": "目标", "request_id": "request-1", **patch}
    result = actions.team_run(**payload)
    assert not result["ok"] and result["error"] == "invalid_input"
    assert not env.templates and not records(env)


def test_missing_runtime_identity_fails_before_effects(env):
    env.actor.clear()
    assert launch()["error"] == "invalid_input"
    assert not env.templates


def test_uncertain_template_failure_never_rematerializes_or_leaks_secret(env, monkeypatch):
    calls = []

    def fail(*args, **kwargs):
        calls.append(1)
        raise RuntimeError("secret-token and complete prompt")

    monkeypatch.setattr(actions.team_template_service, "instantiate_team_template", fail)
    first, replay = launch(), launch()
    assert first["error"] == "operation_unconfirmed"
    assert replay["error"] == "materialization_unconfirmed"
    assert calls == [1]
    assert "secret-token" not in json.dumps([first, replay, records(env)])


@pytest.mark.parametrize("bad_role", ["missing", "duplicate", "nonmember", "canonical_nonmember"])
def test_invalid_template_owners_preserve_team_without_starting(env, monkeypatch, bad_role):
    def broken(*args, **kwargs):
        result = env.template(*args, **kwargs)
        if bad_role == "missing":
            result["createdAgents"].pop()
        elif bad_role == "duplicate":
            result["createdAgents"].append(copy.deepcopy(result["createdAgents"][0]))
        elif bad_role == "nonmember":
            result["team"]["members"].pop()
        else:
            env.teams[result["team"]["teamId"]]["members"].pop()
        return result

    monkeypatch.setattr(actions.team_template_service, "instantiate_team_template", broken)
    first, replay = launch(), launch()
    assert first["teamId"] == replay["teamId"] == "team-1"
    assert first["flowId"] and replay["error"] == "materialization_unconfirmed"
    assert not service.list_runs("team-1")["runs"] and len(env.templates) == 1


def test_save_failure_keeps_created_objects_and_blocks_template_retry(env, monkeypatch):
    monkeypatch.setattr(service, "save_flow", lambda *args: (_ for _ in ()).throw(RuntimeError("SECRET")))
    first, replay = launch(), launch()
    assert first["teamId"] == "team-1" and first["flowId"]
    assert replay["error"] == "materialization_unconfirmed"
    assert len(env.templates) == 1 and "team-1" in env.teams
    assert "SECRET" not in json.dumps([first, replay, records(env)])


def test_saved_flow_recovers_start_with_same_native_key(env, monkeypatch):
    original = service.start_run
    payloads = []

    def transient(team_id, flow_id, payload):
        payloads.append(copy.deepcopy(payload))
        if len(payloads) == 1:
            raise RuntimeError("secret")
        return original(team_id, flow_id, payload)

    monkeypatch.setattr(service, "start_run", transient)
    first, replay = launch(), launch()
    assert first["error"] == "start_unconfirmed" and first["teamId"] == "team-1"
    assert replay["ok"] and replay["reused"]
    assert payloads[0] == payloads[1]
    assert set(payloads[0]) == {"values", "expectedRevision", "idempotencyKey"}
    assert len(env.templates) == 1


def test_lost_flow_save_acknowledgement_recovers_by_exact_readback(env, monkeypatch):
    original = service.save_flow
    saves = []

    def lost(*args):
        saves.append(args)
        original(*args)
        raise RuntimeError("save committed but acknowledgement lost")

    monkeypatch.setattr(service, "save_flow", lost)
    first, replay = launch(), launch()
    assert first["error"] == "operation_unconfirmed"
    assert first["teamId"] == replay["teamId"] and replay["ok"]
    assert len(saves) == len(env.templates) == 1


def test_unconfirmed_saved_flow_with_different_definition_cannot_start(env, monkeypatch):
    original = service.save_flow

    def changed(team_id, flow_id, payload):
        payload = copy.deepcopy(payload)
        payload["flow"]["steps"][0]["instruction"] = "different task"
        original(team_id, flow_id, payload)
        raise RuntimeError("lost acknowledgement")

    monkeypatch.setattr(service, "save_flow", changed)
    first, replay = launch(), launch()
    assert first["teamId"] == "team-1"
    assert replay["error"] == "materialization_unconfirmed"
    assert len(env.templates) == 1 and service.list_runs("team-1")["runs"] == []


def test_start_conflict_readback_cannot_claim_another_input_run(env, monkeypatch):
    original = service.start_run

    def different_input(team_id, flow_id, payload):
        changed = {**payload, "values": {"goal": "unrelated goal"}}
        original(team_id, flow_id, changed)
        return original(team_id, flow_id, payload)

    monkeypatch.setattr(service, "start_run", different_input)
    first, replay = launch(), launch()
    assert first["error"] == replay["error"] == "start_unconfirmed"
    assert len(env.templates) == 1 and len(service.list_runs("team-1")["runs"]) == 1


def test_lost_start_acknowledgement_reads_back_native_run(env, monkeypatch):
    original = service.start_run

    def lost(*args):
        original(*args)
        raise RuntimeError("lost acknowledgement secret")

    monkeypatch.setattr(service, "start_run", lost)
    first, replay = launch(), launch()
    assert first["ok"] and replay["ok"] and first["runId"] == replay["runId"]
    assert len(service.list_runs("team-1")["runs"]) == len(env.templates) == 1


def test_status_ownership_gate_precedes_any_run_read(env, monkeypatch):
    result = launch()
    calls = []
    original = service.get_run
    monkeypatch.setattr(service, "get_run", lambda *args: calls.append(args) or original(*args))
    env.actor["agentId"] = "another-assistant"
    assert actions.team_run_status(result["teamId"], result["runId"])["error"] == "not_owned"
    assert calls == []
    env.actor["agentId"] = "personal-assistant"
    env.actor["sessionId"] = "another-session"
    assert actions.team_run_status(result["teamId"], result["runId"])["ok"]
    assert len(calls) == 1


def test_status_has_no_transcript_goal_errors_or_mutations(env, monkeypatch):
    result = launch()
    before = copy.deepcopy(records(env))
    run = service.get_run(result["teamId"], result["runId"])
    run.update(error="SECRET", messages=["SECRET"], attempts=[{
        "nodeId": "node-1", "number": index, "agentId": "agent-a", "sessionId": "session-a",
        "turnId": "turn-a", "status": "completed", "key": "SECRET", "promptHash": "SECRET"}
        for index in range(25)])
    monkeypatch.setattr(service, "get_run", lambda *args: copy.deepcopy(run))
    monkeypatch.setattr(service, "reconcile_run", lambda *args: pytest.fail("status must not mutate"))
    summary = actions.team_run_status(result["teamId"], result["runId"])
    assert summary["ok"] and len(summary["attempts"]) == 20 and summary["attemptsTruncated"]
    assert summary["attemptCount"] == 25
    assert "SECRET" not in json.dumps(summary) and "goal" not in json.dumps(summary)
    assert records(env) == before
