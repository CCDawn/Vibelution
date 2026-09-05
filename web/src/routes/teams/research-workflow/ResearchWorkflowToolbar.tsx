import { useState, type ReactNode } from "react";
import {
  VButton,
  VDropdownMenu,
  VCommandPalette,
  VStatusChip,
  VToolbar,
} from "../../../components/vui";
import { useShellI18n } from "../../../i18n/useShellI18n";
import {
  formatExperimentSwitchLabel,
  type ExperimentChromeIdentity,
  type ExperimentSwitchOption,
} from "./researchExperimentSwitchModel";
import type { ResearchProcessPanel } from "./researchProcessPanelSelection";
import {
  RUN_TIMELINE_TERM,
} from "./researchTerminology";
import styles from "./ResearchWorkflowToolbar.styles";

import type { ResearchWorkflowContext } from "./researchWorkflowContextModel";
import { STATUS_LABEL, STATUS_TONE } from "./researchTaskPresentation";

export function ResearchWorkflowToolbar(props: {
  context: ResearchWorkflowContext;
  identity: ExperimentChromeIdentity | null;
  runStatus: string;
  experimentOptions: ExperimentSwitchOption[];
  panel: ResearchProcessPanel;
  /** Fail-closed scope transition state shown as read-only workflow health. */
  scopeMismatch?: boolean;
  statusMessage?: string;
  /** Canonical count of human work items for the selected question. */
  awaitingHumanCount?: number;
  onNavigateCurrent?: () => void;
  onSelectExperiment: (questionId: string) => void;
  onOpenPanel: (panel: ResearchProcessPanel) => void;
  /** Workspace switcher (team) — same row as experiment, not a second chrome strip. */
  leading?: ReactNode;
  /** Opens the existing team communication surface from the workflow chrome. */
  onOpenTeamCommunication?: () => void;
  /** Selected-experiment actions supplied by their owning feature component. */
  experimentActions?: ReactNode;
}) {
  const { lang } = useShellI18n();
  const [pickerOpen, setPickerOpen] = useState(false);
  const isZh = lang === "zh";
  const runStatusBadge = researchRunStatusBadge(props.runStatus, lang);
  const selectedQuestionId = props.identity?.questionId || null;
  const emptySwitcherLabel = props.identity
    ? formatExperimentSwitchLabel(props.identity.questionId, props.identity.title)
    : (isZh ? "尚未选择实验" : "No experiment selected");
  const detailItems = [
    { id: "progress", label: isZh ? "题目进度" : "Progress", onSelect: () => props.onOpenPanel("progress") },
    { id: "question", label: isZh ? "题目档案" : "Question archive", onSelect: () => props.onOpenPanel("question") },
    { id: "team", label: isZh ? "成员与讨论" : "Members", onSelect: () => props.onOpenPanel("team") },
    { id: "evidence", label: isZh ? "证据图谱" : "Evidence graph", onSelect: () => props.onOpenPanel("evidence") },
    { id: "leaderboard", label: isZh ? "假说排行" : "Hypothesis leaderboard", onSelect: () => props.onOpenPanel("leaderboard") },
    { id: "agents", label: "Agent", onSelect: () => props.onOpenPanel("agents") },
    { id: "timeline", label: isZh ? RUN_TIMELINE_TERM.zh : RUN_TIMELINE_TERM.en, onSelect: () => props.onOpenPanel("timeline") },
  ];
  return (
    <VToolbar ariaLabel={isZh ? "科研流程" : "Research workflow"} wrap={false} className={styles.root}>
      <div className={styles.context}>
        {props.leading ? <div className={styles.leading}>{props.leading}</div> : null}
        <div className={styles.switcher}>
          {props.experimentOptions.length > 0 ? (
            <>
              <VButton density="compact" variant="secondary" aria-label={isZh ? "切换研究题目" : "Switch research question"} onClick={() => setPickerOpen(true)} className={styles.questionTrigger} title={emptySwitcherLabel}>{emptySwitcherLabel}</VButton>
              <VCommandPalette open={pickerOpen} onOpenChange={setPickerOpen}
                labels={{ searchPlaceholder: "搜索题号或题名", emptyTitle: "没有匹配的研究题目", hint: "方向键选择 · Enter 打开 · Esc 关闭" }}
                items={props.experimentOptions.map((item) => ({ id: item.questionId, label: item.label, detail: item.description, group: "研究题目", keywords: `${item.questionId} ${item.title}`, onRun: () => props.onSelectExperiment(item.questionId) }))}
              />
            </>
          ) : (
            <span className={styles.empty}>{emptySwitcherLabel}</span>
          )}
        </div>
      </div>
      <div className={styles.actions}>
        {props.context.currentTask ? <VStatusChip tone={STATUS_TONE[props.context.currentTask.status]} role="status" data-testid="research-current-task-status">当前任务：{props.context.currentTask.title} · {STATUS_LABEL[props.context.currentTask.status]}</VStatusChip> : null}
        {(props.awaitingHumanCount ?? 0) > 0 ? (
          <VButton
            type="button"
            density="compact"
            variant="secondary"
            onClick={props.onNavigateCurrent}
            isDisabled={!props.onNavigateCurrent}
            disabledReason={props.onNavigateCurrent ? undefined : (isZh ? "当前任务尚未就绪" : "The current task is not ready")}
            data-testid="research-awaiting-human-badge"
          >
            {isZh
              ? `待人工处理 ${props.awaitingHumanCount}`
              : `${props.awaitingHumanCount} awaiting human`}
          </VButton>
        ) : null}
        <VButton density="compact" variant="secondary" aria-pressed={props.panel === "node"} onClick={() => props.onOpenPanel("node")}>流程画布</VButton>
        <VButton density="compact" variant="secondary" aria-pressed={props.panel === "question"} onClick={() => props.onOpenPanel("question")}>题目档案</VButton>
        <VDropdownMenu
          aria-label={isZh ? "查看只读信息" : "View read-only information"}
          align="end"
          items={detailItems}
          trigger={<VButton type="button" density="compact" variant="secondary">{isZh ? "查看" : "View"}</VButton>}
        />
        {selectedQuestionId ? props.experimentActions : null}
        {runStatusBadge ? (
          <VStatusChip
            tone={runStatusBadge.tone}
            role="status"
            data-testid="research-run-status"
            className={styles.trailing}
          >
            {isZh ? "运行：" : "Run: "}{runStatusBadge.label}
          </VStatusChip>
        ) : null}
        {props.onOpenTeamCommunication ? (
          <VButton
            type="button"
            density="compact"
            variant="secondary"
            onClick={props.onOpenTeamCommunication}
            data-testid="research-open-team-communication"
          >
            {isZh ? "团队与讨论" : "Team discussion"}
          </VButton>
        ) : null}
        {props.scopeMismatch && props.statusMessage ? (
          <VStatusChip tone="warning" role="status" className={styles.trailing}>
            {props.statusMessage}
          </VStatusChip>
        ) : null}
      </div>
    </VToolbar>
  );
}

function researchRunStatusBadge(
  status: string | null | undefined,
  lang: "zh" | "en",
): { label: string; tone: "neutral" | "accent" | "success" | "warning" | "danger" } | null {
  const normalized = String(status || "").trim().toLowerCase();
  const isZh = lang === "zh";
  switch (normalized) {
    case "reconciliation_required":
      return { label: isZh ? "需要对账" : "Needs reconciliation", tone: "warning" };
    case "archived":
      return { label: isZh ? "已归档" : "Archived", tone: "neutral" };
    case "failed":
      return { label: isZh ? "运行失败" : "Run failed", tone: "danger" };
    case "cancelled":
    case "canceled":
      return { label: isZh ? "已取消" : "Cancelled", tone: "warning" };
    default:
      return null;
  }
}
