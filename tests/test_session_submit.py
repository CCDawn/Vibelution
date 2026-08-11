"""Focused tests for session submit slice (pure helpers + facade re-export)."""

from __future__ import annotations

from pathlib import Path

from core.chat.conversation_ledger import (
    EVENT_TURN_STARTED,
    EVENT_USER_MESSAGE,
    load_conversation_events,
)
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
