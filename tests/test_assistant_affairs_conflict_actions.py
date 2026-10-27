"""The Launcher assistant can inspect, but never activate, archived differences."""
import threading

import pytest

from core.assistant_runtime import affairs_conflict_actions as actions
from core.assistant_runtime import migration_affairs_conflicts as conflicts
from core.assistant_runtime import native


def test_only_live_assistant_turn_can_read_its_archived_differences(tmp_path, monkeypatch):
    monkeypatch.setattr(actions, "assistant_native_root", lambda: tmp_path)
    monkeypatch.setattr(native, "_STARTED", True)
    monkeypatch.setattr(native, "_OFFLINE_MIGRATION", False)
    monkeypatch.setattr(native, "_STOP_REQUESTED", threading.Event())
    monkeypatch.setattr(native, "_AGENT_ID", "assistant")
    monkeypatch.setattr(native, "_SESSION_ID", "direct")
    scope = {"projectId": "project", "instanceId": "main", "agentId": "old-assistant"}
    monkeypatch.setattr(conflicts, "resolve_affairs_conflict_scope", lambda root, **kw: scope)
    monkeypatch.setattr(conflicts, "list_affairs_conflicts", lambda root, **kw: {
        "sourceScope": kw["source_scope"], "targetSnapshotOnly": True, "readOnly": True,
    })
    runtime = {"agentId": "assistant", "sessionId": "direct"}
    result = actions.execute("affairs_conflict_list", {"sync_id": "migration-1"}, runtime)
    assert result["sourceScope"] == scope and result["targetSnapshotOnly"] and result["readOnly"]
    with pytest.raises(ValueError):
        actions.execute("affairs_conflict_list", {"sync_id": "migration-1"}, {**runtime, "agentId": "other"})
    with pytest.raises(ValueError):
        actions.execute("affairs_conflict_list", {"sync_id": "migration-1", "path": "C:/private"}, runtime)
    receipt = actions.execute("affairs_sync_receipt", {"sync_id": "affairs-" + "a" * 40}, runtime)
    assert receipt["state"] == "unknown" and not receipt["readyForCutover"]
    with pytest.raises(ValueError):
        actions.execute("affairs_sync_receipt", {"sync_id": "C:/private"}, runtime)
