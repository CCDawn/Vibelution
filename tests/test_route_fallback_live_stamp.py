"""Live-message ``routeFallback`` stamping for the explicit fallback route.

The switch is read from the durable Session Journal authority
(``llm_resilience`` / ``fallback_switch``), not from an in-memory registry,
so a recorded switch survives process restarts. ``_messages_with_live_output``
stamps the exact-turn switch payload onto the live message (copy-on-write),
and a switch recorded for a different turn must never relabel a fresh live
message.
"""

from __future__ import annotations

import pytest

from core.chat.llm_resilience_journal import (
    record_llm_resilience_event,
)
from core.infrastructure import developer_sandbox
from core.web.services import session_service
from core.web.services.session import projection


@pytest.fixture(autouse=True)
def _isolated_data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "operator-data"))
    monkeypatch.setattr(developer_sandbox, "is_developer_mode_enabled", lambda: False)


def _record_fallback(session_id: str, turn_id: str, *, attempt: int = 1) -> None:
    # Write through the same project root the DTO reader resolves so both
    # sides land on one journal file even when test fixtures re-pin the
    # workspace home.
    record_llm_resilience_event(
        session_service.PROJECT_ROOT,
        session_id,
        turn_id,
        stage="fallback_switch",
        attempt=attempt,
        fields={
            "sessionId": session_id,
            "turnId": turn_id,
            "from": "primary",
            "to": "backup_qwen",
            "errorCategory": "server_error",
            "routeId": "route-primary",
        },
    )


def _prepare_live_message(monkeypatch, *, session_turn_id: str) -> None:
    monkeypatch.setattr(session_service, "_session_ledger_visible_messages", lambda sid: [])
    monkeypatch.setattr(
        session_service, "_without_live_turn_ledger_partials", lambda msgs, live: msgs
    )
    monkeypatch.setattr(session_service, "_session_events_have_terminal_turn", lambda events, tid: False)
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
    _record_fallback("session-stamp-exact", "turn-live")

    messages = projection._messages_with_live_output("session-stamp-exact")

    assert messages[-1]["routeFallback"] == {"from": "primary", "to": "backup_qwen"}


def test_live_message_not_stamped_for_other_turn_switch(monkeypatch) -> None:
    _prepare_live_message(monkeypatch, session_turn_id="turn-live")
    _record_fallback("session-stamp-other", "turn-older")

    messages = projection._messages_with_live_output("session-stamp-other")

    assert "routeFallback" not in messages[-1]
