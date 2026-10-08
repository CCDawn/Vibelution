import json
import os
from pathlib import Path

import pytest

from core.infrastructure import git_process
from core.web.services import (
    agent_directory_service,
    chat_room_service,
    session_service,
    team_service,
    team_template_service,
)
from core.web.services.team.dev_task_board import ensure_dev_task_workspace
from tools.dev_task_board_tools import (
    _untracked_head,
    dev_task_board_tool,
)
from tests.helpers.system_agent_state import _mark_config_agent_instances_present


_RUNTIME: dict = {"agentId": ""}


def _fake_current_agent_runtime() -> dict:
    return dict(_RUNTIME)


@pytest.fixture()
def dev_team(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Seeded repo + one instantiated dev-team. Returns {team, agentByRole}."""

    for key in list(os.environ):
        if key.startswith("GIT_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    _seed_main_repo(tmp_path, monkeypatch)

    for service in (agent_directory_service, chat_room_service, session_service, team_service, team_template_service):
        monkeypatch.setattr(service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(agent_directory_service, "current_agent_runtime", _fake_current_agent_runtime)
    _RUNTIME.clear()

    _mark_config_agent_instances_present()
    created = team_template_service.instantiate_team_template("dev-team", name="工具化任务板")
    team = created["team"]
    agent_by_role = {member["role"]: member["agentId"] for member in team["members"]}
    member_by_role = {member["role"]: member["memberId"] for member in team["members"]}
    return {
        "team": team,
        "teamId": team["teamId"],
        "agentByRole": agent_by_role,
        "memberByRole": member_by_role,
        "root": tmp_path,
    }


def _as(role: str, env: dict) -> None:
    _RUNTIME["agentId"] = env["agentByRole"].get(role, "")


def _call(**kwargs) -> dict:
    return json.loads(dev_task_board_tool(**kwargs))


def _create_task(env: dict, team_id: str, **overrides) -> dict:
    payload = {"action": "create_task", "team_id": team_id, "subject": "拆出登录按钮", "description": "只改文案"}
    payload.update(overrides)
    _as("规划师", env)
    return _call(**payload)


def _claim(env: dict, team_id: str, task_id: str, revision: int) -> dict:
    _as("开发工程师 A", env)
    return _call(action="claim_task", team_id=team_id, task_id=task_id, expected_revision=revision)


def test_planner_create_and_update_but_cannot_claim_or_close(dev_team):
    env = dev_team
    created = _create_task(env, env["teamId"])
    assert created["status"] == "ok"
    assert created["taskId"] == "task-1"
    assert created["taskStatus"] == "pending"
    assert created["revision"] == 1

    _as("规划师", env)
    updated = _call(
        action="update_task",
        team_id=env["teamId"],
        task_id="task-1",
        expected_revision=1,
        subject="新主题",
        write_scopes=["web/src/routes/login"],
    )
    assert updated["status"] == "ok"
    assert updated["subject"] == "新主题"
    assert updated["revision"] == 2

    for action in ("claim_task", "complete_task", "rework_task"):
        denied = _call(action=action, team_id=env["teamId"], task_id="task-1", expected_revision=2)
        assert denied["status"] == "error", action
        assert denied["code"] == "ROLE_DENIED", action


def test_engineer_can_only_claim_and_read_is_denied(dev_team):
    env = dev_team
    _create_task(env, env["teamId"])
    _as("开发工程师 A", env)

    for action in ("create_task", "complete_task", "rework_task"):
        kwargs = {"action": action, "team_id": env["teamId"], "task_id": "task-1", "expected_revision": 1}
        if action == "create_task":
            kwargs = {"action": action, "team_id": env["teamId"], "subject": "工程师建任务"}
        denied = _call(**kwargs)
        assert denied["status"] == "error", action
        assert denied["code"] == "ROLE_DENIED", action

    read_denied = _call(action="read_task_changes", team_id=env["teamId"], task_id="task-1")
    assert read_denied["status"] == "error"
    assert read_denied["code"] == "ROLE_DENIED"
    assert "规划师与评审员" in read_denied["message"]

    claimed = _claim(env, env["teamId"], "task-1", 1)
    assert claimed["status"] == "ok"
    assert claimed["taskStatus"] == "in_progress"
    assert claimed["revision"] == 2
    assert claimed["workspacePath"].startswith(".worktrees/")
    assert claimed["workspaceBranch"].startswith("codex/dev-")
    worktree = env["root"] / claimed["workspacePath"]
    assert (worktree / ".git").exists()


def test_claim_reuses_apply_claim_with_workspace_and_second_engineer_is_blocked(dev_team):
    env = dev_team
    _as("规划师", env)
    created = _call(
        action="create_task",
        team_id=env["teamId"],
        subject="指派给 A",
        owner_member_id=env["memberByRole"]["开发工程师 A"],
    )
    assert created["ownerMemberId"] == env["memberByRole"]["开发工程师 A"]

    _as("开发工程师 B", env)
    blocked = _call(action="claim_task", team_id=env["teamId"], task_id="task-1", expected_revision=1)
    assert blocked["status"] == "error"
    assert blocked["code"] == "BOARD_REJECTED"
    assert "已经有负责人" in blocked["message"]


def test_reviewer_completes_and_reworks_with_stale_revision_passthrough(dev_team):
    env = dev_team
    _create_task(env, env["teamId"])
    claimed = _claim(env, env["teamId"], "task-1", 1)
    assert claimed["revision"] == 2

    _as("评审员", env)
    stale = _call(
        action="complete_task",
        team_id=env["teamId"],
        task_id="task-1",
        expected_revision=1,
        review_note="早了",
    )
    assert stale["status"] == "error"
    assert stale["code"] == "STALE_REVISION"
    assert "任务版本已变" in stale["message"]

    for action, code in (("create_task", "ROLE_DENIED"), ("claim_task", "ROLE_DENIED"), ("update_task", "ROLE_DENIED")):
        kwargs = {"action": action, "team_id": env["teamId"], "task_id": "task-1", "expected_revision": 2}
        if action == "create_task":
            kwargs = {"action": action, "team_id": env["teamId"], "subject": "评审员建任务"}
        denied = _call(**kwargs)
        assert denied["code"] == code, action

    reworked = _call(
        action="rework_task",
        team_id=env["teamId"],
        task_id="task-1",
        expected_revision=2,
        review_note="补测试再提审",
    )
    assert reworked["status"] == "ok"
    assert reworked["taskStatus"] == "rework"
    assert reworked["revision"] == 3

    _as("开发工程师 A", env)
    reclaimed = _call(action="claim_task", team_id=env["teamId"], task_id="task-1", expected_revision=3)
    assert reclaimed["revision"] == 4

    _as("评审员", env)
    completed = _call(
        action="complete_task",
        team_id=env["teamId"],
        task_id="task-1",
        expected_revision=4,
        review_note="通过",
    )
    assert completed["status"] == "ok"
    assert completed["taskStatus"] == "completed"
    assert completed["reviewNote"] == "通过"


def test_non_member_and_missing_context_fail_closed(dev_team):
    env = dev_team
    _RUNTIME.clear()
    no_context = _call(action="read_task_changes", team_id=env["teamId"], task_id="task-1")
    assert no_context["status"] == "error"
    assert no_context["code"] == "NO_AGENT_CONTEXT"

    _RUNTIME["agentId"] = "agent-outsider"
    outsider = _call(action="create_task", team_id=env["teamId"], subject="外人建任务")
    assert outsider["status"] == "error"
    assert outsider["code"] == "NOT_TEAM_MEMBER"

    _as("规划师", env)
    missing_team = _call(action="create_task", team_id="team-nope", subject="投错板")
    assert missing_team["status"] == "error"
    assert missing_team["code"] == "TEAM_NOT_FOUND"


def test_invalid_action_and_missing_revision_are_actionable(dev_team):
    env = dev_team
    _as("规划师", env)
    invalid = _call(action="delete_task", team_id=env["teamId"], task_id="task-1")
    assert invalid["code"] == "INVALID_ACTION"
    assert "delete_task" not in invalid["message"]

    created = _create_task(env, env["teamId"])
    _as("开发工程师 A", env)
    missing = _call(action="claim_task", team_id=env["teamId"], task_id=created["taskId"])
    assert missing["code"] == "MISSING_REVISION"


def test_read_changes_returns_bounded_diffs_with_untracked_label(dev_team):
    env = dev_team
    _create_task(env, env["teamId"])
    claimed = _claim(env, env["teamId"], "task-1", 1)
    worktree = env["root"] / claimed["workspacePath"]

    big = "\n".join(f"line-{index:03d} 原有内容" for index in range(1, 51))
    (worktree / "README.md").write_text(big + "\n", encoding="utf-8")
    tracked_big = worktree / "src" / "big.py"
    tracked_big.parent.mkdir(parents=True)
    tracked_big.write_text("\n".join(f"print({index})  # 改过的长文件" for index in range(300)) + "\n", encoding="utf-8")
    untracked_small = worktree / "notes" / "todo.md"
    untracked_small.parent.mkdir(parents=True)
    untracked_small.write_text("第一行\n第二行\n", encoding="utf-8")

    _as("评审员", env)
    read = _call(action="read_task_changes", team_id=env["teamId"], task_id="task-1")
    assert read["status"] == "ok"
    assert read["available"] is True
    by_path = {item["path"]: item for item in read["changes"]}

    readme = by_path["README.md"]
    assert readme["status"] == "modified"
    assert "-line-001 原有内容" in readme["diff"] or "-seed" in readme["diff"]
    assert readme["diffTruncated"] is False

    big_change = by_path["src/big.py"]
    assert big_change["status"] == "untracked"
    assert big_change["note"].startswith("未跟踪")
    assert big_change["diff"].splitlines()[0].startswith("print(0)")
    assert big_change["diffTruncated"] is True

    todo = by_path["notes/todo.md"]
    assert todo["status"] == "untracked"
    assert "未跟踪" in todo["note"]
    assert todo["diff"] == "第一行\n第二行"

    assert read["diffBudget"]["usedLines"] <= read["diffBudget"]["totalLines"]
    assert read["diffBudget"]["perFileLines"] == 200


def test_read_changes_budget_caps_total_lines_across_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    for key in list(os.environ):
        if key.startswith("GIT_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    _seed_main_repo(tmp_path, monkeypatch)
    opened = ensure_dev_task_workspace(team_id="team-1", task_id="task-1", member_id="m-a", project_root=tmp_path)
    directory = tmp_path / opened["workspacePath"]
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}

    for index in range(6):
        target = directory / f"file-{index}.txt"
        target.write_text("seed\n", encoding="utf-8")
        _git(directory, ["add", f"file-{index}.txt"], env=env)
    _git(directory, ["commit", "-m", "track six files"], env=env)

    from tools.dev_task_board_tools import _bounded_diff

    budget = {"used": 0, "exhausted": False}
    for index in range(6):
        target = directory / f"file-{index}.txt"
        target.write_text("\n".join(f"changed-{line}" for line in range(300)) + "\n", encoding="utf-8")
        body, truncated, note = _bounded_diff(directory, f"file-{index}.txt", "modified", budget)
        if index < 4:
            assert len(body.splitlines()) == 200, index
            assert truncated is True, index
        else:
            assert body == "", index
            assert truncated is True, index
            assert "总量" in note, index
    assert budget["used"] == 800


def test_untracked_head_never_reads_outside_the_worktree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _seed_main_repo(tmp_path, monkeypatch)
    opened = ensure_dev_task_workspace(team_id="team-1", task_id="task-1", member_id="m-a", project_root=tmp_path)
    directory = tmp_path / opened["workspacePath"]
    secret = tmp_path / "secret.md"
    secret.write_text("机密\n", encoding="utf-8")

    from tools.dev_task_board_tools import _bounded_diff

    budget = {"used": 0, "exhausted": False}
    body, truncated, note = _bounded_diff(directory, "../secret.md", "untracked", budget)
    assert body == ""
    assert truncated is True
    assert "路径越出" in note
    assert budget["used"] == 0


def test_read_changes_reports_missing_workspace_without_raising(dev_team):
    env = dev_team
    _create_task(env, env["teamId"])
    _as("评审员", env)
    read = _call(action="read_task_changes", team_id=env["teamId"], task_id="task-1")
    assert read["status"] == "ok"
    assert read["workspace"] is False
    assert read["changes"] == []
    assert "没有工作区" in read["message"]

    missing = _call(action="read_task_changes", team_id=env["teamId"], task_id="task-99")
    assert missing["status"] == "error"
    assert missing["code"] == "TASK_NOT_FOUND"


# --- helpers ----------------------------------------------------------------


def _seed_main_repo(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("GIT_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    hooks = path / "_hooks"
    hooks.mkdir(exist_ok=True)
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    _git(path, ["init", "-b", "main"], env=env)
    _git(path, ["config", "user.name", "Vibelution Test"], env=env)
    _git(path, ["config", "user.email", "test@example.invalid"], env=env)
    _git(path, ["config", "core.hooksPath", str(hooks)], env=env)
    (path / "README.md").write_text("seed\n", encoding="utf-8")
    _git(path, ["add", "README.md"], env=env)
    _git(path, ["commit", "-m", "seed"], env=env)


def _git(cwd: Path, args: list, env: dict | None = None) -> str:
    result = git_process.run_git(
        args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return str(result.stdout or "")


def test_instantiated_developer_agents_run_with_full_access(dev_team):
    for role in ("开发工程师 A", "开发工程师 B"):
        agent = agent_directory_service.get_agent(dev_team["agentByRole"][role])
        assert str(agent.get("permissionPreset") or "") == "full_access", role
    for role in ("规划师", "评审员"):
        agent = agent_directory_service.get_agent(dev_team["agentByRole"][role])
        assert str(agent.get("permissionPreset") or "") != "full_access", role
