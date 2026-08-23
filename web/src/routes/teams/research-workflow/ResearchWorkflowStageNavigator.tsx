import {
  AlertTriangle,
  CheckCircle2,
  Circle,
  CircleDot,
  Clock3,
} from "lucide-react";

import type { ResearchWorkflowProgress } from "../../../api/types/research-workflow/core";
import {
  VButton,
  VSkeleton,
  VStatusChip,
  VSurface,
  type VStatusTone,
  type WorkflowCanvasNodeInput,
  type WorkflowCanvasStageInput,
  type WorkflowLayoutInput,
} from "../../../components/vui";
import type { ResearchWorkflowWorkspaceLoadState } from "./researchWorkflowWorkspaceModel";
import styles from "./ResearchWorkflowStageNavigator.styles";

export type ResearchWorkflowStageNavigatorStatus =
  | "completed"
  | "current"
  | "upcoming"
  | "blocked";

export type ResearchWorkflowStageNavigatorNode = {
  id: string;
  label: string;
  status: ResearchWorkflowStageNavigatorStatus;
};

export type ResearchWorkflowStageNavigatorStage = {
  id: string;
  label: string;
  completed: number;
  total: number;
  blocked: number;
  status: ResearchWorkflowStageNavigatorStatus;
  targetNodeId: string | null;
  nodes: ResearchWorkflowStageNavigatorNode[];
};

export type ResearchWorkflowStageNavigatorModel = {
  state: "ready" | "loading" | "empty" | "error" | "unknown";
  detail: string | null;
  stages: ResearchWorkflowStageNavigatorStage[];
  summary: {
    currentStage: number;
    totalStages: number;
    completedNodes: number;
    totalNodes: number;
    blockedNodes: number;
    percent: number;
    authority: "formal" | "graph";
  };
};

export type BuildResearchWorkflowStageNavigatorModelInput = {
  graph: WorkflowLayoutInput | null;
  progress: ResearchWorkflowProgress | null;
  currentTaskNodeId?: string | null;
  loadState?: ResearchWorkflowWorkspaceLoadState;
  scopeMismatch?: boolean;
  error?: string | null;
};

function clampCount(value: number, maximum = Number.POSITIVE_INFINITY): number {
  return Math.min(Math.max(0, Math.round(Number(value) || 0)), maximum);
}

function graphNodeStatus(node: WorkflowCanvasNodeInput): ResearchWorkflowStageNavigatorStatus {
  if (["blocked", "failed", "stale", "cancelled"].includes(node.status)) return "blocked";
  if (node.status === "succeeded" || node.status === "skipped") return "completed";
  if (node.isRuntimeCurrent || ["ready", "running", "waiting_human"].includes(node.status)) return "current";
  return "upcoming";
}

function fallbackStageStatus(
  stage: WorkflowCanvasStageInput,
  nodes: readonly ResearchWorkflowStageNavigatorNode[],
  completed: number,
  total: number,
): ResearchWorkflowStageNavigatorStatus {
  if (stage.stageTone === "attention" || nodes.some((node) => node.status === "blocked")) return "blocked";
  if (stage.stageTone === "active" || nodes.some((node) => node.status === "current")) return "current";
  if (stage.stageTone === "done" || (total > 0 && completed >= total)) return "completed";
  return "upcoming";
}

function fallbackStage(
  stage: WorkflowCanvasStageInput,
  graphNodes: readonly WorkflowCanvasNodeInput[],
): ResearchWorkflowStageNavigatorStage {
  const sourceNodes = stage.nodeIds
    .map((nodeId) => graphNodes.find((node) => node.nodeId === nodeId))
    .filter((node): node is WorkflowCanvasNodeInput => Boolean(node));
  const nodes = sourceNodes.map((node) => ({
    id: node.nodeId,
    label: node.label,
    status: graphNodeStatus(node),
  }));
  const completed = clampCount(
    stage.progress?.completed ?? nodes.filter((node) => node.status === "completed").length,
  );
  const total = Math.max(
    completed,
    clampCount(stage.progress?.total ?? nodes.length),
  );
  const blocked = nodes.filter((node) => node.status === "blocked").length;
  const status = fallbackStageStatus(stage, nodes, completed, total);
  const currentNode = nodes.find((node) => node.status === "current");
  return {
    id: stage.stageId,
    label: stage.label,
    completed,
    total,
    blocked,
    status,
    targetNodeId: currentNode?.id ?? nodes[0]?.id ?? null,
    nodes,
  };
}

