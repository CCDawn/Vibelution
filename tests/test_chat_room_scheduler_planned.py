"""PlannedScheduler (manager-dispatch) unit tests."""

from core.chatroom.scheduler import get_scheduler_registry
from core.web.services import chat_room_service


def _dev_team_participants():
    return [
        {
            "participantId": "p-planner",
            "teamRole": "规划师",
            "agentCode": "DT01",
            "enabled": True,
        },
        {
            "participantId": "p-dev-a",
            "teamRole": "开发工程师 A",
            "agentCode": "DT02",
            "enabled": True,
        },
        {
            "participantId": "p-dev-b",
            "teamRole": "开发工程师 B",
            "agentCode": "DT03",
            "enabled": True,
        },
        {
            "participantId": "p-reviewer",
            "teamRole": "评审员",
            "agentCode": "DT04",
            "enabled": True,
        },
    ]


def _history_with_manager_message(content: str, *, round_id: str = "round-1"):
    return [
        {
            "roundId": round_id,
            "messages": [
                {
                    "participantId": "p-planner",
                    "status": "completed",
                    "content": content,
                }
            ],
        }
    ]


def _select(participants, *, history=None, config=None):
    scheduler = get_scheduler_registry().get("planned")
    assert scheduler is not None
    assert scheduler.status == "ready"
    return scheduler.select_speakers(
        participants,
        topic="推进任务",
        history=history or [],
        config=config or {},
    )


def test_planned_mode_is_registered_as_ready():
    modes = {item["id"]: item for item in get_scheduler_registry().list_modes()}

    assert modes["planned"]["status"] == "ready"
    assert modes["planned"]["label"] == "计划分派"


def test_planned_mode_without_history_returns_manager_only():
    speakers = _select(_dev_team_participants(), config={"managerTeamRole": "规划师"})

    assert [item["participantId"] for item in speakers] == ["p-planner"]


def test_planned_mode_selects_mentioned_team_roles_in_order():
    history = _history_with_manager_message("本轮派发：@开发工程师 B 先行，@开发工程师 A 跟进。")

    speakers = _select(
        _dev_team_participants(),
        history=history,
        config={"managerTeamRole": "规划师"},
    )

    assert [item["participantId"] for item in speakers] == ["p-dev-b", "p-dev-a"]


def test_planned_mode_mention_tolerates_missing_space_and_matches_team_role():
    history = _history_with_manager_message("派发给@开发工程师A，完成后交@评审员审查。")

    speakers = _select(
        _dev_team_participants(),
        history=history,
        config={"managerTeamRole": "规划师"},
    )

    assert [item["participantId"] for item in speakers] == ["p-dev-a", "p-reviewer"]


def test_planned_mode_mention_matches_agent_code():
    history = _history_with_manager_message("@DT03 负责本轮实现。")

    speakers = _select(
        _dev_team_participants(),
        history=history,
        config={"managerTeamRole": "规划师"},
    )

    assert [item["participantId"] for item in speakers] == ["p-dev-b"]


def test_planned_mode_without_hits_falls_back_to_manager():
    history = _history_with_manager_message("继续拆解需求，暂不派发。")

    speakers = _select(
        _dev_team_participants(),
        history=history,
        config={"managerTeamRole": "规划师"},
    )

    assert [item["participantId"] for item in speakers] == ["p-planner"]


def test_planned_mode_uses_latest_manager_message_only():
    history = [
        {
            "roundId": "round-1",
            "messages": [
                {
                    "participantId": "p-planner",
                    "status": "completed",
                    "content": "@开发工程师 A 先做登录页。",
                }
            ],
        },
        {
            "roundId": "round-2",
            "messages": [
                {
                    "participantId": "p-dev-a",
                    "status": "completed",
                    "content": "登录页已完成。",
                },
                {
                    "participantId": "p-planner",
                    "status": "completed",
                    "content": "收到，继续规划下一步。",
                },
            ],
        },
    ]

    speakers = _select(
        _dev_team_participants(),
        history=history,
        config={"managerTeamRole": "规划师"},
    )

    assert [item["participantId"] for item in speakers] == ["p-planner"]


def test_planned_mode_returns_manager_once_assignees_have_reported():
    history = [
        {
            "roundId": "round-1",
            "messages": [
                {
                    "participantId": "p-planner",
                    "status": "completed",
                    "content": "@开发工程师 A 先做登录页。",
                }
            ],
        },
        {
            "roundId": "round-2",
            "messages": [
                {
                    "participantId": "p-dev-a",
                    "status": "completed",
                    "content": "登录页已完成。",
                }
            ],
        },
    ]

    speakers = _select(
        _dev_team_participants(),
        history=history,
        config={"managerTeamRole": "规划师"},
    )

    assert [item["participantId"] for item in speakers] == ["p-planner"]


def test_planned_mode_manager_can_reassign_after_report():
    history = [
        {
            "roundId": "round-1",
            "messages": [
                {
                    "participantId": "p-planner",
                    "status": "completed",
                    "content": "@开发工程师 A 先做登录页。",
                }
            ],
        },
        {
            "roundId": "round-2",
            "messages": [
                {
                    "participantId": "p-dev-a",
                    "status": "completed",
                    "content": "登录页已完成。",
                }
            ],
        },
        {
            "roundId": "round-3",
            "messages": [
                {
                    "participantId": "p-planner",
                    "status": "completed",
                    "content": "收到，下一步 @开发工程师 B 负责注册页。",
                }
            ],
        },
    ]

    speakers = _select(
        _dev_team_participants(),
        history=history,
        config={"managerTeamRole": "规划师"},
    )

    assert [item["participantId"] for item in speakers] == ["p-dev-b"]


