import type {
  VStatusTone,
  WorkflowCanvasNodeInput,
  WorkflowLayoutInput,
} from "../../../components/vui";
import { VButton, VNativeButton, VStatusChip, VSurface } from "../../../components/vui";
import type { HypothesisFirstNextAction } from "./hypothesisFirstNextAction";
import styles from "./ResearchProcessRail.styles";

type StageRow = {
  stageId: string;
  label: string;
  index: number;
  tone: "idle" | "active" | "done" | "attention";
  nodes: WorkflowCanvasNodeInput[];
  completed: number;
  total: number;
};

export type ResearchProcessRailProps = {
  graph: WorkflowLayoutInput | null;
  selectedNodeId: string | null;
  runtimeCurrentNodeIds: string[];
  nextAction: HypothesisFirstNextAction;
  onSelectNode: (nodeId: string) => void;
  onNavigateCurrent: (nodeId: string) => void;
};

function stageRows(graph: WorkflowLayoutInput | null): StageRow[] {
  if (!graph) return [];
  const nodesById = new Map(graph.nodes.map((node) => [node.nodeId, node]));
  const assignedNodeIds = new Set<string>();
  const rows = graph.stages.flatMap((stage, position) => {
    const nodes = stage.nodeIds
      .map((nodeId) => nodesById.get(nodeId))
      .filter((node): node is WorkflowCanvasNodeInput => Boolean(node));
    nodes.forEach((node) => assignedNodeIds.add(node.nodeId));
    if (!nodes.length) return [];
    const completed = stage.progress?.completed
      ?? nodes.filter((node) => node.status === "succeeded" || node.status === "skipped").length;
    return [{
      stageId: stage.stageId,
      label: stage.label,
      index: stage.index ?? position + 1,
      tone: stage.stageTone ?? "idle",
      nodes,
      completed,
      total: stage.progress?.total ?? nodes.length,
    }];
  });

  const unassignedNodes = graph.nodes.filter((node) => !assignedNodeIds.has(node.nodeId));
  if (unassignedNodes.length) {
    rows.push({
      stageId: "unassigned",
      label: "其他节点",
      index: rows.length + 1,
      tone: "idle",
      nodes: unassignedNodes,
      completed: unassignedNodes.filter((node) => node.status === "succeeded" || node.status === "skipped").length,
      total: unassignedNodes.length,
    });
  }
  return rows;
}

function nodeStatusLabel(
  node: WorkflowCanvasNodeInput,
  currentTask: boolean,
  runtimeCurrent: boolean,
): string {
  if (currentTask) return "当前任务";
  if (runtimeCurrent) return "运行位置";
  switch (node.status) {
    case "succeeded":
    case "skipped":
      return "已完成";
    case "running":
      return "处理中";
    case "waiting_human":
      return "待确认";
    case "failed":
      return "失败";
    case "blocked":
      return "已阻塞";
    case "ready":
      return "可开始";
    case "stale":
      return "待刷新";
    case "cancelled":
      return "已取消";
    default:
      return "未开始";
  }
}

function nodeStatusTone(node: WorkflowCanvasNodeInput): VStatusTone {
  switch (node.status) {
    case "failed":
      return "danger";
    case "blocked":
    case "waiting_human":
      return "warning";
    case "running":
      return "accent";
    case "succeeded":
    case "skipped":
      return "success";
    default:
      return "neutral";
  }
}

function nextStatus(nextAction: HypothesisFirstNextAction): { label: string; tone: VStatusTone } {
  if (nextAction.recovery || nextAction.stage === "collection_recovery" || nextAction.stage === "budget_exhausted") {
    return { label: "需要处理", tone: "warning" };
  }
  if (nextAction.stage === "blocked") return { label: "已阻塞", tone: "danger" };
  if (nextAction.command) return { label: "等待你操作", tone: "warning" };
  if (nextAction.statusMessage) return { label: "系统处理中", tone: "accent" };
  if (nextAction.stage === "no_run") return { label: "待开始", tone: "neutral" };
  return { label: "当前任务", tone: "accent" };
}

function nextDetail(nextAction: HypothesisFirstNextAction): string {
  return nextAction.commandDetail
    || nextAction.recovery?.reason
    || nextAction.statusMessage
    || nextAction.disabledReason
    || (nextAction.stage === "no_run" ? "选择题目后，研究阶段和可操作任务会显示在这里。" : "从当前任务进入右侧操作面板。");
}

function stageStatusLabel(row: StageRow, currentStageId: string | null): string {
  if (row.stageId === currentStageId) return "当前阶段";
  if (row.tone === "attention") return "需处理";
  if (row.tone === "active") return "进行中";
  if (row.tone === "done") return "已完成";
  return "未开始";
}

