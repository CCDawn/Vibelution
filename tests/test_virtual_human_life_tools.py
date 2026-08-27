from __future__ import annotations

import json
from datetime import datetime, timezone

from core.agent_plugins.virtual_human_life.manifest import VIRTUAL_HUMAN_TOOL_NAMES
from core.agent_plugins.virtual_human_life.service import VirtualHumanLifeService
from core.web.services import agent_directory_service, tool_catalog
from core.web.services.virtual_human_life_service import (
    set_virtual_human_life_service_for_tests,
)
from tools.Key_Tools import create_key_tools
from tools.virtual_human_life_tools import (
    virtual_human_activity_tool,
    virtual_human_status_tool,
)


def test_virtual_human_tool_bundle_is_registered_in_key_tools_and_catalog() -> None:
    names = {getattr(item, "name", "") for item in create_key_tools()}
    assert set(VIRTUAL_HUMAN_TOOL_NAMES).issubset(names)
    for name in VIRTUAL_HUMAN_TOOL_NAMES:
        assert tool_catalog.metadata_for_tool(name)["category"] == "virtual_life"
    bundles = {item["bundleId"]: item for item in tool_catalog.list_tool_bundles()}
    assert set(bundles["virtual_human_life"]["toolNames"]) == set(VIRTUAL_HUMAN_TOOL_NAMES)


def test_virtual_human_tools_fail_closed_until_current_agent_binding_is_enabled(
    tmp_path,
    monkeypatch,
) -> None:
    agent = {"agentId": "agent-a", "status": "active", "directSessionId": "session-a"}
    service = VirtualHumanLifeService(
        tmp_path,
        agent_loader=lambda agent_id, include_archived=False: (
            agent if agent_id == "agent-a" else None
        ),
        agent_lister=lambda: [agent],
        plugin_root_resolver=lambda agent_id: (
            tmp_path / "agents" / agent_id / "plugins" / "virtual-human-life"
        ),
        now_provider=lambda: datetime(2026, 8, 27, 9, 0, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        agent_directory_service,
        "current_agent_runtime",
        lambda: {"agentId": "agent-a", "sessionId": "session-a"},
    )
    set_virtual_human_life_service_for_tests(service)
    try:
        blocked = json.loads(virtual_human_status_tool())
        assert blocked["ok"] is False
        assert blocked["error"] == "plugin_binding_disabled"
        assert service.plugin_root("agent-a").exists() is False

        service.set_binding("agent-a", enabled=True, expected_version=0)
        ready = json.loads(virtual_human_status_tool())
        assert ready["ok"] is True
        assert ready["snapshot"]["state"]["mood"]["label"] == "calm"
        mutation_without_idempotency = json.loads(
            virtual_human_activity_tool(
                action="cancel",
                expected_version=ready["snapshot"]["state"]["stateVersion"],
                activity_id=ready["snapshot"]["todaySchedule"]["activities"][0][
                    "activityId"
                ],
            )
        )
        assert mutation_without_idempotency["ok"] is False
        assert mutation_without_idempotency["error"] == "idempotency_key_required"
    finally:
        set_virtual_human_life_service_for_tests(None)


def test_active_agent_runtime_carries_virtual_human_binding_fence(
    tmp_path,
    monkeypatch,
) -> None:
    agent = {
        "agentId": "agent-a",
        "status": "active",
        "directSessionId": "session-a",
        "toolPolicyId": "tool-agent-a",
        "toolPolicy": {
            "policyId": "tool-agent-a",
            "policyVersion": 1,
            "allowedTools": [],
            "blockedTools": [],
            "preferredTools": [],
            "networkAccess": "restricted",
            "mutationAccess": "controlled",
            "delegationAccess": "none",
            "maxCallsPerTurn": 4,
            "approvalOverrides": {},
        },
        "metadata": {},
        "configRevision": 1,
        "configHash": "config-agent-a",
        "permissionPreset": "request_approval",
    }
    service = VirtualHumanLifeService(
        tmp_path,
        agent_loader=lambda agent_id, include_archived=False: (
            agent if agent_id == "agent-a" else None
        ),
        agent_lister=lambda: [agent],
        plugin_root_resolver=lambda agent_id: (
            tmp_path / "agents" / agent_id / "plugins" / "virtual-human-life"
        ),
        now_provider=lambda: datetime(2026, 8, 27, 9, 0, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        agent_directory_service,
        "get_agent",
        lambda agent_id, **_kwargs: agent if agent_id == "agent-a" else None,
    )
    set_virtual_human_life_service_for_tests(service)
    try:
        with agent_directory_service.active_agent_runtime(
            "agent-a", session_id="session-a", turn_id="turn-a"
        ) as runtime:
            assert runtime["externallyBlockedTools"] == list(VIRTUAL_HUMAN_TOOL_NAMES)

        service.set_binding("agent-a", enabled=True, expected_version=0)
        with agent_directory_service.active_agent_runtime(
            "agent-a", session_id="session-a", turn_id="turn-b"
        ) as runtime:
            assert runtime["externallyBlockedTools"] == []
    finally:
        set_virtual_human_life_service_for_tests(None)
