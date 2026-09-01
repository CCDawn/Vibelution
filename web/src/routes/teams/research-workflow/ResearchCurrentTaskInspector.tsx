import type { ReactNode } from "react";

import { VButton, VStatusChip, type VStatusTone } from "../../../components/vui";
import type {
  ResearchWorkflowContext,
  ResearchWorkflowTaskStatus,
} from "./researchWorkflowContextModel";
import type { ResearchWorkflowSnapshot } from "../../../api/types/research-workflow/core";
import styles from "./ResearchCurrentTaskInspector.styles";

const STATUS_LABEL: Record<ResearchWorkflowTaskStatus, string> = {
  not_started: "未开始",
  running: "进行中",
  waiting_system: "处理中",
  waiting_user: "待确认",
  recoverable_error: "可恢复",
  blocked: "已阻塞",
  never_started: "从未启动",
  failed_to_dispatch: "启动失败",
  completed: "已完成",
};

const STATUS_TONE: Record<ResearchWorkflowTaskStatus, VStatusTone> = {
  not_started: "neutral",
  running: "accent",
  waiting_system: "accent",
  waiting_user: "warning",
  recoverable_error: "danger",
  blocked: "danger",
  never_started: "warning",
  failed_to_dispatch: "danger",
  completed: "success",
};

function liveRole(status: ResearchWorkflowTaskStatus): "alert" | "status" {
  return status === "recoverable_error"
    || status === "blocked"
    || status === "never_started"
    || status === "failed_to_dispatch"
    ? "alert"
    : "status";
}

export type ResearchCurrentTaskInspectorProps = {
  context: ResearchWorkflowContext;
  children?: ReactNode;
  /** Command area stays outside the scroll container so the primary action is always perceptible. */
  footer?: ReactNode;
  onReturnCurrentTask?: () => void;
  onRetryDispatch?: () => void;
  retryPending?: boolean;
  stageOne?: ResearchWorkflowSnapshot["stageOne"];
};

export function ResearchCurrentTaskInspector({
  context,
  children,
  footer,
  onReturnCurrentTask,
  onRetryDispatch,
  retryPending = false,
  stageOne,
}: ResearchCurrentTaskInspectorProps) {
  const task = context.currentTask;
  const historyMode = Boolean(
    task
    && context.view.panel === "node"
    && context.view.selectedNodeId
    && !context.view.selectedIsCurrentTask,
  );

  if (!task) {
    const message = context.loadState === "scope_mismatch"
      ? "正在切换题目，旧任务已隐藏"
      : context.loadState === "error"
        ? "当前任务暂时无法读取"
        : "正在读取当前任务";
    return (
      <section
        aria-label="当前任务操作"
        className={styles.root}
        data-vui="research-current-task-inspector"
        data-load-state={context.loadState}
      >
        <header className={styles.header} data-vui-region="current-task-header">
          <div className={styles.empty} role={context.loadState === "error" ? "alert" : "status"}>
            {message}
          </div>
        </header>
        <div className={styles.body} data-vui-region="current-task-body">
          {children}
        </div>
        <footer className={styles.footer} data-vui-region="current-task-action">
          {footer}
        </footer>
      </section>
    );
  }

  return (
    <section
      aria-label={historyMode ? "历史任务回顾" : "当前任务操作"}
      className={styles.root}
      data-vui="research-current-task-inspector"
      data-history-mode={historyMode ? "true" : "false"}
      data-current-task-key={task.key}
      data-task-status={task.status}
    >
      <header className={styles.header} data-vui-region="current-task-header">
        <div className={styles.titleRow}>
          <h2 className={styles.title}>{task.title}</h2>
          <VStatusChip tone={STATUS_TONE[task.status]}>{STATUS_LABEL[task.status]}</VStatusChip>
        </div>
      </header>
      <div className={styles.body} data-vui-region="current-task-body">
        <div
          aria-live={liveRole(task.status) === "alert" ? "assertive" : "polite"}
          className={styles.detail}
          role={liveRole(task.status)}
        >
          {historyMode ? `归档记录 · 当前仍是“${task.title}”` : task.detail}
        </div>
        {task.progress && !historyMode ? <div className={styles.progress}>{task.progress.label}</div> : null}
        {stageOne && !historyMode ? (
          <div className={styles.progress} data-testid="stage-one-topology-summary">
            {`正式执行图 ${stageOne.formalTopology.workflowVersionId || "未标版本"} · hf_* 仅为操作投影 · ${
              stageOne.knowledgeFlow.topology === "embedded" ? "知识节点在正式图内" : "知识补充为独立子流程"
            } · 终态以 Challenge Program 登记为准`}
          </div>
        ) : null}
        {children}
      </div>
      <footer className={styles.footer} data-vui-region="current-task-action">
        {historyMode ? (
          <VButton type="button" variant="primary" className={styles.primaryAction} onClick={onReturnCurrentTask}>
            返回当前任务
          </VButton>
        ) : (
          <>
            {task.retryAction && onRetryDispatch ? (
              <VButton
                type="button"
                variant="primary"
                isPending={retryPending}
                isDisabled={retryPending}
                onClick={onRetryDispatch}
              >
                {task.retryAction.label}
              </VButton>
            ) : null}
            {footer}
          </>
        )}
      </footer>
    </section>
  );
}
