"""Elo tournament scoring for hypothesis review (Co-Scientist style).

Pure, deterministic, order-independent math for ranking hypothesis
candidates from pairwise review outcomes. This module never calls an LLM
and never mutates hypothesis content — it only orders what the pairwise
review meetings already decided, so the existing human-in-the-loop flow
stays authoritative.

Contract highlights (``TOURNAMENT_ARTIFACT_CONTRACT_VERSION``):

- ratings start at ``DEFAULT_INITIAL_RATING`` (1500) and update with the
  standard Elo expectation formula, K-factor configurable (default 32);
- a draw ("tie") moves both ratings toward the expectation;
- identical inputs always produce an identical artifact (no clock, no
  randomness — ``createdAt`` is supplied by the caller);
- the artifact records every pairwise outcome and per-round rating
  snapshots so a ranking is fully auditable.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Dict, List

TOURNAMENT_ARTIFACT_CONTRACT_VERSION = 1
DEFAULT_INITIAL_RATING = 1500.0
DEFAULT_K_FACTOR = 32.0
VALID_OUTCOMES = ("win", "loss", "tie")


def _expected_score(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))


def _normalize_candidate_id(value: Any) -> str:
    return str(value if value is not None else "").strip()


def normalize_ratings(raw: Mapping[str, Any] | None) -> Dict[str, float]:
    """Load prior ratings (candidateId -> rating), dropping invalid entries."""

    ratings: Dict[str, float] = {}
    for key, value in dict(raw or {}).items():
        candidate_id = _normalize_candidate_id(key)
        if not candidate_id:
            continue
        try:
            ratings[candidate_id] = float(value)
        except (TypeError, ValueError):
            continue
    return ratings


def normalize_pairwise_outcomes(raw: Sequence[Mapping[str, Any]] | None) -> List[Dict[str, str]]:
    """Normalize pairwise records ``{winnerId, loserId | tieWithId}``."""

    outcomes: List[Dict[str, str]] = []
    for record in raw or []:
        if not isinstance(record, Mapping):
            continue
        tie = _normalize_candidate_id(record.get("tieWithId"))
        winner = _normalize_candidate_id(record.get("winnerId"))
        loser = _normalize_candidate_id(record.get("loserId"))
        if tie:
            other = _normalize_candidate_id(record.get("otherId"))
            if tie and other and tie != other:
                outcomes.append({"kind": "tie", "a": tie, "b": other})
            continue
        if winner and loser and winner != loser:
            outcomes.append({"kind": "win", "winner": winner, "loser": loser})
    return outcomes


def apply_pairwise_round(
    ratings: Mapping[str, float],
    outcomes: Sequence[Dict[str, str]],
    *,
    k_factor: float = DEFAULT_K_FACTOR,
) -> Dict[str, float]:
    """Apply one round of pairwise outcomes to the rating table.

    Outcomes are applied in the given order (rounds are sequential by
    design); a rating table without a candidate starts it at the default.
    """

    table = {key: float(value) for key, value in dict(ratings).items()}
    for outcome in outcomes:
        if outcome.get("kind") == "win":
            winner = str(outcome["winner"])
            loser = str(outcome["loser"])
            rating_winner = table.get(winner, DEFAULT_INITIAL_RATING)
            rating_loser = table.get(loser, DEFAULT_INITIAL_RATING)
            expected_winner = _expected_score(rating_winner, rating_loser)
            table[winner] = rating_winner + k_factor * (1.0 - expected_winner)
            table[loser] = rating_loser + k_factor * (0.0 - (1.0 - expected_winner))
        elif outcome.get("kind") == "tie":
            a = str(outcome["a"])
            b = str(outcome["b"])
            rating_a = table.get(a, DEFAULT_INITIAL_RATING)
            rating_b = table.get(b, DEFAULT_INITIAL_RATING)
            expected_a = _expected_score(rating_a, rating_b)
            table[a] = rating_a + k_factor * (0.5 - expected_a)
            table[b] = rating_b + k_factor * (0.5 - (1.0 - expected_a))
    return table


def rank_candidates(ratings: Mapping[str, float]) -> List[Dict[str, Any]]:
    """Deterministic ranking: rating desc, then candidateId asc for ties."""

    ordered = sorted(
        ((rating, _normalize_candidate_id(candidate_id)) for candidate_id, rating in dict(ratings).items()),
        key=lambda item: (-item[0], item[1]),
    )
    return [
        {"rank": index, "candidateId": candidate_id, "rating": round(rating, 2)}
        for index, (rating, candidate_id) in enumerate(ordered, start=1)
    ]


def build_tournament_artifact(
    *,
    tournament_id: str,
    pairwise_outcomes_by_round: Sequence[Sequence[Mapping[str, Any]]],
    prior_ratings: Mapping[str, Any] | None = None,
    k_factor: float = DEFAULT_K_FACTOR,
    created_at: str,
) -> Dict[str, Any]:
    """Fold all rounds into one auditable tournament artifact."""

    ratings = normalize_ratings(prior_ratings)
    normalized_rounds = [normalize_pairwise_outcomes(round_raw) for round_raw in pairwise_outcomes_by_round]
    round_snapshots: List[Dict[str, Any]] = []
    for round_index, outcomes in enumerate(normalized_rounds, start=1):
        ratings = apply_pairwise_round(ratings, outcomes, k_factor=k_factor)
        round_snapshots.append(
            {
                "round": round_index,
                "outcomeCount": len(outcomes),
                "ratings": {key: round(value, 2) for key, value in sorted(ratings.items())},
            }
        )
    return {
        "schemaVersion": TOURNAMENT_ARTIFACT_CONTRACT_VERSION,
        "tournamentId": _normalize_candidate_id(tournament_id),
        "kFactor": float(k_factor),
        "initialRating": DEFAULT_INITIAL_RATING,
        "rounds": round_snapshots,
        "totalOutcomes": sum(snapshot["outcomeCount"] for snapshot in round_snapshots),
        "ranking": rank_candidates(ratings),
        "createdAt": str(created_at or "").strip(),
    }


def validate_tournament_artifact(artifact: Mapping[str, Any]) -> List[str]:
    """Return human-readable contract violations (empty list = valid)."""

    problems: List[str] = []
    if not isinstance(artifact, Mapping):
        return ["artifact must be a JSON object"]
    if artifact.get("schemaVersion") != TOURNAMENT_ARTIFACT_CONTRACT_VERSION:
        problems.append(f"schemaVersion must be {TOURNAMENT_ARTIFACT_CONTRACT_VERSION}")
    if not _normalize_candidate_id(artifact.get("tournamentId")):
        problems.append("tournamentId is required")
    ranking = artifact.get("ranking")
    if not isinstance(ranking, list) or not ranking:
        problems.append("ranking must be a non-empty list")
    else:
        for entry in ranking:
            if not isinstance(entry, Mapping) or not _normalize_candidate_id(entry.get("candidateId")):
                problems.append("ranking entries need candidateId")
                break
    if not isinstance(artifact.get("rounds"), list):
        problems.append("rounds must be a list")
    return problems


def _outcomes_from_comparisons(comparisons: Sequence[Mapping[str, Any]]) -> List[Dict[str, str]]:
    """Adapt executor comparisons (left_wins/right_wins/tie) to Elo inputs."""

    adapted: List[Dict[str, str]] = []
    for record in comparisons:
        if not isinstance(record, Mapping):
            continue
        left = _normalize_candidate_id(record.get("leftCandidateId"))
        right = _normalize_candidate_id(record.get("rightCandidateId"))
        outcome = str(record.get("outcome") or "").strip().lower()
        if not left or not right or left == right:
            continue
        if outcome == "left_wins":
            adapted.append({"kind": "win", "winner": left, "loser": right})
        elif outcome == "right_wins":
            adapted.append({"kind": "win", "winner": right, "loser": left})
        elif outcome == "tie":
            adapted.append({"kind": "tie", "a": left, "b": right})
    return adapted


def tournament_from_comparisons(
    comparisons: Sequence[Mapping[str, Any]],
    *,
    tournament_id: str,
    created_at: str,
    k_factor: float = DEFAULT_K_FACTOR,
) -> Dict[str, Any]:
    """Fold one hypothesis-review round's comparisons into an Elo artifact.

    ``build_tournament_artifact`` re-normalizes raw ``winnerId`` records, so
    the already-normalized internal outcomes are folded here directly.
    """

    outcomes = _outcomes_from_comparisons(comparisons)
    ratings = apply_pairwise_round({}, outcomes, k_factor=k_factor)
    return {
        "schemaVersion": TOURNAMENT_ARTIFACT_CONTRACT_VERSION,
        "tournamentId": _normalize_candidate_id(tournament_id),
        "kFactor": float(k_factor),
        "initialRating": DEFAULT_INITIAL_RATING,
        "rounds": [
            {
                "round": 1,
                "outcomeCount": len(outcomes),
                "ratings": {key: round(value, 2) for key, value in sorted(ratings.items())},
            }
        ],
        "totalOutcomes": len(outcomes),
        "ranking": rank_candidates(ratings),
        "createdAt": str(created_at or "").strip(),
    }
