import json

import pytest

from core.infrastructure import native_runtime
from core.web.services.external_management.contracts import contracts
from core.web.services.session.tool_approvals import _assistant_management_summary


def test_creation_contract_explains_zero_tool_and_dispatch_limit():
    description = contracts()["agent_create"]["description"]
    assert "不授予任何工具或读写范围" in description
    assert "派遣写任务也不会自动增加工具权限" in description


def test_launcher_creation_approval_explains_actual_capability(monkeypatch):
    monkeypatch.setattr(native_runtime, "is_launcher_assistant_process", lambda: True)
    values = {"project_id": "project-1", "request_id": "create-1", "display_name": "Worker", "model_id": "model-1"}
    summary = _assistant_management_summary({"action": "agent_create", "arguments_json": json.dumps(values)})
    assert summary["assistantTargets"] == {"project_id": "project-1", "display_name": "Worker", "model_id": "model-1"}
    assert "没有工具和读写范围" in summary["assistantOperationDescription"]
    assert "派遣写任务不会自动增加工具权限" in summary["assistantOperationDescription"]


def test_launcher_creation_approval_accepts_120_unicode_code_points(monkeypatch):
    monkeypatch.setattr(native_runtime, "is_launcher_assistant_process", lambda: True)
    values = {"project_id": "project-1", "request_id": "create-1", "display_name": "😀" * 120, "model_id": "m" * 200}
    summary = _assistant_management_summary({"action": "agent_create", "arguments_json": json.dumps(values)})
    assert summary["assistantTargets"]["display_name"] == values["display_name"]
    assert summary["assistantTargets"]["model_id"] == values["model_id"]


@pytest.mark.parametrize("change", [
    {"project_id": "project\nforged"}, {"display_name": "worker\u202eforged"}, {"model_id": "model\u202eforged"},
    {"toolPolicy": {"allowedTools": ["write_file_tool"]}},
])
def test_invalid_creation_approval_fails_closed(monkeypatch, change):
    monkeypatch.setattr(native_runtime, "is_launcher_assistant_process", lambda: True)
    values = {"project_id": "project-1", "request_id": "create-1", "display_name": "Worker", "model_id": "model-1", **change}
    summary = _assistant_management_summary({"action": "agent_create", "arguments_json": json.dumps(values)})
    assert summary == {"assistantAction": "agent_create", "assistantArgumentsInvalid": True}
