import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { queryKeys } from "../../../api/queryKeys";
import type { AnomalyInboxResponse } from "../../../api/types/hypothesisFirst";
import type { ChallengeCupRealBatchProjection } from "../../../api/types/challengeCup";
import type { ChallengeSubmissionReadiness } from "../../../api/types/challengeCup";
import { VWorkflowCanvas } from "../../../components/vui";
import type { WorkflowLayoutInput } from "../../../components/vui/product/workflow/workflowCanvasTypes";
import { ChallengeCatalogOverview } from "../../../routes/teams/challenge-cup/ChallengeCatalogOverview";
import type { CatalogOverview } from "../../../routes/teams/challenge-cup/challengeCatalogOverviewModel";
import { ChallengeTokenUsageStrip } from "../../../routes/teams/challenge-cup/ChallengeTokenUsageStrip";
import { ChallengeRealBatchControlPanel } from "../../../routes/teams/research-workflow/ChallengeRealBatchControlPanel";
import { ChallengeSubmissionReadinessPanel } from "../../../routes/teams/research-workflow/ChallengeSubmissionReadinessPanel";
import { ResearchAnomalyInboxPanel } from "../../../routes/teams/research-workflow/ResearchAnomalyInboxPanel";
import { VuiPreviewCard } from "../VuiPreviewCard";
import { VuiPreviewSection } from "../VuiPreviewSection";
import { workflowCatalogClasses } from "./WorkflowCatalog.styles";

const demoGraph: WorkflowLayoutInput = {
  stages: [
    { stageId: "knowledge_collection", label: "知识采集", nodeIds: ["kc_search", "kc_verify"], stageTone: "done" },
    { stageId: "experiment_design", label: "实验设计", nodeIds: ["ed_design", "ed_decision"], stageTone: "active" },
    { stageId: "execution_iteration", label: "执行迭代", nodeIds: ["ei_run"], stageTone: "idle" },
  ],
  nodes: [
    {
      nodeId: "kc_search",
      stageId: "knowledge_collection",
      label: "知识检索",
      actorKind: "agent",
      visualKind: "agent_task",
      status: "succeeded",
    },
    {
      nodeId: "kc_verify",
      stageId: "knowledge_collection",
      label: "证据核验",
      actorKind: "system",
      visualKind: "system_task",
      status: "succeeded",
    },
    {
      nodeId: "ed_design",
      stageId: "experiment_design",
      label: "实验方案",
      actorKind: "agent",
      visualKind: "agent_task",
      status: "running",
      isRuntimeCurrent: true,
    },
    {
      nodeId: "ed_decision",
      stageId: "experiment_design",
      label: "方案决策",
      actorKind: "agent",
      visualKind: "decision",
      status: "pending",
    },
    {
      nodeId: "ei_run",
      stageId: "execution_iteration",
      label: "迭代执行",
      actorKind: "system",
      visualKind: "system_task",
      status: "pending",
    },
  ],
  edges: [
    {
      edgeId: "e1",
      fromNodeId: "kc_search",
      toNodeId: "kc_verify",
      label: "提交核验",
      gateKind: "evidence_review",
      semanticKind: "main",
      pathState: "traversed",
      labelAlwaysVisible: false,
    },
    {
      edgeId: "e2",
      fromNodeId: "kc_verify",
      toNodeId: "ed_design",
      label: "进入设计",
      gateKind: "handoff",
      semanticKind: "main",
      pathState: "active",
      labelAlwaysVisible: true,
    },
    {
      edgeId: "e3",
      fromNodeId: "ed_decision",
      toNodeId: "ei_run",
      label: "通过",
      gateKind: "human_approval",
      semanticKind: "main",
      pathState: "idle",
      labelAlwaysVisible: false,
    },
  ],
  run: {
    runId: "run-demo",
    status: "running",
    runtimeCurrentNodeIds: ["ed_design"],
  },
};

