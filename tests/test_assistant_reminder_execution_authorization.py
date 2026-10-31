from types import SimpleNamespace

import pytest

from core.authorization import tool_authorization_service
from core.infrastructure import native_runtime, tool_executor as tool_executor_module
from core.infrastructure.tool_executor import ToolExecutor
from core.web.services import agent_directory_service
from core.web.services.external_agent import approval_binding
from core.web.services.session import tool_approvals


TOOL = "personal_assistant_manage_tool"
RECOVERY_ARGS = {
    "action": "reminder_handoff_recover",
    "arguments_json": '{"project_id":"project-a","preview_id":"preview-a"}',
}


@pytest.fixture
def execution(monkeypatch):
    runtime = {
        "agentId": "agent-a",
        "turnId": "turn-a",
        "sessionId": "session-a",
        "agentConfigSnapshot": {"configRevision": 1, "configHash": "hash-a"},
        "permissionPreset": "request_approval",
        "collaborationMode": {"mode": "yolo", "planEnabled": False, "prePlanMode": "build"},
    }
    monkeypatch.setattr(agent_directory_service, "current_agent_runtime", lambda: runtime)
    monkeypatch.setattr(approval_binding, "registered_external_task", lambda **kwargs: "")
    monkeypatch.setattr(tool_executor_module, "_record_tool_scene_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(tool_executor_module, "_record_current_agent_tool_observation", lambda *args, **kwargs: None)
    monkeypatch.setattr(tool_authorization_service, "_record_execution_denial_reason", lambda **kwargs: None)
    tool_authorization_service.install_execution_authorization(SimpleNamespace(
        decision=SimpleNamespace(
            agent_id="agent-a", turn_id="turn-a", decision_fingerprint="decision-a",
            executable_tools=(TOOL,),
        ),
    ))
    context = tool_authorization_service.current_execution_authorization()
    context.approval_requirements = ((TOOL, "always", "high"),)
    yield runtime
    tool_authorization_service.clear_execution_authorization()


def _executor(calls):
    executor = ToolExecutor()
    executor.register_tool(TOOL, lambda **kwargs: calls.append(kwargs) or "executed")
    return executor


def test_native_recovery_yolo_requires_destructive_approval_before_execution(monkeypatch, execution):
    monkeypatch.setattr(native_runtime, "is_launcher_assistant_process", lambda: True)
    asked = []
    monkeypatch.setattr(
        tool_approvals, "authorize_or_wait",
        lambda **kwargs: asked.append(kwargs) or SimpleNamespace(
            allowed=False, code="declined", message="operator declined",
        ),
    )
    calls = []

    result, action = _executor(calls).execute(TOOL, RECOVERY_ARGS, tool_call_id="call-recovery")

    assert (result, action) == ("operator declined", None)
    assert calls == []
    assert len(asked) == 1
    assert asked[0]["approval"] == "always"
    assert asked[0]["risk"] == "destructive"
    assert asked[0]["call_id"] == "call-recovery"
    assert asked[0]["tool_name"] == TOOL
    assert asked[0]["tool_args"] == RECOVERY_ARGS


def test_native_recovery_plan_denies_before_approval(monkeypatch, execution):
    execution["collaborationMode"]["planEnabled"] = True
    monkeypatch.setattr(native_runtime, "is_launcher_assistant_process", lambda: True)
    asked = []
    monkeypatch.setattr(tool_approvals, "authorize_or_wait", lambda **kwargs: asked.append(kwargs))

    decision = tool_authorization_service.authorize_tool_execution(
        tool_name=TOOL, tool_call_id="call-plan", tool_args=RECOVERY_ARGS,
    )
    calls = []
    result, action = _executor(calls).execute(TOOL, RECOVERY_ARGS, tool_call_id="call-plan-executor")

    assert decision.allowed is False
    assert decision.code == "collaboration_mode_denied"
    assert decision.rule_id == "mode.plan.nonReadOnly"
    assert result == decision.message
    assert action is None
    assert asked == []
    assert calls == []


@pytest.mark.parametrize(
    ("native", "args"),
    [
        (False, RECOVERY_ARGS),
        (True, {"action": "reminder_handoff_receipt", "arguments_json": "{}"}),
    ],
    ids=("non-launcher-recovery", "launcher-other-action"),
)
def test_other_yolo_paths_keep_existing_automatic_execution(monkeypatch, execution, native, args):
    monkeypatch.setattr(native_runtime, "is_launcher_assistant_process", lambda: native)
    asked = []
    monkeypatch.setattr(tool_approvals, "authorize_or_wait", lambda **kwargs: asked.append(kwargs))
    calls = []

    result, action = _executor(calls).execute(TOOL, args, tool_call_id="call-ordinary")

    assert (result, action) == ("executed", None)
    assert calls == [args]
    assert asked == []
