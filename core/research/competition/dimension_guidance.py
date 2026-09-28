# -*- coding: utf-8 -*-
"""维度加权引导的纯计算层（dimension guidance）。

把「评审批评 → 修订」的维度异质性统计（``reviewer_diagnostic_reward`` 的
by_dimension 聚合）转成可消费的改进引导载荷：哪些维度应重点强化
（emphasize）、哪些维度修订时须防退化（caution，历史修订净负）。真实
数据锚点：修订循环对 competitionFit 平均 +0.1175，对 falsifiability/
novelty 净负 −0.0175——「照单全收改进意见」会系统性牺牲部分维度。

No I/O, no state, no network; every function is deterministic.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

GUIDANCE_EMPHASIZE = "emphasize"
GUIDANCE_CAUTION = "caution"
GUIDANCE_NEUTRAL = "neutral"
GUIDANCE_INSUFFICIENT = "insufficient"


def _number(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or isinstance(value, bool):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any) -> int:
    return int(_number(value, default=0.0))


@dataclass(frozen=True, slots=True)
class DimensionGuidance:
    dimension: str
    sample_count: int
    mean_delta: float
    improved_count: int
    harmed_count: int
    guidance: str


@dataclass(frozen=True, slots=True)
class DimensionGuidanceReport:
    min_samples: int
    generated_from: int
    dimensions: tuple[DimensionGuidance, ...]
    guidance_hint: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "minSamples": self.min_samples,
            "generatedFrom": self.generated_from,
            "dimensions": [
                {
                    "dimension": item.dimension,
                    "sampleCount": item.sample_count,
                    "meanDelta": item.mean_delta,
                    "improvedCount": item.improved_count,
                    "harmedCount": item.harmed_count,
                    "guidance": item.guidance,
                }
                for item in self.dimensions
            ],
            "guidanceHint": self.guidance_hint,
        }


def _classify(
    *,
    sample_count: int,
    mean_delta: float,
    improved: int,
    harmed: int,
    min_samples: int,
) -> str:
    if sample_count < min_samples:
        return GUIDANCE_INSUFFICIENT
    if mean_delta > 0 and improved > harmed:
        return GUIDANCE_EMPHASIZE
    if mean_delta < 0 and harmed > 0:
        return GUIDANCE_CAUTION
    return GUIDANCE_NEUTRAL


def _build_hint(dimensions: tuple[DimensionGuidance, ...]) -> str:
    emphasize = sorted(
        item.dimension for item in dimensions if item.guidance == GUIDANCE_EMPHASIZE
    )
    caution = sorted(
        item.dimension for item in dimensions if item.guidance == GUIDANCE_CAUTION
    )
    parts: list[str] = []
    if emphasize:
        parts.append("重点强化 " + "、".join(emphasize))
    if caution:
        parts.append("谨慎处理 " + "、".join(caution) + "（历史修订平均净负，防止退化）")
    if not parts:
        return "修订指引：各维度历史修订收益中性或样本不足，按评审意见常规处理。"
    return "修订指引：" + "；".join(parts) + "。"


def build_dimension_guidance(
    by_dimension: Mapping[str, Mapping[str, Any]],
    *,
    min_samples: int = 3,
) -> DimensionGuidanceReport:
    """Translate per-dimension diagnostic stats into guidance signals.

    输入键为维度名（缺名/非映射项跳过），值携带 critique_count /
    improved_count / harmed_count / mean_delta（缺字段按 0 容错）。输出按
    维度名字典序排列，保证确定性。
    """
    items: list[DimensionGuidance] = []
    for raw_dimension, raw_stats in by_dimension.items():
        dimension = str(raw_dimension or "").strip()
        if not dimension or not isinstance(raw_stats, Mapping):
            continue
        sample_count = _int(raw_stats.get("critique_count"))
        improved = _int(raw_stats.get("improved_count"))
        harmed = _int(raw_stats.get("harmed_count"))
        mean_delta = _number(raw_stats.get("mean_delta"))
        items.append(
            DimensionGuidance(
                dimension=dimension,
                sample_count=sample_count,
                mean_delta=mean_delta,
                improved_count=improved,
                harmed_count=harmed,
                guidance=_classify(
                    sample_count=sample_count,
                    mean_delta=mean_delta,
                    improved=improved,
                    harmed=harmed,
                    min_samples=min_samples,
                ),
            )
        )
    items.sort(key=lambda item: item.dimension)
    dimensions = tuple(items)
    return DimensionGuidanceReport(
        min_samples=min_samples,
        generated_from=sum(item.sample_count for item in dimensions),
        dimensions=dimensions,
        guidance_hint=_build_hint(dimensions),
    )


__all__ = [
    "DimensionGuidance",
    "DimensionGuidanceReport",
    "GUIDANCE_CAUTION",
    "GUIDANCE_EMPHASIZE",
    "GUIDANCE_INSUFFICIENT",
    "GUIDANCE_NEUTRAL",
    "build_dimension_guidance",
]
