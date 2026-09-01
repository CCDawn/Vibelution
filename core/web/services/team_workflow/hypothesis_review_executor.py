"""Hypothesis review executor: four separated review steps for one closed meeting.

The executor turns the bounded review context (closed meeting digest v2 +
candidate hypotheses + evidence refs) into the content of a closable
``HypothesisRound``:

1. **Reflection** — every candidate is scored independently on the five
   decision dimensions; the two auxiliary diagnostics remain separate; owning
   role ``research_evidence_reviewer``.
2. **Pairwise debate** — every unordered candidate pair is compared once; the
   left/right presentation order is randomized from a recorded seed to
   mitigate position bias, and the persisted comparison fields record the
   order that was debated; owning role ``research_theme_synthesizer``.
3. **Pareto classification** — every candidate is classified as front or
   dominated over the five dimensions (no Elo-style single total score,
   D-02); owning role ``research_theme_synthesizer``.  The classification
   call shares the pairwise concurrency wave, and with exactly two
   candidates it is a deterministic dominance decision (no model call).
4. **MetaReview** — one recommendation with rationale, risk notes, and an
   acceptance flag; owning role is the meeting Coordinator.

DEV fixtures are deterministic (seeded from the review context id).  The
explicit ``DEV`` / ``FORMAL`` execution fence keeps those fixtures out of
formal review: FORMAL requires all five real runners and one provider-bound
model invocation receipt for every model call.
Every step fails closed: a missing dimension, an invalid or missing
comparison, an unclassified candidate, or a missing recommendation raises
``ContractValidationError`` before anything is persisted.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import logging
import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

from core.research.competition.question_result_package import (
    REQUIRED_REVIEW_DIMENSIONS,
    REVIEW_DIMENSION_RATINGS,
)
from core.research.workflow.contracts import (
    COMPARISON_OUTCOMES,
    MAX_FINALIST_LIMIT,
    REVIEW_CALL_BUDGET_FORMULA,
    SCORE_DIMENSIONS,
    ContractValidationError,
    CoreHypothesisCoherenceResult,
    ReviewCallBudget,
    review_call_budget_for,
    reconcile_review_call_budget,
)
from core.research.workflow.contracts.hypothesis_quality import (
    normalize_hypothesis_scores,
)
from core.research.workflow.contracts.model_invocation_receipt import (
    ModelInvocationReceipt,
    ModelInvocationStatus,
)

_LOGGER = logging.getLogger(__name__)

REFLECTION_ROLE = "research_evidence_reviewer"
PAIRWISE_ROLE = "research_theme_synthesizer"
PARETO_ROLE = "research_theme_synthesizer"
METAREVIEW_ROLE = "coordinator"

SCHEMA_VERSION = 1

# Reflection and pairwise fans out to one LLM call per candidate / pair; the
# executor only parallelizes that IO wait (never the validation below), so the
# review latency stays bounded instead of O(candidates + pairs) serial calls.
MAX_CONCURRENT_REVIEW_CALLS = 4


class HypothesisReviewExecutionMode(str, Enum):
    """Execution fence for deterministic development vs formal review output."""

    DEV = "dev"
    FORMAL = "formal"


def _source_collection_run_id_for_formal_workflow(workflow_run_id: str) -> str:
    """Resolve artifact authority from the canonical Ledger run snapshot."""

    normalized_run_id = str(workflow_run_id or "").strip()
    if not normalized_run_id:
        return ""
    try:
        from core.web.services.team_workflow.research_runtime.formal_write_runtime import (
            get_write_store,
        )

        run = get_write_store().get_run(normalized_run_id)
        snapshot = json.loads(str(getattr(run, "input_snapshot_json", "") or "{}"))
    except Exception:  # noqa: BLE001 - caller decides whether missing scope is fatal
        return ""
    if not isinstance(snapshot, Mapping):
        return ""
    return str(snapshot.get("sourceCollectionRunId") or "").strip()


@dataclass(frozen=True, slots=True)
class ProviderBoundReviewResult:
    """One parsed review payload paired with its provider-issued receipt."""

    payload: Mapping[str, Any]
    model_invocation_receipt: Mapping[str, Any] | None


def normalize_execution_mode(value: Any) -> HypothesisReviewExecutionMode:
    """Normalize the explicit review mode and reject unknown values."""

    raw = value.value if isinstance(value, HypothesisReviewExecutionMode) else str(value or "")
    normalized = raw.strip().lower() or HypothesisReviewExecutionMode.DEV.value
    try:
        return HypothesisReviewExecutionMode(normalized)
    except ValueError as exc:
        raise ContractValidationError(
            "hypothesis review execution mode must be one of: dev, formal; "
            f"got {normalized or '<empty>'}"
        ) from exc


def _require_formal_prerequisites(
    *,
    reflection_runner: ReflectionRunner | None,
    pairwise_runner: PairwiseRunner | None,
    pareto_runner: ParetoRunner | None,
    metareview_runner: MetaReviewRunner | None,
    revision_runner: RevisionRunner | None,
) -> None:
    """Keep FORMAL out of the DEV fixture path unless all runners are real."""

    runners = {
        "reflection": reflection_runner,
        "pairwise": pairwise_runner,
        "pareto": pareto_runner,
        "metareview": metareview_runner,
        "revision": revision_runner,
    }
    missing = [name for name, runner in runners.items() if not callable(runner)]
    if missing:
        raise ContractValidationError(
            "FORMAL hypothesis review requires all five real runners; missing: "
            + ", ".join(missing)
        )


ReviewRunnerResult = Mapping[str, Any] | ProviderBoundReviewResult | None
ReflectionRunner = Callable[[dict[str, Any], dict[str, Any]], ReviewRunnerResult]
PairwiseRunner = Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], ReviewRunnerResult]
ParetoRunner = Callable[[dict[str, dict[str, float]], dict[str, Any]], ReviewRunnerResult]
MetaReviewRunner = Callable[
    [dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]],
    ReviewRunnerResult,
]
RevisionRunner = Callable[
    [dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Any]],
    ReviewRunnerResult,
]


class HypothesisReviewExecutionError(RuntimeError):
    """Base error for hypothesis review execution."""


class CoreHypothesisCoherenceFailure(ContractValidationError):
    """Stage-one reflection found a non-compensable coherence defect."""

    code = "coherence_failure"

    def __init__(self, candidate_ids: Sequence[str], *, artifact_ref: str = "") -> None:
        self.candidate_ids = tuple(str(item) for item in candidate_ids)
        self.artifact_ref = str(artifact_ref or "")
        super().__init__(
            "coherence_failure: " + ", ".join(self.candidate_ids)
        )


def _validated_runner_payload(
    produced: ReviewRunnerResult,
    *,
    step_label: str,
    formal_receipts: list[dict[str, Any]] | None,
    required_outcome_kinds: Sequence[str] = ("review",),
) -> Mapping[str, Any] | None:
    """Unwrap a runner output and verify its provider receipt in FORMAL mode."""

    if isinstance(produced, ProviderBoundReviewResult):
        payload = produced.payload
    else:
        payload = produced
    if formal_receipts is None:
        return payload
    if not isinstance(produced, ProviderBoundReviewResult):
        raise ContractValidationError(
            f"FORMAL {step_label} must return a provider-bound model invocation receipt"
        )
    raw_receipt = produced.model_invocation_receipt
    if not isinstance(raw_receipt, Mapping):
        raise ContractValidationError(
            f"FORMAL {step_label} is missing a provider-bound model invocation receipt"
        )
    try:
        receipt = ModelInvocationReceipt.from_dict(raw_receipt)
    except (ContractValidationError, TypeError, ValueError) as exc:
        raise ContractValidationError(
            f"FORMAL {step_label} model invocation receipt is invalid: {exc}"
        ) from exc
    if receipt.status not in {
        ModelInvocationStatus.SUCCEEDED,
        ModelInvocationStatus.RETRIED,
    }:
        raise ContractValidationError(
            f"FORMAL {step_label} receipt status must be succeeded or retried"
        )
    question_stage = str(receipt.metadata.get("questionStage") or "").strip().lower()
    if question_stage != "review":
        raise ContractValidationError(
            f"FORMAL {step_label} receipt questionStage must be review"
        )
    outcome_kinds = {
        str(item or "").strip().lower()
        for item in list(receipt.metadata.get("outcomeKinds") or [])
        if str(item or "").strip()
    }
    required_kinds = {
        str(item or "").strip().lower()
        for item in required_outcome_kinds
        if str(item or "").strip()
    }
    if not required_kinds.issubset(outcome_kinds):
        raise ContractValidationError(
            f"FORMAL {step_label} receipt outcomeKinds must include "
            + ", ".join(sorted(required_kinds))
        )
    if any(item.get("receiptId") == receipt.receipt_id for item in formal_receipts):
        raise ContractValidationError(
            f"FORMAL hypothesis review contains duplicate receiptId {receipt.receipt_id}"
        )
    formal_receipts.append(receipt.to_dict())
    return payload


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def canonical_hypothesis_revision_snapshot(
    candidates: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return the stable R0/R1/R2 content used by two-phase lineage hashes.

    The snapshot deliberately excludes review scores and prose: those are
    observations about a hypothesis, not the hypothesis revision itself.
    Aliases let generation records (``statement``) and review inputs
    (``claim``) resolve to the same R1 hash.
    """

    normalized: list[dict[str, Any]] = []
    for raw in candidates:
        candidate_id = str(
            raw.get("candidateId") or raw.get("draftId") or ""
        ).strip()
        claim = str(raw.get("claim") or raw.get("statement") or "").strip()
        if not candidate_id or not claim:
            raise ContractValidationError(
                "hypothesis revision snapshot requires candidateId and claim"
            )
        axis_profile = raw.get("axisProfile")
        normalized.append(
            {
                "candidateId": candidate_id,
                "claim": claim,
                "lineageRefs": sorted(
                    {
                        str(item).strip()
                        for item in list(raw.get("lineageRefs") or [])
                        if str(item or "").strip()
                    }
                ),
                "testablePrediction": str(
                    raw.get("testablePrediction") or ""
                ).strip(),
                "falsifier": str(raw.get("falsifier") or "").strip(),
                "axisProfile": (
                    dict(axis_profile) if isinstance(axis_profile, Mapping) else {}
                ),
            }
        )
    return sorted(normalized, key=lambda item: item["candidateId"])


