"""Task discovery uses this run's receipts rather than ordinary role chats."""
from __future__ import annotations

import copy
import json

import pytest

from core.web.services.team_workflow.generic import service, store
from core.web.services.team_workflow.generic.communication import task_roster
from tests.test_generic_workflow_binding import bound_env, source_run, fail_source
from tests.test_generic_team_workflows import env, tick, save, start, command


def roster_from_prompt(prompt):
    return json.loads(prompt.split("TaskRoster（", 1)[1].split("\n", 1)[1].split("\n", 1)[0])


def test_repair_developer_receives_four_roles_and_exact_same_run_sessions(bound_env):
    agents_before = copy.deepcopy(bound_env.agents)
    source = fail_source(bound_env, source_run(bound_env, maxAttempts=1))
    child = tick(service.get_run("team-a", source["recovery"]["repairRunId"]))
    director = child["attempts"][-1]
    bound_env.sessions.finish(director, content="director result")
    child = tick(child, 2)
    developer = child["attempts"][-1]
    roster = roster_from_prompt(bound_env.sessions.submitted[-1][1])
    assert roster["runId"] == child["id"]
    assert roster["sourceRunId"] == source["id"]
    assert {item["role"]: item["agentId"] for item in roster["roles"]} == {
        "assistant": "assistant", "director": "director", "developer": "developer", "reviewer": "reviewer"}
    peers = {item["agentId"]: item for item in roster["participants"]}
    assert peers["director"]["sessionId"] == director["sessionId"]
    assert peers["director"]["turnId"] == director["turnId"]
    assert peers["director"]["addressState"] == "historical"
    assert peers["developer"]["sessionId"] == developer["sessionId"]
    assert peers["developer"]["addressState"] == "current"
    assert peers["reviewer"]["addressState"] == "unaddressable"
    assert peers["reviewer"]["sessionId"] == ""
    assert bound_env.agents == agents_before  # Discovery never grants tools.


def test_roster_excludes_other_runs_inputs_transcripts_and_superseded_attempts(bound_env):
    source = source_run(bound_env)
    record = store.read(store.path("team-a", "runs", source["id"]))
    old = record["attempts"][-1]
    old.update(status="failed", sessionId="old-session")
    latest = {**old, "number": 2, "key": "latest-key", "sessionId": "latest-session", "status": "dispatching"}
    record["attempts"].append(latest)
    record["values"]["subject"] = "private-input"
    record["unrelatedRun"] = {"sessionId": "foreign-session"}
    result = task_roster(record, record["flow"]["steps"][1])
    encoded = json.dumps(result)
    assert "latest-session" in encoded and "latest-key" in encoded
    assert all(value not in encoded for value in ["old-session", "foreign-session", "private-input", "原任务"])
    assert len(result["participants"]) == 1


def test_roster_rejects_receipt_owned_by_a_different_agent(bound_env):
    source = source_run(bound_env)
    record = store.read(store.path("team-a", "runs", source["id"]))
    record["attempts"][-1]["agentId"] = "reviewer"
    with pytest.raises(ValueError, match="owner"):
        task_roster(record, record["flow"]["steps"][1])


def test_owned_output_has_task_address_but_unowned_output_does_not(bound_env):
    run = source_run(bound_env)
    record = store.read(store.path("team-a", "runs", run["id"]))
    work = record["flow"]["steps"][1]
    work["kind"] = "output"
    roster = task_roster(record, work)
    assert len(roster["participants"]) == 1
    assert roster["participants"][0]["sessionId"] == record["attempts"][-1]["sessionId"]
    work["owner"] = ""
    assert task_roster(record, work)["participants"] == []


def test_pre_upgrade_dispatch_prompt_stays_byte_identical(bound_env):
    run = source_run(bound_env)
    record = store.read(store.path("team-a", "runs", run["id"]))
    step = record["flow"]["steps"][1]
    record.pop("_taskRosterVersion")
    prompt = service._prompt(record, step)
    assert "TaskRoster（" not in prompt
    assert prompt.endswith(json.dumps({"values": record["values"], "previousResults": [],
                                       "previousVersion": None}, ensure_ascii=False))
    record["_taskRosterVersion"] = 1
    assert "TaskRoster（" in service._prompt(record, step)


def test_pre_upgrade_persisted_dispatch_hash_can_resume_without_new_roster(env, monkeypatch):
    from core.web.services.team_workflow.generic import native

    save()
    run = tick(start())
    target = store.path("team-a", "runs", run["id"])
    record = store.read(target)
    record.pop("_taskRosterVersion")
    store.write(target, record)
    submit = native.submit

    def interrupted(*args):
        raise OSError("simulated transport interruption")

    monkeypatch.setattr(native, "submit", interrupted)
    run = tick(run)
    old_hash = run["attempts"][-1]["promptHash"]
    assert old_hash and run["status"] == "failed"
    monkeypatch.setattr(native, "submit", submit)
    run = tick(command(run, "retry"))
    assert run["attempts"][-1]["turnId"]
    assert run["attempts"][-1]["promptHash"] == old_hash
    assert "TaskRoster（" not in env.sessions.submitted[-1][1]
