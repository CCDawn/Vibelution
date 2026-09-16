"""Focused tests for session submit slice (pure helpers + facade re-export)."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from core.chat.conversation_ledger import (
    EVENT_TURN_STARTED,
    EVENT_USER_MESSAGE,
    append_conversation_event,
    load_conversation_events,
)
from core.logging.trace_context import bind_trace_context, new_trace_context
from core.web.services import session_service
from core.web.services.session import submit
from tests.helpers.web_chat_state import (
    _bind_seeded_submittable_agent,
    _reset_seeded_session_runtime,
    _seed_chat_state,
)


def test_resolve_user_message_content_plain_and_base64() -> None:
    assert submit._resolve_user_message_content("  hello  ") == "hello"
    import base64

    encoded = base64.b64encode("你好".encode()).decode("ascii")
    assert submit._resolve_user_message_content("", content_utf8_base64=encoded) == "你好"
    # invalid base64 falls back to content
    assert submit._resolve_user_message_content("fallback", content_utf8_base64="%%%") == "fallback"


def test_accepted_session_turn_payload_shape() -> None:
    payload = submit._accepted_session_turn_payload(
        "sess-1",
        "turn-1",
        status="running",
        client_submission_id="client-xyz",
    )
    assert payload["accepted"] is True
    assert payload["sessionId"] == "sess-1"
    assert payload["turnId"] == "turn-1"
    assert payload["status"] == "running"
    assert payload["clientSubmissionId"] == "client-xyz"
    assert payload["acceptedAt"]


def test_facade_reexports_submit_entrypoints() -> None:
    assert session_service.submit_session_message is submit.submit_session_message
    assert session_service.submit_session_message_lightweight is submit.submit_session_message_lightweight
    assert session_service.edit_and_resubmit_session_message is submit.edit_and_resubmit_session_message
    assert session_service.regenerate_session_message is submit.regenerate_session_message
    assert session_service.submit_session_guidance is submit.submit_session_guidance


def test_turn_started_is_deferred_fsync_event() -> None:
    from core.chat import turn_journal

    assert turn_journal.EVENT_TURN_STARTED in turn_journal.DEFERRED_FSYNC_EVENT_TYPES
    assert turn_journal.EVENT_USER_MESSAGE not in turn_journal.DEFERRED_FSYNC_EVENT_TYPES


def test_initial_journal_markers_keep_the_journal_as_the_only_transcript(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("VIBELUTION_SESSION_SQLITE_ADMISSION_ROOT", raising=False)

    receipt = submit._append_initial_session_journal_markers(
        session_id="session-a",
        turn_id="turn-a",
        client_submission_id="submission-a",
        agent={"agentId": "agent-a", "displayName": "Agent A"},
        conversation={"title": "Session A"},
        source="raw",
        leases=["readonly_chat"],
        user_payload={"content": "hello", "metadata": {"clientSubmissionId": "submission-a"}},
    )

    events = load_conversation_events(tmp_path, "session-a")
    assert [event.event_type for event in events] == [EVENT_TURN_STARTED, EVENT_USER_MESSAGE]
    assert receipt["turnId"] == "turn-a"
    assert receipt["journalSequence"] == events[-1].sequence
    assert receipt["journalEventId"] == events[-1].event_id


def test_development_submit_bridge_reuses_the_journaled_submission(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from core.web.services.session import admission

    project_root = tmp_path / "project"
    monkeypatch.setattr(session_service, "PROJECT_ROOT", project_root)
    monkeypatch.setenv(
        "VIBELUTION_SESSION_SQLITE_ADMISSION_ROOT",
        str(tmp_path / "development-data"),
    )
    arguments = {
        "session_id": "session-a",
        "client_submission_id": "submission-a",
        "agent": {"agentId": "agent-a", "displayName": "Agent A"},
        "conversation": {"title": "Session A"},
        "source": "raw",
        "leases": ["readonly_chat"],
        "user_payload": {"content": "hello", "metadata": {"clientSubmissionId": "submission-a"}},
    }
    try:
        first = submit._append_initial_session_journal_markers(turn_id="turn-a", **arguments)
        second = submit._append_initial_session_journal_markers(turn_id="turn-new", **arguments)

        assert first["admissionDisposition"] == "appended"
        assert second["admissionDisposition"] == "already_journaled"
        assert second["turnId"] == "turn-a"
        assert [event.event_type for event in load_conversation_events(project_root, "session-a")] == [
            EVENT_TURN_STARTED,
            EVENT_USER_MESSAGE,
        ]
    finally:
        admission.close_development_submission_admission_runtimes()


def test_development_submit_bridge_recovers_partial_marker_without_duplicate_turn_start(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Retry after a partial marker append keeps the initial process chain singular."""

    from core.web.services.session import admission

    project_root = tmp_path / "project"
    monkeypatch.setattr(session_service, "PROJECT_ROOT", project_root)
    monkeypatch.setenv(
        "VIBELUTION_SESSION_SQLITE_ADMISSION_ROOT",
        str(tmp_path / "development-data"),
    )
    append_conversation_event(
        project_root,
        "session-a",
        "turn-a",
        EVENT_TURN_STARTED,
        status="running",
        correlation_id="submission-a",
        visible_in_model=False,
    )
    try:
        receipt = submit._append_initial_session_journal_markers(
            session_id="session-a",
            turn_id="turn-a",
            client_submission_id="submission-a",
            agent={"agentId": "agent-a", "displayName": "Agent A"},
            conversation={"title": "Session A"},
            source="raw",
            leases=["readonly_chat"],
            user_payload={"content": "hello", "metadata": {"clientSubmissionId": "submission-a"}},
        )

        events = load_conversation_events(project_root, "session-a")
        assert receipt["admissionDisposition"] == "appended"
        assert [event.event_type for event in events] == [
            EVENT_TURN_STARTED,
            EVENT_USER_MESSAGE,
        ]
    finally:
        admission.close_development_submission_admission_runtimes()


