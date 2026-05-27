from core.ui.chat_state import load_chat_state, save_chat_state
from core.web.services import chat_room_service, session_service


def _seed_chat_sessions(root):
    save_chat_state(
        root,
        {
            "version": 1,
            "active_conversation_id": "session-alpha",
            "conversations": [
                {
                    "conversation_id": "session-alpha",
                    "title": "Alpha Agent",
                    "updated_at": "2026-05-26T10:00:00",
                    "messages": [
                        {"role": "user", "content": "先看 API", "timestamp": "2026-05-26T10:00:00"},
                        {"role": "assistant", "content": "API 线索已记录。", "timestamp": "2026-05-26T10:01:00"},
                    ],
                },
                {
                    "conversation_id": "session-beta",
                    "title": "Beta Agent",
                    "updated_at": "2026-05-26T10:02:00",
                    "messages": [
                        {"role": "user", "content": "先看 UI", "timestamp": "2026-05-26T10:02:00"},
                        {"role": "assistant", "content": "UI 线索已记录。", "timestamp": "2026-05-26T10:03:00"},
                    ],
                },
            ],
        },
    )


def test_create_chat_room_defaults_to_existing_sessions(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)

    room = chat_room_service.create_chat_room(title="方案群聊")

    assert room["title"] == "方案群聊"
    assert room["mode"] == "round_robin"
    assert [item["sessionId"] for item in room["participants"]] == [
        "session-alpha",
        "session-beta",
    ]
    assert room["rounds"] == []


