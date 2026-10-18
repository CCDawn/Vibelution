"""Session supervision reads native journal facts, never completion repair APIs."""
from __future__ import annotations

import copy
import json
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from core.chat.turn_journal import TurnJournalEvent
from core.runtime_manager.work_run_store import WorkRunStore
from core.web.services.team_workflow.generic import session_source, store

_NATIVE_SNAPSHOT = session_source.journal_bridge.load_session_conversation_events_snapshot


class Journal:
    def __init__(self):
        self.events = []

    def add(self, kind, turn, *, source="submit_session_message", payload=None, **fields):
        event = TurnJournalEvent.from_dict({
            "schemaVersion": 2, "sessionId": "session-a", "turnId": turn,
            "eventId": f"event-{len(self.events) + 1}", "sequence": len(self.events) + 1,
            "eventType": kind, "status": "recorded", "timestamp": "2026-10-18T00:00:00Z",
            "source": source, "payload": payload or {}, **fields,
        })
        self.events.append(event)
        return event

    def user(self, turn, content="SECRET prompt", **fields):
        return self.add("user_message", turn, payload={"content": content, **fields})

    def fail(self, turn, code="runtime_error", **fields):
        return self.add("turn_failed", turn, source="persist_session_turn_failure",
                        status="failed_runtime", payload={"failureCategory": code,
                            "failureDisposition": "permanent", "rawError": "SECRET error",
                            "message": "SECRET transcript", **fields})

    def regenerate(self, old_turn, new_turn, *, operation="regenerate"):
        active = session_source.build_journal_event_tree(self.events)
        active_events = [active.events_by_id[key] for key in active.chain_ids]
        cut = next(i for i, event in enumerate(active_events) if event.turn_id == old_turn)
        target = next(event for event in active_events[cut:] if event.event_type == "user_message")
        parent = active_events[cut - 1].event_id if cut else ""
        replaced = list(dict.fromkeys(event.turn_id for event in active_events[cut:]))
        self.add("branch_rebase", new_turn, source="session_branch_rebase",
                 visibleInModel=False, projectionKind="session_branch_rebase", parentEventId=parent,
                 payload={"operation": operation, "branchId": f"branch-{new_turn}",
                          "fromEventId": parent, "replacedTurnIds": replaced,
                          "baseMessageId": target.event_id})
        return self.add("user_message", new_turn,
                        source="regenerate_session_message" if operation == "regenerate" else "edit_and_resubmit_session_message",
                        payload={"content": target.payload["content"],
                                 "source": "regenerated_user_message" if operation == "regenerate" else "edited_user_message",
                                 "metadata": {"turnId": new_turn}})

    def resume(self, old_turn, new_turn):
        return self.add("user_message", new_turn, correlationId=f"resume:{old_turn}", payload={
            "content": "SECRET prompt", "source": "hot_restart_resume", "metadata": {
                "kind": "hot_restart_resume", "recoverySource": "startup_sweep",
                "recoveredTurnId": old_turn, "clientSubmissionId": f"resume:{old_turn}"}})


@pytest.fixture
def env(tmp_path, monkeypatch):
    journal = Journal()
    state = {"conversation_id": "session-a", "agent_id": "agent-a", "last_turn_status": "ready"}
    agents = [{"agentId": "agent-a", "status": "active", "metadata": {}}]
    team = {"teamId": "team-a", "status": "active", "members": [{"agentId": "agent-a"}]}
    runtime = {"running": False}
    calls = []

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Observation must never repair or submit native state")

    def registry_path(*parts, **kwargs):
        assert parts == ("agents", "agents.json")
        assert kwargs == {"intent": "state", "seed": False}
        return SimpleNamespace(read_text=lambda **_kwargs: json.dumps({"agents": agents}))

    sessions = SimpleNamespace(PROJECT_ROOT=tmp_path,
        load_session_chat_state=lambda *_args: copy.deepcopy(state),
        _is_session_running=lambda _sid: runtime["running"],
        _WORK_RUN_STORE=WorkRunStore(root=tmp_path / "work-runs"),
        _active_chat_turn_work_run_for_session=forbidden,
        agent_directory_service=SimpleNamespace(load_state=forbidden, get_agent=forbidden,
            scoped_project_root=lambda _root: nullcontext(), _workspace_path=registry_path),
        get_session_turn_completion_snapshot=forbidden, get_session_detail=forbidden,
        regenerate_session_message=forbidden, submit_session_message=forbidden)
    monkeypatch.setattr(session_source, "_service", lambda: sessions)
    monkeypatch.setattr(store, "team", lambda team_id: copy.deepcopy(team) if team_id == "team-a" else {})
    monkeypatch.setattr(session_source.journal_bridge, "load_session_conversation_events_snapshot",
                        lambda *_args, **_kwargs: calls.append("journal") or list(journal.events))
    record = {"id": "run-watch", "teamId": "team-a", "attempts": [], "flow": {
        "fields": [], "steps": [{"id": "source", "kind": "session", "sessionSource": {
            "sessionId": "session-a", "turnId": "turn-1", "agentId": "agent-a"}}],
        "failureRecovery": {"maxAttempts": 3}}}
    return SimpleNamespace(journal=journal, state=state, team=team, agents=agents,
                           runtime=runtime, record=record, sessions=sessions, calls=calls)


