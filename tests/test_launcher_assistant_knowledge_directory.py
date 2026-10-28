"""Existing-only Team knowledge catalog projection; no target transport yet."""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from types import SimpleNamespace
from pathlib import Path

import pytest

from tests.test_external_management_workspace_queries import snapshot

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows pinned-source authority")


@pytest.fixture
def env(tmp_path, monkeypatch):
    import vibelution_storage as storage
    from config import paths as config_paths
    from core.web.services import team_knowledge_service, team_service
    root = tmp_path / "project"
    (root / ".vibelution").mkdir(parents=True)
    identity = root / ".vibelution" / "project.json"
    identity.write_text('{"schemaVersion":1,"projectId":"test-project"}', encoding="utf-8")
    config = tmp_path / "config.toml"
    config.write_text("[launcher.developer_mode]\nenabled = false\n", encoding="utf-8")
    monkeypatch.setenv(storage.PROJECTS_HOME_ENV, str(tmp_path / "projects"))
    monkeypatch.setenv(config_paths.CONFIG_PATH_ENV, str(config))
    monkeypatch.delenv(config_paths.DATA_HOME_ENV, raising=False)
    paths = storage.resolve_project_storage_paths(root)
    marker = storage.storage_migration_state_path(paths)
    marker.parent.mkdir(parents=True)
    marker.write_text(json.dumps({"schemaVersion": 1, "status": "completed", "projectId": "test-project", "instanceId": paths.instance_id, "projectRoot": str(root)}), encoding="utf-8")
    workspace = paths.workspace
    workspace.mkdir(parents=True)
    team = {"teamId": "team-a", "name": "Ordinary team", "status": "active", "purpose": "Coordinate",
            "teamKind": "custom", "teamSource": "manual", "members": [{"agentId": "agent-a"}]}
    teams_path = workspace / "teams" / "teams.json"
    teams_path.parent.mkdir(parents=True)
    def write(teams=None):
        teams_path.write_text(json.dumps({"teams": [team] if teams is None else teams}), encoding="utf-8")
    write()
    directory = SimpleNamespace(CONFIG_PATH=config, PROJECT_ROOT=root)
    monkeypatch.setattr(team_service, "PROJECT_ROOT", root)
    monkeypatch.setattr(team_knowledge_service, "PROJECT_ROOT", root)
    e = SimpleNamespace(root=root, workspace=workspace, config=config, directory=directory, paths=paths,
                        identity=identity, marker=marker, team=team, teams_path=teams_path, write=write)
    e.path = workspace / "teams" / "team-a" / "knowledge" / "knowledge_bases.json"
    e.path.parent.mkdir(parents=True)
    e.base = {"knowledgeBaseId": "kb-a", "ownerType": "team", "ownerId": "team-a", "teamId": "team-a",
              "agentId": "", "name": "Public name", "status": "active", "description": "PRIVATE DESCRIPTION",
              "acl": {"read": ["PRIVATE ACL"]}}
    def write_bases(rows=None):
        e.path.write_text(json.dumps({"schemaVersion": 1, "knowledgeBases": [e.base] if rows is None else rows}), encoding="utf-8")
    e.write_bases = write_bases
    e.write_bases()
    return e


def read(env, team_id="team-a", **options):
    from core.web.services.external_management.knowledge_directory import read_team_knowledge_directory
    return read_team_knowledge_directory(env.root, env.directory, team_id, **options)


def test_team_catalog_is_existing_only_and_projects_no_acl_body_or_stats(env, monkeypatch):
    from core.web.services import team_knowledge_service as knowledge
    from core.web.services.external_management import knowledge_directory as reader
    def forbidden(*_args, **_kwargs):
        pytest.fail("legacy knowledge reader, write or initialization called")
    for name in ("list_team_knowledge_catalog", "list_team_knowledge_bases", "_knowledge_base_stats_for_owner",
                 "_knowledge_bases_for_owner", "_route_team_knowledge_workspace_path"):
        monkeypatch.setattr(knowledge, name, forbidden)
    observed = []
    original = reader.read_stable_file
    def tracked(path, maximum, **kwargs):
        observed.append(path.name)
        return original(path, maximum, **kwargs)
    monkeypatch.setattr(reader, "read_stable_file", tracked)
    before = snapshot(env)
    result = read(env)
    assert result["knowledgeBases"] == [{"id": "kb-a", "name": "Public name", "status": "active"}]
    assert result["requiredScopes"] == ["knowledge:catalog:read", "teams:directory:read"]
    assert "decoded" in result["coverage"]
    assert "PRIVATE" not in json.dumps(result) and set(result["knowledgeBases"][0]) == {"id", "name", "status"}
    assert set(observed) == {"project.json", "config.toml", "storage-migration.json", "teams.json", "knowledge_bases.json"}
    assert snapshot(env) == before


