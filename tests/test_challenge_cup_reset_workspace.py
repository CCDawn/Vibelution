from __future__ import annotations

from pathlib import Path

from core.web.services.team_workflow import research_projects


def test_workspace_reset_moves_only_allowlisted_experiment_state(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "research-team"
    (root / "candidate_store").mkdir(parents=True)
    (root / "candidate_store" / "legacy.json").write_text("{}", encoding="utf-8")
    (root / "research_projects").mkdir()
    (root / "research_projects" / "index.json").write_text("{}", encoding="utf-8")
    (root / "canvas").mkdir()
    (root / "canvas" / "keep.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(research_projects, "formal_team_workspace_root", lambda _team_id: root)

    stage = research_projects.prepare_challenge_cup_experiment_state_reset(
        "research-team",
        reset_id="reset-workspace-1",
        entry_ids=["candidate_store", "research_projects"],
    )
    assert not (root / "candidate_store").exists()
    assert not (root / "research_projects").exists()
    assert (root / "canvas" / "keep.json").is_file()

    research_projects.purge_challenge_cup_experiment_state_reset(stage, reset_id="reset-workspace-1")
    restored = research_projects.restore_challenge_cup_experiment_state_reset(
        stage, reset_id="reset-workspace-1"
    )
    assert restored["restoredCount"] == 2
    assert (root / "candidate_store" / "legacy.json").is_file()
    assert (root / "research_projects" / "index.json").is_file()

    second = research_projects.prepare_challenge_cup_experiment_state_reset(
        "research-team",
        reset_id="reset-workspace-2",
        entry_ids=["candidate_store", "research_projects"],
    )
    research_projects.purge_challenge_cup_experiment_state_reset(second, reset_id="reset-workspace-2")
    finalized = research_projects.destroy_challenge_cup_experiment_state_reset(
        second, reset_id="reset-workspace-2"
    )
    assert finalized["status"] == "destroyed"
    assert not (root / "candidate_store").exists()
    assert (root / "canvas" / "keep.json").is_file()
