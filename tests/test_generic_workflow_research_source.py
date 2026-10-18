"""Research supervision reuses repair runs without owning research execution."""
from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from core.web.services.team_workflow.generic import service, store
from core.web.services.team_workflow.generic.models import Flow
from tests.test_generic_team_workflows import env, tick  # noqa: F401
from tests.test_generic_workflow_binding import bound_env, payload  # noqa: F401
from tests.test_generic_workflow_recovery import scan, child_of, finish_repair


def source_definition():
    return {"id": "source-flow", "name": "研究故障监督", "fields": [], "steps": [
        {"id": "source", "label": "原研究节点", "kind": "research", "owner": "",
         "researchSource": {"runId": "research-run", "nodeId": "source_finding"}},
    ]}


def test_source_contract_is_explicit_and_cannot_mix_execution_steps():
    flow = Flow.model_validate(source_definition())
    assert flow.steps[0].researchSource.runId == "research-run"
    mixed = source_definition()
    mixed["steps"].append({"id": "other", "label": "执行", "kind": "agent", "owner": "developer"})
    with pytest.raises(ValidationError):
        Flow.model_validate(mixed)
    invalid = source_definition()
    invalid["steps"][0]["researchSource"] = None
    with pytest.raises(ValidationError):
        Flow.model_validate(invalid)


def supervised(bound_env, monkeypatch, *, failures=3, exhausted=False, safety="idempotent"):
    from core.web.services.team_workflow.generic import binding, research_source

    state = {"status": "failed", "eligible": True, "reason": "", "retryExhausted": exhausted,
             "attempts": [{"nodeId": "source", "number": n, "agentId": "", "sessionId": "", "turnId": "",
                           "key": f"native-{n}", "status": "failed", "failureCode": "provider_timeout"}
                          for n in range(1, failures + 1)]}
    monkeypatch.setattr(research_source, "observe", lambda record: {
        **copy.deepcopy(state), "sourceAttemptKey": state["attempts"][-1]["key"]})
    service.save_flow("team-a", "source-flow", {"flow": source_definition(), "expectedRevision": 0})
    binding.bind_recovery("team-a", "source-flow", payload(replaySafety=safety))
    run = service.start_run("team-a", "source-flow", {"expectedRevision": 2,
        "idempotencyKey": "supervise", "values": {}})
    return tick(run), state


def test_source_requires_bound_opt_in_before_start(bound_env):
    service.save_flow("team-a", "source-flow", {"flow": source_definition(), "expectedRevision": 0})
    with pytest.raises(store.WorkflowError):
        service.start_run("team-a", "source-flow", {"expectedRevision": 1,
            "idempotencyKey": "unbound", "values": {}})


def test_three_native_failures_dispatch_once_without_source_session(bound_env, monkeypatch):
    run, _ = supervised(bound_env, monkeypatch)
    run = scan(run, 4)
    assert run["recovery"]["failureCount"] == 3
    assert run["recovery"]["repairAttempts"] == 1
    assert len(service.list_runs("team-a")["runs"]) == 2
    assert bound_env.sessions.submitted == []
    assert child_of(run)["flow"]["steps"][0]["owner"] == "director"


@pytest.mark.parametrize("exhausted, expected", [(False, "tracking"), (True, "repairing")])
def test_native_retry_exhaustion_escalates_before_three(bound_env, monkeypatch, exhausted, expected):
    run, _ = supervised(bound_env, monkeypatch, failures=1, exhausted=exhausted)
    run = scan(run)
    assert run["recovery"]["status"] == expected
    assert bound_env.sessions.submitted == []


def test_repair_receipt_does_not_resolve_before_native_success(bound_env, monkeypatch):
    from core.web.services.team_workflow.generic import research_source

    run, state = supervised(bound_env, monkeypatch)
    replay = []
    monkeypatch.setattr(research_source, "replay", lambda record: replay.append(record["id"]) or "")
    run = tick(finish_repair(bound_env, scan(run)))
    assert run["recovery"]["status"] == "replaying"
    assert len(replay) == 1
    state["status"] = "completed"
    state["attempts"].append({**state["attempts"][-1], "number": 4, "key": "native-4",
                               "status": "completed", "failureCode": ""})
    run = scan(tick(run))
    assert run["recovery"]["status"] == "resolved"
    assert run["recovery"]["replayedAttemptKey"] == "native-4"


