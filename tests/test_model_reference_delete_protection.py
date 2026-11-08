from __future__ import annotations

import copy
import json
import sqlite3
from types import SimpleNamespace

import pytest

from config.public_config import public_config_hash
from core.chat.conversation_store import ConversationStore
from core.infrastructure import developer_sandbox
from core.web.services import model_reference_service, provider_config_service
from core.web.services.model_reference_service import ModelReferenceConflictError
from core.web.services.session.directory_runtime import conversation_store_path


TARGET = "relay_target/unlisted"
KEEP = "relay_keep/base"


def _binding(model_id):
    return {"dialogueModelId": model_id, "llmBindings": {"dialogue": {"modelId": model_id}}}


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(model_reference_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(developer_sandbox, "is_developer_mode_enabled", lambda: False)
    provider = {
        "label": "Fixture", "service_class": "relay", "vendor": "multi_model",
        "driver": "openai", "base_url": "https://fixture.invalid/v1", "auth_kind": "none",
        "credential_ref": "none", "requires_credential": False,
        "protocols": {"default": "chat_completions", "allowed": ["chat_completions"]},
        "models": {},
    }
    config = {"llm": {"schema_version": 2, "providers": {
        "relay_target": copy.deepcopy(provider), "relay_keep": copy.deepcopy(provider),
    }, "profiles": {"primary": {"model_ref": KEEP, "overrides": {}}}, "model_aliases": {}}}
    config["llm"]["providers"]["relay_keep"]["models"]["base"] = {"upstream_id": "base"}
    monkeypatch.setattr(provider_config_service, "load_public_config", lambda: copy.deepcopy(config))
    monkeypatch.setattr(provider_config_service, "load_model_catalog_state", lambda: {"providers": {}})
    monkeypatch.setattr(provider_config_service, "_record_provider_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(provider_config_service, "_build_workspace", lambda public_config, **kwargs: {
        "publicConfig": public_config,
    })
    return SimpleNamespace(root=tmp_path, config=config,
        workspace=developer_sandbox.formal_workspace_path(tmp_path), db=conversation_store_path(tmp_path))


def _seed_owner(env, owner):
    if owner == "team":
        env.policy = env.workspace / "teams" / "team-a" / "workflow_orchestration.json"
        env.policy.parent.mkdir(parents=True)
        env.policy.write_text(json.dumps({"promptCachePolicy": {"modelId": TARGET}}), encoding="utf-8")
        return
    with ConversationStore(env.db) as store:
        created = store.repository.create_agent(agent_id="agent-a", display_name="Fixture", kind="chat",
            config=_binding(TARGET), source="test").result(timeout=5)
        env.original_revision = created["configRevisionId"]
        if owner == "session":
            store.repository.create_session(session_id="session-a", agent_id="agent-a",
                agent_config_revision_id=env.original_revision, title="Pinned session").result(timeout=5)
            store.repository.compare_and_swap_agent_config(agent_id="agent-a",
                expected_config_revision_id=env.original_revision, display_name="Fixture", kind="chat",
                status="active", config=_binding(KEEP), source="test").result(timeout=5)


def _release_owner(env, owner):
    if owner == "team":
        env.policy.write_text(json.dumps({"promptCachePolicy": {"modelId": KEEP}}), encoding="utf-8")
        return
    if owner == "agent":
        with ConversationStore(env.db) as store:
            store.repository.compare_and_swap_agent_config(agent_id="agent-a",
                expected_config_revision_id=env.original_revision, display_name="Fixture", kind="chat",
                status="active", config=_binding(KEEP), source="test").result(timeout=5)
    else:
        # Remove the isolated owner; archiving alone must retain its compiled pin.
        with sqlite3.connect(env.db) as connection:
            connection.execute("DELETE FROM sessions WHERE session_id='session-a'")
    with sqlite3.connect(env.db) as connection:
        preserved = connection.execute("SELECT config_json FROM agent_config_revisions WHERE revision_id=?",
            (env.original_revision,)).fetchone()[0]
    assert json.loads(preserved)["dialogueModelId"] == TARGET


