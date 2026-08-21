import type { ReactNode } from "react";

import { VButton, VStatusChip, type VStatusTone } from "../../../components/vui";
import type {
  ResearchWorkflowContext,
  ResearchWorkflowTaskStatus,
} from "./researchWorkflowContextModel";
import styles from "./ResearchCurrentTaskInspector.styles";

const STATUS_LABEL: Record<ResearchWorkflowTaskStatus, string> = {
  not_started: "未开始",
  running: "进行中",
  waiting_system: "系统处理中",
  waiting_user: "等待你确认",
  recoverable_error: "可以恢复",
  blocked: "已阻塞",
  completed: "已完成",
};

const STATUS_TONE: Record<ResearchWorkflowTaskStatus, VStatusTone> = {
  not_started: "neutral",
  running: "accent",
  waiting_system: "accent",
  waiting_user: "warning",
  recoverable_error: "danger",
  blocked: "danger",
  completed: "success",
};

function liveRole(status: ResearchWorkflowTaskStatus): "alert" | "status" {
  return status === "recoverable_error" || status === "blocked" ? "alert" : "status";
}

export type ResearchCurrentTaskInspectorProps = {
  context: ResearchWorkflowContext;
  children?: ReactNode;
  /** Command area stays outside the scroll container so the primary action is always perceptible. */
  footer?: ReactNode;
  onReturnCurrentTask?: () => void;
};

export function ResearchCurrentTaskInspector({
  context,
  children,
  footer,
  onReturnCurrentTask,
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
        <div className={styles.empty} role={context.loadState === "error" ? "alert" : "status"}>
          {message}
        </div>
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
    >
      <header className={styles.header}>
        <div className={styles.eyebrow}>{historyMode ? "历史回顾 · 只读" : "当前任务 · 唯一操作面"}</div>
        <div className={styles.titleRow}>
          <h2 className={styles.title}>{task.title}</h2>
          <VStatusChip tone={STATUS_TONE[task.status]}>{STATUS_LABEL[task.status]}</VStatusChip>
        </div>
        <div
          aria-live={liveRole(task.status) === "alert" ? "assertive" : "polite"}
          className={styles.detail}
          role={liveRole(task.status)}
        >
          {task.detail}
        </div>
        {task.progress ? <div className={styles.progress}>{task.progress.label}</div> : null}
        {historyMode ? (
          <div className={styles.historyNotice}>
            <div className={styles.historyCopy}>
              你正在查看历史节点。流程当前任务仍是“{task.title}”，历史内容不会改变流程进度。
            </div>
            <VButton type="button" density="compact" variant="secondary" onClick={onReturnCurrentTask}>
              返回当前任务
            </VButton>
          </div>
        ) : null}
      </header>
      <div className={styles.body} data-vui-region="current-task-body">
        {children}
      </div>
      {!historyMode && footer ? (
        <footer className={styles.footer} data-vui-region="current-task-action">
          {footer}
        </footer>
      ) : null}
    </section>
  );
}
