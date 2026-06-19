from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.evaluation import self_evolution_workbench
from core.infrastructure import developer_sandbox
from core.web.services import self_evolution_service


@pytest.fixture(autouse=True)
def isolate_developer_sandbox_config(tmp_path: Path, monkeypatch):
    _set_developer_sandbox(tmp_path, monkeypatch, False)


def _enable_developer_sandbox(project_root: Path, monkeypatch) -> dict:
    return _set_developer_sandbox(project_root, monkeypatch, True)


def _set_developer_sandbox(project_root: Path, monkeypatch, enabled: bool) -> dict:
    config_path = project_root / "config.toml"
    if not config_path.exists():
        config_path.write_text("[launcher]\ncontrol_port = 8765\n", encoding="utf-8")
    monkeypatch.setattr(developer_sandbox, "CONFIG_PATH", config_path)
    monkeypatch.setattr(developer_sandbox, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(developer_sandbox, "resolve_workspace_home", lambda *args, **kwargs: project_root / "workspace")
    status = developer_sandbox.get_developer_mode_status(config_path=config_path, project_root=project_root)
    return developer_sandbox.update_developer_mode_status(
        enabled,
        base_hash=status["configHash"],
        config_path=config_path,
        project_root=project_root,
    )


def _fake_config() -> SimpleNamespace:
    return SimpleNamespace(evolution=SimpleNamespace(audit_log_path="workspace/evolution/audit.jsonl"))


def test_self_evolution_audit_reads_developer_sandbox_records(tmp_path: Path, monkeypatch):
    _enable_developer_sandbox(tmp_path, monkeypatch)
    monkeypatch.setattr(self_evolution_workbench, "get_config", _fake_config)
    monkeypatch.setattr(self_evolution_service, "get_config", _fake_config)
    sandbox_audit = developer_sandbox.seeded_sandbox_workspace_path(tmp_path, "evolution", "audit.jsonl")
    sandbox_audit.parent.mkdir(parents=True, exist_ok=True)
    sandbox_audit.write_text(
        json.dumps({"timestamp": "2026-06-16T00:00:00Z", "event": "debug.audit", "txn_id": "sandbox-txn"})
        + "\n",
        encoding="utf-8",
    )
    formal_audit = tmp_path / "workspace" / "evolution" / "audit.jsonl"
    formal_audit.parent.mkdir(parents=True, exist_ok=True)
    formal_audit.write_text(
        json.dumps({"timestamp": "2026-06-16T00:00:00Z", "event": "formal.audit", "txn_id": "formal-txn"})
        + "\n",
        encoding="utf-8",
    )

    workbench_records = self_evolution_workbench.load_self_evolution_audit_records(tmp_path)
    service_deleted_count = self_evolution_service._delete_audit_groups(tmp_path, ["sandbox-txn"])

    assert [item["txn_id"] for item in workbench_records] == ["sandbox-txn"]
    assert service_deleted_count == 1
    assert "sandbox-txn" not in sandbox_audit.read_text(encoding="utf-8")
    assert "formal-txn" in formal_audit.read_text(encoding="utf-8")