const previewTeamId = "challenge-readiness-preview";
const challengeReadinessPreview: ChallengeSubmissionReadiness = {
  schemaVersion: 1,
  teamId: previewTeamId,
  status: "blocked",
  readyCount: 3,
  requiredCount: 5,
  blockerCount: 2,
  artifacts: [
    {
      key: "full_catalog_results",
      label: "Full catalog results",
      required: true,
      status: "blocked",
      detail: "122/125",
      blocker: "full_catalog_results_incomplete",
      primaryAction: { kind: "repair", target: "full-catalog-results", label: "Repair", questionId: "SCI-124" },
    },
    {
      key: "technical_proposal_pdf",
      label: "Technical proposal PDF",
      required: true,
      status: "ready",
      detail: "confirmed",
      blocker: "",
      primaryAction: { kind: "inspect", target: "submission-package", label: "Inspect" },
    },
    {
      key: "demo_video",
      label: "Demo video",
      required: false,
      status: "optional",
      detail: "optional",
      blocker: "",
      primaryAction: { kind: "inspect", target: "submission-package", label: "Inspect" },
    },
  ],
  blockers: [
    {
      code: "full_catalog_results_incomplete",
      label: "Full catalog results incomplete",
      action: { kind: "repair", target: "full-catalog-results", label: "Repair", questionId: "SCI-124" },
    },
    {
      code: "source_code_not_packaged",
      label: "Source package not confirmed",
      action: { kind: "inspect", target: "submission-package", label: "Inspect" },
    },
  ],
  programSummary: {
    title: "Challenge Cup Research",
    questionCount: 125,
    approvedQuestionCount: 122,
    deepExperimentCount: 2,
    approvedDeepExperimentCount: 2,
  },
};
const challengeReadinessQueryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: Infinity, retry: false } },
});
challengeReadinessQueryClient.setQueryData(
  queryKeys.challengeSubmissionReadiness(previewTeamId),
  challengeReadinessPreview,
);
const challengeCatalogOverviewPreview: CatalogOverview = {
  schemaVersion: 1,
  teamId: previewTeamId,
  generatedAt: "2026-08-20T00:00:00Z",
  questionCount: 2,
  counts: { queued: 0, running: 0, succeeded: 1, failed: 1 },
  questions: [
    {
      questionId: "SCI-001",
      title: "基线复现",
      domain: "science",
      status: "failed",
      executionStatus: "failed",
      currentStage: "catalog_execution",
      checkpointProgress: "1/3",
      attempts: 1,
      planId: "plan-preview",
      action: "retry",
      blocker: { code: "eval_failed", message: "评测未通过", remediationLabel: "重试失败题" },
    },
    {
      questionId: "SCI-002",
      title: "对照实验",
      domain: "science",
      status: "succeeded",
      executionStatus: "succeeded",
      currentStage: "complete",
      checkpointProgress: "3/3",
      attempts: 1,
      planId: "plan-preview",
      action: "view",
      blocker: null,
    },
  ],
};
challengeReadinessQueryClient.setQueryData(
  queryKeys.challengeCupCatalogOverview(previewTeamId),
  challengeCatalogOverviewPreview,
);
const realBatchPreview: ChallengeCupRealBatchProjection = {
  schemaVersion: 1,
  planId: "real-125",
  gateId: "gate-real-125",
  exists: true,
  questionCount: 125,
  statusSummary: { pending: 8, running: 3, succeeded: 112, failed: 2, blocked: 0 },
  pendingCount: 8,
  succeededCount: 112,
  failedCount: 2,
  blockedCount: 0,
  totalAttempts: 131,
  completedQuestionIds: ["SCI-001", "SCI-002"],
  pendingQuestionIds: ["SCI-123", "SCI-124"],
  runRefs: { "SCI-001": { runId: "run-sci-001", attempt: 2 } },
  awaitingApprovalQuestionIds: [],
  consecutiveFailures: 1,
  failureBudget: 5,
  circuitBreakerOpen: false,
  cancelled: false,
  gateComplete: false,
  lastUpdatedAt: "2026-08-28T00:00:00Z",
  canResume: true,
  drainState: "draining",
  concurrencyLimit: 4,
  autoCloseTarget: 95,
};
challengeReadinessQueryClient.setQueryData(
  queryKeys.challengeCupRealBatchStatus(previewTeamId, "real-125"),
  realBatchPreview,
);
const anomalyInboxPreview: AnomalyInboxResponse = {
  schemaVersion: 1,
  teamId: previewTeamId,
  questionId: "",
  inbox: {
    schemaVersion: 1,
    ruleId: "anomaly-inbox",
    generatedAt: "2026-08-28T00:00:00Z",
    items: [
      {
        kind: "blocked_run",
        scope: { teamId: previewTeamId, questionId: "SCI-124", runId: "run-sci-124", nodeId: "human_gate", meetingRoundId: "" },
        severity: "critical",
        firstSeenAt: "2026-08-27T09:00:00Z",
        lastSeenAt: "2026-08-28T00:00:00Z",
        summary: "运行在人工门禁处阻塞超过 2 小时",
        recommendedAction: "reconcile_run",
        evidence: ["gate=human_approval", "waiting_minutes=128"],
      },
      {
        kind: "retry_budget_exhausted",
        scope: { teamId: previewTeamId, questionId: "SCI-002", runId: "run-sci-002", nodeId: "formal_run", meetingRoundId: "" },
        severity: "high",
        firstSeenAt: "2026-08-27T18:30:00Z",
        lastSeenAt: "2026-08-28T00:00:00Z",
        summary: "formal_run 节点重试预算耗尽",
        recommendedAction: "retry_node",
        evidence: ["attempts=3", "budget=3"],
      },
      {
        kind: "drift_sentinel_hit",
        scope: { teamId: previewTeamId, questionId: "SCI-121", runId: "run-sci-121", nodeId: "evidence_sample", meetingRoundId: "" },
        severity: "medium",
        firstSeenAt: "2026-08-28T06:12:00Z",
        lastSeenAt: "2026-08-28T06:12:00Z",
        summary: "抽样漂移哨兵命中一次，证据一致性待复核",
        recommendedAction: null,
        evidence: ["sample_ratio=0.18"],
      },
    ],
  },
};
challengeReadinessQueryClient.setQueryData(
  queryKeys.hypothesisFirstChainAnomalyInbox(previewTeamId, ""),
  anomalyInboxPreview,
);

