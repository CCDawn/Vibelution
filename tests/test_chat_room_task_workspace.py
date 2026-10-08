"""Dev-team chat room speaker binding: task worktree, write contract, convergence."""

import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from core.web.services import (
    agent_directory_service,
    chat_room_service,
    session_service,
    team_service,
    team_template_service,
)
from core.web.services.team.dev_task_board import format_dev_task_board_prompt
from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from tests.helpers.system_agent_state import _mark_config_agent_instances_present


READONLY_CONTRACT = "请给出一段紧凑、可读、只读的群聊发言。不要修改文件、不要提交、不要启动进化或部署。"
ENGINEER_CONTRACT = "只允许在你认领任务的工作区内修改文件（路径见任务摘要）"
CONVERGENCE_LINE = "当任务摘要显示全部任务已完成，总结成果并宣布本团队目标收敛"
PLANNER_FLOW_LINE = "派发前必须先用 dev_task_board_tool 的 create_task 把拆分后的任务落到共享任务板"
ENGINEER_FLOW_LINE = "开工前先用 dev_task_board_tool 的 claim_task 认领派给你的任务并取得任务工作区"
REVIEWER_FLOW_LINE = "评审依据 dev_task_board_tool 的 read_task_changes 返回的任务 diff 与测试输出"
DEV_TEAM_HEADER = "你正在参加 Vibelution 的开发团队群聊。"
READONLY_HEADER = "你正在参加 Vibelution 的只读 Agent 群聊。"


def _client() -> TestClient:
    return TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