function formalNodeStatus(
  nodeId: string,
  progress: ResearchWorkflowProgress,
): ResearchWorkflowStageNavigatorStatus {
  if (progress.blockedNodeIds.includes(nodeId)) return "blocked";
  if (progress.completedNodeIds.includes(nodeId)) return "completed";
  if (progress.currentNodeId === nodeId) return "current";
  return "upcoming";
}

function currentStageNumber(stages: readonly ResearchWorkflowStageNavigatorStage[]): number {
  if (!stages.length) return 0;
  const current = stages.findIndex((stage) => stage.status === "current" || stage.status === "blocked");
  if (current >= 0) return current + 1;
  const completed = stages.filter((stage) => stage.status === "completed").length;
  return Math.min(stages.length, completed + 1);
}

export function buildResearchWorkflowStageNavigatorModel(
  input: BuildResearchWorkflowStageNavigatorModelInput,
): ResearchWorkflowStageNavigatorModel {
  const formal = input.progress;
  const formalCurrentIndex = formal?.stages.findIndex((stage) => stage.id === formal.currentStageId) ?? -1;
  const formalCompletedStageCount = formal?.stages.filter((stage) => stage.state === "completed").length ?? 0;
  const emptySummary: ResearchWorkflowStageNavigatorModel["summary"] = formal
    ? {
        currentStage: formalCurrentIndex >= 0
          ? formalCurrentIndex + 1
          : Math.min(formal.stages.length, formalCompletedStageCount + 1),
        totalStages: formal.stages.length,
        completedNodes: clampCount(formal.completedNodes),
        totalNodes: Math.max(clampCount(formal.completedNodes), clampCount(formal.totalNodes)),
        blockedNodes: clampCount(formal.blockedNodes),
        percent: clampCount(formal.percent, 100),
        authority: "formal",
      }
    : {
        currentStage: 0,
        totalStages: 0,
        completedNodes: 0,
        totalNodes: 0,
        blockedNodes: 0,
        percent: 0,
        authority: "graph",
      };
  if (input.scopeMismatch || input.loadState === "scope_mismatch") {
    return { state: "unknown", detail: "题目或运行范围正在切换，等待权威快照。", stages: [], summary: emptySummary };
  }
  if (input.error || input.loadState === "error") {
    return { state: "error", detail: input.error || "暂时无法读取流程进度。", stages: [], summary: emptySummary };
  }
  if (["loading", "refreshing", "resync_required"].includes(input.loadState ?? "")) {
    return { state: "loading", detail: null, stages: [], summary: emptySummary };
  }
  if (!input.graph) {
    return { state: "empty", detail: "流程定义尚未就绪，阶段导航会在读取后自动更新。", stages: [], summary: emptySummary };
  }

  const formalStageById = new Map((formal?.stages ?? []).map((stage) => [stage.id, stage] as const));
  const stages = input.graph.stages.map((stage) => {
    const fallback = fallbackStage(stage, input.graph?.nodes ?? []);
    const formalStage = formalStageById.get(stage.stageId);
    if (!formal || !formalStage) return fallback;
    const nodes = fallback.nodes.map((node) => ({
      ...node,
      status: formalNodeStatus(node.id, formal),
    }));
    const isFormalCurrentStage = !formal.currentStageId || formal.currentStageId === stage.stageId;
    const preferredCurrentNode = isFormalCurrentStage
      ? [input.currentTaskNodeId, formal.currentNodeId]
          .find((nodeId) => Boolean(nodeId && stage.nodeIds.includes(nodeId))) ?? null
      : null;
    return {
      ...fallback,
      completed: clampCount(formalStage.completed),
      total: Math.max(clampCount(formalStage.completed), clampCount(formalStage.total)),
      blocked: clampCount(formalStage.blocked),
      status: formalStage.state,
      targetNodeId: preferredCurrentNode || nodes[0]?.id || null,
      nodes,
    };
  });

  if (formal) {
    return {
      state: stages.length ? "ready" : "empty",
      detail: stages.length ? null : "当前流程没有可显示的阶段。",
      stages,
      summary: {
        currentStage: formalCurrentIndex >= 0
          ? formalCurrentIndex + 1
          : Math.min(formal.stages.length, formalCompletedStageCount + 1),
        totalStages: formal.stages.length,
        completedNodes: clampCount(formal.completedNodes),
        totalNodes: Math.max(clampCount(formal.completedNodes), clampCount(formal.totalNodes)),
        blockedNodes: clampCount(formal.blockedNodes),
        percent: clampCount(formal.percent, 100),
        authority: "formal",
      },
    };
  }

  const graphNodeStates = input.graph.nodes.map(graphNodeStatus);
  const completedNodes = graphNodeStates.filter((status) => status === "completed").length;
  const totalNodes = graphNodeStates.length;
  const blockedNodes = graphNodeStates.filter((status) => status === "blocked").length;
  return {
    state: stages.length ? "ready" : "empty",
    detail: stages.length ? null : "当前流程没有可显示的阶段。",
    stages,
    summary: {
      currentStage: currentStageNumber(stages),
      totalStages: stages.length,
      completedNodes,
      totalNodes,
      blockedNodes,
      percent: totalNodes ? clampCount((completedNodes / totalNodes) * 100, 100) : 0,
      authority: "graph",
    },
  };
}

