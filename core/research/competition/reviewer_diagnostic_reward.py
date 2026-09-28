# -*- coding: utf-8 -*-
"""评审者诊断奖励的纯计算层（diagnostic-reward meta-evaluation）。

把一串已持久化的 HypothesisRound 记录（调用方按时间顺序提供）转成
「评审者的审计批评 → 被批候选在下一轮同维度评级变化」的归因统计：
这是 CoNL（ICML 2026, arXiv:2601.21464）诊断奖励 r_diag 的免训练、
事后计算版本——批评质量用「被批评对象随后是否在该维度改善」衡量，
不依赖任何 ground-truth 标签。

设计决策（v1, 2026-09-17）：

- 维度与评级直接复用假说链的审计契约：七维 ``REQUIRED_REVIEW_DIMENSIONS``
  × 五档 ordinal ``REVIEW_DIMENSION_RATINGS``（insufficient=0 … strong=4）。
  v1.1（2026-09-18）核实生产轮次的持久化形态后新增**数值分数通道**：轮次
  候选内联携带五维 ``SCORE_DIMENSIONS`` 0-1 浮点分，按同样的相邻轮次×
  同候选配对计算维度级 delta（批评=基线分未达 1.0）；ordinal 通道依赖的
  权威审计行存储（``dimensionReviewRefs`` 所指）尚未接线，两通道独立报告。
- 「批评」的定义：评级低于 ``strong`` 的审计维度行（存在改进空间的发现）。
  评级为 strong 的行不构成批评，也不参与 delta 计算。
- 归因配对：只在相邻两轮（rounds[i], rounds[i+1]）中按 ``candidateId``
  匹配同一候选；候选跨轮缺席即不贡献样本。轮次顺序由调用方保证
  （append-only JSONL 的读取顺序即为时间顺序）。
- 评审者归属优先级：行内 ``reviewer`` / ``reviewerAgentId`` → 轮记录
  ``roles["reflection"]`` → 默认 ``research_evidence_reviewer``（reflection
  步骤的 owning role，与 hypothesis_review_executor 的常量一致；此处不
  import web 层，避免 competition 层反向依赖）。
- 奖励口径：``reward = max(0, delta)``（改进为正；退化计 0 奖励但计入
  harm_rate 与 mean_delta）。同时报告 improved/harmed/unchanged 计数与
  improvement_rate 的 95% Wilson 区间下界（小样本透明；方法与
  ``calibration_stats`` 的 Wilson 实现同族，独立实现以保持本模块零依赖）。
- fail-closed：评级/维度/候选绑定非法、或同一候选同维度出现重复行时抛
  ``ContractValidationError``；空序列或无可配对候选返回空统计（数据缺失
  不是契约违规）。

No I/O, no state, no network; every function is deterministic.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from core.research.workflow.contracts import ContractValidationError, SCORE_DIMENSIONS
from .question_result_package import (
    REQUIRED_REVIEW_DIMENSIONS,
    REVIEW_DIMENSION_RATINGS,
)

DEFAULT_REFLECTION_REVIEWER = "research_evidence_reviewer"

RATING_ORDINAL: dict[str, int] = {
    rating: index for index, rating in enumerate(REVIEW_DIMENSION_RATINGS)
}
_ALLOWED_DIMENSIONS = frozenset(REQUIRED_REVIEW_DIMENSIONS)

# 数值分数通道的「批评」定义：维度基线分未达满分即存在改进空间（与
# ordinal 通道「评级低于 strong」同义）。生产持久化的五维分数为 0-1 浮点。
_SCORE_CRITIQUE_HEADROOM = 0.999
_SCORE_DIMENSIONS = frozenset(SCORE_DIMENSIONS)

_WILSON_Z = 1.959963984540054  # two-sided 95%


@dataclass(frozen=True, slots=True)
class CritiqueOutcome:
    """One attributed critique and the next-round rating change it faces."""

    reviewer: str
    candidate_id: str
    dimension: str
    from_round_index: int
    to_round_index: int
    rating_from: str
    rating_to: str
    delta: int
    reward: int
    improved: bool
    harmed: bool


@dataclass(frozen=True, slots=True)
class ReviewerDiagnosticSummary:
    reviewer: str
    critique_count: int
    improved_count: int
    harmed_count: int
    unchanged_count: int
    improvement_rate: float
    harm_rate: float
    mean_reward: float
    mean_delta: float
    improvement_rate_wilson_lower: float


@dataclass(frozen=True, slots=True)
class DimensionDiagnosticSummary:
    dimension: str
    critique_count: int
    improved_count: int
    harmed_count: int
    mean_delta: float


@dataclass(frozen=True, slots=True)
class DiagnosticRewardReport:
    rounds_examined: int
    candidate_transitions: int
    critique_outcomes: tuple[CritiqueOutcome, ...]
    by_reviewer: dict[str, ReviewerDiagnosticSummary] = field(default_factory=dict)
    by_dimension: dict[str, DimensionDiagnosticSummary] = field(default_factory=dict)
    overall: ReviewerDiagnosticSummary | None = None
    # 数值分数通道（生产轮次内联的五维 0-1 分数；2026-09-18 核实持久化
    # 形态后启用）。ordinal 通道依赖的权威审计行存储尚未接线，两者独立。
    score_outcomes: tuple[ScoreCritiqueOutcome, ...] = ()
    score_by_reviewer: dict[str, ReviewerDiagnosticSummary] = field(default_factory=dict)
    score_by_dimension: dict[str, DimensionDiagnosticSummary] = field(default_factory=dict)
    score_overall: ReviewerDiagnosticSummary | None = None
    score_candidate_transitions: int = 0


@dataclass(frozen=True, slots=True)
class ScoreCritiqueOutcome:
    """One numeric-score critique and the next-round score change it faces."""

    reviewer: str
    candidate_id: str
    dimension: str
    from_round_index: int
    to_round_index: int
    score_from: float
    score_to: float
    delta: float
    reward: float
    improved: bool
    harmed: bool


def rating_ordinal(rating: str) -> int:
    """Validate one audit rating and return its ordinal (0..4)."""
    normalized = str(rating or "").strip().lower()
    if normalized not in RATING_ORDINAL:
        raise ContractValidationError(
            f"unknown review dimension rating {rating!r}; "
            f"allowed ratings are {list(REVIEW_DIMENSION_RATINGS)}"
        )
    return RATING_ORDINAL[normalized]


def _wilson_lower_bound(successes: int, trials: int, z: float = _WILSON_Z) -> float:
    """Lower limit of the two-sided 95% Wilson score interval for a proportion."""
    if trials <= 0:
        return 0.0
    p = successes / trials
    denominator = 1.0 + z * z / trials
    centre = p + z * z / (2.0 * trials)
    margin = z * math.sqrt(p * (1.0 - p) / trials + z * z / (4.0 * trials * trials))
    return max(0.0, (centre - margin) / denominator)


def _candidate_dimension_rows(
    round_record: Mapping[str, Any]
) -> dict[str, dict[str, Mapping[str, Any]]]:
    """Index one round's audit rows as {candidateId: {dimension: row}}.

    Fail-closed on rows without dimension/rating, on unknown dimensions, on
    duplicate (candidate, dimension) rows, and on rows whose explicit
    candidate binding contradicts the candidate they are stored under.
    """
    indexed: dict[str, dict[str, Mapping[str, Any]]] = {}
    candidates = round_record.get("candidates")
    if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)):
        return indexed
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        candidate_id = str(candidate.get("candidateId") or "").strip()
        if not candidate_id:
            continue
        rows = candidate.get("dimensionReviews", candidate.get("dimension_reviews"))
        if rows is None:
            continue
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            raise ContractValidationError(
                f"candidate {candidate_id} dimensionReviews must be a list"
            )
        by_dimension: dict[str, Mapping[str, Any]] = {}
        for row in rows:
            if not isinstance(row, Mapping):
                raise ContractValidationError(
                    f"candidate {candidate_id} dimensionReviews rows must be objects"
                )
            row_candidate = str(
                row.get("candidateId") or row.get("hypothesis_id") or ""
            ).strip()
            if row_candidate and row_candidate != candidate_id:
                raise ContractValidationError(
                    f"dimension review row bound to {row_candidate!r} is stored "
                    f"under candidate {candidate_id!r}"
                )
            dimension = str(row.get("dimension") or "").strip()
            if dimension not in _ALLOWED_DIMENSIONS:
                raise ContractValidationError(
                    f"unknown audit dimension {dimension!r}; allowed dimensions "
                    f"are {list(REQUIRED_REVIEW_DIMENSIONS)}"
                )
            if dimension in by_dimension:
                raise ContractValidationError(
                    f"candidate {candidate_id} has duplicate audit rows for "
                    f"dimension {dimension!r}"
                )
            rating_ordinal(str(row.get("rating") or ""))
            by_dimension[dimension] = row
        indexed[candidate_id] = by_dimension
    return indexed


def _row_reviewer(
    round_record: Mapping[str, Any], row: Mapping[str, Any]
) -> str:
    explicit = str(row.get("reviewer") or row.get("reviewerAgentId") or "").strip()
    if explicit:
        return explicit
    roles = round_record.get("roles")
    if isinstance(roles, Mapping):
        reflection_agent = str(roles.get("reflection") or "").strip()
        if reflection_agent:
            return reflection_agent
    return DEFAULT_REFLECTION_REVIEWER


def _summarize(
    reviewer: str, outcomes: Sequence[CritiqueOutcome]
) -> ReviewerDiagnosticSummary:
    count = len(outcomes)
    improved = sum(1 for outcome in outcomes if outcome.improved)
    harmed = sum(1 for outcome in outcomes if outcome.harmed)
    mean_reward = sum(outcome.reward for outcome in outcomes) / count if count else 0.0
    mean_delta = sum(outcome.delta for outcome in outcomes) / count if count else 0.0
    return ReviewerDiagnosticSummary(
        reviewer=reviewer,
        critique_count=count,
        improved_count=improved,
        harmed_count=harmed,
        unchanged_count=count - improved - harmed,
        improvement_rate=improved / count if count else 0.0,
        harm_rate=harmed / count if count else 0.0,
        mean_reward=mean_reward,
        mean_delta=mean_delta,
        improvement_rate_wilson_lower=_wilson_lower_bound(improved, count),
    )


def _dimension_summary(
    dimension: str, outcomes: Sequence[Any]
) -> DimensionDiagnosticSummary:
    count = len(outcomes)
    return DimensionDiagnosticSummary(
        dimension=dimension,
        critique_count=count,
        improved_count=sum(1 for o in outcomes if o.improved),
        harmed_count=sum(1 for o in outcomes if o.harmed),
        mean_delta=(sum(o.delta for o in outcomes) / count if count else 0.0),
    )


def _candidate_scores(
    round_record: Mapping[str, Any]
) -> dict[str, dict[str, float]]:
    """Index one round's inline five-dimension scores per candidate.

    Fail-closed on unknown dimension keys and non-numeric values; unknown
    shape elsewhere is absence, not a violation.
    """
    indexed: dict[str, dict[str, float]] = {}
    candidates = round_record.get("candidates")
    if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)):
        return indexed
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        candidate_id = str(candidate.get("candidateId") or "").strip()
        if not candidate_id:
            continue
        scores = candidate.get("scores")
        if not isinstance(scores, Mapping):
            continue
        dims: dict[str, float] = {}
        for key, value in scores.items():
            dimension = str(key).strip()
            if dimension not in _SCORE_DIMENSIONS:
                raise ContractValidationError(
                    f"unknown score dimension {dimension!r}; allowed dimensions "
                    f"are {list(SCORE_DIMENSIONS)}"
                )
            if dimension in dims:
                raise ContractValidationError(
                    f"candidate {candidate_id} has duplicate score for {dimension!r}"
                )
            try:
                dims[dimension] = float(value)
            except (TypeError, ValueError) as exc:
                raise ContractValidationError(
                    f"candidate {candidate_id} score for {dimension!r} is not numeric"
                ) from exc
        indexed[candidate_id] = dims
    return indexed


def _candidate_score_reviewer(
    round_record: Mapping[str, Any], candidate: Mapping[str, Any]
) -> str:
    explicit = str(candidate.get("reviewedBy") or "").strip()
    if explicit:
        return explicit
    roles = round_record.get("roles")
    if isinstance(roles, Mapping):
        reflection_agent = str(roles.get("reflection") or "").strip()
        if reflection_agent:
            return reflection_agent
    return DEFAULT_REFLECTION_REVIEWER


def build_diagnostic_reward_report(
    rounds: Sequence[Mapping[str, Any]],
) -> DiagnosticRewardReport:
    """Compute diagnostic rewards over an ordered sequence of round records.

    Only critiques (audit rows rated below ``strong``) whose candidate also
    appears in the immediately following round contribute outcomes. The
    numeric lane applies the same pairing to the inline five-dimension
    scores, counting dimensions with headroom (below 1.0) as critiques.
    """
    indexed_rounds = [_candidate_dimension_rows(record) for record in rounds]
    outcomes: list[CritiqueOutcome] = []
    transitions = 0
    score_indexed_rounds = [_candidate_scores(record) for record in rounds]
    score_candidates_by_round: list[dict[str, Mapping[str, Any]]] = []
    for record in rounds:
        candidates = record.get("candidates")
        entries: dict[str, Mapping[str, Any]] = {}
        if isinstance(candidates, Sequence) and not isinstance(candidates, (str, bytes)):
            for candidate in candidates:
                if isinstance(candidate, Mapping):
                    candidate_id = str(candidate.get("candidateId") or "").strip()
                    if candidate_id:
                        entries[candidate_id] = candidate
        score_candidates_by_round.append(entries)
    score_outcomes: list[ScoreCritiqueOutcome] = []
    score_transitions = 0
    for index in range(len(rounds) - 1):
        current, following = indexed_rounds[index], indexed_rounds[index + 1]
        for candidate_id, current_rows in current.items():
            following_rows = following.get(candidate_id)
            if following_rows is None:
                continue
            transitions += 1
            for dimension, row in current_rows.items():
                rating_from = str(row.get("rating") or "")
                if RATING_ORDINAL[rating_from] >= RATING_ORDINAL["strong"]:
                    continue
                rating_to = str(following_rows[dimension].get("rating") or "") if dimension in following_rows else None
                if rating_to is None:
                    # 批评维度在下一轮缺失：不是契约违规（fail-closed 只约束
                    # 单轮结构），但也不能虚构「未变化」，跳过并保持可审计。
                    continue
                delta = RATING_ORDINAL[rating_to] - RATING_ORDINAL[rating_from]
                outcomes.append(
                    CritiqueOutcome(
                        reviewer=_row_reviewer(rounds[index], row),
                        candidate_id=candidate_id,
                        dimension=dimension,
                        from_round_index=index,
                        to_round_index=index + 1,
                        rating_from=rating_from,
                        rating_to=rating_to,
                        delta=delta,
                        reward=max(0, delta),
                        improved=delta > 0,
                        harmed=delta < 0,
                    )
                )
        current_scores = score_indexed_rounds[index]
        following_scores = score_indexed_rounds[index + 1]
        for candidate_id, current_dims in current_scores.items():
            following_dims = following_scores.get(candidate_id)
            if following_dims is None:
                continue
            score_transitions += 1
            for dimension, score_from in current_dims.items():
                if score_from >= _SCORE_CRITIQUE_HEADROOM:
                    continue
                if dimension not in following_dims:
                    continue
                score_to = following_dims[dimension]
                score_delta = score_to - score_from
                score_outcomes.append(
                    ScoreCritiqueOutcome(
                        reviewer=_candidate_score_reviewer(
                            rounds[index], score_candidates_by_round[index][candidate_id]
                        ),
                        candidate_id=candidate_id,
                        dimension=dimension,
                        from_round_index=index,
                        to_round_index=index + 1,
                        score_from=score_from,
                        score_to=score_to,
                        delta=score_delta,
                        reward=max(0.0, score_delta),
                        improved=score_delta > 0,
                        harmed=score_delta < 0,
                    )
                )

    by_reviewer: dict[str, ReviewerDiagnosticSummary] = {}
    dimension_totals: dict[str, list[CritiqueOutcome]] = {}
    reviewer_totals: dict[str, list[CritiqueOutcome]] = {}
    for outcome in outcomes:
        reviewer_totals.setdefault(outcome.reviewer, []).append(outcome)
        dimension_totals.setdefault(outcome.dimension, []).append(outcome)
    for reviewer, reviewer_outcomes in reviewer_totals.items():
        by_reviewer[reviewer] = _summarize(reviewer, reviewer_outcomes)
    by_dimension: dict[str, DimensionDiagnosticSummary] = {
        dimension: _dimension_summary(dimension, dimension_outcomes)
        for dimension, dimension_outcomes in dimension_totals.items()
    }
    overall = _summarize("(overall)", outcomes) if outcomes else None

    score_reviewer_totals: dict[str, list[ScoreCritiqueOutcome]] = {}
    score_dimension_totals: dict[str, list[ScoreCritiqueOutcome]] = {}
    for outcome in score_outcomes:
        score_reviewer_totals.setdefault(outcome.reviewer, []).append(outcome)
        score_dimension_totals.setdefault(outcome.dimension, []).append(outcome)
    score_by_reviewer = {
        reviewer: _summarize(reviewer, reviewer_outcomes)
        for reviewer, reviewer_outcomes in score_reviewer_totals.items()
    }
    score_by_dimension = {
        dimension: _dimension_summary(dimension, dimension_outcomes)
        for dimension, dimension_outcomes in score_dimension_totals.items()
    }
    score_overall = (
        _summarize("(overall)", score_outcomes) if score_outcomes else None
    )
    return DiagnosticRewardReport(
        rounds_examined=len(rounds),
        candidate_transitions=transitions,
        critique_outcomes=tuple(outcomes),
        by_reviewer=by_reviewer,
        by_dimension=by_dimension,
        overall=overall,
        score_outcomes=tuple(score_outcomes),
        score_by_reviewer=score_by_reviewer,
        score_by_dimension=score_by_dimension,
        score_overall=score_overall,
        score_candidate_transitions=score_transitions,
    )
