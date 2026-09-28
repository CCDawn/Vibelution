"""Hidden/hallucinated tool_calls must land in the ConversationLedger.

Defect ② (2026-09-25 audit): when the model returns a tool_call for a tool
that is not visible to the current agent (unbound tool or hallucinated name),
the blocking branch synthesized a tool result into memory only. The legal path
journals tool events through the stream_capture proxy; the blocked path did
not, so the next send-time reconcile could not rebuild the current turn's
assistant/tool layer and the strict fingerprint gate fail-closed the session
(``turn_journal_replay_failed`` / ``ledger_history_mismatch`` error card).

These tests pin the fix: the blocking path journals one ``tool_call_started``
plus one ``tool_result`` entry (payload carries the model-visible blocked
message), and the next-round reconcile must pass with a well-formed chain.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from agent import AgentRuntime
from core.chat.conversation_invariant import (
    check_conversation_payload_invariant,
)
from core.chat.turn_journal import (
    EVENT_TOOL_CALL_STARTED,
    EVENT_TOOL_RESULT,
    EVENT_TURN_STARTED,
    EVENT_USER_MESSAGE,
    append_turn_event,
    load_turn_events,
)
from core.chat.conversation_ledger import load_conversation_events
from core.orchestration.turn_message_assembly import (
    reconcile_chat_messages_with_ledger,
)


@pytest.fixture(autouse=True)
def _isolated_data_home(tmp_path, monkeypatch):
    # Journal workspaces for identity-less tmp roots resolve to a shared home;
    # per-test isolation keeps sessions from bleeding across tests.
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "operator-data"))


BLOCKED_MESSAGE = "[工具可见性提示] `hidden_tool` 未暴露给当前 Agent。"
SESSION_ID = "sess-hidden-tool-replay"
TURN_ID = "turn-hidden-tool-replay"


def _make_agent(project_root: Path | None) -> AgentRuntime:
    agent = AgentRuntime.__new__(AgentRuntime)
    agent.project_root = str(project_root or "")
    identity = (
        (project_root, SESSION_ID, TURN_ID) if project_root is not None else None
    )
    agent._chat_ledger_identity = lambda: identity
    return agent


def _seed_turn_scaffold(project_root: Path) -> None:
    append_turn_event(project_root, SESSION_ID, TURN_ID, EVENT_TURN_STARTED, payload={})
    append_turn_event(
        project_root,
        SESSION_ID,
        TURN_ID,
        EVENT_USER_MESSAGE,
        payload={"content": "帮我用隐藏工具查一下"},
    )


def _memory_chain_after_block(tool_name: str, call_id: str) -> list:
    return [
        {"role": "user", "content": "帮我用隐藏工具查一下"},
        AIMessage(
            content="",
            tool_calls=[
                {"name": tool_name, "args": {"query": "x"}, "id": call_id, "type": "function"}
            ],
        ),
        ToolMessage(content=BLOCKED_MESSAGE, tool_call_id=call_id),
    ]


def test_hidden_tool_block_journals_tool_call_and_blocked_result(tmp_path):
    """The blocked call must journal the assistant tool_call entry and the result placeholder."""

    agent = _make_agent(tmp_path)

    agent._persist_hidden_tool_block_to_ledger(
        {"name": "hidden_tool", "id": "call_blk_1", "args": {"query": "x"}},
        BLOCKED_MESSAGE,
    )

    events = load_turn_events(tmp_path, SESSION_ID)
    by_type: dict[str, list] = {}
    for event in events:
        by_type.setdefault(event.event_type, []).append(event)

    started_events = by_type.get(EVENT_TOOL_CALL_STARTED, [])
    result_events = by_type.get(EVENT_TOOL_RESULT, [])
    assert len(started_events) == 1
    assert len(result_events) == 1

    started = started_events[0]
    assert started.turn_id == TURN_ID
    assert started.status == "blocked"
    assert started.tool_call_id == "call_blk_1"
    assert started.correlation_id == "call_blk_1"
    started_call = dict(started.payload.get("toolCall") or {})
    assert started_call.get("name") == "hidden_tool"
    assert started_call.get("arguments") == {"query": "x"}

    result = result_events[0]
    assert result.status == "blocked"
    assert result.tool_call_id == "call_blk_1"
    assert result.correlation_id == "call_blk_1"
    result_call = dict(result.payload.get("toolCall") or {})
    assert result_call.get("name") == "hidden_tool"
    assert result_call.get("result") == BLOCKED_MESSAGE


def test_hidden_tool_block_without_ledger_identity_is_silent_noop(tmp_path):
    """No ledger identity (non-chat runtime) must neither write nor raise."""

    agent = _make_agent(None)

    agent._persist_hidden_tool_block_to_ledger(
        {"name": "hidden_tool", "id": "call_blk_2", "args": {}},
        BLOCKED_MESSAGE,
    )

    assert load_turn_events(tmp_path, SESSION_ID) == []


@pytest.mark.parametrize(
    ("tool_name", "call_id"),
    [
        ("hidden_tool", "call_unbound_1"),
        ("web_search_pro_tool", "call_hallu_1"),
    ],
)
def test_blocked_call_replay_reconciles_next_llm_send(tmp_path, tool_name, call_id):
    """After journaling the block, the next send-time reconcile must pass.

    Without the ledger entries this exact input raised ``TurnJournalReplayError``
    (``ledger_history_mismatch``) — the fail-closed error card from the audit.
    The hallucinated-name variant (tool bound to the agent, name does not
    exist) takes the same blocking branch and must behave the same.
    """

    _seed_turn_scaffold(tmp_path)
    agent = _make_agent(tmp_path)
    messages = _memory_chain_after_block(tool_name, call_id)

    agent._persist_hidden_tool_block_to_ledger(
        {"name": tool_name, "id": call_id, "args": {"query": "x"}},
        BLOCKED_MESSAGE,
    )

    events = load_conversation_events(tmp_path, SESSION_ID)
    reconciled = reconcile_chat_messages_with_ledger(
        messages,
        events,
        turn_id=TURN_ID,
        strict=True,
    )

    assert len(reconciled) == 3
    replayed_call_message = reconciled[1]
    replayed_calls = list(getattr(replayed_call_message, "tool_calls", None) or [])
    assert len(replayed_calls) == 1
    assert replayed_calls[0].get("id") == call_id
    assert replayed_calls[0].get("name") == tool_name
    replayed_result = reconciled[2]
    assert getattr(replayed_result, "tool_call_id", "") == call_id
    assert BLOCKED_MESSAGE in str(getattr(replayed_result, "content", ""))
    assert check_conversation_payload_invariant(reconciled).ok


def test_blocked_entry_coexists_with_legal_tool_chain(tmp_path):
    """A blocked entry followed by a legal tool run must reconcile in order."""

    _seed_turn_scaffold(tmp_path)
    agent = _make_agent(tmp_path)

    agent._persist_hidden_tool_block_to_ledger(
        {"name": "hidden_tool", "id": "call_blk_3", "args": {"query": "x"}},
        BLOCKED_MESSAGE,
    )
    # Legal tool timeline, journaled by the stream_capture proxy in production.
    append_turn_event(
        tmp_path,
        SESSION_ID,
        TURN_ID,
        EVENT_TOOL_CALL_STARTED,
        status="running",
        payload={
            "toolCall": {
                "name": "read_file_tool",
                "status": "running",
                "arguments": {"path": "a.py"},
                "summary": "",
            }
        },
        tool_call_id="call_legal_1",
        correlation_id="call_legal_1",
        source="session_ui_capture",
    )
    append_turn_event(
        tmp_path,
        SESSION_ID,
        TURN_ID,
        EVENT_TOOL_RESULT,
        status="done",
        payload={
            "toolCall": {
                "name": "read_file_tool",
                "status": "done",
                "arguments": {"path": "a.py"},
                "summary": "file body",
                "result": "file body",
            }
        },
        tool_call_id="call_legal_1",
        correlation_id="call_legal_1",
        source="session_ui_capture",
    )

    events = load_conversation_events(tmp_path, SESSION_ID)
    reconciled = reconcile_chat_messages_with_ledger(
        _memory_chain_after_block("hidden_tool", "call_blk_3"),
        events,
        turn_id=TURN_ID,
        strict=True,
    )

    assert check_conversation_payload_invariant(reconciled).ok
    chain_tool_call_ids = [
        str(getattr(message, "tool_call_id", "") or "")
        for message in reconciled
        if getattr(message, "tool_call_id", "")
    ]
    # Same turn, one blocked call + one legal call, order preserved.
    assert chain_tool_call_ids.count("call_blk_3") == 1
    assert chain_tool_call_ids.count("call_legal_1") == 1
    assert chain_tool_call_ids.index("call_blk_3") < chain_tool_call_ids.index("call_legal_1")
