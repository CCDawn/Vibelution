import { AlertCircle, Bot, ExternalLink, RefreshCw } from "lucide-react";

import type {
  ResearchProjectAgentTaskKind,
  TeamResearchProjectAgentTask,
} from "../../../api/types";
import { VButton, VStatusChip, VTooltip, type VStatusTone } from "../../../components/vui";
import styles from "./ResearchProjectAgentTaskPanel.styles";

type Stage = "experiment" | "iteration";

type TaskDefinition = {
  taskKind: ResearchProjectAgentTaskKind;
  roleLabel: string;
};

const TASKS_BY_STAGE: Record<Stage, TaskDefinition[]> = {
  experiment: [
    {
      taskKind: "experiment_design",
      roleLabel: "实验规划",
    },
    {
      taskKind: "experiment_evidence_review",
      roleLabel: "实验证据",
    },
  ],
  iteration: [
    {
      taskKind: "iteration_decision",
      roleLabel: "迭代决策",
    },
    {
      taskKind: "version_governance",
      roleLabel: "版本治理",
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
  if (status === "completed") return "accent";
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
          const taskDetail = task
            ? `${task.sessionTitle} · 第 ${task.sessionAttempt} 次`
            : "尚未创建会话";
          return (
            <article className={styles.card} key={definition.taskKind}>
              <span className={styles.role}>
                <Bot size={15} aria-hidden="true" />
                {definition.roleLabel}
              </span>
              <div className={styles.controls}>
                <VTooltip content={taskDetail}>
                  <span>
                    <VStatusChip
                      className={styles.status}
                      tone={statusTone(task?.status || "")}
                    >
                      {task ? statusLabel(task.status) : "未启动"}
                    </VStatusChip>
                  </span>
                </VTooltip>
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
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
