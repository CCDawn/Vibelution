"""Generic workflows use temp Team storage and a native Session seam only."""
from __future__ import annotations

import copy
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from core.web.services.team_workflow.generic import native, runtime, service, store
from core.web.services.team_workflow.generic.models import Flow


def test_delayed_lifespan_begin_cannot_reopen_a_retired_owner(monkeypatch):
    called = []
    monkeypatch.setattr(runtime, "_EXECUTOR", SimpleNamespace(begin=lambda: called.append("begin") or {"opened": True}))
    monkeypatch.setattr(runtime, "_ADMITTING", False)
    stop = threading.Event()
    stop.set()
    assert runtime.begin_generic_workflow_lifecycle(should_stop=stop.is_set) == {
        "opened": False, "skipped": "lifespan_stopping",
    }
    assert called == []
    assert runtime._ADMITTING is False


class NativeSessions:
    def __init__(self):
        self.sessions = {}
        self.turns = {}
        self.submitted = []
        self.stops = []
        self.auto_stop = True

    def create(self, attempt, run, step):
        return self.sessions.setdefault(attempt["key"], "session-" + str(len(self.sessions) + 1))

    def submit(self, attempt, prompt):
        if attempt["key"] not in self.turns:
            self.submitted.append((attempt["key"], prompt))
            self.turns[attempt["key"]] = {"turnId": "turn-" + str(len(self.turns) + 1), "terminal": False,
                                           "terminalStatus": "", "assistantTurnId": "", "assistantText": ""}
        return self.turns[attempt["key"]]["turnId"]

    def snapshot(self, attempt):
        return copy.deepcopy(self.turns[attempt["key"]])

    def finish(self, attempt, status="completed", content="原生最终结果"):
        self.turns[attempt["key"]].update(terminal=True, terminalStatus=status,
                                         assistantTurnId=attempt["turnId"], assistantText=content)

    def stop(self, attempt):
        self.stops.append((attempt["sessionId"], attempt["turnId"]))
        if self.auto_stop:
            self.finish(attempt, status="stopped", content="部分结果")


@pytest.fixture
def env(tmp_path, monkeypatch):
    teams = {"team-a": {"teamId": "team-a", "status": "active", "members": [{"agentId": "agent-a"}]},
             "team-b": {"teamId": "team-b", "status": "active", "members": []}}
    monkeypatch.setattr(store.team_store, "_teams_root", lambda: tmp_path / "teams")
    monkeypatch.setattr(store.team_store, "_load_index", lambda: {"teams": list(teams.values())})
    monkeypatch.setattr(service, "_wake", lambda: None)
    monkeypatch.setattr(runtime, "_ADMITTING", True)
    monkeypatch.setattr(runtime, "_STOP", threading.Event())
    def owner(team_id, agent_id):
        if agent_id not in {item["agentId"] for item in store.team(team_id)["members"]}:
            raise store.WorkflowError("负责人不可用")
    monkeypatch.setattr(native, "validate_owner", owner)
    sessions = NativeSessions()
    for name in ("create", "submit", "snapshot", "stop"):
        monkeypatch.setattr(native, name, getattr(sessions, name))
    monkeypatch.setattr(native, "lookup_turn", lambda attempt: sessions.turns.get(attempt["key"], {}).get("turnId", ""))
    def recovery(attempt):
        result = sessions.turns.get(attempt["key"], {})
        return "safe_new_attempt" if result.get("terminal") and result.get("terminalStatus") != "completed" else "resume_same_identity"
    monkeypatch.setattr(native, "recovery", recovery)
    return SimpleNamespace(teams=teams, sessions=sessions, tmp_path=tmp_path)


def definition(**overrides):
    flow = {"id": "flow-a", "name": "用户流程", "description": "", "revision": 0, "updatedAt": "",
            "fields": [{"id": "subject", "label": "主题", "kind": "text", "required": True, "options": []},
                       {"id": "mode", "label": "模式", "kind": "select", "required": False, "options": ["甲", "乙"]}],
            "steps": [{"id": "input", "label": "输入", "kind": "input", "owner": "用户", "instruction": ""},
                      {"id": "work", "label": "处理", "kind": "agent", "owner": "agent-a", "instruction": "整理结果"},
                      {"id": "check", "label": "确认", "kind": "human", "owner": "用户", "instruction": "检查"},
                      {"id": "out", "label": "输出", "kind": "output", "owner": "", "instruction": ""}]}
    flow.update(overrides)
    return flow