def test_empty_and_paginated_metadata_never_fabricates_authority(env):
    from tests.test_assistant_runtime_actions import _through_native_model_budget
    env.write_bases([])
    assert read(env)["knowledgeBases"] == []
    rows = [{**env.base, "knowledgeBaseId": f"kb-{index}"} for index in reversed(range(8))]
    rows.append({**env.base, "knowledgeBaseId": "kb-archived", "status": "archived"})
    env.write_bases(rows)
    first = read(env)
    assert first["total"] == 8 and first["nextOffset"] == 6
    assert [row["id"] for row in first["knowledgeBases"]] == [f"kb-{i}" for i in range(6)]
    assert [row["id"] for row in read(env, offset=6)["knowledgeBases"]] == ["kb-6", "kb-7"]
    raw, outcome, facts, rendered = _through_native_model_budget({**first, "projectId": "p" * 160})
    assert outcome is None and not facts.truncated and json.loads(rendered.split("\nResult:\n", 1)[1]) == json.loads(raw)


@pytest.mark.parametrize("change", ["missing", "broken", "private-team", "archived-team", "wrong-owner-type", "wrong-owner-id", "wrong-team-id", "agent-owned", "unknown-status", "bad-schema", "duplicate-base", "case-base", "case-team", "normalized-team", "wrong-project"])
def test_unavailable_or_ambiguous_authority_fails_closed(env, change):
    from core.web.services.external_management.service import ManagementError
    if change == "missing":
        env.path.unlink()
    elif change == "broken":
        env.path.write_text("{", encoding="utf-8")
    elif change in {"private-team", "archived-team"}:
        env.team.update({"hidden": True} if change == "private-team" else {"status": "archived"})
        env.write()
    elif change in {"wrong-owner-type", "wrong-owner-id", "wrong-team-id", "agent-owned", "unknown-status"}:
        env.base.update({"wrong-owner-type": {"ownerType": "agent"}, "wrong-owner-id": {"ownerId": "team-b"},
            "wrong-team-id": {"teamId": "team-b"}, "agent-owned": {"agentId": "agent-a"},
            "unknown-status": {"status": "draft"}}[change])
        env.write_bases()
    elif change == "bad-schema":
        env.path.write_text('{"schemaVersion":true,"knowledgeBases":[]}', encoding="utf-8")
    elif change == "duplicate-base":
        env.write_bases([env.base, env.base])
    elif change == "case-base":
        env.write_bases([env.base, {**env.base, "knowledgeBaseId": "KB-A"}])
    elif change in {"case-team", "normalized-team"}:
        conflicting = {**env.team, "teamId": "TEAM-A" if change == "case-team" else "team:a"}
        env.write([env.team, conflicting])
    else:
        env.directory.PROJECT_ROOT = env.root / "different"
    with pytest.raises(ManagementError) as error:
        read(env)
    assert error.value.code == "KNOWLEDGE_DIRECTORY_UNAVAILABLE"


