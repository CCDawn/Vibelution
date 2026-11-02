"""Handoff metadata reads retain the existing operator and ACL authorities."""
from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

import vibelution_storage as storage
from config import paths as config_paths
from core.infrastructure import storage_owner_handoff as handoff
from core.web.services import team_knowledge_service as knowledge
from core.web.services.external_management import knowledge_directory as catalog
from core.web.services.external_management.service import ManagementError
from core.web.services.team_workflow.research_runtime.operator_authorization import server_operator_scope
from tests.test_assistant_knowledge_owner_catalog import owner_env
from tests.test_launcher_assistant_knowledge_directory import env
from tests.test_storage_owner_handoff import files, other_owner_source, replace_config

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows pinned owner authority")


@pytest.fixture
def relocated(owner_env):
    e = owner_env
    (e.root / ".git").mkdir()
    e.marker.unlink()
    old_root = e.root.parent / "former-checkout"
    old_id = storage.instance_id_for_project(old_root)
    source = e.paths.project_home / "instances" / old_id / "data"
    source.parent.mkdir(parents=True)
    e.paths.data.rename(source)
    e.workspace = source / "workspace"
    e.path = e.workspace / "teams" / "team-a" / "knowledge" / "knowledge_bases.json"
    e.teams_path = e.workspace / "teams" / "teams.json"
    e.agent_path = e.workspace / "agents" / "agent-a" / "knowledge" / "knowledge_bases.json"
    e.agents_path = e.workspace / "agents" / "agents.json"
    e.source_marker = source.parent / storage.STORAGE_MIGRATION_STATE_NAME
    e.source_marker.write_text(json.dumps({"schemaVersion": 1, "status": "completed", "projectId": e.paths.project_id,
        "instanceId": old_id, "projectRoot": str(old_root), "targetRoot": str(source.parent)}), encoding="utf-8")
    e.config.write_text('[storage]\ndata_home = ' + json.dumps(str(source)) + '\n', encoding="utf-8")
    e.plan = handoff.plan_storage_owner_handoff(e.root)
    return e


def commit(e):
    return handoff.apply_storage_owner_handoff(e.root, plan_digest=e.plan["planDigest"],
        confirm_relocated_data=True, request_id="knowledge-handoff-1")


def read(e):
    with server_operator_scope("operator-test", roles=("operator",)):
        return catalog.read_knowledge_directory(e.root, e.directory)


def test_unproven_configured_old_owner_still_denied_and_valid_handoff_keeps_native_acl(relocated):
    e = relocated
    with pytest.raises(ManagementError) as denied:
        read(e)
    assert denied.value.code == "KNOWLEDGE_DIRECTORY_UNAVAILABLE"
    commit(e)
    before = files(e.root.parent)
    result = read(e)
    assert result["status"] == "available" and result["total"] == 3
    assert {row["scopedKnowledgeBaseId"] for row in result["knowledgeBases"]} == {
        "team:team-a:kb-a", "team:knowledge-expansion-team:kb-a", "agent:agent-a:kb-a"}
    assert all(set(row) == {"knowledgeBaseId", "scopedKnowledgeBaseId", "ownerType", "ownerId", "status", "fingerprint", "name"}
               for row in result["knowledgeBases"])
    assert "PRIVATE" not in json.dumps(result) and files(e.root.parent) == before
    # The ordinary public-Team reader retains hidden/system exclusions.
    assert catalog.read_team_knowledge_directory(e.root, e.directory, "team-a")["total"] == 1
    with pytest.raises(ManagementError):
        catalog.read_team_knowledge_directory(e.root, e.directory, "knowledge-expansion-team")


def test_handoff_does_not_grant_operator_or_seed_any_owner(relocated, monkeypatch):
    e = relocated
    commit(e)
    def forbidden(*args, **kwargs):
        pytest.fail("handoff called a body read, hydration or write")
    for name in ("load_state", "get_agent", "list_agents"):
        monkeypatch.setattr(knowledge.agent_directory_service, name, forbidden)
    for name in ("_route_team_knowledge_workspace_path", "_read_jsonl", "_write_json", "list_team_knowledge_bases",
                 "_knowledge_base_stats_for_owner", "_require_base_with_owner"):
        monkeypatch.setattr(knowledge, name, forbidden)
    with pytest.raises(ManagementError) as denied:
        catalog.read_knowledge_directory(e.root, e.directory)
    assert denied.value.code == "OPERATOR_CONTROL_REQUIRED"
    with server_operator_scope("reader", roles=("reader",)):
        with pytest.raises(ManagementError) as denied:
            catalog.read_knowledge_directory(e.root, e.directory)
        assert denied.value.code == "OPERATOR_CONTROL_REQUIRED"
    before = files(e.root.parent)
    assert read(e)["total"] == 3 and files(e.root.parent) == before


