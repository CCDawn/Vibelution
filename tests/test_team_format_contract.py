"""Unified team/role format contract tests.

Freezes the authoritative shapes documented in
``docs/standards/unified-team-format.md``:

- ``canvas_normalize._normalize_members`` member-row golden shape;
- ``team_template_service._dev_role`` role-definition golden shape;
- model projection reads agents.json only (no model values in stored rows);
- ``team_format`` validators accept canonical records and reject malformed
  ones (missing agentId, unknown agentId, model literals, non-slot modelRef).

Isolation follows ``tests/_support/team_workflow/helpers.py``:
VIBELUTION_DATA_HOME + per-module PROJECT_ROOT pins so no test can reach the
live operator workspace.
"""

from __future__ import annotations

from core.web.services import (
    agent_directory_service,
    chat_room_service,
    session_service,
    team_service,
    team_template_service,
)
from core.web.services.team import canvas_normalize, team_format, team_projection


def _use_tmp_project_root(tmp_path, monkeypatch):
    # PROJECT_ROOT alone is not a storage isolation boundary: pin the data
    # home before any AgentDirectory read/write so focused tests and ad-hoc
    # single-test runs cannot touch real Agent assets.
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)

    def list_direct_agent_sessions(*args, **kwargs):
        sessions = []
        for agent in agent_directory_service.list_agents(include_archived=False):
            session_id = str(agent.get("directSessionId") or "").strip()
            if not session_id:
                continue
            sessions.append(
                {
                    "id": session_id,
                    "title": str(agent.get("displayName") or session_id),
                    "agentId": str(agent.get("agentId") or ""),
                    "agentCode": str(agent.get("agentCode") or ""),
                    "workspacePath": str(agent.get("workspacePath") or ""),
                    "status": "active",
                    "updatedAt": "2026-10-07T00:00:00Z",
                }
            )
        return sessions

    monkeypatch.setattr(session_service, "list_sessions", list_direct_agent_sessions)


def _canonical_role() -> dict:
    return team_template_service._dev_role(
        role_key="dev_team_planner",
        role="规划师",
        purpose="把需求拆成可并行任务并派发。",
        responsibilities=["拆解需求", "派发任务"],
        agent_name="规划师 Agent",
        style="沉稳克制",
        communication_style="结论先行",
        expertise=["任务规划"],
        identity_notes="只做规划，不代写实现。",
        preferred_tasks="拆解需求、派发任务",
        avoid_tasks="不直接实现代码",
        success_criteria="每项任务可并行、可验证",
        constraints="写操作限定在任务 worktree",
        deliverables="任务清单",
        allowed_tools=["agent_message_tool"],
        preferred_tools=["agent_message_tool"],
        write_scopes=["private"],
    )


def _member_row(agent_id: str) -> dict:
    return {
        "memberId": "m1",
        "agentId": agent_id,
        "agentCode": "code-x",
        "agentName": "Alpha",
        "role": "负责人",
        "purpose": "统筹团队",
        "responsibilities": ["拆解任务"],
        "agentStatus": "active",
    }


def _team_with(members, **overrides) -> dict:
    team = {
        "teamId": "team",
        "name": "统一格式团队",
        "purpose": "契约验证",
        "status": "active",
        "linkedChatRoomId": "",
        "members": members,
    }
    team.update(overrides)
    return team


def _codes(result: dict) -> set[str]:
    return {issue["code"] for issue in result["issues"]}


# --- member row golden shape (canvas_normalize._normalize_members) ---------