@pytest.mark.parametrize("changed", ["team", "knowledge", "config"])
def test_authority_change_before_guard_is_unavailable(env, monkeypatch, changed):
    from core.web.services.external_management import knowledge_directory as reader
    from core.web.services.external_management.service import ManagementError
    original = reader.pinned_source_files
    @contextmanager
    def changing(sources):
        names = {item.path.name for item in sources}
        if changed in {"team", "knowledge"} and "teams.json" not in names:
            with original(sources):
                yield
            return
        if changed == "config" and "config.toml" not in names:
            with original(sources):
                yield
            return
        if changed == "team":
            env.team["hidden"] = True
            env.write()
        elif changed == "knowledge":
            env.base["name"] = "Changed"
            env.write_bases()
        else:
            env.config.write_text("[launcher.developer_mode]\nenabled = true\n", encoding="utf-8")
        with original(sources):
            yield
    monkeypatch.setattr(reader, "pinned_source_files", changing)
    with pytest.raises(ManagementError) as error:
        read(env)
    assert error.value.code == "KNOWLEDGE_DIRECTORY_UNAVAILABLE"


def test_linked_metadata_and_missing_developer_authority_are_unavailable(env):
    from core.web.services.external_management.service import ManagementError
    os.link(env.path, env.path.parent / "other-link.json")
    with pytest.raises(ManagementError):
        read(env)
    env.config.write_text("[launcher.developer_mode]\nenabled = true\n", encoding="utf-8")
    with pytest.raises(ManagementError):
        read(env)


def test_developer_sandbox_is_read_without_formal_fallback_or_seeding(env, monkeypatch):
    from core.infrastructure import developer_sandbox
    sandbox = env.paths.runtime / "developer-mode" / "sandboxes" / "sandbox-a"
    workspace = sandbox / "workspace"
    team_path = workspace / "teams" / "teams.json"
    base_path = workspace / "teams" / "team-a" / "knowledge" / "knowledge_bases.json"
    team_path.parent.mkdir(parents=True)
    base_path.parent.mkdir(parents=True)
    team_path.write_bytes(env.teams_path.read_bytes())
    base_path.write_text(json.dumps({"schemaVersion": 1, "knowledgeBases": [{**env.base, "name": "Sandbox only"}]}), encoding="utf-8")
    active = env.paths.runtime / "developer-mode" / "active.json"
    active.parent.mkdir(parents=True, exist_ok=True)
    active.write_text('{"schemaVersion":1,"sandboxId":"sandbox-a"}', encoding="utf-8")
    env.config.write_text("[launcher.developer_mode]\nenabled = true\n", encoding="utf-8")
    before = snapshot(env)
    result = read(env)
    assert result["knowledgeBases"][0]["name"] == "Sandbox only" and snapshot(env) == before
    base_path.unlink()
    from core.web.services.external_management.service import ManagementError
    with pytest.raises(ManagementError):
        read(env)
    assert not base_path.exists()


@pytest.mark.parametrize("options", [{"offset": -1}, {"limit": 7}, {"limit": True}, {"offset": 10001}])
def test_query_bounds_are_strict(env, options):
    from core.web.services.external_management.service import ManagementError
    with pytest.raises(ManagementError) as error:
        read(env, **options)
    assert error.value.code == "INVALID_INPUT"


@pytest.mark.parametrize("kind", ["missing", "broken", "duplicate", "replaced"])
def test_project_identity_is_required_and_pinned(env, monkeypatch, kind):
    from core.web.services.external_management import knowledge_directory as reader
    from core.web.services.external_management.service import ManagementError
    if kind == "missing":
        env.identity.unlink()
    elif kind == "broken":
        env.identity.write_text("{", encoding="utf-8")
    elif kind == "duplicate":
        env.identity.write_text('{"schemaVersion":1,"projectId":"test-project","projectId":"other"}', encoding="utf-8")
    else:
        original = reader.pinned_source_files
        @contextmanager
        def replace(sources):
            if any(item.path == env.identity for item in sources):
                env.identity.unlink()
                env.identity.write_text('{"schemaVersion":1,"projectId":"other-project"}', encoding="utf-8")
            with original(sources):
                yield
        monkeypatch.setattr(reader, "pinned_source_files", replace)
    with pytest.raises(ManagementError) as error:
        read(env)
    assert error.value.code == "KNOWLEDGE_DIRECTORY_UNAVAILABLE"


