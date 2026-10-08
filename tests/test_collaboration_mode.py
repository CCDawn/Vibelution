from types import SimpleNamespace

from core.authorization import collaboration_mode as mode
from core.authorization import tool_authorization_service
from core.web.services import agent_directory_service


def test_plan_mode_denies_writes_and_allows_reads():
    state = mode.entered_plan_state(mode.default_collaboration_state())

    write = mode.check_collaboration_mode(state, "write_file_tool")
    read = mode.check_collaboration_mode(state, "read_file_tool")
    fetch = mode.check_collaboration_mode(state, "web_fetch_tool")
    command = mode.check_collaboration_mode(state, "exec_command")
    plan_list = mode.check_collaboration_mode(state, "plan_update_tool")

    assert write.decision == "deny"
    assert write.rule_id == "mode.plan.nonReadOnly"
    assert read.decision == "allow"
    assert fetch.decision == "allow"
    assert command.decision == "deny"
    assert plan_list.decision == "allow"


def test_plan_flag_beats_yolo_and_auto_is_closed():
    yolo = {"mode": "yolo", "planEnabled": False, "prePlanMode": "build"}
    planned_yolo = {"mode": "yolo", "planEnabled": True, "prePlanMode": "yolo"}
    auto = {"mode": "auto", "planEnabled": False, "prePlanMode": "build"}

    assert mode.check_collaboration_mode(yolo, "write_file_tool").decision == "allow"
    assert mode.check_collaboration_mode(planned_yolo, "write_file_tool").decision == "deny"
    assert mode.check_collaboration_mode(auto, "read_file_tool").rule_id == "mode.auto.unimplemented"


def test_edit_allows_file_edits_and_build_keeps_the_existing_gate():
    edit = {"mode": "edit", "planEnabled": False, "prePlanMode": "build"}
    build = mode.default_collaboration_state()

    assert mode.check_collaboration_mode(edit, "apply_patch_tool").rule_id == "mode.edit.fileEdit"
    assert mode.check_collaboration_mode(edit, "exec_command").decision == "inherit"
    assert mode.check_collaboration_mode(build, "write_file_tool").decision == "inherit"


def test_exit_plan_asks_only_with_a_plan_and_an_open_flag():
    idle = mode.default_collaboration_state()
    active = mode.entered_plan_state(idle)

    assert mode.check_collaboration_mode(idle, mode.EXIT_PLAN_MODE_TOOL, tool_args={"plan": "做"}).decision == "deny"
    assert mode.check_collaboration_mode(active, mode.EXIT_PLAN_MODE_TOOL, tool_args={"plan": "  "}).decision == "deny"
    asked = mode.check_collaboration_mode(active, mode.EXIT_PLAN_MODE_TOOL, tool_args={"plan": "先看再改"})
    assert asked.decision == "ask"
    assert mode.check_collaboration_mode(active, mode.ENTER_PLAN_MODE_TOOL).decision == "allow"


def test_exit_restores_the_mode_from_before_plan():
    entered = mode.entered_plan_state({"mode": "edit", "planEnabled": False, "prePlanMode": "build"})
    left = mode.exited_plan_state(entered)

    assert entered["planEnabled"] is True
    assert entered["prePlanMode"] == "edit"
    assert left["planEnabled"] is False
    assert left["mode"] == "edit"


def test_empty_tool_policy_does_not_gain_plan_controls():
    assert mode.with_collaboration_controls({"allowedTools": []})["allowedTools"] == []
    widened = mode.with_collaboration_controls({
        "allowedTools": ["read_file_tool"],
        "blockedTools": ["exit_plan_mode_tool"],
    })
    assert widened["allowedTools"] == ["read_file_tool", "enter_plan_mode_tool"]


def _runtime(monkeypatch, **collaboration):
    payload = {
        "agentId": "agent-a",
        "turnId": "turn-a",
        "sessionId": "session-a",
        "agentConfigSnapshot": {"configRevision": 1, "configHash": "hash"},
        "permissionPreset": "request_approval",
    }
    if collaboration:
        payload["collaborationMode"] = collaboration
    monkeypatch.setattr(agent_directory_service, "current_agent_runtime", lambda: payload)