def test_submit_entrypoint_reuses_one_journal_backed_turn_in_development_mode(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A browser retry reuses the journal-backed admission, not transcript rows."""

    from core.web.services import agent_directory_service
    from core.web.services.session import admission

    session_id = "session-live"
    development_root = tmp_path / "development-data"
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv(
        "VIBELUTION_SESSION_SQLITE_ADMISSION_ROOT",
        str(development_root),
    )
    _seed_chat_state(tmp_path)
    _bind_seeded_submittable_agent(tmp_path, session_id=session_id)
    scheduled_contexts: list[dict] = []
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: scheduled_contexts.append(dict(context)),
    )

    try:
        first = submit.submit_session_message_lightweight(
            session_id,
            "development journal bridge",
            client_submission_id="submission-development-1",
            mental_model_enabled=False,
        )
        retried = submit.submit_session_message_lightweight(
            session_id,
            "development journal bridge",
            client_submission_id="submission-development-1",
            mental_model_enabled=False,
        )

        matching_events = [
            event
            for event in load_conversation_events(tmp_path, session_id)
            if event.correlation_id == "submission-development-1"
        ]
        assert first["turnId"]
        assert retried["accepted"] is True
        assert retried["turnId"] == first["turnId"]
        assert [event.event_type for event in matching_events] == [
            EVENT_TURN_STARTED,
            EVENT_USER_MESSAGE,
        ]
        assert [context["turn_id"] for context in scheduled_contexts] == [first["turnId"]]
        assert (
            development_root / "conversation-control" / "session_admission.sqlite3"
        ).is_file()
    finally:
        _reset_seeded_session_runtime(session_id)
        admission.close_development_submission_admission_runtimes()


def test_submit_scheduled_context_carries_trace_context_carrier(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session_id = "session-trace-carrier"
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_chat_state(tmp_path)
    _bind_seeded_submittable_agent(tmp_path, session_id=session_id)
    scheduled_contexts: list[dict] = []
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: scheduled_contexts.append(dict(context)),
    )
    carrier = new_trace_context(request_id="submit-request").to_carrier()

    try:
        result = submit.submit_session_message_lightweight(
            session_id,
            "trace carrier",
            client_submission_id="submission-trace-carrier",
            trace_context_carrier=carrier,
            mental_model_enabled=False,
        )

        assert result["accepted"] is True
        assert scheduled_contexts
        assert scheduled_contexts[0]["trace_context_carrier"] == carrier
    finally:
        _reset_seeded_session_runtime(session_id)


def test_initial_source_stage_submit_carries_only_ephemeral_challenge_deadline(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from core.web.services.team_workflow.research_runtime.challenge_turn_policy import (
        challenge_task_deadline_scope,
    )
    from core.web.services.team_workflow.source_collection import stage_session

    session_id = "session-source-stage-deadline"
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_chat_state(tmp_path)
    _bind_seeded_submittable_agent(tmp_path, session_id=session_id)
    scheduled_contexts: list[dict] = []
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: scheduled_contexts.append(dict(context)),
    )
    monkeypatch.setattr(
        stage_session,
        "_read_source_collection_stage_session_task_record",
        lambda team_id, task_id: {
            "taskId": task_id,
            "teamId": team_id,
            "challengeTaskContract": {
                "workflowRunId": "workflow-1",
                "nodeRunId": "node-1",
            },
        },
    )

    try:
        with challenge_task_deadline_scope(1_000):
            result = submit.submit_session_message(
                session_id,
                "start formal source stage",
                client_submission_id="submission-source-stage-deadline",
                mental_model_enabled=False,
                message_source="agent_inbox",
                message_metadata={
                    "kind": "source_collection_stage_session_task",
                    "teamId": "team-1",
                    "sourceCollectionStageTaskId": "stage-task-1",
                },
                include_started_turn_id=True,
                lightweight_response=True,
            )

        from core.web.services.team_workflow.research_runtime.challenge_turn_policy import (
            CHALLENGE_LOGICAL_TASK_TIMEOUT_MS,
        )

        assert result["accepted"] is True
        assert (
            scheduled_contexts[0]["_challenge_task_deadline_at_ms"]
            == 1_000 + CHALLENGE_LOGICAL_TASK_TIMEOUT_MS
        )
        assert "_challenge_task_deadline_at_ms" not in scheduled_contexts[0]["message_metadata"]
    finally:
        _reset_seeded_session_runtime(session_id)


def test_continuation_submit_carries_same_ephemeral_challenge_deadline(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from core.web.services.team_workflow.research_runtime.challenge_turn_policy import (
        challenge_task_deadline_scope,
    )

    session_id = "session-continuation-deadline"
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_chat_state(tmp_path)
    _bind_seeded_submittable_agent(tmp_path, session_id=session_id)
    scheduled_contexts: list[dict] = []
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: scheduled_contexts.append(dict(context)),
    )

    try:
        with challenge_task_deadline_scope(2_000):
            result = submit.submit_session_message(
                session_id,
                "继续",
                client_submission_id="submission-continuation-deadline",
                mental_model_enabled=False,
                message_source="agent_inbox",
                message_metadata={
                    "sourceSurface": "team_workflow_agent_turn_continuation",
                    "workflowRunId": "workflow-1",
                    "nodeRunId": "node-1",
                },
                include_started_turn_id=True,
                lightweight_response=True,
            )

        assert result["accepted"] is True
        from core.web.services.team_workflow.research_runtime.challenge_turn_policy import (
            CHALLENGE_LOGICAL_TASK_TIMEOUT_MS,
        )

        assert (
            scheduled_contexts[0]["_challenge_task_deadline_at_ms"]
            == 2_000 + CHALLENGE_LOGICAL_TASK_TIMEOUT_MS
        )
        assert "_challenge_task_deadline_at_ms" not in scheduled_contexts[0]["message_metadata"]
    finally:
        _reset_seeded_session_runtime(session_id)


def test_session_lifecycle_event_prefers_explicit_trace_carrier(monkeypatch) -> None:
    current_context = new_trace_context(request_id="current-request")
    carrier_context = new_trace_context(request_id="carrier-request")
    recorded: list[dict] = []

    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded.append(dict(kwargs)),
    )

    with bind_trace_context(current_context):
        session_service._record_session_turn_lifecycle_event(
            "session-trace-lifecycle",
            "scheduled",
            turn_id="turn-trace-lifecycle",
            trace_context_carrier=carrier_context.to_carrier(),
        )

    assert len(recorded) == 1
    expected = carrier_context.to_fields()
    for payload_name in ("fields", "child_log_payload"):
        payload = recorded[0][payload_name]
        for field_name, expected_value in expected.items():
            assert payload[field_name] == expected_value
        assert payload["traceId"] != current_context.trace_id
        assert payload["spanId"] != current_context.span_id
        assert payload["requestId"] != current_context.request_id


def test_steer_guidance_stays_in_model_history_but_is_not_editable() -> None:
    original = {
        "role": "user",
        "content": "do the work",
        "metadata": {"kind": "journal_user_message"},
    }
    steer = {
        "role": "user",
        "content": "line1\nline2\nline3 keep me",
        "metadata": {"kind": "user_guidance", "source": "steer"},
    }
    assert session_service._is_real_user_message_entry(original) is True
    assert session_service._is_real_user_message_entry(steer) is False
    assert session_service._is_steer_guidance_message_entry(steer) is True
    assert session_service._should_omit_message_from_agent_history(steer) is False
    messages = [original, {"role": "assistant", "content": "working"}, steer]
    assert session_service._latest_user_message_index(messages) == 0


def _chat_state_lock_held() -> bool:
    lock = session_service._CHAT_STATE_LOCK
    return bool(getattr(lock._local, "transactions", None))


def _seed_submittable_sessions(tmp_path: Path, session_ids: list[str]) -> None:
    conversations = [
        {
            "conversation_id": session_id,
            "title": session_id,
            "updated_at": "2026-05-18T12:00:00",
            "last_turn_status": "ready",
            "messages": [
                {
                    "role": "user",
                    "content": "seed",
                    "timestamp": "2026-05-18T11:55:00",
                }
            ],
        }
        for session_id in session_ids
    ]
    _seed_chat_state(tmp_path, conversations=conversations)
    for session_id in session_ids:
        _bind_seeded_submittable_agent(tmp_path, session_id=session_id)


def test_new_turn_ledger_io_runs_outside_chat_state_lock(tmp_path: Path, monkeypatch) -> None:
    from core.web.services import agent_directory_service

    session_id = "session-live"
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _seed_submittable_sessions(tmp_path, [session_id])
    held_during_ledger: list[tuple[str, bool]] = []

    def fake_reconcile(target_session_id, **kwargs):
        held_during_ledger.append(("reconcile", _chat_state_lock_held()))
        assert kwargs.get("reason") == "new_turn_submitted"
        assert target_session_id == session_id

    def fake_visible(target_session_id):
        held_during_ledger.append(("visible", _chat_state_lock_held()))
        assert target_session_id == session_id
        return []

    monkeypatch.setattr(session_service, "_reconcile_stale_session_ledger", fake_reconcile)
    monkeypatch.setattr(session_service, "_session_ledger_visible_messages", fake_visible)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)

    try:
        result = submit.submit_session_message_lightweight(
            session_id,
            "outside lock",
            mental_model_enabled=False,
        )
        assert result["accepted"] is True
        assert held_during_ledger == [("reconcile", False), ("visible", False)]
    finally:
        _reset_seeded_session_runtime(session_id)


def test_same_session_second_submit_stays_busy(tmp_path: Path, monkeypatch) -> None:
    from core.web.services import agent_directory_service

    session_id = "session-live"
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _seed_submittable_sessions(tmp_path, [session_id])
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)

    try:
        first = submit.submit_session_message_lightweight(
            session_id,
            "first turn",
            mental_model_enabled=False,
        )
        assert first["accepted"] is True
        with pytest.raises(session_service.SessionBusyError) as exc_info:
            submit.submit_session_message_lightweight(
                session_id,
                "second turn",
                mental_model_enabled=False,
            )
        message = str(exc_info.value)
        assert "仍在运行" in message or "still running" in message.lower()
    finally:
        _reset_seeded_session_runtime(session_id)


def test_parallel_session_submits_do_not_serialize_on_ledger_io(tmp_path: Path, monkeypatch) -> None:
    from core.web.services import agent_directory_service

    session_ids = ["session-a", "session-b", "session-c"]
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _seed_submittable_sessions(tmp_path, session_ids)

    barrier = threading.Barrier(len(session_ids))
    held_during_ledger: list[bool] = []
    accepted_timings: list[dict] = []
    results: dict[str, object] = {}
    errors: list[BaseException] = []

    def slow_reconcile(session_id, **kwargs):
        held_during_ledger.append(_chat_state_lock_held())
        barrier.wait(timeout=2)
        time.sleep(0.15)

    def capture_accepted(context, timing_fields):
        accepted_timings.append(dict(timing_fields))

    monkeypatch.setattr(session_service, "_reconcile_stale_session_ledger", slow_reconcile)
    monkeypatch.setattr(session_service, "_session_ledger_visible_messages", lambda session_id: [])
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)
    monkeypatch.setattr(session_service, "_record_session_turn_accepted_event", capture_accepted)

    def submit_one(session_id: str) -> None:
        try:
            results[session_id] = submit.submit_session_message_lightweight(
                session_id,
                f"parallel {session_id}",
                mental_model_enabled=False,
            )
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=submit_one, args=(session_id,), daemon=True)
        for session_id in session_ids
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    try:
        assert errors == []
        assert all(thread.is_alive() is False for thread in threads)
        assert all(isinstance(results.get(session_id), dict) and results[session_id]["accepted"] for session_id in session_ids)
        # Reaching the shared barrier means the 150ms ledger sleeps overlapped.
        # Holding _CHAT_STATE_LOCK across that I/O would deadlock the barrier.
        assert held_during_ledger == [False, False, False]
        assert len(accepted_timings) == 3
        assert all(int(item.get("chatStateLockWaitMs") or 0) == 0 for item in accepted_timings)
        remaining_ids = {
            str(item.get("conversation_id") or "")
            for item in session_service.load_chat_state(tmp_path).get("conversations") or []
            if isinstance(item, dict)
        }
        assert remaining_ids == set(session_ids)
    finally:
        for session_id in session_ids:
            _reset_seeded_session_runtime(session_id)


def test_submit_uses_session_row_io_and_keeps_siblings(tmp_path: Path, monkeypatch) -> None:
    from core.web.services import agent_directory_service

    session_ids = ["session-a", "session-b"]
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _seed_submittable_sessions(tmp_path, session_ids)
    monkeypatch.setattr(session_service, "_schedule_session_turn", lambda context: None)

    document_loads: list[str] = []
    document_saves: list[int] = []
    original_load = session_service.load_chat_state
    original_save = session_service.save_chat_state

    def spy_load(project_root):
        document_loads.append("load")
        return original_load(project_root)

    def spy_save(project_root, state, **kwargs):
        conversations = state.get("conversations") if isinstance(state, dict) else []
        document_saves.append(len(conversations) if isinstance(conversations, list) else -1)
        return original_save(project_root, state, **kwargs)

    monkeypatch.setattr(session_service, "load_chat_state", spy_load)
    monkeypatch.setattr(session_service, "save_chat_state", spy_save)
    before_b = session_service.load_session_chat_state(tmp_path, "session-b")

    try:
        result = submit.submit_session_message_lightweight(
            "session-a",
            "row io",
            mental_model_enabled=False,
        )
        after_b = session_service.load_session_chat_state(tmp_path, "session-b")
        after_a = session_service.load_session_chat_state(tmp_path, "session-a")
        assert result["accepted"] is True
        assert document_loads == []
        assert document_saves == []
        assert after_b["title"] == before_b["title"]
        assert after_b["updated_at"] == before_b["updated_at"]
        assert after_a["last_turn_status"] == "running"
    finally:
        for session_id in session_ids:
            _reset_seeded_session_runtime(session_id)


def test_get_session_detail_does_not_assemble_full_document(tmp_path: Path, monkeypatch) -> None:
    from core.web.services import agent_directory_service

    session_ids = ["session-a", "session-b"]
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _seed_submittable_sessions(tmp_path, session_ids)

    document_loads: list[str] = []
    original_load = session_service.load_chat_state

    def spy_load(project_root):
        document_loads.append("load")
        return original_load(project_root)

    monkeypatch.setattr(session_service, "load_chat_state", spy_load)
    try:
        detail = session_service.get_session_detail(
            "session-a",
            message_limit=0,
            transcript_scope="none",
            include_secondary=False,
        )
        assert detail is not None
        assert str(detail.get("id") or detail.get("sessionId") or "") == "session-a"
        assert document_loads == []
        sibling = session_service.load_session_chat_state(tmp_path, "session-b")
        assert sibling is not None
        assert sibling["title"] == "session-b"
    finally:
        for session_id in session_ids:
            _reset_seeded_session_runtime(session_id)


def test_submit_records_persist_segment_timing(tmp_path: Path, monkeypatch) -> None:
    session_id = "session-persist-timing"
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_chat_state(tmp_path)
    _bind_seeded_submittable_agent(tmp_path, session_id=session_id)
    scheduled_contexts: list[dict] = []
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: scheduled_contexts.append(dict(context)),
    )
    monkeypatch.setattr(
        session_service,
        "_session_context_limit_payload",
        lambda conversation: {"limit": 128000},
    )
    persisted_work_runs: list[dict] = []
    monkeypatch.setattr(
        session_service,
        "_persist_chat_turn_work_run",
        lambda **kwargs: persisted_work_runs.append(kwargs),
    )
    accepted_timings: list[dict] = []

    def capture_accepted(context, timing_fields):
        accepted_timings.append(dict(timing_fields))

    monkeypatch.setattr(session_service, "_record_session_turn_accepted_event", capture_accepted)

    try:
        result = submit.submit_session_message_lightweight(
            session_id,
            "persist timing",
            mental_model_enabled=False,
        )
        assert result["accepted"] is True
    finally:
        _reset_seeded_session_runtime(session_id)

    assert len(accepted_timings) == 1
    timings = accepted_timings[0]
    for key in (
        "chatStateLockWaitMs",
        "persistResolveMs",
        "persistMessageBuildMs",
        "chatStateSaveMs",
        "setSessionRunningMs",
        "workRunPersistMs",
        "chatStateLockedMs",
    ):
        assert key in timings, key
        assert isinstance(timings[key], int), key
        assert timings[key] >= 0, key
    # The resolve segment is the first slice of the locked window, so the total
    # must never be smaller than it.
    assert timings["chatStateLockedMs"] >= timings["persistResolveMs"]
    assert len(persisted_work_runs) == 1
    assert persisted_work_runs[0]["session_id"] == session_id


def test_submit_acceptance_window_failure_settles_running_turn(tmp_path: Path, monkeypatch) -> None:
    """A journal failure after running is set must settle the turn, not wedge it.

    Regression guard for the acceptance window between ``_set_session_running``
    and ``_schedule_session_turn``: the failure has to run the same settlement
    sequence as a schedule failure (work run failed -> turn failure persisted
    while still current -> running cleared -> turn control cleared -> snapshot
    published) and re-raise the original error.
    """

    from core.web.services import agent_directory_service

    session_id = "session-admission-window-failure"
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _seed_submittable_sessions(tmp_path, [session_id])

    def raise_journal_lock_timeout(**kwargs):
        raise TimeoutError("journal file lock timed out")

    monkeypatch.setattr(submit, "_append_initial_session_journal_markers", raise_journal_lock_timeout)
    work_run_calls: list[dict] = []
    monkeypatch.setattr(
        session_service,
        "_persist_chat_turn_work_run",
        lambda **kwargs: work_run_calls.append(dict(kwargs)),
    )
    published_sessions: list[str] = []
    monkeypatch.setattr(
        session_service,
        "_publish_session_detail_snapshot",
        lambda target: published_sessions.append(target),
    )
    scene_events: list[dict] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda component, phase, event_code, **kwargs: scene_events.append(
            {"component": component, "phase": phase, "event_code": event_code, **kwargs}
        ),
    )

    try:
        with pytest.raises(TimeoutError):
            submit.submit_session_message_lightweight(
                session_id,
                "admission window failure",
                mental_model_enabled=False,
            )

        failed_calls = [call for call in work_run_calls if str(call.get("status")) == "failed"]
        assert failed_calls, "expected the turn work run to be settled as failed"
        handler_call = next(
            call for call in failed_calls if call.get("user_message") == "admission window failure"
        )
        assert str(handler_call.get("summary", "")).startswith("TimeoutError:")
        assert handler_call.get("turn_id")
        assert session_service._is_session_running(session_id) is False
        assert session_service._get_session_turn_control(session_id) is None
        assert published_sessions == [session_id]
        admission_failure_events = [
            event for event in scene_events if event["event_code"] == "conversation.submit.admission_window_failed"
        ]
        assert len(admission_failure_events) == 1
        assert admission_failure_events[0]["fields"]["failedStage"] == "initial_journal_markers"
        assert admission_failure_events[0]["fields"]["errorType"] == "TimeoutError"
    finally:
        _reset_seeded_session_runtime(session_id)


def test_submit_acceptance_window_failure_survives_settlement_step_errors(tmp_path: Path, monkeypatch) -> None:
    """A settlement step that raises must not mask the original submission error."""

    from core.web.services import agent_directory_service

    session_id = "session-admission-settle-failure"
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _seed_submittable_sessions(tmp_path, [session_id])

    def raise_journal_lock_timeout(**kwargs):
        raise TimeoutError("journal file lock timed out")

    monkeypatch.setattr(submit, "_append_initial_session_journal_markers", raise_journal_lock_timeout)

    def raise_still_locked(**kwargs):
        if str(kwargs.get("status")) != "failed":
            return
        raise TimeoutError("journal still locked")

    # The failed-status settlement persist itself fails; the remaining steps
    # must still clear running/turn control and the original error must win.
    monkeypatch.setattr(session_service, "_persist_chat_turn_work_run", raise_still_locked)
    settle_step_events: list[dict] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda component, phase, event_code, **kwargs: settle_step_events.append(
            {"component": component, "phase": phase, "event_code": event_code, **kwargs}
        ),
    )

    try:
        with pytest.raises(TimeoutError, match="journal file lock timed out"):
            submit.submit_session_message_lightweight(
                session_id,
                "settlement step failure",
                mental_model_enabled=False,
            )

        assert session_service._is_session_running(session_id) is False
        assert session_service._get_session_turn_control(session_id) is None
        settle_step_failures = [
            event
            for event in settle_step_events
            if event["event_code"] == "conversation.submit.admission_settle_step_failed"
        ]
        assert settle_step_failures, "expected the failing settlement step to be reported"
        assert settle_step_failures[0]["fields"]["settlementStep"] == "persist_work_run_failed"
    finally:
        _reset_seeded_session_runtime(session_id)


def test_steer_guidance_after_turn_terminal_is_dropped_gracefully(tmp_path: Path, monkeypatch) -> None:
    """A guidance write losing the terminal race must drop, not raise."""

    from core.chat.turn_journal import TurnJournalPostTerminalWriteError

    session_id = "session-guidance-late"
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_submittable_sessions(tmp_path, [session_id])

    class _SettledTurnControl:
        turn_id = "turn-already-settled"

        def snapshot(self) -> dict:
            return {
                "turnId": "turn-already-settled",
                "releasedToUser": False,
                "stopRequested": False,
                "stopRequestedAt": "",
                "stopReason": "",
            }

    monkeypatch.setattr(
        session_service,
        "_get_session_turn_control",
        lambda _session_id: _SettledTurnControl(),
    )
    monkeypatch.setattr(session_service, "_is_session_running", lambda _session_id: False)

    def raise_post_terminal_write(*args, **kwargs):
        raise TurnJournalPostTerminalWriteError("turn already has a terminal event")

    monkeypatch.setattr(session_service, "_append_session_conversation_event", raise_post_terminal_write)
    scene_events: list[dict] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda component, phase, event_code, **kwargs: scene_events.append(
            {"component": component, "phase": phase, "event_code": event_code, **kwargs}
        ),
    )

    detail = submit.submit_session_guidance(session_id, "focus on the failing test", mode="safe")

    assert str(detail.get("id") or detail.get("sessionId") or "") == session_id
    dropped_events = [
        event for event in scene_events if event["event_code"] == "chat.guidance.write_dropped"
    ]
    assert len(dropped_events) == 1
    assert dropped_events[0]["fields"]["reason"] == "post_terminal_write"
    assert dropped_events[0]["fields"]["turnId"] == "turn-already-settled"
    assert dropped_events[0]["fields"]["sessionId"] == session_id



def test_resubmit_acceptance_window_failure_settles_running_turn(tmp_path: Path, monkeypatch) -> None:
    """A journal failure after running is set must settle the resubmit turn.

    Regression guard for the shared edit/regenerate acceptance window between
    ``_set_session_running`` and ``_schedule_session_turn``: a failure there
    (here: the user message journal append) has to run the same settlement
    sequence as a schedule failure (work run failed -> turn failure persisted
    while still current -> running cleared -> turn control cleared -> snapshot
    published) and re-raise the original error.
    """

    from core.web.services import agent_directory_service

    session_id = "session-resubmit-window-failure"
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _seed_submittable_sessions(tmp_path, [session_id])

    original_append = session_service._append_session_conversation_event

    def raise_journal_lock_timeout(*args, **kwargs):
        if str(kwargs.get("source") or "") == "regenerate_session_message":
            raise TimeoutError("journal file lock timed out")
        return original_append(*args, **kwargs)

    monkeypatch.setattr(session_service, "_append_session_conversation_event", raise_journal_lock_timeout)
    work_run_calls: list[dict] = []
    monkeypatch.setattr(
        session_service,
        "_persist_chat_turn_work_run",
        lambda **kwargs: work_run_calls.append(dict(kwargs)),
    )
    turn_failure_calls: list[dict] = []
    monkeypatch.setattr(
        session_service,
        "_persist_session_turn_failure",
        lambda target, context, exc: turn_failure_calls.append(
            {"session_id": target, "context": dict(context), "exc": exc}
        ),
    )
    published_sessions: list[str] = []
    monkeypatch.setattr(
        session_service,
        "_publish_session_detail_snapshot",
        lambda target: published_sessions.append(target),
    )
    scene_events: list[dict] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda component, phase, event_code, **kwargs: scene_events.append(
            {"component": component, "phase": phase, "event_code": event_code, **kwargs}
        ),
    )

    try:
        with pytest.raises(TimeoutError, match="journal file lock timed out"):
            submit.regenerate_session_message(
                session_id,
                f"{session_id}-message-1",
                mental_model_enabled=False,
            )

        failed_calls = [call for call in work_run_calls if str(call.get("status")) == "failed"]
        assert failed_calls, "expected the resubmit turn work run to be settled as failed"
        settle_call = failed_calls[-1]
        assert settle_call.get("session_id") == session_id
        assert settle_call.get("user_message") == "seed"
        assert str(settle_call.get("summary", "")).startswith("TimeoutError:")
        turn_id = str(settle_call.get("turn_id") or "")
        assert turn_id
        # The failure persist ran with the still-current turn identity.
        assert turn_failure_calls, "expected the turn failure to be persisted while still current"
        assert turn_failure_calls[-1]["session_id"] == session_id
        assert turn_failure_calls[-1]["context"] == {"turn_id": turn_id}
        assert isinstance(turn_failure_calls[-1]["exc"], TimeoutError)
        assert session_service._is_session_running(session_id) is False
        assert session_service._get_session_turn_control(session_id) is None
        assert published_sessions == [session_id]
        admission_failure_events = [
            event for event in scene_events if event["event_code"] == "conversation.submit.admission_window_failed"
        ]
        assert len(admission_failure_events) == 1
        assert admission_failure_events[0]["fields"]["failedStage"] == "user_message_journal"
        assert admission_failure_events[0]["fields"]["errorType"] == "TimeoutError"
        assert not [
            event
            for event in scene_events
            if event["event_code"] == "conversation.submit.admission_settle_step_failed"
        ], "expected a clean settlement with no step failures"
    finally:
        _reset_seeded_session_runtime(session_id)


def test_resubmit_acceptance_window_failure_survives_settlement_step_errors(tmp_path: Path, monkeypatch) -> None:
    """A settlement step that raises must not mask the original resubmit error."""

    from core.web.services import agent_directory_service

    session_id = "session-resubmit-settle-failure"
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    _seed_submittable_sessions(tmp_path, [session_id])

    original_append = session_service._append_session_conversation_event

    def raise_journal_lock_timeout(*args, **kwargs):
        if str(kwargs.get("source") or "") == "regenerate_session_message":
            raise TimeoutError("journal file lock timed out")
        return original_append(*args, **kwargs)

    monkeypatch.setattr(session_service, "_append_session_conversation_event", raise_journal_lock_timeout)

    def raise_still_locked(**kwargs):
        if str(kwargs.get("status")) != "failed":
            return
        raise TimeoutError("journal still locked")

    # The failed-status settlement persist itself fails; the remaining steps
    # must still clear running/turn control and the original error must win.
    monkeypatch.setattr(session_service, "_persist_chat_turn_work_run", raise_still_locked)
    settle_step_events: list[dict] = []
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda component, phase, event_code, **kwargs: settle_step_events.append(
            {"component": component, "phase": phase, "event_code": event_code, **kwargs}
        ),
    )

    try:
        with pytest.raises(TimeoutError, match="journal file lock timed out"):
            submit.regenerate_session_message(
                session_id,
                f"{session_id}-message-1",
                mental_model_enabled=False,
            )

        assert session_service._is_session_running(session_id) is False
        assert session_service._get_session_turn_control(session_id) is None
        settle_step_failures = [
            event
            for event in settle_step_events
            if event["event_code"] == "conversation.submit.admission_settle_step_failed"
        ]
        assert settle_step_failures, "expected the failing settlement step to be reported"
        assert settle_step_failures[0]["fields"]["settlementStep"] == "persist_work_run_failed"
        assert settle_step_failures[0]["fields"]["failedStage"] == "user_message_journal"
    finally:
        _reset_seeded_session_runtime(session_id)