def _collect_runner_outputs(
    calls: Sequence[Callable[[], ReviewRunnerResult]],
    *,
    max_concurrent_calls: int,
) -> list[ReviewRunnerResult]:
    """Invoke runner thunks and return their raw outputs in input order.

    Only the IO-bound runner wait runs concurrently; receipt verification and
    all payload validation stay sequential afterwards, so the assembled review
    is deterministic and no partial output escapes.  ``max_concurrent_calls``
    below 2 degrades to the fully serial loop where a failing call prevents
    the later calls from being issued at all.  With real parallelism some
    later calls may already be in flight when an earlier one fails — they
    cannot be recalled — but the re-raised error is always the failing
    input's own exception, selected by input order, never completion order.
    """

    limit = max(1, int(max_concurrent_calls))
    outputs: list[ReviewRunnerResult] = []
    if limit == 1 or len(calls) <= 1:
        for call in calls:
            outputs.append(call())
        return outputs
    workers = min(limit, len(calls))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(call) for call in calls]
        for future in futures:
            outputs.append(future.result())
    return outputs


# Sentinel for "no raw output was collected for this step" that stays distinct
# from a collected ``None`` output (``None`` is a legal runner result that must
# still flow into sequential validation and fail closed there).
_PARETO_OUTPUT_NOT_COLLECTED = object()


