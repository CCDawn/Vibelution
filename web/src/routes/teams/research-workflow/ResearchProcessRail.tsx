import type {
  VStatusTone,
  WorkflowCanvasNodeInput,
  WorkflowLayoutInput,
} from "../../../components/vui";
import { VButton, VNativeButton, VStatusChip, VSurface } from "../../../components/vui";
import type { HypothesisFirstNextAction } from "./hypothesisFirstNextAction";
import { getNodeAdapter } from "./nodeAdapterModel";
import styles from "./ResearchProcessRail.styles";

type Language = "zh" | "en";

const STAGE_LABELS: Record<string, { zh: string; en: string }> = {
  hypothesis_first: { zh: "假说先行", en: "Hypothesis first" },
  knowledge_collection: { zh: "知识搜集", en: "Knowledge collection" },
  experiment_design: { zh: "实验设计", en: "Experiment design" },
  execution_iteration: { zh: "执行迭代", en: "Execution & iteration" },
  unassigned: { zh: "其他节点", en: "Other nodes" },
};

// The workflow graph currently carries one description field, and that field
// is authored in Chinese. Keep the English rail copy independent from that
// payload so a translated node title is not followed by a duplicate title or
// a Chinese description.
const NODE_DESCRIPTION_EN: Record<string, string> = {
  source_finding: "Find relevant sources",
  source_extraction: "Extract evidence from sources",
  evidence_relations: "Connect evidence relationships",
  knowledge_ingestion: "Add knowledge to the workspace",
  knowledge_handoff: "Review and hand off the knowledge package",
  hypothesis_design: "Shape the working hypothesis",
  protocol_design: "Draft the experiment protocol",
  protocol_review: "Review the experiment protocol",
  protocol_freeze: "Lock the approved protocol",
  smoke_gate: "Run the smoke check before execution",
  controlled_run: "Run the controlled experiment",
  result_evaluation: "Evaluate the experiment results",
  iteration_decision: "Choose the next iteration",
  candidate_promotion: "Approve the candidate for promotion",
  result_package: "Package the final result",
};

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
  lang: Language;
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
  lang: Language,
): string {
  if (currentTask) return lang === "zh" ? "当前任务" : "Current task";
  if (runtimeCurrent) return lang === "zh" ? "运行位置" : "Runtime position";
  const labels = lang === "zh"
    ? {
        succeeded: "已完成",
        skipped: "已完成",
        running: "处理中",
        waiting_human: "待确认",
        failed: "失败",
        blocked: "已阻塞",
        ready: "可开始",
        stale: "待刷新",
        cancelled: "已取消",
      }
    : {
        succeeded: "Completed",
        skipped: "Skipped",
        running: "Processing",
        waiting_human: "Waiting for review",
        failed: "Failed",
        blocked: "Blocked",
        ready: "Ready",
        stale: "Needs refresh",
        cancelled: "Cancelled",
      };
  return labels[node.status as keyof typeof labels] || (lang === "zh" ? "未开始" : "Not started");
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

function nextStatus(nextAction: HypothesisFirstNextAction, lang: Language): { label: string; tone: VStatusTone } {
  const isZh = lang === "zh";
  if (nextAction.recovery || nextAction.stage === "collection_recovery" || nextAction.stage === "budget_exhausted") {
    return { label: isZh ? "需要处理" : "Needs attention", tone: "warning" };
  }
  if (nextAction.stage === "blocked") return { label: isZh ? "已阻塞" : "Blocked", tone: "danger" };
  if (nextAction.command) return { label: isZh ? "等待你操作" : "Waiting for your action", tone: "warning" };
  if (nextAction.statusMessage) return { label: isZh ? "系统处理中" : "Processing", tone: "accent" };
  if (nextAction.stage === "no_run") return { label: isZh ? "待开始" : "Not started", tone: "neutral" };
  return { label: isZh ? "当前任务" : "Current task", tone: "accent" };
}

function nextDetail(nextAction: HypothesisFirstNextAction, lang: Language): string {
  return nextAction.commandDetail
    || nextAction.recovery?.reason
    || nextAction.statusMessage
    || nextAction.disabledReason
    || (nextAction.stage === "no_run"
      ? (lang === "zh" ? "选择题目后，研究阶段和可操作任务会显示在这里。" : "Choose a question to see research stages and available tasks here.")
      : (lang === "zh" ? "从当前任务进入右侧操作面板。" : "Open the inspector from the current task."));
}

function stageStatusLabel(row: StageRow, currentStageId: string | null, lang: Language): string {
  if (row.stageId === currentStageId) return lang === "zh" ? "当前阶段" : "Current stage";
  if (row.tone === "attention") return lang === "zh" ? "需处理" : "Needs attention";
  if (row.tone === "active") return lang === "zh" ? "进行中" : "In progress";
  if (row.tone === "done") return lang === "zh" ? "已完成" : "Completed";
  return lang === "zh" ? "未开始" : "Not started";
}

function stageDisplayLabel(row: StageRow, lang: Language): string {
  return STAGE_LABELS[row.stageId]?.[lang] || row.label;
}

function nodeDisplayLabel(node: WorkflowCanvasNodeInput, lang: Language): string {
  if (lang === "zh") return node.label;
  return getNodeAdapter(node.nodeId)?.labelEn || node.label;
}

function nodeDisplayDescription(node: WorkflowCanvasNodeInput, lang: Language): string {
  if (lang === "zh") return node.description || node.label;
  return NODE_DESCRIPTION_EN[node.nodeId] || "Workflow step";
}

export function ResearchProcessRail({
  lang,
  graph,
  selectedNodeId,
  runtimeCurrentNodeIds,
  nextAction,
  onSelectNode,
  onNavigateCurrent,
}: ResearchProcessRailProps) {
  const isZh = lang === "zh";
  const rows = stageRows(graph);
  const currentTaskId = nextAction.targetNodeId;
  const currentNode = graph?.nodes.find((node) => node.nodeId === currentTaskId) ?? null;
  const currentStage = rows.find((row) => row.nodes.some((node) => node.nodeId === currentTaskId)) ?? null;
  const currentStatus = nextStatus(nextAction, lang);

  return (
    <nav
      className={styles.root}
      aria-label={isZh ? "研究阶段与任务" : "Research stages and tasks"}
      data-testid="research-process-rail"
      data-vui="research-process-rail"
    >
      <div className={styles.body}>
        <VSurface tone="panel" elevation="flat" padding="compact" className={styles.currentCard} data-testid="research-process-rail-current">
          <span className={styles.kicker}>{isZh ? "当前任务" : "Current task"}</span>
          <div className={styles.currentMeta}>
            <strong className={styles.currentTitle}>{currentNode ? nodeDisplayLabel(currentNode, lang) : nextAction.navigationLabel}</strong>
            <VStatusChip tone={currentStatus.tone}>{currentStatus.label}</VStatusChip>
          </div>
          {currentStage ? (
            <span className={styles.currentStage}>
              {isZh ? `第 ${currentStage.index} 阶段 · ${stageDisplayLabel(currentStage, lang)}` : `Stage ${currentStage.index} · ${stageDisplayLabel(currentStage, lang)}`}
            </span>
          ) : null}
          <p className={styles.currentDetail}>{nextDetail(nextAction, lang)}</p>
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
            {isZh ? "前往当前任务" : "Go to current task"}
          </VButton>
        </VSurface>

        <section className={styles.stageSection} aria-labelledby="research-process-rail-stage-heading">
          <h2 id="research-process-rail-stage-heading" className={styles.sectionLabel}>{isZh ? "研究阶段" : "Research stages"}</h2>
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
                      <strong className={styles.stageTitle}>{row.index.toString().padStart(2, "0")} · {stageDisplayLabel(row, lang)}</strong>
                      <VStatusChip tone={row.tone === "attention" ? "warning" : row.tone === "active" ? "accent" : row.tone === "done" ? "success" : "neutral"}>
                        {stageStatusLabel(row, currentStage?.stageId ?? null, lang)}
                      </VStatusChip>
                    </div>
                    <span className={styles.stageMeta}>{row.completed}/{row.total} {isZh ? "已完成" : "completed"}</span>
                    <ul className={styles.nodeList}>
                      {row.nodes.map((node) => {
                        const currentTask = node.nodeId === currentTaskId;
                        const runtimeCurrent = runtimeCurrentNodeIds.includes(node.nodeId);
                        const selected = node.nodeId === selectedNodeId;
                        const label = nodeDisplayLabel(node, lang);
                        const description = nodeDisplayDescription(node, lang);
                        const stateHint = currentTask
                          ? (isZh ? "，当前任务" : ", current task")
                          : selected
                            ? (isZh ? "，正在查看" : ", selected")
                            : "";
                        return (
                          <li key={node.nodeId}>
                            <VNativeButton
                              type="button"
                              className={selected ? styles.nodeItemSelected : styles.nodeItem}
                              aria-pressed={selected}
                              aria-current={currentTask ? "step" : undefined}
                              aria-label={`${label}${stateHint}`}
                              data-current-task={currentTask ? "true" : "false"}
                              data-runtime-current={runtimeCurrent ? "true" : "false"}
                              data-testid={`research-process-rail-node-${node.nodeId}`}
                              onClick={() => onSelectNode(node.nodeId)}
                            >
                              <span className={styles.nodeCopy}>
                                <strong className={styles.nodeTitle}>{label}</strong>
                                <small className={styles.nodeDescription}>{description}</small>
                              </span>
                              <VStatusChip tone={nodeStatusTone(node)}>
                                {nodeStatusLabel(node, currentTask, runtimeCurrent, lang)}
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
            <p className={styles.empty}>{isZh ? "流程定义加载后，阶段目录会显示在这里。" : "The stage directory will appear after the workflow definition loads."}</p>
          )}
        </section>
      </div>
    </nav>
  );
}
