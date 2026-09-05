from __future__ import annotations

import json
from pathlib import Path

from scripts.cleanup_challenge_stage2_rounds import cleanup_invalid_stage2_rounds


def _write_store(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_cleanup_is_dry_run_by_default_and_apply_backs_up_exact_sources(tmp_path):
    project_roots = {
        "challenge-sci-091": tmp_path / "sci091",
        "challenge-sci-096": tmp_path / "sci096",
    }
    invalid_091 = {
        "stageRoundId": "round-091-invalid",
        "stageType": "experiment",
        "researchProjectId": "challenge-sci-091",
    }
    valid_091 = {
        "stageRoundId": "round-091-valid",
        "stageType": "experiment",
        "researchProjectId": "challenge-sci-091",
        "challengeQuestionId": "SCI-091",
        "programPhase": 2,
        "programDirection": "B",
        "deepExperiment": True,
    }
    wrong_096 = {
        "stageRoundId": "round-096-wrong-project",
        "stageType": "experiment",
        "researchProjectId": "challenge-sci-020",
    }
    knowledge_round = {
        "stageRoundId": "knowledge-096",
        "stageType": "knowledge_collection",
    }
    _write_store(
        project_roots["challenge-sci-091"] / "research_stage_rounds" / "index.json",
        {"rounds": [invalid_091, valid_091]},
    )
    _write_store(
        project_roots["challenge-sci-091"] / "experiment_plans" / "index.json",
        {
            "activePlanId": "plan-invalid",
            "plans": [
                {"planId": "plan-invalid", "stageRoundId": "round-091-invalid"},
                {"planId": "plan-valid", "stageRoundId": "round-091-valid"},
            ],
        },
    )
    _write_store(
        project_roots["challenge-sci-096"] / "research_stage_rounds" / "index.json",
        {"rounds": [knowledge_round, wrong_096]},
    )
    backup_root = tmp_path / "backups" / "cleanup-1"

    preview = cleanup_invalid_stage2_rounds(
        project_roots,
        backup_root=backup_root,
        apply=False,
    )

    assert preview["status"] == "dry_run"
    assert preview["removedRoundIds"] == [
        "round-091-invalid",
        "round-096-wrong-project",
    ]
    assert preview["removedPlanIds"] == ["plan-invalid"]
    assert not backup_root.exists()
    assert len(
        json.loads(
            (project_roots["challenge-sci-091"] / "research_stage_rounds" / "index.json").read_text()
        )["rounds"]
    ) == 2

    applied = cleanup_invalid_stage2_rounds(
        project_roots,
        backup_root=backup_root,
        apply=True,
    )

    assert applied["status"] == "applied"
    assert (backup_root / "manifest.json").is_file()
    backed_up = backup_root / "challenge-sci-091" / "research_stage_rounds" / "index.json"
    assert backed_up.is_file()
    assert len(json.loads(backed_up.read_text())["rounds"]) == 2
    updated_rounds = json.loads(
        (project_roots["challenge-sci-091"] / "research_stage_rounds" / "index.json").read_text()
    )["rounds"]
    assert [item["stageRoundId"] for item in updated_rounds] == ["round-091-valid"]
    updated_plans = json.loads(
        (project_roots["challenge-sci-091"] / "experiment_plans" / "index.json").read_text()
    )
    assert [item["planId"] for item in updated_plans["plans"]] == ["plan-valid"]
    assert updated_plans["activePlanId"] == ""


def test_cleanup_refuses_to_reuse_an_existing_backup_directory(tmp_path):
    backup_root = tmp_path / "existing"
    backup_root.mkdir()

    try:
        cleanup_invalid_stage2_rounds({}, backup_root=backup_root, apply=True)
    except ValueError as exc:
        assert "backup" in str(exc).lower()
    else:
        raise AssertionError("expected existing backup directory to be rejected")
