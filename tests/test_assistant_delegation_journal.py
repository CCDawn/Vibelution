"""Goal provenance crosses real native Journal turns without weakening dispatch."""
from __future__ import annotations

import dataclasses
import json
import threading
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import anyio
import pytest

from core.assistant_runtime import delegation, native
from core.assistant_runtime.dispatch import DispatchError, DispatchService
from core.assistant_runtime.task_source import resolve_task
from core.chat import turn_journal as journal
from core.infrastructure import native_runtime


@pytest.fixture
def canonical_goal(tmp_path, monkeypatch):
    """Inject only native identity/storage; Journal append, replay and readers are real."""
    root = tmp_path / "native-profile"
    root.mkdir()
    runtime = {"agentId": "assistant-a", "sessionId": "own-session", "turnId": "operator-turn"}
    directory = SimpleNamespace(PROJECT_ROOT=root, current_agent_runtime=lambda: dict(runtime))
    sessions = SimpleNamespace(PROJECT_ROOT=root, SessionNotFoundError=type("Missing", (Exception,), {}),
        SessionBusyError=type("Busy", (Exception,), {}), SessionValidationError=type("Invalid", (Exception,), {}))
    opened = SimpleNamespace(directory_store_project_root=lambda: root, get_open_directory_store=lambda: object())
    monkeypatch.setattr(native_runtime, "_ASSISTANT_NATIVE_ROOT", root)
    monkeypatch.setattr(native, "_STARTED", True)
    monkeypatch.setattr(native, "_STOP_REQUESTED", threading.Event())
    monkeypatch.setattr(native, "_LOCK", threading.RLock())
    monkeypatch.setattr(native, "_AGENT_ID", runtime["agentId"])
    monkeypatch.setattr(native, "_SESSION_ID", runtime["sessionId"])
    monkeypatch.setattr(native, "_OFFLINE_MIGRATION", False)
    monkeypatch.setattr(native, "_QUIESCING", False)
    monkeypatch.setattr(native, "_services", lambda: (directory, None, sessions, opened))
    monkeypatch.setattr(native, "_projection", lambda: pytest.fail("source read hydrated/repaired Session"))
    monkeypatch.setattr(journal.developer_sandbox, "sandboxed_workspace_path",
                        lambda project, *parts: Path(project).joinpath("workspace", *parts))

    content = "目标：🧭检查失败组件，保留组合字符 e\u0301，完成后核验原回执。"
    start, user = journal.append_turn_events(root, runtime["sessionId"], runtime["turnId"], [
        {"event_type": journal.EVENT_TURN_STARTED, "status": "running", "source": "submit_session_message",
         "correlation_id": "operator-submit", "source_kind": "operator", "visible_in_model": False,
         "payload": {"agentId": runtime["agentId"], "source": "raw"}},
        {"event_type": journal.EVENT_USER_MESSAGE, "source": "submit_session_message", "provider_role": "user",
         "correlation_id": "operator-submit", "source_kind": "operator",
         "payload": {"content": content, "source": "raw", "metadata": {
             "clientSubmissionId": "operator-submit", "turnId": runtime["turnId"]}}},
    ])
    task, reference = resolve_task(dict(runtime), task_source={})
    assert task == content and reference["eventId"] == user.event_id
    journal.append_turn_event(root, runtime["sessionId"], runtime["turnId"], journal.EVENT_TURN_COMPLETED,
                              status="completed", visible_in_model=False)
    runtime["turnId"] = "proactive-turn"
    current_start, current_user = journal.append_turn_events(root, runtime["sessionId"], runtime["turnId"], [
        {"event_type": journal.EVENT_TURN_STARTED, "status": "running", "source": "submit_session_message",
         "source_kind": "personal-assistant-dialogue", "correlation_id": "patrol-trigger", "visible_in_model": False,
         "payload": {"agentId": runtime["agentId"], "source": "proactive"}},
        {"event_type": journal.EVENT_USER_MESSAGE, "source": "submit_session_message", "provider_role": "user",
         "source_kind": "personal-assistant-dialogue", "correlation_id": "patrol-trigger",
         "payload": {"content": "检查已授权目标的原任务回执。", "source": "proactive", "metadata": {
             "clientSubmissionId": "patrol-trigger", "kind": "proactive", "proactive": True}}},
    ])
    return SimpleNamespace(root=root, runtime=runtime, directory=directory, sessions=sessions, opened=opened,
        reference=reference, start=start, user=user, current_start=current_start, current_user=current_user,
        content=content, path=journal.turn_journal_path(root, runtime["sessionId"]))