const serpentineStatusGraph: WorkflowLayoutInput = {
  stages: [
    {
      stageId: "s_knowledge",
      label: "知识搜集",
      nodeIds: ["sk_find", "sk_extract", "sk_ingest"],
      stageTone: "done",
    },
    {
      stageId: "s_experiment",
      label: "实验设计",
      nodeIds: ["se_hypothesis", "se_protocol", "se_review", "se_smoke"],
      stageTone: "active",
    },
    {
      stageId: "s_iteration",
      label: "执行迭代",
      nodeIds: ["si_run", "si_eval", "si_decision"],
      stageTone: "attention",
    },
    {
      stageId: "s_misc",
      label: "其余状态",
      nodeIds: ["sm_ready", "sm_skipped", "sm_stale", "sm_cancelled"],
      stageTone: "idle",
    },
  ],
  nodes: [
    { nodeId: "sk_find", stageId: "s_knowledge", label: "资料寻找", actorKind: "agent", visualKind: "agent_task", status: "succeeded", primaryRoleKey: "source_finder", primaryAgentId: "agent-bai" },
    { nodeId: "sk_extract", stageId: "s_knowledge", label: "证据提炼", actorKind: "agent", visualKind: "agent_task", status: "succeeded", primaryRoleKey: "source_extractor", primaryAgentId: "agent-gu" },
    { nodeId: "sk_ingest", stageId: "s_knowledge", label: "知识入库", actorKind: "system", visualKind: "system_task", status: "succeeded", primaryRoleKey: "source_ingestor" },
    { nodeId: "se_hypothesis", stageId: "s_experiment", label: "假设起草", actorKind: "agent", visualKind: "agent_task", status: "succeeded", primaryRoleKey: "experiment_planner", primaryAgentId: "agent-lin" },
    { nodeId: "se_protocol", stageId: "s_experiment", label: "协议冻结", actorKind: "agent", visualKind: "agent_task", status: "running", isRuntimeCurrent: true, primaryRoleKey: "experiment_planner", primaryAgentId: "agent-shen" },
    { nodeId: "se_review", stageId: "s_experiment", label: "人工评审", actorKind: "human", visualKind: "human_gate", status: "waiting_human", primaryRoleKey: "research_owner" },
    { nodeId: "se_smoke", stageId: "s_experiment", label: "试跑放行", actorKind: "system", visualKind: "system_task", status: "pending", primaryRoleKey: "formal_runner" },
    { nodeId: "si_run", stageId: "s_iteration", label: "批次执行", actorKind: "agent", visualKind: "agent_task", status: "failed", primaryRoleKey: "formal_runner", primaryAgentId: "agent-zhou" },
    { nodeId: "si_eval", stageId: "s_iteration", label: "结果评估", actorKind: "agent", visualKind: "agent_task", status: "blocked", primaryRoleKey: "experiment_ledger" },
    { nodeId: "si_decision", stageId: "s_iteration", label: "迭代决策", actorKind: "agent", visualKind: "decision", status: "pending", primaryRoleKey: "iteration_planner" },
    { nodeId: "sm_ready", stageId: "s_misc", label: "就绪任务", actorKind: "agent", visualKind: "agent_task", status: "ready", primaryRoleKey: "iteration_planner" },
    { nodeId: "sm_skipped", stageId: "s_misc", label: "跳过任务", actorKind: "agent", visualKind: "agent_task", status: "skipped", primaryRoleKey: "iteration_versioning" },
    { nodeId: "sm_stale", stageId: "s_misc", label: "过期任务", actorKind: "agent", visualKind: "agent_task", status: "stale", primaryRoleKey: "package_builder" },
    { nodeId: "sm_cancelled", stageId: "s_misc", label: "取消任务", actorKind: "agent", visualKind: "agent_task", status: "cancelled", primaryRoleKey: "package_builder" },
  ],
  edges: [
    { edgeId: "se1", fromNodeId: "sk_find", toNodeId: "sk_extract", label: "提交提炼", gateKind: "auto", semanticKind: "main", pathState: "traversed", labelAlwaysVisible: false },
    { edgeId: "se2", fromNodeId: "sk_extract", toNodeId: "sk_ingest", label: "入库", gateKind: "auto", semanticKind: "main", pathState: "traversed", labelAlwaysVisible: false },
    { edgeId: "se3", fromNodeId: "sk_ingest", toNodeId: "se_hypothesis", label: "证据交接", gateKind: "knowledge_package", semanticKind: "human_gate", pathState: "traversed", labelAlwaysVisible: true },
    { edgeId: "se4", fromNodeId: "se_hypothesis", toNodeId: "se_protocol", label: "冻结", gateKind: "auto", semanticKind: "main", pathState: "active", labelAlwaysVisible: false },
    { edgeId: "se5", fromNodeId: "se_protocol", toNodeId: "se_review", label: "送审", gateKind: "human", semanticKind: "human_gate", pathState: "attention", labelAlwaysVisible: true },
    { edgeId: "se6", fromNodeId: "se_review", toNodeId: "se_smoke", label: "放行", gateKind: "smoke", semanticKind: "main", pathState: "idle", labelAlwaysVisible: false },
    { edgeId: "se7", fromNodeId: "se_smoke", toNodeId: "si_run", label: "进入执行", gateKind: "auto", semanticKind: "main", pathState: "idle", labelAlwaysVisible: false },
    { edgeId: "se8", fromNodeId: "si_run", toNodeId: "si_eval", label: "评估", gateKind: "auto", semanticKind: "main", pathState: "danger", labelAlwaysVisible: false },
    { edgeId: "se9", fromNodeId: "si_eval", toNodeId: "si_decision", label: "门禁判定", gateKind: "promotion", semanticKind: "decision_branch", pathState: "idle", labelAlwaysVisible: true },
    { edgeId: "se10", fromNodeId: "si_decision", toNodeId: "sm_ready", label: "重跑", gateKind: "auto", semanticKind: "rerun", pathState: "idle", labelAlwaysVisible: true },
  ],
  run: {
    runId: "run-serpentine-demo",
    status: "running",
    runtimeCurrentNodeIds: ["se_protocol"],
  },
};