def test_replay_budget_refusal_waits_for_decision(bound_env, monkeypatch):
    from core.web.services.team_workflow.generic import research_source

    run, _ = supervised(bound_env, monkeypatch)
    monkeypatch.setattr(research_source, "replay", lambda record: "source_retry_budget_exhausted")
    run = tick(finish_repair(bound_env, scan(run)))
    assert run["recovery"]["status"] == "awaiting_replay_decision"
    assert run["recovery"]["reason"] == "source_retry_budget_exhausted"


def test_duplicate_supervision_is_rejected_and_original_request_is_idempotent(bound_env, monkeypatch):
    run, _ = supervised(bound_env, monkeypatch)
    request = {"expectedRevision": 2, "idempotencyKey": "supervise", "values": {}}
    assert service.start_run("team-a", "source-flow", request)["id"] == run["id"]
    with pytest.raises(store.Conflict):
        service.start_run("team-a", "source-flow", {**request, "idempotencyKey": "another"})


def test_native_source_moving_cancels_stale_repair(bound_env, monkeypatch):
    run, state = supervised(bound_env, monkeypatch)
    run = scan(run)
    child = tick(child_of(run))
    assert child["attempts"][-1]["agentId"] == "director"
    state["status"] = "running"
    state["eligible"] = False
    state["attempts"].append({**state["attempts"][-1], "number": 4, "key": "native-4", "status": "running"})
    run = tick(run)
    assert run["recovery"]["status"] == "blocked"
    assert child_of(run)["stopRequested"] is True


def test_revoke_before_replay_intent_submission_prevents_native_retry(bound_env, monkeypatch):
    from core.web.services.team_workflow.generic import binding, research_source

    run, _ = supervised(bound_env, monkeypatch)
    run = finish_repair(bound_env, scan(run))
    called = []
    monkeypatch.setattr(research_source, "replay", lambda record: called.append(record) or "")
    binding.revoke_recovery("team-a", "source-flow", {"expectedRevision": 2})
    run = tick(run)
    assert not called
    assert run["recovery"]["status"] == "blocked"


def test_unknown_side_effects_never_automatically_replay(bound_env, monkeypatch):
    from core.web.services.team_workflow.generic import research_source

    run, _ = supervised(bound_env, monkeypatch, safety="unknown")
    called = []
    monkeypatch.setattr(research_source, "replay", lambda record: called.append(record) or "")
    run = tick(finish_repair(bound_env, scan(run)))
    assert run["recovery"]["status"] == "awaiting_replay_decision"
    assert not called


def test_stopped_supervision_cannot_overlap_its_unsettled_repair_child(bound_env, monkeypatch):
    run, _ = supervised(bound_env, monkeypatch)
    run = scan(run)
    child = tick(child_of(run))
    run = service.command_run("team-a", run["id"], {"action": "stop", "expectedRevision": run["revision"]})
    assert run["status"] == "stopped"
    with pytest.raises(store.Conflict):
        service.start_run("team-a", "source-flow", {"expectedRevision": 2,
            "idempotencyKey": "replacement", "values": {}})
    bound_env.sessions.finish(child["attempts"][-1], status="stopped", content="")
    assert service.start_run("team-a", "source-flow", {"expectedRevision": 2,
        "idempotencyKey": "replacement", "values": {}})["id"] != run["id"]


def test_different_problem_codes_do_not_count_as_three_same_failures(bound_env, monkeypatch):
    run, state = supervised(bound_env, monkeypatch)
    for index, attempt in enumerate(state["attempts"]):
        attempt["failureCode"] = f"problem_{index}"
    run = scan(tick(run))
    assert run["recovery"]["status"] == "tracking"
    assert run["recovery"]["failureCount"] == 1
    assert len(service.list_runs("team-a")["runs"]) == 1


def test_source_advancing_during_session_create_prevents_stale_native_submit(bound_env, monkeypatch):
    from core.web.services.team_workflow.generic import native

    run, state = supervised(bound_env, monkeypatch)
    run = scan(run)
    create = bound_env.sessions.create
    def advancing_create(attempt, child, step):
        session = create(attempt, child, step)
        state["status"] = "running"
        state["eligible"] = False
        state["attempts"].append({**state["attempts"][-1], "key": "native-4", "status": "running"})
        return session
    monkeypatch.setattr(native, "create", advancing_create)
    tick(child_of(run))
    assert not bound_env.sessions.submitted
