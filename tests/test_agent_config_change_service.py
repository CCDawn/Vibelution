import pytest

from core.web.services import (
    agent_config_change_service,
    agent_config_effective_projection,
)

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


def test_agent_config_is_versioned_and_permission_preset_is_canonical(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="Canonical config agent",
        direct_session_id="session-canonical-config",
    )

    assert agent["configSchemaVersion"] == 2
    assert agent["configRevision"] == 1
    assert agent["permissionPreset"] == "request_approval"
    assert len(agent["configHash"]) == 64
    initial_hash = agent["configHash"]

    updated = agent_directory_service.update_agent_instance(
        agent["agentId"],
        permission_preset="auto_review",
        expected_config_revision=1,
    )

    assert updated["permissionPreset"] == "auto_review"
    assert updated["configRevision"] == 2
    assert updated["configHash"] != initial_hash

    with pytest.raises(agent_directory_service.AgentStateConflictError):
        agent_directory_service.update_agent_instance(
            agent["agentId"],
            permission_preset="full_access",
            expected_config_revision=1,
        )


def test_agent_config_rejects_unknown_permission_preset(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Strict permission agent")

    with pytest.raises(agent_directory_service.AgentDirectoryError, match="permission preset"):
        agent_directory_service.update_agent_instance(
            agent["agentId"],
            permission_preset="custom",
            expected_config_revision=agent["configRevision"],
        )


def test_agent_patch_updates_permission_preset_with_config_revision_cas(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="Permission route agent",
    )

    updated = client.patch(
        f"/api/agents/{agent['agentId']}",
        json={
            "permissionPreset": "auto_review",
            "expectedConfigRevision": agent["configRevision"],
        },
    )

    assert updated.status_code == 200, updated.text
    assert updated.json()["permissionPreset"] == "auto_review"
    assert updated.json()["configRevision"] == agent["configRevision"] + 1
    assert updated.json()["runtimePermissions"] == {
        "preset": "auto_review",
        "sandboxMode": "workspace_write",
        "approvalPolicy": "on_request",
        "approvalsReviewer": "auto_review",
    }

    stale = client.patch(
        f"/api/agents/{agent['agentId']}",
        json={
            "permissionPreset": "full_access",
            "expectedConfigRevision": agent["configRevision"],
        },
    )
    assert stale.status_code == 409


def test_agent_config_embeds_every_runtime_policy_at_creation(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)

    agent = agent_directory_service.create_agent_instance(
        display_name="Embedded policy agent",
    )

    assert agent["toolPolicy"]["policyId"] == agent["toolPolicyId"]
    assert agent["memoryPolicy"]["policyId"] == agent["memoryPolicyId"]
    assert agent["contextCompressionPolicy"]["mode"] == "custom"
    assert agent["contextCompressionEffectivePolicy"]["source"] == "agent"
    assert agent["metadata"]["delegationPolicy"] == agent_directory_service.normalize_delegation_policy({})
    assert agent["metadata"]["supervisionPolicy"] == agent_directory_service.normalize_supervision_policy({})


def test_runtime_policy_resolution_ignores_shared_catalog_changes(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="Private runtime policy agent",
    )
    original_tool_policy = agent["toolPolicy"]
    original_memory_policy = agent["memoryPolicy"]

    state = agent_directory_service.load_state()
    state["toolPolicies"][agent["toolPolicyId"]]["allowedTools"] = ["untrusted_catalog_tool"]
    state["memoryPolicies"][agent["memoryPolicyId"]]["readSharedGroups"] = ["untrusted-catalog-group"]
    agent_directory_service.save_state(state)

    resolved_tool_policy = agent_directory_service.resolve_tool_policy_for_agent(agent["agentId"])
    resolved_memory_policy = agent_directory_service.resolve_memory_policy_for_agent(agent["agentId"])

    assert resolved_tool_policy["allowedTools"] == original_tool_policy["allowedTools"]
    assert resolved_memory_policy["readSharedGroups"] == original_memory_policy["readSharedGroups"]


def test_unmigrated_agent_runtime_policies_fail_closed_without_catalog_fallback(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    workspace_path = "workspace/agents/agent-legacy-unmigrated"
    agent_directory_service.save_state(
        {
            "agents": [
                {
                    "agentId": "agent-legacy-unmigrated",
                    "displayName": "Legacy unmigrated agent",
                    "workspacePath": workspace_path,
                    "toolPolicyId": "shared-wide",
                    "memoryPolicyId": "shared-memory",
                    "status": "active",
                }
            ],
            "toolPolicies": {
                "shared-wide": {
                    **agent_directory_service.default_tool_policy("shared-wide"),
                    "allowedTools": ["dangerous_catalog_tool"],
                }
            },
            "memoryPolicies": {
                "shared-memory": {
                    **agent_directory_service.default_memory_policy(
                        "shared-memory",
                        workspace_path,
                    ),
                    "readSharedGroups": ["sensitive-catalog-group"],
                }
            },
        }
    )

    tool_policy = agent_directory_service.resolve_tool_policy_for_agent(
        "agent-legacy-unmigrated"
    )
    memory_policy = agent_directory_service.resolve_memory_policy_for_agent(
        "agent-legacy-unmigrated"
    )

    assert tool_policy["allowedTools"] == []
    assert memory_policy["readSharedGroups"] == []


def test_effective_configuration_has_only_the_agent_as_runtime_source(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="Single source projection agent",
    )

    projected = agent_config_effective_projection.derive_effective_configuration(agent)

    assert projected["fields"]
    for field in projected["fields"]:
        assert field["source"]["kind"] == "agent"
        assert field["source"]["id"] == agent["agentId"]
        assert field["inheritanceChain"] == [
            {
                **field["source"],
                "value": field["effectiveValue"],
                "active": True,
            }
        ]


def test_active_turn_keeps_one_immutable_agent_config_snapshot(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="Immutable turn config agent",
    )

    with agent_directory_service.active_agent_runtime(agent["agentId"]) as runtime:
        captured = runtime["agentConfigSnapshot"]
        agent_directory_service.update_agent_instance(
            agent["agentId"],
            permission_preset="full_access",
            expected_config_revision=agent["configRevision"],
        )

        assert captured == {
            "agentId": agent["agentId"],
            "configRevision": agent["configRevision"],
            "configHash": agent["configHash"],
        }
        assert runtime["agent"]["permissionPreset"] == "request_approval"
        assert runtime["permissionPreset"] == "request_approval"

    with agent_directory_service.active_agent_runtime(agent["agentId"]) as next_runtime:
        assert next_runtime["agentConfigSnapshot"]["configRevision"] == agent["configRevision"] + 1
        assert next_runtime["permissionPreset"] == "full_access"


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
    assert published.json()["configRevision"] == agent["configRevision"] + 1
    assert published.json()["publishedConfigChange"]["sourceDraftId"] == draft["draftId"]
    history = client.get(f"/api/agents/{agent['agentId']}/config-changes")
    assert history.status_code == 200, history.text
    assert history.json()["activeDraft"] is None
    assert history.json()["revisions"][0]["runtimeBinding"]["directSessionId"] == "session-route-config"
