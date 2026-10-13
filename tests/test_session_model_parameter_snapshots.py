"""Submission-time model parameter snapshots for session turns."""

from __future__ import annotations

import copy
import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.chat.conversation_ledger import EVENT_USER_MESSAGE, load_conversation_events
from core.web.services import session_service
from core.web.services.session import queued_turns, submit, worker
from tests.helpers.web_chat_state import (
    _bind_seeded_submittable_agent,
    _reset_seeded_session_runtime,
    _seed_chat_state,
)


@pytest.fixture
def seeded_session(tmp_path: Path, monkeypatch):
    """Seed session and Agent storage under pytest temp with a private config copy."""

    from core.web.services import agent_directory_service
    from core.web.services.session import admission

    # The shared helper may add a context_window to its config object. Keep that
    # change in a deep-copied test config rather than the operator config singleton.
    test_config = copy.deepcopy(session_service.get_config())
    monkeypatch.setattr(session_service, "get_config", lambda: test_config)
    monkeypatch.setattr("config.settings.get_config", lambda: test_config)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv(
        "VIBELUTION_SESSION_SQLITE_ADMISSION_ROOT",
        str(tmp_path / "admission-data"),
    )

    session_id = "session-live"
    _seed_chat_state(tmp_path)
    agent = _bind_seeded_submittable_agent(tmp_path, session_id=session_id)
    model_ref = str(session_service._resolve_session_agent_llm(agent, "dialogue").model_ref)
    try:
        yield session_id, agent, test_config, model_ref
    finally:
        _reset_seeded_session_runtime(session_id)
        admission.close_development_submission_admission_runtimes()


def _user_events_for_submission(project_root: Path, session_id: str, submission_id: str):
    return [
        event
        for event in load_conversation_events(project_root, session_id)
        if event.event_type == EVENT_USER_MESSAGE
        and str(((event.payload or {}).get("metadata") or {}).get("clientSubmissionId") or "")
        == submission_id
    ]


def _snapshot(agent: dict, model_ref: str, context_window: int, effort: str) -> dict:
    return {
        "agentId": agent["agentId"],
        "modelRef": model_ref,
        "configRevision": int(agent.get("configRevision") or 0),
        "contextWindow": context_window,
        "reasoningEffort": effort,
    }


def test_submit_freezes_parameters_at_acceptance_and_same_id_reuses_turn(
    seeded_session, monkeypatch
) -> None:
    session_id, agent, _config, model_ref = seeded_session
    accepted = _snapshot(agent, model_ref, 48_000, "medium")
    changed = _snapshot(agent, model_ref, 96_000, "high")
    current = {"value": accepted}
    captures: list[dict] = []

    def capture(_service, _conversation, **_kwargs):
        value = copy.deepcopy(current["value"])
        captures.append(value)
        return value

    scheduled: list[dict] = []
    monkeypatch.setattr(submit, "capture_model_parameters", capture)
    monkeypatch.setattr(
        session_service,
        "_session_context_limit_payload",
        lambda _conversation: {"limit": 200_000, "source": "test"},
    )
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: scheduled.append(dict(context)),
    )

    try:
        first = submit.submit_session_message_lightweight(
            session_id,
            "请继续检查",
            client_submission_id="snapshot-submit-1",
            mental_model_enabled=False,
        )

        # Guidance is inserted into the already-running turn. It must not open
        # a new turn or capture a second parameter set.
        submit.submit_session_guidance(session_id, "优先检查失败用例")

        # A configuration edit after acceptance must affect a new submission,
        # while a transport retry of this accepted id remains attached to turn 1.
        current["value"] = changed
        retried = submit.submit_session_message_lightweight(
            session_id,
            "请继续检查",
            client_submission_id="snapshot-submit-1",
            mental_model_enabled=False,
        )

        accepted_events = _user_events_for_submission(
            session_service.PROJECT_ROOT, session_id, "snapshot-submit-1"
        )
        assert first["turnId"]
        assert retried["turnId"] == first["turnId"]
        assert len(scheduled) == 1
        assert len(captures) == 1
        assert scheduled[0]["model_parameters"] == accepted
        assert len(accepted_events) == 1
        assert accepted_events[0].payload["metadata"]["modelParameters"] == accepted
    finally:
        _reset_seeded_session_runtime(session_id)


