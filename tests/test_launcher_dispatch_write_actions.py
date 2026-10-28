import asyncio

import pytest

from core.assistant_runtime import actions


class _Service:
    def __init__(self, effective="read_only"):
        self.calls = []
        self.effective = effective

    def project_ids(self):
        return ("project-a",)

    async def dispatch_write_from_source(self, project_id, **kwargs):
        self.calls.append((project_id, kwargs))
        return {"dispatchId": kwargs["dispatch_id"], "receipt": {"effectivePermissionProfile": self.effective}}


@pytest.mark.anyio
async def test_write_action_requires_governed_tool_and_reports_target_ceiling():
    service = _Service()
    runtime = {"agentId": "assistant", "sessionId": "session", "turnId": "turn"}
    args = {"project_id": "project-a", "agent_id": "coder", "dispatch_id": "request-a", "task": "修改文件"}
    actions.bind_actions(service, asyncio.get_running_loop())
    try:
        contract = await asyncio.to_thread(actions.execute_action, "describe", {"action": "dispatch_write"})
        assert contract["governed"] is True
        assert "permission_profile" not in contract["parameters"]["properties"]
        blocked = await asyncio.to_thread(actions.execute_action, "dispatch_write", args, runtime=runtime)
        assert blocked["status"] == "approval_required" and service.calls == []
        result = await asyncio.to_thread(actions.execute_action, "dispatch_write", args, runtime=runtime, governed=True)
        assert service.calls == [("project-a", {"agent_id": "coder", "dispatch_id": "request-a", "task": "修改文件", "runtime": runtime})]
        assert result["receipt"]["effectivePermissionProfile"] == "read_only"
        assert "只读" in result["permissionNotice"]
        with pytest.raises(ValueError, match="schema"):
            await asyncio.to_thread(actions.execute_action, "dispatch_write", {**args, "permission_profile": "full_access"}, runtime=runtime, governed=True)
        too_long = await asyncio.to_thread(actions.execute_action, "dispatch_write", {**args, "task": "x" * 12001}, runtime=runtime, governed=True)
        assert too_long["code"] == "TASK_SOURCE_TOO_LONG"
        assert len(service.calls) == 1
    finally:
        actions.unbind_actions(service)


@pytest.mark.anyio
@pytest.mark.parametrize("message,task", [
    ("不要修改文件", "修改文件"),
    ("修改文件，但不要提交", "修改文件"),
])
async def test_governed_write_rejects_partial_original_message_before_native_start(tmp_path, monkeypatch, message, task):
    from core.assistant_runtime import native
    from tests.test_assistant_runtime_dispatch import ClientProbe, adapter

    runtime = {"agentId": "assistant", "sessionId": "session", "turnId": "turn"}
    monkeypatch.setattr(native, "read_task_source", lambda caller, source_ref=None: {
        **runtime, "eventId": "event-a", "content": message,
    })
    probe = ClientProbe()
    service = adapter(tmp_path, probe)
    args = {"project_id": "project-a", "agent_id": "coder", "dispatch_id": "request-a", "task": task}
    actions.bind_actions(service, asyncio.get_running_loop())
    try:
        result = await asyncio.to_thread(actions.execute_action, "dispatch_write", args, runtime=runtime, governed=True)
        assert result["code"] == "TASK_SOURCE_MISMATCH"
        assert probe.calls == [] and not service._path("request-a").exists()
    finally:
        actions.unbind_actions(service)


@pytest.mark.anyio
async def test_preview_and_governed_dispatch_share_complete_message(tmp_path, monkeypatch):
    import json
    from core.assistant_runtime import native
    from core.web.services.session.tool_approvals import _assistant_management_summary
    from tests.test_assistant_runtime_dispatch import ClientProbe, adapter

    monkeypatch.setattr("core.infrastructure.native_runtime.is_launcher_assistant_process", lambda: True)
    runtime = {"agentId": "assistant", "sessionId": "session", "turnId": "turn"}
    task = "修改文件，但不要提交"
    monkeypatch.setattr(native, "read_task_source", lambda caller, source_ref=None: {
        **runtime, "eventId": "event-a", "content": " \n" + task + " \n",
    })
    args = {"project_id": "project-a", "agent_id": "coder", "dispatch_id": "request-a", "task": task}
    summary = _assistant_management_summary({"action": "dispatch_write", "arguments_json": json.dumps(args, ensure_ascii=False)})
    probe = ClientProbe()
    service = adapter(tmp_path, probe)
    actions.bind_actions(service, asyncio.get_running_loop())
    try:
        await asyncio.to_thread(actions.execute_action, "dispatch_write", args, runtime=runtime, governed=True)
        sent = next(kwargs for name, kwargs in probe.calls if name == "start")
        assert summary["assistantTask"] == sent["task"] == task
        assert summary["assistantTargets"] == {"project_id": "project-a", "agent_id": "coder", "dispatch_id": "request-a"}
        assert summary["assistantRequestedPermission"] == sent["permission_profile"] == "workspace_write"
    finally:
        actions.unbind_actions(service)