function statusPresentation(status: ResearchWorkflowStageNavigatorStatus, zh: boolean): {
  label: string;
  tone: VStatusTone;
  icon: typeof Circle;
} {
  if (status === "completed") return { label: zh ? "已完成" : "Completed", tone: "success", icon: CheckCircle2 };
  if (status === "current") return { label: zh ? "进行中" : "Current", tone: "accent", icon: CircleDot };
  if (status === "blocked") return { label: zh ? "已阻塞" : "Blocked", tone: "danger", icon: AlertTriangle };
  return { label: zh ? "未开始" : "Upcoming", tone: "neutral", icon: Clock3 };
}

export function ResearchWorkflowStageNavigator({
  lang,
  model,
  onNavigateNode,
}: {
  lang: "zh" | "en";
  model: ResearchWorkflowStageNavigatorModel;
  onNavigateNode: (nodeId: string) => void;
}) {
  const zh = lang === "zh";
  const summary = model.summary;
  return (
    <VSurface
      as="section"
      ariaLabel={zh ? "科研流程阶段导航" : "Research workflow stage navigation"}
      className={styles.root}
      data-testid="research-workflow-stage-navigator"
      data-vui="research-workflow-stage-navigator"
      padding="none"
      role="navigation"
      tone="rail"
    >
      <header className={styles.header}>
        <div className={styles.headingRow}>
          <h2 className={styles.title}>{zh ? "流程进度" : "Workflow progress"}</h2>
          <VStatusChip tone={summary.blockedNodes > 0 ? "danger" : "neutral"}>
            {summary.blockedNodes > 0 ? (
              <span className={styles.statusContent}><AlertTriangle size={12} aria-hidden="true" />{zh ? `${summary.blockedNodes} 项阻塞` : `${summary.blockedNodes} blocked`}</span>
            ) : (zh ? "无阻塞" : "No blockers")}
          </VStatusChip>
        </div>
        <div className={styles.summaryGrid} data-testid="stage-navigator-summary">
          <span className={styles.summaryItem}><span className={styles.summaryLabel}>{zh ? "阶段" : "Stage"}</span><strong className={styles.summaryValue}>{summary.currentStage}/{summary.totalStages}</strong></span>
          <span className={styles.summaryItem}><span className={styles.summaryLabel}>{zh ? "节点" : "Nodes"}</span><strong className={styles.summaryValue}>{summary.completedNodes}/{summary.totalNodes}</strong></span>
          <span className={styles.summaryItem}><span className={styles.summaryLabel}>{zh ? "阻塞" : "Blocked"}</span><strong className={styles.summaryValue}>{summary.blockedNodes}</strong></span>
          <span className={styles.summaryItem}><span className={styles.summaryLabel}>{zh ? "整体" : "Overall"}</span><strong className={styles.summaryValue}>{summary.percent}%</strong></span>
        </div>
        <div className={styles.progressTrack} role="progressbar" aria-label={zh ? "整体进度" : "Overall progress"} aria-valuemin={0} aria-valuemax={100} aria-valuenow={summary.percent}>
          <div className={styles.progressFill} style={{ width: `${summary.percent}%` }} />
        </div>
      </header>
      <div className={styles.body}>
        {model.state === "loading" ? (
          <div className={styles.skeleton} aria-label={zh ? "正在读取阶段进度" : "Loading stage progress"} aria-busy="true">
            <VSkeleton shape="block" /><VSkeleton shape="block" /><VSkeleton shape="block" />
          </div>
        ) : model.state !== "ready" ? (
          <div className={styles.state} data-state={model.state}>
            <Circle size={22} aria-hidden="true" className="mx-auto text-[var(--fg-tertiary)]" />
            <h3 className={styles.stateTitle}>{model.state === "error" ? (zh ? "进度读取失败" : "Progress unavailable") : model.state === "unknown" ? (zh ? "进度待确认" : "Progress pending") : (zh ? "等待流程定义" : "Waiting for workflow")}</h3>
            <p className={styles.stateDetail}>{model.detail}</p>
          </div>
        ) : (
          <ol className={styles.stageList}>
            {model.stages.map((stage) => {
              const presentation = statusPresentation(stage.status, zh);
              const StageIcon = presentation.icon;
              return (
                <li key={stage.id} className={styles.stage} data-stage-status={stage.status}>
                  <VButton
                    type="button"
                    contentLayout="plain"
                    variant="secondary"
                    className={styles.stageButton}
                    aria-current={stage.status === "current" ? "step" : undefined}
                    isDisabled={!stage.targetNodeId}
                    disabledReason={zh ? "该阶段没有可定位节点" : "No navigable node in this stage"}
                    onClick={() => stage.targetNodeId && onNavigateNode(stage.targetNodeId)}
                  >
                    <span className={styles.stageButtonBody}>
                      <span className={styles.stageTopLine}><span className={styles.stageLabel}>{stage.label}</span><span className={styles.stageCount}>{stage.completed}/{stage.total}</span></span>
                      <VStatusChip tone={presentation.tone}><span className={styles.statusContent}><StageIcon size={12} aria-hidden="true" />{presentation.label}</span></VStatusChip>
                    </span>
                  </VButton>
                  {stage.nodes.length ? (
                    <div className={styles.nodes} aria-label={zh ? `${stage.label}节点` : `${stage.label} nodes`}>
                      {stage.nodes.map((node) => {
                        const nodePresentation = statusPresentation(node.status, zh);
                        const NodeIcon = nodePresentation.icon;
                        return (
                          <VButton
                            key={node.id}
                            type="button"
                            contentLayout="plain"
                            variant="ghost"
                            className={styles.nodeButton}
                            aria-current={node.status === "current" ? "step" : undefined}
                            onClick={() => onNavigateNode(node.id)}
                          >
                            <NodeIcon size={12} aria-hidden="true" />
                            <span className={styles.nodeLabel}>{node.label}</span>
                            <span className={styles.nodeStatus}>{nodePresentation.label}</span>
                          </VButton>
                        );
                      })}
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ol>
        )}
      </div>
    </VSurface>
  );
}
