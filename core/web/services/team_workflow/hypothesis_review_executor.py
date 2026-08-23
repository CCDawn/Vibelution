"""Hypothesis review executor: four separated review steps for one closed meeting.

The executor turns the bounded review context (closed meeting digest v2 +
candidate hypotheses + evidence refs) into the content of a closable
``HypothesisRound``:

1. **Reflection** — every candidate is scored independently on the seven
   fixed review dimensions; owning role ``research_evidence_reviewer``.
2. **Pairwise debate** — every unordered candidate pair is compared once; the
   left/right presentation order is randomized from a recorded seed to
   mitigate position bias, and the persisted comparison fields record the
   order that was debated; owning role ``research_theme_synthesizer``.
3. **Pareto classification** — every candidate is classified as front or
   dominated over the seven dimensions (no Elo-style single total score,
   D-02); owning role ``research_theme_synthesizer``.
4. **MetaReview** — one recommendation with rationale, risk notes, and an
   acceptance flag; owning role is the meeting Coordinator.

DEV fixtures are deterministic (seeded from the review context id); inject
``reflection_runner`` / ``pairwise_runner`` / ``pareto_runner`` /
``metareview_runner`` to delegate a step to a real role later.  Every step
fails closed: a missing dimension, an invalid or missing comparison, an
unclassified candidate, or a missing recommendation raises
``ContractValidationError`` before anything is persisted.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from typing import Any

from core.research.workflow.contracts import (
    COMPARISON_OUTCOMES,
    SCORE_DIMENSIONS,
    ContractValidationError,
)

REFLECTION_ROLE = "research_evidence_reviewer"
PAIRWISE_ROLE = "research_theme_synthesizer"
PARETO_ROLE = "research_theme_synthesizer"
METAREVIEW_ROLE = "coordinator"

SCHEMA_VERSION = 1

ReflectionRunner = Callable[[dict[str, Any], dict[str, Any]], Mapping[str, Any] | None]
PairwiseRunner = Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], Mapping[str, Any] | None]
ParetoRunner = Callable[[dict[str, dict[str, float]], dict[str, Any]], Mapping[str, Any] | None]
MetaReviewRunner = Callable[
    [dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]],
    Mapping[str, Any] | None,
]


class HypothesisReviewExecutionError(RuntimeError):
    """Base error for hypothesis review execution."""


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def deterministic_pairwise_order(
    candidate_ids: Sequence[str],
    position_seed: str,
) -> list[tuple[str, str]]:
    """Return the debated (left, right) order of every unordered pair.

    The order is shuffled from ``position_seed`` so position bias is not
    correlated with candidate identity; the persisted comparison's
    ``leftCandidateId``/``rightCandidateId`` record the debated order, and
    replaying this function with the same seed reproduces it exactly.
    """
    ids = [str(item) for item in candidate_ids]
    rng = random.Random(f"hypothesis-review-pairwise:{position_seed}")
    ordered: list[tuple[str, str]] = []
    for index, left in enumerate(ids):
        for right in ids[index + 1 :]:
            if rng.random() < 0.5:
                ordered.append((right, left))
            else:
                ordered.append((left, right))
    return ordered


def _fixture_score(context_id: str, candidate_id: str, dimension: str) -> float:
    digest = hashlib.sha256(f"{context_id}:{candidate_id}:{dimension}".encode()).hexdigest()
    return round(0.5 + (int(digest[:8], 16) % 46) / 100.0, 2)


def _context_candidates(context: Mapping[str, Any]) -> list[dict[str, Any]]:
    candidates = [
        dict(item)
        for item in list(context.get("candidates") or [])
        if isinstance(item, Mapping) and str(item.get("candidateId") or "").strip()
    ]
    if len(candidates) < 2:
        raise ContractValidationError(
            "hypothesis review requires at least two candidates in the review context"
        )
    ids = [str(item["candidateId"]) for item in candidates]
    if len(set(ids)) != len(ids):
        raise ContractValidationError("review context candidateId values must be unique")
    return candidates


def _reflection_step(
    context: Mapping[str, Any],
    candidates: list[dict[str, Any]],
    *,
    runner: ReflectionRunner | None,
    agent_id: str,
) -> list[dict[str, Any]]:
    """Score every candidate independently on the seven fixed dimensions."""

    context_id = str(context.get("contextId") or "")
    reviewed: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_id = str(candidate["candidateId"])
        merged = dict(candidate)
        explicit_dimension_reviews: Any = None
        has_explicit_dimension_reviews = False
        if runner is not None:
            produced = runner(dict(candidate), dict(context))
            if not isinstance(produced, Mapping):
                raise ContractValidationError(
                    f"reflection runner must return a mapping for candidate {candidate_id}"
                )
            merged.update(dict(produced))
            # The v2 dimension rows are an independent output of the real
            # reflection runner.  Preserve them verbatim for the canonical
            # artifact writer; never manufacture rows from scores.
            if "dimensionReviews" in produced:
                explicit_dimension_reviews = produced["dimensionReviews"]
                has_explicit_dimension_reviews = True
            elif "dimension_reviews" in produced:
                explicit_dimension_reviews = produced["dimension_reviews"]
                has_explicit_dimension_reviews = True
            if has_explicit_dimension_reviews and not isinstance(
                explicit_dimension_reviews, (list, tuple)
            ):
                raise ContractValidationError(
                    f"reflection dimensionReviews for {candidate_id} must be a list"
                )
        else:
            merged["scores"] = {
                dimension: _fixture_score(context_id, candidate_id, dimension)
                for dimension in SCORE_DIMENSIONS
            }
        if not str(merged.get("claim") or "").strip():
            raise ContractValidationError(
                f"reflection candidate {candidate_id} requires a non-empty claim"
            )
        if not str(merged.get("differenceFromAlternatives") or "").strip():
            raise ContractValidationError(
                f"reflection candidate {candidate_id} requires differenceFromAlternatives"
            )
        scores = merged.get("scores")
        if not isinstance(scores, Mapping):
            raise ContractValidationError(
                f"reflection result for {candidate_id} is missing scores"
            )
        missing = [dimension for dimension in SCORE_DIMENSIONS if dimension not in scores]
        if missing:
            raise ContractValidationError(
                f"reflection result for {candidate_id} is missing review dimensions: "
                + ", ".join(missing)
            )
        reviewed_item = {
            "candidateId": candidate_id,
            "claim": str(merged.get("claim") or "").strip(),
            "rationale": str(merged.get("rationale") or "").strip(),
            "differenceFromAlternatives": str(
                merged.get("differenceFromAlternatives") or ""
            ).strip(),
            "lineageRefs": [
                str(item) for item in list(merged.get("lineageRefs") or [])
            ],
            "scores": {dimension: scores[dimension] for dimension in SCORE_DIMENSIONS},
            "reviewedBy": str(merged.get("reviewedBy") or "").strip() or agent_id,
            "status": str(merged.get("status") or "").strip() or "reviewed",
        }
        if has_explicit_dimension_reviews:
            reviewed_item["dimensionReviews"] = deepcopy(list(explicit_dimension_reviews))
        reviewed.append(reviewed_item)
    return reviewed


def _fixture_debate_outcome(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
) -> tuple[str, str]:
    """DEV pairwise debate: the candidate ahead on more dimensions wins."""

    left_scores = left.get("scores") if isinstance(left.get("scores"), Mapping) else {}
    right_scores = right.get("scores") if isinstance(right.get("scores"), Mapping) else {}
    left_ahead = [
        dimension
        for dimension in SCORE_DIMENSIONS
        if float(left_scores.get(dimension) or 0) > float(right_scores.get(dimension) or 0)
    ]
    right_ahead = [
        dimension
        for dimension in SCORE_DIMENSIONS
        if float(right_scores.get(dimension) or 0) > float(left_scores.get(dimension) or 0)
    ]
    left_id = str(left.get("candidateId") or "")
    right_id = str(right.get("candidateId") or "")
    if len(left_ahead) > len(right_ahead):
        outcome = "left_wins"
    elif len(right_ahead) > len(left_ahead):
        outcome = "right_wins"
    else:
        outcome = "tie"
    justification = (
        f"七维独立评分对比：{left_id} 在 {len(left_ahead)} 维领先（{('、'.join(left_ahead)) or '无'}），"
        f"{right_id} 在 {len(right_ahead)} 维领先（{('、'.join(right_ahead)) or '无'}）。"
    )
    return outcome, justification


def _pairwise_step(
    context: Mapping[str, Any],
    candidates: list[dict[str, Any]],
    *,
    runner: PairwiseRunner | None,
    agent_id: str,
    position_seed: str,
    round_id: str,
) -> list[dict[str, Any]]:
    """Compare every unordered pair once, in the recorded randomized order."""

    by_id = {str(item["candidateId"]): item for item in candidates}
    comparisons: list[dict[str, Any]] = []
    for left_id, right_id in deterministic_pairwise_order(list(by_id), position_seed):
        left = by_id[left_id]
        right = by_id[right_id]
        if runner is not None:
            produced = runner(dict(left), dict(right), dict(context))
            if not isinstance(produced, Mapping):
                raise ContractValidationError(
                    "pairwise runner must return a mapping for pair "
                    f"{left_id} vs {right_id}"
                )
            outcome = str(produced.get("outcome") or "").strip().lower()
            justification = str(produced.get("justification") or "").strip()
        else:
            outcome, justification = _fixture_debate_outcome(left, right)
        if outcome not in COMPARISON_OUTCOMES:
            raise ContractValidationError(
                f"pairwise comparison {left_id} vs {right_id} produced an invalid outcome: "
                f"{outcome or '<empty>'}"
            )
        if not justification:
            raise ContractValidationError(
                f"pairwise comparison {left_id} vs {right_id} requires a justification"
            )
        comparisons.append(
            {
                "comparisonId": f"cmp-{_stable_hash({'roundId': round_id, 'left': left_id, 'right': right_id, 'seed': position_seed})[:12]}",
                "leftCandidateId": left_id,
                "rightCandidateId": right_id,
                "reviewerAgentId": agent_id,
                "outcome": outcome,
                "justification": justification,
            }
        )
    covered = {
        frozenset((item["leftCandidateId"], item["rightCandidateId"])) for item in comparisons
    }
    expected = {
        frozenset(pair)
        for pair in deterministic_pairwise_order(list(by_id), position_seed)
    }
    missing = expected - covered
    if missing:
        for left_id, right_id in deterministic_pairwise_order(list(by_id), position_seed):
            if frozenset((left_id, right_id)) in missing:
                raise ContractValidationError(
                    f"missing pairwise comparison between {left_id} and {right_id}"
                )
    return comparisons


def _fixture_pareto(scores_by_candidate: Mapping[str, Mapping[str, float]]) -> tuple[list[str], list[str]]:
    """Dominance over the seven dimensions; the front is the non-dominated set."""

    ids = list(scores_by_candidate)

    def dominates(left_id: str, right_id: str) -> bool:
        left = scores_by_candidate[left_id]
        right = scores_by_candidate[right_id]
        return all(
            float(left.get(dimension) or 0) >= float(right.get(dimension) or 0)
            for dimension in SCORE_DIMENSIONS
        ) and any(
            float(left.get(dimension) or 0) > float(right.get(dimension) or 0)
            for dimension in SCORE_DIMENSIONS
        )

    front = [
        candidate_id
        for candidate_id in ids
        if not any(other != candidate_id and dominates(other, candidate_id) for other in ids)
    ]
    dominated = [candidate_id for candidate_id in ids if candidate_id not in front]
    return front, dominated


def _pareto_step(
    context: Mapping[str, Any],
    candidates: list[dict[str, Any]],
    *,
    runner: ParetoRunner | None,
    agent_id: str,
) -> dict[str, Any]:
    """Classify every candidate as Pareto front or dominated (fail closed)."""

    scores_by_candidate = {
        str(item["candidateId"]): dict(item["scores"]) for item in candidates
    }
    if runner is not None:
        produced = runner(scores_by_candidate, dict(context))
        if not isinstance(produced, Mapping):
            raise ContractValidationError("pareto runner must return a mapping")
        front = [str(item) for item in list(produced.get("paretoFrontCandidateIds") or [])]
        dominated = [str(item) for item in list(produced.get("dominatedCandidateIds") or [])]
        notes = str(produced.get("notes") or "").strip()
    else:
        front, dominated = _fixture_pareto(scores_by_candidate)
        notes = "七维评分 Pareto 分类：前沿候选不被任何其他候选全维度占优（DEV fixture）。"
    candidate_ids = set(scores_by_candidate)
    overlap = set(front) & set(dominated)
    if overlap:
        raise ContractValidationError(
            "a candidate cannot be both on the Pareto front and dominated: "
            + ", ".join(sorted(overlap))
        )
    unknown = (set(front) | set(dominated)) - candidate_ids
    if unknown:
        raise ContractValidationError(
            "Pareto analysis references unknown candidates: " + ", ".join(sorted(unknown))
        )
    missing = candidate_ids - (set(front) | set(dominated))
    if missing:
        raise ContractValidationError(
            "Pareto analysis must classify every candidate: " + ", ".join(sorted(missing))
        )
    if not front:
        raise ContractValidationError("a closed round requires a non-empty Pareto front")
    return {
        "paretoFrontCandidateIds": front,
        "dominatedCandidateIds": dominated,
        "analystAgentId": agent_id,
        "notes": notes,
    }


def _fixture_metareview(
    context: Mapping[str, Any],
    candidates: list[dict[str, Any]],
    pairwise: list[dict[str, Any]],
    pareto: Mapping[str, Any],
) -> dict[str, Any]:
    """DEV MetaReview: recommend the front candidate with the most debate wins."""

    wins = {str(item["candidateId"]): 0 for item in candidates}
    for comparison in pairwise:
        if comparison["outcome"] == "left_wins":
            wins[comparison["leftCandidateId"]] += 1
        elif comparison["outcome"] == "right_wins":
            wins[comparison["rightCandidateId"]] += 1
    front = [str(item) for item in list(pareto.get("paretoFrontCandidateIds") or [])]
    recommendation = min(front, key=lambda candidate_id: (-wins[candidate_id], candidate_id))
    digest = context.get("digest") if isinstance(context.get("digest"), Mapping) else {}
    agreement_count = len(list(digest.get("agreements") or []))
    disagreement_count = len(list(digest.get("disagreements") or []))
    risks = [str(item) for item in list(digest.get("risks") or [])]
    rationale = (
        f"推荐 {recommendation}：位于 Pareto 前沿且两两比较胜出 {wins[recommendation]} 场；"
        f"会议共识 {agreement_count} 条、分歧 {disagreement_count} 条已纳入评审上下文。"
    )
    return {
        "recommendationCandidateId": recommendation,
        "rationale": rationale,
        "riskNotes": "；".join(risks),
        "accepted": True,
    }


def _metareview_step(
    context: Mapping[str, Any],
    candidates: list[dict[str, Any]],
    pairwise: list[dict[str, Any]],
    pareto: Mapping[str, Any],
    *,
    runner: MetaReviewRunner | None,
    agent_id: str,
    round_id: str,
) -> dict[str, Any]:
    """Produce the Coordinator MetaReview with recommendation and acceptance."""

    if runner is not None:
        produced = runner(
            dict(context),
            [dict(item) for item in candidates],
            [dict(item) for item in pairwise],
            dict(pareto),
        )
        if not isinstance(produced, Mapping):
            raise ContractValidationError("metareview runner must return a mapping")
        review = dict(produced)
    else:
        review = _fixture_metareview(context, candidates, pairwise, pareto)
    candidate_ids = {str(item["candidateId"]) for item in candidates}
    recommendation = str(review.get("recommendationCandidateId") or "").strip()
    if not recommendation:
        raise ContractValidationError("MetaReview requires a recommendation candidate")
    if recommendation not in candidate_ids:
        raise ContractValidationError(
            "MetaReview recommendation references an unknown candidate"
        )
    return {
        "metaReviewId": str(review.get("metaReviewId") or "").strip()
        or f"meta-{_stable_hash({'roundId': round_id, 'recommendation': recommendation})[:12]}",
        "reviewerAgentId": str(review.get("reviewerAgentId") or "").strip() or agent_id,
        "recommendationCandidateId": recommendation,
        "rationale": str(review.get("rationale") or "").strip(),
        "riskNotes": str(review.get("riskNotes") or "").strip(),
        "accepted": bool(review.get("accepted")),
    }


def execute_hypothesis_review(
    context: Mapping[str, Any],
    *,
    round_id: str = "",
    reflection_runner: ReflectionRunner | None = None,
    pairwise_runner: PairwiseRunner | None = None,
    pareto_runner: ParetoRunner | None = None,
    metareview_runner: MetaReviewRunner | None = None,
    reviewer_assignments: Mapping[str, Any] | None = None,
    position_seed: str = "",
) -> dict[str, Any]:
    """Run the four separated review steps over one bounded review context.

    Returns the candidate scores, pairwise comparisons, Pareto analysis, and
    MetaReview ready for ``HypothesisRound`` persistence, plus the role
    attribution and the recorded pairwise position seed.  Raises
    ``ContractValidationError`` on any incomplete step output.
    """

    if not isinstance(context, Mapping):
        raise ContractValidationError("hypothesis review requires a review context mapping")
    candidates = _context_candidates(context)
    assignments = dict(reviewer_assignments) if isinstance(reviewer_assignments, Mapping) else {}
    reflection_agent = str(assignments.get("reflection") or "").strip() or REFLECTION_ROLE
    pairwise_agent = str(assignments.get("pairwise") or "").strip() or PAIRWISE_ROLE
    pareto_agent = str(assignments.get("pareto") or "").strip() or PARETO_ROLE
    metareview_agent = str(assignments.get("metareview") or "").strip()
    if not metareview_agent:
        raise ContractValidationError(
            "hypothesis review requires a MetaReview reviewer (meeting Coordinator)"
        )
    seed = str(position_seed or "").strip() or _stable_hash(
        {
            "contextId": str(context.get("contextId") or ""),
            "candidateIds": [str(item["candidateId"]) for item in candidates],
        }
    )[:16]

    reviewed_candidates = _reflection_step(
        context, candidates, runner=reflection_runner, agent_id=reflection_agent
    )
    comparisons = _pairwise_step(
        context,
        reviewed_candidates,
        runner=pairwise_runner,
        agent_id=pairwise_agent,
        position_seed=seed,
        round_id=round_id,
    )
    pareto = _pareto_step(context, reviewed_candidates, runner=pareto_runner, agent_id=pareto_agent)
    meta_review = _metareview_step(
        context,
        reviewed_candidates,
        comparisons,
        pareto,
        runner=metareview_runner,
        agent_id=metareview_agent,
        round_id=round_id,
    )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "reviewContextId": str(context.get("contextId") or ""),
        "positionSeed": seed,
        "candidates": reviewed_candidates,
        "pairwiseComparisons": comparisons,
        "pareto": pareto,
        "metaReview": meta_review,
        "roles": {
            "reflection": reflection_agent,
            "pairwise": pairwise_agent,
            "pareto": pareto_agent,
            "metareview": metareview_agent,
        },
    }