def _pareto_model_call_required(candidate_count: int) -> bool:
    """N=2 Pareto is a pure two-way dominance decision over recorded scores.

    With exactly two candidates the Pareto partition is fully determined by
    the reflection scores (one dominates the other, or they are incomparable
    and share the front), so the deterministic ``_fixture_pareto`` dominance
    computation replaces the model call.  N>2 keeps the LLM classification.
    """

    return candidate_count != 2


def _collect_pairwise_and_pareto_outputs(
    context: Mapping[str, Any],
    reviewed_candidates: list[dict[str, Any]],
    *,
    pairwise_runner: PairwiseRunner | None,
    pareto_runner: ParetoRunner | None,
    position_seed: str,
    max_concurrent_calls: int,
) -> tuple[list[ReviewRunnerResult] | None, Any]:
    """Collect the pairwise and Pareto raw runner outputs in one bounded wave.

    Pareto only consumes the reflection scores, so its single call shares the
    pairwise fan-out wave (under the same ``max_concurrent_calls`` cap)
    instead of serializing behind the pairwise step.  Raw outputs are returned
    unvalidated: receipt verification and payload validation stay sequential
    in :func:`_pairwise_step` (pair order first) and then :func:`_pareto_step`,
    exactly like the previous serial arrangement.  A runner failure still
    re-raises the failing input's own exception in input order, and with
    ``max_concurrent_calls`` below 2 the wave degrades to the same serial
    order as before (all pairwise calls, then Pareto).
    """

    by_id = {str(item["candidateId"]): item for item in reviewed_candidates}
    pairs = deterministic_pairwise_order(list(by_id), position_seed)
    calls: list[Callable[[], ReviewRunnerResult]] = []
    if pairwise_runner is not None:
        calls.extend(
            lambda left=by_id[left_id], right=by_id[right_id]: pairwise_runner(
                dict(left), dict(right), dict(context)
            )
            for left_id, right_id in pairs
        )
    pairwise_count = len(calls)
    pareto_output: Any = _PARETO_OUTPUT_NOT_COLLECTED
    if pareto_runner is not None and _pareto_model_call_required(
        len(reviewed_candidates)
    ):
        scores_by_candidate = {
            str(item["candidateId"]): dict(item["scores"])
            for item in reviewed_candidates
        }
        calls.append(lambda: pareto_runner(scores_by_candidate, dict(context)))
    if calls:
        outputs = _collect_runner_outputs(
            calls, max_concurrent_calls=max_concurrent_calls
        )
        pairwise_outputs = outputs[:pairwise_count]
        if len(outputs) > pairwise_count:
            pareto_output = outputs[pairwise_count]
    else:
        pairwise_outputs = None
    return pairwise_outputs, pareto_output


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


def _validate_explicit_dimension_reviews(
    rows: Sequence[Any],
    *,
    candidate_id: str,
) -> list[dict[str, Any]]:
    """Validate explicit audit rows without deriving them from 5+2 scores."""

    allowed_dimensions = set(REQUIRED_REVIEW_DIMENSIONS)
    allowed_ratings = set(REVIEW_DIMENSION_RATINGS)
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise ContractValidationError("reflection dimensionReviews rows must be objects")
        hypothesis_id = str(
            raw.get("hypothesis_id") or raw.get("candidateId") or ""
        ).strip()
        dimension = str(raw.get("dimension") or "").strip()
        rating = str(raw.get("rating") or "").strip().lower()
        rationale = str(raw.get("rationale") or "").strip()
        reviewer = str(
            raw.get("reviewer") or raw.get("reviewerAgentId") or ""
        ).strip()
        evidence_refs = raw.get("evidence_refs", raw.get("evidenceRefs", []))
        if hypothesis_id != candidate_id:
            raise ContractValidationError(
                f"reflection dimensionReviews are not bound to candidate {candidate_id}"
            )
        if dimension not in allowed_dimensions or dimension in seen:
            raise ContractValidationError(
                "reflection dimensionReviews must cover exactly the seven audit dimensions"
            )
        if rating not in allowed_ratings or not rationale or not reviewer:
            raise ContractValidationError(
                f"reflection audit dimension {dimension} is incomplete"
            )
        if not isinstance(evidence_refs, list):
            raise ContractValidationError(
                f"reflection audit dimension {dimension} evidence_refs must be a list"
            )
        seen.add(dimension)
        normalized.append(
            {
                "hypothesis_id": hypothesis_id,
                "dimension": dimension,
                "rating": rating,
                "rationale": rationale,
                "reviewer": reviewer,
                "evidence_refs": [
                    str(item).strip()
                    for item in evidence_refs
                    if str(item or "").strip()
                ],
            }
        )
    if seen != allowed_dimensions:
        raise ContractValidationError(
            "reflection dimensionReviews must cover exactly the seven audit dimensions"
        )
    return normalized


