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
                    f"假说评审 {open_ids[-1]} 尚未闭环；"
                    "首轮搜集范围只能来自评审闭环时的搜集决策"
                )
                title = "假说评审尚未闭环"
                remediation_label = "前往确认并结束当前评审轮"
            elif first_meeting_id:
                detail = (
                    f"假说评审已全部闭环，但没有任何一轮决策携带资料缺口请求；"
                    "首轮搜集范围只能来自评审的证据请求决策"
                )
                title = "评审缺少资料缺口请求"
                remediation_label = "再开一轮评审，让团队提出资料缺口（证据请求）"
            else:
                detail = "假说评审尚未开启；首轮搜集范围只能来自评审的证据请求决策"
                title = "假说评审尚未开启"
                remediation_label = "开启首轮假说评审"
            blockers.append(
                blocker(
                    "hypothesis_first_meeting_open",
                    title,
                    detail,
                    category="evidence_insufficient",
                    remediation_kind=RemediationKind.RESOLVE_HUMAN,
                    remediation_label=remediation_label,
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
