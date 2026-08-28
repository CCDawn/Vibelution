"""Experiment readiness evaluators: hypothesis_design through smoke_gate."""

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
    run_has_accepted_knowledge_package,
)


def evaluate_hypothesis_design(
    *,
    run: RunSnapshot,
    node: WorkflowNodeSpec,
    common: CommonReadinessResult,
    context: DomainReadinessContext,
) -> DomainVerdict:
    blockers: list[Any] = []
    # Knowledge gate: the node contract requires an ACCEPTED knowledge
    # package.  It is satisfied by an accepted in-graph handoff (2.1.0
    # chain) OR by a knowledge sideflow invocation absorbed into this run
    # (main flow 3.0.0 / hypothesis-first collection).  Without either, the
    # node stays blocked — no adapter dispatch is ever created against a
    # missing or rejected package.
    package_via_sideflow = run_has_accepted_knowledge_package(context, run)
    if not common.accepted_handoff_ids and not package_via_sideflow:
        blockers.append(
            blocker(
                "knowledge_handoff_not_accepted",
                "知识包交接未接受",
                "实验设计要求 accepted 的 Knowledge Package",
                category="evidence_insufficient",
                remediation_kind=RemediationKind.RESOLVE_HUMAN,
                remediation_label="等待知识包交接或发起知识搜集",
            )
        )
    package = context.knowledge_package(run.team_id, run.run_id)
    if not package_via_sideflow and (
        not isinstance(package, dict)
        or package.get("accepted") is not True
        or not list(package.get("knowledgeItems") or [])
    ):
        blockers.append(
            blocker(
                "knowledge_package_not_materialized",
                "知识包尚未形成正式产物",
                "人工接受必须绑定可回读的 Team Knowledge 产物",
            )
        )
    if hypothesis_first_run(context, run):
        state = hypothesis_first_chain_state(context, run)
        pending = int(state.get("pendingCollectionCount") or 0)
        if pending > 0:
            blockers.append(
                blocker(
                    "knowledge_gap_pending",
                    "知识缺口搜集中",
                    f"{pending} 个讨论决策触发的搜集请求尚未完成知识包交接",
                    category="evidence_insufficient",
                    remediation_kind=RemediationKind.RESOLVE_HUMAN,
                    remediation_label="等待子运行知识包交接",
                )
            )
        if not state.get("hypothesisConverged"):
            detail = str(state.get("convergenceDetail") or "") or "最近一轮假说评审未闭环或未被接受"
            if state.get("budgetExhausted"):
                detail = (
                    f"讨论轮次已达预算（{state.get('meetingCount') or 0}/"
                    f"{state.get('roundBudget') or 0}）且仍未收敛，必须人工决策"
                )
            blockers.append(
                blocker(
                    "hypothesis_round_unconverged",
                    "假说评审未收敛",
                    detail,
                    category="evidence_insufficient",
                    remediation_kind=RemediationKind.RESOLVE_HUMAN,
                    remediation_label="推进假说评审收敛",
                )
            )
        if not state.get("templateBaselineExists"):
            blockers.append(
                blocker(
                    "template_baseline_missing",
                    "模板基线缺失",
                    "实验设计要求该题作用域下存在 frozen 的模板基线；"
                    "请先通过 POST /teams/{team_id}/workflow-orchestration/template-baselines "
                    "为该题创建并冻结模板基线，再启动实验设计节点",
                    remediation_kind=RemediationKind.RESOLVE_HUMAN,
                    remediation_label="冻结模板基线",
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
