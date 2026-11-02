"""Operator discovery uses native owners and exact, existing-only ACL identities."""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from core.web.services import team_knowledge_service as knowledge
from core.web.services.external_management import knowledge_directory as catalog
from core.web.services.external_management.asset_control import AssetControl
from core.web.services.external_management.knowledge_catalog_contracts import KnowledgeCatalogQuery, KnowledgeCatalogResponse
from core.web.services.external_management.service import ManagementError
from core.web.services.team_workflow.research_runtime.operator_authorization import server_operator_scope
from tests.test_launcher_assistant_knowledge_directory import env
from tests.test_external_management_workspace_queries import snapshot

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows pinned-source authority")


@pytest.fixture
def owner_env(env, monkeypatch):
    from core.web.services import agent_directory_service as directory
    monkeypatch.setattr(directory, "PROJECT_ROOT", env.root)
    monkeypatch.setattr(directory, "CONFIG_PATH", env.config)
    env.agents_path = env.workspace / "agents" / "agents.json"
    env.agents_path.parent.mkdir(parents=True)
    env.agents_path.write_text(json.dumps({"agents": [{"agentId": "agent-a", "status": "active", "hidden": True}]}), encoding="utf-8")
    env.base["acl"] = {"read": "team", "propose": "team", "review": "review_roles", "grants": {"read": ["reader"]}}
    env.write_bases()
    env.agent_path = env.workspace / "agents" / "agent-a" / "knowledge" / "knowledge_bases.json"
    env.agent_path.parent.mkdir(parents=True)
    env.agent_base = {**env.base, "ownerType": "agent", "ownerId": "agent-a", "agentId": "agent-a", "teamId": "",
                      "name": "Private agent library", "status": "archived"}
    env.agent_path.write_text(json.dumps({"schemaVersion": 1, "knowledgeBases": [env.agent_base]}), encoding="utf-8")
    env.system_id = "knowledge-expansion-team"
    env.write([env.team, {**env.team, "teamId": env.system_id, "teamKind": "knowledge_expansion", "teamSource": "knowledge_expansion"}])
    env.system_path = env.workspace / "teams" / env.system_id / "knowledge" / "knowledge_bases.json"
    env.system_path.parent.mkdir(parents=True)
    env.system_base = {**env.base, "ownerId": env.system_id, "teamId": env.system_id, "name": "System library"}
    env.system_path.write_text(json.dumps({"schemaVersion": 1, "knowledgeBases": [env.system_base]}), encoding="utf-8")
    return env


def read(env, **kwargs):
    with server_operator_scope("operator-test", roles=("operator",)):
        return catalog.read_knowledge_directory(env.root, env.directory, **kwargs)


def test_unknown_library_ids_are_discoverable_then_query_exact_native_acl(owner_env):
    env = owner_env
    before = snapshot(env)
    result = read(env)
    assert result["status"] == "available" and result["total"] == 3
    assert result["requiredScopes"] == ["knowledge:catalog:read"]
    assert {entry["ownerType"] for entry in result["knowledgeBases"]} == {"agent", "team"}
    assert any(entry["ownerId"] == env.system_id for entry in result["knowledgeBases"])
    native = SimpleNamespace(project_root=env.root, _owners=lambda: env.directory)
    with server_operator_scope("operator-test", roles=("operator",)):
        for entry in result["knowledgeBases"]:
            acl = AssetControl(native).read_knowledge_acl(entry["scopedKnowledgeBaseId"])
            assert acl["fingerprint"] == entry["fingerprint"]
            assert acl["scopedKnowledgeBaseId"] == f"{entry['ownerType']}:{entry['ownerId']}:kb-a"
    assert "PRIVATE" not in json.dumps(result) and "acl" not in result["knowledgeBases"][0]
    assert snapshot(env) == before
    assert read(env, owner_type="agent", owner_id="agent-a")["total"] == 1
    assert read(env, owner_type="team", query="System library")["knowledgeBases"][0]["ownerId"] == env.system_id
    # The old Team-only, public/ordinary directory remains unchanged.
    assert catalog.read_team_knowledge_directory(env.root, env.directory, "team-a")["knowledgeBases"] == [
        {"id": "kb-a", "name": "Public name", "status": "active"}]


