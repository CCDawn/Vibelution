"""Elo hypothesis tournament: math, determinism and artifact contract."""

from __future__ import annotations

import pytest

from core.web.services.team_workflow.research_runtime.hypothesis_tournament import (
    DEFAULT_INITIAL_RATING,
    DEFAULT_K_FACTOR,
    apply_pairwise_round,
    build_tournament_artifact,
    normalize_pairwise_outcomes,
    rank_candidates,
    validate_tournament_artifact,
)


def test_elo_win_moves_ratings_by_expectation():
    ratings = {"a": 1500.0, "b": 1500.0}
    updated = apply_pairwise_round(ratings, [{"kind": "win", "winner": "a", "loser": "b"}])
    # Equal ratings: expected 0.5, so the winner gains K/2 and the loser drops K/2.
    assert updated["a"] == pytest.approx(1500.0 + DEFAULT_K_FACTOR / 2)
    assert updated["b"] == pytest.approx(1500.0 - DEFAULT_K_FACTOR / 2)
    assert updated["a"] + updated["b"] == pytest.approx(3000.0)


def test_elo_favourite_gains_less_than_underdog_upset():
    ratings = {"strong": 1700.0, "weak": 1300.0}
    expected_gain = apply_pairwise_round(ratings, [{"kind": "win", "winner": "strong", "loser": "weak"}])
    upset_gain = apply_pairwise_round(ratings, [{"kind": "win", "winner": "weak", "loser": "strong"}])
    assert expected_gain["strong"] - 1700.0 < upset_gain["weak"] - 1300.0


def test_elo_tie_converges_ratings():
    ratings = {"a": 1600.0, "b": 1400.0}
    updated = apply_pairwise_round(ratings, [{"kind": "tie", "a": "a", "b": "b"}])
    assert updated["a"] < 1600.0 and updated["b"] > 1400.0
    assert updated["a"] + updated["b"] == pytest.approx(3000.0)


def test_unknown_candidates_start_at_default_rating():
    updated = apply_pairwise_round({}, [{"kind": "win", "winner": "new-a", "loser": "new-b"}])
    assert updated["new-a"] == pytest.approx(DEFAULT_INITIAL_RATING + DEFAULT_K_FACTOR / 2)


def test_ranking_is_deterministic_with_stable_ties():
    ranking = rank_candidates({"b": 1500.0, "a": 1500.0, "c": 1600.0})
    assert [entry["candidateId"] for entry in ranking] == ["c", "a", "b"]
    assert ranking[0]["rank"] == 1


def test_normalize_pairwise_outcomes_drops_invalid_records():
    outcomes = normalize_pairwise_outcomes(
        [
            {"winnerId": "a", "loserId": "b"},
            {"winnerId": "a", "loserId": "a"},  # self-pairing dropped
            {"winnerId": "", "loserId": "b"},  # empty id dropped
            {"tieWithId": "c", "otherId": "d"},
            "garbage",
        ]
    )
    assert outcomes == [
        {"kind": "win", "winner": "a", "loser": "b"},
        {"kind": "tie", "a": "c", "b": "d"},
    ]


def test_tournament_artifact_rounds_and_validation():
    artifact = build_tournament_artifact(
        tournament_id="t-1",
        pairwise_outcomes_by_round=[
            [{"winnerId": "a", "loserId": "b"}, {"winnerId": "b", "loserId": "c"}],
            [{"tieWithId": "a", "otherId": "c"}],
        ],
        created_at="2026-09-20T00:00:00Z",
    )
    assert validate_tournament_artifact(artifact) == []
    assert artifact["totalOutcomes"] == 3
    assert len(artifact["rounds"]) == 2
    assert artifact["rounds"][0]["ratings"]["a"] > artifact["rounds"][0]["ratings"]["b"]
    top = artifact["ranking"][0]["candidateId"]
    assert top == "a"

    rebuilt = build_tournament_artifact(
        tournament_id="t-1",
        pairwise_outcomes_by_round=[
            [{"winnerId": "a", "loserId": "b"}, {"winnerId": "b", "loserId": "c"}],
            [{"tieWithId": "a", "otherId": "c"}],
        ],
        created_at="2026-09-20T00:00:00Z",
    )
    assert rebuilt == artifact  # identical inputs, identical artifact

    problems = validate_tournament_artifact({"schemaVersion": 99, "ranking": []})
    assert any("schemaVersion" in problem for problem in problems)
