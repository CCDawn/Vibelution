from __future__ import annotations

import json
from pathlib import Path

from core.web.services.evolution_promotion_lane import (
    PROMOTION_LANE,
    build_current_baseline_promotion,
)
from core.web.services.evolution_runtime_projection_service import (
    build_workspace_runtime_projection,
)


def _write_manifest(directory: Path, *, name: str, payload: dict) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_current_baseline_is_none_without_manifests(tmp_path: Path):
    payload = build_current_baseline_promotion(
        tmp_path,
        current_head="abc",
        manifest_roots=[tmp_path / "empty"],
    )
    assert payload["lane"] == PROMOTION_LANE
    assert payload["status"] == "none"
    assert payload["commitSha"] == ""


def test_current_baseline_matches_head_from_supervised_manifest(tmp_path: Path):
    root = tmp_path / "supervised-integration"
    _write_manifest(
        root,
        name="swte-1-variant.json",
        payload={
            "runId": "swte-1",
            "commitSha": "deadbeef",
            "baseCommit": "cafebabe",
            "committedAt": "2026-09-18T10:00:00+00:00",
            "changedFiles": ["agent.py"],
        },
    )
    payload = build_current_baseline_promotion(
        tmp_path,
        current_head="deadbeef",
        manifest_roots=[root],
    )
    assert payload["status"] == "current"
    assert payload["commitSha"] == "deadbeef"
    assert payload["sourceKind"] == "supervised_worktree"
    assert payload["changedFiles"] == ["agent.py"]
    assert payload["runId"] == "swte-1"


def test_current_baseline_prefers_latest_committed_at(tmp_path: Path):
    supervised = tmp_path / "git" / "vibelution" / "supervised-integration"
    autonomous = tmp_path / "self_evolution" / "autonomous_loops" / "integration_manifests"
    _write_manifest(
        supervised,
        name="older.json",
        payload={
            "commitSha": "111",
            "committedAt": "2026-09-01T00:00:00+00:00",
            "runId": "old",
        },
    )
    _write_manifest(
        autonomous,
        name="newer.json",
        payload={
            "commitSha": "222",
            "committedAt": "2026-09-18T00:00:00+00:00",
            "runId": "new",
        },
    )
    payload = build_current_baseline_promotion(
        tmp_path,
        current_head="aaa",
        manifest_roots=[supervised, autonomous],
    )
    assert payload["commitSha"] == "222"
    assert payload["status"] == "superseded"
    assert payload["sourceKind"] == "autonomous_loop"


def test_workspace_runtime_projection_carries_promotion_lane():
    projection = build_workspace_runtime_projection(
        current_baseline={
            "lane": PROMOTION_LANE,
            "status": "current",
            "commitSha": "abc123",
        }
    )
    assert projection["promotionLane"] == PROMOTION_LANE
    assert projection["currentBaseline"]["commitSha"] == "abc123"
    assert projection["active"] is None
    assert projection["byKind"] == {}