def test_config_replacement_aba_is_rejected_before_route(env, monkeypatch):
    from core.web.services.external_management import knowledge_directory as reader
    from core.web.services.external_management.service import ManagementError
    original = reader.pinned_source_files
    @contextmanager
    def replace(sources):
        if any(item.path == env.config for item in sources):
            content = env.config.read_bytes()
            env.config.unlink()
            env.config.write_bytes(b"[launcher.developer_mode]\nenabled = true\n")
            env.config.unlink()
            env.config.write_bytes(content)
        with original(sources):
            yield
    monkeypatch.setattr(reader, "pinned_source_files", replace)
    with pytest.raises(ManagementError) as error:
        read(env)
    assert error.value.code == "KNOWLEDGE_DIRECTORY_UNAVAILABLE"


def test_reserved_system_team_case_alias_is_not_visible(env):
    from core.web.services.team.kind_helpers import SYSTEM_MANAGED_TEAM_IDS
    from core.web.services.external_management.service import ManagementError
    for tid in SYSTEM_MANAGED_TEAM_IDS:
        alias = tid.upper()
        env.write([{**env.team, "teamId": alias}])
        with pytest.raises(ManagementError) as error:
            read(env, alias)
        assert error.value.code == "KNOWLEDGE_DIRECTORY_UNAVAILABLE"



def test_config_cannot_change_during_native_route_resolution(env, monkeypatch):
    from core.web.services.external_management import knowledge_directory as reader
    original = reader.storage.resolve_project_storage_paths
    attempted = []
    def replacing(root, *args, **kwargs):
        try:
            env.config.write_text("[launcher.developer_mode]\nenabled = true\n", encoding="utf-8")
        except PermissionError:
            attempted.append("blocked")
        else:
            pytest.fail("configuration was mutable while determining workspace")
        return original(root, *args, **kwargs)
    monkeypatch.setattr(reader.storage, "resolve_project_storage_paths", replacing)
    assert read(env)["knowledgeBases"][0]["id"] == "kb-a"
    assert attempted and all(item == "blocked" for item in attempted)


@pytest.mark.parametrize("kind", ["missing-marker", "bad-marker", "shared-override"])
def test_unproven_project_workspace_is_unavailable(env, kind):
    from core.web.services.external_management.service import ManagementError
    if kind == "missing-marker":
        env.marker.unlink()
    elif kind == "bad-marker":
        env.marker.write_text('{"schemaVersion":1,"status":"completed","projectId":"other"}', encoding="utf-8")
    else:
        env.config.write_text('[storage]\ndata_home = "shared"\n', encoding="utf-8")
    with pytest.raises(ManagementError) as error:
        read(env)
    assert error.value.code == "KNOWLEDGE_DIRECTORY_UNAVAILABLE"


@pytest.mark.parametrize("owner", ["missing", "wrong", "case-only"])
def test_migration_owner_must_match_physical_project(env, owner):
    from core.web.services.external_management.service import ManagementError
    marker = json.loads(env.marker.read_text(encoding="utf-8"))
    if owner == "missing":
        del marker["projectRoot"]
    elif owner == "wrong":
        marker["projectRoot"] = str(env.root.parent)
    else:
        marker["projectRoot"] = str(env.root).swapcase()
    env.marker.write_text(json.dumps(marker), encoding="utf-8")
    if owner == "case-only":
        assert read(env)["knowledgeBases"][0]["id"] == "kb-a"
    else:
        with pytest.raises(ManagementError) as error:
            read(env)
        assert error.value.code == "KNOWLEDGE_DIRECTORY_UNAVAILABLE"


