import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
import pytest

from agent import SelfEvolvingAgent
from core.agent_kernel import service as agent_kernel_service
from core.chat.conversation_ledger import (
    EVENT_ASSISTANT_MESSAGE,
    EVENT_USER_MESSAGE,
    append_conversation_event,
    conversation_visible_messages_from_events,
    load_conversation_events,
)
from core.chatroom import store as chat_room_store
from core.chatroom.scheduler import get_scheduler_registry
from core.infrastructure import developer_sandbox
from core.runtime_manager import work_run_store
from core.ui.chat_state import load_chat_state, save_chat_state
from core.web.services import agent_directory_service, chat_room_service, session_service
from core.web.services.team_workflow.research_runtime import meeting_receipt_authority

from tests.helpers.chat_turn_harness import wait_for_matching_event


def test_chat_room_executor_allows_four_concurrent_rounds() -> None:
    assert chat_room_service._CHAT_ROOM_EXECUTOR_MAX_WORKERS == 4


def _append_session_ledger_message(root, session_id: str, message: dict, *, turn_id: str) -> None:
    role = str(message.get("role") or "").strip().lower()
    append_conversation_event(
        root,
        session_id,
        turn_id,
        EVENT_USER_MESSAGE if role == "user" else EVENT_ASSISTANT_MESSAGE,
        status="recorded" if role == "user" else "completed",
        payload={
            "content": str(message.get("content") or ""),
            "metadata": dict(message.get("metadata") or {}) if isinstance(message.get("metadata"), dict) else {},
        },
        timestamp=str(message.get("timestamp") or ""),
    )


def _session_ledger_messages(root, session_id: str) -> list[dict]:
    return conversation_visible_messages_from_events(load_conversation_events(root, session_id))


def _has_room_transcript(root, session_id: str, room_id: str) -> bool:
    return any(
        (message.get("metadata") or {}).get("sourceRoomId") == room_id
        for message in _session_ledger_messages(root, session_id)
        if isinstance(message, dict)
    )


def _seed_chat_sessions(root):
    seed_messages = {
        "session-alpha": [
            {"role": "user", "content": "先看 API", "timestamp": "2026-05-26T10:00:00"},
            {"role": "assistant", "content": "API 线索已记录。", "timestamp": "2026-05-26T10:01:00"},
        ],
        "session-beta": [
            {"role": "user", "content": "先看 UI", "timestamp": "2026-05-26T10:02:00"},
            {"role": "assistant", "content": "UI 线索已记录。", "timestamp": "2026-05-26T10:03:00"},
        ],
    }
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
                },
                {
                    "conversation_id": "session-beta",
                    "title": "Beta Agent",
                    "updated_at": "2026-05-26T10:02:00",
                },
            ],
        },
    )
    for session_id, messages in seed_messages.items():
        for index, message in enumerate(messages, start=1):
            _append_session_ledger_message(root, session_id, message, turn_id=f"{session_id}-seed-{index}")


def _isolate_chat_room_kernel(tmp_path, monkeypatch):
    data_home = tmp_path / "operator-data"
    work_runs_root = tmp_path / "work_runs"
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(data_home))
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.meeting_receipt_authority.workflow_run_stop_reason",
        lambda _authority: "",
    )
    monkeypatch.setattr(agent_kernel_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(developer_sandbox, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(developer_sandbox, "resolve_workspace_home", lambda *args, **kwargs: data_home / "workspace")
    monkeypatch.setattr(work_run_store, "WORK_RUNS_DIR", work_runs_root)


def _install_chat_room_test_llm_config(monkeypatch, model_id: str = "chat-room-test-model") -> dict[str, dict[str, str]]:
    base_config = session_service.get_config().model_copy(deep=True)
    try:
        provider_id = str(
            base_config.llm.get_profile(profile_id=session_service.DEFAULT_SESSION_AGENT_PROFILE_ID).provider_id or ""
        ).strip()
    except Exception:
        provider_id = ""
    if not provider_id or provider_id not in base_config.llm.providers:
        provider_id = next(iter(base_config.llm.providers.keys()), "default")
    base_config.llm.model_library[model_id] = {
        "provider_id": provider_id,
        "model": "chat-room-test-model",
        "streaming": False,
        "tool_calling_mode": "disabled",
    }
    monkeypatch.setattr(session_service, "get_config", lambda: base_config)
    monkeypatch.setattr(
        session_service,
        "_session_llm_model_choices",
        lambda: [
            {
                "modelId": model_id,
                "modelRef": model_id,
                "providerId": provider_id,
                "provider": provider_id,
                "model": "chat-room-test-model",
                "label": "Chat room test model",
                "reasoningEffortValues": [],
                "reasoningEffortOptions": [],
                "defaultReasoningEffort": "",
            }
        ],
    )
    return {"dialogue": {"modelId": model_id}}


def _capture_session_lifecycle_events(monkeypatch):
    events = []
    condition = threading.Condition()

    def record_session_turn_lifecycle_event(session_id, phase, **kwargs):
        event = {
            "session_id": session_id,
            "phase": phase,
            "turn_id": kwargs.get("turn_id", ""),
            "outcome": kwargs.get("outcome", ""),
            "fields": dict(kwargs.get("fields") or {}),
        }
        with condition:
            events.append(event)
            condition.notify_all()

    def wait_for_phase(phase, *, timeout=10.0, fields=None):
        expected_fields = fields or {}
        return wait_for_matching_event(
            events,
            timeout_s=timeout,
            predicate=lambda event: (
                event["phase"] == phase
                and all(
                    event["fields"].get(key) == value
                    for key, value in expected_fields.items()
                )
            ),
            condition=condition,
        )

    monkeypatch.setattr(session_service, "_record_session_turn_lifecycle_event", record_session_turn_lifecycle_event)
    return wait_for_phase, events


def _lightweight_agent_context(*args, **kwargs):
    return SimpleNamespace(agent_id="", profile_id="", memory_policy={}, context_block="", timings={})


def test_chat_room_store_retries_transient_permission_error(tmp_path, monkeypatch):
    store = chat_room_store.ChatRoomStore(root=tmp_path)
    real_replace = chat_room_store.os.replace
    attempts: list[str] = []

    def flaky_replace(source, target):
        attempts.append(str(target))
        if len(attempts) == 1:
            raise PermissionError("locked")
        return real_replace(source, target)

    monkeypatch.setattr(chat_room_store.os, "replace", flaky_replace)

    store.save({"rooms": [{"roomId": "room-a"}]})

    assert len(attempts) == 2
    assert store.state_path.exists()
    assert store.load()["rooms"][0]["roomId"] == "room-a"


def test_group_speaker_message_uses_completion_time_and_strips_self_prefix(monkeypatch):
    timestamps = iter(["2026-05-29T12:00:30+00:00"])
    monkeypatch.setattr(chat_room_service, "utc_now_iso", lambda: next(timestamps))

    participant = {
        "participantId": "session-alpha",
        "agentId": "agent-alpha",
        "agentCode": "A012",
        "sessionId": "session-alpha",
        "title": "组织顾问 Agent",
    }

    def fake_runner(_participant, _prompt, _context):
        return {
            "status": "completed",
            "raw_output": "A012 · 江知微：收到，夏总。",
            "summary": "A012 · 江知微：收到，夏总。",
        }

    message = chat_room_service._run_one_speaker(
        participant,
        "prompt",
        {"roundId": "round-alpha", "speakerStartedAtMonotonic": chat_room_service._perf_counter()},
        fake_runner,
    )

    assert message["timestamp"] == "2026-05-29T12:00:30+00:00"
    assert message["content"] == "收到，夏总。"
    assert message["summary"] == "收到，夏总。"


def test_participant_speaker_label_prefers_code_without_role_suffix():
    assert chat_room_service._participant_speaker_label(
        {"participantId": "session-alpha", "agentCode": "A012", "title": "组织顾问 Agent"}
    ) == "A012"
    assert chat_room_service._participant_speaker_label(
        {"participantId": "session-alpha", "title": "搜索 Agent"}
    ) == "搜索 Agent"
    assert chat_room_service._participant_speaker_label({"participantId": "session-alpha"}) == "session-alpha"


def test_group_speaker_marks_team_discussion_internal_when_case_discusses():
    participant = {
        "participantId": "session-alpha",
        "agentId": "agent-alpha",
        "agentCode": "A012",
        "sessionId": "session-alpha",
        "title": "组织顾问 Agent",
    }

    def fake_runner(_participant, _prompt, _context):
        return {"status": "completed", "raw_output": "建议先形成方案。", "summary": "ok"}

    message = chat_room_service._run_one_speaker(
        participant,
        "prompt",
        {
            "roundId": "round-alpha",
            "speakerStartedAtMonotonic": chat_room_service._perf_counter(),
            "caseState": {
                "nextAction": "discuss",
                "userFacingMode": "team_discussion",
                "discussionVisibility": "collapsed_by_default",
            },
        },
        fake_runner,
    )

    assert message["messageKind"] == "team_discussion"
    assert message["audience"] == "internal"
    assert message["visibility"] == "collapsed_by_default"


def test_room_to_api_normalizes_legacy_case_state_and_message_visibility():
    room = {
        "roomId": "room-legacy",
        "title": "旧问诊群",
        "mode": "round_robin",
        "purpose": "meeting",
        "participants": [],
        "rounds": [
            {
                "roundId": "round-legacy",
                "roomId": "room-legacy",
                "topic": "孩子晚上经常哭泣是为什么？",
                "mode": "round_robin",
                "purpose": "meeting",
                "caseState": {
                    "intent": "maternal_child_consultation_demo",
                    "nextAction": "ask_user",
                    "missingFacts": ["年龄/月龄", "体温或发热情况", "伴随症状", "既往史/用药/过敏史"],
                    "riskFlags": [],
                },
                "messages": [
                    {
                        "messageId": "message-legacy",
                        "participantId": "host",
                        "sessionId": "session-host",
                        "speakerTitle": "方案主持 Agent",
                        "status": "completed",
                        "content": "先补充信息。",
                        "summary": "",
                        "timestamp": "2026-06-01T00:00:00+00:00",
                    }
                ],
            }
        ],
    }

    payload = chat_room_service._room_to_api(room)
    case_state = payload["rounds"][0]["caseState"]
    message = payload["rounds"][0]["messages"][0]

    assert case_state["nextAction"] == "clarify"
    assert case_state["informationSufficiency"] == "insufficient"
    assert case_state["userFacingMode"] == "direct_clarification"
    assert case_state["discussionVisibility"] == "user_visible"
    assert message["messageKind"] == "user_clarification"
    assert message["audience"] == "user"


def test_group_speaker_strips_ui_identity_prefix_and_prompt_uses_role_view():
    participant = {
        "participantId": "session-advisor",
        "agentId": "agent-advisor",
        "agentCode": "A012",
        "sessionId": "session-advisor",
        "title": "组织顾问 Agent",
        "teamId": "research-team",
        "teamName": "科研团队",
        "teamPurpose": "组织科研 agent",
        "teamRole": "organization_advisor",
        "teamMemberPurpose": "科研组织顾问",
        "teamResponsibilities": ["拆解研究组织结构", "提醒协作边界"],
    }

    prompt = chat_room_service._build_participant_prompt(
        room={"roomId": "room-research", "title": "科研团队 团队群聊", "purpose": "discussion"},
        round_payload={"topic": "请补充研究方向", "mode": "round_robin", "purpose": "discussion"},
        participant=participant,
        prior_messages=[],
    )

    assert "你的身份:" not in prompt
    assert "A012 · 组织顾问 Agent" not in prompt
    assert "你的发言视角: organization_advisor / 科研组织顾问" in prompt
    assert "所属团队: 科研团队" in prompt
    assert "团队目标: 组织科研 agent" in prompt
    assert "岗位职责: 科研组织顾问" in prompt
    assert "职责清单: 拆解研究组织结构；提醒协作边界" in prompt
    assert "不是普通直连会话 Agent" in prompt
    assert "不要在正文开头写 Agent 编号、姓名、职位、标题" in prompt
    assert chat_room_service._strip_redundant_speaker_prefix(
        "A012 · 组织顾问 Agent：认同CEO锚定方向优先的思路。",
        participant,
    ) == "认同CEO锚定方向优先的思路。"
    assert chat_room_service._strip_redundant_speaker_prefix(
        "**A012 · 组织顾问 Agent**：先搭骨架，再填血肉。",
        participant,
    ) == "先搭骨架，再填血肉。"


def test_casual_group_topic_uses_chat_purpose_for_one_round():
    assert chat_room_service._resolve_round_purpose("你们好", "discussion") == "chat"
    assert chat_room_service._resolve_round_purpose("讨论近期科研方向", "discussion") == "discussion"


def test_create_chat_room_defaults_to_sessions_in_recent_activity_order(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)

    room = chat_room_service.create_chat_room(title="方案群聊")

    assert room["title"] == "方案群聊"
    assert room["mode"] == "round_robin"
    assert room["purpose"] == "discussion"
    assert room["availablePurposes"] == chat_room_service.list_chat_room_purposes()
    assert [item["sessionId"] for item in room["participants"]] == [
        "session-beta",
        "session-alpha",
    ]
    assert room["rounds"] == []


def test_create_chat_room_resolves_explicit_hidden_team_agent_session(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    agent = agent_directory_service.create_agent_instance(
        display_name="资料发现",
        direct_session_id="session-hidden-team-agent",
        primary_mode="research",
        role_key="source_finder",
        created_by="challenge_cup_team",
    )
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": "",
            "conversations": [
                {
                    "conversation_id": "session-hidden-team-agent",
                    "title": "资料发现",
                    "agent_id": agent["agentId"],
                    "agentId": agent["agentId"],
                    "conversation_index_kind": "team_agent",
                    "conversationIndexKind": "team_agent",
                    "hidden_from_index": True,
                    "hiddenFromIndex": True,
                    "session_kind": "main",
                    "sessionKind": "main",
                }
            ],
        },
    )

    monkeypatch.setattr(session_service, "list_sessions", lambda *args, **kwargs: [])

    room = chat_room_service.create_chat_room(
        title="挑战杯团队群聊",
        participant_session_ids=["session-hidden-team-agent"],
    )

    assert [participant["sessionId"] for participant in room["participants"]] == ["session-hidden-team-agent"]
    assert room["participants"][0]["agentId"] == agent["agentId"]


def test_list_chat_rooms_compact_does_not_hydrate_sessions_or_agents(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    room = chat_room_service.create_chat_room(title="Compact room")

    monkeypatch.setattr(
        session_service,
        "list_sessions",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("compact list should not scan sessions")),
    )
    monkeypatch.setattr(
        agent_directory_service,
        "list_agents",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("compact list should not scan agents")),
    )
    monkeypatch.setattr(
        agent_directory_service,
        "get_agent",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("compact list should not hydrate agents")),
    )

    rooms = chat_room_service.list_chat_rooms_compact()

    assert [item["roomId"] for item in rooms] == [room["roomId"]]
    assert [item["sessionId"] for item in rooms[0]["participants"]] == ["session-beta", "session-alpha"]