def test_planned_mode_alternates_dispatch_and_report_rounds():
    participants = _dev_team_participants()
    config = {"managerTeamRole": "规划师"}

    def _round(round_id, messages):
        return {"roundId": round_id, "messages": messages}

    def _msg(participant_id, content):
        return {
            "participantId": participant_id,
            "status": "completed",
            "content": content,
        }

    planning = _round("round-1", [_msg("p-planner", "@开发工程师 A、@开发工程师 B 并行实现。")])
    reports = _round(
        "round-2",
        [_msg("p-dev-a", "登录页已完成。"), _msg("p-dev-b", "注册页已完成。")],
    )
    review_dispatch = _round("round-3", [_msg("p-planner", "汇总完成，@评审员 提审。")])
    review_report = _round("round-4", [_msg("p-reviewer", "评审通过。")])

    assert [
        item["participantId"] for item in _select(participants, history=[planning], config=config)
    ] == ["p-dev-a", "p-dev-b"]
    assert [
        item["participantId"]
        for item in _select(participants, history=[planning, reports], config=config)
    ] == ["p-planner"]
    assert [
        item["participantId"]
        for item in _select(participants, history=[planning, reports, review_dispatch], config=config)
    ] == ["p-reviewer"]
    assert [
        item["participantId"]
        for item in _select(
            participants, history=[planning, reports, review_dispatch, review_report], config=config
        )
    ] == ["p-planner"]


def test_planned_mode_static_speaker_order_overrides_history_mentions():
    history = _history_with_manager_message("@开发工程师 A 先行。")

    speakers = _select(
        _dev_team_participants(),
        history=history,
        config={
            "managerTeamRole": "规划师",
            "speakerOrder": ["DT04", "p-dev-b", "missing-key"],
        },
    )

    assert [item["participantId"] for item in speakers] == ["p-reviewer", "p-dev-b"]


def test_planned_mode_skips_disabled_members_when_matching_mentions():
    participants = _dev_team_participants()
    participants[1]["enabled"] = False
    history = _history_with_manager_message("@开发工程师 A 与 @开发工程师 B 并行。")

    speakers = _select(
        participants,
        history=history,
        config={"managerTeamRole": "规划师"},
    )

    assert [item["participantId"] for item in speakers] == ["p-dev-b"]


def test_planned_mode_manager_resolution_prefers_role_then_key_then_first_enabled():
    participants = _dev_team_participants()

    by_role = _select(participants, config={"managerTeamRole": "规划师"})
    assert by_role[0]["participantId"] == "p-planner"

    by_key = _select(participants, config={"managerParticipantKey": "DT02"})
    assert by_key[0]["participantId"] == "p-dev-a"

    fallback = _select(participants, config={})
    assert fallback[0]["participantId"] == "p-planner"


def test_planned_mode_respects_max_speakers_limit():
    history = _history_with_manager_message("@开发工程师 A、@开发工程师 B 并行。")

    speakers = _select(
        _dev_team_participants(),
        history=history,
        config={"managerTeamRole": "规划师", "maxSpeakers": 1},
    )

    assert [item["participantId"] for item in speakers] == ["p-dev-a"]


def test_planned_prompt_instructs_mention_dispatch_lexicon():
    prompt = chat_room_service._build_participant_prompt(
        room={"roomId": "room-planned", "title": "开发团队", "mode": "planned"},
        round_payload={"topic": "开发登录页", "mode": "planned", "purpose": "meeting"},
        participant={"participantId": "p-planner", "teamRole": "规划师"},
        prior_messages=[],
    )

    assert "计划分派模式" in prompt
    assert "@成员角色名" in prompt
    assert "@开发工程师 A" in prompt
    assert "被指派成员发言后，下一轮回到规划角色汇总并决定后续指派" in prompt
    assert "共享任务板" not in prompt


def test_dev_team_prompt_includes_the_readonly_board_and_keeps_mentions(monkeypatch):
    monkeypatch.setattr(
        chat_room_service,
        "_dev_task_board_prompt",
        lambda team_id: f"BOARD:{team_id}",
    )

    prompt = chat_room_service._build_participant_prompt(
        room={
            "roomId": "room-planned",
            "title": "开发团队",
            "mode": "planned",
            "config": {"teamTemplateId": "dev-team"},
        },
        round_payload={"topic": "开发登录页", "mode": "planned", "purpose": "meeting"},
        participant={"participantId": "p-planner", "teamRole": "规划师", "teamId": "team-9"},
        prior_messages=[],
    )

    assert "BOARD:team-9" in prompt
    assert "@开发工程师 A" in prompt


def test_other_team_prompts_do_not_read_the_dev_task_board(monkeypatch):
    def unexpected(team_id: str) -> str:
        raise AssertionError(team_id)

    monkeypatch.setattr(chat_room_service, "_dev_task_board_prompt", unexpected)
    prompt = chat_room_service._build_participant_prompt(
        room={
            "roomId": "room-research",
            "title": "研究团队",
            "mode": "planned",
            "config": {"teamTemplateId": "research", "teamId": "team-research"},
        },
        round_payload={"topic": "选题", "mode": "planned", "purpose": "meeting"},
        participant={"participantId": "p-a", "teamRole": "研究员", "teamId": "team-research"},
        prior_messages=[],
    )

    assert "共享任务板" not in prompt


def test_round_robin_prompt_stays_free_of_planned_dispatch_line():
    prompt = chat_room_service._build_participant_prompt(
        room={"roomId": "room-plain", "title": "普通群聊", "mode": "round_robin"},
        round_payload={"topic": "随便聊聊", "mode": "round_robin", "purpose": "chat"},
        participant={"participantId": "p-a"},
        prior_messages=[],
    )

    assert "计划分派模式" not in prompt
