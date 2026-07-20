"""Focused tests for session submit slice (pure helpers + facade re-export)."""

from __future__ import annotations

from core.web.services import session_service
from core.web.services.session import submit


def test_resolve_user_message_content_plain_and_base64() -> None:
    assert submit._resolve_user_message_content("  hello  ") == "hello"
    import base64

    encoded = base64.b64encode("你好".encode("utf-8")).decode("ascii")
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