@pytest.mark.parametrize("owner", ["agent", "session", "team"])
@pytest.mark.parametrize("operation", ["model", "provider"])
def test_live_owner_blocks_delete_until_released(isolated, owner, operation):
    _seed_owner(isolated, owner)
    if operation == "model":
        isolated.config["llm"]["providers"]["relay_target"]["models"]["unlisted"] = {"upstream_id": "unlisted"}
        delete = lambda: provider_config_service.draft_unpin_provider_model(isolated.config, draft_meta={},
            base_hash=public_config_hash(isolated.config), provider_id="relay_target", model_key="unlisted")
    else:
        delete = lambda: provider_config_service.draft_delete_provider(isolated.config, draft_meta={},
            base_hash=public_config_hash(isolated.config), provider_id="relay_target")
    before = copy.deepcopy(isolated.config)

    with pytest.raises(ModelReferenceConflictError) as caught:
        delete()

    impact = caught.value.impact
    assert impact["modelId"] == TARGET
    assert impact["blocking"] is True
    assert {ref["ownerType"] for ref in impact["liveReferences"]} == {
        "team_prompt_cache_policy" if owner == "team" else owner,
    }
    assert isolated.config == before
    _release_owner(isolated, owner)

    deleted = delete()["publicConfig"]

    assert deleted["llm"]["providers"]["relay_keep"] == before["llm"]["providers"]["relay_keep"]
    if operation == "model":
        assert deleted["llm"]["providers"]["relay_target"]["models"] == {}
    else:
        assert "relay_target" not in deleted["llm"]["providers"]
    assert isolated.config == before


def test_archived_session_still_keeps_its_revision_live(isolated):
    _seed_owner(isolated, "session")
    with sqlite3.connect(isolated.db) as connection:
        connection.execute("UPDATE sessions SET archived_at_ms=1 WHERE session_id='session-a'")

    impact = model_reference_service.scan_model_references(TARGET)

    assert impact["blocking"] is True
    assert {ref["ownerType"] for ref in impact["liveReferences"]} == {"session"}


def test_unpinned_newer_revision_does_not_replace_current_agent_pin(isolated):
    _seed_owner(isolated, "agent")
    with sqlite3.connect(isolated.db) as connection:
        connection.execute("INSERT INTO agent_config_revisions "
            "(revision_id,agent_id,config_hash,config_json,source,created_at_ms) "
            "VALUES ('unpinned','agent-a','unpinned',?,'test',9999999999999)", (json.dumps(_binding(KEEP)),))

    assert model_reference_service.scan_model_references(TARGET)["blocking"] is True
    assert model_reference_service.scan_model_references(KEEP)["blocking"] is False


def test_historical_team_artifact_does_not_block_empty_provider_delete(isolated):
    historical = isolated.workspace / "supervised_evolution" / "decisions" / "historical.json"
    historical.parent.mkdir(parents=True)
    historical.write_text(json.dumps({"modelId": TARGET}), encoding="utf-8")

    impact = model_reference_service.scan_model_references(TARGET)
    assert impact["historicalReferenceCount"] == 1
    assert impact["blocking"] is False
    deleted = provider_config_service.draft_delete_provider(isolated.config, draft_meta={},
        base_hash=public_config_hash(isolated.config), provider_id="relay_target")["publicConfig"]

    assert "relay_target" not in deleted["llm"]["providers"]
    assert TARGET in historical.read_text(encoding="utf-8")


