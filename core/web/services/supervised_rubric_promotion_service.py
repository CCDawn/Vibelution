# -*- coding: utf-8 -*-
"""Rubric promotion gate service (evaluate + gated promote)."""

from __future__ import annotations

from typing import Any

from core.research.competition.rubric_promotion_gate import (
    RubricPromotionGateResult,
    evaluate_rubric_promotion_gate,
)
from core.web.services.supervised_rubric_version_store import (
    RubricVersionStoreError,
    list_rubric_versions,
    promote_rubric_version,
)
from core.web.services.supervised_judge_quality_service import (
    build_supervised_judge_quality_report,
)


class RubricPromotionBlockedError(ValueError):
    """Raised when a promote was requested while the gate is not passed."""


def evaluate_rubric_promotion() -> dict[str, Any]:
    """Read-only: evaluate the shadow→active promotion gate over live data."""
    panel = build_supervised_judge_quality_report(limit=200)
    versions = list_rubric_versions(limit=500)
    result = evaluate_rubric_promotion_gate(panel, versions)
    return {
        "schemaVersion": 1,
        **result.as_dict(),
    }


def promote_rubric_if_eligible() -> dict[str, Any]:
    """Promote the pending shadow rubric; the gate must pass first.

    门内强制：评估未通过时抛 :class:`RubricPromotionBlockedError`（带全部
    check 明细），绝不放行；晋升证据即门评估的证据快照。
    """
    evaluation = evaluate_rubric_promotion()
    if not evaluation.get("eligible"):
        raise RubricPromotionBlockedError(
            "rubric promotion gate not passed: "
            + "; ".join(
                f"{check.get('checkId')}={check.get('detail')}"
                for check in evaluation.get("checks") or []
                if not check.get("passed")
            )
        )
    promoted = promote_rubric_version(
        str(evaluation.get("candidateVersionId") or ""),
        evidence={
            "gate": "rubric_promotion_v1",
            "evidenceScope": evaluation.get("evidenceScope"),
            **{k: v for k, v in dict(evaluation.get("evidence") or {}).items()},
        },
    )
    return {"schemaVersion": 1, "promoted": promoted}


__all__ = [
    "RubricPromotionBlockedError",
    "RubricVersionStoreError",
    "evaluate_rubric_promotion",
    "promote_rubric_if_eligible",
]