@pytest.mark.parametrize("drift", ["source", "config-route", "proof", "revoked", "canonical-marker", "acl"])
def test_knowledge_reader_rejects_drift_and_keeps_acl_validation(relocated, drift):
    e = relocated
    commit(e)
    if drift == "source":
        e.source_marker.write_text(e.source_marker.read_text(encoding="utf-8") + " ", encoding="utf-8")
    elif drift == "config-route":
        e.config.write_text('[storage]\ndata_home="different"\n', encoding="utf-8")
    elif drift == "proof":
        (e.paths.instance_home / handoff.RECORD_NAME).unlink()
    elif drift == "revoked":
        digest = handoff.plan_storage_owner_handoff(e.root)["recordDigest"]
        handoff.revoke_storage_owner_handoff(e.root, record_digest=digest, request_id="revoke-knowledge")
    elif drift == "canonical-marker":
        e.marker.write_text(json.dumps({"schemaVersion": 1, "status": "completed", "projectId": e.paths.project_id,
            "instanceId": e.paths.instance_id, "projectRoot": str(e.root)}), encoding="utf-8")
    else:
        e.agent_base["acl"] = {"read": ["invalid-acl"]}
        e.agent_path.write_text(json.dumps({"schemaVersion": 1, "knowledgeBases": [e.agent_base]}), encoding="utf-8")
        result = read(e)
        assert result["status"] == "partial" and result["total"] == 2
        return
    with pytest.raises(ManagementError) as unavailable:
        read(e)
    assert unavailable.value.code == "KNOWLEDGE_DIRECTORY_UNAVAILABLE"


def test_unrelated_config_update_keeps_handoff_knowledge_available(relocated):
    e = relocated
    commit(e)
    before = read(e)
    replace_config(e.config, e.config.read_text(encoding="utf-8") + '\n[provider]\nname="new"\n[assistant]\ndispatch_allowlist=["agent-a"]\n')
    after = read(e)
    assert after["knowledgeBases"] == before["knowledgeBases"]


@pytest.mark.parametrize("initial_explicit", [False, True])
def test_same_owner_environment_transition_keeps_knowledge_available(relocated, monkeypatch, initial_explicit):
    e = relocated
    source = e.workspace.parent
    if initial_explicit:
        monkeypatch.setenv(config_paths.DATA_HOME_ENV, str(source))
        e.plan = handoff.plan_storage_owner_handoff(e.root)
    commit(e)
    before = read(e)
    if initial_explicit:
        monkeypatch.delenv(config_paths.DATA_HOME_ENV)
    else:
        monkeypatch.setenv(config_paths.DATA_HOME_ENV, str(source))
    after = read(e)
    assert after["knowledgeBases"] == before["knowledgeBases"]


def test_foreign_environment_owner_in_same_project_home_cannot_borrow_knowledge(relocated, monkeypatch):
    e = relocated
    commit(e)
    foreign = other_owner_source(SimpleNamespace(target=e.paths, tmp=e.root.parent))
    monkeypatch.setenv(config_paths.DATA_HOME_ENV, str(foreign))
    with pytest.raises(ManagementError) as unavailable:
        read(e)
    assert unavailable.value.code == "KNOWLEDGE_DIRECTORY_UNAVAILABLE"


def test_during_read_revoke_source_and_config_mutation_are_pinned(relocated, monkeypatch):
    e = relocated
    commit(e)
    original = catalog._catalog_owners
    blocked = []
    def observed(*args, **kwargs):
        for path in (e.source_marker, e.config, e.paths.instance_home / handoff.RECORD_NAME):
            try:
                path.write_bytes(b"mutate")
            except PermissionError:
                blocked.append(path.name)
            else:
                pytest.fail("owner authority changed during metadata read")
        return original(*args, **kwargs)
    monkeypatch.setattr(catalog, "_catalog_owners", observed)
    assert read(e)["total"] == 3
    assert set(blocked) == {"storage-migration.json", "config.toml", handoff.RECORD_NAME}
