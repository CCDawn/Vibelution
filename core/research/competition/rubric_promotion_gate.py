# -*- coding: utf-8 -*-
"""Rubric shadow→active 晋升门的纯计算层（frozen thresholds v1）。

评估器版本化的治理闸门：一个 shadow rubric 只有在「人工锚定的一致性
证据 + 假自动批准上界」同时受控时才允许晋升为 active。阈值直接复用
G12 校准门（决策 #13）的冻结常量，不另造口径：

- Cohen's kappa ≥ ``KAPPA_ACCEPTABLE_THRESHOLD``（0.6，可接受档）；
- 假自动批准率单侧上界（Beta-Binomial，保守方法）≤
  ``DEFAULT_MAX_FALSE_AUTO_APPROVE_UPPER_BOUND``（0.05）；
- 人工锚定配对数 ≥ ``min_anchored_pairs``（默认 3）——同模型族的 agent
  审批存在相关性误差，无人工锚点一律不放行。

v1 证据范围（已知限制，显式声明）：judge-quality 面板是全局口径，尚未
按 rubric 谱系归因；结果携带 ``evidenceScope="global_panel_v1"``，下游
消费方必须知晓。任何证据缺失一律 fail-closed（not eligible + 明细）。

No I/O, no state, no network; deterministic.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .calibration_stats import (
    DEFAULT_MAX_FALSE_AUTO_APPROVE_UPPER_BOUND,
    KAPPA_ACCEPTABLE_THRESHOLD,
)

DEFAULT_MIN_ANCHORED_PAIRS = 3
_CONSERVATIVE_BOUND_METHOD = "beta_binomial"
_EVIDENCE_SCOPE = "global_panel_v1"


def _safe_int(value: Any) -> int:
    """Evidence counters coerce malformed values to 0 (fail-closed), never raise."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return 0


def _safe_float(value: Any) -> float | None:
    """Numeric evidence must be a real number; bool counts as missing."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


@dataclass(frozen=True, slots=True)
class GateCheck:
    check_id: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class RubricPromotionGateResult:
    eligible: bool
    candidate_version_id: str
    candidate_rubric_hash: str
    candidate_source: str
    checks: tuple[GateCheck, ...] = field(default_factory=tuple)
    evidence: dict[str, Any] = field(default_factory=dict)
    evidence_scope: str = _EVIDENCE_SCOPE

    def as_dict(self) -> dict[str, Any]:
        return {
            "eligible": self.eligible,
            "candidateVersionId": self.candidate_version_id,
            "candidateRubricHash": self.candidate_rubric_hash,
            "candidateSource": self.candidate_source,
            "checks": [
                {"checkId": c.check_id, "passed": c.passed, "detail": c.detail}
                for c in self.checks
            ],
            "evidence": self.evidence,
            "evidenceScope": self.evidence_scope,
        }


def _latest_by_status(versions: Sequence[Mapping[str, Any]], status: str) -> Mapping[str, Any] | None:
    for record in reversed(list(versions)):
        if str(record.get("status") or "") == status:
            return record
    return None


def _select_candidate(versions: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    active = _latest_by_status(versions, "active")
    active_hash = str((active or {}).get("rubricHash") or "")
    for record in reversed(list(versions)):
        if str(record.get("status") or "") != "shadow":
            continue
        if active and str(record.get("rubricHash") or "") == active_hash:
            continue
        return record
    return None


def evaluate_rubric_promotion_gate(
    panel: Mapping[str, Any],
    versions: Sequence[Mapping[str, Any]],
    *,
    min_anchored_pairs: int = DEFAULT_MIN_ANCHORED_PAIRS,
) -> RubricPromotionGateResult:
    """Evaluate whether the newest distinct shadow rubric may be promoted."""
    if not isinstance(panel, Mapping):
        panel = {}
    candidate = _select_candidate(versions)

    anchored_pairs = _safe_int(panel.get("anchoredPairs"))
    anchored_kappa_payload = panel.get("anchoredKappa")
    anchored_kappa_payload = (
        anchored_kappa_payload if isinstance(anchored_kappa_payload, Mapping) else {}
    )
    kappa_defined = bool(anchored_kappa_payload.get("defined"))
    kappa_value = _safe_float(anchored_kappa_payload.get("kappa"))
    bounds = panel.get("falseAutoApproveUpperBounds")
    bounds = bounds if isinstance(bounds, Mapping) else {}
    trials_auto_approved = _safe_int(bounds.get("trialsAutoApproved"))
    bound_value = _safe_float(bounds.get(_CONSERVATIVE_BOUND_METHOD))

    checks: list[GateCheck] = []

    checks.append(
        GateCheck(
            check_id="shadow_candidate_exists",
            passed=candidate is not None,
            detail=(
                f"candidate {candidate.get('rubricVersionId')}"
                if candidate is not None
                else "no distinct shadow version pending promotion"
            ),
        )
    )
    checks.append(
        GateCheck(
            check_id="anchored_evidence_sufficient",
            passed=anchored_pairs >= min_anchored_pairs,
            detail=f"anchored pairs {anchored_pairs} / required {min_anchored_pairs}",
        )
    )
    kappa_passed = bool(
        kappa_defined
        and kappa_value is not None
        and kappa_value >= KAPPA_ACCEPTABLE_THRESHOLD
    )
    checks.append(
        GateCheck(
            check_id="anchored_kappa_acceptable",
            passed=kappa_passed,
            detail=(
                f"anchored kappa {kappa_value} >= {KAPPA_ACCEPTABLE_THRESHOLD}"
                if kappa_passed
                else f"anchored kappa {kappa_value!r} (defined={kappa_defined}) "
                f"below {KAPPA_ACCEPTABLE_THRESHOLD}"
            ),
        )
    )
    bound_passed = bool(
        trials_auto_approved >= 1
        and bound_value is not None
        and bound_value <= DEFAULT_MAX_FALSE_AUTO_APPROVE_UPPER_BOUND
    )
    checks.append(
        GateCheck(
            check_id="false_auto_approve_bounded",
            passed=bound_passed,
            detail=(
                f"{_CONSERVATIVE_BOUND_METHOD} upper bound {bound_value} <= "
                f"{DEFAULT_MAX_FALSE_AUTO_APPROVE_UPPER_BOUND} over "
                f"{trials_auto_approved} auto-approved trials"
                if bound_passed
                else f"bound {bound_value!r} over {trials_auto_approved} trials "
                f"not controlled at {DEFAULT_MAX_FALSE_AUTO_APPROVE_UPPER_BOUND}"
            ),
        )
    )

    eligible = all(check.passed for check in checks)
    return RubricPromotionGateResult(
        eligible=eligible,
        candidate_version_id=str((candidate or {}).get("rubricVersionId") or ""),
        candidate_rubric_hash=str((candidate or {}).get("rubricHash") or ""),
        candidate_source=str((candidate or {}).get("source") or ""),
        checks=tuple(checks),
        evidence={
            "anchoredPairs": anchored_pairs,
            "anchoredKappa": dict(anchored_kappa_payload),
            "falseAutoApproveUpperBounds": dict(bounds),
            "topLevelSampleSource": str(panel.get("topLevelSampleSource") or ""),
            "totalRuns": int(panel.get("totalRuns") or 0),
        },
    )


__all__ = [
    "DEFAULT_MIN_ANCHORED_PAIRS",
    "GateCheck",
    "RubricPromotionGateResult",
    "evaluate_rubric_promotion_gate",
]
