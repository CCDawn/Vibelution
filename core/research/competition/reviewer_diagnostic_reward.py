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
  五维数值评分通道（HYPOTHESIS_SCORE_DIMENSIONS）不进 v1：其持久化形态
  与轮次记录的绑定关系需另行核实，留作后续任务。
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

from core.research.workflow.contracts import ContractValidationError
from .question_result_package import (
    REQUIRED_REVIEW_DIMENSIONS,
    REVIEW_DIMENSION_RATINGS,
)

DEFAULT_REFLECTION_REVIEWER = "research_evidence_reviewer"

RATING_ORDINAL: dict[str, int] = {
    rating: index for index, rating in enumerate(REVIEW_DIMENSION_RATINGS)
}
_ALLOWED_DIMENSIONS = frozenset(REQUIRED_REVIEW_DIMENSIONS)

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


def build_diagnostic_reward_report(
    rounds: Sequence[Mapping[str, Any]],
) -> DiagnosticRewardReport:
    """Compute diagnostic rewards over an ordered sequence of round records.

    Only critiques (audit rows rated below ``strong``) whose candidate also
    appears in the immediately following round contribute outcomes.
    """
    indexed_rounds = [_candidate_dimension_rows(record) for record in rounds]
    outcomes: list[CritiqueOutcome] = []
    transitions = 0
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

    by_reviewer: dict[str, ReviewerDiagnosticSummary] = {}
    dimension_totals: dict[str, list[CritiqueOutcome]] = {}
    reviewer_totals: dict[str, list[CritiqueOutcome]] = {}
    for outcome in outcomes:
        reviewer_totals.setdefault(outcome.reviewer, []).append(outcome)
        dimension_totals.setdefault(outcome.dimension, []).append(outcome)
    for reviewer, reviewer_outcomes in reviewer_totals.items():
        by_reviewer[reviewer] = _summarize(reviewer, reviewer_outcomes)
    by_dimension: dict[str, DimensionDiagnosticSummary] = {}
    for dimension, dimension_outcomes in dimension_totals.items():
        count = len(dimension_outcomes)
        by_dimension[dimension] = DimensionDiagnosticSummary(
            dimension=dimension,
            critique_count=count,
            improved_count=sum(1 for o in dimension_outcomes if o.improved),
            harmed_count=sum(1 for o in dimension_outcomes if o.harmed),
            mean_delta=(
                sum(o.delta for o in dimension_outcomes) / count if count else 0.0
            ),
        )
    overall = _summarize("(overall)", outcomes) if outcomes else None
    return DiagnosticRewardReport(
        rounds_examined=len(rounds),
        candidate_transitions=transitions,
        critique_outcomes=tuple(outcomes),
        by_reviewer=by_reviewer,
        by_dimension=by_dimension,
        overall=overall,
    )
