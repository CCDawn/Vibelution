"""The artifact store must keep every team id inside the teams namespace.

``_path`` turns the caller-supplied team id into one directory component, and
HTTP routes pass that id through as a raw string, so a ``..`` (or any
separator-bearing) id must never be able to address a file outside
``<workspace>/teams``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.web.services.team_workflow.research_runtime import workflow_artifact_store
from core.web.services.team_workflow.research_runtime.workflow_artifact_store import (
    list_workflow_artifacts,
    put_workflow_artifact,
)


def _use_artifact_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(workflow_artifact_store, "PROJECT_ROOT", tmp_path)
    return tmp_path / "workspace" / "teams"


def _put(team_id: str, *, identity: str = "record-1") -> dict:
    return put_workflow_artifact(
        team_id,
        kind="run_artifacts",
        workflow_run_id="workflow-1",
        source_collection_run_id="source-1",
        artifact_identity=identity,
        payload={"identity": identity},
    )


@pytest.mark.parametrize(
    "team_id",
    ["..", "../..", "../../outside", "a/b", "a\\b", "..\\..\\outside", ".hidden", "...", "  ..  "],
)
def test_hostile_team_ids_cannot_escape_the_teams_namespace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, team_id: str
) -> None:
    teams_root = _use_artifact_root(monkeypatch, tmp_path)

    path = workflow_artifact_store._path(team_id, "run_artifacts")
    resolved = path.resolve()

    # <workspace>/teams/<component>/workflow_artifacts/run_artifacts.jsonl
    assert teams_root.resolve() == resolved.parents[2]
    assert resolved.parent.name == "workflow_artifacts"
    component = resolved.parents[1].name
    assert component not in {".", "..", ""}
    assert "/" not in component and "\\" not in component


def test_hostile_team_id_write_and_read_use_the_same_contained_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    teams_root = _use_artifact_root(monkeypatch, tmp_path)

    written = _put("../../escape")
    assert written["teamId"]

    landed = sorted(
        candidate
        for candidate in teams_root.rglob("run_artifacts.jsonl")
        if candidate.is_file()
    )
    assert len(landed) == 1
    assert teams_root.resolve() in landed[0].resolve().parents
    assert not (tmp_path / "escape").exists()
    assert not (tmp_path / "workspace" / "workflow_artifacts").exists()

    rows = list_workflow_artifacts("../../escape", kind="run_artifacts")
    assert [row["payload"]["identity"] for row in rows] == ["record-1"]


def test_ordinary_team_ids_keep_their_historical_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    teams_root = _use_artifact_root(monkeypatch, tmp_path)

    path = workflow_artifact_store._path("research-team", "run_artifacts")

    assert path == teams_root / "research-team" / "workflow_artifacts" / "run_artifacts.jsonl"


def test_empty_team_id_still_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _use_artifact_root(monkeypatch, tmp_path)

    with pytest.raises(ValueError):
        workflow_artifact_store._path("   ", "run_artifacts")
