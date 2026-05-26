#!/usr/bin/env python3
"""Shared supervised artifact reader tests."""

import json
from pathlib import Path

from core.evaluation.supervised_artifacts import (
    load_policy_proposal_artifact,
    policy_target_key,
    resolve_project_artifact_path,
)


def test_load_policy_proposal_artifact_reads_first_safe_existing_path(tmp_path: Path):
    proposal_path = tmp_path / "workspace" / "evolution" / "proposals" / "case.json"
    proposal_path.parent.mkdir(parents=True, exist_ok=True)
    proposal_path.write_text(
        json.dumps(
            {
                "proposal_id": "demo:case:hash",
                "target": {"case_id": "case_1", "kind": "bundle_prompt_case"},
                "status": "observing",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    decision_payload = {
        "policy_action": {
            "proposal_paths": [
                "workspace/evolution/proposals/missing.json",
                str(proposal_path),
            ],
        }
    }

    artifact = load_policy_proposal_artifact(decision_payload, project_root=tmp_path)

    assert artifact is not None
    assert artifact.path == str(proposal_path.resolve())
    assert artifact.payload["proposal_id"] == "demo:case:hash"
    assert policy_target_key(artifact.payload) == 'target:{"case_id": "case_1", "kind": "bundle_prompt_case"}'


def test_load_policy_proposal_artifact_rejects_paths_outside_project(tmp_path: Path):
    outside_path = tmp_path.parent / "outside-proposal.json"
    outside_path.write_text(json.dumps({"proposal_id": "outside"}, ensure_ascii=False), encoding="utf-8")
    decision_payload = {"policy_action": {"proposal_paths": [str(outside_path)]}}

    artifact = load_policy_proposal_artifact(decision_payload, project_root=tmp_path)

    assert artifact is None
    assert resolve_project_artifact_path(str(outside_path), project_root=tmp_path) is None
