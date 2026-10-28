"""Private, single-Team result evidence; all state lives in pytest temporary roots."""
from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest

from core.chat.turn_journal import TurnJournalEvent
from core.web.services.external_management import state_snapshot, team_result
from core.web.services.team_workflow.generic import service as workflows
from tests.test_external_management_team import env, invoke


def _event(number, kind, turn, payload, *, correlation="", status="", parent=""):
    return TurnJournalEvent(schema_version=1, event_id=f"event-{number}", session_id="session-final",
        turn_id=turn, sequence=number, event_type=kind, status=status, timestamp="2026-01-01T00:00:00Z",
        source="test", payload=payload, parent_event_id=parent, visible_in_model=True, correlation_id=correlation).to_dict()


@pytest.fixture
def result_env(env, monkeypatch):
    result = invoke(env)
    grant = env.service._authorize(*env.args, "teams:read")
    intents = env.service._team_intents(grant)
    env.gateway.project_root = env.root
    env.gateway._owners = lambda: None
    env.gateway.agents = SimpleNamespace(_owners=lambda: SimpleNamespace(CONFIG_PATH=env.root / "config.toml"))
    (env.root / "config.toml").write_text("", encoding="utf-8")
    monkeypatch.setattr(state_snapshot, "read_existing_config_snapshot", lambda _: {})
    monkeypatch.setattr(state_snapshot, "existing_sandboxed_workspace_path", lambda root, *parts, **kw: env.root.joinpath(*parts))
    monkeypatch.setattr(state_snapshot.developer_sandbox, "workspace_routing_fingerprint", lambda _: ("private",))
    monkeypatch.setattr(state_snapshot.developer_sandbox, "_active_state_path", lambda _: env.root / "absent")
    (env.root / "teams").mkdir(exist_ok=True)
    team_path = env.root / "teams/teams.json"
    team_path.write_text(json.dumps({"teams": list(env.teams.values())}), encoding="utf-8")
    run_id = result["teamRun"]["runId"]
    run_path = env.root / "teams/team-1/generic-workflows/runs" / (run_id + ".json")
    run = json.loads(run_path.read_text(encoding="utf-8"))
    step = run["flow"]["steps"][-1]
    key = "gw-" + workflows.digest([str(run_path.resolve()), run_id, step["id"], 1])[:48]
    attempt = {"nodeId": step["id"], "number": 1, "agentId": step["owner"], "sessionId": "session-final",
               "turnId": "turn-1", "originTurnId": "turn-1", "recoveryTurnIds": [], "status": "completed",
               "key": key, "promptHash": ""}
    run.update(status="completed", current=len(run["flow"]["steps"]), attempts=[attempt])
    run_path.write_text(json.dumps(run), encoding="utf-8")
    row = {"sessionId": "session-final", "agentId": step["owner"]}
    runtime = {"id": "session-final", "agentId": step["owner"],
               "metadata": {"source": "generic_team_workflow", "externalTaskId": key}}
    class Repository:
        def get_session(self, session_id, **kwargs):
            assert session_id == "session-final"
            return copy.deepcopy(row)
        def get_session_runtime_state(self, session_id):
            assert session_id == "session-final"
            return copy.deepcopy(runtime)
    store = SimpleNamespace(repository=Repository())
    monkeypatch.setattr(team_result.directory_runtime, "get_open_directory_store", lambda: store)
    monkeypatch.setattr(team_result.directory_runtime, "directory_store_project_root", lambda: env.root)
    journal = env.root / "sessions/session-final/turn_journal.jsonl"
    journal.parent.mkdir(parents=True)
    events = [
        _event(1, "user_message", "turn-1", {"content": "task", "source": "generic_team_workflow"}, correlation=key),
        _event(2, "assistant_item_committed", "turn-1", {"kind": "assistant_message", "channel": "answer", "phase": "final_answer", "text": "Verified result"}, parent="event-1"),
        _event(3, "turn_completed", "turn-1", {}, status="completed", parent="event-2"),
    ]
    def save_events():
        journal.write_text("".join(json.dumps(item) + "\n" for item in events), encoding="utf-8")
    def save_run():
        run_path.write_text(json.dumps(run), encoding="utf-8")
    save_events()
    return SimpleNamespace(env=env, intents=intents, run=run, run_path=run_path, save_run=save_run, row=row,
                           runtime=runtime, events=events, save_events=save_events, journal=journal, key=key)


def read(context):
    return team_result.read_team_result(context.intents, "request-1", context.env.root)


def test_verified_bounded_answer_without_mutating_authority(result_env, monkeypatch):
    from core.web.services.team_workflow.generic import native
    c = result_env
    files = {path: path.read_bytes() for path in c.env.root.rglob("*") if path.is_file()}
    def forbidden(*args, **kwargs):
        raise AssertionError("mutating snapshot API invoked")
    monkeypatch.setattr(workflows, "artifacts", forbidden)
    monkeypatch.setattr(native, "snapshot", forbidden)
    assert read(c) == {"status": "available", "text": "Verified result", "truncated": False, "untrustedContent": True}
    assert files == {path: path.read_bytes() for path in c.env.root.rglob("*") if path.is_file()}
    c.events[1]["payload"]["text"] = "x" * 12001
    c.save_events()
    output = read(c)
    assert output["text"] == "x" * 12000 and output["truncated"] is True