export function WorkflowCatalog() {
  return (
    <VuiPreviewSection title="Workflow">
      <VuiPreviewCard name="ChallengeSubmissionReadiness" className={workflowCatalogClasses.card}>
        <QueryClientProvider client={challengeReadinessQueryClient}>
          <ChallengeSubmissionReadinessPanel teamId={previewTeamId} onOpenQuestion={() => undefined} />
        </QueryClientProvider>
      </VuiPreviewCard>
      <VuiPreviewCard name="ChallengeTokenUsageStrip" className={workflowCatalogClasses.card}>
        <ChallengeTokenUsageStrip
          totalTokens={12800}
          callCount={6}
          inputTokens={8400}
          outputTokens={4400}
        />
      </VuiPreviewCard>
      <VuiPreviewCard name="ChallengeCatalogOverview" className={workflowCatalogClasses.card}>
        <QueryClientProvider client={challengeReadinessQueryClient}>
          <ChallengeCatalogOverview teamId={previewTeamId} onOpenQuestion={() => undefined} />
        </QueryClientProvider>
      </VuiPreviewCard>
      <VuiPreviewCard name="ChallengeRealBatchControlPanel" className={workflowCatalogClasses.card}>
        <QueryClientProvider client={challengeReadinessQueryClient}>
          <ChallengeRealBatchControlPanel teamId={previewTeamId} lang="zh" />
        </QueryClientProvider>
      </VuiPreviewCard>
      <VuiPreviewCard name="ResearchAnomalyInboxPanel" className={workflowCatalogClasses.card}>
        <QueryClientProvider client={challengeReadinessQueryClient}>
          <ResearchAnomalyInboxPanel teamId={previewTeamId} lang="zh" />
        </QueryClientProvider>
      </VuiPreviewCard>
      <VuiPreviewCard name="VWorkflowCanvas" className={workflowCatalogClasses.card}>
        <div className={workflowCatalogClasses.host}>
          <VWorkflowCanvas graph={demoGraph} height="100%" />
        </div>
      </VuiPreviewCard>
      <VuiPreviewCard name="VWorkflowCanvas · serpentine 全状态" className={workflowCatalogClasses.card}>
        <div className={workflowCatalogClasses.hostTall}>
          <VWorkflowCanvas graph={serpentineStatusGraph} height="100%" layoutMode="serpentine" showMiniMap />
        </div>
      </VuiPreviewCard>
    </VuiPreviewSection>
  );
}
