"""P0: readiness must not read data/domain_artifacts latest-file fallback."""

from __future__ import annotations

import json
from pathlib import Path

from core.infrastructure import path_containment
from core.web.services.team_workflow.research_runtime.real_readiness_context import (
    _artifact_payload,
)


def test_artifact_payload_ignores_domain_artifacts_latest_file(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(path_containment, "PROJECT_ROOT", tmp_path)
    root = (
        tmp_path
        / "data"
        / "domain_artifacts"
        / "knowledge"
        / "team-x"
        / "knowledge_package"
    )
    root.mkdir(parents=True)
    stale = {
        "contentHash": "a" * 64,
        "domainRevision": "rev-stale",
        "schemaVersion": "1.0.0",
        "payload": {"title": "stale from other run", "runId": "run-other"},
    }
    (root / "stale.json").write_text(json.dumps(stale), encoding="utf-8")

    # Current run must not unlock from latest domain_artifacts file.
    assert (
        _artifact_payload(
            "knowledge_package",
            "team-x",
            "run-current",
            authority_run_id="run-current",
        )
        is None
    )