def save(flow=None, expected=0, team="team-a"):
    return service.save_flow(team, "flow-a", {"flow": flow or definition(), "expectedRevision": expected})


def start(key="request-a", values=None):
    return service.start_run("team-a", "flow-a", {"values": values if values is not None else {"subject": "问题"},
                                                "expectedRevision": 1, "idempotencyKey": key})


def tick(run, count=1):
    for _ in range(count):
        service.reconcile_run("team-a", run["id"])
    return service.get_run("team-a", run["id"])


def command(run, action):
    return service.command_run("team-a", run["id"], {"action": action, "expectedRevision": run["revision"]})


def test_frozen_flow_revision_and_idempotent_start(env):
    save()
    run = start()
    assert start()["id"] == run["id"]
    save(definition(name="改名"), expected=1)
    assert start()["flow"]["name"] == "用户流程"
    assert service.get_run("team-a", run["id"])["flow"]["revision"] == 1
    with pytest.raises(store.Conflict):
        save(expected=1)
    with pytest.raises(store.Conflict):
        start(values={"subject": "不同输入"})
    with pytest.raises(store.Conflict):
        start(key="new-key")


@pytest.mark.parametrize("values", [{}, {"subject": " "}, {"subject": "x", "mode": "丙"},
                                    {"subject": "x", "unknown": "v"}, {"subject": "x" * 12001}])
def test_required_select_and_size_validation(env, values):
    save()
    with pytest.raises(store.WorkflowError):
        start(values=values)
    assert not service.list_runs("team-a")["runs"]


def test_empty_flow_has_no_business_fields_and_cannot_start(env):
    blank = save(definition(fields=[], steps=[]))
    assert blank["fields"] == blank["steps"] == []
    with pytest.raises(store.WorkflowError):
        start(values={})


@pytest.mark.parametrize("patch", [
    {"fields": [definition()["fields"][0]] * 2},
    {"steps": [definition()["steps"][0]] * 2},
    {"fields": [{"id": "x", "label": "x", "kind": "select", "options": []}]},
    {"fields": [{"id": "x", "label": "x", "kind": "select", "options": ["a", "a"]}]},
])
def test_definition_uniqueness_and_options(env, patch):
    with pytest.raises(ValidationError):
        Flow.model_validate(definition(**patch))


def test_team_and_path_isolation(env):
    save()
    run = start()
    assert service.list_flows("team-b")["flows"] == []
    with pytest.raises(store.NotFound):
        service.get_run("team-b", run["id"])
    for bad in ("../team-a", "team-a/../team-b", "team-a.", "C:\\tmp"):
        with pytest.raises(store.WorkflowError):
            service.list_flows(bad)
    with pytest.raises(store.NotFound):
        service.list_flows("unknown")


def test_native_completion_human_confirm_output_and_no_transcript_copy(env):
    save()
    run = tick(start(), 2)
    assert run["status"] == "running" and len(run["attempts"]) == 1
    attempt = run["attempts"][0]
    env.sessions.finish(attempt)
    run = tick(run, 2)
    assert run["status"] == "waiting" and run["current"] == 2
    with pytest.raises(store.Conflict):
        service.command_run("team-a", run["id"], {"action": "confirm", "expectedRevision": 1})
    projected = service.artifacts("team-a", run["id"])["artifacts"]
    assert projected[0]["content"] == "原生最终结果"
    stored = store.path("team-a", "runs", run["id"]).read_text(encoding="utf-8")
    assert "原生最终结果" not in stored
    assert tick(command(run, "confirm"), 2)["status"] == "completed"
    assert len(env.sessions.submitted) == 1


def test_failed_retry_and_revise_use_new_isolated_attempts(env):
    save()
    run = tick(start(), 2)
    env.sessions.finish(run["attempts"][-1], status="failed_runtime", content="")
    run = tick(run)
    assert run["status"] == "failed"
    run = tick(command(run, "retry"))
    assert len(run["attempts"]) == 2
    assert run["attempts"][0]["key"] != run["attempts"][1]["key"]
    assert run["attempts"][0]["sessionId"] != run["attempts"][1]["sessionId"]
    env.sessions.finish(run["attempts"][-1])
    run = tick(run, 2)
    assert run["status"] == "waiting"
    run = tick(command(run, "revise"))
    assert len(run["attempts"]) == 3 and run["current"] == 1


