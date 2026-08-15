"""Iteration readiness evaluators: controlled_run through result_package."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.research.workflow.models import WorkflowNodeSpec

from .common import (
    CommonReadinessResult,
    DomainReadinessContext,
    DomainVerdict,
    RunSnapshot,
    blocker,
    is_bounded_controlled_run,
)

_PACKAGE_START_DECISIONS = frozenset({"stop", "rollback_candidate", "rollback"})


def _governance_kind(governance: Mapping[str, Any] | None) -> str:
    if not isinstance(governance, Mapping):
        return ""
    return str(
        governance.get("decision_kind")
        or governance.get("operation")
        or governance.get("kind")
        or ""
    ).strip()


def _governance_terminal_reason(governance: Mapping[str, Any] | None) -> str:
    if not isinstance(governance, Mapping):
        return ""
    return str(
        governance.get("terminalReason")
        or governance.get("terminal_reason")
        or governance.get("reason")
        or ""
    ).strip()


def _result_package_is_complete(package: Mapping[str, Any] | None) -> bool:
    if not isinstance(package, Mapping):
        return False
    return bool(
        package.get("required_artifacts")
        and int(package.get("pending_human_tasks") or 0) == 0
        and str(package.get("terminal_reason") or "").strip()
    )


def evaluate_controlled_run(
    *,
    run: RunSnapshot,
    node: WorkflowNodeSpec,
    common: CommonReadinessResult,
    context: DomainReadinessContext,
) -> DomainVerdict:
    blockers: list[Any] = []
    smoke = context.smoke_evidence(run.team_id, run.run_id)
    frozen = context.frozen_protocol(run.team_id, run.run_id)
    if smoke is None or not smoke.get("released"):
        blockers.append(
            blocker(
                "formal_run_not_released",
                "Smoke 未放行",
                "受控运行要求 accepted smoke release",
            )
        )
    if frozen is None:
        blockers.append(
            blocker(
                "formal_run_not_released",
                "协议未冻结",
                "受控运行要求同一 frozen protocol",
            )
        )
    return DomainVerdict(
        blockers=tuple(blockers),
        revision_vector=common.domain_revision_vector,
    )


def evaluate_result_evaluation(
    *,
    run: RunSnapshot,
    node: WorkflowNodeSpec,
    common: CommonReadinessResult,
    context: DomainReadinessContext,
) -> DomainVerdict:
    blockers: list[Any] = []
    run_state = context.controlled_run(run.team_id, run.run_id)
    if run_state is None:
        blockers.append(
            blocker(
                "run_artifacts_incomplete",
                "运行产物不完整",
                "没有已终止的受控运行",
            )
        )
    elif not run_state.get("terminal"):
        blockers.append(
            blocker(
                "run_artifacts_incomplete",
                "运行产物不完整",
                "受控运行尚未终止",
            )
        )
    else:
        missing = [
            key
            for key in ("logs", "metrics", "artifact_hash")
            if not run_state.get(key)
        ]
        if missing and not is_bounded_controlled_run(run_state):
            blockers.append(
                blocker(
                    "run_artifacts_incomplete",
                    "运行产物不完整",
                    "缺少: " + ", ".join(missing),
                )
            )
    return DomainVerdict(
        blockers=tuple(blockers),
        revision_vector=common.domain_revision_vector,
    )


def evaluate_iteration_decision(
    *,
    run: RunSnapshot,
    node: WorkflowNodeSpec,
    common: CommonReadinessResult,
    context: DomainReadinessContext,
) -> DomainVerdict:
    blockers: list[Any] = []
    report = context.evaluation_report(run.team_id, run.run_id)
    if report is None:
        blockers.append(
            blocker(
                "evaluation_incomplete",
                "评价不完整",
                "缺少 baseline 对比、失败分析或置信边界",
            )
        )
    else:
        missing = [
            key
            for key in ("baseline_comparison", "failure_analysis", "confidence_bounds")
            if not report.get(key)
        ]
        if missing:
            blockers.append(
                blocker(
                    "evaluation_incomplete",
                    "评价不完整",
                    "缺少: " + ", ".join(missing),
                )
            )
    return DomainVerdict(
        blockers=tuple(blockers),
        revision_vector=common.domain_revision_vector,
    )


def evaluate_version_governance(
    *,
    run: RunSnapshot,
    node: WorkflowNodeSpec,
    common: CommonReadinessResult,
    context: DomainReadinessContext,
) -> DomainVerdict:
    blockers: list[Any] = []
    decision = context.iteration_decision(run.team_id, run.run_id)
    if decision is None or not decision.get("kind"):
        blockers.append(
            blocker(
                "version_lineage_invalid",
                "迭代决策缺失",
                "版本治理要求结构化 iteration decision",
            )
        )
    else:
        for key in ("target_version", "lineage", "reason"):
            if not decision.get(key):
                blockers.append(
                    blocker(
                        "version_lineage_invalid",
                        "版本谱系无效",
                        f"迭代决策缺少 {key}",
                    )
                )
                break
    return DomainVerdict(
        blockers=tuple(blockers),
        revision_vector=common.domain_revision_vector,
    )


def evaluate_candidate_promotion(
    *,
    run: RunSnapshot,
    node: WorkflowNodeSpec,
    common: CommonReadinessResult,
    context: DomainReadinessContext,
) -> DomainVerdict:
    blockers: list[Any] = []
    governance = context.version_governance(run.team_id, run.run_id)
    if governance is None or governance.get("decision_kind") != "promote_candidate":
        blockers.append(
            blocker(
                "promotion_proposal_invalid",
                "晋升提案无效",
                "candidate_promotion 仅接受 promote 的治理记录",
            )
        )
    else:
        for key in ("candidate_hash", "proposal"):
            if not governance.get(key):
                blockers.append(
                    blocker(
                        "promotion_proposal_invalid",
                        "晋升提案无效",
                        f"治理记录缺少 {key}",
                    )
                )
                break
    return DomainVerdict(
        blockers=tuple(blockers),
        revision_vector=common.domain_revision_vector,
    )


def evaluate_result_package(
    *,
    run: RunSnapshot,
    node: WorkflowNodeSpec,
    common: CommonReadinessResult,
    context: DomainReadinessContext,
) -> DomainVerdict:
    """Start gate for packaging — do not require the output package to exist.

    ``result_package`` is the SYSTEM node that *writes* ``research_result_package``.
    Requiring that artifact here deadlocks auto-advance after STOP governance.
    """
    blockers: list[Any] = []
    package = context.result_package(run.team_id, run.run_id)
    if _result_package_is_complete(package):
        return DomainVerdict(
            blockers=(),
            revision_vector=common.domain_revision_vector,
        )
    governance = context.version_governance(run.team_id, run.run_id)
    kind = _governance_kind(governance)
    terminal = _governance_terminal_reason(governance)
    if kind in _PACKAGE_START_DECISIONS and terminal:
        return DomainVerdict(
            blockers=(),
            revision_vector=common.domain_revision_vector,
        )
    if package is None:
        blockers.append(
            blocker(
                "result_package_incomplete",
                "结果包不完整",
                "缺少 STOP/rollback 治理记录，或必需 artifact 未齐备、存在未决 HumanTask、终止原因不明",
            )
        )
    else:
        if not package.get("required_artifacts"):
            blockers.append(
                blocker(
                    "result_package_incomplete",
                    "结果包不完整",
                    "必需 artifact 未齐备",
                )
            )
        elif int(package.get("pending_human_tasks") or 0) > 0:
            blockers.append(
                blocker(
                    "result_package_incomplete",
                    "结果包不完整",
                    "存在未决 HumanTask",
                )
            )
        elif not package.get("terminal_reason"):
            blockers.append(
                blocker(
                    "result_package_incomplete",
                    "结果包不完整",
                    "终止原因不明",
                )
            )
    return DomainVerdict(
        blockers=tuple(blockers),
        revision_vector=common.domain_revision_vector,
    )
