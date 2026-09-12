"""Independent operator prerequisites; no Challenge Cup catalog or stage-one gates."""
from __future__ import annotations

from .common import DomainVerdict, blocker


def evaluate_operator_node(run, node, common, context) -> DomainVerdict:
    state = context.operator_campaign_state(run.team_id, run.run_id)
    if not state:
        return DomainVerdict(blockers=(blocker(
            "operator_campaign_missing", "实验活动不可用", "无法回读本次运行所属的实验活动", category="scope",
        ),))
    failures = []
    if node.nodeId == "optimization_knowledge":
        from ...operator_optimization.knowledge import (
            build_knowledge_request,
            knowledge_reuse_available,
            load_knowledge_snapshot,
        )
        from ...operator_optimization.store import CampaignConflict
        try:
            request = build_knowledge_request(run.team_id, run.run_id)
            active = next((r for r in state["campaign"].get("rounds", []) if r["runId"] == run.run_id), {})
            if active.get("knowledgeRef"):
                load_knowledge_snapshot(run.team_id, run.run_id)
            elif request.evidenceGaps and not knowledge_reuse_available(run.team_id, run.run_id, request):
                failures.append(("operator_knowledge_collection_budget_not_implemented",
                    "缺少匹配的已接受知识包，付费资料搜集预算尚未接入", "budget"))
        except (CampaignConflict, ValueError, FileNotFoundError):
            failures.append(("operator_knowledge_source_unavailable", "无法回读本轮假设或知识来源", "domain"))
    if node.nodeId == "optimization_plan":
        failures.append(("operator_plan_task_not_implemented", "实验计划冻结已实现，规划 Agent 任务尚未接入", "domain"))
    campaign = state["campaign"]
    if campaign["researchProjectId"] != run.project_id or campaign["teamId"] != run.team_id:
        failures.append(("operator_scope_mismatch", "实验活动与运行归属不一致", "scope"))
    if campaign["status"] != "running" or campaign["activeRunId"] != run.run_id:
        failures.append(("operator_campaign_inactive", "活动已停止、暂停或当前轮次已变化", "state"))
    if not campaign["budget"]["authorized"]:
        failures.append(("operator_budget_unauthorized", "尚未授权实验费用与 GPU 时长", "budget"))
    if node.nodeId in {"operator_baseline", "operator_execution"}:
        if not state["environmentVerified"]:
            failures.append(("operator_environment_unverified", "缺少本次环境的核验产物", "domain"))
        if not state["protocolFrozen"]:
            failures.append(("operator_protocol_missing", "尚未冻结工作负载和测量协议", "domain"))
        if state["budgetSummary"]["gpuTuningAvailableSeconds"] <= 0:
            failures.append(("operator_gpu_budget_empty", "GPU 时长预算不足", "budget"))
    if node.nodeId in {"optimization_discussion", "optimization_plan"} and campaign["budget"]["modelCostLimit"] <= 0:
        failures.append(("operator_model_budget_empty", "模型与检索预算不足", "budget"))
    if node.nodeId == "optimization_discussion" and not campaign["budget"].get("discussion"):
        failures.append(("operator_discussion_budget_missing", "尚未配置讨论调用次数、token 预算与模型价目", "budget"))
    if node.nodeId != "operator_baseline" and not campaign["baselineRef"]:
        failures.append(("operator_baseline_missing", "优化轮次需要可回读的初始基线", "domain"))
    return DomainVerdict(
        blockers=tuple(blocker(code, message, message, category=category) for code, message, category in failures),
        revision_vector={"operatorCampaign": str(campaign["revision"])},
    )