def inventory(folder):
    return {str(path.relative_to(folder)): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in folder.rglob("*") if path.is_file()}


def rewrite_event(env, event_id, **changes):
    events = journal.load_turn_events(env.root, env.runtime["sessionId"])
    assert all(isinstance(event, journal.TurnJournalEvent) for event in events)
    journal.rewrite_turn_events(env.root, env.runtime["sessionId"], [
        dataclasses.replace(event, **changes) if event.event_id == event_id else event for event in events])


def test_real_operator_goal_can_be_verified_from_real_proactive_turn_without_journal_writes(canonical_goal):
    env = canonical_goal
    before = inventory(env.root)
    events = journal.load_turn_events(env.root, "own-session")
    assert env.user in events and env.current_user in events
    assert env.current_user.payload["source"] == "proactive"
    assert any(event.turn_id == "operator-turn" and event.event_type == journal.EVENT_TURN_COMPLETED for event in events)
    assert delegation.read_goal_source(dict(env.runtime), deepcopy(env.reference)) == env.reference
    assert inventory(env.root) == before
    assert env.content not in json.dumps(env.reference, ensure_ascii=False)


def test_real_goal_source_does_not_open_ordinary_native_source_or_dispatch_in_proactive_turn(canonical_goal, tmp_path):
    env = canonical_goal
    assert delegation.read_goal_source(dict(env.runtime), env.reference) == env.reference
    with pytest.raises(native.AssistantSessionError) as failure:
        native.read_task_source(dict(env.runtime), source_ref=env.reference)
    assert failure.value.code == "TASK_SOURCE_NOT_OPERATOR"
    with pytest.raises(DispatchError) as failure:
        resolve_task(dict(env.runtime), task_source={}, source_ref=env.reference)
    assert failure.value.code == "TASK_SOURCE_UNAVAILABLE"
    calls = []

    def client_factory(*args, **kwargs):
        calls.append((args, kwargs))
        pytest.fail("ordinary proactive dispatch reached a native client")

    target = tmp_path / "target-project"
    target.mkdir()
    service = DispatchService(tmp_path / "dispatch-profile", {"project-a": target}, client_factory=client_factory)

    async def dispatch():
        return await service.dispatch_from_source("project-a", agent_id="worker-a", dispatch_id="ordinary-proactive",
                                                  runtime=dict(env.runtime), task_source={})

    with pytest.raises(DispatchError) as failure:
        anyio.run(dispatch)
    assert failure.value.code == "TASK_SOURCE_UNAVAILABLE" and calls == []
    assert not list(service._root.glob("*.json"))


@pytest.mark.parametrize("source_kind", ["agent", "system", "proactive"])
def test_real_journal_original_source_cannot_be_promoted_from_nonoperator_kind(canonical_goal, source_kind):
    env = canonical_goal
    rewrite_event(env, env.user.event_id, source_kind=source_kind)
    with pytest.raises(DispatchError) as failure:
        delegation.read_goal_source(dict(env.runtime), env.reference)
    assert failure.value.code == "DELEGATION_SOURCE_UNAVAILABLE"


@pytest.mark.parametrize("change", ["proactive_payload", "agent_metadata", "system_metadata", "agent_actor",
                                   "foreign_start_agent", "invisible", "imported_source"])
def test_real_journal_provenance_flags_cannot_self_declare_operator(canonical_goal, change):
    env = canonical_goal
    payload = deepcopy(env.user.payload)
    if change == "foreign_start_agent":
        rewrite_event(env, env.start.event_id, payload={**env.start.payload, "agentId": "other-agent"})
    elif change == "invisible":
        rewrite_event(env, env.user.event_id, visible_in_model=False)
    elif change == "imported_source":
        rewrite_event(env, env.user.event_id, source="imported_transcript")
    else:
        if change == "proactive_payload":
            payload["source"] = "proactive"
            payload["metadata"].update(kind="proactive", proactive=True)
        elif change == "agent_metadata":
            payload["metadata"]["agentId"] = "assistant-a"
        elif change == "system_metadata":
            payload["metadata"]["system"] = True
        else:
            payload["metadata"]["actorType"] = "agent"
        rewrite_event(env, env.user.event_id, payload=payload)
    with pytest.raises(DispatchError) as failure:
        delegation.read_goal_source(dict(env.runtime), env.reference)
    assert failure.value.code == "DELEGATION_SOURCE_UNAVAILABLE"