def test_colliding_project_instance_cannot_read_other_projects_team(env, monkeypatch):
    import random
    import vibelution_storage as storage
    from core.web.services import team_knowledge_service, team_service
    from core.web.services.external_management.service import ManagementError
    # The native FNV-1a32 slot ID is not injective. Construct a collision
    # within the pytest temporary root without touching any other project.
    randomizer = random.Random(81023)
    seen = {}
    collision = None
    for _ in range(400_000):
        candidate = env.root.parent / f"project-{randomizer.getrandbits(64):016x}"
        slot = storage.slot_id_for_key(os.path.normcase(str(candidate)))
        if slot in seen and seen[slot] != candidate:
            collision = seen[slot], candidate
            break
        seen[slot] = candidate
    assert collision is not None
    owner, other = collision
    for project in collision:
        (project / ".vibelution").mkdir(parents=True)
        (project / ".vibelution" / "project.json").write_text(
            '{"schemaVersion":1,"projectId":"test-project"}', encoding="utf-8")
    owner_paths = storage.resolve_project_storage_paths(owner)
    assert storage.resolve_project_storage_paths(other).instance_id == owner_paths.instance_id
    marker = storage.storage_migration_state_path(owner_paths)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"schemaVersion": 1, "status": "completed", "projectId": "test-project",
                                  "instanceId": owner_paths.instance_id, "projectRoot": str(owner)}), encoding="utf-8")
    team_path = owner_paths.workspace / "teams" / "teams.json"
    kb_path = owner_paths.workspace / "teams" / "team-a" / "knowledge" / "knowledge_bases.json"
    team_path.parent.mkdir(parents=True, exist_ok=True)
    kb_path.parent.mkdir(parents=True, exist_ok=True)
    team_path.write_bytes(env.teams_path.read_bytes())
    kb_path.write_bytes(env.path.read_bytes())
    def select(project):
        env.directory.PROJECT_ROOT = project
        monkeypatch.setattr(team_service, "PROJECT_ROOT", project)
        monkeypatch.setattr(team_knowledge_service, "PROJECT_ROOT", project)
        return reader(project, env.directory, "team-a")
    from core.web.services.external_management.knowledge_directory import read_team_knowledge_directory as reader
    assert select(owner)["knowledgeBases"][0]["id"] == "kb-a"
    with pytest.raises(ManagementError) as error:
        select(other)
    assert error.value.code == "KNOWLEDGE_DIRECTORY_UNAVAILABLE"


def test_migration_owner_cannot_use_directory_link(env):
    from core.web.services.external_management.service import ManagementError
    alias = env.root.parent / "project-alias"
    try:
        os.symlink(env.root, alias, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlink unavailable")
    marker = json.loads(env.marker.read_text(encoding="utf-8"))
    marker["projectRoot"] = str(alias)
    env.marker.write_text(json.dumps(marker), encoding="utf-8")
    with pytest.raises(ManagementError) as error:
        read(env)
    assert error.value.code == "KNOWLEDGE_DIRECTORY_UNAVAILABLE"


def test_case_sensitive_distinct_project_directories_are_not_same_owner(env, monkeypatch):
    import subprocess
    import vibelution_storage as storage
    from core.web.services import team_knowledge_service, team_service
    from core.web.services.external_management import knowledge_directory as reader
    from core.web.services.external_management.service import ManagementError
    parent = env.root.parent / "case-sensitive"
    parent.mkdir()
    fsutil = Path(os.environ["SystemRoot"]) / "System32" / "fsutil.exe"
    result = subprocess.run([str(fsutil), "file", "setCaseSensitiveInfo", str(parent), "enable"],
                            capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, check=False)
    if result.returncode:
        pytest.skip("case-sensitive directories unavailable on this filesystem or account")
    root, other = parent / "project", parent / "Project"
    root.mkdir()
    try:
        other.mkdir()
    except FileExistsError:
        pytest.skip("filesystem did not create separate case-sensitive directory")
    assert other.stat().st_ino != root.stat().st_ino
    (root / ".vibelution").mkdir()
    (root / ".vibelution" / "project.json").write_text(
        '{"schemaVersion":1,"projectId":"test-project"}', encoding="utf-8")
    paths = storage.resolve_project_storage_paths(root)
    marker = storage.storage_migration_state_path(paths)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"schemaVersion": 1, "status": "completed", "projectId": "test-project",
                                  "instanceId": paths.instance_id, "projectRoot": str(root)}), encoding="utf-8")
    team_path = paths.workspace / "teams" / "teams.json"
    kb_path = paths.workspace / "teams" / "team-a" / "knowledge" / "knowledge_bases.json"
    team_path.parent.mkdir(parents=True, exist_ok=True)
    kb_path.parent.mkdir(parents=True, exist_ok=True)
    team_path.write_bytes(env.teams_path.read_bytes())
    kb_path.write_bytes(env.path.read_bytes())
    env.directory.PROJECT_ROOT = root
    monkeypatch.setattr(team_service, "PROJECT_ROOT", root)
    monkeypatch.setattr(team_knowledge_service, "PROJECT_ROOT", root)
    assert reader.read_team_knowledge_directory(root, env.directory, "team-a")["knowledgeBases"][0]["id"] == "kb-a"
    env.directory.PROJECT_ROOT = other
    with pytest.raises(ManagementError) as error:
        reader.read_team_knowledge_directory(root, env.directory, "team-a")
    assert error.value.code == "KNOWLEDGE_DIRECTORY_UNAVAILABLE"
    env.directory.PROJECT_ROOT = root
    # Switch only after the metadata has been read and its sources are pinned:
    # the final check must notice a physical change that pathlib text misses.
    original_pin = reader.pinned_source_files
    @contextmanager
    def switch_during_read(snapshots):
        with original_pin(snapshots):
            if any(item.path.name == "knowledge_bases.json" for item in snapshots):
                env.directory.PROJECT_ROOT = other
            yield
    with monkeypatch.context() as patch:
        patch.setattr(reader, "pinned_source_files", switch_during_read)
        with pytest.raises(ManagementError) as error:
            reader.read_team_knowledge_directory(root, env.directory, "team-a")
        assert error.value.code == "KNOWLEDGE_DIRECTORY_UNAVAILABLE"
    env.directory.PROJECT_ROOT = root
    marker_data = json.loads(marker.read_text(encoding="utf-8"))
    marker_data["projectRoot"] = str(other)
    marker.write_text(json.dumps(marker_data), encoding="utf-8")
    identities = []
    original = reader._locked_source
    @contextmanager
    def capture(*args, **kwargs):
        with original(*args, **kwargs) as result:
            info = result[2]
            identities.append((info.volume, info.index_high, info.index_low))
            yield result
    monkeypatch.setattr(reader, "_locked_source", capture)
    with pytest.raises(ManagementError) as error:
        reader.read_team_knowledge_directory(root, env.directory, "team-a")
    assert error.value.code == "KNOWLEDGE_DIRECTORY_UNAVAILABLE"
    assert len(identities) == 2 and identities[0] != identities[1]