def test_stop_waits_for_native_terminal_and_preserves_records(env):
    save()
    run = tick(start(), 2)
    env.sessions.auto_stop = False
    run = command(run, "stop")
    assert run["status"] == "running" and run["stopRequested"]
    run = tick(run)
    assert run["status"] == "running"
    assert env.sessions.stops == [(run["attempts"][0]["sessionId"], run["attempts"][0]["turnId"])]
    env.sessions.finish(run["attempts"][0], status="stopped", content="已完成的一部分")
    run = tick(run)
    assert run["status"] == "stopped" and run["attempts"][0]["status"] == "stopped"
    assert service.artifacts("team-a", run["id"])["artifacts"][0]["content"] == "已完成的一部分"
    assert len(env.sessions.submitted) == 1


def test_stop_before_dispatch_does_not_create_session(env):
    save()
    run = command(start(), "stop")
    assert run["status"] == "stopped"
    assert not env.sessions.sessions


def test_restart_recovers_missing_submit_ack_without_duplicate(env):
    save()
    run = tick(start(), 2)
    target = store.path("team-a", "runs", run["id"])
    record = store.read(target)
    record["attempts"][0]["turnId"] = ""
    record["attempts"][0]["status"] = "dispatching"
    store.write(target, record)
    # A new owner has no in-memory run registry; it scans persisted snapshots.
    runtime.reconcile_all()
    restored = service.get_run("team-a", run["id"])
    assert restored["attempts"][0]["turnId"] == run["attempts"][0]["turnId"]
    assert len(env.sessions.submitted) == 1
    # Same uncertain dispatch must be recovered without a fresh submit on stop.
    store.write(target, record)
    restored = tick(command(service.get_run("team-a", run["id"]), "stop"))
    assert restored["status"] == "stopped" and len(env.sessions.submitted) == 1


def test_transient_submit_error_retries_same_identity(env, monkeypatch):
    save()
    original = env.sessions.submit
    def accepted_then_error(attempt, prompt):
        original(attempt, prompt)
        raise OSError("response lost")
    monkeypatch.setattr(native, "submit", accepted_then_error)
    run = tick(start(), 2)
    assert run["status"] == "failed" and not run["attempts"][0]["turnId"]
    monkeypatch.setattr(native, "submit", original)
    run = tick(command(run, "retry"))
    assert len(run["attempts"]) == 1 and len(env.sessions.submitted) == 1


def test_current_team_membership_rechecked_before_dispatch(env):
    save()
    run = start()
    env.teams["team-a"]["members"] = []
    run = tick(run, 2)
    assert run["status"] == "failed" and not env.sessions.submitted


def test_reads_never_dispatch(env):
    save()
    run = start()
    service.list_runs("team-a")
    service.get_run("team-a", run["id"])
    service.artifacts("team-a", run["id"])
    assert not env.sessions.submitted


def test_start_and_artifacts_wait_for_canonical_recovery_lifecycle(env, monkeypatch):
    save()
    existing = start()
    monkeypatch.setattr(runtime, "_ADMITTING", False)
    with pytest.raises(store.Conflict, match="尚未就绪"):
        start()
    assert service.list_runs("team-a")["runs"][0]["id"] == existing["id"]
    assert service.get_run("team-a", existing["id"])["id"] == existing["id"]
    with pytest.raises(store.Conflict, match="尚未就绪"):
        service.artifacts("team-a", existing["id"])
    assert not env.sessions.submitted


def test_output_owner_executes_and_unassigned_output_is_sink(env):
    flow = definition(fields=[], steps=[
        {"id": "write", "label": "交付文档", "kind": "output", "owner": "agent-a", "instruction": "撰写文档"},
        {"id": "deliver", "label": "直接交付", "kind": "output", "owner": "", "instruction": ""},
    ])
    save(flow)
    run = tick(start(values={}))
    assert len(env.sessions.submitted) == 1 and run["attempts"][0]["nodeId"] == "write"
    env.sessions.finish(run["attempts"][0], content="交付文档正文")
    run = tick(run, 3)
    assert run["status"] == "completed" and len(env.sessions.submitted) == 1
    assert service.artifacts("team-a", run["id"])["artifacts"][0]["content"] == "交付文档正文"


