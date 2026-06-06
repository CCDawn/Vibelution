from core.web.services import agent_directory_service, project_agent_bus_service, session_service


def _use_tmp_project_root(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(project_agent_bus_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)


def test_project_agent_bus_observe_message_only_writes_timeline(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    monkeypatch.setattr(project_agent_bus_service.session_service, "wake_agent_for_inbox_message", lambda message: {})

    event = project_agent_bus_service.send_project_agent_bus_message(
        content="只是总群观察，不投递",
        target_scope="observe",
    )

    assert event["messageType"] == "project_observation"
    assert event["targetAgentIds"] == []
    assert event["deliveries"] == []
    assert project_agent_bus_service.list_project_agent_bus_events()["events"][-1]["eventId"] == event["eventId"]
    assert agent_directory_service.list_agent_inbox_messages_for_agent(alpha["agentId"]) == []


def test_project_agent_bus_plain_message_defaults_to_all_active_agents(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    beta = agent_directory_service.create_agent_instance(display_name="Beta", direct_session_id="session-beta")
    monkeypatch.setattr(
        project_agent_bus_service.session_service,
        "wake_agent_for_inbox_message",
        lambda message: {
            "wakeRequested": True,
            "wakeStatus": "started",
            "messageId": message["messageId"],
            "targetAgentId": message["targetAgentId"],
            "targetSessionId": message["targetSessionId"],
            "turnId": "turn-default-all",
            "reason": "",
        },
    )

    event = project_agent_bus_service.send_project_agent_bus_message(content="普通总群消息也要投递")

    assert event["messageType"] == "user_guidance"
    assert event["targetScope"] == "all"
    assert {alpha["agentId"], beta["agentId"]}.issubset(set(event["targetAgentIds"]))
    assert len(event["deliveries"]) == len(event["targetAgentIds"])
    assert all(item["status"] == "delivered" for item in event["deliveries"])


def test_project_agent_bus_all_mention_delivers_to_active_agents_only(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    beta = agent_directory_service.create_agent_instance(display_name="Beta", direct_session_id="session-beta")
    archived = agent_directory_service.create_agent_instance(display_name="Archived", direct_session_id="session-archived")
    agent_directory_service.archive_agent_instance(archived["agentId"])
    wake_calls = []
    monkeypatch.setattr(
        project_agent_bus_service.session_service,
        "wake_agent_for_inbox_message",
        lambda message: wake_calls.append(message) or {
            "wakeRequested": True,
            "wakeStatus": "started",
            "messageId": message["messageId"],
            "targetAgentId": message["targetAgentId"],
            "targetSessionId": message["targetSessionId"],
            "turnId": "turn-1",
            "reason": "",
        },
    )

    event = project_agent_bus_service.send_project_agent_bus_message(content="@全体成员 请同步当前判断")

    assert event["targetScope"] == "all"
    assert {alpha["agentId"], beta["agentId"]}.issubset(set(event["targetAgentIds"]))
    assert archived["agentId"] not in event["targetAgentIds"]
    assert len(event["deliveries"]) == len(event["targetAgentIds"])
    assert all(item["status"] == "delivered" for item in event["deliveries"])
    assert len(wake_calls) == len(event["targetAgentIds"])
    assert agent_directory_service.count_agent_inbox_messages_for_agent(alpha["agentId"]) == 1
    assert agent_directory_service.count_agent_inbox_messages_for_agent(beta["agentId"]) == 1
    assert agent_directory_service.count_agent_inbox_messages_for_agent(archived["agentId"]) == 0


def test_project_agent_bus_named_mention_targets_one_agent_without_wake(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    beta = agent_directory_service.create_agent_instance(display_name="Beta", direct_session_id="session-beta")

    event = project_agent_bus_service.send_project_agent_bus_message(
        content=f"@{alpha['agentCode']} 先看接口边界",
        wake_target=False,
    )

    assert event["targetScope"] == "agents"
    assert event["targetAgentIds"] == [alpha["agentId"]]
    assert event["deliveries"][0]["wake"]["wakeStatus"] == "not_requested"
    assert agent_directory_service.count_agent_inbox_messages_for_agent(alpha["agentId"]) == 1
    assert agent_directory_service.count_agent_inbox_messages_for_agent(beta["agentId"]) == 0


def test_project_agent_bus_named_mention_does_not_match_legacy_profile_id(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent_directory_service.create_agent_instance(
        display_name="Research Broad",
        llm_bindings={"dialogue": {"modelId": "research-broad-model"}},
        direct_session_id="session-research-broad",
    )

    event = project_agent_bus_service.send_project_agent_bus_message(
        content="@research_broad 这不应该再按旧 profile 命中",
        wake_target=False,
    )

    assert event["targetScope"] == "agents"
    assert event["targetAgentIds"] == []
    assert event["unresolvedMentions"] == ["research_broad"]


def test_project_agent_bus_revoke_marks_event_inbox_and_stops_targets(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    stopped_sessions = []
    monkeypatch.setattr(
        project_agent_bus_service.session_service,
        "wake_agent_for_inbox_message",
        lambda message: {
            "wakeRequested": True,
            "wakeStatus": "started",
            "messageId": message["messageId"],
            "targetAgentId": message["targetAgentId"],
            "targetSessionId": message["targetSessionId"],
            "turnId": "turn-revoked",
            "reason": "",
        },
    )
    monkeypatch.setattr(
        project_agent_bus_service.session_service,
        "request_stop_session_turn",
        lambda session_id: stopped_sessions.append(session_id) or {"status": "stopped"},
    )
    event = project_agent_bus_service.send_project_agent_bus_message(content=f"@{alpha['agentCode']} 发错的内容")
    inbox_message_id = event["deliveries"][0]["inboxMessageId"]

    revoked = project_agent_bus_service.revoke_project_agent_bus_message(
        event["eventId"],
        reason="发错内容",
    )

    assert revoked["status"] == "revoked"
    assert revoked["deliveries"][0]["revoked"] is True
    assert revoked["revocations"][0]["inboxStatus"] == "revoked"
    assert revoked["revocations"][0]["stopStatus"] == "stopped"
    assert stopped_sessions == ["session-alpha"]
    inbox_messages = agent_directory_service.list_agent_inbox_messages_for_agent(alpha["agentId"], status="")
    inbox = next(item for item in inbox_messages if item["messageId"] == inbox_message_id)
    assert inbox["status"] == "revoked"
    assert inbox["promptEligible"] is False
    assert agent_directory_service.list_agent_inbox_messages_for_agent(alpha["agentId"], status="pending") == []


def test_project_agent_bus_interrupts_only_target_agents(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    alpha = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    beta = agent_directory_service.create_agent_instance(display_name="Beta", direct_session_id="session-beta")
    stopped = []
    recorded_events = []
    monkeypatch.setattr(
        project_agent_bus_service.session_service,
        "get_session_detail",
        lambda session_id: {"id": session_id, "status": "running" if session_id == "session-alpha" else "ready"},
    )
    monkeypatch.setattr(
        project_agent_bus_service.session_service,
        "request_stop_session_turn",
        lambda session_id: stopped.append(session_id) or {"id": session_id, "status": "stopped"},
    )
    monkeypatch.setattr(
        project_agent_bus_service.session_service,
        "wake_agent_for_inbox_message",
        lambda message: {
            "wakeRequested": True,
            "wakeStatus": "skipped_busy",
            "messageId": message["messageId"],
            "targetAgentId": message["targetAgentId"],
            "targetSessionId": message["targetSessionId"],
            "turnId": "",
            "reason": "target_session_busy",
        },
    )
    monkeypatch.setattr(
        project_agent_bus_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )

    event = project_agent_bus_service.send_project_agent_bus_message(
        content=f"@{alpha['agentCode']} 改用新的边界判断",
        interrupt_mode="interrupt_targets",
    )

    assert event["targetAgentIds"] == [alpha["agentId"]]
    assert stopped == ["session-alpha"]
    assert event["interruptions"][0]["status"] == "interrupted"
    assert beta["agentId"] not in event["targetAgentIds"]
    assert recorded_events
    log_args, log_kwargs = recorded_events[-1]
    assert log_args[2] == "project_agent_bus.message.sent"
    assert log_kwargs["fields"]["targetAgentIds"] == [alpha["agentId"]]
    assert log_kwargs["fields"]["inboxMessageIds"] == [event["deliveries"][0]["inboxMessageId"]]
    assert log_kwargs["fields"]["wakeStatuses"] == ["skipped_busy"]
    assert log_kwargs["fields"]["interruptStatuses"] == ["interrupted"]
    assert log_kwargs["child_log_path"] == f"agent/project_agent_bus/{event['eventId']}.jsonl"
    child_payload = log_kwargs["child_log_payload"]
    assert child_payload["target_agent_ids"] == [alpha["agentId"]]
    assert child_payload["mentioned_tokens"] == [alpha["agentCode"]]
    assert child_payload["deliveries"][0]["inbox_message_id"] == event["deliveries"][0]["inboxMessageId"]
    assert child_payload["deliveries"][0]["wake_status"] == "skipped_busy"
    assert child_payload["deliveries"][0]["turn_id"] == ""
    assert child_payload["interruptions"][0]["status"] == "interrupted"