def _use_tmp_project_root(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chat_room_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(team_template_service, "PROJECT_ROOT", tmp_path)


def _seed_main_repo(path: Path, monkeypatch) -> None:
    import os

    from core.infrastructure import git_process

    for key in list(os.environ):
        if key.startswith("GIT_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    hooks = path / "_hooks"
    hooks.mkdir(exist_ok=True)
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    result = git_process.run_git(
        ["init", "-b", "main"],
        cwd=str(path),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    for args in (
        ["config", "user.name", "Vibelution Test"],
        ["config", "user.email", "test@example.invalid"],
        ["config", "core.hooksPath", str(hooks)],
    ):
        git_process.run_git(args, cwd=str(path), capture_output=True, text=True, env=env, check=False)
    (path / "README.md").write_text("seed\n", encoding="utf-8")
    git_process.run_git(["add", "README.md"], cwd=str(path), capture_output=True, text=True, env=env, check=False)
    commit = git_process.run_git(
        ["commit", "-m", "seed"], cwd=str(path), capture_output=True, text=True, env=env, check=False
    )
    assert commit.returncode == 0, commit.stderr


def _dev_team(tmp_path, monkeypatch):
    _seed_main_repo(tmp_path, monkeypatch)
    _use_tmp_project_root(tmp_path, monkeypatch)
    _mark_config_agent_instances_present()
    client = _client()
    created = client.post("/api/team-templates/dev-team/instantiate", json={"name": "绑定团队"})
    assert created.status_code == 201, created.text
    team = created.json()["team"]
    members = {member["role"]: member for member in team["members"]}
    assert str(members["开发工程师 A"].get("agentId") or ""), members
    assert str(members["开发工程师 B"].get("agentId") or ""), members
    return client, team, members


def _create_task(client, team, members, *, subject="拆出登录按钮", owner=None):
    created = client.post(
        f"/api/teams/{team['teamId']}/dev-tasks",
        json={
            "actorMemberId": members["规划师"]["memberId"],
            "subject": subject,
            "description": "只改按钮文案",
            "writeScopes": ["web/src/routes/login"],
            "ownerMemberId": (owner or {}).get("memberId", ""),
        },
    )
    assert created.status_code == 201, created.text
    views = created.json()["tasks"]
    return [item for item in views if item["subject"] == subject][-1]


def _act(client, team, members, task, action, *, actor="开发工程师 A", revision=None, note=""):
    acted = client.post(
        f"/api/teams/{team['teamId']}/dev-tasks/{task['id']}",
        json={
            "actorMemberId": members[actor]["memberId"],
            "action": action,
            "expectedRevision": task["revision"] if revision is None else revision,
            "reviewNote": note,
        },
    )
    assert acted.status_code == 200, acted.text
    views = [item for item in acted.json()["tasks"] if item["id"] == task["id"]]
    assert views, acted.text
    return views[0]


def test_active_claim_binds_the_task_worktree(tmp_path, monkeypatch):
    client, team, members = _dev_team(tmp_path, monkeypatch)
    task = _create_task(client, team, members, owner=members["开发工程师 A"])
    claimed = _act(client, team, members, task, "claim")
    assert claimed["status"] == "in_progress"

    bound = chat_room_service._participant_task_workspace(
        {"devTeamId": team["teamId"]},
        {"agentId": members["开发工程师 A"]["agentId"]},
    )
    assert bound == (tmp_path / claimed["workspacePath"]).resolve()
    assert (tmp_path / claimed["workspacePath"] / ".git").exists()


def test_rework_still_binds_but_completed_pending_and_missing_do_not(tmp_path, monkeypatch):
    client, team, members = _dev_team(tmp_path, monkeypatch)
    agent_a = {"agentId": members["开发工程师 A"]["agentId"]}

    rework_task = _act(
        client,
        team,
        members,
        _create_task(client, team, members, subject="退回重做", owner=members["开发工程师 A"]),
        "claim",
    )
    reworked = _act(
        client,
        team,
        members,
        rework_task,
        "rework",
        actor="评审员",
        revision=rework_task["revision"],
        note="补测试",
    )
    assert reworked["status"] == "rework"
    bound = chat_room_service._participant_task_workspace({"devTeamId": team["teamId"]}, agent_a)
    assert bound == (tmp_path / reworked["workspacePath"]).resolve()

    completed = _act(
        client,
        team,
        members,
        reworked,
        "complete",
        actor="评审员",
        revision=reworked["revision"],
        note="通过",
    )
    assert completed["status"] == "completed"
    assert chat_room_service._participant_task_workspace({"devTeamId": team["teamId"]}, agent_a) is None

    pending = _create_task(client, team, members, subject="还没认领", owner=members["开发工程师 A"])
    assert pending["status"] == "pending"
    assert chat_room_service._participant_task_workspace({"devTeamId": team["teamId"]}, agent_a) is None

    claimed = _act(client, team, members, pending, "claim")
    assert claimed["status"] == "in_progress"
    shutil.rmtree(tmp_path / claimed["workspacePath"])
    assert chat_room_service._participant_task_workspace({"devTeamId": team["teamId"]}, agent_a) is None


def test_two_engineers_bind_their_own_worktrees_only(tmp_path, monkeypatch):
    client, team, members = _dev_team(tmp_path, monkeypatch)
    task_a = _create_task(client, team, members, subject="A 的任务", owner=members["开发工程师 A"])
    task_b = _create_task(client, team, members, subject="B 的任务", owner=members["开发工程师 B"])
    claimed_a = _act(client, team, members, task_a, "claim")
    claimed_b = _act(client, team, members, task_b, "claim", actor="开发工程师 B")
    assert claimed_a["workspacePath"] != claimed_b["workspacePath"]

    context = {"devTeamId": team["teamId"]}
    bound_a = chat_room_service._participant_task_workspace(
        context, {"agentId": members["开发工程师 A"]["agentId"]}
    )
    bound_b = chat_room_service._participant_task_workspace(
        context, {"agentId": members["开发工程师 B"]["agentId"]}
    )
    assert bound_a == (tmp_path / claimed_a["workspacePath"]).resolve()
    assert bound_b == (tmp_path / claimed_b["workspacePath"]).resolve()
    assert bound_a != bound_b
    # A planner or an unknown agent never binds.
    assert chat_room_service._participant_task_workspace(
        context, {"agentId": members["规划师"]["agentId"]}
    ) is None
    assert chat_room_service._participant_task_workspace(context, {"agentId": "agent-unknown"}) is None


def test_binding_needs_a_dev_team_and_never_raises(monkeypatch):
    assert chat_room_service._participant_task_workspace({}, {"agentId": "agent-1"}) is None
    assert chat_room_service._participant_task_workspace(None, {"agentId": "agent-1"}) is None
    assert chat_room_service._participant_task_workspace({"devTeamId": "team-1"}, {}) is None

    def boom(team_id, agent_id):
        raise RuntimeError("board exploded")

    monkeypatch.setattr(
        "core.web.services.team.dev_task_board.member_active_task_workspace", boom
    )
    assert (
        chat_room_service._participant_task_workspace({"devTeamId": "team-1"}, {"agentId": "agent-1"}) is None
    )


def test_engineer_contract_differs_and_planner_gets_the_convergence_line(monkeypatch):
    monkeypatch.setenv("VIBELUTION_CHAT_ROOM_STRUCTURED_CONTEXT_ENABLED", "0")

    def board(team_id: str) -> str:
        return f"BOARD:{team_id}"

    monkeypatch.setattr(chat_room_service, "_dev_task_board_prompt", board)
    room = {
        "roomId": "room-dev",
        "title": "绑定团队 团队群聊",
        "mode": "planned",
        "config": {"teamTemplateId": "dev-team", "teamId": "team-9"},
    }
    round_payload = {"topic": "开发登录页", "mode": "planned", "purpose": "meeting"}

    engineer_prompt = chat_room_service._build_participant_prompt(
        room=room,
        round_payload=round_payload,
        participant={"participantId": "p-a", "teamRole": "开发工程师 A", "teamId": "team-9"},
        prior_messages=[],
    )
    assert ENGINEER_CONTRACT in engineer_prompt
    assert ENGINEER_FLOW_LINE in engineer_prompt
    assert "不要修改文件" not in engineer_prompt
    assert CONVERGENCE_LINE not in engineer_prompt
    assert "BOARD:team-9" in engineer_prompt
    assert DEV_TEAM_HEADER in engineer_prompt
    assert READONLY_HEADER not in engineer_prompt

    planner_prompt = chat_room_service._build_participant_prompt(
        room=room,
        round_payload=round_payload,
        participant={"participantId": "p-plan", "teamRole": "规划师", "teamId": "team-9"},
        prior_messages=[],
    )
    assert PLANNER_FLOW_LINE in planner_prompt
    assert READONLY_CONTRACT not in planner_prompt
    assert "不要直接修改仓库文件" in planner_prompt
    assert CONVERGENCE_LINE in planner_prompt
    assert DEV_TEAM_HEADER in planner_prompt

    reviewer_prompt = chat_room_service._build_participant_prompt(
        room=room,
        round_payload=round_payload,
        participant={"participantId": "p-rev", "teamRole": "评审员", "teamId": "team-9"},
        prior_messages=[],
    )
    assert REVIEWER_FLOW_LINE in reviewer_prompt
    assert READONLY_CONTRACT not in reviewer_prompt
    assert CONVERGENCE_LINE not in reviewer_prompt
    assert ENGINEER_CONTRACT not in reviewer_prompt


def test_non_dev_team_rooms_keep_the_readonly_contract(monkeypatch):
    monkeypatch.setenv("VIBELUTION_CHAT_ROOM_STRUCTURED_CONTEXT_ENABLED", "0")

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
    assert READONLY_CONTRACT in prompt
    assert READONLY_HEADER in prompt
    assert DEV_TEAM_HEADER not in prompt
    assert ENGINEER_CONTRACT not in prompt
    assert CONVERGENCE_LINE not in prompt
    assert "共享任务板" not in prompt
    assert PLANNER_FLOW_LINE not in prompt
    assert ENGINEER_FLOW_LINE not in prompt
    assert REVIEWER_FLOW_LINE not in prompt


def test_structured_contract_appends_the_engineer_write_line_only(monkeypatch):
    monkeypatch.setenv("VIBELUTION_CHAT_ROOM_STRUCTURED_CONTEXT_ENABLED", "1")
    monkeypatch.setattr(
        chat_room_service, "_dev_task_board_prompt", lambda team_id: f"BOARD:{team_id}"
    )
    room = {
        "roomId": "room-dev",
        "title": "绑定团队 团队群聊",
        "mode": "planned",
        "config": {"teamTemplateId": "dev-team", "teamId": "team-9"},
    }
    round_payload = {"topic": "开发登录页", "mode": "planned", "purpose": "meeting"}

    engineer_prompt = chat_room_service._build_participant_prompt(
        room=room,
        round_payload=round_payload,
        participant={"participantId": "p-a", "teamRole": "开发工程师 A", "teamId": "team-9"},
        prior_messages=[],
    )
    assert "严格遵循 system 区中的群聊结构化输出合同；不要在 JSON 前后添加说明。" in engineer_prompt
    assert ENGINEER_CONTRACT in engineer_prompt
    assert ENGINEER_FLOW_LINE in engineer_prompt
    assert "不要修改文件" not in engineer_prompt
    assert CONVERGENCE_LINE not in engineer_prompt

    planner_prompt = chat_room_service._build_participant_prompt(
        room=room,
        round_payload=round_payload,
        participant={"participantId": "p-plan", "teamRole": "规划师", "teamId": "team-9"},
        prior_messages=[],
    )
    assert "严格遵循 system 区中的群聊结构化输出合同；不要在 JSON 前后添加说明。" in planner_prompt
    assert PLANNER_FLOW_LINE in planner_prompt
    assert ENGINEER_CONTRACT not in planner_prompt
    assert CONVERGENCE_LINE in planner_prompt

    reviewer_prompt = chat_room_service._build_participant_prompt(
        room=room,
        round_payload=round_payload,
        participant={"participantId": "p-rev", "teamRole": "评审员", "teamId": "team-9"},
        prior_messages=[],
    )
    assert "严格遵循 system 区中的群聊结构化输出合同；不要在 JSON 前后添加说明。" in reviewer_prompt
    assert REVIEWER_FLOW_LINE in reviewer_prompt

    plain_prompt = chat_room_service._build_participant_prompt(
        room={"roomId": "room-plain", "title": "普通群聊", "mode": "round_robin"},
        round_payload={"topic": "随便聊聊", "mode": "round_robin", "purpose": "chat"},
        participant={"participantId": "p-x", "teamRole": "开发工程师 A"},
        prior_messages=[],
    )
    assert "严格遵循 system 区中的群聊结构化输出合同；不要在 JSON 前后添加说明。" in plain_prompt
    assert ENGINEER_CONTRACT not in plain_prompt
    assert ENGINEER_FLOW_LINE not in plain_prompt


def test_board_prompt_marks_the_all_completed_state():
    completed = [
        {
            "id": f"task-{index}",
            "status": "completed",
            "ownerRole": "开发工程师 A",
            "subject": "旧任务",
        }
        for index in (1, 2)
    ]
    text = format_dev_task_board_prompt(completed)
    assert "全部任务已完成" in text

    open_board = [
        *completed,
        {"id": "task-3", "status": "in_progress", "ownerRole": "开发工程师 B", "subject": "还在做"},
    ]
    assert "全部任务已完成" not in format_dev_task_board_prompt(open_board)
    assert "全部任务已完成" not in format_dev_task_board_prompt([])
    assert "全部任务已完成" not in format_dev_task_board_prompt(
        [{"id": "task-4", "status": "rework", "ownerRole": "开发工程师 A", "subject": "退回"}]
    )


def test_room_turn_tool_access_rules():
    # Dev-team turns execute the loop itself: policy tools, structured or not.
    assert chat_room_service._room_turn_tool_access(
        {"devTeamId": "team-9", "_structuredChatRoomContext": True}
    ) == (False, None)
    assert chat_room_service._room_turn_tool_access({"devTeamId": "team-9"}) == (False, None)
    # Every other room stays a tool-less venue; structured rooms keep the reader.
    assert chat_room_service._room_turn_tool_access({"_structuredChatRoomContext": True}) == (
        False,
        ["read_chat_room_context_refs"],
    )
    assert chat_room_service._room_turn_tool_access({}) == (True, None)
    assert chat_room_service._room_turn_tool_access({"devTeamId": "   "}) == (True, None)


def test_dev_task_board_tool_descriptor_does_not_require_approval():
    from core.web.services.tool_catalog import build_tool_descriptor

    descriptor = build_tool_descriptor("dev_task_board_tool", args_schema={"type": "object"})
    assert descriptor.approval == "never"
    assert descriptor.write_scope_gated is False
