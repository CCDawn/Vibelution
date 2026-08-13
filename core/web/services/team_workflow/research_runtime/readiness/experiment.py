"""Experiment readiness evaluators: hypothesis_design through smoke_gate."""

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


def evaluate_hypothesis_design(
    *,
    run: RunSnapshot,
    node: WorkflowNodeSpec,
    common: CommonReadinessResult,
    context: DomainReadinessContext,
) -> DomainVerdict:
    blockers: list[Any] = []
    # The accepted Ledger handoff is the canonical gate decision.  Do not
    # require a second ``knowledge_package.accepted`` flag from a parallel
    # artifact store: the human-resolution command commits the handoff, and
    # common readiness already validates its accepted status.
    if not common.accepted_handoff_ids:
        blockers.append(
            blocker(
                "knowledge_handoff_not_accepted",
                "知识包交接未接受",
                "实验设计要求 accepted 的 Knowledge Package",
            )
        )
    return DomainVerdict(
        blockers=tuple(blockers),
        revision_vector=common.domain_revision_vector,
    )


def evaluate_protocol_design(
    *,
    run: RunSnapshot,
    node: WorkflowNodeSpec,
    common: CommonReadinessResult,
    context: DomainReadinessContext,
) -> DomainVerdict:
    blockers: list[Any] = []
    hypotheses = context.hypothesis_set(run.team_id, run.run_id)
    if hypotheses is None or int(hypotheses.get("hypothesis_count") or 0) <= 0:
        blockers.append(
            blocker(
                "hypothesis_contract_incomplete",
                "假设契约不完整",
                "没有可证伪的假设、变量或失败条件定义",
            )
        )
    return DomainVerdict(
        blockers=tuple(blockers),
        revision_vector=common.domain_revision_vector,
    )


def evaluate_protocol_review(
    *,
    run: RunSnapshot,
    node: WorkflowNodeSpec,
    common: CommonReadinessResult,
    context: DomainReadinessContext,
) -> DomainVerdict:
    blockers: list[Any] = []
    draft = context.protocol_draft(run.team_id, run.run_id)
    missing: list[str] = []
    if draft is None:
        missing = ["protocol_draft"]
    else:
        for key in ("dataset", "baseline", "metric", "seed", "budget", "stop_condition"):
            if not draft.get(key):
                missing.append(key)
    if missing:
        blockers.append(
            blocker(
                "protocol_draft_incomplete",
                "协议草稿不完整",
                "缺少: " + ", ".join(missing),
            )
        )
    return DomainVerdict(
        blockers=tuple(blockers),
        revision_vector=common.domain_revision_vector,
    )


def evaluate_protocol_freeze(
    *,
    run: RunSnapshot,
    node: WorkflowNodeSpec,
    common: CommonReadinessResult,
    context: DomainReadinessContext,
) -> DomainVerdict:
    blockers: list[Any] = []
    review = context.protocol_review(run.team_id, run.run_id)
    if review is None:
        blockers.append(
            blocker(
                "protocol_review_blocked",
                "协议评审未通过",
                "协议评审报告缺失",
            )
        )
    else:
        blocking_issues = int(review.get("blocking_issue_count") or 0)
        waiver_issue = review.get("open_waivers") or 0
        if blocking_issues > 0:
            blockers.append(
                blocker(
                    "protocol_review_blocked",
                    "协议评审未通过",
                    f"仍有 {blocking_issues} 个阻塞问题未解决",
                )
            )
        if int(waiver_issue) > 0:
            blockers.append(
                blocker(
                    "protocol_review_blocked",
                    "协议评审未通过",
                    f"仍有 {waiver_issue} 个无操作者/理由的 waiver",
                )
            )
    return DomainVerdict(
        blockers=tuple(blockers),
        revision_vector=common.domain_revision_vector,
    )


def evaluate_smoke_gate(
    *,
    run: RunSnapshot,
    node: WorkflowNodeSpec,
    common: CommonReadinessResult,
    context: DomainReadinessContext,
) -> DomainVerdict:
    blockers: list[Any] = []
    frozen = context.frozen_protocol(run.team_id, run.run_id)
    if frozen is None:
        blockers.append(
            blocker(
                "frozen_protocol_missing",
                "协议未冻结",
                "Smoke 门要求 frozen protocol",
            )
        )
    return DomainVerdict(
        blockers=tuple(blockers),
        revision_vector=common.domain_revision_vector,
    )
