from core.web.services.team_case_orchestrator import (
    build_team_case_state,
    case_prompt_lines,
    format_case_state_prompt,
    select_speakers_for_case,
)


def test_heletech_health_question_becomes_intake_case_before_solution():
    participants = [
        {"participantId": "host", "teamRole": "方案主持", "enabled": True},
        {"participantId": "business", "teamRole": "妇幼业务顾问", "enabled": True},
        {"participantId": "emr", "teamRole": "病历集成顾问", "enabled": True},
        {"participantId": "data", "teamRole": "数据科研顾问", "enabled": True},
        {"participantId": "safety", "teamRole": "合规交付顾问", "enabled": True},
    ]

    case_state = build_team_case_state(
        room={
            "roomId": "room-demo",
            "config": {
                "teamId": "demo-2",
                "teamTemplateId": "heletech-maternal-digital-health-demo",
                "heletechMaternalDigitalHealthDemo": True,
            },
        },
        topic="孩子晚上经常哭泣是为什么",
        purpose="meeting",
        participants=participants,
        history=[],
    )

    assert case_state["intent"] == "maternal_child_consultation_demo"
    assert case_state["informationSufficiency"] == "insufficient"
    assert case_state["nextAction"] == "clarify"
    assert case_state["userFacingMode"] == "direct_clarification"
    assert case_state["discussionVisibility"] == "user_visible"
    assert case_state["status"] == "waiting_user"
    assert "年龄/月龄" in case_state["missingFacts"]
    assert "伴随症状" in case_state["missingFacts"]
    assert "先完成用户侧问诊信息对齐" in case_state["demoMapping"]
    assert any("面向用户自然澄清" in line for line in case_prompt_lines(case_state))
    assert any("不是开会讨论如何澄清" in line for line in case_prompt_lines(case_state))
    assert any("不要写成问卷" in line for line in case_prompt_lines(case_state))
    assert any("整套项目一次性铺开" in line for line in case_prompt_lines(case_state))
    assert any("clarify 阶段禁止提" in line for line in case_prompt_lines(case_state))
    formatted_prompt = format_case_state_prompt(case_state)
    assert "Demo 映射边界" in formatted_prompt
    assert "本轮不要做产品能力映射" in formatted_prompt
    assert "Demo 映射原则" not in formatted_prompt

    selected = select_speakers_for_case(participants, participants=participants, case_state=case_state)

    assert [item["participantId"] for item in selected] == ["host"]


def test_heletech_health_question_with_enough_context_discusses_before_plan():
    participants = [
        {"participantId": "host", "teamRole": "方案主持", "enabled": True},
        {"participantId": "business", "teamRole": "妇幼业务顾问", "enabled": True},
        {"participantId": "safety", "teamRole": "合规交付顾问", "enabled": True},
    ]

    case_state = build_team_case_state(
        room={"roomId": "room-demo", "config": {"heletechMaternalDigitalHealthDemo": True}},
        topic="3岁孩子连续3天晚上哭闹，体温正常，没有咳嗽呕吐腹泻，既往无过敏和用药史",
        purpose="meeting",
        participants=participants,
        history=[],
    )

    assert case_state["informationSufficiency"] == "sufficient"
    assert case_state["nextAction"] == "discuss"
    assert case_state["userFacingMode"] == "team_discussion_then_advice"
    assert case_state["discussionVisibility"] == "collapsed_by_default"
    assert select_speakers_for_case(participants, participants=participants, case_state=case_state) == participants
    assert any("信息足以进入团队讨论" in line for line in case_prompt_lines(case_state))
    assert "Demo 映射原则" in format_case_state_prompt(case_state)


def test_heletech_non_health_demo_topic_keeps_full_team_delegation():
    participants = [
        {"participantId": "host", "teamRole": "方案主持", "enabled": True},
        {"participantId": "data", "teamRole": "数据科研顾问", "enabled": True},
    ]

    case_state = build_team_case_state(
        room={"roomId": "room-demo", "config": {"heletechMaternalDigitalHealthDemo": True}},
        topic="给公司展示云上妇幼产品方案",
        purpose="meeting",
        participants=participants,
        history=[],
    )

    assert case_state["intent"] == "enterprise_demo_solution"
    assert case_state["informationSufficiency"] == "sufficient"
    assert case_state["nextAction"] == "discuss"
    assert case_state["userFacingMode"] == "team_discussion"
    assert select_speakers_for_case(participants, participants=participants, case_state=case_state) == participants