def test_one_failure_reads_only_native_facts_and_keeps_private_text_out(env):
    env.journal.user("turn-1")
    env.journal.fail("turn-1")
    before = copy.deepcopy(env.record)
    first = session_source.observe(env.record)
    assert first == session_source.observe(env.record)
    assert env.record == before
    assert first["eligible"] is True and first["retryExhausted"] is False
    assert first["sourceAttemptKey"] == "turn-1"
    assert first["attempts"][0]["failureCode"] == "runtime_error"
    assert "SECRET" not in json.dumps(first)
    assert session_source.replay(env.record) == "source_replay_requires_user"


def test_first_turn_regenerate_is_real_lineage_even_without_native_alias(env):
    env.journal.user("turn-1")
    env.journal.fail("turn-1")
    env.journal.regenerate("turn-1", "turn-2")
    env.journal.fail("turn-2")
    env.journal.regenerate("turn-2", "turn-3")
    env.journal.fail("turn-3")
    snapshot = session_source.observe(env.record)
    assert [item["key"] for item in snapshot["attempts"]] == ["turn-1", "turn-2", "turn-3"]
    assert snapshot["retryExhausted"] and snapshot["eligible"]
    latest_record = copy.deepcopy(env.record)
    latest_record["flow"]["steps"][0]["sessionSource"]["turnId"] = "turn-3"
    assert session_source.identity(latest_record) == session_source.identity(env.record) == {
        "kind": "session", "sessionId": "session-a", "turnId": "turn-1", "agentId": "agent-a"}
    env.record["attempts"] = copy.deepcopy(snapshot["attempts"])
    assert session_source.fence(env.record) == ""
    assert session_source.observe(env.record) == snapshot


def test_policy_budget_one_exhausts_but_tool_retries_do_not(env):
    env.journal.user("turn-1")
    for _ in range(5):
        env.journal.add("tool_result", "turn-1", payload={"error": "SECRET tool error"})
        env.journal.add("llm_resilience", "turn-1", payload={"attempt": 4})
    env.journal.fail("turn-1")
    assert len(session_source.observe(env.record)["attempts"]) == 1
    env.record["flow"]["failureRecovery"]["maxAttempts"] = 1
    assert session_source.observe(env.record)["retryExhausted"] is True


def test_startup_resume_chain_is_one_business_attempt_and_fences_effective_turn(env):
    env.journal.user("turn-1")
    env.journal.resume("turn-1", "resume-1")
    initial = session_source.observe(env.record)
    env.record["attempts"] = copy.deepcopy(initial["attempts"])
    env.journal.resume("resume-1", "resume-2")
    env.journal.fail("resume-2")
    snapshot = session_source.observe(env.record)
    assert len(snapshot["attempts"]) == 1
    assert snapshot["attempts"][0]["originTurnId"] == "turn-1"
    assert snapshot["attempts"][0]["turnId"] == "resume-2"
    assert snapshot["attempts"][0]["recoveryTurnIds"] == ["resume-1", "resume-2"]
    assert snapshot["sourceAttemptKey"] == "turn-1"
    assert snapshot["retryExhausted"] is False
    assert session_source.fence(env.record) == "source_advanced"


