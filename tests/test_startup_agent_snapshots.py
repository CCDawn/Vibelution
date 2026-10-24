"""Startup discovery reads identities without constructing Agent UI payloads."""

from __future__ import annotations

from copy import deepcopy

import pytest

from core.web.services import agent_directory_service as directory
from core.web.services.agent_directory.parameter_snapshot import list_agent_identity_snapshots


@pytest.fixture
def registry(monkeypatch):
    state = {
        "agents": [
            {"agentId": "old", "createdAt": "2026-01-01", "status": "active",
             "displayName": "Old", "directSessionId": "session-old", "metadata": {"nested": [1]},
             "toolPolicy": {"mustNotBeProjected": True}},
            {"agentId": "archived", "updatedAt": "2026-03-01", "status": "archived", "metadata": {}},
            {"agentId": "draft", "createdAt": "2026-02-01", "status": "draft", "metadata": {}},
            {"agentId": "active-default", "updatedAt": "2026-04-01", "metadata": {}},
            "invalid legacy record",
        ],
    }
    calls = []
    monkeypatch.setattr(directory, "_load_repaired_state_for_read", lambda: (calls.append("repair") or state, False))
    for name in ("save_state", "_agent_to_api_summary", "_build_agent_api_hydration_context", "_available_agent_avatar_filenames"):
        monkeypatch.setattr(directory, name, lambda *a, **kw: pytest.fail("identity reads must not hydrate or write"))
    return state, calls


def test_discovery_uses_repaired_authority_and_existing_status_order(registry):
    state, calls = registry
    before = deepcopy(state)
    rows = list_agent_identity_snapshots()
    assert [row["agentId"] for row in rows] == ["active-default", "archived", "draft", "old"]
    assert calls == ["repair"]
    assert state == before
    old = rows[-1]
    assert old["displayName"] == "Old"
    assert old["directSessionId"] == "session-old"
    assert "toolPolicy" not in old
    assert "contextCompressionEffectivePolicy" not in old


def test_discovery_filters_archived_only_and_detaches_metadata(registry):
    state, _ = registry
    rows = list_agent_identity_snapshots(include_archived=False)
    assert [row["agentId"] for row in rows] == ["active-default", "draft", "old"]
    rows[-1]["metadata"]["nested"].append(2)
    assert state["agents"][0]["metadata"] == {"nested": [1]}
    assert list_agent_identity_snapshots(include_archived=False)[-1]["metadata"] == {"nested": [1]}


def test_discovery_does_not_report_unavailable_registry_as_empty(monkeypatch):
    def unavailable():
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr(directory, "_load_repaired_state_for_read", unavailable)
    with pytest.raises(RuntimeError, match="registry unavailable"):
        list_agent_identity_snapshots()


def test_discovery_keeps_legacy_identity_normalization(registry):
    state, _ = registry
    state["agents"][0].update({
        "displayName": " Old ", "directSessionId": " session-old ", "createdBy": " operator ",
        "roleKey": "", "metadata": {"researchAgentKey": " legacy-role "},
    })
    row = list_agent_identity_snapshots()[-1]
    assert row["displayName"] == "Old"
    assert row["directSessionId"] == "session-old"
    assert row["createdBy"] == "operator"
    assert row["roleKey"] == "research_legacy_role"
    assert row["agentCode"] == directory._fallback_agent_code("old")
