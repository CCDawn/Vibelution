import json

from core.web.services.session.tool_approvals import _arguments_hash, _assistant_management_summary


def _arguments(values):
    return {"action": "project_lifecycle", "arguments_json": json.dumps(values)}


def test_lifecycle_approval_binds_and_displays_the_complete_operation(monkeypatch):
    monkeypatch.setattr("core.infrastructure.native_runtime.is_launcher_assistant_process", lambda: True)
    values = {"project_id": "project:1", "operation": "start", "request_id": "request-1"}
    assert _assistant_management_summary(_arguments(values)) == {
        "assistantAction": "project_lifecycle", "assistantTargets": values,
    }
    for key, replacement in (("project_id", "other"), ("operation", "stop"), ("request_id", "other")):
        assert _arguments_hash(_arguments(values)) != _arguments_hash(_arguments({**values, key: replacement}))


def test_lifecycle_approval_rejects_invalid_and_non_launcher_requests(monkeypatch):
    values = {"project_id": "project:1", "operation": "start", "request_id": "request-1"}
    monkeypatch.setattr("core.infrastructure.native_runtime.is_launcher_assistant_process", lambda: False)
    assert _assistant_management_summary(_arguments(values))["assistantArgumentsInvalid"]
    monkeypatch.setattr("core.infrastructure.native_runtime.is_launcher_assistant_process", lambda: True)
    for invalid in ({**values, "force": True}, {**values, "operation": "force-stop"},
                    {**values, "project_id": "project\nforged"}, {**values, "request_id": "x" * 129},
                    {key: value for key, value in values.items() if key != "request_id"}):
        assert _assistant_management_summary(_arguments(invalid))["assistantArgumentsInvalid"]