def test_missing_directory_file_id_is_unavailable(env, monkeypatch):
    from core.web.services.external_management import knowledge_directory as reader
    from core.web.services.external_management.service import ManagementError
    original = reader._locked_source
    @contextmanager
    def no_file_id(*args, **kwargs):
        with original(*args, **kwargs) as (api, handle, info):
            yield api, handle, SimpleNamespace(volume=info.volume, index_high=0, index_low=0)
    monkeypatch.setattr(reader, "_locked_source", no_file_id)
    with pytest.raises(ManagementError) as error:
        read(env)
    assert error.value.code == "KNOWLEDGE_DIRECTORY_UNAVAILABLE"


def test_launcher_canonical_data_home_and_native_override_priority(env, monkeypatch):
    from config.paths import DATA_HOME_ENV
    # Launcher normally injects canonical data as an environment override.
    monkeypatch.setenv(DATA_HOME_ENV, str(env.paths.data))
    before = snapshot(env)
    assert read(env)["knowledgeBases"][0]["id"] == "kb-a"
    assert snapshot(env) == before
    # The environment has priority even over a different configured data home.
    env.config.write_text('[storage]\ndata_home = "shared"\n', encoding="utf-8")
    assert read(env)["knowledgeBases"][0]["id"] == "kb-a"
    # Without the environment override the configured canonical path is valid.
    monkeypatch.delenv(DATA_HOME_ENV)
    env.config.write_text('[storage]\ndata_home = ' + json.dumps(str(env.paths.data)) + '\n', encoding="utf-8")
    assert read(env)["knowledgeBases"][0]["id"] == "kb-a"
    # A noncanonical environment value takes priority and must be rejected.
    from core.web.services.external_management.service import ManagementError
    monkeypatch.setenv(DATA_HOME_ENV, str(env.root.parent / "shared"))
    with pytest.raises(ManagementError) as error:
        read(env)
    assert error.value.code == "KNOWLEDGE_DIRECTORY_UNAVAILABLE"