export function ResearchProcessRail({
  graph,
  selectedNodeId,
  runtimeCurrentNodeIds,
  nextAction,
  onSelectNode,
  onNavigateCurrent,
}: ResearchProcessRailProps) {
  const rows = stageRows(graph);
  const currentTaskId = nextAction.targetNodeId;
  const currentNode = graph?.nodes.find((node) => node.nodeId === currentTaskId) ?? null;
  const currentStage = rows.find((row) => row.nodes.some((node) => node.nodeId === currentTaskId)) ?? null;
  const currentStatus = nextStatus(nextAction);

  return (
    <nav
      className={styles.root}
      aria-label="研究阶段与任务"
      data-testid="research-process-rail"
      data-vui="research-process-rail"
    >
      <div className={styles.body}>
        <VSurface tone="panel" elevation="flat" padding="compact" className={styles.currentCard} data-testid="research-process-rail-current">
          <span className={styles.kicker}>当前任务</span>
          <div className={styles.currentMeta}>
            <strong className={styles.currentTitle}>{currentNode?.label ?? nextAction.navigationLabel}</strong>
            <VStatusChip tone={currentStatus.tone}>{currentStatus.label}</VStatusChip>
          </div>
          {currentStage ? (
            <span className={styles.currentStage}>
              第 {currentStage.index} 阶段 · {currentStage.label}
            </span>
          ) : null}
          <p className={styles.currentDetail}>{nextDetail(nextAction)}</p>
          <VButton
            type="button"
            density="compact"
            variant="primary"
            className={styles.action}
            isDisabled={!currentTaskId}
            onPress={() => {
              if (currentTaskId) onNavigateCurrent(currentTaskId);
            }}
            data-testid="research-process-rail-current-action"
          >
            前往当前任务
          </VButton>
        </VSurface>

        <section className={styles.stageSection} aria-labelledby="research-process-rail-stage-heading">
          <h2 id="research-process-rail-stage-heading" className={styles.sectionLabel}>研究阶段</h2>
          {rows.length ? (
            <ol className={styles.stageList} data-testid="research-process-rail-stages">
              {rows.map((row) => {
                const active = row.stageId === currentStage?.stageId;
                return (
                  <li
                    key={row.stageId}
                    className={active ? styles.stageItemActive : styles.stageItem}
                    data-active={active ? "true" : "false"}
                    data-testid={`research-process-rail-stage-${row.stageId}`}
                  >
                    <div className={styles.stageHeader}>
                      <strong className={styles.stageTitle}>{row.index.toString().padStart(2, "0")} · {row.label}</strong>
                      <VStatusChip tone={row.tone === "attention" ? "warning" : row.tone === "active" ? "accent" : row.tone === "done" ? "success" : "neutral"}>
                        {stageStatusLabel(row, currentStage?.stageId ?? null)}
                      </VStatusChip>
                    </div>
                    <span className={styles.stageMeta}>{row.completed}/{row.total} 已完成</span>
                    <ul className={styles.nodeList}>
                      {row.nodes.map((node) => {
                        const currentTask = node.nodeId === currentTaskId;
                        const runtimeCurrent = runtimeCurrentNodeIds.includes(node.nodeId);
                        const selected = node.nodeId === selectedNodeId;
                        const description = node.description || node.label;
                        return (
                          <li key={node.nodeId}>
                            <VNativeButton
                              type="button"
                              className={selected ? styles.nodeItemSelected : styles.nodeItem}
                              aria-pressed={selected}
                              aria-current={currentTask ? "step" : undefined}
                              aria-label={`${node.label}${currentTask ? "，当前任务" : selected ? "，正在查看" : ""}`}
                              data-current-task={currentTask ? "true" : "false"}
                              data-runtime-current={runtimeCurrent ? "true" : "false"}
                              data-testid={`research-process-rail-node-${node.nodeId}`}
                              onClick={() => onSelectNode(node.nodeId)}
                            >
                              <span className={styles.nodeCopy}>
                                <strong className={styles.nodeTitle}>{node.label}</strong>
                                <small className={styles.nodeDescription}>{description}</small>
                              </span>
                              <VStatusChip tone={nodeStatusTone(node)}>
                                {nodeStatusLabel(node, currentTask, runtimeCurrent)}
                              </VStatusChip>
                            </VNativeButton>
                          </li>
                        );
                      })}
                    </ul>
                  </li>
                );
              })}
            </ol>
          ) : (
            <p className={styles.empty}>流程定义加载后，阶段目录会显示在这里。</p>
          )}
        </section>
      </div>
    </nav>
  );
}
