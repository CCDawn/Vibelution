"""Native platform controls must retain their original task and owner binding."""
import asyncio

import pytest

from core.assistant_runtime.actions import bind_actions, execute_action, unbind_actions
from core.assistant_runtime.dispatch import DispatchError
from tests.test_assistant_runtime_dispatch import ClientProbe, adapter, start


@pytest.mark.anyio
async def test_dispatch_cancel_is_discoverable_governed_and_preserves_native_result(tmp_path):
    probe = ClientProbe()
    service = adapter(tmp_path, probe)
    await start(service)
    bind_actions(service, asyncio.get_running_loop())
    parameters = {"project_id": "project-a", "dispatch_id": "dispatch-1", "native_task_id": "eat-1"}
    try:
        contract = execute_action("describe", {"action": "dispatch_cancel"})
        assert contract["governed"] is True and "停止" in contract["description"]
        denied = await asyncio.to_thread(execute_action, "dispatch_cancel", parameters)
        assert denied["status"] == "approval_required"
        assert not any(name == "cancel" for name, _ in probe.calls)
        result = await asyncio.to_thread(execute_action, "dispatch_cancel", parameters,
                                         runtime={"agentId": "assistant", "sessionId": "own"}, governed=True)
        assert result["nativeTaskId"] == "eat-1" and result["receipt"]["status"] == "stop_unconfirmed"
        assert [args for name, args in probe.calls if name == "cancel"] == [{"task_id": "eat-1"}]
    finally:
        unbind_actions(service)


@pytest.mark.anyio
async def test_dispatch_cancel_rejects_stale_identity_before_any_native_write(tmp_path):
    probe = ClientProbe()
    service = adapter(tmp_path, probe)
    await start(service)
    for project, task in (("other-project", "eat-1"), ("project-a", "other-task")):
        with pytest.raises(DispatchError, match="changed"):
            await service.cancel("dispatch-1", project_id=project, expected_task_id=task)
    assert not any(name == "cancel" for name, _ in probe.calls)