def test_catalog_enforces_native_operator_and_never_initializes(owner_env, monkeypatch):
    env = owner_env
    def forbidden(*_args, **_kwargs):
        pytest.fail("catalog called a hydrating, writing or body-reading API")
    for name in ("load_state", "get_agent", "list_agents"):
        monkeypatch.setattr(knowledge.agent_directory_service, name, forbidden)
    for name in ("_route_team_knowledge_workspace_path", "_read_jsonl", "_write_json", "list_team_knowledge_bases",
                 "_knowledge_base_stats_for_owner", "_require_base_with_owner"):
        monkeypatch.setattr(knowledge, name, forbidden)
    before = snapshot(env)
    with pytest.raises(ManagementError) as denied:
        catalog.read_knowledge_directory(env.root, env.directory)
    assert denied.value.code == "OPERATOR_CONTROL_REQUIRED"
    with server_operator_scope("unprivileged", roles=("reader",)):
        with pytest.raises(ManagementError) as denied:
            catalog.read_knowledge_directory(env.root, env.directory)
        assert denied.value.code == "OPERATOR_CONTROL_REQUIRED"
    assert read(env)["total"] == 3
    assert snapshot(env) == before


@pytest.mark.parametrize("change", ["missing", "broken", "wrong-owner", "owner-alias", "case-collision", "bad-acl", "missing-owner", "orphan"])
def test_missing_damaged_and_unknown_ownership_is_explicit_and_read_only(owner_env, change):
    env = owner_env
    if change == "missing":
        env.agent_path.unlink()
    elif change == "broken":
        env.agent_path.write_text("broken", encoding="utf-8")
    elif change in {"wrong-owner", "owner-alias", "bad-acl", "case-collision"}:
        row = {**env.agent_base}
        if change == "wrong-owner":
            row["ownerId"] = "another-agent"
        if change == "owner-alias":
            row["team_id"] = "a-team"
        if change == "bad-acl":
            row["acl"] = {"read": ["malformed"]}
        rows = [row, {**row, "knowledgeBaseId": "KB-A"}] if change == "case-collision" else [row]
        env.agent_path.write_text(json.dumps({"schemaVersion": 1, "knowledgeBases": rows}), encoding="utf-8")
    elif change == "missing-owner":
        env.agents_path.unlink()
    elif change == "orphan":
        path = env.workspace / "agents" / "unregistered" / "knowledge" / "knowledge_bases.json"
        path.parent.mkdir(parents=True)
        path.write_bytes(env.agent_path.read_bytes())
    before = snapshot(env)
    result = read(env)
    assert result["status"] == "partial" and result["issues"]
    assert result["total"] == (3 if change == "orphan" else 2)
    focused = read(env, owner_type="agent", owner_id="missing" if change == "orphan" else "agent-a")
    assert focused["status"] == "unavailable" and focused["total"] == 0
    assert snapshot(env) == before


def test_empty_existing_metadata_is_distinct_from_missing_authority(owner_env):
    env = owner_env
    env.agent_path.write_text('{"schemaVersion":1,"knowledgeBases":[]}', encoding="utf-8")
    result = read(env, owner_type="agent", owner_id="agent-a")
    assert result["status"] == "available" and result["total"] == 0 and result["issues"] == []
    env.agent_path.unlink()
    result = read(env, owner_type="agent", owner_id="agent-a")
    assert result["status"] == "unavailable" and result["issues"] == ["library_authority_unavailable"]


def test_catalog_pages_are_digest_bound_and_no_owner_or_query_filter_can_reuse_them(owner_env):
    env = owner_env
    env.write_bases([{**env.base, "knowledgeBaseId": f"kb-{index:02}"} for index in reversed(range(9))])
    first = read(env, owner_type="team", limit=4)
    found = first["knowledgeBases"][:]
    current = first
    while current["nextOffset"] is not None:
        current = read(env, owner_type="team", limit=4, offset=current["nextOffset"], expected_digest=first["digest"])
        found.extend(current["knowledgeBases"])
    assert len(found) == first["total"] == 10
    assert len({row["scopedKnowledgeBaseId"] for row in found}) == 10
    for options in ({"query": "no-match"}, {"owner_type": "agent"}):
        with pytest.raises(ManagementError) as conflict:
            read(env, offset=4, expected_digest=first["digest"], **options)
        assert conflict.value.code == "STATE_CONFLICT"
    env.write_bases([{**env.base, "knowledgeBaseId": f"kb-{index:02}"} for index in range(10)])
    with pytest.raises(ManagementError) as conflict:
        read(env, owner_type="team", offset=4, expected_digest=first["digest"])
    assert conflict.value.code == "STATE_CONFLICT"


