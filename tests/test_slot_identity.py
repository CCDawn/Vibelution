from __future__ import annotations

import json
from pathlib import Path

from config.paths import CONFIG_HOME_ENV, DATA_HOME_ENV, default_data_home, resolve_data_home
from core.launcher import slot_identity


def _write_project_identity(project: Path) -> None:
    path = project / ".vibelution" / "project.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"schemaVersion": 1, "projectId": "test-vibelution"}) + "\n",
        encoding="utf-8",
    )


def test_same_path_different_case_shares_slot_id_on_windows(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    project = tmp_path / "Repo"
    project.mkdir()
    lower = slot_identity.slot_id_for_project(project)
    mixed = slot_identity.slot_id_for_project(Path(str(project).swapcase()) if str(project) != str(project).swapcase() else project)
    assert lower == slot_identity.slot_id_for_project(project.resolve())
    if os_name_is_nt():
        assert lower == slot_identity.slot_id_for_key(slot_identity.normalize_slot_key(project))


def os_name_is_nt() -> bool:
    import os

    return os.name == "nt"


def test_two_checkouts_get_disjoint_data_homes(tmp_path, monkeypatch):
    monkeypatch.delenv(DATA_HOME_ENV, raising=False)
    monkeypatch.setenv("VIBELUTION_PROJECTS_HOME", str(tmp_path / "project-state"))
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    _write_project_identity(left)
    _write_project_identity(right)
    home_left = slot_identity.data_home_for_project(left)
    home_right = slot_identity.data_home_for_project(right)
    assert home_left != home_right
    assert home_left.name == "data"
    assert "test-vibelution" in home_left.parts
    assert "instances" in home_left.parts


def test_apply_slot_env_does_not_change_default_data_home(tmp_path, monkeypatch):
    monkeypatch.delenv(DATA_HOME_ENV, raising=False)
    monkeypatch.setenv("VIBELUTION_PROJECTS_HOME", str(tmp_path / "project-state"))
    project = tmp_path / "task"
    project.mkdir()
    _write_project_identity(project)
    env = slot_identity.apply_slot_spawn_environment({}, project, backend_port=8101, control_port=9210, mkdir=False)
    assert env[DATA_HOME_ENV] == str(slot_identity.data_home_for_project(project))
    assert env[CONFIG_HOME_ENV]
    assert env["VIBELUTION_PORT"] == "8101"
    assert env["VIBELUTION_LAUNCHER_PORT"] == "9210"
    assert resolve_data_home() == default_data_home().resolve()
