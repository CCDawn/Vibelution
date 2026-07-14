from __future__ import annotations

import pytest

from core.authorization.tool_authorization_service import resolve_enforced_authorization
from core.authorization.tool_policy_models import ToolPolicyInvalidError
from core.logging import tool_authorization_events


def _registry_payload():
    return {
        "registryVersion": 1,
        "registryFingerprint": "registry-1",
        "descriptors": [
            {
                "name": "grep_search_tool",
                "enabled": True,
                "capabilities": ["read"],
                "risk": "read",
                "approval": "never",
                "aliases": [],
            },
            {
                "name": "web_search_tool",
                "enabled": True,
                "capabilities": ["network"],
                "risk": "network",
                "approval": "never",
                "aliases": [],
            },
        ],
        "tools": [
            {"name": "grep_search_tool", "enabled": True, "runtimeActive": True, "llmVisible": True},
            {"name": "web_search_tool", "enabled": True, "runtimeActive": True, "llmVisible": True},
        ],
    }


def _runtime(policy):
    return {
        "agentId": "agent-auth",
        "turnId": "turn-auth",
        "agent": {"agentId": "agent-auth", "primaryMode": "chat"},
        "toolPolicy": {"policyId": "tool-agent-auth", **policy},
    }


def test_canonical_authorization_resolves_visible_and_executable_tools_without_legacy_input():
    report = resolve_enforced_authorization(
        runtime=_runtime({"allowedTools": ["grep_search_tool"], "preferredTools": ["grep_search_tool"]}),
        registry_payload=_registry_payload(),
        generated_at="2026-07-14T00:00:00Z",
    )

    assert report.decision.visible_tools == ("grep_search_tool",)
    assert report.decision.executable_tools == ("grep_search_tool",)
    assert dict(report.deny_code_counts)["not_assigned"] == 1


def test_canonical_authorization_fails_closed_for_unknown_policy_tool():
    with pytest.raises(ToolPolicyInvalidError):
        resolve_enforced_authorization(
            runtime=_runtime({"allowedTools": ["unknown_tool"], "preferredTools": []}),
            registry_payload=_registry_payload(),
        )


def test_authorization_decision_logging_is_bounded_and_has_no_legacy_fields(monkeypatch):
    report = resolve_enforced_authorization(
        runtime=_runtime({"allowedTools": ["grep_search_tool"], "preferredTools": []}),
        registry_payload=_registry_payload(),
    )
    captured = []
    monkeypatch.setattr(
        "core.web.services.runtime_scene_service.record_runtime_scene_event",
        lambda *args, **kwargs: captured.append((args, kwargs)),
    )

    tool_authorization_events.record_authorization_decision(report)

    args, kwargs = captured[0]
    assert args == ("tool_authorization", "decision", "tool.authorization.decision")
    assert kwargs["fields"]["visibleCount"] == 1
    assert kwargs["fields"]["executableCount"] == 1
    assert "legacyVisibleCount" not in kwargs["fields"]
    assert "toolPolicy" not in kwargs["fields"]
