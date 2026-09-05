import type { ReactNode } from "react";

import { VButton, VErrorSummary, VStatusChip } from "../../../components/vui";
import { presentResearchWorkflowError } from "../researchWorkflowErrorModel";
import type {
  ResearchWorkflowContext,
  ResearchWorkflowTaskStatus,
} from "./researchWorkflowContextModel";
import styles from "./ResearchCurrentTaskInspector.styles";

import { STATUS_LABEL, STATUS_TONE } from "./researchTaskPresentation";

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
  navigation?: ReactNode;
  /** Command area stays outside the scroll container so the primary action is always perceptible. */
  footer?: ReactNode;
  onReturnCurrentTask?: () => void;
  onRetryDispatch?: () => void;
  retryPending?: boolean;
  error?: string | null;
};

export function ResearchCurrentTaskInspector({
  context,
  children,
  navigation,
  footer,
  onReturnCurrentTask,
  onRetryDispatch,
  retryPending = false,
  error,
}: ResearchCurrentTaskInspectorProps) {
  const task = context.currentTask;
  const historyMode = Boolean(
    task
    && context.view.panel === "node"
    && context.view.selectedNodeId
    && !context.view.selectedIsCurrentTask,
  );

  if (!task) {
    const message = error ? "当前任务读取失败，请查看画布中的错误详情" : context.loadState === "scope_mismatch"
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
          <div className={styles.empty} role={error || context.loadState === "error" ? "alert" : "status"}>
            {message}
          </div>
          {navigation}
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

  const panelTitle = context.view.panel === "evidence" ? "题目证据图谱"
    : context.view.panel === "timeline" ? "运行记录"
    : context.view.panel === "team" ? "团队与讨论"
    : context.view.panel === "agents" ? "团队 Agent"
    : context.view.panel === "leaderboard" ? "题目假说排行" : null;
  const taskError = presentResearchWorkflowError(task.detail);
  return (
    <section
      aria-label={historyMode ? "所选节点详情" : "当前任务操作"}
      className={styles.root}
      data-vui="research-current-task-inspector"
      data-history-mode={historyMode ? "true" : "false"}
      data-current-task-key={task.key}
      data-task-status={task.status}
    >
      <header className={styles.header} data-vui-region="current-task-header">
        <div className={styles.titleRow}>
          <h2 className={styles.title}>{panelTitle ?? (historyMode ? "所选节点详情" : task.title)}</h2>
          {!historyMode && !panelTitle ? <VStatusChip tone={STATUS_TONE[task.status]}>{STATUS_LABEL[task.status]}</VStatusChip> : null}
        </div>
        {navigation}
      </header>
      <div className={styles.body} data-vui-region="current-task-body">
        <div
          aria-live={liveRole(task.status) === "alert" ? "assertive" : "polite"}
          className={styles.detail}
          role={liveRole(task.status)}
        >
          {panelTitle ? `${context.scope.questionId ?? "当前题目"} · 当前任务为“${task.title}”` : historyMode ? `所选节点详情 · 当前任务为“${task.title}”` : liveRole(task.status) === "alert" ? (
            <>
              <VErrorSummary
                label={STATUS_LABEL[task.status]}
                summary={taskError.titleZh}
                details={task.detail}
                openLabel="诊断"
                closeLabel="收起"
                defaultOpen={false}
              />
              <ul className={styles.errorSteps} aria-label="处理建议">
                {taskError.bodyZh.split("；").filter(Boolean).map((step, index) => <li key={index}>{step}</li>)}
              </ul>
            </>
          ) : task.detail}
        </div>
        {task.progress && !historyMode ? <div className={styles.progress}>{task.progress.label}</div> : null}
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
