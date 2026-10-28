import json

import pytest
from pydantic import ValidationError

from core.assistant_runtime.dispatch_approval import DispatchWrite
from core.web.services.session.tool_approvals import _arguments_hash, _assistant_management_summary


def _arguments(values):
    return {"action": "dispatch_write", "arguments_json": json.dumps(values, ensure_ascii=False)}


def test_write_approval_shows_full_bound_task_identity_and_requested_permission(monkeypatch):
    monkeypatch.setattr("core.infrastructure.native_runtime.is_launcher_assistant_process", lambda: True)
    values = {"project_id": "project:1", "agent_id": "coder-1", "dispatch_id": "request-1",
              "task": "修改文件\n保留其他内容。"}
    args = _arguments(values)
    assert _assistant_management_summary(args) == {
        "assistantAction": "dispatch_write",
        "assistantTargets": {"project_id": "project:1", "agent_id": "coder-1", "dispatch_id": "request-1"},
        "assistantRequestedPermission": "workspace_write", "assistantTask": values["task"],
    }
    for field, changed in (("project_id", "other"), ("agent_id", "other"),
                           ("dispatch_id", "other"), ("task", "修改别的文件")):
        assert _arguments_hash(args) != _arguments_hash(_arguments({**values, field: changed}))


def test_write_approval_rejects_unsafe_incomplete_and_model_permission_fields(monkeypatch):
    values = {"project_id": "project:1", "agent_id": "coder-1", "dispatch_id": "request-1", "task": "修改文件"}
    monkeypatch.setattr("core.infrastructure.native_runtime.is_launcher_assistant_process", lambda: False)
    assert _assistant_management_summary(_arguments(values))["assistantArgumentsInvalid"]
    monkeypatch.setattr("core.infrastructure.native_runtime.is_launcher_assistant_process", lambda: True)
    for invalid in ({**values, "permission_profile": "full_access"},
                    {**values, "agent_id": "agent\nother"}, {**values, "task": "修改\u202efile"},
                    {**values, "task": " 修改文件"}, {**values, "task": "x" * 12001},
                    {key: value for key, value in values.items() if key != "task"}):
        assert _assistant_management_summary(_arguments(invalid))["assistantArgumentsInvalid"]
        with pytest.raises(ValidationError):
            DispatchWrite.model_validate(invalid)
