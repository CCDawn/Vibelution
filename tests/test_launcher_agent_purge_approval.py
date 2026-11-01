"""Purge approval shows the exact executable identity without private data."""
import json

import pytest

from core.assistant_runtime.actions import agent_purge_approval_summary
from core.web.services.session.tool_approvals import _assistant_management_summary

PARAMETERS = {"project_id": "registered:1", "request_id": "purge-1", "agent_id": "agent-1",
    "expected_config_revision": 9007199254740993}


def test_purge_summary_keeps_exact_revision_and_every_effect(monkeypatch):
    monkeypatch.setattr("core.infrastructure.native_runtime.is_launcher_assistant_process", lambda: True)
    result = _assistant_management_summary({"action": "agent_purge", "arguments_json": json.dumps(PARAMETERS)})
    assert result == agent_purge_approval_summary(PARAMETERS)
    assert result["assistantTargets"] == {**{k: v for k, v in PARAMETERS.items() if k != "expected_config_revision"},
        "expected_config_revision": "9007199254740993"}
    assert result["assistantPurgeIrreversible"] is True
    assert result["assistantPurgeEffects"] == ["agent", "sessions", "private_workspace", "team_room_mode_references"]


@pytest.mark.parametrize("change", [{"force": True}, {"approved": True}, {"agent_id": "bad\nagent"},
    {"project_id": "bad\u202eproject"}, {"expected_config_revision": True},
    {"expected_config_revision": "3"}, {"request_id": "bad.request"}])
def test_purge_summary_rejects_unreviewable_or_open_request(monkeypatch, change):
    monkeypatch.setattr("core.infrastructure.native_runtime.is_launcher_assistant_process", lambda: True)
    result = _assistant_management_summary({"action": "agent_purge",
        "arguments_json": json.dumps({**PARAMETERS, **change})})
    assert result == {"assistantAction": "agent_purge", "assistantArgumentsInvalid": True}


def test_purge_is_not_added_to_ordinary_adapter_or_action_window(monkeypatch):
    from core.web.services.session.assistant_manage_policy import (
        ASSISTANT_MANAGE_HIGH_RISK_ACTIONS, ASSISTANT_MANAGE_LOW_RISK_ACTIONS,
    )
    monkeypatch.setattr("core.infrastructure.native_runtime.is_launcher_assistant_process", lambda: False)
    assert _assistant_management_summary({"action": "agent_purge", "arguments_json": json.dumps(PARAMETERS)})["assistantArgumentsInvalid"]
    assert "agent_purge" in ASSISTANT_MANAGE_HIGH_RISK_ACTIONS
    assert "agent_purge" not in ASSISTANT_MANAGE_LOW_RISK_ACTIONS