def test_list_chat_rooms_for_conversation_index_does_not_repair_participants_by_default(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    room = chat_room_service.create_chat_room(title="conversation-index-light")

    repair_calls = 0

    def fake_repair_room_participants_in_state(state, **kwargs):
        nonlocal repair_calls
        repair_calls += 1
        return True

    session_list_calls = 0
    real_list_sessions = session_service.list_sessions

    def counting_list_sessions(*args, **kwargs):
        nonlocal session_list_calls
        session_list_calls += 1
        return real_list_sessions(*args, **kwargs)

    monkeypatch.setattr(chat_room_service, "_repair_room_participants_in_state", fake_repair_room_participants_in_state)
    monkeypatch.setattr(session_service, "list_sessions", counting_list_sessions)

    listed = chat_room_service.list_chat_rooms_for_conversation_index()

    assert [item["roomId"] for item in listed] == [room["roomId"]]
    assert repair_calls == 0
    assert session_list_calls == 0


def test_list_chat_rooms_for_conversation_index_repair_participants_when_enabled(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    room = chat_room_service.create_chat_room(title="conversation-index-heavy")

    repair_calls = 0

    def fake_repair_room_participants_in_state(state, **kwargs):
        nonlocal repair_calls
        repair_calls += 1
        return True

    session_list_calls = 0
    real_list_sessions = session_service.list_sessions

    def counting_list_sessions(*args, **kwargs):
        nonlocal session_list_calls
        session_list_calls += 1
        return real_list_sessions(*args, **kwargs)

    monkeypatch.setattr(chat_room_service, "_repair_room_participants_in_state", fake_repair_room_participants_in_state)
    monkeypatch.setattr(session_service, "list_sessions", counting_list_sessions)

    listed = chat_room_service.list_chat_rooms_for_conversation_index(repair_room_participants=True)

    assert [item["roomId"] for item in listed] == [room["roomId"]]
    assert repair_calls == 1
    assert session_list_calls == 1


def test_list_chat_rooms_skips_participant_repair_on_index_surface(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    room = chat_room_service.create_chat_room(
        title="索引面群聊",
        participant_session_ids=["session-alpha", "session-beta"],
    )

    monkeypatch.setattr(
        chat_room_service,
        "_repair_room_participants_in_state",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("chat room list should not block on participant repair")
        ),
    )

    rooms = chat_room_service.list_chat_rooms()

    assert [item["roomId"] for item in rooms] == [room["roomId"]]


def test_room_to_conversation_index_reference_uses_latest_round_summary():
    room = {
        "roomId": "room-index",
        "title": "聚焦群聊",
        "status": "ready",
        "updatedAt": "2026-06-13T10:00:00",
        "mode": "round_robin",
        "rounds": [
            {"roundId": "round-1", "summary": "第一轮总结"},
            {"roundId": "round-2", "summary": "第二轮总结"},
        ],
        "participants": [{"agentId": "agent-a"}, {"sessionId": "session-alpha"}],
    }

    payload = chat_room_service._room_to_conversation_index_reference(room)

    assert payload["summary"] == "第二轮总结"
    assert payload["mode"] == "round_robin"
    assert payload["participants"] == [{"agentId": "agent-a"}, {"sessionId": "session-alpha"}]


def test_medical_consultation_mode_prioritizes_host_risk_and_intake():
    scheduler = get_scheduler_registry().get("medical_consultation_panel")

    speakers = scheduler.select_speakers(
        [
            {"participantId": "specialist", "teamRole": "专科顾问", "enabled": True},
            {"participantId": "intake", "teamRole": "症状采集员", "enabled": True},
            {"participantId": "host", "teamRole": "问诊主持", "enabled": True},
            {"participantId": "risk", "teamRole": "风险分诊员", "enabled": True},
            {"participantId": "summary", "teamRole": "结果整理员", "enabled": True},
        ],
        topic="用户说胸口发闷，应该怎么办？",
        history=[],
        config={},
    )

    assert [item["participantId"] for item in speakers] == [
        "host",
        "risk",
        "intake",
        "specialist",
        "summary",
    ]


def test_medical_triage_prompt_keeps_safe_user_facing_boundary():
    participant = {
        "participantId": "session-host",
        "agentId": "agent-host",
        "agentCode": "M001",
        "sessionId": "session-host",
        "title": "问诊主持 Agent",
        "teamName": "医疗问诊团队",
        "teamRole": "问诊主持",
        "teamMemberPurpose": "控制问诊节奏并合并团队意见",
    }

    prompt = chat_room_service._build_participant_prompt(
        room={"roomId": "room-medical", "title": "医疗问诊团队 群聊", "purpose": "medical_triage"},
        round_payload={
            "topic": "用户发热三天，伴随咳嗽",
            "mode": "medical_consultation_panel",
            "purpose": "medical_triage",
        },
        participant=participant,
        prior_messages=[],
    )

    assert "协同问诊会诊模式" in prompt
    assert "分诊与就医准备" in prompt
    assert "不替代医生面诊、检查、诊断或治疗" in prompt
    assert "严禁给出确定诊断、处方、剂量、停药/换药指令或保证性结论" in prompt
    assert "风险等级、可能方向、建议科室" in prompt


def test_team_case_orchestration_keeps_heletech_health_case_in_intake_phase(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    sessions = [
        session_service.create_chat_session(title="方案主持 Agent"),
        session_service.create_chat_session(title="妇幼业务顾问 Agent"),
        session_service.create_chat_session(title="病历集成顾问 Agent"),
        session_service.create_chat_session(title="数据科研顾问 Agent"),
        session_service.create_chat_session(title="合规交付顾问 Agent"),
    ]
    roles = ["方案主持", "妇幼业务顾问", "病历集成顾问", "数据科研顾问", "合规交付顾问"]
    purposes = ["方案编排", "妇幼流程", "病历集成", "科研数据", "合规交付"]
    contexts = {
        session["agentId"]: {
            "teamId": "demo-2",
            "teamName": "和乐妇幼数字健康 Demo 团队",
            "teamPurpose": "演示妇幼数字健康方案协作。",
            "teamRole": role,
            "teamMemberPurpose": purpose,
        }
        for session, role, purpose in zip(sessions, roles, purposes, strict=True)
    }
    room = chat_room_service.create_chat_room(
        title="和乐妇幼数字健康 Demo 团队",
        participant_agent_ids=[session["agentId"] for session in sessions],
        participant_contexts_by_agent_id=contexts,
        mode="round_robin",
        purpose="meeting",
        config={
            "source": "team_template",
            "teamId": "demo-2",
            "teamTemplateId": "heletech-maternal-digital-health-demo",
            "heletechMaternalDigitalHealthDemo": True,
        },
    )
    captured_prompts = []
    captured_roles = []

    def fake_runner(participant, prompt, context):
        captured_prompts.append(prompt)
        captured_roles.append(participant["teamRole"])
        return {
            "status": "completed",
            "raw_output": f"{participant['teamRole']} 先补齐关键信息。",
            "summary": "ok",
        }

    detail = chat_room_service.start_chat_room_round(
        room["roomId"],
        "孩子晚上经常哭泣是为什么",
        agent_runner=fake_runner,
    )

    latest_round = detail["rounds"][-1]
    case_state = latest_round["caseState"]
    assert case_state["intent"] == "maternal_child_consultation_demo"
    assert case_state["informationSufficiency"] == "insufficient"
    assert case_state["nextAction"] == "clarify"
    assert case_state["userFacingMode"] == "direct_clarification"
    assert "年龄/月龄" in case_state["missingFacts"]
    assert "伴随症状" in case_state["missingFacts"]
    assert latest_round["messages"][0]["participantId"] == f"session-{sessions[0]['id']}"
    assert latest_round["messages"][0]["content"] == "方案主持 先补齐关键信息。"
    assert captured_roles == ["方案主持"]
    assert [message["speakerTitle"] for message in latest_round["messages"]]
    assert latest_round["messages"][0]["messageKind"] == "user_clarification"
    assert latest_round["messages"][0]["audience"] == "user"
    assert len(captured_prompts) == 1
    assert "本轮用户需求 Case 状态" in captured_prompts[0]
    assert "下一步动作: clarify" in captured_prompts[0]
    assert "用户可见模式: direct_clarification" in captured_prompts[0]
    assert "对话目的: meeting" in captured_prompts[0]
    assert "本轮推进模式: medical_clarification" in captured_prompts[0]
    assert "缺失信息:" in captured_prompts[0]
    assert "面向用户自然澄清，而不是开会讨论如何澄清" in captured_prompts[0]
    assert "不要把追问写成内部任务分派" in captured_prompts[0]
    assert "不要写成问卷" in captured_prompts[0]
    assert "clarify 阶段禁止提" in captured_prompts[0]
    assert "Demo 映射边界" in captured_prompts[0]
    assert "Demo 映射原则" not in captured_prompts[0]


def test_maternal_child_clarify_output_boundary_removes_product_mapping(monkeypatch):
    recorded_events = []
    monkeypatch.setattr(
        chat_room_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )
    participant = {
        "participantId": "session-host",
        "agentId": "agent-host",
        "agentCode": "A022",
        "sessionId": "session-host",
        "title": "方案主持 Agent",
    }

    def fake_runner(_participant, _prompt, _context):
        return {
            "status": "completed",
            "raw_output": (
                "孩子夜间哭闹比较常见，先确认孩子多大、哭闹持续多久、有没有发热或呕吐腹泻。\n"
                "补充这些信息后，我们可以把场景对应到妇幼数字健康的产品能力上，比如母子健康手册、云上妇幼和专科电子病历。"
            ),
            "summary": "补齐信息后映射妇幼数字健康产品能力。",
        }

    message = chat_room_service._run_one_speaker(
        participant,
        "prompt",
        {
            "roomId": "room-demo",
            "roundId": "round-demo",
            "speakerStartedAtMonotonic": chat_room_service._perf_counter(),
            "caseState": {
                "intent": "maternal_child_consultation_demo",
                "nextAction": "clarify",
                "missingFacts": ["年龄/月龄", "持续时间与频率", "伴随症状"],
            },
        },
        fake_runner,
    )

    assert message["status"] == "completed"
    assert message["messageKind"] == "user_clarification"
    assert "孩子多大" in message["content"]
    assert "妇幼数字健康" not in message["content"]
    assert "产品能力" not in message["content"]
    assert "母子健康手册" not in message["content"]
    assert "云上妇幼" not in message["content"]
    assert "专科电子病历" not in message["content"]
    assert "妇幼数字健康" not in message["summary"]
    assert any(
        args[:3]
        == (
            "chat_room",
            "case_output_boundary",
            "chat_room.case_visible_output_boundary.applied",
        )
        and kwargs["fields"]["roomId"] == "room-demo"
        and kwargs["fields"]["roundId"] == "round-demo"
        and kwargs["fields"]["removedSegmentCount"] >= 1
        for args, kwargs in recorded_events
    )


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
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    room = chat_room_service.create_chat_room(
        title="轻量详情群聊",
        participant_session_ids=["session-alpha", "session-beta"],
    )

    def fail_full_session_load(session_id):
        raise AssertionError(f"full session detail should not load for room list/detail: {session_id}")

    monkeypatch.setattr(session_service, "get_session_detail", fail_full_session_load)
    real_list_sessions = session_service.list_sessions
    list_session_calls = 0

    def counting_list_sessions(*args, **kwargs):
        nonlocal list_session_calls
        list_session_calls += 1
        return real_list_sessions(*args, **kwargs)

    monkeypatch.setattr(session_service, "list_sessions", counting_list_sessions)
    real_list_agents = agent_directory_service.list_agents
    list_agent_calls = 0

    def counting_list_agents(*args, **kwargs):
        nonlocal list_agent_calls
        list_agent_calls += 1
        return real_list_agents(*args, **kwargs)

    monkeypatch.setattr(agent_directory_service, "list_agents", counting_list_agents)

    listed = chat_room_service.list_chat_rooms()
    detail = chat_room_service.get_chat_room_detail(room["roomId"])

    assert listed[0]["roomId"] == room["roomId"]
    assert [participant["sessionId"] for participant in detail["participants"]] == [
        "session-alpha",
        "session-beta",
    ]
    assert list_session_calls == 0
    assert list_agent_calls == 0


def test_chat_room_participant_index_stays_warm_for_message_only_session_changes(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    room = chat_room_service.create_chat_room(
        title="缓存命中群聊",
        participant_session_ids=["session-alpha", "session-beta"],
    )
    chat_room_service.get_chat_room_detail(room["roomId"])
    chat_room_service._clear_participant_refresh_index_cache()
    real_summary_index = chat_room_service._session_summary_index
    summary_index_calls = 0

    def counting_summary_index(*, session_ids=None):
        nonlocal summary_index_calls
        summary_index_calls += 1
        return real_summary_index(session_ids=session_ids)

    monkeypatch.setattr(chat_room_service, "_session_summary_index", counting_summary_index)

    first_detail = chat_room_service.get_chat_room_detail(room["roomId"])
    assert first_detail["participants"][0]["title"] == "Alpha Agent"
    assert summary_index_calls == 1

    state = load_chat_state(tmp_path)
    for conversation in state["conversations"]:
        if conversation["conversation_id"] == "session-alpha":
            conversation["updated_at"] = "2026-05-26T10:04:00"
            break
    _append_session_ledger_message(
        tmp_path,
        "session-alpha",
        {
            "role": "user",
            "content": "追加一条普通消息",
            "timestamp": "2026-05-26T10:04:00",
        },
        turn_id="session-alpha-extra-message",
    )
    state["updated_at"] = "2026-05-26T10:04:00"
    state["conversations"][0]["last_turn_status"] = "completed"
    save_chat_state(tmp_path, state)

    second_detail = chat_room_service.get_chat_room_detail(room["roomId"])
    assert second_detail["participants"][0]["title"] == "Alpha Agent"
    assert summary_index_calls == 1

    state = load_chat_state(tmp_path)
    for conversation in state["conversations"]:
        if conversation["conversation_id"] == "session-alpha":
            conversation["title"] = "Alpha Renamed Agent"
            break
    save_chat_state(tmp_path, state)

    third_detail = chat_room_service.get_chat_room_detail(room["roomId"])
    assert third_detail["participants"][0]["title"] == "Alpha Renamed Agent"
    assert summary_index_calls == 2


def test_chat_room_participant_index_singleflights_same_signature(monkeypatch):
    chat_room_service._clear_participant_refresh_index_cache()
    signature_barrier = threading.Barrier(2)
    summary_started = threading.Event()
    release_summary = threading.Event()
    summary_calls = 0
    summary_calls_lock = threading.Lock()

    def shared_signature(*, session_ids=None, agent_ids=None):
        signature_barrier.wait(timeout=2)
        return ("shared-participant-index-signature",)

    def empty_active_agents(*, agent_ids=None, session_ids=None):
        return {"by_id": {}, "by_session_id": {}}

    def slow_summary_index(*, session_ids=None):
        nonlocal summary_calls
        with summary_calls_lock:
            summary_calls += 1
        summary_started.set()
        assert release_summary.wait(timeout=2)
        return {"session-alpha": {"id": "session-alpha", "title": "Alpha Agent"}}

    monkeypatch.setattr(chat_room_service, "_participant_refresh_index_signature", shared_signature)
    monkeypatch.setattr(chat_room_service, "_active_agent_participant_indexes", empty_active_agents)
    monkeypatch.setattr(chat_room_service, "_session_summary_index", slow_summary_index)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(chat_room_service._participant_refresh_indexes) for _ in range(2)]
        try:
            assert summary_started.wait(timeout=2)
            time.sleep(0.05)
            assert summary_calls == 1
        finally:
            release_summary.set()
        first = futures[0].result(timeout=2)
        second = futures[1].result(timeout=2)

    assert first[0] == second[0]
    assert sorted([first[1], second[1]]) == [False, True]
    assert summary_calls == 1
    chat_room_service._clear_participant_refresh_index_cache()


def test_chat_room_participant_index_keeps_different_signatures_separate(monkeypatch):
    chat_room_service._clear_participant_refresh_index_cache()
    summary_calls: list[set[str]] = []

    monkeypatch.setattr(
        chat_room_service,
        "_participant_refresh_index_signature",
        lambda *, session_ids=None, agent_ids=None: ("participant-scope", tuple(sorted(session_ids or set()))),
    )
    monkeypatch.setattr(
        chat_room_service,
        "_active_agent_participant_indexes",
        lambda *, agent_ids=None, session_ids=None: {"by_id": {}, "by_session_id": {}},
    )

    def scoped_summary_index(*, session_ids=None):
        scoped_ids = set(session_ids or set())
        summary_calls.append(scoped_ids)
        return {session_id: {"id": session_id, "title": session_id} for session_id in scoped_ids}

    monkeypatch.setattr(chat_room_service, "_session_summary_index", scoped_summary_index)

    alpha, alpha_cache_hit, _ = chat_room_service._participant_refresh_indexes(
        participants=[{"sessionId": "session-alpha"}],
    )
    beta, beta_cache_hit, _ = chat_room_service._participant_refresh_indexes(
        participants=[{"sessionId": "session-beta"}],
    )
    alpha_cached, alpha_cached_hit, _ = chat_room_service._participant_refresh_indexes(
        participants=[{"sessionId": "session-alpha"}],
    )

    assert set(alpha["session_summaries"]) == {"session-alpha"}
    assert set(beta["session_summaries"]) == {"session-beta"}
    assert alpha_cached == alpha
    assert [alpha_cache_hit, beta_cache_hit, alpha_cached_hit] == [False, False, True]
    assert summary_calls == [{"session-alpha"}, {"session-beta"}]
    chat_room_service._clear_participant_refresh_index_cache()


def test_chat_room_participant_index_releases_singleflight_after_builder_error(monkeypatch):
    chat_room_service._clear_participant_refresh_index_cache()
    summary_calls = 0

    monkeypatch.setattr(
        chat_room_service,
        "_participant_refresh_index_signature",
        lambda *, session_ids=None, agent_ids=None: ("failed-participant-index-signature",),
    )
    monkeypatch.setattr(
        chat_room_service,
        "_active_agent_participant_indexes",
        lambda *, agent_ids=None, session_ids=None: {"by_id": {}, "by_session_id": {}},
    )

    def flaky_summary_index(*, session_ids=None):
        nonlocal summary_calls
        summary_calls += 1
        if summary_calls == 1:
            raise RuntimeError("index build failed")
        return {"session-alpha": {"id": "session-alpha", "title": "Alpha Agent"}}

    monkeypatch.setattr(chat_room_service, "_session_summary_index", flaky_summary_index)

    with pytest.raises(RuntimeError, match="index build failed"):
        chat_room_service._participant_refresh_indexes()

    indexes, cache_hit, _timings = chat_room_service._participant_refresh_indexes()

    assert indexes["session_summaries"]["session-alpha"]["title"] == "Alpha Agent"
    assert cache_hit is False
    assert summary_calls == 2
    chat_room_service._clear_participant_refresh_index_cache()


def test_reconciliation_does_not_hold_room_lock_while_loading_work_run(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    room = chat_room_service.create_chat_room(
        title="对账不阻塞停止",
        participant_session_ids=["session-alpha"],
    )
    state = chat_room_service._store().load()
    stored_room = next(item for item in state["rooms"] if item["roomId"] == room["roomId"])
    stored_room["status"] = "running"
    stored_room["activeRoundId"] = "round-running"
    stored_room["rounds"] = [{
        "roundId": "round-running",
        "status": "running",
        "messages": [],
        "speakerOrder": ["session-session-alpha"],
        "startedAt": "2026-08-24T00:00:00+00:00",
        "updatedAt": "2026-08-24T00:00:00+00:00",
    }]
    chat_room_service._store().save(state)

    work_run_read_started = threading.Event()
    release_work_run_read = threading.Event()

    class SlowWorkRunStore:
        def load_snapshot(self, _run_kind, _round_id):
            work_run_read_started.set()
            assert release_work_run_read.wait(timeout=2)
            return {}

        def persist_snapshot(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(chat_room_service, "_work_run_store", lambda: SlowWorkRunStore())
    monkeypatch.setattr(chat_room_service, "_publish_chat_room_detail_snapshot", lambda _room_id: None)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(chat_room_service._reconcile_chat_room_round_state)
        try:
            assert work_run_read_started.wait(timeout=1)
            stopped = chat_room_service.stop_chat_room_round(room["roomId"], reason="pytest reconciliation stop")
            assert stopped["status"] == "stopping"
        finally:
            release_work_run_read.set()
        assert future.result(timeout=2) == []


def test_terminal_round_failure_publishes_after_releasing_room_lock(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    room = chat_room_service.create_chat_room(
        title="终态失败通知",
        participant_session_ids=["session-alpha"],
    )
    state = chat_room_service._store().load()
    stored_room = next(item for item in state["rooms"] if item["roomId"] == room["roomId"])
    terminal_round = {
        "roundId": "round-terminal",
        "status": "stopped",
        "messages": [],
        "speakerOrder": [],
    }
    stored_room["rounds"] = [terminal_round]
    chat_room_service._store().save(state)
    published: list[str] = []

    def publish_after_unlock(room_id: str):
        assert not chat_room_service._chat_room_lock_owned_by_current_thread()
        published.append(room_id)

    monkeypatch.setattr(chat_room_service, "_publish_chat_room_detail_snapshot", publish_after_unlock)

    chat_room_service._fail_chat_room_round(
        room["roomId"],
        "round-terminal",
        stored_room,
        terminal_round,
        RuntimeError("already terminal"),
        lang="zh",
    )

    assert published == [room["roomId"]]


def test_chat_room_refresh_rebinds_participant_to_current_agent_direct_session(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    first = session_service.create_chat_session(title="Alpha Agent")
    second = session_service.create_chat_session(title="Beta Agent")
    room = chat_room_service.create_chat_room(
        title="旧 session 引用群聊",
        participant_agent_ids=[first["agentId"], second["agentId"]],
    )
    room_state = chat_room_service._store().load()
    stored_room = next(item for item in room_state["rooms"] if item["roomId"] == room["roomId"])
    stored_room["participants"][0]["agentId"] = first["agentId"]
    stored_room["participants"][0]["agentCode"] = first.get("agentCode", "")
    chat_room_service._store().save(room_state)
    rebound_session_id = "session-alpha-rebound"
    state = agent_directory_service.load_state()
    for agent in state.get("agents") or []:
        if agent.get("agentId") == first["agentId"]:
            agent["directSessionId"] = rebound_session_id
            break
    agent_directory_service.save_state(state)
    chat_state = load_chat_state(tmp_path)
    chat_state["conversations"] = [
        item
        for item in chat_state.get("conversations") or []
        if (item.get("conversation_id") or item.get("id")) != first["id"]
    ]
    save_chat_state(tmp_path, chat_state)

    detail = chat_room_service.get_chat_room_detail(room["roomId"])

    participants = {item["agentId"]: item for item in detail["participants"]}
    assert participants[first["agentId"]]["sessionId"] == rebound_session_id
    assert participants[first["agentId"]]["directSessionId"] == rebound_session_id
    assert participants[first["agentId"]]["enabled"] is True


def test_group_round_sync_materializes_agent_directory_only_sessions(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    detail = session_service.create_chat_session(title="Alpha Agent")
    state = load_chat_state(tmp_path)
    state["conversations"] = [
        item
        for item in state.get("conversations") or []
        if (item.get("conversation_id") or item.get("id")) != detail["id"]
    ]
    save_chat_state(tmp_path, state)
    room = {
        "roomId": "room-alpha",
        "title": "同步群聊",
        "participants": [
            {
                "participantId": "session-alpha",
                "agentId": detail["agentId"],
                "sessionId": detail["id"],
                "directSessionId": detail["id"],
                "title": "Alpha Agent",
                "enabled": True,
            }
        ],
    }
    round_payload = {
        "roundId": "round-alpha",
        "roomId": "room-alpha",
        "topic": "同步测试",
        "summary": "已经讨论完。",
        "finishedAt": "2026-05-29T08:30:00+00:00",
        "messages": [
            {
                "participantId": "session-alpha",
                "speakerTitle": "Alpha Agent",
                "status": "completed",
                "content": "我会把结论写回直聊。",
            }
        ],
    }

    chat_room_service._sync_group_round_to_participant_sessions(room, round_payload)

    synced_state = load_chat_state(tmp_path)
    conversation = session_service._find_conversation_entry(synced_state, detail["id"])
    assert conversation is not None
    assert conversation.get("agent_id") == detail["agentId"]
    messages = _session_ledger_messages(tmp_path, detail["id"])
    assert messages[-1]["metadata"]["kind"] == "group_room_transcript"
    assert messages[-1]["metadata"]["sourceRoundId"] == "round-alpha"


def test_chat_room_disables_missing_agent_participants(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
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
    monkeypatch.setattr(session_service, "_recover_active_direct_session_agent", lambda *args, **kwargs: None)
    sessions = session_service.list_sessions()
    room = chat_room_service.create_chat_room(
        title="断链群聊",
        participant_session_ids=["session-alpha"],
    )
    state = load_chat_state(tmp_path)
    state["conversations"][0]["agent_id"] = "agent-missing"
    state["conversations"][0]["agentId"] = "agent-missing"
    state["conversations"][0]["conversationIndexKind"] = "personal_agent"
    save_chat_state(tmp_path, state)
    session_service._invalidate_session_list_cache()
    room_state = chat_room_service._store().load()
    stored_room = next(item for item in room_state["rooms"] if item["roomId"] == room["roomId"])
    stored_room["participants"][0]["agentId"] = "agent-missing"
    chat_room_service._store().save(room_state)

    detail = chat_room_service.get_chat_room_detail(room["roomId"])

    assert {item["id"] for item in sessions} == {"session-alpha", "session-beta"}
    visible_sessions = {item["id"] for item in session_service.list_sessions()}
    assert "session-alpha" not in visible_sessions
    updated_sessions = {item["id"]: item for item in session_service.list_sessions(include_hidden_internal=True)}
    assert updated_sessions["session-alpha"]["agentMissing"] is True
    assert updated_sessions["session-alpha"]["agentStatusCode"] == "missing_agent"
    assert updated_sessions["session-alpha"]["conversationIndexKind"] == "invalid"
    participant = detail["participants"][0]
    assert participant["sessionId"] == "session-alpha"
    assert participant["agentMissing"] is True
    assert participant["agentStatusCode"] == "missing_agent"
    assert "缺少有效 Agent" in participant["agentStatusMessage"]
    assert participant["enabled"] is False
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
    assert "- 你是本轮第一位发言者。" in prompts[0][1]
    assert prompts[1][0] == "session-alpha"
    assert "Beta Agent 对 讨论群聊 MVP 怎么切第一版 的发言" in prompts[1][1]
    assert "- 你是本轮第一位发言者。" not in prompts[1][1]

    work_run_summary = chat_room_service.load_chat_room_work_run_summary()
    assert work_run_summary["active"] is None
    assert work_run_summary["latest"]["runKind"] == "chat_room_round"
    assert work_run_summary["latest"]["status"] == "completed"
    assert work_run_summary["latest"]["roomId"] == room["roomId"]
    assert any(
        event[0][:3] == ("chat_room", "round", "chat_room.round.completed")
        for event in recorded_events
    )
    started_events = [
        event
        for event in recorded_events
        if event[0][:3] == ("chat_room", "round", "chat_room.round.started")
    ]
    assert started_events
    started_fields = started_events[-1][1]["fields"]
    assert started_fields["chatRoomLockedMs"] >= 0
    assert started_fields["participantRefreshMs"] >= 0
    assert started_fields["submitElapsedBeforeStartLogMs"] >= 0
    speaker_events = [
        event
        for event in recorded_events
        if event[0][:3] == ("chat_room", "speaker", "chat_room.speaker.completed")
    ]
    assert speaker_events
    speaker_fields = speaker_events[-1][1]["fields"]
    assert speaker_fields["promptBuildMs"] >= 0
    assert speaker_fields["speakerRunMs"] >= 0
    assert speaker_fields["runnerMs"] >= 0
    assert speaker_fields["totalSpeakerMs"] >= 0


def test_start_chat_room_round_refreshes_participants_outside_room_lock(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    room = chat_room_service.create_chat_room(
        title="锁外刷新群聊",
        participant_session_ids=["session-alpha", "session-beta"],
    )
    chat_room_service._clear_participant_refresh_index_cache()

    details_started = threading.Event()
    release_details = threading.Event()
    real_get_session_detail = session_service.get_session_detail

    def blocking_get_session_detail(session_id):
        assert not chat_room_service._chat_room_lock_owned_by_current_thread()
        details_started.set()
        assert release_details.wait(timeout=5)
        return real_get_session_detail(session_id)

    monkeypatch.setattr(session_service, "get_session_detail", blocking_get_session_detail)

    def fail_full_session_list(*args, **kwargs):
        raise AssertionError("round start must use targeted session summaries")

    monkeypatch.setattr(session_service, "list_sessions", fail_full_session_list)

    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pytest-chat-room-lock-safety")
    future = executor.submit(
        chat_room_service.start_chat_room_round,
        room["roomId"],
        "锁外刷新后再持久化",
        agent_runner=lambda participant, prompt, context: {
            "status": "completed",
            "raw_output": f"{participant['title']} 发言",
            "summary": "ok",
        },
    )
    try:
        assert details_started.wait(timeout=5)
        assert chat_room_service._CHAT_ROOM_LOCK.acquire(timeout=0.5)
        chat_room_service._CHAT_ROOM_LOCK.release()
        release_details.set()
        detail = future.result(timeout=10)
    finally:
        release_details.set()
        executor.shutdown(wait=True)

    assert detail["rounds"][-1]["status"] == "completed"
    assert detail["rounds"][-1]["speakerOrder"] == [
        "session-session-alpha",
        "session-session-beta",
    ]


def test_start_chat_room_round_revalidates_participant_snapshot_before_persist(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    room = chat_room_service.create_chat_room(
        title="并发成员变化群聊",
        participant_session_ids=["session-alpha", "session-beta"],
    )

    first_refresh_started = threading.Event()
    release_first_refresh = threading.Event()
    refresh_calls = 0
    real_refresh = chat_room_service._refresh_chat_room_round_participants

    def blocking_first_refresh(participants, **kwargs):
        nonlocal refresh_calls
        refresh_calls += 1
        if refresh_calls == 1:
            first_refresh_started.set()
            assert release_first_refresh.wait(timeout=5)
        return real_refresh(participants, **kwargs)

    monkeypatch.setattr(
        chat_room_service,
        "_refresh_chat_room_round_participants",
        blocking_first_refresh,
    )

    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pytest-chat-room-snapshot-recheck")
    future = executor.submit(
        chat_room_service.start_chat_room_round,
        room["roomId"],
        "成员变化后必须重新取快照",
        agent_runner=lambda participant, prompt, context: {
            "status": "completed",
            "raw_output": f"{participant['title']} 发言",
            "summary": "ok",
        },
    )
    try:
        assert first_refresh_started.wait(timeout=5)
        updated = chat_room_service.update_chat_room(
            room["roomId"],
            participant_session_ids=["session-alpha"],
        )
        assert [item["sessionId"] for item in updated["participants"]] == ["session-alpha"]
        release_first_refresh.set()
        detail = future.result(timeout=10)
    finally:
        release_first_refresh.set()
        executor.shutdown(wait=True)

    assert refresh_calls >= 2
    assert [item["sessionId"] for item in detail["participants"]] == ["session-alpha"]
    assert detail["rounds"][-1]["speakerOrder"] == ["session-session-alpha"]


def test_start_chat_room_round_aborts_after_bounded_participant_snapshot_retries(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    room = chat_room_service.create_chat_room(
        title="成员持续更新群聊",
        participant_session_ids=["session-alpha", "session-beta"],
    )
    chat_room_service._clear_participant_refresh_index_cache()

    refresh_started = threading.Event()
    refresh_releases = [
        threading.Event() for _ in range(chat_room_service._CHAT_ROOM_PARTICIPANT_REFRESH_MAX_ATTEMPTS)
    ]
    refresh_calls = 0
    real_refresh = chat_room_service._refresh_chat_room_round_participants
    real_get_session_detail = session_service.get_session_detail
    real_list_sessions = session_service.list_sessions
    detail_lock_states = []
    list_lock_states = []

    def tracked_get_session_detail(session_id):
        detail_lock_states.append(chat_room_service._chat_room_lock_owned_by_current_thread())
        return real_get_session_detail(session_id)

    def tracked_list_sessions(*args, **kwargs):
        list_lock_states.append(chat_room_service._chat_room_lock_owned_by_current_thread())
        return real_list_sessions(*args, **kwargs)

    monkeypatch.setattr(session_service, "get_session_detail", tracked_get_session_detail)
    monkeypatch.setattr(session_service, "list_sessions", tracked_list_sessions)

    def blocking_refresh(participants, **kwargs):
        nonlocal refresh_calls
        attempt = refresh_calls
        refresh_calls += 1
        assert attempt < len(refresh_releases)
        refresh_started.set()
        assert refresh_releases[attempt].wait(timeout=5)
        return real_refresh(participants, **kwargs)

    monkeypatch.setattr(
        chat_room_service,
        "_refresh_chat_room_round_participants",
        blocking_refresh,
    )

    participant_by_session_id = {
        str(item["sessionId"]): dict(item)
        for item in room["participants"]
    }

    def overwrite_room_participants(session_ids):
        with chat_room_service._CHAT_ROOM_LOCK:
            state = chat_room_service._store().load()
            stored_room = chat_room_service._find_room(state, room["roomId"])
            assert stored_room is not None
            stored_room["participants"] = [dict(participant_by_session_id[session_id]) for session_id in session_ids]
            chat_room_service._store().save(state)

    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pytest-chat-room-bounded-retry")
    future = executor.submit(
        chat_room_service.start_chat_room_round,
        room["roomId"],
        "持续更新时应明确失败",
        agent_runner=lambda participant, prompt, context: {
            "status": "completed",
            "raw_output": f"{participant['title']} 发言",
            "summary": "ok",
        },
    )
    participant_updates = [
        ["session-alpha"],
        ["session-beta"],
        ["session-alpha"],
    ]
    try:
        for attempt, session_ids in enumerate(participant_updates):
            assert refresh_started.wait(timeout=5)
            refresh_started.clear()
            overwrite_room_participants(session_ids)
            refresh_releases[attempt].set()

        with pytest.raises(chat_room_service.ChatRoomBusyError, match="群聊成员正在更新"):
            future.result(timeout=10)
    finally:
        for release in refresh_releases:
            release.set()
        executor.shutdown(wait=True)

    assert refresh_calls == chat_room_service._CHAT_ROOM_PARTICIPANT_REFRESH_MAX_ATTEMPTS
    assert detail_lock_states
    assert all(not owned for owned in detail_lock_states)
    assert all(not owned for owned in list_lock_states)
    detail = chat_room_service.get_chat_room_detail(room["roomId"])
    assert detail["status"] == "ready"
    assert detail["activeRoundId"] == ""
    assert detail["rounds"] == []


def test_start_chat_room_round_preserves_structured_runner_failure(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    recorded_events = []
    monkeypatch.setattr(
        chat_room_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )

    room = chat_room_service.create_chat_room(
        title="结构化失败群聊",
        participant_session_ids=["session-alpha", "session-beta"],
    )

    detail = chat_room_service.start_chat_room_round(
        room["roomId"],
        "验证结构化失败不会伪装成功",
        agent_runner=lambda participant, prompt, context: {
            "status": "failed",
            "raw_output": "",
            "summary": "configured model does not exist",
            "error": "provider_protocol_error",
            "llm_failure": {"category": "provider_protocol_error"},
        },
    )

    latest_round = detail["rounds"][-1]
    assert detail["status"] == "failed"
    assert latest_round["status"] == "failed"
    assert [message["status"] for message in latest_round["messages"]] == ["failed", "failed"]
    assert [message["resultStatus"] for message in latest_round["messages"]] == ["failed", "failed"]
    assert [message["errorType"] for message in latest_round["messages"]] == [
        "provider_protocol_error",
        "provider_protocol_error",
    ]
    assert chat_room_service.load_chat_room_work_run_summary()["latest"]["status"] == "failed"
    assert any(
        event[0][:3] == ("chat_room", "speaker", "chat_room.speaker.failed")
        and event[1]["fields"]["status"] == "failed"
        for event in recorded_events
    )
    assert any(
        event[0][:3] == ("chat_room", "round", "chat_room.round.failed")
        for event in recorded_events
    )
    assert not _has_room_transcript(tmp_path, "session-alpha", room["roomId"])
    assert not _has_room_transcript(tmp_path, "session-beta", room["roomId"])


def test_start_chat_room_round_projects_mixed_results_as_partial(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    recorded_events = []
    monkeypatch.setattr(
        chat_room_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )

    def mixed_runner(participant, prompt, context):
        if participant["sessionId"] == "session-alpha":
            return {
                "status": "completed",
                "raw_output": "Alpha 提供了可用结论。",
                "summary": "Alpha completed",
            }
        return {
            "status": "failed",
            "raw_output": "",
            "summary": "Beta provider failure must not enter group context.",
            "llm_failure": {"category": "provider_protocol_error"},
        }

    room = chat_room_service.create_chat_room(
        title="部分完成群聊",
        participant_session_ids=["session-alpha", "session-beta"],
    )

    detail = chat_room_service.start_chat_room_round(
        room["roomId"],
        "验证部分完成状态",
        agent_runner=mixed_runner,
    )

    latest_round = detail["rounds"][-1]
    assert detail["status"] == "ready"
    assert latest_round["status"] == "partial"
    assert [message["status"] for message in latest_round["messages"]] == ["completed", "failed"]
    assert chat_room_service.load_chat_room_work_run_summary()["latest"]["status"] == "partial"
    partial_event = next(
        event
        for event in recorded_events
        if event[0][:3] == ("chat_room", "round", "chat_room.round.partial")
    )
    assert partial_event[1]["fields"]["completedCount"] == 1
    assert partial_event[1]["fields"]["failedCount"] == 1
    assert partial_event[1]["fields"]["unsuccessfulCount"] == 1
    for session_id in ("session-alpha", "session-beta"):
        transcript = "\n".join(str(item.get("content") or "") for item in _session_ledger_messages(tmp_path, session_id))
        assert "Alpha 提供了可用结论。" in transcript
        assert "Beta provider failure must not enter group context." not in transcript


def test_start_chat_room_round_preserves_all_partial_results(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    recorded_events = []
    monkeypatch.setattr(
        chat_room_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )

    room = chat_room_service.create_chat_room(
        title="全员部分完成群聊",
        participant_session_ids=["session-alpha", "session-beta"],
    )

    detail = chat_room_service.start_chat_room_round(
        room["roomId"],
        "验证全员降级结果不会被误判失败",
        agent_runner=lambda participant, prompt, context: {
            "status": "degraded",
            "raw_output": f"{participant['title']} 仅完成了部分分析。",
            "summary": "Partial output must remain visible but not enter group context.",
        },
    )

    latest_round = detail["rounds"][-1]
    assert detail["status"] == "ready"
    assert latest_round["status"] == "partial"
    assert [message["status"] for message in latest_round["messages"]] == ["partial", "partial"]
    assert "2 位部分完成" in latest_round["summary"]
    assert chat_room_service.load_chat_room_work_run_summary()["latest"]["status"] == "partial"
    partial_event = next(
        event
        for event in recorded_events
        if event[0][:3] == ("chat_room", "round", "chat_room.round.partial")
    )
    assert partial_event[1]["fields"]["completedCount"] == 0
    assert partial_event[1]["fields"]["partialCount"] == 2
    assert partial_event[1]["fields"]["unsuccessfulCount"] == 2
    assert not _has_room_transcript(tmp_path, "session-alpha", room["roomId"])
    assert not _has_room_transcript(tmp_path, "session-beta", room["roomId"])


@pytest.mark.parametrize(
    ("runner_status", "expected_message_status", "expected_result_status", "expected_error_type"),
    [
        (None, "completed", "", ""),
        ("succeeded", "completed", "succeeded", ""),
        ("blocked", "blocked", "blocked", ""),
        ("stopped_by_user", "stopped", "stopped_by_user", ""),
        ("degraded", "partial", "degraded", ""),
        ("needs_continue", "partial", "needs_continue", ""),
        ("unexpected_status", "failed", "unexpected_status", "UnexpectedResultStatus"),
    ],
)
def test_run_one_speaker_normalizes_structured_result_status(
    monkeypatch,
    runner_status,
    expected_message_status,
    expected_result_status,
    expected_error_type,
):
    monkeypatch.setattr(
        chat_room_service,
        "_evaluate_speaker_supervision_policy",
        lambda participant: SimpleNamespace(
            allowed=True,
            reason="",
            supervision_enabled=False,
            requires_review=False,
            review_mode="",
            evidence_level="",
        ),
    )
    monkeypatch.setattr(agent_directory_service, "record_supervision_policy_decision", lambda decision: None)
    result = {"raw_output": "可见输出", "summary": "摘要"}
    if runner_status is not None:
        result["status"] = runner_status

    message = chat_room_service._run_one_speaker(
        {
            "participantId": "participant-status",
            "agentId": "agent-status",
            "agentCode": "A-status",
            "sessionId": "session-status",
            "title": "状态 Agent",
        },
        "测试结构化状态",
        {},
        lambda participant, prompt, context: result,
    )

    assert message["status"] == expected_message_status
    assert message["resultStatus"] == expected_result_status
    assert message.get("errorType", "") == expected_error_type


def test_start_chat_room_round_records_kernel_trace_without_agent_inbox_delivery(tmp_path, monkeypatch):
    _isolate_chat_room_kernel(tmp_path, monkeypatch)
    recorded_events = []
    monkeypatch.setattr(
        chat_room_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    room = chat_room_service.create_chat_room(
        title="Kernel 追踪群聊",
        participant_agent_ids=[alpha["agentId"], beta["agentId"]],
    )

    detail = chat_room_service.start_chat_room_round(
        room["roomId"],
        "讨论群聊轮次如何进入任务中心",
        agent_runner=lambda participant, prompt, context: {
            "status": "completed",
            "raw_output": f"{participant['title']} 已完成",
            "summary": "ok",
        },
    )

    latest_round = detail["rounds"][-1]
    kernel_trace = latest_round["kernel"]
    assert latest_round["status"] == "completed"
    assert kernel_trace["traceOnly"] is True
    assert kernel_trace["status"] == "recorded"
    assert kernel_trace["taskId"]
    assert kernel_trace["workRunId"]
    assert kernel_trace["outcomeStatus"] == "succeeded"

    task = agent_kernel_service.get_kernel_task(kernel_trace["taskId"])
    assert task["status"] == "succeeded"
    assert task["goal"] == "Chat room round: 讨论群聊轮次如何进入任务中心"
    assert task["assignedAgentIds"] == [alpha["agentId"], beta["agentId"]]
    timeline = agent_kernel_service.get_kernel_task_timeline(kernel_trace["taskId"])
    assert timeline["event"]["deliveryPolicy"]["traceOnly"] is True
    assert timeline["outcome"]["deliveries"] == []
    assert agent_directory_service.list_agent_inbox_messages_for_agent(alpha["agentId"]) == []
    assert agent_directory_service.list_agent_inbox_messages_for_agent(beta["agentId"]) == []

    work_run_summary = chat_room_service.load_chat_room_work_run_summary()
    assert work_run_summary["latest"]["kernel"]["taskId"] == kernel_trace["taskId"]
    assert any(
        event[0][:3] == ("chat_room", "kernel", "chat_room.round.kernel_trace_recorded")
        and event[1]["fields"]["kernelTaskId"] == kernel_trace["taskId"]
        for event in recorded_events
    )


def test_start_chat_room_round_continues_when_kernel_trace_fails(tmp_path, monkeypatch):
    _isolate_chat_room_kernel(tmp_path, monkeypatch)
    alpha = session_service.create_chat_session(title="Alpha Agent")
    beta = session_service.create_chat_session(title="Beta Agent")
    room = chat_room_service.create_chat_room(
        title="Kernel 失败不阻塞群聊",
        participant_agent_ids=[alpha["agentId"], beta["agentId"]],
    )

    def raise_kernel_trace(_event):
        raise RuntimeError("kernel unavailable")

    monkeypatch.setattr(agent_kernel_service, "handle_kernel_event", raise_kernel_trace)

    detail = chat_room_service.start_chat_room_round(
        room["roomId"],
        "即使追踪失败也要继续讨论",
        agent_runner=lambda participant, prompt, context: {
            "status": "completed",
            "raw_output": f"{participant['title']} 已发言",
            "summary": "ok",
        },
    )

    latest_round = detail["rounds"][-1]
    assert latest_round["status"] == "completed"
    assert [message["status"] for message in latest_round["messages"]] == ["completed", "completed"]
    assert latest_round["kernel"]["status"] == "failed"
    assert latest_round["kernel"]["errorType"] == "RuntimeError"
    assert "kernel unavailable" in latest_round["kernel"]["reason"]


def test_start_chat_room_round_dedupes_duplicate_participants_before_prompt_chain(tmp_path, monkeypatch):
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
        prompts.append((participant["sessionId"], prompt))
        return {
            "status": "completed",
            "raw_output": f"{participant['title']} 发言 {context['speakerIndex']}",
            "summary": "ok",
        }

    room = chat_room_service.create_chat_room(
        title="重复成员群聊",
        participant_session_ids=["session-alpha", "session-beta"],
    )
    state = chat_room_service._store().load()
    stored_room = next(item for item in state["rooms"] if item["roomId"] == room["roomId"])
    duplicate_alpha = dict(stored_room["participants"][0])
    duplicate_alpha["participantId"] = "duplicate-alpha"
    stored_room["participants"].append(duplicate_alpha)
    chat_room_service._store().save(state)

    detail = chat_room_service.start_chat_room_round(
        room["roomId"],
        "重复成员不能重复发言",
        agent_runner=fake_runner,
    )

    latest_round = detail["rounds"][-1]
    assert [message["sessionId"] for message in latest_round["messages"]] == ["session-alpha", "session-beta"]
    assert latest_round["speakerOrder"] == ["session-session-alpha", "session-session-beta"]
    assert [participant["sessionId"] for participant in detail["participants"]] == ["session-alpha", "session-beta"]
    assert "Alpha Agent 发言 0" in prompts[1][1]
    assert "- 你是本轮第一位发言者。" not in prompts[1][1]
    started_event = next(
        event
        for event in recorded_events
        if event[0][:3] == ("chat_room", "round", "chat_room.round.started")
    )
    assert started_event[1]["fields"]["participantDedupeRemoved"] == 1


def test_start_chat_room_round_filters_speakers_to_frozen_participant_agent_ids(
    tmp_path, monkeypatch
):
    _isolate_chat_room_kernel(tmp_path, monkeypatch)
    sessions = [
        session_service.create_chat_session(title=f"Participant {index}")
        for index in range(6)
    ]
    room = chat_room_service.create_chat_room(
        title="六人房间四人会议",
        participant_agent_ids=[session["agentId"] for session in sessions],
    )
    frozen_agent_ids = [
        sessions[4]["agentId"],
        sessions[0]["agentId"],
        sessions[5]["agentId"],
        sessions[2]["agentId"],
    ]

    detail = chat_room_service.start_chat_room_round(
        room["roomId"],
        "只允许冻结的四位角色发言",
        config={"participantAgentIds": frozen_agent_ids},
        agent_runner=lambda participant, prompt, context: {
            "status": "completed",
            "raw_output": f"{participant['title']} 已发言",
            "summary": "ok",
        },
    )

    latest_round = detail["rounds"][-1]
    assert [message["agentId"] for message in latest_round["messages"]] == frozen_agent_ids
    assert [participant["agentId"] for participant in detail["participants"]] == [
        session["agentId"] for session in sessions
    ]

    with pytest.raises(chat_room_service.ChatRoomValidationError, match="frozen participant"):
        chat_room_service.start_chat_room_round(
            room["roomId"],
            "缺少冻结成员时必须拒绝",
            config={"participantAgentIds": [*frozen_agent_ids, "agent-missing"]},
            agent_runner=lambda participant, prompt, context: {
                "status": "completed",
                "raw_output": "unexpected",
                "summary": "unexpected",
            },
        )


@pytest.mark.parametrize("failure_mode", ["disabled", "ambiguous"])
def test_start_chat_room_round_rejects_unavailable_or_ambiguous_frozen_participant(
    tmp_path, monkeypatch, failure_mode
):
    _isolate_chat_room_kernel(tmp_path, monkeypatch)
    sessions = [
        session_service.create_chat_session(title=f"Participant {index}")
        for index in range(4)
    ]
    frozen_agent_ids = [session["agentId"] for session in sessions]
    room = chat_room_service.create_chat_room(
        title="冻结四人会议",
        participant_agent_ids=frozen_agent_ids,
    )
    state = chat_room_service._store().load()
    stored_room = next(item for item in state["rooms"] if item["roomId"] == room["roomId"])
    if failure_mode == "disabled":
        stored_room["participants"][1]["enabled"] = False
    else:
        duplicate = dict(stored_room["participants"][1])
        duplicate["participantId"] = "duplicate-frozen-participant"
        stored_room["participants"].append(duplicate)
    chat_room_service._store().save(state)

    with pytest.raises(chat_room_service.ChatRoomValidationError, match="frozen participant"):
        chat_room_service.start_chat_room_round(
            room["roomId"],
            "冻结成员必须完整可用",
            config={"participantAgentIds": frozen_agent_ids},
            agent_runner=lambda participant, prompt, context: {
                "status": "completed",
                "raw_output": "unexpected",
                "summary": "unexpected",
            },
        )


@pytest.mark.parametrize(
    ("topic", "purpose", "config_override"),
    [
        ("冻结名单不能被 maxSpeakers 截断", "meeting", {"maxSpeakers": 2}),
        (
            "宝宝一直哭",
            "medical_triage",
            {"heletechMaternalDigitalHealthDemo": True},
        ),
    ],
)
def test_start_chat_room_round_rejects_scheduler_or_case_reduction_of_frozen_roster(
    tmp_path, monkeypatch, topic, purpose, config_override
):
    _isolate_chat_room_kernel(tmp_path, monkeypatch)
    sessions = [
        session_service.create_chat_session(title=f"Participant {index}")
        for index in range(4)
    ]
    frozen_agent_ids = [session["agentId"] for session in sessions]
    room = chat_room_service.create_chat_room(
        title="冻结四人会议",
        participant_agent_ids=frozen_agent_ids,
    )

    with pytest.raises(chat_room_service.ChatRoomValidationError, match="frozen participant"):
        chat_room_service.start_chat_room_round(
            room["roomId"],
            topic,
            purpose=purpose,
            config={"participantAgentIds": frozen_agent_ids, **config_override},
            agent_runner=lambda participant, prompt, context: {
                "status": "completed",
                "raw_output": "unexpected",
                "summary": "unexpected",
            },
        )
    assert chat_room_service.get_chat_room_detail(room["roomId"])["rounds"] == []


def test_start_chat_room_round_rejects_priority_reordering_of_frozen_roster(
    tmp_path, monkeypatch
):
    _isolate_chat_room_kernel(tmp_path, monkeypatch)
    sessions = [
        session_service.create_chat_session(title=f"Participant {index}")
        for index in range(4)
    ]
    frozen_agent_ids = [session["agentId"] for session in sessions]
    room = chat_room_service.create_chat_room(
        title="冻结四人会议",
        participant_agent_ids=frozen_agent_ids,
    )

    with pytest.raises(chat_room_service.ChatRoomValidationError, match="frozen participant"):
        chat_room_service.start_chat_room_round(
            room["roomId"],
            "冻结名单顺序不能被 priorityAgentIds 改写",
            mode="opportunistic",
            config={
                "participantAgentIds": frozen_agent_ids,
                "priorityAgentIds": list(reversed(frozen_agent_ids)),
            },
            agent_runner=lambda participant, prompt, context: {
                "status": "completed",
                "raw_output": "unexpected",
                "summary": "unexpected",
            },
        )
    assert chat_room_service.get_chat_room_detail(room["roomId"])["rounds"] == []


def test_reset_chat_room_clears_history_and_group_context_pollution(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    recorded_events = []
    monkeypatch.setattr(
        chat_room_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )
    prompts = []

    def fake_runner(participant, prompt, context):
        prompts.append(prompt)
        return {
            "status": "completed",
            "raw_output": f"{participant['title']} 提到旧污染",
            "summary": "旧污染摘要",
        }

    alpha = agent_directory_service.ensure_agent_for_session("session-alpha", display_name="Alpha Agent")
    beta = agent_directory_service.ensure_agent_for_session("session-beta", display_name="Beta Agent")
    room = chat_room_service.create_chat_room(
        title="可重置群聊",
        participant_agent_ids=[alpha["agentId"], beta["agentId"]],
        purpose="meeting",
        config={"source": "team", "teamId": "team-a"},
    )
    detail = chat_room_service.start_chat_room_round(
        room["roomId"],
        "旧污染议题",
        agent_runner=fake_runner,
    )
    latest_round = detail["rounds"][-1]
    assert latest_round["messages"]
    assert "旧污染议题" in prompts[0]
    assert agent_directory_service.list_group_context_events_for_agent(
        alpha["agentId"],
        prompt_eligible_only=True,
    )
    assert _has_room_transcript(tmp_path, "session-alpha", room["roomId"])
    assert _has_room_transcript(tmp_path, "session-beta", room["roomId"])

    reset = chat_room_service.reset_chat_room(room["roomId"])

    assert reset["roomId"] == room["roomId"]
    assert reset["title"] == "可重置群聊"
    assert reset["purpose"] == "meeting"
    assert reset["config"]["teamId"] == "team-a"
    assert [participant["agentId"] for participant in reset["participants"]] == [alpha["agentId"], beta["agentId"]]
    assert reset["rounds"] == []
    assert reset["status"] == "ready"
    assert reset["activeRoundId"] == ""
    assert not _has_room_transcript(tmp_path, "session-alpha", room["roomId"])
    assert not _has_room_transcript(tmp_path, "session-beta", room["roomId"])
    assert not agent_directory_service.list_group_context_events_for_agent(
        alpha["agentId"],
        prompt_eligible_only=True,
    )
    reset_events = [
        event
        for event in recorded_events
        if event[0][:3] == ("chat_room", "room", "chat_room.reset")
    ]
    assert reset_events
    reset_fields = reset_events[-1][1]["fields"]
    assert reset_fields["clearedRoundCount"] == 1
    assert reset_fields["clearedMessageCount"] == 2
    assert reset_fields["clearedSessionTranscriptCount"] == 2
    assert reset_fields["disabledGroupContextEventCount"] == 2

    prompts.clear()
    next_detail = chat_room_service.start_chat_room_round(
        room["roomId"],
        "新议题",
        agent_runner=fake_runner,
    )

    assert len(next_detail["rounds"]) == 1
    assert "旧污染议题" not in prompts[0]
    assert "旧污染摘要" not in prompts[0]


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
    recorded_room_events = []
    monkeypatch.setattr(
        agent_directory_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )
    monkeypatch.setattr(
        chat_room_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_room_events.append((args, kwargs)) or {"accepted": True},
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
    assert latest_round["status"] == "partial"
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
    assert any(
        event[0][:3] == ("chat_room", "speaker", "chat_room.speaker.blocked")
        for event in recorded_room_events
    )
    assert any(
        event[0][:3] == ("chat_room", "round", "chat_room.round.partial")
        for event in recorded_room_events
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


def test_chat_room_participant_runner_reuses_session_workspace_and_agent_llm_binding(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    base_config = session_service.get_config().model_copy(deep=True)
    base_config.llm.model_library["agent-explorer-model"] = {
        "provider_id": base_config.llm.profiles["primary"].provider_id,
        "model": "explorer-model",
        "streaming": False,
        "tool_calling_mode": "disabled",
    }
    monkeypatch.setattr(session_service, "get_config", lambda: base_config)
    beta_agent = agent_directory_service.ensure_agent_for_session("session-beta", display_name="Beta Agent")
    detail = session_service.get_session_detail("session-beta")
    agent_id = detail["agentId"] or beta_agent["agentId"]
    agent_directory_service.update_agent_instance(
        agent_id,
        llm_bindings={"dialogue": {"modelId": "agent-explorer-model"}},
    )
    captured = {}
    captured_receipt_routes = []
    original_build_receipt_context = meeting_receipt_authority.build_speaker_receipt_context

    def capture_receipt_context(*args, **kwargs):
        captured_receipt_routes.append(dict(kwargs["expected_model_route"]))
        return original_build_receipt_context(*args, **kwargs)

    monkeypatch.setattr(
        meeting_receipt_authority,
        "build_speaker_receipt_context",
        capture_receipt_context,
    )

    class ProfileAwareAgent:
        def __init__(self, workspace_path=None, config=None):
            captured["workspace_path"] = str(workspace_path or "")
            captured["primary_model"] = config.llm.get_profile(role="primary").model

        def set_turn_identity(self, turn_identity):
            captured["turn_identity"] = str(turn_identity or "")

        def seed_chat_history(self, messages):
            captured["history"] = list(messages)

        def seed_static_runtime_context(self, content):
            captured["static_runtime_context"] = str(content or "")

        def seed_runtime_context(self, content):
            captured.setdefault("runtime_contexts", []).append(str(content or ""))

        def mark_runtime_context_seeded_by_host(self):
            captured["runtime_context_seeded_by_host"] = True

        def run_single_turn(self, initial_prompt=None, disable_tools=False):
            captured["active_runtime"] = agent_directory_service.current_agent_runtime()
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

    assert detail["participants"][0]["agentId"] == agent_id
    event_path = tmp_path / "workspace" / "agents" / agent_id / "events" / "agent_turn_results.jsonl"
    turn_results = [
        json.loads(line)
        for line in event_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert captured["workspace_path"] == str((tmp_path / "workspace" / "agents" / agent_id).resolve())
    assert captured["primary_model"] == "explorer-model"
    assert f"AgentId: {agent_id}" in captured["static_runtime_context"]
    assert captured["runtime_context_seeded_by_host"] is True
    assert captured["history"]
    assert captured["turn_identity"].startswith("chat-room:")
    assert captured["active_runtime"]["turnId"] == captured["turn_identity"]
    assert captured_receipt_routes == [
        {
            "modelRef": "agent-explorer-model",
            "providerId": base_config.llm.profiles["primary"].provider_id,
            "modelId": "explorer-model",
        }
    ]
    assert turn_results[-1]["agentId"] == agent_id
    assert turn_results[-1]["status"] == "completed"
    assert detail["rounds"][-1]["messages"][0]["status"] == "completed"
    latest_message = detail["rounds"][-1]["messages"][0]
    assert latest_message["timings"]["agentLookupMs"] >= 0
    assert latest_message["timings"]["agentContextBuildMs"] >= 0
    assert latest_message["timings"]["agentCreateMs"] >= 0
    assert latest_message["timings"]["agentSeedMs"] >= 0
    assert latest_message["timings"]["llmElapsedMs"] >= 0


def test_chat_room_real_agent_reaches_llm_with_bound_turn_identity(tmp_path, monkeypatch):
    _isolate_chat_room_kernel(tmp_path, monkeypatch)
    monkeypatch.setattr(session_service, "build_agent_context", _lightweight_agent_context)
    monkeypatch.setattr(chat_room_service, "build_agent_context", _lightweight_agent_context)
    llm_bindings = _install_chat_room_test_llm_config(monkeypatch)
    alpha = session_service.create_chat_session(title="Alpha Agent", llm_bindings=llm_bindings)
    beta = session_service.create_chat_session(title="Beta Agent", llm_bindings=llm_bindings)
    room = chat_room_service.create_chat_room(
        title="真实 Agent 身份群聊",
        participant_agent_ids=[alpha["agentId"], beta["agentId"]],
        config={"maxSpeakers": 1},
    )
    invocations = []

    def fake_invoke_llm(self, messages, *, replay_state=None):
        invocations.append(agent_directory_service.current_agent_runtime())
        return None

    monkeypatch.setattr(SelfEvolvingAgent, "_invoke_llm", fake_invoke_llm)

    detail = chat_room_service.start_chat_room_round(room["roomId"], "检查群聊 turn identity")

    assert invocations
    assert invocations[0]["sessionId"]
    assert invocations[0]["turnId"].startswith("chat-room:")
    latest_message = detail["rounds"][-1]["messages"][0]
    assert "ledger identity" not in str(latest_message.get("content") or "").lower()


def test_formal_meeting_speaker_builds_question_receipt_context():
    authority = {
        "schemaVersion": 1,
        "authorityKind": "workflow_run",
        "teamId": "team-formal",
        "questionId": "SCI-096",
        "workflowRunId": "run-formal",
        "workflowId": "challenge-cup-research",
        "workflowVersionId": "wv-formal",
        "modelPolicySha256": "a" * 64,
    }

    receipt_context = meeting_receipt_authority.build_speaker_receipt_context(
        {"participantId": "participant-1", "agentId": "agent-1"},
        {
            "roundId": "round-1",
            "meetingRoundId": "meeting-1",
            "meetingType": "hypothesis_candidate_generation",
            "teamId": "team-formal",
            "questionId": "SCI-096",
            "_modelInvocationReceiptAuthority": authority,
        },
        session_id="session-1",
        turn_identity="chat-room:round-1:participant-1",
        expected_model_route={
            "modelRef": "opencode/deepseek-v4-flash",
            "providerId": "opencode",
            "modelId": "deepseek-v4-flash",
        },
    )

    assert receipt_context is not None
    assert receipt_context["receiptRunId"] == "run-formal"
    assert receipt_context["outcomeKinds"] == ["candidate"]
    assert receipt_context["expectedModelRoute"] == {
        "modelRef": "opencode/deepseek-v4-flash",
        "providerId": "opencode",
        "modelId": "deepseek-v4-flash",
    }
    binding = receipt_context["questionStageBinding"]
    assert binding["questionStage"] == "generation"
    assert binding["formalNodeId"] == "hypothesis_design"
    assert binding["formalNodeRunId"] == "meeting:meeting-1:round-1:participant-1"
    assert receipt_context["evidenceLocator"]["executionKind"] == "chat_room_meeting"


def test_formal_meeting_speaker_without_receipt_fails_closed(monkeypatch):
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.model_invocation_receipt_registry.question_model_invocation_receipts",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "core.chat.conversation_ledger.load_conversation_events",
        lambda *_args: [],
    )

    with pytest.raises(
        meeting_receipt_authority.MeetingReceiptAuthorityError,
        match="without a verifiable invocation receipt",
    ):
        meeting_receipt_authority.register_speaker_receipts(
            project_root=Path("."),
            team_id="team-formal",
            question_id="SCI-096",
            workflow_run_id="run-formal",
            session_id="session-1",
            turn_identity="turn-1",
        )


def test_formal_meeting_speaker_turn_projects_receipt_outside_journal(
    tmp_path,
    monkeypatch,
):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.meeting_receipt_authority.workflow_run_stop_reason",
        lambda _authority: "",
    )
    base_config = session_service.get_config().model_copy(deep=True)
    _provider_id = base_config.llm.profiles["primary"].provider_id
    _model_key = f"{_provider_id}/agent-explorer-model"
    # Receipt route validation requires the model library key (the resolved
    # modelRef) to carry the provider prefix, as production entries do.
    base_config.llm.model_library[_model_key] = {
        "provider_id": _provider_id,
        "model": "explorer-model",
        "streaming": False,
        "tool_calling_mode": "disabled",
    }
    monkeypatch.setattr(session_service, "get_config", lambda: base_config)
    beta_agent = agent_directory_service.ensure_agent_for_session("session-beta", display_name="Beta Agent")
    detail = session_service.get_session_detail("session-beta")
    agent_id = detail["agentId"] or beta_agent["agentId"]
    agent_directory_service.update_agent_instance(
        agent_id,
        llm_bindings={"dialogue": {"modelId": _model_key}},
    )

    registered_receipts = []
    from core.web.services.team_workflow.research_runtime import (
        model_invocation_receipt_registry,
    )

    def capture_registration(*_args, **kwargs):
        registered_receipts.extend(list(kwargs.get("receipts") or []))
        return [f"receipt-ref-{index}" for index, _ in enumerate(registered_receipts)]

    monkeypatch.setattr(
        model_invocation_receipt_registry,
        "register_question_model_invocation_receipts",
        capture_registration,
    )

    class ReceiptJournalingAgent:
        def __init__(self, workspace_path=None, config=None):
            pass

        def set_turn_identity(self, turn_identity):
            self.turn_identity = str(turn_identity or "")

        def seed_chat_history(self, messages):
            pass

        def seed_static_runtime_context(self, content):
            pass

        def seed_runtime_context(self, content):
            pass

        def mark_runtime_context_seeded_by_host(self):
            pass

        def set_turn_interrupt_checker(self, checker):
            pass

        def record_turn_preparation_diagnostic(self, diagnostic):
            pass

        def clear_turn_preparation_state(self):
            pass

        def run_single_turn(self, initial_prompt=None, disable_tools=False):
            from core.infrastructure.event_bus import EventNames, get_event_bus

            runtime = agent_directory_service.current_agent_runtime()
            identity = SimpleNamespace(
                session_id=str(runtime.get("sessionId") or ""),
                turn_id=str(runtime.get("turnId") or ""),
                invocation_id="inv-meeting-1",
                iteration=0,
                item_id="item-final",
                item_revision=0,
                sequence=0,
            )
            outcome = SimpleNamespace(
                identity=identity,
                kind="final_answer",
                final_text="CANDIDATE: C1 | 候选假说 | 理由",
                events=(),
                tool_calls=(),
                model_invocation_receipt={
                    "receiptId": "receipt-meeting-1",
                    "provider": "opencode",
                    "model": "deepseek-v4-flash",
                },
            )
            get_event_bus().publish(
                EventNames.LLM_RESPONSE,
                {"turn_outcome": outcome},
                source="agent.canonical_turn_outcome",
            )
            return {
                "status": "completed",
                "raw_output": "CANDIDATE: C1 | 候选假说 | 理由",
                "summary": "ok",
                "tool_call_count": 0,
            }

    monkeypatch.setattr(session_service, "create_chat_agent", ReceiptJournalingAgent)
    room = chat_room_service.create_chat_room(
        title="正式会议回执群聊",
        participant_session_ids=["session-beta"],
    )
    participant = room["participants"][0]
    authority = {
        "schemaVersion": 1,
        "authorityKind": "workflow_run",
        "teamId": "team-formal",
        "questionId": "SCI-096",
        "workflowRunId": "run-formal",
        "workflowId": "challenge-cup-research",
        "workflowVersionId": "wv-formal",
        "modelPolicySha256": "a" * 64,
    }

    result = chat_room_service._run_participant_agent(
        participant,
        "请提出候选假说",
        {
            "roomId": room["roomId"],
            "roundId": "round-formal-1",
            "topic": "候选假说生成",
            "purpose": "meeting",
            "meetingRoundId": "meeting-formal-1",
            "meetingType": "hypothesis_candidate_generation",
            "teamId": "team-formal",
            "questionId": "SCI-096",
            "_modelInvocationReceiptAuthority": authority,
        },
    )

    assert result["status"] == "completed"
    session_id = str(participant.get("sessionId") or "").strip()
    participant_id = str(participant.get("participantId") or "").strip()
    journal_path = (
        tmp_path
        / "workspace"
        / "sessions"
        / session_id
        / "turn_journal.jsonl"
    )
    assert journal_path.exists(), "formal meeting turn must journal its canonical outcome"
    committed_events = []
    for line in journal_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("eventType") != "assistant_item_committed":
            continue
        if event.get("source") != "canonical_turn_outcome":
            continue
        if event.get("turnId") != f"chat-room:round-formal-1:{participant_id}":
            continue
        payload = event.get("payload") or {}
        committed_events.append(payload)
    assert len(committed_events) == 1
    assert "modelInvocationReceipt" not in committed_events[0]
    assert "requestExcerpt" not in str(committed_events[0])
    assert "responseExcerpt" not in str(committed_events[0])
    assert [receipt.get("receiptId") for receipt in registered_receipts] == ["receipt-meeting-1"]


def test_scoped_discussion_room_round_fails_closed_without_receipt_authority(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    scoped_room = chat_room_service.create_chat_room(
        title="正式阶段群聊",
        participant_session_ids=["session-beta"],
        purpose="meeting",
        config={
            "scopeAuthority": "workflow_discussion_scope.v1",
            "discussionScope": {"kind": "hypothesis_review", "questionId": "SCI-096", "key": "scope-1"},
            "scopeHash": "c" * 24,
        },
    )

    with pytest.raises(chat_room_service.ChatRoomValidationError) as excinfo:
        chat_room_service.start_chat_room_round(
            scoped_room["roomId"],
            "假说评审会议开幕",
        )
    message = str(excinfo.value)
    assert "回执授权" in message or "receipt authority" in message

    authority = {
        "schemaVersion": 1,
        "authorityKind": "workflow_run",
        "teamId": "team-formal",
        "questionId": "SCI-096",
        "workflowRunId": "run-formal",
        "workflowId": "challenge-cup-research",
        "workflowVersionId": "wv-formal",
        "modelPolicySha256": "a" * 64,
    }
    with_authority_message = ""
    try:
        chat_room_service.start_chat_room_round(
            scoped_room["roomId"],
            "假说评审会议开幕",
            _model_invocation_receipt_authority=authority,
        )
    except chat_room_service.ChatRoomValidationError as exc:
        with_authority_message = str(exc)
    assert "回执授权" not in with_authority_message and "receipt authority" not in with_authority_message


def test_formal_challenge_room_uses_structured_message_contract_without_changing_normal_rooms(
    tmp_path,
    monkeypatch,
):
    _isolate_chat_room_kernel(tmp_path, monkeypatch)
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.challenge_turn_policy.current_challenge_task_deadline_at_ms",
        lambda: None,
    )
    structured_output = json.dumps(
        {
            "schemaVersion": 1,
            "display": {
                "conclusion": "当前证据不足，暂不升级候选。",
                "sections": [
                    {"title": "判断依据", "bullets": ["缺少直接证据。"]},
                ],
            },
            "protocol": {
                "agreements": ["保留当前候选等级。"],
                "disagreements": [],
                "risks": ["检索覆盖不完整。"],
                "actionItems": [],
                "knowledgeCandidates": [],
                "proposedCandidates": [],
                "evidenceRequests": [],
            },
        },
        ensure_ascii=False,
    )
    captured_prompts = []

    formal_room = chat_room_service.create_chat_room(
        title="正式挑战杯讨论",
        participant_session_ids=["session-beta"],
        purpose="meeting",
        config={
            "scopeAuthority": "workflow_discussion_scope.v1",
            "discussionScope": {
                "kind": "hypothesis_review",
                "questionId": "SCI-096",
                "key": "scope-structured",
            },
            "scopeHash": "d" * 24,
        },
    )
    authority = {
        "schemaVersion": 1,
        "authorityKind": "workflow_run",
        "teamId": "team-formal",
        "questionId": "SCI-096",
        "workflowRunId": "run-formal",
        "workflowId": "challenge-cup-research",
        "workflowVersionId": "wv-formal",
        "modelPolicySha256": "a" * 64,
    }

    def formal_runner(_participant, prompt, _context):
        captured_prompts.append(prompt)
        return {"status": "completed", "raw_output": structured_output, "summary": "ok"}

    formal_detail = chat_room_service.start_chat_room_round(
        formal_room["roomId"],
        "评审候选证据",
        config={
            "teamId": "team-formal",
            "question": "SCI-096",
            "meetingRoundId": "meeting-structured",
            "meetingType": "hypothesis_review",
            "challengeDeadlineAtMs": int(time.time() * 1000) + 60_000,
        },
        agent_runner=formal_runner,
        _model_invocation_receipt_authority=authority,
    )

    formal_message = formal_detail["rounds"][-1]["messages"][0]
    assert "挑战杯会议结构化输出合同" in captured_prompts[0]
    assert formal_message["content"].startswith("当前证据不足，暂不升级候选。")
    assert formal_message["messagePayload"]["audit"]["parseStatus"] == "structured"
    assert formal_message["messagePayload"]["audit"]["rawModelOutput"] == structured_output
    assert formal_message["messagePayload"]["protocol"]["agreements"] == ["保留当前候选等级。"]

    normal_prompts = []
    normal_room = chat_room_service.create_chat_room(
        title="普通会议群聊",
        participant_session_ids=["session-alpha"],
        purpose="meeting",
    )

    def normal_runner(_participant, prompt, _context):
        normal_prompts.append(prompt)
        return {"status": "completed", "raw_output": "普通会议文本保持不变。", "summary": "ok"}

    normal_detail = chat_room_service.start_chat_room_round(
        normal_room["roomId"],
        "普通会议",
        agent_runner=normal_runner,
    )
    normal_message = normal_detail["rounds"][-1]["messages"][0]
    assert "挑战杯会议结构化输出合同" not in normal_prompts[0]
    assert normal_message["content"] == "普通会议文本保持不变。"
    assert "messagePayload" not in normal_message


def test_formal_room_speakers_share_one_challenge_deadline(tmp_path, monkeypatch):
    _isolate_chat_room_kernel(tmp_path, monkeypatch)
    _seed_chat_sessions(tmp_path)
    now_seconds = [999.0]
    deadline_at_ms = 1_000_000
    monkeypatch.setattr(chat_room_service.time, "time", lambda: now_seconds[0])
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.challenge_turn_policy.current_challenge_task_deadline_at_ms",
        lambda: None,
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.meeting_receipt_authority.workflow_run_stop_reason",
        lambda _authority: "",
    )
    room = chat_room_service.create_chat_room(
        title="正式共享截止时间群聊",
        participant_session_ids=["session-alpha", "session-beta"],
        purpose="meeting",
        config={
            "scopeAuthority": "workflow_discussion_scope.v1",
            "discussionScope": {"kind": "question_generation", "questionId": "SCI-096"},
            "scopeHash": "d" * 64,
        },
    )
    authority = {
        "schemaVersion": 1,
        "authorityKind": "workflow_run",
        "teamId": "team-formal",
        "questionId": "SCI-096",
        "workflowRunId": "run-formal",
        "workflowId": "challenge-cup-research",
        "workflowVersionId": "wv-formal",
        "modelPolicySha256": "a" * 64,
    }
    called_participants = []

    def runner(participant, _prompt, context):
        called_participants.append(participant["participantId"])
        assert context["challengeDeadlineAtMs"] == deadline_at_ms
        now_seconds[0] = 1000.001
        return {"status": "completed", "raw_output": "候选一", "summary": "ok"}

    detail = chat_room_service.start_chat_room_round(
        room["roomId"],
        "候选生成",
        config={"challengeDeadlineAtMs": deadline_at_ms},
        agent_runner=runner,
        _model_invocation_receipt_authority=authority,
    )

    latest = detail["rounds"][-1]
    assert len(called_participants) == 1
    assert latest["config"]["challengeDeadlineAtMs"] == deadline_at_ms
    assert latest["status"] == "stopped"
    assert latest["terminalReason"] == "challenge_logical_task_deadline_exhausted"
    assert len(latest["messages"]) == 1
    assert latest["messages"][0]["status"] == "stopped"
    assert latest["messages"][0]["content"] == ""
    assert latest["messages"][0]["lateResultDiscarded"] is True
    assert "1/2" in latest["summary"]
    assert "challenge_logical_task_deadline_exhausted" in latest["summary"]


@pytest.mark.parametrize(
    "stop_reason",
    ["challenge_workflow_run_cancelled", "challenge_workflow_run_blocked"],
)
def test_formal_room_stops_fanout_when_parent_workflow_run_is_inactive(
    tmp_path,
    monkeypatch,
    stop_reason,
):
    _isolate_chat_room_kernel(tmp_path, monkeypatch)
    _seed_chat_sessions(tmp_path)
    room = chat_room_service.create_chat_room(
        title="父任务取消群聊",
        participant_session_ids=["session-alpha", "session-beta"],
        purpose="meeting",
        config={
            "scopeAuthority": "workflow_discussion_scope.v1",
            "discussionScope": {"kind": "question_generation", "questionId": "SCI-096"},
            "scopeHash": "d" * 64,
        },
    )
    authority = {
        "schemaVersion": 1,
        "authorityKind": "workflow_run",
        "teamId": "team-formal",
        "questionId": "SCI-096",
        "workflowRunId": "run-cancelled",
        "workflowId": "challenge-cup-research",
        "workflowVersionId": "wv-formal",
        "modelPolicySha256": "a" * 64,
    }
    run_reads = ["", stop_reason]
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.meeting_receipt_authority.workflow_run_stop_reason",
        lambda _authority: run_reads.pop(0) if run_reads else stop_reason,
    )
    called_participants = []
    terminal_bridges = []
    monkeypatch.setattr(
        "core.web.services.team_workflow.meeting_runtime.finalize_stopped_meeting_after_chat_round",
        lambda room, round_payload: terminal_bridges.append(
            (dict(room), dict(round_payload))
        ),
    )

    detail = chat_room_service.start_chat_room_round(
        room["roomId"],
        "候选生成",
        config={
            "meetingRoundId": "meeting-parent-run-stop",
            "meetingType": "hypothesis_candidate_generation",
            "teamId": "team-formal",
        },
        agent_runner=lambda participant, _prompt, _context: (
            called_participants.append(participant["participantId"])
            or {"status": "completed", "raw_output": "候选一", "summary": "ok"}
        ),
        _model_invocation_receipt_authority=authority,
    )

    latest = detail["rounds"][-1]
    assert len(called_participants) == 1
    assert len(latest["messages"]) == 1
    assert latest["status"] == "stopped"
    assert latest["terminalReason"] == stop_reason
    assert "1/2" in latest["summary"]
    assert len(terminal_bridges) == 1
    assert terminal_bridges[0][1]["roundId"] == latest["roundId"]


def test_formal_room_uses_earliest_outer_and_meeting_deadline(monkeypatch):
    from core.web.services.team_workflow.research_runtime import challenge_turn_policy

    room = {
        "config": {
            "scopeAuthority": "workflow_discussion_scope.v1",
            "discussionScope": {"kind": "question_generation", "questionId": "SCI-096"},
            "scopeHash": "d" * 64,
        }
    }
    authority = {"workflowRunId": "run-formal"}
    monkeypatch.setattr(
        challenge_turn_policy,
        "current_challenge_task_deadline_at_ms",
        lambda: 1_800_000,
    )
    assert chat_room_service._resolve_challenge_room_deadline_at_ms(
        room,
        {"challengeDeadlineAtMs": 300_000},
        receipt_authority=authority,
    ) == 300_000

    monkeypatch.setattr(
        challenge_turn_policy,
        "current_challenge_task_deadline_at_ms",
        lambda: 200_000,
    )
    assert chat_room_service._resolve_challenge_room_deadline_at_ms(
        room,
        {"challengeDeadlineAtMs": 300_000},
        receipt_authority=authority,
    ) == 200_000


def test_preformal_room_receives_server_meeting_deadline_without_receipt(monkeypatch):
    from core.web.services.team_workflow.research_runtime import challenge_turn_policy

    room = {
        "config": {
            "scopeAuthority": "preformal_candidate_review_scope.v1",
            "discussionScope": {
                "kind": "preformal_candidate_review",
                "questionId": "SCI-096",
            },
            "discussionScopeHash": "e" * 64,
        }
    }
    monkeypatch.setattr(
        challenge_turn_policy,
        "current_challenge_task_deadline_at_ms",
        lambda: None,
    )

    assert chat_room_service._resolve_challenge_room_deadline_at_ms(
        room,
        {"challengeDeadlineAtMs": 900_000},
        receipt_authority=None,
    ) == 900_000


def test_challenge_speaker_persists_heartbeat_without_touching_ordinary_rooms(
    tmp_path, monkeypatch
):
    _isolate_chat_room_kernel(tmp_path, monkeypatch)
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(
        chat_room_service, "_CHALLENGE_ROOM_HEARTBEAT_INTERVAL_SECONDS", 0.01
    )
    room = chat_room_service.create_chat_room(
        title="preformal heartbeat",
        participant_session_ids=["session-alpha"],
        purpose="meeting",
        config={
            "scopeAuthority": "preformal_candidate_review_scope.v1",
            "discussionScope": {
                "kind": "preformal_candidate_review",
                "questionId": "SCI-096",
            },
            "discussionScopeHash": "e" * 64,
        },
    )

    def slow_runner(*_args):
        time.sleep(0.05)
        return {"status": "completed", "raw_output": "pass", "summary": "pass"}

    detail = chat_room_service.start_chat_room_round(
        room["roomId"],
        "heartbeat",
        config={"challengeDeadlineAtMs": int(time.time() * 1000) + 5_000},
        agent_runner=slow_runner,
    )

    assert detail["rounds"][-1]["status"] == "completed"
    assert detail["rounds"][-1]["heartbeatAt"]
    work_run = chat_room_service._work_run_store().load_snapshot(
        chat_room_service.RUN_KIND, detail["rounds"][-1]["roundId"]
    )
    assert work_run["heartbeatAt"]


def test_candidate_generation_uses_trusted_short_answer_contract():
    prompt = chat_room_service._build_participant_prompt(
        room={"roomId": "room-formal", "title": "formal"},
        round_payload={
            "topic": "候选生成",
            "purpose": "meeting",
            "mode": "round_robin",
            "config": {
                "challengeDeadlineAtMs": 1_000_000,
                "meetingType": "hypothesis_candidate_generation",
            },
        },
        participant={
            "participantId": "participant-a",
            "agentCode": "A",
            "sessionId": "session-a",
        },
        prior_messages=[],
    )
    assert "正文不超过 180 个中文字符" in prompt
    assert "只输出一条 CANDIDATE 标记" in prompt

    grounded_prompt = chat_room_service._build_participant_prompt(
        room={"roomId": "room-grounded", "title": "grounded"},
        round_payload={
            "topic": "正式证据接地候选生成",
            "purpose": "meeting",
            "mode": "round_robin",
            "config": {
                "challengeDeadlineAtMs": 1_000_000,
                "meetingType": "hypothesis_candidate_generation",
                "candidateAuthority": "formal_grounded_candidate",
            },
        },
        participant={
            "participantId": "participant-a",
            "agentCode": "A",
            "sessionId": "session-a",
        },
        prior_messages=[],
    )
    assert "挑战杯会议结构化输出合同" in grounded_prompt
    assert "只输出一条 CANDIDATE 标记" not in grounded_prompt


def test_challenge_meeting_prior_prompt_keeps_late_candidate_and_review_rows():
    prior_messages = [
        {
            "speakerTitle": "A015 · 搜索 Agent",
            "content": (
                "先给出本轮检索的背景说明。\n"
                "前两行只是帮助理解的普通说明。\n"
                "CANDIDATE: C1 | 机制候选一 | 解释理由一\n"
                "CANDIDATE: C2 | 机制候选二 | 解释理由二\n"
                "[REV] C1 -> 补充边界条件与可证伪预测\n"
                "DISAGREE: C2 的干预路径仍缺少直接证据\n"
                "CONCLUSION: 保留 C1，要求下一步补充证据"
            ),
        }
    ]

    for meeting_type in ("hypothesis_candidate_generation", "hypothesis_review"):
        prompt = chat_room_service._build_participant_prompt(
            room={"roomId": "room-challenge", "title": "Challenge Cup"},
            round_payload={
                "topic": "候选讨论",
                "purpose": "meeting",
                "mode": "round_robin",
                "config": {"meetingType": meeting_type},
            },
            participant={"participantId": "participant-next", "sessionId": "session-next"},
            prior_messages=prior_messages,
        )
        assert "CANDIDATE: C1 | 机制候选一 | 解释理由一" in prompt
        assert "CANDIDATE: C2 | 机制候选二 | 解释理由二" in prompt
        assert "[REV] C1 -> 补充边界条件与可证伪预测" in prompt
        assert "DISAGREE: C2 的干预路径仍缺少直接证据" in prompt
        assert "CONCLUSION: 保留 C1，要求下一步补充证据" in prompt


def test_ordinary_prior_prompt_keeps_existing_three_line_compression():
    prompt = chat_room_service._build_participant_prompt(
        room={"roomId": "room-ordinary", "title": "普通群聊"},
        round_payload={
            "topic": "普通讨论",
            "purpose": "discussion",
            "mode": "round_robin",
        },
        participant={"participantId": "participant-next", "sessionId": "session-next"},
        prior_messages=[
            {
                "speakerTitle": "普通成员",
                "content": (
                    "普通说明第一行\n"
                    "普通说明第二行\n"
                    "普通说明第三行\n"
                    "普通说明第四行"
                ),
            }
        ],
    )

    assert "普通说明第一行" in prompt
    assert "普通说明第二行" in prompt
    assert "普通说明第三行" in prompt
    assert "普通说明第四行" not in prompt


def test_ordinary_room_does_not_inherit_challenge_deadline(tmp_path, monkeypatch):
    _isolate_chat_room_kernel(tmp_path, monkeypatch)
    _seed_chat_sessions(tmp_path)
    from core.web.services.team_workflow.research_runtime import challenge_turn_policy

    monkeypatch.setattr(chat_room_service.time, "time", lambda: 1000.0)
    monkeypatch.setattr(
        challenge_turn_policy,
        "current_challenge_task_deadline_at_ms",
        lambda: 999_000,
    )
    room = chat_room_service.create_chat_room(
        title="普通群聊",
        participant_session_ids=["session-alpha", "session-beta"],
    )
    contexts = []

    detail = chat_room_service.start_chat_room_round(
        room["roomId"],
        "普通讨论",
        agent_runner=lambda participant, _prompt, context: (
            contexts.append(dict(context))
            or {"status": "completed", "raw_output": participant["title"], "summary": "ok"}
        ),
    )

    latest = detail["rounds"][-1]
    assert latest["status"] == "completed"
    assert len(latest["messages"]) == 2
    assert "challengeDeadlineAtMs" not in latest["config"]
    assert all(context["challengeDeadlineAtMs"] is None for context in contexts)


def test_challenge_room_interrupt_checker_enables_provider_abort_and_classifies_cancel(monkeypatch):
    now_seconds = [999.0]
    monkeypatch.setattr(chat_room_service.time, "time", lambda: now_seconds[0])
    context = {
        "roomId": "room-formal",
        "roundId": "round-formal",
        "challengeDeadlineAtMs": 1_000_000,
        "speakerStartedAtMonotonic": chat_room_service._perf_counter(),
        "caseState": {},
    }
    checker = chat_room_service._chat_room_interrupt_checker("round-formal", context)
    assert checker() == ""
    assert checker._vibelution_chat_provider_abort_enabled is True

    def cancelled_runner(*_args):
        now_seconds[0] = 1000.001
        raise RuntimeError("provider connection closed after cancellation")

    message = chat_room_service._run_one_speaker(
        {
            "participantId": "participant-formal",
            "agentId": "agent-formal",
            "sessionId": "session-formal",
        },
        "prompt",
        context,
        cancelled_runner,
    )

    assert checker() == "challenge_logical_task_deadline_exhausted"
    assert message["status"] == "stopped"
    assert message["summary"] == "challenge_logical_task_deadline_exhausted"
    ordinary_checker = chat_room_service._chat_room_interrupt_checker(
        "round-ordinary", {"challengeDeadlineAtMs": None}
    )
    assert ordinary_checker._vibelution_chat_provider_abort_enabled is False

    blocked_context = {
        "challengeDeadlineAtMs": 2_000_000,
        "_modelInvocationReceiptAuthority": {"workflowRunId": "run-blocked"},
    }
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.meeting_receipt_authority.workflow_run_stop_reason",
        lambda _authority: "challenge_workflow_run_blocked",
    )
    blocked_checker = chat_room_service._chat_room_interrupt_checker(
        "round-blocked",
        blocked_context,
    )
    assert blocked_checker() == "challenge_workflow_run_blocked"
    assert blocked_checker._vibelution_chat_provider_abort_enabled is True


def test_challenge_per_call_budget_exhaustion_discards_speaker_and_round_advances(
    tmp_path, monkeypatch
):
    """Per-call expiry fences only one speaker call; the meeting stays open."""

    _isolate_chat_room_kernel(tmp_path, monkeypatch)
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.challenge_turn_policy.current_challenge_task_deadline_at_ms",
        lambda: None,
    )
    now_seconds = [1000.0]
    monkeypatch.setattr(chat_room_service.time, "time", lambda: now_seconds[0])
    room = chat_room_service.create_chat_room(
        title="逐调用预算群聊",
        participant_session_ids=["session-alpha", "session-beta"],
        purpose="meeting",
        config={
            "scopeAuthority": "workflow_discussion_scope.v1",
            "discussionScope": {"kind": "hypothesis_review", "questionId": "SCI-096"},
            "scopeHash": "c" * 24,
        },
    )
    authority = {
        "schemaVersion": 1,
        "authorityKind": "workflow_run",
        "teamId": "team-percall",
        "questionId": "SCI-096",
        "workflowRunId": "run-percall",
        "workflowId": "challenge-cup-research",
        "workflowVersionId": "wv-percall",
        "modelPolicySha256": "a" * 64,
    }
    meeting_deadline_ms = 1_000_000 + 3_600_000
    contexts = []
    called_participants = []

    def runner(participant, _prompt, context):
        called_participants.append(participant["participantId"])
        contexts.append(dict(context))
        if len(called_participants) == 1:
            # The provider answers after the per-call fence but well before
            # the meeting deadline: this one late result must be discarded.
            now_seconds[0] = 1060.0
            return {"status": "completed", "raw_output": "晚到发言", "summary": "late"}
        return {"status": "completed", "raw_output": "正常发言", "summary": "ok"}

    meeting_bridges = []
    auto_drafts = []
    monkeypatch.setattr(
        "core.web.services.team_workflow.meeting_runtime.finalize_stopped_meeting_after_chat_round",
        lambda room, round_payload: meeting_bridges.append(dict(round_payload)),
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.meeting_runtime.maybe_auto_draft_meeting",
        lambda *_args, **_kwargs: auto_drafts.append(True) or {},
    )

    detail = chat_room_service.start_chat_room_round(
        room["roomId"],
        "假说评审",
        config={
            "challengeDeadlineAtMs": meeting_deadline_ms,
            "perCallBudgetMs": 50_000,
            "meetingRoundId": "meeting-percall",
            "teamId": "team-percall",
        },
        agent_runner=runner,
        _model_invocation_receipt_authority=authority,
    )

    latest = detail["rounds"][-1]
    assert called_participants == [
        detail["participants"][0]["participantId"],
        detail["participants"][1]["participantId"],
    ]
    # The meeting-level clock is no longer overwritten by the per-call fence.
    assert contexts[0]["challengeDeadlineAtMs"] == meeting_deadline_ms
    assert contexts[0]["challengePerCallDeadlineAtMs"] == 1_050_000
    assert contexts[1]["challengeDeadlineAtMs"] == meeting_deadline_ms
    assert contexts[1]["challengePerCallDeadlineAtMs"] == 1_110_000
    # The round advanced past the exhausted speaker call and stays open: it
    # closes as a normal (non-stopped) round with one discarded speech.
    assert latest["status"] == "partial"
    assert not str(latest.get("terminalReason") or "").strip()
    assert len(latest["messages"]) == 2
    assert latest["messages"][0]["status"] == "stopped"
    assert latest["messages"][0]["lateResultDiscarded"] is True
    assert latest["messages"][0]["summary"] == "challenge_per_call_budget_exhausted"
    assert latest["messages"][1]["status"] == "completed"
    assert meeting_bridges == []


def test_challenge_meeting_deadline_expiry_still_terminates_meeting(tmp_path, monkeypatch):
    """Fail-closed guard: meeting-level expiry keeps terminating the meeting."""

    _isolate_chat_room_kernel(tmp_path, monkeypatch)
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.challenge_turn_policy.current_challenge_task_deadline_at_ms",
        lambda: None,
    )
    now_seconds = [1000.0]
    monkeypatch.setattr(chat_room_service.time, "time", lambda: now_seconds[0])
    room = chat_room_service.create_chat_room(
        title="会议级到期群聊",
        participant_session_ids=["session-alpha", "session-beta"],
        purpose="meeting",
        config={
            "scopeAuthority": "workflow_discussion_scope.v1",
            "discussionScope": {"kind": "hypothesis_review", "questionId": "SCI-096"},
            "scopeHash": "c" * 24,
        },
    )
    authority = {
        "schemaVersion": 1,
        "authorityKind": "workflow_run",
        "teamId": "team-meeting-deadline",
        "questionId": "SCI-096",
        "workflowRunId": "run-meeting-deadline",
        "workflowId": "challenge-cup-research",
        "workflowVersionId": "wv-meeting-deadline",
        "modelPolicySha256": "a" * 64,
    }
    meeting_deadline_ms = 1_000_500

    def runner(participant, _prompt, context):
        # The speaker call answers after the meeting deadline.
        now_seconds[0] = 1001.0
        return {"status": "completed", "raw_output": "迟到发言", "summary": "late"}

    meeting_bridges = []
    monkeypatch.setattr(
        "core.web.services.team_workflow.meeting_runtime.finalize_stopped_meeting_after_chat_round",
        lambda room, round_payload: meeting_bridges.append(dict(round_payload)),
    )

    detail = chat_room_service.start_chat_room_round(
        room["roomId"],
        "假说评审",
        config={
            "challengeDeadlineAtMs": meeting_deadline_ms,
            "perCallBudgetMs": 600_000,
            "meetingRoundId": "meeting-meeting-deadline",
            "teamId": "team-meeting-deadline",
        },
        agent_runner=runner,
        _model_invocation_receipt_authority=authority,
    )

    latest = detail["rounds"][-1]
    assert latest["status"] == "stopped"
    assert latest["terminalReason"] == "challenge_logical_task_deadline_exhausted"
    assert latest["messages"][0]["lateResultDiscarded"] is True
    assert len(meeting_bridges) == 1
    assert (
        meeting_bridges[0]["terminalReason"] == "challenge_logical_task_deadline_exhausted"
    )
    assert meeting_bridges[0]["config"]["meetingRoundId"] == "meeting-meeting-deadline"


def test_chat_room_participant_runner_rejects_archived_agent_before_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    detail = session_service.create_chat_session(title="群聊归档 Agent")
    peer = session_service.create_chat_session(title="群聊保留 Agent")
    room = chat_room_service.create_chat_room(
        title="归档成员群聊",
        participant_agent_ids=[detail["agentId"], peer["agentId"]],
    )
    participant = room["participants"][0]
    events = []
    monkeypatch.setattr(
        chat_room_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)) or {"accepted": True},
    )
    monkeypatch.setattr(
        session_service,
        "create_chat_agent",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("archived participant must not create runtime")),
    )

    agent_directory_service.archive_agent_instance(detail["agentId"])
    try:
        chat_room_service._run_participant_agent(
            participant,
            "请发言",
            {
                "roomId": room["roomId"],
                "roundId": "round-archived",
                "topic": "归档阻断",
                "purpose": "discussion",
            },
        )
    except chat_room_service.ChatRoomValidationError as exc:
        assert "已归档" in str(exc) or "archived" in str(exc)
    else:
        raise AssertionError("archived chat-room participant should be blocked before runtime")

    archived_events = [
        item
        for item in events
        if item[0][:3] == (
            "chat_room",
            "participant_agent",
            "chat_room.participant_agent_archived",
        )
    ]
    assert len(archived_events) == 1
    assert archived_events[0][1]["fields"]["agentId"] == detail["agentId"]


def test_chat_room_speaker_turn_passes_stable_prompt_cache_partition(tmp_path, monkeypatch):
    """Speaker LLM calls bind a non-empty, stable per-(room, session) cache partition.

    The speaker path replays the session ledger history on every call, so the
    partition handed to run_existing_agent_single_turn must stay identical
    across turns of one speaker session in one room (prefix cache hits) while
    staying disjoint across sessions and rooms (no shard sharing).
    """
    _isolate_chat_room_kernel(tmp_path, monkeypatch)
    alpha = session_service.create_chat_session(title="分区发言者甲")
    beta = session_service.create_chat_session(title="分区发言者乙")
    alpha_session_id = str(alpha.get("id") or "").strip()
    beta_session_id = str(beta.get("id") or "").strip()
    assert alpha_session_id and beta_session_id
    room_one = chat_room_service.create_chat_room(
        title="分区房间一",
        participant_session_ids=[alpha_session_id, beta_session_id],
    )
    room_two = chat_room_service.create_chat_room(
        title="分区房间二",
        participant_session_ids=[alpha_session_id],
    )

    def participant_in(room, session_id):
        return next(
            p for p in room["participants"] if str(p.get("sessionId") or "") == session_id
        )

    captured: list[dict] = []

    def fake_runner(_agent, **kwargs):
        captured.append(dict(kwargs))
        return {"status": "completed", "raw_output": "ok", "summary": "ok"}

    monkeypatch.setattr(chat_room_service, "run_existing_agent_single_turn", fake_runner)

    def run_speaker(participant, room_id):
        return chat_room_service._run_participant_agent(
            participant,
            "请发言",
            {
                "roomId": room_id,
                "roundId": "round-partition",
                "topic": "缓存分区",
                "purpose": "discussion",
            },
        )

    alpha_one = participant_in(room_one, alpha_session_id)
    beta_one = participant_in(room_one, beta_session_id)
    alpha_two = participant_in(room_two, alpha_session_id)

    assert run_speaker(alpha_one, room_one["roomId"])["status"] == "completed"
    assert run_speaker(alpha_one, room_one["roomId"])["status"] == "completed"
    assert run_speaker(beta_one, room_one["roomId"])["status"] == "completed"
    assert run_speaker(alpha_two, room_two["roomId"])["status"] == "completed"

    assert len(captured) == 4
    partition_alpha = captured[0]["prompt_cache_partition"]
    # Non-empty and scoped to the (room, session) pair.
    assert partition_alpha
    assert partition_alpha.startswith("chat-room:")
    assert room_one["roomId"] in partition_alpha
    assert alpha_session_id in partition_alpha
    # Same room + session across turns -> identical partition (cache hits).
    assert captured[1]["prompt_cache_partition"] == partition_alpha
    # Different session in the same room -> different partition.
    assert captured[2]["prompt_cache_partition"] != partition_alpha
    # Same session in a different room -> different partition.
    assert captured[3]["prompt_cache_partition"] != partition_alpha


def test_speaker_prompt_cache_partition_requires_session_id():
    assert chat_room_service._speaker_prompt_cache_partition("", "room-1") == ""
    assert chat_room_service._speaker_prompt_cache_partition("  ", "room-1") == ""



def test_chat_room_chat_agent_factory_disables_auto_delegation(monkeypatch):
    """Chat-surface runtimes must carry the stable-session prompt-goal flag.

    Without the flag, agent.py treats the raw speaker prompt as the effective
    goal and re-injects the whole prompt into RUNTIME_GOAL and MEMORY on every
    turn. The chat-room speaker path calls create_chat_agent directly, so the
    factory itself must mirror _create_chat_agent_for_session's behavior.
    """
    runtime_agent = SimpleNamespace()
    captured: dict = {}

    def fake_create_agent_runtime(**kwargs):
        captured.update(kwargs)
        return runtime_agent

    monkeypatch.setattr(session_service, "create_agent_runtime", fake_create_agent_runtime)

    created = session_service.create_chat_agent(
        workspace_path="workspace/speaker",
        config={"model": "qwen-max"},
    )

    assert created is runtime_agent
    assert captured == {
        "mode": "chat",
        "workspace_path": "workspace/speaker",
        "config": {"model": "qwen-max"},
        "runtime_agent_binding": None,
    }
    assert created._allow_session_subagent_auto_delegation is False

def test_speaker_payload_contains_each_message_exactly_once(tmp_path, monkeypatch):
    """Speaker LLM payload must not inject one message twice.

    The speaker turn seeds the session's full ledger replay as chat history;
    the prompt text must not re-embed that same session tail and only add
    room-round messages that are not in the speaker's ledger yet.
    """
    _isolate_chat_room_kernel(tmp_path, monkeypatch)
    session = session_service.create_chat_session(title="去重发言者")
    session_id = str(session.get("id") or "").strip()
    assert session_id
    room = chat_room_service.create_chat_room(
        title="去重群聊",
        participant_session_ids=[session_id],
    )
    participant = next(
        p for p in room["participants"] if str(p.get("sessionId") or "") == session_id
    )
    session_tail_user = "上一轮用户推进提示：收敛到唯一候选。"
    session_tail_assistant = "上一轮讲者结论：保留候选一并补充证据。"
    _append_session_ledger_message(
        tmp_path,
        session_id,
        {"role": "user", "content": session_tail_user},
        turn_id=f"{session_id}-tail-1",
    )
    _append_session_ledger_message(
        tmp_path,
        session_id,
        {"role": "assistant", "content": session_tail_assistant},
        turn_id=f"{session_id}-tail-2",
    )
    # Chat-state projection of the same session tail: before the dedup this
    # block duplicated the seeded ledger replay in the same payload.
    participant = {
        **participant,
        "recentMessages": [
            {"role": "user", "content": session_tail_user},
            {"role": "assistant", "content": session_tail_assistant},
        ],
    }
    room_message = "评审 Agent 本轮的独有房间发言。"
    prompt = chat_room_service._build_participant_prompt(
        room={"roomId": "room-dedup", "title": "去重群聊"},
        round_payload={"topic": "讨论去重", "mode": "round_robin", "purpose": "discussion"},
        participant=participant,
        prior_messages=[{"speakerTitle": "B002 · 评审 Agent", "content": room_message}],
    )

    captured: list[dict] = []

    def fake_runner(_agent, **kwargs):
        captured.append(dict(kwargs))
        return {"status": "completed", "raw_output": "ok", "summary": "ok"}

    monkeypatch.setattr(chat_room_service, "run_existing_agent_single_turn", fake_runner)
    result = chat_room_service._run_participant_agent(
        participant,
        prompt,
        {
            "roomId": str(room.get("roomId") or ""),
            "roundId": "round-dedup",
            "topic": "讨论去重",
            "purpose": "discussion",
        },
    )
    assert result["status"] == "completed"
    assert captured
    history_text = "\n".join(
        str(item.get("content") or "") for item in (captured[0].get("chat_history") or [])
    )
    # Ledger replay stays the only copy of the session tail.
    assert session_tail_user in history_text
    assert session_tail_assistant in history_text
    assert session_tail_user not in prompt
    assert session_tail_assistant not in prompt
    assert "你的会话近况" not in prompt
    # Room-round messages are unique to the prompt and appear exactly once.
    assert prompt.count(room_message) == 1
    # Whole-payload invariant: no session or room message content twice.
    combined_payload = f"{history_text}\n{prompt}"
    assert combined_payload.count(session_tail_user) == 1
    assert combined_payload.count(session_tail_assistant) == 1
    assert combined_payload.count(room_message) == 1



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


@pytest.mark.slow
def test_chat_room_participant_runs_with_active_direct_turn_in_another_session(tmp_path, monkeypatch):
    _isolate_chat_room_kernel(tmp_path, monkeypatch)
    _wait_for_lifecycle_phase, scheduler_events = _capture_session_lifecycle_events(monkeypatch)
    monkeypatch.setattr(session_service, "build_agent_context", _lightweight_agent_context)
    monkeypatch.setattr(chat_room_service, "build_agent_context", _lightweight_agent_context)
    monkeypatch.setattr(
        meeting_receipt_authority,
        "build_speaker_receipt_context",
        lambda *_args, **_kwargs: None,
    )
    llm_bindings = _install_chat_room_test_llm_config(monkeypatch)
    alpha = session_service.create_chat_session(title="Alpha Agent", llm_bindings=llm_bindings)
    gamma = session_service.create_chat_session(title="Gamma Agent", llm_bindings=llm_bindings)
    child = session_service.create_child_session(
        alpha["id"],
        user_request="候选实验会话",
        task_title="Alpha candidate session",
        auto_start=False,
    )
    child_session_id = child["childSessionId"]
    room = chat_room_service.create_chat_room(
        title="同 Agent 不同 Session 并行群聊",
        participant_session_ids=[child_session_id, gamma["id"]],
        config={
            "maxSpeakers": 1,
            "scopeAuthority": "workflow_discussion_scope.v1",
            "scopeHash": "scope-hash",
            "discussionScope": {
                "workflowRunId": "workflow-run",
                "nodeRunId": "node-run",
            },
        },
    )
    assert room["participants"][0]["agentId"] == alpha["agentId"]
    assert room["participants"][0]["sessionId"] == child_session_id
    receipt_authority = {
        "schemaVersion": 1,
        "authorityKind": "workflow_run",
        "teamId": "team-formal",
        "questionId": "SCI-002",
        "workflowRunId": "workflow-run",
        "workflowId": "challenge-cup-research",
        "workflowVersionId": "workflow-version",
        "modelPolicySha256": "a" * 64,
    }
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
            if "群聊也想让 alpha 发言" not in prompt and prompt.strip() == "alpha direct turn":
                direct_started.set()
                assert release_direct.wait(10.0)
                return {
                    "status": "completed",
                    "summary": "direct done",
                    "raw_output": "direct done",
                    "outcome": "done",
                    "tool_call_count": 0,
                    "tool_trace": [],
                }
            room_started.set()
            assert release_room.wait(10.0)
            return {
                "status": "completed",
                "summary": "room done",
                "raw_output": "room done",
                "tool_call_count": 0,
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda **kwargs: BlockingAgent())

    try:
        session_service.submit_session_message(alpha["id"], "alpha direct turn")
        assert direct_started.wait(10.0)

        result_holder: dict[str, dict] = {}
        room_thread = threading.Thread(
            target=lambda: result_holder.update(
                detail=chat_room_service.start_chat_room_round(
                    room["roomId"],
                    "群聊也想让 alpha 发言",
                    _model_invocation_receipt_authority=receipt_authority,
                )
            ),
            name="pytest-chat-room-round",
        )
        room_thread.start()

        assert room_started.wait(8.0), [("ids", alpha["id"], child_session_id), *[
            (
                event["session_id"],
                event["phase"],
                event["fields"].get("schedulerSessionKey"),
                event["fields"].get("queueReason"),
                event["fields"].get("reservationScope"),
            )
            for event in scheduler_events
            if "scheduler" in event["phase"]
        ]]
        assert not release_direct.is_set()
        release_room.set()
        release_direct.set()
        room_thread.join(timeout=2.0)
    finally:
        release_direct.set()
        release_room.set()
        executor.shutdown(wait=True, cancel_futures=True)

    assert not room_thread.is_alive()
    assert result_holder["detail"]["rounds"][-1]["status"] == "completed"
    assert prompts[0] == "alpha direct turn"
    assert "群聊也想让 alpha 发言" in prompts[1]


@pytest.mark.slow
def test_two_scoped_rooms_run_same_agent_in_distinct_sessions_concurrently(tmp_path, monkeypatch):
    _isolate_chat_room_kernel(tmp_path, monkeypatch)
    monkeypatch.setattr(session_service, "build_agent_context", _lightweight_agent_context)
    monkeypatch.setattr(chat_room_service, "build_agent_context", _lightweight_agent_context)
    monkeypatch.setattr(
        meeting_receipt_authority,
        "build_speaker_receipt_context",
        lambda *_args, **_kwargs: None,
    )
    llm_bindings = _install_chat_room_test_llm_config(monkeypatch)
    alpha = session_service.create_chat_session(title="Alpha Agent", llm_bindings=llm_bindings)
    gamma = session_service.create_chat_session(title="Gamma Agent", llm_bindings=llm_bindings)
    delta = session_service.create_chat_session(title="Delta Agent", llm_bindings=llm_bindings)
    first_child = session_service.create_child_session(
        alpha["id"],
        user_request="候选一评审",
        task_title="Alpha candidate one",
        auto_start=False,
    )["childSessionId"]
    second_child = session_service.create_child_session(
        alpha["id"],
        user_request="候选二评审",
        task_title="Alpha candidate two",
        auto_start=False,
    )["childSessionId"]

    def create_scoped_room(title, alpha_session_id, peer_session_id, scope_hash):
        return chat_room_service.create_chat_room(
            title=title,
            participant_session_ids=[alpha_session_id, peer_session_id],
            config={
                "maxSpeakers": 1,
                "scopeAuthority": "workflow_discussion_scope.v1",
                "scopeHash": scope_hash,
                "discussionScope": {
                    "workflowRunId": "workflow-run",
                    "nodeRunId": "node-run",
                },
            },
        )

    first_room = create_scoped_room("Candidate one", first_child, gamma["id"], "scope-one")
    second_room = create_scoped_room("Candidate two", second_child, delta["id"], "scope-two")
    assert first_room["participants"][0]["agentId"] == alpha["agentId"]
    assert second_room["participants"][0]["agentId"] == alpha["agentId"]
    assert first_child != second_child

    authority = {
        "schemaVersion": 1,
        "authorityKind": "workflow_run",
        "teamId": "team-formal",
        "questionId": "SCI-002",
        "workflowRunId": "workflow-run",
        "workflowId": "challenge-cup-research",
        "workflowVersionId": "workflow-version",
        "modelPolicySha256": "a" * 64,
    }
    entered_sessions: set[str] = set()
    entered_lock = threading.Lock()
    both_entered = threading.Event()
    release_calls = threading.Event()

    class BlockingAgent:
        def __init__(self, workspace_path=None, config=None):
            pass

        def seed_chat_history(self, messages):
            pass

        def seed_runtime_context(self, content):
            pass

        def run_single_turn(self, initial_prompt=None, disable_tools=False):
            active_session_id = str(
                agent_directory_service.current_agent_runtime().get("sessionId") or ""
            )
            with entered_lock:
                entered_sessions.add(active_session_id)
                if entered_sessions == {first_child, second_child}:
                    both_entered.set()
            assert release_calls.wait(10.0)
            return {
                "status": "completed",
                "summary": "room done",
                "raw_output": "room done",
                "tool_call_count": 0,
            }

    monkeypatch.setattr(session_service, "create_chat_agent", lambda **kwargs: BlockingAgent())
    results: dict[str, dict] = {}

    def run_room(key, room, topic):
        results[key] = chat_room_service.start_chat_room_round(
            room["roomId"],
            topic,
            _model_invocation_receipt_authority=authority,
        )

    first_thread = threading.Thread(target=run_room, args=("first", first_room, "candidate-one"))
    second_thread = threading.Thread(target=run_room, args=("second", second_room, "candidate-two"))
    try:
        first_thread.start()
        second_thread.start()
        assert both_entered.wait(10.0), entered_sessions
    finally:
        release_calls.set()
        first_thread.join(timeout=10.0)
        second_thread.join(timeout=10.0)

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert results["first"]["rounds"][-1]["status"] == "completed"
    assert results["second"]["rounds"][-1]["status"] == "completed"


@pytest.mark.slow
def test_chat_room_same_session_wait_does_not_block_later_different_session_turn(tmp_path, monkeypatch):
    _isolate_chat_room_kernel(tmp_path, monkeypatch)
    wait_for_lifecycle_phase, _events = _capture_session_lifecycle_events(monkeypatch)
    monkeypatch.setattr(session_service, "build_agent_context", _lightweight_agent_context)
    monkeypatch.setattr(chat_room_service, "build_agent_context", _lightweight_agent_context)
    llm_bindings = _install_chat_room_test_llm_config(monkeypatch)
    alpha = session_service.create_chat_session(title="Alpha Agent", llm_bindings=llm_bindings)
    beta = session_service.create_chat_session(title="Beta Agent", llm_bindings=llm_bindings)
    state = load_chat_state(tmp_path)
    for conversation in state["conversations"]:
        if conversation["conversation_id"] == beta["id"]:
            conversation["agent_id"] = alpha["agentId"]
            conversation["agentId"] = alpha["agentId"]
    save_chat_state(tmp_path, state)
    room = chat_room_service.create_chat_room(
        title="同 Agent FIFO 群聊",
        participant_agent_ids=[
            alpha["agentId"],
            session_service.create_chat_session(title="Gamma Agent", llm_bindings=llm_bindings)["agentId"],
        ],
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
            if "群聊排在第二个" in prompt:
                run_order.append("room")
                room_started.set()
                assert release_room.wait(10.0)
                run_order.append("room_finished")
                return {"status": "completed", "summary": "room done", "raw_output": "room done"}
            if "first direct" in prompt:
                run_order.append("first_direct")
                first_direct_started.set()
                assert release_first_direct.wait(10.0)
                return {
                    "status": "completed",
                    "summary": "first direct done",
                    "raw_output": "first direct done",
                    "outcome": "done",
                    "tool_call_count": 0,
                    "tool_trace": [],
                }
            if "room_finished" not in run_order:
                run_order.append("second_direct_started_before_room_finished")
            else:
                run_order.append("second_direct")
            second_direct_started.set()
            assert release_second_direct.wait(10.0)
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
        assert first_direct_started.wait(10.0)

        result_holder: dict[str, dict] = {}
        room_thread = threading.Thread(
            target=lambda: result_holder.update(
                detail=chat_room_service.start_chat_room_round(room["roomId"], "群聊排在第二个")
            ),
            name="pytest-chat-room-fifo-round",
        )
        room_thread.start()
        external_queued_event = wait_for_lifecycle_phase(
            "scheduler_external_queued",
            fields={"owner": "chat_room_round"},
        )
        assert external_queued_event is not None
        assert not room_started.is_set()

        second_direct = session_service.submit_session_message(beta["id"], "beta second direct")
        assert second_direct["currentPhase"] == "running"
        assert second_direct_started.wait(10.0)
        assert not room_started.is_set()
        release_second_direct.set()

        release_first_direct.set()
        assert room_started.wait(15.0)
        release_room.set()
        room_thread.join(timeout=2.0)
    finally:
        release_first_direct.set()
        release_room.set()
        release_second_direct.set()
        executor.shutdown(wait=True, cancel_futures=True)

    assert not room_thread.is_alive()
    assert result_holder["detail"]["rounds"][-1]["status"] == "completed"
    assert run_order == [
        "first_direct",
        "second_direct_started_before_room_finished",
        "room",
        "room_finished",
    ]


@pytest.mark.slow
def test_force_stop_chat_room_round_cancels_waiting_agent_slot(tmp_path, monkeypatch):
    _isolate_chat_room_kernel(tmp_path, monkeypatch)
    wait_for_lifecycle_phase, _events = _capture_session_lifecycle_events(monkeypatch)
    monkeypatch.setattr(session_service, "build_agent_context", _lightweight_agent_context)
    monkeypatch.setattr(chat_room_service, "build_agent_context", _lightweight_agent_context)
    llm_bindings = _install_chat_room_test_llm_config(monkeypatch)
    alpha = session_service.create_chat_session(title="Alpha Agent", llm_bindings=llm_bindings)
    beta = session_service.create_chat_session(title="Beta Agent", llm_bindings=llm_bindings)
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
            prompt = str(initial_prompt or "")
            if "等待 direct 后发言" in prompt or prompt.strip() != "alpha direct":
                room_started.set()
                return {"status": "completed", "summary": "room should not run", "raw_output": "room should not run"}
            direct_started.set()
            assert release_direct.wait(10.0)
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
        assert direct_started.wait(10.0)
        detail = chat_room_service.start_chat_room_round(room["roomId"], "等待 direct 后发言", background=True)
        round_id = detail["activeRoundId"]
        assert round_id
        queued_event = wait_for_lifecycle_phase(
            "scheduler_external_queued",
            fields={"owner": "chat_room_round"},
        )
        assert queued_event is not None
        assert not room_started.is_set()

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
    finally:
        release_direct.set()
        session_executor.shutdown(wait=True, cancel_futures=True)
        room_executor.shutdown(wait=True, cancel_futures=True)

    assert not room_started.is_set(), "stopped queued room speaker must not start after direct turn releases"
    final_detail = chat_room_service.get_chat_room_detail(room["roomId"])
    assert final_detail["status"] == "ready"
    assert final_detail["activeRoundId"] == ""
    assert final_detail["rounds"][-1]["status"] == "stopped"
    assert "pytest shutdown" in final_detail["rounds"][-1]["summary"]
    assert chat_room_service.load_chat_room_work_run_summary()["active"] is None


def test_chat_room_detail_reconciles_terminal_work_run_after_backend_restart(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(work_run_store, "WORK_RUNS_DIR", tmp_path / "work_runs")
    terminal_bridges = []
    monkeypatch.setattr(
        "core.web.services.team_workflow.meeting_runtime.finalize_stopped_meeting_after_chat_round",
        lambda room, round_payload: terminal_bridges.append(
            (dict(room), dict(round_payload))
        ),
    )

    room = chat_room_service.create_chat_room(
        title="重启后待收口群聊",
        participant_session_ids=["session-alpha", "session-beta"],
    )
    round_id = "round-restart-stopping"
    original_message = {
        "messageId": "message-before-restart",
        "participantId": "session-session-alpha",
        "speakerTitle": "Alpha Agent",
        "status": "completed",
        "content": "重启前已经完成的发言",
        "summary": "已完成发言",
        "timestamp": "2026-07-10T02:35:00+00:00",
    }
    state = chat_room_service._store().load()
    stored_room = next(item for item in state["rooms"] if item["roomId"] == room["roomId"])
    stored_room["status"] = "stopping"
    stored_room["activeRoundId"] = round_id
    stored_room["rounds"] = [
        {
            "roundId": round_id,
            "roomId": room["roomId"],
            "topic": "probe topic",
            "mode": "round_robin",
            "purpose": "discussion",
            "config": {},
            "status": "stopping",
            "speakerOrder": ["session-session-alpha", "session-session-beta"],
            "messages": [original_message],
            "summary": "正在停止当前群聊轮次，等待正在发言的 Agent 收尾。",
            "startedAt": "2026-07-10T02:30:52+00:00",
            "updatedAt": "2026-07-10T02:49:48+00:00",
            "finishedAt": "",
        }
    ]
    chat_room_service._store().save(state)
    chat_room_service._work_run_store().persist_snapshot(
        chat_room_service.RUN_KIND,
        {
            "runId": round_id,
            "runKind": chat_room_service.RUN_KIND,
            "roomId": room["roomId"],
            "roundId": round_id,
            "status": "stopped",
            "currentPhase": "stopped",
            "runtimeStatus": "force_stopped",
            "forceStopReason": "pytest launcher force stop",
            "summary": "Launcher force-stopped the stale chat room round.",
            "startedAt": "2026-07-10T02:30:52+00:00",
            "updatedAt": "2026-07-10T07:44:40+00:00",
            "finishedAt": "2026-07-10T07:44:40+00:00",
        },
        active_run_id="",
    )

    detail = chat_room_service.get_chat_room_detail(room["roomId"])

    assert detail is not None
    assert detail["status"] == "ready"
    assert detail["activeRoundId"] == ""
    reconciled_round = detail["rounds"][-1]
    assert reconciled_round["status"] == "stopped"
    assert reconciled_round["finishedAt"] == "2026-07-10T07:44:40+00:00"
    assert reconciled_round["messages"][0]["messageId"] == original_message["messageId"]
    assert reconciled_round["messages"][0]["content"] == original_message["content"]
    stored_detail = chat_room_service._store().load()["rooms"][0]
    assert stored_detail["rounds"][-1]["messages"] == [original_message]
    assert "pytest launcher force stop" in reconciled_round["summary"]
    assert reconciled_round["terminalReason"] == "pytest launcher force stop"
    assert len(terminal_bridges) == 1
    assert terminal_bridges[0][1]["terminalReason"] == "pytest launcher force stop"
    assert chat_room_service.list_active_chat_room_work_runs() == []


def test_chat_room_work_run_summary_closes_active_snapshot_when_room_is_missing(tmp_path, monkeypatch):
    """A deleted room must not leave a running WorkRun blocking lifecycle actions."""

    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(work_run_store, "WORK_RUNS_DIR", tmp_path / "work_runs")
    monkeypatch.setattr(chat_room_service, "utc_now_iso", lambda: "2026-08-11T02:20:00Z")
    round_id = "round-missing-room-index"
    store = chat_room_service._work_run_store()
    store.persist_snapshot(
        chat_room_service.RUN_KIND,
        {
            "runId": round_id,
            "runKind": chat_room_service.RUN_KIND,
            "roomId": "room-deleted-before-restart",
            "roundId": round_id,
            "status": "running",
            "currentPhase": "running",
            "runtimeStatus": "running",
            "summary": "The old room is no longer present.",
            "startedAt": "2026-08-10T17:14:11Z",
            "updatedAt": "2026-08-10T17:14:11Z",
            "finishedAt": "",
        },
        active_run_id=round_id,
    )

    summary = chat_room_service.load_chat_room_work_run_summary()

    assert summary["active"] is None
    assert summary["activeItems"] == []
    assert summary["latest"]["runId"] == round_id
    assert summary["latest"]["status"] == "stopped"
    assert summary["latest"]["runtimeStatus"] == "orphaned_room_reconciled"
    assert summary["latest"]["reconciliationSource"] == "missing_room_record"
    assert store.load_run_index(chat_room_service.RUN_KIND)["activeRunId"] == ""


@pytest.mark.parametrize(
    ("work_status", "expected_round_status", "expected_room_status"),
    [
        ("completed", "completed", "ready"),
        ("partial", "partial", "ready"),
        ("closed", "stopped", "ready"),
        ("stop_failed", "failed", "failed"),
    ],
)
def test_chat_room_detail_maps_terminal_work_run_status(
    tmp_path,
    monkeypatch,
    work_status,
    expected_round_status,
    expected_room_status,
):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(work_run_store, "WORK_RUNS_DIR", tmp_path / "work_runs")
    room = chat_room_service.create_chat_room(
        title=f"{work_status} 终态对账",
        participant_session_ids=["session-alpha"],
    )
    round_id = f"round-terminal-{work_status}"
    state = chat_room_service._store().load()
    stored_room = next(item for item in state["rooms"] if item["roomId"] == room["roomId"])
    stored_room["status"] = "stopping"
    stored_room["activeRoundId"] = round_id
    stored_room["rounds"] = [
        {
            "roundId": round_id,
            "roomId": room["roomId"],
            "topic": "terminal result",
            "mode": "round_robin",
            "purpose": "discussion",
            "config": {},
            "status": "stopping",
            "speakerOrder": ["session-session-alpha"],
            "messages": [],
            "summary": "旧的停止中摘要",
            "startedAt": "2026-07-10T02:30:52+00:00",
            "updatedAt": "2026-07-10T02:49:48+00:00",
            "finishedAt": "",
        }
    ]
    chat_room_service._store().save(state)
    expected_summary = f"pytest {work_status} terminal summary"
    chat_room_service._work_run_store().persist_snapshot(
        chat_room_service.RUN_KIND,
        {
            "runId": round_id,
            "runKind": chat_room_service.RUN_KIND,
            "roomId": room["roomId"],
            "roundId": round_id,
            "status": work_status,
            "currentPhase": work_status,
            "summary": expected_summary,
            "startedAt": "2026-07-10T02:30:52+00:00",
            "updatedAt": "2026-07-10T07:44:40+00:00",
            "finishedAt": "2026-07-10T07:44:40+00:00",
        },
        active_run_id="",
    )

    detail = chat_room_service.get_chat_room_detail(room["roomId"])

    assert detail is not None
    assert detail["status"] == expected_room_status
    assert detail["activeRoundId"] == ""
    assert detail["rounds"][-1]["status"] == expected_round_status
    assert expected_summary in detail["rounds"][-1]["summary"]


def test_active_chat_room_list_reconciles_round_without_process_controller(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(work_run_store, "WORK_RUNS_DIR", tmp_path / "work_runs")

    room = chat_room_service.create_chat_room(
        title="后端重启后遗留群聊",
        participant_session_ids=["session-alpha", "session-beta"],
    )
    round_id = "round-orphaned-after-restart"
    state = chat_room_service._store().load()
    stored_room = next(item for item in state["rooms"] if item["roomId"] == room["roomId"])
    stored_room["status"] = "stopping"
    stored_room["activeRoundId"] = round_id
    stored_room["rounds"] = [
        {
            "roundId": round_id,
            "roomId": room["roomId"],
            "topic": "orphan topic",
            "mode": "round_robin",
            "purpose": "discussion",
            "config": {},
            "status": "stopping",
            "speakerOrder": ["session-session-alpha", "session-session-beta"],
            "messages": [],
            "summary": "正在停止当前群聊轮次，等待正在发言的 Agent 收尾。",
            "startedAt": "2026-07-10T02:30:52+00:00",
            "updatedAt": "2026-07-10T02:49:48+00:00",
            "finishedAt": "",
        }
    ]
    chat_room_service._store().save(state)
    chat_room_service._work_run_store().persist_snapshot(
        chat_room_service.RUN_KIND,
        {
            "runId": round_id,
            "runKind": chat_room_service.RUN_KIND,
            "roomId": room["roomId"],
            "roundId": round_id,
            "status": "stopping",
            "currentPhase": "stopping",
            "summary": "Waiting for the current speaker to finish.",
            "startedAt": "2026-07-10T02:30:52+00:00",
            "updatedAt": "2026-07-10T02:49:48+00:00",
            "finishedAt": "",
        },
        active_run_id=round_id,
    )
    monkeypatch.setattr(chat_room_service, "utc_now_iso", lambda: "2026-07-10T08:00:00+00:00")

    active_runs = chat_room_service.list_active_chat_room_work_runs()

    assert active_runs == []
    detail = chat_room_service.get_chat_room_detail(room["roomId"])
    assert detail is not None
    assert detail["status"] == "ready"
    assert detail["activeRoundId"] == ""
    assert detail["rounds"][-1]["status"] == "stopped"
    assert detail["rounds"][-1]["finishedAt"] == "2026-07-10T08:00:00+00:00"
    assert "后端进程已重启" in detail["rounds"][-1]["summary"]
    run_summary = chat_room_service.load_chat_room_work_run_summary()
    assert run_summary["active"] is None
    assert run_summary["latest"]["status"] == "stopped"


@pytest.mark.parametrize(
    "reader_name",
    ["full", "conversation_index", "compact"],
)
def test_chat_room_list_surfaces_reconcile_orphaned_rounds(tmp_path, monkeypatch, reader_name):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(work_run_store, "WORK_RUNS_DIR", tmp_path / "work_runs")

    room = chat_room_service.create_chat_room(
        title=f"{reader_name} 遗留群聊",
        participant_session_ids=["session-alpha", "session-beta"],
    )
    round_id = f"round-orphaned-{reader_name}"
    state = chat_room_service._store().load()
    stored_room = next(item for item in state["rooms"] if item["roomId"] == room["roomId"])
    stored_room["status"] = "stopping"
    stored_room["activeRoundId"] = round_id
    stored_room["rounds"] = [
        {
            "roundId": round_id,
            "roomId": room["roomId"],
            "topic": "orphan list topic",
            "mode": "round_robin",
            "purpose": "discussion",
            "config": {},
            "status": "stopping",
            "speakerOrder": ["session-session-alpha", "session-session-beta"],
            "messages": [],
            "summary": "正在停止当前群聊轮次。",
            "startedAt": "2026-07-10T02:30:52+00:00",
            "updatedAt": "2026-07-10T02:49:48+00:00",
            "finishedAt": "",
        }
    ]
    chat_room_service._store().save(state)
    chat_room_service._work_run_store().persist_snapshot(
        chat_room_service.RUN_KIND,
        {
            "runId": round_id,
            "runKind": chat_room_service.RUN_KIND,
            "roomId": room["roomId"],
            "roundId": round_id,
            "status": "stopping",
            "currentPhase": "stopping",
            "startedAt": "2026-07-10T02:30:52+00:00",
            "updatedAt": "2026-07-10T02:49:48+00:00",
            "finishedAt": "",
        },
        active_run_id=round_id,
    )

    if reader_name == "full":
        chat_room_service.list_chat_rooms()
    elif reader_name == "conversation_index":
        chat_room_service.list_chat_rooms_for_conversation_index()
    else:
        chat_room_service.list_chat_rooms_compact()

    reconciled_room = chat_room_service._store().load()["rooms"][0]
    assert reconciled_room["status"] == "ready"
    assert reconciled_room["activeRoundId"] == ""
    assert reconciled_room["rounds"][-1]["status"] == "stopped"


def test_chat_room_round_registers_process_control_before_active_work_run_persist(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(work_run_store, "WORK_RUNS_DIR", tmp_path / "work_runs")
    room = chat_room_service.create_chat_room(
        title="启动顺序群聊",
        participant_session_ids=["session-alpha"],
    )
    observed_process_control: dict[str, bool] = {}
    real_persist = chat_room_service._persist_chat_room_work_run

    def observe_persist(room_payload, round_payload, *, status, summary):
        observed_process_control.setdefault(
            status,
            chat_room_service._chat_room_round_has_process_control(round_payload["roundId"]),
        )
        return real_persist(room_payload, round_payload, status=status, summary=summary)

    monkeypatch.setattr(chat_room_service, "_persist_chat_room_work_run", observe_persist)

    chat_room_service.start_chat_room_round(
        room["roomId"],
        "验证控制器注册顺序",
        agent_runner=lambda *_args: {"status": "completed", "raw_output": "done", "summary": "done"},
    )

    assert observed_process_control["running"] is True


def test_nested_compact_room_read_defers_orphan_reconciliation_until_outer_lock_releases(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(work_run_store, "WORK_RUNS_DIR", tmp_path / "work_runs")
    stale_room = chat_room_service.create_chat_room(
        title="待外层事务结束再收口",
        participant_session_ids=["session-alpha"],
    )
    round_id = "round-nested-read-orphan"
    state = chat_room_service._store().load()
    stored_room = next(item for item in state["rooms"] if item["roomId"] == stale_room["roomId"])
    stored_room["status"] = "stopping"
    stored_room["activeRoundId"] = round_id
    stored_room["rounds"] = [
        {
            "roundId": round_id,
            "roomId": stale_room["roomId"],
            "topic": "nested read",
            "mode": "round_robin",
            "purpose": "discussion",
            "config": {},
            "status": "stopping",
            "speakerOrder": ["session-session-alpha"],
            "messages": [],
            "summary": "正在停止当前群聊轮次。",
            "startedAt": "2026-07-10T02:30:52+00:00",
            "updatedAt": "2026-07-10T02:49:48+00:00",
            "finishedAt": "",
        }
    ]
    chat_room_service._store().save(state)
    chat_room_service._work_run_store().persist_snapshot(
        chat_room_service.RUN_KIND,
        {
            "runId": round_id,
            "runKind": chat_room_service.RUN_KIND,
            "roomId": stale_room["roomId"],
            "roundId": round_id,
            "status": "stopping",
            "currentPhase": "stopping",
            "startedAt": "2026-07-10T02:30:52+00:00",
            "updatedAt": "2026-07-10T02:49:48+00:00",
            "finishedAt": "",
        },
        active_run_id=round_id,
    )
    recorded_events = []
    monkeypatch.setattr(
        chat_room_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )

    with chat_room_service._CHAT_ROOM_LOCK:
        outer_state = chat_room_service._store().load()
        chat_room_service.list_chat_rooms_compact()
        chat_room_service._store().save(outer_state)

    reconciliation_events = [
        item for item in recorded_events if item[0][:3] == ("chat_room", "round", "chat_room.round.orphan_reconciled")
    ]
    assert reconciliation_events == []
    still_stale = next(
        item for item in chat_room_service._store().load()["rooms"] if item["roomId"] == stale_room["roomId"]
    )
    assert still_stale["status"] == "stopping"

    chat_room_service.list_chat_rooms_compact()

    reconciliation_events = [
        item for item in recorded_events if item[0][:3] == ("chat_room", "round", "chat_room.round.orphan_reconciled")
    ]
    assert len(reconciliation_events) == 1
    reconciled = next(
        item for item in chat_room_service._store().load()["rooms"] if item["roomId"] == stale_room["roomId"]
    )
    assert reconciled["status"] == "ready"


@pytest.mark.slow
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
        assert release_runner.wait(10.0)
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


def test_stopped_round_still_syncs_completed_messages_to_participant_sessions(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    room = chat_room_service.create_chat_room(
        title="停止同步群聊",
        participant_session_ids=["session-alpha", "session-beta"],
    )

    second_speaker_started = threading.Event()
    release_runner = threading.Event()

    def staged_runner(participant, prompt, context):
        # Speaker one completes and is persisted; speaker two blocks so the
        # stop lands between turns with one completed message already stored.
        if participant.get("sessionId") != "session-beta":
            return {"status": "completed", "raw_output": "停止前的发言", "summary": "ok"}
        second_speaker_started.set()
        assert release_runner.wait(10.0)
        return {"status": "completed", "raw_output": "迟到的发言", "summary": "late"}

    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pytest-chat-room-stop-sync")
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_EXECUTOR", executor)

    try:
        started = chat_room_service.start_chat_room_round(
            room["roomId"],
            "停止后仍要同步的讨论",
            agent_runner=staged_runner,
            background=True,
        )
        assert second_speaker_started.wait(1.0)
        chat_room_service.stop_chat_room_round(room["roomId"], reason="pytest stop sync")
    finally:
        release_runner.set()
        executor.shutdown(wait=True, cancel_futures=True)

    detail = chat_room_service.get_chat_room_detail(room["roomId"])
    assert detail["rounds"][-1]["status"] == "stopped"
    for session_id in ("session-alpha", "session-beta"):
        events = load_conversation_events(tmp_path, session_id)
        synced = [
            event
            for event in events
            if event.source == "chat_room_round_sync"
            and started["activeRoundId"] in event.event_id
        ]
        assert synced, f"stopped round transcript missing in {session_id}"


def test_start_chat_room_round_rejects_when_inflight_cap_reached(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    room = chat_room_service.create_chat_room(title="背压群聊", participant_session_ids=["session-alpha"])
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_MAX_INFLIGHT_ROUNDS", 1)
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_INFLIGHT_COUNT", 1)

    try:
        chat_room_service.start_chat_room_round(
            room["roomId"],
            "应该被背压拒绝的讨论",
            agent_runner=lambda participant, prompt, context: {"status": "completed", "raw_output": "ok", "summary": "ok"},
            background=True,
        )
    except chat_room_service.ChatRoomBusyError as exc:
        assert "任务较多" in str(exc)
    else:
        raise AssertionError("inflight cap should reject the new background round")

    # The rejection must leave the room clean: no round created, no active id.
    detail = chat_room_service.get_chat_room_detail(room["roomId"])
    assert detail["activeRoundId"] == ""
    assert detail["rounds"] == []


def test_room_to_api_truncates_history_round_messages_only(tmp_path, monkeypatch):
    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    room = chat_room_service.create_chat_room(title="截断群聊", participant_session_ids=["session-alpha"])
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_API_HISTORY_MESSAGE_LIMIT", 2)

    def _round(round_id, message_count, status):
        return {
            "roundId": round_id,
            "roomId": room["roomId"],
            "topic": f"topic-{round_id}",
            "mode": "round_robin",
            "purpose": "discussion",
            "status": status,
            "speakerOrder": [],
            "messages": [
                {
                    "messageId": f"{round_id}-msg-{index}",
                    "participantId": "participant-1",
                    "sessionId": "session-alpha",
                    "status": "completed",
                    "content": f"消息 {index}",
                    "timestamp": f"2026-08-21T00:00:{index:02d}Z",
                }
                for index in range(message_count)
            ],
            "summary": "",
            "startedAt": "2026-08-21T00:00:00Z",
            "updatedAt": "2026-08-21T00:00:30Z",
            "finishedAt": "2026-08-21T00:00:30Z",
        }

    state = chat_room_service._store().load()
    stored_room = next(item for item in state["rooms"] if item["roomId"] == room["roomId"])
    stored_room["rounds"] = [_round("round-old", 3, "completed"), _round("round-new", 1, "completed")]
    chat_room_service._store().save(state)

    detail = chat_room_service.get_chat_room_detail(room["roomId"])
    old_round, new_round = detail["rounds"]
    assert old_round["roundId"] == "round-old"
    assert len(old_round["messages"]) == 2
    assert old_round["messagesTruncated"] is True
    assert old_round["messagesTotalCount"] == 3
    assert old_round["messages"][-1]["messageId"] == "round-old-msg-2"
    assert new_round["roundId"] == "round-new"
    assert len(new_round["messages"]) == 1
    assert "messagesTruncated" not in new_round


def test_stop_chat_room_round_survives_contended_session_transaction(tmp_path, monkeypatch):
    """Regression for the py-spy lock-order deadlock.

    The stop finalizer (session sync via the chat-state transaction) used to
    run while the round runner still held ``_CHAT_ROOM_LOCK``.  With the
    session transaction contended, stop, room detail and round persistence all
    froze.  The finalizer must release the room lock before touching the
    session state lock, so stop stays responsive and room state stays readable
    while the sync is parked.
    """

    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    room = chat_room_service.create_chat_room(
        title="停止不被会话事务冻死",
        participant_session_ids=["session-alpha"],
    )
    room_id = room["roomId"]

    state_hold_seconds = 3.0
    finalizer_entered_state_lock = threading.Event()
    release_state_lock = threading.Event()
    runner_can_return = threading.Event()
    runner_entered_speaker = threading.Event()
    real_state_lock = session_service._CHAT_STATE_LOCK

    class ContendedStateLock:
        def __enter__(self):
            if finalizer_entered_state_lock.is_set():
                return real_state_lock.__enter__()
            # Lock order contract: the chat room lock must already be released
            # when the stop finalizer enters the session state lock.
            assert not chat_room_service._chat_room_lock_owned_by_current_thread()
            finalizer_entered_state_lock.set()
            assert release_state_lock.wait(timeout=state_hold_seconds)
            return real_state_lock.__enter__()

        def __exit__(self, exc_type, exc_value, traceback):
            return real_state_lock.__exit__(exc_type, exc_value, traceback)

    monkeypatch.setattr(session_service, "_CHAT_STATE_LOCK", ContendedStateLock())

    def runner_requests_stop_then_completes(participant, prompt, context):
        # Park inside the speaker call so the stop below lands mid-round, then
        # request the stop exactly like the production stop flow does before
        # the runner's persist branch sees the stop reason.
        runner_entered_speaker.set()
        assert runner_can_return.wait(timeout=5)
        chat_room_service._request_chat_room_round_stop(context["roundId"], "pytest lock-order stop")
        return {
            "status": "completed",
            "raw_output": f"{participant['title']} 发言",
            "summary": "ok",
        }

    def cancel_must_not_run_under_room_lock(run_id):
        assert not chat_room_service._chat_room_lock_owned_by_current_thread()
        return True

    monkeypatch.setattr(
        session_service,
        "cancel_agent_execution_reservation",
        cancel_must_not_run_under_room_lock,
    )

    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pytest-chat-room-round-runner")
    future = executor.submit(
        chat_room_service.start_chat_room_round,
        room_id,
        "停止收尾必须放锁后再同步会话",
        agent_runner=runner_requests_stop_then_completes,
    )
    try:
        # Wait until the runner is parked inside the speaker call (past the
        # round loop's stop check) so the stop below lands mid-round.
        assert runner_entered_speaker.wait(timeout=5)
        detail = chat_room_service.stop_chat_room_round(room_id, reason="pytest lock-order stop")
        assert detail["status"] == "stopping"
        # The stopping state is durable while the round runner is still parked.
        stored = chat_room_service._store().load()
        stored_room = next(item for item in stored["rooms"] if item["roomId"] == room_id)
        assert stored_room["status"] == "stopping"
        assert stored_room["rounds"][-1]["status"] == "stopping"

        runner_can_return.set()
        # The finalizer parks on the contended session transaction; room reads
        # must stay responsive instead of freezing behind the room lock.  The
        # bounded executor keeps the test failing fast (instead of hanging) if
        # the room lock is ever held across the session sync again.
        probe_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pytest-chat-room-lock-probe")
        try:
            assert finalizer_entered_state_lock.wait(timeout=5)
            detail_future = probe_executor.submit(chat_room_service.get_chat_room_detail, room_id)
            detail_while_parked = detail_future.result(timeout=2)
            assert detail_while_parked is not None
            busy_stop_future = probe_executor.submit(
                chat_room_service.stop_chat_room_round, room_id, reason="pytest duplicate stop"
            )
            with pytest.raises(chat_room_service.ChatRoomBusyError):
                busy_stop_future.result(timeout=2)
        finally:
            probe_executor.shutdown(wait=False)
    finally:
        runner_can_return.set()
        release_state_lock.set()
        detail = future.result(timeout=10)
        executor.shutdown(wait=True)

    assert detail["status"] == "ready"
    latest_round = detail["rounds"][-1]
    assert latest_round["status"] == "stopped"
    # The stop finalization still syncs the completed speaker transcript into
    # participant sessions; it just does so outside the room lock.
    assert _has_room_transcript(tmp_path, "session-alpha", room_id)


def test_stop_and_round_persist_stress_does_not_deadlock(tmp_path, monkeypatch):
    """Concurrent round persistence + stop must always make progress."""

    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)

    for iteration in range(3):
        room = chat_room_service.create_chat_room(
            title=f"压力迭代 {iteration}",
            participant_session_ids=["session-alpha", "session-beta"],
        )
        room_id = room["roomId"]
        stop_fired = threading.Event()
        speaker_entered = threading.Event()

        def slow_runner(participant, prompt, context):
            # Keep the persist/stop race window open for every speaker.
            speaker_entered.set()
            assert stop_fired.wait(timeout=5)
            time.sleep(0.05)
            return {
                "status": "completed",
                "raw_output": f"{participant['title']} 发言",
                "summary": "ok",
            }

        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"pytest-chat-room-stress-{iteration}")
        stop_executor = None
        future = executor.submit(
            chat_room_service.start_chat_room_round,
            room_id,
            f"压力并发 {iteration}",
            agent_runner=slow_runner,
        )
        try:
            # The runner parks inside the first speaker; stop then races the
            # round's persist/finalize path from another thread.
            assert speaker_entered.wait(timeout=5)
            stop_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"pytest-chat-room-stopper-{iteration}")
            stop_future = stop_executor.submit(chat_room_service.stop_chat_room_round, room_id, reason=f"pytest stress stop {iteration}")
            stop_future.result(timeout=5)
            stop_fired.set()
            # Detail reads must stay fast while stop/persist run concurrently.
            detail_started_at = time.perf_counter()
            detail = chat_room_service.get_chat_room_detail(room_id)
            assert time.perf_counter() - detail_started_at < 1.0
            assert detail is not None
        finally:
            stop_fired.set()
            detail = future.result(timeout=10)
            executor.shutdown(wait=True)
            if stop_executor is not None:
                stop_executor.shutdown(wait=True)

        latest_round = detail["rounds"][-1]
        assert latest_round["status"] in {"stopped", "completed", "partial"}
        assert detail["status"] in {"ready", "failed"}


def test_participant_resolution_runs_outside_room_lock(tmp_path, monkeypatch):
    """Lock order contract: create/update resolve participants before locking."""

    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    room = chat_room_service.create_chat_room(
        title="锁外解析成员",
        participant_session_ids=["session-alpha"],
    )

    real_resolve = chat_room_service._resolve_participants

    def resolve_must_not_hold_room_lock(session_ids):
        assert not chat_room_service._chat_room_lock_owned_by_current_thread()
        return real_resolve(session_ids)

    monkeypatch.setattr(chat_room_service, "_resolve_participants", resolve_must_not_hold_room_lock)

    updated = chat_room_service.update_chat_room(
        room["roomId"],
        participant_session_ids=["session-beta"],
    )
    assert [item["sessionId"] for item in updated["participants"]] == ["session-beta"]


def test_read_paths_skip_reconcile_and_return_while_room_lock_is_held(tmp_path, monkeypatch):
    """Acceptance: reads stay bounded while _CHAT_ROOM_LOCK is hijacked.

    list_chat_rooms_compact feeds /api/teams, /conversations and
    runtime-summary reads.  With the per-read reconcile gate in its
    steady state, a read must not queue on _CHAT_ROOM_LOCK at all.
    """

    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    chat_room_service.create_chat_room(
        title="读路径不穿大锁",
        participant_session_ids=["session-alpha"],
    )

    reconcile_calls = []
    real_reconcile = chat_room_service._reconcile_chat_room_round_state_locked_gate

    def counting_reconcile():
        reconcile_calls.append(True)
        return real_reconcile()

    monkeypatch.setattr(
        chat_room_service,
        "_reconcile_chat_room_round_state_locked_gate",
        counting_reconcile,
    )
    # Reset the gate to its cold state: room creation already consumed the
    # process's first reconcile pass via its detail publish.
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_RECONCILE_LAST_RUN_AT", None)
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_RECONCILE_INFLIGHT", False)
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_RECONCILE_LAST_STORE_TOKEN", None)

    # First read runs the reconcile pass once (cold gate).
    rooms = chat_room_service.list_chat_rooms_compact()
    assert len(rooms) == 1
    assert reconcile_calls

    # Steady state: same store revision and inside the TTL -> no more passes.
    reconcile_calls.clear()
    rooms = chat_room_service.list_chat_rooms_compact()
    assert len(rooms) == 1
    assert not reconcile_calls

    # Even while the room lock is held forever, the steady-state read returns.
    assert chat_room_service._CHAT_ROOM_LOCK.acquire(timeout=1)
    try:
        probe_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pytest-chat-room-read-probe")
        try:
            read_future = probe_executor.submit(chat_room_service.list_chat_rooms_compact)
            started_at = time.perf_counter()
            rooms = read_future.result(timeout=2)
            assert time.perf_counter() - started_at < 1.5
            assert len(rooms) == 1
        finally:
            probe_executor.shutdown(wait=False)
    finally:
        chat_room_service._CHAT_ROOM_LOCK.release()


def test_reconcile_gate_reruns_after_store_change_or_inflight_release(tmp_path, monkeypatch):
    """The reconcile gate must rerun on store changes, not stick shut.

    The gate primitives are asserted directly: background session machinery
    can trigger reconciles concurrently, so counting wrapper invocations would
    be nondeterministic.
    """

    _seed_chat_sessions(tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    chat_room_service.create_chat_room(
        title="去抖门可重开",
        participant_session_ids=["session-alpha"],
    )
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_RECONCILE_LAST_RUN_AT", None)
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_RECONCILE_INFLIGHT", False)
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_RECONCILE_LAST_STORE_TOKEN", None)

    # Cold gate: a run is granted and released.
    assert chat_room_service._acquire_chat_room_reconcile_run() is True
    chat_room_service._release_chat_room_reconcile_run()
    # Unchanged store + inside TTL: skipped.
    assert chat_room_service._acquire_chat_room_reconcile_run() is False
    # An inflight marker blocks a rerun even on a cold timestamp.
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_RECONCILE_LAST_RUN_AT", None)
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_RECONCILE_INFLIGHT", True)
    assert chat_room_service._acquire_chat_room_reconcile_run() is False
    monkeypatch.setattr(chat_room_service, "_CHAT_ROOM_RECONCILE_INFLIGHT", False)
    assert chat_room_service._acquire_chat_room_reconcile_run() is True
    chat_room_service._release_chat_room_reconcile_run()
    # A store write (mtime change) reopens the gate.
    state = chat_room_service._store().load()
    chat_room_service._store().save(state)
    assert chat_room_service._acquire_chat_room_reconcile_run() is True
    chat_room_service._release_chat_room_reconcile_run()
    assert next(item for item in state["rooms"] if item["roomId"]) is not None
