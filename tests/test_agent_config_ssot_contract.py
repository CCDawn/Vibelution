"""SSOT contract for Agent config identity: one canonical payload, one write gate.

Covers the B1 findings:
- every persistence path re-stamps configSchemaVersion/permissionPreset/hash
  (configRevision only moves when the canonical payload really changed);
- the change channel snapshot uses the canonical payload (persona/task
  included, draft diff free of spurious fields);
- repair heals stale identity from legacy bypass writes exactly once.
"""

import json

from core.web.services import agent_config_change_service
from core.web.services.agent_config_authority import (
    agent_config_hash,
    canonical_agent_config_payload,
)
from tests.test_agent_config_workspace_service import (
    _use_tmp_project_root,
    agent_directory_service,
)


def _stored_agent(agent_id: str) -> dict:
    state = agent_directory_service.load_state()
    return next(
        item
        for item in state.get("agents") or []
        if str(item.get("agentId") or "").strip() == agent_id
    )


def test_save_state_gate_stamps_stale_config_identity(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Identity gate agent")
    state = agent_directory_service.load_state()
    stored = next(
        item for item in state["agents"] if item["agentId"] == agent["agentId"]
    )
    revision = int(stored["configRevision"])
    stored["configHash"] = "stale-hash"

    agent_directory_service.save_state(state)

    reloaded = _stored_agent(agent["agentId"])
    assert reloaded["configHash"] == agent_config_hash(reloaded)
    assert int(reloaded["configRevision"]) == revision


def test_repair_stamps_stale_identity_exactly_once(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Identity repair agent")
    registry_path = agent_directory_service.registry_path()
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    target = next(
        item for item in payload["agents"] if item["agentId"] == agent["agentId"]
    )
    revision = int(target["configRevision"])
    target["configHash"] = "stale-hash"
    registry_path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    agent_directory_service._invalidate_repaired_state_cache()

    agent_directory_service.repair_agent_directory()
    repaired = _stored_agent(agent["agentId"])
    assert repaired["configHash"] == agent_config_hash(repaired)
    assert int(repaired["configRevision"]) == revision

    stable = _stored_agent(agent["agentId"])
    agent_directory_service.repair_agent_directory()
    assert _stored_agent(agent["agentId"]) == stable


def test_archive_write_keeps_canonical_identity(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Archive identity agent")
    before_revision = int(_stored_agent(agent["agentId"])["configRevision"])

    archived = agent_directory_service.archive_agent_instance(
        agent["agentId"],
        repair_mode_bindings=False,
    )

    assert archived["status"] == "archived"
    stored = _stored_agent(agent["agentId"])
    assert stored["configHash"] == agent_config_hash(stored)
    assert int(stored["configRevision"]) == before_revision


def test_binding_replace_stamps_identity_before_projection(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Binding identity agent")
    before = _stored_agent(agent["agentId"])
    before_revision = int(before["configRevision"])
    slot = agent_directory_service.DEFAULT_AGENT_LLM_SLOT
    new_bindings = dict(agent.get("llmBindings") or {})
    new_bindings[slot] = {"modelId": "identity-test-model"}

    updated = agent_directory_service.replace_agent_llm_bindings_if_current(
        agent["agentId"],
        expected_updated_at=agent["updatedAt"],
        llm_bindings=new_bindings,
        emit_event=False,
    )

    assert updated["llmBindings"] != before["llmBindings"]
    stored = _stored_agent(agent["agentId"])
    assert stored["llmBindings"] != before["llmBindings"]
    assert stored["configHash"] == agent_config_hash(stored)
    assert int(stored["configRevision"]) == before_revision + 1


def test_reasoning_effort_edit_publishes_canonical_revision(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Effort revision agent")
    before = agent_directory_service.get_agent(agent["agentId"], include_archived=True)
    slot = agent_directory_service.DEFAULT_AGENT_LLM_SLOT

    after = agent_directory_service.update_agent_instance(
        agent["agentId"],
        reasoning_effort_by_slot={slot: "xhigh"},
    )
    revision = agent_config_change_service.record_agent_config_revision(
        agent["agentId"],
        before=before,
        after=after,
        source="direct_patch",
    )

    assert revision is not None
    assert revision["changedFields"] == ["reasoningEffortBySlot"]


def test_read_repair_does_not_inject_a_default_llm_binding(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Read path binding agent")
    before = _stored_agent(agent["agentId"])
    assert before["llmBindings"] == {}

    agent_directory_service.get_agent(agent["agentId"], include_archived=True)

    after = _stored_agent(agent["agentId"])
    assert after["llmBindings"] == {}
    assert after["configHash"] == agent_config_hash(after)
    assert int(after["configRevision"]) == int(before["configRevision"])


def test_ensure_agent_for_session_materializes_default_dialogue_binding(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)

    agent = agent_directory_service.ensure_agent_for_session(
        "session-ensure-default",
        display_name="Ensure default binding agent",
    )

    stored = _stored_agent(agent["agentId"])
    model_id = str((stored.get("llmBindings") or {}).get("dialogue", {}).get("modelId") or "").strip()
    assert model_id


def test_change_snapshot_uses_canonical_payload_keys(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Snapshot parity agent")

    snapshot = agent_config_change_service.config_snapshot_from_agent(agent)

    assert set(snapshot) == set(canonical_agent_config_payload(agent))
    assert "personaProfile" in snapshot
    assert "taskProfile" in snapshot


def test_draft_changed_fields_stay_free_of_untouched_canonical_fields(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Draft parity agent")
    before = agent_directory_service.get_agent(agent["agentId"], include_archived=True)
    snapshot = agent_config_change_service.config_snapshot_from_agent(before)
    snapshot["displayName"] = "Draft parity agent renamed"

    draft = agent_config_change_service.save_agent_config_draft(
        agent["agentId"],
        base_updated_at=before["updatedAt"],
        snapshot=snapshot,
        summary="Rename only.",
    )

    assert draft["changedFields"] == ["displayName"]