def test_output_owner_validated_and_sink_needs_no_team_agents(env):
    flow = definition(fields=[], steps=[{"id": "out", "label": "交付", "kind": "output", "owner": "other", "instruction": ""}])
    save(flow)
    with pytest.raises(store.WorkflowError):
        start(values={})
    flow["steps"][0]["owner"] = ""
    save(flow, expected=1)
    env.teams["team-a"]["members"] = []
    run = service.start_run("team-a", "flow-a", {"values": {}, "expectedRevision": 2, "idempotencyKey": "sink"})
    assert tick(run, 2)["status"] == "completed"
    assert not env.sessions.submitted


def test_agent_to_output_handoff_reads_canonical_result_into_new_session(env):
    flow = definition()
    flow["steps"][3]["owner"] = "agent-a"
    flow["steps"][3]["instruction"] = "根据前序结果撰写交付文档"
    save(flow)
    run = tick(start(), 2)
    env.sessions.finish(run["attempts"][0], content="上一Agent的研究结果")
    run = tick(run, 2)
    run = tick(command(run, "confirm"))
    assert len(run["attempts"]) == 2
    assert run["attempts"][0]["sessionId"] != run["attempts"][1]["sessionId"]
    assert "上一Agent的研究结果" in env.sessions.submitted[-1][1]
    assert "上一Agent的研究结果" not in store.path("team-a", "runs", run["id"]).read_text(encoding="utf-8")


def test_restart_recovers_native_create_ack_and_wrong_result_does_not_complete(env):
    save()
    run = tick(start(), 2)
    target = store.path("team-a", "runs", run["id"])
    record = store.read(target)
    record["attempts"][0].update(sessionId="", turnId="", status="dispatching")
    store.write(target, record)
    run = tick(run)
    assert len(env.sessions.sessions) == len(env.sessions.submitted) == 1
    env.sessions.finish(run["attempts"][0])
    env.sessions.turns[run["attempts"][0]["key"]]["assistantTurnId"] = "unrelated-turn"
    run = tick(run)
    assert run["status"] == "failed"
    assert service.artifacts("team-a", run["id"])["artifacts"] == []


def test_runtime_recovers_valid_run_after_corrupt_record(env):
    save()
    run = start()
    bad = store.path("team-a", "runs", "broken")
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("not-json", encoding="utf-8")
    runtime.reconcile_all()
    assert service.get_run("team-a", run["id"])["current"] == 1


def test_http_contracts_and_errors(env, monkeypatch):
    from core.web.routes.generic_team_workflows import register_generic_team_workflow_routes
    app = FastAPI()
    router = APIRouter()
    register_generic_team_workflow_routes(router)
    app.include_router(router)
    with TestClient(app) as client:
        base = "/teams/team-a"
        assert client.get(f"{base}/workflows").json() == {"schemaVersion": 1, "teamId": "team-a", "flows": []}
        assert client.put(f"{base}/workflows/flow-a", json={"flow": definition(), "expectedRevision": 0}).status_code == 200
        assert client.put(f"{base}/workflows/flow-a", json={"flow": definition(), "expectedRevision": 0}).status_code == 409
        assert client.post(f"{base}/workflows/flow-a/runs", json={"values": {}, "expectedRevision": 1, "idempotencyKey": "x"}).status_code == 422
        response = client.post(f"{base}/workflows/flow-a/runs", json={"values": {"subject": "x"}, "expectedRevision": 1, "idempotencyKey": "http"})
        assert response.status_code == 200
        run = response.json()
        assert "_createFingerprint" not in run
        assert client.get(f"{base}/workflow-runs").json()["runs"][0]["id"] == run["id"]
        assert client.get(f"/teams/team-b/workflow-runs/{run['id']}").status_code == 404
        assert client.get(f"{base}/workflow-runs/{run['id']}/artifacts").json() == {"artifacts": []}
        assert client.post(f"{base}/workflow-runs/{run['id']}/commands", json={"action": "stop", "expectedRevision": run["revision"]}).json()["status"] == "stopped"
        assert client.post(f"{base}/workflow-runs/{run['id']}/commands", json={"action": "confirm", "expectedRevision": run["revision"]}).status_code == 409
        monkeypatch.setattr(runtime, "_ADMITTING", False)
        assert client.get(f"{base}/workflow-runs/{run['id']}/artifacts").status_code == 409
        assert client.get(f"{base}/workflow-runs/{run['id']}").status_code == 200


