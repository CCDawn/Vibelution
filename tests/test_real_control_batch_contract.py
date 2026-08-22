from __future__ import annotations

import pytest

from core.research.competition.catalog_execution import (
    CatalogExecutionError,
    build_result_set,
)
from core.research.competition.real_control_batch import (
    new_real_batch_state,
    project_real_batch_state,
)
from core.research.competition.result_set import QuestionResult
from tests.test_catalog_execution_state_machine import _package


def test_real_projection_exposes_package_quality_and_integrity_hashes() -> None:
    state = new_real_batch_state("real-1")
    package = _package(state.scope, state.plan.question_ids[0])
    state.record_package(package)

    projection = project_real_batch_state(
        state,
        updated_at="2026-08-23T10:00:00Z",
    )

    checkpoint = state.to_checkpoint()
    manifest = build_result_set(state).manifest()
    assert projection["checkpointSha256"] == checkpoint["checkpoint_sha256"]
    assert projection["resultManifestSha256"] == manifest["manifest_sha256"]
    assert projection["packageQualitySummary"] == {
        "approved": 1,
        "blocked": 0,
        "failed": 0,
        "pendingHumanGate": 0,
        "packageBacked": 1,
    }


def test_real_projection_preserves_legacy_checkpoint_without_claiming_v2_hash() -> None:
    state = new_real_batch_state("real-1")
    question_id = state.plan.question_ids[0]
    state.mark_running(question_id)
    state.record_success(
        question_id,
        QuestionResult.create(
            scope=state.scope,
            question_id=question_id,
            model_receipt_locator="legacy-model-receipt://sci-091",
            knowledge_locator="legacy-knowledge://sci-091",
        ),
    )

    checkpoint = state.to_checkpoint()
    assert "schema_version" not in checkpoint
    assert "checkpoint_sha256" not in checkpoint

    projection = project_real_batch_state(
        state,
        updated_at="2026-08-23T10:00:00Z",
    )

    assert projection["checkpointSha256"] == ""


@pytest.mark.parametrize(
    ("hash_mutation", "error_pattern"),
    [
        pytest.param("missing", "hash is required", id="missing-hash"),
        pytest.param("wrong", "hash does not match", id="wrong-hash"),
    ],
)
def test_real_projection_rejects_v2_checkpoint_without_valid_outer_hash(
    monkeypatch: pytest.MonkeyPatch,
    hash_mutation: str,
    error_pattern: str,
) -> None:
    state = new_real_batch_state("real-1")
    checkpoint = state.to_checkpoint()
    if hash_mutation == "missing":
        checkpoint.pop("checkpoint_sha256")
    else:
        checkpoint["checkpoint_sha256"] = "0" * 64
    monkeypatch.setattr(state, "to_checkpoint", lambda: checkpoint)

    with pytest.raises(CatalogExecutionError, match=error_pattern):
        project_real_batch_state(
            state,
            updated_at="2026-08-23T10:00:00Z",
        )
