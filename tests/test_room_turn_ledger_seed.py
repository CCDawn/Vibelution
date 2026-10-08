"""Chat-room speaker turns must survive multi-iteration tool loops.

The room execution path does not journal mid-turn conversation items, so the
seeded ledger fingerprint has to stay valid for later LLM sends while the
ledger still matches the seed state; in-memory growth after the verified seed
is the runtime's own in-flight layer, not history drift. When the ledger has
advanced, the stamp must be dropped and the strict journal replay take over.
"""

from pathlib import Path

import pytest

import agent as agent_module
from core.chat.conversation_invariant import canonical_conversation_messages_from_events
from core.infrastructure.runtime_input import build_chat_user_message
from core.orchestration.turn_message_assembly import (
    ledger_seeded_history_fingerprint,
)
from core.web.services import agent_directory_service, session_service


def _seed_journal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    session_service._append_session_conversation_event(
        "session-room",
        "turn-a",
        session_service.EVENT_USER_MESSAGE,
        status="recorded",
        payload={"role": "user", "content": "首个需求", "turnId": "turn-a"},
        source="test",
    )
    session_service._append_session_conversation_event(
        "session-room",
        "turn-a",
        session_service.EVENT_ASSISTANT_MESSAGE,
        status="committed",
        payload={"role": "assistant", "content": "已规划", "turnId": "turn-a"},
        source="test",
    )


def _fake_agent(tmp_path: Path) -> agent_module.AgentRuntime:
    agent = object.__new__(agent_module.AgentRuntime)
    agent.project_root = str(tmp_path)
    agent._seeded_history_ledger_fingerprint = ""
    agent._ledger_conversation_fingerprint = ""
    agent._record_turn_failure_diagnostic = lambda **_kwargs: None
    return agent


def test_seeded_fingerprint_stays_valid_for_unjournaled_iterations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_journal(tmp_path, monkeypatch)
    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: {"sessionId": "session-room", "turnId": "turn-b"},
    )
    agent = _fake_agent(tmp_path)
    events = session_service._load_session_conversation_events_cached("session-room")
    seeded = canonical_conversation_messages_from_events(events, current_turn_id="turn-b")
    messages = [*seeded, build_chat_user_message("继续推进")]

    agent._seeded_history_ledger_fingerprint = ledger_seeded_history_fingerprint(
        events, turn_id="turn-b"
    )

    assert agent._reconcile_chat_conversation_before_llm(messages) == (messages, True)

    grown = [
        *messages,
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "name": "dev_task_board_tool"}]},
        {"role": "tool", "tool_call_id": "c1", "content": "task-1 created"},
    ]
    assert agent._reconcile_chat_conversation_before_llm(grown) == (grown, True)
    assert agent._seeded_history_ledger_fingerprint


def test_seeded_fingerprint_drops_once_ledger_advances(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_journal(tmp_path, monkeypatch)
    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: {"sessionId": "session-room", "turnId": "turn-b"},
    )
    agent = _fake_agent(tmp_path)
    events = session_service._load_session_conversation_events_cached("session-room")
    seeded = canonical_conversation_messages_from_events(events, current_turn_id="turn-b")
    messages = [*seeded, build_chat_user_message("继续推进")]

    agent._seeded_history_ledger_fingerprint = ledger_seeded_history_fingerprint(
        events, turn_id="turn-b"
    )
    assert agent._reconcile_chat_conversation_before_llm(messages) == (messages, True)

    session_service._append_session_conversation_event(
        "session-room",
        "turn-b",
        session_service.EVENT_USER_MESSAGE,
        status="recorded",
        payload={"role": "user", "content": "继续推进", "turnId": "turn-b"},
        source="test",
    )
    # The seeded fingerprint covers history only, so current-turn journal
    # growth does not invalidate the seed: the shortcut keeps accepting a
    # provenance-clean in-memory history.
    assert agent._reconcile_chat_conversation_before_llm(messages) == (messages, True)
    assert agent._seeded_history_ledger_fingerprint

    # Without a valid stamp the strict journal replay owns the check and
    # still fails closed on real history drift (ok=False blocks the send).
    agent._seeded_history_ledger_fingerprint = ""
    tampered = [
        {**seeded[0]},
        {**seeded[1], "content": "被改写的历史"},
        build_chat_user_message("继续推进"),
    ]
    assert agent._reconcile_chat_conversation_before_llm(tampered) == (tampered, False)