def test_runtime_owned_shutdown_and_reopen(env, monkeypatch):
    calls = threading.Event()
    monkeypatch.setattr(runtime, "reconcile_all", calls.set)
    assert runtime.begin_generic_workflow_lifecycle()["opened"]
    assert calls.wait(2)
    assert runtime.shutdown_generic_workflow_executor(deadline=time.monotonic() + 3)["closed"]
    with pytest.raises(store.Conflict):
        runtime.ensure_admission()
    calls.clear()
    assert runtime.begin_generic_workflow_lifecycle()["opened"]
    assert calls.wait(2)
    assert runtime.shutdown_generic_workflow_executor(deadline=time.monotonic() + 3)["closed"]


@pytest.fixture
def native_adapter(monkeypatch):
    # Only replace the native boundary. Never submit to a model in these tests.
    from core.web.services import session_service as sessions
    from core.web.services.session import journal_bridge
    attempt = {"key": "gw-test-attempt", "agentId": "agent-a", "sessionId": "session-a", "turnId": "turn-a"}
    detail = {"id": "session-a", "agentId": "agent-a", "lastTurnTerminalTurnId": "turn-a"}
    state = {"turnId": "turn-a", "terminal": True, "terminalStatus": "completed",
             "completionSource": "turn_journal", "assistantTurnId": "turn-a", "assistantText": "答案"}
    correlation = [SimpleNamespace(turn_id="turn-a", payload={"source": "generic_team_workflow"})]
    resumes = {}
    monkeypatch.setattr(sessions, "get_session_detail", lambda session_id, **kwargs: detail)
    monkeypatch.setattr(sessions, "get_session_turn_completion_snapshot", lambda session_id, turn_id: state.copy())
    monkeypatch.setattr(journal_bridge, "load_session_conversation_events_by_correlation",
                        lambda *args, **kwargs: correlation if kwargs["correlation_id"] == "gw-test-attempt"
                        else resumes.get(kwargs["correlation_id"], []))
    return SimpleNamespace(sessions=sessions, attempt=attempt, detail=detail, state=state, correlation=correlation, resumes=resumes)


def test_native_adapter_requires_own_agent_turn_and_submission(native_adapter):
    ctx = native_adapter
    assert native.snapshot(ctx.attempt)["terminal"]
    ctx.detail["agentId"] = "other-agent"
    with pytest.raises(store.WorkflowError):
        native.snapshot(ctx.attempt)
    ctx.detail["agentId"] = "agent-a"
    ctx.correlation[0].turn_id = "other-turn"
    with pytest.raises(store.WorkflowError):
        native.snapshot(ctx.attempt)
    ctx.correlation[0].turn_id = "turn-a"
    ctx.state.update(completionSource="last_turn_status", terminalStatus="ready")
    ctx.detail["lastTurnTerminalTurnId"] = "other-turn"
    assert native.snapshot(ctx.attempt)["terminal"] is False
    ctx.state.update(completionSource="turn_journal", turnId="other-turn")
    assert native.snapshot(ctx.attempt)["terminal"] is False


