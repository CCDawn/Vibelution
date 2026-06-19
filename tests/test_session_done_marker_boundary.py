from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from core.ui.chat_state import CHAT_STATE_VERSION, save_chat_state
from core.web.services import session_service


def _seed_session(root: Path) -> None:
    save_chat_state(
        root,
        {
            "version": CHAT_STATE_VERSION,
            "active_conversation_id": "session-live",
            "updated_at": "2026-05-22T12:00:00",
            "conversations": [
                {
                    "conversation_id": "session-live",
                    "title": "Agent 会话",
                    "updated_at": "2026-05-22T12:00:00",
                    "last_turn_status": "ready",
                    "messages": [],
                    "active_task": None,
                }
            ],
        },
    )


def test_bare_done_marker_keeps_previous_visible_continuation_reply(tmp_path, monkeypatch):
    _seed_session(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "get_web_chat_config",
        lambda: SimpleNamespace(max_continuation_turns=2),
    )
    calls = []

    class DoneMarkerAgent:
        def seed_chat_history(self, messages):
            self.messages = list(messages)

        def run_single_turn(self, initial_prompt=None):
            calls.append(initial_prompt)
            if len(calls) == 1:
                return {
                    "status": "completed",
                    "summary": "结果如下：项目审查完成，核心问题集中在回答持久化。",
                    "raw_output": "结果如下：项目审查完成，核心问题集中在回答持久化。",
                    "outcome": "progress",
                    "read_files": ["README.md"],
                    "tool_call_count": 1,
                    "tool_trace": [
                        {"name": "read_file_tool", "args": {"file_path": "README.md"}},
                    ],
                }
            return {
                "status": "completed",
                "summary": "outcome=done",
                "raw_output": "outcome=done",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    monkeypatch.setattr(session_service, "create_chat_agent", lambda: DoneMarkerAgent())
    monkeypatch.setattr(
        session_service,
        "_schedule_session_turn",
        lambda context: session_service._run_session_turn({**context, "allow_internal_auto_continue": True}),
    )

    payload = session_service.submit_session_message("session-live", "审查项目并汇报")

    assert len(calls) == 2
    assistant = payload["messages"][-1]
    assert assistant["role"] == "assistant"
    assert assistant["content"] == "结果如下：项目审查完成，核心问题集中在回答持久化。"
    assert "outcome=done" not in str(payload)
    assert payload["activeTask"] is None
