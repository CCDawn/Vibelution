"""Terminal-anchor contract for turn completion snapshots.

"ready" is the session's idle marker and is written by several unrelated
outcomes: normal completion, user stop, and stale restart repair for turns
killed mid-flight.  A turn-scoped poller must only trust "ready" as terminal
when the conversation anchors its last real settlement
(``last_turn_terminal_turn_id``) to the requested turn; otherwise a
restart-killed turn looks like a successful one and workflow adapters settle
nodes on work that never finished.
"""

from __future__ import annotations

import pytest

from core.ui.chat_state import save_chat_state
from core.web.services import session_service
from core.web.services.team_workflow.research_runtime.agent_turn_completion import (
    TurnNotReadyError,
    wait_for_agent_turn_terminal,
)


def _seed_session_row(tmp_path, *, status: str, terminal_turn_id: str = "") -> None:
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "conversations": [
                {
                    "conversation_id": "session-a",
                    "title": "A",
                    "last_turn_status": status,
                    **({"last_turn_terminal_turn_id": terminal_turn_id} if terminal_turn_id else {}),
                }
            ],
        },
    )


def _snapshot(monkeypatch, tmp_path, *, status: str, terminal_turn_id: str = "", turn_id: str = "turn-a"):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_session_row(tmp_path, status=status, terminal_turn_id=terminal_turn_id)
    monkeypatch.setattr(session_service, "reconcile_stale_chat_turn_work_runs", lambda **_kwargs: [])
    monkeypatch.setattr(session_service, "_repair_stale_running_conversation", lambda *_a, **_k: False)
    monkeypatch.setattr(session_service, "_session_ledger_visible_messages", lambda *_a, **_k: [])
    monkeypatch.setattr(session_service, "_find_turn_scoped_assistant_message", lambda *_a, **_k: None)
    return session_service.get_session_turn_completion_snapshot("session-a", turn_id)


def test_restart_killed_ready_turn_without_anchor_is_not_terminal(monkeypatch, tmp_path):
    """Stale repair rewrites a killed turn's session row to "ready"; without a
    settlement anchor that must NOT read as a terminal success."""

    snapshot = _snapshot(monkeypatch, tmp_path, status="ready", terminal_turn_id="")

    assert snapshot["lastTurnStatus"] == "ready"
    assert snapshot["terminal"] is False
    assert snapshot["completionSource"] == "running"


def test_ready_with_matching_anchor_is_terminal(monkeypatch, tmp_path):
    snapshot = _snapshot(monkeypatch, tmp_path, status="ready", terminal_turn_id="turn-a")

    assert snapshot["terminal"] is True
    assert snapshot["terminalStatus"] == "ready"
    assert snapshot["completionSource"] == "last_turn_status"


def test_ready_anchored_to_another_turn_is_not_terminal(monkeypatch, tmp_path):
    snapshot = _snapshot(
        monkeypatch, tmp_path, status="ready", terminal_turn_id="turn-older", turn_id="turn-a"
    )

    assert snapshot["terminal"] is False


def test_explicit_failure_status_stays_terminal_without_anchor(monkeypatch, tmp_path):
    snapshot = _snapshot(monkeypatch, tmp_path, status="failed", terminal_turn_id="")

    assert snapshot["terminal"] is True
    assert snapshot["terminalStatus"] == "failed"


def test_adapter_wait_rejects_restart_killed_ready_turn(monkeypatch, tmp_path):
    """The workflow adapter must keep polling (and eventually time out) instead
    of settling a node on a turn the restart killed."""

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_session_row(tmp_path, status="ready", terminal_turn_id="")
    monkeypatch.setattr(session_service, "reconcile_stale_chat_turn_work_runs", lambda **_kwargs: [])
    monkeypatch.setattr(session_service, "_repair_stale_running_conversation", lambda *_a, **_k: False)
    monkeypatch.setattr(session_service, "_session_ledger_visible_messages", lambda *_a, **_k: [])
    monkeypatch.setattr(session_service, "_find_turn_scoped_assistant_message", lambda *_a, **_k: None)

    with pytest.raises(TurnNotReadyError):
        wait_for_agent_turn_terminal(
            "session-a",
            "turn-a",
            timeout_ms=50,
            poll_ms=10,
        )
