import json
import threading
from concurrent.futures import ThreadPoolExecutor

from core.ui.chat_state import load_chat_state, save_chat_state
from core.web.services import agent_directory_service, chat_room_service, session_service


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
    assert room["purpose"] == "discussion"
    assert [item["id"] for item in room["availablePurposes"]] == ["chat", "discussion", "meeting"]
    assert [item["sessionId"] for item in room["participants"]] == [
        "session-alpha",
        "session-beta",
    ]
    assert room["rounds"] == []


def test_chat_room_purpose_changes_participant_prompt_and_round_payload(tmp_path, monkeypatch):
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
    contexts = []

    def fake_runner(participant, prompt, context):
        prompts.append(prompt)
        contexts.append(context)
        return {
            "status": "completed",
            "raw_output": f"{participant['title']} 自然回应",
            "summary": "ok",
        }

    room = chat_room_service.create_chat_room(
        title="自然聊天群",
        participant_session_ids=["session-alpha", "session-beta"],
        purpose="chat",
    )

    detail = chat_room_service.start_chat_room_round(
        room["roomId"],
        "你们好",
        agent_runner=fake_runner,
    )

    latest_round = detail["rounds"][-1]
    assert room["purpose"] == "chat"
    assert latest_round["purpose"] == "chat"
    assert contexts[0]["purpose"] == "chat"
    assert "对话目的: chat" in prompts[0]
    assert "像真实群聊一样回应当前用户话题" in prompts[0]
    assert "不要写成任务报告" in prompts[0]
    assert "会议协作" not in prompts[0]
    assert any(
        event[0][:3] == ("chat_room", "round", "chat_room.round.completed")
        and event[1]["fields"]["purpose"] == "chat"
        for event in recorded_events
    )


