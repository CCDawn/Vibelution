"""Agent archival approvals must show the exact closed executable target."""
import json

import pytest

from core.web.services.session.tool_approvals import _assistant_management_summary


PARAMETERS = {"project_id": "registered:1", "request_id": "archive-1", "agent_id": "agent-1",
              "expected_config_revision": 9007199254740993}


def test_archive_preview_keeps_project_request_and_exact_revision(monkeypatch):
    monkeypatch.setattr("core.infrastructure.native_runtime.is_launcher_assistant_process", lambda: True)
    result = _assistant_management_summary({"action": "agent_archive", "arguments_json": json.dumps(PARAMETERS)})
    assert result["assistantTargets"] == {**PARAMETERS, "expected_config_revision": "9007199254740993"}
    assert result.get("assistantDetailsOmitted") is not True
    assert not result.get("assistantArgumentsInvalid")
    assert "assistantPurgeIrreversible" not in result


@pytest.mark.parametrize("change", [{"force": True}, {"approved": True}, {"agent_id": "bad\nagent"},
    {"project_id": "bad\u202eproject"}, {"expected_config_revision": True},
    {"expected_config_revision": "3"}, {"request_id": "bad.request"}])
def test_archive_preview_rejects_unreviewable_or_open_request(monkeypatch, change):
    monkeypatch.setattr("core.infrastructure.native_runtime.is_launcher_assistant_process", lambda: True)
    result = _assistant_management_summary({"action": "agent_archive",
        "arguments_json": json.dumps({**PARAMETERS, **change})})
    assert result == {"assistantAction": "agent_archive", "assistantArgumentsInvalid": True}


def test_archive_preview_keeps_ordinary_adapter_projection_unchanged(monkeypatch):
    monkeypatch.setattr("core.infrastructure.native_runtime.is_launcher_assistant_process", lambda: False)
    result = _assistant_management_summary({"action": "agent_archive", "arguments_json": json.dumps(PARAMETERS)})
    assert result["assistantTargets"] == {"agent_id": "agent-1"}
    assert result["assistantDetailsOmitted"] is True