def test_regenerate_original_user_after_startup_resume_keeps_effective_failure(env):
    env.journal.user("turn-1")
    env.journal.resume("turn-1", "resume-1")
    env.journal.resume("resume-1", "resume-2")
    env.journal.fail("resume-2")
    env.journal.regenerate("turn-1", "turn-2")
    env.journal.fail("turn-2")
    env.journal.regenerate("turn-2", "turn-3")
    env.journal.fail("turn-3")
    snapshot = session_source.observe(env.record)
    assert [item["status"] for item in snapshot["attempts"]] == ["failed", "failed", "failed"]
    assert snapshot["attempts"][0]["turnId"] == "resume-2"
    assert snapshot["attempts"][0]["recoveryTurnIds"] == ["resume-1", "resume-2"]
    assert snapshot["retryExhausted"]


@pytest.mark.parametrize("advance", ["followup", "edit", "head_select"])
def test_other_task_or_branch_selection_does_not_join_retry_lineage(env, advance):
    original = env.journal.user("turn-1")
    terminal = env.journal.fail("turn-1")
    env.record["attempts"] = session_source.observe(env.record)["attempts"]
    if advance == "followup":
        env.journal.user("new-task", content="SECRET unrelated task")
        env.journal.fail("new-task")
    elif advance == "edit":
        env.journal.regenerate("turn-1", "edited", operation="edit")
        env.journal.fail("edited")
    else:
        env.journal.regenerate("turn-1", "turn-2")
        env.journal.fail("turn-2")
        env.journal.add("branch_rebase", "turn-1", source="session_head_select", visibleInModel=False,
                        payload={"operation": "head_select", "fromEventId": terminal.event_id,
                                 "baseMessageId": original.event_id, "replacedTurnIds": []})
    result = session_source.observe(env.record)
    assert not result["eligible"] and result["reason"] == "source_advanced"
    assert session_source.fence(env.record) == "source_advanced"


@pytest.mark.parametrize("damage", ["wrong_base", "wrong_replaced", "missing_parent", "bad_resume", "duplicate_terminal"])
def test_broken_or_forged_lineage_fails_closed(env, damage):
    env.journal.user("turn-1")
    if damage == "bad_resume":
        env.journal.resume("missing-parent", "resume-1")
        env.journal.fail("resume-1")
    else:
        env.journal.fail("turn-1")
        if damage == "duplicate_terminal":
            env.journal.fail("turn-1")
        else:
            env.journal.regenerate("turn-1", "turn-2")
            marker = env.journal.events[-2]
            if damage == "wrong_base":
                marker.payload["baseMessageId"] = "wrong-event"
            elif damage == "wrong_replaced":
                marker.payload["replacedTurnIds"] = ["wrong-turn"]
            else:
                marker.payload["fromEventId"] = "unknown-event"
            env.journal.fail("turn-2")
    snapshot = session_source.observe(env.record)
    assert not snapshot["eligible"] and snapshot["reason"] == "source_lineage_invalid"
    assert session_source.fence(env.record) == "source_lineage_invalid"


@pytest.mark.parametrize("failure", [
    {"failureCategory": "auth_error"}, {"failureCategory": "authentication_error"},
    {"problemCode": "context_budget_exhausted"}, {"failureDisposition": "budget_or_context"},
    {"failureCategory": "quota_error"}, {"problemCode": "approval_rejected"},
    {"failureCategory": "user_interrupt"}, {"errorType": "credential_error"},
    {"problemCode": "approval_declined"}, {"problemCode": "approval_cancelled"},
    {"finalStatus": "stopped_by_user"},
])
def test_budget_auth_human_and_cancel_failures_never_dispatch_repairs(env, failure):
    env.journal.user("turn-1")
    env.journal.fail("turn-1", **failure)
    result = session_source.observe(env.record)
    assert not result["eligible"] and result["reason"] == "source_human_required"


def test_explicit_stop_and_running_or_human_wait_are_not_repairable(env):
    env.journal.user("turn-1")
    env.journal.add("turn_interrupted", "turn-1", status="stopped", payload={"reason": "user_stop"})
    assert session_source.observe(env.record)["status"] == "stopped"
    env.journal.events.pop()
    env.journal.fail("turn-1")
    env.runtime["running"] = True
    assert session_source.observe(env.record)["reason"] == "source_execution_unsettled"
    env.runtime["running"] = False
    env.state["last_turn_status"] = "waiting_human"
    assert session_source.observe(env.record)["reason"] == "source_human_required"