@pytest.mark.parametrize("change", ["user_correlation", "start_correlation", "client_submission", "event_id",
                                   "content_hash", "span_hash", "range"])
def test_real_journal_correlation_event_and_hash_tampering_is_rejected(canonical_goal, change):
    env = canonical_goal
    reference = deepcopy(env.reference)
    if change == "user_correlation":
        rewrite_event(env, env.user.event_id, correlation_id="forged-submission")
    elif change == "start_correlation":
        rewrite_event(env, env.start.event_id, correlation_id="forged-start")
    elif change == "client_submission":
        payload = deepcopy(env.user.payload)
        payload["metadata"]["clientSubmissionId"] = "forged-client"
        rewrite_event(env, env.user.event_id, payload=payload)
    elif change == "event_id":
        reference["eventId"] = env.current_user.event_id
    elif change in {"content_hash", "span_hash"}:
        reference[{"content_hash": "contentHash", "span_hash": "spanHash"}[change]] = "0" * 64
    else:
        reference["end"] += 1
    with pytest.raises(DispatchError) as failure:
        delegation.read_goal_source(dict(env.runtime), reference)
    expected = "DELEGATION_SOURCE_CHANGED" if change in {"content_hash", "span_hash", "range"} else "DELEGATION_SOURCE_UNAVAILABLE"
    assert failure.value.code == expected


@pytest.mark.parametrize("change", ["reference_agent", "reference_session", "runtime_agent", "runtime_session",
                                   "runtime_turn", "directory_root", "sessions_root", "store_root", "closed_store"])
def test_real_journal_goal_cannot_cross_agent_session_runtime_or_native_root(canonical_goal, change):
    env = canonical_goal
    runtime, reference = dict(env.runtime), deepcopy(env.reference)
    if change.startswith("reference_"):
        reference[{"reference_agent": "agentId", "reference_session": "sessionId"}[change]] = "foreign"
    elif change.startswith("runtime_"):
        runtime[{"runtime_agent": "agentId", "runtime_session": "sessionId", "runtime_turn": "turnId"}[change]] = "foreign"
    elif change == "directory_root":
        env.directory.PROJECT_ROOT = env.root / "foreign"
    elif change == "sessions_root":
        env.sessions.PROJECT_ROOT = env.root / "foreign"
    elif change == "store_root":
        env.opened.directory_store_project_root = lambda: env.root / "foreign"
    else:
        env.opened.get_open_directory_store = lambda: None
    with pytest.raises(DispatchError) as failure:
        delegation.read_goal_source(runtime, reference)
    assert failure.value.code == "DELEGATION_IDENTITY_INVALID"


@pytest.mark.parametrize("terminal", sorted(journal.TERMINAL_EVENTS))
def test_real_current_terminal_event_revokes_goal_source_read(canonical_goal, terminal):
    env = canonical_goal
    journal.append_turn_event(env.root, "own-session", "proactive-turn", terminal, status="completed", visible_in_model=False)
    with pytest.raises(DispatchError) as failure:
        delegation.read_goal_source(dict(env.runtime), env.reference)
    assert failure.value.code == "DELEGATION_TURN_UNAVAILABLE"


@pytest.mark.parametrize("change", ["deleted_event", "deleted_turn", "corrupt_original", "deleted_journal"])
def test_removed_or_corrupt_original_source_is_not_recovered_from_cached_or_current_text(canonical_goal, change):
    env = canonical_goal
    assert delegation.read_goal_source(dict(env.runtime), env.reference) == env.reference
    if change in {"deleted_event", "deleted_turn"}:
        events = journal.load_turn_events(env.root, "own-session")
        journal.rewrite_turn_events(env.root, "own-session", [event for event in events
            if (event.event_id != env.user.event_id if change == "deleted_event" else event.turn_id != "operator-turn")])
    elif change == "corrupt_original":
        lines = env.path.read_text(encoding="utf-8").splitlines()
        env.path.write_text("\n".join("{invalid-original-event" if json.loads(line)["eventId"] == env.user.event_id else line
                                     for line in lines) + "\n", encoding="utf-8")
    else:
        env.path.unlink()
    with pytest.raises(DispatchError) as failure:
        delegation.read_goal_source(dict(env.runtime), env.reference)
    assert failure.value.code in {"DELEGATION_SOURCE_UNAVAILABLE", "DELEGATION_TURN_UNAVAILABLE"}