def _reflection_step(
    context: Mapping[str, Any],
    candidates: list[dict[str, Any]],
    *,
    runner: ReflectionRunner | None,
    agent_id: str,
    formal_receipts: list[dict[str, Any]] | None,
    require_core_coherence: bool = False,
    max_concurrent_calls: int = MAX_CONCURRENT_REVIEW_CALLS,
) -> list[dict[str, Any]]:
    """Score every candidate independently on the five fixed dimensions."""

    context_id = str(context.get("contextId") or "")
    # Phase 1 acquires the raw runner outputs (the only concurrent part);
    # phase 2 validates receipts and payloads sequentially in input order, so
    # the shared formal_receipts list is never touched from worker threads.
    produced_by_candidate: list[ReviewRunnerResult] = []
    if runner is not None:
        produced_by_candidate = _collect_runner_outputs(
            [
                lambda candidate=candidate: runner(dict(candidate), dict(context))
                for candidate in candidates
            ],
            max_concurrent_calls=max_concurrent_calls,
        )
    reviewed: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        candidate_id = str(candidate["candidateId"])
        merged = dict(candidate)
        explicit_dimension_reviews: Any = None
        has_explicit_dimension_reviews = False
        coherence_receipt_ref = ""
        if runner is not None:
            raw_produced = produced_by_candidate[index]
            if isinstance(raw_produced, ProviderBoundReviewResult) and isinstance(
                raw_produced.model_invocation_receipt, Mapping
            ):
                coherence_receipt_ref = str(
                    raw_produced.model_invocation_receipt.get("receiptId") or ""
                ).strip()
            produced = _validated_runner_payload(
                raw_produced,
                step_label=f"reflection for candidate {candidate_id}",
                formal_receipts=formal_receipts,
            )
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
        raw_scores = merged.get("scores")
        if not isinstance(raw_scores, Mapping):
            raise ContractValidationError(
                f"reflection result for {candidate_id} is missing scores"
            )
        raw_diagnostics = merged.get("diagnostics")
        if raw_diagnostics is not None and not isinstance(raw_diagnostics, Mapping):
            raise ContractValidationError(
                f"reflection diagnostics for {candidate_id} must be an object"
            )
        missing = [dimension for dimension in SCORE_DIMENSIONS if dimension not in raw_scores]
        if missing:
            raise ContractValidationError(
                f"reflection result for {candidate_id} is missing review dimensions: "
                + ", ".join(missing)
            )
        try:
            scores, diagnostics = normalize_hypothesis_scores(
                raw_scores,
                raw_diagnostics=raw_diagnostics,
            )
        except ContractValidationError as exc:
            raise ContractValidationError(
                f"reflection result for {candidate_id} has invalid scores: {exc}"
            ) from exc
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
            "scores": scores,
            "reviewedBy": str(merged.get("reviewedBy") or "").strip() or agent_id,
            "status": str(merged.get("status") or "").strip() or "reviewed",
        }
        if diagnostics:
            reviewed_item["diagnostics"] = diagnostics
        if has_explicit_dimension_reviews:
            reviewed_item["dimensionReviews"] = _validate_explicit_dimension_reviews(
                list(explicit_dimension_reviews),
                candidate_id=candidate_id,
            )
        if require_core_coherence:
            raw_coherence = merged.get("coreHypothesisCoherence")
            if not isinstance(raw_coherence, Mapping):
                raise ContractValidationError(
                    f"coherence_failure: candidate {candidate_id} is missing the five-item core coherence gate"
                )
            coherence = CoreHypothesisCoherenceResult.from_review_payload(
                raw_coherence,
                candidate_id=candidate_id,
                reviewer=str(merged.get("reviewedBy") or "").strip() or agent_id,
                receipt_ref=coherence_receipt_ref,
            )
            reviewed_item["coreHypothesisCoherence"] = coherence.to_dict()
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
        f"五维独立评分对比：{left_id} 在 {len(left_ahead)} 维领先（{('、'.join(left_ahead)) or '无'}），"
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
    formal_receipts: list[dict[str, Any]] | None,
    max_concurrent_calls: int = MAX_CONCURRENT_REVIEW_CALLS,
    precomputed_outputs: Sequence[ReviewRunnerResult] | None = None,
) -> list[dict[str, Any]]:
    """Compare every unordered pair once, in the recorded randomized order.

    ``precomputed_outputs`` carries the raw runner outputs already collected
    by :func:`_collect_pairwise_and_pareto_outputs`; when it is ``None`` the
    step collects its own wave (serial or pooled) exactly as before.
    """

    by_id = {str(item["candidateId"]): item for item in candidates}
    pairs = deterministic_pairwise_order(list(by_id), position_seed)
    produced_by_pair: list[ReviewRunnerResult] = []
    if runner is not None:
        if precomputed_outputs is not None:
            produced_by_pair = list(precomputed_outputs)
        else:
            produced_by_pair = _collect_runner_outputs(
                [
                    lambda left=by_id[left_id], right=by_id[right_id]: runner(
                        dict(left), dict(right), dict(context)
                    )
                    for left_id, right_id in pairs
                ],
                max_concurrent_calls=max_concurrent_calls,
            )
    comparisons: list[dict[str, Any]] = []
    for index, (left_id, right_id) in enumerate(pairs):
        left = by_id[left_id]
        right = by_id[right_id]
        if runner is not None:
            produced = _validated_runner_payload(
                produced_by_pair[index],
                step_label=f"pairwise comparison {left_id} vs {right_id}",
                formal_receipts=formal_receipts,
            )
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
    expected = {frozenset(pair) for pair in pairs}
    missing = expected - covered
    if missing:
        for left_id, right_id in pairs:
            if frozenset((left_id, right_id)) in missing:
                raise ContractValidationError(
                    f"missing pairwise comparison between {left_id} and {right_id}"
                )
    return comparisons


