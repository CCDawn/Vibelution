from core.web.services.team_conversation_contract import build_team_conversation_projection


def test_projection_marks_team_without_room_as_unlinked():
    projection = build_team_conversation_projection(
        team={"teamId": "team-a", "members": [{"agentId": "agent-a", "agentStatus": "active"}]},
        linked_room=None,
        agents_by_id={"agent-a": {"agentId": "agent-a"}},
    )

    assert projection.to_api() == {
        "teamId": "team-a",
        "linkedRoomId": "",
        "status": "unlinked",
        "memberAgentIds": ["agent-a"],
        "roomAgentIds": [],
        "missingAgentIds": [],
        "missingAgentCount": 0,
    }


def test_projection_marks_matching_room_as_linked():
    projection = build_team_conversation_projection(
        team={
            "teamId": "team-a",
            "linkedChatRoomId": "room-a",
            "members": [{"agentId": "agent-a", "agentStatus": "active"}],
        },
        linked_room={"roomId": "room-a", "participants": [{"agentId": "agent-a"}]},
        agents_by_id={"agent-a": {"agentId": "agent-a"}},
    )

    assert projection.status == "linked"
    assert projection.linked_room_id == "room-a"
    assert projection.member_agent_ids == ("agent-a",)
    assert projection.room_agent_ids == ("agent-a",)


def test_projection_marks_stale_member_as_agent_missing():
    projection = build_team_conversation_projection(
        team={
            "teamId": "team-a",
            "linkedChatRoomId": "room-a",
            "members": [{"agentId": "agent-a", "agentStatus": "stale"}],
        },
        linked_room={"roomId": "room-a", "participants": []},
        agents_by_id={},
    )

    assert projection.status == "agent_missing"
    assert projection.missing_agent_ids == ("agent-a",)


def test_projection_marks_room_membership_drift_as_conflict():
    projection = build_team_conversation_projection(
        team={
            "teamId": "team-a",
            "linkedChatRoomId": "room-a",
            "members": [
                {"agentId": "agent-a", "agentStatus": "active"},
                {"agentId": "agent-b", "agentStatus": "active"},
            ],
        },
        linked_room={"roomId": "room-a", "participants": [{"agentId": "agent-a"}]},
        agents_by_id={"agent-a": {"agentId": "agent-a"}, "agent-b": {"agentId": "agent-b"}},
    )

    assert projection.status == "membership_conflict"
    assert projection.member_agent_ids == ("agent-a", "agent-b")
    assert projection.room_agent_ids == ("agent-a",)


def test_projection_marks_missing_linked_room_as_room_missing():
    projection = build_team_conversation_projection(
        team={
            "teamId": "team-a",
            "linkedChatRoomId": "room-missing",
            "members": [{"agentId": "agent-a", "agentStatus": "active"}],
        },
        linked_room=None,
        agents_by_id={"agent-a": {"agentId": "agent-a"}},
    )

    assert projection.status == "room_missing"
    assert projection.linked_room_id == "room-missing"
