from __future__ import annotations

from core.research.competition.catalog_execution import build_result_set
from core.research.competition.real_control_batch import (
    new_real_batch_state,
    project_real_batch_state,
)
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