def test_chat_room_update_purpose_and_round_override_are_separate_from_scheduler_mode(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    prompts = []

    def fake_runner(participant, prompt, context):
        prompts.append(prompt)
        return {"status": "completed", "raw_output": "ok", "summary": "ok"}

    room = chat_room_service.create_chat_room(
        title="目的可改群",
        participant_session_ids=["session-alpha", "session-beta"],
        mode="round_robin",
        purpose="discussion",
    )
    updated = chat_room_service.update_chat_room(room["roomId"], purpose="meeting")

    detail = chat_room_service.start_chat_room_round(
        room["roomId"],
        "先开会再闲聊",
        purpose="chat",
        agent_runner=fake_runner,
    )

    latest_round = detail["rounds"][-1]
    assert updated["mode"] == "round_robin"
    assert updated["purpose"] == "meeting"
    assert latest_round["mode"] == "round_robin"
    assert latest_round["purpose"] == "chat"
    assert "对话目的: chat" in prompts[0]


def test_chat_room_list_and_detail_use_lightweight_participant_refresh(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    room = chat_room_service.create_chat_room(
        title="轻量详情群聊",
        participant_session_ids=["session-alpha", "session-beta"],
    )

    def fail_full_session_load(session_id):
        raise AssertionError(f"full session detail should not load for room list/detail: {session_id}")

    monkeypatch.setattr(session_service, "get_session_detail", fail_full_session_load)
    real_list_sessions = session_service.list_sessions
    list_session_calls = 0

    def counting_list_sessions():
        nonlocal list_session_calls
        list_session_calls += 1
        return real_list_sessions()

    monkeypatch.setattr(session_service, "list_sessions", counting_list_sessions)

    listed = chat_room_service.list_chat_rooms()
    detail = chat_room_service.get_chat_room_detail(room["roomId"])

    assert listed[0]["roomId"] == room["roomId"]
    assert [participant["sessionId"] for participant in detail["participants"]] == [
        "session-alpha",
        "session-beta",
    ]
    assert list_session_calls == 2


def test_chat_room_disables_missing_agent_participants(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    recorded_room_events = []
    recorded_session_events = []
    monkeypatch.setattr(
        chat_room_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_room_events.append((args, kwargs)) or {"accepted": True},
    )
    monkeypatch.setattr(
        session_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_session_events.append((args, kwargs)) or {"accepted": True},
    )
    sessions = session_service.list_sessions()
    room = chat_room_service.create_chat_room(
        title="断链群聊",
        participant_session_ids=["session-alpha"],
    )
    state = load_chat_state(tmp_path)
    state["conversations"][0]["agent_id"] = "agent-missing"
    state["conversations"][0]["agentId"] = "agent-missing"
    save_chat_state(tmp_path, state)

    detail = chat_room_service.get_chat_room_detail(room["roomId"])

    assert {item["id"] for item in sessions} == {"session-alpha", "session-beta"}
    assert "session-alpha" not in {item["id"] for item in session_service.list_sessions()}
    participant = detail["participants"][0]
    assert participant["sessionId"] == "session-alpha"
    assert participant["agentMissing"] is True
    assert participant["agentStatusCode"] == "missing_agent"
    assert "缺少有效 Agent" in participant["agentStatusMessage"]
    assert participant["enabled"] is False
    hidden_events = [
        event for event in recorded_session_events
        if event[0][2] == "session.agent_missing.hidden_from_index"
    ]
    assert hidden_events
    assert hidden_events[-1][1]["fields"]["sessionId"] == "session-alpha"
    assert hidden_events[-1][1]["fields"]["agentId"] == "agent-missing"
    assert hidden_events[-1][1]["fields"]["agentStatusCode"] == "missing_agent"
    assert hidden_events[-1][1]["child_log_path"] == "conversations/session-alpha-agent-bindings.jsonl"
    room_missing_events = [
        event for event in recorded_room_events
        if event[0][2] == "chat_room.participant_agent_missing"
    ]
    assert room_missing_events
    assert room_missing_events[-1][1]["fields"]["roomId"] == room["roomId"]
    assert room_missing_events[-1][1]["fields"]["sessionId"] == "session-alpha"
    assert room_missing_events[-1][1]["fields"]["agentId"] == "agent-missing"
    assert room_missing_events[-1][1]["fields"]["agentStatusCode"] == "missing_agent"
    assert room_missing_events[-1][1]["fields"]["enabled"] is False

    try:
        chat_room_service.start_chat_room_round(
            room["roomId"],
            "无效成员不应被调度",
            agent_runner=lambda participant, prompt, context: {"status": "completed"},
        )
    except chat_room_service.ChatRoomValidationError as exc:
        assert "没有可发言" in str(exc)
    else:
        raise AssertionError("missing-agent participant should not be scheduled")


def test_chat_room_event_stream_yields_initial_detail_snapshot(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    room = chat_room_service.create_chat_room(
        title="流式群聊",
        participant_session_ids=["session-alpha", "session-beta"],
    )

    stream = chat_room_service.stream_chat_room_events(room["roomId"])
    try:
        first_event = next(stream)
    finally:
        stream.close()

    assert "event: chat_room_detail" in first_event
    assert f'"roomId": "{room["roomId"]}"' in first_event


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


def test_chat_room_required_supervision_blocks_autonomous_speaker_before_runner(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    alpha = agent_directory_service.ensure_agent_for_session("session-alpha", display_name="Alpha Agent")
    beta = agent_directory_service.ensure_agent_for_session("session-beta", display_name="Beta Agent")
    agent_directory_service.update_agent_instance(
        alpha["agentId"],
        supervision_policy={
            "supervisionEnabled": True,
            "requiresReview": True,
            "reviewMode": "required",
            "evidenceLevel": "strict",
        },
    )
    recorded_events = []
    monkeypatch.setattr(
        agent_directory_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )
    runner_calls = []

    def fake_runner(participant, prompt, context):
        runner_calls.append(participant["agentId"])
        return {
            "status": "completed",
            "raw_output": f"{participant['title']} 发言",
            "summary": "ok",
        }

    room = chat_room_service.create_chat_room(
        title="监督群聊",
        participant_agent_ids=[alpha["agentId"], beta["agentId"]],
    )

    detail = chat_room_service.start_chat_room_round(room["roomId"], "需要审核的群聊发言", agent_runner=fake_runner)

    latest_round = detail["rounds"][-1]
    assert latest_round["status"] == "completed"
    assert [message["status"] for message in latest_round["messages"]] == ["blocked", "completed"]
    blocked = latest_round["messages"][0]
    assert blocked["agentId"] == alpha["agentId"]
    assert blocked["summary"] == "supervision_review_required"
    assert blocked["supervision"]["reviewMode"] == "required"
    assert blocked["supervision"]["evidenceLevel"] == "strict"
    assert runner_calls == [beta["agentId"]]
    assert any(
        event[0][:3] == ("supervision_policy", "execute", "supervision.policy_blocked")
        and event[1]["fields"]["agentId"] == alpha["agentId"]
        and event[1]["fields"]["action"] == "chat_room_speaker"
        for event in recorded_events
    )


def test_chat_room_advisory_supervision_observes_without_blocking(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    alpha = agent_directory_service.ensure_agent_for_session("session-alpha", display_name="Alpha Agent")
    beta = agent_directory_service.ensure_agent_for_session("session-beta", display_name="Beta Agent")
    agent_directory_service.update_agent_instance(
        alpha["agentId"],
        supervision_policy={
            "supervisionEnabled": True,
            "requiresReview": False,
            "reviewMode": "advisory",
            "evidenceLevel": "light",
        },
    )
    recorded_events = []
    monkeypatch.setattr(
        agent_directory_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )

    room = chat_room_service.create_chat_room(
        title="建议监督群聊",
        participant_agent_ids=[alpha["agentId"], beta["agentId"]],
    )

    detail = chat_room_service.start_chat_room_round(
        room["roomId"],
        "建议监督仍允许发言",
        agent_runner=lambda participant, prompt, context: {
            "status": "completed",
            "raw_output": f"{participant['title']} 发言",
            "summary": "ok",
        },
    )

    latest_round = detail["rounds"][-1]
    assert [message["status"] for message in latest_round["messages"]] == ["completed", "completed"]
    assert latest_round["messages"][0]["supervision"]["reviewMode"] == "advisory"
    assert any(
        event[0][:3] == ("supervision_policy", "execute", "supervision.policy_observed")
        and event[1]["fields"]["agentId"] == alpha["agentId"]
        and event[1]["fields"]["action"] == "chat_room_speaker"
        for event in recorded_events
    )


def test_chat_room_participant_runner_reuses_session_workspace_and_agent_profile(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
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

        def seed_runtime_context(self, content):
            captured["runtime_context"] = str(content or "")

        def run_single_turn(self, initial_prompt=None, disable_tools=False):
            return {
                "status": "completed",
                "raw_output": "beta 发言",
                "summary": "ok",
                "tool_call_count": 0,
            }

    monkeypatch.setattr(session_service, "create_chat_agent", ProfileAwareAgent)
    room = chat_room_service.create_chat_room(
        title="会话配置群聊",
        participant_session_ids=["session-beta"],
    )

    detail = chat_room_service.start_chat_room_round(room["roomId"], "按会话配置发言")

    assert detail["participants"][0]["agentProfileId"] == "subagent_explorer"
    agent_id = detail["participants"][0]["agentId"]
    event_path = tmp_path / "workspace" / "agents" / agent_id / "events" / "agent_turn_results.jsonl"
    turn_results = [
        json.loads(line)
        for line in event_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert captured["workspace_path"] == str((tmp_path / "workspace" / "agents" / agent_id).resolve())
    assert captured["primary_model"] == "explorer-model"
    assert f"AgentId: {agent_id}" in captured["runtime_context"]
    assert captured["history"]
    assert turn_results[-1]["agentId"] == agent_id
    assert turn_results[-1]["status"] == "completed"
    assert detail["rounds"][-1]["messages"][0]["status"] == "completed"


def test_update_agent_chat_room_membership_only_changes_selected_agent(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    gamma = session_service.create_chat_session(title="Gamma Agent")
    first_room = chat_room_service.create_chat_room(
        title="第一群聊",
        participant_agent_ids=[alpha["agentId"], beta["agentId"]],
    )
    second_room = chat_room_service.create_chat_room(
        title="第二群聊",
        participant_agent_ids=[beta["agentId"], gamma["agentId"]],
    )

    result = chat_room_service.update_agent_chat_room_membership(
        alpha["agentId"],
        [second_room["roomId"], second_room["roomId"]],
    )

    assert result["roomIds"] == [second_room["roomId"]]
    first_detail = chat_room_service.get_chat_room_detail(first_room["roomId"])
    second_detail = chat_room_service.get_chat_room_detail(second_room["roomId"])
    assert [participant["agentId"] for participant in first_detail["participants"]] == [beta["agentId"]]
    assert [participant["agentId"] for participant in second_detail["participants"]] == [
        beta["agentId"],
        gamma["agentId"],
        alpha["agentId"],
    ]

    repeated = chat_room_service.update_agent_chat_room_membership(alpha["agentId"], [second_room["roomId"]])
    second_detail = chat_room_service.get_chat_room_detail(second_room["roomId"])
    assert repeated["changedRoomIds"] == []
    assert [participant["agentId"] for participant in second_detail["participants"]].count(alpha["agentId"]) == 1


def test_update_agent_chat_room_membership_rejects_unknown_room(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    agent = session_service.create_chat_session(title="Alpha Agent")

    try:
        chat_room_service.update_agent_chat_room_membership(agent["agentId"], ["room-missing"])
    except chat_room_service.ChatRoomValidationError as exc:
        assert "Unknown chat room" in str(exc)
    else:
        raise AssertionError("expected unknown room validation error")


def test_chat_room_participant_waits_for_active_direct_turn_on_same_agent(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    room = chat_room_service.create_chat_room(
        title="同 Agent 串行群聊",
        participant_agent_ids=[alpha["agentId"], beta["agentId"]],
        config={"maxSpeakers": 1},
    )
    assert room["participants"][0]["agentId"] == alpha["agentId"]
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pytest-chat-room-agent-slot")
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", executor)

    direct_started = threading.Event()
    room_started = threading.Event()
    release_direct = threading.Event()
    release_room = threading.Event()
    prompts: list[str] = []

    class BlockingAgent:
        def __init__(self, workspace_path=None, config=None):
            pass

        def seed_chat_history(self, messages):
            pass

        def seed_runtime_context(self, content):
            pass

        def run_single_turn(self, initial_prompt=None, disable_tools=False):
            prompt = str(initial_prompt or "")
            prompts.append(prompt)
            if not disable_tools:
                direct_started.set()
                assert release_direct.wait(2.0)
                return {
                    "status": "completed",
                    "summary": "direct done",
                    "raw_output": "direct done",
                    "outcome": "done",
                    "tool_call_count": 0,
                    "tool_trace": [],
                }
            room_started.set()
            assert release_room.wait(2.0)
            return {
                "status": "completed",
                "summary": "room done",
                "raw_output": "room done",
                "tool_call_count": 0,
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda **kwargs: BlockingAgent())

    try:
        session_service.submit_session_message(alpha["id"], "alpha direct turn")
        assert direct_started.wait(1.0)

        result_holder: dict[str, dict] = {}
        room_thread = threading.Thread(
            target=lambda: result_holder.update(
                detail=chat_room_service.start_chat_room_round(room["roomId"], "群聊也想让 alpha 发言")
            ),
            name="pytest-chat-room-round",
        )
        room_thread.start()

        assert not room_started.wait(0.3)
        release_direct.set()
        assert room_started.wait(2.0), "room speaker should start after the direct turn releases the agent slot"
        release_room.set()
        room_thread.join(timeout=2.0)
    finally:
        release_direct.set()
        release_room.set()
        executor.shutdown(wait=True, cancel_futures=True)

    assert not room_thread.is_alive()
    assert result_holder["detail"]["rounds"][-1]["status"] == "completed"
    assert prompts[0] == "alpha direct turn"
    assert "群聊也想让 alpha 发言" in prompts[1]


def test_chat_room_waiting_speaker_keeps_fifo_before_later_direct_turn(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    state = load_chat_state(tmp_path)
    for conversation in state["conversations"]:
        if conversation["conversation_id"] == beta["id"]:
            conversation["agent_id"] = alpha["agentId"]
            conversation["agentId"] = alpha["agentId"]
    save_chat_state(tmp_path, state)
    room = chat_room_service.create_chat_room(
        title="同 Agent FIFO 群聊",
        participant_agent_ids=[alpha["agentId"], session_service.create_chat_session(title="Gamma Agent")["agentId"]],
        config={"maxSpeakers": 1},
    )
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pytest-chat-room-fifo")
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", executor)

    first_direct_started = threading.Event()
    room_started = threading.Event()
    second_direct_started = threading.Event()
    release_first_direct = threading.Event()
    release_room = threading.Event()
    release_second_direct = threading.Event()
    run_order: list[str] = []

    class BlockingAgent:
        def __init__(self, workspace_path=None, config=None):
            pass

        def seed_chat_history(self, messages):
            pass

        def seed_runtime_context(self, content):
            pass

        def run_single_turn(self, initial_prompt=None, disable_tools=False):
            prompt = str(initial_prompt or "")
            if disable_tools:
                run_order.append("room")
                room_started.set()
                assert release_room.wait(2.0)
                return {"status": "completed", "summary": "room done", "raw_output": "room done"}
            if "first direct" in prompt:
                run_order.append("first_direct")
                first_direct_started.set()
                assert release_first_direct.wait(2.0)
                return {
                    "status": "completed",
                    "summary": "first direct done",
                    "raw_output": "first direct done",
                    "outcome": "done",
                    "tool_call_count": 0,
                    "tool_trace": [],
                }
            run_order.append("second_direct")
            second_direct_started.set()
            assert release_second_direct.wait(2.0)
            return {
                "status": "completed",
                "summary": "second direct done",
                "raw_output": "second direct done",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda **kwargs: BlockingAgent())

    try:
        session_service.submit_session_message(alpha["id"], "alpha first direct")
        assert first_direct_started.wait(1.0)

        result_holder: dict[str, dict] = {}
        room_thread = threading.Thread(
            target=lambda: result_holder.update(
                detail=chat_room_service.start_chat_room_round(room["roomId"], "群聊排在第二个")
            ),
            name="pytest-chat-room-fifo-round",
        )
        room_thread.start()
        assert not room_started.wait(0.3)

        queued_direct = session_service.submit_session_message(beta["id"], "beta second direct")
        assert queued_direct["currentPhase"] == "queued"
        assert not second_direct_started.wait(0.3)

        release_first_direct.set()
        assert room_started.wait(2.0)
        assert not second_direct_started.wait(0.3)
        release_room.set()
        assert second_direct_started.wait(2.0)
        release_second_direct.set()
        room_thread.join(timeout=2.0)
    finally:
        release_first_direct.set()
        release_room.set()
        release_second_direct.set()
        executor.shutdown(wait=True, cancel_futures=True)

    assert not room_thread.is_alive()
    assert result_holder["detail"]["rounds"][-1]["status"] == "completed"
    assert run_order == ["first_direct", "room", "second_direct"]


def test_force_stop_chat_room_round_cancels_waiting_agent_slot(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    room = chat_room_service.create_chat_room(
        title="等待中的群聊",
        participant_agent_ids=[alpha["agentId"], beta["agentId"]],
        config={"maxSpeakers": 1},
    )
    session_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="pytest-chat-room-stop-session")
    room_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pytest-chat-room-stop-room")
    monkeypatch.setattr(session_service, "_SESSION_EXECUTOR", session_executor)
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_EXECUTOR", room_executor)

    direct_started = threading.Event()
    room_started = threading.Event()
    release_direct = threading.Event()

    class BlockingAgent:
        def __init__(self, workspace_path=None, config=None):
            pass

        def seed_chat_history(self, messages):
            pass

        def seed_runtime_context(self, content):
            pass

        def set_turn_interrupt_checker(self, checker):
            self.checker = checker

        def run_single_turn(self, initial_prompt=None, disable_tools=False):
            if disable_tools:
                room_started.set()
                return {"status": "completed", "summary": "room should not run", "raw_output": "room should not run"}
            direct_started.set()
            assert release_direct.wait(2.0)
            return {
                "status": "completed",
                "summary": "direct done",
                "raw_output": "direct done",
                "outcome": "done",
                "tool_call_count": 0,
                "tool_trace": [],
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda **kwargs: BlockingAgent())

    try:
        session_service.submit_session_message(alpha["id"], "alpha direct")
        assert direct_started.wait(1.0)
        detail = chat_room_service.start_chat_room_round(room["roomId"], "等待 direct 后发言", background=True)
        round_id = detail["activeRoundId"]
        assert round_id
        assert not room_started.wait(0.3)

        stopped = chat_room_service.force_stop_active_chat_room_rounds_for_shutdown("pytest shutdown")

        assert stopped == [
            {
                "kind": "chat_room_round",
                "roomId": room["roomId"],
                "runId": round_id,
                "roundId": round_id,
                "status": "stopped",
            }
        ]
        release_direct.set()
        assert not room_started.wait(0.5), "stopped queued room speaker must not start after direct turn releases"
    finally:
        release_direct.set()
        session_executor.shutdown(wait=True, cancel_futures=True)
        room_executor.shutdown(wait=True, cancel_futures=True)

    final_detail = chat_room_service.get_chat_room_detail(room["roomId"])
    assert final_detail["status"] == "ready"
    assert final_detail["activeRoundId"] == ""
    assert final_detail["rounds"][-1]["status"] == "stopped"
    assert "pytest shutdown" in final_detail["rounds"][-1]["summary"]
    assert chat_room_service.load_chat_room_work_run_summary()["active"] is None


def test_stop_chat_room_round_enters_stopping_then_publishes_ready_detail(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    recorded_events = []
    monkeypatch.setattr(
        chat_room_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )

    room = chat_room_service.create_chat_room(
        title="可停止群聊",
        participant_session_ids=["session-alpha", "session-beta"],
    )

    runner_started = threading.Event()
    release_runner = threading.Event()

    def blocking_runner(participant, prompt, context):
        runner_started.set()
        assert release_runner.wait(2.0)
        return {"status": "completed", "raw_output": "late response", "summary": "late"}

    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pytest-chat-room-user-stop")
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_EXECUTOR", executor)

    try:
        started = chat_room_service.start_chat_room_round(
            room["roomId"],
            "需要停止的讨论",
            agent_runner=blocking_runner,
            background=True,
        )
        assert runner_started.wait(1.0)

        stopped = chat_room_service.stop_chat_room_round(room["roomId"], reason="pytest user stop")

        assert started["activeRoundId"]
        assert stopped["status"] == "stopping"
        assert stopped["activeRoundId"] == started["activeRoundId"]
        latest_round = stopped["rounds"][-1]
        assert latest_round["roundId"] == started["activeRoundId"]
        assert latest_round["status"] == "stopping"
        assert latest_round["finishedAt"] == ""
        assert chat_room_service.load_chat_room_work_run_summary()["active"]["status"] == "stopping"
        stop_requested_events = [
            event
            for event in recorded_events
            if event[0][:3] == ("chat_room", "round", "chat_room.round.stop_requested")
        ]
        assert len(stop_requested_events) == 1
        assert stop_requested_events[0][1]["outcome"] == "stopping"
        assert stop_requested_events[0][1]["lifecycle"] is True
        assert stop_requested_events[0][1]["fields"]["roomId"] == room["roomId"]
        assert stop_requested_events[0][1]["fields"]["roundId"] == started["activeRoundId"]
        assert stop_requested_events[0][1]["fields"]["reason"] == "pytest user stop"
    finally:
        release_runner.set()
        executor.shutdown(wait=True, cancel_futures=True)

    final_detail = chat_room_service.get_chat_room_detail(room["roomId"])
    assert final_detail["status"] == "ready"
    assert final_detail["activeRoundId"] == ""
    assert final_detail["rounds"][-1]["status"] == "stopped"
    assert "pytest user stop" in final_detail["rounds"][-1]["summary"]
    assert chat_room_service.load_chat_room_work_run_summary()["active"] is None


def test_stop_chat_room_round_rejects_room_without_active_round(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    room = chat_room_service.create_chat_room(title="空闲群聊", participant_session_ids=["session-alpha"])

    try:
        chat_room_service.stop_chat_room_round(room["roomId"])
    except chat_room_service.ChatRoomBusyError as exc:
        assert "没有正在运行" in str(exc)
    else:
        raise AssertionError("idle chat room stop should fail")


def test_opportunistic_chat_room_mode_prioritizes_configured_speakers(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    room = chat_room_service.create_chat_room(
        title="扩展模式",
        participant_session_ids=["session-alpha", "session-beta"],
        mode="opportunistic",
        config={
            "prioritySessionIds": ["session-beta"],
            "maxSpeakers": 1,
        },
    )

    modes = chat_room_service.list_chat_room_modes()

    assert {item["id"]: item["status"] for item in modes}["round_robin"] == "ready"
    assert {item["id"]: item["status"] for item in modes}["opportunistic"] == "ready"

    detail = chat_room_service.start_chat_room_round(
        room["roomId"],
        "抢占式讨论",
        agent_runner=lambda participant, prompt, context: {
            "status": "completed",
            "raw_output": f"{participant['title']} 抢先发言",
            "summary": "ok",
        },
    )

    latest_round = detail["rounds"][-1]
    assert latest_round["mode"] == "opportunistic"
    assert latest_round["speakerOrder"] == ["session-session-beta"]
    assert [message["sessionId"] for message in latest_round["messages"]] == ["session-beta"]


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
