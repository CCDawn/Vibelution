import { AlertCircle, Bot, ExternalLink, RefreshCw } from "lucide-react";

import type {
  ResearchProjectAgentTaskKind,
  TeamResearchProjectAgentTask,
} from "../../../api/types";
import { VButton, VStatusChip, type VStatusTone } from "../../../components/vui";
import styles from "./ResearchProjectAgentTaskPanel.styles";

type Stage = "experiment" | "iteration";

type TaskDefinition = {
  taskKind: ResearchProjectAgentTaskKind;
  roleLabel: string;
  description: string;
};

const TASKS_BY_STAGE: Record<Stage, TaskDefinition[]> = {
  experiment: [
    {
      taskKind: "experiment_design",
      roleLabel: "实验规划",
      description: "生成并修订可执行的实验设计。",
    },
    {
      taskKind: "experiment_evidence_review",
      roleLabel: "实验证据",
      description: "核对设计依据、结果证据与边界。",
    },
  ],
  iteration: [
    {
      taskKind: "iteration_decision",
      roleLabel: "迭代决策",
      description: "依据当前结果决定晋升、修订或停止。",
    },
    {
      taskKind: "version_governance",
      roleLabel: "版本治理",
      description: "登记版本关系、淘汰原因与审计线索。",
    },
  ],
};

const ACTIVE_STATUSES = new Set(["queued", "running", "in_progress"]);
const RETRYABLE_STATUSES = new Set(["failed", "blocked", "cancelled"]);

function latestTask(
  tasks: TeamResearchProjectAgentTask[],
  taskKind: ResearchProjectAgentTaskKind,
) {
  return tasks
    .filter((task) => task.taskKind === taskKind)
    .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt))[0] ?? null;
}

function statusLabel(status: string) {
  return ({
    queued: "排队中",
    running: "运行中",
    in_progress: "处理中",
    completed: "已完成",
    failed: "失败",
    blocked: "已阻塞",
    cancelled: "已取消",
  }[status] ?? status) || "未开始";
}

function statusTone(status: string): VStatusTone {
  if (ACTIVE_STATUSES.has(status)) return "accent";
  if (status === "completed") return "success";
  if (RETRYABLE_STATUSES.has(status)) return "warning";
  return "neutral";
}

export function ResearchProjectAgentTaskPanel(props: {
  stage: Stage;
  activeProjectId: string;
  tasks: TeamResearchProjectAgentTask[];
  isLoading: boolean;
  isStarting: boolean;
  startingTaskKind?: ResearchProjectAgentTaskKind | null;
  errorMessage?: string;
  onStartTask: (
    taskKind: ResearchProjectAgentTaskKind,
    options?: { formalRetry?: boolean; retryTaskId?: string },
  ) => Promise<void>;
  onOpenTask?: (task: TeamResearchProjectAgentTask) => void;
}) {
  const projectMissing = !props.activeProjectId;
  return (
    <section
      className={styles.root}
      aria-label={props.stage === "experiment" ? "实验设计 Agent 任务" : "执行迭代 Agent 任务"}
      data-testid={`research-project-agent-tasks-${props.stage}`}
    >
      <header className={styles.header}>
        <div>
          <span>Agent sessions</span>
          <h3>按职责进入平级实验会话</h3>
        </div>
        <span className={styles.count}>
          {props.isLoading ? "同步中" : `${TASKS_BY_STAGE[props.stage].length} 个职责`}
        </span>
      </header>
      {projectMissing ? (
        <p className={styles.projectWarning}>
          <AlertCircle size={15} aria-hidden="true" />
          请先选择研究项目，再启动 Agent 任务。
        </p>
      ) : null}
      {props.errorMessage ? (
        <p className={styles.error} role="alert">
          任务状态读取或启动失败，请重试。
        </p>
      ) : null}
      <div className={styles.grid}>
        {TASKS_BY_STAGE[props.stage].map((definition) => {
          const task = latestTask(props.tasks, definition.taskKind);
          const active = Boolean(task && ACTIVE_STATUSES.has(task.status));
          const retryable = Boolean(task && RETRYABLE_STATUSES.has(task.status));
          const starting = props.isStarting && props.startingTaskKind === definition.taskKind;
          return (
            <article className={styles.card} key={definition.taskKind}>
              <div className={styles.cardHeader}>
                <span className={styles.role}>
                  <Bot size={15} aria-hidden="true" />
                  {definition.roleLabel}
                </span>
                <VStatusChip
                  className={styles.status}
                  tone={statusTone(task?.status || "")}
                  style={{ minHeight: 22, fontSize: 10, fontWeight: 400, lineHeight: "15.8px" }}
                >
                  {task ? statusLabel(task.status) : "未启动"}
                </VStatusChip>
              </div>
              <p className={styles.description}>{definition.description}</p>
              {task ? (
                <div className={styles.session}>
                  <strong title={task.sessionTitle}>
                    {task.sessionTitle}
                  </strong>
                  <span>
                    第 {task.sessionAttempt} 次{task.retryOfSessionId ? " · 平级重试会话" : " · 当前实验会话"}
                  </span>
                </div>
              ) : null}
              <div className={styles.actions}>
                {active && task ? (
                  <VButton
                    type="button"
                    variant="primary"
                    density="compact"
                    icon={<ExternalLink size={14} />}
                    isDisabled={!props.onOpenTask}
                    onPress={() => props.onOpenTask?.(task)}
                  >
                    继续会话
                  </VButton>
                ) : (
                  <VButton
                    type="button"
                    variant="primary"
                    density="compact"
                    isDisabled={projectMissing || props.isLoading || props.isStarting}
                    onPress={() => {
                      void props.onStartTask(definition.taskKind).catch(() => undefined);
                    }}
                  >
                    {starting ? "启动中…" : task ? "继续任务" : "启动任务"}
                  </VButton>
                )}
                {retryable && task ? (
                  <VButton
                    type="button"
                    variant="secondary"
                    density="compact"
                    icon={<RefreshCw size={14} />}
                    isDisabled={projectMissing || props.isStarting}
                    onPress={() => {
                      void props.onStartTask(definition.taskKind, {
                        formalRetry: true,
                        retryTaskId: task.taskId,
                      }).catch(() => undefined);
                    }}
                  >
                    正式重试
                  </VButton>
                ) : null}
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
