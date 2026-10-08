from __future__ import annotations

import json

from core.chat.turn_journal import load_turn_events
from core.orchestration.subagent_address import (
    MISSING_CHILD_SESSION,
    NO_ACTIVE_AGENT,
    append_child_exchange,
    begin_resume,
    continue_addressed,
    get_subagent_address,
    note_subagent_progress,
    restore_subagent_status,
)
from core.orchestration import subagent_address


def _record(tmp_path, *, status: str, child_session_id: str = "child-1") -> None:
    subagent_address._save_record(
        {
            "agentId": "subagent-inspect-d1-abc",
            "subRunId": "subagent-inspect-d1-abc",
            "parentSessionId": "parent-1",
            "parentTurnId": "turn-parent",
            "childSessionId": child_session_id,
            "projectRoot": str(tmp_path),
            "status": status,
            "previousStatus": "",
            "resumeClaimed": False,
            "pending": [],
            "activeMessages": [],
            "taskType": "inspect",
            "summary": "",
        }
    )


def test_unknown_agent_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_SUBAGENT_ADDRESS_ROOT", str(tmp_path / "addresses"))

    result = continue_addressed("missing", "接着做", resume=lambda _text: "nope")

    assert result["code"] == NO_ACTIVE_AGENT


def test_running_agent_queues_on_the_same_child_without_resume(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_SUBAGENT_ADDRESS_ROOT", str(tmp_path / "addresses"))
    _record(tmp_path, status="running")
    called: list[str] = []

    result = continue_addressed(
        "subagent-inspect-d1-abc",
        "下一句",
        resume=lambda text: called.append(text),
    )

    assert result["delivery"] == "queued"
    assert result["childSessionId"] == "child-1"
    assert called == []
    stored = get_subagent_address("subagent-inspect-d1-abc")
    assert stored is not None
    assert stored["pending"][-1]["message"] == "下一句"
    progress = [
        event
        for event in load_turn_events(tmp_path, "parent-1")
        if event.event_type == "subagent_progress"
    ]
    assert progress
    assert progress[-1].visible_in_model is False
    assert progress[-1].payload["childSessionId"] == "child-1"
    assert progress[-1].payload["delivery"] == "queued"
    assert "下一句" not in json.dumps(progress[-1].payload, ensure_ascii=False)


def test_terminal_resume_keeps_the_original_child_and_restores_on_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_SUBAGENT_ADDRESS_ROOT", str(tmp_path / "addresses"))
    _record(tmp_path, status="completed")

    claimed = begin_resume(
        "subagent-inspect-d1-abc",
        ready=True,
        message="接着做",
    )

    assert claimed["delivery"] == "resume"
    assert claimed["childSessionId"] == "child-1"
    assert get_subagent_address("subagent-inspect-d1-abc")["status"] == "running"

    queued = begin_resume(
        "subagent-inspect-d1-abc",
        ready=True,
        message="再等一下",
    )
    assert queued["delivery"] == "queued"
    assert queued["childSessionId"] == "child-1"

    restore_subagent_status("subagent-inspect-d1-abc")
    restored = get_subagent_address("subagent-inspect-d1-abc")
    assert restored["status"] == "completed"
    assert restored["resumeClaimed"] is False
    assert any(item["message"] == "接着做" for item in restored["pending"])


def test_missing_child_session_does_not_allocate_one(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_SUBAGENT_ADDRESS_ROOT", str(tmp_path / "addresses"))
    _record(tmp_path, status="completed", child_session_id="")

    result = begin_resume("subagent-inspect-d1-abc", ready=True, message="接着做")

    assert result["code"] == MISSING_CHILD_SESSION
    assert get_subagent_address("subagent-inspect-d1-abc")["status"] == "completed"


def test_child_exchange_appends_a_new_turn_on_the_same_session(tmp_path):
    first = append_child_exchange(
        tmp_path,
        "child-1",
        user_text="先看日志",
        assistant_text="看完了",
        status="completed",
    )
    second = append_child_exchange(
        tmp_path,
        "child-1",
        user_text="再看一遍",
        assistant_text="还是那场",
        status="completed",
    )

    events = load_turn_events(tmp_path, "child-1")
    assert first and second and first != second
    assert {event.turn_id for event in events if event.event_type == "user_message"} == {first, second}
    assert all(event.session_id == "child-1" for event in events)


def test_parent_progress_is_status_only(tmp_path):
    note_subagent_progress(
        tmp_path,
        "parent-1",
        "turn-parent",
        agent_id="subagent-inspect-d1-abc",
        child_session_id="child-1",
        status="completed",
        delivery="finished",
    )

    events = load_turn_events(tmp_path, "parent-1")
    assert len(events) == 1
    assert events[0].event_type == "subagent_progress"
    assert events[0].visible_in_model is False
    assert events[0].payload["status"] == "completed"
    assert "message" not in events[0].payload


def test_continue_subagent_resumes_the_same_id(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_SUBAGENT_ADDRESS_ROOT", str(tmp_path / "addresses"))
    _record(tmp_path, status="completed")
    seen: dict = {}

    def fake_spawn(**kwargs):
        seen.update(kwargs)
        return json.dumps({"status": "ok", "agentId": kwargs.get("resume_agent_id")})

    monkeypatch.setattr("tools.agent_tools.spawn_agent", fake_spawn)
    from tools.agent_tools import continue_subagent

    payload = json.loads(continue_subagent(to="subagent-inspect-d1-abc", message="接着做"))

    assert payload["agentId"] == "subagent-inspect-d1-abc"
    assert seen["resume_agent_id"] == "subagent-inspect-d1-abc"
    assert seen["_resume_ready"] is True
    assert seen["task"] == "接着做"


def test_resume_keeps_the_message_when_a_summary_is_also_set(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_SUBAGENT_ADDRESS_ROOT", str(tmp_path / "addresses"))
    _record(tmp_path, status="completed")
    seen: dict = {}

    def fake_begin(agent_id, *, ready, message, summary=""):
        seen.update(
            {
                "agent_id": agent_id,
                "ready": ready,
                "message": message,
                "summary": summary,
            }
        )
        return {
            "status": "ok",
            "delivery": "queued",
            "agentId": agent_id,
            "childSessionId": "child-1",
        }

    monkeypatch.setattr("core.orchestration.subagent_address.begin_resume", fake_begin)
    from tools.agent_tools import spawn_agent

    payload = json.loads(
        spawn_agent(
            task="完整的下一句",
            goal="短摘要",
            resume_agent_id="subagent-inspect-d1-abc",
            _resume_ready=True,
        )
    )

    assert payload["delivery"] == "queued"
    assert seen["message"] == "完整的下一句"
    assert seen["summary"] == "短摘要"
    assert seen["ready"] is True


def test_send_message_tool_is_visible_and_spawn_stays_hidden():
    from tools.Key_Tools import create_key_tools

    names = [tool.name for tool in create_key_tools()]

    assert "send_message_tool" in names
    assert "spawn_agent_tool" not in names