def _fixture_pareto(scores_by_candidate: Mapping[str, Mapping[str, float]]) -> tuple[list[str], list[str]]:
    """Dominance over the five decision dimensions; the front is non-dominated."""

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


def _two_candidate_pareto_note(
    front: Sequence[str],
    dominated: Sequence[str],
) -> str:
    """Explain the deterministic N=2 dominance decision in review notes."""

    if dominated:
        return (
            "候选恰好 2 条：Pareto 分类由五维评分 dominance 确定性判定，"
            f"{dominated[0]} 在全部五维不高于 {front[0]} 且至少一维更低，"
            f"判为被支配，{front[0]} 位于前沿。"
        )
    return (
        "候选恰好 2 条：Pareto 分类由五维评分 dominance 确定性判定，"
        "两候选互不全维占优（各有领先维度或五维全相等），同处前沿。"
    )


def _pareto_step(
    context: Mapping[str, Any],
    candidates: list[dict[str, Any]],
    *,
    runner: ParetoRunner | None,
    agent_id: str,
    formal_receipts: list[dict[str, Any]] | None,
    precomputed_output: Any = _PARETO_OUTPUT_NOT_COLLECTED,
) -> dict[str, Any]:
    """Classify every candidate as Pareto front or dominated (fail closed).

    With exactly two candidates the partition is a pure dominance decision
    over the recorded reflection scores, so the deterministic computation
    replaces the model call (``_pareto_model_call_required``); the output
    shape is identical to the LLM classification.
    """

    scores_by_candidate = {
        str(item["candidateId"]): dict(item["scores"]) for item in candidates
    }
    if runner is not None and not _pareto_model_call_required(
        len(scores_by_candidate)
    ):
        front, dominated = _fixture_pareto(scores_by_candidate)
        notes = _two_candidate_pareto_note(front, dominated)
    elif runner is not None:
        raw_produced = (
            runner(scores_by_candidate, dict(context))
            if precomputed_output is _PARETO_OUTPUT_NOT_COLLECTED
            else precomputed_output
        )
        produced = _validated_runner_payload(
            raw_produced,
            step_label="Pareto classification",
            formal_receipts=formal_receipts,
        )
        if not isinstance(produced, Mapping):
            raise ContractValidationError("pareto runner must return a mapping")
        front = [str(item) for item in list(produced.get("paretoFrontCandidateIds") or [])]
        dominated = [str(item) for item in list(produced.get("dominatedCandidateIds") or [])]
        notes = str(produced.get("notes") or "").strip()
    else:
        front, dominated = _fixture_pareto(scores_by_candidate)
        notes = "五维评分 Pareto 分类：前沿候选不被任何其他候选全维度占优（DEV fixture）。"
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
    formal_receipts: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Produce the Coordinator MetaReview with recommendation and acceptance."""

    if runner is not None:
        produced = _validated_runner_payload(
            runner(
                dict(context),
                [dict(item) for item in candidates],
                [dict(item) for item in pairwise],
                dict(pareto),
            ),
            step_label="MetaReview",
            formal_receipts=formal_receipts,
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


def _required_text_list(value: Any, *, field: str) -> list[str]:
    if not isinstance(value, (list, tuple)):
        raise ContractValidationError(f"formal revision {field} must be a list")
    normalized = [
        str(item).strip() for item in value if str(item or "").strip()
    ]
    if not normalized:
        raise ContractValidationError(
            f"formal revision {field} must contain explicit evidence"
        )
    return list(dict.fromkeys(normalized))


def _revision_step(
    context: Mapping[str, Any],
    parent_candidates: list[dict[str, Any]],
    meta_review: Mapping[str, Any],
    *,
    runner: RevisionRunner,
    round_id: str,
    formal_receipts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Produce one real R2 set by revising the MetaReview recommendation.

    Candidate identity remains stable while content changes.  This keeps the
    review/pairwise authorities bound to R1 and records R2 separately instead
    of rewriting the reviewed round or creating a second candidate store.
    """

    recommended_id = str(
        meta_review.get("recommendationCandidateId") or ""
    ).strip()
    parent_by_id = {
        str(item.get("candidateId") or "").strip(): dict(item)
        for item in parent_candidates
    }
    parent = parent_by_id.get(recommended_id)
    if parent is None:
        raise ContractValidationError(
            "formal revision requires the MetaReview recommendation in the R1 set"
        )
    raw_produced = runner(
        dict(context),
        dict(parent),
        [dict(item) for item in parent_candidates],
        dict(meta_review),
    )
    receipt_ref = ""
    if isinstance(raw_produced, ProviderBoundReviewResult) and isinstance(
        raw_produced.model_invocation_receipt, Mapping
    ):
        receipt_ref = str(
            raw_produced.model_invocation_receipt.get("receiptId") or ""
        ).strip()
    produced = _validated_runner_payload(
        raw_produced,
        step_label="hypothesis revision",
        formal_receipts=formal_receipts,
        required_outcome_kinds=("review", "revision"),
    )
    if not isinstance(produced, Mapping):
        raise ContractValidationError("formal revision runner must return a mapping")
    raw_revised = produced.get("revisedCandidate")
    if not isinstance(raw_revised, Mapping):
        raise ContractValidationError(
            "formal revision output requires a revisedCandidate object"
        )
    revised_id = str(raw_revised.get("candidateId") or "").strip()
    if revised_id != recommended_id:
        raise ContractValidationError(
            "formal revision must preserve the recommended candidateId"
        )
    revised_claim = str(raw_revised.get("claim") or "").strip()
    parent_claim = str(parent.get("claim") or parent.get("statement") or "").strip()
    if not revised_claim or revised_claim == parent_claim:
        raise ContractValidationError(
            "formal revision must produce genuinely new hypothesis text"
        )
    revised = dict(parent)
    for key in (
        "claim",
        "rationale",
        "differenceFromAlternatives",
        "lineageRefs",
        "testablePrediction",
        "falsifier",
        "axisProfile",
    ):
        if key in raw_revised:
            revised[key] = raw_revised[key]
    revised["candidateId"] = recommended_id
    revised["claim"] = revised_claim
    child_candidates = [
        revised
        if str(item.get("candidateId") or "").strip() == recommended_id
        else dict(item)
        for item in parent_candidates
    ]
    parent_snapshot = canonical_hypothesis_revision_snapshot(parent_candidates)
    child_snapshot = canonical_hypothesis_revision_snapshot(child_candidates)
    if child_snapshot == parent_snapshot:
        raise ContractValidationError(
            "formal revision output is identical to its R1 parent"
        )
    feedback_text = "；".join(
        item
        for item in (
            str(meta_review.get("rationale") or "").strip(),
            str(meta_review.get("riskNotes") or "").strip(),
        )
        if item
    )
    if not feedback_text:
        raise ContractValidationError(
            "formal revision requires explicit MetaReview feedback"
        )
    changes = _required_text_list(produced.get("changes"), field="changes")
    unresolved = _required_text_list(
        produced.get("unresolvedIssues"), field="unresolvedIssues"
    )
    r1_refs = [
        f"hypothesis_candidate:{item['candidateId']}:r1" for item in parent_snapshot
    ]
    r2_refs = [
        f"hypothesis_candidate:{item['candidateId']}:r2" for item in child_snapshot
    ]
    return {
        "schemaVersion": 1,
        "phase": "review_revision",
        "parentCandidateId": recommended_id,
        "revisionReceiptRef": receipt_ref,
        "feedback": {
            "trigger": "formal_hypothesis_review",
            "humanFeedback": feedback_text,
            "inputRefs": r1_refs,
            "inputHash": _stable_hash(parent_snapshot),
        },
        "revision": {
            "changes": changes,
            "unresolvedIssues": unresolved,
            "outputRefs": r2_refs,
            "outputHash": _stable_hash(child_snapshot),
            "status": "completed",
            "actual": True,
            "output": {"candidates": child_snapshot},
        },
    }