def test_regenerate_captures_current_parameters_and_deduplicates_request_id(
    seeded_session, monkeypatch
) -> None:
    session_id, agent, _config, model_ref = seeded_session
    latest = _snapshot(agent, model_ref, 72_000, "high")
    later = _snapshot(agent, model_ref, 36_000, "low")
    current = {"value": latest}
    captures: list[dict] = []

    def capture(_service, _conversation, **_kwargs):
        result = copy.deepcopy(current["value"])
        captures.append(result)
        return result

    scheduled: list[dict] = []
    monkeypatch.setattr(submit, "capture_model_parameters", capture)
    monkeypatch.setattr(
        session_service,
        "_session_context_limit_payload",
        lambda _conversation: {"limit": 200_000, "source": "test"},
    )
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: scheduled.append(dict(context)),
    )
    visible_messages = session_service._session_ledger_visible_messages(session_id)
    target_user = next(message for message in visible_messages if message.get("role") == "user")

    try:
        first = submit.regenerate_session_message(
            session_id,
            str(target_user["id"]),
            mental_model_enabled=False,
            client_submission_id="snapshot-regenerate-1",
        )

        current["value"] = later
        retried = submit.regenerate_session_message(
            session_id,
            str(target_user["id"]),
            mental_model_enabled=False,
            client_submission_id="snapshot-regenerate-1",
        )

        accepted_events = _user_events_for_submission(
            session_service.PROJECT_ROOT, session_id, "snapshot-regenerate-1"
        )
        assert first["messages"]
        assert retried["messages"]
        assert len(scheduled) == 1
        assert len(captures) == 1
        assert scheduled[0]["model_parameters"] == latest
        assert len(accepted_events) == 1
        assert accepted_events[0].payload["metadata"]["modelParameters"] == latest
    finally:
        _reset_seeded_session_runtime(session_id)


def test_concurrent_regenerate_same_id_waits_for_first_user_marker(
    seeded_session, monkeypatch
) -> None:
    session_id, agent, _config, model_ref = seeded_session
    accepted = _snapshot(agent, model_ref, 72_000, "high")
    capture_calls: list[dict] = []
    scheduled: list[dict] = []
    first_marker_entered = threading.Event()
    release_first_marker = threading.Event()
    append_guard = threading.Lock()
    marker_calls = {"count": 0}
    original_append = session_service._append_session_conversation_event

    def capture(_service, _conversation, **_kwargs):
        result = copy.deepcopy(accepted)
        capture_calls.append(result)
        return result

    def pause_first_marker(*args, **kwargs):
        metadata = (kwargs.get("payload") or {}).get("metadata") or {}
        if (
            kwargs.get("source") == "regenerate_session_message"
            and metadata.get("clientSubmissionId") == "snapshot-concurrent-regenerate"
        ):
            with append_guard:
                marker_calls["count"] += 1
                is_first = marker_calls["count"] == 1
            if is_first:
                first_marker_entered.set()
                if not release_first_marker.wait(timeout=5):
                    raise TimeoutError("test did not release the first regenerate marker")
        return original_append(*args, **kwargs)

    monkeypatch.setattr(submit, "capture_model_parameters", capture)
    monkeypatch.setattr(
        session_service,
        "_session_context_limit_payload",
        lambda _conversation: {"limit": 200_000, "source": "test"},
    )
    monkeypatch.setattr(session_service, "_append_session_conversation_event", pause_first_marker)
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: scheduled.append(dict(context)),
    )
    visible_messages = session_service._session_ledger_visible_messages(session_id)
    target_user = next(message for message in visible_messages if message.get("role") == "user")

    def regenerate():
        return submit.regenerate_session_message(
            session_id,
            str(target_user["id"]),
            mental_model_enabled=False,
            client_submission_id="snapshot-concurrent-regenerate",
        )

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(regenerate)
            assert first_marker_entered.wait(timeout=5), "first request did not reach its user marker"
            second = pool.submit(regenerate)

            # While the first acceptance has not journaled its user marker,
            # the second same-id request must still be waiting at admission.
            with pytest.raises(FutureTimeoutError):
                second.result(timeout=0.2)
            assert scheduled == []

            release_first_marker.set()
            first_result = first.result(timeout=5)
            second_result = second.result(timeout=5)

        assert first_result["messages"]
        assert second_result["messages"]
        assert marker_calls["count"] == 1
        assert len(capture_calls) == 1
        assert len(scheduled) == 1
        assert scheduled[0]["model_parameters"] == accepted
    finally:
        release_first_marker.set()
        _reset_seeded_session_runtime(session_id)


