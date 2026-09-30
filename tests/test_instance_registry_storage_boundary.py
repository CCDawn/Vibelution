from __future__ import annotations

import json

import pytest

from tests.e2e.helpers.instance_registry import (
    InstanceRegistryError,
    assert_health_serves_worktree,
)


def _health(project_root, storage_root):
    return {
        "routesReady": True,
        "workspaceRoot": str(project_root),
        "storageWorkspaceRoot": str(storage_root),
        "serving": {"frontend": {"builtFromCommit": "test-commit"}},
    }


def test_e2e_ready_requires_storage_root_matching_registry(tmp_path):
    project_root = tmp_path / "checkout"
    identity_dir = project_root / ".vibelution"
    identity_dir.mkdir(parents=True)
    (identity_dir / "project.json").write_text(
        json.dumps({"schemaVersion": 1, "projectId": "test-project"}), encoding="utf-8"
    )
    instance_data = tmp_path / "instance-data"

    assert_health_serves_worktree(
        _health(project_root, instance_data / "workspace"),
        project_root,
        data_home=instance_data,
    )
    with pytest.raises(InstanceRegistryError, match="storageWorkspaceRoot"):
        assert_health_serves_worktree(
            _health(project_root, tmp_path / "other-instance" / "workspace"),
            project_root,
            data_home=instance_data,
        )


def test_e2e_ready_requires_tracked_project_identity(tmp_path):
    project_root = tmp_path / "checkout"
    project_root.mkdir()
    instance_data = tmp_path / "instance-data"

    with pytest.raises(InstanceRegistryError, match="project identity"):
        assert_health_serves_worktree(
            _health(project_root, instance_data / "workspace"),
            project_root,
            data_home=instance_data,
        )
