from __future__ import annotations

import copy
import inspect
import json
from pathlib import Path

import pytest

from core.web.services.agent_config_authority import agent_config_hash
from scripts import agent_config_authority_migration as migration


def _legacy_agent(agent_id: str = "agent-alpha") -> dict:
    return {
        "agentId": agent_id,
        "displayName": "Alpha",
        "llmBindings": {"dialogue": {"modelId": "model-alpha"}},
        "promptTemplateId": "chat",
        "toolPolicyId": "tool-alpha",
        "toolPolicy": {"policyId": "tool-alpha", "allowedTools": ["read_file"]},
        "memoryPolicyId": "memory-alpha",
        "memoryPolicy": {"policyId": "memory-alpha", "enabled": True},
        "contextCompressionPolicy": {"mode": "custom", "triggerRatio": 0.8},
        "metadata": {
            "delegationPolicy": {"enabled": False},
            "supervisionPolicy": {"enabled": False},
        },
        "status": "active",
    }


def _seed_data_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    agents: list[dict] | None = None,
) -> tuple[Path, Path, dict]:
    data_root = tmp_path / "agent-config-migration"
    data_root.mkdir()
    operator_workspace = tmp_path / "operator-data" / "workspace"
    operator_workspace.mkdir(parents=True)
    monkeypatch.setattr(
        migration.isolation,
        "formal_operator_workspace",
        lambda: operator_workspace,
    )
    monkeypatch.setattr(migration.isolation, "launcher_mount_roots", lambda: set())
    migration.initialize_migration_data_root(data_root)
    registry_path = data_root / "workspace" / "agents" / "agents.json"
    registry_path.parent.mkdir(parents=True)
    payload = {
        "schemaVersion": 7,
        "agents": copy.deepcopy(agents if agents is not None else [_legacy_agent()]),
        "toolPolicies": {"tool-alpha": {"policyId": "tool-alpha", "marker": "keep"}},
        "memoryPolicies": {"memory-alpha": {"policyId": "memory-alpha", "marker": "keep"}},
        "unrelated": {"keep": ["exact", 1]},
    }
    registry_path.write_text(
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n",
        encoding="utf-8",
    )
    return data_root, registry_path, payload


def test_agent_config_migration_dry_run_is_read_only_and_deterministic(
    tmp_path,
    monkeypatch,
):
    data_root, registry_path, _ = _seed_data_root(tmp_path, monkeypatch)
    before = registry_path.read_bytes()

    first = migration.plan_agent_config_migration(data_root=data_root)
    second = migration.plan_agent_config_migration(data_root=data_root)

    assert first["status"] == "dry_run"
    assert first["applyAllowed"] is True
    assert first["manifest"]["targetPath"] == str(registry_path.resolve())
    assert first["manifest"]["objectCount"] == 1
    assert first["manifest"]["changedAgentCount"] == 1
    assert first["manifest"]["agentIdPatternCounts"] == {
        "agentPrefixed": 1,
        "other": 0,
    }
    assert first["manifest"]["policyHashesBefore"] == first["manifest"]["policyHashesAfter"]
    assert first["manifest"]["manifestHash"] == second["manifest"]["manifestHash"]
    assert registry_path.read_bytes() == before
    assert not (data_root / ".migration").exists()


def test_agent_config_migration_apply_requires_matching_manifest_and_preserves_registry_data(
    tmp_path,
    monkeypatch,
):
    data_root, registry_path, original = _seed_data_root(tmp_path, monkeypatch)
    before = registry_path.read_bytes()
    dry_run = migration.plan_agent_config_migration(data_root=data_root)

    with pytest.raises(migration.AgentConfigMigrationError, match="manifest hash"):
        migration.apply_agent_config_migration(
            data_root=data_root,
            approved_manifest_hash="wrong",
        )

    assert registry_path.read_bytes() == before
    assert not (data_root / ".migration").exists()

    applied = migration.apply_agent_config_migration(
        data_root=data_root,
        approved_manifest_hash=dry_run["manifest"]["manifestHash"],
    )

    assert applied["status"] == "applied"
    migrated = json.loads(registry_path.read_text(encoding="utf-8"))
    agent = migrated["agents"][0]
    assert agent["configSchemaVersion"] == 2
    assert agent["configRevision"] == 1
    assert agent["permissionPreset"] == "request_approval"
    assert agent["configHash"] == agent_config_hash(agent)
    assert migrated["schemaVersion"] == original["schemaVersion"]
    assert migrated["toolPolicies"] == original["toolPolicies"]
    assert migrated["memoryPolicies"] == original["memoryPolicies"]
    assert migrated["unrelated"] == original["unrelated"]

    artifact_root = Path(applied["artifactRoot"])
    assert (artifact_root / "backup" / "agents.json").read_bytes() == before
    quarantine = json.loads(
        (artifact_root / "quarantine" / "index.json").read_text(encoding="utf-8")
    )
    assert quarantine == {
        "schemaVersion": 1,
        "reason": "no records quarantined by config authority migration",
        "entries": [],
    }
    apply_manifest = json.loads(
        (artifact_root / "apply-manifest.json").read_text(encoding="utf-8")
    )
    assert apply_manifest["status"] == "applied"
    assert apply_manifest["manifestHash"] == dry_run["manifest"]["manifestHash"]
    assert apply_manifest["backupSha256"] == dry_run["manifest"]["inputSha256"]
    assert apply_manifest["outputSha256"] == dry_run["manifest"]["candidateSha256"]


