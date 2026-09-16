"""Live-message ``routeFallback`` stamping for the explicit fallback route.

The session-detail root field alone cannot reach the UI: the in-flight status
note reads the live overlay message. ``_messages_with_live_output`` therefore
stamps the exact-turn switch payload onto the live message (copy-on-write), and
a switch recorded for a different turn must never relabel a fresh live message.
"""

from __future__ import annotations

import pytest

from core.infrastructure import developer_sandbox
from core.llm import route_fallback_registry
from core.web.services import session_service
from core.web.services.session import projection


@pytest.fixture(autouse=True)
def _isolated_data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "operator-data"))
    monkeypatch.setattr(developer_sandbox, "is_developer_mode_enabled", lambda: False)


def _prepare_live_message(monkeypatch, *, session_turn_id: str) -> None:
    monkeypatch.setattr(session_service, "_session_ledger_visible_messages", lambda sid: [])
    monkeypatch.setattr(
        session_service, "_without_live_turn_ledger_partials", lambda msgs, live: msgs
    )
    monkeypatch.setattr(session_service, "_session_events_have_terminal_turn", lambda events, tid: False)
    monkeypatch.setattr(session_service, "_load_session_conversation_events_cached", lambda sid: [])
    monkeypatch.setattr(
        session_service,
        "_build_live_output_message",
        lambda sid: {
            "role": "assistant",
            "content": "",
            "turnId": session_turn_id,
            "metadata": {"turnId": session_turn_id},
        },
    )


def test_live_message_carries_route_fallback_for_exact_turn(monkeypatch) -> None:
    _prepare_live_message(monkeypatch, session_turn_id="turn-live")
    route_fallback_registry.record_route_fallback(
        "session-stamp-exact",
        "turn-live",
        from_profile_id="primary",
        to_profile_id="backup_qwen",
        reason="server_error",
    )

    messages = projection._messages_with_live_output("session-stamp-exact")

    assert messages[-1]["routeFallback"] == {"from": "primary", "to": "backup_qwen"}


def test_live_message_not_stamped_for_other_turn_switch(monkeypatch) -> None:
    _prepare_live_message(monkeypatch, session_turn_id="turn-live")
    route_fallback_registry.record_route_fallback(
        "session-stamp-other",
        "turn-older",
        from_profile_id="primary",
        to_profile_id="backup_qwen",
        reason="server_error",
    )

    messages = projection._messages_with_live_output("session-stamp-other")

    assert "routeFallback" not in messages[-1]