def _install(*tools):
    tool_authorization_service.install_execution_authorization(SimpleNamespace(
        decision=SimpleNamespace(
            agent_id="agent-a",
            turn_id="turn-a",
            decision_fingerprint="decision-a",
            executable_tools=tools,
        )
    ))


def test_execution_gate_denies_a_planned_write_without_asking(monkeypatch):
    _runtime(monkeypatch, mode="build", planEnabled=True, prePlanMode="build")
    _install("write_file_tool")
    asked = []
    monkeypatch.setattr(
        "core.web.services.session.tool_approvals.authorize_or_wait",
        lambda **kwargs: asked.append(kwargs),
    )

    result = tool_authorization_service.authorize_tool_execution(
        tool_name="write_file_tool",
        tool_call_id="call-write",
        tool_args={"path": "a.txt"},
    )

    assert result.allowed is False
    assert result.code == "collaboration_mode_denied"
    assert result.rule_id == "mode.plan.nonReadOnly"
    assert asked == []


def test_execution_gate_yolo_skips_approval(monkeypatch):
    _runtime(monkeypatch, mode="yolo", planEnabled=False, prePlanMode="build")
    _install("write_file_tool")
    context = tool_authorization_service.current_execution_authorization()
    context.approval_requirements = (("write_file_tool", "always", "high"),)
    asked = []
    monkeypatch.setattr(
        "core.web.services.session.tool_approvals.authorize_or_wait",
        lambda **kwargs: asked.append(kwargs) or SimpleNamespace(allowed=True, code="approved", message=""),
    )

    result = tool_authorization_service.authorize_tool_execution(
        tool_name="write_file_tool",
        tool_call_id="call-yolo",
        tool_args={},
    )

    assert result.allowed is True
    assert asked == []


def test_execution_gate_asks_before_leaving_plan(monkeypatch):
    _runtime(monkeypatch, mode="build", planEnabled=True, prePlanMode="build")
    _install("exit_plan_mode_tool")
    asked = []
    monkeypatch.setattr(
        "core.web.services.session.tool_approvals.authorize_or_wait",
        lambda **kwargs: asked.append(kwargs["tool_name"]) or SimpleNamespace(allowed=True, code="approved", message=""),
    )

    result = tool_authorization_service.authorize_tool_execution(
        tool_name="exit_plan_mode_tool",
        tool_call_id="call-exit",
        tool_args={"plan": "先看再改"},
    )

    assert result.allowed is True
    assert asked == ["exit_plan_mode_tool"]


def test_exit_tool_saves_the_plan_then_clears_the_flag(monkeypatch, tmp_path):
    from tools import plan_tools

    monkeypatch.setattr(plan_tools, "_current_session_id", lambda: "session a")
    monkeypatch.setattr(plan_tools, "_workspace_root", lambda: tmp_path)
    monkeypatch.setattr(plan_tools, "plan_is_enabled", lambda _state: True, raising=False)
    saved = {}

    def leave(session_id):
        saved["session"] = session_id
        return {"mode": "build", "previousMode": "build", "planEnabled": False, "previousPlanEnabled": True}

    monkeypatch.setattr(
        "core.web.services.session.collaboration_mode.load_collaboration_state",
        lambda _session_id: {"planEnabled": True},
    )
    monkeypatch.setattr(
        "core.web.services.session.collaboration_mode.exit_session_plan_mode",
        leave,
    )

    import json
    payload = json.loads(plan_tools.exit_plan_mode_tool("先看再改"))

    assert payload["approved"] is True
    assert payload["mode"] == "build"
    assert saved["session"] == "session a"
    written = (tmp_path / ".vibelution" / "plans" / "plan-session-a.md").read_text(encoding="utf-8")
    assert written == "先看再改"
