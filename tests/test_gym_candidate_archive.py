from core.gym import CandidateArchive, EvolutionCandidate, EvolutionReplayContext, ObjectiveVector


def _candidate(candidate_id: str, replacement: str) -> EvolutionCandidate:
    return EvolutionCandidate(
        candidate_id=candidate_id,
        artifact_type="prompt_candidate",
        target={"path": "workspace/skills/triage.md"},
        payload={"replacement": replacement},
        expected_effect="preserve validation evidence",
        episode_id="episode:archive",
        replay_context=EvolutionReplayContext(
            baseline_agent_version="vibelution-agent@test",
            dataset_bundle_ref="bundles/foundation.json",
            source_commit="abc123",
            strategy_id="reflective_text",
            strategy_version="v1",
            seed=42,
            model_binding_snapshot={"primary": {"provider": "test", "model": "fake"}},
        ),
    )


def test_archive_applies_hard_gates_then_rebuilds_deterministic_pareto_frontier(tmp_path):
    archive = CandidateArchive(tmp_path / "candidate-events.jsonl")
    dominated = archive.append(
        _candidate("candidate:slow", "check validation"),
        ObjectiveVector(success=1.0, quality=0.8, validation=1.0, cost=5.0, latency=3.0),
    )
    winner = archive.append(
        _candidate("candidate:fast", "check validation and rollback"),
        ObjectiveVector(success=1.0, quality=0.8, validation=1.0, cost=3.0, latency=2.0),
    )
    blocked = archive.append(
        _candidate("candidate:unsafe", "skip safety"),
        ObjectiveVector(success=1.0, quality=1.0, validation=1.0, cost=1.0, safety_risk=1.0),
    )

    assert dominated.status == "dominated"
    assert winner.status == "pareto"
    assert blocked.status == "blocked"
    assert blocked.blockers == ["safety_risk"]
    assert [record.candidate_id for record in archive.frontier()] == ["candidate:fast"]

    duplicate = archive.append(
        _candidate("candidate:fast", "check validation and rollback"),
        ObjectiveVector(success=1.0, quality=0.8, validation=1.0, cost=3.0, latency=2.0),
    )
    assert duplicate.candidate_id == "candidate:fast"
    assert [record.candidate_id for record in CandidateArchive(archive.ledger_path).frontier()] == ["candidate:fast"]