def test_normalize_members_golden_shape_matches_contract(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")

    member = canvas_normalize._normalize_members(
        [
            {
                "memberId": "m1",
                "agentId": agent["agentId"],
                "role": "负责人",
                "purpose": "统筹团队",
                "responsibilities": ["拆解任务", "评审"],
            }
        ],
        require_active=True,
    )[0]

    assert set(member) == set(team_format.MEMBER_ROW_FIELDS)
    assert member["memberId"] == "m1"
    assert member["agentId"] == agent["agentId"]
    assert member["agentCode"] == agent["agentCode"]
    assert member["agentName"] == "Alpha"
    assert member["role"] == "负责人"
    assert member["responsibilities"] == ["拆解任务", "评审"]
    assert member["agentStatus"] == "active"
    # Model never lives in stored member rows; it is a response-time projection.
    assert "model" not in member
    assert team_format.validate_member_row(member, known_agent_ids={agent["agentId"]}) == []


def test_normalize_members_drops_unknown_agent_without_active_requirement(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    assert canvas_normalize._normalize_members([{"agentId": "agent-missing"}], require_active=False) == []


# --- role definition golden shape (team_template_service._dev_role) --------


def test_dev_role_golden_shape_matches_contract():
    role = _canonical_role()

    assert set(role) == set(team_format.ROLE_DEFINITION_FIELDS)
    assert set(role["personaProfile"]) == set(team_format.PERSONA_PROFILE_FIELDS)
    assert set(role["taskProfile"]) == set(team_format.TASK_PROFILE_FIELDS)
    assert set(role["toolPolicy"]) == set(team_format.TOOL_POLICY_FIELDS)
    result = team_format.validate_role_definition(role)
    assert result["valid"], result["issues"]


def test_shipped_dev_template_roles_satisfy_role_contract():
    template = team_template_service.get_team_template(team_template_service.DEV_TEAM_TEMPLATE_ID)
    assert template["roles"]
    for role in template["roles"]:
        result = team_format.validate_role_definition(role)
        assert result["valid"], (role.get("roleKey"), result["issues"])


# --- model reference semantics (agents.json is the sole authority) ---------


def test_member_model_summary_projects_from_agents_json_authority(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    bound = agent_directory_service.create_agent_instance(
        display_name="Bound",
        direct_session_id="session-bound",
        llm_bindings={"dialogue": {"modelId": "qwen3.5-9b"}},
    )
    unbound = agent_directory_service.create_agent_instance(display_name="Plain", direct_session_id="session-plain")

    # Re-read through agents.json so the projection provably resolves the
    # stored llmBindings, not an in-memory literal.
    stored_bound = agent_directory_service.get_agent(bound["agentId"], include_archived=False)
    stored_unbound = agent_directory_service.get_agent(unbound["agentId"], include_archived=False)
    agent_refs = {
        "active_by_id": {
            bound["agentId"]: stored_bound,
            unbound["agentId"]: stored_unbound,
        }
    }

    assert team_projection._member_model_summary(bound["agentId"], agent_refs=agent_refs) == {
        "dialogueModelId": "qwen3.5-9b",
        "configured": True,
    }
    assert team_projection._member_model_summary(unbound["agentId"], agent_refs=agent_refs) == {
        "dialogueModelId": "",
        "configured": False,
    }
    assert team_projection._member_model_summary("agent-ghost", agent_refs=agent_refs) == {
        "dialogueModelId": "",
        "configured": False,
    }


# --- validate_team_record: accept canonical, reject malformed --------------


def test_validate_team_record_accepts_team_created_through_team_service(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")

    response = team_service.create_team(
        name="统一格式团队",
        purpose="契约验证",
        members=[{"agentId": agent["agentId"], "role": "负责人", "responsibilities": ["拆解任务"]}],
    )
    # create_team returns the API projection; the format contract targets the
    # stored record (canvas_normalize._normalize_members output).
    team = team_service._get_team_record(response["teamId"])

    assert team_format.validate_team_record(team)["valid"]
    known_agent_ids = team_format.load_known_agent_ids()
    assert agent["agentId"] in known_agent_ids
    assert team_format.validate_team_record(team, known_agent_ids=known_agent_ids)["valid"]

    # Model stays a response-time projection: present in API rows, absent in
    # the stored row it was projected from.
    assert set(team["members"][0]) == set(team_format.MEMBER_ROW_FIELDS)
    assert "model" not in team["members"][0]
    response_member = response["members"][0]
    assert set(response_member) >= set(team_format.MEMBER_ROW_FIELDS) | {"model"}
    assert set(response_member["model"]) == {"dialogueModelId", "configured"}


def test_validate_team_record_rejects_malformed_records(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Alpha", direct_session_id="session-alpha")
    known_agent_ids = {agent["agentId"]}

    missing_agent_id = team_format.validate_team_record(
        _team_with([_member_row("")]), known_agent_ids=known_agent_ids
    )
    assert not missing_agent_id["valid"]
    assert "member_missing_agent_id" in _codes(missing_agent_id)

    unknown_agent_id = team_format.validate_team_record(
        _team_with([_member_row("agent-ghost")]), known_agent_ids=known_agent_ids
    )
    assert not unknown_agent_id["valid"]
    assert "member_unknown_agent_id" in _codes(unknown_agent_id)

    duplicate = team_format.validate_team_record(
        _team_with([_member_row(agent["agentId"]), _member_row(agent["agentId"])]),
        known_agent_ids=known_agent_ids,
    )
    assert not duplicate["valid"]
    assert "team_duplicate_agent_id" in _codes(duplicate)

    row_with_model = _member_row(agent["agentId"])
    row_with_model["model"] = {"dialogueModelId": "qwen3.5-9b", "configured": True}
    model_literal = team_format.validate_team_record(_team_with([row_with_model]), known_agent_ids=known_agent_ids)
    assert not model_literal["valid"]
    assert "model_literal_forbidden" in _codes(model_literal)

    bad_status = team_format.validate_team_record(
        _team_with([_member_row(agent["agentId"])], status="paused"), known_agent_ids=known_agent_ids
    )
    assert not bad_status["valid"]
    assert "team_invalid_status" in _codes(bad_status)

    members_not_list = team_format.validate_team_record(_team_with("not-a-list"), known_agent_ids=known_agent_ids)
    assert not members_not_list["valid"]
    assert "team_members_not_list" in _codes(members_not_list)

    assert not team_format.validate_team_record("not-a-team")["valid"]


# --- validate_role_definition: accept canonical, reject malformed ----------


def test_validate_role_definition_rejects_missing_sections_and_model_literals():
    valid = _canonical_role()
    assert team_format.validate_role_definition(valid)["valid"]

    missing_section = {key: value for key, value in valid.items() if key != "toolPolicy"}
    missing_result = team_format.validate_role_definition(missing_section)
    assert not missing_result["valid"]
    assert "role_section_missing" in _codes(missing_result)

    model_literal = dict(valid, model="gpt-4o")
    literal_result = team_format.validate_role_definition(model_literal)
    assert not literal_result["valid"]
    assert "model_literal_forbidden" in _codes(literal_result)

    prompt_literal = dict(valid, systemPrompt="你是一个助手。")
    prompt_result = team_format.validate_role_definition(prompt_literal)
    assert not prompt_result["valid"]
    assert "model_literal_forbidden" in _codes(prompt_result)

    # modelRef must be an agents.json llmBindings slot reference, never a
    # concrete model id literal.
    literal_ref = dict(valid, modelRef="qwen3.5-9b")
    ref_result = team_format.validate_role_definition(literal_ref)
    assert not ref_result["valid"]
    assert "role_model_ref_not_slot" in _codes(ref_result)

    slot_ref = dict(valid, modelRef="dialogue")
    assert team_format.validate_role_definition(slot_ref)["valid"]

    assert not team_format.validate_role_definition("not-a-role")["valid"]