def test_start_chat_room_round_runs_participants_in_round_robin_and_persists_work_run(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    recorded_events = []
    monkeypatch.setattr(
        chat_room_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )
    prompts = []

    def fake_runner(participant, prompt, context):
        prompts.append((participant["sessionId"], prompt, context["mode"]))
        return {
            "status": "completed",
            "raw_output": f"{participant['title']} 对 {context['topic']} 的发言",
            "summary": f"{participant['title']} 已发言",
        }

    room = chat_room_service.create_chat_room(
        title="轮询讨论",
        participant_session_ids=["session-beta", "session-alpha"],
    )

    detail = chat_room_service.start_chat_room_round(
        room["roomId"],
        "讨论群聊 MVP 怎么切第一版",
        agent_runner=fake_runner,
    )

    latest_round = detail["rounds"][-1]
    assert latest_round["status"] == "completed"
    assert latest_round["mode"] == "round_robin"
    assert [message["sessionId"] for message in latest_round["messages"]] == [
        "session-beta",
        "session-alpha",
    ]
    assert len({message["messageId"] for message in latest_round["messages"]}) == 2
    assert all(message["status"] == "completed" for message in latest_round["messages"])
    assert prompts[0][0] == "session-beta"
    assert "讨论群聊 MVP 怎么切第一版" in prompts[0][1]
    assert prompts[0][2] == "round_robin"

    work_run_summary = chat_room_service.load_chat_room_work_run_summary()
    assert work_run_summary["active"] is None
    assert work_run_summary["latest"]["runKind"] == "chat_room_round"
    assert work_run_summary["latest"]["status"] == "completed"
    assert work_run_summary["latest"]["roomId"] == room["roomId"]
    assert any(
        event[0][:3] == ("chat_room", "round", "chat_room.round.completed")
        for event in recorded_events
    )


def test_chat_room_participant_runner_reuses_session_workspace_and_agent_profile(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    state = load_chat_state(tmp_path)
    state["conversations"][1]["agent_profile_id"] = "subagent_explorer"
    save_chat_state(tmp_path, state)
    base_config = session_service.get_config().model_copy(deep=True)
    base_config.llm.profiles["subagent_explorer"] = base_config.llm.profiles["primary"].model_copy(deep=True)
    base_config.llm.profiles["subagent_explorer"].profile_id = "subagent_explorer"
    base_config.llm.profiles["subagent_explorer"].model = "explorer-model"
    monkeypatch.setattr(session_service, "get_config", lambda: base_config)
    captured = {}

    class ProfileAwareAgent:
        def __init__(self, workspace_path=None, config=None):
            captured["workspace_path"] = str(workspace_path or "")
            captured["primary_model"] = config.llm.get_profile(role="primary").model

        def seed_chat_history(self, messages):
            captured["history"] = list(messages)

        def run_single_turn(self, initial_prompt=None, disable_tools=False):
            return {
                "status": "completed",
                "raw_output": "beta 发言",
                "summary": "ok",
            }

    monkeypatch.setattr(session_service, "create_chat_agent", ProfileAwareAgent)
    room = chat_room_service.create_chat_room(
        title="会话配置群聊",
        participant_session_ids=["session-beta"],
    )

    detail = chat_room_service.start_chat_room_round(room["roomId"], "按会话配置发言")

    assert detail["participants"][0]["agentProfileId"] == "subagent_explorer"
    assert captured["workspace_path"] == str((tmp_path / "workspace" / "sessions" / "session-beta").resolve())
    assert captured["primary_model"] == "explorer-model"
    assert captured["history"]
    assert detail["rounds"][-1]["messages"][0]["status"] == "completed"


def test_planned_chat_room_modes_are_listed_but_not_runnable_yet(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    room = chat_room_service.create_chat_room(title="扩展模式", participant_session_ids=["session-alpha"])

    modes = chat_room_service.list_chat_room_modes()

    assert {item["id"]: item["status"] for item in modes}["round_robin"] == "ready"
    assert {item["id"]: item["status"] for item in modes}["opportunistic"] == "planned"
    try:
        chat_room_service.start_chat_room_round(room["roomId"], "抢占式讨论", mode="opportunistic")
    except chat_room_service.ChatRoomValidationError as exc:
        assert "not ready" in str(exc)
    else:
        raise AssertionError("planned mode should not run yet")


def test_round_config_limits_speakers_without_dropping_room_participants(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)

    room = chat_room_service.create_chat_room(
        title="限流群聊",
        participant_session_ids=["session-alpha", "session-beta"],
        config={"maxSpeakers": 1},
    )

    detail = chat_room_service.start_chat_room_round(
        room["roomId"],
        "只让一位先发言",
        agent_runner=lambda participant, prompt, context: {
            "status": "completed",
            "raw_output": f"{participant['title']} 已发言",
            "summary": "ok",
        },
    )

    latest_round = detail["rounds"][-1]
    assert [message["sessionId"] for message in latest_round["messages"]] == ["session-alpha"]
    assert [participant["sessionId"] for participant in detail["participants"]] == [
        "session-alpha",
        "session-beta",
    ]


def test_update_chat_room_replaces_participants_without_losing_round_history(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    room = chat_room_service.create_chat_room(
        title="待调整群聊",
        participant_session_ids=["session-alpha"],
    )
    detail = chat_room_service.start_chat_room_round(
        room["roomId"],
        "先让 alpha 发言",
        agent_runner=lambda participant, prompt, context: {
            "status": "completed",
            "raw_output": "alpha 已发言",
            "summary": "ok",
        },
    )

    updated = chat_room_service.update_chat_room(
        detail["roomId"],
        title="调整后的群聊",
        participant_session_ids=["session-beta"],
    )

    assert updated["title"] == "调整后的群聊"
    assert [participant["sessionId"] for participant in updated["participants"]] == ["session-beta"]
    assert len(updated["rounds"]) == 1
    assert updated["rounds"][0]["messages"][0]["sessionId"] == "session-alpha"


def test_delete_chat_room_removes_room(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    room = chat_room_service.create_chat_room(title="删除群聊", participant_session_ids=["session-alpha"])

    result = chat_room_service.delete_chat_room(room["roomId"])

    assert result == {"deleted": True, "roomId": room["roomId"]}
    assert chat_room_service.get_chat_room_detail(room["roomId"]) is None
