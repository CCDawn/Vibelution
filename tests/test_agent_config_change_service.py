import pytest

from core.web.services import agent_config_change_service

from tests.test_agent_config_workspace_service import (
    _use_tmp_project_root,
    agent_directory_service,
    client,
)


def test_agent_config_changes_keep_one_private_draft_and_publish_an_append_only_revision(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    recorded_events = []
    monkeypatch.setattr(
        agent_directory_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )
    agent = agent_directory_service.create_agent_instance(
        display_name="Config history agent",
        direct_session_id="session-config-history",
    )
    before = agent_directory_service.get_agent(agent["agentId"], include_archived=True)
    assert before is not None
    snapshot = agent_config_change_service.config_snapshot_from_agent(before)
    snapshot["displayName"] = "Published config history agent"

    draft = agent_config_change_service.save_agent_config_draft(
        agent["agentId"],
        base_updated_at=before["updatedAt"],
        snapshot=snapshot,
        summary="Prepare a display-name change.",
    )

    draft_path = tmp_path / "workspace" / "agents" / agent["agentId"] / "events" / "config_changes.jsonl"
    assert draft_path.exists()
    assert draft["status"] == "active"
    assert draft["baseUpdatedAt"] == before["updatedAt"]
    assert agent_config_change_service.list_agent_config_changes(agent["agentId"])["activeDraft"]["draftId"] == draft["draftId"]

    after = agent_directory_service.update_agent_instance(
        agent["agentId"],
        display_name=snapshot["displayName"],
        expected_updated_at=before["updatedAt"],
    )
    revision = agent_config_change_service.record_agent_config_revision(
        agent["agentId"],
        before=before,
        after=after,
        source="direct_patch",
        source_draft_id=draft["draftId"],
    )

    history = agent_config_change_service.list_agent_config_changes(agent["agentId"])
    assert history["activeDraft"] is None
    assert history["revisions"][0]["revisionId"] == revision["revisionId"]
    assert history["revisions"][0]["changedFields"] == ["displayName"]
    assert history["revisions"][0]["runtimeBinding"]["directSessionId"] == "session-config-history"
    assert "workspacePath" not in history["revisions"][0]["runtimeBinding"]
    assert any(
        event[0][:3] == ("agent_directory", "config_change", "agent.config_draft.saved")
        for event in recorded_events
    )
    assert any(
        event[0][:3] == ("agent_directory", "config_change", "agent.config_revision.published")
        for event in recorded_events
    )


def test_agent_config_draft_rejects_a_stale_base_revision(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Stale draft agent")
    snapshot = agent_config_change_service.config_snapshot_from_agent(agent)

    with pytest.raises(agent_directory_service.AgentStateConflictError):
        agent_config_change_service.save_agent_config_draft(
            agent["agentId"],
            base_updated_at="stale-revision",
            snapshot=snapshot,
        )


def test_agent_config_revision_does_not_consume_a_draft_when_the_published_snapshot_differs(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Mismatched draft agent")
    before = agent_directory_service.get_agent(agent["agentId"], include_archived=True)
    assert before is not None
    draft_snapshot = agent_config_change_service.config_snapshot_from_agent(before)
    draft_snapshot["displayName"] = "Saved draft name"
    draft = agent_config_change_service.save_agent_config_draft(
        agent["agentId"],
        base_updated_at=before["updatedAt"],
        snapshot=draft_snapshot,
    )
    after = agent_directory_service.update_agent_instance(
        agent["agentId"],
        display_name="Different published name",
        expected_updated_at=before["updatedAt"],
    )

    revision = agent_config_change_service.record_agent_config_revision(
        agent["agentId"],
        before=before,
        after=after,
        source="direct_patch",
        source_draft_id=draft["draftId"],
    )

    assert revision is not None
    assert revision["sourceDraftId"] == ""
    assert agent_config_change_service.list_agent_config_changes(agent["agentId"])["activeDraft"]["draftId"] == draft["draftId"]


def test_agent_config_change_routes_link_a_saved_draft_to_the_published_revision(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="Route config agent",
        direct_session_id="session-route-config",
    )
    current = agent_directory_service.get_agent(agent["agentId"], include_archived=True)
    assert current is not None
    snapshot = agent_config_change_service.config_snapshot_from_agent(current)
    snapshot["displayName"] = "Published route config agent"

    created = client.post(
        f"/api/agents/{agent['agentId']}/config-drafts",
        json={
            "baseUpdatedAt": current["updatedAt"],
            "snapshot": snapshot,
            "summary": "Publish through the canonical Agent PATCH route.",
        },
    )

    assert created.status_code == 201, created.text
    draft = created.json()
    published = client.patch(
        f"/api/agents/{agent['agentId']}",
        json={
            "displayName": snapshot["displayName"],
            "expectedUpdatedAt": current["updatedAt"],
            "sourceDraftId": draft["draftId"],
        },
    )

    assert published.status_code == 200, published.text
    assert published.json()["configRevision"]["sourceDraftId"] == draft["draftId"]
    history = client.get(f"/api/agents/{agent['agentId']}/config-changes")
    assert history.status_code == 200, history.text
    assert history.json()["activeDraft"] is None
    assert history.json()["revisions"][0]["runtimeBinding"]["directSessionId"] == "session-route-config"