def test_agent_config_migration_is_idempotent_after_apply(tmp_path, monkeypatch):
    data_root, registry_path, _ = _seed_data_root(tmp_path, monkeypatch)
    first_plan = migration.plan_agent_config_migration(data_root=data_root)
    migration.apply_agent_config_migration(
        data_root=data_root,
        approved_manifest_hash=first_plan["manifest"]["manifestHash"],
    )
    migrated_bytes = registry_path.read_bytes()

    second_plan = migration.plan_agent_config_migration(data_root=data_root)
    second_apply = migration.apply_agent_config_migration(
        data_root=data_root,
        approved_manifest_hash=second_plan["manifest"]["manifestHash"],
    )

    assert second_plan["manifest"]["changedAgentCount"] == 0
    assert second_plan["manifest"]["inputSha256"] == second_plan["manifest"]["candidateSha256"]
    assert second_apply["status"] == "already_current"
    assert registry_path.read_bytes() == migrated_bytes


def test_agent_config_migration_blocks_session_repair_agents(tmp_path, monkeypatch):
    repaired = _legacy_agent("agent-session-repair")
    repaired["createdBy"] = "session_repair"
    data_root, registry_path, _ = _seed_data_root(
        tmp_path,
        monkeypatch,
        agents=[repaired],
    )
    before = registry_path.read_bytes()

    dry_run = migration.plan_agent_config_migration(data_root=data_root)

    assert dry_run["status"] == "blocked"
    assert dry_run["applyAllowed"] is False
    assert dry_run["manifest"]["anomalies"]["sessionRepairAgents"] == 1
    with pytest.raises(migration.AgentConfigMigrationError, match="session_repair"):
        migration.apply_agent_config_migration(
            data_root=data_root,
            approved_manifest_hash=dry_run["manifest"]["manifestHash"],
        )
    assert registry_path.read_bytes() == before


def test_agent_config_migration_requires_sentinel_and_rejects_operator_or_launcher_roots(
    tmp_path,
    monkeypatch,
):
    data_root = tmp_path / "candidate"
    data_root.mkdir()
    operator_workspace = tmp_path / "operator" / "workspace"
    operator_workspace.mkdir(parents=True)
    monkeypatch.setattr(
        migration.isolation,
        "formal_operator_workspace",
        lambda: operator_workspace,
    )
    monkeypatch.setattr(migration.isolation, "launcher_mount_roots", lambda: set())

    with pytest.raises(migration.AgentConfigMigrationError, match="sentinel"):
        migration.plan_agent_config_migration(data_root=data_root)

    operator_data_root = operator_workspace.parent
    with pytest.raises(migration.AgentConfigMigrationError, match="operator"):
        migration.initialize_migration_data_root(operator_data_root)

    operator_sibling = operator_data_root / "migration-fixture"
    operator_sibling.mkdir()
    with pytest.raises(migration.AgentConfigMigrationError, match="operator"):
        migration.initialize_migration_data_root(operator_sibling)

    mounted_root = tmp_path / "mounted"
    mounted_data_root = mounted_root / "candidate"
    mounted_data_root.mkdir(parents=True)
    monkeypatch.setattr(
        migration.isolation,
        "launcher_mount_roots",
        lambda: {mounted_root},
    )
    with pytest.raises(migration.AgentConfigMigrationError, match="Launcher"):
        migration.initialize_migration_data_root(mounted_data_root)


def test_agent_config_migration_rejects_malformed_registry_without_artifacts(
    tmp_path,
    monkeypatch,
):
    data_root, registry_path, _ = _seed_data_root(tmp_path, monkeypatch)
    registry_path.write_text('{"agents": "not-a-list"}', encoding="utf-8")

    with pytest.raises(migration.AgentConfigMigrationError, match="agents list"):
        migration.plan_agent_config_migration(data_root=data_root)

    assert not (data_root / ".migration").exists()


def test_agent_config_migration_recovers_idempotently_after_target_replace(
    tmp_path,
    monkeypatch,
):
    data_root, registry_path, _ = _seed_data_root(tmp_path, monkeypatch)
    dry_run = migration.plan_agent_config_migration(data_root=data_root)
    approved_hash = dry_run["manifest"]["manifestHash"]
    real_write = migration._strict_atomic_write
    final_manifest_write_seen = False

    def interrupt_after_replace(path: Path, payload: bytes) -> None:
        nonlocal final_manifest_write_seen
        if path.name == "apply-manifest.json":
            document = json.loads(payload.decode("utf-8"))
            if document.get("status") == "applied" and not final_manifest_write_seen:
                final_manifest_write_seen = True
                raise OSError("simulated manifest closeout interruption")
        real_write(path, payload)

    monkeypatch.setattr(migration, "_strict_atomic_write", interrupt_after_replace)
    with pytest.raises(OSError, match="closeout interruption"):
        migration.apply_agent_config_migration(
            data_root=data_root,
            approved_manifest_hash=approved_hash,
        )
    assert json.loads(registry_path.read_text(encoding="utf-8"))["agents"][0][
        "configSchemaVersion"
    ] == 2

    monkeypatch.setattr(migration, "_strict_atomic_write", real_write)
    recovered = migration.apply_agent_config_migration(
        data_root=data_root,
        approved_manifest_hash=approved_hash,
    )

    assert recovered["status"] == "already_applied"
    apply_manifest = json.loads(
        (Path(recovered["artifactRoot"]) / "apply-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert apply_manifest["status"] == "applied"
    assert apply_manifest["recoveredAt"]


def test_agent_config_migration_has_no_operator_or_launcher_target_fallback():
    source = inspect.getsource(migration)

    assert "VIBELUTION_DATA_HOME" not in source
    assert "resolve_data_home" not in source
    assert "load_public_config" not in source
    assert "VibelutionLauncher" not in source
    assert 'parser.add_argument(\n        "--data-root",\n        required=True' in source
