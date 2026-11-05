"""Privacy (sec_) attachment consumption across the shared submit pipeline.

The personal-assistant session gets a value-free presence marker appended to
the model message and a metadata-only journal row; ordinary sessions treat
the same ids as nonexistent. The plaintext value never reaches the model
context or the journal.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.assistant_runtime import secret_attachments
from core.web.services import agent_directory_service, session_service
from core.web.services.session import submit
from tests.helpers.web_chat_state import (
    _bind_seeded_submittable_agent,
    _reset_seeded_session_runtime,
    _seed_chat_state,
)

SECRET_PLAINTEXT = "sk-live-key-123"


@pytest.fixture(autouse=True)
def _isolated_secret_store():
    secret_attachments._STORE.clear()
    yield
    secret_attachments._STORE.clear()


def _seed_pa_session(tmp_path: Path, monkeypatch) -> dict:
    session_id = "session-live"
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_chat_state(tmp_path)
    agent = _bind_seeded_submittable_agent(tmp_path, session_id=session_id)
    agent_directory_service.update_agent_instance(
        agent["agentId"],
        metadata={"personalAssistantProfile": "personal_assistant_v1"},
    )
    return agent


def _capture_turn_context(monkeypatch) -> list[dict]:
    scheduled_contexts: list[dict] = []
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: scheduled_contexts.append(dict(context)),
    )
    return scheduled_contexts


def _latest_user_event_payload(session_id: str) -> dict:
    events = session_service._load_session_conversation_events_cached(session_id)
    user_events = [
        event for event in events if event.event_type == session_service.EVENT_USER_MESSAGE
    ]
    assert user_events
    return dict(user_events[-1].payload or {})


def test_pa_session_secret_attachment_marks_model_message_without_plaintext(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session_id = "session-live"
    _seed_pa_session(tmp_path, monkeypatch)
    scheduled_contexts = _capture_turn_context(monkeypatch)
    token = secret_attachments.issue_secret_attachment(
        SECRET_PLAINTEXT, "api_key", label="Provider Key",
    )

    try:
        result = submit.submit_session_message(
            session_id,
            "帮我把这个 key 配置到 provider",
            client_submission_id="submission-pa-secret",
            attachment_ids=[token],
            include_started_turn_id=True,
            lightweight_response=True,
        )

        assert result["accepted"] is True
        assert len(scheduled_contexts) == 1
        context = scheduled_contexts[0]
        model_message = str(context["user_message"])
        # Presence marker names the one-shot token and the display label...
        assert token in model_message
        assert "[隐私附件]" in model_message
        assert "Provider Key" in model_message
        assert "类型" not in model_message
        assert 'credential_token="' + token + '"' in model_message
        # ...but the plaintext never reaches the model context.
        assert SECRET_PLAINTEXT not in model_message
        assert SECRET_PLAINTEXT not in json.dumps(context, ensure_ascii=False, default=str)
        assert context["attachments"] == []

        payload = _latest_user_event_payload(session_id)
        secret_rows = [
            row for row in (payload.get("attachments") or [])
            if isinstance(row, dict) and row.get("kind") == "user_secret"
        ]
        assert secret_rows == [
            {"attachmentId": token, "kind": "user_secret", "label": "Provider Key"},
        ]
        # The journal carries no value anywhere in the user event payload.
        assert SECRET_PLAINTEXT not in json.dumps(payload, ensure_ascii=False, default=str)
    finally:
        _reset_seeded_session_runtime(session_id)


def test_secret_attachment_prompt_block_uses_label_or_unnamed_fallback() -> None:
    token = secret_attachments.issue_secret_attachment(SECRET_PLAINTEXT, "api_key", label="")
    bare = submit._secret_attachment_prompt_block([{"attachmentId": token}])
    assert "[隐私附件]" in bare
    assert "未命名" in bare
    assert "类型" not in bare
    assert 'credential_token="' + token + '"' in bare
    labeled = submit._secret_attachment_prompt_block([{"attachmentId": token, "label": "邮箱密码"}])
    assert "邮箱密码" in labeled
    assert "未命名" not in labeled
    assert "类型" not in labeled


def test_ordinary_session_treats_secret_ids_as_nonexistent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session_id = "session-live"
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_chat_state(tmp_path)
    _bind_seeded_submittable_agent(tmp_path, session_id=session_id)
    scheduled_contexts = _capture_turn_context(monkeypatch)
    token = secret_attachments.issue_secret_attachment(
        SECRET_PLAINTEXT, "api_key", label="Provider Key",
    )

    try:
        result = submit.submit_session_message(
            session_id,
            "普通会话消息",
            client_submission_id="submission-plain-secret",
            attachment_ids=[token],
            include_started_turn_id=True,
            lightweight_response=True,
        )

        assert result["accepted"] is True
        assert len(scheduled_contexts) == 1
        context = scheduled_contexts[0]
        model_message = str(context["user_message"])
        assert model_message == "普通会话消息"
        assert token not in model_message
        assert "[隐私附件]" not in model_message
        payload = _latest_user_event_payload(session_id)
        assert SECRET_PLAINTEXT not in json.dumps(payload, ensure_ascii=False, default=str)
        secret_rows = [
            row for row in (payload.get("attachments") or [])
            if isinstance(row, dict) and row.get("kind") == "user_secret"
        ]
        assert secret_rows == []

        # Attachment treated as nonexistent: an otherwise-empty submit with
        # only a sec_ id is rejected like a submit with nothing at all.
        _reset_seeded_session_runtime(session_id)
        with pytest.raises(session_service.SessionValidationError):
            submit.submit_session_message(
                session_id,
                "",
                client_submission_id="submission-plain-secret-empty",
                attachment_ids=[token],
            )
        assert len(scheduled_contexts) == 1
    finally:
        _reset_seeded_session_runtime(session_id)


def test_pa_session_expired_secret_is_ignored(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session_id = "session-live"
    _seed_pa_session(tmp_path, monkeypatch)
    scheduled_contexts = _capture_turn_context(monkeypatch)
    clock = {"now": 0.0}
    monkeypatch.setattr(secret_attachments.time, "monotonic", lambda: clock["now"])
    token = secret_attachments.issue_secret_attachment(SECRET_PLAINTEXT, "password")
    clock["now"] += secret_attachments.SECRET_ATTACHMENT_TTL_SECONDS + 1

    try:
        result = submit.submit_session_message(
            session_id,
            "这条消息引用的隐私附件已经过期",
            client_submission_id="submission-pa-secret-expired",
            attachment_ids=[token],
            include_started_turn_id=True,
            lightweight_response=True,
        )

        assert result["accepted"] is True
        assert len(scheduled_contexts) == 1
        model_message = str(scheduled_contexts[0]["user_message"])
        assert token not in model_message
        assert "[隐私附件]" not in model_message
        payload = _latest_user_event_payload(session_id)
        secret_rows = [
            row for row in (payload.get("attachments") or [])
            if isinstance(row, dict) and row.get("kind") == "user_secret"
        ]
        assert secret_rows == []
    finally:
        _reset_seeded_session_runtime(session_id)