def test_queued_turn_keeps_accepted_snapshot_through_pause_resume_send_now_and_drain(
    seeded_session, monkeypatch
) -> None:
    session_id, agent, _config, model_ref = seeded_session
    first_snapshot = _snapshot(agent, model_ref, 64_000, "medium")
    second_snapshot = _snapshot(agent, model_ref, 32_000, "low")
    edited_snapshot = _snapshot(agent, model_ref, 16_000, "high")
    current = {"value": first_snapshot}
    captures: list[dict] = []

    def capture(_service, _conversation, **_kwargs):
        result = copy.deepcopy(current["value"])
        captures.append(result)
        return result

    monkeypatch.setattr(submit, "capture_model_parameters", capture)
    monkeypatch.setattr(queued_turns, "capture_model_parameters", capture)
    monkeypatch.setattr(
        session_service,
        "_session_context_limit_payload",
        lambda _conversation: {"limit": 200_000, "source": "test"},
    )
    monkeypatch.setattr(session_service, "_schedule_session_queued_turn_drain", lambda _sid: None)
    scheduled: list[dict] = []
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: scheduled.append(dict(context)),
    )

    active_turn_id = "active-turn-for-queue-test"
    session_service._create_session_turn_control(session_id, turn_id=active_turn_id)
    session_service._set_session_running(session_id, True, turn_id=active_turn_id)
    try:
        submit.submit_session_message_lightweight(
            session_id,
            "排队消息一",
            client_submission_id="snapshot-queue-1",
            queue_if_busy=True,
            mental_model_enabled=False,
        )
        current["value"] = second_snapshot
        submit.submit_session_message_lightweight(
            session_id,
            "排队消息二",
            client_submission_id="snapshot-queue-2",
            queue_if_busy=True,
            mental_model_enabled=False,
        )

        first_row = next(
            row
            for row in queued_turns.list_session_queued_turns(session_id)
            if row.get("clientSubmissionId") == "snapshot-queue-1"
        )
        second_row = next(
            row
            for row in queued_turns.list_session_queued_turns(session_id)
            if row.get("clientSubmissionId") == "snapshot-queue-2"
        )
        assert first_row["modelParameters"] == first_snapshot
        assert second_row["modelParameters"] == second_snapshot

        # Pausing and resuming changes delivery order only. It does not recapture
        # parameters, even after the Agent's current setting has changed.
        queued_turns.update_session_queued_turn(
            session_id, first_row["id"], status="paused"
        )
        current["value"] = edited_snapshot
        resumed = queued_turns.update_session_queued_turn(
            session_id, first_row["id"], status="queued"
        )
        assert [row["clientSubmissionId"] for row in resumed] == [
            "snapshot-queue-2",
            "snapshot-queue-1",
        ]

        def stop_active_turn(_sid, **_kwargs):
            session_service._set_session_running(_sid, False, turn_id=active_turn_id)
            session_service._clear_session_turn_control(_sid, turn_id=active_turn_id)
            return {"stopped": True}

        monkeypatch.setattr(session_service, "request_stop_session_turn", stop_active_turn)
        promoted = queued_turns.send_now_session_queued_turn(session_id, first_row["id"])
        assert promoted["stopRequested"] is True
        assert promoted["queuedTurns"][0]["modelParameters"] == first_snapshot
        assert promoted["queuedTurns"][0]["sendNow"] is True

        assert queued_turns.drain_session_queued_turns(session_id) is True

        assert len(captures) == 2
        assert len(scheduled) == 1
        assert scheduled[0]["model_parameters"] == first_snapshot
        assert scheduled[0]["user_message"] == "排队消息一"
        remaining = queued_turns.list_session_queued_turns(session_id)
        assert [row["clientSubmissionId"] for row in remaining] == ["snapshot-queue-2"]
    finally:
        _reset_seeded_session_runtime(session_id)