def test_native_create_submit_and_stop_contract(native_adapter, monkeypatch):
    ctx = native_adapter
    calls = {}
    def create(**kwargs):
        calls["create"] = kwargs
        return {"id": "session-a", "agentId": "agent-a"}
    def submit(session_id, prompt, **kwargs):
        calls["submit"] = (session_id, prompt, kwargs)
        return {"turnId": "turn-a"}
    monkeypatch.setattr(ctx.sessions, "create_chat_session", create)
    monkeypatch.setattr(ctx.sessions, "submit_session_message", submit)
    monkeypatch.setattr(ctx.sessions, "request_stop_session_turn", lambda session_id, **kwargs: calls.update(stop=(session_id, kwargs)))
    run = {"flow": {"name": "流程"}}
    assert native.create(ctx.attempt, run, {"label": "步骤"}) == "session-a"
    assert calls["create"]["agent_id"] == "agent-a"
    assert calls["create"]["activate"] is False
    assert calls["create"]["conversation_index_kind"] == "hidden"
    assert calls["create"]["idempotency_key"] == ctx.attempt["key"]
    assert native.submit(ctx.attempt, "prompt") == "turn-a"
    assert calls["submit"][2]["client_submission_id"] == ctx.attempt["key"]
    assert calls["submit"][2]["message_source"] == "generic_team_workflow"
    native.stop(ctx.attempt)
    assert calls["stop"] == ("session-a", {"expected_turn_id": "turn-a", "fast_ack": True})


def test_stop_serializes_with_inflight_dispatch(env, monkeypatch):
    save()
    run = tick(start())  # input consumed, dispatch is the next worker operation
    entered, release = threading.Event(), threading.Event()
    original = env.sessions.submit
    def blocking_submit(attempt, prompt):
        entered.set()
        assert release.wait(3)
        return original(attempt, prompt)
    monkeypatch.setattr(native, "submit", blocking_submit)
    worker = threading.Thread(target=service.reconcile_run, args=("team-a", run["id"]))
    worker.start()
    assert entered.wait(2)
    result = {}
    # A stop waits behind the dispatch fence and then uses its own exact Turn.
    def stop_command():
        current = service.get_run("team-a", run["id"])
        try:
            result["run"] = command(current, "stop")
        except store.Conflict:
            result["conflict"] = True
    stopper = threading.Thread(target=stop_command)
    stopper.start()
    release.set()
    worker.join(3)
    stopper.join(3)
    assert not worker.is_alive() and not stopper.is_alive()
    current = service.get_run("team-a", run["id"])
    if result.get("conflict"):
        current = command(current, "stop")
    else:
        current = result["run"]
    assert tick(current)["status"] == "stopped"
    assert len(env.sessions.submitted) == 1
    assert env.sessions.stops[0][1] == current["attempts"][0]["turnId"]


def test_confirmed_missing_session_allows_fresh_attempt_and_stop(env, monkeypatch):
    save()
    run = tick(start(), 2)
    original_snapshot = native.snapshot
    first_key = run["attempts"][0]["key"]
    def missing(attempt):
        if attempt["key"] == first_key:
            raise native.SessionUnavailable("原会话不存在且没有运行轮次", safe_new_attempt=True)
        return original_snapshot(attempt)
    monkeypatch.setattr(native, "snapshot", missing)
    monkeypatch.setattr(native, "recovery", lambda attempt: "safe_new_attempt")
    run = tick(run)
    assert run["status"] == "failed" and run["attempts"][0]["status"] == "failed"
    run = tick(command(run, "retry"))
    assert len(run["attempts"]) == 2 and len(env.sessions.submitted) == 2
    run = tick(command(run, "stop"))
    assert run["status"] == "stopped"


def test_unknown_identity_blocks_retry_and_reports_stop_failure(env, monkeypatch):
    save()
    run = tick(start(), 2)
    def unavailable(attempt):
        raise native.SessionUnavailable("负责人变化，旧轮次状态尚未确认")
    monkeypatch.setattr(native, "snapshot", unavailable)
    monkeypatch.setattr(native, "recovery", lambda attempt: "unknown_blocked")
    run = tick(run)
    assert run["status"] == "failed"
    with pytest.raises(store.Conflict, match="尚未确认"):
        command(run, "retry")
    run = tick(command(run, "stop"))
    assert run["status"] == "failed" and run["stopRequested"]
    assert "尚未确认" in run["error"]
    assert len(env.sessions.submitted) == 1
    # An operator confirms and closes the original canonical turn externally.
    def gone_and_inactive(attempt):
        raise native.SessionUnavailable("旧轮次已结束", safe_new_attempt=True)
    monkeypatch.setattr(native, "snapshot", gone_and_inactive)
    run = tick(command(run, "stop"))
    assert run["status"] == "stopped"


