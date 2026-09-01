import type { ReactNode } from "react";
import {
  VButton,
  VDropdownMenu,
  VSelect,
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
import type { HypothesisFirstStage } from "./hypothesisFirstNextAction";
import { getNodeAdapter } from "./nodeAdapterModel";
import {
  RESEARCH_STAGE_TERMS,
  RUN_TIMELINE_TERM,
} from "./researchTerminology";
import styles from "./ResearchWorkflowToolbar.styles";

type WorkflowPhase = {
  step: number | null;
  zh: string;
  en: string;
  currentNodeZh?: string;
  currentNodeEn?: string;
  stageZh?: string;
  stageEn?: string;
};

const HYPOTHESIS_FIRST_STAGE_PHASES: Partial<Record<HypothesisFirstStage, WorkflowPhase>> = {
  generation_missing: { step: 1, zh: "候选形成", en: "Candidate formation" },
  generation_running: { step: 1, zh: "候选形成", en: "Candidate formation" },
  generation_ready_to_summarize: { step: 1, zh: "候选形成", en: "Candidate formation" },
  generation_summarizing: { step: 1, zh: "候选形成", en: "Candidate formation" },
  generation_awaiting_approval: { step: 1, zh: "候选形成", en: "Candidate formation" },
  selection_required: { step: 2, zh: "假说选择", en: "Hypothesis selection" },
  review_running: { step: 3, zh: "团队评审", en: "Team review" },
  review_ready_to_summarize: { step: 3, zh: "团队评审", en: "Team review" },
  review_summarizing: { step: 3, zh: "团队评审", en: "Team review" },
  review_awaiting_approval: { step: 3, zh: "团队评审", en: "Team review" },
  next_review: { step: 3, zh: "团队评审", en: "Team review" },
  budget_exhausted: { step: 3, zh: "团队评审", en: "Team review" },
  collecting: { step: 4, zh: "资料搜集", en: "Evidence collection" },
  collection_recovery: { step: 4, zh: "资料搜集", en: "Evidence collection" },
  handoff_pending: { step: 4, zh: "资料搜集", en: "Evidence collection" },
};

/** The hypothesis-first chain has five fixed phases; step badges read X/5. */
const HYPOTHESIS_FIRST_PHASE_STEP_TOTAL = 5;

export function researchWorkflowPhase(
  navigationLabel?: string,
  runtimeCurrentNodeIds?: readonly string[] | null,
  formalRuntimeActive = true,
  nextActionStage?: HypothesisFirstStage,
): WorkflowPhase {
  const runtimeNode = formalRuntimeActive
    ? (runtimeCurrentNodeIds ?? [])
      .map((nodeId) => getNodeAdapter(String(nodeId || "").trim()))
      .find(Boolean)
    : null;
  if (runtimeNode) {
    const stage = RESEARCH_STAGE_TERMS[runtimeNode.stageId];
    return {
      step: null,
      zh: stage.zh,
      en: stage.en,
      stageZh: stage.zh,
      stageEn: stage.en,
      currentNodeZh: runtimeNode.label,
      currentNodeEn: runtimeNode.labelEn,
    };
  }
  // A converged hypothesis-first chain can exist before the formal workflow
  // run has a current node. The next-action stage is the authoritative state
  // in that case; do not turn the old navigation label into a misleading
  // "假说准备 · 5/5" progress marker.
  if (nextActionStage === "converged") {
    return {
      step: null,
      zh: "假说先行闭环已完成",
      en: "Hypothesis-first loop complete",
    };
  }
  // Structural stage mapping is authoritative whenever the hypothesis-first
  // chain provides one. The navigation-label ladder below stays only as a
  // fallback for callers without a stage, so label rewording can no longer
  // silently move the progress marker.
  const stagedPhase = nextActionStage ? HYPOTHESIS_FIRST_STAGE_PHASES[nextActionStage] : undefined;
  if (stagedPhase) {
    return stagedPhase;
  }
  const label = String(navigationLabel || "").trim();
  if (label.includes("假说收敛")) return { step: 5, zh: "假说收敛", en: "Convergence" };
  if (label.includes("资料搜集")) return { step: 4, zh: "资料搜集", en: "Evidence collection" };
  if (label.includes("假说选择")) return { step: 2, zh: "假说选择", en: "Hypothesis selection" };
  if (label.includes("候选")) return { step: 1, zh: "候选形成", en: "Candidate formation" };
  if (label.includes("评审") || label.includes("讨论") || label.includes("本轮")) {
    return { step: 3, zh: "团队评审", en: "Team review" };
  }
  return { step: null, zh: "流程进行中", en: "Workflow in progress" };
}

export function ResearchWorkflowToolbar(props: {
  identity: ExperimentChromeIdentity | null;
  runId: string;
  runStatus: string;
  experimentOptions: ExperimentSwitchOption[];
  panel: ResearchProcessPanel;
  /** A hypothesis-first chain may be active without a formal run id. */
  workflowActive?: boolean;
  navigationLabel?: string;
  runtimeCurrentNodeIds?: readonly string[] | null;
  formalRuntimeActive?: boolean;
  /** Authoritative hypothesis-first stage when no formal runtime node exists. */
  nextActionStage?: HypothesisFirstStage;
  /** Fail-closed scope transition state shown as read-only workflow health. */
  scopeMismatch?: boolean;
  statusMessage?: string;
  atCurrentTask?: boolean;
  /** Review-round progress for the hypothesis-first chain (K of budget). */
  chainRound?: { current: number; budget: number } | null;
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
  const isZh = lang === "zh";
  const runStatusBadge = researchRunStatusBadge(props.runStatus, lang);
  // Global "step X/5" progress for the pre-formal hypothesis-first chain. The
  // derivation yields a numbered step only while the chain is in progress;
  // formal-runtime nodes, a converged loop and unknown states return
  // step:null, keeping the badge off the top bar for delivered work.
  const workflowPhase = researchWorkflowPhase(
    props.navigationLabel,
    props.runtimeCurrentNodeIds,
    props.formalRuntimeActive ?? true,
    props.nextActionStage,
  );
  const phaseBadgeText = typeof workflowPhase.step === "number"
    ? (isZh
      ? `假说先行 · 第${workflowPhase.step}/${HYPOTHESIS_FIRST_PHASE_STEP_TOTAL}步 · ${workflowPhase.zh}`
      : `Hypothesis-first · Step ${workflowPhase.step}/${HYPOTHESIS_FIRST_PHASE_STEP_TOTAL} · ${workflowPhase.en}`)
    : null;
  const chainRoundText = props.chainRound
    ? (isZh
      ? `第${props.chainRound.current}轮/${props.chainRound.budget}`
      : `Round ${props.chainRound.current}/${props.chainRound.budget}`)
    : null;
  const selectedQuestionId = props.identity?.questionId || null;
  const emptySwitcherLabel = props.identity
    ? formatExperimentSwitchLabel(props.identity.questionId, props.identity.hypothesisSummary)
    : (isZh ? "尚未选择实验" : "No experiment selected");
  const detailItems = [
    { id: "progress", label: isZh ? "题目进度" : "Progress", onSelect: () => props.onOpenPanel("progress") },
    { id: "question", label: isZh ? "题目档案" : "Question archive", onSelect: () => props.onOpenPanel("question") },
    { id: "team", label: isZh ? "成员与讨论" : "Members", onSelect: () => props.onOpenPanel("team") },
    { id: "evidence", label: isZh ? "证据图谱" : "Evidence graph", onSelect: () => props.onOpenPanel("evidence") },
    { id: "agents", label: "Agent", onSelect: () => props.onOpenPanel("agents") },
    { id: "timeline", label: isZh ? RUN_TIMELINE_TERM.zh : RUN_TIMELINE_TERM.en, onSelect: () => props.onOpenPanel("timeline") },
  ];
  return (
    <VToolbar ariaLabel={isZh ? "科研流程" : "Research workflow"} wrap={false} className={styles.root}>
      <div className={styles.context}>
        {props.leading ? <div className={styles.leading}>{props.leading}</div> : null}
        <div className={styles.switcher}>
          {props.experimentOptions.length > 0 ? (
            <VSelect
              density="compact"
              aria-label={isZh ? "切换实验" : "Switch experiment"}
              placeholder={isZh ? "选择实验" : "Select experiment"}
              selectedKey={selectedQuestionId}
              options={props.experimentOptions.map((item) => ({
                id: item.questionId,
                label: item.label,
                description: item.description,
              }))}
              onSelectionChange={(key) => {
                if (key == null) return;
                props.onSelectExperiment(String(key));
              }}
            />
          ) : (
            <span className={styles.empty}>{emptySwitcherLabel}</span>
          )}
        </div>
      </div>
      <div className={styles.actions}>
        {phaseBadgeText ? (
          <VStatusChip
            tone="accent"
            role="status"
            data-testid="research-workflow-phase-badge"
            className={styles.trailing}
          >
            {chainRoundText ? `${phaseBadgeText} · ${chainRoundText}` : phaseBadgeText}
          </VStatusChip>
        ) : null}
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
            {runStatusBadge.label}
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
            {isZh ? "协作" : "Collaborate"}
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