def test_resume_anchored_to_original_dispatch(result_env):
    c = result_env
    c.run["attempts"][-1].update(turnId="turn-2", recoveryTurnIds=["turn-2"])
    c.save_run()
    c.events[1:] = [
        _event(2, "user_message", "turn-2", {"source": "hot_restart_resume", "content": "resume", "metadata":
            {"kind": "hot_restart_resume", "recoverySource": "startup_sweep", "recoveredTurnId": "turn-1"}}, correlation="resume:turn-1", parent="event-1"),
        _event(3, "assistant_item_committed", "turn-2", {"kind": "assistant_message", "channel": "answer", "phase": "final_answer", "text": "Resumed"}, parent="event-2"),
        _event(4, "turn_completed", "turn-2", {}, status="completed", parent="event-3"),
    ]
    c.save_events()
    assert read(c)["text"] == "Resumed"
    c.events[1]["payload"]["metadata"]["recoveredTurnId"] = "other"
    c.save_events()
    assert read(c)["status"] == "unavailable"


@pytest.mark.parametrize("mutation", ["wrong_actor", "wrong_source", "wrong_key", "wrong_step", "not_completed", "bad_terminal", "conflicting_result", "duplicate_event", "missing_event_id", "partial_line", "branch", "duplicate_user"])
def test_unproven_or_conflicting_authority_fails_closed(result_env, mutation):
    c = result_env
    if mutation == "wrong_actor": c.runtime["agentId"] = "other"
    if mutation == "wrong_source": c.runtime["metadata"]["source"] = "other"
    if mutation == "wrong_key": c.runtime["metadata"]["externalTaskId"] = "other"
    if mutation == "wrong_step": c.run["attempts"][-1]["nodeId"] = "other"; c.save_run()
    if mutation == "not_completed": c.run["status"] = "running"; c.save_run()
    if mutation == "bad_terminal": c.events[-1]["eventType"] = "turn_failed"
    if mutation == "conflicting_result": c.events[-1]["payload"]["resultStatus"] = "failed"
    if mutation == "duplicate_event": c.events[1]["eventId"] = c.events[0]["eventId"]
    if mutation == "missing_event_id": c.events[1].pop("eventId")
    if mutation == "branch": c.events.insert(1, _event(2, "branch_rebase", "turn-1", {"operation": "edit"}))
    if mutation == "duplicate_user": c.events.insert(1, _event(2, "user_message", "turn-1", {"source": "generic_team_workflow"}, correlation=c.key))
    if mutation not in {"wrong_actor", "wrong_source", "wrong_key", "wrong_step", "not_completed", "partial_line"}: c.save_events()
    if mutation == "partial_line": c.journal.write_bytes(c.journal.read_bytes() + b'{"eventId":')
    assert read(c)["status"] == "unavailable"


def test_empty_answer_is_explicit(result_env):
    result_env.events.pop(1)
    result_env.save_events()
    assert read(result_env) == {"status": "empty", "text": "", "truncated": False, "untrustedContent": True}


def test_native_journal_writer_format(result_env, monkeypatch):
    from core.chat import turn_journal
    c = result_env
    c.journal.unlink()
    monkeypatch.setattr(turn_journal, "turn_journal_workspace_root", lambda _: c.env.root / "sessions")
    turn_journal.append_turn_event(c.env.root, "session-final", "turn-1", "turn_started", status="running")
    turn_journal.append_turn_event(c.env.root, "session-final", "turn-1", "user_message",
        payload={"content": "task", "source": "generic_team_workflow"}, correlation_id=c.key)
    turn_journal.append_turn_event(c.env.root, "session-final", "turn-1", "assistant_message",
        status="completed", payload={"content": "Native answer"})
    turn_journal.append_turn_event(c.env.root, "session-final", "turn-1", "turn_completed",
        status="completed", payload={"resultStatus": "completed", "finalStatus": "completed"})
    assert read(c)["text"] == "Native answer"


def test_authority_changes_during_read_fail_closed(result_env, monkeypatch):
    c = result_env
    original = team_result._journal
    def mutate_after_journal(path):
        result = original(path)
        c.run["status"] = "failed"
        c.save_run()
        return result
    monkeypatch.setattr(team_result, "_journal", mutate_after_journal)
    assert read(c)["status"] == "unavailable"


def test_wrong_project_and_subject_fail_closed(result_env):
    c = result_env
    assert team_result.read_team_result(c.intents, "request-1", c.env.root / "wrong")["status"] == "unavailable"
    c.intents.owner = type(c.intents.owner)("other-subject", c.intents.owner.binding, c.intents.owner.authority,
                                            c.intents.owner.record_root)
    assert read(c)["status"] == "unavailable"
