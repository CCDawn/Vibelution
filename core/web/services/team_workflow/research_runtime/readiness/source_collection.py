"""Source Collection readiness evaluators: source_finding / source_extraction."""

from __future__ import annotations

from typing import Any

from core.research.workflow.contracts.node_readiness import RemediationKind
from core.research.workflow.models import WorkflowNodeSpec

from .common import (
    CommonReadinessResult,
    DomainReadinessContext,
    DomainVerdict,
    RunSnapshot,
    blocker,
    hypothesis_first_chain_state,
    hypothesis_first_run,
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
    if hypothesis_first_run(context, run):
        state = hypothesis_first_chain_state(context, run)
        if not state.get("collectionReady"):
            open_ids = list(state.get("openMeetingIds") or [])
            first_meeting_id = str(state.get("firstMeetingId") or "")
            if open_ids:
                detail = (
                    f"首轮假说讨论 {open_ids[-1]} 尚未 closed；"
                    "首轮搜集范围只能来自讨论闭环后的搜集决策"
                )
            elif first_meeting_id:
                detail = (
                    f"首轮假说讨论 {first_meeting_id} 已 closed，但决策未携带有效 "
                    "searchEnvelope；首轮搜集范围只能来自讨论决策"
                )
            else:
                detail = "首轮假说讨论尚未开启；首轮搜集范围只能来自讨论决策"
            blockers.append(
                blocker(
                    "hypothesis_first_meeting_open",
                    "首轮假说讨论未闭环",
                    detail,
                    category="evidence_insufficient",
                    remediation_kind=RemediationKind.RESOLVE_HUMAN,
                    remediation_label="前往闭环首轮假说讨论",
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