def test_worker_follows_canonical_resume_turn_for_completion_and_stop(env):
    save()
    run = tick(start(), 2)
    attempt = run["attempts"][0]
    origin = attempt["turnId"]
    env.sessions.turns[attempt["key"]].update(turnId="resumed-turn", originTurnId=origin,
                                            recoveryTurnIds=["resumed-turn"])
    run = tick(run)
    assert run["attempts"][0]["originTurnId"] == origin
    assert run["attempts"][0]["turnId"] == "resumed-turn"
    run = tick(command(run, "stop"))
    assert run["status"] == "stopped"
    assert env.sessions.stops == [(attempt["sessionId"], "resumed-turn")]
    assert service.artifacts("team-a", run["id"])["artifacts"][0]["turnId"] == "resumed-turn"
    assert len(env.sessions.submitted) == 1


def test_retry_failed_origin_does_not_duplicate_running_native_resume(env):
    save()
    run = tick(start(), 2)
    attempt = run["attempts"][0]
    env.sessions.finish(attempt, status="interrupted", content="")
    run = tick(run)
    assert run["status"] == "failed"
    # Startup recovery is canonical and creates another Turn in the same Session.
    env.sessions.turns[attempt["key"]].update(turnId="resume-active", terminal=False, terminalStatus="",
                                            originTurnId=attempt["turnId"], recoveryTurnIds=["resume-active"])
    run = tick(command(run, "retry"))
    assert run["attempts"][0]["turnId"] == "resume-active"
    assert len(run["attempts"]) == len(env.sessions.submitted) == 1
    env.sessions.finish(run["attempts"][0], content="恢复后的结果")
    assert tick(run, 2)["status"] == "waiting"


def test_native_resume_chain_is_verified_and_stop_targets_last_child(native_adapter, monkeypatch):
    ctx = native_adapter
    def resumed(parent, child):
        return SimpleNamespace(turn_id=child, payload={"source": "hot_restart_resume", "metadata": {
            "kind": "hot_restart_resume", "recoverySource": "startup_sweep", "recoveredTurnId": parent}})
    ctx.resumes["resume:turn-a"] = [resumed("turn-a", "resume-1")]
    ctx.resumes["resume:resume-1"] = [resumed("resume-1", "resume-2")]
    states = {
        "turn-a": {**ctx.state, "terminalStatus": "interrupted", "assistantText": ""},
        "resume-2": {"turnId": "resume-2", "terminal": False, "terminalStatus": "", "completionSource": "running",
                     "assistantTurnId": "", "assistantText": "", "isRunning": True},
    }
    monkeypatch.setattr(ctx.sessions, "get_session_turn_completion_snapshot", lambda session_id, turn_id: states[turn_id].copy())
    result = native.snapshot(ctx.attempt)
    assert result["turnId"] == "resume-2" and result["terminal"] is False
    assert result["originTurnId"] == "turn-a" and result["recoveryTurnIds"] == ["resume-1", "resume-2"]
    assert native.recovery(ctx.attempt) == "resume_same_identity"
    stopped = []
    monkeypatch.setattr(ctx.sessions, "request_stop_session_turn", lambda session_id, **kwargs: stopped.append(kwargs["expected_turn_id"]))
    native.stop(ctx.attempt)
    assert stopped == ["resume-2"]
    # A current owner mismatch is never called safe while the recovered Turn runs.
    ctx.detail["agentId"] = "other-agent"
    assert native.recovery(ctx.attempt) == "unknown_blocked"
    states["resume-2"].update(terminal=True, terminalStatus="stopped", completionSource="turn_journal")
    assert native.recovery(ctx.attempt) == "safe_new_attempt"
    ctx.detail["agentId"] = "agent-a"
    ctx.resumes["resume:resume-1"][0].payload["metadata"]["recoveredTurnId"] = "unrelated-turn"
    with pytest.raises(native.SessionUnavailable, match="恢复链"):
        native.snapshot(ctx.attempt)


def test_native_missing_requires_no_running_controller(native_adapter, monkeypatch):
    ctx = native_adapter
    monkeypatch.setattr(ctx.sessions, "get_session_detail", lambda *args, **kwargs: None)
    ctx.state.update(terminal=False, completionSource="missing_conversation", isRunning=True)
    assert native.recovery(ctx.attempt) == "unknown_blocked"
    ctx.state["isRunning"] = False
    assert native.recovery(ctx.attempt) == "safe_new_attempt"
