"""Evidence readiness evaluator: evidence_relations."""

from __future__ import annotations

from typing import Any

from core.research.workflow.models import WorkflowNodeSpec

from .common import (
    CommonReadinessResult,
    DomainReadinessContext,
    DomainVerdict,
    RunSnapshot,
    blocker,
)


def evaluate_evidence_relations(
    *,
    run: RunSnapshot,
    node: WorkflowNodeSpec,
    common: CommonReadinessResult,
    context: DomainReadinessContext,
) -> DomainVerdict:
    blockers: list[Any] = []
    stats = context.evidence_cards_stats(run.team_id, run.run_id)
    if stats is None or int(stats.get("card_count") or 0) <= 0:
        blockers.append(
            blocker(
                "evidence_cards_missing",
                "证据卡片缺失",
                "Evidence Store 中没有已物化且可读的证据卡片",
            )
        )
    else:
        missing_fields = stats.get("missing_minimal_fields") or []
        if missing_fields:
            blockers.append(
                blocker(
                    "evidence_cards_incomplete",
                    "证据卡片字段不完整",
                    f"{len(missing_fields)} 张卡片缺少最小主张字段",
                )
            )
    return DomainVerdict(
        blockers=tuple(blockers),
        revision_vector=common.domain_revision_vector,
    )
