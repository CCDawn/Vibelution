from __future__ import annotations

import json

import pytest

from core.web.services.team_workflow.research_runtime import workflow_artifact_store
from core.web.services.team_workflow.research_runtime.workflow_artifact_store import (
    WorkflowArtifactResetConflictError,
    WorkflowArtifactResetStateError,
    WorkflowArtifactResetValidationError,
    destroy_workflow_artifact_reset,
    list_workflow_artifacts,
    prepare_workflow_artifact_reset,
    purge_workflow_artifact_reset,
    put_workflow_artifact,
    restore_workflow_artifact_reset,
)


def _use_artifact_root(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(workflow_artifact_store, "PROJECT_ROOT", tmp_path)


def _put(team_id: str = "research-team", *, kind: str = "run_artifacts", identity: str = "record-1") -> dict:
    return put_workflow_artifact(
        team_id,
        kind=kind,
        workflow_run_id="workflow-1",
        source_collection_run_id="source-1",
        artifact_identity=identity,
        payload={"identity": identity, "kind": kind},
    )


def test_prepare_purge_and_destroy_keep_a_managed_manifest_until_finalization(
    monkeypatch, tmp_path
) -> None:
    _use_artifact_root(monkeypatch, tmp_path)
    first = _put(identity="record-1")
    second = _put(kind="research_plan", identity="plan-1")

    staged = prepare_workflow_artifact_reset(
        "research-team",
        reset_id="reset-1",
        artifact_ids=[first["recordId"], second["recordId"]],
    )
    assert staged["status"] == "staged"
    assert staged["artifactCount"] == 2
    assert list_workflow_artifacts("research-team", kind="run_artifacts") == []
    assert list_workflow_artifacts("research-team", kind="research_plan") == []

    purged = purge_workflow_artifact_reset(
        "research-team", reset_id="reset-1", stage=staged
    )
    assert purged["status"] == "purged"
    assert purged["manifestHash"] == staged["manifestHash"]

    manifest_path = workflow_artifact_store._reset_stage_path("research-team", "reset-1")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "purged"
    assert manifest["records"]

    destroyed = destroy_workflow_artifact_reset(
        "research-team", reset_id="reset-1", stage=staged
    )
    assert destroyed["status"] == "destroyed"
    finalized = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert finalized["status"] == "destroyed"
    assert finalized["payloadRetained"] is False
    assert all("payload" not in entry["record"] for entry in finalized["records"])


def test_restore_is_exact_and_idempotent_after_purge(monkeypatch, tmp_path) -> None:
    _use_artifact_root(monkeypatch, tmp_path)
    original = _put()
    staged = prepare_workflow_artifact_reset("research-team", reset_id="reset-2")
    purge_workflow_artifact_reset("research-team", reset_id="reset-2", stage=staged)

    restored = restore_workflow_artifact_reset(
        "research-team", reset_id="reset-2", stage=staged
    )
    assert restored["status"] == "restored"
    rows = list_workflow_artifacts("research-team", kind="run_artifacts")
    assert rows == [original]

    repeated = restore_workflow_artifact_reset(
        "research-team", reset_id="reset-2", stage=staged
    )
    assert repeated == restored
    with pytest.raises(WorkflowArtifactResetStateError):
        purge_workflow_artifact_reset("research-team", reset_id="reset-2", stage=staged)

    discarded = workflow_artifact_store.discard_restored_workflow_artifact_reset(
        "research-team", reset_id="reset-2"
    )
    assert discarded["status"] == "discarded"
    assert not workflow_artifact_store._reset_stage_path("research-team", "reset-2").exists()
    retried = prepare_workflow_artifact_reset("research-team", reset_id="reset-2")
    assert retried["status"] == "staged"


def test_stage_fails_closed_for_unowned_or_duplicate_rows(monkeypatch, tmp_path) -> None:
    _use_artifact_root(monkeypatch, tmp_path)
    row = _put()
    path = workflow_artifact_store._path("research-team", "run_artifacts")
    path.write_text(
        json.dumps({**row, "teamId": "other-team"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(WorkflowArtifactResetValidationError):
        prepare_workflow_artifact_reset("research-team", reset_id="reset-owner")
    assert path.is_file()

    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for _ in range(2)) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(WorkflowArtifactResetConflictError):
        prepare_workflow_artifact_reset("research-team", reset_id="reset-duplicate")
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2


def test_stage_rejects_stale_plan_and_mismatched_handle(monkeypatch, tmp_path) -> None:
    _use_artifact_root(monkeypatch, tmp_path)
    row = _put()
    with pytest.raises(WorkflowArtifactResetConflictError):
        prepare_workflow_artifact_reset(
            "research-team",
            reset_id="reset-plan",
            artifact_ids=["not-the-live-id"],
        )
    assert list_workflow_artifacts("research-team", kind="run_artifacts") == [row]

    staged = prepare_workflow_artifact_reset("research-team", reset_id="reset-handle")
    with pytest.raises(WorkflowArtifactResetValidationError):
        purge_workflow_artifact_reset("research-team", reset_id="another-reset", stage=staged)


def test_reset_scope_rejects_path_like_ids(monkeypatch, tmp_path) -> None:
    _use_artifact_root(monkeypatch, tmp_path)
    with pytest.raises(WorkflowArtifactResetValidationError):
        prepare_workflow_artifact_reset("research-team/other", reset_id="reset-safe")
    with pytest.raises(WorkflowArtifactResetValidationError):
        prepare_workflow_artifact_reset("research-team", reset_id="../unsafe")
