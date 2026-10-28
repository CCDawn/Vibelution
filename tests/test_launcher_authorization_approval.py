import json
import asyncio

import pytest

from core.web.services.session.tool_approvals import _assistant_management_summary


def _summary(values):
    return _assistant_management_summary({
        "action": "authorization_upgrade",
        "arguments_json": json.dumps(values),
    })


def test_launcher_authorization_preview_identifies_project_and_every_added_scope(monkeypatch):
    monkeypatch.setattr("core.infrastructure.native_runtime.is_launcher_assistant_process", lambda: True)
    result = _summary({
        "project_id": "registered:1",
        "request_id": "request-1",
        "expected_scopes": ["agents:read"],
        "add_scopes": ["source:read", "tasks:read"],
    })
    assert result["assistantAction"] == "authorization_upgrade"
    assert result["assistantTargets"]["project_id"] == "registered:1"
    assert result["assistantAddedScopes"] == ["source:read", "tasks:read"]
    assert not result.get("assistantArgumentsInvalid")


def test_authorization_preview_fails_closed_for_invalid_input_and_other_process(monkeypatch):
    values = {"project_id": "registered:1", "request_id": "request-1",
              "expected_scopes": ["agents:read"], "add_scopes": ["tasks:read"]}
    monkeypatch.setattr("core.infrastructure.native_runtime.is_launcher_assistant_process", lambda: False)
    assert _summary(values)["assistantArgumentsInvalid"] is True
    monkeypatch.setattr("core.infrastructure.native_runtime.is_launcher_assistant_process", lambda: True)
    for invalid in ({**values, "approved": True}, {**values, "add_scopes": ["tasks:read", "source:read"]},
                    {**values, "project_id": "bad\nproject"}):
        assert _summary(invalid)["assistantArgumentsInvalid"] is True


@pytest.mark.anyio
async def test_governed_upgrade_refuses_project_id_that_cannot_be_displayed(tmp_path):
    from core.assistant_runtime.actions import bind_actions, execute_action, unbind_actions
    from core.assistant_runtime.dispatch import DispatchService

    project_id = "bad\nproject"
    service = DispatchService(tmp_path / "profile", {project_id: tmp_path / "project"})
    bind_actions(service, asyncio.get_running_loop())
    try:
        with pytest.raises(ValueError, match="cannot be displayed safely"):
            await asyncio.to_thread(execute_action, "authorization_upgrade", {
                "project_id": project_id, "request_id": "request-1",
                "expected_scopes": ["agents:read"], "add_scopes": ["tasks:read"],
            }, governed=True)
    finally:
        unbind_actions(service)