@pytest.mark.parametrize("field", ["last_turn_status", "lastTurnStatus"])
@pytest.mark.parametrize("status", ["queued", "running", "stopping", " RUNNING "])
def test_persisted_execution_state_fences_old_terminal_before_local_flag(env, field, status):
    env.journal.user("turn-1")
    env.journal.fail("turn-1")
    env.record["attempts"] = session_source.observe(env.record)["attempts"]
    env.state.pop("last_turn_status")
    env.state[field] = status
    result = session_source.observe(env.record)
    assert result["status"] == "running" and not result["eligible"]
    assert result["reason"] == "source_execution_unsettled"
    assert session_source.fence(env.record) == "source_execution_unsettled"


@pytest.mark.parametrize("active", [True, False])
def test_work_run_reads_every_active_slot_without_repairing_settled_index(env, active):
    env.journal.user("turn-1")
    env.journal.fail("turn-1")
    env.record["attempts"] = session_source.observe(env.record)["attempts"]
    work_runs = env.sessions._WORK_RUN_STORE
    work_runs.ensure_kind_dirs("chat_turn")
    ids = [f"other-{i}" for i in range(45)]
    # The supervised run is older than 40 unrelated runs and is not the
    # legacy latest active id. A settled active id must stay byte-for-byte.
    ids.insert(0, "turn-2")
    work_runs.index_path("chat_turn").write_text(json.dumps({
        "activeRunIds": ids, "activeRunId": ids[-1], "recentRunIds": ids[1:]}), encoding="utf-8")
    for run_id in ids:
        watched = run_id == "turn-2"
        value = {"runId": run_id, "sessionId": "session-a" if watched else "other-session",
                 "status": "queued" if active and watched else "completed"}
        (work_runs.runs_dir("chat_turn") / f"{run_id}.json").write_text(json.dumps(value), encoding="utf-8")
    before = {str(path): path.read_bytes() for path in work_runs.root.rglob("*") if path.is_file()}
    result = session_source.observe(env.record)
    if active:
        assert result["status"] == "running" and not result["eligible"]
        assert result["reason"] == "source_execution_unsettled"
        assert session_source.fence(env.record) == "source_execution_unsettled"
    else:
        assert result["status"] == "failed" and result["eligible"]
    after = {str(path): path.read_bytes() for path in work_runs.root.rglob("*") if path.is_file()}
    assert after == before


@pytest.mark.parametrize("case", ["member_removed", "owner_changed", "agent_deleted", "companion", "archived"])
def test_source_identity_and_live_team_ownership_fail_closed(env, case):
    env.journal.user("turn-1")
    env.journal.fail("turn-1")
    if case == "member_removed":
        env.team["members"] = []
    elif case == "owner_changed":
        env.state["agent_id"] = "other-agent"
    elif case == "agent_deleted":
        env.agents.clear()
    elif case == "companion":
        env.agents[0]["metadata"]["virtualHumanCompanion"] = True
    else:
        env.team["status"] = "archived"
    with pytest.raises(store.WorkflowError):
        session_source.observe(env.record)
    assert session_source.fence(env.record) == "source_scope_unavailable"


def test_source_advance_between_reads_is_not_a_settled_failure(env, monkeypatch):
    env.journal.user("turn-1")
    env.journal.fail("turn-1")
    env.record["attempts"] = session_source.observe(env.record)["attempts"]
    reads = []

    def racing(*_args, **_kwargs):
        if reads:
            env.journal.user(f"next-task-{len(reads)}")
        reads.append(True)
        return list(env.journal.events)

    monkeypatch.setattr(session_source.journal_bridge, "load_session_conversation_events_snapshot", racing)
    snapshot = session_source.observe(env.record)
    assert not snapshot["eligible"] and snapshot["reason"] == "source_advanced"
    assert session_source.fence(env.record) == "source_advanced"


def test_completed_anchor_does_not_resolve_after_source_has_advanced(env):
    env.journal.user("turn-1")
    env.journal.add("assistant_message", "turn-1", payload={"content": "real answer"})
    env.journal.add("turn_completed", "turn-1", status="completed")
    env.journal.user("new-task")
    result = session_source.observe(env.record)
    assert result["status"] == "running"
    assert not result["eligible"] and result["reason"] == "source_advanced"


def test_native_companion_binding_blocks_even_when_directory_metadata_is_absent(env, monkeypatch):
    env.journal.user("turn-1")
    env.journal.fail("turn-1")
    monkeypatch.setattr(session_source.VirtualHumanLifeStore, "read_json",
                        lambda _self, _agent, _path: {"enabled": True, "agentId": "agent-a"})
    with pytest.raises(store.WorkflowError):
        session_source.observe(env.record)


