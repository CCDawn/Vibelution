"""Canonical 5+2 hypothesis quality rubric and score normalization.

The five decision dimensions drive the primary review and Pareto classification;
the two auxiliary dimensions remain diagnostics and never silently change the
primary ranking.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from ._canonical import sha256_hex
from ._validation import ContractValidationError, require_score

HYPOTHESIS_SCORE_RUBRIC_VERSION = "hypothesis-quality-rubric-v1"
HYPOTHESIS_SCORE_DIMENSIONS = (
    "novelty",
    "competitionFit",
    "falsifiability",
    "evidenceSupport",
    "feasibility",
)
AUXILIARY_HYPOTHESIS_DIAGNOSTIC_DIMENSIONS = (
    "replicability",
    "scopeAlignment",
)

_RUBRIC_BANDS: tuple[dict[str, Any], ...] = (
    {
        "minimum": 0.0,
        "maximum": 0.2,
        "maximumInclusive": False,
        "label": "insufficient",
        "descriptions": {
            "novelty": "已知方案复述，没有可辨认的新机制或组合。",
            "competitionFit": "偏离赛题、竞赛评价或交付边界。",
            "falsifiability": "不存在可观测的反驳结果。",
            "evidenceSupport": "没有可追溯证据，或现有证据直接反驳。",
            "feasibility": "在冻结资源、数据或时间内不可执行。",
        },
    },
    {
        "minimum": 0.2,
        "maximum": 0.4,
        "maximumInclusive": False,
        "label": "weak",
        "descriptions": {
            "novelty": "仅有局部参数变化或表面重组。",
            "competitionFit": "只弱关联部分赛题要求。",
            "falsifiability": "预测模糊且缺少阈值或失败判据。",
            "evidenceSupport": "只有单一、间接或低可信证据。",
            "feasibility": "依赖大量尚未获得的关键资源。",
        },
    },
    {
        "minimum": 0.4,
        "maximum": 0.6,
        "maximumInclusive": False,
        "label": "mixed",
        "descriptions": {
            "novelty": "有意义但仍明显依赖既有方案。",
            "competitionFit": "覆盖主要问题，但缺少关键竞赛交付。",
            "falsifiability": "可以测试，但判据或边界仍不完整。",
            "evidenceSupport": "证据方向混合且存在明显缺口。",
            "feasibility": "原则上可执行，但有重大外部依赖。",
        },
    },
    {
        "minimum": 0.6,
        "maximum": 0.8,
        "maximumInclusive": False,
        "label": "strong",
        "descriptions": {
            "novelty": "具有区别于备选的明确机制或组合。",
            "competitionFit": "强匹配赛题、指标和成果边界。",
            "falsifiability": "有明确预测、阈值和反例。",
            "evidenceSupport": "有多项相关证据，并检查了反证。",
            "feasibility": "冻结预算内可执行，风险可管理。",
        },
    },
    {
        "minimum": 0.8,
        "maximum": 1.0,
        "maximumInclusive": True,
        "label": "exceptional",
        "descriptions": {
            "novelty": "相对备选具有清晰、可核验的新贡献。",
            "competitionFit": "直接提升竞赛价值且没有范围漂移。",
            "falsifiability": "可预注册，正反结果均有确定解释。",
            "evidenceSupport": "独立证据、反证和边界条件均可追溯。",
            "feasibility": "资源、数据、时间和复现路径全部闭合。",
        },
    },
)


def canonical_hypothesis_score_rubric() -> dict[str, Any]:
    """Return the immutable 5+2 rubric body used for prompt and snapshot hashes."""

    return {
        "version": HYPOTHESIS_SCORE_RUBRIC_VERSION,
        "dimensions": list(HYPOTHESIS_SCORE_DIMENSIONS),
        "auxiliaryDiagnostics": list(AUXILIARY_HYPOTHESIS_DIAGNOSTIC_DIMENSIONS),
        "bands": copy.deepcopy(list(_RUBRIC_BANDS)),
    }


def hypothesis_score_rubric_sha256(payload: Mapping[str, Any]) -> str:
    return sha256_hex(dict(payload))


HYPOTHESIS_SCORE_RUBRIC_SHA256 = hypothesis_score_rubric_sha256(
    canonical_hypothesis_score_rubric()
)


def normalize_hypothesis_scores(
    raw_scores: Mapping[str, Any],
    *,
    raw_diagnostics: Mapping[str, Any] | None = None,
    allow_legacy_auxiliary_scores: bool = True,
) -> tuple[dict[str, float], dict[str, float]]:
    """Split five authoritative scores from the two optional diagnostics."""

    missing = [key for key in HYPOTHESIS_SCORE_DIMENSIONS if key not in raw_scores]
    if missing:
        raise ContractValidationError(
            "missing hypothesis scores: " + ", ".join(missing)
        )
    allowed_score_keys = set(HYPOTHESIS_SCORE_DIMENSIONS)
    if allow_legacy_auxiliary_scores:
        allowed_score_keys.update(AUXILIARY_HYPOTHESIS_DIAGNOSTIC_DIMENSIONS)
    unknown_scores = sorted(set(raw_scores) - allowed_score_keys)
    if unknown_scores:
        raise ContractValidationError(
            "unsupported hypothesis score dimensions: " + ", ".join(unknown_scores)
        )
    diagnostics_payload = dict(raw_diagnostics or {})
    unknown_diagnostics = sorted(
        set(diagnostics_payload) - set(AUXILIARY_HYPOTHESIS_DIAGNOSTIC_DIMENSIONS)
    )
    if unknown_diagnostics:
        raise ContractValidationError(
            "unsupported hypothesis diagnostic dimensions: "
            + ", ".join(unknown_diagnostics)
        )
    diagnostics: dict[str, float] = {}
    for dimension in AUXILIARY_HYPOTHESIS_DIAGNOSTIC_DIMENSIONS:
        legacy_present = dimension in raw_scores
        explicit_present = dimension in diagnostics_payload
        if (
            legacy_present
            and explicit_present
            and raw_scores[dimension] != diagnostics_payload[dimension]
        ):
            raise ContractValidationError(
                f"hypothesis diagnostic {dimension} disagrees with the legacy score"
            )
        if legacy_present or explicit_present:
            value = (
                raw_scores[dimension]
                if legacy_present
                else diagnostics_payload[dimension]
            )
            diagnostics[dimension] = require_score(value, f"diagnostics.{dimension}")
    scores = {
        dimension: require_score(raw_scores[dimension], f"scores.{dimension}")
        for dimension in HYPOTHESIS_SCORE_DIMENSIONS
    }
    return scores, diagnostics


__all__ = [
    "AUXILIARY_HYPOTHESIS_DIAGNOSTIC_DIMENSIONS",
    "HYPOTHESIS_SCORE_DIMENSIONS",
    "HYPOTHESIS_SCORE_RUBRIC_SHA256",
    "HYPOTHESIS_SCORE_RUBRIC_VERSION",
    "canonical_hypothesis_score_rubric",
    "hypothesis_score_rubric_sha256",
    "normalize_hypothesis_scores",
]