@pytest.mark.parametrize("parameters", [{"offset": 1}, {"owner_id": "agent-a"}, {"owner_type": "system"},
    {"owner_type": "agent", "actor_agent_id": "agent-a"}, {"limit": 7}, {"limit": True}, {"offset": -1}])
def test_catalog_schema_is_closed_and_bounded(parameters):
    with pytest.raises(ValidationError):
        KnowledgeCatalogQuery.model_validate(parameters)


def test_catalog_responses_remain_closed(owner_env):
    result = read(owner_env)
    assert KnowledgeCatalogResponse.model_validate(result).model_dump() == result
    with pytest.raises(ValidationError):
        KnowledgeCatalogResponse.model_validate({**result, "body": "not metadata"})
    result["knowledgeBases"][0]["ownerId"] = "forged"
    with pytest.raises(ValidationError):
        KnowledgeCatalogResponse.model_validate(result)


def test_long_metadata_pages_fit_native_tool_budget_without_losing_items(owner_env, monkeypatch):
    from tests.test_assistant_runtime_actions import _through_native_model_budget
    env = owner_env
    long_owner = "a" * 128
    env.agents_path.write_text(json.dumps({"agents": [{"agentId": long_owner, "status": "active"}]}), encoding="utf-8")
    env.agent_path.unlink()
    long_path = env.workspace / "agents" / long_owner / "knowledge" / "knowledge_bases.json"
    long_path.parent.mkdir(parents=True)
    rows = [{**env.agent_base, "ownerId": long_owner, "agentId": long_owner,
             "knowledgeBaseId": "k" * 125 + f"{index:03}", "name": "知" * 64} for index in range(9)]
    long_path.write_text(json.dumps({"schemaVersion": 1, "knowledgeBases": rows}), encoding="utf-8")
    seen, offset, digest = [], 0, ""
    reads = []
    original = catalog.read_stable_file
    def tracked(path, *args, **kwargs):
        reads.append(Path(path))
        return original(path, *args, **kwargs)
    monkeypatch.setattr(catalog, "read_stable_file", tracked)
    while True:
        reads.clear()
        page = read(env, owner_type="agent", offset=offset, expected_digest=digest)
        digest = page["digest"]
        assert len(page["knowledgeBases"]) < 6
        assert reads.count(env.agents_path) == reads.count(long_path) == 1
        raw, outcome, facts, rendered = _through_native_model_budget({**page, "projectId": "p" * 160})
        assert len(raw) <= 3400 and outcome is None and not facts.truncated
        assert json.loads(rendered.split("\nResult:\n", 1)[1]) == json.loads(raw)
        seen.extend(row["scopedKnowledgeBaseId"] for row in page["knowledgeBases"])
        if page["nextOffset"] is None:
            break
        offset = page["nextOffset"]
    assert len(seen) == len(set(seen)) == 9


def test_metadata_change_during_projection_fails_closed(owner_env, monkeypatch):
    env = owner_env
    original = knowledge.read_operator_knowledge_base_acl
    changed = False
    def mutate_after_read(reference, **kwargs):
        nonlocal changed
        result = original(reference, **kwargs)
        if not changed:
            changed = True
            env.agent_path.write_text(json.dumps({"schemaVersion": 1, "knowledgeBases": []}), encoding="utf-8")
        return result
    monkeypatch.setattr(knowledge, "read_operator_knowledge_base_acl", mutate_after_read)
    with pytest.raises(ManagementError) as conflict:
        read(env)
    assert changed and conflict.value.code == "KNOWLEDGE_DIRECTORY_UNAVAILABLE"
