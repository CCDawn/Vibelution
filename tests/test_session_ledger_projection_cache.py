"""Ledger-visible projection cache regression.

The submit path normalizes the whole active branch before accepting a turn.
For a long ledger that is seconds of work even though the ledger only appends;
these tests pin the cache key (event revision + display language), the returned
copy boundary, and the append invalidation.
"""

from __future__ import annotations

from typing import Any

from core.web.services import session_service
from core.web.services.session import signals_format


class _Event:
    def __init__(self, event_id: str) -> None:
        self.event_id = event_id
        self.event_type = ""
        self.payload: dict[str, Any] = {}


class _State:
    def __init__(self) -> None:
        self.events = [_Event("event-1")]
        self.language = "zh"
        self.normalize_calls = 0
        self.raw_messages: list[dict[str, Any]] = [{"role": "user", "content": "hello"}]

    def install(self, monkeypatch) -> None:
        state = self
        signals_format._reset_session_ledger_visible_messages_cache()

        def load_events(_session_id: str):
            return list(state.events)

        def visible(_events):
            return ([dict(message) for message in state.raw_messages], "leaf", "branch")

        def normalize(_session_id: str, items):
            state.normalize_calls += 1
            return [dict(item, normalized=True) for item in items]

        monkeypatch.setattr(session_service, "_load_session_conversation_events_cached", load_events)
        monkeypatch.setattr(session_service, "visible_messages_with_branch_info", visible)
        monkeypatch.setattr(session_service, "_normalize_messages", normalize)
        monkeypatch.setattr(session_service, "get_web_language", lambda: state.language)


def test_projection_cache_hits_and_returns_independent_copies(monkeypatch) -> None:
    state = _State()
    state.install(monkeypatch)

    first = signals_format._session_ledger_visible_messages("session-cache")
    assert first == [{"role": "user", "content": "hello", "normalized": True}]
    assert state.normalize_calls == 1

    second = signals_format._session_ledger_visible_messages("session-cache")
    assert second == first
    assert state.normalize_calls == 1
    assert second is not first
    assert second[0] is not first[0]

    second[0]["content"] = "mutated"
    third = signals_format._session_ledger_visible_messages("session-cache")
    assert third[0]["content"] == "hello"


def test_projection_cache_invalidates_on_append_and_language_change(monkeypatch) -> None:
    state = _State()
    state.install(monkeypatch)

    signals_format._session_ledger_visible_messages("session-cache")
    assert state.normalize_calls == 1

    state.events.append(_Event("event-2"))
    signals_format._session_ledger_visible_messages("session-cache")
    assert state.normalize_calls == 2

    state.language = "en"
    signals_format._session_ledger_visible_messages("session-cache")
    assert state.normalize_calls == 3


def test_empty_session_short_circuits(monkeypatch) -> None:
    state = _State()
    state.events = []
    state.install(monkeypatch)

    assert signals_format._session_ledger_visible_messages("") == []
    assert signals_format._session_ledger_visible_messages("session-empty") == []
    assert state.normalize_calls == 0


def test_stop_tail_probe_reads_the_raw_tail_without_normalizing(monkeypatch) -> None:
    """Shutdown idempotency needs one bit, not a full transcript projection."""

    state = _State()
    state.install(monkeypatch)

    state.raw_messages = [{"role": "assistant", "content": "partial\n\n本轮已按请求停止"}]
    assert signals_format._session_ledger_last_message_is_stopped_turn("session-stop") is True
    assert state.normalize_calls == 0

    state.raw_messages = [{"role": "assistant", "content": "still working"}]
    assert signals_format._session_ledger_last_message_is_stopped_turn("session-stop") is False

    state.raw_messages = [{"role": "user", "content": "本轮已按请求停止"}]
    assert signals_format._session_ledger_last_message_is_stopped_turn("session-stop") is False

    state.raw_messages = []
    assert signals_format._session_ledger_last_message_is_stopped_turn("session-stop") is False

    state.events = []
    assert signals_format._session_ledger_last_message_is_stopped_turn("session-stop") is False
    assert state.normalize_calls == 0
