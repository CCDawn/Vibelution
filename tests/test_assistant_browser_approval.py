import json

import pytest

from core.infrastructure import native_runtime
from core.web.services.session.tool_approvals import _assistant_management_summary


PARAMETERS = {
    "page_id": "8e2731f7-06a2-41db-bfa2-cbe76a099811",
    "snapshot_id": "8e2731f7-06a2-41db-bfa2-cbe76a099812",
    "element_ref": "1",
    "url": "https://www.bilibili.com/",
    "element_name": "搜索",
    "operation": "fill",
    "value": "机器学习\n保留完整内容",
}


def test_browser_approval_preserves_exact_native_arguments(monkeypatch):
    monkeypatch.setattr(native_runtime, "is_launcher_assistant_process", lambda: True)
    summary = _assistant_management_summary({"action": "browser_interact", "arguments_json": json.dumps(PARAMETERS)})
    assert summary["assistantTargets"] == PARAMETERS
    assert summary["assistantOperationDescription"] == "向网页上的所选元素填写所示内容。"


@pytest.mark.parametrize("patch", [{"approved": True}, {"operation": "click"}, {"snapshot_id": "forged"}, {"url": "javascript:alert(1)"}])
def test_browser_approval_rejects_incomplete_or_unbound_arguments(monkeypatch, patch):
    monkeypatch.setattr(native_runtime, "is_launcher_assistant_process", lambda: True)
    summary = _assistant_management_summary({"action": "browser_interact", "arguments_json": json.dumps({**PARAMETERS, **patch})})
    assert summary == {"assistantAction": "browser_interact", "assistantArgumentsInvalid": True}


def test_ordinary_session_cannot_gain_browser_approval_projection(monkeypatch):
    monkeypatch.setattr(native_runtime, "is_launcher_assistant_process", lambda: False)
    summary = _assistant_management_summary({"action": "browser_interact", "arguments_json": json.dumps(PARAMETERS)})
    assert "snapshot_id" not in summary.get("assistantTargets", {})
