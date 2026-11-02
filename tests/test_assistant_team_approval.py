"""Team consent scopes bind effects, identity and member-role permissions."""
import json

import pytest

from core.assistant_runtime.team_management_approval import team_management_approval_summary

BASE = {"project_id": "project-a", "request_id": "request-a"}
TEAM = {**BASE, "team_id": "team-a", "expected_team_fingerprint": "a" * 64}


def test_team_creation_exposes_roles_without_private_bodies():
    result = team_management_approval_summary("team_create", {**BASE, "name": "开发团队",
        "purpose": "PRIVATE_GOAL", "members": [{"agentId": "agent-a", "role": "lead", "purpose": "PRIVATE_MEMBER"}]})
    delta = result["assistantDelta"]
    assert result["assistantTargets"] == BASE and result["assistantChangedFields"] == ["team"]
    assert delta["memberAgentIds"] == ["agent-a"] and delta["memberCount"] == "1"
    assert delta["memberRoles"][0]["knowledgeReviewEligible"] is True
    assert result["assistantContentOmitted"] is True and "PRIVATE" not in json.dumps(result)


def test_member_add_and_remove_express_distinct_effects():
    add = team_management_approval_summary("team_member_add", {**TEAM, "member": {"agentId": "agent-a", "role": "reviewer"}})
    remove = team_management_approval_summary("team_member_remove", {**TEAM, "agent_id": "agent-a"})
    assert add["assistantDelta"]["operation"] == "add" and add["assistantDelta"]["memberAgentIds"] == ["agent-a"]
    assert remove["assistantDelta"] == {"operation": "remove", "removedAgentId": "agent-a", "preservesAgent": True,
        "preservesHistory": True, "explicitKnowledgeGrantsUnchanged": True}
    assert remove["assistantTargets"]["agent_id"] == "agent-a"


def test_archive_binds_exact_cascade_and_native_room():
    result = team_management_approval_summary("team_archive", {**TEAM,
        "expected_member_agent_ids": ["agent-a", "agent-b"], "expected_linked_chat_room_id": "room-a"})
    assert result["assistantTargets"]["expected_linked_chat_room_id"] == "room-a"
    assert result["assistantDelta"] == {"operation": "archive", "memberAgentIds": ["agent-a", "agent-b"],
        "memberCount": "2", "linkedChatRoomId": "room-a", "archivesMemberAgents": True,
        "freezesMemberSessions": True, "deletesLinkedChatRooms": True,
        "clearsOtherMemberRoomAssociations": True, "dissolvesEmptyMemberRooms": True,
        "keepsTeamKnowledgeAndFlows": True}
    assert result["assistantContentOmitted"] is False and result["assistantDetailsOmitted"] is False


@pytest.mark.parametrize("patch", [{"project_id": "../other"}, {"request_id": "id\n"}, {"actor": "admin"},
    {"name": "foo\u202ebar"}, {"name": "foo\nbar"}, {"name": "foo\u2028bar"}])
def test_invalid_or_invisible_consent_scope_is_rejected(patch):
    with pytest.raises(ValueError):
        team_management_approval_summary("team_create", {**BASE, "name": "Team", **patch})


def test_native_team_approval_projection_is_launcher_only(monkeypatch):
    from core.infrastructure import native_runtime
    from core.web.services.session.tool_approvals import _argument_summary, _assistant_management_summary
    values = {**BASE, "name": "Team", "description": "Legacy description"}
    arguments = {"action": "team_create", "arguments_json": json.dumps(values)}
    monkeypatch.setattr(native_runtime, "is_launcher_assistant_process", lambda: False)
    legacy = _assistant_management_summary(arguments)
    assert legacy == {"assistantAction": "team_create", "assistantTargets": {
        "name": "Team", "description": "Legacy description"}, "assistantDetailsOmitted": True}
    monkeypatch.setattr(native_runtime, "is_launcher_assistant_process", lambda: True)
    launcher = _assistant_management_summary(arguments)
    assert launcher == team_management_approval_summary("team_create", values)
    assert "Legacy description" not in json.dumps(launcher)
    native_projection = _argument_summary("personal_assistant_manage_tool", arguments)
    assert native_projection == {"argumentKeys": ["action", "arguments_json"], **launcher}


def test_launcher_team_approval_rejects_duplicate_native_arguments(monkeypatch):
    from core.infrastructure import native_runtime
    from core.web.services.session.tool_approvals import _assistant_management_summary
    monkeypatch.setattr(native_runtime, "is_launcher_assistant_process", lambda: True)
    result = _assistant_management_summary({"action": "team_archive", "arguments_json":
        '{"project_id":"project-a","request_id":"request-a","team_id":"team-a","team_id":"team-b"}'})
    assert result == {"assistantAction": "team_archive", "assistantArgumentsInvalid": True}