def execute_hypothesis_review(
    context: Mapping[str, Any],
    *,
    round_id: str = "",
    execution_mode: str | HypothesisReviewExecutionMode | None = None,
    reflection_runner: ReflectionRunner | None = None,
    pairwise_runner: PairwiseRunner | None = None,
    pareto_runner: ParetoRunner | None = None,
    metareview_runner: MetaReviewRunner | None = None,
    revision_runner: RevisionRunner | None = None,
    reviewer_assignments: Mapping[str, Any] | None = None,
    position_seed: str = "",
    max_concurrent_calls: int | None = None,
    expected_review_call_budget: Mapping[str, Any] | ReviewCallBudget | None = None,
) -> dict[str, Any]:
    """Run separated review steps over one bounded review context.

    ``execution_mode`` defaults to ``DEV`` for existing fixture callers.  A
    ``FORMAL`` request is fenced before any review step: all five real runners
    plus a real revision runner must be present, every call must return a
    unique provider-bound receipt, and the finalist count may not exceed
    ``MAX_FINALIST_LIMIT`` — the exact Stage-1 review call budget is
    ``n + n(n-1)/2 + 2`` review calls (n individual + n(n-1)/2 pairwise +
    Pareto + MetaReview), so extra candidates fail closed instead of silently
    spending an over-budget C(n,2) fan-out; trimming candidates belongs to the
    upstream screening, never to this executor.
    The reflection and pairwise runner calls run with bounded parallelism
    (``max_concurrent_calls``; default ``MAX_CONCURRENT_REVIEW_CALLS``, values
    below 2 fall back to fully serial invocation); the single Pareto model
    call shares the pairwise wave because it only consumes the reflection
    scores.  Raw outputs are always validated sequentially in step order
    (reflection, pairwise, Pareto, MetaReview) and every step still fails
    closed on any incomplete output.  With exactly two candidates the Pareto
    classification is a pure dominance decision over the recorded scores, so
    it is computed locally and consumes no model call; the budget record
    still counts the Pareto step, mirroring the DEV fixture convention where
    the structural step count is reconciled while zero model calls are spent.
    ``expected_review_call_budget`` lets the caller pass the budget it derived
    upstream; a disagreement with the actual candidate set fails closed before
    any review call.

    Returns the candidate scores, pairwise comparisons, Pareto analysis, and
    MetaReview ready for ``HypothesisRound`` persistence, plus the role
    attribution, the recorded pairwise position seed, and the
    ``reviewCallBudget`` record proving the exact budget was respected.
    Raises ``ContractValidationError`` on any incomplete step output.
    """

    if not isinstance(context, Mapping):
        raise ContractValidationError("hypothesis review requires a review context mapping")
    mode = normalize_execution_mode(execution_mode)
    if mode is HypothesisReviewExecutionMode.FORMAL:
        _require_formal_prerequisites(
            reflection_runner=reflection_runner,
            pairwise_runner=pairwise_runner,
            pareto_runner=pareto_runner,
            metareview_runner=metareview_runner,
            revision_runner=revision_runner,
        )
    effective_concurrency = (
        MAX_CONCURRENT_REVIEW_CALLS if max_concurrent_calls is None else int(max_concurrent_calls)
    )
    formal_receipts: list[dict[str, Any]] | None = (
        [] if mode is HypothesisReviewExecutionMode.FORMAL else None
    )
    candidates = _context_candidates(context)
    finalist_count = len(candidates)
    # Exact Stage-1 review call budget (n + n(n-1)/2 + 2).  Fail closed
    # before any review call when the wiring disagrees with the candidate
    # set or the finalist count busts the formal budget.
    if expected_review_call_budget is not None:
        expected_budget = (
            expected_review_call_budget
            if isinstance(expected_review_call_budget, ReviewCallBudget)
            else ReviewCallBudget.from_dict(expected_review_call_budget)
        )
        if expected_budget.finalistCount != finalist_count:
            raise ContractValidationError(
                "review call budget was derived for "
                f"{expected_budget.finalistCount} finalists but the review "
                f"context carries {finalist_count} candidates "
                f"({expected_budget.describe()})"
            )
    budget = review_call_budget_for(finalist_count)
    if finalist_count > MAX_FINALIST_LIMIT:
        formal_budget = review_call_budget_for(MAX_FINALIST_LIMIT)
        over_budget_detail = (
            f"{finalist_count} candidates would require {budget.totalReviewCalls} "
            f"review calls ({budget.describe()}); formal review allows at most "
            f"{MAX_FINALIST_LIMIT} finalists ({formal_budget.describe()})"
        )
        if mode is HypothesisReviewExecutionMode.FORMAL:
            raise ContractValidationError(
                "formal hypothesis review exceeds the exact review call budget: "
                f"{over_budget_detail}; reduce the finalists upstream at "
                "screening instead of silently over-running the budget here"
            )
        _LOGGER.warning(
            "dev hypothesis review exceeds the exact review call budget: %s; "
            "trim candidates upstream at screening",
            over_budget_detail,
        )
    require_core_coherence = bool(context.get("requireCoreHypothesisCoherence")) or (
        bool(candidates)
        and all(
            str(item.get("candidateAuthority") or "").strip().lower()
            == "formal_grounded_candidate"
            for item in candidates
        )
    )
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
        context,
        candidates,
        runner=reflection_runner,
        agent_id=reflection_agent,
        formal_receipts=formal_receipts,
        require_core_coherence=require_core_coherence,
        max_concurrent_calls=effective_concurrency,
    )
    coherence_results = [
        dict(item.get("coreHypothesisCoherence"))
        for item in reviewed_candidates
        if isinstance(item.get("coreHypothesisCoherence"), Mapping)
    ]
    if require_core_coherence:
        if len(coherence_results) != len(reviewed_candidates):
            raise ContractValidationError(
                "coherence_failure: every stage-one finalist requires a core coherence result"
            )
        coherence_artifact_ref = ""
        if formal_receipts is not None:
            authority = (
                context.get("_modelInvocationReceiptAuthority")
                if isinstance(context.get("_modelInvocationReceiptAuthority"), Mapping)
                else {}
            )
            team_id = str(context.get("teamId") or "").strip()
            workflow_run_id = str(authority.get("workflowRunId") or "").strip()
            source_collection_run_id = str(
                authority.get("sourceCollectionRunId") or ""
            ).strip() or _source_collection_run_id_for_formal_workflow(
                workflow_run_id
            )
            from core.research.competition.stage_one_completion_policy import (
                STAGE_ONE_POLICY_QUESTION_IDS,
            )

            question_id = str(context.get("questionId") or "").strip().upper()
            if not team_id or not workflow_run_id:
                raise ContractValidationError(
                    "coherence_failure: formal coherence artifact scope is unavailable"
                )
            if (
                question_id in STAGE_ONE_POLICY_QUESTION_IDS
                and not source_collection_run_id
            ):
                raise ContractValidationError(
                    "coherence_failure: stage-one source collection authority is unavailable"
                )
            from core.web.services.team_workflow.research_runtime.core_hypothesis_coherence_artifact_writer import (
                record_core_hypothesis_coherence_artifact,
            )

            coherence_artifact_ref = record_core_hypothesis_coherence_artifact(
                team_id=team_id,
                workflow_run_id=workflow_run_id,
                source_collection_run_id=source_collection_run_id,
                review_context_id=str(context.get("contextId") or ""),
                results=coherence_results,
                require_receipts=True,
            )["canonicalRef"]
        failed = [
            str(item.get("candidateId") or "")
            for item in coherence_results
            if item.get("passed") is not True
        ]
        if failed:
            raise CoreHypothesisCoherenceFailure(
                failed,
                artifact_ref=coherence_artifact_ref,
            )
    else:
        coherence_artifact_ref = ""
    # One bounded wave carries the pairwise fan-out and the single Pareto
    # call (Pareto only consumes the reflection scores); the raw outputs are
    # then validated sequentially — pairwise first, then Pareto — so the
    # fail-closed aggregation order is unchanged.
    pairwise_outputs, pareto_output = _collect_pairwise_and_pareto_outputs(
        context,
        reviewed_candidates,
        pairwise_runner=pairwise_runner,
        pareto_runner=pareto_runner,
        position_seed=seed,
        max_concurrent_calls=effective_concurrency,
    )
    comparisons = _pairwise_step(
        context,
        reviewed_candidates,
        runner=pairwise_runner,
        agent_id=pairwise_agent,
        position_seed=seed,
        round_id=round_id,
        formal_receipts=formal_receipts,
        max_concurrent_calls=effective_concurrency,
        precomputed_outputs=pairwise_outputs,
    )
    pareto = _pareto_step(
        context,
        reviewed_candidates,
        runner=pareto_runner,
        agent_id=pareto_agent,
        formal_receipts=formal_receipts,
        precomputed_output=pareto_output,
    )
    meta_review = _metareview_step(
        context,
        reviewed_candidates,
        comparisons,
        pareto,
        runner=metareview_runner,
        agent_id=metareview_agent,
        round_id=round_id,
        formal_receipts=formal_receipts,
    )
    # Record actual review-step spending against the exact budget.  The four
    # contract-enumerated steps (reflection / pairwise / Pareto / MetaReview)
    # must exhaust the formula exactly; the FORMAL revision call stays
    # outside the formula and is recorded separately for deadline accounting.
    reconciliation = reconcile_review_call_budget(
        budget,
        individual_review_calls=len(reviewed_candidates),
        pairwise_comparison_calls=len(comparisons),
        pareto_calls=1,
        metareview_calls=1,
    )
    budget_record = {
        **budget.to_dict(),
        "actual": reconciliation.to_dict(),
    }
    revision_envelope = None
    if mode is HypothesisReviewExecutionMode.FORMAL:
        assert revision_runner is not None
        assert formal_receipts is not None
        revision_envelope = _revision_step(
            context,
            candidates,
            meta_review,
            runner=revision_runner,
            round_id=round_id,
            formal_receipts=formal_receipts,
        )
        budget_record["revisionRunnerCalls"] = 1
        if not reconciliation.exact:
            raise ContractValidationError(
                "formal hypothesis review deviated from the exact review call "
                f"budget ({REVIEW_CALL_BUDGET_FORMULA}): "
                + reconciliation.deviation_detail()
            )
    result = {
        "schemaVersion": SCHEMA_VERSION,
        "executionMode": mode.value,
        "reviewContextId": str(context.get("contextId") or ""),
        "positionSeed": seed,
        "candidates": reviewed_candidates,
        "pairwiseComparisons": comparisons,
        "pareto": pareto,
        "metaReview": meta_review,
        "reviewCallBudget": budget_record,
        "roles": {
            "reflection": reflection_agent,
            "pairwise": pairwise_agent,
            "pareto": pareto_agent,
            "metareview": metareview_agent,
        },
    }
    if formal_receipts is not None:
        result["modelInvocationReceipts"] = formal_receipts
        result["revisionEnvelope"] = revision_envelope
    if require_core_coherence:
        result["coreHypothesisCoherence"] = coherence_results
        result["coreHypothesisCoherenceArtifactRef"] = coherence_artifact_ref
    return result