def test_blocked_queue_retry_requires_failed_receipt_and_refreshes_snapshot(
    seeded_session, monkeypatch
) -> None:
    session_id, agent, _config, model_ref = seeded_session
    original = _snapshot(agent, model_ref, 80_000, "medium")
    current = _snapshot(agent, model_ref, 40_000, "high")
    captures: list[dict] = []

    def capture(_service, _conversation, **_kwargs):
        result = copy.deepcopy(current)
        captures.append(result)
        return result

    monkeypatch.setattr(queued_turns, "capture_model_parameters", capture)
    monkeypatch.setattr(session_service, "_schedule_session_queued_turn_drain", lambda _sid: None)
    row = queued_turns.enqueue_session_queued_turn(
        session_id,
        content="失败后重试",
        attachments=[],
        references=[],
        mental_model_enabled=False,
        runtime_status_enabled=None,
        turn_mode="",
        write_intent=None,
        client_submission_id="snapshot-blocked-1",
        model_parameters=original,
    )
    monkeypatch.setattr(
        session_service,
        "submit_session_message",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("scheduled submit failed")),
    )

    try:
        assert queued_turns.drain_session_queued_turns(session_id) is True
        blocked = queued_turns.list_session_queued_turns(session_id)[0]
        assert blocked["status"] == "blocked"
        assert blocked["modelParameters"] == original

        monkeypatch.setattr(
            submit,
            "_queued_submission_retry_state",
            lambda *_args, **_kwargs: "unknown",
        )
        with pytest.raises(session_service.SessionValidationError):
            queued_turns.update_session_queued_turn(session_id, row["id"], content="改后重试")
        assert queued_turns.list_session_queued_turns(session_id)[0]["modelParameters"] == original
        assert captures == []

        monkeypatch.setattr(
            submit,
            "_queued_submission_retry_state",
            lambda *_args, **_kwargs: "failed",
        )
        retried_rows = queued_turns.update_session_queued_turn(
            session_id, row["id"], content="改后重试"
        )
        retried = retried_rows[0]
        assert retried["status"] == "queued"
        assert retried["dispatchClientSubmissionId"] != "snapshot-blocked-1"
        assert retried["modelParameters"] == current
        assert captures == [current]
    finally:
        _reset_seeded_session_runtime(session_id)