def test_success_requires_same_turn_real_assistant_and_resets_failure_budget(env):
    env.journal.user("turn-1")
    env.journal.fail("turn-1")
    env.journal.regenerate("turn-1", "turn-2")
    env.journal.add("turn_completed", "turn-2", status="completed", payload={"summary": "Executor says done"})
    result = session_source.observe(env.record)
    assert result["status"] != "completed" and result["reason"] == "source_completion_unverified"
    env.journal.events.pop()
    env.journal.add("assistant_partial", "turn-2", payload={"content": "partial"})
    env.journal.add("assistant_message", "other-turn", payload={"content": "wrong turn"})
    env.journal.add("turn_completed", "turn-2", status="completed")
    assert session_source.observe(env.record)["status"] != "completed"
    env.journal.events.pop()
    env.journal.add("assistant_message", "turn-2", payload={"content": "SECRET native answer"})
    env.journal.add("turn_completed", "turn-2", status="completed")
    assert session_source.observe(env.record)["status"] == "completed"
    env.journal.regenerate("turn-2", "turn-3")
    env.journal.fail("turn-3")
    result = session_source.observe(env.record)
    assert [item["status"] for item in result["attempts"]] == ["failed", "completed", "failed"]
    assert not result["retryExhausted"]


def test_non_first_turn_regenerate_alias_and_api_position_base_are_supported(env):
    env.journal.user("earlier")
    env.journal.add("assistant_message", "earlier", payload={"content": "earlier answer"})
    env.journal.user("turn-1")
    env.journal.fail("turn-1")
    env.journal.regenerate("turn-1", "turn-2")
    env.journal.events[-2].payload["baseMessageId"] = "session-a-message-3"
    env.journal.fail("turn-2")
    snapshot = session_source.observe(env.record)
    assert snapshot["eligible"]
    assert [item["key"] for item in snapshot["attempts"]] == ["turn-1", "turn-2"]


def test_untrusted_failure_text_is_not_a_code(env):
    env.journal.user("turn-1")
    env.journal.fail("turn-1", problemCode="SECRET prompt: user request", errorType="SECRET exception body")
    snapshot = session_source.observe(env.record)
    assert snapshot["attempts"][0]["failureCode"] == "runtime_error"
    assert "SECRET" not in json.dumps(snapshot)


def test_late_assistant_after_terminal_does_not_manufacture_completion(env):
    env.journal.user("turn-1")
    env.journal.add("turn_completed", "turn-1", status="completed")
    env.journal.add("assistant_message", "turn-1", payload={"content": "invalid late answer"})
    result = session_source.observe(env.record)
    assert result["status"] == "running" and result["reason"] == "source_completion_unverified"


def test_reads_native_on_disk_journal_and_preserves_every_file(env, monkeypatch, tmp_path):
    from core.chat.turn_journal import append_turn_event, turn_journal_path

    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "operator-data"))
    monkeypatch.setattr("core.infrastructure.developer_sandbox.is_developer_mode_enabled", lambda: False)
    env.journal.add("turn_started", "turn-1")
    env.journal.user("turn-1")
    env.journal.fail("turn-1")
    env.journal.regenerate("turn-1", "turn-2")
    env.journal.fail("turn-2")
    # Native writers establish the same coordination sidecar native readers
    # use. Build the journal through that owner before installing exact ids.
    append_turn_event(env.sessions.PROJECT_ROOT, "session-a", "turn-1", "turn_started")
    path = turn_journal_path(env.sessions.PROJECT_ROOT, "session-a")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(event.to_dict()) + "\n" for event in env.journal.events), encoding="utf-8")
    before = {str(item): item.read_bytes() for item in tmp_path.rglob("*") if item.is_file()}
    monkeypatch.setattr(session_source.journal_bridge, "load_session_conversation_events_snapshot", _NATIVE_SNAPSHOT)
    snapshot = session_source.observe(env.record)
    assert [item["key"] for item in snapshot["attempts"]] == ["turn-1", "turn-2"]
    assert snapshot["eligible"]
    assert session_source.observe(env.record) == snapshot
    after = {str(item): item.read_bytes() for item in tmp_path.rglob("*") if item.is_file()}
    assert after == before
