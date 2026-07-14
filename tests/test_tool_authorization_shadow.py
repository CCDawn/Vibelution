import json

import pytest

from core.authorization.tool_authorization_service import resolve_shadow_authorization
from core.authorization.tool_policy_models import ToolPolicyInvalidError
from core.logging import tool_authorization_events
from core.web.services import tool_catalog
from tools import conversation_log_tools


def _registry_payload():
    descriptor_objects = (
        tool_catalog.build_tool_descriptor("grep_search_tool", args_schema={"type": "object"}),
        tool_catalog.build_tool_descriptor("web_search_tool", args_schema={"type": "object"}),
        tool_catalog.build_tool_descriptor("apply_patch_tool", args_schema={"type": "object"}),
    )
    names = {descriptor.name for descriptor in descriptor_objects}
    return {
        "registryVersion": 1,
        "registryFingerprint": tool_catalog.registry_descriptor_fingerprint(descriptor_objects),
        "descriptors": [descriptor.public_projection() for descriptor in descriptor_objects],
        "tools": [
            {
                "name": name,
                "enabled": True,
                "runtimeActive": True,
                "llmVisible": True,
            }
            for name in sorted(names)
        ],
    }


def _runtime(policy):
    return {
        "agentId": "agent-shadow",
        "turnId": "turn-shadow",
        "agent": {
            "agentId": "agent-shadow",
            "primaryMode": "chat",
            "roleKey": "",
            "metadata": {},
        },
        "toolPolicy": {"policyId": "tool-agent-shadow", **policy},
    }


def test_shadow_authorization_reports_parity_without_changing_legacy_surface():
    report = resolve_shadow_authorization(
        runtime=_runtime(
            {
                "allowedTools": ["grep_search_tool"],
                "preferredTools": ["grep_search_tool"],
                "networkAccess": "restricted",
                "mutationAccess": "controlled",
            }
        ),
        legacy_visible_tool_names=("grep_search_tool",),
        registry_payload=_registry_payload(),
        generated_at="2026-07-14T00:00:00Z",
    )

    assert report.parity is True
    assert report.legacy_visible_tools == ("grep_search_tool",)
    assert report.decision.visible_tools == ("grep_search_tool",)
    assert report.shadow_only_tools == ()
    assert report.legacy_only_tools == ()


def test_shadow_authorization_classifies_bounded_visibility_diff():
    report = resolve_shadow_authorization(
        runtime=_runtime(
            {
                "allowedTools": ["grep_search_tool", "web_search_tool"],
                "preferredTools": [],
                "networkAccess": "full",
                "mutationAccess": "controlled",
            }
        ),
        legacy_visible_tool_names=("grep_search_tool",),
        registry_payload=_registry_payload(),
    )

    assert report.parity is False
    assert report.shadow_only_tools == ("web_search_tool",)
    assert report.legacy_only_tools == ()
    assert dict(report.deny_code_counts)["not_assigned"] == 1


def test_shadow_authorization_fails_closed_for_corrupt_policy():
    with pytest.raises(ToolPolicyInvalidError):
        resolve_shadow_authorization(
            runtime=_runtime({"allowedTools": ["unknown_tool"], "preferredTools": []}),
            legacy_visible_tool_names=("grep_search_tool",),
            registry_payload=_registry_payload(),
        )


def test_shadow_event_logging_is_bounded_and_excludes_policy_payload(monkeypatch):
    report = resolve_shadow_authorization(
        runtime=_runtime(
            {
                "allowedTools": ["grep_search_tool", "web_search_tool"],
                "preferredTools": [],
                "networkAccess": "full",
                "mutationAccess": "controlled",
            }
        ),
        legacy_visible_tool_names=("grep_search_tool",),
        registry_payload=_registry_payload(),
    )
    captured = []
    monkeypatch.setattr(
        "core.web.services.runtime_scene_service.record_runtime_scene_event",
        lambda *args, **kwargs: captured.append((args, kwargs)),
    )

    tool_authorization_events.record_shadow_authorization_event(report)

    assert len(captured) == 1
    args, kwargs = captured[0]
    assert args == ("tool_authorization", "shadow", "tool.authorization.shadow_decision")
    assert kwargs["fields"]["shadowOnlyTools"] == ["web_search_tool"]
    assert "toolPolicy" not in kwargs["fields"]
    assert "arguments" not in kwargs["fields"]
    assert "prompt" not in kwargs["fields"]


def test_conversation_log_inspector_summarizes_authorization_events(tmp_path, monkeypatch):
    log_dir = tmp_path / "log_info"
    log_dir.mkdir()
    log_path = log_dir / "conversation_auth.jsonl"
    log_path.write_text(
        json.dumps(
            {
                "event_code": "tool.authorization.shadow_decision",
                "outcome": "diff",
                "ts": "2026-07-14T00:00:00Z",
                "fields": {
                    "agentId": "agent-shadow",
                    "turnId": "turn-shadow",
                    "policyId": "tool-agent-shadow",
                    "policyVersion": 2,
                    "registryVersion": 1,
                    "decisionFingerprint": "abc123",
                    "parity": False,
                    "legacyVisibleCount": 1,
                    "shadowVisibleCount": 2,
                    "shadowOnlyCount": 1,
                    "legacyOnlyCount": 0,
                    "denyCodeCounts": {"not_assigned": 1},
                    "durationMs": 4,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(conversation_log_tools, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(conversation_log_tools, "LOG_INFO_DIR", log_dir)

    payload = conversation_log_tools.inspect_conversation_logs(log_path=str(log_path), limit=1, max_events=200)

    authorization = payload["inspections"][0]["toolAuthorization"]
    assert authorization["eventCount"] == 1
    assert authorization["parityMismatchCount"] == 1
    assert authorization["failureCount"] == 0
    assert authorization["latest"]["agentId"] == "agent-shadow"
    assert payload["summary"]["toolAuthorizationMismatchCount"] == 1
