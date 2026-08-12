"""Knowledge readiness evaluators: knowledge_ingestion / knowledge_handoff."""

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


def evaluate_knowledge_ingestion(
    *,
    run: RunSnapshot,
    node: WorkflowNodeSpec,
    common: CommonReadinessResult,
    context: DomainReadinessContext,
) -> DomainVerdict:
    blockers: list[Any] = []
    graph = context.evidence_graph_stats(run.team_id, run.run_id)
    if graph is None:
        blockers.append(
            blocker(
                "evidence_graph_incomplete",
                "证据关系图不完整",
                "Evidence Store 中没有可解析的证据关系图",
            )
        )
    else:
        if int(graph.get("node_count") or 0) <= 0:
            blockers.append(
                blocker(
                    "evidence_graph_incomplete",
                    "证据关系图不完整",
                    "证据关系图为空",
                )
            )
        missing_links = int(graph.get("missing_link_count") or 0)
        waivers = int(graph.get("waiver_count") or 0)
        if missing_links > 0 and waivers <= 0:
            blockers.append(
                blocker(
                    "evidence_graph_incomplete",
                    "证据关系图不完整",
                    f"存在 {missing_links} 个未豁免的 blocking missing links",
                )
            )
    return DomainVerdict(
        blockers=tuple(blockers),
        revision_vector=common.domain_revision_vector,
    )


def evaluate_knowledge_handoff(
    *,
    run: RunSnapshot,
    node: WorkflowNodeSpec,
    common: CommonReadinessResult,
    context: DomainReadinessContext,
) -> DomainVerdict:
    blockers: list[Any] = []
    draft = context.knowledge_package_draft(run.team_id, run.run_id)
    if draft is None:
        blockers.append(
            blocker(
                "knowledge_package_not_reviewable",
                "知识包暂不可审阅",
                "Knowledge Store 中没有正式写回的 draft 知识包",
            )
        )
    elif not draft.get("auditComplete") and not draft.get("reviewable"):
        blockers.append(
            blocker(
                "knowledge_package_not_reviewable",
                "知识包暂不可审阅",
                "知识包冲突、重复与 provenance 审计未完成",
            )
        )
    return DomainVerdict(
        blockers=tuple(blockers),
        revision_vector=common.domain_revision_vector,
    )
