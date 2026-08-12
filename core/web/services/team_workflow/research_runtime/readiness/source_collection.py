"""Source Collection readiness evaluators: source_finding / source_extraction."""

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


def evaluate_source_finding(
    *,
    run: RunSnapshot,
    node: WorkflowNodeSpec,
    common: CommonReadinessResult,
    context: DomainReadinessContext,
) -> DomainVerdict:
    blockers: list[Any] = []
    snapshot = context.question_snapshot(
        run.team_id, run.question_id, run_id=run.run_id
    )
    if snapshot is None:
        blockers.append(
            blocker(
                "question_snapshot_missing",
                "题目快照缺失",
                "题目权威存储中没有可用的冻结题目快照",
                remediation_kind=None,
            )
        )
    return DomainVerdict(
        blockers=tuple(blockers),
        revision_vector=common.domain_revision_vector,
    )


def evaluate_source_extraction(
    *,
    run: RunSnapshot,
    node: WorkflowNodeSpec,
    common: CommonReadinessResult,
    context: DomainReadinessContext,
) -> DomainVerdict:
    blockers: list[Any] = []
    stats = context.candidate_stats(run.team_id, run.run_id)
    if stats is None:
        blockers.append(
            blocker(
                "source_candidates_missing",
                "没有可提炼的资料",
                "资料权威存储中没有属于当前运行的候选资料",
                remediation_kind=None,
            )
        )
    elif int(stats.get("record_count") or 0) <= 0:
        blockers.append(
            blocker(
                "source_candidates_missing",
                "没有可提炼的资料",
                "资料权威存储中没有属于当前运行的候选资料",
                remediation_kind=None,
            )
        )
    return DomainVerdict(
        blockers=tuple(blockers),
        revision_vector=common.domain_revision_vector,
    )
