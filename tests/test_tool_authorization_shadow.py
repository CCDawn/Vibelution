from __future__ import annotations

import pytest

from core.authorization.tool_authorization_service import (
    _descriptors_from_registry,
    resolve_enforced_authorization,
)
from core.authorization.tool_policy_models import ToolPolicyInvalidError, ToolRegistryMissingError
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
    # 聚合事件 schema 不变：per-tool 明细只进并行事件。
    assert "deniedTools" not in kwargs["fields"]


def test_decision_reasons_event_carries_bounded_per_tool_rule_ids(monkeypatch):
    report = resolve_enforced_authorization(
        runtime=_runtime({"allowedTools": ["grep_search_tool"], "preferredTools": []}),
        registry_payload=_registry_payload(),
        generated_at="2026-07-14T00:00:00Z",
    )
    captured = []
    monkeypatch.setattr(
        "core.web.services.runtime_scene_service.record_runtime_scene_event",
        lambda *args, **kwargs: captured.append((args, kwargs)),
    )

    tool_authorization_events.record_authorization_decision(report)

    assert [item[0][2] for item in captured] == [
        "tool.authorization.decision",
        "tool.authorization.decision_reasons",
    ]
    args, kwargs = captured[1]
    assert args == ("tool_authorization", "decision", "tool.authorization.decision_reasons")
    fields = kwargs["fields"]
    assert fields["agentId"] == "agent-auth"
    assert fields["turnId"] == "turn-auth"
    assert fields["policyId"] == "tool-agent-auth"
    assert fields["deniedCount"] == 1
    assert "denyCodeCounts" not in fields
    assert "durationMs" not in fields
    entries = fields["deniedTools"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["toolName"] == "web_search_tool"
    assert entry["phase"] == "visibility"
    assert entry["reasonCode"] == "not_assigned"
    assert entry["gateId"] == "policy.allowedTools"
    assert entry["ruleId"] == "tool-agent-auth:policy.allowedTools:not_assigned"
    assert isinstance(entry["message"], str) and entry["message"]
    # per-tool 明细必须有界。
    assert tool_authorization_events.MAX_DECISION_REASON_TOOLS == 8


def test_decision_reasons_event_absent_when_no_tool_is_denied(monkeypatch):
    report = resolve_enforced_authorization(
        runtime=_runtime(
            {
                "allowedTools": ["grep_search_tool", "web_search_tool"],
                "preferredTools": [],
            }
        ),
        registry_payload=_registry_payload(),
        generated_at="2026-07-14T00:00:00Z",
    )
    assert report.decision.denied == ()
    captured = []
    monkeypatch.setattr(
        "core.web.services.runtime_scene_service.record_runtime_scene_event",
        lambda *args, **kwargs: captured.append((args, kwargs)),
    )

    tool_authorization_events.record_authorization_decision(report)

    assert [item[0][2] for item in captured] == ["tool.authorization.decision"]


def test_string_capabilities_and_aliases_are_not_split_into_characters():
    descriptors = _descriptors_from_registry(
        {
            "descriptors": [
                {
                    "name": "grep_search_tool",
                    "enabled": True,
                    "capabilities": "read",
                    "risk": "read",
                    "approval": "never",
                    "aliases": "grep",
                }
            ]
        }
    )

    assert descriptors[0].capabilities == ("read",)
    assert descriptors[0].aliases == ("grep",)


def test_string_false_hides_registry_tools_from_available_names():
    payload = _registry_payload()
    payload["descriptors"][0]["enabled"] = "false"
    payload["tools"][0]["enabled"] = "false"
    payload["tools"][0]["runtimeActive"] = "false"
    payload["tools"][0]["llmVisible"] = "false"

    report = resolve_enforced_authorization(
        runtime=_runtime({"allowedTools": ["grep_search_tool"], "preferredTools": ["grep_search_tool"]}),
        registry_payload=payload,
        generated_at="2026-07-14T00:00:00Z",
    )

    assert "grep_search_tool" not in report.decision.visible_tools
    assert "grep_search_tool" not in report.decision.executable_tools


def test_snake_case_tool_policy_is_accepted():
    runtime = {
        "agentId": "agent-auth",
        "turnId": "turn-auth",
        "agent": {"agentId": "agent-auth", "primaryMode": "chat"},
        "tool_policy": {
            "policyId": "tool-agent-auth",
            "allowedTools": ["grep_search_tool"],
            "preferredTools": ["grep_search_tool"],
        },
    }

    report = resolve_enforced_authorization(
        runtime=runtime,
        registry_payload=_registry_payload(),
        generated_at="2026-07-14T00:00:00Z",
    )

    assert report.decision.visible_tools == ("grep_search_tool",)
    assert report.decision.executable_tools == ("grep_search_tool",)


def test_non_mapping_registry_payload_fails_closed_without_dict_crash():
    with pytest.raises(ToolRegistryMissingError):
        resolve_enforced_authorization(
            runtime=_runtime({"allowedTools": ["grep_search_tool"], "preferredTools": []}),
            registry_payload=["not-a-map"],
        )
