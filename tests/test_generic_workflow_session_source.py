"""Ordinary Session supervisors reuse the existing repair state machine."""
from __future__ import annotations

from copy import deepcopy

import pytest

from core.web.services.team_workflow.generic import service
from core.web.services.team_workflow.generic.models import Flow
from tests.test_generic_team_workflows import env, tick  # noqa: F401
from tests.test_generic_workflow_binding import bound_env, payload  # noqa: F401
from tests.test_generic_workflow_recovery import child_of, finish_repair, scan


def flow():
    return {"id": "session-watch", "name": "Session failure supervision", "steps": [
        {"id": "source", "label": "Bound task", "kind": "session", "sessionSource": {
            "sessionId": "session-1", "turnId": "turn-1", "agentId": "source-agent"}}]}


def test_session_source_is_an_explicit_single_read_only_reference():
    validated = Flow.model_validate(flow()).model_dump()
    assert service.supervised({"flow": validated})
    assert validated["steps"][0]["sessionSource"]["turnId"] == "turn-1"


@pytest.mark.parametrize("patch", [{"owner": "writer"}, {"instruction": "execute"},
                                   {"resultContract": "outcome_v1"},
                                   {"researchSource": {"runId": "r", "nodeId": "n"}}])
def test_source_cannot_add_execution_or_mix_source_kinds(patch):
    definition = flow()
    definition["steps"][0].update(patch)
    with pytest.raises(ValueError):
        Flow.model_validate(definition)


def test_source_cannot_mix_with_an_executable_step_or_inputs():
    for extra in ({"fields": [{"id": "input", "label": "input", "kind": "text"}]},
                  {"steps": [*flow()["steps"], {"id": "run", "label": "run", "kind": "agent", "owner": "writer"}]}):
        with pytest.raises(ValueError):
            Flow.model_validate({**flow(), **extra})


def supervised_session(bound_env, monkeypatch, *, count=3, exhausted=False, safety="idempotent"):
    from core.web.services.team_workflow.generic import binding, session_source

    definition = flow()
    definition["steps"][0]["sessionSource"]["agentId"] = "agent-a"
    state = {"status": "failed", "eligible": True, "reason": "", "retryExhausted": exhausted,
        "attempts": [{"nodeId": "source", "number": n, "agentId": "agent-a", "sessionId": "session-1",
                      "turnId": f"turn-{n}", "key": f"turn-{n}", "status": "failed",
                      "failureCode": "provider_timeout"} for n in range(1, count + 1)]}
    monkeypatch.setattr(session_source, "identity", lambda record: {
        "kind": "session", "sessionId": "session-1", "turnId": "turn-1", "agentId": "agent-a"})
    monkeypatch.setattr(session_source, "observe", lambda record: {
        **deepcopy(state), "sourceAttemptKey": state["attempts"][-1]["key"]})
    service.save_flow("team-a", definition["id"], {"flow": definition, "expectedRevision": 0})
    binding.bind_recovery("team-a", definition["id"], payload(replaySafety=safety))
    run = service.start_run("team-a", definition["id"], {
        "expectedRevision": 2, "idempotencyKey": "session-supervision", "values": {}})
    return tick(run), state


@pytest.mark.parametrize("count,exhausted,status", [(1, False, "tracking"), (2, False, "tracking"),
                                                    (1, True, "repairing"), (3, False, "repairing")])
def test_session_failures_use_existing_escalation_thresholds(bound_env, monkeypatch, count, exhausted, status):
    run, _state = supervised_session(bound_env, monkeypatch, count=count, exhausted=exhausted)
    run = scan(run, 4)
    assert run["recovery"]["status"] == status
    assert run["recovery"]["failureCount"] == count
    assert bound_env.sessions.submitted == []
    if status == "repairing":
        assert child_of(run)["flow"]["steps"][0]["owner"] == "director"
        assert run["recovery"]["repairAttempts"] == 1


def test_session_repair_waits_for_native_retry_and_resolves_only_on_real_source_success(bound_env, monkeypatch):
    from core.web.services.team_workflow.generic import session_source

    run, state = supervised_session(bound_env, monkeypatch)
    monkeypatch.setattr(session_source, "replay", lambda record: "source_replay_requires_user")
    run = tick(finish_repair(bound_env, scan(run)))
    assert run["recovery"]["status"] == "awaiting_replay_decision"
    assert run["recovery"]["reason"] == "source_replay_requires_user"
    assert run["status"] == "failed"
    state["status"] = "running"
    state["eligible"] = False
    state["attempts"].append({**state["attempts"][-1], "number": 4, "key": "turn-4",
                               "turnId": "turn-4", "status": "running", "failureCode": ""})
    run = tick(run)
    assert run["recovery"]["status"] == "replaying"
    state["status"] = "completed"
    state["attempts"][-1]["status"] = "completed"
    run = scan(tick(run))
    assert run["recovery"]["status"] == "resolved"
    assert run["recovery"]["replayedAttemptKey"] == "turn-4"


def test_same_logical_session_task_cannot_be_supervised_twice_from_different_retry_anchor(bound_env, monkeypatch):
    from core.web.services.team_workflow.generic import binding, store

    run, _state = supervised_session(bound_env, monkeypatch)
    other = flow()
    other["id"] = "another-supervisor"
    other["steps"][0]["sessionSource"].update(turnId="turn-3", agentId="agent-a")
    service.save_flow("team-a", other["id"], {"flow": other, "expectedRevision": 0})
    binding.bind_recovery("team-a", other["id"], payload())
    with pytest.raises(store.Conflict, match="已有故障监督"):
        service.start_run("team-a", other["id"], {
            "expectedRevision": 2, "idempotencyKey": "duplicate", "values": {}})
    assert len(service.list_runs("team-a")["runs"]) == 1


def test_source_advance_cancels_stale_session_repair(bound_env, monkeypatch):
    run, state = supervised_session(bound_env, monkeypatch)
    run = scan(run)
    state.update(status="running", eligible=False, reason="source_advanced")
    state["attempts"].append({**state["attempts"][-1], "number": 4, "key": "turn-4", "turnId": "turn-4", "status": "running"})
    run = tick(run)
    assert run["recovery"]["status"] == "blocked"
    assert child_of(run)["stopRequested"]


def test_changing_session_source_does_not_reuse_prior_repair_authorization(bound_env, monkeypatch):
    from core.web.services.team_workflow.generic import binding, store

    run, _state = supervised_session(bound_env, monkeypatch, count=1)
    target = store.path("team-a", "flows", run["flow"]["id"])
    definition = store.read(target)
    definition["steps"][0]["sessionSource"]["turnId"] = "unrelated-turn"
    service.save_flow("team-a", definition["id"], {"flow": definition, "expectedRevision": 2})
    assert binding.authorization_reason("team-a", store.read(store.path("team-a", "runs", run["id"]))) == "recovery_source_changed"
    run = scan(run)
    assert run["recovery"]["status"] == "blocked"
    assert run["recovery"]["reason"] == "recovery_source_changed"


def test_session_source_artifacts_are_read_only_native_pointers(bound_env, monkeypatch):
    from core.web.services.team_workflow.generic import native

    run, _state = supervised_session(bound_env, monkeypatch)

    def forbidden(_attempt):
        pytest.fail("Source artifacts must not call the generic native completion/repair path")

    monkeypatch.setattr(native, "snapshot", forbidden)
    artifacts = service.artifacts("team-a", run["id"])["artifacts"]
    assert len(artifacts) == 3
    assert all(item["content"] == "" for item in artifacts)
    assert artifacts[-1]["chatUrl"] == "/chat?session=session-1&turn=turn-3"
