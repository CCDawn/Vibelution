#!/usr/bin/env python3
"""Compatibility and replay contracts for supervised-evolution artifacts."""

import pytest

from core.gym import (
    CandidateImprovement,
    EvolutionCandidate,
    EvolutionReplayContext,
    OptimizationContractError,
    candidate_from_improvement,
)


def _replay_context(*, model_binding_snapshot=None, proposer_visible_splits=None):
    return EvolutionReplayContext(
        baseline_agent_version="vibelution-agent@abc123",
        dataset_bundle_ref="workspace/supervised_evolution/bundles/foundation.json",
        source_commit="abc123",
        strategy_id="reflective_text",
        strategy_version="v1",
        seed=42,
        model_binding_snapshot=model_binding_snapshot or {"primary": {"provider": "test", "model": "fake"}},
        proposer_visible_splits=proposer_visible_splits or ["train", "dev"],
    )


def test_legacy_candidate_improvement_round_trips_as_proposal_only_candidate():
    legacy = CandidateImprovement(
        improvement_id="exercise:prompt:001",
        improvement_type="prompt_candidate",
        target={"path": "workspace/skills/triage.md"},
        expected_effect="preserve validation evidence",
        payload={"replacement": "Check validation before closing."},
    )

    candidate = candidate_from_improvement(
        legacy,
        episode_id="episode_001",
        replay_context=_replay_context(),
        evidence_refs=["traces/trace_001.json"],
    )

    artifact = candidate.to_dict()

    assert artifact["schema_version"] == 1
    assert artifact["runtime_effect"] == "not_applied"
    assert artifact["agent_consumption"] == "advisory"
    assert artifact["payload"] == legacy.payload
    assert artifact["target"] == legacy.target
    assert artifact["replay_context"]["seed"] == 42
    assert candidate.to_candidate_improvement() == legacy


def test_candidate_fingerprint_is_stable_for_equivalent_replay_inputs():
    left = EvolutionCandidate(
        candidate_id="candidate:stable",
        artifact_type="prompt_candidate",
        target={"path": "workspace/skills/triage.md", "kind": "prompt"},
        payload={"replacement": "Check validation before closing.", "constraints": ["bounded"]},
        expected_effect="preserve validation evidence",
        episode_id="episode_001",
        parent_ids=["parent:b", "parent:a"],
        strategy_id="reflective_text",
        strategy_version="v1",
        generation=1,
        evidence_refs=["traces/b.json", "traces/a.json"],
        replay_context=_replay_context(
            model_binding_snapshot={"primary": {"model": "fake", "provider": "test"}}
        ),
    )
    right = EvolutionCandidate(
        candidate_id="candidate:stable",
        artifact_type="prompt_candidate",
        target={"kind": "prompt", "path": "workspace/skills/triage.md"},
        payload={"constraints": ["bounded"], "replacement": "Check validation before closing."},
        expected_effect="preserve validation evidence",
        episode_id="episode_001",
        parent_ids=["parent:a", "parent:b"],
        strategy_id="reflective_text",
        strategy_version="v1",
        generation=1,
        evidence_refs=["traces/a.json", "traces/b.json"],
        replay_context=_replay_context(
            model_binding_snapshot={"primary": {"provider": "test", "model": "fake"}}
        ),
    )

    assert left.artifact_fingerprint == right.artifact_fingerprint
    assert left.to_dict()["artifact_fingerprint"] == right.to_dict()["artifact_fingerprint"]


def test_replay_context_hides_holdout_and_candidate_cannot_claim_runtime_application():
    with pytest.raises(OptimizationContractError, match="holdout"):
        _replay_context(proposer_visible_splits=["train", "holdout"])

    with pytest.raises(OptimizationContractError, match="not_applied"):
        EvolutionCandidate(
            candidate_id="candidate:unsafe",
            artifact_type="prompt_candidate",
            target={"path": "workspace/skills/triage.md"},
            payload={},
            expected_effect="unsafe",
            episode_id="episode_001",
            replay_context=_replay_context(),
            runtime_effect="applied",
        )