def test_worker_preparation_uses_the_accepted_agent_model_parameters(
    seeded_session, monkeypatch, tmp_path: Path
) -> None:
    session_id, seeded_agent, _config, model_ref = seeded_session
    accepted = _snapshot(seeded_agent, model_ref, 56_000, "high")
    base_agent = {**copy.deepcopy(seeded_agent), "workspacePath": ""}
    observed: dict = {}

    class _Decision:
        effective_enabled = False

    def capture_resolved_agent(agent, llm_slot, *, reasoning_effort=None):
        observed["agent"] = copy.deepcopy(agent)
        observed["slot"] = llm_slot
        observed["reasoning_effort"] = reasoning_effort
        raise session_service.SessionValidationError("stop before provider invocation")

    monkeypatch.setattr(session_service, "_is_session_turn_current", lambda *_args: True)
    monkeypatch.setattr(session_service, "_normalize_optional_bool", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(session_service, "resolve_feature_decision", lambda *_args, **_kwargs: _Decision())
    monkeypatch.setattr(worker, "_abort_session_turn_for_stop", lambda **_kwargs: False)
    monkeypatch.setattr(session_service, "_ensure_session_workspace", lambda *_args: tmp_path)
    monkeypatch.setattr(session_service, "_sync_agent_directory_project_root", lambda: None)
    monkeypatch.setattr(
        session_service,
        "get_agent",
        lambda _agent_id, **_kwargs: copy.deepcopy(base_agent),
    )
    monkeypatch.setattr(session_service, "_supervised_role_for_runtime_context", lambda *_args: "")
    monkeypatch.setattr(session_service, "_supervised_runtime_tool_grants_for_context", lambda *_args: None)
    monkeypatch.setattr(session_service, "_supervised_workspace_override_path", lambda *_args: None)
    monkeypatch.setattr(session_service, "_ensure_session_agent_prompt_snapshot", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(session_service, "_render_agent_prompt_snapshot_block", lambda *_args: "")
    monkeypatch.setattr(session_service, "_normalize_message_attachments", lambda *_args: [])
    monkeypatch.setattr(
        session_service,
        "_lightweight_chat_payload_decision",
        lambda *_args, **_kwargs: (False, "test"),
    )
    monkeypatch.setattr(session_service, "build_agent_context", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(session_service, "resolve_memory_policy_for_agent", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        session_service,
        "evaluate_agent_workspace_write",
        lambda *_args, **_kwargs: SimpleNamespace(allowed=True, reason=""),
    )
    monkeypatch.setattr(session_service, "sync_llm_key_env_from_persisted_user_env", lambda **_kwargs: {"ok": True})
    monkeypatch.setattr(session_service, "_resolve_session_agent_llm", capture_resolved_agent)
    monkeypatch.setattr(session_service, "_extract_missing_agent_llm_model_id", lambda *_args: "")
    monkeypatch.setattr(session_service, "_make_local_runtime_turn_error", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(session_service, "_persist_session_turn_runtime_error", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(session_service, "_record_session_turn_lifecycle_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(session_service, "_set_session_running", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(session_service, "_clear_session_turn_control", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(session_service, "_publish_session_detail_snapshot", lambda *_args, **_kwargs: None)

    context = {
        "session_id": session_id,
        "turn_id": "turn-accepted-model-parameters",
        "turn_control": session_service.SessionTurnControl(
            session_id=session_id,
            turn_id="turn-accepted-model-parameters",
        ),
        "agent_id": seeded_agent["agentId"],
        "agent_snapshot": base_agent,
        "model_parameters": accepted,
        "user_message": "继续",
        "mental_model_enabled": False,
        "llm_slot": "dialogue",
    }

    worker._run_session_turn_impl(context)

    pinned = observed["agent"]
    assert observed["slot"] == "dialogue"
    assert observed["reasoning_effort"] == "high"
    assert pinned["llmBindings"]["dialogue"]["modelId"] == accepted["modelRef"]
    assert pinned["metadata"]["llmModelParameters"][accepted["modelRef"]] == {
        "contextWindow": 56_000,
        "reasoningEffort": "high",
    }
    assert "llmModelParameters" not in base_agent.get("metadata", {})


def test_capture_uses_supplied_frozen_agent_for_all_parameters_without_live_reread() -> None:
    from core.web.services.session.turn_model_parameters import capture_model_parameters

    agent_id = "agent-snapshot-capture"
    old_model_ref = "provider/old-model"
    new_model_ref = "provider/new-model"
    frozen_agent = {
        "agentId": agent_id,
        "configRevision": 7,
        "displayName": "Frozen Agent",
        "permissionPreset": "safe",
        "llmBindings": {"dialogue": {"modelId": old_model_ref}},
        "metadata": {
            "llmModelParameters": {
                old_model_ref: {"contextWindow": 12_345, "reasoningEffort": "high"},
            },
            "snapshotMarker": "old-complete-config",
        },
    }
    live_agent = copy.deepcopy(frozen_agent)
    live_agent.update(configRevision=8, displayName="New Agent", permissionPreset="full")
    live_agent["llmBindings"]["dialogue"]["modelId"] = new_model_ref
    live_agent["metadata"] = {
        "llmModelParameters": {
            new_model_ref: {"contextWindow": 98_765, "reasoningEffort": "low"},
        },
        "snapshotMarker": "new-complete-config",
    }

    resolved_agents: list[dict] = []
    context_agents: list[dict] = []
    get_agent_calls = 0

    def get_live_agent(_agent_id: str, **_kwargs):
        nonlocal get_agent_calls
        get_agent_calls += 1
        return copy.deepcopy(live_agent)

    def resolve_agent_llm(agent: dict, slot: str):
        resolved_agents.append(copy.deepcopy(agent))
        model_ref = agent["llmBindings"][slot]["modelId"]
        parameters = agent["metadata"]["llmModelParameters"][model_ref]
        return SimpleNamespace(
            model_ref=model_ref,
            reasoning_effort_requested=parameters["reasoningEffort"],
        )

    def resolve_context_window(conversation: dict):
        context_agent = conversation["_agent"]
        context_agents.append(copy.deepcopy(context_agent))
        model_ref = context_agent["llmBindings"]["dialogue"]["modelId"]
        return {
            "limit": context_agent["metadata"]["llmModelParameters"][model_ref]["contextWindow"],
        }

    service = SimpleNamespace(
        agent_directory_service=SimpleNamespace(_STATE_LOCK=threading.RLock()),
        get_agent=get_live_agent,
        _resolve_session_agent_llm=resolve_agent_llm,
        _session_context_limit_payload=resolve_context_window,
        SessionValidationError=ValueError,
    )
    frozen_before = copy.deepcopy(frozen_agent)
    live_before = copy.deepcopy(live_agent)

    snapshot = capture_model_parameters(
        service,
        {"agent_id": agent_id},
        agent=frozen_agent,
    )

    assert get_agent_calls == 0
    assert resolved_agents == [frozen_before]
    assert context_agents == [frozen_before]
    assert snapshot == {
        "agentId": agent_id,
        "modelRef": old_model_ref,
        "configRevision": 7,
        "contextWindow": 12_345,
        "reasoningEffort": "high",
    }
    assert frozen_agent == frozen_before
    assert live_agent == live_before