@pytest.mark.parametrize("owner", ["agent_registry", "chat_room_registry", "agent_store"])
@pytest.mark.parametrize("field", ["modelId", "dialogueModelId", "agentTemplateLabel"])
def test_provider_enumeration_covers_each_declared_model_field(isolated, owner, field):
    if owner == "agent_store":
        with ConversationStore(isolated.db) as store:
            store.repository.create_agent(agent_id="agent-a", display_name="Fixture", kind="chat",
                config={field: TARGET}, source="test").result(timeout=5)
    else:
        if owner == "agent_registry":
            path = isolated.workspace / "agents" / "agents.json"
            payload = {"agents": [{"agentId": "agent-a", field: TARGET}]}
        else:
            path = isolated.workspace / "chat_rooms" / "chat_rooms.json"
            payload = {"rooms": [{"roomId": "room-a", "participants": [{"agentId": "agent-a", field: TARGET}]}]}
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    assert model_reference_service.scan_model_references(TARGET)["blocking"] is True
    impact = model_reference_service.scan_provider_live_references("relay_target")
    assert impact["modelIds"] == [TARGET]
    with pytest.raises(ModelReferenceConflictError) as caught:
        provider_config_service.draft_delete_provider(isolated.config, draft_meta={},
            base_hash=public_config_hash(isolated.config), provider_id="relay_target")
    assert caught.value.impact["modelId"] == TARGET
    assert {ref["field"] for ref in caught.value.impact["liveReferences"]} == {field}


@pytest.mark.parametrize("label", ["Display label", "relay_target/", "relay_target/family/model", "relay_target/" + "a" * 97])
def test_template_display_label_does_not_block_provider_delete(isolated, label):
    path = isolated.workspace / "agents" / "agents.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"agents": [{"agentId": "agent-a", "agentTemplateLabel": label}]}), encoding="utf-8")

    impact = model_reference_service.scan_provider_live_references("relay_target")
    assert impact["modelIds"] == []
    deleted = provider_config_service.draft_delete_provider(isolated.config, draft_meta={},
        base_hash=public_config_hash(isolated.config), provider_id="relay_target")["publicConfig"]
    assert "relay_target" not in deleted["llm"]["providers"]


@pytest.mark.parametrize("state,blocking", [(state, True) for state in ("reserved", "journaled", "projected")]
    + [(state, False) for state in ("rejected", "expired")])
def test_only_active_admissions_hold_a_compiled_revision(isolated, state, blocking):
    _seed_owner(isolated, "session")
    with sqlite3.connect(isolated.db) as connection:
        # Isolate the admission authority from the Session and current Agent pins.
        connection.execute("UPDATE sessions SET agent_config_revision_id="
            "(SELECT current_config_revision_id FROM agents WHERE agent_id='agent-a')")
        connection.execute("INSERT INTO session_admissions "
            "(session_id,client_submission_id,turn_id,agent_id,agent_config_revision_id,state,created_at_ms,updated_at_ms) "
            "VALUES ('session-a','request-a','turn-a','agent-a',?,?,1,1)", (isolated.original_revision, state))

    impact = model_reference_service.scan_model_references(TARGET)
    assert impact["blocking"] is blocking
    assert model_reference_service.scan_provider_live_references("relay_target")["blocking"] is blocking
    if blocking:
        assert {ref["ownerType"] for ref in impact["liveReferences"]} == {"admission"}
        assert {ref["ownerId"] for ref in impact["liveReferences"]} == {"turn-a"}


def test_compiled_pin_scan_projects_only_binding_fields(isolated):
    with ConversationStore(isolated.db) as store:
        store.repository.create_agent(agent_id="agent-a", display_name="Fixture", kind="chat",
            config={**_binding(TARGET), "prompt": "unrelated prompt " * 100_000}, source="test").result(timeout=5)
    bindings = model_reference_service._iter_agent_store_bindings(isolated.root)
    assert len(bindings) == 1
    payload = bindings[0][-1]
    assert payload["dialogueModelId"] == TARGET
    assert payload["llmBindings"]["dialogue"]["modelId"] == TARGET
    assert "prompt" not in payload
    assert len(json.dumps(payload)) < 500
