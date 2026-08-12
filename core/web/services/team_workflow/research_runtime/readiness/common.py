"""Common readiness prerequisites and the read-only domain context protocol.

Every evaluator runs the same ten common checks first (spec 9.1). This module
never writes; all domain reads go through ``DomainReadinessContext`` so tests
can fake authorities and T5 wires the live adapters.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from core.research.workflow.contracts import (
    ActorReadiness,
    BudgetReadiness,
    ReadinessBlocker,
)
from core.research.workflow.contracts.node_readiness import Remediation, RemediationKind
from core.research.workflow.models import ActorKind, WorkflowNodeSpec

TERMINAL_RUN_STATUSES = frozenset({"succeeded", "failed", "cancelled", "archived"})

ACTIVE_ATTEMPT_STATUSES = frozenset({"starting", "dispatching", "running", "waiting_human"})


@dataclass(frozen=True, slots=True)
class RunSnapshot:
    run_id: str
    team_id: str
    workflow_id: str
    workflow_version_id: str
    project_id: str
    question_id: str
    status: str
    run_version: int
    input_snapshot_hash: str


@dataclass(frozen=True, slots=True)
class BudgetLimitsSnapshot:
    policy_hash: str
    stage_tokens_limit: int = 250_000
    stage_tokens_consumed: int = 0
    max_tool_calls: int = 300
    tool_calls_consumed: int = 0
    max_seconds: int = 21_600
    seconds_consumed: int = 0
    auto_retries: int = 2
    retries_consumed: int = 0
    estimated_next_attempt_tokens: int = 0

    def available(self) -> tuple[bool, str]:
        if self.tool_calls_consumed + 1 > self.max_tool_calls:
            return False, "tool_calls_limit_reached"
        if self.seconds_consumed + 60 > self.max_seconds:
            return False, "time_limit_reached"
        if self.stage_tokens_consumed + self.estimated_next_attempt_tokens > self.stage_tokens_limit:
            return False, "stage_tokens_limit_reached"
        return True, ""


@dataclass(frozen=True, slots=True)
class HandoffSnapshot:
    handoff_id: str
    from_node_run_id: str
    status: str


@dataclass(frozen=True, slots=True)
class CommonReadinessResult:
    blockers: tuple[ReadinessBlocker, ...]
    actor: ActorReadiness
    budget: BudgetReadiness
    domain_revision_vector: Mapping[str, str]
    accepted_handoff_ids: tuple[str, ...]
    input_artifact_refs: tuple[Any, ...]

    @property
    def ready(self) -> bool:
        return not self.blockers


@dataclass(frozen=True, slots=True)
class DomainVerdict:
    blockers: tuple[ReadinessBlocker, ...] = ()
    revision_vector: Mapping[str, str] = field(default_factory=dict)
    input_artifact_refs: tuple[Any, ...] = ()

    @property
    def ready(self) -> bool:
        return not self.blockers


class DomainReadinessContext(Protocol):
    """Read-only window into domain authorities; no write methods exist."""

    def domain_revision_vector(self, team_id: str, run_id: str) -> Mapping[str, str]: ...

    def question_snapshot(
        self, team_id: str, question_id: str, *, run_id: str | None = None
    ) -> Mapping[str, Any] | None: ...

    def candidate_stats(self, team_id: str, run_id: str) -> Mapping[str, Any] | None: ...

    def evidence_cards_stats(self, team_id: str, run_id: str) -> Mapping[str, Any] | None: ...

    def evidence_graph_stats(self, team_id: str, run_id: str) -> Mapping[str, Any] | None: ...

    def knowledge_package_draft(self, team_id: str, run_id: str) -> Mapping[str, Any] | None: ...

    def knowledge_package(self, team_id: str, run_id: str) -> Mapping[str, Any] | None: ...

    def hypothesis_set(self, team_id: str, run_id: str) -> Mapping[str, Any] | None: ...

    def protocol_draft(self, team_id: str, run_id: str) -> Mapping[str, Any] | None: ...

    def protocol_review(self, team_id: str, run_id: str) -> Mapping[str, Any] | None: ...

    def frozen_protocol(self, team_id: str, run_id: str) -> Mapping[str, Any] | None: ...

    def smoke_evidence(self, team_id: str, run_id: str) -> Mapping[str, Any] | None: ...

    def controlled_run(self, team_id: str, run_id: str) -> Mapping[str, Any] | None: ...

    def evaluation_report(self, team_id: str, run_id: str) -> Mapping[str, Any] | None: ...

    def iteration_decision(self, team_id: str, run_id: str) -> Mapping[str, Any] | None: ...

    def version_governance(self, team_id: str, run_id: str) -> Mapping[str, Any] | None: ...

    def promotion_proposal(self, team_id: str, run_id: str) -> Mapping[str, Any] | None: ...

    def result_package(self, team_id: str, run_id: str) -> Mapping[str, Any] | None: ...

    def budget_limits(self, team_id: str, run_id: str) -> BudgetLimitsSnapshot: ...

    def binding_snapshot(self, run_id: str, node_id: str) -> Mapping[str, Any] | None: ...

    def agent_resolvable(self, agent_id: str) -> bool: ...

    def recovery_blocker_codes(self, run_id: str) -> Sequence[str]: ...

    def adapter_registered(self, node_id: str) -> bool: ...

    def incoming_handoffs(self, run_id: str, node_id: str) -> Sequence[HandoffSnapshot]: ...


def blocker(
    code: str,
    title: str,
    detail: str,
    *,
    category: str = "dependency",
    remediation_kind: RemediationKind | None = None,
    remediation_label: str = "",
    target_node_id: str | None = None,
    target_run_id: str | None = None,
) -> ReadinessBlocker:
    remediation = None
    if remediation_kind:
        remediation = Remediation(
            kind=remediation_kind,
            label=remediation_label or title,
            target_node_id=target_node_id,
            target_run_id=target_run_id,
        )
    return ReadinessBlocker(
        code=code,
        title=title,
        detail=detail,
        category=category,
        remediation=remediation,
    )


def evaluate_common(
    *,
    run: RunSnapshot,
    node: WorkflowNodeSpec,
    requested_team_id: str,
    definition_node_ids: set[str],
    live_attempt_count: int,
    context: DomainReadinessContext,
) -> CommonReadinessResult:
    blockers: list[ReadinessBlocker] = []

    if requested_team_id != run.team_id:
        blockers.append(
            blocker(
                "team_scope_mismatch",
                "团队作用域不一致",
                f"请求 teamId={requested_team_id}，Run 属于 {run.team_id}",
                category="scope",
            )
        )
    if run.status in TERMINAL_RUN_STATUSES:
        blockers.append(
            blocker(
                "run_terminal",
                "运行已结束",
                f"Run 状态为 {run.status}，不能开始新节点",
                category="state",
            )
        )
    elif run.status == "reconciliation_required":
        blockers.append(
            blocker(
                "run_reconciliation_required",
                "需要人工对账",
                "Run 处于 reconciliation_required，先执行 reconcile_run",
                category="state",
                remediation_kind=RemediationKind.VIEW_DIAGNOSTICS,
                remediation_label="查看对账诊断",
            )
        )
    if node.nodeId not in definition_node_ids:
        blockers.append(
            blocker("unknown_node", "未知节点", f"{node.nodeId} 不属于冻结的工作流定义", category="state")
        )
    if live_attempt_count > 0:
        blockers.append(
            blocker(
                "node_live_attempt",
                "节点已有进行中的尝试",
                "同一节点存在 starting/dispatching/running 的 attempt",
                category="state",
            )
        )
    for handoff in context.incoming_handoffs(run.run_id, node.nodeId):
        if handoff.status != "accepted":
            blockers.append(
                blocker(
                    "handoff_not_accepted",
                    "上游交接未接受",
                    f"Handoff {handoff.handoff_id} 状态为 {handoff.status}",
                    category="handoff",
                )
            )
            break

    accepted_handoff_ids = tuple(
        handoff.handoff_id
        for handoff in context.incoming_handoffs(run.run_id, node.nodeId)
        if handoff.status == "accepted"
    )

    actor = _evaluate_actor(run, node, context)
    if (not actor.configured or not actor.resolvable) and node.actorKind == ActorKind.AGENT:
        blockers.append(
            blocker(
                "agent_not_configured",
                "Agent 未配置",
                "Run binding snapshot 缺少可解析的 Agent",
                category="actor",
                remediation_kind=RemediationKind.REBIND_AGENT,
                remediation_label="配置 Agent",
            )
        )

    budget_limits = context.budget_limits(run.team_id, run.run_id)
    budget_available, budget_reason = budget_limits.available()
    budget = BudgetReadiness(
        policy_hash=budget_limits.policy_hash,
        available=budget_available,
        reason=budget_reason or "ok",
        estimated_tokens=budget_limits.estimated_next_attempt_tokens,
    )
    if not budget_available:
        blockers.append(
            blocker(
                "budget_safety_limit_reached",
                "预算安全上限",
                f"预算无法容纳一次新尝试（{budget_reason}）",
                category="budget",
            )
        )

    try:
        revision_vector = dict(context.domain_revision_vector(run.team_id, run.run_id))
    except Exception:
        revision_vector = {}
        blockers.append(
            blocker(
                "domain_revision_unreadable",
                "领域版本向量不可读",
                "领域权威存储无法提供 revision vector",
                category="domain",
            )
        )

    if not context.adapter_registered(node.nodeId):
        blockers.append(
            blocker(
                "adapter_not_registered",
                "执行器未注册",
                f"节点 {node.nodeId} 没有注册的 adapter",
                category="adapter",
            )
        )

    for recovery_code in context.recovery_blocker_codes(run.run_id):
        blockers.append(
            blocker(
                "recovery_blocked",
                "存在未解决的恢复记录",
                f"未解决 recovery record: {recovery_code}",
                category="recovery",
            )
        )

    return CommonReadinessResult(
        blockers=tuple(blockers),
        actor=actor,
        budget=budget,
        domain_revision_vector=revision_vector,
        accepted_handoff_ids=accepted_handoff_ids,
        input_artifact_refs=(),
    )


def _evaluate_actor(
    run: RunSnapshot,
    node: WorkflowNodeSpec,
    context: DomainReadinessContext,
) -> ActorReadiness:
    if node.actorKind == ActorKind.HUMAN:
        return ActorReadiness(configured=True, resolvable=True, binding_snapshot_id=None)
    if node.actorKind == ActorKind.SYSTEM:
        return ActorReadiness(configured=True, resolvable=True, binding_snapshot_id=None)
    binding = context.binding_snapshot(run.run_id, node.nodeId)
    if not binding or not str(binding.get("agentId") or ""):
        return ActorReadiness(
            configured=False,
            resolvable=False,
            binding_snapshot_id=str(binding.get("snapshotId") or "") if binding else None,
        )
    agent_id = str(binding["agentId"])
    return ActorReadiness(
        configured=True,
        resolvable=context.agent_resolvable(agent_id),
        binding_snapshot_id=str(binding.get("snapshotId") or ""),
        agent_id=agent_id,
    )
