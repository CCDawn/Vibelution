import type { ReactNode } from "react";
import {
  VButton,
  VSelect,
  VStatusChip,
  VTabs,
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
  onNavigateCurrent?: () => void;
  onSelectExperiment: (questionId: string) => void;
  onOpenPanel: (panel: ResearchProcessPanel) => void;
  /** Workspace switcher (team) — same row as experiment, not a second chrome strip. */
  leading?: ReactNode;
  /** Opens the existing team communication surface from the workflow chrome. */
  onOpenTeamCommunication?: () => void;
}) {
  const { lang } = useShellI18n();
  const isZh = lang === "zh";
  const workflowActive = props.workflowActive ?? Boolean(props.runId);
  const selectedQuestionId = props.identity?.questionId || null;
  const emptySwitcherLabel = props.identity
    ? formatExperimentSwitchLabel(props.identity.questionId, props.identity.hypothesisSummary)
    : (isZh ? "尚未选择实验" : "No experiment selected");
  const phase = researchWorkflowPhase(
    props.navigationLabel,
    props.runtimeCurrentNodeIds,
    props.formalRuntimeActive,
    props.nextActionStage,
  );
  const detailsPanel = (
    props.panel === "question"
    || props.panel === "agents"
    || props.panel === "timeline"
    || props.panel === "evidence"
    || props.panel === "team"
    || props.panel === "progress"
    || props.panel === "launch"
  ) ? props.panel : null;
  // Navigation tabs for the inspector pane: views only. Workflow mutations
  // stay in the fixed current-task inspector so users always advance in one place.
  const detailTabs = [
    { id: "progress", label: isZh ? "题目进度" : "Progress" },
    { id: "question", label: isZh ? "题目档案" : "Question archive" },
    { id: "team", label: isZh ? "成员与讨论" : "Members" },
    { id: "evidence", label: isZh ? "证据图谱" : "Evidence graph" },
    { id: "agents", label: "Agent" },
    { id: "timeline", label: isZh ? RUN_TIMELINE_TERM.zh : RUN_TIMELINE_TERM.en },
  ];
  const activeDetailTab = detailTabs.some((tab) => tab.id === detailsPanel)
    ? String(detailsPanel ?? "")
    : undefined;
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
        {workflowActive ? (
          <div className={styles.phase} data-vui="research-workflow-phase">
            {phase.stageZh && phase.currentNodeZh
              ? (isZh ? `${phase.stageZh} · ${phase.currentNodeZh}` : `${phase.stageEn} · ${phase.currentNodeEn}`)
              : phase.step === 3 && props.chainRound && props.chainRound.current > 0
                ? (isZh
                  ? `假说评审 · 第 ${Math.min(props.chainRound.current, props.chainRound.budget)}/${props.chainRound.budget} 轮`
                  : `Hypothesis review · round ${Math.min(props.chainRound.current, props.chainRound.budget)}/${props.chainRound.budget}`)
              : phase.step
                ? (isZh ? `假说准备 · ${phase.step}/5` : "Hypothesis prep · " + phase.step + "/5")
                : (isZh ? phase.zh : phase.en)}
          </div>
        ) : null}
      </div>
      <div className={styles.actions}>
        <VTabs
          density="compact"
          className={styles.details}
          listClassName="flex-nowrap overflow-x-auto"
          aria-label={isZh ? "检查器视图" : "Inspector views"}
          items={detailTabs}
          value={activeDetailTab}
          onValueChange={(key) => {
            props.onOpenPanel(key as ResearchProcessPanel);
          }}
        />
        {props.onOpenTeamCommunication ? (
          <VButton
            type="button"
            density="compact"
            variant="secondary"
            onClick={props.onOpenTeamCommunication}
            data-testid="research-open-team-communication"
          >
            {isZh ? "团队沟通" : "Team communication"}
          </VButton>
        ) : null}
        {workflowActive && props.atCurrentTask ? (
          // Position indicator, not a dead button: a disabled ghost labeled
          // 当前任务 reads as broken while adding no action (audit #7).
          <VStatusChip tone="accent" className={styles.trailing}>
            {isZh ? "当前任务" : "Current task"}
          </VStatusChip>
        ) : null}
        {workflowActive && !props.atCurrentTask ? (
          <VButton
            type="button"
            density="compact"
            variant="secondary"
            className={styles.trailing}
            isDisabled={!props.onNavigateCurrent}
            disabledReason={
              !props.onNavigateCurrent
                ? (isZh ? "当前任务导航尚未准备好，请稍后重试" : "Current-task navigation is not ready; try again shortly")
                : undefined
            }
            onClick={props.onNavigateCurrent}
          >
            {isZh ? "定位当前任务" : "Locate current task"}
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
